# Naskah Video Tutorial — Cara Memasang KISA

Naskah siap rekam untuk video tutorial pemasangan KISA.
Target durasi total: **±4–5 menit**. Narasi Bahasa Indonesia santai.
Yang merekam: rekaman layar PC (*screen recording*) + suara narasi.
Tidak perlu menampilkan wajah.

> Video ini versi visual dari TUTORIAL.md — ikuti langkah yang sama.

---

## Adegan 1 — Pembuka (0:00–0:20, ±20 detik)

**Yang tampil di layar:** Dashboard KISA di HP (atau di browser PC),
kartu-kartu bergerak — CPU, suhu, FPS game.

**Narasi:**
> "Halo! Ini KISA — dashboard buat memantau PC kamu dari HP. Suhu, FPS game,
> lagu yang lagi diputar, semuanya kelihatan dari HP, tanpa install aplikasi
> apa-apa di HP-nya. Di video ini aku tunjukin cara pasangnya dari nol.
> Gampang banget, ikutin aja."

---

## Adegan 2 — Unduh dan ekstrak (0:20–0:50, ±30 detik)

**Yang tampil di layar:** Halaman Releases GitHub (atau folder Google Drive),
klik unduh zip → klik kanan → Extract All → folder `C:\KISA\` terbuka.

**Narasi:**
> "Pertama, unduh dulu file zip-nya dari link di deskripsi. Terus ekstrak ke
> folder baru, misalnya C:\KISA. Nah, di dalam folder ini ada file
> Jalankan_di_PC.bat — ini yang nanti kita klik."

---

## Adegan 3 — Jalankan Setup Otomatis (0:50–1:45, ±55 detik)

**Yang tampil di layar:** Klik dua kali `Jalankan_di_PC.bat` → jendela hitam
"Setup Otomatis" jalan langkah [1/7] sampai [7/7] → tulisan "Setup selesai"
→ jendela "KISA Server" terbuka → gambar QR muncul.

**Narasi:**
> "Klik dua kali Jalankan_di_PC.bat. Pertama, Setup Otomatis jalan dulu —
> dia ngecek Python, Afterburner, LibreHardwareMonitor, sampai Nocturne.
> Yang belum ada, diunduh dan dipasang sendiri, jadi tinggal tunggu sampai
> muncul tulisan 'Setup selesai'. Jangan ditutup di tengah jalan ya.
> Kalau Windows Firewall nanya, klik Allow aja. Nah, kalau sudah selesai,
> server jalan di jendela 'KISA Server' — jendela ini jangan ditutup selama
> dashboard dipakai. Terus gambar QR-nya otomatis kebuka, ini buat HP nanti."

---

## Adegan 4 — Buka dashboard di PC (1:45–2:10, ±25 detik)

**Yang tampil di layar:** Browser PC, ketik `http://localhost:8000` →
dashboard tampil lengkap.

**Narasi:**
> "Coba dulu di PC: buka browser, ketik localhost:8000. Kalau dashboard-nya
> muncul seperti ini, berarti server sudah jalan."

---

## Adegan 5 — Buka di HP: scan QR + tambah ke layar utama (2:10–2:50, ±40 detik)

**Yang tampil di layar:** Kamera HP diarahkan ke QR di layar PC → dashboard
terbuka di Chrome HP → titik tiga → "Tambahkan ke Layar Utama" → ikon K
muncul di home screen → ketuk ikon, dashboard terbuka seperti aplikasi.

**Narasi:**
> "Sekarang di HP. Pastiin HP dan PC satu Wi-Fi yang sama. Buka kamera,
> arahkan ke QR yang tadi muncul di layar PC — dashboard langsung kebuka di
> browser HP. Biar terasa kayak aplikasi, tambahkan ke layar utama: titik
> tiga, terus 'Tambahkan ke Layar Utama'. Nah, ikon K-nya muncul di home
> screen, tinggal ketuk dan dashboard langsung kebuka."

