"""Скачивание треков из Яндекс.Музыки (логика yamd.py без изменений).

Отличия только в точках ввода: вместо input() токен и параметры приходят из GUI.
"""

import os
import re
import sys
import time

import requests

from ..progress import as_progress

try:
    from yandex_music import Client
    _YM_IMPORT_ERROR = None
except Exception as exc:
    Client = None
    _YM_IMPORT_ERROR = exc

from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1, TALB, APIC, TYER
from mutagen.flac import FLAC, Picture

VER = '1.3.2'


class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    BLACK = '\033[30m'
    BG_YELLOW = '\033[43m'
    END = '\033[0m'


def sanitize(name):
    return re.sub(r'[\\/*?:"<>|]', "", name)


def write_tags(filepath, track, timeout):
    ext = os.path.splitext(filepath)[1].lower()
    try:
        if ext == '.mp3':
            audio = MP3(filepath, ID3=ID3)
            try:
                audio.add_tags()
            except Exception:
                pass
            audio.tags.add(TIT2(encoding=3, text=track.title))
            artists = ", ".join([a.name for a in track.artists])
            audio.tags.add(TPE1(encoding=3, text=artists))
            if track.albums:
                audio.tags.add(TALB(encoding=3, text=track.albums[0].title))
                if track.albums[0].year:
                    audio.tags.add(TYER(encoding=3, text=str(track.albums[0].year)))
            if track.cover_uri:
                try:
                    cover_url = "https://" + track.cover_uri.replace("%%", "600x600")
                    img_data = requests.get(cover_url, timeout=timeout).content
                    audio.tags.add(APIC(encoding=3, mime='image/jpeg', type=3, desc='Cover', data=img_data))
                except Exception:
                    pass
            audio.save()
        elif ext == '.flac':
            audio = FLAC(filepath)
            audio["title"] = track.title
            audio["artist"] = ", ".join([a.name for a in track.artists])
            if track.albums:
                audio["album"] = track.albums[0].title
                if track.albums[0].year:
                    audio["date"] = str(track.albums[0].year)
            if track.cover_uri:
                try:
                    cover_url = "https://" + track.cover_uri.replace("%%", "600x600")
                    img_data = requests.get(cover_url, timeout=timeout).content
                    image = Picture()
                    image.type = 3
                    image.mime = "image/jpeg"
                    image.desc = "Cover"
                    image.data = img_data
                    audio.add_picture(image)
                except Exception:
                    pass
            audio.save()
    except Exception:
        pass


def verify_report(target_dir, original_list, downloaded_list):
    print(f"\n{Colors.BOLD}{Colors.CYAN}--- ОТЧЕТ О НЕСООТВЕТСТВИЯХ ---{Colors.END}")
    missing = [item for item in original_list if item not in downloaded_list]
    report_path = os.path.join(target_dir, "!missing_tracks.txt")
    if not missing:
        print(f"{Colors.GREEN}Все треки из файла обработаны успешно{Colors.END}")
        if os.path.exists(report_path):
            os.remove(report_path)
    else:
        print(f"{Colors.YELLOW}Не скачано: {len(missing)} треков. Список в !missing_tracks.txt{Colors.END}")
        with open(report_path, 'w', encoding='utf-8') as f:
            for track in missing:
                f.write(f"{track}\n")
    print(f"Итого: {len(downloaded_list)} из {len(original_list)} треков.")


