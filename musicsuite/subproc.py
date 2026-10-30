"""Запуск внешних программ без всплывающего консольного окна.

Проблема
--------
На Windows каждое GUI-приложение запускает дочерний консольный процесс
в новом окне: `subprocess.run(["ffmpeg", ...])` открывает чёрное окно
командной строки, которое мигает или висит на экране. Для FFmpeg, который
вызывается на каждый трек, это особенно заметно — окно появляется десятки
раз и отбирает фокус у главного окна.

Решение — флаг создания процесса CREATE_NO_WINDOW (0x08000000). Он просит
Windows не создавать консоль для дочернего процесса. На Linux и macOS
флаг не нужен: там отдельного окна не возникает.

Кроме того, при сборке через PyInstaller в режиме --noconsole у процесса
нет собственной консоли, и без флага дочерние программы могут вообще
не запуститься — так что этот модуль нужен ещё и для стабильности.
"""

from __future__ import annotations

import subprocess
import sys

# CREATE_NO_WINDOW: дочерний процесс не получает своё консольное окно.
# CREATE_NEW_PROCESS_GROUP не берём: он мешает Ctrl+C и не нужен для GUI.
_CREATE_NO_WINDOW = 0x08000000


def popen_kwargs() -> dict:
    """Дополнительные аргументы для subprocess на текущей платформе.

    Возвращает пустой словарь вне Windows, поэтому вызов одинаков
    на всех ОС.
    """
    if sys.platform == "win32":
        return {"creationflags": _CREATE_NO_WINDOW}
    return {}


def run(cmd, check: bool = False, capture_output: bool = False,
        timeout: float | None = None, **kwargs):
    """Замена subprocess.run без окна консоли.

    Параметры те же, что у subprocess.run; добавляется только скрытие окна.
    """
    kwargs.update(popen_kwargs())
    if capture_output:
        kwargs["capture_output"] = True
    if timeout is not None:
        kwargs["timeout"] = timeout
    return subprocess.run(cmd, check=check, **kwargs)


def popen(cmd, **kwargs):
    """Замена subprocess.Popen без окна консоли."""
    kwargs.update(popen_kwargs())
    return subprocess.Popen(cmd, **kwargs)


def run_quiet(cmd, check: bool = True, timeout: float | None = None):
    """Запускает программу, подавляя её вывод целиком.

    Нужно для FFmpeg: он пишет служебные сообщения в stderr, которые
    в приложении не нужны — прогресс и так виден на полосе.
    """
    return run(cmd, check=check, capture_output=True, timeout=timeout)
