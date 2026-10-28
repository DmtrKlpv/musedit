"""Поиск треков из плейлиста в папке и замена путей на актуальные.

Задача: плейлист ссылается на файлы, которых по этим путям больше нет —
папка переехала, диск сменил букву, музыка разложена иначе. Нужно найти
каждый трек в указанной папке (рекурсивно) и записать в плейлист
рабочий путь.

Чем отличается от «Обновления плейлиста»:
  * там состав плейлиста приводится к содержимому папки (что-то удаляется,
    что-то дописывается);
  * здесь состав не меняется — меняются ТОЛЬКО строки с путями,
    и каждая замена подтверждается пользователем.

Формат путей считается через ``plscreate.format_path``, поэтому префикс
и абсолютные пути работают ровно так же, как в остальных вкладках.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import plscreate
from ..progress import as_progress

try:
    from mutagen import File as MutagenFile
    _HAS_MUTAGEN = True
except Exception:  # noqa: BLE001 — без mutagen поиск по тегам просто отключён
    MutagenFile = None
    _HAS_MUTAGEN = False

MUSIC_EXTS = ('.mp3', '.flac', '.wav', '.m4a', '.ogg', '.ape', '.dsf', '.dff')


@dataclass
class TrackRow:
    """Одна строка плейлиста и результат её поиска."""

    index: int                 # порядковый номер строки в файле
    old_path: str              # как записано сейчас
    new_path: str = ""         # выбранный путь в формате для записи
    found_file: str = ""       # полный путь к файлу на диске
    applied: bool = False      # уже заменено в файле
    fuzzy: bool = False        # найден по названию или тегам, а не по точному имени
    default_path: str = ""     # вариант, предложенный поиском (первый в списке)

    # Все найденные варианты с тем же именем файла, лучший — первый.
    # Нужны для выпадающего списка: одноимённые треки в разных альбомах
    # встречаются постоянно, и выбор должен оставаться за пользователем.
    candidates: List[str] = field(default_factory=list)

    @property
    def option_count(self) -> int:
        """Сколько путей-кандидатов найдено."""
        return len(self.candidates)

    @property
    def track_name(self) -> str:
        return os.path.basename(self.old_path.replace("\\", "/"))

    @property
    def state(self) -> str:
        if self.applied:
            return "changed"
        return "found" if self.new_path else "missing"


@dataclass
class SearchResult:
    """Итог поиска по плейлисту."""

    playlist_path: str = ""
    folder: str = ""
    format: str = "m3u8"
    rows: List[TrackRow] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def found(self) -> List[TrackRow]:
        return [r for r in self.rows if r.new_path and not r.applied]

    @property
    def missing(self) -> List[TrackRow]:
        return [r for r in self.rows if not r.new_path]

    @property
    def summary(self) -> str:
        if self.error:
            return self.error
        return (f"Всего строк: {len(self.rows)}. "
                f"Найдено: {len(self.found)}. "
                f"Не найдено: {len(self.missing)}.")


def detect_format(playlist_path: str) -> str:
    ext = os.path.splitext(playlist_path)[1].lower().lstrip(".")
    return ext if ext in ("m3u", "m3u8", "pls", "xspf", "wpl") else "m3u8"


# ---------------------------------------------------------------------------
# Чтение и запись строк плейлиста с сохранением структуры файла
# ---------------------------------------------------------------------------

def read_lines(playlist_path: str) -> List[str]:
    """Читает файл как список строк, без нормализации.

    Нужно именно так, а не через read_playlist_tracks: при замене путей
    важно сохранить комментарии, теги #EXTINF и порядок строк.
    """
    with open(playlist_path, "r", encoding="utf-8", errors="replace") as stream:
        return stream.read().splitlines()


def is_path_line(line: str, fmt: str) -> bool:
    """Является ли строка путём к файлу (а не тегом или комментарием)."""
    stripped = line.strip()
    if not stripped:
        return False
    if fmt in ("m3u", "m3u8"):
        return not stripped.startswith("#")
    if fmt == "pls":
        return stripped.lower().startswith("file") and "=" in stripped
    if fmt == "xspf":
        return "<location>" in stripped
    if fmt == "wpl":
        return "<media" in stripped
    return False


def extract_path(line: str, fmt: str) -> str:
    """Достаёт путь из строки нужного формата."""
    stripped = line.strip()
    if fmt == "pls":
        return stripped.split("=", 1)[1].strip()
    if fmt == "xspf":
        match = re.search(r"<location>(.*?)</location>", stripped)
        return (match.group(1).strip() if match else "")
    if fmt == "wpl":
        match = re.search(r'src="([^"]*)"', stripped)
        return (match.group(1).strip() if match else "")
    return stripped


def replace_path(line: str, fmt: str, new_path: str) -> str:
    """Подставляет новый путь в строку, сохраняя её формат."""
    stripped = line.strip()
    indent = line[:len(line) - len(line.lstrip())]

    if fmt == "pls":
        prefix = stripped.split("=", 1)[0]
        return f"{indent}{prefix}={new_path}"
    if fmt == "xspf":
        return re.sub(r"<location>.*?</location>",
                      f"<location>{new_path}</location>", stripped)
    if fmt == "wpl":
        return re.sub(r'src="[^"]*"', f'src="{new_path}"', stripped)
    return f"{indent}{new_path}"


# ---------------------------------------------------------------------------
# Поиск
# ---------------------------------------------------------------------------

def count_music_files(folder: str) -> int:
    """Считает аудиофайлы в папке — нужен, чтобы шкала прогресса была честной.

    Обход без чтения файлов дешёвый: на 20 000 файлов это доли секунды,
    а взамен полоса показывает реальный ход индексации, а не стоит на месте.
    """
    total = 0
    for _, _, files in os.walk(folder):
        for name in files:
            if name.lower().endswith(MUSIC_EXTS):
                total += 1
    return total


# Слова, которые не помогают отличить один трек от другого.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "feat", "ft", "vs", "prod", "remix", "edit", "version", "radio",
}


def track_title(name: str) -> str:
    """Название трека без исполнителя.

    «System Of A Down - Aerials.mp3» → «Aerials».
    Берём часть после ПОСЛЕДНЕГО разделителя: в именах вида
    «Artist - Album - Track» названием считается последний сегмент.
    """
    base = os.path.splitext(os.path.basename(name.replace("\\", "/")))[0]
    for separator in (" - ", " – ", " — "):
        if separator in base:
            return base.rsplit(separator, 1)[1]
    return base


def title_tokens(name: str) -> List[str]:
    """Значимые слова названия трека в нормализованном виде.

    Числа и короткие слова отбрасываем: «14» в «14 - Aerials» — это номер
    трека, он есть в одном файле и отсутствует в другом, хотя трек тот же.
    """
    title = track_title(name)
    normalized = plscreate.normalize_name(title + ".x")   # .x — чтобы не срезать расширение
    tokens = []
    for word in normalized.split():
        if len(word) <= 2:
            continue
        if word in _STOPWORDS:
            continue
        if word.isdigit():
            continue
        tokens.append(word)
    return tokens


def read_tags(path: str):
    """Читает исполнителя и название из ID3-тегов файла.

    Возвращает (artist, title) или (None, None), если тегов нет или файл
    не читается. Ошибки не пробрасываем: один битый файл не должен
    срывать индексацию всей библиотеки.
    """
    if not _HAS_MUTAGEN:
        return None, None

    try:
        audio = MutagenFile(path, easy=True)
        if audio is None:
            return None, None
        artists = audio.get("artist") or []
        titles = audio.get("title") or []
        artist = str(artists[0]).strip() if artists else None
        title = str(titles[0]).strip() if titles else None
        return artist or None, title or None
    except Exception:  # noqa: BLE001
        return None, None


def _tag_key(artist: str, title: str) -> str:
    """Ключ для сопоставления по тегам: нормализованные исполнитель + название."""
    return f"{plscreate.normalize_name(artist or '')}|{plscreate.normalize_name(title or '')}"


def _index_tags(folder: str, report=None, offset: int = 0,
                total_steps: int = 0, file_count: int = 0):
    """Индекс по ID3-тегам: «исполнитель|название» → список путей.

    Возвращает (tag_index, title_index). title_index — по одному названию,
    на случай если в плейлисте указан только трек без исполнителя.

    Чтение тегов — самая дорогая операция, поэтому по умолчанию выключено
    и включается галочкой в интерфейсе.
    """
    tag_index: Dict[str, List[str]] = {}
    title_index: Dict[str, List[str]] = {}
    processed = 0

    for root, _, files in os.walk(folder):
        for name in files:
            if not name.lower().endswith(MUSIC_EXTS):
                continue
            full = os.path.join(root, name)
            processed += 1

            artist, title = read_tags(full)
            if title:
                tag_index.setdefault(_tag_key(artist, title), []).append(full)
                title_index.setdefault(
                    plscreate.normalize_name(title), []
                ).append(full)

            if report is not None and total_steps:
                report.update(offset + processed, total_steps,
                              f"Теги: {name}")

    return tag_index, title_index


def _index_folder(folder: str, base_dir: str, absolute: bool,
                  rel_base: Optional[str], report=None, offset: int = 0,
                  total_steps: int = 0):
    """Индекс файлов папки: имя и слова названия → список путей для записи.

    Списком, а не одним значением: одноимённые треки в разных альбомах —
    обычное дело, их надо уметь различать по остатку старого пути.

    report — объект прогресса; на каждый файл идёт advance, поэтому полоса
    движется во время индексации, а не только на сопоставлении.
    """
    index: Dict[str, List[str]] = {}
    # Индекс по словам названия: нужен, когда имя файла в плейлисте и на
    # диске записаны по-разному — «System Of A Down - Aerials.mp3» против
    # «14 - Aerials.mp3». Ключ — значимое слово, значение — пути.
    token_index: Dict[str, List[str]] = {}
    processed = 0

    for root, _, files in os.walk(folder):
        for name in files:
            if not name.lower().endswith(MUSIC_EXTS):
                continue
            full = os.path.join(root, name)
            key = plscreate.normalize_name(name)
            write_path = plscreate.format_path(
                full, base_dir=base_dir, absolute=absolute, rel_base=rel_base
            )
            index.setdefault(key, []).append(write_path)

            for token in title_tokens(name):
                token_index.setdefault(token, []).append(write_path)

            processed += 1
            if report is not None and total_steps:
                report.update(offset + processed, total_steps, f"Индексация: {name}")

    return index, token_index


def _fuzzy_candidates(old_path: str, token_index: Dict[str, List[str]],
                      limit: int = 60) -> List[str]:
    """Ищет файлы по словам названия, когда точного совпадения имени нет.

    Берём самое длинное слово названия (оно самое редкое), затем оставляем
    только те файлы, где встречаются ВСЕ значимые слова. Если таких нет —
    отдаём кандидатов по самому длинному слову: пользователь увидит их
    в выпадающем списке и выберет нужный.
    """
    tokens = title_tokens(old_path)
    if not tokens:
        return []

    # Стартуем с самого редкого слова — меньше кандидатов на проверку.
    tokens.sort(key=lambda t: len(token_index.get(t, ())))
    primary = tokens[0]
    pool = token_index.get(primary) or []
    if not pool:
        return []

    need = set(tokens)

    def matches(path: str) -> bool:
        words = set(title_tokens(os.path.basename(path)))
        return need.issubset(words)

    strict = [p for p in pool if matches(p)]
    if strict:
        return strict[:limit]

    # Строгого совпадения нет — возвращаем по главному слову, но
    # отбрасываем совсем короткие названия-однословки слишком общего вида.
    return pool[:limit]


def _tag_candidates(old_path: str, tag_index: Dict[str, List[str]],
                    title_index: Dict[str, List[str]],
                    base_dir: str, absolute: bool,
                    rel_base: Optional[str]) -> List[str]:
    """Ищет файл по ID3-тегам, когда имя файла не совпало.

    Проверяем два варианта:
      1. «исполнитель — название» из записи плейлиста против тегов;
      2. только название трека (исполнитель в плейлисте может отсутствовать).
    Найденные пути сразу пересчитываются в формат плейлиста.
    """
    base = os.path.basename(old_path.replace("\\", "/"))
    title = track_title(base)
    artist_guess = ""
    if " - " in os.path.splitext(base)[0]:
        artist_guess = os.path.splitext(base)[0].rsplit(" - ", 1)[0].strip()

    found: List[str] = []

    if artist_guess and title:
        key = _tag_key(artist_guess, title)
        found.extend(tag_index.get(key) or [])

    if not found and title:
        found.extend(title_index.get(plscreate.normalize_name(title)) or [])

    # Пересчитываем в формат плейлиста: пути из тегового индекса —
    # абсолютные пути на диске.
    result = []
    for full in found:
        try:
            result.append(plscreate.format_path(
                full, base_dir=base_dir, absolute=absolute, rel_base=rel_base
            ))
        except Exception:  # noqa: BLE001
            continue
    return result


def _score_candidate(old_path: str, candidate: str) -> int:
    """Чем больше общих сегментов пути, тем вероятнее совпадение.

    Нужно, чтобы «Album A/01 Track.mp3» выбирал файл из Album A,
    а не первый попавшийся одноимённый.
    """
    old_parts = set(
        p.lower() for p in re.split(r"[/\\]", old_path) if p and p not in (".", "..")
    )
    new_parts = set(
        p.lower() for p in re.split(r"[/\\]", candidate) if p and p not in (".", "..")
    )
    return len(old_parts & new_parts)


def find_playlist_matches(playlist_path: str, folder: str,
                          absolute: bool = False,
                          rel_base: Optional[str] = None,
                          search_tags: bool = False,
                          progress=None) -> SearchResult:
    """Ищет каждый трек плейлиста в папке и готовит новые пути."""
    report = as_progress(progress)
    result = SearchResult(playlist_path=playlist_path, folder=folder)

    if not playlist_path or not os.path.isfile(playlist_path):
        result.error = f"Файл плейлиста не найден: {playlist_path}"
        print(f"[ОШИБКА] {result.error}")
        return result

    if not folder or not os.path.isdir(folder):
        result.error = f"Папка для поиска не найдена: {folder}"
        print(f"[ОШИБКА] {result.error}")
        return result

    fmt = detect_format(playlist_path)
    result.format = fmt

    print(f"\n=== Поиск по плейлисту ===")
    print(f"Плейлист: {playlist_path}")
    print(f"Папка:    {folder}")

    lines = read_lines(playlist_path)
    path_rows = [(i, line) for i, line in enumerate(lines) if is_path_line(line, fmt)]
    print(f"Строк с путями: {len(path_rows)}")

    # Шкала прогресса задаётся один раз и покрывает оба этапа:
    # по шагу на каждый файл папки и по шагу на каждую строку плейлиста.
    # Раньше индексация занимала 1 шаг из (2 + строк) — почти всё время
    # работы полоса стояла на 3%, а потом прыгала в 100%.
    file_count = count_music_files(folder)
    # Если включён поиск по тегам, файлы проходятся дважды: индексация имён
    # и чтение тегов. Шкала это учитывает, иначе полоса врала бы о ходе.
    total_steps = file_count * (2 if search_tags else 1) + len(path_rows)
    if total_steps <= 0:
        total_steps = 1

    report.start(total_steps, "Чтение плейлиста")

    base_dir = folder
    index, token_index = _index_folder(
        folder, base_dir, absolute, rel_base,
        report=report, offset=0, total_steps=total_steps,
    )
    print(f"Аудиофайлов в папке: {sum(len(v) for v in index.values())}")

    tag_index: Dict[str, List[str]] = {}
    tag_title_index: Dict[str, List[str]] = {}
    if search_tags:
        if not _HAS_MUTAGEN:
            result.error = ("Не установлена библиотека mutagen — "
                            "поиск по mp3-тегам недоступен.")
            print(f"[ОШИБКА] {result.error}")
            return result
        tag_index, tag_title_index = _index_tags(
            folder, report=report, offset=file_count,
            total_steps=total_steps, file_count=file_count,
        )
        print(f"Файлов с тегами: {len(tag_title_index)}")

    total = len(path_rows)
    for position, (line_index, line) in enumerate(path_rows, start=1):
        old_path = extract_path(line, fmt)
        row = TrackRow(index=line_index, old_path=old_path)

        key = plscreate.normalize_name(os.path.basename(old_path.replace("\\", "/")))
        candidates = list(index.get(key) or [])

        # Точного совпадения имени нет — пробуем найти по названию трека.
        # Так «System Of A Down - Aerials.mp3» находит «14 - Aerials.mp3»
        # из папки дискографии.
        fuzzy = False
        if not candidates:
            candidates = _fuzzy_candidates(old_path, token_index)
            fuzzy = bool(candidates)
            if fuzzy:
                print(f"  [~] Найдено по названию: {old_path} "
                      f"({len(candidates)} вариант(ов))")

        # Последняя попытка — по ID3-тегам. Сюда попадают треки, у которых
        # имя файла совсем не совпадает с записью в плейлисте.
        if not candidates and search_tags:
            candidates = _tag_candidates(old_path, tag_index, tag_title_index,
                                         base_dir, absolute, rel_base)
            if candidates:
                fuzzy = True
                print(f"  [~] Найдено по тегам: {old_path} "
                      f"({len(candidates)} вариант(ов))")

        if candidates:
            # Точные совпадения имени + найденные по названию. Пользователь
            # видит в списке все варианты: и файл из текущей раскладки,
            # и такой же трек из дискографии.
            merged = list(candidates)
            for extra in _fuzzy_candidates(old_path, token_index):
                if extra not in merged:
                    merged.append(extra)

            ordered = sorted(
                merged,
                key=lambda c: _score_candidate(old_path, c),
                reverse=True,
            )
            row.candidates = list(ordered)
            row.new_path = ordered[0]
            row.default_path = ordered[0]   # для подсветки ручного выбора
            row.fuzzy = fuzzy

            # Абсолютный путь к файлу на диске нужен для кнопки «Открыть папку»
            # и для проверки существования.
            if os.path.isabs(row.new_path.replace("/", os.sep)):
                row.found_file = row.new_path
            else:
                candidate_rel = row.new_path
                if rel_base and candidate_rel.startswith(rel_base.rstrip("/") + "/"):
                    candidate_rel = candidate_rel[len(rel_base.rstrip("/")) + 1:]
                row.found_file = os.path.normpath(
                    os.path.join(folder, candidate_rel.replace("/", os.sep))
                )

        if not row.new_path:
            print(f"  [—] Не найден: {old_path}")

        result.rows.append(row)
        offset = file_count * (2 if search_tags else 1)
        report.update(offset + position, total_steps,
                      os.path.basename(old_path))

    report.finish(result.summary)
    print(f"\n{result.summary}")
    return result


# ---------------------------------------------------------------------------
# Запись
# ---------------------------------------------------------------------------

def apply_rows(playlist_path: str, rows: List[TrackRow],
               progress=None) -> int:
    """Заменяет пути в файле плейлиста на найденные.

    Возвращает число изменённых строк. Формат файла сохраняется целиком:
    комментарии, теги и порядок строк остаются на местах.
    """
    report = as_progress(progress)
    fmt = detect_format(playlist_path)

    targets = [r for r in rows if r.new_path and not r.applied]
    if not targets:
        return 0

    report.start(len(targets), "Запись плейлиста")
    lines = read_lines(playlist_path)
    changed = 0

    for position, row in enumerate(targets, start=1):
        if row.index >= len(lines):
            continue
        line = lines[row.index]
        if not is_path_line(line, fmt):
            # Файл могли изменить между поиском и записью — пропускаем.
            print(f"  [~] Строка {row.index + 1} больше не путь, пропущена")
            continue

        lines[row.index] = replace_path(line, fmt, row.new_path)
        row.applied = True
        changed += 1
        print(f"  [+] {os.path.basename(row.old_path)} -> {row.new_path}")
        report.advance(1, os.path.basename(row.old_path))

    if changed:
        with open(playlist_path, "w", encoding="utf-8", newline="\n") as stream:
            stream.write("\n".join(lines))
            if lines and lines[-1] != "":
                stream.write("\n")

    report.finish(f"Изменено строк: {changed}")
    print(f"\n[+] Изменено строк: {changed}")
    return changed


def apply_single(playlist_path: str, row: TrackRow) -> bool:
    """Заменяет путь одной строки — для кнопки «Изменить путь»."""
    return apply_rows(playlist_path, [row]) > 0
