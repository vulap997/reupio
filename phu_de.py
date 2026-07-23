# -*- coding: utf-8 -*-
"""
Tạo phụ đề tiếng Việt cho video: nhận dạng giọng nói tiếng Trung bằng faster-whisper
rồi dịch sang tiếng Việt qua Google Translate. Xuất file .srt.
"""

import json
import os
import sys
import urllib.parse
import urllib.request

_MODEL = None
_MODEL_SIZE = None
_MODEL_DEVICE = None   # "cuda" | "cpu" — biết model đang nạp ở đâu (cho CPU-fallback khi GPU lỗi)
_GPU_TAT = False       # đã NGỪNG thử GPU cả phiên (lỗi cố định: thiếu cuDNN / lỗi liên tiếp quá ngưỡng)
_GPU_LOI_LIEN = 0      # số lần GPU lỗi giữa chừng LIÊN TIẾP (reset về 0 khi 1 lượt GPU trót lọt)
_GPU_GIOI_HAN = 2      # lỗi liên tiếp tới ngưỡng này → tắt GPU cả phiên; dưới ngưỡng → lượt sau VẪN thử lại GPU
_DLL_DIRS_DONE = False


def _add_cuda_dll_dirs():
    """Windows: thêm bin của nvidia-cuda-runtime/cublas/cudnn/nvrtc-cu12 (pip) vào DLL search path.
    CTranslate2 chỉ tự thêm thư mục của CHÍNH nó, KHÔNG thêm site-packages/nvidia/*/bin → không
    làm bước này thì cài cuBLAS/cuDNN xong whisper vẫn báo 'cublas64_12.dll not found'. Chạy 1 lần.
    LƯU Ý: cublas64_12.dll PHỤ THUỘC cudart64_12.dll (nvidia.cuda_runtime) → thiếu cuda_runtime thì
    cublas 'cannot be loaded' dù file có sẵn. Thêm cuda_runtime TRƯỚC để nó nằm trong search path."""
    global _DLL_DIRS_DONE
    if _DLL_DIRS_DONE or sys.platform != "win32":
        return
    _DLL_DIRS_DONE = True
    try:
        import importlib.util
        for pkg in ("nvidia.cuda_runtime", "nvidia.cublas", "nvidia.cudnn", "nvidia.cuda_nvrtc"):
            spec = importlib.util.find_spec(pkg)
            if not spec or not spec.submodule_search_locations:
                continue
            for loc in spec.submodule_search_locations:
                b = os.path.join(loc, "bin")
                if os.path.isdir(b):
                    os.add_dll_directory(b)
                    # QUAN TRỌNG: ctranslate2 (C++) nạp cuBLAS/cuDNN bằng LoadLibrary → tìm theo PATH,
                    # KHÔNG đọc add_dll_directory (chỉ loader Python dùng). Không prepend PATH thì
                    # 'cublas64_12.dll cannot be loaded' lúc TRANSCRIBE (model nạp OK nhưng compute fail).
                    if b.lower() not in os.environ.get("PATH", "").lower():
                        os.environ["PATH"] = b + os.pathsep + os.environ.get("PATH", "")
    except Exception:
        pass


def _dich_vi(text, sl="zh-CN", tl=None):
    text = (text or "").strip()
    if not text:
        return ""
    if tl is None:
        tl = (os.environ.get("TARGET_LANG") or "vi").strip().lower()
        try:                                   # cho MỌI ngôn ngữ đích trong bảng ngon_ngu.LANGS (Google phủ hết)
            import ngon_ngu
            if tl not in ngon_ngu.HO_TRO:
                tl = "vi"
        except Exception:
            if tl not in ("vi", "en", "ko"):
                tl = "vi"
    try:
        url = ("https://translate.googleapis.com/translate_a/single"
               "?client=gtx&sl=" + sl + "&tl=" + tl + "&dt=t&q=" + urllib.parse.quote(text))
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.loads(r.read().decode("utf-8"))
        return "".join(s[0] for s in d[0] if s and s[0]).strip()
    except Exception:
        return text


