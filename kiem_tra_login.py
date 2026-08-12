# -*- coding: utf-8 -*-
"""
Kiểm tra ĐĂNG NHẬP từng nền tảng bằng cách mở trình duyệt NGẦM (headless) với đúng
hồ sơ của tool, đọc cookie thật (kể cả httpOnly) + kiểm tra giao diện, rồi TỰ ĐÓNG.

Dùng:  python kiem_tra_login.py dy bili xhs wb
Ghi kết quả JSON {ma: "in"|"out"|"unknown"} ra _login_check.json và in ra stdout.
"""
import os
import sys
import json
import shutil
import sqlite3
import subprocess
import tempfile
import time

from playwright.sync_api import sync_playwright

THU_MUC_GOC = os.path.dirname(os.path.abspath(__file__))
THU_MUC_CRAWLER = os.path.join(THU_MUC_GOC, "MediaCrawler")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# Xiaohongshu QUỐC TẾ (rednote.com) khi tool bật cờ MC_XHS_INTL — phải khớp domain user thật
# (tài khoản ngoài TQ bị redirect sang rednote.com) thì check login mới đúng.
XHS_INTL = os.environ.get("MC_XHS_INTL", "0") == "1"

# XHS tách 2 nền tảng RIÊNG (domain CỐ ĐỊNH theo platform, KHÔNG còn theo toggle MC_XHS_INTL — vì 1 lần
# check nhiều nền không thể vừa nội-địa vừa quốc-tế): xhs = xiaohongshu.com · rednote = rednote.com.
HOST = {"dy": "douyin.com", "bili": "bilibili.com",
        "xhs": "xiaohongshu.com", "rednote": "rednote.com", "wb": "weibo.com",
        "tw": "x.com", "ig": "instagram.com", "tt": "tiktok.com", "fb": "facebook.com"}
URL = {"dy": "https://www.douyin.com", "bili": "https://www.bilibili.com",
       "xhs": "https://www.xiaohongshu.com", "rednote": "https://www.rednote.com",
       "wb": "https://weibo.com", "tw": "https://x.com", "ig": "https://www.instagram.com",
       "tt": "https://www.tiktok.com", "fb": "https://www.facebook.com"}
# Cookie CHỈ có khi đã đăng nhập (không tính cookie khách)
AUTH = {
    "dy": ["sessionid", "sessionid_ss", "sid_tt"],
    "bili": ["SESSDATA", "DedeUserID"],
    # XHS web login: cookie phiên THẬT là `web_session` (xiaohongshu.com & rednote.com) + `id_token`
    # (chỉ có khi đã đăng nhập, bản rednote). Cookie creator cũ (customer-sso-sid...) KHÔNG xuất hiện
    # ở web thường -> dùng chúng làm cổng khiến tài khoản đã đăng nhập vẫn bị báo "out". Quyết định
    # chính cho XHS là DOM (xem _check); list này chỉ là fallback khi DOM không chắc.
    "xhs": ["web_session", "id_token"],
    "rednote": ["web_session", "id_token"],   # XHS QUỐC TẾ — cùng cookie, domain/profile RIÊNG
    "wb": ["SUB", "SUBP", "SSOLoginState"],
    "tw": ["auth_token", "ct0"],
    "ig": ["sessionid", "ds_user_id"],
    "tt": ["sessionid", "sessionid_ss", "sid_tt"],   # TikTok (ByteDance) — như Douyin; cookie giữ cả khi phiên chết -> phải kiểm DOM
    "fb": ["c_user", "xs"],   # c_user = user ID, xs = session token — như tw/ig: chưa có DOM-verify riêng, tin cookie-presence
}


def _cookie_in(cookies, plat, names=None):
    if names is None:
        names = AUTH.get(plat, [])
    host = HOST.get(plat, "")
    for c in cookies:
        if (c.get("name") in names and host in (c.get("domain") or "")
                and (c.get("value") or "").strip()):
            return True
    return False


