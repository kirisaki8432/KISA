#!/usr/bin/env python3
"""
KISA - Agen PC untuk dipantau dari HP
=========================================================
Di PC:  python monitor_server.py  (atau Jalankan_di_PC.bat di Windows)
Di HP (satu WiFi yang sama): buka http://IP-PC:8000  di browser.
Tampilan HP: HUD dengan gauge CPU/RAM/GPU, jam, uptime, suhu,
top proses CPU, monitor, jaringan, dan disk.

Suhu di Windows:
  psutil sendiri sering tidak bisa membaca suhu CPU di Windows.
  Karena itu server ini mencoba, berurutan:
  1. psutil.sensors_temperatures() (Linux / sebagian PC)
  2. WMI ThermalZone (laptop Windows, tanpa tool tambahan)
  3. LibreHardwareMonitor / OpenHardwareMonitor yang sedang jalan
     di PC (download gratis, jalankan .exe-nya, biarkan di background)
     -> via WMI (kalau ada menu Enable WMI, aktifkan), atau
  3b. Remote Web Server LHM: Options > Remote Web Server > Start
      (port default 8085) -> server ini membaca http://127.0.0.1:8085/data.json
      Ini jalan di versi LHM yang menunya tidak punya Enable WMI.
  4. Suhu GPU NVIDIA via nvidia-smi (sudah masuk di kartu GPU).
  Kalau semua sumber kosong, dashboard akan menulis "tidak tersedia",
  itu normal, bukan error server. Lihat TUTORIAL.md bagian suhu (Langkah 5).
Hanya untuk jaringan lokal. Jangan expose port 8000 ke internet.
Butuh: psutil saja.
"""
import asyncio
import base64
import json
import hashlib
import os
import platform
import re
import socket
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    import psutil
except ImportError:
    raise SystemExit("psutil belum terinstal. Jalankan: pip install psutil")

PORT = 8000
# Patch 4.6 (S157 Cara 1): versi dashboard yang terpasang — dipakai
# /api/check_update untuk membandingkan dengan rilis GitHub terbaru.
# Naikkan tiap patch (bersamaan dengan footer dashboard).
KISA_VERSION = "4.7"
BASE_DIR = Path(__file__).resolve().parent
IS_WIN = platform.system() == "Windows"

_prev_net = None
_prev_time = None
_temp_cache = ([], 0.0)
_monitor_cache = ([], 0.0)
_disk_types_cache = ({}, 0.0)
_wifi_cache = (None, 0.0)


def _gb(n):
    return round(n / (1024 ** 3), 2)


def _local_ips():
    ips = []
    try:
        for _iface, addrs in psutil.net_if_addrs().items():
            for a in addrs:
                if a.family == socket.AF_INET and not a.address.startswith("127."):
                    if a.address not in ips:
                        ips.append(a.address)
    except Exception:
        pass
    return ips


_QR_PNG = BASE_DIR / "QR_Dashboard.png"
_QR_IP = None  # IP LAN yang dipakai QR terakhir (untuk regenerasi live di /qr.png)


def _dashboard_qr():
    """Buat QR code http://<IP-LAN>:8000 di QR_Dashboard.png, dibuat ULANG tiap
    server mulai (IP bisa berubah bila DHCP ganti). Pakai segno (pure Python,
    tanpa dependensi). Gagal (segno belum ter-install / tidak ada IP LAN) ->
    peringatan saja, server tetap jalan tanpa QR. Kembalikan URL-nya, atau None."""
    global _QR_IP
    _QR_IP = None
    try:
        ips = _local_ips()
        if not ips:
            print("QR dashboard: tidak ada IP LAN, QR tidak dibuat.")
            return None
        import segno
        url = "http://%s:%d" % (ips[0], PORT)
        qr = segno.make(url, error="m")
        modules = qr.symbol_size(border=0)[0]
        scale = max(1, round(512 / (modules + 8)))
        qr.save(str(_QR_PNG), kind="png", scale=scale, border=4,
                dark="black", light="white")
        _QR_IP = ips[0]
        return url
    except ImportError:
        print("QR dashboard: library 'segno' belum ter-install — QR tidak dibuat.")
        print("  (Jalankan Setup_Otomatis.bat lagi, atau: pip install segno)")
        return None
    except Exception as e:
        print("QR dashboard: gagal membuat QR (%s) — lanjut tanpa QR." % e)
        return None


def _ensure_firewall_rule():
    """Izinkan port 8000 di Windows Firewall untuk semua profil (Private+Public),
    supaya dashboard bisa dibuka lewat hotspot HP juga. Jaringan hotspot biasanya
    dianggap Public oleh Windows, dan aturan firewall lama sering hanya berlaku
    untuk Private, sehingga HP tidak bisa tersambung. Butuh admin; kalau gagal
    (bukan admin), kembalikan False dan server menampilkan petunjuknya."""
    if not IS_WIN:
        return False
    try:
        chk = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule",
             "name=KISA"],
            capture_output=True, timeout=10, text=True,
        )
        if chk.returncode == 0 and "KISA" in (chk.stdout or ""):
            return True
        r = subprocess.run(
            ["netsh", "advfirewall", "firewall", "add", "rule",
             "name=KISA", "dir=in", "action=allow",
             "protocol=TCP", "localport=8000", "profile=any"],
            capture_output=True, timeout=15, text=True,
        )
        return r.returncode == 0
    except Exception:
        return False


def _run_ps(cmd, timeout=4):
    """Jalankan PowerShell, kembalikan stdout atau '' kalau gagal."""
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-NonInteractive", "-STA", "-Command", cmd],
            timeout=timeout, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="ignore",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        _last_ps_err["kind"] = ""
        return out or ""
    except subprocess.TimeoutExpired:
        _last_ps_err["kind"] = "timeout"
        return ""
    except Exception:
        _last_ps_err["kind"] = "gagal"
        return ""


def _run_ps_full(cmd, timeout=4):
    """Jalankan PowerShell, kembalikan (stdout, stderr, returncode).

    Dipakai untuk GSMTC supaya pesan error PowerShell-nya bisa
    ditampilkan di /api/np_debug (gsmtc_err), bukan cuma 'gagal'.
    timeout -> rc -1, error lain -> rc -2.
    """
    try:
        p = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-STA", "-Command", cmd],
            timeout=timeout, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="ignore",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return (p.stdout or "", p.stderr or "", p.returncode)
    except subprocess.TimeoutExpired:
        return ("", "timeout", -1)
    except Exception as e:
        return ("", "gagal: " + str(e), -2)


def _run_ps_full_pwsh(cmd, timeout=15):
    """Seperti _run_ps_full tapi memakai pwsh (PowerShell 7).

    Dipakai sebagai fallback GSMTC kalau powershell 5.1 gagal
    (mis. WinRT tidak bisa diakses). pwsh tidak ada -> rc -3.
    """
    try:
        p = subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", cmd],
            timeout=timeout, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="ignore",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return (p.stdout or "", p.stderr or "", p.returncode)
    except subprocess.TimeoutExpired:
        return ("", "timeout", -1)
    except FileNotFoundError:
        return ("", "pwsh tidak ada", -3)
    except Exception as e:
        return ("", "gagal: " + str(e), -2)


def _gpu_info():
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            timeout=3, stderr=subprocess.DEVNULL, text=True,
        ).strip()
        if not out:
            return []
        gpus = []
        for line in out.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 5:
                gpus.append({
                    "name": parts[0], "util": parts[1],
                    "mem_used_mb": parts[2], "mem_total_mb": parts[3],
                    "temp_c": parts[4],
                })
        return gpus
    except Exception:
        return []


def _temps_windows():
    """Suhu Windows via WMI + Libre/OpenHardwareMonitor. Di-cache 5 detik."""
    global _temp_cache
    now = time.time()
    if now - _temp_cache[1] < 5 and _temp_cache[0]:
        return _temp_cache[0]
    out = []
    # 1. ThermalZone bawaan Windows (sering ada di laptop)
    txt = _run_ps(
        "Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature "
        "-ErrorAction SilentlyContinue | Select-Object -ExpandProperty CurrentTemperature"
    )
    for m in re.findall(r"\d+", txt):
        try:
            c = int(m) / 10.0 - 273.15
        except Exception:
            continue
        if 0 < c < 120:
            out.append({"sensor": "ThermalZone", "label": "CPU / ThermalZone", "temp_c": round(c, 1)})
            break
    # 2. LibreHardwareMonitor / OpenHardwareMonitor yang sedang jalan
    for ns in ("root/LibreHardwareMonitor", "root/OpenHardwareMonitor"):
        txt = _run_ps(
            f"Get-CimInstance -Namespace {ns} -ClassName Sensor -ErrorAction SilentlyContinue "
            f"| Where-Object {{ $_.SensorType -eq 'Temperature' }} "
            f"| ForEach-Object {{ \"$($_.Name)=$($_.Value)\" }}"
        )
        for line in txt.splitlines():
            if "=" not in line:
                continue
            name, val = line.split("=", 1)
            try:
                c = float(val.strip())
            except Exception:
                continue
            if 0 < c < 120:
                out.append({"sensor": ns.split("/")[-1], "label": name.strip(), "temp_c": round(c, 1)})
        if out:
            break
    # Deduplikasi berdasarkan label
    seen, dedup = set(), []
    for t in out:
        if t["label"] not in seen:
            seen.add(t["label"])
            dedup.append(t)
    _temp_cache = (dedup[:10], now)
    return dedup[:10]


def _walk_lhm(node, out, parent_text=""):
    """Jelajahi pohon data.json LHM/OHM secara rekursif, ambil node suhu."""
    if isinstance(node, dict):
        text = str(node.get("Text") or "")
        typ = str(node.get("Type") or "")
        val = node.get("Value")
        # Node suhu: Type-nya Temperature, atau nilainya berakhiran °C,
        # atau induknya bernama Temperatures.
        is_temp = (
            typ.lower() == "temperature"
            or parent_text.lower() == "temperatures"
            or (isinstance(val, str) and val.strip().endswith("°C"))
        )
        if is_temp and val is not None:
            m = re.search(r"-?\d+(?:[.,]\d+)?", str(val))
            if m:
                try:
                    c = float(m.group(0).replace(",", "."))
                except Exception:
                    c = None
                if c is not None and 0 < c < 120 and text:
                    out.append({"sensor": "LHM-Web", "label": text, "temp_c": round(c, 1)})
        for child in node.get("Children") or []:
            _walk_lhm(child, out, text)
    elif isinstance(node, list):
        for child in node:
            _walk_lhm(child, out, parent_text)


def _gpu_from_lhm_data(data):
    """Cari GPU AMD/Intel/NVIDIA di pohon data.json LHM, ambil load + suhu.

    Struktur: Sensor > [hardware] > [kategori: Load/Temperatures/Data] > [sensor]
    Hardware GPU namanya mengandung Radeon / GeForce / Arc / Graphics.
    """
    gpus = []

    def walk(node, hw_name=""):
        if isinstance(node, dict):
            text = str(node.get("Text") or "")
            children = node.get("Children") or []
            # Node hardware adalah anak langsung dari root Sensor (kedalaman 2)
            # Kita kenali dari namanya, lalu cari kategori di bawahnya.
            low = text.lower()
            is_gpu_hw = any(k in low for k in ("radeon", "geforce", "arc ", "graphics", "rtx ", "gtx "))
            if is_gpu_hw and children:
                util = temp = None
                mem_used = mem_total = None
                for cat in children:
                    if not isinstance(cat, dict):
                        continue
                    cat_text = str(cat.get("Text") or "")
                    for s in cat.get("Children") or []:
                        if not isinstance(s, dict):
                            continue
                        s_text = str(s.get("Text") or "")
                        val = str(s.get("Value") or "")
                        m = re.search(r"-?\d+(?:[.,]\d+)?", val)
                        if not m:
                            continue
                        try:
                            num = float(m.group(0).replace(",", "."))
                        except Exception:
                            continue
                        if cat_text.lower() == "load" and s_text.lower() in ("gpu core", "gpu"):
                            util = num
                        elif cat_text.lower() == "temperatures" and s_text.lower() in ("gpu core", "gpu"):
                            temp = num
                        elif "memory used" in s_text.lower():
                            mem_used = num
                        elif "memory total" in s_text.lower() or "memory" == s_text.lower():
                            mem_total = num
                gpus.append({
                    "name": text, "util": str(util) if util is not None else "0",
                    "mem_used_mb": str(mem_used) if mem_used is not None else None,
                    "mem_total_mb": str(mem_total) if mem_total is not None else None,
                    "temp_c": str(temp) if temp is not None else None,
                })
            for child in children:
                walk(child, text)
        elif isinstance(node, list):
            for child in node:
                walk(child, hw_name)

    walk(data)
    return gpus


_lhm_status = "unknown"
_lhm_host = ""


def _lhm_hosts():
    """Daftar host untuk mencoba LHM: localhost dulu, lalu IP LAN PC.

    Penting: LHM bisa dibuka lewat IP LAN PC (misalnya 192.168.1.10:8085),
    bukan localhost. Kalau Interface di LHM diset ke IP LAN saja,
    localhost:8085 tidak akan merespons, padahal halaman web-nya jalan.
    Karena itu server ini harus mencoba keduanya.
    """
    hosts = ["127.0.0.1"]
    try:
        for iface, addrs in psutil.net_if_addrs().items():
            for a in addrs:
                ip = getattr(a, "address", "")
                if ip and not ip.startswith("127.") and "." in ip and ip not in hosts:
                    hosts.append(ip)
    except Exception:
        pass
    try:
        hn = socket.gethostbyname(socket.gethostname())
        if hn and hn not in hosts and not hn.startswith("127."):
            hosts.append(hn)
    except Exception:
        pass
    return hosts


_lhm_fetch_cache = (None, "", "", 0.0)


def _lhm_fetch():
    """Ambil data.json LHM, di-cache 1 detik (perc153).

    Tanpa cache, collect() memanggil ini sampai 3x tiap tick
    (GPU, suhu, fan) — 3x HTTP + 3x parse JSON data.json per 0,5 detik.
    Cache 1 detik: paling banyak 1x HTTP per detik; saat LHM mati pun
    percobaan koneksi yang gagal ikut di-cache 1 detik.
    """
    global _lhm_status, _lhm_host, _lhm_fetch_cache
    now = time.time()
    if now - _lhm_fetch_cache[3] < 1.0:
        _lhm_status = _lhm_fetch_cache[1]
        _lhm_host = _lhm_fetch_cache[2]
        return _lhm_fetch_cache[0], _lhm_fetch_cache[1]
    data, status = _lhm_fetch_uncached()
    _lhm_fetch_cache = (data, status, _lhm_host, time.time())
    return data, status


def _lhm_fetch_uncached():
    """Ambil data.json LHM, kembalikan (data, status).

    Status: ok / auth (401, Authentication aktif di LHM) /
    not_running (web server tidak jalan / port salah) / error.
    Status disimpan global supaya dashboard bisa menampilkan penyebabnya,
    bukan cuma 'tidak tersedia' yang membingungkan.
    """
    global _lhm_status, _lhm_host
    for host in _lhm_hosts():
        try:
            with urllib.request.urlopen(f"http://{host}:8085/data.json", timeout=2) as r:
                data = json.loads(r.read().decode("utf-8", errors="ignore"))
            _lhm_status = "ok"
            _lhm_host = host
            return data, "ok"
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                _lhm_status = "auth"
                _lhm_host = host
                print("LHM web server minta login (HTTP %s). Matikan Authentication di LHM: Options > Remote Web Server > Authentication (hilangkan centang)." % e.code, flush=True)
                return None, "auth"
            continue
        except Exception:
            continue
    _lhm_status = "not_running"
    return None, "not_running"


def _gpu_from_lhm_web():
    data, _ = _lhm_fetch()
    if data is None:
        return []
    return _gpu_from_lhm_data(data)


def _temps_lhm_web():
    """Suhu via Remote Web Server LHM/OHM di http://localhost:8085/data.json.

    Di LHM: Options > Remote Web Server > aktifkan / Start, port default 8085.
    Ini jalan di versi LHM yang menunya tidak punya Enable WMI.
    Perhatian: kalau Authentication di LHM aktif, data.json minta login
    dan server ini (tanpa username/password) tidak bisa membacanya.
    """
    data, _ = _lhm_fetch()
    if data is None:
        return []
    out = []
    _walk_lhm(data, out)
    seen, dedup = set(), []
    for t in out:
        if t["label"] not in seen:
            seen.add(t["label"])
            dedup.append(t)
    return dedup[:10]


def _walk_lhm_fans_mobo(node, out_fans, out_mobo_temps, hw="", cat=""):
    """Jelajahi data.json LHM, ambil fan (RPM) dan suhu motherboard.

    Struktur LHM: Sensor > [hardware: ASRock B550M, Ryzen, Radeon, ...]
    > [kategori: Temperatures/Fans/Controls/...] > [sensor].
    Hardware motherboard dikenali sebagai hardware yang BUKAN CPU
    (Ryzen/Intel) dan BUKAN GPU (Radeon/GeForce) dan BUKAN storage/RAM,
    tapi punya kategori Temperatures — pada PC user itu ASRock B550M Pro SE.
    Fan CPU/GPU/casing semuanya ada di kategori Fans di bawah hardware
    masing-masing, jadi nama hardware-nya ikut ditampilkan supaya jelas
    mana fan CPU, mana fan GPU, mana fan casing.
    """
    if isinstance(node, dict):
        text = str(node.get("Text") or "")
        val = node.get("Value")
        children = node.get("Children") or []
        new_hw, new_cat = hw, cat
        if cat == "" and hw == "" and text and text.lower() != "sensor":
            # Anak langsung dari root Sensor = hardware
            new_hw = text
        elif text.lower() in ("fans", "temperatures", "controls", "load", "data", "voltages", "clocks", "powers"):
            new_cat = text
        if new_cat.lower() == "fans" and val is not None:
            m = re.search(r"-?\d+(?:[.,]\d+)?", str(val))
            if m and text:
                try:
                    rpm = float(m.group(0).replace(",", "."))
                except Exception:
                    rpm = None
                if rpm is not None and 0 <= rpm < 20000:
                    out_fans.append({"name": text, "hardware": new_hw, "rpm": round(rpm)})
        if new_cat.lower() == "temperatures" and val is not None and new_hw:
            low = new_hw.lower()
            is_cpu = any(k in low for k in ("ryzen", "intel", "core i", "pentium", "celeron"))
            is_gpu = any(k in low for k in ("radeon", "geforce", "arc ", "graphics", "rtx ", "gtx "))
            is_storage = any(k in low for k in ("harddisk", "ssd", "nvme", "samsung", "wd ", "seagate", "kingston"))
            if not is_cpu and not is_gpu and not is_storage and text:
                m = re.search(r"-?\d+(?:[.,]\d+)?", str(val))
                if m:
                    try:
                        c = float(m.group(0).replace(",", "."))
                    except Exception:
                        c = None
                    if c is not None and 0 < c < 120:
                        out_mobo_temps.append({"label": text, "temp_c": round(c, 1), "hardware": new_hw})
        for child in children:
            _walk_lhm_fans_mobo(child, out_fans, out_mobo_temps, new_hw, new_cat)
    elif isinstance(node, list):
        for child in node:
            _walk_lhm_fans_mobo(child, out_fans, out_mobo_temps, hw, cat)


def _fans_mobo_lhm():
    """Kembalikan (fans, mobo_name, mobo_temps) dari LHM web, atau kosong."""
    if not IS_WIN:
        return [], None, []
    data, _ = _lhm_fetch()
    if data is None:
        return [], None, []
    fans, mobo_temps = [], []
    _walk_lhm_fans_mobo(data, fans, mobo_temps)
    # Deduplikasi fan berdasarkan hardware+nama, suhu mobo berdasarkan label
    seen, fans_dedup = set(), []
    for f in fans:
        k = (f["hardware"], f["name"])
        if k not in seen:
            seen.add(k)
            fans_dedup.append(f)
    seen, mobo_dedup = set(), []
    mobo_name = None
    for t in mobo_temps:
        if t["label"] not in seen:
            seen.add(t["label"])
            mobo_dedup.append(t)
            mobo_name = t["hardware"]
    return fans_dedup, mobo_name, mobo_dedup


def _fans_windows_fallback():
    """Fan via WMI LHM/OHM kalau web server tidak jalan."""
    if not IS_WIN:
        return []
    out = []
    for ns in ("root/LibreHardwareMonitor", "root/OpenHardwareMonitor"):
        txt = _run_ps(
            f"Get-CimInstance -Namespace {ns} -ClassName Sensor -ErrorAction SilentlyContinue "
            f"| Where-Object {{ $_.SensorType -eq 'Fan' }} "
            f"| ForEach-Object {{ \\\"$($_.Name)=$($_.Value)\\\" }}\""
        )
        for line in txt.splitlines():
            if "=" not in line:
                continue
            name, val = line.split("=", 1)
            try:
                rpm = float(val.strip())
            except Exception:
                continue
            if 0 <= rpm < 20000:
                out.append({"name": name.strip(), "hardware": "", "rpm": round(rpm)})
        if out:
            break
    return out


def _fans_mobo():
    fans, mobo_name, mobo_temps = _fans_mobo_lhm()
    if not fans:
        fans = _fans_windows_fallback()
    return {"fans": fans, "mobo_name": mobo_name, "mobo_temps": mobo_temps}


def _temps():
    out = []
    try:
        temps = psutil.sensors_temperatures()
    except Exception:
        temps = {}
    for name, entries in (temps or {}).items():
        for e in entries:
            if e.current is not None:
                out.append({"sensor": name, "label": e.label or name, "temp_c": round(e.current, 1)})
    if IS_WIN:
        for t in _temps_windows():
            if t["label"] not in [x["label"] for x in out]:
                out.append(t)
        # Fallback: kalau WMI masih kosong, coba web server LHM
        if not out:
            for t in _temps_lhm_web():
                if t["label"] not in [x["label"] for x in out]:
                    out.append(t)
    return out[:12]


_cpu_model_cache = ("", 0.0)


