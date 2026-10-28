"""Исправление тегов MP3: восстановление повреждённых кодировок (UTF-8, CP1251, KOI8-R, CP866).

Логика исходного fixtags.py сохранена: тот же обход папки, тот же набор ID3-кадров,
то же сохранение с ``v1=0, v2_version=4`` и тот же режим DRY-RUN.

Что добавлено по сравнению с исходником
---------------------------------------
Исходный ``fix_mojibake`` вслепую выполнял ``text.encode('latin-1').decode('cp1251')``
и принимал результат, если в нём появлялась хотя бы одна кириллическая буква. Из-за
этого корректные названия портились:

    'Vallée De Larmes'    -> 'Vallйe De Larmes'      (é -> й)
    'Düsseldorf, Germany' -> 'Dьsseldorf, Germany'   (ü -> ь)

Здесь вместо эвристики «появилась кириллица — значит починили» используется
попереборный детектор: для каждого слова подбирается такая пара кодировок
(encode -> decode), которая даёт *правдоподобный* текст, а корректные слова
не трогаются вообще. Дополнительно поддерживается ремонт UTF-8, ошибочно
прочитанного как CP1251/KOI8-R/CP866 (частый случай у старых рипперов).
"""

from __future__ import annotations

import math
import os
import re
import unicodedata
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from mutagen.id3 import Encoding
from mutagen.mp3 import MP3

from ..progress import as_progress


class Colors:
    """ANSI-коды для тех же сообщений, что были в исходном CLI-скрипте."""

    GREEN, RED, YELLOW, CYAN, GRAY, BOLD, END = (
        '\033[92m', '\033[91m', '\033[93m', '\033[96m', '\033[90m', '\033[1m', '\033[0m'
    )

# Словарь для перевода ID кодов в понятные названия
FRAME_NAMES = {
    "TIT2": "Title", "TPE1": "Artist", "TPE2": "Album Artist",
    "TALB": "Album", "TDRC": "Year", "TRCK": "Track",
    "TCON": "Genre", "COMM": "Comment", "USLT": "Lyrics",
    "TCOM": "Composer", "TPOS": "Disc", "TPUB": "Publisher",
    "TORY": "Original Year", "TSOP": "Sort Artist", "TSO2": "Sort Album Artist",
    "TSOA": "Sort Album", "TSOT": "Sort Title"
}

# Русские названия для таблицы в интерфейсе
FRAME_NAMES_RU = {
    "TIT2": "Название", "TPE1": "Исполнитель", "TPE2": "Альбомный исполнитель",
    "TALB": "Альбом", "TDRC": "Год", "TRCK": "Трек",
    "TCON": "Жанр", "COMM": "Комментарий", "USLT": "Текст песни",
    "TCOM": "Композитор", "TPOS": "Диск", "TPUB": "Издатель",
    "TORY": "Оригинальный год", "TSOP": "Сорт. исполнитель",
    "TSO2": "Сорт. альбомный исполнитель", "TSOA": "Сорт. альбом",
    "TSOT": "Сорт. название"
}

# ---------------------------------------------------------------------------
# Классификация символов
# ---------------------------------------------------------------------------

_LATIN = lambda c: "A" <= c <= "Z" or "a" <= c <= "z"
_CYRILLIC = lambda c: "\u0400" <= c <= "\u04ff"
_LATIN1 = lambda c: "\u00c0" <= c <= "\u00ff"

# Пунктуация, допустимая в «нормальном» теге
_ALLOWED_PUNCT = set(
    " \t-–—_'\u2019\"\u201c\u201d\u201e\u00ab\u00bb.,:;!?()[]{}/\\+*&=#@%$~^_|<>\n\r"
)

# Символ, встречающийся в UTF-8-тексте, прочитанном как однобайтовая кодировка
_UTF8_MARKERS = (
    "\u00c3\u00c2\u00d0\u00d1\u00c5\u00e2\u00e3\u00e4"
    "\u00a9\u00ae\u0403\u0453\u0490\u0452\u20ac\u2122\u0161\u017e\u0178"
)

_ENCODINGS = (
    "utf-8", "cp1251", "cp1252", "latin-1",
    "koi8-r", "cp866", "iso-8859-15", "cp437", "mac_cyrillic",
)


