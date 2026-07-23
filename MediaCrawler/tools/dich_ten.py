# -*- coding: utf-8 -*-
"""Dịch TIÊU ĐỀ video (Trung) sang ngôn ngữ đích để ĐẶT TÊN FILE khi cào
douyin/bilibili/xhs — không chỉ dịch hiển thị trên màn hình.

- Ngôn ngữ đích đọc qua env TARGET_LANG (vi/en) do web_app truyền vào subprocess cào.
- Dùng Google Translate web (không cần key), cache theo từng nền tảng để khỏi gọi lại.
- Không có chữ Trung -> giữ nguyên (đỡ tốn request). Lỗi mạng -> trả về gốc, KHÔNG cache (để thử lại lần sau).
- KHÔNG làm sạch/cắt ở đây: chỗ gọi đã bọc _safe_name(...) để bỏ ký tự cấm + cắt độ dài.
"""
import json
import os
import threading
import urllib.parse
import urllib.request

import config

_CACHE = {}            # {đường_dẫn_cache: {tiêu đề gốc: bản dịch}}
_LOCK = threading.Lock()


def _data_base() -> str:
    return config.SAVE_DATA_PATH if config.SAVE_DATA_PATH else "data"


def _target_lang() -> str:
    tl = (os.environ.get("TARGET_LANG") or "vi").strip().lower()
    return tl if tl in ("vi", "en") else "vi"


def _co_chu_trung(s: str) -> bool:
    return any("一" <= c <= "鿿" for c in (s or ""))


def _load_cache(path: str) -> dict:
    if path not in _CACHE:
        c = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    c = json.load(f)
            except Exception:
                c = {}
        _CACHE[path] = c
    return _CACHE[path]


def dich_tieu_de(text: str, platform: str) -> str:
    """Dịch tiêu đề video Trung -> ngôn ngữ đích (TARGET_LANG); cache theo nền tảng.
    Không có chữ Trung -> giữ nguyên. Lỗi/không dịch được -> trả về gốc."""
    text = (text or "").strip()
    if not text or not _co_chu_trung(text):
        return text
    lang = _target_lang()
    path = os.path.join(_data_base(), platform, f"_tieude_{lang}.json")
    c = _load_cache(path)
    if text in c:
        return c[text]
    # Tiêu đề douyin hay kèm cả "rừng" hashtag -> cắt nguồn ~120 ký tự cho gọn request
    # (chỗ gọi vẫn cắt tiếp về 50-60 nên không mất gì).
    nguon = text[:120]
    try:
        url = ("https://translate.googleapis.com/translate_a/single"
               "?client=gtx&sl=zh-CN&tl=" + lang + "&dt=t&q=" + urllib.parse.quote(nguon))
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read().decode("utf-8"))
        vi = "".join(s[0] for s in d[0] if s and s[0]).strip()
    except Exception:
        return text   # lỗi mạng -> giữ gốc, KHÔNG cache (thử lại lần sau)
    if not vi:
        return text
    with _LOCK:
        c[text] = vi
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(c, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    return vi
