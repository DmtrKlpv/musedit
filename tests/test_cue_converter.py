"""Конвертер CUE → MP3: четыре изменения.

1. Селектор качества: понятные подписи VBR V0…V8 и CBR 320…96
   вместо «v0» и «320».
2. Поле обложки: ссылка на картинку встраивается в теги.
3. Консоль: каждая строка появляется один раз, а не дважды.
4. Заголовок окна содержит версию из version.py.
"""

import os
import struct
import sys
import tempfile
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from musicsuite.engines import cue2mp3
from musicsuite.version import APP_NAME, APP_VERSION, APP_TITLE, ORGANIZATION

OUT = sys.__stdout__


def ok(label, condition, extra=""):
    OUT.write(f"[{'OK ' if condition else 'FAIL'}] {label}"
              f"{(' — ' + extra) if extra else ''}\n")
    OUT.flush()
    if not condition:
        raise SystemExit(1)


def pump(ms=80):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def make_png(path, size=8, color=(200, 60, 60)):
    """Настоящий PNG — чтобы проверить определение MIME."""
    def chunk(tag, data):
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xffffffff))

    raw = b"".join(b"\x00" + bytes(color) * size for _ in range(size))
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as stream:
        stream.write(png)
    return path


# ------------------------------------------------------------------ 1. качество
OUT.write("--- 1. Пресеты качества ---\n")
presets = list(cue2mp3.QUALITY_PRESETS)
OUT.write(f"  всего пресетов: {len(presets)}\n")
for name in presets:
    OUT.write(f"    {name:40} -> {cue2mp3.encode_args(name)}\n")

ok("пресетов не меньше десяти", len(presets) >= 10, str(len(presets)))
ok("нет голых «v0» и «320» в списке",
   "v0" not in presets and "320" not in presets)
ok("подписи содержат VBR", any("VBR" in p for p in presets))
ok("подписи содержат CBR", any("CBR" in p for p in presets))
ok("есть максимальное качество VBR",
   cue2mp3.encode_args("VBR V0 — максимум, ~245 kbps")
   == ["-c:a", "libmp3lame", "-q:a", "0"])
ok("есть максимальное качество CBR",
   cue2mp3.encode_args("CBR 320 kbps — максимум")
   == ["-c:a", "libmp3lame", "-b:a", "320k"])
ok("есть низкое качество",
   cue2mp3.encode_args("CBR 96 kbps — минимальное")
   == ["-c:a", "libmp3lame", "-b:a", "96k"])

# Совместимость со старыми значениями
ok("старое «v0» работает",
   cue2mp3.encode_args("v0") == ["-c:a", "libmp3lame", "-q:a", "0"])
ok("старое «320» работает",
   cue2mp3.encode_args("320") == ["-c:a", "libmp3lame", "-b:a", "320k"])
ok("неизвестное значение не падает",
   cue2mp3.encode_args("чепуха") == cue2mp3.encode_args(cue2mp3.DEFAULT_QUALITY))

# VBR и CBR чередуются по возрастанию качества
vbr = [p for p in presets if p.startswith("VBR")]
cbr = [p for p in presets if p.startswith("CBR")]
ok("VBR-пресетов восемь", len(vbr) == 8, str(len(vbr)))
ok("CBR-пресетов семь", len(cbr) == 7, str(len(cbr)))

# ------------------------------------------------------------------ 2. обложка
OUT.write("\n--- 2. Обложка с диска ---\n")
tmp = tempfile.mkdtemp(prefix="cover_")
cover_path = make_png(os.path.join(tmp, "cover.png"))
OUT.write(f"  тестовая картинка: {os.path.getsize(cover_path)} байт\n")

# Обложка читается с диска, а не скачивается по ссылке.
data, mime = cue2mp3.load_cover_file(cover_path)
OUT.write(f"  прочитано: {len(data) if data else 0} байт, mime={mime}\n")
ok("обложка прочитана с диска", data is not None)
ok("MIME определён как PNG", mime == "image/png", str(mime))
ok("размер совпадает", len(data) == os.path.getsize(cover_path))

