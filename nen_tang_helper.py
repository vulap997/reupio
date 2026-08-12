# -*- coding: utf-8 -*-
"""Tiện ích chung: đoán nền tảng từ link và dựng lệnh tải (MediaCrawler hoặc yt-dlp)."""
import os
import sys

THU_MUC_GOC = os.path.dirname(os.path.abspath(__file__))
THU_MUC_CRAWLER = os.path.join(THU_MUC_GOC, "MediaCrawler")
# python cho subprocess = python ĐANG CHẠY (sys.executable). Từ v0.1.20 venv ở userData/runtime/venv,
# KHÔNG còn ở MediaCrawler/.venv -> hardcode đường dẫn cũ gây WinError 2.
PYTHON_VENV = sys.executable or os.path.join(THU_MUC_CRAWLER, ".venv", "Scripts", "python.exe")
if os.path.basename(PYTHON_VENV).lower() == "pythonw.exe":
    _p = os.path.join(os.path.dirname(PYTHON_VENV), "python.exe")
    PYTHON_VENV = _p if os.path.exists(_p) else PYTHON_VENV

NEN_TANG_YTDLP = ("yt", "tt", "tw", "ig", "fb")

# Đoán nền tảng theo tên miền trong link
_DOAN = [
    ("tiktok.com", "tt"),
    ("douyin.com", "dy"), ("iesdouyin.com", "dy"),
    ("youtube.com", "yt"), ("youtu.be", "yt"),
    ("bilibili.com", "bili"), ("b23.tv", "bili"),
    ("xiaohongshu.com", "xhs"), ("xhslink.com", "xhs"),
    ("rednote.com", "rednote"),
    ("weibo.com", "wb"), ("weibo.cn", "wb"),
    ("kuaishou.com", "ks"),
    ("twitter.com", "tw"), ("x.com", "tw"),
    ("instagram.com", "ig"),
    ("facebook.com", "fb"), ("fb.com", "fb"), ("fb.watch", "fb"),
]


def doan_nen_tang(url, mac_dinh="dy"):
    u = (url or "").lower()
    for dom, ma in _DOAN:
        if dom in u:
            return ma
    return mac_dinh


def lenh_creator(platform, link, so):
    """Lệnh + thư mục chạy để tải MỚI theo kênh (yt-dlp tự bỏ video đã có nhờ archive)."""
    if platform in NEN_TANG_YTDLP:
        return ([PYTHON_VENV, "tai_ytdlp.py", "--platform", platform,
                 "--type", "creator", "--input", link, "--count", str(so)], THU_MUC_GOC)
    mc_platform = "xhs" if platform == "rednote" else platform
    return ([PYTHON_VENV, "main.py", "--platform", mc_platform, "--lt", "qrcode",
             "--get_comment", "no", "--save_data_option", "jsonl",
             "--headless", "yes", "--type", "creator",
             "--creator_id", link, "--crawler_max_notes_count", str(so)], THU_MUC_CRAWLER)
