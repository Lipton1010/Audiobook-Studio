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
; The canonical build script checks Inno's output manifest before handing over
; the executable. 7-Zip cannot inspect an Inno-compiled installer.
;
; What this does, in order:
;   1. PrepareToInstall (before any file is copied): looks for the app's own
;      private conda base python; if absent, downloads and silently installs
;      Miniconda under {app}\runtime with Inno's built-in downloader (current user only, no admin:
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
;   4. Creates Start Menu + Desktop shortcuts that launch launcher.py through
;      the private pythonw.exe, so the native app window has no console behind it.
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
;   - Reuse a machine-wide Python. The one-click install owns a private
;     Miniconda under {app}\runtime so its 10 GB footprint stays together.

#define MyAppName "Audiobook Studio"
#define MyAppDirName "AudiobookStudio"
#define MyAppVersion "1.0.1"
#define MyAppPublisher "Audiobook Studio"

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
; Miniconda's Windows installer rejects or misbehaves with some destinations
; containing spaces. Keep the physical folder space-free while retaining the
; normal spaced product name everywhere the user sees it.
DefaultDirName={userpf}\{#MyAppDirName}
; Inno normally remembers the previous directory for the same AppId and lets it
; override DefaultDirName. Pre-release builds used "Audiobook Studio" with a
; space, so a retry could silently return to that obsolete path. Keep this
; unpublished 1.0 installer on the current space-free application root.
UsePreviousAppDir=no
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
; The embedded source is tiny, but Miniconda, the conda environment, pip cache,
; torch and model weights use roughly 10 GB after setup. Require 12 GiB beyond
; the installer payload so the environment build does not fail near the end.
ExtraDiskSpaceRequired=12884901888
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
; The private runtime is app-owned and is removed on uninstall. User data
; (books, voices, jobs, and generated audiobooks) is deliberately retained.
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
    Excludes: "*.pdf,*.wav,*.mp3,*.flac,*.ogg,*.m4a,*.m4b,*.aac,*.jpg,*.jpeg,*.pyc,__pycache__,.git,.claude,\tests\*,\app\jobs\*,\app\voices\*,\app\config.json,\app\*.log,\audiobooks\*,\ab_samples\*,\source_pdfs\*,\samples\Voice_Sample\*,\tools\*,\Output\*,\install\*.exe,\install_log.txt,\install_warnings.txt,\launcher_log.txt,\AUDIT_HANDOFF.md,\AUDIT_TRIAGE_HANDOFF.md"
; Extracted to {tmp}, not installed permanently, purely to be invoked once by
; the [Run] entry below. See that entry for why this is a separate step from
; the wildcard copy above (merge-safety into a config.json setup.py may have
; already written to).
Source: "merge_webhook_config.py"; DestDir: "{tmp}"

[Icons]
; pythonw.exe keeps the normal installed launch completely console-free.
; launcher.py redirects detached stdout/stderr to launcher_log.txt, and still
; uses MessageBoxW for a failure the user needs to see.
Name: "{group}\{#MyAppName}"; Filename: "{app}\runtime\miniconda3\pythonw.exe"; Parameters: """{app}\app\launcher.py"""; WorkingDir: "{app}\app"; IconFilename: "{app}\app\icon.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\runtime\miniconda3\pythonw.exe"; Parameters: """{app}\app\launcher.py"""; WorkingDir: "{app}\app"; Tasks: desktopicon; IconFilename: "{app}\app\icon.ico"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

[UninstallDelete]
; Byproducts created after installation, so they are not in the uninstall log
; and would otherwise leave the install folder behind. User data (app\jobs,
; app\voices, audiobooks) is deliberately NOT listed.
Type: files; Name: "{app}\install_log.txt"
Type: files; Name: "{app}\install_warnings.txt"
Type: files; Name: "{app}\miniconda_install_log.txt"
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\tools"
Type: filesandordirs; Name: "{app}\app\__pycache__"
Type: filesandordirs; Name: "{app}\install\__pycache__"

[Run]
; setup.py is NOT here on purpose -- see the ordering note in the header. The
; only two [Run] entries are this webhook wiring and the optional launch.
;
; Wires up the Discord crash reporter (config.py's error_webhook_url) by
; merging just that one key into config.json via merge_webhook_config.py
; (real json.loads/dumps).
;
; ORDERING, corrected 2026-08-23 after a real silent run proved the opposite
; assumption wrong: a [Run] entry WITHOUT the postinstall flag (this one only
; has runhidden) executes as the LAST step of the main install sequence,
; which is BEFORE ssPostInstall's CurStepChanged fires -- i.e. BEFORE
; RunSetupPy() has run. An instrumented build confirmed this directly: on a
; fresh install, config.json did not exist yet when this step ran. Only
; postinstall-flagged entries (the launch below) run later, on the Finished
; page, which is also why /VERYSILENT always skips them.
;
; Despite running first, this cannot lose chatterbox_python: both writers are
; independently merge-safe. This script preserves every existing key and
; touches only error_webhook_url; setup.py's pin_chatterbox_python() (called
; from RunSetupPy, which runs after this) reads the file back and adds only
; chatterbox_python, never a blind overwrite. So whichever of the two runs
; second still preserves what the first one wrote. That merge-safety, not
; execution order, is what actually prevents the race -- do not re-order
; these two steps on the assumption that order alone provides safety; if
; either write path ever becomes a blind overwrite, this breaks silently on
; the currently-lucky ordering. Not gated on SetupPySucceeded: writing one
; JSON key has no dependency on whether the (much heavier) environment build
; succeeded.
;
; THIS BUILD EMBEDS A LIVE WEBHOOK URL. Anyone with it can post to that
; Discord channel. This repo is PUBLIC, so a build with this step must NEVER
; be attached to a public GitHub Release -- only sent directly to specific
; people. A future public release must omit this [Files]/[Run] pair, or bake
; in an empty URL (config.py treats blank/missing as disabled).
Filename: "{app}\runtime\miniconda3\python.exe"; \
    Parameters: """{tmp}\merge_webhook_config.py"" ""{app}\app\config.json"" ""https://discord.com/api/webhooks/1541175653842558987/WzHMD2PFZVd7o4CLFrAgg7RmdqbwDuMYTnTDvq_4qJl7wnnkHxdRmXpEJduc6kVufvp4"""; \
    Flags: runhidden
; The optional launch, suppressed if setup.py failed so nobody is invited to
; start an app whose environment was never built.
Filename: "{app}\runtime\miniconda3\pythonw.exe"; Parameters: """{app}\app\launcher.py"""; \
    WorkingDir: "{app}\app"; Description: "Launch {#MyAppName} now"; \
    Flags: postinstall skipifsilent nowait; Check: SetupPySucceeded

[Code]
var
  CondaPythonPath: string;
  MinicondaFailureLogPath: string;
  SetupPyOk: Boolean;

function SetEnvironmentVariableW(lpName, lpValue: string): Boolean;
  external 'SetEnvironmentVariableW@kernel32.dll stdcall';

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

procedure SetManagedRuntimeEnvironment();
var
  RuntimeRoot: string;
  CacheRoot: string;
  MinicondaRoot: string;
begin
  // Do not call this before Miniconda's own installer has finished. The
  // installer invokes `conda constructor` internally; CONDA_NO_PLUGINS=true
  // removes that command and makes the pinned installer abort with code 2.
  // These settings are for Audiobook Studio's later conda/setup processes.
  RuntimeRoot := ExpandConstant('{app}\runtime');
  CacheRoot := RuntimeRoot + '\cache';
  MinicondaRoot := RuntimeRoot + '\miniconda3';
  SetEnvironmentVariableW('HF_HOME', CacheRoot + '\huggingface');
  SetEnvironmentVariableW('TORCH_HOME', CacheRoot + '\torch');
  SetEnvironmentVariableW('PIP_CACHE_DIR', CacheRoot + '\pip');
  SetEnvironmentVariableW('XDG_CACHE_HOME', CacheRoot);
  SetEnvironmentVariableW('XDG_CONFIG_HOME', RuntimeRoot + '\config');
  SetEnvironmentVariableW('CONDA_ENVS_PATH', MinicondaRoot + '\envs');
  SetEnvironmentVariableW('CONDA_PKGS_DIRS', MinicondaRoot + '\pkgs');
  SetEnvironmentVariableW('CONDA_REGISTER_ENVS', 'false');
  SetEnvironmentVariableW('CONDA_NO_PLUGINS', 'true');
  SetEnvironmentVariableW('CONDA_SOLVER', 'classic');
  SetEnvironmentVariableW('CONDA_ANACONDA_ANON_USAGE', 'false');
  SetEnvironmentVariableW('ANACONDA_ANON_USAGE', 'false');
end;

function InitializeSetup: Boolean;
begin
  // Default to True so the "Launch now" checkbox behaves normally; only an
  // actual non-zero exit from setup.py clears it.
  SetupPyOk := True;
  Result := True;
end;

// The one-click install deliberately does not reuse a machine-wide conda. Its
// Python, narrator environment, package cache and model weights belong under
// one {app}\runtime tree. Source installs still use normal conda discovery.
function FindPrivateCondaPython(): string;
var
  Candidate: string;
begin
  Candidate := ExpandConstant('{app}\runtime\miniconda3\python.exe');
  if FileExists(Candidate) then
    Result := Candidate
  else
    Result := '';
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

procedure AppendMinicondaInstallerLog(const S: String);
var
  Lines: TArrayOfString;
begin
  SetArrayLength(Lines, 1);
  Lines[0] := S;
  if not SaveStringsToUTF8FileWithoutBOM(MinicondaFailureLogPath, Lines, True) then
    Log('Could not append to Miniconda diagnostic log: ' + MinicondaFailureLogPath);
end;

procedure OnMinicondaInstallerOutput(const S: String; const Error, FirstLine: Boolean);
begin
  if Error then
    AppendMinicondaInstallerLog('[output capture error] ' + S)
  else
    AppendMinicondaInstallerLog(S);
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
  InstallLogPath: string;
  Params: string;
  ResultCode: Integer;
begin
  Result := False;
  InstallerPath := ExpandConstant('{tmp}\') + MinicondaFile;
  InstallDir := ExpandConstant('{app}\runtime\miniconda3');
  Params := '/InstallationType=JustMe /RegisterPython=0 /S /D=' + InstallDir;
  MinicondaFailureLogPath := ExpandConstant('{userpf}\AudiobookStudio_Miniconda_Install.log');
  DeleteFile(MinicondaFailureLogPath);
  AppendMinicondaInstallerLog('Audiobook Studio Miniconda child-process log');
  AppendMinicondaInstallerLog('Executable: ' + InstallerPath);
  AppendMinicondaInstallerLog('Resolved application directory: ' + ExpandConstant('{app}'));
  AppendMinicondaInstallerLog('Working directory: ' + ExpandConstant('{userpf}'));
  AppendMinicondaInstallerLog('Arguments: ' + Params);

  // This function is called only when the private python.exe was not found.
  // Miniconda refuses to install into any non-empty target, so remove an
  // incomplete app-owned target left by an interrupted or rolled-back attempt.
  // A complete private runtime is never removed here, and user data lives
  // outside runtime\miniconda3.
  if FileExists(InstallDir + '\python.exe') then
  begin
    AppendMinicondaInstallerLog('A complete private Miniconda appeared before installation; reusing it.');
    Result := True;
    exit;
  end;
  if DirExists(InstallDir) then
  begin
    AppendMinicondaInstallerLog('Removing incomplete private Miniconda target before retry: ' + InstallDir);
    if not DelTree(InstallDir, True, True, True) then
    begin
      AppendMinicondaInstallerLog('Could not remove the incomplete private Miniconda target.');
      MsgBox('Setup found an incomplete private Miniconda installation but could not remove it:' + #13#10#13#10 +
             InstallDir + #13#10#13#10 +
             'Close programs using that folder and run Setup again.' + #13#10#13#10 +
             'Diagnostic log:' + #13#10 + MinicondaFailureLogPath,
             mbError, MB_OK);
      exit;
    end;
    if DirExists(InstallDir) then
    begin
      AppendMinicondaInstallerLog('The incomplete private Miniconda target still exists after cleanup.');
      MsgBox('Setup could not completely remove an earlier partial Miniconda installation:' + #13#10#13#10 +
             InstallDir + #13#10#13#10 +
             'Diagnostic log:' + #13#10 + MinicondaFailureLogPath,
             mbError, MB_OK);
      exit;
    end;
    AppendMinicondaInstallerLog('Incomplete private Miniconda target removed successfully.');
  end;

  // PrepareToInstall runs before [Files], so {app}\runtime does not exist yet.
  // Create the parent explicitly rather than relying on Miniconda's NSIS
  // wrapper to create multiple missing levels from its /D argument.
  if not ForceDirectories(ExpandConstant('{app}\runtime')) then
  begin
    MsgBox('Could not create Audiobook Studio''s private runtime folder at:' + #13#10 +
           ExpandConstant('{app}\runtime'), mbError, MB_OK);
    exit;
  end;

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
  // Empty WorkingDir made Inno use the downloaded executable's private {tmp}
  // directory, unlike both successful physical command-line runs. Give the
  // child the stable, user-writable {userpf} directory explicitly.
  // ExecAndLogOutput also supplies real stdout/stderr handles; constructor's
  // silent NSIS installer prints its transient .step.log there and then deletes
  // that file. Persist
  // every line so another child failure cannot collapse to an opaque code 2.
  try
    if not ExecAndLogOutput(InstallerPath, Params,
        ExpandConstant('{userpf}'), SW_SHOWNORMAL, ewWaitUntilTerminated,
        ResultCode, @OnMinicondaInstallerOutput) then
    begin
      AppendMinicondaInstallerLog('Failed to launch: ' + SysErrorMessage(ResultCode));
      MsgBox('The Miniconda installer failed to launch.' + #13#10#13#10 +
             'Diagnostic log:' + #13#10 + MinicondaFailureLogPath,
             mbError, MB_OK);
      exit;
    end;
  except
    AppendMinicondaInstallerLog('Output-capture exception: ' + GetExceptionMessage);
    MsgBox('The Miniconda installer could not be launched with output capture:' + #13#10#13#10 +
           GetExceptionMessage + #13#10#13#10 + 'Diagnostic log:' + #13#10 +
           MinicondaFailureLogPath, mbError, MB_OK);
    exit;
  end;
  AppendMinicondaInstallerLog('Exit code: ' + IntToStr(ResultCode));

  if ResultCode <> 0 then
  begin
    MsgBox('The Miniconda installer exited with error code ' + IntToStr(ResultCode) +
           '.' + #13#10#13#10 + 'Target folder:' + #13#10 + InstallDir + #13#10#13#10 +
           'Diagnostic log:' + #13#10 + MinicondaFailureLogPath,
           mbError, MB_OK);
    exit;
  end;

  // On success keep the same evidence inside the application tree. On failure
  // the copy beside {app} under the user's Programs directory survives Inno
  // rolling back {app}.
  InstallLogPath := ExpandConstant('{app}\miniconda_install_log.txt');
  if FileExists(InstallLogPath) then
    DeleteFile(InstallLogPath);
  if not RenameFile(MinicondaFailureLogPath, InstallLogPath) then
    Log('Could not move Miniconda diagnostic log into the application folder.');
  Result := True;
end;

// Runs BEFORE any file is copied. Returning a non-empty string stops Setup on
// the "Preparing to Install" page and shows that string as the error, which is
// exactly the behaviour wanted here: no conda means nothing downstream can
// work, so do not create shortcuts to a broken install.
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  CondaPythonPath := FindPrivateCondaPython();
  if CondaPythonPath = '' then
  begin
    if not InstallMinicondaViaInno() then
    begin
      Result := 'Audiobook Studio''s private Miniconda runtime could not be installed. ' +
                'Setup stopped before copying the app files.' + #13#10#13#10 +
                'Do not install Miniconda manually: this installer deliberately uses ' +
                'its own isolated copy. Send the error-code screenshot to whoever gave ' +
                'you this installer.';
      exit;
    end;

    CondaPythonPath := FindPrivateCondaPython();
    if CondaPythonPath = '' then
    begin
      Result := 'Miniconda reported a successful install but python.exe is not at the ' +
                'expected private runtime location:' + #13#10 +
                ExpandConstant('{app}\runtime\miniconda3\python.exe') + #13#10#13#10 +
                'Run this installer again. If it repeats, send install_log.txt to ' +
                'whoever gave you the installer.';
      exit;
    end;
  end;

  // Miniconda is now complete. Its internal constructor command is no longer
  // needed, so subsequent setup.py and conda children can use the isolated,
  // plugin-free managed environment.
  SetManagedRuntimeEnvironment();
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
            '" --yes --auto-install-ffmpeg --prefetch-weights --runtime-root "' +
            ExpandConstant('{app}\runtime') + '" > "' + LogPath + '" 2>&1"';

  WizardForm.StatusLabel.Caption :=
    'Setting up Audiobook Studio. This downloads several gigabytes and uses ' +
    'about 10 GB of disk space. It can take 15-30 minutes. It is not frozen.';
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
