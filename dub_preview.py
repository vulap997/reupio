# -*- coding: utf-8 -*-
"""NGHE THỬ giọng lồng tiếng: sinh 1 câu tiếng Việt bằng engine đang chọn rồi ghi ra wav.

Tái dùng đúng hàm TTS trong localize.py (1 backend thống nhất với lồng tiếng thật) để giọng
nghe-thử KHỚP giọng khi render:
  - edge : _tts_edge_wav(text, voice, out)         (nhanh, cần mạng)
  - piper: long_tieng_piper([1 câu], dur, out)     (offline, nhanh)
  - omnivoice: long_tieng_omnivoice([1 câu], dur, out, ref_audio)(clone giọng mẫu, cần GPU)

Dùng:
  python dub_preview.py --engine edge --voice vi-VN-HoaiMyNeural --text "..." --out preview.wav
  python dub_preview.py --engine omnivoice  --ref-audio mau.wav --text "..." --out preview.wav
In "OUT|<path>" nếu xong, "ERR|<lý do>" nếu lỗi.
"""
import os
import sys
import argparse

try:
    sys.stdout.reconfigure(encoding="utf-8")   # tránh crash cp1252 khi in tiếng Việt trên Windows
except Exception:
    pass

import localize


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="edge", choices=["edge", "piper", "omnivoice", "supertonic"])
    ap.add_argument("--voice", default="vi-VN-HoaiMyNeural")
    ap.add_argument("--ref-audio", dest="ref_audio", default=None)
    ap.add_argument("--lang", default="en")   # cho supertonic: ngôn ngữ đích (en/ko...) — text đã đúng ngôn ngữ đó
    ap.add_argument("--text", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    text = (a.text or "").strip()[:200]
    if not text:
        print("ERR|empty-text"); return
    out = a.out
    # 1 "câu" theo cấu trúc segs_vi của localize: (start, end, (zh, vi))
    seg = [(0.0, 6.0, ("", text))]
    ok = False
    try:
        if a.engine == "supertonic":
            # Supertonic (ONNX CPU, đích Hàn/EN...) — text đã đúng ngôn ngữ đích; voice = M1-M5/F1-F5.
            ok = bool(localize.long_tieng_supertonic(seg, 6.5, out, voice=a.voice, lang=a.lang))
        elif a.engine == "piper":
            v_name = a.voice
            if v_name == "thanhphuong":
                v_name = "thanhphuong2"
            model_path = os.path.join(localize.PIPER_DIR, v_name + ".onnx")
            ok = bool(localize.long_tieng_piper(seg, 6.5, out, model_path=model_path))
        elif a.engine == "omnivoice":
            # OmniVoice clone: ref = file upload hoặc giọng mẫu mặc định.
            ref = a.ref_audio if (a.ref_audio and os.path.isfile(a.ref_audio)) else \
                localize.OMNI_GIONG_MAU.get((a.voice or "").lower(), localize.OMNI_REF_MAC_DINH)
            ok = bool(localize.long_tieng_omnivoice(seg, 6.5, out, ref_audio=ref, num_step=None))
        else:
            ok = bool(localize._tts_edge_wav(text, a.voice, out))
    except Exception as e:
        print("ERR|" + repr(e)[:160]); return

    print(("OUT|" + out) if (ok and os.path.isfile(out)) else "ERR|no-audio")


if __name__ == "__main__":
    main()