# Ссылка вместо файла должна быть отклонена: конвертация
# не зависит от сети и не делает запросов наружу.
link_data, _ = cue2mp3.load_cover_file("https://example.com/cover.jpg")
ok("ссылка отклонена", link_data is None)

empty, _ = cue2mp3.load_cover_file("")
ok("пустая строка ничего не читает", empty is None)

missing, _ = cue2mp3.load_cover_file(os.path.join(tmp, "нет.jpg"))
ok("отсутствующий файл отклонён", missing is None)

fake = os.path.join(tmp, "fake.jpg")
with open(fake, "wb") as stream:
    stream.write(b"<html>this is not an image</html>")
not_image, _ = cue2mp3.load_cover_file(fake)
ok("файл с неверным содержимым отклонён", not_image is None)

folder, _ = cue2mp3.load_cover_file(tmp)
ok("папка вместо файла отклонена", folder is None)

# ------------------------------------------------------------------ 3. консоль
OUT.write("\n--- 3. Консоль: без дублей ---\n")
app = QApplication.instance() or QApplication([])
from musicsuite.console import ConsoleView

real_stdout = sys.__stdout__
console = ConsoleView()
console.set_show_all(True)     # самый строгий режим: видно все строки
console.install()

print("[INFO] старт конвертации")
for index in range(1, 4):
    print(f"{index:02d}/3: Test Artist - Track {index}")
print("[DONE] готово")
pump(400)

sys.stdout = real_stdout
field = console.editor.toPlainText()
OUT.write("  поле консоли:\n")
for line in field.splitlines():
    OUT.write(f"    {line}\n")

for index in range(1, 4):
    count = field.count(f"Track {index}")
    OUT.write(f"  Track {index}: {count}\n")
    ok(f"строка Track {index} ровно один раз", count == 1, str(count))

ok("INFO один раз", field.count("старт конвертации") == 1)
ok("DONE один раз", field.count("[DONE]") == 1)
ok("порядок строк сохранён",
   field.index("[INFO]") < field.index("Track 1") < field.index("[DONE]"))

# ------------------------------------------------------------------ 4. заголовок
OUT.write("\n--- 4. Название и версия ---\n")
OUT.write(f"  APP_NAME={APP_NAME} APP_VERSION={APP_VERSION}\n")
OUT.write(f"  APP_TITLE={APP_TITLE}\n")
OUT.write(f"  ORGANIZATION={ORGANIZATION}\n")

ok("имя приложения MusEdit", APP_NAME == "MusEdit")
ok("версия из трёх чисел",
   len(APP_VERSION.split(".")) == 3, APP_VERSION)
ok("заголовок = имя + версия",
   APP_TITLE == f"{APP_NAME} {APP_VERSION}", APP_TITLE)
ok("организация совпадает", ORGANIZATION == "Dmkr Klpv, 2026"
   or ORGANIZATION == "Dmtr Klpv, 2026", ORGANIZATION)

from musicsuite.main_window import MainWindow

window = MainWindow()
OUT.write(f"  windowTitle(): {window.windowTitle()!r}\n")
ok("заголовок окна содержит версию",
   APP_VERSION in window.windowTitle(), window.windowTitle())

# поле обложки во вкладке
tab = window.cue_tab
ok("поле обложки есть", hasattr(tab, "cover_field"))
ok("поле обложки — выбор файла, а не ссылки",
   hasattr(tab.cover_field, "file_btn"))
ok("в подсказке упомянут файл",
   "файл" in tab.cover_field.edit.placeholderText().lower())
ok("селектор содержит 15 пресетов", tab.quality_combo.count() == 15,
   str(tab.quality_combo.count()))

OUT.write("\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ\n")
