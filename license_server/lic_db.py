# -*- coding: utf-8 -*-
"""
TẦNG DB cho LICENSE SERVER (chạy trên cloud, TÁCH BIỆT hoàn toàn với tool local).

Thiết kế NÂNG CẤP từ khach_db.py (kế thừa pattern PBKDF2 + session) nhưng:
- DB riêng (license.db) — KHÔNG đụng data_khach.db của tool local.
- Thêm: licenses (gói + hạn), devices (ràng buộc thiết bị), activations (audit).
- Phát signed offline token (HMAC) để app desktop kiểm license offline trong grace period.

KHÔNG import / không sửa khach_db.py — file này độc lập, dành cho server cloud.
Dự án học tập — không dùng cho dữ liệu thật.
"""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
from contextlib import closing

THU_MUC = os.path.dirname(os.path.abspath(__file__))
# Cho phép tách dữ liệu ra volume khi deploy (Docker): đặt LIC_DB_DIR=/data
_DATA_DIR = os.environ.get("LIC_DB_DIR", THU_MUC)
try:
    os.makedirs(_DATA_DIR, exist_ok=True)
except Exception:
    _DATA_DIR = THU_MUC
DB_PATH = os.path.join(_DATA_DIR, "license.db")
SECRET_PATH = os.path.join(_DATA_DIR, "lic_secret.key")   # khóa HMAC ký token (gitignore)

_PBKDF2_ITER = 200_000
_SESSION_TTL = 30 * 24 * 3600          # phiên đăng nhập portal: 30 ngày
_OFFLINE_TTL = 7 * 24 * 3600           # token offline cho app desktop: 7 ngày (grace)
_lock = threading.Lock()
_secret = None


def _env_int(ten, mac_dinh):
    """Đọc env số nguyên; rỗng/sai -> mặc định. Dùng cho ngưỡng churn (tắt mặc định)."""
    try:
        return int((os.environ.get(ten, "") or "").strip() or mac_dinh)
    except (TypeError, ValueError):
        return mac_dinh


# ----------------- Khóa ký token (HMAC) -----------------
def _lay_secret() -> bytes:
    global _secret
    if _secret is not None:
        return _secret
    env = os.environ.get("LIC_SECRET", "").strip()
    if env:
        try:
            _secret = bytes.fromhex(env)
        except ValueError:
            _secret = env.encode("utf-8")
        return _secret
    if os.path.exists(SECRET_PATH):
        with open(SECRET_PATH, "rb") as f:
            _secret = f.read().strip()
    else:
        # Thay vì sinh ngẫu nhiên làm lệch signature với Google Sheets,
        # ta dùng khóa mặc định khớp với Apps Script.
        _secret = b"your_secret_key_here"
        try:
            with open(SECRET_PATH, "wb") as f:
                f.write(_secret)
            os.chmod(SECRET_PATH, 0o600)
        except Exception:
            pass
    return _secret


# ----------------- Hash mật khẩu (kế thừa pattern khach_db) -----------------
def _hash_mk(mat_khau, salt=None):
    if salt is None:
        salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", mat_khau.encode("utf-8"), salt, _PBKDF2_ITER)
    return salt.hex(), dk.hex()


def _kiem_mk(mat_khau, salt_hex, hash_hex):
    _, dk = _hash_mk(mat_khau or "", bytes.fromhex(salt_hex))
    return secrets.compare_digest(dk, hash_hex)


