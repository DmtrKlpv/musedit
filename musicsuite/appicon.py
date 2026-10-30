"""Иконка приложения: загрузка и установка на окно.

Почему иконка в заголовке не берётся из EXE
-------------------------------------------
`pyinstaller --icon` встраивает картинку в ресурсы исполняемого файла.
Windows показывает её в проводнике, на панели задач и в Alt+Tab.
Но Qt рисует заголовок своего окна сам и про эти ресурсы не знает —
поэтому на кнопке окна остаётся стандартная иконка Qt, если не вызвать
`setWindowIcon`.

Отсюда два независимых места:
  * .ico в EXE — для проводника и панели задач;
  * setWindowIcon — для рамки окна и переключателя Alt+Tab.

Иконка кладётся в нескольких размерах: 16 и 24 для заголовка, 32 для
панели задач, 256 для крупных представлений. Один размер 32×32 именно
поэтому и «не отображался»: Windows для заголовка берёт 16×16, и при
отсутствии такого размера масштабирует единственный имеющийся, теряя
чёткость вплоть до полной неразличимости.
"""

from __future__ import annotations

import os
import sys

from PySide6.QtGui import QIcon

# Порядок важен: Qt берёт первый найденный вариант. PNG читается
# надёжнее на Linux/macOS, ICO нужен Windows для правильных размеров.
_CANDIDATES = ("icon.ico", "icon.png")


def assets_dir() -> str:
    """Папка с ресурсами — работает и в собранном EXE, и из исходников."""
    if getattr(sys, "frozen", False):
        # PyInstaller распаковывает datas в _MEIPASS
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "assets")


def icon_path() -> str | None:
    """Путь к существующему файлу иконки или None."""
    folder = assets_dir()
    for name in _CANDIDATES:
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            return path
    return None


def app_icon() -> QIcon:
    """QIcon приложения.

    В .ico лежат все размеры, поэтому Qt сам выберет подходящий для
    заголовка, панели задач и Alt+Tab.
    """
    path = icon_path()
    if not path:
        return QIcon()

    icon = QIcon(path)
    # Добавляем PNG как fallback на случай, если Qt не разобрал ICO
    # (бывает на старых сборках Qt под Linux).
    png = os.path.join(assets_dir(), "icon.png")
    if os.path.isfile(png) and icon.isNull():
        icon = QIcon(png)
    return icon
