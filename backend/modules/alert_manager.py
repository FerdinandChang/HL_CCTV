import os
import cv2
import time
import requests
from datetime import datetime
from pathlib import Path
from ..config import Config
from ..database import save_alert_event

class AlertManager:
    def __init__(self, cam_id="cam_main", config_dict=None):
        self.cam_id = cam_id
        cfg = config_dict or {}
        self.muddy_streak = 0
        self.muddy_streak_threshold = int(cfg.get('muddy_streak_threshold', Config.MUDDY_STREAK_THRESHOLD))
        self.alert_cooldown = int(cfg.get('alert_cooldown', Config.ALERT_COOLDOWN_SEC))
        self.last_alert_time = 0.0
        self.is_alert = False
        self.snapshot_dir = Config.SNAPSHOTS_DIR
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

    def on_clean(self):
        """路面乾淨或受遮擋時重置 streak"""
        self.muddy_streak = 0
        self.is_alert = False

    def on_muddy(self, frame, status_str, confidence, edge_density, video_file="", video_sec=0.0):
        """路面判定為泥濘"""
        self.muddy_streak += 1
        print(f"[{self.cam_id}] Muddy Streak: {self.muddy_streak}/{self.muddy_streak_threshold}")

        if self.muddy_streak >= self.muddy_streak_threshold:
            self.is_alert = True
            now = time.time()
            if now - self.last_alert_time >= self.alert_cooldown:
                self.last_alert_time = now
                snapshot_name = self.save_snapshot(frame, status_str, confidence, edge_density)
                alert_id = save_alert_event(
                    cam_id=self.cam_id,
                    status=status_str,
                    confidence=confidence,
                    edge_density=edge_density,
                    snapshot_file=snapshot_name,
                    video_file=video_file,
                    video_sec=video_sec
                )
                print(f"[{self.cam_id}] !!! 觸發路污警報 (ID: {alert_id}, Snapshot: {snapshot_name}) !!!")
                self.send_notification(status_str, confidence, edge_density, snapshot_name)
                return True
        return False

    def save_snapshot(self, frame, status_str, confidence, edge_density):
        """存檔警報影格快照"""
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{self.cam_id}_{timestamp_str}_alert_muddy.jpg"
        filepath = self.snapshot_dir / filename
        
        # 在截圖上繪製告警資訊浮水印
        annotated = frame.copy()
        cv2.putText(annotated, f"MUD DETECTED - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", 
                    (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
        cv2.putText(annotated, f"Conf: {confidence:.1f}% | Edge: {edge_density:.3f}", 
                    (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
        
        cv2.imwrite(str(filepath), annotated)
        return filename

    def send_notification(self, status, confidence, edge_density, snapshot_file):
        """發送 LINE Notify 或其他通知（若設定了 Token）"""
        token = Config.LINE_CHANNEL_TOKEN
        if not token:
            return
        msg = f"\n⚠️ [HL_CCTV 路污警報]\n站點: {self.cam_id}\n狀態: {status}\n信心度: {confidence:.1f}%\n紋理密度: {edge_density:.3f}\n時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        try:
            headers = {"Authorization": f"Bearer {token}"}
            # 支援 LINE Notify 或 Messaging API
            requests.post("https://notify-api.line.me/api/notify", headers=headers, data={"message": msg}, timeout=5)
        except Exception as e:
            print(f"Failed to send LINE alert: {e}")
