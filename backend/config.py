import json
import os
from pathlib import Path
from dotenv import load_dotenv

# 專案路徑
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

class Config:
    PROJECT_ROOT = BASE_DIR
    BACKEND_DIR = BASE_DIR / "backend"
    DATA_DIR = BASE_DIR / "data"
    REFS_DIR = DATA_DIR / "refs"
    OUTPUT_DIR = BASE_DIR / "output"
    SNAPSHOTS_DIR = OUTPUT_DIR / "snapshots"
    TEST_MEDIA_DIR = BASE_DIR / "test_media"
    
    # 錄影存放路徑（可由 .env 覆寫）
    RECORD_DIR = Path(os.getenv("RECORD_DIR", r"D:\錄影\record"))
    
    # 影像來源：可以是 RTSP 網址、測試影片路徑 (如 D:/HL_CCTV/test_media/sample.ts)、或 WebCam index
    VIDEO_SOURCE = os.getenv("VIDEO_SOURCE", str(TEST_MEDIA_DIR / "sample.ts"))
    
    # 執行模式: "live" (串流即時分析), "watch" (監控 RECORD_DIR 的 .ts 檔案), "both"
    RUN_MODE = os.getenv("RUN_MODE", "live")

    # 模型權重路徑
    MODEL_PATH = str(BACKEND_DIR / "models" / "yolo11n-seg.pt")
    if not Path(MODEL_PATH).exists():
        MODEL_PATH = "yolo11n-seg.pt"  # fallback

    # 資料庫路徑
    DB_PATH = DATA_DIR / "hl_cctv.db"
    CONFIG_FILE = BACKEND_DIR / "cameras.json"

    # 分析演算法參數
    SAMPLE_INTERVAL_SEC = float(os.getenv("SAMPLE_INTERVAL_SEC", 2.0))
    MUDDY_STREAK_THRESHOLD = int(os.getenv("MUDDY_STREAK_THRESHOLD", 3))
    BLOCKED_TIME_THRESHOLD = float(os.getenv("BLOCKED_TIME_THRESHOLD", 3.0))
    EDGE_THRESHOLD_BASE = float(os.getenv("EDGE_THRESHOLD", 0.025))
    CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", 0.3))
    ALERT_COOLDOWN_SEC = int(os.getenv("ALERT_COOLDOWN_SEC", 300))  # 5分鐘

    # LINE Messaging API / Notify
    LINE_CHANNEL_TOKEN = os.getenv("LINE_CHANNEL_TOKEN", "")
    LINE_USER_ID = os.getenv("LINE_USER_ID", "")

    # 確保目錄存在
    REFS_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    TEST_MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def load_camera_config(cls):
        """載入相機與 ROI 配置"""
        default_cfg = {
            "cam_main": {
                "name": "營建站洗車與出入口",
                "source": cls.VIDEO_SOURCE,
                "roi": [
                    [0.1, 0.5],
                    [0.9, 0.5],
                    [0.9, 0.95],
                    [0.1, 0.95]
                ],
                "start_time": "07:00",
                "end_time": "19:00",
                "muddy_streak_threshold": cls.MUDDY_STREAK_THRESHOLD,
                "blocked_time_threshold": cls.BLOCKED_TIME_THRESHOLD,
                "edge_threshold": cls.EDGE_THRESHOLD_BASE,
                "alert_cooldown": cls.ALERT_COOLDOWN_SEC
            }
        }
        if not cls.CONFIG_FILE.exists():
            cls.save_camera_config(default_cfg)
            return default_cfg
        try:
            with open(cls.CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default_cfg

    @classmethod
    def save_camera_config(cls, data):
        with open(cls.CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
