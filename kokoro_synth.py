# -*- coding: utf-8 -*-
"""Worker LỒNG TIẾNG TIẾNG ANH bằng Kokoro-82M (kokoro-onnx, Apache-2.0).

Chạy trong venv RIÊNG `.venv_kokoro` (gọi qua subprocess từ localize.long_tieng_kokoro — mirror
F5/OmniVoice). Đọc texts.json → sinh seg_<i>.wav (24k mono 16-bit) vào --out-dir.

GPU (nếu có onnxruntime-gpu + CUDAExecutionProvider): preload_dlls + ép ONNX_PROVIDER=CUDA + model fp32
(RTX 3050 ~×2.6 realtime). Không có GPU: onnxruntime CPU + model int8. Tự lùi CPU nếu CUDA fail.

LƯU Ý: KHÔNG chuẩn-hoá kiểu tiếng Việt — text đã là tiếng Anh; Kokoro/misaki tự G2P (espeak-ng bundle
qua espeakng-loader). Model + voices.bin do cai_kokoro.py tải về KOKORO_DIR.
"""
import argparse
import json
import os
import sys
import wave

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SR = 24000


def _kokoro_dir():
    """Thư mục GHI ĐƯỢC + bền update chứa model (giống localize._piper_dir_rw)."""
    lic = os.environ.get("LIC_CACHE_DIR", "").strip()
    if lic:
        return os.path.join(lic, "runtime", "kokoro")
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kokoro_models")
    try:
        os.makedirs(d, exist_ok=True)
        t = os.path.join(d, ".wtest"); open(t, "w").close(); os.remove(t)
        return d
    except Exception:
        return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
                            "ViralCrawl", "kokoro")


KOKORO_DIR = _kokoro_dir()


def _co_cuda():
    try:
        import onnxruntime as o
        return "CUDAExecutionProvider" in o.get_available_providers()
    except Exception:
        return False


def _nap_cuda_dll():
    """Nạp DLL CUDA/cuDNN từ gói nvidia-*-cu12 (cách chuẩn ORT 1.22+)."""
    try:
        import onnxruntime as o
        if hasattr(o, "preload_dlls"):
            o.preload_dlls()
            return
    except Exception:
        pass
    try:                                  # fallback: add_dll_directory từng nvidia/<lib>/bin
        import nvidia
        for base in list(getattr(nvidia, "__path__", [])):
            for sub in ("cudnn", "cublas", "cuda_runtime", "cuda_nvrtc", "cufft"):
                p = os.path.join(base, sub, "bin")
                if os.path.isdir(p):
                    try: os.add_dll_directory(p)
                    except Exception: pass
                    os.environ["PATH"] = p + os.pathsep + os.environ.get("PATH", "")
    except Exception:
        pass


def _chon_model(dung_gpu):
    """Trả (onnx_path, voices_path). GPU ưu tiên fp32; CPU ưu tiên int8; lùi cái nào có."""
    fp32 = os.path.join(KOKORO_DIR, "kokoro-v1.0.onnx")
    int8 = os.path.join(KOKORO_DIR, "kokoro-v1.0.int8.onnx")
    voices = os.path.join(KOKORO_DIR, "voices-v1.0.bin")
    order = [fp32, int8] if dung_gpu else [int8, fp32]
    for m in order:
        if os.path.isfile(m):
            return m, voices
    return (order[0], voices)


def _load_kokoro(log):
    """Nạp Kokoro — thử GPU trước (nếu có CUDA), lỗi thì lùi CPU. Trả (kokoro, dung_gpu)."""
    from kokoro_onnx import Kokoro
    if _co_cuda() and os.environ.get("KOKORO_CPU") != "1":
        try:
            _nap_cuda_dll()
            os.environ["ONNX_PROVIDER"] = "CUDAExecutionProvider"
            m, v = _chon_model(True)
            k = Kokoro(m, v)
            provs = k.sess.get_providers()
            if "CUDAExecutionProvider" in provs:
                log("[kokoro] GPU (CUDA) — %s" % os.path.basename(m))
                return k, True
            log("[kokoro] CUDA không vào session → lùi CPU.")
        except Exception as e:
            log("[kokoro] GPU lỗi (%s) → lùi CPU." % str(e)[:80])
    os.environ.pop("ONNX_PROVIDER", None)   # ép CPU
    os.environ["ONNX_PROVIDER"] = "CPUExecutionProvider"
    m, v = _chon_model(False)
    k = Kokoro(m, v)
    log("[kokoro] CPU — %s" % os.path.basename(m))
    return k, False


def _ghi_wav(samp, path):
    import numpy as np
    a = (np.clip(np.asarray(samp, dtype="float32"), -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(a.tobytes())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--texts", required=True, help="JSON list lời thoại tiếng Anh (theo thứ tự câu)")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--voice", default="af_heart")
    ap.add_argument("--speed", type=float, default=1.0)
    a = ap.parse_args()

    def log(m):
        print(m); sys.stdout.flush()

    texts = json.load(open(a.texts, encoding="utf-8"))
    os.makedirs(a.out_dir, exist_ok=True)
    voice = (a.voice or "af_heart").strip() or "af_heart"
    try:
        k, _gpu = _load_kokoro(log)
    except Exception as e:
        log("[kokoro] Không nạp được Kokoro: %s" % str(e)[:120])
        sys.exit(1)

    n = 0
    for i, text in enumerate(texts):
        text = (text or "").strip()
        if not text:
            continue
        try:
            samp, sr = k.create(text, voice=voice, speed=a.speed, lang="en-us")
            _ghi_wav(samp, os.path.join(a.out_dir, "seg_%d.wav" % i))
            n += 1
        except Exception as e:
            log("[kokoro] bỏ câu %d (%s)" % (i, str(e)[:60]))
        if (i + 1) % 20 == 0 or i == len(texts) - 1:
            log("[kokoro] đọc %d/%d" % (i + 1, len(texts)))
    log("[kokoro] xong %d câu." % n)


if __name__ == "__main__":
    main()
