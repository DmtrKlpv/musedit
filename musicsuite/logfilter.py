"""Фильтр консоли: в поле вывода попадают только ошибки и информационные строки.

Движки печатают много служебного шума — перечни файлов, счётчики треков,
прогресс-строки tqdm. В GUI прогресс показывают полосы, поэтому такие строки
отбрасываются. Пользователь может переключить «Все сообщения», чтобы увидеть
полный поток.
"""

from __future__ import annotations

import re

# Строки, которые считаем «информационными» и всегда показываем.
_KEEP = (
    re.compile(r"^\s*=+"),                       # заголовки секций === ...
    re.compile(r"^\s*-{3,}\s*$"),                # разделители
    re.compile(r"^\s*\[[A-ZА-ЯЁ!+~xX\-]{1,12}\]"),  # [INFO], [ERROR], [x], [+], [!]
    re.compile(r"(?i)\b(error|ошибк|fail|failed|traceback|exception|критич)"),
    re.compile(r"(?i)\b(warn|предупрежд|внимание)"),
    re.compile(r"(?i)(готово|итого|сохран|записан|создан|обновлен|обновлён|"
               r"удал|найдено|не найден|не найдено|пропущен|обработан|завершен|завершён)"),
    re.compile(r"(?i)(файл|папка|директория|каталог)\s*[:\-]"),
    re.compile(r"(?i)^(поиск|индексация|анализ|конвертация|скачивание|экспорт|"
               r"создание|исправление|загрузка)\b"),
    re.compile(r"(?i)^\s*(режим|режим:|mode)"),
)

# Явный мусор: прогресс-бары, счётчики, перечисления путей.
_DROP = (
    re.compile(r"%\|"),                          # tqdm: 45%|####
    re.compile(r"^\s*\d+%"),                     # «100% ...»
    re.compile(r"^\s*[\|\-\\/]\s*$"),            # spinner
    re.compile(r"\d+\s*/\s*\d+\s*\["),           # tqdm счётчик
    re.compile(r"^\s+\S+\.(mp3|flac|wav|m4a|ogg|ape|dsf|dff)\s"),  # перечень файлов
    re.compile(r"(?i)^\s*(загрузка|loading)\s*[:|]"),                # URL-прогресс
    re.compile(r"(?i)^\s*файл:\s"),                                  # «File: track.mp3»
)


class MessageFilter:
    """Решает, показывать ли завершённую строку в консоли."""

    def __init__(self, show_all: bool = False) -> None:
        self.show_all = show_all

    def keep(self, line: str) -> bool:
        if self.show_all:
            return True

        stripped = line.strip()
        if not stripped:
            return False

        for pattern in _DROP:
            if pattern.search(stripped):
                return False

        for pattern in _KEEP:
            if pattern.search(stripped):
                return True

        return False
