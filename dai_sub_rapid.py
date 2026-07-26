# -*- coding: utf-8 -*-
"""Dò DẢI sub gốc bằng RapidOCR (PP-OCRv5 det) + CLUSTERING — chuẩn như phần mềm lớn (OCR → tracking →
subtitle region → blur), KHÔNG gộp mọi box thành 1 dải (sẽ dính username/watermark/title).

Cách làm: lấy mẫu N frame → det-only (chỉ cần box, nhanh) trên ~38% đáy → gom TẤT CẢ box.
CLUSTER box theo y (1D) → mỗi cluster = 1 phần tử text lặp qua các frame (username / watermark / SUBTITLE).
Chọn cluster phụ đề = XUẤT HIỆN NHIỀU FRAME + RỘNG (loại box hẹp góc) + THẤP → dải y của nó = dải che.
None → caller (detect_blur_band) lùi Tesseract → OpenCV. Tắt: env CHE_RAPID=0.
"""
import os


def _box_1frame_cheap(fr, cv2, np):
    """Tìm HỘP sub 1 frame bằng phân tích ảnh RẺ (trắng + gradient như ocr_timing, KHÔNG OCR → ~100× nhanh
    hơn RapidOCR det). Sub = DẢI NGANG chữ trắng-viền rộng nhất ở vùng 25–93%. Trả (y0,y1,x0,x1)% hoặc None."""
    H, W = fr.shape[:2]
    y_lo, y_hi = int(H * 0.22), int(H * 0.995)   # quét TỚI 99.5% (hardsub Douyin hay sát ĐÁY 92-99%; trước 93% bỏ sót → fail OCR)
    # CROP vùng đáy [y_lo:y_hi] TRƯỚC khi cvtColor/Laplacian → chỉ xử lý ~78% frame (bỏ 22% trên không dùng)
    # → cvtColor+Laplacian nhanh hơn, KẾT QUẢ Y HỆT (rowcov/cols vẫn lấy đúng các hàng cũ). mask giờ index từ y_lo.
    g = cv2.cvtColor(fr[y_lo:y_hi, :], cv2.COLOR_BGR2GRAY)
    mask = (g > 190) & (np.abs(cv2.Laplacian(g, cv2.CV_32F, ksize=3)) > 40)   # chữ trắng CÓ nét (loại nền phẳng sáng)
    rowcov = mask.sum(axis=1).astype(np.float32) / W
    k = max(3, (int(H * 0.012) | 1))
    rowcov = cv2.GaussianBlur(rowcov.reshape(-1, 1), (1, k), 0).ravel()
    if rowcov.size == 0 or float(rowcov.max()) < 0.035:        # không đủ "chữ" rộng → không có sub
        return None
    pk = int(rowcov.argmax())
    thr = float(rowcov.max()) * 0.35
    a = pk
    while a > 0 and rowcov[a - 1] > thr:
        a -= 1
    b = pk
    while b < len(rowcov) - 1 and rowcov[b + 1] > thr:
        b += 1
    y0, y1 = (y_lo + a) / H, (y_lo + b) / H
    if (y1 - y0) > 0.22:                                        # quá cao = nhiễu (không phải hàng chữ)
        return None
    cols = np.where(mask[a:b + 1, :].sum(axis=0) > 0)[0]   # mask đã crop từ y_lo → index a,b trực tiếp (= y_lo+a..y_lo+b cũ)
    if len(cols) < W * 0.1:
        return None
    x0, x1 = float(np.percentile(cols, 2)) / W, float(np.percentile(cols, 98)) / W
    return (max(0.0, y0 - 0.005), min(1.0, y1 + 0.006), max(0.0, x0 - 0.008), min(1.0, x1 + 0.008))