def _xhs_dom(page, plat="xhs"):
    """XHS: cookie web_session có cả ở khách -> kiểm tra giao diện cho chắc.
    Nhận diện CẢ bản Trung (xiaohongshu.com: nút '登录' + class .reds-avatar) LẪN bản quốc tế
    (rednote.com: nút 'Log in'/'Sign in' tiếng Anh + avatar DOM khác). plat='rednote' → rednote.com."""
    try:
        page.goto(URL.get(plat, URL["xhs"]), wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2800)
        return page.evaluate(
            """() => {
                // ĐỊNH ĐOẠT: __INITIAL_STATE__.user.loggedIn (Vue ref) = cờ login THẬT của XHS. Trang /explore
                // LUÔN có nút '登录' rải rác (mỗi post) + avatar FEED (không phải của user) -> đếm '登录'/avatar
                // SAI (luôn 'out' oan dù đã đăng nhập). Đã kiểm: login thật loggedIn=true · phiên chết loggedIn=false.
                try {
                    const u = (window.__INITIAL_STATE__ || {}).user || {};
                    const unref = (r) => (r && typeof r === 'object' && ('value' in r)) ? r.value : r;
                    const li = unref(u.loggedIn);
                    if (li === true) return 'in';
                    if (li === false) return 'out';
                } catch (e) {}
                // Fallback (rednote / __INITIAL_STATE__ vắng): nút đăng nhập + avatar (kém tin hơn)
                const vis = (e) => e && e.offsetParent !== null;
                const els = Array.from(document.querySelectorAll('button,a,div,span'));
                const hasLogin = els.some(e => {
                    if (!vis(e)) return false;
                    const t = (e.textContent || '').trim();
                    if (t.length > 12) return false;
                    return t === '登录' || /^(log\\s?in|sign\\s?in)$/i.test(t);
                });
                const hasAvatar = !!document.querySelector(
                    '.user .reds-avatar, .reds-avatar, img.user-avatar, .side-bar .user, ' +
                    '[class*="avatar"] img, [class*="Avatar"] img, img[class*="avatar"]');
                if (hasLogin) return 'out';
                if (hasAvatar) return 'in';
                return 'unknown';
            }"""
        )
    except Exception:
        return None


def _tt_dom(page):
    """TikTok: cookie sessionid/sid_tt CÒN trên đĩa cả khi phiên ĐÃ CHẾT -> 'in' oan. KHÔNG dò DOM được
    vì TikTok trả trang RỖNG cho headless (anti-bot). Cách TIN CẬY = vào trang /upload (cần đăng nhập):
    chưa login -> TikTok ĐÁ về /login (ở tầng ĐIỀU HƯỚNG, không phụ thuộc JS) -> 'out'; còn ở /upload
    (hoặc tiktokstudio) -> 'in'; khác/lỗi -> None để caller giữ theo cookie (tránh 'out' oan)."""
    try:
        page.goto(URL["tt"].rstrip("/") + "/upload", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1500)
        u = (page.url or "").lower()
        if "/login" in u:
            return "out"
        if "/upload" in u or "tiktokstudio" in u or "studio.tiktok" in u:
            return "in"
        return None
    except Exception:
        return None


