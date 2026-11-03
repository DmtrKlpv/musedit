"""Импорт и пересоздание CSV в поиске дубликатов.

Что проверяем
-------------
1. Отчёт сохраняется с колонкой «Группа» — по ней восстанавливаются
   группы при импорте.
2. Импорт нового отчёта даёт те же группы и тот же тип совпадения.
3. Старый отчёт без колонки «Группа» тоже читается: группы собираются
   из подряд идущих строк.
4. Разделитель определяется сам — `;` или `,`.
5. Мусорный файл отклоняется с понятным сообщением.
6. После удаления файла «Пересоздать CSV» пишет отчёт без него.
7. Импортированный файл, отсутствующий на диске, помечен и не удаляется.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QPushButton

from musicsuite.engines import duplsearch

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


def make_mp3(path, seed=0):
    """Минимальный MP3-подобный файл: содержимое различается по seed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as stream:
        stream.write(b"\xFF\xFB\x90\x64" + bytes([seed]) * 2000)


# ------------------------------------------------------------------ данные
tmp = tempfile.mkdtemp(prefix="csvio_")
root = os.path.join(tmp, "Music")

for sub in ("A", "B", "C"):
    make_mp3(os.path.join(root, sub, "song.mp3"), seed=1)
for sub in ("A", "B"):
    make_mp3(os.path.join(root, sub, "other.mp3"), seed=2)

# ------------------------------------------------------------------ 1. запись
OUT.write("--- 1. Сохранение отчёта ---\n")
groups = duplsearch.find_duplicates(root, modes=(duplsearch.MODE_SHA256,))
OUT.write(f"  найдено групп: {len(groups)}\n")
ok("найдены две группы", len(groups) == 2, str(len(groups)))

csv_path = duplsearch.write_csv(groups, os.path.join(tmp, "report.csv"))
body = open(csv_path, encoding="utf-8-sig").read()
OUT.write("  содержимое:\n")
for line in body.strip().splitlines():
    OUT.write(f"    {line}\n")

header = body.splitlines()[0]
ok("в заголовке есть колонка «Группа»", "Группа" in header, header)
ok("разделитель — точка с запятой", ";" in header)
ok("номера групп идут с 1", ";1" in body and ";2" in body)

# ------------------------------------------------------------------ 2. импорт
OUT.write("\n--- 2. Импорт нового отчёта ---\n")
restored = duplsearch.read_csv(csv_path)
OUT.write(f"  групп после импорта: {len(restored)}\n")
for group in restored:
    OUT.write(f"    {group['filename']:12} {group['match']:8} "
              f"файлов {len(group['files'])}\n")

ok("число групп совпало", len(restored) == len(groups))
ok("имена и порядок совпали",
   [g["filename"] for g in restored] == [g["filename"] for g in groups])
ok("количество файлов в группах совпало",
   [len(g["files"]) for g in restored] == [len(g["files"]) for g in groups])
ok("тип совпадения сохранён",
   all(g["match"] == "SHA256" for g in restored))
ok("все файлы найдены на диске",
   all(entry["exists"] for g in restored for entry in g["files"]))

# ------------------------------------------------------------------ 3. старый формат
OUT.write("\n--- 3. Отчёт старого формата (без «Группа») ---\n")
old_csv = os.path.join(tmp, "old.csv")
with open(old_csv, "w", encoding="utf-8-sig") as stream:
    stream.write(
        "Название;Папка;Размер;Битрейт;Совпадение\n"
        "song.mp3;/m/a;1 MB;320 kbps;SHA256\n"
        "song.mp3;/m/b;1 MB;320 kbps;SHA256\n"
        "other.mp3;/m/a;2 MB;192 kbps;Имя\n"
        "other.mp3;/m/c;2 MB;192 kbps;Имя\n"
    )

old_groups = duplsearch.read_csv(old_csv)
OUT.write(f"  групп: {len(old_groups)}\n")
for group in old_groups:
    OUT.write(f"    {group['filename']:12} {group['match']:8} "
              f"файлов {len(group['files'])}\n")

ok("старый формат прочитан", len(old_groups) == 2, str(len(old_groups)))
ok("группы не слиплись",
   old_groups[0]["filename"] == "song.mp3"
   and old_groups[1]["filename"] == "other.mp3")
ok("тип «Имя» восстановлен", old_groups[1]["match"] == "Имя")
ok("отсутствующие файлы помечены",
   all(not e["exists"] for g in old_groups for e in g["files"]))

# Три строки одного имени — одна группа из трёх файлов
three_csv = os.path.join(tmp, "three.csv")
with open(three_csv, "w", encoding="utf-8-sig") as stream:
    stream.write(
        "Название;Папка;Размер;Битрейт;Совпадение\n"
        "a.mp3;/x;1 MB;320;SHA256\n"
        "a.mp3;/y;1 MB;320;SHA256\n"
        "a.mp3;/z;1 MB;320;SHA256\n"
    )
