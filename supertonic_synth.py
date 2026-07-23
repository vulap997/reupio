# -*- coding: utf-8 -*-
"""Worker LỒNG TIẾNG bằng Supertonic-3 (supertone-inc/supertonic, ONNX, CPU nhanh).

Mirror kokoro_synth.py: đọc texts.json → sinh seg_<i>.wav (24k mono 16-bit) vào --out-dir.
Gọi qua subprocess từ localize.long_tieng_supertonic.

- Chạy trên CPU (onnxruntime), KHÔNG cần GPU, KHÔNG torch. Model auto-download từ HuggingFace lần đầu.
- 31 ngôn ngữ (en/ko/vi/ja...), 10 giọng cố định M1-M5 (nam) / F1-F5 (nữ).
- License: code MIT, model OpenRAIL-M (thương mại được + attribution). KHÔNG dùng để mạo danh.

POOL SONG SONG (--workers ≥ 2): chia câu cho N PROCESS, MỖI process nạp model RIÊNG + bị GHIM vào K core
(affinity) → chạy đè THẬT mà KHÔNG oversubscribe (bài học OCR pool: all-core mỗi worker = 0×). Chất lượng
KHÔNG đổi (đã verify: Supertonic non-deterministic, concurrency không giảm MOS — chỉ GIẢM STEPS mới giảm).
Auto workers theo core + RAM (model ~1GB/worker). workers=1 → đường TUẦN TỰ cũ (không đụng gì).
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

SR = 24000   # xuất 24k mono cho khớp _ghep_track_khop (như kokoro_synth)

# ---- Per-process (pool worker) globals — nạp model 1 lần/worker rồi tái dùng cho mọi câu của worker đó ----
_TTS = None
_STYLE = None


def _ghi_wav(samp, path, sr_in):
    """Ghi float32 [-1,1] -> wav 24k mono 16-bit (resample tuyến tính nếu sr_in != 24k)."""
    import numpy as np
    a = np.asarray(samp, dtype="float32").reshape(-1)
    if sr_in and sr_in != SR and len(a) > 1:
        n = int(round(len(a) * SR / sr_in))
        if n > 1:
            a = np.interp(np.linspace(0, 1, n, endpoint=False),
                          np.linspace(0, 1, len(a), endpoint=False), a).astype("float32")
    a = (np.clip(a, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(a.tobytes())


def _ram_gb():
    """(total_gb, avail_gb) qua ctypes MEMORYSTATUSEX (Windows). Lỗi → (0,0)."""
    try:
        import ctypes

        class _M(ctypes.Structure):
            _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong)] + \
                       [(c, ctypes.c_ulonglong) for c in "abcdefg"]
        m = _M(); m.l = ctypes.sizeof(m)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.a / (1024 ** 3), m.b / (1024 ** 3)   # a=total, b=avail
    except Exception:
        return 0.0, 0.0


def _ghim_core(threads):
    """GHIM process hiện tại vào `threads` core RIÊNG (theo chỉ số worker) → N worker KHÔNG giành core.
    Mấu chốt: onnxruntime tự spawn thread all-core, nhưng OS chỉ xếp lên core được ghim → hết oversubscribe.
    Best-effort (Windows SetProcessAffinityMask); lỗi thì thôi (vẫn chạy, chỉ có thể chậm hơn)."""
    try:
        import ctypes
        import multiprocessing as _mp
        idx = ((_mp.current_process()._identity or [1])[0] - 1)   # 0-based worker index
        ncpu = os.cpu_count() or 4
        cores = [((idx * threads) + j) % ncpu for j in range(max(1, threads))]
        mask = 0
        for c in cores:
            mask |= (1 << c)
        k32 = ctypes.windll.kernel32
        k32.SetProcessAffinityMask(k32.GetCurrentProcess(), ctypes.c_size_t(mask))
    except Exception:
        pass


def _init_worker(model_name, voice, lang, threads):
    """Chạy 1 LẦN/worker: giới hạn luồng (env + affinity) TRƯỚC khi import onnx-lib → nạp model + style riêng."""
    if threads and threads > 0:
        for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
            os.environ[_k] = str(threads)
        _ghim_core(threads)
    global _TTS, _STYLE
    import supertonic
    _TTS = supertonic.TTS(model=model_name, auto_download=True)
    _STYLE = _TTS.get_voice_style(voice)


def _synth_one(task):
    """1 câu (chạy trong worker đã _init): synth → seg_<i>.wav. Trả (i, ok, msg)."""
    i, text, lang, speed, steps, out_dir = task
    try:
        res = _TTS.synthesize(text, _STYLE, lang=lang, speed=speed, total_steps=steps)
        wav = res[0] if isinstance(res, tuple) else res
        sr = int(getattr(_TTS, "sample_rate", 0) or 44100)
        _ghi_wav(wav, os.path.join(out_dir, "seg_%d.wav" % i), sr)
        return (i, True, "")
    except Exception as e:
        return (i, False, str(e)[:80])


def _auto_workers(n_task, threads_per):
    """Số worker = min(core-based, RAM-based, số câu). Model ~1GB/worker → cap theo RAM trống. Sàn 1."""
    ncpu = os.cpu_count() or 4
    theo_core = max(1, ncpu // max(1, threads_per))
    _, avail = _ram_gb()
    theo_ram = max(1, int(avail / 1.2)) if avail > 0 else theo_core   # ~1.2GB/worker (model + onnx arena)
    return max(1, min(theo_core, theo_ram, n_task))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--texts", required=True, help="JSON list lời thoại (theo thứ tự câu)")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--voice", default="F1", help="M1-M5 / F1-F5")
    ap.add_argument("--lang", default="en", help="mã ngôn ngữ Supertonic (en/ko/vi/ja...)")
    ap.add_argument("--speed", type=float, default=1.05)
    ap.add_argument("--steps", type=int, default=int(os.environ.get("SUPERTONIC_STEPS") or 5),
                    help="số bước synth (Balanced=5; 8=chất lượng hơn/chậm hơn; 2-3=nhanh/thô)")
    # MẶC ĐỊNH 1 (TUẦN TỰ): benchmark THẬT trên máy 16-core cho thấy pool CHẬM HƠN — Supertonic đã ăn hết
    # core/câu (onnxruntime intra-op), chia worker × ít-core làm mỗi câu chậm N× + N× nạp model. Pool CHỈ khi
    # user ép SUPERTONIC_WORKERS≥2 (vd model tương lai ít-core/câu). KHÔNG auto (tránh regress dub live).
    ap.add_argument("--workers", type=int, default=int(os.environ.get("SUPERTONIC_WORKERS") or 1),
                    help="1=tuần tự (mặc định, NHANH NHẤT trên máy core-nhiều); N≥2=pool (thường CHẬM hơn với Supertonic)")
    ap.add_argument("--threads-per", type=int, default=int(os.environ.get("SUPERTONIC_THREADS_PER") or 0),
                    help="0=auto; số core mỗi worker (ghim affinity, né oversubscribe)")
    a = ap.parse_args()

    def log(m):
        print(m); sys.stdout.flush()

    texts = json.load(open(a.texts, encoding="utf-8"))
    os.makedirs(a.out_dir, exist_ok=True)
    voice = (a.voice or "F1").strip() or "F1"
    lang = (a.lang or "en").strip().lower() or "en"
    model = os.environ.get("SUPERTONIC_MODEL") or "supertonic-3"
    steps = a.steps

    tasks = [(i, (t or "").strip(), lang, a.speed, steps, a.out_dir)
             for i, t in enumerate(texts) if (t or "").strip()]
    if not tasks:
        log("[supertonic] không có câu nào."); return

    ncpu = os.cpu_count() or 4
    threads_per = a.threads_per if a.threads_per > 0 else max(2, ncpu // 4)   # mặc định ~4 worker
    workers = a.workers if a.workers > 0 else _auto_workers(len(tasks), threads_per)
    workers = max(1, min(workers, len(tasks)))

    # ---- ĐƯỜNG TUẦN TỰ (workers=1): giữ NGUYÊN hành vi cũ (không thread-limit, không multiprocessing) ----
    if workers <= 1:
        try:
            _init_worker(model, voice, lang, 0)   # threads=0 → không giới hạn (all-core như cũ)
        except Exception as e:
            log("[supertonic] Không nạp được Supertonic: %s" % str(e)[:140]); sys.exit(1)
        sr_model = int(getattr(_TTS, "sample_rate", 0) or 44100)
        log("[supertonic] %s | giọng %s | lang %s | steps %d | speed %.2f | CPU | sr %d | tuần tự"
            % (model, voice, lang, steps, a.speed, sr_model))
        n = 0
        for k, task in enumerate(tasks, 1):
            i, ok, msg = _synth_one(task)
            if ok:
                n += 1
            else:
                log("[supertonic] bỏ câu %d (%s)" % (i, msg))
            if k % 20 == 0 or k == len(tasks):
                log("[supertonic] đọc %d/%d" % (k, len(tasks)))
        log("[supertonic] xong %d câu." % n)
        return

    # ---- POOL SONG SONG (workers ≥ 2): N process, mỗi cái model riêng + ghim `threads_per` core ----
    import multiprocessing as mp
    log("[supertonic] %s | giọng %s | lang %s | steps %d | speed %.2f | CPU | POOL %d worker × %d core"
        % (model, voice, lang, steps, a.speed, workers, threads_per))
    n = 0
    try:
        with mp.Pool(processes=workers, initializer=_init_worker,
                     initargs=(model, voice, lang, threads_per)) as pool:
            for k, (i, ok, msg) in enumerate(pool.imap_unordered(_synth_one, tasks), 1):
                if ok:
                    n += 1
                elif msg:
                    log("[supertonic] bỏ câu %d (%s)" % (i, msg))
                if k % 20 == 0 or k == len(tasks):
                    log("[supertonic] đọc %d/%d" % (k, len(tasks)))
    except Exception as e:
        log("[supertonic] pool lỗi (%s) — thử lại TUẦN TỰ." % str(e)[:100])
        # fallback an toàn: nếu pool vỡ (spawn/pickle/RAM) → chạy tuần tự để KHÔNG mất lồng tiếng
        try:
            _init_worker(model, voice, lang, 0)
            for task in tasks:
                i, ok, msg = _synth_one(task)
                if ok:
                    n += 1
        except Exception as e2:
            log("[supertonic] tuần tự cũng lỗi: %s" % str(e2)[:100]); sys.exit(1)
    log("[supertonic] xong %d câu." % n)


if __name__ == "__main__":
    main()
