; KISA-Setup.iss — Installer KISA (Patch 5.1) untuk Inno Setup 6.
; Dijalankan SETELAH PyInstaller membuat dist\KISA.exe:
;     pyinstaller app\KISA.spec
;     iscc app\KISA-Setup.iss
; Hasil: dist-installer\KISA-Setup-5.1.exe
;
; Catatan:
; - KISA.exe (onefile) sudah berisi Python + server + dashboard; installer
;   tidak perlu memasang Python.
; - Komponen pendukung (Python + paket, MSI Afterburner, LibreHardwareMonitor,
;   Nocturne, FFmpeg) ditawarkan di halaman wizard "Aplikasi Pendukung"
;   (ditambah di Patch 4.1, S153 Cara 3 — dikelompokkan per fitur, PC saja) dan dipasang
;   lewat Setup_Otomatis.bat yang ikut terinstal, sesuai kelompok yang dicentang.
; - Auto-start Windows diatur aplikasi sendiri (tray menu / --install-autostart).

#define MyAppName "KISA"
#define MyAppVersion "5.1"
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
; Patch 5.1 perc213 (bug hotspot): izinkan port 8000 di Windows Firewall
; untuk SEMUA profil (termasuk Public/hotspot) — installer jalan sebagai admin.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""KISA"" dir=in action=allow protocol=TCP localport=8000 profile=any"; Flags: runhidden
Filename: "{app}\Setup_Otomatis.bat"; Parameters: """{code:SupportGroupsParam}"""; Flags: postinstall skipifsilent; Check: SupportAnySelected
Filename: "{app}\{#MyAppExeName}"; Description: "Jalankan KISA"; Flags: postinstall nowait skipifsilent unchecked

[UninstallDelete]
Type: files; Name: "{app}\QR_Dashboard.png"
Type: files; Name: "{app}\*.log"

[Code]
{ Halaman wizard "Aplikasi Pendukung" (S153 Cara 3, ditambah di Patch 4.1).
  Menampilkan 5 kelompok aplikasi pendukung per fitur, lengkap dengan
  status "Sudah ada" / "Belum ada" yang dideteksi saat halaman dibuka.
  Kelompok yang sudah ada: checkbox dimatikan (tidak bisa dicentang).
  Kelompok yang belum ada: tercentang otomatis.
  Pilihan diteruskan ke Setup_Otomatis.bat sebagai argumen daftar koma
  (python,afterburner,lhm,nocturne,ffmpeg) — .bat tetap mesin installnya
  (winget / download resmi + cek ukuran file), halaman ini hanya UI-nya.
  Tanpa argumen, .bat tetap memasang semua (dijalankan langsung).
  Tampilan kartu mengikuti S193 "Rapi Modern" (Patch 5.1): kartu putih
  ber-border abu-abu tipis, ikon huruf di kotak biru, pill hijau/oranye. }

var
  SupportPage: TWizardPage;
  SupportCheck: array[0..4] of TNewCheckBox;
  SupportStatus: array[0..4] of TNewStaticText;
  SupportPill: array[0..4] of TPanel;
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
var
  TmpFile: String;
  Lines: TArrayOfString;
  I: Integer;
  ResultCode: Integer;
