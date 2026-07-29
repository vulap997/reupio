# -*- coding: utf-8 -*-
"""Tự động dịch zh.srt -> vi.srt qua GEMINI WEB (Playwright, profile đăng nhập sẵn).
Ý chính: KHÔNG bắt Gemini xuất SRT (nó hay làm hỏng format). Gửi CÁC DÒNG CHỮ đánh số → lấy bản dịch
→ TOOL tự GHÉP lại timestamp GỐC + chữ dịch thành vi.srt. Profile persistent: login Gemini 1 lần.
Dùng: python dich_gemini_web.py --srt video.zh.srt --out video.vi.srt --show
"""
import os, sys, time, argparse, re


def doc_srt(path):
    """[(timestamp_line, text)] theo thứ tự."""
    segs = []
    for b in re.split(r"\n\s*\n", open(path, encoding="utf-8").read().strip()):
        lines = [x for x in b.strip().split("\n") if x.strip()]
        if len(lines) >= 3 and "-->" in lines[1]:
            segs.append((lines[1].strip(), " ".join(lines[2:]).strip()))
    return segs


def _slot_giay(ts):
    """'00:00:01,000 --> 00:00:03,000' → số giây khe (en-st), cho ngân sách ký tự khớp lồng tiếng. Lỗi → 0."""
    try:
        a, b = ts.split("-->")
        def _s(x):
            x = x.strip().replace(",", "."); h, m, s = x.split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
        return max(0.0, _s(b) - _s(a))
    except Exception:
        return 0.0


def doc_tm(tm_dir):
    """Nạp QUY TẮC + TỪ ĐIỂN TÊN RIÊNG do người dùng nhập (translation_memory/*.md) để đấu vào prompt.
    Gemini đã dịch tốt → KHÔNG cần luật rườm rà; chỉ cần tên riêng nhất quán + quy tắc user thêm."""
    import glob
    if not tm_dir or not os.path.isdir(tm_dir):
        return ""
    parts = []
    for f in sorted(glob.glob(os.path.join(tm_dir, "*.md"))):
        try:
            t = open(f, encoding="utf-8").read().strip()
            if t:
                parts.append(t)
        except Exception:
            pass
    return "\n\n".join(parts)


def _tim_o_nhap(page, wait_login, log_fn):
    """Chờ ô nhập Gemini (Quill editor) hiện ra → trả element hoặc None (chưa login / đổi UI)."""
    for _ in range(wait_login):
        ed = page.query_selector("div.ql-editor[contenteditable='true']") or \
             page.query_selector("div[contenteditable='true'][role='textbox']") or \
             page.query_selector("div[contenteditable='true']")
        if ed:
            return ed
        time.sleep(1)
    return None


def _doi_phan_hoi(page, min_len, log_fn, done_check=None):
    """Chờ Gemini trả lời trên page đang mở (cuộn load hết element) → text raw.
    done_check(text)->bool: response ĐÃ đủ câu (caller biết số dòng mong đợi). Đủ 2 lần liên tiếp → XONG NGAY,
    KHÔNG chờ length ổn định → fix cold-flaky `wait`~500s (length cứ dao động dù câu trả lời đã tới → loop hết
    160×3s). Không có done_check → fallback cũ: đủ dài + length ổn định 3 lần."""
    resp, cur, last_len, stable, done_stable, _empty0 = "", "", 0, 0, 0, 0
    for k in range(320):
        time.sleep(1.5)    # poll 3→1.5s: bắt 'xong' nhanh hơn (slack sau khi Gemini sinh xong 6s→3s/lô); range×2 giữ cap ~480s
        try:
            page.mouse.wheel(0, 6000)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight);"
                          "document.querySelectorAll('.markdown,message-content')"
                          ".forEach(e=>e.scrollIntoView({block:'end'}))")
        except Exception:
            pass
        els = page.query_selector_all("message-content .markdown, .model-response-text, .markdown")
        # EARLY-ABORT (fix cold-start 'wait~500s'): 0 element trả lời kéo dài = prompt GỬI HỤT (trang chưa
        # sẵn sàng lúc Chrome vừa mở) → Gemini không sinh gì. Thoát SỚM (~60s) để _translate_loop GỬI LẠI
        # (retry trên page đã ấm ăn ngay ~6s) thay vì chờ hết cap 480s. Có element rồi (đang nghĩ/stream) → reset.
        if not els:
            _empty0 += 1
            if _empty0 >= 40:              # 40×1.5s = 60s Gemini 0 phản hồi → chắc gửi hụt → break để gửi lại
                log_fn("   ⚠ Gemini 0 element trả lời ~%ds → nghi GỬI HỤT (cold-start) → thoát sớm, gửi lại." % int(_empty0 * 1.5))
                break
        else:
            _empty0 = 0
        cur = els[-1].inner_text() if els else ""
        cl = len(cur)
        if k % 6 == 0:
            log_fn("   ...resp len=%d (els=%d, stable=%d, done=%d)" % (cl, len(els), stable, done_stable))
        # XONG NGAY: đã đủ câu (done_check) 2 lần liên tiếp → break (kể cả length còn dao động chút cuối).
        if done_check is not None and cl > min_len and done_check(cur):
            done_stable += 1
            if done_stable >= 2:
                resp = cur
                break
        else:
            done_stable = 0
        # fallback (không có done_check / CHƯA đủ câu): đủ dài + NGỪNG tăng 3 lần → xong.
        if cl > min_len and cl == last_len:
            stable += 1
            if stable >= 3:
                resp = cur
                break
        else:
            stable = 0
        last_len = cl
    return resp or cur