def phat_hien_hop_dong(video, log_fn=print, fps_sample=4.0, n_max=4000):
    """Dò HỘP sub ĐỘNG theo thời gian (sub DI CHUYỂN trong clip) → list (t_on, t_off, y0, y1, x0, x1) mỗi
    ĐOẠN vị-trí. Sample ~fps_sample fps (đọc tuần tự grab/read), dò box RẺ mỗi mẫu, GOM mẫu liên tiếp cùng
    vị-trí (tâm y gần ≤0.045, gap ≤0.8s) thành đoạn → blur/phụ đề bám theo. None nếu < 1 đoạn tin cậy.
    Tốc độ: fps_sample chỉnh qua env CHE_DONG_FPS (giãn THƯA = nhanh, hợp video hardsub ổn định); video DÀI
    tự GIÃN stride để ≤ n_max mẫu phủ HẾT (không kẹt/sót đuôi video dài)."""
    try:
        import cv2
        import numpy as np
        try:
            fps_sample = float(os.environ.get("CHE_DONG_FPS", "") or fps_sample)
        except ValueError:
            pass
        cap = cv2.VideoCapture(os.path.abspath(video))
        if not cap.isOpened():
            return None
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        nfr = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if nfr <= 0:
            cap.release()
            return None
        # GIÃN sampling: stride đủ thưa để TỔNG mẫu ≤ n_max phủ HẾT video dài (tăng tốc, không kẹt), nhưng
        # không dày hơn fps_sample yêu cầu. ceil(nfr/n_max) = số frame/mẫu tối thiểu để ≤ n_max mẫu.
        stride = max(1, int(round(fps / fps_sample)), -(-nfr // n_max))
        # Khe GỘP đoạn phải theo MẬT-ĐỘ-mẫu thực: video DÀI → stride lớn → mẫu cách nhau stride/fps giây.
        # Cố định 0.8s mà mẫu cách >0.8s (video >~8' do cap n_max) → KHÔNG mẫu nào gộp → mọi đoạn n=1 → BỎ
        # HẾT → 0 đoạn → lùi ASR oan (đã đo: video 72' mẫu cách 7.2s). Nới khe = max(0.8, mẫu×2.2).
        gap = max(0.8, stride / fps * 2.2)
        samples = []                                # (t, box|None)
        # GRAB tuần tự (KHÔNG seek per-frame: với sampling dày stride<GOP, cap.set phải giải-mã-lại GOP
        # nhiều lần → CHẬM hơn). Grab tuần tự là tối ưu cho giải mã; chỉ read frame được lấy mẫu.
        fidx = 0
        import time as _t2
        _lp = _t2.perf_counter()
        log_fn("🔎 Đang dò dải phụ đề…")   # video dài: báo tiến độ để thanh % không "đứng 1%"
        while fidx < nfr and len(samples) < n_max:
            if fidx % 512 == 0 and (_t2.perf_counter() - _lp) > 15.0:
                _lp = _t2.perf_counter()
                log_fn("🔎 Dò dải %d/%d khung…" % (fidx, nfr))
            if fidx % stride == 0:
                ok, fr = cap.read()
                if not ok or fr is None:
                    break
                samples.append((fidx / fps, _box_1frame_cheap(fr, cv2, np)))
            else:
                if not cap.grab():
                    break
            fidx += 1
        cap.release()
        if not samples:
            return None
        # GOM mẫu liên tiếp cùng vị-trí → đoạn [t_on, t_last, [boxes], yc(trung bình động)]
        segs, cur = [], None
        for t, box in samples:
            if box is None:
                if cur and (t - cur[1]) > gap:      # khe trống dài → đóng đoạn
                    segs.append(cur); cur = None
                continue
            yc = (box[0] + box[1]) / 2.0
            if cur and abs(yc - cur[4]) <= 0.045 and (t - cur[1]) <= gap:
                cur[1] = t; cur[2].append(box)
                cur[3] += 1; cur[4] += (yc - cur[4]) / cur[3]    # cập nhật yc trung bình (đỡ trôi)
            else:
                if cur:
                    segs.append(cur)
                cur = [t, t, [box], 1, yc]
        if cur:
            segs.append(cur)
        half = stride / fps / 2.0
        out = []
        for t_on, t_last, boxes, n, _ in segs:
            if n < 2:
                continue                            # đoạn 1 mẫu = nhiễu → bỏ
            y0 = float(np.percentile([b[0] for b in boxes], 10))
            y1 = float(np.percentile([b[1] for b in boxes], 90))
            x0 = float(np.percentile([b[2] for b in boxes], 10))
            x1 = float(np.percentile([b[3] for b in boxes], 90))
            # Khống chế chiều cao hộp động tránh phình to do bọt nước/nhiễu nền
            max_h = 0.12
            if (y1 - y0) > max_h:
                yc = (y0 + y1) / 2.0
                if yc >= 0.5:
                    y0 = y1 - max_h
                else:
                    y1 = y0 + max_h
            out.append((max(0.0, t_on - half), t_last + half, y0, y1, x0, x1))
        if not out:
            return None
        log_fn("🎯 Dò HỘP sub ĐỘNG (ảnh rẻ): %d đoạn vị-trí — blur + phụ đề bám theo sub di chuyển." % len(out))
        return out
    except Exception:
        return None


def phat_hien_dai_rapid(video, log_fn=print, n_frames=8):
    """Trả (y0_frac, y1_frac, H) dải sub, hoặc None nếu không đủ tin cậy."""
    try:
        import cv2
        import numpy as np
        import ocr_text
        if not ocr_text.co_rapidocr():
            return None
        eng = ocr_text._engine()
        cap = cv2.VideoCapture(os.path.abspath(video))
        if not cap.isOpened():
            return None
        nfr = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        if H <= 0 or nfr <= 0 or W <= 0:
            cap.release()
            return None
        y_off = int(H * 0.45)            # OCR ~55% dưới (sub có video nằm ~57% nên không cắt) → clustering tự tách
        sc = 1280.0 / W if W > 1280 else 1.0   # thu nhỏ cho det nhanh
        boxes = []   # mỗi box: (yc_frac, y0_frac, y1_frac, w_frac, xc_frac, frame_k)
        crops = []   # (k, crop_bgr) — GIỮ để dò CHỮ-ĐỔI (phân biệt SUB vs biển-hiệu-TĨNH) ở bước chọn cluster
        for k in range(n_frames):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(nfr * (k + 0.5) / n_frames))
            ok, fr = cap.read()
            if not ok or fr is None:
                continue
            crop = fr[y_off:, :]
            crops.append((k, crop))
            cim = cv2.resize(crop, (int(crop.shape[1] * sc), int(crop.shape[0] * sc))) if sc != 1.0 else crop
            try:
                out = eng(cim, use_cls=False, use_rec=False)   # DET-ONLY (chỉ box)
            except Exception:
                continue
            bxs = out[0] if isinstance(out, tuple) else out
            ch, cw = cim.shape[0], cim.shape[1]
            for box in (bxs or []):
                ys = [p[1] for p in box]
                xs = [p[0] for p in box]
                a = (min(ys) / ch * (H - y_off) + y_off) / H
                b = (max(ys) / ch * (H - y_off) + y_off) / H
                w = (max(xs) - min(xs)) / cw
                xc = (max(xs) + min(xs)) / 2.0 / cw
                boxes.append(((a + b) / 2, a, b, w, xc, k))
        cap.release()
        if len(boxes) < max(3, n_frames // 3):
            return None
        # CLUSTER 1D theo y-center: sort rồi gom các box cách nhau ≤ 0.03 (cùng 1 hàng text lặp qua frame).
        boxes.sort(key=lambda z: z[0])
        clusters, cur = [], [boxes[0]]
        for bx in boxes[1:]:
            if bx[0] - cur[-1][0] <= 0.03:
                cur.append(bx)
            else:
                clusters.append(cur)
                cur = [bx]
        clusters.append(cur)
        # Chọn cluster SUBTITLE. Ứng viên: nhiều frame (ổn định) × rộng (loại watermark/username hẹp góc).
        cand = []
        for cl in clusters:
            nf = len(set(z[5] for z in cl))                    # số frame khác nhau cluster xuất hiện
            avg_w = sum(z[3] for z in cl) / len(cl)            # bề rộng trung bình (sub rộng, watermark hẹp)
            yc = sum(z[0] for z in cl) / len(cl)              # vị trí dọc (thấp = gần đáy)
            if nf < 2 or avg_w < 0.12:                         # bỏ cluster thoáng qua / quá hẹp (góc)
                continue
            cand.append((cl, nf, avg_w, yc))
        if not cand:
            return None
        # KHÔI PHỤC che-sub GIỮA khung (regression: det-only + bottom-bias (0.6+yc) nuốt sub giữa split-screen
        # Douyin "2 ảnh chồng"). Phân biệt SUB (nội dung ĐỔI qua frame, MỌI vị trí kể cả giữa) vs biển-hiệu/logo/
        # watermark TĨNH (không đổi) bằng CHÊNH-LỆCH ẢNH giữa các frame (rẻ, KHÔNG OCR — rec quá chậm ~70s). Dải
        # đổi-ảnh nhiều = SUB. Có cluster đổi → chọn theo nhiều-frame×rộng (BỎ bottom-bias → sub giữa thắng).
        # KHÔNG cluster nào đổi (mọi cluster tĩnh / lỗi) → GIỮ logic cũ bottom-biased (0 regression). Tắt: CHE_GIUA=0.
        _crop_h = H - y_off
        def _doi_anh(cl):
            y0c = min(z[1] for z in cl); y1c = max(z[2] for z in cl)
            r0 = max(0, int(y0c * H - y_off) - 4); r1 = min(_crop_h, int(y1c * H - y_off) + 4)
            if r1 - r0 < 6:
                return 0.0
            ks = set(z[5] for z in cl); bands = []
            for _k, _crop in crops:
                if _k in ks:
                    bands.append(cv2.cvtColor(_crop[r0:r1, :], cv2.COLOR_BGR2GRAY))
            if len(bands) < 2:
                return 0.0
            difs = [float(np.mean(cv2.absdiff(bands[i], bands[i - 1]))) for i in range(1, len(bands))]
            return sum(difs) / len(difs)                       # thang xám 0-255; sub ĐỔI chữ → cao, banner tĩnh → ~0
        best = None
        if os.environ.get("CHE_GIUA", "1") != "0":
            try:
                _thr = float(os.environ.get("CHE_GIUA_THR", "4.0") or 4.0)
            except ValueError:
                _thr = 4.0
            changing = [(cl, nf * avg_w) for (cl, nf, avg_w, yc) in cand if _doi_anh(cl) >= _thr]
            if changing:
                best = max(changing, key=lambda x: x[1])[0]    # position-agnostic → sub GIỮA không bị đáy lấn
        if best is None:                                       # fallback: logic cũ (bottom-biased) — zero-risk
            best = max(cand, key=lambda c: c[1] * c[2] * (0.6 + c[3]))[0]
        y0 = float(np.percentile([z[1] for z in best], 10))   # bỏ outlier mép trên/dưới của cluster
        y1 = float(np.percentile([z[2] for z in best], 90))
        if y1 <= y0 or (y1 - y0) < 0.01:
            return None
        # Khống chế dải che mờ bị phình to do nhiễu nền (bọt nước, rót nước, vạch chia nước, tay chuyển động)
        max_h = 0.12  # Chiều cao tối đa hợp lý cho dải sub (12% khung hình)
        if (y1 - y0) > max_h:
            yc = (y0 + y1) / 2.0
            if yc >= 0.5:
                y0 = y1 - max_h  # Sub ở nửa dưới: giữ đáy, cắt bớt phần trên (nơi có bọt nước/nhiễu)
            else:
                y1 = y0 + max_h  # Sub ở nửa trên: giữ đỉnh, cắt bớt phần dưới
        # BỀ NGANG text: union x của MỌI box nằm trong dải y (cả 2 dòng sub, không chỉ cluster tốt nhất) →
        # blur ĐÚNG HỘP text (không full-width đè 2 mép). box: z[4]=xc, z[3]=w (đều phần trăm bề rộng khung).
        inb = [z for z in boxes if (y0 - 0.02) <= z[0] <= (y1 + 0.02)]
        lf = [z[4] - z[3] / 2 for z in inb] or [0.0]
        rt = [z[4] + z[3] / 2 for z in inb] or [1.0]
        x0 = max(0.0, float(np.percentile(lf, 5)) - 0.01)     # margin NHỎ 1% mỗi mép (đủ phủ nét chữ, không dư)
        x1 = min(1.0, float(np.percentile(rt, 95)) + 0.01)
        nf = len(set(z[5] for z in best))
        log_fn("🎯 Dò HỘP sub RapidOCR+clustering: y %.0f–%.0f%%, x %.0f–%.0f%% (%d/%d frame)."
               % (y0 * 100, y1 * 100, x0 * 100, x1 * 100, nf, n_frames))
        return (max(0.0, y0 - 0.006), min(1.0, y1 + 0.008), H, x0, x1)   # TIGHT: chỉ phủ nét chữ, không phình
    except Exception:
        return None


def phat_hien_chu_khac(video, main_sub_band=None, log_fn=print, sample_fps=2.0):
    """
    Dò các cụm chữ Trung khác (tiêu đề, chú thích...) xuất hiện tạm thời trong video (0.8s -> 10s)
    và không trùng với dải phụ đề chính (main_sub_band).
    """
    try:
        import cv2
        import numpy as np
        import ocr_text
        if not ocr_text.co_rapidocr():
            return []
        eng = ocr_text._engine()
        
        cap = cv2.VideoCapture(os.path.abspath(video))
        if not cap.isOpened():
            return []
            
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        nfr = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        if H <= 0 or W <= 0 or nfr <= 0:
            cap.release()
            return []
            
        stride = max(1, int(round(fps / sample_fps)))
        
        # main_sub_band format: (y0, y1, H, x0, x1)
        sub_y0 = main_sub_band[0] if main_sub_band else 0.80
        sub_y1 = main_sub_band[1] if main_sub_band else 0.99
        
        all_boxes = []
        fidx = 0
        while fidx < nfr:
            if fidx % stride == 0:
                ok, fr = cap.read()
                if not ok or fr is None:
                    break
                t = fidx / fps
                
                sc = 960.0 / W if W > 960 else 1.0
                if sc != 1.0:
                    fr_ocr = cv2.resize(fr, (960, int(H * sc)))
                else:
                    fr_ocr = fr
                
                try:
                    out, _ = eng(fr_ocr)
                except Exception:
                    fidx += 1
                    continue
                    
                if out:
                    for box, txt, score in out:
                        if not txt or score < 0.40:
                            continue
                        
                        # Chỉ lấy chữ Trung CJK
                        if not any("一" <= c <= "鿿" for c in txt):
                            continue
                            
                        xs = [p[0] for p in box]
                        ys = [p[1] for p in box]
                        
                        ch, cw = fr_ocr.shape[:2]
                        y0_frac = min(ys) / ch
                        y1_frac = max(ys) / ch
                        x0_frac = min(xs) / cw
                        x1_frac = max(xs) / cw
                        
                        yc = (y0_frac + y1_frac) / 2.0
                        if sub_y0 - 0.03 <= yc <= sub_y1 + 0.03:
                            continue
                            
                        all_boxes.append((t, y0_frac, y1_frac, x0_frac, x1_frac, txt))
            else:
                if not cap.grab():
                    break
            fidx += 1
            
        cap.release()
        
        if not all_boxes:
            return []
            
        segs = []
        for box in all_boxes:
            t, y0, y1, x0, x1, txt = box
            found = False
            for seg in segs:
                if t - seg['t_end'] <= 1.5:
                    seg_yc = (seg['y0'] + seg['y1']) / 2.0
                    seg_xc = (seg['x0'] + seg['x1']) / 2.0
                    yc = (y0 + y1) / 2.0
                    xc = (x0 + x1) / 2.0
                    if abs(yc - seg_yc) <= 0.04 and abs(xc - seg_xc) <= 0.05:
                        seg['t_end'] = t
                        seg['y0'] = min(seg['y0'], y0)
                        seg['y1'] = max(seg['y1'], y1)
                        seg['x0'] = min(seg['x0'], x0)
                        seg['x1'] = max(seg['x1'], x1)
                        seg['texts'].append(txt)
                        found = True
                        break
            if not found:
                segs.append({
                    't_start': t,
                    't_end': t,
                    'y0': y0,
                    'y1': y1,
                    'x0': x0,
                    'x1': x1,
                    'texts': [txt]
                })
                
        out_segs = []
        video_dur = nfr / fps
        max_dur = min(20.0, video_dur * 0.85)
        if max_dur < 5.0:
            max_dur = video_dur
            
        for seg in segs:
            dur = seg['t_end'] - seg['t_start']
            if 0.8 <= dur <= max_dur:
                ny0 = max(0.0, seg['y0'] - 0.005)
                ny1 = min(1.0, seg['y1'] + 0.008)
                nx0 = max(0.0, seg['x0'] - 0.01)
                nx1 = min(1.0, seg['x1'] + 0.01)
                
                t_on = max(0.0, seg['t_start'] - 0.2)
                t_off = seg['t_end'] + 0.2
                out_segs.append((t_on, t_off, ny0, ny1, nx0, nx1))
                
        log_fn("🎯 [CHE CHỮ KHÁC] Tìm thấy %d vùng chữ Trung khác xuất hiện tạm thời." % len(out_segs))
        return out_segs
    except Exception as e:
        log_fn("⚠ Lỗi khi dò chữ Trung khác: " + str(e))
        return []
