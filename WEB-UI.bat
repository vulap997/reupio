@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Dang mo giao dien web... (giu cua so nay de chay; dong = tat web)
"MediaCrawler\.venv\Scripts\python.exe" web_app.py
pause
