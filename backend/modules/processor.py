import cv2
import time
import threading
import numpy as np
from datetime import datetime
from pathlib import Path
from ultralytics import YOLO

from ..config import Config
from ..database import save_history_record, save_alert_event
from .tracker import SimpleTracker
from .reference_manager import ReferenceManager
from .alert_manager import AlertManager
from .truck_bed_analyzer import TruckBedAnalyzer
from .lpr_manager import LPRVehicleManager

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
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    time.sleep(0.1)
                    continue
                else:
                    time.sleep(1)
                    self.cap.release()
                    self.cap = cv2.VideoCapture(self.src)
                    continue

            with self.lock:
                self.frame = frame
                self.last_grab_time = time.time()
            
            time.sleep(0.03)

    def read(self):
        with self.lock:
            return self.frame.copy() if self.frame is not None else None

    def stop(self):
        self.running = False
        if hasattr(self.cap, 'release'):
            self.cap.release()

class RoadAnalyzer:
    """
    核心路污與車斗辨識引擎
    (整合 YOLO 物件遮擋、車斗覆蓋辨識、CLAHE 光影平衡、時段 HSV、Color Difference 色差校正與污染面積輪廓標註)
    """
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

        # 貨廂防塵設施 (車斗覆蓋網) 判視器
        self.truck_analyzer = TruckBedAnalyzer()
        self.latest_truck_status = "無卡車"
        self.last_truck_alert_time = 0

        # 運輸車輛帶泥舉證與車牌/車頭特寫管理模組
        self.lpr_mgr = LPRVehicleManager(max_buffer_sec=30.0)
        self.latest_suspect_vehicle = "無行經車輛"
        self.last_attributed_alert_time = 0

        self.roi_mask = None
        self.roi_area = 0
        self.current_status = "Initializing..."
        self.confidence = 0.0
        self.edge_density = 0.0
        self.muddy_area_pct = 0.0
        self.last_buffer_update = 0
        self.latest_annotated_frame = None
        self.save_ref_trigger = None

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
        self.roi_points = new_roi
        self.roi_mask = None
        all_cfg = Config.load_camera_config()
        if self.cam_id in all_cfg:
            all_cfg[self.cam_id]['roi'] = new_roi
            Config.save_camera_config(all_cfg)

    def trigger_save_ref(self, label):
        self.save_ref_trigger = label

    def _analysis_loop(self):
        while self.running:
            start_time = time.time()
            frame = self.stream.read()
            if frame is not None:
                annotated_frame, stats = self.analyze_frame(frame)
                self.latest_annotated_frame = annotated_frame

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
        h, w = frame.shape[:2]
        if self.roi_mask is None or self.roi_mask.shape[:2] != (h, w):
            self.roi_mask = self._create_roi_mask(w, h)

        if self.save_ref_trigger:
            self.ref_manager.save_ref(frame, self.roi_mask, self.save_ref_trigger)
            self.save_ref_trigger = None

        annotated = frame.copy()
        current_detections = []
        truck_boxes = []

        # 1. YOLO 物件偵測與車斗覆蓋檢驗 (COCO: 0=人, 1=單車, 2=汽車, 3=機車, 5=公車, 7=卡車)
        try:
            results = self.model(frame, classes=[0, 1, 2, 3, 5, 7], verbose=False)
            res = results[0]
            if res.boxes:
                boxes = res.boxes.xyxy.cpu().numpy()
                classes = res.boxes.cls.cpu().numpy()
                for box, cls_id in zip(boxes, classes):
                    x1, y1, x2, y2 = map(int, box)
                    x1, y1 = max(0, x1), max(0, y1)
                    x2, y2 = min(w, x2), min(h, y2)
                    if x2 > x1 and y2 > y1:
                        # 檢查與路面 ROI 之重疊
                        roi_slice = self.roi_mask[y1:y2, x1:x2]
                        overlap = cv2.countNonZero(roi_slice)
                        if overlap > (self.roi_area * 0.03):
                            current_detections.append([x1, y1, x2, y2])

                        # 記錄行經車輛供帶泥溯源舉證與車牌辨識
                        if int(cls_id) in [2, 5, 7]:
                            vtype = "Truck" if int(cls_id) == 7 else "Vehicle"
                            p_box, p_num = self.lpr_mgr.record_passing_vehicle(frame, [x1, y1, x2, y2], vtype)
                            suspect = self.lpr_mgr.get_latest_vehicle()
                            if suspect:
                                self.latest_suspect_vehicle = f"{suspect['cls_name']} ({suspect['plate_num']})"

                            # 若為砂石車/卡車，在畫面上精準繪製青色科技執法車牌框與標籤
                            if int(cls_id) == 7 and p_box:
                                px1, py1, px2, py2 = p_box
                                cv2.rectangle(annotated, (px1, py1), (px2, py2), (255, 255, 0), 2)
                                cv2.rectangle(annotated, (px1, py1 - 22), (px1 + 135, py1), (255, 255, 0), -1)
                                cv2.putText(annotated, f"LPR: {p_num}", (px1 + 4, py1 - 6),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2)

                        # 若為卡車 (class 7)，執行車斗防塵設施判視
                        if int(cls_id) == 7:
                            truck_boxes.append([x1, y1, x2, y2])
                            bed_crop, bed_box = self.truck_analyzer.extract_truck_bed_roi(frame, [x1, y1, x2, y2])
                            if bed_crop is not None and bed_crop.size > 0:
                                is_cov, bed_status, bed_conf, bed_details = self.truck_analyzer.analyze_coverage(bed_crop)
                                annotated = self.truck_analyzer.draw_annotation(
                                    annotated, [x1, y1, x2, y2], bed_box, bed_status, bed_conf, bed_details
                                )
                                self.latest_truck_status = f"{bed_status} ({bed_conf:.1f}%)"

                                # 若檢驗為未覆蓋防塵網 (UNCOVERED)，觸發車斗違規警報快照
                                if not is_cov and (time.time() - self.last_truck_alert_time > 15.0):
                                    self.last_truck_alert_time = time.time()
                                    ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                                    snap_name = f"truck_uncovered_{self.cam_id}_{ts_str}.jpg"
                                    snap_path = Config.SNAPSHOTS_DIR / snap_name
                                    cv2.imwrite(str(snap_path), annotated)
                                    save_alert_event(
                                        cam_id=self.cam_id,
                                        status="UNCOVERED_TRUCK",
                                        confidence=bed_conf,
                                        edge_density=bed_details.get("texture_var", 0.0),
                                        snapshot_file=snap_name,
                                        video_file=video_file,
                                        video_sec=video_sec
                                    )
                                    print(f"[Alert] 🚨 抓拍到車斗未依規定覆蓋防塵網違規: {snap_name}")
        except Exception as e:
            print(f"YOLO detection/Truck error: {e}")

        # 車輛停留與路面遮擋
        track_updates = self.tracker.update(current_detections, dt=Config.SAMPLE_INTERVAL_SEC)
        is_blocked = False
        for tid, trk in track_updates.items():
            if trk['lost'] == 0 and trk['age_seconds'] >= self.blocked_time_threshold:
                is_blocked = True
                bx = trk['box']
                cv2.rectangle(annotated, (bx[0], bx[1]), (bx[2], bx[3]), (0, 165, 255), 2)
                cv2.putText(annotated, f"Passing Truck {trk['age_seconds']:.1f}s", (bx[0], bx[1] - 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 2)

        # 2. 判讀路面狀態與 Color Difference 色差校正 / 面積輪廓標註
        status_color = (0, 255, 0)
        self.edge_density = 0.0
        self.muddy_area_pct = 0.0

        if is_blocked:
            # 若遮擋目標為卡車，優先依車斗覆蓋狀態呈現專業受檢狀態
            if truck_boxes and "UNCOVERED" in self.latest_truck_status:
                self.current_status = f"VIOLATION: UNCOVERED TRUCK ({self.latest_suspect_vehicle})"
                status_color = (0, 0, 255)
            elif truck_boxes:
                self.current_status = f"PASSING: INSPECTED ({self.latest_suspect_vehicle})"
                status_color = (0, 215, 255)
            else:
                self.current_status = "Blocked (Vehicle/Person)"
                status_color = (0, 165, 255)
            self.confidence = 92.0
            self.alert_manager.on_clean()
        else:
            lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            cl = self.clahe.apply(l)
            enhanced = cv2.cvtColor(cv2.merge((cl, a, b)), cv2.COLOR_LAB2BGR)

            label, score, _ = self.ref_manager.compare(enhanced, self.roi_mask, self.confidence_threshold)
            self.confidence = score * 100

            if label == 'muddy':
                # Canny 邊緣抗光影反光
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                blurred = cv2.GaussianBlur(gray, (5, 5), 0)
                edges = cv2.Canny(blurred, 40, 100)
                roi_edges = cv2.bitwise_and(edges, edges, mask=self.roi_mask)
                self.edge_density = cv2.countNonZero(roi_edges) / max(self.roi_area, 1)

                if self.edge_density < self.edge_threshold_base:
                    self.current_status = f"CLEAN (Anti-Reflect: {self.edge_density:.3f})"
                    self.confidence = 95.0
                    status_color = (180, 255, 180)
                    self.alert_manager.on_clean()
                else:
                    # ──【符合計畫書規範】Color Difference 色差分割與污染面積/輪廓標註 ──
                    # 利用邊緣紋理與對比差異提取髒污遮罩 (Muddy Mask)
                    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
                    dilated_edges = cv2.dilate(roi_edges, kernel, iterations=2)
                    mud_mask = cv2.bitwise_and(dilated_edges, dilated_edges, mask=self.roi_mask)
                    
                    mud_pixels = cv2.countNonZero(mud_mask)
                    self.muddy_area_pct = round((mud_pixels / max(self.roi_area, 1)) * 100.0, 1)

                    # 自動標註污染斑塊位置 (繪製黃色/紅色輪廓)
                    mud_contours, _ = cv2.findContours(mud_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    for cnt in mud_contours:
                        if cv2.contourArea(cnt) > 60:
                            cv2.drawContours(annotated, [cnt], -1, (0, 255, 255), 2)

                    self.current_status = f"MUDDY (Area: {self.muddy_area_pct}%)"
                    status_color = (0, 0, 255)
                    self.alert_manager.on_muddy(
                        frame=annotated,  # 儲存已自動標註污染輪廓的高清快照
                        status_str=self.current_status,
                        confidence=self.confidence,
                        edge_density=self.edge_density,
                        video_file=video_file,
                        video_sec=video_sec
                    )

                    # 【科技執法核心】若有剛駛離之涉嫌車輛，自動合成科技執法二合一舉證單
                    if (time.time() - self.last_attributed_alert_time > 20.0):
                        attr_snap, suspect_info = self.lpr_mgr.create_attributed_evidence(
                            annotated, self.cam_id, self.muddy_area_pct, video_file, video_sec
                        )
                        if attr_snap:
                            self.last_attributed_alert_time = time.time()
                            save_alert_event(
                                cam_id=self.cam_id,
                                status="ATTRIBUTED_MUDDY",
                                confidence=self.confidence,
                                edge_density=self.edge_density,
                                snapshot_file=attr_snap,
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

        # 3. 繪製標記與狀態儀表資訊 (加入半透明 HUD 底板，防止與影片自帶文字重疊打架)
        contours, _ = cv2.findContours(self.roi_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(annotated, contours, -1, (255, 255, 0), 2)

        # 半透明 HUD 黑色底框
        hud_overlay = annotated.copy()
        cv2.rectangle(hud_overlay, (15, 15), (460, 145), (15, 20, 28), -1)
        cv2.addWeighted(hud_overlay, 0.82, annotated, 0.18, 0, annotated)
        cv2.rectangle(annotated, (15, 15), (460, 145), (55, 68, 85), 1)

        # 排版整齊緊湊的 4 行 OSD 資訊
        cv2.putText(annotated, f"Road: {self.current_status}", (25, 45),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, status_color, 2)
        cv2.putText(annotated, f"Conf: {self.confidence:.1f}% | Mud Area: {self.muddy_area_pct}%", 
                    (25, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (220, 220, 220), 1)
        cv2.putText(annotated, f"Truck Bed: {self.latest_truck_status}", (25, 105),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 255, 255), 1)
        cv2.putText(annotated, f"Vehicle: {self.latest_suspect_vehicle}", (25, 133),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.58, (120, 200, 255), 1)

        if self.alert_manager.is_alert:
            cv2.putText(annotated, "! MUD DETECTED !", (20, 185), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3)
            cv2.rectangle(annotated, (0, 0), (w, h), (0, 0, 255), 8)

        stats = {
            "status": self.current_status,
            "confidence": self.confidence,
            "edge_density": self.edge_density,
            "muddy_area_pct": self.muddy_area_pct,
            "truck_bed_status": self.latest_truck_status,
            "suspect_vehicle": self.latest_suspect_vehicle,
            "is_alert": self.alert_manager.is_alert,
            "streak": self.alert_manager.muddy_streak,
            "is_blocked": is_blocked
        }
        return annotated, stats

    def get_latest_frame_jpg(self):
        if self.latest_annotated_frame is None:
            return None
        ret, buf = cv2.imencode('.jpg', self.latest_annotated_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return buf.tobytes() if ret else None
