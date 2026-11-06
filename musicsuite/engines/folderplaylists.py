"""Создание плейлистов из папок.

Задача
------
Есть папка с дискографиями: внутри папки артистов, внутри них — альбомы.
Нужно получить по одному плейлисту на артиста, не собирая плейлисты для
каждого альбома.

Два режима
----------
1. «Использовать папку как основную» (``use_main_folder=True``).
   Плейлисты создаются по подпапкам ПЕРВОГО уровня: ``Дискографии/Арист1``
   даёт плейлист «Арист1», куда рекурсивно попадают все треки из
   ``Дискографии/Арист1/**``. Подпапки второго уровня (альбомы) своих
   плейлистов не получают.

2. Галочка снята — один плейлист из всей выбранной папки, имя по имени
   папки.

Порядок треков
--------------
``SORT_BY_PATH``  — по алфавиту относительного пути: альбомы идут в порядке
                    папок, треки внутри — в порядке имён. Файлы, лежащие
                    прямо в корне, оказываются первыми (их родитель — пустая
                    строка, а она сортируется раньше любого имени).

``SORT_BY_TITLE`` — по названию из тегов. Если тега нет, берётся имя файла
                    без расширения: иначе треки без тегов сбивались бы
                    в конец в произвольном порядке.

Пути в плейлисте
----------------
Формируются функцией ``plscreate.format_path`` — той же, что в остальных
вкладках, чтобы формат совпадал:

* галочка «полные пути» — абсолютный путь как есть;
* префикс ``/music`` — путь относительно сканируемой папки с префиксом;
* пустой префикс — путь относительно сканируемой папки.
"""

from __future__ import annotations

import os
import re

from ..progress import as_progress
from . import plscreate
from .plscreate import format_path, normalize_track_path, read_playlist_tracks

# Расширения, которые считаем музыкой
AUDIO_EXTENSIONS = (
    ".mp3", ".flac", ".ape", ".wav", ".ogg", ".opus", ".m4a", ".aac",
    ".wma", ".wv", ".tta", ".dsf", ".aiff", ".alac",
)

# Форматы плейлистов и подписи для списка
FORMATS = ("m3u", "m3u8", "pls", "xspf", "wpl")

# Способы сортировки
SORT_BY_PATH = "path"
SORT_BY_TITLE = "title"

SORT_LABELS = {
    "По алфавиту пути — альбомы по папкам": SORT_BY_PATH,
    "По названию трека — из тегов": SORT_BY_TITLE,
}
DEFAULT_SORT_LABEL = "По алфавиту пути — альбомы по папкам"

# Статусы в таблице результатов
STATUS_CREATED = "Создан"
STATUS_UPDATED = "Обновлён"
STATUS_UNCHANGED = "Без изменений"

# Символы, недопустимые в имени файла на Windows
_BAD_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def normalize_prefix(prefix: str) -> str:
    """Приводит префикс к виду «/сегмент/сегмент» без хвостового слэша.

    Обратные слэши заменяются на прямые: пользователь может вставить путь
    из Проводника, а в плейлисте нужны Unix-разделители.
    """
    value = (prefix or "").replace("\\", "/").strip()
    if not value:
        return ""
    value = re.sub(r"/+", "/", value)
    if value != "/":
        value = value.rstrip("/")
    return value


def strip_duplicated_prefix(relative: str, prefix: str) -> str:
    """Убирает из относительного пути сегменты, уже вошедшие в префикс.

    Зачем это нужно: если сканировать родительскую папку (``D:\\Music``),
    а префикс указать вместе с именем вложенной папки
    (``/music/Дискографии``), то относительный путь начинается с того же
    «Дискографии», и получалось ``/music/Дискографии/Дискографии/Арист1/...``.
    Один и тот же сегмент попадал в путь дважды, и плейлист не открывался.

    Сравнение идёт по сегментам и без учёта регистра. Возвращается путь
    без повторов; если совпадений нет — путь не меняется.
    """
    prefix = normalize_prefix(prefix)
    if not prefix or not relative:
        return relative

    prefix_parts = [part for part in prefix.split("/") if part]
    rel_parts = relative.replace("\\", "/").split("/")
    if not prefix_parts or not rel_parts:
        return relative

    # Ищем наибольшее перекрытие: конец префикса = начало относительного пути.
    max_overlap = min(len(prefix_parts), len(rel_parts) - 1)
    for size in range(max_overlap, 0, -1):
        tail = [part.casefold() for part in prefix_parts[-size:]]
        head = [part.casefold() for part in rel_parts[:size]]
        if tail == head:
            return "/".join(rel_parts[size:])
    return relative


