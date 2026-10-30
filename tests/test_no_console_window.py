"""FFmpeg запускается без всплывающего консольного окна.

На Windows каждый вызов subprocess открывал чёрное окно командной строки —
на каждый трек альбома. Здесь проверяем, что:

1. хелпер subproc добавляет CREATE_NO_WINDOW только на Windows;
2. конвертация CUE по-прежнему работает и создаёт файлы;
3. вывод FFmpeg не попадает в консоль приложения.
"""

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from musicsuite import subproc

OUT = sys.__stdout__


def ok(label, condition, extra=""):
    OUT.write(f"[{'OK ' if condition else 'FAIL'}] {label}"
              f"{(' — ' + extra) if extra else ''}\n")
    OUT.flush()
    if not condition:
        raise SystemExit(1)


# ------------------------------------------------------- 1. флаги платформы
OUT.write("--- 1. Флаги запуска процессов ---\n")
OUT.write(f"  платформа: {sys.platform}\n")
flags = subproc.popen_kwargs()
OUT.write(f"  kwargs: {flags}\n")

if sys.platform == "win32":
    ok("на Windows задан creationflags",
       flags.get("creationflags") == 0x08000000, str(flags))
    ok("это именно CREATE_NO_WINDOW",
       flags.get("creationflags", 0) & 0x08000000 == 0x08000000)
else:
    ok("вне Windows флагов нет", flags == {}, str(flags))

# Хелпер не должен терять пользовательские аргументы
captured = {}


def fake_run(cmd, **kwargs):
    captured.update(kwargs)

    class Result:
        returncode = 0
        stdout = b""
        stderr = b""

    return Result()


real_run = subproc.subprocess.run
subproc.subprocess.run = fake_run
try:
    subproc.run(["echo", "test"], check=True, capture_output=True)
finally:
    subproc.subprocess.run = real_run

OUT.write(f"  переданные аргументы: {sorted(captured)}\n")
ok("check проброшен", captured.get("check") is True)
ok("capture_output проброшен", captured.get("capture_output") is True)
if sys.platform == "win32":
    ok("флаг скрытия окна проброшен",
       captured.get("creationflags") == 0x08000000)

# ------------------------------------------------------- 2. конвертация
OUT.write("\n--- 2. Конвертация CUE ---\n")

import imageio_ffmpeg

bindir = tempfile.mkdtemp()
link = os.path.join(bindir, "ffmpeg")
os.symlink(imageio_ffmpeg.get_ffmpeg_exe(), link)
old_path = os.environ.get("PATH", "")
os.environ["PATH"] = bindir + os.pathsep + old_path

tmp = tempfile.mkdtemp(prefix="proc_")
flac = os.path.join(tmp, "album.flac")
subprocess.run(
    [link, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
     "-i", "sine=frequency=440:duration=6", "-c:a", "flac", flac, "-y"],
    check=True,
)

cue = os.path.join(tmp, "album.cue")
with open(cue, "w", encoding="utf-8") as stream:
    stream.write('PERFORMER "Test Artist"\n'
                 'TITLE "Test Album"\n'
                 'FILE "album.flac" WAVE\n'
                 '  TRACK 01 AUDIO\n'
                 '    TITLE "One"\n'
                 '    INDEX 01 00:00:00\n'
                 '  TRACK 02 AUDIO\n'
                 '    TITLE "Two"\n'
                 '    INDEX 01 00:02:00\n'
                 '  TRACK 03 AUDIO\n'
                 '    TITLE "Three"\n'
                 '    INDEX 01 00:04:00\n')

import argparse
import io

from musicsuite.engines import cue2mp3

out_dir = os.path.join(tmp, "out")
args = argparse.Namespace(input=cue, output=out_dir,
                          quality=cue2mp3.DEFAULT_QUALITY,
                          cover="", debug=False)

buffer = io.StringIO()
real_stdout = sys.stdout
sys.stdout = buffer
try:
    result = cue2mp3.main(args)
finally:
    sys.stdout = real_stdout

log = buffer.getvalue()
OUT.write(f"  результат: {result}\n")
OUT.write("  лог конвертации:\n")
for line in log.strip().splitlines():
    OUT.write(f"    {line}\n")

ok("конвертация вернула результат", isinstance(result, dict))
ok("ни одного сбоя", result.get("failed") == 0, str(result.get("failed")))
ok("создано три трека", result.get("tracks") == 3,
   str(result.get("tracks")))

files = sorted(os.listdir(out_dir))
OUT.write(f"  файлы: {files}\n")
ok("все три файла на месте", len(files) == 3, str(len(files)))
ok("файлы не пустые",
   all(os.path.getsize(os.path.join(out_dir, f)) > 1000 for f in files))

# ------------------------------------------------ 3. вывод FFmpeg подавлен
OUT.write("\n--- 3. Вывод FFmpeg не попадает в лог ---\n")

# FFmpeg с -loglevel error молчит при успехе; проверяем, что в лог
# не просочились его служебные строки вида "frame=" или "size=".
noise = [line for line in log.splitlines()
         if any(marker in line for marker in ("frame=", "size=", "bitrate=",
                                              "Stream mapping", "Press [q]"))]
OUT.write(f"  служебных строк FFmpeg в логе: {len(noise)}\n")
for line in noise[:5]:
    OUT.write(f"    {line}\n")
ok("служебный вывод FFmpeg не просочился", not noise, str(noise[:2]))

# Каждый трек упомянут ровно один раз
for index in range(1, 4):
    marker = f"0{index}/3"
    count = log.count(marker)
    OUT.write(f"  «{marker}»: {count}\n")
    ok(f"трек {index} в логе один раз", count == 1, str(count))

os.environ["PATH"] = old_path

OUT.write("\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ\n")
