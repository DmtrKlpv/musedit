"""Сборка многоразмерного .ico из исходной картинки.

Почему не растягиваем исходник
------------------------------
Исходник — 32×32 JPEG. Растянутый до 256×256 он превращается в мыло:
края полос размазываются. Поэтому рисунок воспроизводится геометрически
в нужном размере и уменьшается с суперсэмплингом.

Почему для мелких размеров другой рисунок
-----------------------------------------
Шесть полос с промежутками занимают 22 px. В кадр 16×16 они не влезают:
при уменьшении LANCZOS полосы и зазоры сливаются в одно тёмное пятно —
иконка в заголовке окна выглядит грязным квадратом. Поэтому для 16, 20
и 24 px берётся упрощённый рисунок из четырёх полос, а начиная с 32 px —
полный из шести. Это обычная практика в иконках: мелкий размер рисуют
заново, а не уменьшают крупный.

Цвета взяты пипеткой из исходной картинки: полосы #402301 на кремовом
градиенте.

Запуск:
    python tools/make_icon.py
"""

from __future__ import annotations

import os
import struct

from PIL import Image, ImageDraw

BAR_COLOR = (64, 35, 1)                  # #402301 — тёмно-коричневый полос
BG_TOP = (255, 246, 226)                 # светлый край градиента
BG_BOTTOM = (255, 227, 186)              # тёплый низ градиента

# Полный рисунок: шесть полос, как в исходной картинке.
# Высоты — доли от размера холста.
BARS_FULL = (0.125, 0.3125, 0.5625, 0.6875, 0.375, 0.1875)

# Упрощённый рисунок для мелких размеров: четыре полосы, шире и с
# заметными промежутками — иначе в 16 px они сливаются.
BARS_SMALL = (0.25, 0.50, 0.75, 0.40)

CORNER_RADIUS = 0.22      # скругление фона
SUPERSAMPLE = 4           # во сколько раз рисуем крупнее перед уменьшением


def _pattern_for(size: int):
    """Рисунок и геометрия полос под конкретный размер.

    Возвращает (высоты, ширина полосы, промежуток) в долях от холста.
    """
    if size <= 24:
        # Крупные полосы и широкие зазоры: на 16 px иначе всё сливается.
        return BARS_SMALL, 0.105, 0.085
    if size <= 32:
        return BARS_FULL, 0.075, 0.055
    return BARS_FULL, 0.0625, 0.0625


def _background(size: int) -> Image.Image:
    """Скруглённый квадрат с вертикальным градиентом."""
    big = size * SUPERSAMPLE

    gradient = Image.new("RGB", (big, big))
    draw = ImageDraw.Draw(gradient)
    for y in range(big):
        ratio = y / max(1, big - 1)
        color = tuple(
            round(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * ratio)
            for i in range(3)
        )
        draw.line([(0, y), (big, y)], fill=color)

    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, big - 1, big - 1],
        radius=int(big * CORNER_RADIUS),
        fill=255,
    )

    result = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    result.paste(gradient, (0, 0), mask)

    if big != size:
        result = result.resize((size, size), Image.LANCZOS)
    return result


def draw_icon(size: int) -> Image.Image:
    """Рисует иконку ровно этого размера.

    Каждый размер рисуется своим рисунком и уменьшается с суперсэмплингом,
    поэтому полосы остаются раздельными и на 16 px.
    """
    heights, bar_w_ratio, gap_ratio = _pattern_for(size)

    # Рисуем крупнее и уменьшаем: сглаживает торцы полос без размытия
    # промежутков между ними.
    big = size * SUPERSAMPLE
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))

    # Фон рисуем в том же масштабе, чтобы не было двойного ресемплинга
    gradient = Image.new("RGB", (big, big))
    draw_bg = ImageDraw.Draw(gradient)
    for y in range(big):
        ratio = y / max(1, big - 1)
        color = tuple(
            round(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * ratio)
            for i in range(3)
        )
        draw_bg.line([(0, y), (big, y)], fill=color)

    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, big - 1, big - 1],
        radius=int(big * CORNER_RADIUS),
        fill=255,
    )
    image.paste(gradient, (0, 0), mask)

    draw = ImageDraw.Draw(image)
    count = len(heights)
    bar_w = bar_w_ratio * big
    gap = gap_ratio * big

    total = count * bar_w + (count - 1) * gap
    left = (big - total) / 2

    for index, height_ratio in enumerate(heights):
        bar_h = height_ratio * big
        x0 = left + index * (bar_w + gap)
        y0 = (big - bar_h) / 2
        draw.rounded_rectangle(
            [x0, y0, x0 + bar_w, y0 + bar_h],
            radius=bar_w / 2,
            fill=BAR_COLOR,
        )

    return image.resize((size, size), Image.LANCZOS)


