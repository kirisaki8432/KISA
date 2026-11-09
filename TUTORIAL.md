# Tutorial Pemasangan KISA (untuk pengguna baru)

KISA adalah dashboard untuk memantau PC dari HP lewat browser. Kamu tidak perlu
install apa pun di HP — cukup jalankan server kecil di PC, lalu buka dashboard
dari HP yang tersambung ke Wi-Fi yang sama.

> 📖 Versi singkat ada di README.md bagian "Cara pakai". File ini versi
> langkah-demi-langkah untuk yang baru pertama kali memasang.

## Yang dibutuhkan

| Kebutuhan | Keterangan |
|---|---|
| PC Windows 10 / 11 | PC yang mau dipantau |
| HP + browser (Chrome/Safari) | Untuk membuka dashboard |
| Wi-Fi yang sama | HP dan PC harus satu jaringan |
| Internet (saat setup) | Untuk mengunduh Python, Afterburner, LHM, Nocturne |
| Python 3 | Dicek & dipasang otomatis oleh Setup (lihat Langkah 2) |

Sisanya — MSI Afterburner, LibreHardwareMonitor, Nocturne — diurus oleh
Setup Otomatis. Yang wajib dipasang manual hanya **FFmpeg** (Langkah 4).

## Langkah 1 — Unduh dan ekstrak

1. Unduh file zip KISA (dari halaman Releases di GitHub, atau dari link Google Drive).
2. Klik kanan zip → **Extract All** (atau **Ekstrak di sini**), ke folder baru.
   Contoh: `C:\KISA\`
3. Buka folder hasil ekstrak. Isinya antara lain `Jalankan_di_PC.bat`,
   `Setup_Otomatis.bat`, `dashboard.html`, dan `monitor_server.py`.

## Langkah 2 — Jalankan `Jalankan_di_PC.bat`

1. Klik dua kali `Jalankan_di_PC.bat`.
2. **Setup Otomatis jalan dulu** (7 langkah, yang sudah ada dilewati):
   1. Python, 2. psutil, 3. segno (untuk QR code), 4. winrt (untuk lagu Nocturne),
   5. MSI Afterburner, 6. LibreHardwareMonitor, 7. Nocturne Music.
   Kalau ada yang belum ada, Setup mengunduh/menginstalnya sendiri — tunggu
   sampai muncul tulisan **"Setup selesai"**. Jangan ditutup di tengah jalan.
3. Kalau Windows Firewall bertanya, klik **Allow / Izinkan** (Private network).
4. Setelah setup selesai, server jalan di jendela hitam **"KISA Server"**.
   Jendela ini harus tetap terbuka selama dashboard dipakai.
5. Gambar QR (`QR_Dashboard.png`) otomatis terbuka di layar — ini untuk HP
   (Langkah 3). Kalau QR tidak muncul, dashboard tetap bisa dibuka manual
   lewat alamat IP yang tampil di jendela "KISA Server".

> ⚠️ Kalau Python belum ada dan install otomatis gagal, install manual dari
> https://www.python.org/downloads/ — centang **"Add python.exe to PATH"**
> saat install, lalu jalankan lagi `Jalankan_di_PC.bat`.

## Langkah 3 — Buka dashboard di PC dan HP

**Di PC sendiri:**
- Buka browser, ketik: `http://localhost:8000`

**Di HP:**
1. HP harus tersambung ke **Wi-Fi yang sama** dengan PC (bukan data seluler).
2. Buka kamera HP, arahkan ke QR yang tampil di layar PC — dashboard langsung
   terbuka di browser HP. (Kalau QR sudah tertutup, buka file
   `QR_Dashboard.png` di folder KISA, atau ketik manual
   `http://IP-PC:8000` — alamat IP tampil di jendela "KISA Server".)
3. Supaya terasa seperti aplikasi, tambahkan ke layar utama:
   - Android Chrome: titik tiga → **Tambahkan ke Layar Utama**
   - iPhone Safari: tombol Share → **Add to Home Screen**

**Tanpa Wi-Fi rumah (hotspot HP):** nyalakan hotspot di HP, sambungkan Wi-Fi PC
ke hotspot itu, lalu jalankan `Jalankan_di_PC.bat` seperti biasa. Pakai alamat
yang ditandai "(kemungkinan hotspot HP)" (biasanya `192.168.43.x`).

## Langkah 4 — Pasang FFmpeg (untuk kompres latar video)

Setup Otomatis **tidak** memasang FFmpeg — ini satu-satunya langkah manual.

1. Buka **Command Prompt sebagai Administrator** (cari `cmd` di Start →
   klik kanan → Run as administrator).
2. Ketik perintah ini, lalu Enter:
   ```
   winget install Gyan.FFmpeg
   ```
   Tunggu sampai unduhan (±245 MB) dan instalasi selesai.
3. Tutup Command Prompt, buka yang baru (biasa saja), ketik:
   ```
   ffmpeg -version
   ```
   Kalau muncul tulisan `ffmpeg version 9.0.2 ...`, berarti sudah terpasang.
4. Tutup jendela **"KISA Server"** yang lama, lalu jalankan lagi
   `Jalankan_di_PC.bat` supaya server membaca FFmpeg yang baru.

Tanpa FFmpeg, kompres latar video jatuh ke mode browser (real-time, lambat)
dan "Mesin saat ini" menampilkan "—". Dengan FFmpeg, kompres jalan di PC
(GPU/AMF atau CPU) dengan progres persen, kecepatan, dan sisa waktu.

## Langkah 5 — Cek FPS, suhu, dan kipas

