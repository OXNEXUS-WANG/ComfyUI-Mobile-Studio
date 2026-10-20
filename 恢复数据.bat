@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "python_embeded\python.exe" (
  set "PY=python_embeded\python.exe"
) else (
  set "PY=python"
)
echo Close the mobile web service before restoring.
echo.
set /p "ZIP=Backup ZIP path: "
if "%ZIP%"=="" goto :eof
"%PY%" tools\restore.py "%ZIP%"
pause
