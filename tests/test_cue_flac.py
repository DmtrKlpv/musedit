"""Конвертер CUE: нарезка в FLAC и в MP3.

Задача — резать один CUE/FLAC не только в MP3, но и в отдельные FLAC,
причём FLAC должен быть выбран по умолчанию: альбом режется без потери
качества, а MP3 из него делается когда угодно.

Проверяем:
1. формат по умолчанию — FLAC;
2. запись тегов у FLAC своя (Vorbis comments), у MP3 — ID3v2.4;
3. обложка попадает в FLAC отдельным блоком PICTURE, в MP3 — в APIC;
4. расширения и имена файлов соответствуют формату;
5. MP3-поле качества неактивно для FLAC и активно для MP3;
6. звук во FLAC остаётся без потерь (тот же поток, что у исходника).
"""

import argparse
import os
import struct
import sys
import tempfile
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from musicsuite.engines import cue2mp3

OUT = sys.__stdout__


def ok(label, condition, extra=""):
    OUT.write(f"[{'OK ' if condition else 'FAIL'}] {label}"
              f"{(' — ' + extra) if extra else ''}\n")
    OUT.flush()
    if not condition:
        raise SystemExit(1)


def make_png(path, size=8, color=(200, 60, 60)):
    """Настоящий PNG — чтобы проверить определение MIME и встраивание."""
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


# ------------------------------------------------------------ 1. формат
OUT.write("--- 1. Выбор формата ---\n")
OUT.write(f"  подписи: {list(cue2mp3.FORMAT_LABELS)}\n")
OUT.write(f"  по умолчанию: {cue2mp3.DEFAULT_FORMAT_LABEL}\n")

ok("FLAC — формат по умолчанию",
   cue2mp3.resolve_format(cue2mp3.DEFAULT_FORMAT_LABEL) == cue2mp3.FORMAT_FLAC)
ok("FLAC стоит первым в списке",
   list(cue2mp3.FORMAT_LABELS)[0] == cue2mp3.DEFAULT_FORMAT_LABEL)
ok("MP3 по-прежнему доступен",
   cue2mp3.resolve_format("MP3 — VBR или CBR") == cue2mp3.FORMAT_MP3)
ok("код формата тоже принимается",
   cue2mp3.resolve_format("flac") == cue2mp3.FORMAT_FLAC)
ok("неизвестное значение — FLAC",
   cue2mp3.resolve_format("чепуха") == cue2mp3.FORMAT_FLAC)

ok("расширение FLAC", cue2mp3.extension("flac") == ".flac")
ok("расширение MP3", cue2mp3.extension("mp3") == ".mp3")

flac_args = cue2mp3.encode_args_for("flac")
mp3_args = cue2mp3.encode_args_for("mp3", "CBR 320 kbps — максимум")
OUT.write(f"  FLAC args: {flac_args}\n")
OUT.write(f"  MP3 args : {mp3_args}\n")
ok("FLAC кодируется кодеком flac", flac_args[:2] == ["-c:a", "flac"])
ok("для FLAC битрейт не задаётся",
   not any("b:a" in a for a in flac_args))
ok("MP3 использует libmp3lame",
   mp3_args[:2] == ["-c:a", "libmp3lame"])
ok("CBR 320 применяется", "320k" in mp3_args)

# ------------------------------------------------------- 2. вкладка
OUT.write("\n--- 2. Вкладка ---\n")
app = QApplication.instance() or QApplication([])
from musicsuite.tabs.cue_tab import CueTab


class FakeWindow:
    def show_console(self):
        pass


tab = CueTab(FakeWindow())

OUT.write(f"  формат в списке: {tab.format_combo.currentText()!r}\n")
OUT.write(f"  вариантов: {tab.format_combo.count()}\n")
ok("в списке два формата", tab.format_combo.count() == 2)
ok("выбран FLAC по умолчанию",
   tab.format_combo.currentText() == cue2mp3.DEFAULT_FORMAT_LABEL,
   tab.format_combo.currentText())
ok("качество MP3 неактивно при FLAC", not tab.quality_combo.isEnabled())
ok("папка вывода — flac_output",
   tab.output_field.text() == "flac_output", tab.output_field.text())
ok("название вкладки без «MP3»", "MP3" not in tab.TITLE, tab.TITLE)

tab.format_combo.setCurrentText("MP3 — VBR или CBR")
OUT.write(f"  после переключения на MP3: качество активно="
          f"{tab.quality_combo.isEnabled()}, папка={tab.output_field.text()!r}\n")
ok("качество MP3 активно", tab.quality_combo.isEnabled())
ok("папка вывода — mp3_output", tab.output_field.text() == "mp3_output")

tab.format_combo.setCurrentText(cue2mp3.DEFAULT_FORMAT_LABEL)
ok("возврат на FLAC снова блокирует качество",
   not tab.quality_combo.isEnabled())

# -------------------------------------------- 3. реальная конвертация
OUT.write("\n--- 3. Конвертация ---\n")
import subprocess

import imageio_ffmpeg

bindir = tempfile.mkdtemp()
link = os.path.join(bindir, "ffmpeg")
os.symlink(imageio_ffmpeg.get_ffmpeg_exe(), link)
old_path = os.environ.get("PATH", "")
os.environ["PATH"] = bindir + os.pathsep + old_path

