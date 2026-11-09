@echo off
chcp 65001 >nul
title KISA - Agen PC
echo ================================================
echo  KISA - untuk dipantau dari HP
echo ================================================
REM Setup otomatis dulu: lengkapi Python/psutil/winrt/Afterburner/
REM LibreHardwareMonitor bila belum ada (yang sudah ada dilewati).
if exist "%~dp0Setup_Otomatis.bat" (
  call "%~dp0Setup_Otomatis.bat"
  if errorlevel 1 (
    echo.
    echo Setup belum selesai. Perbaiki pesan di atas lalu jalankan lagi file ini.
    pause
    exit /b 1
  )
)
echo.
echo Menjalankan server di jendela "KISA Server"...
echo Server akan menyalakan otomatis Afterburner, RTSS, dan
echo LibreHardwareMonitor bila sudah ter-install di PC ini.
echo.
REM Hapus QR lama supaya yang dibuka nanti pasti QR baru dari server ini.
if exist "%~dp0QR_Dashboard.png" del "%~dp0QR_Dashboard.png"
start "KISA Server" /D "%~dp0" python monitor_server.py
REM Tunggu QR dibuat server (maks ~20 detik), lalu buka supaya bisa di-scan dari HP.
set "QR_OK="
for /L %%i in (1,1,20) do (
  if exist "%~dp0QR_Dashboard.png" set "QR_OK=1"
  if defined QR_OK goto :qr_found
  timeout /t 1 /nobreak >nul
)
:qr_found
if defined QR_OK (
  echo.
  echo QR dashboard dibuat - membukanya supaya bisa di-scan dari HP.
  start "" "%~dp0QR_Dashboard.png"
) else (
  echo.
  echo QR dashboard tidak dibuat (server mungkin belum jalan atau segno
  echo belum ter-install). Dashboard tetap bisa dibuka manual lewat
  echo alamat IP yang tampil di jendela "KISA Server".
)
echo.
echo Server jalan di jendela "KISA Server" - biarkan jendela itu
echo tetap terbuka selama dashboard dipakai.
echo Jendela ini boleh ditutup, server tetap jalan.
pause
