; KISA-Setup.iss — Installer KISA (Patch 3.9, S138 Cara 3) untuk Inno Setup 6.
; Dijalankan SETELAH PyInstaller membuat dist\KISA.exe:
;     pyinstaller app\KISA.spec
;     iscc app\KISA-Setup.iss
; Hasil: dist-installer\KISA-Setup-3.9.exe
;
; Catatan:
; - KISA.exe (onefile) sudah berisi Python + server + dashboard; installer
;   tidak perlu memasang Python.
; - Komponen pendukung (MSI Afterburner, LibreHardwareMonitor, Nocturne)
;   tetap dipasang lewat Setup_Otomatis.bat yang ikut terinstal — ditawarkan
;   sebagai langkah opsional setelah instalasi.
; - Auto-start Windows diatur aplikasi sendiri (tray menu / --install-autostart).

#define MyAppName "KISA"
#define MyAppVersion "3.9"
#define MyAppPublisher "kirisaki"
#define MyAppExeName "KISA.exe"

[Setup]
AppId={{3F2A1B4C-9D8E-4A7F-B123-4C5D6E7F8091}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin
OutputDir=..\dist-installer
OutputBaseFilename=KISA-Setup-{#MyAppVersion}
SetupIconFile=icons\kisa.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\LICENSE

[Languages]

Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "autostart"; Description: "Jalankan KISA otomatis saat Windows nyala"; GroupDescription: "Auto-start"; Flags: unchecked

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Setup_Otomatis.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Jalankan_di_PC.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\TUTORIAL.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README_APP.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Parameters: "--install-autostart"; Flags: runhidden; Tasks: autostart
Filename: "{app}\Setup_Otomatis.bat"; Description: "Pasang komponen pendukung (MSI Afterburner, LibreHardwareMonitor, Nocturne)"; Flags: postinstall skipifsilent
Filename: "{app}\{#MyAppExeName}"; Description: "Jalankan KISA"; Flags: postinstall nowait skipifsilent unchecked

[UninstallDelete]
Type: files; Name: "{app}\QR_Dashboard.png"
Type: files; Name: "{app}\*.log"
