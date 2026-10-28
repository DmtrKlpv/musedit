"""Проверка прогресс-бара: полоса должна двигаться, а не прыгать 0→100.

Раньше на шкале индексация папки занимала 1 шаг из (2 + строк), поэтому
почти всё время работы полоса стояла на 3%, а затем прыгала в 100%.
Теперь шкала покрывает каждый файл папки и каждую строку плейлиста.
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

OUT = sys.__stdout__


def ok(label, condition, extra=""):
    OUT.write(f"[{'OK ' if condition else 'FAIL'}] {label}"
              f"{(' — ' + extra) if extra else ''}\n")
    OUT.flush()
    if not condition:
        raise SystemExit(1)


def pump(ms=100):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def make_library(root, albums=40, per_album=100):
    for d in range(albums):
        sub = os.path.join(root, f"Album{d:03d}")
        os.makedirs(sub, exist_ok=True)
        for i in range(per_album):
            with open(os.path.join(sub, f"Song {d}_{i}.mp3"), "wb") as stream:
                stream.write(b"\x00" * 20)


app = QApplication.instance() or QApplication([])

from musicsuite.main_window import MainWindow

window = MainWindow()
window.show()
pump(100)

tab = window.playlist_search_tab
window.tabs.setCurrentWidget(tab)
window.resize(1200, 900)
app.processEvents()

events = []
original = tab.progress_panel.set_progress


def spy(done, total, text=""):
    events.append((done, total, time.monotonic()))
    original(done, total, text)


tab.progress_panel.set_progress = spy

tmp = tempfile.mkdtemp(prefix="pb_")
music = os.path.join(tmp, "M")
make_library(music, albums=40, per_album=100)   # 4000 файлов

playlist = os.path.join(tmp, "p.m3u8")
with open(playlist, "w", encoding="utf-8") as stream:
    stream.write("#EXTM3U\n")
    for i in range(40):
        stream.write(f"Z:/old/Song {i}.mp3\n")

tab.rel_edit.setText("/music")
tab.playlist_field.setText(playlist)
tab.folder_field.setText(music)

started = time.monotonic()
tab.on_scan()
for _ in range(400):
    pump(100)
    if not tab.is_busy():
        break
pump(300)

elapsed = time.monotonic() - started
OUT.write(f"--- 4000 файлов, 40 строк, {elapsed:.2f} c ---\n")

seq = [(d, t) for d, t, _ in events if t]
OUT.write(f"событий с осмысленной шкалой: {len(seq)}\n")

percents = []
for done, total in seq:
    percents.append(int(round(100.0 * done / total)))
OUT.write(f"проценты по ходу: {percents}\n")

ok("события прогресса приходят", len(seq) >= 3, str(percents))
ok("шкала одна и та же", len({t for _, t in seq}) == 1,
   str({t for _, t in seq}))
ok("полоса не прыгает сразу в 100", any(0 < p < 100 for p in percents),
   str(percents))
ok("прогресс монотонный",
   all(b >= a for a, b in zip(percents, percents[1:])), str(percents))
ok("финальное значение 100%", percents[-1] == 100)

bar = tab.progress_panel.bar
OUT.write(f"полоса после завершения: {bar.value()}%\n")
ok("полоса осталась на 100%", bar.value() == 100)

# Кнопка справа
btn_x = tab.scan_btn.mapTo(tab, tab.scan_btn.rect().topLeft()).x()
OUT.write(f"кнопка x={btn_x}, ширина вкладки={tab.width()}\n")
ok("кнопка прижата вправо", btn_x > tab.width() / 2)

OUT.write("\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ\n")
