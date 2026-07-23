@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo   CAI DAT F5-TTS  (long tieng clone giong - tieng Viet)
echo   Cai vao userData\runtime (BEN qua update) - KHONG de trong app-src.
echo   Tu dung GPU (CUDA) neu may co - khong thi chay CPU (cham hon).
echo ============================================================
echo.

rem --- Noi cai: userData\runtime (ban dong goi) ; neu khong co -^> thu muc nay (dev) ---
set "F5BASE=%APPDATA%\lln-app\runtime"
if not exist "%F5BASE%\venv" set "F5BASE=%~dp0"
if "%F5BASE:~-1%"=="\" set "F5BASE=%F5BASE:~0,-1%"

rem --- uv: uu tien ban bundle (resources\vendor\uv.exe), khong thi uv trong PATH ---
set "UV=%~dp0..\vendor\uv.exe"
if not exist "%UV%" set "UV=uv"

echo Cai vao : %F5BASE%
echo Dung uv : %UV%
echo.

echo [1/4] Tao moi truong ao .venv_f5 (Python 3.11)...
"%UV%" venv "%F5BASE%\.venv_f5" --python 3.11
if errorlevel 1 ( echo LOI tao venv. Can cai uv truoc. & pause & exit /b 1 )

echo.
echo [2/4] Cai f5-tts + vinorm + underthesea (keo torch/transformers, hoi lau)...
"%UV%" pip install --python "%F5BASE%\.venv_f5\Scripts\python.exe" f5-tts vinorm underthesea
if errorlevel 1 ( echo LOI cai f5-tts. & pause & exit /b 1 )

echo.
echo [3/4] Neu co GPU NVIDIA: thay PyTorch CPU -^> CUDA 12.1 (long tieng nhanh ~10x)...
where nvidia-smi >nul 2>nul
if %errorlevel%==0 (
    echo   Thay GPU NVIDIA, dang tai PyTorch CUDA ^(~2.5GB, hoi lau^)...
    "%UV%" pip install --python "%F5BASE%\.venv_f5\Scripts\python.exe" --reinstall torch torchaudio --index-url https://download.pytorch.org/whl/cu121
    if errorlevel 1 ( echo   ^(Loi tai CUDA torch - giu ban CPU, long tieng van chay nhung cham hon.^) )
) else (
    echo   Khong thay GPU NVIDIA -^> giu PyTorch CPU ^(long tieng chay CPU, cham hon^).
)

echo.
echo [4/4] Tai model F5-TTS tieng Viet (~1.3GB) ve %F5BASE%\f5_vn_model\ ...
"%F5BASE%\.venv_f5\Scripts\python.exe" -c "from huggingface_hub import hf_hub_download; import os; d=os.path.join(r'%F5BASE%','f5_vn_model'); os.makedirs(d, exist_ok=True); [print(hf_hub_download('yukiakai/F5-TTS-Vietnamese', f, local_dir=d)) for f in ('model_85044.safetensors','vocab.txt')]"
if errorlevel 1 ( echo LOI tai model. & pause & exit /b 1 )

echo.
echo ============================================================
echo   XONG! Long tieng se dung F5-TTS clone giong.
echo   Da cai o: %F5BASE%  (BEN qua update - khong mat khi cap nhat app).
echo ============================================================
pause
