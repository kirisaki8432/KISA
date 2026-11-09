# -*- mode: python ; coding: utf-8 -*-
# KISA.spec — PyInstaller untuk KISA.exe (Windows).
# Jalankan dari root repo (folder yang berisi dashboard.html):
#     pip install -r app/requirements-app.txt
#     pyinstaller app/KISA.spec
# Hasil: dist/KISA.exe (onefile, tanpa console).
#
# Catatan:
# - monitor_server di-import kisa_app.py, jadi ikut terbungkus sebagai modul.
#   BASE_DIR server saat frozen = folder _MEIPASS, sehingga dashboard.html,
#   publisher/ dan covers/ harus ikut sebagai data di root bundle (di bawah).
# - winrt/segno di-import server secara lazy (di dalam fungsi) + guarded,
#   jadi harus disebut eksplisit di hiddenimports.
# - Dibangun HANYA di Windows (atau runner windows-latest GitHub Actions);
#   PyInstaller Linux tidak bisa menghasilkan .exe Windows.

import os

SPECPATH_DIR = SPECPATH  # noqa: F821 - disediakan PyInstaller
ROOT = os.path.join(SPECPATH_DIR, "..")

block_cipher = None

a = Analysis(
    [os.path.join(SPECPATH_DIR, "kisa_app.py")],
    pathex=[SPECPATH_DIR],
    binaries=[],
    datas=[
        (os.path.join(ROOT, "dashboard.html"), "."),
        (os.path.join(ROOT, "publisher"), "publisher"),
        (os.path.join(ROOT, "covers"), "covers"),
        (os.path.join(SPECPATH_DIR, "icons", "kisa.ico"), "."),
        (os.path.join(SPECPATH_DIR, "icons", "kisa-192.png"), "."),
    ],
    hiddenimports=[
        "psutil",
        "segno",
        "winrt",
        "winrt.windows.media.control",
        "winrt.windows.foundation",
        "winrt.windows.storage.streams",
        "webview",
        "pystray",
        "PIL",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="KISA",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(SPECPATH_DIR, "icons", "kisa.ico"),
)
