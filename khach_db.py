# -*- coding: utf-8 -*-
"""
Lưu trữ KHÁCH HÀNG + thông tin nhạy cảm (tài khoản đăng nhập, cookie/token) bằng SQLite.

Bảo mật:
- Mật khẩu TÀI KHOẢN APP (người dùng tool): hash bằng PBKDF2-HMAC-SHA256 + salt ngẫu nhiên (KHÔNG lưu plaintext).
- Thông tin nhạy cảm CỦA KHÁCH (user/pass nền tảng, cookie, token): MÃ HÓA bằng Fernet (AES-128-CBC + HMAC).
  Khóa nằm ở file `secret.key` (đã .gitignore). Mất khóa = không giải mã được dữ liệu cũ.

Đây là dự án HỌC TẬP — không dùng cho dữ liệu thật của người dùng thật.
"""
import os
import sys
import json
import time
import base64
import hashlib
import secrets
import sqlite3
import tempfile
import threading
from contextlib import closing

from cryptography.fernet import Fernet, InvalidToken

THU_MUC_GOC = os.path.dirname(os.path.abspath(__file__))
# DB khách + khóa mã hóa để ở thư mục BỀN VỮNG (KHACH_DB_DIR = userData khi đóng gói) -> KHÔNG bị update xoá.
# Trước ở app-src: mỗi lần cập nhật mất data + khóa, hoặc key/DB lệch nhau -> Fernet giải mã lỗi -> handler
# throw -> connection reset -> frontend báo "Lỗi kết nối". Dev/standalone (không set env) giữ cạnh file này.
_DATA_DIR = (os.environ.get("KHACH_DB_DIR") or "").strip() or THU_MUC_GOC
DB_PATH = os.path.join(_DATA_DIR, "data_khach.db")
KEY_PATH = os.path.join(_DATA_DIR, "secret.key")
# DI CƯ 1 lần: chỉ khi vị trí mới TRỐNG hẳn (cả db lẫn key) và vị trí cũ có -> copy CẢ CẶP (giữ key↔db khớp).
try:
    if _DATA_DIR != THU_MUC_GOC and not os.path.exists(DB_PATH) and not os.path.exists(KEY_PATH):
        os.makedirs(_DATA_DIR, exist_ok=True)
        import shutil as _sh
        for _src, _dst in ((os.path.join(THU_MUC_GOC, "secret.key"), KEY_PATH),
                           (os.path.join(THU_MUC_GOC, "data_khach.db"), DB_PATH)):
            if os.path.exists(_src):
                _sh.copy2(_src, _dst)
except Exception:
    pass

_PBKDF2_ITER = 200_000
_SESSION_TTL = 30 * 24 * 3600  # 30 ngày
_lock = threading.Lock()
_fernet = None


# ----------------- Khóa mã hóa -----------------
def _dpapi():
    """Module DPAPI (Windows) để BỌC khóa Fernet gắn với tài khoản Windows.
    Trả None nếu không khả dụng (vd dev non-Windows) -> fallback plaintext như cũ."""
    try:
        import bao_mat_key
        return bao_mat_key
    except Exception:
        return None


