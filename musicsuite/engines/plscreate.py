"""Создание плейлистов (логика plscreate.py без изменений).

Аргументы передаются объектом-совместимым с argparse.Namespace,
поэтому main() работает ровно как в исходнике.
"""

import os
import re
import sys
import argparse
import xml.etree.ElementTree as ET
from xml.dom import minidom

from ..progress import as_progress


class Colors:
    GREEN, RED, YELLOW, CYAN, GRAY, BOLD, END = (
        '\033[92m', '\033[91m', '\033[93m', '\033[96m', '\033[90m', '\033[1m', '\033[0m'
    )


def get_args():
    parser = argparse.ArgumentParser(
        description="Утилита для создания плейлистов, совместимых с Navidrome."
    )
    parser.add_argument("path", nargs="?", help="Путь к музыке (откуда брать папки)")
    parser.add_argument(
        "-f", "--format",
        choices=["m3u", "m3u8", "pls", "xspf", "wpl"],
        help="Формат плейлиста"
    )
    parser.add_argument("-savedir", help="Папка для сохранения плейлистов")
    parser.add_argument("-list", "--from-list", help="Создать плейлист из текстового файла")
    parser.add_argument("-mass", help="Путь к папке с TXT-файлами для массового создания плейлистов")
    parser.add_argument("-searchdir", help="Папка для поиска треков (используется с -list или -mass)")
    parser.add_argument("-abs", "--absolute", action="store_true",
                        help="Использовать абсолютные пути в плейлисте")
    parser.add_argument("-rel", "--relative-base",
                        help="Базовый путь для относительных ссылок (например: '/music').")
    parser.add_argument("-name", "--use-folder-name", action="store_true",
                        help="Записать имя папки в заголовок плейлиста")
    return parser.parse_args()


def normalize_name(name):
    """Очистка имени: убирает расширение, пунктуацию и лишние пробелы"""
    name = os.path.splitext(name)[0]
    name = re.sub(r'[^\w\s]', ' ', name)
    return " ".join(name.lower().split())


def choose_format():
    formats = {"1": "m3u", "2": "m3u8", "3": "pls", "4": "xspf", "5": "wpl"}
    print("Выберите формат:\n"
          "1. M3U\n2. M3U8\n3. PLS\n4. XSPF\n5. WPL")
    return formats.get(input("Введите номер: ").strip(), "m3u8")


def format_path(full_path, base_dir=None, absolute=False, rel_base=None):
    """Форматирует путь согласно настройкам.

    Для Navidrome: если указан -rel /music, пути будут начинаться с /music/...
    Порядок правил важен:

      1. absolute — отдаём полный путь как есть;
      2. rel_base — путь ОТНОСИТЕЛЬНО base_dir, с префиксом спереди;
      3. иначе — относительный путь от base_dir.

    Раньше префикс искался как подстрока в пути, и на папке вида
    ``D:/prj/music_suite/M1`` префикс ``/music`` находился внутри слова
    ``music_suite`` — получалось ``/music_suite/M1/...`` вместо
    ``/music/m1/...``. Подстрочный поиск оставлен только для случая,
    когда base_dir неизвестен, и теперь требует границу пути.
    """
    path = full_path.replace('\\', '/')

    if absolute:
        return path

    if rel_base:
        rel_base_norm = rel_base.replace('\\', '/').rstrip('/') or '/'

        # Основной путь: считаем от базовой папки. Именно это ожидает
        # пользователь, задавая префикс вроде /music.
        if base_dir:
            try:
                relative = os.path.relpath(full_path, base_dir).replace('\\', '/')
            except ValueError:
                relative = os.path.basename(full_path)
            if relative.startswith('./'):
                relative = relative[2:]
            if relative.startswith('../'):
                # Файл вне base_dir: отдаём имя, чтобы не писать ../..
                relative = os.path.basename(full_path)
            result = f"{rel_base_norm}/{relative}"
            return re.sub(r'/+', '/', result)

        # base_dir не задан — ищем префикс в пути, но только как
        # отдельный сегмент: /music/ или /music в конце.
        pattern = re.compile(
            re.escape(rel_base_norm) + r'(?=/|$)', re.IGNORECASE
        )
        match = pattern.search(path)
        if match:
            tail = path[match.end():]
            return re.sub(r'/+', '/', rel_base_norm + tail)

        print(f"{Colors.YELLOW}⚠ Префикс '{rel_base}' не найден в пути: {path}{Colors.END}")
        return path

    if base_dir:
        try:
            return os.path.relpath(full_path, base_dir).replace('\\', '/')
        except ValueError:
            pass
    return path