def _fb_login(ctx, cookies):
    """Facebook: cookie datr/fr/sb là cookie KHÁCH (Facebook set cả khi CHƯA login) → cookie-presence
    báo 'in' OAN ('xanh giả'). Cookie auth THẬT = c_user (user id) + xs (session). Đã reproduce: badge
    'in' mà profile chỉ có datr/fr/sb (không c_user/xs) + facebook.com hiện FORM LOGIN.
    → (1) không có c_user+xs trên đĩa = chắc chắn CHƯA login → 'out'. (2) có → xác minh DOM: form login
    (input password/email) hiện = phiên chết → 'out'; có UI đã-login (nav/compose) → 'in'; lỗi → giữ cookie."""
    have_auth = _cookie_in(cookies, "fb", ["c_user"]) and _cookie_in(cookies, "fb", ["xs"])
    if not have_auth:
        return "out"                         # thiếu c_user/xs = chưa đăng nhập thật (dù còn cookie khách)
    try:
        page = ctx.new_page()
        page.goto(URL["fb"], wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)
        sig = page.evaluate(
            """() => {
                const hasPw = !!document.querySelector('input[type=password], input[name=pass]');
                const hasEmail = !!document.querySelector('input[name=email], input#email');
                const hasNav = !!document.querySelector('[aria-label*="Your profile"], [aria-label*="Trang cá nhân"], div[role=navigation]');
                const hasCompose = !!document.querySelector('[aria-label*="Create a post"], [aria-label*="Tạo bài"]');
                return { form_login: (hasPw && hasEmail), da_login_ui: (hasNav || hasCompose) };
            }""")
        if sig.get("form_login") and not sig.get("da_login_ui"):
            return "out"                     # form login hiện + không UI đã-login = phiên chết
        if sig.get("da_login_ui"):
            return "in"
        return "in"                          # có c_user+xs, DOM không rõ → tin cookie auth (đừng đỏ oan)
    except Exception:
        return "in"                          # lỗi mạng → có c_user+xs thì giữ 'in'


def _api_bili_login(ctx):
    """Bilibili: cookie SESSDATA có thể CÒN trên đĩa nhưng đã HẾT HẠN → chỉ kiểm tra 'có cookie'
    sẽ báo 'in' oan. Gọi API nav (dùng cookie của context đang chạy) để biết server còn nhận phiên không.
    Trả 'in'/'out' nếu chắc chắn, None nếu không xác định (lỗi mạng → caller giữ theo cookie)."""
    try:
        r = ctx.request.get("https://api.bilibili.com/x/web-interface/nav",
                            headers={"User-Agent": UA, "Referer": "https://www.bilibili.com"},
                            timeout=15000)
        if not r.ok:
            return None
        d = r.json()
        if not isinstance(d, dict):
            return None
        is_login = bool((d.get("data") or {}).get("isLogin"))
        code = d.get("code")
        if code == 0 and is_login:
            return "in"
        if code == -101 or (code == 0 and not is_login):   # -101 = 账号未登录
            return "out"
        return None
    except Exception:
        return None


def _bili_login_nobrowser(udd):
    """Bilibili check KHÔNG mở browser — đọc cookie từ profile (cookie_decrypt DPAPI) + httpx gọi nav API.
    Tránh fingerprint Playwright HEADLESS GIẾT phiên (gốc của 'badge đỏ oan' + 'cào lúc được lúc không').
    'in'/'out' nếu chắc; None nếu không xác định (412/lỗi → caller giữ theo cookie)."""
    try:
        import cookie_decrypt
        ck = cookie_decrypt.doc_cookies(udd, "bilibili.com")
    except Exception:
        return None
    if not ck or not ck.get("SESSDATA"):
        return "out"   # không có cookie phiên trên đĩa = chưa đăng nhập
    try:
        import httpx
        cookie_str = "; ".join("%s=%s" % (k, v) for k, v in ck.items())
        r = httpx.get("https://api.bilibili.com/x/web-interface/nav",
                      headers={"User-Agent": UA, "Referer": "https://www.bilibili.com/",
                               "Cookie": cookie_str}, timeout=15.0)
        if r.status_code != 200:
            return None
        d = r.json()
        if not isinstance(d, dict):
            return None
        is_login = bool((d.get("data") or {}).get("isLogin"))
        code = d.get("code")
        if code == 0 and is_login:
            return "in"
        if code == -101 or (code == 0 and not is_login):
            return "out"
        return None
    except Exception:
        return None


