import os
import cv2
import time
import queue
import threading
from pathlib import Path

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False

from ..config import Config
from ..database import upsert_video_record, complete_video_record

if HAS_WATCHDOG:
    class TSFileHandler(FileSystemEventHandler):
        def __init__(self, watcher):
            self.watcher = watcher

        def on_created(self, event):
            if not event.is_directory and event.src_path.lower().endswith('.ts'):
                self.watcher.on_new_ts_file(event.src_path)

        def on_modified(self, event):
            if not event.is_directory and event.src_path.lower().endswith('.ts'):
                self.watcher.on_new_ts_file(event.src_path)

class TSVideoWatcher:
    r"""監控 D:\錄影\Record 下各鏡頭子目錄中的 .ts 檔案並批次抽幀分析"""
    def __init__(self, analyzer_dict, record_dir=r"D:\錄影\Record"):
        self.analyzers = analyzer_dict if isinstance(analyzer_dict, dict) else {"cam_main": analyzer_dict}
        self.record_dir = Path(record_dir)
        self.file_queue = queue.Queue()
        self.processing_files = set()
        self.running = True

        # 啟動佇列處理線程
        self.worker_thread = threading.Thread(target=self._queue_worker, daemon=True)
        self.worker_thread.start()

        if HAS_WATCHDOG:
            self.observer = Observer()
            if self.record_dir.exists():
                # 遞迴監控各相機子目錄
                self.observer.schedule(TSFileHandler(self), str(self.record_dir), recursive=True)
                self.observer.start()
                print(f"[TS Watcher] 已遞迴監控錄影目錄: {self.record_dir}")
        else:
            print("[TS Watcher] 啟動原生遞迴 Polling 監控線程。")
            self.poll_thread = threading.Thread(target=self._polling_loop, daemon=True)
            self.poll_thread.start()

    def _polling_loop(self):
        known_files = set()
        while self.running:
            if self.record_dir.exists():
                try:
                    current_files = set(str(f) for f in self.record_dir.rglob("*.ts"))
                    for f in current_files:
                        if f not in known_files:
                            known_files.add(f)
                            self.on_new_ts_file(f)
                except Exception:
                    pass
            time.sleep(3.0)

    def on_new_ts_file(self, file_path):
        path_str = str(file_path)
        if path_str.endswith(".temp"):
            return  # 忽略寫入中的暫存檔
        if path_str not in self.processing_files:
            self.processing_files.add(path_str)
            threading.Thread(target=self._wait_for_stability_and_enqueue, args=(path_str,), daemon=True).start()

    def _wait_for_stability_and_enqueue(self, file_path):
        p = Path(file_path)
        last_size = -1
        stable_count = 0
        
        while self.running:
            if not p.exists():
                self.processing_files.discard(file_path)
                return
            try:
                curr_size = p.stat().st_size
                if curr_size > 0 and curr_size == last_size:
                    stable_count += 1
                    if stable_count >= 3:
                        upsert_video_record(p.name, str(p), curr_size, status="QUEUED")
                        self.file_queue.put(str(p))
                        print(f"[TS Watcher] 檔案就緒進佇列: {p.name} ({curr_size / (1024*1024):.1f} MB)")
                        return
                else:
                    stable_count = 0
                    last_size = curr_size
            except Exception:
                pass
            time.sleep(1.0)

    def _queue_worker(self):
        while self.running:
            try:
                file_path = self.file_queue.get(timeout=2.0)
            except queue.Empty:
                continue

            try:
                self._process_single_ts(file_path)
            except Exception as e:
                print(f"[TS Watcher] 處理失敗 {file_path}: {e}")
            finally:
                self.processing_files.discard(file_path)
                self.file_queue.task_done()

    def _process_single_ts(self, file_path):
        p = Path(file_path)
        print(f"[TS Watcher] 開始抽幀分析: {p.name}")
        upsert_video_record(p.name, str(p), p.stat().st_size, status="PROCESSING")

        # 根據目錄路徑判斷相機 ID (10.0.0.10 -> cam_10, 10.0.0.11 -> cam_11)
        target_cam = "cam_10" if "10.0.0.10" in str(p) else ("cam_11" if "10.0.0.11" in str(p) else "cam_10")
        analyzer = self.analyzers.get(target_cam, list(self.analyzers.values())[0])

        cap = cv2.VideoCapture(str(p))
        if not cap.isOpened():
            upsert_video_record(p.name, str(p), status="FAILED")
            return

        fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
        sample_interval = Config.SAMPLE_INTERVAL_SEC
        step_frames = max(1, int(fps * sample_interval))

        frame_idx = 0
        total_sampled = 0
        muddy_count = 0

        while self.running:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % step_frames == 0:
                video_sec = frame_idx / fps
                _, stats = analyzer.analyze_frame(frame, video_file=p.name, video_sec=video_sec)
                total_sampled += 1
                # 統計所有違規事件 (包含道路泥污、車斗未覆蓋防塵設施)
                stat_str = stats.get("status", "")
                t_stat = stats.get("truck_bed", "")
                if "MUDDY" in stat_str or "UNCOVERED" in t_stat or "VIOLATION" in stat_str:
                    muddy_count += 1

            frame_idx += 1

        cap.release()
        complete_video_record(p.name, total_sampled, muddy_count, status="COMPLETED")
        print(f"[TS Watcher] 分析完成: {p.name} | 總抽幀: {total_sampled} | 違規事件數: {muddy_count}")

    def scan_historical_records(self):
        if not self.record_dir.exists():
            return
        for f in self.record_dir.rglob("*.ts"):
            self.on_new_ts_file(str(f))

    def stop(self):
        self.running = False
        if HAS_WATCHDOG and hasattr(self, 'observer') and self.observer.is_alive():
            self.observer.stop()
            self.observer.join()
