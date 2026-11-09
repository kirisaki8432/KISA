# kisa_app.py — Launcher aplikasi KISA (Patch 3.5, tray minimize).
#
# Menjalankan server monitor KISA di dalam proses aplikasi (thread),
# lalu membuka dashboard di jendela aplikasi sendiri (pywebview).
# Kalau pywebview tidak tersedia, fallback: buka browser default.
# Ikon tray (pystray) + auto-start Windows bersifat opsional dan
# semuanya dijaga try/except supaya aplikasi tetap jalan tanpa mereka.
#
# Patch 3.5 — tutup ke tray: tombol X pada jendela TIDAK keluar dari
# aplikasi, melainkan menyembunyikan jendela ke tray (server tetap
# jalan, ikon tray tetap ada). "Buka KISA" di menu tray menampilkan
# lagi jendela; keluar yang sebenarnya hanya lewat "Keluar" di tray
# (stop_server + stop tray + os._exit).
# Dasar pywebview (v6.2.1, diverifikasi dari source wheel + docs resmi):
# window.events.closing dibuat dengan should_lock=True, jadi
# Event.set() menjalankan handler secara sinkron dan mengembalikan
# True bila ada handler yang me-return False; backend WinForms
# (on_closing) lalu mengeset args.Cancel = True. window.show() /
# window.hide() dari thread lain di-marshal ke GUI thread lewat
# Control.Invoke di backend WinForms, jadi aman dipanggil dari
# thread menu tray.
#
# Patch 3.5 — startup cepat: server HTTP dibuat + serve_forever jalan
# DULU di start_server(), baru pemanasan lambat (collect / firewall /
# QR) menyusul di background — jendela tidak lagi menunggu puluhan
# detik collect() pertama (cache dingin) sebelum port 8000 listen.
# Patch 3.8 — pengaturan tersimpan (root cause TERBUKTI dari source
# pywebview 6.2.1, BUKAN tebakan): webview.start() dipanggil TANPA argumen,
# padahal default pywebview 6.x adalah private_mode=True (docstring start():
# "In private mode, cookies and local storage are not preserved. Default is
# True"). Akibatnya backend EdgeChromium mengaktifkan InPrivate WebView2
# (edgechromium.py: props.set_IsInPrivateModeEnabled(_state['private_mode']))
# DAN winforms.init_storage() memakai folder temp
# (cache_dir = tempfile.TemporaryDirectory().name) bila private_mode True
# tanpa storage_path — semua localStorage (preset tata letak, pengaturan)
# terhapus tiap aplikasi ditutup total, walau sesi sudah lama. Perbaikan:
# webview.start(private_mode=False, storage_path=<folder persisten eksplisit>)
# dengan folder %LOCALAPPDATA%\KISA\WebView2 (stabil, tidak ikut terhapus
# saat exe di-update; bukan _MEIPASS, bukan folder install). Pengujian nyata
# (preset bertahan setelah Keluar lalu buka lagi) hanya bisa di PC user.
#
# Patch 3.9 — jendela & taskbar & keluar & startup (BUKTI dari source,
# bukan tebakan):
# - (2) Jendela di tengah: create_window() tanpa x/y memakai
#   FormStartPosition.CenterScreen (WinForms), TAPI ukuran jendela dihitung
#   dalam piksel FISIK (int(width*scale), Dpi-aware) sementara CenterScreen
#   memusatkan pada batas layar penuh (taskbar tidak dikecualikan) — bila
#   DPI bukan 100%, jendela bisa lebih besar dari layar logis dan mendarat
#   rendah/terpotong bawah (laporan user). Perbaikan: posisi dihitung
#   eksplisit dari WorkingArea layar utama (webview.screens, frame =
#   area kerja tanpa taskbar), dijepit agar 1280x800 selalu muat.
# - (3) Ikon K ganda: pywebview 6.2.1 TIDAK menyetel AppUserModelID sama
#   sekali (grep source: 0 hasil) — jendela mendapat AppUserModelID default
#   Windows, sementara shortcut installer memakai AppId dari KISA-Setup.iss
#   — dua ID berbeda = Windows menampilkan ikon pin + ikon jendela sebagai
#   DUA ikon taskbar. Perbaikan: SetCurrentProcessExplicitAppUserModelID
#   dengan nilai yang SAMA dengan AppId .iss, sebelum jendela dibuat.
#   AppId di .iss TIDAK berubah.
# - (3)+(7) Single-instance: TIDAK ADA mutex di 3.8. Instance kedua: gagal
#   bind port 8000 (diam-diam), TAPI wait_for_server() tetap sukses karena
#   server instance pertama menjawab — lalu instance kedua membuka jendela
#   + ikon tray KEDUA, dan klik ikon taskbar yang meluncurkan instance
#   kedua tidak memunculkan apa-apa. Perbaikan: named mutex + named event;
#   instance kedua menyinyal instance pertama (tampilkan jendela ke depan)
#   lalu keluar — tanpa instance/server kedua.
# - (4) Keluar lambat: shutdown kini bertahap DENGAN BATAS WAKTU — watchdog
#   2 detik memaksa os._exit(0); jendela ditutup dulu (WebView2 flush,
#   perbaikan 3.8 terjaga) lewat destroy() dengan flag _QUITTING yang
#   melewati veto tray; baru server + tray dimatikan.
# - (5) Buka lambat: peluncuran kedua kini fast-path (mutex -> sinyal ->
#   keluar, tanpa server/WebView2 baru). Peluncuran PERTAMA masih dibatasi
#   ekstraksi onefile PyInstaller + cold-start WebView2 (bawaan packaging /
#   runtime, bukan kode ini) — perbaikan 3.5 (listen-first) dipertahankan;
#   opsi lanjutan onedir TIDAK dibangun di 3.9.
# Bukti visual (tengah/tidak terpotong, 1 ikon, Keluar cepat, buka cepat)
# HANYA bisa di PC user.
#
# Catatan jujur:
# - Server KISA (monitor_server.py) TIDAK diubah: port 8000 hardcode,
#   dashboard dibaca dari BASE_DIR server (folder aplikasi / _MEIPASS
#   saat dibungkus PyInstaller onefile).
# - File QR_Dashboard.png ditulis server ke BASE_DIR; dalam mode onefile
#   itu folder sementara PyInstaller (_MEIPASS) yang dihapus saat keluar.
#   Jendela aplikasi menampilkan dashboard langsung, jadi QR tidak wajib.
# - Jendela pywebview TIDAK bisa diuji di VM Linux tanpa display; yang
#   teruji di sini adalah jalur start server + tunggu server siap.
# - Menutup jendela (X) hanya menyembunyikannya ke tray; webview.start()
#   tetap blocking dan aplikasi baru berhenti lewat "Keluar" di tray.