# Размеры, которые запрашивает Windows:
#   16  — значок в заголовке окна, компактный список
#   20  — панель задач при масштабе 125%
#   24  — панель задач при 150%
#   32  — панель задач, Alt+Tab
#   40  — 125% от 32
#   48  — проводник, крупные значки
#   64  — плитка в меню «Пуск»
#   128 — крупный просмотр в проводнике
#   256 — плитка и предпросмотр; обязателен для Vista+
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def _dib_frame(image: Image.Image) -> bytes:
    """Кадр ICO в формате DIB: BITMAPINFOHEADER + BGRA + маска прозрачности.

    Pillow при сохранении ICO с append_images масштабирует один кадр на все
    размеры — мелкие иконки получались размытыми. Поэтому контейнер
    собирается вручную: каждый размер остаётся тем, что нарисован.

    DIB выбран вместо PNG внутри ICO: PNG в контейнере официально
    поддержан с Vista, но старые просмотрщики и некоторые оболочки его
    не читают. DIB понимают все версии Windows.
    """
    width, height = image.size
    rgba = image.convert("RGBA")

    # Пиксели: BGRA, снизу вверх
    pixels = bytearray()
    for y in range(height - 1, -1, -1):
        for x in range(width):
            red, green, blue, alpha = rgba.getpixel((x, y))
            pixels += bytes((blue, green, red, alpha))

    # AND-маска: 1 бит на пиксель, строки выровнены по 4 байта.
    # При 32-битном цвете она не используется для прозрачности (её задаёт
    # альфа-канал), но обязана присутствовать в структуре.
    row_bytes = ((width + 31) // 32) * 4
    mask = bytearray()
    for y in range(height - 1, -1, -1):
        bits = bytearray(row_bytes)
        for x in range(width):
            if rgba.getpixel((x, y))[3] == 0:
                bits[x // 8] |= 1 << (7 - (x % 8))
        mask += bits

    header = struct.pack(
        "<IiiHHIIiiII",
        40,              # размер заголовка
        width,
        height * 2,      # в ICO высота учитывает и цвет, и маску
        1,               # плоскостей
        32,              # бит на пиксель
        0,               # сжатие BI_RGB
        len(pixels) + len(mask),
        0, 0, 0, 0,
    )
    return header + bytes(pixels) + bytes(mask)


def build_ico(path: str, sizes=ICON_SIZES) -> str:
    """Собирает .ico вручную: каждый размер — свой рисунок."""
    frames = [draw_icon(size) for size in sizes]
    payloads = [_dib_frame(frame) for frame in frames]

    # ICONDIR: reserved, type=1 (иконка), количество кадров
    directory = struct.pack("<HHH", 0, 1, len(frames))

    offset = 6 + 16 * len(frames)
    entries = b""
    for size, payload in zip(sizes, payloads):
        entries += struct.pack(
            "<BBBBHHII",
            size if size < 256 else 0,   # 0 означает 256
            size if size < 256 else 0,
            0,                            # цветов в палитре
            0,                            # зарезервировано
            1,                            # плоскостей
            32,                           # бит на пиксель
            len(payload),
            offset,
        )
        offset += len(payload)

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as stream:
        stream.write(directory + entries + b"".join(payloads))
    return path


def build_png(path: str, size: int = 256) -> str:
    """PNG для Qt: надёжнее читается на Linux и macOS."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    draw_icon(size).save(path, format="PNG")
    return path


if __name__ == "__main__":
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assets = os.path.join(root, "musicsuite", "assets")

    ico = build_ico(os.path.join(assets, "icon.ico"))
    png = build_png(os.path.join(assets, "icon.png"))

    print(f"ICO: {ico} ({os.path.getsize(ico)} байт, "
          f"размеры {', '.join(map(str, ICON_SIZES))})")
    print(f"PNG: {png} ({os.path.getsize(png)} байт)")
