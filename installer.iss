; Inno Setup script for BURST
; Builds a Windows installer from the PyInstaller output in dist\BURST\

[Setup]
AppName=BURST
AppVersion=1.0
AppPublisher=BUTI Lab
DefaultDirName={autopf}\BURST
DefaultGroupName=BURST
OutputBaseFilename=BURST_Setup
OutputDir=installer_output
SetupIconFile=buti_app\ui\icons\BURST.ico
UninstallDisplayIcon={app}\BURST 1.0.exe
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
PrivilegesRequired=lowest

[Files]
Source: "dist\BURST\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\BURST"; Filename: "{app}\BURST 1.0.exe"; IconFilename: "{app}\BURST 1.0.exe"
Name: "{autodesktop}\BURST"; Filename: "{app}\BURST 1.0.exe"; IconFilename: "{app}\BURST 1.0.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\BURST 1.0.exe"; Description: "Launch BURST"; Flags: nowait postinstall skipifsilent
