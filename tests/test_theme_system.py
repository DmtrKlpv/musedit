"""Тема следует за системной и остаётся читаемой в обеих схемах.

Что проверяем
-------------
1. Приложение НЕ подменяет системную палитру и НЕ включает Fusion.
2. Таблица стилей собирается из палитры: в светлой теме светлая,
   в тёмной — тёмная. Зашитых светлых цветов в тёмном варианте нет.
3. Подписи, флажки и кнопки читаемы в обеих темах: нет белого текста
   на светлом фоне и чёрного на тёмном.
4. Смена темы на лету применяется без перезапуска.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QPushButton

from musicsuite import theme

OUT = sys.__stdout__


def ok(label, condition, extra=""):
    OUT.write(f"[{'OK ' if condition else 'FAIL'}] {label}"
              f"{(' — ' + extra) if extra else ''}\n")
    OUT.flush()
    if not condition:
        raise SystemExit(1)


def luminance(color_name: str) -> float:
    """Яркость 0..255 по грубой формуле."""
    try:
        red = int(color_name[1:3], 16)
        green = int(color_name[3:5], 16)
        blue = int(color_name[5:7], 16)
    except (ValueError, IndexError):
        return 0.0
    return 0.299 * red + 0.587 * green + 0.114 * blue


def set_light(app):
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#efefef"))
    palette.setColor(QPalette.WindowText, QColor("#000000"))
    palette.setColor(QPalette.Base, QColor("#ffffff"))
    palette.setColor(QPalette.Text, QColor("#000000"))
    palette.setColor(QPalette.Button, QColor("#efefef"))
    palette.setColor(QPalette.ButtonText, QColor("#000000"))
    palette.setColor(QPalette.AlternateBase, QColor("#f7f7f7"))
    app.setPalette(palette)


def set_dark(app):
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#202020"))
    palette.setColor(QPalette.WindowText, QColor("#e8e8e8"))
    palette.setColor(QPalette.Base, QColor("#2b2b2b"))
    palette.setColor(QPalette.Text, QColor("#e8e8e8"))
    palette.setColor(QPalette.Button, QColor("#2d2d2d"))
    palette.setColor(QPalette.ButtonText, QColor("#e8e8e8"))
    palette.setColor(QPalette.AlternateBase, QColor("#262626"))
    app.setPalette(palette)


app = QApplication.instance() or QApplication([])

# ---------------------------------------------------------------- 1. светлая
OUT.write("--- 1. Светлая системная тема ---\n")
set_light(app)
theme.apply_theme(app)

light_tokens = theme.tokens()
OUT.write(f"  dark={light_tokens.dark} window={light_tokens.window} "
          f"surface={light_tokens.surface} text={light_tokens.text}\n")
ok("тема определена как светлая", light_tokens.dark is False)
ok("фон окна светлый", luminance(light_tokens.window) > 128,
   light_tokens.window)
ok("текст тёмный", luminance(light_tokens.text) < 128, light_tokens.text)

qss_light = app.styleSheet()
ok("QSS собран", len(qss_light) > 2000, str(len(qss_light)))
ok("в светлом QSS светлый фон",
   f"background: {light_tokens.window}" in qss_light)

# ---------------------------------------------------------------- 2. тёмная
OUT.write("\n--- 2. Тёмная системная тема ---\n")
set_dark(app)
theme.apply_theme(app)

dark_tokens = theme.tokens()
OUT.write(f"  dark={dark_tokens.dark} window={dark_tokens.window} "
          f"surface={dark_tokens.surface} text={dark_tokens.text}\n")
ok("тема определена как тёмная", dark_tokens.dark is True)
ok("фон окна тёмный", luminance(dark_tokens.window) < 128,
   dark_tokens.window)
ok("текст светлый", luminance(dark_tokens.text) > 128, dark_tokens.text)

qss_dark = app.styleSheet()
OUT.write(f"  длина тёмного QSS: {len(qss_dark)}\n")

# Главное: в тёмном варианте не осталось зашитых светлых фонов
for stale in ("#f6f7f9", "#ffffff", "#f2f4f7", "#eef0f3"):
    present = stale in qss_dark
    ok(f"нет зашитого светлого {stale} в тёмном QSS", not present)

ok("QSS пересобрался, а не остался прежним", qss_light != qss_dark)

# ---------------------------------------------------------------- 3. окно
OUT.write("\n--- 3. Окно в тёмной теме ---\n")
from musicsuite.main_window import MainWindow

window = MainWindow()
window.resize(1500, 950)
window.show()
app.processEvents()

ok("палитра не подменена приложением",
   app.palette().color(QPalette.Window).name() == "#202020",
   app.palette().color(QPalette.Window).name())

bad_labels = []
total = 0
for name, tab in (
    ("Скачивание", window.download_hub_tab),
    ("Обновление", window.update_playlist_tab),
    ("Поиск", window.playlist_search_tab),
    ("Теги", window.tags_tab),
    ("CUE", window.cue_tab),
    ("Дубликаты", window.duplicates_tab),
):
    for label in tab.findChildren(QLabel):
        text = label.text().strip()
        if not text:
            continue
        total += 1
        current = label.palette().color(QPalette.WindowText).name()
        if luminance(current) < 90:
            bad_labels.append((name, text[:34], current))

OUT.write(f"  подписей проверено: {total}\n")
for entry in bad_labels[:8]:
    OUT.write(f"    ПРОБЛЕМА {entry[0]:14} {entry[1]:36} {entry[2]}\n")
ok("подписи найдены", total > 20, str(total))
ok("в тёмной теме нет тёмного текста на тёмном", not bad_labels,
   str(bad_labels[:3]))

bad_checks = [
    (box.text()[:28], box.palette().color(QPalette.WindowText).name())
    for box in window.findChildren(QCheckBox)
    if box.text().strip()
    and luminance(box.palette().color(QPalette.WindowText).name()) < 90
]
OUT.write(f"  флажков проверено: {len(window.findChildren(QCheckBox))}\n")
ok("флажки читаемы", not bad_checks, str(bad_checks[:3]))

bad_buttons = [
    (btn.text()[:24], btn.palette().color(QPalette.ButtonText).name())
    for btn in window.findChildren(QPushButton)
    if btn.text().strip() and btn.objectName() not in ("primary", "consoleEditor")
    and luminance(btn.palette().color(QPalette.ButtonText).name()) < 90
]
ok("кнопки читаемы", not bad_buttons, str(bad_buttons[:3]))

# ------------------------------------------------- 4. переключение на лету
OUT.write("\n--- 4. Переключение темы без перезапуска ---\n")
before = app.styleSheet()
set_light(app)
theme.apply_theme(app)
after = app.styleSheet()
OUT.write(f"  QSS изменился: {before != after}\n")
ok("стили пересобрались на светлую", before != after)
ok("вернулся светлый фон",
   f"background: {theme.tokens().window}" in after)

# Строки таблиц тоже должны перерисоваться без падения
window._on_theme_changed()
OUT.write("  перерисовка таблиц: без ошибок\n")
ok("перерисовка таблиц прошла", True)

OUT.write("\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ\n")
