; KISA-Setup.iss — Installer KISA (Patch 4.1, S153 Cara 3) untuk Inno Setup 6.
; Dijalankan SETELAH PyInstaller membuat dist\KISA.exe:
;     pyinstaller app\KISA.spec
;     iscc app\KISA-Setup.iss
; Hasil: dist-installer\KISA-Setup-4.1.exe
;
; Catatan:
; - KISA.exe (onefile) sudah berisi Python + server + dashboard; installer
;   tidak perlu memasang Python.
; - Komponen pendukung (Python + paket, MSI Afterburner, LibreHardwareMonitor,
;   Nocturne, FFmpeg) ditawarkan di halaman wizard "Aplikasi Pendukung"
;   (Patch 4.1, S153 Cara 3 — dikelompokkan per fitur, PC saja) dan dipasang
;   lewat Setup_Otomatis.bat yang ikut terinstal, sesuai kelompok yang dicentang.
; - Auto-start Windows diatur aplikasi sendiri (tray menu / --install-autostart).

#define MyAppName "KISA"
#define MyAppVersion "4.1"
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
Filename: "{app}\Setup_Otomatis.bat"; Parameters: """{code:SupportGroupsParam}"""; Flags: postinstall skipifsilent; Check: SupportAnySelected
Filename: "{app}\{#MyAppExeName}"; Description: "Jalankan KISA"; Flags: postinstall nowait skipifsilent unchecked

[UninstallDelete]
Type: files; Name: "{app}\QR_Dashboard.png"
Type: files; Name: "{app}\*.log"

[Code]
{ Patch 4.1 (S153 Cara 3): halaman wizard "Aplikasi Pendukung".
  Menampilkan 5 kelompok aplikasi pendukung per fitur, lengkap dengan
  status "Sudah ada" / "Belum ada" yang dideteksi saat halaman dibuka.
  Kelompok yang sudah ada: checkbox dimatikan (tidak bisa dicentang).
  Kelompok yang belum ada: tercentang otomatis.
  Pilihan diteruskan ke Setup_Otomatis.bat sebagai argumen daftar koma
  (python,afterburner,lhm,nocturne,ffmpeg) — .bat tetap mesin installnya
  (winget / download resmi + cek ukuran file), halaman ini hanya UI-nya.
  Tanpa argumen, .bat tetap memasang semua (dijalankan langsung). }

var
  SupportPage: TWizardPage;
  SupportCheck: array[0..4] of TNewCheckBox;
  SupportStatus: array[0..4] of TNewStaticText;
  SupportGroupPython: Boolean;
  SupportGroupAfterburner: Boolean;
  SupportGroupLHM: Boolean;
  SupportGroupNocturne: Boolean;
  SupportGroupFFmpeg: Boolean;

function SupportPythonInstalled: Boolean;
var
  ResultCode: Integer;