- **Kartu FPS:** mainkan game apa pun, lalu lihat kartu FPS — angkanya muncul
  kalau **MSI Afterburner + RTSS sedang berjalan** dan monitoring "Framerate"
  aktif di Afterburner (Settings → Monitoring). Kalau Afterburner tidak jalan,
  kartu tetap tampil dengan tulisan "MSI Afterburner tidak berjalan".
- **Suhu & kipas:** suhu CPU/GPU dan kecepatan kipas dibaca lewat
  LibreHardwareMonitor. Server mengaktifkan otomatis Remote Web Server LHM
  (port 8085), jadi biasanya langsung tampil tanpa langkah tambahan.
  Warna suhu: <70°C hijau, 70–85°C kuning, >85°C merah (waspada panas).
  Kalau suhu tetap tidak tampil, aktifkan manual di LHM: Options >
  Remote Web Server > Start (port 8085), lalu jalankan lagi
  `Jalankan_di_PC.bat`.
- **Kartu Musik:** putar lagu di Nocturne Music atau foobar2000 + Gatefold.

## Troubleshooting (masalah yang sering terjadi)

| Masalah | Solusi |
|---|---|
| Browser bilang `ERR_CONNECTION_REFUSED` / "tidak bisa dibuka" | Server memang belum jalan. Cek jendela **Setup Otomatis** — kalau masih di langkah [6/7] mengunduh LibreHardwareMonitor, tunggu sampai "Setup selesai" dan jendela "KISA Server" terbuka sendiri. Kalau setup sudah selesai tapi server tidak jalan, buka Command Prompt di folder KISA lalu jalankan `python monitor_server.py` dan lihat pesan errornya. |
| Server lama masih jalan / port 8000 bentrok | Tutup semua jendela "KISA Server" dan proses `python.exe` di Task Manager, lalu jalankan lagi `Jalankan_di_PC.bat`. |
| Kompres latar lambat / mentok di "Mengirim... 100%" | FFmpeg belum terpasang — ikuti Langkah 4. |
| Kartu FPS tidak muncul angka | Pastikan MSI Afterburner + RTSS berjalan dan game sedang dimainkan. Kalau kartu tertulis "MSI Afterburner tidak berjalan", jalankan Afterburner dulu. |
| HP tidak bisa membuka dashboard | Pastikan HP dan PC satu Wi-Fi yang sama, jendela "KISA Server" masih terbuka, dan coba dulu di PC (`http://localhost:8000`). Kalau di PC bisa tapi di HP tidak, itu hampir pasti Windows Firewall — jalankan `Jalankan_di_PC.bat` sebagai Administrator sekali saja. |

## Pasang manual (kalau Setup Otomatis gagal)

Kalau ada komponen yang gagal dipasang otomatis, pasang manual dari daftar
ini (cek dulu dengan perintah "Cek" — kalau sudah ada, lewati):

| Komponen | Cek | Pasang manual |
|---|---|---|
| Python 3.15 | `python --version` | https://www.python.org/downloads/ — centang "Add python.exe to PATH" saat install |
| psutil | `python -c "import psutil"` | `python -m pip install psutil` |
| segno (QR code) | `python -c "import segno"` | `python -m pip install segno` |
| winrt (lagu Nocturne) | `python -c "import winrt.windows.media.control"` | Jalankan `Install_winrt.bat`, atau `python -m pip install --only-binary :all: winrt-Windows.Media.Control` |
| MSI Afterburner + RTSS (FPS) | File `C:\Program Files (x86)\MSI Afterburner\MSIAfterburner.exe` | https://www.msi.com/Landing/afterburner/graphics-cards — setelah install, aktifkan monitoring "Framerate" di Afterburner |
| LibreHardwareMonitor v0.9.6 (suhu/kipas) | File `LibreHardwareMonitor.exe` di mana saja di PC | https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases/download/v0.9.6/LibreHardwareMonitor.zip — ekstrak ke folder mana saja |
| Nocturne Music v0.9.0 (lagu) | Aplikasi Nocturne terpasang | https://github.com/Neo-XD/nocturne-music/releases/tag/v0.9.0 — setelah install, sign-in YouTube Music |

Tanpa Afterburner, kartu FPS tetap tampil dengan tulisan "MSI Afterburner
tidak berjalan". Tanpa LHM, suhu/kipas/daya tampil kosong. Tanpa winrt,
lagu Nocturne tidak muncul di kartu Musik.

## PC spek rendah

KISA dibuat ringan (server sekitar 37 MB RAM di VM). Kalau PC terasa berat:
1. Atur Tampilan > Performa > Kecepatan Refresh: pilih 1 detik (default)
   atau 2 detik. Makin lambat, makin ringan.
2. Nyalakan **Mode Ringan** (Atur Tampilan > Performa): mematikan FPS dan
   musik, dua fitur yang paling banyak memakai CPU/RAM server.
3. Untuk PC yang lebih rendah lagi (RAM 500 MB–1 GB): nyalakan **Mode Super
   Ringan** — refresh dipaksa 5 detik, yang tersisa hanya data dasar (CPU,
   RAM, storage, jaringan, waktu, daya estimasi).
4. Tutup aplikasi pihak ketiga yang fiturnya tidak dibutuhkan: tidak butuh
   FPS → tutup Afterburner + RTSS; tidak butuh suhu/kipas → tutup LHM.
   Mereka makan RAM jauh lebih besar dari server KISA sendiri.

## Keamanan

- Dashboard ini hanya untuk **jaringan lokal** (Wi-Fi rumah / hotspot sendiri).
  **Jangan** forward port 8000 di router ke internet.
- Tidak ada data yang dikirim ke server luar — semua data hanya dari PC kamu
  ke HP kamu di jaringan yang sama.
