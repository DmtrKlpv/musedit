"""Обновление существующего плейлиста по текущему состоянию папки с музыкой.

Задача утилиты: у вас есть плейлист (m3u/m3u8/pls/xspf/wpl) и папка с
треками, которая с тех пор изменилась — что-то добавилось, что-то удалено,
что-то переехало в подпапку. Скрипт пересобирает плейлист из фактического
содержимого папки, сохраняя:

  * формат и кодировку исходного плейлиста;
  * порядок треков, который был в плейлисте (новые дописываются в конец);
  * настройки путей — абсолютные/относительные и префикс вроде /music.

Логика путей, разбор форматов и запись файла взяты из движка plscreate
(save_playlist, read_playlist_tracks, format_path) без изменений, чтобы
поведение совпадало с утилитой «Создание плейлистов».
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

from . import plscreate
from ..progress import as_progress

MUSIC_EXTS = ('.mp3', '.flac', '.wav', '.m4a', '.ogg', '.ape', '.dsf', '.dff')


@dataclass
class UpdateReport:
    """Итог обновления: что произошло и с какими файлами."""

    playlist_path: str = ""
    format: str = "m3u8"
    total_found: int = 0
    kept: List[str] = field(default_factory=list)
    added: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    written: bool = False
    error: Optional[str] = None

    @property
    def summary(self) -> str:
        if self.error:
            return self.error
        if not self.written:
            return "Плейлист не изменён: содержимое совпадает с папкой."
        return (
            f"Треков в плейлисте: {len(self.kept) + len(self.added)} "
            f"(добавлено {len(self.added)}, удалено {len(self.removed)})"
        )


def detect_format(playlist_path: str) -> str:
    """Формат по расширению файла. Неизвестное расширение → m3u8."""
    ext = os.path.splitext(playlist_path)[1].lower().lstrip(".")
    return ext if ext in ("m3u", "m3u8", "pls", "xspf", "wpl") else "m3u8"


def _read_raw_tracks(playlist_path: str, fmt: str) -> dict:
    """Читает плейлист, сохраняя исходное написание путей.

    ``read_playlist_tracks`` нормализует пути (нижний регистр, прямые слэши),
    поэтому для отчёта «что удалено» нужен отдельный проход: иначе в GUI
    пользователь увидит имена в нижнем регистре.
    Возвращает {нормализованный путь: исходная строка}.
    """
    result = {}
    try:
        if fmt in ("m3u", "m3u8"):
            with open(playlist_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    raw = line.strip().rstrip("\r\n")
                    if raw and not raw.startswith("#"):
                        result[plscreate.normalize_track_path(raw)] = raw
        elif fmt == "pls":
            with open(playlist_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    raw = line.strip().rstrip("\r\n")
                    if raw.lower().startswith("file") and "=" in raw:
                        value = raw.split("=", 1)[1].strip()
                        result[plscreate.normalize_track_path(value)] = value
        else:
            import xml.etree.ElementTree as ET
            tree = ET.parse(playlist_path)
            for element in tree.getroot().iter():
                value = None
                if fmt == "xspf" and element.tag.endswith("location"):
                    value = (element.text or "").strip()
                elif fmt == "wpl" and element.tag == "media":
                    value = (element.get("src") or "").strip()
                if value:
                    result[plscreate.normalize_track_path(value)] = value
    except Exception:  # noqa: BLE001 — отчёт не должен срывать обновление
        return result
    return result


def _index_folder(music_dir: str, absolute: bool, rel_base: Optional[str],
                  progress) -> dict:
    """Строит соответствие «нормализованное имя файла» → путь для плейлиста."""
    found = {}
    for root, _, files in os.walk(music_dir):
        for name in files:
            if not name.lower().endswith(MUSIC_EXTS):
                continue
            full = os.path.join(root, name)
            path_for_playlist = plscreate.format_path(
                full, base_dir=music_dir, absolute=absolute, rel_base=rel_base
            )
            key = plscreate.normalize_name(name)
            # При совпадении имён в разных папках выигрывает первый —
            # ровно как в индексации самой утилиты «Создание плейлистов».
            found.setdefault(key, path_for_playlist)
    return found


def _match_old_track(old_path: str, folder_index: dict,
                     key_by_path: dict) -> Optional[str]:
    """Находит актуальный путь для трека из старого плейлиста.

    Сначала пробуем совпадение по имени файла (трек мог переехать в другую
    подпапку), затем точное совпадение нормализованного пути.
    """
    normalized = plscreate.normalize_track_path(old_path)
    direct = key_by_path.get(normalized)
    if direct:
        return direct

    base = os.path.basename(normalized)
    key = plscreate.normalize_name(base)
    return folder_index.get(key)


def update_playlist(playlist_path: str, music_dir: Optional[str] = None,
                    absolute: bool = False, rel_base: Optional[str] = None,
                    keep_missing: bool = False, add_new: bool = True,
                    progress=None) -> UpdateReport:
    """Пересобирает плейлист по содержимому папки.

    playlist_path — существующий плейлист, который нужно обновить.
    music_dir     — папка с музыкой; по умолчанию берётся папка плейлиста.
    absolute      — писать полные пути (как флаг -abs в plscreate).
    rel_base      — префикс относительного пути, например /music.
    keep_missing  — оставлять в плейлисте треки, которых нет в папке.
    add_new       — дописывать треки из папки, которых нет в плейлисте.
    """
    report = as_progress(progress)
    result = UpdateReport(playlist_path=playlist_path)

    if not playlist_path or not os.path.exists(playlist_path):
        result.error = f"Файл плейлиста не найден: {playlist_path}"
        print(f"[ОШИБКА] {result.error}")
        return result

    fmt = detect_format(playlist_path)
    result.format = fmt

    folder = music_dir or os.path.dirname(os.path.abspath(playlist_path))
    if not os.path.isdir(folder):
        result.error = f"Папка с музыкой не найдена: {folder}"
        print(f"[ОШИБКА] {result.error}")
        return result

    report.start(3, "Чтение плейлиста")
    print(f"\n=== Обновление плейлиста ===")
    print(f"Плейлист: {playlist_path}")
    print(f"Формат:   {fmt}")
    print(f"Музыка:   {folder}")

    old_tracks = plscreate.read_playlist_tracks(playlist_path, fmt)
    if old_tracks is None:
        old_tracks = []
        print("Плейлист не читается — будет собран заново из папки.")
    else:
        print(f"Треков в старом плейлисте: {len(old_tracks)}")

    # Исходное написание путей — только для отчёта, логика работает
    # по нормализованным значениям из old_tracks.
    raw_tracks = _read_raw_tracks(playlist_path, fmt)

    report.advance(1, "Индексация папки")
    folder_index = _index_folder(folder, absolute, rel_base, report)
    # Обратное соответствие: нормализованный путь из плейлиста → актуальный путь
    key_by_path = {}
    for path_value in folder_index.values():
        key_by_path[plscreate.normalize_track_path(path_value)] = path_value

    result.total_found = len(folder_index)
    print(f"Найдено аудиофайлов в папке: {len(folder_index)}")

    report.advance(1, "Сопоставление треков")
    ordered: List[str] = []
    seen_keys = set()

    for old_path in old_tracks:
        actual = _match_old_track(old_path, folder_index, key_by_path)
        if actual:
            key = plscreate.normalize_track_path(actual)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            ordered.append(actual)
            result.kept.append(os.path.basename(actual))
        else:
            display = raw_tracks.get(plscreate.normalize_track_path(old_path),
                                     os.path.basename(old_path))
            result.removed.append(display)
            print(f"  [—] Нет в папке: {display}")
            if keep_missing:
                key = plscreate.normalize_track_path(old_path)
                if key not in seen_keys:
                    seen_keys.add(key)
                    ordered.append(old_path)
                    result.kept.append(os.path.basename(old_path))

    if add_new:
        for key, path_value in sorted(folder_index.items()):
            norm = plscreate.normalize_track_path(path_value)
            if norm in seen_keys:
                continue
            seen_keys.add(norm)
            ordered.append(path_value)
            result.added.append(os.path.basename(path_value))
            print(f"  [+] Новый трек: {os.path.basename(path_value)}")

    if not ordered:
        result.error = "В папке не найдено ни одного аудиофайла — плейлист не изменён."
        print(f"[ОШИБКА] {result.error}")
        return result

    report.advance(1, "Запись плейлиста")
    playlist_name = os.path.splitext(os.path.basename(playlist_path))[0]

    # Сравниваем состав до записи: если он не изменился, файл не трогаем.
    new_normalized = sorted(plscreate.normalize_track_path(t) for t in ordered)
    if old_tracks and sorted(old_tracks) == new_normalized:
        result.written = False
        report.finish("Изменений нет")
        print("\n[=] Плейлист уже соответствует папке — файл не изменён.")
        return result

    # force=True: решение об изменении уже принято выше, повторная
    # проверка внутри save_playlist только привела бы к двойной записи.
    plscreate.save_playlist(playlist_path, ordered, fmt, playlist_name,
                            use_folder_name=False, force=True)
    result.written = True

    report.finish(result.summary)
    print(f"\n[+] Готово: {result.summary}")
    print(f"Файл: {playlist_path}")
    return result


# ---------------------------------------------------------------------------
# Режим сравнения для GUI: два списка — плейлист и папка — без записи файла
# ---------------------------------------------------------------------------

@dataclass
class PlaylistEntry:
    """Строка левой таблицы: трек, записанный в плейлисте."""

    original: str          # как записано в файле
    normalized: str        # нормализованный путь для сравнения
    matched: Optional[str] = None   # актуальный путь в папке, если найден

    @property
    def state(self) -> str:
        return "kept" if self.matched else "missing"

    @property
    def display(self) -> str:
        """Текст для таблицы: путь как в файле, либо имя найденного файла."""
        return self.original


@dataclass
class FolderEntry:
    """Строка правой таблицы: аудиофайл, найденный в папке."""

    full_path: str
    normalized: str
    in_playlist: bool = False

    @property
    def state(self) -> str:
        return "kept" if self.in_playlist else "new"

    @property
    def display(self) -> str:
        return os.path.basename(self.full_path)


@dataclass
class CompareResult:
    """Результат сравнения плейлиста и папки."""

    playlist_path: str = ""
    music_dir: str = ""
    format: str = "m3u8"
    entries: List[PlaylistEntry] = field(default_factory=list)
    files: List[FolderEntry] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def missing(self) -> List[PlaylistEntry]:
        return [e for e in self.entries if e.state == "missing"]

    @property
    def new(self) -> List[FolderEntry]:
        return [f for f in self.files if f.state == "new"]

    @property
    def kept(self) -> List[PlaylistEntry]:
        return [e for e in self.entries if e.state == "kept"]


def scan_folder(music_dir: str) -> List[FolderEntry]:
    """Собирает все аудиофайлы папки (рекурсивно), в порядке обхода."""
    found: List[FolderEntry] = []
    if not os.path.isdir(music_dir):
        return found
    for root, _, files in os.walk(music_dir):
        for name in files:
            if not name.lower().endswith(MUSIC_EXTS):
                continue
            full = os.path.join(root, name)
            found.append(FolderEntry(full_path=full,
                                     normalized=plscreate.normalize_track_path(full)))
    found.sort(key=lambda entry: entry.full_path.lower())
    return found


def compare(playlist_path: str, music_dir: str, progress=None) -> CompareResult:
    """Строит два списка для GUI, ничего не записывая на диск.

    Сопоставление повторяет логику update_playlist: сначала точное совпадение
    нормализованного пути, затем — по нормализованному имени файла. Второй
    вариант нужен, потому что трек мог переехать в другую подпапку.
    """
    report = as_progress(progress)
    result = CompareResult(playlist_path=playlist_path, music_dir=music_dir)

    if not playlist_path or not os.path.isfile(playlist_path):
        result.error = f"Файл плейлиста не найден: {playlist_path}"
        print(f"[ОШИБКА] {result.error}")
        return result

    if not music_dir or not os.path.isdir(music_dir):
        result.error = f"Папка для сканирования не найдена: {music_dir}"
        print(f"[ОШИБКА] {result.error}")
        return result

    fmt = detect_format(playlist_path)
    result.format = fmt

    report.start(3, "Чтение плейлиста")
    raw_tracks = _read_raw_tracks(playlist_path, fmt)
    if not raw_tracks:
        result.error = ("Плейлист пуст или не читается. Поддерживаются "
                        "m3u, m3u8, pls, xspf и wpl.")
        print(f"[ОШИБКА] {result.error}")
        return result

    for normalized, original in raw_tracks.items():
        result.entries.append(PlaylistEntry(original=original, normalized=normalized))
    print(f"Треков в плейлисте: {len(result.entries)}")

    report.advance(1, "Сканирование папки")
    result.files = scan_folder(music_dir)
    print(f"Аудиофайлов в папке: {len(result.files)}")

    # Индексы для сопоставления: по нормализованному пути и по имени файла.
    by_path = {entry.normalized: entry for entry in result.files}
    by_name: dict = {}
    for entry in result.files:
        by_name.setdefault(plscreate.normalize_name(os.path.basename(entry.full_path)),
                           entry)

    report.advance(1, "Сопоставление")
    for item in result.entries:
        target = by_path.get(item.normalized)
        if target is None:
            name_key = plscreate.normalize_name(os.path.basename(item.normalized))
            target = by_name.get(name_key)
        if target is not None:
            item.matched = target.full_path
            target.in_playlist = True
        else:
            print(f"  [—] Нет в папке: {item.original}")

    for entry in result.new:
        print(f"  [+] Новый файл: {os.path.basename(entry.full_path)}")

    report.finish(
        f"В плейлисте {len(result.entries)}, в папке {len(result.files)}: "
        f"нет в папке {len(result.missing)}, новых {len(result.new)}"
    )
    return result


def apply_comparison(playlist_path: str, entries: List[PlaylistEntry],
                     music_dir: Optional[str] = None,
                     keep_missing: bool = False,
                     absolute: bool = False, rel_base: Optional[str] = None,
                     progress=None) -> UpdateReport:
    """Записывает плейлист по уже построенному списку входов.

    Новые файлы берутся из entries с состоянием kept плюс помеченные как new
    добавляются вызывающей стороной: список передаётся готовым, чтобы
    «Обновить плейлист» записывал ровно то, что видит пользователь в таблицах.

    music_dir нужен для относительных путей: save_playlist пишет строки как есть,
    поэтому format_path (тот же, что в plscreate) применяется здесь.
    """
    report = as_progress(progress)
    out = UpdateReport(playlist_path=playlist_path)
    out.format = detect_format(playlist_path)

    if not playlist_path or not os.path.isfile(playlist_path):
        out.error = f"Файл плейлиста не найден: {playlist_path}"
        print(f"[ОШИБКА] {out.error}")
        return out

    ordered: List[str] = []
    seen = set()

    for item in entries:
        if item.matched:
            value = item.matched
        elif keep_missing:
            value = item.original
        else:
            out.removed.append(item.original)
            print(f"  [—] Удалён из плейлиста: {item.original}")
            continue
        key = plscreate.normalize_track_path(value)
        if key in seen:
            continue
        seen.add(key)
        # Абсолютный путь в файл попадает только по явному запросу:
        # по умолчанию пишем относительно папки или с префиксом rel_base.
        write_value = value
        if os.path.isabs(value) and not absolute:
            write_value = plscreate.format_path(
                value, base_dir=music_dir, absolute=False, rel_base=rel_base
            )
        ordered.append(write_value)
        out.kept.append(os.path.basename(value))

    if not ordered:
        out.error = "В плейлисте не осталось ни одного трека — файл не изменён."
        print(f"[ОШИБКА] {out.error}")
        return out

    report.start(1, "Запись плейлиста")
    name = os.path.splitext(os.path.basename(playlist_path))[0]
    plscreate.save_playlist(playlist_path, ordered, out.format, name,
                            use_folder_name=False, force=True)
    out.written = True
    report.finish(out.summary)
    print(f"\n[+] Готово: {out.summary}")
    print(f"Файл: {playlist_path}")
    return out
