@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "python_embeded\python.exe" (
  set "PY=python_embeded\python.exe"
) else (
  set "PY=python"
)
"%PY%" tools\backup.py
pause
