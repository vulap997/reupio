# -*- coding: utf-8 -*-
"""RAM/CPU máy — dùng CHUNG cho web_app.py (tab gợi ý máy), render_worker.py (tự-restart khi RAM cao)
và localize.py (_ResMon profiling). Trước đây mỗi file tự viết lại GlobalMemoryStatusEx riêng (rule.md
mục 5 bắt buộc component hóa khi có ≥2 bản trùng logic).

Windows: ctypes.windll (y hệt code cũ, KHÔNG đổi hành vi).
macOS/Linux: subprocess sysctl/vm_stat + os.getloadavg() — KHÔNG thêm dependency psutil, giữ đúng
tinh thần "dep-free" mà localize.py._ResMon đã ghi rõ (venv production không có psutil/pynvml).
"""

import ctypes
import os
import re
import subprocess
import sys


def ram_gb_tong() -> float:
    """Tổng RAM vật lý (GB). Lỗi/không xác định -> 0.0."""
    try:
        if sys.platform == "win32":
            class _MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            ms = _MS(); ms.dwLength = ctypes.sizeof(_MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
            return round(ms.ullTotalPhys / (1024 ** 3), 1)
        if sys.platform == "darwin":
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=3)
            return round(int(out.stdout.strip()) / (1024 ** 3), 1)
        with open("/proc/meminfo", "r") as f:      # Linux
            for line in f:
                if line.startswith("MemTotal:"):
                    return round(int(line.split()[1]) * 1024 / (1024 ** 3), 1)
    except Exception:
        pass
    return 0.0


def ram_pct_dung() -> int:
    """% RAM đang dùng (0-100). Lỗi/không xác định -> 0."""
    try:
        if sys.platform == "win32":
            class _M(ctypes.Structure):
                _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong)] + \
                           [(c, ctypes.c_ulonglong) for c in "abcdefg"]
            m = _M(); m.l = ctypes.sizeof(m)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return int(m.load)
        if sys.platform == "darwin":
            out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=3).stdout
            page_m = re.search(r"page size of (\d+) bytes", out)
            page_size = int(page_m.group(1)) if page_m else 4096
            pages = {}
            for line in out.splitlines():
                if ":" not in line:
                    continue
                k, v = line.split(":", 1)
                v = v.strip().rstrip(".")
                if v.isdigit():
                    pages[k.strip()] = int(v)
            used = (pages.get("Pages active", 0) + pages.get("Pages wired down", 0) +
                    pages.get("Pages occupied by compressor", 0))
            total_gb = ram_gb_tong()
            if total_gb <= 0:
                return 0
            return int(round(used * page_size / (1024 ** 3) / total_gb * 100))
        info = {}                                  # Linux
        with open("/proc/meminfo", "r") as f:
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    info[parts[0].strip()] = int(parts[1].strip().split()[0])
        total = info.get("MemTotal", 0)
        if total <= 0:
            return 0
        avail = info.get("MemAvailable", total)
        return int(round((total - avail) / total * 100))
    except Exception:
        pass
    return 0


class TheoDoiCpu:
    """Đo % CPU theo delta giữa 2 lần gọi liên tiếp (thay _ResMon._prev cũ trong localize.py).
    Windows: GetSystemTimes delta (y hệt code cũ). macOS/Linux: os.getloadavg() xấp xỉ theo số nhân
    (đủ dùng cho mục đích profiling nội bộ, không hiển thị cho khách)."""

    def __init__(self):
        self._prev = None

    def phan_tram(self):
        """Trả % CPU (int) hoặc None nếu chưa đo được / lỗi."""
        try:
            if sys.platform == "win32":
                i = ctypes.c_ulonglong(); k = ctypes.c_ulonglong(); u = ctypes.c_ulonglong()
                ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(i), ctypes.byref(k), ctypes.byref(u))
                cur = (i.value, k.value, u.value)
                cpu = None
                if self._prev:
                    di = cur[0] - self._prev[0]
                    tot = (cur[1] - self._prev[1]) + (cur[2] - self._prev[2])
                    if tot > 0:
                        cpu = round(100.0 * (tot - di) / tot)   # kernelTime BAO GỒM idleTime
                self._prev = cur
                return cpu
            la = os.getloadavg()[0]
            n = os.cpu_count() or 1
            return int(round(min(100.0, la / n * 100)))
        except Exception:
            return None
