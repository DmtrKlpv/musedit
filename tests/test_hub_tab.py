"""Проверка объединённой вкладки «Яндекс.Музыка и плейлисты».

Три утилиты жили отдельными вкладками, теперь — три режима одной вкладки.
Здесь проверяем, что после слияния ничего не отвалилось:

  1. в окне пять вкладок, первая — объединённая;
  2. переключение режимов меняет панель и сохраняет состояние полей;
  3. построчная таблица скачивания работает в скрытом режиме;
  4. создание плейлиста реально пишет файл изнутри объединённой вкладки;
  5. у каждой панели своя синяя кнопка запуска.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from musicsuite.engines import plscreate

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


app = QApplication.instance() or QApplication([])

# Модальные окна в offscreen блокируют прогон.
QMessageBox.information = staticmethod(lambda *a, **k: OUT.write("  [диалог info]\n"))
QMessageBox.warning = staticmethod(lambda *a, **k: OUT.write(f"  [диалог warn] {a[2]}\n"))

from musicsuite.main_window import MainWindow

window = MainWindow()
window.show()
pump(200)

OUT.write("--- 1. Структура окна ---\n")
titles = [window.tabs.tabText(i) for i in range(window.tabs.count())]
for index, title in enumerate(titles, start=1):
    OUT.write(f"  {index}. {title}\n")

ok("вкладок стало пять", window.tabs.count() == 5)
ok("первая вкладка — объединённая",
   titles[0] == "Яндекс.Музыка и плейлисты")
ok("отдельных вкладок экспорта и скачивания больше нет",
   "Экспорт из Яндекс.Музыки" not in titles
   and "Скачивание из Яндекс.Музыки" not in titles
   and "Создание плейлистов" not in titles)

hub = window.hub_tab

OUT.write("\n--- 2. Переключение режимов ---\n")
ok("режимов три", hub.stack.count() == 3)

for index in range(3):
    hub.set_mode(index)
    panel = hub.active_panel()
    OUT.write(f"  режим {index + 1}: {panel.TITLE}\n")
    ok(f"режим {index} переключился", hub.current_mode() == index)
    ok(f"кнопка режима {index} нажата",
       hub._buttons.button(index).isChecked())

# Состояние полей не должно теряться при переключении
hub.set_mode(1)
hub.download_panel.timeout_spin.setValue(42)
hub.set_mode(0)
hub.set_mode(1)
ok("значение поля сохранилось после переключения",
   hub.download_panel.timeout_spin.value() == 42)

OUT.write("\n--- 3. Построчная таблица скачивания ---\n")
dl = hub.download_panel
dl.tracks_tree.clear()
hub.set_mode(0)     # панель скрыта, а строки должны добавляться
for index, name in enumerate(["A - One", "B - Two", "C - Three"], start=1):
    dl.track_row.emit({"title": name, "bitrate": "MP3 320 kbps",
                       "size": "8 МБ", "status": "Скачано"})
    pump(80)
    OUT.write(f"  после трека {index}: строк = {dl.tracks_tree.topLevelItemCount()}\n")
ok("таблица наполняется в скрытом режиме",
   dl.tracks_tree.topLevelItemCount() == 3)

OUT.write("\n--- 4. Создание плейлиста из объединённой вкладки ---\n")
tmp = tempfile.mkdtemp(prefix="hub_")
# Движок создаёт по одному плейлисту на каждую ВЛОЖЕННУЮ папку,
# поэтому треки кладём в подпапку Album, а указываем корень music.
music = os.path.join(tmp, "music")
album = os.path.join(music, "Album")
make_track(os.path.join(album, "Artist - Track One.mp3"))
make_track(os.path.join(album, "Artist - Track Two.mp3"))

out_dir = os.path.join(tmp, "playlists")
os.makedirs(out_dir, exist_ok=True)

pl_panel = hub.playlist_panel
hub.set_mode(2)
pl_panel.music_field.setText(music)
pl_panel.save_field.setText(out_dir)
pl_panel.format_combo.setCurrentText("m3u8")

pl_panel.on_generate()
for _ in range(80):
    pump(100)
    if not pl_panel.is_busy():
        break
pump(300)

created = []
for root, _, files in os.walk(out_dir):
    for name in files:
        if name.endswith(".m3u8"):
            created.append(os.path.join(root, name))

OUT.write(f"  создано файлов: {len(created)}\n")
for path in created:
    OUT.write(f"    {os.path.basename(path)}\n")
    for line in open(path, encoding="utf-8").read().strip().splitlines():
        OUT.write(f"      {line}\n")

ok("плейлист создан из объединённой вкладки", len(created) >= 1)
if created:
    content = open(created[0], encoding="utf-8").read()
    ok("в плейлисте два трека", content.count(".mp3") == 2)

OUT.write("\n--- 5. Синие кнопки по режимам ---\n")
for index in range(3):
    hub.set_mode(index)
    panel = hub.active_panel()
    blue = [b.text() for b in panel.findChildren(QPushButton)
            if b.objectName() == "primary"]
    OUT.write(f"  {panel.TITLE}: {blue}\n")
    ok(f"в режиме {index} ровно одна синяя кнопка", len(blue) == 1)

OUT.write("\n--- 6. Общая занятость ---\n")
ok("is_busy объединяет три панели", hub.is_busy() is False)

OUT.write("\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ\n")
