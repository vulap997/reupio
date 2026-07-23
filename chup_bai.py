# -*- coding: utf-8 -*-
"""
CHỤP ẢNH BÀI VIẾT + TOP COMMENT (cho reup — học tập).

- Reddit: old.reddit.com (gọn, không cần đăng nhập với bài công khai).
- Threads (Meta): post công khai (cookie chỉ cần khi bài bị giới hạn).
  LƯU Ý: 1 post Threads dài có thể tách thành NHIỀU tin nhắn nối tiếp của cùng tác giả
  (thread chain) → gom hết chuỗi OP đầu thành "post", phần sau mới là comment.

Xuất: mỗi ô 1 ảnh (00_post.png, 01_post.png nếu thread dài, 02_comment.png ...) + noi_dung.json.
noi_dung.json schema:
  {"url","platform","items":[{"loai":"post|comment","anh","author",
                              "vung":[{"text","bbox":[x,y,w,h]}], "tts":"..."}]}

Dùng:
  python chup_bai.py --platform rd --url "<link reddit>" --comments 10
  python chup_bai.py --platform th --url "<link threads>" --comments 10 [--cookies cookies.txt]

  # LƯỚT FEED Threads (Trang chủ For you) → tự lọc bài ĐẠT NGƯỠNG rồi cào:
  python chup_bai.py --platform th --mode feed --cookies cookies.txt \
      --posts 5 --min-like 2000 --min-cmt 100 --max-cmt 20 [--debug --show]
  (feed cần --cookies đăng nhập Threads; --debug in số tim/cmt dò được mỗi bài để hiệu chỉnh)
"""
import argparse
import json
import os
import re
import sys
import urllib.parse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

THU_MUC_GOC = os.path.dirname(os.path.abspath(__file__))
DSF = 2  # device_scale_factor khi chụp → ảnh có kích thước = css * DSF


def log(msg):
    print("LOG:" + msg, flush=True)


def an_toan(ten):
    ten = re.sub(r'[<>:"/\\|?*\n\r\t]+', " ", ten or "").strip()
    ten = re.sub(r"\s+", " ", ten)
    return (ten[:60] or "bai").rstrip(". ")


def _bbox(parent_el, child_el):
    """Toạ độ child trong ảnh chụp của parent (px ảnh). None nếu lỗi."""
    try:
        p = parent_el.bounding_box()
        c = child_el.bounding_box()
        if p and c:
            return [round((c["x"] - p["x"]) * DSF), round((c["y"] - p["y"]) * DSF),
                    round(c["width"] * DSF), round(c["height"] * DSF)]
    except Exception:
        pass
    return None


def _bbox_union(parent_box, boxes):
    if not (parent_box and boxes):
        return None
    x1 = min(b["x"] for b in boxes)
    y1 = min(b["y"] for b in boxes)
    x2 = max(b["x"] + b["width"] for b in boxes)
    y2 = max(b["y"] + b["height"] for b in boxes)
    return [round((x1 - parent_box["x"]) * DSF), round((y1 - parent_box["y"]) * DSF),
            round((x2 - x1) * DSF), round((y2 - y1) * DSF)]


def _luu_meta(out, url, platform, items):
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "noi_dung.json"), "w", encoding="utf-8") as f:
        json.dump({"url": url, "platform": platform, "items": items}, f, ensure_ascii=False, indent=2)


# ---------------- Reddit ----------------
def reddit_old_url(url, sort):
    u = re.sub(r"https?://(www\.|new\.)?reddit\.com", "https://old.reddit.com", url.strip(), flags=re.I)
    if not u.lower().startswith("http"):
        u = "https://old.reddit.com" + ("" if u.startswith("/") else "/") + u
    sep = "&" if "?" in u else "?"
    return f"{u}{sep}sort={sort or 'top'}&limit=200"


def reddit_id(url):
    m = re.search(r"/comments/([a-z0-9]+)", url, re.I)
    return m.group(1) if m else an_toan(url.rsplit("/", 1)[-1] or "bai")


