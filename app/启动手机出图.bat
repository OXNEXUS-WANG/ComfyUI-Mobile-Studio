@echo off
cd /d "%~dp0"
echo ============================================
echo  Mobile Web UI  -  generate from your phone
echo ============================================
echo.
echo  Keep this window open. Closing it stops the service.
echo.
.\python_embeded\python.exe -s mobile_web.py
rem exit code 3/4 = port already in use (another copy is running)
rem close the window instead of stopping at pause, otherwise dead
rem windows pile up every time the shortcut is launched twice
if errorlevel 3 exit /b
echo.
echo Service stopped. Press any key to close.
pause >nul
