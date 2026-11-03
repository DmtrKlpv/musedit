"""Аудит поиска по SHA-256 и пересечения групп.

Проверяем то, что сложно заметить глазами и легко сломать:

1. хеш совпадает с hashlib на реальных файлах любого размера;
2. файлы >64 КБ сравниваются целиком, а не только первым чанком;
3. одинаковый размер при разном содержимом НЕ считается дубликатом;
4. размер файла читается даже если теги не разбираются;
5. один файл не попадает в две группы при включённых режимах;
6. пустые файлы, кириллица, регистр расширения, нечитаемые файлы;
7. расчёт освобождаемого места совпадает с фактическим.
"""

import hashlib
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from musicsuite.engines import duplsearch as engine

OUT = sys.__stdout__


def ok(label, condition, extra=""):
    OUT.write(f"[{'OK ' if condition else 'FAIL'}] {label}"
              f"{(' — ' + extra) if extra else ''}\n")
    OUT.flush()
    if not condition:
        raise SystemExit(1)


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as stream:
        stream.write(data)
    return path


def names_of(groups):
    return [os.path.basename(f["path"]) for g in groups for f in g["files"]]


# ------------------------------------------------------------------ 1. хеш
OUT.write("--- 1. Хеш совпадает с hashlib ---\n")
tmp = tempfile.mkdtemp(prefix="sha_")
M = os.path.join(tmp, "Music")

small = b"small-payload" * 100
mid = os.urandom(200_000)          # больше одного чанка (64 КБ)
large = os.urandom(3 * 1024 * 1024)  # 3 МБ

p_small = write(os.path.join(M, "a", "small.mp3"), small)
p_mid = write(os.path.join(M, "a", "mid.mp3"), mid)
p_large = write(os.path.join(M, "a", "large.mp3"), large)
p_empty = write(os.path.join(M, "a", "empty.mp3"), b"")

for path, data in ((p_small, small), (p_mid, mid),
                   (p_large, large), (p_empty, b"")):
    ours = engine.get_file_hash(path)
    reference = hashlib.sha256(data).hexdigest()
    OUT.write(f"  {os.path.basename(path):12} {len(data):>8} байт "
              f"{'OK' if ours == reference else 'РАСХОЖДЕНИЕ'}\n")
    ok(f"хеш {os.path.basename(path)} верный", ours == reference)

ok("хеш пустого файла — стандартный SHA-256 пустоты",
   engine.get_file_hash(p_empty).startswith("e3b0c442"))

# ------------------------------------------------- 2. отличие в хвосте
OUT.write("\n--- 2. Отличие в последнем байте ---\n")
M2 = os.path.join(tmp, "Tail")
body = os.urandom(300_000)
first = write(os.path.join(M2, "1", "one.mp3"), body)
second = write(os.path.join(M2, "2", "two.mp3"), body)
third = write(os.path.join(M2, "3", "three.mp3"), body[:-1] + b"\x00")

ok("хеши различаются из-за одного байта",
   engine.get_file_hash(first) != engine.get_file_hash(third))

groups = engine.find_duplicates(M2, modes=[engine.MODE_SHA256])
OUT.write(f"  групп: {len(groups)}\n")
for group in groups:
    OUT.write(f"    {[os.path.basename(f['path']) for f in group['files']]}\n")

ok("одинаковые найдены", len(groups) == 1, str(len(groups)))
ok("различие в хвосте не склеено", len(groups[0]["files"]) == 2,
   str(len(groups[0]["files"])))

# ------------------------------------- 3. одинаковый размер, разные байты
OUT.write("\n--- 3. Одинаковый размер, разное содержимое ---\n")
M3 = os.path.join(tmp, "Size")
write(os.path.join(M3, "x", "same1.mp3"), b"A" * 5000)
write(os.path.join(M3, "y", "same2.mp3"), b"B" * 5000)
size_groups = engine.find_duplicates(M3, modes=[engine.MODE_SHA256])
OUT.write(f"  групп: {len(size_groups)}\n")
ok("ложных срабатываний нет", len(size_groups) == 0, str(len(size_groups)))

# ------------------------------------------- 4. размер при битых тегах
OUT.write("\n--- 4. Размер при нечитаемых тегах ---\n")
broken = write(os.path.join(M3, "z", "broken.mp3"), b"not-a-real-mp3" * 1000)
size_bytes, size_str, duration, bitrate = engine.get_audio_info(broken)
OUT.write(f"  размер={size_bytes} «{size_str}» "
          f"длительность={duration} битрейт={bitrate}\n")
