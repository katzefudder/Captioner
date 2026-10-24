; Inno Setup script for the Windows installer. Run via
; `python scripts/package_windows.py installer` (sets AppVersion and SourceDir via /D).
;
; Installs dist\Captioner\ to Program Files\Captioner (or, without admin rights, to
; %LOCALAPPDATA%\Programs), a Start menu entry, the Explorer context menu "Open with
; Captioner" for folders and drives (card). Several selected folders end up as tabs
; in one window (captioner/ui/instance.py).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\Captioner"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

[Setup]
; fixed: this is how Windows recognizes updates of the same app
AppId={{F70EF242-EABB-4EBF-B59B-4893F856A2FB}
AppName=Captioner
AppVersion={#AppVersion}
AppVerName=Captioner {#AppVersion}
AppPublisher=Florian Dehn
AppPublisherURL=https://www.katzefudder.de/captioner
DefaultDirName={autopf}\Captioner
DefaultGroupName=Captioner
DisableProgramGroupPage=yes
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=Captioner-{#AppVersion}-x64-setup
SetupIconFile=..\captioner\resources\captioner.ico
UninstallDisplayIcon={app}\Captioner.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; if the app is still running, it is closed for the update
CloseApplications=yes
VersionInfoVersion={#AppVersion}

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
de.OpenWith=Mit Captioner öffnen
en.OpenWith=Open with Captioner
de.ContextMenu=Explorer-Kontextmenü „Mit Captioner öffnen“ für Ordner und Laufwerke
en.ContextMenu=Explorer context menu “Open with Captioner” for folders and drives

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "contextmenu"; Description: "{cm:ContextMenu}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; licenses visible next to the exe (in the bundle they are also under _internal)
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "..\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion

[InstallDelete]
; don't leave remains of an earlier version behind (e.g. removed Qt plugins)
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\Captioner"; Filename: "{app}\Captioner.exe"
Name: "{autoprograms}\Captioner Anleitung"; Filename: "{app}\_internal\docs\Captioner-Anleitung.pdf"
Name: "{autoprograms}\Captioner Manual"; Filename: "{app}\_internal\docs\Captioner-Manual.pdf"
Name: "{autodesktop}\Captioner"; Filename: "{app}\Captioner.exe"; Tasks: desktopicon

[Registry]
; HKA = HKLM when installing for all users, otherwise HKCU
Root: HKA; Subkey: "Software\Classes\Directory\shell\Captioner"; ValueType: string; ValueName: ""; ValueData: "{cm:OpenWith}"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Directory\shell\Captioner"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\Captioner.exe"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Directory\shell\Captioner\command"; ValueType: string; ValueName: ""; ValueData: """{app}\Captioner.exe"" ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Directory\Background\shell\Captioner"; ValueType: string; ValueName: ""; ValueData: "{cm:OpenWith}"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Directory\Background\shell\Captioner"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\Captioner.exe"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Directory\Background\shell\Captioner\command"; ValueType: string; ValueName: ""; ValueData: """{app}\Captioner.exe"" ""%V"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Drive\shell\Captioner"; ValueType: string; ValueName: ""; ValueData: "{cm:OpenWith}"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Drive\shell\Captioner"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\Captioner.exe"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Drive\shell\Captioner\command"; ValueType: string; ValueName: ""; ValueData: """{app}\Captioner.exe"" ""%1"""; Tasks: contextmenu

[Run]
Filename: "{app}\Captioner.exe"; Description: "{cm:LaunchProgram,Captioner}"; Flags: nowait postinstall skipifsilent
