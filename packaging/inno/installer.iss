; SubVision AI — Inno Setup 6 Windows Kurulum ve Opsiyonel Kaldırma Betiği (v1.3)
; PyInstaller --onedir çıktısını (dist\SubVisionAI\*) tek bir profesyonel,
; dijital imzalı ve Windows Defender dostu Windows kurulum paketine dönüştürür.
; Kaldırma (Uninstall) sırasında indirilen 227 MB yapay zeka modelini ve kullanıcı
; ayarlarını opsiyonel olarak silme veya koruma seçeneği sunar.
;
; Derleme komutu:
;   python scripts/build_exe.py --only-pyinstaller
;   iscc /DMyAppVersion=1.5.0 packaging\inno\installer.iss
;   python scripts/build_exe.py --sign dist\SubVisionAI-Setup-v1.5.0-Windows-x64.exe

#ifndef MyAppVersion
  #define MyAppVersion "1.5.0"
#endif

#define MyAppName "SubVision AI"
#define MyAppPublisher "SubVision AI Open Source"
#define MyAppURL "https://github.com/Andacbasaran/subvision-ai-subtitle-translator"
#define MyAppExeName "SubVisionAI.exe"
#define MyAppUninstallerHelper "SubVisionAI-Uninstaller.exe"

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
LicenseFile=..\..\LICENSE
OutputDir=..\..\dist
OutputBaseFilename=SubVisionAI-Setup-v{#MyAppVersion}-Windows-x64
SetupIconFile=..\..\assets\app_icon.ico
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
CloseApplications=force
RestartApplications=yes
VersionInfoVersion={#MyAppVersion}.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Kurulum ve Kaldırma Yardımcısı
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\..\dist\SubVisionAI\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autoprograms}\{#MyAppName} Bileşen & Kaldırma Yardımcısı"; Filename: "{app}\{#MyAppUninstallerHelper}"; Parameters: "--uninstall"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#MyAppExeName}"; Flags: nowait skipifnotsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\__pycache__"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DeleteModelsAndRuntime: Boolean;
  DeleteUserSettings: Boolean;
  LocalDataDir: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    LocalDataDir := ExpandConstant('{localappdata}\SubVisionAI');
    DeleteModelsAndRuntime := False;
    DeleteUserSettings := False;

    if not UninstallSilent then
    begin
      if MsgBox(
        'SubVision AI ile birlikte indirilen Yapay Zeka Çeviri Modeli (~227 MB - models/opus-en-tr-ct2) ve ek çalışma ortamı dosyaları da bilgisayardan silinsin mi?' + #13#10 + #13#10 +
        '(İpucu: İleride tekrar kurduğunuzda ~227 MB dil modelini yeniden indirmemek için "Hayır" seçebilirsiniz.)',
        mbConfirmation,
        MB_YESNO
      ) = IDYES then
      begin
        DeleteModelsAndRuntime := True;
      end;

      if MsgBox(
        'Kişisel kullanıcı ayarlarınız, altyazı alanı (ROI) kalibrasyonunuz ve önbellek verileriniz (user_settings.json) de silinsin mi?',
        mbConfirmation,
        MB_YESNO
      ) = IDYES then
      begin
        DeleteUserSettings := True;
      end;
    end;

    if DeleteModelsAndRuntime then
    begin
      DelTree(ExpandConstant('{app}\models'), True, True, True);
      DelTree(ExpandConstant('{app}\runtime'), True, True, True);
      DelTree(LocalDataDir + '\models', True, True, True);
    end;

    if DeleteUserSettings then
    begin
      DeleteFile(ExpandConstant('{app}\user_settings.json'));
      DeleteFile(ExpandConstant('{app}\benchmark_results.json'));
      DeleteFile(LocalDataDir + '\user_settings.json');
    end;

    if DeleteModelsAndRuntime and DeleteUserSettings then
    begin
      RemoveDir(LocalDataDir);
    end;
  end;
end;