def _is_junk(ch: str) -> bool:
    """Символ, которого не должно быть в нормальном теге."""
    if ch.isalnum():
        return False
    if ch in _ALLOWED_PUNCT:
        return False
    code = ord(ch)
    if code == 0xFFFD or code < 0x20 or 0xE000 <= code <= 0xF8FF:
        return True
    # Pf — закрывающие кавычки, остальные категории символов считаем мусором
    return unicodedata.category(ch) != "Pf"


def _counts(text: str) -> Tuple[int, int, int, int]:
    """(латиница, кириллица, latin-1, мусор)"""
    return (
        sum(1 for c in text if _LATIN(c)),
        sum(1 for c in text if _CYRILLIC(c)),
        sum(1 for c in text if _LATIN1(c)),
        sum(1 for c in text if _is_junk(c)),
    )


def _is_clean(text: str) -> bool:
    """Текст выглядит нормально: без мусора и без смешения алфавитов."""
    if not text:
        return False
    latin, cyr, latin1, junk = _counts(text)
    if junk:
        return False
    if latin and cyr:
        return False
    if cyr and latin1:
        return False
    if latin1 >= 2 and not latin and not cyr:
        return False
    return True


def _accent_heavy(text: str) -> bool:
    """Слишком много latin-1 «акцентов» — типичный признак кракозябр."""
    latin, _cyr, latin1, _junk = _counts(text)
    total = latin + latin1
    return total > 0 and latin1 / total > 0.35


def _try(text: str, src: str, dst: str) -> Optional[str]:
    try:
        return text.encode(src).decode(dst)
    except (UnicodeEncodeError, UnicodeDecodeError, LookupError):
        return None


def _looks_utf8_as_cyrillic(text: str) -> bool:
    """'РџСЂРёРІРµС‚' — UTF-8, прочитанный как CP1251."""
    cyr = [c for c in text if _CYRILLIC(c)]
    if len(cyr) < 4:
        return False
    upper = sum(1 for c in cyr if c in "\u0420\u0421")
    return upper >= 2 and upper / len(cyr) >= 0.2


def _odd_case(text: str) -> bool:
    """Заглавная буква в середине слова — след перекодировки."""
    for word in re.findall(r"\S+", text):
        cyr = [c for c in word if _CYRILLIC(c)]
        if not cyr:
            continue
        if all(c.isupper() for c in cyr) or all(c.islower() for c in cyr):
            continue
        if any(c.isupper() for c in cyr[1:]):
            return True
    return False


# ---------------------------------------------------------------------------
# Языковая модель русского языка (используется только как тай-брейкер
# между двумя вариантами «кириллица против кириллицы»)
# ---------------------------------------------------------------------------

_RU_FREQ = {
    "о": 10.97, "е": 8.45, "а": 8.01, "и": 7.35, "н": 6.70, "т": 6.26, "с": 5.47,
    "р": 4.73, "в": 4.54, "л": 4.40, "к": 3.49, "м": 3.21, "д": 2.98, "п": 2.81,
    "у": 2.62, "я": 2.01, "ы": 1.90, "ь": 1.74, "г": 1.70, "з": 1.65, "б": 1.59,
    "ч": 1.44, "й": 1.21, "х": 0.97, "ж": 0.94, "ш": 0.73, "ю": 0.64, "ц": 0.48,
    "щ": 0.36, "э": 0.32, "ф": 0.26, "ъ": 0.04, "ё": 0.04,
}
_RU_BIGRAMS = set(
    "ст но то на ен ов ни ра во ко пр ро ос по ре го не ал ли ка ер та от ле ль "
    "ор те ан ом ес ин ят ет ва ел ат ит ла ил ьн ты ьс ая ой ий".split()
)


def _russian_quality(text: str) -> float:
    letters = [c.lower() for c in text if _CYRILLIC(c)]
    if len(letters) < 3:
        return 0.0
    score = sum(math.log(_RU_FREQ[c] / 100.0) if c in _RU_FREQ else -5.0 for c in letters)
    score += 1.5 * sum(1 for a, b in zip(letters, letters[1:]) if (a + b) in _RU_BIGRAMS)
    score -= 1.5 * sum(1 for c in letters if c in "ъыьэщю")
    for word in re.findall(r"\S+", text):
        cyr = [c for c in word if _CYRILLIC(c)]
        if cyr and not all(c.isupper() for c in cyr):
            score -= 2.0 * sum(1 for c in cyr[1:] if c.isupper())
    return score / max(1, len(letters))


