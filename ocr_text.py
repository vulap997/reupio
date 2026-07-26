# -*- coding: utf-8 -*-
"""Đọc TEXT phụ đề CỨNG bằng OCR — mặc định RapidOCR 3.x + PP-OCRv6 small (env OCR_MODEL); lùi
PP-OCRv4 mobile ONNX (rapidocr_onnxruntime, gói cũ) nếu thiếu v6. Thay cho ASR audio.

Dùng CHUNG band (dai_sub) + intervals (ocr_timing) như nhánh funasr_ocr: mỗi khoảng sub đổi → lấy 1 frame
giữa khoảng → crop DẢI sub → OCR → text. Lợi: chữ trên video = NGUYÊN VĂN (hơn ASR nghe nhầm/ảo giác),
không cần FunASR, RapidOCR khởi động nhanh. CHỈ chạy khi có hardsub (caller đã dò band + đủ khoảng);
không hardsub → caller tự lùi ASR (giọng nói thành văn bản).
"""
import os
import re as _re
import unicodedata as _ud
try:                                   # phồn→giản cho SO-SÁNH gộp cue (vendored zhconv ở app-src); thiếu → no-op
    from zhconv import convert as _zhc
except Exception:
    _zhc = None

_CMP_PUNCT = _re.compile(r"[·、，。！？：；…\s\"'“”‘’（）()《》〈〉「」『』\-—,.!?:;~•]")

# LỌC RÁC KÝ TỰ OCR: hardsub Trung nhưng rec đôi lúc nhả latin/số LẺ ở rìa chữ mờ ('你以后要多运动K', '5EE', 'E').
# Bỏ: (a) cụm latin/số ≤3 ký tự KỀ chữ Hán (đuôi/giữa) — nhiễu mép; (b) dòng THUẦN latin/số ngắn (≤4) — nhiễu hẳn.
# CHỈ áp khi câu có chữ Hán (video Trung) → KHÔNG đụng phụ đề tiếng Anh/Latin thật. Rẻ, chạy mỗi text rec.
_HAN = "一-鿿㐀-䶿"
_RAC_DUOI = _re.compile("(?<=[" + _HAN + "])[A-Za-z0-9]{1,3}$")             # đuôi latin/số kề Hán
_RAC_GIUA = _re.compile("(?<=[" + _HAN + "])[A-Za-z0-9]{1,2}(?=[" + _HAN + "])")  # kẹp giữa 2 chữ Hán
def _loc_rac_ocr(t):
    if not t:
        return t
    s = t.strip()
    if not _re.search("[" + _HAN + "]", s):                 # thuần latin/số → ngắn = nhiễu (K/E/5EE), dài = giữ (có thể chữ thật)
        return "" if len(_re.sub(r"\s", "", s)) <= 4 else s
    s = _RAC_GIUA.sub("", s)
    s = _RAC_DUOI.sub("", s)
    return s.strip()

def _norm_cmp(s):
    """Chuẩn-hoá để SO-SÁNH cue (KHÔNG đổi text gốc): NFKC → phồn→giản → bỏ dấu câu/khoảng trắng/ký tự trang trí.
    → '你好啊' == '你好啊！' == '你好啊。' khi gộp tại nguồn (hết cue lặp do OCR thêm/bớt 1 dấu câu)."""
    s = _ud.normalize("NFKC", s or "")
    if _zhc:
        try:
            s = _zhc(s, "zh-hans")
        except Exception:
            pass
    s = _CMP_PUNCT.sub("", s).strip()
    # bỏ RÁC Latin/số ĐẦU-ĐUÔI ngắn (≤2 ký tự) do OCR đọc viền/hiệu-ứng (vd '价值W', '好好ww', '4分量') — chỉ
    # để SO-SÁNH (không đổi text gốc); cap ≤2 để KHÔNG nuốt từ Latin thật (MVP, 4K...).
    s = _re.sub(r"^[A-Za-z0-9]{1,2}(?=[一-鿿])", "", s)
    s = _re.sub(r"(?<=[一-鿿])[A-Za-z0-9]{1,2}$", "", s)
    return s.strip()

_ENGINE = None


def co_rapidocr():
    """RapidOCR có sẵn? (chưa cài → caller lùi ASR). Nhận CẢ rapidocr(v6, 3.x) LẪN rapidocr_onnxruntime(v5, 1.4.x)."""
    try:
        import rapidocr  # noqa: F401  (PP-OCRv6, bản mới)
        return True
    except Exception:
        pass
    try:
        import rapidocr_onnxruntime  # noqa: F401  (PP-OCRv4 mobile, gói cũ — KHÔNG phải v5)
        return True
    except Exception:
        return False


