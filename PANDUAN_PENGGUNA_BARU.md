# Panduan Pengguna Baru KISA

Panduan ini untuk yang baru pertama kali memakai KISA. Ikuti dari atas ke
bawah — selesai mengikuti panduan ini, semua fitur KISA sudah jalan.

**KISA** adalah dashboard untuk memantau PC dari HP lewat browser. Kamu tidak
perlu install apa pun di HP — cukup pasang KISA di PC, lalu buka dashboard
dari HP yang tersambung ke Wi-Fi yang sama.

> Panduan ini ditulis untuk **KISA Patch 4.7**. Kalau kamu memakai file zip
> (bukan installer), ikut [TUTORIAL.md](TUTORIAL.md) — panduan itu memakai
> jalur zip. Isi kedua panduan saling melengkapi, bukan menggantikan.

## Yang dibutuhkan

| Kebutuhan | Keterangan |
|---|---|
| PC Windows 10 / 11 | PC yang mau dipantau |
| HP + browser (Chrome/Safari) | Untuk membuka dashboard |
| Wi-Fi yang sama | HP dan PC harus satu jaringan (atau hotspot, lihat Bagian 5) |
| Internet (saat install) | Untuk mengunduh aplikasi pendukung |
| Akun administrator Windows | Untuk install sebagian aplikasi pendukung |

## Bagian 1 — Install KISA (cara yang disarankan)

Cara ini memakai installer. Semua aplikasi pendukung ikut ditawarkan di
tengah proses install, jadi kamu tidak perlu download satu-satu.

1. Buka halaman Releases KISA: https://github.com/kirisaki8432/KISA/releases
2. Download file installer versi terbaru: **KISA-Setup-X.Y.exe** (pilih angka
   versi paling besar).
3. Klik dua kali file installer itu.
4. Kalau muncul SmartScreen Windows, klik **More info**, lalu **Run anyway**.
5. Ikuti wizard sampai halaman **Aplikasi Pendukung**.
6. Di halaman Aplikasi Pendukung ada 5 kelompok (lihat Bagian 2). Yang belum
   terpasang di PC sudah tercentang otomatis; yang sudah ada tidak bisa
   dicentang karena akan dilewati. Biarkan apa adanya, lalu klik **Next**.
7. Tunggu Setup Otomatis selesai (8 langkah — yang sudah ada dilewati).
   Jangan ditutup di tengah jalan. Install perlu internet.
8. Klik **Finish**. Aplikasi KISA terbuka.
9. Kalau Windows Firewall bertanya, klik **Allow** / **Izinkan** (jaringan
   Private).
10. (Opsional) Di halaman Tasks installer ada pilihan **Jalankan KISA
    otomatis saat Windows nyala**. Centang kalau mau KISA jalan sendiri
    setiap PC dinyalakan. Pilihan ini juga bisa diubah nanti dari menu tray
    (klik kanan ikon K di tray).

> Kalau install gagal dengan pesan **"DeleteFile failed; code 5"**, itu
> karena KISA lama masih jalan. Tutup KISA sampai tuntas dulu — klik kanan
> ikon K di tray (pojok kanan bawah) lalu **Keluar** — baru jalankan
> installer lagi. (Lihat Bagian 6, masalah 3.)

## Bagian 2 — Aplikasi pendukung, satu per satu

KISA memakai 5 aplikasi pendukung. Masing-masing punya satu fungsi. Di bawah
ini, per aplikasi: fungsinya di KISA, cara pasangnya (otomatis lewat
installer atau manual), dan setting apa yang dilakukan otomatis oleh KISA
vs yang harus kamu lakukan sendiri.

### 2.1 Python 3.15 (+ psutil, winsdk, segno)

- **Fungsi di KISA:** menjalankan server KISA, membuat QR dashboard, dan
  mendeteksi lagu yang sedang diputar.
- **Pasang otomatis:** installer memasang Python 3.15 lewat winget, lalu
  memasang paket yang dibutuhkan (psutil, segno, winrt). Kamu tidak perlu
  apa-apa.
