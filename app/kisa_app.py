# kisa_app.py — Launcher aplikasi KISA (Patch 3.3, S138 Cara 3).
#
# Menjalankan server monitor KISA di dalam proses aplikasi (thread),
# lalu membuka dashboard di jendela aplikasi sendiri (pywebview).
# Kalau pywebview tidak tersedia, fallback: buka browser default.
# Ikon tray (pystray) + auto-start Windows bersifat opsional dan
# semuanya dijaga try/except supaya aplikasi tetap jalan tanpa mereka.
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

_server = None          # ThreadingHTTPServer yang sedang jalan
_server_thread = None
_tray_icon = None


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


# ---------------------------------------------------------------- server
def start_server():
    """Jalankan server monitor KISA di thread daemon. Meniru blok __main__
    monitor_server.py (cpu_percent, collect, power thread, HTTP server)."""
    global _server, _server_thread
    if _server_thread is not None and _server_thread.is_alive():
        return _server

    import monitor_server as ms  # noqa: PLC0415 - import lokal disengaja

    def _run():
        global _server
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
        _server = ThreadingHTTPServer(("0.0.0.0", ms.PORT), ms.Handler)
        try:
            ms._ensure_firewall_rule()
        except Exception:
            pass
        try:
            ms._dashboard_qr()
        except Exception:
            pass
        try:
            _server.serve_forever()
        except Exception:
            pass

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


def _quit_app(icon=None, item=None):
    stop_server()
    try:
        if icon is not None:
            icon.stop()
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
        MenuItem("Buka KISA", lambda icon, item: _open_in_browser()),
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
def open_window():
    """Buka dashboard di jendela aplikasi (pywebview). Kembalikan True bila
    jendela berhasil dibuka, False bila pywebview tidak tersedia."""
    try:
        import webview  # noqa: PLC0415
    except Exception:
        return False
    
    window = webview.create_window(
        APP_TITLE, URL, width=1280, height=800, resizable=True,
        text_select=False,

    )
    try:
        webview.start()
    except Exception:
        return False
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

    start_server()
    if not wait_for_server(timeout=30.0):
        print("KISA: server tidak menjawab di", URL)
        stop_server()
        return 1

    tray_ok = start_tray()

    if not args.tray:
        if open_window():
            # Jendela ditutup user -> keluar dengan rapi.
            stop_tray()
            stop_server()
            return 0
        # pywebview tidak ada: fallback browser.
        _open_in_browser()

    # Mode tray / fallback: jalan sampai user memilih Keluar dari tray
    # (atau Ctrl+C bila dijalankan dari terminal).
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        stop_tray()
        stop_server()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
