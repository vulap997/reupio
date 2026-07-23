# -*- coding: utf-8 -*-
"""Tự PHÂN LOẠI video theo THỂ LOẠI → route vào đúng folder đích khi render.

Cấu hình (web_app truyền vào): list đường dẫn ĐÍCH đầy đủ (vd C:/Users/Admin/video/mukbang),
basename của path = NHÃN thể loại; + 1 folder MẶC ĐỊNH cho ca không khớp.

Quy trình (rẻ trước, đắt sau — Gemini web headless NẶNG):
  1. Từ khóa cào (trong path .../tu-khoa/<kw>/ hoặc kenh/<tên>) khớp tên thể loại → route THẲNG, KHỎI gọi AI.
  2. Cache (từ khóa|tiêu đề → nhãn) — video đã phân loại khỏi gọi lại.
  3. Phần còn lại GOM 1 BATCH → 1 prompt Gemini web (dich_gemini_web.hoi_gemini_web) → nhãn từng video.
     Gemini được phép TỰ ĐẶT thể loại MỚI nếu không hợp thể loại nào đã có.
  4. Nhãn khớp thể loại sẵn → path đó. Nhãn MỚI + có folder mặc định → TẠO FOLDER CON trong mặc định
     (<default>/<tên mới>). AI rớt/chưa login/không tín hiệu → folder MẶC ĐỊNH (graceful, không crash).
Đầu vào phân loại = từ khóa + tiêu đề (+ lời từ .srt CẠNH video NẾU đã có; không tự chạy ASR).
"""
import json
import os
import re


def _ten_the_loai(path):
    """basename của đường dẫn đích = nhãn thể loại. Vd C:/.../video/mukbang → 'mukbang'."""
    return os.path.basename(str(path).replace("\\", "/").rstrip("/"))


def _chuan(s):
    """Chuẩn hóa để SO KHỚP: hạ thường + gọn khoảng trắng (giữ unicode để tên Trung/Việt vẫn khớp được)."""
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def _safe_folder(n):
    """Nhãn thể loại (AI tự đặt) -> tên folder an toàn Windows: bỏ ký tự cấm + path traversal + rút gọn."""
    n = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", str(n or "")).strip().strip(".")
    n = re.sub(r"\s+", " ", n).strip()
    return n[:60]


def _resolve_nhan(nhan, nhan2path, default_dir):
    """Nhãn AI trả -> folder đích. Khớp thể loại ĐÃ CÓ (theo _chuan) -> đúng path đã cấu hình. KHÔNG khớp
    mà có default_dir -> THỂ LOẠI MỚI: tạo FOLDER CON trong folder mặc định (<default>/<tên mới>) — do
    caller makedirs. Không có default -> default_dir (rỗng = cạnh gốc)."""
    p = nhan2path.get(_chuan(nhan))
    if p:
        return p
    safe = _safe_folder(nhan)
    if default_dir and safe:
        return os.path.join(default_dir, safe)
    return default_dir


def _meta_tu_path(video_path):
    """Suy (keyword, title, srt_text) từ đường dẫn video + filename + .srt cạnh bên (nếu có)."""
    p = str(video_path).replace("\\", "/")
    parts = p.split("/")
    keyword = ""
    for moc in ("tu-khoa", "kenh"):
        if moc in parts:
            i = parts.index(moc)
            keyword = parts[i + 1] if i + 1 < len(parts) else ""
            break
    base = os.path.splitext(os.path.basename(p))[0]
    title = re.sub(r"_(xuly|phude|longtieng|mix|dub)$", "", base, flags=re.I)  # bỏ hậu tố bản render
    # SRT cạnh video (CHỈ đọc nếu đã có — KHÔNG tự chạy ASR). Lấy phần chữ, cắt ngắn cho prompt gọn.
    srt_text = ""
    stem = os.path.splitext(str(video_path))[0]
    for ext in (".vi.srt", ".zh.srt"):
        sp = stem + ext
        if os.path.exists(sp):
            try:
                txt = open(sp, encoding="utf-8").read()
                lines = [l.strip() for l in txt.splitlines()
                         if l.strip() and "-->" not in l and not l.strip().isdigit()]
                srt_text = " ".join(lines)[:400]
            except Exception:
                srt_text = ""
            break
    return keyword, title, srt_text


def _cache_path(cache_dir):
    return os.path.join(cache_dir or ".", "_phan_loai_cache.json")