import argparse
import os
import sys
import threading
import time
import urllib.request
import webbrowser
from http.server import ThreadingHTTPServer
from pathlib import Path

APP_NAME = "KISA"
APP_TITLE = "KISA"
PORT = 8000
URL = f"http://127.0.0.1:{PORT}"

# Patch 3.9 (item 3): HARUS sama persis dengan AppId di app/KISA-Setup.iss
# (di .iss ditulis {{3F2A1B4C-...}} karena kurung kurawal di-escape Inno
# Setup; nilai sebenarnya satu kurung kurawal). AppId .iss TIDAK berubah.
APP_USER_MODEL_ID = "{3F2A1B4C-9D8E-4A7F-B123-4C5D6E7F8091}"

# Patch 3.9 (item 3+7): single-instance — nama mutex/event (session-local,
# tanpa butuh hak admin; awalan "Global\" sengaja TIDAK dipakai).
_SINGLE_MUTEX_NAME = "KISA_SingleInstance_3F2A1B4C"
_SHOW_EVENT_NAME = "KISA_ShowWindow_3F2A1B4C"
_single_mutex = None
_single_event = None

_QUITTING = threading.Event()          # Patch 3.9 (item 4): sedang Keluar
_show_window_requested = threading.Event()  # Patch 3.9 (item 7): tampilkan jendela

