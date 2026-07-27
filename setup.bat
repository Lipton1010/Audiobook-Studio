@echo off
title Audiobook Studio - Setup
setlocal DisableDelayedExpansion
cd /d "%~dp0"

rem A one-click installation owns a private runtime. Keep repairs and retries
rem in that same folder rather than falling back to a machine-wide conda.
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

rem Find a Python to bootstrap setup.py with. Prefer conda's base python; fall
rem back to any python on PATH. setup.py itself only uses the standard library.
set "BOOTPY="
if defined AUDIOBOOK_BASE_PY (
    if exist "%AUDIOBOOK_BASE_PY%" set "BOOTPY=%AUDIOBOOK_BASE_PY%"
)
if not defined BOOTPY (
    rem Source installs share this fallback list with Start_Audiobook_Studio.bat
    rem and setup.py's find_conda(). The one-click installer does not reach this
    rem branch because it always uses its app-owned runtime.
    for %%D in (
        "%USERPROFILE%\miniconda3"
        "%USERPROFILE%\anaconda3"
        "%USERPROFILE%\miniforge3"
        "C:\ProgramData\miniconda3"
        "C:\ProgramData\anaconda3"
        "C:\miniconda3"
        "C:\anaconda3"
    ) do (
        if not defined BOOTPY if exist "%%~D\python.exe" set "BOOTPY=%%~D\python.exe"
    )
)
if not defined BOOTPY (
    where python >nul 2>nul && set "BOOTPY=python"
)
if not defined BOOTPY (
    echo Could not find Python to run the setup.
    echo Install Miniconda from https://docs.conda.io/en/latest/miniconda.html,
    echo reopen this window, and run setup.bat again.
    pause
    exit /b 1
)

if exist "%RUNTIME_ROOT%\miniconda3\python.exe" (
    "%BOOTPY%" setup.py --runtime-root "%RUNTIME_ROOT%" %*
) else (
    "%BOOTPY%" setup.py %*
)
echo.
pause
