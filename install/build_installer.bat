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
rem
rem This is a cmd batch file. Running it from PowerShell 7 is fine:
rem     .\install\build_installer.bat

rem Delayed expansion is deliberately DISABLED. Nothing here needs !var!, and
rem enabling it makes cmd eat exclamation marks in expanded values -- a %TEMP%
rem or repo path containing '!' was being silently corrupted.
setlocal DisableDelayedExpansion

cd /d "%~dp0.." || (echo ERROR: could not cd to the repo root. & exit /b 1)

set "STAGE=%TEMP%\audiobook_studio_build"
set "OUTDIR=%CD%\Output"
set "MANIFEST=%OUTDIR%\Setup_AudiobookStudio-manifest.txt"

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

rem A stale manifest from a previous build would be read as if it described
rem this one, so remove it before compiling.
if exist "%MANIFEST%" del /q "%MANIFEST%"

echo Compiling ...
"%ISCC%" /O"%OUTDIR%" "%STAGE%\install\AudiobookStudio.iss"
if errorlevel 1 (echo ERROR: Inno Setup compile failed. & exit /b 1)

rem ---------------------------------------------------------------------
rem Verify what actually got embedded.
rem
rem The old instruction here was "open the .exe with 7-Zip and list its
rem contents". That does not work: 7-Zip cannot parse an Inno-compiled
rem installer and reports "Cannot open the file as archive", so the check was
rem never actually performable. AudiobookStudio.iss now emits
rem OutputManifestFile, which is Inno's own list of every embedded file, and
rem this greps it. A leak fails the build instead of relying on someone
rem remembering to look.
rem
rem Extensions are matched with findstr's end-of-word anchor (\>) rather than as
rem bare substrings, so a legitimate path can't trip a false rejection. The
rem config pattern uses a wildcard separator because the tracked file is
rem config.example.json, which must NOT match.
rem ---------------------------------------------------------------------
if not exist "%MANIFEST%" (
    echo ERROR: Inno produced no manifest, so the contents cannot be verified.
    echo Check that AudiobookStudio.iss still sets OutputManifestFile.
    exit /b 1
)

findstr /I /R /C:"\.pdf\>" /C:"\.wav\>" /C:"\.mp3\>" /C:"\.flac\>" /C:"\.ogg\>" /C:"\.m4a\>" /C:"\.m4b\>" /C:"\.aac\>" /C:"Voice_Sample" /C:"source_pdfs" /C:"app.config\.json" "%MANIFEST%" >nul 2>nul
if not errorlevel 1 (
    echo.
    echo ***********************************************************
    echo  BUILD REJECTED: the installer contains files that must not
    echo  be distributed. Offending manifest entries:
    echo ***********************************************************
    findstr /I /R /C:"\.pdf\>" /C:"\.wav\>" /C:"\.mp3\>" /C:"\.flac\>" /C:"\.ogg\>" /C:"\.m4a\>" /C:"\.m4b\>" /C:"\.aac\>" /C:"Voice_Sample" /C:"source_pdfs" /C:"app.config\.json" "%MANIFEST%"
    echo.
    echo Delete Output\Setup_AudiobookStudio.exe and fix the [Files] Excludes
    echo before sending this to anyone.
    del /q "%OUTDIR%\Setup_AudiobookStudio.exe" 2>nul
    exit /b 1
)

echo.
echo Contents verified against %MANIFEST%
echo   no PDFs, no audio, no voice clip, no local config.
echo.
echo Built: %OUTDIR%\Setup_AudiobookStudio.exe
echo.
echo Before sending it to anyone, note the SHA-256 so the recipient can check
echo it, and warn them that Windows SmartScreen will likely show a
echo "Windows protected your PC" prompt because this build is not
echo code-signed. They need "More info" then "Run anyway".
echo.
certutil -hashfile "%OUTDIR%\Setup_AudiobookStudio.exe" SHA256
endlocal
