"""Исключение групп из дубликатов.

Сценарий из практики: два файла «07 - Иод.mp3» совпадают по имени (и по
размеру), но один — версия с текстом, другой — минус. Удалять нельзя,
а видеть в списке каждый раз мешает. Группа исключается: пропадает из
результатов и не возвращается при повторном поиске или импорте отчёта.

Проверяем:
1. ключ группы строится по типу совпадения и именам файлов без пути;
2. исключение сохраняется в JSON и переживает перезапуск;
3. группа не появляется при повторном поиске;
4. исключение работает и при импорте CSV;
5. возврат группы из списка исключений;
6. повреждённый файл исключений не ломает приложение;
7. кнопки в интерфейсе: состояние и счётчик.
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from musicsuite.exclusions import (
    ExclusionStore, describe, group_signature,
)

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


def make_file(path, seed=1):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as stream:
        stream.write(b"\xFF\xFB\x90\x64" + bytes([seed]) * 3000)


# ------------------------------------------------------- 1. ключ группы
OUT.write("--- 1. Ключ группы ---\n")

with_vocals = {
    "match": "Имя",
    "files": [
        {"path": r"D:\Music\Babooshka\2019 - Православный Аватар\07 - Иод.mp3"},
        {"path": r"D:\Music\Babooshka (Instrumental)\2019 - Православный Аватар\07 - Иод.mp3"},
    ],
}
instrumental = {
    "match": "Имя",
    "files": [
        {"path": r"E:\Archive\Babooshka\07 - Иод.mp3"},
        {"path": r"F:\Other\07 - Иод.mp3"},
    ],
}
sha_group = {
    "match": "SHA256",
    "files": [{"path": "/m/a/song.mp3"}, {"path": "/m/b/song.mp3"}],
}

sig_vocals = group_signature(with_vocals)
sig_inst = group_signature(instrumental)
sig_sha = group_signature(sha_group)
OUT.write(f"  ключ «Имя»:    {sig_vocals}\n")
OUT.write(f"  ключ «SHA256»: {sig_sha}\n")

ok("ключ содержит имя файла", "07 - иод.mp3" in sig_vocals, sig_vocals)
ok("пути в ключ не входят", "Babooshka" not in sig_vocals)
ok("одинаковые имена дают одинаковый ключ", sig_vocals == sig_inst)

# Главное: та же пара файлов, найденная другим способом, — та же группа.
same_pair_sha = {
    "match": "SHA256",
    "files": with_vocals["files"],
}
OUT.write(f"  та же пара по SHA256: {group_signature(same_pair_sha)}\n")
ok("тип совпадения не влияет на ключ",
   group_signature(same_pair_sha) == sig_vocals)

# Группа из трёх копий — не то же самое, что из двух
triple = {
    "match": "Имя",
    "files": [{"path": "/a/s.mp3"}, {"path": "/b/s.mp3"}, {"path": "/c/s.mp3"}],
}
OUT.write(f"  группа из трёх: {group_signature(triple)}\n")
ok("число копий различается",
   group_signature(triple) != sig_vocals, group_signature(triple))

match, names = describe(sig_vocals, "Имя")
OUT.write(f"  разбор: тип={match!r}, имена={names}\n")
ok("тип передаётся снаружи", match == "Имя")
# Ключ хранит число копий: «07 - иод.mp3x2» разворачивается в два имени.
ok("имена восстанавливаются с числом копий",
   names == ["07 - иод.mp3", "07 - иод.mp3"], str(names))

match3, names3 = describe(group_signature(triple), "Имя")
OUT.write(f"  разбор трёх: имена={names3}\n")
ok("повторы имён разворачиваются", names3 == ["s.mp3"] * 3, str(names3))

# ----------------------------------------------------- 2. хранилище и JSON
OUT.write("\n--- 2. Хранилище ---\n")
store_path = os.path.join(tempfile.mkdtemp(prefix="excl_"), "exclusions.json")
store = ExclusionStore(store_path)
OUT.write(f"  файл: {store_path}\n")
ok("изначально пусто", len(store) == 0)
ok("файл ещё не создан", not os.path.isfile(store_path))

signature = store.exclude(with_vocals)
OUT.write(f"  сохранён ключ: {signature}\n")
ok("ключ вернулся", signature == sig_vocals)
ok("файл создан", os.path.isfile(store_path))

saved = json.load(open(store_path, encoding="utf-8"))
OUT.write(f"  содержимое: {json.dumps(saved, ensure_ascii=False)[:150]}\n")
ok("в файле один ключ", len(saved) == 1)
ok("сохранены пути для наглядности",
   "paths" in list(saved.values())[0])
ok("сохранены имена", "names" in list(saved.values())[0])

ok("группа считается исключённой", store.is_excluded(with_vocals))
ok("та же группа с другими путями тоже исключена",
   store.is_excluded(instrumental))
ok("другая группа не исключена", not store.is_excluded(sha_group))

# ------------------------------------------------ 3. переживает перезапуск
OUT.write("\n--- 3. Перезапуск ---\n")
reopened = ExclusionStore(store_path)
OUT.write(f"  после перезапуска: {len(reopened)}\n")
ok("исключение сохранилось", len(reopened) == 1)
ok("группа по-прежнему исключена", reopened.is_excluded(with_vocals))

# Фильтрация списка
pool = [with_vocals, sha_group]
kept = reopened.filter_groups(pool)
OUT.write(f"  из {len(pool)} групп осталось {len(kept)}\n")
ok("фильтр убирает исключённую", len(kept) == 1 and kept[0] is sha_group)

# ------------------------------------------------------- 4. возврат
OUT.write("\n--- 4. Возврат группы ---\n")
ok("возврат вернул True", reopened.restore(sig_vocals))
OUT.write(f"  после возврата: {len(reopened)}\n")
ok("список опустел", len(reopened) == 0)
ok("повторный возврат даёт False", reopened.restore(sig_vocals) is False)

# ------------------------------------------------- 5. повреждённый файл
OUT.write("\n--- 5. Повреждённый файл ---\n")
broken = os.path.join(tempfile.mkdtemp(), "broken.json")
with open(broken, "w", encoding="utf-8") as stream:
    stream.write("{ это не json ")
broken_store = ExclusionStore(broken)
OUT.write(f"  исключений после чтения битого файла: {len(broken_store)}\n")
ok("битый файл не роняет приложение", len(broken_store) == 0)

# ------------------------------------------------ 6. интеграция с вкладкой
OUT.write("\n--- 6. Вкладка ---\n")
home = tempfile.mkdtemp(prefix="home_")
os.environ["HOME"] = home
os.environ["USERPROFILE"] = home

QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.critical = staticmethod(lambda *a, **k: None)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)

app = QApplication.instance() or QApplication([])

from musicsuite.main_window import MainWindow

tmp = tempfile.mkdtemp(prefix="dupl_excl_")
root = os.path.join(tmp, "Music")

# пара «с текстом / минус» — одинаковое имя и содержимое
for folder in ("Babooshka/2019 - Аватар", "Babooshka (Instrumental)/2019 - Аватар"):
    make_file(os.path.join(root, folder, "07 - Иод.mp3"), seed=7)
# контрольная пара
for folder in ("A", "B"):
    make_file(os.path.join(root, folder, "other.mp3"), seed=9)

window = MainWindow()
window.resize(1500, 900)
window.show()
pump(100)

tab = window.duplicates_tab
window.tabs.setCurrentWidget(tab)
app.processEvents()

ok("кнопка исключения есть", hasattr(tab, "exclude_btn"))
ok("подпись кнопки", "Исключить" in tab.exclude_btn.text(),
   tab.exclude_btn.text())
ok("кнопка заблокирована без выбора", not tab.exclude_btn.isEnabled())
ok("кнопка списка исключений есть", hasattr(tab, "excluded_list_btn"))
ok("хранилище в домашней папке",
   ".musedit" in tab.exclusions.path, tab.exclusions.path)

# Поиск
tab.dir_field.setText(root)
tab.on_search()
for _ in range(120):
    pump(100)
    if not tab.is_busy():
        break
pump(300)

found = tab.groups_tree.topLevelItemCount()
OUT.write(f"  найдено групп: {found}\n")
for index in range(found):
    item = tab.groups_tree.topLevelItem(index)
    OUT.write(f"    {item.text(0):16} {item.text(1):8} копий {item.text(2)}\n")
ok("найдены обе группы", found == 2, str(found))

# Выбираем группу с «Иод» и исключаем
target_index = next(
    i for i in range(found)
    if "Иод" in tab.groups_tree.topLevelItem(i).text(0)
)
tab.groups_tree.setCurrentItem(tab.groups_tree.topLevelItem(target_index))
app.processEvents()
ok("кнопка стала активной", tab.exclude_btn.isEnabled())

tab.on_exclude_group()
pump(200)

OUT.write(f"  после исключения: групп {tab.groups_tree.topLevelItemCount()}\n")
OUT.write(f"  кнопка списка: {tab.excluded_list_btn.text()}\n")
ok("группа исчезла из таблицы", tab.groups_tree.topLevelItemCount() == 1)
ok("счётчик обновился", "1" in tab.excluded_list_btn.text())
ok("в статусе сказано про возврат", "ернуть" in tab.status_label.text()
   or "Исключен" in tab.status_label.text())
ok("файл исключений записан", os.path.isfile(tab.exclusions.path))
ok("файлы на диске не тронуты",
   os.path.isfile(os.path.join(
       root, "Babooshka (Instrumental)", "2019 - Аватар", "07 - Иод.mp3")))

# Повторный поиск — исключённая группа не возвращается
tab.on_search()
for _ in range(120):
    pump(100)
    if not tab.is_busy():
        break
pump(300)

remaining = tab.groups_tree.topLevelItemCount()
names_left = [tab.groups_tree.topLevelItem(i).text(0)
              for i in range(remaining)]
OUT.write(f"  после повторного поиска групп: {remaining}, {names_left}\n")
ok("исключённая группа не вернулась", remaining == 1, str(names_left))
ok("это контрольная группа", names_left == ["other.mp3"], str(names_left))

# ------------------------------------------------- 7. импорт CSV с фильтром
OUT.write("\n--- 7. Импорт CSV с исключением ---\n")
from musicsuite.engines import duplsearch

csv_groups = [], 
# Собираем отчёт вручную: обе группы, включая исключённую
manual = [
    {"filename": "07 - Иод.mp3", "match": "Имя", "files": [
        {"path": os.path.join(root, "Babooshka", "2019 - Аватар", "07 - Иод.mp3")},
        {"path": os.path.join(root, "Babooshka (Instrumental)", "2019 - Аватар", "07 - Иод.mp3")},
    ]},
    {"filename": "other.mp3", "match": "SHA256", "files": [
        {"path": os.path.join(root, "A", "other.mp3")},
        {"path": os.path.join(root, "B", "other.mp3")},
    ]},
]
csv_path = duplsearch.write_csv(manual, os.path.join(tmp, "report.csv"))

from PySide6.QtWidgets import QFileDialog
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (csv_path, ""))

tab.on_import_csv()
pump(200)

imported = tab.groups_tree.topLevelItemCount()
OUT.write(f"  групп после импорта: {imported}\n")
OUT.write(f"  статус: {tab.status_label.text()}\n")
ok("импорт отфильтровал исключённую группу", imported == 1, str(imported))
ok("осталась контрольная группа",
   tab.groups_tree.topLevelItem(0).text(0) == "other.mp3")

# ----------------------------------------------- 8. возврат через хранилище
OUT.write("\n--- 8. Возврат и повторный импорт ---\n")
tab.exclusions.clear()
tab.on_import_csv()
pump(200)
OUT.write(f"  групп после очистки исключений: "
          f"{tab.groups_tree.topLevelItemCount()}\n")
ok("после снятия исключения группа вернулась",
   tab.groups_tree.topLevelItemCount() == 2,
   str(tab.groups_tree.topLevelItemCount()))

OUT.write("\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ\n")