def _xhs_login_nobrowser(udd, plat):
    """Xiaohongshu check KHÔNG mở browser — đọc cookie từ profile (cookie_decrypt DPAPI) + httpx gọi trang chủ.
    Tránh fingerprint Playwright HEADLESS GIẾT phiên (gốc của 'cào lúc được lúc không', 'tự văng phiên')."""
    try:
        import cookie_decrypt
        domain = "xiaohongshu.com" if plat == "xhs" else "rednote.com"
        ck = cookie_decrypt.doc_cookies(udd, domain)
    except Exception:
        return None
    if not ck:
        return "out"   # không có cookie trên đĩa
    if not ck.get("web_session") and not ck.get("id_token"):
        return "out"
    try:
        import httpx
        url = "https://www.xiaohongshu.com" if plat == "xhs" else "https://www.rednote.com"
        cookie_str = "; ".join("%s=%s" % (k, v) for k, v in ck.items())
        r = httpx.get(url, headers={"User-Agent": UA, "Cookie": cookie_str}, timeout=15.0)
        if r.status_code != 200:
            return None
        html = r.text
        if '"loggedIn":true' in html:
            return "in"
        if '"loggedIn":false' in html:
            return "out"
        return None
    except Exception:
        return None


def _dom_login(page, url, login_texts):
    """Dò DOM trang chủ: nút đăng nhập (login_texts / 'log in') HIỆN → 'out'; avatar → 'in'; else None.
    Dùng cho nền tảng web (dy/wb): cookie hết hạn → trang hiện nút đăng nhập lại → bắt được 'xanh giả'."""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2800)
        return page.evaluate(
            """(toks) => {
                const vis = (e) => e && e.offsetParent !== null;
                const els = Array.from(document.querySelectorAll('button,a,div,span,p'));
                const hasLogin = els.some(e => {
                    if (!vis(e)) return false;
                    const t = (e.textContent || '').trim();
                    if (t.length > 12) return false;
                    return toks.includes(t) || /^(log\\s?in|sign\\s?in)$/i.test(t);
                });
                const hasAvatar = !!document.querySelector(
                    '[class*="avatar"] img, img[class*="avatar"], [class*="Avatar"] img, ' +
                    'img.bili-avatar-img, .header-avatar img, .gg-login-card');
                if (hasLogin) return 'out';
                if (hasAvatar) return 'in';
                return null;
            }""", list(login_texts))
    except Exception:
        return None


def _sqlite_check(udd, plat):
    """Dự phòng khi KHÔNG mở được trình duyệt (profile vừa đóng còn khóa):
    đọc thẳng Cookies DB + -wal/-shm (copy ra temp) để biết đã đăng nhập chưa."""
    ck = os.path.join(udd, "Default", "Network", "Cookies")
    if not os.path.exists(ck):
        return "out"
    names = AUTH.get(plat, [])
    host = HOST.get(plat, "")
    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp()
        base = os.path.join(tmpdir, "Cookies")
        shutil.copyfile(ck, base)
        for ext in ("-wal", "-shm"):
            if os.path.exists(ck + ext):
                try:
                    shutil.copyfile(ck + ext, base + ext)
                except Exception:
                    pass
        con = sqlite3.connect(base)
        try:
            rows = con.execute(
                "SELECT name, length(encrypted_value), length(value) FROM cookies WHERE host_key LIKE ?",
                ("%" + host + "%",)).fetchall()
            for name, el, vl in rows:
                if name in names and ((el or 0) > 0 or (vl or 0) > 0):
                    return "in"
            return "out"
        finally:
            con.close()
    except Exception:
        return "unknown"
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


