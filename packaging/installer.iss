; Inno Setup script for iPhone App Manager.
; Built by:  .venv-build\Scripts\python.exe packaging\build.py --installer
; (build.py passes AppVersion, SourceDir and OutputDir; the defaults below match the project layout.)

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\iPhone App Manager"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist\installer"
#endif
; Microsoft Visual C++ Redistributable (x64) prerequisite. It is NOT bundled; setup checks for it and warns.
; The minimum version comes from packaging\runtime_policy.py (build.py passes the same numbers); see the
; evidence in that file. The registry key and value names are those the Microsoft redistributable writes.
#ifndef VcMinMajor
  #define VcMinMajor 14
#endif
#ifndef VcMinMinor
  #define VcMinMinor 43
#endif
#ifndef VcMinBld
  #define VcMinBld 34808
#endif
#ifndef VcMinRbld
  #define VcMinRbld 0
#endif
#define VcRuntimeKey "SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"
#define VcDownloadUrl "https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist"
#define AppName "iPhone App Manager"
#define AppExe "iPhone App Manager.exe"
; Must match SetCurrentProcessExplicitAppUserModelID in main.py so pinned shortcuts and the
; running window share one taskbar button.
#define AppUserModelID "iPhoneAppManager.App"

[Setup]
; Permanent identity of the app - never change it, or upgrades/uninstall will not find old installs.
AppId={{27831A4C-13D0-478F-9501-EDC599011401}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
; Per-user install by default (no administrator prompt): %LOCALAPPDATA%\Programs\iPhone App Manager.
; The user may still choose "install for all users" (needs administrator rights).
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
OutputDir={#OutputDir}
OutputBaseFilename={#AppName} Setup {#AppVersion}
SetupIconFile=app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; Ask to close a running copy before files are replaced or removed.
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} Setup

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; The complete portable release: the .exe, _internal (Python runtime + app), tools\libimobiledevice,
; licenses and README.txt.
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Both shortcuts point at the INSTALLED exe (its embedded orange icon is used).
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; \
    Comment: "View and remove the apps installed on your iPhone"; AppUserModelID: "{#AppUserModelID}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; \
    Comment: "View and remove the apps installed on your iPhone"; AppUserModelID: "{#AppUserModelID}"; \
    Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

; No [UninstallDelete] section: the uninstaller removes exactly the files this installer copied
; (and the shortcuts), nothing else. The app itself stores no settings or data files.

[Code]
// ---- Visual C++ Redistributable (x64) prerequisite -------------------------------------------------
// The app needs VCRUNTIME140.dll from Microsoft's Visual C++ v14 Redistributable (x64), which this
// installer does not include. Setup reads the 64-bit registry view, requires Installed = 1 and compares
// Major.Minor.Bld.Rbld with the minimum above. A missing or older runtime produces a clear warning and the
// user may still continue; a newer v14 runtime is accepted silently.
const
  VcRuntimeKey = '{#VcRuntimeKey}';

// Returns 'ok', 'older' or 'missing'. Detail receives the installed Major.Minor.Bld (when readable).
function VcRuntimeStatus(var Detail: String): String;
var
  Installed, Major, Minor, Bld, Rbld: Cardinal;
  Have, Need: Int64;
begin
  Result := 'missing';
  Detail := '';
  if not RegQueryDWordValue(HKLM64, VcRuntimeKey, 'Installed', Installed) then Exit;
  if Installed <> 1 then Exit;
  if not RegQueryDWordValue(HKLM64, VcRuntimeKey, 'Major', Major) then Exit;
  if not RegQueryDWordValue(HKLM64, VcRuntimeKey, 'Minor', Minor) then Exit;
  if not RegQueryDWordValue(HKLM64, VcRuntimeKey, 'Bld', Bld) then Exit;
  if not RegQueryDWordValue(HKLM64, VcRuntimeKey, 'Rbld', Rbld) then Rbld := 0;
  Detail := Format('%d.%d.%d', [Major, Minor, Bld]);
  Result := 'older';
  if Major <> {#VcMinMajor} then Exit;             // only the v14 family is compatible
  Have := PackVersionComponents(Major, Minor, Bld, Rbld);
  Need := PackVersionComponents({#VcMinMajor}, {#VcMinMinor}, {#VcMinBld}, {#VcMinRbld});
  if ComparePackedVersion(Have, Need) >= 0 then Result := 'ok';
end;

function InitializeSetup(): Boolean;
var
  Status, Detail, Msg: String;
begin
  Result := True;
  Status := VcRuntimeStatus(Detail);
  Log('Visual C++ x64 runtime check: ' + Status + ' (installed: ' + Detail + '; minimum: {#VcMinMajor}.{#VcMinMinor}.{#VcMinBld})');
  if Status = 'ok' then Exit;

  if Status = 'older' then
    Msg := 'The Microsoft Visual C++ Redistributable (x64) on this PC is too old (version ' + Detail + ').'
  else
    Msg := 'The Microsoft Visual C++ Redistributable (x64) was not found on this PC.';
  Msg := Msg + #13#10#13#10 +
    'iPhone App Manager needs version {#VcMinMajor}.{#VcMinMinor}.{#VcMinBld} or newer. It is not included in this installer.' + #13#10 +
    'The program will not start until you install it.' + #13#10#13#10 +
    'Download the latest "x64" Visual C++ Redistributable from Microsoft:' + #13#10 +
    '{#VcDownloadUrl}' + #13#10 +
    'Installing it may need administrator rights.' + #13#10#13#10 +
    'Do you want to continue installing iPhone App Manager anyway?';
  // Silent installs (/SUPPRESSMSGBOXES) continue, because Yes is the default answer; the check is logged.
  if SuppressibleMsgBox(Msg, mbError, MB_YESNO, IDYES) = IDNO then
    Result := False;
end;
