# -*- coding: utf-8 -*-
"""
Sinh HARDWARE ID (HWID) ổn định cho từng máy — dùng để ràng buộc license theo thiết bị.

Đây là module CHẠY TRÊN MÁY CLIENT (app desktop), gửi HWID lên license server.
Trên Windows kết hợp các định danh ổn định:
  - MachineGuid (registry HKLM\\SOFTWARE\\Microsoft\\Cryptography\\MachineGuid)
  - Volume serial ổ C:
rồi băm SHA-256 → chuỗi hex 64 ký tự. KHÔNG gửi thông tin máy thô lên server.

Có fallback đa nền tảng (uuid.getnode) để dev/test không phải Windows vẫn chạy.
"""
import hashlib
import os
import platform
import subprocess
import uuid


def _machine_guid_windows() -> str:
    """Đọc MachineGuid từ registry (ổn định, không đổi khi cài lại app)."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Cryptography") as k:
            val, _ = winreg.QueryValueEx(k, "MachineGuid")
            return str(val).strip()
    except Exception:
        return ""


def _volume_serial_windows() -> str:
    """Serial ổ hệ thống (thêm 1 yếu tố). Lỗi -> rỗng."""
    try:
        out = subprocess.run(
            ["cmd", "/c", "vol", os.environ.get("SystemDrive", "C:")],
            capture_output=True, text=True, timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for line in (out.stdout or "").splitlines():
            line = line.strip()
            # Dòng dạng "Volume Serial Number is XXXX-XXXX"
            if "-" in line and line.split()[-1].count("-") == 1 and len(line.split()[-1]) <= 9:
                return line.split()[-1]
    except Exception:
        pass
    return ""


def lay_hwid() -> str:
    """Trả HWID = SHA-256 hex của các định danh máy. Ổn định giữa các lần chạy."""
    parts = []
    if platform.system() == "Windows":
        parts.append(_machine_guid_windows())
        parts.append(_volume_serial_windows())
    # MAC (uuid.getnode) CHỈ dùng khi KHÔNG có MachineGuid (non-Windows/dev) — KHÔNG trộn vào HWID
    # Windows vì MAC ĐỔI theo VPN/Tailscale/đổi card mạng → HWID TRÔI → mất binding license (đã gặp:
    # laptop Tailscale nhảy HWID 194d→92b4 → "máy đã gắn tài khoản khác"). MachineGuid + volume serial
    # đã đủ ổn định + duy nhất cho ràng buộc thiết bị.
    if not any(parts):
        parts.append(f"{uuid.getnode():012x}")
    parts.append(platform.machine())
    raw = "|".join(p for p in parts if p)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def lay_hwid_cu() -> str:
    """HWID theo CÔNG THỨC CŨ (≤v0.1.27): CÓ trộn MAC (uuid.getnode). CHỈ để DI CƯ binding cũ sang
    HWID mới ổn định (cùng máy vật lý) — KHÔNG dùng gắn mới. Trả "" nếu trùng lay_hwid() (đỡ gửi thừa)."""
    parts = []
    if platform.system() == "Windows":
        parts.append(_machine_guid_windows())
        parts.append(_volume_serial_windows())
    parts.append(f"{uuid.getnode():012x}")     # MAC — công thức cũ luôn trộn
    parts.append(platform.machine())
    raw = "|".join(p for p in parts if p)
    cu = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return "" if cu == lay_hwid() else cu


def thong_tin_thiet_bi() -> dict:
    """Tên + OS để hiển thị trong danh sách thiết bị (không nhạy cảm)."""
    try:
        ten = platform.node() or "May-khong-ten"
    except Exception:
        ten = "May-khong-ten"
    return {
        "hwid": lay_hwid(),
        "device_name": ten,
        "os": f"{platform.system()} {platform.release()}".strip(),
    }


if __name__ == "__main__":
    info = thong_tin_thiet_bi()
    # Chạy 2 lần để chứng minh HWID ỔN ĐỊNH (không đổi)
    h2 = lay_hwid()
    print("HWID      :", info["hwid"])
    print("Lan 2     :", h2)
    print("On dinh   :", "OK" if info["hwid"] == h2 else "LOI - khong on dinh")
    print("Device    :", info["device_name"])
    print("OS        :", info["os"])