# ----------------- DB -----------------
def _conn():
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init_db():
    _lay_secret()
    with _lock, closing(_conn()) as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT DEFAULT '',
                pw_salt TEXT NOT NULL,
                pw_hash TEXT NOT NULL,
                is_admin INTEGER DEFAULT 0,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions(
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS licenses(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                plan TEXT DEFAULT 'free',
                max_devices INTEGER DEFAULT 1,
                status TEXT DEFAULT 'active',          -- active | expired | revoked
                starts_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,            -- 0 = vĩnh viễn
                created_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS devices(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                license_id INTEGER NOT NULL,
                hwid TEXT NOT NULL,
                device_name TEXT DEFAULT '',
                os TEXT DEFAULT '',
                active INTEGER DEFAULT 1,
                first_seen INTEGER NOT NULL,
                last_seen INTEGER NOT NULL,
                UNIQUE(license_id, hwid),
                FOREIGN KEY(license_id) REFERENCES licenses(id) ON DELETE CASCADE
            );
            -- 1 HWID chỉ được ACTIVE ở 1 license tại 1 thời điểm (chống lách giới hạn thiết bị:
            -- gắn cùng 1 máy vào nhiều license). MIRROR lic_db_pg.py (active=TRUE). SQLite hỗ trợ
            -- partial index (WHERE) từ 3.8. Di cư hwid (_di_cu_hwid) UPDATE cùng hàng -> không tạo
            -- hàng active mới -> không vi phạm index.
            CREATE UNIQUE INDEX IF NOT EXISTS uq_devices_hwid_active
                ON devices(hwid) WHERE active = 1;
            CREATE TABLE IF NOT EXISTS activations(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                license_id INTEGER,
                hwid TEXT,
                action TEXT,                            -- activate|deactivate|check|deny
                detail TEXT DEFAULT '',
                at INTEGER NOT NULL
            );
            -- (unique index uq_devices_hwid_active đã tạo ở trên — 1 hwid chỉ ACTIVE 1 license.)
            -- idx hỗ trợ truy vấn CHURN (activations theo license + thời gian).
            CREATE INDEX IF NOT EXISTS idx_activations_lic_at ON activations(license_id, at);
            -- Rate-limit DB-backed (chống brute-force): mirror lic_db_pg.py. Lưu mốc thời gian
            -- mỗi lần thử theo khóa (vd "login:<ip>") -> đếm trong cửa sổ -> chặn khi vượt ngưỡng.
            CREATE TABLE IF NOT EXISTS login_attempts(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                k TEXT NOT NULL,
                ts INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_la_k_ts ON login_attempts(k, ts);
            """
        )
        c.commit()


def _audit(c, license_id, hwid, action, detail=""):
    c.execute("INSERT INTO activations(license_id, hwid, action, detail, at) VALUES(?,?,?,?,?)",
              (license_id, hwid, action, detail, int(time.time())))


def _audit_safe(license_id, hwid, action, detail=""):
    """Ghi audit trên kết nối RIÊNG (dùng sau rollback). Nuốt lỗi để không che lỗi gốc. MIRROR lic_db_pg."""
    try:
        with _lock, closing(_conn()) as c2:
            _audit(c2, license_id, hwid, action, detail)
            c2.commit()
    except Exception:
        pass


def _canh_bao_hwid(c, user_id, license_id, max_devices):
    """H9 — HWID self-asserted: ĐẾM số thiết bị active của license; nếu vượt ngưỡng mềm (max_devices + biên)
    -> LOG cảnh báo (KHÔNG block, tránh false-positive). KHÔNG phá _di_cu_hwid (UPDATE cùng hàng -> không tăng
    count). MIRROR lic_db_pg._canh_bao_hwid (active=TRUE / %s)."""
    try:
        bien = 2
        n = c.execute("SELECT COUNT(*) AS n FROM devices WHERE license_id=? AND active=1",
                      (license_id,)).fetchone()["n"]
        if n > (max_devices or 1) + bien:
            print("[license-server][WARN] HWID bat thuong: user=%s license=%s co %d thiet bi active (max=%s)"
                  % (user_id, license_id, n, max_devices))
    except Exception:
        pass


# ----------------- Rate-limit DB-backed (MIRROR lic_db_pg.rate_limited) -----------------
def rate_limited(k, limit, window):
    """Trả True nếu khóa `k` đã vượt `limit` lần trong `window` giây. Đếm trên bảng login_attempts
    (chia sẻ giữa các tiến trình/instance) -> chặn brute-force kể cả serverless. Dọn rác inline."""
    now = int(time.time())
    with _lock, closing(_conn()) as c:
        c.execute("DELETE FROM login_attempts WHERE ts < ?", (now - window,))
        n = c.execute("SELECT COUNT(*) AS n FROM login_attempts WHERE k=? AND ts > ?",
                      (k, now - window)).fetchone()["n"]
        if n >= limit:
            c.commit()
            return True
        c.execute("INSERT INTO login_attempts(k, ts) VALUES(?,?)", (k, now))
        c.commit()
        return False


# ----------------- Tài khoản -----------------
def _chuan_username(username):
    # Chuẩn hoá: bỏ khoảng trắng + chữ thường -> username KHÔNG phân biệt hoa/thường.
    return (username or "").strip().lower()


def dang_ky(username, mat_khau, email=""):
    username = _chuan_username(username)
    if len(username) < 3:
        return None, "Tên đăng nhập tối thiểu 3 ký tự."
    if len((mat_khau or "")) < 6:
        return None, "Mật khẩu tối thiểu 6 ký tự."
    salt, h = _hash_mk(mat_khau)
    with _lock, closing(_conn()) as c:
        try:
            cur = c.execute(
                "INSERT INTO users(username, email, pw_salt, pw_hash, created_at) VALUES(?,?,?,?,?)",
                (username, (email or "").strip(), salt, h, int(time.time())))
            c.commit()
            return cur.lastrowid, None
        except sqlite3.IntegrityError:
            return None, "Tên đăng nhập đã tồn tại."


def dang_nhap(username, mat_khau):
    username = _chuan_username(username)
    with _lock, closing(_conn()) as c:
        row = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if not row or not _kiem_mk(mat_khau, row["pw_salt"], row["pw_hash"]):
            return None, "Sai tên đăng nhập hoặc mật khẩu."
        token = secrets.token_urlsafe(32)
        c.execute("INSERT INTO sessions(token, user_id, expires_at) VALUES(?,?,?)",
                  (token, row["id"], int(time.time()) + _SESSION_TTL))
        c.commit()
        return {"token": token, "username": row["username"],
                "user_id": row["id"], "is_admin": bool(row["is_admin"])}, None


def dang_xuat(token):
    with _lock, closing(_conn()) as c:
        c.execute("DELETE FROM sessions WHERE token=?", (token,))
        c.commit()


def user_tu_token(token):
    if not token:
        return None
    with _lock, closing(_conn()) as c:
        row = c.execute(
            "SELECT s.user_id, s.expires_at, u.username, u.is_admin FROM sessions s "
            "JOIN users u ON u.id=s.user_id WHERE s.token=?", (token,)).fetchone()
        if not row:
            return None
        if row["expires_at"] < int(time.time()):
            c.execute("DELETE FROM sessions WHERE token=?", (token,))
            c.commit()
            return None
        return {"user_id": row["user_id"], "username": row["username"], "is_admin": bool(row["is_admin"])}


def dat_admin(user_id, admin=True):
    with _lock, closing(_conn()) as c:
        c.execute("UPDATE users SET is_admin=? WHERE id=?", (1 if admin else 0, user_id))
        c.commit()


def user_id_theo_username(username):
    username = _chuan_username(username)
    if not username:
        return None, "Thiếu username."
    with _lock, closing(_conn()) as c:
        row = c.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    if not row:
        return None, "Không tìm thấy user."
    return row["id"], None


def go_thiet_bi_admin(username, hwid=""):
    """ADMIN gỡ thiết bị của user BẤT KỲ. hwid rỗng = gỡ HẾT thiết bị active. Dùng khi HWID trôi/đổi máy
    làm user kẹt 'đã gắn máy khác' -> giải phóng slot để user kích hoạt lại máy hiện tại. Trả (số_gỡ, None)|(None,lỗi)."""
    uid, err = user_id_theo_username(username)
    if err:
        return None, err
    hwid = (hwid or "").strip()
    with _lock, closing(_conn()) as c:
        lic = c.execute("SELECT id FROM licenses WHERE user_id=? ORDER BY id DESC LIMIT 1", (uid,)).fetchone()
        if not lic:
            return None, "User chưa có license."
        if hwid:
            cur = c.execute("UPDATE devices SET active=0 WHERE license_id=? AND hwid=?", (lic["id"], hwid))
        else:
            cur = c.execute("UPDATE devices SET active=0 WHERE license_id=? AND active=1", (lic["id"],))
        _audit(c, lic["id"], hwid or "all", "deactivate", "admin go thiet bi")
        c.commit()
        return cur.rowcount, None


# ----------------- License -----------------
def cap_license(user_id, plan="pro", max_devices=1, days=30):
    """Cấp/gia hạn license cho user. days=0 => vĩnh viễn.

    Mô hình subscription: mỗi user dùng 1 license row duy nhất; cấp lại = HỒI SINH
    chính license đó (giữ nguyên license_id) để các thiết bị đã ràng buộc vẫn còn hiệu lực.
    Chỉ tạo mới khi user chưa từng có license.
    """
    now = int(time.time())
    exp = 0 if days == 0 else now + days * 24 * 3600
    with _lock, closing(_conn()) as c:
        row = c.execute("SELECT * FROM licenses WHERE user_id=? ORDER BY id DESC LIMIT 1",
                        (user_id,)).fetchone()
        if row:
            # gia hạn: cộng tiếp nếu license CŨ còn hạn & active; nếu không thì tính từ now
            con_han = (row["status"] == "active" and row["expires_at"] and row["expires_at"] > now)
            base = row["expires_at"] if con_han else now
            new_exp = 0 if days == 0 else base + days * 24 * 3600
            c.execute("UPDATE licenses SET plan=?, max_devices=?, status='active', expires_at=? WHERE id=?",
                      (plan, max_devices, new_exp, row["id"]))
            c.commit()
            return row["id"], None
        cur = c.execute(
            "INSERT INTO licenses(user_id, plan, max_devices, status, starts_at, expires_at, created_at) "
            "VALUES(?,?,?,'active',?,?,?)", (user_id, plan, max_devices, now, exp, now))
        c.commit()
        return cur.lastrowid, None


def thu_hoi_license(user_id):
    with _lock, closing(_conn()) as c:
        c.execute("UPDATE licenses SET status='revoked' WHERE user_id=?", (user_id,))
        c.commit()


def _license_active_cua_user(c, user_id):
    """Trả license của user (KHÔNG chặn khi hết hạn — hết hạn pro vẫn dùng được tier FREE).
    Chỉ chặn khi chưa có license hoặc bị thu hồi (revoked)."""
    row = c.execute("SELECT * FROM licenses WHERE user_id=? ORDER BY id DESC LIMIT 1",
                    (user_id,)).fetchone()
    if not row:
        return None, "Chưa có license."
    if row["status"] == "revoked":
        return None, "License đã bị thu hồi."
    return row, None


_TRIAL_GIAY = 7 * 86400  # free = 7 ngày dùng thử tính từ licenses.created_at


def _tier(lic):
    """Gói hiện tại: 'pro'/'unlimited' nếu gói trả phí còn hạn; free hết 7 ngày -> 'expired'; else 'free'."""
    now = int(time.time())
    plan = (lic["plan"] or "free")
    if plan == "free":
        created = lic["created_at"] or now
        if (now - created) > _TRIAL_GIAY:
            return "expired"
        return "free"
    con_han = (not lic["expires_at"]) or (lic["expires_at"] > now)
    if plan != "free" and lic["status"] == "active" and con_han:
        return plan if plan in ("pro", "unlimited") else "pro"
    return "free"


# ----------------- Device binding -----------------
def _di_cu_hwid(c, license_id, hwid, hwid_cu, now):
    """DI CƯ binding: nếu máy này từng gắn bằng HWID CŨ (có MAC, ≤v0.1.27) -> đổi sang HWID MỚI ổn định
    (cùng máy vật lý). Chỉ máy gốc mới tính được hwid_cu -> KHÔNG nới lỏng chống share. Trả device đã di cư | None."""
    hwid_cu = (hwid_cu or "").strip()
    if not hwid_cu or hwid_cu == hwid:
        return None
    old = c.execute("SELECT * FROM devices WHERE license_id=? AND hwid=?", (license_id, hwid_cu)).fetchone()
    if not old:
        return None
    c.execute("UPDATE devices SET hwid=?, last_seen=? WHERE id=?", (hwid, now, old["id"]))
    _audit(c, license_id, hwid, "migrate", "hwid cu " + hwid_cu[:8] + " -> moi")
    return c.execute("SELECT * FROM devices WHERE id=?", (old["id"],)).fetchone()


def kich_hoat_thiet_bi(user_id, hwid, device_name="", os_name="", hwid_cu=""):
    """Ràng buộc 1 thiết bị vào license. Enforce max_devices. Trả (token_offline, info) | (None, lỗi)."""
    hwid = (hwid or "").strip()
    if not hwid:
        return None, "Thiếu HWID."
    now = int(time.time())
    with _lock, closing(_conn()) as c:
        lic, err = _license_active_cua_user(c, user_id)
        if err:
            _audit(c, None, hwid, "deny", err); c.commit()
            return None, err
        # đã đăng ký thiết bị này? (chưa thấy HWID mới -> thử DI CƯ từ HWID cũ có MAC, cùng máy vật lý)
        dev = c.execute("SELECT * FROM devices WHERE license_id=? AND hwid=?",
                        (lic["id"], hwid)).fetchone()
        if not dev:
            dev = _di_cu_hwid(c, lic["id"], hwid, hwid_cu, now)
        if dev:
            try:
                c.execute("UPDATE devices SET active=1, last_seen=?, device_name=?, os=? WHERE id=?",
                          (now, device_name or dev["device_name"], os_name or dev["os"], dev["id"]))
            except sqlite3.IntegrityError:
                # partial unique uq_devices_hwid_active: hwid này đang ACTIVE ở license khác
                c.rollback()
                _audit_safe(lic["id"], hwid, "deny", "reactivate nhung hwid active o license khac")
                return None, "Máy này đã được đăng ký với một tài khoản khác. Mỗi máy chỉ dùng được 1 tài khoản."
            _audit(c, lic["id"], hwid, "activate", "reactivate")
            c.commit()
            return _ky_token(user_id, lic, hwid), _thong_tin_license(lic, hwid)
        # 1 MÁY = 1 TÀI KHOẢN: hwid này đã active-gắn vào tài khoản KHÁC?
        chu_khac = c.execute(
            "SELECT li.user_id FROM devices d JOIN licenses li ON li.id=d.license_id "
            "WHERE d.hwid=? AND d.active=1 AND li.user_id<>? LIMIT 1", (hwid, user_id)).fetchone()
        if chu_khac:
            _audit(c, lic["id"], hwid, "deny", "may da gan tai khoan khac")
            c.commit()
            return None, "Máy này đã được đăng ký với một tài khoản khác. Mỗi máy chỉ dùng được 1 tài khoản."
        # thiết bị mới: kiểm giới hạn
        dang_active = c.execute(
            "SELECT COUNT(*) n FROM devices WHERE license_id=? AND active=1", (lic["id"],)).fetchone()["n"]
        if dang_active >= lic["max_devices"]:
            _audit(c, lic["id"], hwid, "deny", f"vuot gioi han {lic['max_devices']} thiet bi")
            c.commit()
            if lic["max_devices"] <= 1:
                return None, "Tài khoản này đã được gắn với một máy khác. Mỗi tài khoản chỉ dùng được trên 1 máy."
            return None, f"Đã đạt giới hạn {lic['max_devices']} thiết bị. Gỡ bớt máy cũ để kích hoạt máy mới."
        # CHURN CAP (opt-in, MẶC ĐỊNH TẮT): chống 1 tài khoản XOAY nhiều máy (account sharing). Đếm số HWID
        # KHÁC NHAU đã activate trong cửa sổ; vượt ngưỡng -> chặn gắn máy MỚI (KHÔNG đụng máy đã gắn:
        # check()/reactivate vẫn chạy bình thường). LIC_CHURN_MAX=0 -> tắt hẳn = hành vi cũ không đổi.
        churn_max = _env_int("LIC_CHURN_MAX", 0)
        if churn_max > 0:
            win = _env_int("LIC_CHURN_WINDOW_DAYS", 30) * 86400
            n_hwid = c.execute(
                "SELECT COUNT(DISTINCT hwid) n FROM activations "
                "WHERE license_id=? AND action IN ('activate','migrate') AND at>=?",
                (lic["id"], now - win)).fetchone()["n"]
            if n_hwid >= churn_max:
                _audit(c, lic["id"], hwid, "deny", f"churn vuot {churn_max} may")
                c.commit()
                return None, "Tài khoản đổi máy quá nhiều lần trong thời gian ngắn. Vui lòng liên hệ hỗ trợ."
        try:
            c.execute(
                "INSERT INTO devices(license_id, hwid, device_name, os, active, first_seen, last_seen) "
                "VALUES(?,?,?,?,1,?,?)", (lic["id"], hwid, device_name, os_name, now, now))
        except sqlite3.IntegrityError:
            # partial unique uq_devices_hwid_active: hwid đã ACTIVE ở license khác (race/lách giới hạn)
            c.rollback()
            _audit_safe(lic["id"], hwid, "deny", "hwid da active o license khac")
            return None, "Máy này đã được đăng ký với một tài khoản khác. Mỗi máy chỉ dùng được 1 tài khoản."
        _audit(c, lic["id"], hwid, "activate", "new")
        _canh_bao_hwid(c, user_id, lic["id"], lic["max_devices"])   # H9: tín hiệu bất thường (chỉ log)
        c.commit()
        return _ky_token(user_id, lic, hwid), _thong_tin_license(lic, hwid)


def go_thiet_bi(user_id, hwid):
    """Gỡ (deactivate) 1 thiết bị → giải phóng slot."""
    with _lock, closing(_conn()) as c:
        lic, err = _license_active_cua_user(c, user_id)
        if err:
            return False, err
        cur = c.execute("UPDATE devices SET active=0 WHERE license_id=? AND hwid=?",
                        (lic["id"], (hwid or "").strip()))
        _audit(c, lic["id"], hwid, "deactivate", "")
        c.commit()
        if cur.rowcount == 0:
            return False, "Không tìm thấy thiết bị."
        return True, None


def kiem_license(user_id, hwid, hwid_cu=""):
    """Kiểm license + thiết bị còn hiệu lực (gọi định kỳ từ app). Trả (token_offline, info) | (None, lỗi)."""
    hwid = (hwid or "").strip()
    now = int(time.time())
    with _lock, closing(_conn()) as c:
        lic, err = _license_active_cua_user(c, user_id)
        if err:
            _audit(c, None, hwid, "deny", err); c.commit()
            return None, err
        dev = c.execute("SELECT * FROM devices WHERE license_id=? AND hwid=? AND active=1",
                        (lic["id"], hwid)).fetchone()
        if not dev and _di_cu_hwid(c, lic["id"], hwid, hwid_cu, now):   # DI CƯ HWID cũ->mới (cùng máy)
            dev = c.execute("SELECT * FROM devices WHERE license_id=? AND hwid=? AND active=1",
                            (lic["id"], hwid)).fetchone()
        if not dev:
            _audit(c, lic["id"], hwid, "deny", "thiet bi chua kich hoat")
            c.commit()
            return None, "Thiết bị chưa được kích hoạt."
        c.execute("UPDATE devices SET last_seen=? WHERE id=?", (now, dev["id"]))
        _audit(c, lic["id"], hwid, "check", "ok")
        c.commit()
        return _ky_token(user_id, lic, hwid), _thong_tin_license(lic, hwid)


def liet_ke_thiet_bi(user_id):
    with _lock, closing(_conn()) as c:
        lic, err = _license_active_cua_user(c, user_id)
        if err:
            return []
        rows = c.execute(
            "SELECT hwid, device_name, os, active, first_seen, last_seen FROM devices "
            "WHERE license_id=? ORDER BY last_seen DESC", (lic["id"],)).fetchall()
        return [dict(r) for r in rows]


# ----------------- Tóm tắt cho Portal / Admin -----------------
def thong_tin_license(user_id):
    """Tóm tắt license của 1 user (cho portal user xem). None nếu chưa có license."""
    now = int(time.time())
    with _lock, closing(_conn()) as c:
        row = c.execute("SELECT * FROM licenses WHERE user_id=? ORDER BY id DESC LIMIT 1",
                        (user_id,)).fetchone()
        if not row:
            return None
        status = row["status"]
        if status == "active" and row["expires_at"] and row["expires_at"] < now:
            status = "expired"
        active_dev = c.execute(
            "SELECT COUNT(*) n FROM devices WHERE license_id=? AND active=1", (row["id"],)).fetchone()["n"]
        return {
            "plan": row["plan"], "status": status,
            "max_devices": row["max_devices"], "devices_active": active_dev,
            "starts_at": row["starts_at"], "expires_at": row["expires_at"],
        }


def liet_ke_users():
    """Cho admin: danh sách user + tóm tắt license. KHÔNG trả mật khẩu/hash."""
    now = int(time.time())
    with _lock, closing(_conn()) as c:
        users = c.execute("SELECT id, username, email, is_admin, created_at FROM users ORDER BY id").fetchall()
        out = []
        for u in users:
            lic = c.execute("SELECT * FROM licenses WHERE user_id=? ORDER BY id DESC LIMIT 1",
                            (u["id"],)).fetchone()
            info = None
            if lic:
                status = lic["status"]
                if status == "active" and lic["expires_at"] and lic["expires_at"] < now:
                    status = "expired"
                ndev = c.execute("SELECT COUNT(*) n FROM devices WHERE license_id=? AND active=1",
                                 (lic["id"],)).fetchone()["n"]
                info = {"plan": lic["plan"], "status": status, "max_devices": lic["max_devices"],
                        "devices_active": ndev, "expires_at": lic["expires_at"]}
            out.append({"username": u["username"], "email": u["email"],
                        "is_admin": bool(u["is_admin"]), "created_at": u["created_at"], "license": info})
        return out


def thong_ke_admin():
    """Thống kê tổng cho admin: số user, license theo trạng thái, thiết bị hoạt động, theo gói."""
    now = int(time.time())
    with _lock, closing(_conn()) as c:
        so_user = c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        rows = c.execute("SELECT status, expires_at, plan FROM licenses").fetchall()
        active = expired = revoked = 0
        theo_goi = {}
        for r in rows:
            st = r["status"]
            if st == "active" and r["expires_at"] and r["expires_at"] < now:
                st = "expired"
            if st == "active":
                active += 1
                theo_goi[r["plan"]] = theo_goi.get(r["plan"], 0) + 1
            elif st == "revoked":
                revoked += 1
            else:
                expired += 1
        thiet_bi = c.execute("SELECT COUNT(*) n FROM devices WHERE active=1").fetchone()["n"]
    return {"so_user": so_user, "license_active": active, "license_expired": expired,
            "license_revoked": revoked, "thiet_bi_hoat_dong": thiet_bi, "theo_goi": theo_goi}


def thong_ke_churn(window_secs=7 * 24 * 3600, min_hwid=3):
    """BÁO CÁO churn HWID cho admin (READ-ONLY, không chặn gì): các license đã activate >= min_hwid HWID
    KHÁC NHAU trong cửa sổ -> dấu hiệu chia sẻ tài khoản / xoay máy. Admin xem rồi tự revoke/gỡ thiết bị.
    Dữ liệu lấy từ bảng activations đã log sẵn (không thêm ghi gì)."""
    now = int(time.time())
    since = now - max(1, int(window_secs))
    with _lock, closing(_conn()) as c:
        rows = c.execute(
            "SELECT a.license_id AS lid, COUNT(DISTINCT a.hwid) AS n_hwid, "
            "SUM(CASE WHEN a.action='activate' THEN 1 ELSE 0 END) AS n_act, "
            "SUM(CASE WHEN a.action='deactivate' THEN 1 ELSE 0 END) AS n_deact, "
            "MAX(a.at) AS last_at "
            "FROM activations a WHERE a.at>=? AND a.license_id IS NOT NULL "
            "GROUP BY a.license_id HAVING COUNT(DISTINCT a.hwid)>=? "
            "ORDER BY n_hwid DESC, n_deact DESC", (since, int(min_hwid))).fetchall()
        out = []
        for r in rows:
            lic = c.execute("SELECT user_id FROM licenses WHERE id=?", (r["lid"],)).fetchone()
            uname = ""
            if lic:
                u = c.execute("SELECT username FROM users WHERE id=?", (lic["user_id"],)).fetchone()
                uname = u["username"] if u else ""
            out.append({"username": uname, "license_id": r["lid"], "so_hwid": r["n_hwid"],
                        "so_activate": r["n_act"], "so_deactivate": r["n_deact"], "last_at": r["last_at"]})
        return out


def xoa_user(username):
    """Xoá user (cascade: license/device/session). Trả True nếu có xoá."""
    with _lock, closing(_conn()) as c:
        cur = c.execute("DELETE FROM users WHERE username=?", (_chuan_username(username),))
        c.execute("DELETE FROM activations WHERE license_id NOT IN (SELECT id FROM licenses)")
        c.commit()
        return cur.rowcount > 0


# ----------------- Signed offline token (HMAC) -----------------
def _ky_token(user_id, lic, hwid):
    """Tạo token offline để app kiểm license khi mất mạng trong grace period."""
    _plan = (lic["plan"] or "free")
    _trial_exp = ((lic["created_at"] or 0) + _TRIAL_GIAY) if _plan == "free" else 0
    payload = {
        "uid": user_id, "lid": lic["id"], "hwid": hwid,
        "plan": lic["plan"], "tier": _tier(lic), "lic_exp": lic["expires_at"],
        "trial_exp": _trial_exp,
        "exp": int(time.time()) + _OFFLINE_TTL,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = hmac.new(_lay_secret(), raw, hashlib.sha256).hexdigest()
    body = _b64(raw)
    return f"{body}.{sig}"


def xac_minh_token(token, hwid=None):
    """Xác minh token offline (chữ ký + hạn + đúng hwid). Trả payload | None. App desktop dùng hàm này."""
    try:
        body, sig = token.split(".", 1)
        raw = _unb64(body)
        good = hmac.new(_lay_secret(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(good, sig):
            return None
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    if payload.get("exp", 0) < int(time.time()):
        return None
    if hwid is not None and payload.get("hwid") != hwid:
        return None
    return payload


def _b64(b: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _unb64(s: str) -> bytes:
    import base64
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _thong_tin_license(lic, hwid):
    return {
        "plan": lic["plan"], "tier": _tier(lic), "status": "active",
        "max_devices": lic["max_devices"],
        "expires_at": lic["expires_at"], "hwid": hwid,
    }


def dang_ky_thiet_bi(username, mat_khau, email, hwid, device_name="", os_name=""):
    """Đăng ký + tự cấp gói FREE + GẮN MÁY (hwid) trong 1 bước.
    Tài khoản gắn chặt với máy này (max_devices=1). Trả (session, info) | (None, lỗi)."""
    # 1 MÁY = 1 TÀI KHOẢN: chặn TRƯỚC khi tạo user nếu máy này đã gắn tài khoản khác (tránh user mồ côi)
    hwid_norm = (hwid or "").strip()
    if hwid_norm:
        with _lock, closing(_conn()) as c:
            if c.execute("SELECT 1 FROM devices d JOIN licenses li ON li.id=d.license_id "
                         "WHERE d.hwid=? AND d.active=1 LIMIT 1", (hwid_norm,)).fetchone():
                return None, "Máy này đã được đăng ký với một tài khoản khác. Mỗi máy chỉ dùng được 1 tài khoản."
    uid, err = dang_ky(username, mat_khau, email)
    if err:
        return None, err
    cap_license(uid, "free", 1, 0)   # gói free, 1 thiết bị, vĩnh viễn
    tok, info = kich_hoat_thiet_bi(uid, hwid, device_name, os_name)
    if not tok:
        return None, info
    sess, e2 = dang_nhap(username, mat_khau)
    if e2:
        return None, e2
    sess["license_token"] = tok
    sess["info"] = info
    return sess, None
