@echo off
chcp 65001 >nul
REM Tu xin quyen admin neu chua co
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Dang xin quyen admin...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)
cd /d "%~dp0"
echo ============================================
echo  BAT CHE DO TU DONG: render tu khoi dong cung Windows
echo ============================================
schtasks /Create /TN "ToolCaoVideoRender" /TR "\"%~dp0render_nen.bat\"" /SC ONLOGON /RL HIGHEST /F
if %errorlevel%==0 (
    echo.
    echo [OK] Da bat. Tu lan dang nhap Windows sau, bo render se TU CHAY nen.
    echo Khoi dong render ngay bay gio...
    start "" "MediaCrawler\.venv\Scripts\pythonw.exe" xu_ly_video.py
) else (
    echo [LOI] Khong tao duoc tac vu.
)
echo.
pause
