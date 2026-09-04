import os
import cv2
import numpy as np
from pathlib import Path

def generate_acceptance_video():
    project_root = Path(r"D:\HL_CCTV")
    bg_path = project_root / "output" / "snapshots" / "clean_frame_10.jpg"
    truck_unc_path = project_root / "test_media" / "assets" / "truck_uncovered.jpg"
    truck_cov_path = project_root / "test_media" / "assets" / "truck_covered.jpg"
    
    output_ts_1 = project_root / "test_media" / "sample.ts"
    output_ts_record = Path(r"D:\錄影\Record\10.0.0.10\2026-07-27\20260727145550.ts")
    output_ts_record.parent.mkdir(parents=True, exist_ok=True)
    
    bg_img = cv2.imread(str(bg_path))
    if bg_img is None:
        raise FileNotFoundError(f"找不到背景圖: {bg_path}")
    h, w = bg_img.shape[:2]

    # 去除背景左上角舊文字殘影 (用天空顏色無痕修補)
    bg_img[10:90, 10:480] = cv2.GaussianBlur(bg_img[10:90, 10:480], (35, 35), 0)

    # 完美去背函數 (色差分析 + 外部輪廓實心填充)
    def clean_cutout(img_path):
        img = cv2.imread(str(img_path))
        ih, iw = img.shape[:2]
        corners = np.array([img[5, 5], img[5, iw-6], img[ih-6, 5], img[ih-6, iw-6]], dtype=float)
        bg_color = corners.mean(axis=0)
        diff = np.linalg.norm(img.astype(float) - bg_color, axis=2)
        raw_mask = (diff > 26).astype(np.uint8) * 255
        
        # 尋找卡車外部主輪廓並實心填充
        contours, _ = cv2.findContours(raw_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        mask = np.zeros((ih, iw), dtype=np.uint8)
        if contours:
            # 取面積最大者為主體
            main_cnt = max(contours, key=cv2.contourArea)
            cv2.drawContours(mask, [main_cnt], -1, 255, -1)
            
        # 輕度邊緣平滑
        mask = cv2.GaussianBlur(mask, (3, 3), 0)
        return img, mask

    print("正在執行精確輪廓去背...")
    truck_unc, mask_unc = clean_cutout(truck_unc_path)
    truck_cov, mask_cov = clean_cutout(truck_cov_path)

    # 繪製高辨識度台灣白底黑字車牌
    def attach_license_plate(truck_img, plate_str, box):
        x1, y1, x2, y2 = box
        cv2.rectangle(truck_img, (x1, y1), (x2, y2), (250, 250, 250), -1)
        cv2.rectangle(truck_img, (x1, y1), (x2, y2), (10, 10, 10), 2)
        font_scale = (y2 - y1) / 30.0
        cv2.putText(truck_img, plate_str, (x1 + 6, y2 - 8),
                    cv2.FONT_HERSHEY_DUPLEX, font_scale, (10, 10, 10), 2)

    # HAA-5678 (未覆蓋防塵布違規車輛)
    attach_license_plate(truck_unc, "HAA-5678", (790, 685, 875, 725))
    # KPA-8891 (合規覆蓋帆布車輛)
    attach_license_plate(truck_cov, "KPA-8891", (175, 655, 255, 695))

    fps = 15.0
    duration_sec = 30
    total_frames = int(fps * duration_sec)
    
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out_1 = cv2.VideoWriter(str(output_ts_1), fourcc, fps, (w, h))
    out_rec = cv2.VideoWriter(str(output_ts_record), fourcc, fps, (w, h))
    
    print(f"開始高精度渲染 1080p 15fps 驗收影片 ({total_frames} 幀)...")

    # 建立路面泥濘圖層 (深褐色輪胎印 + 泥漿飛濺)
    mud_layer = np.zeros((h, w, 4), dtype=np.uint8) # BGRA
    
    # 雙軌輪胎印
    cv2.line(mud_layer, (260, 780), (620, 930), (22, 45, 78, 220), 45) # 軌跡1
    cv2.line(mud_layer, (340, 840), (740, 1010), (20, 42, 72, 220), 50) # 軌跡2
    cv2.ellipse(mud_layer, (470, 890), (140, 60), 18, 0, 360, (18, 38, 65, 235), -1) # 中央大泥灘
    
    # 隨機泥漿顆粒飛濺
    np.random.seed(42)
    for _ in range(35):
        rx = np.random.randint(240, 780)
        ry = np.random.randint(760, 1020)
        rr = np.random.randint(4, 14)
        cv2.circle(mud_layer, (rx, ry), rr, (18, 38, 65, 210), -1)

    # 加上泥濘雜訊質感與邊緣羽化
    noise = np.random.randint(-20, 20, (h, w), dtype=np.int16)
    rgb = mud_layer[:, :, :3].astype(np.int16)
    for c in range(3):
        rgb[:, :, c] = np.clip(rgb[:, :, c] + noise, 0, 255)
    mud_layer[:, :, :3] = rgb.astype(np.uint8)
    mud_layer[:, :, 3] = cv2.GaussianBlur(mud_layer[:, :, 3], (7, 7), 0)

    # 卡車貼合渲染
    def blend_truck(bg, truck, mask, cx, cy, scale):
        tw = int(truck.shape[1] * scale)
        th = int(truck.shape[0] * scale)
        if tw <= 10 or th <= 10: return
        t_res = cv2.resize(truck, (tw, th), interpolation=cv2.INTER_AREA)
        m_res = cv2.resize(mask, (tw, th), interpolation=cv2.INTER_AREA)

        x1, y1 = cx - tw // 2, cy - th // 2
        x2, y2 = x1 + tw, y1 + th

        dx1, dy1 = max(0, x1), max(0, y1)
        dx2, dy2 = min(w, x2), min(h, y2)
        sx1, sy1 = dx1 - x1, dy1 - y1
        sx2, sy2 = sx1 + (dx2 - dx1), sy1 + (dy2 - dy1)

        if dx2 > dx1 and dy2 > dy1:
            t_crop = t_res[sy1:sy2, sx1:sx2]
            alpha = (m_res[sy1:sy2, sx1:sx2].astype(float) / 255.0)
            alpha_3 = cv2.merge([alpha, alpha, alpha])

            # 車底動態接觸陰影
            shadow_h = int(th * 0.10)
            sy1_s = max(0, dy2 - shadow_h)
            bg[sy1_s:dy2, dx1:dx2] = (bg[sy1_s:dy2, dx1:dx2].astype(float) * 0.60).astype(np.uint8)

            # Alpha 融合成像
            target = bg[dy1:dy2, dx1:dx2]
            bg[dy1:dy2, dx1:dx2] = (t_crop * alpha_3 + target * (1.0 - alpha_3)).astype(np.uint8)

    for f_idx in range(total_frames):
        cur_sec = f_idx / fps
        frame = bg_img.copy()

        # 1. 專業 CCTV OSD 浮水印 (1080p 15fps 動態跳動時間戳)
        s_int = int(cur_sec)
        ms_int = int((cur_sec - s_int) * 1000)
        time_str = f"2026/09/04 14:35:{s_int:02d}.{ms_int:03d}"
        
        cv2.rectangle(frame, (18, 18), (530, 68), (12, 16, 20), -1)
        cv2.rectangle(frame, (18, 18), (530, 68), (50, 65, 80), 1)
        cv2.putText(frame, f"CAM_10  ENTRANCE  {time_str}", (28, 52),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (235, 235, 235), 2)
        cv2.putText(frame, "1080p 15fps", (430, 52),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 130), 1)

        # 2. 劇本排程:
        # A. 0~4秒 (幀 0~60): 平靜路面 (CLEAN)
        # B. 4~12秒 (幀 61~180): 合規卡車 KPA-8891 經過 (COVERED)
        if 61 <= f_idx <= 180:
            p = (f_idx - 61) / (180 - 61)
            cx = int(220 + p * 620)
            cy = int(720 + p * 220)
            sc = 0.42 + p * 0.28
            blend_truck(frame, truck_cov, mask_cov, cx, cy, sc)

        # C. 13~21秒 (幀 195~315): 違規砂石車 HAA-5678 駛出 (UNCOVERED)
        if 195 <= f_idx <= 315:
            p = (f_idx - 195) / (315 - 195)
            cx = int(180 + p * 640)
            cy = int(710 + p * 230)
            sc = 0.45 + p * 0.30
            blend_truck(frame, truck_unc, mask_unc, cx, cy, sc)

        # D. 16~30秒 (幀 240~450): 輪胎帶泥，路面泥濘逐步顯現並持續
        if f_idx >= 240:
            p_mud = min(1.0, (f_idx - 240) / 60.0) # 4秒內完全展開
            m_alpha = (mud_layer[:, :, 3].astype(float) / 255.0) * p_mud
            m_alpha_3 = cv2.merge([m_alpha, m_alpha, m_alpha])
            m_rgb = mud_layer[:, :, :3]
            frame = (m_rgb * m_alpha_3 + frame * (1.0 - m_alpha_3)).astype(np.uint8)

        out_1.write(frame)
        out_rec.write(frame)

        if f_idx % 45 == 0:
            print(f"渲染進度: {f_idx}/{total_frames} 幀 ({cur_sec:.1f} 秒)...")

    out_1.release()
    out_rec.release()
    print("高擬真驗收影片生成完畢！")

    # 3. 建立相符之正式 Reference 基準樣本 (clean & muddy)
    refs_dir = project_root / "data" / "refs" / "cam_10"
    refs_dir.mkdir(parents=True, exist_ok=True)
    
    roi_cfg = [
        [0.05, 0.65],
        [0.60, 0.65],
        [0.55, 0.98],
        [0.02, 0.98]
    ]
    mask = np.zeros((h, w), dtype=np.uint8)
    points = [[int(p[0] * w), int(p[1] * h)] for p in roi_cfg]
    pts = np.array(points, np.int32).reshape((-1, 1, 2))
    cv2.fillPoly(mask, [pts], 255)

    def save_ref(frame_data, label):
        hsv = cv2.cvtColor(frame_data, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], mask, [50, 60], [0, 180, 0, 256])
        cv2.normalize(hist, hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
        file_id = f"{label}_noon_1788500000"
        np.save(refs_dir / f"{file_id}.npy", hist)
        roi_img = cv2.bitwise_and(frame_data, frame_data, mask=mask)
        cv2.imwrite(str(refs_dir / f"{file_id}.jpg"), roi_img)
        print(f"已更新 Reference 基準樣本: {file_id}")

    cap = cv2.VideoCapture(str(output_ts_1))
    ret1, f1 = cap.read() # 第 0 幀乾淨路面
    if ret1:
        save_ref(f1, "clean")
    
    cap.set(cv2.CAP_PROP_POS_FRAMES, 390) # 第 390 幀泥濘路面
    ret2, f2 = cap.read()
    if ret2:
        save_ref(f2, "muddy")
    cap.release()

if __name__ == "__main__":
    generate_acceptance_video()
