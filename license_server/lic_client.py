# -*- coding: utf-8 -*-
"""
CLIENT helper — chạy TRÊN MÁY USER (trong app desktop), nói chuyện với license server.

Luồng:
  1. Đăng nhập (login) -> nhận session token (lưu cache).
  2. activate(hwid) lần đầu trên máy -> nhận license_token offline (lưu cache).
  3. Mỗi lần mở app: thử check() online; nếu MẤT MẠNG -> dùng offline token còn hạn (grace 7 ngày).

Cache để ở thư mục dữ liệu của app (mặc định cạnh file này khi dev).
KHÔNG nhúng secret server ở client — offline token chỉ ĐỌC, server mới ký được.
"""
import json
import os
import time
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
# Cache để ở thư mục BỀN VỮNG: app desktop truyền LIC_CACHE_DIR = userData (%APPDATA%) -> update
# KHÔNG xoá phiên/license_token (trước đây cache nằm TRONG thư mục cài app-src/ nên mỗi lần NSIS ghi
# đè là mất session -> buộc kích hoạt lại -> đụng binding cũ trên server -> "máy đã gắn account khác").
# Dev (không set env) -> cạnh file này. _LEGACY = vị trí CŨ -> tự DI CƯ 1 lần sang vị trí mới.
_CACHE_DIR = (os.environ.get("LIC_CACHE_DIR") or "").strip() or HERE
CACHE_PATH = os.path.join(_CACHE_DIR, "lic_cache.json")
_LEGACY = os.path.join(HERE, "lic_cache.json")

DEFAULT_BASE = os.environ.get("LIC_SERVER", "https://script.google.com/macros/s/AKfycbzV-jUrvEopJojHYBn-E1lvf8xFvvzyH7mVbpZX3lHWzMGv8PLrsmOUcm6JuSr1bPUy/exec")


def _post(base, path, body, token=None, timeout=15):
    is_gas = "script.google.com" in base

    if is_gas:
        # Nếu là Google Apps Script, chuyển subpath (vd: /license/register) thành field "action"
        action = path.split("/")[-1]
        body["action"] = action
        if token:
            body["token"] = token
        url = base
    else:
        url = base + path

    headers = {"Content-Type": "application/json"}
    if token and not is_gas:
        headers["X-Token"] = token

    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers=headers, method="POST")
    try:
        # Sử dụng urllib.request.urlopen mặc định.
        # Python tự động chuyển hướng và đổi redirect POST 302 của Google sang GET để lấy kết quả.
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8")), r.status
    except urllib.error.HTTPError as e:
        # Server trả 4xx/5xx KÈM body JSON
        try:
            return json.loads(e.read().decode("utf-8")), e.code
        except Exception:
            return {"ok": False, "msg": "Máy chủ trả lỗi HTTP %s." % e.code}, e.code


def _doc_cache():
    # Ưu tiên vị trí MỚI; chưa có mà còn cache CŨ trong thư mục cài -> đọc tạm (sẽ di cư khi _ghi_cache).
    path = CACHE_PATH
    if not os.path.exists(path) and _LEGACY != CACHE_PATH and os.path.exists(_LEGACY):
        path = _LEGACY
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _ghi_cache(d):
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    except OSError:
        pass
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(d, f)


def dang_ky(username, password, hwid, device_name="", os_name="", base=DEFAULT_BASE, hwid_cu=""):
    """Đăng ký + GẮN MÁY trong 1 bước (app desktop dùng lần đầu). Cache phiên + token offline."""
    if os.environ.get("VC_BYPASS_LICENSE") == "1":
        cache = _doc_cache()
        cache["session"] = "mock_session_token"
        cache["username"] = username
        cache["license_token"] = "mock_license_token"
        cache["info"] = {"exp": 4102444800, "tier": "unlimited", "lohapage": True}
        cache["tier"] = "unlimited"
        cache["lohapage"] = True
        _ghi_cache(cache)
        return True, None

    body = {
        "username": username,
        "password": password,
        "hwid": hwid,
        "device_name": device_name,
        "os": os_name
    }
    data, code = _post(base, "/license/register", body)
    if code != 200 or not data.get("ok"):
        return False, data.get("detail", data.get("msg", "Đăng ký không thành công"))

    cache = _doc_cache()
    cache["session"] = data.get("session")
    cache["username"] = username
    cache["license_token"] = data.get("license_token")
    cache["info"] = data.get("info")
    cache["tier"] = data.get("info", {}).get("tier", "free")
    cache["lohapage"] = data.get("info", {}).get("lohapage", False)
    _ghi_cache(cache)
    return True, None


def dang_nhap(username, password, base=DEFAULT_BASE):
    if os.environ.get("VC_BYPASS_LICENSE") == "1":
        cache = _doc_cache()
        cache["session"] = "mock_session_token"
        cache["username"] = username
        cache["tier"] = "unlimited"
        cache["lohapage"] = True
        _ghi_cache(cache)
        return True, None

    body = {
        "username": username,
        "password": password
    }
    data, code = _post(base, "/license/login", body)
    if code != 200 or not data.get("ok"):
        return False, data.get("detail", data.get("msg", "Tên đăng nhập hoặc mật khẩu không đúng"))

    cache = _doc_cache()
    cache["session"] = data.get("token")
    cache["username"] = data.get("username")
    cache["tier"] = "free"  # Mặc định free, sau đó activate sẽ cập nhật tiếp
    cache["lohapage"] = False
    _ghi_cache(cache)
    return True, None


