# -*- coding: utf-8 -*-
"""Dò DẢI phụ đề gốc (burned-in) trong video bằng OpenCV — KHÔNG cần OCR/Tesseract.

Ý tưởng: phụ đề gốc là 1 DẢI NGANG ở vị trí cố định, chữ ĐỔI theo từng câu. Lấy mẫu vài
frame → năng lượng cạnh theo HÀNG (chữ = nhiều cạnh) × BIẾN THIÊN theo thời gian (chữ đổi
→ std cao; nền/watermark tĩnh → std thấp) → dải có điểm cao nhất ở NỬA DƯỚI khung.

phat_hien_dai(video, ff, ffprobe) -> (y0_frac, y1_frac, H) hoặc None (không chắc → caller
dùng hộp che cố định cũ). Chỉ phụ thuộc opencv-python + numpy (đã có sẵn), không thêm gì.
"""
import os
import subprocess


def _kich_thuoc(ffprobe, video):
    """(W, H, duration) của video; (0,0,0) nếu lỗi."""
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-show_entries", "format=duration",
             "-of", "default=nokey=1:noprint_wrappers=1", video],
            capture_output=True, text=True).stdout.split()
        w, h, dur = int(out[0]), int(out[1]), float(out[2])
        return w, h, dur
    except Exception:
        return 0, 0, 0.0


def phat_hien_dai(video, ff, ffprobe, log_fn=print, n_mau=18):
    """Trả (y0_frac, y1_frac, H) của dải sub gốc, hoặc None nếu không đủ tin cậy.
    y0/y1 là phần trăm chiều cao (0..1); H là chiều cao THẬT của video (cho MarginV)."""
    if os.environ.get("CHE_DAI") == "0":
        return None
    try:
        import cv2
        import numpy as np
    except Exception as e:
        log_fn("⚠ Thiếu opencv/numpy (%s) → dùng hộp che cố định." % str(e)[:50])
        return None

    W, H, dur = _kich_thuoc(ffprobe, video)
    if H <= 0 or dur <= 0:
        return None
    try:
        # TỐI ƯU: đọc n_mau frame bằng OpenCV (mở video 1 lần, seek theo mốc) thay vì spawn 18 ffmpeg
        # `-ss -frames:v 1` + ghi/đọc PNG → cắt ~47s xuống ~vài giây. Seek xấp xỉ keyframe là đủ cho dò dải.
        cap = cv2.VideoCapture(video)
        if not cap.isOpened():
            return None
        t0, t1 = dur * 0.1, dur * 0.9          # bỏ intro/outro
        rows = []
        for i in range(n_mau):
            t = t0 + (t1 - t0) * i / max(1, n_mau - 1)
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            sh = max(2, int(round(g.shape[0] * 480.0 / max(1, g.shape[1]))))   # scale rộng 480, giữ tỉ lệ
            g = cv2.resize(g, (480, sh))
            rows.append(np.abs(cv2.Laplacian(g, cv2.CV_32F, ksize=3)).sum(axis=1))
        cap.release()
        if len(rows) < 4:
            return None
        # đồng đều chiều cao frame (scale=480:-2 cho H chẵn, vẫn phòng lệch 1px)
        hmin = min(len(r) for r in rows)
        M = np.array([r[:hmin] for r in rows])
        h = M.shape[1]

        def nrm(a):
            a = a - a.min()
            return a / (a.max() + 1e-6)

        score = nrm(M.mean(axis=0)) * nrm(M.std(axis=0))   # mạnh + biến thiên = chữ động

        def _band_in(z_lo, z_hi):       # tìm dải chữ mạnh nhất TRONG vùng [z_lo, z_hi) → (peak, y0, y1)
            reg = score.copy()
            reg[:z_lo] = 0
            if z_hi < h:
                reg[z_hi:] = 0
            peak = float(reg.max())
            pk = int(reg.argmax())
            thr = max(0.18, peak * 0.45)
            on = reg >= thr
            y0 = pk
            while y0 > z_lo and on[y0 - 1]:
                y0 -= 1
            y1 = pk
            while y1 < min(h - 1, z_hi - 1) and on[y1 + 1]:
                y1 += 1
            return peak, y0, y1

        # MẶC ĐỊNH chỉ dò DƯỚI (45–100%): an toàn — không nhầm username/overlay/logo ở mép trên
        # (đo thật: top TikTok peak 0.78 ~ sub thật, không phân biệt được). Sub gốc Ở TRÊN hiếm gặp →
        # opt-in env CHE_DAI_TREN=1 mới dò thêm mép TRÊN (0–28%) và lấy dải mạnh hơn.
        bot = _band_in(int(h * 0.45), h)
        peak, y0, y1 = bot
        if os.environ.get("CHE_DAI_TREN") == "1":
            top = _band_in(0, int(h * 0.28))
            if top[0] > bot[0]:
                peak, y0, y1 = top
        pad = int(h * 0.015)
        y0f = max(0.0, (y0 - pad) / h)
        y1f = min(1.0, (y1 + pad) / h)
        cao = y1f - y0f
        # tin cậy: đỉnh đủ rõ + dải hợp lý (không quá mỏng/quá dày).
        # B1: siết trần 0.30→0.20 — dải RỘNG (>20% chiều cao) = nội dung-đổi diffuse (video KHÔNG sub) chứ
        # không phải hàng chữ → trả None (đỡ blur đè mặt/cảnh). Sub 1-3 dòng thật ~5-18% vẫn lọt.
        if peak < 0.22 or not (0.03 <= cao <= 0.20):
            log_fn("ℹ Không chắc vị trí sub gốc (peak=%.2f, cao=%.0f%%) → hộp che cố định." %
                   (peak, cao * 100))
            return None
        vi_tri = "TRÊN" if (y0f + y1f) / 2 < 0.5 else "DƯỚI"
        log_fn("🎯 Dải sub gốc ~ %.0f%%–%.0f%% chiều cao (%s) → làm mờ đúng dải." %
               (y0f * 100, y1f * 100, vi_tri))
        return (y0f, y1f, H)
    except Exception as e:
        log_fn("⚠ Dò dải sub lỗi (%s) → hộp che cố định." % str(e)[:60])
        return None