# ---------------------------------------------------------------------------
# Ремонт одного слова
# ---------------------------------------------------------------------------

def repair_token(token: str) -> Optional[str]:
    """Возвращает исправленное слово либо None, если слово уже в порядке."""
    latin, cyr, latin1, junk = _counts(token)
    damaged = (
        junk > 0
        or not _is_clean(token)
        or _looks_utf8_as_cyrillic(token)
        or _odd_case(token)
    )
    if not damaged and not any(c in _UTF8_MARKERS for c in token):
        return None

    # 1. UTF-8, прочитанный как однобайтовая кодировка
    if junk or any(c in _UTF8_MARKERS for c in token) or _looks_utf8_as_cyrillic(token):
        for src in ("cp1252", "latin-1", "cp1251", "iso-8859-15", "cp866", "cp437"):
            cand = _try(token, src, "utf-8")
            if (
                cand
                and cand != token
                and _is_clean(cand)
                and not _looks_utf8_as_cyrillic(cand)
                and not _accent_heavy(cand)
            ):
                return cand

    # 2. Западная кодировка, прочитанная как CP1251 ('Ïåñíÿ' -> 'Песня')
    if latin1 and not latin and not cyr:
        for src in ("latin-1", "cp1252"):
            cand = _try(token, src, "cp1251")
            if cand and _is_clean(cand) and _counts(cand)[1] > 0:
                return cand

    # 3. CP1251, прочитанная как западная ('Vallйe' -> 'Vallée')
    #    Принимаем только если результат не превращается в акцентную кашу —
    #    иначе пострадают реальные названия вроде 'Zемфира' или 'Björk'.
    if cyr and latin:
        for dst in ("cp1252", "latin-1", "iso-8859-15"):
            cand = _try(token, "cp1251", dst)
            if (
                cand
                and cand != token
                and _is_clean(cand)
                and _counts(cand)[0] > 0
                and not _accent_heavy(cand)
            ):
                return cand

    # 4. Перепутанные кириллические кодировки — по языковой модели
    if cyr and damaged:
        base = _russian_quality(token)
        best: Optional[Tuple[float, str]] = None
        for src, dst in (
            ("cp1251", "koi8-r"), ("koi8-r", "cp1251"),
            ("cp866", "cp1251"), ("cp1251", "cp866"),
            ("koi8-r", "cp866"), ("cp866", "koi8-r"),
        ):
            cand = _try(token, src, dst)
            if cand and cand != token and _is_clean(cand) and _counts(cand)[1] > 0:
                quality = _russian_quality(cand)
                if quality > base + 0.5 and (best is None or quality > best[0]):
                    best = (quality, cand)
        if best:
            return best[1]

    return None


_WORD_RE = re.compile(r"(\s+)")


def repair_text(text: str, depth: int = 3) -> str:
    """Чинит повреждённые слова в строке, не трогая корректные."""
    if not isinstance(text, str) or not text.strip():
        return text
    parts: List[str] = []
    for chunk in _WORD_RE.split(text):
        if not chunk or chunk.isspace():
            parts.append(chunk)
            continue
        current = chunk
        for _ in range(depth):
            nxt = repair_token(current)
            if not nxt or nxt == current:
                break
            current = nxt
        parts.append(current)
    return "".join(parts)


def needs_repair(text: str) -> bool:
    """Есть ли что исправлять (без выполнения самого ремонта)."""
    return isinstance(text, str) and bool(text.strip()) and repair_text(text) != text


def fix_mojibake(text: str) -> str:
    """Совместимость с исходным API: возвращает исправленную строку."""
    return repair_text(text)


# ---------------------------------------------------------------------------
# Элемент списка правок
# ---------------------------------------------------------------------------

@dataclass
class FixItem:
    """Одна предлагаемая правка: одно поле одного файла."""

    filepath: str
    frame_id: str          # например TIT2
    frame_key: str         # HashKey кадра, например 'COMM::eng'
    text_index: int        # индекс значения внутри кадра
    field_name: str        # 'Title'
    field_name_ru: str     # 'Название'
    old_text: str
    new_text: str
    applied: bool = False

    @property
    def filename(self) -> str:
        return os.path.basename(self.filepath)

    @property
    def display_field(self) -> str:
        return self.field_name_ru or FRAME_NAMES_RU.get(self.frame_id, self.frame_id)


