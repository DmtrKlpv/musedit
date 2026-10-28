"""Проверка вкладки «Поиск по плейлисту».

Сценарий: плейлист ссылается на старые пути, файлы лежат в другой папке.
  * движок находит каждый трек по имени файла;
  * одиночная замена меняет одну строку;
  * «Поменять все пути» меняет остальные;
  * префикс и абсолютные пути работают как в других вкладках;
  * комментарии и порядок строк в файле сохраняются.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from musicsuite.engines import playlist_search as engine

OUT = sys.__stdout__


def ok(label, condition, extra=""):
    OUT.write(f"[{'OK ' if condition else 'FAIL'}] {label}{(' — ' + extra) if extra else ''}\n")
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


# ------------------------------------------------------------------ данные
tmp = tempfile.mkdtemp(prefix="plsearch_")
music = os.path.join(tmp, "NewMusic")

make_track(os.path.join(music, "Absurd Minds - Zero Point.mp3"))
make_track(os.path.join(music, "Status Quo - Like It Or Not.mp3"))
make_track(os.path.join(music, "Album", "Deep Track.mp3"))

# Плейлист ссылается на старый диск и старую раскладку
playlist = os.path.join(tmp, "old.m3u8")
with open(playlist, "w", encoding="utf-8") as stream:
    stream.write(
        "#EXTM3U\n"
        "#EXTINF:-1,Absurd Minds - Zero Point\n"
        "Z:/broken/Absurd Minds - Zero Point.mp3\n"
        "#EXTINF:-1,Status Quo - Like It Or Not\n"
        "Z:/broken/Status Quo - Like It Or Not.mp3\n"
        "#EXTINF:-1,Deep Track\n"
        "Z:/broken/Deep Track.mp3\n"
        "#EXTINF:-1,Missing Song\n"
        "Z:/broken/Missing Song.mp3\n"
    )

OUT.write("--- 1. Движок: поиск ---\n")
result = engine.find_playlist_matches(playlist, music, rel_base="/music")
OUT.write(f"  {result.summary}\n")
for row in result.rows:
    OUT.write(f"    {row.track_name:32} -> {row.new_path or '—'}\n")

ok("все четыре строки прочитаны", len(result.rows) == 4)
ok("три трека найдены", len(result.found) == 3)
ok("один трек отсутствует", len(result.missing) == 1)
ok("отсутствует именно Missing Song",
   result.missing[0].track_name == "Missing Song.mp3")
ok("префикс применён",
   all(r.new_path.startswith("/music/") for r in result.found))

paths = sorted(r.new_path for r in result.found)
ok("вложенная папка учтена",
   any(p == "/music/Album/Deep Track.mp3" for p in paths), str(paths))

# ------------------------------------------------------- одиночная замена
OUT.write("\n--- 2. Замена одной строки ---\n")
first = result.found[0]
changed = engine.apply_single(playlist, first)
OUT.write(f"  изменено строк: {changed}\n")
body = open(playlist, encoding="utf-8").read()
OUT.write("  файл после замены:\n")
for line in body.strip().splitlines():
    OUT.write(f"    {line}\n")

ok("замена прошла", changed == 1)
ok("новая строка в файле", first.new_path in body)
ok("старый путь этой строки исчез", first.old_path not in body)
ok("комментарии сохранены", body.count("#EXTINF") == 4)
ok("порядок строк сохранён", body.index("#EXTM3U") < body.index("#EXTINF"))
ok("незаменённые строки на месте", "Z:/broken/Status Quo" in body)

# ------------------------------------------------------- замена всех
OUT.write("\n--- 3. Поменять все пути ---\n")
rest = [r for r in result.rows if r.new_path and not r.applied]
changed_all = engine.apply_rows(playlist, rest)
OUT.write(f"  изменено строк: {changed_all}\n")
body = open(playlist, encoding="utf-8").read()
OUT.write("  итоговый файл:\n")
for line in body.strip().splitlines():
    OUT.write(f"    {line}\n")

ok("заменены оставшиеся две", changed_all == 2)
ok("старых путей Z:/ не осталось", "Z:/broken" not in body
   or body.count("Z:/broken") == 1)   # остаётся только ненайденный
ok("ненайденный трек сохранён", "Missing Song.mp3" in body)
ok("все найденные пути с префиксом",
   body.count("/music/") == 3, str(body.count("/music/")))

# ------------------------------------------------------- абсолютные пути
OUT.write("\n--- 4. Абсолютные пути ---\n")
abs_result = engine.find_playlist_matches(playlist, music, absolute=True)
abs_paths = [r.new_path for r in abs_result.found]
OUT.write(f"  {abs_paths[:2]}\n")
ok("абсолютные пути начинаются с корня",
   all(os.path.isabs(p) for p in abs_paths if p))

# ------------------------------------------------------- GUI
OUT.write("\n--- 5. Вкладка ---\n")
QMessageBox.information = staticmethod(lambda *a, **k: OUT.write("  [info]\n"))
QMessageBox.warning = staticmethod(lambda *a, **k: OUT.write(f"  [warn] {a[2]}\n"))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)

app = QApplication.instance() or QApplication([])
from musicsuite.main_window import MainWindow

window = MainWindow()
window.show()
pump(150)

tab = window.playlist_search_tab
window.tabs.setCurrentWidget(tab)

# сбрасываем плейлист в исходное состояние
with open(playlist, "w", encoding="utf-8") as stream:
    stream.write(
        "#EXTM3U\n"
        "#EXTINF:-1,Absurd Minds - Zero Point\n"
        "Z:/broken/Absurd Minds - Zero Point.mp3\n"
        "#EXTINF:-1,Status Quo - Like It Or Not\n"
        "Z:/broken/Status Quo - Like It Or Not.mp3\n"
        "#EXTINF:-1,Deep Track\n"
        "Z:/broken/Deep Track.mp3\n"
        "#EXTINF:-1,Missing Song\n"
        "Z:/broken/Missing Song.mp3\n"
    )

tab.rel_edit.setText("/music")
tab.absolute_check.setChecked(False)
tab.playlist_field.setText(playlist)
tab.folder_field.setText(music)
pump(200)

# Автоматического поиска быть не должно: после выбора путей таблица пуста.
OUT.write(f"  строк до нажатия кнопки: {tab.table.topLevelItemCount()}\n")
ok("автоматический поиск не запускается", tab.table.topLevelItemCount() == 0)
ok("есть кнопка «Начать сканирование»",
   tab.scan_btn.text() == "Начать сканирование")
ok("кнопка сканирования акцентная", tab.scan_btn.objectName() == "primary")

# Кнопка должна стоять справа, а не у левого края.
btn_x = tab.scan_btn.mapTo(tab, tab.scan_btn.rect().topLeft()).x()
OUT.write(f"  кнопка x={btn_x}, ширина вкладки={tab.width()}\n")
ok("кнопка прижата вправо", btn_x > tab.width() / 2)

# Запуск только по кнопке.
tab.on_scan()
for _ in range(80):
    pump(100)
    if not tab.is_busy():
        break
pump(300)

OUT.write(f"  строк в таблице: {tab.table.topLevelItemCount()}\n")
OUT.write(f"  статус: {tab.status_label.text()}\n")
for i in range(tab.table.topLevelItemCount()):
    item = tab.table.topLevelItem(i)
    OUT.write(f"    {item.text(0):32} | {item.text(1)[:34]:34} -> {item.text(2)[:34]}\n")

ok("таблица заполнена", tab.table.topLevelItemCount() == 4)
expected = ["Трек", "Старый путь", "Путей", "Запись в файле",
            "Указать явно", "Изменить путь", "Новый путь"]
actual = [tab.table.headerItem().text(i) for i in range(tab.table.columnCount())]
OUT.write(f"  колонки: {actual}\n")
ok("порядок колонок совпадает с заданием", actual == expected, str(actual))
ok("есть колонка «Указать явно»", "Указать явно" in actual)
ok("«Новый путь» последний", actual[-1] == "Новый путь")
ok("кнопка «Поменять все пути» активна", tab.change_all_btn.isEnabled())

buttons = [tab.table.itemWidget(tab.table.topLevelItem(i), 5)
           for i in range(tab.table.topLevelItemCount())]
buttons = [b for b in buttons if isinstance(b, QPushButton)]
OUT.write(f"  кнопок в строках: {len(buttons)}, ширина: {buttons[0].width()}\n")
ok("кнопка в каждой строке", len(buttons) == 4)
ok("кнопки фиксированной длины", all(b.minimumWidth() == b.maximumWidth() for b in buttons))

# --------------------------------------------------- выпадающий список
OUT.write("\n--- 5б. Выпадающий список в «Запись в файле» ---\n")
from PySide6.QtWidgets import QComboBox

combos = [tab.table.itemWidget(tab.table.topLevelItem(i), 3)
          for i in range(tab.table.topLevelItemCount())]
combos = [c for c in combos if isinstance(c, QComboBox)]
OUT.write(f"  выпадающих списков: {len(combos)}\n")
ok("в каждой строке выпадающий список", len(combos) == 4)
ok("список редактируемый", all(c.isEditable() for c in combos))
ok("в списке есть текущий путь",
   all(c.currentText() for c in combos))

# Колонка «Путей» отражает число кандидатов
counts = [tab.table.topLevelItem(i).text(2)
          for i in range(tab.table.topLevelItemCount())]
OUT.write(f"  значения колонки «Путей»: {counts}\n")
ok("колонка «Путей» заполнена числами", all(c.isdigit() for c in counts))

# Смена значения в списке меняет выбранный путь
first_combo = combos[0]
first_row = tab._items[0]
before = first_row.new_path
first_combo.setCurrentText("X:/custom/path.mp3")
pump(120)
OUT.write(f"  было: {before}\n  стало: {first_row.new_path}\n")
ok("выбор в списке меняет путь", first_row.new_path == "X:/custom/path.mp3")
ok("колонка «Новый путь» обновилась",
   tab.table.topLevelItem(0).text(6) == "X:/custom/path.mp3")

# возвращаем корректное значение
first_combo.setCurrentText(before)
pump(120)
ok("путь возвращён", first_row.new_path == before)

# нажатие кнопки в строке
target_row = next(r for r in tab._items if r.new_path and r.track_name.startswith("Absurd"))
tab.on_change_one(target_row)
for _ in range(80):
    pump(100)
    if not tab.is_busy():
        break
pump(300)

body = open(playlist, encoding="utf-8").read()
OUT.write("  файл после одиночной замены:\n")
for line in body.strip().splitlines():
    OUT.write(f"    {line}\n")
ok("одиночная замена из GUI сработала",
   "/music/Absurd Minds - Zero Point.mp3" in body)

# «Поменять все пути»
tab.on_change_all()
for _ in range(80):
    pump(100)
    if not tab.is_busy():
        break
pump(400)

body = open(playlist, encoding="utf-8").read()
OUT.write("  итог после «Поменять все пути»:\n")
for line in body.strip().splitlines():
    OUT.write(f"    {line}\n")

ok("все найденные пути заменены", body.count("/music/") == 3)
ok("ненайденный сохранён", "Missing Song.mp3" in body)
ok("комментарии целы", body.count("#EXTINF") == 4)
ok("кнопка блокируется после работы", not tab.change_all_btn.isEnabled())

OUT.write("\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ\n")