_server = None          # ThreadingHTTPServer yang sedang jalan
_server_thread = None
_tray_icon = None
_window = None          # Window pywebview yang sedang jalan (None: belum dibuat / mode --tray / fallback browser)


def _app_dir():
    """Folder aplikasi: folder _MEIPASS saat frozen PyInstaller, kalau tidak folder file ini."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # noqa: SLF001 - atribut resmi PyInstaller
    return Path(__file__).resolve().parent


def _resource_path(name):
    """Cari file data: _MEIPASS dulu (frozen), lalu folder aplikasi, lalu folder kerja."""
    for base in (_app_dir(), Path(__file__).resolve().parent, Path.cwd()):
        p = base / name
        if p.exists():
            return str(p)
    return str(_app_dir() / name)


def _exe_path():
    """Path biner aplikasi untuk auto-start. Hanya bermakna saat frozen (Windows)."""
    if getattr(sys, "frozen", False):
        return sys.executable
    return ""


# ------------------------------------------------------- Patch 3.9: jendela & taskbar
def _set_app_user_model_id():
    """Set AppUserModelID proses agar SAMA dengan shortcut installer.

    Patch 3.9 (item 3). Windows saja; di OS lain no-op. Dipanggil di awal
    main(), sebelum jendela dibuat — SetCurrentProcessExplicitAppUserModelID
    harus dipanggil sebelum jendela pertama dibuat agar berlaku untuknya.
    Kegagalan di sini tidak boleh menghentikan aplikasi (try/except)."""
    if os.name != "nt":
        return
    try:
        import ctypes  # noqa: PLC0415 - Windows saja
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass


def _acquire_single_instance():
    """Single-instance (Patch 3.9, item 3 + 7). Windows saja.

    Kembalikan True bila proses ini instance PERTAMA (lanjut jalan normal),
    False bila sudah ada instance lain — dalam hal itu instance pertama
    disinyal lewat named event untuk memunculkan jendelanya, lalu proses
    ini keluar (tanpa server/jendela/tray kedua). Handle mutex disimpan di
    global agar tetap terkunci selama proses hidup. Bila mutex gagal dibuat
    (bukan karena sudah ada), kembalikan True supaya aplikasi tetap jalan."""
    global _single_mutex, _single_event
    if os.name != "nt":
        return True
    try:
        import ctypes  # noqa: PLC0415 - Windows saja
        kernel32 = ctypes.windll.kernel32
        mutex = kernel32.CreateMutexW(None, True, _SINGLE_MUTEX_NAME)
        err = kernel32.GetLastError()
        if err == 183:  # ERROR_ALREADY_EXISTS - instance lain sudah jalan
            try:
                ev = kernel32.OpenEventW(0x0002, False, _SHOW_EVENT_NAME)  # EVENT_MODIFY_STATE
                if ev:
                    kernel32.SetEvent(ev)
                    kernel32.CloseHandle(ev)
            except Exception:
                pass
            try:
                if mutex:
                    kernel32.CloseHandle(mutex)
            except Exception:
                pass
            return False
        _single_mutex = mutex
        _single_event = kernel32.CreateEventW(None, False, False, _SHOW_EVENT_NAME)
        threading.Thread(target=_single_instance_watcher, daemon=True, name="kisa-single").start()
        return True
    except Exception:
        return True


def _single_instance_watcher():
    """Tunggu sinyal 'tampilkan jendela' dari instance kedua, lalu tampilkan.

    Jalan di thread daemon; WaitForSingleObject(INFINITE) pada event
    auto-reset. Bila ada jendela, window.show() (di-marshal ke GUI thread
    oleh backend WinForms: Show + Activate). Bila belum ada jendela (mode
    --tray), _show_window_requested membuat loop utama main() membukanya."""
    if os.name != "nt" or _single_event is None:
        return
    try:
        import ctypes  # noqa: PLC0415 - Windows saja
        kernel32 = ctypes.windll.kernel32
        while True:
            if kernel32.WaitForSingleObject(_single_event, 0xFFFFFFFF) == 0:
                _show_window_requested.set()
                window = _window
                if window is not None:
                    try:
                        window.show()
                    except Exception:
                        pass
    except Exception:
        pass


def _centered_window_geometry(width, height):
    """Hitung (x, y, w, h) agar jendela terbuka DI TENGAH layar utama.

    Patch 3.9 (item 2). Sumber: webview.screens (pywebview 6.2.1,
    __init__.py:513-521 — module property yang menginisialisasi guilib bila
    perlu, aman dipanggil sebelum webview.start()). Tiap Screen membawa
    x/y/width/height logis (Bounds) + frame = WorkingArea (tanpa taskbar,
    winforms.py get_screens()). Dipakai frame bila ada, kalau tidak Bounds.
    Layar utama = yang memuat titik (0,0); kalau tidak ada, screens[0].
    Ukuran dijepit ke area kerja supaya jendela 1280x800 selalu muat
    sepenuhnya (tidak terpotong bawah) di layar apa pun. x/y yang
    dikembalikan dalam piksel LOGIS — satuan yang dipakai pywebview untuk
    x/y create_window (backend WinForms mengalikan lagi dengan scale DPI
    saat menaruh jendela, winforms.py ~214-229). Gagal apa pun ->
    (None, None, width, height) = perilaku CenterScreen lama."""
    try:
        import webview  # noqa: PLC0415
        screens = webview.screens
        scr = None
        for s in screens:
            if s.x == 0 and s.y == 0:
                scr = s
                break
        if scr is None and screens:
            scr = screens[0]
        if scr is not None:
            frame = getattr(scr, "frame", None)
            if frame is not None and getattr(frame, "Width", 0) and getattr(frame, "Height", 0):
                ax, ay, aw, ah = int(frame.X), int(frame.Y), int(frame.Width), int(frame.Height)
            else:
                ax, ay, aw, ah = int(scr.x), int(scr.y), int(scr.width), int(scr.height)
            w = min(int(width), aw)
            h = min(int(height), ah)
            x = ax + max(0, (aw - w) // 2)
            y = ay + max(0, (ah - h) // 2)
            return (x, y, w, h)
    except Exception:
        pass
    return (None, None, width, height)


# ---------------------------------------------------------------- server
def start_server():
    """Jalankan server monitor KISA di thread daemon.

    Patch 3.5 — startup cepat: urutan dibalik dari blok __main__
    monitor_server.py. DULU: cpu_percent + collect() + firewall + QR
    dulu, baru ThreadingHTTPServer dibuat dan serve_forever jalan —
    padahal collect() pertama (semua cache dingin) memanggil belasan
    PowerShell / CIM / GSMTC / LHM berurutan dan bisa makan puluhan
    detik sebelum port 8000 listen, sementara main() menunggu HTTP 200
    di wait_for_server(). SEKARANG: server dibuat + serve_forever
    jalan DULU (port langsung listen, GET / langsung menjawab
    dashboard.html statis tanpa collect), baru sesudahnya pemanasan
    lambat (collect, power thread, firewall, QR) jalan di thread yang
    sama sebagai background — jendela tidak lagi menunggu mereka.
    GET /api/data pertama tetap memanggil collect() seperti biasa
    (di thread request), jadi data menyusul begitu pemanasan selesai.
    Perilaku lain tidak berubah: tray minimize, mode --tray, dan
    fallback browser tetap seperti semula."""
    global _server, _server_thread
    if _server is not None:
        return _server
    if _server_thread is not None and _server_thread.is_alive():
        return _server

    import monitor_server as ms  # noqa: PLC0415 - import lokal disengaja

    def _run():
        global _server
        # 1. Listen DULU — ini satu-satunya yang ditunggu main() /
        #    wait_for_server() sebelum jendela dibuka. Tanpa ini,
        #    semua langkah lambat di bawah memblokir jendela.
        try:
            _server = ThreadingHTTPServer(("0.0.0.0", ms.PORT), ms.Handler)
        except Exception as e:
            print("KISA: gagal membuka port", ms.PORT, "-", e)
            return
        threading.Thread(target=_server.serve_forever, daemon=True,
                         name="kisa-http").start()
        # 2. Pemanasan lambat, SESUDAH listen (background). Urutan sama
        #    seperti blok __main__ monitor_server.py, hanya dipindah ke
        #    belakang serve_forever — masing-masing sudah try/except.
        try:
            ms.psutil.cpu_percent(interval=0.1)
        except Exception:
            pass
        try:
            ms.collect()
        except Exception:
            pass
        try:
            threading.Thread(target=ms._power_thread, daemon=True).start()
        except Exception:
            pass
        try:
            ms._ensure_firewall_rule()
        except Exception:
            pass
        try:
            ms._dashboard_qr()
        except Exception:
            pass
        # serve_forever jalan di thread kisa-http sendiri; thread _run
        # selesai di sini setelah pemanasan, server tetap jalan.

    _server_thread = threading.Thread(target=_run, daemon=True, name="kisa-server")
    _server_thread.start()
    return _server


def wait_for_server(timeout=30.0):
    """Tunggu sampai dashboard menjawab HTTP 200. Kembalikan True bila siap."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(URL + "/", timeout=1) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.25)
    return False


