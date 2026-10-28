# -*- mode: python ; coding: utf-8 -*-
"""Спецификация PyInstaller для сборки «Музыкальные утилиты».

Сборка:
    pyinstaller --clean --noconfirm music_suite.spec
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hiddenimports = []
hiddenimports += collect_submodules("yandex_music")
hiddenimports += collect_submodules("mutagen")
hiddenimports += collect_submodules("send2trash")
hiddenimports += ["tqdm", "requests", "urllib.request", "zipfile", "tarfile"]

datas = []
datas += collect_data_files("yandex_music")

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3DCore",
        "PySide6.QtMultimedia",
        "PySide6.QtQuick",
        "PySide6.QtQml",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Музыкальные утилиты",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Музыкальные утилиты",
)