def chup_reddit(ctx, url, n, sort, out):
    page = ctx.new_page()
    old = reddit_old_url(url, sort)
    log(f"🌐 Mở: {old}")
    page.goto(old, wait_until="domcontentloaded", timeout=60000)
    page.add_style_tag(content=(
        ".commentarea .child{display:none!important}"
        ".side{display:none!important}"
        ".content{margin:0 0 0 5px!important;max-width:760px!important}"
        ".infobar,.premium-banner-outer,.listingsignupbar,.create{display:none!important}"
        "#redesign-beta-optin-btn,.redesign-beta-optin{display:none!important}"))
    try:
        page.wait_for_selector("#siteTable .thing", timeout=30000)
    except Exception:
        log("⚠ Không thấy nội dung bài (có thể bị xóa/khóa/NSFW).")
        page.close()
        return []

    os.makedirs(out, exist_ok=True)
    items = []
    idx = 0

    post = page.query_selector("#siteTable > .thing")
    if post:
        try:
            post.scroll_into_view_if_needed(timeout=5000)
            fn = f"{idx:02d}_post.png"
            post.screenshot(path=os.path.join(out, fn))
            tieu_de = post.query_selector("a.title")
            body = post.query_selector(".entry .usertext-body")
            vung, tts = [], []
            if tieu_de:
                t = tieu_de.inner_text().strip()
                vung.append({"text": t, "bbox": _bbox(post, tieu_de)})
                tts.append(t)
            if body:
                t = body.inner_text().strip()
                if t:
                    vung.append({"text": t, "bbox": _bbox(post, body)})
                    tts.append(t)
            items.append({"loai": "post", "anh": fn, "author": post.get_attribute("data-author") or "",
                          "vung": [v for v in vung if v["bbox"]], "tts": ". ".join(tts)})
            idx += 1
            log("📸 Đã chụp bài (00_post.png)")
        except Exception as e:
            log(f"⚠ Lỗi chụp bài: {str(e)[:120]}")

    for c in page.query_selector_all(".commentarea > .sitetable > .thing.comment"):
        if idx - 1 >= n:
            break
        author = (c.get_attribute("data-author") or "").strip()
        if author.lower() in ("automoderator", "[deleted]", ""):
            continue
        body_el = c.query_selector(".entry .usertext-body")
        if not body_el:
            continue
        txt = body_el.inner_text().strip()
        if not txt or txt in ("[deleted]", "[removed]"):
            continue
        try:
            c.scroll_into_view_if_needed(timeout=5000)
            fn = f"{idx:02d}_comment.png"
            c.screenshot(path=os.path.join(out, fn))
            bb = _bbox(c, body_el)
            items.append({"loai": "comment", "anh": fn, "author": author,
                          "vung": [{"text": txt, "bbox": bb}] if bb else [], "tts": txt})
            log(f"📸 Comment {idx}: {author}")
            idx += 1
        except Exception as e:
            log(f"⚠ Lỗi chụp comment: {str(e)[:120]}")

    _luu_meta(out, url, "reddit", items)
    page.close()
    log(f"✔ Reddit: {len(items)} ảnh → {os.path.relpath(out, THU_MUC_GOC)}")
    return items


def _rd_listing_items(page):
    """Quét trang listing old.reddit (subreddit / r/all) → [(url, score, cmt)]."""
    out = []
    for t in page.query_selector_all("#siteTable > .thing.link"):
        if (t.get_attribute("data-promoted") or "").lower() == "true":
            continue
        perma = t.get_attribute("data-permalink") or ""
        try:
            score = int(t.get_attribute("data-score") or "-1")
        except ValueError:
            score = -1
        cl = t.query_selector("a.comments")
        cmt = _parse_count(cl.inner_text()) if cl else -1
        if perma:
            out.append(("https://old.reddit.com" + perma, score, cmt))
    return out


