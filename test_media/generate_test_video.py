import cv2
import numpy as np
from pathlib import Path

output_path = Path(__file__).parent / "sample.ts"
print(f"正在生成 1080p 15fps 測試影片至: {output_path} ...")

width, height = 1920, 1080
fps = 15.0
duration_sec = 10  # 10秒測試片，播放器會自動迴圈
total_frames = int(fps * duration_sec)

# 使用 MPEG-2 TS 或 MP4V 編碼
fourcc = cv2.VideoWriter_fourcc(*'mp4v')
out = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))

for i in range(total_frames):
    # 建立灰階柏油路面底色
    frame = np.full((height, width, 3), (90, 90, 95), dtype=np.uint8)
    
    # 畫兩側路沿黃線
    cv2.line(frame, (100, 400), (300, 1080), (0, 215, 255), 15)
    cv2.line(frame, (1820, 400), (1620, 1080), (0, 215, 255), 15)
    
    # 在第 3~7 秒模擬一段泥濘污染痕跡 (棕褐色)
    if 45 <= i <= 105:
        cv2.ellipse(frame, (960, 800), (350, 120), 0, 0, 360, (35, 60, 95), -1)
        # 加上高頻雜訊顆粒模擬砂石泥巴
        noise = np.random.randint(-25, 25, (240, 700, 3), dtype=np.int16)
        patch = frame[680:920, 610:1310].astype(np.int16) + noise
        frame[680:920, 610:1310] = np.clip(patch, 0, 255).astype(np.uint8)
        cv2.putText(frame, "[TEST SIMULATION: ROAD MUDDY]", (50, 100), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3)
    else:
        cv2.putText(frame, "[TEST SIMULATION: ROAD CLEAN]", (50, 100), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 0), 3)

    cv2.putText(frame, f"Frame: {i+1}/{total_frames} | 1080p 15fps", (50, 160),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 200, 200), 2)
    
    out.write(frame)

out.release()
print(f"測試影片生成完畢: {output_path}")
