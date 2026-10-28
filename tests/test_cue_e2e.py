"""Полный прогон cue2mp3: синтетический FLAC + CUE -> MP3 с тегами."""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/home/user/music_suite")

from musicsuite.engines import cue2mp3

FFMPEG = "/home/user/ffmpeg_test/ffmpeg"
os.environ["PATH"] = "/home/user/ffmpeg_test:" + os.environ.get("PATH", "")

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    source = tmp / "album.flac"

    # 3 секунды синусоиды: два трека по ~1.5 с
    subprocess.run(
        [FFMPEG, "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
         "-c:a", "flac", "-y", str(source)],
        check=True, capture_output=True
    )
    print("Исходник создан:", source.name, source.stat().st_size, "байт")

    cue = tmp / "album.cue"
    cue.write_text(
        'PERFORMER "Тестовый Исполнитель"\n'
        'TITLE "Тестовый Альбом"\n'
        'DATE "2024"\n'
        'GENRE "Test"\n'
        'FILE "album.flac" WAVE\n'
        '  TRACK 01 AUDIO\n'
        '    TITLE "Первый Трек"\n'
        '    INDEX 01 00:00:00\n'
        '  TRACK 02 AUDIO\n'
        '    TITLE "Второй Трек"\n'
        '    INDEX 01 00:01:50\n',
        encoding="utf-8"
    )

    out = tmp / "output"
    args = argparse.Namespace(input=str(tmp), output=str(out), quality="320", debug=False)
    cue2mp3.main(args)

    files = sorted(os.listdir(out))
    print("\nРезультат в папке вывода:")
    for f in files:
        print("  ", f, (out / f).stat().st_size, "байт")

    from mutagen.mp3 import MP3
    for f in files:
        if f.lower().endswith(".mp3"):
            audio = MP3(out / f)
            tags = audio.tags
            print(f"\n{f}:")
            print("  title   =", tags.get("TIT2"))
            print("  artist  =", tags.get("TPE1"))
            print("  album   =", tags.get("TALB"))
            print("  date    =", tags.get("TDRC"))
            print("  genre   =", tags.get("TCON"))
            print("  версия ID3 =", tags.version)

    assert any("Первый Трек" in f for f in files), "русское имя файла не сохранено"
    print("\nКОНВЕРТАЦИЯ CUE -> MP3 РАБОТАЕТ")
