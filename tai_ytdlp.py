# -*- coding: utf-8 -*-
"""
Tải video YouTube / TikTok / Twitter(X) / Reddit / Instagram bằng yt-dlp (cho học tập).
Chế độ: search (YouTube + Reddit), creator (theo kênh/user/subreddit), detail (theo link).

Dùng:
  python tai_ytdlp.py --platform yt --type search  --input "tu khoa" --count 10
  python tai_ytdlp.py --platform rd --type search  --input "tu khoa" --count 10 --sort top --time week
  python tai_ytdlp.py --platform rd --type creator --input "r/funny" --count 10 --sort controversial
  python tai_ytdlp.py --platform tw --type creator --input "@elonmusk" --count 10 --cookies-browser chrome
  python tai_ytdlp.py --platform ig --type detail  --input "https://www.instagram.com/reel/..." --cookies-browser chrome

In ra các dòng "LOG:..." để web_app đọc và hiển thị tiến trình.
Lưu vào: MediaCrawler/data/{youtube|tiktok|twitter|reddit|instagram}/videos/{tu-khoa/<kw>|kenh/<ten>|link}/
"""
import argparse
import ipaddress
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

THU_MUC_GOC = os.path.dirname(os.path.abspath(__file__))
THU_MUC_CRAWLER = os.path.join(THU_MUC_GOC, "MediaCrawler")
# Profile đăng nhập nền tảng (tt/tw/ig...): userData qua MC_BROWSER_DATA_DIR (web_app/mo_dang_nhap GHI ở đây,
# BỀN qua update). Dev (không env) = chỗ cũ MediaCrawler/browser_data. Trước đây hardcode THU_MUC_CRAWLER/
# browser_data -> ĐỌC NHẦM thư mục (login ghi userData, đây đọc app-src) -> cào báo "chưa đăng nhập" OAN.
BROWSER_DATA_DIR = os.environ.get("MC_BROWSER_DATA_DIR") or os.path.join(THU_MUC_CRAWLER, "browser_data")

NEN = {
    "yt": {"thu_muc": "youtube", "search_prefix": "ytsearch"},
    "tt": {"thu_muc": "tiktok"},
    "tw": {"thu_muc": "twitter"},
    "rd": {"thu_muc": "reddit"},
    "ig": {"thu_muc": "instagram"},
    "fb": {"thu_muc": "facebook"},
}
# Nền tảng cần cookie đăng nhập (đọc từ trình duyệt) mới tải được hầu hết video
NEN_CAN_COOKIE = ("ig", "tw")
# Sort hợp lệ khi liệt kê 1 subreddit (search có thêm 'relevance'/'comments')
REDDIT_SUB_SORT = ("hot", "new", "top", "rising", "controversial")

# Thư mục TẠM (per-process) cho cookie phiên xuất ra cho yt-dlp. Tạo lười, dọn khi thoát.
# Process này chạy 1-shot (subprocess), nên dọn ở finally/atexit là chắc chắn cho MỌI đường (kể cả crash).
_CK_TMP_DIR = None


def _ck_temp_dir():
    """Trả thư mục tạm dùng chung trong tiến trình để chứa cookie phiên (tạo lười + đăng ký dọn atexit)."""
    global _CK_TMP_DIR
    if _CK_TMP_DIR is None:
        _CK_TMP_DIR = tempfile.mkdtemp(prefix="ytck_")
        import atexit
        atexit.register(_don_cookie_temp)
    return _CK_TMP_DIR


def _don_cookie_temp():
    """Xóa thư mục cookie tạm (cookie phiên không tồn đọng plaintext trên đĩa). Best-effort."""
    global _CK_TMP_DIR
    if _CK_TMP_DIR:
        shutil.rmtree(_CK_TMP_DIR, ignore_errors=True)
        _CK_TMP_DIR = None


def log(msg):
    print("LOG:" + msg, flush=True)


def an_toan(ten):
    """Làm sạch tên thư mục (bỏ ký tự cấm trên Windows)."""
    ten = re.sub(r'[<>:"/\\|?*\n\r\t]+', " ", ten or "").strip()
    ten = re.sub(r"\s+", " ", ten)
    return (ten[:60] or "khac").rstrip(". ")


def tach_dong(s):
    return [x.strip() for x in re.split(r"[\n,]+", s or "") if x.strip()]


def chuan_hoa_user(platform, s):
    """@handle hoặc link -> URL trang user (Twitter/Instagram)."""
    s = (s or "").strip()
    if s.lower().startswith("http"):
        return s
    h = s.lstrip("@/").strip()
    if platform == "tw":
        return f"https://x.com/{h}"
    if platform == "ig":
        return f"https://www.instagram.com/{h}/"
    return s


# Các tab hợp lệ của trang kênh YouTube (URL kết thúc bằng tab nào thì giữ nguyên)
_YT_TABS = ("videos", "shorts", "streams", "live", "featured", "playlists", "community", "posts")


def chuan_hoa_kenh_youtube(s):
    """Kênh YouTube -> URL tab '/videos'.
    URL kênh trần (youtube.com/@abc) resolve ra danh sách TAB (Videos/Live/Shorts),
    khiến playlistend giới hạn theo TAB chứ không theo VIDEO -> tải loạn cả kênh.
    Thêm '/videos' để liệt kê thẳng video. Giữ nguyên link 1 video hoặc tab đã chỉ định."""
    s = (s or "").strip()
    if not s:
        return s
    low = s.lower()
    # Link 1 video / 1 short cụ thể -> để nguyên
    if "watch?v=" in low or "youtu.be/" in low or re.search(r"/shorts/[\w-]+", low):
        return s
    # Handle trần: "@abc" hoặc "abc" (không phải URL)
    if not low.startswith("http") and "/" not in s:
        h = s if s.startswith("@") else "@" + s
        return f"https://www.youtube.com/{h}/videos"
    if not low.startswith("http"):
        s = "https://" + s
    base_url = s.split("?")[0].split("#")[0].rstrip("/")
    if base_url.rsplit("/", 1)[-1].lower() in _YT_TABS:
        return base_url                      # đã trỏ tab cụ thể
    return base_url + "/videos"


