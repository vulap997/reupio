# -*- coding: utf-8 -*-
"""
Bộ THEO DÕI KÊNH — Windows Task Scheduler gọi định kỳ (vd mỗi 30 phút).
Đọc theo_doi_config.json (danh sách kênh), kiểm tra từng kênh, tải video MỚI (bỏ qua video đã có).
Ghi nhật ký vào MediaCrawler/data/theo_doi.log
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
# config ở userData (khớp web_app._SETTINGS_DIR = KHACH_DB_DIR | LIC_CACHE_DIR | app-src): app-src read-only.
_cfg_dir = (os.environ.get("KHACH_DB_DIR") or os.environ.get("LIC_CACHE_DIR") or "").strip() or THU_MUC_GOC
FILE_CAU_HINH = os.path.join(_cfg_dir, "theo_doi_config.json")
if not os.path.isfile(FILE_CAU_HINH):   # fallback: chưa di cư / env thiếu → đọc bản app-src cũ
    _old_cfg = os.path.join(THU_MUC_GOC, "theo_doi_config.json")
    if os.path.isfile(_old_cfg):
        FILE_CAU_HINH = _old_cfg
# Task Scheduler chạy STANDALONE → tự giải quyết + SET env MC_DATA_DIR/VC_PROCESSED_DIR (data_dir suy
# userData) để crawl con + video_moi lưu NGOÀI app-src → BỀN qua update. Không có (dev) = chỗ cũ.
try:
    import data_dir as _dd
    _DATA_DIR = _dd.lay_data_dir()[0]
except Exception:
    _DATA_DIR = os.path.join(THU_MUC_CRAWLER, "data")
FILE_LOG = os.path.join(_DATA_DIR, "theo_doi.log")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def ghi_log(dong: str):
    os.makedirs(os.path.dirname(FILE_LOG), exist_ok=True)
    with open(FILE_LOG, "a", encoding="utf-8") as f:
        f.write(dong + "\n")


def dong_chromium_sot():
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Process chrome -ErrorAction SilentlyContinue | "
             "Where-Object { $_.Path -like '*ms-playwright*' } | Stop-Process -Force"],
            creationflags=_NO_WINDOW, capture_output=True, timeout=20)
    except Exception:
        pass


def main():
    moc = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if os.path.exists(os.path.join(THU_MUC_GOC, "tam_dung_cao.flag")):
        ghi_log(f"[{moc}] TẠM DỪNG: ổ cứng đầy (tam_dung_cao.flag). Bỏ qua lượt này.")
        return 0
    if not os.path.exists(FILE_CAU_HINH):
        ghi_log(f"[{moc}] LỖI: chưa có theo_doi_config.json")
        return 1

    with open(FILE_CAU_HINH, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    kenh_list = []
    for c in cfg.get("creators", []):
        link = c if isinstance(c, str) else (c.get("link") if isinstance(c, dict) else "")
        if link and link.strip():
            kenh_list.append(link.strip())
    so = str(cfg.get("count", "10"))
    if not kenh_list:
        ghi_log(f"[{moc}] Chưa có kênh nào để theo dõi.")
        return 0

    ghi_log(f"\n[{moc}] ▶ Kiểm tra {len(kenh_list)} kênh (mỗi kênh lấy tối đa {so} video gần nhất)...")
    dong_chromium_sot()

    from nen_tang_helper import doan_nen_tang, lenh_creator, NEN_TANG_YTDLP
    for kenh in kenh_list:
        nt = doan_nen_tang(kenh)
        lenh, cwd = lenh_creator(nt, kenh, so)
        try:
            kq = subprocess.run(lenh, cwd=cwd, capture_output=True,
                                text=True, encoding="utf-8", errors="replace")
            out = (kq.stdout or "") + (kq.stderr or "")
            if nt in NEN_TANG_YTDLP:        # yt-dlp in "YTDLP_DONE N"
                so_moi = next((int(d.split()[-1]) for d in out.splitlines()
                               if d.startswith("YTDLP_DONE")), 0)
            else:
                so_moi = out.count("save video")
            ghi_log(f"[{datetime.now():%H:%M:%S}] [{nt}] {kenh[:55]} → tải mới: {so_moi} video")
        except Exception as e:
            ghi_log(f"[{datetime.now():%H:%M:%S}] LỖI kênh {kenh[:55]}: {e}")

    ghi_log(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] ✔ Xong lượt kiểm tra.")
    try:
        import video_moi
        n_link = video_moi.tao_links()
        if n_link:
            ghi_log(f"[{datetime.now():%H:%M:%S}] 📁 Tách {n_link} video mới → video_moi_theo_kenh/")
    except Exception as e:
        ghi_log(f"[{datetime.now():%H:%M:%S}] ⚠ Lỗi tách video mới theo kênh: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
