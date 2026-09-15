@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1

if not exist ".venv\Scripts\python.exe" (
    echo [HEXA] Preparing local Python environment...
    where py >nul 2>nul
    if errorlevel 1 (
        echo [HEXA] Python 3.11+ was not found. Install Python and run HEXA.bat again.
        pause
        exit /b 1
    )
    py -3.11 -m venv .venv
    if errorlevel 1 (
        echo [HEXA] Failed to create the local environment.
        pause
        exit /b 1
    )
)

if not exist ".venv\.hexa-desktop-ready" (
    echo [HEXA] Installing desktop requirements for the first run...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    if errorlevel 1 goto :setup_failed
    ".venv\Scripts\python.exe" -m pip install -e ".[desktop,transcription]"
    if errorlevel 1 goto :setup_failed
    type nul > ".venv\.hexa-desktop-ready"
)

if exist ".venv\Scripts\pythonw.exe" (
    ".venv\Scripts\pythonw.exe" -m app.desktop.main
) else (
    ".venv\Scripts\python.exe" -m app.desktop.main
)
exit /b %errorlevel%

:setup_failed
echo.
echo [HEXA] Setup failed. Check the messages above, then run HEXA.bat again.
pause
exit /b 1
