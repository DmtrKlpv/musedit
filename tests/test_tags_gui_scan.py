"""Регрессия GUI: нажатие «Сканировать» во вкладке тегов не должно падать.

Ошибка была такова: вкладка вызывала scan_directory(..., progress=...),
а движок такого аргумента не принимал → TypeError в рабочем потоке.
Здесь доводим сценарий до конца через реальный виджет и реальные MP3.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _helpers import make_mp3

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication


def pump(ms=150):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


app = QApplication.instance() or QApplication([])

from musicsuite.main_window import MainWindow

window = MainWindow()
out = sys.__stdout__   # MainWindow перехватывает stdout в свою консоль
tab = window.tags_tab
window.tabs.setCurrentWidget(tab)

tmp = tempfile.mkdtemp(prefix="fixtags_gui_")
for index, (title, album) in enumerate([
    ("Vallйe De Larmes", "Dьsseldorf, Germany"),
    ("Vallée De Larmes", "Düsseldorf, Germany"),
], start=1):
    make_mp3(os.path.join(tmp, f"track{index}.mp3"), title, album)

tab.music_field.setText(tmp)
tab.ext_edit.setText(".mp3")

out.write("--- нажимаем «Сканировать» ---")
tab.on_scan()

for _ in range(80):
    pump(100)
    if not tab.is_busy():
        break
pump(300)

out.write(f"статус:    {tab.status_label.text()}\n")
out.write(f"строк:     {tab.table.topLevelItemCount()}\n")
out.write(f"прогресс:   {tab.progress_panel.text_label.text()!r} "
          f"{tab.progress_panel.counter_label.text()!r}\n")

assert tab.table.topLevelItemCount() > 0, "таблица пуста — сканирование не отработало"
assert "Ошибка" not in tab.status_label.text(), "в статусе ошибка"

out.write("\nOK: сканирование из вкладки проходит без TypeError\n")
out.flush()
