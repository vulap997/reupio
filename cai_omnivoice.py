# -*- coding: utf-8 -*-
"""Cài OmniVoice (k2-fsa) — lồng tiếng clone chất lượng cao, CHẠY GPU NVIDIA — vào venv RIÊNG .venv_omnivoice.

Chạy:  MediaCrawler\\.venv\\Scripts\\python.exe cai_omnivoice.py   (web_app gọi tự động ở NỀN khi máy CÓ GPU)
Tách .venv_omnivoice để KHÔNG đụng môi trường chính. Idempotent: bước nào xong thì bỏ qua.

⚠️ CHỈ cài khi có NVIDIA (OmniVoice là diffusion GPU-only). Máy không GPU → thoát ngay (không tải phí ~vài GB).
Recipe theo bản cài tay đã chạy trên laptop RTX 3050 + mẫu cai_f5.py. CẦN VERIFY trên máy GPU thật.
"""
import os
import shutil
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
OMNI_VENV = os.path.join(HERE, ".venv_omnivoice")
OMNI_PY = os.path.join(OMNI_VENV, "Scripts", "python.exe")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


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
    """OmniVoice đã sẵn sàng? (venv + import được omnivoice)."""
    if not os.path.isfile(OMNI_PY):
        return False
    try:
        r = subprocess.run([OMNI_PY, "-c", "import omnivoice, torch; print('ok')"],
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


def main():
    if not co_nvidia():
        print("✗ Máy KHÔNG có GPU NVIDIA — OmniVoice là model GPU-only, BỎ QUA cài (khỏi tải phí vài GB).", flush=True)
        print("OMNIVOICE_SKIP_NOGPU", flush=True)
        return
    if da_cai():
        print("✔ OmniVoice đã cài sẵn.", flush=True)
        print("OMNIVOICE_DONE", flush=True)
        return

    uv = _uv()
    print("=== [1/4] Tạo môi trường .venv_omnivoice (Python 3.11)... ===", flush=True)
    if not os.path.isfile(OMNI_PY):
        _run([uv, "venv", OMNI_VENV, "--python", "3.11"], "tạo .venv_omnivoice")

    print("=== [2/4] Cài omnivoice + soundfile + numpy (kéo torch/transformers, hơi lâu)... ===", flush=True)
    _run([uv, "pip", "install", "--python", OMNI_PY, "omnivoice", "soundfile", "numpy"], "cài omnivoice")

    print("=== [3/4] Thay PyTorch sang CUDA 12.1 (~2.5GB — OmniVoice cần GPU)... ===", flush=True)
    try:
        _run([uv, "pip", "install", "--python", OMNI_PY, "--reinstall", "torch", "torchaudio",
              "--index-url", "https://download.pytorch.org/whl/cu121"], "torch CUDA")
    except RuntimeError:
        print("  (lỗi tải torch CUDA — thử lại sau; OmniVoice cần CUDA mới chạy.)", flush=True)

    print("=== [4/4] Tải model k2-fsa/OmniVoice về cache HuggingFace (~vài GB)... ===", flush=True)
    dl = ("from huggingface_hub import snapshot_download; "
          "print(snapshot_download('k2-fsa/OmniVoice'))")
    try:
        _run([OMNI_PY, "-c", dl], "tải model OmniVoice")
    except RuntimeError:
        print("  (chưa tải xong model — sẽ tự tải khi lồng tiếng lần đầu.)", flush=True)

    print("✔ Cài OmniVoice xong." if da_cai() else "⚠ Cài chưa hoàn tất — kiểm lại mạng/GPU.", flush=True)
    print("OMNIVOICE_DONE" if da_cai() else "OMNIVOICE_ERR", flush=True)


if __name__ == "__main__":
    main()
