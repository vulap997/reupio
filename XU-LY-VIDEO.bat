@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  BO XU LY VIDEO (FFmpeg) - dang chay nen
echo  Quet thu muc raw_videos, xu ly -> processed_videos
echo  Nhan Ctrl+C de dung.
echo ============================================
"MediaCrawler\.venv\Scripts\python.exe" xu_ly_video.py
pause