def _ghi_key(key: bytes, dp):
    """Ghi secret.key có MARKER + ghi ATOMIC (temp + os.replace):
      • Windows + DPAPI khả dụng -> `DPAPI1:` + base64(blob DPAPI). Bọc lỗi -> RAISE (KHÔNG ghi plaintext).
      • Windows nhưng module DPAPI lỗi -> RAISE (fail-CLOSED, TUYỆT ĐỐI không ghi plaintext).
      • Non-Windows (dev) -> `PLAIN1:` + key (đánh dấu rõ là plaintext có chủ đích)."""
    is_win = sys.platform == "win32"
    if dp is not None and is_win:
        try:
            data = b"DPAPI1:" + base64.b64encode(dp._ma_hoa(key))   # base64(blob DPAPI)
        except Exception as e:
            raise RuntimeError("DPAPI ma hoa secret.key that bai: %s" % e)
    elif is_win:
        # Windows nhưng module DPAPI không load được -> fail-closed (KHÔNG fallback plaintext)
        raise RuntimeError("DPAPI khong kha dung tren Windows — tu choi ghi secret.key plaintext")
    else:
        data = b"PLAIN1:" + key   # dev non-Windows: plaintext có đánh dấu
    # Ghi ATOMIC: temp cùng thư mục -> os.replace (NTFS/POSIX đảm bảo nguyên tử, không bao giờ để file dở dang)
    d = os.path.dirname(KEY_PATH) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".secret")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        try:
            os.chmod(tmp, 0o600)
        except Exception:
            pass
        os.replace(tmp, KEY_PATH)   # atomic
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def _lay_fernet():
    """Đọc (hoặc tạo lần đầu) khóa Fernet. Khóa được BỌC bằng DPAPI (gắn user Windows):
    malware cùng máy/user khác copy secret.key + data_khach.db -> KHÔNG giải mã được.
    Tự migrate secret.key plaintext cũ sang dạng bọc DPAPI (giá trị khóa giữ nguyên)."""
    global _fernet
    if _fernet is not None:
        return _fernet
    dp = _dpapi()
    key = None
    if os.path.exists(KEY_PATH):
        with open(KEY_PATH, "rb") as f:
            raw = f.read().strip()
        if raw.startswith(b"DPAPI1:"):
            # Khóa bọc DPAPI: BẮT BUỘC có DPAPI để giải mã. Thiếu/sai -> RAISE (KHÔNG đoán plaintext).
            if dp is None:
                raise RuntimeError("secret.key boc DPAPI nhung DPAPI khong kha dung")
            try:
                key = dp._giai_ma(base64.b64decode(raw[7:]))
            except Exception as e:
                raise RuntimeError("Giai ma secret.key that bai: %s" % e)
        elif raw.startswith(b"PLAIN1:"):
            key = raw[7:]
        else:
            # KEY CŨ KHÔNG MARKER (khách hiện hữu): thử DPAPI-b64 (Windows) rồi plaintext, rồi MIGRATE.
            # Giá trị khóa GIỮ NGUYÊN -> DB đã mã hóa của khách vẫn giải mã được sau migrate.
            if dp is not None and sys.platform == "win32":
                try:
                    key = dp._giai_ma(base64.b64decode(raw))   # khóa cũ đã bọc DPAPI (base64)
                except Exception:
                    key = None
            if key is None:
                key = raw                   # khóa cũ plaintext (hoặc dev non-Windows)
            try:
                _ghi_key(key, dp)           # migrate -> thêm marker + ghi atomic
            except Exception:
                pass                        # best-effort: không chặn load (tránh mất quyền dùng DB khách)
    else:
        key = Fernet.generate_key()
        _ghi_key(key, dp)
    _fernet = Fernet(key)
    return _fernet


def ma_hoa(s):
    """Mã hóa chuỗi -> token base64 (str). Chuỗi rỗng -> ''."""
    if not s:
        return ""
    return _lay_fernet().encrypt(s.encode("utf-8")).decode("ascii")


def giai_ma(token):
    """Giải mã token -> chuỗi. Lỗi/khác khóa -> ''."""
    if not token:
        return ""
    try:
        return _lay_fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, Exception):
        return ""


def _che(s, giu=2):
    """Che bớt thông tin nhạy cảm để hiển thị: 'abcdef' -> '••••ef'."""
    if not s:
        return ""
    if len(s) <= giu:
        return "•" * len(s)
    return "•" * min(6, len(s) - giu) + s[-giu:]


# ----------------- Mật khẩu app -----------------
def _hash_mk(mat_khau, salt=None):
    if salt is None:
        salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", mat_khau.encode("utf-8"), salt, _PBKDF2_ITER)
    return salt.hex(), dk.hex()


def _kiem_mk(mat_khau, salt_hex, hash_hex):
    _, dk = _hash_mk(mat_khau, bytes.fromhex(salt_hex))
    return secrets.compare_digest(dk, hash_hex)


