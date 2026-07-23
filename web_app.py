# -*- coding: utf-8 -*-
"""
Giao diện WEB cho ViralCrawl (dashboard giống mockup).
Server Python thuần (thư viện chuẩn) phục vụ trang web + API gọi về backend đã có.
Chạy: MediaCrawler\.venv\Scripts\python.exe web_app.py  (hoặc WEB-UI.bat)
"""

import base64
import hmac
import json
import os
import queue
import re as _re          # module-level: khối _AN_MODEL_PAT/_AN_HOST_PAT (~614) dùng _re TRƯỚC import cũ ở ~692
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import bao_mat_key
import cache_artifact
import khach_db as kdb
import ngon_ngu as ngngu
import thong_tin_may

_START_TIME = time.time()

THU_MUC_GOC = os.path.dirname(os.path.abspath(__file__))
THU_MUC_CRAWLER = os.path.join(THU_MUC_GOC, "MediaCrawler")
# PYTHON cho subprocess (cào/dub/funasr/login...) = CHÍNH python đang chạy web_app (sys.executable).
# Từ v0.1.20 venv dời sang userData/runtime/venv -> KHÔNG còn ở MediaCrawler/.venv. Hardcode đường dẫn cũ
# làm mọi subprocess "WinError 2: file not found" (cào/đăng nhập/funasr đều hỏng). sys.executable luôn
# trỏ đúng venv hiện hành. App chạy bằng pythonw.exe -> đổi sang python.exe để bắt stdout sạch.
def _python_subproc():
    # ƯU TIÊN python.exe TRONG venv (sys.prefix/Scripts) — venv có ĐỦ thư viện (faster_whisper/rapidocr...).
    # LÝ DO: venv tạo bởi uv là launcher RE-EXEC sang uv-base python; sau re-exec sys.executable CÓ THỂ trỏ
    # uv-base (AppData/.../uv/python) THIẾU site-packages → render_worker spawn bằng đó sẽ ModuleNotFoundError
    # (OCR/whisper "thiếu thư viện" → báo nhầm 'lỗi nhận dạng giọng'). sys.prefix LUÔN = venv nên chắc chắn đúng.
    _venv_py = os.path.join(sys.prefix, "Scripts", "python.exe")
    if os.path.isfile(_venv_py):
        return _venv_py
    exe = sys.executable or os.path.join(THU_MUC_CRAWLER, ".venv", "Scripts", "python.exe")
    if os.path.basename(exe).lower() == "pythonw.exe":
        alt = os.path.join(os.path.dirname(exe), "python.exe")
        if os.path.exists(alt):
            return alt
    return exe
PYTHON_VENV = _python_subproc()
# Cookie/phiên đăng nhập nền tảng (dy/bili/xhs/wb...): ĐỂ Ở userData (BỀN qua update) thay vì thư mục
# cài (NSIS update xoá -> mất login, phải đăng nhập lại). Suy từ LIC_CACHE_DIR (=userData desktop truyền,
# như fix lic_cache) rồi đặt MC_BROWSER_DATA_DIR cho MỌI subprocess con dùng chung (mo_dang_nhap.py /
# kiem_tra_login.py / MediaCrawler cores đọc env này). Dev (không có env) = chỗ cũ trong MediaCrawler/.
_BD_OLD = os.path.join(THU_MUC_CRAWLER, "browser_data")
_lic_dir = os.environ.get("LIC_CACHE_DIR")
BROWSER_DATA_DIR = os.environ.get("MC_BROWSER_DATA_DIR") or (
    os.path.join(_lic_dir, "browser_data") if _lic_dir else _BD_OLD)
os.environ["MC_BROWSER_DATA_DIR"] = BROWSER_DATA_DIR
try:
    os.makedirs(BROWSER_DATA_DIR, exist_ok=True)
    # Di cư 1 LẦN phiên đăng nhập cũ (thư mục cài) -> userData để KHÔNG mất login ngay lần update này
    if os.path.abspath(BROWSER_DATA_DIR) != os.path.abspath(_BD_OLD) and os.path.isdir(_BD_OLD) \
            and not os.listdir(BROWSER_DATA_DIR):
        shutil.copytree(_BD_OLD, BROWSER_DATA_DIR, dirs_exist_ok=True)
except Exception:
    pass

# Cài đặt nhỏ của app (vd cờ "Xiaohongshu quốc tế" rednote.com) — LƯU ở userData (BỀN qua update),
# rồi set vào os.environ để MỌI subprocess (crawl/preview/login/check + MediaCrawler config) tự thừa
# kế qua MC_XHS_INTL (giống cơ chế MC_BROWSER_DATA_DIR). Mặc định tắt = bản Trung (giữ hành vi cũ).
_SETTINGS_DIR = os.environ.get("KHACH_DB_DIR") or _lic_dir or THU_MUC_GOC
_SETTINGS_FILE = os.path.join(_SETTINGS_DIR, "app_settings.json")

def _doc_settings():
    try:
        with open(_SETTINGS_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}

def _luu_settings(d):
    try:
        os.makedirs(_SETTINGS_DIR, exist_ok=True)
        with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def _pl_safe_ten(n):
    """Tên thể loại (user gõ) -> tên folder an toàn: bỏ ký tự cấm Windows + path traversal, rút gọn."""
    import re as _re
    n = _re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", str(n or "")).strip().strip(".")
    n = _re.sub(r"\s+", " ", n).strip()
    return n[:60]


def _pl_folders(s=None):
    """Cấu hình phân loại -> (muc[{ten,path}], default_path). Mỗi thể loại = đường dẫn ĐẦY ĐỦ TỰ DO
    (user toàn quyền đặt video ở đâu cũng được). Tương thích ngược config cũ (base + names) nếu chưa có
    'phan_loai_muc'. Chưa cấu hình -> ([], '')."""
    s = s if s is not None else _doc_settings()
    muc, seen = [], set()
    raw = s.get("phan_loai_muc")
    if isinstance(raw, list) and raw:
        for m in raw:
            if not isinstance(m, dict):
                continue
            ten = _pl_safe_ten(m.get("ten") or "")
            path = (m.get("path") or "").strip()
            if _can_lohapage() and isinstance(m.get("dich"), dict):
                lp, _ = _pl_resolve_dich(m["dich"])   # thể loại gán trang/nhóm LohaPage → folder LohaPage
                if lp:
                    path = lp
            if not path and ten:
                path = os.path.join(_pl_base(), ten)   # chỉ có tên (folder thường) → folder con dưới base
            if ten and path and ten.lower() not in seen:
                muc.append({"ten": ten, "path": path}); seen.add(ten.lower())
        return muc, (s.get("phan_loai_default_path") or "").strip()
    # Tương thích ngược: cấu hình CŨ base(folder cha) + names -> <base>\<tên>
    base = (s.get("phan_loai_base") or "").strip()
    if not base:
        return [], (s.get("phan_loai_default_path") or "").strip()
    for n in (s.get("phan_loai_names") or []):
        t = _pl_safe_ten(n)
        if t and t.lower() not in seen:
            muc.append({"ten": t, "path": os.path.join(base, t)}); seen.add(t.lower())
    dn = _pl_safe_ten(s.get("phan_loai_default_name") or "")
    return muc, (os.path.join(base, dn) if dn else "")


def _pl_base():
    """Folder GỐC chứa mọi thể loại phân loại = <processed_videos>/phân loại. Khách CHỈ gõ TÊN thể loại,
    hệ tự tạo folder con <base>/<tên> (khỏi nhập đường dẫn từng thể loại). Thể loại MỚI do AI đặt cũng vào đây."""
    return os.path.join(PROCESSED_DIR, "phân loại")


def _pl_loha_dir():
    """Thư mục uploads LohaPage DÙNG CHUNG (đọc từ kenh_nguon store — 1 nguồn với Kênh nguồn)."""
    try:
        import kenh_nguon
        return (kenh_nguon.doc().get("loha_uploads_dir") or "").strip()
    except Exception:
        return ""


def _pl_resolve_dich(dich):
    """Thể loại gán ĐÍCH LohaPage (page/group) → (folder_path, hashtag). Reuse gom_dang_bai.folder_loha để
    ĐỒNG BỘ contract folder với Kênh nguồn (<loha>/<Tên>_<page_id> hoặc <loha>/__group_<slug>). Thiếu thư
    mục LohaPage / cấu hình chưa đủ → (None, '')."""
    if not isinstance(dich, dict):
        return None, ""
    loha = _pl_loha_dir()
    if not loha:
        return None, ""
    hashtag = (dich.get("hashtag") or "").strip()
    if dich.get("kieu") == "group":
        slug = (dich.get("group_slug") or "").strip()
        return (os.path.join(loha, "__group_" + slug), hashtag) if slug else (None, "")
    pid = (dich.get("page_id") or "").strip()
    if not pid or len(pid) < 5:                 # LohaPage yêu cầu page_id ≥5 ký tự
        return None, ""
    try:
        import gom_dang_bai
        return gom_dang_bai.folder_loha(loha, dich.get("page_ten") or "page", pid), hashtag
    except Exception:
        return os.path.join(loha, (dich.get("page_ten") or "page") + "_" + pid), hashtag


def _pl_hashtag_theo_folder(dest):
    """Hashtag (list) cấu hình cho folder LohaPage `dest` — khớp thể loại có dich resolve == dest. Cho sidecar caption."""
    try:
        for m in (_doc_settings().get("phan_loai_muc") or []):
            if not isinstance(m, dict):
                continue
            lp, ht = _pl_resolve_dich(m.get("dich"))
            if lp and ht and os.path.abspath(lp) == os.path.abspath(dest):
                return [h for h in ht.replace(",", " ").split() if h]   # tách theo dấu cách/phẩy (khỏi phụ thuộc re)
    except Exception:
        pass
    return []


# XHS nội-địa vs quốc-tế: KHÔNG còn toggle global — đã tách thành 2 NỀN TẢNG riêng (xhs / rednote).
# MC_XHS_INTL/MC_XHS_PROFILE/MC_XHS_LEAF được set PER-CRAWL theo platform qua _ap_alias_env (xem _xhs_alias).
# Cắt treo cào Xiaohongshu: feed/detail endpoint hay bị anti-bot → request treo hết 60s × retry lồng
# (get_note_by_id_from_html 3x × request 3x) → tới ~12 phút/note. Hạ timeout xhs xuống 25s → ~4-5 phút/note,
# kèm watchdog báo sớm. Cho phép env phủ (dev). Chỉ áp cho xhs (MediaCrawler đọc env này riêng).
os.environ.setdefault("MC_XHS_TIMEOUT", "25")

# ───────────── Thư mục LƯU DATA (video cào + ảnh + jsonl) & VIDEO ĐÃ RENDER ─────────────
# PHẢI ở NGOÀI app-src: mỗi lần auto-update NSIS xoá sạch app-src → mất hết video đã cào (bug
# persistence, giống venv/lic_cache/khách-DB). User có thể TỰ CHỌN thư mục (vd ổ D:) ở tab Cài đặt
# (lưu key 'data_root' trong app_settings.json — BỀN qua update). Mặc định = userData (bản đóng gói),
# = thư mục app (dev → GIỮ NGUYÊN hành vi cũ, không phá luồng dev). Set MC_DATA_DIR + VC_PROCESSED_DIR
# cho MỌI subprocess (MediaCrawler base_config.SAVE_DATA_PATH, tai_ytdlp, render xu_ly_video) dùng CHUNG.
import data_dir as _dd
DATA_DIR, PROCESSED_DIR = _dd.lay_data_dir()   # giải quyết + set env MC_DATA_DIR/VC_PROCESSED_DIR + di cư 1 lần

def _videos_cua(thu_muc):
    """Thư mục videos của 1 nền tảng dưới DATA_DIR. thu_muc='data/<folder>' → DATA_DIR/<folder>/videos."""
    return _dd.videos_cua(thu_muc, DATA_DIR)

def _rel_goc(full):
    """Đường dẫn tương đối (theo THU_MUC_GOC) để gửi UI. KHÁC Ổ ĐĨA (data/output ở D: còn app ở C:)
    → os.path.relpath ném ValueError ('path is on mount D:, start on mount C:') → dùng path TUYỆT ĐỐI
    (os.path.join(GOC, abs)=abs nên _resolve_video vẫn giải đúng). Tránh crash khi user chọn ổ khác (v1.0.7)."""
    try:
        return os.path.relpath(full, THU_MUC_GOC).replace("\\", "/")
    except ValueError:
        return os.path.abspath(full).replace("\\", "/")

def _merge_move(s, d, dem):
    """Move nội dung thư mục s → d (gộp nếu trùng thư mục con, giữ bản đích nếu trùng file)."""
    for ten in os.listdir(s):
        ss, dd = os.path.join(s, ten), os.path.join(d, ten)
        try:
            if os.path.exists(dd):
                if os.path.isdir(ss) and os.path.isdir(dd):
                    _merge_move(ss, dd, dem)
                continue
            shutil.move(ss, dd); dem[0] += 1
        except Exception:
            dem[1] += 1

def _doi_thu_muc_data(new_root):
    """User đổi thư mục lưu: validate ghi được + MOVE data hiện tại sang nơi mới + lưu settings +
    cập nhật globals/env + _THU_MUC_PHAT. Áp cho tác vụ MỚI (tác vụ đang chạy không đổi). Trả dict."""
    global DATA_DIR, PROCESSED_DIR, _THU_MUC_PHAT
    new_root = (new_root or "").strip().rstrip("/\\")
    if not new_root:
        return {"ok": False, "msg": "Chưa chọn thư mục."}
    try:
        os.makedirs(new_root, exist_ok=True)
        _t = os.path.join(new_root, ".vc_ghi_thu")
        with open(_t, "w") as f:
            f.write("ok")
        os.remove(_t)
    except Exception as e:
        return {"ok": False, "msg": "Thư mục không ghi được: " + str(e)[:120]}
    new_data = os.path.join(new_root, "data")
    new_proc = os.path.join(new_root, "processed_videos")
    if os.path.abspath(new_data) == os.path.abspath(DATA_DIR):
        return {"ok": True, "msg": "Đã ở thư mục này rồi.", "root": new_root,
                "data_dir": DATA_DIR, "processed_dir": PROCESSED_DIR, "da_chuyen": 0, "loi": 0}
    os.makedirs(new_data, exist_ok=True)
    os.makedirs(new_proc, exist_ok=True)
    dem = [0, 0]   # [đã chuyển, lỗi]
    if os.path.isdir(DATA_DIR):
        _merge_move(DATA_DIR, new_data, dem)
    if os.path.isdir(PROCESSED_DIR):
        _merge_move(PROCESSED_DIR, new_proc, dem)
    s = _doc_settings(); s["data_root"] = new_root; _luu_settings(s)
    _old_data_dir, _old_proc_dir = DATA_DIR, PROCESSED_DIR   # giữ để remap path tuyệt đối trong hàng đợi
    DATA_DIR, PROCESSED_DIR = new_data, new_proc
    os.environ["MC_DATA_DIR"] = DATA_DIR
    os.environ["VC_PROCESSED_DIR"] = PROCESSED_DIR
    _THU_MUC_PHAT = [PROCESSED_DIR] + [_videos_cua(i["thu_muc"]) for i in NEN_TANG.values()]
    try:
        _queue_remap_paths(_old_data_dir, new_data, _old_proc_dir, new_proc)   # video đã move → sửa path trong _queue (khỏi 'loi' oan khi khôi phục)
    except Exception:
        pass
    return {"ok": True, "root": new_root, "data_dir": DATA_DIR, "processed_dir": PROCESSED_DIR,
            "da_chuyen": dem[0], "loi": dem[1]}

WEB_DIR = os.path.join(THU_MUC_GOC, "web")
GIONG_DIR = os.path.join(THU_MUC_GOC, "giong_mau")          # giọng built-in nu.wav/nam.wav (app-src, stage lại)
_CLONE_OLD = os.path.join(GIONG_DIR, "upload")              # CŨ: app-src → NSIS update XOÁ → mất giọng clone khách
# Giọng CLONE khách tải lên = DỮ LIỆU NGƯỜI DÙNG (tích lũy hàng tháng, khách kỳ vọng tồn tại mãi) → PHẢI ở
# userData (BỀN qua update), giống browser_data/data/lic_cache. Suy từ LIC_CACHE_DIR (=userData desktop truyền).
# Dev (không có env) = chỗ cũ trong app → GIỮ NGUYÊN hành vi dev.
CLONE_DIR = os.path.join(_lic_dir, "clone_voices") if _lic_dir else _CLONE_OLD
try:
    os.makedirs(CLONE_DIR, exist_ok=True)
    # Di cư 1 LẦN giọng clone cũ (app-src/giong_mau/upload) → userData/clone_voices (khỏi mất ngay lần update này).
    if os.path.abspath(CLONE_DIR) != os.path.abspath(_CLONE_OLD) and os.path.isdir(_CLONE_OLD) \
            and not os.listdir(CLONE_DIR):
        shutil.copytree(_CLONE_OLD, CLONE_DIR, dirs_exist_ok=True)
except Exception:
    pass
# Logo/watermark ẢNH user tải lên = DỮ LIỆU NGƯỜI DÙNG → userData (BỀN qua update + app-src=Program Files
# READ-ONLY khi đóng gói nên KHÔNG ghi được → upload_logo fail). Dev (không env) = chỗ cũ app-src. Di cư 1 lần.
_LOGOS_OLD = os.path.join(THU_MUC_GOC, "user_logos")
LOGOS_DIR = os.path.join(_lic_dir, "user_logos") if _lic_dir else _LOGOS_OLD
try:
    os.makedirs(LOGOS_DIR, exist_ok=True)
    if os.path.abspath(LOGOS_DIR) != os.path.abspath(_LOGOS_OLD) and os.path.isdir(_LOGOS_OLD) \
            and not os.listdir(LOGOS_DIR):
        shutil.copytree(_LOGOS_OLD, LOGOS_DIR, dirs_exist_ok=True)
except Exception:
    pass
# Preview 5s = output TẠM → cũng phải GHI ĐƯỢC (app-src read-only). userData/_preview (else app-src dev).
PREVIEW_DIR = os.path.join(_lic_dir, "_preview") if _lic_dir else os.path.join(THU_MUC_GOC, "_preview")
try:
    os.makedirs(PREVIEW_DIR, exist_ok=True)
except Exception:
    pass
PORT = int(os.environ.get("VC_PORT") or 8770)   # override để chạy nhiều instance / test (env vắng = 8770 như cũ)
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# EMBEDDED: app Electron đã xác thực qua license + gắn máy -> tool KHÔNG cần đăng nhập lần 2.
# Standalone (CAO-VIDEO.bat) không đặt VC_EMBEDDED -> giữ cổng đăng nhập khach_db như cũ.
EMBEDDED = os.environ.get("VC_EMBEDDED") == "1"
OWNER = os.environ.get("VC_USER") or "owner"
# Nonce do app Electron sinh & truyền (env + URL hash). Chỉ renderer THẬT mới biết -> chống
# CSRF/web độc hại tự gọi bootstrap để mint phiên. Rỗng = chế độ standalone (giữ hành vi cũ).
BOOTSTRAP_NONCE = os.environ.get("VC_BOOTSTRAP_NONCE") or ""
# CSRF token cho MỌI POST/PUT/DELETE đổi state (H1). Embedded: tái dùng BOOTSTRAP_NONCE (renderer đã biết
# qua #k=). Standalone: sinh ngẫu nhiên, frontend lấy qua /api/auth/bootstrap response. Chỉ same-origin
# (server bind 127.0.0.1 + Host allowlist) đọc được token → blind-POST từ subprocess/curl không có token bị chặn.
import secrets
CSRF_NONCE = BOOTSTRAP_NONCE or secrets.token_hex(18)
# Chống DNS-rebinding (Host lạ) + CSRF (Origin khác site): chỉ chấp nhận loopback cùng-origin.
_ALLOW_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}", "127.0.0.1", "localhost"}
_ALLOW_ORIGINS = {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}

# ===== GÓI & GIỚI HẠN (free / pro / unlimited) — đọc từ VC_TIER (tier license đã ký) =====
TIER = "free"

# CHỐNG CRACK CR1: VC_TIER là ENV -> kẻ crack đặt VC_TIER=unlimited để mở khoá. Ràng: KHÔNG cho env nâng
# gói VƯỢT tier trong license_token ĐÃ KÝ Ed25519 (verify bằng public key nhúng — sửa payload = sai chữ ký).
# Chỉ HẠ (không nâng); không có token verify được (chưa bật ký / standalone / dev) -> tin env như cũ (không vỡ).
_SIGN_PUB_B64 = "xUufjsVcq6HbRgmD1q31gLCpDLo+6nACDLAySrlJs4Q="   # public key (khớp lic_client._SIGN_PUB_B64)
_TIER_RANK = {"expired": 0, "free": 1, "trai_nghiem": 2, "co_ban": 3, "pro": 4, "unlimited": 5}


def _tier_tu_token_ky():
    """Tier từ license_token đã KÝ trong lic_cache (verify Ed25519). None nếu không có/không verify được."""
    try:
        import json as _json, base64 as _b64m
        cdir = (os.environ.get("LIC_CACHE_DIR") or "").strip()
        if not cdir:
            return None
        with open(os.path.join(cdir, "lic_cache.json"), encoding="utf-8") as _f:
            tok = (_json.load(_f) or {}).get("license_token") or ""
        parts = tok.split(".")
        if len(parts) < 3:            # v1 (chưa ký ed) -> không verify được -> tin env
            return None
        raw = _b64m.urlsafe_b64decode(parts[0] + "=" * (-len(parts[0]) % 4))
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        pub = Ed25519PublicKey.from_public_bytes(_b64m.b64decode(_SIGN_PUB_B64))
        pub.verify(_b64m.urlsafe_b64decode(parts[2] + "=" * (-len(parts[2]) % 4)), raw)   # sai chữ ký -> raise
        pl = _json.loads(raw.decode("utf-8"))
        if pl.get("exp", 0) < int(time.time()):
            return None
        t = pl.get("tier", "free")
        te = pl.get("trial_exp") or 0
        if te and int(time.time()) > int(te):   # trial 7 ngày offline hết -> expired (khớp lic_client)
            t = "expired"
        return t if t in _TIER_RANK else None
    except Exception:
        return None


# TIER ban đầu: lấy từ token ký, fallback env VC_TIER, fallback free
def _khoi_tao_tier():
    env_t = (os.environ.get("VC_TIER") or "free").strip().lower()
    if env_t not in _TIER_RANK:
        env_t = "free"
    
    signed_t = _tier_tu_token_ky()
    if signed_t:
        # CHỐNG CRACK: Chỉ cho HẠ gói (ví dụ env_t là unlimited nhưng signed_t là free -> dùng free)
        if _TIER_RANK.get(env_t, 1) > _TIER_RANK.get(signed_t, 1):
            return signed_t
        return env_t
        
    return env_t

TIER = _khoi_tao_tier()

# LOHAPAGE_OK ban đầu: lấy từ token ký, fallback env VC_LOHAPAGE
def _khoi_tao_lohapage():
    try:
        import json as _json, base64 as _b64m
        cdir = (os.environ.get("LIC_CACHE_DIR") or "").strip()
        if cdir:
            with open(os.path.join(cdir, "lic_cache.json"), encoding="utf-8") as _f:
                tok = (_json.load(_f) or {}).get("license_token") or ""
            parts = tok.split(".")
            if len(parts) >= 3:
                raw = _b64m.urlsafe_b64decode(parts[0] + "=" * (-len(parts[0]) % 4))
                from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
                pub = Ed25519PublicKey.from_public_bytes(_b64m.b64decode(_SIGN_PUB_B64))
                pub.verify(_b64m.urlsafe_b64decode(parts[2] + "=" * (-len(parts[2]) % 4)), raw)
                pl = _json.loads(raw.decode("utf-8"))
                if pl.get("exp", 0) >= int(time.time()):
                    return bool(pl.get("lohapage"))
    except Exception:
        pass
        
    env_loha = (os.environ.get("VC_LOHAPAGE") or "").strip()
    return env_loha == "1"

LOHAPAGE_OK = _khoi_tao_lohapage()


def _can_lohapage():
    """Có quyền dùng LohaPage (Kênh nguồn + Đăng bài) không (cờ server ký, mặc định KHOÁ)."""
    return LOHAPAGE_OK


def _la_loha_path(path):
    """Endpoint có thuộc nhóm LohaPage (Kênh nguồn kn_* + Đăng bài) → cần gate quyền."""
    q = (path or "").split("?", 1)[0]
    return q.startswith("/api/kn_") or q in (
        "/api/loha_dir_chung", "/api/trang_get", "/api/trang_save", "/api/trang_gom")


def _loi_lohapage():
    return {"ok": False, "loi_quyen": True, "lohapage": False,
            "msg": "Tính năng này thuộc LohaPage — cần mua/mở khoá LohaPage để dùng Kênh nguồn & Đăng bài."}

LIMITS = {
    # FREE = dùng thử 7 ngày: cào 3/ngày, lồng tiếng 1 video ≤1 phút; băm/quy-trình/theo-dõi/AI KHOÁ.
    "free":      {"cao_ngay": 3,    "dub_ngay": 1,    "dub_phut_ngay": 1,
                  "clone_tong": 0,    "theodoi_max": 0,    "tro_ly_ai": False, "giong_nang_cao": False,
                  "bam": False, "workflow": False, "theodoi": False},
    # EXPIRED = hết 7 ngày dùng thử -> view-only, chặn MỌI thao tác (số 0 / bool False hết).
    "expired":   {"cao_ngay": 0,    "dub_ngay": 0,    "dub_phut_ngay": 0,
                  "clone_tong": 0,    "theodoi_max": 0,    "tro_ly_ai": False, "giong_nang_cao": False,
                  "bam": False, "workflow": False, "theodoi": False},
    
    # 1. GÓI TRẢI NGHIỆM (di sản - giữ nguyên độ tương thích)
    "trai_nghiem":{"cao_ngay": 50,   "dub_ngay": 5,    "dub_phut_ngay": 30,
                  "clone_tong": 1,    "theodoi_max": 1,    "tro_ly_ai": False, "giong_nang_cao": True,
                  "bam": True, "workflow": True, "theodoi": True},
                  
    # 2. GÓI CƠ BẢN (di sản - giữ nguyên độ tương thích)
    "co_ban":    {"cao_ngay": None, "dub_ngay": 15,   "dub_phut_ngay": 60,
                  "clone_tong": 3,    "theodoi_max": 3,    "tro_ly_ai": False, "giong_nang_cao": True,
                  "bam": True, "workflow": True, "theodoi": True},
                  
    # 3. GÓI THÁNG - CƠ BẢN (299k/tháng): cào không giới hạn, lồng tiếng tối đa 30 video/ngày (120 phút).
    "pro":       {"cao_ngay": None, "dub_ngay": 30,   "dub_phut_ngay": 120,
                  "clone_tong": 5,    "theodoi_max": 5,    "tro_ly_ai": False, "giong_nang_cao": True,
                  "bam": True, "workflow": True, "theodoi": True},
                  
    # 4. GÓI NĂM / VĨNH VIỄN - MỞ RỘNG (999k/năm hoặc 1.799k/vĩnh viễn): cào, lồng tiếng, clone và theo dõi không giới hạn + có Trợ lý AI.
    "unlimited": {"cao_ngay": None, "dub_ngay": None, "dub_phut_ngay": None,
                  "clone_tong": None, "theodoi_max": None, "tro_ly_ai": True,  "giong_nang_cao": True,
                  "bam": True, "workflow": True, "theodoi": True},
}


def _lim(khoa):
    return LIMITS.get(TIER, LIMITS["free"]).get(khoa)


def _block(loai, msg):
    """Trả payload báo chạm giới hạn (frontend hiện banner + nút Nâng cấp)."""
    return {"ok": False, "limit": True, "loai": loai, "tier": TIER, "msg": msg}


def _can(khoa, loai, msg):
    """Chokepoint tier: None nếu tier cho phép tính năng `khoa`; ngược lại _block(loai,msg).
    LIMITS: bool False = chặn (tro_ly_ai/giong_nang_cao); số 0 = chặn; None = không giới hạn (cho phép)."""
    v = _lim(khoa)
    if v is False or v == 0:
        return _block(loai, msg)
    return None


def _guard_expired(loai="expired"):
    """Chặn HẾT thao tác khi tier == 'expired' (hết 7 ngày dùng thử FREE). Trả _block | None.
    Gọi ở ĐẦU mọi POST thao tác (crawl/dub/bam/workflow/localize/xu_ly/td_on/ai). tier≠expired -> None (chạy như cũ)."""
    if TIER == "expired":
        return _block(loai, "Bản dùng thử FREE đã hết 7 ngày. Nâng cấp để tiếp tục thao tác.")
    return None


_tl_cache = {}          # (path, mtime, size) -> phút — cache ffprobe
_tl_cache_lock = threading.Lock()
_tl_probe_q = []        # path CHO probe NEN


def _thoi_luong_cache(full):
    """Thoi luong (phut) — CHI doc cache; CHUA co -> xep probe NEN, tra 0 (list KHONG cho ffprobe -> khong treo).
    Probe dong bo trong list = 228 video x (ffprobe + timeout 20s/video hong) -> treo tab 'File da tai' ca
    PHUT (da reproduce: /api/files 90s van rong). Worker nen probe dan -> lan list SAU co so. 0 = 'chua do'."""
    try:
        st = os.stat(full)
        key = (full, int(st.st_mtime), st.st_size)
    except OSError:
        return 0
    with _tl_cache_lock:
        v = _tl_cache.get(key)
        if v is not None:
            return v
        if full not in _tl_probe_q:
            _tl_probe_q.append(full)
    return 0


def _tl_probe_worker():
    """Nen: probe dan thoi luong video trong hang doi (1 luc 1) -> cache. List khong bao gio cho ffprobe."""
    while True:
        time.sleep(0.5)
        with _tl_cache_lock:
            full = _tl_probe_q.pop(0) if _tl_probe_q else None
        if not full:
            continue
        try:
            st = os.stat(full)
            key = (full, int(st.st_mtime), st.st_size)
        except OSError:
            continue
        with _tl_cache_lock:
            if key in _tl_cache:
                continue
        v = _video_phut(full)
        with _tl_cache_lock:
            if len(_tl_cache) > 5000:
                _tl_cache.clear()
            _tl_cache[key] = v


def _thoi_luong_phut(rel):
    """Thời lượng video (phút, làm tròn LÊN) qua ffprobe. Lỗi/không thấy -> 0."""
    try:
        import math
        rel = (rel or "").replace("\\", "/").lstrip("/")
        full = os.path.normpath(os.path.join(THU_MUC_GOC, rel))
        if not _trong_vung(full, THU_MUC_GOC) or not os.path.isfile(full):   # commonpath, chống prefix-collision
            return 0
        ffp = shutil.which("ffprobe") or "ffprobe"
        r = subprocess.run([ffp, "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=noprint_wrappers=1:nokey=1", full],
                           capture_output=True, text=True, creationflags=_NO_WINDOW, timeout=20)
        giay = float((r.stdout or "0").strip() or 0)
        return max(1, math.ceil(giay / 60.0)) if giay > 0 else 0
    except Exception:
        return 0


def _video_phut(full):
    """Thời lượng (phút, làm tròn LÊN) của video theo path TUYỆT ĐỐI (khác _thoi_luong_phut nhận path
    tương đối). Dùng cho hạn mức lồng tiếng ở đường render (path đã _resolve_video, có thể ổ khác)."""
    try:
        import math
        if not full or not os.path.isfile(full):
            return 0
        try:
            import xu_ly_video as _xlv
            ffp = _xlv.tim_exe("ffprobe") or shutil.which("ffprobe") or "ffprobe"
        except Exception:
            ffp = shutil.which("ffprobe") or "ffprobe"
        r = subprocess.run([ffp, "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=noprint_wrappers=1:nokey=1", full],
                           capture_output=True, text=True, creationflags=_NO_WINDOW, timeout=20)
        giay = float((r.stdout or "0").strip() or 0)
        return max(1, math.ceil(giay / 60.0)) if giay > 0 else 0
    except Exception:
        return 0


# ---- HẠN MỨC LỒNG TIẾNG dùng CHUNG mọi đường (tab Lồng tiếng + Render + Việt hóa + Quy trình) ----
# Trước đây quota dub_phut CHỈ chặn ở /api/dub/start → khách tick "Lồng tiếng" trong tab Render / Quy trình
# đi qua /api/xu_ly, /api/localize, /api/workflow_* → lồng tiếng KHÔNG giới hạn (bypass). Giờ mọi đường
# CHUNG 1 hạn mức: usage đã đếm (job xong) + job ĐANG chờ/chạy (tab Dub + hàng đợi render) chưa đếm.
_dub_phut_dang = 0   # phút của job lồng-tiếng tab-Dub ĐANG chạy (chưa đếm vào usage) — cộng vào cam kết


def _dub_da_cam_ket():
    """(số_video, số_phút) lồng tiếng ĐÃ cam kết hôm nay = usage đã đếm + job lồng-tiếng đang chờ/chạy
    trong hàng đợi render (opts có '_dub_phut') + job tab-Dub đang chạy (_dub_busy)."""
    n_dang = 1 if _dub_busy else 0
    p_dang = _dub_phut_dang if _dub_busy else 0
    try:
        with _queue_lock:
            for it in _queue:
                if it.get("trang_thai") in ("cho", "dang", "cho_srt") and (it.get("opts") or {}).get("_dub_phut"):
                    n_dang += 1
                    p_dang += int(it["opts"]["_dub_phut"])
    except Exception:
        pass
    return (kdb.usage_lay("dub") + n_dang, kdb.usage_lay("dub_phut") + p_dang)


def _dub_quota_loc(paths, long_tieng):
    """Lọc list video (path TUYỆT ĐỐI) theo hạn mức lồng tiếng/ngày khi long_tieng bật. GREEDY: nhận tới
    khi hết budget (số video VÀ số phút), phần vượt bị chặn. Trả (nhan=[(path, phut)...], bo_qua, msg).
    long_tieng False HOẶC tier ∞ (cả 2 hạn mức None) → nhận HẾT với phut=0 (không tính quota)."""
    ghn = _lim("dub_ngay"); ghp = _lim("dub_phut_ngay")
    if not long_tieng or (ghn is None and ghp is None):
        return [(p, 0) for p in paths], 0, ""
    da_n, da_p = _dub_da_cam_ket()
    con_n = (10 ** 9 if ghn is None else max(0, ghn - da_n))
    con_p = (10 ** 9 if ghp is None else max(0, ghp - da_p))
    # Cap CỨNG "mỗi video ≤ dub_phut_ngay phút" (free=1): loại thẳng video DÀI hơn cap trước greedy budget.
    # tier ∞ (ghp None) -> cap_video None -> bỏ qua. Áp mọi đường: localize/xu_ly/workflow.
    cap_video = ghp
    nhan, bo = [], 0
    for p in paths:
        phut = _video_phut(p) or 1   # ffprobe lỗi → fail-CLOSED tối thiểu 1 phút (đừng lọt hạn mức)
        if cap_video is not None and phut > cap_video:   # video vượt cap/video -> loại thẳng
            bo += 1; continue
        if con_n >= 1 and phut <= con_p:
            nhan.append((p, phut)); con_n -= 1; con_p -= phut
        else:
            bo += 1
    msg = ""
    if bo:
        msg = ("Đã đạt hạn mức lồng tiếng gói %s (mỗi video ≤%s phút · ≤%s phút · ≤%s video/ngày). Bỏ qua %d "
               "video vượt hạn — nâng cấp để lồng tiếng nhiều hơn." %
               (TIER.upper(), cap_video if cap_video is not None else "∞",
                ghp if ghp is not None else "∞", ghn if ghn is not None else "∞", bo))
    return nhan, bo, msg


def _refresh_tier():
    """'Làm mới gói': gọi lic_cli status (ONLINE re-check server) lấy tier mới -> cập nhật TIER (không cần khởi động lại).
    Trả nguồn lấy được: 'online' (đã đồng bộ server) | 'offline' (mạng lỗi, dùng cache) | None (không chạy được)."""
    global TIER, LOHAPAGE_OK
    try:
        exe_path = os.path.join(THU_MUC_GOC, "license_server", "lic_cli_bin", "lic_cli.exe")
        if os.path.isfile(exe_path):
            cmd = [exe_path, "status"]
        else:
            cmd = [PYTHON_VENV, os.path.join(THU_MUC_GOC, "license_server", "lic_cli.py"), "status"]
            
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        out, err = p.communicate(timeout=15)
        
        if p.returncode == 0:
            lines = out.strip().split("\n")
            status_line = lines[-1] if lines else ""
            res = json.loads(status_line)
            if res.get("ok"):
                TIER = res.get("tier", "free")
                LOHAPAGE_OK = bool(res.get("lohapage"))
                return res.get("source", "online")
    except Exception:
        pass
        
    try:
        t = _tier_tu_token_ky()
        if t:
            TIER = t
            cdir = (os.environ.get("LIC_CACHE_DIR") or "").strip()
            if cdir:
                with open(os.path.join(cdir, "lic_cache.json"), encoding="utf-8") as _f:
                    cache = json.load(_f) or {}
                    LOHAPAGE_OK = bool(cache.get("lohapage"))
            return "offline"
    except Exception:
        pass
        
    return None


def _goi_info():
    """Thông tin gói + giới hạn + đã dùng + còn lại cho frontend."""
    try:
        td = doc_json(FILE_TD, {"creators": []})
        n_td = len(td.get("creators") or [])
    except Exception:
        n_td = 0

    expires_at = 0
    try:
        cdir = (os.environ.get("LIC_CACHE_DIR") or "").strip()
        if cdir:
            lic_cache_path = os.path.join(cdir, "lic_cache.json")
            if os.path.isfile(lic_cache_path):
                with open(lic_cache_path, encoding="utf-8") as _f:
                    cache_d = json.load(_f) or {}
                tok = cache_d.get("license_token") or ""
                parts = tok.split(".")
                if len(parts) >= 3:
                    raw = base64.urlsafe_b64decode(parts[0] + "=" * (-len(parts[0]) % 4))
                    pl = json.loads(raw.decode("utf-8"))
                    expires_at = pl.get("lic_exp", 0)
                else:
                    expires_at = cache_d.get("info", {}).get("expires_at", 0)
    except Exception:
        pass

    return {"ok": True, "tier": TIER, "lohapage": _can_lohapage(), "expires_at": expires_at,
            "limits": LIMITS.get(TIER, LIMITS["free"]),
            "usage": {"cao": kdb.usage_lay("cao"), "dub": kdb.usage_lay("dub"),
                      "dub_phut": kdb.usage_lay("dub_phut"),
                      "clone": kdb.usage_lay("clone", theo_ngay=False), "theodoi": n_td}}

SAP_XEP = {"Liên quan": 0, "Nhiều like nhất (HOT)": 1, "Mới nhất": 2}
THOI_GIAN = {"Không giới hạn": 0, "Trong 1 ngày": 1, "Trong 1 tuần": 7, "Trong 6 tháng": 180}
SAP_XEP_KENH = {"Mới nhất": "newest", "Nhiều like nhất": "most_liked"}
NEN_TANG = {
    "dy": {"ten": "Douyin", "thu_muc": "data/douyin"},
    "bili": {"ten": "Bilibili", "thu_muc": "data/bili"},
    "xhs": {"ten": "Xiaohongshu", "thu_muc": "data/xhs"},
    "rednote": {"ten": "RedNote (quốc tế)", "thu_muc": "data/rednote"},
    "wb": {"ten": "Weibo (ảnh)", "thu_muc": "data/weibo"},
    "yt": {"ten": "YouTube", "thu_muc": "data/youtube"},
    "tt": {"ten": "TikTok", "thu_muc": "data/tiktok"},
    "tw": {"ten": "Twitter (X)", "thu_muc": "data/twitter"},
    "ig": {"ten": "Instagram", "thu_muc": "data/instagram"},
    "fb": {"ten": "Facebook", "thu_muc": "data/facebook"},
}
# Nền tảng dùng yt-dlp thay vì MediaCrawler
NEN_TANG_YTDLP = ("yt", "tt", "tw", "ig", "fb")
# Nền tảng ĐANG HỖ TRỢ (hiện trong dropdown Lịch sử cào...): chỉ 6 nền chạy ổn — bỏ Weibo/Twitter/Instagram.
NEN_TANG_HO_TRO = ("dy", "bili", "xhs", "rednote", "yt", "tt", "fb")


def _xhs_alias(platform):
    """XHS có 2 bản: 'xhs' = NỘI ĐỊA (xiaohongshu.com) · 'rednote' = QUỐC TẾ (rednote.com).
    Cùng crawler MediaCrawler '--platform xhs' nhưng KHÁC: domain (MC_XHS_INTL), profile trình duyệt
    (MC_XHS_PROFILE → tách phiên đăng nhập, hết lẫn cookie 2 domain), data (MC_XHS_LEAF → data/rednote riêng).
    Trả (mc_platform, intl, profile_dir, data_leaf). Nền khác → chính nó, intl='0'."""
    if platform == "rednote":
        return ("xhs", "1", "rednote_user_data_dir", "rednote")
    if platform == "xhs":
        return ("xhs", "0", "xhs_user_data_dir", "xhs")
    return (platform, "0", f"{platform}_user_data_dir", platform)


def _ap_alias_env(env, platform):
    """Nhét cờ XHS nội-địa/quốc-tế vào env subprocess theo platform (đồng bộ domain+profile+data).
    Dùng cho MỌI subprocess đụng XHS (crawl/preview/chụp/login). Trả mc_platform để thay vào --platform."""
    mc, intl, prof, leaf = _xhs_alias(platform)
    if platform in ("xhs", "rednote"):
        env["MC_XHS_INTL"] = intl
        env["MC_XHS_PROFILE"] = prof
        env["MC_XHS_LEAF"] = leaf
    return mc

# Trạng thái crawl toàn cục
_proc = None
_crawl_lock = threading.Lock()   # bịt race: giữ chỗ ĐỒNG BỘ giữa lúc chay_crawl trả ok và _crawl_worker gán _proc
_dang_cao = False                # True = đã giữ chỗ cào nhưng _crawl_worker chưa kịp gán _proc (bấm 2 lần nhanh)
_render_proc = None   # slot RIÊNG cho render (tách khỏi _proc của crawl → render chạy song song crawl)
_log_lines = []
_log_lock = threading.Lock()


# Log cho KHÁCH: ẨN HẾT dòng kỹ thuật/model + gột mọi tên engine/voice khỏi dòng giữ lại. Raw = LOG_RAW=1.
# ẨN cả dòng nếu chứa: debug, lỗi nội bộ, NẠP/TẢI model, tên model thuần kỹ thuật.
_LOG_AN = ("[funasr]", "[dll]", "traceback", "tai/nap", "nap model", "nạp model", "tải model",
           "lần đầu tải", "⬇", "rtf ", "compute ", "onnxruntime", "nvidia", "cublas", "cudnn",
           "ctranslate", "py_compile", ".py\", line", "ffmpeg version", "stream #", "demucs",
           "[gpu]", "[cpu]", "nvidia-smi", "paraformer", "ct-punc", "fsmn-vad", "fa-zh", "int8",
           "float16", "cuda", "torch", "playwright", "headless", "resp len", "selector",
           "fetching ", "it/s", "%|", "warning:root", "warning:", "trust_remote_code",
           "funasr version", "huggingface", "snapshot_download", "download", " version:", "datasets",
           # --- instrumentation/debug nội bộ (khách non-tech KHÔNG cần thấy) ---
           "tts-split", "rapidocr", "clustering", "vào cache", "session chia sẻ",
           "intra_op", "gemprof", "profile|", "_render_profile", "resmon",
           # --- vòng đời render worker nội bộ (spawn/fallback/RAM) — khách chỉ cần thấy KẾT QUẢ render ---
           "render worker", "ram máy đang cao")
           # (dub-stats over-length/histogram đã gate sau VC_DUB_STATS + ghi dev file → khỏi cần ẩn ở đây)
# Gột (thay) — phần lớn về RỖNG để khách chỉ thấy hành động, không thấy engine/model.
_LOG_THAY = (("đọc chữ bằng FunASR", "đọc chữ"), ("bằng FunASR", ""), ("FunASR Paraformer-zh", ""),
             ("Paraformer-zh", ""), ("Paraformer", ""), ("FunASR", ""), ("funasr_ocr", ""),
             ("OCR-timing", "phụ đề"), ("VieNeu", ""),
             ("Piper", ""), ("bằng edge-tts (vi-VN-HoaiMyNeural)", ""),
             ("edge-tts (vi-VN-HoaiMyNeural)", ""), ("edge-tts", ""), ("Gemini web", "AI"),
             ("Gemini", "AI"), ("whisper", ""), ("(asr+punc)", ""), ("(vad+asr+fa+punc)", ""))


# BẢO VỆ IP: gột MỌI tên model/provider/host API AI khỏi text hiện ra khách (khách hay hỏi "dịch model gì"
# để học lỏm). Dùng cho cả log thường (_loc_log) LẪN traceback lỗi (them_log_raw) — nơi dễ lộ nhất.
_AN_MODEL_PAT = _re.compile(
    r"(?i)\b(gemini|gemma\d*|groq|ollama(?:[-_]?local|[-_]?cloud)?|openrouter|qwen\d*|mixtral|mistral|"
    r"deepseek|gpt[-_]?oss|gpt[-_]?4o?|gpt[-_]?3\.?5|chatgpt|claude|cohere|glm[-_]?\d*|llama[-\d.]*|"
    r"paraformer|funasr|fsmn[-_]?vad|ct[-_]?punc|faster[-_]?whisper\w*|whisper\w*|rapidocr\w*|paddle\w*|pp[-_]?ocr\w*|"
    r"supertonic|omnivoice|vieneu|piper|demucs)\b")
_AN_HOST_PAT = _re.compile(r"(?i)\b[\w.-]*\.(?:groq\.com|ollama\.com|openrouter\.ai|googleapis\.com|huggingface\.co)\S*")
def _an_model(s):
    """Thay tên model/provider/host AI → 'AI' (giấu bí quyết). Idempotent."""
    s = _AN_HOST_PAT.sub("AI", s or "")
    s = _AN_MODEL_PAT.sub("AI", s)
    return s


def _loc_log(dong):
    """Trả dòng đã LÀM SẠCH (ẩn = None). Dòng kỹ thuật/model → ẩn; dòng giữ → gột HẾT tên engine/voice."""
    if os.environ.get("LOG_RAW") == "1":
        return dong
    d = (dong or "").strip()
    if not d:
        return None
    if any(k in d.lower() for k in _LOG_AN):
        return None
    # step-marker debug "[4] Gõ prompt...", "[5] Chờ...", "[Gemini] Lô..." → ẩn (khách không cần)
    if _re.match(r"^\[\d+\]\s", d) or d.lower().startswith("[gemini]"):
        return None
    d = _re.sub(r"\s*·\s*cpu\s*\d+%.*$", "", d)   # bỏ đuôi thống kê 'cpu87% gpu16% ram88% vram182MB' (debug)
    for a, b in _LOG_THAY:
        d = d.replace(a, b)
    # An toàn: gột mọi vết engine dịch nền KỂ CẢ VIẾT HOA + ngoặc lộ profile/login đăng nhập sẵn
    d = _re.sub(r"(?i)gemini[\s_]*web", "AI", d)
    d = _an_model(d)   # gột MỌI model/provider/host còn sót (gemma/groq/ollama/openrouter/llama/qwen...)
    d = _re.sub(r"(?i)\s*\([^)]*profile[^)]*\)", "", d)
    # gột voice-code (F1/M2), số worker, "song song N", ngoặc rỗng còn sót
    d = _re.sub(r"\s*\([FM]\d\)", "", d)
    d = _re.sub(r"\s*\|\s*\d+\s*worker.*", "", d)
    d = _re.sub(r"\s*\((?:song song|mỗi worker)[^)]*\)", "", d)
    d = _re.sub(r"\(\s*\)", "", d)
    d = _re.sub(r"\s{2,}", " ", d)
    return d.strip(" :—-(") or None


_RAC = ("fetching ", "it/s", "%|", "warning:root", "trust_remote_code", "funasr version",
        "huggingface", "snapshot_download", " version:", "datasets:", "0%|", "100%|", "?it")


def _la_rac(d):
    """Rác từ huggingface/funasr (tải file, version, warning) — KHÔNG phải lỗi thật. Bỏ khỏi log."""
    low = (d or "").lower()
    return any(k in low for k in _RAC)


def them_log_raw(dong):
    """Ghi log KHÔNG qua bộ lọc _loc_log — dùng cho traceback/lỗi kỹ thuật khi render FAIL, để user/hỗ trợ
    thấy dòng lỗi THẬT (vd ModuleNotFoundError) thay vì bị ẩn như log thường."""
    d = (dong or "").rstrip("\n")
    if not d.strip():
        return
    _t = time.localtime()
    _h = _t.tm_hour % 12 or 12
    _gio = "%d:%02d%s" % (_h, _t.tm_min, "AM" if _t.tm_hour < 12 else "PM")
    with _log_lock:
        _log_lines.append("[%s] %s" % (_gio, d))


def them_log(dong):
    d = _loc_log(dong)
    if d is None:
        return
    _t = time.localtime()                       # giờ cụ thể đầu dòng, vd [10:55AM] — tự build (locale Việt của
    _h = _t.tm_hour % 12 or 12                   # Windows làm %p rỗng nên không dùng strftime); để thấy lúc xong.
    _gio = "%d:%02d%s" % (_h, _t.tm_min, "AM" if _t.tm_hour < 12 else "PM")
    with _log_lock:
        _log_lines.append("[%s] %s" % (_gio, d.rstrip("\n")))
        if len(_log_lines) > 500:
            del _log_lines[:200]


# ---- Job LỒNG TIẾNG (zh->vi) ----
import re as _re
_LT_SCRIPT = os.path.join(THU_MUC_GOC, "long_tieng", "long_tieng.py")
_dub_proc = None
_dub_busy = False       # True từ lúc /api/dub/start GIỮ CHỖ (trong _dub_lock) tới khi worker xong → chống race double-start
_dub_log = []
_dub_pct = 0
_dub_out = None
_dub_segs = []          # bảng SRT điền dần: [{i, st, en, src, vi}]
_dub_segs_map = {}      # i -> dict (cập nhật nhanh)
_dub_lock = threading.Lock()


def _dub_them(dong):
    global _dub_pct, _dub_out
    d = dong.rstrip("\n")
    if d.startswith("LOG:"):           # localize.py in "LOG:..." -> bỏ tiền tố cho gọn
        d = d[4:]
    if d.startswith("SEG|") or d.startswith("SEGVI|"):   # dòng SRT điền dần (không vào log text)
        try:
            pre, js = d.split("|", 1)
            obj = json.loads(js)
            i = obj.get("i")
            if i:
                with _dub_lock:
                    seg = _dub_segs_map.get(i)
                    if seg is None:
                        seg = {"i": i}
                        _dub_segs_map[i] = seg
                        _dub_segs.append(seg)
                    if pre == "SEG":
                        seg["st"] = obj.get("st"); seg["en"] = obj.get("en"); seg["src"] = obj.get("src", "")
                    else:
                        seg["vi"] = obj.get("vi", "")
        except Exception:
            pass
        return
    with _dub_lock:
        m = _re.match(r"\[(\d+)%\]", d)
        if m:
            _dub_pct = int(m.group(1))
        else:
            mf = _re.match(r"\[f5\]\s*(\d+)\s*/\s*(\d+)", d)   # F5: tiến độ N/M -> ~50..95%
            if mf:
                n, tot = int(mf.group(1)), max(1, int(mf.group(2)))
                _dub_pct = min(95, 50 + int(45 * n / tot))
            else:
                # edge/piper qua localize KHÔNG in '[NN%]' → nội suy % theo pha (ASR/dịch/'đọc N/M'/ghép).
                p = _pct_tu_log(d)
                if p:
                    _dub_pct = max(_dub_pct, p)
        if d.startswith("OUT|"):
            _dub_out = d[4:].strip()
        _dub_log.append(d)
        if len(_dub_log) > 400:
            del _dub_log[:150]


_NVIDIA = None


def _co_nvidia():
    """Máy có GPU NVIDIA? (nvidia-smi đi kèm driver). Cache vì status gọi nhiều lần."""
    global _NVIDIA
    if _NVIDIA is None:
        try:
            r = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True,
                               creationflags=_NO_WINDOW, timeout=10)
            _NVIDIA = (r.returncode == 0 and "GPU" in (r.stdout or ""))
        except Exception:
            _NVIDIA = False
    return _NVIDIA


def dub_engines():
    try:
        r = subprocess.run([PYTHON_VENV, _LT_SCRIPT, "--engines"], capture_output=True,
                           text=True, creationflags=_NO_WINDOW, timeout=25)
        eng = json.loads((r.stdout or "{}").strip().splitlines()[-1])
    except Exception:
        eng = {"demucs": False, "nllb": False, "xtts": False}
    # Trạng thái tăng tốc GPU Whisper: có NVIDIA + gói cudart đã cài trong venv chính chưa
    eng["nvidia"] = _co_nvidia()
    eng["gpu_pack"] = os.path.isdir(os.path.join(sys.prefix, "Lib",
                                                 "site-packages", "nvidia", "cuda_runtime"))
    return eng


_MAY_CACHE = None


def _vram_gb_web():
    """Tổng VRAM GPU (GB) qua nvidia-smi; 0 nếu không có. Để cảnh báo model GPU (OmniVoice/Whisper)."""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, creationflags=_NO_WINDOW, timeout=10)
        return round(int((r.stdout or "0").strip().splitlines()[0]) / 1024.0, 1)
    except Exception:
        return 0.0


def _may_goi_y():
    """Dò cấu hình máy CHI TIẾT (CPU/RAM/GPU+VRAM/ổ đĩa) → gợi ý engine + DANH SÁCH CẢNH BÁO cụ thể +
    khuyến nghị tối ưu theo tier. GẮT: RAM<8GB = rủi ro KHÔNG chạy nổi (tool mở Chromium cào+dịch +
    Whisper + ffmpeg cùng lúc). Cache vì cấu hình không đổi trong phiên."""
    global _MAY_CACHE
    if _MAY_CACHE is not None:
        return _MAY_CACHE
    cpu = os.cpu_count() or 2
    ram_gb = thong_tin_may.ram_gb_tong()
    nvidia = _co_nvidia()
    vram_gb = _vram_gb_web() if nvidia else 0.0
    try:
        disk_gb = round(shutil.disk_usage(DATA_DIR if os.path.isdir(DATA_DIR) else THU_MUC_GOC).free / (1024 ** 3), 1)
    except Exception:
        disk_gb = 0.0
    cb = []   # cảnh báo (muc: loi=đỏ chặn / canh=vàng lưu ý / ok=xanh tốt)
    # --- RAM (quan trọng nhất — ca khách 8GB chạy KHÔNG NỔI) ---
    if ram_gb and ram_gb < 8.5:
        cb.append(("loi", "RAM %.0f GB — KHÔNG ĐỦ (đã có khách 8GB chạy không nổi). Tool mở Chromium (cào + "
                          "dịch AI) + nhận dạng giọng + ffmpeg CÙNG LÚC, cộng Windows ~3GB → 8GB hết sạch RAM → "
                          "treo/đơ/lỗi giữa chừng. CẦN ≥16GB để chạy ổn (8-12GB chỉ làm tác vụ nhẹ, rủi ro)." % ram_gb))
    elif ram_gb and ram_gb < 12:
        cb.append(("canh", "RAM %.1f GB — SÁT NGƯỠNG. PHẢI: tắt trình duyệt/app nặng khi chạy · chọn dịch "
                           "'Google' (nhẹ) thay 'AI' (mở Chromium tốn RAM) · KHÔNG bật model GPU nặng · "
                           "render/lồng tiếng TỪNG video một, đừng đa nhiệm." % ram_gb))
    elif ram_gb and ram_gb < 16:
        cb.append(("canh", "RAM %.0f GB — đủ chạy cơ bản; đóng app nặng khi render/dịch nhiều cho mượt." % ram_gb))
    elif ram_gb >= 16:
        cb.append(("ok", "RAM %.0f GB — thoải mái chạy đa nhiệm (cào + dịch AI + render)." % ram_gb))
    # --- CPU ---
    if cpu <= 2:
        cb.append(("loi", "CPU chỉ %d nhân — nhận dạng giọng/render RẤT CHẬM (video 10' có thể >40'). Khó dùng thực tế." % cpu))
    elif cpu < 4:
        cb.append(("canh", "CPU %d nhân — render/nhận dạng giọng chậm. Ưu tiên giọng Online + giảm độ phân giải." % cpu))
    elif cpu >= 8:
        cb.append(("ok", "CPU %d nhân — render đa luồng nhanh." % cpu))
    # --- GPU / VRAM ---
    if not nvidia:
        cb.append(("canh", "KHÔNG có GPU NVIDIA — nhận dạng giọng + render chạy CPU (chậm); giọng CLONE (ViralVoice Clone) "
                           "KHÔNG dùng được. Dùng giọng Tiêu chuẩn/Online."))
    elif vram_gb and vram_gb < 6:
        cb.append(("canh", "GPU %.0f GB VRAM — nhỏ: nhận dạng giọng + giọng Clone tải lại mỗi lần (chậm "
                           "hơn), không giữ nóng được." % vram_gb))
    elif vram_gb >= 8:
        cb.append(("ok", "GPU %.0f GB VRAM — MẠNH: bật giọng Clone chất lượng cao + nhận dạng giọng GPU + giữ nóng model." % vram_gb))
    elif nvidia:
        cb.append(("ok", "Có GPU NVIDIA%s — bật nhận dạng giọng/render GPU." % (" %.0fGB" % vram_gb if vram_gb else "")))
    # --- Ổ đĩa ---
    if disk_gb and disk_gb < 5:
        cb.append(("loi", "Ổ đĩa trống %.1f GB — QUÁ ÍT. Video gốc + bản render + model dễ ĐẦY ổ → lỗi giữa "
                          "chừng. Cần ≥20GB trống (đổi thư mục lưu sang ổ rộng)." % disk_gb))
    elif disk_gb and disk_gb < 15:
        cb.append(("canh", "Ổ đĩa trống %.0f GB — hơi ít cho cào nhiều + render. Dọn bớt / đổi ổ lưu." % disk_gb))

    # --- VERDICT chạy được ---
    co_loi = any(m == "loi" for m, _ in cb)
    if co_loi:
        chay = "rui_ro"        # đỏ: có thể KHÔNG chạy nổi
    elif any(m == "canh" for m, _ in cb):
        chay = "han_che"       # vàng: chạy được nhưng hạn chế/chậm
    else:
        chay = "tot"           # xanh: chạy tốt

    # --- TIER + engine TTS gợi ý + khuyến nghị tối ưu (ưu tiên hiệu quả cho máy mạnh) ---
    if nvidia and vram_gb >= 6 and ram_gb >= 12:
        muc, engine = "rat_manh", "omnivoice"
        ten = "ViralVoice Clone — lồng tiếng AI (GPU)"
        ly_do = "Máy MẠNH (CPU %d nhân · %.0fGB RAM · GPU %.0fGB) → chạy được TẤT CẢ: lồng tiếng AI, dịch AI, nhận dạng giọng GPU." % (cpu, ram_gb, vram_gb)
        kn = ["Lồng tiếng: ViralVoice Clone (chất lượng cao nhất)",
              "Dịch: AI (chất lượng cao nhất)", "Nhận dạng giọng GPU + NVENC bật sẵn", "Băm/render nhiều video song song được"]
    elif nvidia and ram_gb >= 8:
        muc, engine, ten = "manh", "piper", "ViralVoice Tiêu chuẩn (offline, nhanh) — hoặc Clone nếu cần AI"
        ly_do = "Máy khá (có GPU, %.0fGB RAM) → nhận dạng giọng/render GPU nhanh; lồng tiếng Tiêu chuẩn (Clone được nhưng chậm trên VRAM nhỏ)." % ram_gb
        kn = ["Lồng tiếng: ViralVoice Tiêu chuẩn (nhanh) hoặc Clone", "Dịch: AI hoặc Google", "Nhận dạng giọng GPU bật", "Render 1-2 video/lần"]
    elif cpu >= 4 and ram_gb >= 12:
        muc, engine, ten = "trung_binh", "piper", "ViralVoice Tiêu chuẩn — giọng Việt tự nhiên (offline, nhanh)"
        ly_do = "Máy tầm trung (CPU %d nhân · %.0fGB RAM · không GPU) → Tiêu chuẩn cân bằng; render/nhận dạng giọng CPU (chậm vừa)." % (cpu, ram_gb)
        kn = ["Lồng tiếng: ViralVoice Tiêu chuẩn (offline)", "Dịch: AI hoặc Google", "Đóng app nặng khi render", "Render TỪNG video"]
    else:
        muc, engine, ten = "yeu", "edge", "ViralVoice Online — nhẹ nhất (cần mạng)"
        ly_do = "Máy YẾU (CPU %d nhân · %.0fGB RAM%s) → chỉ nên tác vụ nhẹ; cào/render lớn dễ lỗi." % (cpu, ram_gb, "" if nvidia else " · không GPU")
        kn = ["Lồng tiếng: Edge (nhẹ nhất)", "Dịch: Google (KHÔNG mở Chromium AI tốn RAM)",
              "Render 1 video/lần, tránh đa nhiệm", "Nâng RAM ≥16GB + thêm GPU để dùng đầy đủ"]

    _MAY_CACHE = {"cpu": cpu, "ram_gb": ram_gb, "nvidia": nvidia, "vram_gb": vram_gb, "disk_gb": disk_gb,
                  "muc": muc, "chay": chay, "engine": engine, "ten": ten, "ly_do": ly_do,
                  "canh_bao": [{"muc": m, "txt": t} for m, t in cb], "khuyen_nghi": kn}
    return _MAY_CACHE


def _dub_giu_cho():
    """Giữ chỗ lồng tiếng (chống race double-start/double-count). True=giữ được; False=đang bận."""
    global _dub_busy
    with _dub_lock:
        if _dub_proc is not None or _dub_busy:
            return False
        _dub_busy = True
        return True


def _dub_nha_cho():
    global _dub_busy
    _dub_busy = False


def chay_long_tieng(params, ghn=None, ghp=None, phut=0):
    global _dub_proc, _dub_pct, _dub_out, _dub_busy, _dub_phut_dang
    _dub_phut_dang = phut if (ghp is not None and phut) else 0   # cộng vào cam kết CHUNG khi enqueue render song song
    raw = (params.get("video") or "").replace("\\", "/")
    rel = raw.lstrip("/")
    # Dùng _resolve_video (giống /video, /thumb): HỖ TRỢ data ở Ổ ĐĨA KHÁC (D:) — trước đây check
    # cứng `startswith(THU_MUC_GOC)` (chỉ ổ app) làm "không tìm thấy video" khi user chọn thư mục lưu khác ổ.
    video = _resolve_video(rel)
    if not video or not os.path.exists(video):
        # FALLBACK BỀN (máy khách: DATA_DIR ở userData / ổ khác → round-trip _rel_goc↔_resolve_video có
        # thể trượt; tên file có #/Hán). (1) raw đã là path THẬT trong vùng cho phép? (2) tìm theo TÊN
        # file trong DATA_DIR/PROCESSED_DIR. Vẫn an toàn (chỉ trong vùng cho phép).
        video = None
        if os.path.isfile(raw) and _trong_vung(raw, DATA_DIR, PROCESSED_DIR):
            video = raw
        else:
            ten = os.path.basename(rel)
            if ten:
                for base in (DATA_DIR, PROCESSED_DIR):
                    if video:
                        break
                    try:
                        for root_, _dirs, files in os.walk(base):
                            if ten in files:
                                video = os.path.join(root_, ten)
                                break
                    except Exception:
                        pass
        if not video or not os.path.exists(video):
            _dub_them("[0%] Lỗi: không tìm thấy video (đã thử path: " + (raw[:160] or "(rỗng)") + ")."); return
    tts = params.get("tts", "edge")
    _voice_nhung = ""
    if ":" in tts:   # net an toàn: lỡ nhận "piper:ngochuyen" (UI gộp engine+giọng) → tách ra
        tts, _voice_nhung = tts.split(":", 1)
    if tts not in ("edge", "piper", "omnivoice", "supertonic"):
        tts = "edge"
    # GỘP (1 backend): MỌI engine chạy qua localize.py — 1 pipeline thống nhất với render (xu_ly_chon),
    # 1 output _longtieng.mp4, tùy chọn áp dụng nhất quán. Nhánh long_tieng/long_tieng.py cũ (edge/xtts)
    # KHÔNG còn được gọi (file giữ lại để tham khảo/rollback).
    out = os.path.splitext(video)[0] + "_longtieng.mp4"
    # "Tên file xuất" (tuỳ chọn): user đặt tên video lồng tiếng thay vì <gốc>_longtieng.mp4. CHỈ lấy
    # basename (chặn path traversal) + bỏ ký tự cấm Windows + ép .mp4. Rỗng/không hợp lệ → giữ mặc định.
    _tx = (params.get("ten_xuat") or "").strip()
    out_tuy_chon = None
    if _tx:
        _tx = os.path.basename(_tx)
        if _tx.lower().endswith(".mp4"):
            _tx = _tx[:-4]
        _tx = _re.sub(r'[\\/:*?"<>|]', "", _tx).strip().strip(".")[:120]
        if _tx:
            out_tuy_chon = os.path.join(os.path.dirname(out), _tx + ".mp4")
    # DỊCH: luôn Gemini web (nền, KHÔNG cần key). Google ĐÃ BỎ (chất lượng không chấp nhận được). NLLB đã bỏ.
    engine = "gemini"
    cmd = [PYTHON_VENV, "localize.py", video, "--model", params.get("model", "medium"),
           "--engine", engine, "--long-tieng", "--no-che", "--tts", tts]
    if params.get("dich_lai"):           # "Render từ đầu": bỏ qua cache dịch+lồng tiếng → làm mới
        cmd += ["--dich-lai"]
    # "Nhạc/tiếng nền": none = chỉ giọng Việt (goc-vol 0); duck = giữ nền. Mức nền theo slider "Âm lượng
    # nền" (nen_vol 0-100, mặc định 12%) khi giữ nền.
    if params.get("sep") == "none":
        _nen = 0.0
    else:
        try:
            _nen = max(0.0, min(1.0, float(params.get("nen_vol")) / 100.0))
        except (TypeError, ValueError):
            _nen = 0.12
    cmd += ["--goc-vol", "%.3f" % _nen]
    # "Âm lượng giọng" lồng tiếng (slider, 0-150% → 0-1.5; mặc định 100% = không đổi)
    if params.get("giong_vol") is not None:
        try:
            cmd += ["--giong-vol", "%.3f" % max(0.0, min(1.5, float(params.get("giong_vol")) / 100.0))]
        except (TypeError, ValueError):
            pass
    # Lọc âm nâng cao (checkbox): chỉ nhận giá trị hợp lệ → tránh inject
    _af = params.get("af")
    if isinstance(_af, list) and _af:
        _afv = [x for x in _af if x in ("normalize", "denoise", "wind")]
        if _afv:
            cmd += ["--af", ",".join(_afv)]
    voice = (params.get("voice") or _voice_nhung or "").strip()
    if voice and ("/" in voice or voice.lower().endswith((".wav", ".mp3"))):
        # BẢO MẬT: voice dạng path (giọng clone) PHẢI qua _whitelist_ref (giong_mau/CLONE_DIR/DATA_DIR,
        # chặn '-' arg-injection). Trước đây đưa thẳng path lạ vào localize → đọc file tuỳ ý làm ref-audio.
        try:
            _rv = _whitelist_ref(voice)
        except ValueError:
            _rv = None
        if _rv:
            cmd += ["--ref-audio=" + _rv]    # =value chống arg-injection (mirror _lenh_xu_ly)
            _dem_clone_lan_dau(_rv)           # trừ quota clone khi DÙNG lần đầu (không trừ lúc upload)
        # path ngoài vùng → bỏ ref-audio, dùng giọng mặc định (KHÔNG đưa path lạ vào subprocess)
    elif voice and tts in ("edge", "piper", "supertonic"):
        cmd += ["--voice", voice]        # edge: giọng MS · piper: Banmai/NghiTTS · supertonic: F1-F5/M1-M5
    # OmniVoice: chất lượng ns (8/16/32) qua env subprocess. Daemon vẫn warm trong phiên (idle mặc định 180s).
    _env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    if tts == "omnivoice":
        _ns = str(params.get("omni_ns") or "8")
        if _ns in ("8", "16", "32"):
            _env["OMNI_NS"] = _ns

    def worker():
        global _dub_proc, _dub_out, _dub_pct, _dub_busy, _dub_phut_dang
        rc = 1
        try:
            _dub_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         text=True, encoding="utf-8", errors="replace",
                                         creationflags=_NO_WINDOW, cwd=THU_MUC_GOC, env=_env)
            for line in _dub_proc.stdout:
                _dub_them(line)
            rc = _dub_proc.wait()
            # "Tên file xuất": đổi tên output thật (localize ra = `out`) theo tên user đặt (nếu có).
            # Dùng biến MỚI final_out (KHÔNG gán lại `out` — nó là biến closure, gán sẽ thành local → UnboundLocalError).
            final_out = out
            if out_tuy_chon and os.path.isfile(out) and os.path.abspath(out) != os.path.abspath(out_tuy_chon):
                try:
                    os.replace(out, out_tuy_chon); final_out = out_tuy_chon
                except Exception:
                    pass
            # localize không in "OUT|" -> tự gán kết quả nếu file đã ra
            if _dub_out is None and os.path.exists(final_out):
                _dub_out = final_out
                _dub_pct = 100
            # XUẤT CẢ FILE ÂM THANH: tách track giọng lồng tiếng ra .mp3 CÙNG TÊN video (user dùng riêng
            # — đăng/reup/ghép chỗ khác). localize đã xoá wav tạm nên tách lại từ video output.
            try:
                _vid_out = _dub_out if (_dub_out and os.path.isabs(_dub_out)) else (
                    os.path.join(THU_MUC_GOC, _dub_out) if _dub_out else None)
                if _vid_out and os.path.isfile(_vid_out):
                    _ff = shutil.which("ffmpeg") or "ffmpeg"
                    try:
                        import xu_ly_video as _xlv
                        _ff = _xlv.tim_exe("ffmpeg") or _ff
                    except Exception:
                        pass
                    _mp3 = os.path.splitext(_vid_out)[0] + ".mp3"
                    subprocess.run([_ff, "-y", "-i", _vid_out, "-vn", "-c:a", "libmp3lame",
                                    "-b:a", "192k", _mp3], capture_output=True, creationflags=_NO_WINDOW)
                    if os.path.isfile(_mp3):
                        _dub_them("🎵 Đã xuất file âm thanh: " + os.path.basename(_mp3))
            except Exception:
                pass
            # Đếm quota CHỈ KHI thành công (rc==0 hoặc có file ra) — như crawl đếm theo save-success,
            # tránh trừ quota oan khi job fail (codec lỗi/hết RAM). Race double-start đã chặn bằng _dub_busy.
            if rc == 0 or _dub_out:
                if ghn is not None:
                    kdb.usage_cong("dub", 1)
                if ghp is not None and phut:
                    kdb.usage_cong("dub_phut", phut)
        except Exception as e:
            _dub_them(f"[0%] Lỗi: {e}")
        finally:
            _dub_proc = None
            _dub_busy = False
            _dub_phut_dang = 0

    with _dub_lock:
        _dub_log.clear()
        _dub_segs.clear()
        _dub_segs_map.clear()
    _dub_pct = 0
    _dub_out = None
    threading.Thread(target=worker, daemon=True).start()


def dung_long_tieng():
    global _dub_proc, _dub_busy
    _dub_busy = False
    if _dub_proc:
        _kill_proc_tree(_dub_proc)   # kill CẢ CÂY (ffmpeg/whisper/demucs con) — .kill() chỉ giết tiến trình cha
        _dub_proc = None


def chay_cai_nangcao():
    """Cài bản nâng cao (Demucs/NLLB/viXTTS ~5GB) qua long_tieng/cai_nangcao.py — log vào _dub_log."""
    global _dub_proc, _dub_pct, _dub_out
    script = os.path.join(THU_MUC_GOC, "long_tieng", "cai_nangcao.py")
    cmd = [PYTHON_VENV, script]

    def worker():
        global _dub_proc
        try:
            _dub_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         text=True, encoding="utf-8", errors="replace",
                                         creationflags=_NO_WINDOW, cwd=THU_MUC_GOC)
            for line in _dub_proc.stdout:
                _dub_them(line)
            _dub_proc.wait()
        except Exception as e:
            _dub_them(f"Lỗi cài nâng cao: {e}")
        finally:
            _dub_proc = None

    with _dub_lock:
        _dub_log.clear()
    _dub_pct = 0
    _dub_out = None
    threading.Thread(target=worker, daemon=True).start()


def _chay_cai_script(script, nhan="cài"):
    """Chạy 1 script cài đặt (cai_gpu.py) trong venv chính, log vào _dub_log.
    Tái dùng hạ tầng _dub_proc/_dub_log như chay_cai_nangcao (poll qua /api/dub/log)."""
    global _dub_proc, _dub_pct, _dub_out
    cmd = [PYTHON_VENV, script]

    def worker():
        global _dub_proc
        try:
            _dub_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         text=True, encoding="utf-8", errors="replace",
                                         creationflags=_NO_WINDOW, cwd=THU_MUC_GOC)
            for line in _dub_proc.stdout:
                _dub_them(line)
            _dub_proc.wait()
        except Exception as e:
            _dub_them(f"Lỗi {nhan}: {e}")
        finally:
            _dub_proc = None

    with _dub_lock:
        _dub_log.clear()
    _dub_pct = 0
    _dub_out = None
    threading.Thread(target=worker, daemon=True).start()


# ---- Job CHỤP REDDIT/THREADS + ĐÈ SUB + TTS (Nhánh A) ----
_CHUP_SCRIPT = os.path.join(THU_MUC_GOC, "chup_bai.py")
_SUB_SCRIPT = os.path.join(THU_MUC_GOC, "lam_sub_anh.py")
_VIDEO_SCRIPT = os.path.join(THU_MUC_GOC, "lam_video_anh.py")
ANH_CHUP_DIR = os.path.join(THU_MUC_GOC, "anh_chup")
_chup_proc = None
_chup_running = False    # True suốt cả 2 bước (chụp + sub) — tránh poll tưởng xong sớm
_chup_log = []
_chup_out = None        # thư mục kết quả, tương đối anh_chup/ (vd "reddit/abc123")
_chup_lock = threading.Lock()


def _chup_them(dong):
    d = dong.rstrip("\n")
    if d.startswith("LOG:"):
        d = d[4:]
    if d.startswith(("CHUP_DONE", "SUB_DONE")):
        return
    with _chup_lock:
        _chup_log.append(d)
        if len(_chup_log) > 400:
            del _chup_log[:150]


def chay_chup_sub(params):
    global _chup_proc, _chup_out, _chup_running
    import chup_bai as _cb
    platform = "th" if params.get("platform") == "th" else "rd"
    mode = params.get("mode") or "post"
    if mode not in ("post", "feed", "search"):
        mode = "post"
    url = (params.get("url") or "").strip()
    keyword = (params.get("keyword") or "").strip()
    feed_url = (params.get("feed_url") or "").strip()
    comments = str(params.get("comments") or "10")
    target = ngngu._chuan(params.get("target")) or ngngu.target_lang()
    cookies = (params.get("cookies") or "").strip()
    lam_tts = params.get("tts", True)
    posts = str(params.get("posts") or "5")
    min_like = str(params.get("min_like") or "2000")
    min_cmt = str(params.get("min_cmt") or "100")
    max_cmt = str(params.get("max_cmt") or "20")
    outdir = (params.get("outdir") or "").strip()
    nhieu = mode in ("feed", "search")   # mode gom nhiều bài → nhiều thư mục con

    if mode == "post" and not url:
        _chup_them("⚠ Chưa nhập link."); return
    if mode == "search" and not keyword:
        _chup_them("⚠ Chưa nhập từ khóa."); return

    # Thư mục output (gốc). Người dùng chọn ở UI; trống thì dùng mặc định theo nền tảng/mode.
    if outdir:
        out_root = outdir
    elif mode == "post":
        if platform == "rd":
            out_root = os.path.join(ANH_CHUP_DIR, "reddit", _cb.reddit_id(url))
        else:
            out_root = os.path.join(ANH_CHUP_DIR, "threads",
                                    _cb.an_toan(url.rstrip("/").rsplit("/", 1)[-1]))
    else:
        out_root = os.path.join(ANH_CHUP_DIR, "reddit_feed" if platform == "rd" else "threads_feed")

    def _run(cmd):
        global _chup_proc
        _chup_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      text=True, encoding="utf-8", errors="replace",
                                      creationflags=_NO_WINDOW, cwd=THU_MUC_GOC)
        for line in _chup_proc.stdout:
            _chup_them(line)
        _chup_proc.wait()
        rc = _chup_proc.returncode
        _chup_proc = None
        return rc

    def _co_noidung(d):
        return os.path.isfile(os.path.join(d, "noi_dung.json"))

    def worker():
        global _chup_proc, _chup_out, _chup_running
        try:
            ten_nt = "Threads" if platform == "th" else "Reddit"
            t0 = time.time()
            cmd1 = [PYTHON_VENV, _CHUP_SCRIPT, "--platform", platform, "--mode", mode, "--out", out_root]
            if mode == "post":
                cmd1 += ["--url", url, "--comments", comments]
            else:
                cmd1 += ["--posts", posts, "--min-like", min_like,
                         "--min-cmt", min_cmt, "--max-cmt", max_cmt]
                if mode == "search":
                    cmd1 += ["--keyword", keyword]
                elif feed_url:
                    cmd1 += ["--feed-url", feed_url]
            if cookies:
                cmd1 += ["--cookies", cookies]
            mo_ta = {"post": "theo link", "feed": "lướt feed", "search": "theo từ khóa"}[mode]
            _chup_them(f"▶ Chụp {ten_nt} ({mo_ta})...")
            if _run(cmd1) != 0:
                _chup_them("⚠ Chụp thất bại."); return

            # Tập thư mục cần dịch+đè sub+dựng video.
            if mode == "post":
                folders = [out_root] if _co_noidung(out_root) else []
            else:
                # các thư mục con MỚI tạo/cập nhật trong lần chạy này (mtime của noi_dung.json >= t0)
                folders = []
                if os.path.isdir(out_root):
                    for ten in sorted(os.listdir(out_root)):
                        d = os.path.join(out_root, ten)
                        nj = os.path.join(d, "noi_dung.json")
                        if os.path.isfile(nj) and os.path.getmtime(nj) >= t0 - 2:
                            folders.append(d)
            if not folders:
                _chup_them("⚠ Không có bài nào để xử lý (không đạt ngưỡng / chụp rỗng).")
                return

            for i, folder in enumerate(folders, 1):
                nhan = f" [{i}/{len(folders)}]" if len(folders) > 1 else ""
                cmd2 = [PYTHON_VENV, _SUB_SCRIPT, "--folder", folder, "--target", target]
                if not lam_tts:
                    cmd2.append("--no-tts")
                _chup_them(f"▶{nhan} Dịch + đè sub + TTS (đích: {target}): {os.path.basename(folder)}")
                _run(cmd2)
                _chup_them(f"▶{nhan} Dựng video .mp4 (ghép ảnh + audio)...")
                _run([PYTHON_VENV, _VIDEO_SCRIPT, "--folder", folder])

            _chup_out = out_root
            try:
                rel = os.path.relpath(out_root, THU_MUC_GOC)
            except ValueError:
                rel = out_root
            _chup_them(f"✔ Xong {len(folders)} bài! Ảnh + audio + video ở: {rel}")
        except Exception as e:
            _chup_them(f"⚠ Lỗi: {e}")
        finally:
            _chup_proc = None
            _chup_running = False

    with _chup_lock:
        _chup_log.clear()
    _chup_out = None
    _chup_running = True
    threading.Thread(target=worker, daemon=True).start()


def dung_chup_sub():
    global _chup_proc, _chup_running
    _chup_running = False
    if _chup_proc:
        try:
            _chup_proc.kill()
        except Exception:
            pass
        _chup_proc = None


# ---- Job BĂM NHỎ video dài -> clip ngắn theo cảnh (cat_nho.py + PySceneDetect) ----
_BAM_SCRIPT = os.path.join(THU_MUC_GOC, "cat_nho.py")
_BAM_VIDEO_EXT = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".flv", ".ts", ".m4v")
_bam_proc = None
_bam_running = False
_bam_log = []
_bam_out = []            # list {name, p(abs)} clip cho UI xem trước
_bam_serve_dirs = set()  # thư mục nguồn/clip ngoài dự án được phép phục vụ /video, /thumb
_bam_serve_files = set() # file nguồn ĐĂNG KÝ riêng lẻ (xem trước) — KHÔNG mở cả thư mục cha (H2)
_bam_lock = threading.Lock()


def _bam_la_video(name):
    return str(name).lower().endswith(_BAM_VIDEO_EXT)


def _bam_video_paths(params):
    """Chuẩn hóa danh sách video cần băm -> list abs path (rel = video đã cào dưới THU_MUC_GOC,
    đường dẫn tuyệt đối = file trong thư mục gốc người dùng chọn). Bỏ trùng, chỉ giữ file video tồn tại."""
    raw = params.get("videos")
    if not raw:
        one = params.get("video")
        raw = [one] if one else []
    out = []
    for item in raw:
        if not item:
            continue
        s = str(item).replace("\\", "/")
        if os.path.isabs(s) or (len(s) > 1 and s[1] == ":"):   # tuyệt đối (thư mục gốc)
            full = os.path.normpath(s)
        else:                                                  # tương đối THU_MUC_GOC (đã cào)
            full = os.path.normpath(os.path.join(THU_MUC_GOC, s.lstrip("/")))
        if os.path.isfile(full) and _bam_la_video(full) and full not in out:
            out.append(full)
    return out


def _bam_them(line):
    line = (line or "").rstrip("\n")
    if not line:
        return
    with _bam_lock:
        _bam_log.append(line)
        if len(_bam_log) > 500:
            del _bam_log[:-500]


def _bam_liet_clip(out_dir):
    """List clip .mp4 trong out_dir -> [{name, p(abs, dấu /)}] cho UI xem trước."""
    import glob as _g
    out = []
    for f in sorted(_g.glob(os.path.join(out_dir, "*.mp4"))):
        out.append({"name": os.path.basename(f), "p": f.replace("\\", "/")})
    return out


def _bam_out_dir(video):
    """Thư mục lưu clip khi băm 1 video nguồn:
    - Video ĐÃ TẢI (trong DATA_DIR/PROCESSED_DIR/_OUT_DIRS) → clip_nho/ cạnh nguồn (File đã tải đã quét sẵn).
    - Video NGOÀI (user tự thêm) → DATA_DIR/bam_nho/<tên>/ → để clip HIỆN ở 'File đã tải' sau khi băm."""
    vn = os.path.normcase(os.path.abspath(video))
    for r in [DATA_DIR, PROCESSED_DIR] + list(_OUT_DIRS):
        try:
            rn = os.path.normcase(os.path.abspath(r))
            if os.path.commonpath([rn, vn]) == rn:
                return os.path.join(os.path.dirname(video), "clip_nho")
        except (ValueError, TypeError):
            continue
    stem = os.path.splitext(os.path.basename(video))[0] or "video"
    return os.path.join(DATA_DIR, "bam_nho", stem)


def _ffmpeg_bin():
    ff = shutil.which("ffmpeg") or "ffmpeg"
    try:
        import xu_ly_video as _xlv
        ff = _xlv.tim_exe("ffmpeg") or ff
    except Exception:
        pass
    return ff


def _la_faststart(path):
    """MP4 đã 'web-optimized'? (moov xuất hiện TRƯỚC mdat ở vài atom đầu → trình duyệt tua được NGAY,
    không phải tải hết file). moov nằm CUỐI → phải tải hết mới seek = 'đợi load hết'."""
    import struct
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            pos = 0
            for _ in range(8):
                f.seek(pos); hdr = f.read(8)
                if len(hdr) < 8:
                    break
                sz = struct.unpack(">I", hdr[:4])[0]
                typ = hdr[4:8]
                if typ == b"moov":
                    return True
                if typ == b"mdat":
                    return False           # mdat trước moov → KHÔNG faststart
                if sz == 1:                # atom 64-bit (file lớn)
                    f.seek(pos + 8); sz = struct.unpack(">Q", f.read(8))[0]
                if sz < 8:
                    break
                pos += sz
                if pos >= size:
                    break
    except Exception:
        pass
    return True   # không đọc được → coi như ổn (khỏi remux phí)


_seekable_cache = {}   # (src_normcase, mtime) -> path faststart đã remux (tái dùng giữa các lần mở editor)


def _bam_seekable(src):
    """Trả path video SEEKABLE (faststart) cho editor băm — để tua/cắt tức thì như YouTube, KHỎI đợi load hết.
    Đã faststart → trả src luôn (video đã cào/render thường đã faststart). CHƯA (hay gặp ở video TỰ THÊM) →
    remux `+faststart` (DỜI index lên đầu, `-c copy` KHÔNG re-encode → KHÔNG giảm chất, nhanh) + cache.
    Lỗi remux → trả src (vẫn xem được, chỉ tua chậm)."""
    src = os.path.abspath(src)
    if not os.path.isfile(src) or _la_faststart(src):
        return src
    try:
        key = (os.path.normcase(src), os.path.getmtime(src))
    except OSError:
        return src
    hit = _seekable_cache.get(key)
    if hit and os.path.isfile(hit):
        return hit
    import hashlib
    cache_dir = os.path.join(tempfile.gettempdir(), "vc_seekable")
    try:
        os.makedirs(cache_dir, exist_ok=True)
    except OSError:
        return src
    h = hashlib.sha1(("%s|%s" % key).encode("utf-8", "replace")).hexdigest()[:16]
    out = os.path.join(cache_dir, h + ".mp4")
    if not os.path.isfile(out):
        cmd = [_ffmpeg_bin(), "-y", "-i", src, "-c", "copy", "-movflags", "+faststart", out]
        try:
            r = subprocess.run(cmd, capture_output=True, creationflags=_NO_WINDOW, timeout=600)
            if r.returncode != 0 or not os.path.isfile(out):
                return src
        except Exception:
            return src
    _seekable_cache[key] = out
    with _bam_lock:
        _bam_serve_files.add(os.path.normcase(os.path.abspath(out)))   # cho /video phục vụ file cache
    return out


def chay_bam_nho(params):
    """Băm video -> clip ngắn (cat_nho.py tuần tự, luôn cắt chính xác/re-encode). 3 chế độ:
    - `ranges` (list [s,e]): XUẤT đúng các khoảng từ bản xem trước (chỉ 1 video).
    - `so_ban` (N>0): chia mỗi video thành ĐÚNG N bản (đều + dời về cảnh) — băm hàng loạt.
    - `muc_tieu` (giây): cách cũ (gom theo độ dài), giữ tương thích."""
    global _bam_running
    videos = _bam_video_paths(params)
    if not videos:
        _bam_them("Lỗi: không có video hợp lệ để băm."); return
    try:
        muc_tieu = max(5.0, float(params.get("muc_tieu") or 40))
    except (TypeError, ValueError):
        muc_tieu = 40.0
    try:
        nguong = float(params.get("nguong") or 27)
    except (TypeError, ValueError):
        nguong = 27.0
    try:
        so_ban = int(float(params.get("so_ban") or 0))
    except (TypeError, ValueError):
        so_ban = 0
    ratio = params.get("ratio") if params.get("ratio") in ("9:16", "16:9") else ""
    # chinh_xac=False (mặc định) → cắt `-c copy` TỨC THÌ (không re-encode, không giảm chất, snap keyframe gần
    # nhất). True → re-encode cắt đúng frame (chậm, ngốn CPU/decode). Đổi khung 9:16 thì BUỘC re-encode (cat_nho lo).
    chinh_xac = bool(params.get("chinh_xac"))

    # XUẤT theo ranges (bản xem trước): chỉ áp cho 1 video, ghi khoảng ra file tạm JSON (không BOM).
    ranges = params.get("ranges")
    ranges_file = ""
    if isinstance(ranges, list) and ranges:
        videos = videos[:1]
        try:
            kh = [[float(r[0]), float(r[1])] for r in ranges if len(r) >= 2 and float(r[1]) - float(r[0]) >= 0.5]
        except (TypeError, ValueError, IndexError):
            kh = []
        if not kh:
            _bam_them("Lỗi: khoảng cắt không hợp lệ."); return
        fd, ranges_file = tempfile.mkstemp(prefix="bam_rg_", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(kh, f)

    out_dirs = [_bam_out_dir(v) for v in videos]   # video ngoài → DATA_DIR/bam_nho/ (hiện ở File đã tải)
    with _bam_lock:                          # chỉ mở phục vụ /video cho thư mục CLIP output (xem trước kết quả)
        for od in out_dirs:
            _bam_serve_dirs.add(os.path.normpath(od))

    def worker():
        global _bam_proc, _bam_running, _bam_out
        try:
            for idx, video in enumerate(videos, 1):
                if not _bam_running:
                    _bam_them("⛔ Đã dừng."); break
                _bam_them("━━━ [%d/%d] %s" % (idx, len(videos), os.path.basename(video)))
                cmd = [PYTHON_VENV, _BAM_SCRIPT, video, out_dirs[idx - 1]]
                if chinh_xac:
                    cmd += ["--chinh-xac"]    # chỉ re-encode khi user CHỌN cắt chính xác frame (else -c copy nhanh)
                if ranges_file:
                    cmd += ["--ranges", ranges_file]
                elif so_ban > 0:
                    cmd += ["--so-ban", str(so_ban), "--nguong", str(nguong)]
                else:
                    cmd += ["--muc-tieu", str(muc_tieu), "--nguong", str(nguong)]
                if ratio:
                    cmd += ["--ratio", ratio]
                try:
                    _bam_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                                 text=True, encoding="utf-8", errors="replace",
                                                 creationflags=_NO_WINDOW, cwd=THU_MUC_GOC)
                    for line in _bam_proc.stdout:
                        _bam_them(line)
                    _bam_proc.wait()
                except Exception as e:
                    _bam_them("Lỗi băm: " + str(e))
                finally:
                    _bam_proc = None
        finally:
            _bam_running = False
            if ranges_file:
                try:
                    os.remove(ranges_file)
                except OSError:
                    pass
            with _bam_lock:
                seen, clips = set(), []
                for od in out_dirs:
                    for c in _bam_liet_clip(od):
                        if c["p"] not in seen:
                            seen.add(c["p"]); clips.append(c)
                _bam_out = clips
            _bam_them("✅ Hoàn tất: %d clip." % len(clips))

    with _bam_lock:
        _bam_log.clear()
        _bam_out = []
        _bam_running = True
    threading.Thread(target=worker, daemon=True).start()


def dung_bam_nho():
    global _bam_proc, _bam_running
    _bam_running = False
    if _bam_proc:
        try:
            _bam_proc.kill()
        except Exception:
            pass
        _bam_proc = None


# ---- PHÂN TÍCH cảnh 1 video (cho UI xem trước + chỉnh số bản N, KHÔNG cắt file) ----
_bam_pt = {"running": False, "done": False, "video": "", "dur": 0.0, "scenes": [], "err": ""}
_bam_pt_proc = None
_bam_pt_lock = threading.Lock()


def chay_phan_tich(video_path, nguong=27.0):
    """Dò cảnh + thời lượng 1 video ở NỀN (cat_nho.py --phan-tich in JSON). Kết quả vào _bam_pt."""
    global _bam_pt_proc
    with _bam_lock:                          # cho phép /video phục vụ ĐÚNG file video nguồn (xem trước media-fragment)
        _bam_serve_files.add(os.path.normcase(os.path.abspath(video_path)))   # file-level: KHÔNG lộ cả thư mục cha (H2)
    cmd = [PYTHON_VENV, _BAM_SCRIPT, video_path, "--phan-tich", "--nguong", str(nguong)]

    def worker():
        global _bam_pt_proc
        out = ""
        try:
            _bam_pt_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                            text=True, encoding="utf-8", errors="replace",
                                            creationflags=_NO_WINDOW, cwd=THU_MUC_GOC)
            out, _ = _bam_pt_proc.communicate()
        except Exception as e:
            with _bam_pt_lock:
                _bam_pt.update(running=False, done=False, err=str(e)[:200])
            return
        finally:
            _bam_pt_proc = None
        data = None
        for line in reversed((out or "").splitlines()):    # dòng JSON cuối (bỏ cảnh báo lạc)
            line = line.strip()
            if line.startswith("{"):
                try:
                    data = json.loads(line); break
                except Exception:
                    pass
        with _bam_pt_lock:
            if data and data.get("dur", 0) > 0:
                _bam_pt.update(running=False, done=True, dur=data["dur"],
                               scenes=data.get("scenes", []), err="")
            else:
                _bam_pt.update(running=False, done=False, err="Không phân tích được video.")

    with _bam_pt_lock:
        _bam_pt.update(running=True, done=False, video=video_path, dur=0.0, scenes=[], err="")
    threading.Thread(target=worker, daemon=True).start()


def chup_sub_ket_qua(rel):
    """Đọc sub.json -> {items:[{loai, anh_url, wav_url}], video_url}. video_url='' nếu chưa dựng."""
    full = os.path.normpath(os.path.join(ANH_CHUP_DIR, (rel or "").replace("/", os.sep)))
    if not full.startswith(ANH_CHUP_DIR):
        return {"items": [], "video_url": ""}
    sj = os.path.join(full, "sub.json")
    if not os.path.isfile(sj):
        return {"items": [], "video_url": ""}
    try:
        items = json.load(open(sj, encoding="utf-8")).get("items", [])
    except Exception:
        return {"items": [], "video_url": ""}
    out = []
    for it in items:
        anh, wav = it.get("anh"), it.get("wav")
        out.append({"loai": it.get("loai", ""),
                    "anh_url": f"/anhchup/{rel}/{anh}" if anh else "",
                    "wav_url": f"/anhchup/{rel}/{wav}" if wav else ""})
    code = os.path.basename(full)
    video_url = f"/anhchup/{rel}/{code}.mp4" if os.path.isfile(os.path.join(full, code + ".mp4")) else ""
    return {"items": out, "video_url": video_url}


def dich_google(text, tl, sl="auto"):
    url = ("https://translate.googleapis.com/translate_a/single"
           "?client=gtx&sl=" + sl + "&tl=" + tl + "&dt=t&q=" + urllib.parse.quote(text))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode("utf-8"))
    return "".join(s[0] for s in data[0] if s and s[0]).strip()


_TERM_EN = None


def dich_term_en(term):
    """Dịch nhãn (kênh/từ khóa) sang tiếng Anh để phân biệt; cache. '' nếu đã có chữ Latin."""
    global _TERM_EN
    if _TERM_EN is None:
        _TERM_EN = {}
        p = os.path.join(DATA_DIR, "douyin", "_filter_en.json")
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    _TERM_EN = json.load(f)
            except Exception:
                _TERM_EN = {}
    if not term:
        return ""
    if term in _TERM_EN:
        return _TERM_EN[term]
    ascii_letters = sum(1 for c in term if ord(c) < 128 and c.isalpha())
    en = ""
    if ascii_letters < 3:  # đã có chữ Latin thì khỏi dịch
        try:
            en = dich_google(term, "en", sl="zh-CN")[:30].strip()
        except Exception:
            en = ""
    _TERM_EN[term] = en
    try:
        p = os.path.join(DATA_DIR, "douyin", "_filter_en.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(_TERM_EN, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return en


def _co_cjk(s):
    return any("一" <= c <= "鿿" for c in (s or ""))


_TD_TITLE = {}                 # {lang: {tiêu đề gốc: bản dịch}} — cache tách theo ngôn ngữ đích
_TD_VI_LOCK = threading.Lock()


def _td_path(lang):
    return os.path.join(DATA_DIR, f"_tieu_de_{lang}.json")


def _td_vi(lang=None):
    lang = lang or ngngu.target_lang()
    if lang not in _TD_TITLE:
        c = {}
        p = _td_path(lang)
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    c = json.load(f)
            except Exception:
                c = {}
        _TD_TITLE[lang] = c
    return _TD_TITLE[lang]


_TK_VI = None   # cache TỪ KHOÁ: ZH (đã dịch để cào Douyin) -> VN (user GÕ gốc). Hiện từ khoá = đúng tiếng Việt gốc.


def _tk_path():
    return os.path.join(DATA_DIR, "_tukhoa_vi.json")


def _tk_vi():
    global _TK_VI
    if _TK_VI is None:
        c = {}
        p = _tk_path()
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    c = json.load(f)
            except Exception:
                c = {}
        _TK_VI = c
    return _TK_VI


def _tk_luu(zh, vn):
    """Lưu cặp ZH(đã dịch)->VN(gốc) — chỉ khi zh CÓ chữ Trung + vn KHÔNG (đúng ca user gõ VN rồi dịch sang Trung).
    → filter hiện lại đúng từ khoá VN user gõ, KHỎI dịch ngược (đỡ sai nghĩa). User gõ thẳng Trung → bỏ qua (fallback dịch)."""
    zh = (zh or "").strip(); vn = (vn or "").strip()
    if not zh or not vn or not _co_cjk(zh) or _co_cjk(vn):
        return
    c = _tk_vi()
    if c.get(zh) == vn:
        return
    with _TD_VI_LOCK:
        c[zh] = vn
        try:
            with open(_tk_path(), "w", encoding="utf-8") as f:
                json.dump(c, f, ensure_ascii=False)
        except OSError:
            pass


def dich_tieu_de_vi(text):
    """Dịch tiêu đề video Trung -> ngôn ngữ đích; cache theo ngôn ngữ. Không có chữ Trung thì giữ nguyên. Lỗi mạng KHÔNG cache (để thử lại)."""
    text = (text or "").strip()
    if not text:
        return ""
    _tk = _tk_vi().get(text)     # từ khoá: ưu tiên VN GỐC user đã gõ (chuẩn nghĩa hơn dịch ngược ZH→VI)
    if _tk:
        return _tk
    lang = ngngu.target_lang()
    c = _td_vi(lang)
    if text in c:
        return c[text]
    if not _co_cjk(text):
        return text
    try:
        vi = dich_google(text, ngngu.google_code(lang), sl="zh-CN").strip()
    except Exception:
        return text
    if vi:
        with _TD_VI_LOCK:
            c[text] = vi
        return vi
    return text


def dich_tieu_de_batch(titles):
    """Dịch danh sách tiêu đề (song song + cache). Trả {tiêu đề gốc: tiếng Việt}."""
    from concurrent.futures import ThreadPoolExecutor
    lang = ngngu.target_lang()
    uniq = list(dict.fromkeys(t for t in titles if t))
    c = _td_vi(lang)
    out, can_dich = {}, []
    for t in uniq:
        if t in c:
            out[t] = c[t]
        elif not _co_cjk(t):
            out[t] = t
        else:
            can_dich.append(t)
    if can_dich:
        with ThreadPoolExecutor(max_workers=8) as ex:
            for t, vi in zip(can_dich, ex.map(dich_tieu_de_vi, can_dich)):
                out[t] = vi
        try:
            with _TD_VI_LOCK:
                d = dict(c)
            with open(_td_path(lang), "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False)
        except OSError:
            pass
    return out


_BILI_TD = None


def _bili_titles():
    """Map {video_id: tiêu đề} cho Bilibili (tên file chỉ là video.mp4, tiêu đề nằm ở jsonl)."""
    global _BILI_TD
    if _BILI_TD is None:
        import glob
        _BILI_TD = {}
        for fp in glob.glob(os.path.join(DATA_DIR, "bili", "jsonl", "*content*.jsonl")):
            try:
                with open(fp, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        d = json.loads(line)
                        vid = str(d.get("video_id") or "")
                        t = d.get("title") or d.get("desc") or ""
                        if vid and t:
                            _BILI_TD[vid] = t
            except Exception:
                pass
    return _BILI_TD


def _tieu_de_dy(name):
    """Bóc tiêu đề Douyin từ tên file <tiêu đề>_<id>.mp4 (bỏ đuôi + hậu tố _id / _bd_tmp)."""
    import re
    stem = os.path.splitext(name)[0]
    stem = re.sub(r"_(bd_)?tmp$", "", stem)
    stem = re.sub(r"_\d{4,}$", "", stem)
    return stem.strip()


def _la_video(f):
    """True nếu là file video hoàn chỉnh (bỏ file trung gian .fNNN.mp4 / .temp.mp4 của yt-dlp)."""
    f = f.lower()
    if not f.endswith(".mp4") or ".temp.mp4" in f:
        return False
    if "_slow_tmp" in f or "_bd_tmp" in f:   # file TẠM render (chậm-trước) / tải-dở bili — bị bỏ lại khi lỗi,
        return False                          # KHÔNG phải video thật → đừng liệt kê (tránh "nhân đôi" khi render fail)
    bits = f.rsplit(".", 2)
    if len(bits) == 3 and bits[1].startswith("f") and bits[1][1:].isdigit():
        return False
    return True


def dem_video(thu_muc):
    base = _videos_cua(thu_muc)
    n = 0
    for _root, _dirs, files in os.walk(base):
        n += sum(1 for f in files if _la_video(f))
    return n


def thong_ke():
    import datetime
    today = datetime.date.today()
    yest = today - datetime.timedelta(days=1)
    per = {}
    per_ngay = {}   # {ngay_iso: {nen_tang: so_video}} — cho combobox lọc theo ngày ở tab Cào ngay
    total = today_n = yest_n = 0
    for ma, info in NEN_TANG.items():
        base = _videos_cua(info["thu_muc"])
        c = 0
        for root, _d, files in os.walk(base):
            for f in files:
                if _la_video(f):
                    c += 1
                    total += 1
                    try:
                        d = datetime.date.fromtimestamp(os.path.getmtime(os.path.join(root, f)))
                        if d == today:
                            today_n += 1
                        elif d == yest:
                            yest_n += 1
                        pn = per_ngay.setdefault(d.isoformat(), {})
                        pn[ma] = pn.get(ma, 0) + 1
                    except OSError:
                        pass
        per[ma] = c
    processed = 0
    pdir = PROCESSED_DIR
    for _r, _d, files in os.walk(pdir):
        processed += sum(1 for f in files if f.lower().endswith(".mp4"))
    # % hoàn tất render = đã render / (đã render + còn lại chưa render)
    success = round(100 * processed / max(1, processed + total)) if (processed + total) else 0
    up = int(time.time() - _START_TIME)
    uptime = f"{up//3600}h {(up%3600)//60}m" if up >= 3600 else f"{up//60}m {up%60}s"
    delta = today_n - yest_n
    try:   # đang tải / lỗi: lấy từ hàng đợi render (proxy 'việc đang chạy' cho dashboard)
        dang_tai = sum(1 for x in _queue if x.get("trang_thai") in ("cho", "dang"))
        loi = sum(1 for x in _queue if x.get("trang_thai") == "loi")
    except Exception:
        dang_tai = loi = 0
    return {"da_cao": total, "hom_nay": today_n, "delta_hom_nay": delta,
            "da_render": processed, "success": success, "uptime": uptime, "per": per,
            "per_ngay": per_ngay, "dang_tai": dang_tai, "loi": loi}


# Thư mục được phép phát video (mọi nền tảng + video đã rerender) — đều dưới DATA_DIR/PROCESSED_DIR (userData)
_THU_MUC_PHAT = [PROCESSED_DIR] + [_videos_cua(info["thu_muc"]) for info in NEN_TANG.values()]

# Thư mục lưu TỰ CHỌN của user (render ra ngoài PROCESSED_DIR, vd C:\audio) — LƯU BỀN để "File đã tải"
# hiện + /video,/thumb phục vụ (trước: render ra thư mục riêng → không thấy trong tab đã tải).
_OUT_DIRS = set()
try:
    for _d in (_doc_settings().get("out_dirs") or []):
        if _d:
            _OUT_DIRS.add(os.path.normpath(_d))
except Exception:
    pass


def _them_out_dir(d):
    """Ghi nhớ thư mục lưu tự chọn (bền qua settings) để File đã tải quét + /video phục vụ.
    Bỏ qua nếu đã nằm trong DATA_DIR/PROCESSED_DIR (vốn được quét sẵn)."""
    if not d:
        return
    nd = os.path.normpath(os.path.abspath(str(d)))
    try:
        if _trong_vung(nd, PROCESSED_DIR, DATA_DIR):
            return
    except Exception:
        pass
    if nd in _OUT_DIRS:
        return
    _OUT_DIRS.add(nd)
    try:
        s = _doc_settings()
        s["out_dirs"] = sorted(_OUT_DIRS)
        _luu_settings(s)
    except Exception:
        pass


def _xoa_out_dir(d):
    """Bỏ 1 thư mục đích khỏi danh sách quét (không xoá file thật, chỉ ngừng hiện trong File đã tải)."""
    nd = os.path.normpath(os.path.abspath(str(d or "")))
    if nd in _OUT_DIRS:
        _OUT_DIRS.discard(nd)
        try:
            s = _doc_settings()
            s["out_dirs"] = sorted(_OUT_DIRS)
            _luu_settings(s)
        except Exception:
            pass

# Đoán nền tảng từ đường dẫn file
_NEN_TANG_THU_MUC = {
    "douyin": ("Douyin", "dy"), "bili": ("Bilibili", "bili"),
    "xhs": ("Xiaohongshu", "xhs"), "weibo": ("Weibo", "wb"),
    "youtube": ("YouTube", "yt"), "tiktok": ("TikTok", "tt"),
    "twitter": ("Twitter (X)", "tw"), "instagram": ("Instagram", "ig"),
    "facebook": ("Facebook", "fb"),
}


def _nen_tang_tu_path(parts):
    for seg in parts:
        if seg in _NEN_TANG_THU_MUC:
            return _NEN_TANG_THU_MUC[seg]
    return ("", "")


def liet_ke_file(gioi_han=400):
    import datetime
    items = []
    # (đường dẫn, nhãn nhóm). processed_videos = đã rerender; còn lại = cào gốc theo nền tảng
    bases = [(PROCESSED_DIR, "Đã rerender")]
    for _od in _OUT_DIRS:                       # thư mục lưu tự chọn của user → video render ra đó cũng hiện
        if os.path.isdir(_od):
            bases.append((_od, "Đã render"))
    try:                                        # FOLDER THỂ LOẠI (tự phân loại): output _xuly bị move vào đây
        _pl_muc, _pl_def = _pl_folders()        # → PHẢI quét, không thì "render nhiều chỉ thấy 1" (output ẩn)
        for _m in (_pl_muc or []):
            _p = (_m.get("path") or "").strip()
            if _p and os.path.isdir(_p) and not _trong_vung(_p, PROCESSED_DIR, DATA_DIR):
                bases.append((_p, "Đã render"))
        if _pl_def and os.path.isdir(_pl_def) and not _trong_vung(_pl_def, PROCESSED_DIR, DATA_DIR):
            bases.append((_pl_def, "Đã render"))
    except Exception:
        pass
    for info in NEN_TANG.values():
        bases.append((_videos_cua(info["thu_muc"]), "Cào gốc"))
    bases.append((os.path.join(DATA_DIR, "bam_nho"), "Băm nhỏ"))   # clip băm video NGOÀI → hiện ở File đã tải
    _seen_base = set()   # dedup: folder thể loại có thể vừa trong _OUT_DIRS vừa _pl_folders → tránh liệt kê 2 lần
    _seen_file = set()   # dedup theo FILE: base có thể LỒNG NHAU (vd _OUT_DIRS 'D:\' chứa cả data/facebook) →
                         # cùng 1 video bị os.walk 2 base khác nhau → hiện TRÙNG 2 thẻ. Chốt theo path tuyệt đối.
    for base, nhom in bases:
        if not os.path.isdir(base):
            continue
        if len(os.path.abspath(base)) <= 3:   # gốc ổ đĩa (vd "C:\") → os.walk sẽ quét CẢ Ổ = treo → BỎ QUA
            continue
        _bk = os.path.normcase(os.path.abspath(base))
        if _bk in _seen_base:
            continue
        _seen_base.add(_bk)
        for root, _d, files in os.walk(base):
            for f in files:
                if _la_video(f):
                    full = os.path.join(root, f)
                    _fk = os.path.normcase(os.path.abspath(full))
                    if _fk in _seen_file:   # đã liệt kê ở base trước (base lồng nhau) → bỏ, không trùng thẻ
                        continue
                    _seen_file.add(_fk)
                    try:
                        st = os.stat(full)
                    except OSError:
                        continue
                    rel = _rel_goc(full)
                    parts = rel.split("/")
                    loai, nhom_ten = "Khác", ""
                    if "tu-khoa" in parts:
                        i = parts.index("tu-khoa")
                        loai, nhom_ten = "Từ khóa", parts[i + 1] if i + 1 < len(parts) else ""
                    elif "kenh" in parts:
                        i = parts.index("kenh")
                        loai, nhom_ten = "Kênh", parts[i + 1] if i + 1 < len(parts) else ""
                    elif "link" in parts:
                        loai = "Link"
                    nt_ten, nt_ma = _nen_tang_tu_path(parts)
                    tg = ""
                    if nt_ma == "dy":
                        tg = _tieu_de_dy(f)
                    elif nt_ma == "bili" and len(parts) >= 2:
                        tg = _bili_titles().get(parts[-2], "")
                    items.append({"name": f, "p": rel,
                                  "mb": round(st.st_size / 1048576, 1),
                                  "phut": _thoi_luong_cache(full),   # thời lượng (phút) — cache theo mtime/size
                                  "nhom": nhom, "loai": loai, "nhom_ten": nhom_ten,
                                  "nhom_ten_vi": (_tk_vi().get(nhom_ten) or _td_vi().get(nhom_ten, "")) if nhom_ten else "",
                                  "nen_tang": nt_ten, "nen_tang_ma": nt_ma,
                                  "tieu_de_goc": tg, "ten_vi": _td_vi().get(tg, "") if tg else "",
                                  "date": datetime.date.fromtimestamp(st.st_mtime).isoformat(),
                                  "mtime": st.st_mtime})
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items[:gioi_han]


def lich_su_cao(loc_nt="", q="", chi_chua_tai=False, so_ngay=0, gioi_han=800):
    """LỊCH SỬ CÀO: gom jsonl (*_contents_*) các nền → list bài đã cào (metadata). dedup theo url||id,
    gắn cờ đã_tải (index_metadata), sort mới nhất. loc_nt=lọc nền, q=tìm (tiêu đề/kênh/từ khóa),
    so_ngay=chỉ bài cào trong N ngày gần nhất (0=tất cả)."""
    import glob as _g
    import index_metadata
    import time as _t
    q = (q or "").strip().lower()
    try:
        moc = (_t.time() - float(so_ngay) * 86400) if so_ngay and float(so_ngay) > 0 else 0
    except (TypeError, ValueError):
        moc = 0
    out, dt_cache = {}, {}
    for nt, info in NEN_TANG.items():
        if nt not in NEN_TANG_HO_TRO:   # chỉ 5 nền đang hỗ trợ
            continue
        if loc_nt and nt != loc_nt:
            continue
        leaf = info["thu_muc"].split("/")[-1]
        jdir = os.path.join(DATA_DIR, leaf, "jsonl")
        if not os.path.isdir(jdir):
            continue
        dt = dt_cache.get(nt)
        if dt is None:
            dt = _da_tai_keys(nt)   # SQLite da_tai HỢP ledger _da_tai_ids.txt (đầy đủ cả cào chính)
            dt_cache[nt] = dt
        for jf in _g.glob(os.path.join(jdir, "*_contents_*.jsonl")):
            base = os.path.basename(jf)
            loai = "Từ khóa" if base.startswith("search") else ("Kênh" if base.startswith("creator") else "Chi tiết")
            try:
                for line in open(jf, encoding="utf-8"):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    url = (d.get("video_url") or d.get("note_url") or d.get("url")
                           or d.get("aweme_url") or d.get("share_url") or "").strip()
                    vid = str(d.get("video_id") or d.get("note_id") or d.get("aweme_id") or d.get("id") or "")
                    # Dựng URL từ id nếu jsonl không có field url (vd Douyin lưu 'aweme_url'; bili/xhs nhiều
                    # bản thiếu url) → nút "Tải" lẻ (gọi /api/crawl type=post theo URL) mới hoạt động + tải VIDEO.
                    if not url and vid:
                        if nt == "dy":
                            url = "https://www.douyin.com/video/" + vid
                        elif nt == "bili":
                            url = "https://www.bilibili.com/video/" + str(d.get("bvid") or vid)
                        elif nt == "xhs":
                            url = "https://www.xiaohongshu.com/explore/" + vid
                    key = url or vid
                    if not key:
                        continue
                    title = (d.get("title") or d.get("desc") or "").strip()
                    nick = (d.get("nickname") or "").strip()
                    kw = (d.get("source_keyword") or "").strip()
                    ts = int(d.get("last_modify_ts") or 0) or int(d.get("create_time") or 0)
                    if ts > 1e12:                # ms → s
                        ts = int(ts / 1000)
                    if moc and ts and ts < moc:  # lọc N ngày gần nhất
                        continue
                    da_tai = (url in dt) or (vid in dt)
                    if chi_chua_tai and da_tai:
                        continue
                    if q and (q not in title.lower()) and (q not in nick.lower()) and (q not in kw.lower()):
                        continue
                    o = out.get(key)
                    if (not o) or ts > o.get("ts", 0):
                        out[key] = {"key": key, "nt": nt, "nt_ten": info["ten"], "loai": loai,
                                    "title": title, "nick": nick, "kw": kw, "url": url,
                                    "kw_vi": (_tk_vi().get(kw) or _td_vi().get(kw, "")) if kw else "",
                                    "nick_vi": _td_vi().get(nick, "") if nick else "",
                                    "cover": (d.get("video_cover_url") or d.get("cover_url") or ""),
                                    "ts": ts, "da_tai": da_tai}
            except OSError:
                continue
    items = sorted(out.values(), key=lambda x: x["ts"], reverse=True)
    return items[:gioi_han]


def _ten_kenh_goc(nhom_ten):
    """Bỏ phần ' (English)' ở cuối tên thư mục kênh để khớp với nickname."""
    import re
    return re.sub(r"\s*\([^()]*\)\s*$", "", nhom_ten or "").strip()


def _nguon_avatar():
    """Danh sách (đường dẫn) các file nguồn avatar, theo thứ tự ƯU TIÊN xử lý (setdefault giữ cái đầu).
    creator_creators (avatar gốc 300x300 không hết hạn) > theo dõi > gợi ý > contents > search; mới nhất trước."""
    import glob
    dj = lambda ten: sorted(glob.glob(os.path.join(DATA_DIR, "*", "jsonl", ten)), reverse=True)
    paths = dj("creator_creators_*.jsonl")          # tốt nhất: 300x300, không hết hạn
    paths += [FILE_TD]                               # danh sách theo dõi của người dùng
    paths += sorted(glob.glob(os.path.join(THU_MUC_CRAWLER, "data", "*", "_goi_y_kenh.json")))
    paths += dj("creator_contents_*.jsonl") + dj("search_contents_*.jsonl")  # 100x100, có thể hết hạn
    return paths


def _secuid_tu_link(link):
    """sec_uid douyin từ link dạng .../user/<sec_uid>. '' nếu không phải link kênh douyin."""
    import re
    m = re.search(r"/user/([A-Za-z0-9_-]+)", link or "")
    return m.group(1) if m else ""


_avatar_cache = {"sig": None, "map": {}, "smap": {}}


def avatar_kenh_map():
    """Gom {nickname: avatar} từ theo dõi + cache gợi ý + JSONL crawler.
    Có cache theo chữ ký mtime để khỏi đọc lại toàn bộ JSONL mỗi request."""
    paths = _nguon_avatar()
    try:
        sig = tuple((p, os.path.getmtime(p)) for p in paths if os.path.exists(p))
    except OSError:
        sig = None
    if sig is not None and sig == _avatar_cache["sig"]:
        return _avatar_cache["map"]

    m, ms = {}, {}

    def them(c):  # setdefault: nguồn ưu tiên cao (xử lý trước) sẽ thắng
        if not (isinstance(c, dict) and c.get("avatar")):
            return
        if c.get("nickname"):
            m.setdefault(c["nickname"], c["avatar"])
        sid = c.get("user_id") or c.get("sec_uid") or c.get("sec_user_id") or _secuid_tu_link(c.get("link", ""))
        if sid:
            ms.setdefault(sid, c["avatar"])   # khớp theo sec_uid cho Video mới (kenh có thể là tên đã dịch)

    for p in paths:  # đã sắp theo thứ tự ưu tiên trong _nguon_avatar()
        try:
            if p == FILE_TD:                       # JSON: {"creators": [...]}
                for c in doc_json(FILE_TD, {}).get("creators", []):
                    them(c)
            elif p.endswith(".json"):              # JSON: [ {...}, ... ]
                with open(p, encoding="utf-8") as f:
                    for c in json.load(f):
                        them(c)
            else:                                  # JSONL: mỗi dòng 1 bản ghi
                with open(p, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            them(json.loads(line))
                        except Exception:
                            continue
        except Exception:
            pass
    _avatar_cache["sig"], _avatar_cache["map"], _avatar_cache["smap"] = sig, m, ms
    return m


def avatar_secuid_map():
    """{sec_uid: avatar} — Video mới khớp avatar theo sec_uid (vì 'kenh' có thể là tên ĐÃ DỊCH, không khớp nickname)."""
    avatar_kenh_map()   # build/refresh cache (m + ms cùng 1 lượt)
    return _avatar_cache.get("smap", {})


def kenh_avatar_theo_folder(files):
    """Map {nhom_ten (tên thư mục kênh): avatar} cho các kênh có trong danh sách file."""
    amap = avatar_kenh_map()
    out = {}
    for f in files:
        nt = f.get("nhom_ten")
        if f.get("loai") == "Kênh" and nt and nt not in out:
            av = amap.get(_ten_kenh_goc(nt)) or amap.get(nt)
            if av:
                out[nt] = av
    return out


def _doi_ten_video(full, ten_raw):
    """Đổi tên 1 video (đường dẫn ĐÃ resolve/whitelist) + sidecar (.vi.srt/.zh.srt/.txt) cùng gốc theo tên mới.
    Trả (ok, msg_hoặc_rel, name)."""
    ten_moi = _pl_safe_ten(ten_raw or "")
    if not ten_moi:
        return False, "Tên không hợp lệ.", ""
    d = os.path.dirname(full)
    ext = os.path.splitext(full)[1]
    dest = os.path.join(d, ten_moi + ext)
    if os.path.abspath(dest) == os.path.abspath(full):
        return True, _rel_goc(dest), os.path.basename(dest)
    if os.path.exists(dest):
        return False, "Đã có video tên này trong cùng thư mục.", ""
    try:
        import re as _re_rn
        # .srt sidecar đặt tên KHÔNG kèm hậu tố biến thể (_xuly/_phude/_longtieng) — xem
        # tao_caption.srt_cua_video(); phải bỏ hậu tố này mới khớp đúng file srt thật.
        stem_cu = _re_rn.sub(r"(_longtieng|_phude|_xuly|_bd_tmp)$", "",
                             os.path.splitext(os.path.basename(full))[0], flags=_re_rn.IGNORECASE)
        os.rename(full, dest)
        for hau_to in (".vi.srt", ".zh.srt", ".txt"):
            side = os.path.join(d, stem_cu + hau_to)
            if os.path.isfile(side):
                try:
                    os.rename(side, os.path.join(d, ten_moi + hau_to))
                except OSError:
                    pass
        return True, _rel_goc(dest), os.path.basename(dest)
    except Exception as e:
        return False, str(e), ""


_ghep_dang_chay = {}   # ten_moi -> {"trang_thai": "chay"|"xong"|"loi", "msg": str} — trạng thái ghép video (poll)


def _ghep_video_batch_worker(paths, nhom, ten_goc, log=None):
    """Chia `paths` (ĐÚNG thứ tự đã chọn) thành từng NHÓM `nhom` video liên tiếp → ghép mỗi nhóm thành 1 TẬP
    (chạy TUẦN TỰ, tránh nhiều ffmpeg tranh CPU cùng lúc). Đặt tên tự động '<ten_goc> Tập 1'…'Tập M'
    (M = ceil(len(paths)/nhom)). nhom=1 → mỗi video giữ nguyên thành 1 tập riêng (chỉ đổi định dạng/tên)."""
    log = log or them_log
    nhom = max(1, int(nhom or 1))
    nhoms = [paths[i:i + nhom] for i in range(0, len(paths), nhom)]
    log(f"🎞️ Bắt đầu ghép {len(paths)} video → {len(nhoms)} tập ({nhom} video/tập)...")
    for idx, g in enumerate(nhoms, 1):
        # Ghép thành 1 TẬP duy nhất → dùng TÊN MỚI trực tiếp (không thêm "Tập 1" thừa).
        # Nhiều tập → mới đánh số "Tập N" để phân biệt.
        ten_tap = ten_goc if len(nhoms) == 1 else f"{ten_goc} Tập {idx}"
        _ghep_video_worker(g, ten_tap, log=log)
    log(f"✔ Xong toàn bộ: {len(nhoms)} tập.")


def _ghep_video_worker(paths, ten_moi, log=None):
    """Ghép NHIỀU video ĐÃ RENDER thành 1 video dài (đúng THỨ TỰ paths), theo tập phim. Chuẩn hoá về kích thước
    video ĐẦU TIÊN (scale+pad, giữ tỉ lệ, không méo) + fps 30 trước khi nối — an toàn khi các video khác độ phân
    giải/tỉ lệ khung (khác nguồn/khác lần render). Output PROCESSED_DIR/khac/<ten_moi>.mp4 (GPU NVENC nếu có)."""
    log = log or them_log
    import xu_ly_video as xlv
    _ghep_dang_chay[ten_moi] = {"trang_thai": "chay", "msg": "Đang ghép…"}
    try:
        cfg = xlv.tu_tim_ffmpeg(xlv.nap_config())
        if not xlv.kiem_tra_ffmpeg(cfg):
            raise RuntimeError("Không tìm thấy ffmpeg.")
        w, h = xlv.lay_kich_thuoc(cfg, paths[0])
        if not w or not h:
            raise RuntimeError("Không đọc được kích thước video đầu tiên.")
        dest_dir = os.path.join(PROCESSED_DIR, "khac")
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, ten_moi + ".mp4")
        n = 2
        while os.path.exists(dest):
            dest = os.path.join(dest_dir, "%s (%d).mp4" % (ten_moi, n)); n += 1
        cmd = [cfg["ffmpeg_path"], "-y"]
        for pth in paths:
            cmd += ["-i", pth]
        parts = []
        cat_in = ""
        for i in range(len(paths)):
            parts.append(
                "[%d:v]scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2,"
                "setsar=1,fps=30[v%d]" % (i, w, h, w, h, i))
            cat_in += "[v%d][%d:a]" % (i, i)
        filter_complex = ";".join(parts) + ";%sconcat=n=%d:v=1:a=1[outv][outa]" % (cat_in, len(paths))
        cmd += ["-filter_complex", filter_complex, "-map", "[outv]", "-map", "[outa]"]
        cmd += xlv._enc_args(cfg) + ["-c:a", "aac", "-b:a", "192k", dest]
        log(f"🎞️ Đang ghép {len(paths)} video thành '{ten_moi}.mp4' (có thể mất vài phút)...")
        kq = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                            creationflags=_NO_WINDOW, timeout=3600)
        if kq.returncode != 0 or not os.path.isfile(dest):
            raise RuntimeError((kq.stderr or "")[-400:] or "ffmpeg lỗi không rõ nguyên nhân.")
        log(f"✔ Đã ghép xong: {os.path.basename(dest)}")
        _ghep_dang_chay[ten_moi] = {"trang_thai": "xong", "msg": os.path.basename(dest)}
    except Exception as e:
        log(f"⚠ Ghép video lỗi: {str(e)[:200]}")
        _ghep_dang_chay[ten_moi] = {"trang_thai": "loi", "msg": str(e)[:200]}


def _resolve_video(rel):
    """Giải đường dẫn an toàn, chỉ cho phép trong thư mục video (hoặc thư mục băm nhỏ / file nguồn đã đăng ký)."""
    full = os.path.normpath(os.path.join(THU_MUC_GOC, rel))
    if os.path.normcase(os.path.abspath(full)) in _bam_serve_files and os.path.isfile(full):
        return full   # file nguồn đăng ký riêng lẻ (H2) — không cần mở cả thư mục cha
    for base in list(_THU_MUC_PHAT) + list(_bam_serve_dirs) + list(_OUT_DIRS) + [os.path.join(DATA_DIR, "bam_nho")]:
        nb = os.path.normpath(base)
        try:
            if os.path.commonpath([nb, full]) == nb and os.path.isfile(full):
                return full
        except ValueError:        # khác ổ đĩa -> commonpath ném lỗi, bỏ qua base này
            continue
    return None


def _nen_tang_seg_tu_path(full):
    """Đoán SEG nền tảng (douyin/bili/xhs...) từ ĐƯỜNG DẪN video trong DATA_DIR → gom render về
    processed_videos/<nền tảng>/ (mặc định khi TẮT phân loại). Không đoán được → ''.
    LƯU Ý: KHÁC `_nen_tang_tu_path(parts)` (nhận LIST, trả tuple (ten,ma) cho listing) — trước đây
    2 hàm TRÙNG TÊN khiến cái sau đè cái trước → /api/files 500 (TypeError abspath(list))."""
    try:
        rel = os.path.relpath(os.path.abspath(full), DATA_DIR).replace("\\", "/")
    except (ValueError, OSError):
        return ""
    seg = rel.split("/")[0]
    return seg if (seg and not seg.startswith("..")) else ""


# ----------------- Crawl -----------------
DIA_NGUONG_GB = 5.0   # còn dưới mức này -> cảnh báo nguy cơ hết chỗ khi cào/render (KHÔNG chặn)


def _canh_bao_dia(path=None, viec="cào/tải"):
    """Cảnh báo qua log (KHÔNG chặn) khi ổ chứa `path` còn < DIA_NGUONG_GB. Trả số GB còn (None nếu lỗi)."""
    try:
        free_gb = shutil.disk_usage(path or THU_MUC_GOC).free / (1024 ** 3)
    except Exception:
        return None
    if free_gb < DIA_NGUONG_GB:
        them_log(f"⚠ Ổ đĩa chỉ còn {free_gb:.1f} GB (< {DIA_NGUONG_GB:.0f} GB) — {viec} có thể THẤT BẠI do hết chỗ. "
                 "Hãy dọn ổ đĩa hoặc đổi nơi lưu.")
    return free_gb


# Tiến độ cào HIỆN HÀNH (1 crawl/lúc) → để task worker hiển thị "📊 N/M · MB/s · còn ~Zm" + % lên task.
# _eta_log (trong _crawl_worker) cập nhật; _task_worker đọc. Mutate dict (KHÔNG reassign) → khỏi global.
_tien_do_cao = {"msg": "", "pct": 0}
# "Dừng sau task này" (Stop-After-Current): worker hoàn tất task ĐANG chạy rồi KHÔNG lấy task mới (queue tạm
# nghỉ, KHÔNG kill gì) — an toàn tuyệt đối. Mutate dict → khỏi global trong do_POST.
_task_pause = {"on": False}


def chay_crawl(cfg):
    global _proc, _dang_cao
    # CHỐT CHẶN quota/tier DÙNG CHUNG cho MỌI đường cào (/api/crawl, /api/task/add→_task_worker,
    # /api/lich_run, ...). Trước đây chỉ /api/crawl canh -> các đường khác LỌT (expired/free cào vô hạn).
    # Đặt ở đây phủ hết. pro/unlimited: _lim("cao_ngay")=None -> KHÔNG đổi hành vi cũ. Đặt TRƯỚC busy-guard
    # để không phải hoàn tác cờ _dang_cao khi bị chặn.
    _gx = _guard_expired("cao")
    if _gx:
        return _gx
    _ghn = _lim("cao_ngay")
    if _ghn is not None:
        _conlai = _ghn - kdb.usage_lay("cao")
        if _conlai <= 0:
            return _block("cao", f"Đã đạt giới hạn cào {_ghn} video/ngày của gói {TIER.upper()}. Nâng cấp để cào không giới hạn.")
        try:
            if int(str(cfg.get("count") or "10")) > _conlai:
                cfg["count"] = str(_conlai)   # cắt theo quota còn lại (áp cho cả task/lịch)
        except Exception:
            pass
    _ban = "Đang có tác vụ cào/xử lý đang chạy. Dừng nó để cào cái mới?"
    with _crawl_lock:
        ban_ron = _proc is not None or _dang_cao
    if ban_ron:
        if not cfg.get("force"):
            return {"ok": False, "busy": True, "msg": _ban}
        dung_crawl()                       # đổi ý → dừng lệnh cũ rồi cào mới
        for _ in range(50):                # đợi tiến trình cũ thoát (tối đa ~5s)
            if _proc is None and not _dang_cao:
                break
            time.sleep(0.1)
    # CỬA SỔ LƯỚT (nút 👁) đang mở GIỮ KHÓA profile-cào → cào headless nền đó sẽ mở KHÔNG được profile
    # (1 profile = 1 tiến trình) → 'chưa đăng nhập'/lỗi. Chặn TRƯỚC, nhắc user đóng (không tự đóng cửa sổ
    # họ đang lướt/lấy link). rednote/xhs chung nhánh nhưng profile riêng → check đúng nền đang cào.
    _nt_cao = cfg.get("platform", "dy")
    if cua_so_luot_dang_mo(_nt_cao):
        return {"ok": False, "browse_open": True, "plat": _nt_cao,
                "msg": f"Cửa sổ lướt {_nt_cao.upper()} đang mở (đang giữ trình duyệt). Hãy ĐÓNG cửa sổ đó rồi cào lại."}
    # GIỮ CHỖ đồng bộ NGAY (trong lock) trước khi tạo thread → bấm Cào 2 lần nhanh không lọt 2 tiến trình.
    with _crawl_lock:
        if _proc is not None or _dang_cao:
            return {"ok": False, "busy": True, "msg": _ban}
        _dang_cao = True
    _canh_bao_dia(viec="cào/tải video")   # ổ chứa data/ sắp đầy -> cảnh báo trước khi cào
    nt = cfg.get("platform", "dy")
    che_do = cfg.get("type", "search")
    if che_do == "post":          # 'Tải lại từ lịch sử' (lsTaiLai) gửi type=post = tải 1 video theo LINK
        che_do = "detail"         # MediaCrawler dispatch CHỈ nhận search/detail/creator — 'post' không khớp
                                  # nhánh nào → KHÔNG cào gì → '0 video' oan (cả Douyin LẪN Bilibili). detail = đúng.
    noi_dung = cfg.get("input", "").strip()
    so = str(cfg.get("count", "10"))

    # TỰ NHẬN URL TÌM KIẾM Douyin (dán vào ô Kênh/Link/Từ khóa đều được): douyin.com/search/<từ-khóa>?...&modal_id=...
    # Đây KHÔNG phải link kênh (không có /user/<sec_uid>) → 'Theo kênh' sẽ lỗi. → Tách TỪ KHÓA từ path /search/ +
    # ép mode 'search' → cào CẢ kết quả tìm kiếm. (Muốn CHỈ 1 video đang mở trong search → dùng 'Theo link': mode
    # detail đọc modal_id qua help.parse_video_info_from_url.)
    if nt == "dy" and "douyin.com" in noi_dung and "/search/" in noi_dung:
        import urllib.parse as _up_s
        _m_kw = _re.search(r"/search/([^/?#]+)", noi_dung)
        if _m_kw:
            _kw = _up_s.unquote(_m_kw.group(1)).strip()
            if _kw:
                che_do, noi_dung = "search", _kw
                them_log("🔎 Nhận URL tìm kiếm Douyin → cào theo TỪ KHÓA '%s' (cả kết quả tìm kiếm)." % _kw)

    # YouTube / TikTok -> dùng yt-dlp (module riêng)
    if nt in NEN_TANG_YTDLP:
        lenh = [PYTHON_VENV, "tai_ytdlp.py", "--platform", nt, "--type", che_do,
                "--input", noi_dung, "--count", so]
        ck = (cfg.get("cookies") or "").strip()
        ckb = (cfg.get("cookies_browser") or "").strip()
        if ck:
            lenh += ["--cookies", ck]
        elif ckb:
            lenh += ["--cookies-browser", ckb]
        # X/IG: không truyền cookie thủ công -> tai_ytdlp tự lấy từ phiên đăng nhập (mo_dang_nhap)
        them_log(f"▶ Bắt đầu tải {NEN_TANG.get(nt, {}).get('ten', nt)} — {che_do}")
        env = os.environ.copy()
        env["TARGET_LANG"] = ngngu.target_lang()
        threading.Thread(target=_crawl_worker, args=(lenh, env, THU_MUC_GOC),
                         daemon=True).start()
        return {"ok": True}

    # ĐÃ có "Xem trước & chọn" (preview) -> bước CÀO chạy headless HOÀN TOÀN (không hiện cửa sổ trình duyệt).
    # Đăng nhập nền tảng làm riêng qua mo_dang_nhap.py (headless=False, hiện QR) nên cào không cần cửa sổ.
    headless = "yes"
    env = os.environ.copy()
    env["TARGET_LANG"] = ngngu.target_lang()
    nt_mc = _ap_alias_env(env, nt)   # rednote → --platform xhs + cờ quốc tế/profile/data RIÊNG
    # "Cào KHÔNG TRÙNG" (đào sâu) → cào tới đủ N video CHƯA tải (bỏ qua đã tải, đào trang sâu hơn) thay vì N/10
    # trang. Douyin: search+creator; Bilibili: search (deep ở core.search; creator bili chưa hỗ trợ deep).
    # Đào sâu = nhiều request hơn = rủi ro anti-bot cao hơn (có trần MC_DEEP_PAGE_CAP).
    _deep_ok = bool(cfg.get("khong_trung")) and (
        (nt == "dy" and che_do in ("search", "creator")) or
        (nt == "bili" and che_do == "search"))
    if _deep_ok:
        env["MC_DEEP_NEW"] = "1"
        them_log("🆕 Cào KHÔNG TRÙNG: đào sâu tới khi đủ video MỚI (bỏ qua video đã tải)")
    lenh = [PYTHON_VENV, "main.py", "--platform", nt_mc, "--lt", "qrcode",
            "--get_comment", "no", "--save_data_option", "jsonl",
            "--headless", headless, "--type", che_do]
    if che_do == "search":
        lenh += ["--keywords", noi_dung.replace("\n", ","), "--crawler_max_notes_count", so]
        env["DY_SORT_TYPE"] = str(cfg.get("sort", 0))
        env["DY_PUBLISH_TIME"] = str(cfg.get("publish_time", 0))
    elif che_do == "detail":
        # tách MỌI khoảng trắng/dòng/phẩy (link KHÔNG có space) → dán nhiều link 1 dòng/cách-space vẫn tách đúng
        links = [l.strip() for l in _re.split(r"[\s,]+", noi_dung) if l.strip()]
        lenh += ["--specified_id", ",".join(links)]
    else:
        links = [l.strip() for l in _re.split(r"[\s,]+", noi_dung) if l.strip()]   # nhiều link kênh: tách cả space
        lenh += ["--creator_id", ",".join(links), "--crawler_max_notes_count", so]
        env["DY_CREATOR_SORT"] = cfg.get("creator_sort", "newest")

    them_log(f"▶ Bắt đầu cào {NEN_TANG.get(nt, {}).get('ten', nt)} — {che_do}")
    threading.Thread(target=_crawl_worker, args=(lenh, env), daemon=True).start()
    return {"ok": True}


def _crawl_worker(lenh, env, cwd=None, dub_phut=0, dub_out=""):
    global _proc, _dang_cao
    _dub_t0 = time.time()   # mốc để nhận biết file lồng tiếng VỪA tạo (đếm quota chỉ khi render mới, không tính cache)
    _tien_do_cao["msg"] = ""; _tien_do_cao["pct"] = 0    # reset tiến độ cho lượt cào mới
    da_luu = 0        # số video tải thành công THẬT → biết cào có ra gì không (tránh báo "Hoàn tất" giả khi 0 video)
    loi_fetch = ""    # "" | "fetch" (nền tảng từ chối/phiên hết hạn) | "ip" (anti-bot chặn IP)
    plat_lr = ""      # nền tảng (suy từ lệnh) → cào 0 video thì XÁC MINH LẠI đăng nhập nền tảng đó
    try:
        if "--platform" in lenh:
            plat_lr = lenh[lenh.index("--platform") + 1]
    except Exception:
        plat_lr = ""
    so_detail = 0     # số bài đang lấy chi tiết (xhs) — để hiện tiến trình + phát hiện treo
    last_t = time.time()              # mốc HOẠT ĐỘNG cuối (có dòng log mới) cho watchdog
    wd = {"warned": False, "stop": False}
    def _watchdog():
        # Xiaohongshu hay treo ở khâu lấy chi tiết (feed bị anti-bot) → request đợi hết timeout × retry lồng
        # → user nhìn 0% hàng chục phút tưởng đơ. Watchdog: im lặng >90s mà CHƯA tải được video nào → báo SỚM.
        while not wd["stop"]:
            time.sleep(10)
            if wd["stop"] or wd["warned"] or da_luu > 0:
                continue
            if so_detail > 0 and (time.time() - last_t) > 90:
                wd["warned"] = True
                them_log("⏳ Xiaohongshu phản hồi rất chậm ở khâu lấy chi tiết bài (thường do anti-bot chặn feed). "
                         "Có thể bấm ⛔ Dừng rồi: giảm số lượng, thử lại sau ít phút, hoặc dùng Douyin/YouTube (ổn định hơn).")
    # --- ƯỚC TÍNH THỜI GIAN TẢI: tốc độ (MB/s, từ file mới tải) + số video (count target) → còn ~bao lâu ---
    _eta_t0 = time.time()
    _eta_last = [0.0]
    _eta_target = 0
    for _k in ("--count", "--crawler_max_notes_count"):
        if _k in lenh:
            try:
                _eta_target = int(lenh[lenh.index(_k) + 1]); break
            except (ValueError, IndexError):
                pass
    _eta_dir = None
    try:
        _tm = NEN_TANG.get(plat_lr, {}).get("thu_muc")
        if _tm:
            _eta_dir = _videos_cua(_tm)
    except Exception:
        pass

    def _eta_fmt(sec):
        sec = int(sec)
        if sec < 60:
            return "%d giây" % sec
        if sec < 3600:
            return "%d phút" % round(sec / 60.0)
        return "%.1f giờ" % (sec / 3600.0)

    def _eta_log(xong=False):
        if da_luu <= 0:
            return
        now = time.time()
        if not xong and (now - _eta_last[0]) < 4.0:     # throttle ~4s tránh spam log
            return
        _eta_last[0] = now
        el = max(0.5, now - _eta_t0)
        mb = 0.0
        if _eta_dir and os.path.isdir(_eta_dir):         # tổng MB các file MỚI (mtime >= lúc bắt đầu cào)
            try:
                for _r, _, _fs in os.walk(_eta_dir):
                    for _f in _fs:
                        if _f.lower().endswith((".mp4", ".webm", ".mkv")):
                            try:
                                _st = os.stat(os.path.join(_r, _f))
                                if _st.st_mtime >= _eta_t0 - 3:
                                    mb += _st.st_size
                            except OSError:
                                pass
            except Exception:
                pass
        mb /= 1048576.0
        spd = mb / el
        msg = "📊 Đã tải %d%s video · %.0f MB" % (da_luu, ("/%d" % _eta_target if _eta_target else ""), mb)
        if spd >= 0.05:
            msg += " · %.1f MB/s" % spd
        if _eta_target and da_luu < _eta_target:         # còn lại = (mục tiêu - đã tải) × thời-gian-trung-bình/video
            msg += " · còn ~%s" % _eta_fmt((_eta_target - da_luu) * (el / da_luu))
        them_log(msg)
        _tien_do_cao["msg"] = msg                         # publish cho task worker (hiển thị tiến độ lên task)
        _tien_do_cao["pct"] = int(da_luu * 100 / _eta_target) if _eta_target else 0
    try:
        _proc = subprocess.Popen(lenh, cwd=cwd or THU_MUC_CRAWLER, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                 errors="replace", creationflags=_NO_WINDOW, env=env)
        _dang_cao = False    # đã có _proc THẬT → nhả cờ giữ chỗ (busy-guard giờ dựa vào _proc)
        threading.Thread(target=_watchdog, daemon=True).start()
        for dong in _proc.stdout:
            d = dong.strip()
            low = d.lower()
            last_t = time.time()   # có dòng log mới → còn sống (reset đồng hồ treo)
            # --- Nền tảng TỪ CHỐI request: MediaCrawler in traceback DataFetchError/RetryError/IPBlockError
            #     hoặc captcha/未登录/登录已过期 (xhs hay gặp). Bắt sớm → KHÔNG echo traceback thô ra UI;
            #     ghi nhận loại lỗi để tổng kết bằng thông báo thân thiện. (RetryError chứa 'state=finished'
            #     nên nếu không chặn ở đây sẽ lọt qua nhánh 'finished' bên dưới → in nguyên traceback.) ---
            if any(k in d for k in ("DataFetchError", "RetryError", "IPBlockError")) \
               or any(k in low for k in ("captcha", "verifytype", "未登录", "登录已过期", "登录失效")):
                if not loi_fetch:
                    loi_fetch = "ip" if ("ipblock" in low or "300012" in d or "network connection error" in low) else "fetch"
                continue
            # --- Cào KHÔNG có phiên đăng nhập hợp lệ: MediaCrawler pong() fail -> login_obj.begin() chạy.
            #     Cào chạy headless (--headless yes) KHÔNG hiện được QR -> login chắc chắn fail -> 0 video.
            #     Thẻ trạng thái có thể vẫn XANH vì cookie CŨ còn trên đĩa nhưng đã HẾT HẠN (pong từ chối).
            #     Bắt marker login (dy/bili/xhs/wb) -> báo RÕ "đăng nhập lại" thay vì generic mơ hồ. ---
            if not loi_fetch and any(k in d for k in (
                    "Login.begin]", "login_by_qrcode", "popup_login_dialog",
                    "login dialog box does not pop up", "login qrcode not found")):
                loi_fetch = "login"
                continue
            # --- NỀN TẢNG từ chối / trả RỖNG (Douyin trả [] ngay trang đầu hoặc 风控) = KHÔNG phải lỗi tool.
            #     Phân biệt với "login"/"fetch": ở đây request THÀNH CÔNG nhưng nền tảng cố tình trả 0 kết quả. ---
            if not loi_fetch and ("DOUYIN_EMPTY_RESULT" in d or "风控" in d):
                loi_fetch = "platform"
                continue
            if d.startswith("LOG:"):       # yt-dlp (YouTube/TikTok) đã in sẵn dòng tiến trình
                them_log(d[4:].strip())
            elif d.startswith("YTDLP_DONE"):   # yt-dlp xong: cộng theo SỐ video tải thành công THẬT
                try:
                    _n = int(d.split()[1])
                    if _n > 0:
                        da_luu += _n
                        _eta_log()
                        kdb.usage_cong("cao", _n)   # limit cào tính theo video tải về máy
                except Exception:
                    pass
            elif "success" in low and ("save video" in low or "save_video" in low):
                # Douyin log "save video ... success" (cách); Bilibili log "save save_video ... success"
                # (gạch dưới) → khớp CẢ 2 (trước chỉ bắt "save video" → bili tải OK nhưng đếm 0 = báo sai).
                da_luu += 1
                them_log("✔ Đã tải 1 video")
                _eta_log()
                try:
                    kdb.usage_cong("cao", 1)        # 1 video tải thành công về máy = +1 vào limit cào
                except Exception:
                    pass
            elif "Đang tải video:" in d:   # tiến trình tải video LỚN (bili tải theo khối) -> hiện % cho user biết ĐANG tải, không tưởng treo
                them_log("📥 " + d[d.find("Đang tải video:"):])
            elif "begin get note detail" in low:   # xhs lấy chi tiết — GOM 1 dòng, KHÔNG spam từng note_id
                so_detail += 1
                if so_detail == 1:
                    them_log("🔍 Đang lấy chi tiết từng bài để tải video (Xiaohongshu có thể chậm do anti-bot)...")
            elif "save_creator" in d or "Begin get" in d or "search douyin keyword" in low:
                them_log(d[:160])
            elif "đã tải trước đó" in low or ("finished" in low and "error" not in low and "future" not in low):
                them_log(d[:160])
            elif "error" in low and "403" in d:
                them_log("⚠ 1 video lỗi 403 (bỏ qua)")
        _proc.wait()
        wd["stop"] = True
        _eta_log(xong=True)   # tổng kết tốc độ + MB sau khi cào xong
        # --- Tổng kết THẬT: phân biệt cào ra video vs 0 video + có lỗi (không báo "Hoàn tất" giả) ---
        if da_luu == 0 and loi_fetch == "login":
            them_log("❌ Phiên đăng nhập nền tảng đã HẾT HẠN hoặc chưa đăng nhập — lúc cào hệ thống thử mở đăng nhập nhưng chạy NGẦM nên không quét được mã QR → 0 video. "
                     "Hãy bấm 'Đăng nhập' nền tảng, ĐỢI vào đúng trang chủ rồi mới đóng cửa sổ, sau đó cào lại. "
                     "(Thẻ trạng thái có thể vẫn XANH do cookie cũ còn trên máy — cứ đăng nhập lại để làm mới.)")
        elif da_luu == 0 and loi_fetch == "ip":
            them_log("⛔ Nền tảng tạm chặn truy cập (cào quá nhanh / anti-bot). Nghỉ vài phút, tắt VPN hoặc đổi mạng, giảm số lượng rồi thử lại.")
        elif da_luu == 0 and loi_fetch == "fetch":
            them_log("❌ Không lấy được dữ liệu — phiên đăng nhập có thể đã HẾT HẠN hoặc nền tảng từ chối. Hãy ĐĂNG NHẬP LẠI nền tảng (đợi vào trang chủ rồi mới đóng) và thử lại.")
        elif da_luu == 0 and loi_fetch == "platform":
            them_log("⚠ Nền tảng trả 0 kết quả — ĐÂY KHÔNG PHẢI LỖI TOOL. Douyin tạm từ chối: phiên đăng nhập cần làm mới, HOẶC bị anti-bot/giới hạn tần suất sau khi cào nhiều. "
                     "Hãy: đăng nhập lại Douyin (đợi vào trang chủ rồi mới đóng) · ĐỢI 5-10 phút rồi cào lại · giảm số lượng/tần suất · hoặc đổi mạng/tắt VPN.")
        elif da_luu == 0 and so_detail > 0 and plat_lr in ("xhs", "rednote"):
            # XEM TRƯỚC RA BÀI (browser DOM-scrape né được 风控) nhưng CÀO 0 video (API lấy chi tiết/tải media bị chặn).
            # Đã verify THẬT: account rednote "cứng" (dùng lâu) cào creator+search ĐỀU RA video → 0 video ở đây gần
            # như luôn do TÀI KHOẢN RedNote/Xiaohongshu MỚI TẠO bị nền tảng hạn chế (风控): cho XEM, chặn CÀO.
            them_log("⚠ Xem trước thấy bài nhưng KHÔNG cào được video nào — thường do TÀI KHOẢN RedNote/Xiaohongshu MỚI TẠO bị nền tảng hạn chế (风控: cho xem, chặn tải). "
                     "Cách xử lý: dùng tài khoản đã hoạt động MỘT THỜI GIAN (đăng nhập lâu, có tương tác) — tài khoản mới cần 'nuôi' vài ngày mới cào ổn · giảm số lượng · thử lại sau ít phút · hoặc đổi nền tảng (Douyin/YouTube ổn định hơn).")
        elif da_luu == 0 and so_detail > 0:
            them_log("⚠ Tìm thấy bài nhưng KHÔNG tải được video nào — Xiaohongshu chặn khâu lấy chi tiết (anti-bot) hoặc bài không có video. Thử lại sau / giảm số lượng / đổi nền tảng (Douyin, YouTube ổn định hơn).")
        elif da_luu == 0 and plat_lr in ("yt", "tt", "fb"):
            # yt-dlp (YouTube/TikTok/Facebook công khai) KHÔNG dùng phiên đăng nhập/anti-bot kiểu MediaCrawler
            # → KHÔNG báo "phiên đăng nhập cần làm mới" (gây hiểu nhầm). 0 video ở đây thường do: video RẤT DÀI
            # (phim/live vài giờ → tải quá lâu chưa xong), video riêng tư/đã xóa/chặn khu vực/giới hạn tuổi,
            # hoặc link sai. (Reproduce: link video 2h20 → tải lâu → tưởng '0 video'.)
            them_log("⚠ KHÔNG tải được video nào — KHÔNG phải lỗi tool, cũng KHÔNG phải đăng nhập. Thường do: video QUÁ DÀI (phim/live vài giờ tải rất lâu — đợi thêm), hoặc video riêng tư / đã xóa / chặn khu vực / giới hạn tuổi, hoặc link sai. Kiểm tra lại link, thử video khác, hoặc đợi nếu video dài.")
        elif da_luu == 0:
            them_log("⚠ KHÔNG tải được video nào — thường do NỀN TẢNG (phiên đăng nhập cần làm mới, hoặc nền tảng tạm giới hạn/anti-bot), KHÔNG phải lỗi tool. Kiểm tra đăng nhập, đổi/giảm từ khóa, hoặc thử lại sau ít phút.")
        else:
            them_log("✔ Hoàn tất.")
        if da_luu == 0 and plat_lr in ("dy", "bili", "xhs", "rednote", "wb", "tt", "fb"):
            # CÀO 0 VIDEO → XÁC MINH LẠI đăng nhập nền tảng đó (badge có thể 'xanh giả' do cookie stale).
            # Chạy NỀN (kiem_tra_login mở browser ngầm ~10-20s, ghi _login_check.json → badge tự cập nhật).
            def _recheck(_p=plat_lr):
                try:
                    them_log("🔄 Cào 0 video — kiểm tra lại đăng nhập %s..." % _p)
                    r = subprocess.run([PYTHON_VENV, "kiem_tra_login.py", _p], cwd=THU_MUC_GOC,
                                       capture_output=True, text=True, encoding="utf-8",
                                       errors="replace", creationflags=_NO_WINDOW, timeout=90)
                    tt = "?"
                    for line in (r.stdout or "").splitlines():
                        if "LOGIN_CHECK_DONE" in line:
                            try:
                                tt = json.loads(line.split("LOGIN_CHECK_DONE", 1)[1].strip()).get(_p, "?")
                            except Exception:
                                pass
                    if tt == "out":
                        them_log("🔴 Xác minh: %s ĐÃ ĐĂNG XUẤT (phiên hết hạn) — hãy ĐĂNG NHẬP LẠI rồi cào lại. (Thẻ sẽ chuyển đỏ.)" % _p)
                    elif tt == "in":
                        them_log("🟢 Xác minh: %s VẪN đăng nhập — 0 video là do từ khóa / anti-bot, KHÔNG phải đăng nhập." % _p)
                    else:
                        them_log("🟡 Xác minh %s: chưa chắc (%s) — nếu nghi ngờ, đăng nhập lại cho chắc." % (_p, tt))
                except Exception:
                    pass
            threading.Thread(target=_recheck, daemon=True).start()
    except Exception as e:
        them_log(f"[LỖI] {e}")
    finally:
        wd["stop"] = True
        _proc = None
        _dang_cao = False    # nhả cờ kể cả khi Popen lỗi → không kẹt "đang cào" vĩnh viễn
        # HẠN MỨC LỒNG TIẾNG cho đường /api/localize (Việt hóa + lồng tiếng): đếm SAU khi output _longtieng.mp4
        # VỪA tạo (mtime ≥ mốc start) → thành công thật, không tính lại bản cache cũ. Chung pool với /api/dub.
        if dub_phut and dub_out:
            try:
                if os.path.isfile(dub_out) and os.path.getmtime(dub_out) >= _dub_t0 - 2:
                    kdb.usage_cong("dub", 1)
                    kdb.usage_cong("dub_phut", int(dub_phut))
            except Exception:
                pass


# ---------------- Tìm ẢNH: xem trước (metadata) rồi cào bài đã chọn ----------------
_anh = {"running": False, "items": [], "msg": "", "platform": "", "proc": None, "thread": None}
_anh_lock = threading.Lock()


def _da_tai_keys(nt):
    """Set key ĐÃ TẢI ĐẦY ĐỦ: SQLite da_tai (luồng Xem-trước & chọn) HỢP với ledger _da_tai_ids.txt
    (luồng cào CHÍNH do MediaCrawler ghi) → badge 'đã tải' đúng cho MỌI cách cào, không chỉ preview."""
    keys = set()
    try:
        import index_metadata
        keys |= index_metadata.da_tai_set(nt)
    except Exception:
        pass
    info = NEN_TANG.get(nt)
    if info:
        led = os.path.join(DATA_DIR, info["thu_muc"].split("/")[-1], "_da_tai_ids.txt")
        try:
            with open(led, encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if s:
                        keys.add(s)
        except OSError:
            pass
    return keys


def _gan_badge(platform, items):
    """Gắn cờ da_tai (ĐÃ tải) cho mỗi item — chỉ ĐÁNH DẤU, KHÔNG lọc (tránh '0 bài').
    + SẮP XẾP: video MỚI tinh lên TRÊN, video đã-thấy-lần-trước-chưa-tải ở giữa, ĐÃ TẢI xuống DƯỚI
    (giữ thứ tự cào trong từng nhóm — sort ổn định). 'da_thay' do tim_anh gắn (ID trong jsonl lịch sử)."""
    if not items:
        return
    mk = _da_tai_keys(platform)
    for it in items:
        if isinstance(it, dict):
            it["da_tai"] = (it.get("url", "") in mk) or (str(it.get("id", "")) in mk)
    # 0 = mới tinh (trên), 1 = đã thấy lần trước nhưng chưa tải, 2 = đã tải (dưới)
    items.sort(key=lambda it: (2 if (isinstance(it, dict) and it.get("da_tai")) else
                               (1 if (isinstance(it, dict) and it.get("da_thay")) else 0)))


def _tim_anh_finalize(stdout, platform=""):
    """Đọc DÒNG JSON cuối tim_anh/tai_ytdlp in ra -> chốt kết quả (hoặc msg lỗi login/timeout)."""
    data = {}
    for line in reversed((stdout or "").strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                data = json.loads(line); break
            except Exception:
                continue
    with _anh_lock:
        if data.get("ok"):
            _anh["items"] = data.get("items", [])
            if _anh["items"]:
                _anh["msg"] = f"Tìm thấy {len(_anh['items'])} bài."
            else:                        # request OK nhưng nền tảng cố tình trả 0 (Douyin hay vậy) = KHÔNG phải lỗi tool
                _anh["msg"] = ("⚠ Nền tảng trả 0 kết quả — thường KHÔNG phải lỗi tool. Do phiên đăng nhập cần làm mới, "
                               "hoặc nền tảng tạm giới hạn/anti-bot. Thử: đăng nhập lại nền tảng, đợi vài phút, hoặc đổi/giảm từ khóa.")
        elif data.get("msg"):           # lỗi login/timeout/anti-bot
            if _anh["items"]:           # ĐÃ stream được video → GIỮ (đừng để lỗi trang CUỐI xoá kết quả tốt + báo lỗi oan)
                _anh["msg"] = f"Tìm thấy {len(_anh['items'])} bài."
            else:
                _anh["items"] = []
                _anh["msg"] = data["msg"]
        elif not _anh["items"]:         # không có gì + không msg
            _anh["msg"] = ("⚠ Không tìm thấy bài nào — thường do NỀN TẢNG (đăng nhập cần làm mới / tạm chặn anti-bot), "
                           "KHÔNG phải lỗi tool. Thử đăng nhập lại nền tảng rồi thử lại sau ít phút.")
        else:                            # GIỮ items đã stream được (crawl bị cắt giữa chừng)
            _anh["msg"] = f"Tìm thấy {len(_anh['items'])} bài."
        _gan_badge(platform, _anh["items"])


def _tim_anh_worker(platform, loai, noi_dung, count):
    try:
        if platform in ("yt", "tt", "fb"):
            # YouTube/TikTok/Facebook dùng yt-dlp (liệt kê metadata-only, NHANH/batch) — KHÁC MediaCrawler
            args = [PYTHON_VENV, "tai_ytdlp.py", "--list", "--platform", platform,
                    "--type", loai, "--input", noi_dung, "--count", str(count)]
            kq = subprocess.run(args, cwd=THU_MUC_GOC, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", creationflags=_NO_WINDOW, timeout=1800)
            _tim_anh_finalize(kq.stdout or "", platform)
            return
        # MediaCrawler (dy/bili/xhs/wb): STREAM — hiện video DẦN khi crawl ghi jsonl (khỏi đợi xong hết).
        import tim_anh
        _don_crawl_ro_ri(platform)   # dọn browser-crawl rò rỉ giữ khóa profile -> preview không bị 0 oan
        folder = tim_anh.DATA_FOLDER.get(platform)
        parser = tim_anh._PARSER.get(platform)
        args = [PYTHON_VENV, "tim_anh.py", "--platform", platform, "--type", loai, "--count", str(count)]
        args += ["--creator", noi_dung] if loai == "creator" else ["--keyword", noi_dung]
        if not folder or not parser:    # nền tảng lạ -> batch
            kq = subprocess.run(args, cwd=THU_MUC_GOC, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", creationflags=_NO_WINDOW, timeout=1800)
            _tim_anh_finalize(kq.stdout or "", platform)
            return
        snap = tim_anh._snapshot_lines(folder)
        proc = subprocess.Popen(args, cwd=THU_MUC_GOC, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", creationflags=_NO_WINDOW)
        with _anh_lock:
            _anh["proc"] = proc         # lưu để dừng được khi đóng preview / xem kênh khác
        out_lines = []                  # gom stdout tim_anh (đọc trong thread) để chốt dòng JSON cuối
        threading.Thread(target=lambda: out_lines.extend(proc.stdout) if proc.stdout else None,
                         daemon=True).start()
        while proc.poll() is None:      # crawl đang chạy -> đọc jsonl mới, cập nhật grid DẦN
            time.sleep(1.5)
            try:
                items = [parser(d) for d in tim_anh._rows_vua_them(folder, snap)]
                _gan_badge(platform, items)
                with _anh_lock:
                    _anh["items"] = items
                    _anh["msg"] = f"Đang tìm... thấy {len(items)} bài"
            except Exception:
                pass
        time.sleep(0.6)                 # đợi thread đọc nốt stdout
        _tim_anh_finalize("".join(out_lines), platform)
    except Exception as e:
        with _anh_lock:
            _anh["items"] = []
            _anh["msg"] = "Lỗi: " + str(e)[:200]
    finally:
        with _anh_lock:
            _anh["running"] = False
            _anh["proc"] = None


def _dung_tim_anh():
    """Dừng tác vụ cào-preview đang chạy (kill subprocess tim_anh + đợi worker cũ kết thúc) để xem
    kênh/từ khóa KHÁC ngay — khỏi báo 'Đang tìm, chờ chút' khi đóng preview rồi mở cái mới."""
    with _anh_lock:
        proc = _anh.get("proc")
        th = _anh.get("thread")
        _anh["proc"] = None
    if proc is not None:
        try:
            _kill_proc_tree(proc)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    if th is not None and th.is_alive():
        th.join(timeout=5)
    with _anh_lock:
        _anh["running"] = False


def chay_tim_anh(body):
    platform = body.get("platform", "xhs")
    loai = body.get("type") if body.get("type") in ("search", "creator") else "search"
    # type=search -> dùng 'keyword'/'input' (từ khóa); type=creator -> 'input' (id/link kênh)
    noi_dung = (body.get("input") or body.get("keyword") or "").strip()
    count = body.get("count") or 20
    if not noi_dung:
        return {"ok": False, "msg": "Chưa nhập từ khóa/kênh."}
    # CHẶN xem-trước khi ĐANG CÀO/TẢI: cào + preview DÙNG CHUNG 1 trình duyệt (profile khóa 1-instance) VÀ
    # ghi CHUNG jsonl → chạy song song thì preview vớ nhầm data của lần cào đang tải (vd cào mukbang đang
    # tải → xem trước review phim lại ra mukbang) + profile bị khóa nên cào mới 0 video. Chờ tải xong / Dừng.
    if _proc is not None or _dang_cao:
        return {"ok": False, "msg": "⏳ Đang cào/tải video (dùng chung 1 trình duyệt) — chờ TẢI XONG, "
                                    "hoặc bấm ⛔ Dừng cào, rồi mới Xem trước được."}
    with _anh_lock:
        dang_chay = _anh["running"]
    if dang_chay:                       # đóng preview rồi xem kênh khác: DỪNG cái cũ, KHÔNG báo "chờ chút"
        _dung_tim_anh()
    th = threading.Thread(target=_tim_anh_worker, args=(platform, loai, noi_dung, count), daemon=True)
    with _anh_lock:
        _anh.update({"running": True, "items": [], "msg": "Đang tìm...", "platform": platform, "proc": None, "thread": th})
    th.start()
    return {"ok": True}


# ============================ TAB "KÊNH NGUỒN" (profile kiểu TikTok → tự tải theo lịch → LohaPage) ============
# Feature TỰ CHỦ: ném link kênh → cào metadata (tim_anh creator) → profile {avatar,tên,videos}. Đặt lịch →
# mỗi ngày worker tải N video CHƯA tải (cao_anh_chon) → enqueue render (marker kn_giao) → render xong gọi
# giao_loha THẲNG vào folder LohaPage. KHÔNG qua gom/trang_config. Xem kenh_nguon.py + gom_dang_bai.giao_loha.
import kenh_nguon as _kn

_kn_lock = threading.Lock()          # serialize thao tác cào-thêm-kênh (dùng chung profile trình duyệt)


def _kn_profile_post_cao(platform, items):
    """Lấy (nickname, avatar, sec_uid) của kênh vừa cào từ items + avatar_kenh_map (best-effort)."""
    nick = avatar = sec = ""
    for it in items:
        if it.get("nick"):
            nick = it["nick"]; break
    for it in items:                 # xhs item có sẵn avatar + user_id
        if it.get("avatar"):
            avatar = it["avatar"]
        if it.get("user_id"):
            sec = str(it["user_id"])
        if avatar:
            break
    if nick and not avatar:
        try:
            avatar = avatar_kenh_map().get(nick, "") or ""
        except Exception:
            avatar = ""
    return nick, avatar, sec


def _cao_kenh_meta_ytdlp(platform, link, count=30):
    """Liệt kê METADATA kênh YT/TikTok/Facebook qua tai_ytdlp --list (KHÔNG tải media) →
    {ok, nick, avatar, sec, items} | {ok:False, msg}. Cho Kênh nguồn + Theo dõi (dùng chung _cao_kenh_meta).
    yt-dlp không cần browser 1-instance nên KHÔNG giữ _kn_lock. sec_uid rỗng (định danh kênh = link, xem _kid)."""
    args = [PYTHON_VENV, "tai_ytdlp.py", "--list", "--platform", platform,
            "--type", "creator", "--input", link, "--count", str(count)]
    env = os.environ.copy()
    env["TARGET_LANG"] = ngngu.target_lang()
    try:
        kq = subprocess.run(args, cwd=THU_MUC_GOC, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", creationflags=_NO_WINDOW, timeout=1800, env=env)
    except subprocess.TimeoutExpired:
        return {"ok": False, "msg": "Liệt kê kênh quá lâu — thử lại."}
    # tai_ytdlp.liet_ke in 1 dòng JSON {ok, items, tong}; các dòng "LOG:..." bỏ qua. Lấy dòng JSON CUỐI.
    data = None
    for ln in reversed((kq.stdout or "").strip().splitlines()):
        ln = ln.strip()
        if ln.startswith("{"):
            try:
                data = json.loads(ln); break
            except Exception:
                pass
    if not data:
        return {"ok": False, "msg": "Không đọc được kết quả liệt kê kênh (thử lại / kiểm tra link kênh)."}
    if not data.get("ok"):
        return {"ok": False, "msg": data.get("msg") or "Không lấy được video từ kênh."}
    items = data.get("items") or []
    if not items:
        return {"ok": False, "msg": "Không thấy video nào ở kênh (kênh trống / riêng tư / bị chặn)."}
    nick = (data.get("kenh_nick") or "").strip()   # tên kênh THẬT (channel/uploader) từ tai_ytdlp
    if not nick:
        for it in items:
            if it.get("nick"):
                nick = it["nick"]; break
    if not nick:   # extract_flat không trả channel → suy @handle từ link cho tên đỡ trống
        import re as _re
        m = _re.search(r"(?:@|/user/|/channel/|/c/)([^/?#]+)", link)
        nick = ("@" + m.group(1)) if m else ""
    avatar = (data.get("kenh_avatar") or "").strip()   # AVATAR kênh THẬT (thumbnails cấp playlist)
    if not avatar and nick:
        try:
            avatar = avatar_kenh_map().get(nick, "") or ""
        except Exception:
            avatar = ""
    return {"ok": True, "nick": nick, "avatar": avatar, "sec": "", "items": items}


def _cao_kenh_meta(platform, link, count=30):
    """Cào METADATA 1 kênh (tim_anh creator, KHÔNG tải media) → {ok, nick, avatar, sec, items} | {ok:False, msg}.
    DÙNG CHUNG: Kênh nguồn (_kn_cao_kenh) + Theo dõi (_theodoi_worker/td_add). KHÔNG ghi store — caller tự lưu.
    yt/tt/fb → _cao_kenh_meta_ytdlp (yt-dlp). Nền TQ → tim_anh (browser 1-instance, giữ _kn_lock).
    Tôn trọng guard crawl (browser 1-instance) + _kn_lock (serialize với Kênh nguồn)."""
    link = (link or "").strip()
    if not link:
        return {"ok": False, "msg": "Chưa nhập link/ID kênh."}
    # YT/TikTok/Facebook: liệt kê metadata-only qua yt-dlp (tai_ytdlp --list). Item tai_ytdlp
    # ({id,title,thumb,url,video,like,nick}) đã TƯƠNG THÍCH kenh_nguon._chuan_video + _td_merge_videos.
    # Không dùng browser-crawl 1-instance như MediaCrawler → KHÔNG cần _kn_lock/_don_crawl_ro_ri.
    if platform in ("yt", "tt", "fb"):
        return _cao_kenh_meta_ytdlp(platform, link, count)
    if platform not in ("dy", "bili", "xhs", "rednote", "wb"):
        return {"ok": False, "msg": "Nền tảng chưa hỗ trợ theo kênh: " + platform}
    if _proc is not None or _dang_cao:
        return {"ok": False, "msg": "⏳ Đang cào/tải (dùng chung trình duyệt) — chờ xong rồi thử lại."}
    import tim_anh
    _mc_plat = "xhs" if platform == "rednote" else platform
    folder = tim_anh.DATA_FOLDER.get(_mc_plat)
    parser = tim_anh._PARSER.get(_mc_plat)
    if not folder or not parser:
        return {"ok": False, "msg": "Nền tảng chưa hỗ trợ: " + platform}
    with _kn_lock:
        _don_crawl_ro_ri(platform)
        snap = tim_anh._snapshot_lines(folder)
        args = [PYTHON_VENV, "tim_anh.py", "--platform", platform, "--type", "creator",
                "--creator", link, "--count", str(count)]
        try:
            kq = subprocess.run(args, cwd=THU_MUC_GOC, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", creationflags=_NO_WINDOW, timeout=1800)
        except subprocess.TimeoutExpired:
            return {"ok": False, "msg": "Cào kênh quá lâu (có thể chưa đăng nhập) — thử lại."}
        items = []
        try:
            items = [parser(d) for d in tim_anh._rows_vua_them(folder, snap)]
        except Exception:
            items = []
        if not items:
            for ln in reversed((kq.stdout or "").strip().splitlines()):
                ln = ln.strip()
                if ln.startswith("{"):
                    try:
                        j = json.loads(ln)
                        if not j.get("ok") and j.get("msg"):
                            return {"ok": False, "msg": j["msg"]}
                    except Exception:
                        pass
                    break
            return {"ok": False, "msg": "Không thấy video nào ở kênh (chưa đăng nhập / kênh trống / bị chặn)."}
        nick, avatar, sec = _kn_profile_post_cao(platform, items)
        return {"ok": True, "nick": nick, "avatar": avatar, "sec": sec, "items": items}


def _kn_cao_kenh(platform, link, count=30):
    """Cào METADATA 1 kênh → lưu profile + videos vào kenh_nguon (Kênh nguồn). Dùng _cao_kenh_meta (CHUNG Theo dõi)."""
    r = _cao_kenh_meta(platform, link, count)
    if not r.get("ok"):
        return r
    k = _kn.them_kenh(platform, link, ten=r["nick"], avatar=r["avatar"], sec_uid=r["sec"], videos=r["items"])
    them_log(f"➕ Kênh nguồn: '{k.get('ten') or link}' — {len(k.get('videos', []))} video (metadata).")
    return {"ok": True, "kenh": _kn.thong_ke(k)}


def _kn_import_da_cao(platform=""):
    """Import MỌI kênh ĐÃ CÀO-theo-link (đọc creator_contents_*.jsonl — file cào creator) vào Kênh nguồn, KHÔNG
    cào lại. Gom theo sec_uid/user_id → mỗi kênh = profile (nick+avatar) + danh sách video (id/title/thumb).
    them_kenh MERGE (giữ 'tai' + tên đã đổi). platform rỗng = mọi nền hỗ trợ."""
    import tim_anh, glob as _glob
    plats = [platform] if platform else ["dy", "bili", "xhs", "wb"]
    _mklink = {
        "dy":   lambda sec, uid: "https://www.douyin.com/user/%s" % (sec or uid),
        "bili": lambda sec, uid: "https://space.bilibili.com/%s" % (uid or sec),
        "xhs":  lambda sec, uid: "https://www.xiaohongshu.com/user/profile/%s" % (uid or sec),
        "wb":   lambda sec, uid: "https://weibo.com/u/%s" % (uid or sec),
    }
    _data = (os.environ.get("MC_DATA_DIR") or "").strip() or os.path.join(THU_MUC_CRAWLER, "data")
    tong_k = tong_v = 0
    for plat in plats:
        mc = "xhs" if plat == "rednote" else plat
        folder = tim_anh.DATA_FOLDER.get(mc); parser = tim_anh._PARSER.get(mc)
        if not folder or not parser:
            continue
        files = _glob.glob(os.path.join(_data, folder, "jsonl", "creator_contents_*.jsonl"))
        kenh = {}   # key(sec/uid/nick) -> {sec,uid,nick,avatar,items{id:item}}
        for f in files:
            try:
                fp = open(f, encoding="utf-8", errors="ignore")
            except OSError:
                continue
            with fp:
                for ln in fp:
                    ln = ln.strip()
                    if not ln:
                        continue
                    try:
                        d = json.loads(ln)
                    except Exception:
                        continue
                    sec = str(d.get("sec_uid") or ""); uid = str(d.get("user_id") or "")
                    key = sec or uid or str(d.get("nickname") or "")
                    if not key:
                        continue
                    try:
                        it = parser(d)
                    except Exception:
                        continue
                    if not it or not it.get("id"):
                        continue
                    g = kenh.setdefault(key, {"sec": sec, "uid": uid, "nick": "", "avatar": "", "items": {}})
                    if d.get("nickname"):
                        g["nick"] = d["nickname"]
                    if d.get("avatar") and not g["avatar"]:
                        g["avatar"] = d["avatar"]
                    g["items"][it["id"]] = it
        for key, g in kenh.items():
            link = _mklink.get(plat, lambda s, u: "%s:%s" % (plat, s or u))(g["sec"], g["uid"])
            items = sorted(g["items"].values(), key=lambda x: x.get("time", 0), reverse=True)
            _kn.them_kenh(plat, link, ten=g["nick"], avatar=g["avatar"], sec_uid=(g["sec"] or g["uid"]), videos=items)
            tong_k += 1; tong_v += len(items)
    them_log(f"📥 Import Kênh nguồn: {tong_k} kênh · {tong_v} video (từ dữ liệu đã cào-theo-kênh).")
    return {"ok": True, "so_kenh": tong_k, "so_video": tong_v}


def _kn_capnhat_het(log=None):
    """Cập nhật (re-crawl metadata) TẤT CẢ kênh trong Kênh nguồn → lấy video mới đăng. Chạy tuần tự (dùng chung
    trình duyệt), nghỉ 1s giữa kênh tránh rate-limit. Trả số kênh cập nhật được."""
    log = log or them_log
    ok = 0
    for k in list(_kn.doc().get("kenh", [])):
        try:
            r = _kn_cao_kenh(k.get("platform"), k.get("link"))
            if r.get("ok"):
                ok += 1
        except Exception:
            pass
        time.sleep(1)
    log(f"🔄 Cập nhật kênh mới: xong {ok} kênh.")
    return ok


def _kn_dich_tieu_de_kenh(kid, log=None):
    """Dịch (CHUẨN HOÁ) TOÀN BỘ tiêu đề tiếng Trung CHƯA dịch của 1 kênh: quét hết tên gốc → gom 1 PROMPT
    (batch, giống phan_loai._goi_ai_batch) → Gemini WEB dịch → lưu title_vi vào Kênh nguồn. title_vi này được
    _gom_kenh_nguon (gom_dang_bai.py) ƯU TIÊN dùng LUÔN làm caption thật khi gom→LohaPage (thay vì tự dịch lại
    từ tên file mỗi lần gom như trước)."""
    log = log or them_log
    import re
    import dich_gemini_web
    cfg = _kn.doc()
    krec = next((k for k in cfg.get("kenh", []) if k.get("kid") == kid), None)
    if not krec:
        return 0
    videos = krec.get("videos") or []
    ket_qua = {}                              # video_id -> title_vi (gom hết, ghi đĩa 1 LẦN ở cuối)
    todo = []                                 # [(video_id, tiêu_đề_gốc_đã_bỏ_hashtag)] — CẦN gửi Gemini
    for v in videos:
        raw = (v.get("title") or "").strip()
        if not raw or v.get("title_vi"):
            continue
        cot = re.split(r"[#＃]", raw)[0].strip()      # bỏ hashtag trước khi gửi Gemini (đỡ nhiễu)
        if not re.search(r"[㐀-鿿]", cot):             # không có chữ Hán (TikTok Việt/YouTube Anh) → giữ nguyên
            ket_qua[v["id"]] = cot or raw
            continue
        todo.append((v["id"], cot))
    if not todo and not ket_qua:
        log(f"ℹ Kênh '{krec.get('ten')}': mọi tiêu đề đã chuẩn hoá.")
        return 0
    if todo:
        log(f"🌐 Đang dịch {len(todo)} tiêu đề (Gemini web) của kênh '{krec.get('ten')}'...")
        BATCH = 25                            # 1 prompt/lô — tránh prompt quá dài khi kênh nhiều trăm video
        for i in range(0, len(todo), BATCH):
            chunk = todo[i:i + BATCH]
            dong = ["%d. %s" % (j + 1, t) for j, (_id, t) in enumerate(chunk)]
            prompt = (
                "Dịch mỗi TIÊU ĐỀ video tiếng Trung dưới đây sang tiếng Việt, ngắn gọn, tự nhiên, "
                "HẤP DẪN để đăng Facebook (có thể thêm 1 emoji), KHÔNG giữ chữ Hán/pinyin, KHÔNG giải thích.\n"
                "TRẢ VỀ ĐÚNG %d dòng, MỖI dòng bắt đầu bằng đúng số thứ tự dạng 'số. bản dịch' (vd '1. Bản dịch "
                "đầu tiên'), KHÔNG bỏ số, KHÔNG gộp/tách dòng, KHÔNG markdown, KHÔNG dòng trống xen giữa.\n\n"
                % len(chunk) + "\n".join(dong)
            )
            try:
                resp = dich_gemini_web.hoi_gemini_web(prompt, min_len=10, wait_login=60, log_fn=log)
            except Exception as e:
                log(f"⚠ Gemini web lỗi: {str(e)[:80]}")
                resp = ""
            # _parse_lo: thử khớp 'số. text' TRƯỚC; Gemini hay BỎ số dù đã dặn -> tự fallback map THEO THỨ TỰ
            # dòng không rỗng (đã proven cho dịch SRT) — không còn phụ thuộc Gemini có đánh số hay không.
            ket = dich_gemini_web._parse_lo(resp, len(chunk))
            for kk, t in ket.items():
                t = (t or "").strip().strip('"').strip("*")
                if 1 <= kk <= len(chunk) and t:
                    ket_qua[chunk[kk - 1][0]] = t
            log(f"  … lô {i // BATCH + 1}: dịch được {len(ket)}/{len(chunk)}.")
    n = _kn.dat_title_vi_batch(kid, ket_qua)
    log(f"✔ Đã chuẩn hoá {n}/{len(videos)} tiêu đề kênh '{krec.get('ten')}'.")
    return n


def _kn_render_opts():
    """Tuỳ chọn render mặc định cho video Kênh nguồn (dịch + lồng tiếng + che chữ Trung). Có thể chỉnh sau."""
    return {"phude": True, "che": True, "long_tieng": True, "engine": "gemini",
            "model": "medium", "tts": "edge", "mirror": False}


def _render_opts_mac_dinh():
    """Cấu hình render mặc định AN TOÀN — KHỚP mặc định thật của tab Render (OCR lời thoại + ViralVoice Tiêu
    chuẩn/piper, chỉnh màu bật, tốc độ 1.0x), KHÔNG tự ý hạ chất lượng để chạy tự động."""
    return {
        "mirror": False, "color": True, "speed": 1.0, "watermark": False,
        "trim_start": 0, "trim_end": 0,
        "phude": True, "che_chu": True, "long_tieng": True,
        "loi_thoai": "ocr", "model": "medium", "ref_audio": "", "engine": "gemini",
        "tts": "piper", "voice": "",
        "dich_thu_cong": False, "goc_vol": 0, "tach_nhac": False, "max_speed": 0,
        "ratio": "", "chu_de": "", "phong_cach": [],
        "logo": None, "text_wm": None,
    }


def _render_opts_cho_kenh(kid):
    """Chất lượng render CHO 1 KÊNH — MỖI TRANG (tab Đăng bài) tự cấu hình RIÊNG (panel render đầy đủ, y hệt
    tab Render — mirror/màu/tốc độ/phụ đề/che/lồng tiếng/giọng/logo/watermark/phong cách...). Kênh thuộc trang
    nào (trang.kn có kid) → dùng render_opts đã lưu của trang đó; chưa gán trang / trang chưa cấu hình riêng
    → mặc định an toàn (không tự hạ chất lượng)."""
    d = _render_opts_mac_dinh()
    try:
        import gom_dang_bai
        cfg = gom_dang_bai.doc_config()
        for tr in cfg.get("trang", []):
            if kid in (tr.get("kn") or []):
                o = tr.get("render_opts") or {}
                if o:
                    d.update(o)
                break
    except Exception:
        pass
    return d


def _kn_caption_tu_stem(stem, hashtag):
    """Caption LohaPage = tiêu đề (tên file đã dịch, bỏ _id) + hashtag kênh (giao_loha đặt filename=caption)."""
    import tao_caption
    title_goc = _re.sub(r"_\d{4,}$", "", stem)          # _re = alias re module-level (KHÔNG có 're' trần)
    td = tao_caption.tieu_de_thuong(title_goc)
    tags = [t.strip() for t in _re.split(r"[#\s]+", hashtag or "") if t.strip()]
    return tao_caption.tao_caption(td, tags)


def _kn_tai_va_render(k, n=0, cap_nhat=True, log=None, chon_ids=None):
    """Tải N video CHƯA tải của kênh k (cao_anh_chon: detail) → enqueue render kèm marker kn_giao. Trả số đưa vào
    hàng đợi. chon_ids CÓ → tải ĐÚNG các video đó (tick tay trong lưới); KHÔNG có → N video CŨ NHẤT (n=0 dùng
    lich.so_moi_ngay). cap_nhat=True → RE-CRAWL metadata TRƯỚC (lấy video MỚI đăng, merge)
    → luôn tải/đăng video mới nhất; profile tự tươi. (Guard _proc/_dang_cao trong _kn_cao_kenh.)"""
    log = log or them_log
    if cap_nhat:
        try:
            _r = _kn_cao_kenh(k.get("platform"), k.get("link"))
            if _r.get("ok"):
                log(f"🔄 Cập nhật kênh '{_r['kenh'].get('ten') or k.get('link')}' — {_r['kenh'].get('so_video')} video (mới nhất).")
        except Exception as e:
            log(f"ℹ Cập nhật kênh trước tải bỏ qua (%s)." % str(e)[:70])
    cfg = _kn.doc()
    krec = _kn._tim(cfg, k.get("platform"), k.get("link"))
    if not krec:
        return 0
    if chon_ids:
        want = {str(i) for i in chon_ids}
        dsvid = [v for v in (krec.get("videos") or []) if str(v.get("id")) in want and not v.get("tai")]
    else:
        n = n or int((krec.get("lich") or {}).get("so_moi_ngay") or 1)
        dsvid = _kn.chua_tai(krec, n)
    if not dsvid:
        log(f"ℹ Kênh '{krec.get('ten')}': không còn video chưa tải.")
        return 0
    dest_dir, hashtag = _kn.folder_dich(cfg, krec)
    if not dest_dir:
        log(f"⚠ Kênh '{krec.get('ten')}': chưa cấu hình ĐÍCH (page/group + thư mục LohaPage) — bỏ qua.")
        return 0
    platform = krec.get("platform")
    ids = [v["id"] for v in dsvid if v.get("id")]
    r = cao_anh_chon({"platform": platform, "ids": ids})       # TẢI (detail) — reuse guard bên trong
    if not r.get("ok"):
        log(f"⚠ Tải kênh '{krec.get('ten')}' lỗi: {r.get('msg') or r.get('error') or ''}")
        return 0
    _kn.danh_dau_tai(platform, krec.get("link"), ids)
    _han = time.time() + 600                                    # ĐỢI tải xong (cao_anh_chon chạy nền)
    while (_dang_cao or _proc is not None) and time.time() < _han:
        time.sleep(2)
    _plat_folder = {"dy": "douyin", "bili": "bili", "xhs": "xhs", "rednote": "xhs", "wb": "weibo"}.get(platform, platform)
    vbase = _videos_cua("data/" + _plat_folder)
    id6set = {str(i)[-6:] for i in ids if i}
    dua = 0
    _walk = os.walk(vbase) if os.path.isdir(vbase) else []
    for root, _d, files in _walk:
        for f in files:
            low = f.lower()
            if not low.endswith(".mp4") or any(s in low for s in ("_xuly", "_phude", "_longtieng")):
                continue
            stem = os.path.splitext(f)[0]
            if stem[-6:] not in id6set and stem.split("_")[-1] not in id6set:
                continue
            o2 = dict(_kn_render_opts())
            o2["kn_giao"] = {"dest_dir": dest_dir, "caption": _kn_caption_tu_stem(stem, hashtag)}
            _queue_them(os.path.join(root, f), o2)
            dua += 1
    log(f"📥 Kênh '{krec.get('ten')}': tải {len(ids)} + đưa {dua} video vào hàng đợi render → giao LohaPage.")
    return dua


def _kn_giao_sau_render(video_path, kn_giao, log=None):
    """SAU render (queue): giao bản _xuly.mp4 MỚI NHẤT của video này vào folder LohaPage (đích trong kn_giao)."""
    log = log or them_log
    if not _can_lohapage():          # gate LohaPage: mất quyền giữa chừng → không giao (job cũ trong queue)
        log("⚠ Bỏ giao LohaPage (chưa có quyền LohaPage).")
        return
    try:
        out = _output_xuly_moi_nhat(video_path)
        if not out or not os.path.isfile(out):
            log(f"⚠ Kênh nguồn: không thấy bản render của {os.path.basename(video_path)} để giao.")
            return
        import gom_dang_bai
        dest = gom_dang_bai.giao_loha(kn_giao.get("dest_dir"), out, kn_giao.get("caption") or "", log=log)
        if dest:
            log(f"📤 Đã giao LohaPage: {os.path.basename(dest)}")
    except Exception as e:
        log(f"⚠ Kênh nguồn giao LohaPage lỗi: {str(e)[:120]}")


_kn_da_chay_ngay = {}     # kid -> 'YYYY-MM-DD' đã chạy (né chạy lại trong ngày)


def _kn_worker():
    """Worker nền: mỗi ~60s duyệt kênh có lịch bật; kênh tới GIỜ + CHƯA chạy hôm nay → tải N + render + giao."""
    import datetime
    while True:
        if not _can_lohapage():          # gate LohaPage: chưa có quyền → không tự tải/render/giao theo lịch
            time.sleep(60); continue
        try:
            cfg = _kn.doc()
            now = datetime.datetime.now()
            hom_nay = now.strftime("%Y-%m-%d")
            for krec in cfg.get("kenh", []):
                lich = krec.get("lich") or {}
                if not lich.get("on"):
                    continue
                gio = str(lich.get("gio") or "09:00")
                try:
                    hh, mm = [int(x) for x in gio.split(":")[:2]]
                except ValueError:
                    hh, mm = 9, 0
                if (now.hour, now.minute) < (hh, mm):
                    continue
                kid = krec.get("kid")
                if _kn_da_chay_ngay.get(kid) == hom_nay:
                    continue
                _kn_da_chay_ngay[kid] = hom_nay
                try:
                    _kn_tai_va_render(krec)
                except Exception as e:
                    them_log(f"⚠ Kênh nguồn worker '{krec.get('ten')}' lỗi: {str(e)[:120]}")
        except Exception:
            pass
        time.sleep(60)


def _khoi_dong_kn():
    threading.Thread(target=_kn_worker, daemon=True).start()


# ============ THEO DÕI KÊNH (tab Video mới) — auto DÒ video mới CỨNG 60p in-app (metadata, KHÔNG tải/render) ==========
# Tính năng CHUNG (gate theo TIER theodoi_max, KHÔNG phải LohaPage → khách chưa mua LohaPage vẫn dùng). Store =
# theo_doi_config.json (FILE_TD) schema giàu: creators=[{link, platform, ten(đổi tên), nickname, avatar, sec_uid,
# videos:[{id,title,thumb,url,time,da_xem}], cao_luc}]. TÁI DÙNG _cao_kenh_meta (crawler CHUNG với Kênh nguồn) —
# KHÔNG đụng store/gate LohaPage. THAY HẲN Windows task ToolCaoVideoTheoDoi (task tự mất sau update → auto chết).
_td_lock = threading.RLock()
_TD_INTERVAL = 3600      # cứng 60 phút (không cần UI)


def _td_doc():
    d = doc_json(FILE_TD, {"creators": []})
    if not isinstance(d, dict):
        d = {"creators": []}
    d.setdefault("creators", [])
    d["creators"] = [({"link": c} if isinstance(c, str) else c) for c in d["creators"] if c]   # nâng cấp bản cũ (link chuỗi)
    return d


def _td_tim(d, link):
    link = (link or "").strip()
    for c in d.get("creators", []):
        if (c.get("link") or "").strip() == link:
            return c
    return None


def _td_plat(c):
    from nen_tang_helper import doan_nen_tang
    return (c.get("platform") or "").strip() or doan_nen_tang(c.get("link") or "")


def _td_chuan_video(it):
    return {"id": str(it.get("id") or ""), "title": (it.get("title") or "").strip(),
            "thumb": it.get("thumb") or "", "url": it.get("url") or "",
            "time": int(it.get("time") or 0), "da_xem": False}


def _td_merge_videos(creator, items, baseline=False):
    """Merge video vào creator.videos (dedup theo id). baseline=True (lần thêm kênh đầu) → đánh dấu HẾT da_xem=True
    (khỏi báo 'mới' oan). Trả số video MỚI chưa từng có (0 nếu baseline)."""
    cu = {v["id"]: v for v in creator.get("videos", []) if v.get("id")}
    moi = 0
    for it in (items or []):
        v = _td_chuan_video(it)
        if not v["id"] or v["id"] in cu:
            continue
        v["da_xem"] = bool(baseline)
        cu[v["id"]] = v
        if not baseline:
            moi += 1
    creator["videos"] = sorted(cu.values(), key=lambda v: v.get("time", 0), reverse=True)[:200]
    return moi


def _td_thong_ke(c):
    vids = c.get("videos") or []
    return {"link": c.get("link"), "platform": _td_plat(c),
            "ten": (c.get("ten") or "").strip(), "nickname": c.get("nickname") or "",
            "avatar": c.get("avatar") or "", "sec_uid": c.get("sec_uid") or "",
            "so_video": len(vids), "so_moi": sum(1 for v in vids if not v.get("da_xem")),
            "cao_luc": c.get("cao_luc") or 0,
            "videos": sorted(vids, key=lambda v: v.get("time", 0), reverse=True)}


def _td_ghi_creators(creators_in, interval="30", count="10"):
    """Ghi danh sách creators từ endpoint CŨ (td_save/td_on — tab Quy trình) NHƯNG GIỮ dữ liệu giàu
    (videos/ten/avatar/platform/cao_luc) của kênh đã có (merge theo link) → KHÔNG wipe store Theo dõi."""
    with _td_lock:
        d = _td_doc()
        cu = {(c.get("link") or "").strip(): c for c in d.get("creators", []) if c.get("link")}
        out, seen = [], set()
        for c in (creators_in or []):
            c = {"link": c} if isinstance(c, str) else dict(c or {})
            link = (c.get("link") or "").strip()
            if not link or link in seen:
                continue
            seen.add(link)
            old = cu.get(link)
            if old:                                     # giữ nguyên bản ghi giàu; chỉ cập nhật nick/avatar nếu incoming có
                for k2 in ("nickname", "avatar"):
                    if c.get(k2):
                        old[k2] = c[k2]
                out.append(old)
            else:
                out.append({"link": link, "platform": c.get("platform") or "", "ten": (c.get("ten") or ""),
                            "nickname": c.get("nickname") or "", "avatar": c.get("avatar") or "", "videos": []})
        luu_json(FILE_TD, {"creators": out, "interval": str(interval), "count": str(count)})


def _td_cap_nhat_1(link, baseline=False):
    """Cào lại metadata 1 kênh theo dõi → merge (crawl NGOÀI _td_lock vì chậm; ghi store atomic trong lock).
    Trả (ok, so_moi, msg)."""
    with _td_lock:
        c = _td_tim(_td_doc(), link)
    if not c:
        return False, 0, "Kênh không có trong danh sách theo dõi."
    r = _cao_kenh_meta(_td_plat(c), link, count=30)
    if not r.get("ok"):
        return False, 0, r.get("msg") or "Cào lỗi."
    with _td_lock:
        d = _td_doc(); c = _td_tim(d, link)
        if not c:
            return False, 0, "Kênh đã bị xoá."
        if r.get("nick"):
            c["nickname"] = r["nick"]
        if r.get("avatar"):
            c["avatar"] = r["avatar"]
        if r.get("sec"):
            c["sec_uid"] = r["sec"]
        n = _td_merge_videos(c, r["items"], baseline=baseline)
        c["cao_luc"] = int(time.time())
        luu_json(FILE_TD, d)
    return True, n, ""


def _theodoi_worker():
    """CỨNG 60 phút: cào lại metadata MỌI kênh theo dõi → merge video mới (da_xem=false). KHÔNG tải/render.
    Chạy khi app mở (thay Windows task). _cao_kenh_meta tự bỏ qua nếu đang cào/tải (browser 1-instance)."""
    time.sleep(25)      # đợi app ổn định (login/crawler sẵn sàng)
    while True:
        try:
            links = [(c.get("link") or "").strip() for c in _td_doc().get("creators", [])]
            links = [l for l in links if l]
            tong_moi = 0
            for link in links:
                try:
                    _ok, n, _msg = _td_cap_nhat_1(link)
                    tong_moi += (n or 0)
                except Exception:
                    pass
                time.sleep(2)       # nghỉ giữa kênh (né rate-limit)
            if tong_moi:
                them_log(f"🔔 Theo dõi: phát hiện {tong_moi} video mới ({len(links)} kênh).")
        except Exception as e:
            them_log("Theo dõi worker lỗi: " + str(e)[:100])
        time.sleep(_TD_INTERVAL)


def _khoi_dong_theodoi():
    # Tab Theo dõi dùng WORKER 60p (không cần Windows task) → auto không còn tự chết. KHÔNG xoá task
    # ToolCaoVideoTheoDoi ở đây vì tab "Quy trình" (wfTd) có thể vẫn dùng task đó cho luồng auto-tải riêng.
    threading.Thread(target=_theodoi_worker, daemon=True).start()


def cao_anh_chon(body):
    """Cào (tải) các bài ĐÃ CHỌN: XHS dùng note URL, nền tảng khác dùng ID. Reuse _crawl_worker."""
    global _proc, _dang_cao
    platform = body.get("platform", "xhs")
    ids = [str(x).strip() for x in (body.get("ids") or []) if str(x).strip()]
    if not ids:
        return {"ok": False, "msg": "Chưa chọn bài nào."}
    # Giới hạn tải gói FREE: DÙNG CHUNG quota 'cao' với BẮT ĐẦU CÀO. (Trước đây đường này KHÔNG kiểm
    # -> free cào quá 20 mà không hay biết.) Đủ quota -> _block (interceptor JS tự hiện banner Nâng cấp);
    # còn ít hơn số đã chọn -> CẮT theo quota còn lại.
    gh = _lim("cao_ngay")
    cat_bot = 0
    if gh is not None:
        conlai = gh - kdb.usage_lay("cao")
        if conlai <= 0:
            return _block("cao", f"Đã đạt giới hạn cào {gh} video/ngày của gói {TIER.upper()}. Nâng cấp để cào không giới hạn.")
        if len(ids) > conlai:
            cat_bot = len(ids) - conlai
            ids = ids[:conlai]
    # Busy-guard ĐỒNG BỘ với chay_crawl: chung _crawl_lock + cờ _dang_cao (tránh race khi vừa bấm "Cào hết"
    # vừa "Cào video đã chọn" → 2 crawl đua nhau / kẹt _proc → "đôi lúc không cào được"). Giữ chỗ trước khi mở thread.
    with _crawl_lock:
        if _proc is not None or _dang_cao:
            return {"ok": False, "msg": "Đang chạy lệnh cào trước đó — đợi nó xong (hoặc bấm Dừng) rồi mới 'Cào video đã chọn'."}
        _dang_cao = True
    env = os.environ.copy()
    env["TARGET_LANG"] = ngngu.target_lang()
    them_log(f"▶ Bắt đầu cào {len(ids)} bài đã chọn ({NEN_TANG.get(platform, {}).get('ten', platform)})")
    if platform in ("yt", "tt", "fb"):
        # YouTube/TikTok/Facebook: tải theo URL video đã chọn bằng yt-dlp (detail) — cwd=THU_MUC_GOC
        lenh = [PYTHON_VENV, "tai_ytdlp.py", "--platform", platform, "--type", "detail",
                "--input", ",".join(ids), "--count", str(len(ids))]
        threading.Thread(target=_crawl_worker, args=(lenh, env, THU_MUC_GOC), daemon=True).start()
    else:
        lenh = [PYTHON_VENV, "main.py", "--platform", platform, "--lt", "qrcode",
                "--type", "detail", "--specified_id", ",".join(ids),
                "--get_comment", "no", "--save_data_option", "jsonl", "--headless", "yes"]
        threading.Thread(target=_crawl_worker, args=(lenh, env), daemon=True).start()
    try:
        import index_metadata
        index_metadata.danh_dau(platform, ids)   # đánh dấu "đã tải" -> Xem-trước lần sau gắn badge
    except Exception:
        pass
    return {"ok": True, "n": len(ids), "cat_bot": cat_bot}


_ANH_DATA_FOLDER = {"xhs": "xhs", "rednote": "rednote", "dy": "douyin", "wb": "weibo", "bili": "bili"}
_ANH_TRUNG = ("xhs", "rednote", "dy", "wb", "bili")   # nền tảng tiếng Trung -> OCR chi_sim
_ocr = {"running": False, "msg": ""}
_ocr_lock = threading.Lock()


def _ocr_worker(platform, lang):
    try:
        import ocr_anh
        base = os.path.join(DATA_DIR, _ANH_DATA_FOLDER.get(platform, platform), "images")
        if not os.path.isdir(base):
            them_log("⚠ Chưa có ảnh để OCR (cào ảnh trước).")
            return
        dirs = set()
        for root, _d, files in os.walk(base):
            if any(f.lower().endswith(ocr_anh.ANH_EXT) for f in files):
                dirs.add(root)
        moi = [d for d in sorted(dirs) if not os.path.isfile(os.path.join(d, "ocr.json"))]
        them_log(f"📝 OCR {len(moi)} thư mục ảnh ({lang})...")
        for i, d in enumerate(moi, 1):
            try:
                kq = ocr_anh.ocr_thu_muc(d, lang)
                them_log(f"   [{i}/{len(moi)}] {os.path.basename(d)}: {len(kq)} ảnh")
            except Exception as e:
                them_log(f"   ⚠ {os.path.basename(d)}: {str(e)[:100]}")
        them_log("✔ Hoàn tất OCR.")
    except Exception as e:
        them_log("⚠ OCR lỗi: " + str(e)[:150])
    finally:
        with _ocr_lock:
            _ocr["running"] = False


def _co_traineddata(ten):
    """Có file <ten>.traineddata trong tessdata/ cục bộ hoặc tessdata hệ thống không?"""
    import ocr_anh
    if os.path.isfile(os.path.join(ocr_anh.TESSDATA_DIR, ten + ".traineddata")):
        return True
    exe = ocr_anh.tim_tesseract()
    return bool(exe) and os.path.isfile(os.path.join(os.path.dirname(exe), "tessdata", ten + ".traineddata"))


def chay_ocr_anh(body):
    platform = body.get("platform", "xhs")
    lang = "chi_sim+eng" if platform in _ANH_TRUNG else "vie+eng"
    if platform in _ANH_TRUNG and not _co_traineddata("chi_sim"):
        return {"ok": False, "msg": "Thiếu chi_sim.traineddata cho OCR tiếng Trung. "
                "Tải https://github.com/tesseract-ocr/tessdata_fast/raw/main/chi_sim.traineddata "
                "vào thư mục tessdata/ rồi thử lại."}
    with _ocr_lock:
        if _ocr["running"]:
            return {"ok": False, "msg": "Đang OCR."}
        _ocr["running"] = True
    threading.Thread(target=_ocr_worker, args=(platform, lang), daemon=True).start()
    return {"ok": True}


def chay_detect_band(body):
    """Dò DẢI phụ đề gốc của 1 video → {ok, source, H, y0, y1}. Frontend (editor che chữ) dùng
    TỰ ĐIỀN sẵn dải che; user vẫn chỉnh tay được. {ok:False} nếu không dò được (editor giữ dải tay
    — degrade an toàn). DÙNG CHUNG quyết định với render (dai_sub.detect_blur_band): cùng detector +
    fallback OpenCV→OCR + cùng ffmpeg bundle → preview KHỚP render (lệch nhẹ ở tầng OCR vì preview
    chưa có .vi.srt là chấp nhận được)."""
    p = (body.get("p") or "").strip()
    if not p or not os.path.exists(p):
        return {"ok": False, "msg": "Không thấy video."}
    try:
        import dai_sub
        r = dai_sub.detect_blur_band(p, srt=None, manual=None, log_fn=lambda *a, **k: None)
        if r.get("source") == "none":
            return {"ok": False}
        return {"ok": True, "source": r["source"],
                "y0": round(float(r["y0"]), 4), "y1": round(float(r["y1"]), 4), "H": int(r["H"])}
    except Exception as e:
        return {"ok": False, "msg": str(e)[:120]}


def _trong_vung(p, *goc):
    """True nếu p (abs) nằm trong 1 trong các thư mục gốc cho phép (chống ghi/đọc ngoài vùng)."""
    ap = os.path.abspath(p)
    for g in goc:
        try:
            ag = os.path.abspath(g)
            if os.path.commonpath([ap, ag]) == ag:
                return True
        except ValueError:   # khác ổ đĩa → commonpath ném lỗi, bỏ qua gốc này
            continue
    return False


def _whitelist_out(v):
    """out_dir: chặn arg-injection ('-') + bắt buộc đường dẫn TUYỆT ĐỐI. Cho DATA_DIR/PROCESSED_DIR
    HOẶC thư mục người dùng TỰ CHỌN qua hộp thoại 'chọn thư mục lưu' (vd D:\\ViralCrawl\\23-6) —
    app khách chạy LOCAL 1 user + đã có CSRF nonce chặn POST lạ → ghi video ra thư mục user chọn là
    tính năng CỐ Ý (xung đột cũ: whitelist chỉ cho DATA_DIR/PROCESSED_DIR → chặn oan thư mục user chọn)."""
    if not v:
        return None
    v = str(v)
    if v.startswith("-") or not os.path.isabs(v):
        raise ValueError("out_dir khong hop le")
    return os.path.abspath(v)


def _whitelist_ref(v):
    """ref_audio (giọng mẫu clone) phải nằm trong giong_mau/DATA_DIR và KHÔNG bắt đầu '-'."""
    if not v:
        return None
    v = str(v)
    if v.startswith("-"):
        raise ValueError("ref_audio khong hop le")
    if not _trong_vung(v, GIONG_DIR, CLONE_DIR, DATA_DIR):   # +CLONE_DIR (giọng clone khách ở userData)
        raise ValueError("ref_audio ngoai vung")
    return os.path.abspath(v)


def _dem_clone_lan_dau(ref):
    """Trừ quota clone khi giọng KHÁCH TỰ TẢI (trong CLONE_DIR) được DÙNG LẦN ĐẦU — KHÔNG trừ lúc upload
    (khách upload nhầm rồi xoá thì không mất lượt). Đánh dấu sidecar .used để không trừ lại các lần sau.
    Không tính giọng built-in (giong_mau/nu|nam.wav). An toàn nuốt lỗi (đếm sai không được chặn render/dub)."""
    try:
        if not ref or _lim("clone_tong") is None:
            return
        full = os.path.abspath(str(ref).replace("/", os.sep))
        if not _trong_vung(full, CLONE_DIR) or not os.path.isfile(full):
            return
        mark = os.path.splitext(full)[0] + ".used"
        if not os.path.exists(mark):
            kdb.usage_cong("clone", 1, theo_ngay=False)
            try:
                open(mark, "w").write("1")
            except OSError:
                pass
    except Exception:
        pass


def _lenh_xu_ly(full, o, pha=None):
    """Dựng lệnh xu_ly_chon.py từ các tùy chọn (né bản quyền + dịch/lồng tiếng).
    pha='asr' → DỊCH THỦ CÔNG pha 1: chỉ ASR → zh.srt rồi dừng.
    pha='dub' → pha 2: render với SRT đã dịch (o['srt_da_dich'])."""
    lenh = [PYTHON_VENV, "xu_ly_chon.py", full]
    if o.get("dich_lai"):                # "Render từ đầu": bỏ qua cache dịch+lồng tiếng → làm mới
        lenh.append("--dich-lai")
    if pha == "asr":
        lenh.append("--chi-asr")
        if o.get("model"):
            lenh += ["--model", str(o["model"])]
        if o.get("engine"):
            lenh += ["--engine", str(o["engine"])]
        if o.get("loi_thoai"):
            lenh += ["--asr-engine", str(o["loi_thoai"])]   # ocr=Đọc từ sub | whisper=Giọng nói (pha ASR)
        if o.get("tach_truoc"):
            lenh.append("--tach-truoc")
        return lenh
    if o.get("mirror"):
        lenh.append("--mirror")
    if o.get("speed") and float(o["speed"]) != 1.0:
        lenh += ["--speed", str(o["speed"])]
    if o.get("zoom") and float(o["zoom"]) > 1.0:      # phóng to khung (cắt mép) — pass reframe trước localize
        lenh += ["--zoom", str(o["zoom"])]
    if o.get("lang"):                                 # render đa ngôn ngữ: ÉP ngôn ngữ đích cho job này (dịch+lồng tiếng
        lenh += ["--target-lang", str(o["lang"])]     # theo ngôn ngữ đó) + xu_ly_chon tự gắn lang-tag = mã → không đè file.
    if o.get("watermark") or o.get("wm_file"):
        lenh.append("--watermark")
        _wmf = os.path.basename((o.get("wm_file") or "").strip())   # chỉ basename: chặn path traversal
        if _wmf:
            _wmp = os.path.join(LOGOS_DIR, _wmf)
            if os.path.isfile(_wmp):
                lenh += ["--watermark-path", _wmp]   # chọn watermark đã tải (override watermark cố định)
    if o.get("color"):
        lenh.append("--color")
    if o.get("trim_start"):
        lenh += ["--trim-start", str(o["trim_start"])]
    if o.get("trim_end"):
        lenh += ["--trim-end", str(o["trim_end"])]
    if o.get("bg_nhac"):
        lenh.append("--bg-nhac")
    if o.get("bg_vol"):
        lenh += ["--bg-vol", str(o["bg_vol"])]
    if o.get("phude"):
        lenh.append("--phude")
    if not o.get("che_chu", True):
        lenh.append("--no-che")
    if o.get("long_tieng"):
        lenh.append("--long-tieng")
    if o.get("loi_thoai"):
        lenh += ["--asr-engine", str(o["loi_thoai"])]   # ocr=Đọc từ sub (RapidOCR) | whisper=Giọng nói
    if o.get("tach_nhac"):
        lenh.append("--tach-nhac")
    if o.get("model"):
        lenh += ["--model", str(o["model"])]
    # Net an toàn: nếu tts gộp "piper:ngochuyen" (UI 1-dropdown) → tách engine + giọng
    _tts0 = o.get("tts") or ""
    if ":" in _tts0:
        _e, _v = _tts0.split(":", 1)
        o["tts"] = _e
        if not o.get("voice"):
            o["voice"] = _v
    if o.get("voice"):
        lenh += ["--voice", str(o["voice"])]
    if o.get("engine"):
        lenh += ["--engine", str(o["engine"])]
    if o.get("tach_truoc"):
        lenh.append("--tach-truoc")
    if o.get("khong_tieng_goc"):
        lenh.append("--khong-tieng-goc")   # bỏ HẲN tiếng gốc, chỉ giọng Việt
    if o.get("goc_vol") is not None:
        lenh += ["--goc-vol", str(o["goc_vol"])]   # âm lượng gốc 0-1 (0 = tắt hẳn)
    if o.get("che_band"):
        lenh += ["--che-band", str(o["che_band"])]   # dải che chữ THỦ CÔNG 'y0,y1' (override dò tự động)
    if o.get("max_speed"):
        lenh += ["--max-speed", str(o["max_speed"])]  # tốc độ ĐỌC tối đa khi nén câu tràn
    _ra = _whitelist_ref(o.get("ref_audio"))
    if _ra:
        lenh.append("--ref-audio=" + _ra)          # =value chống arg-injection (giá trị bắt đầu '-')
        _dem_clone_lan_dau(_ra)                     # trừ quota clone khi DÙNG lần đầu (không trừ lúc upload)
    _od = _whitelist_out(o.get("out_dir"))
    if _od:
        lenh.append("--out-dir=" + _od)            # thư mục lưu _xuly.mp4 (mặc định: cạnh gốc), đã whitelist
    if o.get("ratio") in ("9:16", "16:9"):
        lenh += ["--ratio", o["ratio"]]            # đổi tỉ lệ khung (nền mờ)
    if o.get("blur_boxes"):
        lenh += ["--blur-boxes", json.dumps(o["blur_boxes"])]   # vùng làm mờ (xoá logo gốc)
    _logo = o.get("logo") if (o.get("logo") and (o.get("logo") or {}).get("path")) else None
    if not _logo and o.get("logo_file"):
        # Panel chọn logo đã tải (không vẽ vị trí) -> dùng GÓC mặc định (bien_doi_khung tự đặt).
        _lf = os.path.basename((o.get("logo_file") or "").strip())   # chỉ basename: chặn path traversal
        _lp = os.path.join(LOGOS_DIR, _lf)
        if _lf and os.path.isfile(_lp):
            _logo = {"path": _lp, "goc": (o.get("logo_goc") or "tr")}
    if _logo:
        lenh += ["--logo", json.dumps(_logo)]  # chèn logo (toạ độ từ editor, hoặc góc mặc định từ panel)
    # Watermark CHỮ (drawtext). Bản FREE: ÉP "loha Tech" chạy (branding sản phẩm) — KHÔNG cho bỏ/đổi.
    # Pro+ : tôn trọng watermark chữ user cấu hình (panel "lưu vĩnh viễn"). Dùng TIER live (lam_moi_goi cập nhật).
    _loha = {"text": "Loha Tech", "chay": True, "h": 40}
    _uw = o.get("text_wm") if (o.get("text_wm") and (o["text_wm"] or {}).get("text")) else None
    if TIER == "free":
        # FREE: ÉP Loha Tech (branding) NHƯNG VẪN cho watermark riêng của khách — CẢ HAI cùng hiện.
        # TÔN TRỌNG cấu hình chạy/đứng của khách: user chọn cho watermark riêng CHẠY luôn (như đã tick).
        wms = [_loha]
        if _uw:
            wms.append(_uw)
        lenh += ["--text-wm", json.dumps(wms, ensure_ascii=False)]
    elif _uw:
        lenh += ["--text-wm", json.dumps(_uw, ensure_ascii=False)]  # watermark CHỮ (drawtext) theo toạ độ
    lenh += ["--tts", o.get("tts") or "edge"]   # giọng lồng tiếng: edge (nhanh, mặc định) | omnivoice (clone)
    if o.get("chu_de"):
        lenh += ["--chu-de", str(o["chu_de"])]  # loại video → nạp quy tắc dịch chuyên đề (huong_dan/*.md)
    # VIẾT LẠI THEO PHONG CÁCH (nút chọn-nhiều) — THAY free-text "Cải thiện dịch" (free-text dễ phá định dạng).
    # Input đã là video REVIEW → chỉ PARAPHRASE đổi giọng kể, GIỮ ý/tình tiết/timeline. Mỗi mã = cụm CỐ ĐỊNH
    # (an toàn, do tool kiểm soát) → ghép vào DICH_QUY_TAC (ống prompt sẵn có). 'giu_nguyen'/rỗng = không viết lại.
    if "phong_cach" in o:
        # BỎ hoc_thuat/mc (2026-07-01): đo thật thấy 2 style này tràn ngân sách ký tự lồng tiếng nặng nhất
        # (TB 1.31-1.59× khe cho phép, đỉnh tới 2.0×) — dễ làm TTS bị nén/tăng tốc quá tay khi lồng tiếng.
        _PC = {
            "hai_huoc": "hài hước, dí dỏm", "viral": "viral kiểu TikTok (câu mở gây tò mò, cuốn người xem)",
            "kich_tinh": "kịch tính, hồi hộp", "cam_xuc": "giàu cảm xúc, lay động",
            "doi_thuong": "đời thường, gần gũi như đang trò chuyện",
            "van_hoc": "văn học, giàu hình ảnh", "ngan_gon": "ngắn gọn, súc tích",
        }
        _pc = [p for p in (o.get("phong_cach") or []) if p in _PC]
        if _pc:
            lenh.append("--quy-tac=VIẾT LẠI lời thoại theo phong cách: " + ", ".join(_PC[p] for p in _pc) +
                        ". GIỮ NGUYÊN ý nghĩa, KHÔNG thêm/bớt tình tiết, KHÔNG đổi timeline hay số câu.")
    if pha == "dub" and o.get("srt_da_dich"):
        lenh += ["--srt-co-san", str(o["srt_da_dich"])]   # DỊCH THỦ CÔNG pha 2: ghép từ SRT đã dịch
    return lenh


_phan_loai_lock = threading.Lock()


def _output_xuly_moi_nhat(original):
    """Bản render _xuly MỚI NHẤT của 1 video gốc. Output tích luỹ '<ten>_xuly.mp4' / '<ten> (N)_xuly.mp4'
    (KHÔNG ghi đè) → trả file mtime mới nhất khớp. '' nếu chưa có (hoặc đã bị phân-loại move đi)."""
    base = os.path.splitext(original)[0]
    d, bn = os.path.dirname(base), os.path.basename(base)
    try:
        cands = [os.path.join(d, f) for f in os.listdir(d or ".")
                 if f.lower().endswith("_xuly.mp4") and (f[:-9] == bn or f[:-9].startswith(bn + " ("))]
    except OSError:
        return ""
    return max(cands, key=os.path.getmtime) if cands else ""


def _don_srt_canh_video(video):
    """Dọn phụ đề .srt CẠNH video SAU khi render + phân loại xong → thư mục khách gọn (chỉ còn video,
    không rối .srt). Bản cache vẫn nằm trong _cache_artifact (TTL/LRU tự xoá) nên re-render vẫn nhanh.
    KHÔNG gọi cho job dịch-thủ-công (khách cần giữ .zh.srt đã sửa). Lỗi → bỏ qua (không chặn render)."""
    if os.environ.get("VC_GIU_SRT") == "1":   # thoát hiểm: giữ .srt cạnh video nếu khách muốn (mặc định DỌN)
        return
    try:
        stem = os.path.splitext(os.path.abspath(video))[0]
    except Exception:
        return
    for ext in (".vi.srt", ".zh.srt", ".zh.gem.vi.srt", ".dubsync.vi.srt"):
        p = stem + ext
        try:
            if os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass


def _phan_loai_sau_render(original):
    """SAU khi render xong (out_dir=None → output _xuly.mp4 cạnh gốc): đọc .vi.srt VỪA DỊCH (AI đã hiểu
    nội dung → đoán thể loại chuẩn) + từ khóa/tiêu đề → MOVE _xuly.mp4 vào folder thể loại (đường dẫn TỰ
    DO). Chạy THREAD NỀN + serialize (Gemini web profile dùng 1 lúc 1) → KHÔNG chặn render video kế tiếp,
    KHÔNG làm render 'tưởng treo'. Lỗi/chưa cấu hình → giữ output cạnh gốc (graceful)."""
    def _job():
        with _phan_loai_lock:
            try:
                import phan_loai
                muc, default = _pl_folders()
                if not muc and not default:
                    return
                out = _output_xuly_moi_nhat(original)   # '<ten>_xuly.mp4' hoặc '<ten> (N)_xuly.mp4' (tích luỹ) → bản mới nhất
                if not out:
                    return
                route = phan_loai.phan_loai_lo([original], muc, default, cache_dir=DATA_DIR, log_fn=them_log)
                dest = (route.get(original) or default or "").strip()
                if not dest:
                    return
                dest = _whitelist_out(dest)
                os.makedirs(dest, exist_ok=True)
                _them_out_dir(dest)   # ĐĂNG KÝ folder thể loại để "File đã tải" QUÉT (liet_ke_file chỉ quét
                                      # PROCESSED_DIR/_OUT_DIRS/data); KHÔNG đăng ký → output move vào đây
                                      # BIẾN MẤT khỏi danh sách = "render nhiều video chỉ thấy 1".
                target = os.path.join(dest, os.path.basename(out))
                if os.path.abspath(target) == os.path.abspath(out):
                    return
                # CHỐNG ĐÈ: 2 video render ra cùng basename '_xuly.mp4' + phân loại về cùng folder
                # → shutil.move đè mất bản trước ("render nhiều video chỉ thấy 1"). Tích luỹ ' (2)','(3)'...
                if os.path.exists(target):
                    _stem2, _ext2 = os.path.splitext(os.path.basename(out))   # '<ten>_xuly', '.mp4'
                    _k = 2
                    while os.path.exists(target):
                        target = os.path.join(dest, "%s (%d)%s" % (_stem2, _k, _ext2))
                        _k += 1
                shutil.move(out, target)
                them_log("🗂️ Phân loại → đã chuyển vào: %s" % dest)
                # Nếu folder thể loại LÀ folder LohaPage (<Tên>_<pageid≥5số> HOẶC __group_<slug>) → ghi sidecar
                # .txt caption để LohaPage đăng ĐẸP (nó ưu tiên .txt > filename). GIỮ tên .mp4 (khỏi vỡ matching
                # "File đã tải" theo _xuly). Không phải folder Loha → bỏ qua (chỉ xếp thể loại). Tắt: CHE_LOHA_TXT=0.
                _dn = os.path.basename(dest.rstrip("/\\"))
                # Sidecar caption = phần LohaPage (cần QUYỀN). Không quyền → vẫn phân loại + move (folder thường), CHỈ bỏ .txt.
                if _can_lohapage() and os.environ.get("PL_LOHA_TXT", "1") != "0" and (_re.search(r"_\d{5,}$", _dn) or _dn.startswith("__group_")):
                    try:
                        import tao_caption
                        _stem = os.path.splitext(os.path.basename(original))[0]
                        _td = tao_caption.tieu_de_thuong(_re.sub(r"_\d{4,}$", "", _stem)) or _stem
                        _cap = tao_caption.tao_caption(_td, _pl_hashtag_theo_folder(dest))   # #lohatech + hashtag thể loại (nếu gán)
                        with open(os.path.splitext(target)[0] + ".txt", "w", encoding="utf-8") as f:
                            f.write(_cap)
                        them_log("📝 Đã ghi caption LohaPage cho bản phân loại.")
                    except Exception:
                        pass
            except Exception as e:
                them_log("⚠ Phân loại sau render lỗi (giữ output cạnh gốc): %s" % str(e)[:100])
            finally:
                _don_srt_canh_video(original)   # phân loại đã đọc .vi.srt xong → dọn .srt cạnh video
    threading.Thread(target=_job, daemon=True).start()


# ---------------- Hàng đợi RENDER (xử lý tuần tự) ----------------
_queue = []                       # [{id, path, ten, opts, trang_thai: cho|dang|xong|loi, msg}]
_queue_lock = threading.Lock()
_queue_id = 0


def _queue_them(path, opts):
    global _queue_id
    with _queue_lock:
        _queue_id += 1
        _queue.append({"id": _queue_id, "path": path, "ten": os.path.basename(path),
                       "opts": opts, "trang_thai": "cho", "msg": "", "pct": 0})
    _queue_luu()   # bền ngay → sống sót nếu app tắt đột ngột trước khi saver kịp chạy


def _eta_giay(it):
    """Giây CÒN LẠI cho video đang render. Extrapolate từ MỐC (eta_t, eta_pct) chốt lúc pct chạm ≥24
    (đã qua nạp-model/ASR — pha cold-start này RẤT lâu ở video đầu, nếu tính từ t0/pct=1 sẽ cho ETA phi
    lý 'còn ~X giờ'). Chưa có mốc (pct<24) → None (chưa hiện, tránh số sai). None khi xong/lỗi."""
    if it.get("trang_thai") != "dang":
        return None
    pct = it.get("pct", 0)
    et = it.get("eta_t"); ep = it.get("eta_pct", 0)
    if not et or pct <= ep or pct >= 100:
        return None
    return max(0.0, (time.time() - et) * (100 - pct) / (pct - ep))


def _fmt_eta(sec):
    """Giây → 'còn ~Xs / ~X phút Ys / ~X giờ Y phút'. '' nếu None."""
    if sec is None:
        return ""
    s = int(sec)
    if s < 60:
        return "còn ~%ds" % s
    if s < 3600:
        return "còn ~%d phút %02ds" % (s // 60, s % 60)
    return "còn ~%d giờ %d phút" % (s // 3600, (s % 3600) // 60)


def _loi_than_thien(raw_tail, ma_loi=""):
    """Dịch lỗi KỸ THUẬT (traceback/ffmpeg/whisper) → 1 câu DỄ HIỂU cho khách non-tech + cách xử lý.
    Khách chỉ thấy câu này; dòng lỗi thô vẫn ghi log riêng cho hỗ trợ kỹ thuật."""
    blob = (" ".join(raw_tail[-15:]) if raw_tail else "").lower()
    pairs = [
        # THIẾU THƯ VIỆN (chạy sai python — vd backend spawn bằng python hệ thống thiếu faster_whisper/
        # rapidocr). ĐẶT TRƯỚC pattern "model" (quá rộng) để KHÔNG bị map nhầm thành "lỗi tải model".
        (("modulenotfounderror", "no module named", "importerror", "dll load failed"),
         "Lỗi môi trường: thiếu thư viện Python (chạy sai môi trường). ĐÓNG hẳn app + MỞ LẠI bằng biểu tượng "
         "LLN APP. Nếu vẫn lỗi, cài lại app."),
        (("moov atom", "invalid data", "corrupt", "could not find codec"),
         "Video gốc bị hỏng hoặc tải chưa xong — thử tải lại video đó rồi render lại."),
        (("no space", "enospc", "disk full", "không đủ dung lượng"),
         "Ổ đĩa đã hết chỗ trống — xoá bớt file hoặc đổi thư mục lưu sang ổ khác (vd D:\\ViralCrawl) rồi thử lại."),
        (("cuda", "cublas", "cudnn", "nvenc", "out of memory"),
         "Lỗi tăng tốc GPU — vào mục 'Tăng tốc GPU' TẮT tăng tốc (chạy bằng CPU) rồi render lại."),
        (("memoryerror", "paging file", "bad allocation", "cannot allocate"),
         "Máy thiếu RAM — đóng bớt trình duyệt/ứng dụng nặng rồi render LẠI từng video một."),
        (("permission", "winerror 5", "access is denied", "errno 13"),
         "Không có quyền ghi file — đổi thư mục lưu sang chỗ khác (vd D:\\ViralCrawl) rồi thử lại."),
        (("timeout", "connection", "getaddrinfo", "max retries", "ssl", "network"),
         "Lỗi kết nối mạng khi dịch/lồng tiếng — kiểm tra Internet rồi render lại."),
        (("whisper", "ctranslate", "huggingface", "model", "download"),
         "Lỗi tải/chạy mô hình nhận dạng giọng (lần đầu cần Internet để tải) — kiểm tra mạng rồi thử lại."),
        (("ffmpeg", "av_interleaved", "muxer", "demux"),
         "Lỗi khi ghép video — thử render lại; nếu vẫn lỗi, sao chép log gửi cho hỗ trợ."),
    ]
    for keys, msg in pairs:
        if any(k in blob for k in keys):
            return msg
    return "Render thất bại — thử render lại. Nếu vẫn lỗi, sao chép log (📋) gửi cho hỗ trợ để được giúp."


def _pct_tu_log(d):
    """Đoán % tiến trình từ dòng LOG (theo bước) — thanh progress cho video đang render.
    Pha LỒNG TIẾNG (dài nhất) NỘI SUY mượt 72→88 theo 'đọc N/M' (chỉ dub mới log dòng này)."""
    import re
    d = (d or "").lower()
    if "✔ xong" in d or "hoàn tất" in d:
        return 100
    if "đang ghép" in d or "🎬" in d:
        return 88
    # OCR / dò-dải (video dài): nội suy % theo 'X/Y khung' → thanh NHÍCH thay vì đứng 1%
    mfr = re.search(r"(\d+)\s*/\s*(\d+)\s*(?:khung|frame)", d)
    if mfr and int(mfr.group(2)) > 0:
        _fr = min(1.0, int(mfr.group(1)) / int(mfr.group(2)))
        if "dò dải" in d or "🔎" in d:
            return min(11, 6 + int(6 * _fr))        # dò dải sub: 6→12
        return min(37, 12 + int(26 * _fr))          # OCR đọc phụ đề: 12→38
    mlo = re.search(r"lô\s+(\d+)\s*/\s*(\d+)", d)    # dịch Gemini theo lô: 38→52
    if mlo and int(mlo.group(2)) > 0:
        return min(51, 38 + int(14 * int(mlo.group(1)) / int(mlo.group(2))))
    if "dò dải" in d or "🔎" in d:
        return 6
    if "đọc phụ đề" in d or "📖" in d:
        return 12
    m = re.search(r"đọc\s+(\d+)\s*/\s*(\d+)", d)   # dub: 'đọc N/M' → nội suy trong pha lồng tiếng
    if m and int(m.group(2)) > 0:
        return min(87, 72 + int(16 * int(m.group(1)) / int(m.group(2))))
    if "lồng tiếng" in d:
        return 72
    if "ai" in d and ("sửa" in d or "🤖" in d):
        return 62
    if "đang dịch" in d or "  dịch" in d or "dịch (" in d:
        return 52
    if "nhận dạng" in d or "đang nghe" in d or "🎧" in d:
        return 38
    if "tách giọng" in d or "tách nhạc" in d or "demucs" in d or "🎚" in d:
        return 24
    if "biến đổi" in d or "🎞" in d:
        return 12
    return None


def _step_tu_log(msg):
    """Suy 'bước' hiện tại từ dòng log (cho stepper tab Tiến trình)."""
    d = (msg or "").lower()
    if "✔ xong" in d or "hoàn tất" in d:
        return "Ghép"
    if "đang ghép" in d or "🎬" in d:
        return "Ghép"
    if "🎙" in d:                 # chỉ khớp dòng BẮT ĐẦU lồng tiếng (tránh dòng lỗi chứa chữ 'lồng tiếng')
        return "Lồng tiếng"
    if "đang dịch" in d or "  dịch" in d or "dịch (" in d:
        return "Dịch"
    if "nhận dạng" in d or "đang nghe" in d or "🎧" in d:
        return "Nghe"
    if "biến đổi" in d or "🎞" in d:
        return "Biến đổi"
    return ""


def _co_render_dang():
    with _queue_lock:
        return any(it["trang_thai"] == "dang" for it in _queue)


def _video_san_sang(path):
    """Video đã tải XONG chưa? Tránh render lúc cào còn ghi file (mp4 ghi moov atom ở CUỐI
    → render sớm sẽ báo 'thiếu moov atom'). Đủ điều kiện: kích thước ĐỨNG YÊN + ffprobe đọc
    được thời lượng. Fail-open nếu KHÔNG có ffprobe (để xu_ly_chon tự kiểm như cũ)."""
    try:
        if not os.path.isfile(path):
            return False
        s1 = os.path.getsize(path)
        if s1 <= 0:
            return False
        time.sleep(1.0)
        if os.path.getsize(path) != s1:   # còn đang tải (kích thước tăng)
            return False
    except OSError:
        return False
    try:
        ff = shutil.which("ffprobe") or "ffprobe"
        kq = subprocess.run([ff, "-v", "error", "-show_entries", "format=duration",
                             "-of", "default=noprint_wrappers=1:nokey=1", path],
                            capture_output=True, text=True, timeout=30, creationflags=_NO_WINDOW)
        return float((kq.stdout or "0").strip() or 0) > 0
    except FileNotFoundError:
        return True   # máy không có ffprobe trên PATH → bỏ qua bước này (size-stable là đủ)
    except Exception:
        return True   # ffprobe lỗi khác → cứ cho render thử, xu_ly_chon còn 1 lớp kiểm nữa


# === PERSISTENT RENDER WORKER (giữ NÓNG Whisper/OCR qua nhiều render; xem plans/260628-persistent-render-worker) ===
# Worker-primary + FALLBACK subprocess: worker chết/lỗi → render VẪN chạy bằng subprocess cũ (an toàn tuyệt đối).
# Tắt khẩn: env VC_RENDER_WORKER=0. Dịch-thủ-công (asr/dub 2 pha) GIỮ subprocess (ít dùng + dừng giữa chừng).
import queue as _queue_mod
# ===== LANE render (SCHEDULER 2-lane) =====
# Mỗi LANE = 1 render_worker BỀN riêng + evq + reader + lock (env-global TARGET_LANG cô lập theo PROCESS → 2 lane
# = 2 process). VC_RENDER_LANES override rõ (=1 tắt / =2 bật). KHÔNG set → MẶC ĐỊNH THÍCH ỨNG theo máy:
# ≥8 core → 2-lane ON (scheduler edge-mạng ∥ Supertonic-CPU + Gemini prefetch); <8 core → 1-lane (BẢO VỆ máy
# yếu i3-9100F 4-core: Supertonic đã bão hòa mọi core + 2 render_worker = gấp đôi RAM model → 2-lane hại/giật).
def _so_lane():
    try:
        _env = os.environ.get("VC_RENDER_LANES")
        if _env:                                   # user ép rõ → tôn trọng (kể cả =1 để tắt trên máy mạnh)
            return max(1, min(3, int(_env)))
        return 2 if (os.cpu_count() or 0) >= 8 else 1   # máy mạnh mặc định 2-lane; máy yếu giữ 1-lane
    except ValueError:
        return 1
_LANES = [{"proc": None, "evq": _queue_mod.Queue(), "lock": threading.Lock(), "retiring": False}
          for _ in range(3)]   # tối đa 3 lane; chỉ _so_lane() lane đầu được dùng
# Alias tương thích ngược (code cũ ngoài vùng lane vẫn tham chiếu _rw_proc/_rw_lock/_rw_evq của LANE 0):
_rw_lock = _LANES[0]["lock"]
_rw_evq = _LANES[0]["evq"]


def _rw_reader(proc, lane):
    """1 luồng đọc stdout worker của LANE → đẩy từng dòng vào lane['evq']; EOF (worker chết) → đẩy None.
    Thấy 'bye' (worker sắp tự thoát do MAX/RAM) → bật lane['retiring'] để render kế respawn worker mới."""
    try:
        for line in proc.stdout:
            if '"bye"' in line:
                lane["retiring"] = True
                if '"ram"' in line:               # worker tự thoát do RAM cao → THÔNG BÁO CHI TIẾT cho khách
                    try:
                        _r = int(json.loads(line.strip()).get("ram", 0))
                    except Exception:
                        _r = 0
                    them_log("🧠 RAM máy đang cao%s — tiến trình render TỰ GIẢI PHÓNG bộ nhớ (xả model "
                             "Whisper/OCR/giọng nói) rồi KHỞI ĐỘNG LẠI để chạy tiếp. ✅ Video đang/đã render "
                             "KHÔNG mất, hàng đợi vẫn chạy bình thường — chỉ video KẾ chậm hơn vài giây do nạp "
                             "lại model. 💡 Giảm tràn RAM: đóng bớt trình duyệt/app nặng (Chrome, Photoshop, "
                             "game…) khi render; render từng video một (đừng vừa cào vừa render); máy ÍT RAM "
                             "(<16GB) nên chọn dịch 'Google' (nhẹ) thay 'AI' và TẮT giữ model GPU."
                             % ((" (%d%%)" % _r) if _r else ""))
            lane["evq"].put(line)
    except Exception:
        pass
    lane["evq"].put(None)


def _rw_env():
    e = os.environ.copy()
    e["TARGET_LANG"] = ngngu.target_lang()
    e["PYTHONUTF8"] = "1"; e["PYTHONIOENCODING"] = "utf-8"
    e["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"; e["TRANSFORMERS_VERBOSITY"] = "error"; e["HF_HUB_DISABLE_TELEMETRY"] = "1"
    # SPLIT DUB↔ENCODE: bật khi scheduler 2-lane (VC_RENDER_LANES≥2) HOẶC user ép VC_SPLIT_DUB_ENCODE=1.
    # localize sẽ báo "⏹CPU_FREE" sau khi dub xong → nhả guard CPU cho video kế dub trong lúc encode.
    if _so_lane() >= 2 or os.environ.get("VC_SPLIT_DUB_ENCODE") == "1":
        e["VC_SPLIT_DUB_ENCODE"] = "1"
    return e


def _rw_ensure(lane=None):
    """Đảm bảo render worker của LANE sống (spawn nếu chưa/chết/đang-retiring). Trả proc, None nếu fail.
    lane=None → LANE 0 (mặc định, tương thích ngược khi VC_RENDER_LANES=1)."""
    if lane is None:
        lane = _LANES[0]
    with lane["lock"]:
        _p = lane["proc"]
        if _p is not None and _p.poll() is None and not lane["retiring"]:
            return _p
        if lane["retiring"] and _p is not None and _p.poll() is None:
            try:
                _kill_proc_tree(_p)   # worker đang tự thoát (MAX/RAM) → kill dứt để respawn sạch (tránh race)
            except Exception:
                pass
        lane["retiring"] = False
        try:
            _p = subprocess.Popen([PYTHON_VENV, "render_worker.py"], cwd=THU_MUC_GOC,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, encoding="utf-8", errors="replace",
                                  creationflags=_NO_WINDOW, env=_rw_env(), bufsize=1)
            lane["proc"] = _p
            t0 = time.time()
            while time.time() - t0 < 40:        # đợi {"ev":"ready"}
                line = _p.stdout.readline()
                if not line:
                    break
                if '"ready"' in line:
                    try:                                # xả event tồn trước khi reader mới chạy
                        while True:
                            lane["evq"].get_nowait()
                    except Exception:
                        pass
                    threading.Thread(target=_rw_reader, args=(_p, lane), daemon=True).start()
                    them_log("🔥 Render worker sẵn sàng (giữ nóng model — render nhanh hơn từ video thứ 2).")
                    return _p
            _kill_proc_tree(_p); lane["proc"] = None
            return None
        except Exception as e:
            them_log("⚠ Không spawn được render worker (%s) → dùng subprocess." % str(e)[:60])
            lane["proc"] = None
            return None


def _rw_kill(lane=None):
    if lane is None:
        lane = _LANES[0]
    with lane["lock"]:
        if lane["proc"] is not None:
            _kill_proc_tree(lane["proc"]); lane["proc"] = None


def _xl_xu_ly_dong(d, item, _segmap, _raw_tail):
    """Xử lý 1 dòng output render (LOG:/SEG|/SEGVI|/raw) → cập nhật item pct/step/segs. DÙNG CHUNG worker+subprocess."""
    if d.startswith("LOG:"):
        msg = d[4:].strip()
        them_log(msg)
        # SPLIT DUB↔ENCODE: localize báo "⏹CPU_FREE" khi DUB xong, vào encode (nvenc/GPU) → job này KHÔNG còn
        # chiếm CPU nặng → nhả guard 2-lane để video KẾ bắt đầu dub song song (encode chồng dub video sau).
        if "⏹CPU_FREE" in msg:
            item["_cpu_free"] = True
        p = _pct_tu_log(msg)
        if p is not None:
            item["pct"] = max(item.get("pct", 0), p)
            # Mốc ETA: chốt (time, pct) LẦN ĐẦU pct chạm ≥24 (đã qua nạp-model/ASR cold-start rất lâu ở
            # video đầu). Extrapolate từ đây thay vì từ t0/pct=1 → khỏi ETA "còn ~X giờ" phi lý lúc mới vào.
            if item["pct"] >= 24 and "eta_t" not in item:
                item["eta_t"] = time.time()
                item["eta_pct"] = item["pct"]
        stp = _step_tu_log(msg)
        if stp:
            item["step"] = stp
    elif d.startswith("SEG|") or d.startswith("SEGVI|"):
        try:
            pre, js = d.split("|", 1)
            o = json.loads(js); i = o.get("i")
            if i:
                seg = _segmap.get(i)
                if seg is None:
                    seg = {"i": i}; _segmap[i] = seg; item["segs"].append(seg)
                if pre == "SEG":
                    seg["st"] = o.get("st"); seg["en"] = o.get("en"); seg["src"] = o.get("src", "")
                else:
                    seg["vi"] = o.get("vi", "")
        except Exception:
            pass
    elif d and not _la_rac(d):
        _raw_tail.append(d)
        if len(_raw_tail) > 25:
            del _raw_tail[0]


def _render_via_worker(item, pha, _segmap, _raw_tail, lane=None):
    """Render qua worker BỀN của LANE. Trả True/False (xong/lỗi) | None (worker chết/treo → fallback) | 'cancelled'.
    Đọc event qua lane['evq'] (reader riêng lane); treo > VC_RENDER_STALL (mặc định 1800s) → kill+fallback.
    lane=None → LANE 0 (tương thích ngược 1-lane)."""
    if lane is None:
        lane = _LANES[0]
    _evq = lane["evq"]
    proc = _rw_ensure(lane)
    if proc is None:
        return None
    args = _lenh_xu_ly(item["path"], item["opts"], pha)[2:]   # bỏ [PYTHON_VENV, "xu_ly_chon.py"]
    try:                                    # xả event tồn của job trước (nếu có)
        while True:
            _evq.get_nowait()
    except Exception:
        pass
    try:
        proc.stdin.write(json.dumps({"cmd": "render", "id": item["id"], "args": args,
                                     "lang": (item.get("opts") or {}).get("lang") or ""}) + "\n")   # render đa ngôn ngữ: đích riêng mỗi job
        proc.stdin.flush()
    except Exception:
        _rw_kill(lane); return None
    stall = int(os.environ.get("VC_RENDER_STALL", "1800") or 1800)
    while True:
        if item.get("cancel"):
            return "cancelled"
        try:
            line = _evq.get(timeout=stall)
        except _queue_mod.Empty:
            them_log("⚠ Worker treo (>%ds không phản hồi) → kill + fallback subprocess." % stall)
            _rw_kill(lane); return None
        if line is None:                    # worker chết (EOF)
            _rw_kill(lane)
            return "cancelled" if item.get("cancel") else None
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        if ev.get("ev") == "log":
            _xl_xu_ly_dong(ev.get("line", ""), item, _segmap, _raw_tail)
        elif ev.get("ev") == "done" and ev.get("id") == item.get("id"):
            return ev.get("code") == 0


# --- Bền HÀNG ĐỢI RENDER (khôi phục sau khi tắt/mở lại app) — MIRROR _task_luu/_task_nap ---
# Persist ra DATA_DIR (userData ghi được; app-src READ-ONLY). Cache artifact đã giữ srt/dub theo BƯỚC
# (localize lưu srt sau dịch, dub sau TTS) → chỉ cần đưa video VỀ LẠI hàng đợi, render-lại tự HIT cache
# bỏ qua bước đã xong. Snapshot bằng ALLOWLIST key cố định (đọc it[k] theo tên) → KHÔNG iterate it.items()
# nên KHỎI 'dict changed size' khi worker sửa item song song.
_QUEUE_LUU_KEYS = ("id", "path", "ten", "opts", "trang_thai", "msg", "pct", "retry", "pha_xong_asr", "zh_srt")
_queue_luu_last = ""


def _queue_file():
    try:
        return os.path.join(DATA_DIR, "_render_queue.json")
    except Exception:
        return os.path.join(THU_MUC_GOC, "_render_queue.json")


def _queue_luu():
    """Ghi _queue ra đĩa (atomic, CHỈ khi nội dung ĐỔI → khỏi churn khi idle)."""
    global _queue_luu_last
    try:
        with _queue_lock:
            raw = list(_queue)[-300:]          # chỉ giữ lock để chụp danh sách; dựng snapshot ngoài lock
        snap = []
        for it in raw:
            try:
                d = {k: it[k] for k in _QUEUE_LUU_KEYS if k in it}
                if isinstance(d.get("opts"), dict):
                    d["opts"] = dict(d["opts"])   # tách ref opts (worker set _dub_phut=0) → dump an toàn
                snap.append(d)
            except Exception:
                continue
        js = json.dumps(snap, ensure_ascii=False)
        if js == _queue_luu_last:
            return
        tmp = _queue_file() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(js)
        os.replace(tmp, _queue_file())
        _queue_luu_last = js
    except Exception:
        pass


def _queue_nap():
    """Nạp lại hàng đợi render lúc MỞ app: video 'dang' (render dở lúc tắt) → 'cho' để TIẾP TỤC (cache srt/dub
    của bước đã xong → render-lại bỏ qua nghe/dịch/TTS đã hoàn tất); video 'cho'/'cho_srt' mất file gốc → 'loi'.
    Gọi TRƯỚC khi start _queue_worker (worker chỉ nhặt 'cho')."""
    global _queue, _queue_id, _queue_luu_last
    try:
        p = _queue_file()
        if not os.path.exists(p):
            return
        with open(p, encoding="utf-8") as f:
            arr = json.load(f)
        if not isinstance(arr, list):
            return
        kq = []
        for it in arr:
            if not isinstance(it, dict) or not it.get("path"):
                continue
            if it.get("trang_thai") == "dang":
                it["trang_thai"], it["pct"], it["msg"] = "cho", 0, "↻ Tiếp tục sau khi mở lại app"
            if it.get("trang_thai") in ("cho", "cho_srt") and not os.path.exists(it["path"]):
                it["trang_thai"], it["msg"] = "loi", "Video gốc không còn (đã xoá/di chuyển) — bỏ qua"
            kq.append(it)
        _queue = kq
        _queue_id = max([it.get("id", 0) for it in _queue] or [0])
        _queue_luu_last = ""            # trạng thái đã đổi khi nạp → buộc lần lưu kế ghi lại
        n = sum(1 for it in _queue if it.get("trang_thai") in ("cho", "cho_srt"))
        if n:
            them_log("↻ Khôi phục hàng đợi render: %d video tiếp tục (tổng %d mục)." % (n, len(_queue)))
    except Exception:
        pass


def _queue_saver():
    """Thread nền: định kỳ lưu hàng đợi → bắt mọi đổi trạng thái trong worker mà KHÔNG đụng vòng lặp render."""
    while True:
        time.sleep(4)
        _queue_luu()


def _queue_remap_paths(old_data, new_data, old_proc, new_proc):
    """ĐỔI THƯ MỤC lưu → video trong data/processed ĐÃ được _merge_move sang chỗ mới; cập nhật path TUYỆT ĐỐI
    trong _queue theo (khỏi 'loi' oan khi khôi phục vì path cũ đã bị dời đi). CHỈ đổi path nằm DƯỚI thư mục đã
    move; path NGOÀI (user tự thêm từ Desktop...) GIỮ NGUYÊN. Sửa cả 'zh_srt' (sidecar dịch-thủ-công cạnh video)."""
    def _doi(p):
        try:
            ap = os.path.abspath(p)
            for cu, moi in ((old_data, new_data), (old_proc, new_proc)):
                cu_ab = os.path.abspath(cu)
                if os.path.normcase(ap).startswith(os.path.normcase(cu_ab) + os.sep):
                    return os.path.join(moi, os.path.relpath(ap, cu_ab))
        except Exception:
            pass
        return p
    doi = False
    with _queue_lock:
        for it in _queue:
            for k in ("path", "zh_srt"):
                if it.get(k):
                    np = _doi(it[k])
                    if np != it[k]:
                        it[k] = np; doi = True
    if doi:
        _queue_luu()


def _co_the_thu_lai(item):
    """Render LỖI → tự đưa item lại 'cho' để THỬ LẠI (tối đa VC_RENDER_RETRY, mặc định 1 lần). Bỏ qua khi user
    huỷ / dịch-thủ-công (chờ người) / hết lượt. Trả True nếu đã xếp thử lại (bỏ qua bước đánh dấu lỗi)."""
    try:
        gioi_han = int(os.environ.get("VC_RENDER_RETRY", "1") or 0)
    except ValueError:
        gioi_han = 1
    if gioi_han <= 0 or item.get("cancel") or (item.get("opts") or {}).get("dich_thu_cong"):
        return False
    n = int(item.get("retry", 0))
    if n >= gioi_han:
        return False
    item["retry"] = n + 1
    item["trang_thai"], item["pct"] = "cho", 0
    item["msg"] = "↻ Tự thử lại (%d/%d)…" % (n + 1, gioi_han)
    for k in ("t0", "eta_t", "eta_pct"):
        item.pop(k, None)
    them_log("↻ Render lỗi — tự thử lại (%d/%d): %s" % (n + 1, gioi_han, item.get("ten")))
    return True


# ===== SCHEDULER: phân loại tài nguyên job (cho guard 2-lane) =====
def _job_resource(opts):
    """Trả 'net' (dub edge/dịch-only — MẠNG, CPU~0) hoặc 'cpu' (Supertonic/Piper/OmniVoice/OCR-Whisper + encode
    — CPU/GPU nặng). Dùng để guard: ≤1 job 'cpu' cùng lúc (Supertonic bão-hòa all-core + encode-filter)."""
    o = opts or {}
    if not o.get("long_tieng"):
        return "cpu"                       # không lồng tiếng nhưng vẫn OCR+encode = CPU
    tgt = (o.get("lang") or "").strip().lower()
    tts = (o.get("tts") or "").strip().lower()
    if not tts:                            # chưa chỉ định → suy từ bảng (supertonic-first)
        tts = "supertonic" if (ngngu.LANGS.get(tgt) or {}).get("supertonic") else "edge"
    return "net" if tts == "edge" else "cpu"   # edge = MẠNG; còn lại (supertonic/piper/omni) = CPU


def _render_1_job(item, lane):
    """Render TRỌN 1 job trên LANE cho trước (in-process worker của lane hoặc fallback subprocess).
    Cập nhật item['trang_thai']/pct/segs. KHÔNG có 'continue' — dùng cho cả worker 1-lane lẫn dispatcher 2-lane."""
    try:
        item["_lane"] = _LANES.index(lane)   # lane-id (để /api/render_progress + hủy đúng lane)
    except (ValueError, Exception):
        item["_lane"] = 0
    # DỊCH THỦ CÔNG: pha 1 = ASR (chưa xong ASR) → dừng chờ SRT; pha 2 = render với SRT đã dịch.
    pha = None
    if item["opts"].get("dich_thu_cong"):
        pha = "dub" if item.get("pha_xong_asr") else "asr"
    item["pct"] = 1
    item["segs"] = []
    item["step"] = ""
    _segmap = {}
    _raw_tail = []   # giữ vài dòng KHÔNG phải LOG:/SEG: (traceback/ffmpeg/edge-tts) → hiện khi lỗi
    ma_loi = ""
    ok = None
    _sub_proc = [None]   # slot fallback subprocess (per-lane, không global → 2 lane không đè)
    try:
        # WORKER-primary (giữ nóng Whisper/OCR → render thứ 2+ nhanh). Dịch-thủ-công GIỮ subprocess.
        if os.environ.get("VC_RENDER_WORKER", "1") == "1" and not item["opts"].get("dich_thu_cong"):
            ok = _render_via_worker(item, pha, _segmap, _raw_tail, lane)
            if ok == "cancelled":
                item["trang_thai"], item["msg"] = "loi", "⏹ Đã huỷ"
                return
            if ok is None:
                them_log("⚠ Render worker không dùng được → fallback subprocess.")
        if ok is None:          # FALLBACK subprocess (worker tắt/lỗi, hoặc dịch-thủ-công)
            _env_xl = os.environ.copy()
            _env_xl["TARGET_LANG"] = (item.get("opts") or {}).get("lang") or ngngu.target_lang()   # render đa ngôn ngữ: đích riêng mỗi job
            _env_xl["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
            _env_xl["TRANSFORMERS_VERBOSITY"] = "error"
            _env_xl["HF_HUB_DISABLE_TELEMETRY"] = "1"
            _sub_proc[0] = subprocess.Popen(_lenh_xu_ly(item["path"], item["opts"], pha), cwd=THU_MUC_GOC,
                                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                            encoding="utf-8", errors="replace", creationflags=_NO_WINDOW,
                                            env=_env_xl)
            for dong in _sub_proc[0].stdout:
                _xl_xu_ly_dong(dong.strip(), item, _segmap, _raw_tail)
            _sub_proc[0].wait()
            ok = _sub_proc[0].returncode == 0
            ma_loi = "mã %s" % _sub_proc[0].returncode
        if ok and pha == "asr":
            # DỊCH THỦ CÔNG pha 1 xong → DỪNG chờ người dùng dịch + nhập SRT (không đánh dấu 'xong').
            item["pha_xong_asr"] = True
            item["zh_srt"] = os.path.splitext(item["path"])[0] + ".zh.srt"
            item["trang_thai"] = "cho_srt"
            item["pct"] = 50
            item["msg"] = "⏸ Chờ SRT đã dịch"
            item["step"] = "Chờ dịch thủ công"
            them_log(f"⏸ ASR xong — chờ dịch thủ công: {item['ten']}")
            return
        item["trang_thai"] = "xong" if ok else "loi"
        item["pct"] = 100 if ok else item.get("pct", 0)
        if ok and item["opts"].get("_dub_phut"):
            try:
                kdb.usage_cong("dub", 1)
                kdb.usage_cong("dub_phut", int(item["opts"]["_dub_phut"]))
            except Exception:
                pass
            item["opts"]["_dub_phut"] = 0
        threading.Thread(target=_cache_sweep_nen, daemon=True).start()   # dọn cache sau mỗi render (nền)
        if ok and item["opts"].get("phan_loai_sau"):
            _phan_loai_sau_render(item["path"])   # thread nền: đọc .vi.srt + đoán thể loại + MOVE output → TỰ dọn .srt ở cuối
        elif ok and not item["opts"].get("dich_thu_cong"):
            _don_srt_canh_video(item["path"])   # phân loại TẮT + không dịch-thủ-công → dọn .srt cạnh video ngay
        if ok and item["opts"].get("kn_giao"):
            threading.Thread(target=_kn_giao_sau_render, args=(item["path"], item["opts"]["kn_giao"]),
                             daemon=True).start()   # Kênh nguồn: giao bản render vào folder LohaPage
        if not ok:
            # LUÔN log LÝ DO lỗi (kể cả khi còn lượt tự-thử-lại) → chẩn đoán được (trước đây lỗi bị NUỐT khi
            # thử lại: chỉ thấy "↻ tự thử lại" không rõ vì sao → không biết RAM/codec/mạng). Chi tiết kỹ thuật
            # đầy đủ CHỈ khi hết lượt (đỡ spam log khi retry thành công).
            _than = _loi_than_thien(_raw_tail, ma_loi)
            _con_thu = _co_the_thu_lai(item)
            if _con_thu:
                them_log(f"⚠ Lý do lỗi (sẽ thử lại): {_than}")   # NGẮN, để biết nguyên nhân dù tự thử lại
                for _l in _raw_tail[-4:]:   # vài dòng traceback quan trọng nhất (gột tên model)
                    them_log_raw("   ⋯ " + _an_model(str(_l)))
            else:
                them_log(f"❌ Render LỖI: {item['ten']} — {_than}")   # khách thấy câu DỄ HIỂU
                them_log_raw("   ── chi tiết kỹ thuật (gửi hỗ trợ nếu cần) ──")
                for _l in _raw_tail[-15:]:   # traceback THẬT (để hỗ trợ) NHƯNG gột tên model/provider AI (giấu bí quyết)
                    them_log_raw("   ⋯ " + _an_model(str(_l)))
                item["msg"] = _than          # ô trạng thái khách: câu thân thiện, KHÔNG phải traceback
    except Exception as e:
        them_log(f"❌ Render LỖI (nội bộ): {item['ten']} — {str(e)[:140]}")
        item["trang_thai"], item["msg"] = "loi", "Render gặp lỗi không mong muốn — thử lại; nếu vẫn lỗi, sao chép log gửi hỗ trợ."
        _co_the_thu_lai(item)   # XI: còn lượt → tự đưa lại 'cho'


def _chon_va_dat_dang(lane_res=None):
    """Chọn 1 job 'cho' SẴN SÀNG + đặt 'dang' (atomic). lane_res='net'/'cpu' → chỉ nhặt job tài nguyên đó
    (guard 2-lane: ≤1 CPU-nặng). lane_res=None → nhặt bất kỳ (1-lane cũ). Trả item hoặc None."""
    with _queue_lock:
        for it in _queue:
            if it["trang_thai"] != "cho":
                continue
            if lane_res is not None and _job_resource(it.get("opts")) != lane_res:
                continue
            cand = it
            break
        else:
            return None
    # ĐỢI video tải xong (chống 'thiếu moov atom') — NGOÀI lock vì có sleep.
    if not _video_san_sang(cand["path"]):
        cand.setdefault("cho_han", time.time() + 180)
        if time.time() < cand["cho_han"]:
            cand["msg"] = "⏳ Đợi tải xong..."
            return None
        with _queue_lock:
            cand["trang_thai"], cand["msg"] = "loi", "Video hỏng/tải dở (thiếu moov atom)"
        them_log(f"⚠ Bỏ qua (tải dở/hỏng quá lâu): {cand['ten']}")
        return None
    with _queue_lock:
        if cand not in _queue or cand["trang_thai"] != "cho":
            return None
        cand["trang_thai"] = "dang"
        cand["t0"] = time.time()
        cand.pop("eta_t", None); cand.pop("eta_pct", None)
        cand.pop("cho_han", None)
        cand.pop("_cpu_free", None)   # SPLIT DUB↔ENCODE: reset cờ (job thử-lại/nạp-lại không mang cờ cũ)
        cand["msg"] = ""
        xong = sum(1 for x in _queue if x["trang_thai"] in ("xong", "loi"))
        cand["nhan"] = f"Video {xong + 1}/{len(_queue)}"
    them_log(f"▶ {cand['nhan']}: {cand['ten']}")
    _canh_bao_dia(viec="render")
    return cand


def _lane_worker(lane, lane_res):
    """1 thread/lane: nhặt job tài nguyên lane_res + render trọn. Dùng khi VC_RENDER_LANES≥2."""
    while True:
        # GUARD ≤1 CPU-nặng: nếu lane này là 'cpu' mà đã có job 'cpu' đang chạy ở lane khác → chờ.
        # SPLIT DUB↔ENCODE: job đã báo "_cpu_free" (dub xong, đang encode nvenc) KHÔNG tính là chiếm CPU nữa
        # → cho video kế bắt đầu dub trong lúc job này encode (Ý2: dub∥encode giữa 2 video).
        if lane_res == "cpu":
            with _queue_lock:
                dang_cpu = sum(1 for x in _queue
                               if x["trang_thai"] == "dang" and _job_resource(x.get("opts")) == "cpu"
                               and not x.get("_cpu_free"))
            if dang_cpu >= 1:
                time.sleep(1); continue
        item = _chon_va_dat_dang(lane_res)
        if item is None:
            time.sleep(1); continue
        _render_1_job(item, lane)


def _queue_worker():
    """1-LANE (mặc định, VC_RENDER_LANES=1): nhặt lần lượt video 'chờ' → render trọn (như cũ).
    VC_RENDER_LANES≥2: chuyển thành DISPATCHER — spawn 1 thread/lane (lane MẠNG edge ∥ lane CPU Supertonic)."""
    n_lane = _so_lane()
    if n_lane >= 2:
        # LANE 0 = CPU (Supertonic/Piper + OCR + encode); LANE 1 = MẠNG (edge/dịch). Guard ≤1 CPU-nặng.
        them_log("🚦 Scheduler %d-lane: MẠNG (edge) ∥ CPU (Supertonic) — render nhiều video song song." % n_lane)
        threading.Thread(target=_lane_worker, args=(_LANES[0], "cpu"), daemon=True).start()
        threading.Thread(target=_lane_worker, args=(_LANES[1], "net"), daemon=True).start()
        while True:
            time.sleep(3600)   # dispatcher đã spawn xong; giữ thread sống
    # --- Đường 1-LANE cũ (không đổi hành vi) ---
    while True:
        item = _chon_va_dat_dang(None)
        if item is None:
            time.sleep(1)
            continue
        _render_1_job(item, _LANES[0])


def _kill_proc_tree(proc):
    """Kill tiến trình render VÀ toàn bộ con cháu (ffmpeg/demucs/whisper).
    Bắt buộc trên Windows: xu_ly_chon.py sinh tiến trình con giữ pipe stdout mở,
    nếu chỉ terminate() tiến trình cha thì vòng đọc stdout của worker không thoát
    → video vẫn 'treo'. taskkill /T kill cả cây để mở khóa hàng đợi."""
    if proc is None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           creationflags=_NO_WINDOW,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _don_crawl_ro_ri(plat):
    """Kill browser-crawl HEADLESS RÒ RỈ còn giữ khóa profile <plat> (crawl trước bị kill/timeout/re-parent
    không đóng → profile bị khóa → preview/cào SAU ra 0 video 'không ra'). CHỈ kill tiến trình HEADLESS
    (browser crawl) — KHÔNG đụng cửa sổ login (non-headless) đang đăng nhập. Windows only; lỗi -> bỏ qua."""
    if os.name != "nt" or not plat:
        return
    # BẢO MẬT: plat được nội suy vào chuỗi lệnh PowerShell (-like '*<plat>*'). Nếu plat chứa ký tự lạ
    # (nháy đơn...) -> chèn lệnh PS. Mọi platform hợp lệ chỉ gồm [a-z0-9_]; khác -> bỏ qua (không chạy PS).
    _p = str(plat)
    if len(_p) > 20 or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789_" for ch in _p):
        return
    udd_key = f"{plat}_user_data_dir"
    try:
        ps = ("Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" -EA SilentlyContinue | "
              "Where-Object { $_.CommandLine -like '*" + udd_key + "*' -and $_.CommandLine -like '*--headless*' } | "
              "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -EA SilentlyContinue }")
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                       creationflags=_NO_WINDOW, timeout=15,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def _ocr_prefetch_worker():
    """P3 — POOL OCR TRƯỚC các video KẾ TIẾP (CPU, --chi-asr → scan-cache) SONG SONG với render (GPU/burn).
    OCR NHIỀU video kế cùng lúc (thread-limited) → video DÀI (OCR lâu) chỉ chiếm 1 slot, video ngắn phía sau vẫn
    được OCR-trước ở slot khác (KHÔNG kẹt chờ 1 video). Render tới video đã prefetch → localize HIT scan-cache → BỎ
    OCR → chồng CPU↔GPU, tăng throughput bulk. ≥4 core (máy yếu nhường render). Tắt: VC_OCR_PREFETCH=0.
    An toàn: chỉ THÊM scan-cache (không đụng render đang chạy); đua ghi cache = cùng nội dung (vô hại)."""
    if os.environ.get("VC_OCR_PREFETCH", "1") == "0":
        return
    _cores = os.cpu_count() or 0
    if _cores < 4:
        return                                                   # máy yếu → nhường CPU cho render
    # POOL: OCR NHIỀU video kế CÙNG LÚC (thread-limited) → video DÀI (OCR lâu) chỉ chiếm 1 slot, video ngắn phía
    # sau vẫn được OCR-trước ở slot khác (KHÔNG kẹt chờ 1 video). Số worker + luồng auto theo core+RAM (an toàn máy khách).
    try:
        import ocr_bulk
        _cfg = ocr_bulk.kiem_tra_cau_hinh(n_video=8, threads=2)
        _pf_th = _cfg["luong_moi_worker"]
        _pf_workers = max(1, _cfg["worker_de_xuat"] - 1)         # chừa 1 slot cho render (OCR video hiện tại nếu chưa cache + burn)
    except Exception:
        _pf_th, _pf_workers = 2, max(1, (_cores - 2) // 3)
    _pf_timeout = int(os.environ.get("VC_OCR_PREFETCH_TIMEOUT", "5400") or 5400)   # kill job treo (>1.5h) khỏi kẹt slot
    _pf_done = set()                                             # PATH đã OCR-trước (xong)
    _running = {}                                               # PATH -> (Popen, thời-điểm-bắt-đầu) đang OCR-trước
    while True:
        time.sleep(3)
        try:
            # 1) DỌN job prefetch đã xong / treo quá hạn
            for _p, (_pr, _st) in list(_running.items()):
                if _pr.poll() is not None:
                    _pf_done.add(_p); _running.pop(_p, None)
                elif time.time() - _st > _pf_timeout:
                    try: _pr.kill()
                    except Exception: pass
                    _pf_done.add(_p); _running.pop(_p, None)     # bỏ (render tự OCR nếu tới)
            # 2) CÒN SLOT + có video kế CHƯA OCR-trước → START (dedupe theo PATH: bỏ path đang render / đã xong / đang chạy).
            #    đa-ngôn-ngữ 1 video / video đang render = no-op (render + scan-cache lo).
            while len(_running) < _pf_workers:
                with _queue_lock:
                    dang_paths = {it["path"] for it in _queue if it.get("trang_thai") == "dang"}
                    nxt = next((it for it in _queue
                                if it.get("trang_thai") == "cho"
                                and it["path"] not in dang_paths
                                and it["path"] not in _pf_done
                                and it["path"] not in _running
                                and not (it.get("opts") or {}).get("dich_thu_cong")), None)
                if not dang_paths or nxt is None:                # không render / hết video kế → thôi thêm
                    break
                path, opts = nxt["path"], (nxt.get("opts") or {})
                if not os.path.exists(path):
                    _pf_done.add(path); continue
                cmd = _lenh_xu_ly(path, opts, "asr")             # --chi-asr = OCR-only → scan-cache (đúng key render)
                env = os.environ.copy()
                env["OCR_THREADS"] = str(_pf_th)                 # giới hạn luồng/worker → không giành CPU của render
                env["TARGET_LANG"] = ngngu.target_lang()
                them_log("⏩ OCR trước '%s' (%d song song)…" % ((nxt.get("ten") or "")[:34], len(_running) + 1))
                _running[path] = (subprocess.Popen(cmd, cwd=THU_MUC_GOC, env=env,
                                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL), time.time())
        except Exception:
            pass


def _translate_prefetch_worker():
    """DỊCH TRƯỚC ngôn ngữ KẾ (cùng video, tgt khác) trong lúc video hiện tại đang LỒNG TIẾNG → dịch (mạng/Gemini)
    chồng dub (CPU). Render CHÍNH ngôn ngữ đó → HIT trans-cache (localize) → BỎ dịch, tiết ~30s/ngôn ngữ.
    Khác _ocr_prefetch (dedup PATH, đa-ngôn-ngữ=no-op): ở đây dedup theo (PATH, LANG) — đúng ca đa-ngôn-ngữ.
    Gemini SERIAL (1 Chrome) → chỉ 1 prefetch/lúc. Bật khi VC_TRANSLATE_PREFETCH=1 HOẶC scheduler 2-lane bật
    (VC_RENDER_LANES≥2) — vì 2 lane cùng dịch = 2 Chrome (vi phạm Gemini-serial); prefetch TẬP TRUNG giữ 1 Chrome,
    2 lane render chỉ ĐỌC trans-cache (bỏ bước dịch)."""
    if os.environ.get("VC_TRANSLATE_PREFETCH", "0") != "1" and _so_lane() < 2:
        return
    if (os.cpu_count() or 0) < 4:
        return
    _tp_done = set()                                             # (path, lang) đã prefetch
    _tp_running = None                                           # (key, Popen, start) — 1 lúc (Gemini serial)
    _tp_timeout = int(os.environ.get("VC_TRANSLATE_PREFETCH_TIMEOUT", "1800") or 1800)

    def _k(it):
        return (it["path"], (it.get("opts") or {}).get("lang", ""))

    while True:
        time.sleep(3)
        try:
            if _tp_running is not None:
                _key, _pr, _st = _tp_running
                if _pr.poll() is not None or (time.time() - _st > _tp_timeout):
                    if _pr.poll() is None:
                        try: _pr.kill()
                        except Exception: pass
                    _tp_done.add(_key); _tp_running = None
            if _tp_running is None:
                with _queue_lock:
                    # DỊCH TRƯỚC TẤT CẢ ngôn ngữ đã chọn NGAY (KHÔNG cần đợi video nào render) — vì srt zh dùng
                    # CHUNG (scan-cache): Gemini dịch xong ngôn ngữ này → dịch NGAY ngôn ngữ kế (1 Chrome, serial).
                    # → tới lúc render, mọi ngôn ngữ đã có trans-cache → lane render KHÔNG BAO GIỜ đợi dịch.
                    nxt = next((it for it in _queue
                                if it.get("trang_thai") in ("cho", "dang")   # kể cả video đang render (dịch ngôn ngữ KHÁC nó)
                                and _k(it) not in _tp_done
                                and (it.get("opts") or {}).get("lang")            # chỉ job đa-ngôn-ngữ (có lang)
                                and not (it.get("opts") or {}).get("dich_thu_cong")
                                and not (it.get("opts") or {}).get("dich_lai")), None)  # dich_lai=bỏ cache→prefetch vô ích
                if nxt is not None:
                    path, opts = nxt["path"], (nxt.get("opts") or {})
                    if not os.path.exists(path):
                        _tp_done.add(_k(nxt))
                    else:
                        cmd = _lenh_xu_ly(path, opts, None) + ["--chi-dich"]   # full transform (seed khớp render chính) + chỉ-dịch
                        env = os.environ.copy()
                        env["TARGET_LANG"] = opts.get("lang") or ngngu.target_lang()
                        them_log("⏩ Dịch trước '%s' (%s)…" % ((nxt.get("ten") or "")[:30], opts.get("lang")))
                        _tp_running = (_k(nxt), subprocess.Popen(
                            cmd, cwd=THU_MUC_GOC, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL), time.time())
        except Exception:
            pass


def _dub_prefetch_worker():
    """DUB-PREFETCH cho ngôn ngữ EDGE (mạng, nhẹ): tạo TRƯỚC dub.wav (--chi-dub → OCR/dịch cache → DUB → dub-cache,
    KHÔNG encode) trong lúc lane render đang encode video khác → render CHÍNH ngôn ngữ đó HIT dub-cache → BỎ dub,
    chỉ encode+ghép. Edge = I/O mạng (không GPU/CPU nặng) nên prefetch KHÔNG tranh render (user chỉ ra đúng).

    BƯỚC 1 (kế hoạch user — ít rủi ro nhất): GIỮ NGUYÊN _dub_key, dùng ĐÚNG _lenh_xu_ly hiện tại (env khớp render
    → cache khớp, như translate-prefetch đã proven). CHỈ thêm worker; render KHÔNG sửa. Nếu render MISS → BƯỚC 2
    điều tra cache-key (KHÔNG đổi _dub_key trước khi chứng minh nó là nguyên nhân).

    CHỐNG THROTTLE (user chốt "serial + chỉ khi không có job edge đang dub"): SERIAL (1 dub-prefetch/lúc) + BỎ QUA
    khi CÓ job edge đang render/dub (tránh 2 luồng edge-tts cùng lúc → 'No audio'). CHỈ job edge (Supertonic bỏ qua
    — CPU nặng, prefetch sẽ nghẽn render). GATE: bật khi VC_DUB_PREFETCH=1 HOẶC scheduler 2-lane (VC_RENDER_LANES≥2)."""
    if os.environ.get("VC_DUB_PREFETCH", "0") != "1" and _so_lane() < 2:
        return
    _dp_done = set()          # (path, lang) đã prefetch dub
    _dp_running = None        # (key, Popen, start)
    _dp_timeout = int(os.environ.get("VC_DUB_PREFETCH_TIMEOUT", "2400") or 2400)

    def _k(it):
        return (it["path"], (it.get("opts") or {}).get("lang", ""))

    def _la_edge(opts):
        return _job_resource(opts) == "net"   # edge = 'net' (mạng); Supertonic/piper = 'cpu'

    while True:
        time.sleep(3)
        try:
            if _dp_running is not None:
                _key, _pr, _st = _dp_running
                if _pr.poll() is not None or (time.time() - _st > _dp_timeout):
                    if _pr.poll() is None:
                        try: _pr.kill()
                        except Exception: pass
                    _dp_done.add(_key); _dp_running = None
            if _dp_running is None:
                with _queue_lock:
                    # CHỈ prefetch khi KHÔNG có job EDGE nào đang render (dang) → tránh 2 luồng edge-tts = throttle.
                    co_edge_dang = any(x["trang_thai"] == "dang" and _la_edge(x.get("opts"))
                                       for x in _queue)
                    nxt = None
                    if not co_edge_dang:
                        nxt = next((it for it in _queue
                                    if it.get("trang_thai") in ("cho", "dang")
                                    and _k(it) not in _dp_done
                                    and (it.get("opts") or {}).get("lang")
                                    and (it.get("opts") or {}).get("long_tieng")   # có lồng tiếng
                                    and _la_edge(it.get("opts"))                    # CHỈ edge (mạng)
                                    and not (it.get("opts") or {}).get("dich_thu_cong")
                                    and not (it.get("opts") or {}).get("dich_lai")), None)
                if nxt is not None:
                    path, opts = nxt["path"], (nxt.get("opts") or {})
                    if not os.path.exists(path):
                        _dp_done.add(_k(nxt))
                    else:
                        cmd = _lenh_xu_ly(path, opts, None) + ["--chi-dub"]   # full transform (seed khớp render) + chỉ-dub
                        env = os.environ.copy()
                        env["TARGET_LANG"] = opts.get("lang") or ngngu.target_lang()
                        them_log("⏩ Lồng tiếng trước '%s' (%s)…" % ((nxt.get("ten") or "")[:28], opts.get("lang")))
                        _dp_running = (_k(nxt), subprocess.Popen(
                            cmd, cwd=THU_MUC_GOC, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL), time.time())
        except Exception:
            pass


# ---- METRICS REAL-TIME (biểu đồ tab Tiến trình): CPU%/GPU%/Mạng. Lấy mẫu nền ~1.5s KHI có render 'dang'.
# CPU = thong_tin_may (dep-free ctypes); GPU = nvidia-smi (None nếu không NVIDIA); Mạng = số bản edge đang dub
# (tín hiệu scheduler — bao nhiêu video đang lồng tiếng qua mạng cùng lúc). Idle → dừng lấy mẫu (0 overhead).
_metric_hist = []                 # [{"cpu":int,"gpu":int|None,"net":int}, ...] tối đa 80 mẫu
_metric_lock = threading.Lock()


def _gpu_pct():
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=4, creationflags=_NO_WINDOW)
        return int(float((r.stdout or "0").strip().splitlines()[0]))
    except Exception:
        return None


def _metric_worker():
    """Nền: khi có render 'dang' → lấy mẫu CPU/GPU/Mạng vào ring buffer cho biểu đồ real-time. Idle → xả buffer."""
    try:
        _cpu = thong_tin_may.TheoDoiCpu(); _cpu.phan_tram()      # mồi delta
    except Exception:
        _cpu = None
    while True:
        time.sleep(1.5)
        try:
            with _queue_lock:
                dang = [x for x in _queue if x["trang_thai"] == "dang"]
                netj = sum(1 for x in dang if _job_resource(x.get("opts")) == "net" and not x.get("_cpu_free"))
            if not dang:
                with _metric_lock:
                    if _metric_hist:
                        _metric_hist.clear()
                continue
            cpu = _cpu.phan_tram() if _cpu else None
            gpu = _gpu_pct()
            with _metric_lock:
                _metric_hist.append({"cpu": cpu, "gpu": gpu, "net": netj})
                if len(_metric_hist) > 80:
                    _metric_hist.pop(0)
        except Exception:
            pass


def _khoi_dong_queue():
    _queue_nap()                                                 # khôi phục hàng đợi render dở (XIX)
    threading.Thread(target=_queue_worker, daemon=True).start()
    threading.Thread(target=_queue_saver, daemon=True).start()   # lưu bền định kỳ (bắt đổi trạng thái worker)
    threading.Thread(target=_ocr_prefetch_worker, daemon=True).start()   # P3: OCR trước video kế tiếp song song render
    threading.Thread(target=_translate_prefetch_worker, daemon=True).start()   # dịch trước ngôn ngữ kế (gate OFF mặc định)
    threading.Thread(target=_dub_prefetch_worker, daemon=True).start()   # lồng tiếng trước ngôn ngữ EDGE (mạng) — BƯỚC 1
    threading.Thread(target=_metric_worker, daemon=True).start()   # metrics real-time cho biểu đồ tab Tiến trình
    threading.Thread(target=_tl_probe_worker, daemon=True).start()   # probe thoi luong video NEN (list khong cho ffprobe)


# ================= HÀNG ĐỢI TÁC VỤ (TaskQueue chung) — scheduler 1 worker, chờ→đang→xong/lỗi =================
# Hiện hỗ trợ kind='crawl': xếp hàng NHIỀU job cào (Douyin/Bili...) để user bấm + đi ngủ, KHÔNG ngồi canh.
# TÁI DÙNG chay_crawl NGUYÊN VẸN (worker chỉ điều phối: gọi chay_crawl + đợi _proc xong) → KHÔNG đụng crawl logic.
# Render vẫn dùng _queue riêng (gộp sau khi ổn định). Thêm kind render/translate/tts = thêm 1 nhánh trong
# _task_worker, KHÔNG viết scheduler mới. Persist ra DATA_DIR (userData ghi được; app-src READ-ONLY) → resume
# hàng đợi sau khi mở lại app.
_tasks = []                       # [{id,kind,nhan,platform,type,input,count,opts,trang_thai,pct,msg,ts}]
_task_lock = threading.Lock()
_task_id = 0


def _task_file():
    try:
        return os.path.join(DATA_DIR, "_task_queue.json")
    except Exception:
        return os.path.join(THU_MUC_GOC, "_task_queue.json")


def _task_luu():
    try:
        with _task_lock:
            snap = list(_tasks)[-300:]
        tmp = _task_file() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False)
        os.replace(tmp, _task_file())
    except Exception:
        pass


def _task_nap():
    global _tasks, _task_id
    try:
        p = _task_file()
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                arr = json.load(f)
            for t in arr:
                if t.get("trang_thai") == "dang":   # đang chạy lúc tắt app -> cho chạy lại
                    t["trang_thai"], t["pct"], t["msg"] = "cho", 0, ""
            _tasks = arr
            _task_id = max([t.get("id", 0) for t in _tasks] or [0])
    except Exception:
        _tasks = []


def _task_them(kind, **fields):
    global _task_id
    with _task_lock:
        _task_id += 1
        t = {"id": _task_id, "kind": kind, "trang_thai": "cho", "pct": 0, "msg": "", "ts": int(time.time())}
        t.update(fields)
        _tasks.append(t)
        tid = _task_id
    _task_luu()
    return tid


def _task_worker():
    """1 worker tuần tự: lấy task 'cho' -> chạy -> 'xong'/'lỗi'. kind='crawl' = chay_crawl + đợi _proc xong."""
    while True:
        cand = None
        with _task_lock:
            busy = _proc is not None or _dang_cao or any(t["trang_thai"] == "dang" for t in _tasks)
            if not busy and not _task_pause["on"]:   # Stop-After-Current: tạm nghỉ → không lấy task mới
                cand = next((t for t in _tasks if t["trang_thai"] == "cho"), None)
        if cand is None:
            time.sleep(1)
            continue
        # LOGIN-AWARE (cho overnight): trước khi cào, kiểm login NỀN này. Hết phiên → KHÔNG cào rỗng âm thầm
        # mà đánh task "🔒 Cần đăng nhập <nền>" RÕ RÀNG + BỎ QUA mọi task CÙNG NỀN còn chờ (gần như cũng fail),
        # VẪN chạy task nền KHÁC. yt/tt qua yt-dlp công khai → luôn bỏ qua check. fb: "Theo link" (type≠creator)
        # chạy ẩn danh tốt → bỏ qua; "Theo kênh" (type=creator) bị Facebook chặn cứng khi ẩn danh (đã verify
        # THẬT — chỉ ra ~1 video) → CẦN check login như dy/bili (mirror kỹ thuật, không đoán).
        if cand.get("kind") == "crawl":
            _plat = cand.get("platform", "dy")
            _bo_qua_check = _plat in ("yt", "tt") or (_plat == "fb" and cand.get("type") != "creator")
            if not _bo_qua_check and _trang_thai_1lan(_plat) == "out":
                _ten = NEN_TANG.get(_plat, {}).get("ten", _plat)
                with _task_lock:
                    cand["trang_thai"], cand["msg"], cand["reason"] = "loi", f"🔒 Cần đăng nhập {_ten}", "login_expired"
                    for _t in _tasks:
                        if _t.get("trang_thai") == "cho" and _t.get("kind") == "crawl" and _t.get("platform") == _plat:
                            _t["trang_thai"], _t["msg"], _t["reason"] = "loi", f"⏸ Bỏ qua — cần đăng nhập {_ten}", "login_expired"
                _task_luu()
                continue
        with _task_lock:
            cand["trang_thai"], cand["msg"] = "dang", "Đang chạy..."
        _task_luu()
        try:
            if cand.get("kind") == "crawl":
                cfg = {"platform": cand.get("platform", "dy"), "type": cand.get("type", "search"),
                       "input": cand.get("input", ""), "count": cand.get("count", 10), "force": True}
                cfg.update(cand.get("opts") or {})
                r = chay_crawl(cfg) or {}
                if not r.get("ok"):
                    raise RuntimeError(r.get("msg") or "Cào lỗi")
                t0 = time.time()
                while _proc is not None or _dang_cao:   # đợi crawl nền (chay_crawl spawn _crawl_worker) xong
                    if cand.get("cancel"):              # user bấm Huỷ → dung_crawl đã/đang kill _proc
                        break
                    if _tien_do_cao.get("msg"):        # mirror tiến độ crawl ("📊 N/M · MB/s · còn ~Zm") lên task
                        with _task_lock:
                            cand["msg"], cand["pct"] = _tien_do_cao["msg"], _tien_do_cao.get("pct", 0)
                    time.sleep(1.5)
                    if time.time() - t0 > 7200:          # trần 2h/job (an toàn, không treo vĩnh viễn)
                        cand["reason"] = "timeout"
                        break
                with _task_lock:
                    if cand.get("cancel"):
                        cand["trang_thai"], cand["msg"], cand["reason"] = "loi", "⛔ Đã huỷ", "cancelled"
                    elif cand.get("reason") == "timeout":
                        cand["trang_thai"], cand["msg"] = "loi", "⏱ Quá 2h — đã dừng"
                    else:
                        cand["trang_thai"], cand["pct"], cand["msg"], cand["reason"] = "xong", 100, "Hoàn tất", ""
            else:
                with _task_lock:
                    cand["trang_thai"], cand["msg"], cand["reason"] = "loi", "kind chưa hỗ trợ: " + str(cand.get("kind")), "error"
        except Exception as e:
            with _task_lock:
                cand["trang_thai"], cand["msg"], cand["reason"] = "loi", str(e)[:160], "error"
        _task_luu()


def _khoi_dong_task():
    _task_nap()
    threading.Thread(target=_task_worker, daemon=True).start()


# ---------------- TỰ ĐỘNG GOM ĐĂNG BÀI (nền, định kỳ) — vá khúc ĐỨT Cào→Render→[GOM]→LoHa ----------------
# gom_dang_bai.gom() idempotent (sổ _da_gom.txt dedup) → chạy lại an toàn. Thread NỀN ĐỘC LẬP, KHÔNG đụng
# _queue_worker (render) để tránh xung đột session khác. _gom_lock serialize gom-tay (/api/trang_gom) vs gom-tự.
_gom_lock = threading.Lock()
try:
    _AUTOGOM_INTERVAL = max(60, int(os.environ.get("VC_AUTOGOM_SEC", "600")))   # mặc định 10 phút
except ValueError:
    _AUTOGOM_INTERVAL = 600


def _loha_auto_uploads():
    """TỰ DÒ thư mục uploads của LoHa Page. Ưu tiên: uploads_path tùy chỉnh trong data.db của LoHa → else
    %APPDATA%\\LohaAutomation\\uploads (mặc định). Trả path TỒN TẠI hoặc ''."""
    app = os.environ.get("APPDATA") or ""
    local = os.environ.get("LOCALAPPDATA") or ""
    cands = []
    db = os.path.join(app, "LohaAutomation", "data.db")
    if os.path.isfile(db):
        try:
            import sqlite3
            con = sqlite3.connect("file:%s?mode=ro" % db.replace("\\", "/"), uri=True, timeout=1)
            try:
                row = con.execute("SELECT value FROM config WHERE key='uploads_path'").fetchone()
                if row and (row[0] or "").strip():
                    cands.append(row[0].strip())
            finally:
                con.close()
        except Exception:
            pass
    cands += [os.path.join(app, "LohaAutomation", "uploads"),
              os.path.join(local, "LohaAutomation", "uploads"),
              os.path.join(app, "loha-automation", "uploads")]
    for p in cands:
        if p and os.path.isdir(p):
            return p.replace("\\", "/")
    return ""


def _chay_gom(dry_run=False, im_lang_khi_rong=False):
    """Chạy gom_dang_bai.gom() CÓ KHOÁ (chống đua gom-tay ↔ gom-tự). Trả (kq, lines).
    im_lang_khi_rong=True → nuốt dòng 'Không có video mới' cho lần auto định kỳ (đỡ spam log)."""
    import gom_dang_bai
    lines = []

    def _lg(m):
        if im_lang_khi_rong and "Không có video mới" in m:
            return
        them_log(m)
        lines.append(m)

    _tl_muc, _ = _pl_folders()                    # thể loại (phân loại) → {tên: folder} cho gom Kiểu 2
    the_loai_paths = {m["ten"]: m["path"] for m in _tl_muc}
    with _gom_lock:
        kq = gom_dang_bai.gom(dry_run=dry_run, log=_lg, the_loai_paths=the_loai_paths)
    return kq, lines


def _auto_gom_worker():
    while True:
        time.sleep(_AUTOGOM_INTERVAL)
        try:
            import gom_dang_bai
            if not gom_dang_bai.doc_config().get("auto_gom"):
                continue
            if not _can_lohapage():          # gate LohaPage: gom→đăng cần quyền
                continue
            _chay_gom(dry_run=False, im_lang_khi_rong=True)
        except Exception as e:
            try:
                them_log("Auto-gom lỗi: %s" % str(e)[:80])
            except Exception:
                pass


def _khoi_dong_auto_gom():
    threading.Thread(target=_auto_gom_worker, daemon=True).start()


# ---------------- TỰ ĐỘNG KIỂM TRA LOGIN (live, nền, mỗi 3') — giữ _login_check.json LUÔN TƯƠI ----------------
# GỐC "xanh giả": khi cache live >5' (cũ) → badge/guardLogin rơi về đọc COOKIE ĐĨA, mà cookie (sessionid/
# SESSDATA/web_session) CÒN trên đĩa dù phiên đã chết → báo "in" OAN. Re-check live mỗi 3' giữ cache <5'
# (badge KHÔNG bao giờ phải đọc cookie cũ) + bắt phiên chết (nền "in" hoá "out" trong ≤3').
try:
    _LOGIN_RECHECK_SEC = max(60, int(os.environ.get("VC_LOGIN_RECHECK_SEC", "180")))
except ValueError:
    _LOGIN_RECHECK_SEC = 180
_LOGIN_RECHECK_PLATS = ["dy", "bili", "xhs", "rednote", "wb"]


def _login_recheck_worker():
    lc = os.path.join(THU_MUC_GOC, "_login_check.json")
    while True:
        time.sleep(_LOGIN_RECHECK_SEC)
        try:
            if _proc is not None or _dang_cao:
                continue   # ĐANG CÀO = giữ khóa profile → KHÔNG mở Chromium ngầm (tránh đè "out" oan + lock);
                           # lúc cào login không đổi nên bỏ qua an toàn. Chu kỳ rảnh kế sẽ refresh.
            cur = {}
            try:
                with open(lc, encoding="utf-8") as f:
                    cur = json.load(f) or {}
            except Exception:
                cur = {}
            # Re-check nền ĐANG "in" (rủi ro xanh-giả). Cache rỗng (chưa từng check) → check HẾT để bơm live.
            plats = [p for p in _LOGIN_RECHECK_PLATS if cur.get(p) == "in"] if cur else list(_LOGIN_RECHECK_PLATS)
            # Bỏ nền đang MỞ cửa sổ login (profile bận) → để mo_dang_nhap lo, khỏi đè.
            plats = [p for p in plats if not (_login_procs.get(p) and _login_procs[p].poll() is None)]
            if not plats:
                # Không có nền cần xác minh → vẫn LÀM TƯƠI mtime cache (badge khỏi rơi về cookie đĩa cũ).
                try:
                    if cur:
                        with open(lc, "w", encoding="utf-8") as f:
                            json.dump(cur, f, ensure_ascii=False)
                except Exception:
                    pass
                continue
            subprocess.run([PYTHON_VENV, "kiem_tra_login.py", *plats],
                           cwd=THU_MUC_GOC, capture_output=True, creationflags=_NO_WINDOW, timeout=180)
        except Exception:
            pass


def _khoi_dong_login_recheck():
    threading.Thread(target=_login_recheck_worker, daemon=True).start()


# ---------------- TỰ ĐỘNG RENDER (daemon nền, liên tục) ----------------
AUTO_CFG = os.path.join(THU_MUC_GOC, "auto_render_config.json")
_auto = {"on": False, "unlimited": True, "count": 0, "opts": {}, "da_them": 0}
_auto_lock = threading.RLock()   # RLock: _luu_auto() có thể gọi bên trong with _auto_lock → tránh deadlock
_auto_seen = set()            # path đã đẩy vào hàng đợi phiên này (tránh lặp)
_AUTO_INTERVAL = 20           # giây giữa 2 lần quét video mới


def _luu_auto():
    try:
        with _auto_lock:
            d = {k: _auto[k] for k in ("on", "unlimited", "count", "opts", "da_them")}
        with open(AUTO_CFG, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    except OSError:
        pass


def _nap_auto():
    try:
        with open(AUTO_CFG, encoding="utf-8") as f:
            d = json.load(f)
        with _auto_lock:
            for k in ("on", "unlimited", "count", "opts", "da_them"):
                if k in d:
                    _auto[k] = d[k]
    except (OSError, ValueError):
        pass


def _la_video_goc(name):
    low = name.lower()
    return _la_video(name) and not low.endswith(("_xuly.mp4", "_phude.mp4", "_longtieng.mp4"))


def _la_bam_clip(path):
    """True nếu `path` là OUTPUT của cat_nho.py (clip đã băm): nằm trong folder tên đúng 'clip_nho', hoặc
    tên khớp quy ước '<gốc>_cảnhNN[_TxT].mp4'. Dùng để CHẶN auto-workflow băm LẠI clip đã băm — nếu không,
    khi render clip chưa kịp xong (chậm/lỗi/app restart giữa chừng) thì clip vẫn 'chưa render' → cycle sau
    bị tính là 'video gốc mới' → băm tiếp → clip_nho/clip_nho/clip_nho... (đệ quy, ngốn ổ đĩa)."""
    import re as _re
    parent = os.path.basename(os.path.dirname(path))
    if parent.lower() == "clip_nho":
        return True
    return bool(_re.search(r"_c[aả]nh\d{2}(_\d+x\d+)?\.mp4$", os.path.basename(path), _re.I))


def _xl_base(name):
    """Tên gốc (bỏ thư mục + đuôi _xuly/_phude/_longtieng + ' (N)') để KHỚP video gốc ↔ bản render kể cả khi
    output đã bị phân-loại MOVE sang folder thể loại. Mirror _xlBase (JS)."""
    import re as _re
    n = os.path.splitext(os.path.basename(name or ""))[0]
    n = _re.sub(r"_(xuly|phude|longtieng|mix|dub|goc)$", "", n, flags=_re.I)
    n = _re.sub(r" \(\d+\)$", "", n)
    return n.lower()


def _auto_ung_vien():
    """Video GỐC CHƯA render — chưa có bản _xuly/_phude/_longtieng Ở BẤT KỲ ĐÂU (cạnh gốc / processed / out_dir /
    folder thể loại). KHÔNG chỉ check cạnh-gốc: sau phân-loại output bị MOVE đi → check cạnh-gốc TRƯỢT → auto
    render LẠI (đẻ '(N)') mỗi lần quét/khởi động (audit Workflow-H1). liet_ke_file đã quét cả out_dir đã đăng ký."""
    files = liet_ke_file(gioi_han=100000)
    da = set()
    for it in files:
        if (it.get("name") or "").lower().endswith(("_xuly.mp4", "_phude.mp4", "_longtieng.mp4")):
            da.add(_xl_base(it.get("name", "")))
    ds = []
    for it in files:
        if it.get("nhom") != "Cào gốc" or not _la_video_goc(it["name"]):
            continue
        if _xl_base(it["name"]) in da:        # đã có bản render (kể cả đã move) → bỏ qua, KHÔNG render lại
            continue
        ds.append(os.path.join(THU_MUC_GOC, it["p"].replace("/", os.sep)))
    return ds


def _auto_quet_mot_lan():
    """Một lượt: đưa video gốc chưa render vào hàng đợi theo cấu hình _auto. Trả số video vừa thêm."""
    with _auto_lock:
        on, unlimited, count, da = _auto["on"], _auto["unlimited"], _auto["count"], _auto["da_them"]
        opts = dict(_auto["opts"])
    if not on:
        return 0
    con_lai = 10 ** 9 if unlimited else max(0, count - da)
    them = 0
    if con_lai > 0:
        with _queue_lock:
            trong_q = {it["path"] for it in _queue}
        for full in _auto_ung_vien():
            if them >= con_lai:
                break
            if full in trong_q or full in _auto_seen:
                continue
            # HẠN MỨC LỒNG TIẾNG: trước đây auto _queue_them thẳng opts (long_tieng) → BỎ QUA quota →
            # free/expired lồng tiếng vô hạn qua auto. Lọc như workflow/AI: hết quota → vẫn render nhưng
            # TẮT long_tieng (không bỏ video, auto vẫn tiến). pro/unlimited: phut=0 → giữ nguyên hành vi.
            o = dict(opts)
            if o.get("long_tieng"):
                _nhan_a, _bo_a, _msg_a = _dub_quota_loc([full], True)
                if not _nhan_a:
                    o["long_tieng"] = False
                elif _nhan_a[0][1]:
                    o["_dub_phut"] = _nhan_a[0][1]
            _queue_them(full, o)
            _auto_seen.add(full)
            them += 1
        if them:
            with _auto_lock:
                _auto["da_them"] += them
            them_log(f"🤖 Tự động: đưa {them} video vào hàng đợi.")
            _luu_auto()
    with _auto_lock:
        if _auto["on"] and not _auto["unlimited"] and _auto["da_them"] >= _auto["count"]:
            _auto["on"] = False
            them_log(f"✅ Tự động: đã đưa đủ {_auto['count']} video — dừng theo dõi.")
            _luu_auto()
    return them


# ===== WORKFLOW (Quy trình) — orchestrator NỀN chạy 1 flow on-demand. Tab MỚI, gọi LẠI hạ tầng sẵn có
# (_auto_ung_vien nguồn · cat_nho băm · _queue_them render · _chay_gom xuất) — KHÔNG đụng auto-chain session khác. =====
_wf_lock = threading.Lock()
_wf = {"running": False, "blocks": {}, "summary": "", "error": "", "stop": False}
# Tự động chạy CẢ quy trình (vòng nền): định kỳ lấy video chưa-xử-lý → chạy băm→render→xuất theo block đang bật.
_wfauto_lock = threading.Lock()
_wfauto = {"on": False, "blocks": [], "render_opts": {}, "interval": 10, "last": 0.0, "max_moi_lan": 0}
_wfauto_seen = set()
_wfauto_started = False
FILE_WFAUTO = os.path.join(_SETTINGS_DIR, "workflow_auto.json")


def _wf_set(bid, **kw):
    with _wf_lock:
        b = _wf["blocks"].setdefault(bid, {"s": "", "msg": "", "secs": 0, "log": ""})
        b.update(kw)


def _wf_log(bid, line):
    with _wf_lock:
        b = _wf["blocks"].setdefault(bid, {"s": "", "msg": "", "secs": 0, "log": ""})
        b["log"] = (b["log"] + line + "\n")[-4000:]


def _wf_bam_mot(video, ratio="", so_ban=0):
    """Băm 1 video qua cat_nho.py (CLI đã có) → trả list path clip.
    so_ban>0 → chia ĐÚNG N bản (theo ô 'Số clip mong muốn' của UI); =0 → gom theo cảnh (~40s)."""
    out_dir = _bam_out_dir(video) or os.path.join(
        DATA_DIR, "bam_nho", os.path.splitext(os.path.basename(video))[0])
    os.makedirs(out_dir, exist_ok=True)
    cmd = [PYTHON_VENV, _BAM_SCRIPT, video, out_dir, "--nguong", "27", "--chinh-xac"]
    if so_ban and int(so_ban) > 0:
        cmd += ["--so-ban", str(int(so_ban))]
    else:
        cmd += ["--muc-tieu", "40"]
    if ratio:
        cmd += ["--ratio", ratio]
    try:
        subprocess.run(cmd, cwd=THU_MUC_GOC, creationflags=_NO_WINDOW,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3600)
    except Exception as e:
        _wf_log("bam", "Lỗi băm: " + str(e))
    return [c["p"] for c in _bam_liet_clip(out_dir)]


def _wf_chay(blocks, render_opts, videos_override=None):
    """Chạy tuần tự các block: nguon(taive) → [bam] → render → [xuat]. Cập nhật _wf['blocks'] cho UI poll.
    videos_override: nếu có (vòng TỰ ĐỘNG) → BỎ bước lấy nguồn, dùng đúng list này cho [băm]→render→[xuất]."""
    import time as _t
    ids = [b["id"] for b in blocks]
    bmap = {b["id"]: b for b in blocks}
    cur = None
    try:
        arts = None
        # ---- NGUỒN ----
        if videos_override is not None:
            arts = list(videos_override)
            if "nguon" in ids:
                _wf_set("nguon", s="done", msg="%d video (tự động)" % len(arts))
        elif "nguon" in ids:
            cur = "nguon"; t0 = _t.time(); _wf_set("nguon", s="run", msg="Đang lấy danh sách…")
            ch = bmap["nguon"].get("choice"); ncfg = bmap["nguon"].get("cfg") or {}
            if ch == "taive":
                arts = _auto_ung_vien()
                _wf_set("nguon", s="done", msg="%d video chưa render" % len(arts), secs=int(_t.time() - t0))
            elif ch == "folder":
                import glob as _g
                fp = (ncfg.get("folder") or "").strip()
                arts = sorted(_g.glob(os.path.join(fp, "**", "*.mp4"), recursive=True)) if fp and os.path.isdir(fp) else []
                _wf_set("nguon", s="done", msg="%d video trong folder" % len(arts), secs=int(_t.time() - t0))
            elif ch in ("cao", "nhap", "kenh"):
                _ty = {"cao": "search", "nhap": "detail", "kenh": "creator"}[ch]
                _inp = (ncfg.get("keyword") if ch == "cao" else ncfg.get("kenh") if ch == "kenh" else ncfg.get("links")) or ""
                if not _inp.strip():
                    _wf_set("nguon", s="err", msg="Chưa nhập %s." % ("từ khóa" if ch == "cao" else "link"))
                    raise RuntimeError("Nguồn thiếu nội dung")
                before = set(_auto_ung_vien())
                _wf_set("nguon", s="run", msg="Đang cào video…")
                r = chay_crawl({"platform": ncfg.get("platform", "dy"), "type": _ty,
                                "input": _inp, "count": str(ncfg.get("so_video", 10)), "force": True})
                if not (r and r.get("ok")):
                    _wf_set("nguon", s="err", msg=(r or {}).get("msg", "Không cào được"))
                    raise RuntimeError("Cào lỗi")
                while True:                       # chờ cào xong (poll cờ toàn cục)
                    if _wf["stop"]:
                        raise RuntimeError("Đã dừng")
                    with _crawl_lock:
                        xong = _proc is None and not _dang_cao
                    if xong:
                        break
                    _t.sleep(2)
                arts = [p for p in _auto_ung_vien() if p not in before]
                _wf_set("nguon", s="done", msg="Cào được %d video mới" % len(arts), secs=int(_t.time() - t0))
            else:
                _wf_set("nguon", s="err", msg="Nguồn '%s' chưa hỗ trợ" % ch)
                raise RuntimeError("Nguồn '%s' chưa hỗ trợ" % ch)
        if not arts:
            if "nguon" in ids:
                _wf_set("nguon", s="err", msg="Không có video gốc chưa render.")
            raise RuntimeError("Không có video đầu vào.")
        # ---- BĂM (tùy) ----
        if "bam" in ids:
            cur = "bam"; t0 = _t.time(); _wf_set("bam", s="run", msg="Đang băm…")
            # Quy trình: LUÔN cắt theo cảnh (so_ban=0). Số clip cố định chỉ có ở tab Băm nhỏ riêng.
            _bam_ratio = (bmap["bam"].get("cfg") or {}).get("ratio") or ""
            segs = []
            for i, v in enumerate(arts, 1):
                if _wf["stop"]:
                    raise RuntimeError("Đã dừng")
                _wf_set("bam", msg="Băm video %d/%d" % (i, len(arts)))
                out = _wf_bam_mot(v, ratio=_bam_ratio)
                _wf_log("bam", "%s → %d clip" % (os.path.basename(v), len(out)))
                segs += out
            arts = segs or arts
            _wf_set("bam", s="done", msg="%d đoạn" % len(arts), secs=int(_t.time() - t0))
        # ---- RENDER ----
        if "render" in ids:
            cur = "render"; t0 = _t.time(); _wf_set("render", s="run", msg="Xếp hàng đợi…")
            # HẠN MỨC LỒNG TIẾNG (chung /api/dub): render_opts.long_tieng → lọc theo quota, bỏ phần vượt.
            _lt_wf = bool((render_opts or {}).get("long_tieng"))
            _nhan_wf, _bo_wf, _msg_wf = _dub_quota_loc(list(arts), _lt_wf)
            if _bo_wf:
                _wf_log("render", "⚠ Bỏ %d video vượt hạn mức lồng tiếng gói %s." % (_bo_wf, TIER.upper()))
            _phut_wf = dict(_nhan_wf)
            arts = [p for p, _ in _nhan_wf]
            my = []
            for v in arts:
                if _wf["stop"]:
                    raise RuntimeError("Đã dừng")
                o = dict(render_opts or {})
                _nt = _nen_tang_seg_tu_path(v)
                o.setdefault("out_dir", os.path.join(PROCESSED_DIR, _nt or "khac"))
                if _lt_wf and _phut_wf.get(v):
                    o["_dub_phut"] = _phut_wf[v]
                _queue_them(v, o)
                with _queue_lock:
                    my.append(_queue_id)
            while my:
                if _wf["stop"]:
                    raise RuntimeError("Đã dừng")
                with _queue_lock:
                    mine = [it for it in _queue if it["id"] in my]
                    done = [it for it in mine if it["trang_thai"] in ("xong", "loi")]
                _wf_set("render", msg="Render %d/%d video" % (len(done), len(my)))
                if not mine or len(done) >= len(my):
                    break
                _t.sleep(2)
            with _queue_lock:
                loi = sum(1 for it in _queue if it["id"] in my and it["trang_thai"] == "loi")
            _wf_set("render", s="done", secs=int(_t.time() - t0),
                    msg=("Xong %d/%d" % (len(my) - loi, len(my))) + ((" · %d lỗi" % loi) if loi else ""))
        # ---- XUẤT (tùy) ----
        if "xuat" in ids:
            cur = "xuat"; t0 = _t.time(); _wf_set("xuat", s="run", msg="Đang gom đăng bài…")
            _chay_gom(dry_run=False)
            _wf_set("xuat", s="done", msg="Đã gom bản render", secs=int(_t.time() - t0))
        with _wf_lock:
            _wf["summary"] = "✅ Hoàn tất quy trình."
    except Exception as e:
        if cur:
            _wf_set(cur, s="err", msg=str(e))
        with _wf_lock:
            _wf["error"] = str(e)
    finally:
        with _wf_lock:
            _wf["running"] = False


def _wf_auto_worker():
    """Vòng nền TỰ ĐỘNG chạy CẢ quy trình: định kỳ lấy video gốc chưa render (chưa xử lý) → chạy
    [băm]→render→[xuất] theo block đang bật. Dedup _wfauto_seen để không xử lý lại."""
    import time as _t
    while True:
        _t.sleep(20)
        try:
            with _wfauto_lock:
                on, iv, last = _wfauto["on"], _wfauto["interval"], _wfauto["last"]
                blocks, ropts = list(_wfauto["blocks"]), dict(_wfauto["render_opts"])
                gioi_han = int(_wfauto.get("max_moi_lan") or 0)   # 0 = không giới hạn
            if not on:
                continue
            with _wf_lock:
                if _wf["running"]:
                    continue
            if _t.time() - last < max(1, iv) * 60:
                continue
            with _wfauto_lock:
                _wfauto["last"] = _t.time()
            new = [v for v in _auto_ung_vien() if v not in _wfauto_seen]
            if any(b.get("id") == "bam" for b in blocks):
                # Pipeline CÓ bước băm: loại clip ĐÃ LÀ output băm — tránh băm-lại-clip-đã-băm (đệ quy
                # clip_nho/clip_nho/...). Clip này đã được đưa vào render queue ở cycle sinh ra nó rồi.
                new = [v for v in new if not _la_bam_clip(v)]
            if not new:
                continue
            _du = 0
            if gioi_han > 0 and len(new) > gioi_han:       # giới hạn số video MỖI LẦN (tránh render dồn dập)
                _du = len(new) - gioi_han
                new = new[:gioi_han]
            with _wf_lock:
                if _wf["running"]:
                    continue
                _wf.update({"running": True, "blocks": {}, "summary": "", "error": "", "stop": False})
            them_log("🔁 Tự động quy trình: xử lý %d video mới%s." % (len(new), (" (còn %d để lần sau)" % _du) if _du else ""))
            try:
                _wf_chay(blocks, ropts, videos_override=new)
            except Exception:
                pass
            _wfauto_seen.update(new)
        except Exception:
            pass


def _khoi_dong_wfauto():
    """Nạp cấu hình auto-quy-trình đã lưu + chạy worker (resume sau khi mở lại app)."""
    global _wfauto_started
    try:
        d = doc_json(FILE_WFAUTO, {})
        if isinstance(d, dict) and d.get("blocks"):
            with _wfauto_lock:
                _wfauto.update({"on": bool(d.get("on")), "blocks": d.get("blocks") or [],
                                "render_opts": d.get("render_opts") or {},
                                "interval": int(d.get("interval") or 10), "last": 0.0})
    except Exception:
        pass
    if not _wfauto_started:
        _wfauto_started = True
        threading.Thread(target=_wf_auto_worker, daemon=True).start()


def _auto_worker():
    """Khi BẬT: cứ mỗi _AUTO_INTERVAL giây lại quét & đưa video gốc chưa render vào hàng đợi."""
    while True:
        try:
            _auto_quet_mot_lan()
        except Exception as e:
            them_log("⚠ Tự động render lỗi: " + str(e)[:100])
        time.sleep(_AUTO_INTERVAL)


def _khoi_dong_auto():
    _nap_auto()
    threading.Thread(target=_auto_worker, daemon=True).start()


def dung_crawl():
    global _proc, _dang_cao
    _dang_cao = False    # nhả cờ giữ chỗ (nếu bấm Dừng đúng lúc đang khởi động)
    if _proc is not None:
        # KILL CẢ CÂY: yt-dlp/MediaCrawler spawn ffmpeg con; terminate() chỉ giết cha → ffmpeg mồ côi
        # chạy tiếp, để lại file tải dở. taskkill /F /T giết cả con cháu (như render _kill_proc_tree).
        _kill_proc_tree(_proc)
        _proc = None
        them_log("■ Đã dừng.")


def _so_gia(seed, lo, hi):
    """Số giả ổn định (deterministic) từ chuỗi seed — dùng cho dữ liệu mô phỏng."""
    s = 2166136261
    for c in seed:
        s = ((s ^ ord(c)) * 16777619) & 0xFFFFFFFF
    s ^= (s >> 13)
    s = (s * 0x5bd1e995) & 0xFFFFFFFF
    s ^= (s >> 15)
    return lo + (s % (hi - lo + 1))


def goi_y_kenh_mo_phong(keyword, platform):
    """Dữ liệu MÔ PHỎNG (demo học tập) cho nền tảng chưa có API tìm kênh thật."""
    cau_hinh = {
        "bili": {"ten": "Bilibili", "url": "https://space.bilibili.com/",
                 "hau_to": ["官方", "频道", "UP主", "工作室", "日常", "解说", "剪辑", "精选", "社区", "电台"]},
        "xhs": {"ten": "Xiaohongshu", "url": "https://www.xiaohongshu.com/user/profile/",
                "hau_to": ["种草", "日记", "穿搭", "美妆", "生活", "好物", "分享", "笔记", "测评", "灵感"]},
        "tt": {"ten": "TikTok", "url": "https://www.tiktok.com/@",
               "hau_to": ["official", "daily", "vibes", "clips", "studio", "world",
                          "shorts", "central", "hub", "live"]},
    }.get(platform)
    if not cau_hinh:
        return []
    out = []
    for i, h in enumerate(cau_hinh["hau_to"]):
        seed = f"{keyword}|{platform}|{i}"
        out.append({
            "nickname": f"{keyword} {h}",
            "sec_uid": f"mophong_{platform}_{i}",
            "link": cau_hinh["url"] + f"mophong_{platform}_{i}",
            "avatar": "https://api.dicebear.com/7.x/thumbs/svg?seed=" + urllib.parse.quote(seed),
            "fans": _so_gia(seed + "f", 8000, 4500000),
            "total_favorited": _so_gia(seed + "t", 50000, 30000000),
            "videos_count": _so_gia(seed + "v", 20, 1200),
            "signature": f"[MÔ PHỎNG] Kênh {cau_hinh['ten']} demo về \"{keyword}\"",
            "mo_phong": True,
        })
    out.sort(key=lambda c: c["fans"], reverse=True)
    return out


def goi_y_kenh_bili(keyword):
    """Tìm kênh Bilibili THẬT qua bili_goi_y.py (đọc card UP có sẵn follow/video)."""
    out = os.path.join(THU_MUC_CRAWLER, "data", "bili", "_goi_y_kenh.json")
    try:
        if os.path.exists(out):
            os.remove(out)
    except Exception:
        pass
    subprocess.run([PYTHON_VENV, "bili_goi_y.py", keyword],
                   cwd=THU_MUC_GOC, capture_output=True, creationflags=_NO_WINDOW, timeout=120)
    if os.path.exists(out):
        with open(out, encoding="utf-8") as f:
            return json.load(f)
    return []


def goi_y_kenh_youtube(keyword):
    """Tìm kênh YouTube THẬT qua yt_goi_y.py (yt-dlp: subscriber thật, avatar, mô tả)."""
    out = os.path.join(THU_MUC_CRAWLER, "data", "youtube", "_goi_y_kenh.json")
    try:
        if os.path.exists(out):
            os.remove(out)
    except Exception:
        pass
    subprocess.run([PYTHON_VENV, "yt_goi_y.py", keyword],
                   cwd=THU_MUC_GOC, capture_output=True, creationflags=_NO_WINDOW, timeout=150)
    if os.path.exists(out):
        with open(out, encoding="utf-8") as f:
            return json.load(f)
    return []


_TEN_EN = {}


# ----------------- Kiểm tra đăng nhập (đọc cookie auth trong hồ sơ trình duyệt) -----------------
# Cookie CHỈ có khi đã đăng nhập (tránh cookie khách như web_session của XHS)
COOKIE_AUTH = {
    "dy": ["sessionid", "sessionid_ss", "sid_tt"],          # passport sau khi đăng nhập
    "tt": ["sessionid", "sessionid_ss", "sid_tt"],          # TikTok (ByteDance) — cần login để TÌM theo từ khóa
    "bili": ["SESSDATA", "DedeUserID"],                     # khách KHÔNG có 2 cookie này
    "xhs": ["web_session", "id_token"],   # phiên web XHS NỘI ĐỊA. Cookie creator cũ (customer-sso-sid...)
                                          # KHÔNG có ở web thường -> trước đây báo "out" oan dù đã đăng nhập.
    "rednote": ["web_session", "id_token"],   # XHS QUỐC TẾ (rednote.com) — cùng cookie nhưng profile/domain RIÊNG
    "wb": ["SUB", "SUBP", "SSOLoginState"],
    "tw": ["auth_token", "ct0"],                            # X: auth_token = đã đăng nhập
    "ig": ["sessionid", "ds_user_id"],                      # Instagram: sessionid = đã đăng nhập
    "fb": ["c_user", "xs"],                                 # Facebook: c_user (user ID) + xs (session token)
}
HOST_KEY = {"dy": "douyin.com", "bili": "bilibili.com",
            "xhs": "xiaohongshu.com", "rednote": "rednote.com", "wb": "weibo.com",
            "tw": "x.com", "ig": "instagram.com", "tt": "tiktok.com", "fb": "facebook.com"}
# 7 nền tảng hiển thị ở bảng trạng thái đăng nhập.
#   logo: tên file trong web/logos/ ; hoặc chu+mau để vẽ chữ thay logo.
#   ytdlp=True: tải bằng yt-dlp (video công khai) -> không cần đăng nhập.
NEN_TANG_LOGIN = [
    {"ma": "dy", "ten": "Douyin", "logo": "dy"},
    {"ma": "bili", "ten": "Bilibili", "logo": "bili"},
    # XHS nội địa GỘP vào RedNote (dùng chung dữ liệu; link xiaohongshu.com tự đổi domain → rednote.com khi cào).
    # Bỏ thẻ 'xhs' riêng — chỉ giữ 'rednote' (đã login) làm cổng chung cho cả Xiaohongshu.
    {"ma": "rednote", "ten": "Xiaohongshu / RedNote", "logo": "xhs"},
    {"ma": "tt", "ten": "TikTok", "logo": "tt", "ytdlp": True},   # KHÔNG cần login (như YouTube): tải link/kênh công khai qua yt-dlp; search đã tắt (anti-bot)
    {"ma": "yt", "ten": "YouTube", "logo": "yt", "ytdlp": True},
    # Facebook: THẺ THẬT (không ytdlp:True) để có nút "Đăng nhập" bấm được + badge phản ánh đúng trạng
    # thái. Lý do: cào theo LINK vẫn tải được ẩn danh (đã verify) NÊN KHÔNG ép; nhưng cào theo KÊNH/Page ẩn
    # danh bị Facebook chặn cứng sau ~1 video (dialog "Đăng nhập" — đã verify THẬT, KHÁC yt/tt không chặn)
    # → ÉP đăng nhập cho chế độ Kênh (user chốt "cần đăng nhập cũng được"). Gate THEO MODE (không chỉ theo
    # platform): "fb" nằm trong whitelist live-check /api/login_kiemtra_one (khác tt/yt "na" tuyệt đối) —
    # client (index.html guardLogin call-site) chỉ GỌI check khi mode=creator; mode=detail/link bỏ qua.
    {"ma": "fb", "ten": "Facebook", "logo": "fb"},
    # ĐÃ TẮT (user yêu cầu: phần đăng nhập CHỈ giữ Douyin/Bilibili/XHS/TikTok/YouTube) — bỏ comment để bật lại:
    # {"ma": "wb", "ten": "Weibo", "logo": "wb"},
    # {"ma": "tw", "ten": "Twitter (X)", "logo": "tw"},
    # {"ma": "ig", "ten": "Instagram", "logo": "ig"},
    # {"ma": "rd", "ten": "Reddit", "logo": "reddit", "khong_login": True},
    # {"ma": "th", "ten": "Threads", "logo": "threads", "chup": True},
]


def liet_ke_folder(path):
    """Liệt kê thư mục con để duyệt chọn output folder.
    path rỗng → liệt kê ổ đĩa (Windows). Trả {path, parent, dirs:[{name,path}], home, error}."""
    home = THU_MUC_GOC
    path = (path or "").strip()
    if not path:
        # Gốc: các ổ đĩa A:..Z:
        drives = []
        for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            d = f"{c}:\\"
            if os.path.exists(d):
                drives.append({"name": d, "path": d})
        return {"path": "", "parent": None, "dirs": drives, "home": home, "error": ""}
    path = os.path.abspath(path)
    if not os.path.isdir(path):
        return {"path": path, "parent": "", "dirs": [], "home": home,
                "error": "Không phải thư mục hợp lệ."}
    parent = os.path.dirname(path)   # KHÔNG rstrip: "C:\" -> dirname "C:\" == path -> parent="" (danh sách ổ); rstrip làm "C:"->"C:" sai, kẹt 1 ổ
    if parent == path:           # đã ở gốc ổ đĩa → parent = danh sách ổ đĩa
        parent = ""
    dirs = []
    try:
        for ten in sorted(os.listdir(path), key=str.lower):
            full = os.path.join(path, ten)
            try:
                if os.path.isdir(full) and not ten.startswith("$"):
                    dirs.append({"name": ten, "path": full})
            except OSError:
                pass
    except PermissionError:
        return {"path": path, "parent": parent, "dirs": [], "home": home,
                "error": "Không có quyền đọc thư mục này."}
    return {"path": path, "parent": parent, "dirs": dirs, "home": home, "error": ""}


def _trang_thai_login_chup(platform):
    """Trạng thái đăng nhập cho luồng chụp (Reddit/Threads) — profile riêng ở browser_data/,
    KHÔNG dùng hồ sơ MediaCrawler. Reddit (old.reddit) công khai → 'na'."""
    if platform == "rd":
        return "na"
    ck = os.path.join(THU_MUC_GOC, "browser_data", "threads", "Default", "Network", "Cookies")
    if not os.path.exists(ck):
        return "out"
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
                "SELECT name FROM cookies WHERE (host_key LIKE '%threads%' OR host_key LIKE '%instagram%') "
                "AND name='sessionid' AND (length(encrypted_value)>0 OR length(value)>0)").fetchall()
            return "in" if rows else "out"
        finally:
            con.close()
    except Exception:
        return "unknown"
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


def _logout_nentang(platform):
    """Đăng xuất 1 nền tảng: XOÁ cookie trong profile -> lần sau cào phải đăng nhập lại (QR).
    Trả (ok, msg). Lỗi xoá (file bị khoá vì cửa sổ login đang mở) -> ok=False, báo đóng cửa sổ."""
    prof = os.path.join(BROWSER_DATA_DIR, f"{platform}_user_data_dir")
    if not os.path.isdir(prof):
        return True, "Đã đăng xuất (chưa có phiên)."
    targets = []
    for sub in (("Default", "Network", "Cookies"), ("Default", "Cookies")):
        base = os.path.join(prof, *sub)
        for suf in ("", "-journal", "-wal", "-shm"):
            targets.append(base + suf)
    loi = 0
    for f in targets:
        if os.path.exists(f):
            try:
                os.remove(f)
            except Exception:
                loi += 1
    # Douyin: cookie-logout KHÔNG xoá localStorage 'HasUserLogin' -> mở login LẠI, _da_login đọc localStorage
    # CŨ (trang SPA chưa kịp render nút 登录 sau domcontentloaded) -> tưởng "đã đăng nhập sẵn" -> tự đóng cửa
    # sổ (không login lại được). Bili dùng cookie SESSDATA nên logout xoá sạch -> không dính. Xoá luôn web-storage
    # để đăng xuất TRIỆT ĐỂ (best-effort, KHÔNG làm fail logout nếu folder bị khoá).
    for d in ("Local Storage", "Session Storage"):
        p = os.path.join(prof, "Default", d)
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
    if loi:
        return False, "Không xoá được cookie — hãy ĐÓNG cửa sổ đăng nhập của nền tảng này rồi thử lại."
    return True, "Đã đăng xuất."


def _trang_thai_1lan(platform):
    """Đọc cookie 1 LẦN: 'in' = đã đăng nhập, 'out' = chưa, 'unknown' = không đọc được."""
    ck = os.path.join(BROWSER_DATA_DIR, f"{platform}_user_data_dir",
                      "Default", "Network", "Cookies")
    if not os.path.exists(ck):
        return "out"
    names = COOKIE_AUTH.get(platform, [])
    host = HOST_KEY.get(platform, "")

    def _doc(con):
        rows = con.execute(
            "SELECT name, length(encrypted_value), length(value) FROM cookies WHERE host_key LIKE ?",
            ("%" + host + "%",)).fetchall()
        co = {name for name, enc_len, val_len in rows
              if name in names and ((enc_len or 0) > 0 or (val_len or 0) > 0)}
        if platform in ("xhs", "rednote"):
            # web_session là cookie KHÁCH (XHS set CẢ khi chưa login / phiên cũ đã chết) -> KHÔNG đủ báo "in"
            # (gây 'xanh giả'). id_token mới là dấu hiệu login THẬT (hồ sơ khách KHÔNG có). Có web_session mà
            # THIẾU id_token = CHƯA RÕ (vàng) -> để live-check DOM (kiem_tra_login._xhs_dom) phán cuối, không xanh oan.
            if "id_token" in co:
                return "in"
            return "unknown" if "web_session" in co else "out"
        return "in" if co else "out"

    # Cách CHÍNH: copy Cookies + -wal + -shm ra temp rồi đọc bản copy.
    # Chromium ghi cookie MỚI (vừa đăng nhập) vào -wal, chưa checkpoint vào file chính
    # -> đọc thiếu -wal (vd immutable) sẽ báo "chưa đăng nhập" dù đã đăng nhập.
    # Copy cũng chịu được lúc file đang bị khóa (vừa đóng cửa sổ login).
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
            return _doc(con)
        finally:
            con.close()
    except Exception:
        pass
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
    # Fallback: đọc immutable (không thấy -wal) — chỉ khi copy thất bại
    try:
        uri = "file:" + urllib.request.pathname2url(os.path.abspath(ck)) + "?immutable=1"
        con = sqlite3.connect(uri, uri=True)
        try:
            return _doc(con)
        finally:
            con.close()
    except Exception:
        return "unknown"


def trang_thai_dang_nhap(platform):
    """'in'/'out'/'unknown' — ĐỌC LẠI tới khi ổn định.
    Ngay sau khi ĐÓNG cửa sổ login, Chromium chưa kịp ghi/checkpoint cookie xuống đĩa
    -> đọc 1 lần dễ ra 'out'/'unknown' nhầm dù đã đăng nhập. Nếu còn dấu hiệu phiên VỪA
    ghi (còn -wal/-shm, hoặc Cookies vừa đổi <15s) thì đợi & đọc lại; 'in' trả ngay (có
    cookie auth là chắc chắn đã đăng nhập). Lúc rảnh (logout thật) không có dấu hiệu đó
    nên trả ngay, KHÔNG chậm."""
    ck = os.path.join(BROWSER_DATA_DIR, f"{platform}_user_data_dir",
                      "Default", "Network", "Cookies")

    def _vua_ghi():
        try:
            return (os.path.exists(ck + "-wal") or os.path.exists(ck + "-shm")
                    or (os.path.exists(ck) and (time.time() - os.path.getmtime(ck)) < 15))
        except OSError:
            return False

    tt = _trang_thai_1lan(platform)
    for _ in range(5):
        if tt == "in" or not _vua_ghi():
            break
        time.sleep(1.0)
        tt = _trang_thai_1lan(platform)
    return tt


def da_dang_nhap(platform):
    """True nếu hồ sơ trình duyệt của nền tảng có cookie đăng nhập hợp lệ.
    Không đọc được -> True (coi như đã đăng nhập để khỏi chặn nhầm)."""
    tt = trang_thai_dang_nhap(platform)
    return tt in ("in", "unknown")


_login_procs = {}   # nền tảng -> Popen cửa sổ login đang mở (DEDUP)


def mo_dang_nhap(platforms):
    """Mở trình duyệt các nền tảng để người dùng đăng nhập.
    DEDUP: bỏ nền ĐÃ có cửa sổ login đang mở. Trước đây mỗi lần bấm đẻ 1 process mới mà cửa sổ
    đã-login-sẵn KHÔNG tự đóng -> chồng chất 20+ cửa sổ mồ côi giữ khóa Chromium profile (gây cào
    'chưa đăng nhập' oan). Giờ nền nào còn cửa sổ mở thì không mở thêm."""
    can_mo = []
    for p in platforms:
        pr = _login_procs.get(p)
        if pr is not None and pr.poll() is None:   # cửa sổ nền này còn sống -> không mở chồng
            continue
        can_mo.append(p)
    if not can_mo:
        return
    pr = subprocess.Popen([PYTHON_VENV, "mo_dang_nhap.py"] + can_mo,
                          cwd=THU_MUC_GOC, creationflags=_NO_WINDOW)
    for p in can_mo:
        _login_procs[p] = pr

    # SAU KHI cửa sổ login ĐÓNG → xác minh LIVE lại (kiem_tra_login = tín hiệu THẬT mỗi nền) rồi ghi
    # _login_check.json. Không phụ thuộc _da_login/debounce trong cửa sổ (dễ TRƯỢT ghi "in" nếu user tự
    # đóng nhanh → badge kẹt "đỏ" dù đã đăng nhập). Chờ 3s cho cookie flush xuống đĩa; bỏ qua nếu đang cào.
    def _xac_minh_sau_dong():
        try:
            pr.wait()
            time.sleep(3)
            if _proc is not None or _dang_cao:
                return   # đang cào = khóa profile → để recheck worker lúc rảnh lo
            subprocess.run([PYTHON_VENV, "kiem_tra_login.py", *can_mo],
                           cwd=THU_MUC_GOC, capture_output=True, creationflags=_NO_WINDOW, timeout=180)
        except Exception:
            pass
    threading.Thread(target=_xac_minh_sau_dong, daemon=True).start()


_browse_procs = {}   # nền tảng -> Popen cửa sổ LƯỚT đang mở (dedup + để cảnh báo khóa profile trước khi cào)


def cua_so_luot_dang_mo(platform):
    """True nếu cửa sổ LƯỚT của nền này còn mở (giữ khóa profile-cào)."""
    pr = _browse_procs.get(platform)
    return pr is not None and pr.poll() is None


def mo_luot(platforms):
    """Mở cửa sổ Chromium (profile-cào) để khách TỰ LƯỚT + lấy link. Không auto-close (mo_luot.py chờ
    tới khi user đóng). DEDUP: nền đã có cửa sổ lướt mở thì không mở chồng. Set env XHS nội/quốc-tế
    (MC_XHS_PROFILE...) qua _ap_alias_env để rednote mở đúng profile riêng, khớp lúc cào."""
    can_mo = [p for p in platforms if not cua_so_luot_dang_mo(p)]
    if not can_mo:
        return
    env = os.environ.copy()
    for p in can_mo:                 # nhét cờ profile XHS/rednote (subprocess mở đúng user_data_dir)
        _ap_alias_env(env, p)
    pr = subprocess.Popen([PYTHON_VENV, "mo_luot.py"] + can_mo,
                          cwd=THU_MUC_GOC, creationflags=_NO_WINDOW, env=env)
    for p in can_mo:
        _browse_procs[p] = pr


def _co_chu_han(s):
    return any("一" <= c <= "鿿" for c in (s or ""))


def them_dich_ten(creators):
    """Gắn bản dịch tiếng Anh ngay trong tên kênh: '原名 (English)' để dễ phân biệt nội dung."""
    if not creators:
        return creators
    can_dich = []
    for c in creators:
        ten = c.get("nickname") or ""
        if _co_chu_han(ten) and ten not in _TEN_EN:
            can_dich.append(ten)
    can_dich = list(dict.fromkeys(can_dich))  # bỏ trùng, giữ thứ tự
    if can_dich:
        from concurrent.futures import ThreadPoolExecutor

        def _dich(t):
            try:
                return t, dich_google(t, "en", sl="zh-CN")
            except Exception:
                return t, ""

        try:
            with ThreadPoolExecutor(max_workers=8) as ex:
                for t, en in ex.map(_dich, can_dich):
                    _TEN_EN[t] = en
        except Exception:
            pass
    for c in creators:
        ten = c.get("nickname") or ""
        en = (_TEN_EN.get(ten) or "").strip()
        if en and en.lower() != ten.lower() and "(" not in ten:
            c["nickname"] = f"{ten} ({en})"
    return creators


def goi_y_kenh_tu_search(keyword, platform):
    """Gợi ý kênh THẬT cho XHS/TikTok: chạy SEARCH (notes/videos) rồi gom TÁC GIẢ duy nhất → kênh có LINK
    PROFILE thật (bấm 👁 preview được, KHÔNG còn mô phỏng). XHS: tim_anh (note có user_id+avatar); TikTok:
    tai_ytdlp (item có nick=@username → link tiktok.com/@nick). Search dính login/anti-bot → trả [] (frontend báo)."""
    _don_crawl_ro_ri(platform)
    if platform == "xhs":
        args = [PYTHON_VENV, "tim_anh.py", "--platform", "xhs", "--type", "search",
                "--keyword", keyword, "--count", "30"]
    elif platform == "tt":
        args = [PYTHON_VENV, "tai_ytdlp.py", "--list", "--platform", "tt", "--type", "search",
                "--input", keyword, "--count", "30"]
    else:
        return []
    try:
        kq = subprocess.run(args, cwd=THU_MUC_GOC, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", creationflags=_NO_WINDOW, timeout=300)
    except Exception:
        return []
    items = []
    for line in (kq.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("{") and '"items"' in line:
            try:
                items = json.loads(line).get("items") or []
            except Exception:
                items = []
            break
    seen, out = set(), []
    for it in items:
        if platform == "xhs":
            uid = str(it.get("user_id") or "").strip()
            if not uid or uid in seen:
                continue
            seen.add(uid)
            out.append({"nickname": (it.get("nick") or uid).strip(), "avatar": it.get("avatar") or "",
                        "link": "https://www.xiaohongshu.com/user/profile/" + uid,
                        "fans": 0, "videos_count": 0})
        else:  # tt: nick = @username -> link kênh tiktok.com/@username (tai_ytdlp resolve được khi preview)
            nick = (it.get("nick") or "").strip().lstrip("@")
            if not nick or nick.lower() in seen:
                continue
            seen.add(nick.lower())
            out.append({"nickname": nick, "avatar": "",
                        "link": "https://www.tiktok.com/@" + nick,
                        "fans": 0, "videos_count": 0})
    return out


def goi_y_kenh(keyword, platform="dy"):
    # Bilibili: tìm kênh THẬT
    if platform == "bili":
        return them_dich_ten(goi_y_kenh_bili(keyword))
    # YouTube: tìm kênh THẬT qua yt-dlp (subscriber thật)
    if platform == "yt":
        return goi_y_kenh_youtube(keyword)
    # XHS / TikTok: gợi ý kênh THẬT — gom tác giả từ kết quả search (link profile thật → preview/cào được)
    if platform in ("xhs", "tt"):
        return them_dich_ten(goi_y_kenh_tu_search(keyword, platform))
    # Các nền tảng khác (vd Weibo) chưa hỗ trợ
    if platform != "dy":
        return []
    out = os.path.join(THU_MUC_CRAWLER, "data", "douyin", "_goi_y_kenh.json")
    cache_f = os.path.join(THU_MUC_CRAWLER, "data", "douyin", "_goi_y_cache.json")
    kwk = (keyword or "").strip().lower()
    # CACHE: douyin ANTI-BOT throttle RẤT dễ kích (cào userlist nhiều lần liên tiếp → 0 kênh). Dùng lại kết
    # quả gần đây (<15 phút, cùng từ khóa) thay vì cào lại mỗi lần mở gợi-ý → giảm số lần cào douyin = ít bị
    # chặn. CHỈ cache khi CÓ kết quả (không cache 0 do throttle).
    try:
        if os.path.exists(cache_f):
            ent = (json.load(open(cache_f, encoding="utf-8")) or {}).get(kwk)
            if ent and ent.get("list") and (time.time() - ent.get("ts", 0) < 900):
                return them_dich_ten(ent["list"])
    except Exception:
        pass
    try:
        if os.path.exists(out):
            os.remove(out)
    except Exception:
        pass
    _don_crawl_ro_ri("dy")   # dọn browser-crawl headless rò rỉ giữ profile (vd login-check lơ lửng)
    subprocess.run([PYTHON_VENV, "main.py", "--platform", "dy", "--type", "userlist",
                    "--keywords", keyword, "--headless", "yes", "--get_comment", "no"],
                   cwd=THU_MUC_CRAWLER, capture_output=True, creationflags=_NO_WINDOW, timeout=300)
    if os.path.exists(out):
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        if data:
            try:
                cache = json.load(open(cache_f, encoding="utf-8")) if os.path.exists(cache_f) else {}
                cache[kwk] = {"ts": time.time(), "list": data}
                json.dump(cache, open(cache_f, "w", encoding="utf-8"), ensure_ascii=False)
            except Exception:
                pass
        return them_dich_ten(data)
    return []


# ----------------- Trợ lý AI (Groq) -----------------
# Key được MÃ HOÁ bằng Windows DPAPI (bao_mat_key.py) — không còn lưu plaintext trong ai_config.json.
FILE_AI_SYSTEM = os.path.join(THU_MUC_GOC, "ai_system.md")
GROQ_MODEL = "llama-3.3-70b-versatile"

# Giao thức "công cụ" qua PROMPT (JSON-action / ReAct) — chạy được CẢ Groq (native tool tốt) LẪN Ollama Cloud
# gemma3 (KHÔNG tool-call native). Model trả 1 dòng JSON {"action","args"} khi cần thao tác; else trả lời thường.
AI_ACTIONS = """
BẠN CÓ CÔNG CỤ để THAO TÁC GIÚP NGƯỜI DÙNG (cào → liệt kê → render). Khi cần làm 1 việc, trả về DUY NHẤT 1 JSON
trên 1 dòng, KHÔNG kèm chữ nào khác:
{"action":"<tên>","args":{...}}

Danh sách action:
- cao_video — tải video. args: nen_tang ("dy" Douyin | "bili" Bilibili | "xhs" Xiaohongshu | "tt" TikTok |
  "yt" YouTube; mặc định "dy"), che_do ("tu_khoa" hoặc "kenh"), noi_dung (CHỦ ĐỀ nếu tu_khoa — cứ đưa tiếng
  Việt, tool tự dịch sang Trung cho nền tảng Trung; link/tên kênh nếu kenh), so_luong (số, mặc định 10),
  sap_xep ("lien_quan"|"nhieu_like"|"moi_nhat"), thoi_gian ("tat_ca"|"1_ngay"|"1_tuan"|"6_thang").
- tim_kenh — gợi ý kênh theo chủ đề. args: nen_tang (như trên; mặc định "dy"), tu_khoa (CHỦ ĐỀ — cứ đưa TIẾNG
  VIỆT, tool tự dịch). MÁCH NƯỚC: Douyin/XHS phải đăng nhập mới ra kênh; Bilibili/YouTube KHÔNG cần đăng nhập
  → nếu người dùng chỉ muốn xem gợi ý kênh mà chưa login Douyin, ưu tiên nen_tang "bili" hoặc "yt".
- liet_ke_video — liệt kê video ĐÃ TẢI (đánh số) để chọn render. args: {}.
- render_video — xếp 1 video vào hàng đợi render. args: chon (SỐ THỨ TỰ theo liet_ke_video, hoặc 1 phần tên),
  phude (true/false, mặc định true), long_tieng (true/false), tts ("piper"|"edge"|"omnivoice"), che (true/false, mặc định true).
  GIỮ ĐÚNG ý người dùng: nói "lồng tiếng" → long_tieng:true; nói giọng (piper/edge) → tts đúng giọng đó;
  nói "không che" → che:false. Đừng tự bỏ tuỳ chọn người dùng đã yêu cầu.
- trang_thai — xem cào/render tới đâu. args: {}.
- theo_doi — thêm các kênh VỪA tìm (tim_kenh) vào danh sách Theo dõi để hệ thống tự cào video mới định kỳ.
  args: {} (theo dõi tất cả kênh vừa gợi ý). BẮT BUỘC gọi tim_kenh trước.
- bam_nho — băm 1 video DÀI thành nhiều clip NGẮN theo cảnh. args: chon (SỐ thứ tự theo liet_ke_video hoặc 1
  phần tên), so_ban (số clip, mặc định 3), ratio ("9:16" dọc | "16:9" ngang, tuỳ chọn). PHẢI liet_ke_video trước.

QUY TẮC:
- ❗CHỐNG BỊA: TUYỆT ĐỐI KHÔNG nói "đã làm X / đã theo dõi / đã cào xong / đã thêm" nếu BẠN CHƯA gọi action
  tương ứng và nhận [KẾT QUẢ]. Người dùng yêu cầu việc CHƯA có action (đăng bài, xoá, theo dõi khi chưa
  tim_kenh…) → nói THẬT "chưa làm được/cần bước trước", ĐỪNG giả vờ đã làm. Chỉ báo "đã làm" đúng theo [KẾT QUẢ].
- Cào CHỈ chạy 1 việc 1 lúc. "cào hết nhiều kênh" → gọi cao_video lần lượt; nếu [KẾT QUẢ] báo đang bận thì nói
  thật "đang cào kênh trước, các kênh sau xếp sau" — đừng nói đã cào hết.
- "Theo dõi" các kênh → gọi action theo_doi (KHÔNG phải cao_video). Muốn render thì PHẢI gọi liet_ke_video trước
  để biết số thứ tự, rồi render_video theo số.
- NHIỀU VIỆC trong 1 câu (vd "tìm kênh bóng đá RỒI theo dõi luôn", "liệt kê RỒI render số 1", "cào RỒI render"):
  làm ĐỦ TỪNG việc bằng các action LIÊN TIẾP, ĐỪNG dừng sau việc đầu. Chỉ trả lời (không-JSON) cho người dùng
  KHI đã làm xong HẾT các việc họ yêu cầu.
- Chỉ trò chuyện/hỏi đáp (không thao tác) → trả lời tiếng Việt bình thường, TUYỆT ĐỐI không in JSON.
- Người dùng ĐÃ nêu 1 chủ đề (dù NGẮN gọn: "review phim", "ẩm thực", "mèo cún", "mỹ phẩm") → GỌI tim_kenh/
  cao_video NGAY với chủ đề đó, KHÔNG hỏi thêm chi tiết vụn vặt (đừng hỏi "phim gì/loại nào").
- CHỈ khi người dùng KHÔNG nêu chủ đề nào ("gợi ý kênh đi", "chưa biết làm gì hôm nay") → trả lời THƯỜNG: gợi ý
  vài chủ đề HOT (review phim, ẩm thực, thú cưng, mỹ phẩm, hài hước, game, du lịch) + hỏi chọn. TUYỆT ĐỐI
  KHÔNG tự bịa 1 chủ đề rồi đi search.
- Sau khi nhận [KẾT QUẢ ...], tóm tắt ngắn gọn cho người dùng + gợi ý bước tiếp.
"""


def _ai_parse_action(text):
    """Bóc JSON {"action":...} từ câu trả lời model (có thể bọc ```json/kèm chữ; args CÓ THỂ lồng {}). Quét từng
    khối {...} cân ngoặc rồi thử json.loads — KHÔNG dùng regex [^{}]* (vỡ khi args rỗng {}/lồng). None nếu chat thường."""
    t = text or ""
    i = t.find("{")
    while i != -1:
        depth = 0
        for j in range(i, len(t)):
            if t[j] == "{":
                depth += 1
            elif t[j] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        o = json.loads(t[i:j + 1])
                        if isinstance(o, dict) and o.get("action"):
                            return o
                    except Exception:
                        pass
                    break
        i = t.find("{", i + 1)
    return None


def load_ai_key():
    """Lấy Groq key (đã mã hoá DPAPI). Tự migrate key plaintext cũ nếu có."""
    return bao_mat_key.doc_key("groq")


def save_ai_key(k):
    """Mã hoá & lưu Groq key bằng DPAPI."""
    bao_mat_key.luu_key(k, "groq")


def groq_chat(key, messages, tools=None):
    body = {"model": GROQ_MODEL, "messages": messages, "temperature": 0.3}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": "Bearer " + key,
                 "Content-Type": "application/json",
                 # User-Agent giống trình duyệt để qua Cloudflare (tránh lỗi 1010)
                 "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                               "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode("utf-8"))


def _ai_sang_trung(kw):
    """Dịch CHỦ ĐỀ sang tiếng Trung cho Douyin search (Douyin tìm bằng tiếng Trung mới ra). VN/EN→zh; đã là
    tiếng Trung thì giữ nguyên. Dùng cho CẢ cao_video (tu_khoa) lẫn tim_kenh — robust khi model không tự dịch."""
    import re as _re
    kw = (kw or "").strip()
    if not kw or _re.search(r'[一-鿿]', kw):
        return kw
    try:
        zh = dich_google(kw, "zh-CN")
        return zh.strip() if zh and zh.strip() else kw
    except Exception:
        return kw


_AI_NEN_TANG = {"dy": "dy", "douyin": "dy", "bili": "bili", "bilibili": "bili", "xhs": "xhs",
                "xiaohongshu": "xhs", "rednote": "xhs", "tt": "tt", "tiktok": "tt",
                "yt": "yt", "youtube": "yt", "weibo": "weibo", "wb": "weibo"}
_AI_TEN_NEN_TANG = {"dy": "Douyin", "bili": "Bilibili", "xhs": "Xiaohongshu", "tt": "TikTok",
                    "yt": "YouTube", "weibo": "Weibo"}
_AI_PLATFORM_TRUNG = ("dy", "bili", "xhs", "weibo")   # platform Trung Quốc → search bằng TIẾNG TRUNG


def _ai_nen_tang(s):
    return _AI_NEN_TANG.get((s or "dy").strip().lower(), "dy")


def ai_exec_tool(name, args):
    if name == "cao_video":
        if _proc is not None:
            return "Đang có tác vụ cào chạy rồi, vui lòng đợi nó xong."
        nt = _ai_nen_tang(args.get("nen_tang") or args.get("platform"))
        che_do = args.get("che_do", "tu_khoa")
        noi_dung = (args.get("noi_dung") or "").strip()
        if che_do != "kenh" and nt in _AI_PLATFORM_TRUNG:   # platform Trung + từ khoá → dịch sang Trung (YT/TT giữ nguyên)
            noi_dung = _ai_sang_trung(noi_dung)
        cfg = {"platform": nt, "headless": True, "count": args.get("so_luong") or 10, "input": noi_dung}
        if che_do == "kenh":
            cfg["type"] = "creator"
            cfg["creator_sort"] = "most_liked" if args.get("sap_xep") == "nhieu_like" else "newest"
        else:
            cfg["type"] = "search"
            cfg["sort"] = {"lien_quan": 0, "nhieu_like": 1, "moi_nhat": 2}.get(args.get("sap_xep"), 0)
            cfg["publish_time"] = {"tat_ca": 0, "1_ngay": 1, "1_tuan": 7, "6_thang": 180}.get(args.get("thoi_gian"), 0)
        chay_crawl(cfg)
        return ("Đã bắt đầu cào trên %s (%s), từ khoá='%s', số lượng=%s. ĐANG CHẠY NỀN (chưa xong). "
                "Báo người dùng xem tiến trình ở Nhật ký / tab Cào ngay."
                % (_AI_TEN_NEN_TANG.get(nt, nt), cfg["type"], cfg["input"], cfg["count"]))
    if name == "tim_kenh":
        nt = _ai_nen_tang(args.get("nen_tang"))
        kw_goc = (args.get("tu_khoa") or "").strip()
        if not kw_goc:
            return "Bạn muốn gợi ý kênh về CHỦ ĐỀ gì? (vd: mỹ phẩm, ẩm thực, thú cưng, bóng đá, phim…) — cho mình 1 chủ đề."
        kw = _ai_sang_trung(kw_goc) if nt in _AI_PLATFORM_TRUNG else kw_goc   # platform Trung → dịch; YT/TT/Bili-quốc-tế giữ nguyên
        cs = goi_y_kenh(kw, nt)[:6]
        if not cs:
            _goiy = ("Douyin/XHS cần ĐĂNG NHẬP (đăng nhập ở tab Đăng nhập rồi thử lại) hoặc đang bị giới hạn tốc độ"
                     if nt in ("dy", "xhs") else "thử đổi chủ đề hoặc thử lại sau")
            return ("Chưa tìm được kênh %s cho '%s' (tìm: %s). %s. Mách người dùng: Bilibili/YouTube tìm kênh KHÔNG "
                    "cần đăng nhập — có thể đổi sang nền tảng đó." % (_AI_TEN_NEN_TANG.get(nt, nt), kw_goc, kw, _goiy))
        globals()["_AI_DS_KENH"] = cs              # nhớ FULL kênh để action theo_doi dùng (link/nickname/avatar/fans)
        globals()["_AI_LAST_CARDS"] = {"loai": "kenh", "items": [   # THẺ cho UI: avatar + nút "Cào kênh này"
            {"ten": c.get("nickname"), "fans": c.get("fans"), "avatar": c.get("avatar"), "link": c.get("link")}
            for c in cs]}
        return ("OK: tìm được %d kênh %s cho '%s' (thẻ kèm theo, mỗi thẻ có nút 'Cào kênh này'). Nếu người dùng "
                "CÒN yêu cầu việc khác (theo dõi/cào) thì làm tiếp; nếu xong rồi thì báo họ xem thẻ."
                % (len(cs), _AI_TEN_NEN_TANG.get(nt, nt), kw_goc))
    if name == "theo_doi":
        ds = globals().get("_AI_DS_KENH") or []
        if not ds:
            return "Chưa có danh sách kênh để theo dõi. Hãy gọi tim_kenh trước rồi mới theo dõi."
        cfg = doc_json(FILE_TD, {"creators": [], "interval": "30", "count": "10"})
        cur = [c if isinstance(c, dict) else {"link": c} for c in (cfg.get("creators") or [])]
        them = 0
        for c in ds:
            link = c.get("link")
            if link and not any(x.get("link") == link for x in cur):
                cur.append({"link": link, "nickname": c.get("nickname"), "avatar": c.get("avatar"), "fans": c.get("fans")})
                them += 1
        luu_json(FILE_TD, {"creators": cur, "interval": str(cfg.get("interval", "30")), "count": str(cfg.get("count", "10"))})
        return ("Đã THÊM %d kênh vào danh sách Theo dõi (tổng %d kênh). Hệ thống sẽ tự cào video MỚI của các kênh "
                "này định kỳ — nhưng người dùng cần sang tab 'Theo dõi' bấm 'BẬT theo dõi' để kích hoạt (và tính "
                "năng này cần gói PRO/UNLIMITED). Báo đúng như vậy cho người dùng." % (them, len(cur)))
    if name == "liet_ke_video":
        goc = [x for x in liet_ke_file(80) if x.get("nhom") == "Cào gốc"]
        if not goc:
            return "Chưa có video gốc nào đã tải. Hãy cào trước (cao_video)."
        globals()["_AI_DS_VIDEO"] = goc            # nhớ danh sách để render_video chọn theo SỐ
        globals()["_AI_LAST_CARDS"] = {"loai": "video", "items": [   # THẺ: thumbnail + nút Render / Render+lồng tiếng
            {"so": i, "ten": (x.get("ten_vi") or x.get("tieu_de_goc") or x.get("name") or "")[:60],
             "p": x.get("p"), "nen_tang": x.get("nen_tang", ""), "mb": x.get("mb")}
            for i, x in enumerate(goc[:30], 1)]}
        dong = []
        for i, x in enumerate(goc[:30], 1):
            ten = (x.get("ten_vi") or x.get("tieu_de_goc") or x.get("name") or "")[:55]
            dong.append("%d. %s [%s · %sMB]" % (i, ten, x.get("nen_tang", ""), x.get("mb")))
        return "Đã liệt kê %d video (hiện thẻ bên dưới, bấm Render). Danh sách:\n%s" % (len(goc), "\n".join(dong))
    if name == "render_video":
        ds = globals().get("_AI_DS_VIDEO") or [x for x in liet_ke_file(80) if x.get("nhom") == "Cào gốc"]
        if not ds:
            return "Chưa có video để render. Gọi liet_ke_video trước."
        chon = args.get("chon")
        target = None
        if isinstance(chon, int) or (isinstance(chon, str) and str(chon).strip().isdigit()):
            i = int(str(chon).strip()) - 1
            if 0 <= i < len(ds):
                target = ds[i]
        if target is None and isinstance(chon, str) and chon.strip():
            kw = chon.strip().lower()
            for x in ds:
                if kw in (str(x.get("name", "")) + str(x.get("tieu_de_goc", "")) + str(x.get("ten_vi", ""))).lower():
                    target = x
                    break
        if target is None:
            return "Không tìm thấy video '%s'. Gọi liet_ke_video để xem số thứ tự." % chon
        full = _resolve_video(target.get("p", ""))
        if not full:
            return "Video không hợp lệ."
        opts = {"phude": bool(args.get("phude", True)), "che_chu": bool(args.get("che", True))}
        if args.get("long_tieng"):
            opts["long_tieng"] = True
            opts["tts"] = args.get("tts") or "piper"
        _nt = _nen_tang_seg_tu_path(full)
        opts["out_dir"] = os.path.join(PROCESSED_DIR, _nt or "khac")
        # HẠN MỨC LỒNG TIẾNG (chung mọi đường — bịt bypass qua trợ lý AI): render CÓ lồng tiếng phải qua quota.
        if opts.get("long_tieng"):
            _nhan_ai, _bo_ai, _msg_ai = _dub_quota_loc([full], True)
            if not _nhan_ai:
                return "Đã đạt hạn mức lồng tiếng của gói hôm nay%s. Có thể render KHÔNG lồng tiếng, hoặc nâng cấp gói." % (
                    ": " + _msg_ai if _msg_ai else "")
            opts["_dub_phut"] = _nhan_ai[0][1]
        _queue_them(full, opts)
        return "Đã xếp render: '%s' (phụ đề=%s, lồng tiếng=%s, che=%s). Theo dõi bằng trang_thai." % (
            (target.get("ten_vi") or target.get("name") or "")[:40],
            opts["phude"], opts.get("long_tieng", False), opts["che_chu"])
    if name == "trang_thai":
        cao = "ĐANG cào" if _proc is not None else "rảnh (không cào)"
        with _queue_lock:
            cho = sum(1 for x in _queue if x["trang_thai"] == "cho")
            dang = sum(1 for x in _queue if x["trang_thai"] == "dang")
            xong = sum(1 for x in _queue if x["trang_thai"] == "xong")
            loi = sum(1 for x in _queue if x["trang_thai"] == "loi")
        return "Cào: %s. Render — %d đang chạy, %d chờ, %d xong, %d lỗi." % (cao, dang, cho, xong, loi)
    if name == "bam_nho":
        if _bam_running:
            return "Đang băm video khác, đợi xong đã."
        ds = globals().get("_AI_DS_VIDEO") or [x for x in liet_ke_file(80) if x.get("nhom") == "Cào gốc"]
        if not ds:
            return "Chưa có video để băm. Hãy cào hoặc gọi liet_ke_video trước."
        chon = args.get("chon")
        target = None
        if isinstance(chon, int) or (isinstance(chon, str) and str(chon).strip().isdigit()):
            i = int(str(chon).strip()) - 1
            if 0 <= i < len(ds):
                target = ds[i]
        if target is None and isinstance(chon, str) and chon.strip():
            kw = chon.strip().lower()
            for x in ds:
                if kw in (str(x.get("name", "")) + str(x.get("tieu_de_goc", "")) + str(x.get("ten_vi", ""))).lower():
                    target = x
                    break
        if target is None:
            return "Không tìm thấy video '%s'. Gọi liet_ke_video để xem số thứ tự." % chon
        full = _resolve_video(target.get("p", ""))
        if not full:
            return "Video không hợp lệ."
        try:
            so_ban = max(2, int(float(args.get("so_ban") or 3)))
        except (TypeError, ValueError):
            so_ban = 3
        ratio = args.get("ratio") if args.get("ratio") in ("9:16", "16:9") else ""
        chay_bam_nho({"videos": [full], "so_ban": so_ban, "ratio": ratio})
        return ("Đã bắt đầu BĂM NHỎ '%s' thành %d clip theo cảnh%s. ĐANG CHẠY NỀN — xem kết quả ở tab Băm nhỏ / "
                "File đã tải." % ((target.get("ten_vi") or target.get("name") or "")[:40], so_ban,
                                  (" (tỉ lệ %s)" % ratio) if ratio else ""))
    return "Action không hỗ trợ: " + str(name)


def _ghi_usage_chat(key, resp):
    """Ghi nhận request + token (Groq) cho key chat vào kho ai_dich (cho dashboard quota)."""
    try:
        import ai_dich
        u = (resp or {}).get("usage") or {}
        ai_dich.ghi_su_dung(key=key, tok_in=u.get("prompt_tokens", 0), tok_out=u.get("completion_tokens", 0))
    except Exception:
        pass


def _ai_provider_key():
    """Chọn (provider, key, url, model) cho Trợ lý AI: ưu tiên GROQ (tool-calling tốt), không có thì OLLAMA CLOUD
    (gemma3, qua giao thức JSON-action prompt). '' nếu không có key nào."""
    import ai_dich
    gk = ai_dich.key_groq_dung_duoc()
    if gk:
        return "groq", gk, ai_dich.PROVIDERS["groq"]["chat"], ai_dich.PROVIDERS["groq"]["models"][0]
    for k in ai_dich._doc_kho():        # key Ollama Cloud trong kho (chatbot dùng chung kho với dịch cũ)
        if k.get("provider") == "ollama" and k.get("trang_thai") != "sai":
            return "ollama", k["key"], ai_dich.PROVIDERS["ollama"]["chat"], ai_dich.PROVIDERS["ollama"]["models"][0]
    gk2 = load_ai_key()                 # key Groq DPAPI riêng (đường cũ)
    if gk2:
        return "groq", gk2, ai_dich.PROVIDERS["groq"]["chat"], ai_dich.PROVIDERS["groq"]["models"][0]
    return "", "", "", ""


def _ai_app_state():
    """TRẠNG THÁI THẬT của app lúc này (nhồi vào prompt mỗi lượt → AI suy luận từ STATE thật, không đoán/bịa).
    Chỉ lấy state RẺ (instant, không quét đĩa/không gọi mạng) để khỏi tốn thời gian + token."""
    cao = "ĐANG cào" if _proc is not None else "rảnh (không cào)"
    try:
        with _queue_lock:
            dang = sum(1 for x in _queue if x["trang_thai"] == "dang")
            cho = sum(1 for x in _queue if x["trang_thai"] == "cho")
            xong = sum(1 for x in _queue if x["trang_thai"] == "xong")
    except Exception:
        dang = cho = xong = 0
    bam = "ĐANG băm" if _bam_running else "rảnh"
    return ("[TRẠNG THÁI THẬT lúc này — DỰA VÀO ĐÂY, ĐỪNG ĐOÁN] Cào: %s. Render: %d đang/%d chờ/%d xong. "
            "Băm: %s. Nền tảng hỗ trợ: Douyin, Bilibili, XHS, TikTok, YouTube (Bili/YT tìm kênh không cần login)."
            % (cao, dang, cho, xong, bam))


def _ai_chat_raw(url, key, model, messages, timeout=90):
    """Gọi chat kiểu OpenAI (Groq/Ollama Cloud đều OpenAI-compatible). UA giả để qua Cloudflare (Groq)."""
    body = json.dumps({"model": model, "messages": messages, "temperature": 0.3, "stream": False}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": "Bearer " + key, "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def handle_ai(user_messages):
    """Trợ lý AI end-to-end: chat (Groq/Ollama Cloud) + tự THAO TÁC (cào/liệt kê/render/trạng thái) qua giao thức
    JSON-action (ReAct, tối đa 5 vòng → chain cào→trạng thái→render). Không native-tool → hợp cả gemma3."""
    prov, key, url, model = _ai_provider_key()
    if not key:
        return {"reply": "Trợ lý AI cần 1 key **Groq** (gsk_…, free console.groq.com) hoặc **Ollama Cloud** "
                         "(free ollama.com). Dán key vào ô '➕ Thêm khóa AI' phía trên."}
    try:
        with open(FILE_AI_SYSTEM, encoding="utf-8") as f:
            system = f.read()
    except Exception:
        system = "Bạn là trợ lý của công cụ cào + render video LLN APP. Trả lời tiếng Việt ngắn gọn."
    globals()["_AI_LAST_CARDS"] = None   # thẻ (kênh/video) tool sinh ra trong lượt này → trả về cho UI render
    msgs = [{"role": "system", "content": system + "\n" + AI_ACTIONS + "\n\n" + _ai_app_state()}]
    for m in user_messages:
        if m.get("role") in ("user", "assistant") and m.get("content"):
            msgs.append({"role": m["role"], "content": m["content"]})
    for _vong in range(5):              # tối đa 5 vòng action (chain nhiều bước giúp người dùng end-to-end)
        try:
            resp = _ai_chat_raw(url, key, model, msgs)
        except urllib.error.HTTPError as e:
            return {"reply": "Lỗi AI (%s %d): %s" % (prov, e.code, e.read().decode("utf-8", "replace")[:160])}
        except Exception as e:
            return {"reply": "Lỗi gọi AI (%s): %s" % (prov, str(e)[:160])}
        _ghi_usage_chat(key, resp)
        content = ((resp.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        act = _ai_parse_action(content)
        if not act:                     # không có JSON-action → là câu trả lời cho người dùng
            return {"reply": content or "(không có nội dung)", "cards": globals().get("_AI_LAST_CARDS")}
        kq = ai_exec_tool(act.get("action", ""), act.get("args") or {})
        msgs.append({"role": "assistant", "content": content})
        msgs.append({"role": "user", "content": "[KẾT QUẢ %s]\n%s" % (act.get("action"), kq)})
    return {"reply": "Đã thực hiện một số bước. Bạn gõ 'trạng thái' để xem tiến độ nhé.",
            "cards": globals().get("_AI_LAST_CARDS")}


# ----------------- Theo dõi & Hẹn giờ (Task Scheduler) -----------------
# theo_doi_config/lich_config PHẢI ở _SETTINGS_DIR (userData): app-src READ-ONLY → ghi vào đó PermissionError
# (500 khi BẬT theo dõi / lưu hẹn giờ). Di cư file cũ từ app-src 1 lần. theo_doi.py/chay_tu_dong.py đọc cùng path.
FILE_TD = os.path.join(_SETTINGS_DIR, "theo_doi_config.json")
FILE_LICH = os.path.join(_SETTINGS_DIR, "lich_config.json")
if _SETTINGS_DIR != THU_MUC_GOC:
    import shutil as _shutil_cfg
    for _nf in (FILE_TD, FILE_LICH):
        try:
            _of = os.path.join(THU_MUC_GOC, os.path.basename(_nf))
            if not os.path.exists(_nf) and os.path.isfile(_of):
                os.makedirs(_SETTINGS_DIR, exist_ok=True)
                _shutil_cfg.copyfile(_of, _nf)
        except Exception:
            pass
BAT_TD = os.path.join(THU_MUC_GOC, "theo_doi.bat")
BAT_LICH = os.path.join(THU_MUC_GOC, "chay_tu_dong.bat")
TASK_TD = "ToolCaoVideoTheoDoi"
TASK_LICH = "ToolCaoVideoTuDong"


def _schtasks(args):
    return subprocess.run(["schtasks"] + args, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", creationflags=_NO_WINDOW)


def task_on(name):
    try:
        return _schtasks(["/Query", "/TN", name]).returncode == 0
    except Exception:
        return False


def doc_json(path, macdinh):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return macdinh


def luu_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ----------------- HTTP -----------------
class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if "json" in ctype or "html" in ctype else ""))
        self.send_header("Content-Length", str(len(data)))
        if "html" in ctype:   # không cache HTML -> trình duyệt luôn lấy index.html mới (tránh kẹt bản cũ)
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        # Security headers (defense-in-depth): chống nhúng iframe (clickjacking) + sniff MIME + rò #k=nonce
        # qua Referer. CSP chỉ frame-ancestors/object-src/base-uri để KHÔNG vỡ SPA inline-JS (index.html).
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        # H7 + siết CSP (đã test Chromium/Playwright): default-src 'self' làm nền; MỞ RỘNG đúng nhu cầu app:
        #  - img-src +https:/data:/blob: (avatar nền tảng douyinpic... + thumbnail data/blob)
        #  - media-src 'self' blob: data: (video /video + preview blob)
        #  - style-src/script-src 'unsafe-inline' (SPA inline; app KHÔNG dùng eval nên KHÔNG có 'unsafe-eval')
        #  - connect-src 'self' (fetch /api same-origin) · object-src 'none' · frame-ancestors 'none' · base/form 'self'
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                         "img-src 'self' data: blob: https:; media-src 'self' blob: data:; font-src 'self' data:; "
                         "connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass

    def _user(self):
        """Trả về {user_id, username} từ header X-Token, hoặc None."""
        return kdb.user_tu_token(self.headers.get("X-Token"))

    def _guard(self):
        """Chặn DNS-rebinding (Host lạ) + CSRF (request từ site khác). True = an toàn."""
        host = (self.headers.get("Host") or "").strip().lower()
        if host not in _ALLOW_HOSTS:   # KHÔNG fail-open Host rỗng/thiếu — buộc khớp allowlist
            return False
        origin = self.headers.get("Origin")
        if origin and origin.strip().lower() not in _ALLOW_ORIGINS:
            return False
        site = (self.headers.get("Sec-Fetch-Site") or "").strip().lower()
        if site and site not in ("same-origin", "none"):
            return False
        # State-changing (POST/PUT/DELETE) BẮT BUỘC CSRF token khớp nonce same-origin (H1). Chống
        # blind-POST từ subprocess/curl/web lạ — chúng KHÔNG đọc được nonce same-origin để gửi header.
        if self.command in ("POST", "PUT", "DELETE"):
            tok = (self.headers.get("X-CSRF-Token") or "").strip()
            if not hmac.compare_digest(tok, CSRF_NONCE):
                return False
        return True

    def do_GET(self):
        # Bọc try/except: handler lỗi -> trả 500 JSON (KHÔNG để exception thoát ra làm RESET connection
        # -> frontend báo "Lỗi kết nối" sai lệch). Lỗi thật (vd DB lock) sẽ hiện rõ thay vì im lặng.
        try:
            self._do_GET()
        except Exception:
            try:
                import traceback; traceback.print_exc()   # log nội bộ (stderr) — KHÔNG gửi chi tiết ra client (INFO-LEAK)
                self._send(500, {"ok": False, "msg": "Lỗi máy chủ nội bộ"})
            except Exception: pass

    def _do_GET(self):
        if not self._guard():
            self._send(403, {"error": "forbidden"}); return
        p = urllib.parse.urlparse(self.path)
        if _la_loha_path(p.path) and not _can_lohapage():   # gate quyền LohaPage (Kênh nguồn + Đăng bài)
            self._send(200, _loi_lohapage()); return
        if p.path in ("/", "/index.html"):
            try:
                with open(os.path.join(WEB_DIR, "index.html"), "rb") as f:
                    _html = f.read()
                try:   # INJECT app_lang TỪ CONFIG (server = nguồn sự thật) → UI áp đúng dù localStorage không giữ
                    _al = (ngngu.doc_cau_hinh().get("app_lang") or "vi")
                    _html = _html.replace(b"<head>",
                        b'<head><script>window.__APP_LANG=%s;</script>' % json.dumps(_al).encode("utf-8"), 1)
                except Exception:
                    pass
                self._send(200, _html, "text/html")
            except Exception:
                import traceback; traceback.print_exc()
                self._send(500, "Lỗi tải trang", "text/plain")
        elif p.path == "/api/stats":
            self._send(200, thong_ke())
        elif p.path == "/api/cache/stats":
            s = _doc_settings()
            self._send(200, {"on": s.get("cache_on") is not False,
                             "cap_mb": int(s.get("cache_cap_mb") or cache_artifact.CAP_MB_MAC_DINH),
                             "size_mb": cache_artifact.dung_luong_mb()})
        elif p.path == "/api/log":
            with _log_lock:
                lines = _log_lines[-200:]
            lang = (urllib.parse.parse_qs(p.query).get("lang") or [""])[0]
            if lang == "en":
                import log_i18n
                lines = log_i18n.dich_nhieu(lines, "en")
            self._send(200, {"lines": lines, "running": _proc is not None})
        elif p.path == "/api/glossary_get":
            # CẢI THIỆN DỊCH: đọc từ điển/quy tắc người dùng nhập → đấu vào prompt Gemini
            gp = os.path.join(THU_MUC_GOC, "translation_memory", "00_user.md")
            try:
                content = open(gp, encoding="utf-8").read() if os.path.isfile(gp) else ""
            except OSError:
                content = ""
            self._send(200, {"content": content})
        elif p.path == "/api/quy_tac_rieng":
            # QUY TẮC RIÊNG (đặc thù video, vd "2 người xưng tôi/con vợ") — lưu settings, GIỮ qua tắt/reset
            self._send(200, {"content": _doc_settings().get("quy_tac_rieng", "")})
        elif p.path == "/api/task/list":
            with _task_lock:
                ts = list(_tasks)
            self._send(200, {"tasks": ts, "pause": _task_pause["on"], "dem": {
                "cho": sum(1 for t in ts if t["trang_thai"] == "cho"),
                "dang": sum(1 for t in ts if t["trang_thai"] == "dang"),
                "xong": sum(1 for t in ts if t["trang_thai"] == "xong"),
                "loi": sum(1 for t in ts if t["trang_thai"] == "loi")}})
        elif p.path == "/api/kn_list":
            # Tab Kênh nguồn: danh sách kênh (tóm tắt) + thư mục uploads LohaPage.
            cfg = _kn.doc()
            self._send(200, {"ok": True, "loha_uploads_dir": cfg.get("loha_uploads_dir") or "",
                             "kenh": [_kn.thong_ke(k) for k in cfg.get("kenh", [])]})
        elif p.path == "/api/kn_videos":
            # Lưới video 1 kênh (theo kid). Trả list {id,title,thumb,url,tai}.
            q = urllib.parse.parse_qs(p.query)
            kid = (q.get("kid", [""])[0] or "").strip()
            k = next((x for x in _kn.doc().get("kenh", []) if x.get("kid") == kid), None)
            if not k:
                self._send(200, {"ok": False, "msg": "Không thấy kênh."})
            else:
                self._send(200, {"ok": True, "kenh": _kn.thong_ke(k), "videos": k.get("videos", [])})
        elif p.path == "/api/kn_ds_list":
            # Mọi 'danh sách' (playlist RENDER) đã lưu — khác LoHa Page (đó là chọn video để ĐĂNG).
            self._send(200, {"ok": True, "danh_sach": _kn.ds_list()})
        elif p.path == "/api/queue_get":
            with _queue_lock:
                items = []
                for it in _queue:
                    rel = _rel_goc(it["path"])
                    nt_ten, _nt_ma = _nen_tang_tu_path(rel.split("/"))
                    try:
                        mb = round(os.path.getsize(it["path"]) / 1048576, 1)
                    except OSError:
                        mb = 0
                    items.append({"id": it["id"], "ten": it["ten"], "trang_thai": it["trang_thai"],
                                  "msg": it.get("msg", ""), "pct": it.get("pct", 0),
                                  "step": it.get("step", ""), "eta": _fmt_eta(_eta_giay(it)),
                                  "p": rel, "mb": mb, "nen": nt_ten})
            self._send(200, {"items": items})
        elif p.path == "/api/workflow_status":
            with _wf_lock:
                self._send(200, {"running": _wf["running"], "blocks": dict(_wf["blocks"]),
                                 "summary": _wf["summary"], "error": _wf["error"]})
        elif p.path == "/api/workflow_auto_get":
            with _wfauto_lock:
                self._send(200, {"on": _wfauto["on"], "interval": _wfauto["interval"], "max_moi_lan": _wfauto.get("max_moi_lan") or 0})
        elif p.path == "/api/render_progress":
            # Chi tiết video đang render (cho tab Tiến trình): bước + phụ đề điền dần + kết quả.
            # ĐA-LANE: trả LIST 'videos' (mỗi video 'dang' 1 mục) + giữ field cũ (video 'dang' đầu) cho UI cũ.
            with _queue_lock:
                dang = [it for it in _queue if it["trang_thai"] == "dang"]
                cur = dang[0] if dang else None
                if cur is None:
                    done = [it for it in _queue if it["trang_thai"] in ("xong", "loi")]
                    cur = done[-1] if done else None
                if cur is None:
                    self._send(200, {"active": False, "videos": []}); return
                def _vinfo(it):
                    orel = ""
                    if it["trang_thai"] == "xong":
                        _c = _output_xuly_moi_nhat(it["path"])
                        if _c:
                            orel = _rel_goc(_c)
                    return {"id": it.get("id"), "ten": it["ten"], "trang_thai": it["trang_thai"],
                            "lane": it.get("_lane", 0), "lang": (it.get("opts") or {}).get("lang", ""),
                            "res": _job_resource(it.get("opts")),
                            "cpu_free": bool(it.get("_cpu_free")),   # CPU job đã dub xong, đang encode (nvenc)
                            "pct": it.get("pct", 0), "step": it.get("step", ""),
                            "eta": _fmt_eta(_eta_giay(it)), "segs": list(it.get("segs", [])), "out_rel": orel}
                videos = [_vinfo(it) for it in dang] or [_vinfo(cur)]
                _c0 = videos[0]
                with _metric_lock:
                    _mh = list(_metric_hist)          # biểu đồ real-time CPU/GPU/Mạng (frontend đẩy vào chart)
                self._send(200, {"active": True, "ten": _c0["ten"], "trang_thai": _c0["trang_thai"],
                                 "pct": _c0["pct"], "step": _c0["step"], "eta": _c0["eta"],
                                 "segs": _c0["segs"], "out_rel": _c0["out_rel"],
                                 "videos": videos, "n_lane": _so_lane(), "metrics": _mh})
        elif p.path == "/api/queue_detail":
            # Chi tiết 1 video trong hàng đợi theo id (danh sách tổng quan tab Tiến trình bấm xem).
            q = urllib.parse.parse_qs(p.query)
            try:
                qid = int(q.get("id", ["0"])[0])
            except (ValueError, TypeError):
                qid = 0
            with _queue_lock:
                it = next((x for x in _queue if x["id"] == qid), None)
                if it is None:
                    self._send(200, {"active": False}); return
                out_rel = ""
                if it["trang_thai"] == "xong":
                    cand = _output_xuly_moi_nhat(it["path"])
                    if cand:
                        out_rel = _rel_goc(cand)
                self._send(200, {"active": True, "ten": it["ten"], "trang_thai": it["trang_thai"],
                                 "pct": it.get("pct", 0), "step": it.get("step", ""),
                                 "eta": _fmt_eta(_eta_giay(it)),
                                 "segs": list(it.get("segs", [])), "out_rel": out_rel})
        elif p.path == "/api/srt_export":
            # DỊCH THỦ CÔNG: tải phụ đề GỐC (zh) của video đang 'Chờ SRT' để mang đi dịch (ChatGPT/Gemini).
            q = urllib.parse.parse_qs(p.query)
            try:
                qid = int(q.get("id", ["0"])[0])
            except (ValueError, TypeError):
                qid = 0
            with _queue_lock:
                it = next((x for x in _queue if x["id"] == qid), None)
            zh = (it or {}).get("zh_srt") or ""
            if it and zh and os.path.isfile(zh):
                txt = open(zh, encoding="utf-8").read()
                self._send(200, {"ok": True, "ten": os.path.splitext(it["ten"])[0] + ".zh.srt", "content": txt})
            else:
                self._send(200, {"ok": False, "error": "Chưa có phụ đề gốc (ASR chưa xong?)."})
        elif p.path == "/api/auto_get":
            with _auto_lock:
                self._send(200, {"on": _auto["on"], "unlimited": _auto["unlimited"],
                                 "count": _auto["count"], "da_them": _auto["da_them"], "opts": _auto["opts"]})
        elif p.path == "/api/trang_get":
            import gom_dang_bai
            cfg = gom_dang_bai.doc_config()
            items = liet_ke_file(gioi_han=100000)
            tu_khoa = sorted({f["nhom_ten"] for f in items if f["loai"] == "Từ khóa" and f["nhom_ten"]})
            kenh = sorted({f["nhom_ten"] for f in items if f["loai"] == "Kênh" and f["nhom_ten"]})
            dem = {}
            db = gom_dang_bai.DANG_BAI            # userData (đúng chỗ gom GHI; trước đọc app-src cũ → đếm sai sau di cư)
            if os.path.isdir(db):
                for t in os.listdir(db):
                    d = os.path.join(db, t)
                    if os.path.isdir(d):
                        dem[t] = sum(1 for x in os.listdir(d) if x.lower().endswith(".mp4"))
            _tl_muc, _ = _pl_folders()           # thể loại (phân loại) cho cột "Phân loại" — mỗi thể loại = folder video render
            the_loai = [m["ten"] for m in _tl_muc]
            self._send(200, {"trang": cfg.get("trang", []), "tu_khoa": tu_khoa, "kenh": kenh,
                             "the_loai": the_loai, "dang_bai": dem,
                             "loha_uploads_dir": cfg.get("loha_uploads_dir", ""),
                             "auto_gom": bool(cfg.get("auto_gom")),
                             "auto_tai": bool(cfg.get("auto_tai")),
                             "auto_tai_n": int(cfg.get("auto_tai_n") or 1),
                             "auto_tai_gio": cfg.get("auto_tai_gio") or "08:00"})
        elif p.path == "/api/loha_auto_dir":
            # TỰ DÒ thư mục uploads LoHa Page (để "nối" tự động, khỏi tìm tay).
            self._send(200, {"path": _loha_auto_uploads()})
        elif p.path == "/api/giong_list":
            ds = []
            for ten, fn in (("Nữ (mặc định)", "nu.wav"), ("Nam (mặc định)", "nam.wav")):
                if os.path.isfile(os.path.join(GIONG_DIR, fn)):
                    ds.append({"ten": ten, "path": "giong_mau/" + fn, "xoa_duoc": False})
            if os.path.isdir(CLONE_DIR):
                for f in sorted(os.listdir(CLONE_DIR)):
                    if f.lower().endswith((".wav", ".mp3", ".m4a", ".flac")):
                        # CLONE_DIR ở userData (NGOÀI app-src) → path TUYỆT ĐỐI (built-in giong_mau/ vẫn relative)
                        ds.append({"ten": os.path.splitext(f)[0],
                                   "path": os.path.abspath(os.path.join(CLONE_DIR, f)).replace("\\", "/"),
                                   "xoa_duoc": True})
            self._send(200, {"items": ds})
        elif p.path == "/giong_audio":
            q = urllib.parse.parse_qs(p.query)
            rel = (q.get("p") or [""])[0].replace("/", os.sep)
            full = os.path.normpath(os.path.join(THU_MUC_GOC, rel))
            if not _trong_vung(full, GIONG_DIR, CLONE_DIR) or not os.path.isfile(full):   # commonpath, chống prefix-collision
                self._send(404, {"error": "not found"}); return
            data = open(full, "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif p.path == "/api/dub/preview":
            # NGHE THỬ giọng: synth 1 câu tiếng Việt bằng engine+giọng đang chọn → trả wav.
            # Chặn khi đang lồng tiếng (tránh tranh CPU/đụng model). 1 lần 1 preview.
            if _dub_busy or _dub_proc is not None:
                self._send(409, {"error": "Đang lồng tiếng, thử lại sau."}); return
            q = urllib.parse.parse_qs(p.query)
            engine = (q.get("engine") or ["edge"])[0]
            if engine not in ("edge", "piper", "omnivoice", "supertonic"):
                engine = "edge"
            lang = (q.get("lang") or ["en"])[0]   # supertonic: ngôn ngữ đích (en/ko...) cho câu nghe thử
            voice = (q.get("voice") or ["vi-VN-HoaiMyNeural"])[0]
            text = ((q.get("text") or [""])[0]).strip()[:200] or \
                "Xin chào các bạn, đây là giọng đọc thử cho video lồng tiếng."
            ref = ""
            cl = (q.get("clone") or [""])[0].replace("/", os.sep)
            if cl:
                _full = os.path.normpath(os.path.join(THU_MUC_GOC, cl))
                if _trong_vung(_full, GIONG_DIR, CLONE_DIR) and os.path.isfile(_full):   # commonpath, chống prefix-collision
                    ref = _full
            import tempfile
            out = os.path.join(tempfile.gettempdir(), "vc_preview_giong.wav")
            try:
                os.remove(out)
            except OSError:
                pass
            cmd = [PYTHON_VENV, "dub_preview.py", "--engine", engine, "--text", text, "--out", out]
            if engine in ("edge", "supertonic", "piper", "omnivoice"):
                cmd += ["--voice", voice]
            if engine == "supertonic":
                cmd += ["--lang", lang]
            if ref:
                cmd += ["--ref-audio", ref]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", creationflags=_NO_WINDOW, cwd=THU_MUC_GOC, timeout=150)
            except Exception as e:
                self._send(500, {"error": "Lỗi nghe thử: " + str(e)[:120]}); return
            if not os.path.isfile(out):
                self._send(500, {"error": "Không tạo được giọng thử.",
                                 "log": ((r.stdout or "") + (r.stderr or ""))[-200:]}); return
            data = open(out, "rb").read()
            try:
                os.remove(out)
            except OSError:
                pass
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif p.path == "/api/lich_su_cao":
            q = urllib.parse.parse_qs(p.query)
            try:
                _ngay = int((q.get("ngay") or ["0"])[0] or 0)
            except (TypeError, ValueError):
                _ngay = 0
            items = lich_su_cao(loc_nt=(q.get("nt") or [""])[0].strip(),
                                q=(q.get("q") or [""])[0],
                                chi_chua_tai=((q.get("chua_tai") or [""])[0] == "1"),
                                so_ngay=_ngay)
            self._send(200, {"items": items,
                             "nen_tang": [{"ma": k, "ten": v["ten"]} for k, v in NEN_TANG.items() if k in NEN_TANG_HO_TRO]})
        elif p.path == "/api/files":
            files = liet_ke_file()
            try:    # dung lượng ổ THẬT (ổ chứa dự án) cho donut sidebar
                du = shutil.disk_usage(THU_MUC_GOC)
                disk = {"total_gb": round(du.total / 1024**3, 1),
                        "free_gb": round(du.free / 1024**3, 1),
                        "used_gb": round(du.used / 1024**3, 1)}
            except Exception:
                disk = {}
            self._send(200, {"files": files, "kenh_avatar": kenh_avatar_theo_folder(files), "disk": disk,
                             "out_dirs": sorted(_OUT_DIRS)})
        elif p.path == "/api/aikeys_get":
            import ai_dich
            self._send(200, {"keys": ai_dich.danh_sach(), "cfg": ai_dich.cau_hinh(),
                             "trangthai": ai_dich.trang_thai_ai(),
                             "providers": {k: {"ten": v["ten"], "models": v["models"],
                                               "key_url": v.get("key_url", "")}
                                           for k, v in ai_dich.PROVIDERS.items()}})
        elif p.path == "/api/ai_models":
            import ai_dich
            q = urllib.parse.parse_qs(p.query)
            self._send(200, {"models": ai_dich.lay_models(q.get("provider", ["gemini"])[0])})
        elif p.path == "/api/dub/log":
            with _dub_lock:
                out_rel = ""
                if _dub_out:
                    try:
                        out_rel = _rel_goc(_dub_out)
                    except Exception:
                        out_rel = ""
                self._send(200, {"lines": _dub_log[-200:], "running": _dub_proc is not None,
                                 "pct": _dub_pct, "out": _dub_out, "out_rel": out_rel,
                                 "segs": list(_dub_segs)})
        elif p.path == "/api/chupsub/log":
            with _chup_lock:
                self._send(200, {"lines": _chup_log[-200:], "running": _chup_running,
                                 "out": _chup_out})
        elif p.path == "/api/chupsub/result":
            q = urllib.parse.parse_qs(p.query)
            self._send(200, chup_sub_ket_qua((q.get("folder") or [""])[0]))
        elif p.path == "/api/bam/log":
            with _bam_lock:
                self._send(200, {"lines": _bam_log[-200:], "running": _bam_running,
                                 "clips": list(_bam_out)})
        elif p.path == "/api/bam/videos":
            vids = [f for f in liet_ke_file()
                    if str(f.get("name", "")).lower().endswith((".mp4", ".mov", ".mkv", ".webm"))]
            self._send(200, {"videos": vids})
        elif p.path == "/api/bam/folder":
            q = urllib.parse.parse_qs(p.query)
            folder = (q.get("path") or [""])[0].strip().strip('"')
            if not folder or not os.path.isdir(folder):
                self._send(200, {"ok": False, "videos": [], "msg": "Không thấy thư mục."}); return
            vids = []
            for f in sorted(os.listdir(folder)):
                full = os.path.join(folder, f)
                if os.path.isfile(full) and _bam_la_video(f):
                    try:
                        mb = round(os.path.getsize(full) / 1048576, 1)
                    except OSError:
                        mb = 0
                    vids.append({"name": f, "p": full.replace("\\", "/"), "mb": mb})
            self._send(200, {"ok": True, "videos": vids})
        elif p.path == "/api/bam/seekable":
            # Web-optimize (faststart) video cho editor băm → tua/cắt tức thì, khỏi đợi load hết.
            # p = rel (THU_MUC_GOC) hoặc abs (video tự thêm). Trả path để UI gắn /video?p=
            q = urllib.parse.parse_qs(p.query)
            raw = (q.get("p") or [""])[0].replace("\\", "/")
            if os.path.isabs(raw) or (len(raw) > 1 and raw[1] == ":"):
                srcp = os.path.normpath(raw)
            else:
                srcp = os.path.normpath(os.path.join(THU_MUC_GOC, raw.lstrip("/")))
            if not raw or not os.path.isfile(srcp):
                self._send(200, {"ok": False, "p": raw, "msg": "không thấy video"}); return
            # BẢO MẬT: chỉ nhận FILE VIDEO vào ffmpeg (chống đưa path tuỳ ý như C:\Windows\... vào -i).
            # Băm nhỏ vốn chỉ xử lý video → không phá tính năng (thư mục user tự chọn vẫn dùng bình thường).
            if not _bam_la_video(os.path.basename(srcp)):
                self._send(200, {"ok": False, "p": raw, "msg": "chỉ hỗ trợ file video"}); return
            out = _bam_seekable(srcp)
            self._send(200, {"ok": True, "p": out.replace("\\", "/"),
                             "optimized": os.path.abspath(out) != os.path.abspath(srcp)})
        elif p.path == "/api/bam/phan_tich/status":
            with _bam_pt_lock:
                self._send(200, {"running": _bam_pt["running"], "done": _bam_pt["done"],
                                 "dur": _bam_pt["dur"], "scenes": _bam_pt["scenes"],
                                 "err": _bam_pt["err"]})
        elif p.path.startswith("/anhchup/"):
            rel = urllib.parse.unquote(p.path[len("/anhchup/"):]).replace("/", os.sep)
            full = os.path.normpath(os.path.join(ANH_CHUP_DIR, rel))
            if not full.startswith(ANH_CHUP_DIR) or not os.path.isfile(full):
                self._send(404, {"error": "not found"}); return
            ctype = {".png": "image/png", ".jpg": "image/jpeg", ".wav": "audio/wav",
                     ".mp3": "audio/mpeg", ".mp4": "video/mp4", ".json": "application/json"}.get(
                         os.path.splitext(full)[1].lower(), "application/octet-stream")
            data = open(full, "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif p.path == "/api/dub/engines":
            vids = [f for f in liet_ke_file()
                    if str(f.get("name", "")).lower().endswith((".mp4", ".mov", ".mkv", ".webm"))]
            self._send(200, {"engines": dub_engines(), "videos": vids,
                             "voices": [{"id": "vi-VN-HoaiMyNeural", "ten": "Nữ — Hoài My"},
                                        {"id": "vi-VN-NamMinhNeural", "ten": "Nam — Nam Minh"}]})
        elif p.path == "/api/may_goi_y":
            self._send(200, _may_goi_y())   # cấu hình máy → gợi ý engine TTS (Render + Lồng tiếng)
        elif p.path == "/api/ai_key":
            import ai_dich
            self._send(200, {"has_key": bool(ai_dich.key_groq_dung_duoc() or load_ai_key())})
        elif p.path == "/api/lang_get":
            self._send(200, ngngu.doc_cau_hinh())
        elif p.path == "/api/pl_import_muc":
            # IMPORT THỂ LOẠI: thêm 1 folder (đã chứa video render) làm 1 'thể loại' → hiện ở cột Phân loại để tick.
            ten = _pl_safe_ten(body.get("ten") or "")
            path = (body.get("path") or "").strip().strip('"')
            if not path or not os.path.isdir(path):
                self._send(200, {"ok": False, "msg": "Thư mục không tồn tại: " + (path or "(trống)")}); return
            if not ten:
                ten = _pl_safe_ten(os.path.basename(path.rstrip("/\\"))) or "thể loại"
            s = _doc_settings()
            muc, _ = _pl_folders(s)
            if any(m["ten"].lower() == ten.lower() for m in muc):
                self._send(200, {"ok": False, "msg": "Đã có thể loại tên '%s'." % ten}); return
            muc.append({"ten": ten, "path": path})
            s["phan_loai_on"] = True
            s["phan_loai_muc"] = muc
            for _k in ("phan_loai_base", "phan_loai_names", "phan_loai_default_name"):
                s.pop(_k, None)
            _luu_settings(s)
            self._send(200, {"ok": True, "ten": ten, "so_video": sum(1 for x in os.listdir(path) if x.lower().endswith(".mp4"))})
        elif p.path == "/api/phan_loai":
            # Đọc cấu hình TỰ PHÂN LOẠI: muc=[{ten, path đầy đủ TỰ DO}] + default_path. _pl_folders đã
            # chuẩn hóa + tương thích ngược config cũ (base+names).
            s = _doc_settings()
            muc, default = _pl_folders(s)
            # path_rel/default_path_rel: quy về CÙNG định dạng với f.p (liet_ke_file dùng _rel_goc) để
            # UI (fileTheLoai) so khớp folder đúng — category CÙNG Ổ ĐĨA với app có f.p dạng "../Videos/x"
            # (tương đối), còn path cấu hình là tuyệt đối "C:/Users/.../Videos/x" → so string luôn trật →
            # badge/lọc thể loại KHÔNG hiện dù backend ĐÃ chuyển file đúng chỗ (chỉ category khác ổ đĩa,
            # nơi _rel_goc cũng trả tuyệt đối, mới tình cờ khớp).
            _raw = {(_pl_safe_ten(m.get("ten") or "")).lower(): m
                    for m in (s.get("phan_loai_muc") or []) if isinstance(m, dict)}
            for m in muc:
                m["path_rel"] = _rel_goc(m["path"])
                _r = _raw.get(m["ten"].lower())      # đính kèm dich (đích LohaPage) để UI dựng lại picker
                if _r and isinstance(_r.get("dich"), dict):
                    m["dich"] = _r["dich"]
            default_rel = _rel_goc(default) if default else ""
            self._send(200, {"on": bool(s.get("phan_loai_on")), "muc": muc, "default_path": default,
                             "default_path_rel": default_rel, "lohapage": _can_lohapage(),
                             "loha_dir": _pl_loha_dir(),
                             "base": _pl_base(), "names": [m["ten"] for m in muc]})
        elif p.path == "/api/data_dir":
            # Thư mục đang lưu video (cào + render) + dung lượng trống — cho tab Cài đặt
            root_cur = os.path.dirname(DATA_DIR) or DATA_DIR
            try:
                free_gb = round(shutil.disk_usage(root_cur if os.path.isdir(root_cur) else DATA_DIR).free / (1024**3), 1)
            except Exception:
                free_gb = None
            self._send(200, {"root": root_cur, "data_dir": DATA_DIR, "processed_dir": PROCESSED_DIR,
                             "da_chon": bool((_doc_settings().get("data_root") or "").strip()),
                             "free_gb": free_gb})
        elif p.path == "/api/lang_dict":
            q = urllib.parse.parse_qs(p.query)
            lang = (q.get("lang") or ["en"])[0]
            fdict = os.path.join(WEB_DIR, "lang_%s.json" % lang)
            try:
                with open(fdict, encoding="utf-8") as f:
                    self._send(200, json.load(f))
            except Exception:
                self._send(200, {})
        elif p.path == "/api/anh_search_get":
            with _anh_lock:
                self._send(200, {"running": _anh["running"], "items": _anh["items"],
                                 "msg": _anh["msg"], "platform": _anh["platform"]})
        elif p.path == "/api/login_status":
            self._send(200, {p2: da_dang_nhap(p2) for p2 in ("dy", "bili", "xhs", "rednote", "wb")})
        elif p.path == "/api/login_trangthai":
            # Trạng thái cho 6 thẻ: in / out / unknown / na (na = yt-dlp, không cần đăng nhập)
            # Ưu tiên 'in' LIVE từ _login_check.json (mo_dang_nhap ghi từ context đang chạy) nếu còn
            # tươi (<5 phút) — đọc trực tiếp context chắc chắn hơn đọc cookie trên đĩa (tránh báo 'out' oan).
            live = {}
            try:
                lc = os.path.join(THU_MUC_GOC, "_login_check.json")
                if os.path.exists(lc) and (time.time() - os.path.getmtime(lc)) < 300:
                    with open(lc, encoding="utf-8") as f:
                        live = json.load(f)
            except Exception:
                live = {}
            tt = {}
            for x in NEN_TANG_LOGIN:
                if x.get("ytdlp") or x.get("khong_login"):
                    tt[x["ma"]] = "na"
                elif x.get("chup"):
                    tt[x["ma"]] = _trang_thai_login_chup(x["ma"])
                elif live.get(x["ma"]) in ("in", "out"):
                    # Kết quả LIVE tươi (<5') từ kiem_tra_login (đã xác minh API/DOM thật) hoặc mo_dang_nhap.
                    # Tôn trọng CẢ "out": trước đây chỉ nhận "in" → live "out" bị disk-presence ("xanh giả"
                    # do cookie hết hạn còn trên đĩa) che mất → thẻ vẫn xanh dù đã xác minh là chưa đăng nhập.
                    tt[x["ma"]] = live[x["ma"]]
                else:
                    tt[x["ma"]] = trang_thai_dang_nhap(x["ma"])
            self._send(200, {"plats": NEN_TANG_LOGIN, "trang_thai": tt})
        elif p.path == "/api/folders":
            q = urllib.parse.parse_qs(p.query)
            self._send(200, liet_ke_folder((q.get("path") or [""])[0]))
        elif p.path == "/api/td_get":
            cfg = doc_json(FILE_TD, {"creators": [], "interval": "30", "count": "10"})
            try:   # gắn tên ĐÃ DỊCH (Trung→Việt) cho mỗi kênh có nickname chữ Hán → UI hiện kèm tên gốc
                _crs = [c for c in (cfg.get("creators") or []) if isinstance(c, dict) and c.get("nickname")]
                _vmap = dich_tieu_de_batch([c["nickname"] for c in _crs]) if _crs else {}
                for c in _crs:
                    _vi = (_vmap.get(c["nickname"]) or "").strip()
                    if _vi and _vi != c["nickname"]:
                        c["ten_vi"] = _vi
            except Exception:
                pass
            self._send(200, {"cfg": cfg, "on": task_on(TASK_TD)})
        elif p.path == "/api/td_list":
            # Theo dõi kênh (metadata) — danh sách kênh + video mới đã dò. Gate TIER (KHÔNG LohaPage).
            ds = [_td_thong_ke(c) for c in _td_doc().get("creators", [])]
            try:      # tên đã DỊCH (Trung→Việt) hiện kèm (như tab Video mới cũ)
                _nn = [c.get("nickname") for c in ds if c.get("nickname")]
                _vmap = dich_tieu_de_batch(_nn) if _nn else {}
                for c in ds:
                    _vi = (_vmap.get(c.get("nickname")) or "").strip()
                    if _vi and _vi != c.get("nickname"):
                        c["ten_vi"] = _vi
            except Exception:
                pass
            ds.sort(key=lambda c: (c["so_moi"] > 0, c["cao_luc"]), reverse=True)
            self._send(200, {"kenh": ds})
        elif p.path == "/api/video_moi":
            import video_moi
            try:
                video_moi.tao_links()   # cập nhật cây folder mỗi lần mở tab (cả crawl thủ công lẫn theo dõi)
            except Exception:
                pass
            _ds = video_moi.doc_nhom()
            try:
                _amap = avatar_kenh_map()       # {nickname: avatar}
                _smap = avatar_secuid_map()      # {sec_uid: avatar} — ưu tiên (kenh có thể là tên đã dịch)
            except Exception:
                _amap = _smap = {}
            for _k in _ds:              # enrich: avatar kênh + p (rel cho /video thumbnail + render) + mtime (cache-bust)
                _k["avatar"] = _smap.get(_k.get("sec_uid", ""), "") or _amap.get(_k.get("kenh", ""), "")
                for _v in _k.get("videos", []):
                    _f = (_v.get("file") or "").strip()
                    if not _f:
                        continue
                    _abs = os.path.join(video_moi.THU_MUC_DATA, _v.get("platform", ""), "videos", *_f.split("/"))
                    if os.path.isfile(_abs):
                        _v["p"] = _rel_goc(_abs)
                        try:
                            _v["mtime"] = int(os.path.getmtime(_abs))
                        except OSError:
                            _v["mtime"] = 0
            try:   # tên kênh đã DỊCH (Trung→Việt) cho ô/modal Video mới hiện kèm tên gốc
                _vmap = dich_tieu_de_batch([_k.get("kenh", "") for _k in _ds if _k.get("kenh")])
                for _k in _ds:
                    _vi = (_vmap.get(_k.get("kenh", "")) or "").strip()
                    if _vi and _vi != _k.get("kenh"):
                        _k["ten_vi"] = _vi
            except Exception:
                pass
            self._send(200, {"kenh": _ds})
        elif p.path == "/api/kenh_info":
            # Lấy nickname+avatar 1 kênh từ LINK (cho 'Theo dõi' hiện tên+avatar khi DÁN LINK, khỏi qua Gợi ý kênh)
            link = (urllib.parse.parse_qs(p.query).get("link") or [""])[0].strip()
            info = {}
            if link:
                try:
                    kq = subprocess.run([PYTHON_VENV, "lay_kenh_info.py", link], cwd=THU_MUC_GOC,
                                        env=os.environ.copy(), capture_output=True, text=True,
                                        encoding="utf-8", errors="replace", creationflags=_NO_WINDOW, timeout=40)
                    for ln in reversed((kq.stdout or "").splitlines()):
                        ln = ln.strip()
                        if ln.startswith("{"):
                            info = json.loads(ln); break
                except Exception as e:
                    info = {"loi": str(e)[:120]}
            self._send(200, info)
        elif p.path == "/api/lich_get":
            cfg = doc_json(FILE_LICH, {"platform": "dy", "type": "search", "input": "",
                                       "count": "10", "sort": 0, "publish_time": 0, "gio": "08", "phut": "00"})
            self._send(200, {"cfg": cfg, "on": task_on(TASK_LICH)})
        elif p.path == "/api/auth/me":
            u = self._user()
            if u:
                self._send(200, {"ok": True, "username": u["username"]})
            else:
                self._send(401, {"ok": False})
        elif p.path == "/api/goi":
            self._send(200, _goi_info())
        elif p.path == "/api/auth/bootstrap":
            # EMBEDDED (app Electron đã xác thực license) -> vào thẳng tool, KHÔNG đăng nhập lần 2.
            # Standalone (CAO-VIDEO.bat) -> embedded=False -> giữ cổng đăng nhập khach_db như cũ.
            if EMBEDDED:
                if BOOTSTRAP_NONCE:
                    got = urllib.parse.parse_qs(p.query).get("k", [""])[0]
                    if not hmac.compare_digest(got, BOOTSTRAP_NONCE):
                        self._send(403, {"ok": False, "error": "bootstrap nonce sai"}); return
                sess = kdb.dam_bao_phien_local(OWNER)
                self._send(200, {"ok": True, "embedded": True,
                                 "token": sess["token"], "username": sess["username"],
                                 "nonce": CSRF_NONCE})
            else:
                self._send(200, {"ok": True, "embedded": False, "nonce": CSRF_NONCE})
        elif p.path == "/api/khach/list":
            u = self._user()
            if not u:
                self._send(401, {"error": "Chưa đăng nhập"}); return
            self._send(200, {"khach": kdb.liet_ke_khach(u["user_id"])})
        elif p.path == "/api/khach/tk":
            u = self._user()
            if not u:
                self._send(401, {"error": "Chưa đăng nhập"}); return
            q = urllib.parse.parse_qs(p.query)
            khach_id = int(q.get("khach_id", ["0"])[0] or 0)
            hien = q.get("hien", ["0"])[0] == "1"
            self._send(200, {"tk": kdb.liet_ke_tk(u["user_id"], khach_id, hien)})
        elif p.path == "/video":
            q = urllib.parse.parse_qs(p.query)
            rel = q.get("p", [""])[0]
            self._serve_video(_resolve_video(rel))
        elif p.path == "/thumb":
            # Ảnh thu nhỏ 1 khung hình của video (cache theo mtime) cho lưới chọn video
            q = urllib.parse.parse_qs(p.query)
            full = _resolve_video(q.get("p", [""])[0])
            if not full:
                self._send(404, b"", "image/jpeg"); return
            import hashlib
            cache_dir = os.path.join(tempfile.gettempdir(), "tcv_thumbs")
            os.makedirs(cache_dir, exist_ok=True)
            key = hashlib.md5((full + str(os.path.getmtime(full))).encode("utf-8")).hexdigest()
            thumb = os.path.join(cache_dir, key + ".jpg")
            if not os.path.isfile(thumb):
                subprocess.run([shutil.which("ffmpeg") or "ffmpeg", "-y", "-ss", "1", "-i", full,
                                "-vframes", "1", "-vf", "scale=300:-2", thumb],
                               capture_output=True, creationflags=_NO_WINDOW)
            if os.path.isfile(thumb):
                with open(thumb, "rb") as f:
                    self._send(200, f.read(), "image/jpeg")
            else:
                self._send(404, b"", "image/jpeg")
        elif p.path.startswith(("/logos/", "/giong_thu/", "/flags/")) or p.path.endswith((".png", ".jpg", ".css", ".js", ".ico", ".svg")):
            self._serve_static(p.path)   # +/giong_thu/: MP3 nghe thử; +/flags/: cờ nước SVG (tĩnh)
        else:
            self._send(404, {"error": "not found"})

    def _serve_static(self, path):
        safe = os.path.normpath(os.path.join(WEB_DIR, path.lstrip("/")))
        if not safe.startswith(os.path.normpath(WEB_DIR)) or not os.path.isfile(safe):
            self._send(404, {"error": "not found"})
            return
        ext = os.path.splitext(safe)[1].lower()
        ctype = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                 ".css": "text/css", ".js": "application/javascript", ".ico": "image/x-icon",
                 ".svg": "image/svg+xml",
                 ".mp3": "audio/mpeg", ".wav": "audio/wav"}.get(ext, "application/octet-stream")
        with open(safe, "rb") as f:
            self._send(200, f.read(), ctype)

    def _serve_video(self, full):
        if not full:
            self._send(404, {"error": "not found"})
            return
        size = os.path.getsize(full)
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        code = 200
        if rng and rng.startswith("bytes="):
            try:
                s, e = rng[6:].split("-")
                start = int(s) if s else 0
                end = int(e) if e else size - 1
                code = 206
            except Exception:
                start, end = 0, size - 1
        end = min(end, size - 1)
        length = end - start + 1
        self.send_response(code)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        try:
            with open(full, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(262144, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass   # trình duyệt HỦY stream giữa chừng (tua/seek video) — Windows ném 10053 ConnectionAborted

    def do_POST(self):
        # Bọc try/except: handler lỗi (vd kdb.dang_nhap throw do DB lock/corrupt) -> trả 500 JSON có thông báo
        # THẬT, KHÔNG để exception thoát ra làm reset connection -> frontend báo "Lỗi kết nối" sai lệch.
        try:
            self._do_POST()
        except Exception:
            try:
                import traceback; traceback.print_exc()   # log nội bộ (stderr) — KHÔNG gửi chi tiết ra client (INFO-LEAK)
                try:                                       # + ghi ra FILE để chẩn lỗi 500 (vd thêm key) khi không xem được stderr
                    import datetime as _dt
                    with open(os.path.join(DATA_DIR, "_loi_500.log"), "a", encoding="utf-8") as _lf:
                        _lf.write("=== %s POST %s ===\n%s\n" % (_dt.datetime.now().strftime("%H:%M:%S"),
                                                               getattr(self, "path", "?"), traceback.format_exc()))
                except Exception:
                    pass
                self._send(500, {"ok": False, "msg": "Lỗi máy chủ nội bộ"})
            except Exception: pass

    def _do_POST(self):
        if not self._guard():
            self._send(403, {"error": "forbidden"}); return
        p = urllib.parse.urlparse(self.path)
        ln = int(self.headers.get("Content-Length", 0))
        # errors="replace": body lạ/không-UTF-8 KHÔNG làm crash decode (trước đây ném UnicodeDecodeError
        # TRƯỚC try json.loads → 500 rỗng → frontend báo "Không thêm được" khó hiểu).
        raw = self.rfile.read(ln).decode("utf-8", "replace") if ln else "{}"
        try:
            body = json.loads(raw) if raw else {}
        except Exception:
            body = {}
        if _la_loha_path(p.path) and not _can_lohapage():   # gate quyền LohaPage (Kênh nguồn + Đăng bài)
            self._send(200, _loi_lohapage()); return
        if p.path == "/api/crawl":
            g = _guard_expired("cao")
            if g:
                self._send(200, g); return
            gh = _lim("cao_ngay")
            if gh is not None:
                conlai = gh - kdb.usage_lay("cao")
                if conlai <= 0:
                    self._send(200, _block("cao", f"Đã đạt giới hạn cào {gh} video/ngày của gói {TIER.upper()}. Nâng cấp để cào không giới hạn.")); return
                try:
                    if int(str(body.get("count") or "10")) > conlai:
                        body["count"] = str(conlai)   # cắt theo số còn lại
                except Exception:
                    pass
            r = chay_crawl(body) or {"ok": True}
            # KHÔNG cộng usage ở đây (đó chỉ là SỐ YÊU CẦU). Đếm theo video TẢI THÀNH CÔNG thật
            # trong _crawl_worker (mỗi 'save video success' / tổng 'YTDLP_DONE n').
            self._send(200, r)
        elif p.path == "/api/task/add":     # xếp 1 job cào vào hàng đợi (chạy lần lượt)
            g = _guard_expired("cao")       # expired: chặn NGAY khi xếp (chay_crawl vẫn chốt lại lúc chạy)
            if g:
                self._send(200, g); return
            tid = _task_them(body.get("kind", "crawl"), nhan=(body.get("nhan") or ""),
                             platform=body.get("platform", "dy"), type=body.get("type", "search"),
                             input=(body.get("input") or "").strip(), count=body.get("count", 10),
                             opts=body.get("opts") or {})
            self._send(200, {"ok": True, "id": tid})
        elif p.path == "/api/task/remove":  # xoá 1 task (không xoá task ĐANG chạy)
            _id = body.get("id")
            with _task_lock:
                _tasks[:] = [t for t in _tasks if not (t.get("id") == _id and t["trang_thai"] != "dang")]
            _task_luu()
            self._send(200, {"ok": True})
        elif p.path == "/api/task/clear":   # scope: done (xoá xong/lỗi) | all (giữ task đang chạy)
            scope = body.get("scope", "done")
            with _task_lock:
                if scope == "all":
                    _tasks[:] = [t for t in _tasks if t["trang_thai"] == "dang"]
                else:
                    _tasks[:] = [t for t in _tasks if t["trang_thai"] not in ("xong", "loi")]
            _task_luu()
            self._send(200, {"ok": True})
        elif p.path == "/api/task/cancel":  # huỷ task: ĐANG chạy → kill crawl + "đã huỷ"; CHỜ → đánh huỷ luôn
            _id = body.get("id"); _stop = False
            with _task_lock:
                t = next((x for x in _tasks if x.get("id") == _id), None)
                if t and t.get("trang_thai") == "dang":
                    t["cancel"] = True; _stop = True            # worker thấy cờ → đánh "đã huỷ" sau khi _proc chết
                elif t and t.get("trang_thai") == "cho":
                    t["trang_thai"], t["msg"], t["reason"] = "loi", "⛔ Đã huỷ", "cancelled"
            if _stop:
                dung_crawl()                                    # kill _proc (gọi NGOÀI _task_lock, tránh deadlock)
            _task_luu()
            self._send(200, {"ok": True})
        elif p.path == "/api/task/retry":   # xếp lại 1 task lỗi → "chờ" (worker chạy lại)
            _id = body.get("id")
            with _task_lock:
                for t in _tasks:
                    if t.get("id") == _id and t.get("trang_thai") == "loi":
                        t["trang_thai"], t["msg"], t["pct"], t["reason"] = "cho", "", 0, ""
                        t.pop("cancel", None)
            _task_luu()
            self._send(200, {"ok": True})
        elif p.path == "/api/task/retry_all":  # xếp lại task lỗi; lọc theo reason VÀ/HOẶC platform
            scope = body.get("reason")          # None = mọi reason; hoặc "login_expired"...
            plat = body.get("platform")         # None = mọi nền; hoặc "dy"/"bili"... → "Retry Douyin"
            with _task_lock:
                for t in _tasks:
                    if (t.get("trang_thai") == "loi"
                            and (scope is None or t.get("reason") == scope)
                            and (plat is None or t.get("platform") == plat)):
                        t["trang_thai"], t["msg"], t["pct"], t["reason"] = "cho", "", 0, ""
                        t.pop("cancel", None)
            _task_luu()
            self._send(200, {"ok": True})
        elif p.path == "/api/task/pause":   # Stop-After-Current: on=true → worker nghỉ sau task hiện tại
            _task_pause["on"] = bool(body.get("on"))
            self._send(200, {"ok": True, "pause": _task_pause["on"]})
        elif p.path == "/api/video_moi_da_xem":
            import video_moi
            n = video_moi.danh_dau_da_xem(aweme_ids=body.get("aweme_ids"), sec_uid=body.get("sec_uid"))
            self._send(200, {"ok": True, "n": n})
        elif p.path == "/api/anh_search":
            self._send(200, chay_tim_anh(body))
        elif p.path == "/api/anh_cao":
            self._send(200, cao_anh_chon(body))
        elif p.path == "/api/kn_them":
            # Tab Kênh nguồn: cào metadata 1 kênh (creator) → lưu profile + videos.
            self._send(200, _kn_cao_kenh(body.get("platform", "dy"), body.get("link") or body.get("input") or "",
                                         int(body.get("count") or 30)))
        elif p.path == "/api/kn_loha_dir":
            # Đặt thư mục uploads LohaPage (dùng chung mọi kênh).
            self._send(200, {"ok": True, "loha_uploads_dir": _kn.dat_loha_dir(body.get("path") or "")})
        elif p.path == "/api/loha_dir_chung":
            # HUB Đăng bài: đặt thư mục uploads LohaPage DÙNG CHUNG → ghi cả kenh_nguon (Kênh nguồn) LẪN
            # trang_config (gom cũ) → 1 nguồn cho mọi luồng giao. (Phân loại dùng path thể loại tự do, không đụng.)
            _p = (body.get("path") or "").strip()
            _kn.dat_loha_dir(_p)
            try:
                import gom_dang_bai
                _tc = gom_dang_bai.doc_config()
                _tc["loha_uploads_dir"] = _p
                gom_dang_bai.luu_config(_tc)
            except Exception:
                pass
            self._send(200, {"ok": True, "loha_uploads_dir": _p})
        elif p.path == "/api/kn_import":
            # Import MỌI kênh đã cào-theo-link (creator_contents jsonl) vào Kênh nguồn — không cào lại.
            self._send(200, _kn_import_da_cao(body.get("platform") or ""))
        elif p.path == "/api/kn_capnhat":
            # Cập nhật 1 kênh: re-crawl metadata → lấy video MỚI đăng (merge, giữ 'tai').
            k = next((x for x in _kn.doc().get("kenh", []) if x.get("kid") == (body.get("kid") or "")), None)
            if not k:
                self._send(200, {"ok": False, "msg": "Không thấy kênh."})
            else:
                self._send(200, _kn_cao_kenh(k.get("platform"), k.get("link")))
        elif p.path == "/api/kn_capnhat_het":
            # Cập nhật TẤT CẢ kênh (nền) — lấy video mới đăng.
            threading.Thread(target=_kn_capnhat_het, daemon=True).start()
            self._send(200, {"ok": True, "msg": "Đang cập nhật tất cả kênh (nền) — lấy video mới đăng."})
        elif p.path == "/api/kn_dich_tieu_de":
            # Dịch (chuẩn hoá) TOÀN BỘ tiêu đề tiếng Trung chưa dịch của 1 kênh, dùng luôn làm caption thật.
            kid = body.get("kid") or ""
            if not any(k.get("kid") == kid for k in _kn.doc().get("kenh", [])):
                self._send(200, {"ok": False, "msg": "Không thấy kênh."})
            else:
                threading.Thread(target=_kn_dich_tieu_de_kenh, args=(kid,), daemon=True).start()
                self._send(200, {"ok": True, "msg": "Đang dịch tiêu đề (Gemini web) ở nền — mở lại kênh sau ít phút để xem."})
        elif p.path == "/api/kn_lich":
            k = _kn.dat_lich(body.get("platform", ""), body.get("link", ""), body.get("lich") or {})
            self._send(200, {"ok": bool(k), "kenh": _kn.thong_ke(k) if k else None})
        elif p.path == "/api/kn_dich":
            k = _kn.dat_dich(body.get("platform", ""), body.get("link", ""), body.get("dich") or {})
            self._send(200, {"ok": bool(k), "kenh": _kn.thong_ke(k) if k else None})
        elif p.path == "/api/kn_doiten":
            k = _kn.doi_ten(body.get("platform", ""), body.get("link", ""), body.get("ten") or "")
            self._send(200, {"ok": bool(k), "kenh": _kn.thong_ke(k) if k else None})
        elif p.path == "/api/kn_xoa":
            ok = _kn.xoa_kenh(body.get("platform", ""), body.get("link", ""))
            self._send(200, {"ok": ok})
        elif p.path == "/api/kn_ds_luu":
            # Lưu 1 danh sách = tên + kênh + list id video (đúng thứ tự). dong_bo=True → đặt luôn
            # title_vi='<ten_tap> Tập N' theo thứ tự (đồng bộ tên tập, dùng làm caption thật khi đăng);
            # ten_tap rỗng → lùi về dùng tên danh sách.
            rec = _kn.ds_luu(body.get("ten") or "", body.get("kid") or "", body.get("ids") or [],
                             dong_bo=bool(body.get("dong_bo")), ten_tap=body.get("ten_tap") or "")
            self._send(200, {"ok": bool(rec), "danh_sach": rec})
        elif p.path == "/api/kn_ds_xoa":
            self._send(200, {"ok": _kn.ds_xoa(body.get("ten") or "")})
        elif p.path == "/api/kn_tai_ngay":
            # Tải NGAY video chưa tải của 1 kênh (không đợi lịch) → render → giao LohaPage. Chạy nền.
            # body.ids CÓ → tải ĐÚNG các video đã tick chọn tay; KHÔNG có → N video cũ nhất (body.n).
            k = next((x for x in _kn.doc().get("kenh", []) if x.get("kid") == (body.get("kid") or "")), None)
            if not k:
                self._send(200, {"ok": False, "msg": "Không thấy kênh."})
            else:
                _n = int(body.get("n") or 0)
                _ids = [str(i) for i in (body.get("ids") or []) if str(i).strip()] or None
                threading.Thread(target=_kn_tai_va_render, args=(k, _n, True, None, _ids), daemon=True).start()
                msg = f"Đang tải + render {len(_ids)} video đã chọn (nền) → sẽ tự giao LohaPage." if _ids \
                    else "Đang tải + render nền → sẽ tự giao LohaPage."
                self._send(200, {"ok": True, "msg": msg})
        elif p.path == "/api/anh_ocr":
            self._send(200, chay_ocr_anh(body))
        elif p.path == "/api/detect_band":
            self._send(200, chay_detect_band(body))
        elif p.path == "/api/cache/co":
            # Kiểm video đã có CACHE bản dịch chưa → UI hỏi "dùng lại dịch/lồng tiếng hay render từ đầu".
            # Nhận 1 video ("video"/"p") hoặc nhiều ("paths"); trả co=True nếu CÓ ÍT NHẤT 1 video đã cache.
            raw = body.get("paths") or ([body.get("video") or body.get("p")] if (body.get("video") or body.get("p")) else [])
            n = 0
            for x in raw:
                v = _resolve_video((x or "").replace("\\", "/").lstrip("/"))
                if v and cache_artifact.co_srt(v):
                    n += 1
            self._send(200, {"ok": True, "co": n > 0, "n": n, "tong": len(raw)})
        elif p.path == "/api/cache/clear":
            # Bỏ cache để render lại từ đầu. scope='all' (toàn bộ) hoặc 'video' + path 1 video.
            scope = body.get("scope", "all")
            vid = (body.get("video") or "").replace("\\", "/").lstrip("/")
            vh = None
            if scope == "video" and vid:
                _vp = os.path.normpath(os.path.join(THU_MUC_GOC, vid))
                vh = cache_artifact.video_hash(_vp)
            n = cache_artifact.xoa("video" if (scope == "video" and vh) else "all", video_hash=vh)
            self._send(200, {"ok": True, "n": n})
        elif p.path == "/api/cache/set":
            # Bật/tắt cache + đổi cap (MB). Lưu settings + đẩy env cho subprocess sau.
            s = _doc_settings()
            if "cache_on" in body:
                s["cache_on"] = bool(body["cache_on"])
            if "cache_cap_mb" in body:
                try:
                    s["cache_cap_mb"] = max(50, int(body["cache_cap_mb"]))
                except (TypeError, ValueError):
                    pass
            _luu_settings(s)
            _ap_dung_cache_settings()
            self._send(200, {"ok": True})
        elif p.path == "/api/stop":
            dung_crawl()
            self._send(200, {"ok": True})
        elif p.path == "/api/goi/refresh":
            nguon = _refresh_tier()
            info = _goi_info(); info["source"] = nguon   # online/offline -> frontend báo rõ đã đồng bộ server chưa
            self._send(200, info)
        elif p.path == "/api/dub/start":
            g = _guard_expired("dub")
            if g:
                self._send(200, g); return
            if not _dub_giu_cho():   # giữ chỗ trong _dub_lock → chống race double-start/double-count
                self._send(200, {"ok": False, "msg": "Đang lồng tiếng video khác."}); return
            # PRO/UNLIMITED CHỈ khi: dùng giọng TỰ TẢI (file trong CLONE_DIR = clone giọng-của-bạn).
            # FREE: Edge + Piper(Banmai) + OmniVoice với GIỌNG MẪU SẴN (giong_mau) — user yêu cầu OmniVoice cho free.
            def _clone_up(p):   # True nếu giọng TỰ TẢI (CLONE_DIR), KHÔNG tính giọng mẫu sẵn (giong_mau)
                if not p:
                    return False
                try:
                    fp = os.path.normpath(p if os.path.isabs(p) else os.path.join(THU_MUC_GOC, p.replace("/", os.sep)))
                    return fp.startswith(CLONE_DIR)
                except Exception:
                    return False
            adv = _clone_up(body.get("voice")) or _clone_up(body.get("ref_audio"))
            if adv and not _lim("giong_nang_cao"):
                _dub_nha_cho()
                self._send(200, _block("giong", "Clone giọng TỰ TẢI (giọng của bạn) chỉ có ở gói PRO/UNLIMITED. Gói FREE dùng Edge / Banmai / OmniVoice (giọng mẫu sẵn).")); return
            ghn = _lim("dub_ngay"); ghp = _lim("dub_phut_ngay")
            phut = _thoi_luong_phut(body.get("video")) if (ghn is not None or ghp is not None) else 0
            if ghp is not None and phut <= 0:
                phut = 1   # ffprobe lỗi/vắng → fail-CLOSED (tính tối thiểu 1 phút, đừng để lọt giới hạn phút)
            # Cap CỨNG mỗi video ≤ dub_phut_ngay phút (free=1). tier ∞ (ghp None) → bỏ qua.
            if ghp is not None and phut > ghp:
                _dub_nha_cho()
                self._send(200, _block("dub_phut", f"Gói {TIER.upper()}: mỗi video lồng tiếng tối đa {ghp} phút. Video này {phut} phút — nâng cấp để lồng video dài hơn.")); return
            if ghn is not None and kdb.usage_lay("dub") >= ghn:
                _dub_nha_cho()
                self._send(200, _block("dub", f"Đã đạt giới hạn lồng tiếng {ghn} video/ngày của gói {TIER.upper()}. Nâng cấp để lồng tiếng nhiều hơn.")); return
            if ghp is not None and (kdb.usage_lay("dub_phut") + phut) > ghp:
                _dub_nha_cho()
                self._send(200, _block("dub_phut", f"Đã đạt giới hạn {ghp} phút lồng tiếng/ngày của gói {TIER.upper()}. Nâng cấp để lồng tiếng nhiều hơn.")); return
            # quota cộng SAU success (trong worker) — không trừ oan job fail. _dub_busy nhả khi worker xong/Dừng.
            chay_long_tieng(body, ghn=ghn, ghp=ghp, phut=phut)
            self._send(200, {"ok": True})
        elif p.path == "/api/dub/stop":
            dung_long_tieng()
            self._send(200, {"ok": True})
        elif p.path == "/api/cai_gpu":
            if _dub_proc is not None:
                self._send(200, {"ok": False, "msg": "Đang bận (lồng tiếng/cài)."}); return
            _chay_cai_script(os.path.join(THU_MUC_GOC, "cai_gpu.py"), "cài GPU")
            self._send(200, {"ok": True})
        elif p.path == "/api/chupsub/start":
            if _chup_proc is not None:
                self._send(200, {"ok": False, "msg": "Đang chạy chụp/sub khác."}); return
            chay_chup_sub(body)
            self._send(200, {"ok": True})
        elif p.path == "/api/chupsub/stop":
            dung_chup_sub()
            self._send(200, {"ok": True})
        elif p.path == "/api/bam/start":
            g = _guard_expired("bam") or _can("bam", "bam", "Băm nhỏ chỉ có ở gói PRO/UNLIMITED. Nâng cấp để dùng.")
            if g:
                self._send(200, g); return
            if _bam_running:
                self._send(200, {"ok": False, "msg": "Đang băm video khác."}); return
            chay_bam_nho(body)
            self._send(200, {"ok": True})
        elif p.path == "/api/bam/stop":
            dung_bam_nho()
            self._send(200, {"ok": True})
        elif p.path == "/api/bam/phan_tich":
            g = _guard_expired("bam") or _can("bam", "bam", "Băm nhỏ chỉ có ở gói PRO/UNLIMITED. Nâng cấp để dùng.")
            if g:
                self._send(200, g); return
            with _bam_pt_lock:
                dang_chay = _bam_pt["running"]
            if dang_chay:
                self._send(200, {"ok": False, "msg": "Đang phân tích video khác."}); return
            paths = _bam_video_paths(body)
            if not paths:
                self._send(200, {"ok": False, "msg": "Không tìm thấy video."}); return
            try:
                nguong = float(body.get("nguong") or 27)
            except (TypeError, ValueError):
                nguong = 27.0
            chay_phan_tich(paths[0], nguong)
            self._send(200, {"ok": True})
        elif p.path == "/api/clear_log":
            with _log_lock:
                _log_lines.clear()
            self._send(200, {"ok": True})
        elif p.path == "/api/lang_set":
            cfg = ngngu.luu_cau_hinh(app_lang=body.get("app_lang"),
                                     target_lang=body.get("target_lang"))
            self._send(200, {"ok": True, **cfg})
        elif p.path == "/api/translate":
            try:
                t = body.get("text", "")
                gian = dich_google(t, "zh-CN"); phon = dich_google(t, "zh-TW")
                _tk_luu(gian, t); _tk_luu(phon, t)   # lưu ZH(đã dịch)->VN(gốc) → filter hiện lại từ khoá tiếng Việt
                self._send(200, {"gian": gian, "phon": phon})
            except Exception as e:
                self._send(200, {"error": str(e)})
        elif p.path == "/api/translate_terms":
            terms = body.get("terms", []) or []
            self._send(200, {"map": {t: dich_term_en(t) for t in terms}})
        elif p.path == "/api/dich_tieu_de":
            self._send(200, {"map": dich_tieu_de_batch(body.get("titles", []) or [])})
        elif p.path == "/api/trang_save":
            import gom_dang_bai
            cfg = gom_dang_bai.doc_config()          # GIỮ các khóa khác (vd loha_uploads_dir)
            cfg["trang"] = body.get("trang", []) or []
            if "loha_uploads_dir" in body:
                cfg["loha_uploads_dir"] = (body.get("loha_uploads_dir") or "").strip()
            if "auto_gom" in body:
                cfg["auto_gom"] = bool(body.get("auto_gom"))
            if "auto_tai" in body:
                cfg["auto_tai"] = bool(body.get("auto_tai"))
            if "auto_tai_n" in body:
                cfg["auto_tai_n"] = max(1, int(body.get("auto_tai_n") or 1))
            if "auto_tai_gio" in body:
                cfg["auto_tai_gio"] = (body.get("auto_tai_gio") or "08:00").strip()
            gom_dang_bai.luu_config(cfg)
            self._send(200, {"ok": True})
        elif p.path == "/api/trang_gom":
            if body.get("dry"):                       # THỬ (dry-run): không copy, trả danh sách sẽ gom
                them_log("🔍 Thử (dry-run) gom — không copy file...")
                kq, lines = _chay_gom(dry_run=True)
                self._send(200, {"ok": True, "dry": True, "kq": kq, "lines": lines})
            else:
                them_log("📥 Bắt đầu gom video vào folder đăng theo trang...")
                threading.Thread(target=lambda: _chay_gom(dry_run=False), daemon=True).start()
                self._send(200, {"ok": True})
        elif p.path == "/api/ai_key":
            k = (body.get("api_key") or "").strip()
            if k:  # để trống = giữ key cũ
                save_ai_key(k)
            self._send(200, {"ok": True, "has_key": bool(load_ai_key())})
        elif p.path == "/api/ai":
            # C2: trợ lý AI chỉ ở gói UNLIMITED (free/pro/expired tro_ly_ai=False) — gate TRƯỚC khi gọi handle_ai.
            chan = _guard_expired("ai") or _can("tro_ly_ai", "ai", f"Trợ lý AI chỉ có ở gói UNLIMITED (gói hiện tại: {TIER.upper()}). Nâng cấp để dùng.")
            if chan:
                self._send(200, chan); return
            self._send(200, handle_ai(body.get("messages", []) or []))
        elif p.path == "/api/suggest":
            try:
                self._send(200, {"creators": goi_y_kenh(body.get("keyword", ""), body.get("platform", "dy"))})
            except Exception as e:
                self._send(200, {"error": str(e), "creators": []})
        elif p.path == "/api/open_folder":
            # Mở thư mục: path tuyệt đối (vd folder thể loại) HOẶC theo bộ lọc đang xem.
            tm = None
            _pth = body.get("path")
            if _pth:
                try:
                    tm = _whitelist_out(_pth)   # path tuyệt đối hợp lệ (folder thể loại user cấu hình)
                except ValueError:
                    tm = None
            if not tm:
                nguon = body.get("nguon")        # "rerender" | "goc" | None
                nt = body.get("platform")         # mã nền tảng hoặc rỗng
                if nguon == "rerender":
                    tm = PROCESSED_DIR
                elif nt and nt in NEN_TANG:
                    tm = _videos_cua(NEN_TANG[nt]["thu_muc"])
                else:
                    tm = DATA_DIR   # gốc của tất cả nền tảng
            try:
                os.makedirs(tm, exist_ok=True)
                os.startfile(tm)
            except Exception as e:
                self._send(200, {"ok": False, "msg": str(e)}); return
            self._send(200, {"ok": True, "folder": tm})
        elif p.path == "/api/localize":
            # Dịch & phụ đề (+ lồng tiếng) cho 1 video — chạy localize.py qua worker chung
            g = _guard_expired("xu_ly")
            if g:
                self._send(200, g); return
            if _proc is not None:
                self._send(200, {"ok": False, "msg": "Đang có tác vụ chạy, đợi xong đã."}); return
            full = _resolve_video(body.get("p", ""))
            if not full:
                self._send(200, {"ok": False, "msg": "Video không hợp lệ."}); return
            # HẠN MỨC LỒNG TIẾNG (chung /api/dub): Việt hóa CÓ lồng tiếng → chặn nếu quá hạn mức.
            _lt_lc = bool(body.get("long_tieng"))
            _nhan_lc, _bo_lc, _msg_lc = _dub_quota_loc([full], _lt_lc)
            if not _nhan_lc:
                self._send(200, _block("dub_phut", _msg_lc or "Đã đạt hạn mức lồng tiếng của gói.")); return
            _dub_phut_lc = _nhan_lc[0][1] if _lt_lc else 0
            _dub_out_lc = os.path.splitext(full)[0] + "_longtieng.mp4"
            lenh = [PYTHON_VENV, "localize.py", full, "--model", str(body.get("model", "medium"))]
            if not body.get("che_chu", True):
                lenh.append("--no-che")
            if body.get("long_tieng"):
                lenh.append("--long-tieng")
            if body.get("tach_nhac"):
                lenh.append("--tach-nhac")
            if body.get("goc_vol") is not None:
                lenh += ["--goc-vol", str(body.get("goc_vol"))]   # âm lượng gốc 0-1 (0 = tắt hẳn)
            # Net an toàn: tts gộp "piper:ngochuyen" → tách engine + giọng
            _tts2 = body.get("tts") or ""
            if ":" in _tts2:
                _e2, _v2 = _tts2.split(":", 1)
                body["tts"] = _e2
                if not body.get("voice"):
                    body["voice"] = _v2
            if body.get("voice"):
                lenh += ["--voice", str(body.get("voice"))]
            try:
                _ra = _whitelist_ref(body.get("ref_audio"))
            except ValueError:
                self._send(200, {"ok": False, "msg": "Giọng mẫu không hợp lệ."}); return
            if _ra:
                lenh.append("--ref-audio=" + _ra)
            lenh += ["--tts", str(body.get("tts") or "edge")]
            them_log("🌐 Bắt đầu Việt hóa: " + os.path.basename(full))
            threading.Thread(target=_crawl_worker, args=(lenh, os.environ.copy(), THU_MUC_GOC),
                             kwargs={"dub_phut": _dub_phut_lc, "dub_out": _dub_out_lc},
                             daemon=True).start()
            self._send(200, {"ok": True})
        elif p.path == "/api/workflow_run":
            g = _guard_expired("workflow") or _can("workflow", "workflow", "Quy trình tự động chỉ có ở gói PRO/UNLIMITED. Nâng cấp để dùng.")
            if g:
                self._send(200, g); return
            if _wf["running"]:
                self._send(200, {"ok": False, "msg": "Quy trình đang chạy."}); return
            blocks = body.get("blocks") or []
            ropts = body.get("render_opts") or {}
            if not blocks:
                self._send(200, {"ok": False, "msg": "Chưa có bước nào."}); return
            try:
                _whitelist_out(ropts.get("out_dir")); _whitelist_ref(ropts.get("ref_audio"))
            except ValueError:
                self._send(200, {"ok": False, "msg": "Cấu hình render không hợp lệ."}); return
            with _wf_lock:
                _wf.update({"running": True, "blocks": {}, "summary": "", "error": "", "stop": False})
            threading.Thread(target=_wf_chay, args=(blocks, ropts), daemon=True).start()
            self._send(200, {"ok": True})
        elif p.path == "/api/workflow_stop":
            with _wf_lock:
                _wf["stop"] = True
            self._send(200, {"ok": True})
        elif p.path == "/api/workflow_auto_on":
            g = _guard_expired("workflow") or _can("workflow", "workflow", "Quy trình tự động chỉ có ở gói PRO/UNLIMITED. Nâng cấp để dùng.")
            if g:
                self._send(200, g); return
            blocks = body.get("blocks") or []
            ropts = body.get("render_opts") or {}
            try:
                iv = max(1, int(body.get("interval") or 10))
            except (TypeError, ValueError):
                iv = 10
            try:
                maxml = max(0, int(body.get("max_moi_lan") or 0))
            except (TypeError, ValueError):
                maxml = 0
            if not blocks:
                self._send(200, {"ok": False, "msg": "Chưa có bước xử lý nào."}); return
            try:
                _whitelist_out(ropts.get("out_dir")); _whitelist_ref(ropts.get("ref_audio"))
            except ValueError:
                self._send(200, {"ok": False, "msg": "Cấu hình render không hợp lệ."}); return
            with _wfauto_lock:
                _wfauto.update({"on": True, "blocks": blocks, "render_opts": ropts, "interval": iv, "last": 0.0, "max_moi_lan": maxml})
            try:
                luu_json(FILE_WFAUTO, {"on": True, "blocks": blocks, "render_opts": ropts, "interval": iv, "max_moi_lan": maxml})
            except Exception:
                pass
            _khoi_dong_wfauto()   # đảm bảo worker chạy (idempotent)
            them_log("🔁 BẬT tự động chạy quy trình — mỗi %d phút xử lý video mới." % iv)
            self._send(200, {"ok": True})
        elif p.path == "/api/workflow_auto_off":
            with _wfauto_lock:
                _wfauto["on"] = False
            try:
                d = doc_json(FILE_WFAUTO, {}); d["on"] = False; luu_json(FILE_WFAUTO, d)
            except Exception:
                pass
            self._send(200, {"ok": True})
        elif p.path in ("/api/xu_ly", "/api/xu_ly_batch", "/api/queue_add"):
            # Thêm video vào HÀNG ĐỢI render (1 video qua "p", nhiều video qua "paths")
            g = _guard_expired("xu_ly")
            if g:
                self._send(200, g); return
            o = body.get("opts", {}) or {}
            try:
                _whitelist_out(o.get("out_dir")); _whitelist_ref(o.get("ref_audio"))
            except ValueError:
                self._send(200, {"ok": False, "msg": "Thư mục lưu hoặc giọng mẫu không hợp lệ."}); return
            paths = body.get("paths") or ([body.get("p")] if body.get("p") else [])
            paths = [x for x in (_resolve_video(x) for x in paths) if x]
            if not paths:
                self._send(200, {"ok": False, "msg": "Chưa chọn video hợp lệ."}); return
            # HẠN MỨC LỒNG TIẾNG (chung /api/dub): tick "Lồng tiếng" → lọc theo quota, chặn phần vượt.
            _nhan, _bo, _msg_lt = _dub_quota_loc(paths, bool(o.get("long_tieng")))
            if not _nhan:
                self._send(200, _block("dub_phut", _msg_lt or "Đã đạt hạn mức lồng tiếng của gói.")); return
            _phut_map = dict(_nhan)          # full → phút (0 nếu không lồng tiếng / tier ∞)
            paths = [p for p, _ in _nhan]
            _pl_on = bool(_doc_settings().get("phan_loai_on"))
            _out_gui = (o.get("out_dir") or "").strip()   # user tự chọn "Thư mục lưu" → tôn trọng, không ghi đè
            if _out_gui:
                _them_out_dir(_out_gui)   # nhớ thư mục này để File đã tải hiện + /video phục vụ video render ra đó
            # RENDER ĐA NGÔN NGỮ: tick nhiều ngôn ngữ đích → mỗi (video × ngôn ngữ) = 1 job (lang riêng, tên output
            # gắn mã ngôn ngữ khỏi đè). Trống = giữ hành vi cũ (1 job/video theo đích global).
            _langs = []
            for _l in (body.get("langs") or []):
                _c = ngngu._chuan(_l)
                if _c and _c not in _langs:
                    _langs.append(_c)
            _langs = _langs[:20]          # chặn lạm dụng (tối đa 20 ngôn ngữ/lần)
            # GIỌNG RIÊNG mỗi ngôn ngữ: {lang:{tts,voice}} từ UI → job của lang đó dùng đúng engine+giọng đã chọn.
            _lang_voices = {}
            _lv_in = body.get("lang_voices") or {}
            if isinstance(_lv_in, dict):
                for _lk, _lvv in _lv_in.items():
                    _ck = ngngu._chuan(_lk)
                    if _ck and isinstance(_lvv, dict):
                        _lang_voices[_ck] = {"tts": str(_lvv.get("tts") or "").strip(),
                                             "voice": str(_lvv.get("voice") or "").strip()}
            for full in paths:
                o2 = dict(o)
                if o.get("long_tieng") and _phut_map.get(full):
                    o2["_dub_phut"] = _phut_map[full]   # marker: đếm quota SAU khi render xong (trong _queue_worker)
                if _pl_on:
                    # TỰ PHÂN LOẠI: KHÔNG đoán thể loại TRƯỚC render (Gemini chậm → render tưởng treo). Vào hàng
                    # đợi NGAY; SAU khi render xong, thread nền đọc .vi.srt vừa dịch để đoán thể loại + MOVE
                    # output vào folder thể loại. Cờ phan_loai_sau chỉ là marker cho worker (KHÔNG vào _lenh_xu_ly).
                    o2["phan_loai_sau"] = True
                elif not _out_gui:
                    # MẶC ĐỊNH (tắt phân loại + user không chọn thư mục): gom render về processed_videos/<nền tảng>/
                    # thay vì cạnh video gốc → output gọn 1 chỗ, tách khỏi video gốc.
                    _nt = _nen_tang_seg_tu_path(full)
                    o2["out_dir"] = os.path.join(PROCESSED_DIR, _nt or "khac")
                if _langs:
                    for _lg in _langs:
                        o3 = dict(o2); o3["lang"] = _lg   # đích riêng cho job này → worker/subprocess set TARGET_LANG
                        _lv = _lang_voices.get(_lg)       # giọng riêng ngôn ngữ này (nếu UI gửi)
                        if _lv:
                            if _lv.get("tts"):
                                o3["tts"] = _lv["tts"]
                            if _lv.get("voice"):
                                o3["voice"] = _lv["voice"]
                        elif not (o3.get("tts") or "").strip():
                            # KHÔNG chỉ định giọng (API/UI cũ) → mặc định SUPERTONIC-FIRST (offline, giọng đã chọn
                            # cho sản phẩm); edge CHỈ khi ngôn ngữ đó Supertonic không đọc chuẩn (supertonic=False
                            # trong ngon_ngu.LANGS — vd th/ru/id). Trước rơi thẳng edge → sai giọng mặc định.
                            o3["tts"] = "supertonic" if (ngngu.LANGS.get(_lg) or {}).get("supertonic") else "edge"
                        _queue_them(full, o3)
                else:
                    _queue_them(full, o2)
            _so = len(paths) * (len(_langs) or 1)   # tổng job đã thêm (video × ngôn ngữ)
            them_log("➕ Đã thêm %d job render.%s%s%s"
                     % (_so, (" (%d video × %d ngôn ngữ)" % (len(paths), len(_langs))) if _langs else "",
                        " (tự phân loại SAU khi render)" if _pl_on
                        else ("" if _out_gui else " → processed_videos/"),
                        (" ⚠ Bỏ %d video vượt hạn mức lồng tiếng." % _bo) if _bo else ""))
            self._send(200, {"ok": True, "so": _so, "bo_qua_dub": _bo, "langs": len(_langs),
                             "limit": bool(_bo), "msg": _msg_lt if _bo else ""})   # limit=true → banner tự hiện
        elif p.path == "/api/glossary_save":
            # CẢI THIỆN DỊCH: lưu từ điển/quy tắc người dùng → translation_memory/00_user.md (Gemini tự nạp)
            content = body.get("content") or ""
            try:
                d = os.path.join(THU_MUC_GOC, "translation_memory")
                os.makedirs(d, exist_ok=True)
                with open(os.path.join(d, "00_user.md"), "w", encoding="utf-8") as f:
                    f.write(content)
                self._send(200, {"ok": True})
            except OSError as e:
                self._send(200, {"ok": False, "msg": "Lưu lỗi: " + str(e)[:80]})
        elif p.path == "/api/quy_tac_rieng":
            # Lưu QUY TẮC RIÊNG vào settings (BỀN qua tắt/reset, KHÔNG xoá khi bỏ tick)
            try:
                s = _doc_settings()
                s["quy_tac_rieng"] = body.get("content") or ""
                _luu_settings(s)
                self._send(200, {"ok": True})
            except Exception as e:
                self._send(200, {"ok": False, "msg": "Lưu lỗi: " + str(e)[:80]})
        elif p.path == "/api/upload_logo":
            # Lưu ảnh logo người dùng (data URL base64) -> trả đường dẫn tuyệt đối để chèn khi render
            data = body.get("data") or ""
            ten = (body.get("name") or "logo.png")
            try:
                if "," in data:
                    data = data.split(",", 1)[1]
                raw = base64.b64decode(data)
                if not raw or len(raw) > 8 * 1024 * 1024:
                    self._send(200, {"ok": False, "msg": "Ảnh trống hoặc quá lớn (>8MB)."}); return
                ext = os.path.splitext(ten)[1].lower()
                if ext not in (".png", ".jpg", ".jpeg", ".webp"):
                    ext = ".png"
                d = LOGOS_DIR
                os.makedirs(d, exist_ok=True)
                import hashlib as _hl
                fn = _hl.md5(raw).hexdigest()[:16] + ext
                full = os.path.join(d, fn)
                if not os.path.isfile(full):
                    with open(full, "wb") as f:
                        f.write(raw)
                self._send(200, {"ok": True, "path": full})
            except Exception:
                import traceback; traceback.print_exc()
                self._send(200, {"ok": False, "msg": "Lỗi lưu logo."})
        elif p.path == "/api/list_logos":
            # Liệt kê ảnh logo/watermark đã tải (user_logos/) -> đổ vào spinner chọn nhanh.
            try:
                d = LOGOS_DIR
                files = sorted([f for f in os.listdir(d)
                                if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))]) \
                    if os.path.isdir(d) else []
            except Exception:
                files = []
            self._send(200, {"ok": True, "files": files})
        elif p.path == "/api/preview5s":
            # Preview NHANH ~5s: cắt 5s + hiệu ứng HÌNH (blur che chữ + sub placeholder + logo + watermark),
            # KHÔNG ASR/dịch/TTS → nhanh, cho user xem BỐ CỤC trước khi render full.
            try:
                vid = _resolve_video((body.get("path") or "").strip())
                if not vid or not os.path.isfile(vid):
                    self._send(200, {"ok": False, "msg": "Không thấy video để preview."}); return
                pvdir = PREVIEW_DIR
                os.makedirs(pvdir, exist_ok=True)
                op = os.path.join(pvdir, "opts.json")
                with open(op, "w", encoding="utf-8") as f:
                    json.dump(body.get("opts") or {}, f, ensure_ascii=False)
                out = os.path.join(pvdir, "preview.mp4")
                try:
                    if os.path.isfile(out):
                        os.remove(out)
                except OSError:
                    pass
                r = subprocess.run([PYTHON_VENV, "preview_5s.py", vid, op, out],
                                   cwd=THU_MUC_GOC, env=os.environ.copy(), capture_output=True,
                                   text=True, encoding="utf-8", errors="replace",
                                   timeout=180, creationflags=_NO_WINDOW)
                if not os.path.isfile(out):
                    self._send(200, {"ok": False, "msg": "Preview lỗi: " + ((r.stderr or r.stdout or "")[-200:])}); return
                _bam_serve_files.add(os.path.normcase(os.path.abspath(out)))
                self._send(200, {"ok": True, "url": "/video?p=_preview/preview.mp4&t=" + str(int(os.path.getmtime(out)))})
            except subprocess.TimeoutExpired:
                self._send(200, {"ok": False, "msg": "Preview quá lâu (máy đang tải nặng) — thử lại."})
            except Exception as e:
                self._send(200, {"ok": False, "msg": str(e)[:200]})
        elif p.path == "/api/queue_clear":
            # Xóa các video CHỜ + ĐÃ XONG/LỖI khỏi hàng đợi (giữ video đang chạy)
            with _queue_lock:
                _queue[:] = [it for it in _queue if it["trang_thai"] == "dang"]
            _queue_luu()
            self._send(200, {"ok": True})
        elif p.path == "/api/queue_cancel":
            # Hủy/xóa 1 video theo id. Nếu video ĐANG xử lý (kể cả treo) thì kill cả
            # cây tiến trình render để mở khóa hàng đợi cho video kế tiếp.
            qid = body.get("id")
            target = None
            dang_cancel = False
            _lane_idx = None
            with _queue_lock:
                target = next((it for it in _queue if it["id"] == qid), None)
                if target is not None:
                    if target["trang_thai"] == "dang":
                        target["cancel"] = True       # worker/subprocess-loop đọc cờ → trả 'cancelled' (dừng job này)
                        _lane_idx = target.get("_lane")   # lane đang chạy job này (scheduler đa-lane); None = 1-lane
                        dang_cancel = True
                    _queue[:] = [it for it in _queue if it["id"] != qid]
            killed = False
            if dang_cancel:
                # Worker-mode: kill worker của ĐÚNG lane chứa job (né kill nhầm video lane kia). 1-lane → lane 0.
                _rw_kill(_LANES[_lane_idx] if isinstance(_lane_idx, int) and 0 <= _lane_idx < len(_LANES) else None)
                killed = True
                them_log(f"⏹ Đã hủy video đang xử lý: {target['ten']}")
            elif target is not None:
                them_log(f"🗑 Đã xóa khỏi hàng đợi: {target['ten']}")
            _queue_luu()
            self._send(200, {"ok": True, "killed": killed})
        elif p.path == "/api/srt_import":
            # DỊCH THỦ CÔNG: nhận SRT đã dịch (text) → lưu cạnh video (.vi.srt) → cho render tiếp pha 2.
            qid = body.get("id")
            content = (body.get("content") or "").strip()
            with _queue_lock:
                it = next((x for x in _queue if x["id"] == qid), None)
                if it is None:
                    self._send(200, {"ok": False, "error": "Không thấy video trong hàng đợi."}); return
                if not content:
                    self._send(200, {"ok": False, "error": "Nội dung SRT rỗng."}); return
                vi_path = os.path.splitext(it["path"])[0] + ".vi.srt"
                try:
                    with open(vi_path, "w", encoding="utf-8") as f:
                        f.write(content)
                except OSError as e:
                    self._send(200, {"ok": False, "error": "Lưu SRT lỗi: " + str(e)[:80]}); return
                it["opts"]["srt_da_dich"] = vi_path
                it["pha_xong_asr"] = True
                it["trang_thai"] = "cho"      # → worker nhặt lại render pha 2 (dub + ghép theo SRT đã dịch)
                it["msg"] = "Đã nhận SRT → chờ render"
                it["pct"] = 55
            them_log(f"📥 Nhận SRT đã dịch → render tiếp: {it['ten']}")
            self._send(200, {"ok": True})
        elif p.path == "/api/auto_on":
            g = _guard_expired("xu_ly")
            if g:
                self._send(200, g); return
            o = body.get("opts", {}) or {}
            unlimited = bool(body.get("unlimited"))
            try:
                count = int(body.get("count") or 0)
            except (TypeError, ValueError):
                count = 0
            if not unlimited and count < 1:
                self._send(200, {"ok": False, "msg": "Nhập số video > 0 hoặc chọn Không giới hạn."}); return
            with _auto_lock:
                _auto.update({"on": True, "unlimited": unlimited, "count": count, "opts": o, "da_them": 0})
            _auto_seen.clear()
            _luu_auto()
            them_log("🤖 BẬT tự động render — " + ("không giới hạn." if unlimited else f"{count} video."))
            self._send(200, {"ok": True})
        elif p.path == "/api/auto_off":
            with _auto_lock:
                _auto["on"] = False
            _luu_auto()
            them_log("⏹ TẮT tự động render.")
            self._send(200, {"ok": True})
        elif p.path == "/api/upload_ref":
            ghc = _lim("clone_tong")
            if ghc is not None:
                if ghc <= 0:
                    self._send(200, _block("clone", "Gói FREE không có tính năng clone giọng. Nâng cấp lên PRO/UNLIMITED.")); return
                if kdb.usage_lay("clone", theo_ngay=False) >= ghc:
                    self._send(200, _block("clone", f"Đã dùng hết {ghc} lượt clone giọng của gói {TIER.upper()} (clone xong xoá vẫn tính). Nâng cấp UNLIMITED để clone không giới hạn.")); return
            # Nhận file giọng mẫu (base64) → convert sang wav mono 24k → giong_mau/upload/
            ten = (body.get("ten") or "giong").strip()
            data = body.get("data") or ""
            if data.startswith("data:") and "," in data:
                data = data.split(",", 1)[1]
            try:
                raw = base64.b64decode(data)
            except Exception:
                self._send(200, {"ok": False, "msg": "File không hợp lệ."}); return
            if not raw:
                self._send(200, {"ok": False, "msg": "File rỗng."}); return
            os.makedirs(CLONE_DIR, exist_ok=True)
            safe = "".join(c for c in os.path.splitext(ten)[0] if c.isalnum() or c in " _-").strip() or "giong"
            tmp_in = os.path.join(CLONE_DIR, "_tmp_" + safe)
            out_wav = os.path.join(CLONE_DIR, safe + ".wav")
            with open(tmp_in, "wb") as f:
                f.write(raw)
            # CẮT giọng mẫu về ~12s (bỏ lặng đầu, lấy đoạn nói liền) NẾU quá dài + chuẩn hoá mono 24k.
            # Mẫu clone QUÁ DÀI làm clone chậm + chất lượng kém — giữ ~5–15s là tốt nhất.
            _dur_goc = 0.0
            ok_conv = False
            try:
                import cat_giong_clone
                _dur_goc = cat_giong_clone.thoi_luong(tmp_in)
                ok_conv = cat_giong_clone.cat(tmp_in, out_wav, target=12.0, maxs=15.0)
            except Exception:
                ok_conv = False
            if not ok_conv:   # fallback: convert thẳng (không cắt) nếu script lỗi
                ff = shutil.which("ffmpeg") or "ffmpeg"
                kq = subprocess.run([ff, "-y", "-i", tmp_in, "-ac", "1", "-ar", "24000", out_wav],
                                    capture_output=True, creationflags=_NO_WINDOW)
                ok_conv = (kq.returncode == 0 and os.path.isfile(out_wav))
            try:
                os.remove(tmp_in)
            except OSError:
                pass
            if not ok_conv or not os.path.isfile(out_wav):
                self._send(200, {"ok": False, "msg": "Không đọc được file âm thanh (thử wav/mp3)."}); return
            # dọn cache transcript/marker CŨ cùng tên (re-upload khác nội dung → khỏi dùng nhầm lời file cũ;
            # cache THẬT theo HASH ở localize._ref_text_tu_audio nên không stale — đây chỉ dọn cache-tên cũ + .used).
            for _c in (os.path.splitext(out_wav)[0] + ".txt", os.path.splitext(out_wav)[0] + ".used"):
                try:
                    if os.path.isfile(_c):
                        os.remove(_c)
                except OSError:
                    pass
            rel = os.path.abspath(out_wav).replace("\\", "/")   # CLONE_DIR ở userData → path tuyệt đối
            # KHÔNG trừ quota clone lúc upload — chỉ trừ khi DÙNG lần đầu (_dem_clone_lan_dau) để khách upload
            # nhầm rồi xoá thì KHÔNG mất lượt.
            _dur_out = 0.0
            try:
                import cat_giong_clone
                _dur_out = cat_giong_clone.thoi_luong(out_wav)
            except Exception:
                pass
            _da_cat = bool(_dur_goc > 15.5 and _dur_out and _dur_out < _dur_goc - 1)
            them_log("🎤 Đã thêm giọng mẫu: " + safe + (
                " (cắt %.0fs → %.0fs cho clone tốt hơn)" % (_dur_goc, _dur_out) if _da_cat else ""))
            self._send(200, {"ok": True, "ten": safe, "path": rel,
                             "giay": round(_dur_out, 1), "cat": _da_cat})
        elif p.path == "/api/giong_del":
            rel = (body.get("path") or "").replace("/", os.sep)
            full = os.path.normpath(os.path.join(THU_MUC_GOC, rel))
            if _trong_vung(full, CLONE_DIR) and os.path.isfile(full):   # commonpath, chống prefix-collision (xoá file)
                try:
                    try:   # dọn cache transcript THEO HASH nội dung (tính trước khi xoá file)
                        import hashlib
                        _h = hashlib.sha1(open(full, "rb").read()).hexdigest()[:16]
                        _hc = os.path.join(os.path.dirname(full), "_voicecache_" + _h + ".txt")
                        if os.path.isfile(_hc):
                            os.remove(_hc)
                    except Exception:
                        pass
                    os.remove(full)
                    for _c in (os.path.splitext(full)[0] + ".txt", os.path.splitext(full)[0] + ".used"):
                        if os.path.isfile(_c):
                            os.remove(_c)
                    them_log("🗑 Đã xóa giọng mẫu.")
                    self._send(200, {"ok": True}); return
                except OSError as e:
                    self._send(200, {"ok": False, "msg": str(e)}); return
            self._send(200, {"ok": False, "msg": "Chỉ xóa được giọng đã tải lên."})
        elif p.path == "/api/giong_rename":
            # Đổi tên giọng CLONE do khách tự tải (trong CLONE_DIR). Giọng mẫu built-in (giong_mau/) KHÔNG đổi.
            rel = (body.get("path") or "").replace("/", os.sep)
            full = os.path.normpath(os.path.join(THU_MUC_GOC, rel))
            if not (full.startswith(CLONE_DIR) and os.path.isfile(full)):
                self._send(200, {"ok": False, "msg": "Chỉ đổi tên được giọng bạn tự tải."}); return
            ten = os.path.basename((body.get("ten") or "").strip())
            ten = _re.sub(r'[\\/:*?"<>|]', "", ten).strip().strip(".")[:80]
            if not ten:
                self._send(200, {"ok": False, "msg": "Tên không hợp lệ."}); return
            ext = os.path.splitext(full)[1]
            if not ten.lower().endswith(ext.lower()):
                ten += ext
            new = os.path.join(CLONE_DIR, ten)
            if os.path.abspath(new) == os.path.abspath(full):
                self._send(200, {"ok": True, "path": os.path.abspath(new).replace("\\", "/"),
                                 "ten": os.path.splitext(ten)[0]}); return
            if os.path.exists(new):
                self._send(200, {"ok": False, "msg": "Tên đã tồn tại, chọn tên khác."}); return
            try:
                os.replace(full, new)
                for _suf in (".txt", ".used"):   # dời sidecar transcript/đánh-dấu theo TÊN (cache hash giữ nguyên)
                    _o = os.path.splitext(full)[0] + _suf
                    if os.path.isfile(_o):
                        try:
                            os.replace(_o, os.path.splitext(new)[0] + _suf)
                        except OSError:
                            pass
                them_log("✏ Đã đổi tên giọng mẫu: " + os.path.splitext(ten)[0])
                self._send(200, {"ok": True, "path": os.path.abspath(new).replace("\\", "/"),
                                 "ten": os.path.splitext(ten)[0]}); return
            except OSError as e:
                self._send(200, {"ok": False, "msg": str(e)}); return
        # ---- AI keys ----
        elif p.path == "/api/aikey_add":
            import ai_dich
            self._send(200, ai_dich.them_key(body.get("provider", ""), body.get("key", "")))
        elif p.path == "/api/aikey_del":
            import ai_dich
            self._send(200, ai_dich.xoa_key(body.get("id", "")))
        elif p.path == "/api/aikey_check":
            import ai_dich
            self._send(200, ai_dich.kiem_tra_id(body.get("id", "")))
        elif p.path == "/api/aikey_checkall":
            import ai_dich
            self._send(200, ai_dich.kiem_tra_tat_ca())
        elif p.path == "/api/aikey_auto":
            # 1 Ô CHUNG: dán 1+ key bất kỳ → tự phát hiện provider (gemini/groq/ollama) + kiểm tra hạn mức
            import ai_dich
            self._send(200, ai_dich.them_tu_dong(body.get("text") or body.get("key") or ""))
        elif p.path == "/api/aikey_toggle":
            import ai_dich
            self._send(200, ai_dich.bat_tat_key(body.get("id", ""), body.get("bat", True)))
        elif p.path == "/api/aikey_label":
            import ai_dich
            self._send(200, ai_dich.sua_nhan(body.get("id", ""), body.get("nhan", "")))
        elif p.path == "/api/aikey_them_dung":
            import ai_dich
            k = body.get("key", "")
            if "\n" in k or "," in k:          # dán nhiều key (mỗi dòng/phẩy 1 key) → thêm hàng loạt
                self._send(200, ai_dich.them_nhieu_key(body.get("provider", ""), k))
            else:
                self._send(200, ai_dich.them_va_dung(body.get("provider", ""), k))
        elif p.path == "/api/ai_cauhinh_set":
            import ai_dich
            self._send(200, ai_dich.luu_cau_hinh(body.get("provider", "gemini"), body.get("model", "")))
        elif p.path == "/api/file_del":
            # Xóa 1 file video (chỉ trong thư mục video cho phép)
            full = _resolve_video(body.get("p", ""))
            if not full:
                self._send(200, {"ok": False, "msg": "Đường dẫn không hợp lệ hoặc file không tồn tại."}); return
            try:
                os.remove(full)
                them_log("🗑️ Đã xóa: " + os.path.basename(full))
                self._send(200, {"ok": True})
            except Exception as e:
                self._send(200, {"ok": False, "msg": str(e)})
        elif p.path == "/api/file_rename":
            # Đổi tên 1 video ĐÃ RENDER (chỉ trong thư mục video cho phép) — kèm đổi tên sidecar (.vi.srt/.zh.srt/.txt)
            # cùng gốc để khớp cặp. KHÔNG đụng bản gốc/data cào (chỉ file người dùng trỏ tới qua _resolve_video).
            full = _resolve_video(body.get("p", ""))
            if not full:
                self._send(200, {"ok": False, "msg": "Đường dẫn không hợp lệ hoặc file không tồn tại."}); return
            ok, msg_hoac_p, name = _doi_ten_video(full, body.get("ten") or "")
            if ok:
                them_log(f"✏️ Đổi tên: {os.path.basename(full)} → {name}")
                self._send(200, {"ok": True, "p": msg_hoac_p, "name": name})
            else:
                self._send(200, {"ok": False, "msg": msg_hoac_p})
        elif p.path == "/api/file_rename_batch":
            # Đặt tên HÀNG LOẠT (vd 1 series/danh sách phim) — items=[{p,ten}] theo thứ tự client đã đánh số
            # sẵn (vd "<tên gốc> Tập 1"…"Tập N"). Đổi lần lượt, KHÔNG dừng giữa chừng nếu 1 video lỗi.
            items = body.get("items") or []
            ok_n = 0
            loi = []
            for it in items:
                full = _resolve_video(it.get("p", ""))
                if not full:
                    loi.append((it.get("ten") or "?") + ": đường dẫn không hợp lệ"); continue
                ok, msg_hoac_p, name = _doi_ten_video(full, it.get("ten") or "")
                if ok:
                    ok_n += 1
                else:
                    loi.append(os.path.basename(full) + ": " + msg_hoac_p)
            them_log(f"🔢 Đặt tên hàng loạt: {ok_n}/{len(items)} video.")
            self._send(200, {"ok": True, "n": ok_n, "loi": loi})
        elif p.path == "/api/file_ghep":
            # Ghép NHIỀU video (đã chọn, ĐÚNG thứ tự) → chia nhóm `nhom` video/tập → mỗi nhóm ghép thành 1 tập
            # dài (nền, tuần tự). paths validate qua _resolve_video (whitelist); tên qua _pl_safe_ten.
            paths_in = body.get("paths") or []
            full_paths = []
            for pp in paths_in:
                full = _resolve_video(pp)
                if not full:
                    self._send(200, {"ok": False, "msg": "Video không hợp lệ: " + str(pp)[:80]}); return
                full_paths.append(full)
            if len(full_paths) < 2:
                self._send(200, {"ok": False, "msg": "Chọn ít nhất 2 video để ghép."}); return
            ten_goc = _pl_safe_ten(body.get("ten") or "")
            if not ten_goc:
                self._send(200, {"ok": False, "msg": "Tên không hợp lệ."}); return
            try:
                nhom = max(1, min(len(full_paths), int(body.get("nhom") or len(full_paths))))
            except (TypeError, ValueError):
                nhom = len(full_paths)
            threading.Thread(target=_ghep_video_batch_worker, args=(full_paths, nhom, ten_goc), daemon=True).start()
            so_tap = (len(full_paths) + nhom - 1) // nhom
            self._send(200, {"ok": True, "msg": f"Đang ghép nền → {so_tap} tập ({nhom} video/tập). Xem nhật ký."})
        elif p.path == "/api/phan_loai":
            # Cấu hình ĐƠN GIẢN: khách CHỈ gõ TÊN thể loại (body.names); hệ tự tạo folder con <base>/<tên>
            # (base = processed_videos/phân loại). Thể loại AI không có sẵn → folder mới cũng dưới base.
            # Backward-compat: client cũ gửi 'muc' (name+path tự do) vẫn nhận.
            base = _pl_base()
            muc, seen = [], set()
            src = body.get("muc")
            if isinstance(src, list):
                for m in src:
                    if not isinstance(m, dict):
                        continue
                    ten = _pl_safe_ten(m.get("ten") or "")
                    if not ten or ten.lower() in seen:
                        continue
                    seen.add(ten.lower())
                    dich = m.get("dich")
                    if _can_lohapage() and isinstance(dich, dict) and dich.get("kieu") in ("page", "group"):
                        # thể loại gán ĐÍCH LohaPage → LƯU dich (path resolve động khi đọc, theo loha_dir hiện thời)
                        muc.append({"ten": ten, "dich": {
                            "kieu": dich.get("kieu"),
                            "page_ten": (dich.get("page_ten") or "").strip()[:80],
                            "page_id": (dich.get("page_id") or "").strip()[:40],
                            "group_slug": (dich.get("group_slug") or "").strip()[:60],
                            "hashtag": (dich.get("hashtag") or "").strip()[:120]}})
                    else:                                 # folder thường (path tự do backward-compat, hoặc base/ten)
                        try:
                            _p = _whitelist_out(str(m.get("path") or "").strip()) if m.get("path") else ""
                        except ValueError:
                            _p = ""
                        muc.append({"ten": ten, "path": _p or os.path.join(base, ten)})
            elif isinstance(body.get("names"), list):     # client CŨ: chỉ gõ tên
                for n in body["names"]:
                    ten = _pl_safe_ten(n)
                    if ten and ten.lower() not in seen:
                        muc.append({"ten": ten, "path": os.path.join(base, ten)}); seen.add(ten.lower())
            s = _doc_settings()
            s["phan_loai_on"] = bool(body.get("on"))
            s["phan_loai_muc"] = muc
            s["phan_loai_default_path"] = base if muc else ""   # base = nơi chứa thể loại + folder MỚI của AI
            for _k in ("phan_loai_base", "phan_loai_names", "phan_loai_default_name"):
                s.pop(_k, None)   # dọn config CŨ để _pl_folders ưu tiên muc
            _luu_settings(s)
            _rmuc, _ = _pl_folders(s)                    # resolve (dich→folder LohaPage) cho makedirs + response
            if s["phan_loai_on"]:                        # tạo sẵn base + folder thể loại để khách thấy ngay
                for _d in [base] + [m["path"] for m in _rmuc]:
                    try:
                        os.makedirs(_d, exist_ok=True)
                    except OSError:
                        pass
            self._send(200, {"ok": True, "on": s["phan_loai_on"], "muc": _rmuc,
                             "default_path": s["phan_loai_default_path"], "base": base,
                             "names": [m["ten"] for m in _rmuc]})
        elif p.path == "/api/phan_loai_move":
            # Chuyển TAY 1 video render sang folder thể loại khác (sửa khi AI đoán sai). the_loai = nhãn
            # trong cấu hình HOẶC "__default__" (folder mặc định). Move file + đăng ký out_dir để vẫn hiện.
            full = _resolve_video(body.get("p", ""))
            if not full:
                self._send(200, {"ok": False, "msg": "Video không hợp lệ."}); return
            muc, default = _pl_folders()
            tl = str(body.get("the_loai") or "").strip()
            if tl == "__default__":
                dest = default
            else:
                ctl = _pl_safe_ten(tl).lower()
                dest = next((m["path"] for m in muc if m["ten"].lower() == ctl), "")
            if not dest:
                self._send(200, {"ok": False, "msg": "Thể loại không tồn tại hoặc chưa có folder mặc định."}); return
            try:
                dest = _whitelist_out(dest)
                os.makedirs(dest, exist_ok=True)
                target = os.path.join(dest, os.path.basename(full))
                if os.path.abspath(target) != os.path.abspath(full):
                    if os.path.exists(target):
                        os.remove(target)   # ghi đè bản cũ cùng tên (chuyển lại lần 2)
                    shutil.move(full, target)
                _them_out_dir(dest)
                them_log("🗂️ Chuyển thể loại (tay) → %s" % dest)
                self._send(200, {"ok": True, "path": target})
            except Exception as e:
                self._send(200, {"ok": False, "msg": str(e)})
        elif p.path == "/api/out_dirs":
            # File đã tải: user TỰ ĐẶT thư mục đích để quét (xem video render ra thư mục riêng). add/del.
            act = (body.get("action") or "add").strip()
            path = (body.get("path") or "").strip()
            if act == "del":
                _xoa_out_dir(path)
            elif path:
                if path.startswith("-") or not os.path.isabs(path):
                    self._send(200, {"ok": False, "msg": "Đường dẫn không hợp lệ."}); return
                _them_out_dir(path)
            self._send(200, {"ok": True, "dirs": sorted(_OUT_DIRS)})
        elif p.path == "/api/them_video":
            # Cho user THÊM video CỦA HỌ (ngoài data đã cào) để render: mở hộp thoại chọn FILE (native,
            # tiến trình con) → đăng ký vào _bam_serve_files (để /video,/thumb,_resolve_video phục vụ
            # file ngoài DATA_DIR) → trả danh sách cho lưới Render. App chạy LOCAL nên KHÔNG upload (file nặng).
            try:
                kq = subprocess.run([PYTHON_VENV, "chon_thu_muc.py", "--files"],
                                    cwd=THU_MUC_GOC, capture_output=True, text=True, encoding="utf-8",
                                    errors="replace", creationflags=_NO_WINDOW, timeout=300)
                vids = []
                for line in (kq.stdout or "").splitlines():
                    if not line.startswith("PICKED:"):
                        continue
                    fp = line[len("PICKED:"):].strip()
                    if not fp or not os.path.isfile(fp) or not _bam_la_video(fp):
                        continue
                    ap = os.path.abspath(fp)
                    with _bam_lock:
                        _bam_serve_files.add(os.path.normcase(ap))   # cho phép phục vụ + resolve file ngoài
                    try:
                        mb = round(os.path.getsize(ap) / 1048576, 1)
                    except OSError:
                        mb = 0
                    vids.append({"name": os.path.basename(ap), "p": ap.replace("\\", "/"), "mb": mb,
                                 "nen_tang": "Video của tôi", "nen_tang_ma": "toi",
                                 "loai": "", "nhom_ten": "", "ten_vi": "", "nguon": "goc"})
                self._send(200, {"ok": True, "videos": vids})
            except Exception as e:
                self._send(200, {"ok": False, "msg": str(e)[:160]})
        elif p.path == "/api/data_dir":
            # action="pick": mở hộp thoại chọn thư mục (tkinter, tiến trình con). Else: {root} → đổi + di dời.
            if (body.get("action") or "").strip() == "pick":
                try:
                    kq = subprocess.run([PYTHON_VENV, "chon_thu_muc.py", os.path.dirname(DATA_DIR) or ""],
                                        cwd=THU_MUC_GOC, capture_output=True, text=True, encoding="utf-8",
                                        errors="replace", creationflags=_NO_WINDOW, timeout=300)
                    path = ""
                    for line in (kq.stdout or "").splitlines():
                        if line.startswith("PICKED:"):
                            path = line[len("PICKED:"):].strip()
                    self._send(200, {"ok": bool(path), "path": path})
                except Exception as e:
                    self._send(200, {"ok": False, "msg": str(e)[:160]})
            else:
                kq = _doi_thu_muc_data(body.get("root"))
                if kq.get("ok") and kq.get("da_chuyen", 0):
                    them_log(f"📁 Đã đổi thư mục lưu video → {kq.get('root')} (di dời {kq['da_chuyen']} mục"
                             + (f", {kq['loi']} mục lỗi giữ lại chỗ cũ" if kq.get("loi") else "") + ").")
                self._send(200, kq)
        elif p.path == "/api/open_login":
            plats = body.get("platforms") or ["dy", "bili", "xhs"]
            plats = [x for x in plats if x in ("dy", "bili", "xhs", "rednote", "tt", "fb")]   # giữ login (yt công khai); wb/tw/ig/th đã tắt
            if not plats:   # nền tảng không hợp lệ -> KHÔNG để mo_dang_nhap mặc định mở dy/bili/xhs (bug ấn TikTok ra Douyin)
                self._send(200, {"ok": False, "msg": "Nền tảng không hợp lệ."}); return
            mo_dang_nhap(plats)
            them_log("🔑 Mở trình duyệt để đăng nhập: " + ", ".join(plats))
            self._send(200, {"ok": True, "platforms": plats})
        elif p.path == "/api/open_browse":
            # Nút 👁: mở cửa sổ Chromium (profile-cào) để khách TỰ LƯỚT + lấy link kênh/video.
            # Đã đăng nhập sẵn (chung profile cào) -> khỏi login lại; login/lướt ở đây thì cào sau thấy luôn.
            plats = body.get("platforms") or []
            plats = [x for x in plats if x in ("dy", "bili", "xhs", "rednote", "tt", "fb")]
            if not plats:
                self._send(200, {"ok": False, "msg": "Nền tảng không hợp lệ."}); return
            mo_luot(plats)
            them_log("👁 Mở cửa sổ lướt: " + ", ".join(plats))
            self._send(200, {"ok": True, "platforms": plats})
        elif p.path == "/api/logout_nentang":
            # Đăng xuất 1 nền tảng (xoá cookie profile) — nút "Đăng xuất" trên thẻ login
            plat = (body.get("plat") or "").strip()
            if plat not in ("dy", "bili", "xhs", "rednote", "tt", "fb"):
                self._send(200, {"ok": False, "msg": "Nền tảng không hợp lệ."}); return
            ok, msg = _logout_nentang(plat)
            if ok:
                them_log("🚪 Đã đăng xuất nền tảng: " + plat)
            self._send(200, {"ok": ok, "msg": msg, "trang_thai": _trang_thai_1lan(plat)})
        elif p.path == "/api/login_kiemtra":
            # Mở NGẦM (headless) từng nền tảng để xác minh đăng nhập rồi tự đóng
            them_log("🔍 Đang kiểm tra đăng nhập (chạy ngầm)...")
            kt = {}
            try:
                out = os.path.join(THU_MUC_GOC, "_login_check.json")
                try:
                    os.remove(out)
                except Exception:
                    pass
                subprocess.run([PYTHON_VENV, "kiem_tra_login.py", "dy", "bili", "xhs", "rednote", "wb", "tw", "ig", "tt", "fb"],
                               cwd=THU_MUC_GOC, capture_output=True, creationflags=_NO_WINDOW, timeout=180)
                if os.path.exists(out):
                    with open(out, encoding="utf-8") as f:
                        kt = json.load(f)
            except Exception as e:
                them_log("⚠️ Kiểm tra đăng nhập lỗi: " + str(e))
            # Gộp kết quả vào đủ 6 thẻ (tt/yt = na)
            tt = {}
            for x in NEN_TANG_LOGIN:
                if x.get("ytdlp") or x.get("khong_login"):
                    tt[x["ma"]] = "na"
                elif x.get("chup"):
                    tt[x["ma"]] = _trang_thai_login_chup(x["ma"])
                else:
                    tt[x["ma"]] = kt.get(x["ma"]) or trang_thai_dang_nhap(x["ma"])
            them_log("✅ Kiểm tra đăng nhập xong.")
            self._send(200, {"plats": NEN_TANG_LOGIN, "trang_thai": tt})
        elif p.path == "/api/login_kiemtra_one":
            # Kiểm tra LIVE 1 nền tảng (mở Chromium ngầm đọc cookie thật) — dùng khi guardLogin đọc
            # nhanh trên đĩa ra "out" để XÁC MINH lại trước khi chặn cào (tránh chặn oan dù đã đăng nhập).
            plat = (body.get("plat") or "").strip()
            if plat not in ("dy", "bili", "xhs", "rednote", "wb", "tw", "ig", "fb"):   # tt = yt-dlp công khai (như YouTube) → na, KHÔNG check login. fb: check THẬT (gate theo mode ở client — chỉ gọi khi Theo kênh)
                self._send(200, {"ok": False, "plat": plat, "trang_thai": "na"}); return
            st = "unknown"
            try:
                kq = subprocess.run([PYTHON_VENV, "kiem_tra_login.py", plat],
                                    cwd=THU_MUC_GOC, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", creationflags=_NO_WINDOW, timeout=60)
                for line in (kq.stdout or "").splitlines():
                    if line.startswith("LOGIN_CHECK_DONE "):
                        try:
                            st = (json.loads(line[len("LOGIN_CHECK_DONE "):]) or {}).get(plat) or "unknown"
                        except Exception:
                            pass
            except Exception:
                st = "unknown"
            self._send(200, {"ok": True, "plat": plat, "trang_thai": st})

        # ---- Theo dõi kênh ----
        elif p.path == "/api/td_save":
            # td_save trước KHÔNG canh → free/expired lưu config rồi td_run bỏ qua limit của td_on.
            # Canh y hệt td_on (expired chặn hết; theodoi_max theo tier). pro/unlimited: max None/3 → giữ nguyên.
            g = _guard_expired("theodoi")
            if g:
                self._send(200, g); return
            tdmax = _lim("theodoi_max")
            ncre = len(body.get("creators") or [])
            if tdmax is not None and ncre > tdmax:
                self._send(200, _block("theodoi",
                    (f"Gói {TIER.upper()} theo dõi tối đa {tdmax} kênh." if tdmax > 0
                     else "Gói FREE không có tính năng theo dõi kênh. Nâng cấp lên PRO/UNLIMITED để dùng."))); return
            # GIỮ store Theo dõi giàu (videos/avatar/tên) — merge theo link, KHÔNG wipe (thay luu_json thô của main)
            _td_ghi_creators(body.get("creators", []), body.get("interval", "30"), body.get("count", "10"))
            self._send(200, {"ok": True})
        elif p.path == "/api/td_add":
            # THEO DÕI (mới): thêm kênh → cào metadata (avatar+tên+videos mọi nền, như Kênh nguồn). Baseline = video
            # hiện có đánh dấu ĐÃ XEM (chỉ báo 'mới' cho video đăng SAU). Gate TIER theodoi (KHÔNG LohaPage).
            g = _guard_expired("theodoi")
            if g:
                self._send(200, g); return
            link = (body.get("link") or "").strip()
            if not link:
                self._send(200, {"ok": False, "msg": "Chưa nhập link kênh."}); return
            from nen_tang_helper import doan_nen_tang as _dnt
            plat = (body.get("platform") or "").strip()
            if plat not in ("dy", "bili", "xhs", "rednote", "wb"):
                plat = _dnt(link)      # đoán từ LINK (nguồn chuẩn) nếu client gửi sai/thiếu
            with _td_lock:
                d = _td_doc()
                if _td_tim(d, link):
                    self._send(200, {"ok": False, "msg": "Kênh đã trong danh sách theo dõi."}); return
                tdmax = _lim("theodoi_max")
                if tdmax is not None and len(d.get("creators", [])) >= tdmax:
                    self._send(200, _block("theodoi",
                        (f"Gói {TIER.upper()} theo dõi tối đa {tdmax} kênh." if tdmax > 0
                         else "Gói FREE không có tính năng theo dõi kênh. Nâng cấp lên PRO/UNLIMITED."))); return
                d.setdefault("creators", []).append({"link": link, "platform": plat, "ten": "", "videos": []})
                luu_json(FILE_TD, d)
            ok, _n, msg = _td_cap_nhat_1(link, baseline=True)
            with _td_lock:
                c = _td_tim(_td_doc(), link)
            self._send(200, {"ok": True, "kenh": _td_thong_ke(c) if c else {"link": link},
                             "canh_bao": ("" if ok else msg)})
        elif p.path == "/api/td_rename":
            link = (body.get("link") or "").strip(); ten = (body.get("ten") or "").strip()
            with _td_lock:
                d = _td_doc(); c = _td_tim(d, link)
                if not c:
                    self._send(200, {"ok": False, "msg": "Không thấy kênh."}); return
                c["ten"] = ten
                luu_json(FILE_TD, d)
            self._send(200, {"ok": True})
        elif p.path == "/api/td_remove":
            link = (body.get("link") or "").strip()
            with _td_lock:
                d = _td_doc(); n0 = len(d.get("creators", []))
                d["creators"] = [c for c in d.get("creators", []) if (c.get("link") or "").strip() != link]
                luu_json(FILE_TD, d)
            self._send(200, {"ok": True, "removed": n0 - len(d["creators"])})
        elif p.path == "/api/td_seen":
            link = (body.get("link") or "").strip(); vid = str(body.get("id") or "").strip()
            with _td_lock:
                d = _td_doc(); c = _td_tim(d, link)
                if c:
                    for v in c.get("videos", []):
                        if not vid or str(v.get("id")) == vid:
                            v["da_xem"] = True
                    luu_json(FILE_TD, d)
            self._send(200, {"ok": True})
        elif p.path == "/api/td_refresh":
            link = (body.get("link") or "").strip()
            if link:
                ok, n, msg = _td_cap_nhat_1(link)
                self._send(200, {"ok": ok, "so_moi": n, "msg": msg})
            else:      # làm mới TẤT CẢ (chạy nền, tránh block request)
                threading.Thread(target=lambda: [_td_cap_nhat_1((c.get("link") or "").strip())
                                                 for c in _td_doc().get("creators", []) if c.get("link")],
                                 daemon=True).start()
                self._send(200, {"ok": True, "async": True})
        elif p.path == "/api/td_on":
            g = _guard_expired("theodoi")
            if g:
                self._send(200, g); return
            tdmax = _lim("theodoi_max")
            ncre = len(body.get("creators") or [])
            if tdmax is not None and ncre > tdmax:
                self._send(200, _block("theodoi",
                    (f"Gói {TIER.upper()} theo dõi tối đa {tdmax} kênh." if tdmax > 0
                     else "Gói FREE không có tính năng theo dõi kênh. Nâng cấp lên PRO/UNLIMITED để dùng."))); return
            _td_ghi_creators(body.get("creators", []), body.get("interval", "30"), body.get("count", "10"))
            if not body.get("creators"):
                self._send(200, {"ok": False, "msg": "Chưa có kênh để theo dõi."}); return
            # /TR PHẢI bọc nháy: đường dẫn app có DẤU CÁCH ("reupo douyin+"/"Program Files") -> Task Scheduler
            # lưu chuỗi lệnh không-nháy sẽ TÁCH ở dấu cách khi chạy -> tìm "...\reupo" -> 0x80070002 (file not
            # found) -> task fail âm thầm, theo dõi KHÔNG chạy. (Chạy bat tay OK vì bat tự cd %~dp0.)
            kq = _schtasks(["/Create", "/TN", TASK_TD, "/TR", '"%s"' % BAT_TD, "/SC", "MINUTE",
                            "/MO", str(body.get("interval", "30")), "/F"])
            self._send(200, {"ok": kq.returncode == 0, "on": task_on(TASK_TD), "msg": kq.stderr or kq.stdout})
        elif p.path == "/api/td_off":
            _schtasks(["/Delete", "/TN", TASK_TD, "/F"])
            self._send(200, {"ok": True, "on": task_on(TASK_TD)})
        elif p.path == "/api/td_run":
            # td_run (chạy thử) trước KHÔNG canh → free/expired trigger theo_doi.py cào thật. Canh như td_on.
            g = _guard_expired("theodoi") or _can("theodoi", "theodoi",
                    "Gói FREE không có tính năng theo dõi kênh. Nâng cấp lên PRO/UNLIMITED để dùng.")
            if g:
                self._send(200, g); return
            subprocess.Popen([PYTHON_VENV, "theo_doi.py"], cwd=THU_MUC_GOC, creationflags=_NO_WINDOW)
            them_log("🧪 Đang kiểm tra theo dõi kênh...")
            self._send(200, {"ok": True})

        # ---- Hẹn giờ ----
        elif p.path == "/api/lich_save" or p.path == "/api/lich_on":
            # Hẹn giờ = cào tự động → expired (view-only) KHÔNG được lập/chạy lịch. (free vẫn dùng như cũ;
            # quota ngày thực thi vẫn do chay_crawl chốt.) pro/unlimited: không đổi.
            g = _guard_expired("cao")
            if g:
                self._send(200, g); return
            cfg = {"platform": body.get("platform", "dy"), "type": body.get("type", "search"),
                   "input": body.get("input", ""), "count": str(body.get("count", "10")),
                   "sort": int(body.get("sort", 0) or 0), "publish_time": int(body.get("publish_time", 0) or 0),
                   "tan_suat": body.get("tan_suat", "daily"),
                   "gio": str(body.get("gio", "08")).zfill(2), "phut": str(body.get("phut", "00")).zfill(2)}
            luu_json(FILE_LICH, cfg)
            if p.path == "/api/lich_save":
                self._send(200, {"ok": True}); return
            if not cfg["input"].strip():
                self._send(200, {"ok": False, "msg": "Chưa nhập nội dung cào."}); return
            if cfg["tan_suat"] == "hourly":
                # Mỗi giờ 1 lần, chạy ở phút cố định (00:phut, lặp mỗi 60 phút)
                kq = _schtasks(["/Create", "/TN", TASK_LICH, "/TR", '"%s"' % BAT_LICH, "/SC", "HOURLY",
                                "/MO", "1", "/ST", f"00:{cfg['phut']}", "/F"])
            else:
                kq = _schtasks(["/Create", "/TN", TASK_LICH, "/TR", '"%s"' % BAT_LICH, "/SC", "DAILY",
                                "/ST", f"{cfg['gio']}:{cfg['phut']}", "/F"])
            self._send(200, {"ok": kq.returncode == 0, "on": task_on(TASK_LICH), "msg": kq.stderr or kq.stdout})
        elif p.path == "/api/lich_off":
            _schtasks(["/Delete", "/TN", TASK_LICH, "/F"])
            self._send(200, {"ok": True, "on": task_on(TASK_LICH)})
        elif p.path == "/api/lich_run":
            g = _guard_expired("cao")   # chạy thử lịch = cào → expired chặn
            if g:
                self._send(200, g); return
            subprocess.Popen([PYTHON_VENV, "chay_tu_dong.py"], cwd=THU_MUC_GOC, creationflags=_NO_WINDOW)
            them_log("🧪 Đang chạy thử tác vụ hẹn giờ...")
            self._send(200, {"ok": True})

        # ---- Đăng nhập / đăng ký ----
        elif p.path == "/api/auth/register":
            uid, err = kdb.dang_ky(body.get("username"), body.get("password"))
            if err:
                self._send(200, {"ok": False, "msg": err}); return
            sess, err = kdb.dang_nhap(body.get("username"), body.get("password"))
            if err or not sess:   # tài khoản đã tạo nhưng auto-login lỗi → đừng crash, bảo đăng nhập tay
                self._send(200, {"ok": True, "msg": "Đã tạo tài khoản. Hãy đăng nhập."}); return
            self._send(200, {"ok": True, "token": sess["token"], "username": sess["username"]})
        elif p.path == "/api/auth/login":
            sess, err = kdb.dang_nhap(body.get("username"), body.get("password"))
            if err:
                self._send(200, {"ok": False, "msg": err}); return
            self._send(200, {"ok": True, "token": sess["token"], "username": sess["username"]})
        elif p.path == "/api/auth/logout":
            kdb.dang_xuat(self.headers.get("X-Token"))
            self._send(200, {"ok": True})

        # ---- Khách hàng (cần đăng nhập) ----
        elif p.path.startswith("/api/khach/"):
            u = self._user()
            if not u:
                self._send(401, {"ok": False, "msg": "Chưa đăng nhập"}); return
            uid = u["user_id"]
            if p.path == "/api/khach/add":
                kid, err = kdb.them_khach(uid, body.get("ten"), body.get("ghi_chu", ""))
                self._send(200, {"ok": not err, "id": kid, "msg": err})
            elif p.path == "/api/khach/edit":
                kdb.sua_khach(uid, int(body.get("id", 0)), body.get("ten"), body.get("ghi_chu", ""))
                self._send(200, {"ok": True})
            elif p.path == "/api/khach/del":
                kdb.xoa_khach(uid, int(body.get("id", 0)))
                self._send(200, {"ok": True})
            elif p.path == "/api/khach/tk_add":
                tid, err = kdb.them_tk(uid, int(body.get("khach_id", 0)),
                                       body.get("nen_tang", "dy"), body.get("nhan", ""),
                                       body.get("tk", ""), body.get("mk", ""),
                                       body.get("cookie", ""), body.get("token", ""))
                self._send(200, {"ok": not err, "id": tid, "msg": err})
            elif p.path == "/api/khach/tk_del":
                kdb.xoa_tk(uid, int(body.get("id", 0)))
                self._send(200, {"ok": True})
            else:
                self._send(404, {"error": "not found"})
        else:
            self._send(404, {"error": "not found"})


def _ap_dung_cache_settings():
    """Đẩy cấu hình cache (bật/tắt + cap) vào os.environ để MỌI subprocess (render + lồng tiếng)
    thừa kế (chúng đọc VC_CACHE_ON/VC_CACHE_CAP qua cache_artifact)."""
    try:
        s = _doc_settings()
        os.environ["VC_CACHE_ON"] = "0" if s.get("cache_on") is False else "1"
        os.environ["VC_CACHE_CAP"] = str(int(s.get("cache_cap_mb") or cache_artifact.CAP_MB_MAC_DINH))
    except Exception:
        pass


_TMP_RAC_HAU_TO = ("_bd_tmp.mp4", "_slow_tmp.mp4", "_che_tmp.mp4", "_khung_tmp.mp4",
                   "_slow_tmp_longtieng.mp4")


def _don_tmp_ro_ri(gio_cu=2.0):
    """DỌN file TẠM render RÒ RỈ (không bị xoá khi render LỖI/hủy giữa chừng → tích luỹ đầy đĩa máy khách).
    CHỈ xoá file có hậu-tố tmp render (_bd_tmp/_slow_tmp/_che_tmp/_khung_tmp) VÀ mtime CŨ > gio_cu (mặc định
    2h → chắc chắn KHÔNG phải file render ĐANG chạy: render active ghi mtime liên tục). KHÔNG bao giờ đụng
    video gốc / _xuly / _longtieng / _phude (không khớp hậu tố). Trả (số file, MB đã dọn)."""
    import time as _t
    now = _t.time()
    n = 0
    mb = 0.0
    try:
        for root, _dirs, files in os.walk(DATA_DIR):
            for f in files:
                if not f.endswith(_TMP_RAC_HAU_TO) or "_tmp" not in f:
                    continue
                fp = os.path.join(root, f)
                try:
                    st = os.stat(fp)
                    if (now - st.st_mtime) <= gio_cu * 3600:   # còn mới → có thể đang render → GIỮ
                        continue
                    sz = st.st_size
                    os.remove(fp)
                    n += 1
                    mb += sz / 1048576
                except OSError:
                    pass
    except Exception:
        pass
    return n, mb


def _cache_sweep_nen():
    """Dọn cache (TTL quá hạn + LRU vượt cap) + file TẠM render rò rỉ ở thread nền — KHÔNG chặn server/worker."""
    try:
        s = _doc_settings()
        cap = int(s.get("cache_cap_mb") or cache_artifact.CAP_MB_MAC_DINH)
        r = cache_artifact.sweep(cap_mb=cap)
        if r.get("ttl_xoa") or r.get("lru_xoa"):
            them_log("CACHE dọn: %d quá hạn + %d vượt cap." % (r["ttl_xoa"], r["lru_xoa"]))
    except Exception as e:
        them_log("CACHE sweep lỗi: %s" % str(e)[:80])
    try:   # dọn file tạm render rò rỉ (render lỗi/hủy giữa chừng KHÔNG dọn temps → tích đầy đĩa)
        _n, _mb = _don_tmp_ro_ri()
        if _n:
            them_log("🧹 Dọn %d file tạm render rò rỉ (%.0f MB)." % (_n, _mb))
    except Exception:
        pass


_omni_dl = {"running": False, "done": False, "started": False}
_omni_lock = threading.Lock()


def chay_tai_omnivoice():
    """TỰ tải/cài OmniVoice ở NỀN — CHỈ máy có NVIDIA (OmniVoice là diffusion GPU-only; máy không GPU
    bỏ qua, khỏi tải phí ~vài GB). Đã có .venv_omnivoice → coi như xong. cai_omnivoice.py idempotent.
    (User chọn: 'tự tải nền chỉ máy có GPU' — như FunASR nhưng có cổng GPU.)"""
    global _omni_dl
    with _omni_lock:
        if _omni_dl["running"] or _omni_dl["done"]:
            return
        if not _co_nvidia():
            _omni_dl["done"] = True
            return
        if os.path.isfile(os.path.join(THU_MUC_GOC, ".venv_omnivoice", "Scripts", "python.exe")):
            _omni_dl["done"] = True
            return
        _omni_dl.update({"running": True, "started": True})

    def worker():
        global _omni_dl
        try:   # tải nền IM LẶNG (bỏ log OmniVoice theo yêu cầu) — vẫn chạy bình thường
            subprocess.run([PYTHON_VENV, os.path.join(THU_MUC_GOC, "cai_omnivoice.py")],
                           creationflags=_NO_WINDOW, cwd=THU_MUC_GOC, timeout=3600)
        except Exception:
            pass
        finally:
            _omni_dl["running"] = False
            _omni_dl["done"] = True

    threading.Thread(target=worker, daemon=True).start()


# (Kokoro downloader ĐÃ GỠ 2026-07-04 — Supertonic phủ EN, tải sẵn qua pip supertonic; edge fallback online.)


def main():
    try:
        import sys
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        kdb.init_db()
    except Exception as e:
        them_log(f"Lỗi khởi tạo DB khách: {e}")
    _ap_dung_cache_settings()   # set env cache TRƯỚC khi worker render spawn (thừa kế qua os.environ)
    threading.Thread(target=_cache_sweep_nen, daemon=True).start()   # sweep lúc khởi động (nền)
    _khoi_dong_queue()
    _khoi_dong_task()
    _khoi_dong_auto_gom()   # gom đăng bài định kỳ (nếu bật auto_gom) → chuỗi Cào→Render→Gom→LoHa hands-off
    _khoi_dong_kn()         # Kênh nguồn: worker ngày (tải N/kênh theo lịch → render → giao LohaPage)
    _khoi_dong_theodoi()    # Theo dõi kênh: worker CỨNG 60p dò video mới (metadata, không tải) — thay Windows task
    _khoi_dong_login_recheck()   # kiểm tra login LIVE mỗi 3' (nền) → badge luôn tươi, hết "xanh giả" cookie cũ
    _khoi_dong_wfauto()     # tự động chạy CẢ quy trình (băm→render→xuất) nếu đã bật trước đó
    _khoi_dong_auto()
    try:
        chay_tai_omnivoice()   # tự tải OmniVoice ở nền CHỈ khi máy có GPU NVIDIA (bỏ qua nếu không GPU / đã cài)
    except Exception:
        pass
    them_log("Sẵn sàng.")
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    try:
        print("Web UI: " + url)
    except Exception:
        pass  # pythonw không có stdout
    import sys as _sys
    if "--noopen" not in _sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
