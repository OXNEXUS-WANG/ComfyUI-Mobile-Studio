@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo.
echo Commercial-clean mode:
echo   - no image model downloads
echo   - no GPL custom nodes
echo   - Chinese translation uses an MIT shim, not AGPL MiniSBD
echo   - ComfyUI is reused if present; otherwise you will be asked
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\install.ps1" -CommercialClean %*
set RC=%ERRORLEVEL%
if not "%RC%"=="0" (
  echo.
  echo Install failed. See the log above.
  pause
)
exit /b %RC%
