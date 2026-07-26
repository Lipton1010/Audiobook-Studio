@echo off
rem Build Setup_AudiobookStudio.exe from a CLEAN copy of the repo.
rem
rem Why this exists: AudiobookStudio.iss packages "..\*", i.e. whatever is
rem sitting in the source tree at compile time. Inno's Excludes are not
rem gitignore (a leading backslash anchors to the root instead of matching
rem anywhere), and even a correct exclude list is one typo away from shipping
rem 136 MB of purchased PDFs and the voice clip that must never be
rem distributed. `git archive` sidesteps the whole class of mistake: it can
rem only emit files that are tracked in git, and no book, audio file, job
rem folder, or local config is tracked.
rem
rem Requires: git, and Inno Setup 6 (ISCC.exe).
rem Usage:    install\build_installer.bat        (run from the repo root)

setlocal enabledelayedexpansion
cd /d "%~dp0.."

set "STAGE=%TEMP%\audiobook_studio_build"
set "OUTDIR=%CD%\Output"

where git >nul 2>nul || (echo ERROR: git is not on PATH. & exit /b 1)

set "ISCC="
for %%P in (
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    "C:\Program Files\Inno Setup 6\ISCC.exe"
) do (
    if not defined ISCC if exist %%P set "ISCC=%%~P"
)
if not defined ISCC (
    where ISCC >nul 2>nul && set "ISCC=ISCC"
)
if not defined ISCC (
    echo ERROR: Inno Setup's compiler ^(ISCC.exe^) was not found.
    echo Install Inno Setup 6 from https://jrsoftware.org/isinfo.php and retry.
    exit /b 1
)

rem git archive only sees COMMITTED files. Uncommitted fixes will not be in the
rem installer, which is deliberate but is exactly the kind of thing that eats an
rem afternoon, so say so loudly.
git diff --quiet && git diff --cached --quiet
if errorlevel 1 (
    echo.
    echo WARNING: you have uncommitted changes. They will NOT be in this build,
    echo          because the staging copy is made with 'git archive HEAD'.
    echo.
    choice /C YN /M "Build anyway"
    if errorlevel 2 exit /b 1
)

echo Staging a clean copy of HEAD in %STAGE% ...
if exist "%STAGE%" rmdir /s /q "%STAGE%"
mkdir "%STAGE%" || exit /b 1
git archive --format=tar HEAD | tar -x -C "%STAGE%"
if errorlevel 1 (echo ERROR: git archive failed. & exit /b 1)

if not exist "%STAGE%\install\AudiobookStudio.iss" (
    echo ERROR: staged copy is missing install\AudiobookStudio.iss
    exit /b 1
)

echo Compiling ...
"%ISCC%" /O"%OUTDIR%" "%STAGE%\install\AudiobookStudio.iss"
if errorlevel 1 (echo ERROR: Inno Setup compile failed. & exit /b 1)

echo.
echo Built: %OUTDIR%\Setup_AudiobookStudio.exe
echo.
echo BEFORE SENDING IT TO ANYONE: open that .exe with 7-Zip and list its
echo contents. There must be no .pdf, no .wav/.mp3, and no samples\Voice_Sample.
endlocal
