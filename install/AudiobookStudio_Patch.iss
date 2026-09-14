; Audiobook Studio PATCH installer.
;
; Ships a small code fix onto an EXISTING install. Crash reporting remains
; disabled by default and can only be configured locally; this installer must
; never embed or inject a reporting credential.
;
; This updates code, then provisions VibeVoice and its separate CPU quality
; runtime below the existing app-owned runtime folder. It never changes the
; legacy Chatterbox environment, user books, voices, jobs, or audiobooks.
;
; The post-copy provisioning is deliberately small and uses the existing
; private base Python. It writes a durable install_log.txt and suppresses
; launch on failure, so an old install never appears upgraded when narration
; cannot start.
;
; Shares the main installer's AppId, so Inno's own UsePreviousAppDir (default
; yes, NOT overridden here unlike the main script) auto-detects wherever the
; app actually got installed, without the user needing to know or browse for
; the path. DisableDirPage=yes hides the directory page entirely: Welcome,
; then straight to Install, then Finished. Nothing to click wrong.
;
; Build: install\build_installer.bat patch
;   -> Output\Setup_AudiobookStudio_Patch.exe
;
; Requires Audiobook Studio already installed via Setup_AudiobookStudio.exe.
;
#define MyAppName "Audiobook Studio"
#define MyAppDirName "AudiobookStudio"
#define MyAppVersion "1.0.5"
#define MyAppPublisher "Audiobook Studio"

