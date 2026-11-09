# TWA (Trusted Web Activity) — catatan penting

File di folder ini (`twa-manifest.json` untuk Bubblewrap + `assetlinks.json`
untuk Digital Asset Links) adalah jalur TWA standar — TAPI ada batasan
arsitektur yang harus dipahami sebelum dipakai:

**TWA butuh PWA yang di-host di URL HTTPS publik.** `host` di
`twa-manifest.json` harus domain sungguhan yang kamu kuasai, dan
`assetlinks.json` harus bisa diakses di `https://<domain>/.well-known/assetlinks.json`.

**KISA tidak memenuhi syarat itu:** dashboard KISA dilayani server lokal
di PC (`http://<IP-LAN>:8000`), bukan dari internet. Kalau PWA-nya di-host
publik, PWA itu tidak akan menampilkan data PC siapa pun (tidak ada server
lokal yang terhubung).

Jadi:
- **Jangan pakai TWA untuk KISA.** File-file ini disertakan sesuai rencana
  S138 supaya lengkap, tapi jalur APK yang benar untuk KISA adalah wrapper
  WebView di `app/android/` — aplikasi Android yang membuka alamat LAN
  server PC (`http://<IP-PC>:8000`) yang dimasukkan pengguna, di Wi-Fi
  yang sama. Itulah yang dibangun CI pada job Android.
- Kalau suatu hari KISA punya situs publik sendiri, ganti `host`,
  `iconUrl`, dan sidik jari SHA-256 keystore di file-file ini dengan nilai
  asli, lalu jalankan `bubblewrap build` dari folder ini.

## Yang harus diganti sebelum dipakai (bila tetap mau TWA)
- `twa-manifest.json`: `host`, `iconUrl`, `maskableIconUrl`,
  `fullScopeUrl` → domain publik asli.
- `assetlinks.json`: `sha256_cert_fingerprints` → sidik jari SHA-256
  keystore rilis yang sebenarnya (placeholder `AA:BB:...` di atas).