def resolve_sort(value) -> str:
    """Приводит выбор сортировки к коду. Неизвестное — по пути."""
    if value in SORT_LABELS:
        return SORT_LABELS[value]
    if value in SORT_LABELS.values():
        return value
    return SORT_BY_PATH


def safe_name(name: str) -> str:
    """Имя файла без символов, запрещённых в Windows."""
    cleaned = _BAD_NAME_CHARS.sub("", (name or "").strip())
    cleaned = cleaned.strip(". ")
    return cleaned or "playlist"


def is_audio(name: str) -> bool:
    """Похоже ли имя файла на музыку."""
    return name.lower().endswith(AUDIO_EXTENSIONS)


def scan_tracks(folder: str) -> list[str]:
    """Все аудиофайлы папки рекурсивно, в натуральном порядке обхода.

    Порядок здесь не важен: сортировка делается отдельно, уже с учётом
    выбранного способа.
    """
    found = []
    for root, dirs, files in os.walk(folder):
        dirs.sort()
        for name in sorted(files):
            if is_audio(name):
                found.append(os.path.join(root, name))
    return found


def build_targets(root: str, use_main_folder: bool) -> list[tuple[str, str]]:
    """Список пар (папка, имя плейлиста).

    В режиме основной папки — подпапки первого уровня. Если подпапок нет,
    поведение вырождается в обычное: один плейлист по самой папке. Иначе
    пользователь нажал бы «Создать» и не получил ничего без объяснений.
    """
    root = os.path.abspath(root)

    if use_main_folder:
        try:
            entries = sorted(os.listdir(root))
        except OSError:
            entries = []

        subfolders = [
            os.path.join(root, name) for name in entries
            if os.path.isdir(os.path.join(root, name))
            # Служебные папки не превращаем в плейлисты
            and not name.startswith(".")
        ]
        if subfolders:
            return [(folder, os.path.basename(folder)) for folder in subfolders]

    name = os.path.basename(os.path.normpath(root)) or "playlist"
    return [(root, name)]


def _title_of(path: str) -> str:
    """Название трека из тега, иначе имя файла без расширения."""
    try:
        from mutagen import File as MutagenFile

        audio = MutagenFile(path, easy=True)
        if audio is not None:
            titles = audio.get("title") or []
            if titles:
                title = str(titles[0]).strip()
                if title:
                    return title
    except Exception:
        # Битый файл или неизвестный формат — сортируем по имени файла.
        pass
    return os.path.splitext(os.path.basename(path))[0]


def order_tracks(tracks: list[str], sort_mode: str, base_dir: str) -> list[str]:
    """Сортирует треки выбранным способом."""
    if sort_mode == SORT_BY_TITLE:
        # Ключ — (название, путь): при одинаковых названиях порядок
        # остаётся предсказуемым и не зависит от порядка обхода.
        return sorted(tracks, key=lambda p: (_title_of(p).casefold(),
                                             p.casefold()))

    def path_key(path: str):
        relative = os.path.relpath(path, base_dir).replace("\\", "/")
        return relative.casefold()

    return sorted(tracks, key=path_key)