def _doi_lang(udd):
    """Vừa ĐÓNG cửa sổ login -> đợi Chromium ghi/checkpoint cookie xong (xóa -wal/-shm)
    rồi mới đọc, tránh đọc nhằm trạng thái CŨ → báo "chưa đăng nhập" oan. Tối đa ~8s."""
    ck = os.path.join(udd, "Default", "Network", "Cookies")
    for _ in range(8):
        try:
            vua_ghi = (os.path.exists(ck + "-wal") or os.path.exists(ck + "-shm")
                       or (os.path.exists(ck) and (time.time() - os.path.getmtime(ck)) < 4))
        except OSError:
            vua_ghi = False
        if not vua_ghi:
            return
        time.sleep(1.0)


def _dy_cookie_login(cookies):
    """Douyin: tín hiệu đăng nhập THẬT mà MediaCrawler dùng (douyin/client.py pong) là cookie
    LOGIN_STATUS == '1' — KHÔNG phải sessionid/sid_tt (mấy cookie đó CÒN LẠI sau khi hết hạn nên
    gây 'xanh giả'). Trả 'in' nếu LOGIN_STATUS=='1'; còn lại None (chưa chắc → xác minh localStorage)."""
    for c in cookies:
        if (c.get("name") == "LOGIN_STATUS" and "douyin.com" in (c.get("domain") or "")
                and (c.get("value") or "").strip() == "1"):
            return "in"
    return None


def _dy_api_login(cookies, udd=None):
    """Xác minh phiên Douyin bằng API THẬT (endpoint self cần đăng nhập) thay vì đoán qua DOM/cookie.
    Cookie sessionid CÒN LẠI sau khi phiên chết → disk-check báo 'xanh giả'; DOM headless hay degrade
    → 'unknown'. API im/spotlight/relation/ (danh sách following của CHÍNH MÌNH) phân biệt rạch ròi:
    phiên sống → trả following list; phiên chết/khách → status_code 8 '用户未登录'. Reproduce THẬT:
    có cookie sống → HTTP200 ~39KB following; guest → 114 bytes 用户未登录. Không cần a_bogus.
    Trả 'in' / 'out' / None (không chắc → để caller rơi về DOM+cookie, KHÔNG đỏ oan).

    QUAN TRỌNG: đọc cookie từ ĐĨA (cookie_decrypt) — sessionid/sessionid_ss/sid_tt là httpOnly, launch
    context headless KHÔNG expose qua ctx.cookies() (đã reproduce: ctx trả 6 cookie, THIẾU sessionid →
    API 用户未登录 → 'out' OAN). Đọc đĩa lấy đủ 56 cookie kể cả httpOnly, khớp cái crawler pong dùng."""
    cookie_str = ""
    if udd:
        try:
            import cookie_decrypt
            ck = cookie_decrypt.doc_cookies(udd, "douyin.com")
            cookie_str = "; ".join(f"{k}={v}" for k, v in ck.items())
        except Exception:
            cookie_str = ""
    if not cookie_str:   # fallback: cookie từ context (thiếu httpOnly nhưng còn hơn không)
        cookie_str = "; ".join(f"{c.get('name')}={c.get('value')}" for c in cookies
                               if c.get("name") and "douyin.com" in (c.get("domain") or ""))
    if not cookie_str:
        return None
    try:
        import httpx
        headers = {"User-Agent": UA, "Cookie": cookie_str, "Referer": "https://www.douyin.com/"}
        with httpx.Client(timeout=12, headers=headers) as c:
            r = c.get("https://www.douyin.com/aweme/v1/web/im/spotlight/relation/")
        if r.status_code != 200:
            return None                       # server lỗi/chặn → không chắc
        j = r.json()
        # Phiên CHẾT: status_code 8 (用户未登录) hoặc trả followings=null kèm không có dữ liệu login.
        if j.get("status_code") == 8 or "用户未登录" in (j.get("status_msg") or ""):
            return "out"
        # Phiên SỐNG: có following list (dù rỗng, status_code 0 = đã xác thực).
        if j.get("status_code") == 0 and "followings" in j:
            return "in"
        return None
    except Exception:
        return None                           # mạng/timeout/parse lỗi → không chắc


