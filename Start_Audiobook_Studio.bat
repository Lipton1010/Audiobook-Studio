@echo off
title Audiobook Studio
setlocal DisableDelayedExpansion

rem One-click installs keep their private Python environment and every large
rem cache under this app folder. A source checkout normally has no runtime\
rem folder and continues to use the developer's existing conda installation.
set "RUNTIME_ROOT=%~dp0runtime"
if exist "%RUNTIME_ROOT%\miniconda3\python.exe" (
    set "AUDIOBOOK_BASE_PY=%RUNTIME_ROOT%\miniconda3\python.exe"
    set "HF_HOME=%RUNTIME_ROOT%\cache\huggingface"
    set "TORCH_HOME=%RUNTIME_ROOT%\cache\torch"
    set "PIP_CACHE_DIR=%RUNTIME_ROOT%\cache\pip"
    set "XDG_CACHE_HOME=%RUNTIME_ROOT%\cache"
    set "XDG_CONFIG_HOME=%RUNTIME_ROOT%\config"
    set "CONDA_ENVS_PATH=%RUNTIME_ROOT%\miniconda3\envs"
    set "CONDA_PKGS_DIRS=%RUNTIME_ROOT%\miniconda3\pkgs"
    set "CONDA_REGISTER_ENVS=false"
    set "CONDA_NO_PLUGINS=true"
    set "CONDA_SOLVER=classic"
    set "CONDA_ANACONDA_ANON_USAGE=false"
    set "ANACONDA_ANON_USAGE=false"
)

rem Run from this script's own folder, wherever the repo was cloned.
cd /d "%~dp0app"

rem Base Python must have PyMuPDF (fitz), requests, and pywebview. Resolve it
rem portably:
rem   1. AUDIOBOOK_BASE_PY env override
rem   2. the app-owned runtime used by the installer
rem   3. common miniconda/anaconda base locations
rem   4. python on PATH
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
if exist "%RUNTIME_ROOT%\miniconda3\pythonw.exe" (
    start "" "%RUNTIME_ROOT%\miniconda3\pythonw.exe" launcher.py
    exit /b 0
)
"%BASEPY%" launcher.py
pause
