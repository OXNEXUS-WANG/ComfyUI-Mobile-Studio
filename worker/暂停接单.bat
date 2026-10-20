@echo off
setlocal
set "PY=python"
if exist "%~dp0..\python_embeded\python.exe" set "PY=%~dp0..\python_embeded\python.exe"
"%PY%" "%~dp0worker_agent.py" pause
pause
