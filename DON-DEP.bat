@echo off
chcp 65001 >nul
:: ===== Tu xin quyen Admin (de kill duoc tien trinh cao chay nen) =====
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Dang xin quyen Admin...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)
cd /d "%~dp0"
echo ============================================================
echo   DON DEP: tat cac tien trinh cao / trinh duyet bi treo
echo ============================================================
echo.
echo Dang tat python / pythonw va Chromium cua tool...
powershell -NoProfile -Command "Get-Process python,pythonw -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue; Get-Process chrome -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*ms-playwright*' } | Stop-Process -Force -ErrorAction SilentlyContinue"
echo Dang giai phong khoa ho so dang nhap...
del /F /Q "MediaCrawler\browser_data\dy_user_data_dir\Singleton*" 2>nul
echo.
echo XONG! Da don sach. Bay gio:
echo   - Mo lai giao dien:  WEB-UI.bat  (hoac CAO-VIDEO.bat)
echo   - Roi thu lai "Goi y kenh"
echo.
echo Luu y: chi chay 1 viec cao tai 1 thoi diem (theo doi / hen gio / goi y
echo dung chung 1 ho so dang nhap, chay cung luc se ket nhau).
echo.
pause
