@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 ccscience.py uninstall
) else (
  python ccscience.py uninstall
)

echo.
echo Done. You can close this window.
pause
