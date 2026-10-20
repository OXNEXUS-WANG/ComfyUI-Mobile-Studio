@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   Build an offline USB bundle
echo ============================================
echo.
.\python_embeded\python.exe -s tools\usb_bundle.py --root "%~dp0"
pause
