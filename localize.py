# -*- coding: utf-8 -*-
"""
PHẦN 1 — Dịch & Phụ đề (chạy LOCAL, không cần GPU). Phục vụ học tập.

Luồng:  video tiếng Trung
  → Faster-Whisper nghe   → zh.srt (phụ đề gốc)
  → Dịch Google (+ AI sửa nếu chọn) → vi.srt   [áp từ điển sửa thuật ngữ]
  → FFmpeg: che chữ Trung (drawbox) + burn phụ đề Việt → <ten>_phude.mp4

Dùng:  python localize.py "video.mp4" [--model small] [--engine google|ai] [--no-che] [--no-burn]
In ra các dòng "LOG:..." để web_app đọc hiển thị tiến trình.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import phu_de  # tái dùng WhisperModel + _ts + _dich_vi (Google)
import thong_tin_may  # RAM/CPU dùng chung (Windows ctypes + fallback macOS/Linux)
import xu_ly_video  # tái dùng co_nvenc() để encode bằng GPU NVIDIA nếu có

# Chuẩn hoá text cho TTS đọc đúng số/ngày/tiền/%/đơn-vị + PHIÊN ÂM từ tiếng Anh→Việt (iPhone→ai-phôn,
# coding→cô-đinh). ƯU TIÊN vietnormalizer (đầy đủ + transliterate, MIT, stdlib-only); lỗi → lùi tts_chuan_hoa.py
# (port NghiTTS: số/ngày/tiền); cả 2 lỗi → no-op an toàn. (User chọn: vietnormalizer + fallback port cũ.)
try:
    import tts_chuan_hoa
    _chuan_hoa_port = tts_chuan_hoa.chuan_hoa
except Exception:
    def _chuan_hoa_port(s):
        return s
try:
    from vietnormalizer import VietnameseNormalizer
    _vn_norm = VietnameseNormalizer()

    def _chuan_hoa_vi(s):
        try:
            r = _vn_norm.normalize(s)
            return r if (r or "").strip() else s   # normalizer trả rỗng (text không-Việt) → giữ gốc (an toàn kép)
        except Exception:
            return _chuan_hoa_port(s)   # vietnormalizer lỗi câu này → lùi port cũ
except Exception:
    _chuan_hoa_vi = _chuan_hoa_port     # vietnormalizer chưa cài → dùng port cũ


def _chuan_hoa_tts(s):
    """Chuẩn hoá text cho TTS. vietnormalizer CHỈ đúng cho TIẾNG VIỆT (số/ngày/tiền → chữ Việt + phiên âm
    Anh→Việt: iPhone→ai-phôn) → CHỈ áp khi ĐÍCH = 'vi'. Đích KHÁC giữ NGUYÊN text: voice đích tự đọc số/chữ
    theo tiếng nó; nếu ép normalizer Việt sẽ (a) chèn chữ số/phiên-âm VIỆT SAI vào câu ngôn ngữ khác, hoặc
    (b) XOÁ RỖNG chữ không-Latin (Thái/Ả Rập/Nga/Nhật/Hàn...) → TTS bỏ câu → dub mất tiếng."""
    if not (s or "").strip():
        return s
    try:
        import ngon_ngu
        if ngon_ngu.target_lang() != "vi":
            return s
    except Exception:
        pass
    return _chuan_hoa_vi(s)

# Phồn→Giản (繁→简) cho DEDUP: OCR đọc CÙNG 1 dòng hardsub qua nhiều frame, lần ra chữ PHỒN THỂ, lần ra
# GIẢN THỂ (傑克薩利講 vs 杰克萨利讲) → byte KHÁC nhau → _dedup_lap/_gan_giong so trượt (đo thật r=0.40 ko bắt
# được). Chuẩn-hoá về giản thể TRƯỚC khi so → 2 bản trùng khớp lại. zhconv = pure-python, MIT; thiếu → no-op
# (dedup lùi về hành vi cũ, KHÔNG crash). CHỈ dùng để SO SÁNH dedup — KHÔNG đổi text gốc đưa vào Gemini/zh.srt.
try:
    from zhconv import convert as _zhconvert

    def _t2s(s):
        try:
            return _zhconvert(s or "", "zh-hans")
        except Exception:
            return s or ""
except Exception:
    def _t2s(s):
        return s or ""

THU_MUC_GOC = os.path.dirname(os.path.abspath(__file__))


def log(msg):
    print("LOG:" + msg, flush=True)


def _seg(i, st, en, src):
    """Phát 1 dòng vừa nhận diện (web hiện bảng SRT điền dần ở tab Tiến trình)."""
    print("SEG|" + json.dumps({"i": i, "st": round(float(st), 3), "en": round(float(en), 3),
                               "src": src}, ensure_ascii=False), flush=True)


def _segvi(i, vi):
    print("SEGVI|" + json.dumps({"i": i, "vi": vi}, ensure_ascii=False), flush=True)


# ---------------- Từ điển sửa thuật ngữ (dùng chung mọi video) ----------------
FILE_TU_DIEN = os.path.join(THU_MUC_GOC, "tu_dien_dich.json")
_TU_DIEN = None


def _load_tu_dien():
    global _TU_DIEN
    if _TU_DIEN is None:
        _TU_DIEN = {}
        if os.path.exists(FILE_TU_DIEN):
            try:
                with open(FILE_TU_DIEN, encoding="utf-8") as f:
                    _TU_DIEN = json.load(f)
            except Exception:
                _TU_DIEN = {}
    return _TU_DIEN


def ap_tu_dien(vi):
    """Thay 'từ sai → từ đúng' theo từ điển (không phân biệt hoa thường)."""
    import re
    for sai, dung in _load_tu_dien().items():
        if sai:
            vi = re.sub(re.escape(sai), dung, vi, flags=re.IGNORECASE)
    return vi


# ---------------- Dịch (Google MT, áp từ điển) ----------------
def dich_dong(text):
    """Dịch 1 câu bằng Google rồi áp từ điển sửa."""
    text = (text or "").strip()
    if not text:
        return ""
    return ap_tu_dien(phu_de._dich_vi(text, sl="zh-CN") or text)


def doc_srt(path):
    """Đọc file .srt → [(start_giây, end_giây, text)]."""
    import re
    segs = []
    if not os.path.isfile(path):
        return segs
    with open(path, encoding="utf-8") as f:
        khoi = f.read().strip().split("\n\n")
    for k in khoi:
        dong = [d for d in k.splitlines() if d.strip()]
        if len(dong) < 2:
            continue
        m = re.search(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)", k)
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        st = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000.0
        en = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000.0
        txt = " ".join(dong[2:]) if len(dong) > 2 else ""
        segs.append((st, en, txt))
    return segs


# ---------------- ASR + SRT ----------------
# Câu whisper hay BỊA ở đầu/cuối (credit phụ đề, kêu gọi like/sub) — KHÔNG có trong tiếng nói thật → bỏ.
# Cả giản thể lẫn phồn thể; so khớp sau khi bỏ dấu cách + thường hoá.
_AO_GIAC = (
    "字幕by", "字幕组", "字幕組", "字幕志愿", "字幕志願", "字幕制作", "字幕製作", "字幕提供",
    "amara.org", "请不吝", "請不吝", "点赞订阅", "點贊訂閱", "点赞转发", "點贊轉發",
    "点赞关注", "點贊關注", "请点赞", "請點贊", "明镜与点点", "明鏡與點點", "点点栏目", "點點欄目",
    "谢谢观看", "謝謝觀看", "感谢观看", "感謝觀看", "感谢您的观看", "感謝您的觀看",
    "谢谢收看", "謝謝收看", "谢谢大家观看", "謝謝大家觀看",
)


def _la_ao_giac(t):
    s = (t or "").lower().replace(" ", "")
    return any(m in s for m in _AO_GIAC)


def _transcribe_thu(model, video, src_lang, on_seg=None, quiet=False):
    """Nhận dạng 1 lượt. GPU chạy THẬT khi LẶP generator (không phải lúc gọi transcribe)
    → lỗi/OOM GPU cũng bung ra ở vòng lặp này, không phải lúc nạp model.
    on_seg(st,en,zh): callback mỗi đoạn vừa nghe → cho phép DỊCH SONG SONG ngay khi đang nghe."""
    # Tiếng Trung: ép 'zh'. Nguồn KHÁC (Anh/Việt/Nhật...): để whisper TỰ DÒ ngôn ngữ → phụ đề đúng tiếng
    # gốc (tên file chỉ biết "không phải Trung", không biết tiếng gì cụ thể).
    lang = src_lang if _la_tieng_trung(src_lang) else None
    segments, _info = phu_de._transcribe(
        model, video, log=(None if quiet else log), language=lang, task="transcribe",
        vad_filter=True, vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=False,   # tránh lặp ảo giác kiểu "乖乖 乖乖 乖乖..."
        temperature=0.0, compression_ratio_threshold=2.4, no_speech_threshold=0.6)
    segs = []
    for s in segments:
        t = (s.text or "").strip()
        if not t or _la_ao_giac(t):      # bỏ câu whisper BỊA (credit/sub) trước khi stream + dịch + lồng tiếng
            continue
        # LỌC ẢO GIÁC VÙNG KHÔNG LỜI (nhạc/intro/tiếng động): Whisper bịa 1 câu NGẮN kéo DÀI bất thường
        # (vd '中康女為行美塞' 7 chữ suốt 66s ở đoạn gõ chiêng) → mật độ chữ/giây cực thấp; Gemini dịch chuỗi
        # rác này ra '(Audio corrupted)'. Câu NÓI thật dày hơn nhiều (2-5 chữ/giây). Chỉ loại câu NGẮN
        # (≤10 chữ) mà TRẢI dài (≥6s) + mật độ <0.6 → không đụng câu nói thật (dày) hay câu ngắn-nhanh (dur nhỏ).
        _dur = float(s.end) - float(s.start)
        _nchar = len(t.replace(" ", ""))
        if _dur >= 6.0 and _nchar <= 10 and _nchar / max(_dur, 0.1) < 0.6:
            continue
        segs.append((s.start, s.end, t))
        if not quiet:                    # quiet=True: thread Whisper-bù chạy NỀN, chỉ thu (không hiện rối UI OCR)
            _seg(len(segs), s.start, s.end, t)   # hiện ngay dòng vừa nghe
            if on_seg:
                on_seg(len(segs), s.start, s.end, t)   # đẩy sang luồng dịch nền KÈM chỉ số đoạn → khớp Dịch
    return segs


def _la_tieng_trung(src_lang):
    s = (src_lang or "").strip().lower()
    return s.startswith("zh") or s in ("chinese", "cn", "中文")


def _co_chu_han(s):
    """Chuỗi (TÊN FILE) có chữ Hán (CJK) không → dò NHANH nguồn tiếng Trung mà không cần nghe audio.
    Video cào về luôn mang tiêu đề ngôn ngữ gốc nên tên có chữ Hán ⇒ tiếng Trung; không ⇒ nguồn khác."""
    return any("一" <= c <= "鿿" or "㐀" <= c <= "䶿" for c in (s or ""))


def _wav_16k(media):
    """Trích audio 16k mono wav (chuẩn Paraformer) ra file tạm — trả đường dẫn."""
    import tempfile
    fd, out = tempfile.mkstemp(suffix=".funasr.wav")
    os.close(fd)
    subprocess.run([_ffmpeg(), "-y", "-i", media, "-vn", "-ac", "1", "-ar", "16000",
                    "-c:a", "pcm_s16le", out], capture_output=True)
    return out


def _do_ngon_ngu_noi(video, log_fn=log):
    """Dò NGÔN NGỮ NÓI thật (sample ~25s đầu) bằng faster-whisper 'tiny' (CPU, nhẹ) → trả mã 'vi'/'zh'/'en'...
    hoặc '' nếu lỗi. Dùng để BẮT video nguồn KHÔNG phải tiếng Trung (vd video Việt lọt folder Douyin sau
    khi DỊCH TÊN khi cào → _co_chu_han sai → tưởng zh) → tránh dub đè giọng (Việt+Việt = 2 giọng)."""
    import tempfile
    wav = os.path.join(tempfile.gettempdir(), "vc_langdet_%d.wav" % os.getpid())
    try:
        ff = _ffmpeg()
        r = subprocess.run([ff, "-y", "-i", os.path.abspath(video), "-t", "25",
                            "-ar", "16000", "-ac", "1", "-vn", wav], capture_output=True)
        if r.returncode != 0 or not os.path.isfile(wav):
            return ""
        from faster_whisper import WhisperModel
        # tiny + CPU int8: nạp ~vài giây, ĐỦ chính xác cho NHẬN DIỆN NGÔN NGỮ (không cần model lớn).
        # KHÔNG dùng phu_de._get_model (cache toàn cục, tránh đè model 'medium' của ASR chính).
        m = WhisperModel("tiny", device="cpu", compute_type="int8")
        _segs, info = m.transcribe(wav, task="transcribe")   # language=None → faster-whisper tự dò
        return ((getattr(info, "language", "") or "").lower(),
                float(getattr(info, "language_probability", 0.0) or 0.0))   # kèm ĐỘ TIN để chống dò nhầm
    except Exception as e:
        log_fn("⚠ Dò ngôn ngữ bỏ qua (%s)." % str(e)[:50])
        return ("", 0.0)
    finally:
        try:
            os.remove(wav)
        except OSError:
            pass


def _merge_ocr_whisper(ocr_segs, wh_segs, min_gap=1.2):
    """Lấp KHE OCR bằng Whisper: giữ cue OCR (chữ trên màn, chuẩn vị-trí); chỗ OCR TRỐNG >min_gap mà Whisper
    CÓ tiếng (tâm cue nằm trong khe) → chèn cue Whisper. Trả list (st,en,txt) sắp theo thời gian."""
    if not wh_segs:
        return ocr_segs
    occ = sorted(ocr_segs, key=lambda x: x[0])   # (s,e,txt) — giữ TEXT để dedup mảnh ở BIÊN khe
    # CHỈ lấp khe GIỮA các cue OCR (vùng creator có hardsub mà OCR sót). KHÔNG lấp khe DẪN (trước hardsub đầu)
    # lẫn khe ĐUÔI (sau hardsub cuối): đó là intro/outro/nhạc — creator KHÔNG làm sub → Whisper hay ẢO GIÁC ở đó
    # → đẻ phụ đề Việt khi "chưa nói/chỉ có nhạc". prev khởi từ cue OCR ĐẦU (bỏ khe dẫn); không thêm khe đuôi.
    gaps, prev_end, prev_txt = [], occ[0][0], occ[0][2]
    for s, e, t in occ:
        if s - prev_end > min_gap:
            gaps.append((prev_end, s, prev_txt, t))   # + text 2 cue OCR bao khe (trước | sau) để dedup mảnh
        if e > prev_end:
            prev_end, prev_txt = e, t
    out = list(ocr_segs)
    for ws, we, wt in wh_segs:
        if not (wt or "").strip():
            continue
        mid = (ws + we) / 2.0
        for g0, g1, ptxt, ntxt in gaps:
            if g0 <= mid < g1:                 # tâm cue Whisper rơi vào khe OCR → lấp
                # DEDUP biên (chống lặp-từ '完了'⊂'完了他要动手了'): mảnh Whisper ⊂ cue OCR ĐẦU/CUỐI khe → BỎ.
                # 1-CHIỀU (chỉ bỏ khi Whisper là CON): Whisper dài hơn thì GIỮ → KHÔNG bao giờ bỏ nhầm câu thật (không sót).
                nw = _norm_zh(wt)
                if len(nw) >= 2 and ((ntxt and nw in _norm_zh(ntxt)) or (ptxt and nw in _norm_zh(ptxt))):
                    break
                a, b = max(ws, g0), min(we, g1)   # CLAMP vào đúng khe → KHÔNG đè cue OCR kề (hết "chữ đè chữ")
                if b - a >= 0.30:                 # sau cắt còn đủ dài mới giữ
                    out.append((a, b, wt))
                break
    out.sort(key=lambda x: x[0])
    return out                          # de-overlap để _gop_trung (chạy sau asr_segments) lo CHUNG cả OCR-nội-bộ


def _norm_zh(s):
    """Chuẩn-hoá câu ZH để SO SÁNH dedup: phồn→giản + bỏ khoảng trắng + bỏ dấu câu CJK/middle-dot (杰克·萨利
    vs 杰克萨利). KHÔNG đổi text gốc — chỉ dùng nội bộ _gan_giong/_dedup_lap."""
    import re as _re
    return _re.sub(r"[·、，。！？：；…·\s\"'“”‘’（）()《》〈〉「」『』\-—,.!?:;]", "", _t2s(s or "").strip())


def _gan_giong(a, b):
    """2 câu ZH GẦN như trùng: OCR đọc lại 1 dòng hardsub qua nhiều frame, lệch chút — rác đuôi ('…主导者很室'
    vs '…主导者') hoặc nhận nhầm ký tự ('这一' vs '这—'), hoặc PHỒN-vs-GIẢN. Trả True để gộp 1 (khỏi đẻ câu lặp)."""
    a, b = _norm_zh(a), _norm_zh(b)
    if not a or not b:
        return False
    if a == b:
        return True
    s, l = (a, b) if len(a) <= len(b) else (b, a)
    # ngắn là TIỀN TỐ/HẬU TỐ của dài + đuôi thừa NGẮN (rác đuôi OCR / nhận nhầm ký tự). CAP độ-thừa để KHÔNG
    # gộp nhầm 2 câu KHÁC chỉ tình cờ share đuôi/đầu ≥4 ký tự (audit TTS-H3: bỏ cap gây gộp sai).
    if len(s) >= 4 and (l.startswith(s) or l.endswith(s)) and (len(l) - len(s)) <= max(3, len(l) // 4):
        return True
    import difflib
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.80


def _gop_trung(segs, eps=0.02):
    """QUÉT cue CHỒNG THỜI GIAN (OCR đẻ 2 cue cùng giây / 2-dòng hardsub / fill đè) → GỘP thành 1 cue:
    time = [min st, max en], zh = nối các đoạn KHÁC nhau (trùng text → giữ 1). Cue gộp đi tiếp qua dịch Gemini
    → Gemini lo NỘI DUNG (1 câu mạch lạc, dedup) → hết 'chữ đè chữ' mà KHÔNG mất ý. Trả list (st,en,zh)."""
    if not segs:
        return segs
    segs = sorted(segs, key=lambda x: x[0])
    out = [list(segs[0])]
    for st, en, z in segs[1:]:
        zz = (z or "").strip()
        prev_z = (out[-1][2] or "").strip()
        overlap = st < out[-1][1] - eps
        near = bool(zz and prev_z and _gan_giong(zz, prev_z))   # gần TRÙNG (OCR đọc lại 1 dòng, lệch chút)
        if overlap or (zz and prev_z and st - out[-1][1] <= 2.0 and near):
            # GỘP vào cue trước. gần trùng → GIỮ bản DÀI hơn (KHÔNG nối → tránh câu lặp ở zh.srt/Gemini/dub);
            # chồng nhưng KHÁC nội dung (2-dòng hardsub) → nối lại như cũ.
            out[-1][1] = max(out[-1][1], en)
            if near:
                if len(zz) > len(prev_z):
                    out[-1][2] = zz
            elif overlap and zz and zz not in prev_z:
                out[-1][2] = (prev_z + " " + zz).strip()
        else:
            out.append([st, en, z])
    return [(a, b, c) for a, b, c in out]


def _dedup_lap(segs, win=3):
    """Bỏ cue OCR LẶP/TÁCH còn sót sau _gop_trung (các cue KHÔNG chồng thời gian nên _gop_trung không bắt → gây
    phụ đề TRÙNG). So sánh trên bản CHUẨN-HOÁ (_norm_zh: phồn→giản + bỏ dấu câu) vì OCR đọc 1 dòng hardsub
    qua nhiều frame ra PHỒN rồi GIẢN (傑克薩利講 vs 杰克萨利讲) → byte khác, ratio thô chỉ ~0.4 KHÔNG bắt được:
      (1) TÁCH: cue[i] == mảnh kế tiếp ghép lại (2 hoặc 3 mảnh), khớp CHẶT (==) hoặc GẦN (ratio≥0.90 cho lệch
          1 chữ kiểu OCR 步/部) → bỏ các mảnh, giữ FULL.
      (2) TIỀN/HẬU TỐ: 1 cue là đầu/đuôi DÀI (≥4 chữ, ≥60% bản dài) của 1 cue khác trong cửa sổ → bỏ cue NGẮN
          (OCR đọc thiếu/đọc lại 1 phần). (vd 64 '就是借由人类意识的接入' là đuôi của 63).
      (3) LẶP trong cửa sổ ≤win: ratio≥0.85 → bỏ cue SAU (giữ cue đầu)."""
    if not segs or len(segs) < 2:
        return segs
    import difflib as _dl

    def _r(a, b):
        return _dl.SequenceMatcher(None, a, b).ratio()

    nz = [_norm_zh(s[2]) for s in segs]                 # chuẩn-hoá MỘT lần (phồn→giản, bỏ dấu câu)
    drop = set()
    for i in range(len(segs)):                          # (1) cue TÁCH: full ≈ mảnh1+mảnh2(+mảnh3) LIỀN sau
        if i in drop:
            continue
        full = nz[i]
        if len(full) < 6:
            continue
        for npieces in (2, 3):                          # thử ghép 2 rồi 3 mảnh kế tiếp
            js = list(range(i + 1, i + 1 + npieces))
            if js[-1] >= len(segs) or any(j in drop for j in js):
                continue
            joined = "".join(nz[j] for j in js)
            if not all(nz[j] for j in js):
                continue
            if joined and (full == joined or _r(full, joined) >= 0.90):
                for j in js:
                    drop.add(j)                         # giữ FULL (cue i), bỏ các mảnh tách
                break
    # (1b) LỘ DẦN hardsub 2 dòng: OCR đọc CÙNG 1 câu qua các giai đoạn hiện chữ → mảnh-đầu / NGUYÊN-câu /
    # mảnh-cuối (FULL ở GIỮA — stage (1) chỉ bắt FULL đứng đầu, stage (2) ngưỡng 60% + exact nên mỗi nửa ~45-50%
    # + OCR nhầm ký tự (仓/舱) đều TRƯỢT). Nhận: mảnh là fuzzy prefix/suffix (ratio VÙNG đầu/đuôi ≥0.85 → sống
    # sót OCR nhầm 1 chữ) của 1 cue DÀI hơn trong cửa sổ → bỏ MẢNH, giữ FULL. Ngưỡng độ-dài: cặp đơn cần mảnh
    # ≥45% (chặt, tránh gộp nhầm); nhưng nếu FULL có CẢ mảnh-đầu LẪN mảnh-cuối 2 phía (TRIPLE = reveal chắc
    # chắn) → nới xuống 30% (bắt cả nửa lệch, vd dòng-1 dài dòng-2 ngắn).
    def _pre_ok(frag, full):
        lf = len(frag)
        return 4 <= lf < len(full) and _r(full[:lf], frag) >= 0.85
    def _suf_ok(frag, full):
        lf = len(frag)
        return 4 <= lf < len(full) and _r(full[-lf:], frag) >= 0.85
    for i in range(len(segs)):
        if i in drop:
            continue
        fi = nz[i]
        if len(fi) < 8:                                  # 'FULL' phải đủ dài (2 nửa ≥4 chữ) mới xét
            continue
        lo, hi = max(0, i - win), min(i + 1 + win, len(segs))
        pres = [j for j in range(lo, hi)
                if j != i and j not in drop and len(nz[j]) < len(fi) and _pre_ok(nz[j], fi)]
        sufs = [j for j in range(lo, hi)
                if j != i and j not in drop and len(nz[j]) < len(fi) and _suf_ok(nz[j], fi)]
        thr = 0.30 if (pres and sufs) else 0.45         # TRIPLE 2 phía → nới 30%; cặp đơn → giữ chặt 45%
        for j in set(pres + sufs):
            if len(nz[j]) >= thr * len(fi):             # mảnh đủ dài (loại trùng-đầu/đuôi ngắn tình cờ)
                drop.add(j)
    for i in range(len(segs)):                          # (2) TIỀN/HẬU TỐ dài → bỏ cue NGẮN
        if i in drop:
            continue
        ai = nz[i]
        if len(ai) < 4:
            continue
        for j in range(i + 1, min(i + 1 + win, len(segs))):
            if j in drop:
                continue
            bj = nz[j]
            if len(bj) < 4:
                continue
            s, l = (ai, bj) if len(ai) <= len(bj) else (bj, ai)
            if (l.startswith(s) or l.endswith(s)) and len(s) >= max(4, int(len(l) * 0.6)):
                drop.add(i if len(ai) <= len(bj) else j)   # bỏ cue NGẮN (mảnh thiếu), giữ cue DÀI (full)
    for i in range(len(segs)):                          # (3) LẶP trong cửa sổ → bỏ cue SAU
        if i in drop:
            continue
        ai = nz[i]
        if len(ai) < 4:
            continue
        for j in range(i + 1, min(i + 1 + win, len(segs))):
            if j in drop:
                continue
            bj = nz[j]
            if len(bj) >= 4 and (ai == bj or _r(ai, bj) >= 0.85):
                drop.add(j)
    # GIÃN cue giữ lại phủ KHE của cue bị bỏ → tránh "mất sub" thoáng: cue drop (là trùng, nội dung đã có ở cue
    # kề) → nối thời gian vào cue KỀ TRƯỚC còn giữ (sub trước ở lại tới hết slot). KHÔNG đẻ nội dung mới. Lố thì
    # _chong_de (chạy sau) cắt đuôi gọn.
    res = [list(s) for s in segs]
    last = None
    for k in range(len(res)):
        if k in drop:
            if last is not None:
                res[last][1] = max(res[last][1], res[k][1])
        else:
            last = k
    return [(res[k][0], res[k][1], res[k][2]) for k in range(len(res)) if k not in drop]


def _bo_manh_trung(segs, win=2, min_len=2, max_gap=3.0):
    """Bỏ cue là MẢNH (substring chuẩn-hoá) của 1 cue KỀ (≤win cue, cách ≤max_gap giây) → giữ cue DÀI.
    Bắt lặp TIỀN/HẬU-TỐ mà _dedup_lap (ngưỡng ≥4 ký tự & ≥60% độ dài, giữ chặt tránh dương-tính-giả) BỎ SÓT:
    '一直'⊂'一直没有找到合适好用的', '傻猴的'⊂'你就是个傻猴的', '眼望不到头'⊂'...一眼望不到头'. KHÔNG mất nội
    dung (text mảnh đã nằm TRỌN trong cue dài giữ lại). Regression corpus THẬT laptop: 5425 cue → chỉ bỏ 0.42%
    (đều mảnh thật), diệt 31→1 cặp trùng. min_len≥2 (né 1 chữ tình cờ); max_gap+win → CHỈ gộp mảnh KỀ (reveal
    OCR / Whisper vấp), KHÔNG đụng câu giống nhau ở XA (điệp-ngữ hợp lệ)."""
    if len(segs) < 2:
        return segs
    nzs = [_norm_zh(s[2]) for s in segs]
    drop = set()
    for i in range(len(segs)):
        if i in drop or len(nzs[i]) < min_len:
            continue
        for j in range(max(0, i - win), min(len(segs), i + win + 1)):
            if j == i or j in drop or len(nzs[j]) < min_len:
                continue
            if abs(segs[i][0] - segs[j][0]) > max_gap and abs(segs[i][1] - segs[j][1]) > max_gap:
                continue                                # chỉ mảnh KỀ thời gian (reveal), không phải câu lặp ở xa
            a, b = nzs[i], nzs[j]
            if len(a) < len(b) and a in b:              # i là MẢNH (ngắn hơn) ⊂ j → bỏ i, giữ j (đủ nội dung)
                drop.add(i)
                break
    res = [list(s) for s in segs]                        # giãn cue giữ lại phủ khe cue bỏ (tránh "mất sub" thoáng)
    last = None
    for k in range(len(res)):
        if k in drop:
            if last is not None:
                res[last][1] = max(res[last][1], res[k][1])
        else:
            last = k
    return [(res[k][0], res[k][1], res[k][2]) for k in range(len(res)) if k not in drop]


def _bo_lap_lien(text, min_cjk=3, min_word=3):
    """Bỏ LẶP LIỀN-KỀ GIỐNG HỆT ngay TRONG 1 cue do Whisper VẤP/ảo giác ('林总好林总好'→'林总好',
    '知道了张雪知道了张雪机车'→'知道了张雪机车'). Đây là lớp lặp _dedup_lap KHÔNG bắt (nó so giữa các cue,
    không soi trong cùng cue) → cue bị phồng chữ → engine ghép-track NÉN cho vừa khe → câu đó đọc NHANH bất
    thường (1 câu nhanh 1 câu chậm). CHỈ gộp khối LIỀN-KỀ y hệt, đơn vị ≥3 ký tự (CJK) / ≥3 từ (Latin) →
    GIỮ nguyên điệp-từ hợp lệ: reduplication (看看/想想/精神精神, đơn-vị ≤2), và lặp CÁCH QUÃNG có chữ xen
    (一边..一边 / 一杯敬自由..一杯敬孤独 / 有人..有人). Tắt: env DUB_DESTUTTER=0."""
    if not text or not text.strip():
        return text
    s = text.strip()
    latin = " " in s
    seq = s.split(" ") if latin else list(s)
    min_unit = min_word if latin else min_cjk
    changed = True
    while changed:
        changed = False
        n = len(seq)
        for L in range(n // 2, min_unit - 1, -1):    # đơn vị DÀI trước (bắt stutter dài trước khi vụn)
            i = 0
            while i + 2 * L <= len(seq):
                if seq[i:i + L] == seq[i + L:i + 2 * L]:
                    k = 2                             # đếm số khối lặp liên tiếp
                    while i + (k + 1) * L <= len(seq) and seq[i:i + L] == seq[i + k * L:i + (k + 1) * L]:
                        k += 1
                    del seq[i + L:i + k * L]          # giữ 1 khối, xoá (k-1) khối lặp
                    changed = True
                else:
                    i += 1
            if changed:
                break
    return (" " if latin else "").join(seq)


def _chong_de(segs, eps=0.02):
    """CHỐT cuối trước BURN: cue (st,en,payload) sắp theo start; cue sau đè cue trước → cắt đuôi cue trước
    (nếu còn >eps) hoặc bỏ cue sau (quá sát). Đảm bảo .vi.srt 0 cặp chồng kể cả sau chia_sub_dai ép ≥0.5s."""
    if not segs:
        return segs
    segs = sorted(segs, key=lambda x: x[0])
    out = []
    for st, en, p in segs:
        if out and st < out[-1][1] - eps:
            pst, pen, pp = out[-1]
            if st - pst > eps:
                out[-1] = (pst, st, pp)        # cắt đuôi cue trước về sát cue sau
            else:
                continue                       # 2 cue gần như cùng start → bỏ cue sau (giữ cue trước)
        out.append((st, en, p))
    return out


def asr_segments(video, model_size, log_fn, src_lang="zh", on_seg=None, on_reset=None, box_sink=None):
    eng = os.environ.get("ASR_ENGINE", "").lower()
    if not eng:   # MẶC ĐỊNH MỚI (user chốt sau khi đo thật): Whisper khi CÓ GPU (nhanh hơn + phủ ĐỦ câu hơn,
        try:      # rõ nhất ở video DÀI — 817s: Whisper 212s/615 câu vs OCR 298s/530). Máy KHÔNG GPU → OCR
            _dev, _ = phu_de._whisper_device()   # (Whisper CPU quá chậm cho video dài). Ép cứng: ASR_ENGINE=whisper|ocr.
            eng = "whisper" if _dev == "cuda" else "ocr"
        except Exception:
            eng = "ocr"

    # --- "ĐỌC TỪ SUB" (OCR) cho TIẾNG TRUNG (khi eng=ocr): đọc CHỮ phụ đề cứng bằng RapidOCR (PP-OCRv5) →
    # nguyên văn, nhanh + chuẩn hơn FunASR. Dùng chung band (dai_sub) + khoảng (ocr_timing). KHÔNG hardsub /
    # chưa cài RapidOCR / quá ít khoảng → tự lùi WHISPER bên dưới (Whisper có timestamp tốt, không cần FunASR).
    # Chọn "Giọng nói thành văn bản" → ASR_ENGINE=whisper (bỏ qua OCR).
    if eng != "whisper" and _la_tieng_trung(src_lang):
        try:
            import ocr_text
            if ocr_text.co_rapidocr():
                vabs = os.path.abspath(video)
                log_fn("👁 Đọc phụ đề bằng OCR (chữ trên video, BÁM vị-trí sub di chuyển)...")

                def _ocr_seg(i, st, en, t):
                    _seg(i, st, en, t)
                    if on_seg:
                        on_seg(i, st, en, t)
                # WHISPER-BÙ SONG SONG (GPU): nghe AUDIO trong lúc OCR (CPU) đọc hardsub → LẤP câu OCR sót.
                # GPU≠CPU không tranh nhau (gần như miễn phí thời gian). quiet=True (chỉ thu, không hiện rối UI).
                # MẶC ĐỊNH BẬT LẠI (2026-07-02): OCR sót ~½ sub ở video khó (anime/sub nhanh/nền rối/sub đổi vị-trí)
                # → SÓT câu → dub "im" hoặc nhồi text vào cue ngắn = đọc nhanh. Whisper bù câu OCR sót (verified
                # video34: 9→20 cue, bù 肯定是圈套/你很幸运...). LẶP-TỪ đã chặn 2 lớp: _merge_ocr_whisper dedup mảnh
                # ở BIÊN khe ('完了'⊂'完了他要动手了') + _bo_lap_lien (lặp TRONG cue). Tắt: ASR_OCR_WHISPER_FILL=0.
                _wh = {"segs": None}
                _wht = None
                if os.environ.get("ASR_OCR_WHISPER_FILL", "1") != "0":
                    import threading
                    def _wh_run():
                        try:
                            _m = phu_de._get_model(model_size, log_fn)
                            _wh["segs"] = _transcribe_thu(_m, vabs, src_lang, quiet=True)
                            if phu_de._dang_gpu():
                                phu_de._bao_gpu_ok()
                        except Exception:
                            _wh["segs"] = []   # Whisper lỗi → chỉ dùng OCR (không làm hỏng render)
                    _wht = threading.Thread(target=_wh_run, daemon=True)
                    _wht.start()
                # HỢP NHẤT: 1 lần dò → text + HỘP vị-trí mỗi câu (blur động + phụ đề bám). boxes ra box_sink.
                segs, boxes = ocr_text.ocr_dong(vabs, log=log_fn, on_seg=_ocr_seg)
                # CHECK-ĐẦU/RESCUE bằng OCR-MEDIUM: small (mặc định) dò yếu ở video khó (chữ trắng nền sáng/mờ) →
                # đọc QUÁ ÍT → SẮP rớt xuống Whisper (nguồn 'Audio corrupted' khi intro nhạc). Thử lại MEDIUM (chuẩn
                # nhất) TRƯỚC: medium đọc được → dùng OCR (khỏi Whisper); medium cũng ít → mới là video KHÔNG hardsub
                # thật → Whisper (đã có lọc ảo giác). Chỉ chạy khi small<ngưỡng → HIẾM nên chi phí medium chấp nhận.
                _min_cue = int(os.environ.get("OCR_MIN_CUE", "3") or 3)
                _cur_model = (os.environ.get("OCR_MODEL", "v6-small") or "v6-small").lower()
                if (not segs or len(segs) < _min_cue) and _cur_model not in ("v6-medium", "v5-mobile") \
                        and os.environ.get("OCR_RESCUE_MEDIUM", "1") != "0":
                    _old_m = os.environ.get("OCR_MODEL")
                    try:
                        os.environ["OCR_MODEL"] = "v6-medium"
                        ocr_text._ENGINE = None       # ép dựng lại engine = medium
                        log_fn("🔎 OCR-small đọc ít (%d câu) → thử lại OCR-medium (chuẩn hơn) trước khi dùng Whisper..."
                               % (len(segs) if segs else 0))
                        _s2, _b2 = ocr_text.ocr_dong(vabs, log=log_fn, on_seg=None)   # None: khỏi stream trùng UI
                        if _s2 and len(_s2) >= _min_cue:
                            segs, boxes = _s2, _b2
                            log_fn("✔ OCR-medium đọc được %d câu → dùng OCR (bỏ qua Whisper)." % len(segs))
                    except Exception as _e:
                        log_fn("ℹ OCR-medium rescue bỏ qua (%s)." % str(_e)[:60])
                    finally:
                        if _old_m is None:
                            os.environ.pop("OCR_MODEL", None)
                        else:
                            os.environ["OCR_MODEL"] = _old_m
                        ocr_text._ENGINE = None        # trả engine về small cho video sau
                if _wht is not None:
                    _wht.join(timeout=float(os.environ.get("ASR_WHISPER_FILL_TIMEOUT", "900") or 900))
                _wsegs = _wh.get("segs") or []
                if segs and len(segs) >= 3:
                    _n0 = len(segs)
                    if _wsegs:
                        segs = _merge_ocr_whisper(segs, _wsegs, min_gap=1.0)   # chỉ khe ≥1s mới Whisper lấp
                    _nfill = len(segs) - _n0
                    log_fn("👁 OCR đọc %d câu%s (kèm vị-trí HỘP cho blur/phụ đề bám sub di chuyển)."
                           % (_n0, (" + Whisper bù %d câu chỗ trống ≥1s" % _nfill) if _nfill else ""))
                    if box_sink is not None:
                        box_sink.extend(boxes)
                    return segs
                # OCR quá ít chữ cứng → DÙNG LUÔN Whisper đã nghe song song (khỏi nghe lại bên dưới)
                if _wsegs and len(_wsegs) >= 3:
                    log_fn("ℹ OCR ít chữ cứng (%d câu) → dùng Whisper (đã nghe song song): %d câu." % (len(segs), len(_wsegs)))
                    if on_reset and segs:
                        on_reset()
                    return _wsegs
                log_fn("ℹ OCR ít/không thấy chữ cứng (%d câu) → 'Giọng nói thành văn bản' (ASR)." % len(segs))
                if on_reset and segs:        # đã stream vài câu rồi mới lùi → reset trạng thái gộp dịch
                    on_reset()
            else:
                log_fn("⚠ Chưa cài RapidOCR → 'Giọng nói thành văn bản' (ASR).")
        except Exception as e:
            log_fn("⚠ OCR lỗi (%s) → ASR thường." % str(e)[:90])
            if on_reset:
                on_reset()

    # --- Whisper (mặc định cho ngôn ngữ khác, hoặc khi OCR không dùng được) ---
    model = phu_de._get_model(model_size, log_fn)
    tren_gpu = phu_de._dang_gpu()
    log("🎧 Đang nghe & nhận dạng giọng nói (%s)..." % src_lang)
    try:
        segs = _transcribe_thu(model, video, src_lang, on_seg=on_seg)
        if tren_gpu:
            phu_de._bao_gpu_ok()   # GPU chạy trót lọt → reset đếm lỗi (giữ GPU cho lượt sau)
        return segs
    except Exception as e:
        # GPU lỗi/treo GIỮA CHỪNG (OOM card 4GB, cuDNN…). try ở _get_model chỉ bắt lúc NẠP,
        # không bắt được lỗi trong generator → lùi CPU chạy lại cho XONG (chậm hơn nhưng không treo).
        if tren_gpu:
            log_fn("⚠ GPU lỗi khi nhận dạng (%s) → nạp lại CPU chạy tiếp (chậm hơn)..." % str(e)[:80])
            phu_de._bao_gpu_loi(log_fn)   # đếm lỗi; chưa quá ngưỡng thì lượt SAU vẫn thử lại GPU
            if on_reset:
                on_reset()   # ASR chạy LẠI từ đầu trên CPU → reset trạng thái gộp câu của luồng dịch
            cpu_model = phu_de._ep_cpu(model_size, log_fn)
            return _transcribe_thu(cpu_model, video, src_lang, on_seg=on_seg)
        # Đã ở CPU (không có đường lùi GPU) mà vẫn lỗi → KHÔNG raise cứng (làm chết cả render);
        # log + trả [] để caller (asr_segments→chay) lùi nhánh chỉ-encode-hình thay vì văng traceback.
        log_fn("⚠ Nhận dạng lời thoại lỗi trên CPU (%s) → bỏ qua ASR." % str(e)[:80])
        return []


# Dấu kết câu (Trung + Latin) — để gộp các đoạn ASR rời thành câu đầy đủ
_KET_CAU = ("。", "！", "？", ".", "!", "?", "…", "；", ";")


def gop_cau(segs, max_dur=12.0, max_gap=1.0):
    """Gộp các đoạn ASR liên tiếp thành câu đầy đủ hơn → dịch & đọc tự nhiên hơn.
    Gộp khi đoạn trước CHƯA kết thúc bằng dấu kết câu, khoảng lặng nhỏ, tổng chưa quá dài."""
    if not segs:
        return segs
    out = []
    cst, cen, ctxt = segs[0]
    for st, en, t in segs[1:]:
        chua_het = not ctxt.rstrip().endswith(_KET_CAU)
        if chua_het and (st - cen) <= max_gap and (en - cst) <= max_dur:
            cen = en
            ctxt = (ctxt.rstrip() + " " + t.lstrip()).strip()
        else:
            out.append((cst, cen, ctxt))
            cst, cen, ctxt = st, en, t
    out.append((cst, cen, ctxt))
    return out


def _luong_dich_ai(zh_list):
    """Dịch 1 lô câu zh -> list vi cùng độ dài (im lặng log, dùng trong luồng nền). Câu AI bỏ -> ''."""
    import ai_dich
    out = ai_dich.dich_phu_de([(0.0, 0.0, z) for z in zh_list], log_fn=lambda m: None)
    return [v for (_s, _e, (_z, v)) in out]


class _DichStream:
    """NGHE + DỊCH SONG SONG, DỊCH 1:1 TỪNG ĐOẠN (KHÔNG gộp câu) → cột Gốc và Dịch khớp đúng từng dòng
    (như ChatGPT), giữ mốc thời gian gốc. Nhận (i, st, en, zh) mỗi đoạn ASR → gom LÔ → NHIỀU luồng dịch
    AI song song; fill cột Dịch real-time đúng chỉ số đoạn i. Trả dict zh->vi cho caller khớp lại.
    AN TOÀN: caller dựng segs_vi từ segs + tra zh->vi + bù Google nếu sót; ASR lùi CPU (reset) vô hại."""
    def __init__(self, log_fn, workers=2, lo=15, dung_ai=True):
        self.log, self.lo, self.dung_ai = log_fn, lo, dung_ai
        self.ex = ThreadPoolExecutor(max_workers=max(1, workers))
        self.lock = threading.Lock()
        self.buf = []         # [(i, zh)] đoạn chờ gửi 1 lô
        self.kq = {}          # zh -> vi
        self.futs = []

    def them_seg(self, i, st, en, zh):
        with self.lock:
            self.buf.append((i, zh))
            if len(self.buf) >= self.lo:
                self.futs.append(self.ex.submit(self._dich, list(self.buf))); self.buf = []

    def reset(self):   # ASR lùi CPU chạy lại từ đầu -> bỏ buffer chờ (kq giữ, khớp theo zh nên vô hại)
        with self.lock:
            self.buf = []

    def _dich(self, items):    # luồng nền: dịch 1 lô [(i, zh)] 1:1 + fill SEGVI đúng chỉ số đoạn
        zhs = [z for _, z in items]
        if self.dung_ai:
            try:
                vis = _luong_dich_ai(zhs)
            except Exception:
                vis = ["" for _ in zhs]
        else:
            vis = [dich_dong(z) for z in zhs]   # chế độ Google: dịch từng câu NGAY (ngoài lock)
        with self.lock:
            for (i, z), v in zip(items, vis):
                v = v if (v or "").strip() else dich_dong(z)   # đoạn AI bỏ/Google sót -> bù
                self.kq[z] = v
                _segvi(i, v)                                   # điền cột Dịch ngay (đúng dòng Gốc i)

    def xong(self):    # gọi SAU khi ASR xong: flush lô cuối + chờ mọi luồng -> dict zh->vi
        with self.lock:
            if self.buf:
                self.futs.append(self.ex.submit(self._dich, list(self.buf))); self.buf = []
            futs = list(self.futs)
        for f in futs:
            try:
                f.result()
            except Exception as e:
                self.log("LOG:⚠ luồng dịch lỗi: %s" % str(e)[:60])
        self.ex.shutdown(wait=True)
        with self.lock:
            return dict(self.kq)

    def huy(self):
        self.ex.shutdown(wait=False)


def _chia_text(vi, max_ky_tu):
    """Chia 1 đoạn dài để dễ đọc: cắt SAU dấu câu (. ! ? …) VÀ dấu phẩy/cụm (, ; :) -> mỗi mệnh đề
    1 mảnh; gom mệnh đề quá ngắn cho đỡ vụn; mệnh đề vẫn quá dài (hiếm) mới cắt theo từ."""
    import re
    parts = [p.strip() for p in re.split(r"(?<=[.!?…,;:])\s+", vi) if p.strip()]
    manh, cur = [], ""
    for p in parts:
        if not cur:
            cur = p
        elif len(cur) + 1 + len(p) <= max_ky_tu:     # gom mệnh đề ngắn liền kề cho đỡ vụn
            cur += " " + p
        else:
            manh.append(cur); cur = p
    if cur:
        manh.append(cur)
    gioihan = int(max_ky_tu * 2)                      # mệnh đề <= ngưỡng này giữ nguyên (tối đa ~2 dòng)
    kq = []
    for m in manh:
        while len(m) > gioihan:                       # mệnh đề vẫn quá dài -> cắt theo từ
            cut = m.rfind(" ", 0, gioihan)
            cut = cut if cut > 0 else gioihan
            kq.append(m[:cut].strip()); m = m[cut:].strip()
        if m:
            kq.append(m)
    return kq


def _bo_vi_trung_lien_tiep(segs_vi, log_fn=log):
    """Gộp cue có BẢN DỊCH VIỆT giống HỆT nhau LIÊN TIẾP. Sinh khi OCR đọc CÙNG 1 dòng hardsub qua nhiều khung
    ra ZH KHÁC CHỮ (lỗi OCR tên riêng: 周浦齐 vs 周潇齐; 自已 vs 自己) → dedup ZH theo ratio KHÔNG bắt (khác 2-3
    chữ → ratio <0.85; zhconv chỉ lo phồn↔giản) → Gemini dịch ra VI Y HỆT → phụ đề + lồng tiếng LẶP. Dedup tầng
    VI bắt SẠCH mọi biến thể OCR. Gộp = giữ cue ĐẦU, kéo dài hết khe cue trùng (khỏi hụt thời lượng/desync dub).
    segs_vi = [(st, en, (zh, vi))]."""
    if not segs_vi or len(segs_vi) < 2:
        return segs_vi
    out = [list(segs_vi[0])]
    n = 0
    for st, en, zv in segs_vi[1:]:
        vi = (zv[1] or "").strip()
        if vi and vi == ((out[-1][2][1] or "").strip()):
            out[-1][1] = en          # kéo dài cue trước phủ hết khe cue trùng
            n += 1
        else:
            out.append([st, en, zv])
    if n:
        log_fn("🧹 Gộp %d cue dịch TRÙNG liên tiếp (OCR đọc lại 1 dòng khác chữ → VI giống hệt) → %d câu." % (n, len(out)))
    return [tuple(x) for x in out]


def chia_sub_dai(segs_vi, max_ky_tu=42):
    """KHÔNG chia câu dài nữa (theo yêu cầu) — Gemini length-control ([≤N] ký tự/dòng) giữ câu NGẮN + libass
    TỰ xuống dòng khi burn nếu còn dài. Chỉ ÉP mỗi cue ≥0.5s: OCR đôi khi ra segment 0-giây (st==en, vd
    [13.7-13.7]) → cue 0-giây → ffmpeg subtitles= BỎ QUA → MẤT phụ đề (dù dub vẫn đọc). Bỏ chia-theo-ký-tự vì
    CHÍNH NÓ chia thời gian sinh ra cue 0-giây = bug mất sub. (max_ky_tu giữ cho tương thích chữ ký, không dùng.)"""
    MIN = 0.5
    out = []
    for st, en, (zh, vi) in segs_vi:
        if en - st < MIN:
            en = st + MIN
        out.append((st, en, (zh, (vi or "").strip())))
    return out


# ---------------- FFmpeg: che chữ + burn phụ đề ----------------
_font_size = int(os.environ.get("SUB_FONT_SIZE", "20"))
_STYLE_SUB = f"FontName=Arial,FontSize={_font_size},Bold=1,Italic=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H00000000,Outline=3,Shadow=1,MarginV=18"


def _enc_video(ff):
    """Tham số encoder video: NVENC (GPU) nếu có, không thì libx264 (CPU).
    NVENC preset chỉnh qua env NVENC_PRESET: p1=nhanh nhất … p7=đẹp/chậm nhất; mặc định p5 (cân bằng).
    Video mạng xã hội thường p4/p3 ổn → encode nhanh hơn ~15-25%, chất lượng giảm không đáng kể.
    (Lưu ý: nút thắt encode video DÀI thường là FILTER CPU — libass sub + blur động — chứ không phải NVENC;
    đổi preset chỉ lợi khi NVENC là phần chậm.)"""
    if xu_ly_video.co_nvenc(ff):
        preset = (os.environ.get("NVENC_PRESET", "") or "p5").strip()
        # cq20 CŨ → ~10.8Mbps (5× nguồn Douyin ~2Mbps = phình vô ích, nguồn 2Mbps không có chất lượng để giữ).
        # cq28 → ~4.3Mbps (2.2× nguồn) đủ đẹp dư cho reup, file -60%. Chỉnh: NVENC_CQ (thấp=đẹp/to, cao=nhỏ).
        cq = (os.environ.get("NVENC_CQ", "") or "28").strip()
        return ["-c:v", "h264_nvenc", "-preset", preset, "-rc", "vbr", "-cq", cq, "-b:v", "0"]
    crf = (os.environ.get("VC_X264_CRF", "") or "23").strip()   # crf20→23: cùng mức "đẹp web", file ~½
    return ["-c:v", "libx264", "-crf", crf, "-preset", "veryfast"]


def _chia_nhip(cues, max_ky_tu=58, min_doc=0.45, max_doc=5.0):
    """Phase 5 (Timestamp Splitter) + Phase 6 (Optimizer) — CODE thuần, KHÔNG dùng AI:
    cues=[(sa,sb,text)] giây (đã dịch) → [(sa,sb,text)] NHỊP đã chia thời gian + tối ưu thời lượng.
    - Cắt cue SAU dấu , . ! ? ; : → nhịp đọc; nhịp > max_ky_tu ký tự (không dấu) → cắt tiếp theo TỪ.
    - Chia thời gian cue cho nhịp theo SỐ KÝ TỰ (tốc độ đọc). Nhịp hiển thị > max_doc giây → cắt tiếp theo từ.
    - Nhịp < min_doc giây → GỘP vào nhịp kế (tránh chớp nhoáng khó đọc). Env: CHE_NHIP_KYTU / CHE_NHIP_MIN."""
    import re
    try:
        max_ky_tu = int(os.environ.get("CHE_NHIP_KYTU", "") or max_ky_tu)
    except ValueError:
        pass
    try:
        min_doc = float(os.environ.get("CHE_NHIP_MIN", "") or min_doc)
    except ValueError:
        pass

    def _cat_tu(p, maxk):                        # cắt chuỗi dài (không dấu) → mảnh ~maxk ký tự, cắt ở khoảng trắng (KHÔNG vỡ từ)
        out, cur = [], ""
        for w in p.split():
            if cur and len(cur) + 1 + len(w) > maxk:
                out.append(cur); cur = w
            else:
                cur = (cur + " " + w) if cur else w
        if cur:
            out.append(cur)
        return out or [p]

    res = []
    for (a, b, text) in cues:
        flat = " ".join(str(text).replace("\\N", " ").split())
        if not flat:
            continue
        parts = [p.strip() for p in re.split(r"(?<=[,，.。!！?？;；:：])\s+", flat) if p.strip()] or [flat]
        nhip = []
        for p in parts:
            nhip.extend([p] if len(p) <= max_ky_tu else _cat_tu(p, max_ky_tu))
        dur, tong, t, seg = max(0.01, b - a), sum(len(x) for x in nhip) or 1, a, []
        for i, x in enumerate(nhip):
            en = b if i == len(nhip) - 1 else min(b, t + dur * len(x) / tong)
            seg.append([t, en, x]); t = en
        # Optimizer A: nhịp hiển thị quá DÀI (> max_doc giây) → cắt tiếp theo từ, chia lại thời gian
        j = 0
        while j < len(seg):
            sa, sb, tx = seg[j]
            n = int((sb - sa) / max_doc) + 1
            if n > 1 and len(tx.split()) > 1:
                sub = _cat_tu(tx, max(8, -(-len(tx) // n)))
                if len(sub) > 1:
                    tt, tg, rep = sa, sum(len(z) for z in sub) or 1, []
                    for k, z in enumerate(sub):
                        e2 = sb if k == len(sub) - 1 else min(sb, tt + (sb - sa) * len(z) / tg)
                        rep.append([tt, e2, z]); tt = e2
                    seg[j:j + 1] = rep
                    j += len(rep); continue
            j += 1
        # Optimizer B: nhịp quá NGẮN (< min_doc giây) → gộp vào nhịp kế (hoặc trước nếu là nhịp cuối)
        k = 0
        while len(seg) > 1 and k < len(seg):
            if seg[k][1] - seg[k][0] < min_doc:
                if k + 1 < len(seg):
                    seg[k + 1][0] = seg[k][0]
                    seg[k + 1][2] = (seg[k][2] + " " + seg[k + 1][2]).strip()
                else:
                    seg[k - 1][1] = seg[k][1]
                    seg[k - 1][2] = (seg[k - 1][2] + " " + seg[k][2]).strip()
                del seg[k]
                continue
            k += 1
        res.extend((s[0], s[1], s[2]) for s in seg)
    return res


def _srt_to_ass_pos(srt_path, ass_path, W, H, segs, fz_base=13, ol_base=2.4, phude_style="default", no_box=False):
    """Sinh ASS đặt phụ đề Việt ĐÚNG vị trí (\\pos + \\an5) → ĐÈ LÊN dải blur, KHÔNG hard-code MarginV (đo thật
    force_style MarginV libass áp KHÔNG đáng tin: 72≡144), 2 DÒNG tự căn giữa quanh tâm (không vỡ). `segs` =
    list (t_on,t_off,y0,y1,x0,x1): mỗi cue → ĐOẠN chứa mốc-giữa-cue (sub DI CHUYỂN thì cue bám đúng đoạn) →
    tâm y đoạn đó; không khớp → đoạn gần nhất. 1 đoạn = bám tĩnh. PlayRes=video thật → \\pos pixel chuẩn;
    font scale H/288 cho cỡ BẰNG bản force_style cũ (FontSize=16 ở PlayRes mặc định 288). Trả số cue."""
    import re
    try:
        fz_base = float(os.environ.get("CHE_SUB_FZ", "") or fz_base)   # cỡ chữ phụ đề (mặc định nhỏ gọn)
    except ValueError:
        pass
    s = min(W, H) / 288.0
    fz = max(8, round(fz_base * s))
    ol = max(1, round(ol_base * s))
    sh = max(1, round(1.0 * s))       # bóng đổ (drop shadow) — bít nét, che chữ Trung sau tốt hơn + nhìn viral
    cx = round(W / 2.0)

    p_col = "&H00FFFFFF"
    o_col = "&H00000000"
    b_col = "&H00000000"
    b_style = 1
    sh_val = sh
    
    if phude_style == "black_on_white":
        p_col = "&H00000000"
        o_col = "&H00FFFFFF"
        b_col = "&H00FFFFFF"
        b_style = 1 if no_box else 3
        sh_val = 0
    elif phude_style == "black_on_yellow":
        p_col = "&H00000000"
        o_col = "&H0000FFFF"
        b_col = "&H0000FFFF"
        b_style = 1 if no_box else 3
        sh_val = 0
    elif phude_style == "white_on_yellow_black":
        p_col = "&H00FFFFFF"
        o_col = "&H00000000"
        b_col = "&H0000FFFF"
        b_style = 1 if no_box else 3
        sh_val = 0
    elif phude_style == "white_on_black":
        p_col = "&H00FFFFFF"
        o_col = "&H00000000"
        b_col = "&H00000000"
        b_style = 1 if no_box else 3
        sh_val = 0

    # ===== AUTO-FIT cỡ chữ theo BỀ NGANG (fix phụ đề VIDEO DỌC tràn dải) =====
    # Bug: video dọc bề ngang hẹp mà font scale theo chiều CAO (H/288) → font to → câu dài wrap 4+ dòng → tràn
    # dải blur (2 dòng cuối lòi xuống nền sáng, mờ). Fix: ĐO chữ Việt (metric Arial Bold, khớp libass) rồi TỰ
    # thu cỡ để câu vừa ≤ N dòng trong bề ngang; tự XUỐNG DÒNG cân + KẸP vị trí để khối luôn trong khung.
    try:
        _maxln = max(1, int(os.environ.get("CHE_SUB_MAXLINES") or 2))
    except ValueError:
        _maxln = 2
    _usable = W * 0.90                              # chừa lề 2 bên
    _fzmin = max(10, int(round(fz * 0.5)))          # sàn cỡ chữ (không thu quá nhỏ)
    try:
        from PIL import ImageFont
        _fp = next((c for c in (r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\Arial.ttf")
                    if os.path.isfile(c)), None)
        _fcache = {}
        def _measure(txt, size):
            f = _fcache.get(size)
            if f is None and _fp:
                f = ImageFont.truetype(_fp, size); _fcache[size] = f
            return f.getlength(txt) if f else len(txt) * size * 0.58
    except Exception:
        def _measure(txt, size):
            return len(txt) * size * 0.58           # thiếu PIL → ước lượng hệ số

    def _wrap(txt, size):                           # word-wrap greedy theo bề rộng đo được
        words = txt.replace("\\N", " ").split()
        if not words:
            return [txt]
        lines, cur = [], words[0]
        for w in words[1:]:
            if _measure(cur + " " + w, size) <= _usable:
                cur += " " + w
            else:
                lines.append(cur); cur = w
        lines.append(cur)
        return lines

    def _fit(txt):                                  # thu cỡ đến khi ≤ _maxln dòng (hoặc chạm sàn)
        fzc = fz
        lines = _wrap(txt, fzc)
        while len(lines) > _maxln and fzc > _fzmin:
            fzc = max(_fzmin, int(round(fzc * 0.92)))
            lines = _wrap(txt, fzc)
        return fzc, lines

    def _sec(ts):
        ts = ts.strip().replace(",", ".")
        hh, mm, ss = ts.split(":")
        return int(hh) * 3600 + int(mm) * 60 + float(ss)

    def _fmt_sec(s):                         # giây -> 0:00:01.50 (ASS)
        return "%d:%02d:%05.2f" % (int(s // 3600), int((s % 3600) // 60), s % 60)

    def _cy(tmid):                           # tâm y(%) của đoạn chứa tmid; không có → đoạn gần nhất
        best, bd = None, 1e9
        for sg in segs:
            if sg[0] <= tmid <= sg[1]:
                return (sg[2] + sg[3]) / 2.0
            d = min(abs(tmid - sg[0]), abs(tmid - sg[1]))
            if d < bd:
                bd, best = d, sg
        return (best[2] + best[3]) / 2.0 if best else 0.85

    try:
        raw = open(srt_path, encoding="utf-8", errors="replace").read()
    except OSError:
        return 0
    cues = []
    for blk in re.split(r"\n\s*\n", raw.strip()):
        ls = [x for x in blk.splitlines() if x.strip()]
        ti = next((i for i, l in enumerate(ls) if "-->" in l), -1)
        if ti < 0:
            continue
        ab = ls[ti].split("-->")
        if len(ab) < 2:
            continue
        txt = "\\N".join(ls[ti + 1:]).strip()
        if txt:
            cues.append((ab[0], ab[1], txt))
    if not cues:
        return 0
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write("[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n" % (W, H))
        f.write("[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, "
                "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
                "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n")
        # Bold=1 + Italic=1 + Shadow (bóng): chữ Việt ĐẬM, nét dày, có bóng → BÍT kín, che chữ Trung sau + style "viral".
        f.write("Style: Default,Arial,%d,%s,%s,%s,1,1,0,0,100,100,0,0,%d,%d,%d,5,10,10,10,1\n\n" % (fz, p_col, o_col, b_col, b_style, ol, sh_val))
        f.write("[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
        # KHÔNG cắt dòng (theo yêu cầu user): mỗi cue = 1 Dialogue NGUYÊN CÂU (giữ đúng nhịp gốc OCR [t_on,t_off]),
        # chữ đã nhỏ nên fit; libass tự xuống dòng nếu quá dài. Bật lại cắt-nhịp = env CHE_CAT_DONG=1.
        if os.environ.get("CHE_CAT_DONG", "0") == "1":
            _cues_pos = _chia_nhip([(_sec(a), _sec(b), txt) for a, b, txt in cues])
        else:
            _cues_pos = [(_sec(a), _sec(b), txt) for a, b, txt in cues]
        max_h_norm = 0.0
        for pa, pb, ptxt in _cues_pos:
            cy = _cy((pa + pb) / 2.0) * H
            fzc, lines = _fit(ptxt)                          # thu cỡ + xuống dòng để câu dài KHÔNG tràn (video dọc)
            wrapped = "\\N".join(lines)
            block_h = len(lines) * fzc * 1.28                # chiều cao khối chữ (ước lượng line-height)
            max_h_norm = max(max_h_norm, block_h / H)
            m = H * 0.03                                     # lề an toàn trên/dưới
            cyc = min(cy, H - m - block_h / 2.0)             # KẸP: khối không lòi khỏi ĐÁY
            cyc = max(cyc, m + block_h / 2.0)                #      cũng không lòi khỏi ĐỈNH
            tag = ("{\\fs%d\\pos(%d,%d)}" % (fzc, cx, round(cyc))) if fzc != fz \
                else ("{\\pos(%d,%d)}" % (cx, round(cyc)))   # cỡ chuẩn → khỏi ghi \fs (giữ hành vi cũ khi vừa)
            f.write("Dialogue: 0,%s,%s,Default,,0,0,0,,%s%s\n" % (_fmt_sec(pa), _fmt_sec(pb), tag, wrapped))
    return len(cues), max_h_norm


def _canh_sub_theo_dub(vi_srt, dub_onsets, time_warp, out_srt, log_fn=log):
    """CĂN phụ đề Việt khớp GIỌNG lồng tiếng (chống desync).

    Câu Việt thường DÀI hơn khe → trong _ghep_track_khop con trỏ `cursor` TRÔI dần sau mốc gốc (nén chạm cap
    vẫn tràn) → dub đọc câu i ở vị-trí THỰC `onset_out` ≠ mốc gốc. Nhưng phụ đề burn theo mốc GỐC (bake-then-warp)
    → sub xuất hiện ≠ lúc giọng đọc → user thấy "phụ đề lúc sớm lúc muộn". Đo thật: lệch tích luỹ ~0.5–0.9s
    (max ~2.2s) khi Video Assist bật.

    FIX: dời timestamp mỗi cue vi_srt sao cho — SAU khi burn_phude warp video (setpts piecewise theo time_warp) —
    cue xuất hiện ĐÚNG lúc dub đọc câu chứa nó.
      • dub_onsets = [(st_orig_câu, onset_out, end_out)] (output timeline) do _ghep_track_khop xuất.
      • Cue ở mốc gốc t → câu dub i (st_orig gần nhất). out_muốn = onset_out_i + (t - st_orig_i) (kẹp trong câu).
      • burn warp cue: out_thấy = warp_fwd(moc_goc_cue). Cần out_thấy = out_muốn → moc_goc_cue_mới = warp_inv(out_muốn).
      • time_warp=None (Video Assist TẮT): warp = identity → moc_goc_cue_mới = out_muốn = onset dub trực tiếp.
    Bất kỳ lỗi → trả vi_srt GỐC (fallback an toàn, hành vi cũ). Trả đường dẫn srt để burn (out_srt hoặc vi_srt)."""
    import re
    if not (dub_onsets and vi_srt and os.path.isfile(vi_srt)):
        return vi_srt
    try:
        # --- warp forward/inverse từ time_warp (list orig (o0,o1,f)); None = identity ---
        segs = [(o0, o1, float(f) or 1.0) for (o0, o1, f) in (time_warp or []) if o1 - o0 > 1e-6]
        outacc, _t = [], 0.0
        for o0, o1, f in segs:
            outacc.append((o0, o1, f, _t)); _t += (o1 - o0) / f

        def warp_fwd(torig):
            if not outacc:
                return torig
            for o0, o1, f, ot in outacc:
                if torig <= o1 + 1e-9:
                    return ot + max(0.0, torig - o0) / f
            o0, o1, f, ot = outacc[-1]; return ot + (o1 - o0) / f

        def warp_inv(tout):
            if not outacc:
                return tout
            for o0, o1, f, ot in outacc:
                seglen = (o1 - o0) / f
                if tout <= ot + seglen + 1e-9:
                    return o0 + max(0.0, tout - ot) * f
            return outacc[-1][1]

        onsets = sorted(dub_onsets, key=lambda x: x[0])   # theo st_orig tăng dần
        st_origs = [o[0] for o in onsets]
        import bisect

        def cau_cho(t):                                   # câu dub có st_orig gần t nhất
            j = bisect.bisect_left(st_origs, t)
            cands = [k for k in (j - 1, j) if 0 <= k < len(onsets)]
            return min(cands, key=lambda k: abs(onsets[k][0] - t)) if cands else 0

        def _sec(ts):
            ts = ts.strip().replace(",", "."); hh, mm, ss = ts.split(":")
            return int(hh) * 3600 + int(mm) * 60 + float(ss)

        def _ts(s):
            s = max(0.0, s); h = int(s // 3600); m = int((s % 3600) // 60); sec = s - h * 3600 - m * 60
            ms = int(round((sec - int(sec)) * 1000))
            if ms >= 1000:                       # làm tròn lên giây
                sec += 1; ms = 0
            return "%02d:%02d:%02d,%03d" % (h, m, int(sec), ms)

        raw = open(vi_srt, encoding="utf-8", errors="replace").read()
        cues = []
        for blk in re.split(r"\n\s*\n", raw.strip()):
            ls = [x for x in blk.splitlines() if x.strip()]
            ti = next((i for i, l in enumerate(ls) if "-->" in l), -1)
            if ti < 0:
                continue
            ab = ls[ti].split("-->")
            if len(ab) < 2:
                continue
            t0, t1 = _sec(ab[0]), _sec(ab[1])
            txt = ls[ti + 1:]
            k = cau_cho(t0)
            st_o, on_o, en_o = onsets[k]
            dur_cue = max(0.1, t1 - t0)
            # output mong muốn: giữ offset của cue trong câu (cue có thể là 1 mảnh sau chia_sub_dai), kẹp trong [on_o, en_o]
            want0 = on_o + max(0.0, t0 - st_o)
            want0 = min(want0, max(on_o, en_o - 0.1))
            want1 = want0 + dur_cue
            # về mốc GỐC để burn warp ra đúng output (identity khi warp tắt)
            g0, g1 = warp_inv(want0), warp_inv(want1)
            if g1 <= g0:
                g1 = g0 + 0.1
            cues.append([g0, g1, "\n".join(txt)])
        if not cues:
            return vi_srt
        # ÉP ĐƠN ĐIỆU + KHÔNG CHỒNG: nhiều cue/câu (chia_sub_dai) + clamp có thể làm cue lệch thứ tự / đè nhau
        # → libass hiển thị giật. Mốc gốc tăng dần (warp đơn điệu nên sau warp vẫn không chồng). Cắt cue trước
        # tại start cue sau (giữ tối thiểu 0.1s); cue start lùi về sau end cue trước.
        cues.sort(key=lambda c: c[0])
        for j in range(len(cues)):
            if j > 0 and cues[j][0] < cues[j - 1][1]:
                cues[j][0] = cues[j - 1][1]
            if cues[j][1] <= cues[j][0]:
                cues[j][1] = cues[j][0] + 0.1
        out_blocks = ["%d\n%s --> %s\n%s" % (i, _ts(g0), _ts(g1), tx)
                      for i, (g0, g1, tx) in enumerate(cues, 1)]
        with open(out_srt, "w", encoding="utf-8") as f:
            f.write("\n\n".join(out_blocks) + "\n")
        log_fn("🎯 Đã căn phụ đề Việt khớp giọng lồng tiếng (%d cue)." % len(out_blocks))
        return out_srt
    except Exception as e:
        log_fn("⚠ Căn phụ đề theo giọng lỗi (%s) → giữ phụ đề gốc." % str(e)[:60])
        return vi_srt


def _burn_run(cmd, base_dir, log_fn, **meta):
    """Chạy ffmpeg ghép CUỐI + ĐO wall-time (stage này trước giờ profile BỎ SÓT) → ghi _render_profile.jsonl.
    VC_FFSPLIT=1: chạy THÊM 1 lần '-f null -' (chỉ decode+filter, bỏ encode) → TÁCH filter vs encode (đo 1
    lần để biết nút thắt nằm ở libass/blur hay ở encoder; chậm gấp ~2 nên chỉ bật khi đo)."""
    import time as _t, json as _j
    _t0 = _t.time()
    kq = subprocess.run(cmd, cwd=base_dir, capture_output=True, text=True, encoding="utf-8", errors="replace")
    secs = _t.time() - _t0
    null_secs = None
    if os.environ.get("VC_FFSPLIT") == "1" and kq.returncode == 0:
        try:
            ci = cmd.index("-c:v")                      # bỏ encoder + output → chỉ decode+filter (filter-only)
            _n0 = _t.time()
            subprocess.run(cmd[:ci] + ["-f", "null", "-"], cwd=base_dir,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
            null_secs = _t.time() - _n0
        except Exception:
            pass
    enc = "nvenc" if any(isinstance(c, str) and "nvenc" in c for c in cmd) else "x264"
    rec = {"secs": round(secs, 1), "enc": enc}
    rec.update(meta)
    msg = "⏱ ffmpeg ghép: %.1fs (%s)" % (secs, enc)
    if null_secs is not None:
        rec["filter_only"] = round(null_secs, 1)
        rec["encode"] = round(max(0.0, secs - null_secs), 1)
        msg += " = filter %.1fs + encode %.1fs" % (null_secs, max(0.0, secs - null_secs))
    log_fn(msg)
    try:
        _pl = os.environ.get("VC_PROFILE_LOG")
        if _pl:
            with open(_pl, "a", encoding="utf-8") as _f:
                _f.write(_j.dumps({"t": int(_t.time()), "ffmpeg": rec}, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return kq


def _fc_args(fc_str, dir=None):
    """LUÔN ghi filtergraph ra FILE tạm + trả (args -filter_complex_script, đường file). Dùng THAY -filter_complex
    inline ở MỌI filter phức tạp → command-line KHÔNG BAO GIỜ vượt giới hạn Windows 32767 ký tự ([WinError 206])
    dù filter dài bao nhiêu (warp/cue/ảnh hàng trăm-nghìn node). Bỏ ngưỡng đo độ dài (đơn giản + bền tương lai).
    Caller xoá file trả về sau khi chạy xong (try/except OSError)."""
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".fffc", dir=dir)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(fc_str)
    return ["-filter_complex_script", path], path


def burn_phude(video, vi_srt, out_mp4, che_chu=True, audio_path=None, log_fn=log,
               extra_vf=None, speed=1.0, wm_path=None, wm_pos="20:20", wm_scale="",
               bg_path=None, bg_vol=0.25, blur_band=None, blur_segs=None,
               logo=None, text_wm=None, blur_boxes=None, video_slow=1.0, time_warp=None,
               phude_style="default"):
    """Ghép video CUỐI trong 1 LẦN ENCODE.
    - Mặc định (chỉ che chữ + burn phụ đề): đường ĐƠN GIẢN như cũ (không đụng luồng khác).
    - Khi có biến đổi hình / tăng tốc / watermark / nhạc nền → gộp HẾT vào 1 filter_complex
      (thay cho việc encode riêng B1 'biến đổi hình' và B3 'tăng tốc' → tiết kiệm 2 lần encode).
    extra_vf : list filter video chèn TRƯỚC che/sub (vd ['hflip','eq=...']).
    speed    : tăng tốc — setpts (video) + atempo (audio), áp ở CUỐI (whisper đã nghe tốc độ gốc).
    wm_path/bg_path: watermark / nhạc nền (gộp cùng lần encode)."""
    base_dir = os.path.dirname(os.path.abspath(vi_srt)) if vi_srt else os.path.dirname(os.path.abspath(video))
    try:
        import dai_sub
        _vW, _vH, _ = dai_sub._kich_thuoc(xu_ly_video.tim_exe("ffprobe"), os.path.abspath(video))
    except Exception:
        _vW, _vH = 0, 0
    extra_vf = [f for f in (extra_vf or []) if f]
    spd = float(speed or 1.0)
    co_wm = bool(wm_path and os.path.isfile(wm_path))
    co_bg = bool(bg_path and os.path.isfile(bg_path))
    co_speed = abs(spd - 1.0) > 1e-6
    # blur_band=(y0,y1,H[,x0,x1]): làm mờ ĐÚNG dải sub gốc (dò bằng dai_sub) thay hộp đen cố định.
    # blur_segs=list (t_on,t_off,y0,y1,x0,x1): blur ĐỘNG bám sub DI CHUYỂN (mỗi đoạn 1 vị-trí, bật theo thời gian).
    # Cần split/overlay → ép đi đường filter_complex (gop) cho gọn 1 chỗ.
    blur_segs = [s for s in (blur_segs or []) if s] or None
    co_blur = bool(che_chu and (blur_band or blur_segs))
    
    # SRT copy & ASS generation (called early to get max_h_norm for cover box size calculation)
    import shutil
    sub_rel, sub_tmp = (os.path.basename(vi_srt) if vi_srt else None), None
    sub_ass_rel = sub_ass_tmp = None
    max_h_norm = 0.0
    if vi_srt and os.path.isfile(vi_srt):
        _cand = "_burnsub_%d.srt" % os.getpid()
        try:
            shutil.copyfile(vi_srt, os.path.join(base_dir, _cand))
            sub_rel, sub_tmp = _cand, os.path.join(base_dir, _cand)
        except OSError:
            pass
            
    if co_blur and sub_tmp:
        try:
            _W, _Hp = _vW, _vH
            if _W > 0 and _Hp > 0:
                if blur_segs:
                    _segs = blur_segs
                else:
                    _bx0 = blur_band[3] if len(blur_band) > 3 else 0.0
                    _bx1 = blur_band[4] if len(blur_band) > 4 else 1.0
                    _segs = [(0.0, 1e9, blur_band[0], blur_band[1], _bx0, _bx1)]
                _acand = "_burnpos_%d.ass" % os.getpid()
                _res, _max_h = _srt_to_ass_pos(sub_tmp, os.path.join(base_dir, _acand), _W, _Hp, _segs, phude_style=phude_style, no_box=co_blur)
                if _res > 0:
                    sub_ass_rel, sub_ass_tmp = _acand, os.path.join(base_dir, _acand)
                    max_h_norm = _max_h
        except Exception as _e:
            log_fn("⚠ Đặt phụ đề theo dải lỗi (%s) → phụ đề thường." % str(_e)[:50])
    # KHUNG (logo/blur-box/watermark-chữ) cũng cần đường GỘP (gộp vào 1 encode, bỏ pass 2 đổi-khung khi ko reframe).
    co_khung = bool(blur_boxes or (logo and logo.get("path")) or xu_ly_video.co_text_wm(text_wm))
    # video_slow<1 (Video Assist uniform CŨ) hoặc time_warp (per-segment) → PHẢI đi đường GỘP (setpts slow
    # video chỉ có ở đó); đường đơn-giản bỏ qua. time_warp = list (o0,o1,f) → slow VIDEO biến thiên từng đoạn.
    _has_warp = bool(time_warp)
    gop = bool(extra_vf or co_wm or co_bg or co_speed or co_blur or co_khung
               or float(video_slow or 1.0) < 0.999 or _has_warp)
    
    # Calculate simple path style variables (scaled for vertical video)
    fs_val = _font_size
    ol_val = 3
    sh_val = 1
    if _vW > 0 and _vH > 0 and _vH > _vW:
        # Scale down by W / H to counteract ffmpeg automatic subtitles scaling by height
        fs_val = max(8, round(_font_size * _vW / _vH))
        ol_val = max(1, round(3.0 * _vW / _vH))
        sh_val = max(0, round(1.0 * _vW / _vH))

    # Style sub: nếu biết dải → đặt MarginV để chữ Việt nằm ĐÚNG dải đã làm mờ (đè lên chữ gốc).
    style_sub = f"FontName=Arial,FontSize={fs_val},Bold=1,Italic=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H00000000,Outline={ol_val},Shadow={sh_val},MarginV=18"
    if phude_style != "default":
        _b_style = 1 if co_blur else 3
        if phude_style == "black_on_white":
            style_sub = f"FontName=Arial,FontSize={fs_val},Bold=1,Italic=1,PrimaryColour=&H00000000,OutlineColour=&H00FFFFFF,BackColour=&H00FFFFFF,Outline={ol_val},Shadow=0,BorderStyle={_b_style},MarginV=18"
        elif phude_style == "black_on_yellow":
            style_sub = f"FontName=Arial,FontSize={fs_val},Bold=1,Italic=1,PrimaryColour=&H00000000,OutlineColour=&H0000FFFF,BackColour=&H0000FFFF,Outline={ol_val},Shadow=0,BorderStyle={_b_style},MarginV=18"
        elif phude_style == "white_on_yellow_black":
            style_sub = f"FontName=Arial,FontSize={fs_val},Bold=1,Italic=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H0000FFFF,Outline={ol_val},Shadow=0,BorderStyle={_b_style},MarginV=18"
        elif phude_style == "white_on_black":
            style_sub = f"FontName=Arial,FontSize={fs_val},Bold=1,Italic=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H00000000,Outline={ol_val},Shadow=0,BorderStyle={_b_style},MarginV=18"
    if co_blur:
        _y0, _y1, _H = blur_band[:3]          # blur_band có thể là 5-tuple (y0,y1,H,x0,x1) — chỉ cần y cho MarginV
        if (_y0 + _y1) / 2.0 < 0.5:
            # Dải sub gốc ở NỬA TRÊN → đặt chữ Việt LÊN TRÊN (Alignment=8 = giữa-trên), MarginV tính từ ĐỈNH.
            _mv = max(8, int(round(_y0 * _H)))
            style_sub = style_sub.replace("MarginV=18", "Alignment=8,MarginV=%d" % _mv)
        # Dải ở dưới: GIỮ MarginV mặc định (=18, sát đáy) → chữ Việt nằm ĐÁY đè lên dải đã blur (đã nới sát
        # đáy). KHÔNG tính _mv theo pixel vì ASS hiểu MarginV theo PlayRes (~288) → lệch lên GIỮA màn.
    ff = _ffmpeg()

    # (SRT copy & ASS generation moved early in function to compute max_h_norm)

    if not gop:
        # ===== ĐƯỜNG ĐƠN GIẢN (GIỮ NGUYÊN hành vi cũ cho case chỉ phụ đề) =====
        srt_rel = sub_rel
        vf = []
        if che_chu:
            # che dải chữ Trung thường nằm ở đáy (~20% dưới) bằng hộp đen
            vf.append("drawbox=x=0:y=ih*0.80:w=iw:h=ih*0.20:color=black@1.0:t=fill")
        if vi_srt:                                  # CHỈ burn phụ đề khi có srt (che độc lập: vi_srt=None)
            vf.append(f"subtitles={srt_rel}:force_style='{style_sub}'")
        cmd = [ff, "-y", "-i", os.path.abspath(video)]
        if audio_path:                              # thay audio (bản lồng tiếng)
            cmd += ["-i", os.path.abspath(audio_path)]
        cmd += (["-vf", ",".join(vf)] if vf else []) + _enc_video(ff)
        if audio_path:
            cmd += ["-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-b:a", "192k", "-shortest"]
        else:
            # RE-ENCODE audio (KHÔNG copy): 1 số video crawl về có AAC với AudioSpecificConfig/channel-config
            # "khác chuẩn" (phát được ở player rộng lượng NHƯNG payload channel-element loạn). `-c:a copy` giữ
            # nguyên payload đó → output audio HỎNG ("channel element X.Y is not allocated", nhiều player/ffmpeg
            # decode lỗi → mất tiếng). Encode lại về AAC stereo chuẩn 44.1k để CHUẨN HOÁ, hết lỗi mux copy.
            cmd += ["-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "44100"]
        cmd += ["-movflags", "+faststart", os.path.abspath(out_mp4)]
        log_fn("🎬 Đang ghép video (che chữ + phụ đề" + (" + lồng tiếng" if audio_path else "") + ")...")
        kq = _burn_run(cmd, base_dir, log_fn, path="simple", che=bool(che_chu), sub=bool(vi_srt))
        if sub_tmp:
            try: os.remove(sub_tmp)
            except OSError: pass
        if kq.returncode != 0:
            log_fn("⚠ FFmpeg lỗi: " + (kq.stderr or "")[-400:])
            return False
        return True

    # ===== ĐƯỜNG GỘP (1 filter_complex): biến đổi hình + watermark + che + sub + tăng tốc + nhạc nền =====
    cmd = [ff, "-y", "-i", os.path.abspath(video)]          # input 0: video
    a_in = None
    if audio_path:
        cmd += ["-i", os.path.abspath(audio_path)]; a_in = 1   # input 1: track lồng tiếng
    nxt = 1 if a_in is None else 2
    wm_in = bg_in = None
    if co_wm:
        cmd += ["-i", os.path.abspath(wm_path)]; wm_in = nxt; nxt += 1
    if co_bg:
        cmd += ["-i", os.path.abspath(bg_path)]; bg_in = nxt; nxt += 1

    fc = []
    # --- video: [biến đổi hình] -> [watermark] -> [che chữ + burn sub] -> [setpts tăng tốc] ---
    cur = "0:v"
    if extra_vf:
        fc.append(f"[0:v]{','.join(extra_vf)}[vb]"); cur = "vb"
    if co_wm:
        if wm_scale:
            fc.append(f"[{wm_in}:v]scale={wm_scale}[wm]"); wmlab = "wm"
        else:
            wmlab = f"{wm_in}:v"
        fc.append(f"[{cur}][{wmlab}]overlay={wm_pos}[vw]"); cur = "vw"
    # MIRROR fix: extra_vf có hflip → video LẬT NGANG, nhưng blur_segs/blur_band toạ-độ x lấy từ bản GỐC →
    # blur crop trên video đã lật = rơi vào x ĐỐI XỨNG → che TRƯỢT khỏi chữ (chữ Trung vẫn hiện). Lật x cho
    # khớp: x' = 1-(x+w) tức (x0',x1')=(1-x1,1-x0). y GIỮ NGUYÊN (hflip không đổi chiều dọc).
    if extra_vf and any("hflip" in str(_v) for _v in extra_vf):
        if blur_segs:
            blur_segs = [(a, b, sy0, sy1, 1.0 - sx1, 1.0 - sx0)
                         for (a, b, sy0, sy1, sx0, sx1) in blur_segs]
        if blur_band and len(blur_band) >= 5:
            blur_band = (blur_band[0], blur_band[1], blur_band[2], 1.0 - blur_band[4], 1.0 - blur_band[3])
    post = []
    if co_blur and blur_segs:
        # ===== BLUR ĐỘNG: sub DI CHUYỂN → mỗi ĐOẠN 1 hộp, BẬT theo thời gian (overlay enable=between(t,...)).
        # Tách N+1 bản từ [cur]; mỗi đoạn crop hộp + gblur + overlay (chỉ hiện trong khoảng đoạn). Đoạn không
        # chồng thời gian nên overlay tuần tự không xung đột. Phụ đề Việt cũng bám đoạn qua ASS \pos.
        n = len(blur_segs)
        fc.append(f"[{cur}]split={n + 1}" + "".join(f"[cs{i}]" for i in range(n + 1)))
        base = "cs0"
        for i, (a, b, sy0, sy1, sx0, sx1) in enumerate(blur_segs):
            sbh = max(0.03, min(0.25, sy1 - sy0))
            sbw = max(0.05, min(1.0, sx1 - sx0))
            sx0 = min(sx0, 1.0 - sbw); sy0 = min(sy0, 1.0 - sbh)
            fc.append(f"[cs{i + 1}]crop=iw*{sbw:.4f}:ih*{sbh:.4f}:iw*{sx0:.4f}:ih*{sy0:.4f},gblur=sigma=16:steps=1[csb{i}]")  # steps 2→1: blur động chạy N lần/frame → ~2× rẻ, sigma giữ nguyên (che y hệt)
            fc.append(f"[{base}][csb{i}]overlay=W*{sx0:.4f}:H*{sy0:.4f}:enable='between(t,{a:.2f},{b:.2f})'[cso{i}]")
            base = f"cso{i}"
        cur = base
    elif co_blur:
        # Làm mờ dải sub gốc: tách 1 bản, crop dải, boxblur MẠNH rồi overlay đè lại (phần còn lại nét nguyên).
        # Dải dai_sub hay HẸP/CAO hơn chữ thật (chữ nằm sát đáy) → NỚI cho phủ hết, không thì blur trượt chữ.
        by0, by1, _Hb = blur_band[:3]
        _by0_txt, _by1_txt = by0, by1     # mép chữ DÒ ĐƯỢC (trước nới) — dải cuối PHẢI phủ hết, cap chỉ cắt phần NỚI
        bx0, bx1 = (blur_band[3], blur_band[4]) if len(blur_band) >= 5 else (0.0, 1.0)   # bề ngang HỘP text (0,1=full-width)
        # Nới thêm CHIỀU CAO để che HẾT chữ gốc: dải dò bám sát hàng chữ nên chữ cao / sub 2 dòng
        # hay tràn ngoài → nới theo tỉ lệ chiều cao dải, tối thiểu 5% khung. Tăng thêm qua env
        # CHE_NOI (vd CHE_NOI=0.10 = nới 10% khung) nếu vẫn còn sót.
        try:
            import dai_sub
            _W, _Hp, _ = dai_sub._kich_thuoc(xu_ly_video.tim_exe("ffprobe"), os.path.abspath(video))
        except Exception:
            _W, _Hp = 0, 0
        _is_landscape = (_W > 0 and _Hp > 0 and _W > _Hp)

        try:
            _noi_env = float(os.environ.get("CHE_NOI", "") or 0)
        except ValueError:
            _noi_env = 0.0
        # Tinh chỉnh động theo chiều cao phụ đề gốc để ôm khít chữ chính xác cho từng video
        h_sub = by1 - by0
        _top_pad_coef = 0.08 if _is_landscape else 0.15
        _bot_pad_coef = 0.05 if _is_landscape else 0.10
        noi_top = max(_noi_env, max(0.005 if _is_landscape else 0.008, min(0.025, h_sub * _top_pad_coef)))
        noi_bot = max(_noi_env, max(0.003 if _is_landscape else 0.005, min(0.015, h_sub * _bot_pad_coef)))
        
        if (by0 + by1) / 2.0 >= 0.5:          # dải ở NỬA DƯỚI
            if by1 >= 0.85:
                # Sub SÁT đáy khung (video full-frame): nới nhẹ lên trên, kéo sát đáy
                by0 = max(0.0, by0 - noi_top)
                by1 = min(1.0, max(by1, 0.995))
            else:
                # Sub Ở GIỮA: nới nhẹ cả trên lẫn dưới
                by0 = max(0.0, by0 - noi_top)
                by1 = min(1.0, by1 + noi_bot)
        else:                                  # dải ĐỈNH (ở trên đầu)
            by0 = max(0.0, min(by0, 0.005))
            by1 = min(1.0, by1 + noi_bot)

        # Tự động mở rộng dải che nếu chữ phụ đề Việt quá dài (nhiều dòng) làm tràn dải che mặc định
        if max_h_norm > 0.0:
            h_req = max_h_norm + 0.02   # thêm 2% lề an toàn
            h_cur = by1 - by0
            if h_cur < h_req:
                cy_box = (by0 + by1) / 2.0
                by0 = cy_box - h_req / 2.0
                by1 = cy_box + h_req / 2.0
                # Căn lề kẹp trong khoảng [0.0, 1.0]
                if by0 < 0.0:
                    by1 = min(1.0, by1 - by0)
                    by0 = 0.0
                elif by1 > 1.0:
                    by0 = max(0.0, by0 - (by1 - 1.0))
                    by1 = 1.0
                _by0_txt, _by1_txt = by0, by1   # cập nhật cả text boundaries để không bị min/max cũ kéo lệch
            
        # CAP: Khống chế chiều cao động theo phụ đề gốc của chính video đó
        try:
            _cap_env = float(os.environ.get("CHE_CAP", "") or 0)
        except ValueError:
            _cap_env = 0
        _cap_default = 0.12 if _is_landscape else 0.08
        _cap = _cap_env if _cap_env > 0 else _cap_default
        
        # Đảm bảo cap đủ rộng để không bóp méo/cắt phụ đề Việt thực tế
        if max_h_norm > 0.0:
            _cap = max(_cap, max_h_norm + 0.02)
        
        # Cắt bớt phần text dò được nếu chiều cao text gốc vượt quá cap (do nhiễu OCR...)
        if _by1_txt - _by0_txt > _cap:
            if (by0 + by1) / 2.0 >= 0.5:
                _by0_txt = _by1_txt - _cap
            else:
                _by1_txt = _by0_txt + _cap
                
        # 🐛 FIX (đáy/mọi dải lộ mép chữ): kéo phủ hết chiều cao chữ dò được (đã được giới hạn trong cap)
        by0 = min(by0, _by0_txt)
        by1 = max(by1, _by1_txt)
        
        # Áp dụng giới hạn cứng của cap lên dải sau khi đã cộng thêm khoảng nới (padding)
        if by1 - by0 > _cap:
            if (by0 + by1) / 2.0 >= 0.5:
                by0 = by1 - _cap           # dải đáy → giữ ĐÁY, cắt phần trên
            else:
                by1 = by0 + _cap           # dải đỉnh → giữ ĐỈNH, cắt phần dưới
        # CÁCH LỀ (đỡ xấu, giống các video khác): dải blur chừa lề CHE_LE mỗi bên (mặc định 5% khung) thay vì
        # bám sát 2 mép. Chỉ THU vào (max/min) — nếu hộp text đã hẹp hơn thì GIỮ, không nới ra ngoài lề.
        try:
            _le = float(os.environ.get("CHE_LE", "") or 0.05)
        except ValueError:
            _le = 0.05
        if _le > 0:
            bx0 = max(bx0, _le); bx1 = min(bx1, 1.0 - _le)
        bh = max(0.04, by1 - by0)
        bw = max(0.05, bx1 - bx0)            # bề ngang HỘP blur (chừa lề khi CHE_LE>0)
        # TRONG SUỐT (đỡ xấu): dải blur phủ ALPHA (CHE_ALPHA, mặc định 0.85) → ~15% hình gốc lộ nhẹ → dải MỀM,
        # bớt như thanh kiểm duyệt. Chữ Việt burn ĐÈ lên che phần giữa. Hạ CHE_ALPHA đẹp hơn NHƯNG chữ Trung
        # có thể lộ mờ (ngược với "che kín" — cân theo gu). blur MẠNH ĐÚNG HỘP text → chữ Hán không đọc được.
        try:
            _alpha_default = 0.85 if phude_style == "default" else 1.0
            _alpha = min(1.0, max(0.3, float(os.environ.get("CHE_ALPHA", "") or _alpha_default)))
        except ValueError:
            _alpha = 0.85 if phude_style == "default" else 1.0
        _mix = "" if _alpha >= 0.999 else f",format=yuva420p,colorchannelmixer=aa={_alpha:.3f}"
        if phude_style == "default":
            fc.append(f"[{cur}]split[cmain][cband]")
            # gblur (gaussian) sigma lớn, KHÔNG vướng giới hạn radius≤kích-thước như boxblur (an toàn mọi hộp).
            fc.append(f"[cband]crop=iw*{bw:.4f}:ih*{bh:.4f}:iw*{bx0:.4f}:ih*{by0:.4f},gblur=sigma=18:steps=3{_mix}[cbandb]")
            fc.append(f"[cmain][cbandb]overlay=W*{bx0:.4f}:H*{by0:.4f}[vmsk]")
        else:
            _color_map = {
                "black_on_white": "white",
                "black_on_yellow": "yellow",
                "white_on_yellow_black": "yellow",
                "white_on_black": "black"
            }
            _c_name = _color_map.get(phude_style, "black")
            _c_val = f"{_c_name}@{_alpha:.3f}" if _alpha < 0.999 else _c_name
            fc.append(f"[{cur}]drawbox=x=iw*{bx0:.4f}:y=ih*{by0:.4f}:w=iw*{bw:.4f}:h=ih*{bh:.4f}:color={_c_val}:t=fill[vmsk]")
        cur = "vmsk"
    elif che_chu:
        _color_map = {
            "black_on_white": "white@1.0",
            "black_on_yellow": "yellow@1.0",
            "white_on_yellow_black": "yellow@1.0",
            "white_on_black": "black@1.0"
        }
        _box_color = _color_map.get(phude_style, "black@1.0")
        post.append(f"drawbox=x=0:y=ih*0.80:w=iw:h=ih*0.20:color={_box_color}:t=fill")
    if vi_srt:
        if sub_ass_rel:                       # ASS \pos: phụ đề ĐÈ tâm dải blur (style nằm trong file ASS)
            post.append(f"subtitles={sub_ass_rel}")
        else:
            post.append(f"subtitles={sub_rel}:force_style='{style_sub}'")
    # KHUNG (logo / blur-box xoá logo gốc / watermark-chữ) GỘP vào CHÍNH pass này (sau che+sub) → BỎ pass 2
    # "đổi khung/logo" khi KHÔNG reframe → tiết kiệm 1 lần encode (~120s video dài). speed (setpts) phải áp
    # CUỐI (sau khung) nên tách riêng khỏi post.
    # VIDEO ASSIST: video chậm → setpts. Tốc độ VIDEO = spd(user) × hệ-số-slow; AUDIO chỉ atempo theo spd
    # (giọng/mix ĐÃ fit sẵn per-segment, KHÔNG atempo lại theo slow).
    #  - time_warp (PER-SEGMENT, mới): mỗi đoạn warp (o0,o1,f) → trim đoạn + setpts=PTS/(spd×f) + concat.
    #    Sub/blur/khung đã áp lên `cur` TRƯỚC bằng enable=between(t,...) trên mốc GỐC → tự bám tốc độ đoạn (đúng).
    #  - video_slow (uniform CŨ): 1 setpts cho cả video. _vspd=spd×S.
    _vspd = spd * float(video_slow or 1.0)
    _spd_node = f"setpts=PTS/{_vspd:.5f}" if abs(_vspd - 1.0) > 1e-6 else ""

    def _emit_speed(_inlab):
        """Append node(s) tốc độ từ [_inlab] → [vo]. time_warp → piecewise trim/setpts/concat; else setpts đơn."""
        if _has_warp:
            # PIECEWISE: split [_inlab] thành N bản, mỗi bản trim 1 khoảng warp (thời-gian GỐC) + setpts theo spd×f,
            # nối lại bằng concat. trim+setpts=PTS-STARTPTS reset mốc → mỗi đoạn bắt đầu từ 0; setpts/(spd×f) nén/giãn.
            _segs = [(o0, o1, f) for (o0, o1, f) in time_warp if o1 - o0 > 1e-6]
            _n = len(_segs)
            fc.append(f"[{_inlab}]split={_n}" + "".join(f"[vw{i}]" for i in range(_n)))
            _labs = []
            for i, (o0, o1, f) in enumerate(_segs):
                _s = spd * float(f or 1.0)         # tốc độ đoạn = user-speed × warp-factor (f<1 → chậm)
                _node = "trim=start=%.4f:end=%.4f,setpts=PTS-STARTPTS" % (o0, o1)
                if abs(_s - 1.0) > 1e-6:
                    _node += ",setpts=PTS/%.5f" % _s
                fc.append(f"[vw{i}]{_node}[vws{i}]")
                _labs.append(f"[vws{i}]")
            fc.append("".join(_labs) + f"concat=n={_n}:v=1:a=0[vo]")
        else:
            fc.append(f"[{_inlab}]{_spd_node}[vo]" if _spd_node else f"[{_inlab}]null[vo]")

    _khung_tw = []
    if co_khung:
        _mr = any("hflip" in str(_v) for _v in (extra_vf or []))   # video đã hflip → helper lật x blur_boxes
        _logo_lab = ""
        if logo and logo.get("path") and os.path.isfile(logo["path"]):
            cmd += ["-i", os.path.abspath(logo["path"])]; _logo_lab = f"{nxt}:v"; nxt += 1
        _kin = cur
        if post:                                  # áp che/sub trước → rồi khung đè lên trên
            fc.append(f"[{cur}]{','.join(post)}[vpre]"); _kin = "vpre"
        _kp, _kout, _kn, _khung_tw = xu_ly_video.khung_filter_parts(
            {"ffmpeg_path": ff}, os.path.abspath(video), _kin, 9000,
            blur_boxes, logo, _logo_lab, text_wm, _mr)
        fc += _kp
        _emit_speed(_kout)
    else:
        # KHÔNG khung: gộp post (che/sub) vào 1 node rồi áp tốc độ. time_warp cần input là 1 label nên KHÔNG
        # dồn setpts vào post; còn không-warp thì giữ cách cũ (append setpts vào post — 1 node, rẻ hơn).
        if _has_warp:
            _pre = f"[{cur}]{','.join(post)}[vpre]" if post else f"[{cur}]null[vpre]"
            fc.append(_pre)
            _emit_speed("vpre")
        else:
            if _spd_node:
                post.append(_spd_node)           # SAU sub: sub vẽ theo mốc gốc rồi mới nén tốc độ → vẫn khớp
            fc.append(f"[{cur}]{','.join(post)}[vo]" if post else f"[{cur}]null[vo]")
    vmap = "[vo]"
    # --- audio: [nguồn (lồng tiếng/gốc)] -> [atempo tăng tốc] -> [trộn nhạc nền] ---
    base_a = f"{a_in}:a" if a_in is not None else "0:a"
    cura = base_a
    if co_speed:
        atempo = "atempo=2.0,atempo=%s" % (spd / 2.0) if spd > 2.0 else "atempo=%s" % spd
        fc.append(f"[{base_a}]{atempo}[asp]"); cura = "asp"
    if co_bg:
        fc.append(f"[{bg_in}:a]volume={bg_vol}[bgv]")
        fc.append(f"[{cura}][bgv]amix=inputs=2:duration=first:normalize=0[ao]"); amap = "[ao]"
    else:
        amap = f"[{cura}]" if cura != base_a else base_a

    _fa, _fc_script = _fc_args(";".join(fc))   # LUÔN script-file (bỏ ngưỡng 6000) → bền WinError 206 với filter dài bất kỳ
    cmd += _fa + ["-map", vmap, "-map", amap]
    cmd += _enc_video(ff) + ["-c:a", "aac", "-b:a", "192k", "-shortest",
                             "-movflags", "+faststart", os.path.abspath(out_mp4)]
    log_fn("🎬 Đang ghép video — GỘP biến đổi hình + che chữ + phụ đề"
           + (" + lồng tiếng" if audio_path else "") + (" + tăng tốc" if co_speed else "")
           + " (1 lần encode)...")
    kq = _burn_run(cmd, base_dir, log_fn, path="gop", che=bool(che_chu), sub=bool(vi_srt),
                   segs=len(blur_segs or []), band=bool(blur_band), speed=round(float(speed), 2))
    if _fc_script:
        try: os.remove(_fc_script)
        except OSError: pass
    if sub_tmp:
        try: os.remove(sub_tmp)
        except OSError: pass
    if sub_ass_tmp:
        try: os.remove(sub_ass_tmp)
        except OSError: pass
    for _tw in _khung_tw:                          # dọn file tạm chữ watermark (khung gộp)
        try: os.remove(_tw)
        except OSError: pass
    if kq.returncode != 0:
        log_fn("⚠ FFmpeg lỗi (gộp): " + (kq.stderr or "")[-500:])
        return False
    return True


def _ffmpeg():
    return xu_ly_video.tim_exe("ffmpeg")   # PATH -> bundle vendor -> winget (khách thiếu PATH vẫn chạy)


def _thoi_luong(path):
    try:
        kq = subprocess.run([xu_ly_video.tim_exe("ffprobe"), "-v", "error",
                             "-show_entries", "format=duration", "-of",
                             "default=noprint_wrappers=1:nokey=1", path],
                            capture_output=True, text=True, timeout=60)
        return float(kq.stdout.strip())
    except Exception:
        return 0.0


def _im_lang_wav(dur, out, ff):
    """Tạo wav im lặng dài `dur` giây (24k mono)."""
    subprocess.run([ff, "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                    "-t", "%.3f" % max(0.02, dur), "-ar", "24000", "-ac", "1",
                    "-c:a", "pcm_s16le", out], capture_output=True)


def _atempo_wav(src, tempo, out, ff):
    """Tăng tốc wav bằng atempo (giữ cao độ) → ép cho vừa khe thời gian. (Dự phòng khi audiostretchy lỗi.)"""
    subprocess.run([ff, "-y", "-i", src, "-af", "atempo=%.3f" % tempo,
                    "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", out], capture_output=True)


def _stretch_raw_py(seg_audio, ratio):
    """Nén/giãn 1 câu (pydub AudioSegment 24k mono 16-bit) bằng audiostretchy — THUẦN PYTHON,
    giữ cao độ (TDHS), chạy TRONG RAM (không spawn ffmpeg, không file tạm). ratio<1 = nhanh/ngắn hơn.
    Trả (raw_bytes, dur_giây) hoặc None (chưa cài audiostretchy / lỗi → caller lùi ffmpeg atempo).
    Ép DUB_STRETCH=ffmpeg để buộc dùng atempo (nếu nghe audiostretchy không hợp)."""
    if os.environ.get("DUB_STRETCH") == "ffmpeg":
        return None
    try:
        import io
        import numpy as np
        from audiostretchy.stretch import AudioStretch
        ratio = max(0.5, min(2.0, float(ratio)))   # vùng an toàn TDHS (cap nén 1.6x → ratio 0.625)
        buf = io.BytesIO()
        seg_audio.export(buf, format="wav")
        buf.seek(0)
        a = AudioStretch()
        a.open(file=buf, format="wav")
        a.stretch(ratio=ratio)
        s = a.samples
        if s is None or len(s) == 0:
            return None
        nz = np.nonzero(s)[0]            # audiostretchy KHÔNG cắt đệm zero ở đuôi → tự cắt, không thì dôi im lặng
        s = s[: nz[-1] + 1] if len(nz) else s[:0]
        if len(s) == 0:
            return None
        return s.astype(np.int16).tobytes(), len(s) / float(a.framerate or 24000)
    except Exception:
        return None


def _ghep_track_khop(items, tong_giay, dub_wav, log_fn=log):
    """Dựng track lồng tiếng NỐI TIẾP + ÉP KHỚP THỜI LƯỢNG từng câu (24k mono 16-bit).
    items = [(st, en, seg_wav)]. Câu Việt dài hơn khe (en-st) → atempo nén lại (cap 1.6x);
    chèn im lặng cho đúng mốc bắt đầu. KHÔNG overlay → KHÔNG chồng tiếng. Trả dub_wav hoặc None.

    TỐI ƯU: nối RAW BYTES trong bộ nhớ bằng pydub (1 lần join) thay vì spawn ~2 ffmpeg/câu
    (silence + concat) → bỏ hàng trăm process, nhanh ~5-10×. Chỉ còn atempo (ffmpeg) cho câu TRÀN."""
    from pydub import AudioSegment
    SR = 24000
    work = os.path.join(os.path.dirname(os.path.abspath(dub_wav)), "_dubtmp")
    os.makedirs(work, exist_ok=True)

    # Giảm dead-air: chèn im lặng tối đa MAX_SIL giây (<=0 = không giới hạn).
    # DUB_FILL: khe RỖNG > 0.8s thì GIÃN giọng (đọc CHẬM lại) tối đa FILL lần cho đỡ trống.
    # MẶC ĐỊNH 1.0 = KHÔNG giãn — vì kéo chậm giọng nghe NHÃO (nhất là với OCR-timing: khe = thời gian
    # sub HIỂN THỊ, vốn dài hơn lời nói → giãn nhiều → chậm). Giọng đọc tốc độ TỰ NHIÊN, khe trống để
    # im lặng; CHỈ nén khi câu TRÀN (đọc nhanh ít chói hơn kéo chậm). Đặt DUB_FILL>1 nếu muốn giãn lấp khe.
    try:
        MAX_SIL = float(os.environ.get("DUB_MAX_SIL", "1.2"))
    except ValueError:
        MAX_SIL = 1.2
    if MAX_SIL <= 0:
        MAX_SIL = float("inf")
    try:
        FILL = float(os.environ.get("DUB_FILL", "1.0"))
    except ValueError:
        FILL = 1.0
    # Câu TRÀN khe sub → NÉN (đọc nhanh) cho vừa, tối đa MAXSP lần. Trước chặn 1.6× → giọng dài quá
    # (tiếng Việt thường dài hơn tiếng Trung) nén không kịp → LỆCH SAU text. Nâng 2.0 để
    # giọng LUÔN khít khe = khớp text mọi clip (câu nào dài quá thì đọc gấp hơn). Chỉnh env DUB_MAX_SPEED.
    # MẶC ĐỊNH 1.3 (thong thả, đọc TỰ NHIÊN — đã GỠ "bám timing 2.0x" theo yêu cầu): câu Việt dài chỉ nén
    # NHẸ (≤1.3×), không ép gấp cho khít từng khe → giọng nghe tự nhiên (chấp nhận lệch nhẹ ở video dài).
    # Ép qua env DUB_MAX_SPEED nếu cần nén mạnh hơn.
    try:
        MAXSP = float(os.environ.get("DUB_MAX_SPEED", "1.3"))
    except ValueError:
        MAXSP = 1.3
    if MAXSP < 1.0:
        MAXSP = 1.0
    # ADAPTIVE dead-zone: câu tràn ≤ TOL (mặc định 12%) KHI KHÔNG đang trễ → ĐỌC TỰ NHIÊN (1.0×), cho lấn
    # vào khe lặng kế; chỉ nén khi tràn nhiều HOẶC đang catch-up (trễ thật). Tai người không nhận ra tràn nhẹ
    # < ~12% nhưng rất nhạy với nén đột ngột → để tự nhiên đẹp hơn. Tắt: DUB_FIT_TOL=0. (nén vẫn TỈ LỆ fit_to/dur)
    try:
        TOL = float(os.environ.get("DUB_FIT_TOL", "0.12"))
    except ValueError:
        TOL = 0.12
    if TOL < 0:
        TOL = 0.0
    # CATCH-UP đồng bộ (drift): tiếng Việt thường DÀI hơn khe → cursor trôi DẦN sau phụ đề; video dài (1807 câu)
    # → lệch tích luỹ lớn ở cuối ("giọng chậm hơn chữ"). KHI giọng đang TRỄ > ngưỡng → nén MẠNH hơn (cap động
    # tới CATCHUP_MAX) + ép câu kết thúc gần 'en' để ĐUỔI KỊP DẦN; câu đúng giờ vẫn nén tự nhiên (≤MAXSP).
    # Tắt: DUB_CATCHUP=0. Chỉnh: DUB_CATCHUP_THRESHOLD (mặc định 0.3s) / DUB_CATCHUP_MAX (mặc định 2.2×).
    CATCHUP = os.environ.get("DUB_CATCHUP", "1") != "0"
    try:
        CATCHUP_TH = float(os.environ.get("DUB_CATCHUP_THRESHOLD", "0.3"))
    except ValueError:
        CATCHUP_TH = 0.3
    try:
        CATCHUP_MAX = float(os.environ.get("DUB_CATCHUP_MAX", "2.2"))
    except ValueError:
        CATCHUP_MAX = 2.2
    if CATCHUP_MAX < MAXSP:
        CATCHUP_MAX = MAXSP
    # B2: khe im lặng > GAP_GIU giây = NGẮT THẬT (nhạc/hành động/ngắt) → GIỮ đủ im lặng để giọng bám đúng
    # mốc hình (đồng bộ). Khe nhỏ hơn → kẹp về MAX_SIL cho đỡ dead-air. DUB_GAP_GIU=0 giữ MỌI khe;
    # đặt RẤT LỚN (vd 99999) = luôn kẹp (hành vi cũ, ít dead-air nhưng có thể lệch khi gap dài).
    try:
        GAP_GIU = float(os.environ.get("DUB_GAP_GIU", "3.0"))
    except ValueError:
        GAP_GIU = 3.0

    def _sil(sec):                            # bytes im lặng 24k mono 16-bit
        return b"\x00\x00" * int(max(0.0, sec) * SR)

    def _seg_audio(p):                        # đọc wav -> AudioSegment 24k mono 16-bit (tự resample)
        return AudioSegment.from_file(p).set_frame_rate(SR).set_channels(1).set_sample_width(2)

    # ===== VIDEO ASSIST PER-SEGMENT (van giảm áp video↔giọng, BIẾN THIÊN theo thời gian) =====
    # CŨ = 1 hệ số S cho CẢ video (uniform). MỚI = chỉ ĐOẠN GIỌNG NHANH mới chậm video (chia tải cục bộ).
    # Mỗi câu i: need_i = dur_i/slot_i.
    #   need_i ≤ VOICE_CAP (1.12)  → giọng đọc tự nhiên (≤1.12×), KHÔNG chậm video đoạn này (f_i=1.0).
    #   need_i > VOICE_CAP         → CHẬM VIDEO đoạn này f_i = max(1-MAXSLOW, VOICE_CAP/need_i) (≥1-MAXSLOW).
    #       Khe câu GIÃN 1/f_i → giọng nén tới need_i×f_i (=VOICE_CAP nếu chưa chạm trần; nếu f chạm trần
    #       thì giọng = need_i×f_i > VOICE_CAP — chấp nhận, video đã chậm hết cỡ).
    # → Sinh BẢN ĐỒ WARP phủ TOÀN [0,tong_giay] = list (orig_start, orig_end, f) LIÊN TỤC (gap+câu thường f=1.0,
    #   câu nhanh f<1). Export qua _LAST_TIME_WARP cho caller slow VIDEO + tiếng gốc piecewise khớp.
    # MAXSLOW=0 → TẮT: warp=None, _LAST_VIDEO_SLOW=1.0 (đường cũ, không assist — fallback an toàn).
    # Đo need từ wav ĐÃ synth (KHÔNG synth lại). Slot câu sau giãn = đường vào loop ghép vẫn fit như cũ
    # (catch-up/dead-zone/atempo GIỮ NGUYÊN — chỉ khe rộng hơn nên nén ít hơn).
    _time_warp = None
    # BẬT MẶC ĐỊNH (user chốt sau khi đo THẬT trên video liệt kê nhanh id: cap-hit 100%→53%, need_mean
    # 6.09×→1.52× khi bật 40%; đã verify cơ chế TỰ GIỚI HẠN — chỉ câu THẬT SỰ cần (need>_vcap) mới bị
    # chậm video, câu bình thường f=1.0 không đổi gì → video thường không bị ảnh hưởng). Tắt: DUB_VIDEO_MAXSLOW=0.
    try:
        _maxslow = float(os.environ.get("DUB_VIDEO_MAXSLOW", "0.4") or 0.4)
    except ValueError:
        _maxslow = 0.4
    try:
        _vcap = float(os.environ.get("DUB_VOICE_CAP", "1.12") or 1.12)
    except ValueError:
        _vcap = 1.12
    if _vcap < 1.0:
        _vcap = 1.0
    if _maxslow > 0.001:
        import wave as _wv
        _fmin = max(0.0, 1.0 - _maxslow)           # video chậm tối đa MAXSLOW → f_i ≥ _fmin
        # Đo need mỗi câu hợp lệ (giữ đúng thứ tự items, dùng cho cả warp lẫn rescale slot)
        _need_of = {}
        for _idx, (st, en, seg) in enumerate(items):
            if not (seg and os.path.isfile(seg)):
                continue
            try:
                with _wv.open(seg, "rb") as _w:
                    _d = _w.getnframes() / float(_w.getframerate() or SR)
            except Exception:
                continue
            _need_of[_idx] = _d / max(0.1, en - st)
        # Build warp map (orig time) + rescale items sang OUTPUT timeline (khe câu nhanh giãn 1/f).
        _warp = []
        _new_items = []
        _orig_st_list = []                         # st GỐC mỗi câu (cùng thứ tự _new_items) → căn phụ đề
        _orig_cur = 0.0                            # con trỏ thời-gian GỐC
        _out_cur = 0.0                             # con trỏ thời-gian OUTPUT (đã giãn)
        _n_slow = 0
        for _idx, (st, en, seg) in enumerate(items):
            # gap trước câu: giữ tốc độ gốc (f=1.0)
            if st - _orig_cur > 1e-6:
                _warp.append((_orig_cur, st, 1.0))
                _out_cur += (st - _orig_cur)        # f=1 → output = gốc
            slot = max(0.1, en - st)
            need = _need_of.get(_idx, 1.0)
            if need > _vcap:                        # câu NHANH → chậm video đoạn này
                f = max(_fmin, _vcap / need)
                _n_slow += 1
            else:
                f = 1.0
            _warp.append((st, en, f))
            _new_slot = (en - st) / f               # khe OUTPUT giãn 1/f
            _new_items.append((_out_cur, _out_cur + _new_slot, seg))
            _orig_st_list.append(st)                # mốc GỐC câu này (cho căn phụ đề khớp dub)
            _out_cur += _new_slot
            _orig_cur = en
        # gap đuôi tới hết video (f=1.0) — phủ liên tục [0, tong_giay]
        if tong_giay and tong_giay - _orig_cur > 1e-6:
            _warp.append((_orig_cur, tong_giay, 1.0))
            _out_cur += (tong_giay - _orig_cur)
        # GỘP đoạn LIỀN KỀ CÙNG tốc độ (nhất là chuỗi f=1.0) → giảm SỐ ĐOẠN cho filter_complex piecewise:
        # video 300 câu mà KHÔNG gộp = ~600 trim+concat (graph khổng lồ, ffmpeg chậm/ngốn RAM); gộp về số VÙNG
        # ĐỔI-tốc-độ thật (thường vài chục). KHÔNG đổi kết quả warp (đoạn liền + cùng f = 1 đoạn dài).
        if _warp:
            _merged = [list(_warp[0])]
            for (a, b, f) in _warp[1:]:
                if abs(f - _merged[-1][2]) < 1e-4 and abs(a - _merged[-1][1]) < 1e-6:
                    _merged[-1][1] = b               # nối tiếp + cùng tốc độ → kéo dài đoạn trước
                else:
                    _merged.append([a, b, f])
            _warp = [(a, b, f) for (a, b, f) in _merged]
    _orig_st_map = None
    if _maxslow > 0.001 and _n_slow > 0:
            items = _new_items
            tong_giay = _out_cur if tong_giay else tong_giay
            _time_warp = _warp
            _orig_st_map = _orig_st_list           # st GỐC mỗi câu (cho căn phụ đề khớp dub)
            _tot_orig = sum(b - a for (a, b, _f) in _warp)
            log_fn("🎬 Video Assist per-segment: %d/%d câu nhanh → chậm video cục bộ (cap %.0f%%, giọng ≤%.2f×) "
                   "→ video %+.1f%% dài hơn" % (_n_slow, len(items), _maxslow * 100, _vcap,
                   ((_out_cur / _tot_orig - 1.0) * 100) if _tot_orig else 0.0))
    globals()["_LAST_TIME_WARP"] = _time_warp
    # _LAST_VIDEO_SLOW giữ cho tương thích ngược (caller cũ / khi warp tắt). Per-segment → 1.0 (slow nằm trong warp).
    globals()["_LAST_VIDEO_SLOW"] = 1.0

    parts, cursor, co_tieng = [], 0.0, 0
    _dub_onsets = []   # (st_ORIG câu, onset_OUT, end_OUT): vị trí THỰC dub mỗi câu trên timeline OUTPUT
                       # (sau chèn im lặng + nén/catch-up). Dùng để CĂN phụ đề Việt khớp giọng (chống desync).
                       # st_orig = mốc gốc câu (items0[i][0] khi warp bật; = items[i][0] khi warp tắt).
    _ratios = []; _nen = [0]   # _ratios = over-length thô; _nen = số câu THỰC SỰ bị nén (sau dead-zone)
    _applied = []   # tốc độ TTS THỰC SỰ áp dụng mỗi câu (dur_gốc/dur_sau) — đo mức nén THẬT (sau cap+catch-up)
    _needed = []    # tốc độ CẦN để vừa khe (dur/fit_to) TRƯỚC khi cap → so với applied = catch-up/cap cứu bao nhiêu
    _cap = [0]; _caup_n = [0]   # _cap=số câu CHẠM trần MAXSP/CATCHUP (vẫn tràn); _caup_n=số câu kích catch-up (đang trễ)
    for i, (st, en, seg) in enumerate(items):
        if not (seg and os.path.isfile(seg)):
            continue
        try:
            a = _seg_audio(seg)
        except Exception:
            continue
        raw, dur = a.raw_data, (len(a) / 1000.0)
        if dur <= 0:
            continue
        _dur0 = dur   # dur GỐC (trước nén/giãn) → tính tốc độ áp dụng = _dur0/dur cuối
        gap = st - cursor
        if gap > 0.03:                        # chèn im lặng tới đúng mốc bắt đầu câu
            sil = gap if gap > GAP_GIU else min(gap, MAX_SIL)   # B2: gap LỚN giữ mốc thật; nhỏ kẹp đỡ dead-air
            parts.append(_sil(sil)); cursor += sil
        _onset_out = cursor                   # vị trí THỰC dub câu này (output) — TRƯỚC khi phát raw
        _st_orig = _orig_st_map[i] if (_orig_st_map and i < len(_orig_st_map)) else st  # mốc gốc câu (warp tắt: st)
        slot = max(0.1, en - st)
        _ratios.append(dur / slot)   # over-length thô (TRƯỚC nén): >1 = TTS dài hơn khe → phải nén/đuổi
        # CATCH-UP: drift = giọng đang TRỄ bao nhiêu so phụ đề (cursor đã vượt mốc bắt đầu st).
        # Trễ > ngưỡng → cap nén ĐỘNG cao hơn (đuổi kịp) + đích = khe CÒN LẠI (en-cursor) để câu kết thúc gần en.
        drift = cursor - st
        eff_max, fit_to = MAXSP, slot
        _caup = CATCHUP and drift > CATCHUP_TH
        if _caup:
            _caup_n[0] += 1
            eff_max = min(CATCHUP_MAX, MAXSP + min(drift / 2.0, 0.9))   # drift 0.3→~1.45×, 1s→1.8×, ≥1.8s→2.2×
            fit_to = max(0.1, en - cursor)    # còn lại trong khe từ vị-trí TRỄ → ép câu khít vào đây cho bám kịp
        # dead-zone: KHÔNG trễ → bỏ qua tràn ≤TOL (đọc tự nhiên, lấn khe lặng); đang trễ → nén ngay (đuổi kịp)
        _nguong = fit_to if _caup else fit_to * (1.0 + TOL)
        if dur > _nguong:                     # tràn QUÁ ngưỡng → nén TỈ LỆ cho vừa fit_to (giữ cao độ), cap eff_max
            _need = dur / fit_to              # tốc độ CẦN để khít khe (trước cap) → đo cap/catch-up cứu bao nhiêu
            _needed.append(_need)
            if _need > eff_max + 1e-6:        # cần > trần → CHẠM CAP (vẫn tràn, không khít được)
                _cap[0] += 1
            ratio = max(1.0 / eff_max, fit_to / dur)   # ratio = đích/hiện-tại; >= 1/eff_max (không nén quá eff_max×)
            _nen[0] += 1
            r = _stretch_raw_py(a, ratio)     # THUẦN PYTHON (audiostretchy), trong RAM
            if r:
                raw, dur = r
            else:                             # audiostretchy chưa cài/lỗi → lùi ffmpeg atempo
                fit = os.path.join(work, "fit_%d.wav" % i)
                _atempo_wav(seg, min(eff_max, dur / fit_to), fit, _ffmpeg())
                try:
                    b = _seg_audio(fit); raw, dur = b.raw_data, (len(b) / 1000.0)
                except Exception:
                    pass
        elif FILL > 1.0 and (slot - dur) > 0.8:   # khe RỖNG → giãn nhẹ giọng (chậm) cho đỡ trống, cap FILL
            r = _stretch_raw_py(a, min(FILL, slot / dur))
            if r:
                raw, dur = r
        parts.append(raw); cursor += dur
        _dub_onsets.append((_st_orig, _onset_out, cursor))   # (mốc gốc câu, dub bắt đầu, dub kết thúc) — căn phụ đề
        _applied.append(_dur0 / dur if dur > 0 else 1.0)   # >1 = đọc nhanh hơn (nén); ~1 = giữ; <1 = giãn (khe rỗng)
        co_tieng += 1
    if _ratios:   # ĐO phân bố over-length (raw, TRƯỚC nén) → quyết có cần LLM-rewrite rút ngắn text không
        _s = sorted(_ratios); _n = len(_s)
        _med = _s[_n // 2]; _p90 = _s[min(_n - 1, int(_n * 0.9))]; _mx = _s[-1]
        _o = lambda th: round(100 * sum(1 for r in _ratios if r > th) / _n)
        if os.environ.get("VC_DUB_STATS") == "1":   # over-length THÔ (gây hiểu lầm) — chỉ DEV; khách khỏi thấy
            log_fn("📊 DUB over-length: n=%d · median %.2f · p90 %.2f · max %.2f · >1.15:%d%% >1.3:%d%% >1.5:%d%% · NÉN %d/%d (%d%%)"
                   % (_n, _med, _p90, _mx, _o(1.15), _o(1.3), _o(1.5), _nen[0], _n, round(100 * _nen[0] / _n)))
        try:
            _pl = os.environ.get("VC_PROFILE_LOG")
            if _pl:
                import json as _j, time as _tt
                with open(_pl, "a", encoding="utf-8") as _f:
                    _f.write(_j.dumps({"t": int(_tt.time()), "dub": {"n": _n, "median": round(_med, 2),
                        "p90": round(_p90, 2), "max": round(_mx, 2), "pct_gt115": _o(1.15),
                        "pct_gt13": _o(1.3), "pct_gt15": _o(1.5), "nen": _nen[0]}}, ensure_ascii=False) + "\n")
        except Exception:
            pass
    if _applied:   # ĐO tốc độ TTS THỰC SỰ áp dụng (sau cap+catch-up) → biết câu nào ĐÁNG xử (vội nghe được,
        # >1.08) vs lệch 1-2% (không đáng). Khác over-length THÔ (trước nén/cap → gây hiểu lầm). mean/p95/cap-hit/
        # catch-up giá trị hơn histogram thô. FULL → dev file; UI khách KHÔNG thấy (chỉ hiện khi VC_DUB_STATS=1).
        _sa = sorted(_applied); _na = len(_sa)
        _mean = sum(_sa) / _na
        _median = _sa[_na // 2]
        _p95 = _sa[min(_na - 1, int(_na * 0.95))]
        _amax = _sa[-1]
        _bk = [("=1.00", 1.005), ("1.01-1.03", 1.03), ("1.03-1.05", 1.05),
               ("1.05-1.08", 1.08), ("1.08-1.10", 1.10), (">1.10", 9.0)]
        _cnt = {k: 0 for k, _ in _bk}; _slow = 0
        for _s in _applied:
            if _s < 0.99:
                _slow += 1; continue
            for _k, _hi in _bk:
                if _s <= _hi:
                    _cnt[_k] += 1; break
        _nmean = (sum(_needed) / len(_needed)) if _needed else 0.0   # tốc độ CẦN tb (trước cap) → cap/catch-up cứu
        _stats = {"n": _na, "mean": round(_mean, 3), "median": round(_median, 3), "p95": round(_p95, 3),
                  "max": round(_amax, 3), "cap_hit": _cap[0], "catchup": _caup_n[0],
                  "need_mean": round(_nmean, 3), "hist": _cnt, "slow": _slow,
                  "max_speed": round(MAXSP, 2), "catchup_max": round(CATCHUP_MAX, 2),
                  "dub_cps": float(os.environ.get("DUB_CPS", "16") or 16)}
        try:   # FULL → dev file (VC_PROFILE_LOG): sau 20-30 video biết phân bố hệ thống → quyết DUB_CPS/MAX_SPEED
            _pl = os.environ.get("VC_PROFILE_LOG")
            if _pl:
                import json as _j2, time as _t2
                with open(_pl, "a", encoding="utf-8") as _f:
                    _f.write(_j2.dumps({"t": int(_t2.time()), "dub_speed": _stats}, ensure_ascii=False) + "\n")
        except Exception:
            pass
        if os.environ.get("VC_DUB_STATS") == "1":   # 1 dòng tóm tắt cho DEV (mặc định TẮT → khách khỏi thấy)
            log_fn("📊 DUB speed: mean %.3f median %.3f p95 %.3f max %.3f · cap-hit %d · catch-up %d · "
                   "ĐÁNG xử(>1.08) %d/%d · need_mean %.3f | "
                   % (_mean, _median, _p95, _amax, _cap[0], _caup_n[0],
                      _cnt["1.08-1.10"] + _cnt[">1.10"], _na, _nmean)
                   + " ".join("%s:%d" % (k, _cnt[k]) for k, _ in _bk) + (" giãn:%d" % _slow if _slow else ""))
    # Xuất bản đồ vị-trí DUB thực (output) mỗi câu → caller CĂN phụ đề Việt khớp giọng (chống desync khi câu
    # Việt dài hơn khe làm dub TRÔI khỏi mốc gốc). Reset ở đầu xu_ly (cache-hit/no-dub → None → giữ sub gốc).
    globals()["_LAST_DUB_ONSETS"] = _dub_onsets if co_tieng else None
    if not co_tieng:                          # KHÔNG có câu thoại nào → thất bại (caller fallback)
        shutil.rmtree(work, ignore_errors=True)
        return None
    if tong_giay and tong_giay - cursor > 0.1:
        parts.append(_sil(tong_giay - cursor))
    try:
        out = AudioSegment(data=b"".join(parts), sample_width=2, frame_rate=SR, channels=1)
        out.export(dub_wav, format="wav")
    except Exception as e:
        log_fn("⚠ Ghép track lỗi: %s" % str(e)[:80])
        shutil.rmtree(work, ignore_errors=True)
        return None
    shutil.rmtree(work, ignore_errors=True)
    return dub_wav if os.path.isfile(dub_wav) else None


def lay_audio(video, wav_out, video_slow=1.0, time_warp=None):
    """Tách audio gốc ra wav (44.1k stereo).
    - time_warp = list (orig_start, orig_end, f) (Video Assist per-segment): atempo CHẬM tiếng gốc TỪNG
      khoảng (atempo=f, f<1 = chậm/dài hơn) rồi nối lại → khớp video đã slow cục bộ. Khoảng f≈1.0 giữ nguyên.
    - video_slow<1 (uniform CŨ, không có warp): atempo đều theo S.
    Cả hai khớp dub đã fit per-segment → trộn nền không lệch độ dài/đồng bộ."""
    ff = _ffmpeg()
    if time_warp:
        # PIECEWISE: trim audio gốc theo từng khoảng warp (thời-gian GỐC) + atempo=f mỗi khoảng + concat.
        # f<1 → atempo<1 → đoạn DÀI ra (khớp video đã chậm); f=1 → giữ nguyên.
        fc, labs = [], []
        for i, (o0, o1, f) in enumerate(time_warp):
            if o1 - o0 <= 1e-6:
                continue
            ff_f = max(0.5, min(2.0, float(f) or 1.0))   # atempo an toàn [0.5,2.0]
            node = "atrim=start=%.4f:end=%.4f,asetpts=PTS-STARTPTS" % (o0, o1)
            if abs(ff_f - 1.0) > 1e-6:
                node += ",atempo=%.5f" % ff_f
            fc.append("[0:a]%s[aw%d]" % (node, i))
            labs.append("[aw%d]" % i)
        if labs:
            fc.append("%sconcat=n=%d:v=0:a=1[aout]" % ("".join(labs), len(labs)))
            _fa, _scr = _fc_args(";".join(fc))   # LUÔN script-file (warp PER-SEGMENT nhiều cue → tránh WinError 206)
            cmd = [ff, "-y", "-i", video] + _fa + ["-map", "[aout]", "-ac", "2", "-ar", "44100", wav_out]
            subprocess.run(cmd, capture_output=True)
            try: os.remove(_scr)
            except OSError: pass
            if os.path.isfile(wav_out):
                return wav_out
            # warp lỗi → lùi tách thẳng (đồng bộ kém hơn nhưng không hỏng pipeline)
    af = []
    _vs = float(video_slow or 1.0)
    if _vs < 0.999:
        af = ["-af", "atempo=%.5f" % max(0.5, _vs)]   # atempo<1 = chậm/dài hơn (khớp video đã slow)
    subprocess.run([ff, "-y", "-i", video, "-vn", "-ac", "2", "-ar", "44100"] + af + [wav_out],
                   capture_output=True)
    return wav_out if os.path.isfile(wav_out) else ""


# LIC_CACHE_DIR = userData (Electron truyền cho subprocess) — runtime venv ĐẶT Ở userData/runtime (BỀN
# qua update; app-src bị NSIS xoá sạch mỗi lần update). Dev (không có LIC_CACHE_DIR) -> THU_MUC_GOC.
_F5_LIC = os.environ.get("LIC_CACHE_DIR", "").strip()

# ---------------- OmniVoice (k2-fsa) — venv riêng .venv_omnivoice, CẦN GPU NVIDIA (diffusion) ----------
# 6 giọng VN + clone + thiết kế giọng (instruct). Apache-2.0. RTX 3050 RTF ~0.47 (ns8). LỰA CHỌN GPU.
OMNI_PY = os.path.join(THU_MUC_GOC, ".venv_omnivoice", "Scripts", "python.exe")
OMNI_SCRIPT = os.path.join(THU_MUC_GOC, "omnivoice_synth.py")
# Giọng mẫu CỐ ĐỊNH cho OmniVoice (clone) khi user KHÔNG upload clone → mọi câu cùng 1 giọng (chống drift).
OMNI_REF_NU = os.path.join(THU_MUC_GOC, "giong_mau", "nu.wav")
OMNI_REF_NAM = os.path.join(THU_MUC_GOC, "giong_mau", "nam.wav")
OMNI_REF_MAC_DINH = os.environ.get("OMNI_REF") or OMNI_REF_NU   # mặc định = giọng nữ

# (Kokoro-82M ĐÃ GỠ 2026-07-04 theo yêu cầu user — Supertonic phủ EN; edge là fallback online.)
# Thư mục runtime venv (userData/runtime nếu đóng gói, else repo) — trước đây khai báo trong block Kokoro.
_RUNTIME_VENV_BASE = os.path.join(_F5_LIC, "runtime") if _F5_LIC else THU_MUC_GOC

# ---------------- Supertonic-3 (supertonic, ONNX, CPU nhanh, 31 ngôn ngữ gồm en/ko/vi) ---------------
# Engine lồng tiếng TIẾNG HÀN (và tuỳ chọn EN). NHẸ (onnxruntime, KHÔNG torch). Thứ tự tìm python:
# env SUPERTONIC_PY (override, vd dev) > .venv_supertonic ở userData/runtime (nếu build tách venv riêng) >
# python đang chạy (nếu `pip install supertonic` vào venv CHÍNH app). Model auto-download HF. 10 giọng M1-M5/F1-F5.
def _supertonic_py():
    _ov = (os.environ.get("SUPERTONIC_PY") or "").strip()
    if _ov:
        return _ov
    _cand = os.path.join(_RUNTIME_VENV_BASE, ".venv_supertonic", "Scripts", "python.exe")
    return _cand if os.path.isfile(_cand) else sys.executable
SUPERTONIC_PY = _supertonic_py()
SUPERTONIC_SCRIPT = os.path.join(THU_MUC_GOC, "supertonic_synth.py")
SUPERTONIC_VOICE_MAC_DINH = os.environ.get("SUPERTONIC_VOICE") or "F1"
# Tên giọng mẫu UI → file ref clone (mọi giọng nhất quán nhờ clone 1 ref cố định).
OMNI_GIONG_MAU = {"nu": OMNI_REF_NU, "nam": OMNI_REF_NAM}

# ---------------- Piper TTS (ONNX, offline, VÔ HẠN, nhanh ~8x realtime trên CPU) ----------------
# Giọng .onnx tải bằng:  python -m piper.download_voices vi_VN-vais1000-medium --data-dir piper_vn
# Thư mục giọng Piper GHI ĐƯỢC + bền update. Thứ tự: userData/runtime (LIC_CACHE_DIR Electron truyền) >
# app-src nếu ghi được (dev) > LOCALAPPDATA (app-src trong Program Files là READ-ONLY → tải giọng
# on-demand sẽ PermissionError WinError 5). 3 file (localize/tai_banmai/giong_piper) tính RA CÙNG path.
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
# Mặc định = Ngọc Huyền (NghiTTS, tải qua giong_piper/gdown) — user chốt. Tự tải khi thiếu;
# tải lỗi → lùi vais1000. Đổi bằng env PIPER_VOICE.
PIPER_VOICE_MAC_DINH = os.environ.get("PIPER_VOICE") or os.path.join(PIPER_DIR, "ngochuyen.onnx")


def _ref_text_tu_audio(ref_wav, log_fn=log):
    """ASR giọng mẫu (tiếng Việt) bằng faster-whisper để lấy transcript cho TTS clone.
    Cache theo HASH NỘI DUNG file (_voicecache_<sha>.txt) — re-upload cùng TÊN khác NỘI DUNG sẽ KHÔNG
    dùng nhầm lời file cũ (trước đây cache theo tên → ghi đè wav nhưng giữ .txt cũ → clone lỗi chất lượng).
    Fallback cache-tên cũ (<ref>.txt) cho giọng built-in (giong_mau/nu.txt) + cache đã có."""
    import hashlib
    try:
        _h = hashlib.sha1(open(ref_wav, "rb").read()).hexdigest()[:16]
        cache = os.path.join(os.path.dirname(os.path.abspath(ref_wav)), "_voicecache_" + _h + ".txt")
    except Exception:
        cache = os.path.splitext(ref_wav)[0] + ".txt"
    for c in (cache, os.path.splitext(ref_wav)[0] + ".txt"):   # hash trước, rồi cache-tên cũ (built-in)
        if os.path.isfile(c):
            t = open(c, encoding="utf-8").read().strip()
            if t:
                return t
    try:
        from faster_whisper import WhisperModel
        log_fn("🎧 Nghe giọng mẫu để lấy lời (cho clone)...")
        dev, ct = phu_de._whisper_device()   # GPU nếu có, không thì CPU
        try:
            m = WhisperModel("small", device=dev, compute_type=ct)
        except Exception:
            m = WhisperModel("small", device="cpu", compute_type="int8")
        segs, _ = m.transcribe(ref_wav, language="vi")
        t = " ".join(s.text for s in segs).strip()
        try:
            open(cache, "w", encoding="utf-8").write(t)
        except OSError:
            pass
        return t
    except Exception as e:
        log_fn("⚠ Không lấy được lời giọng mẫu: " + str(e)[:60])
        return ""


_OMNI_NO_WIN = 0x08000000 if sys.platform == "win32" else 0   # CREATE_NO_WINDOW (daemon nền, ẩn console)


def _vram_gb():
    """Tổng VRAM GPU (GB) qua nvidia-smi; 0 nếu không có NVIDIA. Quyết định daemon warm (cần ≥6GB để
    OmniVoice ~2.2GB + ASR ~2GB cùng tồn tại) hay one-shot (load mỗi render — đúng cho GPU nhỏ ≤4GB)."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10, creationflags=_OMNI_NO_WIN)
        return int(out.stdout.strip().splitlines()[0]) / 1024.0
    except Exception:
        return 0.0


