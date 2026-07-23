@echo off
cd /d "%~dp0"
rem Task Scheduler chạy đứng một mình → tự set userData (config/khách/cache ở đó) + dùng runtime venv (KHÔNG
rem còn MediaCrawler\.venv từ v0.1.20). %APPDATA%\lln-app = userData của app.
set "LIC_CACHE_DIR=%APPDATA%\lln-app"
set "KHACH_DB_DIR=%APPDATA%\lln-app"
set "VCPY=%APPDATA%\lln-app\runtime\venv\Scripts\pythonw.exe"
if not exist "%VCPY%" set "VCPY=MediaCrawler\.venv\Scripts\pythonw.exe"
"%VCPY%" theo_doi.py
