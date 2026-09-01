; Audiobook Studio PATCH installer.
;
; Ships a small code fix onto an EXISTING install. Crash reporting remains
; disabled by default and can only be configured locally; this installer must
; never embed or inject a reporting credential.
;
; This does NOT touch conda, torch, ffmpeg, or the model weights at all --
; only 8 small files (the changed app Python/UI files, config schema, and
; VERSION), all explicitly named, never a
; wildcard, so there is no risk of sweeping up a book PDF or the voice clip
; the way the main installer's `..\*` source spec has to guard against.
;
; Deliberately has NO conda/ffmpeg/weights Pascal Script at all -- that is
; where every bug in the main installer's history came from (see the
; installer-release skill). The only custom code here is a single FileExists
; check that refuses to proceed if it can't find an existing install, so this
; never silently creates a fresh empty folder instead of patching the real one.
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
#define MyAppVersion "1.0.2"
#define MyAppPublisher "Audiobook Studio"

[Setup]
; Same GUID as the main installer on purpose: this is an update to that same
; product, not a separate app, and sharing it is what makes UsePreviousAppDir
; find the real install location.
AppId={{FF5AC68A-1E05-4C9D-9B5D-204F12CD7183}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
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

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\app\server.py"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\app\narrate_worker.py"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\app\gpu_oom.py"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\app\launcher.py"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\app\static\index.html"; DestDir: "{app}\app\static"; Flags: ignoreversion
Source: "..\app\config.py"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\app\config.example.json"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\app\VERSION"; DestDir: "{app}\app"; Flags: ignoreversion

[Run]
; No Check needed here (unlike the main installer's SetupPySucceeded): a file
; copy either happened or the wizard already stopped, there is no partial
; setup.py state to gate on.
Filename: "{app}\runtime\miniconda3\pythonw.exe"; Parameters: """{app}\app\launcher.py"""; \
    WorkingDir: "{app}\app"; Description: "Launch {#MyAppName} now"; \
    Flags: postinstall skipifsilent nowait

[Code]
// {app} is not guaranteed initialized inside wpWelcome's NextButtonClick when
// DisableDirPage=yes (confirmed by a real silent-install crash: "attempt was
// made to expand the app constant before it was initialized"). PrepareToInstall
// is the point the main installer's own Miniconda check already proved safe
// for this: returning a non-empty string aborts cleanly with that message.
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if not FileExists(ExpandConstant('{app}\app\server.py')) then
  begin
    Result :=
      'Could not find an existing Audiobook Studio install at:' + #13#10 +
      ExpandConstant('{app}') + #13#10#13#10 +
      'This patch only updates an app that is already installed. Please run ' +
      'Setup_AudiobookStudio.exe (the full installer) first, then run this ' +
      'patch again.';
  end;
end;