[Setup]
; Same GUID as the main installer on purpose: this is an update to that same
; product, not a separate app, and sharing it is what makes UsePreviousAppDir
; find the real install location.
AppId={{FF5AC68A-1E05-4C9D-9B5D-204F12CD7183}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppMutex=AudiobookStudio_1E05_4C9D_9B5D_204F12CD7183
DefaultDirName={userpf}\{#MyAppDirName}
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
OutputDir=..\Output
OutputBaseFilename=Setup_AudiobookStudio_Patch
; Same audit habit as the main installer: this file lists every file actually
; embedded, so it can be checked before handing the .exe to anyone.
OutputManifestFile=Setup_AudiobookStudio_Patch-manifest.txt
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\app\icon.ico
ExtraDiskSpaceRequired=12884901888

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\app\server.py"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\app\narrate_worker.py"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\app\vibevoice_plan.py"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\app\vibevoice_worker.py"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\app\vibevoice_quality.py"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\app\vibevoice_assembly.py"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\app\vibevoice_audio.py"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\install\bootstrap_vibevoice.py"; DestDir: "{app}\install"; Flags: ignoreversion
Source: "..\install\check_running_app.ps1"; DestDir: "{app}\install"; Flags: ignoreversion
; PrepareToInstall runs before normal [Files] copying, so it extracts this
; duplicate temporary payload for the running-app guard on pre-1.0.5 targets.
Source: "..\install\check_running_app.ps1"; Flags: dontcopy
Source: "..\install\requirements-vibevoice.txt"; DestDir: "{app}\install"; Flags: ignoreversion
Source: "..\install\requirements-narration-quality.txt"; DestDir: "{app}\install"; Flags: ignoreversion
Source: "..\app\narration_eta.py"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\app\batched_narrate.py"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\app\narration_safety.py"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\app\assembly_metadata.py"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\app\pipeline_text.py"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\app\visual_review.py"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\app\convert_voice.py"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\app\gpu_oom.py"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\app\launcher.py"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\app\managed_runtime.py"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\app\static\index.html"; DestDir: "{app}\app\static"; Flags: ignoreversion
Source: "..\app\static\storybird-mark.svg"; DestDir: "{app}\app\static"; Flags: ignoreversion
Source: "..\app\config.py"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\app\config.example.json"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\app\VERSION"; DestDir: "{app}\app"; Flags: ignoreversion

[Run]
Filename: "{app}\runtime\miniconda3\pythonw.exe"; Parameters: """{app}\app\launcher.py"""; \
    WorkingDir: "{app}\app"; Description: "Launch {#MyAppName} now"; \
    Flags: postinstall skipifsilent nowait; Check: PatchSetupSucceeded

[Code]
var
  PatchSetupOk: Boolean;
  AppProcessCheckError: Boolean;

function PrivateBasePython(): string;
begin
  Result := ExpandConstant('{app}\runtime\miniconda3\python.exe');
end;

function PrivateConda(): string;
begin
  Result := ExpandConstant('{app}\runtime\miniconda3\Scripts\conda.exe');
end;

function PatchSetupSucceeded(): Boolean;
begin
  Result := PatchSetupOk;
end;

function InstalledAppIsRunning(): Boolean;
var
  Params: string;
  ResultCode: Integer;
begin
  // The packaged script matches command lines for this exact installation.
  // This covers legacy sessions that predate the named mutex and custom ports.
  AppProcessCheckError := False;
  ExtractTemporaryFile('check_running_app.ps1');
  Params := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
    ExpandConstant('{tmp}\check_running_app.ps1') + '" -AppRoot "' +
    ExpandConstant('{app}') + '"';
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Params,
              ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    AppProcessCheckError := True;
    Result := True;
    exit;
  end;
  if ResultCode = 0 then
    Result := False
  else if ResultCode = 9 then
    Result := True
  else
  begin
    AppProcessCheckError := True;
    Result := True;
  end;
end;

// {app} is not guaranteed initialized inside wpWelcome's NextButtonClick when
// DisableDirPage=yes (confirmed by a real silent-install crash: "attempt was
// made to expand the app constant before it was initialized"). PrepareToInstall
// is the point the main installer's own Miniconda check already proved safe
// for this: returning a non-empty string aborts cleanly with that message.
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  PatchSetupOk := False;
  if not FileExists(ExpandConstant('{app}\app\server.py')) then
  begin
    Result :=
      'Could not find an existing Audiobook Studio install at:' + #13#10 +
      ExpandConstant('{app}') + #13#10#13#10 +
      'This patch only updates an app that is already installed. Please run ' +
      'Setup_AudiobookStudio.exe (the full installer) first, then run this ' +
      'patch again.';
    exit;
  end;
  if InstalledAppIsRunning() then
  begin
    if AppProcessCheckError then
      Result :=
        'Setup could not safely determine whether this Audiobook Studio install ' +
        'is running. Close Audiobook Studio and retry the patch. No files were changed.'
    else
      Result :=
        'Audiobook Studio is currently running from this installation:' + #13#10#13#10 +
        ExpandConstant('{app}') + #13#10#13#10 +
        'Close it and retry the patch. Setup does not replace server or worker ' +
        'files while a narration might be in progress.';
    exit;
  end;
  if not FileExists(PrivateBasePython()) or not FileExists(PrivateConda()) then
  begin
    Result :=
      'This existing Audiobook Studio install does not have the private runtime ' +
      'required for the 1.0.5 VibeVoice upgrade:' + #13#10#13#10 +
      ExpandConstant('{app}\runtime\miniconda3') + #13#10#13#10 +
      'Run the 1.0.5 full installer to repair or create the isolated runtime, ' +
      'then run this patch again. Your books, voices, jobs, and audiobooks are preserved.';
  end;
end;

procedure RunVibeVoiceSetup();
var
  Params: string;
  LogPath: string;
  ResultCode: Integer;
begin
  LogPath := ExpandConstant('{app}\install_log.txt');
  Params := '/C ""' + PrivateBasePython() + '" "' +
            ExpandConstant('{app}\install\bootstrap_vibevoice.py') +
            '" --install --conda "' + PrivateConda() +
            '" --runtime-root "' + ExpandConstant('{app}\runtime') +
            '" --config "' + ExpandConstant('{app}\app\config.json') +
            '" >> "' + LogPath + '" 2>&1"';
  WizardForm.StatusLabel.Caption :=
    'Adding VibeVoice 1.5B and its CPU quality checker. This downloads several ' +
    'gigabytes and can take 15-30 minutes. It is not frozen.';
  WizardForm.ProgressGauge.Style := npbstMarquee;
  if not Exec(ExpandConstant('{cmd}'), Params, ExpandConstant('{app}'),
              SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    ResultCode := -1;
  WizardForm.ProgressGauge.Style := npbstNormal;
  if ResultCode <> 0 then
  begin
    MsgBox('The 1.0.5 VibeVoice runtime did not finish building (exit code ' +
           IntToStr(ResultCode) + '). The patch files were copied, but the app ' +
           'will not launch so it cannot run with a partial runtime.' + #13#10#13#10 +
           'Full diagnostic log:' + #13#10 + LogPath + #13#10#13#10 +
           'Close the installer, fix the reported network or disk problem, and ' +
           'run this patch again. Existing books, voices, jobs, and audiobooks ' +
           'were not changed.', mbError, MB_OK);
    exit;
  end;
  PatchSetupOk := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    RunVibeVoiceSetup();
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID <> wpFinished then
    exit;
  if PatchSetupOk then
    WizardForm.FinishedLabel.Caption :=
      'Audiobook Studio 1.0.5 is ready. VibeVoice 1.5B is selected for new books.'
  else
    WizardForm.FinishedLabel.Caption :=
      'The patch copied its files, but VibeVoice setup failed. The app was not ' +
      'launched. Read install_log.txt in the Audiobook Studio folder, then run ' +
      'this patch again after fixing the reported problem.';
end;

function GetCustomSetupExitCode(): Integer;
begin
  if PatchSetupOk then
    Result := 0
  else
    Result := 1;
end;
