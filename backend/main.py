import io
import csv
import time
import threading
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, HTTPException, Response, Request, Query
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional

from .config import Config
from .database import init_db, get_recent_alerts, get_history_stats, get_video_records, get_connection
from .modules.processor import RoadAnalyzer
from .modules.watcher import TSVideoWatcher
from .modules.retention import DiskRetentionManager

app = FastAPI(title="HL_CCTV 工地路污判視系統", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化資料庫
init_db()

# 載入所有相機配置
cameras_cfg = Config.load_camera_config()
analyzers = {}
for cam_id in cameras_cfg:
    analyzers[cam_id] = RoadAnalyzer(cam_id)

# 啟動錄影檔監聽
watcher = TSVideoWatcher(analyzers, r"D:\錄影\Record")

# 啟動硬碟空間守護器
retention_mgr = DiskRetentionManager(r"D:\錄影\Record", min_free_gb=25.0, retention_days=14)

def retention_daemon_loop():
    """定時每小時巡檢一次硬碟容量"""
    while True:
        try:
            retention_mgr.cleanup_old_records()
        except Exception as e:
            print(f"[Retention Daemon Error] {e}")
        time.sleep(3600)

threading.Thread(target=retention_daemon_loop, daemon=True).start()

class ROIUpdateRequest(BaseModel):
    cam_id: Optional[str] = "cam_10"
    roi: List[List[float]]

class SaveRefRequest(BaseModel):
    cam_id: Optional[str] = "cam_10"
    label: str

@app.get("/api/cameras")
def get_cameras():
    cfg = Config.load_camera_config()
    return [{"id": k, "name": v.get("name", k)} for k, v in cfg.items()]

@app.get("/api/status")
def get_current_status(cam_id: str = "cam_10"):
    analyzer = analyzers.get(cam_id, list(analyzers.values())[0])
    return {
        "cam_id": analyzer.cam_id,
        "name": analyzer.cfg.get("name", analyzer.cam_id),
        "status": analyzer.current_status,
        "confidence": round(analyzer.confidence, 1),
        "edge_density": round(analyzer.edge_density, 3),
        "is_alert": analyzer.alert_manager.is_alert,
        "streak": analyzer.alert_manager.muddy_streak,
        "streak_threshold": analyzer.alert_manager.muddy_streak_threshold,
        "video_source": analyzer.source,
        "sample_interval": Config.SAMPLE_INTERVAL_SEC
    }

@app.get("/api/stream/live")
def get_live_stream(cam_id: str = "cam_10"):
    analyzer = analyzers.get(cam_id, list(analyzers.values())[0])
    def frame_generator():
        while True:
            frame_bytes = analyzer.get_latest_frame_jpg()
            if frame_bytes:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            time.sleep(0.1)

    return StreamingResponse(
        frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

@app.get("/api/roi")
def get_roi(cam_id: str = "cam_10"):
    analyzer = analyzers.get(cam_id, list(analyzers.values())[0])
    return {"cam_id": analyzer.cam_id, "roi": analyzer.roi_points}

@app.post("/api/roi")
def update_roi(req: ROIUpdateRequest):
    cam_id = req.cam_id or "cam_10"
    analyzer = analyzers.get(cam_id, list(analyzers.values())[0])
    if len(req.roi) < 3:
        raise HTTPException(status_code=400, detail="ROI 至少需包含 3 個頂點")
    analyzer.update_roi(req.roi)
    return {"success": True, "cam_id": analyzer.cam_id, "roi": analyzer.roi_points}

@app.post("/api/refs/save")
def save_reference_sample(req: SaveRefRequest):
    cam_id = req.cam_id or "cam_10"
    analyzer = analyzers.get(cam_id, list(analyzers.values())[0])
    if req.label not in ["clean", "muddy"]:
        raise HTTPException(status_code=400, detail="標籤必須為 clean 或 muddy")
    analyzer.trigger_save_ref(req.label)
    return {"success": True, "message": f"已排程為 {analyzer.cam_id} 存為 {req.label} 樣本"}

@app.get("/api/refs")
def list_reference_samples(cam_id: str = "cam_10"):
    analyzer = analyzers.get(cam_id, list(analyzers.values())[0])
    return {"refs": analyzer.ref_manager.get_ref_list()}

@app.delete("/api/refs/{cam_id}/{ref_id}")
def delete_reference_sample(cam_id: str, ref_id: str):
    analyzer = analyzers.get(cam_id, list(analyzers.values())[0])
    success = analyzer.ref_manager.delete_ref(ref_id)
    return {"success": success}

@app.get("/api/refs/{cam_id}/{filename}")
def get_ref_image(cam_id: str, filename: str):
    file_path = Config.REFS_DIR / cam_id / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="樣本圖片不存在")
    return FileResponse(str(file_path))

@app.get("/api/alerts")
def list_alerts(limit: int = 50):
    return {"alerts": get_recent_alerts(limit)}

@app.get("/api/snapshots/{filename}")
def get_snapshot_image(filename: str):
    file_path = Config.SNAPSHOTS_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="快照不存在")
    return FileResponse(str(file_path))

@app.get("/api/history")
def get_history():
    return {"history": get_history_stats(hours=24)}

@app.get("/api/videos")
def list_video_records(limit: int = 30):
    return {"videos": get_video_records(limit)}

@app.post("/api/videos/scan")
def trigger_scan_videos():
    watcher.scan_historical_records()
    return {"success": True, "message": "已觸發錄影目錄重新掃描"}

# ── 硬碟空間與儲存管理 API ───────────────────────────────────────
@app.get("/api/disk_usage")
def get_disk_usage():
    """取得錄影儲存硬碟空間狀況"""
    return retention_mgr.get_disk_status()

@app.post("/api/retention/cleanup")
def manual_cleanup_retention():
    """手動觸發清理過期無違規影片"""
    result = retention_mgr.cleanup_old_records(force=True)
    return {"success": True, **result}

# ── 報表匯出 API (Excel 相容 CSV) ─────────────────────────────────
@app.get("/api/reports/export")
def export_alerts_report(days: int = 7):
    """匯出最近 N 天的路污違規事件報表 (CSV 格式，UTF-8 BOM)"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, cam_id, timestamp, status, confidence, edge_density, snapshot_file, video_file, video_sec
            FROM alerts
            ORDER BY id DESC
        ''')
        rows = cursor.fetchall()

    output = io.StringIO()
    # 寫入 UTF-8 BOM 避免 Excel 開啟繁體中文亂碼
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow(["事件編號", "相機名稱", "發生時間", "判定狀態", "信心度(%)", "紋理密度", "快照檔名", "對應錄影檔", "影片內秒數"])
    for r in rows:
        cam_name = "出入口 (10.0.0.10)" if r["cam_id"] == "cam_10" else "外圍車道 (10.0.0.11)"
        writer.writerow([
            r["id"],
            cam_name,
            r["timestamp"],
            r["status"],
            r["confidence"],
            r["edge_density"],
            r["snapshot_file"],
            r["video_file"] or "--",
            round(r["video_sec"], 1) if r["video_sec"] else "--"
        ])

    csv_data = output.getvalue().encode("utf-8-sig")
    filename = f"HL_CCTV_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

frontend_dir = Config.PROJECT_ROOT / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.getenv("PORT", 8088))
    uvicorn.run("backend.main:app", host="0.0.0.0", port=port, reload=False)
