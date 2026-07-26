@echo off
title Audiobook Studio
setlocal enabledelayedexpansion

rem Run from this script's own folder, wherever the repo was cloned.
cd /d "%~dp0app"

rem Base Python must have PyMuPDF (fitz), requests, and pywebview. Resolve it
rem portably:
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
    echo Could not find a base Python with fitz + requests + pywebview.
    echo Set AUDIOBOOK_BASE_PY to your base conda python.exe and retry.
    pause
    exit /b 1
)

rem launcher.py starts the server on a background thread and opens a native
rem app window (falls back to your browser if pywebview / WebView2 aren't
rem available). It reads the port itself via config.py, so nothing here
rem needs to guess it.
echo Starting Audiobook Studio...
echo Using base Python: %BASEPY%
"%BASEPY%" launcher.py
pause
