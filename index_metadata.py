# -*- coding: utf-8 -*-
"""Index nhẹ SQLite: đánh dấu video ĐÃ TẢI/ĐÃ CÀO để Xem-trước gắn badge "✓ đã tải".

KHÔNG lọc cứng (tránh bug "0 bài" — chỉ ĐÁNH DẤU, vẫn hiện trong kết quả). DB ở userData
(bền qua NSIS update như khach_db). Khóa = (platform, key) với key = url||id của bài (đúng cái
checkbox preview gửi đi: data-id = it.url || it.id).
"""
import os
import sqlite3
import time


def _db_path():
    # userData (bền qua update) — như khach_db: KHACH_DB_DIR > LIC_CACHE_DIR > thư mục file (dev)
    d = (os.environ.get("KHACH_DB_DIR") or os.environ.get("LIC_CACHE_DIR")
         or os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(d, "metadata_index.db")


def _conn():
    c = sqlite3.connect(_db_path(), timeout=5)
    c.execute(
        "CREATE TABLE IF NOT EXISTS da_tai "
        "(platform TEXT, k TEXT, ts INTEGER, PRIMARY KEY(platform, k))"
    )
    return c


def danh_dau(platform, keys):
    """Đánh dấu danh sách key (url||id) ĐÃ TẢI của 1 nền. Bỏ qua lỗi (index chỉ phụ trợ)."""
    keys = [str(k).strip() for k in (keys or []) if str(k).strip()]
    if not keys:
        return
    try:
        c = _conn()
        now = int(time.time())
        c.executemany(
            "INSERT OR REPLACE INTO da_tai(platform, k, ts) VALUES(?,?,?)",
            [(platform, k, now) for k in keys],
        )
        c.commit()
        c.close()
    except Exception:
        pass


def da_tai_set(platform):
    """Set key (url||id) đã tải của 1 nền — để preview gắn badge. '' an toàn khi lỗi."""
    try:
        c = _conn()
        rows = c.execute("SELECT k FROM da_tai WHERE platform=?", (platform,)).fetchall()
        c.close()
        return set(r[0] for r in rows)
    except Exception:
        return set()
