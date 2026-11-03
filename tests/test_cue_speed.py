"""Конвертация CUE не должна «висеть» на длинных альбомах.

Проблема, которую фиксирует тест
--------------------------------
Позиция -ss стояла после -i. В этом режиме FFmpeg декодирует файл
с самого начала и выбрасывает всё до точки разреза, поэтому трек в конце
часового рипа кодировался в разы дольше первого. Пользователь видел
полосу на 87%, которая почти не двигалась, и это выглядело как зависание.

Что проверяем
-------------
1. -ss идёт ДО -i — иначе позиционирование медленное;
2. длина куска задаётся через -t, а не -to (при -ss перед -i метки
   времени начинаются с нуля);
3. есть -nostdin — иначе GUI-процесс может ждать ввода;
4. альбом обрабатывается быстрее реального времени;
5. все треки собираются с правильной длительностью;
6. прогресс обновляется внутри трека, а не только между ними.
"""

import argparse
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from musicsuite.engines import cue2mp3

OUT = sys.__stdout__


def ok(label, condition, extra=""):
    OUT.write(f"[{'OK ' if condition else 'FAIL'}] {label}"
              f"{(' — ' + extra) if extra else ''}\n")
    OUT.flush()
    if not condition:
        raise SystemExit(1)


import imageio_ffmpeg

bindir = tempfile.mkdtemp(prefix="ffbin_")
link = os.path.join(bindir, "ffmpeg")
os.symlink(imageio_ffmpeg.get_ffmpeg_exe(), link)
old_path = os.environ.get("PATH", "")
os.environ["PATH"] = bindir + os.pathsep + old_path


def ffmpeg(*args):
    subprocess.run([link, "-hide_banner", "-loglevel", "error", *args],
                   check=True, capture_output=True)


# ------------------------------------------------- 1. порядок аргументов
OUT.write("--- 1. Аргументы FFmpeg ---\n")

captured = []


class FakeProcess:
    stdout = iter([
        "out_time_us=30000000\n",
        "out_time_us=60000000\n",
        "progress=end\n",
    ])

    def wait(self):
        return 0


def fake_popen(cmd, **kwargs):
    captured.append(list(cmd))
    return FakeProcess()


class Recorder:
    """Минимальный прогресс: запоминает все значения."""
    def __init__(self):
        self.values = []
        self.total = 0
        self.done = 0

    def start(self, total=0, text=""):
        self.total = total

    def set_total(self, total):
        self.total = total

    def advance(self, step=1, text=""):
        self.done += step

    def update(self, done, total=None, text=""):
        self.values.append(done)
        self.done = done
        if total is not None:
            self.total = total

    def message(self, text=""):
        pass

    def detail(self, text=""):
        pass

    def finish(self, text=""):
        pass


recorder = Recorder()
real_popen = cue2mp3.popen
cue2mp3.popen = fake_popen
try:
    encoded_ok, error = cue2mp3._encode_track(
        "ffmpeg", "/in/album.flac", "/out/track.flac",
        start_sec=120.0, end_sec=240.0,
        enc_args=["-c:a", "flac"], track_seconds=120.0,
        report=recorder, index=2, total_tracks=10,
    )
finally:
    cue2mp3.popen = real_popen

# FFmpeg прислал 30 с и 60 с из 120 — значит прогресс должен пройти
# через 1.25 и 1.5, то есть сдвинуться ВНУТРИ второго трека.
OUT.write(f"  прогресс внутри трека: {recorder.values}\n")

cmd = captured[0] if captured else []
OUT.write(f"  команда: {' '.join(str(c) for c in cmd)}\n")

ok("команда собрана", bool(cmd))
ok("есть -nostdin", "-nostdin" in cmd)
ok("успех без ошибок", encoded_ok and not error, error)

ss_index = cmd.index("-ss") if "-ss" in cmd else -1
input_index = cmd.index("-i") if "-i" in cmd else -1
OUT.write(f"  позиция -ss: {ss_index}, позиция -i: {input_index}\n")
ok("есть -ss", ss_index >= 0)
ok("есть -i", input_index >= 0)
ok("-ss стоит ДО -i (быстрое позиционирование)",
   ss_index < input_index, f"{ss_index} vs {input_index}")
ok("кусок задаётся через -t", "-t" in cmd)
ok("абсолютного -to нет", "-to" not in cmd)
if "-t" in cmd:
    ok("длительность куска = 120 с", cmd[cmd.index("-t") + 1] == "120.000",
       cmd[cmd.index("-t") + 1])
ok("прогресс идёт через pipe", "pipe:1" in cmd)
ok("-nostats отключает служебный вывод", "-nostats" in cmd)

