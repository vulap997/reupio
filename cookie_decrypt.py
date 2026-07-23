# -*- coding: utf-8 -*-
"""Giải mã cookie Chromium (v10: DPAPI + AES-256-GCM) KHÔNG mở browser.

Dùng cho chế độ cào API-only (httpx + cookie) — bỏ Playwright headless để nền tảng
(bilibili) không phát hiện fingerprint trình duyệt tự động rồi vô hiệu hóa phiên login.

Chỉ Windows (DPAPI). v20 App-Bound Encryption CHƯA hỗ trợ (gate đã verify máy khách = v10,
Local State.os_crypt.encrypted_key prefix = b'DPAPI'). Nếu gặp v20 sẽ raise rõ ràng.

Public API:
    doc_cookies(user_data_dir, host_substr) -> {name: value}
    cookie_header(user_data_dir, host_substr) -> "name=value; name=value"
    CookieManager().get_cookie(platform) -> cookie_header cho nền (bilibili/douyin/...)
"""

import os
import json
import base64
import sqlite3
import shutil
import tempfile
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _dpapi_unprotect(blob: bytes) -> bytes:
    """CryptUnprotectData (DPAPI per-user) qua ctypes — không cần pywin32."""
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf_in = ctypes.create_string_buffer(blob, len(blob))
    blob_in = DATA_BLOB(len(blob), ctypes.cast(buf_in, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    )
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _aes_key(user_data_dir: str) -> bytes:
    """Local State -> os_crypt.encrypted_key (base64) -> bỏ prefix 'DPAPI' -> DPAPI giải -> AES-256 key."""
    ls = os.path.join(user_data_dir, "Local State")
    with open(ls, "r", encoding="utf-8") as f:
        data = json.load(f)
    enc = base64.b64decode(data["os_crypt"]["encrypted_key"])
    if enc[:5] != b"DPAPI":
        raise ValueError(
            "Cookie KHÔNG phải v10 DPAPI (có thể v20 App-Bound Encryption) — chưa hỗ trợ"
        )
    return _dpapi_unprotect(enc[5:])


def _decrypt_value(enc: bytes, key: bytes) -> str:
    """Giải 1 encrypted_value. v10/v11 = prefix(3) + nonce(12) + ciphertext + tag(16), AES-256-GCM."""
    if not enc:
        return ""
    if enc[:3] in (b"v10", b"v11"):
        nonce = enc[3:15]
        ct_tag = enc[15:]  # ciphertext + 16-byte GCM tag (AESGCM nhận chung)
        try:
            return AESGCM(key).decrypt(nonce, ct_tag, None).decode("utf-8", "replace")
        except Exception:
            return ""
    # Cookie cũ DPAPI thuần (không prefix, Chrome < 80)
    try:
        return _dpapi_unprotect(enc).decode("utf-8", "replace")
    except Exception:
        return ""


def doc_cookies(user_data_dir: str, host_substr: str) -> dict:
    """Trả {name: value} cookie đã giải mã cho host khớp host_substr. KHÔNG mở browser.

    Copy Cookies + -wal/-shm ra temp (tránh khóa sqlite khi Chromium đang chạy), đọc trực tiếp.
    """
    ck = os.path.join(user_data_dir, "Default", "Network", "Cookies")
    if not os.path.isfile(ck):
        return {}
    key = _aes_key(user_data_dir)
    # Retry chống khóa thoáng qua: app nền (kiem_tra_login badge) có thể mở profile bili giây lát
    # -> copy bắt đúng lúc đó = file dở -> "no such table". Thử lại vài lần với khoảng nghỉ ngắn.
    rows = None
    for attempt in range(4):
        td = tempfile.mkdtemp(prefix="ckdec_")
        b = os.path.join(td, "Cookies")
        try:
            shutil.copyfile(ck, b)
            for ext in ("-wal", "-shm"):
                if os.path.exists(ck + ext):
                    try:
                        shutil.copyfile(ck + ext, b + ext)
                    except Exception:
                        pass
            con = sqlite3.connect(b)
            try:
                rows = con.execute(
                    "SELECT name, encrypted_value FROM cookies WHERE host_key LIKE ?",
                    ("%" + host_substr + "%",),
                ).fetchall()
                break  # đọc được bảng (kể cả 0 dòng khớp) -> xong
            except sqlite3.OperationalError:
                rows = None  # "no such table" = khóa/copy dở -> thử lại
            finally:
                con.close()
        except (OSError, sqlite3.Error):
            # PermissionError (Errno 13): file Cookies bị KHÓA ĐỘC QUYỀN (Chromium/badge-check
            # mở profile giây lát) -> copyfile fail. NUỐT + thử lại — KHÔNG để crash preview/crawl.
            rows = None
        finally:
            shutil.rmtree(td, ignore_errors=True)
        if attempt < 3:
            time.sleep(0.6)
    if not rows:
        return {}
    out = {}
    for name, enc in rows:
        if enc:
            val = _decrypt_value(bytes(enc), key)
            if val:
                out[name] = val
    return out


def cookie_header(user_data_dir: str, host_substr: str) -> str:
    """Trả chuỗi 'name=value; name=value' cho httpx header Cookie. '' nếu không có."""
    c = doc_cookies(user_data_dir, host_substr)
    return "; ".join("%s=%s" % (k, v) for k, v in c.items())


class CookieManager:
    """Facade: get_cookie(platform) -> Cookie header. Gộp resolve profile + decrypt 1 chỗ
    để các nền dùng chung (giảm nợ kỹ thuật). Phase 01 chỉ bili chạy thật."""

    # platform -> tên thư mục profile (<X>_user_data_dir) + host lọc cookie
    _PLAT = {
        "bilibili": ("bili", "bilibili.com"),
        "bili": ("bili", "bilibili.com"),
        "douyin": ("dy", "douyin.com"),
        "dy": ("dy", "douyin.com"),
        "xhs": ("xhs", "xiaohongshu.com"),
        "weibo": ("wb", "weibo.com"),
        "wb": ("wb", "weibo.com"),
    }

    def __init__(self, browser_data_dir: str = None):
        self.bd = (
            browser_data_dir
            or os.environ.get("MC_BROWSER_DATA_DIR")
            or os.path.join(os.path.dirname(os.path.abspath(__file__)), "MediaCrawler", "browser_data")
        )

    def profile_dir(self, platform: str) -> str:
        if platform not in self._PLAT:
            raise ValueError("Nền không hỗ trợ: %s" % platform)
        udd, _ = self._PLAT[platform]
        return os.path.join(self.bd, "%s_user_data_dir" % udd)

    def get_cookie(self, platform: str) -> str:
        if platform not in self._PLAT:
            raise ValueError("Nền không hỗ trợ: %s" % platform)
        _, host = self._PLAT[platform]
        return cookie_header(self.profile_dir(platform), host)


if __name__ == "__main__":
    # CLI test: python cookie_decrypt.py <platform>  -> in cookie (CHE giá trị) để kiểm decrypt đúng
    import sys

    plat = sys.argv[1] if len(sys.argv) > 1 else "bilibili"
    cm = CookieManager()
    try:
        cookies = doc_cookies(cm.profile_dir(plat), cm._PLAT[plat][1])
    except Exception as e:
        print("LỖI:", e)
        sys.exit(1)
    print("Nền:", plat, "| profile:", cm.profile_dir(plat))
    print("Số cookie giải mã:", len(cookies))
    for name, val in cookies.items():
        # CHE giá trị (bảo mật) — chỉ in độ dài + định dạng để xác minh decrypt đúng
        printable = all(32 <= ord(c) < 127 for c in val[:64]) if val else False
        fmt = "ascii-OK" if printable else "GARBAGE?"
        extra = ""
        if name == "bili_jct":
            extra = "(32hex)" if (len(val) == 32 and all(c in "0123456789abcdef" for c in val)) else "(?)"
        if name == "DedeUserID":
            extra = "(digits=%s)" % val if val.isdigit() else "(?)"
        print("  %-16s len=%-4d %s %s" % (name, len(val), fmt, extra))
