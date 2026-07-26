# -*- coding: utf-8 -*-
"""
Dò DẢI sub gốc bằng OCR THẬT (Tesseract chi_sim) — FALLBACK khi dai_sub (OpenCV) trượt.

Ý tưởng: OCR vài khung tại MỐC có sub (đọc từ .vi.srt, hoặc trải đều theo thời lượng)
-> lấy bbox các từ CHỮ TRUNG -> cộng dồn "độ phủ" theo từng hàng (cân theo bề rộng)
-> dải có đỉnh phủ = dải sub gốc. Chính xác hơn heuristic cạnh (Laplacian) vì bám đúng chữ.

phat_hien_dai_ocr(video, srt_path, log_fn) -> (y0_frac, y1_frac, H) hoặc None
  (None = thiếu tesseract/chi_sim, hoặc không đủ tin cậy -> caller lùi hộp đen như cũ).

Tái dùng setup tesseract của ocr_anh (tim_tesseract/chuan_bi/_set_tessdata).
"""
import os
import re


def _moc_tu_srt(srt_path, n=8):
    """n mốc thời gian (giây, GIỮA mỗi cue) trải đều từ .srt. Không có srt -> []."""
    if not srt_path or not os.path.isfile(srt_path):
        return []
    try:
        with open(srt_path, encoding="utf-8-sig", errors="replace") as f:
            txt = f.read()
    except Exception:
        return []
    ts = []
    for m in re.finditer(
        r"(\d\d):(\d\d):(\d\d)[,.](\d+)\s*-->\s*(\d\d):(\d\d):(\d\d)[,.](\d+)", txt):
        g = list(map(int, m.groups()))
        a = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000.0
        b = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000.0
        ts.append((a + b) / 2.0)
    if len(ts) <= n:
        return ts
    step = len(ts) / float(n)
    return [ts[int(i * step)] for i in range(n)]


def _co_cjk(s):
    return any("一" <= c <= "鿿" for c in (s or ""))


