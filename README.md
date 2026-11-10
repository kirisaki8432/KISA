# KISA — Pantau PC dari HP

**KISA** adalah dashboard monitoring PC yang dibuka lewat browser HP atau PC. Cukup jalankan server kecil di PC, lalu buka dashboard dari HP yang satu WiFi — tanpa install aplikasi apa pun di HP.

![KISA](https://img.shields.io/badge/KISA-Patch%203.3-blue) ![License](https://img.shields.io/badge/license-MIT-green) ![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey)

## ✨ Fitur utama

- **12 kartu monitoring** dalam 4 grup: Hardware (CPU, RAM, GPU, Daya, FPS), Layar (Waktu, Port, Wallpaper), Media & Jaringan (Musik, Jaringan), Perangkat (Penyimpanan, Fan)
- **Kartu FPS** — FPS game real-time lewat MSI Afterburner (shared memory), lengkap dengan ikon game dan logo publisher
- **Suhu & kipas** — suhu CPU/GPU dan kecepatan kipas CPU + GPU lewat LibreHardwareMonitor
- **Now Playing** — lagu yang sedang diputar (Nocturne / foobar2000 + Gatefold), lengkap dengan sampul album dan LED yang mengikuti warna sampul
- **Wallpaper kustom** — foto atau video sebagai latar dashboard, dengan kompres video otomatis (progres nyata: persen, kecepatan, sisa waktu)
- **7 bahasa** — Indonesia, Inggris, Jepang, Korea, Mandarin, Rusia, Thailand
- **Favicon logo K + PWA** — tab browser menampilkan logo K, dan dashboard bisa ditambahkan ke layar utama HP seperti aplikasi
- **Tampilan bisa diatur** — urutan kartu bisa diseret, warna kartu & LED bisa diganti, mode terang/gelap

## 🖥️ Syarat

| Kebutuhan | Keterangan |
|---|---|
| Windows 10 / 11 | Sistem operasi PC yang dipantau |
| Python 3 | Server dashboard (otomatis dicek saat setup) |
| MSI Afterburner + RTSS | **Wajib** untuk kartu FPS |
| LibreHardwareMonitor | **Wajib** untuk suhu & kipas |
| FFmpeg | **Wajib** untuk kompres latar video (install: `winget install Gyan.FFmpeg`) |
| Nocturne / foobar2000 | Opsional, untuk kartu Now Playing |

> 💡 **Setup otomatis** (`Setup_Otomatis.bat`) akan mengecek dan melengkapi Python, MSI Afterburner, LibreHardwareMonitor, dan Nocturne saat pertama kali dijalankan — jadi kamu tidak harus install semuanya manual. Lihat [TUTORIAL.md](TUTORIAL.md) bagian "Pasang manual" kalau setup otomatis gagal.

## 🚀 Cara pakai

> 📖 **Baru pertama kali pasang?** Ikuti [TUTORIAL.md](TUTORIAL.md) — panduan langkah demi langkah (unduh, setup, buka di HP, pasang FFmpeg, troubleshooting).

1. **Download** file zip dari halaman [Releases](../../releases) (atau clone repo ini), lalu **ekstrak ke folder baru**.
2. **Jalankan `Jalankan_di_PC.bat`** dari folder hasil ekstrak. Biarkan jendela hitamnya tetap terbuka selama dashboard dipakai.
3. **Buka dashboard:**
   - **Di HP (cara cepat):** setelah server jalan, file `QR_Dashboard.png` otomatis terbuka di layar PC — scan dengan kamera HP, dashboard langsung terbuka.
   - **Di HP (manual):** ketik `http://IP-PC:8000` di browser HP (alamat IP ditampilkan di jendela server).
   - **Di PC sendiri:** buka `http://localhost:8000`.
4. Kalau HP tidak bisa membuka: izinkan port **8000** di firewall (server sudah mencoba mengaturnya otomatis; kalau gagal, jalankan `.bat` dengan klik kanan → *Run as administrator*, sekali saja).

> ⚠️ **Penting:** dashboard ini **tidak bisa jalan dari GitHub Pages saja**. KISA butuh server Python yang berjalan di PC masing-masing — GitHub hanya tempat mengunduh kodenya. Setiap pengguna menjalankan servernya sendiri di PC-nya.

## 📁 Isi repo

```
KISA/
├── dashboard.html          # Halaman dashboard (satu file, dibuka lewat server)
├── monitor_server.py       # Server Python (port 8000)
├── Jalankan_di_PC.bat      # Launcher: setup otomatis + jalankan server
├── Setup_Otomatis.bat      # Setup: cek & lengkapi Python, Afterburner, LHM, Nocturne
├── Install_winrt.bat       # Install winrt (untuk Now Playing)
├── requirements.txt        # Dependensi Python (psutil)
├── TUTORIAL.md             # Tutorial pemasangan langkah demi langkah
├── covers/                 # Gambar sampul cadangan untuk Now Playing
└── publisher/              # Logo publisher game (76 logo)
```

## 📜 Riwayat versi

Lihat **Atur Tampilan → Riwayat Update** di dalam dashboard. Versi saat ini: **Patch 3.3** (KISA percobaan 182).

## 🤝 Dukungan

Dikembangkan oleh **kirisaki**. Kalau KISA bermanfaat, dukung pengembangannya lewat Saweria (tautan donasi ada di dalam dashboard, menu **Atur Tampilan → Dukungan**).

## 📄 Lisensi

MIT License — lihat file [LICENSE](LICENSE). Bebas dipakai, diubah, dan dibagikan, dengan tetap mencantumkan lisensi ini.

---

## English summary

**KISA** is a PC monitoring dashboard you open in your phone or PC browser. Run the small Python server on your Windows PC, then open the dashboard from any phone on the same Wi-Fi — no app install needed on the phone.

- 12 monitoring cards (Hardware, Display, Media & Network, Devices)
- Real-time game FPS via MSI Afterburner, temps & fans via LibreHardwareMonitor
- Now Playing (Nocturne / foobar2000), custom photo/video wallpaper with server-side compression, 7 languages, K-logo favicon + PWA support
- **Quick start:** download the zip from Releases → extract → run `Jalankan_di_PC.bat` → open `http://localhost:8000` (or scan the QR code from your phone)
- **Note:** this dashboard cannot run from GitHub Pages alone — it needs the Python server running on each user's own PC. GitHub is only where you download the code.
