"""Префикс пути во вкладке «Создание плейлиста».

Префикс задаёт, с какого пути записывать треки. Раньше можно было
указать «/music/Дискографии», а в файл попадало «/music» — префикс
терял часть. Сейчас префикс подставляется целиком, а повторяющиеся
сегменты убираются.

Проверяем:
1. префикс с папкой сохраняется целиком: /music/Дискографии/Арист1/...;
2. папка, уже входящая в префикс, не дублируется;
3. пустой префикс — пути от сканируемой папки;
4. обратные слэши и хвостовой слэш нормализуются;
5. полные пути игнорируют префикс;
6. все форматы плейлистов сохраняют префикс;
7. GUI передаёт префикс без искажений.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from musicsuite.engines import folderplaylists as engine

OUT = sys.__stdout__


def ok(label, condition, extra=""):
    OUT.write(f"[{'OK ' if condition else 'FAIL'}] {label}"
              f"{(' — ' + extra) if extra else ''}\n")
    OUT.flush()
    if not condition:
        raise SystemExit(1)


def make_tree(base):
    """D:/Music/Дискографии/Арист1/2001 - Первый/01 - Песня.mp3"""
    music = os.path.join(base, "Music")
    root = os.path.join(music, "Дискографии")
    for artist in ("Арист1", "Арист2"):
        track = os.path.join(root, artist, "2001 - Первый", "01 - Песня.mp3")
        os.makedirs(os.path.dirname(track), exist_ok=True)
        with open(track, "wb") as stream:
            stream.write(b"x")
    return music, root


def paths_of(result):
    playlist = next(r for r in result if r["path"])
    return [line for line in
            open(playlist["path"], encoding="utf-8").read().splitlines()
            if line and not line.startswith("#")]


def build(base, folder, prefix, absolute=False, fmt="m3u"):
    out = os.path.join(base, f"out_{abs(hash((folder, prefix, absolute, fmt)))}")
    return engine.build_playlists(
        folder, use_main_folder=True, prefix=prefix, absolute=absolute,
        playlist_format=fmt, sort_by=engine.SORT_BY_PATH, save_dir=out,
    )


# ------------------------------------------------- 1. префикс целиком
OUT.write("--- 1. Префикс с папкой ---\n")
base = tempfile.mkdtemp(prefix="prefix_")
music, root = make_tree(base)

lines = paths_of(build(base, root, "/music/Дискографии"))
OUT.write(f"  {lines[0]}\n")
ok("префикс сохранён целиком",
   lines[0] == "/music/Дискографии/Арист1/2001 - Первый/01 - Песня.mp3",
   lines[0])
ok("сегмент «Дискографии» один раз",
   lines[0].count("Дискографии") == 1, lines[0])
ok("сегмент «Арист1» один раз", lines[0].count("Арист1") == 1, lines[0])

# ------------------------------------- 2. папка не дублируется в префиксе
OUT.write("\n--- 2. Совпадение папки и префикса ---\n")
# Сканируется родитель Music, а префикс содержит вложенную «Дискографии»
lines2 = paths_of(build(base, music, "/music/Дискографии"))
OUT.write(f"  папка Music, префикс /music/Дискографии:\n    {lines2[0]}\n")
ok("повтор сегмента убран",
   lines2[0].count("Дискографии") == 1, lines2[0])
ok("путь верный",
   lines2[0] == "/music/Дискографии/Арист1/2001 - Первый/01 - Песня.mp3",
   lines2[0])

# ---------------------------------------------- 3. простой и пустой префикс
OUT.write("\n--- 3. Другие префиксы ---\n")
simple = paths_of(build(base, root, "/music"))
OUT.write(f"  /music: {simple[0]}\n")
ok("/music без имени папки",
   simple[0] == "/music/Арист1/2001 - Первый/01 - Песня.mp3", simple[0])

empty = paths_of(build(base, root, ""))
OUT.write(f"  пусто: {empty[0]}\n")
ok("пустой префикс — от сканируемой папки",
   empty[0] == "Арист1/2001 - Первый/01 - Песня.mp3", empty[0])
ok("в пути нет ведущего слэша", not empty[0].startswith("/"))

# ------------------------------------------- 4. нормализация префикса
OUT.write("\n--- 4. Нормализация ---\n")
back = paths_of(build(base, root, "\\music\\Дискографии"))
OUT.write(f"  обратные слэши: {back[0]}\n")
ok("обратные слэши заменены на прямые",
   back[0] == "/music/Дискографии/Арист1/2001 - Первый/01 - Песня.mp3",
   back[0])

trail = paths_of(build(base, root, "/music/Дискографии/"))
OUT.write(f"  хвостовой слэш: {trail[0]}\n")
ok("хвостовой слэш не даёт двойного //",
   "//" not in trail[0], trail[0])
ok("путь без изменений",
   trail[0] == "/music/Дискографии/Арист1/2001 - Первый/01 - Песня.mp3",
   trail[0])

double = paths_of(build(base, root, "//music//Дискографии"))
OUT.write(f"  двойные слэши: {double[0]}\n")
ok("лишние слэши схлопнуты", "//" not in double[0], double[0])

# ------------------------------------------------- 5. полные пути
OUT.write("\n--- 5. Полные пути ---\n")
absolute = paths_of(build(base, root, "/music/Дискографии", absolute=True))
OUT.write(f"  {absolute[0]}\n")
ok("абсолютный путь от корня",
   os.path.isabs(absolute[0].replace("/", os.sep)), absolute[0])
ok("префикс не применён", not absolute[0].startswith("/music"), absolute[0])

# ------------------------------------------------- 6. все форматы
OUT.write("\n--- 6. Форматы ---\n")
for fmt in engine.FORMATS:
    out_dir = os.path.join(base, f"fmt_{fmt}")
    engine.build_playlists(
        root, use_main_folder=True, prefix="/music/Дискографии",
        absolute=False, playlist_format=fmt, sort_by=engine.SORT_BY_PATH,
        save_dir=out_dir,
    )
    path = os.path.join(out_dir, f"Арист1.{fmt}")
    body = open(path, encoding="utf-8", errors="replace").read()
    found = "/music/Дискографии/Арист1/2001 - Первый/01 - Песня.mp3" in body
    OUT.write(f"  {fmt:5} {'OK' if found else 'НЕТ ПУТИ'}\n")
    ok(f"формат {fmt} сохранил префикс", found)

# ------------------------------------------------------- 7. GUI
OUT.write("\n--- 7. Вкладка ---\n")
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.information = staticmethod(lambda *a, **k: None)

app = QApplication.instance() or QApplication([])
from musicsuite.main_window import MainWindow

window = MainWindow()
window.resize(1300, 900)
window.show()
tab = window.create_playlists_tab
window.tabs.setCurrentWidget(tab)
app.processEvents()


def pump(ms=60):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


gui_out = os.path.join(base, "gui")
tab.folder_field.setText(root)
tab.save_field.setText(gui_out)
tab.prefix_edit.setText("/music/Дискографии")
pump(120)

ok("префикс в поле без искажений",
   tab.prefix_edit.text() == "/music/Дискографии", tab.prefix_edit.text())

tab.on_create()
for _ in range(120):
    pump(60)
    if not tab.is_busy():
        break
pump(400)

gui_line = [l for l in open(os.path.join(gui_out, "Арист1.m3u"),
                            encoding="utf-8").read().splitlines()
            if l and not l.startswith("#")][0]
OUT.write(f"  через GUI: {gui_line}\n")
ok("GUI записал путь с полным префиксом",
   gui_line == "/music/Дискографии/Арист1/2001 - Первый/01 - Песня.mp3",
   gui_line)

OUT.write("\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ\n")
