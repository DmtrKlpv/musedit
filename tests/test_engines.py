"""Проверка движков на реальных файлах (без сети)."""

import argparse
import os
import sys
import tempfile

sys.path.insert(0, "/home/user/music_suite")

from musicsuite.engines import cue2mp3, fixtags, plscreate, yamd


def section(title):
    print(f"\n=== {title} ===")


# ----------------------------------------------------------------------
section("plscreate: плейлист из папок (m3u8)")
with tempfile.TemporaryDirectory() as tmp:
    album = os.path.join(tmp, "Album One")
    os.makedirs(album)
    for name in ("01 - Track.mp3", "02 - Track.flac", "cover.jpg"):
        with open(os.path.join(album, name), "wb") as f:
            f.write(b"x")
    out = os.path.join(tmp, "pls_out")
    args = argparse.Namespace(
        path=tmp, format="m3u8", savedir=out, from_list=None, mass=None,
        searchdir=None, absolute=False, relative_base=None, use_folder_name=True,
    )
    plscreate.main(args)
    created = os.listdir(out)
    print("Создано файлов:", created)
    content = open(os.path.join(out, created[0]), encoding="utf-8").read()
    print("Содержимое:\n" + content)
    assert content.startswith("#EXTM3U")
    assert "01 - Track.mp3" in content
    assert "cover.jpg" not in content

section("plscreate: повторный запуск не перезаписывает")
with tempfile.TemporaryDirectory() as tmp:
    album = os.path.join(tmp, "A")
    os.makedirs(album)
    open(os.path.join(album, "t.mp3"), "wb").close()
    args = argparse.Namespace(
        path=tmp, format="m3u", savedir=None, from_list=None, mass=None,
        searchdir=None, absolute=True, relative_base="/music", use_folder_name=False,
    )
    plscreate.main(args)
    plscreate.main(args)

section("plscreate: из TXT-списка")
with tempfile.TemporaryDirectory() as tmp:
    music = os.path.join(tmp, "music")
    os.makedirs(os.path.join(music, "sub"))
    open(os.path.join(music, "sub", "Artist - Song.mp3"), "wb").close()
    lst = os.path.join(tmp, "list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        f.write("Artist - Song\nНеизвестный трек\n")
    save = os.path.join(tmp, "out")
    args = argparse.Namespace(
        path=None, format="m3u8", savedir=save, from_list=lst, mass=None,
        searchdir=music, absolute=False, relative_base="/music", use_folder_name=False,
    )
    plscreate.main(args)
    print("Файлы:", os.listdir(save))

# ----------------------------------------------------------------------
section("cue2mp3: разбор CUE")
cue_text = """PERFORMER "Artist Name"
TITLE "Album Title"
DATE "1999"
GENRE "Rock"
FILE "album.flac" WAVE
  TRACK 01 AUDIO
    TITLE "First Song"
    INDEX 01 00:00:00
  TRACK 02 AUDIO
    TITLE "Second Song"
    INDEX 01 03:21:45
"""
album_meta, tracks = cue2mp3.parse_cue_content(cue_text)
print("Альбом:", album_meta)
for t in tracks:
    print(" Трек:", t)
assert album_meta["SOURCE_FILE"] == "album.flac"
assert len(tracks) == 2
assert tracks[1]["TITLE"] == "Second Song"
print("время 03:21:45 ->", round(cue2mp3.time_to_seconds("03:21:45"), 3), "сек")
assert abs(cue2mp3.time_to_seconds("03:21:45") - 201.6) < 0.001
print("MIME по сигнатуре JPEG:", cue2mp3.get_mime_type(b"\xff\xd8\xff\xe0"))

section("cue2mp3: поиск CUE в папке и подстановка аудио")
with tempfile.TemporaryDirectory() as tmp:
    with open(os.path.join(tmp, "album.cue"), "w", encoding="cp1251") as f:
        f.write(cue_text.replace('"album.flac"', '"missing.flac"'))
    open(os.path.join(tmp, "real.flac"), "wb").close()
    content, enc = cue2mp3.read_cue_file(
        __import__("pathlib").Path(tmp) / "album.cue"
    )
    print("Кодировка определена:", enc)

# ----------------------------------------------------------------------
section("fixtags: исправление кракозябр")
broken = "Песня".encode("cp1251").decode("latin-1")
print("Было:", broken, "-> Стало:", fixtags.fix_mojibake(broken))
assert fixtags.fix_mojibake(broken) == "Песня"
assert fixtags.fix_mojibake("Normal Text") == "Normal Text"
print("Пустая строка:", repr(fixtags.fix_mojibake("")))

# ----------------------------------------------------------------------
section("yamd: конфиг init.tok и sanitize")
cwd = os.getcwd()
with tempfile.TemporaryDirectory() as tmp:
    os.chdir(tmp)
    yamd.save_config({"TOKEN": "abc123", "TIMEOUT": "20"})
    cfg = yamd.load_config()
    print("Прочитано:", cfg)
    assert cfg["TOKEN"] == "abc123"
    os.chdir(cwd)
print("sanitize:", yamd.sanitize('AC/DC: "Live" <2020>'))
assert yamd.sanitize('a/b:c*d?e"f<g>h|i') == "abcdefghi"

print("\nВСЕ ПРОВЕРКИ ДВИЖКОВ ПРОЙДЕНЫ")
