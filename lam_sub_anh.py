# -*- coding: utf-8 -*-
"""
NHÁNH A — Biến thư mục ảnh chụp (Reddit/Threads) thành "ảnh đã đè sub + audio TTS".

Đọc noi_dung.json (schema items). Với mỗi ảnh:
  1. Dịch text gốc -> ngôn ngữ đích (Google, sl=auto).
  2. Đè chữ dịch LÊN chữ gốc (nền trắng, giữ icon) -> <ten>_<lang>.png   (dan_sub).
  3. TTS đọc text dịch -> <ten>.wav  (edge-tts; vi-VN / en-US theo đích).

Dùng:
  python lam_sub_anh.py --folder anh_chup/reddit/1u2lifp --target vi
  python lam_sub_anh.py --folder anh_chup/threads/xxx --target vi --no-tts

Ngôn ngữ đích mặc định: TARGET_LANG (env) hoặc "vi".
"""
import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys

from dan_sub import overlay_text

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

THU_MUC_GOC = os.path.dirname(os.path.abspath(__file__))
GIONG_MAC_DINH = {"vi": "vi-VN-HoaiMyNeural", "en": "en-US-AriaNeural"}


def log(msg):
    print("LOG:" + msg, flush=True)


def dich(text, target):
    """Dịch text -> target (vi/en) bằng Google (sl=auto). Lỗi -> trả text gốc."""
    text = (text or "").strip()
    if not text:
        return ""
    try:
        from phu_de import _dich_vi
        out = _dich_vi(text, sl="auto", tl=target)
        return (out or text).strip()
    except Exception as e:
        log(f"⚠ Lỗi dịch: {str(e)[:120]}")
        return text


def _mp3_to_wav(mp3, out_wav):
    """mp3 -> wav. ffmpeg trước, không có thì pydub. Trả True/False."""
    ff = shutil.which("ffmpeg")
    if ff and subprocess.run([ff, "-y", "-i", mp3, out_wav], capture_output=True).returncode == 0 \
            and os.path.isfile(out_wav):
        return True
    try:
        from pydub import AudioSegment
        AudioSegment.from_file(mp3).export(out_wav, format="wav")
        return os.path.isfile(out_wav)
    except Exception:
        return False


def _gtts_wav(text, voice, out_wav):
    """Dự phòng khi edge-tts rớt (throttle IP): gTTS (Google, hạ tầng khác). lang theo voice. True/False."""
    text = (text or "").strip()
    if not text:
        return False
    lang = "en" if (voice or "").lower().startswith("en") else "vi"
    mp3 = out_wav + ".g.mp3"
    try:
        from gtts import gTTS
        gTTS(text, lang=lang).save(mp3)
        if os.path.isfile(mp3) and os.path.getsize(mp3) > 100 and _mp3_to_wav(mp3, out_wav):
            return True
    except Exception as e:
        log("⚠ gTTS lỗi: " + str(e)[:80])
    finally:
        if os.path.isfile(mp3):
            try:
                os.remove(mp3)
            except OSError:
                pass
    return False


def tts(text, voice, out_wav):
    """edge-tts đọc text -> out_wav. Retry; edge rớt hẳn -> DỰ PHÒNG gTTS. None nếu cả hai đều thua."""
    import time
    import edge_tts
    mp3 = out_wav + ".mp3"
    loi = ""
    for lan in range(3):
        try:
            async def _go():
                await edge_tts.Communicate(text, voice).save(mp3)
            asyncio.run(_go())
            if os.path.isfile(mp3) and os.path.getsize(mp3) > 100:
                break
        except Exception as e:
            loi = str(e)[:90]
        time.sleep(1.2)
    else:
        # edge-tts rớt cả 3 lần (thường do throttle IP) -> gTTS dự phòng
        log(f"↻ edge-tts rớt ({loi or 'No audio'}) → thử gTTS...")
        if _gtts_wav(text, voice, out_wav):
            return out_wav
        log("⚠ TTS bỏ qua (cả edge-tts lẫn gTTS đều không đọc được).")
        return None
    if _mp3_to_wav(mp3, out_wav):
        try:
            os.remove(mp3)
        except OSError:
            pass
        return out_wav
    return mp3


# Nhãn UI / rác KHÔNG nên đọc (cả tiếng Anh lẫn bản dịch tiếng Việt hay gặp)
_NHAN_UI = ("See translation", "Translate", "Xem bản dịch", "Dịch",
            "Theo dõi", "Follow", "Pinned", "Đã ghim",
            "This content is unavailable", "Nội dung này không khả dụng")

