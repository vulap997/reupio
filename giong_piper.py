# -*- coding: utf-8 -*-
"""Giọng Piper (NghiTTS) — tải on-demand từ Google Drive. Mỗi giọng = <name>.onnx + .onnx.json ~60MB.
Banmai có downloader riêng (tai_banmai, HTTP Range). Các giọng khác tải qua gdown khi user CHỌN."""
import os

# GHI ĐƯỢC + bền update (xem localize._piper_dir_rw): userData/runtime > app-src nếu ghi được > LOCALAPPDATA.
# ĐỪNG để app-src (Program Files) — makedirs/tải giọng PermissionError WinError 5 (read-only).
def _piper_dir_rw():
    _lic = os.environ.get("LIC_CACHE_DIR", "").strip()
    if _lic:
        return os.path.join(_lic, "runtime", "piper_vn")
    _d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "piper_vn")
    try:
        os.makedirs(_d, exist_ok=True)
        _t = os.path.join(_d, ".wtest"); open(_t, "w").close(); os.remove(_t)
        return _d
    except Exception:
        return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "ViralCrawl", "piper_vn")
PIPER_DIR = _piper_dir_rw()

# name -> (gdrive_id_onnx, gdrive_id_json, "Tên hiển thị")
GIONG = {
    "ngochuyen":    ("12HNgJmBY3GiNCcFBRpHxYFv-qbE-jEv7", "1p-oDIiuhecInjgys4bqsaeOf794OFcHC", "Ngọc Huyền"),
    "ngochuyennew": ("1cpiuiO6zwCtvyygiSBAvARARQjtL5xsT", "10kxjoicf9q7nCpll5ijdaJ-b93_4r05n", "Ngọc Huyền (mới)"),
    "maiphuong":    ("1jJ1jn7SZUZqEu7y9eHlMn3UWzHti2PaL", "1iN6TXnQD-N1g8zvcYTbbxLcoHmMhcazo", "Mai Phương"),
    "manhdung":     ("1Lto6WIUeesmlqj1B8ZOs3oR5PKAn4lZS", "122NzEd4FN0oIdvr4-JkNxp_7DUQlxgwS", "Mạnh Dũng (nam)"),
    "minhkhang":    ("1P5xuenCWN3xOdVLXRzLYn44mDOOh1JiS", "13gFxt7pPQNdS-3VhZS1olg4iNLI-ZXWq", "Minh Khang (nam)"),
    "phuongtrang":  ("1MBXaejxEujqUigeZdCHaV88knGC9zU2L", "1RTUo_BKUD7hNULInREoBcDS-oLeBWEN7", "Phương Trang"),
    "thanhphuong2": ("1F6TKcGJp3Gw2zAdOrdJv256toExz3URi", "1dreiPNqacBk8tkTiUW6Aq2h5yzCWV9Wf", "Thanh Phương"),
}


def duong_dan(name):
    return os.path.join(PIPER_DIR, name + ".onnx")


def tai(name, log_fn=print):
    """Tải giọng <name> (onnx+json) nếu chưa có → trả đường dẫn onnx, None nếu lỗi/không biết."""
    if name not in GIONG:
        return None
    onnx = duong_dan(name)
    if os.path.isfile(onnx) and os.path.isfile(onnx + ".json"):
        return onnx
    oid, jid, ten = GIONG[name]
    try:
        import gdown
    except Exception:
        log_fn("⚠ Cần gdown để tải giọng '%s'." % ten)
        return None
    os.makedirs(PIPER_DIR, exist_ok=True)
    try:
        log_fn("⬇ Tải giọng %s (~60MB, 1 lần)..." % ten)
        if not os.path.isfile(onnx):
            gdown.download(id=oid, output=onnx, quiet=True)
        if not os.path.isfile(onnx + ".json"):
            gdown.download(id=jid, output=onnx + ".json", quiet=True)
        return onnx if (os.path.isfile(onnx) and os.path.isfile(onnx + ".json")) else None
    except Exception as e:
        log_fn("⚠ Tải giọng %s lỗi: %s" % (ten, str(e)[:80]))
        return None
