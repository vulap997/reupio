# -*- coding: utf-8 -*-
"""Cache artifact LOSSLESS cho pipeline localize/render (tái dùng vi.srt/zh.srt/band.json/_dub.wav).

Mục tiêu: tăng tốc XỬ LÝ LẶP cùng 1 video (render lại, đổi cài-hình, thử nhiều giọng) bằng cách
tái dùng ĐÚNG artifact đã sinh — KHÔNG giảm chất lượng, KHÔNG đụng encode.

Nguyên tắc:
- NGHI NGỜ → MISS: mọi lỗi/không-chắc trả MISS (recompute) — cache KHÔNG bao giờ làm hỏng render.
- Key gồm video-hash (basename+size+mtime) + ĐỦ tham số ảnh hưởng output + CACHE_VERSION. Sót tham
  số = serve nhầm → bump CACHE_VERSION để vô hiệu cache cũ khi đổi logic.
- Cache dir = anh-em với data/ ở userData (bền qua auto-update); KHÔNG đụng data/ & processed_videos/.
- TTL theo st_mtime (Windows tắt atime) + os.utime touch khi HIT để gia hạn (last-access). LRU theo cap.

Stdlib only. API cho localize.py / web_app.py: duong_cache_dir, video_hash, tinh_key,
lay, luu, luu_noi_dung, sweep, xoa, bat.
"""
import os
import json
import time
import hashlib
import tempfile
import shutil

CACHE_VERSION = "1"          # BUMP khi đổi logic sinh artifact → vô hiệu cache cũ an toàn
try:
    # TTL mặc định 7 NGÀY (theo last-access — touch khi HIT). Trước là 1 ngày → render hôm trước hôm sau
    # đã hết cache. Chỉnh qua env VC_CACHE_TTL_DAYS (vd 30). Cap dung lượng vẫn giữ (LRU) nên không phình.
    TTL_GIAY = int(float(os.environ.get("VC_CACHE_TTL_DAYS") or 7) * 86400)
except (ValueError, TypeError):
    TTL_GIAY = 7 * 86400
CAP_MB_MAC_DINH = 3000       # cap mặc định (user chốt 2026-06-24); override qua env VC_CACHE_CAP
_TEN_THU_MUC = "_cache_artifact"

_cache_dir = None            # lazy resolve, cache module-level


# ---------------- Bật/tắt ----------------
def bat():
    """Cache có bật không. web_app set env VC_CACHE_ON='0' khi user tắt; mặc định bật."""
    return (os.environ.get("VC_CACHE_ON", "1") or "1").strip() != "0"


def _cap_mb():
    try:
        return max(50, int(os.environ.get("VC_CACHE_CAP") or CAP_MB_MAC_DINH))
    except (ValueError, TypeError):
        return CAP_MB_MAC_DINH


# ---------------- Thư mục cache ----------------
def duong_cache_dir():
    """Trả thư mục cache (anh-em với DATA_DIR), tạo nếu chưa có. Lỗi → None (→ cache vô hiệu)."""
    global _cache_dir
    if _cache_dir:
        return _cache_dir
    try:
        import data_dir
        dd = (os.environ.get("MC_DATA_DIR") or "").strip() or data_dir.giai_quyet()[0]
        cha = os.path.dirname(dd.rstrip("/\\")) or dd
        d = os.path.join(cha, _TEN_THU_MUC)
        os.makedirs(d, exist_ok=True)
        _cache_dir = d
        return d
    except Exception:
        return None


# ---------------- Hash / key ----------------
def video_hash(path):
    """Hash NHANH 1 file (video/ref-audio): basename+size+mtime. KHÔNG đọc nội dung (file lớn).
    Lỗi/không tồn tại → None (caller coi như MISS)."""
    try:
        st = os.stat(path)
        khoa = "%s|%d|%d" % (os.path.basename(path), st.st_size, int(st.st_mtime))
        return hashlib.sha1(khoa.encode("utf-8")).hexdigest()[:16]
    except Exception:
        return None


def noi_dung_hash(path):
    """Hash NỘI DUNG 1 file NHỎ (vd vi.srt) — ổn định qua copy (khác mtime). Lỗi → ''."""
    try:
        return hashlib.sha1(open(path, "rb").read()).hexdigest()[:16]
    except Exception:
        return ""


def co_srt(video):
    """True nếu ĐÃ có bản dịch (vi.srt) cache cho video này (BẤT KỲ cấu hình nào) — để UI hỏi
    'dùng lại bản dịch/lồng tiếng hay render từ đầu'. Glob theo prefix srt_<vhash>_ (KHÔNG cần khớp
    param-key, chỉ cần biết 'video này đã từng dịch'). Tắt cache / lỗi / chưa có → False."""
    if not bat():
        return False
    try:
        import glob
        vh = video_hash(video)
        d = duong_cache_dir()
        if not vh or not d:
            return False
        return bool(glob.glob(os.path.join(d, "srt_%s_*.vi.srt" % vh)))
    except Exception:
        return False


def tinh_key(loai, _vhash="", **params):
    """Key canonical cho 1 artifact. loai in {srt,band,dub}. _vhash = video_hash (đưa vào prefix
    tên file để xoa-per-video lọc được). params = MỌI tham số ảnh hưởng output (đã gồm các key nhúng).
    CACHE_VERSION luôn được thêm. Trả 'loai_vhash_hex' (None nếu _vhash rỗng → ép MISS)."""
    if not _vhash:
        return None
    try:
        params = dict(params)
        params["_v"] = CACHE_VERSION
        payload = json.dumps(params, sort_keys=True, ensure_ascii=False, default=str)
        h = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:24]
        return "%s_%s_%s" % (loai, _vhash, h)
    except Exception:
        return None


