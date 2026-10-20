@echo off
setlocal
set "PY=python"
if exist "%~dp0..\python_embeded\python.exe" set "PY=%~dp0..\python_embeded\python.exe"
set /p CODE=Join code:
set /p NAME=Node name:
if exist "%~dp0cert.pem" (
  "%PY%" "%~dp0worker_agent.py" join --server https://192.168.137.1:8800 --code %CODE% --name "%NAME%" --ca cert.pem
) else (
  "%PY%" "%~dp0worker_agent.py" join --server https://192.168.137.1:8800 --code %CODE% --name "%NAME%" --insecure
)
pause
