@echo off
title Audiobook Studio
setlocal enabledelayedexpansion

rem Run from this script's own folder, wherever the repo was cloned.
cd /d "%~dp0app"

rem Base Python must have PyMuPDF (fitz) + requests. Resolve it portably:
rem   1. AUDIOBOOK_BASE_PY env override
rem   2. common miniconda/anaconda base locations
rem   3. python on PATH
set "BASEPY="
if defined AUDIOBOOK_BASE_PY (
    if exist "%AUDIOBOOK_BASE_PY%" set "BASEPY=%AUDIOBOOK_BASE_PY%"
)
if not defined BASEPY (
    for %%D in (
        "%USERPROFILE%\miniconda3"
        "%USERPROFILE%\anaconda3"
        "%USERPROFILE%\miniforge3"
        "C:\ProgramData\miniconda3"
        "C:\ProgramData\anaconda3"
        "C:\miniconda3"
        "C:\anaconda3"
    ) do (
        if not defined BASEPY if exist "%%~D\python.exe" set "BASEPY=%%~D\python.exe"
    )
)
if not defined BASEPY (
    where python >nul 2>nul && set "BASEPY=python"
)
if not defined BASEPY (
    echo Could not find a base Python with fitz + requests.
    echo Set AUDIOBOOK_BASE_PY to your base conda python.exe and retry.
    pause
    exit /b 1
)

rem Open the browser at the SAME port the server will use. config.py is the
rem single source of truth (env > config.json > default), so ask it rather
rem than guess; fall back to 8765 only if that call fails.
set "PORT="
for /f "usebackq delims=" %%p in (`"%BASEPY%" -c "from config import CFG; print(CFG.port)" 2^>nul`) do set "PORT=%%p"
if not defined PORT set "PORT=8765"

echo Starting Audiobook Studio at http://localhost:%PORT%
echo Using base Python: %BASEPY%
start "" http://localhost:%PORT%
"%BASEPY%" server.py
pause
