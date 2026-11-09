@echo off
chcp 65001 >nul
title Install winrt (untuk deteksi lagu Nocturne)
echo ================================================
echo  Install paket winrt (sekali saja)
echo  Dipakai server untuk membaca lagu Nocturne
echo  lewat GSMTC. Perlu internet.
echo ================================================
echo.
python --version
echo.
python -c "import winrt.windows.media.control" >nul 2>&1
if errorlevel 1 (
  echo Menginstal winrt-Windows.Media.Control...
  python -m pip install --only-binary :all: winrt-Windows.Media.Control
) else (
  echo winrt sudah terpasang.
  goto :cek
)
python -c "import winrt.windows.media.control" >nul 2>&1
if errorlevel 1 (
  echo Coba paket winrt lama sebagai cadangan...
  python -m pip install --only-binary :all: winrt
)
:cek
echo.
python -c "import winrt.windows.media.control; print('OK: winrt terpasang dan bisa diimpor.')"
if errorlevel 1 (
  echo.
  echo GAGAL: winrt tidak bisa dipasang/diimpor di Python ini.
  echo Catat versi Python di atas dan kirim screenshot jendela ini.
) else (
  echo.
  echo Selesai. Sekarang jalankan Jalankan_di_PC.bat seperti biasa.
)
echo.
pause
