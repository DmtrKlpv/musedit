"""Поиск дубликатов тремя способами: SHA-256, имя файла, mp3-теги.

Логика сканирования и отчёта сохранена от исходного duplsearch.py.
Добавлено:
  * режимы сравнения — можно включить любой набор;
  * поле ``match`` у каждой группы: «SHA256», «Имя» или «Теги»;
  * группы не дублируются: если файлы уже найдены как одинаковые по
    содержимому, второй раз по имени они не показываются.

Приоритет режимов задан порядком: SHA-256 → имя → теги. Совпадение по
содержимому достовернее совпадения по имени, поэтому оно идёт первым
и «забирает» файлы себе.
"""

import os
import csv
import hashlib

from mutagen import File

from ..progress import as_progress

try:
    from tqdm import tqdm
    _HAS_TQDM = True
except Exception:
    _HAS_TQDM = False


class Colors:
    CYAN = '\033[96m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    GREEN = '\033[92m'
    BOLD = '\033[1m'
    GRAY = '\033[90m'
    END = '\033[0m'


# Режимы сравнения и их подписи для таблицы
MODE_SHA256 = "sha256"
MODE_NAME = "name"
MODE_TAGS = "tags"

# Порядок важен: чем раньше режим, тем он достовернее и тем раньше
# забирает файлы в свою группу.
MODE_ORDER = (MODE_SHA256, MODE_NAME, MODE_TAGS)

MODE_LABELS = {
    MODE_SHA256: "SHA256",
    MODE_NAME: "Имя",
    MODE_TAGS: "Теги",
}

AUDIO_EXTENSIONS = ('.mp3', '.flac', '.wav', '.m4a', '.ogg', '.ape', '.dsf', '.dff')


def _iter_with_progress(items, desc="Прогресс", unit="файл"):
    if _HAS_TQDM:
        return tqdm(items, desc=desc, unit=unit, colour="green")
    return items


def get_file_hash(path):
    hasher = hashlib.sha256()
    try:
        with open(path, 'rb') as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return None


def get_audio_info(path):
    try:
        size_bytes = os.path.getsize(path)
        size_mb = round(size_bytes / (1024 * 1024), 2)
        audio = File(path)
        bitrate = "N/A"
        if audio and audio.info and hasattr(audio.info, 'bitrate'):
            bitrate = f"{int(audio.info.bitrate / 1000)} kbps"
        return size_bytes, f"{size_mb} MB", bitrate
    except Exception:
        return 0, "N/A", "N/A"


def get_tags_key(path):
    """Ключ по ID3-тегам: исполнитель + название.

    None, если тегов нет — такие файлы в сравнение по тегам не попадают:
    иначе все файлы без тегов слиплись бы в одну «группу дубликатов».
    """
    try:
        audio = File(path, easy=True)
        if audio is None:
            return None
        artists = audio.get("artist") or []
        titles = audio.get("title") or []
        artist = str(artists[0]).strip().lower() if artists else ""
        title = str(titles[0]).strip().lower() if titles else ""
        if not artist and not title:
            return None
        return f"{artist}|{title}"
    except Exception:
        return None


def get_name_key(path):
    """Ключ по имени файла без учёта регистра и пути."""
    return os.path.basename(path).strip().lower()


# ---------------------------------------------------------------------------
# CSV: сохранение и загрузка результатов
# ---------------------------------------------------------------------------

DEFAULT_CSV_NAME = "duplicates_report.csv"

# Заголовки колонок. Импорт ищет их по имени, а не по номеру: если
# пользователь переставит столбцы в Excel, чтение не сломается.
CSV_COLUMNS = ("Название", "Папка", "Размер", "Битрейт", "Совпадение", "Группа")

# Варианты заголовка на случай правок вручную
_HEADER_ALIASES = {
    "название": ("название", "файл", "name", "filename", "файл_имя"),
    "папка": ("папка", "путь", "folder", "path", "директория"),
    "размер": ("размер", "size"),
    "битрейт": ("битрейт", "bitrate"),
    "совпадение": ("совпадение", "match", "тип"),
    "группа": ("группа", "group", "группа_id", "group_id"),
}


def _detect_delimiter(sample: str) -> str:
    """Определяет разделитель: точка с запятой или запятая."""
    first_line = sample.splitlines()[0] if sample.splitlines() else ""
    if first_line.count(";") >= first_line.count(","):
        return ";"
    return ","


def write_csv(groups, path: str) -> str:
    """Сохраняет группы дубликатов в CSV. Возвращает полный путь.

    Добавлена колонка «Группа»: без неё при импорте нельзя отличить две
    разные группы с одинаковым именем файла и одним типом совпадения —
    они слились бы в одну. Старые отчёты без этой колонки тоже читаются,
    там группы восстанавливаются по соседним строкам.
    """
    path = os.path.abspath(path)
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)

    with open(path, "w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream, delimiter=";")
        writer.writerow(CSV_COLUMNS)

        for index, group in enumerate(groups, start=1):
            match_label = group.get("match", "SHA256")
            for entry in group.get("files", []):
                writer.writerow([
                    os.path.basename(entry.get("path", "")),
                    os.path.dirname(entry.get("path", "")),
                    entry.get("size_str", "N/A"),
                    entry.get("bitrate", "N/A"),
                    match_label,
                    index,
                ])
    return path


class CsvImportError(Exception):
    """CSV не похож на отчёт о дубликатах."""


def _map_columns(header):
    """Сопоставляет заголовки файла с известными полями."""
    mapping = {}
    for position, raw in enumerate(header):
        name = (raw or "").strip().lower().replace("ё", "е")
        for field, aliases in _HEADER_ALIASES.items():
            if name in aliases:
                mapping[field] = position
                break
    return mapping


def read_csv(path: str):
    """Читает CSV с дубликатами и восстанавливает группы.

    Понимает и новые отчёты (с колонкой «Группа»), и старые без неё.
    Для старых группы собираются из подряд идущих строк с одинаковым
    именем файла и типом совпадения — именно в таком порядке их писал
    прежний экспорт.
    """
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise CsvImportError(f"Файл не найден: {path}")

    with open(path, "r", encoding="utf-8-sig", errors="replace") as stream:
        sample = stream.read()
    if not sample.strip():
        raise CsvImportError("Файл пуст.")

    delimiter = _detect_delimiter(sample)
    rows = list(csv.reader(sample.splitlines(), delimiter=delimiter))
    if not rows:
        raise CsvImportError("Не удалось прочитать ни одной строки.")

    header = rows[0]
    mapping = _map_columns(header)
    if "название" not in mapping or "папка" not in mapping:
        raise CsvImportError(
            "В файле нет колонок «Название» и «Папка». "
            "Похоже, это не отчёт о дубликатах."
        )

    data_rows = [row for row in rows[1:] if any(cell.strip() for cell in row)]
    if not data_rows:
        raise CsvImportError("В файле нет строк с файлами.")

    def cell(row, field, default=""):
        position = mapping.get(field)
        if position is None or position >= len(row):
            return default
        return row[position].strip()

    # --- сборка групп ---
    groups = []
    current = None          # (ключ, группа)
    has_group_column = "группа" in mapping

    for row in data_rows:
        filename = cell(row, "название")
        folder = cell(row, "папка")
        if not filename:
            continue

        match_label = cell(row, "совпадение") or "SHA256"
        if match_label not in ("SHA256", "Имя", "Теги"):
            match_label = "SHA256"

        group_id = cell(row, "группа") if has_group_column else ""
        key = group_id if group_id else f"{filename}\x00{match_label}"

        full_path = os.path.join(folder, filename) if folder else filename
        exists = os.path.isfile(full_path)

        # Размер и битрейт берём с диска, если файл на месте: в CSV они
        # могли устареть, а расчёт «сколько освободится» должен быть верным.
        if exists:
            size_bytes, size_str, bitrate = get_audio_info(full_path)
        else:
            size_bytes = 0
            size_str = cell(row, "размер") or "N/A"
            bitrate = cell(row, "битрейт") or "N/A"

        entry = {
            "path": full_path,
            "size_bytes": size_bytes,
            "size_str": size_str,
            "bitrate": bitrate,
            "exists": exists,
        }

        if current is None or current[0] != key:
            group = {
                "hash": hashlib.md5(
                    f"{key}:{len(groups)}".encode("utf-8", "ignore")
                ).hexdigest(),
                "filename": filename,
                "match": match_label,
                "files": [],
            }
            groups.append(group)
            current = (key, group)

        current[1]["files"].append(entry)

    # Группа из одной строки дубликатом не является
    groups = [group for group in groups if len(group["files"]) > 1]

    if not groups:
        raise CsvImportError(
            "В файле не нашлось групп с двумя и более файлами."
        )
    return groups


def _collect_files(root_path):
    found = []
    for root, _, files in os.walk(root_path):
        for file in files:
            if file.lower().endswith(AUDIO_EXTENSIONS):
                found.append(os.path.join(root, file))
    return found


def _group_by(files, key_func, report, offset, total_steps, label):
    """Группирует файлы по ключу, сообщая о прогрессе."""
    buckets = {}
    for index, path in enumerate(files, start=1):
        key = key_func(path)
        if key:
            buckets.setdefault(key, []).append(path)
        if report is not None:
            report.update(offset + index, total_steps,
                          f"{label}: {os.path.basename(path)}")
    return [paths for paths in buckets.values() if len(paths) > 1]


def find_duplicates(root_path, progress=None, on_group=None, modes=None):
    """Ищет дубликаты выбранными способами.

    modes — набор режимов из MODE_ORDER, по умолчанию только SHA-256
    (поведение прежних версий).

    Возвращает список групп:
        [{'hash', 'filename', 'match', 'files': [
            {'path', 'size_bytes', 'size_str', 'bitrate'}]}]
    где ``match`` — «SHA256», «Имя» или «Теги».
    """
    report = as_progress(progress)
    report.start(0, "Анализ папок")

    selected = [m for m in MODE_ORDER if not modes or m in modes]
    if not selected:
        selected = [MODE_SHA256]

    root_path = os.path.abspath(root_path)
    if not os.path.isdir(root_path):
        print(f"{Colors.RED}[x] Ошибка: Путь не найден.{Colors.END}")
        return []

    all_audio_files = _collect_files(root_path)

    if not all_audio_files:
        print(f"{Colors.YELLOW}Файлы не найдены.{Colors.END}")
        report.finish("Файлы не найдены")
        return []

    # Шкала прогресса: столько шагов, сколько раз придётся пройти по файлам.
    # Имя файла считается мгновенно, хеш и теги требуют чтения с диска.
    costly = [m for m in selected if m in (MODE_SHA256, MODE_TAGS)]
    total_steps = len(all_audio_files) * max(1, len(costly))
    report.start(total_steps, "Поиск дубликатов")

    key_funcs = {
        MODE_SHA256: get_file_hash,
        MODE_NAME: get_name_key,
        MODE_TAGS: get_tags_key,
    }

    candidates = []      # (mode, [paths]) в порядке приоритета
    step_offset = 0

    for mode in selected:
        label = MODE_LABELS[mode]
        print(f"{Colors.CYAN}Поиск по режиму: {label}{Colors.END}")
        groups = _group_by(all_audio_files, key_funcs[mode], report,
                           step_offset, total_steps, label)
        for paths in groups:
            candidates.append((mode, paths))
        if mode in (MODE_SHA256, MODE_TAGS):
            step_offset += len(all_audio_files)

    if not candidates:
        print(f"\n{Colors.GREEN}Дубликатов нет!{Colors.END}")
        report.finish("Дубликаты не найдены")
        return []

    total_wasted_size = 0
    groups = []
    covered = set()      # файлы, уже показанные в какой-либо группе

    print(f"\n{Colors.BOLD}{Colors.YELLOW}РЕЗУЛЬТАТЫ:{Colors.END}")
    print("=" * 60)

    report.set_total(len(candidates))

    for mode, paths in candidates:
        # Если все файлы этой группы уже показаны в более достоверной
        # группе — не дублируем: одна и та же пара не должна встречаться
        # и как «SHA256», и как «Имя».
        if all(p in covered for p in paths):
            continue

        match_label = MODE_LABELS[mode]
        filename = os.path.basename(paths[0])
        print(f"{Colors.BOLD}Файл: {Colors.CYAN}{filename}"
              f"{Colors.END} {Colors.GRAY}[{match_label}]{Colors.END}")

        group_files = []
        for i, p in enumerate(paths):
            size_bytes, size_str, bitrate = get_audio_info(p)
            folder = os.path.dirname(p)

            if i > 0:
                total_wasted_size += size_bytes

            print(f"  {folder} {Colors.GRAY}{size_str} | {bitrate}{Colors.END}")

            group_files.append({
                "path": p,
                "size_bytes": size_bytes,
                "size_str": size_str,
                "bitrate": bitrate,
            })
            covered.add(p)

        group = {
            "hash": hashlib.md5(
                (f"{match_label}:{filename}".encode("utf-8", "ignore"))
            ).hexdigest(),
            "filename": filename,
            "match": match_label,
            "files": group_files,
        }
        groups.append(group)

        if on_group is not None:
            on_group(group, len(groups))

        print(f"{Colors.GRAY}" + "-" * 40 + f"{Colors.END}")
        report.update(len(groups), max(1, len(candidates)),
                      f"Группа: {filename}")

    if not groups:
        print(f"\n{Colors.GREEN}Дубликатов нет!{Colors.END}")
        report.finish("Дубликаты не найдены")
        return []

    wasted_mb = round(total_wasted_size / (1024 * 1024), 2)
    print(f"\n{Colors.BOLD}{Colors.YELLOW}Можно освободить: "
          f"{wasted_mb} MB {Colors.END}")

    try:
        saved = write_csv(groups, DEFAULT_CSV_NAME)
        print(f"{Colors.CYAN}Отчет сохранен в: {saved}{Colors.END}")
    except Exception as e:
        print(f"{Colors.RED}[x] Ошибка записи CSV: {e}{Colors.END}")

    report.finish(f"Найдено групп: {len(groups)}")
    return groups
