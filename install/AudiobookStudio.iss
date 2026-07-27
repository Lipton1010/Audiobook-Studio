; Audiobook Studio installer (Inno Setup script)
;
; BUILD IT WITH install\build_installer.bat, NOT by opening this file directly.
; That script stages a clean copy of the repo with `git archive` first, so only
; tracked files can ever be packaged. Compiling straight from D:\Audiobook_Pipeline
; would sweep up whatever else is sitting in the working tree (purchased PDFs,
; the voice clip, audit notes). The Excludes list below is a second line of
; defense, not the primary one.
;
; Manual build, if you really want it:
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" install\AudiobookStudio.iss
;   -> Output\Setup_AudiobookStudio.exe
; Then open the resulting .exe with 7-Zip and LIST ITS CONTENTS before sending
; it to anyone. This has never been verified on a real machine.
;
; What this does, in order:
;   1. PrepareToInstall (before any file is copied): looks for an existing
;      conda base python; if none, downloads and silently installs Miniconda
;      with Inno's built-in downloader (current user only, no admin:
;      /InstallationType=JustMe /RegisterPython=0 /S /D=path). This has to be
;      Pascal Script, not install\bootstrap_conda.py, because on a truly clean
;      machine there is no Python yet to run that script with. If it fails,
;      setup ABORTS here with a readable message instead of installing a
;      half-working app.
;   2. [Files] copies the repo to the install folder.
;   3. ssPostInstall runs setup.py --yes --auto-install-ffmpeg
;      --prefetch-weights with the conda python from step 1, redirecting all
;      output to install_log.txt, and CHECKS ITS EXIT CODE. setup.py in turn
;      calls install\bootstrap_ffmpeg.py and install\bootstrap_weights.py.
;   4. Creates Start Menu + Desktop shortcuts pointing at
;      Start_Audiobook_Studio.bat, which opens a native app window (pywebview)
;      instead of a browser tab.
;
; Why setup.py is NOT a [Run] entry: Inno processes [Run] as the LAST part of
; the actual installation, and fires ssPostInstall AFTER that. The first
; version of this script installed conda in ssPostInstall and ran setup.py
; from [Run], i.e. exactly backwards -- setup.py got an empty python path,
; produced no log at all, and the wizard still reported success.
;
; What it deliberately does NOT do:
;   - Install or upgrade an NVIDIA driver. If there's no GPU, setup.py reports
;     that clearly; this installer does not try to fix it.
;   - Touch Ollama in any way. It is optional (scanned-image books / Path B
;     only) and is commonly shared with other things on a user's machine, so
;     installing or upgrading it is not this installer's business.
;   - Install a bundled Python. It relies on the Miniconda it just installed
;     (or found) to run setup.py itself, since setup.py is stdlib-only.

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
; Emit the list of every file actually embedded in the .exe. This is the ONLY
; reliable way to audit what shipped: 7-Zip cannot open an Inno-compiled
; installer at all (it reports "Cannot open the file as archive"), so the
; old advice to inspect the .exe with 7-Zip could never have worked.
; build_installer.bat greps this manifest and refuses to hand over a build
; that contains a book, an audio file, or the voice clip.
OutputManifestFile=Setup_AudiobookStudio-manifest.txt
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
; Uninstall removes the files this installer copied plus its own byproducts
; (see [UninstallDelete]). It does NOT remove Miniconda, the conda envs, the
; Hugging Face weight cache, or any book/audio the user produced. Those are
; either shared with other software or are the user's own data; deleting them
; on uninstall would be worse than leaving them. Removing them by hand:
;   conda env remove -n chatterbox
;   rmdir /s "%USERPROFILE%\.cache\huggingface"
UninstallDisplayIcon={app}\app\icon.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
; Source is the repo root (one level up from install\, where this .iss lives).
;
; EXCLUDES SEMANTICS, easy to get wrong: Inno is NOT gitignore. Per the [Files]
; docs, a pattern starting with "\" is matched against the START of the
; relative path, and anything else is matched against the END of it. So "\*.pdf"
; excludes ONLY a pdf sitting in the repo root, while "*.pdf" excludes pdfs
; anywhere. The first version of this file copied .gitignore's patterns and
; added a leading backslash to each, which means the opposite of what git does;
; it would have packaged every purchased book under source_pdfs\ and samples\
; plus the voice clip that CLAUDE.md says must never be distributed.
Source: "..\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; \
    Excludes: "*.pdf,*.wav,*.mp3,*.flac,*.ogg,*.m4a,*.m4b,*.aac,*.jpg,*.jpeg,*.pyc,__pycache__,.git,.claude,\app\jobs\*,\app\voices\*,\app\config.json,\app\*.log,\audiobooks\*,\ab_samples\*,\source_pdfs\*,\samples\Voice_Sample\*,\tools\*,\Output\*,\install\*.exe,\install_log.txt,\install_warnings.txt,\launcher_log.txt,\AUDIT_HANDOFF.md,\AUDIT_TRIAGE_HANDOFF.md"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\app\icon.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon; IconFilename: "{app}\app\icon.ico"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

