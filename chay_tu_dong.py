# -*- coding: utf-8 -*-
"""
Bộ chạy NỀN cho tác vụ hẹn giờ — được Windows Task Scheduler gọi mỗi ngày.
Đọc cấu hình từ lich_config.json rồi chạy crawler ở chế độ headless (không cần người canh).
Ghi nhật ký vào data/tu_dong.log
"""

import json
import os
import subprocess
import sys
from datetime import datetime

THU_MUC_GOC = os.path.dirname(os.path.abspath(__file__))
THU_MUC_CRAWLER = os.path.join(THU_MUC_GOC, "MediaCrawler")
# python cho subprocess = python ĐANG CHẠY (sys.executable). Từ v0.1.20 venv ở userData/runtime/venv,
# KHÔNG còn ở MediaCrawler/.venv -> hardcode đường dẫn cũ gây WinError 2 (mọi subprocess hỏng).
PYTHON_VENV = sys.executable or os.path.join(THU_MUC_CRAWLER, ".venv", "Scripts", "python.exe")
if os.path.basename(PYTHON_VENV).lower() == "pythonw.exe":
    _p = os.path.join(os.path.dirname(PYTHON_VENV), "python.exe")
    PYTHON_VENV = _p if os.path.exists(_p) else PYTHON_VENV
# config ở userData (khớp web_app._SETTINGS_DIR): app-src read-only. Fallback app-src nếu thiếu env/chưa di cư.
_cfg_dir = (os.environ.get("KHACH_DB_DIR") or os.environ.get("LIC_CACHE_DIR") or "").strip() or THU_MUC_GOC
FILE_CAU_HINH = os.path.join(_cfg_dir, "lich_config.json")
if not os.path.isfile(FILE_CAU_HINH):
    _old = os.path.join(THU_MUC_GOC, "lich_config.json")
    if os.path.isfile(_old):
        FILE_CAU_HINH = _old
# Task Scheduler chạy STANDALONE (không kế thừa env web_app) → tự giải quyết + SET env MC_DATA_DIR/
# VC_PROCESSED_DIR (data_dir suy userData qua %APPDATA% / app_settings 'data_root') để crawl con lưu
# video NGOÀI app-src → BỀN qua update. Không có (dev) = chỗ cũ MediaCrawler/data.
try:
    import data_dir as _dd
    _DATA_DIR = _dd.lay_data_dir()[0]
except Exception:
    _DATA_DIR = os.path.join(THU_MUC_CRAWLER, "data")
FILE_LOG = os.path.join(_DATA_DIR, "tu_dong.log")


def ghi_log(dong: str):
    os.makedirs(os.path.dirname(FILE_LOG), exist_ok=True)
    with open(FILE_LOG, "a", encoding="utf-8") as f:
        f.write(dong + "\n")


def dong_chromium_sot():
    """Đóng Chromium của tool còn sót (khóa hồ sơ) trước khi chạy."""
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Process chrome -ErrorAction SilentlyContinue | "
             "Where-Object { $_.Path -like '*ms-playwright*' } | Stop-Process -Force"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            capture_output=True, timeout=20)
    except Exception:
        pass


def main():
    moc = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if os.path.exists(os.path.join(THU_MUC_GOC, "tam_dung_cao.flag")):
        ghi_log(f"[{moc}] TẠM DỪNG: ổ cứng đầy (tam_dung_cao.flag). Bỏ qua lượt này.")
        return 0
    if not os.path.exists(FILE_CAU_HINH):
        ghi_log(f"[{moc}] LỖI: chưa có lich_config.json — hãy mở tool và lưu tác vụ hẹn giờ.")
        return 1

    with open(FILE_CAU_HINH, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    platform = cfg.get("platform", "dy")
    che_do = cfg.get("type", "search")
    noi_dung = cfg.get("input", "").strip()
    so = str(cfg.get("count", "10"))

    if not noi_dung:
        ghi_log(f"[{moc}] LỖI: cấu hình chưa có từ khóa/link/kênh.")
        return 1

    # YouTube / TikTok -> dùng yt-dlp (module riêng)
    from nen_tang_helper import NEN_TANG_YTDLP
    if platform in NEN_TANG_YTDLP:
        lenh = [PYTHON_VENV, "tai_ytdlp.py", "--platform", platform,
                "--type", che_do, "--input", noi_dung, "--count", so]
        ghi_log(f"\n[{moc}] ▶ Bắt đầu tác vụ tự động (yt-dlp): {platform} / {che_do} / '{noi_dung[:50]}'")
        dong_chromium_sot()
        try:
            kq = subprocess.run(lenh, cwd=THU_MUC_GOC, capture_output=True,
                                text=True, encoding="utf-8", errors="replace")
            ghi_log((kq.stdout or "")[-3000:])
            ghi_log(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] ✔ Hoàn tất (mã {kq.returncode}).")
            return kq.returncode
        except Exception as e:
            ghi_log(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] LỖI: {e}")
            return 1

    lenh = [PYTHON_VENV, "main.py", "--platform", platform, "--lt", "qrcode",
            "--get_comment", "no", "--save_data_option", "jsonl",
            "--headless", "yes", "--type", che_do]

    env = os.environ.copy()
    if che_do == "search":
        lenh += ["--keywords", noi_dung.replace("\n", ","), "--crawler_max_notes_count", so]
        env["DY_SORT_TYPE"] = str(cfg.get("sort", 0))
        env["DY_PUBLISH_TIME"] = str(cfg.get("publish_time", 0))
    elif che_do == "detail":
        links = [l.strip() for l in noi_dung.splitlines() if l.strip()]
        lenh += ["--specified_id", ",".join(links)]
    else:  # creator
        lenh += ["--creator_id", noi_dung.splitlines()[0].strip(), "--crawler_max_notes_count", so]

    ghi_log(f"\n[{moc}] ▶ Bắt đầu tác vụ tự động: {platform} / {che_do} / '{noi_dung[:50]}'")
    dong_chromium_sot()
    try:
        kq = subprocess.run(lenh, cwd=THU_MUC_CRAWLER,
                            capture_output=True, text=True,
                            encoding="utf-8", errors="replace", env=env)
        ghi_log(kq.stdout[-3000:] if kq.stdout else "")
        if kq.returncode == 0:
            ghi_log(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] ✔ Hoàn tất.")
        else:
            ghi_log(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] ■ Kết thúc mã {kq.returncode} "
                    f"(có thể do phiên đăng nhập hết hạn — hãy mở tool quét QR lại).")
        return kq.returncode
    except Exception as e:
        ghi_log(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] LỖI: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
