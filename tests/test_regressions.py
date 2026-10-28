"""Регрессия на три исправленных бага и новую единую вкладку.

  1. TypeError: TagsTab.on_fix_one.<locals>.<lambda>() takes 0 positional
     arguments but 1 was given — start_task принудительно включал progress.
  2. Кнопка «Исправить» в строке должна быть фиксированной короткой длины.
  3. Консоль при сканировании тегов не должна печатать каждый файл.
  4. Создание плейлистов для плоской папки без подпапок.
  5. Единая вкладка «Скачивание с Яндекс.Музыки»: поля, таблица, конвейер.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from _helpers import make_mp3
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


app = QApplication.instance() or QApplication([])

QMessageBox.information = staticmethod(lambda *a, **k: OUT.write("  [диалог info]\n"))
QMessageBox.warning = staticmethod(lambda *a, **k: OUT.write(f"  [диалог warn] {a[2]}\n"))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)

from musicsuite.main_window import MainWindow
from musicsuite.tabs import base as base_module

# ---------------------------------------------------------------- баг 1
OUT.write("--- 1. start_task и лямбда без аргументов ---\n")

from musicsuite.workers import TaskWorker

ok("лямбда без progress не получает его автоматически",
   TaskWorker(lambda: 42, with_progress=None)._with_progress is False)
ok("функция с progress получает его",
   TaskWorker(lambda progress: 42, with_progress=None)._with_progress is True)

import inspect
sig = inspect.signature(base_module.BaseTab.start_task)
ok("use_progress по умолчанию не форсирует True",
   sig.parameters["use_progress"].default is None)

# ---------------------------------------------------------------- баг 2 и 3
OUT.write("\n--- 2. Кнопка «Исправить» и консоль ---\n")

tmp = tempfile.mkdtemp(prefix="tags_")
music = os.path.join(tmp, "Music")
make_mp3(os.path.join(music, "track1.mp3"), "Vallйe De Larmes", "Dьsseldorf")
make_mp3(os.path.join(music, "track2.mp3"), "Vallйe Deux", "Dьsseldorf")

window = MainWindow()
window.show()
pump(200)

tags = window.tags_tab
window.tabs.setCurrentWidget(tags)
tags.music_field.setText(music)
tags.ext_edit.setText(".mp3")

tags.on_scan()
for _ in range(80):
    pump(100)
    if not tags.is_busy():
        break
pump(300)

rows = tags.table.topLevelItemCount()
OUT.write(f"  строк в таблице: {rows}\n")
ok("правки найдены", rows > 0)

# консоль: не должно быть построчного списка файлов
console_text = window.console.editor.toPlainText()
OUT.write(f"--- консоль (хвост) ---\n{console_text.strip()[-400:]}\n")
ok("в консоли нет построчного перечисления файлов",
   "File: track1.mp3" not in console_text and "-> '" not in console_text)
ok("в консоли есть только итог",
   "Сканирование завершено" in console_text)

# кнопки «Исправить» фиксированной длины
buttons = [tags.table.itemWidget(tags.table.topLevelItem(i), 6)
           for i in range(rows)]
buttons = [b for b in buttons if isinstance(b, QPushButton)]
OUT.write(f"  кнопок «Исправить»: {len(buttons)}, ширина: "
          f"{[b.width() for b in buttons[:3]]}, fixed={[b.minimumWidth() for b in buttons[:3]]}\n")
ok("кнопки существуют", len(buttons) == rows)
ok("ширина кнопки фиксирована и мала",
   all(b.minimumWidth() == b.maximumWidth() for b in buttons)
   and all(b.maximumWidth() <= 120 for b in buttons))

# нажатие «Исправить» не должно падать с TypeError
OUT.write("\n--- нажимаем «Исправить» на первой строке ---\n")
first_item = tags._item_for_row(tags.table.topLevelItem(0))
tags.on_fix_one(first_item)
for _ in range(80):
    pump(100)
    if not tags.is_busy():
        break
pump(300)
status = tags.table.topLevelItem(0).text(5)
OUT.write(f"  статус строки после нажатия: {status}\n")
ok("исправление не упало с TypeError", status == "Исправлено")

# ---------------------------------------------------------------- баг 4
OUT.write("\n--- 3. Плейлисты для плоской папки ---\n")

flat = os.path.join(tmp, "AllFavorites")
os.makedirs(flat, exist_ok=True)
make_mp3(os.path.join(flat, "Song One.mp3"), "One", "Album")
make_mp3(os.path.join(flat, "Song Two.mp3"), "Two", "Album")
out_dir = os.path.join(tmp, "pls")
os.makedirs(out_dir, exist_ok=True)

import argparse
from musicsuite.engines import plscreate as pc

args = argparse.Namespace(
    path=flat, format="m3u8", savedir=out_dir, from_list=None, mass=None,
    searchdir=None, absolute=False, relative_base=None, use_folder_name=True,
)
result = pc.main(args)
OUT.write(f"  результат движка: {result}\n")

created = [f for f in os.listdir(out_dir) if f.endswith(".m3u8")]
OUT.write(f"  создано файлов: {created}\n")
ok("плейлист для плоской папки создан", len(created) == 1)
content = open(os.path.join(out_dir, created[0]), encoding="utf-8").read()
OUT.write("  содержимое:\n" + "\n".join("    " + l for l in content.strip().splitlines()) + "\n")
ok("в плейлисте оба трека", content.count(".mp3") == 2)

# ---------------------------------------------------------------- новая вкладка
OUT.write("\n--- 4. Единая вкладка скачивания ---\n")

titles = [window.tabs.tabText(i) for i in range(window.tabs.count())]
OUT.write(f"  вкладки: {titles}\n")
ok("вкладка одна", "Скачивание с Яндекс.Музыки" in titles)
ok("отдельных вкладок экспорта и плейлистов нет",
   "Экспорт из Яндекс.Музыки" not in titles
   and "Создание плейлистов" not in titles)

hub = window.download_hub_tab
ok("есть поле iframe", hasattr(hub, "iframe_edit"))
ok("есть поле TXT", hasattr(hub, "txt_field"))
ok("есть папка музыки", hasattr(hub, "music_field"))
ok("есть папка плейлиста", hasattr(hub, "playlist_dir_field"))
ok("есть имя плейлиста", hasattr(hub, "name_edit"))
ok("есть формат", hasattr(hub, "format_combo"))
ok("есть токен", hasattr(hub, "token_edit"))
ok("есть таблица треков", hasattr(hub, "tracks_tree"))

# построчное наполнение таблицы
hub.tracks_tree.clear()
for index, name in enumerate(["A - One", "B - Two", "C - Three"], start=1):
    hub.track_row.emit({"title": name, "bitrate": "MP3 320 kbps",
                        "size": "8 МБ", "status": "Скачано"})
    pump(80)
    OUT.write(f"  после трека {index}: строк = {hub.tracks_tree.topLevelItemCount()}\n")
ok("таблица наполняется построчно", hub.tracks_tree.topLevelItemCount() == 3)

# ---------------------------------------------------------------- конвейер
OUT.write("\n--- 5. Конвейер: папка + плейлист ---\n")

from musicsuite.engines import pipeline

# Папку «скачанного» предзаполняем сами: сеть в песочнице недоступна.
def make_track(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as stream:
        stream.write(b"\xFF\xFB\x90\x64" + b"\x00" * 200)

music_root = os.path.join(tmp, "downloads")
target = os.path.join(music_root, "Мой плейлист")
make_track(os.path.join(target, "Artist - Track One.mp3"))
make_track(os.path.join(target, "Artist - Track Two.mp3"))

pls_out = os.path.join(tmp, "out_pls")
os.makedirs(pls_out, exist_ok=True)

count = pipeline._build_playlist_from_folder(
    target, os.path.join(pls_out, "Мой плейлист.m3u8"), "m3u8",
    False, None, True, None,
)
OUT.write(f"  треков в плейлисте: {count}\n")
pls_file = os.path.join(pls_out, "Мой плейлист.m3u8")
ok("файл плейлиста создан", os.path.isfile(pls_file))
body = open(pls_file, encoding="utf-8").read()
OUT.write("  содержимое:\n" + "\n".join("    " + l for l in body.strip().splitlines()) + "\n")
ok("оба трека в плейлисте", body.count(".mp3") == 2)
ok("пути относительные", "/tmp/" not in body)

# относительный префикс
count2 = pipeline._build_playlist_from_folder(
    target, os.path.join(pls_out, "pref.m3u8"), "m3u8", False, "/music", False, None,
)
body2 = open(os.path.join(pls_out, "pref.m3u8"), encoding="utf-8").read()
OUT.write("  с префиксом /music:\n" + "\n".join("    " + l for l in body2.strip().splitlines()) + "\n")
ok("префикс применён", all(l.startswith("/music/") for l in body2.strip().splitlines() if l and not l.startswith("#")))

OUT.write("\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ\n")
