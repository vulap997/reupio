# -*- coding: utf-8 -*-
"""Tải giọng Piper tiếng Việt 'Banmai' (NghiTTS) về piper_vn/.

Model nằm trong models.zip (293MB, gộp TTS+ASR) ở GitHub Release của VNTTS. Ta CHỈ kéo 2 file
banmai (model.onnx ~60MB + .json) bằng HTTP Range (đọc 'mục lục' zip) — không tải 230MB ASR thừa.
Trả True nếu piper_vn/banmai.onnx sẵn sàng.
"""
import os
import struct
import zlib
import urllib.request

URL = "https://github.com/Devhub-Solutions/VNTTS/releases/download/models/models.zip"
THU_MUC_GOC = os.path.dirname(os.path.abspath(__file__))
# GHI ĐƯỢC + bền update (xem localize._piper_dir_rw): userData/runtime > app-src nếu ghi được > LOCALAPPDATA.
def _piper_dir_rw():
    _lic = os.environ.get("LIC_CACHE_DIR", "").strip()
    if _lic:
        return os.path.join(_lic, "runtime", "piper_vn")
    _d = os.path.join(THU_MUC_GOC, "piper_vn")
    try:
        os.makedirs(_d, exist_ok=True)
        _t = os.path.join(_d, ".wtest"); open(_t, "w").close(); os.remove(_t)
        return _d
    except Exception:
        return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "ViralCrawl", "piper_vn")
PIPER_DIR = _piper_dir_rw()
BANMAI = os.path.join(PIPER_DIR, "banmai.onnx")


def _rng(url, a, b, timeout):
    req = urllib.request.Request(url, headers={"Range": "bytes=%d-%d" % (a, b),
                                               "User-Agent": "vntts-banmai/1"})
    return urllib.request.urlopen(req, timeout=timeout).read()


def tai(log_fn=print, timeout=180):
    """Tải banmai.onnx + .json về piper_vn/ (chỉ phần cần, qua Range). True nếu đã có/tải xong."""
    if os.path.isfile(BANMAI):
        return True
    os.makedirs(PIPER_DIR, exist_ok=True)
    try:
        h = urllib.request.urlopen(urllib.request.Request(URL, method="HEAD",
                                   headers={"User-Agent": "vntts-banmai/1"}), timeout=30)
        total = int(h.headers["Content-Length"])
        log_fn("⬇ Tải giọng Banmai (chỉ ~58MB từ gói %.0fMB)..." % (total / 1048576))
        tail = _rng(URL, total - 65536, total - 1, 30)
        p = tail.rfind(b"PK\x05\x06")
        if p < 0:
            log_fn("⚠ Không đọc được mục lục zip Banmai."); return False
        cd_size, cd_off = struct.unpack("<II", tail[p + 12:p + 20])
        cd = _rng(URL, cd_off, cd_off + cd_size - 1, 60)
        i = 0
        want = {}
        while i < len(cd) - 4 and cd[i:i + 4] == b"PK\x01\x02":
            method, = struct.unpack("<H", cd[i + 10:i + 12])
            comp, = struct.unpack("<I", cd[i + 20:i + 24])
            nlen, elen, clen = struct.unpack("<HHH", cd[i + 28:i + 34])
            loff, = struct.unpack("<I", cd[i + 42:i + 46])
            name = cd[i + 46:i + 46 + nlen].decode("utf-8", "replace")
            if "banmai/" in name and (name.endswith(".onnx") or name.endswith(".onnx.json")):
                want[name] = (loff, comp, method)
            i += 46 + nlen + elen + clen
        if not want:
            log_fn("⚠ Không tìm thấy file Banmai trong gói."); return False
        for name, (loff, comp, method) in want.items():
            lh = _rng(URL, loff, loff + 29, 30)
            lnlen, lelen = struct.unpack("<HH", lh[26:30])
            start = loff + 30 + lnlen + lelen
            raw = _rng(URL, start, start + comp - 1, timeout)
            data = zlib.decompress(raw, -15) if method == 8 else raw
            out = BANMAI + ".json" if name.endswith(".json") else BANMAI
            with open(out, "wb") as f:
                f.write(data)
        ok = os.path.isfile(BANMAI)
        log_fn("✔ Đã tải giọng Banmai." if ok else "⚠ Tải Banmai chưa đủ file.")
        return ok
    except Exception as e:
        log_fn("⚠ Tải Banmai lỗi: %s" % str(e)[:80])
        return False


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    tai()