fractional = [v for v in recorder.values if v != int(v)]
ok("прогресс движется внутри трека", bool(fractional),
   f"значения {recorder.values}")
if len(recorder.values) >= 2:
    ok("значения растут", recorder.values == sorted(recorder.values),
       str(recorder.values))
    ok("первое значение — 30 с из 120 (1.25 трека)",
       abs(recorder.values[0] - 1.25) < 0.01, str(recorder.values[0]))
    ok("второе — 60 с из 120 (1.5 трека)",
       abs(recorder.values[1] - 1.5) < 0.01, str(recorder.values[1]))

# ---------------------------------------- 2. тайминг на длинном альбоме
OUT.write("\n--- 2. Скорость на 20-минутном альбоме ---\n")
tmp = tempfile.mkdtemp(prefix="speed_")
source = os.path.join(tmp, "album.flac")

# Розовый шум сжимается плохо — близко к реальному рипу с винила.
ffmpeg("-f", "lavfi", "-i", "anoisesrc=d=1200:c=pink:r=44100:a=0.5",
       "-ac", "2", "-c:a", "flac", source)

size_mb = os.path.getsize(source) / (1024 * 1024)
OUT.write(f"  исходник: {size_mb:.0f} МБ, 20 минут\n")

cue_path = os.path.join(tmp, "album.cue")
lines = ['PERFORMER "Artist"', 'TITLE "Album"', 'FILE "album.flac" WAVE']
for index in range(10):
    lines += [f'  TRACK {index + 1:02d} AUDIO',
              f'    TITLE "Track {index + 1}"',
              f'    INDEX 01 {index * 2:02d}:00:00']
with open(cue_path, "w", encoding="utf-8") as stream:
    stream.write("\n".join(lines) + "\n")

marks = []


class Collector:
    total = 0
    done = 0

    def start(self, total=0, text=""):
        self.total, self.done = total, 0

    def set_total(self, total):
        self.total = total

    def advance(self, step=1, text=""):
        self.done += step

    def update(self, done, total=None, text=""):
        self.done = done
        if total is not None:
            self.total = total
        marks.append(done)

    def message(self, text=""):
        pass

    def detail(self, text=""):
        pass

    def finish(self, text=""):
        pass


started = time.time()
result = cue2mp3.main(
    argparse.Namespace(input=cue_path, output=os.path.join(tmp, "out"),
                       quality=cue2mp3.DEFAULT_QUALITY,
                       format="FLAC — без потерь", cover="", debug=False),
    progress=Collector(),
)
elapsed = time.time() - started

OUT.write(f"  всего: {elapsed:.1f} с на {result['tracks']} треков\n")
OUT.write(f"  сбоев: {result['failed']}\n")

ok("все треки собраны", result["failed"] == 0, str(result["failed"]))
ok("десять треков", result["tracks"] == 10, str(result["tracks"]))
ok("быстрее реального времени в 5+ раз",
   elapsed < 1200 / 5, f"{elapsed:.1f} с")

# ------------------------------------------- 3. длительности не съехали
OUT.write("\n--- 3. Границы треков ---\n")
from mutagen.flac import FLAC

files = sorted(os.listdir(os.path.join(tmp, "out")))
OUT.write(f"  файлов: {len(files)}\n")
ok("десять файлов", len(files) == 10, str(len(files)))

deviations = []
for name in files:
    length = FLAC(os.path.join(tmp, "out", name)).info.length
    if abs(length - 120) > 0.05:
        deviations.append((name, length))

OUT.write(f"  отклонений от 120 с: {len(deviations)}\n")
for name, length in deviations[:5]:
    OUT.write(f"    {name}: {length:.3f}\n")
ok("все треки по 120 с", not deviations, str(deviations[:2]))

# ------------------------------------------- 4. прогресс внутри трека
OUT.write("\n--- 4. Прогресс ---\n")
OUT.write(f"  обновлений: {len(marks)}\n")
ok("прогресс обновлялся", len(marks) > 0, str(len(marks)))
ok("прогресс монотонно растёт",
   marks == sorted(marks), "есть откаты назад")
ok("прогресс дошёл до конца",
   abs(marks[-1] - 10) < 0.01, str(marks[-1]))
# Кодирование занимает доли секунды, поэтому FFmpeg присылает только
# финальное значение времени — промежуточные шаги разобраны в блоке 1
# на управляемом процессе.
OUT.write("  (быстрый энкод даёт только финальное обновление — это норма)\n")

os.environ["PATH"] = old_path
OUT.write("\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ\n")
