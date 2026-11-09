# KISA sebagai Aplikasi — .exe PC + .apk HP (S138 Cara 3)

Paket ini mengubah KISA (Patch 3.3) dari "server + tab browser" menjadi
aplikasi beneran: **KISA.exe** di PC dan **KISA.apk** di HP. Fungsinya sama
persis — yang berubah hanya bungkusnya.

> **Penting: file .exe dan .apk JADI tidak ada di zip ini.** Keduanya hanya
> bisa dibuat di Windows (untuk .exe) dan dengan Android SDK (untuk .apk).
> Cara mendapatkannya ada di bawah — lewat GitHub Actions (paling mudah)
> atau dibangun sendiri di PC Windows.

## Cara mendapatkan biner jadi — lewat GitHub Actions (disarankan)

1. Push isi repo ini ke GitHub (repo Public, mis. `KISA`).
2. Buat tag rilis: `git tag v3.3 && git push origin v3.3`
   (atau buka tab **Actions → Build KISA Apps → Run workflow**).
3. Tunggu kedua job selesai, lalu unduh dari tab **Artifacts**:
   - `KISA-exe-3.3` → `KISA.exe`
   - `KISA-Setup-3.3` → `KISA-Setup-3.3.exe` (installer)
   - `KISA-apk-3.3` → `app-debug.apk`

## Cara membangun sendiri di PC Windows (.exe + installer)

```bat
pip install -r requirements.txt
pip install -r app\requirements-app.txt
pyinstaller app\KISA.spec
iscc app\KISA-Setup.iss
```

Hasil: `dist\KISA.exe` dan `dist-installer\KISA-Setup-3.3.exe`.
Butuh: Python 3.12 + Inno Setup 6 (diinstal CI lewat `choco install innosetup`).

## Cara memasang di PC — KISA.exe

1. Jalankan `KISA-Setup-3.3.exe` → Next-Next-Finish (instal ke
   `C:\Program Files\KISA`, shortcut Desktop + Start Menu, ada uninstaller).
2. Centang **"Pasang komponen pendukung"** saat instalasi — ini menjalankan
   `Setup_Otomatis.bat` untuk memasang MSI Afterburner, LibreHardwareMonitor,
   dan Nocturne (tetap dibutuhkan: FPS dari Afterburner, suhu/kipas dari LHM).
   FFmpeg untuk kompres latar tetap dipasang manual:
   `winget install Gyan.FFmpeg` (lihat TUTORIAL.md).
3. Buka KISA dari shortcut — server jalan otomatis di dalam aplikasi dan
   dashboard tampil di jendela aplikasi sendiri (bukan tab browser).
4. Ikon tray KISA: klik kanan untuk buka dashboard, ubah alamat, atur
   auto-start Windows, atau keluar. Auto-start juga bisa diatur dari
   installer (centang "Jalankan KISA otomatis saat Windows nyala").

Tanpa installer pun bisa: jalankan `KISA.exe` langsung (portable, satu file).

## Cara memasang di HP — KISA.apk

1. Di HP, izinkan instalasi dari sumber tak dikenal untuk file APK ini.
2. Instal `app-debug.apk` → buka aplikasi KISA.
3. Masukkan alamat server PC, contoh: `http://192.168.1.10:8000`
   (alamat IP LAN PC — lihat di jendela server PC atau scan QR dashboard).
   HP dan PC harus di **Wi-Fi yang sama**.
4. Alamat tersimpan; ganti lewat menu "Ubah alamat server".

Catatan: APK ini adalah wrapper WebView — ia membuka dashboard server PC,
bukan memonitor HP. Alternatif tanpa APK: tambah dashboard ke layar utama
HP dari browser (PWA, ikon K — sudah ada sejak Patch 3.3).

## Isi paket aplikasi (`app/`)

| File | Fungsi |
|---|---|
| `app/kisa_app.py` | Launcher: server in-process + jendela pywebview + tray + auto-start |
| `app/KISA.spec` | Konfigurasi PyInstaller (onefile, tanpa console) |
| `app/requirements-app.txt` | Dependensi aplikasi (pywebview, pystray, pillow, pyinstaller) |
| `app/KISA-Setup.iss` | Installer Inno Setup 6 (Next-Next-Finish) |
| `app/icons/` | Ikon K: `kisa.ico` (multi-ukuran), PNG 180/192/512, `kisa.svg` sumber |
| `app/twa/` | Manifest Bubblewrap + assetlinks (lihat catatan TWA di bawah) |
| `app/android/` | Proyek wrapper WebView Android (MainActivity + Gradle) |
| `.github/workflows/build-apps.yml` | CI: job Windows (.exe + installer) + job Android (.apk) |

## Catatan jujur (baca sebelum memakai)

- **TWA tidak dipakai untuk KISA.** File di `app/twa/` adalah jalur TWA
  standar, tapi TWA butuh PWA di URL HTTPS publik — dashboard KISA hanya
  ada di server lokal PC (`http://<IP-LAN>:8000`). Jalur APK yang benar
  adalah wrapper WebView di `app/android/`. Detail: `app/twa/README.md`.
- **QR_Dashboard.png** dalam mode .exe onefile ditulis ke folder sementara
  PyInstaller dan dihapus saat aplikasi keluar. Jendela aplikasi menampilkan
  dashboard langsung, jadi QR tidak wajib; alamat LAN tetap tampil di
  dashboard dan bisa dilihat di menu aplikasi.
- **Antivirus** kadang menandai .exe hasil PyInstaller sebagai mencurigakan
  (false positive yang umum). Kalau terjadi, laporkan sebagai aman / tambahkan
  pengecualian, atau bangun sendiri dari kode sumber ini.
- **Keamanan jaringan sama seperti sebelumnya:** dashboard hanya untuk
  jaringan lokal — jangan port-forward port 8000 ke internet.
- **Tidak ada data pribadi** di paket ini (disapu seperti paket publik).
