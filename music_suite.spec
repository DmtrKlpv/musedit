# -*- mode: python ; coding: utf-8 -*-
"""Спецификация PyInstaller для сборки «Музыкальные утилиты».

Сборка:
    pyinstaller --clean --noconfirm music_suite.spec

О пакетах, которые нельзя импортировать целиком
------------------------------------------------
``collect_submodules`` не просто перечисляет модули пакета — он каждый
импортирует, чтобы проверить, что тот собирается. На этом сборка выдавала
два предупреждения, хотя оба модуля приложению не нужны:

**yandex_music.ynison** — плеер Ynison (удалённое управление воспроизведением
через WebSocket). Требует ``betterproto`` и ``websockets>=13``, которых в
requirements.txt нет. Приложение использует только ``Client`` для загрузки
треков, Ynison не вызывается нигде. Тянуть две лишние зависимости и десяток
мегабайт в сборку незачем — модуль исключён.

**send2trash.mac / send2trash.win** — платформенные реализации Корзины.
Пакет при импорте выбирает нужную по ``sys.platform``. Модуль чужой
платформы не импортируется никогда: ``send2trash.mac`` на не-macOS падает
с ``ValueError: invalid literal for int() with base 10`` — это разбор
``platform.mac_ver()``, который вне мака возвращает пустую строку. Поэтому
собираем только реализацию текущей платформы.
"""

import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hiddenimports = []

# --- yandex_music: всё, кроме Ynison -----------------------------------
# Ynison требует betterproto и websockets, которых нет в зависимостях.
# Приложение его не использует — исключаем целиком, без предупреждения.
hiddenimports += collect_submodules(
    "yandex_music",
    filter=lambda name: not name.startswith("yandex_music.ynison"),
)

hiddenimports += collect_submodules("mutagen")

# --- send2trash: только реализация текущей платформы -------------------
# Модуль чужой платформы не импортируется в принципе, а его импорт при
# сборе падает с ValueError на разборе версии системы.
_FOREIGN_TRASH = {
    "win32": ("send2trash.mac",),
    "darwin": ("send2trash.win",),
}.get(sys.platform, ("send2trash.mac", "send2trash.win"))

hiddenimports += collect_submodules(
    "send2trash",
    filter=lambda name: not name.startswith(_FOREIGN_TRASH),
)

hiddenimports += ["tqdm", "requests", "urllib.request", "zipfile", "tarfile"]

datas = []
datas += collect_data_files("yandex_music")

# Иконка должна попасть внутрь сборки: приложение читает её во время
# работы для setWindowIcon. Без этой строки в EXE окажется только
# встроенный ресурс, а Qt его не видит.
datas += [("musicsuite/assets/icon.ico", "assets"),
          ("musicsuite/assets/icon.png", "assets")]

ICON_PATH = "musicsuite/assets/icon.ico"

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
        # Модули, которые не собираются и не используются
        "yandex_music.ynison",
        "betterproto",
        "websockets",
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
    name="MusEdit",
    icon=ICON_PATH,
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
    name="MusEdit",
)