def phat_hien_dai_ocr(video, srt_path=None, log_fn=print, n_frames=8):
    """Trả (y0_frac, y1_frac, H) dải sub gốc theo OCR, hoặc None."""
    try:
        import cv2
        import numpy as np
    except Exception:
        return None
    try:
        import ocr_anh
        import pytesseract
    except Exception:
        return None

    ok, msg = ocr_anh.chuan_bi()
    if not ok:
        log_fn("⚠ OCR dò dải: %s" % msg)
        return None
    ocr_anh._set_tessdata("chi_sim")
    pre = os.environ.get("TESSDATA_PREFIX", "")
    if not (pre and os.path.isfile(os.path.join(pre, "chi_sim.traineddata"))):
        log_fn("⚠ OCR dò dải: thiếu chi_sim.traineddata → bỏ qua (lùi hộp đen).")
        return None

    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        return None
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 0
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    nfr = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    dur = (nfr / fps) if fps > 0 else 0.0
    if H <= 0:
        cap.release()
        return None

    moc = _moc_tu_srt(srt_path, n_frames)
    if not moc:
        moc = [dur * (i + 0.5) / n_frames for i in range(n_frames)] if dur > 0 else []
    if not moc:
        cap.release()
        return None

    cov = np.zeros(H, dtype=np.float32)   # độ phủ chữ Trung theo từng hàng (cân theo bề rộng)
    NBIN = 24                              # chia khung thành 24 dải ngang để dò "chữ ĐỔI giữa frame"
    bin_chars = [set() for _ in range(NBIN)]   # KÝ TỰ CJK gom qua MỌI frame theo dải (bền với nhiễu OCR)
    bin_maxlen = [0] * NBIN                     # số ký tự CJK NHIỀU NHẤT trong 1 frame của dải đó
    n_hit = 0
    for t in moc:
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t) * 1000.0)
        ok2, fr = cap.read()
        if not ok2 or fr is None:
            continue
        fh = fr.shape[0]
        # downscale theo bề rộng ~960 cho OCR nhanh; quy bbox về toạ độ gốc theo tỉ lệ chiều cao
        scale = 1.0
        if fr.shape[1] > 960:
            scale = 960.0 / fr.shape[1]
            fr_ocr = cv2.resize(fr, (960, max(1, int(fh * scale))), interpolation=cv2.INTER_AREA)
        else:
            fr_ocr = fr
        ry = H / float(fr_ocr.shape[0])   # quy hàng OCR -> hàng video gốc (H)
        try:
            d = pytesseract.image_to_data(
                fr_ocr, lang="chi_sim", config="--oem 1 --psm 6",
                output_type=pytesseract.Output.DICT)
        except Exception:
            continue
        got = False
        frame_chars = [set() for _ in range(NBIN)]   # ký tự CJK của RIÊNG frame này theo dải
        for i in range(len(d.get("text", []))):
            txt = (d["text"][i] or "").strip()
            try:
                conf = float(d["conf"][i])
            except (ValueError, TypeError):
                conf = -1.0
            if conf < 35 or not _co_cjk(txt):
                continue
            top = int(round(int(d["top"][i]) * ry))
            bot = int(round((int(d["top"][i]) + int(d["height"][i])) * ry))
            w = max(1, int(round(int(d["width"][i]) * ry)))
            top = max(0, min(H - 1, top))
            bot = max(top + 1, min(H, bot))
            cov[top:bot] += w
            cy = (top + bot) // 2          # tâm chữ → dải; gom KÝ TỰ CJK theo dải để biết dải nào ĐỔI chữ
            b = min(NBIN - 1, cy * NBIN // H)
            frame_chars[b].update(c for c in txt if "一" <= c <= "鿿")
            got = True
        for b in range(NBIN):              # cập nhật tích lũy + max-1-frame cho từng dải
            if frame_chars[b]:
                bin_chars[b] |= frame_chars[b]
                if len(frame_chars[b]) > bin_maxlen[b]:
                    bin_maxlen[b] = len(frame_chars[b])
        if got:
            n_hit += 1

    cap.release()
    if n_hit < 2 or float(cov.max()) <= 0.0:
        log_fn("ℹ OCR dò dải: không đủ khung thấy chữ Trung (%d) → lùi hộp đen." % n_hit)
        return None

    # CHỐNG DƯƠNG-TÍNH-GIẢ + BẮT SUB GIỮA KHUNG (Douyin "2 ảnh chồng, sub ở dải giữa"):
    # PHÂN BIỆT sub vs nội-dung-tĩnh bằng KÝ TỰ CJK CÓ ĐỔI NHIỀU giữa các frame không. SUB đổi câu mỗi
    # cue → TỔNG ký tự gom qua mọi frame NHIỀU HƠN HẲN ký tự của frame đông nhất (chữ mới liên tục).
    # Biển hiệu/caption TĨNH = chữ gần như cố định → tổng ≈ 1-frame (chênh nhỏ chỉ do NHIỄU OCR).
    # → bền với nhiễu OCR (trước dùng "≥2 chuỗi khác" bị nhiễu OCR đánh lừa, dò nhầm chữ tĩnh).
    # ƯU TIÊN dải đổi-chữ (mọi vị trí kể cả giữa); KHÔNG có → fallback mép dưới ≥60% / trên ≤28%.
    doi = np.zeros_like(cov)
    for b in range(NBIN):
        if len(bin_chars[b]) - bin_maxlen[b] >= 5:   # ≥5 ký tự MỚI ngoài frame đông nhất = chữ đổi (sub)
            doi[b * H // NBIN:(b + 1) * H // NBIN] = 1.0
    if float(doi.max()) > 0.0:
        cov = cov * doi                    # CHỈ giữ dải đổi chữ → bắt đúng sub (kể cả giữa), bỏ nội-dung-tĩnh
    else:
        hop_le = np.zeros_like(cov)        # không bắt được dải đổi → fallback vị trí kinh điển
        hop_le[int(H * 0.60):] = cov[int(H * 0.60):]
        if os.environ.get("CHE_DAI_TREN") == "1":
            hop_le[:int(H * 0.28)] = cov[:int(H * 0.28)]
        cov = hop_le
    if float(cov.max()) <= 0.0:
        log_fn("ℹ OCR dò dải: chỉ thấy chữ Trung TĨNH ở giữa (nội dung, không phải sub) → lùi hộp đen.")
        return None

    thr = float(cov.max()) * 0.25
    on = cov >= thr
    pk = int(cov.argmax())
    y0 = pk
    while y0 > 0 and on[y0 - 1]:
        y0 -= 1
    y1 = pk
    while y1 < H - 1 and on[y1 + 1]:
        y1 += 1
    # Nới TRÊN+DƯỚI dày hơn (chữ cao/2 dòng/dấu thanh) — burn_phude blur che NGUYÊN dải NGANG (full-width)
    # nên dù chữ ở khung khác dài hơn lúc OCR vẫn bị che hết; chỉ cần đủ CAO.
    pad = int(round(0.03 * H))
    y0 = max(0, y0 - pad)
    y1 = min(H - 1, y1 + pad)
    y0_frac = y0 / float(H)
    y1_frac = y1 / float(H)
    # Khống chế dải che tránh phình to do nhiễu
    max_h = 0.15
    if (y1_frac - y0_frac) > max_h:
        yc = (y0_frac + y1_frac) / 2.0
        if yc >= 0.5:
            y0_frac = y1_frac - max_h
        else:
            y1_frac = y0_frac + max_h
    log_fn("🔎 OCR dò dải sub gốc: %.1f%%–%.1f%% chiều cao (%d/%d khung có chữ)."
           % (100.0 * y0_frac * 100, 100.0 * y1_frac * 100, n_hit, len(moc)))
    return (y0_frac, y1_frac, H)


if __name__ == "__main__":
    import argparse
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--srt", default="")
    ap.add_argument("--n", type=int, default=8)
    a = ap.parse_args()
    r = phat_hien_dai_ocr(a.video, a.srt or None, n_frames=a.n)
    print("KETQUA:", r)