- **Pasang manual (kalau otomatis gagal):**
  1. Download dari https://www.python.org/downloads/ (atau langsung:
     https://www.python.org/ftp/python/3.15.2/python-3.15.2-amd64.exe).
  2. Saat install, centang **"Add python.exe to PATH"**, lalu klik Install.
  3. Buka Command Prompt, ketik `python -m pip install psutil segno`,
     lalu Enter.
  4. Jalankan lagi installer KISA (atau `Setup_Otomatis.bat`).
- **Setting manual:** tidak ada. Setelah terpasang, server langsung bisa
  jalan.

### 2.2 MSI Afterburner + RTSS

- **Fungsi di KISA:** kartu **FPS** (angka FPS game yang sedang dimainkan,
  lengkap dengan ikon game).
- **Pasang otomatis:** installer memasang Afterburner lewat winget
  (paket Guru3D.Afterburner, cadangan MSI.Afterburner). RTSS ikut
  terpasang bersama Afterburner.
- **Jalankan otomatis:** begitu dashboard pertama kali dibuka, server KISA
  menyalakan otomatis Afterburner + RTSS — asalkan keduanya sudah
  ter-install di PC. Kamu tidak perlu membukanya manual tiap kali.
- **Pasang manual (kalau otomatis gagal):**
  1. Download dari https://www.msi.com/Landing/afterburner/graphics-cards
     (atau cari "MSI Afterburner" di Guru3D).
  2. Jalankan installer-nya, ikuti sampai selesai (RTSS ikut terpasang).
  3. Jalankan lagi installer KISA, atau jalankan `Setup_Otomatis.bat`.
- **Setting manual (satu langkah, penting untuk FPS):**
  1. Buka MSI Afterburner.
  2. Klik ikon gerigi (**Settings**).
  3. Buka tab **Monitoring**.
  4. Cari **Framerate** di daftar, pastikan tercentang.
  5. Klik **OK**.
  6. Mainkan game apa pun — kartu FPS di dashboard akan menampilkan angka.
- **Catatan:** kalau kamu tidak mau tampilan FPS (OSD) muncul di dalam
  game, tapi tetap mau angkanya tampil di dashboard KISA: di tab Monitoring
  yang sama, hilangkan centang **"Show in On-Screen Display"** pada
  tiap-tiap grafik, tapi biarkan **Framerate** tetap tercentang. KISA
  membaca FPS dari Afterburner, bukan dari OSD.

### 2.3 LibreHardwareMonitor (LHM)

- **Fungsi di KISA:** kartu suhu CPU/GPU, kecepatan kipas, dan daya.
- **Pasang otomatis:** installer mengunduh LHM v0.9.6 (6,3 MB) dan
  mengekstraknya ke folder
  `%APPDATA%\PCMonitorHUD\tools\LibreHardwareMonitor`. LHM itu aplikasi
  portable — tidak ada proses install, cukup diekstrak dan dijalankan.
- **Jalankan otomatis:** begitu dashboard pertama kali dibuka, server KISA
  menyalakan otomatis LHM. Server juga mengaktifkan otomatis **Remote Web
  Server LHM (port 8085)** lewat file config LHM, supaya suhu/kipas/daya
  tampil tanpa langkah manual. Setting config ini hanya ditulis saat LHM
  sedang tidak jalan; kalau LHM sudah jalan tapi web server-nya mati,
  server me-restart LHM supaya settingnya aktif.
