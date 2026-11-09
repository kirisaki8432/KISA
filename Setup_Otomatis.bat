@echo off
chcp 65001 >nul
title Setup Otomatis - KISA
echo ================================================
echo  Setup Otomatis - KISA
echo  Mengecek dan melengkapi software yang
echo  dibutuhkan. Yang sudah ada akan dilewati.
echo  Perlu internet untuk download/install.
echo ================================================
echo.
set "SETUP_OK=1"
set "WINGET_OK=0"
where winget >nul 2>&1
if not errorlevel 1 set "WINGET_OK=1"

REM ---------- 1. Python ----------
echo [1/7] Mengecek Python...
python --version >nul 2>&1
if not errorlevel 1 (
  echo   Python sudah ada.
  goto :step_psutil
)
echo   Python belum ditemukan, mencoba install via winget...
if "%WINGET_OK%"=="0" goto :python_manual
winget install -e --id Python.Python.3.15 --silent --accept-source-agreements --accept-package-agreements
if errorlevel 1 goto :python_manual
REM winget tidak selalu menyegarkan PATH di sesi ini, tambahkan manual:
set "PATH=%LOCALAPPDATA%\Programs\Python\Python315;%LOCALAPPDATA%\Programs\Python\Python315\Scripts;%PATH%"
python --version >nul 2>&1
if not errorlevel 1 (
  echo   Python berhasil diinstall.
  goto :step_psutil
)
echo   Python sudah diinstall tapi belum dikenali di jendela ini.
echo   Tutup jendela ini lalu jalankan lagi file .bat ini.
goto :fatal
:python_manual
echo   GAGAL install Python otomatis.
echo   Install manual dari: https://www.python.org/downloads/
echo   (langsung: https://www.python.org/ftp/python/3.15.2/python-3.15.2-amd64.exe)
echo   Centang "Add python.exe to PATH" saat install, lalu jalankan lagi file ini.
goto :fatal

:step_psutil
REM ---------- 2. psutil ----------
echo [2/7] Mengecek psutil...
python -c "import psutil" >nul 2>&1
if not errorlevel 1 (
  echo   psutil sudah ada.
  goto :step_segno
)
echo   Menginstal psutil...
python -m pip install psutil
python -c "import psutil" >nul 2>&1
if errorlevel 1 (
  echo   PERINGATAN: psutil gagal diinstall. Server tidak bisa jalan tanpa psutil.
  echo   Coba manual: python -m pip install psutil
  set "SETUP_OK=0"
) else (
  echo   psutil berhasil diinstall.
)

:step_segno
REM ---------- 3. segno (QR code dashboard) ----------
echo [3/7] Mengecek segno (untuk QR code dashboard)...
python -c "import segno" >nul 2>&1
if not errorlevel 1 (
  echo   segno sudah ada.
  goto :step_winrt
)
echo   Menginstal segno...
python -m pip install segno
python -c "import segno" >nul 2>&1
if errorlevel 1 (
  echo   PERINGATAN: segno gagal diinstall. QR dashboard tidak akan dibuat,
  echo   tapi dashboard tetap jalan (buka manual lewat IP di jendela server).
) else (
  echo   segno berhasil diinstall.
)

:step_winrt
REM ---------- 4. winrt (deteksi lagu Nocturne) ----------
echo [4/7] Mengecek winrt (untuk lagu Nocturne)...
python -c "import winrt.windows.media.control" >nul 2>&1
if not errorlevel 1 (
  echo   winrt sudah ada.
  goto :step_ab
)
echo   Menginstal winrt-Windows.Media.Control...
python -m pip install --only-binary :all: winrt-Windows.Media.Control
python -c "import winrt.windows.media.control" >nul 2>&1
if not errorlevel 1 (
  echo   winrt berhasil diinstall.
  goto :step_ab
)
echo   Coba paket winrt lama sebagai cadangan...
python -m pip install --only-binary :all: winrt
python -c "import winrt.windows.media.control" >nul 2>&1
if errorlevel 1 (
  echo   PERINGATAN: winrt gagal diinstall. Lagu Nocturne mungkin tidak muncul
  echo   di kartu Musik. Dashboard tetap jalan. Coba jalankan Install_winrt.bat.
) else (
  echo   winrt berhasil diinstall.
)

:step_ab
REM ---------- 5. MSI Afterburner + RTSS (FPS utama) ----------
echo [5/7] Mengecek MSI Afterburner...
tasklist /FI "IMAGENAME eq MSIAfterburner.exe" 2>nul | find /I "MSIAfterburner.exe" >nul
if not errorlevel 1 (
  echo   Afterburner sudah jalan.
  goto :step_lhm
)
if exist "C:\Program Files (x86)\MSI Afterburner\MSIAfterburner.exe" (
  echo   Afterburner sudah ter-install.
  goto :step_lhm
)
if exist "C:\Program Files\MSI Afterburner\MSIAfterburner.exe" (
  echo   Afterburner sudah ter-install.
  goto :step_lhm
)
echo   Afterburner belum ada, mencoba install via winget...
if "%WINGET_OK%"=="0" goto :ab_manual
winget install -e --id Guru3D.Afterburner --silent --accept-source-agreements --accept-package-agreements
if not errorlevel 1 goto :ab_done
echo   Paket Guru3D.Afterburner gagal, coba paket MSI.Afterburner...
winget install -e --id MSI.Afterburner --silent --accept-source-agreements --accept-package-agreements
if not errorlevel 1 goto :ab_done
goto :ab_manual
:ab_done
if exist "C:\Program Files (x86)\MSI Afterburner\MSIAfterburner.exe" (
  echo   Afterburner berhasil diinstall.
  goto :step_lhm
)
if exist "C:\Program Files\MSI Afterburner\MSIAfterburner.exe" (
  echo   Afterburner berhasil diinstall.
  goto :step_lhm
)
echo   winget selesai tapi file Afterburner tidak ditemukan. Coba jalankan lagi,
echo   atau install manual (lihat di bawah).
:ab_manual
echo   GAGAL install Afterburner otomatis (butuh admin + internet + winget).
echo   Install manual dari halaman resmi MSI:
echo   https://www.msi.com/Landing/afterburner/graphics-cards
echo   (atau cari "MSI Afterburner" di Guru3D). Setelah itu jalankan lagi file ini.
echo   Kartu FPS tidak tampil sampai Afterburner terpasang dan jalan.

:step_lhm
REM ---------- 6. LibreHardwareMonitor (suhu/kipas/daya) ----------
echo [6/7] Mengecek LibreHardwareMonitor...
set "LHM_DIR=%APPDATA%\PCMonitorHUD\tools\LibreHardwareMonitor"
tasklist /FI "IMAGENAME eq LibreHardwareMonitor.exe" 2>nul | find /I "LibreHardwareMonitor.exe" >nul
if not errorlevel 1 (
  echo   LibreHardwareMonitor sudah jalan.
  goto :done
)
if exist "%LHM_DIR%\LibreHardwareMonitor.exe" (
  echo   LibreHardwareMonitor sudah ada di %LHM_DIR%.
  goto :done
)
if exist "C:\Program Files\LibreHardwareMonitor\LibreHardwareMonitor.exe" (
  echo   LibreHardwareMonitor sudah ter-install.
  goto :done
)
if exist "C:\Program Files (x86)\LibreHardwareMonitor\LibreHardwareMonitor.exe" (
  echo   LibreHardwareMonitor sudah ter-install.
  goto :done
)
if exist "C:\LibreHardwareMonitor\LibreHardwareMonitor.exe" (
  echo   LibreHardwareMonitor sudah ter-install.
  goto :done
)
echo   LibreHardwareMonitor belum ada, mendownload v0.9.6 (6,3 MB)...
if not exist "%LHM_DIR%" mkdir "%LHM_DIR%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri 'https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases/download/v0.9.6/LibreHardwareMonitor.zip' -OutFile '%TEMP%\LHM.zip'"
if errorlevel 1 goto :lhm_manual
if not exist "%TEMP%\LHM.zip" goto :lhm_manual
for /f %%A in ('powershell -NoProfile -Command "(Get-Item '%TEMP%\LHM.zip').Length"') do set "LHM_SIZE=%%A"
if not "%LHM_SIZE%"=="6632626" (
  echo   Ukuran file download tidak cocok (dapat %LHM_SIZE%, harus 6632626). Download rusak, dibatalkan.
  del "%TEMP%\LHM.zip" >nul 2>&1
  goto :lhm_manual
)
echo   Download OK (6.632.626 byte), mengekstrak ke %LHM_DIR%...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Path '%TEMP%\LHM.zip' -DestinationPath '%LHM_DIR%' -Force"
del "%TEMP%\LHM.zip" >nul 2>&1
if not exist "%LHM_DIR%\LibreHardwareMonitor.exe" goto :lhm_manual
echo   LibreHardwareMonitor berhasil di-download dan diekstrak.
echo   CATATAN: server dashboard sekarang mengaktifkan otomatis
echo   Remote Web Server LHM (port 8085) lewat file config-nya, jadi
echo   suhu/kipas/daya tampil tanpa langkah manual. Kalau tetap tidak
echo   tampil, aktifkan manual di LHM (Options ^> Remote Web Server ^> Start).
goto :step_nocturne
:lhm_manual
echo   GAGAL download LibreHardwareMonitor otomatis.
echo   Download manual dari:
echo   https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases/tag/v0.9.6
echo   (file LibreHardwareMonitor.zip), ekstrak ke folder mana saja, lalu jalankan lagi file ini.
echo   Sementara itu dashboard tetap jalan, hanya data suhu/kipas/daya yang kosong.
goto :step_nocturne

:step_nocturne
REM ---------- 7. Nocturne Music (aplikasi musik) ----------
echo [7/7] Mengecek Nocturne Music...
tasklist /FI "IMAGENAME eq nocturne-app.exe" 2>nul | find /I "nocturne-app.exe" >nul
if not errorlevel 1 (
  echo   Nocturne Music sudah jalan.
  goto :done
)
if exist "%LOCALAPPDATA%\Nocturne Music\nocturne-app.exe" (
  echo   Nocturne Music sudah ter-install.
  goto :done
)
if exist "%LOCALAPPDATA%\Nocturne.Music\nocturne-app.exe" (
  echo   Nocturne Music sudah ter-install.
  goto :done
)
if exist "C:\Program Files\Nocturne Music\nocturne-app.exe" (
  echo   Nocturne Music sudah ter-install.
  goto :done
)
if exist "C:\Program Files (x86)\Nocturne Music\nocturne-app.exe" (
  echo   Nocturne Music sudah ter-install.
  goto :done
)
echo   Nocturne Music belum ada, mendownload v0.9.0 (55,3 MB)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri 'https://github.com/Neo-XD/nocturne-music/releases/download/v0.9.0/Nocturne.Music_0.9.0_x64-setup.exe' -OutFile '%TEMP%\Nocturne-setup.exe'"
if errorlevel 1 goto :nocturne_manual
if not exist "%TEMP%\Nocturne-setup.exe" goto :nocturne_manual
for /f %%A in ('powershell -NoProfile -Command "(Get-Item '%TEMP%\Nocturne-setup.exe').Length"') do set "NOCT_SIZE=%%A"
if not "%NOCT_SIZE%"=="55281470" (
  echo   Ukuran file download tidak cocok (dapat %NOCT_SIZE%, harus 55281470). Download rusak, dibatalkan.
  del "%TEMP%\Nocturne-setup.exe" >nul 2>&1
  goto :nocturne_manual
)
echo   Download OK (55.281.470 byte).
echo   Menjalankan installer Nocturne Music - klik Next sampai selesai.
start /wait "" "%TEMP%\Nocturne-setup.exe"
del "%TEMP%\Nocturne-setup.exe" >nul 2>&1
if exist "%LOCALAPPDATA%\Nocturne Music\nocturne-app.exe" (
  echo   Nocturne Music berhasil di-install.
  goto :done
)
if exist "%LOCALAPPDATA%\Nocturne.Music\nocturne-app.exe" (
  echo   Nocturne Music berhasil di-install.
  goto :done
)
if exist "C:\Program Files\Nocturne Music\nocturne-app.exe" (
  echo   Nocturne Music berhasil di-install.
  goto :done
)
if exist "C:\Program Files (x86)\Nocturne Music\nocturne-app.exe" (
  echo   Nocturne Music berhasil di-install.
  goto :done
)
echo   Installer selesai tapi file Nocturne tidak ketemu di lokasi umum.
echo   Coba install manual dari:
echo   https://github.com/Neo-XD/nocturne-music/releases/tag/v0.9.0
echo   CATATAN: setelah install, buka Nocturne Music dan sign-in
echo   YouTube Music. Kalau sesi kedaluwarsa dan lagu tidak muncul di
echo   kartu Musik, sign-in ulang di Nocturne.
goto :done
:nocturne_manual
echo   GAGAL download Nocturne Music otomatis.
echo   Download manual dari:
echo   https://github.com/Neo-XD/nocturne-music/releases/tag/v0.9.0
echo   (file Nocturne.Music_0.9.0_x64-setup.exe), install, lalu jalankan lagi file ini.
echo   Sementara itu dashboard tetap jalan, hanya kartu Musik yang kosong bila
echo   Nocturne belum ter-install.
goto :done

:done
echo.
echo ================================================
echo  Setup selesai.
if "%SETUP_OK%"=="0" (
  echo  Ada peringatan di atas - baca sebelum lanjut.
)
echo  Server akan menyalakan otomatis Afterburner,
echo  RTSS, dan LibreHardwareMonitor bila sudah ada.
echo ================================================
exit /b 0

:fatal
echo.
echo ================================================
echo  Setup BELUM selesai (lihat pesan di atas).
echo ================================================
echo.
pause
exit /b 1