def normalize_track_path(path):
    """Нормализует путь трека для сравнения: заменяет слэши, приводит к нижнему регистру, убирает \\r"""
    return path.replace('\\', '/').lower().strip().rstrip('\r\n')


def read_playlist_tracks(playlist_path, ext):
    """
    Читает существующий плейлист и возвращает список нормализованных путей треков.
    Поддерживает: m3u, m3u8, pls, xspf, wpl
    """
    if not os.path.exists(playlist_path):
        return None

    tracks = []
    try:
        if ext in ['m3u', 'm3u8']:
            enc = 'utf-8' if ext == 'm3u8' else 'utf-8'
            with open(playlist_path, 'r', encoding=enc, errors='replace') as f:
                for line in f:
                    line = line.strip().rstrip('\r\n')
                    if line and not line.startswith('#'):
                        tracks.append(normalize_track_path(line))

        elif ext == 'pls':
            with open(playlist_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip().rstrip('\r\n')
                    if line.lower().startswith('file'):
                        _, path = line.split('=', 1)
                        tracks.append(normalize_track_path(path))

        elif ext in ['xspf', 'wpl']:
            tree = ET.parse(playlist_path)
            root = tree.getroot()
            if ext == 'xspf':
                for loc in root.iter('{http://xspf.org}location'):
                    if loc.text:
                        tracks.append(normalize_track_path(loc.text))
            else:
                for media in root.iter('media'):
                    src = media.get('src')
                    if src:
                        tracks.append(normalize_track_path(src))

        return sorted(tracks)
    except Exception:
        return None


def save_playlist(path, tracks, ext, name, use_folder_name=False, force=False):
    """
    Сохраняет плейлист в указанный формат.
    Критично для Navidrome: UTF-8 без BOM, Unix-переносы, стандартный #EXTM3U.
    """
    if not tracks:
        return

    # Нормализуем новые треки для сравнения
    new_tracks = sorted([normalize_track_path(t) for t in tracks])

    # Если плейлист уже существует — проверяем, изменилось ли содержимое
    if os.path.exists(path) and not force:
        old_tracks = read_playlist_tracks(path, ext)
        if old_tracks is not None and old_tracks == new_tracks:
            print(f"{Colors.YELLOW}[~] Пропущен:{Colors.END} {os.path.basename(path)} "
                  f"(содержимое не изменилось)")
            return
        else:
            print(f"{Colors.CYAN}[!] Обновление:{Colors.END} {os.path.basename(path)} "
                  f"(изменения обнаружены)")

    # Имя для заголовка: используем имя папки только если указан флаг -name
    pl_name = name if use_folder_name else None

    try:
        if ext in ['m3u', 'm3u8']:
            # 🔧 КРИТИЧНО: чистый UTF-8 без BOM + Unix-переносы
            with open(path, 'w', encoding='utf-8', newline='\n', errors='replace') as f:
                # ✅ СТРОГО стандарт: #EXTM3U без суффикса!
                f.write("#EXTM3U\n")

                # ✅ Пишем треки: сохраняем пути КАК ЕСТЬ (с /music/ если есть)
                for track in tracks:
                    # Гарантируем чистоту: только прямые слеши, без \r, без лишних пробелов
                    clean = track.replace('\\', '/').rstrip('\r\n').strip()
                    if clean:  # пропускаем пустые строки
                        f.write(f"{clean}\n")

        elif ext == 'pls':
            with open(path, 'w', encoding='utf-8', newline='\n') as f:
                f.write("[playlist]\n")
                if pl_name:
                    f.write(f"PlaylistName={pl_name}\n")
                for i, t in enumerate(tracks, 1):
                    f.write(f"File{i}={t}\nTitle{i}={os.path.basename(t)}\n")
                f.write(f"NumberOfEntries={len(tracks)}\nVersion=2\n")

        elif ext == 'xspf':
            root_el = ET.Element("playlist", version="1", xmlns="http://xspf.org")
            if pl_name:
                ET.SubElement(root_el, "title").text = pl_name
            tl = ET.SubElement(root_el, "trackList")
            for t in tracks:
                ET.SubElement(ET.SubElement(tl, "track"), "location").text = t
            with open(path, 'w', encoding='utf-8', newline='\n') as f:
                f.write(minidom.parseString(ET.tostring(root_el)).toprettyxml(indent="  "))

        elif ext == 'wpl':
            root_el = ET.Element("smil")
            h = ET.SubElement(root_el, "head")
            if pl_name:
                ET.SubElement(h, "title").text = pl_name
            seq = ET.SubElement(ET.SubElement(root_el, "body"), "seq")
            for t in tracks:
                ET.SubElement(seq, "media", src=t)
            with open(path, 'w', encoding='utf-8', newline='\n') as f:
                f.write(minidom.parseString(ET.tostring(root_el)).toprettyxml(indent="  "))

        print(f"{Colors.GREEN}[+] Создан:{Colors.END} {os.path.basename(path)} ({len(tracks)} треков)")

    except Exception as e:
        print(f"{Colors.RED}[x] Ошибка записи: {e}{Colors.END}")


def find_match(query, db):
    """Улучшенный поиск: точное совпадение -> вхождение -> пословный поиск"""
    q_n = normalize_name(query)
    for n, p in db:
        if q_n == n or q_n in n or n in q_n:
            return p
    words = [w for w in q_n.split() if len(w) > 1]
    if not words:
        return None
    for n, p in db:
        if all(word in n for word in words):
            return p
    return None


def process_list(list_file, db, ext, save_dir, absolute, rel_base=None,
                 use_folder_name=False, progress=None):
    if not os.path.exists(list_file):
        print(f"[x] Файл не найден: {list_file}")
        return 0

    with open(list_file, 'r', encoding='utf-8') as f:
        queries = [l.strip() for l in f if l.strip()]

    found = []
    for q in queries:
        match = find_match(q, db)
        if match:
            found.append(match)
        else:
            print(f"    — Не найден: {q}")
        if progress is not None:
            progress.detail(f"Сопоставление: {q[:60]}")

    pl_base = os.path.splitext(os.path.basename(list_file))[0]
    save_playlist(os.path.join(save_dir, f"{pl_base}.{ext}"), found, ext, pl_base, use_folder_name)
    return len(found)


def main(args, progress=None):
    """Полный аналог main() исходного plscreate.py, но с готовым namespace."""
    report = as_progress(progress)
    report.start(0, "Подготовка")

    ext = args.format or choose_format()
    music_exts = ('.mp3', '.flac', '.wav', '.m4a', '.ogg', '.ape', '.dsf', '.dff')

    if args.from_list or args.mass:
        s_dir = os.path.abspath(args.searchdir or os.getcwd())
        save_dir = os.path.abspath(args.savedir or s_dir)
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)

        print(f"Индексация файлов в {s_dir}...")
        report.message(f"Индексация папки {s_dir}")

        db = []
        for r, _, fs in os.walk(s_dir):
            for f in fs:
                if f.lower().endswith(music_exts):
                    full_p = os.path.join(r, f)
                    path_to_save = format_path(full_p, base_dir=s_dir,
                                               absolute=args.absolute, rel_base=args.relative_base)
                    db.append((normalize_name(f), path_to_save))

        report.message(f"Проиндексировано файлов: {len(db)}")

        if args.mass:
            mass_path = os.path.abspath(args.mass)
            if not os.path.isdir(mass_path):
                print(f"[x] Папка не найдена: {mass_path}")
                sys.exit(1)

            txt_files = [os.path.join(mass_path, f) for f in os.listdir(mass_path)
                         if f.lower().endswith('.txt')]
            report.set_total(len(txt_files))
            created = 0
            for index, txt in enumerate(txt_files, start=1):
                print("-" * 40)
                print(f"Обработка: {os.path.basename(txt)}")
                report.update(index - 1, len(txt_files), os.path.basename(txt))
                created += process_list(txt, db, ext, save_dir, args.absolute,
                                        args.relative_base, args.use_folder_name,
                                        progress=report)
            report.finish(f"Обработано TXT-файлов: {len(txt_files)}")
            return {"created": created, "lists": len(txt_files)}
        else:
            created = process_list(args.from_list, db, ext, save_dir, args.absolute,
                                   args.relative_base, args.use_folder_name,
                                   progress=report)
            report.finish("Плейлист создан")
            return {"created": created, "lists": 1}

    else:
        raw_p = args.path or args.savedir or ""
        if not raw_p:
            raise ValueError("Укажите папку с музыкой.")
        root_dir = os.path.abspath(raw_p)
        save_dir = os.path.abspath(args.savedir or root_dir)

        if not os.path.isdir(root_dir):
            print("[x] Путь не найден.")
            sys.exit(1)
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)

        # Подпапки первого уровня — по одной на плейлист.
        subdirs = [entry for entry in os.scandir(root_dir)
                   if entry.is_dir() and os.path.abspath(entry.path) != save_dir]

        # Если подпапок нет, а музыка лежит прямо в указанной папке,
        # создаём ОДИН плейлист по её имени. Раньше такой случай молча
        # давал «Создано плейлистов: 0» — цикл по пустому списку subdirs.
        flat_tracks = []
        if not subdirs:
            for r, _, fs in os.walk(root_dir):
                if os.path.abspath(r).startswith(os.path.abspath(save_dir)):
                    continue
                for f in fs:
                    if f.lower().endswith(music_exts):
                        full_p = os.path.join(r, f)
                        track_path = format_path(full_p, base_dir=root_dir,
                                                 absolute=args.absolute,
                                                 rel_base=args.relative_base)
                        flat_tracks.append(track_path.replace('\\', '/'))
            flat_tracks.sort()

        total_units = len(subdirs) if subdirs else (1 if flat_tracks else 0)
        report.set_total(total_units)

        created = 0

        if not subdirs:
            if flat_tracks:
                list_name = os.path.basename(os.path.normpath(root_dir)) or "playlist"
                report.update(0, 1, list_name)
                save_playlist(os.path.join(save_dir, f"{list_name}.{ext}"),
                              flat_tracks, ext, list_name, args.use_folder_name)
                created = 1
                print(f"{Colors.GREEN}[+] Создан:{Colors.END} {list_name}.{ext} "
                      f"({len(flat_tracks)} треков из папки без подпапок)")
            else:
                print(f"{Colors.YELLOW}[~] В папке не найдено аудиофайлов: "
                      f"{root_dir}{Colors.END}")
        else:
            for index, entry in enumerate(subdirs, start=1):
                report.update(index - 1, len(subdirs), entry.name)
                tracks = []
                for r, _, fs in os.walk(entry.path):
                    for f in fs:
                        if f.lower().endswith(music_exts):
                            full_p = os.path.join(r, f)
                            track_path = format_path(full_p, base_dir=root_dir,
                                                     absolute=args.absolute,
                                                     rel_base=args.relative_base)
                            tracks.append(track_path)
                if tracks:
                    tracks.sort()
                    tracks = [t.replace('\\', '/') for t in tracks]
                    save_playlist(os.path.join(save_dir, f"{entry.name}.{ext}"),
                                  tracks, ext, entry.name, args.use_folder_name)
                    created += 1

        report.finish(f"Создано плейлистов: {created}")
        return {"created": created, "lists": total_units}
