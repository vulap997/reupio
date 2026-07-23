# -*- coding: utf-8 -*-
"""Chẩn đoán vì sao Whisper không chạy GPU — kiểm TỪNG mắt xích nạp CUDA DLL + driver.
Dành cho AGENT/người dùng chạy trên MÁY KHÁCH (có GPU NVIDIA):
    MediaCrawler\\.venv\\Scripts\\python.exe chan_doan_gpu.py
Cuối có mục [KET LUAN] nói RÕ nguyên nhân + hành động cần làm. Gửi toàn bộ output cho dev nếu cần.
"""
import os
import sys
import glob
import subprocess
import importlib.util

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def p(*a):
    print(*a, flush=True)


p("=== CHAN DOAN GPU WHISPER ===")
p("python  :", sys.executable)
p("platform:", sys.platform)

# [0] Driver NVIDIA (nvidia-smi) — driver CŨ là thủ phạm hay gặp của 'cublas cannot be loaded'
p("\n[0] Driver NVIDIA (nvidia-smi):")
driver_ver = ""
smi_ok = False
try:
    r = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version",
                        "--format=csv,noheader"], capture_output=True, text=True,
                       creationflags=_NO_WINDOW, timeout=15)
    if r.returncode == 0 and (r.stdout or "").strip():
        smi_ok = True
        p("  " + r.stdout.strip().replace("\n", "\n  "))
        # driver_version = cot 2
        try:
            driver_ver = r.stdout.strip().splitlines()[0].split(",")[1].strip()
        except Exception:
            pass
    else:
        p("  nvidia-smi loi/khong co GPU:", (r.stderr or r.stdout or "?")[:120])
except Exception as e:
    p("  KHONG chay duoc nvidia-smi (chua cai driver NVIDIA?):", str(e)[:100])

# [1] Gói nvidia (pip) + thư mục bin + DLL có thật không
p("\n[1] Goi nvidia + DLL trong bin:")
dll_dirs = []
missing_pkgs = []
for pkg, dlls in (("nvidia.cuda_runtime", ["cudart64_12.dll"]),
                  ("nvidia.cublas", ["cublas64_12.dll", "cublasLt64_12.dll"]),
                  ("nvidia.cudnn", ["cudnn64_9.dll", "cudnn_ops64_9.dll"])):
    spec = importlib.util.find_spec(pkg)
    if not spec or not spec.submodule_search_locations:
        p(f"  {pkg:20s} -> KHONG CAI (find_spec=None)")
        missing_pkgs.append(pkg)
        continue
    found_bin = False
    for loc in spec.submodule_search_locations:
        b = os.path.join(loc, "bin")
        if os.path.isdir(b):
            found_bin = True
            dll_dirs.append(b)
            p(f"  {pkg:20s} -> bin CO: {b}")
            for d in dlls:
                p(f"        {d:22s}: {'CO' if os.path.isfile(os.path.join(b, d)) else 'THIEU'}")
            got = [os.path.basename(x) for x in glob.glob(os.path.join(b, '*.dll'))]
            p(f"        (.dll: {', '.join(got[:14])}{'...' if len(got) > 14 else ''})")
    if not found_bin:
        p(f"  {pkg:20s} -> bin KHONG CO")
        missing_pkgs.append(pkg)

# [2] Add dll dirs (giống phu_de._add_cuda_dll_dirs) rồi nạp thử TỪNG DLL theo thứ tự phụ thuộc
p("\n[2] Add DLL dirs + nap thu (ctypes.WinDLL):")
dll_fail = {}
if sys.platform == "win32":
    for b in dll_dirs:
        try:
            os.add_dll_directory(b)
        except Exception as e:
            p(f"  add_dll_directory LOI: {b} -> {e}")
    import ctypes
    for d in ("cudart64_12.dll", "cublasLt64_12.dll", "cublas64_12.dll", "cudnn64_9.dll"):
        try:
            ctypes.WinDLL(d)
            p(f"  {d:22s} -> NAP OK")
        except Exception as e:
            dll_fail[d] = str(e)[:140]
            p(f"  {d:22s} -> LOI: {str(e)[:140]}")
else:
    p("  (khong phai Windows -> bo qua)")

# [3] ctranslate2 thấy GPU không + compute type hỗ trợ
p("\n[3] ctranslate2:")
cuda_count = None
driver_issue = False
try:
    import ctranslate2
    p("  version:", getattr(ctranslate2, "__version__", "?"))
    cuda_count = ctranslate2.get_cuda_device_count()
    p("  get_cuda_device_count():", cuda_count)
    try:
        p("  supported_compute_types(cuda):", ctranslate2.get_supported_compute_types("cuda"))
    except Exception as e:
        msg = str(e)
        p("  supported_compute_types(cuda) LOI:", msg[:120])
        if "driver" in msg.lower() and "insufficient" in msg.lower():
            driver_issue = True
except Exception as e:
    p("  import ctranslate2 LOI:", str(e)[:140])

# [4] Nạp thử model whisper trên cuda
p("\n[4] Thu nap WhisperModel('tiny', cuda, int8_float16):")
model_ok = False
try:
    from faster_whisper import WhisperModel
    WhisperModel("tiny", device="cuda", compute_type="int8_float16")
    model_ok = True
    p("  NAP MODEL CUDA OK.")
except Exception as e:
    msg = str(e)
    p("  LOI:", msg[:180])
    if "driver" in msg.lower() and "insufficient" in msg.lower():
        driver_issue = True

# ===================== KET LUAN =====================
p("\n========== [KET LUAN] ==========")
if missing_pkgs:
    p("NGUYEN NHAN: THIEU goi CUDA: " + ", ".join(missing_pkgs))
    p("HANH DONG  : Bam nut 'Cai/sua tang toc GPU' trong tab Cai dat (hoac chay cai_gpu.py).")
elif driver_issue or (cuda_count == 0 and not missing_pkgs):
    p("NGUYEN NHAN: DRIVER NVIDIA QUA CU — khong du moi cho CUDA 12 runtime (du goi + DLL deu OK).")
    p("           : driver hien tai = " + (driver_ver or "khong doc duoc"))
    p("HANH DONG  : CAP NHAT DRIVER NVIDIA len ban moi (GeForce Experience hoac nvidia.com/Download).")
    p("           : CUDA 12.x can driver Windows >= ~527; nen cai ban MOI NHAT cho RTX 3050.")
    p("           : Cap nhat driver xong KHOI DONG LAI may roi chay lai script nay.")
elif dll_fail:
    p("NGUYEN NHAN: DLL CUDA khong nap duoc (goi co nhung load fail):")
    for d, e in dll_fail.items():
        p(f"           : {d} -> {e}")
    p("HANH DONG  : Neu loi nhac 'driver' -> cap nhat driver NVIDIA. Neu khac -> cai lai goi (cai_gpu.py).")
elif model_ok:
    p("KET QUA    : GPU OK! Whisper se chay GPU. Khoi dong lai tool + render lai.")
else:
    p("KET QUA    : Chua ro — gui TOAN BO output nay cho dev.")
p("================================")
