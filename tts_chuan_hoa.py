# -*- coding: utf-8 -*-
"""Chuẩn hoá văn bản tiếng Việt TRƯỚC khi đưa vào TTS (Piper/Edge/F5) — port logic của NghiTTS
(github.com/nghimestudio/nghitts, src/utils/vietnamese-processor.js) sang Python.

Mục tiêu: TTS đọc ĐÚNG số/ngày/giờ/tiền/%/SĐT/số La Mã thay vì đọc từng chữ số hoặc đọc sai.
Ví dụ:  "1.000.000đ" → "một triệu đồng" · "25/12/2024" → "ngày hai mươi lăm tháng mười hai năm
hai nghìn không trăm hai mươi tư" · "50%" → "năm mươi phần trăm" · "7,5" → "bảy phẩy năm".

CHỈ áp cho text đưa vào TTS (giọng nói) — KHÔNG đụng phụ đề hiển thị (giữ số dạng chữ số cho dễ đọc).
"""
import re

_DIGITS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]
_SCALE = ["", " nghìn", " triệu", " tỷ"]


def _doc_3(n, full):
    """Đọc nhóm 0-999. full=True (nhóm KHÔNG phải cao nhất) → ép 'trăm' + 'lẻ' cho khớp cách đọc VN."""
    tram, rem = divmod(n, 100)
    chuc, dvi = divmod(rem, 10)
    parts = []
    if tram > 0 or full:
        parts.append(_DIGITS[tram] + " trăm")
    if chuc == 0:
        if dvi > 0:
            parts.append(("lẻ " + _DIGITS[dvi]) if (tram > 0 or full) else _DIGITS[dvi])
    elif chuc == 1:
        parts.append("mười" if dvi == 0 else ("mười lăm" if dvi == 5 else "mười " + _DIGITS[dvi]))
    else:
        s = _DIGITS[chuc] + " mươi"
        if dvi == 1:
            s += " mốt"
        elif dvi == 4:
            s += " tư"
        elif dvi == 5:
            s += " lăm"
        elif dvi > 0:
            s += " " + _DIGITS[dvi]
        parts.append(s)
    return " ".join(parts).strip()