def _add_cuda_dlls():
    """Thêm MỌI nvidia/*/bin (pip) vào DLL search path. onnxruntime-gpu cần cuFFT/cuRAND/cuSPARSE...
    NGOÀI bộ cuBLAS/cuDNN của whisper (phu_de._add_cuda_dll_dirs chỉ thêm 4 gói cho whisper) → glob HẾT
    để không thiếu DLL phụ thuộc (vd cufft64_11.dll). Idempotent."""
    import sys
    import glob as _g
    if sys.platform != "win32":
        return
    try:
        import importlib.util
        spec = importlib.util.find_spec("nvidia")
        if not spec or not spec.submodule_search_locations:
            return
        for root in spec.submodule_search_locations:
            for b in _g.glob(os.path.join(root, "*", "bin")):
                if not os.path.isdir(b):
                    continue
                try:
                    os.add_dll_directory(b)
                except Exception:
                    pass
                if b.lower() not in os.environ.get("PATH", "").lower():
                    os.environ["PATH"] = b + os.pathsep + os.environ.get("PATH", "")
    except Exception:
        pass


_ENGINE_LOCK = __import__("threading").Lock()


class _RapidV6:
    """Wrapper RapidOCR 3.x (PP-OCRv6 tiny/small/medium) → TRẢ ĐÚNG format rapidocr_onnxruntime 1.4.x để MỌI
    downstream (_doc/_doc_box/_doc_rec_sc + dai_sub_rapid) KHÔNG phải đổi. Mỗi call = per-call use_det/use_rec/use_cls:
      use_rec=False (det-only) → ([box,box,...], 0.0)          box = 4 điểm (dai_sub dò dải)
      use_det=False (rec-only) → ([(text,score),...], 0.0)
      det+rec (mặc định)       → ([(box,txt,score),...], 0.0)
    v6 rec nhanh ~10-18× v5-mobile trên CPU; đọc đúng cả sub nhỏ/mờ/nén (đã benchmark)."""

    def __init__(self, tier):
        from rapidocr import RapidOCR, OCRVersion, ModelType, EngineType
        mt = {"tiny": ModelType.TINY, "small": ModelType.SMALL, "medium": ModelType.MEDIUM}.get(tier, ModelType.TINY)
        params = {
            "Det.engine_type": EngineType.ONNXRUNTIME, "Det.ocr_version": OCRVersion.PPOCRV6, "Det.model_type": mt,
            "Rec.engine_type": EngineType.ONNXRUNTIME, "Rec.ocr_version": OCRVersion.PPOCRV6, "Rec.model_type": mt,
        }
        # OCR_THREADS: giới hạn luồng ORT/instance. 1 render đơn → -1 (tất cả core, nhanh nhất/video). Pool OCR song
        # song (ocr_bulk) đặt OCR_THREADS=2-4 → K instance × ít luồng ≈ tổng core, TRÁNH oversubscription (đo: limit
        # luồng → K=4 scale 2.6×; all-core → 0×). 0/rỗng = mặc định -1.
        try:
            _th = int(os.environ.get("OCR_THREADS", "") or 0)
        except ValueError:
            _th = 0
        if _th > 0:
            params["EngineConfig.onnxruntime.intra_op_num_threads"] = _th
        self._e = RapidOCR(params=params)

    def __call__(self, img, use_det=True, use_rec=True, use_cls=False):
        r = self._e(img, use_det=use_det, use_rec=use_rec, use_cls=use_cls)
        boxes = getattr(r, "boxes", None)
        if not use_rec:                                    # DET-ONLY → chỉ box (v5 use_rec=False)
            return (list(boxes) if boxes is not None else []), 0.0
        txts = list(getattr(r, "txts", None) or [])
        scores = list(getattr(r, "scores", None) or [])
        if not use_det:                                    # REC-ONLY → [(text, score)]
            return [(t, float(s)) for t, s in zip(txts, scores)], 0.0
        bx = list(boxes) if boxes is not None else [None] * len(txts)   # DET+REC → [(box, txt, score)]
        return [(b, t, float(s)) for b, t, s in zip(bx, txts, scores)], 0.0