def _frame_hash_key(frame_id: str, frame) -> str:
    """HashKey кадра — по нему кадр можно найти при повторном открытии файла."""
    key = getattr(frame, "HashKey", None)
    if isinstance(key, str) and key:
        return key
    return frame_id


def _iter_text_values(frame) -> List[Tuple[int, str]]:
    """Все текстовые значения кадра с их индексами."""
    text = getattr(frame, "text", None)
    if text is None:
        return []
    if isinstance(text, str):
        return [(0, text)] if text else []
    out: List[Tuple[int, str]] = []
    try:
        for index, value in enumerate(text):
            if isinstance(value, str):
                out.append((index, value))
            else:
                out.append((index, str(value)))
    except TypeError:
        return []
    return out


def _write_text_value(frame, index: int, value: str) -> None:
    """Записывает новое значение в кадр (учитывая str и list)."""
    current = getattr(frame, "text", None)
    if isinstance(current, str):
        frame.text = value
        return
    values = list(current)
    if index < len(values):
        values[index] = value
    else:
        values.append(value)
    frame.text = values


# ---------------------------------------------------------------------------
# Сканирование
# ---------------------------------------------------------------------------

def collect_file(filepath: str) -> Tuple[List[FixItem], Optional[str]]:
    """Возвращает (список правок, текст ошибки) для одного файла."""
    try:
        audio = MP3(filepath)
    except Exception as exc:  # noqa: BLE001 — повреждённый файл не должен ломать скан
        return [], f"{os.path.basename(filepath)}: {exc}"

    if audio.tags is None:
        return [], None

    items: List[FixItem] = []
    try:
        frames = list(audio.tags.items())
    except Exception as exc:  # noqa: BLE001
        return [], f"{os.path.basename(filepath)}: {exc}"

    for frame_id, frame in frames:
        for index, value in _iter_text_values(frame):
            if not value.strip():
                continue
            repaired = repair_text(value)
            if repaired == value:
                continue
            items.append(
                FixItem(
                    filepath=filepath,
                    frame_id=frame_id.split(":")[0] if ":" in frame_id else frame_id,
                    frame_key=_frame_hash_key(frame_id, frame),
                    text_index=index,
                    field_name=FRAME_NAMES.get(frame_id.split(":")[0], frame_id),
                    field_name_ru=FRAME_NAMES_RU.get(frame_id.split(":")[0], frame_id),
                    old_text=value,
                    new_text=repaired,
                )
            )
    return items, None


def scan_directory(directory: str, ext: str = ".mp3", progress=None) -> List[FixItem]:
    """Обходит папку и собирает все предлагаемые правки.

    progress — необязательный объект с методами start/advance/message
    (см. musicsuite.progress) либо любой совместимый. Если он не передан,
    функция ведёт себя ровно как в исходном CLI-скрипте.
    """
    if not os.path.isdir(directory):
        print(f"Error: Folder not found: {directory}")
        return []

    print(f"Search for {ext} in: {directory}")
    items: List[FixItem] = []
    processed = 0

    # Предварительный проход: нужен, чтобы полоса прогресса знала общее число
    # файлов. Обход дерева дешёвый по сравнению с чтением ID3-тегов.
    pending: List[str] = []
    for root, _, files in os.walk(directory):
        for name in files:
            if name.lower().endswith(ext):
                pending.append(os.path.join(root, name))

    total = len(pending)
    report = as_progress(progress)
    report.start(total, "Сканирование тегов")

    for path in pending:
        processed += 1
        name = os.path.basename(path)
        report.advance(1, name)
        file_items, error = collect_file(path)
        if error:
            print(f"  Error in {error}")
            continue
        # Найденные правки НЕ печатаем построчно: они и так видны в таблице
        # вкладки. Раньше консоль забивалась списком файлов, и в ней
        # терялись настоящие ошибки.
        items.extend(file_items)

    report.finish(f"Проверено файлов: {processed}")
    print(f"{Colors.GREEN}[+] Сканирование завершено:{Colors.END} "
          f"файлов {processed}, найдено правок {len(items)}")
    return items


