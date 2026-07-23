# -*- coding: utf-8 -*-
"""
Mở SẴN trình duyệt nhiều nền tảng để ĐĂNG NHẬP một lần.
Mỗi nền tảng 1 cửa sổ Chromium dùng đúng hồ sơ mà crawler dùng -> đăng nhập xong
cứ đóng cửa sổ, phiên được lưu lại, các lần cào/tìm kênh sau khỏi quét QR.

Dùng:  python mo_dang_nhap.py            (mở cả dy, bili, xhs)
        python mo_dang_nhap.py dy bili    (chỉ mở các nền tảng chỉ định)
"""
import os
import sys
import json
import time

from playwright.sync_api import sync_playwright

THU_MUC_GOC = os.path.dirname(os.path.abspath(__file__))
THU_MUC_CRAWLER = os.path.join(THU_MUC_GOC, "MediaCrawler")
STATUS_FILE = os.path.join(THU_MUC_GOC, "_login_check.json")

# Xiaohongshu QUỐC TẾ (rednote.com) khi tool bật cờ MC_XHS_INTL — tài khoản ngoài TQ bị
# xiaohongshu.com redirect sang rednote.com (domain/cookie khác → login/cào hỏng nếu nhắm bản Trung).
XHS_INTL = os.environ.get("MC_XHS_INTL", "0") == "1"

URL = {
    "dy":   "https://www.douyin.com",
    "bili": "https://www.bilibili.com",
    "xhs":  "https://www.xiaohongshu.com",   # NỘI ĐỊA (domain cố định theo platform, bỏ toggle)
    "rednote": "https://www.rednote.com",    # QUỐC TẾ — nền tảng RIÊNG, profile riêng
    "wb":   "https://weibo.com",
    "tw":   "https://x.com/login",
    "ig":   "https://www.instagram.com/accounts/login/",
    "th":   "https://www.threads.com/login",
    "tt":   "https://www.tiktok.com/login",
    "fb":   "https://www.facebook.com/login/",
}
# Domain + cookie CHỈ có khi đã đăng nhập (giống kiem_tra_login.py) — để dò LIVE rồi tự đóng.
HOST = {"dy": "douyin.com", "bili": "bilibili.com",
        "xhs": "xiaohongshu.com", "rednote": "rednote.com",
        "wb": "weibo.com", "tw": "x.com", "ig": "instagram.com", "th": "threads",
        "tt": "tiktok.com", "fb": "facebook.com"}
AUTH = {
    "dy": ["sessionid", "sessionid_ss", "sid_tt"],
    "tt": ["sessionid", "sessionid_ss", "sid_tt"],   # TikTok (ByteDance, cùng họ Douyin)
    "bili": ["SESSDATA", "DedeUserID"],
    # XHS web login: phiên thật = web_session (xiaohongshu.com & rednote.com) + id_token (bản rednote).
    # Cookie creator cũ KHÔNG có ở web thường -> trước đây không tự đóng cửa sổ & không ghi "in" sau login.
    "xhs": ["web_session", "id_token"],
    "rednote": ["web_session", "id_token"],   # XHS QUỐC TẾ — nền tảng riêng
    "wb": ["SUB", "SUBP", "SSOLoginState"],
    "tw": ["auth_token", "ct0"],
    "ig": ["sessionid", "ds_user_id"],
    "th": ["sessionid"],
    "fb": ["c_user", "xs"],   # c_user = user ID, xs = session token — chỉ có khi đã đăng nhập
}
# Threads dùng profile RIÊNG (browser_data/threads) — chung với chup_bai.py feed/search.
PROFILE_RIENG = {"th": os.path.join(THU_MUC_GOC, "browser_data", "threads")}