begin
  { 1) samakan dengan .bat: cek proses sedang jalan (menangkap LHM di lokasi mana pun) }
  TmpFile := ExpandConstant('{tmp}\kisa_lhm_tasklist.txt');
  if Exec('cmd.exe', '/c tasklist /FI "IMAGENAME eq LibreHardwareMonitor.exe" /NH > "' + TmpFile + '"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    if LoadStringsFromFile(TmpFile, Lines) then
      for I := 0 to GetArrayLength(Lines) - 1 do
        if Pos('LibreHardwareMonitor.exe', Lines[I]) > 0 then
        begin
          Result := True;
          Exit;
        end;
  end;
  { 2) fallback: 4 path file seperti sekarang }
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
      { S193: pill hijau — latar #DCFCE7, teks #15803D }
      SupportStatus[I].Caption := 'Sudah ada';
      SupportStatus[I].Font.Color := $003D8015;
      SupportPill[I].Color := $00E7FCDC;
      SupportCheck[I].Checked := False;
      SupportCheck[I].Enabled := False;
    end
    else
    begin
      { S193: pill oranye — latar #FFEDD5, teks #C2410C }
      SupportStatus[I].Caption := 'Belum ada';
      SupportStatus[I].Font.Color := $000C41C2;
      SupportPill[I].Color := $00D5EDFF;
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

{ S193 "Rapi Modern" (Patch 5.1): tiap kelompok tampil sebagai kartu putih
  dengan border abu-abu tipis (#E5E7EB), ikon huruf di kotak biru (#2563EB),
  dan pill status hijau "Sudah ada" / oranye "Belum ada".
  Susunan dalam kartu (kiri ke kanan): checkbox, ikon, judul + deskripsi, pill.
  Kartu luar berperan sebagai border 1px; kartu dalam berwarna putih. }
procedure SupportAddGroup(Index: Integer; Top: Integer; IconText, Title, Desc: String);
var
  Card: TPanel;
  Inner: TPanel;
  Icon: TPanel;
  Chk: TNewCheckBox;
  TitleLbl: TNewStaticText;
  Lbl: TNewStaticText;
  Pill: TPanel;
  St: TNewStaticText;
  W: Integer;
begin
  W := SupportPage.SurfaceWidth;
  { Kartu luar = warna border, kartu dalam = putih (inset 1px) }
  Card := TPanel.Create(SupportPage);
  Card.Parent := SupportPage.Surface;
  Card.Left := ScaleX(8);
  Card.Top := Top;
  Card.Width := W - ScaleX(16);
  Card.Height := ScaleY(36);
  Card.Color := $00EBE7E5;
  Card.BevelOuter := bvNone;
  Inner := TPanel.Create(SupportPage);
  Inner.Parent := Card;
  Inner.Left := ScaleX(1);
  Inner.Top := ScaleY(1);
  Inner.Width := Card.Width - ScaleX(2);
  Inner.Height := Card.Height - ScaleY(2);
  Inner.Color := clWhite;
  Inner.BevelOuter := bvNone;
  { Checkbox (kiri, tanpa caption — judul jadi label sendiri) }
  Chk := TNewCheckBox.Create(SupportPage);
  Chk.Parent := Inner;
  Chk.Left := ScaleX(7);
  Chk.Top := ScaleY(9);
  Chk.Width := ScaleX(16);
  Chk.Height := ScaleY(16);
  Chk.Caption := '';
  SupportCheck[Index] := Chk;
  { Ikon: kotak biru aksen S193 berisi huruf/kode kelompok }
  Icon := TPanel.Create(SupportPage);
  Icon.Parent := Inner;
  Icon.Left := ScaleX(28);
  Icon.Top := ScaleY(4);
  Icon.Width := ScaleX(26);
  Icon.Height := ScaleY(26);
  Icon.Color := $00EB6325;
  Icon.Font.Color := clWhite;
  Icon.Font.Style := [fsBold];
  Icon.Font.Size := 9;
  Icon.Caption := IconText;
  Icon.Alignment := taCenter;
  Icon.BevelOuter := bvNone;
  { Judul (tebal) + deskripsi (abu-abu, satu baris ala S193) }
  TitleLbl := TNewStaticText.Create(SupportPage);
  TitleLbl.Parent := Inner;
  TitleLbl.Left := ScaleX(62);
  TitleLbl.Top := ScaleY(3);
  TitleLbl.Width := Inner.Width - ScaleX(62) - ScaleX(96);
  TitleLbl.Height := ScaleY(14);
  TitleLbl.Font.Style := [fsBold];
  TitleLbl.Caption := Title;
  Lbl := TNewStaticText.Create(SupportPage);
  Lbl.Parent := Inner;
  Lbl.Left := ScaleX(62);
  Lbl.Top := ScaleY(18);
  Lbl.Width := Inner.Width - ScaleX(62) - ScaleX(96);
  Lbl.Height := ScaleY(12);
  Lbl.Font.Color := clGray;
  Lbl.Caption := Desc;
  { Pill status: panel latar + teks rata tengah di atasnya }
  Pill := TPanel.Create(SupportPage);
  Pill.Parent := Inner;
  Pill.Left := Inner.Width - ScaleX(84);
  Pill.Top := ScaleY(8);
  Pill.Width := ScaleX(76);
  Pill.Height := ScaleY(18);
  Pill.Color := $00E8ECF1;
  Pill.BevelOuter := bvNone;
  SupportPill[Index] := Pill;
  St := TNewStaticText.Create(SupportPage);
  St.Parent := Pill;
  St.Left := 0;
  St.Top := ScaleY(2);
  St.Width := Pill.Width;
  St.Height := ScaleY(14);
  St.Alignment := taCenter;
  St.Font.Color := clGray;
  St.Caption := 'Memeriksa...';
  SupportStatus[Index] := St;
end;

procedure InitializeWizard();
var
  Logo: TPanel;
  AppTitle: TNewStaticText;
  AppSub: TNewStaticText;
  Badge: TPanel;
  Intro: TNewStaticText;
  Y: Integer;
begin
  SupportPage := CreateCustomPage(wpSelectTasks, 'Aplikasi Pendukung',
    'Pilih aplikasi pendukung yang mau di-install agar semua fitur KISA jalan.');
  { Header S193: logo "K" biru + nama KISA + badge Patch 5.1 }
  Logo := TPanel.Create(SupportPage);
  Logo.Parent := SupportPage.Surface;
  Logo.Left := ScaleX(8);
  Logo.Top := ScaleY(0);
  Logo.Width := ScaleX(28);
  Logo.Height := ScaleY(28);
  Logo.Color := $00EB6325;
  Logo.Font.Color := clWhite;
  Logo.Font.Style := [fsBold];
  Logo.Font.Size := 13;
  Logo.Caption := 'K';
  Logo.Alignment := taCenter;
  Logo.BevelOuter := bvNone;
  AppTitle := TNewStaticText.Create(SupportPage);
  AppTitle.Parent := SupportPage.Surface;
  AppTitle.Left := ScaleX(44);
  AppTitle.Top := ScaleY(1);
  AppTitle.Width := ScaleX(120);
  AppTitle.Height := ScaleY(14);
  AppTitle.Font.Style := [fsBold];
  AppTitle.Font.Size := 11;
  AppTitle.Caption := 'KISA';
  AppSub := TNewStaticText.Create(SupportPage);
  AppSub.Parent := SupportPage.Surface;
  AppSub.Left := ScaleX(44);
  AppSub.Top := ScaleY(15);
  AppSub.Width := ScaleX(200);
  AppSub.Height := ScaleY(12);
  AppSub.Font.Color := clGray;
  AppSub.Caption := 'Installer · KISA Setup';
  Badge := TPanel.Create(SupportPage);
  Badge.Parent := SupportPage.Surface;
  Badge.Left := SupportPage.SurfaceWidth - ScaleX(8) - ScaleX(68);
  Badge.Top := ScaleY(5);
  Badge.Width := ScaleX(68);
  Badge.Height := ScaleY(18);
  Badge.Color := $00EB6325;
  Badge.Font.Color := clWhite;
  Badge.Font.Style := [fsBold];
  Badge.Font.Size := 8;
  Badge.Caption := 'Patch 5.1';
  Badge.Alignment := taCenter;
  Badge.BevelOuter := bvNone;
  Intro := TNewStaticText.Create(SupportPage);
  Intro.Parent := SupportPage.Surface;
  Intro.Left := ScaleX(8);
  Intro.Top := ScaleY(34);
  Intro.Width := SupportPage.SurfaceWidth - ScaleX(16);
  Intro.Height := ScaleY(26);
  Intro.WordWrap := True;
  Intro.AutoSize := False;
  Intro.Caption := 'Centang kelompok aplikasi yang mau di-install. Yang sudah ada dilewati otomatis. Install perlu internet.';
  Y := ScaleY(66);
  SupportAddGroup(0, Y, 'Py', 'Server, QR & Deteksi Musik', 'Python 3.15 (+ psutil, winsdk, segno)');
  Y := Y + ScaleY(40);
  SupportAddGroup(1, Y, 'FPS', 'FPS', 'MSI Afterburner + RTSS');
  Y := Y + ScaleY(40);
  SupportAddGroup(2, Y, '°C', 'Suhu, Kipas & Daya', 'LibreHardwareMonitor');
  Y := Y + ScaleY(40);
  SupportAddGroup(3, Y, '♪', 'Musik', 'Nocturne Music');
  Y := Y + ScaleY(40);
  SupportAddGroup(4, Y, '▶', 'Kompresi Latar', 'FFmpeg');
  SupportPage.OnActivate := @SupportPageActivate;
  SupportPage.OnNextButtonClick := @SupportPageNextButtonClick;
end;
