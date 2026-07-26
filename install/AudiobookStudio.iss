; Audiobook Studio installer (Inno Setup script)
;
; Build with the Inno Setup Compiler (free, Windows-only): https://jrsoftware.org/isinfo.php
;   1. Install Inno Setup on your own machine.
;   2. Open this file in the Inno Setup IDE, or run from a terminal:
;        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" install\AudiobookStudio.iss
;   3. Output/Setup_AudiobookStudio.exe is the single file to hand to your friend.
;
; What this does, in order, all silent/unattended:
;   1. Copies the repo (app code, samples/, install/, launcher, batch files) to
;      the chosen install folder. Large gitignored content (PDFs, audio, HF
;      cache, app/jobs) is never bundled -- it does not exist in a fresh clone.
;   2. [Code] section below (Pascal Script, no Python needed) checks for an
;      existing conda; if none is found, downloads the official Miniconda
;      installer with Inno's built-in downloader and runs it fully silently
;      (current user only, no admin: /InstallationType=JustMe /RegisterPython=0
;      /S /D=path). This has to happen in Pascal Script, not a Python script,
;      because on a truly clean machine there is no Python at all yet to run
;      install\bootstrap_conda.py with.
;   3. Runs setup.py --yes --auto-install-ffmpeg --prefetch-weights using the
;      conda base python from step 2. setup.py in turn calls
;      install\bootstrap_ffmpeg.py (fetches a static ffmpeg build into tools\
;      if not already present) and install\bootstrap_weights.py (pre-downloads
;      the ~3 GB of Chatterbox weights via plain HTTP, no CUDA/inference
;      involved, so a failure here is isolated from whether the GPU/torch
;      stack itself works).
;   4. Creates Start Menu + Desktop shortcuts pointing at
;      Start_Audiobook_Studio.bat, which now opens a native app window
;      (pywebview) instead of a browser tab.
;
; What it deliberately does NOT do:
;   - Install or upgrade an NVIDIA driver. If there's no GPU, setup.py reports
;     that clearly; this installer does not try to fix it.
;   - Touch Ollama in any way (hard project rule; see CLAUDE.md).
;   - Install a bundled Python. It relies on the Miniconda it just installed
;     (or found) to run setup.py itself, since setup.py is stdlib-only.
;
; Every step below writes its own log to install_log.txt in the install
; folder, since "send me the whole terminal output" (the ask in the README)
; is the actual debugging path for a first install on someone else's machine.

#define MyAppName "Audiobook Studio"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Audiobook Studio"
#define MyAppExeName "Start_Audiobook_Studio.bat"