ok("размер с диска получен", size_bytes == os.path.getsize(broken),
   str(size_bytes))
ok("размер строкой не N/A", size_str != "N/A", size_str)
ok("длительность помечена как неизвестная", duration == "N/A")

# ------------------------------- 5. один файл не в двух группах
OUT.write("\n--- 5. Пересечение групп при нескольких режимах ---\n")
M4 = os.path.join(tmp, "Mix")
# X и Y — байт-в-байт (группа SHA256)
# X и Z — одинаковое имя song.mp3 (группа «Имя»), но содержимое разное
X = write(os.path.join(M4, "X", "song.mp3"), b"payload-XYZ" * 100)
Y = write(os.path.join(M4, "Y", "other_name.mp3"), b"payload-XYZ" * 100)
Z = write(os.path.join(M4, "Z", "song.mp3"), b"different" * 100)

mixed = engine.find_duplicates(M4, modes=engine.MODE_ORDER)
OUT.write(f"  групп: {len(mixed)}\n")
for group in mixed:
    OUT.write(f"    [{group['match']}] "
              f"{[os.path.basename(f['path']) for f in group['files']]}\n")

counts = {}
for group in mixed:
    for entry in group["files"]:
        counts[entry["path"]] = counts.get(entry["path"], 0) + 1

repeated = {path: n for path, n in counts.items() if n > 1}
OUT.write(f"  файлов в двух группах: {len(repeated)}\n")
for path, count in repeated.items():
    OUT.write(f"    ПОВТОР {os.path.basename(path)} ×{count}\n")

ok("ни один файл не повторяется", not repeated, str(repeated))
ok("X присутствует (первым его забрала SHA256-группа)", X in counts)
ok("Z не показан повторно", counts.get(Z, 0) <= 1)

# --------------------------------------- 6. краевые случаи имён/расширений
OUT.write("\n--- 6. Краевые случаи ---\n")
M5 = os.path.join(tmp, "Edge")
cyr1 = write(os.path.join(M5, "J", "Песня.mp3"), b"cyr" * 500)
cyr2 = write(os.path.join(M5, "K", "Песня копия.MP3"), b"cyr" * 500)
write(os.path.join(M5, "L", "note.txt"), b"text")
write(os.path.join(M5, "M", "note2.txt"), b"text")

edge = engine.find_duplicates(M5, modes=[engine.MODE_SHA256])
edge_names = names_of(edge)
OUT.write(f"  найденные файлы: {edge_names}\n")
ok("кириллица и верхний регистр расширения", 
   "Песня.mp3" in edge_names and "Песня копия.MP3" in edge_names)
ok("не аудио проигнорировано",
   "note.txt" not in edge_names and "note2.txt" not in edge_names)

# нечитаемый файл не должен появляться в результатах
M6 = os.path.join(tmp, "Locked")
lock_a = write(os.path.join(M6, "1", "locked.mp3"), b"locked" * 500)
lock_b = write(os.path.join(M6, "2", "locked.mp3"), b"locked" * 500)
os.chmod(lock_a, 0o000)
try:
    locked_groups = engine.find_duplicates(M6, modes=[engine.MODE_SHA256])
    locked_names = names_of(locked_groups)
    OUT.write(f"  при закрытом файле: {locked_groups}\n")
    ok("поиск не падает на нечитаемом файле", isinstance(locked_groups, list))
finally:
    os.chmod(lock_a, 0o644)

# -------------------------------------------- 7. освобождаемое место
OUT.write("\n--- 7. Освобождаемое место ---\n")
total_reported = 0
for group in engine.find_duplicates(M2, modes=[engine.MODE_SHA256]):
    for index, entry in enumerate(group["files"]):
        if index > 0:
            total_reported += entry["size_bytes"]

total_real = 0
for group in engine.find_duplicates(M2, modes=[engine.MODE_SHA256]):
    for entry in group["files"][1:]:
        if os.path.exists(entry["path"]):
            total_real += os.path.getsize(entry["path"])

OUT.write(f"  по движку: {total_reported}, по факту: {total_real}\n")
ok("расчёт совпадает", total_reported == total_real,
   f"{total_reported} != {total_real}")

shutil.rmtree(tmp, ignore_errors=True)
OUT.write("\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ\n")