def build_playlists(root: str, *, use_main_folder: bool = True,
                    prefix: str = "/music", absolute: bool = False,
                    playlist_format: str = "m3u", sort_by: str = SORT_BY_PATH,
                    save_dir: str = "", progress=None,
                    on_playlist=None) -> list[dict]:
    """Создаёт плейлисты и возвращает список результатов.

    Каждый элемент: ``{name, path, tracks, status, folder}``.

    ``on_playlist(entry, index, total)`` вызывается сразу после
    записи очередного файла — чтобы таблица в интерфейсе
    наполнялась по ходу дела, а не после завершения всего прогона.
    На большой фонотеке прогон занимает минуты, и пустая таблица всё это
    время выглядит как зависание.
    """
    report = as_progress(progress)
    root = os.path.abspath(root)

    if not os.path.isdir(root):
        raise ValueError(f"Папка не найдена: {root}")

    playlist_format = playlist_format if playlist_format in FORMATS else "m3u"
    sort_mode = resolve_sort(sort_by)

    # Куда писать. Пусто — рядом со сканируемой папкой, чтобы результат
    # был на виду, а не в неизвестном каталоге.
    target_dir = os.path.abspath(save_dir) if save_dir else root
    os.makedirs(target_dir, exist_ok=True)

    targets = build_targets(root, use_main_folder)
    report.start(len(targets), "Поиск треков")
    print(f"\n{plscreate.Colors.BOLD}{plscreate.Colors.CYAN}"
          f"Создание плейлистов: {root}{plscreate.Colors.END}")
    print(f"Формат: {playlist_format}, плейлистов: {len(targets)}, "
          f"куда: {target_dir}")
    shown_prefix = normalize_prefix(prefix) or "(нет — пути от папки)"
    print(f"Префикс пути: {shown_prefix}, полные пути: "
          f"{'да' if absolute else 'нет'}")

    results = []
    for index, (folder, name) in enumerate(targets, start=1):
        report.update(index - 1, len(targets), name)
        print("-" * 50)
        print(f"[{index}/{len(targets)}] {name}")

        tracks = scan_tracks(folder)
        if not tracks:
            print(f"  {plscreate.Colors.YELLOW}нет музыки, пропуск"
                  f"{plscreate.Colors.END}")
            empty_entry = {
                "name": name, "path": "", "tracks": 0,
                "status": "Нет треков", "folder": folder,
            }
            results.append(empty_entry)
            if on_playlist is not None:
                on_playlist(empty_entry, index, len(targets))
            continue

        ordered = order_tracks(tracks, sort_mode, root)

        # Собираем путь сами, а не через format_path с base_dir: та считает
        # путь от base_dir заново и, получив уже готовый относительный путь
        # в качестве префикса, приписала бы его к самому себе.
        clean_prefix = normalize_prefix(prefix)
        formatted = []
        for path in ordered:
            if absolute:
                formatted.append(format_path(path, absolute=True))
                continue

            relative = os.path.relpath(path, root).replace("\\", "/")
            relative = strip_duplicated_prefix(relative, clean_prefix)
            if clean_prefix:
                formatted.append(f"{clean_prefix}/{relative}")
            else:
                formatted.append(relative)

        playlist_path = os.path.join(
            target_dir, f"{safe_name(name)}.{playlist_format}"
        )

        # Статус вычисляем до записи: save_playlist сам решает, писать ли
        # файл, но не сообщает об этом вызывающему.
        if os.path.isfile(playlist_path):
            old = read_playlist_tracks(playlist_path, playlist_format)
            new = sorted(normalize_track_path(t) for t in formatted)
            status = STATUS_UNCHANGED if old == new else STATUS_UPDATED
        else:
            status = STATUS_CREATED

        plscreate.save_playlist(
            playlist_path, formatted, playlist_format, name,
            use_folder_name=True,
        )

        print(f"  треков: {len(formatted)}, статус: {status}")
        entry = {
            "name": name,
            "path": playlist_path,
            "tracks": len(formatted),
            "status": status,
            "folder": folder,
        }
        results.append(entry)

        # Отдаём наверх сразу: таблица заполняется по ходу, а не в конце.
        if on_playlist is not None:
            on_playlist(entry, index, len(targets))

    created = sum(1 for r in results if r["status"] == STATUS_CREATED)
    updated = sum(1 for r in results if r["status"] == STATUS_UPDATED)
    unchanged = sum(1 for r in results if r["status"] == STATUS_UNCHANGED)

    print("-" * 50)
    print(f"[DONE] создано: {created}, обновлено: {updated}, "
          f"без изменений: {unchanged}")

    report.finish(f"Плейлистов: {len(results)} "
                  f"(создано {created}, обновлено {updated})")
    return results