def _tt_extract_secuid(html):
    """Trích secUid từ HTML trang TikTok user (JSON rehydration của CHỦ trang, fallback regex)."""
    m = re.search(r'__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html, re.S)
    if m:
        try:
            scope = json.loads(m.group(1)).get("__DEFAULT_SCOPE__", {})
            for v in scope.values():
                u = v.get("userInfo", {}).get("user", {}) if isinstance(v, dict) else {}
                if u.get("secUid"):
                    return u["secUid"]
        except Exception:
            pass
    m = re.search(r'"secUid":"([A-Za-z0-9_\-]{30,})"', html)   # dự phòng
    return m.group(1) if m else ""


def _tiktok_secuid(handle):
    """Lấy secUid 1 user TikTok qua Playwright (TikTok chặn HTTP thường = trả trang captcha).
    yt-dlp 2026.06 KHÔNG resolve được @username ('Unable to extract secondary user ID'),
    bắt buộc đưa secUid dạng 'tiktokuser:<secUid>'. Trả '' nếu thất bại.
    DÙNG profile login tt + stealth (clean launch bị anti-bot trả captcha). TikTok anti-bot KHÔNG
    nhất quán (lúc trả trang lấy được secUid, lúc captcha) -> RETRY context MỚI tối đa 3 lần
    (đã đo thật: lần 1 fail, lần 2 OK 5 video)."""
    handle = (handle or "").lstrip("@").strip()
    if not handle:
        return ""
    url = "https://www.tiktok.com/@%s" % handle
    udd = os.path.join(BROWSER_DATA_DIR, "tt_user_data_dir")
    stealth = os.path.join(THU_MUC_CRAWLER, "libs", "stealth.min.js")
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            for attempt in range(3):
                html = ""
                try:
                    ctx = pw.chromium.launch_persistent_context(
                        udd, headless=True, user_agent=ua,
                        args=["--disable-blink-features=AutomationControlled"],
                    )
                    try:
                        if os.path.isfile(stealth):
                            ctx.add_init_script(path=stealth)
                        pg = ctx.new_page()
                        pg.goto(url, wait_until="domcontentloaded", timeout=35000)
                        pg.wait_for_timeout(3000)
                        html = pg.content()
                    finally:
                        ctx.close()
                except Exception as e:
                    log(f"⚠ TikTok @{handle} lần {attempt + 1}/3 lỗi mở trang: {str(e)[:80]}")
                    continue
                sec = _tt_extract_secuid(html)
                if sec:
                    return sec
                log(f"  · @{handle} lần {attempt + 1}/3: tải được trang nhưng CHƯA lấy được ID (TikTok anti-bot/captcha) — thử lại...")
                # anti-bot trả captcha (không có secUid) -> thử context MỚI
    except Exception as e:
        log(f"⚠ Không mở được trang TikTok @{handle}: {str(e)[:120]}")
        return ""
    return ""


def chuan_hoa_kenh_tiktok(s):
    """@user / link profile TikTok -> URL kênh chuẩn 'https://www.tiktok.com/@<user>'. '' nếu không rõ.
    yt-dlp 2026+ xử lý THẲNG URL @username; dạng 'tiktokuser:<secUid>' kiểu CŨ đã bị yt-dlp từ chối
    ('Unable to extract secondary user ID') → 0 video. Nên dùng URL @username (đã verify liệt kê được)."""
    s = (s or "").strip()
    if s.lower().startswith("tiktokuser:"):
        return s   # user tự nhập channel_id mới của yt-dlp → giữ nguyên
    m = re.search(r"tiktok\.com/@([\w.\-]+)", s, re.I)
    handle = (m.group(1) if m else s).lstrip("@").strip()
    if not handle:
        log("✗ KHÔNG rõ kênh TikTok — dán @tên-kênh hoặc link kênh (vd https://www.tiktok.com/@tiktok).")
        return ""
    log(f"✔ Kênh TikTok: @{handle}")
    return "https://www.tiktok.com/@" + handle


def chuan_hoa_link_tiktok(url):
    """Link 1 bài TikTok -> (url_chuan, la_photo).
    TikTok có 2 dạng bài: /video/<id> (video) và /photo/<id> (bài ẢNH slideshow).
    Extractor yt-dlp CHỈ khớp regex /video/<id> -> link /photo/ bị 'Unsupported URL'
    và bị ignoreerrors nuốt -> 'tải 0 video' không rõ lý do.
    Bài /photo/ và /video/ DÙNG CHUNG item id, nên rewrite /photo/->/video/ để yt-dlp
    resolve được item (bài chỉ có ảnh sẽ không có format video -> caller tự xử lý/báo)."""
    u = (url or "").strip()
    if re.search(r"tiktok\.com/@[\w.\-]+/photo/\d+", u, re.I):
        return re.sub(r"/photo/(\d+)", r"/video/\1", u, flags=re.I), True
    return u, False


def _tiktok_search(query, count, log=print):
    """SEARCH TikTok qua Playwright (yt-dlp KHÔNG search TT được). Dùng profile đăng nhập sẵn
    (browser_data/tt_user_data_dir) để né tường login. Trả list item {id,title,thumb,url,...}.
    FRAGILE: phụ thuộc DOM/anti-bot TikTok + cần đã đăng nhập TikTok."""
    udd = os.path.join(BROWSER_DATA_DIR,"tt_user_data_dir")
    if not os.path.isdir(udd):
        udd = os.path.join(BROWSER_DATA_DIR,"_tt_tmp")
    url = "https://www.tiktok.com/search?q=" + urllib.parse.quote(query)
    anchors = []
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(udd, headless=True)
            try:
                pg = ctx.pages[0] if ctx.pages else ctx.new_page()
                pg.goto(url, wait_until="domcontentloaded", timeout=40000)
                pg.wait_for_timeout(3500)
                js = ("els=>els.map(a=>{const im=a.querySelector('img');"
                      "return {href:a.href, img:im?im.src:'', alt:im?im.alt:''};})")
                for _ in range(4):
                    try:
                        anchors = pg.eval_on_selector_all("a[href*='/video/']", js)
                    except Exception:
                        anchors = []
                    if len(anchors) >= count:
                        break
                    pg.mouse.wheel(0, 3000)
                    pg.wait_for_timeout(1500)
            finally:
                ctx.close()
    except Exception as e:
        log("⚠ Search TikTok lỗi (%s) — đã đăng nhập TikTok chưa?" % str(e)[:120])
        return []
    items, seen = [], set()
    for a in anchors:
        m = re.search(r"tiktok\.com/@([\w.\-]+)/video/(\d+)", a.get("href", ""))
        if not m:
            continue
        nick, vid = m.group(1), m.group(2)
        if vid in seen:
            continue
        seen.add(vid)
        items.append({"id": vid, "title": (a.get("alt") or "").strip()[:160], "thumb": a.get("img") or "",
                      "loai": "video", "video": True, "so_anh": 0,
                      "url": "https://www.tiktok.com/@%s/video/%s" % (nick, vid), "like": "", "nick": nick})
        if len(items) >= count:
            break
    return items


# ---------------- Facebook: cào theo LINK (yt-dlp extractor sẵn, không cần code riêng) +
# theo KÊNH/Page (yt-dlp KHÔNG liệt kê được Page -> Playwright cuộn thu link, mirror TikTok) ----------------
def chuan_hoa_kenh_facebook(s):
    """Link Page / tên Page / '@ten' -> URL gốc Page 'https://www.facebook.com/<page>' (không kèm tab
    con). '' nếu không nhận diện được (link 1 video, /watch, /reel, /groups... không phải Page)."""
    s = (s or "").strip()
    if not s:
        return ""
    if not s.lower().startswith("http"):
        s = "https://www.facebook.com/" + s.lstrip("@/")
    m = re.search(r"facebook\.com/profile\.php\?id=(\d+)", s, re.I)
    if m:
        return "https://www.facebook.com/profile.php?id=%s" % m.group(1)
    m = re.search(r"facebook\.com/([^/?#]+)", s, re.I)
    if not m:
        return ""
    page = m.group(1)
    if page.lower() in ("watch", "share", "reel", "groups", "login", "help", "photo.php", "permalink.php"):
        return ""   # link 1 video/bài, không phải Page
    return "https://www.facebook.com/" + page


def _fb_scroll_links(pg, want, log=print):
    """Cuộn trang Facebook (tab /videos hoặc /reels đang mở), thu link video/reel DUY NHẤT tới khi đủ
    `want` hoặc 3 lần cuộn liên tiếp KHÔNG ra thêm (hết nội dung / anti-bot chặn). Trả list item
    {id,title,thumb,url,...} (định dạng như _item_yt/_item_tt để dùng chung downstream)."""
    items, seen = [], set()
    js_get = ("els=>els.map(a=>{const im=a.querySelector('img');"
              "return {href:a.href, img:im?im.src:'', alt:im?(im.alt||''):''};})")
    khong_moi = 0
    for _ in range(20):
        try:
            anchors = pg.eval_on_selector_all(
                "a[href*='/videos/'],a[href*='/reel/'],a[href*='watch/?v=']", js_get)
        except Exception:
            anchors = []
        moi = 0
        for a in anchors:
            href = a.get("href", "")
            m = re.search(r"facebook\.com/(?:watch/\?v=(\d+)|[^/]+/videos/(\d+)|reel/(\d+))", href)
            if not m:
                continue
            vid = m.group(1) or m.group(2) or m.group(3)
            if vid in seen:
                continue
            seen.add(vid); moi += 1
            items.append({"id": vid, "title": (a.get("alt") or "").strip()[:160],
                          "thumb": a.get("img") or "", "loai": "video", "video": True, "so_anh": 0,
                          "url": href.split("&")[0] if "watch/?v=" not in href else href.split("&")[0],
                          "like": "", "nick": ""})
            if len(items) >= want:
                break
        if len(items) >= want:
            break
        khong_moi = khong_moi + 1 if moi == 0 else 0
        if khong_moi >= 3:
            break
        pg.mouse.wheel(0, 4500)
        pg.wait_for_timeout(1800)
    return items


def _fb_co_tuong_dang_nhap(pg):
    """Facebook chặn xem ẩn danh sau ~1 bài bằng dialog 'Xem thêm trên Facebook / Đăng nhập' (đã verify
    THẬT: trang login-wall có document.body cố định = viewport, KHÔNG cuộn thêm được dù gọi scrollTo/wheel).
    Dò dialog này để phân biệt '1 video vì Page thật chỉ có 1' (hiếm) với 'bị chặn login' (log hint đúng lúc)."""
    try:
        return bool(pg.evaluate(
            """() => Array.from(document.querySelectorAll('div[role="dialog"]')).some(
                d => /đăng nhập|log in|log into facebook|tạo tài khoản mới|create new account/i.test(d.innerText||''))"""))
    except Exception:
        return False


def _fb_liet_ke_kenh(page_input, count, log=print):
    """Liệt kê video 1 Page Facebook (metadata-only, KHÔNG tải) cho cả 'Xem trước & chọn' lẫn tải-theo-kênh.
    yt-dlp không liệt kê được Page FB -> Playwright mở '/videos' rồi '/reels' (nếu chưa đủ), cuộn thu link
    (mirror TikTok). Dùng profile đăng nhập fb NẾU CÓ (browser_data/fb_user_data_dir).
    ĐÃ VERIFY THẬT: Page công khai xem ẨN DANH bị Facebook CHẶN CỨNG sau ~1 video (dialog "Xem thêm trên
    Facebook — Đăng nhập", trang không cuộn thêm được) — KHÁC YouTube/TikTok (không chặn). UI (index.html
    _boQuaLogin) ÉP đăng nhập trước khi gọi hàm này qua "Theo kênh" (mode=creator) — "Theo link" thì
    không cần. Hàm này (gọi trực tiếp qua CLI/Task Queue, bỏ qua UI) vẫn KHÔNG tự chặn cứng — tự chạy hết
    khả năng rồi log HINT khi phát hiện đúng tường chặn (tránh chặn oan Page thật sự chỉ có 1 video, và
    vẫn hữu ích nếu đã đăng nhập ở máy chạy Task Queue). FRAGILE: phụ thuộc DOM Facebook. Retry context
    mới tối đa 3 lần nếu 0 kết quả."""
    base = chuan_hoa_kenh_facebook(page_input)
    if not base:
        log(f"⚠ Facebook: không nhận diện được Page từ '{str(page_input)[:60]}' (dán link Page, không phải link 1 video).")
        return []
    udd = os.path.join(BROWSER_DATA_DIR, "fb_user_data_dir")
    stealth = os.path.join(THU_MUC_CRAWLER, "libs", "stealth.min.js")
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
    items, tuong_login = [], False
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            for attempt in range(3):
                try:
                    ctx = pw.chromium.launch_persistent_context(
                        udd, headless=True, user_agent=ua,
                        args=["--disable-blink-features=AutomationControlled"])
                except Exception as e:
                    log(f"⚠ Facebook lần {attempt + 1}/3 lỗi mở trình duyệt: {str(e)[:100]}")
                    continue
                try:
                    if os.path.isfile(stealth):
                        ctx.add_init_script(path=stealth)
                    pg = ctx.new_page()
                    for tab in ("videos", "reels"):
                        if len(items) >= count:
                            break
                        try:
                            pg.goto(f"{base}/{tab}", wait_until="domcontentloaded", timeout=40000)
                            pg.wait_for_timeout(2500)
                        except Exception:
                            continue
                        if _fb_co_tuong_dang_nhap(pg):
                            tuong_login = True
                        seen_id = {it["id"] for it in items}
                        for it in _fb_scroll_links(pg, count - len(items), log=log):
                            if it["id"] not in seen_id:
                                seen_id.add(it["id"]); items.append(it)
                finally:
                    ctx.close()
                if items:
                    break
                log(f"  · Facebook lần {attempt + 1}/3: chưa lấy được video (anti-bot/Page trống/riêng tư) — thử lại...")
    except Exception as e:
        log(f"⚠ Không mở được Facebook: {str(e)[:120]}")
        return []
    if tuong_login and len(items) < count:
        log(f"ℹ Facebook giới hạn xem ẨN DANH — chỉ lấy được {len(items)} video (dialog đăng nhập chặn xem thêm). "
            "Đăng nhập Facebook (mục Đăng nhập nền tảng) rồi cào lại để lấy đầy đủ danh sách kênh.")
    return items[:count]


def reddit_sub(s):
    """'funny' | 'r/funny' | link subreddit -> tên subreddit sạch."""
    s = (s or "").strip()
    m = re.search(r"reddit\.com/r/([^/?#]+)", s, re.I)
    if m:
        return m.group(1)
    return re.sub(r"[^A-Za-z0-9_]", "", s.lstrip("/").split("?")[0].removeprefix("r/").removeprefix("R/"))


def _reddit_get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "reupo-tool/1.0 (video reup, hoc tap)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _co_video(d):
    """Post Reddit này có video không (để yt-dlp tải được)?"""
    if d.get("is_video"):
        return True
    if d.get("post_hint") in ("hosted:video", "rich:video"):
        return True
    dom = (d.get("domain") or "").lower()
    return any(h in dom for h in ("v.redd.it", "youtube.com", "youtu.be",
                                  "redgifs.com", "gfycat.com", "streamable.com"))


def reddit_lay_links(che_do, kw_hoac_sub, sort, time_window, count):
    """Gọi Reddit JSON -> trả list link post (có video), đã giới hạn count.
    che_do='search' (tìm từ khóa toàn Reddit) | 'creator' (1 subreddit)."""
    sort = (sort or "").strip().lower()
    t = (time_window or "").strip().lower()
    links, after, vong = [], None, 0
    while len(links) < count and vong < 6:
        vong += 1
        params = {"limit": 100, "raw_json": 1}
        if after:
            params["after"] = after
        if che_do == "search":
            params["q"] = kw_hoac_sub
            params["type"] = "link"
            params["include_over_18"] = "on"
            params["sort"] = sort if sort in ("relevance", "hot", "top", "new", "comments") else "top"
            if params["sort"] == "top" and t:
                params["t"] = t
            url = "https://www.reddit.com/search.json?" + urllib.parse.urlencode(params)
        else:  # creator = 1 subreddit
            sub = reddit_sub(kw_hoac_sub)
            s = sort if sort in REDDIT_SUB_SORT else "hot"
            if s in ("top", "controversial") and t:
                params["t"] = t
            url = f"https://www.reddit.com/r/{sub}/{s}.json?" + urllib.parse.urlencode(params)
        try:
            data = _reddit_get_json(url)
        except Exception as e:
            log(f"⚠ Lỗi gọi Reddit: {str(e)[:160]}")
            break
        children = (data.get("data") or {}).get("children") or []
        if not children:
            break
        for c in children:
            d = c.get("data") or {}
            if _co_video(d) and d.get("permalink"):
                links.append("https://www.reddit.com" + d["permalink"])
                if len(links) >= count:
                    break
        after = (data.get("data") or {}).get("after")
        if not after:
            break
    return links


def xuat_cookie_tu_phien(platform, temp_dir=None):
    """X/IG: mở profile đăng nhập (browser_data/<plat>_user_data_dir) bằng Playwright,
    xuất cookie ra cookies.txt (Netscape) cho yt-dlp. Trả đường dẫn hoặc ''.
    (yt-dlp không giải mã trực tiếp được cookie Chromium của Playwright nên phải xuất qua Playwright.)

    Cookie phiên (auth token) KHÔNG còn ghi cố định vào browser_data nữa: ghi vào THƯ MỤC TẠM
    per-job rồi caller xóa trong `finally` (giảm bề mặt lộ phiên trên đĩa). browser_data/
    <plat>_user_data_dir (phiên login Playwright) GIỮ NGUYÊN — chỉ file *_cookies.txt mới chuyển temp.
    temp_dir vắng -> tự tạo (giữ tương thích chữ ký cũ; caller nên truyền dir để gom + dọn)."""
    udd = os.path.join(BROWSER_DATA_DIR, f"{platform}_user_data_dir")
    if not os.path.isdir(udd):
        return ""
    d = temp_dir or _ck_temp_dir()
    out = os.path.join(d, f"{platform}_cookies.txt")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(udd, headless=True)
            try:
                cks = ctx.cookies()
            finally:
                ctx.close()
    except Exception as e:
        log(f"⚠ Không đọc được phiên đăng nhập {platform}: {str(e)[:120]}")
        return ""
    if not cks:
        return ""
    try:
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            f.write("# Netscape HTTP Cookie File\n")
            for c in cks:
                dom = c.get("domain", "")
                exp = int(c.get("expires") or 0)
                f.write("\t".join([dom, "TRUE" if dom.startswith(".") else "FALSE",
                                   c.get("path", "/"), "TRUE" if c.get("secure") else "FALSE",
                                   str(exp if exp > 0 else 0), c.get("name", ""),
                                   c.get("value", "")]) + "\n")
        try:
            os.chmod(out, stat.S_IRUSR | stat.S_IWUSR)   # chỉ chủ sở hữu đọc/ghi (best-effort)
        except Exception:
            pass
        return out
    except Exception:
        return ""


# ---------------- XEM TRƯỚC (liệt kê metadata, KHÔNG tải) — cho nút "Xem trước & chọn" ----------------
def _item_yt(e):
    vid = e.get("id") or ""
    return {
        "id": vid,
        "title": (e.get("title") or "").strip()[:160],
        "thumb": "https://i.ytimg.com/vi/%s/hqdefault.jpg" % vid if vid else "",  # suy từ ID (flat không có thumb)
        "loai": "video", "video": True, "so_anh": 0,
        "url": e.get("url") or ("https://www.youtube.com/watch?v=%s" % vid if vid else ""),
        "like": str(e.get("view_count") or ""),
        "nick": e.get("channel") or e.get("uploader") or "",
    }


def _item_tt(e):
    vid = str(e.get("id") or "")
    thumbs = e.get("thumbnails") or []
    thumb = e.get("thumbnail") or (thumbs[-1].get("url") if thumbs else "")
    return {
        "id": vid,
        "title": (e.get("title") or e.get("description") or "").strip()[:160],
        "thumb": thumb,
        "loai": "video", "video": True, "so_anh": 0,
        "url": e.get("url") or "",
        "like": str(e.get("view_count") or e.get("like_count") or ""),
        "nick": e.get("uploader") or e.get("channel") or "",
    }


def liet_ke(a, count):
    """Liệt kê video (metadata-only, extract_flat) cho XEM TRƯỚC — in 1 dòng JSON {ok, items}.
    YouTube: search (ytsearchN) + creator (kênh /videos).
    TikTok: search = HASHTAG (tiktok.com/tag/<từ khoá>) qua yt-dlp + cookie đăng nhập, dự phòng scrape
            trang search; creator = kênh.
    Facebook: CHỈ creator (Page) qua Playwright (_fb_liet_ke_kenh) — không hỗ trợ search từ khóa."""
    plat = a.platform
    if plat not in ("yt", "tt", "fb"):
        print(json.dumps({"ok": False, "msg": "Nền tảng chưa hỗ trợ xem trước: " + plat})); return
    if plat == "fb":
        if a.type != "creator":
            print(json.dumps({"ok": False, "msg": "Facebook: chỉ hỗ trợ xem trước theo KÊNH (Page) — dùng 'Theo link' để tải trực tiếp 1 video."})); return
        items, seen = [], set()
        for x in tach_dong(a.input):
            for it in _fb_liet_ke_kenh(x, count, log=log):
                if it["id"] not in seen:
                    seen.add(it["id"]); items.append(it)
                if len(items) >= count:
                    break
            if len(items) >= count:
                break
        print(json.dumps({"ok": True, "items": items, "tong": len(items)}, ensure_ascii=False)); return
    from yt_dlp import YoutubeDL
    cookiefile = ""
    if a.type == "creator":
        if plat == "yt":
            urls = [chuan_hoa_kenh_youtube(x) for x in tach_dong(a.input)]
        else:
            cookiefile = xuat_cookie_tu_phien("tt")    # best-effort: dùng phiên đăng nhập TikTok nếu có
            urls = [u for u in (chuan_hoa_kenh_tiktok(x) for x in tach_dong(a.input)) if u]
        if not urls:
            print(json.dumps({"ok": False, "msg": "Không lấy được kênh (thử dán link 1 video của kênh)."})); return
    elif plat == "tt":  # TikTok search: từ khoá = HASHTAG (tag) — cần cookie đăng nhập TikTok
        cookiefile = xuat_cookie_tu_phien("tt")
        if not cookiefile:
            print(json.dumps({"ok": False, "msg": "Chưa đăng nhập TikTok — bấm thẻ TikTok ở mục Đăng nhập nền tảng rồi thử lại."})); return
        urls = ["https://www.tiktok.com/tag/%s" % urllib.parse.quote(kw.lstrip("#").replace(" ", "").strip())
                for kw in tach_dong(a.input) if kw.strip()]
        if not urls:
            print(json.dumps({"ok": False, "msg": "Chưa nhập từ khóa."})); return
    else:  # search YouTube
        urls = ["ytsearch%d:%s" % (count, kw) for kw in tach_dong(a.input)]
        if not urls:
            print(json.dumps({"ok": False, "msg": "Chưa nhập từ khóa."})); return

    opts = {"extract_flat": "in_playlist", "skip_download": True, "playlistend": count,
            "quiet": True, "no_warnings": True, "ignoreerrors": True, "nocheckcertificate": True}
    if cookiefile and os.path.isfile(cookiefile):
        opts["cookiefile"] = cookiefile
    parser = _item_yt if plat == "yt" else _item_tt
    items, seen = [], set()
    kenh_nick, kenh_avatar = "", ""   # metadata KÊNH (creator) — cho Theo dõi/Kênh nguồn lấy tên + avatar THẬT
    try:
        with YoutubeDL(opts) as ydl:
            for u in urls:
                try:
                    info = ydl.extract_info(u, download=False)
                except Exception as e:
                    log("⚠ Lỗi liệt kê %s: %s" % (u[:40], str(e)[:120])); continue
                if a.type == "creator" and isinstance(info, dict) and not kenh_nick:
                    # info cấp playlist (trang kênh) có channel/uploader + thumbnails = AVATAR kênh (yt).
                    kenh_nick = (info.get("channel") or info.get("uploader") or "").strip()
                    _ths = info.get("thumbnails") or []
                    if _ths:
                        kenh_avatar = _ths[-1].get("url") or (_ths[0].get("url") or "")
                entries = info.get("entries") if isinstance(info, dict) else None
                for e in (entries or ([info] if info else [])):
                    if not e:
                        continue
                    it = parser(e)
                    if it["id"] and it["id"] not in seen:
                        seen.add(it["id"]); items.append(it)
                    if len(items) >= count:
                        break
                if len(items) >= count:
                    break
    except Exception as e:
        print(json.dumps({"ok": False, "msg": "Lỗi xem trước: " + str(e)[:160]})); return
    # TikTok: hashtag qua yt-dlp đôi khi lỗi 'No app info' -> dự phòng scrape trang search (cùng phiên login)
    if plat == "tt" and a.type != "creator" and not items:
        log("ℹ Hashtag TikTok không ra video — thử scrape trang search.")
        for kw in tach_dong(a.input):
            for it in _tiktok_search(kw, count):
                if it["id"] and it["id"] not in seen:
                    seen.add(it["id"]); items.append(it)
                if len(items) >= count:
                    break
            if len(items) >= count:
                break
    _don_cookie_temp()   # dọn cookie phiên tạm (các đường return sớm vẫn được atexit dọn)
    # nick/avatar item (nếu parser có) làm dự phòng khi thiếu metadata kênh cấp playlist
    if not kenh_nick:
        for it in items:
            if it.get("nick"):
                kenh_nick = it["nick"]; break
    print(json.dumps({"ok": True, "items": items, "tong": len(items),
                      "kenh_nick": kenh_nick, "kenh_avatar": kenh_avatar}, ensure_ascii=False))


def _url_an_toan(u):
    """H11 chống SSRF: chỉ cho URL scheme http(s) + host KHÔNG loopback/private/reserved/link-local.
    Chặn file://, ftp://, http://127.0.0.1, http://192.168.x... (yt-dlp đọc file cục bộ / gọi dịch vụ nội bộ)."""
    try:
        p = urllib.parse.urlparse((u or "").strip())
    except Exception:
        return False
    if p.scheme not in ("http", "https"):
        return False
    host = (p.hostname or "").lower()
    if not host or host == "localhost":
        return False
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_loopback or ip.is_private or ip.is_reserved or ip.is_link_local:
            return False
    except ValueError:
        pass   # host là tên miền → để yt-dlp resolve (CDN/nền tảng hợp lệ)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", required=True, choices=list(NEN.keys()))
    ap.add_argument("--type", required=True, choices=["search", "creator", "detail"])
    ap.add_argument("--input", required=True)
    ap.add_argument("--count", default="10")
    ap.add_argument("--sort", default="")            # Reddit: relevance/top/comments/hot/new/controversial
    ap.add_argument("--time", default="")            # Reddit: hour/day/week/month/year/all
    ap.add_argument("--cookies-browser", dest="cookies_browser", default="")  # chrome/edge/firefox...
    ap.add_argument("--cookies", default="")          # đường dẫn cookies.txt (Netscape) — X/IG
    ap.add_argument("--list", action="store_true")    # CHỈ liệt kê metadata (xem trước), KHÔNG tải
    a = ap.parse_args()

    try:
        count = max(1, int(a.count))
    except ValueError:
        count = 10

    if a.list:                       # xem trước (metadata-only) -> in JSON rồi thoát, KHÔNG tải
        liet_ke(a, count)
        return

    from yt_dlp import YoutubeDL

    plat = NEN[a.platform]
    # Gốc data = env MC_DATA_DIR (web_app/chay_tu_dong đặt = userData / user-chọn → BỀN qua update);
    # không có env (chạy tay trong dev) = chỗ cũ MediaCrawler/data.
    _data_goc = (os.environ.get("MC_DATA_DIR") or "").strip() or os.path.join(THU_MUC_CRAWLER, "data")
    base = os.path.join(_data_goc, plat["thu_muc"], "videos")
    archive = os.path.join(_data_goc, plat["thu_muc"], "_da_tai.txt")
    os.makedirs(base, exist_ok=True)

    ffmpeg = shutil.which("ffmpeg")
    cookies_browser = (a.cookies_browser or "").strip().lower()
    cookies_file = (a.cookies or "").strip()
    _co_cookie = lambda: cookies_browser or (cookies_file and os.path.isfile(cookies_file))
    # X/IG: chưa truyền cookie thủ công -> lấy từ phiên đăng nhập (mo_dang_nhap)
    if a.platform in NEN_CAN_COOKIE and not _co_cookie():
        cf = xuat_cookie_tu_phien(a.platform)
        if cf:
            cookies_file = cf
            log(f"🔑 Dùng cookie phiên đăng nhập {a.platform.upper()}.")
    if a.platform in NEN_CAN_COOKIE and not _co_cookie():
        log(f"⚠ {a.platform.upper()} cần đăng nhập — chưa có phiên. Bấm 'Đăng nhập {a.platform.upper()}' trước khi cào.")
    # TikTok: dùng cookie phiên đăng nhập nếu có (tải ổn định hơn / né rate-limit) — KHÔNG bắt buộc cho tải kênh/link
    if a.platform == "tt" and not _co_cookie():
        cf = xuat_cookie_tu_phien("tt")
        if cf:
            cookies_file = cf
            log("🔑 Dùng cookie phiên đăng nhập TikTok.")
    # Facebook: cookie phiên đăng nhập nếu có (giúp tải ổn định hơn) — KHÔNG bắt buộc (Page công khai vẫn tải được)
    if a.platform == "fb" and not _co_cookie():
        cf = xuat_cookie_tu_phien("fb")
        if cf:
            cookies_file = cf
            log("🔑 Dùng cookie phiên đăng nhập Facebook.")

    # Đếm số video tải được trong phiên (theo id để không đếm trùng stream video+audio)
    da_xong = set()

    # LỊCH SỬ CÀO: yt-dlp (yt/tt/fb...) ghi *_contents_*.jsonl cạnh videos (như MediaCrawler) -> video ĐÃ TẢI
    # hiện trong tab "Lịch sử cào" (lich_su_cao chỉ đọc jsonl; trước đây yt-dlp chỉ tải file nên bị bỏ sót).
    import datetime as _dt
    _ls_dir = os.path.join(os.path.dirname(base), "jsonl")   # base=.../<nền>/videos -> jsonl cạnh đó
    _ls_loai = a.type if a.type in ("search", "creator", "detail") else "detail"
    _ls_file = os.path.join(_ls_dir, f"{_ls_loai}_contents_{_dt.date.today().isoformat()}.jsonl")
    _ls_da_ghi = set()

    def _ghi_lich_su(info):
        vid = str(info.get("id") or "")
        if not vid or vid in _ls_da_ghi:
            return
        _ls_da_ghi.add(vid)
        try:
            url = info.get("webpage_url") or info.get("original_url") or ""
            ts = int(info.get("timestamp") or 0)
            if not ts:
                ud = str(info.get("upload_date") or "")
                if len(ud) == 8:
                    try:
                        ts = int(_dt.datetime.strptime(ud, "%Y%m%d").timestamp())
                    except Exception:
                        ts = 0
            rec = {"video_id": vid, "id": vid, "title": info.get("title") or "",
                   "nickname": info.get("uploader") or info.get("channel") or "",
                   "video_url": url, "url": url, "create_time": ts, "last_modify_ts": ts,
                   "source_keyword": (a.input if a.type == "search" else "")}
            os.makedirs(_ls_dir, exist_ok=True)
            with open(_ls_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            try:   # ĐÁNH DẤU đã-tải (index_metadata SQLite) -> badge "✓ đã tải" đúng ở Lịch sử cào + Xem trước
                import index_metadata   # noqa: cùng repo, cwd=THU_MUC_GOC
                index_metadata.danh_dau(a.platform, [x for x in (url, vid) if x])
            except Exception:
                pass
        except Exception:
            pass

    _tien_do = {"pct": -1}   # % ĐÃ log gần nhất — chỉ log mỗi mốc ~10% (tránh spam từng fragment)

    def hook(d):
        st = d.get("status")
        if st == "downloading":
            # Video DÀI/NẶNG (phim, live vài giờ = cả GB) tải MẤT VÀI PHÚT → không có log thì khách tưởng
            # treo/0 video. Log % + dung lượng + tốc độ mỗi mốc ~10% để thấy ĐANG TẢI.
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            if total > 0:
                pct = int(done * 100 / total)
                if pct >= _tien_do["pct"] + 10 or (pct >= 99 and _tien_do["pct"] < 99):
                    _tien_do["pct"] = pct
                    mb = total / 1048576
                    spd = (d.get("speed") or 0) / 1048576
                    log(f"📥 Đang tải video: {pct}% của {mb:.0f}MB" + (f" ({spd:.1f}MB/s)" if spd > 0 else ""))
            return
        if st == "finished":
            _tien_do["pct"] = -1   # reset cho video kế
            info = d.get("info_dict") or {}
            vid = info.get("id") or d.get("filename", "")
            if vid in da_xong:
                return
            da_xong.add(vid)
            _ghi_lich_su(info)   # ghi lịch sử cào (1 lần/video)
            ten = info.get("title") or os.path.basename(d.get("filename", ""))
            log(f"✔ Đã tải {len(da_xong)}: {ten[:80]}")

    def _da_co_file(vid):
        """File video có [<id>] ĐÃ tồn tại trong data (bất kỳ folder link/kênh/tu-khoa)? → chống trùng ĐỘC LẬP
        download_archive. yt-dlp ghi id vào _da_tai.txt CHỈ SAU khi tải XONG → video LỚN (3GB) tải 10-30 phút,
        trong lúc đó id CHƯA vào archive → bấm cào lại / job lặp / cào link+kênh cùng video = tải BẢN TRÙNG.
        Kiểm file [id] sẵn có chặn trùng NGAY kể cả khi archive chưa kịp ghi."""
        if not vid:
            return False
        needle = "[%s]" % vid
        for root, _dirs, files in os.walk(base):
            for f in files:
                if needle in f and f.lower().endswith((".mp4", ".mkv", ".webm")):
                    return True
        return False

    def _match_bo_trung(info):
        """yt-dlp match_filter: bỏ qua video đã có file [id] trên đĩa. Trả None = tải; str = lý do skip."""
        vid = str(info.get("id") or "")
        if vid and _da_co_file(vid):
            log(f"↩ Bỏ qua (đã tải trước đó): {(info.get('title') or vid)[:60]}")
            return "da co file [%s]" % vid
        return None

    def opts_cho(outtmpl, playlistend=None):
        o = {
            "outtmpl": outtmpl,
            "match_filter": _match_bo_trung,   # chống trùng theo FILE [id] sẵn có (độc lập download_archive)
            # Ưu tiên H.264 (avc1/h264) để trình duyệt phát được — tránh HEVC/bytevc1 (đen hình, chỉ có tiếng)
            "format": ("bv*[vcodec~='^(avc1|h264)']+ba[ext=m4a]/"
                       "b[vcodec~='^(avc1|h264)']/"
                       "bv*[ext=mp4]+ba/b[ext=mp4]/b"),
            "format_sort": ["vcodec:h264"],
            "merge_output_format": "mp4",
            "ignoreerrors": True,
            "nocheckcertificate": True,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "retries": 3,
            "download_archive": archive,
            "progress_hooks": [hook],
            "concurrent_fragment_downloads": 4,
            "enable_file_urls": False,   # H11: tường minh KHÔNG cho yt-dlp đọc file:// (chống SSRF/đọc file cục bộ)
        }
        if ffmpeg:
            o["ffmpeg_location"] = ffmpeg
        if cookies_file and os.path.isfile(cookies_file):
            o["cookiefile"] = cookies_file
        elif cookies_browser:
            o["cookiesfrombrowser"] = (cookies_browser,)
        # YouTube (yt-dlp 2026.06+): TẢI cần JS runtime + EJS challenge solver để giải nsig/signature.
        # Thiếu -> yt-dlp lùi client android_vr -> 0 format -> "This video is not available" (XEM TRƯỚC
        # vẫn chạy vì extract_flat không cần JS, nên dễ tưởng cào OK). Installer bundle node
        # (resources/vendor/node) đã ở PATH; opt lạ -> YoutubeDL bỏ qua nên an toàn với yt-dlp cũ.
        if a.platform == "yt":
            _node = shutil.which("node")
            o["js_runtimes"] = {"node": {"path": _node}} if _node else {"node": {"path": None}}
            o["remote_components"] = ["ejs:github"]
        if playlistend:
            o["playlistend"] = playlistend
        # "Theo link" (detail): CHỈ tải ĐÚNG video được dán — KHÔNG kéo cả playlist/radio-mix khi URL có &list=
        # (vd watch?v=X&list=RDxxx = radio 60 video). creator/search dùng URL playlist THẬT nên KHÔNG set.
        if a.type == "detail":
            o["noplaylist"] = True
        return o

    # ---- Dựng danh sách (URL, outtmpl) theo chế độ ----
    cong_viec = []  # mỗi phần tử: (list_url, outtmpl, playlistend)

    if a.type == "search":
        if a.platform == "yt":
            for kw in tach_dong(a.input):
                thu_muc = os.path.join(base, "tu-khoa", an_toan(kw))
                outtmpl = os.path.join(thu_muc, "%(title).80B [%(id)s].%(ext)s")
                cong_viec.append(([f"{plat['search_prefix']}{count}:{kw}"], outtmpl, count))
                log(f"🔎 Tìm YouTube: {kw} (tối đa {count})")
        elif a.platform == "rd":
            for kw in tach_dong(a.input):
                links = reddit_lay_links("search", kw, a.sort, a.time, count)
                if not links:
                    log(f"⚠ Reddit: không thấy post có video cho '{kw}'.")
                    continue
                thu_muc = os.path.join(base, "tu-khoa", an_toan(kw))
                outtmpl = os.path.join(thu_muc, "%(title).80B [%(id)s].%(ext)s")
                cong_viec.append((links, outtmpl, None))
                log(f"🔎 Reddit '{kw}' (sort={a.sort or 'top'}): {len(links)} post có video")
        else:
            log(f"⚠ {a.platform.upper()} không hỗ trợ tìm theo từ khóa. Dùng link hoặc theo kênh/user.")
            print("YTDLP_DONE 0", flush=True)
            return

    elif a.type == "creator":
        if a.platform == "rd":
            for sub_in in tach_dong(a.input):
                sub = reddit_sub(sub_in)
                links = reddit_lay_links("creator", sub_in, a.sort, a.time, count)
                if not links:
                    log(f"⚠ Reddit r/{sub}: không thấy post có video.")
                    continue
                thu_muc = os.path.join(base, "kenh", an_toan(sub))
                outtmpl = os.path.join(thu_muc, "%(title).80B [%(id)s].%(ext)s")
                cong_viec.append((links, outtmpl, None))
                log(f"📺 Reddit r/{sub} (sort={a.sort or 'hot'}): {len(links)} post có video")
        elif a.platform in ("tw", "ig"):
            urls = [chuan_hoa_user(a.platform, x) for x in tach_dong(a.input)]
            thu_muc = os.path.join(base, "kenh", "%(uploader,channel,uploader_id)s")
            outtmpl = os.path.join(thu_muc, "%(title).80B [%(id)s].%(ext)s")
            cong_viec.append((urls, outtmpl, count))
            log(f"📺 Tải theo user: {len(urls)} user (tối đa {count} video/user)")
        elif a.platform == "yt":
            urls = [chuan_hoa_kenh_youtube(x) for x in tach_dong(a.input)]
            thu_muc = os.path.join(base, "kenh", "%(channel,uploader,uploader_id)s")
            outtmpl = os.path.join(thu_muc, "%(title).80B [%(id)s].%(ext)s")
            cong_viec.append((urls, outtmpl, count))
            log(f"📺 Tải theo kênh YouTube: {len(urls)} kênh (tối đa {count} video/kênh)")
        elif a.platform == "fb":
            # yt-dlp không liệt kê được Page FB -> liệt kê bằng Playwright rồi tải TỪNG link (mirror TikTok)
            items, seen = [], set()
            for x in tach_dong(a.input):
                for it in _fb_liet_ke_kenh(x, count, log=log):
                    if it["id"] not in seen:
                        seen.add(it["id"]); items.append(it)
            if not items:
                log("⚠ Facebook: không lấy được video nào từ Page (thử đăng nhập Facebook để ổn định hơn, hoặc thử lại sau).")
                print("YTDLP_DONE 0", flush=True)
                return
            urls = [it["url"] for it in items]
            thu_muc = os.path.join(base, "kenh", "%(uploader,channel,uploader_id)s")
            outtmpl = os.path.join(thu_muc, "%(title).80B [%(id)s].%(ext)s")
            cong_viec.append((urls, outtmpl, None))   # đã giới hạn count khi liệt kê -> playlistend None
            log(f"📺 Tải theo kênh Facebook: {len(urls)} video")
        else:  # tt
            chan_urls = []
            for x in tach_dong(a.input):
                u = chuan_hoa_kenh_tiktok(x)
                if u:
                    chan_urls.append(u)
                else:
                    log(f"⚠ TikTok: không lấy được kênh từ '{x[:50]}' (thử lại, hoặc dán link 1 video của kênh).")
            if not chan_urls:
                log("⚠ TikTok: không có kênh hợp lệ để tải.")
                print("YTDLP_DONE 0", flush=True)
                return
            # TikTok: tải THẲNG url kênh (extract playlist non-flat) hay 0 video (anti-bot). Thay vì vậy:
            # LIỆT KÊ flat ra URL TỪNG VIDEO (đã chứng minh chạy) RỒI tải từng video như link (cũng đã chạy).
            from yt_dlp import YoutubeDL as _YDLf
            _fo = {"extract_flat": "in_playlist", "skip_download": True, "playlistend": count,
                   "quiet": True, "no_warnings": True, "ignoreerrors": True, "nocheckcertificate": True}
            if cookies_file and os.path.isfile(cookies_file):
                _fo["cookiefile"] = cookies_file
            urls = []
            with _YDLf(_fo) as _yf:
                for cu in chan_urls:
                    try:
                        _info = _yf.extract_info(cu, download=False)
                    except Exception as e:
                        log(f"⚠ Liệt kê kênh TikTok lỗi: {str(e)[:100]}"); continue
                    for _e in ((_info or {}).get("entries") or []):
                        _vu = (_e or {}).get("url") or (_e or {}).get("webpage_url")
                        if _vu:
                            urls.append(_vu)
                        if len(urls) >= count:
                            break
            if not urls:
                log("⚠ TikTok: kênh không liệt kê được video nào (anti-bot / kênh trống). Thử lại hoặc dán link 1 video.")
                print("YTDLP_DONE 0", flush=True)
                return
            thu_muc = os.path.join(base, "kenh", "%(channel,uploader,uploader_id)s")
            outtmpl = os.path.join(thu_muc, "%(title).80B [%(id)s].%(ext)s")
            cong_viec.append((urls, outtmpl, None))   # đã giới hạn count khi liệt kê → playlistend None
            log(f"📺 Tải theo kênh TikTok: {len(urls)} video")

    else:  # detail
        # H11 SSRF: URL người dùng DÁN THÔ → lọc scheme http(s) + chặn loopback/private (file://, 127.0.0.1...).
        urls = [u for u in tach_dong(a.input) if _url_an_toan(u)]
        if not urls:
            log("⚠ Không có URL hợp lệ (chỉ nhận link http/https công khai; bỏ file:// và địa chỉ nội bộ).")
            print("YTDLP_DONE 0", flush=True)
            return
        # TikTok: rewrite /photo/->/video/ (extractor chỉ nhận /video/), và pre-check bài ẢNH
        # slideshow (không có format video) -> bỏ qua + báo rõ thay vì tải nhầm audio / "0 video" mơ hồ.
        if a.platform == "tt":
            from yt_dlp import YoutubeDL as _YDL
            pre_opts = {"skip_download": True, "quiet": True, "no_warnings": True,
                        "nocheckcertificate": True, "ignoreerrors": True}
            if cookies_file and os.path.isfile(cookies_file):
                pre_opts["cookiefile"] = cookies_file
            loc = []
            for u in urls:
                nu, la_photo = chuan_hoa_link_tiktok(u)
                if not la_photo:
                    loc.append(nu)
                    continue
                # bài /photo/: kiểm tra có stream video không (slideshow ảnh thì không có)
                co_video = False
                try:
                    with _YDL(pre_opts) as _y:
                        _info = _y.extract_info(nu, download=False)
                    co_video = bool(_info) and any(
                        (f.get("vcodec") or "none") != "none" for f in (_info.get("formats") or []))
                except Exception:
                    co_video = False
                if co_video:
                    loc.append(nu)
                else:
                    log(f"ℹ Bỏ qua bài ẢNH (slideshow TikTok, không có video): {u[:60]}")
            if not loc:
                log("⚠ Link TikTok là bài ẢNH (slideshow) — không có video để tải. "
                    "Tool chỉ tải VIDEO; hãy dùng link bài /video/.")
                print("YTDLP_DONE 0", flush=True)
                return
            urls = loc
        thu_muc = os.path.join(base, "link")
        outtmpl = os.path.join(thu_muc, "%(title).80B [%(id)s].%(ext)s")
        cong_viec.append((urls, outtmpl, None))
        log(f"🔗 Tải theo link: {len(urls)} video")

    # ---- Thực thi ---- (finally: luôn dọn cookie phiên tạm, kể cả khi yt-dlp throw giữa chừng)
    try:
        for urls, outtmpl, pe in cong_viec:
            try:
                with YoutubeDL(opts_cho(outtmpl, pe)) as ydl:
                    ydl.download(urls)
            except Exception as e:
                log(f"⚠ Lỗi: {str(e)[:160]}")
    finally:
        _don_cookie_temp()

    log(f"✔ Hoàn tất. Tải được {len(da_xong)} video.")
    print(f"YTDLP_DONE {len(da_xong)}", flush=True)


if __name__ == "__main__":
    main()
