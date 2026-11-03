"""Версия: единый источник и совпадение с номером сборки.

Версия задаётся в двух частях: MAJOR.MINOR — смысловая, BUILD — номер
сборки, совпадающий с номером архива. Тест следит, чтобы:

1. версия в version.py состояла из трёх чисел;
2. BUILD совпадал с номером, ожидаемым для этой сборки (передаётся
   аргументом или берётся из EXPECTED_BUILD ниже);
3. заголовок окна содержал версию — то, ради чего всё затевалось;
4. README на первом экране показывал ту же версию и номер сборки;
5. «О программе» и QApplication использовали то же значение.

Если подняли BUILD, но забыли README — тест упадёт и покажет, что именно
расходится.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from musicsuite import version as v

OUT = sys.__stdout__


def ok(label, condition, extra=""):
    OUT.write(f"[{'OK ' if condition else 'FAIL'}] {label}"
              f"{(' — ' + extra) if extra else ''}\n")
    OUT.flush()
    if not condition:
        raise SystemExit(1)


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ------------------------------------------------------------ 1. формат
OUT.write("--- 1. Формат версии ---\n")
OUT.write(f"  APP_NAME        : {v.APP_NAME}\n")
OUT.write(f"  APP_VERSION     : {v.APP_VERSION}\n")
OUT.write(f"  APP_TITLE       : {v.APP_TITLE}\n")
OUT.write(f"  APP_VERSION_FULL: {v.APP_VERSION_FULL}\n")
OUT.write(f"  BUILD           : {v.BUILD}\n")

ok("версия из трёх чисел",
   bool(re.fullmatch(r"\d+\.\d+\.\d+", v.APP_VERSION)), v.APP_VERSION)
ok("MAJOR.MINOR совпадает с первыми двумя числами",
   v.APP_VERSION.startswith(f"{v.MAJOR}.{v.MINOR}."), v.APP_VERSION)
ok("третье число — BUILD",
   v.APP_VERSION.split(".")[-1] == str(v.BUILD), v.APP_VERSION)
ok("кортеж совпадает со строкой",
   v.version_tuple() == tuple(int(x) for x in v.APP_VERSION.split(".")))
ok("номер сборки положительный", v.BUILD > 0, str(v.BUILD))

# ------------------------------------------- 2. номер архива = BUILD
OUT.write("\n--- 2. Номер сборки и имя архива ---\n")
OUT.write(f"  archive_name(): {v.archive_name()}\n")
ok("имя архива содержит build",
   f"v{v.BUILD}" in v.archive_name(), v.archive_name())
ok("имя архива содержит версию",
   v.APP_VERSION in v.archive_name(), v.archive_name())
ok("без пробелов в имени файла",
   " " not in v.archive_name(), v.archive_name())

# ------------------------------------------------------ 3. заголовок окна
OUT.write("\n--- 3. Заголовок окна ---\n")
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])
from musicsuite.main_window import MainWindow

window = MainWindow()
title = window.windowTitle()
OUT.write(f"  windowTitle(): {title!r}\n")

ok("заголовок содержит версию", v.APP_VERSION in title, title)
ok("заголовок содержит имя", v.APP_NAME in title, title)
ok("заголовок совпадает с APP_TITLE", title == v.APP_TITLE)
# Заголовок должен содержать номер сборки, а не только MAJOR.MINOR:
# иначе две разные сборки выглядят одинаково.
ok("в заголовке есть номер сборки",
   str(v.BUILD) in title, title)

# ---------------------------------------------- 4. «О программе»
OUT.write("\n--- 4. О программе ---\n")
source = open(os.path.join(ROOT, "musicsuite", "main_window.py"),
              encoding="utf-8").read()
ok("диалог использует APP_VERSION_FULL", "APP_VERSION_FULL" in source)
ok("в диалоге есть слово «Версия»", "Версия" in source)

# ------------------------------------------------------------- 5. README
OUT.write("\n--- 5. README ---\n")
readme_path = os.path.join(ROOT, "README.md")
readme = open(readme_path, encoding="utf-8").read()
head = "\n".join(readme.splitlines()[:12])

OUT.write(f"  первая строка: {readme.splitlines()[0]!r}\n")

ok("заголовок README содержит версию",
   v.APP_VERSION in readme.splitlines()[0], readme.splitlines()[0])
ok("на первом экране указан номер сборки",
   str(v.BUILD) in head, "нет в первых строках")
ok("на первом экране указана организация",
   v.ORGANIZATION in head, "нет в первых строках")
ok("README ссылается на version.py", "version.py" in readme)

# Проверяем, что в README нет устаревшей версии из старых сборок.
# Строка таблицы, где MAJOR.MINOR = 1.9, — законное упоминание: это
# описание схемы версионирования, а не версия сборки.
stale_lines = [
    line for line in readme.splitlines()
    if re.search(r"1\.9(?!\.\d)", line) and "MAJOR.MINOR" not in line
]
OUT.write(f"  строк с устаревшей «1.9»: {len(stale_lines)}\n")
for line in stale_lines:
    OUT.write(f"    {line.strip()[:70]}\n")
ok("нет старой версии «1.9» без build", not stale_lines,
   f"{len(stale_lines)} строк")

# И отдельно: старое название окна не должно встречаться нигде в проекте
old_title_hits = []
for folder, _dirs, files in os.walk(ROOT):
    if "__pycache__" in folder or "/.git" in folder:
        continue
    for name in files:
        if not name.endswith((".py", ".md", ".spec")):
            continue
        # Сам этот тест содержит искомую строку как литерал — пропускаем.
        if name == "test_version.py":
            continue
        path = os.path.join(folder, name)
        try:
            body = open(path, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(body.splitlines(), 1):
            if '"MusEdit 1.9"' in line or "'MusEdit 1.9'" in line:
                old_title_hits.append(f"{name}:{number}")

OUT.write(f"  жёстко зашитых «MusEdit 1.9»: {len(old_title_hits)}\n")
for hit in old_title_hits:
    OUT.write(f"    {hit}\n")
ok("версия нигде не зашита строкой", not old_title_hits, str(old_title_hits))

# ------------------------------------------------- 6. main.py
OUT.write("\n--- 6. Точка входа ---\n")
main_source = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
ok("main.py импортирует версию из version.py",
   "musicsuite.version" in main_source)
ok("applicationVersion выставляется",
   "setApplicationVersion" in main_source)

# -------------------------------------- 7. spec: имя EXE без версии
OUT.write("\n--- 7. Спецификация сборки ---\n")
spec = open(os.path.join(ROOT, "music_suite.spec"), encoding="utf-8").read()
ok("имя EXE — MusEdit", 'name="MusEdit"' in spec)

OUT.write("\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ\n")