_GEM = None   # phiên Gemini BỀN: {"pw","ctx","page"} — giữ Chrome+SPA NÓNG qua render (render_worker, Step 3)
_GEM_LOCK = __import__("threading").Lock()


def _gem_close():
    """Đóng phiên Gemini bền (atexit khi worker thoát, hoặc phiên chết → mở lại)."""
    global _GEM
    g = _GEM; _GEM = None
    if g:
        try: g["ctx"].close()
        except Exception: pass
        try: g["pw"].stop()
        except Exception: pass


def _gem_open(show, profile, log_fn=print):
    """Mở/REUSE phiên Gemini bền. Trả (pw, ctx, page, warm) — warm=True nếu tái dùng phiên đang sống."""
    global _GEM
    import atexit
    from playwright.sync_api import sync_playwright
    with _GEM_LOCK:
        g = _GEM
        if g is not None:
            try:
                if not g["page"].is_closed():
                    return g["pw"], g["ctx"], g["page"], True   # còn nóng → tái dùng
            except Exception:
                pass
            _gem_close()    # phiên chết → dọn rồi mở lại
        os.makedirs(profile, exist_ok=True)
        pw = sync_playwright().start()
        ctx = pw.chromium.launch_persistent_context(
            profile, headless=not show,
            args=["--disable-blink-features=AutomationControlled",
                  "--disable-dev-shm-usage", "--disable-gpu", "--no-sandbox",
                  "--disable-features=IsolateOrigins,site-per-process"],
            viewport={"width": 1200, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        _GEM = {"pw": pw, "ctx": ctx, "page": page}
        atexit.register(_gem_close)
        log_fn("🔥 Gemini mở phiên BỀN (giữ Chrome+SPA nóng qua render).")
        return pw, ctx, page, False


def _translate_loop(page, prompts, wait_login, min_len, log_fn, on_resp, validate, tries):
    """Vòng dịch trên 1 page (mỗi prompt = 1 chat mới /app). Trả (outs, t_load, t_wait).
    DÙNG CHUNG cho đường subprocess (browser mới) lẫn in-process BỀN (browser giữ nóng)."""
    outs = []; n = len(prompts); t_load = 0.0; t_wait = 0.0
    for idx, prompt in enumerate(prompts, 1):
        if n > 1:
            log_fn("[Gemini] Lô %d/%d (chat mới)..." % (idx, n))
        resp = ""
        for attempt in range(1, max(1, tries) + 1):
            # CHAT MỚI mỗi lô (reload /app) → KHÔNG tích luỹ context, mỗi lô dịch độc lập gọn nhẹ.
            _tg = time.time()
            try:
                page.goto("https://gemini.google.com/app", wait_until="domcontentloaded", timeout=60000)
            except Exception:
                pass
            t_load += time.time() - _tg       # = load/hydrate Gemini SPA (lần 1 kèm login-check)
            ed = _tim_o_nhap(page, wait_login if (idx == 1 and attempt == 1) else 40, log_fn)
            if not ed:
                log_fn("[X] Không thấy ô nhập (chưa đăng nhập / Gemini đổi giao diện).")
                time.sleep(3)
                continue
            log_fn("[4] Gõ prompt + gửi (lần %d)..." % attempt)
            ed.click()
            page.keyboard.insert_text(prompt)
            time.sleep(0.6)
            page.keyboard.press("Enter")
            log_fn("[5] Chờ Gemini trả lời...")
            _tw = time.time()
            # done_check = "lô này đã đủ câu chưa" (validate caller) → break NGAY khi đủ, đỡ loop hết timeout.
            resp = _doi_phan_hoi(page, min_len, log_fn,
                                 done_check=(lambda r: validate(idx - 1, r)) if validate else None)
            t_wait += time.time() - _tw       # = thời gian MODEL nghĩ (network/model thật)
            if validate is None or validate(idx - 1, resp):
                break
            log_fn("[!] Lô %d THIẾU câu/lỗi (lần %d/%d) → GỬI LẠI (Gemini tự bù, đỡ rớt Google)..."
                   % (idx, attempt, max(1, tries)))
            time.sleep(4)   # nghỉ trước khi thử lại → giảm throttle
        outs.append(resp)
        if on_resp:
            try: on_resp(idx - 1, resp)   # ghi LŨY TIẾN: timeout vẫn giữ các lô đã xong
            except Exception: pass
        if idx < n:
            time.sleep(2)   # delay giữa lô → giảm throttle Gemini khi dịch NHIỀU lô
    return outs, t_load, t_wait


def hoi_gemini_web_nhieu(prompts, show=False, wait_login=180, min_len=50, log_fn=print,
                         on_resp=None, validate=None, tries=2, keep=False):
    """Gửi NHIỀU prompt vào Gemini web trong CÙNG 1 browser (mỗi prompt = 1 CHAT MỚI, độc lập) → list
    response. Dùng cho CHUNK video dài (mỗi lô ~150-200 câu) — tránh 1 prompt khổng lồ bị Gemini CẮT output.
    on_resp(idx0, resp): gọi NGAY sau mỗi lô (idx0 = 0-based) → caller ghi LŨY TIẾN (timeout vẫn giữ lô đã xong).
    validate(idx0, resp)->bool: lô ĐỦ câu chưa; SAI → GỬI LẠI lô đó (tới `tries` lần) để Gemini tự bù,
    đỡ phải rớt Google. tries = số lần thử mỗi lô."""
    # Fallback profile PHẢI theo MC_BROWSER_DATA_DIR (web_app set = userData khi đóng gói) — KHÔNG dùng
    # đường dẫn tương đối 'MediaCrawler/browser_data/...' trần: khi hàm này chạy TRONG TIẾN TRÌNH web_app
    # (vd _phan_loai_sau_render gọi thẳng, không qua subprocess) và CWD = app-src trong Program Files
    # (READ-ONLY, không admin) → makedirs/Chromium ghi lock file vào đó FAIL WinError 5 Access denied →
    # phân loại AI luôn lỗi → mọi video rớt về thư mục mặc định (không bao giờ vào đúng thể loại).
    profile = os.environ.get("GEMINI_PROFILE_DIR") or os.path.join(
        os.environ.get("MC_BROWSER_DATA_DIR") or os.path.join("MediaCrawler", "browser_data"),
        "gemini_user_data_dir")
    os.makedirs(profile, exist_ok=True)
    n = len(prompts)
    _t_open = 0.0   # PROFILE: startup(browser) / load(SPA goto) / wait(model)
    _to = time.time()
    if keep:        # phiên BỀN: tái dùng Chrome đang nóng (warm=True → open=0); KHÔNG đóng cuối hàm
        pw, ctx, page, _warm = _gem_open(show, profile, log_fn)
        if not _warm:
            _t_open = time.time() - _to
        _own = False
    else:           # CLI/subprocess: mở browser MỚI, đóng khi xong (hành vi cũ)
        from playwright.sync_api import sync_playwright
        # Gemini SPA RẤT NẶNG → headless hay "Target crashed" thiếu cờ → thêm cờ chống crash.
        pw = sync_playwright().start()
        ctx = pw.chromium.launch_persistent_context(
            profile, headless=not show,
            args=["--disable-blink-features=AutomationControlled",
                  "--disable-dev-shm-usage", "--disable-gpu", "--no-sandbox",
                  "--disable-features=IsolateOrigins,site-per-process"],
            viewport={"width": 1200, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        _t_open = time.time() - _to                # = chi phí khởi động Chrome
        _own = True
    try:
        outs, _t_load, _t_wait = _translate_loop(page, prompts, wait_login, min_len, log_fn,
                                                 on_resp, validate, tries)
        if show or os.environ.get("GEMINI_DEBUG"):   # screenshot debug — không ở production headless
            try:
                page.screenshot(path="_gemini_debug.png", full_page=True)
            except Exception:
                pass
    finally:
        if _own:    # phiên bền (keep) KHÔNG đóng → giữ nóng cho render sau
            try: ctx.close()
            except Exception: pass
            try: pw.stop()
            except Exception: pass
    # PROFILE: open=khởi động Chrome (0 nếu warm), load=goto/hydrate SPA, wait=model nghĩ.
    log_fn("GEMPROF|open=%.1f load=%.1f wait=%.1f chunks=%d" % (_t_open, _t_load, _t_wait, n))
    try:        # tích luỹ vào CÙNG jsonl với PROFILE render (localize set VC_PROFILE_LOG)
        _pl = os.environ.get("VC_PROFILE_LOG")
        if _pl:
            import json as _j
            with open(_pl, "a", encoding="utf-8") as _f:
                _f.write(_j.dumps({"t": int(time.time()), "gemini": {
                    "open": round(_t_open, 1), "load": round(_t_load, 1),
                    "wait": round(_t_wait, 1), "chunks": n}}, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return outs


def hoi_gemini_web(prompt, show=False, wait_login=180, min_len=50, log_fn=print):
    """Gửi 1 prompt vào Gemini web → trả CHỮ trả lời (raw). Dùng chung: dịch SRT + phân loại video.
    (Bọc hoi_gemini_web_nhieu với 1 prompt — giữ tương thích ngược cho mọi caller cũ.)"""
    log_fn("[2] Mở Gemini...")
    outs = hoi_gemini_web_nhieu([prompt], show=show, wait_login=wait_login, min_len=min_len, log_fn=log_fn)
    return outs[0] if outs else ""


def _parse_lo(resp, clen):
    """Phân tích 1 lô → {số_local(1..clen): bản_dịch}. Map theo SỐ; lô không đánh số → map theo THỨ TỰ."""
    d = {}
    if not resp:
        return d

    def _clean_prefix(text):
        prev = None
        while text != prev:
            prev = text
            # Clean @00:00:00 or @00:00
            text = re.sub(r"^\s*@\d+(?::\d+){1,2}(?:[.,]\d+)?\s*", "", text)
            # Clean [2.3s ≤37] or similar
            text = re.sub(r"^\s*\[[^\]]*\]\s*", "", text)
            text = text.strip()
        return text

    for l in resp.split("\n"):
        m = re.match(r"^\s*(\d+)\s*[\.\):\-]\s*(.+?)\s*$", l)
        if m:
            k = int(m.group(1))
            if 1 <= k <= clen:
                v = m.group(2).strip().strip('"')
                v = _clean_prefix(v)
                d[k] = v
    if len(d) < clen * 0.6:     # lô KHÔNG đánh số → map theo THỨ TỰ
        seq = [x.strip() for x in resp.split("\n") if x.strip() and not x.strip().endswith(":")]
        seq = [re.sub(r"^\s*\d+\s*[\.\):\-]\s*", "", x) for x in seq]
        seq = [_clean_prefix(x) for x in seq]
        d = {j + 1: seq[j] for j in range(min(len(seq), clen))}
    return d


def _ghep(segs, lo, CHUNK, resps):
    """resps (có thể thiếu lô cuối) → (out_lines, vi_dict). Câu thiếu → giữ zh (localize Google bù)."""
    vi = {}
    for ci, resp in enumerate(resps):
        if ci >= len(lo):
            break
        for k, v in _parse_lo(resp, len(lo[ci])).items():
            vi[ci * CHUNK + k] = v
    out = ["%d\n%s\n%s\n" % (i, ts, vi.get(i, zh)) for i, (ts, zh) in enumerate(segs, 1)]
    return out, vi


def dich_srt(srt_path, out_path, show=False, wait_login=180, tm_dir="translation_memory", log_fn=print, keep=False):
    """Dịch zh.srt → vi.srt IN-PROCESS (cho render_worker bền). keep=True: dùng phiên Gemini bền (giữ nóng
    qua render). Trả code: 0 đủ, 1 srt rỗng, 3 thiếu (<80%). Caller (localize) Google bù câu sót.
    Logic == CLI cũ (tách ra để localize gọi thẳng, KHÔNG spawn subprocess → bỏ overhead + giữ browser)."""
    segs = doc_srt(srt_path)
    log_fn("[1] Đọc %d câu từ %s" % (len(segs), os.path.basename(srt_path)))
    if not segs:
        log_fn("SRT rỗng"); return 1

    # Ngôn ngữ ĐÍCH: TARGET_LANG do web_app truyền (mirror phu_de._dich_vi) — TRƯỚC ĐÂY prompt cứng "TIẾNG VIỆT"
    # bất kể đích gì → chọn đích=en (lồng tiếng Kokoro/edge-en) vẫn ra bản dịch TIẾNG VIỆT (sai hoàn toàn, TTS
    # tiếng Anh đọc phải văn bản Việt). Giờ đọc đích thật → dựng prompt tiếng Anh khi cần.
    tgt = (os.environ.get("TARGET_LANG") or "vi").strip().lower()
    try:                                   # cho MỌI ngôn ngữ đích trong bảng ngon_ngu.LANGS (mirror phu_de._dich_vi)
        import ngon_ngu
        if tgt not in ngon_ngu.HO_TRO:
            tgt = "vi"
    except Exception:
        if tgt not in ("vi", "en", "ko"):
            tgt = "vi"
    if tgt != "vi":
        log_fn("[1a] Đích dịch = %s (không phải Việt) → dùng prompt tiếng Anh." % tgt)

    # Từ điển tên riêng/quy tắc (translation_memory/*.md) BẢN CHẤT là Hán→VIỆT (tên Hán-Việt, thuật ngữ
    # Việt, luật độ-dài tiếng Việt) → CHỈ nạp khi đích=vi. Đích=en nạp vào sẽ ép tên kiểu "Triệu Lộ Tư" vào
    # câu tiếng Anh (đáng lẽ "Zhao Lusi") → BỎ. (Phong cách vẫn giữ vì là lựa chọn văn phong của user.)
    _glossary = doc_tm(tm_dir) if tgt == "vi" else ""
    # Quy tắc dịch: env DICH_QUY_TAC = phong cách ĐÃ CHỌN (web_app, nút chọn-nhiều) → GHÉP THÊM vào từ điển
    # thay vì THAY THẾ — trước đây thay thế làm mất nhất quán Hán-Việt (tên nhân vật...) mỗi khi chọn phong
    # cách. Rỗng ("" tường minh, dùng cho CLI cũ) → không viết lại, cũng không nạp glossary. Không đặt biến →
    # quét thư mục (cách cũ, chỉ vi).
    if "DICH_QUY_TAC" in os.environ:
        _pc = (os.environ.get("DICH_QUY_TAC") or "").strip()
        if _pc:
            tm = (_pc + "\n\n" + _glossary) if _glossary else _pc
            log_fn("[1b] Nạp phong cách đã chọn (%d ký tự) + từ điển tên riêng (%d ký tự) → đấu vào prompt"
                   % (len(_pc), len(_glossary)))
        else:
            tm = ""
    else:
        tm = _glossary
        if tm:
            log_fn("[1b] Nạp quy tắc + từ điển tên riêng (%s, %d ký tự) → đấu vào prompt" % (tm_dir, len(tm)))

    # CHUNK: video DÀI (1 tiếng ~1000+ câu) → 1 prompt khổng lồ làm Gemini CẮT output (rớt Google). Chia LÔ
    # ~CHUNK câu (đánh số LOCAL 1..N mỗi lô — Gemini giữ số nhỏ chuẩn hơn), gửi từng lô (chat riêng) rồi GHÉP.
    try:
        CHUNK = int(os.environ.get("GEMINI_CHUNK", "180") or 180)
    except ValueError:
        CHUNK = 180
    if CHUNK < 20:
        CHUNK = 20
    # KHỚP LỒNG TIẾNG (length-control): câu Việt thường DÀI hơn khe sub → giọng đọc chậm hơn hình (đo thật:
    # median over-length 1.35×, 52% câu >1.3×). Gắn [≤N] ký tự/dòng (N = khe_giây × DUB_CPS) → Gemini dịch
    # NGẮN khớp sẵn → đỡ phải nén/đuổi. Tắt: DUB_FIT_LEN=0. Chỉnh tốc độ đọc giả định: DUB_CPS (ký tự/giây).
    FIT = os.environ.get("DUB_FIT_LEN", "1") != "0"
    try:
        CPS = float(os.environ.get("DUB_CPS", "16") or 16)
    except ValueError:
        CPS = 16.0
    prefix = ""
    if tgt == "vi":
        if tm:   # đấu TỪ ĐIỂN tên riêng + thuật ngữ vào MỖI lô (giữ nhất quán Hán-Việt giữa các lô)
            prefix += ("QUY TẮC + TỪ ĐIỂN TÊN RIÊNG (BẮT BUỘC, nhất quán Hán-Việt):\n"
                       "=== QUY TẮC ===\n" + tm + "\n=== HẾT ===\n\n")
        prefix += ("Bạn là NGƯỜI BẢN NGỮ đang KỂ LẠI câu chuyện dưới đây bằng tiếng Việt — KHÔNG PHẢI máy dịch từng "
                   "chữ. Áp dụng từ điển ở trên.\n"
                   "CÁCH LÀM (theo đúng thứ tự):\n"
                   "1) ĐỌC HẾT cả đoạn dưới trước — đây là 1 ĐOẠN LIÊN TỤC (hội thoại/thuyết minh của CÙNG người "
                   "nói), KHÔNG phải câu rời rạc.\n"
                   "2) HIỂU tình huống: chuyện gì đang xảy ra, ai nói với ai, họ đang muốn truyền đạt điều gì "
                   "(thông tin/cảm xúc/ý định) — không chỉ dịch nghĩa đen từng chữ.\n"
                   "3) Chốt xưng hô + đại từ (tôi/mình/bạn/anh/chị...) và GIỮ NHẤT QUÁN xuyên suốt cả đoạn.\n"
                   "4) VIẾT LẠI từng câu bằng tiếng Việt tự nhiên — NHƯ NGƯỜI VIỆT THẬT SỰ SẼ NÓI trong tình huống "
                   "đó. Mục tiêu là ĐÚNG Ý NGHĨA + CẢM XÚC + TÌNH TIẾT của cả câu chuyện, KHÔNG PHẢI đúng câu chữ "
                   "gốc. ĐƯỢC PHÉP đổi cấu trúc câu, đổi cách diễn đạt, viết lại hoàn toàn khác — miễn giữ đủ thông "
                   "tin và tình tiết. Câu cụt/thiếu chủ ngữ → suy đúng nghĩa từ ngữ cảnh xung quanh.\n"
                   "QUY TẮC PHỤ ĐỀ — bạn LÀM PHỤ ĐỀ cho LỒNG TIẾNG, giọng phải đọc kịp trong khe thời gian mỗi câu "
                   "nên CÀNG NGẮN CÀNG TỐT miễn giữ đủ ý — NGẮN phải là KẾT QUẢ TỰ NHIÊN của việc kể lại theo cách "
                   "người Việt nói, KHÔNG PHẢI dịch sát nghĩa xong rồi mới cắt bớt chữ:\n"
                   "- Nếu Ở TRÊN có yêu cầu VIẾT LẠI theo phong cách → phong cách đó quyết GIỌNG VĂN, nhưng các quy tắc ngắn-gọn/thời-lượng ở đây vẫn là TRẦN độ dài.\n"
                   "- GIỮ ý CỐT LÕI + MỌI chi tiết mô tả (đặc điểm, con số, tính chất được kể) — KHÔNG bỏ tình tiết + KHÔNG bịa. Câu LIỆT KÊ nhiều đặc điểm (vd đặc tính đồ vật) → GIỮ ĐỦ mọi đặc điểm, chỉ rút gọn CÁCH NÓI.\n"
                   "- Thêm DẤU PHẨY / DẤU CHẤM ở chỗ NGẮT NHỊP tự nhiên (tool cắt dòng phụ đề theo các dấu này).\n"
                   "- KHÔNG viết tắt (KHÔNG 'TQ','HN','ko'…) — phụ đề này còn dùng để LỒNG TIẾNG đọc thành tiếng.\n"
                   "- DỊCH 1:1 (RÀNG BUỘC CỨNG, KHÔNG ĐƯỢC PHÁ dù viết lại tự do về CÁCH NÓI): MỖI dòng gốc VẪN → "
                   "ĐÚNG 1 dòng dịch, đúng thứ tự, TUYỆT ĐỐI KHÔNG gộp/tách/bỏ dòng — mỗi dòng gốc gắn 1 khe thời "
                   "gian cố định trong video, gộp/tách sẽ làm LỆCH đồng bộ hình-tiếng (tool dedupe câu trùng TRƯỚC "
                   "khi gửi — bạn KHÔNG cần lo lặp).\n"
                   "  ⚠ KỂ CẢ dòng RẤT NGẮN hay câu DẪN/NỐI ('tóm lại', 'tức là', 'nói cách khác', 'và', 'thì', "
                   "'nó là'…) VẪN phải có 1 dòng dịch RIÊNG mang ĐÚNG số đó — TUYỆT ĐỐI KHÔNG dồn câu dẫn ngắn "
                   "vào dòng kế rồi đánh số lại. Bỏ 1 dòng sẽ làm LỆCH SỐ toàn bộ phụ đề phía sau (chữ hiện sai "
                   "thời điểm, sub gốc dài mà bản dịch ngắn). SỐ DÒNG OUTPUT PHẢI BẰNG SỐ DÒNG INPUT.\n")
        if FIT:
            prefix += ("- KHỚP LỒNG TIẾNG: đầu mỗi dòng có [Ts ≤N] = câu này có T GIÂY để lồng tiếng đọc → hãy dịch "
                       "≤N ký tự để giọng TTS đọc KỊP trong T giây đó (không tràn ra, không chậm hơn hình). Câu NHIỀU "
                       "giây được dài hơn, câu ÍT giây phải thật gọn — căn chữ cho vừa khít T giây. Để đạt ≤N: bỏ từ "
                       "đệm (thật sự, rất rất, một cách, đấy, ấy mà, vô cùng, thì, là…) + chọn từ NGẮN đồng nghĩa. "
                       "Nếu buộc dài hơn mới đủ ý thì ưu tiên NGHĨA. TUYỆT ĐỐI KHÔNG in [Ts ≤N] vào bản dịch.\n")
        prefix += ("LƯU Ý INPUT: '@HH:MM:SS' đầu mỗi dòng = MỐC GIỜ câu xuất hiện trong video — CHỈ để bạn hiểu "
                   "TIMING + nhận ra câu TRÙNG kề nhau (2 dòng sát giờ + cùng ý = phụ đề song ngữ). TUYỆT ĐỐI "
                   "KHÔNG in '@HH:MM:SS' vào bản dịch.\n"
                   "CHỈ trả về BẢN DỊCH: mỗi dòng MỘT câu, GIỮ NGUYÊN số thứ tự '1.' '2.'… đầu mỗi dòng, đúng "
                   "thứ tự, KHÔNG gộp/tách dòng. TUYỆT ĐỐI KHÔNG thêm chữ nào khác — không lời dẫn, không xác "
                   "nhận, không giải thích, không markdown:\n\n")
    else:   # tgt != vi: dich sang NGON NGU DICH bat ky (parametric theo ten tieng Anh) — GOP en/ko/fr/es/th/de...
        try:
            import ngon_ngu
            _LN = (ngon_ngu.LANGS.get(tgt) or {}).get("ten_en") or tgt.upper()
        except Exception:
            _LN = {"en": "English", "ko": "Korean", "fr": "French", "es": "Spanish", "pt": "Portuguese",
                   "th": "Thai", "de": "German", "it": "Italian", "ja": "Japanese", "ru": "Russian",
                   "id": "Indonesian", "hi": "Hindi", "ar": "Arabic"}.get(tgt, tgt.upper())
        _NL = chr(10)
        if tm:
            prefix += "RULES + STYLE (MANDATORY, keep consistent):" + _NL + "=== RULES ===" + _NL + tm + _NL + "=== END ===" + _NL + _NL
        _pl = [
            "You are a NATIVE {L} SPEAKER retelling the story below in {L} - you are NOT a word-for-word translation machine. Write in the native script of {L} - do NOT romanize (e.g. Hangul for Korean, Thai script for Thai).",
            "HOW TO DO THIS (follow in order):",
            "1) READ THE WHOLE PASSAGE below first - it is ONE CONTINUOUS passage (dialogue/narration by the SAME speaker), NOT isolated sentences.",
            "2) UNDERSTAND the situation: what is happening, who is speaking to whom, what are they trying to convey (information/emotion/intent) - not just the literal words.",
            "3) Decide the register/pronouns and keep them CONSISTENT throughout the whole passage.",
            "4) REWRITE each line in natural {L}, the way a real {L} speaker would actually say it in that situation. Your goal is to preserve the MEANING, EMOTION and STORY of the whole conversation, NOT the exact wording of the source. You MAY restructure sentences, change phrasing, or rewrite it completely differently - as long as no information or plot detail is lost. A fragment or subject-less line -> infer the real meaning from context.",
            "SUBTITLE RULES - you are a professional SUBTITLE LOCALIZER for DUBBING; the voice must finish within each line's time slot, so SHORTER IS BETTER as long as meaning survives - brevity must come NATURALLY from retelling it the way a native speaker would, NOT from translating literally first and then trimming words:",
            "- If a STYLE rewrite is requested above, that style controls the TONE - but these timing/brevity rules still cap the LENGTH.",
            "- Keep the CORE meaning + ALL descriptive facts (attributes, numbers, qualities being described) - NEVER drop a plot detail and NEVER invent anything. If a line LISTS several attributes, keep EVERY attribute - only shorten the wording, never the list.",
            "- Add natural punctuation at pauses (the tool splits subtitle lines on these marks).",
            "- Do NOT abbreviate and do NOT romanize - this subtitle is also read aloud for DUBBING.",
            "- 1:1 TRANSLATION (HARD CONSTRAINT, DO NOT BREAK even though you rewrite freely in WORDING): EACH source line MUST STILL map to EXACTLY 1 translated line, same order - NEVER merge/split/drop lines (each source line is tied to a fixed time slot in the video; merging/splitting breaks audio-video sync). OUTPUT LINE COUNT MUST EQUAL INPUT LINE COUNT.",
            "  EVEN very short filler or connector lines MUST still get their OWN line with the EXACT SAME number - never merge a short line into the next one and renumber.",
        ]
        prefix += (_NL.join(_pl) + _NL).replace("{L}", _LN)
        if FIT:
            prefix += "- DUB TIMING: each line starts with [Ts <=N] = this line has T SECONDS to be read aloud for dubbing -> translate to <=N characters so the TTS voice finishes within T seconds. Lines with MORE seconds can be longer; lines with FEW seconds must be very tight. If a longer phrasing is required to keep the meaning, prioritize MEANING. NEVER print [Ts <=N] in the translation." + _NL
        prefix += ("INPUT NOTE: '@HH:MM:SS' at the start of each line = the TIME MARK the line appears in the video - ONLY for you to understand TIMING + spot ADJACENT DUPLICATE lines. NEVER print '@HH:MM:SS' in the translation." + _NL + "RETURN ONLY THE TRANSLATION in " + _LN + ": one line per sentence, KEEP the exact numbering 1. 2. at the start of each line, same order, do NOT merge or split lines. NEVER add anything else - no preamble, no confirmation, no explanation, no markdown:" + _NL + _NL)
    lo = [segs[i:i + CHUNK] for i in range(0, len(segs), CHUNK)]

    def _pline(j, ts, zh):
        tg = ts.split("-->")[0].strip().split(",")[0] if ("-->" in (ts or "")) else ""   # mốc giờ BẮT ĐẦU HH:MM:SS
        tg = ("@%s " % tg) if tg else ""
        if FIT:
            s = _slot_giay(ts)
            if s > 0:
                return "%d. %s[%.1fs ≤%d] %s" % (j + 1, tg, s, max(10, round(s * CPS)), zh)
        return "%d. %s%s" % (j + 1, tg, zh)
    prompts = [prefix + "\n".join(_pline(j, ts, zh) for j, (ts, zh) in enumerate(chunk))
               for chunk in lo]
    if len(lo) > 1:
        log_fn("[2] Video DÀI %d câu → chia %d lô (~%d câu/lô) gửi Gemini (tránh cắt output)" % (
            len(segs), len(lo), CHUNK))

    # validate: lô ĐỦ câu chưa (≥90%) → thiếu thì hoi_gemini_web_nhieu GỬI LẠI lô đó (Gemini tự bù).
    def _du(ci, resp):
        return len(_parse_lo(resp, len(lo[ci]))) >= len(lo[ci]) * 0.9

    resps_acc = [""] * len(prompts)
    def _ghi(ci, resp):           # ghi LŨY TIẾN sau mỗi lô → timeout/crash vẫn giữ các lô đã xong
        resps_acc[ci] = resp
        try:
            log_fn("📝 Dịch xong lô %d/%d (câu %d–%d)" % (
                ci + 1, len(lo), ci * CHUNK + 1, min(len(segs), (ci + 1) * CHUNK)))
        except Exception:
            pass
        try:
            out_l, _ = _ghep(segs, lo, CHUNK, resps_acc)
            open(out_path, "w", encoding="utf-8").write("\n".join(out_l))
        except Exception:
            pass

    _tries = 3 if len(lo) > 1 else 2     # video dài: thử lại tới 3 lần/lô để Gemini đủ câu, đỡ rớt Google
    resps = hoi_gemini_web_nhieu(prompts, show=show, wait_login=wait_login,
                                 on_resp=_ghi, validate=_du, tries=_tries, log_fn=log_fn, keep=keep)
    log_fn("[6] Ghép theo SỐ thứ tự trong từng lô (bền với lệch)...")
    out, vi = _ghep(segs, lo, CHUNK, resps)
    open(out_path, "w", encoding="utf-8").write("\n".join(out))
    log_fn("[7] GHÉP xong: %s — %d/%d câu (%d lô)" % (out_path, len(vi), len(segs), len(lo)))
    return 0 if len(vi) >= len(segs) * 0.8 else 3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--srt", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--show", action="store_true", help="hiện cửa sổ (để login lần đầu)")
    ap.add_argument("--wait-login", type=int, default=180, help="giây chờ đăng nhập")
    ap.add_argument("--tm", default="translation_memory", help="thư mục quy tắc + từ điển tên riêng")
    a = ap.parse_args()
    # CLI = một lần (subprocess fallback): keep=False → mở browser mới, đóng khi xong (hành vi cũ y nguyên).
    return dich_srt(a.srt, a.out, show=a.show, wait_login=a.wait_login, tm_dir=a.tm,
                    log_fn=lambda m: print(m, flush=True), keep=False)


if __name__ == "__main__":
    sys.exit(main())
