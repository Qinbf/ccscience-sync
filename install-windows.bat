@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 ccscience_sync.py install
  py -3 ccscience_sync.py status
) else (
  python ccscience_sync.py install
  python ccscience_sync.py status
)

echo.
echo Done. You can close this window.
pause