def _rd_search_items(page):
    """Quét trang search old.reddit (.search-result-link) → [(url, score, cmt)]."""
    out = []
    for t in page.query_selector_all(".search-result-link"):
        a = t.query_selector("a.search-title") or t.query_selector("a.search-comments")
        href = (a.get_attribute("href") or "") if a else ""
        sc = t.query_selector(".search-score")
        cm = t.query_selector(".search-comments")
        score = _parse_count(sc.inner_text()) if sc else -1
        cmt = _parse_count(cm.inner_text()) if cm else -1
        if href:
            out.append((href, score, cmt))
    return out


def chup_reddit_feed(ctx, list_url, is_search, n_posts, max_cmt, sort,
                     min_like, min_cmt, out_root, debug=False):
    """Mở 1 trang listing/search old.reddit, lọc bài đạt ngưỡng (điểm>=min_like HOẶC cmt>=min_cmt),
    rồi cào từng bài (tối đa max_cmt comment). old.reddit công khai → KHÔNG cần đăng nhập.
    Trả list dict {url, out, items, like, cmt}."""
    page = ctx.new_page()
    log(f"🌐 Mở {'tìm kiếm' if is_search else 'feed'} Reddit: {list_url}")
    page.goto(list_url, wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_selector(".search-result-link, #siteTable .thing", timeout=30000)
    except Exception:
        log("⚠ Không thấy bài nào (subreddit sai / bị chặn / từ khóa rỗng).")
        page.close()
        return []
    items = _rd_search_items(page) if is_search else _rd_listing_items(page)
    page.close()
    chon = []
    for url, score, cmt in items:
        if debug:
            log(f"   • {reddit_id(url)}: ⬆{score} 💬{cmt}")
        if score >= min_like or cmt >= min_cmt:
            chon.append((url, score, cmt))
            if len(chon) >= n_posts:
                break
    if not chon:
        log("⚠ Không có bài nào đạt ngưỡng (giảm ngưỡng / đổi subreddit / --debug để xem).")
        return []
    log(f"🔎 Lọc được {len(chon)} bài đạt ngưỡng → cào (tối đa {max_cmt} comment/bài).")
    ket = []
    for url, score, cmt in chon:
        out = os.path.join(out_root, reddit_id(url))
        try:
            its = chup_reddit(ctx, url, max_cmt, sort, out)
            ket.append({"url": url, "out": out, "items": len(its), "like": score, "cmt": cmt})
        except Exception as e:
            log(f"⚠ Lỗi cào {url}: {str(e)[:120]}")
    return ket


# ---------------- Threads (Meta) ----------------
def threads_op(url):
    m = re.search(r"/@([^/]+)/post/", url, re.I)
    return m.group(1).lower() if m else ""


def _th_author(container):
    a = container.query_selector('a[href^="/@"]')
    h = (a.get_attribute("href") or "") if a else ""
    return h.strip("/").lstrip("@").split("/")[0].lower()


def _th_body(container):
    """Trả (text, bbox) body của 1 ô Threads. Body = span[dir=auto] KHÔNG trong <a>,
    bỏ timestamp (4d/1h) và span chỉ có số/emoji."""
    pbox = container.bounding_box()
    parts, boxes = [], []
    for s in container.query_selector_all('span[dir="auto"]'):
        try:
            if s.evaluate('e=>!!e.closest("a")'):
                continue
        except Exception:
            continue
        t = (s.inner_text() or "").strip()
        if len(t) < 2:
            continue
        if re.match(r"^\d{1,2}\s*[smhdwy]$", t):              # timestamp 4d / 1h
            continue
        if re.match(r"^[\d.,]+\s*[KMBkmb]?$", t):             # lượt tương tác: 3,4K / 599 / 170
            continue
        if t in ("Author", "Translate", "See translation", "Dịch", "More", "Thêm"):
            continue
        if not re.search(r"[A-Za-zÀ-ỹ]", t):                  # chỉ emoji / ký tự
            continue
        parts.append(t)
        bb = s.bounding_box()
        if bb:
            boxes.append(bb)
    return " ".join(parts).strip(), _bbox_union(pbox, boxes)


def _th_anh_kem(container):
    """Các <img> ẢNH NỘI DUNG (ảnh người dùng đính kèm) trong 1 ô Threads — bỏ avatar/icon nhỏ."""
    out = []
    for im in container.query_selector_all("img"):
        try:
            if im.evaluate('e=>!!e.closest(\'a[href^="/@"]\')'):   # avatar nằm trong link profile
                continue
            bb = im.bounding_box()
            if bb and bb["width"] >= 150 and bb["height"] >= 150:
                out.append(im)
        except Exception:
            continue
    return out


def _ocr_anh_kem(images, tmp_dir, prefix, lang):
    """Chụp từng <img> đính kèm → OCR → gộp text (đã strip). '' nếu không có ảnh/không đọc được chữ."""
    import ocr_anh
    parts = []
    for k, im in enumerate(images):
        tmp = os.path.join(tmp_dir, f"_ocr_{prefix}_{k}.png")
        try:
            im.scroll_into_view_if_needed(timeout=4000)
            im.screenshot(path=tmp)
            t = ocr_anh.ocr_anh(tmp, lang).strip()
            if t:
                parts.append(t)
                log(f"   📝 OCR ảnh kèm: +{len(t)} ký tự")
        except Exception as e:
            log(f"   ⚠ OCR ảnh kèm lỗi: {str(e)[:90]}")
        finally:
            try:
                if os.path.isfile(tmp):
                    os.remove(tmp)
            except OSError:
                pass
    return " ".join(parts).strip()


def chup_threads(ctx, url, n, out, ocr_lang=None):
    page = ctx.new_page()
    ocr_lang = ocr_lang or os.environ.get("OCR_LANG", "vie+eng")
    # Bật OCR ảnh kèm nếu Tesseract sẵn sàng (báo 1 lần nếu thiếu rồi bỏ qua, không làm gãy chụp).
    try:
        import ocr_anh
        ocr_ok, ocr_msg = ocr_anh.chuan_bi()
    except Exception as e:
        ocr_ok, ocr_msg = False, str(e)[:120]
    if not ocr_ok:
        log(f"ℹ OCR ảnh kèm TẮT ({ocr_msg or 'thiếu Tesseract'}) → chỉ đọc chữ bài/comment.")
    op = threads_op(url)
    log(f"🌐 Mở Threads: {url} (OP=@{op})")
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3500)
    # Ẩn tường/popup đăng nhập (hiện khi cuộn sâu lúc chưa login) — áp cả cho popup xuất hiện sau
    try:
        page.add_style_tag(content='div[role="dialog"],div[aria-modal="true"]{display:none!important}')
    except Exception:
        pass
    for sel in ('div[role="dialog"] div[aria-label="Close"]', 'div[aria-label="Đóng"]'):
        el = page.query_selector(sel)
        if el:
            try:
                el.click(timeout=2000)
            except Exception:
                pass
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass

    containers = page.query_selector_all('div[data-pressable-container="true"]')
    if not containers:
        log("⚠ Threads: không nhận diện được bài (layout đổi / cần --cookies).")
        page.close()
        return []

    os.makedirs(out, exist_ok=True)
    items = []
    idx = 0
    cnt_cmt = 0
    trong_post = True
    for c in containers:
        au = _th_author(c)
        if trong_post and au and op and au != op:
            trong_post = False
        if not trong_post and cnt_cmt >= n:
            break
        text, bbox = _th_body(c)
        loai = "post" if trong_post else "comment"
        try:
            c.scroll_into_view_if_needed(timeout=5000)
            page.wait_for_timeout(250)
            # OCR ảnh ĐÍNH KÈM (nếu có) → GỘP vào lời đọc (tts). KHÔNG tạo item riêng,
            # KHÔNG tính thành comment khác; ảnh vẫn nằm trong khung chụp của comment đó.
            ocr_text = _ocr_anh_kem(_th_anh_kem(c), out, str(idx), ocr_lang) if ocr_ok else ""
            doc = (text + " " + ocr_text).strip()
            if loai == "comment":
                if not doc:                 # cả chữ thân lẫn chữ trong ảnh đều rỗng → bỏ
                    continue
                cnt_cmt += 1
            fn = f"{idx:02d}_{loai}.png"
            c.screenshot(path=os.path.join(out, fn))
            items.append({"loai": loai, "anh": fn, "author": au,
                          "vung": [{"text": text, "bbox": bbox}] if (text and bbox) else [],
                          "tts": doc})
            log(f"📸 {'Bài (phần ' + str(idx+1) + ')' if loai=='post' else 'Comment ' + str(cnt_cmt)}: @{au}"
                + (" +OCR ảnh" if ocr_text else ""))
            idx += 1
        except Exception as e:
            log(f"⚠ Lỗi chụp Threads: {str(e)[:120]}")

    so_post = sum(1 for it in items if it["loai"] == "post")
    _luu_meta(out, url, "threads", items)
    page.close()
    log(f"✔ Threads: {len(items)} ảnh ({so_post} phần bài + {cnt_cmt} comment) → {os.path.relpath(out, THU_MUC_GOC)}")
    return items


