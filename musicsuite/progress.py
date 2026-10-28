"""Единый канал отчёта о прогрессе: движки -> GUI.

Движки получают объект с методами start/advance/message. Реализация может быть
любой: в фоне это Progress с колбэком в Qt-сигнал, в тестах — NullProgress.
Благодаря этому логика движков не знает про GUI и остаётся запускаемой из CLI.
"""

from __future__ import annotations

import time
from typing import Callable, Optional

ProgressCallback = Callable[[int, int, str], None]


class NullProgress:
    """Заглушка: движок можно вызывать без GUI и без колбэков."""

    total = 0
    done = 0

    def start(self, total: int = 0, text: str = "") -> None:
        self.total = max(0, int(total))
        self.done = 0

    def set_total(self, total: int) -> None:
        self.total = max(0, int(total))

    def advance(self, step: int = 1, text: str = "") -> None:
        self.done += step

    def update(self, done: int, total: Optional[int] = None, text: str = "") -> None:
        self.done = done
        if total is not None:
            self.total = max(0, int(total))

    def message(self, text: str) -> None:
        pass

    def detail(self, text: str) -> None:
        pass

    def finish(self, text: str = "") -> None:
        pass


class Progress(NullProgress):
    """Прогресс с колбэком. Троттлинг защищает GUI от тысяч сигналов в секунду."""

    def __init__(self, callback: Optional[ProgressCallback] = None,
                 min_interval: float = 0.02) -> None:
        self._callback = callback
        self._min_interval = min_interval
        self._last_emit = 0.0
        self._last_text = ""
        self.total = 0
        self.done = 0

    # ------------------------------------------------------------------
    def _emit(self, text: str = "", force: bool = False) -> None:
        if self._callback is None:
            return
        now = time.monotonic()
        if not force and (now - self._last_emit) < self._min_interval:
            return
        self._last_emit = now
        self._last_text = text
        try:
            self._callback(self.done, self.total, text)
        except RuntimeError:
            # Окно уже закрыто — молча выходим, чтобы не рвать рабочий поток.
            pass

    # ------------------------------------------------------------------
    def start(self, total: int = 0, text: str = "") -> None:
        self.total = max(0, int(total))
        self.done = 0
        self._emit(text, force=True)

    def set_total(self, total: int) -> None:
        self.total = max(0, int(total))
        self._emit(self._last_text, force=True)

    def advance(self, step: int = 1, text: str = "") -> None:
        self.done += step
        self._emit(text)

    def update(self, done: int, total: Optional[int] = None, text: str = "") -> None:
        self.done = done
        if total is not None:
            self.total = max(0, int(total))
        self._emit(text)

    def message(self, text: str) -> None:
        self._emit(text, force=True)

    def detail(self, text: str) -> None:
        """Частая детализация (проценты загрузки) — с троттлингом."""
        self._emit(text)

    def finish(self, text: str = "") -> None:
        if self.total:
            self.done = self.total
        self._emit(text, force=True)


def as_progress(value) -> NullProgress:
    """Любое значение (None, Progress, заглушка) приводит к объекту с нужным API."""
    if value is None:
        return NullProgress()
    return value
