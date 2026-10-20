@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "python_embeded\python.exe" (
  set "PY=python_embeded\python.exe"
) else (
  set "PY=python"
)
echo Unit tests run without a password.
echo Set MGS_TEST_PASSWORD to also run live HTTP smoke tests.
"%PY%" tests\run_tests.py
pause
