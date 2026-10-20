@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
.\python_embeded\python.exe -s start_service.py %*
