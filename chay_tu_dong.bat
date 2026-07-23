@echo off
cd /d "%~dp0"
rem Hẹn giờ chạy đứng một mình → set userData + runtime venv (như theo_doi.bat). %APPDATA%\lln-app = userData.
set "LIC_CACHE_DIR=%APPDATA%\lln-app"
set "KHACH_DB_DIR=%APPDATA%\lln-app"
set "VCPY=%APPDATA%\lln-app\runtime\venv\Scripts\pythonw.exe"
if not exist "%VCPY%" set "VCPY=MediaCrawler\.venv\Scripts\pythonw.exe"
"%VCPY%" chay_tu_dong.py
