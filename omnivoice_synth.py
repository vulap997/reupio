# -*- coding: utf-8 -*-
"""Synth tiếng Việt bằng OmniVoice (k2-fsa) — CHẠY TRONG .venv_omnivoice (cần GPU NVIDIA).

2 chế độ:
  • ONE-SHOT: --texts texts.json --out-dir DIR  → load model, synth, thoát.
  • DAEMON warm: --serve QUEUE_DIR  → load model 1 LẦN, nằm chờ; mỗi req_<id>.json (gồm texts/out_dir/
    num_step/ref) được synth ra seg_<i>.wav + ghi _omnidone; RẢNH quá OMNI_IDLE giây → tự thoát (giải
    phóng VRAM). → render liên tiếp KHỎI load lại model (~10s/lần).

BATCH theo lô (generate nhận list) + sort theo độ dài + language=vi + FP16. RTX 3050: ns16 batch8 ~4.4×
realtime. Giọng: auto (mặc định) hoặc CLONE (--ref + --ref-text, clone là điểm mạnh nhất của OmniVoice).
"""
import os
import sys
import json
import time
import glob
import argparse

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_VCP_CACHE = {}   # đường-dẫn-ref → VoiceClonePrompt (speaker embedding); tái dùng giữa các render cùng giọng


def _synth_to_dir(model, np, sf, texts, out_dir, num_step, ref, ref_text, batch, heartbeat=None, instruct=None):
    """Synth list câu → seg_<i>.wav (24kHz) trong out_dir. Batch theo lô + sort độ dài.
    heartbeat = path _alive: cập nhật mỗi batch để client biết daemon CÒN SỐNG lúc synth dài."""
    os.makedirs(out_dir, exist_ok=True)
    SR = 24000
    n = len(texts)
    results = [None] * n
    idx = [i for i, t in enumerate(texts) if (t or "").strip()]
    idx.sort(key=lambda i: len(texts[i]))   # gom câu dài-ngắn gần nhau → GPU đỡ chờ
    # CLONE: encode ref CHỈ 1 LẦN → VoiceClonePrompt ("speaker embedding") tái dùng cho mọi câu (giọng
    # NHẤT QUÁN + nhanh 2× so truyền ref_audio mỗi câu). Không có ref → auto (giọng ngẫu nhiên → "drift").
    # Cache theo đường dẫn ref: render SAU cùng giọng (daemon warm) khỏi encode lại — đúng ý "speaker profile".
    vcp = None
    if ref and os.path.isfile(ref):
        _k = os.path.abspath(ref)
        vcp = _VCP_CACHE.get(_k)
        if vcp is None:
            try:
                vcp = model.create_voice_clone_prompt(ref, ref_text)
                _VCP_CACHE[_k] = vcp
            except Exception as e:
                print("[omnivoice] create_voice_clone_prompt lỗi: %s" % repr(e)[:100], flush=True)
        else:
            print("[omnivoice] dùng lại speaker embedding (cache).", flush=True)
    done = 0
    for s in range(0, len(idx), batch):
        chunk = idx[s:s + batch]
        ctexts = [texts[i].strip() for i in chunk]
        kw = {"text": ctexts, "language": ["vi"] * len(ctexts), "num_step": num_step}
        if vcp is not None:
            kw["voice_clone_prompt"] = [vcp] * len(ctexts)   # 1 prompt đã encode → mọi câu cùng giọng
        elif instruct:
            kw["instruct"] = [instruct] * len(ctexts)        # Voice Design: tạo giọng theo thuộc tính (nhanh, ko ref)
        try:
            audios = model.generate(**kw)
        except Exception as e:
            print("[omnivoice] batch lỗi: %s — thử từng câu" % repr(e)[:120], flush=True)
            audios = []
            for t in ctexts:
                try:
                    one = {"text": t, "language": "vi", "num_step": num_step}
                    if vcp is not None:
                        one["voice_clone_prompt"] = vcp
                    elif instruct:
                        one["instruct"] = instruct
                    r = model.generate(**one)
                    audios.append(r[0] if isinstance(r, (list, tuple)) else r)
                except Exception:
                    audios.append(np.zeros(int(SR * 0.1), dtype="float32"))
        for j, i in enumerate(chunk):
            results[i] = audios[j] if j < len(audios) else None
        done += len(chunk)
        print("[omnivoice] %d/%d" % (done, len(idx)), flush=True)
        if heartbeat:
            try: open(heartbeat, "w").write("x")
            except Exception: pass
    for i in range(n):
        out = os.path.join(out_dir, "seg_%d.wav" % i)
        arr = results[i]
        sf.write(out, np.zeros(int(SR * 0.1), dtype="float32") if arr is None
                 else np.asarray(arr, dtype="float32"), SR)


