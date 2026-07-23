@echo off
chcp 65001 >nul
cd /d "%~dp0"
:: Khoi dong server web (neu chua chay) roi mo localhost trong Chrome che do app - 1 lan bam la xong
set "URL=http://localhost:8770"

:: 1) Bat server neu chua chay
powershell -NoProfile -Command "if(-not (Get-NetTCPConnection -LocalPort 8770 -State Listen -ErrorAction SilentlyContinue)){ Start-Process -WindowStyle Hidden -FilePath '%~dp0MediaCrawler\.venv\Scripts\pythonw.exe' -ArgumentList 'web_app.py','--noopen' -WorkingDirectory '%~dp0'; Start-Sleep -Seconds 2 }"

:: 2) Tim trinh duyet Chromium (Chrome truoc, roi Edge)
set "BROWSER="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "BROWSER=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined BROWSER if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "BROWSER=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not defined BROWSER if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set "BROWSER=%LocalAppData%\Google\Chrome\Application\chrome.exe"
if not defined BROWSER if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" set "BROWSER=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not defined BROWSER if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" set "BROWSER=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"

:: 3) Mo localhost
if not defined BROWSER goto mac_dinh
start "" "%BROWSER%" --app=%URL% --window-size=1400,900
goto xong

:mac_dinh
:: Khong tim thay Chrome/Edge -> mo bang trinh duyet mac dinh
start "" %URL%

:xong
exit