def _omni_batch():
    """Batch OmniVoice TỰ scale theo VRAM (GPU to → batch lớn → nhanh hơn). ENV OMNI_BATCH ép cứng nếu đặt.
    ≤4.5GB (RTX 3050...) giữ 8 (đã tune ~2.2GB peak); 4.5-8→16; 8-12→24; ≥12→32."""
    _e = os.environ.get("OMNI_BATCH")
    if _e:
        try:
            return max(1, int(_e))
        except ValueError:
            pass
    v = _vram_gb()
    if v >= 12:
        return 32
    if v >= 8:
        return 24
    if v >= 4.5:
        return 16
    return 8


def _omni_daemon_synth(seg_dir, texts, num_step, ref, ref_text, log_fn, instruct=None):
    """Gửi job tới DAEMON OmniVoice warm (khởi động nếu chưa chạy, GIỮ model trong VRAM cho lần sau).
    True nếu daemon synth xong (seg wav sẵn ở seg_dir); False → caller lùi one-shot."""
    import time as _t
    import tempfile
    qdir = os.path.join(tempfile.gettempdir(), "vc_omni_queue")   # temp = luôn ghi được (app-src có thể chỉ-đọc)
    os.makedirs(qdir, exist_ok=True)
    alive = os.path.join(qdir, "_alive")

    def _ok():
        try:
            return os.path.isfile(alive) and (_t.time() - os.path.getmtime(alive) < 30)
        except OSError:
            return False

    if not _ok():
        _bs = _omni_batch()
        log_fn("⬆ Khởi động OmniVoice (giữ model warm — các lần sau khỏi load lại ~10s; batch %d theo VRAM)..." % _bs)
        env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        subprocess.Popen([OMNI_PY, OMNI_SCRIPT, "--serve", qdir, "--batch", str(_bs)], cwd=THU_MUC_GOC,
                         creationflags=_OMNI_NO_WIN, env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(200):        # chờ load model (lần đầu có thể lâu)
            if _ok():
                break
            _t.sleep(1)
        if not _ok():
            return False

    for m in ("_omnidone", "_omnierr"):     # dọn marker cũ
        try:
            os.remove(os.path.join(seg_dir, m))
        except OSError:
            pass
    reqid = "%d_%d" % (os.getpid(), int(_t.time() * 1000))
    req = {"texts": texts, "out_dir": seg_dir, "num_step": num_step, "ref": ref, "ref_text": ref_text,
           "instruct": instruct}
    tmp = os.path.join(qdir, "req_%s.json.tmp" % reqid)
    json.dump(req, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(tmp, os.path.join(qdir, "req_%s.json" % reqid))   # ghi ATOMIC (daemon khỏi đọc dở)
    log_fn("🎙 OmniVoice (daemon WARM, diffusion BATCH) — %d câu..." % len(texts))
    done = os.path.join(seg_dir, "_omnidone")
    err = os.path.join(seg_dir, "_omnierr")
    deadline = _t.time() + 1800     # tối đa 30 phút (video dài)
    while _t.time() < deadline:
        if os.path.isfile(done):
            return True
        if os.path.isfile(err):
            log_fn("⚠ Daemon OmniVoice báo lỗi job → lùi one-shot.")
            return False
        if not _ok():
            log_fn("⚠ Daemon OmniVoice mất tín hiệu → lùi one-shot.")
            return False
        _t.sleep(0.5)
    return False


def long_tieng_omnivoice(segs_vi, tong_giay, dub_wav, ref_audio=None, num_step=None, log_fn=log, instruct=None):
    """OmniVoice (k2-fsa, .venv_omnivoice, CẦN GPU): synth BATCH → seg wav → ghép đúng mốc.
    Ưu tiên DAEMON warm (khỏi load model mỗi lần); fallback one-shot.
    2 chế độ giọng: clone (ref_audio, NHẤT QUÁN tuyệt đối, chậm RTF~1.5) HOẶC Voice Design (instruct =
    "female, young adult, moderate pitch" → tạo giọng theo thuộc tính, NHANH RTF~0.5, không cần file mẫu).
    Tắt daemon bằng env OMNI_DAEMON=0. None nếu chưa cài/lỗi (caller fallback)."""
    if not (os.path.isfile(OMNI_PY) and os.path.isfile(OMNI_SCRIPT)):
        log_fn("⚠ Chưa cài OmniVoice (.venv_omnivoice) → bỏ OmniVoice.")
        return None
    thu_muc = os.path.dirname(os.path.abspath(dub_wav))
    seg_dir = os.path.join(thu_muc, "_omnisegs")
    os.makedirs(seg_dir, exist_ok=True)
    texts = [_chuan_hoa_tts(vi) for (st, en, (zh, vi)) in segs_vi]   # đọc đúng số/ngày/tiền
    ns = int(num_step or int(os.environ.get("OMNI_NS", "8")))
    if instruct:
        # VOICE DESIGN: tạo giọng theo thuộc tính (nhanh, không file mẫu). Thuộc tính giữ giọng nhất quán
        # (cùng giới tính/tuổi/cao độ mọi câu) — KHÔNG clone, KHÔNG default ref.
        ref = None
        rt = None
        log_fn("🎨 OmniVoice Voice Design: %s" % instruct)
    else:
        # CHỐNG "drift giọng" (auto bốc giọng ngẫu nhiên mỗi câu → nghe nhiều người): LUÔN clone từ 1 ref CỐ
        # ĐỊNH cho MỌI câu → 1 giọng nhất quán. User upload clone → dùng giọng đó; không → giọng mẫu mặc định.
        ref = ref_audio if (ref_audio and os.path.isfile(ref_audio)) else (
            OMNI_REF_MAC_DINH if os.path.isfile(OMNI_REF_MAC_DINH) else None)
        if ref:
            try:    # CẮT ref nếu quá dài — OmniVoice clone ưa 3-10s (community: ref dài = chậm + chất lượng kém)
                import cat_giong_clone
                if cat_giong_clone.thoi_luong(ref) > 12:
                    _rc = os.path.splitext(ref)[0] + "_omnicut.wav"
                    if not os.path.isfile(_rc):
                        cat_giong_clone.cat(ref, _rc, target=10.0, maxs=12.0)
                    if os.path.isfile(_rc):
                        ref = _rc
                        log_fn("✂ Cắt giọng mẫu OmniVoice về ~10s (tránh ref quá dài).")
            except Exception:
                pass
        rt = _ref_text_tu_audio(ref, log_fn=log_fn) if ref else None   # clone đẹp hơn khi có transcript mẫu

    ok = False
    # Daemon warm CHỈ đáng trên GPU đủ lớn (≥6GB): giữ OmniVoice + chạy ASR render sau cùng lúc. GPU nhỏ
    # (≤4GB) → daemon warm OOM (whisper/FunASR + OmniVoice >VRAM) + phá ASR render kế → ĐI THẲNG one-shot
    # (load mỗi render; nhanh hơn vì khỏi lần thử daemon load-rồi-crash ~70s). Ép daemon: OMNI_DAEMON=1.
    _ud = os.environ.get("OMNI_DAEMON")
    _dung_daemon = (_ud == "1") or (_ud != "0" and _vram_gb() >= 6.0)
    if _dung_daemon:
        try:
            ok = _omni_daemon_synth(seg_dir, texts, ns, ref, rt, log_fn, instruct=instruct)
        except Exception as e:
            log_fn("⚠ Daemon OmniVoice lỗi (%s) → one-shot." % str(e)[:60])
    if not ok:
        json.dump(texts, open(os.path.join(seg_dir, "texts.json"), "w", encoding="utf-8"), ensure_ascii=False)
        cmd = [OMNI_PY, OMNI_SCRIPT, "--texts", os.path.join(seg_dir, "texts.json"),
               "--out-dir", seg_dir, "--num-step", str(ns), "--batch", str(_omni_batch())]
        if ref:
            cmd += ["--ref", ref]
            if rt:
                cmd += ["--ref-text", rt]
        elif instruct:
            cmd += ["--instruct", instruct]
        log_fn("🎙 OmniVoice (one-shot, diffusion BATCH) — %d câu..." % len(texts))
        env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        proc = subprocess.Popen(cmd, cwd=THU_MUC_GOC, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", env=env)
        for line in proc.stdout:
            line = line.rstrip()
            if line.startswith("[omnivoice]"):
                log_fn(line)
        proc.wait()

    items = [(st, en, os.path.join(seg_dir, "seg_%d.wav" % i))
             for i, (st, en, (zh, vi)) in enumerate(segs_vi)]
    out = _ghep_track_khop(items, tong_giay, dub_wav, log_fn=log_fn)
    shutil.rmtree(seg_dir, ignore_errors=True)
    if not out:
        log_fn("⚠ OmniVoice không tạo được câu nào.")
        return None
    return out


def long_tieng_supertonic(segs_vi, tong_giay, dub_wav, voice=None, lang="en", log_fn=log):
    """Lồng tiếng bằng Supertonic-3 (ONNX, CPU; dùng cho đích Hàn/EN). MIRROR long_tieng_kokoro: ghi texts.json →
    subprocess supertonic_synth sinh seg_<i>.wav → _ghep_track_khop. voice = M1-M5/F1-F5; lang = đích (en/ko...).
    Trả dub_wav hoặc None (caller lùi edge-tts theo đích)."""
    voice = (voice or SUPERTONIC_VOICE_MAC_DINH).strip() or SUPERTONIC_VOICE_MAC_DINH
    # GUARD giọng: Supertonic chỉ nhận M1-M5/F1-F5. Giọng KHÁC lọt vào (vd default CLI 'vi-VN-HoaiMyNeural'
    # khi job không chỉ định voice) → get_voice_style vỡ → synth fail → rơi edge OAN. → ép về mặc định F1.
    if len(voice) != 2 or voice[0].upper() not in "MF" or voice[1] not in "12345":
        voice = SUPERTONIC_VOICE_MAC_DINH
    if not os.path.isfile(SUPERTONIC_PY) or not os.path.isfile(SUPERTONIC_SCRIPT):
        log_fn("⚠ Chưa cài Supertonic (python/script) → lùi edge-tts.")
        return None
    thu_muc = os.path.dirname(os.path.abspath(dub_wav))
    seg_dir = os.path.join(thu_muc, "_supertonicsegs")
    os.makedirs(seg_dir, exist_ok=True)
    # vi ở (zh, vi) = lời ĐÍCH (đã dịch sang Hàn/EN). Supertonic tự G2P — KHÔNG _chuan_hoa_tts (đó là chuẩn-hoá VN).
    texts = [(vi or "").strip() for (st, en, (zh, vi)) in segs_vi]
    json.dump(texts, open(os.path.join(seg_dir, "texts.json"), "w", encoding="utf-8"), ensure_ascii=False)
    log_fn("🎙 Lồng tiếng bằng Supertonic (%s, giọng %s) — %d câu..." % (lang, voice, len([t for t in texts if t])))
    cmd = [SUPERTONIC_PY, SUPERTONIC_SCRIPT, "--texts", os.path.join(seg_dir, "texts.json"),
           "--out-dir", seg_dir, "--voice", voice, "--lang", lang]
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    try:
        proc = subprocess.Popen(cmd, cwd=THU_MUC_GOC, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", env=env)
        for line in proc.stdout:
            line = line.rstrip()
            if line.startswith("[supertonic]"):
                log_fn(line)
        proc.wait()
    except Exception as e:
        log_fn("⚠ Supertonic lỗi (%s) → lùi edge-tts." % str(e)[:80])
        shutil.rmtree(seg_dir, ignore_errors=True)
        return None
    items = [(st, en, os.path.join(seg_dir, "seg_%d.wav" % i))
             for i, (st, en, (zh, vi)) in enumerate(segs_vi)]
    out = _ghep_track_khop(items, tong_giay, dub_wav, log_fn=log_fn)
    shutil.rmtree(seg_dir, ignore_errors=True)
    if not out:
        log_fn("⚠ Supertonic không tạo được câu nào → lùi edge-tts.")
        return None
    return out


def _tts_edge_wav(text, voice, out_wav, log_fn=log, tries=3):
    """Sinh 1 câu bằng edge-tts -> wav 24k mono. Trả True/False. Retry vì edge-tts hay 'No audio received'."""
    import asyncio
    import time
    import random
    # JITTER + BACKOFF MŨ (giảm 429/503): pool thread mở WebSocket gần như cùng lúc = burst → Microsoft dễ phạt.
    # EDGE_JITTER_MS: rải ngẫu nhiên 0..N ms TRƯỚC mỗi request để de-sync các worker (mặc định 150; =0 tắt).
    # EDGE_BACKOFF_BASE: giây cơ sở backoff MŨ giữa các lần thử (mặc định 1.5 → ~1.5/3/6s, cap 12s).
    try:
        _jit_ms = max(0, int(os.environ.get("EDGE_JITTER_MS", "150")))
    except ValueError:
        _jit_ms = 150
    try:
        _bo_base = max(0.0, float(os.environ.get("EDGE_BACKOFF_BASE", "1.5")))
    except ValueError:
        _bo_base = 1.5
    text = _chuan_hoa_tts((text or "").strip())   # số/ngày/tiền → chữ cho edge đọc đúng
    if not text:
        return False
    mp3 = out_wav + ".mp3"
    loi = ""
    try:
        import edge_tts
        from pydub import AudioSegment

        async def _save_co():
            # TIMEOUT cứng: edge-tts hay mở kết nối rồi 'treo' khi bị throttle (không nhả data, không lỗi)
            # → không bọc timeout thì asyncio.run kẹt VÔ HẠN, cả lồng tiếng đứng. Treo 30s = coi như rớt.
            await asyncio.wait_for(edge_tts.Communicate(text, voice).save(mp3), timeout=30)

        n_thu = max(1, tries)
        for lan in range(n_thu):     # thử `tries` lần; câu vẫn rớt thì vớt/gTTS lo (đỡ hammer kéo dài throttle)
            if _jit_ms:              # jitter TRƯỚC request → tách các worker khỏi bắn WebSocket cùng lúc
                time.sleep(random.uniform(0, _jit_ms) / 1000.0)
            try:
                asyncio.run(_save_co())
                if os.path.isfile(mp3) and os.path.getsize(mp3) > 100:
                    AudioSegment.from_file(mp3).set_frame_rate(24000).set_channels(1).export(out_wav, format="wav")
                    return True
            except Exception as e:
                loi = str(e)[:80]
            if lan < n_thu - 1:      # backoff MŨ + jitter giữa các lần thử (thay 2·n tuyến tính); cap 12s
                time.sleep(min(12.0, _bo_base * (2 ** lan)) + random.uniform(0, _jit_ms) / 1000.0)
        log_fn("⚠ edge-tts bỏ câu (No audio sau %d lần): " % n_thu + loi)
        return False
    finally:
        if os.path.isfile(mp3):
            try:
                os.remove(mp3)
            except OSError:
                pass


def _tts_gtts_wav(text, out_wav, lang="vi", log_fn=log):
    """Dự phòng: sinh 1 câu bằng gTTS (Google) -> wav 24k mono. Trả True/False.
    Dùng khi edge-tts liên tục 'No audio' (throttle IP) — gTTS hạ tầng khác edge nên ít trùng lỗi."""
    text = (text or "").strip()
    if not text:
        return False
    mp3 = out_wav + ".g.mp3"
    try:
        from gtts import gTTS
        from pydub import AudioSegment
        gTTS(text, lang=lang).save(mp3)
        if os.path.isfile(mp3) and os.path.getsize(mp3) > 100:
            AudioSegment.from_file(mp3).set_frame_rate(24000).set_channels(1).export(out_wav, format="wav")
            return True
    except Exception as e:
        log_fn("⚠ gTTS lỗi: " + str(e)[:80])
    finally:
        if os.path.isfile(mp3):
            try:
                os.remove(mp3)
            except OSError:
                pass
    return False


def long_tieng_edge(segs_vi, tong_giay, dub_wav, voice, log_fn=log):
    """Sinh giọng đích bằng edge-tts (cho đích KHÔNG phải tiếng Việt) rồi đặt đúng mốc thời gian.
    Trả đường dẫn dub_wav, hoặc None nếu không tạo được câu nào.
    edge-tts thuần network (KHÔNG dùng GPU/CPU nặng) → đọc SONG SONG cho nhanh (env EDGE_SONG_SONG,
    mặc định 4, có jitter+backoff mũ trong _tts_edge_wav để giảm 429/503). NỐI TIẾP (=1) đỡ throttle
    nhưng video nhiều câu (vài trăm) sẽ CỰC CHẬM/như treo ở
    bước lồng tiếng → KHÔNG để 1 làm mặc định. Câu rớt: VỚT lặp tới EDGE_VOT_VONG vòng NGAY sau lượt 1
    (không sleep — thời gian đọc các câu khác đã đủ để throttle nguội), giữ giọng edge đồng nhất. KHÔNG
    dùng gTTS bù (giọng khác edge → xen lẫn mất đồng bộ); câu edge vẫn thua → IM LẶNG."""
    seg_dir = os.path.join(os.path.dirname(os.path.abspath(dub_wav)), "_edgesegs")
    os.makedirs(seg_dir, exist_ok=True)
    import concurrent.futures
    # chỉ đọc câu có chữ; giữ theo index để ghép đúng thứ tự thời gian
    can_doc = [(i, st, en, _chuan_hoa_tts(vi)) for i, (st, en, (zh, vi)) in enumerate(segs_vi) if (vi or "").strip()]
    # 6 worker song song bắn request quá dày với video DÀI (2000+ câu) → Microsoft throttle IP →
    # "No audio received" rớt hàng loạt. Hạ mặc định 6→4 (chậm hơn chút nhưng ít burst → ít rớt trên video dài).
    try:
        songsong = max(1, int(os.environ.get("EDGE_SONG_SONG", "4")))
    except ValueError:
        songsong = 4
    _che_do = "nối tiếp" if songsong == 1 else f"song song {songsong}"
    log_fn(f"🎙 Lồng tiếng bằng edge-tts ({voice}) — {len(can_doc)} câu ({_che_do})...")
    items = {}   # i -> (st, en, seg)

    def _doc1(arg):
        i, st, en, vi = arg
        seg = os.path.join(seg_dir, f"seg_{i}.wav")
        return i, st, en, seg, _tts_edge_wav(vi, voice, seg, log_fn=log_fn)

    # ThreadPool: mỗi luồng tự chạy asyncio.run riêng trong _tts_edge_wav (an toàn);
    # network I/O nhả GIL nên các câu thật sự chạy đè lên nhau. ex.map giữ ĐÚNG thứ tự.
    if can_doc:
        with concurrent.futures.ThreadPoolExecutor(max_workers=songsong) as ex:
            for n, (i, st, en, seg, ok) in enumerate(ex.map(_doc1, can_doc), 1):
                if ok:
                    items[i] = (st, en, seg)
                if n % 5 == 0 or n == len(can_doc):
                    log_fn(f"   đọc {n}/{len(can_doc)}")
    # LƯỢT VỚT cuối (user chốt "chạy hết 1 lần, câu nào rớt thì QUAY LẠI SAU"): các câu rớt được gom lại
    # xử NGAY sau lượt 1 — KHÔNG sleep chặn. Lý do: thời gian đọc HÀNG TRĂM câu khác ở lượt 1 ĐÃ đủ để
    # throttle IP nguội tự nhiên → vớt lại ăn ngay, khỏi tốn thời gian nghỉ. Lặp tới MAX vòng, mỗi vòng
    # câu rớt ít dần (throttle càng nguội). GIỮ GIỌNG EDGE đồng nhất — KHÔNG gTTS (giọng khác → xen lẫn
    # mất đồng bộ, user chốt bỏ). Câu nào edge vẫn thua sau hết vòng → IM LẶNG (đồng nhất hơn giọng lạ).
    # EDGE_VOT=0 tắt vớt; EDGE_VOT_VONG = số vòng vớt tối đa (mặc định 3).
    if os.environ.get("EDGE_VOT", "1") != "0" and items:
        try:
            max_vong = max(1, int(os.environ.get("EDGE_VOT_VONG", "3")))
        except ValueError:
            max_vong = 3

        def _vot1(arg):
            i, st, en, vi = arg
            seg = os.path.join(seg_dir, f"seg_{i}.wav")
            return i, st, en, seg, _tts_edge_wav(vi, voice, seg, log_fn=lambda m: None, tries=2)
        for _v in range(max_vong):
            rot = [(i, st, en, vi) for (i, st, en, vi) in can_doc if i not in items]
            if not rot:
                break
            log_fn(f"↻ {len(rot)} câu rớt → vớt lại edge-tts (vòng {_v + 1}/{max_vong}, giữ giọng đồng nhất)...")
            _truoc = len(items)
            with concurrent.futures.ThreadPoolExecutor(max_workers=songsong) as ex:
                for (i, st, en, seg, ok) in ex.map(_vot1, rot):
                    if ok:
                        items[i] = (st, en, seg)
            if len(items) == _truoc:   # vòng này KHÔNG vớt thêm được câu nào → IP chết hẳn, vớt tiếp vô ích
                break
    co_text = len(can_doc)
    roi = co_text - len(items)
    if roi > 0:
        log_fn(f"⚠ Rớt {roi}/{co_text} câu (edge-tts không đọc được — các câu này sẽ IM LẶNG để giữ giọng đồng nhất).")
    else:
        log_fn(f"✔ Đọc đủ {len(items)} câu (edge-tts, giọng đồng nhất).")
    items_list = [items[i] for i in sorted(items)]   # đúng thứ tự thời gian
    out = _ghep_track_khop(items_list, tong_giay, dub_wav, log_fn=log_fn)
    shutil.rmtree(seg_dir, ignore_errors=True)
    if not out:
        log_fn("⚠ edge-tts không tạo được câu nào → bỏ lồng tiếng.")
        return None
    return out


# CACHE Piper (giữ NÓNG qua nhiều render trong Persistent Worker — KHÔNG load lại model mỗi video).
# voice = bản ĐƠN (multi-core, nhánh tuần tự); pool = N bản intra_op=1 (nhánh song song). Key theo model_path.
_PIPER_CACHE = {}
_PIPER_LOCK = __import__("threading").Lock()


def _piper_voice(model_path, log_fn=log):
    """PiperVoice ĐƠN (multi-core) cho nhánh tuần tự — CACHE theo model_path (giữ nóng qua render)."""
    with _PIPER_LOCK:
        c = _PIPER_CACHE.setdefault(model_path, {})
        if c.get("voice") is None:
            from piper import PiperVoice
            c["voice"] = PiperVoice.load(model_path)
            log_fn("🔥 Piper nạp giọng vào cache: %s" % os.path.basename(model_path))
        return c["voice"]


def _piper_shared(model_path, log_fn=log):
    """1 PiperVoice (onnx session intra_op=1) CHIA SẺ qua N luồng cho nhánh SONG SONG — CACHE theo model_path.
    onnx Run() thread-safe + espeak phonemize serialize qua GIL → ĐO THẬT audio KHÔNG vỡ (dur share≈tuần tự),
    synth 0.20s/câu (≈ pool). Build CHỈ 1 session (~17s) thay pool N (~84s, mỗi InferenceSession ~8s) + RAM 1×."""
    import onnxruntime as _ort
    from piper import PiperVoice
    with _PIPER_LOCK:
        c = _PIPER_CACHE.setdefault(model_path, {})
        if c.get("shared") is None:
            v = PiperVoice.load(model_path)
            _so = _ort.SessionOptions(); _so.intra_op_num_threads = 1; _so.inter_op_num_threads = 1
            v.session = _ort.InferenceSession(model_path, sess_options=_so, providers=["CPUExecutionProvider"])
            c["shared"] = v
            log_fn("🔥 Piper 1 session chia sẻ (intra_op=1) vào cache")
        return c["shared"]


def long_tieng_piper(segs_vi, tong_giay, dub_wav, model_path=None, chuan_hoa=True, log_fn=log):
    """Lồng tiếng bằng Piper (ONNX, OFFLINE, VÔ HẠN, ~8x realtime CPU). Nạp model 1 lần, sinh tuần tự.
    Mỗi câu -> wav 24k mono (khớp _ghep_track_khop). Trả dub_wav, hoặc None nếu chưa cài/thiếu giọng.
    chuan_hoa=True: áp _chuan_hoa_tts (chuẩn-hoá số/ngày/tiền kiểu VIỆT) — CHỈ cho giọng VN. Giọng Piper TIẾNG
    ANH (lessac/ryan...) phải chuan_hoa=False (để phonemizer tiếng Anh tự đọc số kiểu Anh, không ép Hán-Việt)."""
    model_path = model_path or PIPER_VOICE_MAC_DINH
    try:
        import wave as _wave
        from piper import PiperVoice
    except Exception as e:
        log_fn("⚠ Chưa cài piper-tts (%s) → bỏ Piper." % str(e)[:60])
        return None
    if not os.path.isfile(model_path):
        ten_giong = os.path.splitext(os.path.basename(model_path))[0]
        os.makedirs(PIPER_DIR, exist_ok=True)
        if ten_giong == "banmai":
            # Banmai (NghiTTS) KHÔNG có trong registry piper → tải riêng (partial từ GitHub Release VNTTS).
            try:
                import tai_banmai
                tai_banmai.tai(log_fn=log_fn)
            except Exception as e:
                log_fn("⚠ Tải Banmai lỗi (%s)." % str(e)[:60])
            if not os.path.isfile(model_path):     # tải Banmai fail → lùi giọng chuẩn vais1000
                model_path = os.path.join(PIPER_DIR, "vi_VN-vais1000-medium.onnx")
                ten_giong = "vi_VN-vais1000-medium"
                log_fn("ℹ Lùi giọng Piper mặc định (vais1000).")
        else:
            # Giọng NghiTTS (ngochuyen mặc định / maiphuong / manhdung...) KHÔNG có trong registry piper
            # → tải qua giong_piper (gdown, CÙNG PIPER_DIR). Bảo đảm default Ngọc Huyền tự tải trên máy khách.
            try:
                import giong_piper as _gp
                if ten_giong in _gp.GIONG:
                    _gp.tai(ten_giong, log_fn=log_fn)
            except Exception as e:
                log_fn("⚠ Tải giọng '%s' lỗi (%s)." % (ten_giong, str(e)[:60]))
        if not os.path.isfile(model_path):
            # Giọng có trong registry piper → tải 1 lần (cần mạng lần đầu, sau offline mãi).
            log_fn(f"⬇ Chưa có giọng Piper '{ten_giong}' → tải về {PIPER_DIR} (1 lần)...")
            subprocess.run([sys.executable, "-m", "piper.download_voices", ten_giong,
                            "--data-dir", PIPER_DIR], capture_output=True)
        if not os.path.isfile(model_path):
            log_fn("⚠ Tải giọng Piper thất bại → bỏ Piper.")
            return None
    seg_dir = os.path.join(os.path.dirname(os.path.abspath(dub_wav)), "_pipersegs")
    os.makedirs(seg_dir, exist_ok=True)
    can_doc = [(i, st, en, (_chuan_hoa_tts(vi) if chuan_hoa else (vi or "").strip()))
               for i, (st, en, (zh, vi)) in enumerate(segs_vi) if (vi or "").strip()]
    log_fn(f"🎙 Lồng tiếng bằng Piper (offline, vô hạn) — {len(can_doc)} câu...")
    try:
        voice = _piper_voice(model_path, log_fn)   # CACHE: giữ nóng giọng qua nhiều render (worker bền)
    except Exception as e:
        log_fn("⚠ Nạp model Piper lỗi (%s) → bỏ Piper." % str(e)[:80])
        return None
    # SONG SONG hoá (đo thật ~1.29× ở 4 luồng cho video DÀI; audio verify NGHE = tuần tự, không vỡ tiếng):
    # POOL N PiperVoice RIÊNG, mỗi cái onnx intra_op=1 (1 synth = 1 nhân → KHÔNG oversubscribe onnx; nếu để
    # multi-thread mặc định × N luồng = chậm hơn). espeak có trạng thái GLOBAL nên KHÔNG share 1 model.
    # Ít câu (<24) / PIPER_WORKERS=1 → tuần tự (đỡ phí load N model). items[i] theo INDEX → thứ tự đúng dù song song.
    import threading as _th, queue as _q
    # POOL N giọng (mỗi bản onnx intra_op=1) cho RENDER NHIỀU (batch). ĐO THẬT laptop 16 lõi (instrument TTS-split):
    # - synth pool-6 = 0.16s/câu vs 1-giọng-multicore 0.5s/câu → pool nhanh ~3×. intra_op=1 BẮT BUỘC: bỏ nó →
    #   6 bản multi-core OVERSUBSCRIBE (96 luồng/16 lõi) → 0.76s/câu (CHẬM hơn cả 1 giọng).
    # - build pool 6 bản ~84s (tạo session sau càng chậm) NHƯNG cache _piper_pool giữ qua render → CHỈ trả 1
    #   lần/worker (render-2+ build=0). Hoà vốn ~7 render; batch render-2+ synth 5s vs 18s → pool thắng ~2.3×.
    # Render LẺ (ít video) → đặt PIPER_WORKERS=1 để khỏi 84s build đầu. <24 câu vẫn tuần tự (1 giọng, đỡ phí).
    try:
        _nw = int(os.environ.get("PIPER_WORKERS", "") or min((os.cpu_count() or 4), 6))
    except ValueError:
        _nw = min((os.cpu_count() or 4), 6)
    _nw = max(1, min(_nw, len(can_doc)))
    items = {}
    _ilock = _th.Lock()
    _cnt = [0]
    # Tốc độ đọc Piper (length_scale): <1 = đọc NHANH hơn. Mặc định 0.9 (đo thật: nhanh ~5-8% vẫn rõ/tự nhiên
    # trên Banmai; <0.7 mới méo) → giọng đỡ TRÀN khe → bớt phải catch-up nén → bám phụ đề tự nhiên hơn.
    # Chỉnh/tắt qua env DUB_PIPER_SPEED (1.0 = tốc độ gốc, 0.85 = nhanh hơn chút).
    try:
        _pls = float(os.environ.get("DUB_PIPER_SPEED", "0.9"))
    except ValueError:
        _pls = 0.9
    _syn = None
    if abs(_pls - 1.0) > 1e-6:
        try:
            from piper import SynthesisConfig as _SC
            _syn = _SC(length_scale=_pls)
        except Exception:
            _syn = None

    def _synth1(i, st, en, vi, seg, v):
        # Ghi THẲNG wav Piper (bỏ ffmpeg/câu) — _ghep_track_khop tự resample 24k mono khi ghép
        with _wave.open(seg, "wb") as w:
            if _syn is not None:
                v.synthesize_wav(vi, w, syn_config=_syn)
            else:
                v.synthesize_wav(vi, w)
        if os.path.isfile(seg) and os.path.getsize(seg) > 100:
            with _ilock:
                items[i] = (st, en, seg)

    import time as _t
    _t_synth0 = _t.time()
    if _nw <= 1 or len(can_doc) < 24:
        for n, (i, st, en, vi) in enumerate(can_doc, 1):
            seg = os.path.join(seg_dir, f"seg_{i}.wav")
            try:
                _synth1(i, st, en, vi, seg, voice)
            except Exception as e:
                log_fn("⚠ Piper bỏ câu %d (%s)" % (i, str(e)[:60]))
            if n % 20 == 0 or n == len(can_doc):
                log_fn(f"   đọc {n}/{len(can_doc)}")
    else:
        _vsh = _piper_shared(model_path, log_fn)   # 1 session CHIA SẺ N luồng (thay pool N) — build ~17s ko 84s
        log_fn(f"   (song song {_nw} luồng, 1 session chia sẻ)")

        def _work(arg):
            i, st, en, vi = arg
            try:
                seg = os.path.join(seg_dir, f"seg_{i}.wav")
                _synth1(i, st, en, vi, seg, _vsh)   # tất cả luồng dùng CHUNG _vsh (đã test audio không vỡ)
            except Exception as e:
                log_fn("⚠ Piper bỏ câu %d (%s)" % (i, str(e)[:60]))
            with _ilock:
                _cnt[0] += 1
                if _cnt[0] % 40 == 0 or _cnt[0] == len(can_doc):
                    log_fn(f"   đọc {_cnt[0]}/{len(can_doc)}")
        with ThreadPoolExecutor(max_workers=_nw) as _ex:
            list(_ex.map(_work, can_doc))
    items_list = [items[i] for i in sorted(items)]
    _t_synth = _t.time() - _t_synth0
    _t_str0 = _t.time()
    out = _ghep_track_khop(items_list, tong_giay, dub_wav, log_fn=log_fn)
    _t_str = _t.time() - _t_str0
    # ĐO TTS-split: synth (Piper) vs stretch+ghép (_ghep_track_khop) → biết 115s nằm ở synth hay stretch.
    _n = max(1, len(can_doc))
    log_fn("⏱ TTS-split: synth %.1fs (%.2fs/câu) | stretch+ghép %.1fs (%.2fs/câu) | %d câu × %d luồng"
           % (_t_synth, _t_synth / _n, _t_str, _t_str / _n, len(can_doc), _nw))
    try:
        _pl = os.environ.get("VC_PROFILE_LOG")
        if _pl:
            import json as _j
            with open(_pl, "a", encoding="utf-8") as _f:
                _f.write(_j.dumps({"t": int(_t.time()), "tts": {
                    "engine": "piper", "synth": round(_t_synth, 1), "stretch_concat": round(_t_str, 1),
                    "segs": len(can_doc), "nw": _nw, "audio_sec": round(float(tong_giay or 0), 1),
                    "synth_per": round(_t_synth / _n, 2), "stretch_per": round(_t_str / _n, 2)}},
                    ensure_ascii=False) + "\n")
    except Exception:
        pass
    shutil.rmtree(seg_dir, ignore_errors=True)
    if not out:
        log_fn("⚠ Piper không tạo được câu nào → bỏ lồng tiếng.")
        return None
    return out


# (VieNeu-TTS đã GỠ — engine không khả dụng: tokenizer ModelScope 404 + chậm CPU. Dùng Piper/edge/OmniVoice.)


# ---------------- Tách giọng/nhạc (demucs, tùy chọn — nặng) ----------------
def tach_demucs(audio_wav, log_fn=log):
    """Tách 2 stem qua subprocess riêng (_demucs_worker.py) — PyTorch + model unload ngay khi xong.
    Trả (giong_wav, nhac_wav) — '' nếu lỗi."""
    worker = os.path.join(THU_MUC_GOC, "_demucs_worker.py")
    out_dir = os.path.join(os.path.dirname(audio_wav), "_demucs")
    os.makedirs(out_dir, exist_ok=True)
    log_fn("🎚 Đang tách giọng/nhạc (demucs — chậm nếu không GPU)...")
    kq = subprocess.run([sys.executable, worker, audio_wav, out_dir],
                        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if kq.returncode == 2:
        # exit(2) = ImportError (chưa cài demucs/soundfile)
        log_fn("⚠ Thiếu demucs/soundfile → bỏ tách giọng. (%s)" % (kq.stdout or kq.stderr or "")[:80])
        return "", ""
    if kq.returncode != 0:
        log_fn("⚠ demucs lỗi: " + (kq.stderr or "")[-200:])
        return "", ""
    giong = nhac = ""
    for line in kq.stdout.splitlines():
        if line.startswith("GIONG:"):
            giong = line[6:]
        elif line.startswith("NHAC:"):
            nhac = line[5:]
    return giong, nhac


def tach_nhac(audio_wav, log_fn=log):
    """(Tương thích cũ) Trả riêng đường dẫn nhạc nền (no_vocals)."""
    return tach_demucs(audio_wav, log_fn=log_fn)[1]


def tron_audio(dub_wav, nen_wav, out_wav, nen_giam_db=0.0):
    """Trộn track lồng tiếng đè lên nền (nhạc nền sạch hoặc tiếng gốc đã giảm âm).
    (Giọng dub ĐÃ được chuẩn hoá độ vang loudnorm ở khâu giong_vol phía trên — ở đây chỉ đè + fallback đỉnh.)"""
    from pydub import AudioSegment
    dub = AudioSegment.from_file(dub_wav).set_frame_rate(44100).set_channels(2)
    try:
        dub = dub.normalize(headroom=1.0)   # fallback nếu loudnorm khâu trên không chạy — vô hại nếu đã loudnorm
    except Exception:
        pass
    nen = AudioSegment.from_file(nen_wav).set_frame_rate(44100).set_channels(2)
    if nen_giam_db:
        nen = nen + nen_giam_db   # giảm âm nền (db âm)
    out = nen.overlay(dub)
    out.export(out_wav, format="wav")
    return out_wav


# ---------------- Luồng chính ----------------
class _ResMon:
    """Lấy mẫu CPU%/RAM%/GPU%/VRAM nền (dep-free: ctypes Windows/thong_tin_may + nvidia-smi — venv
    production KHÔNG có psutil/pynvml) → biết tài nguyên nào RẢNH mỗi stage (quyết overlap được không).
    Hỏng/thiếu → None, KHÔNG ảnh hưởng render."""
    def __init__(self):
        self.samples = []      # [(t, cpu%, ram%, gpu%, vram_mb)]
        self._stop = False
        self._cpu_theo_doi = thong_tin_may.TheoDoiCpu()
    def _cpu_ram(self):
        return self._cpu_theo_doi.phan_tram(), thong_tin_may.ram_pct_dung()
    def _gpu(self):
        try:
            r = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used",
                                "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=4)
            a = (r.stdout or "").strip().splitlines()[0].split(",")
            return float(a[0]), float(a[1])
        except Exception:
            return None, None
    def _loop(self):
        import time as _t2
        self._cpu_ram()                       # mồi prev cho CPU delta
        while not self._stop:
            _t2.sleep(2.5)
            c, r = self._cpu_ram(); g, v = self._gpu()
            self.samples.append((_t2.time(), c, r, g, v))
    def start(self):
        try:
            import threading
            threading.Thread(target=self._loop, daemon=True).start()
        except Exception:
            pass
    def stop(self):
        self._stop = True
    def avg(self, t0, t1):
        xs = [s for s in self.samples if t0 <= s[0] <= t1]
        def _a(idx):
            v = [s[idx] for s in xs if s[idx] is not None]
            return round(sum(v) / len(v)) if v else None
        vr = [s[4] for s in xs if s[4] is not None]
        return {"cpu": _a(1), "ram": _a(2), "gpu": _a(3), "vram": round(max(vr)) if vr else None}


def chay(video, model_size="medium", che_chu=True, che_khac=False, burn=True,
         lam_long_tieng=False, lam_tach_nhac=False, voice="vi-VN-HoaiMyNeural",
         engine="google", srt_co_san=None, tach_truoc=False, ref_audio=None,
         src_lang=None, tts_engine="edge", log_fn=log,
         extra_vf=None, speed=1.0, wm_path=None, wm_pos="20:20", wm_scale="",
         bg_path=None, bg_vol=0.25, tat_tieng_goc=False, goc_vol=None, chi_asr=False,
         che_band_manual=None, dich_lai=False, giong_vol=None, af_loc="",
         logo=None, text_wm=None, blur_boxes=None, chi_dich=False, chi_dub=False,
         phude_style="default"):
    # chi_dich=True (TRANSLATE-PREFETCH): OCR(cache)→dịch→ghi vi.srt (+ trans-cache) rồi DỪNG (không dò-dải/
    # dub/encode). Để prefetch dịch NGÔN NGỮ KẾ trong lúc video hiện tại đang lồng tiếng (dịch mạng ∥ dub CPU).
    # chi_dub=True (SPLIT DUB↔ENCODE): OCR+dịch(cache)→DUB→lưu dub-cache (.dub.wav + .dubmeta.json = onsets/warp/
    # slow) rồi DỪNG (KHÔNG mux/encode). Encode-phase (job kế) HIT dub-cache + restore 3 global → burn khớp hình-tiếng.
    # dich_lai=True ("Render TỪ ĐẦU"): BỎ QUA cache lookup srt+dub → nghe+dịch+lồng tiếng MỚI (vẫn LƯU
    # đè cache để lần reuse sau dùng bản mới). KEY vẫn tính bình thường để bước lưu hoạt động.
    # chi_asr=True (DỊCH THỦ CÔNG): chỉ chạy ASR → ghi phụ đề GỐC (zh.srt) rồi DỪNG (không dịch/lồng/ghép),
    # để người dùng tự dịch (ChatGPT/Gemini) rồi nhập lại qua srt_co_san ở lượt sau.
    if not os.path.isfile(video):
        log_fn("⚠ Không thấy file video: " + video)
        return None
    # Video dài > 5 phút + model lớn → tự giảm xuống medium để tiết kiệm RAM & thời gian
    _LARGE_MODELS = {"large", "large-v1", "large-v2", "large-v3", "large-v3-turbo"}
    if model_size in _LARGE_MODELS:
        _dur_raw = _thoi_luong(video) or 0
        if _dur_raw > 300:
            log_fn(f"ℹ Video {_dur_raw/60:.1f} phút → dùng model 'medium' thay '{model_size}' (tiết kiệm RAM).")
            model_size = "medium"
    # AUTO CHE WATERMARK NGUỒN (dò dai_watermark rồi tự blur/che) ĐÃ GỠ — nhận diện dễ NHẦM: blur đè lên
    # nội dung chính thay vì logo nguồn (đã gặp thật: che nửa người mẫu). Chỉ giữ logo/blur user TỰ đặt tay
    # (có toạ độ x/y/w/h trong tab Edit) — đi thẳng vào burn_kw dưới, KHÔNG auto-dò gì.
    # Biến đổi hình (lật/màu/watermark/nhạc nền) + tăng tốc được GỘP vào lần encode burn cuối
    # (thay vì encode riêng B1/B3) — xem burn_phude. ASR vẫn chạy trên `video` tốc độ gốc.
    burn_kw = dict(extra_vf=extra_vf, speed=speed, wm_path=wm_path, wm_pos=wm_pos,
                   wm_scale=wm_scale, bg_path=bg_path, bg_vol=bg_vol,
                   logo=logo, text_wm=text_wm, blur_boxes=blur_boxes)
    globals()["_LAST_VIDEO_SLOW"] = 1.0   # reset: chỉ _ghep_track_khop (dub MỚI) mới đặt S; cache-hit/no-dub → 1.0
    globals()["_LAST_TIME_WARP"] = None   # reset warp per-segment (tránh dùng lại warp cũ ở cache-hit/no-dub)
    globals()["_LAST_DUB_ONSETS"] = None  # reset bản đồ vị-trí dub (cache-hit/no-dub → giữ phụ đề gốc, không căn nhầm)
    # PROFILING + _tg ĐỊNH NGHĨA SỚM (trước nhánh cache) → cache-hit vẫn có _tg/_RES/_PROF (fix UnboundLocalError).
    # ĐO THỜI GIAN TỪNG STAGE (tìm nút thắt render dài): log "⏱ <stage>: Ns" sau mỗi pha.
    import time as _tm
    _TG = [_tm.time()]
    _PROF_T0 = _tm.time()
    _PROF_STAGES = []     # [(stage, giây)] → ghi jsonl cuối render để tích luỹ qua NHIỀU video
    # set sớm để dich_gemini_web (chạy lúc dịch, cùng process) ghi GEMPROF vào CÙNG file
    os.environ.setdefault("VC_PROFILE_LOG", os.path.join(
        os.environ.get("MC_DATA_DIR") or THU_MUC_GOC, "_render_profile.jsonl"))
    _RES = _ResMon(); _RES.start()   # đo CPU/GPU/RAM/VRAM mỗi stage → biết tài nguyên rảnh (overlap?)
    def _tg(_nhan):
        _n = _tm.time(); _d = _n - _TG[0]; _r = _RES.avg(_TG[0], _n)
        log_fn("⏱ %s: %.1fs · cpu%s%% gpu%s%% ram%s%% vram%sMB"
               % (_nhan, _d, _r["cpu"], _r["gpu"], _r["ram"], _r["vram"]))
        _PROF_STAGES.append((_nhan, round(_d, 1), _r)); _TG[0] = _n
    # TODO(cache): dub cache CHƯA lưu S → nếu Assist bật + dub cache-hit, video sẽ KHÔNG slow khớp. Demo dùng
    # dich_lai (fresh) nên đúng; trước khi bật mặc định cần đưa maxslow vào _dub_key + lưu S theo cache.
    co_extra_hinh = bool(extra_vf or wm_path or bg_path or abs(float(speed or 1.0) - 1.0) > 1e-6)
    import ngon_ngu
    tgt = ngon_ngu.target_lang()
    plat = ngon_ngu.platform_tu_duong_dan(video)
    if src_lang is None and srt_co_san:
        src_lang = "zh"   # B5: có SRT dịch sẵn = luồng zh→vi (dịch thủ công) → ép zh, KHÔNG suy theo tên file
    if src_lang is None:
        # DÒ qua TÊN FILE: có chữ Hán = CHẮC CHẮN tiếng Trung (đường nhanh, khỏi dò audio).
        if _co_chu_han(os.path.basename(video)):
            src_lang = "zh"
        else:
            # Tên KHÔNG có chữ Hán → CHƯA chắc nguồn: có thể là video Trung USER TỰ UPLOAD (tên tiếng
            # Việt/Anh), hoặc tên cào đã dịch, hoặc video Việt/Anh thật. Suy tạm theo nền tảng, mặc định = đích.
            src_lang = ngon_ngu.nguon_theo_nen_tang(plat) if plat else tgt
            # Nếu định LỒNG TIẾNG → DÒ NGÔN NGỮ NÓI THẬT bằng ASR (~vài giây, chỉ khi cần lồng tiếng):
            #  • BẮT video tiếng Trung dù tên KHÔNG có chữ Hán (vd user tự upload, hoặc tên đã dịch) → cho
            #    lồng tiếng (TRƯỚC ĐÂY bị bỏ oan vì chỉ dò khi nền tảng=zh; video upload không có nền tảng).
            #  • Tránh đè 2 giọng cho video Việt/Anh (lọt folder Trung hoặc user thêm nhầm).
            if lam_long_tieng:
                _lang_that, _lang_prob = _do_ngon_ngu_noi(video, log_fn=log_fn)
                if _lang_that:
                    if _la_tieng_trung(_lang_that):
                        if src_lang != "zh":
                            log_fn("🎧 ASR dò nguồn NÓI = tiếng Trung (dù tên file không có chữ Hán) → BẬT lồng tiếng.")
                        src_lang = "zh"
                    elif _la_tieng_trung(src_lang) and _lang_prob < 0.70:
                        # Nền tảng = Trung NHƯNG ASR (whisper 'tiny', 25s) dò ra ngôn ngữ khác với ĐỘ TIN THẤP
                        # → KHÔNG tin (clip ngắn/nhạc/lẫn tiếng dễ sai) → GIỮ tiếng Trung + VẪN lồng tiếng.
                        # (Trước: top-guess tiny ghi đè thẳng → video Trung bị tưởng 'en' → render rỗng/sai.)
                        log_fn("🎧 ASR dò '%s' (prob %.2f) CHƯA chắc + nền tảng=Trung → giữ tiếng Trung, vẫn lồng tiếng." % (_lang_that, _lang_prob))
                    else:
                        if _la_tieng_trung(src_lang):
                            log_fn("🎧 ASR dò nguồn NÓI = '%s' (prob %.2f, KHÔNG phải tiếng Trung) → bỏ lồng tiếng (tránh đè 2 giọng)." % (_lang_that, _lang_prob))
                        src_lang = _lang_that
    # CHỈ TIẾNG TRUNG mới DỊCH + LỒNG TIẾNG. Nguồn khác → chỉ PHỤ ĐỀ GỐC bằng whisper, KHÔNG dịch,
    # KHÔNG lồng tiếng (reup video Việt/Anh chỉ cần phụ đề, cần gì lồng).
    cung_ngon_ngu = (src_lang != "zh") or (src_lang == tgt)
    if cung_ngon_ngu and lam_long_tieng:
        lam_long_tieng = False
        if src_lang != "zh":
            burn = True   # đảm bảo VẪN xuất phụ đề gốc cho video không-tiếng-Trung
            log_fn("ℹ Nguồn KHÔNG phải tiếng Trung (tên file → %s) → tắt lồng tiếng, chỉ phụ đề gốc (whisper, không dịch)." % src_lang)
        else:
            log_fn("ℹ Nguồn đã cùng ngôn ngữ đích (%s) — bỏ lồng tiếng, chỉ phụ đề/né bản quyền." % tgt)
    thu_muc = os.path.dirname(os.path.abspath(video))
    ten = os.path.splitext(os.path.basename(video))[0]
    zh_srt = os.path.join(thu_muc, ten + ".zh.srt")
    vi_srt = os.path.join(thu_muc, ten + ".vi.srt")
    nhac_da_tach = ""   # nếu tách trước ASR thì giữ lại nhạc nền để dùng cho lồng tiếng

    # === CACHE artifact (lossless): tái dùng phụ đề/giọng đã sinh cho lần xử lý LẶP cùng video. ===
    # NGHI NGỜ → MISS (cache lỗi KHÔNG được làm hỏng render). KHÔNG đè srt_co_san do USER truyền.
    import cache_artifact as _ca
    _vhash = _ca.video_hash(video)
    # SCAN-CACHE key = TÁCH khỏi ngôn ngữ đích: chỉ gồm tham số ảnh hưởng NGHE/OCR + dedup (KHÔNG tgt/engine-dịch)
    # → đổi ngôn ngữ đích (vi↔en↔th...) vẫn HIT scan → bỏ ASR/OCR nặng, chỉ dịch + lồng tiếng lại theo ngôn ngữ mới.
    # VHASH cho SCAN: ưu tiên VC_SCAN_VHASH (seed ỔN ĐỊNH gốc+transform do xu_ly_chon đặt khi pre-encode) — vì OCR
    # chạy trên TEMP đã transform, video_hash(temp) đổi mtime mỗi ngôn ngữ → nếu dùng nó thì scan MISS + OCR lặp.
    _vhash_scan = os.environ.get("VC_SCAN_VHASH") or _vhash
    _scan_key = _ca.tinh_key("scan", _vhash=_vhash_scan, model=model_size, src=(src_lang or ""),
                             tach_truoc=bool(tach_truoc), e_asr=os.environ.get("ASR_ENGINE", ""),
                             e_ocrfps=os.environ.get("OCR_FPS", ""), e_funseg=os.environ.get("FUNASR_MAX_SEG", ""),
                             e_destutter=os.environ.get("DUB_DESTUTTER", ""),
                             e_cheocr=os.environ.get("CHE_OCR", "")) if _vhash_scan else None
    # TRANS-CACHE (dịch): key = SCAN-SEED (ổn định qua temp-mtime) + tgt + engine + tham số ảnh hưởng bản dịch
    # → prefetch (chi_dich) dịch ngôn ngữ B lưu vi.srt; render CHÍNH của B HIT → BỎ dịch (dịch mạng ∥ dub CPU).
    _trans_key = _ca.tinh_key(
        "trans", _vhash=_vhash_scan, model=model_size, src=(src_lang or ""), engine=engine, tgt=tgt,
        tach_truoc=bool(tach_truoc), e_asr=os.environ.get("ASR_ENGINE", ""),
        e_nhanh=(os.environ.get("AI_DICH_NHANH", "") if engine == "ai" else ""),
        e_reflect=(os.environ.get("VL_REFLECT", "") if engine == "ai" else ""),
        e_ocrfps=os.environ.get("OCR_FPS", ""), e_funseg=os.environ.get("FUNASR_MAX_SEG", ""),
        e_cheocr=os.environ.get("CHE_OCR", "")) if (_vhash_scan and not srt_co_san and not chi_asr) else None
    _srt_key = None
    if _vhash and not srt_co_san and not chi_asr:
        try:
            _srt_key = _ca.tinh_key(
                "srt", _vhash=_vhash, model=model_size, src=src_lang, engine=engine, tgt=tgt,
                tach_truoc=bool(tach_truoc),
                e_asr=os.environ.get("ASR_ENGINE", ""),
                e_nhanh=(os.environ.get("AI_DICH_NHANH", "") if engine == "ai" else ""),
                e_reflect=(os.environ.get("VL_REFLECT", "") if engine == "ai" else ""),  # bật/tắt reflect → đổi vi.srt
                e_ocrfps=os.environ.get("OCR_FPS", ""),
                e_funseg=os.environ.get("FUNASR_MAX_SEG", ""),
                e_chedai=os.environ.get("CHE_DAI", ""),
                e_chedaitren=os.environ.get("CHE_DAI_TREN", ""),
                e_cheocr=os.environ.get("CHE_OCR", ""))
            _pv = (None if dich_lai else _ca.lay(_srt_key, ".vi.srt"))   # dich_lai → bỏ qua lookup (vẫn lưu đè sau)
            if _pv:
                shutil.copyfile(_pv, vi_srt)
                _pz = _ca.lay(_srt_key, ".zh.srt")
                if _pz:
                    shutil.copyfile(_pz, zh_srt)
                srt_co_san = vi_srt   # bơm → nhánh dưới tự BỎ QUA ASR + dịch
                log_fn("[CACHE HIT srt] Dùng lại phụ đề đã dịch — bỏ qua nghe + dịch.")
        except Exception as _e:
            log_fn("ℹ Cache srt bỏ qua (%s)." % str(_e)[:60])
    # TRANS-CACHE lookup: _srt_key MISS (temp-mtime khác) nhưng prefetch đã dịch (key scan-seed ỔN ĐỊNH) → HIT
    # → dùng vi.srt đã dịch, bỏ OCR + dịch (nhánh srt_co_san dưới lo). Chỉ khi CHƯA có srt_co_san + không dich_lai.
    if _trans_key and not srt_co_san and not dich_lai and not chi_asr:
        try:
            _ptv = _ca.lay(_trans_key, ".vi.srt")
            if _ptv:
                shutil.copyfile(_ptv, vi_srt)
                srt_co_san = vi_srt
                log_fn("[CACHE HIT trans] Dùng lại bản DỊCH đã prefetch — bỏ nghe + dịch.")
        except Exception:
            pass

    if srt_co_san and os.path.isfile(srt_co_san):
        # Ghép lại từ phụ đề ĐÃ SỬA — bỏ qua nhận dạng + dịch
        segs_vi = [(st, en, ("", vi)) for st, en, vi in doc_srt(srt_co_san)]
        vi_srt = srt_co_san
        log_fn(f"📄 Dùng phụ đề đã sửa: {len(segs_vi)} câu.")
        if not segs_vi:
            log_fn("⚠ Phụ đề rỗng.")
            return None
    else:
        asr_input = video
        if tach_truoc:
            # Tách giọng TRƯỚC rồi nhận dạng trên giọng sạch → đỡ nghe nhầm do nhạc nền
            goc = os.path.join(thu_muc, ten + "_goc.wav")
            lay_audio(video, goc)
            giong, nhac_da_tach = tach_demucs(goc, log_fn=log_fn)
            if giong:
                asr_input = giong
                log_fn("✔ Đã tách giọng — nhận dạng trên giọng sạch (chính xác hơn).")
            try:
                os.remove(goc)
            except OSError:
                pass
        # DỊCH 1:1 TỪNG ĐOẠN (KHÔNG gộp câu) → cột Gốc↔Dịch khớp từng dòng, giữ mốc thời gian gốc.
        # Google: dịch SONG SONG ngay khi nghe → video DÀI cũng thấy cột Dịch điền dần.
        # AI: summary-first kiểu VideoLingo (tóm tắt + glossary + dịch 3 bước) cần TOÀN transcript →
        # dịch SAU khi ASR xong, cột Dịch điền 1 lần sau pha Nghe (đánh đổi để dịch sát + nhất quán tên).
        dung_ai = (engine == "ai") and not cung_ngon_ngu
        dung_gemini = (engine == "gemini") and not cung_ngon_ngu   # MẶC ĐỊNH: dịch bằng Gemini web (nền)
        # Google: DỊCH SONG SONG khi nghe (giữ live-fill). AI/Gemini: dịch SAU khi ASR xong (cần TOÀN
        # transcript). Gemini web → subprocess dich_gemini_web.py (headless, profile login), lỗi → Google bù.
        dich = _DichStream(log_fn, dung_ai=False) \
            if (not cung_ngon_ngu and not dung_ai and not dung_gemini and not chi_asr) else None
        if dung_ai:
            log_fn("📝 Nghe trước; rồi DỊCH bằng AI kiểu VideoLingo (tóm tắt + glossary → dịch 3 bước)...")
        elif dich:
            log_fn("📝 Nghe + DỊCH SONG SONG (Google, 1:1 từng đoạn) — cột Dịch điền dần khi đang nghe...")
        _ocr_boxes = []      # HỢP NHẤT: OCR đọc text + trả HỘP vị-trí mỗi câu vào đây → blur động + phụ đề bám
        # SCAN-CACHE (TÁCH ngôn ngữ đích): đổi vi↔en↔th... KHÔNG cần nghe/OCR lại — nạp segs (zh, ĐÃ dedup) đã lưu
        # → chỉ dịch + lồng tiếng làm lại. dich_lai ("Render từ đầu") → bỏ qua, quét mới. Blur-box có cache riêng.
        segs = None
        if _scan_key and not dich_lai:
            _pzs = _ca.lay(_scan_key, ".zh.srt")
            if _pzs:
                try:
                    segs = [(st, en, zh) for st, en, zh in doc_srt(_pzs)] or None
                except Exception:
                    segs = None
        if segs is not None:
            if dich:
                dich.huy()      # scan cached → KHÔNG dùng dịch-live (Google): dịch batch ở nhánh dưới
            dich = None
            log_fn("[CACHE HIT scan] Dùng lại nghe/OCR đã lưu (%d câu) — bỏ ASR/OCR, chỉ dịch sang %s." % (len(segs), tgt))
        else:
            segs = asr_segments(asr_input, model_size, log_fn, src_lang=src_lang,
                                on_seg=(dich.them_seg if dich else None),
                                on_reset=(dich.reset if dich else None), box_sink=_ocr_boxes)
            if not segs:
                if dich:
                    dich.huy()
                log_fn("⚠ Không nhận dạng được lời thoại.")
                return None
            _tg("ASR/OCR (đọc lời thoại %d câu)" % len(segs))
            _n_truoc = len(segs)
            segs = _gop_trung(segs)          # gộp cue CHỒNG (OCR 2-dòng / fill đè) → Gemini dịch nội dung gộp → hết 'chữ đè chữ'
            if len(segs) < _n_truoc:
                log_fn("🔗 Gộp %d cue chồng thời gian → %d cue (tránh chữ đè chữ)." % (_n_truoc, len(segs)))
            _n_lap = len(segs)
            segs = _dedup_lap(segs)          # bỏ cue OCR LẶP/TÁCH (đọc lại 1 dòng full→tách, hoặc lặp cách 1-2 cue)
            if len(segs) < _n_lap:
                log_fn("🧹 Bỏ %d cue LẶP/TÁCH (OCR đọc lại) → %d câu (hết phụ đề trùng)." % (_n_lap - len(segs), len(segs)))
            _n_manh = len(segs)
            segs = _bo_manh_trung(segs)      # bỏ cue-MẢNH ⊂ câu kề (tiền/hậu-tố ngắn _dedup_lap bỏ sót: '一直'⊂'一直没有找到')
            if len(segs) < _n_manh:
                log_fn("🧹 Bỏ %d cue MẢNH (⊂ câu kề) → %d câu (hết trùng tiền/hậu-tố, đọc đều)." % (_n_manh - len(segs), len(segs)))
            if os.environ.get("DUB_DESTUTTER", "1") != "0":   # bỏ LẶP LIỀN-KỀ trong cùng cue (Whisper vấp) → hết câu-nhanh
                _n_st = 0
                _segs2 = []
                for st, en, zh in segs:
                    zc = _bo_lap_lien(zh)
                    if zc != zh:
                        _n_st += 1
                    _segs2.append((st, en, zc))
                segs = _segs2
                if _n_st:
                    log_fn("🩹 Gộp lặp-từ LIỀN-KỀ (Whisper vấp) trong %d cue → đọc đều, hết câu nhanh bất thường." % _n_st)
            if _scan_key:      # LƯU scan (tách tgt) → lần đổi ngôn ngữ sau HIT (khỏi nghe/OCR lại)
                try:
                    _ca.luu_noi_dung(_scan_key, ".zh.srt", "\n".join(
                        "%d\n%s --> %s\n%s\n" % (i, phu_de._ts(st), phu_de._ts(en), zh)
                        for i, (st, en, zh) in enumerate(segs, 1)))
                except Exception:
                    pass
        if chi_asr:
            # DỊCH THỦ CÔNG: ASR xong → ghi phụ đề GỐC (zh) rồi DỪNG (chờ người dùng dịch + nhập lại).
            with open(zh_srt, "w", encoding="utf-8") as f:
                f.write("\n".join("%d\n%s --> %s\n%s\n" % (i, phu_de._ts(st), phu_de._ts(en), zh)
                                  for i, (st, en, zh) in enumerate(segs, 1)))
            log_fn("✔ ASR xong — xuất phụ đề gốc: %s (chờ dịch thủ công)." % os.path.basename(zh_srt))
            return {"zh_srt": zh_srt, "vi_srt": "", "video_phude": "", "video_longtieng": "",
                    "so_cau": len(segs), "cho_dich": True}
        # KHÔNG gộp câu nữa — dịch & hiển thị 1:1 theo từng đoạn ASR (khớp Gốc↔Dịch, sync chuẩn).
        if cung_ngon_ngu:
            # Nguồn đã cùng ngôn ngữ đích -> không dịch, phụ đề giữ nguyên lời gốc (từng đoạn)
            log_fn("📝 Nhận dạng %d đoạn (nguồn cùng ngôn ngữ đích — không dịch)." % len(segs))
            segs_vi = [(st, en, (zh, zh)) for st, en, zh in segs]
            for i, (st, en, zh) in enumerate(segs, 1):
                _segvi(i, zh)
        elif dung_ai:   # AI dịch. Mặc định Lingo (summary-first). Công tắt env AI_DICH_NHANH=1 → cũ 1 bước (đỡ ~½ quota)
            import ai_dich
            if os.environ.get("AI_DICH_NHANH") == "1":
                log_fn(f"📝 Nhận dạng {len(segs)} đoạn — dịch AI NHANH 1 bước (dich_phu_de, tiết kiệm quota)...")
                segs_vi = ai_dich.dich_phu_de([(st, en, zh) for (st, en, zh) in segs],
                                              log_fn=lambda m: print(m, flush=True))
                for i, (st, en, (zh, vi)) in enumerate(segs_vi):
                    if (vi or "").strip():    # dich_phu_de không tự bắn SEGVI → fill cột Dịch ở đây
                        _segvi(i + 1, vi)
            else:
                log_fn(f"📝 Nhận dạng {len(segs)} đoạn — dịch AI summary-first VideoLingo (tóm tắt + glossary → 3 bước)...")
                segs_vi = ai_dich.dich_video_vl([(st, en, zh) for (st, en, zh) in segs],
                                                log_fn=lambda m: print(m, flush=True), on_segvi=_segvi)
            for i, (st, en, (zh, vi)) in enumerate(segs_vi):
                if not (vi or "").strip():    # đoạn AI bỏ/sót → Google dịch bù (không để sót tiếng gốc)
                    vi = dich_dong(zh)
                    segs_vi[i] = (st, en, (zh, vi))
                    _segvi(i + 1, vi)
        elif dung_gemini:   # GEMINI WEB (mặc định) — dịch SAU ASR qua subprocess nền; sót → Gemini dịch lại (Google chỉ khi Gemini sập)
            log_fn("📝 Nhận dạng %d đoạn — đang dịch bằng AI (nền)..." % len(segs))
            with open(zh_srt, "w", encoding="utf-8") as f:    # ghi zh.srt cho script đọc
                f.write("\n".join("%d\n%s --> %s\n%s\n" % (i, phu_de._ts(st), phu_de._ts(en), zh)
                                  for i, (st, en, zh) in enumerate(segs, 1)))
            vis = {}
            # Gemini trả 1 DẢI LIỀN → hoặc dịch CẢ mẻ, hoặc sập CẢ mẻ (0 câu). Sập hẳn (0 câu) → DỊCH LẠI bằng
            # Gemini 1 lần (KHÔNG per-cue retry, KHÔNG Google — chất lượng Google không chấp nhận được).
            for _gem_att in range(2):
                try:
                    import tempfile   # subprocess, sys ĐÃ import ở module-level (dòng 17-18) — import lại Ở ĐÂY
                    vi_tmp = os.path.splitext(zh_srt)[0] + ".gem.vi.srt"
                    _gem_done = False
                    # STEP 3 — IN-PROCESS Gemini BỀN: trong render_worker (VC_RENDER_WORKER_PROC=1) gọi thẳng
                    # dich_srt(keep=True) → giữ Chrome+SPA Gemini NÓNG qua render + bỏ subprocess spawn (~24s) +
                    # tránh cold-flaky lần đầu. Lỗi BẤT KỲ → rớt xuống subprocess (cũ) bên dưới, KHÔNG vỡ dịch.
                    if os.environ.get("VC_RENDER_WORKER_PROC") == "1":
                        try:
                            import dich_gemini_web as _dgw
                            _dgw.dich_srt(zh_srt, vi_tmp, log_fn=lambda m: print(m, flush=True), keep=True)
                            if os.path.isfile(vi_tmp):
                                _gem_done = True
                        except Exception as _e:
                            log_fn("⚠ Gemini in-process lỗi (%s) → subprocess bù." % str(_e)[:80])
                    # python = python đang chạy (sys.executable); venv ở userData từ v0.1.20, KHÔNG ở MediaCrawler/.venv
                    py = sys.executable or os.path.join(THU_MUC_GOC, "MediaCrawler", ".venv", "Scripts", "python.exe")
                    if os.path.basename(py).lower() == "pythonw.exe":
                        _pp = os.path.join(os.path.dirname(py), "python.exe")
                        py = _pp if os.path.exists(_pp) else py
                    sc = os.path.join(THU_MUC_GOC, "dich_gemini_web.py")
                    # Profile Gemini để ở thư mục GHI ĐƯỢC (app-src có thể read-only khi cài Program Files →
                    # makedirs vỡ). Gemini chạy KHÔNG cần login nên profile tạm là đủ.
                    env_gem = dict(os.environ)
                    _gem_prof = os.path.join(tempfile.gettempdir(), "vc_gemini_profile")
                    env_gem["GEMINI_PROFILE_DIR"] = _gem_prof
                    if not _gem_done and os.path.isfile(py) and os.path.isfile(sc):
                        try:
                            # Timeout NỚI theo số câu (video dài = nhiều lô + retry): 200 câu ~10', 1000 câu ~25'.
                            # Dù timeout, dich_gemini_web ghi vi_tmp LŨY TIẾN nên các lô đã xong KHÔNG mất.
                            _gto = min(1800, 360 + len(segs) * 1.4)
                            subprocess.run([py, sc, "--srt", zh_srt, "--out", vi_tmp],
                                           capture_output=True, text=True, encoding="utf-8",
                                           errors="replace", timeout=_gto, env=env_gem)
                        finally:
                            # Profile Gemini là TẠM (không login-cache — xem ghi chú trên) → dọn để khỏi rò rác %TEMP%.
                            shutil.rmtree(_gem_prof, ignore_errors=True)
                    if os.path.isfile(vi_tmp):    # ĐỌC kết quả — CHUNG cho cả in-process lẫn subprocess
                        for k, (s2, e2, v2) in enumerate(doc_srt(vi_tmp), 1):
                            vis[k] = v2
                        try:
                            os.remove(vi_tmp)
                        except OSError:
                            pass
                    log_fn("📝 AI dịch: %d/%d câu." % (len(vis), len(segs)))
                except Exception:
                    log_fn("⚠ Dịch AI lỗi.")
                if any((v or "").strip() for v in vis.values()):
                    break                                  # có ≥1 câu dịch được (Gemini chạy) → KHÔNG dịch lại
                if _gem_att == 0:
                    log_fn("🔁 Gemini sập cả mẻ (0 câu) → dịch LẠI bằng Gemini 1 lần...")

            # KHÔNG Google bù (chất lượng Google không chấp nhận được): câu Gemini không dịch được → GIỮ zh
            # (tiếng Trung). Sập cả mẻ (0 câu) đã DỊCH LẠI bằng Gemini ở vòng trên; tới đây còn sót lẻ (hiếm) để zh.
            segs_vi = []
            for i, (st, en, zh) in enumerate(segs, 1):
                vi = vis.get(i, "")
                if not (vi or "").strip():
                    vi = zh          # Gemini sót câu này → giữ zh (KHÔNG Google)
                segs_vi.append((st, en, (zh, vi)))
                _segvi(i, vi)
        elif dich:   # google — đã dịch SONG SONG lúc nghe (cột Dịch điền dần)
            kq = dich.xong()   # chờ các luồng dịch (đã chạy SONG SONG lúc nghe) xong → dict zh->vi
            log_fn(f"📝 Nhận dạng {len(segs)} đoạn — đã dịch 1:1 (song song khi nghe).")
            segs_vi = []
            for i, (st, en, zh) in enumerate(segs):
                vi = kq.get(zh)
                if not (vi or "").strip():           # đoạn AI bỏ/sót → Google dịch bù
                    vi = dich_dong(zh)
                segs_vi.append((st, en, (zh, vi)))
                _segvi(i + 1, vi)                     # chốt đúng dòng + nội dung cuối
        else:
            log_fn(f"📝 Nhận dạng {len(segs)} đoạn. Đang dịch (Google, 1:1)...")
            segs_vi = []
            for i, (st, en, zh) in enumerate(segs, 1):
                vi = dich_dong(zh)
                segs_vi.append((st, en, (zh, vi)))
                _segvi(i, vi)
                if i % 5 == 0 or i == len(segs):
                    log_fn(f"   dịch {i}/{len(segs)}")
        segs_vi = _bo_vi_trung_lien_tiep(segs_vi, log_fn)   # gộp cue dịch TRÙNG liên tiếp (OCR đọc lại 1 dòng khác chữ → VI giống hệt)
        with open(zh_srt, "w", encoding="utf-8") as f:
            f.write("\n".join(f"{i}\n{phu_de._ts(st)} --> {phu_de._ts(en)}\n{zh}\n"
                              for i, (st, en, (zh, vi)) in enumerate(segs_vi, 1)))
        # vi_srt (bản BURN lên video): chia câu dài thành dòng ngắn cho dễ đọc
        segs_hien = _chong_de(chia_sub_dai(segs_vi))   # CHỐT: 0 cặp chồng khi burn (kể cả sau ép ≥0.5s)
        with open(vi_srt, "w", encoding="utf-8") as f:
            f.write("\n".join(f"{i}\n{phu_de._ts(st)} --> {phu_de._ts(en)}\n{vi}\n"
                              for i, (st, en, (zh, vi)) in enumerate(segs_hien, 1)))
        log_fn(f"✔ Đã tạo phụ đề: {os.path.basename(zh_srt)} + {os.path.basename(vi_srt)}")
        if _srt_key:   # MISS → lưu cache cho lần xử lý LẶP sau (lossless)
            try:
                _ca.luu(_srt_key, ".zh.srt", zh_srt)
                _ca.luu(_srt_key, ".vi.srt", vi_srt)
            except Exception:
                pass
        if _trans_key:   # TRANS-CACHE: lưu bản dịch theo SCAN-SEED → prefetch/render CHÍNH reuse (ổn định temp-mtime)
            try:
                _ca.luu(_trans_key, ".vi.srt", vi_srt)
            except Exception:
                pass

    ket = {"zh_srt": zh_srt, "vi_srt": vi_srt, "video_phude": "", "video_longtieng": "",
           "so_cau": len(segs_vi)}
    if chi_dich:            # PREFETCH DỊCH: đã có vi.srt (+ trans-cache) → DỪNG, KHÔNG dò-dải/dub/encode.
        return ket

    # Giải phóng whisper khỏi RAM ngay sau khi ASR xong, trước khi demucs/TTS load
    import gc
    phu_de._MODEL = None
    gc.collect()

    # Che chữ gốc: DÒ DẢI sub gốc (OpenCV) 1 lần → làm mờ ĐÚNG dải đó (đè sub Việt lên).
    # Không chắc → blur_band=None → burn_phude lùi về hộp đen cố định đáy. Tắt: env CHE_DAI=0.
    blur_band = blur_segs = None
    if che_chu and not cung_ngon_ngu:
        # QUYẾT ĐỊNH dải che DÙNG CHUNG với preview (dai_sub.detect_blur_band) — cùng logic/fallback/ffmpeg.
        # Cổng "có cần che không" (che_chu/cung_ngon_ngu) GIỮ Ở ĐÂY (nghiệp vụ render); detector chỉ trả "ở đâu".
        import dai_sub
        # CACHE band: dò dải sub gốc tốn vài giây quét frame → tái dùng khi xử lý LẶP cùng video.
        # Key gồm nội dung vi_srt (chỉ ảnh hưởng nhánh OCR fallback) + ENV CHE_DAI*/CHE_OCR.
        _band_key = _ca.tinh_key(
            "band", _vhash=_vhash,
            manual=(list(che_band_manual) if che_band_manual else None),
            srt=_ca.noi_dung_hash(vi_srt),
            e_chedai=os.environ.get("CHE_DAI", ""),
            e_chedaitren=os.environ.get("CHE_DAI_TREN", ""),
            e_cheocr=os.environ.get("CHE_OCR", "")) if _vhash else None
        _r = None
        _pb = (None if dich_lai else _ca.lay(_band_key, ".band.json")) if _band_key else None   # dich_lai: dò DẢI CHE lại từ đầu (đồng bộ với bỏ-cache srt; trước đây sót → "Render từ đầu" vẫn dùng dải cũ)
        if _pb:
            try:
                _r = json.load(open(_pb, encoding="utf-8"))
                log_fn("[CACHE HIT band] Dùng lại dải che đã dò.")
            except Exception:
                _r = None
        if _r is None:
            _r = dai_sub.detect_blur_band(video, srt=vi_srt, manual=che_band_manual, log_fn=log_fn)
            if _band_key:
                try:
                    _ca.luu_noi_dung(_band_key, ".band.json", json.dumps(_r))
                except Exception:
                    pass
        _is_manual = False
        if _r and _r.get("source") != "none":
            _is_manual = (_r.get("source") == "manual")
            blur_band = (_r["y0"], _r["y1"], _r["H"],
                         _r.get("x0", 0.0), _r.get("x1", 1.0))   # +x0,x1 → blur ĐÚNG HỘP text (không full-width)
        # CHE Ở ĐÁY (MẶC ĐỊNH): blur DẢI ĐÁY full-width (KHÔNG đo ngang) + phụ đề Việt TĨNH đè lên đáy; KỆ chữ
        # Trung ở trên video. Đơn giản + ổn cho mọi clip. Tắt = env CHE_DAY=0 (che ĐÚNG dải chữ Trung dò được).
        # CHE_DAY chỉ ÉP dải-đáy khi sub gốc THỰC SỰ ở đáy (y0≥0.80). Sub gốc CAO hơn (vd 0.76) → ép xuống 0.82 sẽ
        # NÉ chữ Trung (chữ ở TRÊN dải blur → vẫn hiện, lệch pha với phụ đề Việt). Cao hơn → GIỮ dải đã dò để blur +
        # phụ đề Việt đè ĐÚNG chỗ chữ Trung (che hẳn + đồng bộ). Tắt CHE_DAY=0 = luôn dùng dải dò.
        # AUTO blur-động (MẶC ĐỊNH THÔNG MINH): OCR đọc được HỘP vị-trí + sub KHÔNG ở ĐÁY thật (mép trên box y0 <
        # 0.85) → dùng blur ĐỘNG theo box OCR (đè + che ĐÚNG chỗ chữ mọi vị-trí: giữa/cao/split-screen). Sub ở đáy
        # thật (y0≥0.85) GIỮ dải-tĩnh + CHE_DAY (ổn định, ca phổ biến). Lý do: CHE_DAY ép dải-đáy (0.82,0.99) làm
        # TRƯỢT chữ ở vùng 0.80–0.85 (chữ ở TRÊN dải blur → vẫn hiện + sub Việt rơi xuống đáy, không đè). Tắt auto:
        # CHE_DONG_AUTO=0. Ép bật mọi lúc: CHE_DONG=1; ép tắt: CHE_DONG=0.
        _ob0 = locals().get("_ocr_boxes") or []
        _auto_dong = False
        # MẶC ĐỊNH DÙNG DẢI TĨNH (nhanh + đẹp hơn): blur động chỉ bật khi user ÉP (CHE_DONG=1) hoặc bật lại auto
        # (CHE_DONG_AUTO=1) cho video sub NHẢY vị-trí/split-screen. Dải tĩnh phủ đúng chỗ chữ Trung (đã cache
        # vị-trí qua detect_blur_band) → burn nhanh hẳn (1 overlay thay N), tránh thanh blur giật theo sub.
        if len(_ob0) >= 2 and os.environ.get("CHE_DONG_AUTO", "0") == "1":
            _y0s = sorted(s[2] for s in _ob0)
            _auto_dong = _y0s[len(_y0s) // 2] < 0.85          # mép trên box (median) chưa chạm đáy thật
        _env_cd = os.environ.get("CHE_DONG", "")
        _che_dong = (_env_cd == "1") or (_auto_dong and _env_cd != "0")
        if blur_band and os.environ.get("CHE_DAY", "1") != "0" and blur_band[0] >= 0.80 and not _che_dong and not _is_manual:
            # Sub ở ĐÁY: GIỮ mép-trên DÒ ĐƯỢC (min với 0.82 → khỏi lộ đỉnh chữ khi text cao hơn) + kéo đáy sát khung.
            # Full-width (0,1) → cách lề áp ở burn qua CHE_LE (thanh đáy CÓ lề, không bám 2 mép). Trước ép cứng 0.82
            # làm dải bắt đầu DƯỚI đỉnh chữ (0.80–0.82) → lộ đỉnh chữ Trung (lỗi user báo).
            # Tối ưu hóa cho video ngang (aspect ratio > 1): mốc kéo lên chỉ cần min 0.86 thay vì 0.82 để dải mờ mỏng/đẹp hơn.
            try:
                import xu_ly_video
                _W, _H, _ = dai_sub._kich_thuoc(xu_ly_video.tim_exe("ffprobe"), os.path.abspath(video))
            except Exception:
                _W, _H = 0, 0
            _is_landscape = (_W > 0 and _H > 0 and _W > _H)
            _top_limit = 0.88 if _is_landscape else 0.82
            blur_band = (min(blur_band[0], _top_limit), max(blur_band[1], 0.99), blur_band[2], 0.0, 1.0)
        # HỢP NHẤT (ưu tiên): HỘP vị-trí lấy LUÔN từ OCR đọc-text (box_sink _ocr_boxes) — chuẩn (RapidOCR det) +
        # timing KHỚP câu dịch + KHÔNG quét 2 lần. OCR không chạy (whisper/no-hardsub) mà vẫn có dải → dò riêng.
        if blur_band and _che_dong:   # blur ĐỘNG (bật tay CHE_DONG=1 HOẶC auto khi sub không ở đáy thật)
            _ob = locals().get("_ocr_boxes") or []
            _bk = _ca.tinh_key("boxes", _vhash=_vhash, e_fps=os.environ.get("CHE_DONG_FPS", ""),
                               e_chedong=os.environ.get("CHE_DONG", "")) if _vhash else None
            if len(_ob) >= 2:
                blur_segs = [tuple(s) for s in _ob]
                if _bk:                                  # CACHE vị-trí → render-LẠI (cache srt, bỏ OCR) KHỎI quét lại
                    try:
                        _ca.luu_noi_dung(_bk, ".boxes.json", json.dumps(_ob))
                    except Exception:
                        pass
                log_fn("🎯 Blur động + phụ đề bám: %d câu (vị-trí từ OCR — chuẩn, khớp text)." % len(_ob))
            else:
                # OCR KHÔNG chạy (CACHE HIT srt — render lại / whisper) → ưu tiên DÙNG LẠI vị-trí đã cache (KHỎI
                # quét lại = tăng tốc render-lại hardsub); không có cache mới dò riêng (phat_hien_hop_dong).
                _cb = _ca.lay(_bk, ".boxes.json") if _bk else None
                if _cb:
                    try:
                        _segs = json.load(open(_cb, encoding="utf-8"))
                        if _segs and len(_segs) >= 2:
                            blur_segs = [tuple(s) for s in _segs]
                            log_fn("🎯 Blur động: dùng lại %d vị-trí đã CACHE (hardsub render lại — KHỎI quét)." % len(_segs))
                    except Exception:
                        pass
                if blur_segs is None and _r.get("source") == "rapidocr":
                    try:
                        import dai_sub_rapid
                        _segs = dai_sub_rapid.phat_hien_hop_dong(video, log_fn=log_fn)
                        if _segs and len(_segs) >= 2:
                            blur_segs = [tuple(s) for s in _segs]
                            if _bk:
                                try:
                                    _ca.luu_noi_dung(_bk, ".boxes.json", json.dumps(_segs))
                                except Exception:
                                    pass
                    except Exception:
                        blur_segs = None

        if che_khac:
            try:
                import dai_sub_rapid
                log_fn("🔎 Đang dò tìm các chữ Trung khác xuất hiện tạm thời trong video...")
                other_segs = dai_sub_rapid.phat_hien_chu_khac(video, blur_band, log_fn=log_fn)
                if other_segs:
                    if blur_segs is None:
                        blur_segs = []
                    blur_segs.extend(other_segs)
                    co_blur = True
            except Exception as _e:
                log_fn("⚠ Lỗi khi dò chữ Trung khác: " + str(_e))

    if lam_long_tieng:
        dur = _thoi_luong(video) or (segs_vi[-1][1] + 2)
        dub_wav = os.path.join(thu_muc, ten + "_dub.wav")
        # CACHE dub: track giọng THUẦN (TRƯỚC pha mux goc_vol/watermark/tăng tốc) → tái dùng khi khách
        # đổi cài-hình mà giữ giọng. dub-key gồm NỘI DUNG vi_srt (lời đọc) + engine TTS + giọng +
        # ref_audio(clone OmniVoice) + ENV DUB_*. goc_vol/extra_vf/speed/wm/bg KHÔNG vào key (áp ở mux cuối).
        _dub_key = _ca.tinh_key(
            "dub", _vhash=_vhash, srt=_ca.noi_dung_hash(vi_srt), tts=tts_engine,
            voice=(voice or ""), tgt=tgt,
            ref=(_ca.video_hash(ref_audio) if (tts_engine == "omnivoice" and ref_audio) else ""),
            e_maxsil=os.environ.get("DUB_MAX_SIL", ""), e_fill=os.environ.get("DUB_FILL", ""),
            e_maxspeed=os.environ.get("DUB_MAX_SPEED", ""), e_gapgiu=os.environ.get("DUB_GAP_GIU", ""),
            e_stretch=os.environ.get("DUB_STRETCH", "")) if _vhash else None
        _tg("Dịch (AI) %d câu" % len(segs_vi))
        lt = None
        _pd = _ca.lay(_dub_key, ".dub.wav") if (_dub_key and not dich_lai) else None   # dich_lai → lồng tiếng MỚI
        if _pd:
            try:
                shutil.copyfile(_pd, dub_wav)
                lt = dub_wav
                # RESTORE 3 global (onsets/warp/slow) từ sidecar → mux+burn khớp HÌNH-TIẾNG y như liền mạch.
                # (Trước đây cache-hit dub KHÔNG khôi phục → Video Assist bật thì tiếng-hình lệch — TODO 2602 đã ghi.)
                _pm = _ca.lay(_dub_key, ".dubmeta.json")
                if _pm and os.path.isfile(_pm):
                    try:
                        _mj = json.load(open(_pm, encoding="utf-8"))
                        globals()["_LAST_DUB_ONSETS"] = ([tuple(x) for x in _mj["onsets"]] if _mj.get("onsets") else None)
                        globals()["_LAST_TIME_WARP"] = ([tuple(x) for x in _mj["warp"]] if _mj.get("warp") else None)
                        globals()["_LAST_VIDEO_SLOW"] = float(_mj.get("slow", 1.0) or 1.0)
                        log_fn("[CACHE HIT dub] Dùng lại giọng + căn thời-lượng đã lưu — bỏ qua lồng tiếng (TTS).")
                    except Exception:
                        log_fn("[CACHE HIT dub] Dùng lại giọng đã sinh — bỏ qua lồng tiếng (TTS).")
                else:
                    log_fn("[CACHE HIT dub] Dùng lại giọng đã sinh — bỏ qua lồng tiếng (TTS).")
            except Exception:
                _pd = None
        if _pd is None:
            if tgt == "vi" and tts_engine == "piper":
                # Piper ONNX: OFFLINE, VÔ HẠN, nhanh nhất (~8x realtime CPU) — không throttle như edge.
                # voice = tên giọng Piper (banmai/ngochuyen/maiphuong...) → tải on-demand (NghiTTS); trống/banmai = mặc định.
                _pmp = None
                _pv = str(voice or "").lower()
                if _pv and _pv != "banmai" and not _pv.startswith(("vi-", "en-")) and "/" not in _pv:
                    try:
                        import giong_piper
                        _pmp = giong_piper.tai(_pv, log_fn=log_fn)
                    except Exception:
                        _pmp = None
                lt = long_tieng_piper(segs_vi, dur, dub_wav, model_path=_pmp, log_fn=log_fn)
                if not lt:
                    log_fn("ℹ Piper không dùng được → lồng tiếng bằng edge-tts (giọng Việt).")
                    ev = voice if (voice or "").startswith("vi-") else ngon_ngu.voice_mac_dinh("vi")
                    lt = long_tieng_edge(segs_vi, dur, dub_wav, ev, log_fn=log_fn)
            elif tgt == "vi" and tts_engine == "omnivoice":
                # OmniVoice CLONE (cần GPU): giọng = file mẫu upload (ref_audio) hoặc mặc định nu.wav
                # → clone 1 giọng NHẤT QUÁN. Chất lượng theo num_step (env OMNI_NS = 8/16/32, máy mạnh chọn cao).
                _oref = ref_audio if ref_audio else OMNI_GIONG_MAU.get(str(voice or "").lower(), OMNI_REF_MAC_DINH)
                lt = long_tieng_omnivoice(segs_vi, dur, dub_wav, ref_audio=_oref, num_step=None, log_fn=log_fn)
                if not lt:
                    log_fn("ℹ OmniVoice không dùng được (cần GPU?) → lồng tiếng bằng edge-tts.")
                    ev = voice if (voice or "").startswith("vi-") else ngon_ngu.voice_mac_dinh("vi")
                    lt = long_tieng_edge(segs_vi, dur, dub_wav, ev, log_fn=log_fn)
            elif tgt != "vi" and tts_engine == "supertonic":
                # Supertonic-3 (ONNX, CPU; đích Hàn/EN). voice = M1-M5/F1-F5; lang = đích thật (ko/en...).
                # Lỗi/thiếu → lùi edge-tts theo đích (ko-KR / en-US).
                lt = long_tieng_supertonic(segs_vi, dur, dub_wav, voice=voice, lang=tgt, log_fn=log_fn)
                if not lt:
                    log_fn("ℹ Supertonic không dùng được → lồng tiếng bằng edge-tts (%s)." % tgt)
                    voi = voice
                    if str(voice or "").strip().upper().startswith(("M", "F")):
                        info = ngon_ngu.LANGS.get(tgt)
                        if info and "voices" in info and len(info["voices"]) >= 2:
                            voi = info["voices"][1][0] if str(voice or "").strip().upper().startswith("M") else info["voices"][0][0]
                    if not voi or str(voi).count("-") < 2:
                        voi = ngon_ngu.voice_mac_dinh(tgt)
                    lt = long_tieng_edge(segs_vi, dur, dub_wav, voi, log_fn=log_fn)
            elif tgt != "vi" and tts_engine == "piper":
                # Piper TIẾNG ANH (narrator HF: en_US-lessac-high/ryan-high/amy-medium) — OFFLINE, CPU nhanh, VÔ
                # HẠN. long_tieng_piper tự tải onnx qua `piper.download_voices <ten>` nếu thiếu. chuan_hoa=False:
                # KHÔNG chuẩn-hoá số/ngày kiểu VN (để phonemizer tiếng Anh tự đọc). Lỗi/thiếu → lùi edge-en.
                _pv = str(voice or "").strip() or "en_US-lessac-high"
                _emp = os.path.join(PIPER_DIR, _pv + ".onnx")
                lt = long_tieng_piper(segs_vi, dur, dub_wav, model_path=_emp, chuan_hoa=False, log_fn=log_fn)
                if not lt:
                    log_fn("ℹ Piper EN không dùng được → lồng tiếng bằng edge-tts (en).")
                    voi = voice if (voice or "").startswith("en-") else ngon_ngu.voice_mac_dinh(tgt)
                    lt = long_tieng_edge(segs_vi, dur, dub_wav, voi, log_fn=log_fn)
            else:
                # edge-tts (NHANH, không cần model local) — MỌI ngôn ngữ. Giọng edge locale (xx-YY-...Neural) giữ nguyên; else mặc định theo đích.
                voi = voice
                if str(voice or "").strip().upper().startswith(("M", "F")):
                    info = ngon_ngu.LANGS.get(tgt)
                    if info and "voices" in info and len(info["voices"]) >= 2:
                        voi = info["voices"][1][0] if str(voice or "").strip().upper().startswith("M") else info["voices"][0][0]
                if not voi or str(voi).count("-") < 2:
                    voi = ngon_ngu.voice_mac_dinh(tgt)
                lt = long_tieng_edge(segs_vi, dur, dub_wav, voi, log_fn=log_fn)
            _tg("Lồng tiếng (TTS + ghép track khớp timing)")
            if lt and os.path.isfile(dub_wav) and _dub_key:   # MISS → lưu track giọng thuần + META căn thời-lượng
                try:
                    _ca.luu(_dub_key, ".dub.wav", dub_wav)
                    # SIDECAR: onsets/warp/slow (do _ghep_track_khop set) → encode-phase/cache-hit restore để
                    # burn khớp HÌNH-TIẾNG. onsets/warp = list tuple (JSON-able); slow = float.
                    _mj = {"onsets": globals().get("_LAST_DUB_ONSETS"),
                           "warp": globals().get("_LAST_TIME_WARP"),
                           "slow": float(globals().get("_LAST_VIDEO_SLOW", 1.0) or 1.0)}
                    _ca.luu_noi_dung(_dub_key, ".dubmeta.json", json.dumps(_mj, ensure_ascii=False, default=list))
                except Exception:
                    pass
        # SPLIT DUB↔ENCODE: đã có dub_wav (+ dub-cache + sidecar) → DỪNG, KHÔNG mux/encode. Encode-phase (job kế,
        # lane khác) HIT dub-cache + restore 3 global → burn. Lane CPU nhả NGAY sau dub → dub video kế.
        if chi_dub:
            if lt and os.path.isfile(dub_wav):
                log_fn("✔ Lồng tiếng xong (chờ encode) — %d câu." % len(segs_vi))
                ket["dub_wav"] = dub_wav
                # KHÔNG xoá dub_wav ở đây (đã copy vào cache; file tạm cạnh video sẽ dọn ở cleanup cuối/encode-phase).
                return ket
            log_fn("⚠ Lồng tiếng thất bại (chi_dub) — không có giọng để encode.")
            return None
        # SPLIT DUB↔ENCODE (1 tiến trình): DUB (Supertonic/CPU) đã xong; phần còn lại là mux + ffmpeg encode
        # (nvenc/GPU; filter che-chữ+burn CPU nhưng NHẸ so với TTS). Báo scheduler "CPU rảnh" → nhả guard để
        # video KẾ bắt đầu dub trong lúc video này encode. Gate VC_SPLIT_DUB_ENCODE=1 (mặc định TẮT = như cũ).
        if lt and os.environ.get("VC_SPLIT_DUB_ENCODE") == "1":
            log_fn("⏹CPU_FREE dub xong — bắt đầu encode (nvenc), lane CPU rảnh cho video kế.")
        if lt and os.path.isfile(dub_wav):
            # ÂM LƯỢNG GIỌNG: CHUẨN HOÁ ĐỘ VANG (loudnorm) cho giọng dub → TO, đều mọi engine. LÝ DO (đo thật):
            # TTS ra RẤT NHỎ — Supertonic đỉnh ~-11dB / RMS ~-27dB; chuẩn hoá theo ĐỈNH (pydub normalize cũ) bị 1
            # transient/click là VÔ HIỆU → giọng vẫn nhỏ dù để 100%. loudnorm đưa về -16 LUFS + true-peak -1.5dB
            # (có limiter, KHÔNG méo). 100% (giong_vol=1.0) = -16 LUFS chuẩn; kéo slider = ±dB từ mức đó
            # (1.5→-12.5, 0.5→-22). Áp 1 LẦN cho MỌI nhánh (kể cả tắt tiếng gốc). dub_wav là track thuần đã copy.
            import math as _math
            _target = -16.0
            if giong_vol is not None:
                try:
                    _gv = max(0.1, min(3.0, float(giong_vol)))
                    _target = -16.0 + 20.0 * _math.log10(_gv)
                except (TypeError, ValueError):
                    pass
            _ln = dub_wav + ".ln.wav"
            _rv = subprocess.run([_ffmpeg(), "-y", "-i", dub_wav, "-af",
                                  "loudnorm=I=%.1f:TP=-1.5:LRA=11" % _target, "-ar", "44100", "-ac", "2", _ln],
                                 capture_output=True)
            if _rv.returncode == 0 and os.path.isfile(_ln):
                os.replace(_ln, dub_wav)
                log_fn("🔊 Âm lượng giọng lồng tiếng: %d%% (chuẩn hoá to đều)."
                       % round((giong_vol if giong_vol is not None else 1.0) * 100))
            # VIDEO ASSIST: S đã chọn lúc fit dub (_ghep_track_khop). Tiếng gốc trộn nền PHẢI chậm theo S (lay_audio
            # video_slow=_vs) để khớp dub (dài tong/S). _vs=1.0 nếu Assist tắt / cache (fresh render mới có S).
            _vs = float(globals().get("_LAST_VIDEO_SLOW", 1.0) or 1.0)
            _tw = globals().get("_LAST_TIME_WARP")   # Video Assist per-segment: warp video+tiếng gốc khớp dub
            # ĐIỀU KHIỂN MỚI: 1 thanh "Âm lượng gốc" goc_vol∈[0,1]. 0 = tắt hẳn tiếng gốc (chỉ giọng Việt);
            # >0 = giảm tiếng gốc xuống mức đó rồi đè giọng Việt (KHÔNG dùng demucs). goc_vol=None → giữ
            # logic cũ (tat_tieng_goc / lam_tach_nhac) cho tương thích ngược.
            if lam_tach_nhac:
                # "Tách lời (giữ nhạc gốc)": demucs BỎ giọng gốc, GIỮ NHẠC NỀN nguyên rồi đè giọng Việt.
                # ƯU TIÊN trên goc_vol — vì goc_vol chỉ GIẢM ĐỀU (vẫn còn tiếng Trung), không bỏ được giọng.
                # NAY: áp dụng mức giảm gốc (slider %) lên nhạc nền nếu người dùng cấu hình goc_vol.
                goc_wav = os.path.join(thu_muc, ten + "_goc.wav")
                lay_audio(video, goc_wav, video_slow=_vs, time_warp=_tw)
                inst = nhac_da_tach if (nhac_da_tach and os.path.isfile(nhac_da_tach)) else tach_nhac(goc_wav, log_fn=log_fn)
                if goc_vol is not None:
                    import math
                    try:
                        gv = max(0.0, min(1.0, float(goc_vol)))
                    except (TypeError, ValueError):
                        gv = 0.2
                    giam = 30.0 * math.log10(gv) if gv > 0.001 else -99.0
                else:
                    giam = 0.0 if inst else -12.0

                nen = inst if (inst and giam > -90.0) else (goc_wav if giam > -90.0 else None)
                if nen is None:
                    log_fn("🔇 Âm lượng nhạc nền = 0 — chỉ giữ giọng lồng tiếng Việt.")
                    mix_wav = dub_wav
                else:
                    if inst:
                        if goc_vol is not None:
                            log_fn("🎵 Giữ NHẠC NỀN (tách lời demucs) ở mức %d%% (giảm %.1f dB), đè giọng Việt." % (round(gv * 100), giam))
                        else:
                            log_fn("🎵 Giữ NHẠC NỀN (tách lời demucs) 100%%, bỏ giọng gốc, đè giọng Việt.")
                    else:
                        log_fn("⚠ Tách lời thất bại → giảm tiếng gốc %.1f dB rồi đè giọng Việt." % abs(giam))
                    mix_wav = os.path.join(thu_muc, ten + "_mix.wav")
                    tron_audio(dub_wav, nen, mix_wav, nen_giam_db=giam)
            elif goc_vol is not None:
                try:
                    gv = max(0.0, min(1.0, float(goc_vol)))
                except (TypeError, ValueError):
                    gv = 0.2
                if gv <= 0.001:
                    log_fn("🔇 Âm lượng gốc = 0 — chỉ giữ giọng lồng tiếng Việt.")
                    goc_wav = None
                    mix_wav = dub_wav
                else:
                    import math
                    goc_wav = os.path.join(thu_muc, ten + "_goc.wav")
                    lay_audio(video, goc_wav, video_slow=_vs, time_warp=_tw)
                    # Đường cong DỐC (30·log10 thay 20·log10): mức thấp giảm mạnh hơn để tiếng gốc rõ là NỀN,
                    # giữ 100%=0dB. 1.0→0dB · 0.5→−9dB · 0.2→−21dB (trước −14dB còn hơi to) · 0.1→−30dB.
                    giam = 30.0 * math.log10(gv)
                    log_fn("🔉 Giữ tiếng gốc %d%% (giảm %.1f dB), đè giọng Việt lên." % (round(gv * 100), giam))
                    mix_wav = os.path.join(thu_muc, ten + "_mix.wav")
                    tron_audio(dub_wav, goc_wav, mix_wav, nen_giam_db=giam)
            elif tat_tieng_goc:
                # BỎ HẲN tiếng gốc → audio CHỈ là giọng Việt (dub). Không trộn nền.
                log_fn("🔇 Tắt tiếng gốc — chỉ giữ giọng lồng tiếng Việt.")
                goc_wav = None
                mix_wav = dub_wav
            else:
                goc_wav = os.path.join(thu_muc, ten + "_goc.wav")
                lay_audio(video, goc_wav, video_slow=_vs, time_warp=_tw)
                nen, giam = goc_wav, -20.0   # mặc định giảm tiếng gốc −20dB (nền rõ, trước −14dB còn hơi to)
                mix_wav = os.path.join(thu_muc, ten + "_mix.wav")
                tron_audio(dub_wav, nen, mix_wav, nen_giam_db=giam)
            # LỌC ÂM nâng cao (checkbox UI): áp lên audio CUỐI (mix_wav) trước khi mux. Thứ tự: lọc gió
            # (highpass cắt ầm trầm) → xóa tạp âm (afftdn) → chuẩn hóa loudness (loudnorm, để cuối cho mức ổn).
            if af_loc and mix_wav and os.path.isfile(mix_wav):
                _chain = []
                if "wind" in af_loc:
                    _chain.append("highpass=f=90")
                if "denoise" in af_loc:
                    _chain.append("afftdn=nf=-25")
                if "normalize" in af_loc:
                    _chain.append("loudnorm=I=-16:TP=-1.5:LRA=11")
                if _chain:
                    _aftmp = os.path.join(thu_muc, ten + "_af.wav")
                    _ra = subprocess.run([_ffmpeg(), "-y", "-i", mix_wav, "-af", ",".join(_chain), _aftmp],
                                         capture_output=True)
                    if _ra.returncode == 0 and os.path.isfile(_aftmp):
                        if mix_wav != dub_wav:   # mix_wav==dub_wav khi goc_vol=0 → đừng xoá track giọng đang dùng
                            try:
                                os.remove(mix_wav)
                            except OSError:
                                pass
                        mix_wav = _aftmp
                        log_fn("🎚 Lọc âm: " + ", ".join(_chain))
            out_lt = os.path.join(thu_muc, ten + "_longtieng.mp4")
            # CĂN phụ đề Việt khớp GIỌNG: dub trôi khỏi mốc gốc (câu Việt dài) → dời timestamp sub theo vị-trí
            # dub THỰC (do _ghep_track_khop xuất _LAST_DUB_ONSETS). Cache-hit/no-dub → onsets=None → giữ vi_srt gốc.
            # Tắt: DUB_SUB_SYNC=0 (fallback hành vi cũ). Chỉ áp cho video LỒNG TIẾNG (sub khớp giọng đang đọc).
            vi_srt_burn = vi_srt
            _onsets = globals().get("_LAST_DUB_ONSETS")
            if burn and _onsets and os.environ.get("DUB_SUB_SYNC", "1") != "0":
                vi_srt_burn = _canh_sub_theo_dub(
                    vi_srt, _onsets, _tw, os.path.join(thu_muc, ten + ".dubsync.vi.srt"), log_fn=log_fn)
            if burn:   # CÓ phụ đề: burn phụ đề Việt + che chữ Trung + lồng tiếng (+ gộp biến đổi hình/tăng tốc)
                ok_lt = burn_phude(video, vi_srt_burn, out_lt, che_chu=che_chu, audio_path=mix_wav,
                                   log_fn=log_fn, blur_band=blur_band, blur_segs=blur_segs,
                                   video_slow=_vs, time_warp=_tw, phude_style=phude_style, **burn_kw)
            elif co_extra_hinh or _vs < 0.999 or _tw:   # biến đổi hình / video-slow / warp per-segment → re-encode
                ok_lt = burn_phude(video, None, out_lt, che_chu=False, audio_path=mix_wav,
                                   log_fn=log_fn, video_slow=_vs, time_warp=_tw, **burn_kw)
            else:      # CHỈ lồng tiếng, KHÔNG biến đổi gì: GIỮ NGUYÊN hình (copy video) — chỉ thay tiếng
                ff = _ffmpeg()
                base = [ff, "-y", "-i", video, "-i", mix_wav, "-map", "0:v:0", "-map", "1:a:0",
                        "-c:a", "aac", "-b:a", "192k", "-shortest", out_lt]
                r = subprocess.run(base[:6] + ["-c:v", "copy"] + base[6:], capture_output=True)
                if not (r.returncode == 0 and os.path.isfile(out_lt)):   # copy lỗi (codec lạ) -> encode lại
                    enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
                    r = subprocess.run(base[:6] + enc + base[6:], capture_output=True)
                ok_lt = (r.returncode == 0 and os.path.isfile(out_lt))
            if ok_lt:
                ket["video_longtieng"] = out_lt
                log_fn("✔ Xong video " + ("LỒNG TIẾNG + phụ đề" if burn else "CHỈ LỒNG TIẾNG (giữ nguyên hình)")
                       + ": " + os.path.basename(out_lt))
            _srt_sync = vi_srt_burn if vi_srt_burn != vi_srt else None   # srt căn theo giọng (tạm) → dọn
            for tmp in (dub_wav, goc_wav, mix_wav, _srt_sync):
                if not tmp:
                    continue   # goc_wav=None khi tắt tiếng gốc; _srt_sync=None khi không căn
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            d = os.path.join(thu_muc, "_demucs")
            if os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True)
        else:
            log_fn("⚠ Lồng tiếng không thành công → xuất video phụ đề thay thế.")
            out_mp4 = os.path.join(thu_muc, ten + "_phude.mp4")
            # GIỮ biến đổi hình/tăng tốc (**burn_kw) như nhánh 'elif burn' — trước đây thiếu nên fallback
            # ra video gần như giống gốc (mất lật/watermark/tăng tốc → rủi ro bản quyền cho khách).
            if burn_phude(video, vi_srt, out_mp4, che_chu=che_chu, log_fn=log_fn, blur_band=blur_band, blur_segs=blur_segs, phude_style=phude_style, **burn_kw):
                ket["video_phude"] = out_mp4
                log_fn("✔ Xong video phụ đề: " + os.path.basename(out_mp4))
    elif burn:
        out_mp4 = os.path.join(thu_muc, ten + "_phude.mp4")
        if burn_phude(video, vi_srt, out_mp4, che_chu=che_chu, log_fn=log_fn, blur_band=blur_band, blur_segs=blur_segs, phude_style=phude_style, **burn_kw):
            ket["video_phude"] = out_mp4
            log_fn("✔ Xong video phụ đề: " + os.path.basename(out_mp4))

    # dọn thư mục tách demucs nếu còn (trường hợp tách trước mà không lồng tiếng)
    d = os.path.join(thu_muc, "_demucs")
    if os.path.isdir(d):
        shutil.rmtree(d, ignore_errors=True)

    # PROFILE tích luỹ (instrument — KHÔNG refactor): ghi 1 dòng/render vào jsonl → đọc qua NHIỀU video để
    # biết nút thắt THẬT (ASR/OCR/dịch/TTS/encode) thay vì suy từ 1 mẫu. GEMPROF (Gemini open/load/wait) log riêng.
    try:
        import json as _json, time as _tj
        _RES.stop()
        _plog = os.environ.get("VC_PROFILE_LOG") or os.path.join(
            os.environ.get("MC_DATA_DIR") or thu_muc, "_render_profile.jsonl")
        # META workload → chuẩn hoá giây/segment, giây/1000-chars, giây/phút-audio (ổn định hơn time thô)
        _meta = {}
        try:
            _meta["segments"] = len(segs)
            _meta["audio_sec"] = round(sum((e - s) for s, e, _z in segs), 1)
            _meta["chars_zh"] = sum(len(_z) for _s, _e, _z in segs)
        except Exception:
            pass
        try:
            _meta["chars_vi"] = sum(len(_v) for _s, _e, (_z, _v) in segs_vi)
        except Exception:
            pass
        _rec = {"t": int(_tj.time()), "video": os.path.basename(video),
                "mb": round(os.path.getsize(video) / 1048576, 1) if os.path.isfile(video) else 0,
                "dur": round(_thoi_luong(video) or 0, 1),
                "total": round(_tj.time() - _PROF_T0, 1),
                "meta": _meta,
                "stages": _PROF_STAGES}
        with open(_plog, "a", encoding="utf-8") as _pf:
            _pf.write(_json.dumps(_rec, ensure_ascii=False) + "\n")
        log_fn("PROFILE|" + _json.dumps(_rec, ensure_ascii=False))
    except Exception:
        pass
    log_fn("LOCALIZE_DONE")
    return ket


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--model", default="small")
    ap.add_argument("--no-che", action="store_true", help="Không che chữ Trung")
    ap.add_argument("--che-khac", action="store_true", help="Che chữ Trung khác")
    ap.add_argument("--no-burn", action="store_true", help="Chỉ xuất .srt, không ghép video")
    ap.add_argument("--long-tieng", action="store_true", help="Lồng tiếng Việt (edge-tts)")
    ap.add_argument("--tach-nhac", action="store_true", help="Tách nhạc nền (demucs, nặng)")
    ap.add_argument("--voice", default="vi-VN-HoaiMyNeural")
    ap.add_argument("--engine", default="google", choices=["google", "ai", "gemini"])
    ap.add_argument("--srt-co-san", default=None, help="Ghép lại từ phụ đề đã sửa (bỏ qua ASR)")
    ap.add_argument("--tach-truoc", action="store_true", help="Tách giọng (demucs) TRƯỚC khi nhận dạng — đỡ nhầm")
    ap.add_argument("--ref-audio", default=None, help="File mẫu giọng (wav/mp3 ~5-15s) để CLONE giọng — ưu tiên hơn --voice")
    ap.add_argument("--tts", default="edge", choices=["edge", "piper", "omnivoice", "supertonic"],
                    help="Giọng lồng tiếng: piper=nhanh nhất | omnivoice=clone (GPU) | supertonic=offline đa ngôn ngữ | edge=edge-tts (cần mạng)")
    ap.add_argument("--chi-asr", dest="chi_asr", action="store_true",
                    help="DỊCH THỦ CÔNG: chỉ ASR → ghi zh.srt rồi dừng (chờ nhập SRT đã dịch)")
    ap.add_argument("--chi-dich", dest="chi_dich", action="store_true",
                    help="TRANSLATE-PREFETCH: OCR(cache)→dịch→ghi vi.srt(+trans-cache) rồi dừng (không dub/encode)")
    ap.add_argument("--chi-dub", dest="chi_dub", action="store_true",
                    help="SPLIT DUB↔ENCODE: OCR+dịch(cache)→DUB→lưu .dub.wav+.dubmeta.json rồi DỪNG (không mux/encode)")
    ap.add_argument("--goc-vol", type=float, default=None,
                    help="Âm lượng tiếng gốc 0-1 (0 = tắt hẳn, chỉ giọng Việt). Bỏ trống = giữ logic cũ")
    ap.add_argument("--dich-lai", dest="dich_lai", action="store_true",
                    help="RENDER TỪ ĐẦU: bỏ qua cache dịch+lồng tiếng → dịch/lồng tiếng MỚI (vẫn lưu đè cache)")
    ap.add_argument("--giong-vol", type=float, default=None,
                    help="Âm lượng GIỌNG lồng tiếng 0-2 (1=gốc). Bỏ trống = giữ nguyên")
    ap.add_argument("--af", default="",
                    help="Lọc âm cuối, danh sách cách nhau dấu phẩy: normalize,denoise,wind")
    a = ap.parse_args()
    try:
        chay(a.video, model_size=a.model, che_chu=not a.no_che, che_khac=a.che_khac, burn=not a.no_burn,
             lam_long_tieng=a.long_tieng, lam_tach_nhac=a.tach_nhac, voice=a.voice,
             engine=a.engine, srt_co_san=a.srt_co_san, tach_truoc=a.tach_truoc,
             ref_audio=a.ref_audio, tts_engine=a.tts, goc_vol=a.goc_vol, chi_asr=a.chi_asr,
             dich_lai=a.dich_lai, giong_vol=a.giong_vol, af_loc=a.af, chi_dich=a.chi_dich,
             chi_dub=a.chi_dub)
    except Exception:
        # In traceback có tiền tố LOG: → render worker (web_app) bắt được & hiện trong Nhật ký,
        # thay vì chết âm thầm chỉ thấy "lỗi". sys.exit(1) để web đánh dấu trạng thái 'loi'.
        import traceback
        log("❌ LỖI localize: " + repr(sys.exc_info()[1])[:200])
        for _l in traceback.format_exc().splitlines()[-15:]:
            log("   " + _l)
        sys.exit(1)


if __name__ == "__main__":
    main()
