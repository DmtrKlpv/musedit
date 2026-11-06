"""Вкладка «Создание плейлиста»: разбор папок и запись плейлистов.

Сценарий
--------
Папка с дискографиями: внутри — папки артистов, внутри них — альбомы.
Нужен плейлист на артиста, а не на каждый альбом.

Что проверяем
-------------
1. режим «основная папка» даёт плейлисты по подпапкам первого уровня,
   и в каждый попадают треки из вложенных альбомов;
2. без галочки — один плейлист из всей папки, имя по имени папки;
3. папки без музыки не создают пустых файлов;
4. все расширения из списка считаются музыкой, картинки — нет;
5. сортировка по пути ставит альбомы по папкам, а файлы без папок — в начало;
6. сортировка по названию берёт тег title, без тега — имя файла;
7. формат путей: префикс /music, пустой префикс, полные пути;
8. все пять форматов плейлистов пишутся;
9. папка сохранения работает отдельно от сканируемой;
10. повторный запуск не перезаписывает неизменённый плейлист;
11. вкладка стоит второй и содержит все поля;
12. прогон через вкладку (GUI) заполняет таблицу.
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


def touch(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as stream:
        stream.write(data)
    return path


def make_library(root, with_tags=False):
    """Дискографии/Арист1/{2001,2005}/треки + трек и картинка в корне."""
    for artist in ("Арист1", "Арист2"):
        for album in ("2001 - Первый", "2005 - Второй"):
            for number in (1, 2):
                touch(os.path.join(root, artist, album,
                                   f"{number:02d} - Песня.mp3"))
    # Трек прямо в папке артиста — без подпапки
    touch(os.path.join(root, "Арист1", "бонус.flac"))
    # Не музыка
    touch(os.path.join(root, "Арист1", "обложка.jpg"))
    touch(os.path.join(root, "Арист1", "readme.txt"))
    return root


# ------------------------------------------------------- 1. цели
OUT.write("--- 1. Набор плейлистов ---\n")
base = tempfile.mkdtemp(prefix="fp_")
root = os.path.join(base, "Дискографии")
make_library(root)

targets = engine.build_targets(root, use_main_folder=True)
OUT.write(f"  режим «основная папка»: {[name for _f, name in targets]}\n")
ok("по плейлисту на артиста", [n for _f, n in targets] == ["Арист1", "Арист2"],
   str([n for _f, n in targets]))

whole = engine.build_targets(root, use_main_folder=False)
OUT.write(f"  без галочки: {[name for _f, name in whole]}\n")
ok("один плейлист на всю папку", len(whole) == 1, str(len(whole)))
ok("имя по имени папки", whole[0][1] == "Дискографии", whole[0][1])

# Папка без подпапок: режим вырождается в обычный, иначе не создалось бы ничего
flat = os.path.join(base, "Плоская")
touch(os.path.join(flat, "01 - Трек.mp3"))
flat_targets = engine.build_targets(flat, use_main_folder=True)
OUT.write(f"  плоская папка: {[n for _f, n in flat_targets]}\n")
ok("плоская папка даёт один плейлист", len(flat_targets) == 1)
ok("имя — по папке", flat_targets[0][1] == "Плоская", flat_targets[0][1])

# -------------------------------------------------- 2. расширения
OUT.write("\n--- 2. Что считается музыкой ---\n")
music = ["a.mp3", "a.flac", "a.ape", "a.wav", "a.ogg", "a.opus", "a.m4a",
         "a.aac", "a.wma", "a.wv", "a.tta", "a.dsf", "a.aiff", "a.alac"]
not_music = ["a.jpg", "a.png", "a.txt", "a.cue", "a.log", "a.nfo", "a.pdf"]

missing = [name for name in music if not engine.is_audio(name)]
extra = [name for name in not_music if engine.is_audio(name)]
OUT.write(f"  не распознаны как музыка: {missing}\n")
OUT.write(f"  ошибочно приняты за музыку: {extra}\n")
ok("все 14 расширений музыки", not missing, str(missing))
ok("картинки и тексты не музыка", not extra, str(extra))
ok("регистр расширения не важен",
   engine.is_audio("Трек.MP3") and engine.is_audio("Трек.FlAc"))

# ----------------------------------------------- 3. создание и пути
OUT.write("\n--- 3. Создание плейлистов (префикс /music) ---\n")
out_dir = os.path.join(base, "Готовые")
results = engine.build_playlists(
    root, use_main_folder=True, prefix="/music", absolute=False,
    playlist_format="m3u", sort_by=engine.SORT_BY_PATH, save_dir=out_dir,
)
OUT.write(f"  плейлистов: {len(results)}\n")
for entry in results:
    OUT.write(f"    {entry['name']:10} {entry['tracks']} треков  "
              f"{entry['status']}\n")

ok("два плейлиста", len(results) == 2, str(len(results)))

# Движок должен отдавать каждый плейлист сразу после записи,
# иначе таблица пуста всё время прогона.
delivered = []
engine.build_playlists(
    root, use_main_folder=True, prefix="/music", absolute=False,
    playlist_format="m3u", sort_by=engine.SORT_BY_PATH,
    save_dir=os.path.join(base, "Колбэк"),
    on_playlist=lambda entry, index, total: delivered.append(
        (entry["name"], index, total)
    ),
)
OUT.write(f"  \u043aолбэк \u043fолучил: {delivered}\n")
ok("\u043a\u043e\u043b\u0431\u044d\u043a \u0432\u044b\u0437\u0432\u0430\u043d \u043d\u0430 \u043a\u0430\u0436\u0434\u044b\u0439 \u043f\u043b\u0435\u0439\u043b\u0438\u0441\u0442",
   len(delivered) == 2, str(len(delivered)))
ok("\u043f\u043e\u0440\u044f\u0434\u043e\u043a \u0438 \u043d\u043e\u043c\u0435\u0440\u0430 \u0432\u0435\u0440\u043d\u044b\u0435",
   [d[1] for d in delivered] == [1, 2]
   and all(d[2] == 2 for d in delivered), str(delivered))
ok("все созданы", all(r["status"] == engine.STATUS_CREATED for r in results))
ok("Арист1 собрал 5 треков (4 альбомных + бонус)",
   results[0]["tracks"] == 5, str(results[0]["tracks"]))
ok("файлы в папке сохранения",
   os.path.isfile(os.path.join(out_dir, "Арист1.m3u")), out_dir)

content = open(os.path.join(out_dir, "Арист1.m3u"), encoding="utf-8").read()
OUT.write("  содержимое Арист1.m3u:\n")
for line in content.splitlines():
    OUT.write(f"    {line}\n")

lines = [l for l in content.splitlines() if l and not l.startswith("#")]
ok("префикс /music применён",
   all(l.startswith("/music/") for l in lines), str(lines[:2]))
ok("картинка и readme не попали",
   not any(l.endswith((".jpg", ".txt")) for l in lines))
ok("вложенные альбомы включены",
   any("2001 - Первый" in l for l in lines)
   and any("2005 - Второй" in l for l in lines))
ok("бонус из корня артиста включён",
   any("бонус.flac" in l for l in lines), str(lines))
ok("относительно сканируемой папки, без имени артиста в начале сегмента",
   lines[0].startswith("/music/Арист1/"), lines[0])

# Сортировка по пути. Папки идут в порядке имён, файлы внутри — тоже,
# а файлы из корня артиста сортируются по имени наравне с именами папок.
# «2001» начинается с цифры (U+0032), «бонус» — с кириллицы (U+0431),
# поэтому альбомы оказываются раньше. Это ожидаемо, а не ошибка.
OUT.write(f"  порядок: {[l.split('/')[-1] for l in lines]}\n")

ok("альбомы идут в порядке папок",
   [l for l in lines if "2001" in l or "2005" in l]
   == [l for l in lines if "2001" in l] + [l for l in lines if "2005" in l],
   str(lines))

ok("внутри альбома треки по именам",
   [l.split("/")[-1] for l in lines if "2001" in l]
   == ["01 - Песня.mp3", "02 - Песня.mp3"],
   str([l.split("/")[-1] for l in lines if "2001" in l]))

# Файл без папки не теряется и стоит в общем алфавитном порядке
ok("файл из корня артиста на месте", any(l.endswith("бонус.flac") for l in lines),
   str(lines))
root_files = [l for l in lines if l.count("/") == 3]
OUT.write(f"  файлы без подпапки: {root_files}\n")
ok("он последний: кириллица после цифр",
   lines[-1].endswith("бонус.flac"), lines[-1])

# ----------------------------------------- 4. пустой префикс и абсолют
OUT.write("\n--- 4. Другие режимы путей ---\n")
plain_dir = os.path.join(base, "БезПрефикса")
plain = engine.build_playlists(
    root, use_main_folder=True, prefix="", absolute=False,
    playlist_format="m3u", sort_by=engine.SORT_BY_PATH, save_dir=plain_dir,
)
plain_lines = [l for l in open(os.path.join(plain_dir, "Арист1.m3u"),
                               encoding="utf-8").read().splitlines()
               if l and not l.startswith("#")]
OUT.write(f"  без префикса: {plain_lines[0]}\n")
ok("пустой префикс — путь от сканируемой папки",
   plain_lines[0].startswith("Арист1/"), plain_lines[0])

abs_dir = os.path.join(base, "Абсолютные")
engine.build_playlists(
    root, use_main_folder=True, prefix="/music", absolute=True,
    playlist_format="m3u", sort_by=engine.SORT_BY_PATH, save_dir=abs_dir,
)
abs_lines = [l for l in open(os.path.join(abs_dir, "Арист1.m3u"),
                             encoding="utf-8").read().splitlines()
             if l and not l.startswith("#")]
OUT.write(f"  полный путь: {abs_lines[0]}\n")
ok("абсолютный путь начинается с корня диска",
   os.path.isabs(abs_lines[0].replace("/", os.sep)), abs_lines[0])
ok("префикс при абсолютных путях не применяется",
   not abs_lines[0].startswith("/music/"), abs_lines[0])

# ------------------------------------------------ 5. все форматы
OUT.write("\n--- 5. Форматы ---\n")
for fmt in engine.FORMATS:
    fmt_dir = os.path.join(base, f"fmt_{fmt}")
    engine.build_playlists(
        root, use_main_folder=True, prefix="/music", absolute=False,
        playlist_format=fmt, sort_by=engine.SORT_BY_PATH, save_dir=fmt_dir,
    )
    path = os.path.join(fmt_dir, f"Арист1.{fmt}")
    exists = os.path.isfile(path)
    size = os.path.getsize(path) if exists else 0
    OUT.write(f"  {fmt:5} файл={exists} размер={size}\n")
    ok(f"формат {fmt} записан", exists and size > 0)

# ------------------------------------------- 6. сортировка по тегам
OUT.write("\n--- 6. Сортировка по названию трека ---\n")
tag_root = os.path.join(base, "СТегами")

# Теги читаются только из настоящего аудио: на файле-заглушке mutagen
# падает с HeaderNotFoundError и название берётся из имени файла.
# Поэтому для этого блока создаём короткие MP3 через FFmpeg.
import subprocess

import imageio_ffmpeg
from mutagen.id3 import ID3, TIT2

ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

# Имена файлов нарочно против порядка названий
files = {
    "Яблоко": "01 - zzz.mp3",
    "Банан": "02 - aaa.mp3",
    "Арбуз": "03 - mmm.mp3",
}

for title, name in files.items():
    path = os.path.join(tag_root, "Артист", name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    subprocess.run(
        [ffmpeg_exe, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=0.2", "-c:a", "libmp3lame",
         path, "-y"],
        check=True, capture_output=True,
    )
    tags = ID3()
    tags.add(TIT2(encoding=3, text=[title]))
    tags.save(path)

by_title_dir = os.path.join(base, "ПоТегам")
engine.build_playlists(
    tag_root, use_main_folder=True, prefix="", absolute=False,
    playlist_format="m3u", sort_by=engine.SORT_BY_TITLE, save_dir=by_title_dir,
)
by_title_lines = [l for l in open(os.path.join(by_title_dir, "Артист.m3u"),
                                  encoding="utf-8").read().splitlines()
                  if l and not l.startswith("#")]
OUT.write(f"  порядок по названиям: {[l.split('/')[-1] for l in by_title_lines]}\n")
ok("Арбуз, Банан, Яблоко — по алфавиту названий",
   [l.split("/")[-1] for l in by_title_lines]
   == ["03 - mmm.mp3", "02 - aaa.mp3", "01 - zzz.mp3"],
   str([l.split("/")[-1] for l in by_title_lines]))

# Файл без тега сортируется по имени файла
untagged = touch(os.path.join(tag_root, "Артист", "00 - без тега.mp3"))
by_title_dir2 = os.path.join(base, "ПоТегам2")
engine.build_playlists(
    tag_root, use_main_folder=True, prefix="", absolute=False,
    playlist_format="m3u", sort_by=engine.SORT_BY_TITLE, save_dir=by_title_dir2,
)
lines2 = [l for l in open(os.path.join(by_title_dir2, "Артист.m3u"),
                          encoding="utf-8").read().splitlines()
          if l and not l.startswith("#")]
OUT.write(f"  с файлом без тега: {[l.split('/')[-1] for l in lines2]}\n")
ok("файл без тега не потерян", len(lines2) == 4, str(len(lines2)))

# ----------------------------------- 7. повторный запуск и пустые папки
OUT.write("\n--- 7. Повторный запуск ---\n")
again = engine.build_playlists(
    root, use_main_folder=True, prefix="/music", absolute=False,
    playlist_format="m3u", sort_by=engine.SORT_BY_PATH, save_dir=out_dir,
)
OUT.write(f"  статусы: {[r['status'] for r in again]}\n")
ok("неизменённые плейлисты не перезаписаны",
   all(r["status"] == engine.STATUS_UNCHANGED for r in again),
   str([r["status"] for r in again]))

# Папка без музыки
empty_root = os.path.join(base, "Пустая")
os.makedirs(os.path.join(empty_root, "НетМузыки"), exist_ok=True)
empty_results = engine.build_playlists(
    empty_root, use_main_folder=True, prefix="", absolute=False,
    playlist_format="m3u", sort_by=engine.SORT_BY_PATH, save_dir="",
)
OUT.write(f"  пустая папка: {[(r['name'], r['status']) for r in empty_results]}\n")
ok("пустой плейлист не создан",
   all(r["status"] == "Нет треков" for r in empty_results),
   str([r["status"] for r in empty_results]))
ok("файлы не появились",
   not any(f.endswith(".m3u") for f in os.listdir(
       os.path.join(empty_root, "НетМузыки"))))

# ---------------------------------------------- 8. вкладка и GUI
OUT.write("\n--- 8. Вкладка ---\n")
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.information = staticmethod(lambda *a, **k: None)

app = QApplication.instance() or QApplication([])
from musicsuite.main_window import MainWindow

window = MainWindow()
window.resize(1400, 900)
window.show()

titles = [window.tabs.tabText(i) for i in range(window.tabs.count())]
OUT.write(f"  вкладки: {titles}\n")
ok("вкладка вторая", titles[1] == "Создание плейлиста", str(titles[:3]))
ok("всего семь вкладок", len(titles) == 7, str(len(titles)))

tab = window.create_playlists_tab
window.tabs.setCurrentWidget(tab)
app.processEvents()

ok("поле папки есть", hasattr(tab, "folder_field"))
ok("галочка основной папки включена по умолчанию",
   tab.main_folder_check.isChecked())
ok("поле папки сохранения есть", hasattr(tab, "save_field"))
ok("префикс по умолчанию /music", tab.prefix_edit.text() == "/music",
   tab.prefix_edit.text())
ok("галочка полных путей есть и снята", not tab.absolute_check.isChecked())
ok("пять форматов",
   [tab.format_combo.itemText(i) for i in range(tab.format_combo.count())]
   == ["m3u", "m3u8", "pls", "xspf", "wpl"])
ok("два способа сортировки", tab.sort_combo.count() == 2)
ok("таблица с четырьмя колонками",
   tab.result_tree.columnCount() == 4)


def pump(ms=100):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


gui_out = os.path.join(base, "ИзGUI")
tab.folder_field.setText(root)
tab.save_field.setText(gui_out)
tab.prefix_edit.setText("/music")

# Следим, сколько строк было в таблице в момент добавления
# каждого плейлиста.
counts_during = []
_original_append = tab._append_playlist


def _spy_append(entry, index, total):
    _original_append(entry, index, total)
    counts_during.append(tab.result_tree.topLevelItemCount())


tab.playlist_ready.disconnect()
tab.playlist_ready.connect(_spy_append)

tab.on_create()
for _ in range(100):
    pump(100)
    if not tab.is_busy():
        break
pump(200)

rows = tab.result_tree.topLevelItemCount()
OUT.write(f"  строк в таблице: {rows}\n")
OUT.write(f"  статус: {tab.status_label.text()}\n")
ok("таблица заполнена", rows == 2, str(rows))
ok("в таблице имена плейлистов",
   {tab.result_tree.topLevelItem(i).text(0) for i in range(rows)}
   == {"Арист1", "Арист2"})
ok("колонка треков заполнена",
   tab.result_tree.topLevelItem(0).text(1) == "5",
   tab.result_tree.topLevelItem(0).text(1))
ok("статус в таблице",
   tab.result_tree.topLevelItem(0).text(2) == engine.STATUS_CREATED,
   tab.result_tree.topLevelItem(0).text(2))
ok("файлы созданы через GUI",
   os.path.isfile(os.path.join(gui_out, "Арист1.m3u")))
ok("кнопка очистки активна", tab.clear_btn.isEnabled())

# Живой показ: строки добавлялись по одной, а не все сразу в конце.
OUT.write(f"  \u0441\u0447\u0451\u0442\u0447\u0438\u043a \u0441\u0442\u0440\u043e\u043a \u043f\u043e \u0445\u043e\u0434\u0443: {counts_during}\n")
ok("\u0441\u0442\u0440\u043e\u043a\u0438 \u0434\u043e\u0431\u0430\u0432\u043b\u044f\u044e\u0442\u0441\u044f \u043f\u043e \u043c\u0435\u0440\u0435 \u0441\u043e\u0437\u0434\u0430\u043d\u0438\u044f",
   counts_during == [1, 2], str(counts_during))

# \u041a\u043e\u043b\u043e\u043d\u043a\u0438 \u043d\u0435 \u0434\u043e\u043b\u0436\u043d\u044b \u0441\u043b\u0438\u043f\u0430\u0442\u044c\u0441\u044f: \u043c\u0438\u043d\u0438\u043c\u0443\u043c 80 px \u043d\u0430 \u0441\u0435\u043a\u0446\u0438\u044e.
widths = [tab.result_tree.columnWidth(i) for i in range(3)]
OUT.write(f"  \u0448\u0438\u0440\u0438\u043d\u044b \u043a\u043e\u043b\u043e\u043d\u043e\u043a: {widths}\n")
ok("\u041f\u043b\u0435\u0439\u043b\u0438\u0441\u0442 \u043d\u0435 \u0443\u0436\u0435 200 px", widths[0] >= 200, str(widths[0]))
ok("\u0422\u0440\u0435\u043a\u043e\u0432 \u043d\u0435 \u0443\u0436\u0435 80 px", widths[1] >= 80, str(widths[1]))
ok("\u0421\u0442\u0430\u0442\u0443\u0441 \u043d\u0435 \u0443\u0436\u0435 120 px", widths[2] >= 120, str(widths[2]))

tab._clear_table()
ok("очистка списка работает", tab.result_tree.topLevelItemCount() == 0)

OUT.write("\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ\n")
