# -*- coding: utf-8 -*-
"""Persistent Render Worker — process SỐNG, chạy xu_ly_chon.main() IN-PROCESS theo vòng lặp → giữ NÓNG
WhisperModel/OCR (cache module-global trong phu_de/localize) qua nhiều render, KHÔNG load lại mỗi video.

Giao tiếp: đọc JSON-line ở stdin, in JSON-line ở stdout (web_app điều phối — xem plans/260628-...).
  job  : {"cmd":"render","id":N,"args":["video.mp4","--model","small","--long-tieng","--engine","google",...]}
  quit : {"cmd":"quit"}
  out  : {"ev":"ready"} | {"ev":"log","id":N,"line":...} | {"ev":"done","id":N,"code":0/1}

xu_ly_chon.main() dùng argparse(sys.argv) + sys.exit() rải rác → set sys.argv trước, bắt SystemExit (worker
KHÔNG chết). KHÔNG refactor xu_ly_chon. Cancel/restart/health = web_app (kill cây worker + respawn).
"""
import sys
import os
import io
import json

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# GIỮ stdout THẬT (pipe IPC) — vì lúc job ta redirect sys.stdout=_Tee để bắt log; _emit PHẢI ghi vào
# pipe thật, KHÔNG phải _Tee (nếu không event đi vào tee → đệ quy/mất event → render hỏng code=1).
_REAL_OUT = sys.stdout

# Báo cho localize biết đang chạy TRONG worker bền → dùng Gemini IN-PROCESS giữ browser nóng (Step 3),
# Piper/Whisper/OCR cache cũng giữ nóng. PHẢI set TRƯỚC khi import xu_ly_chon (kéo theo localize).
os.environ["VC_RENDER_WORKER_PROC"] = "1"
# Profile Gemini ở thư mục GHI ĐƯỢC + ỔN ĐỊNH (app-src read-only ở Program Files → makedirs default vỡ;
# phiên bền tái dùng nên KHÔNG dùng temp-mới-mỗi-lần). Gemini free KHÔNG cần login → profile trống là đủ.
import tempfile as _tf
os.environ.setdefault("GEMINI_PROFILE_DIR", os.path.join(_tf.gettempdir(), "vc_gemini_profile_worker"))

# import sẵn (1 lần) — module nặng (faster_whisper lazy trong _get_model nên import này nhẹ)
import xu_ly_chon


import threading
_EMIT_LOCK = threading.Lock()


def _emit(obj):
    # LOCK: luồng warm-on-start + luồng job có thể _emit song song → tránh 2 dòng JSON ghi LẪN vào pipe.
    line = json.dumps(obj, ensure_ascii=False) + "\n"
    with _EMIT_LOCK:
        _REAL_OUT.write(line)
        _REAL_OUT.flush()


class _Tee:
    """Bắt MỌI print của xu_ly_chon.main() (chạy in-process) → chuyển thành event log theo job id."""
    def __init__(self, job_id):
        self.id = job_id
        self.buf = ""

    def write(self, s):
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            if line.strip():
                _emit({"ev": "log", "id": self.id, "line": line})

    def flush(self):
        pass


def _run_job(job):
    jid = job.get("id")
    args = job.get("args") or []
    code = 1
    real_out, real_err = sys.stdout, sys.stderr
    tee = _Tee(jid)
    sys.stdout = tee
    sys.stderr = tee
    sys.argv = ["xu_ly_chon.py"] + [str(a) for a in args]
    # Render ĐA NGÔN NGỮ: job mang "lang" riêng → đặt TARGET_LANG cho job NÀY (worker bền dùng CHUNG env, phải
    # trả lại sau) để localize/phu_de dịch+lồng đúng đích. KHÔNG có lang = giữ đích global như cũ.
    _old_tl = os.environ.get("TARGET_LANG")
    _job_lang = job.get("lang")
    if _job_lang:
        os.environ["TARGET_LANG"] = str(_job_lang)
    try:
        xu_ly_chon.main()
        code = 0
    except SystemExit as e:           # xu_ly_chon dùng sys.exit(0/1) — KHÔNG để giết worker
        code = int(e.code) if isinstance(e.code, int) else (0 if not e.code else 1)
    except Exception as e:
        try:
            tee.write("WORKER_JOB_EXCEPTION: %s\n" % str(e)[:300])
        except Exception:
            pass
        code = 1
    finally:
        sys.stdout = real_out
        sys.stderr = real_err
        if _job_lang:                     # trả env về cũ → job sau (không đa-ngôn-ngữ) dùng đúng đích global
            if _old_tl is None:
                os.environ.pop("TARGET_LANG", None)
            else:
                os.environ["TARGET_LANG"] = _old_tl
    _emit({"ev": "done", "id": jid, "code": code})


def _ram_pct():
    """RAM toàn máy (%) qua ctypes — để worker tự thoát khi RAM cao (tránh phình do giữ nóng model lâu)."""
    try:
        import ctypes

        class _M(ctypes.Structure):
            _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong)] + \
                       [(c, ctypes.c_ulonglong) for c in "abcdefg"]
        m = _M(); m.l = ctypes.sizeof(m)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return int(m.load)
    except Exception:
        return 0


def main():
    _emit({"ev": "ready", "pid": os.getpid()})
    # AUTO-RESTART: sau N video HOẶC RAM cao → worker tự thoát (sau khi job done) → web_app respawn (warm lại,
    # xả Whisper/OCR/Piper-pool → tránh RAM phình + leak/fragment khi giữ nóng model hàng giờ). Kiểm soát qua env.
    done = 0
    maxn = int(os.environ.get("VC_RENDER_WORKER_MAX", "30") or 0)
    maxram = int(os.environ.get("VC_RENDER_WORKER_RAM", "92") or 0)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            job = json.loads(line)
        except Exception:
            continue
        if job.get("cmd") == "quit":
            break
        if job.get("cmd") == "render":
            _run_job(job)
            done += 1
            ram = _ram_pct()
            if (maxn and done >= maxn) or (maxram and ram >= maxram):
                _emit({"ev": "bye", "reason": ("max_jobs" if (maxn and done >= maxn) else "ram"),
                       "n": done, "ram": ram})
                break    # thoát sạch → web_app _rw_ensure respawn ở render kế (warm lại)


if __name__ == "__main__":
    main()
