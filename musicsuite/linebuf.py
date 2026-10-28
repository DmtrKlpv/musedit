"""Построчный буфер для консоли: эмуляция поведения терминала с '\\r'.

Модуль не зависит от Qt, поэтому логика перерисовки строк тестируется отдельно.
feed() возвращает список операций, которые виджет применяет к QPlainTextEdit:
    ("replace", текст) — заменить содержимое текущей (последней) строки
    ("newline", None)  — завершить строку и начать новую

Возврат каретки начинает строку заново: прогресс-бары (tqdm, счётчики загрузки)
перерисовывают одну и ту же строку вместо накопления тысяч новых.
"""

from typing import List, Optional, Tuple

Op = Tuple[str, Optional[str]]


class LineBuffer:
    def __init__(self) -> None:
        self.current = ""
        self.lines: List[str] = []
        # '\r' на конце порции может оказаться началом '\r\n' в следующей
        # порции — придерживаем его, иначе строка потеряется.
        self._carry = ""

    # ------------------------------------------------------------------
    def _consume(self, segment: str) -> None:
        """Проводит фрагмент через возврат каретки."""
        pieces = segment.split("\r")
        self.current += pieces[0]
        for piece in pieces[1:]:
            # '\r' возвращает курсор в начало: строка начинается заново.
            # Остаток прежней строки не сохраняем — иначе в логе остаётся
            # «мусорный хвост» от предыдущего состояния прогресс-бара.
            self.current = piece

    # ------------------------------------------------------------------
    def feed(self, text: str) -> List[Op]:
        if not text:
            return []

        ops: List[Op] = []
        text = self._carry + text
        self._carry = ""

        # Одиночный '\r' в конце порции: не знаем, будет ли дальше '\n'.
        if text.endswith("\r"):
            self._carry = "\r"
            text = text[:-1]

        text = text.replace("\r\n", "\n")
        parts = text.split("\n")

        for segment in parts[:-1]:
            self._consume(segment)
            ops.append(("replace", self.current))
            ops.append(("newline", None))
            self.lines.append(self.current)
            self.current = ""

        tail = parts[-1]
        if tail:
            self._consume(tail)
            ops.append(("replace", self.current))

        return ops

    # ------------------------------------------------------------------
    def text(self) -> str:
        return "\n".join(self.lines + [self.current + self._carry])

    def clear(self) -> None:
        self.current = ""
        self.lines.clear()
        self._carry = ""
