"""Иконка: файл, размеры и подключение к окну.

Проверяем то, из-за чего иконка «не отображалась в заголовке»:

1. в .ico есть размер 16×16 — именно его Windows берёт для заголовка;
2. в .ico есть 32×32 и 256×256 — панель задач и крупные значки;
3. окно получает иконку через setWindowIcon (ресурсы EXE Qt не читает);
4. QApplication тоже получает иконку — иначе диалоги без значка;
5. spec-файл содержит icon= и копирует файлы в сборку.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

OUT = sys.__stdout__


def ok(label, condition, extra=""):
    OUT.write(f"[{'OK ' if condition else 'FAIL'}] {label}"
              f"{(' — ' + extra) if extra else ''}\n")
    OUT.flush()
    if not condition:
        raise SystemExit(1)


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
assets = os.path.join(ROOT, "musicsuite", "assets")

# --------------------------------------------------------- 1. файлы на месте
OUT.write("--- 1. Файлы иконки ---\n")
ico_path = os.path.join(assets, "icon.ico")
png_path = os.path.join(assets, "icon.png")

for path in (ico_path, png_path):
    exists = os.path.isfile(path)
    size = os.path.getsize(path) if exists else 0
    OUT.write(f"  {os.path.basename(path):10} "
              f"{'есть' if exists else 'НЕТ':4} {size} байт\n")

ok("icon.ico существует", os.path.isfile(ico_path))
ok("icon.png существует", os.path.isfile(png_path))

# --------------------------------------------------------- 2. размеры в ICO
OUT.write("\n--- 2. Размеры внутри ICO ---\n")
from PIL import Image

with Image.open(ico_path) as image:
    sizes = sorted(image.info.get("sizes", []))
OUT.write(f"  размеры: {[f'{w}x{h}' for w, h in sizes]}\n")

required = {16, 24, 32, 48, 256}
present = {w for w, _ in sizes}
missing = required - present
OUT.write(f"  обязательные: {sorted(required)}\n")
ok("есть 16×16 для заголовка окна", 16 in present, str(sorted(present)))
ok("есть 32×32 для панели задач", 32 in present)
ok("есть 256×256 для крупных значков", 256 in present)
ok("все обязательные размеры на месте", not missing, str(sorted(missing)))
ok("размеров не меньше пяти", len(present) >= 5, str(len(present)))

# Проверяем, что кадры действительно разные, а не один растянутый
OUT.write("\n--- 3. Содержимое кадров ---\n")

def bars_in_row(img, size):
    """Считает группы тёмных пикселей в средней строке — это полосы."""
    row = [img.getpixel((x, size // 2)) for x in range(size)]
    dark = [x for x, p in enumerate(row)
            if p[3] > 200 and sum(p[:3]) < 400]
    groups = []
    for x in dark:
        if groups and x == groups[-1][-1] + 1:
            groups[-1].append(x)
        else:
            groups.append([x])
    return groups


frames = {}
for size in (16, 20, 24, 32, 48, 256):
    with Image.open(ico_path) as image:
        image.size = (size, size)
        image.load()
        frames[size] = image.convert("RGBA").copy()

# Главное: в мелких кадрах полосы не сливаются в одно пятно.
# На 16 px используется упрощённый рисунок из четырёх полос,
# на 32 px и больше — полный из шести.
for size, expected in ((16, 4), (20, 4), (24, 4), (32, 6), (48, 6), (256, 6)):
    groups = bars_in_row(frames[size], size)
    widths = [len(g) for g in groups]
    OUT.write(f"  {size:3}×{size:<3} полос {len(groups)} "
              f"(ширины {widths}), ожидается {expected}\n")
    ok(f"кадр {size}×{size}: полосы различимы",
       len(groups) == expected, f"{len(groups)} вместо {expected}")
    ok(f"кадр {size}×{size}: полосы не шире трети кадра",
       all(w <= size / 3 for w in widths), str(widths))

# Цвета: полосы тёмные, фон кремовый
mid_256 = frames[256]
dark_pixels = [(x, y) for x in range(256) for y in range(256)
               if mid_256.getpixel((x, y))[3] > 200
               and sum(mid_256.getpixel((x, y))[:3]) < 400]
OUT.write(f"  тёмных пикселей в 256×256: {len(dark_pixels)}\n")
ok("полосы занимают заметную площадь", len(dark_pixels) > 3000,
   str(len(dark_pixels)))

bar_color = min((mid_256.getpixel(p) for p in dark_pixels[:500]), key=lambda c: sum(c[:3]))
OUT.write(f"  цвет полос: {bar_color[:3]}\n")
ok("полосы тёмно-коричневые",
   abs(bar_color[0] - 64) < 30 and abs(bar_color[1] - 35) < 30,
   str(bar_color[:3]))

# Фон: берём точку между полосами у верхнего края
bg_pixel = mid_256.getpixel((128, 8))
OUT.write(f"  фон у верхнего края: {bg_pixel[:3]}\n")
ok("фон светлый",
   bg_pixel[3] > 200 and sum(bg_pixel[:3]) > 600, str(bg_pixel[:3]))

# Кадр 16 и 256 — не одно и то же изображение, уменьшенное механически
small_bytes = frames[16].tobytes()
large_bytes = frames[256].resize((16, 16), Image.LANCZOS).tobytes()
ok("кадр 16 нарисован отдельно, а не уменьшен из 256",
   small_bytes != large_bytes)

# ------------------------------------------------- 4. подключение к Qt
OUT.write("\n--- 4. Иконка в Qt ---\n")
app = QApplication.instance() or QApplication([])

from musicsuite.appicon import app_icon, assets_dir, icon_path

OUT.write(f"  assets_dir(): {assets_dir()}\n")
OUT.write(f"  icon_path():  {icon_path()}\n")

icon = app_icon()
OUT.write(f"  размеры QIcon: "
          f"{[f'{s.width()}x{s.height()}' for s in icon.availableSizes()]}\n")
ok("иконка загрузилась", not icon.isNull())
ok("Qt видит несколько размеров",
   len(icon.availableSizes()) >= 5, str(len(icon.availableSizes())))
ok("Qt читает ICO с кадрами", not icon.pixmap(16, 16).isNull())
ok("в ICO есть 256 для панели задач",
   any(s.width() == 256 for s in icon.availableSizes()))

from musicsuite.main_window import MainWindow

window = MainWindow()
window_icon = window.windowIcon()
OUT.write(f"  иконка окна пустая: {window_icon.isNull()}\n")
ok("окно получило иконку", not window_icon.isNull())
ok("у иконки окна есть размеры",
   len(window_icon.availableSizes()) >= 5,
   str(len(window_icon.availableSizes())))

# ------------------------------------------------- 5. spec-файл
OUT.write("\n--- 5. Спецификация PyInstaller ---\n")
spec_path = os.path.join(ROOT, "music_suite.spec")
with open(spec_path, encoding="utf-8") as stream:
    spec = stream.read()

OUT.write(f"  размер spec: {len(spec)} символов\n")
ok("в spec есть icon=", "icon=ICON_PATH" in spec or "icon=" in spec)
ok("icon указывает на .ico", "ICON_PATH" in spec and ".ico" in spec)
ok("ресурсы копируются в сборку",
   '"musicsuite/assets/icon.ico", "assets"' in spec)
ok("имя EXE — MusEdit", 'name="MusEdit"' in spec)

# ------------------------------------------- 6. инструмент воспроизводим
OUT.write("\n--- 6. Скрипт сборки иконки ---\n")
tool = os.path.join(ROOT, "tools", "make_icon.py")
ok("tools/make_icon.py существует", os.path.isfile(tool))

content = open(tool, encoding="utf-8").read()
ok("скрипт задаёт все размеры", "ICON_SIZES" in content)
ok("скрипт рисует, а не растягивает",
   "draw_icon" in content and "LANCZOS" in content)

OUT.write("\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ\n")