# Emoji / icon / ký hiệu (để TTS không "đọc" icon)
_EMOJI_RE = re.compile(
    "[\U0001F1E0-\U0001F1FF\U0001F300-\U0001F5FF\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF\U0001F700-\U0001F77F\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF\U0001F900-\U0001F9FF\U0001FA00-\U0001FAFF"
    "\U00002600-\U000026FF\U00002700-\U000027BF\U00002B00-\U00002BFF"
    "\U00002190-\U000021FF\U000023E9-\U000023FA\U0000FE00-\U0000FE0F\U0000200D]+"
)

# Link/URL (http, www, hoặc tên miền trần kiểu about.fb.com/news) — không đọc thành lời
_URL_RE = re.compile(
    r"(?i)(?:https?://|www\.)\S+"
    r"|\b[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?(?:\.[a-z0-9\-]+)*"
    r"\.(?:com|net|org|io|vn|me|co|ly|info|app|fb|tv|gg|edu|gov)(?:/\S*)?"
)

# Mặt cười kiểu chữ (emoticon ASCII) đứng riêng — TTS đọc lạ, bỏ đi (vd :v =)) :))) xD <3 ^^ T_T)
_EMOTICON_RE = re.compile(
    r"(?<![^\s])(?:[:;=]['\"]?[-^]?[)(\]\[DPpvVoO3><|/\\]+|<3+|\^[_.]?\^|[tT]_[tT]|-_-+|x[Dd]+)(?![^\s])"
)

# Viết tắt chat tiếng Việt → đọc cho đúng (TTS hay đọc sai "mn"→"mầm non"...).
# Mỗi key chỉ thay khi ĐỨNG RIÊNG một token (regex \b...\b) nên không phá chữ trong từ.
# Chửi tục để dạng đánh vần chữ cái (vl→"vê lờ") để TTS không phát ra tiếng chửi nguyên.
_VIET_TAT = {
    # không
    "k": "không", "ko": "không", "kh": "không", "khg": "không", "hok": "không",
    "hokk": "không", "hem": "không", "hum": "không", "hong": "không", "hông": "không",
    # được
    "dc": "được", "đc": "được",
    # anh em / mọi người / mình / tao tôi
    "ae": "anh em", "ace": "anh chị em",
    "mn": "mọi người", "mng": "mọi người",
    "mk": "mình", "mik": "mình", "mjk": "mình",
    "t": "tao", "tui": "tôi",
    # quan hệ
    "ny": "người yêu", "nyc": "người yêu cũ",
    "ck": "chồng", "ox": "chồng", "vk": "vợ", "bx": "vợ",
    # mạng xã hội / tương tác
    "ib": "inbox", "inb": "inbox", "rep": "trả lời", "trl": "trả lời",
    "cmt": "bình luận", "cmttt": "bình luận", "ad": "admin", "acc": "tài khoản",
    "fb": "facebook", "ig": "instagram", "ins": "instagram", "tt": "tiktok",
    "mxh": "mạng xã hội", "nt": "nhắn tin", "ntin": "nhắn tin",
    "kb": "kết bạn", "gr": "group", "ib": "inbox",
    # đời thường
    "bt": "biết", "bk": "biết", "kbiet": "không biết",
    "z": "vậy", "zậy": "vậy", "ntn": "như thế nào", "ntnh": "như thế này",
    "vs": "với", "r": "rồi", "oy": "rồi", "ms": "mới", "cx": "cũng",
    "cg": "cái gì", "j": "gì", "ji": "gì",
    "bth": "bình thường", "trc": "trước",
    "bh": "bao giờ", "đbh": "đéo bao giờ", "tg": "tác giả",
    # chửi tục → đánh vần (TTS không phát tiếng chửi)
    "vl": "vê lờ", "vcl": "vê cờ lờ", "vkl": "vê ka lờ",
    "dm": "đờ mờ", "đm": "đờ mờ", "đcm": "đờ cờ mờ", "đjt": "địt",
    # tiếng Anh chat → đánh vần / đọc
    "wtf": "double u tê ép", "omg": "ô em gi", "lmao": "lờ mao",
    "btw": "by the way", "afaik": "as far as i know",
    "imo": "in my opinion", "irl": "in real life", "otp": "ô ti pi",
    "cr": "crush", "cp": "couple", "stv": "sinh tố viên",
    "rv": "review", "rvp": "review phim",
    # học hành / địa danh
    "sđt": "số điện thoại", "dt": "điện thoại", "msv": "mã sinh viên",
    "sv": "sinh viên", "gv": "giảng viên", "ktx": "ký túc xá",
    "hn": "Hà Nội", "hcm": "Hồ Chí Minh", "sg": "Sài Gòn",
    "vn": "Việt Nam", "tphcm": "thành phố Hồ Chí Minh",
}
_VIET_TAT_RE = re.compile(r"(?iu)\b(" + "|".join(map(re.escape, _VIET_TAT)) + r")\b")