def _cpu_model():
    """Nama CPU otomatis, sesuai CPU yang dipakai PC itu.

    Urutan: Windows Win32_Processor -> LHM web server (hardware CPU)
    -> /proc/cpuinfo (Linux) -> platform.processor().
    Di-cache 60 detik karena nama CPU tidak berubah-ubah.
    """
    global _cpu_model_cache
    now = time.time()
    if now - _cpu_model_cache[1] < 60 and _cpu_model_cache[0]:
        return _cpu_model_cache[0]
    name = ""
    if IS_WIN:
        txt = _run_ps(
            "Get-CimInstance Win32_Processor -ErrorAction SilentlyContinue "
            "| Select-Object -First 1 -ExpandProperty Name"
        ).strip()
        if txt:
            name = txt.splitlines()[0].strip()
    if not name:
        # Dari LHM web server: hardware yang namanya mengandung Ryzen/Core/Xeon/dll, bukan GPU/RAM/motherboard
        try:
            with urllib.request.urlopen("http://127.0.0.1:8085/data.json", timeout=2) as r:
                data = json.loads(r.read().decode("utf-8", errors="ignore"))
            for hw in (data.get("Children") or []):
                t = str(hw.get("Text") or "")
                low = t.lower()
                if any(k in low for k in ("ryzen", "intel", "core ", "xeon", "epyc", "pentium", "celeron")) and "radeon" not in low and "geforce" not in low:
                    name = t
                    break
        except Exception:
            pass
    if not name:
        try:
            with open("/proc/cpuinfo", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.startswith("model name"):
                        name = line.split(":", 1)[1].strip()
                        break
        except Exception:
            pass
    if not name:
        name = platform.processor() or "CPU"
    _cpu_model_cache = (name, now)
    return name


def _top_processes():
    out = []
    try:
        for p in psutil.process_iter(["name", "cpu_percent"]):
            try:
                c = p.info.get("cpu_percent") or 0
            except Exception:
                continue
            if c > 0:
                out.append({"name": p.info.get("name") or "?", "cpu": round(c, 1)})
    except Exception:
        return []
    out.sort(key=lambda x: x["cpu"], reverse=True)
    return out[:6]



_MONITOR_BRANDS = {
    "SAM": "Samsung", "SEC": "Samsung",
    "LGD": "LG", "GSM": "LG", "LGE": "LG",
    "ACI": "ASUS", "ASU": "ASUS",
    "DEL": "Dell", "DPC": "Dell",
    "AOC": "AOC", "HWP": "HP", "HPN": "HP",
    "LEN": "Lenovo", "MSI": "MSI", "BNQ": "BenQ", "HWV": "Huawei",
    "VSC": "ViewSonic", "PHL": "Philips",
    "AUO": "AU Optronics", "CMO": "Innolux",
    "IVM": "Iiyama", "EIZ": "EIZO", "NEC": "NEC",
    "APP": "Apple", "ACR": "Acer", "HSD": "Hanns-G",
    "GIG": "Gigabyte", "SKY": "Skyworth", "TCL": "TCL",
    "XIA": "Xiaomi", "HIS": "Hisense", "KTC": "KTC",
    "HKC": "HKC", "SHP": "Sharp", "TOS": "Toshiba",
    "SON": "Sony", "PAN": "Panasonic",
}


def _parse_monitor_brands(txt):
    """Parse baris WmiMonitorID 'Instance|Manufacturer|Friendly|Serial'.

    ManufacturerName di EDID hanya kode 3 huruf (mis. SAM), jadi
    dipetakan ke nama merek. Kalau Friendly sudah diawali merek,
    dipakai apa adanya, kalau tidak digabung 'Merek Model'.
    """
    brands = []
    for line in (txt or "").splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            continue
        code = parts[1].upper()
        model = parts[2].strip()
        brand = _MONITOR_BRANDS.get(code, code if code else "")
        if model and brand and model.lower().startswith(brand.lower()):
            display = model
        elif brand and model:
            display = f"{brand} {model}"
        else:
            display = brand or model
        brands.append({"brand": brand, "model": model, "display": display})
    return brands


def _monitor_brands():
    """Deteksi merek+model monitor dari EDID via WmiMonitorID (Windows).

    WmiMonitorID membaca EDID monitor yang terhubung, jadi mereknya
    adalah merek asli monitor, bukan tebakan dari resolusi. Urutan
    hasilnya dipakai untuk dipasangkan dengan daftar DISPLAY1..10
    (untuk 1 monitor, pasangannya selalu tepat). Kalau WMI kosong,
    fallback ke Win32_DesktopMonitor; kalau itu pun kosong, daftar
    kembali ke 'Monitor N' seperti sebelumnya.
    """
    if not IS_WIN:
        return []
    ps = r"""
Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorID -ErrorAction SilentlyContinue | ForEach-Object {
  $man = (($_.ManufacturerName | ForEach-Object {[char]$_}) -join '').Trim([char]0).Trim()
  $fr = (($_.UserFriendlyName | ForEach-Object {[char]$_}) -join '').Trim([char]0).Trim()
  $ser = (($_.SerialNumberID | ForEach-Object {[char]$_}) -join '').Trim([char]0).Trim()
  "$($_.InstanceName)|$man|$fr|$ser"
}
"""
    brands = _parse_monitor_brands(_run_ps(ps))
    if any(b["display"] for b in brands):
        return brands
    txt = _run_ps(
        "Get-CimInstance Win32_DesktopMonitor -ErrorAction SilentlyContinue | "
        "ForEach-Object { \"$($_.Name)|$($_.MonitorManufacturer)\" }"
    )
    out = []
    for line in txt.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 2 and parts[1]:
            out.append({"brand": parts[1], "model": "", "display": parts[1]})
        else:
            out.append({"brand": "", "model": "", "display": ""})
    return out


_PORT_NAMES = {1: "VGA", 5: "DVI", 6: "HDMI", 10: "DisplayPort", 18: "USB-C"}


def _port_name(tech):
    """Map VideoOutputTechnology (WMI / DisplayConfig) ke label port fisik.

    Hanya port eksternal yang ditampilkan; layar internal laptop,
    wireless (Miracast), OTHER, dan nilai tak dikenal -> "" (tidak
    ditampilkan, bukan ditebak).
    """
    try:
        return _PORT_NAMES.get(int(tech), "")
    except (TypeError, ValueError):
        return ""


def _monitor_ports():
    """Port koneksi tiap monitor dari WMI WmiMonitorConnectionParams.

    Namespace root/wmi yang sama dengan WmiMonitorID (sudah terbukti
    untuk merek monitor). Urutan dipakai untuk dipasangkan dengan
    daftar monitor, sama seperti pasangan merek; untuk 1 monitor
    pasangannya selalu tepat. Di luar Windows -> [].
    """
    if not IS_WIN:
        return []
    txt = _run_ps(
        "Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorConnectionParams "
        "-ErrorAction SilentlyContinue | ForEach-Object { \"$($_.VideoOutputTechnology)\" }"
    )
    return [_port_name(line.strip()) for line in txt.splitlines() if line.strip()]


def _monitors():
    """Scan monitor maks. 4, Windows saja. Di-cache 60 detik.

    Cara lama (Win32_VideoController) hanya mengembalikan 1 baris per GPU,
    jadi monitor ke-2/3/4 yang menempel di GPU yang sama tidak pernah
    muncul. Karena itu sekarang dipakai, berurutan:
    1. EnumDisplaySettings per DISPLAY1..DISPLAY10 (user32) -> resolusi
       DAN refresh rate per monitor yang sebenarnya, bukan per GPU.
    2. Fallback: [System.Windows.Forms.Screen]::AllScreens -> jumlah dan
       resolusi tiap layar, refresh rate diambil dari VideoController.
    3. Fallback terakhir: Win32_VideoController (1 monitor per GPU).
    Nama GPU diambil dari VideoController pertama dan dipakai untuk
    semua monitor, karena semua monitor itu biasanya di GPU yang sama.
    """
    global _monitor_cache
    now = time.time()
    if now - _monitor_cache[1] < 60 and _monitor_cache[0]:
        return _monitor_cache[0]
    out = []
    if IS_WIN:
        gpu_name = ""
        txt_gpu = _run_ps(
            "Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue | "
            "Select-Object -First 1 -ExpandProperty Name"
        ).strip()
        if txt_gpu:
            gpu_name = txt_gpu.splitlines()[0].strip()
        # 1. EnumDisplaySettings
        ps_enum = r"""
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class Disp {
  [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Ansi)]
  public struct DEVMODE {
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst=32)] public string dmDeviceName;
    public short dmSpecVersion; public short dmDriverVersion; public short dmSize; public short dmDriverExtra; public int dmFields;
    public int dmPositionX; public int dmPositionY; public int dmDisplayOrientation; public int dmDisplayFixedOutput;
    public short dmColor; public short dmDuplex; public short dmYResolution; public short dmTTOption; public short dmCollate;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst=32)] public string dmFormName;
    public short dmLogPixels; public int dmBitsPerPel; public int dmPelsWidth; public int dmPelsHeight;
    public int dmDisplayFlags; public int dmDisplayFrequency; public int dmICMMethod; public int dmICMIntent;
    public int dmMediaType; public int dmDitherType; public int dmReserved1; public int dmReserved2; public int dmPanningWidth; public int dmPanningHeight;
  }
  [DllImport("user32.dll")] public static extern bool EnumDisplaySettings(string lpszDeviceName, int iModeNum, ref DEVMODE lpDevMode);
}
'@;
for ($i=1; $i -le 10; $i++) { $dm = New-Object Disp+DEVMODE; $dm.dmSize = [System.Runtime.InteropServices.Marshal]::SizeOf($dm); if ([Disp]::EnumDisplaySettings("\\\\.\\DISPLAY$i", -1, [ref]$dm)) { if ($dm.dmPelsWidth -gt 0) { "$i|$($dm.dmPelsWidth)|$($dm.dmPelsHeight)|$($dm.dmDisplayFrequency)" } } }
"""
        for line in _run_ps(ps_enum).splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 4 and parts[1].isdigit() and parts[2].isdigit():
                hz = parts[3] if parts[3].isdigit() and int(parts[3]) > 0 else ""
                out.append({
                    "name": f"Monitor {parts[0]}", "gpu": gpu_name,
                    "res": f"{parts[1]}x{parts[2]}", "hz": hz,
                })
        # 2. Fallback AllScreens
        if not out:
            txt_screens = _run_ps(
                "[System.Windows.Forms.Screen]::AllScreens | "
                "ForEach-Object { \"$($_.DeviceName)|$($_.Bounds.Width)|"
                "$($_.Bounds.Height)|$($_.Primary)\" }"
            )
            hz_fallback = ""
            txt_vc = _run_ps(
                "Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue | "
                "Select-Object -First 1 -ExpandProperty CurrentRefreshRate"
            ).strip()
            if txt_vc and txt_vc.splitlines()[0].strip().isdigit():
                hz_fallback = txt_vc.splitlines()[0].strip()
            for line in txt_screens.splitlines():
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 3 and parts[1].isdigit():
                    num = "".join(ch for ch in parts[0] if ch.isdigit()) or str(len(out) + 1)
                    primary = len(parts) >= 4 and parts[3].lower() == "true"
                    out.append({
                        "name": f"Monitor {num}" + (" (Utama)" if primary else ""),
                        "gpu": gpu_name,
                        "res": f"{parts[1]}x{parts[2]}", "hz": hz_fallback,
                    })
        # 3. Fallback VideoController
        if not out:
            txt = _run_ps(
                "Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue | "
                "ForEach-Object { \"$($_.Name)|$($_.CurrentHorizontalResolution)|"
                "$($_.CurrentVerticalResolution)|$($_.CurrentRefreshRate)\" }"
            )
            for i, line in enumerate([l for l in txt.splitlines() if "|" in l], 1):
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 4 and parts[1].isdigit():
                    out.append({
                        "name": f"Monitor {i}", "gpu": parts[0],
                        "res": f"{parts[1]}x{parts[2]}", "hz": parts[3],
                    })
    # Batas maks. 4 monitor (permintaan user 2026-11-03): apa pun yang
    # terdeteksi lebih dari itu (mis. layar virtual) tidak ditampilkan
    # dan tidak dihitung ke daya monitor.
    out = out[:4]
    if out:
        brands = _monitor_brands()
        ports = _monitor_ports()
        for i, mon in enumerate(out):
            if i < len(brands) and brands[i].get("display"):
                mon["name"] = brands[i]["display"]
                mon["brand"] = brands[i].get("brand", "")
                mon["model"] = brands[i].get("model", "")
            else:
                mon["brand"] = ""
                mon["model"] = ""
            mon["port"] = ports[i] if i < len(ports) else ""
    _monitor_cache = (out, now)
    return out


_app_icon_cache = {"exe": "", "png": None}
_active_app_cache = {"data": None, "time": 0.0}
_recent_apps = []
_recent_app_paths = {}


def _active_app():
    """Aplikasi yang sedang dipakai (foreground window), Windows saja.

    Pakai user32 GetForegroundWindow + GetWindowThreadProcessId via ctypes
    (cepat, tidak perlu PowerShell tiap tick). Di-cache 1 detik supaya
    tick 2 detik tidak membebani. Kembalikan None kalau tidak ada jendela
    aktif / bukan Windows (misal di Linux, atau hanya desktop).
    """
    if not IS_WIN:
        return None
    now = time.time()
    if now - _active_app_cache["time"] < 1 and _active_app_cache["data"] is not None:
        return _active_app_cache["data"]
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return None
        proc = psutil.Process(pid.value)
        exe = proc.exe() or ""
        name = proc.name() or ""
        if not name and not title:
            return None
        data = {
            "name": name,
            "title": title,
            "exe": exe.rsplit("\\", 1)[-1] if exe else name,
            "exe_path": exe,
            "pid": pid.value,
        }
        _active_app_cache["data"] = data
        _active_app_cache["time"] = now
        return data
    except Exception:
        return None


def _app_icon_png(exe_path=None):
    """PNG ikon aplikasi, di-cache per exe.

    Kalau exe_path tidak diberikan, pakai aplikasi aktif saat ini.
    Kalau diberikan (dari daftar recent_apps), pakai exe itu.
    Ekstraksi ikon dilakukan HANYA saat exe berganti, lewat
    PowerShell [System.Drawing.Icon]::ExtractAssociatedIcon(exe) yang
    disimpan sementara sebagai PNG lalu dibaca ke memori. Kalau gagal
    (exe tanpa ikon, PowerShell gagal, dll), kembalikan None dan
    dashboard akan menampilkan nama saja tanpa ikon.
    """
    if exe_path is None:
        app = _active_app()
        if not app or not app.get("exe_path"):
            return None
        exe = app["exe_path"]
    else:
        exe = exe_path
    if _app_icon_cache["exe"] == exe and _app_icon_cache["png"]:
        return _app_icon_cache["png"]
    try:
        import tempfile, os
        tmp = os.path.join(tempfile.gettempdir(), "pcmon_app_icon.png")
        exe_ps = exe.replace("'", "''")
        ps = (
            "Add-Type -AssemblyName System.Drawing; "
            "Add-Type @\"\n"
            "using System; using System.Drawing; using System.Runtime.InteropServices;\n"
            "public static class IconBig {\n"
            " [DllImport(\"user32.dll\", CharSet = CharSet.Auto)]\n"
            " public static extern uint PrivateExtractIcons(string f, int i, int cx, int cy, IntPtr[] h, uint[] id, uint n, uint fl);\n"
            " [DllImport(\"user32.dll\")] public static extern bool DestroyIcon(IntPtr h);\n"
            "}\n"
            "\"@; "
            f"$tmp='{tmp}'; $exe='{exe_ps}'; $ok=$false; "
            "try { $h=New-Object IntPtr[] 1; $id=New-Object uint[] 1; "
            "$n=[IconBig]::PrivateExtractIcons($exe,0,256,256,$h,$id,1,0); "
            "if ($n -gt 0 -and $h[0] -ne [IntPtr]::Zero) { "
            "$ico=[System.Drawing.Icon]::FromHandle($h[0]); $bm=$ico.ToBitmap(); "
            "$bm.Save($tmp,[System.Drawing.Imaging.ImageFormat]::Png); "
            "$ico.Dispose(); $bm.Dispose(); [IconBig]::DestroyIcon($h[0]) | Out-Null; $ok=$true } } catch { } "
            "if (-not $ok) { $icon=[System.Drawing.Icon]::ExtractAssociatedIcon($exe); "
            f"if ($icon) {{ $icon.ToBitmap().Save('{tmp}', [System.Drawing.Imaging.ImageFormat]::Png) }} }}"
        )
        _run_ps(ps)
        with open(tmp, "rb") as f:
            png = f.read()
        if png[:8] == b"\x89PNG\r\n\x1a\n":
            _app_icon_cache["exe"] = exe
            _app_icon_cache["png"] = png
            return png
    except Exception:
        pass
    return None


_now_playing_cache = (None, 0.0)
_gsmtc_cache = (None, 0.0)
_fallback_cache = (None, 0.0)
_cover_cache = {"id": "", "data": None, "ctype": "image/jpeg", "tried_key": "", "tried_at": 0.0}


def _parse_media_window(proc_name, title):
    """Ubah judul jendela pemutar jadi info lagu, atau None.

    Fungsi murni (tidak butuh Windows) supaya bisa dites di mana saja.
    Ini jalur otomatis untuk file lokal: pemutar lokal biasanya
    menampilkan 'Artis - Judul' di judul jendelanya, walau tidak
    mendaftar ke GSMTC. Daftar pemutar sengaja dibuat luas, bukan
    cuma satu aplikasi, supaya deteksinya otomatis apa pun pemutar
    yang sedang dipakai saat itu.
    """
    if not proc_name or not title:
        return None
    name = proc_name.lower()
    title = title.strip()
    if name == "spotify.exe":
        if title in ("Spotify", "Spotify Free", "Spotify Premium"):
            return None
        player = "Spotify"
    elif name == "vlc.exe":
        if not title.endswith(" - VLC media player"):
            return None
        title = title[: -len(" - VLC media player")].strip()
        player = "VLC"
    elif name in ("nocturne.exe", "nocturne music.exe", "nocturne-music.exe", "nocturne-app.exe"):
        # Klien YouTube Music: judul jendela mengikuti judul halaman YT Music,
        # "<Judul Lagu> - <Artis> - YouTube Music" (atau tanpa suffix itu).
        # Berbeda dengan foobar2000 ("Artis - Judul"), di sini judul dulu.
        player = "Nocturne Music"
        for suffix in (" - YouTube Music", " | YouTube Music"):
            if suffix in title:
                title = title.split(suffix)[0].strip()
                break
        if (not title or title.lower() in ("nocturne", "nocturne music", "youtube music")
                or title.lower().startswith("com.nocturne.music")):
            return None
        if " \u2022 " in title:
            song, artist = title.split(" \u2022 ", 1)
        elif " - " in title:
            song, artist = title.rsplit(" - ", 1)
        else:
            song, artist = title, ""
        if not song.strip():
            return None
        return {"title": song.strip(), "artist": artist.strip(), "album": "",
                "player": player, "status": "Aktif"}
    elif name in ("foobar2000.exe", "musicbee.exe", "aimp.exe", "aimp64.exe",
                  "winamp.exe", "itunes.exe", "mediamonkey.exe", "clementine.exe",
                  "strawberry.exe", "jriver mediacenter.exe", "dopamine.exe",
                  "wmplayer.exe"):
        player = {"foobar2000.exe": "foobar2000", "musicbee.exe": "MusicBee",
                  "aimp.exe": "AIMP", "aimp64.exe": "AIMP", "winamp.exe": "Winamp",
                  "itunes.exe": "iTunes", "mediamonkey.exe": "MediaMonkey",
                  "clementine.exe": "Clementine", "strawberry.exe": "Strawberry",
                  "jriver mediacenter.exe": "JRiver Media Center",
                  "dopamine.exe": "Dopamine",
                  "wmplayer.exe": "Windows Media Player"}.get(name, name)
        if name == "wmplayer.exe" and title.endswith(" - Windows Media Player"):
            title = title[: -len(" - Windows Media Player")].strip()
        # Judul UI (bukan lagu), mis. Mini player Gatefold: "Gatefold · Mini player".
        # Titik tengahnya bisa U+00B7 (·) atau U+2022 (•); samakan dulu.
        t_guard = re.sub(r"\s+", " ", title.lower().replace("·", " ").replace("•", " ")).strip()
        if t_guard in ("foobar2000", "musicbee", "aimp", "winamp", "itunes",
                       "mediamonkey", "clementine", "strawberry",
                       "jriver media center", "dopamine",
                       "windows media player", "gatefold",
                       "gatefold mini player", "mini player"):
            return None
    elif name in ("mediaplayer.exe", "music.ui.exe", "potplayermini64.exe",
                  "potplayermini.exe", "potplayer.exe", "kmplayer64.exe",
                  "kmplayer.exe", "mpc-hc64.exe", "mpc-hc.exe", "mpc-be64.exe",
                  "mpc-be.exe", "gom.exe", "youtube music.exe",
                  "youtube-music.exe", "yt music.exe", "youtubemusic.exe"):
        player = {"mediaplayer.exe": "Media Player", "music.ui.exe": "Groove Music",
                  "potplayermini64.exe": "PotPlayer", "potplayermini.exe": "PotPlayer",
                  "potplayer.exe": "PotPlayer", "kmplayer64.exe": "KMPlayer",
                  "kmplayer.exe": "KMPlayer", "mpc-hc64.exe": "MPC-HC",
                  "mpc-hc.exe": "MPC-HC", "mpc-be64.exe": "MPC-BE",
                  "mpc-be.exe": "MPC-BE", "gom.exe": "GOM Player",
                  "youtube music.exe": "YouTube Music", "youtube-music.exe": "YouTube Music",
                  "yt music.exe": "YouTube Music", "youtubemusic.exe": "YouTube Music"}.get(name, name)
        for suffix in (" - PotPlayerMini64", " - PotPlayer", " - KMPlayer",
                       " - MPC-HC", " - MPC-BE", " - GOM Player", " - Media Player",
                       " - Groove Music", " - YouTube Music", " - YT Music"):
            if title.endswith(suffix):
                title = title[: -len(suffix)].strip()
                break
        if not title or title.lower() in ("potplayer", "potplayermini64", "kmplayer",
                                          "mpc-hc", "mpc-be", "gom player", "media player",
                                          "groove music", "youtube music", "yt music"):
            return None
        if name in ("youtube music.exe", "youtube-music.exe", "yt music.exe", "youtubemusic.exe"):
            if " \u2022 " in title:
                song, artist = title.split(" \u2022 ", 1)
            elif " - " in title:
                song, artist = title.rsplit(" - ", 1)
            else:
                song, artist = title, ""
            if not song.strip():
                return None
            return {"title": song.strip(), "artist": artist.strip(), "album": "",
                    "player": player, "status": "Aktif"}
    elif name in ("brave.exe", "chrome.exe", "msedge.exe", "firefox.exe"):
        # Judul jendela browser selalu diakhiri nama browsernya, misal:
        #   "Judul Lagu - Artis - YouTube Music - Brave"
        #   "YouTube Music - Brave"  (halaman utama, belum ada lagu)
        # Kalau suffix browser tidak dibuang dulu, parser lama salah
        # membaca "Brave" sebagai judul lagu dan "YouTube Music"
        # sebagai artisnya. Jadi buang suffix browser dulu, baru
        # ambil judul lagu dari sebelum " - YouTube Music".
        for suffix in (" - Brave", " - Google Chrome", " - Microsoft Edge",
                       " - Mozilla Firefox", " - Firefox", " - Opera", " - Vivaldi"):
            if title.endswith(suffix):
                title = title[: -len(suffix)].strip()
                break
        if "YouTube Music" in title:
            # " - YouTube Music" atau " | YouTube Music" (tergantung tab)
            for sep in (" - YouTube Music", " | YouTube Music"):
                if sep in title:
                    title = title.split(sep)[0].strip()
                    break
            if not title or title.lower() == "youtube music":
                # Hanya halaman utama YouTube Music yang terbuka, belum
                # ada lagu yang diputar. Jangan tampilkan sebagai lagu.
                return None
            player = "YouTube Music (Browser)"
            if " • " in title:
                song, artist = title.split(" • ", 1)
            elif " - " in title:
                # "Judul Lagu - Artis": artis adalah setelah dash terakhir,
                # karena judul lagu sendiri bisa mengandung dash.
                song, artist = title.rsplit(" - ", 1)
            else:
                song, artist = title, ""
            return {"title": song.strip(), "artist": artist.strip(), "album": "",
                    "player": player, "status": "Aktif"}
        # YouTube biasa: judul tab "<Judul Video> - YouTube" (atau
        # " | YouTube"). Halaman utama "YouTube" saja bukan video.
        for sep in (" - YouTube", " | YouTube"):
            if title.endswith(sep):
                video = title[: -len(sep)].strip()
                if not video or video.lower() == "youtube":
                    return None
                return {"title": video, "artist": "", "album": "",
                        "player": "YouTube (Browser)", "status": "Aktif"}
        return None
    else:
        return None
    if not title:
        return None
    for sep in (" — ", " – ", " - "):
        if sep in title:
            artist, song = title.split(sep, 1)
            break
    else:
        artist, song = "", title
    return {"title": song.strip(), "artist": artist.strip(), "album": "",
            "player": player, "status": "Aktif"}


def _media_from_windows():
    """Fallback otomatis: lagu dari judul jendela pemutar yang sedang jalan.

    Membaca semua proses yang punya judul jendela lewat PowerShell,
    lalu mencoba _parse_media_window untuk masing-masing. Urutan
    prioritas: pemutar lokal dulu, baru browser, supaya kalau Spotify
    dan browser sama-sama terbuka, yang tampil adalah pemutar lokalnya.
    """
    if not IS_WIN:
        return None
    try:
        txt = _run_ps(
            "Get-Process | Where-Object { $_.MainWindowTitle } "
            "| ForEach-Object { \"$($_.ProcessName)|$($_.MainWindowTitle)\" }",
            timeout=4,
        )
        candidates = []
        _np_debug["windows"] = []
        for line in txt.splitlines():
            if "|" not in line:
                continue
            proc, win_title = line.split("|", 1)
            if len(_np_debug["windows"]) < 30:
                _np_debug["windows"].append({"proc": proc.strip(), "title": win_title.strip()})
            parsed = _parse_media_window(proc.strip() + ".exe", win_title.strip())
            if parsed:
                candidates.append((proc.strip().lower(), parsed))
        if not candidates:
            return None
        browsers = ("brave", "chrome", "msedge", "firefox")
        for proc, parsed in candidates:
            if proc not in browsers:
                return parsed
        return candidates[0][1]
    except Exception:
        return None


def _fetch_yt_cover(title):
    """Cari sampul video YouTube dari judulnya (fallback kalau GSMTC tak ada sampul).

    Dipakai hanya untuk trek YouTube Music di browser yang terdeteksi lewat
    judul jendela. Mengambil videoId pertama dari halaman hasil pencarian
    YouTube lalu mengunduh thumbnail hqdefault-nya. Mengembalikan bytes
    JPEG atau None (mis. halaman diblokir / tidak ada hasil / bukan JPEG).
    """
    if not title:
        return None
    # buang suffix tab browser (" | YouTube Music" / " - YouTube Music")
    # supaya pencarian YouTube memakai judul videonya saja
    for suf in (" | YouTube Music", " - YouTube Music", " | YouTube", " - YouTube"):
        if title.endswith(suf):
            title = title[: -len(suf)]
            break
    try:
        ua = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
        q = urllib.parse.quote(title)
        req = urllib.request.Request("https://www.youtube.com/results?search_query=" + q, headers=ua)
        html = urllib.request.urlopen(req, timeout=8).read().decode("utf-8", "ignore")
        m = re.search(r'"videoId":"([A-Za-z0-9_-]{11})"', html)
        if not m:
            return None
        img_req = urllib.request.Request("https://i.ytimg.com/vi/" + m.group(1) + "/hqdefault.jpg", headers=ua)
        raw = urllib.request.urlopen(img_req, timeout=8).read()
        if raw[:3] == b"\xff\xd8\xff":
            return raw
        return None
    except Exception:
        return None


def _fetch_itunes_cover(title, artist):
    """Cari sampul album lewat iTunes Search API (gratis, tanpa kunci).

    Dipakai untuk lagu lokal (mis. foobar2000) yang GSMTC-nya tak ada
    sampul dan bukan YouTube — server tidak tahu path file lokalnya,
    jadi sampul dicari dari judul + artis. Coba judul penuh dulu, lalu
    judul tanpa (...) / [...] kalau tidak ketemu. Mengembalikan
    (bytes JPEG 600x600, nama album, tahun) atau (None, "", "").
    """
    if not title:
        return None, "", ""
    def _try(t):
        q = urllib.parse.quote((artist + " " + t).strip())
        req = urllib.request.Request(
            "https://itunes.apple.com/search?term=" + q + "&media=music&entity=song&limit=1",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        )
        try:
            data = json.loads(urllib.request.urlopen(req, timeout=8).read().decode("utf-8", "ignore"))
        except Exception:
            return None, "", ""
        results = data.get("results") or []
        if not results:
            return None, "", ""
        r0 = results[0]
        url = (r0.get("artworkUrl100") or "").replace("100x100bb.jpg", "600x600bb.jpg")
        if not url:
            return None, "", ""
        try:
            img_req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            raw = urllib.request.urlopen(img_req, timeout=8).read()
        except Exception:
            return None, "", ""
        if raw[:3] != b"\xff\xd8\xff":
            return None, "", ""
        album = (r0.get("collectionName") or "").replace(" - Single", "").strip()
        rd = r0.get("releaseDate") or ""
        year = rd[:4] if len(rd) >= 4 and rd[:4].isdigit() else ""
        return raw, album, year
    raw, album, year = _try(title)
    if raw:
        return raw, album, year
    clean = re.sub(r"\s*[\(\[].*?[\)\]]", "", title).strip()
    if clean and clean != title:
        return _try(clean)
    return None, "", ""


def _fetch_cover():
    """Ambil sampul album lagu GSMTC yang sedang diputar, Windows saja.

    Mengembalikan (bytes, content_type) atau (None, None). Jalur:
    sesi GSMTC yang sedang Playing (kalau tidak ada, yang pertama
    berjudul) -> Thumbnail.OpenReadAsync -> .NET MemoryStream ->
    base64 ke stdout. Dipanggil hanya saat lagu berganti (dan
    paling cepat 60 detik sekali kalau gagal), supaya PowerShell
    tidak dijalankan tiap tick.
    """
    if not IS_WIN:
        return None, None
    try:
        ps = r"""
Add-Type -AssemblyName System.Runtime.WindowsRuntime
function AwaitOp($op) {
  if (-not $op) { return $null }
  try { return $op.AsTask().GetAwaiter().GetResult() } catch { return $null }
}
$mgrType = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows, ContentType=WindowsRuntime]
$manager = AwaitOp ($mgrType::RequestAsync())
if (-not $manager) { exit }
$best = $null
$bestPlaying = $null
foreach ($s in $manager.GetSessions()) {
  $props = AwaitOp ($s.TryGetMediaPropertiesAsync())
  $info = $null
  try { $info = $s.GetPlaybackInfo() } catch {}
  if ($props -and $props.Title) {
    $stNum = 0
    if ($info) { $stNum = [int]$info.PlaybackStatus }
    if ($stNum -eq 3) { $bestPlaying = $s; break }
    if (-not $best) { $best = $s }
  }
}
$sess = $null
if ($bestPlaying) { $sess = $bestPlaying } elseif ($best) { $sess = $best }
if ($sess) {
  $props = AwaitOp ($sess.TryGetMediaPropertiesAsync())
  $thumb = $null
  if ($props) { $thumb = $props.Thumbnail }
  if ($thumb) {
    $stream = AwaitOp ($thumb.OpenReadAsync())
    if ($stream) {
      $netStream = [System.Runtime.InteropServices.WindowsRuntime.WindowsRuntimeStreamExtensions]::AsStream($stream)
      $mem = New-Object System.IO.MemoryStream
      $netStream.CopyTo($mem)
      $netStream.Close()
      [Convert]::ToBase64String($mem.ToArray())
    }
  }
}
"""
        out = _run_ps(ps, timeout=8).strip()
        if not out:
            return None, None
        raw = base64.b64decode(out)
        if raw[:3] == b"\xff\xd8\xff":
            return raw, "image/jpeg"
        if raw[:8] == b"\x89PNG\r\n\x1a\n":
            return raw, "image/png"
        return raw, "image/jpeg"
    except Exception:
        return None, None


_WINRT_IMPORT_ERROR = ""


def _gsmtc_winrt():
    """Musik via GSMTC memakai paket Python 'winrt' (tanpa PowerShell).

    PowerShell 5.1 di PC ini terbukti tidak bisa memakai WinRT async
    (tipe tidak ketemu, lalu __ComObject tidak punya AsTask, lalu
    polling Status tidak pernah selesai). Paket winrt memanggil WinRT
    langsung dari Python lewat asyncio, jadi tidak kena masalah itu.
    Mengembalikan dict lagu (title/artist/album/player/status) atau
    None. Mengisi _np_debug['winrt'] ('ada'/'tidak ada'/pesan error).
    Dipanggil paling cepat 2 detik sekali (cache GSMTC yang sama).
    """
    global _WINRT_IMPORT_ERROR
    try:
        try:
            from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager
            _np_debug["winrt"] = "ada (winsdk)"
        except Exception:
            from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager
            _np_debug["winrt"] = "ada (winrt)"
    except Exception as e:
        _np_debug["winrt"] = "tidak ada"
        if not _WINRT_IMPORT_ERROR:
            _WINRT_IMPORT_ERROR = str(e)[:200]
        return None

    async def _query():
        manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
        if manager is None:
            return None
        sessions = list(manager.get_sessions())
        if not sessions:
            return None
        best = None
        best_playing = None
        for sess in sessions:
            try:
                props = await sess.try_get_media_properties_async()
            except Exception:
                continue
            if props is None or not getattr(props, "title", ""):
                continue
            try:
                info = sess.get_playback_info()
                if info is not None:
                    _ps = info.playback_status
                    try:
                        st = int(_ps)
                    except Exception:
                        _nm = str(getattr(_ps, "name", _ps)).lower()
                        if "play" in _nm:
                            st = 3
                        elif "paus" in _nm:
                            st = 4
                        elif "stop" in _nm:
                            st = 2
                        else:
                            st = 0
                else:
                    st = 0
            except Exception:
                st = 0
            if st == 0:
                st = 3
            app = ""
            try:
                app = sess.source_app_user_model_id or ""
            except Exception:
                app = ""
            try:
                _np_debug["winrt_status_raw"] = str(st)
            except Exception:
                pass
            line = {
                "title": props.title or "",
                "artist": getattr(props, "artist", "") or "",
                "album": getattr(props, "album_title", "") or "",
                "player": app,
                "status": "Playing" if st == 3 else ("Paused" if st == 4 else "Unknown"),
            }
            if st == 3:
                best_playing = line
                break
            if best is None:
                best = line
        return best_playing if best_playing is not None else best

    try:
        raw = asyncio.run(asyncio.wait_for(_query(), timeout=10))
    except Exception as e:
        _np_debug["gsmtc_err"] = ("winrt: " + str(e))[:300]
        return None
    if raw is None:
        return None
    # samakan bentuk dengan _parse_gsmtc_out (player + status)
    app_raw = (raw.get("player") or "").lower()
    if "spotify" in app_raw:
        player = "Spotify"
    elif "brave" in app_raw:
        player = "Brave (Browser)"
    elif "chrome" in app_raw:
        player = "Chrome (Browser)"
    elif "msedge" in app_raw or "edge" in app_raw:
        player = "Microsoft Edge (Browser)"
    elif "firefox" in app_raw:
        player = "Firefox (Browser)"
    elif "vlc" in app_raw:
        player = "VLC"
    elif "wmplayer" in app_raw or "mediaplayer" in app_raw:
        player = "Windows Media Player"
    elif "nocturne" in app_raw:
        player = "Nocturne Music"
    else:
        player = (raw.get("player") or "").split("_")[0] if raw.get("player") else ""
    return {
        "title": raw.get("title", ""), "artist": raw.get("artist", ""),
        "album": raw.get("album", ""), "player": player,
        "status": raw.get("status", "Unknown"),
    }


def _gsmtc_thumbnail_winrt():
    """Sampul album dari aplikasi pemutar via Python winrt (bukan PowerShell).

    Ini gambar yang sama dengan yang ditampilkan aplikasi pemutar itu sendiri
    (Nocturne Music / Gatefold / Spotify / dll.) di sesi medianya — GSMTC
    Thumbnail. PowerShell 5.1 WinRT terbukti rusak di PC ini (perc77-85),
    jadi _fetch_cover() yang memakai PowerShell sering gagal; jalur winrt
    ini sama dengan yang dipakai _gsmtc_winrt() untuk info lagu dan terbukti
    jalan. Mengembalikan (bytes, content_type) atau (None, None).
    """
    try:
        try:
            from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager
            from winsdk.windows.storage.streams import DataReader
        except Exception:
            from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager
            from winrt.windows.storage.streams import DataReader
    except Exception:
        return None, None

    async def _query():
        manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
        if manager is None:
            return None
        sessions = list(manager.get_sessions())
        if not sessions:
            return None
        best = None
        best_playing = None
        for sess in sessions:
            try:
                props = await sess.try_get_media_properties_async()
            except Exception:
                continue
            if props is None or not getattr(props, "title", ""):
                continue
            try:
                info = sess.get_playback_info()
                st = 0
                if info is not None:
                    try:
                        st = int(info.playback_status)
                    except Exception:
                        _nm = str(getattr(info.playback_status, "name", "")).lower()
                        if "play" in _nm:
                            st = 3
                        elif "paus" in _nm:
                            st = 4
            except Exception:
                st = 0
            if st == 0:
                st = 3
            thumb = getattr(props, "thumbnail", None)
            if st == 3:
                best_playing = thumb
                break
            if best is None:
                best = thumb
        ref = best_playing if best_playing is not None else best
        if ref is None:
            return None
        try:
            stream = await ref.open_read_async()
        except Exception:
            return None
        if stream is None:
            return None
        try:
            size = int(stream.size)
        except Exception:
            size = 0
        if size <= 0:
            return None
        try:
            reader = DataReader(stream)
            await reader.load_async(size)
            try:
                raw = bytes(reader.read_bytes(size))
            except Exception:
                raw = bytes(reader.read_buffer(size))
            return raw
        except Exception:
            return None

    try:
        raw = asyncio.run(asyncio.wait_for(_query(), timeout=10))
    except Exception:
        return None, None
    if not raw:
        return None, None
    if raw[:3] == b"\xff\xd8\xff":
        return raw, "image/jpeg"
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return raw, "image/png"
    return raw, "image/jpeg"


def _parse_gsmtc_out(out):
    """Parse output PS GSMTC: 5 baris (judul, artis, album, app, status).

    Dipisah per baris (bukan '|') karena judul lagu/video bisa mengandung
    '|' — mis. 'Best Anime Opens (2000 - 2024) || FULL SONGS | YouTube
    Music' akan hancur kalau di-split '|'. Fungsi murni supaya bisa dites.
    """
    if not out:
        return None
    parts = [p.strip() for p in out.strip().splitlines()]
    if len(parts) < 5 or not parts[0] or parts[0].lower() in ("youtube music", "youtube"):
        return None
    app_raw = parts[3].lower()
    if "spotify" in app_raw:
        player = "Spotify"
    elif "brave" in app_raw:
        player = "Brave (Browser)"
    elif "chrome" in app_raw:
        player = "Chrome (Browser)"
    elif "msedge" in app_raw or "edge" in app_raw:
        player = "Microsoft Edge (Browser)"
    elif "firefox" in app_raw:
        player = "Firefox (Browser)"
    elif "vlc" in app_raw:
        player = "VLC"
    elif "wmplayer" in app_raw or "mediaplayer" in app_raw:
        player = "Windows Media Player"
    elif "nocturne" in app_raw:
        player = "Nocturne Music"
    else:
        player = parts[3].split("_")[0] if parts[3] else ""
    return {
        "title": parts[0], "artist": parts[1], "album": parts[2],
        "player": player, "status": parts[4],
    }


_np_debug = {"beefweb": "-", "gsmtc": "-", "windows": [], "gsmtc_err": "", "pwsh": "-", "winrt": "-"}
_np_last_source = "-"
_last_ps_err = {"kind": ""}
_BEEFWEB_BASE = "http://127.0.0.1:8880"
_BEEFWEB_COLS = ["%artist%", "%title%", "%album%", "%date%", "%codec%", "%bitrate%", "%samplerate%", "%bitspersample%", "%channels%"]
_beefweb_current = {"playlist_id": "", "index": -1}
_beefweb_upnext = {"key": "", "items": []}


def _beefweb_get(path):
    """GET JSON dari Beefweb (localhost:8880) atau None kalau tidak ada/tidak jalan."""
    try:
        req = urllib.request.Request(_BEEFWEB_BASE + path, headers={"User-Agent": "PCMonitorHUD/1.0"})
        return json.loads(urllib.request.urlopen(req, timeout=2).read().decode("utf-8", "ignore"))
    except Exception:
        return None


def _beefweb_artwork(pid, idx):
    """Sampul asli lagu dari Beefweb: coba /api/artwork/{playlist}/{index}, lalu /api/artwork/current."""
    for path in ("/api/artwork/%s/%s" % (urllib.parse.quote(str(pid)), idx), "/api/artwork/current"):
        try:
            req = urllib.request.Request(_BEEFWEB_BASE + path, headers={"User-Agent": "PCMonitorHUD/1.0"})
            raw = urllib.request.urlopen(req, timeout=4).read()
            if raw[:3] == b"\xff\xd8\xff":
                return raw, "image/jpeg"
            if raw[:8] == b"\x89PNG\r\n\x1a\n":
                return raw, "image/png"
        except Exception:
            continue
    return None, None


def _beefweb_now_playing():
    """Lagu yang sedang diputar di foobar2000/Gatefold via Beefweb.

    Mengembalikan dict now_playing (atau None): judul, artis, album,
    tahun, format (badge codec/bit depth/bitrate), posisi/durasi, dan
    menyimpan playlist + index aktif untuk sampul dan up next. Hanya
    dipakai kalau statusnya 'playing' — kalau dijeda/berhenti, biarkan
    GSMTC/fallback yang bicara (mungkin Nocturne yang sedang main).
    Mengembalikan None kalau Beefweb tidak terpasang / tidak jalan.
    """
    cols_q = urllib.parse.urlencode({"columns": _BEEFWEB_COLS}, doseq=True)
    data = _beefweb_get("/api/player?" + cols_q)
    if not data:
        _np_debug["beefweb"] = "unreachable"
        return None
    player = data.get("player") or {}
    if (player.get("playbackState") or "").lower() != "playing":
        _np_debug["beefweb"] = "paused/stopped"
        return None
    item = player.get("activeItem") or {}
    cols = list(item.get("columns") or []) + [""] * len(_BEEFWEB_COLS)
    artist, title, album, date, codec, bitrate, samplerate, bits, channels = cols[:9]
    if not title:
        return None
    year = (date or "")[:4] if (date or "")[:4].isdigit() else ""
    fmt = []
    if codec:
        fmt.append(codec.upper())
    if bits and samplerate:
        try:
            fmt.append("%s-bit / %s kHz" % (bits, ("%g" % (float(samplerate) / 1000.0))))
        except Exception:
            pass
    elif samplerate:
        try:
            fmt.append("%s kHz" % ("%g" % (float(samplerate) / 1000.0)))
        except Exception:
            pass
    if bitrate:
        fmt.append("%s kbps" % bitrate)
    _beefweb_current["playlist_id"] = (player.get("playlist") or {}).get("id", "") or ""
    _beefweb_current["index"] = item.get("index", -1)
    res = {
        "title": title, "artist": artist, "album": album,
        "player": "foobar2000", "status": "Playing", "_bw": True,
    }
    if year:
        res["year"] = year
    if fmt:
        res["format"] = fmt
    try:
        pos = float(item.get("position"))
        dur = float(item.get("duration"))
        if dur > 0:
            res["position"] = pos
            res["duration"] = dur
    except Exception:
        pass
    vol = player.get("volume") or {}
    if vol:
        res["muted"] = bool(vol.get("isMuted", False))
        try:
            res["volume_db"] = float(vol.get("value"))
        except Exception:
            pass
    _np_debug["beefweb"] = "playing"
    return res


def _beefweb_up_next(key):
    """5 lagu berikutnya di playlist yang sedang dimainkan (via Beefweb)."""
    if _beefweb_upnext["key"] == key:
        return _beefweb_upnext["items"]
    items = []
    pid = _beefweb_current.get("playlist_id") or ""
    idx = _beefweb_current.get("index", -1)
    if pid and idx >= 0:
        cols_q = urllib.parse.urlencode({"columns": ["%artist%", "%title%"]}, doseq=True)
        data = _beefweb_get("/api/playlists/%s/items?start=%d&count=5&%s" % (
            urllib.parse.quote(str(pid)), idx + 1, cols_q))
        if data:
            for it in (data.get("playlistItems") or [])[:5]:
                cols = list(it.get("columns") or []) + ["", ""]
                if cols[1]:
                    items.append({"artist": cols[0] or "", "title": cols[1]})
    _beefweb_upnext["key"] = key
    _beefweb_upnext["items"] = items
    return items


def _beefweb_post(path, params=None):
    """POST ke Beefweb, kembalikan True kalau HTTP 2xx."""
    try:
        url = _BEEFWEB_BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, data=b"", method="POST",
                                     headers={"User-Agent": "PCMonitorHUD/1.0"})
        with urllib.request.urlopen(req, timeout=2) as r:
            return 200 <= r.status < 300
    except Exception:
        return False