def _load(batch_hint):
    import torch
    from omnivoice import OmniVoice
    dev = "cuda:0" if torch.cuda.is_available() else "cpu"
    dt = torch.float16 if dev.startswith("cuda") else torch.float32
    print("[omnivoice] nạp model (device=%s)..." % dev, flush=True)
    return OmniVoice.from_pretrained("k2-fsa/OmniVoice", device_map=dev, dtype=dt)


def _serve(qdir, batch):
    """Daemon warm: load 1 lần, xử lý req_*.json tới khi rảnh quá OMNI_IDLE giây."""
    import numpy as np
    import soundfile as sf
    os.makedirs(qdir, exist_ok=True)
    alive = os.path.join(qdir, "_alive")
    IDLE = float(os.environ.get("OMNI_IDLE", "180"))   # 0 = GIỮ MODEL MÃI (load 1 lần, không tự thoát)
    model = _load(batch)
    open(alive, "w").write(str(os.getpid()))
    print("[omnivoice] daemon SẴN SÀNG (warm). Idle %ds." % IDLE, flush=True)
    last = time.time()
    while True:
        try:
            open(alive, "w").write(str(os.getpid()))   # heartbeat
        except Exception:
            pass
        reqs = sorted(glob.glob(os.path.join(qdir, "req_*.json")))
        if not reqs:
            if IDLE > 0 and time.time() - last > IDLE:   # IDLE=0 → giữ model mãi (dùng được mãi)
                break
            time.sleep(0.3)
            continue
        for req in reqs:
            try:
                d = json.load(open(req, encoding="utf-8"))
            except Exception:
                try: os.remove(req)
                except OSError: pass
                continue
            try:
                os.remove(req)
            except OSError:
                continue
            out_dir = d.get("out_dir")
            try:
                _synth_to_dir(model, np, sf, d.get("texts") or [], out_dir,
                              int(d.get("num_step") or 8), d.get("ref"), d.get("ref_text"), batch,
                              heartbeat=alive, instruct=d.get("instruct"))
                open(os.path.join(out_dir, "_omnidone"), "w").write("ok")
            except Exception as e:
                try: open(os.path.join(out_dir, "_omnierr"), "w").write(repr(e)[:200])
                except Exception: pass
                print("[omnivoice] req lỗi: %s — THOÁT daemon (nhả VRAM, tránh treo orphan)." % repr(e)[:120], flush=True)
                # lỗi synth (OOM/CUDA hỏng) thường KHÔNG hồi phục → THOÁT hẳn daemon để giải phóng VRAM;
                # lần render sau client tự khởi động daemon MỚI sạch (không tích tụ tiến trình chết chiếm VRAM).
                try: os.remove(alive)
                except OSError: pass
                return
            last = time.time()
    try:
        os.remove(alive)
    except OSError:
        pass
    print("[omnivoice] daemon thoát (rảnh) → giải phóng VRAM.", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--texts", default=None)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--serve", default=None)         # chế độ daemon: thư mục hàng đợi
    ap.add_argument("--ref", default=None)
    ap.add_argument("--ref-text", dest="ref_text", default=None)
    ap.add_argument("--instruct", default=None)      # Voice Design: "female, young adult, moderate pitch"
    ap.add_argument("--num-step", dest="num_step", type=int, default=int(os.environ.get("OMNI_NS", "8")))
    ap.add_argument("--batch", type=int, default=int(os.environ.get("OMNI_BATCH", "8")))   # RTX 3050 4GB→8 (~2.2GB peak)
    a = ap.parse_args()

    if a.serve:
        _serve(a.serve, a.batch)
        return
    # one-shot
    import numpy as np
    import soundfile as sf
    texts = json.load(open(a.texts, encoding="utf-8"))
    ref = a.ref if (a.ref and os.path.isfile(a.ref)) else None
    print("[omnivoice] one-shot (ns=%d, batch=%d)..." % (a.num_step, a.batch), flush=True)
    model = _load(a.batch)
    _synth_to_dir(model, np, sf, texts, a.out_dir, a.num_step, ref, a.ref_text, a.batch, instruct=a.instruct)
    print("[omnivoice] xong %d câu" % len(texts), flush=True)


if __name__ == "__main__":
    main()
