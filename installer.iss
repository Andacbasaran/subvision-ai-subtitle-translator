; SubVision AI — Inno Setup 6 Windows Kurulum Betiği (v1.3)
; PyInstaller --onedir çıktısını (dist\SubVisionAI\*) tek bir profesyonel,
; terminalsiz ve Windows Defender dostu Windows kurulum paketine dönüştürür.
;
; Derleme komutu:
;   python build_exe.py --only-pyinstaller
;   iscc /DMyAppVersion=1.3.0 installer.iss

#ifndef MyAppVersion
  #define MyAppVersion "1.3.0"
#endif

#define MyAppName "SubVision AI"
#define MyAppPublisher "SubVision AI Open Source"
#define MyAppURL "https://github.com/Andacbasaran/subvision-ai-subtitle-translator"
#define MyAppExeName "SubVisionAI.exe"

[Setup]
AppId={{7E8E4A24-6D52-49E1-8E65-8C6E3B7B2B13}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=LICENSE
OutputDir=dist
OutputBaseFilename=SubVisionAI-Setup-v{#MyAppVersion}-Windows-x64
SetupIconFile=assets\app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
DisableProgramGroupPage=yes
CloseApplications=yes
VersionInfoVersion={#MyAppVersion}.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Kurulum Sihirbazı
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\SubVisionAI\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\user_settings.json"
Type: filesandordirs; Name: "{app}\__pycache__"
