@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Missing Python environment. See WEB_APP.md.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "scripts\run_app.py"
if errorlevel 1 pause