def _parse_count(s):
    """Đếm số tương tác Threads (locale en-US) → int. '2,345'→2345, '2.3K'→2300,
    '1.2M'→1200000, '100'→100. -1 nếu không đọc được."""
    s = (s or "").strip().lower().replace(",", "").replace("\xa0", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*([kmb])?", s)
    if not m:
        return -1
    return int(float(m.group(1)) * {"k": 1e3, "m": 1e6, "b": 1e9}.get(m.group(2) or "", 1))


def _th_feed_metric(container):
    """(like, cmt, url) của 1 ô feed Threads. like/cmt=-1 nếu không dò được, url='' nếu thiếu permalink.
    Đọc nút Like/Comment qua aria-label (locale en: 'Like'/'Reply'/'Comment'); count là text trong nút."""
    url = ""
    a = container.query_selector('a[href*="/post/"]')
    if a:
        href = (a.get_attribute("href") or "").strip()
        if href:
            url = href if href.startswith("http") else "https://www.threads.com" + href
    like = cmt = -1
    try:
        data = container.evaluate(r"""el => {
            const out = {like:"", cmt:""};
            const btns = el.querySelectorAll('[role="button"], a[role="link"], button');
            for (const b of btns) {
                const svg = b.querySelector('svg');
                const lbl = ((b.getAttribute('aria-label')||'') + ' ' +
                             (svg ? (svg.getAttribute('aria-label')||'') : '')).toLowerCase();
                const num = (b.innerText||'').replace(/[^0-9.,kmbKMB]/g,'');
                if (!num) continue;
                if (!out.like && /(^|\s)(like|unlike|thích)/.test(lbl)) out.like = num;
                else if (!out.cmt && /(repl|comment|bình luận)/.test(lbl)) out.cmt = num;
            }
            return out;
        }""")
        if data:
            if data.get("like"):
                like = _parse_count(data["like"])
            if data.get("cmt"):
                cmt = _parse_count(data["cmt"])
    except Exception:
        pass
    return like, cmt, url


def chup_threads_feed(ctx, out_root, n_posts, max_cmt, min_like, min_cmt,
                      feed_url="https://www.threads.com/", debug=False, cho_login=0):
    """Lướt feed Trang chủ Threads, lọc bài đạt ngưỡng (tim>=min_like HOẶC cmt>=min_cmt),
    rồi cào từng bài (tối đa max_cmt comment). Cần đăng nhập (profile/cookies) để feed hiện đầy đủ.
    cho_login>0: chờ tới N giây cho người dùng đăng nhập trong cửa sổ (mode --show).
    Trả list dict {url, out, items, like, cmt}."""
    page = ctx.new_page()
    log(f"🌐 Mở feed Threads: {feed_url}")
    page.goto(feed_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    # Chờ đăng nhập: nếu chưa thấy bài nào (tường login), đợi người dùng login trong cửa sổ.
    da = 0
    while not page.query_selector_all('div[data-pressable-container="true"]') and da < cho_login:
        if da == 0:
            log("🔑 Chưa thấy feed → hãy ĐĂNG NHẬP Threads trong cửa sổ vừa mở. Đang đợi...")
        page.wait_for_timeout(5000)
        da += 5
    try:
        page.add_style_tag(content='div[role="dialog"],div[aria-modal="true"]{display:none!important}')
    except Exception:
        pass

    da_xet, chon = set(), []
    lan_kho_moi = 0
    while len(chon) < n_posts and lan_kho_moi < 8:
        moi = 0
        for c in page.query_selector_all('div[data-pressable-container="true"]'):
            like, cmt, url = _th_feed_metric(c)
            if not url or url in da_xet:
                continue
            da_xet.add(url)
            moi += 1
            # Bỏ bài VIDEO (chụp tự động không phát được → rác "Sorry, trouble playing"). Chỉ lấy bài chữ/ảnh.
            co_video = bool(c.query_selector('video') or c.query_selector('[aria-label*="Play"i]'))
            if debug:
                log(f"   • {url.rstrip('/').rsplit('/', 1)[-1]}: ❤{like} 💬{cmt}" + (" [VIDEO→bỏ]" if co_video else ""))
            if co_video:
                continue
            if like >= min_like or cmt >= min_cmt:
                chon.append((url, like, cmt))
                log(f"✅ Đạt ngưỡng (❤{like} / 💬{cmt}): {url}")
                if len(chon) >= n_posts:
                    break
        lan_kho_moi = 0 if moi else lan_kho_moi + 1
        page.mouse.wheel(0, 4000)
        page.wait_for_timeout(1800)
    page.close()

    if not chon:
        log("⚠ Lướt feed không thấy bài nào đạt ngưỡng (kiểm cookies đăng nhập / ngưỡng / dùng --debug).")
        return []
    log(f"🔎 Lọc được {len(chon)} bài đạt ngưỡng → cào (tối đa {max_cmt} comment/bài).")
    ket = []
    for url, like, cmt in chon:
        code = an_toan(url.rstrip("/").rsplit("/", 1)[-1])
        out = os.path.join(out_root, code)
        try:
            items = chup_threads(ctx, url, max_cmt, out)
            ket.append({"url": url, "out": out, "items": len(items), "like": like, "cmt": cmt})
        except Exception as e:
            log(f"⚠ Lỗi cào {url}: {str(e)[:120]}")
    return ket


def nap_cookies(ctx, path):
    if not path or not os.path.isfile(path):
        return
    cookies = []
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        p = line.split("\t")
        if len(p) < 7:
            continue
        dom, _flag, cpath, secure, exp, name, val = p[:7]
        try:
            exp = int(exp)
        except ValueError:
            exp = -1
        cookies.append({"name": name, "value": val, "domain": dom, "path": cpath,
                        "secure": secure.upper() == "TRUE", "expires": exp})
    if cookies:
        ctx.add_cookies(cookies)
        log(f"🍪 Đã nạp {len(cookies)} cookie từ {os.path.basename(path)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", required=True, choices=["rd", "th"])
    ap.add_argument("--mode", default="post", choices=["post", "feed", "search"])
    ap.add_argument("--url", default="")
    ap.add_argument("--keyword", default="", help="từ khóa (mode search)")
    ap.add_argument("--comments", default="10")
    ap.add_argument("--sort", default="top")
    ap.add_argument("--out", default="")
    ap.add_argument("--cookies", default="")
    ap.add_argument("--show", action="store_true")
    # feed mode (lướt Trang chủ Threads, lọc ngưỡng):
    ap.add_argument("--posts", default="5")
    ap.add_argument("--min-like", dest="min_like", default="2000")
    ap.add_argument("--min-cmt", dest="min_cmt", default="100")
    ap.add_argument("--max-cmt", dest="max_cmt", default="20")
    ap.add_argument("--feed-url", dest="feed_url", default="https://www.threads.com/")
    ap.add_argument("--profile", default="", help="thư mục profile trình duyệt (nhớ đăng nhập). Feed mặc định browser_data/threads")
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()

    nhieu = a.mode in ("feed", "search")   # các mode gom nhiều bài (xuất ra nhiều thư mục con)
    if a.mode == "search" and not a.keyword:
        log("⚠ Thiếu --keyword (mode search).")
        print("CHUP_DONE 0", flush=True)
        return
    if a.mode == "post" and not a.url:
        log("⚠ Thiếu --url (mode post).")
        print("CHUP_DONE 0", flush=True)
        return

    def _int(v, mac_dinh):
        try:
            return max(1, int(v))
        except ValueError:
            return mac_dinh

    n = _int(a.comments, 10)

    if a.mode == "post":
        if a.platform == "rd":
            out = a.out or os.path.join(THU_MUC_GOC, "anh_chup", "reddit", reddit_id(a.url))
        else:
            code = an_toan(a.url.rstrip("/").rsplit("/", 1)[-1])
            out = a.out or os.path.join(THU_MUC_GOC, "anh_chup", "threads", code)
    else:
        sub = "reddit_feed" if a.platform == "rd" else "threads_feed"
        out = a.out or os.path.join(THU_MUC_GOC, "anh_chup", sub)

    # Profile cố định để NHỚ đăng nhập. Threads luôn dùng (login 1 lần); Reddit dùng old.reddit công khai nên không cần.
    profile = a.profile or (os.path.join(THU_MUC_GOC, "browser_data", "threads") if a.platform == "th" else "")
    ctx_kw = dict(
        viewport={"width": 1000, "height": 1400},
        device_scale_factor=DSF,
        user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"),
        locale="en-US",
    )

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        if profile:
            os.makedirs(profile, exist_ok=True)
            ctx = pw.chromium.launch_persistent_context(profile, headless=not a.show, **ctx_kw)
            browser = None
        else:
            browser = pw.chromium.launch(headless=not a.show)
            ctx = browser.new_context(**ctx_kw)
        ctx.add_cookies([
            {"name": "over18", "value": "1", "domain": ".reddit.com", "path": "/"},
            {"name": "eu_cookie", "value": '{"opted":true,"nonessential":false}',
             "domain": ".reddit.com", "path": "/"},
        ])
        nap_cookies(ctx, a.cookies)
        feed_ket = None
        try:
            if nhieu:
                posts = _int(a.posts, 5)
                max_cmt = min(20, _int(a.max_cmt, 20))
                mlike, mcmt = _int(a.min_like, 2000), _int(a.min_cmt, 100)
                if a.platform == "th":
                    if a.mode == "search":
                        kw = urllib.parse.quote(a.keyword)
                        feed_url = f"https://www.threads.com/search?q={kw}&serp_type=default"
                    else:
                        feed_url = a.feed_url
                    feed_ket = chup_threads_feed(
                        ctx, out, posts, max_cmt, mlike, mcmt,
                        feed_url=feed_url, debug=a.debug, cho_login=180 if a.show else 0)
                else:  # Reddit
                    if a.mode == "search":
                        kw = urllib.parse.quote(a.keyword)
                        list_url = f"https://old.reddit.com/search?q={kw}&sort={a.sort or 'relevance'}&limit=100"
                    else:
                        feed_src = a.feed_url if a.feed_url.startswith("http") or a.feed_url.startswith("/") \
                            else "https://old.reddit.com/r/all/"
                        list_url = reddit_old_url(feed_src, a.sort)
                    feed_ket = chup_reddit_feed(
                        ctx, list_url, a.mode == "search", posts, max_cmt, a.sort,
                        mlike, mcmt, out, debug=a.debug)
                items = []
            else:
                items = chup_reddit(ctx, a.url, n, a.sort, out) if a.platform == "rd" \
                    else chup_threads(ctx, a.url, n, out)
        finally:
            ctx.close()
            if browser:
                browser.close()

    if nhieu:
        print(f"FEED_DONE {len(feed_ket or [])}", flush=True)
    else:
        print(f"CHUP_DONE {len(items)}", flush=True)


if __name__ == "__main__":
    main()