def _beefweb_control(action, value=None):
    """Kontrol pemutaran foobar2000/Gatefold via Beefweb.

    Endpoint dari pyfoobeef 0.9.0.4 (endpoints.py): play, pause,
    pause/toggle, next, previous, dan set_player_state via
    POST /api/player?isMuted=.. / ?position=.. (query string).
    """
    if action == "play":
        return _beefweb_post("/api/player/play")
    if action == "pause":
        return _beefweb_post("/api/player/pause")
    if action == "toggle":
        return _beefweb_post("/api/player/pause/toggle")
    if action == "next":
        return _beefweb_post("/api/player/next")
    if action == "prev":
        return _beefweb_post("/api/player/previous")
    if action == "mute":
        return _beefweb_post("/api/player", {"isMuted": "true" if value else "false"})
    if action == "seek":
        try:
            return _beefweb_post("/api/player", {"position": str(float(value))})
        except Exception:
            return False
    return False


def _gsmtc_control_ps(action, value=None):
    """Script PowerShell untuk kontrol transport GSMTC.

    Memakai AwaitOp (AsTask/GetAwaiter/GetResult, perc80) yang sama dengan pembacaan metadata:
    pilih sesi yang sedang Playing (atau yang pertama berjudul),
    lalu panggil TryPlayAsync / TryPauseAsync / TrySkipNextAsync /
    TrySkipPreviousAsync / TryChangePlaybackPositionAsync.
    Mengembalikan 'ok' kalau operasinya berhasil.
    """
    if action == "play":
        call = "$sess.TryPlayAsync()"
    elif action == "pause":
        call = "$sess.TryPauseAsync()"
    elif action == "next":
        call = "$sess.TrySkipNextAsync()"
    elif action == "prev":
        call = "$sess.TrySkipPreviousAsync()"
    elif action == "seek":
        try:
            ticks = int(float(value) * 10000000)
        except Exception:
            return ""
        call = "$sess.TryChangePlaybackPositionAsync(%d)" % ticks
    else:
        return ""
    return """
Add-Type -AssemblyName System.Runtime.WindowsRuntime
function AwaitOp($op) {
  if (-not $op) { return $null }
  try { return $op.AsTask().GetAwaiter().GetResult() } catch { return $null }
}
$mgrType = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows, ContentType=WindowsRuntime]
$manager = AwaitOp ($mgrType::RequestAsync())
if (-not $manager) { exit }
$best = $null
$bestPlaying = $null
foreach ($s in $manager.GetSessions()) {
  $props = AwaitOp ($s.TryGetMediaPropertiesAsync())
  if ($props -and $props.Title) {
    $info = $null
    try { $info = $s.GetPlaybackInfo() } catch {}
    $stNum = 0
    if ($info) { $stNum = [int]$info.PlaybackStatus }
    if ($stNum -eq 3) { $bestPlaying = $s; break }
    if (-not $best) { $best = $s }
  }
}
$sess = $null
if ($bestPlaying) { $sess = $bestPlaying } elseif ($best) { $sess = $best }
if ($sess) {
  $r = AwaitOp (""" + call + """)
  if ($r) { 'ok' }
}
"""


def _gsmtc_control(action, value=None):
    """Kontrol transport sesi GSMTC (Nocturne / browser / Spotify)."""
    if not IS_WIN:
        return False
    ps = _gsmtc_control_ps(action, value)
    if not ps:
        return False
    out, err, rc = _run_ps_full(ps, timeout=10)
    return "ok" in (out or "")



# --- Placeholder anime untuk album tanpa cover (perc129) ---
# Bila kelima sumber cover gagal, pakai gambar anime orisinil dari folder
# covers/ di samping monitor_server.py, dipilih dari kata kunci judul+artis.
_ANIME_COVER_FILES = {"energetic": "anime_energetic.jpg", "calm": "anime_calm.jpg",
                      "sad": "anime_sad.jpg", "default": "anime_default.jpg"}
_ANIME_COVER_CACHE = {}  # key -> bytes JPG, dimuat sekali per key
_ANIME_COVER_SAD = ("sad", "tears", "tear", "cry", "crying", "lonely", "alone",
    "goodbye", "farewell", "miss", "lost", "pain", "hurt", "broken",
    "heartbreak", "sorry", "regret", "melancholy", "sorrow", "grief",
    "memory", "remember", "sayonara", "nostalgia", "longing", "ache",
    "wound", "scar", "namida", "kanashii", "solitude", "silent")
_ANIME_COVER_ENERGETIC = ("rock", "metal", "dance", "edm", "electro",
    "party", "upbeat", "power", "battle", "fight", "remix", "dubstep",
    "punk", "happy", "energy", "jump", "drive", "speed", "fire", "burn",
    "storm", "thunder", "beat", "bass", "club", "rave", "hyper", "turbo",
    "wild", "crazy", "boom", "bang", "kick", "shout", "scream", "loud",
    "heavy", "guitar", "drum", "disco", "funk", "summer", "sun", "fly",
    "high", "groove", "move", "festival", "anthem")
_ANIME_COVER_CALM = ("calm", "relax", "chill", "slow", "soft", "peace",
    "peaceful", "ambient", "piano", "acoustic", "ballad", "lullaby",
    "sleep", "dream", "gentle", "quiet", "serene", "tranquil", "mellow",
    "smooth", "easy", "lofi", "lo-fi", "jazz", "bossa", "soul", "healing",
    "meditation", "rain", "sea", "ocean", "wind", "sky", "star", "moon",
    "night", "sakura", "blossom", "spring", "morning", "sunset", "dusk")

def _anime_cover_key(title, artist):
    """Kunci placeholder anime dari kata kunci judul+artis. Prioritas:
    sad > energetic > calm > default."""
    t = ((title or "") + " " + (artist or "")).lower()
    if any(k in t for k in _ANIME_COVER_SAD):
        return "sad"
    if any(k in t for k in _ANIME_COVER_ENERGETIC):
        return "energetic"
    if any(k in t for k in _ANIME_COVER_CALM):
        return "calm"
    return "default"

def _load_anime_cover(key):
    """Bytes JPG placeholder anime (cache di memori per key). Return bytes/None."""
    if key in _ANIME_COVER_CACHE:
        return _ANIME_COVER_CACHE[key]
    try:
        p = BASE_DIR / "covers" / _ANIME_COVER_FILES.get(key, "anime_default.jpg")
        data = p.read_bytes()
        if data[:3] == b"\xff\xd8\xff":
            _ANIME_COVER_CACHE[key] = data
            return data
    except Exception:
        pass
    return None