def _engine():
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    # LOCK: warm-on-start (luồng nền) có thể song song job đầu → tránh tạo RapidOCR 2 lần.
    with _ENGINE_LOCK:
        if _ENGINE is not None:
            return _ENGINE
        # OCR_MODEL: 'v6-small'(MẶC ĐỊNH — điểm ngọt)|'v6-tiny'(nhanh nhưng SÓT/rác)|'v6-medium'(chuẩn nhất, chậm 2×)|'v5-mobile'.
        # Benchmark THẬT (user, video hardsub Trung khó): small ĐỌC ĐỦ + chính xác ≈ medium (14s) NHƯNG nhanh ≈ tiny
        # (13s) — tiny dò yếu SÓT ~1/3 câu + rác (厉/E/5EE), medium chuẩn nhất nhưng ~2× (29s). → small là default.
        # v6 (rapidocr 3.x) lỗi/thiếu gói → tự LÙI PP-OCRv4 mobile (rapidocr_onnxruntime; nhãn env 'v5-mobile'
        # là gọi theo thói quen — MODEL THẬT đi kèm gói cũ là ch_PP-OCRv4_det/rec) → KHÔNG bao giờ chết OCR.
        _model = (os.environ.get("OCR_MODEL", "v6-small") or "v6-small").strip().lower()
        if _model.startswith("v6"):
            try:
                _tier = _model.split("-", 1)[1] if "-" in _model else "small"
                _ENGINE = _RapidV6(_tier)
                return _ENGINE
            except Exception as _e:
                try:
                    print("LOG:⚠ PP-OCRv6 không dùng được (%s) → lùi PP-OCRv4 mobile." % str(_e)[:70], flush=True)
                except Exception:
                    pass
        _add_cuda_dlls()   # nạp HẾT DLL CUDA (pip nvidia-*) cho onnxruntime-gpu thấy (cuFFT/cuRAND/cuSPARSE...)
        from rapidocr_onnxruntime import RapidOCR
        cuda = False
        try:
            import onnxruntime as ort
            cuda = "CUDAExecutionProvider" in ort.get_available_providers()   # cần onnxruntime-gpu (laptop)
        except Exception:
            pass
        if cuda:
            try:
                _ENGINE = RapidOCR(det_use_cuda=True, rec_use_cuda=True, cls_use_cuda=True)   # GPU → ~5-10× CPU
            except Exception:
                _ENGINE = RapidOCR()
        else:
            _ENGINE = RapidOCR()   # CPU (model PP-OCR ONNX đi kèm)
    return _ENGINE


def _doc(img, eng):
    """OCR 1 ảnh BGR (numpy) → text gộp các dòng (gom theo HÀNG ~ y, trong hàng trái→phải)."""
    try:
        res, _ = eng(img, use_cls=False)   # sub không xoay → tắt direction classifier cho nhanh
    except TypeError:
        try:
            res, _ = eng(img)
        except Exception:
            return ""
    except Exception:
        return ""
    if not res:
        return ""
    its = []
    for box, txt, score in res:
        if not txt or (score is not None and score < 0.5):
            continue
        ys = sum(p[1] for p in box) / 4.0
        xs = sum(p[0] for p in box) / 4.0
        its.append((round(ys / 14.0), xs, txt.strip()))   # gom hàng (~14px) rồi trái→phải
    its.sort()
    return " ".join(t for _, _, t in its if t).strip()


def _doc_box(img, eng):
    """OCR 1 crop BGR → (text gộp dòng, box (y0,y1,x0,x1) phần trăm CỦA CROP bao chữ THẬT) — refine vị trí."""
    try:
        res, _ = eng(img, use_cls=False)
    except TypeError:
        try:
            res, _ = eng(img)
        except Exception:
            return "", None
    except Exception:
        return "", None
    if not res:
        return "", None
    ch, cw = img.shape[:2]
    its, ys0, ys1, xs0, xs1 = [], [], [], [], []
    for box, txt, score in res:
        if not txt or (score is not None and score < 0.5):
            continue
        yy = [p[1] for p in box]
        xx = [p[0] for p in box]
        its.append((round((sum(yy) / 4.0) / 14.0), sum(xx) / 4.0, txt.strip()))
        ys0.append(min(yy)); ys1.append(max(yy)); xs0.append(min(xx)); xs1.append(max(xx))
    if not its:
        return "", None
    its.sort()
    text = " ".join(t for _, _, t in its if t).strip()
    if not text:
        return "", None
    bb = (min(ys0) / ch, max(ys1) / ch, min(xs0) / cw, max(xs1) / cw)
    return text, bb


