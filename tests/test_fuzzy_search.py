"""Регрессия: поиск по названию трека, когда имя файла записано иначе.

Баг из реальной библиотеки: в плейлисте строка
    /music/All/db1/System Of A Down - Aerials.mp3
а на диске тот же трек лежит как
    Дискографии/System Of A Down/Albums/.../14 - Aerials.mp3

Индекс строился по полному нормализованному имени, поэтому
"system of a down aerials" не совпадало с "14 aerials", и папка
дискографии полностью игнорировалась.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from musicsuite.engines import playlist_search as engine

OUT = sys.__stdout__


def ok(label, condition, extra=""):
    OUT.write(f"[{'OK ' if condition else 'FAIL'}] {label}"
              f"{(' — ' + extra) if extra else ''}\n")
    OUT.flush()
    if not condition:
        raise SystemExit(1)


def make_track(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as stream:
        stream.write(b"\xFF\xFB\x90\x64" + b"\x00" * 200)


# ------------------------------------------------------------------ сценарий
tmp = tempfile.mkdtemp(prefix="fuzzy_")
music = os.path.join(tmp, "Music")

# Дискография: имена вида «14 - Aerials.mp3»
deep = os.path.join(
    music, "Дискографии", "System Of A Down", "Albums",
    "System Of A Down - 2001 - Toxicity",
)
make_track(os.path.join(deep, "14 - Aerials.mp3"))
make_track(os.path.join(deep, "06 - Chop Suey!.mp3"))
make_track(os.path.join(deep, "01 - Prison Song.mp3"))

# Плоская папка: имена вида «Artist - Track.mp3»
make_track(os.path.join(music, "All", "db1", "System Of A Down - Aerials.mp3"))
make_track(os.path.join(music, "All", "db1", "Sum 41 - Fat Lip.mp3"))

playlist = os.path.join(tmp, "p.m3u8")
with open(playlist, "w", encoding="utf-8") as stream:
    stream.write("#EXTM3U\n")
    for path in (
        "/music/All/db1/System Of A Down - Aerials.mp3",
        "/music/All/db1/System Of A Down - Chop Suey!.mp3",
        "/music/All/db1/System Of A Down - Prison Song.mp3",
        "/music/All/db1/Sum 41 - Fat Lip.mp3",
        "/music/All/db1/System Of A Down - NoSuchSong.mp3",
    ):
        stream.write(path + "\n")

OUT.write("--- 1. Поиск с разными именами файлов ---\n")
result = engine.find_playlist_matches(playlist, music, rel_base="/music")
for row in result.rows:
    OUT.write(f"  {row.track_name:38} путей={row.option_count} "
              f"fuzzy={row.fuzzy}\n")
    for index, candidate in enumerate(row.candidates[:3]):
        OUT.write(f"      [{index}] {candidate}\n")

by_name = {row.track_name: row for row in result.rows}

ok("всего строк разобрано", len(result.rows) == 5)
ok("Aerials найден", by_name["System Of A Down - Aerials.mp3"].option_count >= 2)
ok("Chop Suey найден по названию",
   by_name["System Of A Down - Chop Suey!.mp3"].option_count >= 1)
ok("Prison Song найден по названию",
   by_name["System Of A Down - Prison Song.mp3"].option_count >= 1)
ok("Fat Lip найден по точному имени",
   by_name["Sum 41 - Fat Lip.mp3"].option_count >= 1)
ok("несуществующий трек не найден",
   by_name["System Of A Down - NoSuchSong.mp3"].option_count == 0)

# Ключевая проверка из жалобы: файл из Дискографии виден в кандидатах
aerials = by_name["System Of A Down - Aerials.mp3"]
deep_paths = [c for c in aerials.candidates if "Дискографии" in c]
OUT.write(f"\n  варианты из Дискографии: {deep_paths}\n")
ok("файл из папки Дискографии попал в кандидаты", bool(deep_paths),
   str(aerials.candidates))
ok("имя файла в нём — 14 - Aerials.mp3",
   deep_paths and "14 - Aerials.mp3" in deep_paths[0])

chop = by_name["System Of A Down - Chop Suey!.mp3"]
ok("Chop Suey сопоставлен именно с 06 - Chop Suey!",
   any("06 - Chop Suey!" in c for c in chop.candidates),
   str(chop.candidates))
ok("Chop Suey помечен как нечёткое совпадение", chop.fuzzy)

# ------------------------------------------------------------------ запись
OUT.write("\n--- 2. Запись выбранного варианта ---\n")
target = deep_paths[0]
aerials.new_path = target
changed = engine.apply_single(playlist, aerials)
body = open(playlist, encoding="utf-8").read()
OUT.write("  файл после записи:\n")
for line in body.strip().splitlines():
    OUT.write(f"    {line}\n")

ok("строка заменена", changed == 1)
ok("в файле путь из Дискографии", target in body)
ok("комментарии целы", body.count("#EXTINF") == 0 and body.startswith("#EXTM3U"))

# ------------------------------------------------------- токены названия
OUT.write("\n--- 3. Разбор названия трека ---\n")
cases = [
    ("System Of A Down - Aerials.mp3", "Aerials"),
    ("14 - Chop Suey!.mp3", "Chop Suey!"),
    ("Artist – Song Name.mp3", "Song Name"),
    ("Artist — Track.mp3", "Track"),
    ("NoSeparator.mp3", "NoSeparator"),
]
for raw, expected in cases:
    actual = engine.track_title(raw)
    OUT.write(f"  {raw:36} -> {actual!r}\n")
    ok("название извлечено", actual == expected, actual)

tokens = engine.title_tokens("System Of A Down - Aerials.mp3")
OUT.write(f"  токены Aerials: {tokens}\n")
ok("служебные слова отброшены", "of" not in tokens and "a" not in tokens)
ok("значимое слово осталось", "aerials" in tokens)

tokens2 = engine.title_tokens("14 - Chop Suey!.mp3")
OUT.write(f"  токены Chop Suey: {tokens2}\n")
ok("номер трека отброшен", not any(t.isdigit() for t in tokens2))
ok("оба слова названия на месте",
   "chop" in tokens2 and "suey" in tokens2, str(tokens2))

OUT.write("\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ\n")