def _now_playing():
    """Musik yang sedang diputar, Windows saja, via GSMTC.

    GSMTC (Global System Media Transport Controls) adalah sesi media
    sistem Windows: Spotify, YouTube / YouTube Music di browser, VLC,
    Windows Media Player, dll. yang sedang memutar media akan muncul
    di sini, lengkap dengan judul, artis, album, aplikasi sumber, dan
    status Playing/Paused. Di-cache 5 detik karena PowerShell + WinRT
    lumayan berat kalau dijalankan tiap tick 2 detik.
    Kalau tidak ada sesi media, kembalikan None (bukan error).

    PENTING untuk file lokal: tidak semua pemutar file lokal mendaftarkan
    dirinya ke GSMTC. Pemutar lokal lama / tertentu hanya menampilkan
    judul lagu di judul jendelanya saja, tanpa sesi GSMTC. Karena itu,
    kalau GSMTC kosong, fungsi ini jatuh ke _media_from_windows():
    membaca judul jendela Spotify / VLC / foobar2000 / MusicBee /
    AIMP / Windows Media Player / YouTube Music di browser, dan
    mengambil judul + artis dari sana. Jadi file MP3 lokal yang diputar
    di pemutar-pemutar itu tetap terdeteksi, walau tanpa GSMTC.
    """
    global _now_playing_cache, _gsmtc_cache, _fallback_cache
    if not IS_WIN:
        return None
    now = time.time()
    # Beefweb dicek fresh tiap tick (localhost, murah) supaya ganti lagu
    # di foobar2000/Gatefold terdeteksi instan, tanpa menunggu cache.
    result = _beefweb_now_playing()
    src = "beefweb" if result is not None else None
    if result is None and now - _gsmtc_cache[1] < 2:
        result = _gsmtc_cache[0]
        if result is not None:
            src = "gsmtc"
    if result is None and now - _gsmtc_cache[1] >= 2:
        _wr = _gsmtc_winrt()
        if _wr is not None:
            result = _wr
            _np_debug["gsmtc"] = "ok: " + (result.get("player") or "?") + " (winrt)"
            _np_debug["gsmtc_err"] = ""
            _gsmtc_cache = (result, now)
            src = "gsmtc"
    if result is None and now - _gsmtc_cache[1] >= 2:
        err, rc = "", 0
        try:
            ps = r"""
try {
  Add-Type -AssemblyName System.Runtime.WindowsRuntime
  function AwaitOp($op) {
    if (-not $op) { return $null }
    try { return $op.AsTask().GetAwaiter().GetResult() } catch { return $null }
  }
  $mgrType = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows, ContentType=WindowsRuntime]
  $manager = $mgrType::RequestAsync().AsTask().GetAwaiter().GetResult()
  if (-not $manager) { [Console]::Error.WriteLine("SESSIONS:0 manager-null"); exit }
  $sessions = @($manager.GetSessions())
  if ($sessions.Count -eq 0) { [Console]::Error.WriteLine("SESSIONS:0") }
  $best = $null
  $bestPlaying = $null
  foreach ($s in $sessions) {
    $props = AwaitOp ($s.TryGetMediaPropertiesAsync())
    if (-not $props -or -not $props.Title) { continue }
    $info = $null
    try { $info = $s.GetPlaybackInfo() } catch {}
    $stNum = 0
    $stName = "Unknown"
    if ($info) { $stNum = [int]$info.PlaybackStatus; $stName = "$($info.PlaybackStatus)" }
    $line = "$($props.Title)`n$($props.Artist)`n$($props.AlbumTitle)`n$($s.SourceAppUserModelId)`n$stName"
    if ($stNum -eq 3) { $bestPlaying = $line; break }
    if (-not $best) { $best = $line }
  }
  if ($bestPlaying) { $bestPlaying } elseif ($best) { $best }
} catch {
  [Console]::Error.WriteLine(("GSMTC-ERR: " + $_.Exception.Message))
  exit 1
}
"""
            out, err, rc = _run_ps_full(ps, timeout=15)
            _np_debug["pwsh"] = "ada" if shutil.which("pwsh") else "tidak ada"
            if rc != 0:
                out2, err2, rc2 = _run_ps_full_pwsh(ps, timeout=15)
                if out2.strip():
                    out, err, rc = out2, err2, rc2
            _np_debug["gsmtc_err"] = err.strip().replace("\r", " ").replace("\n", " ")[:300] if err.strip() else ""
            result = _parse_gsmtc_out(out.strip())
        except Exception:
            result = None
        if result:
            _np_debug["gsmtc"] = "ok: " + (result.get("player") or "?")
        elif rc == -1:
            _np_debug["gsmtc"] = "tidak ada sesi (powershell timeout)"
        elif rc != 0:
            _np_debug["gsmtc"] = "tidak ada sesi (powershell gagal)"
        else:
            _np_debug["gsmtc"] = "tidak ada sesi"
        _gsmtc_cache = (result, now)
        if result is not None:
            src = "gsmtc"
    if result is None:
        # Judul jendela: cache 1 detik saja (Get-Process ringan), supaya
        # ganti lagu di pemutar lokal terasa instan.
        if now - _fallback_cache[1] < 1:
            result = _fallback_cache[0]
        else:
            result = _media_from_windows()
            _fallback_cache = (result, now)
        if result is not None:
            src = "fallback"
    if result is not None:
        global _np_last_source
        if src:
            _np_last_source = src
            result["source"] = src
        result["cover_id"] = ""
        key = hashlib.md5(
            f"{result.get('title', '')}|{result.get('artist', '')}|{result.get('album', '')}".encode("utf-8", "ignore")
        ).hexdigest()[:12]
        if _cover_cache["data"] and _cover_cache["id"] == key:
            result["cover_id"] = key
        elif _cover_cache["tried_key"] != key or now - _cover_cache["tried_at"] >= 60:
            _cover_cache["tried_key"] = key
            _cover_cache["tried_at"] = now
            data, ctype = (None, None)
            it_album, it_year = "", ""
            _cover_src = "none"
            if result.get("_bw"):
                data, ctype = _beefweb_artwork(_beefweb_current.get("playlist_id") or "", _beefweb_current.get("index", -1))
                if data:
                    _cover_src = "beefweb"
            if not data and result.get("status") != "Aktif":
                data, ctype = _gsmtc_thumbnail_winrt()
                if data:
                    _cover_src = "winrt"
            if not data and result.get("status") != "Aktif":
                data, ctype = _fetch_cover()
                if data:
                    _cover_src = "powershell"
            if not data and ("YouTube" in (result.get("player") or "") or "Nocturne" in (result.get("player") or "")):
                data = _fetch_yt_cover(result.get("title", ""))
                ctype = "image/jpeg"
                if data:
                    _cover_src = "youtube"
            if not data and "YouTube" not in (result.get("player") or ""):
                data, it_album, it_year = _fetch_itunes_cover(result.get("title", ""), result.get("artist", ""))
                ctype = "image/jpeg"
                if data:
                    _cover_src = "itunes"
            if not data and "YouTube" not in (result.get("player") or ""):
                _yt_q = result.get("title", "")
                if result.get("artist"):
                    _yt_q = _yt_q + " - " + result.get("artist", "")
                data = _fetch_yt_cover(_yt_q)
                ctype = "image/jpeg"
                if data:
                    _cover_src = "youtube"
            if data:
                _cover_cache.update({"id": key, "data": data, "ctype": ctype or "image/jpeg",
                                     "album": it_album, "year": it_year})
                result["cover_id"] = key
            else:
                _ak = _anime_cover_key(result.get("title", ""), result.get("artist", ""))
                _ad = _load_anime_cover(_ak)
                if _ad:
                    _cover_cache.update({"id": "anime:" + _ak, "data": _ad,
                                         "ctype": "image/jpeg", "album": "", "year": ""})
                    result["cover_id"] = "anime:" + _ak
                    _cover_src = "anime"
                else:
                    _cover_cache["data"] = None
                    _cover_cache["id"] = ""
                    _cover_cache["album"] = ""
                    _cover_cache["year"] = ""
        try:
            _np_debug["cover_src"] = _cover_src
        except Exception:
            pass
        if not result.get("album") and _cover_cache.get("id") == key and _cover_cache.get("album"):
            result["album"] = _cover_cache["album"]
            result["year"] = _cover_cache.get("year") or ""
        if result.get("_bw"):
            result["up_next"] = _beefweb_up_next(key)
    if result is not None:
        result.pop("_bw", None)
    _now_playing_cache = (result, now)
    return result


PLN_TARIFFS = {
    "R-1 450 VA (subsidi)": 415,
    "R-1 900 VA (subsidi)": 605,
    "R-1 900 VA-RTM": 1352,
    "R-1 1300 VA": 1444.70,
    "R-1 2200 VA": 1444.70,
    "R-2/R-3 3500 VA ke atas": 1699.53,
}
_power_last = {"time": 0.0}


def _power_path():
    import os
    if IS_WIN:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return Path(base) / "PCMonitorHUD" / "power.json"
    return Path(os.path.expanduser("~")) / ".pc_monitor_hud" / "power.json"


def _load_power():
    try:
        data = json.loads(_power_path().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"date": "", "kwh_today": 0.0, "kwh_total": 0.0,
            "golongan": "R-1 1300 VA", "tariff": PLN_TARIFFS["R-1 1300 VA"]}


def _save_power(data):
    try:
        p = _power_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data), encoding="utf-8")
        return True
    except Exception:
        return False


def _cpu_tdp(model):
    m = (model or "").lower()
    if "ryzen 9" in m or "ryzen 9 " in m:
        return 170
    if "ryzen 7" in m:
        return 105
    if "ryzen 5" in m:
        return 65
    if "ryzen 3" in m:
        return 65
    if "i9" in m:
        return 125
    if "i7" in m:
        return 125
    if "i5" in m:
        return 65
    if "i3" in m:
        return 65
    return 65


def _gpu_tdp(name):
    n = (name or "").lower()
    if "rx 6600 xt" in n:
        return 160
    if "rx 6600" in n:
        return 132
    if "rx 6700" in n:
        return 175
    if "rtx 4060" in n:
        return 115
    if "rtx 3060" in n:
        return 170
    if "rtx 3070" in n:
        return 220
    if "gtx 1660" in n:
        return 120
    if "gtx 1650" in n:
        return 75
    if n:
        return 120
    return 0


def _estimate_watts(cpu_pct, gpu_util, cpu_model, gpu_name, monitor_count):
    cpu_tdp = _cpu_tdp(cpu_model)
    gpu_tdp = _gpu_tdp(gpu_name)
    cpu_w = 12 + max(0.0, min(100.0, cpu_pct or 0)) / 100.0 * max(cpu_tdp - 12, 0)
    gpu_w = 0.0
    if gpu_tdp:
        gpu_w = 10 + max(0.0, min(100.0, gpu_util or 0)) / 100.0 * max(gpu_tdp - 10, 0)
    base_w = 40.0
    monitor_w = 25.0 * max(monitor_count, 0)
    total = cpu_w + gpu_w + base_w + monitor_w
    return {"watts": round(total, 1), "cpu_w": round(cpu_w, 1), "gpu_w": round(gpu_w, 1),
            "base_w": base_w, "monitor_w": monitor_w,
            "cpu_tdp": cpu_tdp, "gpu_tdp": gpu_tdp}


def _accumulate_power(cpu_pct=None, gpu_util=None, cpu_model=None, gpu_name=None, monitor_count=0):
    """Tambah energi (kWh) berdasarkan daya saat ini dan waktu sejak
    hitungan terakhir. Dipanggil tiap tick dashboard dan tiap 10 detik
    oleh thread latar, jadi akumulasi tetap jalan walau dashboard HP
    ditutup, selama jendela server masih terbuka. dt dibatasi 60 detik
    supaya jeda panjang (misal PC tidur) tidak dihitung sebagai pemakaian
    penuh. Ini ESTIMASI dari utilisasi, bukan pembacaan wattmeter."""
    import datetime
    now = time.time()
    last = _power_last["time"]
    _power_last["time"] = now
    if cpu_pct is None:
        try:
            cpu_pct = psutil.cpu_percent(interval=None)
        except Exception:
            cpu_pct = 0
    if _ULTRA_MODE:
        # Mode Super Ringan: jangan panggil fallback berat (PowerShell untuk
        # nama CPU, nvidia-smi/LHM untuk GPU, scan monitor). Pakai cache /
        # nilai terakhir yang diketahui saja.
        if cpu_model is None:
            cpu_model = _cpu_model_cache[0]
        if gpu_name is None:
            gpu_name = ""
        if monitor_count == 0:
            monitor_count = _ULTRA_MONITORS
    else:
        if cpu_model is None:
            cpu_model = _cpu_model()
        if gpu_name is None:
            try:
                gs = _gpu_info()
                if not gs and IS_WIN:
                    gs = _gpu_from_lhm_web()
                gpu_name = gs[0]["name"] if gs else ""
                if gpu_util is None and gs:
                    gpu_util = float(gs[0]["util"])
            except Exception:
                gpu_name = ""
        if monitor_count == 0:
            try:
                monitor_count = len(_monitors())
            except Exception:
                monitor_count = 0
    est = _estimate_watts(cpu_pct, gpu_util, cpu_model, gpu_name, monitor_count)
    data = _load_power()
    today = datetime.date.today().isoformat()
    if data.get("date") != today:
        data["date"] = today
        data["kwh_today"] = 0.0
    if last and 0 < now - last <= 60:
        kwh = est["watts"] * (now - last) / 3600000.0
        data["kwh_today"] = round(data.get("kwh_today", 0.0) + kwh, 6)
        data["kwh_total"] = round(data.get("kwh_total", 0.0) + kwh, 6)
        _save_power(data)
    return est, data


def _power_info(cpu_pct, gpu_util, cpu_model, gpu_name, monitor_count):
    import datetime
    est, data = _accumulate_power(cpu_pct, gpu_util, cpu_model, gpu_name, monitor_count)
    tariff = float(data.get("tariff") or PLN_TARIFFS["R-1 1300 VA"])
    golongan = data.get("golongan") or "R-1 1300 VA"
    try:
        off = datetime.datetime.now().astimezone().utcoffset().total_seconds() / 3600
        tz = f"UTC{off:+g}".replace("+", "+").replace("-", "-")
        location = f"Indonesia ({tz})" if off in (7, 8, 9) else f"Indonesia (zona PC {tz})"
    except Exception:
        location = "Indonesia"
    kwh_today = data.get("kwh_today", 0.0)
    return {"country": "Indonesia", "provider": "PLN", "currency": "IDR",
            "location_auto": location, "golongan": golongan, "tariff_per_kwh": tariff,
            "tariffs": PLN_TARIFFS,
            "watts": est["watts"], "cpu_w": est["cpu_w"], "gpu_w": est["gpu_w"],
            "base_w": est["base_w"], "monitor_w": est["monitor_w"],
            "cpu_tdp": est["cpu_tdp"], "gpu_tdp": est["gpu_tdp"],
            "kwh_today": round(kwh_today, 4), "kwh_total": round(data.get("kwh_total", 0.0), 4),
            "cost_today": round(kwh_today * tariff, 0),
            "cost_per_hour": round(est["watts"] / 1000.0 * tariff, 1),
            "note": "Estimasi dari utilisasi CPU/GPU, bukan wattmeter."}


def _power_thread():
    while True:
        try:
            _accumulate_power()
        except Exception:
            pass
        time.sleep(10)


def _update_recent_apps(app):
    """Daftar 3-5 aplikasi terakhir yang dipakai, terbaru di atas.

    Tiap tick, aplikasi aktif saat ini dipindah ke posisi pertama
    (kalau sudah ada di daftar, dihapus dulu lalu dimasukkan lagi di
    atas dengan judul terbarunya), lalu daftar dipotong maksimal 5.
    Jadi dashboard tidak cuma menampilkan 1 aplikasi, tapi 3-5 aplikasi
    terakhir yang dipakai, masing-masing dengan ikonnya sendiri.
    """
    if app and app.get("exe"):
        exe = app["exe"]
        if app.get("exe_path"):
            _recent_app_paths[exe] = app["exe_path"]
        _recent_apps[:] = [a for a in _recent_apps if a["exe"] != exe]
        _recent_apps.insert(0, {
            "name": app["name"], "title": app["title"], "exe": exe, "pid": app["pid"],
        })
        del _recent_apps[5:]
    return list(_recent_apps)



def _disk_type_from(media, bus, model=""):
    """Tentukan label tipe disk dari MediaType/BusType/Model (Windows)."""
    m = (media or "").strip()
    b = (bus or "").strip()
    mo = (model or "").strip().lower()
    if b.lower() == "nvme" or "nvme" in mo:
        return "NVMe"
    if m.lower() == "ssd" or "ssd" in mo:
        return "SSD"
    if m.lower() == "hdd":
        return "HDD"
    if b.lower() == "usb":
        return "USB"
    if m and m.lower() != "unspecified":
        return m
    if b and b.lower() != "unspecified":
        return b
    return None


def _parse_disk_types_ps(txt):
    """Parse output PowerShell 'Huruf|MediaType|BusType|Model' -> {huruf: tipe}."""
    out = {}
    for line in (txt or "").splitlines():
        parts = [x.strip() for x in line.split("|")]
        if len(parts) < 3 or not parts[0]:
            continue
        t = _disk_type_from(parts[1], parts[2], parts[3] if len(parts) > 3 else "")
        if t:
            out[parts[0].upper()] = t
    return out


def _disk_types_windows():
    """Peta huruf drive -> tipe, cache 5 menit supaya PowerShell tidak jalan tiap 2 detik."""
    global _disk_types_cache
    data, ts = _disk_types_cache
    if data is not None and time.time() - ts < 300:
        return data
    ps = (
        "$m=@{}; Get-Partition | Where-Object {$_.DriveLetter} | ForEach-Object { $k=\"$($_.DiskNumber)\"; "
        "if (-not $m.ContainsKey($k)) { $m[$k]=@() }; $m[$k]+=$_.DriveLetter }; "
        "Get-PhysicalDisk | ForEach-Object { $k=\"$($_.DeviceId)\"; "
        "if ($m.ContainsKey($k)) { foreach ($d in $m[$k]) { \"$d|$($_.MediaType)|$($_.BusType)|$($_.Model)\" } } }"
    )
    data = _parse_disk_types_ps(_run_ps(ps, timeout=8))
    _disk_types_cache = (data, time.time())
    return data


def _linux_disk_type(device):
    """Fallback Linux: nama nvme -> NVMe, /sys/block rotational 0 -> SSD, 1 -> HDD."""
    try:
        base = device.rsplit("/", 1)[-1]
        if "nvme" in base:
            return "NVMe"
        block = re.sub(r"p?\d+$", "", base)
        with open(f"/sys/block/{block}/queue/rotational", "r", encoding="utf-8") as f:
            return "SSD" if f.read().strip() == "0" else "HDD"
    except Exception:
        return None



def _parse_wifi_signal(txt):
    """Parse 'netsh wlan show interfaces' -> {ssid, signal} untuk Wi-Fi yang tersambung, atau None."""
    ssid = None
    state = ""
    for line in (txt or "").splitlines():
        s = line.strip()
        if s.lower().startswith("ssid"):
            ssid = s.split(":", 1)[1].strip() if ":" in s else None
        elif s.lower().startswith("state"):
            state = s.split(":", 1)[1].strip().lower() if ":" in s else ""
        elif s.lower().startswith("signal"):
            try:
                pct = int(s.split(":", 1)[1].strip().rstrip("%"))
            except Exception:
                continue
            if state == "connected":
                return {"ssid": ssid, "signal": pct}
    return None


def _wifi_signal():
    """Sinyal Wi-Fi PC (Windows, netsh), cache 30 detik supaya tidak jalan tiap 2 detik."""
    global _wifi_cache
    if not IS_WIN:
        return None
    data, ts = _wifi_cache
    if time.time() - ts < 30:
        return data
    out = _run_ps("netsh wlan show interfaces", timeout=4)
    data = _parse_wifi_signal(out)
    _wifi_cache = (data, time.time())
    return data



def _ping_ms(host):
    """Ping ICMP (ping.exe Windows / ping Linux), rata-rata ms, atau None."""
    try:
        cmd = ["ping", "-n", "4", host] if IS_WIN else ["ping", "-c", "4", "-W", "2", host]
        out = subprocess.check_output(cmd, timeout=15, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="ignore")
    except Exception:
        return None
    m = re.search(r"(?:Average|Rata-rata)\s*=\s*(\d+)", out)
    if m:
        return int(m.group(1))
    vals = [int(v) for v in re.findall(r"(?:time|waktu)\s*[=<]\s*(\d+)\s*ms", out, flags=re.I)]
    if vals:
        return round(sum(vals) / len(vals))
    return None


def _http_ping_ms():
    """Cadangan kalau ICMP diblokir: waktu GET kecil ke Cloudflare, ms."""
    try:
        t0 = time.time()
        req = urllib.request.Request("https://speed.cloudflare.com/__down?bytes=0", headers={"User-Agent": "PCMonitorHUD"})
        with urllib.request.urlopen(req, timeout=8) as r:
            r.read(1)
        return round((time.time() - t0) * 1000)
    except Exception:
        return None


def _download_mbps(max_seconds=10):
    """Unduh dari Cloudflare sampai 10 detik / selesai, hitung Mbps dari byte yang terbaca."""
    try:
        req = urllib.request.Request("https://speed.cloudflare.com/__down?bytes=50000000", headers={"User-Agent": "PCMonitorHUD"})
        t0 = time.time()
        total = 0
        with urllib.request.urlopen(req, timeout=15) as r:
            while True:
                if time.time() - t0 >= max_seconds:
                    break
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                total += len(chunk)
        dt = max(time.time() - t0, 0.001)
        return round(total * 8 / dt / 1_000_000, 2) if total else None
    except Exception:
        return None


def _upload_mbps():
    """Unggah 5 MB ke Cloudflare, hitung Mbps. Upload sangat lambat bisa gagal (timeout) -> None."""
    try:
        data = b"\0" * 5_000_000
        req = urllib.request.Request("https://speed.cloudflare.com/__up", data=data, headers={"User-Agent": "PCMonitorHUD", "Content-Type": "application/octet-stream"}, method="POST")
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
        dt = max(time.time() - t0, 0.001)
        return round(5_000_000 * 8 / dt / 1_000_000, 2)
    except Exception:
        return None


def _speed_test():
    """Tes kecepatan sekali jalan (hanya saat tombol ditekan, bukan tiap refresh)."""
    ping = _ping_ms("8.8.8.8")
    if ping is None:
        ping = _ping_ms("1.1.1.1")
    if ping is None:
        ping = _http_ping_ms()
    return {
        "download_mbps": _download_mbps(),
        "upload_mbps": _upload_mbps(),
        "ping_ms": ping,
    }

_collect_cache = {}
# Patch 4.5: single-flight — satu pengambilan collect() berjalan dalam satu
# waktu. Request /api/data yang datang bersamaan menunggu hasil pengambilan
# yang sedang berjalan (lalu memakai cache-nya), bukan memulai pengambilan
# paralel yang menggandakan beban saat server sedang lambat.
_collect_lock = threading.Lock()


def _fps_off():
    """Dict fps saat FPS dimatikan (kartu disembunyikan / Mode Ringan)."""
    return {"value": 0, "game": "", "status": "off", "source": "",
            "error": "", "game_exe": "", "game_duration": 0, "game_icon": False}


def collect(skip=None):
    """Kumpulkan semua data dashboard.

    skip: frozenset/set berisi 'fps' dan/atau 'np' — bagian berat yang
    dilewati bila kartu terkait disembunyikan atau Mode Ringan aktif.
    Hasil di-cache 1 detik per kunci skip (perc153): pada refresh 0,5 detik,
    2 request hanya menghitung 1x — pemakaian CPU server turun ~setengah.
    """
    skip = frozenset(skip or ())
    _ent = _collect_cache.get(skip)
    if _ent is not None and time.time() - _ent[1] < 1.0:
        return _ent[0]
    with _collect_lock:
        # Cek lagi: thread lain mungkin baru saja mengisi cache selagi menunggu.
        _ent = _collect_cache.get(skip)
        if _ent is not None and time.time() - _ent[1] < 1.0:
            return _ent[0]
        return _collect_inner(skip)


