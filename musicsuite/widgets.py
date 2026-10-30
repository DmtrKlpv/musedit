"""Переиспользуемые виджеты: поле пути, спинбокс, акцентная кнопка, прогресс-панель."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QProgressBar, QPushButton,
    QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)


class PathField(QWidget):
    """Поле пути + кнопки выбора файла и/или папки через стандартный Проводник."""

    def __init__(self, mode="dir", placeholder="", parent=None):
        super().__init__(parent)
        self._mode = mode  # "dir" | "file" | "both" | "save"

        self.edit = QLineEdit(self)
        self.edit.setPlaceholderText(placeholder)
        self.edit.setClearButtonEnabled(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.edit, 1)

        if mode in ("file", "both", "save"):
            self.file_btn = QPushButton("Файл...", self)
            self.file_btn.clicked.connect(self._browse_file)
            layout.addWidget(self.file_btn)

        if mode in ("dir", "both"):
            self.dir_btn = QPushButton("Папка...", self)
            self.dir_btn.clicked.connect(self._browse_dir)
            layout.addWidget(self.dir_btn)

    # ------------------------------------------------------------------
    def _start_dir(self) -> str:
        current = self.edit.text().strip()
        if not current:
            return ""
        if os.path.isdir(current):
            return current
        parent = os.path.dirname(current)
        return parent if os.path.isdir(parent) else ""

    def _browse_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите файл", self._start_dir(), "Все файлы (*.*)"
        )
        if path:
            self.edit.setText(path)

    def _browse_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Выберите папку", self._start_dir()
        )
        if path:
            self.edit.setText(path)

    # ------------------------------------------------------------------
    def text(self) -> str:
        return self.edit.text().strip()

    def setText(self, value: str) -> None:
        self.edit.setText(value or "")

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802 — API Qt
        super().setEnabled(enabled)
        self.edit.setEnabled(enabled)
        for name in ("file_btn", "dir_btn"):
            button = getattr(self, name, None)
            if button is not None:
                button.setEnabled(enabled)


class SavePathField(PathField):
    """Поле с кнопкой «Сохранить как...» — для выбора итогового файла."""

    def __init__(self, placeholder="", filter_text="Все файлы (*.*)", parent=None,
                 default_suffix=".txt"):
        super().__init__("save", placeholder, parent)
        self._filter = filter_text
        self._suffix = default_suffix
        self.file_btn.setText("Сохранить как...")
        self.file_btn.clicked.disconnect()
        self.file_btn.clicked.connect(self._browse_save)

    def _browse_save(self) -> None:
        start = self.edit.text().strip() or ""
        path, _ = QFileDialog.getSaveFileName(
            self, "Укажите файл для сохранения", start, self._filter
        )
        if not path:
            return
        if self._suffix and not os.path.splitext(path)[1]:
            path += self._suffix
        self.edit.setText(path)


def make_spin(minimum: int, maximum: int, value: int, suffix: str = "") -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(minimum, maximum)
    spin.setValue(value)
    spin.setAlignment(Qt.AlignLeft)
    if suffix:
        spin.setSuffix(suffix)
    return spin


class ActionButton(QPushButton):
    """Синяя акцентная кнопка фиксированной ширины — не растягивается на всю строку."""

    def __init__(self, text: str, parent=None, minimum_width: int = 190):
        super().__init__(text, parent)
        self.setObjectName("primary")
        self.setMinimumHeight(34)
        self.setMinimumWidth(minimum_width)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)


def action_row(*widgets, stretch_before: bool = True) -> QHBoxLayout:
    """Горизонтальный ряд: [растяжка] + кнопки, прижатые вправо."""
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    if stretch_before:
        row.addStretch(1)
    for widget in widgets:
        if widget is not None:
            row.addWidget(widget)
    return row


class ProgressPanel(QWidget):
    """Полоса прогресса + подпись: заменяет прогресс-строки в консоли."""

    def __init__(self, parent=None, text_width: int = 380):
        super().__init__(parent)

        self.bar = QProgressBar(self)
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(True)
        self.bar.setFormat("%p%")
        self.bar.setMinimumHeight(20)
        self.bar.setMaximumHeight(20)

        self.text_label = QLabel("Готов к работе", self)
        self.text_label.setProperty("role", "status")
        self.text_label.setMinimumWidth(text_width)
        self.text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.text_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        self.counter_label = QLabel("", self)
        self.counter_label.setProperty("role", "status")
        self.counter_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.counter_label.setMinimumWidth(96)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(self.text_label, 1)
        row.addWidget(self.counter_label)
        row.addWidget(self.bar, 2)

    # ------------------------------------------------------------------
    def reset(self) -> None:
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setFormat("%p%")
        self.text_label.setText("Готов к работе")
        self.counter_label.setText("")

    def set_text(self, text: str) -> None:
        if text:
            self.text_label.setText(text)

    def set_busy(self, text: str = "") -> None:
        """Неопределённый прогресс — когда общее число шагов неизвестно."""
        self.bar.setRange(0, 0)
        self.bar.setFormat("")
        if text:
            self.text_label.setText(text)
        self.counter_label.setText("")

    def set_progress(self, done: int, total: int, text: str = "") -> None:
        if text:
            self.text_label.setText(text)

        if total <= 0:
            if self.bar.maximum() != 0:
                self.set_busy()
            return

        if self.bar.maximum() == 0:
            self.bar.setRange(0, 100)
            self.bar.setFormat("%p%")

        clamped = max(0, min(done, total))
        percent = int(round(100.0 * clamped / total))
        self.bar.setValue(percent)
        self.counter_label.setText(f"{clamped} / {total}")

    def finish(self, text: str = "Готово") -> None:
        if self.bar.maximum() == 0:
            self.bar.setRange(0, 100)
            self.bar.setFormat("%p%")
        self.bar.setValue(100 if self.bar.maximum() == 100 else self.bar.maximum())
        self.text_label.setText(text)
        self.counter_label.setText("")
