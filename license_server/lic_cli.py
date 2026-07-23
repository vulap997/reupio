# -*- coding: utf-8 -*-
"""
CLI license cho Electron gọi (qua Python venv). In JSON ra stdout, exit code 0/1.
Dùng lại hwid.py + lic_client.py + lic_db.xac_minh_token (đã test). KHÔNG chứa secret server.

Lệnh:
  python lic_cli.py status                 -> {ok, licensed, source, username?, info?, msg?}
  python lic_cli.py login   --user U --pass P [--server URL]
  python lic_cli.py activate [--server URL]   (HWID tự lấy của máy)
  python lic_cli.py check    [--server URL]
  python lic_cli.py deactivate [--server URL]
  python lic_cli.py devices  [--server URL]
  python lic_cli.py logout
  python lic_cli.py hwid                    -> in thông tin thiết bị

Mặc định server lấy từ biến môi trường LIC_SERVER (vd http://your-server:8900).
"""
import argparse
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import hwid as hwid_mod
import lic_client
import lic_db


def _out(obj, ok=True):
    print(json.dumps(obj, ensure_ascii=False))
    sys.exit(0 if ok else 1)


def _loi_ket_noi(e):
    """Lỗi kết nối -> thông báo thân thiện (KHÔNG hiện WinError thô cho người dùng)."""
    try:
        print(f"[lic_cli] connect error: {e}", file=sys.stderr)   # giữ chi tiết cho log debug
    except Exception:
        pass
    return ("Không kết nối được máy chủ. Kiểm tra kết nối mạng "
            "(hoặc tường lửa/diệt virus đang chặn) rồi thử lại.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["status", "register", "login", "activate", "check",
                                    "deactivate", "devices", "logout", "hwid"])
    ap.add_argument("--user", default="")
    ap.add_argument("--pass", dest="password", default="")
    ap.add_argument("--server", default=os.environ.get("LIC_SERVER", lic_client.DEFAULT_BASE))
    a = ap.parse_args()

    base = a.server
    info = hwid_mod.thong_tin_thiet_bi()
    hw = info["hwid"]
    hw_cu = hwid_mod.lay_hwid_cu()   # HWID cũ (có MAC) -> server tự DI CƯ binding cũ sang HWID mới ổn định

    if a.cmd == "hwid":
        _out({"ok": True, **info})

    if a.cmd == "logout":
        lic_client.dang_xuat()
        _out({"ok": True})

    if a.cmd == "register":
        if not a.user or not a.password:
            _out({"ok": False, "msg": "Thiếu --user/--pass"}, ok=False)
        try:
            ok, err = lic_client.dang_ky(a.user, a.password, hw, info["device_name"], info["os"], base=base, hwid_cu=hw_cu)
        except Exception as e:
            _out({"ok": False, "msg": _loi_ket_noi(e)}, ok=False)
        _out({"ok": ok, "msg": err} if not ok else {"ok": True, "hwid": hw}, ok=ok)

    if a.cmd == "login":
        if not a.user or not a.password:
            _out({"ok": False, "msg": "Thiếu --user/--pass"}, ok=False)
        try:
            ok, err = lic_client.dang_nhap(a.user, a.password, base=base)
        except Exception as e:
            _out({"ok": False, "msg": _loi_ket_noi(e)}, ok=False)
        _out({"ok": ok, "msg": err} if not ok else {"ok": True}, ok=ok)

    if a.cmd == "activate":
        try:
            ok, err = lic_client.kich_hoat(hw, info["device_name"], info["os"], base=base, hwid_cu=hw_cu)
        except Exception as e:
            _out({"ok": False, "msg": _loi_ket_noi(e)}, ok=False)
        _out({"ok": ok, "msg": err} if not ok else {"ok": True, "hwid": hw}, ok=ok)

    if a.cmd == "deactivate":
        try:
            data, _ = lic_client._post(base, "/license/deactivate",
                                       {"hwid": hw}, token=lic_client._doc_cache().get("session"))
        except Exception as e:
            _out({"ok": False, "msg": _loi_ket_noi(e)}, ok=False)
        _out(data, ok=bool(data.get("ok")))

    if a.cmd == "devices":
        try:
            tok = lic_client._doc_cache().get("session")
            import urllib.request
            req = urllib.request.Request(base + "/license/devices", headers={"X-Token": tok or ""})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read().decode("utf-8"))
        except Exception as e:
            _out({"ok": False, "msg": _loi_ket_noi(e)}, ok=False)
        _out(data, ok=bool(data.get("ok")))

    if a.cmd in ("check", "status"):
        hop_le, nguon, err = lic_client.kiem_tra(hw, base=base, offline_verifier=lic_db.xac_minh_token, hwid_cu=hw_cu)
        cache = lic_client._doc_cache()
        # tier gate lấy từ cache["tier"] (đã bind vào token server ký) — KHÔNG tin info sửa tay.
        tier = (cache.get("tier") if hop_le else "free") or "free"
        # lohapage: cờ tool LohaPage (server ký vào token) → app gate tab Kênh nguồn/Đăng bài. Vắng = chưa mua = False.
        lohapage = bool(cache.get("lohapage")) if hop_le else False
        _out({"ok": True, "licensed": hop_le, "source": nguon,
              "username": cache.get("username", ""), "tier": tier, "lohapage": lohapage,
              "info": cache.get("info"), "msg": err}, ok=True)


if __name__ == "__main__":
    main()
