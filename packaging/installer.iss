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