def _ts(giay: float) -> str:
    if giay < 0:
        giay = 0
    h = int(giay // 3600)
    m = int((giay % 3600) // 60)
    s = int(giay % 60)
    ms = int((giay - int(giay)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _whisper_device():
    """Ưu tiên GPU NVIDIA ('cuda','float16'); không có thì về CPU ('cpu','int8').
    Dò bằng CTranslate2 (engine THẬT của faster-whisper), KHÔNG qua torch — vì torch
    bản CPU-only vẫn cho Whisper chạy GPU qua CTranslate2 (chỉ cần cuDNN/cuBLAS CUDA12).
    Máy không GPU (vd máy dev) -> get_cuda_device_count()=0 -> tự về CPU."""
    try:
        import ctranslate2
        if not _GPU_TAT and ctranslate2.get_cuda_device_count() > 0:
            # int8_float16: trọng số lưu int8 (~NỬA VRAM của float16) nhưng PHÉP TÍNH vẫn float16
            # → large-v3-turbo vừa card 4GB (tránh OOM), chất lượng gần như không đổi.
            # Env WHISPER_COMPUTE đổi được (vd "float16" cho card VRAM lớn).
            ct = (os.environ.get("WHISPER_COMPUTE") or "int8_float16").strip()
            return "cuda", ct
    except Exception:
        pass
    return "cpu", "int8"


_MODEL_LOCK = __import__("threading").Lock()


def _get_model(model_size, log):
    global _MODEL, _MODEL_SIZE, _MODEL_DEVICE, _GPU_TAT
    dev, ct = _whisper_device()    # 'cuda' nếu GPU sẵn & CHƯA bị tắt phiên, ngược lại 'cpu'
    # Tái dùng cache khi ĐÚNG size VÀ ĐÚNG thiết bị mong muốn. Nếu trước đó đã lùi CPU mà GPU lại
    # được phép thử (chưa quá ngưỡng lỗi) → dev='cuda' ≠ cache 'cpu' → NẠP LẠI GPU = kiểm tra lại GPU.
    if _MODEL is not None and _MODEL_SIZE == model_size and _MODEL_DEVICE == dev:
        return _MODEL
    # LOCK: warm-on-start (luồng nền) có thể chạy song song job đầu → tránh nạp Whisper 2 lần (phí RAM/thời gian).
    with _MODEL_LOCK:
        if _MODEL is not None and _MODEL_SIZE == model_size and _MODEL_DEVICE == dev:
            return _MODEL    # luồng khác đã nạp xong khi ta chờ lock
        _add_cuda_dll_dirs()   # Windows: cho ctranslate2 thấy cuBLAS/cuDNN (pip) trước khi nạp
        from faster_whisper import WhisperModel
        log(f"[phu de] Nap model '{model_size}' tren {dev} (lan dau se tai ve)...")
        try:
            _MODEL = WhisperModel(model_size, device=dev, compute_type=ct)
            _MODEL_DEVICE = dev
            if dev == "cuda":
                log(f"[phu de] Whisper chay GPU (cuda/{ct}).")
        except Exception as e:
            # Lỗi khi NẠP GPU (thiếu cuDNN/CUDA libs) = lỗi CỐ ĐỊNH → tắt GPU cả phiên rồi dùng CPU.
            log(f"[phu de] GPU loi khi nap ({str(e)[:80]}) -> tat GPU ca phien, dung CPU.")
            if dev == "cuda":
                _GPU_TAT = True
            _MODEL = WhisperModel(model_size, device="cpu", compute_type="int8")
            _MODEL_DEVICE = "cpu"
        _MODEL_SIZE = model_size
        return _MODEL


_BATCHED = None        # BatchedInferencePipeline bọc _MODEL (opt-in WHISPER_BATCH) — tăng tốc ASR ~3-4× GPU
_BATCHED_FOR = None    # id(model) đang được bọc → tái tạo khi model/thiết bị đổi


def _transcribe(model, audio, log=None, **kw):
    """transcribe() có tùy chọn BatchedInferencePipeline (env WHISPER_BATCH=N, N>=1 = BẬT + batch_size=N).
    Mặc định TẮT (WHISPER_BATCH=0) → hành vi Y HỆT cũ (tool bán KHÔNG đổi). Chỉ batched khi đang GPU
    (batched cho GPU; CPU không lợi). OOM/không hỗ trợ lúc SETUP → tự LÙI transcribe thường; OOM lúc LẶP
    generator sẽ do caller (asr_segments) bắt → lùi CPU. Trả (segments, info) như model.transcribe."""
    global _BATCHED, _BATCHED_FOR
    try:
        bs = int(os.environ.get("WHISPER_BATCH", "0") or "0")
    except ValueError:
        bs = 0
    if bs >= 1 and _MODEL_DEVICE == "cuda":
        try:
            from faster_whisper import BatchedInferencePipeline
            if _BATCHED is None or _BATCHED_FOR != id(model):
                _BATCHED = BatchedInferencePipeline(model=model)
                _BATCHED_FOR = id(model)
            r = _BATCHED.transcribe(audio, batch_size=bs, **kw)
            if log:
                log("[phu de] Whisper BATCHED (batch_size=%d) tren GPU." % bs)
            return r
        except Exception as e:
            if log:
                log("[phu de] Batched loi (%s) -> transcribe thuong." % str(e)[:80])
            _BATCHED = None
    return model.transcribe(audio, **kw)


def _dang_gpu():
    """Model whisper đang nạp trên GPU? (để caller biết có nên thử lùi CPU khi lỗi giữa chừng)."""
    return _MODEL_DEVICE == "cuda"


def _ep_cpu(model_size, log):
    """Ép nạp lại model trên CPU cho lượt nhận dạng NÀY — khi GPU lỗi/treo GIỮA LÚC nhận dạng
    (OOM 4GB, cuDNN…). KHÔNG khóa GPU vĩnh viễn: lượt sau `_get_model` sẽ tự thử lại GPU (trừ khi
    `_bao_gpu_loi` đã đẩy lỗi quá ngưỡng → `_GPU_TAT`). (Mỗi video render là 1 tiến trình riêng nên
    biến này cũng reset mỗi video.)"""
    global _MODEL, _MODEL_SIZE, _MODEL_DEVICE
    import gc
    from faster_whisper import WhisperModel
    _MODEL = None          # bỏ tham chiếu model GPU → CTranslate2 giải phóng VRAM
    gc.collect()
    log(f"[phu de] Nap lai model '{model_size}' tren CPU (int8)...")
    _MODEL = WhisperModel(model_size, device="cpu", compute_type="int8")
    _MODEL_SIZE = model_size
    _MODEL_DEVICE = "cpu"
    return _MODEL


def _bao_gpu_loi(log):
    """Gọi khi GPU lỗi GIỮA CHỪNG lúc nhận dạng (đã lùi CPU cho lượt này). Đếm lỗi LIÊN TIẾP;
    quá ngưỡng `_GPU_GIOI_HAN` → tắt GPU cả phiên (lỗi cố định). Dưới ngưỡng → lượt SAU vẫn thử lại GPU."""
    global _GPU_LOI_LIEN, _GPU_TAT
    _GPU_LOI_LIEN += 1
    if _GPU_LOI_LIEN >= _GPU_GIOI_HAN:
        _GPU_TAT = True
        log("[phu de] GPU loi %d lan lien tiep -> NGUNG thu GPU (dung CPU)." % _GPU_LOI_LIEN)
    else:
        log("[phu de] GPU loi (lan %d/%d) -> luot sau VAN thu lai GPU." % (_GPU_LOI_LIEN, _GPU_GIOI_HAN))


def _bao_gpu_ok():
    """Gọi khi 1 lượt nhận dạng trên GPU TRÓT LỌT → reset đếm lỗi (lỗi trước đó chỉ là transient)."""
    global _GPU_LOI_LIEN
    _GPU_LOI_LIEN = 0


def tao_phu_de(video_path, srt_out, model_size="small", lang_goc="zh", dich=True, log=print):
    try:
        model = _get_model(model_size, log)
    except Exception as e:
        log(f"[phu de] Khong nap duoc model: {e}")
        return ""

    log(f"[phu de] Dang nhan dang giong noi ({lang_goc})...")
    try:
        segments, info = _transcribe(
            model, video_path, log=log, language=lang_goc, task="transcribe",
            vad_filter=True, vad_parameters={"min_silence_duration_ms": 500},
        )
    except Exception as e:
        log(f"[phu de] Loi nhan dang: {e}")
        return ""

    dong = []
    idx = 1
    for seg in segments:
        text = (seg.text or "").strip()
        if not text:
            continue
        if dich:
            text = _dich_vi(text, sl="zh-CN") or text
        dong.append(f"{idx}\n{_ts(seg.start)} --> {_ts(seg.end)}\n{text}\n")
        idx += 1

    if not dong:
        log("[phu de] Khong co loi thoai nhan dang duoc.")
        return ""

    os.makedirs(os.path.dirname(srt_out) or ".", exist_ok=True)
    with open(srt_out, "w", encoding="utf-8") as f:
        f.write("\n".join(dong))
    log(f"[phu de] Da tao {idx-1} dong phu de: {srt_out}")
    return srt_out