def _bung_viettat(text):
    return _VIET_TAT_RE.sub(lambda m: _VIET_TAT.get(m.group(0).lower(), m.group(0)), text)


def _loc_doc_tts(text, author=""):
    """Làm SẠCH text trước khi TTS đọc:
    - bỏ link/URL (about.fb.com/news…), emoji/icon, @handle tác giả, nhãn UI (Translate/Pinned…);
    - đổi NBSP→space; bung viết tắt chat (mn→mọi người) để TTS không đọc sai.
    Gọi được cả trước và sau khi dịch (idempotent)."""
    text = (text or "").replace("\xa0", " ").strip()
    if not text:
        return ""
    text = _URL_RE.sub(" ", text)
    text = _EMOJI_RE.sub(" ", text)
    text = _EMOTICON_RE.sub(" ", text)
    for w in _NHAN_UI:
        text = re.sub(r"(?im)(?:^|\s)" + re.escape(w) + r"(?=\s|$|[.,!?])", " ", text)
    a = (author or "").lstrip("@").strip()
    if a:
        text = re.sub(r"(?i)@?" + re.escape(a) + r"\b", " ", text)
    text = _bung_viettat(text)
    return re.sub(r"\s{2,}", " ", text).strip()


def xu_ly_item(folder, it, target, voice, lam_tts):
    img_file = it.get("anh")
    src = os.path.join(folder, img_file) if img_file else ""
    if not src or not os.path.isfile(src):
        return None

    dst = os.path.join(folder, os.path.splitext(img_file)[0] + f"_{target}.png")
    shutil.copyfile(src, dst)
    da_de = 0
    tts_parts = []
    for v in (it.get("vung") or []):
        text, bbox = v.get("text", ""), v.get("bbox")
        if not (text and bbox):
            continue
        vi = dich(text, target)
        tts_parts.append(vi)
        if vi.strip().lower() != text.strip().lower():   # chỉ đè khi thật sự khác (đã dịch)
            overlay_text(dst, bbox, vi, dst)
            da_de += 1
    if da_de == 0:
        os.remove(dst)
        dst = src

    wav = None
    if lam_tts:
        # ĐỌC nội dung sạch (field "tts" = thân bài), KHÔNG đọc các vùng phụ (tên người đăng, "Translate"...).
        # Làm sạch TRƯỚC dịch (bỏ link/emoji/nhãn UI gốc + bung viết tắt) rồi làm sạch lại SAU dịch (nhãn UI tiếng Việt).
        raw = (it.get("tts") or "").strip()
        if raw:
            doc = _loc_doc_tts(dich(_loc_doc_tts(raw, it.get("author")), target), it.get("author"))
        else:
            doc = _loc_doc_tts(" ".join(tts_parts), it.get("author"))
        if doc.strip():
            wav = tts(doc, voice, os.path.join(folder, os.path.splitext(img_file)[0] + ".wav"))
    log(f"✔ {img_file} [{it.get('loai','')}]: đè {da_de} vùng" + (f" + TTS {os.path.basename(wav)}" if wav else ""))
    return {"loai": it.get("loai"), "anh": os.path.basename(dst), "wav": os.path.basename(wav) if wav else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", required=True)
    ap.add_argument("--target", default=os.environ.get("TARGET_LANG", "vi"), choices=["vi", "en"])
    ap.add_argument("--voice", default="")
    ap.add_argument("--no-tts", action="store_true")
    a = ap.parse_args()

    meta_path = os.path.join(a.folder, "noi_dung.json")
    if not os.path.isfile(meta_path):
        log(f"⚠ Không thấy {meta_path} (cần chụp bằng chup_bai.py trước).")
        print("SUB_DONE 0", flush=True)
        return
    meta = json.load(open(meta_path, encoding="utf-8"))
    items = meta.get("items") or []
    voice = a.voice or GIONG_MAC_DINH[a.target]
    lam_tts = not a.no_tts

    ket = []
    for it in items:
        try:
            r = xu_ly_item(a.folder, it, a.target, voice, lam_tts)
        except Exception as e:
            log(f"⚠ Lỗi xử lý {it.get('anh')}: {str(e)[:100]}")
            r = None
        if r:
            ket.append(r)

    with open(os.path.join(a.folder, "sub.json"), "w", encoding="utf-8") as f:
        json.dump({"target": a.target, "items": ket}, f, ensure_ascii=False, indent=2)
    log(f"✔ Xong {len(ket)} ảnh → {os.path.relpath(a.folder, THU_MUC_GOC)}")
    print(f"SUB_DONE {len(ket)}", flush=True)


if __name__ == "__main__":
    main()