def doc_so(n):
    """Số nguyên → chữ tiếng Việt (mốt/tư/lăm/lẻ/mười đúng quy tắc). Hỗ trợ tới hàng nghìn tỷ."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return str(n)
    if n == 0:
        return "không"
    neg = n < 0
    n = abs(n)
    groups = []
    while n > 0:
        n, g = divmod(n, 1000)
        groups.append(g)               # groups[0] = nhóm thấp nhất
    ng = len(groups)
    out = []
    for idx in range(ng - 1, -1, -1):
        g = groups[idx]
        if g == 0:
            continue                    # bỏ nhóm rỗng (vd 1 triệu lẻ 5)
        full = (idx != ng - 1)          # nhóm không-cao-nhất → ép trăm + lẻ
        scale = _SCALE[idx] if idx < len(_SCALE) else (" tỷ" * (idx - 2))   # >tỷ: lặp 'tỷ'
        out.append(_doc_3(g, full) + scale)
    s = " ".join(out).strip()
    return ("âm " + s) if neg else s


def _bo_ngan_cach(m):
    """1.000.000 → 1000000 (xoá dấu chấm ngăn cách nghìn, lặp tới hết)."""
    return m.group(0).replace(".", "")


def _doc_tung_so(s):
    return " ".join(_DIGITS[int(c)] for c in s if c.isdigit())


# La Mã → Ả Rập (chỉ chuỗi ≥2 ký tự hợp lệ để tránh nhầm "I","V","X" lẻ trong tên/viết tắt)
_ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def _roman_to_int(s):
    s = s.upper()
    if not re.fullmatch(r"M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})", s) or not s:
        return None
    tot = 0
    prev = 0
    for c in reversed(s):
        v = _ROMAN[c]
        tot += -v if v < prev else v
        prev = max(prev, v)
    return tot


# ===== CHUYỂN TỰ Anh/ngoại → phiên âm tiếng Việt (để Piper/Edge đọc tự nhiên) =====
# AN TOÀN: CHỈ chuyển từ trong TỪ ĐIỂN + acronym viết HOA; từ thường lạ GIỮ NGUYÊN (tránh
# hỏng từ tiếng Việt không dấu như "anh/em/ban/nam"). Giá trị dùng KHOẢNG TRẮNG ngăn âm tiết.
_PHIEN_AM = {
    # mạng xã hội / app
    "google": "gu gồ", "facebook": "phây búc", "fb": "phây búc", "youtube": "diu túp",
    "tiktok": "tích tóc", "instagram": "in sờ ta gram", "insta": "in sờ ta", "twitter": "tuýt tơ",
    "telegram": "te lê gram", "zalo": "za lô", "messenger": "mét sần dơ", "tinder": "tin đơ",
    "reddit": "rét đít", "threads": "thrét", "discord": "đít co", "twitch": "tuých",
    # hãng / sản phẩm
    "iphone": "ai phôn", "ipad": "ai pát", "macbook": "mác búc", "apple": "áp pồ",
    "samsung": "sam sung", "xiaomi": "xao mi", "oppo": "ốp pô", "vivo": "vi vô", "huawei": "hoa uây",
    "android": "an đờ roi", "windows": "quin đâu", "microsoft": "mai cờ rô sốp", "google pixel": "gu gồ pích sồ",
    "nvidia": "en vi đi a", "amd": "a em đê", "intel": "in teo", "tesla": "tét la", "spacex": "sờ pây ếch",
    "nasa": "na sa", "amazon": "a ma dôn", "netflix": "nét phờ lích", "spotify": "sờ pô ti phai",
    # AI / công nghệ
    "chatgpt": "chát gi pi ti", "openai": "ô pừn ây ai", "gpt": "gi pi ti", "deepseek": "đíp sích",
    "gemini": "ghê mi nai", "claude": "cờ lốt", "grok": "gờ rốc", "midjourney": "mít jơ ni",
    "wifi": "quai phai", "bluetooth": "blu tút", "email": "i meo", "gmail": "ghi meo",
    "internet": "in tơ nét", "online": "on lai", "offline": "óp lai", "website": "guép sai",
    "app": "áp", "web": "guép", "server": "sơ vơ", "laptop": "láp tóp", "pc": "pi xi",
    "smartphone": "sờ mát phôn", "robot": "rô bốt", "drone": "đ rôn", "camera": "ca mê ra",
    "video": "vi đê ô", "clip": "cờ líp", "live": "lai", "stream": "sờ t rim", "livestream": "lai sờ t rim",
    "usb": "diu ét bi", "cpu": "xi pi diu", "gpu": "gi pi diu", "ram": "ram", "ssd": "ét ét đê",
    "hdd": "ếch đê đê", "led": "lét", "lcd": "eo xi đi", "oled": "ô lét", "hd": "ếch đê", "ai": "ây ai",
    # chào / thông dụng
    "hello": "he lô", "hi": "hai", "ok": "ô kê", "okay": "ô kê", "yes": "dét", "no": "nâu",
    "bye": "bai", "sorry": "so ri", "thanks": "then kiu", "wow": "oao", "cool": "kun",
    "free": "phờ ri", "sale": "xêu", "shop": "sốp", "order": "ót đơ", "ship": "síp",
    # đơn vị viết tắt (đọc đầy đủ)
    "usd": "đô la Mỹ", "vnd": "việt nam đồng", "eur": "ơ rô", "km": "ki lô mét",
    "kg": "ki lô gam", "gb": "ghi ga bai", "mb": "mê ga bai", "tb": "tê ra bai", "kb": "ki lô bai",
    "mm": "mi li mét", "cm": "xen ti mét", "kw": "ki lô oát", "mp": "mê ga pích sồ",
}
# Đánh vần acronym viết HOA lạ (2-5 chữ): G→gi, P→pi... (kiểu đọc thông dụng tiếng Việt)
_VAN_CHU = {"a": "ây", "b": "bi", "c": "xi", "d": "đi", "e": "i", "f": "ép", "g": "gi",
            "h": "hét", "i": "ai", "j": "giây", "k": "kây", "l": "eo", "m": "em", "n": "en",
            "o": "ô", "p": "pi", "q": "kiu", "r": "a", "s": "ét", "t": "ti", "u": "diu",
            "v": "vi", "w": "đáp liu", "x": "ích", "y": "quai", "z": "dét"}


def _phien_am_tu(tok):
    """1 token chữ Latin → phiên âm nếu trong từ điển / là acronym HOA; không thì GIỮ NGUYÊN."""
    low = tok.lower()
    if low in _PHIEN_AM:
        return _PHIEN_AM[low]
    # acronym: TOÀN HOA, 2-5 chữ cái (NASA đã ở dict; GPT/USB... đánh vần)
    if 2 <= len(tok) <= 5 and tok.isupper() and tok.isalpha():
        return " ".join(_VAN_CHU.get(c.lower(), c) for c in tok)
    return tok


def chuyen_tu(text):
    """Chuyển token ngoại trong câu sang phiên âm Việt (an toàn — chỉ dict + acronym HOA)."""
    # km/h, m/s... → đọc "trên"
    text = re.sub(r"\bkm/h\b", "ki lô mét trên giờ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bm/s\b", "mét trên giây", text, flags=re.IGNORECASE)
    # tách giữ nguyên dấu câu, chỉ đụng cụm chữ Latin thuần
    return re.sub(r"[A-Za-z][A-Za-z']*", lambda m: _phien_am_tu(m.group(0)), text)


def chuan_hoa(text):
    """Chuẩn hoá 1 câu tiếng Việt cho TTS: số/ngày/tiền → chữ + chuyển tự Anh→phiên âm Việt."""
    if not text or not any(c.isdigit() for c in text):
        return text                     # không có số → khỏi xử lý (đa số câu)
    t = " " + text + " "

    # 1) Xoá dấu chấm ngăn cách nghìn: 1.000.000 → 1000000
    for _ in range(4):
        t = re.sub(r"\d{1,3}(?:\.\d{3})+", _bo_ngan_cach, t)

    # 2) Ngày/giờ (trước khi tách số lẻ)
    t = re.sub(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b",
               lambda m: "ngày %s tháng %s năm %s" % (doc_so(m.group(1)), doc_so(m.group(2)), doc_so(m.group(3))), t)
    t = re.sub(r"\b(\d{1,2})[/-](\d{4})\b",
               lambda m: "tháng %s năm %s" % (doc_so(m.group(1)), doc_so(m.group(2))), t)
    t = re.sub(r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b",
               lambda m: ("%s giờ %s phút" % (doc_so(m.group(1)), doc_so(m.group(2))))
                         + (" %s giây" % doc_so(m.group(3)) if m.group(3) else ""), t)
    t = re.sub(r"\b(\d{1,2})h(\d{2})\b",
               lambda m: "%s giờ %s phút" % (doc_so(m.group(1)), doc_so(m.group(2))), t)

    # 3) Số La Mã (≥2 ký tự) — đứng riêng
    def _rep_roman(m):
        v = _roman_to_int(m.group(1))
        return doc_so(v) if v else m.group(0)
    t = re.sub(r"(?<![\wÀ-ỹ])([IVXLCDM]{2,})(?![\wÀ-ỹ])", _rep_roman, t)

    # 4) Tiền tệ
    t = re.sub(r"\$\s*(\d+)", lambda m: doc_so(m.group(1)) + " đô la", t)
    t = re.sub(r"(\d+)\s*(?:đồng|VND|VNĐ|vnđ|đ)\b",
               lambda m: doc_so(m.group(1)) + " đồng", t, flags=re.IGNORECASE)

    # 5) Phần trăm (kèm khoảng A-B%)
    t = re.sub(r"(\d+)\s*[-–—]\s*(\d+)\s*%",
               lambda m: "%s đến %s phần trăm" % (doc_so(m.group(1)), doc_so(m.group(2))), t)
    t = re.sub(r"(\d+)\s*%", lambda m: doc_so(m.group(1)) + " phần trăm", t)

    # 6) Thập phân (dấu PHẨY = thập phân trong tiếng Việt): 7,5 → bảy phẩy năm (phần lẻ đọc từng số)
    t = re.sub(r"(\d+),(\d+)",
               lambda m: "%s phẩy %s" % (doc_so(m.group(1)), _doc_tung_so(m.group(2))), t)

    # 7) Khoảng số 5-10 → 5 đến 10 (cả 2 vế là số)
    t = re.sub(r"(\d+)\s*[-–—]\s*(\d+)",
               lambda m: "%s đến %s" % (doc_so(m.group(1)), doc_so(m.group(2))), t)

    # 8) Số điện thoại (0 + 9-10 số) → đọc từng số
    t = re.sub(r"\b0\d{9,10}\b", lambda m: _doc_tung_so(m.group(0)), t)

    # 9) Số âm còn lại (-5 → âm 5; không dính ngày/khoảng đã xử lý)
    t = re.sub(r"(?<![\d\w])-\s*(\d+)", lambda m: "âm " + doc_so(m.group(1)), t)

    # 10) Số nguyên còn lại → chữ
    t = re.sub(r"\d+", lambda m: doc_so(m.group(0)), t)

    # 11) Dọn khoảng trắng
    t = re.sub(r"\s+", " ", t).strip()
    return t


if __name__ == "__main__":      # test nhanh: python tts_chuan_hoa.py
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    for s in ["Giá 1.000.000đ giảm 50% còn 500000 đồng",
              "Hôm nay 25/12/2024 lúc 15:30, nhiệt độ 7,5 độ",
              "Gọi 0987654321 trong khoảng 5-10 phút",
              "Thế kỷ XXI, chương IV, âm 3 độ", "Bình thường không có số"]:
        print(repr(s), "→", repr(chuan_hoa(s)))
