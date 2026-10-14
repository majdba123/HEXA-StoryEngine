@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
if not defined HEXA_WEB_PYTHON set "HEXA_WEB_PYTHON=.venv\Scripts\python.exe"
if not exist "%HEXA_WEB_PYTHON%" (
    echo [HEXA WEB] Python environment is missing. Set HEXA_WEB_PYTHON to an existing project Python or run HEXA.bat once.
    pause
    exit /b 1
)
"%HEXA_WEB_PYTHON%" -c "import fastapi, uvicorn, multipart; from app.web.server import app"
if errorlevel 1 (
    echo [HEXA WEB] Web dependencies are missing. Run: %%HEXA_WEB_PYTHON%% -m pip install -e .
    pause
    exit /b 1
)
where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo [HEXA WEB] FFmpeg is missing from PATH.
    pause
    exit /b 1
)
where ffprobe >nul 2>nul
if errorlevel 1 (
    echo [HEXA WEB] FFprobe is missing from PATH.
    pause
    exit /b 1
)
"%HEXA_WEB_PYTHON%" -m app.web
if errorlevel 1 (
    echo [HEXA WEB] Server failed to start. Check port 8787 and the error above.
    pause
    exit /b 1
)
