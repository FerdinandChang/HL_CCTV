import os
import zipfile
import shutil
from datetime import datetime

base_dir = r"d:\HL_CCTV"
out_zip = r"d:\HL_CCTV\HL_CCTV_Release.zip"

include_dirs = [
    "backend",
    "frontend",
    "data/refs",
    "output/snapshots"
]

include_files = [
    "requirements.txt",
    "README.md",
    "啟動監測系統.bat",
    "啟動監測系統(無黑窗).vbs",
    "停止監測系統.bat",
    "建立桌面捷徑.vbs",
    "首次環境安裝.bat",
    "data/hl_cctv.db"
]

ignore_patterns = [
    "__pycache__",
    ".git",
    ".pytest_cache",
    ".vscode",
    ".idea",
    "sample.ts"
]

print(f"[*] 開始執行 HL_CCTV 發行版打包作業...")
file_count = 0
total_uncompressed = 0

with zipfile.ZipFile(out_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
    # 1. 打包指定目錄
    for d in include_dirs:
        abs_d = os.path.join(base_dir, d)
        if not os.path.exists(abs_d):
            os.makedirs(abs_d, exist_ok=True)
        
        # 若為空目錄，也寫入目錄條目保持結構
        is_empty = True
        for root, dirs, files in os.walk(abs_d):
            # 過濾忽視資料夾
            dirs[:] = [sub for sub in dirs if not any(p in sub for p in ignore_patterns)]
            
            for f in files:
                if any(p in f for p in ignore_patterns):
                    continue
                if f.endswith(".pyc") or f.endswith(".log"):
                    continue
                full_p = os.path.join(root, f)
                rel_p = os.path.relpath(full_p, base_dir)
                zf.write(full_p, rel_p)
                file_count += 1
                total_uncompressed += os.path.getsize(full_p)
                is_empty = False
                
        if is_empty:
            rel_dir = os.path.relpath(abs_d, base_dir) + "/"
            zf.writestr(rel_dir, "")

    # 2. 打包指定獨立檔案
    for f in include_files:
        full_p = os.path.join(base_dir, f)
        if os.path.exists(full_p):
            zf.write(full_p, f)
            file_count += 1
            total_uncompressed += os.path.getsize(full_p)

zip_size_mb = os.path.getsize(out_zip) / (1024 * 1024)
uncompressed_mb = total_uncompressed / (1024 * 1024)

print(f"[OK] 打包成功完成！")
print(f"  - 輸出檔案: {out_zip}")
print(f"  - 檔案總數: {file_count} 個")
print(f"  - 原始大小: {uncompressed_mb:.2f} MB")
print(f"  - 壓縮後大小: {zip_size_mb:.2f} MB")
