@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  CAI DAT MOI TRUONG - chi can chay 1 lan
echo ============================================
echo.
echo [1/4] Kiem tra va cai uv (trinh quan ly Python)...
python -m uv --version >nul 2>nul
if errorlevel 1 (
    python -m pip install uv
)
echo.
echo [2/4] Cai Python 3.11 + thu vien cho MediaCrawler (co the mat vai phut)...
cd MediaCrawler
python -m uv sync
echo.
echo [3/4] Cai trinh duyet Chromium cho Playwright...
python -m uv run playwright install chromium
echo.
echo [4/4] (Tuy chon) Neu co GPU NVIDIA: tai CUDA ~1.3GB cho Whisper GPU...
where nvidia-smi >nul 2>nul
if %errorlevel%==0 (
    python -m uv sync --extra gpu
) else (
    echo   Khong thay GPU NVIDIA - bo qua CUDA, Whisper chay CPU.
)
echo.
echo ============================================
echo  CAI DAT XONG! Chay file CAO-VIDEO.bat de bat dau cao video.
echo ============================================
pause
