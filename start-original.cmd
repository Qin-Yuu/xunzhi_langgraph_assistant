@echo off
setlocal
set PYTHONUTF8=1
cd /d "%~dp0"
if not exist ".venv\Scripts\langgraph.exe" (
  echo Missing local environment. See README.md.
  pause
  exit /b 1
)
echo Starting the original ReAct Agent at http://127.0.0.1:2024
echo Fill .env with your model API key and TAVILY_API_KEY before chatting.
echo Press Ctrl+C to stop.
".venv\Scripts\langgraph.exe" dev --host 127.0.0.1 --port 2024 --no-browser
if errorlevel 1 pause