def _khoang_cach(a, b):
    """Khoảng cách sửa (Levenshtein) thuần Python — CJK chuỗi ngắn nên rẻ. Số ký tự cần thêm/xoá/đổi."""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if not la:
        return lb
    if not lb:
        return la
    prev = list(range(lb + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[lb]


def _giong(a, b):
    """CÙNG câu? Trùng tuyệt đối → True. Khác → coi cùng câu nếu CHỈ sai 1-2 ký tự (lỗi OCR lác đác: 我们/我门)
    TRÊN câu đủ dài (≥4 ký tự) → tránh tách câu mới giả. Câu NGẮN (<4) phải trùng tuyệt đối (không gộp nhầm
    上山/下山). Câu khác nghĩa = nhiều ký tự sai → KHÔNG gộp (ratio difflib SAI cho CJK, đo thật). Tắt: env OCR_FUZZY_MERGE=0."""
    if a == b:
        return True
    if not a or not b or os.environ.get("OCR_FUZZY_MERGE", "1") == "0":
        return False
    na, nb = _norm_cmp(a), _norm_cmp(b)        # so trên bản CHUẨN-HOÁ: bỏ dấu câu/phồn-giản → 1 khác biệt nhỏ = cùng câu
    if na and na == nb:
        return True
    m = min(len(na), len(nb))
    if m < 4:
        return False
    return _khoang_cach(na, nb) <= max(1, m // 8)


def _iv_merge(a, b):
    """CÙNG ĐOẠN cand (= cùng subtitle theo dò vị-trí) → gộp re-read kể cả lệch NHIỀU chữ (OCR drift nặng:
    周浦齐/用满齐). LOOSER hơn _giong vì cùng đoạn = gần chắc chắn cùng 1 câu. An toàn: sub KHÁC trong đoạn thô
    (nội dung khác hẳn) → không norm-equal/prefix/ratio≥0.72 → KHÔNG gộp → giữ nguyên (không mất sub)."""
    na, nb = _norm_cmp(a), _norm_cmp(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    s, l = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(s) >= 2 and (l.startswith(s) or l.endswith(s)):     # build dần: 谁在用 ⊂ 谁在用琵琶 (1 bản là tiền/hậu tố bản kia)
        return True
    if len(s) <= 5 and len(l) >= 2 * len(s) and s[:2] == l[:2]:  # mảnh fade-in misread (成为个 vs 成为一个…): chung 2 đầu + ngắn hẳn
        return True
    import difflib
    return difflib.SequenceMatcher(None, na, nb).ratio() >= 0.72


def _doc_rec(img, eng):
    """REC-ONLY (use_det=False): dải ĐÃ là 1 dòng sub → BỎ Detection. Đo thật: det+rec ~2.1s vs rec-only
    ~0.74s/call (~3× nhanh) + ĐÚNG HƠN (det hay crop lệch vài pixel → rec đoán nhầm; rec-only đọc nguyên dòng)."""
    return _doc_rec_sc(img, eng)[0]


def _doc_rec_sc(img, eng):
    """Như _doc_rec nhưng TRẢ THÊM score (min các dòng) → cho fallback theo độ tin cậy (mask-clean vs raw)."""
    try:
        res, _ = eng(img, use_det=False, use_cls=False)
    except TypeError:
        try:
            res, _ = eng(img, use_det=False)
        except Exception:
            return "", 0.0
    except Exception:
        return "", 0.0
    if not res:
        return "", 0.0
    out, scs = [], []
    for item in res:                          # use_det=False → item = (text, score)
        txt = item[0] if item else ""
        score = item[1] if len(item) > 1 else 1.0
        if txt and (score is None or score >= 0.5):
            out.append(str(txt).strip())
            scs.append(float(score) if score is not None else 1.0)
    # lọc rác OCR rìa: bỏ '#' (rec ra # cho ký tự mờ → 1 dòng thành 4 biến thể không merge) + nhiễu mép —…·
    text = " ".join(t for t in out if t).strip().replace("#", "").strip("—…·.•~ ")
    text = _loc_rac_ocr(text)          # + bỏ latin/số LẺ kề chữ Hán ('...运动K'→'...运动') / dòng nhiễu 'E','5EE'
    return text, (min(scs) if scs else 0.0)


def _ocr_clean(band, mk, eng, np, cv2):
    """OCR trên dải ĐÃ LÀM-SẠCH-NỀN nhưng GIỮ XÁM (anti-alias) — không nhị-phân-thuần (recognizer đọc kém).
    Dilate mask chữ (3×3) để phủ cả viền + cạnh anti-alias → whiten NỀN XA, giữ nguyên nét chữ. Trả (text, score)."""
    try:
        dm = cv2.dilate(mk.astype(np.uint8), np.ones((3, 3), np.uint8))
        gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
        gray[dm == 0] = 255                                       # bỏ nền (lửa/nước/tóc/texture) → nền trắng sạch
        tb = _trim_band(cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR), np, cv2)
        return _doc_rec_sc(tb, eng)
    except Exception:
        return "", 0.0


def _trim_band(band, np, cv2):
    """Cắt mép TRẮNG trái/phải trước rec (sub thật ~700-900px nhưng dải ~1920px) → rec xử lý ảnh HẸP hơn →
    nhanh thêm ~20-40%. Dò cột CÓ chữ (trắng+nét); hẹp bất thường / nền sáng không rõ → giữ NGUYÊN dải (an toàn)."""
    try:
        g = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
        mask = (g > 190) & (np.abs(cv2.Laplacian(g, cv2.CV_32F, ksize=3)) > 40)
        cols = np.where(mask.sum(axis=0) > max(1.0, band.shape[0] * 0.04))[0]
        if len(cols) < 5:
            return band
        x0 = max(0, int(cols.min()) - 10); x1 = min(band.shape[1], int(cols.max()) + 10)
        if x1 <= x0 or (x1 - x0) < band.shape[1] * 0.25:
            return band
        return band[:, x0:x1]
    except Exception:
        return band


def ocr_dong(video, log=print, on_seg=None):
    """HỢP NHẤT (1 lần): dò ĐOẠN vị-trí (dai_sub_rapid, RẺ) → mỗi đoạn crop hộp + RapidOCR det+rec cho TEXT
    + box CHÍNH XÁC. Đoạn KHÔNG đọc được chữ → LOẠI (lọc nhiễu). Gộp đoạn liền kề CÙNG text. Trả (segs, boxes):
      segs  = [(t_on, t_off, text)]            — drop-in cho asr_segments → dịch (timing đã KHỚP box).
      boxes = [(t_on, t_off, y0,y1,x0,x1)]     — blur ĐỘNG + đặt phụ đề bám đúng chỗ chữ DI CHUYỂN.
    Vị trí chuẩn (RapidOCR) + timing khớp text + đọc chữ ĐÚNG nơi nó di chuyển (fix 'mất câu'). [] nếu không hardsub."""
    import cv2
    import dai_sub_rapid
    import time as _tm
    _PROF = os.environ.get("OCR_PROFILE") == "1"
    pr = {"read": 0, "grab": 0, "skip": 0, "ocr": 0, "merged": 0, "new": 0, "hit": 0, "t_detect": 0.0,
          "t_dec": 0.0, "t_diff": 0.0, "t_trim": 0.0, "t_ocr": 0.0}
    _td = _tm.perf_counter()
    cand = dai_sub_rapid.phat_hien_hop_dong(video, log_fn=log)   # truyền log THẬT → tiến độ dò-dải hiện lên (video dài không "đứng 1%")
    pr["t_detect"] = _tm.perf_counter() - _td
    if not cand:
        return [], []
    eng = _engine()
    cap = cv2.VideoCapture(os.path.abspath(video))
    if not cap.isOpened():
        return [], []
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    nfr = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    import numpy as np
    segs, boxes, cue_si = [], [], []          # cue_si[i] = chỉ số đoạn cand của cue i (để gộp re-read CÙNG đoạn)
    _run0 = _last_log = _tm.perf_counter()
    # ĐỌC TUẦN TỰ + FRAME-DIFF: kiểm dải mỗi ~OCR_CHK giây; CHỈ OCR khi NỘI DUNG dải ĐỔI (mean absdiff > ngưỡng)
    # → mỗi câu OCR ~1 lần (sub đứng yên nhiều frame → skip, chi phí diff ≈0). OCR = REC-ONLY trên dải (bỏ det:
    # dải ĐÃ là 1 dòng → ~3× nhanh + đúng hơn) + cắt mép trắng. KHÔNG seek per-mốc (cap.set O(n) → O(n²) treo);
    # grab tuần tự = O(n). (Chỉnh: OCR_CHK nhịp kiểm, OCR_DIFF ngưỡng đổi-chữ.)
    chk = max(1, int(round(float(os.environ.get("OCR_CHK", "0.25") or 0.25) * fps)))
    xthr = float(os.environ.get("OCR_XOR", "0.012") or 0.012)   # mask chữ đổi > xthr (so câu ĐANG hiện) = đổi
    wmin = float(os.environ.get("OCR_WMIN", "0.004") or 0.004)  # white_ratio < wmin = dải TRỐNG (không chữ) → skip
    hyst = int(os.environ.get("OCR_HYST", "2") or 2)            # HYSTERESIS: mask đổi phải GIỮ ≥hyst nhịp mới OCR
    fidx, si, next_chk, pend = 0, 0, 0, 0                       # (lọc nền-rung/cháy-nổ thoáng qua 1 frame)
    prev_mask = None
    t_new = 0.0                                # mốc frame ĐẦU thấy mask câu mới = t_on THẬT (bỏ trễ hysteresis ~0.5s)
    iou_on = os.environ.get("OCR_IOU", "0") == "1"             # #6 dò-đổi IoU: test clip sạch +4 cue (ngưỡng 0.80 nhạy hơn absdiff) → MẶC ĐỊNH TẮT, opt-in + tune OCR_IOU_THR cho video glow/karaoke
    iou_same = float(os.environ.get("OCR_IOU_THR", "0.80") or 0.80)   # IoU ≥ ngưỡng = CÙNG câu
    cache_on = os.environ.get("OCR_CACHE", "1") == "1"        # #3 cache text theo fingerprint mask (IoU≥0.97 → khỏi OCR lại)
    _ocr_cache = []                                            # [(mask_bin 200×24, text)] gần đây, cap 12

    def _iou(a_bin, b_bin):
        inter = float(np.logical_and(a_bin, b_bin).sum())
        uni = float(np.logical_or(a_bin, b_bin).sum())
        return 1.0 if uni == 0 else inter / uni
    log("📖 Đang đọc phụ đề (OCR)…")   # để thanh % RỜI 1% ngay + video dài không "đứng"
    try:
        while si < len(cand):
            if (_tm.perf_counter() - _last_log) > 20.0:   # log tiến độ mỗi 20s (LUÔN bật — video dài không "đứng 1%")
                _last_log = _tm.perf_counter()
                _el = _last_log - _run0
                _eta = (_el * nfr / fidx - _el) if fidx > 0 and nfr > 0 else 0.0
                log("⏳ %d/%d khung · OCR=%d skip=%d new=%d · loop %.0fs · ETA~%.0f phút"
                    % (fidx, nfr, pr["ocr"], pr["skip"], pr["new"], _el, _eta / 60.0))
            a, b, y0, y1, x0, x1 = cand[si]
            fa, fb = int(a * fps), int(b * fps)
            if fidx > fb:                                 # qua đoạn → đoạn kế (reset so-sánh dải)
                si += 1; prev_mask = None; pend = 0
                continue
            if fidx < fa or fidx < next_chk:              # chưa tới nhịp kiểm → grab tuần tự (rẻ)
                _s = _tm.perf_counter()
                g = cap.grab()
                pr["t_dec"] += _tm.perf_counter() - _s; pr["grab"] += 1
                if not g:
                    break
                fidx += 1
                continue
            _s = _tm.perf_counter()
            ok, fr = cap.read()
            pr["t_dec"] += _tm.perf_counter() - _s; pr["read"] += 1
            if not ok or fr is None:
                break
            t = fidx / fps
            next_chk = fidx + chk
            fidx += 1
            py0 = max(0, int((y0 - 0.025) * H)); py1 = min(H, int((y1 + 0.025) * H))
            px0 = max(0, int((x0 - 0.04) * W)); px1 = min(W, int((x1 + 0.04) * W))
            if py1 - py0 < 8 or px1 - px0 < 20:
                continue
            band = fr[py0:py1, px0:px1]
            _s = _tm.perf_counter()
            # MẶT-NẠ CHỮ-TRẮNG (g>195): (1) white_ratio < wmin = KHÔNG có chữ ở dải → skip, KHÔNG OCR (khe câu);
            # (2) so mask với mask câu ĐANG HIỂN THỊ (KHÔNG phải frame-trước → không trôi tích lũy theo nền): đổi
            # > xthr = câu MỚI mới OCR. Mask cô lập chữ → nền ACTION động bị bỏ qua → "1 câu OCR ~1 lần".
            _g = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
            # mask = chữ TRẮNG CÓ VIỀN ĐEN (hardsub Trung) → loại nhiễu trắng KHÔNG viền (tia nước/cháy nổ/trời sáng):
            # pixel trắng (>195) mà GẦN pixel đen (<70 = viền) mới tính chữ → nền action sáng bị loại khỏi mask.
            _w = _g > 195
            if os.environ.get("OCR_NOUTLINE") == "1":
                _mk = _w                                  # tắt viền → mask trắng thuần (A/B test)
            else:
                _dk = cv2.dilate((_g < 70).astype(np.uint8), np.ones((7, 7), np.uint8))
                _mk = _w & (_dk > 0)
            wr = float(_mk.mean())
            if wr < wmin:                                 # dải TRỐNG (không chữ) → khe câu → KHÔNG OCR
                pr["t_diff"] += _tm.perf_counter() - _s
                pr["skip"] += 1
                prev_mask = None                          # sub kết thúc → câu kế là MỚI
                continue
            m = cv2.resize(_mk.astype(np.float32), (200, 24), interpolation=cv2.INTER_AREA)
            if prev_mask is None:
                same = False
            elif iou_on:
                same = _iou(m > 0.4, prev_mask > 0.4) >= iou_same   # IoU ỔN ĐỊNH với viền/glow/anti-alias (mean-absdiff nhạy → re-OCR thừa)
            else:
                same = float(np.abs(m - prev_mask).mean()) < xthr   # luồng cũ (mean absdiff)
            pr["t_diff"] += _tm.perf_counter() - _s
            if same:
                pend = 0                                  # về câu cũ → huỷ "đang đổi" (nền-rung thoáng qua)
                pr["skip"] += 1
                if segs and boxes[-1][1] < t:             # mask chữ y nguyên → cùng câu, kéo dài t_off
                    segs[-1] = (segs[-1][0], t, segs[-1][2])
                    pb = boxes[-1]; boxes[-1] = (pb[0], t, pb[2], pb[3], pb[4], pb[5])
                continue
            pend += 1                                     # mask KHÁC câu cũ → HYSTERESIS đợi ≥hyst nhịp xác nhận
            if pend == 1:
                t_new = t                                 # frame ĐẦU thấy mask mới = lúc chữ vừa HIỆN → t_on thật (trước trễ hysteresis + OCR-retry fade-in)
            if pend < hyst:                               # mới 1 nhịp = nghi nền-rung thoáng qua → CHƯA OCR
                pr["skip"] += 1
                continue
            _s = _tm.perf_counter()
            _mb = m > 0.4
            txt = None
            if cache_on:                                         # #3 mask ~trùng câu OCR gần đây → DÙNG LẠI text (khỏi OCR + hết drift)
                for _cm, _ct in _ocr_cache:
                    if _iou(_mb, _cm) >= 0.97:
                        txt = _ct; pr["hit"] += 1; break
            if txt is None:
                if os.environ.get("OCR_WHITE", "0") == "1":      # OPT-IN: test thật cho thấy mask-clean HẠI accuracy
                    # (recognizer đọc ảnh xám-whiten kém hơn ảnh gốc) → mặc định TẮT; chỉ bật cho video nền-nhiễu-nặng.
                    txt, _sc = _ocr_clean(band, _mk, eng, np, cv2)
                    if (not txt) or _sc < 0.80:                   # mờ/kém → fallback dải MÀU thô, chọn bản tin-cậy hơn
                        _t2, _s2 = _doc_rec_sc(_trim_band(band, np, cv2), eng)
                        if _s2 > _sc:
                            txt = _t2
                else:
                    txt = _doc_rec(_trim_band(band, np, cv2), eng)   # MẶC ĐỊNH: dải màu thô (raw đọc tốt hơn)
                pr["ocr"] += 1
                if txt and cache_on:                             # lưu fingerprint mask → text
                    _ocr_cache.append((_mb, txt))
                    if len(_ocr_cache) > 12:
                        _ocr_cache.pop(0)
            pr["t_ocr"] += _tm.perf_counter() - _s
            txt = _loc_rac_ocr(txt)                       # lọc rác latin/số lẻ (phủ MỌI nhánh rec: _doc_rec + _doc_rec_sc)
            if not txt:
                # REC RỖNG (chữ đang fade-in / 1 frame nhiễu) → KHÔNG chốt prev_mask/pend → nhịp SAU OCR LẠI.
                # (Trước: chốt prev_mask TRƯỚC khi check txt → OCR rỗng 1 lần là MẤT câu vĩnh viễn — sót sub đầu.)
                continue
            pend = 0
            prev_mask = m                                 # chỉ chốt câu KHI OCR RA CHỮ
            ry0 = max(0.0, y0 - 0.006); ry1 = min(1.0, y1 + 0.008)   # box = dải đoạn (rec-only không trả box)
            rx0 = max(0.0, x0 - 0.01); rx1 = min(1.0, x1 + 0.01)
            # GỘP re-read cùng 1 hardsub: (1) CÙNG ĐOẠN cand → looser _iv_merge (kể cả drift nặng), KHÔNG cần gap;
            # (2) khác đoạn nhưng _giong + gap≤2.0 (re-read FSM-cách-quãng). → fix regression e4e02b6 (gap≤1.2 +
            # re-OCR-giữa-câu tách cùng-sub thành nhiều cue = TRÙNG). Cũ: 1 OCR/đoạn → không trùng.
            ivm = os.environ.get("OCR_IVMERGE", "1") == "1"
            same_iv = ivm and bool(segs) and bool(cue_si) and cue_si[-1] == si
            gap = (t - boxes[-1][1]) if segs else 999.0
            # gộp re-read/HIỆN-DẦN cùng 1 dòng: _iv_merge khi CÙNG đoạn (mọi gap) HOẶC khác đoạn nhưng SÁT (gap≤1.5
            # — phụ đề hiện dần từng chữ làm ảnh đổi nhiều → dai_sub tách đoạn, nhưng vẫn cùng 1 câu); + _giong gap≤2.0
            if segs and ((ivm and _iv_merge(txt, segs[-1][2]) and (same_iv or gap <= 1.5))
                         or (_giong(txt, segs[-1][2]) and gap <= 2.0)):
                pr["merged"] += 1
                # giữ bản đọc DÀI hơn (drift đọc thiếu → bản dài đủ chữ hơn); kéo dài t_off
                keep = segs[-1][2] if len(segs[-1][2]) >= len(txt) else txt
                segs[-1] = (segs[-1][0], t, keep)
                pb = boxes[-1]
                # HỘP = BAO TRÙM cả vòng đời dòng (min/max) → phụ đề hiện-dần rộng dần thì che (blur động CHE_DONG=1)
                # phủ ĐỦ bề rộng chữ, không hụt. Vị-trí xác định 1 lần/dòng dùng cho cả timing lẫn che.
                ny0 = min(pb[2], ry0)
                ny1 = max(pb[3], ry1)
                # Khống chế chiều cao tránh phình to do bọt nước/nhiễu nền khi gộp cue
                max_h = 0.15
                if (ny1 - ny0) > max_h:
                    nyc = (ny0 + ny1) / 2.0
                    if nyc >= 0.5:
                        ny0 = ny1 - max_h
                    else:
                        ny1 = ny0 + max_h
                boxes[-1] = (pb[0], t, ny0, ny1, min(pb[4], rx0), max(pb[5], rx1))
            else:
                pr["new"] += 1
                # t_on = t_new (lúc chữ vừa HIỆN) thay vì t (sau trễ hysteresis ~0.5s) → phụ đề Việt hiện SỚM đúng
                # nhịp gốc. Cho phép t_new=0.0 (chữ có từ FRAME ĐẦU): trước dùng '0.0<' (lớn hơn nghiêm) loại t_new=0.0
                # → cue ĐẦU rơi về t = trễ 1 nhịp kiểm (~0.25s) so với chữ Trung. '0.0<=' để cue đầu hiện đúng 0.0.
                t0 = t_new if (os.environ.get("OCR_BACKDATE", "1") == "1" and 0.0 <= t_new <= t) else t
                # BÙ TRỄ granularity — XÁC ĐỊNH độ trễ, không đoán: onset chỉ bắt được tại mốc KIỂM (mỗi chk frame =
                # OCR_CHK giây). Chữ thật hiện ở đâu đó trong (mốc-kiểm-trước, t_new] → độ trễ ~PHÂN BỐ ĐỀU, kỳ vọng
                # = ½ khoảng-kiểm = chk/(2·fps). Lùi t_on đúng bằng ĐÓ (tính từ fps+chk THẬT của video) → sub Việt
                # hiện đúng nhịp chữ Trung. Hệ số OCR_SUB_LEAD (mặc định 0.5 = midpoint; 0 = tắt; 1.0 = lùi cả nhịp).
                # CHỈ lùi khi KHÔNG chồng câu trước. Áp cho CẢ box (blur) bên dưới → blur+sub vẫn đồng bộ.
                _lead = (chk / fps) * float(os.environ.get("OCR_SUB_LEAD", "0.5") or 0)
                if _lead > 0 and (t0 - _lead) >= (segs[-1][1] if segs else 0.0):
                    t0 = max(0.0, t0 - _lead)
                if segs and t0 < segs[-1][1]:
                    t0 = t
                segs.append((t0, t, txt))                 # câu MỚI
                boxes.append((t0, t, ry0, ry1, rx0, rx1))
                cue_si.append(si)
                if on_seg:
                    on_seg(len(segs), t0, t, txt)
                if len(segs) % 100 == 0:               # mỗi 100 câu → log mốc (người dùng dễ theo dõi + thanh % nhích)
                    _elc = _tm.perf_counter() - _run0
                    _etc = (_elc * nfr / fidx - _elc) if (fidx > 0 and nfr > 0) else 0.0
                    log("📖 Đã đọc %d câu · %d/%d khung · ETA~%.0f phút" % (len(segs), fidx, nfr, _etc / 60.0))
    finally:
        cap.release()
    if _PROF:
        log("📊 PROFILE: detect=%.0fs | read=%d grab=%d skip(diff)=%d | OCR-call=%d new=%d cached=%d | "
            "decode=%.0fs diff=%.0fs trim=%.0fs ocr=%.0fs"
            % (pr["t_detect"], pr["read"], pr["grab"], pr["skip"], pr["ocr"], pr["new"], pr["merged"],
               pr["t_dec"], pr["t_diff"], pr["t_trim"], pr["t_ocr"]))
    return segs, boxes


def ocr_theo_khoang(video, intervals, band, log=print, on_seg=None):
    """band = (y0f, y1f[, H]) phần trăm chiều cao chứa dải sub. intervals = [(t_on, t_off)] (giây).
    Trả list TUPLE (t_on, t_off, text) — GIỐNG funasr_asr.asr_theo_khoang để drop-in vào asr_segments.
    Câu OCR TRÙNG khoảng liền trước → gộp (kéo dài t_off)."""
    import cv2
    eng = _engine()
    cap = cv2.VideoCapture(os.path.abspath(video))
    if not cap.isOpened():
        return []
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    y0 = max(0, int(H * band[0]) - 6)
    y1 = min(H, int(H * band[1]) + 6)
    segs = []
    try:
        for a, b in intervals:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int((a + b) / 2.0 * fps))
            ok, fr = cap.read()
            if not ok or fr is None:
                continue
            txt = _doc(fr[y0:y1, :], eng)
            if not txt:
                continue
            if segs and txt == segs[-1][2]:        # cùng câu kéo dài qua nhiều khoảng → gộp (kéo dài t_off)
                segs[-1] = (segs[-1][0], float(b), txt)
                continue
            segs.append((float(a), float(b), txt))
            if on_seg:
                on_seg(len(segs), float(a), float(b), txt)
    finally:
        cap.release()
    return segs
