@echo off
cd /d "%~dp0"
chcp 65001 >nul
.\python_embeded\python.exe -s security_setup.py
echo.
echo Press any key to close.
pause >nul
