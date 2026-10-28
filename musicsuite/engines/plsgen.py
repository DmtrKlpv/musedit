"""Экспорт плейлиста Яндекс.Музыки в TXT (логика plsgen.py без изменений).

Добавлено только необязательное сохранение в выбранный пользователем файл и
отчёт о прогрессе для GUI — сама последовательность действий прежняя.
"""

import os
import re

from ..progress import as_progress

try:
    from yandex_music import Client
    _YM_IMPORT_ERROR = None
except Exception as exc:  # библиотека может отсутствовать
    Client = None
    _YM_IMPORT_ERROR = exc


class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    BLACK = '\033[30m'
    BG_YELLOW = '\033[43m'
    END = '\033[0m'


def get_playlist_tracks(iframe_code, custom_filename, output_path=None,
                        progress=None):
    """Исходная функция экспорта. Возвращает путь к созданному файлу или None.

    output_path — полный путь к TXT-файлу. Если не задан, сохраняется в
    подпапку pls рядом с приложением, как в оригинальном скрипте.
    """
    report = as_progress(progress)
    report.start(4, "Проверка данных плейлиста")

    if _YM_IMPORT_ERROR is not None:
        raise RuntimeError(
            "Не установлена библиотека yandex_music. Выполните: pip install yandex_music"
        )

    # 1. Извлекаем данные из строки iframe
    match = re.search(r'playlist/([^/]+)/(\d+)', iframe_code)
    if not match:
        print(f"{Colors.RED}[x] Не удалось найти данные плейлиста в переданном тексте.{Colors.END}")
        print("")
        return None

    username, playlist_id = match.groups()
    report.advance(1, "Авторизация в Яндекс.Музыке")
    client = Client().init()

    try:
        # 2. Получаем объект плейлиста
        report.advance(1, "Загрузка списка треков")
        playlist = client.users_playlists(playlist_id, username)
        tracks = playlist.fetch_tracks()

        raw_count = len(tracks)
        print('---------------------------------')
        print(f"Найдено треков в плейлисте: {raw_count}")

        # 3. Формируем список строк
        track_list = []
        for item in tracks:
            track = item.track if hasattr(item, 'track') else item
            artists = ", ".join([a.name for a in track.artists])
            track_list.append(f"{artists} - {track.title}")

        # 4. Проверка и удаление дубликатов
        unique_tracks = list(dict.fromkeys(track_list))
        final_count = len(unique_tracks)

        if raw_count != final_count:
            print(f"Внимание: Удалено дубликатов: {raw_count - final_count}")
        else:
            print("Дубликатов не обнаружено.")

        # 5. Работа с директорией и именем файла
        report.advance(1, "Подготовка файла")

        if output_path:
            file_path = os.path.abspath(output_path)
            target_dir = os.path.dirname(file_path) or "."
            if not os.path.exists(target_dir):
                os.makedirs(target_dir)
                print(f"Создана директория: {target_dir}")
            if not os.path.splitext(file_path)[1]:
                file_path += ".txt"
        else:
            target_dir = "pls"
            if not os.path.exists(target_dir):
                os.makedirs(target_dir)
                print(f"Создана директория: {target_dir}")

            if not custom_filename or not custom_filename.strip():
                custom_filename = "playlist_export"

            if not custom_filename.endswith(".txt"):
                custom_filename += ".txt"

            file_path = os.path.join(target_dir, custom_filename)

        # 6. Запись в файл
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(unique_tracks))

        print(f"Готово! Файл сохранён в: {file_path}")
        print(f"Итого строк в файле: {final_count}")
        print('---------------------------------')

        report.finish(f"Экспортировано треков: {final_count}")
        return os.path.abspath(file_path)
    except Exception as e:
        print(f"{Colors.RED}[x] Произошла ошибка при получении данных: {e}{Colors.END}")
        raise
