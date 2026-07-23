# -*- coding: utf-8 -*-
"""
Dò MỐC THỜI GIAN phụ đề cứng (hardsub) bằng THAY ĐỔI HÌNH ẢNH trong dải sub — KHÔNG OCR ký tự.
Ý tưởng: chữ phụ đề = các nét TRẮNG trong dải đáy. Mỗi frame -> 'chữ ký' = (độ phủ chữ, biên dạng cột).
- độ phủ > ngưỡng = ĐANG có sub; ~0 = khe trống.
- biên dạng cột đổi nhiều (mà không qua khe trống) = SANG câu sub khác.
Trả [(t_on, t_off)] mỗi khoảng = MỘT dòng sub hiển thị. Ghép với text ASR (FunASR) ở bước sau.

API: detect_intervals(video, band=(y0f,y1f), fps_coarse=8, ...) -> list[(t_on, t_off)]
"""
import os


def _signature(band_bgr, cv2, np):
    """(cov, prof): cov = tỉ lệ điểm chữ trắng; prof = biên dạng số điểm trắng theo CỘT (chuẩn hoá)."""
    g = cv2.cvtColor(band_bgr, cv2.COLOR_BGR2GRAY)
    # chữ sub = trắng + có viền tối quanh nét → lấy điểm rất sáng VÀ có gradient mạnh (nét mảnh),
    # loại nền sáng phẳng (trời/tuyết) vốn sáng nhưng KHÔNG có nét.
    bright = g > 190
    grad = np.abs(cv2.Laplacian(g, cv2.CV_32F, ksize=3)) > 40
    mask = (bright & grad).astype(np.float32)
    cov = float(mask.mean())
    prof = mask.sum(axis=0)
    s = prof.sum()
    prof = (prof / s) if s > 0 else prof
    return cov, prof.astype(np.float32)


def _dist(p, q):
    import numpy as np
    return 0.5 * float(np.abs(p - q).sum())   # khoảng cách L1/2 giữa 2 biên dạng đã chuẩn hoá, trong [0,1]


def detect_intervals(video, band, fps_coarse=8.0, t_start=0.0, t_end=None,
                     t_cov=0.012, t_dist=0.40, min_dur=0.25, log=print):
    """band = (y0f, y1f) phần trăm chiều cao chứa dải sub. Trả [(t_on, t_off)] (giây)."""
    import cv2, numpy as np
    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        return []
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    nfr = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    dur = (nfr / fps) if fps else 0.0
    if t_end is None:
        t_end = dur
    y0, y1 = int(H * band[0]), int(H * band[1])
    stride = max(1, int(round(fps / fps_coarse)))   # lấy mẫu mỗi `stride` frame

    # ĐỌC TUẦN TỰ: grab() bỏ qua frame KHÔNG decode (nhanh), chỉ retrieve() ở frame lấy mẫu —
    # nhanh hơn nhiều so với set(POS_MSEC) seek từng mẫu.
    start_f = int(t_start * fps)
    end_f = int(t_end * fps) if t_end else int(nfr)
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_f)
    samples = []   # (t, cov, prof)
    fidx = start_f
    while fidx < end_f:
        if (fidx - start_f) % stride == 0:
            ok, fr = cap.read()
            if not ok or fr is None:
                break
            cov, prof = _signature(fr[y0:y1, :], cv2, np)
            samples.append((fidx / fps, cov, prof))
        else:
            if not cap.grab():
                break
        fidx += 1
    cap.release()
    if not samples:
        return []

    intervals = []
    cur_start = None
    cur_prof = None
    prev_t = samples[0][0]
    for (tt, cov, prof) in samples:
        has = cov > t_cov
        if has:
            if cur_start is None:
                cur_start = tt; cur_prof = prof
            elif _dist(prof, cur_prof) > t_dist:        # sub đổi mà KHÔNG qua khe trống
                bnd = (prev_t + tt) / 2.0
                intervals.append((cur_start, bnd))
                cur_start = bnd; cur_prof = prof
            else:
                cur_prof = prof                          # cùng câu → cập nhật biên dạng mới nhất
        else:
            if cur_start is not None:
                intervals.append((cur_start, (prev_t + tt) / 2.0))
                cur_start = None; cur_prof = None
        prev_t = tt
    if cur_start is not None:
        intervals.append((cur_start, prev_t))

    out = [(a, b) for (a, b) in intervals if (b - a) >= min_dur]
    return out


if __name__ == "__main__":
    import sys, cv2
    V = sys.argv[1] if len(sys.argv) > 1 else \
        r"MediaCrawler/data/douyin/videos/tu-khoa/一口气看完/一口气看完最新灾难电影 #推荐电影_027593.mp4"
    ts = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0
    te = float(sys.argv[3]) if len(sys.argv) > 3 else 180.0
    band = (0.84, 1.0)
    iv = detect_intervals(V, band, fps_coarse=8.0, t_start=ts, t_end=te)
    print("=== %d khoang sub trong [%.0f..%.0f]s (band %.2f-%.2f) ===" % (len(iv), ts, te, band[0], band[1]))
    OUT = "_iv_frames"; os.makedirs(OUT, exist_ok=True)
    cap = cv2.VideoCapture(V); H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    for k, (a, b) in enumerate(iv):
        print("  [%02d] %.2f -> %.2f  (%.2fs)" % (k, a, b, b - a))
        if k < 14:
            cap.set(cv2.CAP_PROP_POS_MSEC, (a + 0.15) * 1000.0)
            ok, fr = cap.read()
            if ok:
                cv2.imwrite(os.path.join(OUT, "iv_%02d.png" % k), fr[int(H * band[0]):, :])
    cap.release()
