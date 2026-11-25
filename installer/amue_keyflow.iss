; Amue KeyFlow installer for Inno Setup 6
; Build the app first (PyInstaller), then compile this script with ISCC.exe.
;
; Upgrades always land in {localappdata}\Programs\Amue KeyFlow, which Inno Setup
; upgrades in place because the AppId and directory never change. Earlier builds
; could also land in C:\Program Files when Setup was run elevated; those copies
; are removed before installing so only one installation ever exists.

#define AppName "Amue KeyFlow"
#define AppVersion "1.6.0"
#define AppPublisher "Amue"
#define AppExeName "AmueKeyFlow.exe"
#define AppId "{{8B1B0F2F-5E8E-47F0-9C2A-1E0B8A6C4D11}"
#define UninstallSubkey "Software\Microsoft\Windows\CurrentVersion\Uninstall\{{8B1B0F2F-5E8E-47F0-9C2A-1E0B8A6C4D11}}_is1"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}
; Fixed per-user location: no elevation, and every update replaces this copy.
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=output
OutputBaseFilename=AmueKeyFlow-{#AppVersion}-Setup
SetupIconFile=..\app\resources\icons\amue_keyflow.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\LICENSE
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked
Name: "startup"; Description: "Start {#AppName} with Windows (current user)"; GroupDescription: "Startup:"; Flags: unchecked

[InstallDelete]
; Remove the previous program files so no stale library survives an upgrade.
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\{#AppExeName}"

[Files]
Source: "..\dist\AmueKeyFlow\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; \
    ValueName: "AmueKeyFlow"; ValueData: """{app}\{#AppExeName}"" --autostart"; \
    Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
{ Remove an older copy that lives somewhere other than the target directory.
  A per-machine copy needs elevation, so Windows asks for it once via runas. }
procedure RemoveOldInstall(const Dir: String);
var
  ResultCode: Integer;
  Uninstaller: String;
begin
  if not DirExists(Dir) then
    Exit;
  Uninstaller := AddBackslash(Dir) + 'unins000.exe';
  if FileExists(Uninstaller) then
  begin
    if not Exec(Uninstaller, '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '',
                SW_HIDE, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
      ShellExec('runas', Uninstaller, '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '',
                SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
  { Folder left behind without an uninstaller (aborted install): delete it.
    Best effort only: a per-machine folder needs elevation, and a silent
    install must never raise a UAC prompt, so a failure here is ignored. }
  if DirExists(Dir) and not FileExists(Uninstaller) then
    DelTree(Dir, True, True, True);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
  Target, MachineDir, Subkey: String;
begin
  { A running tray instance keeps AmueKeyFlow.exe locked, which makes replacing
    it fail with "Access is denied". Close it before Setup copies files. }
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM AmueKeyFlow.exe', '',
       SW_HIDE, ewWaitUntilTerminated, ResultCode);

  Target := ExpandConstant('{app}');
  MachineDir := ExpandConstant('{commonpf}\{#AppName}');
  if CompareText(AddBackslash(MachineDir), AddBackslash(Target)) <> 0 then
  begin
    RemoveOldInstall(MachineDir);
    { Drop the per-machine registration a failed removal may have left behind. }
    Subkey := ExpandConstant('{#UninstallSubkey}');
    if (not DirExists(MachineDir)) and RegKeyExists(HKLM, Subkey) then
      RegDeleteKeyIncludingSubkeys(HKLM, Subkey);
  end;

  Result := '';
end;

[UninstallDelete]
; Remove only the bundled program files; user configuration in %APPDATA%\AmueKeyFlow is kept.
Type: filesandordirs; Name: "{app}\_internal"