- **Pasang manual (kalau otomatis gagal):**
  1. Download https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases/download/v0.9.6/LibreHardwareMonitor.zip
  2. Ekstrak zip itu ke folder mana saja (contoh: `C:\LibreHardwareMonitor\`).
  3. Jalankan `LibreHardwareMonitor.exe` dari folder hasil ekstrak.
  4. Jalankan lagi installer KISA, atau jalankan `Setup_Otomatis.bat`.
- **Setting manual (hanya kalau suhu tetap tidak tampil):**
  1. Buka jendela LibreHardwareMonitor.
  2. Klik menu **Options** → **Remote Web Server** → **Start**.
  3. Pastikan port-nya **8085**.
  4. Tutup jendela **"KISA Server"** yang lama, lalu jalankan lagi KISA.
  5. Suhu/kipas/daya akan tampil di dashboard.

### 2.4 Nocturne Music

- **Fungsi di KISA:** kartu **Now Playing** — judul lagu, sampul album, dan
  LED yang mengikuti warna sampul.
- **Pasang otomatis:** installer mengunduh Nocturne Music v0.9.0 (55,3 MB)
  dan menjalankan installer-nya. Klik **Next** sampai selesai.
- **Pasang manual (kalau otomatis gagal):**
  1. Download https://github.com/Neo-XD/nocturne-music/releases/tag/v0.9.0
     (file `Nocturne.Music_0.9.0_x64-setup.exe`).
  2. Jalankan file itu, klik **Next** sampai selesai.
- **Setting manual (satu langkah):**
  1. Buka Nocturne Music.
  2. Sign-in ke **YouTube Music** di dalam Nocturne.
  3. Putar lagu apa pun. Kartu Now Playing di dashboard mendeteksi lagu
     secara otomatis lewat Windows (GSMTC) — tidak ada setting khusus di
     Nocturne untuk KISA.
- **Catatan:** kalau lagu tiba-tiba tidak muncul lagi di kartu Musik,
  biasanya sesi YouTube Music di Nocturne kedaluwarsa — sign-in ulang di
  Nocturne. Alternatif Nocturne: **foobar2000 + Gatefold** juga didukung
  kartu Now Playing.

### 2.5 FFmpeg

- **Fungsi di KISA:** kompres latar video (pakai GPU/AMF) saat kamu memasang
  video sebagai latar dashboard. Tanpa FFmpeg, kompres jatuh ke mode
  browser (lambat) dan tulisan "Mesin saat ini" menampilkan "—".
- **Pasang otomatis:** installer memasang FFmpeg lewat
  `winget install Gyan.FFmpeg` (langkah 8 Setup Otomatis). Perlu akun
  administrator.
- **Pasang manual (kalau otomatis gagal):**
  1. Buka **Command Prompt sebagai Administrator** (cari `cmd` di Start →
     klik kanan → Run as administrator).
  2. Ketik `winget install Gyan.FFmpeg`, lalu Enter. Tunggu sampai selesai.
  3. Tutup jendela **"KISA Server"** yang lama, lalu jalankan lagi KISA.
  4. Cek: buka Command Prompt biasa, ketik `ffmpeg -version`. Kalau muncul
     tulisan `ffmpeg version ...`, berarti sudah terpasang.
- **Setting manual:** tidak ada. Setelah terpasang dan server di-restart,
  kompres latar langsung memakai FFmpeg.

### Ringkasan: apa yang otomatis, apa yang manual

| Hal | Otomatis | Manual (kamu) |
|---|---|---|
| Download + install 5 aplikasi pendukung | Ya, lewat halaman Aplikasi Pendukung di installer | Hanya kalau otomatis gagal (link ada di atas) |
| Menyalakan Afterburner + RTSS + LHM | Ya, saat dashboard pertama dibuka | — |
| Remote Web Server LHM (port 8085) | Ya, lewat file config LHM | Hanya kalau tetap tidak tampil (Bagian 2.3) |
| Monitoring "Framerate" di Afterburner | Tidak | Centang sekali di Settings → Monitoring (Bagian 2.2) |
| Sign-in YouTube Music di Nocturne | Tidak | Sign-in sekali di Nocturne (Bagian 2.4) |
| QR dashboard | Ya, dibuat ulang dari IP LAN saat ini | Scan ulang kalau IP PC berubah |
| Update KISA | Cek + unduh dari dalam aplikasi (Bagian 4) | Tekan tombol "Periksa Pembaruan" |

## Bagian 3 — Cek pertama kali: semua kartu hidup atau tidak

1. Buka aplikasi KISA di PC (atau buka `http://localhost:8000` di browser
   PC).
