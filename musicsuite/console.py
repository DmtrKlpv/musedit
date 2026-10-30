"""Консоль приложения: перехват stdout/stderr и вывод в текстовое поле.

Особенности:
  * в обычном режиме показываются только ошибки и информационные сообщения —
    прогресс-бары и служебные перечни отбрасываются, потому что ход работы
    виден на полосах прогресса вкладок;
  * переключатель «Все сообщения» возвращает полный поток;
  * возврат каретки '\\r' обрабатывается по правилам терминала: обновляется
    текущая строка, а не добавляются новые.
"""

import re
import sys
from typing import List, Tuple

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox,
    QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from .linebuf import LineBuffer
from .logfilter import MessageFilter

# Управляющие последовательности ANSI (цвета из исходных скриптов)
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")


def _strip_ansi_stream(text: str, carry: str) -> Tuple[str, str]:
    """Вырезает ANSI-коды, не теряя последовательность, разрезанную между write()."""
    text = carry + text
    carry = ""

    match = re.search(r"\x1b(?:\[[0-9;?]*)?$", text)
    if match:
        carry = text[match.start():]
        text = text[:match.start()]

    return _ANSI_RE.sub("", text), carry


class _StreamEmitter(QObject):
    """Передатчик текста из рабочего потока в GUI-поток (queued connection)."""

    text_ready = Signal(str)


class StreamRedirector:
    """Замена sys.stdout / sys.stderr, транслирующая записи в сигнал Qt."""

    encoding = "utf-8"
    errors = "replace"

    def __init__(self, emitter: _StreamEmitter):
        self._emitter = emitter
        self._ansi_carry = ""

    def writable(self) -> bool:
        return True

    def readable(self) -> bool:
        return False

    def isatty(self) -> bool:
        return False

    def write(self, text) -> int:
        if not text:
            return 0
        if not isinstance(text, str):
            text = str(text)
        clean, self._ansi_carry = _strip_ansi_stream(text, self._ansi_carry)
        if clean:
            self._emitter.text_ready.emit(clean)
        return len(text)

    def flush(self) -> None:
        return None


def split_lines(text: str) -> Tuple[List[str], str]:
    """Делит поток на завершённые строки и незавершённый хвост.

    Внутри завершённой строки '\r' применяется по семантике терминала:
    остаётся только текст после последнего возврата каретки.
    """
    text = text.replace("\r\n", "\n")
    parts = text.split("\n")
    tail = parts.pop()

    lines = []
    for part in parts:
        if "\r" in part:
            part = part.split("\r")[-1]
        lines.append(part)
    return lines, tail