three = duplsearch.read_csv(three_csv)
OUT.write(f"  три строки одного имени → групп {len(three)}, "
          f"файлов {len(three[0]['files'])}\n")
ok("одна группа из трёх файлов",
   len(three) == 1 and len(three[0]["files"]) == 3)

# ------------------------------------------------------------------ 4. запятая
OUT.write("\n--- 4. Разделитель «запятая» ---\n")
comma_csv = os.path.join(tmp, "comma.csv")
with open(comma_csv, "w", encoding="utf-8") as stream:
    stream.write(
        "Название,Папка,Размер,Битрейт,Совпадение\n"
        "b.mp3,/p,1 MB,320,SHA256\n"
        "b.mp3,/q,1 MB,320,SHA256\n"
    )
comma_groups = duplsearch.read_csv(comma_csv)
OUT.write(f"  групп: {len(comma_groups)}, файлов: "
          f"{len(comma_groups[0]['files']) if comma_groups else 0}\n")
ok("файл с запятыми прочитан",
   len(comma_groups) == 1 and len(comma_groups[0]["files"]) == 2)

# ------------------------------------------------------------------ 5. мусор
OUT.write("\n--- 5. Посторонний файл ---\n")
bad_csv = os.path.join(tmp, "bad.csv")
with open(bad_csv, "w", encoding="utf-8") as stream:
    stream.write("что;то\nсовсем;другое\n")

try:
    duplsearch.read_csv(bad_csv)
    ok("мусорный файл отклонён", False, "исключения не было")
except duplsearch.CsvImportError as exc:
    OUT.write(f"  сообщение: {exc}\n")
    ok("мусорный файл отклонён", True)
    ok("сообщение объясняет причину",
       "Название" in str(exc) or "дубликат" in str(exc), str(exc))

# Файла нет вовсе
try:
    duplsearch.read_csv(os.path.join(tmp, "нет-такого.csv"))
    ok("отсутствующий файл отклонён", False)
except duplsearch.CsvImportError:
    ok("отсутствующий файл отклонён", True)

# ------------------------------------------------------------------ 6. GUI
OUT.write("\n--- 6. Кнопки во вкладке ---\n")
app = QApplication.instance() or QApplication([])
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.critical = staticmethod(lambda *a, **k: None)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)

from musicsuite.main_window import MainWindow

window = MainWindow()
window.resize(1500, 900)
window.show()
pump(100)

tab = window.duplicates_tab
window.tabs.setCurrentWidget(tab)
app.processEvents()

ok("кнопка импорта есть", hasattr(tab, "import_btn"))
ok("подпись кнопки импорта",
   "Импортировать" in tab.import_btn.text(), tab.import_btn.text())
ok("кнопка пересоздания есть", hasattr(tab, "recreate_btn"))
ok("подпись кнопки пересоздания",
   "Пересоздать" in tab.recreate_btn.text(), tab.recreate_btn.text())
ok("пересоздание заблокировано без данных",
   not tab.recreate_btn.isEnabled())

# Импорт через вкладку
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (csv_path, ""))
tab.on_import_csv()
pump(150)

OUT.write(f"  групп в таблице: {tab.groups_tree.topLevelItemCount()}\n")
OUT.write(f"  статус: {tab.status_label.text()}\n")
ok("группы появились после импорта",
   tab.groups_tree.topLevelItemCount() == 2,
   str(tab.groups_tree.topLevelItemCount()))
ok("пересоздание стало доступно", tab.recreate_btn.isEnabled())
ok("в статусе указано число файлов", "файлов" in tab.status_label.text())

# ------------------------------------------------------------------ 7. пересоздание
OUT.write("\n--- 7. Пересоздание после удаления ---\n")
first_group = tab._groups[0]
victim = first_group["files"][-1]["path"]
files_before = sum(len(g["files"]) for g in tab._groups)
OUT.write(f"  удаляем: {os.path.basename(os.path.dirname(victim))}/"
          f"{os.path.basename(victim)}\n")

tab.on_delete_path(victim)
pump(200)

files_after = sum(len(g["files"]) for g in tab._groups)
OUT.write(f"  файлов было {files_before}, стало {files_after}\n")
ok("файл удалён с диска", not os.path.exists(victim))
ok("список сократился", files_after == files_before - 1)

new_csv = os.path.join(tmp, "recreated.csv")
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (new_csv, ""))
tab.on_recreate_csv()
pump(150)

ok("отчёт создан", os.path.isfile(new_csv))
recreated_body = open(new_csv, encoding="utf-8-sig").read()
OUT.write("  пересозданный отчёт:\n")
for line in recreated_body.strip().splitlines():
    OUT.write(f"    {line}\n")

ok("удалённого файла нет в отчёте",
   os.path.basename(victim) not in recreated_body
   or victim.replace(os.sep, "/") not in recreated_body.replace(os.sep, "/"))
ok("в отчёте есть колонка «Группа»", "Группа" in recreated_body)

rounded = duplsearch.read_csv(new_csv)
ok("пересозданный отчёт читается обратно", len(rounded) >= 1)

OUT.write("\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ\n")
