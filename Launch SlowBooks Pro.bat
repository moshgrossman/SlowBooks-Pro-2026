@echo off
REM ==========================================================================
REM  Slowbooks Pro 2026 - one-click desktop launcher (Windows)
REM
REM  Double-click this file to start Slowbooks Pro in its own window.
REM  Requires Python, WSL2, and Docker Engine to already be set up — run
REM  "Setup SlowBooks Pro.bat" first if you haven't. desktop_launcher.py
REM  itself talks to Docker inside WSL2, so nothing else is needed here.
REM ==========================================================================

cd /d "%~dp0"

REM Make sure the native-window dependency is present (fast if already there).
python -c "import webview" 2>nul
if errorlevel 1 (
    echo Installing the desktop window component ^(one-time^)...
    python -m pip install -r requirements-desktop.txt
)

python "desktop_launcher.py"
if errorlevel 1 (
    echo.
    echo Something went wrong. See the messages above.
    pause
)
