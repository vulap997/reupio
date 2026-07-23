# -*- coding: utf-8 -*-
"""
Worker chạy demucs trong process riêng — PyTorch + model unload ngay khi subprocess thoát.
Dùng: python _demucs_worker.py <audio_wav> <out_dir>
In ra:
    GIONG:<path>
    NHAC:<path>
"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main():
    if len(sys.argv) < 3:
        print("NHAC:", flush=True)
        print("GIONG:", flush=True)
        sys.exit(1)
    audio_wav, out_dir = sys.argv[1], sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)

    try:
        import torchaudio
        import soundfile as sf
        import demucs.separate
    except ImportError as e:
        print(f"LỖIIMPORT:{e}", flush=True)
        sys.exit(2)

    # Vá torchaudio.save → soundfile (torchaudio 2.11+ dùng torchcodec, lỗi với FFmpeg mới)
    def _save(path, wav, sample_rate=44100, **kw):
        sf.write(str(path), wav.detach().cpu().numpy().T, int(sample_rate))
    torchaudio.save = _save

    argv_cu = sys.argv[:]
    sys.argv = ["demucs", "--two-stems=vocals", "-o", out_dir, audio_wav]
    try:
        demucs.separate.main()
    except SystemExit:
        pass
    except Exception as e:
        print(f"LỖI:{e}", flush=True)
        sys.argv = argv_cu
        sys.exit(1)
    finally:
        sys.argv = argv_cu

    giong = nhac = ""
    for root, _d, files in os.walk(out_dir):
        for f in files:
            fl = f.lower()
            if fl.startswith("vocals"):
                giong = os.path.join(root, f)
            elif fl.startswith("no_vocals"):
                nhac = os.path.join(root, f)
    print(f"GIONG:{giong}", flush=True)
    print(f"NHAC:{nhac}", flush=True)


if __name__ == "__main__":
    main()