def load_config(config_file='init.tok'):
    config = {}
    if os.path.exists(config_file):
        with open(config_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, val = line.split('=', 1)
                config[key.strip()] = val.strip()
    return config


def save_config(config, config_file='init.tok'):
    with open(config_file, 'w', encoding='utf-8') as f:
        for k, v in config.items():
            f.write(f"{k}={v}\n")


def authorize(token, config_file='init.tok'):
    """Возвращает (client, token). Пишет токен в init.tok как в оригинале."""
    if _YM_IMPORT_ERROR is not None:
        raise RuntimeError(
            "Не установлена библиотека yandex_music. Выполните: pip install yandex_music"
        )
    if not token:
        raise ValueError("Токен не задан. Укажите Яндекс-токен в поле вкладки.")

    config = load_config(config_file)
    client = Client(token).init()
    print(f"{Colors.GREEN}[+] Авторизация успешна{Colors.END}")
    config['TOKEN'] = token
    save_config(config, config_file)
    return client, token


def download(input_file, download_dir, timeout, max_retries, use_flac, token,
             config_file='init.tok', progress=None, on_track=None):
    """Основной цикл скачивания. Соответствует main() исходного yamd.py.

    Дополнительно сообщает о прогрессе и возвращает список скачанных треков
    для таблицы во вкладке.

    ``on_track`` — необязательный колбэк, вызываемый сразу после обработки
    каждого трека (до перехода к следующему). Нужен, чтобы таблица в GUI
    заполнялась по ходу скачивания, а не одним куском в конце. Ошибка внутри
    колбэка не должна срывать скачивание, поэтому она подавляется.
    """
    report = as_progress(progress)
    report.start(0, "Подготовка")

    if _YM_IMPORT_ERROR is not None:
        raise RuntimeError(
            "Не установлена библиотека yandex_music. Выполните: pip install yandex_music"
        )

    print(f"{Colors.BG_YELLOW}{Colors.BLACK}{Colors.BOLD} Yamd ver. {VER} {Colors.END}\n")

    report.message("Авторизация")
    client, token = authorize(token, config_file)

    config = load_config(config_file)
    DOWNLOAD_DIR = download_dir or config.get('DOWNLOAD_DIR', 'downloads')
    TIMEOUT = timeout or int(config.get('TIMEOUT', 15))
    MAX_RETRIES = max_retries or int(config.get('MAX_RETRIES', 3))

    if not input_file:
        raise ValueError("Не указан путь к TXT-файлу плейлиста")

    if not os.path.exists(input_file):
        print(f"{Colors.RED}[-] Файл плейлиста не найден{Colors.END}")
        return

    base_name = os.path.splitext(os.path.basename(input_file))[0]
    target_dir = os.path.join(DOWNLOAD_DIR, sanitize(base_name))
    if not os.path.exists(target_dir):
        os.makedirs(target_dir)

    with open(input_file, 'r', encoding='utf-8') as f:
        original_tracks = [line.strip() for line in f if line.strip() and not line.startswith('#')]

    successfully_processed = []
    print(f"В директории: {DOWNLOAD_DIR} создана папка /{base_name}, "
          f"Таймаут: {TIMEOUT}, Попыток: {MAX_RETRIES}")
    print(f"{Colors.BOLD}Коллекция:{Colors.END} {base_name} | {len(original_tracks)} треков")
    print("-" * 80)

    trackCounter = 0
    report.set_total(len(original_tracks))
    report.message(f"Коллекция: {base_name}")

    downloaded_rows = []

    def _emit_row(row):
        """Кладёт строку в итоговый список и сразу отдаёт её в GUI."""
        downloaded_rows.append(row)
        if on_track is not None:
            try:
                on_track(row)
            except Exception:  # noqa: BLE001 — колбэк GUI не должен ломать загрузку
                pass

    for query in original_tracks:
        trackCounter += 1
        display_name = (query[:67] + '...') if len(query) > 70 else query
        print(f"{display_name:<70} | {trackCounter}", end=" ", flush=True)
        report.update(trackCounter - 1, len(original_tracks), display_name)

        try:
            search = client.search(query)
            if not search.tracks or not search.tracks.results:
                print(f"{Colors.RED}НЕ НАЙДЕНО{Colors.END}")
                _emit_row({
                    "title": query, "bitrate": "—", "size": "—",
                    "status": "Не найдено",
                })
                continue

            track = search.tracks.results[0]
            info = track.get_download_info(get_direct_links=True)

            # Логика выбора качества
            selected_info = None
            if use_flac:
                flac_options = [i for i in info if i.codec == 'flac']
                if flac_options:
                    selected_info = flac_options[0]

            if not selected_info:
                mp3_options = [i for i in info if i.codec == 'mp3']
                mp3_options.sort(key=lambda x: x.bitrate_in_kbps, reverse=True)
                selected_info = mp3_options[0] if mp3_options else info[0]

            ext = f".{selected_info.codec}"
            artists_str = ", ".join([a.name for a in track.artists])
            filename = f"{sanitize(artists_str)} - {sanitize(track.title)}{ext}"
            filepath = os.path.join(target_dir, filename)

            if os.path.exists(filepath):
                sys.stdout.write(
                    f"\r{display_name:<70} {trackCounter:<8} | "
                    f"{Colors.YELLOW}ПРОПУЩЕНО (Существует){Colors.END}\n")
                successfully_processed.append(query)
                _emit_row({
                    "title": f"{artists_str} - {track.title}",
                    "bitrate": _format_bitrate(selected_info),
                    "size": _format_size(os.path.getsize(filepath)),
                    "status": "Уже был",
                })
                report.advance(1, display_name)
                continue

            link = selected_info.get_direct_link()
            downloaded = False
            for attempt in range(MAX_RETRIES):
                try:
                    response = requests.get(link, stream=True, timeout=TIMEOUT)
                    response.raise_for_status()
                    total_size = int(response.headers.get('content-length', 0))

                    with open(filepath, 'wb') as f:
                        current_size = 0
                        for data in response.iter_content(chunk_size=32768):
                            current_size += len(data)
                            f.write(data)
                            if total_size > 0:
                                percent = int(100 * current_size / total_size)
                                sys.stdout.write(
                                    f'\r{display_name:<70} {Colors.CYAN}ЗАГРУЗКА{Colors.END} | '
                                    f'{Colors.CYAN}{percent}%{Colors.END}')
                                sys.stdout.flush()
                                report.detail(
                                    f"{display_name} — загрузка {percent}%"
                                )
                    downloaded = True
                    break
                except Exception:
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(1)
                        continue
                    else:
                        raise

            if downloaded:
                write_tags(filepath, track, TIMEOUT)
                successfully_processed.append(query)
                q_label = "FLAC" if selected_info.codec == 'flac' else f"MP3 {selected_info.bitrate_in_kbps}k"
                sys.stdout.write(
                    f"\r{display_name:<70} {trackCounter:<8} | "
                    f"{Colors.GREEN}OK ({q_label}){Colors.END}\n")
                _emit_row({
                    "title": f"{artists_str} - {track.title}",
                    "bitrate": _format_bitrate(selected_info),
                    "size": _format_size(os.path.getsize(filepath)),
                    "status": "Скачано",
                })

        except Exception as e:
            sys.stdout.write(
                f"\r{display_name:<70} {trackCounter:<8} | "
                f"{Colors.RED}ОШИБКА{Colors.END} ({type(e).__name__})\n")
            print(f"[ОШИБКА] {query}: {type(e).__name__}: {e}")
            _emit_row({
                "title": query, "bitrate": "—", "size": "—",
                "status": f"Ошибка ({type(e).__name__})",
            })
        finally:
            report.update(trackCounter, len(original_tracks), display_name)

    print("-" * 80)
    verify_report(target_dir, original_tracks, successfully_processed)
    report.finish(f"Обработано треков: {len(downloaded_rows)}")

    return {
        "rows": downloaded_rows,
        "target_dir": os.path.abspath(target_dir),
        "downloaded": len(successfully_processed),
        "total": len(original_tracks),
    }


def _format_bitrate(info) -> str:
    """Подпись качества: FLAC без битрейта, MP3 с числом kbps."""
    try:
        if getattr(info, "codec", "") == "flac":
            return "FLAC"
        return f"MP3 {info.bitrate_in_kbps} kbps"
    except Exception:
        return "—"


def _format_size(size_bytes: int) -> str:
    try:
        if size_bytes >= 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.2f} МБ"
        return f"{size_bytes / 1024:.0f} КБ"
    except Exception:
        return "—"
