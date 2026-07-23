# -*- coding: utf-8 -*-
"""Tự dò WATERMARK/LOGO TĨNH (baked) trong video nguồn — bằng ĐỘ BỀN CỦA NÉT theo thời gian (OpenCV).

Vì sao KHÔNG dùng OCR-theo-vị-trí: thử thật cho thấy OCR bắt nhầm TIÊU ĐỀ nội dung (chữ "刀"/"小时候" — đứng
một chỗ nhưng ĐỔI CHỮ) và trượt WATERMARK THẬT (chữ mờ "毒舌电影" ở mép — đứng yên, KHÔNG đổi).

Tín hiệu ĐÚNG (user chốt "vùng TĨNH"): watermark baked = NÉT nằm ở CÙNG pixel qua HẦU HẾT frame (dù mờ/bán trong
suốt vẫn thêm nét đều đặn); còn tiêu đề/nội dung đổi → nét chập chờn. → lấy mẫu N frame, tính bản đồ nét (Laplacian)
mỗi frame, đo TỈ LỆ frame có nét ở từng pixel (persistence). Pixel nét-bền cao + nằm ở GÓC/mép (không phải giữa,
không phải dải phụ đề đổi chữ) = watermark → gom thành hộp {x,y,w,h}(px gốc) để blur + (tùy chọn) đè logo/chữ.

An toàn: thiếu OpenCV/lỗi/không chắc → trả [] (render giữ nguyên hành vi cũ). Có trần thời gian (mặc định 10s).
Tắt hẳn: env CHE_WM=0. Tinh chỉnh: CHE_WM_PERSIST (ngưỡng bền, mặc định 0.72), CHE_WM_FRAMES (số frame, 16).
"""
import os
import time


def _goc_cua(xc, yc):
    return ("b" if yc >= 0.5 else "t") + ("r" if xc >= 0.5 else "l")


_CACHE = {}   # (path, mtime, size) -> boxes — dò 1 LẦN/video (render đa-ngôn-ngữ khỏi dò lại N lần)


def phat_hien_watermark(video, log_fn=print, n_frames=16, ngan_sach_giay=10.0):
    """Trả list vùng watermark baked: [{"x","y","w","h","goc"}] (px video GỐC), hoặc [] nếu không chắc."""
    if os.environ.get("CHE_WM") == "0":
        return []
    _key = None
    try:
        _st = os.stat(video)
        _key = (os.path.abspath(video), _st.st_mtime, _st.st_size)
        if _key in _CACHE:
            return _CACHE[_key]
    except OSError:
        pass
    _r = _phat_hien(video, log_fn, n_frames, ngan_sach_giay)
    if _key is not None:
        _CACHE[_key] = _r
    return _r


