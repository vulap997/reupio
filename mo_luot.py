# -*- coding: utf-8 -*-
"""
Mở cửa sổ Chromium để KHÁCH TỰ LƯỚT / lấy link kênh + link video, dùng ĐÚNG hồ sơ (profile) mà
crawler dùng để cào -> đã đăng nhập sẵn, khỏi login lại; login/lướt ngay trong cửa sổ này thì lần
cào sau THẤY session luôn (KHÔNG cần đồng bộ cookie — cookie phiên không copy được sang profile khác).

KHÁC mo_dang_nhap.py: KHÔNG auto-close, KHÔNG poll trạng thái, KHÔNG ghi _login_check.json — chỉ mở
cửa sổ rồi CHỜ tới khi người dùng tự đóng (block cho tới lúc cửa sổ đóng thì tiến trình thoát).

Ràng buộc: 1 profile Chromium chỉ 1 tiến trình mở 1 lúc -> khi cửa sổ này còn mở, cào nền đó sẽ BỊ
KHÓA. web_app cảnh báo người dùng đóng trước khi cào (guardLogin/_browse_procs).

Dùng:  python mo_luot.py xhs          (mở 1 nền để lướt)
        python mo_luot.py dy bili      (mở nhiều)
"""
import os
import sys
import time

from playwright.sync_api import sync_playwright

THU_MUC_GOC = os.path.dirname(os.path.abspath(__file__))
THU_MUC_CRAWLER = os.path.join(THU_MUC_GOC, "MediaCrawler")

# Trang chủ mỗi nền (nơi khách bắt đầu lướt / dán link kênh). XHS nội địa vs rednote quốc tế = domain riêng.
URL = {
    "dy":   "https://www.douyin.com",
    "bili": "https://www.bilibili.com",
    "xhs":  "https://www.xiaohongshu.com",
    "rednote": "https://www.rednote.com",
    "tt":   "https://www.tiktok.com",
    "fb":   "https://www.facebook.com",
}
# Profile RIÊNG (khớp _xhs_alias của web_app): rednote tách khỏi xhs nội địa.
PROFILE = {"rednote": "rednote_user_data_dir"}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def _kill_profile_holders(user_data_dir):
    """Giết tiến trình Chromium đang giữ khóa profile này (cửa sổ CŨ kẹt/vô hình) -> mở lại được.
    CHỈ gọi khi mở THẤT BẠI (profile đang bị dùng). Copy từ mo_dang_nhap._kill_profile_holders."""
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
    platforms = [p for p in sys.argv[1:] if p in URL] or ["xhs"]
    stealth_path = os.path.join(THU_MUC_CRAWLER, "libs", "stealth.min.js")
    rong, cao = 1180, 880

    with sync_playwright() as p:
        ctxs = []   # [(plat, ctx)]
        for i, plat in enumerate(platforms):
            _bd = os.environ.get("MC_BROWSER_DATA_DIR") or os.path.join(THU_MUC_CRAWLER, "browser_data")
            user_data_dir = os.path.join(_bd, PROFILE.get(plat, f"{plat}_user_data_dir"))
            os.makedirs(user_data_dir, exist_ok=True)
            x, y = 120 + i * 40, 30 + i * 36

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
                # Profile bị KHÓA (cửa sổ cũ kẹt / đang cào) -> dọn tiến trình giữ profile rồi mở lại.
                print(f"[mo_luot] {plat}: profile đang bị khóa, dọn cửa sổ cũ rồi mở lại...")
                _kill_profile_holders(user_data_dir)
                time.sleep(2.0)
                try:
                    ctx = _mo_ctx()
                except Exception as e:
                    print(f"[mo_luot] khong mo duoc {plat}: {e}")
                    continue
            if os.path.exists(stealth_path):
                try:
                    ctx.add_init_script(path=stealth_path)
                except Exception:
                    pass
            page = ctx.new_page()
            try:
                page.goto(URL[plat], wait_until="domcontentloaded", timeout=60000)
            except Exception:
                pass
            for other in list(ctx.pages):   # đóng tab trống còn sót
                if other is not page:
                    try:
                        other.close()
                    except Exception:
                        pass
            ctxs.append((plat, ctx))

        if not ctxs:
            print("[mo_luot] khong mo duoc cua so nao")
            return

        # CHỜ tới khi người dùng đóng HẾT cửa sổ (không auto-close). Poll 1s: context nào không còn
        # page (đã đóng) thì bỏ; hết context thì thoát -> giải phóng khóa profile cho lúc cào.
        while ctxs:
            time.sleep(1.0)
            con_lai = []
            for plat, ctx in ctxs:
                try:
                    if ctx.pages:            # còn tab mở = cửa sổ còn sống
                        con_lai.append((plat, ctx))
                    else:
                        try:
                            ctx.close()
                        except Exception:
                            pass
                except Exception:
                    pass                     # context đã chết (user đóng) -> bỏ
            ctxs = con_lai
        print("[mo_luot] da dong het cua so luot")


if __name__ == "__main__":
    main()
