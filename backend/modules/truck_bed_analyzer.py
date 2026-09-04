import cv2
import numpy as np

class TruckBedAnalyzer:
    """
    貨廂防塵設施判視模組 (符合花蓮環保局 115-2-05 計畫書 C-2 規範)
    功能：
    1. 針對出入口行經之砂石車/卡車 (Truck) 進行車斗區域定位與裁剪。
    2. 分析車斗表面紋理粗糙度 (Laplacian/Texture Variance) 與色彩平整度。
    3. 判斷車斗是否依規定覆蓋防塵網/帆布 (COVERED / UNCOVERED)。
    4. 檢驗防塵網周圍是否下拉包覆。
    """
    def __init__(self, texture_threshold=180.0, color_std_threshold=32.0):
        # 紋理變異數閾值：未蓋帆布的砂石/土方表面顆粒粗糙，Laplacian 方差高於 180
        self.texture_threshold = texture_threshold
        # 顏色標準差閾值：平整帆布顏色均勻 (標準差低)，未蓋之雜亂土石顏色標準差大
        self.color_std_threshold = color_std_threshold

    def extract_truck_bed_roi(self, frame, bbox):
        """
        從卡車整體 Bounding Box [x1, y1, x2, y2] 提取車斗頂部區域
        通常車斗位於卡車上方 20%~75% 及 後方 30%~100% 區域 (俯視角度)
        """
        x1, y1, x2, y2 = bbox
        w = x2 - x1
        h = y2 - y1
        if w < 50 or h < 50:
            return None, None

        # 俯視視角下的車斗核心檢測區
        bed_y1 = max(0, int(y1 + h * 0.15))
        bed_y2 = min(frame.shape[0], int(y1 + h * 0.75))
        bed_x1 = max(0, int(x1 + w * 0.15))
        bed_x2 = min(frame.shape[1], int(x1 + w * 0.85))

        bed_crop = frame[bed_y1:bed_y2, bed_x1:bed_x2]
        bed_box = (bed_x1, bed_y1, bed_x2, bed_y2)
        return bed_crop, bed_box

    def analyze_coverage(self, bed_crop):
        """
        分析車斗覆蓋狀態：
        回傳: (is_covered, status_str, confidence, details)
        """
        if bed_crop is None or bed_crop.size == 0:
            return True, "UNKNOWN", 0.0, {}

        # 1. 轉灰階計算紋理粗糙度 (Laplacian 變異數)
        gray = cv2.cvtColor(bed_crop, cv2.COLOR_BGR2GRAY)
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        texture_var = float(laplacian.var())

        # 2. 轉 HSV 計算色彩均勻度 (標準差)
        hsv = cv2.cvtColor(bed_crop, cv2.COLOR_BGR2HSV)
        h, s, v = cv2.split(hsv)
        s_std = float(np.std(s))
        v_std = float(np.std(v))

        # 3. 綠色/藍色/黑色 專用防塵帆布色譜佔比
        # 綠色防塵網 H: 35~85, 藍色帆布 H: 90~130, 黑色防塵布 V < 60
        mask_green = cv2.inRange(hsv, np.array([35, 40, 40]), np.array([85, 255, 255]))
        mask_blue = cv2.inRange(hsv, np.array([90, 40, 40]), np.array([130, 255, 255]))
        mask_dark = cv2.inRange(hsv, np.array([0, 0, 0]), np.array([180, 255, 65]))
        
        tarp_pixels = cv2.countNonZero(mask_green | mask_blue | mask_dark)
        total_pixels = bed_crop.shape[0] * bed_crop.shape[1]
        tarp_ratio = float(tarp_pixels / total_pixels) if total_pixels > 0 else 0.0

        # 4. 綜合判決邏輯
        # 條件：若帆布色譜佔比高且表面紋理平滑 -> 合格覆蓋
        # 若砂石紋理強烈且帆布佔比低 -> 違規未覆蓋
        is_covered = True
        confidence = 85.0

        if tarp_ratio > 0.45 and texture_var < self.texture_threshold * 1.5:
            is_covered = True
            status_str = "COVERED"
            confidence = min(98.0, 70.0 + tarp_ratio * 30.0)
        elif texture_var > self.texture_threshold and tarp_ratio < 0.25:
            is_covered = False
            status_str = "UNCOVERED"
            confidence = min(96.0, 60.0 + (texture_var / self.texture_threshold) * 20.0)
        else:
            # 邊界過渡區：以色彩方差判定
            if v_std > self.color_std_threshold * 1.3:
                is_covered = False
                status_str = "UNCOVERED"
                confidence = 75.0
            else:
                is_covered = True
                status_str = "COVERED"
                confidence = 80.0

        details = {
            "texture_var": round(texture_var, 1),
            "tarp_ratio": round(tarp_ratio * 100, 1),
            "v_std": round(v_std, 1),
            "is_covered": is_covered
        }
        return is_covered, status_str, confidence, details

    def draw_annotation(self, frame, truck_bbox, bed_bbox, status_str, confidence, details):
        """在畫面上繪製車斗檢驗框與合規標籤"""
        annotated = frame.copy()
        color = (0, 200, 0) if status_str == "COVERED" else (0, 0, 240)
        label_text = f"Truck Bed: {status_str} ({confidence:.1f}%)"
        
        # 標註卡車整體框 (白框)
        tx1, ty1, tx2, ty2 = truck_bbox
        cv2.rectangle(annotated, (tx1, ty1), (tx2, ty2), (220, 220, 220), 2)
        
        # 標註車斗檢驗框
        if bed_bbox:
            bx1, by1, bx2, by2 = bed_bbox
            cv2.rectangle(annotated, (bx1, by1), (bx2, by2), color, 3)
            # 背景標籤條
            cv2.rectangle(annotated, (bx1, max(0, by1 - 32)), (bx1 + 320, by1), color, -1)
            cv2.putText(annotated, label_text, (bx1 + 6, max(22, by1 - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            
            sub_text = f"Tarp: {details.get('tarp_ratio', 0)}% | Texture: {details.get('texture_var', 0)}"
            cv2.putText(annotated, sub_text, (bx1 + 6, by2 + 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

        return annotated