[UninstallDelete]
; Byproducts created after installation, so they are not in the uninstall log
; and would otherwise leave the install folder behind. User data (app\jobs,
; app\voices, audiobooks) is deliberately NOT listed.
Type: files; Name: "{app}\install_log.txt"
Type: files; Name: "{app}\install_warnings.txt"
Type: filesandordirs; Name: "{app}\tools"
Type: filesandordirs; Name: "{app}\app\__pycache__"
Type: filesandordirs; Name: "{app}\install\__pycache__"

[Run]
; setup.py is NOT here on purpose -- see the ordering note in the header. The
; only [Run] entry is the optional launch, and it is suppressed if setup.py
; failed, so nobody is invited to start an app whose env was never built.
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName} now"; \
    Flags: postinstall skipifsilent shellexec; Check: SetupPySucceeded

[Code]
var
  CondaPythonPath: string;
  SetupPyOk: Boolean;

const
  // PINNED, and kept in sync with install/bootstrap_conda.py's MINICONDA_FILE
  // and MINICONDA_SHA256. Miniconda3-latest is a moving alias (as of 2026-07-08
  // it is byte-identical to the py314 build), so an unpinned install would give
  // a friend a different base Python from the 3.13 one everything was verified
  // on, and a moving alias has no stable hash to verify against. Passing the
  // SHA-256 as DownloadTemporaryFile's 3rd argument makes Inno verify it and
  // raise on mismatch, so a corrupted or swapped 125 MB executable is never
  // run. To bump, update both files from https://repo.anaconda.com/miniconda/
  MinicondaFile = 'Miniconda3-py313_26.5.3-1-Windows-x86_64.exe';
  MinicondaUrl = 'https://repo.anaconda.com/miniconda/Miniconda3-py313_26.5.3-1-Windows-x86_64.exe';
  MinicondaSha256 = 'c229a161e9fad48fd7d2c701da363e6a307b233eba379cd967bc26aa2cb3fa68';

function InitializeSetup: Boolean;
begin
  // Default to True so the "Launch now" checkbox behaves normally; only an
  // actual non-zero exit from setup.py clears it.
  SetupPyOk := True;
  Result := True;
end;

// Finds an already-installed conda's base python.exe at the usual locations.
// Kept in sync with setup.py's find_conda() and Start_Audiobook_Studio.bat's
// own search list, so the three cannot disagree about what counts as "conda is
// present". KNOWN LIMITATION: this cannot see a conda that is only reachable
// via PATH at a nonstandard root (setup.py checks shutil.which("conda") first
// and this cannot). Worst case that installs a second, unused Miniconda.
function FindExistingCondaPython(): string;
var
  Candidates: array[0..6] of string;
  I: Integer;
begin
  Candidates[0] := ExpandConstant('{%USERPROFILE}\miniconda3\python.exe');
  Candidates[1] := ExpandConstant('{%USERPROFILE}\anaconda3\python.exe');
  Candidates[2] := ExpandConstant('{%USERPROFILE}\miniforge3\python.exe');
  Candidates[3] := 'C:\ProgramData\miniconda3\python.exe';
  Candidates[4] := 'C:\ProgramData\anaconda3\python.exe';
  Candidates[5] := 'C:\miniconda3\python.exe';
  Candidates[6] := 'C:\anaconda3\python.exe';
  Result := '';
  for I := 0 to 6 do
  begin
    if FileExists(Candidates[I]) then
    begin
      Result := Candidates[I];
      exit;
    end;
  end;
end;

function OnMinicondaDownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  if ProgressMax > 0 then
    WizardForm.PreparingLabel.Caption :=
      Format('Downloading Miniconda... %d MB of %d MB', [Progress div 1048576, ProgressMax div 1048576])
  else
    WizardForm.PreparingLabel.Caption :=
      Format('Downloading Miniconda... %d MB', [Progress div 1048576]);
  Result := True;
end;

// Downloads and silently runs the official Miniconda installer using Inno's
// built-in downloader (no Python needed). Same silent flags as
// install/bootstrap_conda.py, kept in sync deliberately.
//
// DownloadTemporaryFile's real signature is
//   (Url, BaseName, RequiredSHA256OfFile: String; OnDownloadProgress: TOnDownloadProgress): Int64
// It RAISES on failure and returns a byte count, so it must be wrapped in
// try/except and must not be tested as a Boolean. The first version of this
// script passed a destination path as the 4th argument and treated the result
// as a Boolean, which is a hard compile error (type mismatch) -- the installer
// could never have been built at all.
function InstallMinicondaViaInno(): Boolean;
var
  InstallerPath: string;
  InstallDir: string;
  ResultCode: Integer;
begin
  Result := False;
  InstallerPath := ExpandConstant('{tmp}\') + MinicondaFile;
  InstallDir := ExpandConstant('{%USERPROFILE}\miniconda3');

  WizardForm.PreparingLabel.Caption := 'Downloading Miniconda (first-time setup)...';
  try
    // BaseName is written under {tmp}; that is what InstallerPath points at.
    // The 3rd argument is a required SHA-256: Inno checks it and raises if the
    // download does not match, so the except branch below covers both a failed
    // download and a corrupted or substituted one.
    DownloadTemporaryFile(MinicondaUrl, MinicondaFile, MinicondaSha256, @OnMinicondaDownloadProgress);
  except
    // NOTE: no continuation line may start with '#'. ISPP treats a line whose
    // first non-blank character is '#' as a preprocessor directive, so a wrapped
    // '#13#10' at the start of a line aborts the compile with 'Unknown
    // preprocessor directive'. Keep the newline constants mid-line.
    MsgBox('Could not download Miniconda:' + #13#10#13#10 + GetExceptionMessage + #13#10#13#10 +
           'Check your internet connection and run this installer again. ' +
           'If the message mentions a hash or checksum, the pinned Miniconda build ' +
           'has been replaced upstream and this installer needs rebuilding.',
           mbError, MB_OK);
    exit;
  end;

  if not FileExists(InstallerPath) then
  begin
    MsgBox('Miniconda downloaded but the installer file was not found at' + #13#10 +
           InstallerPath, mbError, MB_OK);
    exit;
  end;

  WizardForm.PreparingLabel.Caption := 'Installing Miniconda (this can take a few minutes)...';
  // /D must be LAST and must not be quoted, per Anaconda's own silent-install
  // docs. Do not add arguments after it.
  if not Exec(InstallerPath,
      '/InstallationType=JustMe /RegisterPython=0 /S /D=' + InstallDir,
      '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    MsgBox('The Miniconda installer failed to launch.', mbError, MB_OK);
    exit;
  end;
  if ResultCode <> 0 then
  begin
    MsgBox('The Miniconda installer exited with error code ' + IntToStr(ResultCode) + '.',
           mbError, MB_OK);
    exit;
  end;
  Result := True;
end;

// Runs BEFORE any file is copied. Returning a non-empty string stops Setup on
// the "Preparing to Install" page and shows that string as the error, which is
// exactly the behaviour wanted here: no conda means nothing downstream can
// work, so do not create shortcuts to a broken install.
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  CondaPythonPath := FindExistingCondaPython();
  if CondaPythonPath <> '' then
    exit;

  if not InstallMinicondaViaInno() then
  begin
    Result := 'Miniconda could not be installed automatically, and Audiobook Studio ' +
              'needs it. Install Miniconda yourself from ' +
              'https://www.anaconda.com/docs/getting-started/miniconda/install ' +
              '(the default options are fine), then run this installer again.';
    exit;
  end;

  CondaPythonPath := FindExistingCondaPython();
  if CondaPythonPath = '' then
    Result := 'Miniconda reported a successful install but python.exe is not at the ' +
              'expected location (%USERPROFILE%\miniconda3\python.exe). Install ' +
              'Miniconda manually from ' +
              'https://www.anaconda.com/docs/getting-started/miniconda/install ' +
              'and run this installer again.';
end;

// Everything is piped through cmd /C so stdout+stderr land in install_log.txt,
// because "send me the whole terminal output" (the README's ask when an install
// fails) needs a file to point at when there was never a visible terminal.
//
// QUOTING, easy to get wrong: cmd /C with more than two quote characters strips
// the FIRST and LAST quote on the line. So the whole command needs one extra
// enclosing pair, otherwise cmd mangles both the exe path and the redirect
// target and dies with "The filename, directory name, or volume label syntax is
// incorrect" -- writing no log file at all, in the default install location,
// which always contains a space.
procedure RunSetupPy();
var
  Params: string;
  LogPath: string;
  WarnPath: string;
  WarnLines: TArrayOfString;
  WarnMsg: string;
  ResultCode: Integer;
  I: Integer;
begin
  LogPath := ExpandConstant('{app}\install_log.txt');
  WarnPath := ExpandConstant('{app}\install_warnings.txt');
  Params := '/C ""' + CondaPythonPath + '" "' + ExpandConstant('{app}\setup.py') +
            '" --yes --auto-install-ffmpeg --prefetch-weights > "' + LogPath + '" 2>&1"';

  WizardForm.StatusLabel.Caption :=
    'Setting up Audiobook Studio. This downloads about 3-4 GB (PyTorch and the ' +
    'voice model) and can take 15-30 minutes. It is not frozen.';
  WizardForm.ProgressGauge.Style := npbstMarquee;

  if not Exec(ExpandConstant('{cmd}'), Params, ExpandConstant('{app}'),
              SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    ResultCode := -1;

  WizardForm.ProgressGauge.Style := npbstNormal;

  if ResultCode <> 0 then
  begin
    SetupPyOk := False;
    MsgBox('Audiobook Studio''s Python environment did not finish building ' +
           '(setup.py exited with code ' + IntToStr(ResultCode) + ').' + #13#10#13#10 +
           'The app is installed but will not narrate until this is fixed. The full ' +
           'log is at:' + #13#10 + LogPath + #13#10#13#10 +
           'Send that file to whoever gave you this installer. You can also retry ' +
           'without reinstalling by running setup.bat in the install folder.',
           mbError, MB_OK);
    exit;
  end;

  // setup.py writes install_warnings.txt only when there is something the user
  // genuinely needs to know (no GPU, no ffmpeg, weights not pre-fetched). A
  // hidden console means these would otherwise scroll past invisibly and the
  // wizard would claim unqualified success.
  if LoadStringsFromFile(WarnPath, WarnLines) then
  begin
    WarnMsg := '';
    for I := 0 to GetArrayLength(WarnLines) - 1 do
      WarnMsg := WarnMsg + WarnLines[I] + #13#10;
    if WarnMsg <> '' then
      MsgBox('Audiobook Studio installed, but with warnings:' + #13#10#13#10 +
             WarnMsg + #13#10 + 'Full log: ' + LogPath, mbInformation, MB_OK);
  end;
end;

function SetupPySucceeded(): Boolean;
begin
  Result := SetupPyOk;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  // ssPostInstall fires just after the actual installation finishes, which is
  // after [Files] has copied setup.py into {app}. That is the earliest point
  // setup.py exists on disk and the latest point we can still show the user a
  // message on the wizard rather than in a console they will never see.
  if CurStep = ssPostInstall then
    RunSetupPy();
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID <> wpFinished then
    exit;
  // The default "Setup has finished installing" text is a lie when setup.py
  // failed, and the failure message box has already been dismissed by now.
  if SetupPyOk then
    WizardForm.FinishedLabel.Caption :=
      'Audiobook Studio is installed.' + #13#10#13#10 +
      'Start it from the Start Menu (or the desktop shortcut). The first launch ' +
      'takes a minute while the voice model loads.' + #13#10#13#10 +
      'If anything misbehaves, the full install log is at ' +
      ExpandConstant('{app}\install_log.txt') + '. Send that file along when ' +
      'reporting a problem.'
  else
    WizardForm.FinishedLabel.Caption :=
      'Audiobook Studio was copied to your computer, but its Python environment ' +
      'did not finish building, so it cannot narrate anything yet.' + #13#10#13#10 +
      'Send this file to whoever gave you this installer:' + #13#10 +
      ExpandConstant('{app}\install_log.txt') + #13#10#13#10 +
      'Or retry the environment build by running setup.bat in ' +
      ExpandConstant('{app}') + '.';
end;
