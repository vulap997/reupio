# -*- coding: utf-8 -*-
"""Cài Kokoro-82M (kokoro-onnx) — lồng tiếng TIẾNG ANH — vào venv RIÊNG .venv_kokoro.

Khác OmniVoice: Kokoro chạy ĐƯỢC cả CPU → cài cho MỌI máy (engine dub mặc định bản tiếng Anh).
- MÁY GPU NVIDIA: onnxruntime-gpu 1.22 (CUDA 12) + cuDNN 9.5.1.17 (PIN — 9.23 vỡ conv) + nvidia cu12 libs
  + model fp32 (~310MB) → RTX 3050 ~×2.6 realtime.
- MÁY KHÔNG GPU: onnxruntime CPU (kokoro-onnx tự kéo) + model int8 (~89MB) → ~×0.5 realtime.
Tách .venv_kokoro để KHÔNG đụng onnxruntime CPU của venv chính (RapidOCR dùng). Idempotent.
Model + voices.bin tải về KOKORO_DIR (LIC_CACHE_DIR/runtime/kokoro — ghi được, bền update).
Chạy: MediaCrawler\\.venv\\Scripts\\python.exe cai_kokoro.py  (web_app gọi nền lúc khởi động).
"""
import os
import shutil
import subprocess
import sys
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
# .venv_kokoro Ở userData/runtime (BỀN qua update, GHI ĐƯỢC — app-src/Program Files read-only) — giống .venv_f5.
_LIC = os.environ.get("LIC_CACHE_DIR", "").strip()
_RUNTIME = os.path.join(_LIC, "runtime") if _LIC else HERE
KOKORO_VENV = os.path.join(_RUNTIME, ".venv_kokoro")
KOKORO_PY = os.path.join(KOKORO_VENV, "Scripts", "python.exe")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_REL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
_FP32 = "kokoro-v1.0.onnx"
_INT8 = "kokoro-v1.0.int8.onnx"
_VOICES = "voices-v1.0.bin"


def _kokoro_dir():
    lic = os.environ.get("LIC_CACHE_DIR", "").strip()
    if lic:
        return os.path.join(lic, "runtime", "kokoro")
    d = os.path.join(HERE, "kokoro_models")
    try:
        os.makedirs(d, exist_ok=True)
        t = os.path.join(d, ".wtest"); open(t, "w").close(); os.remove(t)
        return d
    except Exception:
        return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
                            "ViralCrawl", "kokoro")


KOKORO_DIR = _kokoro_dir()


def _uv():
    cand = os.path.join(HERE, "desktop", "vendor", "uv.exe")
    return cand if os.path.exists(cand) else (shutil.which("uv") or "uv")


def co_nvidia():
    try:
        r = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True,
                           creationflags=_NO_WINDOW, timeout=10)
        return r.returncode == 0 and "GPU" in (r.stdout or "")
    except Exception:
        return False


def da_cai():
    """venv + import kokoro_onnx OK + có model + voices."""
    if not os.path.isfile(KOKORO_PY):
        return False
    if not os.path.isfile(os.path.join(KOKORO_DIR, _VOICES)):
        return False
    if not (os.path.isfile(os.path.join(KOKORO_DIR, _FP32)) or
            os.path.isfile(os.path.join(KOKORO_DIR, _INT8))):
        return False
    try:
        r = subprocess.run([KOKORO_PY, "-c", "import kokoro_onnx; print('ok')"],
                           capture_output=True, text=True, creationflags=_NO_WINDOW, timeout=60)
        return r.returncode == 0 and "ok" in (r.stdout or "")
    except Exception:
        return False


def _run(args, buoc=""):
    try:
        subprocess.run(args, check=True, creationflags=_NO_WINDOW)
    except FileNotFoundError as e:
        raise RuntimeError("không tìm thấy lệnh '%s' (%s)" % (args[0], e))
    except subprocess.CalledProcessError as e:
        raise RuntimeError("bước [%s] thất bại — mã %s" % (buoc, e.returncode))


def _tai(ten, retry=4):
    """Tải 1 file model về KOKORO_DIR nếu chưa có (urllib + retry)."""
    out = os.path.join(KOKORO_DIR, ten)
    if os.path.isfile(out) and os.path.getsize(out) > 1024 * 1024:
        return True
    os.makedirs(KOKORO_DIR, exist_ok=True)
    url = "%s/%s" % (_REL, ten)
    for lan in range(retry):
        try:
            print("  ⬇ %s (lần %d)..." % (ten, lan + 1), flush=True)
            tmp = out + ".part"
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "vc-kokoro/1"}),
                                        timeout=120) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f, 1024 * 256)
            os.replace(tmp, out)
            if os.path.getsize(out) > 1024 * 1024:
                return True
        except Exception as e:
            print("    lỗi: %s" % str(e)[:80], flush=True)
    return os.path.isfile(out) and os.path.getsize(out) > 1024 * 1024


def main():
    gpu = co_nvidia()
    if da_cai():
        print("✔ Kokoro đã cài sẵn (%s)." % ("GPU" if gpu else "CPU"), flush=True)
        print("KOKORO_DONE", flush=True)
        return

    uv = _uv()
    print("=== [1/4] Tạo .venv_kokoro (Python 3.11) tại %s... ===" % KOKORO_VENV, flush=True)
    if not os.path.isfile(KOKORO_PY):
        os.makedirs(_RUNTIME, exist_ok=True)
        _run([uv, "venv", KOKORO_VENV, "--python", "3.11"], "tạo .venv_kokoro")

    print("=== [2/4] Cài kokoro-onnx + soundfile + numpy... ===", flush=True)
    _run([uv, "pip", "install", "--python", KOKORO_PY, "kokoro-onnx", "soundfile", "numpy"], "cài kokoro-onnx")

    if gpu:
        print("=== [3/4] Máy có GPU — onnxruntime-gpu 1.22 (CUDA12) + cuDNN 9.5.1.17 (PIN) + nvidia cu12... ===", flush=True)
        # kokoro-onnx kéo onnxruntime CPU → gỡ rồi reinstall bản GPU (cùng thư mục onnxruntime/, CPU đè GPU nếu để chung)
        try:
            _run([uv, "pip", "uninstall", "--python", KOKORO_PY, "onnxruntime"], "gỡ onnxruntime CPU")
        except RuntimeError:
            pass
        _run([uv, "pip", "install", "--python", KOKORO_PY, "--reinstall", "onnxruntime-gpu==1.22.0",
              "nvidia-cudnn-cu12==9.5.1.17", "nvidia-cublas-cu12", "nvidia-cuda-runtime-cu12",
              "nvidia-cufft-cu12"], "onnxruntime-gpu + CUDA libs")
    else:
        print("=== [3/4] Máy KHÔNG GPU — giữ onnxruntime CPU (đã có). ===", flush=True)

    print("=== [4/4] Tải model Kokoro (%s) + voices về %s... ===" % ("fp32+int8" if gpu else "int8", KOKORO_DIR), flush=True)
    ok = _tai(_VOICES)
    ok = _tai(_FP32 if gpu else _INT8) and ok      # GPU: fp32; CPU: int8
    if gpu:
        _tai(_INT8)     # GPU máy cũng tải int8 (CPU fallback khi GPU lỗi) — không bắt buộc

    print("✔ Cài Kokoro xong (%s)." % ("GPU" if gpu else "CPU") if (da_cai() and ok)
          else "⚠ Cài Kokoro chưa hoàn tất — kiểm mạng.", flush=True)
    print("KOKORO_DONE" if (da_cai() and ok) else "KOKORO_ERR", flush=True)


if __name__ == "__main__":
    main()
