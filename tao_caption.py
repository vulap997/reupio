# -*- coding: utf-8 -*-
"""Tạo TIÊU ĐỀ + CAPTION cho video ĐÃ RENDER, để LoHa Page auto đăng.

- Video CÓ thuyết minh (có .vi.srt cạnh bên) → AI tóm tắt phụ đề thành 1 tiêu đề hấp dẫn.
- Video KHÔNG lời (mukbang/ASMR/nhảy — không có .vi.srt) → tiêu đề theo MẪU của chủ đề.
- Caption = tiêu đề + #lohatech + hashtag chủ đề + (tối đa ~4 tag user tự thêm).

Dùng làm bước trước khi gom video vào folder đăng của LoHa Page.
"""
import os
import re

import ai_dich

GOC = os.path.dirname(os.path.abspath(__file__))

# Cụm "rác" hay gặp trong tiêu đề Douyin (bỏ cho tiêu đề gọn tự nhiên) — bỏ TRƯỚC khi dịch
FILLER_ZH = ["完整版解说", "完整版", "影视解说", "电影解说", "万字解说", "精讲", "解说", "完结"]


def text_tu_srt(srt_path, gioi_han=1800):
    """Lấy phần CHỮ trong .srt (bỏ số thứ tự + dòng timestamp)."""
    try:
        raw = open(srt_path, encoding="utf-8").read()
    except OSError:
        return ""
    cau = []
    for kh in raw.strip().split("\n\n"):
        ls = [l for l in kh.splitlines() if l.strip()]
        if len(ls) >= 3:
            cau.append(" ".join(ls[2:]))
    return " ".join(cau)[:gioi_han]


def srt_cua_video(video_path):
    """Tìm .vi.srt khớp video (cùng thư mục, bỏ hậu tố biến thể _longtieng/_phude/_xuly...)."""
    d = os.path.dirname(video_path)
    ten = os.path.basename(video_path)
    ten = re.sub(r"(_longtieng|_phude|_xuly|_bd_tmp)?\.mp4$", "", ten, flags=re.IGNORECASE)
    for cand in (ten + ".vi.srt", os.path.splitext(os.path.basename(video_path))[0] + ".vi.srt"):
        p = os.path.join(d, cand)
        if os.path.isfile(p):
            return p
    return None


def tieu_de_ai(srt_path, log_fn=print):
    """AI tóm tắt phụ đề → 1 tiêu đề Facebook hấp dẫn tiếng Việt (≤ ~100 ký tự)."""
    txt = text_tu_srt(srt_path)
    if not txt:
        return ""
    prompt = (
        "Đây là phụ đề tiếng Việt của 1 video. Hãy đặt 1 TIÊU ĐỀ Facebook tiếng Việt thật HẤP DẪN, "
        "gây tò mò để câu view, NGẮN GỌN (tối đa ~100 ký tự), có thể thêm 1 emoji. "
        "CHỈ trả về đúng tiêu đề, KHÔNG giải thích, KHÔNG dùng ngoặc kép.\n\nPHỤ ĐỀ:\n" + txt)
    try:
        t = ai_dich.goi_ai(prompt, log_fn=lambda m: None)
        t = (t or "").strip().strip('"').splitlines()[0].strip().strip('"')
        return ai_dich._bo_chu_han(t)[:120]
    except Exception as e:
        log_fn("⚠ AI tiêu đề lỗi: " + str(e)[:60])
        return ""


def tieu_de_mau(mau_list, seed):
    """Chọn 1 mẫu tiêu đề (xoay vòng theo seed để không trùng giữa các video)."""
    if not mau_list:
        return ""
    h = sum(ord(c) for c in seed)
    return mau_list[h % len(mau_list)]


def _doc_ten_co_dinh():
    """Đọc tên cố định trong huong_dan_dich.md → {chữ_Hán: Tên Việt}.
    Hỗ trợ 2 dạng: section '## 0.' (cũ, `chữ_Hán` = **Tên**) HOẶC khối 'Fixed:' (mới, '嫖哥 = Tiểu Cường')."""
    d = {}
    try:
        txt = open(os.path.join(GOC, "huong_dan_dich.md"), encoding="utf-8").read()
    except OSError:
        return d
    # Dạng cũ: section '## 0.' với `chữ_Hán` ... = **Tên**
    m = re.search(r"##\s*0\..*?(?=\n##\s)", txt, re.S)
    for line in (m.group(0).splitlines() if m else []):
        mm = re.search(r"`([㐀-鿿]+)`.*?=\s*\*{0,2}\s*([^*\n]+?)\s*\*{0,2}\s*$", line)
        if mm:
            d[mm.group(1)] = mm.group(2).strip()
    # Dạng mới: khối 'Fixed:' — mỗi dòng '汉字 = Tên Việt', dừng ở nhãn/đoạn khác (vd 'Terms:')
    trong_fixed = False
    for line in txt.splitlines():
        s = line.strip()
        if s.lower().rstrip(":") == "fixed":
            trong_fixed = True
            continue
        if trong_fixed:
            mm = re.match(r"^([㐀-鿿]+)\s*=\s*(.+)$", s)
            if mm:
                d.setdefault(mm.group(1), mm.group(2).strip())
            elif s:                       # dòng không rỗng & không phải mapping → hết khối Fixed
                trong_fixed = False
    return d


