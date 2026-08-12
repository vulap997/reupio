# -*- coding: utf-8 -*-
"""Cài/sửa TĂNG TỐC GPU cho Whisper: nvidia cuda-runtime(cudart) + cuBLAS + cuDNN vào venv CHÍNH.
Chạy:  MediaCrawler\\.venv\\Scripts\\python.exe cai_gpu.py   (web_app gọi qua nút trong app)

Vá đúng máy khách bản CŨ thiếu cudart -> 'cublas64_12.dll cannot be loaded' -> Whisper lùi CPU.
Dùng `uv pip install` (CỘNG THÊM, idempotent) — KHÔNG dùng `uv sync` kẻo prune mất torch/yt-dlp.
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


def lay_ten_gpu():
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                           capture_output=True, text=True, creationflags=_NO_WINDOW, timeout=10)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def main():
    if not co_nvidia():
        print("⚠ Không thấy GPU NVIDIA (nvidia-smi) — máy này Whisper chạy CPU, KHÔNG cần gói CUDA.")
        return
    print("=== Cài/sửa tăng tốc GPU cho Whisper (cudart + cuBLAS + cuDNN, ~1.3GB) ===", flush=True)
    pkgs = ["nvidia-cuda-runtime-cu12>=12,<13", "nvidia-cublas-cu12", "nvidia-cudnn-cu12>=9,<10"]
    subprocess.run([_uv(), "pip", "install", "--python", sys.executable] + pkgs,
                   check=True, creationflags=_NO_WINDOW)

    gpu_name = lay_ten_gpu()
    is_blackwell = any(x in gpu_name for x in ["5070", "5080", "5090", "Blackwell"])

    if is_blackwell:
        print("\n=== Phát hiện GPU Blackwell (%s) → cài PyTorch CUDA 12.8 (~2.5GB) ===" % gpu_name, flush=True)
        idx_url = "https://download.pytorch.org/whl/cu128"
        torch_pkgs = ["torch>=2.7.0", "torchaudio>=2.7.0"]
    else:
        print("\n=== Cài/sửa PyTorch CUDA để tăng tốc tách nhạc nền (Demucs) VÀ lồng tiếng (~2.5GB) ===", flush=True)
        idx_url = "https://download.pytorch.org/whl/cu124"
        torch_pkgs = ["torch", "torchaudio"]

    try:
        subprocess.run([_uv(), "pip", "install", "--python", sys.executable, "--reinstall",
                        "--extra-index-url", idx_url] + torch_pkgs,
                       check=True, creationflags=_NO_WINDOW)
        print("✅ Đã cài đặt PyTorch CUDA thành công.", flush=True)
    except Exception as e:
        print("❌ Lỗi khi cài đặt PyTorch CUDA: %s" % str(e)[:160], flush=True)

    # VERIFY THẬT: nạp cublas64_12.dll y như Whisper (sau _add_cuda_dll_dirs) — để biết CHẮC đã ăn,
    # không chỉ "cài xong". Cài đúng mà vẫn fail ở đây = phu_de.py CŨ (chưa thêm dir cudart vào DLL path).
    print("\n=== Kiểm tra nạp cuBLAS (giống Whisper) ===", flush=True)
    try:
        import ctypes
        import phu_de
        phu_de._add_cuda_dll_dirs()
        ctypes.WinDLL("cublas64_12.dll")
        print("✅ NẠP cublas64_12.dll OK → Whisper sẽ chạy GPU. Khởi động lại tool rồi render lại.", flush=True)
    except Exception as e:
        print("❌ Cài xong NHƯNG vẫn không nạp được cublas64_12.dll: %s" % str(e)[:160], flush=True)
        print("   → Nhiều khả năng phu_de.py trên máy này CŨ (chưa thêm thư mục cudart vào DLL path).", flush=True)
        print("   → Cập nhật/đóng gói lại app để lấy phu_de.py mới nhất rồi bấm Cài lại.", flush=True)


if __name__ == "__main__":
    main()