# ----------------- DB -----------------
def _conn():
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init_db():
    _lay_fernet()
    with _lock, closing(_conn()) as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                pw_salt TEXT NOT NULL,
                pw_hash TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions(
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS khach(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                ten TEXT NOT NULL,
                ghi_chu TEXT DEFAULT '',
                created_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS khach_tk(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                khach_id INTEGER NOT NULL,
                nen_tang TEXT DEFAULT 'dy',
                nhan TEXT DEFAULT '',
                tk_enc TEXT DEFAULT '',
                mk_enc TEXT DEFAULT '',
                cookie_enc TEXT DEFAULT '',
                token_enc TEXT DEFAULT '',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                FOREIGN KEY(khach_id) REFERENCES khach(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS usage_gioihan(
                khoa TEXT PRIMARY KEY,         -- 'YYYY-MM-DD:loai' (theo ngày) hoặc 'all:loai' (tích luỹ)
                gia_tri INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        c.commit()


# ----------------- Đếm giới hạn theo gói (cào/lồng tiếng/clone...) -----------------
def _khoa_usage(loai, theo_ngay):
    ngay = time.strftime("%Y-%m-%d", time.localtime())   # reset 00:00 giờ máy local
    return (f"{ngay}:{loai}") if theo_ngay else f"all:{loai}"


def usage_lay(loai, theo_ngay=True):
    """Lấy giá trị đếm hiện tại (vd số video đã cào hôm nay)."""
    with _lock, closing(_conn()) as c:
        r = c.execute("SELECT gia_tri FROM usage_gioihan WHERE khoa=?",
                      (_khoa_usage(loai, theo_ngay),)).fetchone()
        return r["gia_tri"] if r else 0


def usage_cong(loai, delta=1, theo_ngay=True):
    """Cộng dồn (theo ngày hoặc tích luỹ). Trả giá trị mới."""
    khoa = _khoa_usage(loai, theo_ngay)
    with _lock, closing(_conn()) as c:
        c.execute("INSERT INTO usage_gioihan(khoa, gia_tri) VALUES(?, ?) "
                  "ON CONFLICT(khoa) DO UPDATE SET gia_tri = gia_tri + ?", (khoa, delta, delta))
        c.commit()
        return c.execute("SELECT gia_tri FROM usage_gioihan WHERE khoa=?", (khoa,)).fetchone()["gia_tri"]


# ----------------- Auth -----------------
def dang_ky(username, mat_khau):
    username = (username or "").strip().lower()  # không phân biệt hoa/thường (tránh trùng tài khoản)
    if len(username) < 3:
        return None, "Tên đăng nhập tối thiểu 3 ký tự."
    if len(mat_khau or "") < 6:
        return None, "Mật khẩu tối thiểu 6 ký tự."
    salt, h = _hash_mk(mat_khau)
    with _lock, closing(_conn()) as c:
        try:
            cur = c.execute(
                "INSERT INTO users(username, pw_salt, pw_hash, created_at) VALUES(?,?,?,?)",
                (username, salt, h, int(time.time())),
            )
            c.commit()
            return cur.lastrowid, None
        except sqlite3.IntegrityError:
            return None, "Tên đăng nhập đã tồn tại."


def dang_nhap(username, mat_khau):
    username = (username or "").strip().lower()  # không phân biệt hoa/thường (tránh trùng tài khoản)
    with _lock, closing(_conn()) as c:
        row = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if not row or not _kiem_mk(mat_khau or "", row["pw_salt"], row["pw_hash"]):
            return None, "Sai tên đăng nhập hoặc mật khẩu."
        token = secrets.token_urlsafe(32)
        c.execute("INSERT INTO sessions(token, user_id, expires_at) VALUES(?,?,?)",
                  (token, row["id"], int(time.time()) + _SESSION_TTL))
        c.commit()
        return {"token": token, "username": row["username"], "user_id": row["id"]}, None


def dam_bao_phien_local(username="owner"):
    """EMBEDDED (chạy trong app Electron đã xác thực license): đảm bảo có tài khoản chủ máy
    + cấp session, KHÔNG cần mật khẩu (license + gắn máy đã là lớp xác thực).
    Dùng cho luồng 'đăng ký license xong -> vào thẳng tool, không đăng nhập lần 2'."""
    username = (username or "owner").strip().lower() or "owner"
    with _lock, closing(_conn()) as c:
        row = c.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        if row:
            uid = row["id"]
        else:
            salt, h = _hash_mk(secrets.token_hex(16))  # mật khẩu ngẫu nhiên, không dùng để đăng nhập
            uid = c.execute(
                "INSERT INTO users(username, pw_salt, pw_hash, created_at) VALUES(?,?,?,?)",
                (username, salt, h, int(time.time()))).lastrowid
        token = secrets.token_urlsafe(32)
        c.execute("INSERT INTO sessions(token, user_id, expires_at) VALUES(?,?,?)",
                  (token, uid, int(time.time()) + _SESSION_TTL))
        c.commit()
        return {"token": token, "username": username, "user_id": uid}


def dang_xuat(token):
    with _lock, closing(_conn()) as c:
        c.execute("DELETE FROM sessions WHERE token=?", (token,))
        c.commit()


def user_tu_token(token):
    """Trả về dict {user_id, username} nếu token hợp lệ & chưa hết hạn, ngược lại None."""
    if not token:
        return None
    with _lock, closing(_conn()) as c:
        row = c.execute(
            "SELECT s.user_id, s.expires_at, u.username FROM sessions s "
            "JOIN users u ON u.id=s.user_id WHERE s.token=?", (token,)).fetchone()
        if not row:
            return None
        if row["expires_at"] < int(time.time()):
            c.execute("DELETE FROM sessions WHERE token=?", (token,))
            c.commit()
            return None
        return {"user_id": row["user_id"], "username": row["username"]}


def so_user():
    with _lock, closing(_conn()) as c:
        return c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]


# ----------------- Khách -----------------
def them_khach(user_id, ten, ghi_chu=""):
    ten = (ten or "").strip()
    if not ten:
        return None, "Thiếu tên khách."
    with _lock, closing(_conn()) as c:
        cur = c.execute("INSERT INTO khach(user_id, ten, ghi_chu, created_at) VALUES(?,?,?,?)",
                        (user_id, ten, (ghi_chu or "").strip(), int(time.time())))
        c.commit()
        return cur.lastrowid, None


def sua_khach(user_id, khach_id, ten, ghi_chu):
    with _lock, closing(_conn()) as c:
        c.execute("UPDATE khach SET ten=?, ghi_chu=? WHERE id=? AND user_id=?",
                  ((ten or "").strip(), (ghi_chu or "").strip(), khach_id, user_id))
        c.commit()
    return True, None


def xoa_khach(user_id, khach_id):
    with _lock, closing(_conn()) as c:
        c.execute("DELETE FROM khach WHERE id=? AND user_id=?", (khach_id, user_id))
        c.commit()
    return True, None


def liet_ke_khach(user_id):
    with _lock, closing(_conn()) as c:
        rows = c.execute(
            "SELECT k.*, (SELECT COUNT(*) FROM khach_tk t WHERE t.khach_id=k.id) so_tk "
            "FROM khach k WHERE k.user_id=? ORDER BY k.created_at DESC", (user_id,)).fetchall()
        return [dict(r) for r in rows]


def _khach_cua_user(c, user_id, khach_id):
    return c.execute("SELECT id FROM khach WHERE id=? AND user_id=?", (khach_id, user_id)).fetchone()


# ----------------- Tài khoản nhạy cảm của khách -----------------
def them_tk(user_id, khach_id, nen_tang, nhan, tk, mk, cookie, token):
    with _lock, closing(_conn()) as c:
        if not _khach_cua_user(c, user_id, khach_id):
            return None, "Không tìm thấy khách."
        now = int(time.time())
        cur = c.execute(
            "INSERT INTO khach_tk(khach_id, nen_tang, nhan, tk_enc, mk_enc, cookie_enc, token_enc, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (khach_id, nen_tang or "dy", (nhan or "").strip(),
             ma_hoa(tk), ma_hoa(mk), ma_hoa(cookie), ma_hoa(token), now, now))
        c.commit()
        return cur.lastrowid, None


def xoa_tk(user_id, tk_id):
    with _lock, closing(_conn()) as c:
        c.execute(
            "DELETE FROM khach_tk WHERE id=? AND khach_id IN (SELECT id FROM khach WHERE user_id=?)",
            (tk_id, user_id))
        c.commit()
    return True, None


def liet_ke_tk(user_id, khach_id, hien=False):
    """Liệt kê tài khoản của 1 khách. hien=False -> che bớt; hien=True -> giải mã đầy đủ."""
    with _lock, closing(_conn()) as c:
        if not _khach_cua_user(c, user_id, khach_id):
            return []
        rows = c.execute("SELECT * FROM khach_tk WHERE khach_id=? ORDER BY created_at DESC",
                         (khach_id,)).fetchall()
    out = []
    for r in rows:
        tk, mk = giai_ma(r["tk_enc"]), giai_ma(r["mk_enc"])
        cookie, token = giai_ma(r["cookie_enc"]), giai_ma(r["token_enc"])
        out.append({
            "id": r["id"], "nen_tang": r["nen_tang"], "nhan": r["nhan"],
            "tk": tk if hien else _che(tk),
            "mk": mk if hien else _che(mk),
            "cookie": cookie if hien else ("(có)" if cookie else ""),
            "token": token if hien else ("(có)" if token else ""),
            "co_cookie": bool(cookie), "co_token": bool(token),
            "updated_at": r["updated_at"],
        })
    return out
