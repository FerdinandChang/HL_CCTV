import cv2
import time
import threading
import numpy as np
from datetime import datetime
from pathlib import Path
from ultralytics import YOLO

from ..config import Config
from ..database import save_history_record
from .tracker import SimpleTracker
from .reference_manager import ReferenceManager
from .alert_manager import AlertManager

class YOLOModelSingleton:
    _model = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls, model_path=Config.MODEL_PATH):
        if cls._model is None:
            with cls._lock:
                if cls._model is None:
                    print(f"[YOLO] 正在載入模型: {model_path} ...")
                    cls._model = YOLO(model_path)
                    print("[YOLO] 模型載入完成。")
        return cls._model

class CameraStream:
    """串流與影片讀取線程（支援 RTSP 斷線重連與測試影片自動迴圈）"""
    def __init__(self, src):
        self.src = src
        self.is_file = False
        if str(src).isdigit():
            self.src = int(src)
        elif isinstance(src, str) and (Path(src).exists() or src.endswith(('.ts', '.mp4', '.avi'))):
            self.is_file = True

        self.cap = cv2.VideoCapture(self.src)
        self.running = True
        self.lock = threading.Lock()
        self.frame = None
        self.last_grab_time = time.time()
        
        self.t = threading.Thread(target=self._worker, daemon=True)
        self.t.start()

    def _worker(self):
        while self.running:
            if not self.cap.isOpened():
                time.sleep(1)
                self.cap = cv2.VideoCapture(self.src)
                continue

            grabbed, frame = self.cap.read()
            if not grabbed:
                if self.is_file:
                    # 測試影片播放完畢，自動重頭播放（方便開發測試）
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    time.sleep(0.1)
                    continue
                else:
                    # RTSP 斷線重連
                    time.sleep(1)
                    self.cap.release()
                    self.cap = cv2.VideoCapture(self.src)
                    continue

            with self.lock:
                self.frame = frame
                self.last_grab_time = time.time()
            
            # 適度控制讀取幀率，避免吃滿 CPU
            time.sleep(0.03)

    def read(self):
        with self.lock:
            return self.frame.copy() if self.frame is not None else None

    def stop(self):
        self.running = False
        if hasattr(self.cap, 'release'):
            self.cap.release()