[Setup]
; Real GUID (generated once for this project) so Windows recognizes upgrades
; of this same app rather than treating every rebuild as a new install.
; Regenerate only if you deliberately want a rebuild to be seen as unrelated.
AppId={{FF5AC68A-1E05-4C9D-9B5D-204F12CD7183}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Per-user install, no admin required -- matches the "JustMe" Miniconda
; install and keeps this usable on a locked-down work laptop.
DefaultDirName={userpf}\{#MyAppName}
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
OutputDir=..\Output
OutputBaseFilename=Setup_AudiobookStudio
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
; This is a real installer, so a real uninstall entry; it removes only what
; the installer copied plus the two conda envs it created, never the user's
; books, audio, or a pre-existing conda/ffmpeg install.
UninstallDisplayIcon={app}\app\icon.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
; Everything except the gitignored, machine-local, or job-output content that
; a fresh clone would never have anyway. Source is the repo root (one level
; up from install\, where this .iss file lives).
Source: "..\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; \
    Excludes: "\.git\*,\app\jobs\*,\app\config.json,\app\*.log,\audiobooks\*,\ab_samples\*,\tools\*,\install\Output\*,\*.pdf,\*.wav,\*.mp3,\*.flac,\*.ogg,\*.jpg,\__pycache__\*"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\app\icon.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon; IconFilename: "{app}\app\icon.ico"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

[Run]
; Each step is its own Run entry so the wizard's progress page shows discrete,
; named stages instead of one opaque "running..." bar, and so a failure in
; one step is attributable in install_log.txt rather than buried.
;
; StatusMsg text doubles as what the user reads while it runs -- written for
; someone who has never seen a terminal, per the "make it simple" goal.
;
; IMPORTANT ordering note: step 1 (Miniconda) is launched directly by Inno's
; [Code] section below, in Pascal Script, NOT via a Python script. This is
; deliberate: on a truly clean machine there is no Python at all yet, so
; nothing here can assume python.exe, py.exe, or conda exist until AFTER
; Miniconda is installed. Everything from step 2 onward runs with the
; Miniconda base python we just guaranteed exists.

; Piped through cmd /C so stdout+stderr land in install_log.txt -- "send me
; the whole terminal output" (the README's actual ask for a failed install)
; needs a file to point at when there was never a visible terminal.
Filename: "{cmd}"; Parameters: "/C ""{code:GetCondaPython}"" ""{app}\setup.py"" --yes --auto-install-ffmpeg --prefetch-weights > ""{app}\install_log.txt"" 2>&1"; \
    WorkingDir: "{app}"; StatusMsg: "Setting up Audiobook Studio (downloads ~3-4 GB: PyTorch + TTS weights, first time only)..."; \
    Flags: runhidden waituntilterminated

Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName} now"; Flags: postinstall skipifsilent shellexec

[Code]
var
  CondaPythonPath: string;

const
  MinicondaUrl = 'https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe';

// Finds an already-installed conda's base python.exe at the usual locations.
// Mirrors setup.py's own find_conda() search order so the two never disagree
// about what counts as "conda is present".
function FindExistingCondaPython(): string;
var
  Candidates: array[0..3] of string;
  I: Integer;
begin
  Candidates[0] := ExpandConstant('{%USERPROFILE}\miniconda3\python.exe');
  Candidates[1] := ExpandConstant('{%USERPROFILE}\anaconda3\python.exe');
  Candidates[2] := 'C:\ProgramData\miniconda3\python.exe';
  Candidates[3] := 'C:\ProgramData\anaconda3\python.exe';
  Result := '';
  for I := 0 to 3 do
  begin
    if FileExists(Candidates[I]) then
    begin
      Result := Candidates[I];
      exit;
    end;
  end;
end;

// Downloads and silently runs the official Miniconda installer using Inno's
// built-in downloader (idpdownload), which needs no Python. Runs the exact
// same silent flags as install/bootstrap_conda.py documents and uses, kept
// in sync deliberately: /InstallationType=JustMe /RegisterPython=0 /S
// /D=<path>, current user only, no admin.
procedure InstallMinicondaViaInno();
var
  InstallerPath: string;
  InstallDir: string;
  ResultCode: Integer;
begin
  InstallerPath := ExpandConstant('{tmp}\miniconda_installer.exe');
  InstallDir := ExpandConstant('{%USERPROFILE}\miniconda3');

  WizardForm.StatusLabel.Caption := 'Downloading Miniconda (first-time setup)...';
  if not DownloadTemporaryFile(MinicondaUrl, 'miniconda_installer.exe', '', InstallerPath) then
  begin
    MsgBox('Could not download Miniconda. Check your internet connection and re-run this installer.', mbError, MB_OK);
    exit;
  end;

  WizardForm.StatusLabel.Caption := 'Installing Miniconda (this can take a few minutes)...';
  if not Exec(InstallerPath,
      '/InstallationType=JustMe /RegisterPython=0 /S /D=' + InstallDir,
      '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    MsgBox('Miniconda installer failed to launch.', mbError, MB_OK);
    exit;
  end;
  if ResultCode <> 0 then
    MsgBox('Miniconda installer exited with an error code. Setup will try to continue, ' +
           'but may fail at the next step.', mbError, MB_OK);
end;

// Called once, early in the wizard (see CurStepChanged), so CondaPythonPath
// is resolved and ready by the time [Run] needs it via GetCondaPython.
procedure EnsureCondaAvailable();
begin
  CondaPythonPath := FindExistingCondaPython();
  if CondaPythonPath <> '' then
    exit;

  InstallMinicondaViaInno();
  CondaPythonPath := FindExistingCondaPython();
  if CondaPythonPath = '' then
    MsgBox('Miniconda installation finished but python.exe still could not be found at the ' +
           'expected path. Setup cannot continue automatically -- please install Miniconda ' +
           'manually from https://docs.conda.io/en/latest/miniconda.html, then re-run this installer.',
           mbError, MB_OK);
end;

function GetCondaPython(Param: string): string;
begin
  Result := CondaPythonPath;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  // ssPostInstall runs after files are copied but before [Run] entries fire,
  // which is exactly when we need conda to exist and CondaPythonPath filled in.
  if CurStep = ssPostInstall then
    EnsureCondaAvailable();
end;