begin
  Result := False;
  if Exec('python', '--version', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    if ResultCode = 0 then Result := True;
  if not Result then
    if FileExists(ExpandConstant('{localappdata}\Programs\Python\Python315\python.exe')) then Result := True;
  if not Result then
    if RegKeyExists(HKLM, 'SOFTWARE\Python\PythonCore\3.15') then Result := True;
  if not Result then
    if RegKeyExists(HKCU, 'SOFTWARE\Python\PythonCore\3.15') then Result := True;
  if not Result then
    if RegKeyExists(HKLM, 'SOFTWARE\Python\PythonCore\3.12') then Result := True;
  if not Result then
    if RegKeyExists(HKCU, 'SOFTWARE\Python\PythonCore\3.12') then Result := True;
end;

function SupportAfterburnerInstalled: Boolean;
begin
  Result := FileExists('C:\Program Files (x86)\MSI Afterburner\MSIAfterburner.exe')
    or FileExists('C:\Program Files\MSI Afterburner\MSIAfterburner.exe');
end;

function SupportLHMInstalled: Boolean;
begin
  Result := FileExists(ExpandConstant('{userappdata}\PCMonitorHUD\tools\LibreHardwareMonitor\LibreHardwareMonitor.exe'))
    or FileExists('C:\Program Files\LibreHardwareMonitor\LibreHardwareMonitor.exe')
    or FileExists('C:\Program Files (x86)\LibreHardwareMonitor\LibreHardwareMonitor.exe')
    or FileExists('C:\LibreHardwareMonitor\LibreHardwareMonitor.exe');
end;

function SupportNocturneInstalled: Boolean;
begin
  Result := FileExists(ExpandConstant('{localappdata}\Nocturne Music\nocturne-app.exe'))
    or FileExists(ExpandConstant('{localappdata}\Nocturne.Music\nocturne-app.exe'))
    or FileExists('C:\Program Files\Nocturne Music\nocturne-app.exe')
    or FileExists('C:\Program Files (x86)\Nocturne Music\nocturne-app.exe');
end;

function SupportFFmpegInstalled: Boolean;
var
  ResultCode: Integer;
begin
  Result := False;
  if Exec('ffmpeg', '-version', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    if ResultCode = 0 then Result := True;
end;

function SupportInstalled(Index: Integer): Boolean;
begin
  case Index of
    0: Result := SupportPythonInstalled();
    1: Result := SupportAfterburnerInstalled();
    2: Result := SupportLHMInstalled();
    3: Result := SupportNocturneInstalled();
    4: Result := SupportFFmpegInstalled();
  else
    Result := False;
  end;
end;

procedure SupportPageActivate(Sender: TWizardPage);
var
  I: Integer;
begin
  for I := 0 to 4 do
  begin
    if SupportInstalled(I) then
    begin
      SupportStatus[I].Caption := 'Sudah ada';
      SupportStatus[I].Font.Color := clGreen;
      SupportCheck[I].Checked := False;
      SupportCheck[I].Enabled := False;
    end
    else
    begin
      SupportStatus[I].Caption := 'Belum ada';
      SupportStatus[I].Font.Color := $000080FF;
      SupportCheck[I].Checked := True;
      SupportCheck[I].Enabled := True;
    end;
  end;
end;

function SupportPageNextButtonClick(Sender: TWizardPage): Boolean;
begin
  SupportGroupPython := SupportCheck[0].Checked;
  SupportGroupAfterburner := SupportCheck[1].Checked;
  SupportGroupLHM := SupportCheck[2].Checked;
  SupportGroupNocturne := SupportCheck[3].Checked;
  SupportGroupFFmpeg := SupportCheck[4].Checked;
  Result := True;
end;

function SupportAnySelected: Boolean;
begin
  Result := SupportGroupPython or SupportGroupAfterburner or SupportGroupLHM
    or SupportGroupNocturne or SupportGroupFFmpeg;
end;

function SupportGroupsParam(Param: String): String;
begin
  Result := '';
  if SupportGroupPython then Result := Result + 'python,';
  if SupportGroupAfterburner then Result := Result + 'afterburner,';
  if SupportGroupLHM then Result := Result + 'lhm,';
  if SupportGroupNocturne then Result := Result + 'nocturne,';
  if SupportGroupFFmpeg then Result := Result + 'ffmpeg,';
  if Length(Result) > 0 then
    SetLength(Result, Length(Result) - 1);
end;

procedure SupportAddGroup(Index: Integer; Top: Integer; Title, Desc: String);
var
  Chk: TNewCheckBox;
  Lbl: TNewStaticText;
  St: TNewStaticText;
  W: Integer;
begin
  W := SupportPage.SurfaceWidth;
  Chk := TNewCheckBox.Create(SupportPage);
  Chk.Parent := SupportPage.Surface;
  Chk.Left := ScaleX(8);
  Chk.Top := Top;
  Chk.Width := W - ScaleX(8) - ScaleX(78);
  Chk.Height := ScaleY(17);
  Chk.Caption := Title;
  Chk.Font.Style := [fsBold];
  SupportCheck[Index] := Chk;
  St := TNewStaticText.Create(SupportPage);
  St.Parent := SupportPage.Surface;
  St.Left := W - ScaleX(78);
  St.Top := Top;
  St.Width := ScaleX(70);
  St.Height := ScaleY(17);
  St.Alignment := taRightJustify;
  St.Caption := 'Memeriksa...';
  SupportStatus[Index] := St;
  Lbl := TNewStaticText.Create(SupportPage);
  Lbl.Parent := SupportPage.Surface;
  Lbl.Left := ScaleX(26);
  Lbl.Top := Top + ScaleY(18);
  Lbl.Width := W - ScaleX(26) - ScaleX(8);
  Lbl.Height := ScaleY(26);
  Lbl.WordWrap := True;
  Lbl.AutoSize := False;
  Lbl.Font.Color := clGray;
  Lbl.Caption := Desc;
end;

procedure InitializeWizard();
var
  Intro: TNewStaticText;
  Y: Integer;
begin
  SupportPage := CreateCustomPage(wpSelectTasks, 'Aplikasi Pendukung',
    'Pilih aplikasi pendukung yang mau di-install agar semua fitur KISA jalan.');
  Intro := TNewStaticText.Create(SupportPage);
  Intro.Parent := SupportPage.Surface;
  Intro.Left := ScaleX(8);
  Intro.Top := ScaleY(4);
  Intro.Width := SupportPage.SurfaceWidth - ScaleX(16);
  Intro.Height := ScaleY(28);
  Intro.WordWrap := True;
  Intro.AutoSize := False;
  Intro.Caption := 'Centang kelompok aplikasi yang mau di-install. Yang sudah ada dilewati otomatis. Install perlu internet.';
  Y := ScaleY(36);
  SupportAddGroup(0, Y, 'Server, QR & Deteksi Musik', 'Python 3.15 (+ psutil, winsdk, segno) — Server KISA jalan, QR dashboard, deteksi musik');
  Y := Y + ScaleY(46);
  SupportAddGroup(1, Y, 'FPS', 'MSI Afterburner + RTSS — Kartu FPS');
  Y := Y + ScaleY(46);
  SupportAddGroup(2, Y, 'Suhu, Kipas & Daya', 'LibreHardwareMonitor — Suhu CPU/GPU, kipas, daya');
  Y := Y + ScaleY(46);
  SupportAddGroup(3, Y, 'Musik', 'Nocturne Music — Kartu Now Playing');
  Y := Y + ScaleY(46);
  SupportAddGroup(4, Y, 'Kompresi Latar', 'FFmpeg — Kompresi latar video (GPU AMF)');
  SupportPage.OnActivate := @SupportPageActivate;
  SupportPage.OnNextButtonClick := @SupportPageNextButtonClick;
end;
