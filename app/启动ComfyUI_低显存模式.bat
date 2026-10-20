@echo off
cd /d "%~dp0"
echo ============================================
echo  ComfyUI - LOW MEMORY mode
echo  Use this if you get out-of-memory errors.
echo ============================================
echo.
set PATH=%~dp0git\cmd;%~dp0git\bin;%PATH%
set ARGOS_CHUNK_TYPE=MINISBD
.\python_embeded\python.exe -s ComfyUI\main.py --windows-standalone-build --reserve-vram 1.0 --cache-none --preview-method none
echo.
echo ComfyUI stopped. Press any key to close this window.
pause >nul