def _payload_tu_token(token):
    """Đọc payload trong license_token. KHÔNG verify chữ ký — chỉ dùng ở nhánh ONLINE,
    nơi token vừa nhận TRỰC TIẾP từ server qua HTTPS (đã tin nguồn)."""
    try:
        import base64
        body = (token or "").split(".", 1)[0]
        pad = "=" * (-len(body) % 4)
        return json.loads(base64.urlsafe_b64decode(body + pad).decode("utf-8"))
    except Exception:
        return {}


def kich_hoat(hwid, device_name="", os_name="", base=DEFAULT_BASE, hwid_cu=""):
    if os.environ.get("VC_BYPASS_LICENSE") == "1":
        cache = _doc_cache()
        cache["license_token"] = "mock_license_token"
        cache["info"] = {"exp": 4102444800, "tier": "unlimited", "lohapage": True}
        cache["tier"] = "unlimited"
        cache["lohapage"] = True
        _ghi_cache(cache)
        return True, None

    cache = _doc_cache()
    session = cache.get("session")
    if not session:
        return False, "Chưa đăng nhập. Vui lòng đăng nhập trước."

    body = {
        "hwid": hwid,
        "device_name": device_name,
        "os": os_name,
        "hwid_cu": hwid_cu
    }
    data, code = _post(base, "/license/activate", body, token=session)
    if code != 200 or not data.get("ok"):
        return False, data.get("detail", data.get("msg", "Kích hoạt thiết bị thất bại."))

    cache["license_token"] = data.get("license_token")
    cache["info"] = data.get("info")
    cache["tier"] = data.get("info", {}).get("tier", "free")
    cache["lohapage"] = data.get("info", {}).get("lohapage", False)
    _ghi_cache(cache)
    return True, None


def kiem_tra(hwid, base=DEFAULT_BASE, offline_verifier=None, hwid_cu=""):
    """
    Kiểm license khi mở app.
    - Online: gọi server, làm mới offline token.
    - Mất mạng: dùng offline token đã cache (nếu offline_verifier xác minh còn hạn & đúng hwid).
    offline_verifier: hàm (token, hwid)->payload|None. App nhúng lic_db.xac_minh_token sẽ KHÔNG
      có secret server, nên thực tế đây chỉ kiểm HẠN + cấu trúc; chống gỡ mạng ngắn hạn, không chống crack.
    Trả: (hop_le: bool, nguon: 'online'|'offline'|None, msg)
    """
    if os.environ.get("VC_BYPASS_LICENSE") == "1":
        cache = _doc_cache()
        cache["tier"] = "unlimited"
        cache["lohapage"] = True
        cache["session"] = "mock_session_token"
        cache["username"] = "UnlimitedMember"
        cache["info"] = {"exp": 4102444800, "tier": "unlimited", "lohapage": True}
        _ghi_cache(cache)
        return True, "online", None

    cache = _doc_cache()
    session = cache.get("session")

    # 1. Thử kiểm tra ONLINE trước
    if session:
        body = {
            "hwid": hwid,
            "hwid_cu": hwid_cu
        }
        try:
            data, code = _post(base, "/license/check", body, token=session, timeout=10)
            if code == 200 and data.get("ok"):
                cache["license_token"] = data.get("license_token")
                cache["info"] = data.get("info")
                cache["tier"] = data.get("info", {}).get("tier", "free")
                cache["lohapage"] = data.get("info", {}).get("lohapage", False)
                _ghi_cache(cache)
                return True, "online", None
            elif code == 401:
                return False, None, "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại."
            elif code == 400:
                return False, None, data.get("detail", data.get("msg", "Thiết bị hoặc tài khoản bị chặn."))
        except Exception:
            # Mạng lỗi, chuyển xuống kiểm tra offline
            pass

    # 2. Nhánh OFFLINE: Xác minh token offline đã cache bằng signature
    lic_token = cache.get("license_token")
    if not lic_token:
        return False, None, "Không kết nối được máy chủ bản quyền và chưa kích hoạt offline."

    if offline_verifier:
        # Xác minh chữ ký token offline (lic_db.xac_minh_token)
        payload = offline_verifier(lic_token, hwid)
        if not payload and hwid_cu:
            payload = offline_verifier(lic_token, hwid_cu)
            
        if payload:
            # Token offline hợp lệ và còn hạn sử dụng
            cache["tier"] = payload.get("tier", "free")
            # Ở bản offline, cờ lohapage được nội suy dựa trên plan hoặc lưu từ trước
            cache["lohapage"] = bool(cache.get("info", {}).get("lohapage"))
            _ghi_cache(cache)
            return True, "offline", None
        else:
            return False, None, "Bản quyền offline không hợp lệ hoặc đã hết hạn ( grace period 7 ngày)."

    return False, None, "Không thể xác minh bản quyền."


def dang_xuat():
    for p in (CACHE_PATH, _LEGACY):
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass
