import sqlite3
import time
from datetime import datetime
from pathlib import Path
from .config import Config

DB_FILE = Config.DB_PATH

def get_connection():
    conn = sqlite3.connect(str(DB_FILE))
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    Config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # 警報事件表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cam_id TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                status TEXT NOT NULL,
                confidence REAL,
                edge_density REAL,
                snapshot_file TEXT,
                video_file TEXT,
                video_sec REAL,
                note TEXT
            )
        ''')

        # 24小時歷史狀態抽樣表（供前端圖表）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cam_id TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                status_code INTEGER NOT NULL,  -- 0:Clean, 1:Muddy, 2:Blocked, 3:Alert
                status TEXT NOT NULL,
                confidence REAL
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_hist_ts ON history (timestamp)')

        # TS 影片批次紀錄表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS video_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL UNIQUE,
                file_path TEXT NOT NULL,
                file_size INTEGER,
                recorded_at DATETIME,
                status TEXT DEFAULT "PENDING",  -- PENDING, PROCESSING, COMPLETED, FAILED
                total_sampled INTEGER DEFAULT 0,
                muddy_count INTEGER DEFAULT 0,
                uncovered_count INTEGER DEFAULT 0,
                processed_at DATETIME
            )
        ''')

        # 遷移檢查：若 video_records 無 uncovered_count 則自動新增
        cursor.execute("PRAGMA table_info(video_records)")
        cols = [c[1] for c in cursor.fetchall()]
        if "uncovered_count" not in cols:
            cursor.execute("ALTER TABLE video_records ADD COLUMN uncovered_count INTEGER DEFAULT 0")

        conn.commit()

def save_alert_event(cam_id, status, confidence, edge_density, snapshot_file="", video_file="", video_sec=0.0):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO alerts (cam_id, timestamp, status, confidence, edge_density, snapshot_file, video_file, video_sec)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            cam_id,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            status,
            float(confidence),
            float(edge_density),
            snapshot_file,
            video_file,
            float(video_sec)
        ))
        conn.commit()
        return cursor.lastrowid

def get_recent_alerts(limit=50):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM alerts ORDER BY id DESC LIMIT ?
        ''', (limit,))
        return [dict(row) for row in cursor.fetchall()]

def save_history_record(cam_id, status_code, status, confidence):
    with get_connection() as conn:
        cursor = conn.cursor()
        now_ts = int(time.time())
        cursor.execute('''
            INSERT INTO history (cam_id, timestamp, status_code, status, confidence)
            VALUES (?, ?, ?, ?, ?)
        ''', (cam_id, now_ts, status_code, status, float(confidence)))
        conn.commit()

def get_history_stats(hours=24):
    with get_connection() as conn:
        cursor = conn.cursor()
        since = int(time.time()) - (hours * 3600)
        cursor.execute('''
            SELECT timestamp, status_code, status, confidence 
            FROM history 
            WHERE timestamp >= ? 
            ORDER BY timestamp ASC
        ''', (since,))
        return [dict(row) for row in cursor.fetchall()]

def upsert_video_record(filename, file_path, file_size=0, status="PENDING"):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO video_records (filename, file_path, file_size, status, recorded_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(filename) DO UPDATE SET
                file_size=excluded.file_size,
                status=excluded.status
        ''', (filename, file_path, file_size, status, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()

def complete_video_record(filename, total_sampled, muddy_count, uncovered_count=0, status="COMPLETED"):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE video_records 
            SET total_sampled = ?, muddy_count = ?, uncovered_count = ?, status = ?, processed_at = ?
            WHERE filename = ?
        ''', (total_sampled, muddy_count, uncovered_count, status, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), filename))
        conn.commit()

def get_video_records(limit=30):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT v.*, 
                   (SELECT COUNT(*) FROM alerts a WHERE a.video_file = v.filename AND (a.status = 'MUDDY' OR a.status = 'ATTRIBUTED_MUDDY')) AS actual_muddy_count,
                   (SELECT COUNT(*) FROM alerts a WHERE a.video_file = v.filename AND a.status = 'UNCOVERED_TRUCK') AS actual_uncovered_count
            FROM video_records v 
            ORDER BY v.id DESC LIMIT ?
        ''', (limit,))
        rows = cursor.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            actual_muddy = d.get("actual_muddy_count", 0)
            actual_uncovered = d.get("actual_uncovered_count", 0)
            rec_muddy = d.get("muddy_count", 0) or 0
            rec_uncovered = d.get("uncovered_count", 0) or 0

            # 獨立拆分統計：
            # 1. 車斗未覆蓋次數
            final_uncovered = max(rec_uncovered, actual_uncovered)

            # 2. 路污次數（若歷史舊資料誤將車斗違規計入 rec_muddy，透過 alerts 實際分類校正隔離）
            if actual_uncovered > 0 and actual_muddy == 0 and rec_muddy == actual_uncovered:
                final_muddy = 0
            elif actual_muddy > 0:
                final_muddy = actual_muddy
            else:
                final_muddy = rec_muddy

            d["muddy_count"] = final_muddy
            d["uncovered_count"] = final_uncovered
            result.append(d)
        return result

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
