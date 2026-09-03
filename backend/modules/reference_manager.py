import os
import cv2
import numpy as np
from datetime import datetime
from pathlib import Path
from ..config import Config

class ReferenceManager:
    """管理 clean 與 muddy 的參考樣本 (HSV Histogram + Image)"""
    def __init__(self, cam_id="cam_main"):
        self.cam_id = cam_id
        self.base_dir = Config.REFS_DIR / cam_id
        self.staging_dir = self.base_dir / "staging"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.refs = []
        self.staging = []
        self.load_refs()
        self.load_staging()

    def get_time_period(self):
        """依據當前小時回傳時段標籤"""
        h = datetime.now().hour
        if 5 <= h < 9: return "morning"
        if 9 <= h < 15: return "noon"
        if 15 <= h < 18: return "afternoon"
        return "night"

    def get_roi_hist(self, frame, mask):
        """計算 ROI 區域的 HSV 直方圖 (H:50, S:60 bins)"""
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], mask, [50, 60], [0, 180, 0, 256])
        cv2.normalize(hist, hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
        return hist

    def save_ref(self, frame, mask, label):
        """儲存當前畫面為正式參考樣本 (JPG + NPY)"""
        hist = self.get_roi_hist(frame, mask)
        timestamp = int(datetime.now().timestamp())
        period = self.get_time_period()
        file_id = f"{label}_{period}_{timestamp}"

        np.save(self.base_dir / f"{file_id}.npy", hist)
        roi_img = cv2.bitwise_and(frame, frame, mask=mask)
        cv2.imwrite(str(self.base_dir / f"{file_id}.jpg"), roi_img)

        self.refs.append({'label': label, 'hist': hist, 'id': file_id, 'period': period})
        print(f"[{self.cam_id}] 成功儲存參考樣本: {label} ({period})")
        return file_id

    def load_refs(self):
        """載入所有正式參考樣本"""
        self.refs = []
        if not self.base_dir.exists():
            return
        for f in os.listdir(self.base_dir):
            if f.endswith(".npy"):
                file_id = f[:-4]
                parts = file_id.split('_')
                label = parts[0]
                period = parts[1] if len(parts) >= 3 and parts[1] in ['morning', 'noon', 'afternoon', 'night'] else 'all'
                try:
                    hist = np.load(self.base_dir / f)
                    self.refs.append({'label': label, 'hist': hist, 'id': file_id, 'period': period})
                except Exception as e:
                    print(f"Error loading ref {f}: {e}")
        print(f"[{self.cam_id}] 已載入 {len(self.refs)} 個正式參考樣本。")

    def load_staging(self):
        """載入待審核暫存樣本"""
        self.staging = []
        if not self.staging_dir.exists():
            return
        for f in os.listdir(self.staging_dir):
            if f.endswith(".npy"):
                file_id = f[:-4]
                parts = file_id.split('_')
                label = parts[0]
                period = parts[1] if len(parts) >= 3 and parts[1] in ['morning', 'noon', 'afternoon', 'night'] else 'all'
                try:
                    hist = np.load(self.staging_dir / f)
                    self.staging.append({'label': label, 'hist': hist, 'id': file_id, 'period': period})
                except Exception:
                    pass

    def compare(self, frame, mask, confidence_threshold=0.3):
        """比對當前畫面與參考樣本庫，回傳最佳 Label、分數及詳細資訊"""
        if not self.refs:
            return "unknown", 0.0, {"reason": "No Reference Samples"}

        curr_hist = self.get_roi_hist(frame, mask)
        current_period = self.get_time_period()

        scores = {}
        for ref in self.refs:
            score = float(cv2.compareHist(curr_hist, ref['hist'], cv2.HISTCMP_CORREL))
            ref_period = ref.get('period', 'all')
            # 若非當前時段樣本，給予適當折扣以抵抗光影偏差
            if ref['label'] == 'clean' and ref_period != 'all' and ref_period != current_period:
                score *= 0.85
            
            label = ref['label']
            if label not in scores:
                scores[label] = []
            scores[label].append(score)

        summary_scores = {k: max(v) for k, v in scores.items() if v}
        if not summary_scores:
            return "unknown", 0.0, {}

        best_label = max(summary_scores, key=summary_scores.get)
        best_score = summary_scores[best_label]

        if best_score < confidence_threshold:
            return "unknown", best_score, summary_scores

        return best_label, best_score, summary_scores

    def get_ref_list(self):
        """回傳樣本清單供前端展示"""
        result = []
        for r in self.refs:
            jpg_name = f"{r['id']}.jpg"
            result.append({
                "id": r["id"],
                "label": r["label"],
                "period": r.get("period", "all"),
                "image_url": f"/api/refs/{self.cam_id}/{jpg_name}"
            })
        return result

    def delete_ref(self, ref_id):
        self.refs = [r for r in self.refs if r['id'] != ref_id]
        npy_path = self.base_dir / f"{ref_id}.npy"
        jpg_path = self.base_dir / f"{ref_id}.jpg"
        if npy_path.exists(): npy_path.unlink()
        if jpg_path.exists(): jpg_path.unlink()
        return True
