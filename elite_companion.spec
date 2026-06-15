# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Elite Companion
# Build:  py -m PyInstaller elite_companion.spec

import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Collect all watchdog and pystray submodules so the dynamic backend
# imports they use at runtime are included in the bundle.
hidden_imports = [
    # watchdog — Windows backend
    "watchdog.observers.winapi",
    "watchdog.observers.read_directory_changes",
    "watchdog.observers.polling",
    "watchdog.observers.api",
    # pystray — Windows backend
    "pystray._win32",
    "pystray._util",
    # pyserial — port enumeration
    "serial.tools.list_ports",
    "serial.tools.list_ports_windows",
    # PIL/Pillow image modules used by tray icon drawing
    "PIL.Image",
    "PIL.ImageDraw",
    # tkinter — config window
    "tkinter",
    "tkinter.ttk",
    "tkinter.filedialog",
    "tkinter.messagebox",
]

a = Analysis(
    ["run.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude large unused packages that may be pulled in transitively
        "matplotlib",
        "numpy",
        "scipy",
        "pandas",
        "IPython",
        "jupyter",
    ],
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
    name="EliteCompanion",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,         # UPX can cause false-positive AV alerts — keep off
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,     # no console window — runs silently in background
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon="assets/icon.ico",  # uncomment when an .ico asset is added
)
