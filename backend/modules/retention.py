import os
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from ..config import Config
from ..database import get_connection

class DiskRetentionManager:
    """硬碟空間守護與舊影片自動輪替管理（FIFO Retention）"""
    def __init__(self, record_dir=r"D:\錄影\Record", min_free_gb=25.0, retention_days=14):
        self.record_dir = Path(record_dir)
        self.min_free_gb = float(min_free_gb)
        self.retention_days = int(retention_days)

    def get_disk_status(self):
        """取得錄影硬碟的容量狀況 (Total, Used, Free in GB & Percentage)"""
        target_path = self.record_dir if self.record_dir.exists() else Path("D:/")
        if not target_path.exists():
            target_path = Path("C:/")
        
        try:
            total, used, free = shutil.disk_usage(str(target_path))
            total_gb = round(total / (1024 ** 3), 1)
            used_gb = round(used / (1024 ** 3), 1)
            free_gb = round(free / (1024 ** 3), 1)
            used_pct = round((used / total) * 100, 1)
            return {
                "drive": str(target_path)[:2],
                "total_gb": total_gb,
                "used_gb": used_gb,
                "free_gb": free_gb,
                "used_pct": used_pct,
                "is_low_space": free_gb < self.min_free_gb
            }
        except Exception as e:
            print(f"[Retention] 讀取磁碟容量失敗: {e}")
            return {
                "drive": "D:", "total_gb": 0, "used_gb": 0, "free_gb": 0, "used_pct": 0, "is_low_space": False
            }

    def cleanup_old_records(self, force=False):
        """自動清理過期或空間不足時的無違規舊影片"""
        disk = self.get_disk_status()
        needs_cleanup = force or disk["is_low_space"]
        
        with get_connection() as conn:
            cursor = conn.cursor()
            
            # 1. 條件一：超過保存天數（例如 14 天）且無違規髒污的影片
            expire_date = (datetime.now() - timedelta(days=self.retention_days)).strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute('''
                SELECT id, filename, file_path, file_size 
                FROM video_records 
                WHERE status = 'COMPLETED' 
                  AND muddy_count = 0 
                  AND recorded_at < ?
                ORDER BY recorded_at ASC
            ''', (expire_date,))
            expired_files = cursor.fetchall()

            purged_count = 0
            freed_bytes = 0

            for row in expired_files:
                fpath = Path(row["file_path"])
                if fpath.exists():
                    try:
                        size = fpath.stat().st_size
                        fpath.unlink()
                        freed_bytes += size
                        purged_count += 1
                        print(f"[Retention] 刪除過期影片: {fpath.name}")
                    except Exception as e:
                        print(f"[Retention] 刪除失敗: {e}")
                
                cursor.execute("UPDATE video_records SET status = 'PURGED' WHERE id = ?", (row["id"],))

            conn.commit()

            # 2. 條件二：若磁碟空間依然小於閾值，由舊到新加速淘汰無違規影片
            disk = self.get_disk_status()
            if disk["is_low_space"]:
                print(f"[Retention] 硬碟空間仍不足 ({disk['free_gb']} GB < {self.min_free_gb} GB)，啟動 FIFO 緊急淘汰...")
                cursor.execute('''
                    SELECT id, filename, file_path, file_size 
                    FROM video_records 
                    WHERE status = 'COMPLETED' 
                      AND muddy_count = 0
                    ORDER BY recorded_at ASC 
                    LIMIT 20
                ''')
                fifo_files = cursor.fetchall()
                for row in fifo_files:
                    fpath = Path(row["file_path"])
                    if fpath.exists():
                        try:
                            size = fpath.stat().st_size
                            fpath.unlink()
                            freed_bytes += size
                            purged_count += 1
                            print(f"[Retention] FIFO 釋放空間，刪除: {fpath.name}")
                        except Exception as e:
                            pass
                    cursor.execute("UPDATE video_records SET status = 'PURGED' WHERE id = ?", (row["id"],))
                conn.commit()

        freed_mb = round(freed_bytes / (1024 * 1024), 1)
        if purged_count > 0:
            print(f"[Retention] 本次清理完成: 共清理 {purged_count} 支舊影片，釋放 {freed_mb} MB 空間。")
        return {"purged_count": purged_count, "freed_mb": freed_mb}
