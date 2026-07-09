@echo off
setlocal

REM ==========================================================================
REM  Slowbooks Pro 2026 - Setup (Windows)
REM
REM  This is the ONE file to download and double-click. It installs
REM  everything Slowbooks Pro needs (Python, WSL2, Docker Engine), downloads
REM  the app itself, and opens it. Safe to run again if it stops partway
REM  through (e.g. after a restart).
REM
REM  Windows will likely show a "Windows protected your PC" SmartScreen
REM  warning the first time you run a downloaded script like this one --
REM  that's expected for an unsigned script. Click "More info" then
REM  "Run anyway" to continue.
REM
REM  This file stays small on purpose: it always fetches the latest setup
REM  logic from GitHub, so it keeps working even if that logic improves
REM  later.
REM ==========================================================================

REM --- Self-elevate to Administrator (needed to install Python system-wide
REM     and enable the WSL2 Windows feature) ---
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator privileges...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -WorkingDirectory '%~dp0' -Verb RunAs"
    exit /b
)

set "SETUP_URL=https://raw.githubusercontent.com/moshgrossman/SlowBooks-Pro-2026/main/Setup-SlowBooksPro.ps1"
set "SETUP_PS1=%TEMP%\Setup-SlowBooksPro.ps1"

echo Downloading the latest setup script...
powershell -NoProfile -Command "try { Invoke-WebRequest -Uri '%SETUP_URL%' -OutFile '%SETUP_PS1%' -UseBasicParsing } catch { exit 1 }"
if errorlevel 1 (
    echo.
    echo Could not download the setup script. Check your internet connection
    echo and try again, or set up manually using the instructions at:
    echo   https://github.com/moshgrossman/SlowBooks-Pro-2026/blob/main/INSTALL.md
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%SETUP_PS1%"
set "EXITCODE=%errorlevel%"

if not "%EXITCODE%"=="0" (
    echo.
    echo Setup did not finish. See the messages above for what to do next.
    pause
)

exit /b %EXITCODE%