def _duong(key, suffix):
    d = duong_cache_dir()
    if not d or not key:
        return None
    return os.path.join(d, key + suffix)


# ---------------- Lấy / lưu ----------------
def lay(key, suffix):
    """HIT → trả path (đã touch mtime để gia hạn TTL); MISS/tắt/lỗi → None."""
    if not bat():
        return None
    p = _duong(key, suffix)
    if not p:
        return None
    try:
        if os.path.isfile(p) and os.path.getsize(p) > 0:
            try:
                os.utime(p, None)   # touch: last-access → gia hạn TTL
            except OSError:
                pass
            return p
    except Exception:
        pass
    return None


def _ghi_atomic(dest, viet_fn):
    """Ghi atomic vào dest: tmp cùng thư mục → os.replace. viet_fn(tmp_path) thực hiện ghi."""
    d = os.path.dirname(dest)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    os.close(fd)
    try:
        viet_fn(tmp)
        os.replace(tmp, dest)       # atomic ghi-đè trên Windows (khác os.rename)
        try:
            os.utime(dest, None)
        except OSError:
            pass
        return True
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def luu(key, suffix, src_path):
    """Copy 1 file đã sinh (vi.srt/_dub.wav...) vào cache (atomic). Trả True nếu lưu được."""
    if not bat():
        return False
    p = _duong(key, suffix)
    if not p or not src_path or not os.path.isfile(src_path):
        return False
    try:
        return _ghi_atomic(p, lambda tmp: shutil.copy2(src_path, tmp))
    except Exception:
        return False


def luu_noi_dung(key, suffix, data):
    """Ghi THẲNG nội dung (str/bytes — vd band.json nhỏ) vào cache (atomic). Trả True nếu lưu được."""
    if not bat():
        return False
    p = _duong(key, suffix)
    if not p:
        return False
    raw = data.encode("utf-8") if isinstance(data, str) else data

    def _viet(tmp):
        with open(tmp, "wb") as f:
            f.write(raw)
    try:
        return _ghi_atomic(p, _viet)
    except Exception:
        return False


# ---------------- Dọn cache ----------------
def _liet_ke():
    """[(path, mtime, size)] mọi file trong cache_dir (bỏ .tmp). Lỗi → []."""
    d = duong_cache_dir()
    out = []
    if not d:
        return out
    try:
        for e in os.scandir(d):
            if not e.is_file() or e.name.endswith(".tmp"):
                continue
            try:
                st = e.stat()
                out.append((e.path, st.st_mtime, st.st_size))
            except OSError:
                pass
    except Exception:
        pass
    return out


def _xoa_file(p):
    try:
        os.remove(p)
        return True
    except (OSError, PermissionError):   # Windows: file đang mở → bỏ qua, lần sau dọn
        return False


def sweep(ttl_giay=None, cap_mb=None):
    """Dọn: (1) file quá TTL (now-mtime>ttl); (2) LRU nếu tổng > cap. Trả {'ttl_xoa','lru_xoa'}.
    Chạy KỂ CẢ khi cache tắt (giải phóng ổ). Fail-safe per-file."""
    ttl_giay = TTL_GIAY if ttl_giay is None else ttl_giay
    cap_byte = (_cap_mb() if cap_mb is None else cap_mb) * 1024 * 1024
    files = _liet_ke()
    now = time.time()
    ttl_xoa = lru_xoa = 0
    con = []
    for p, mt, sz in files:
        if ttl_giay > 0 and (now - mt) > ttl_giay:
            if _xoa_file(p):
                ttl_xoa += 1
        else:
            con.append((p, mt, sz))
    tong = sum(sz for _, _, sz in con)
    if cap_byte > 0 and tong > cap_byte:
        con.sort(key=lambda x: x[1])            # cũ nhất trước (mtime tăng dần)
        for p, _mt, sz in con:
            if tong <= cap_byte:
                break
            if _xoa_file(p):
                tong -= sz
                lru_xoa += 1
    return {"ttl_xoa": ttl_xoa, "lru_xoa": lru_xoa}


def xoa(scope="all", video_hash=None):
    """Xóa cache. scope='all' → toàn bộ; scope='video' + video_hash → chỉ artifact của video đó
    (lọc theo prefix '_<vhash>_' trong tên). CHỈ thao tác trong cache_dir. Trả số file đã xóa."""
    d = duong_cache_dir()
    if not d:
        return 0
    loc = ("_%s_" % video_hash) if (scope == "video" and video_hash) else None
    n = 0
    for p, _mt, _sz in _liet_ke():
        ten = os.path.basename(p)
        if loc and loc not in ten:
            continue
        # an toàn: chỉ xóa file NẰM TRONG cache_dir
        if not os.path.abspath(p).startswith(os.path.abspath(d)):
            continue
        if _xoa_file(p):
            n += 1
    return n


def dung_luong_mb():
    """Tổng dung lượng cache (MB) — cho /api/cache/stats."""
    return round(sum(sz for _, _, sz in _liet_ke()) / (1024 * 1024), 1)
