"""Проверка вкладки «Обновление плейлиста»: два списка, цветовая разметка, запись.

Сценарий повторяет пользовательский: открыт плейлист из трёх треков, в папке
один из них удалён, один переехал в подпапку, один добавлен новый.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QMessageBox

from musicsuite.engines import plscreate
from musicsuite.engines import update_playlist as engine

OUT = sys.__stdout__


def ok(label, condition):
    OUT.write(f"[{'OK ' if condition else 'FAIL'}] {label}\n")
    OUT.flush()
    if not condition:
        raise SystemExit(1)


def pump(ms=120):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def make_track(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as stream:
        stream.write(b"\xFF\xFB\x90\x64" + b"\x00" * 200)


tmp = tempfile.mkdtemp(prefix="upl_gui_")
music = os.path.join(tmp, "Music")

make_track(os.path.join(music, "Artist - One.mp3"))
make_track(os.path.join(music, "Artist - Two.mp3"))
make_track(os.path.join(music, "Artist - Moved.mp3"))
make_track(os.path.join(music, "Artist - Fresh.mp3"))

playlist = os.path.join(tmp, "mix.m3u8")
plscreate.save_playlist(
    playlist,
    ["Artist - One.mp3", "Artist - Two.mp3", "Artist - Moved.mp3"],
    "m3u8", "mix",
)

# Меняем папку: Two удалён, Moved переехал в подпапку, Fresh добавлен.
os.remove(os.path.join(music, "Artist - Two.mp3"))
os.makedirs(os.path.join(music, "Sub"), exist_ok=True)
os.rename(os.path.join(music, "Artist - Moved.mp3"),
          os.path.join(music, "Sub", "Artist - Moved.mp3"))

OUT.write("--- 1. Движок: сравнение ---\n")
res = engine.compare(playlist, music)
OUT.write(f"  плейлист: {len(res.entries)}, папка: {len(res.files)}\n")
OUT.write(f"  нет в папке: {[e.original for e in res.missing]}\n")
OUT.write(f"  новые:       {[f.display for f in res.new]}\n")
OUT.write(f"  совпало:     {[e.original for e in res.kept]}\n")

ok("плейлист прочитан полностью", len(res.entries) == 3)
ok("папка отсканирована", len(res.files) == 3)
ok("пропавший трек найден", len(res.missing) == 1
   and res.missing[0].original == "Artist - Two.mp3")
ok("новый файл найден", len(res.new) == 1
   and res.new[0].display == "Artist - Fresh.mp3")
ok("переехавший трек сопоставлен по имени", len(res.kept) == 2)

OUT.write("\n--- 2. Вкладка: таблицы и цвет ---\n")

# Модальные окна в offscreen ждут нажатия — подменяем на запись в лог.
QMessageBox.information = staticmethod(lambda *a, **k: OUT.write("  [диалог info]\n"))
QMessageBox.warning = staticmethod(lambda *a, **k: OUT.write(f"  [диалог warning] {a[2]}\n"))

app = QApplication.instance() or QApplication([])
from musicsuite.main_window import MainWindow

window = MainWindow()
tab = window.update_playlist_tab
window.tabs.setCurrentWidget(tab)

OUT.write(f"  вкладка на позиции: {window.tabs.indexOf(tab) + 1}\n")
ok("вкладка присутствует в окне", window.tabs.indexOf(tab) >= 0)

tab.playlist_field.setText(playlist)
tab.folder_field.setText(music)

for _ in range(80):
    pump(100)
    if not tab.is_busy():
        break
pump(300)

left = tab.playlist_tree
right = tab.folder_tree
OUT.write(f"  строк слева: {left.topLevelItemCount()}, справа: {right.topLevelItemCount()}\n")
OUT.write(f"  счётчик: {tab.counts_label.text()}\n")

for i in range(left.topLevelItemCount()):
    item = left.topLevelItem(i)
    colour = item.background(0).color().name()
    OUT.write(f"    Л {item.text(0):14} {item.text(1):24} bg={colour}\n")
for i in range(right.topLevelItemCount()):
    item = right.topLevelItem(i)
    colour = item.background(0).color().name()
    OUT.write(f"    П {item.text(0):14} {item.text(1):24} bg={colour}\n")

ok("левая таблица заполнена", left.topLevelItemCount() == 3)
ok("правая таблица заполнена", right.topLevelItemCount() == 3)

pink = QColor("#fde2e4").name()
green = QColor("#e3f6e5").name()

missing_items = [left.topLevelItem(i) for i in range(left.topLevelItemCount())
                 if left.topLevelItem(i).text(0) == "Нет в папке"]
new_items = [right.topLevelItem(i) for i in range(right.topLevelItemCount())
             if right.topLevelItem(i).text(0) == "Новый файл"]

ok("пропавшая строка одна", len(missing_items) == 1)
ok("пропавшая строка розовая",
   missing_items[0].background(0).color().name() == pink)
ok("новый файл один", len(new_items) == 1)
ok("новый файл светло-зелёный",
   new_items[0].background(0).color().name() == green)
ok("структура на месте", hasattr(tab, "playlist_tree") and hasattr(tab, "folder_tree"))
ok("кнопка обновления активна", tab.run_btn.isEnabled())

OUT.write("\n--- 3. Запись плейлиста ---\n")

tab.on_update()
for _ in range(80):
    pump(100)
    if not tab.is_busy():
        break
pump(500)

content = open(playlist, encoding="utf-8").read()
OUT.write("  итоговый файл:\n")
for line in content.strip().splitlines():
    OUT.write(f"    {line}\n")

ok("пропавший трек убран", "Artist - Two" not in content)
ok("существующий трек остался", "Artist - One" in content)
ok("новый трек дописан", "Artist - Fresh" in content)
ok("порядок сохранён (One раньше Fresh)",
   content.index("Artist - One") < content.index("Artist - Fresh"))

OUT.write("\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ\n")
