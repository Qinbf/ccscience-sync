@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 ccscience.py install
  py -3 ccscience.py status
) else (
  python ccscience.py install
  python ccscience.py status
)

echo.
echo Done. You can close this window.
pause