def _phat_hien(video, log_fn, n_frames, ngan_sach_giay):
    try:
        import cv2
        import numpy as np
    except Exception as e:
        log_fn("ℹ Thiếu OpenCV (%s) → bỏ qua dò watermark." % str(e)[:50])
        return []
    try:
        n_frames = int(os.environ.get("CHE_WM_FRAMES") or n_frames)
        std_thr = float(os.environ.get("CHE_WM_STD") or 8.0)   # std pixel < ngưỡng = KHÔNG đổi = logo che kín (opaque)
    except ValueError:
        n_frames, std_thr = 16, 8.0

    try:
        t_bd = time.time()
        cap = cv2.VideoCapture(os.path.abspath(video))
        if not cap.isOpened():
            return []
        nfr = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        if H <= 0 or W <= 0 or nfr <= 0:
            cap.release()
            return []
        gw = 360                                   # rộng chuẩn hoá cho tính toán (giữ tỉ lệ)
        gh = max(2, int(round(H * gw / W)))
        frames = []                                # gom frame xám để đo BẤT BIẾN theo thời gian
        for k in range(n_frames):
            if time.time() - t_bd > ngan_sach_giay:
                log_fn("ℹ Dò logo quá %.0fs → dùng %d frame đã lấy." % (ngan_sach_giay, len(frames)))
                break
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(nfr * (k + 0.5) / n_frames))
            ok, fr = cap.read()
            if not ok or fr is None:
                continue
            g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
            frames.append(cv2.resize(g, (gw, gh)).astype(np.float32))
        cap.release()
        if len(frames) < max(4, n_frames // 3):
            return []

        # LOGO ĐỤC (opaque): che kín nền → pixel gần như KHÔNG đổi qua các frame (std thấp) + có NÉT đồ hoạ.
        # Watermark MỜ để lộ nền phía sau → pixel biến thiên → LOẠI (user: "không dò watermark mờ, chỉ dò logo").
        # Mảng phẳng (trời/tường) cũng std thấp nhưng KHÔNG nét → loại bằng edge_mask.
        stack = np.stack(frames)
        std = stack.std(axis=0)                    # biến thiên theo thời gian (opaque logo ~0)
        mean = stack.mean(axis=0).astype(np.uint8)
        edge_bin = np.abs(cv2.Laplacian(mean, cv2.CV_32F, ksize=3)) > 26   # NÉT đồ hoạ (viền/chi tiết logo)
        mask = (std < std_thr).astype(np.uint8)    # vùng gần như KHÔNG đổi = logo che kín (opaque)

        # ----- CHỈ GIỮ vùng GÓC/MÉP: watermark NÉP SÁT MÉP; TIÊU ĐỀ nội dung ở GIỮA (top/bottom-center) → BỎ.
        # Dò thật cho thấy tiêu đề "小时候"/"刀" nằm top-GIỮA (đứng yên nhưng là nội dung) → chỉ lấy 2 GÓC ở
        # trên/dưới (né giữa) + 2 dải MÉP trái/phải (bắt watermark cạnh kiểu 毒舌电影 ở x=0).
        zone = np.zeros((gh, gw), np.uint8)
        mx = int(gw * 0.18)                         # biên trái/phải 18% (đủ ôm watermark cạnh mờ)
        my_t = int(gh * 0.14)                       # biên trên 14%
        my_b = int(gh * 0.86)                       # biên dưới (từ 86%)
        cor = int(gw * 0.28)                        # bề rộng "góc" trên/dưới (né phần giữa)
        zone[:, :mx] = 1; zone[:, gw - mx:] = 1     # dải MÉP trái + phải (full chiều cao)
        zone[:my_t, :cor] = 1; zone[:my_t, gw - cor:] = 1     # trên: CHỈ 2 góc
        zone[my_b:, :cor] = 1; zone[my_b:, gw - cor:] = 1     # dưới: CHỈ 2 góc (né dải phụ đề giữa-đáy)
        mask = cv2.bitwise_and(mask, zone)
        # nối nét gần nhau thành khối
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                                cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9)))

        n_lbl, lbls, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        tot = gw * gh
        boxes = []
        for i in range(1, n_lbl):
            x, y, w, h, area = stats[i]
            frac = area / float(tot)
            if frac < 0.0009 or frac > 0.06:        # quá nhỏ = nhiễu; quá to = mảng cảnh, không phải logo
                continue
            if w > gw * 0.55:                        # rộng gần cả khung = viền/letterbox/dải → bỏ
                continue
            comp = (lbls == i)
            if area / float(max(1, w * h)) < 0.35:   # khối logo là ĐẶC, không rời rạc
                continue
            if float(edge_bin[comp].mean()) < 0.09:  # NÉT thưa (trời/tường/sàn gạch) → bỏ; logo nét DÀY hơn
                continue
            x0, y0 = x / gw, y / gh
            x1, y1 = (x + w) / gw, (y + h) / gh
            padx, pady = 0.015, 0.012
            x0 = max(0.0, x0 - padx); y0 = max(0.0, y0 - pady)
            x1 = min(1.0, x1 + padx); y1 = min(1.0, y1 + pady)
            bx = int(round(x0 * W)); by = int(round(y0 * H))
            bw = int(round((x1 - x0) * W)); bh = int(round((y1 - y0) * H))
            if bw < 8 or bh < 8:
                continue
            boxes.append({"x": bx, "y": by, "w": bw, "h": bh,
                          "goc": _goc_cua((x0 + x1) / 2, (y0 + y1) / 2)})

        if not boxes:
            return []
        gocs = ", ".join(sorted(set(b["goc"] for b in boxes)))
        log_fn("🎯 Dò LOGO nguồn (đục, che kín, bất biến theo thời gian): %d vùng (góc: %s) → blur + đè logo của bạn." %
               (len(boxes), gocs))
        return boxes
    except Exception as e:
        log_fn("ℹ Dò watermark lỗi (%s) → bỏ qua (chỉ blur che-band như cũ)." % str(e)[:60])
        return []


