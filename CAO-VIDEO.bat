@echo off
cd /d "%~dp0"
if not exist "MediaCrawler\.venv\Scripts\pythonw.exe" (
    echo Chua cai moi truong! Dang tu dong chay cai dat...
    call CAI-DAT.bat
)
echo Dang khoi dong server web...
:: Bat server neu chua chay, roi DOI den khi san sang moi mo trinh duyet (tranh "tu choi ket noi")
powershell -NoProfile -Command "if(-not (Get-NetTCPConnection -LocalPort 8770 -State Listen -ErrorAction SilentlyContinue)){ Start-Process -WindowStyle Hidden -FilePath '%~dp0MediaCrawler\.venv\Scripts\pythonw.exe' -ArgumentList 'web_app.py','--noopen' -WorkingDirectory '%~dp0' }; for($i=0;$i -lt 60;$i++){ if(Get-NetTCPConnection -LocalPort 8770 -State Listen -ErrorAction SilentlyContinue){break}; Start-Sleep -Milliseconds 250 }"
start "" http://localhost:8770
echo Giao dien web: http://localhost:8770  (dong cua so nay cung duoc)