def _da_login(ctx, plat):
    """Đọc cookie từ context ĐANG CHẠY (không qua đĩa → không race/khóa profile).
    TikTok: cookie sessionid/sid_tt GIỮ cả khi phiên ĐÃ CHẾT -> cookie-presence báo 'in' OAN
    (giữ cửa sổ mở -> khóa profile -> cào 'chưa đăng nhập'). Dựa REDIRECT: trang /login bị đá
    sang trang chủ (URL không còn /login) = phiên SỐNG; còn ở /login = chưa đăng nhập."""
    if plat == "tt":
        try:
            for pg in ctx.pages:
                u = (pg.url or "").lower()
                if "tiktok.com" in u and "/login" not in u and "/signup" not in u:
                    return True
            return False
        except Exception:
            return False
    if plat == "dy":
        # Douyin: DOM trang đang mở: nút 登录 hiện = chưa login. Mất nút + HasUserLogin='1' = đã login.
        # BẪY: HasUserLogin CÒN '1' cả khi phiên hết hạn, VÀ trang captcha/degraded (验证码中间页) KHÔNG có
        # nút 登录 -> tin cờ cũ = 'đã login' OAN -> ban_dau/poll đóng cửa sổ TRƯỚC khi user kịp login.
        # -> Trên trang captcha/degraded (title 验证码 / body rỗng) trả False (chưa chắc → GIỮ cửa sổ mở).
        try:
            for pg in ctx.pages:
                if "douyin.com" not in (pg.url or ""):
                    continue
                sig = pg.evaluate(
                    """() => {
                        const vis = (e) => e && e.offsetParent !== null;
                        const els = Array.from(document.querySelectorAll('button,a,div,span,p'));
                        const hasLogin = els.some(e => {
                            if (!vis(e)) return false;
                            const t = (e.textContent || '').trim();
                            if (t.length > 6) return false;
                            return t === '登录' || t === '登 录' || t === '登錄';
                        });
                        let has = null;
                        try { has = window.localStorage.getItem('HasUserLogin'); } catch (e) {}
                        const title = document.title || '';
                        const blen = document.body ? (document.body.innerText || '').length : 0;
                        const chan = /验证码|verify|captcha/i.test(title) || blen < 40;
                        return { hasLogin, has, chan };
                    }""")
                if sig.get("hasLogin"):
                    return False
                if sig.get("chan"):        # trang captcha/degraded -> KHÔNG tin cờ cũ (tránh đóng oan)
                    return False
                if sig.get("has") == "1":
                    return True
            return False
        except Exception:
            return False
    if plat in ("xhs", "rednote"):
        # loggedIn THẬT (__INITIAL_STATE__.user.loggedIn — Vue ref). id_token/web_session CÒN trên đĩa cả
        # khi phiên CHẾT -> cookie-presence = 'đã login' OAN -> đóng cửa sổ trước khi user login. Đọc DOM
        # trang đang mở (cửa sổ HEADFUL nên KHÔNG degrade). loggedIn===true mới là đã login THẬT.
        try:
            host = HOST.get(plat, "")
            for pg in ctx.pages:
                if host and host not in (pg.url or ""):
                    continue
                li = pg.evaluate(
                    """() => { try {
                        const u = (window.__INITIAL_STATE__ || {}).user || {};
                        const unref = (r) => (r && typeof r === 'object' && ('value' in r)) ? r.value : r;
                        return unref(u.loggedIn) === true;
                    } catch (e) { return false; } }""")
                if li:
                    return True
            return False
        except Exception:
            return False
    # bili + nền khác: cookie auth trên context (bili đã login sẵn -> đóng là ĐÚNG).
    try:
        cookies = ctx.cookies()
    except Exception:
        return False
    names, host = AUTH.get(plat, []), HOST.get(plat, "")
    for c in cookies:
        if (c.get("name") in names and host in (c.get("domain") or "")
                and (c.get("value") or "").strip()):
            return True
    return False


def _ghi_status(st):
    """Cập nhật (merge) _login_check.json — chỉ đụng nền tảng đang xử lý, giữ nguyên cái khác."""
    cur = {}
    try:
        with open(STATUS_FILE, encoding="utf-8") as f:
            cur = json.load(f)
    except Exception:
        cur = {}
    cur.update(st)
    try:
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(cur, f, ensure_ascii=False)
    except Exception:
        pass
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# Vị trí cửa sổ để các web không chồng khít lên nhau
VITRI = {"dy": (0, 0), "bili": (470, 0), "xhs": (940, 0), "wb": (0, 430)}


