"""Регрессия: префикс пути не должен «прилипать» к имени папки.

Баг: при папке ``D:/prj/music_suite/M1`` и префиксе ``/music`` путь
получался ``/music_suite/M1/...`` — префикс находился внутри слова
``music_suite``, потому что искался как подстрока.

Правильно: префикс плюс путь ОТНОСИТЕЛЬНО базовой папки,
то есть ``/music/m1/Track.mp3``.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from musicsuite.engines import plscreate


def ok(label, condition, extra=""):
    print(f"[{'OK ' if condition else 'FAIL'}] {label}{(' — ' + extra) if extra else ''}")
    if not condition:
        raise SystemExit(1)


CASES = [
    # (full_path, base_dir, rel_base, ожидание)
    ("D:/prj/music_suite/M1/m1/Absurd Minds - Zero Point.mp3",
     "D:/prj/music_suite/M1", "/music",
     "/music/m1/Absurd Minds - Zero Point.mp3"),

    ("D:/prj/music_suite/M1/m1/Status Quo - Like It Or Not.mp3",
     "D:/prj/music_suite/M1", "/music",
     "/music/m1/Status Quo - Like It Or Not.mp3"),

    # Тот самый случай: имя папки содержит слово music
    ("/tmp/music/Album/song.mp3", "/tmp/music", "/music",
     "/music/Album/song.mp3"),

    # Без префикса — просто относительный путь
    ("D:/prj/music_suite/M1/m1/song.mp3", "D:/prj/music_suite/M1", None,
     "m1/song.mp3"),
]

print("--- префикс пути ---")
for full, base, rel, expected in CASES:
    actual = plscreate.format_path(full, base_dir=base, rel_base=rel)
    print(f"  ({rel!r}) {os.path.basename(full)}")
    print(f"    получено:  {actual}")
    print(f"    ожидалось: {expected}")
    ok("путь совпал", actual == expected, actual)

print("\n--- абсолютные пути ---")
actual = plscreate.format_path(CASES[0][0], base_dir=CASES[0][1], absolute=True)
print(f"  {actual}")
ok("absolute отдаёт полный путь", actual.startswith("D:/prj/music_suite"))

print("\n--- файл вне базовой папки ---")
actual = plscreate.format_path("/other/place/song.mp3", base_dir="/tmp/music",
                               rel_base="/music")
print(f"  {actual}")
ok("не уходит в ../..", ".." not in actual)

print("\n--- base_dir не задан, префикс есть в пути как сегмент ---")
actual = plscreate.format_path("/music/m1/song.mp3", base_dir=None,
                               rel_base="/music")
print(f"  {actual}")
ok("сегмент найден корректно", actual == "/music/m1/song.mp3", actual)

print("\n--- префикс не должен совпасть с частью слова ---")
actual = plscreate.format_path("/musicology/m1/song.mp3", base_dir=None,
                               rel_base="/music")
print(f"  {actual}")
ok("word-boundary соблюдён", not actual.startswith("/music/"), actual)

print("\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