2. Di HP: tekan tombol **QR** di header dashboard, lalu scan QR yang muncul
   dengan kamera HP. Dashboard terbuka di browser HP. (Kalau QR sudah
   tertutup, buka file `QR_Dashboard.png` di folder KISA, atau ketik manual
   `http://IP-PC:8000` — alamat IP tampil di jendela "KISA Server".)
3. Supaya terasa seperti aplikasi, tambahkan ke layar utama HP:
   - Android Chrome: titik tiga → **Tambahkan ke Layar Utama**.
   - iPhone Safari: tombol Share → **Add to Home Screen**.
4. Periksa tiap kartu:
   - **WAKTU:** jam berdetak tiap detik.
   - **CPU / RAM / GPU:** ada angka yang berubah.
   - **Suhu (di kartu CPU/GPU):** ada angka suhu, bukan "Tidak tersedia".
   - **FPS:** mainkan game apa pun — angkanya muncul. Kalau masih "--",
     lihat Bagian 6 masalah 5.
   - **Now Playing:** putar lagu di Nocturne — judul + sampul muncul.
     Kalau kosong, lihat Bagian 6 masalah 6.
   - **Wallpaper:** pasang foto/video lewat Atur Tampilan → Latar Belakang.
     Video terkompres otomatis (butuh FFmpeg, Bagian 2.5).
5. Buka **Atur Tampilan → Dukungan**: 5 aplikasi pendukung harus
   menampilkan **Sudah ada**. Kalau ada yang **Belum ada**, pasang dari
   Bagian 2.

Arti tampilan kosong:

| Tampilan | Artinya | Perbaiki di |
|---|---|---|
| Suhu/kipas/daya "Tidak tersedia" | LHM belum jalan, atau Remote Web Server-nya mati | Bagian 2.3 |
| FPS "--" atau "MSI Afterburner tidak berjalan" | Afterburner tidak jalan, atau tidak ada game | Bagian 2.2 / Bagian 6 masalah 5 |
| Kartu Musik kosong | Tidak ada lagu diputar, atau Nocturne belum sign-in | Bagian 2.4 / Bagian 6 masalah 6 |
| "Mesin saat ini: —" di kompres latar | FFmpeg belum terpasang | Bagian 2.5 |

## Bagian 4 — Update KISA dari dalam aplikasi (Patch 4.6 ke atas)

1. Buka **Atur Tampilan → Riwayat Update**.
2. Tekan tombol **Periksa Pembaruan**.
3. Kalau ada versi baru: muncul kartu versi baru + changelog. Tekan
   **Unduh & Pasang**, tunggu progress sampai selesai, lalu tekan
   **Pasang & Restart**.
4. Kalau muncul **"Kamu sudah memakai versi terbaru"**: tidak ada yang
   perlu dilakukan.
5. Kalau muncul **"Tidak bisa memeriksa update"**: PC tidak bisa mencapai
   GitHub saat itu — periksa internet, lalu tekan lagi. Sejak Patch 4.7,
   server otomatis mencoba jalur cadangan (halaman rilis GitHub) bila API
   GitHub gagal, dan jam "Terakhir diperiksa" tetap tercatat walau
   pemeriksaan gagal.
6. Di HP: update aplikasi HP (APK) juga lewat tombol yang sama — unduh APK
   baru, izinkan "install aplikasi tidak dikenal" sekali saja, lalu tekan
   Install. APK 4.2 ke atas menimpa versi lama tanpa hapus dulu.

## Bagian 5 — Pakai HP tanpa internet (offline)

Monitoring HP–PC **tidak butuh internet sama sekali**. Yang penting HP dan
PC satu jaringan lokal. Caranya:

1. **Wi-Fi rumah yang sama** (cara biasa): sambungkan HP dan PC ke Wi-Fi
   yang sama.
2. **Hotspot HP:** nyalakan hotspot di HP (data seluler boleh dimatikan),
   sambungkan Wi-Fi PC ke hotspot itu. Android boleh menampilkan
   "Wi-Fi tidak ada internet" — abaikan saja, dashboard tetap jalan.
3. **Hotspot PC:** nyalakan Mobile Hotspot di Windows, sambungkan HP ke
   hotspot PC itu.
