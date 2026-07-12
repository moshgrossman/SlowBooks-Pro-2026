; Inno Setup script for SlowBooks Pro 2026 (Windows installer).
; Built in CI: iscc /DAppVersion=<x.y.z> SlowBooksPro.iss
; Paths are relative to this .iss file (packaging/windows).
;
; All user data (.env, company databases, uploads, backups, logs) lives in
; %LOCALAPPDATA%\SlowBooksPro — this installer never writes there, upgrades
; replace only {app}, and the uninstaller leaves the data intact.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{f67ccf1c-2072-4f4a-9102-4e3897758a97}
AppName=SlowBooks Pro 2026
AppVersion={#AppVersion}
AppPublisher=VonHoltenCodes
AppPublisherURL=https://github.com/VonHoltenCodes/SlowBooks-Pro-2026
DefaultDirName={autopf}\SlowBooks Pro 2026
DefaultGroupName=SlowBooks Pro 2026
UninstallDisplayIcon={app}\SlowBooksPro.exe
OutputDir=.
OutputBaseFilename=SlowBooksPro-Setup-x64
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
WizardStyle=modern
DisableProgramGroupPage=yes
; Ask running instances to close before upgrading. The uvicorn server child
; (--_serve) has no window, so [Code] below also stops it by name.
CloseApplications=yes

[Files]
Source: "dist\SlowBooksPro\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{group}\SlowBooks Pro 2026"; Filename: "{app}\SlowBooksPro.exe"
Name: "{group}\Uninstall SlowBooks Pro 2026"; Filename: "{uninstallexe}"
Name: "{autodesktop}\SlowBooks Pro 2026"; Filename: "{app}\SlowBooksPro.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Run]
Filename: "{app}\SlowBooksPro.exe"; Description: "Launch SlowBooks Pro 2026"; Flags: nowait postinstall skipifsilent

[Code]
// The server runs as a second, windowless SlowBooksPro.exe process
// (--_serve). CloseApplications can't reach it (no window, no message
// loop), so stop every SlowBooksPro.exe by name before install/uninstall
// — otherwise file-in-use errors block the upgrade.
procedure KillAppProcesses();
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM SlowBooksPro.exe /T',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  KillAppProcesses();
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  KillAppProcesses();
  Result := True;
end;
