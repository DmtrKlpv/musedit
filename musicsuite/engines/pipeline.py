"""Конвейер: экспорт плейлиста → скачивание треков → создание файла плейлиста.

Одна операция вместо трёх вкладок. На входе — либо HTML/iframe плейлиста
Яндекс.Музыки, либо готовый TXT-список треков. На выходе — папка с музыкой
и файл плейлиста, который на неё указывает.

Шаги используют существующие движки без изменения их логики:

  1. ``plsgen.get_playlist_tracks`` — iframe → TXT со списком треков;
  2. ``yamd.download``            — TXT → MP3/FLAC в папку коллекции;
  3. ``plscreate.format_path`` +
     ``plscreate.save_playlist``  — папка → файл плейлиста.

Промежуточный TXT удаляется, если он был создан из iframe: пользователю
нужны музыка и плейлист, а не служебный список.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

from . import plscreate, plsgen, yamd
from ..progress import NullProgress, as_progress

MUSIC_EXTS = ('.mp3', '.flac', '.wav', '.m4a', '.ogg', '.ape', '.dsf', '.dff')


@dataclass
class PipelineResult:
    """Итог конвейера: что создано и где это лежит."""

    playlist_path: str = ""
    music_dir: str = ""
    txt_path: str = ""
    tracks_found: int = 0
    downloaded: int = 0
    total: int = 0
    rows: List[dict] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def summary(self) -> str:
        if self.error:
            return self.error
        return (
            f"Скачано треков: {self.downloaded} из {self.total}. "
            f"В плейлисте: {self.tracks_found}."
        )


def _safe_name(name: str, fallback: str = "playlist") -> str:
    """Имя папки и файла без символов, запрещённых в Windows."""
    clean = re.sub(r'[<>:"/\\|?*]', "_", (name or "").strip())
    clean = clean.strip(" .")
    return clean or fallback


def _detect_format(output_name: str) -> str:
    ext = os.path.splitext(output_name)[1].lower().lstrip(".")
    return ext if ext in ("m3u", "m3u8", "pls", "xspf", "wpl") else "m3u8"


def _build_playlist_from_folder(music_dir: str, playlist_path: str,
                                fmt: str, absolute: bool,
                                rel_base: Optional[str],
                                use_folder_name: bool,
                                progress) -> int:
    """Собирает файл плейлиста по фактическому содержимому папки."""
    base_dir = os.path.dirname(os.path.abspath(music_dir))
    tracks: List[str] = []

    for root, _, files in os.walk(music_dir):
        for name in files:
            if not name.lower().endswith(MUSIC_EXTS):
                continue
            full = os.path.join(root, name)
            tracks.append(plscreate.format_path(
                full, base_dir=base_dir, absolute=absolute, rel_base=rel_base
            ))

    tracks.sort()
    if not tracks:
        return 0

    pls_name = os.path.splitext(os.path.basename(playlist_path))[0]
    plscreate.save_playlist(playlist_path, tracks, fmt, pls_name,
                            use_folder_name=use_folder_name, force=True)
    # save_playlist возвращает None, поэтому факт считаем по списку треков.
    if progress is not None:
        progress.message(f"Плейлист: {len(tracks)} треков")
    return len(tracks)


def run(iframe_code: str = "",
        txt_path: str = "",
        music_root: str = "",
        playlist_dir: str = "",
        playlist_name: str = "",
        playlist_format: str = "m3u8",
        absolute: bool = False,
        rel_base: Optional[str] = None,
        token: str = "",
        timeout: int = 15,
        retries: int = 3,
        use_flac: bool = False,
        progress=None,
        on_track=None) -> PipelineResult:
    """Полный цикл: получить список треков, скачать их, записать плейлист.

    iframe_code   — HTML/iframe плейлиста (взаимоисключимо с txt_path).
    txt_path      — готовый TXT со списком треков.
    music_root    — корневая папка, куда складывать музыку.
    playlist_dir  — папка для файла плейлиста (по умолчанию music_root).
    playlist_name — имя плейлиста без расширения; задаёт и имя подпапки.
    """
    report = as_progress(progress)
    result = PipelineResult()

    if not music_root or not os.path.isdir(music_root):
        result.error = f"Папка для музыки не найдена: {music_root}"
        print(f"[ОШИБКА] {result.error}")
        return result

    name = _safe_name(playlist_name or "playlist")
    playlist_dir = playlist_dir or music_root
    os.makedirs(playlist_dir, exist_ok=True)
    fmt = playlist_format if playlist_format in ("m3u", "m3u8", "pls", "xspf", "wpl") \
        else _detect_format(playlist_name)

    print(f"\n=== Скачивание с Яндекс.Музыки: {name} ===")

    # ---- шаг 1: получить TXT со списком треков ----
    created_txt = False
    if iframe_code.strip():
        report.start(3, "Разбор плейлиста")
        result.txt_path = os.path.join(
            playlist_dir, f"{name}.txt"
        )
        txt = plsgen.get_playlist_tracks(
            iframe_code, f"{name}.txt", output_path=result.txt_path,
            progress=report,
        )
        if not txt:
            result.error = ("Не удалось получить список треков из iframe. "
                            "Проверьте, что вставлен код плейлиста.")
            print(f"[ОШИБКА] {result.error}")
            return result
        result.txt_path = txt
        created_txt = True
    elif txt_path.strip():
        if not os.path.isfile(txt_path):
            result.error = f"TXT-файл не найден: {txt_path}"
            print(f"[ОШИБКА] {result.error}")
            return result
        result.txt_path = txt_path
    else:
        result.error = "Укажите код iframe плейлиста или TXT-файл со списком треков."
        print(f"[ОШИБКА] {result.error}")
        return result

    # ---- шаг 2: скачать треки ----
    report.start(0, "Скачивание треков")
    dl = yamd.download(
        result.txt_path, music_root, timeout, retries, use_flac, token,
        progress=report, on_track=on_track,
    )

    if not isinstance(dl, dict):
        result.error = "Скачивание не выполнено: движок не вернул результат."
        print(f"[ОШИБКА] {result.error}")
        return result

    result.music_dir = dl.get("target_dir", "")
    result.rows = dl.get("rows") or []
    result.downloaded = dl.get("downloaded", 0)
    result.total = dl.get("total", 0)

    # ---- шаг 3: создать плейлист ----
    report.message("Создание плейлиста")
    extension = fmt
    playlist_path = os.path.join(playlist_dir, f"{name}.{extension}")
    result.playlist_path = playlist_path

    result.tracks_found = _build_playlist_from_folder(
        result.music_dir, playlist_path, fmt, absolute, rel_base,
        bool(name), report,
    )

    if not result.tracks_found:
        result.error = ("Треки не найдены в папке загрузки — плейлист не создан. "
                        "Проверьте токен и названия треков.")
        print(f"[ОШИБКА] {result.error}")
    else:
        print(f"[+] Плейлист: {playlist_path}")
        print(f"[+] Музыка:   {result.music_dir}")

    # Служебный TXT из iframe удаляем: пользователю он не нужен.
    if created_txt and os.path.isfile(result.txt_path):
        try:
            os.remove(result.txt_path)
        except OSError:
            pass

    report.finish(result.summary)
    print(f"\n[+] Готово: {result.summary}")
    return result