def _collect_inner(skip):
    """Satu kali pengambilan penuh (dipanggil dari collect() dengan lock)."""
    global _prev_net, _prev_time, _collect_cache, _ULTRA_MONITORS
    now = time.time()
    # Patch 4.5: instrumentasi — ukur tiap bagian besar (hanya pencatatan,
    # tidak mengubah nilai sensor, timeout, atau urutan baca).
    _timings = {"psutil": 0, "network_storage": 0, "lhm": 0, "system": 0,
                "fans": 0, "now_playing": 0, "fps": 0, "power": 0, "total": 0}
    _t0 = time.perf_counter()
    _t_start = _t0
    cpu = psutil.cpu_percent(interval=None)
    per_core = psutil.cpu_percent(interval=None, percpu=True)
    try:
        freq = psutil.cpu_freq()
        freq_mhz = round(freq.current) if freq else None
    except Exception:
        freq_mhz = None
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    _timings["psutil"] = int(round((time.perf_counter() - _t0) * 1000)); _t0 = time.perf_counter()
    net = psutil.net_io_counters()
    if _prev_net is None:
        up_mbps = down_mbps = 0.0
    else:
        dt = max(now - _prev_time, 0.001)
        up_mbps = round((net.bytes_sent - _prev_net.bytes_sent) / dt / 1024 / 1024 * 8, 2)
        down_mbps = round((net.bytes_recv - _prev_net.bytes_recv) / dt / 1024 / 1024 * 8, 2)
    _prev_net, _prev_time = net, now

    disks = []
    win_types = _disk_types_windows() if IS_WIN else None
    for p in psutil.disk_partitions(all=False):
        try:
            u = psutil.disk_usage(p.mountpoint)
        except Exception:
            continue
        if IS_WIN:
            letter = p.device[0].upper() if len(p.device) >= 2 and p.device[1] == ":" else None
            dtype = win_types.get(letter) if letter else None
        else:
            dtype = _linux_disk_type(p.device)
        disks.append({
            "device": p.device, "mount": p.mountpoint,
            "total_gb": _gb(u.total), "used_gb": _gb(u.used),
            "free_gb": _gb(u.free), "percent": round(u.percent, 1),
            "type": dtype,
        })

    boot = psutil.boot_time()
    uptime_s = int(now - boot)
    _timings["network_storage"] = int(round((time.perf_counter() - _t0) * 1000)); _t0 = time.perf_counter()
    ultra = "ultra" in skip
    if ultra:
        # Mode Super Ringan (perc154): lewati semua sumber berat (nvidia-smi,
        # LHM web server, WMI/PowerShell suhu, EnumDisplaySettings, EnumWindows,
        # netsh WiFi). Hanya data dasar psutil yang tersisa: CPU, RAM, disk,
        # jaringan, waktu, daya estimasi.
        gpus = []
        temps = []
        cpu_temp = None
        gpu_util = None
        gpu_temp = None
        _model = _cpu_model_cache[0]
        _mons = []
        _aa = None
        _ra = []
        _wifi = None
        _fans = {"fans": [], "mobo_name": "", "mobo_temps": []}
        _np = None
        _fps = _fps_off()
        _pow = _power_info(cpu, None, _model, "", _ULTRA_MONITORS)
    else:
        gpus = _gpu_info()
        if not gpus and IS_WIN:
            # NVIDIA tidak ada (AMD/Intel) -> coba baca GPU dari LHM web server
            gpus = _gpu_from_lhm_web()
        temps = _temps()
        # Suhu CPU utama: cari label CPU/Core/ThermalZone dulu, kalau tidak ada pakai suhu pertama
        cpu_temp = None
        for t in temps:
            if any(k in t["label"].lower() for k in ("cpu", "core", "thermal", "package", "tctl", "tdie")):
                cpu_temp = t["temp_c"]
                break
        if cpu_temp is None and temps:
            cpu_temp = temps[0]["temp_c"]
        _timings["lhm"] = int(round((time.perf_counter() - _t0) * 1000)); _t0 = time.perf_counter()
        gpu_util = None
        gpu_temp = None
        if gpus:
            try:
                gpu_util = float(gpus[0]["util"])
                gpu_temp = float(gpus[0]["temp_c"])
            except Exception:
                pass
        _model = _cpu_model()
        _mons = _monitors()
        if _mons:
            _ULTRA_MONITORS = len(_mons)
        _aa = _active_app()
        _ra = _update_recent_apps(_aa)
        _wifi = _wifi_signal()
        _timings["system"] = int(round((time.perf_counter() - _t0) * 1000)); _t0 = time.perf_counter()
        _fans = _fans_mobo()
        _timings["fans"] = int(round((time.perf_counter() - _t0) * 1000)); _t0 = time.perf_counter()
        _np = _now_playing() if "np" not in skip else _now_playing_cache[0]
        _timings["now_playing"] = int(round((time.perf_counter() - _t0) * 1000)); _t0 = time.perf_counter()
        _fps = _fps_dict() if "fps" not in skip else _fps_off()
        _timings["fps"] = int(round((time.perf_counter() - _t0) * 1000)); _t0 = time.perf_counter()
        _pow = _power_info(cpu, gpu_util, _model,
                           gpus[0]["name"] if gpus else "", len(_mons))
        _timings["power"] = int(round((time.perf_counter() - _t0) * 1000))
    _timings["total"] = int(round((time.perf_counter() - _t_start) * 1000))
    # Patch 4.5: satu baris peringatan kalau satu collect melewati 2 detik,
    # menyebut bagian paling lambat — supaya macet berikutnya bisa dilacak.
    if _timings["total"] > 2000:
        _slow = max((k for k in _timings if k != "total"), key=lambda k: _timings[k])
        print(f"[KISA] collect lambat: {_timings['total']} ms (paling lambat: {_slow} {_timings[_slow]} ms)", flush=True)
    result = {
        "time": time.strftime("%H:%M:%S"),
        "host": platform.node(),
        "os": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "cpu": {
            "percent": round(cpu, 1), "cores": psutil.cpu_count(logical=False),
            "threads": psutil.cpu_count(logical=True), "freq_mhz": freq_mhz,
            "per_core": [round(x, 1) for x in per_core], "temp_c": cpu_temp,
            "model": _model,
        },
        "ram": {
            "percent": round(mem.percent, 1), "total_gb": _gb(mem.total),
            "used_gb": _gb(mem.used), "free_gb": _gb(mem.available),
            "swap_percent": round(swap.percent, 1),
        },
        "disks": disks,
        "network": {
            "up_mbps": up_mbps, "down_mbps": down_mbps,
            "sent_gb": _gb(net.bytes_sent), "recv_gb": _gb(net.bytes_recv),
        },
        "wifi": _wifi,
        "gpu": gpus,
        "gpu_util": gpu_util, "gpu_temp_c": gpu_temp,
        "temps": temps,
        "lhm_status": "off" if ultra else _lhm_status,
        "lhm_host": "" if ultra else _lhm_host,
        "top_processes": [],  # perc153: tidak dipakai dashboard (kartu dihapus) — process_iter tiap tick dihapus
        "monitors": _mons,
        "active_app": (None if not _aa else {
            "name": _aa["name"], "title": _aa["title"], "exe": _aa["exe"], "pid": _aa["pid"],
        }),
        "recent_apps": _ra,
        "now_playing": _np,
        "fps": _fps,
        "fans_mobo": _fans,
        "power": _pow,
        "uptime": {"hours": uptime_s // 3600, "minutes": (uptime_s % 3600) // 60},
        "timings_ms": _timings,
    }
    _collect_cache[skip] = (result, time.time())
    return result

# --- FPS game monitoring via MSI Afterburner (MAHM) — satu-satunya sumber ---
# Alat FPS cadangan lama DIHAPUS PERMANEN di perc179 (Patch 3.0): tidak ada
# lagi file .exe cadangan, tidak ada CSV fps, tidak ada fallback CSV.
# FPS hanya dari Afterburner (lihat _fps_afterburner di bawah).
_fps_ab_error = ""
_FPS_SKIP = {"dwm.exe", "explorer.exe", "ShellExperienceHost.exe", "SearchHost.exe",
             "TextInputHost.exe", "System", "Idle", "Registry", "csrss.exe",
             "winlogon.exe", "sihost.exe", "taskhostw.exe", "RuntimeBroker.exe",
             "ApplicationFrameHost.exe", "StartMenuExperienceHost.exe",
             "Widgets.exe", "PhoneExperienceHost.exe", "monitor_server.py"}

# --- FPS via MSI Afterburner (MAHM shared memory) ---
# Afterburner mempublikasikan data monitoring (termasuk framerate dari RTSS)
# lewat shared memory "MAHMSharedMemory" (SDK: MAHMSharedMemory.h v2.0).
# Layout header: dwSignature(4) dwVersion(4) dwHeaderSize(4) dwNumEntries(4)
# dwEntrySize(4) time(8) dwNumGpuEntries(4) dwGpuEntrySize(4).
# Entry (1324 B): 5x char[260] (szSrcName, szSrcUnits, szLocalizedSrcName,
# szLocalizedSrcUnits, szRecommendedFormat), lalu data f32 @1300,
# minLimit @1304, maxLimit @1308, dwFlags @1312, dwGpu @1316, dwSrcId @1320.
# MONITORING_SOURCE_ID_FRAMERATE = 0x50; data = FLT_MAX bila tidak tersedia.
# Dibaca via OpenFileMapping (hanya buka bila sudah ada — TIDAK pernah membuat
# mapping baru, jadi aman bila Afterburner tidak jalan). Satu-satunya sumber
# FPS sejak perc179. Syarat: Afterburner + RTSS jalan, monitoring
# "Framerate" aktif, dan ada game 3D yang sedang berjalan.
_MAHM_FRAMERATE_ID = 0x50
_MAHM_ENTRY_SIZE_MIN = 1324

def _fps_afterburner():
    """FPS dari MSI Afterburner (MAHM). Return float atau None."""
    global _fps_ab_error
    _fps_ab_error = ""
    if not IS_WIN:
        _fps_ab_error = "not_windows"
        return None
    try:
        import ctypes, struct
        kernel32 = ctypes.windll.kernel32
        # PENTING (perc126): tanpa restype/argtypes, ctypes memotong
        # pointer 64-bit jadi 32-bit (c_int) — alamat MapViewOfFile di
        # atas 4 GB jadi salah, baca shared memory gagal diam-diam.
        kernel32.OpenFileMappingW.restype = ctypes.c_void_p
        kernel32.OpenFileMappingW.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_wchar_p]
        kernel32.MapViewOfFile.restype = ctypes.c_void_p
        kernel32.MapViewOfFile.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_size_t]
        kernel32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        FILE_MAP_READ = 0x0004
        h = kernel32.OpenFileMappingW(FILE_MAP_READ, False, "MAHMSharedMemory")
        if not h:
            _fps_ab_error = "no_mapping"
            return None
        try:
            addr = kernel32.MapViewOfFile(h, FILE_MAP_READ, 0, 0, 0)
            if not addr:
                _fps_ab_error = "no_view"
                return None
            try:
                head = ctypes.string_at(addr, 20)
                sig = head[0:4]
                if sig not in (b"MAHM", b"MHAM"):
                    _fps_ab_error = "bad_sig:" + repr(sig[:4])
                    return None
                _ver, hdr_size, n_entries, entry_size = struct.unpack_from("<IIII", head, 4)
                if hdr_size < 20 or hdr_size > 4096:
                    _fps_ab_error = "bad_hdr:" + str(hdr_size)
                    return None
                if n_entries <= 0 or n_entries > 10000:
                    _fps_ab_error = "bad_n:" + str(n_entries)
                    return None
                if entry_size < _MAHM_ENTRY_SIZE_MIN:
                    _fps_ab_error = "bad_entry_size:" + str(entry_size)
                    return None
                FLT_MAX = 3.4028235e38
                for i in range(n_entries):
                    off = hdr_size + i * entry_size
                    ent = ctypes.string_at(addr + off, _MAHM_ENTRY_SIZE_MIN)
                    src_id = struct.unpack_from("<I", ent, 1320)[0]
                    if src_id == _MAHM_FRAMERATE_ID:
                        fps = struct.unpack_from("<f", ent, 1300)[0]
                        if fps and 0.0 < fps < 10000.0 and fps < FLT_MAX:
                            return round(float(fps), 1)
                        # Entri framerate ada tapi nilainya belum valid
                        # (mis. FLT_MAX) — lanjut cari entri lain.
                        _fps_ab_error = "invalid_value:" + str(fps)
                        continue
                if not _fps_ab_error:
                    _fps_ab_error = "no_framerate_entry"
                return None
            finally:
                kernel32.UnmapViewOfFile(addr)
        finally:
            kernel32.CloseHandle(h)
    except Exception as e:
        _fps_ab_error = "exc:" + str(e)[:120]
        return None

def _fps_debug():
    """Diagnostik FPS untuk /api/fps_debug (hanya Afterburner, perc179)."""
    ab = _fps_afterburner()
    return {
        "afterburner": ab,
        "afterburner_error": _fps_ab_error,
        "autostart_afterburner": dict(_AB_AUTOSTART),
        "autostart_lhm": dict(_LHM_AUTOSTART),
        "lhm_webserver": "on" if _lhm_webserver_live() else "off",
        "ultralite": _ULTRA_MODE,
    }


# --- Patch 4.1 (S153): status aplikasi pendukung untuk daftar baca-saja di HP ---
_support_apps_cache = ({}, 0.0)


def _win_program_paths(*rels):
    """Kandidat path program Windows; kosong di luar Windows."""
    if not IS_WIN:
        return []
    roots = []
    for _env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA", "APPDATA"):
        _v = os.environ.get(_env)
        if _v:
            roots.append(_v)
    out = []
    for _r in roots:
        for _rel in rels:
            out.append(os.path.join(_r, _rel))
    for _rel in rels:
        out.append(os.path.join("C:\\", _rel))
    return out


def _proc_running(*names):
    try:
        want = {n.lower() for n in names}
        for _p in psutil.process_iter(["name"]):
            try:
                if (_p.info.get("name") or "").lower() in want:
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _mahm_present():
    """True bila shared memory MAHM Afterburner ada (Afterburner jalan)."""
    if not IS_WIN:
        return False
    _fps_afterburner()
    return _fps_ab_error not in ("not_windows", "no_mapping")


def _support_apps():
    """Status terpasang aplikasi pendukung (Patch 4.1, S153).

    Dipakai daftar baca-saja di halaman Dukungan dashboard (HP): tiap
    kelompok S153 — python / afterburner / lhm / nocturne / ffmpeg.
    "Terpasang" = file program ada di PC, atau aplikasinya sedang jalan
    (proses / MAHM / web server LHM) — jadi aplikasi yang di-install di
    lokasi lain tetap terdeteksi. Untuk Nocturne sengaja TIDAK memakai
    sesi GSMTC: GSMTC hanya ada saat lagu sedang diputar, bukan bukti
    aplikasi ter-install. Python selalu True: server ini sendiri jalan
    di atas Python + psutil/winsdk/segno.
    Di-cache 5 detik; semua deteksi dibungkus try/except supaya endpoint
    ini tidak pernah mematikan server (termasuk di Linux tanpa semua
    komponen Windows).
    """
    global _support_apps_cache
    now = time.time()
    if now - _support_apps_cache[1] < 5 and _support_apps_cache[0]:
        return _support_apps_cache[0]
    out = {"python": True, "afterburner": False, "lhm": False,
           "nocturne": False, "ffmpeg": False}
    try:
        out["afterburner"] = (
            any(os.path.exists(_p) for _p in _win_program_paths(
                os.path.join("MSI Afterburner", "MSIAfterburner.exe")))
            or _mahm_present()
            or _proc_running("MSIAfterburner.exe"))
    except Exception:
        pass
    try:
        out["lhm"] = (
            any(os.path.exists(_p) for _p in _win_program_paths(
                os.path.join("LibreHardwareMonitor", "LibreHardwareMonitor.exe"),
                os.path.join("PCMonitorHUD", "tools", "LibreHardwareMonitor",
                             "LibreHardwareMonitor.exe")))
            or _lhm_status in ("ok", "auth")
            or _proc_running("LibreHardwareMonitor.exe"))
    except Exception:
        pass
    try:
        out["nocturne"] = (
            any(os.path.exists(_p) for _p in _win_program_paths(
                os.path.join("Nocturne Music", "nocturne-app.exe"),
                os.path.join("Nocturne.Music", "nocturne-app.exe")))
            or _proc_running("nocturne-app.exe"))
    except Exception:
        pass
    try:
        out["ffmpeg"] = shutil.which("ffmpeg") is not None
    except Exception:
        pass
    _support_apps_cache = (out, now)
    return out


# --- Patch 4.6 (S157 Cara 1): Periksa Pembaruan dari dalam aplikasi -------
# PERMANEN: fitur ini bagian tetap KISA, terbawa ke patch berikutnya.
# Alur: GET /api/check_update (rilis GitHub terbaru, cache 1 jam) ->
# POST /api/download_update (server mengunduh aset ke folder sementara,
# progres dilacak) -> GET /api/download_progress (persen nyata) ->
# PC: POST /api/install_update (jalankan installer, aplikasi menutup diri
# dulu — kalau tidak, file terkunci seperti instal 3.9) / HP: GET
# /api/update_file (APK diambil HP lewat bridge KisaApp.downloadApk).
# Semua kegagalan jaringan ditangkap -> JSON netral, tidak pernah traceback.
_APP_QUIT_FN = None  # diisi kisa_app.py (start_server) dengan _quit_app
_update_check_cache = (None, 0.0)
_update_dl = {"state": "idle", "pct": 0, "downloaded": 0, "total": 0,
              "name": None, "path": None, "error": None}
_update_dl_lock = threading.Lock()
_UPDATE_DL_DIR = None
_UPDATE_GH_URL = "https://api.github.com/repos/kirisaki8432/KISA/releases/latest"


def _upd_parse_version(s):
    """'v4.6' / '4.6' -> (4, 6, 0). Bagian non-angka dihitung 0."""
    try:
        s = (s or "").strip()
        if s[:1].lower() == "v":
            s = s[1:]
        parts = []
        for p in s.split("."):
            try:
                parts.append(int(p))
            except ValueError:
                parts.append(0)
        while len(parts) < 3:
            parts.append(0)
        return tuple(parts[:3])
    except Exception:
        return (0, 0, 0)