def _dy_login(ctx, cookies, udd=None):
    """Trạng thái đăng nhập Douyin. XÁC MINH BẰNG API THẬT trước (chắc chắn nhất, khớp cái crawl kiểm),
    rồi mới DOM. LOGIN_STATUS cookie / HasUserLogin localStorage là CỜ CLIENT — Douyin vô hiệu phiên
    server-side mà 2 cờ này VẪN '1' → 'xanh giả'; cookie sessionid cũng CÒN LẠI sau khi phiên chết.
    → (1) Gọi API self im/spotlight/relation/: following list → 'in'; 用户未登录/status_code 8 → 'out'
    (kể cả cookie còn stale). (2) API không chắc (mạng lỗi) → DOM: nút '登录' hiện rõ → 'out'; không →
    theo cờ. Lỗi load → giữ cờ cũ để tránh 'out' oan khi mạng lỗi."""
    api = _dy_api_login(cookies, udd)           # (1) API thật — trọng tài chính (đọc cookie đĩa)
    if api in ("in", "out"):
        return api
    flag_in = bool(_dy_cookie_login(cookies))   # LOGIN_STATUS=='1'
    try:
        page = ctx.new_page()
        page.goto(URL["dy"], wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(1800)
        sig = page.evaluate(
            """() => {
                const vis = (e) => e && e.offsetParent !== null;
                const els = Array.from(document.querySelectorAll('button,a,div,span,p'));
                // Nút ĐĂNG NHẬP Douyin: text NGẮN, đúng '登录' (đã đăng nhập KHÔNG hiện nút này)
                const hasLogin = els.some(e => {
                    if (!vis(e)) return false;
                    const t = (e.textContent || '').trim();
                    if (t.length > 10) return false;
                    return t === '登录' || t === '登 录' || t === '登錄' || /^(login|log\\s?in)$/i.test(t);
                });
                let has = null;
                try { has = window.localStorage.getItem('HasUserLogin'); } catch (e) {}
                return { hasLogin, has };
            }""")
        if sig.get("hasLogin"):
            # Nút 登录 hiện: CHỈ 'out' khi KHÔNG có cờ cookie (chắc chắn chưa login). Có cờ mà nút vẫn hiện
            # = MÂU THUẪN (trang headless dễ bị degrade/anti-bot) → 'unknown' (vàng), KHÔNG báo đỏ oan.
            return "unknown" if flag_in else "out"
        if sig.get("has") == "1" or flag_in:
            return "in"
        return "unknown"                         # không nút login + không cờ = KHÔNG CHẮC → vàng (đừng đỏ oan)
    except Exception:
        return "in" if flag_in else "unknown"    # lỗi load → có cờ giữ 'in'; không cờ = 'unknown' (đừng đỏ oan)


def _profile_dang_dung(udd):
    """True nếu CÓ tiến trình Chromium khác đang GIỮ profile này (cửa sổ login đang mở / crawl chạy).
    Lúc profile bận, context phụ headless mở ĐÈ lên bị degrade -> trang web phục vụ bản đăng-xuất-giả
    (nút 登录 hiện) -> _dy_login/_check trả 'out' OAN dù đã đăng nhập (đã reproduce với douyin).
    -> Trả 'unknown' thay vì 'out'. Chỉ Windows; nền khác coi như không khóa."""
    if os.name != "nt":
        return False
    key = os.path.basename(str(udd).replace("\\", "/").rstrip("/"))   # vd 'dy_user_data_dir'
    if not key:
        return False
    try:
        ps = ("Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" -EA SilentlyContinue | "
              "Where-Object { $_.CommandLine -like '*" + key + "*' } | Measure-Object | "
              "ForEach-Object { $_.Count }")
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                           capture_output=True, text=True, timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = (r.stdout or "").strip()
        return out.isdigit() and int(out) > 0
    except Exception:
        return False


def _check(p, plat):
    _bd = os.environ.get("MC_BROWSER_DATA_DIR") or os.path.join(THU_MUC_CRAWLER, "browser_data")
    udd = os.path.join(_bd, f"{plat}_user_data_dir")
    if not os.path.isdir(udd):
        return "out"  # chưa từng mở/đăng nhập
    if _profile_dang_dung(udd):
        # Cửa sổ login đang mở / crawl đang chạy giữ khóa profile -> check ngầm KHÔNG tin được
        # (degrade -> 'out' oan). Trả 'unknown' để endpoint giữ trạng thái cũ / disk-check, KHÔNG báo đỏ.
        return "unknown"
    _doi_lang(udd)    # đợi phiên vừa đăng nhập được ghi xuống đĩa xong
    # XHS/rednote: KHÔNG short-circuit theo id_token no-browser nữa. id_token CÒN trên đĩa cả khi phiên
    # đã CHẾT (hết hạn/đăng xuất) -> tin cookie-presence = "xanh giả" (đã xác minh bằng ảnh: badge 'in'
    # mà rednote.com hiện modal đăng nhập). Trọng tài ĐÚNG = DOM `__INITIAL_STATE__.user.loggedIn` ở
    # nhánh dưới (_xhs_dom). id_token VẪN dùng làm FALLBACK khi DOM không chắc (dòng ~398) → giữ chống
    # xanh-giả-chéo-domain cũ mà không còn báo 'in' oan khi session chết.
    if plat == "bili":
        # NO-BROWSER cho bili: KHÔNG mở headless trên profile (fingerprint Playwright GIẾT phiên →
        # badge đỏ oan + "cào lúc được lúc không"). Đọc cookie + nav API qua httpx.
        lv = _bili_login_nobrowser(udd)
        if lv in ("in", "out"):
            return lv
        try:   # không xác định (412/lỗi) → cookie-based: có SESSDATA = 'in' (đừng giết phiên, đừng đỏ oan)
            import cookie_decrypt
            ck = cookie_decrypt.doc_cookies(udd, "bilibili.com")
            return "in" if (ck and ck.get("SESSDATA")) else "out"
        except Exception:
            return "unknown"
    if plat in ("xhs", "rednote"):
        lv = _xhs_login_nobrowser(udd, plat)
        if lv in ("in", "out"):
            return lv
        try:
            import cookie_decrypt
            domain = "xiaohongshu.com" if plat == "xhs" else "rednote.com"
            ck = cookie_decrypt.doc_cookies(udd, domain)
            return "in" if (ck and (ck.get("id_token") or ck.get("web_session"))) else "out"
        except Exception:
            return "unknown"
    # Mở profile NGẦM — vừa đóng cửa sổ login thì profile còn bị khóa -> retry vài lần
    ctx = None
    for _ in range(3):
        try:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=udd, headless=True, user_agent=UA,
                ignore_default_args=["--enable-automation"],
                args=["--no-first-run", "--no-default-browser-check",
                      "--hide-crash-restore-bubble", "--disable-session-crashed-bubble"],
            )
            break
        except Exception:
            time.sleep(1.5)
    if ctx is None:
        return _sqlite_check(udd, plat)   # vẫn khóa -> đọc thẳng SQLite + WAL
    try:
        cookies = ctx.cookies()
        # XHS: web_session có CẢ ở khách (đổi giá trị khi đăng nhập) -> KHÔNG dùng cookie làm cổng,
        # nếu không tài khoản đã đăng nhập (chỉ có web_session/id_token, không có cookie creator) bị
        # báo "out" oan. DOM thật là trọng tài: avatar -> 'in', nút đăng nhập -> 'out'. DOM không
        # chắc (lỗi mạng/uncertain) mới xét cookie phiên còn giá trị để KHÔNG chặn oan người đã login.
        if plat in ("xhs", "rednote"):
            lv = _xhs_dom(ctx.new_page(), plat)
            if lv in ("in", "out"):
                return lv
            # DOM không chắc (lỗi/timeout rednote SPA) -> CHỈ id_token mới chứng minh đã đăng nhập.
            # web_session XHS/rednote set CẢ cho KHÁCH -> dùng nó làm cổng = "xanh giả" (đã xác minh:
            # guest rednote.com có web_session, KHÔNG có id_token). id_token -> 'in'; còn lại -> 'unknown'
            # (KHÔNG 'out': tránh báo nhầm người ĐÃ login khi DOM timeout — bản nội địa có thể thiếu id_token;
            # KHÔNG 'in': tránh xanh giả). 'unknown' để endpoint xét tiếp disk-check. Đồng bộ disk-check web_app.
            return "in" if _cookie_in(cookies, plat, ["id_token"]) else "unknown"
        if plat == "dy":
            # Douyin: dùng tín hiệu pong (LOGIN_STATUS / HasUserLogin) thay vì sessionid — sessionid
            # CÒN LẠI sau khi hết hạn → 'xanh giả' khiến lúc cào ra 0 video. Khớp đúng cái crawl kiểm.
            return _dy_login(ctx, cookies, udd)
        if plat == "fb":
            # Facebook: datr/fr/sb là cookie KHÁCH → cookie-presence = 'xanh giả'. Xác minh c_user+xs + DOM.
            return _fb_login(ctx, cookies)
        # Nền tảng khác: KHÔNG có cookie auth nào trên đĩa -> chắc chắn chưa đăng nhập (nhanh, khỏi mở trang).
        if not _cookie_in(cookies, plat):
            return "out"
        # CÓ cookie auth, NHƯNG cookie có thể đã HẾT HẠN mà vẫn còn trên đĩa -> báo 'in' oan ("xanh giả").
        # XÁC MINH LIVE bằng API/DOM thật. Chỉ trả 'out' khi server/giao diện KHẲNG ĐỊNH chưa đăng nhập;
        # không chắc (lỗi mạng / uncertain) -> giữ 'in' (còn cookie) để KHÔNG chặn oan người đã đăng nhập.
        lv = None
        if plat == "bili":
            lv = _api_bili_login(ctx)
        elif plat == "wb":
            lv = _dom_login(ctx.new_page(), URL["wb"], ["登录", "登 录"])
        elif plat == "tt":
            lv = _tt_dom(ctx.new_page())   # cookie TikTok giữ cả khi phiên chết -> phải kiểm DOM
        # tw/ig: chưa có bước xác minh live đáng tin -> giữ theo cookie (dy đã xử riêng bằng _dy_login ở trên).
        return lv if lv in ("in", "out") else "in"
    except Exception:
        return _sqlite_check(udd, plat)
    finally:
        try:
            ctx.close()
        except Exception:
            pass


def main():
    plats = [a for a in sys.argv[1:] if a in HOST] or ["dy", "bili", "xhs", "wb"]
    out = {}
    with sync_playwright() as p:
        for plat in plats:
            out[plat] = _check(p, plat)
    # MERGE vào _login_check.json sẵn có — chạy 1 nền tảng (vd guardLogin xác minh lại) KHÔNG xoá
    # cache "in" của nền tảng khác. Full-check (/api/login_kiemtra) đã xoá file trước nên vẫn sạch.
    path = os.path.join(THU_MUC_GOC, "_login_check.json")
    cur = {}
    try:
        with open(path, encoding="utf-8") as f:
            cur = json.load(f)
        if not isinstance(cur, dict):
            cur = {}
    except Exception:
        cur = {}
    cur.update(out)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cur, f, ensure_ascii=False)
    except Exception:
        pass
    print("LOGIN_CHECK_DONE " + json.dumps(out))


if __name__ == "__main__":
    main()
