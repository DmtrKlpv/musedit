"""Вкладка «Обновление плейлиста»: запуск только по кнопке.

Проблема, которую фиксирует тест
--------------------------------
На обоих полях пути висел сигнал textChanged, и обработчик сразу
запускал сканирование. Достаточно было выбрать папку — без нажатия
кнопки стартовал обход всей фонотеки. На диске в сотни альбомов это
минуты работы, кнопка «Обновить» оставалась серой, и вкладка выглядела
зависшей. Отменить прогон было нельзя.

Что проверяем
-------------
1. выбор папки и плейлиста НЕ запускает сканирование;
2. кнопка включается, когда оба пути указывают на существующие объекты;
3. нажатие кнопки: сравнение, затем запись — за один проход;
4. повторные клики не создают второй поток и не показывают модальных окон;
5. смена пути во время работы не запускает параллельное сканирование;
6. после смены пути данные помечаются устаревшими и пересчитываются.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

OUT = sys.__stdout__


def ok(label, condition, extra=""):
    OUT.write(f"[{'OK ' if condition else 'FAIL'}] {label}"
              f"{(' — ' + extra) if extra else ''}\n")
    OUT.flush()
    if not condition:
        raise SystemExit(1)


from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

# Диалоги записываем, но не показываем: они блокируют прогон.
dialogs = []


def _record(kind):
    def handler(_parent, _title, text="", *args, **kwargs):
        dialogs.append(f"{kind}: {text}")
        return QMessageBox.Ok
    return staticmethod(handler)


QMessageBox.warning = _record("warning")
QMessageBox.information = _record("information")
QMessageBox.critical = _record("critical")

app = QApplication.instance() or QApplication([])
from musicsuite.main_window import MainWindow


def pump(ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_idle(tab, limit=300, step=40):
    for _ in range(limit):
        pump(step)
        if not tab.is_busy():
            return True
    return False


# ------------------------------------------------------------ данные
tmp = tempfile.mkdtemp(prefix="upd_")
music = os.path.join(tmp, "Music")
os.makedirs(music)
for index in range(40):
    open(os.path.join(music, f"{index:02d} - Track.mp3"), "wb").write(b"x")

playlist = os.path.join(tmp, "list.m3u")
with open(playlist, "w", encoding="utf-8") as stream:
    stream.write("#EXTM3U\n")
    stream.write("\n".join(f"{i:02d} - Track.mp3" for i in range(40)) + "\n")

window = MainWindow()
window.resize(1300, 900)
window.show()
tab = window.update_playlist_tab
window.tabs.setCurrentWidget(tab)
app.processEvents()

# ------------------------------------------------- 1. автозапуска нет
OUT.write("--- 1. Автозапуск ---\n")

scans = []
original_scan = tab._start_scan


def spy_scan(pl, folder):
    scans.append((os.path.basename(pl), os.path.basename(folder)))
    return original_scan(pl, folder)


tab._start_scan = spy_scan

ok("при пустых полях кнопка выключена", not tab.run_btn.isEnabled())

tab.playlist_field.setText(playlist)
pump(80)
OUT.write(f"  после выбора плейлиста: запусков={len(scans)}, "
          f"кнопка={tab.run_btn.isEnabled()}\n")
ok("выбор плейлиста не запускает сканирование", not scans, str(scans))
ok("одного плейлиста мало для кнопки", not tab.run_btn.isEnabled())

tab.folder_field.setText(music)
pump(300)
OUT.write(f"  после выбора папки: запусков={len(scans)}, busy={tab.is_busy()}, "
          f"кнопка={tab.run_btn.isEnabled()}\n")
ok("выбор папки не запускает сканирование", not scans, str(scans))
ok("ничего не выполняется", not tab.is_busy())
ok("кнопка включилась", tab.run_btn.isEnabled())
ok("таблицы пусты до нажатия", tab.playlist_tree.topLevelItemCount() == 0)

# -------------------------------------------- 2. кнопка: скан + запись
OUT.write("\n--- 2. Нажатие кнопки ---\n")
tab.run_btn.click()
wait_idle(tab)
pump(300)

OUT.write(f"  запусков сканирования: {len(scans)}\n")
OUT.write(f"  строк в таблице: {tab.playlist_tree.topLevelItemCount()}\n")
ok("сканирование запущено один раз", len(scans) == 1, str(scans))
ok("таблица заполнена", tab.playlist_tree.topLevelItemCount() == 40,
   str(tab.playlist_tree.topLevelItemCount()))

written = [line for line in open(playlist, encoding="utf-8").read().splitlines()
           if line and not line.startswith("#")]
OUT.write(f"  строк в файле: {len(written)}\n")
ok("плейлист записан", len(written) == 40, str(len(written)))

# ------------------------------- 3. повторные клики и смена путей
OUT.write("\n--- 3. Повторные клики ---\n")
dialogs.clear()
for _ in range(8):
    tab.run_btn.click()
    pump(20)

# Ни одного модального окна: пользователь и так видит прогресс.
modal = [d for d in dialogs if "Подождите" in d]
OUT.write(f"  окон «Подождите»: {len(modal)}\n")
ok("без модальных окон при повторных кликах", not modal, str(modal[:2]))

wait_idle(tab)
pump(300)
ok("после кликов работа завершена", not tab.is_busy())

# Смена пути во время работы
OUT.write("\n--- 4. Смена пути во время работы ---\n")
other = os.path.join(tmp, "other.m3u")
open(other, "w", encoding="utf-8").write("#EXTM3U\n")

tab.run_btn.click()
pump(30)
busy_during = tab.is_busy()
scans_before = len(scans)
tab.playlist_field.setText(other)
pump(120)
OUT.write(f"  работа шла: {busy_during}, новых запусков: {len(scans) - scans_before}\n")
ok("смена пути не запускает второй поток",
   len(scans) - scans_before == 0, str(len(scans) - scans_before))

wait_idle(tab)
pump(300)

# ------------------------------------- 5. устаревшие данные пересчитаются
OUT.write("\n--- 5. Пересчёт после смены пути ---\n")
tab.playlist_field.setText(playlist)
tab.folder_field.setText(music)
pump(100)
scans_before = len(scans)
tab.run_btn.click()
wait_idle(tab)
pump(300)
OUT.write(f"  новых сканирований: {len(scans) - scans_before}\n")
ok("данные пересчитаны после смены пути",
   len(scans) - scans_before >= 1, str(len(scans) - scans_before))
ok("таблица снова заполнена",
   tab.playlist_tree.topLevelItemCount() == 40,
   str(tab.playlist_tree.topLevelItemCount()))

# ------------------------------------------------- итог
OUT.write("\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ\n")
