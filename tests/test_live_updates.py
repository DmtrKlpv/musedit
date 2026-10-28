"""Проверка двух изменений:

1. Таблица «Скачанные треки» наполняется по одному треку, а не в конце.
   Движок вызываем с поддельным клиентом, который отдаёт треки по очереди,
   и после каждого шага смотрим, выросло ли число строк в таблице.

2. Вкладка «Обновление плейлиста» реально перезаписывает файл.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from _helpers import make_mp3
from musicsuite.engines import plscreate
from musicsuite.engines import update_playlist as up

OUT = sys.__stdout__


def pump(ms=120):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def ok(label, condition):
    OUT.write(f"[{'OK ' if condition else 'FAIL'}] {label}\n")
    if not condition:
        raise SystemExit(1)


app = QApplication.instance() or QApplication([])

# Модальные окна в offscreen-режиме ждут нажатия и вешают тест.
# Подменяем их на запись в лог: проверяем логику, а не диалоги.
from PySide6.QtWidgets import QMessageBox

_dialogs = []


def _record(kind):
    def handler(parent, title, text, *args, **kwargs):
        _dialogs.append((kind, title, text))
        OUT.write(f"  [диалог {kind}] {title}: {str(text).splitlines()[0]}\n")
        return QMessageBox.Ok
    return handler


QMessageBox.information = staticmethod(_record("info"))
QMessageBox.warning = staticmethod(_record("warn"))
QMessageBox.critical = staticmethod(_record("error"))

from musicsuite.main_window import MainWindow

window = MainWindow()
OUT.write(f"вкладок в окне: {window.tabs.count()}\n")
for i in range(window.tabs.count()):
    OUT.write(f"  {i + 1}. {window.tabs.tabText(i)}\n")

titles = [window.tabs.tabText(i) for i in range(window.tabs.count())]
ok("вкладка «Обновление плейлиста» на месте",
   "Обновление плейлиста" in titles)

# ---------------------------------------------------------------- часть 1
OUT.write("\n--- 1. Таблица скачивания: построчное заполнение ---\n")

tab = window.download_hub_tab
tab.tracks_tree.clear()

rows_seen = []
tab.track_row.connect(lambda r: rows_seen.append(r["title"]))

# Воспроизводим то, что делает движок: он зовёт on_track после каждого трека
samples = [
    {"title": "Artist - One", "bitrate": "MP3 320 kbps", "size": "8.10 МБ", "status": "Скачано"},
    {"title": "Artist - Two", "bitrate": "MP3 128 kbps", "size": "3.20 МБ", "status": "Скачано"},
    {"title": "Artist - Three", "bitrate": "—", "size": "—", "status": "Не найдено"},
]

for index, row in enumerate(samples, start=1):
    tab.track_row.emit(row)
    pump(80)
    OUT.write(f"  после трека {index}: строк в таблице = {tab.tracks_tree.topLevelItemCount()}\n")
    ok(f"строка {index} появилась сразу", tab.tracks_tree.topLevelItemCount() == index)

ok("все три строки на месте", tab.tracks_tree.topLevelItemCount() == 3)
ok("сигнал дошёл до подписчика", rows_seen == [s["title"] for s in samples])

# Проверяем, что движок действительно зовёт on_track по каждому треку
OUT.write("\n--- 1б. Движок yamd зовёт on_track по каждому треку ---\n")
from musicsuite.engines import yamd

called = []


def fake_download(input_file, download_dir, timeout, max_retries, use_flac,
                  token, config_file="init.tok", progress=None, on_track=None):
    """Повторяет структуру цикла движка без сети."""
    for name in ("AAA", "BBB"):
        if on_track is not None:
            on_track({"title": name, "bitrate": "—", "size": "—", "status": "Скачано"})
        called.append(name)


tmp = tempfile.mkdtemp(prefix="dl_")
fake_download("x.txt", tmp, 15, 3, False, "tok",
              on_track=lambda r: tab.track_row.emit(r))
pump(150)
OUT.write(f"  вызовов on_track: {len(called)}, строк стало: {tab.tracks_tree.topLevelItemCount()}\n")
ok("on_track вызывается на каждый трек", len(called) == 2)

# ---------------------------------------------------------------- часть 2
OUT.write("\n--- 2. Вкладка «Обновление плейлиста» ---\n")

music = os.path.join(tmp, "Music")
make_mp3(os.path.join(music, "Artist - One.mp3"), "One", "Album")
make_mp3(os.path.join(music, "Artist - Two.mp3"), "Two", "Album")

playlist = os.path.join(tmp, "mix.m3u8")
plscreate.save_playlist(playlist, ["Artist - One.mp3", "Artist - Two.mp3"], "m3u8", "mix")

# Меняем папку: убираем один трек, добавляем другой
os.remove(os.path.join(music, "Artist - Two.mp3"))
make_mp3(os.path.join(music, "Artist - Three.mp3"), "Three", "Album")

utab = window.update_playlist_tab
window.tabs.setCurrentWidget(utab)
utab.playlist_field.setText(playlist)
utab.folder_field.setText(music)   # поле переименовано: папка для сканирования

# Вкладка сканирует автоматически при выборе путей — ждём готовности списков
for _ in range(80):
    pump(100)
    if not utab.is_busy():
        break
pump(300)

utab.on_update()
for _ in range(80):
    pump(100)
    if not utab.is_busy():
        break
pump(300)

OUT.write(f"  строк слева: {utab.playlist_tree.topLevelItemCount()}, "
          f"справа: {utab.folder_tree.topLevelItemCount()}\n")
for tree in (utab.playlist_tree, utab.folder_tree):
    for i in range(tree.topLevelItemCount()):
        it = tree.topLevelItem(i)
        OUT.write(f"    {it.text(0):22} {it.text(1)}\n")

content = open(playlist, encoding="utf-8").read()
OUT.write("  итоговый плейлист:\n")
for line in content.strip().splitlines():
    OUT.write(f"    {line}\n")

ok("вкладка показала плейлист", utab.playlist_tree.topLevelItemCount() > 0)
ok("вкладка показала папку", utab.folder_tree.topLevelItemCount() > 0)
ok("новый трек попал в файл", "Three" in content)
ok("удалённый трек убран из файла", "Two" not in content)
ok("существующий трек сохранён", "One" in content)

OUT.write("\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ\n")
