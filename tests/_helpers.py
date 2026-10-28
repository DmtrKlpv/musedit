"""Общие помощники для тестов: генерация настоящих MP3 с нужными тегами."""

import os
import subprocess

from mutagen.id3 import ID3, TALB, TIT2, TPE1


def make_mp3(path, title, album, seconds=1.0, bitrate="192k", artist=None):
    """Создаёт реальный MP3 через ffmpeg и навешивает ID3v2.4-теги.

    Синтетические файлы из одних нулей mutagen не читает
    (can't sync to MPEG frame), поэтому нужен настоящий поток.
    """
    try:
        import imageio_ffmpeg
    except ImportError:
        raise SystemExit("нужен imageio_ffmpeg для генерации тестового MP3")

    exe = imageio_ffmpeg.get_ffmpeg_exe()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    subprocess.run(
        [exe, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "libmp3lame",
         "-b:a", bitrate, path, "-y"],
        check=True,
    )
    tags = ID3()
    tags.add(TIT2(encoding=1, text=[title]))
    tags.add(TALB(encoding=1, text=[album]))
    if artist:
        tags.add(TPE1(encoding=1, text=[artist]))
    tags.save(path, v1=0, v2_version=4)
    return path
