@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PY="
set "COMFY="
if exist "%~dp0python_embeded\python.exe" (
  set "PY=%~dp0python_embeded\python.exe"
  set "COMFY=%~dp0"
)
if not defined PY if exist "%~dp0..\python_embeded\python.exe" (
  set "PY=%~dp0..\python_embeded\python.exe"
  set "COMFY=%~dp0.."
)
if not defined PY if exist "D:\AI\ComfyUI_windows_portable\python_embeded\python.exe" (
  set "PY=D:\AI\ComfyUI_windows_portable\python_embeded\python.exe"
  set "COMFY=D:\AI\ComfyUI_windows_portable"
)
if not defined PY if exist "C:\AI\ComfyUI_windows_portable\python_embeded\python.exe" (
  set "PY=C:\AI\ComfyUI_windows_portable\python_embeded\python.exe"
  set "COMFY=C:\AI\ComfyUI_windows_portable"
)
if not defined PY (
  echo Could not find ComfyUI Python automatically.
  set /p "COMFY=Enter ComfyUI_windows_portable folder: "
  if exist "%COMFY%\python_embeded\python.exe" set "PY=%COMFY%\python_embeded\python.exe"
)
if not defined PY (
  where python >nul 2>&1
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo Python not found. Install ComfyUI portable or add Python to PATH.
  pause
  exit /b 1
)
if defined COMFY (
  "%PY%" deploy_node.py --comfy "%COMFY%" %*
) else (
  "%PY%" deploy_node.py %*
)
pause