---

## Adegan 6 — Pasang FFmpeg (2:50–3:25, ±35 detik)

**Yang tampil di layar:** Command Prompt (Admin) → ketik
`winget install Gyan.FFmpeg` → progres unduh → jendela cmd baru →
`ffmpeg -version` → muncul `ffmpeg version 9.0.2` → restart server
(tutup jendela "KISA Server", jalankan lagi `Jalankan_di_PC.bat`).

**Narasi:**
> "Satu langkah manual: pasang FFmpeg, buat kompres latar video. Buka
> Command Prompt sebagai Administrator, ketik 'winget install Gyan.FFmpeg',
> Enter, tunggu sampai selesai. Terus buka Command Prompt baru, ketik
> 'ffmpeg -version' — kalau muncul versi 9.0.2, berarti sudah terpasang.
> Terakhir, restart servernya: tutup jendela 'KISA Server' yang lama, jalankan
> lagi Jalankan_di_PC.bat. Tanpa FFmpeg, kompresnya lambat banget — jadi
> jangan dilewatin."

---

## Adegan 7 — Cek FPS, suhu, dan kipas (3:25–3:55, ±30 detik)

**Yang tampil di layar:** Game dibuka di PC → kartu FPS di dashboard menampilkan
angka + nama game → kartu suhu dan kipas menampilkan angka.

**Narasi:**
> "Terakhir, kita cek: buka game apa aja, kartu FPS langsung nampilin
> angkanya — ini dibaca dari MSI Afterburner, jadi pastiin Afterburner-nya
> jalan. Suhu dan kipas juga langsung kebaca dari LibreHardwareMonitor.
> Udah, selesai. Dashboard kamu siap dipakai."

---

## Adegan 8 — Kalau ada masalah (3:55–4:20, ±25 detik)

**Yang tampil di layar:** Teks di layar (3 poin, satu-satu muncul):
1. "Tidak bisa dibuka → tunggu Setup selesai / cek jendela server"
2. "Kompres lambat → FFmpeg belum terpasang"
3. "HP tidak bisa buka → cek Wi-Fi sama / jalankan .bat sebagai Admin"

**Narasi:**
> "Kalau ada masalah, tiga yang paling sering: pertama, dashboard tidak bisa
> dibuka — biasanya Setup-nya masih jalan, tunggu sampai 'Setup selesai'.
> Kedua, kompres lambat — berarti FFmpeg belum terpasang, balik ke langkah
> tadi. Ketiga, HP tidak bisa buka — cek Wi-Fi-nya sama atau belum, dan coba
> jalankan file .bat-nya sebagai Administrator sekali aja."

---

## Adegan 9 — Penutup (4:20–4:40, ±20 detik)

**Yang tampil di layar:** Dashboard KISA di HP, teks di layar: link GitHub /
Google Drive + "Dukung via Saweria — kirisaki".

**Narasi:**
> "Segitu aja cara pasang KISA. Link download ada di deskripsi, dan kalau
> proyek ini bermanfaat, dukung pengembangnya, kirisaki, lewat Saweria —
> link-nya juga ada di deskripsi dan di dalam dashboard. Sampai jumpa di
> video berikutnya!"

---

## Catatan untuk yang merekam

- Rekam layar PC dengan OBS / Xbox Game Bar (Win + G), suara dengan mikrofon
  biasa — tidak perlu alat khusus.
- Saat merekam Adegan 3, jangan dipotong: biarkan penonton melihat Setup
  jalan dari [1/7] sampai "Setup selesai" (bisa dipercepat 2× di edit).
- Sembunyikan data pribadi sebelum merekam: tutup tab browser lain, dan
  pastikan tidak ada alamat IP asli yang tampil selain contoh umum.
- Total durasi target ±4–5 menit; kalau kepanjangan, potong Adegan 8 jadi
  teks di layar saja tanpa narasi panjang.
