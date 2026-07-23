# -*- coding: utf-8 -*-
"""Giải quyết thư mục lưu DATA (video cào/ảnh/jsonl) + VIDEO ĐÃ RENDER — BỀN qua auto-update.

Vì sao cần: NSIS update XÓA SẠCH app-src mỗi lần cập nhật → video cào trong MediaCrawler/data +
processed_videos (đều ở app-src) MẤT HẾT. Module này gom 1 gốc DUY NHẤT ngoài app-src để mọi
entrypoint (web_app, chay_tu_dong, theo_doi, tai_ytdlp, xu_ly_video, gom_dang_bai, doi_ten_kenh,
video_moi, tim_anh...) dùng CHUNG + set env MC_DATA_DIR / VC_PROCESSED_DIR cho subprocess con.

Ưu tiên: ENV MC_DATA_DIR (test/đã set sẵn) > user CHỌN (app_settings 'data_root') > userData
(bản đóng gói) > thư mục app (DEV → giữ chỗ cũ, KHÔNG phá luồng dev).
"""
import os
import json
import shutil

_HERE = os.path.dirname(os.path.abspath(__file__))
_CRAWLER = os.path.join(_HERE, "MediaCrawler")
DATA_CU = os.path.join(_CRAWLER, "data")            # chỗ cũ (dev / trước fix)
PROC_CU = os.path.join(_HERE, "processed_videos")   # chỗ cũ (dev / trước fix)
_APP_NAME = "lln-app"                     # tên userData của Electron (app.getPath('userData'))


def _user_data():
    """Thư mục userData (BỀN qua update). web_app/subprocess con: lấy từ env LIC_CACHE_DIR/KHACH_DB_DIR.
    Standalone (Task Scheduler chay_tu_dong/theo_doi — KHÔNG có env đó): suy từ %APPDATA%/<app>."""
    for k in ("LIC_CACHE_DIR", "KHACH_DB_DIR"):
        v = (os.environ.get(k) or "").strip()
        if v:
            return v
    # Standalone packaged (Task Scheduler chạy chay_tu_dong/theo_doi — không có env trên): suy userData
    # từ %APPDATA%/<app>. CHỈ khi đang chạy từ bản ĐÓNG GÓI (đường dẫn chứa 'app-src') để DEV (chạy từ
    # repo, không có 'app-src') GIỮ NGUYÊN chỗ cũ — KHÔNG phá luồng dev.
    if "app-src" in _HERE.replace("/", os.sep).lower():
        ap = os.environ.get("APPDATA")
        if ap:
            cand = os.path.join(ap, _APP_NAME)
            if os.path.isdir(cand):
                return cand
    return ""


def _settings_root():
    """data_root user đã chọn (app_settings.json ở userData). '' nếu chưa chọn."""
    d = _user_data() or _HERE
    try:
        with open(os.path.join(d, "app_settings.json"), encoding="utf-8") as f:
            return (json.load(f).get("data_root") or "").strip()
    except Exception:
        return ""


def _di_cu_1lan(cu, moi):
    """Di cư 1 LẦN data cũ → mới nếu mới còn RỖNG (an toàn, không ghi đè)."""
    try:
        if os.path.abspath(cu) != os.path.abspath(moi) and os.path.isdir(cu) and os.listdir(cu) \
                and (not os.path.isdir(moi) or not os.listdir(moi)):
            shutil.copytree(cu, moi, dirs_exist_ok=True)
    except Exception:
        pass


def giai_quyet():
    """Trả (DATA_DIR, PROCESSED_DIR) — KHÔNG set env, KHÔNG tạo thư mục (cho nơi chỉ cần biết)."""
    env_dd = (os.environ.get("MC_DATA_DIR") or "").strip()
    if env_dd:
        pr = (os.environ.get("VC_PROCESSED_DIR") or "").strip() \
            or os.path.join(os.path.dirname(env_dd.rstrip("/\\")) or env_dd, "processed_videos")
        return env_dd, pr
    root = _settings_root()
    if root and os.path.isdir(root):                 # user đã chọn 1 thư mục có thật
        return os.path.join(root, "data"), os.path.join(root, "processed_videos")
    ud = _user_data()
    if ud:                                           # bản đóng gói = userData
        return os.path.join(ud, "data"), os.path.join(ud, "processed_videos")
    return DATA_CU, PROC_CU                          # dev: giữ chỗ cũ (không phá luồng dev)


def lay_data_dir(di_cu=True):
    """Giải quyết + set env MC_DATA_DIR/VC_PROCESSED_DIR + tạo thư mục (+ di cư 1 lần). Trả (DATA_DIR, PROCESSED_DIR)."""
    dd, pr = giai_quyet()
    os.environ["MC_DATA_DIR"] = dd
    os.environ["VC_PROCESSED_DIR"] = pr
    try:
        os.makedirs(dd, exist_ok=True)
        os.makedirs(pr, exist_ok=True)
        if di_cu:
            _di_cu_1lan(DATA_CU, dd)
            _di_cu_1lan(PROC_CU, pr)
    except Exception:
        pass
    return dd, pr


def videos_cua(thu_muc, data_dir=None):
    """Thư mục videos của 1 nền tảng. thu_muc='data/<folder>' → <DATA_DIR>/<folder>/videos."""
    dd = data_dir or os.environ.get("MC_DATA_DIR") or giai_quyet()[0]
    sub = thu_muc.split("/", 1)[-1] if "/" in thu_muc else thu_muc
    return os.path.join(dd, sub.replace("/", os.sep), "videos")