class RoadAnalyzer:
    """核心路污分析引擎"""
    def __init__(self, cam_id="cam_main"):
        self.cam_id = cam_id
        cameras_cfg = Config.load_camera_config()
        self.cfg = cameras_cfg.get(cam_id, {})
        
        self.source = self.cfg.get('source', Config.VIDEO_SOURCE)
        self.roi_points = self.cfg.get('roi', [[0.1, 0.5], [0.9, 0.5], [0.9, 0.95], [0.1, 0.95]])
        self.blocked_time_threshold = float(self.cfg.get('blocked_time_threshold', Config.BLOCKED_TIME_THRESHOLD))
        self.edge_threshold_base = float(self.cfg.get('edge_threshold', Config.EDGE_THRESHOLD_BASE))
        self.confidence_threshold = float(self.cfg.get('confidence_threshold', Config.CONFIDENCE_THRESHOLD))

        self.model = YOLOModelSingleton.get_instance(Config.MODEL_PATH)
        self.stream = CameraStream(self.source)
        self.ref_manager = ReferenceManager(cam_id)
        self.alert_manager = AlertManager(cam_id, self.cfg)
        self.tracker = SimpleTracker(max_lost=30, iou_thresh=0.3)
        self.clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

        self.roi_mask = None
        self.roi_area = 0
        self.current_status = "Initializing..."
        self.confidence = 0.0
        self.edge_density = 0.0
        self.last_buffer_update = 0
        self.latest_annotated_frame = None
        self.save_ref_trigger = None

        # 背景分析迴圈
        self.running = True
        self.worker_thread = threading.Thread(target=self._analysis_loop, daemon=True)
        self.worker_thread.start()

    def _create_roi_mask(self, w, h):
        mask = np.zeros((h, w), dtype=np.uint8)
        points = []
        for p in self.roi_points:
            points.append([int(p[0] * w), int(p[1] * h)])
        if points:
            pts = np.array(points, np.int32).reshape((-1, 1, 2))
            cv2.fillPoly(mask, [pts], 255)
        self.roi_area = cv2.countNonZero(mask)
        return mask

    def update_roi(self, new_roi):
        """前端動態更新 ROI 座標"""
        self.roi_points = new_roi
        self.roi_mask = None
        all_cfg = Config.load_camera_config()
        if self.cam_id in all_cfg:
            all_cfg[self.cam_id]['roi'] = new_roi
            Config.save_camera_config(all_cfg)

    def trigger_save_ref(self, label):
        """觸發截取當前畫面為參考樣本（手動教學）"""
        self.save_ref_trigger = label

    def _analysis_loop(self):
        """即時分析主迴圈（依據 SAMPLE_INTERVAL_SEC 進行抽幀）"""
        while self.running:
            start_time = time.time()
            frame = self.stream.read()
            if frame is not None:
                annotated_frame, stats = self.analyze_frame(frame)
                self.latest_annotated_frame = annotated_frame

                # 每 60 秒存一次 24H 歷史紀錄
                if time.time() - self.last_buffer_update > 60:
                    code = 0
                    if 'MUDDY' in self.current_status: code = 1
                    if 'Blocked' in self.current_status: code = 2
                    if self.alert_manager.is_alert: code = 3
                    save_history_record(self.cam_id, code, self.current_status, self.confidence)
                    self.last_buffer_update = time.time()

            elapsed = time.time() - start_time
            sleep_time = max(0.05, Config.SAMPLE_INTERVAL_SEC - elapsed)
            time.sleep(sleep_time)

    def analyze_frame(self, frame, video_file="", video_sec=0.0):
        """單幀核心分析管線（YOLO遮擋 + CLAHE + HSV比對 + Canny抗光影）"""
        h, w = frame.shape[:2]
        if self.roi_mask is None or self.roi_mask.shape[:2] != (h, w):
            self.roi_mask = self._create_roi_mask(w, h)

        # 處理手動樣本儲存觸發
        if self.save_ref_trigger:
            self.ref_manager.save_ref(frame, self.roi_mask, self.save_ref_trigger)
            self.save_ref_trigger = None

        annotated = frame.copy()
        current_detections = []

        # 1. YOLO 遮擋過濾 (COCO: 0=人, 1=自行車, 2=汽車, 3=機車, 5=公車, 7=卡車)
        try:
            results = self.model(frame, classes=[0, 1, 2, 3, 5, 7], verbose=False)
            res = results[0]
            if res.boxes and self.roi_area > 0:
                boxes = res.boxes.xyxy.cpu().numpy()
                for box in boxes:
                    x1, y1, x2, y2 = map(int, box)
                    x1, y1 = max(0, x1), max(0, y1)
                    x2, y2 = min(w, x2), min(h, y2)
                    if x2 > x1 and y2 > y1:
                        roi_slice = self.roi_mask[y1:y2, x1:x2]
                        overlap = cv2.countNonZero(roi_slice)
                        # 重疊超過 3% 判定為車輛遮擋 ROI
                        if overlap > (self.roi_area * 0.03):
                            current_detections.append([x1, y1, x2, y2])
        except Exception as e:
            print(f"YOLO detection error: {e}")

        # 更新追蹤器計算停留時間
        track_updates = self.tracker.update(current_detections, dt=Config.SAMPLE_INTERVAL_SEC)
        is_blocked = False
        for tid, trk in track_updates.items():
            if trk['lost'] == 0 and trk['age_seconds'] >= self.blocked_time_threshold:
                is_blocked = True
                bx = trk['box']
                cv2.rectangle(annotated, (bx[0], bx[1]), (bx[2], bx[3]), (0, 165, 255), 2)
                cv2.putText(annotated, f"Blocked {trk['age_seconds']:.1f}s", (bx[0], bx[1] - 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 2)

        # 2. 判讀路面狀態
        status_color = (0, 255, 0)
        self.edge_density = 0.0

        if is_blocked:
            self.current_status = "Blocked (Vehicle/Person)"
            self.confidence = 0.0
            status_color = (0, 165, 255)
            self.alert_manager.on_clean()
        else:
            # CLAHE 局部對比增強（消除陰影與高光）
            lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            cl = self.clahe.apply(l)
            enhanced = cv2.cvtColor(cv2.merge((cl, a, b)), cv2.COLOR_LAB2BGR)

            # HSV 直方圖比對
            label, score, _ = self.ref_manager.compare(enhanced, self.roi_mask, self.confidence_threshold)
            self.confidence = score * 100

            if label == 'muddy':
                # Canny 邊緣密度驗證（抗積水反光與純黑陰影）
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                blurred = cv2.GaussianBlur(gray, (5, 5), 0)
                edges = cv2.Canny(blurred, 40, 100)
                roi_edges = cv2.bitwise_and(edges, edges, mask=self.roi_mask)
                self.edge_density = cv2.countNonZero(roi_edges) / max(self.roi_area, 1)

                if self.edge_density < self.edge_threshold_base:
                    # 邊緣平滑無高頻紋理 -> 判定為水漬或反光，非泥濘
                    self.current_status = f"CLEAN (Anti-Reflect: {self.edge_density:.3f})"
                    self.confidence = 95.0
                    status_color = (180, 255, 180)
                    self.alert_manager.on_clean()
                else:
                    # 邊緣紋理豐富 -> 確認為泥土、砂石或輪痕
                    self.current_status = f"MUDDY (Edge: {self.edge_density:.3f})"
                    status_color = (0, 0, 255)
                    self.alert_manager.on_muddy(
                        frame=frame,
                        status_str=self.current_status,
                        confidence=self.confidence,
                        edge_density=self.edge_density,
                        video_file=video_file,
                        video_sec=video_sec
                    )
            elif label == 'clean':
                self.current_status = f"CLEAN ({self.confidence:.1f}%)"
                status_color = (0, 255, 0)
                self.alert_manager.on_clean()
            else:
                self.current_status = f"UNKNOWN ({self.confidence:.1f}%)"
                status_color = (128, 128, 128)
                self.alert_manager.on_clean()

        # 3. 繪製標記（ROI 輪廓與狀態文字）
        contours, _ = cv2.findContours(self.roi_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(annotated, contours, -1, (255, 255, 0), 2)
        cv2.putText(annotated, f"Status: {self.current_status}", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, status_color, 2)
        cv2.putText(annotated, f"Conf: {self.confidence:.1f}% | Streak: {self.alert_manager.muddy_streak}", 
                    (20, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (240, 240, 240), 2)

        if self.alert_manager.is_alert:
            cv2.putText(annotated, "! MUD DETECTED !", (20, 120), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3)
            cv2.rectangle(annotated, (0, 0), (w, h), (0, 0, 255), 8)

        stats = {
            "status": self.current_status,
            "confidence": self.confidence,
            "edge_density": self.edge_density,
            "is_alert": self.alert_manager.is_alert,
            "streak": self.alert_manager.muddy_streak,
            "is_blocked": is_blocked
        }
        return annotated, stats

    def get_latest_frame_jpg(self):
        """將最新分析影格編碼為 JPEG 回傳"""
        if self.latest_annotated_frame is None:
            return None
        ret, buf = cv2.imencode('.jpg', self.latest_annotated_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return buf.tobytes() if ret else None
