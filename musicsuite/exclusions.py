"""Исключения для поиска дубликатов: «это не дубликаты, больше не показывать».

Задача
------
Бывает, что файлы совпадают по имени или по SHA-256, но дубликатами не
являются. Пример из практики: «07 - Иод.mp3» и «07 - Иод.mp3» из папки
«… (Instrumental)» — одна версия с текстом, другая минус. Размер и содержимое
у одинаковых по имени файлов могут совпадать, но это разные записи.

Удалять их нельзя, а видеть в списке каждый раз — мешает. Поэтому группа
исключается: пропадает из результатов и больше не появляется при повторном
поиске или импорте отчёта.

Как определяется «та же группа»
-------------------------------
Ключ строится из типа совпадения и набора имён файлов без пути:

    ("Имя", ("07 - иод.mp3",))

Имена, а не полные пути: папку могут переименовать или перенести, а
исключение должно продолжать работать. Регистр не важен.

Если в группе несколько файлов, набор имён сравнивается как множество —
порядок строк в отчёте не влияет.

Где хранится
------------
JSON в домашней папке пользователя: ``~/.musedit/exclusions.json``.
Файл читается при старте вкладки, поэтому исключения живут между
запусками программы.
"""

from __future__ import annotations

import json
import os
from typing import Iterable

# Имя файла с исключениями
STORE_NAME = "exclusions.json"
APP_DIR = ".musedit"


def default_path() -> str:
    """Путь к файлу исключений в домашней папке пользователя."""
    return os.path.join(os.path.expanduser("~"), APP_DIR, STORE_NAME)


def _normalize(name: str) -> str:
    """Имя файла в том виде, в котором оно сравнивается."""
    return os.path.basename(name.replace("\\", "/")).strip().lower()


def group_signature(group: dict) -> str:
    """Строковый ключ группы: имена файлов и сколько их.

    Тип совпадения в ключ НЕ входит намеренно. Пользователь исключает
    пару файлов («это не дубликаты»), а не способ, которым они совпали:
    «07 - Иод.mp3» и версия минус могут найтись и по имени, и по SHA-256 —
    после исключения группа не должна всплывать при смене режима.

    Имя повторяется столько раз, сколько файлов с ним в группе: группа
    из трёх копий и группа из двух — разные группы, даже если имя одно.

    Пути не входят: папку могут переименовать или перенести, а исключение
    должно продолжать работать.

    Строка, а не кортеж: JSON хранит строки и числа, а сравнение должно
    быть стабильным и не зависеть от порядка строк в отчёте.
    """
    counts: dict[str, int] = {}
    for entry in group.get("files", []):
        name = _normalize(entry.get("path", ""))
        if name:
            counts[name] = counts.get(name, 0) + 1

    parts = [f"{name}x{count}" if count > 1 else name
             for name, count in sorted(counts.items())]
    return "~".join(parts)


def describe(signature: str, match: str = "") -> tuple[str, list[str]]:
    """Разбирает ключ обратно: (тип совпадения, список имён).

    Тип совпадения в ключе больше не хранится — его передаёт вызывающий
    из сохранённых данных. Старые ключи с префиксом «Имя|» читаются тоже.
    """
    rest = signature
    if "|" in signature:
        stored_match, rest = signature.split("|", 1)
        match = match or stored_match

    names = []
    for part in rest.split("~"):
        if not part:
            continue
        # «имяx3» → три повтора имени
        if "x" in part:
            name, _, count = part.rpartition("x")
            if count.isdigit() and name:
                names.extend([name] * int(count))
                continue
        names.append(part)
    return match, names


class ExclusionStore:
    """Список исключённых групп с сохранением в JSON."""

    def __init__(self, path: str | None = None):
        self.path = path or default_path()
        self._items: dict[str, dict] = {}
        self.load()

    # ------------------------------------------------------------------
    def load(self) -> None:
        """Читает файл. Повреждённый файл не ломает приложение."""
        self._items = {}
        if not os.path.isfile(self.path):
            return

        try:
            with open(self.path, "r", encoding="utf-8") as stream:
                raw = json.load(stream)
        except Exception:  # noqa: BLE001 — битый JSON просто игнорируем
            return

        if not isinstance(raw, dict):
            return

        for signature, payload in raw.items():
            if isinstance(payload, dict):
                self._items[signature] = payload
            else:
                self._items[signature] = {}

    def save(self) -> None:
        """Записывает файл. Ошибка записи не должна срывать работу."""
        folder = os.path.dirname(self.path)
        try:
            if folder:
                os.makedirs(folder, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as stream:
                json.dump(self._items, stream, ensure_ascii=False, indent=2)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, group) -> bool:
        if isinstance(group, str):
            return group in self._items
        return group_signature(group) in self._items

    def is_excluded(self, group: dict) -> bool:
        """Исключена ли группа."""
        return group_signature(group) in self._items

    def exclude(self, group: dict) -> str:
        """Добавляет группу в исключения. Возвращает ключ."""
        signature = group_signature(group)
        self._items[signature] = {
            "match": group.get("match", "SHA256"),
            "names": sorted({
                _normalize(entry.get("path", ""))
                for entry in group.get("files", [])
                if entry.get("path")
            }),
            # Полные пути сохраняем для наглядного списка в диалоге:
            # по одним именам непонятно, какую папку исключили.
            "paths": [
                entry.get("path", "")
                for entry in group.get("files", [])
            ],
        }
        self.save()
        return signature

    def restore(self, signature: str) -> bool:
        """Убирает группу из исключений. True, если что-то удалили."""
        if signature in self._items:
            del self._items[signature]
            self.save()
            return True
        return False

    def clear(self) -> None:
        """Сбрасывает все исключения."""
        self._items.clear()
        self.save()

    def signatures(self) -> list[str]:
        """Ключи всех исключённых групп."""
        return sorted(self._items)

    def entries(self) -> Iterable[tuple[str, dict]]:
        """Пары (ключ, данные) для отображения."""
        for signature in self.signatures():
            yield signature, self._items[signature]

    def filter_groups(self, groups):
        """Убирает исключённые группы из списка."""
        return [g for g in groups if not self.is_excluded(g)]