def stop_server():
    """Matikan server HTTP dengan rapi."""
    global _server
    if _server is not None:
        try:
            _server.shutdown()
        except Exception:
            pass
        try:
            _server.server_close()
        except Exception:
            pass
        _server = None


# ---------------------------------------------------------------- auto-start (Windows saja)
def _run_key():
    import winreg  # noqa: PLC0415 - Windows saja
    return winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE,
    )


def get_autostart():
    """True bila KISA terdaftar jalan otomatis saat Windows nyala."""
    if sys.platform != "win32" or not _exe_path():
        return False
    try:
        with _run_key() as key:
            import winreg  # noqa: PLC0415
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except Exception:
        return False


def set_autostart(enable):
    """Daftarkan / hapus KISA dari Run key Windows. Kembalikan True bila berhasil."""
    if sys.platform != "win32" or not _exe_path():
        return False
    try:
        import winreg  # noqa: PLC0415
        with _run_key() as key:
            if enable:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{_exe_path()}" --tray')
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- tray (opsional)
def _tray_image():
    from PIL import Image  # noqa: PLC0415
    path = _resource_path("kisa-192.png")
    img = Image.open(path)
    return img.resize((64, 64))


def _open_in_browser():
    webbrowser.open(URL)


def _open_kisa_window(icon=None, item=None):
    """Menu tray "Buka KISA": tampilkan lagi jendela aplikasi bila ada,
    kalau tidak ada jendela (mode --tray, atau pywebview gagal) fallback
    ke browser. Dipanggil dari thread menu tray; window.show() di-marshal
    ke GUI thread oleh backend WinForms pywebview (Control.Invoke), dan
    dibungkus try/except supaya galatnya tidak mematikan thread tray."""
    global _window
    window = _window
    if window is not None:
        try:
            window.show()
            return
        except Exception:
            pass
    # Patch 3.9 (item 7): tidak ada jendela (mode --tray) — minta loop utama
    # main() membukanya. Beri waktu sekejap; bila jendela tetap tidak ada
    # (pywebview tidak tersedia), fallback ke browser seperti semula.
    _show_window_requested.set()
    for _ in range(10):
        time.sleep(0.1)
        if _window is not None:
            return
    _open_in_browser()