def _kich_thuoc(video):
    import cv2
    cap = cv2.VideoCapture(os.path.abspath(video))
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return W, H


def quyet_dinh_che(video, co_brand, log_fn=print):
    """CHÍNH SÁCH "logo che góc + blur nhỏ" (user chốt). Trả dict:
      {"blur": [{x,y,w,h}...], "logo_box": {x,y,w,h,goc}|None}
    - co_brand=True (tab Edit CÓ logo/watermark): trả vùng watermark chính để logo CHE KÍN + blur nấp dưới logo
      (an toàn dù dò lệch: kết quả = logo của bạn ở góc đó). Không thấy vùng cỡ-watermark → logo_box=None (caller
      đặt logo góc mặc định như cũ, KHÔNG blur).
    - co_brand=False: CHỈ blur hộp CHẮC = nhỏ + SÁT MÉP (watermark cạnh kiểu 毒舌电影); không chắc → [] (KHÔNG
      đụng cảnh/tiêu đề — user ưu tiên an toàn)."""
    boxes = phat_hien_watermark(video, log_fn=log_fn)
    if not boxes:
        return {"blur": [], "logo_box": None}
    try:
        W, H = _kich_thuoc(video)
    except Exception:
        W, H = 0, 0
    if W <= 0 or H <= 0:
        return {"blur": [], "logo_box": None}

    def _nho(b):        # cỡ watermark hợp lý (không phải cả mảng cảnh)
        return b["w"] <= 0.30 * W and b["h"] <= 0.22 * H

    def _sat_mep(b):    # chạm mép khung = watermark thật (tiêu đề/cảnh giữa không chạm mép)
        return b["x"] <= 3 or b["y"] <= 3 or (b["x"] + b["w"]) >= W - 3 or (b["y"] + b["h"]) >= H - 3

    if co_brand:
        cand = [b for b in boxes if _nho(b)]
        if not cand:
            return {"blur": [], "logo_box": None}
        primary = min(cand, key=lambda b: b["w"] * b["h"])   # nhỏ nhất = watermark nhất
        return {"blur": [primary], "logo_box": primary}
    conf = [b for b in boxes if _nho(b) and _sat_mep(b)]
    if conf:
        log_fn("   → %d vùng CHẮC (nhỏ+sát mép) sẽ blur; %d vùng không chắc BỎ QUA (an toàn)."
               % (len(conf), len(boxes) - len(conf)))
    return {"blur": conf, "logo_box": None}


if __name__ == "__main__":
    import sys
    v = sys.argv[1] if len(sys.argv) > 1 else ""
    if not v or not os.path.isfile(v):
        print("Dùng: python dai_watermark.py <video.mp4>")
        raise SystemExit(1)
    print("phat_hien:", phat_hien_watermark(v))
    print("quyet_dinh(brand=True):", quyet_dinh_che(v, True))
    print("quyet_dinh(brand=False):", quyet_dinh_che(v, False))
