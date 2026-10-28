"""Поиск дубликатов с расчетом объема и экспортом в CSV (логика duplsearch.py).

Логика сканирования и отчёта сохранена. Возвращаемое значение (список групп)
добавлено для графического представления результатов во вкладке GUI.
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


def find_duplicates(root_path, progress=None, on_group=None):
    """Возвращает группы дубликатов: [{'hash','filename','files':[{path,size,size_str,bitrate}]}]

    progress — объект прогресса для полосы в GUI.
    on_group — необязательный колбэк, вызываемый сразу после обнаружения группы,
    чтобы интерфейс наполнялся по мере сканирования, а не только в конце.
    """
    report = as_progress(progress)
    report.start(0, "Анализ папок")

    root_path = os.path.abspath(root_path)
    if not os.path.isdir(root_path):
        print(f"{Colors.RED}[x] Ошибка: Путь не найден.{Colors.END}")
        return []

    all_audio_files = []
    extensions = ('.mp3', '.flac', '.wav', '.m4a', '.ogg', '.ape', '.dsf', '.dff')

    print(f"{Colors.CYAN}Анализ папок...{Colors.END}")
    for root, _, files in os.walk(root_path):
        for file in files:
            if file.lower().endswith(extensions):
                all_audio_files.append(os.path.join(root, file))

    if not all_audio_files:
        print(f"{Colors.YELLOW}Файлы не найдены.{Colors.END}")
        report.finish("Файлы не найдены")
        return []

    files_by_hash = {}
    print(f"{Colors.CYAN}Поиск дубликатов:{Colors.END}")  # sha256
    report.start(len(all_audio_files), "Расчёт контрольных сумм")

    for index, full_path in enumerate(all_audio_files, start=1):
        f_hash = get_file_hash(full_path)
        if f_hash:
            files_by_hash.setdefault(f_hash, []).append(full_path)
        report.update(index, len(all_audio_files), os.path.basename(full_path))

    duplicates = [paths for paths in files_by_hash.values() if len(paths) > 1]
    if not duplicates:
        print(f"\n{Colors.GREEN}Дубликатов нет!{Colors.END}")
        report.finish("Дубликаты не найдены")
        return []

    total_wasted_size = 0
    csv_data = []
    groups = []

    print(f"\n{Colors.BOLD}{Colors.YELLOW}РЕЗУЛЬТАТЫ:{Colors.END}")
    print("=" * 60)

    report.set_total(len(duplicates))

    for group_index, paths in enumerate(duplicates, start=1):
        filename = os.path.basename(paths[0])
        print(f"{Colors.BOLD}Файл: {Colors.CYAN}{filename}{Colors.END}")

        # Инфо о первом файле (оригинал для расчета)
        orig_size_bytes, _, _ = get_audio_info(paths[0])

        group_files = []
        for i, p in enumerate(paths):
            size_bytes, size_str, bitrate = get_audio_info(p)
            folder = os.path.dirname(p)

            # Если это не первый файл в группе, считаем его "мусором"
            if i > 0:
                total_wasted_size += size_bytes

            print(f"  {folder} {Colors.GRAY}{size_str} | {bitrate}{Colors.END}")

            csv_data.append([filename, folder, size_str, bitrate])
            group_files.append({
                "path": p,
                "size_bytes": size_bytes,
                "size_str": size_str,
                "bitrate": bitrate,
            })

        group = {
            "hash": hashlib.md5(filename.encode("utf-8", "ignore")).hexdigest(),
            "filename": filename,
            "files": group_files,
        }
        groups.append(group)

        if on_group is not None:
            on_group(group, len(groups))

        print(f"{Colors.GRAY}" + "-" * 40 + f"{Colors.END}")
        report.update(group_index, len(duplicates), f"Группа: {filename}")

    # Итоги
    wasted_mb = round(total_wasted_size / (1024 * 1024), 2)
    print(f"\n{Colors.BOLD}{Colors.YELLOW}Можно освободить: {wasted_mb} MB {Colors.END}")

    # Сохранение в CSV
    csv_file = "duplicates_report.csv"
    try:
        with open(csv_file, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f, delimiter=';')
            writer.writerow(['Название', 'Папка', 'Размер', 'Битрейт'])
            writer.writerows(csv_data)
        print(f"{Colors.CYAN}Отчет сохранен в: {os.path.abspath(csv_file)}{Colors.END}")
    except Exception as e:
        print(f"{Colors.RED}[x] Ошибка записи CSV: {e}{Colors.END}")

    report.finish(f"Найдено групп: {len(groups)}")
    return groups
