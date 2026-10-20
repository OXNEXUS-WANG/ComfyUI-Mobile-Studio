@echo off
cd /d "%~dp0"
echo ============================================
echo  ComfyUI - RTX 5060 8GB recommended settings
echo ============================================
echo.
REM Bundled git on PATH (ComfyUI-Manager needs it; system has no git installed)
set PATH=%~dp0git\cmd;%~dp0git\bin;%PATH%
REM Force MiniSBD so offline CN->EN prompt translation works.
REM (default stanza path needs raw.githubusercontent.com / huggingface.co, both blocked here)
set ARGOS_CHUNK_TYPE=MINISBD
.\python_embeded\python.exe -s ComfyUI\main.py --windows-standalone-build --reserve-vram 0.8 --preview-method auto --auto-launch
echo.
echo ComfyUI stopped. Press any key to close this window.
pause >nul