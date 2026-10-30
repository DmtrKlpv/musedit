"""Проверка трёх режимов поиска дубликатов и кнопок удаления в строках.

Что проверяем
-------------
1. SHA-256 находит файлы с одинаковым содержимым.
2. Имя файла находит одноимённые файлы с разным содержимым.
3. Теги находят файлы с одинаковыми исполнителем и названием.
4. Один и тот же файл не попадает в две группы: приоритет SHA-256 → имя → теги.
5. В правой таблице есть колонки «Совпадение» и кнопка «Удалить» в строке.
6. Кнопки снизу больше нет; удаление из строки убирает файл и обновляет список.
"""

import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mutagen.id3 import ID3, TPE1, TIT2
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from musicsuite.engines import duplsearch

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


def make_mp3(path, artist, title, freq=440):
    """Разные freq дают разное содержимое, одинаковые теги задаются явно."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    import imageio_ffmpeg
    subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", f"sine=frequency={freq}:duration=0.4",
         "-c:a", "libmp3lame", "-b:a", "192k", path, "-y"],
        check=True,
    )
    tags = ID3()
    tags.add(TIT2(encoding=1, text=[title]))
    tags.add(TPE1(encoding=1, text=[artist]))
    tags.save(path, v1=0, v2_version=4)


tmp = tempfile.mkdtemp(prefix="dupl_")
root = os.path.join(tmp, "Music")

# 1) одинаковое содержимое, разные имена и теги
make_mp3(os.path.join(root, "A", "first.mp3"), "Artist One", "Song One", 440)
os.makedirs(os.path.join(root, "B"), exist_ok=True)
shutil.copy(os.path.join(root, "A", "first.mp3"),
            os.path.join(root, "B", "second.mp3"))

# 2) одинаковое имя, разное содержимое
make_mp3(os.path.join(root, "C", "same.mp3"), "Artist C", "Title C", 550)
make_mp3(os.path.join(root, "D", "same.mp3"), "Artist D", "Title D", 660)

# 3) одинаковые теги, разные имена и содержимое
make_mp3(os.path.join(root, "E", "alpha.mp3"), "Same Artist", "Same Title", 770)
make_mp3(os.path.join(root, "F", "beta.mp3"), "Same Artist", "Same Title", 880)

# 4) одиночный файл — ни с чем не совпадает
make_mp3(os.path.join(root, "G", "unique.mp3"), "Solo", "Alone", 990)

# ------------------------------------------------------------------ движок
OUT.write("--- 1. Режим SHA-256 ---\n")
sha_groups = duplsearch.find_duplicates(root, modes=[duplsearch.MODE_SHA256])
for group in sha_groups:
    OUT.write(f"  [{group['match']}] {group['filename']}: "
              f"{len(group['files'])} файлов\n")
ok("SHA-256 нашёл одну группу", len(sha_groups) == 1, str(len(sha_groups)))
ok("тип совпадения — SHA256", sha_groups[0]["match"] == "SHA256")
ok("в группе два файла", len(sha_groups[0]["files"]) == 2)

OUT.write("\n--- 2. Режим «Имя файла» ---\n")
name_groups = duplsearch.find_duplicates(root, modes=[duplsearch.MODE_NAME])
for group in name_groups:
    OUT.write(f"  [{group['match']}] {group['filename']}: "
              f"{len(group['files'])} файлов\n")
ok("по имени найдена одна группа", len(name_groups) == 1, str(len(name_groups)))
ok("тип совпадения — Имя", name_groups[0]["match"] == "Имя")
ok("это именно same.mp3", name_groups[0]["filename"] == "same.mp3")

OUT.write("\n--- 3. Режим «Теги» ---\n")
tag_groups = duplsearch.find_duplicates(root, modes=[duplsearch.MODE_TAGS])
for group in tag_groups:
    OUT.write(f"  [{group['match']}] {group['filename']}: "
              f"{len(group['files'])} файлов\n")
ok("по тегам найдены две группы (теги + скопированный файл)",
   len(tag_groups) == 2, str(len(tag_groups)))
ok("все группы помечены как Теги",
   all(g["match"] == "Теги" for g in tag_groups))

OUT.write("\n--- 4. Все режимы вместе: приоритет ---\n")
all_groups = duplsearch.find_duplicates(root, modes=duplsearch.MODE_ORDER)
for group in all_groups:
    OUT.write(f"  [{group['match']:8}] {group['filename']}: "
              f"{len(group['files'])} файлов\n")

kinds = [g["match"] for g in all_groups]
OUT.write(f"  типы групп: {kinds}\n")
ok("три группы, по одной на каждый способ", len(all_groups) == 3,
   str(len(all_groups)))
ok("SHA256 идёт первым", kinds[0] == "SHA256")
ok("имя вторым", kinds[1] == "Имя")
ok("теги третьими", kinds[2] == "Теги")

# Файлы не должны повторяться между группами
seen = set()
duplicates_between_groups = []
for group in all_groups:
    for entry in group["files"]:
        if entry["path"] in seen:
            duplicates_between_groups.append(entry["path"])
        seen.add(entry["path"])
ok("один файл не в двух группах", not duplicates_between_groups,
   str(duplicates_between_groups[:2]))

# ------------------------------------------------------------------ GUI
OUT.write("\n--- 5. Интерфейс ---\n")
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)

# QApplication должен существовать ДО создания окна, иначе Qt падает
# с «Must construct a QApplication before a QWidget».
app = QApplication.instance() or QApplication([])

from musicsuite.main_window import MainWindow

window = MainWindow()
window.resize(1500, 900)
window.show()
pump(100)

tab = window.duplicates_tab
window.tabs.setCurrentWidget(tab)
app.processEvents()

ok("галочка SHA-256 есть и включена",
   tab.sha_check.isChecked() and not tab.sha_check.isEnabled())
ok("галочка «По имени файла» есть", hasattr(tab, "name_check"))
ok("галочка «По mp3-тегам» есть", hasattr(tab, "tags_check"))
ok("кнопки удаления снизу больше нет", not hasattr(tab, "trash_btn"))

# Запуск поиска через вкладку со всеми режимами
tab.dir_field.setText(root)
tab.name_check.setChecked(True)
tab.tags_check.setChecked(True)
tab.on_search()
for _ in range(120):
    pump(100)
    if not tab.is_busy():
        break
pump(400)

OUT.write(f"  групп в таблице: {tab.groups_tree.topLevelItemCount()}\n")
for index in range(tab.groups_tree.topLevelItemCount()):
    item = tab.groups_tree.topLevelItem(index)
    OUT.write(f"    {item.text(0):14} | {item.text(1):8} | копий {item.text(2)}\n")

ok("группы появились в таблице", tab.groups_tree.topLevelItemCount() == 3)
ok("есть колонка «Совпадение» в группах",
   tab.groups_tree.headerItem().text(1) == "Совпадение")

files_header = [tab.files_tree.headerItem().text(i)
                for i in range(tab.files_tree.columnCount())]
OUT.write(f"  колонки файлов: {files_header}\n")
ok("в файлах есть колонка «Совпадение»", "Совпадение" in files_header)
ok("в файлах есть колонка под кнопку", files_header[-1] == "")

# Правая таблица: значения «Совпадение» и кнопки в строках
rows = tab.files_tree.topLevelItemCount()
OUT.write(f"  строк в правой таблице: {rows}\n")
ok("правая таблица заполнена", rows >= 2, str(rows))

values = [tab.files_tree.topLevelItem(i).text(3) for i in range(rows)]
OUT.write(f"  значения «Совпадение»: {values}\n")
ok("тип совпадения заполнен у каждой строки",
   all(v in ("SHA256", "Имя", "Теги") for v in values), str(values))

buttons = [tab.files_tree.itemWidget(tab.files_tree.topLevelItem(i), 4)
           for i in range(rows)]
buttons = [b for b in buttons if isinstance(b, QPushButton)]
OUT.write(f"  кнопок в строках: {len(buttons)}, "
          f"ширина: {buttons[0].minimumWidth() if buttons else 0}\n")
ok("кнопка «Удалить» в каждой строке", len(buttons) == rows)
ok("подпись кнопки — «Удалить»",
   all(b.text() == "Удалить" for b in buttons))
ok("кнопки фиксированной ширины",
   all(b.minimumWidth() == b.maximumWidth() for b in buttons))

# ---------------------------------------------------- удаление из строки
OUT.write("\n--- 6. Удаление из строки ---\n")
first_group = tab._groups[0]
target = first_group["files"][0]["path"]
OUT.write(f"  удаляем: {os.path.basename(target)}\n")
existed_before = os.path.exists(target)

tab.on_delete_path(target)
for _ in range(60):
    pump(100)
    if not tab.is_busy():
        break
pump(300)

OUT.write(f"  файл существует после удаления: {os.path.exists(target)}\n")
ok("файл был на диске", existed_before)
ok("файл удалён", not os.path.exists(target))
ok("группа исчезла из списка (осталась одна копия)",
   tab.groups_tree.topLevelItemCount() == len(tab._groups))

OUT.write("\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ\n")
