@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem 系统里装过 Python 的用户可能设置了这些变量，会把便携版 Python 带偏
set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONSTARTUP="
set "PYTHONUSERBASE="
set "PIP_TARGET="
set "PIP_USER="
set "PYTHONNOUSERSITE=1"
set PYTHONIOENCODING=utf-8
.\python_embeded\python.exe -s start_service.py --watch %*
