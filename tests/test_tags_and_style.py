"""Регрессия: подсветка ручного выбора и поиск по mp3-тегам.

1. Если в колонке «Запись в файле» выбран не первый (предложенный поиском)
   вариант, список подсвечивается — видно, что строка отличается от
   автоматического результата.

2. Галочка «Так же искать в mp3-тегах» включает сопоставление по ID3:
   файл со «случайным» именем находится по тегам исполнитель + название.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QComboBox, QMessageBox

from _helpers import make_mp3
from musicsuite.engines import playlist_search as engine

OUT = sys.__stdout__


def ok(label, condition, extra=""):
    OUT.write(f"[{'OK ' if condition else 'FAIL'}] {label}"
              f"{(' — ' + extra) if extra else ''}\n")
    OUT.flush()
    if not condition:
        raise SystemExit(1)


def pump(ms=120):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


app = QApplication.instance() or QApplication([])
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)

from musicsuite.main_window import MainWindow

window = MainWindow()
window.resize(1500, 900)
window.show()
pump(100)

tab = window.playlist_search_tab
window.tabs.setCurrentWidget(tab)
app.processEvents()

# ---------------------------------------------------------------- 1. подсветка
OUT.write("--- 1. Подсветка изменённого выбора ---\n")

tmp = tempfile.mkdtemp(prefix="style_")
music = os.path.join(tmp, "Music")
for album in ("Album A", "Album B"):
    make_mp3(os.path.join(music, album, "Track.mp3"), "Track", album)

playlist = os.path.join(tmp, "p.m3u8")
with open(playlist, "w", encoding="utf-8") as stream:
    stream.write("#EXTM3U\nZ:/old/Track.mp3\n")

tab.rel_edit.setText("/music")
tab.playlist_field.setText(playlist)
tab.folder_field.setText(music)
tab.on_scan()
for _ in range(80):
    pump(100)
    if not tab.is_busy():
        break
pump(300)

item = tab.table.topLevelItem(0)
combo = tab.table.itemWidget(item, 3)
row = tab._items[0]

OUT.write(f"  вариантов: {combo.count()}\n")
OUT.write(f"  выбран по умолчанию: {combo.currentText()!r}\n")
ok("есть из чего выбирать", combo.count() == 2)
ok("по умолчанию выбран первый", combo.currentText() == row.default_path)
ok("первый не подсвечен", combo.styleSheet() == "")

combo.setCurrentIndex(1)
pump(150)
OUT.write(f"  после выбора второго: {combo.currentText()!r}\n")
OUT.write(f"  стиль: {combo.styleSheet()!r}\n")
ok("второй вариант подсвечен", "#fff4d6" in combo.styleSheet())
ok("подсказка объясняет причину",
   "Выбран вручную" in combo.toolTip())
ok("путь строки обновился", row.new_path == combo.currentText())

combo.setCurrentIndex(0)
pump(150)
OUT.write(f"  после возврата к первому: стиль={combo.styleSheet()!r}\n")
ok("подсветка снята при возврате", combo.styleSheet() == "")

# ---------------------------------------------------------------- 2. теги
OUT.write("\n--- 2. Поиск по mp3-тегам ---\n")

music2 = os.path.join(tmp, "TagMusic")
# Имена файлов ничего общего с плейлистом не имеют — спасёт только тег
make_mp3(os.path.join(music2, "deep", "x1.mp3"),
         title="Aerials", album="Toxicity", artist="System Of A Down")
make_mp3(os.path.join(music2, "deep", "x2.mp3"),
         title="Chop Suey!", album="Toxicity", artist="System Of A Down")

playlist2 = os.path.join(tmp, "tags.m3u8")
with open(playlist2, "w", encoding="utf-8") as stream:
    stream.write("#EXTM3U\n")
    stream.write("Z:/old/System Of A Down - Aerials.mp3\n")
    stream.write("Z:/old/System Of A Down - Chop Suey!.mp3\n")

OUT.write("  без тегов:\n")
without = engine.find_playlist_matches(playlist2, music2, rel_base="/music",
                                       search_tags=False)
for result_row in without.rows:
    OUT.write(f"    {result_row.track_name:38} путей={result_row.option_count}\n")
ok("без тегов ничего не найдено",
   all(r.option_count == 0 for r in without.rows))

OUT.write("  с тегами:\n")
with_tags = engine.find_playlist_matches(playlist2, music2, rel_base="/music",
                                         search_tags=True)
for result_row in with_tags.rows:
    OUT.write(f"    {result_row.track_name:38} путей={result_row.option_count}\n")
    for path in result_row.candidates:
        OUT.write(f"        {path}\n")

ok("с тегами найдены оба", all(r.option_count >= 1 for r in with_tags.rows))
ok("Aerials найден по тегу",
   any("x1.mp3" in c for r in with_tags.rows if "Aerials" in r.track_name
       for c in r.candidates))
ok("путь получил префикс",
   all(c.startswith("/music/") for r in with_tags.rows for c in r.candidates))

# ---------------------------------------------------------------- 3. галочка в GUI
OUT.write("\n--- 3. Галочка в интерфейсе ---\n")
ok("галочка существует", hasattr(tab, "tags_check"))
ok("подпись совпадает",
   tab.tags_check.text() == "Так же искать в mp3-тегах",
   tab.tags_check.text())
ok("по умолчанию выключена", tab.tags_check.isChecked() is False)

y_prefix = tab.rel_edit.mapTo(tab, tab.rel_edit.rect().topLeft()).y()
y_tags = tab.tags_check.mapTo(tab, tab.tags_check.rect().topLeft()).y()
OUT.write(f"  y префикса={y_prefix}, y галочки={y_tags}\n")
ok("галочка ниже поля префикса", y_tags > y_prefix)

# Гоняем поиск через вкладку с включённой галочкой
tab.tags_check.setChecked(True)
tab.rel_edit.setText("/music")
tab.playlist_field.setText(playlist2)
tab.folder_field.setText(music2)
tab.on_scan()
for _ in range(80):
    pump(100)
    if not tab.is_busy():
        break
pump(400)

found_rows = tab.table.topLevelItemCount()
OUT.write(f"  строк в таблице: {found_rows}\n")
for index in range(found_rows):
    entry = tab.table.topLevelItem(index)
    OUT.write(f"    {entry.text(0):38} путей={entry.text(2)}\n")

ok("таблица заполнена через вкладку", found_rows == 2)
ok("найдено по тегам через вкладку",
   all(tab.table.topLevelItem(i).text(2) != "0" for i in range(found_rows)))

OUT.write("\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ\n")