def tieu_de_thuong(zh_title, fixed_names=None):
    """[BÌNH THƯỜNG — 0 token AI] Dịch TIÊU ĐỀ GỐC: thay tên cố định → bỏ rác Douyin → Google dịch → dọn.
    Title KHÔNG phải tiếng Trung (TikTok Việt, YouTube Anh) → GIỮ NGUYÊN, không dịch."""
    import phu_de
    t = re.split(r"[#＃]", zh_title)[0].strip()              # bỏ phần hashtag
    t = re.sub(r"\s*\[[^\]]*\]\s*$", "", t).strip()          # bỏ [id] cuối (YouTube/TikTok)
    if not re.search(r"[㐀-鿿]", t):                          # không có chữ Hán → giữ nguyên (Việt/Anh)
        return re.sub(r"\s{2,}", " ", t).strip(" .,")
    if fixed_names is None:
        fixed_names = _doc_ten_co_dinh()
    for zh, vi in fixed_names.items():                       # thay tên cố định TRƯỚC khi dịch
        t = t.replace(zh, vi)
    for f in FILLER_ZH:                                      # bỏ cụm rác (完整版解说, 解说...)
        t = t.replace(f, " ")
    t = re.sub(r"\s{2,}", " ", t).strip(" .,!，。！·-")
    vi = phu_de._dich_vi(t, sl="zh-CN") or t
    vi = ai_dich._bo_chu_han(vi)
    return re.sub(r"\s{2,}", " ", vi).strip(" .,")


def got_tieu_de_ai(vi_titles, log_fn=print):
    """[AI CHỈNH SỬA — batch 1 lần cho rẻ] Gọt nhiều tiêu đề Việt thành bản cuốn hơn. Trả list cùng độ dài."""
    if not vi_titles:
        return vi_titles
    dong = ["%d. %s" % (i + 1, t) for i, t in enumerate(vi_titles)]
    prompt = (
        "Gọt lại các tiêu đề Facebook tiếng Việt dưới đây cho NGẮN GỌN & CUỐN hơn (gây tò mò), "
        "tối đa ~90 ký tự, có thể thêm 1 emoji. GIỮ ĐÚNG Ý — KHÔNG bịa thêm số liệu/chi tiết. "
        "Tên riêng để tiếng Việt (không chữ Hán/pinyin). Giữ NGUYÊN số thứ tự.\n"
        "Trả về DUY NHẤT mỗi dòng:  số|tiêu đề đã gọt\n\n" + "\n".join(dong))
    try:
        tra = ai_dich.goi_ai(prompt, log_fn=lambda m: None)
    except Exception as e:
        log_fn("⚠ AI gọt tiêu đề lỗi: " + str(e)[:60])
        return vi_titles
    sua = {}
    for ln in (tra or "").splitlines():
        m = re.match(r"^\s*(\d+)\s*[|.:)\-]\s*(.+?)\s*$", ln)   # bắt 'số|', 'số.', 'số:', 'số)'
        if m:
            sua[int(m.group(1))] = ai_dich._bo_chu_han(m.group(2).strip().strip('"'))
    return [sua.get(i + 1, t) for i, t in enumerate(vi_titles)]


def tao_caption(tieu_de, hashtags, tag_user=None, gioi_han_tag=7):
    """Ghép caption = tiêu đề + dòng trống + hashtag (#lohatech luôn đầu, giới hạn số tag)."""
    tags = ["#lohatech"]
    for h in (hashtags or []) + (tag_user or []):
        h = h.strip()
        if not h:
            continue
        h = h if h.startswith("#") else "#" + h.replace(" ", "")
        if h.lower() not in [x.lower() for x in tags]:
            tags.append(h)
    tags = tags[:gioi_han_tag]
    return (tieu_de.strip() + "\n\n" + " ".join(tags)).strip()
