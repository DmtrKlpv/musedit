"""Проверка движка «Обновление плейлиста» на реальных файлах."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from musicsuite.engines import plscreate
from musicsuite.engines import update_playlist as up


def make_track(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\xFF\xFB\x90\x64" + b"\x00" * 100)


def ok(label, condition):
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    if not condition:
        raise SystemExit(1)


tmp = tempfile.mkdtemp(prefix="upl_")
music = os.path.join(tmp, "Music")

make_track(os.path.join(music, "Artist - One.mp3"))
make_track(os.path.join(music, "Artist - Two.mp3"))
make_track(os.path.join(music, "Album", "Artist - Three.mp3"))

pl = os.path.join(tmp, "test.m3u8")
plscreate.save_playlist(pl, ["Artist - One.mp3", "Artist - Two.mp3"], "m3u8", "test")
print("--- стартовый плейлист ---")
print(open(pl, encoding="utf-8").read().strip())

# Меняем папку: удаляем один трек, добавляем новый
os.remove(os.path.join(music, "Artist - Two.mp3"))
make_track(os.path.join(music, "Artist - Four.mp3"))

rep = up.update_playlist(pl, music)
print(f"\n--- результат ---\nwritten={rep.written}")
print("kept:   ", rep.kept)
print("added:  ", rep.added)
print("removed:", rep.removed)
print("\n--- новый плейлист ---")
print(open(pl, encoding="utf-8").read().strip())

ok("существующий трек сохранён", any("One" in k for k in rep.kept))
ok("добавлен трек из подпапки", any("Three" in a for a in rep.added))
ok("добавлен новый трек", any("Four" in a for a in rep.added))
ok("отмечен удалённый трек", any("Two" in r for r in rep.removed))
ok("файл перезаписан", rep.written)

rep2 = up.update_playlist(pl, music)
print(f"\nповторный запуск: written={rep2.written} — {rep2.summary}")

pl2 = os.path.join(tmp, "pref.m3u8")
with open(pl2, "w", encoding="utf-8") as f:
    f.write("#EXTM3U\n")
rep3 = up.update_playlist(pl2, music, rel_base="/music")
content = open(pl2, encoding="utf-8").read()
print("\n--- с префиксом /music ---")
print(content.strip())
tracks = [l for l in content.splitlines() if l and not l.startswith("#")]
ok("префикс применён ко всем путям", all(t.startswith("/music/") for t in tracks))

rep4 = up.update_playlist(os.path.join(tmp, "nope.m3u8"), music)
print(f"\nнесуществующий плейлист → {rep4.error}")
ok("ошибка обработана", bool(rep4.error))

print("\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
