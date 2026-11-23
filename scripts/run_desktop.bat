@echo off
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo No .venv yet. Start the gateway once with scripts\run_gateway.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -c "import webview" 2>nul || (
  echo Installing the desktop window package ^(first run only^) ...
  .venv\Scripts\python.exe -m pip install pywebview
)
.venv\Scripts\python.exe desktop\yantguard_desktop.py %*
if errorlevel 1 pause