def detect_blur_band(video, srt=None, manual=None, log_fn=print):
    """QUYẾT ĐỊNH dải che sub gốc — DÙNG CHUNG cho preview (web_app /api/detect_band) và
    render (localize.chay) → cả hai cùng 1 logic: cùng thứ tự fallback + cùng cách resolve
    ffmpeg + cùng tầng dò. Trả dict:
      {"source": "manual"|"opencv"|"ocr"|"none", "y0":frac, "y1":frac, "H":px}
    "none" = không dò được → caller lùi hộp che cố định.
    Thứ tự (bê NGUYÊN từ render cũ): manual → OpenCV(phat_hien_dai) → OCR(dai_sub_ocr, khi
    OpenCV None + env CHE_OCR≠0) → none.
    LƯU Ý: preview gọi srt=None (chưa có .vi.srt) → tầng OCR lấy frame TRẢI ĐỀU (xấp xỉ render,
    không khác về QUYẾT ĐỊNH nhưng kết quả có thể lệch nhẹ — đúng kỳ vọng).
    """
    va = os.path.abspath(video)
    # ffmpeg/ffprobe = BUNDLE (qua xu_ly_video.tim_exe) — resolve executable LÀ MỘT PHẦN của quyết
    # định: preview & render PHẢI dùng cùng binary, không thì cùng hàm vẫn ra band khác trên máy khách.
    try:
        import xu_ly_video
        ff = xu_ly_video.tim_exe("ffmpeg")
        ffp = xu_ly_video.tim_exe("ffprobe")
    except Exception:
        ff, ffp = "ffmpeg", "ffprobe"
    try:
        if manual:
            y0f, y1f = float(manual[0]), float(manual[1])
            _W, _H, _ = _kich_thuoc(ffp, va)
            log_fn("🎯 Che chữ THỦ CÔNG: dải %.0f%%–%.0f%% chiều cao." % (y0f * 100, y1f * 100))
            return {"source": "manual", "y0": max(0.0, y0f), "y1": min(1.0, y1f), "H": int(_H or 0)}
        # ƯU TIÊN NHẤT: RapidOCR (PP-OCRv5 det) + CLUSTERING — tách cluster username/watermark/subtitle rồi
        # chọn cluster phụ đề (thấp + nhiều frame + rộng) → dải TIGHT, KHÔNG che đè mặt. Verify thật: RapidOCR
        # ra 92.6%–100% (đúng sub đáy) trong ~9s; Tesseract over-detect 57%–82% (che vào mặt) + chậm 16s +
        # không ổn định. Không đủ tin cậy / chưa cài → lùi Tesseract → OpenCV. Tắt: env CHE_RAPID=0.
        if os.environ.get("CHE_RAPID", "1") != "0":
            try:
                import dai_sub_rapid
                band = dai_sub_rapid.phat_hien_dai_rapid(va, log_fn=log_fn)
                if band:
                    # band 5-tuple (y0,y1,H,x0,x1): x0/x1 = bề ngang HỘP text → blur đúng hộp (không full-width)
                    return {"source": "rapidocr", "y0": band[0], "y1": band[1], "H": band[2],
                            "x0": band[3] if len(band) > 3 else 0.0, "x1": band[4] if len(band) > 4 else 1.0}
            except Exception:
                pass
        # OCR THẬT (Tesseract chi_sim) — fallback khi RapidOCR chưa cài/không chắc. Tắt: env CHE_OCR=0.
        if os.environ.get("CHE_OCR", "1") != "0":
            try:
                import dai_sub_ocr
                band = dai_sub_ocr.phat_hien_dai_ocr(va, srt, log_fn=log_fn)
                if band:
                    return {"source": "ocr", "y0": band[0], "y1": band[1], "H": band[2]}
            except Exception:
                pass
        band = phat_hien_dai(va, ff, ffp, log_fn=log_fn)
        if band:
            return {"source": "opencv", "y0": band[0], "y1": band[1], "H": band[2]}
    except Exception as e:
        log_fn("⚠ Dò dải sub bỏ qua (%s) → hộp che cố định." % str(e)[:60])
    return {"source": "none"}
