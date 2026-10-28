"""Регрессия: scan_directory обязан принимать progress (TypeError при вызове из вкладки).

Проверяем три вещи:
  1. вызов с progress не падает и корректно репортит start/advance/finish;
  2. total в start равен числу найденных файлов;
  3. вызов без progress ведёт себя ровно как исходный CLI-скрипт.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mutagen.id3 import ID3, TALB, TIT2

from musicsuite.engines import fixtags
from musicsuite.progress import NullProgress

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _helpers import make_mp3  # noqa: E402


class Spy(NullProgress):
    def __init__(self):
        self.events = []

    def start(self, total=0, text=""):
        super().start(total, text)
        self.events.append(("start", total, text))

    def advance(self, step=1, text=""):
        super().advance(step, text)
        self.events.append(("advance", self.done, text))

    def finish(self, text=""):
        self.events.append(("finish", text))


def ok(label, condition):
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    if not condition:
        raise SystemExit(1)


tmp = tempfile.mkdtemp(prefix="fixtags_scan_")
cases = [
    ("Vallйe De Larmes", "Dьsseldorf, Germany"),   # битые
    ("Vallée De Larmes", "Düsseldorf, Germany"),   # корректные
    ("Песня", "Альбом"),                            # кириллица
]
for index, (title, album) in enumerate(cases, start=1):
    folder = os.path.join(tmp, f"disc{index}")
    os.makedirs(folder, exist_ok=True)
    make_mp3(os.path.join(folder, f"track{index}.mp3"), title, album)

print("--- вызов с progress ---")
spy = Spy()
items = fixtags.scan_directory(tmp, ".mp3", progress=spy)

for event in spy.events:
    print("  ", event)

ok("start получил верный total", spy.events[0][0] == "start" and spy.events[0][1] == 3)
ok("advance вызван по разу на файл",
   sum(1 for e in spy.events if e[0] == "advance") == 3)
ok("finish вызван", any(e[0] == "finish" for e in spy.events))
ok("правки найдены", bool(items))

print("\n--- найденные правки ---")
for item in items:
    print(f"  {item.filename:14} {item.field_name:8} {item.old_text!r} -> {item.new_text!r}")

print("\n--- вызов без progress (совместимость с CLI) ---")
items_cli = fixtags.scan_directory(tmp, ".mp3")
ok("результат совпадает", len(items_cli) == len(items))

print("\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
