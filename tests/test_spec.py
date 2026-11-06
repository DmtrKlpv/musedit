"""Спецификация сборки: без падающих модулей и без лишних зависимостей.

Два предупреждения при сборке были безобидны, но мешали читать лог
и скрывали настоящие проблемы:

1. ``yandex_music.ynison`` требует betterproto и websockets — их нет в
   requirements.txt, а приложение Ynison не использует вовсе (только
   ``Client`` для загрузки треков).
2. ``send2trash.mac`` / ``send2trash.win`` — модуль чужой платформы.
   Вне macOS ``platform.mac_ver()`` возвращает пустую строку, разбор
   которой падает с ValueError.

Тест проверяет, что спецификация собирает нужное и не пытается
импортировать ненужное.
"""

import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OUT = sys.__stdout__
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ok(label, condition, extra=""):
    OUT.write(f"[{'OK ' if condition else 'FAIL'}] {label}"
              f"{(' — ' + extra) if extra else ''}\n")
    OUT.flush()
    if not condition:
        raise SystemExit(1)


spec_path = os.path.join(ROOT, "music_suite.spec")
spec = open(spec_path, encoding="utf-8").read()

# ------------------------------------------------------------ 1. текст
OUT.write("--- 1. Спецификация ---\n")
ok("spec на месте", os.path.isfile(spec_path))

ok("ynison исключён из сбора",
   "yandex_music.ynison" in spec and "filter" in spec)
ok("есть фильтр платформенных модулей send2trash",
   "send2trash" in spec and "_FOREIGN_TRASH" in spec)
ok("чужие модули попадают в excludes",
   "excludes" in spec and '"yandex_music.ynison"' in spec)
ok("betterproto и websockets не тянутся",
   '"betterproto"' in spec and '"websockets"' in spec)

# Имя EXE и иконка — были раньше, не должны потеряться
ok("имя сборки MusEdit", 'name="MusEdit"' in spec)
ok("иконка подключена", "assets/icon.ico" in spec)
ok("console выключен", "console=False" in spec)

# ------------------------------------------------- 2. фильтры в работе
OUT.write("\n--- 2. Фильтры в работе ---\n")
code = r"""
import sys
from PyInstaller.utils.hooks import collect_submodules

mods = collect_submodules(
    "yandex_music",
    filter=lambda n: not n.startswith("yandex_music.ynison"),
)
assert not [m for m in mods if "ynison" in m], "ynison попал в сборку"
assert "yandex_music.client" in mods, "Client потерялся"

foreign = {"win32": ("send2trash.mac",), "darwin": ("send2trash.win",)}.get(
    sys.platform, ("send2trash.mac", "send2trash.win"))
trash = collect_submodules(
    "send2trash", filter=lambda n: not n.startswith(foreign)
)
assert trash, "send2trash не собрался"

print(f"yandex_music: {len(mods)} модулей, Client на месте")
print(f"send2trash: {len(trash)} модулей ({sys.platform})")
print("NO_WARNINGS")
"""
result = subprocess.run([sys.executable, "-c", code],
                        capture_output=True, text=True)
OUT.write(f"  вывод: {result.stdout.strip()[-200:]}\n")

ok("сбор подмодулей без предупреждений",
   "Failed to collect submodules" not in (result.stdout + result.stderr),
   (result.stdout + result.stderr)[-200:])
ok("скрипт сбора отработал", "NO_WARNINGS" in result.stdout,
   result.stderr[-200:])
ok("Client в сборке", "Client на месте" in result.stdout)

# ------------------------------------- 3. Ynison действительно не нужен
OUT.write("\n--- 3. Зависимости приложения ---\n")
requirements = open(os.path.join(ROOT, "requirements.txt"),
                    encoding="utf-8").read().lower()

ok("betterproto не требуется", "betterproto" not in requirements)
ok("websockets не требуется", "websockets" not in requirements)
ok("yandex_music требуется", "yandex_music" in requirements)

# Приложение нигде не обращается к Ynison
usages = []
for folder, dirs, files in os.walk(os.path.join(ROOT, "musicsuite")):
    if "__pycache__" in folder:
        continue
    for name in files:
        if not name.endswith(".py"):
            continue
        body = open(os.path.join(folder, name), encoding="utf-8").read()
        if re.search(r"\bynison\b", body, re.IGNORECASE):
            usages.append(name)

OUT.write(f"  упоминания Ynison в коде: {usages}\n")
ok("Ynison не используется в коде", not usages, str(usages))

OUT.write("\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ\n")
