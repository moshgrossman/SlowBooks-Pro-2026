@echo off
REM ==========================================================================
REM  Slowbooks Pro 2026 - stop the app (Windows)
REM
REM  Stops the Docker containers running inside WSL2. Your data is kept safe
REM  in Docker volumes and will be there next time you launch.
REM ==========================================================================

echo Stopping Slowbooks Pro...
wsl.exe -d Ubuntu -u root -- bash -lc "cd /root/slowbooks-pro && docker compose down"
if errorlevel 1 (
    echo.
    echo Could not stop the app. If you haven't run "Setup SlowBooks Pro.bat"
    echo yet, there is nothing running to stop.
)

echo Done. Your data is preserved.
pause
