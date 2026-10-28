"""Фоновые потоки (QThread) для длительных операций."""

from __future__ import annotations

import inspect
import sys
import traceback
from typing import Callable, Optional

from PySide6.QtCore import QThread, Signal

from .progress import Progress


class _BlockingStdin:
    """Заглушка stdin: фоновому потоку нельзя виснуть на input()."""

    encoding = "utf-8"

    def readline(self, *args, **kwargs):
        raise RuntimeError(
            "Запрошен ввод из консоли. Задайте все параметры в полях вкладки."
        )

    def read(self, *args, **kwargs):
        return self.readline()

    def isatty(self):
        return False

    def flush(self):
        pass


def _accepts_progress(func: Callable) -> bool:
    """Определяет, принимает ли функция объект прогресса дополнительным аргументом."""
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return False

    for parameter in signature.parameters.values():
        if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
            return False
        if parameter.name in ("progress", "reporter"):
            return True
    return False


class TaskWorker(QThread):
    """Выполняет произвольную функцию в отдельном потоке.

    Сигналы:
        succeeded(object)      — функция завершилась без исключения
        failed(str)            — текст ошибки
        progressed(int, int, str) — (сделано, всего, подпись)
    """

    succeeded = Signal(object)
    failed = Signal(str)
    progressed = Signal(int, int, str)

    def __init__(self, func, parent=None, with_progress: Optional[bool] = None):
        super().__init__(parent)
        self._func = func
        if with_progress is None:
            with_progress = _accepts_progress(func)
        self._with_progress = with_progress

    def run(self) -> None:
        original_stdin = sys.stdin
        sys.stdin = _BlockingStdin()
        try:
            if self._with_progress:
                progress = Progress(
                    lambda done, total, text: self.progressed.emit(done, total, text)
                )
                result = self._func(progress)
            else:
                result = self._func()
        except SystemExit as exc:
            code = exc.code
            if code in (0, None):
                self.succeeded.emit(None)
            elif isinstance(code, str):
                self.failed.emit(code)
            else:
                self.failed.emit(
                    f"Операция прервана (код выхода {code}). "
                    "Подробности — в системной консоли ниже."
                )
        except BaseException as exc:  # noqa: BLE001 — нужен полный перехват
            self.failed.emit(
                "".join(traceback.format_exception_only(type(exc), exc)).strip()
            )
        else:
            self.succeeded.emit(result)
        finally:
            sys.stdin = original_stdin