def _on_window_closing():
    """Handler window.events.closing: sembunyikan jendela ke tray dan
    VETO penutupan (return False). Dipanggil sinkron di GUI thread oleh
    pywebview (closing dibuat dengan should_lock=True); return False
    membuat backend WinForms mengeset args.Cancel = True sehingga
    jendela tidak dihancurkan dan webview.start() tetap blocking.
    Selalu return False, juga bila hide() gagal — jendela tetap tampil
    daripada aplikasi mati diam-diam; keluar hanya lewat "Keluar".
    Patch 3.9 (item 4): bila _QUITTING set (Keluar dari tray), kembalikan
    True — penutupan DIIZINKAN supaya jendela dihancurkan dan WebView2
    sempat flush penyimpanan (perbaikan 3.8 tetap terjaga)."""
    if _QUITTING.is_set():
        return True
    global _window
    window = _window
    if window is not None:
        try:
            window.hide()
        except Exception:
            pass
    return False


def _quit_app(icon=None, item=None):
    """Keluar dari tray (Patch 3.9, item 4 — shutdown bertahap + batas waktu).

    Dulu: stop_server() -> icon.stop() -> os._exit(0). Lambatnya bisa dari
    server.shutdown() yang menunggu, atau icon.stop() (pystray) yang
    dipanggil dari thread menu. Sekarang: (1) watchdog 2 detik yang memaksa
    os._exit(0) apa pun yang terjadi — Keluar tidak pernah lebih dari
    ~2 detik; (2) tutup jendela DULU lewat destroy() dengan _QUITTING set
    (melewati veto tray, jadi WebView2 flush localStorage — perbaikan 3.8
    tetap terjaga); (3) tunggu sebentar sampai GUI loop selesai (maks 1
    detik); (4) matikan server + tray; (5) os._exit(0)."""
    _wd = threading.Timer(2.0, lambda: os._exit(0))
    _wd.daemon = True
    _wd.start()
    _QUITTING.set()
    window = _window
    if window is not None:
        try:
            window.destroy()
        except Exception:
            pass
        deadline = time.time() + 1.0
        while time.time() < deadline and _window is not None:
            time.sleep(0.05)
    stop_server()
    try:
        if icon is not None:
            icon.stop()
        elif _tray_icon is not None:
            _tray_icon.stop()
    except Exception:
        pass
    os._exit(0)