4. IP PC berubah setiap ganti jaringan — scan ulang QR (QR dibuat ulang
   dari IP LAN saat ini).

Yang butuh internet hanya: sampul lagu dari YouTube/iTunes (kalau gagal,
dashboard memakai gambar cadangan lokal), dan cek update (Bagian 4).

## Bagian 6 — Troubleshooting (masalah yang sering terjadi)

| Masalah | Perbaikan |
|---|---|
| Dashboard masih menampilkan versi lama (mis. 4.4 padahal sudah install 4.7) | Server yang jalan masih dari folder lama. Tutup jendela "KISA Server" yang lama, ekstrak zip baru ke folder BARU, jalankan `Jalankan_di_PC.bat` di dalam folder itu, lalu tutup tab browser lama dan buka lagi. |
| Jendela server langsung hilang tanpa muncul IP | Server lama masih jalan dan memakai port 8000. Tutup semua jendela "KISA Server" (cek juga Task Manager → `python.exe`), lalu jalankan lagi. |
| Install .exe gagal: "DeleteFile failed; code 5" | KISA lama masih jalan di tray. Klik kanan ikon K di tray → **Keluar**, lalu jalankan installer lagi. |
| Suhu/kipas/daya "Tidak tersedia" | Di LHM: Options → Remote Web Server → Start (port 8085), lalu restart server KISA. (Bagian 2.3.) |
| FPS "--" padahal game jalan | Jalankan Afterburner + RTSS, pastikan game 3D sedang berjalan, dan cek "Framerate" tercentang di Afterburner → Settings → Monitoring. (Bagian 2.2.) |
| Kartu Musik kosong | Putar lagu di Nocturne. Kalau tetap kosong, sign-in ulang YouTube Music di Nocturne. (Bagian 2.4.) |
| Kompres latar lambat / "Mesin saat ini: —" | Pasang FFmpeg (`winget install Gyan.FFmpeg`), lalu restart server KISA. (Bagian 2.5.) |
| HP tidak bisa membuka dashboard | Pastikan HP dan PC satu Wi-Fi yang sama, jendela "KISA Server" masih terbuka, dan coba dulu di PC (`http://localhost:8000`). Kalau di PC bisa tapi di HP tidak, hampir pasti Windows Firewall — jalankan `Jalankan_di_PC.bat` sebagai Administrator sekali saja. |
| "Periksa Pembaruan" selalu gagal padahal online | Di Patch 4.7 sudah diperbaiki (jalur cadangan halaman rilis). Kalau masih memakai 4.6 ke bawah, update manual dari halaman Releases. (Bagian 4.) |
| Browser bilang `ERR_CONNECTION_REFUSED` | Server memang belum jalan. Tunggu Setup Otomatis sampai selesai ("Setup selesai") dan jendela "KISA Server" terbuka. Kalau sudah selesai tapi server tidak jalan, buka Command Prompt di folder KISA lalu jalankan `python monitor_server.py` dan lihat pesan errornya. |

## Bagian 7 — Keamanan

- Dashboard ini hanya untuk **jaringan lokal** (Wi-Fi rumah / hotspot
  sendiri). **Jangan** forward port 8000 di router ke internet.
- Tidak ada data yang dikirim ke server luar — semua data hanya dari PC
  kamu ke HP kamu di jaringan yang sama.
- Kalau memakai KISA versi zip (bukan installer): jangan bagikan folder
  kerja mentah — di dalamnya bisa ada `QR_Dashboard.png` berisi IP LAN
  kamu. Bagikan file zip yang sudah dibersihkan saja.

## Bagian 8 — Kalau masih bermasalah

- Jalur instalasi file zip (bukan installer) dijelaskan lengkap di
  [TUTORIAL.md](TUTORIAL.md) — termasuk tabel "Pasang manual" untuk semua
  komponen dan tips PC spek rendah.
- Naskah video tutorial ada di [NASKAH_VIDEO.md](NASKAH_VIDEO.md).
- Versi yang terpasang dan riwayat perubahan: **Atur Tampilan → Riwayat
  Update** di dalam dashboard.
