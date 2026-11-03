; Compile on Windows after scripts/build-windows.py.
; Per-user installation: no elevation, service registration or sensor activation.
#define AppVersion "0.5.0"
#ifndef SourceDir
  #define SourceDir "..\..\..\artifacts\windows\Ambi-win-x64"
#endif
[Setup]
AppId={{875DBDC0-BCA7-4BF5-9C89-0A9A0A0B5881}
AppName=Ambi
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Ambi
DefaultGroupName=Ambi
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\..\artifacts\windows
OutputBaseFilename=Ambi-Setup-{#AppVersion}-x64
SetupIconFile=..\..\shared\icons\ambi.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\Ambi.exe
[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\Ambi"; Filename: "{app}\Ambi.exe"
[Run]
Filename: "{app}\Ambi.exe"; Description: "Open Ambi"; Flags: nowait postinstall skipifsilent unchecked
; User data and Codex sign-in are deliberately outside the installer directory.