def _upd_github_latest():
    """Ambil rilis terbaru GitHub (dict) atau None bila gagal. Timeout 10 dtk."""
    try:
        req = urllib.request.Request(
            _UPDATE_GH_URL,
            headers={"User-Agent": "KISA-Updater",
                     "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode("utf-8", "ignore"))
    except Exception:
        return None


def _upd_releases_page_latest():
    """Jalur cadangan (Patch 4.7, S161 Cara 2): baca halaman rilis GitHub
    biasa bila API (api.github.com) gagal — halaman ini tidak kena batas
    API. Ikut redirect ke /releases/tag/vX.Y, lalu bentuk dict yang SAMA
    persis seperti hasil API (tag_name, name, body, assets) supaya loop
    aset di _update_check bisa dipakai ulang. Nama aset mengikuti aturan
    penamaan (KISA-Setup-X.Y.exe, KISA-X.Y.apk); size 0 bila tidak
    diketahui. Kembalikan None bila gagal."""
    try:
        req = urllib.request.Request(
            "https://github.com/kirisaki8432/KISA/releases/latest",
            headers={"User-Agent": "KISA-Updater"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            final_url = resp.geturl()
            html = resp.read().decode("utf-8", "ignore")
        tag = ""
        m = re.search(r"/releases/tag/(v[0-9][0-9A-Za-z.\-]*)", final_url)
        if m:
            tag = m.group(1)
        if not tag:
            m2 = re.search(r"/kirisaki8432/KISA/releases/tag/(v[0-9][0-9A-Za-z.\-]*)", html)
            if m2:
                tag = m2.group(1)
        if not tag:
            return None
        latest = tag[1:] if tag[:1].lower() == "v" else tag
        assets = []
        for name in ("KISA-Setup-" + latest + ".exe", "KISA-" + latest + ".apk"):
            assets.append({
                "name": name,
                "size": 0,
                "browser_download_url": "https://github.com/kirisaki8432/KISA/releases/download/" + tag + "/" + name,
            })
        return {
            "tag_name": tag,
            "name": "KISA Patch " + latest,
            "body": "",
            "assets": assets,
        }
    except Exception:
        return None


def _update_check(force=False):
    """Hasil cek update (dict JSON-siap). Cache 1 jam kecuali force=True.
    Tidak pernah melempar: gagal jaringan -> {"ok": False}."""
    global _update_check_cache
    now = time.time()
    try:
        cached, ts = _update_check_cache
        if (not force) and cached and (now - ts) < 3600:
            return cached
        rel = _upd_github_latest()
        via = "api"
        if not rel:
            # Patch 4.7 (S161 Cara 2): API gagal -> jalur cadangan
            # halaman rilis (tidak kena batas API).
            rel = _upd_releases_page_latest()
            via = "releases_page"
        if not rel:
            return {"ok": False, "error": "check_failed",
                    "installed": KISA_VERSION,
                    "installed_tag": "v" + KISA_VERSION}
        tag = str(rel.get("tag_name") or "")
        latest = tag[1:] if tag[:1].lower() == "v" else tag
        assets = []
        for a in (rel.get("assets") or []):
            try:
                assets.append({"name": str(a.get("name") or ""),
                               "size": int(a.get("size") or 0),
                               "url": str(a.get("browser_download_url") or "")})
            except Exception:
                continue
        out = {"ok": True,
               "installed": KISA_VERSION, "installed_tag": "v" + KISA_VERSION,
               "latest": latest, "latest_tag": tag,
               "latest_name": str(rel.get("name") or ("KISA Patch " + latest)),
               "body": str(rel.get("body") or ""),
               "update_available": _upd_parse_version(latest) > _upd_parse_version(KISA_VERSION),
               "via": via,
               "assets": assets,
               "checked_at": int(now)}
        _update_check_cache = (out, now)
        return out
    except Exception:
        return {"ok": False, "error": "check_failed",
                "installed": KISA_VERSION, "installed_tag": "v" + KISA_VERSION}


def _update_dl_set(**kw):
    with _update_dl_lock:
        _update_dl.update(kw)


def _update_download_worker(url, name, total):
    """Unduh aset GitHub ke folder sementara; progres di _update_dl."""
    global _UPDATE_DL_DIR
    try:
        import tempfile
        if not _UPDATE_DL_DIR:
            _UPDATE_DL_DIR = tempfile.mkdtemp(prefix="kisa_update_")
        dest = os.path.join(_UPDATE_DL_DIR, name)
        req = urllib.request.Request(url, headers={"User-Agent": "KISA-Updater"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            total = int(resp.headers.get("Content-Length") or total or 0)
            _update_dl_set(state="downloading", pct=0, downloaded=0,
                           total=total, name=name, path=dest, error=None)
            got = 0
            with open(dest, "wb") as fh:
                while True:
                    chunk = resp.read(1024 * 256)
                    if not chunk:
                        break
                    fh.write(chunk)
                    got += len(chunk)
                    pct = int(got * 100 / total) if total else 0
                    _update_dl_set(downloaded=got, pct=min(100, pct))
        _update_dl_set(state="done", pct=100, downloaded=got, total=total or got)
    except Exception as e:
        _update_dl_set(state="error", error="download_failed")
        try:
            print("KISA update: unduhan gagal -", e)
        except Exception:
            pass


def _update_start_download(asset_name):
    """Mulai unduh aset (nama harus ada di hasil cek terakhir). Bila sedang
    berjalan, kembalikan progres saat ini."""
    try:
        with _update_dl_lock:
            cur = dict(_update_dl)
        if cur.get("state") == "downloading":
            return {"ok": True, "state": "downloading", "pct": cur.get("pct", 0)}
        data = _update_check()
        assets = (data.get("assets") or []) if data.get("ok") else []
        want = None
        for a in assets:
            if a.get("name") == asset_name:
                want = a
                break
        if not want or not want.get("url"):
            return {"ok": False, "error": "asset_not_found"}
        _update_dl_set(state="downloading", pct=0, downloaded=0,
                       total=int(want.get("size") or 0), name=asset_name,
                       path=None, error=None)
        threading.Thread(target=_update_download_worker,
                         args=(want["url"], asset_name, int(want.get("size") or 0)),
                         daemon=True, name="kisa-update-dl").start()
        return {"ok": True, "state": "downloading", "pct": 0}
    except Exception:
        return {"ok": False, "error": "download_failed"}


def _update_install(asset_name):
    """PC: jalankan installer yang sudah diunduh, lalu tutup aplikasi
    dengan bersih. Kembalikan dict JSON-siap (ok/error)."""
    try:
        with _update_dl_lock:
            cur = dict(_update_dl)
        if cur.get("state") != "done" or not cur.get("path"):
            return {"ok": False, "error": "not_downloaded"}
        if asset_name and cur.get("name") != asset_name:
            return {"ok": False, "error": "not_downloaded"}
        path = cur["path"]
        if not os.path.exists(path):
            return {"ok": False, "error": "not_downloaded"}
        if os.name != "nt":
            return {"ok": False, "error": "unsupported_platform"}
        # Jalankan installer (wizard terlihat, tanpa argumen senyap),
        # lalu tutup aplikasi setelah jeda singkat supaya file tidak
        # terkunci saat installer mengganti KISA.exe.
        try:
            subprocess.Popen([path],
                             creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        except Exception:
            try:
                os.startfile(path)
            except Exception:
                return {"ok": False, "error": "launch_failed"}

        def _quit_later():
            try:
                time.sleep(1.5)
            except Exception:
                pass
            try:
                fn = _APP_QUIT_FN
            except Exception:
                fn = None
            if fn:
                try:
                    fn()
                    return
                except Exception:
                    pass
            try:
                os._exit(0)
            except Exception:
                pass

        threading.Thread(target=_quit_later, daemon=True,
                         name="kisa-update-quit").start()
        return {"ok": True}
    except Exception:
        return {"ok": False, "error": "install_failed"}


# --- Auto-start MSI Afterburner + RTSS + LibreHardwareMonitor (perc150) ---
# User tidak mau lagi membuka aplikasi ini manual: begitu server dashboard
# dijalankan (Jalankan_di_PC.bat), server menyalakan otomatis aplikasi yang
# SUDAH ter-install di PC. Afterburner/RTSS TIDAK dibundel (proprietary MSI,
# harus di-install dengan driver + registry) dan LHM TIDAK dibundel (portable,
# lokasi simpan user tidak tercatat) — fitur ini hanya me-launch yang sudah
# ada. Kalau tidak ketemu, status "not_found", server tetap jalan, kartu FPS
# disembunyikan (FPS hanya dari Afterburner), data LHM kosong seperti biasa.
# Dipanggil SEKALI saat server mulai, bukan tiap tick/API call.
# Semua kegagalan ditangani tanpa crash (try/except di tiap langkah).
_AB_AUTOSTART = {"afterburner": "unknown", "rtss": "unknown", "error": ""}
_LHM_AUTOSTART = {"lhm": "unknown", "webserver": "unknown",
                          "port": None, "error": ""}
_AUTOSTART_DONE = False
# --- Mode Super Ringan (perc154) ---
# _ULTRA_MODE: True bila request /api/data terakhir memakai ultralite=1.
# Server mengikuti mode dashboard terakhir: bila True, collect() melewati
# LHM/FPS/NP/monitor/app/WiFi/GPU, _accumulate_power() tidak memanggil
# fallback berat (PowerShell/LHM/nvidia-smi), dan auto-start
# LHM/Afterburner tidak dipicu. _ULTRA_MONITORS: jumlah monitor terakhir
# yang diketahui (default 1) supaya estimasi daya di mode ini tetap
# memakai jumlah monitor yang benar.
_ULTRA_MODE = False
_ULTRA_MONITORS = 1
_AUTOSTART_TRIGGERED = False
_AUTOSTART_LOCK = threading.Lock()


def _proc_running(exe_name):
    """True bila proses bernama exe_name sedang jalan (psutil, case-insensitive)."""
    try:
        want = (exe_name or "").lower()
        for p in psutil.process_iter(["name"]):
            try:
                if (p.info.get("name") or "").lower() == want:
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _reg_install_location(display_substr):
    """InstallLocation dari registry uninstall (Windows) untuk aplikasi yang
    DisplayName-nya mengandung display_substr. Return '' bila tidak ketemu
    (mis. bukan Windows, atau aplikasi portable tanpa entri uninstall)."""
    try:
        import winreg
    except Exception:
        return ""
    subs = (display_substr or "").lower()
    bases = [
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for hive, key_path in bases:
        try:
            key = winreg.OpenKey(hive, key_path)
        except Exception:
            continue
        try:
            n = winreg.QueryInfoKey(key)[0]
            for i in range(min(n, 1000)):
                try:
                    sub = winreg.EnumKey(key, i)
                    sk = winreg.OpenKey(key, sub)
                    try:
                        name, _ = winreg.QueryValueEx(sk, "DisplayName")
                    except Exception:
                        name = ""
                    if name and subs in str(name).lower():
                        for val in ("InstallLocation", "DisplayIcon"):
                            try:
                                v, _ = winreg.QueryValueEx(sk, val)
                            except Exception:
                                continue
                            v = str(v or "").strip().strip('"')
                            if v:
                                return v
                    winreg.CloseKey(sk)
                except Exception:
                    continue
        except Exception:
            pass
        try:
            winreg.CloseKey(key)
        except Exception:
            pass
    return ""


def _find_app_exe(exe_name, roots, reg_names, dir_hints):
    """Cari file exe. Return str path atau ''.

    roots: folder yang dicek langsung (<root>/<exe_name>) DAN di-scan 1 level
      (entri folder di dalamnya yang namanya mengandung salah satu dir_hints).
    reg_names: DisplayName registry yang dicari InstallLocation-nya.
    """
    from pathlib import Path as _P
    try:
        for r in roots:
            try:
                p = _P(r) / exe_name
                if p.is_file():
                    return str(p)
            except Exception:
                continue
        for rn in reg_names:
            loc = _reg_install_location(rn)
            if loc:
                for cand in (_P(loc) / exe_name, _P(loc)):
                    try:
                        if cand.is_file() and cand.name.lower() == exe_name.lower():
                            return str(cand)
                    except Exception:
                        continue
        for r in roots:
            try:
                base = _P(r)
                if not base.is_dir():
                    continue
                entries = list(base.iterdir())
            except Exception:
                continue
            for e in entries:
                try:
                    if not e.is_dir():
                        continue
                    el = e.name.lower()
                    if any(h in el for h in dir_hints):
                        p = e / exe_name
                        if p.is_file():
                            return str(p)
                except Exception:
                    continue
    except Exception:
        pass
    return ""


def _default_search_roots():
    """Folder-folder umum tempat aplikasi Windows dicari (daftar Path)."""
    import os
    from pathlib import Path as _P
    roots = []
    try:
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        up = os.environ.get("USERPROFILE", "")
        roots += [_P(pf86), _P(pf), _P("C:\\")]
        if up:
            roots += [_P(up) / "Desktop", _P(up) / "Downloads",
                      _P(up) / "Documents"]
        roots += [BASE_DIR, BASE_DIR.parent]
    except Exception:
        pass
    return roots


def _launch_detached(path):
    """Jalankan exe di background tanpa blokir server.
    Return (True, '') bila proses tetap hidup, (False, err) bila gagal."""
    import os
    try:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        proc = subprocess.Popen([str(path)], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, creationflags=flags)
    except Exception as e:
        return False, "launch_exc:" + str(e)[:100]
    try:
        time.sleep(0.5)
        rc = proc.poll()
    except Exception:
        rc = None
    if rc is not None:
        return False, "exit:" + str(rc)
    return True, ""


def _autostart_one(exe_name, roots, reg_names, dir_hints):
    """Satu aplikasi: 'running' (sudah jalan) / 'started' (baru dinyalakan) /
    'not_found' (exe tidak ketemu) / 'error' (gagal launch). Return (status, err)."""
    try:
        if _proc_running(exe_name):
            return "running", ""
        path = _find_app_exe(exe_name, roots, reg_names, dir_hints)
        if not path:
            return "not_found", ""
        ok, err = _launch_detached(path)
        if ok:
            return "started", ""
        return "error", err
    except Exception as e:
        return "error", str(e)[:100]


# --- LHM Remote Web Server otomatis (perc151) ---
# Riset (repo LibreHardwareMonitor, source code — lihat
# research_lhm_webserver.md):
# - Setting di LibreHardwareMonitor.config, di folder yang sama dengan
#   LibreHardwareMonitor.exe (MainForm.cs: _settings.Load(
#   Path.ChangeExtension(Application.ExecutablePath, ".config"))).
# - Format XML appSettings: <configuration><appSettings>
#   <add key="runWebServerMenuItem" value="true" /> ... </appSettings></configuration>.
# - Toggle: key "runWebServerMenuItem", bool "true"/"false"
#   (UserOption("runWebServerMenuItem", false, ...)); saat LHM mulai, handler
#   Changed langsung dipanggil, jadi web server ikut nyala bila true.
# - Port: key "listenerPort", int, default 8085. IP default "?" -> "+" (semua
#   interface), jadi tidak perlu set listenerIp.
# - TIDAK ADA argumen command-line (Program.Main tanpa args) — file config
#   satu-satunya cara otomatis. Bukan registry.
# - LHM menulis ulang config saat keluar (SaveConfiguration) -> JANGAN edit
#   config selagi LHM jalan; tulis HANYA saat LHM mati (atau setelah dimatikan
#   graceful via taskkill tanpa /F).
# - Berlaku untuk varian standar (net472) DAN .NET 10 (net10.0-windows):
#   keduanya aplikasi Windows Forms yang sama (TargetFrameworks
#   net472;net10.0-windows). Avalonia artifact terpisah tanpa web server.
_LHM_WS_KEY = "runWebServerMenuItem"
_LHM_WS_PORT_KEY = "listenerPort"
_LHM_WS_PORT = 8085


def _lhm_config_path(lhm_exe):
    """Path LibreHardwareMonitor.config di folder yang sama dengan exe."""
    try:
        from pathlib import Path as _P
        return str(_P(lhm_exe).parent / "LibreHardwareMonitor.config")
    except Exception:
        return ""


def _lhm_enable_webserver(lhm_exe):
    """Tulis runWebServerMenuItem=true (+ listenerPort=8085 bila belum ada)
    ke LibreHardwareMonitor.config di folder exe. HANYA dipanggil saat LHM
    MATI (LHM menimpa config saat keluar).
    Return (status, detail, port). Status: "already_on" | "configured" |
    "error". Idempotent: tidak menulis ulang bila sudah benar; semua key lain
    dipertahankan apa adanya; listenerPort yang sudah ada nilainya dibiarkan
    (tidak menimpa port custom yang disengaja)."""
    import os
    try:
        import copy as _copy
        import xml.etree.ElementTree as _ET
    except Exception as e:
        return "error", "xml_import:" + str(e)[:60], None
    try:
        cfg = _lhm_config_path(lhm_exe)
        if not cfg:
            return "error", "no_config_path", None
        entries = []
        others = []
        valid = False
        if os.path.isfile(cfg):
            try:
                tree = _ET.parse(cfg)
                root = tree.getroot()
                apps = None
                if root is not None and root.tag == "configuration":
                    apps = root.find("appSettings")
                if apps is not None:
                    valid = True
                    seen = set()
                    for add in apps.findall("add"):
                        k = add.get("key")
                        v = add.get("value")
                        if k is None or v is None or k in seen:
                            continue
                        seen.add(k)
                        entries.append((k, v))
                    for child in root:
                        if child.tag != "appSettings":
                            others.append(_copy.deepcopy(child))
            except Exception:
                valid = False
        if not valid and os.path.isfile(cfg):
            # File rusak (LHM sendiri akan menghapusnya saat Load) — backup
            # dulu supaya setting user tidak hilang, lalu tulis baru.
            try:
                bak = cfg + ".bad"
                n = 1
                while os.path.exists(bak):
                    n += 1
                    bak = cfg + ".bad" + str(n)
                os.replace(cfg, bak)
            except Exception:
                pass
            entries = []
            others = []
        vals = dict(entries)
        ws_on = str(vals.get(_LHM_WS_KEY, "")).strip() == "true"
        port_raw = str(vals.get(_LHM_WS_PORT_KEY, "")).strip()
        port = None
        try:
            port = int(port_raw) if port_raw else None
        except Exception:
            port = None
        if ws_on:
            # Web server sudah aktif; port yang sudah ada (bila ada) dibiarkan
            # apa adanya — tidak pernah menimpa port custom yang disengaja.
            return "already_on", "", (port if port else _LHM_WS_PORT)
        vals[_LHM_WS_KEY] = "true"
        if _LHM_WS_PORT_KEY not in vals:
            vals[_LHM_WS_PORT_KEY] = str(_LHM_WS_PORT)
            port = _LHM_WS_PORT
        order = [k for k, _ in entries if k in vals]
        for k in vals:
            if k not in order:
                order.append(k)
        root = _ET.Element("configuration")
        apps = _ET.SubElement(root, "appSettings")
        for k in order:
            _ET.SubElement(apps, "add", {"key": k, "value": vals[k]})
        for child in others:
            root.append(child)
        data = _ET.tostring(root, encoding="utf-8", xml_declaration=True)
        if not data.startswith(b"\xef\xbb\xbf"):
            data = b"\xef\xbb\xbf" + data
        tmp = cfg + ".tmp"
        try:
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, cfg)
        except Exception as e:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass
            return "error", "write:" + str(e)[:60], port
        return "configured", "", port
    except Exception as e:
        return "error", str(e)[:80], None


def _lhm_webserver_live(timeout=0.8):
    """True bila ada host yang menjawab http://<host>:8085/data.json."""
    try:
        for host in _lhm_hosts():
            try:
                with urllib.request.urlopen("http://%s:8085/data.json" % host,
                                            timeout=timeout) as r:
                    if r.status == 200:
                        return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _lhm_restart_with_webserver(lhm_exe):
    """LHM sedang jalan tapi web server mati: tutup graceful (taskkill tanpa
    /F -> WM_CLOSE -> LHM simpan config lalu keluar), tulis config, luncurkan
    lagi. Return (lhm_status, ws_status, port, err). Tidak pernah force-kill:
    bila LHM tidak keluar dalam batas waktu, biarkan apa adanya."""
    import os
    try:
        import subprocess as _sp
        try:
            _sp.run(["taskkill", "/IM", "LibreHardwareMonitor.exe"],
                    stdout=_sp.DEVNULL, stderr=_sp.DEVNULL, timeout=15)
        except Exception:
            pass
        for _ in range(16):
            if not _proc_running("LibreHardwareMonitor.exe"):
                break
            time.sleep(0.5)
        if _proc_running("LibreHardwareMonitor.exe"):
            return "running", "off", None, "close_timeout"
        ws, werr, port = _lhm_enable_webserver(lhm_exe)
        ok, err = _launch_detached(lhm_exe)
        if not ok:
            return "error", "off", port, err
        time.sleep(2.5)
        if _lhm_webserver_live():
            return "restarted", "on", port, werr
        return "restarted", "configured", port, werr
    except Exception as e:
        return "error", "off", None, str(e)[:80]


def _ensure_afterburner():
    """Auto-start MSI Afterburner + RTSS sekali. Status di _AB_AUTOSTART."""
    global _AB_AUTOSTART
    if not IS_WIN:
        _AB_AUTOSTART = {"afterburner": "not_windows", "rtss": "not_windows",
                         "error": ""}
        return
    import os
    from pathlib import Path as _P
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    common = _default_search_roots()
    ab_roots = [_P(pf86) / "MSI Afterburner", _P(pf) / "MSI Afterburner"] + common
    rt_roots = [_P(pf86) / "RivaTuner Statistics Server",
                _P(pf) / "RivaTuner Statistics Server"] + common
    st_ab, err_ab = _autostart_one("MSIAfterburner.exe", ab_roots,
                                   ["MSI Afterburner"], ["msi afterburner"])
    st_rt, err_rt = _autostart_one("RTSS.exe", rt_roots,
                                   ["RivaTuner Statistics Server"], ["rivatuner"])
    err = "; ".join(x for x in (err_ab, err_rt) if x)
    _AB_AUTOSTART = {"afterburner": st_ab, "rtss": st_rt, "error": err}


def _ensure_lhm():
    """Auto-start LibreHardwareMonitor sekali + aktifkan otomatis Remote Web
    Server-nya (port 8085). Status di _LHM_AUTOSTART.

    LHM portable (tidak ada installer) — lokasinya dicari di Program Files,
    drive C:, Desktop/Downloads/Documents (folder + langsung file exe), folder
    dashboard (BASE_DIR) dan folder induknya, folder hasil download
    Setup_Otomatis.bat (%APPDATA%/PCMonitorHUD/tools/LibreHardwareMonitor),
    plus scan 1 level dan registry.
    Remote Web Server diaktifkan dengan menulis runWebServerMenuItem=true ke
    LibreHardwareMonitor.config di folder exe SEBELUM LHM diluncurkan (riset
    perc151: tidak ada argumen command-line; LHM membaca config saat mulai
    dan langsung menyalakan web server). Bila LHM sudah jalan tapi web
    server-nya mati, LHM ditutup graceful lalu diluncurkan lagi dengan config
    yang sudah diperbaiki. Config TIDAK pernah diedit selagi LHM jalan."""
    global _LHM_AUTOSTART
    if not IS_WIN:
        _LHM_AUTOSTART = {"lhm": "not_windows", "webserver": "not_windows",
                          "port": None, "error": ""}
        return
    import os
    from pathlib import Path as _P
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    up = os.environ.get("USERPROFILE", "")
    roots = [_P(pf) / "LibreHardwareMonitor",
             _P(pf86) / "LibreHardwareMonitor",
             _P(r"C:\LibreHardwareMonitor"),
             BASE_DIR / "LibreHardwareMonitor", BASE_DIR,
             BASE_DIR.parent / "LibreHardwareMonitor", BASE_DIR.parent]
    if up:
        for sub in ("Desktop", "Downloads", "Documents"):
            roots.append(_P(up) / sub / "LibreHardwareMonitor")
            roots.append(_P(up) / sub)
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        roots.append(_P(appdata) / "PCMonitorHUD" / "tools" / "LibreHardwareMonitor")
    roots += _default_search_roots()
    # Kasus 1: LHM sudah jalan.
    if _proc_running("LibreHardwareMonitor.exe"):
        if _lhm_webserver_live():
            _LHM_AUTOSTART = {"lhm": "running", "webserver": "on",
                              "port": _LHM_WS_PORT, "error": ""}
            return
        path = _find_app_exe("LibreHardwareMonitor.exe", roots,
                             ["LibreHardwareMonitor"], ["librehardwaremonitor"])
        if not path:
            _LHM_AUTOSTART = {"lhm": "running", "webserver": "off",
                              "port": None, "error": "exe_not_found_for_restart"}
            return
        st, ws, port, err = _lhm_restart_with_webserver(path)
        _LHM_AUTOSTART = {"lhm": st, "webserver": ws, "port": port, "error": err}
        return
    # Kasus 2: LHM belum jalan — tulis config dulu, baru luncurkan.
    path = _find_app_exe("LibreHardwareMonitor.exe", roots,
                         ["LibreHardwareMonitor"], ["librehardwaremonitor"])
    if not path:
        _LHM_AUTOSTART = {"lhm": "not_found", "webserver": "off",
                          "port": None, "error": ""}
        return
    ws, werr, port = _lhm_enable_webserver(path)
    if ws == "error":
        # Config gagal ditulis — tetap luncurkan LHM (web server mungkin
        # sudah aktif dari config lama); jangan blokir dashboard.
        ok, err = _launch_detached(path)
        _LHM_AUTOSTART = {"lhm": "started" if ok else "error",
                          "webserver": "off", "port": port,
                          "error": (werr + "; " + err).strip("; ")}
        return
    ok, err = _launch_detached(path)
    if not ok:
        _LHM_AUTOSTART = {"lhm": "error", "webserver": "off",
                          "port": port, "error": err}
        return
    time.sleep(2.5)
    if _lhm_webserver_live():
        _LHM_AUTOSTART = {"lhm": "started", "webserver": "on",
                          "port": port, "error": werr}
    else:
        _LHM_AUTOSTART = {"lhm": "started", "webserver": "configured",
                          "port": port, "error": werr}


def _ensure_autostart():
    """Auto-start Afterburner + RTSS + LHM sekali saat server mulai."""
    global _AUTOSTART_DONE
    if _AUTOSTART_DONE:
        return
    _AUTOSTART_DONE = True
    try:
        _ensure_afterburner()
    except Exception:
        pass
    try:
        _ensure_lhm()
    except Exception:
        pass


def _maybe_autostart():
    """Pemicu lazy auto-start (perc154): jalankan _ensure_autostart() di
    thread latar sekali, hanya bila dashboard TIDAK dalam Mode Super Ringan.
    Dipanggil dari handler /api/data (dan /api/fps_debug) saat request bukan
    ultralite. Tidak memblokir respons data (LHM punya sleep 2,5 detik).
    Bila dashboard selalu Mode Super Ringan, auto-start tidak pernah jalan —
    itulah tujuannya: PC super ringan tidak dibebani aplikasi berat.
    Proses yang sudah jalan tidak dimatikan (hanya tidak dipakai/dimulai)."""
    global _AUTOSTART_TRIGGERED
    if _ULTRA_MODE:
        # Mode Super Ringan: jangan nyalakan aplikasi berat (LHM/Afterburner)
        # apa pun yang memanggil fungsi ini (termasuk /api/fps_debug).
        return
    if _AUTOSTART_TRIGGERED:
        return
    with _AUTOSTART_LOCK:
        if _AUTOSTART_TRIGGERED:
            return
        _AUTOSTART_TRIGGERED = True
    try:
        threading.Thread(target=_ensure_autostart, daemon=True).start()
    except Exception:
        pass

_game_info_cache = {"exe": None, "name": None, "exe_path": None, "started": 0}

def _main_window_title(pid):
    """Judul jendela utama (visible, top-level) milik pid. Return str/''."""
    if not IS_WIN or not pid:
        return ""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        user32.EnumWindows.restype = wintypes.BOOL
        user32.EnumWindows.argtypes = [wintypes.WNDENUMPROC, wintypes.LPARAM]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        titles = []
        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def _cb(hwnd, _):
            if not user32.IsWindowVisible(hwnd):
                return True
            p = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
            if p.value != pid:
                return True
            ln = user32.GetWindowTextLengthW(hwnd)
            if ln <= 0:
                return True
            buf = ctypes.create_unicode_buffer(ln + 1)
            user32.GetWindowTextW(hwnd, buf, ln + 1)
            t = (buf.value or "").strip()
            if t:
                titles.append(t)
            return True
        user32.EnumWindows(_cb, 0)
        return titles[0] if titles else ""
    except Exception:
        return ""

def _fps_game_info(exe_name):
    """Nama ramah + durasi game dari nama exe.
    Cache per exe (nama/path/started); durasi dihitung fresh tiap panggil.
    Return {name, exe_path, started, duration} atau None."""
    if not IS_WIN or not exe_name:
        return None
    if _game_info_cache.get("exe") == exe_name and _game_info_cache.get("name"):
        started = _game_info_cache.get("started") or 0
        dur = max(0, int(time.time() - started)) if started else 0
        return {"name": _game_info_cache["name"], "exe_path": _game_info_cache.get("exe_path") or "", "started": started, "duration": dur}
    try:
        import psutil
        target = None
        for p in psutil.process_iter(["pid", "name", "exe", "create_time"]):
            try:
                if (p.info.get("name") or "").lower() == exe_name.lower():
                    target = p.info
                    break
            except Exception:
                continue
        if not target:
            return None
        pid = target.get("pid")
        exe_path = target.get("exe") or ""
        started = target.get("create_time") or 0
        name = _main_window_title(pid) if pid else ""
        if not name:
            name = exe_name[:-4] if exe_name.lower().endswith(".exe") else exe_name
        _game_info_cache.update({"exe": exe_name, "name": name, "exe_path": exe_path, "started": started})
        dur = max(0, int(time.time() - started)) if started else 0
        return {"name": name, "exe_path": exe_path, "started": started, "duration": dur}
    except Exception:
        return None

# --- Identifikasi game dari jendela foreground (perc130) ---
# Nama game dari jendela foreground. Game hampir
# selalu jadi jendela foreground saat dimainkan; cache 120 detik menjaga nama
# tetap tampil saat user alt-tab ke browser untuk cek dashboard.
_FPS_FG_SKIP = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe",
    "opera.exe", "whale.exe", "vivaldi.exe", "discord.exe", "discordcanary.exe",
    "discordptb.exe", "steam.exe", "steamwebhelper.exe", "epicgameslauncher.exe",
    "battle.net.exe", "riotclientservices.exe", "leagueclient.exe",
    "spotify.exe", "vlc.exe", "foobar2000.exe", "nocturne-app.exe",
    "whatsapp.exe", "telegram.exe", "slack.exe", "zoom.exe", "teams.exe",
    "explorer.exe", "dwm.exe", "python.exe", "pythonw.exe", "cmd.exe",
    "powershell.exe", "pwsh.exe", "conhost.exe", "windowsterminal.exe",
    "notepad.exe", "code.exe", "devenv.exe", "obs64.exe", "obs32.exe"}
_fps_fg_cache = {"exe": None, "t": 0.0}

def _fps_game_from_foreground():
    """Nama exe game dari jendela foreground (cache 120 detik). Return str/None."""
    if not IS_WIN:
        return None
    now = time.time()
    try:
        app = _active_app()
    except Exception:
        app = None
    if app:
        exe = (app.get("exe") or "").strip()
        if exe and exe.lower() not in _FPS_FG_SKIP:
            _fps_fg_cache.update({"exe": exe, "t": now})
            return exe
    # Foreground bukan game (browser/dll.) -> pakai cache bila masih segar.
    if _fps_fg_cache.get("exe") and now - _fps_fg_cache.get("t", 0) < 120:
        return _fps_fg_cache["exe"]
    return None

_fps_win_cache = {"exe": None, "t": 0.0}

def _fps_game_from_windows():
    """Nama exe game dari SEMUA jendela visible (bukan hanya foreground).
    HANYA aplikasi game: jendela harus fullscreen / hampir fullscreen
    (>=85% luas layar utama) DAN bukan aplikasi non-game (_FPS_FG_SKIP).
    Pilih jendela game berarea terbesar. Cache 5 detik. Return str/None."""
    if not IS_WIN:
        return None
    now = time.time()
    if _fps_win_cache.get("exe") and now - _fps_win_cache.get("t", 0) < 5:
        return _fps_win_cache["exe"]
    try:
        import ctypes
        from ctypes import wintypes
        import psutil
        user32 = ctypes.windll.user32
        user32.EnumWindows.restype = wintypes.BOOL
        user32.EnumWindows.argtypes = [wintypes.WNDENUMPROC, wintypes.LPARAM]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowRect.restype = wintypes.BOOL
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.GetSystemMetrics.restype = ctypes.c_int
        user32.GetSystemMetrics.argtypes = [ctypes.c_int]
        _sw = user32.GetSystemMetrics(0) or 0
        _sh = user32.GetSystemMetrics(1) or 0
        _screen_area = _sw * _sh
        if _screen_area <= 0:
            return None
        best = [0, None]  # [area, exe]
        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def _cb(hwnd, _):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                if user32.GetWindowTextLengthW(hwnd) <= 0:
                    return True
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if not pid.value:
                    return True
                try:
                    exe = (psutil.Process(pid.value).name() or "").strip()
                except Exception:
                    return True
                if not exe or exe.lower() in _FPS_FG_SKIP:
                    return True
                rect = wintypes.RECT()
                if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    return True
                area = max(0, rect.right - rect.left) * max(0, rect.bottom - rect.top)
                # Hanya jendela fullscreen / hampir fullscreen (>=85% layar):
                # game jalan fullscreen/borderless; jendela kecil (notepad,
                # explorer, chat) bukan game dan tidak boleh tampil ikonnya.
                if area > 0 and area >= 0.85 * _screen_area and area > best[0]:
                    best[0] = area
                    best[1] = exe
            except Exception:
                pass
            return True
        user32.EnumWindows(_cb, 0)
        if best[1]:
            _fps_win_cache.update({"exe": best[1], "t": now})
            return best[1]
    except Exception:
        pass
    return None

# --- Logo publisher/developer ganti logo game (perc133) ---
# Mapping exe game (lowercase) -> file logo di folder publisher/.
# Bila game terpetakan, /api/game_icon kembalikan logo publisher; bila tidak,
# tetap ikon game. Tambah game baru = 1 baris di map + 1 file PNG 256x256.
# 30 logo publisher/developer (perc134). Kunci = nama exe game (lowercase).
_PUBLISHER_LOGO_MAP = {
    # Kuro Games
    "client-win64-shipping.exe": "publisher_kuro.png",
    # Capcom
    "basara4-core.exe": "publisher_capcom.png",
    "re4.exe": "publisher_capcom.png",
    "re2.exe": "publisher_capcom.png",
    "monsterhunterworld.exe": "publisher_capcom.png",
    "dmc5.exe": "publisher_capcom.png",
    "streetfighter6.exe": "publisher_capcom.png",
    # HoYoverse
    "genshinimpact.exe": "publisher_hoyoverse.png",
    "starrail.exe": "publisher_hoyoverse.png",
    "zenlesszonezero.exe": "publisher_hoyoverse.png",
    # Riot Games
    "leagueclient.exe": "publisher_riot.png",
    "league of legends.exe": "publisher_riot.png",
    "valorant-win64-shipping.exe": "publisher_riot.png",
    "valorant.exe": "publisher_riot.png",
    # Epic Games
    "fortniteclient-win64-shipping.exe": "publisher_epic.png",
    "rocketleague.exe": "publisher_epic.png",
    "fallguys_client.exe": "publisher_epic.png",
    # Valve
    "cs2.exe": "publisher_valve.png",
    "dota2.exe": "publisher_valve.png",
    # Electronic Arts
    "r5apex.exe": "publisher_ea.png",
    "ts4.exe": "publisher_ea.png",
    "bf2042.exe": "publisher_ea.png",
    "fc25.exe": "publisher_ea.png",
    "fifa23.exe": "publisher_ea.png",
    # Ubisoft
    "acvalhalla.exe": "publisher_ubisoft.png",
    "acodyssey.exe": "publisher_ubisoft.png",
    "farcry6.exe": "publisher_ubisoft.png",
    "rainbowsix.exe": "publisher_ubisoft.png",
    # Activision
    "cod.exe": "publisher_activision.png",
    "modernwarfare.exe": "publisher_activision.png",
    # Blizzard
    "overwatch.exe": "publisher_blizzard.png",
    "diablo iv.exe": "publisher_blizzard.png",
    "wow.exe": "publisher_blizzard.png",
    # Square Enix
    "ffxiv_dx11.exe": "publisher_squareenix.png",
    "ffxvi.exe": "publisher_squareenix.png",
    "kh3.exe": "publisher_squareenix.png",
    # Bandai Namco
    "eldenring.exe": "publisher_bandainamco.png",
    "tekken8.exe": "publisher_bandainamco.png",
    "tales of arise.exe": "publisher_bandainamco.png",
    "darksoulsiii.exe": "publisher_bandainamco.png",
    # Sega
    "p5r.exe": "publisher_sega.png",
    "yakuza0.exe": "publisher_sega.png",
    "sonicfrontiers.exe": "publisher_sega.png",
    # Konami
    "efootball.exe": "publisher_konami.png",
    # Rockstar Games
    "gta5.exe": "publisher_rockstar.png",
    "gta5_enhanced.exe": "publisher_rockstar.png",
    "rdr2.exe": "publisher_rockstar.png",
    # CD Projekt Red
    "cyberpunk2077.exe": "publisher_cdprojekt.png",
    "witcher3.exe": "publisher_cdprojekt.png",
    # Bethesda
    "starfield.exe": "publisher_bethesda.png",
    "fallout4.exe": "publisher_bethesda.png",
    "skyrimse.exe": "publisher_bethesda.png",
    "doometernalx64vk.exe": "publisher_bethesda.png",
    # PlayStation (Sony)
    "gow.exe": "publisher_playstation.png",
    "horizonzerodawn.exe": "publisher_playstation.png",
    "spider-man.exe": "publisher_playstation.png",
    "ghostoftsushima.exe": "publisher_playstation.png",
    "tlou-i.exe": "publisher_playstation.png",
    # Xbox Game Studios
    "forzahorizon5.exe": "publisher_xbox.png",
    "halo infinite.exe": "publisher_xbox.png",
    "aoe2de.exe": "publisher_xbox.png",
    # FromSoftware
    "sekiro.exe": "publisher_fromsoftware.png",
    # Larian Studios
    "bg3.exe": "publisher_larian.png",
    "bg3_dx11.exe": "publisher_larian.png",
    "eocapp.exe": "publisher_larian.png",
    # Krafton
    "tslgame.exe": "publisher_krafton.png",
    "pubg.exe": "publisher_krafton.png",
    # NetEase Games
    "marvelrivals.exe": "publisher_netease.png",
    # Nexon
    "maplestory.exe": "publisher_nexon.png",
    "the first descendant.exe": "publisher_nexon.png",
    # Pearl Abyss
    "blackdesert64.exe": "publisher_pearlabyss.png",
    # Kojima Productions
    "ds.exe": "publisher_kojima.png",
    "deathstranding.exe": "publisher_kojima.png",
    # 2K Games
    "nba2k25.exe": "publisher_2k.png",
    "borderlands3.exe": "publisher_2k.png",
    "civ6.exe": "publisher_2k.png",
    # Warner Bros. Games
    "hogwartslegacy.exe": "publisher_wb.png",
    "mk11.exe": "publisher_wb.png",
    # THQ Nordic
    "biomutant.exe": "publisher_thqnordic.png",
    "darksiders3.exe": "publisher_thqnordic.png",
    # Nintendo: tidak ada exe PC native (game Switch via emulator) -> tanpa mapping,
    # file publisher_nintendo.png tetap tersedia di folder publisher/.
    # Nintendo (Switch via emulator: Ryujinx/Yuzu jalankan game Nintendo)
    "ryujinx.exe": "publisher_nintendo.png",
    "yuzu.exe": "publisher_nintendo.png",
    # Tencent
    "deltaforceclient-win64-shipping.exe": "publisher_tencent.png",
    # Yostar
    "bluearchive.exe": "publisher_yostar.png",
    # Cygames
    "gbfr.exe": "publisher_cygames.png",
    "umamusume.exe": "publisher_cygames.png",
    # Shift Up
    "sb.exe": "publisher_shiftup.png",
    "nikke.exe": "publisher_shiftup.png",
    # Papergames
    "infinitynikki.exe": "publisher_papergames.png",
    # Hypergryph
    "endfield.exe": "publisher_hypergryph.png",
    # Lilith Games
    "farlight84.exe": "publisher_lilith.png",
    # NCSOFT
    "tl.exe": "publisher_ncsoft.png",
    # Naughty Dog
    "tlou-ii.exe": "publisher_naughtydog.png",
    "u4.exe": "publisher_naughtydog.png",
    # Santa Monica Studio
    "godofwarragnarok.exe": "publisher_santamonica.png",
    # Insomniac Games
    "spider-man2.exe": "publisher_insomniac.png",
    "riftapart.exe": "publisher_insomniac.png",
    # Guerrilla Games
    "horizonforbiddenwest.exe": "publisher_guerrilla.png",
    # PlatinumGames
    "nierautomata.exe": "publisher_platinumgames.png",
    "bayonetta.exe": "publisher_platinumgames.png",
    # Atlus
    "p3r.exe": "publisher_atlus.png",
    "metaphor.exe": "publisher_atlus.png",
    # Koei Tecmo
    "nioh2.exe": "publisher_koeitecmo.png",
    "nioh.exe": "publisher_koeitecmo.png",
    # Remedy Entertainment
    "alanwake2.exe": "publisher_remedy.png",
    "control.exe": "publisher_remedy.png",
    # id Software
    "doomx64.exe": "publisher_idsoftware.png",
    # Obsidian Entertainment
    "avowed.exe": "publisher_obsidian.png",
    "indiana.exe": "publisher_obsidian.png",
    # Playground Games
    "forzahorizon4.exe": "publisher_playground.png",
    # Mojang Studios
    "minecraft.exe": "publisher_mojang.png",
    # Supergiant Games
    "hades.exe": "publisher_supergiant.png",
    "hadesii.exe": "publisher_supergiant.png",
    # Hello Games
    "nms.exe": "publisher_hellogames.png",
    # Arrowhead Game Studios
    "helldivers2.exe": "publisher_arrowhead.png",
    # BioWare
    "masseffect.exe": "publisher_bioware.png",
    "masseffect2.exe": "publisher_bioware.png",
    "masseffect3.exe": "publisher_bioware.png",
    "dragonageorigins.exe": "publisher_bioware.png",
    "dragonage2.exe": "publisher_bioware.png",
    "dragonageinquisition.exe": "publisher_bioware.png",
    # DICE
    "bf1.exe": "publisher_dice.png",
    "bfv.exe": "publisher_dice.png",
    "bf4.exe": "publisher_dice.png",
    # Crytek
    "crysis.exe": "publisher_crytek.png",
    "crysis2.exe": "publisher_crytek.png",
    "crysis3.exe": "publisher_crytek.png",
    "huntgame.exe": "publisher_crytek.png",
    # Gearbox Software
    "borderlands2.exe": "publisher_gearbox.png",
    "borderlands.exe": "publisher_gearbox.png",
    # Raven Software
    "blackopscoldwar.exe": "publisher_raven.png",
    "singularity.exe": "publisher_raven.png",
    # Treyarch
    "blackops.exe": "publisher_treyarch.png",
    "blackops2.exe": "publisher_treyarch.png",
    "blackops3.exe": "publisher_treyarch.png",
    "blackops4.exe": "publisher_treyarch.png",
    # Infinity Ward
    "iw4sp.exe": "publisher_infinityward.png",
    "iw5sp.exe": "publisher_infinityward.png",
    "iw6sp64_ship.exe": "publisher_infinityward.png",
    # Sledgehammer Games
    "s2_sp64_ship.exe": "publisher_sledgehammer.png",
    "s1_sp64_ship.exe": "publisher_sledgehammer.png",
    # Respawn Entertainment
    "titanfall2.exe": "publisher_respawn.png",
    "jedifallenorder.exe": "publisher_respawn.png",
    "jedisurvivor.exe": "publisher_respawn.png",
    # Arc System Works
    "ggst.exe": "publisher_arcsystemworks.png",
    "dbfz.exe": "publisher_arcsystemworks.png",
    # SNK
    "kofxv.exe": "publisher_snk.png",
    # Nihon Falcom
    "ed8.exe": "publisher_falcom.png",
    "ys8.exe": "publisher_falcom.png",
    # Spike Chunsoft
    "danganronpa.exe": "publisher_spikechunsoft.png",
    # Nippon Ichi Software
    "disgaea.exe": "publisher_nipponichi.png",
    # Atari
    "rct3.exe": "publisher_atari.png",
    # LucasArts
    "swkotor.exe": "publisher_lucasarts.png",
    "jasp.exe": "publisher_lucasarts.png",
    # Sierra Entertainment
    "swat4.exe": "publisher_sierra.png",
    "fear.exe": "publisher_sierra.png",
    # Codemasters
    "f1_23.exe": "publisher_codemasters.png",
    "dirtrally2.exe": "publisher_codemasters.png",
    "grid.exe": "publisher_codemasters.png",
    # THQ (era 2000-an)
    "darksiders.exe": "publisher_thq.png",
    "saintsrow2.exe": "publisher_thq.png",
    "reliccoh.exe": "publisher_thq.png",
    "metro2033.exe": "publisher_thq.png",
    # Eidos Interactive
    "tombraider.exe": "publisher_eidos.png",
    "dxhr.exe": "publisher_eidos.png",
    # Pandemic Studios
    "battlefrontii.exe": "publisher_pandemic.png",
    # Irrational Games
    "bioshock.exe": "publisher_irrational.png",
    "bioshockinfinite.exe": "publisher_irrational.png",
    # Double Fine
    "psychonauts2.exe": "publisher_doublefine.png",
}
# Nama tampilan ganti nama game (dipakai _fps_dict): exe -> nama publisher.
_GAME_DISPLAY_NAME_MAP = {
    "client-win64-shipping.exe": "Kuro Games",
    "basara4-core.exe": "Capcom",
    "re4.exe": "Capcom",
    "re2.exe": "Capcom",
    "monsterhunterworld.exe": "Capcom",
    "dmc5.exe": "Capcom",
    "streetfighter6.exe": "Capcom",
    "genshinimpact.exe": "HoYoverse",
    "starrail.exe": "HoYoverse",
    "zenlesszonezero.exe": "HoYoverse",
    "leagueclient.exe": "Riot Games",
    "league of legends.exe": "Riot Games",
    "valorant-win64-shipping.exe": "Riot Games",
    "valorant.exe": "Riot Games",
    "fortniteclient-win64-shipping.exe": "Epic Games",
    "rocketleague.exe": "Epic Games",
    "fallguys_client.exe": "Epic Games",
    "cs2.exe": "Valve",
    "dota2.exe": "Valve",
    "r5apex.exe": "EA",
    "ts4.exe": "EA",
    "bf2042.exe": "EA",
    "fc25.exe": "EA",
    "fifa23.exe": "EA",
    "acvalhalla.exe": "Ubisoft",
    "acodyssey.exe": "Ubisoft",
    "farcry6.exe": "Ubisoft",
    "rainbowsix.exe": "Ubisoft",
    "cod.exe": "Activision",
    "modernwarfare.exe": "Activision",
    "overwatch.exe": "Blizzard",
    "diablo iv.exe": "Blizzard",
    "wow.exe": "Blizzard",
    "ffxiv_dx11.exe": "Square Enix",
    "ffxvi.exe": "Square Enix",
    "kh3.exe": "Square Enix",
    "eldenring.exe": "Bandai Namco",
    "tekken8.exe": "Bandai Namco",
    "tales of arise.exe": "Bandai Namco",
    "darksoulsiii.exe": "Bandai Namco",
    "p5r.exe": "Sega",
    "yakuza0.exe": "Sega",
    "sonicfrontiers.exe": "Sega",
    "efootball.exe": "Konami",
    "gta5.exe": "Rockstar Games",
    "gta5_enhanced.exe": "Rockstar Games",
    "rdr2.exe": "Rockstar Games",
    "cyberpunk2077.exe": "CD Projekt Red",
    "witcher3.exe": "CD Projekt Red",
    "starfield.exe": "Bethesda",
    "fallout4.exe": "Bethesda",
    "skyrimse.exe": "Bethesda",
    "doometernalx64vk.exe": "Bethesda",
    "gow.exe": "PlayStation",
    "horizonzerodawn.exe": "PlayStation",
    "spider-man.exe": "PlayStation",
    "ghostoftsushima.exe": "PlayStation",
    "tlou-i.exe": "PlayStation",
    "forzahorizon5.exe": "Xbox",
    "halo infinite.exe": "Xbox",
    "aoe2de.exe": "Xbox",
    "sekiro.exe": "FromSoftware",
    "bg3.exe": "Larian Studios",
    "bg3_dx11.exe": "Larian Studios",
    "eocapp.exe": "Larian Studios",
    "tslgame.exe": "Krafton",
    "pubg.exe": "Krafton",
    "marvelrivals.exe": "NetEase Games",
    "maplestory.exe": "Nexon",
    "the first descendant.exe": "Nexon",
    "blackdesert64.exe": "Pearl Abyss",
    "ds.exe": "Kojima Productions",
    "deathstranding.exe": "Kojima Productions",
    "nba2k25.exe": "2K",
    "borderlands3.exe": "2K",
    "civ6.exe": "2K",
    "hogwartslegacy.exe": "Warner Bros. Games",
    "mk11.exe": "Warner Bros. Games",
    "biomutant.exe": "THQ Nordic",
    "darksiders3.exe": "THQ Nordic",
    "ryujinx.exe": "Nintendo",
    "yuzu.exe": "Nintendo",
    "deltaforceclient-win64-shipping.exe": "Tencent",
    "bluearchive.exe": "Yostar",
    "gbfr.exe": "Cygames",
    "umamusume.exe": "Cygames",
    "sb.exe": "Shift Up",
    "nikke.exe": "Shift Up",
    "infinitynikki.exe": "Papergames",
    "endfield.exe": "Hypergryph",
    "farlight84.exe": "Lilith Games",
    "tl.exe": "NCSOFT",
    "tlou-ii.exe": "Naughty Dog",
    "u4.exe": "Naughty Dog",
    "godofwarragnarok.exe": "Santa Monica Studio",
    "spider-man2.exe": "Insomniac Games",
    "riftapart.exe": "Insomniac Games",
    "horizonforbiddenwest.exe": "Guerrilla Games",
    "nierautomata.exe": "PlatinumGames",
    "bayonetta.exe": "PlatinumGames",
    "p3r.exe": "Atlus",
    "metaphor.exe": "Atlus",
    "nioh2.exe": "Koei Tecmo",
    "nioh.exe": "Koei Tecmo",
    "alanwake2.exe": "Remedy Entertainment",
    "control.exe": "Remedy Entertainment",
    "doomx64.exe": "id Software",
    "avowed.exe": "Obsidian Entertainment",
    "indiana.exe": "Obsidian Entertainment",
    "forzahorizon4.exe": "Playground Games",
    "minecraft.exe": "Mojang Studios",
    "hades.exe": "Supergiant Games",
    "hadesii.exe": "Supergiant Games",
    "nms.exe": "Hello Games",
    "helldivers2.exe": "Arrowhead Game Studios",
    "masseffect.exe": "BioWare",
    "masseffect2.exe": "BioWare",
    "masseffect3.exe": "BioWare",
    "dragonageorigins.exe": "BioWare",
    "dragonage2.exe": "BioWare",
    "dragonageinquisition.exe": "BioWare",
    "bf1.exe": "DICE",
    "bfv.exe": "DICE",
    "bf4.exe": "DICE",
    "crysis.exe": "Crytek",
    "crysis2.exe": "Crytek",
    "crysis3.exe": "Crytek",
    "huntgame.exe": "Crytek",
    "borderlands2.exe": "Gearbox Software",
    "borderlands.exe": "Gearbox Software",
    "blackopscoldwar.exe": "Raven Software",
    "singularity.exe": "Raven Software",
    "blackops.exe": "Treyarch",
    "blackops2.exe": "Treyarch",
    "blackops3.exe": "Treyarch",
    "blackops4.exe": "Treyarch",
    "iw4sp.exe": "Infinity Ward",
    "iw5sp.exe": "Infinity Ward",
    "iw6sp64_ship.exe": "Infinity Ward",
    "s2_sp64_ship.exe": "Sledgehammer Games",
    "s1_sp64_ship.exe": "Sledgehammer Games",
    "titanfall2.exe": "Respawn Entertainment",
    "jedifallenorder.exe": "Respawn Entertainment",
    "jedisurvivor.exe": "Respawn Entertainment",
    "ggst.exe": "Arc System Works",
    "dbfz.exe": "Arc System Works",
    "kofxv.exe": "SNK",
    "ed8.exe": "Nihon Falcom",
    "ys8.exe": "Nihon Falcom",
    "danganronpa.exe": "Spike Chunsoft",
    "disgaea.exe": "Nippon Ichi Software",
    "rct3.exe": "Atari",
    "swkotor.exe": "LucasArts",
    "jasp.exe": "LucasArts",
    "swat4.exe": "Sierra Entertainment",
    "fear.exe": "Sierra Entertainment",
    "f1_23.exe": "Codemasters",
    "dirtrally2.exe": "Codemasters",
    "grid.exe": "Codemasters",
    "darksiders.exe": "THQ",
    "saintsrow2.exe": "THQ",
    "reliccoh.exe": "THQ",
    "metro2033.exe": "THQ",
    "tombraider.exe": "Eidos Interactive",
    "dxhr.exe": "Eidos Interactive",
    "battlefrontii.exe": "Pandemic Studios",
    "bioshock.exe": "Irrational Games",
    "bioshockinfinite.exe": "Irrational Games",
    "psychonauts2.exe": "Double Fine",
}
_PUBLISHER_LOGO_CACHE = {}  # nama file -> bytes PNG

def _load_publisher_logo(exe_name):
    """Bytes PNG logo publisher/developer untuk exe game. Return bytes/None."""
    if not exe_name:
        return None
    fn = _PUBLISHER_LOGO_MAP.get(exe_name.lower())
    if not fn:
        return None
    if fn in _PUBLISHER_LOGO_CACHE:
        return _PUBLISHER_LOGO_CACHE[fn]
    try:
        p = BASE_DIR / "publisher" / fn
        data = p.read_bytes()
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            _PUBLISHER_LOGO_CACHE[fn] = data
            return data
    except Exception:
        pass
    return None

def _fps_game_exe():
    """Nama exe game, satu sumber untuk _fps_dict() dan /api/game_icon.
    Prioritas: jendela visible fullscreen -> foreground."""
    try:
        _f, g, _st, _src = _fps_read2()
    except Exception:
        g = None
    if g:
        return g
    try:
        g = _fps_game_from_windows()
    except Exception:
        g = None
    if g:
        return g
    try:
        g = _fps_game_from_foreground()
    except Exception:
        g = None
    return g

def _fps_dict():
    """Dict fps untuk /api/data, diperluas info game."""
    f, _g_csv, st, src = _fps_read2()
    g_exe = _fps_game_exe()
    d = {"value": f, "game": g_exe, "status": st, "source": src, "error": _fps_ab_error,
         "game_exe": g_exe or "", "game_duration": 0, "game_icon": False}
    info = _fps_game_info(g_exe) if g_exe else None
    if info:
        d["game"] = info["name"]
        d["game_duration"] = info["duration"]
        d["game_icon"] = bool(info.get("exe_path"))
    if g_exe:
        _dn = _GAME_DISPLAY_NAME_MAP.get(g_exe.lower())
        if _dn:
            d["game"] = _dn
    return d

_fps_read2_cache = (None, 0.0)


def _fps_read2():
    """(fps, game, status, source). Hanya MSI Afterburner (MAHM) — perc179.

    Status: ok (Afterburner jalan + ada framerate) | off (Afterburner tidak
    jalan — kartu FPS disembunyikan dashboard) | no_game (Afterburner jalan
    tapi tidak ada game/framerate) | unsupported (bukan Windows).
    Nama game BUKAN dari sini lagi — _fps_game_exe() mengambilnya dari
    jendela game (fullscreen -> foreground).
    Di-memo 0,5 detik (perc153): _fps_dict() memanggil ini 2x tiap collect
    (langsung + lewat _fps_game_exe) — tanpa memo, scan shared memory
    Afterburner terjadi 2x per tick.
    """
    global _fps_read2_cache
    now = time.time()
    if _fps_read2_cache[0] is not None and now - _fps_read2_cache[1] < 0.5:
        return _fps_read2_cache[0]
    ab = _fps_afterburner()
    if ab is not None:
        res = (ab, None, "ok", "afterburner")
    elif not IS_WIN:
        res = (0.0, None, "unsupported", "")
    elif _fps_ab_error == "no_mapping":
        res = (0.0, None, "off", "")
    else:
        res = (0.0, None, "no_game", "")
    _fps_read2_cache = (res, now)
    return res


# --- Progres kompres latar (perc180 / Patch 3.1, S117 Cara 3) ---
# Tiap request /api/bg_compress punya job id (dashboard kirim sebagai
# query &job=...). Selama FFmpeg encode, progres nyata (%, kecepatan,
# ETA, mesin) ditulis ke dict ini; dashboard membacanya lewat
# /api/bg_compress_progress tiap 250 ms. Tanpa ini, progres macet di
# "Mengirim... 100%" selama encode.
_BG_COMP_JOBS = {}
_BG_COMP_JOBS_LOCK = threading.Lock()


def _bg_comp_job_set(job, **kw):
    if not job:
        return
    try:
        with _BG_COMP_JOBS_LOCK:
            ent = _BG_COMP_JOBS.get(job) or {"job": job, "t": time.time()}
            ent.update(kw)
            ent["t"] = time.time()
            _BG_COMP_JOBS[job] = ent
            for k in [k for k, v in _BG_COMP_JOBS.items() if time.time() - (v.get("t") or 0) > 600]:
                _BG_COMP_JOBS.pop(k, None)
    except Exception:
        pass


def _bg_comp_job_get(job):
    try:
        with _BG_COMP_JOBS_LOCK:
            ent = _BG_COMP_JOBS.get(job)
            return dict(ent) if ent else None
    except Exception:
        return None


def _bg_comp_run(cmd, prog_path, err_path, dur, job, in_size, engine):
    """Jalankan FFmpeg sambil menulis progres nyata ke job dict (S117 Cara 3).
    Progress via -progress file: out_time_ms vs durasi -> pct; kecepatan
    MB/dtk + x real-time; ETA detik. Return True bila returncode 0."""
    try:
        err_fh = open(err_path, "wb")
    except Exception:
        err_fh = subprocess.DEVNULL
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=err_fh)
    except Exception:
        try:
            if err_fh is not subprocess.DEVNULL:
                err_fh.close()
        except Exception:
            pass
        return False
    t0 = time.time()
    ok = False
    try:
        while True:
            rc = proc.poll()
            if rc is not None:
                ok = (rc == 0)
                break
            if time.time() - t0 > 1200:
                try:
                    proc.kill()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=10)
                except Exception:
                    pass
                ok = False
                break
            try:
                ot = 0.0
                try:
                    sz = os.path.getsize(prog_path)
                    with open(prog_path, "rb") as pf:
                        if sz > 8192:
                            pf.seek(sz - 8192)
                        tail = pf.read().decode("utf-8", "ignore")
                    for ln in tail.splitlines():
                        if ln.startswith("out_time_ms="):
                            try:
                                ot = float(ln.split("=", 1)[1].strip()) / 1000000.0
                            except Exception:
                                pass
                except Exception:
                    pass
                el = max(0.05, time.time() - t0)
                pct = int(ot / dur * 100) if dur and dur > 0 else 0
                pct = max(0, min(99, pct))
                sx = (ot / el) if el > 0 else 0.0
                smb = ((in_size * pct / 100.0) / el / 1048576.0) if in_size else 0.0
                eta = None
                if dur and sx and sx > 0.05:
                    eta = max(0, int((dur - ot) / sx))
                _bg_comp_job_set(job, phase="encode", pct=pct, engine=engine,
                                 speed_mb=round(smb, 1), speed_x=round(sx, 1), eta_s=eta)
            except Exception:
                pass
            try:
                proc.wait(timeout=0.25)
            except Exception:
                pass
        if ok:
            _bg_comp_job_set(job, phase="done", pct=100, engine=engine,
                             speed_mb=0, speed_x=0, eta_s=0)
        else:
            _bg_comp_job_set(job, phase="error", pct=100, engine=engine, error="ffmpeg_failed")
    finally:
        try:
            if err_fh is not subprocess.DEVNULL:
                err_fh.close()
        except Exception:
            pass
    return ok



# --- Manifest PWA (perc182, Patch 3.3, S135 Cara 3) ---
# Ikon K untuk "Add to Home Screen" di HP: apple-touch-icon 180x180
# di dashboard + entri ikon di manifest ini. Ikon berupa SVG data-URI
# (sama seperti favicon tab) -- kotak hitam + huruf K putih tebal.
_MANIFEST_ICON_180 = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 180 180'><rect width='180' height='180' rx='40' fill='%231A1A1A'/><text x='90' y='138' font-family='Arial,sans-serif' font-size='122' font-weight='800' fill='%23FFFFFF' text-anchor='middle'>K</text></svg>"
_MANIFEST_ICON_16 = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><rect width='16' height='16' rx='4' fill='%231A1A1A'/><text x='8' y='12.2' font-family='Arial,sans-serif' font-size='11' font-weight='800' fill='%23FFFFFF' text-anchor='middle'>K</text></svg>"
_MANIFEST = {
    "name": "KISA",
    "short_name": "KISA",
    "display": "standalone",
    "start_url": "/",
    "background_color": "#060606",
    "theme_color": "#060606",
    "icons": [
        {"src": _MANIFEST_ICON_180, "sizes": "180x180", "type": "image/svg+xml"},
        {"src": _MANIFEST_ICON_180, "sizes": "192x192", "type": "image/svg+xml"},
        {"src": _MANIFEST_ICON_180, "sizes": "512x512", "type": "image/svg+xml"},
        {"src": _MANIFEST_ICON_16, "sizes": "16x16", "type": "image/svg+xml"},
    ],
}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, body, ctype, extra=None):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for _k, _v in (extra or {}).items():
            self.send_header(_k, _v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            html = (BASE_DIR / "dashboard.html").read_text(encoding="utf-8")
            self._send(html, "text/html; charset=utf-8")
        elif self.path == "/qr.png" or self.path.startswith("/qr.png?"):
            _qr_ips = _local_ips()
            _qr_ip = _qr_ips[0] if _qr_ips else None
            if (not _QR_PNG.exists()) or (_qr_ip is not None and _qr_ip != _QR_IP):
                _dashboard_qr()
            if _QR_PNG.exists():
                self._send(_QR_PNG.read_bytes(), "image/png")
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"No QR")
        elif self.path == "/api/qr_url":
            # Patch 3.5: kembalikan URL dashboard (IP LAN + PORT) sebagai JSON
            # supaya popup QR di dashboard tidak perlu menebak alamat server.
            _qru_ips = _local_ips()
            _qru_ip = _qru_ips[0] if _qru_ips else None
            if _qru_ip is not None and _qru_ip != _QR_IP:
                _dashboard_qr()
            if _qru_ip is not None:
                self._send(json.dumps({"url": "http://%s:%d" % (_qru_ip, PORT)}), "application/json")
            else:
                self._send(json.dumps({"url": None}), "application/json")
        elif self.path == "/api/data" or self.path.startswith("/api/data?"):
            _qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            _skip = set()
            for _s in _qs.get("skip", []):
                for _part in _s.split(","):
                    if _part.strip() in ("fps", "np"):
                        _skip.add(_part.strip())
            if _qs.get("lite", ["0"])[0] == "1":
                _skip.update(("fps", "np"))
            global _ULTRA_MODE
            if _qs.get("ultralite", ["0"])[0] == "1":
                # Mode Super Ringan: lewati FPS + NP + semua sumber berat.
                _ULTRA_MODE = True
                _skip.update(("fps", "np", "ultra"))
            else:
                _ULTRA_MODE = False
                _maybe_autostart()
            self._send(json.dumps(collect(skip=_skip)), "application/json")
        elif self.path == "/api/app_icon" or self.path.startswith("/api/app_icon?"):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            exe_q = (qs.get("exe") or [None])[0]
            if exe_q:
                png = _app_icon_png(_recent_app_paths[exe_q]) if exe_q in _recent_app_paths else None
            else:
                png = _app_icon_png()
            if png:
                self._send(png, "image/png")
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"No icon")
        elif self.path == "/api/cover" or self.path.startswith("/api/cover?"):
            if _cover_cache.get("data"):
                self._send(_cover_cache["data"], _cover_cache.get("ctype") or "image/jpeg")
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"No cover")
        elif self.path == "/api/np_debug" or self.path.startswith("/api/np_debug?"):
            self._send(json.dumps(_np_debug, ensure_ascii=False).encode("utf-8"), "application/json")
        elif self.path == "/api/fps_debug":
            _maybe_autostart()
            self._send(json.dumps(_fps_debug(), ensure_ascii=False).encode("utf-8"), "application/json")
        elif self.path == "/api/game_icon" or self.path.startswith("/api/game_icon?"):
            try:
                _ge = _fps_game_exe()
                _png = _load_publisher_logo(_ge)
                if not _png:
                    _info = _fps_game_info(_ge) if _ge else None
                    _png = _app_icon_png(_info["exe_path"]) if _info and _info.get("exe_path") else None
            except Exception:
                _png = None
            if _png:
                self._send(_png, "image/png")
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"No icon")
        elif self.path == "/api/fps" or self.path.startswith("/api/fps?"):
            # perc180 (Patch 3.1, S124 Cara 1): endpoint FPS ringan —
            # hanya _fps_dict(), tanpa collect LHM/GSMTC lengkap.
            # Dashboard memanggilnya tiap 250 ms supaya angka FPS
            # mengikuti game lebih cepat (tipikal ±0,89 dtk, dulu ±1,35 dtk).
            self._send(json.dumps(_fps_dict(), ensure_ascii=False).encode("utf-8"), "application/json")
        elif self.path == "/api/support_apps" or self.path.startswith("/api/support_apps?"):
            # Patch 4.1 (S153): status aplikasi pendukung di PC untuk
            # daftar baca-saja di halaman Dukungan (HP). Di-cache 5 detik
            # di _support_apps(); tidak pernah melempar.
            self._send(json.dumps(_support_apps(), ensure_ascii=False).encode("utf-8"), "application/json")
        elif self.path == "/api/check_update" or self.path.startswith("/api/check_update?"):
            # Patch 4.6 (S157 Cara 1): cek rilis GitHub terbaru.
            # force=1 = lewati cache 1 jam (tombol Periksa Pembaruan).
            # Gagal jaringan -> {"ok": False} netral, tidak pernah traceback.
            _qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            _force = (_qs.get("force") or ["0"])[0] == "1"
            self._send(json.dumps(_update_check(force=_force), ensure_ascii=False).encode("utf-8"), "application/json")
        elif self.path == "/api/download_progress" or self.path.startswith("/api/download_progress?"):
            # Patch 4.6: progres unduhan update (persen nyata dari server).
            with _update_dl_lock:
                _pd = dict(_update_dl)
            _pd.pop("path", None)
            self._send(json.dumps(_pd, ensure_ascii=False).encode("utf-8"), "application/json")
        elif self.path == "/api/update_file" or self.path.startswith("/api/update_file?"):
            # Patch 4.6: layani file update yang sudah diunduh (untuk HP).
            # Nama harus sama persis dengan unduhan yang selesai.
            _qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            _nm = (_qs.get("name") or [""])[0]
            with _update_dl_lock:
                _fd = dict(_update_dl)
            _ok = (_fd.get("state") == "done" and _fd.get("name") == _nm
                   and _fd.get("path") and os.path.exists(_fd["path"]))
            if not _ok:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not found")
            else:
                _ctype = ("application/vnd.android.package-archive"
                          if _nm.lower().endswith(".apk") else "application/octet-stream")
                try:
                    _size = os.path.getsize(_fd["path"])
                except Exception:
                    _size = 0
                self.send_response(200)
                self.send_header("Content-Type", _ctype)
                self.send_header("Content-Length", str(_size))
                self.send_header("Content-Disposition",
                                 'attachment; filename="%s"' % _nm)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                with open(_fd["path"], "rb") as _fh:
                    while True:
                        _chunk = _fh.read(1024 * 1024)
                        if not _chunk:
                            break
                        self.wfile.write(_chunk)
        elif self.path == "/api/bg_compress_progress" or self.path.startswith("/api/bg_compress_progress?"):
            # perc180 (Patch 3.1, S117 Cara 3): progres nyata kompres.
            _qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            _job = (_qs.get("job") or [""])[0][:64]
            _ent = _bg_comp_job_get(_job) if _job else None
            if _ent:
                _ent = dict(_ent)
                _ent.pop("t", None)
                _ent["ok"] = True
                self._send(json.dumps(_ent, ensure_ascii=False).encode("utf-8"), "application/json")
            else:
                self._send(json.dumps({"ok": False, "error": "no_job"}, ensure_ascii=False).encode("utf-8"), "application/json")
        elif self.path == "/manifest.json":
            # perc182 (Patch 3.3, S135 Cara 3): manifest PWA.
            self._send(json.dumps(_MANIFEST, ensure_ascii=False).encode("utf-8"), "application/manifest+json")
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")

    def do_POST(self):
        global _now_playing_cache, _gsmtc_cache, _fallback_cache
        if self.path == "/api/power":
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                body = {}
            gol = body.get("golongan")
            if gol in PLN_TARIFFS:
                data = _load_power()
                data["golongan"] = gol
                data["tariff"] = PLN_TARIFFS[gol]
                _save_power(data)
                self._send(json.dumps({"golongan": gol, "tariff": PLN_TARIFFS[gol]}), "application/json")
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Invalid golongan")
        elif self.path == "/api/np_control":
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                body = {}
            action = (body.get("action") or "").lower()
            value = body.get("value")
            ok = False
            if action in ("play", "pause", "toggle", "next", "prev", "seek", "mute"):
                if _np_last_source == "beefweb":
                    ok = _beefweb_control(action, value)
                    if not ok:
                        ok = _gsmtc_control(action, value)
                else:
                    ok = _gsmtc_control(action, value)
                    if not ok:
                        ok = _beefweb_control(action, value)
                if ok:
                    _now_playing_cache = (None, 0)
                    _gsmtc_cache = (None, 0)
                    _fallback_cache = (None, 0)
            self._send(json.dumps({"ok": bool(ok)}), "application/json")
        elif self.path == "/api/download_update":
            # Patch 4.6: mulai unduh aset update (nama harus ada di hasil
            # cek terakhir). Unduhan jalan di thread latar; progres lewat
            # GET /api/download_progress.
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                body = {}
            _asset = str(body.get("asset") or "")
            self._send(json.dumps(_update_start_download(_asset), ensure_ascii=False).encode("utf-8"), "application/json")
        elif self.path == "/api/install_update":
            # Patch 4.6: jalankan installer yang sudah diunduh, lalu tutup
            # aplikasi dengan bersih (PC). HP tidak memakai endpoint ini —
            # APK dipasang lewat bridge KisaApp.downloadApk.
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                body = {}
            _asset = str(body.get("asset") or "")
            self._send(json.dumps(_update_install(_asset), ensure_ascii=False).encode("utf-8"), "application/json")
        elif self.path == "/api/speedtest":
            self._send(json.dumps(_speed_test()), "application/json")
        elif self.path.startswith("/api/bg_compress"):
            # perc175/177: kompres latar di PC (LAN) via FFmpeg.
            # perc177: coba hardware encoder AMD AMF (h264_amf) dulu,
            # fallback software libx264; header X-KISA-Engine melaporkan mesin yang dipakai.
            # perc180 (S117 Cara 3): progres nyata encode via -progress +
            # /api/bg_compress_progress; libx264 preset veryfast (dulu medium).
            # Body mentah = file; query kind=video|photo, res, fps, speed.
            import os
            import tempfile
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            kind = (qs.get("kind") or ["video"])[0]
            res = (qs.get("res") or ["asli"])[0]
            fps = (qs.get("fps") or ["30"])[0]
            speed = (qs.get("speed") or ["medium"])[0]
            job = (qs.get("job") or [""])[0][:64]
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except Exception:
                length = 0
            maxlen = 2048 * 1024 * 1024 if kind == "video" else 50 * 1024 * 1024
            if kind not in ("video", "photo") or length <= 0 or length > maxlen:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": "bad_request"}).encode("utf-8"))
            else:
                ffmpeg = shutil.which("ffmpeg")
                if not ffmpeg:
                    # Baca habis body dulu supaya respons 503 sampai ke HP.
                    try:
                        drain = length
                        while drain > 0:
                            chunk = self.rfile.read(min(1024 * 1024, drain))
                            if not chunk:
                                break
                            drain -= len(chunk)
                    except Exception:
                        pass
                    _bg_comp_job_set(job, phase="error", pct=100, engine="", error="ffmpeg_missing")
                    self.send_response(503)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"ok": False, "ffmpeg_missing": True, "error": "ffmpeg_missing", "message": "FFmpeg belum terpasang di PC"}, ensure_ascii=False).encode("utf-8"))
                else:
                    tmpdir = tempfile.mkdtemp(prefix="kisa_bg_")
                    try:
                        in_path = os.path.join(tmpdir, "in.bin")
                        out_path = os.path.join(tmpdir, "out.mp4" if kind == "video" else "out.jpg")
                        with open(in_path, "wb") as fh:
                            left = length
                            while left > 0:
                                chunk = self.rfile.read(min(1024 * 1024, left))
                                if not chunk:
                                    break
                                fh.write(chunk)
                                left -= len(chunk)
                                _bg_comp_job_set(job, phase="upload", pct=int((length - left) / length * 100) if length else 0, engine="")
                        dims = {"720": (1280, 720), "1080": (1920, 1080), "1440": (2560, 1440), "2160": (3840, 2160), "4320": (7680, 4320)}.get(res)
                        # Bila media sudah di bawah resolusi target,
                        # kembalikan file asli tanpa re-encode (sama
                        # seperti jalur lokal MediaRecorder).
                        passthrough = False
                        if dims:
                            try:
                                ffprobe = shutil.which("ffprobe") or os.path.join(os.path.dirname(ffmpeg), "ffprobe")
                                pr = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", in_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
                                _wh = pr.stdout.decode("utf-8", "ignore").strip().split(",")
                                if int(_wh[0]) <= dims[0] and int(_wh[1]) <= dims[1]:
                                    passthrough = True
                            except Exception:
                                passthrough = False
                        if passthrough:
                            with open(in_path, "rb") as fh:
                                data = fh.read()
                            ctype_in = self.headers.get("Content-Type") or ("video/mp4" if kind == "video" else "image/jpeg")
                            _bg_comp_job_set(job, phase="done", pct=100, engine="passthrough", speed_mb=0, speed_x=0, eta_s=0)
                            self._send(data, ctype_in, {"X-KISA-Passthrough": "1", "X-KISA-Engine": "passthrough"})
                        else:
                            engine = None
                            if kind == "video":
                                vf = "scale=%d:%d:force_original_aspect_ratio=decrease" % dims if dims else "scale=-2:-2"
                                ctype = "video/mp4"
                                bitrate = {"720": "4M", "1080": "8M", "1440": "12M", "2160": "20M", "4320": "35M"}.get(res, "8M")
                                # perc180 (S117 Cara 3): durasi untuk progres nyata
                                # + file progres FFmpeg (-progress) + stderr ke file.
                                ffprobe = shutil.which("ffprobe") or os.path.join(os.path.dirname(ffmpeg), "ffprobe")
                                prog_path = os.path.join(tmpdir, "progress.txt")
                                err_path = os.path.join(tmpdir, "stderr.txt")
                                dur = 0.0
                                try:
                                    _prd = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", in_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
                                    dur = float((_prd.stdout or b"").decode("utf-8", "ignore").strip() or 0)
                                except Exception:
                                    dur = 0.0
                                # perc177: coba hardware encoder AMD AMF (RX 6600) dulu.
                                amf_ok = False
                                try:
                                    enc = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
                                    amf_ok = b"h264_amf" in (enc.stdout or b"")
                                except Exception:
                                    amf_ok = False
                                if amf_ok:
                                    cmd_amf = [ffmpeg, "-nostdin", "-y", "-i", in_path, "-vf", vf, "-r", fps if fps in ("30", "60") else "30", "-c:v", "h264_amf", "-quality", "speed", "-rc", "cbr", "-b:v", bitrate, "-maxrate", bitrate, "-bufsize", "16M", "-an", "-movflags", "+faststart", "-progress", prog_path, out_path]
                                    _bg_comp_job_set(job, phase="encode", pct=0, engine="amf", speed_mb=0, speed_x=0, eta_s=None)
                                    if _bg_comp_run(cmd_amf, prog_path, err_path, dur, job, length, "amf") and os.path.exists(out_path):
                                        engine = "amf"
                                if engine is None:
                                    # perc180: preset tercepat (veryfast, dulu medium) — S117 Cara 3.
                                    cmd = [ffmpeg, "-nostdin", "-y", "-i", in_path, "-vf", vf, "-r", fps if fps in ("30", "60") else "30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", "-progress", prog_path, out_path]
                                    _bg_comp_job_set(job, phase="encode", pct=0, engine="libx264", speed_mb=0, speed_x=0, eta_s=None)
                                    if not _bg_comp_run(cmd, prog_path, err_path, dur, job, length, "libx264") or not os.path.exists(out_path):
                                        _bg_comp_job_set(job, phase="error", pct=100, engine="", error="ffmpeg_failed")
                                        self.send_response(500)
                                        self.send_header("Content-Type", "application/json")
                                        self.end_headers()
                                        self.wfile.write(json.dumps({"ok": False, "error": "ffmpeg_failed", "message": "FFmpeg gagal mengompres file"}, ensure_ascii=False).encode("utf-8"))
                                    else:
                                        engine = "libx264"
                            else:
                                vf = "scale=%d:%d:force_original_aspect_ratio=decrease" % dims if dims else "scale=-2:-2"
                                _bg_comp_job_set(job, phase="encode", pct=0, engine="photo", speed_mb=0, speed_x=0, eta_s=None)
                                cmd = [ffmpeg, "-y", "-i", in_path, "-vf", vf, "-q:v", "3", out_path]
                                ctype = "image/jpeg"
                                proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1200)
                                if proc.returncode != 0 or not os.path.exists(out_path):
                                    _bg_comp_job_set(job, phase="error", pct=100, engine="", error="ffmpeg_failed")
                                    self.send_response(500)
                                    self.send_header("Content-Type", "application/json")
                                    self.end_headers()
                                    self.wfile.write(json.dumps({"ok": False, "error": "ffmpeg_failed", "message": "FFmpeg gagal mengompres file"}, ensure_ascii=False).encode("utf-8"))
                                else:
                                    engine = "photo"
                            if engine is not None:
                                _bg_comp_job_set(job, phase="done", pct=100, engine=engine or "", speed_mb=0, speed_x=0, eta_s=0)
                                with open(out_path, "rb") as fh:
                                    data = fh.read()
                                self._send(data, ctype, {"X-KISA-Engine": engine})
                    except Exception as exc:
                        try:
                            self.send_response(500)
                            self.send_header("Content-Type", "application/json")
                            self.end_headers()
                            self.wfile.write(json.dumps({"ok": False, "error": "server_error", "message": str(exc)}, ensure_ascii=False).encode("utf-8"))
                        except Exception:
                            pass
                    finally:
                        try:
                            shutil.rmtree(tmpdir, ignore_errors=True)
                        except Exception:
                            pass
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")