def _load_cache(path):
    if os.path.exists(path):
        try:
            return json.load(open(path, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(path, c):
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def _goi_ai_batch(items, nhan_list, log_fn):
    """items: [(path, kw, title, srt, ck)] → gửi 1 prompt Gemini web → {path: nhãn-thô}."""
    try:
        import dich_gemini_web
    except Exception as e:
        log_fn("[phan_loai] không import được dich_gemini_web: %s" % e)
        return {}
    dong = []
    for idx, (p, kw, title, srt, ck) in enumerate(items, 1):
        ctx = ("[%s] %s" % (kw, title)) if kw else title
        if srt:
            ctx += " | lời: " + srt[:200]
        dong.append("%d. %s" % (idx, ctx))
    prompt = (
        "Phân loại mỗi video dưới đây vào 1 thể loại.\n"
        "Thể loại ĐÃ CÓ: [%s].\n"
        "Mỗi dòng là 1 video: 'số. [từ khóa] tiêu đề | lời'. Dựa vào từ khóa + tiêu đề (+ lời nếu có) để đoán.\n"
        "QUY TẮC:\n"
        "- Nếu video HỢP với 1 thể loại đã có → dùng CHÍNH XÁC tên đó.\n"
        "- Nếu KHÔNG hợp thể loại nào đã có → tự ĐẶT một tên thể loại MỚI, ngắn gọn (2-4 từ tiếng Việt).\n"
        "TRẢ VỀ: mỗi video 1 dòng dạng 'số=Tên thể loại'. KHÔNG giải thích, KHÔNG markdown.\n\n"
        % ", ".join(nhan_list)
    ) + "\n".join(dong)
    try:
        # wait_login NGẮN (25s): phân loại chạy NỀN tự động — Gemini đã login thì ô nhập hiện nhanh;
        # CHƯA login thì KHÔNG chờ 3 phút (mặc định 180s của bản dịch) → fallback folder mặc định sớm.
        resp = dich_gemini_web.hoi_gemini_web(prompt, min_len=3, wait_login=25, log_fn=log_fn)
    except Exception as e:
        log_fn("[phan_loai] Gemini web lỗi: %s" % e)
        resp = ""
    ket = {}
    for l in (resp or "").splitlines():
        m = re.match(r"^\s*(\d+)\s*[=:.\)\-]\s*(.+?)\s*$", l)
        if m:
            k = int(m.group(1))
            if 1 <= k <= len(items):
                ket[items[k - 1][0]] = m.group(2).strip().strip('"').strip("*").strip()
    return ket


def phan_loai_lo(paths, muc, default_dir, cache_dir=".", log_fn=print):
    """Phân loại 1 LÔ video → {path: out_dir đích}.
    muc: list [{"ten": nhãn thể loại, "path": folder đích ĐẦY ĐỦ tự do}] — user TOÀN QUYỀN đặt path bất
    kỳ (tên thể loại tách rời path, không cần = basename). default_dir: folder mặc định (rỗng = '').
    Chưa cấu hình → tất cả về default_dir."""
    paths = list(paths or [])
    muc = [m for m in (muc or [])
           if isinstance(m, dict) and str(m.get("ten") or "").strip() and str(m.get("path") or "").strip()]
    if not muc:
        return {p: default_dir for p in paths}
    nhan2path, nhan_list = {}, []
    for m in muc:
        ten = str(m["ten"]).strip()
        nhan_list.append(ten)
        nhan2path[_chuan(ten)] = str(m["path"]).strip()
    cache_p = _cache_path(cache_dir)
    cache = _load_cache(cache_p)
    out, can_ai = {}, []
    for p in paths:
        kw, title, srt = _meta_tu_path(p)
        ckw = _chuan(kw)
        if ckw and ckw in nhan2path:                 # 1) từ khóa trùng tên thể loại → route thẳng
            out[p] = nhan2path[ckw]
            continue
        ck = ckw + "|" + _chuan(title)
        cached = cache.get(ck)
        if cached:                                    # 2) cache (khớp thể loại sẵn HOẶC thể loại mới đã đặt)
            out[p] = _resolve_nhan(cached, nhan2path, default_dir)
            continue
        can_ai.append((p, kw, title, srt, ck))
    if can_ai:                                        # 3) batch AI cho phần còn lại
        log_fn("[phan_loai] %d video cần AI phân loại (đã route %d theo từ khóa/cache)"
               % (len(can_ai), len(out)))
        ket = _goi_ai_batch(can_ai, nhan_list, log_fn)
        dirty = False
        for (p, kw, title, srt, ck) in can_ai:
            raw = (ket.get(p) or "").strip()
            if raw:                                   # AI trả nhãn → thể loại sẵn HOẶC thể loại MỚI (folder con default)
                out[p] = _resolve_nhan(raw, nhan2path, default_dir)
                cache[ck] = raw                       # cache nhãn thô (kể cả mới) → lần sau nhất quán
                dirty = True
            else:
                out[p] = default_dir                  # 4) AI rớt (rỗng) → mặc định
        if dirty:
            _save_cache(cache_p, cache)
    return out