class ConsoleView(QWidget):
    """Панель системной консоли с вертикальной прокруткой."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._autoscroll = True
        self._filter = MessageFilter(show_all=False)
        self._pending = ""
        self._live_buffer = LineBuffer()
        self._live_active = False
        # Позиция в документе, с которой началась «живая» строка.
        # Нужна, чтобы при завершении удалить ровно её, не задев предыдущие.
        self._live_start = None

        self.emitter = _StreamEmitter()
        self.emitter.text_ready.connect(self.feed)

        self.editor = QPlainTextEdit(self)
        self.editor.setReadOnly(True)
        self.editor.setUndoRedoEnabled(False)
        self.editor.setMaximumBlockCount(20000)
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.editor.setPlaceholderText(
            "Здесь появятся ошибки и информационные сообщения утилит."
        )
        # Консоль остаётся тёмной в обеих темах — как в IDE: так привычнее
        # читать лог, и цвета ANSI из скриптов рассчитаны на тёмный фон.
        # Цвета берутся из темы, чтобы на тёмной теме рамка не выбивалась.
        self.editor.setObjectName("consoleEditor")
        self._apply_console_style()

        header = QHBoxLayout()
        title = QLabel("Системная консоль")
        title.setStyleSheet("font-weight:600;")
        header.addWidget(title)

        self.mode_label = QLabel("ошибки и сообщения")
        self.mode_label.setProperty("role", "status")
        header.addWidget(self.mode_label)
        header.addStretch(1)

        self.all_box = QCheckBox("Все сообщения")
        self.all_box.setToolTip(
            "Показывать полный поток вывода, включая служебные строки и прогресс."
        )
        self.all_box.toggled.connect(self.set_show_all)
        header.addWidget(self.all_box)

        self.autoscroll_box = QCheckBox("Автопрокрутка")
        self.autoscroll_box.setChecked(True)
        self.autoscroll_box.toggled.connect(self._on_autoscroll)
        header.addWidget(self.autoscroll_box)

        clear_btn = QPushButton("Очистить")
        clear_btn.clicked.connect(self.clear)
        header.addWidget(clear_btn)

        save_btn = QPushButton("Сохранить лог...")
        save_btn.clicked.connect(self.save_log)
        header.addWidget(save_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addLayout(header)
        layout.addWidget(self.editor, 1)

    # ------------------------------------------------------------------
    def _apply_console_style(self) -> None:
        """Красит поле вывода цветами текущей темы."""
        from .theme import tokens
        t = tokens()
        self.editor.setStyleSheet(
            "QPlainTextEdit#consoleEditor {"
            f" background: {t.console_bg}; color: {t.console_fg};"
            " font-family: Consolas, 'Courier New', monospace; font-size: 9pt;"
            f" border: 1px solid {t.console_border}; }}"
        )

    def refresh_theme(self) -> None:
        """Вызывается главным окном после смены системной темы."""
        self._apply_console_style()

    # ------------------------------------------------------------------
    def install(self) -> None:
        """Перенаправляет стандартные потоки в поле вывода."""
        sys.stdout = StreamRedirector(self.emitter)
        sys.stderr = StreamRedirector(self.emitter)

    # ------------------------------------------------------------------
    def feed(self, text: str) -> None:
        """Принимает порцию текста и обновляет поле вывода."""
        if not text:
            return

        self._pending += text
        lines, self._pending = split_lines(self._pending)

        if lines:
            self._finish_live()
            kept = [line for line in lines if self._filter.keep(line)]
            if kept:
                self._append("\n".join(kept))
        elif self._filter.show_all and self._pending:
            self._render_live(self._pending)

    # ------------------------------------------------------------------
    def _append(self, text: str) -> None:
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.End)

        if not self.editor.document().isEmpty():
            cursor.insertText("\n")
        cursor.insertText(text)

        # Убираем хвостовые пустые строки, чтобы консоль не «росла» вниз.
        while text.endswith("\n"):
            text = text[:-1]

        self.editor.setTextCursor(cursor)
        self._scroll_if_needed()

    def _render_live(self, partial: str) -> None:
        """Показывает незавершённую строку с корректной обработкой '\\r'."""
        self._live_buffer.clear()
        lines, _ = split_lines(partial)
        for line in lines:
            self._live_buffer.feed(line + "\n")

        current = partial.replace("\r\n", "\n")
        if "\r" in current:
            current = current.split("\r")[-1]
        current = current.split("\n")[-1]

        if not self._filter.keep(current):
            return

        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.End)

        if self._live_active:
            # Строка уже показана — перерисовываем её содержимое.
            block = cursor.block()
            cursor.setPosition(block.position())
            cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
            cursor.insertText(current)
        else:
            # Запоминаем позицию ДО вставки: с неё начнётся живая строка.
            self._live_start = len(self.editor.toPlainText())
            if not self.editor.document().isEmpty():
                cursor.insertText("\n")
            cursor.insertText(current)
            self._live_active = True

        cursor.movePosition(QTextCursor.End)
        self.editor.setTextCursor(cursor)
        self._scroll_if_needed()

    def _finish_live(self) -> None:
        """Убирает «живую» строку перед добавлением её же как завершённой.

        print() вызывает write() дважды: сначала текст, потом "\n".
        После первого вызова строка показывается как незавершённая (живая),
        после второго — добавляется обычным путём. Без удаления живой строки
        она оставалась в поле, и каждая строка появлялась дважды — этот баг
        был виден в конвертере CUE.
        """
        if (self._live_active and self._live_start is not None
                and not self.editor.document().isEmpty()):
            cursor = self.editor.textCursor()
            # Возвращаем документ к состоянию до отрисовки живой строки:
            # удаляем всё от запомненной позиции до конца.
            cursor.setPosition(self._live_start)
            cursor.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
            cursor.removeSelectedText()
            cursor.movePosition(QTextCursor.End)
            self.editor.setTextCursor(cursor)

        self._live_active = False
        self._live_start = None
        self._live_buffer.clear()

    # ------------------------------------------------------------------
    def set_show_all(self, show_all: bool) -> None:
        """Переключает режим «показывать всё»."""
        self._filter.show_all = bool(show_all)
        self.mode_label.setText(
            "полный поток" if show_all else "ошибки и сообщения"
        )

    def _scroll_if_needed(self) -> None:
        if not self._autoscroll:
            return
        bar = self.editor.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _on_autoscroll(self, enabled: bool) -> None:
        self._autoscroll = bool(enabled)

    # ------------------------------------------------------------------
    def clear(self) -> None:
        self.editor.clear()
        self._pending = ""
        self._finish_live()

    def save_log(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить лог", "log.txt",
            "Текстовые файлы (*.txt);;Все файлы (*.*)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.editor.toPlainText())
        except OSError as exc:
            QMessageBox.critical(
                self, "Ошибка", f"Не удалось сохранить файл:\n{exc}"
            )