# ---------------------------------------------------------------------------
# Применение правок
# ---------------------------------------------------------------------------

def apply_item(item: FixItem, save: bool = True) -> bool:
    """Применяет одну правку к файлу. Возвращает True при успехе."""
    try:
        audio = MP3(item.filepath)
    except Exception as exc:  # noqa: BLE001
        print(f"  Error opening {os.path.basename(item.filepath)}: {exc}")
        return False

    if audio.tags is None:
        print(f"  No tags in {os.path.basename(item.filepath)}")
        return False

    frame = audio.tags.get(item.frame_key)
    if frame is None:
        frame = audio.tags.get(item.frame_id)
    if frame is None:
        print(f"  Frame {item.frame_key} not found in {os.path.basename(item.filepath)}")
        return False

    _write_text_value(frame, item.text_index, item.new_text)
    try:
        frame.encoding = Encoding.UTF8
    except Exception:  # noqa: BLE001 — не все кадры допускают смену кодировки
        pass

    if not save:
        item.applied = True
        return True

    try:
        audio.tags.save(item.filepath, v1=0, v2_version=4)
    except Exception as exc:  # noqa: BLE001
        print(f"  Error saving {os.path.basename(item.filepath)}: {exc}")
        return False

    item.applied = True
    return True


def apply_items(items: Sequence[FixItem], progress=None) -> int:
    """Применяет пачку правок. Возвращает число успешно сохранённых файлов."""
    by_file: dict = {}
    for item in items:
        by_file.setdefault(item.filepath, []).append(item)

    saved = 0
    total = len(by_file)
    for index, (filepath, file_items) in enumerate(by_file.items(), start=1):
        if progress is not None:
            progress(index, total, os.path.basename(filepath))
        try:
            audio = MP3(filepath)
        except Exception as exc:  # noqa: BLE001
            print(f"  Error in {os.path.basename(filepath)}: {exc}")
            continue
        if audio.tags is None:
            continue

        changed = 0
        for item in file_items:
            frame = audio.tags.get(item.frame_key) or audio.tags.get(item.frame_id)
            if frame is None:
                continue
            _write_text_value(frame, item.text_index, item.new_text)
            try:
                frame.encoding = Encoding.UTF8
            except Exception:  # noqa: BLE001
                pass
            item.applied = True
            changed += 1

        if not changed:
            continue
        try:
            audio.tags.save(filepath, v1=0, v2_version=4)
            saved += 1
            print(f"  Saved ({changed} changes): {os.path.basename(filepath)}")
        except Exception as exc:  # noqa: BLE001
            print(f"  Error saving {os.path.basename(filepath)}: {exc}")
    return saved


# ---------------------------------------------------------------------------
# Совместимость с исходным fixtags.py (CLI-режим и прямой вызов из tab)
# ---------------------------------------------------------------------------

def process_file(filepath: str, dry_run: bool = False, ext: str = ".mp3") -> bool:
    """Обрабатывает один файл. Возвращает True, если были изменения."""
    items, error = collect_file(filepath)
    if error:
        print(f"  {error}")
        return False
    if not items:
        return False

    print(f"File: {os.path.basename(filepath)}")
    for item in items:
        print(f"  {item.field_name}: '{item.old_text}' -> '{item.new_text}'")

    if dry_run:
        print(f"  [DRY-RUN] Will save ({len(items)} changes)\n")
        return True

    if apply_items(items):
        print(f"  Saved ({len(items)} changes)\n")
        return True
    print()
    return False


def main(directory: str, dry_run: bool = False, ext: str = ".mp3") -> List[FixItem]:
    """Аналог main() исходного fixtags.py с параметрами из GUI."""
    if not os.path.isdir(directory):
        print(f"Error: Folder not found: {directory}")
        return []

    print(f"Search for {ext} in: {directory}")
    mode = "DRY-RUN (view only)" if dry_run else "WRITE (apply fixes)"
    print(f"Mode: {mode}\n")

    items = scan_directory(directory, ext)
    if dry_run or not items:
        print(f"Done! Proposed: {len(items)} fixes (nothing written)")
        return items

    saved = apply_items(items)
    print(f"Done! Files updated: {saved}, fixes applied: {len(items)}")
    return items