def _kill_profile_holders(user_data_dir):
    """Giết MỌI tiến trình Chromium đang giữ khóa profile này (cửa sổ login CŨ kẹt/vô hình giữ khóa
    -> bấm login mới 'không hiện cửa sổ'). CHỈ gọi khi mở login THẤT BẠI (profile đang bị dùng)."""
    try:
        import subprocess as _sp
        udd = (user_data_dir or "").replace("'", "''")
        if not udd:
            return
        ps = ("Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" -EA SilentlyContinue | "
              "Where-Object { $_.CommandLine -like '*" + udd + "*' } | "
              "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -EA SilentlyContinue }")
        _sp.run(["powershell", "-NoProfile", "-Command", ps], timeout=20,
                creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0))
    except Exception:
        pass


def main():
    platforms = [p for p in sys.argv[1:] if p in URL] or ["dy", "bili", "xhs"]
    stealth_path = os.path.join(THU_MUC_CRAWLER, "libs", "stealth.min.js")
    # Cửa sổ luôn TO (đủ chỗ cho QR/hộp đăng nhập). Mở nhiều thì xếp lệch (cascade).
    rong, cao = 1180, 880

    with sync_playwright() as p:
        items = []   # [(plat, ctx)]
        for i, plat in enumerate(platforms):
            # MC_BROWSER_DATA_DIR (web_app đặt = userData) -> cookie BỀN qua update; fallback chỗ cũ (dev)
            _bd = os.environ.get("MC_BROWSER_DATA_DIR") or os.path.join(THU_MUC_CRAWLER, "browser_data")
            user_data_dir = PROFILE_RIENG.get(plat) or os.path.join(_bd, f"{plat}_user_data_dir")
            os.makedirs(user_data_dir, exist_ok=True)
            x, y = 120 + i * 40, 30 + i * 36   # xếp lệch nhau cho dễ kéo
            def _mo_ctx():
                return p.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    headless=False,
                    accept_downloads=True,
                    viewport={"width": rong - 20, "height": cao - 90},
                    user_agent=UA,
                    ignore_default_args=["--enable-automation"],
                    args=[
                        f"--window-position={x},{y}",
                        f"--window-size={rong},{cao}",
                        "--hide-crash-restore-bubble",
                        "--no-first-run",
                        "--no-default-browser-check",
                        "--disable-session-crashed-bubble",
                    ],
                )
            try:
                ctx = _mo_ctx()
            except Exception:
                # Profile bị KHÓA (cửa sổ login CŨ kẹt/vô hình giữ khóa) -> TỰ CHỮA: giết tiến trình giữ
                # profile rồi MỞ LẠI (hết "ấn login không hiện cửa sổ" do orphan tích lại).
                print(f"[mo_dang_nhap] {plat}: profile đang bị khóa, dọn cửa sổ cũ rồi mở lại...")
                _kill_profile_holders(user_data_dir)
                time.sleep(2.0)
                try:
                    ctx = _mo_ctx()
                except Exception as e:
                    print(f"[mo_dang_nhap] khong mo duoc {plat}: {e}")
                    continue
            if os.path.exists(stealth_path):
                try:
                    ctx.add_init_script(path=stealth_path)
                except Exception:
                    pass
            page = ctx.new_page()
            try:
                page.goto(URL[plat], wait_until="domcontentloaded", timeout=60000)
                if plat == "dy":
                    # Douyin là SPA: domcontentloaded xong nút 登录 CHƯA kịp render -> đọc DOM ngay bị
                    # race (giống bug đã fix ở kiem_tra_login._dy_login) -> ban_dau sai -> auto-close nhầm.
                    # Chờ 1 LẦN ở đây (không phải trong vòng poll, tránh làm chậm poll mỗi 1s).
                    page.wait_for_timeout(1800)
            except Exception:
                pass
            # đóng tab cũ còn sót
            for other in list(ctx.pages):
                if other is not page:
                    try:
                        other.close()
                    except Exception:
                        pass
            # Trạng thái login LÚC MỞ (cookie sẵn trên hồ sơ). Chỉ auto-close khi login MỚI
            # trong phiên này (chưa->có); đã login sẵn thì GIỮ cửa sổ cho user (đổi nick / kiểm tra).
            try:
                # tt: ÉP ban_dau=False để vòng poll TỰ ĐÓNG cửa sổ ngay khi phát hiện login (redirect),
                # giải phóng khóa profile cho lúc cào. Cookie chết không bị tưởng "đã login" -> không giữ oan.
                ban_dau = False if plat == "tt" else _da_login(ctx, plat)
            except Exception:
                ban_dau = False
            if ban_dau:
                _ghi_status({plat: "in"})
            items.append((plat, ctx, ban_dau, time.time(), 0))   # 0 = số lần liên tiếp đọc thấy "vừa login"

        if not items:
            print("[mo_dang_nhap] khong mo duoc cua so nao")
            return

        # Vòng theo dõi: login MỚI xong (cookie LIVE) -> ghi trạng thái + TỰ ĐÓNG cửa sổ đó.
        # Cửa sổ đã-login-sẵn hoặc chưa login thì giữ tới khi người dùng tự đóng. Poll 1s.
        # BACKSTOP 5 phút: cửa sổ login BỎ QUÊN (đã-login-sẵn không đóng tay, hoặc mở rồi không login)
        # TỰ ĐÓNG -> không kẹt VĨNH VIỄN giữ khóa profile (gây cào 'chưa đăng nhập' + chồng chất 20+ cửa sổ).
        def _bao_va_dong(ctx, text):
            try:                          # phủ overlay báo người dùng rồi đóng (giải phóng khóa profile)
                ctx.pages[0].evaluate(
                    "(t)=>{const d=document.createElement('div');"
                    "d.style.cssText='position:fixed;inset:0;z-index:2147483647;display:flex;"
                    "align-items:center;justify-content:center;background:rgba(8,12,22,.92);"
                    "color:#fff;font:600 22px system-ui';d.textContent=t;"
                    "document.body.appendChild(d);}", text)
            except Exception:
                pass
            time.sleep(1.4)
            try:
                ctx.close()
            except Exception:
                pass

        # BACKSTOP 5 phút giữ nguyên cho ca CHƯA login (mở rồi không đăng nhập). Cửa sổ ĐÃ-LOGIN-SẴN
        # (ban_dau=True) -> đóng sau 5s: giữ cửa sổ = khóa độc quyền profile = chặn cào/preview/gợi-ý
        # ("chưa đăng nhập"/"không ra"); đã login sẵn thì không cần giữ.
        deadline = time.time() + 300
        try:
            while items and time.time() < deadline:
                con_lai = []
                for plat, ctx, ban_dau, t_open, xn in items:
                    try:
                        con_mo = bool(ctx.pages)
                    except Exception:
                        con_mo = False
                    if not con_mo:        # user tự đóng -> bỏ qua, để bản đĩa lo
                        continue
                    if ban_dau and time.time() - t_open >= 5:   # đã login sẵn lúc mở -> thả profile
                        print(f"[mo_dang_nhap] {plat} da dang nhap san -> dong sau 5s")
                        _bao_va_dong(ctx, "✅ Da dang nhap san — dang dong cua so...")
                        continue
                    if not ban_dau:
                        # DEBOUNCE: chỉ tin "vừa login" khi đọc thấy True 2 LẦN LIÊN TIẾP (cách nhau 1s).
                        # 1 lần True đơn lẻ có thể là đọc nhầm thoáng qua (DOM/localStorage đang chuyển
                        # trạng thái giữa lúc quét QR) -> ghi "in" sai vào _login_check.json -> cache đó
                        # được /api/login_trangthai tin tới 5 PHÚT (không có gì tự sửa lại) -> báo xanh giả
                        # dù đăng nhập chưa xong -> cửa sổ đã đóng nên không quét lại được -> "vẫn lỗi".
                        if _da_login(ctx, plat):
                            if xn >= 1:   # đã True ở lượt poll TRƯỚC -> xác nhận, đóng thật
                                _ghi_status({plat: "in"})
                                print(f"[mo_dang_nhap] {plat} vua dang nhap -> tu dong")
                                _bao_va_dong(ctx, "✅ Da dang nhap — dang dong cua so...")
                                continue      # bỏ khỏi danh sách theo dõi
                            con_lai.append((plat, ctx, ban_dau, t_open, xn + 1)); continue
                        xn = 0   # đọc False -> reset (phải 2 lần LIÊN TIẾP, không phải cộng dồn)
                    con_lai.append((plat, ctx, ban_dau, t_open, xn))
                items = con_lai
                time.sleep(1.0)
        except Exception:
            pass
        for plat, ctx, _bd, _t, _xn in items:
            try:
                ctx.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