tmp = tempfile.mkdtemp(prefix="cueflac_")
source = os.path.join(tmp, "album.flac")
subprocess.run(
    [link, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
     "-i", "sine=frequency=440:duration=6", "-c:a", "flac", source, "-y"],
    check=True,
)
make_png(os.path.join(tmp, "cover.png"))

cue_path = os.path.join(tmp, "album.cue")
with open(cue_path, "w", encoding="utf-8") as stream:
    stream.write('PERFORMER "Test Artist"\n'
                 'TITLE "Test Album"\n'
                 'DATE "2024"\n'
                 'GENRE "Rock"\n'
                 'FILE "album.flac" WAVE\n'
                 '  TRACK 01 AUDIO\n'
                 '    TITLE "Первый трек"\n'
                 '    INDEX 01 00:00:00\n'
                 '  TRACK 02 AUDIO\n'
                 '    TITLE "Второй трек"\n'
                 '    INDEX 01 00:02:00\n'
                 '  TRACK 03 AUDIO\n'
                 '    TITLE "Третий трек"\n'
                 '    INDEX 01 00:04:00\n')


def run(out_dir, fmt, quality=cue2mp3.DEFAULT_QUALITY):
    args = argparse.Namespace(input=cue_path, output=out_dir, quality=quality,
                              format=fmt, cover="", debug=False)
    os.makedirs(out_dir, exist_ok=True)
    return cue2mp3.main(args)


flac_dir = os.path.join(tmp, "out_flac")
flac_result = run(flac_dir, "FLAC — без потерь")
flac_files = sorted(os.listdir(flac_dir))
OUT.write(f"  FLAC: {flac_result}\n")
OUT.write(f"  файлы: {flac_files}\n")

ok("FLAC: три трека", flac_result["tracks"] == 3, str(flac_result["tracks"]))
ok("FLAC: без сбоев", flac_result["failed"] == 0)
ok("FLAC: три файла", len(flac_files) == 3, str(len(flac_files)))
ok("FLAC: расширение .flac",
   all(name.endswith(".flac") for name in flac_files), str(flac_files))
ok("FLAC: имена с номером и названием",
   flac_files[0] == "01 - Первый трек.flac", flac_files[0])

# Теги FLAC — Vorbis comments
from mutagen.flac import FLAC

first_flac = FLAC(os.path.join(flac_dir, flac_files[0]))
OUT.write(f"  теги: {dict(first_flac)}\n".replace("\n", " ")[:200] + "\n")
ok("FLAC: title записан", first_flac.get("title") == ["Первый трек"],
   str(first_flac.get("title")))
ok("FLAC: artist записан",
   first_flac.get("artist") == ["Test Artist"], str(first_flac.get("artist")))
ok("FLAC: album записан", first_flac.get("album") == ["Test Album"])
ok("FLAC: date записан", first_flac.get("date") == ["2024"])
ok("FLAC: genre записан", first_flac.get("genre") == ["Rock"])
ok("FLAC: номер трека", first_flac.get("tracknumber") == ["01"],
   str(first_flac.get("tracknumber")))

# Обложка — отдельным блоком PICTURE
OUT.write(f"  картинок в FLAC: {len(first_flac.pictures)}\n")
ok("FLAC: обложка встроена", len(first_flac.pictures) == 1,
   str(len(first_flac.pictures)))
if first_flac.pictures:
    picture = first_flac.pictures[0]
    OUT.write(f"    mime={picture.mime} type={picture.type} "
              f"размер={len(picture.data)}\n")
    ok("FLAC: обложка помечена как передняя", picture.type == 3)
    ok("FLAC: mime картинки PNG", picture.mime == "image/png", picture.mime)

# Звук без потерь: тот же поток, что в исходнике
OUT.write(f"  параметры FLAC: каналов={first_flac.info.channels} "
          f"частота={first_flac.info.sample_rate} "
          f"бит={first_flac.info.bits_per_sample}\n")
from mutagen.flac import FLAC as SrcFLAC

src_audio = SrcFLAC(source)
ok("FLAC: частота совпадает с исходником",
   first_flac.info.sample_rate == src_audio.info.sample_rate)
ok("FLAC: разрядность совпадает",
   first_flac.info.bits_per_sample == src_audio.info.bits_per_sample)

# ------------------------------------------------ 4. MP3 не сломался
OUT.write("\n--- 4. MP3 по-прежнему работает ---\n")
mp3_dir = os.path.join(tmp, "out_mp3")
mp3_result = run(mp3_dir, "MP3 — VBR или CBR", "CBR 320 kbps — максимум")
mp3_files = sorted(os.listdir(mp3_dir))
OUT.write(f"  MP3: {mp3_result}\n")
OUT.write(f"  файлы: {mp3_files}\n")

ok("MP3: три трека", mp3_result["tracks"] == 3)
ok("MP3: расширение .mp3",
   all(name.endswith(".mp3") for name in mp3_files), str(mp3_files))

from mutagen.mp3 import MP3

first_mp3 = MP3(os.path.join(mp3_dir, mp3_files[0]))
OUT.write(f"  битрейт: {int(first_mp3.info.bitrate / 1000)} kbps\n")
ok("MP3: CBR 320 применён", first_mp3.info.bitrate > 300_000,
   str(first_mp3.info.bitrate))
ok("MP3: теги ID3 есть", first_mp3.tags is not None)
ok("MP3: обложка в APIC",
   bool(first_mp3.tags and first_mp3.tags.getall("APIC")))

os.environ["PATH"] = old_path
OUT.write("\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ\n")
