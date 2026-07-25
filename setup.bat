@echo off
title Audiobook Studio - Setup
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem Find a Python to bootstrap setup.py with. Prefer conda's base python; fall
rem back to any python on PATH. setup.py itself only uses the standard library.
set "BOOTPY="
if defined AUDIOBOOK_BASE_PY (
    if exist "%AUDIOBOOK_BASE_PY%" set "BOOTPY=%AUDIOBOOK_BASE_PY%"
)
if not defined BOOTPY (
    for %%D in (
        "%USERPROFILE%\miniconda3"
        "%USERPROFILE%\anaconda3"
        "%USERPROFILE%\miniforge3"
        "C:\ProgramData\miniconda3"
        "C:\ProgramData\anaconda3"
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

"%BOOTPY%" setup.py %*
echo.
pause
