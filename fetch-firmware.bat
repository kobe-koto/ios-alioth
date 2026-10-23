@echo off
rem Fetch / verify the iOS 16.5 IPSW in firmware\ (size + MD5, resumable download).
rem The work is done by fetch-firmware.ps1 next to this file.
rem
rem   fetch-firmware.bat
rem   fetch-firmware.bat -CheckOnly
rem   fetch-firmware.bat -Force
setlocal
set "HERE=%~dp0"
if not exist "%HERE%fetch-firmware.ps1" (
    echo [firmware] fetch-firmware.ps1 is missing next to this .bat
    if defined NO_PAUSE exit /b 1
    pause
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%HERE%fetch-firmware.ps1" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo.
    echo [firmware] exit code %RC%
    if defined NO_PAUSE exit /b %RC%
    pause
)
exit /b %RC%
