@echo off
chcp 65001 >nul
cd /d "%~dp0"
.\python_embeded\python.exe -s installer\download_models.py --root "%~dp0" --manifest installer\models_manifest.json --ask-target
pause
