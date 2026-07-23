# -*- coding: utf-8 -*-
"""
BẢO MẬT API KEY bằng Windows DPAPI (qua ctypes — KHÔNG cần cài thư viện ngoài).

Ý tưởng: key được mã hoá GẮN VỚI TÀI KHOẢN WINDOWS đang đăng nhập.
  • Không bao giờ lưu key dạng plaintext ra file.
  • Copy file mã hoá (key_store.dat) sang máy khác / user Windows khác → KHÔNG giải mã được.
  • KHÔNG có "mật khẩu" nào nằm trong code để bị lộ (khóa giải mã là phiên Windows).

Lưu tại: key_store.dat — JSON dạng {ten_dich_vu: base64(blob đã mã hoá DPAPI)}.
File này đã được .gitignore (TUYỆT ĐỐI không commit).

Tự động chuyển (migrate) key cũ đang để plaintext (groq_config.json / ai_config.json)
sang dạng mã hoá rồi XOÁ bản plaintext, để không còn key lộ trên đĩa.

Dùng:
    import bao_mat_key
    bao_mat_key.luu_key("gsk_...")     # mã hoá & lưu
    key = bao_mat_key.doc_key()        # giải mã khi cần gọi API
    bao_mat_key.co_key()               # đã có key chưa?
    bao_mat_key.xoa_key()              # xoá key

LƯU Ý: DPAPI chỉ có trên Windows. Tool này là app Windows nên đây là lựa chọn an toàn nhất.
"""

import base64
import ctypes
import json
import os
from ctypes import wintypes

THU_MUC_GOC = os.path.dirname(os.path.abspath(__file__))
# key_store.dat PHẢI ở userData (LIC_CACHE_DIR): app-src = Program Files READ-ONLY → ghi vào đó PermissionError
# (500 khi thêm key AI) + bị NSIS update xoá. Dev (không có LIC_CACHE_DIR) → app-src như cũ. Di cư file cũ 1 lần.
_lic_dir = (os.environ.get("LIC_CACHE_DIR") or "").strip()
FILE_STORE = os.path.join(_lic_dir, "key_store.dat") if _lic_dir else os.path.join(THU_MUC_GOC, "key_store.dat")
if _lic_dir:
    try:
        _old_store = os.path.join(THU_MUC_GOC, "key_store.dat")
        if not os.path.exists(FILE_STORE) and os.path.isfile(_old_store):
            import shutil as _sh
            os.makedirs(_lic_dir, exist_ok=True)
            _sh.copyfile(_old_store, FILE_STORE)   # di cư key đã lưu từ app-src → userData
    except Exception:
        pass

# Tên dịch vụ mặc định + danh sách file plaintext cũ để migrate (path, field)
TEN_MAC_DINH = "groq"
_LEGACY = {
    "groq": [
        (os.path.join(THU_MUC_GOC, "groq_config.json"), "api_key"),
        (os.path.join(THU_MUC_GOC, "ai_config.json"), "groq_key"),
    ],
}


# ----------------- DPAPI qua ctypes -----------------
class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


_crypt32 = ctypes.windll.crypt32
_kernel32 = ctypes.windll.kernel32
_crypt32.CryptProtectData.restype = wintypes.BOOL
_crypt32.CryptUnprotectData.restype = wintypes.BOOL


def _blob_vao(data: bytes) -> _DATA_BLOB:
    buf = ctypes.create_string_buffer(data, len(data))
    return _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _blob_ra(blob: _DATA_BLOB) -> bytes:
    out = ctypes.string_at(blob.pbData, blob.cbData)
    _kernel32.LocalFree(blob.pbData)
    return out


def _ma_hoa(thong_tin: bytes) -> bytes:
    """Mã hoá bằng DPAPI (gắn với user Windows hiện tại)."""
    vao = _blob_vao(thong_tin)
    ra = _DATA_BLOB()
    # entropy phụ để tăng tính riêng biệt cho ứng dụng này
    ent = _blob_vao(b"toolcaovideo-v1")
    ok = _crypt32.CryptProtectData(ctypes.byref(vao), None, ctypes.byref(ent),
                                   None, None, 0, ctypes.byref(ra))
    if not ok:
        raise OSError("DPAPI CryptProtectData thất bại")
    return _blob_ra(ra)


def _giai_ma(thong_tin: bytes) -> bytes:
    """Giải mã DPAPI. Lỗi nếu file bị copy từ máy/user khác."""
    vao = _blob_vao(thong_tin)
    ra = _DATA_BLOB()
    ent = _blob_vao(b"toolcaovideo-v1")
    ok = _crypt32.CryptUnprotectData(ctypes.byref(vao), None, ctypes.byref(ent),
                                     None, None, 0, ctypes.byref(ra))
    if not ok:
        raise OSError("DPAPI CryptUnprotectData thất bại")
    return _blob_ra(ra)


# ----------------- Lưu trữ key_store.dat -----------------
def _doc_store() -> dict:
    if os.path.exists(FILE_STORE):
        try:
            with open(FILE_STORE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _ghi_store(d: dict):
    with open(FILE_STORE, "w", encoding="utf-8") as f:
        json.dump(d, f)


# ----------------- API công khai -----------------
def luu_key(key: str, ten: str = TEN_MAC_DINH):
    """Mã hoá & lưu key. Truyền chuỗi rỗng để xoá."""
    key = (key or "").strip()
    store = _doc_store()
    if key:
        blob = _ma_hoa(key.encode("utf-8"))
        store[ten] = base64.b64encode(blob).decode("ascii")
    else:
        store.pop(ten, None)
    _ghi_store(store)


def doc_key(ten: str = TEN_MAC_DINH) -> str:
    """Giải mã & trả key. Nếu chưa có → thử migrate từ file plaintext cũ."""
    enc = _doc_store().get(ten)
    if enc:
        try:
            return _giai_ma(base64.b64decode(enc)).decode("utf-8")
        except Exception:
            # Không giải mã được (vd copy sang máy khác) → coi như chưa có
            return ""
    return _migrate(ten)


def co_key(ten: str = TEN_MAC_DINH) -> bool:
    return bool(doc_key(ten))


def xoa_key(ten: str = TEN_MAC_DINH):
    luu_key("", ten)


def _migrate(ten: str) -> str:
    """Nhập key cũ đang để plaintext → mã hoá lại → XOÁ bản plaintext."""
    for path, field in _LEGACY.get(ten, []):
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                k = (json.load(f).get(field) or "").strip()
        except Exception:
            k = ""
        if k:
            try:
                luu_key(k, ten)        # mã hoá lưu trước
                os.remove(path)        # rồi mới xoá plaintext (an toàn)
            except OSError:
                pass
            return k
    return ""


if __name__ == "__main__":
    # Tự kiểm tra nhanh: mã hoá → giải mã round-trip
    test = "gsk_test_1234567890"
    luu_key(test, "_selftest")
    lay = doc_key("_selftest")
    xoa_key("_selftest")
    print("OK" if lay == test else f"LỖI: {lay!r} != {test!r}")
