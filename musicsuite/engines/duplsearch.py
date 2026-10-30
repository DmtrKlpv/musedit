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
    csv_data = []
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

            csv_data.append([filename, folder, size_str, bitrate, match_label])
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

    csv_file = "duplicates_report.csv"
    try:
        with open(csv_file, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f, delimiter=';')
            writer.writerow(['Название', 'Папка', 'Размер', 'Битрейт', 'Совпадение'])
            writer.writerows(csv_data)
        print(f"{Colors.CYAN}Отчет сохранен в: "
              f"{os.path.abspath(csv_file)}{Colors.END}")
    except Exception as e:
        print(f"{Colors.RED}[x] Ошибка записи CSV: {e}{Colors.END}")

    report.finish(f"Найдено групп: {len(groups)}")
    return groups
