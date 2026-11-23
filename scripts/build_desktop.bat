@echo off
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo No .venv yet. Start the gateway once with scripts\run_gateway.bat first.
  pause
  exit /b 1
)
echo Installing build tools ...
.venv\Scripts\python.exe -m pip install pyinstaller pywebview
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m PyInstaller desktop\yantguard.spec --noconfirm --clean
if errorlevel 1 goto fail
echo.
echo Done: dist\YantGuard\YantGuard.exe
echo Put your .env ^(GEMINI_API_KEY / GROQ_API_KEY^) next to YantGuard.exe, or in %LOCALAPPDATA%\YantGuard\data
pause
exit /b 0
:fail
echo.
echo Build failed. Copy the last 20 lines above and send them to Claude.
pause
exit /b 1
