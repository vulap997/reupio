@echo off
chcp 65001 >nul
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)
echo Tat che do render tu khoi dong cung Windows...
schtasks /Delete /TN "ToolCaoVideoRender" /F
echo Da tat. (Render dang chay van tiep tuc cho den khi ban dong hoac tat may.)
pause