if __name__ == "__main__":
    psutil.cpu_percent(interval=0.1)
    collect()
    try:
        import threading
        threading.Thread(target=_power_thread, daemon=True).start()
    except Exception:
        pass
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    fw_ok = _ensure_firewall_rule()
    # perc154: auto-start LHM/Afterburner TIDAK lagi di sini, tapi malas
    # (lazy) saat request /api/data pertama yang BUKAN Mode Super Ringan
    # (_maybe_autostart). Jadi PC super ringan tidak dibebani aplikasi berat.
    qr_url = _dashboard_qr()
    print("=" * 60)
    print("KISA jalan!")
    print("Buka di HP (satu WiFi yang sama ATAU hotspot HP) salah satu alamat ini:")
    for ip in _local_ips() or ["<IP-PC-kamu>"]:
        tag = " (kemungkinan hotspot HP)" if (ip.startswith("192.168.43.") or ip.startswith("172.20.10.")) else ""
        print(f"  http://{ip}:{PORT}{tag}")
    if qr_url:
        print(f"QR dashboard: {qr_url}  (file QR_Dashboard.png — scan dari HP)")
    if fw_ok:
        print("Firewall: port 8000 sudah diizinkan (termasuk jaringan Public/hotspot).")
    else:
        print("Firewall: port 8000 BELUM tentu diizinkan. Kalau HP tidak bisa membuka,")
        print("  tutup server ini, klik kanan Jalankan_di_PC.bat > Run as administrator,")
        print("  lalu jalankan lagi sekali.")
    print("Auto-start Afterburner/LHM: aktif saat dashboard pertama dibuka")
    print("  (bukan Mode Super Ringan); tidak dinyalakan bila Mode Super Ringan.")
    print("  Status auto-start bisa dicek di http://localhost:8000/api/fps_debug")
    print(f"Di PC ini juga bisa dibuka: http://localhost:{PORT}")
    print("Berhenti: tekan Ctrl+C di jendela ini.")
    print("=" * 60)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer dihentikan.")
