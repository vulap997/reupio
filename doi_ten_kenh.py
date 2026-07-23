# -*- coding: utf-8 -*-
"""
Đổi tên các thư mục kênh hiện có sang TIẾNG VIỆT (cho người Việt dễ đọc).
Vd: 吃货老外铁蛋儿 (Foodie foreigner Tiedaner)  ->  Người nước ngoài háu ăn Thiết Đản
Lấy lại tên gốc tiếng Trung (bỏ hậu tố "(English)" cũ nếu có) rồi dịch sang tiếng Việt.
Dùng chung cache _kenh_vi.json + cùng cách làm sạch tên với crawler để khớp folder lúc cào.
Áp dụng cho cả data/douyin/videos/kenh và processed_videos/kenh.
"""

import json
import os
import re
import sys
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

THU_MUC_GOC = os.path.dirname(os.path.abspath(__file__))
# Gốc data/processed = env (userData/user-chọn → BỀN qua update) nếu có; else chỗ cũ.
_DATA = (os.environ.get("MC_DATA_DIR") or "").strip() or os.path.join(THU_MUC_GOC, "MediaCrawler", "data")
_PROC = (os.environ.get("VC_PROCESSED_DIR") or "").strip() or os.path.join(THU_MUC_GOC, "processed_videos")
CACHE = os.path.join(_DATA, "douyin", "_kenh_vi.json")
THU_MUC_KENH = [
    os.path.join(_DATA, "douyin", "videos", "kenh"),
    os.path.join(_PROC, "kenh"),
]

# Giống _safe_name trong core.py để tên folder migrate khớp tên lúc cào
_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}


def safe_name(s, maxlen=40):
    s = (s or "").strip()
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", s)
    s = re.sub(r"\s+", " ", s).strip().rstrip(". ")
    s = s[:maxlen].strip() or "video"
    if s.upper() in _WIN_RESERVED:
        s += "_"
    return s


_cache = None


def load_cache():
    global _cache
    if _cache is None:
        _cache = {}
        if os.path.exists(CACHE):
            try:
                with open(CACHE, encoding="utf-8") as f:
                    _cache = json.load(f)
            except Exception:
                _cache = {}
    return _cache


def save_cache():
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    try:
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(_cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def dich_vi(name):
    """Dịch tên kênh sang tiếng Việt; cache. Trả "" nếu đã Latin / lỗi mạng."""
    c = load_cache()
    if name in c:
        return c[name]
    ascii_letters = sum(1 for ch in name if ord(ch) < 128 and ch.isalpha())
    vi = ""
    if ascii_letters < max(3, len(name.replace(" ", "")) * 0.5):
        try:
            _tl = (os.environ.get("TARGET_LANG") or "vi").strip().lower()
            if _tl not in ("vi", "en"):
                _tl = "vi"
            url = ("https://translate.googleapis.com/translate_a/single"
                   "?client=gtx&sl=auto&tl=" + _tl + "&dt=t&q=" + urllib.parse.quote(name))
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                d = json.loads(r.read().decode("utf-8"))
            vi = "".join(s[0] for s in d[0] if s and s[0]).strip()
            vi = re.sub(r'[\\/:*?"<>|]+', " ", vi).strip()[:40].strip()
        except Exception:
            vi = ""
    c[name] = vi
    save_cache()
    return vi


def main():
    doi = 0
    for base in THU_MUC_KENH:
        if not os.path.isdir(base):
            continue
        for ten in os.listdir(base):
            cu = os.path.join(base, ten)
            if not os.path.isdir(cu):
                continue
            # Lấy lại tên gốc tiếng Trung: bỏ hậu tố " (English)" cũ nếu có
            goc = ten.split(" (")[0].strip() if (" (" in ten and ten.rstrip().endswith(")")) else ten
            vi = dich_vi(goc)
            if not vi:
                print(f"  (bỏ qua, không dịch được): {ten}")
                continue
            moi_ten = safe_name(vi, 40)
            if moi_ten == ten:
                continue  # đã là tên Việt rồi
            moi = os.path.join(base, moi_ten)
            if os.path.exists(moi):
                print(f"  (đích đã tồn tại, gộp thủ công): {ten}  ->  {moi_ten}")
                continue
            try:
                os.rename(cu, moi)
                print(f"  ✔ {ten}  ->  {moi_ten}")
                doi += 1
            except OSError as e:
                print(f"  ✖ Lỗi đổi tên {ten}: {e}")
    print(f"\nĐã đổi tên {doi} thư mục kênh sang tiếng Việt.")


if __name__ == "__main__":
    main()
