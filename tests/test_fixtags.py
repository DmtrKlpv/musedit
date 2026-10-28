"""Тесты ремонта кодировок тегов (модуль «Исправление тегов MP3»).

Проверяется главное свойство: корректные названия не изменяются,
повреждённые — восстанавливаются.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from musicsuite.engines import fixtags

FAILED = []


def check(label, got, want):
    if got == want:
        print(f"[OK ] {label}")
    else:
        print(f"[FAIL] {label}: got {got!r}, want {want!r}")
        FAILED.append(label)


def check_true(label, condition):
    if condition:
        print(f"[OK ] {label}")
    else:
        print(f"[FAIL] {label}")
        FAILED.append(label)


# ---------------------------------------------------------------------------
# 1. Целевые случаи из задачи
# ---------------------------------------------------------------------------
print("\n=== Целевые случаи ===")
check("Vallйe -> Vallée",
      fixtags.repair_text("Vallйe De Larmes"), "Vallée De Larmes")
check("Dьsseldorf -> Düsseldorf",
      fixtags.repair_text("Dьsseldorf, Germany"), "Düsseldorf, Germany")

# ---------------------------------------------------------------------------
# 2. Корректный текст не должен меняться (главная регрессия)
# ---------------------------------------------------------------------------
print("\n=== Корректные названия остаются без изменений ===")
INTACT = [
    "Vallée De Larmes",
    "Düsseldorf, Germany",
    "Песня",
    "Привет, мир",
    "Björk",
    "Motörhead",
    "Sigur Rós",
    "Café del Mar",
    "Ångström",
    "Über alles",
    "Mötley Crüe",
    "Ёлка",
    "Щука",
    "Любэ",
    "Агата Кристи",
    "Тима Белорусских",
    "Хор Турецкого",
    "Zемфира",
    "Bi-2",
    "AC/DC",
    "Track 01",
    "東京",
    "Сергей - Весна (Live)",
    "",
    "   ",
]
for text in INTACT:
    check(f"{text!r} не тронут", fixtags.repair_text(text), text)

# ---------------------------------------------------------------------------
# 3. Восстановление типовых поломок
# ---------------------------------------------------------------------------
print("\n=== Восстановление поломок ===")
check("CP1251 как Latin-1 (кириллица)",
      fixtags.repair_text("Ïåñíÿ"), "Песня")
check("CP1251 как Latin-1 (фраза)",
      fixtags.repair_text("Ïðèâåò, ìèð"), "Привет, мир")
check("UTF-8 как Latin-1",
      fixtags.repair_text("BjÃ¶rk"), "Björk")
check("UTF-8 как CP1252 (кириллица)",
      fixtags.repair_text("ÐŸÑ€Ð¸Ð²ÐµÑ‚"), "Привет")

# ---------------------------------------------------------------------------
# 4. Ремонт по словам: повреждённое слово чинится, целое — нет
# ---------------------------------------------------------------------------
print("\n=== Смешанная строка ===")
check("Одно битое слово в строке",
      fixtags.repair_text("Vallйe De Larmes"), "Vallée De Larmes")
check("Битое + целое",
      fixtags.repair_text("BjÃ¶rk and Песня"), "Björk and Песня")

# ---------------------------------------------------------------------------
# 5. needs_repair
# ---------------------------------------------------------------------------
print("\n=== needs_repair ===")
check_true("Битое -> True", fixtags.needs_repair("Vallйe"))
check_true("Целое -> False", not fixtags.needs_repair("Vallée"))
check_true("Пустое -> False", not fixtags.needs_repair(""))

# ---------------------------------------------------------------------------
# 6. Работа с реальными ID3-тегами
# ---------------------------------------------------------------------------
print("\n=== Работа с ID3-тегами ===")
try:
    from mutagen.id3 import ID3, TALB, TIT2, TPE1
    from mutagen.mp3 import MP3

    with tempfile.TemporaryDirectory() as tmp:
        audio_path = os.path.join(tmp, "track.mp3")

        # минимальный валидный MPEG-поток
        frame = b"\xff\xfb\x90\x64" + b"\x00" * 413
        with open(audio_path, "wb") as handle:
            handle.write(frame * 40)

        tags = ID3()
        tags.add(TIT2(encoding=1, text=["Vallйe De Larmes"]))
        tags.add(TALB(encoding=1, text=["Dьsseldorf, Germany"]))
        tags.add(TPE1(encoding=1, text=["Песня"]))
        tags.save(audio_path, v1=0, v2_version=4)

        loaded = MP3(audio_path)
        check_true("Тестовый файл читается", loaded.tags is not None)

        items = fixtags.scan_directory(tmp, ".mp3")
        check_true("Найдено ровно две правки", len(items) == 2)

        pending = {item.new_text for item in items}
        check_true("Правка названия найдена",
                   "Vallée De Larmes" in pending)
        check_true("Правка альбома найдена",
                   "Düsseldorf, Germany" in pending)
        check_true("Корректный исполнитель не в списке",
                   "Песня" not in pending)

        saved = fixtags.apply_items(items)
        check("Сохранён один файл", saved, 1)

        result = ID3(audio_path)
        check("Title записан верно",
              result.get("TIT2").text, ["Vallée De Larmes"])
        check("Album записан верно",
              result.get("TALB").text, ["Düsseldorf, Germany"])
        check("Artist не изменён",
              result.get("TPE1").text, ["Песня"])
except Exception as exc:  # noqa: BLE001
    print(f"[FAIL] Ошибка при работе с ID3: {exc}")
    FAILED.append("ID3")

# ---------------------------------------------------------------------------
# 7. Совместимость со старым API
# ---------------------------------------------------------------------------
print("\n=== Совместимость API ===")
check("fix_mojibake работает",
      fixtags.fix_mojibake("Ïåñíÿ"), "Песня")
check_true("process_file существует", callable(fixtags.process_file))
check_true("main существует", callable(fixtags.main))
check_true("FRAME_NAMES на месте", "TIT2" in fixtags.FRAME_NAMES)

# ---------------------------------------------------------------------------
print()
if FAILED:
    print(f"ПРОВАЛЕНО: {len(FAILED)}")
    for name in FAILED:
        print(f"  - {name}")
    sys.exit(1)
print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