def start_tray():
    """Jalankan ikon tray di thread sendiri. Kembalikan False bila pystray tidak ada."""
    global _tray_icon
    try:
        import pystray  # noqa: PLC0415
        from pystray import Menu, MenuItem  # noqa: PLC0415
    except Exception:
        return False

    def _toggle_autostart(icon, item):
        set_autostart(not get_autostart())

    menu = Menu(
        MenuItem("Buka KISA", _open_kisa_window),
        MenuItem("Buka di Browser", lambda icon, item: _open_in_browser()),
        MenuItem(
            "Jalankan saat Windows nyala",
            _toggle_autostart,
            checked=lambda item: get_autostart(),
            enabled=sys.platform == "win32",
        ),
        MenuItem("Keluar", _quit_app),
    )
    try:
        _tray_icon = pystray.Icon(APP_NAME, _tray_image(), APP_TITLE, menu)
        threading.Thread(target=_tray_icon.run, daemon=True, name="kisa-tray").start()
        return True
    except Exception:
        _tray_icon = None
        return False


def stop_tray():
    global _tray_icon
    if _tray_icon is not None:
        try:
            _tray_icon.stop()
        except Exception:
            pass
        _tray_icon = None


# ---------------------------------------------------------------- jendela
def _webview_storage_path():
    """Folder penyimpanan persisten untuk WebView2 (cookies + localStorage).

    Patch 3.8: tanpa ini pywebview 6.2.1 memakai mode privat + folder temp
    sehingga semua pengaturan hilang tiap aplikasi ditutup total.
    Windows: %LOCALAPPDATA%\\KISA\\WebView2 (data lokal mesin, tidak roaming,
    tidak ikut terhapus saat exe di-update). Lainnya: ~/.local/share/KISA/WebView2.
    Folder dibuat bila belum ada; bila gagal dibuat, kembalikan None supaya
    pywebview memakai default-nya (lebih baik daripada aplikasi tidak jalan)."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.path.join(os.path.expanduser("~"), ".local", "share")
    path = os.path.join(base, "KISA", "WebView2")
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        return None
    return path


def open_window():
    """Buka dashboard di jendela aplikasi (pywebview). Kembalikan True bila
    jendela berhasil dibuka, False bila pywebview tidak tersedia.
    Menutup jendela (X) TIDAK mengakhiri aplikasi: handler closing
    mem-veto penutupan dan menyembunyikan jendela ke tray, jadi
    webview.start() di bawah tetap blocking sampai jendela benar-benar
    dihancurkan atau proses dimatikan lewat "Keluar" di tray."""
    global _window
    try:
        import webview  # noqa: PLC0415
    except Exception:
        return False

    # Patch 3.9 (item 2): posisi dihitung eksplisit agar jendela terbuka
    # DI TENGAH layar utama dan selalu muat (tidak terpotong bawah).
    # (None, None) bila gagal dihitung = CenterScreen seperti semula.
    _gx, _gy, _gw, _gh = _centered_window_geometry(1280, 800)
    try:
        window = webview.create_window(
            APP_TITLE, URL, width=_gw, height=_gh, x=_gx, y=_gy,
            resizable=True, text_select=False,
        )
    except Exception:
        return False
    _window = window
    window.events.closing += _on_window_closing
    try:
        # Patch 3.8: private_mode=False + storage_path eksplisit — tanpa ini
        # pywebview 6.2.1 default private_mode=True (localStorage tidak
        # tersimpan) dan folder user-data jatuh ke temp. Jangan ubah lagi
        # ke webview.start() tanpa argumen.
        webview.start(private_mode=False, storage_path=_webview_storage_path())
    except Exception:
        _window = None
        return False
    # GUI loop benar-benar berakhir (jendela dihancurkan): tidak ada lagi
    # window yang bisa ditampilkan dari tray.
    _window = None
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(prog="KISA", description="Aplikasi monitor PC KISA.")
    parser.add_argument("--tray", action="store_true",
                        help="Jalan di tray saja, tanpa membuka jendela.")
    parser.add_argument("--install-autostart", action="store_true",
                        help="Daftarkan KISA ke auto-start Windows lalu keluar.")
    parser.add_argument("--remove-autostart", action="store_true",
                        help="Hapus KISA dari auto-start Windows lalu keluar.")
    args = parser.parse_args(argv)

    if args.install_autostart:
        print("Auto-start:", "OK" if set_autostart(True) else "gagal / bukan Windows")
        return 0
    if args.remove_autostart:
        print("Auto-start dihapus:", "OK" if set_autostart(False) else "gagal / bukan Windows")
        return 0

    # Patch 3.9 (item 3+7): AppUserModelID + single-instance, SEBELUM
    # server/jendela. Instance kedua: sinyal instance pertama untuk
    # menampilkan jendelanya, lalu keluar — tanpa server/jendela kedua.
    _set_app_user_model_id()
    if not _acquire_single_instance():
        print("KISA: sudah berjalan — menampilkan jendela yang ada.")
        return 0

    start_server()
    if not wait_for_server(timeout=30.0):
        print("KISA: server tidak menjawab di", URL)
        stop_server()
        return 1

    tray_ok = start_tray()

    if not args.tray:
        if open_window():
            # GUI loop berakhir (jendela benar-benar dihancurkan) -> keluar
            # dengan rapi. Catatan: tombol X biasa TIDAK sampai ke sini —
            # handler closing mem-veto dan menyembunyikan jendela ke tray,
            # jadi webview.start() tetap blocking dan tray tetap hidup.
            stop_tray()
            stop_server()
            return 0
        # pywebview tidak ada: fallback browser.
        _open_in_browser()

    # Mode tray / fallback: jalan sampai user memilih Keluar dari tray
    # (atau Ctrl+C bila dijalankan dari terminal).
    # Patch 3.9 (item 7): loop ini juga melayani permintaan tampilkan
    # jendela — klik ikon taskbar / desktop / Start menu saat instance
    # sudah jalan di tray, atau menu tray "Buka KISA" saat belum ada
    # jendela. Tanpa ini, peluncuran kedua hanya diam (item 7).
    try:
        while True:
            if _show_window_requested.wait(timeout=0.5):
                _show_window_requested.clear()
                if open_window():
                    # GUI loop berakhir (jendela dihancurkan saat Keluar)
                    stop_tray()
                    stop_server()
                    return 0
                _open_in_browser()
    except KeyboardInterrupt:
        pass
    finally:
        stop_tray()
        stop_server()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
