; Inno Setup script for BURST
; Builds a Windows installer from the PyInstaller output in dist\BURST\

#define AppName "BURST"
#define AppExeName "BURST.exe"
#define VersionFileHandle FileOpen(AddBackslash(SourcePath) + "buti_app\VERSION")
#if !VersionFileHandle
  #error "Could not open buti_app\VERSION"
#endif
#define AppVersion Trim(FileRead(VersionFileHandle))
#expr FileClose(VersionFileHandle)
#if AppVersion == ""
  #error "buti_app\VERSION is empty"
#endif

[Setup]
AppId={{9C588759-4852-4AB9-8F31-0E39458A431B}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=BUTI Lab
AppPublisherURL=https://github.com/vr-oj/BURST
AppSupportURL=https://github.com/vr-oj/BURST/issues
AppUpdatesURL=https://github.com/vr-oj/BURST/releases
DefaultDirName={autopf}\BURST
DefaultGroupName=BURST
OutputBaseFilename=BURST_Setup_{#AppVersion}
OutputDir=installer_output
SetupIconFile=buti_app\ui\icons\BURST.ico
LicenseFile=LICENSE
UninstallDisplayName={#AppName} {#AppVersion}
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
PrivilegesRequired=lowest
SetupLogging=yes

[Files]
Source: "dist\BURST\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\BURST"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"
Name: "{autodesktop}\BURST"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch BURST"; Flags: nowait postinstall skipifsilent
