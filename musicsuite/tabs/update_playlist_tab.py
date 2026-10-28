"""Вкладка «Обновление плейлиста»: сравнение плейлиста с папкой в двух таблицах.

Сценарий: открыт существующий плейлист, рядом — папка со свежими файлами.
Слева видно, что записано в плейлисте, справа — что реально лежит в папке.
Несоответствия подсвечиваются сразу после открытия файлов, без запуска задачи:

  * пропавшие из папки строки — розовые;
  * новые файлы, которых нет в плейлисте, — светло-зелёные;
  * совпавшие — обычным цветом.

Кнопка «Обновить плейлист» записывает файл ровно по тому составу, который
показан в левой таблице: пропавшие убираются, новые дописываются в конец.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..engines import update_playlist as engine
from ..widgets import ActionButton, PathField, action_row
from .base import BaseTab

COL_STATE = 0
COL_TRACK = 1
COL_PATH = 2

BG_MISSING = QColor("#fde2e4")   # розовый: файла нет в папке
BG_NEW = QColor("#e3f6e5")       # светло-зелёный: файла нет в плейлисте
FG_MISSING = QColor("#9f1239")
FG_NEW = QColor("#166534")

STATE_TEXT = {
    "kept": "В плейлисте",
    "missing": "Нет в папке",
    "new": "Новый файл",
}


class UpdatePlaylistTab(BaseTab):
    TITLE = "Обновление плейлиста"

    scan_finished = Signal(object)

    def __init__(self, main_window, parent=None):
        super().__init__(main_window, parent)

        self._result = engine.CompareResult()
        self._entries = []
        self._files = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        form = self.make_form()

        self.playlist_field = PathField(
            "file", "Файл плейлиста: m3u, m3u8, pls, xspf или wpl"
        )
        form.addRow("Плейлист для обновления:", self.playlist_field)

        self.folder_field = PathField(
            "dir", "Папка с треками, по которой сверяется плейлист"
        )
        form.addRow("Папка для сканирования:", self.folder_field)

        self.absolute_check = QCheckBox("Записывать полные пути к файлам")
        form.addRow("Пути:", self.absolute_check)

        self.rel_edit = QLineEdit()
        self.rel_edit.setPlaceholderText("например: /music")
        form.addRow("Префикс пути:", self.rel_edit)

        self.format_combo = QComboBox()
        self.format_combo.addItems(["как в файле", "m3u", "m3u8", "pls", "xspf", "wpl"])
        self.format_combo.setCurrentIndex(0)
        self.format_combo.setToolTip(
            "Формат определяется по расширению открытого плейлиста и не меняется: "
            "так сохраняется совместимость с плеером и сервером."
        )
        form.addRow("Формат при сохранении:", self.format_combo)

        layout.addLayout(form)

        layout.addWidget(self.make_hint(
            "Откройте плейлист и папку — сравнение выполнится сразу.\n"
            "• Розовые строки слева — файла больше нет в папке: при обновлении "
            "он будет убран из плейлиста.\n"
            "• Светло-зелёные строки справа — новый файл, которого нет в плейлисте: "
            "он будет дописан в конец.\n"
            "Снятая галочка «Сохранять в плейлисте пропавшие треки» оставляет "
            "розовые строки на месте. Порядок существующих треков сохраняется."
        ))

        # ---- две таблицы рядом ----
        splitter = QSplitter(Qt.Horizontal, self)

        left_box = QWidget(self)
        left_layout = QVBoxLayout(left_box)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)
        self.playlist_title = self._bold("Плейлист: не открыт")
        left_layout.addWidget(self.playlist_title)

        self.playlist_tree = QTreeWidget(left_box)
        self.playlist_tree.setHeaderLabels(["Статус", "Трек", "Путь в плейлисте"])
        self.playlist_tree.setRootIsDecorated(False)
        self.playlist_tree.setAlternatingRowColors(True)
        self.playlist_tree.setUniformRowHeights(True)
        self.playlist_tree.setSelectionMode(QTreeWidget.SingleSelection)
        self.playlist_tree.setEditTriggers(QTreeWidget.NoEditTriggers)
        self.playlist_tree.setMinimumHeight(180)
        left_header = self.playlist_tree.header()
        left_header.setSectionResizeMode(COL_STATE, QHeaderView.ResizeToContents)
        left_header.setSectionResizeMode(COL_TRACK, QHeaderView.Stretch)
        left_header.setSectionResizeMode(COL_PATH, QHeaderView.Stretch)
        left_layout.addWidget(self.playlist_tree, 1)
        splitter.addWidget(left_box)

        right_box = QWidget(self)
        right_layout = QVBoxLayout(right_box)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)
        self.folder_title = self._bold("Папка: не выбрана")
        right_layout.addWidget(self.folder_title)

        self.folder_tree = QTreeWidget(right_box)
        self.folder_tree.setHeaderLabels(["Статус", "Файл", "Полный путь"])
        self.folder_tree.setRootIsDecorated(False)
        self.folder_tree.setAlternatingRowColors(True)
        self.folder_tree.setUniformRowHeights(True)
        self.folder_tree.setSelectionMode(QTreeWidget.SingleSelection)
        self.folder_tree.setEditTriggers(QTreeWidget.NoEditTriggers)
        self.folder_tree.setMinimumHeight(180)
        right_header = self.folder_tree.header()
        right_header.setSectionResizeMode(COL_STATE, QHeaderView.ResizeToContents)
        right_header.setSectionResizeMode(COL_TRACK, QHeaderView.Stretch)
        right_header.setSectionResizeMode(COL_PATH, QHeaderView.Stretch)
        right_layout.addWidget(self.folder_tree, 1)
        splitter.addWidget(right_box)

        splitter.setSizes([600, 600])
        layout.addWidget(splitter, 1)

        # ---- счётчики ----
        self.counts_label = QLabel("Общее количество записей: плейлист 0, папка 0")
        self.counts_label.setStyleSheet("font-weight:600;")
        layout.addWidget(self.counts_label)

        self.detail_label = QLabel("")
        self.detail_label.setStyleSheet("color:#6b7280;")
        layout.addWidget(self.detail_label)

        option_row = QHBoxLayout()
        option_row.setContentsMargins(0, 0, 0, 0)
        option_row.setSpacing(16)
        self.keep_missing_check = QCheckBox("Сохранять в плейлисте пропавшие треки")
        self.keep_missing_check.setChecked(False)
        option_row.addWidget(self.keep_missing_check)
        option_row.addStretch(1)
        layout.addLayout(option_row)

        self.run_btn = ActionButton("Обновить плейлист", self, minimum_width=190)
        self.run_btn.clicked.connect(self.on_update)
        self.run_btn.setEnabled(False)
        layout.addLayout(action_row(self.run_btn))

        self.add_progress(layout)

        # ---- автоматическое сканирование при выборе файлов ----
        self.playlist_field.edit.textChanged.connect(self._on_paths_changed)
        self.folder_field.edit.textChanged.connect(self._on_paths_changed)
        self.scan_finished.connect(self._on_scan_ready)

    # ------------------------------------------------------------------
    @staticmethod
    def _bold(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("font-weight:600;")
        return label

    def _on_paths_changed(self) -> None:
        """Пересобирает списки, как только оба пути указывают на существующие объекты."""
        playlist = self.playlist_field.text()
        folder = self.folder_field.text()
        if playlist and folder and os.path.isfile(playlist) and os.path.isdir(folder):
            self._start_scan(playlist, folder)

    def _start_scan(self, playlist: str, folder: str) -> None:
        self.playlist_tree.clear()
        self.folder_tree.clear()
        self.run_btn.setEnabled(False)
        self.detail_label.setText("Сканирование папки...")

        self.start_task(
            lambda progress: engine.compare(playlist, folder, progress=progress),
            controls=[self.playlist_field, self.folder_field,
                      self.absolute_check, self.rel_edit, self.format_combo],
            on_success=self.scan_finished.emit,
            busy_text="Сканирование папки",
            use_progress=True,
        )

    # ------------------------------------------------------------------
    def _on_scan_ready(self, result) -> None:
        if result is None:
            return

        self._result = result
        if result.error:
            self.detail_label.setText(result.error)
            self.counts_label.setText("Общее количество записей: 0")
            self.run_btn.setEnabled(False)
            QMessageBox.warning(self, "Не удалось сравнить", result.error)
            return

        self._entries = list(result.entries)
        self._files = list(result.files)
        self._fill_tables()
        self.run_btn.setEnabled(True)

    def _fill_tables(self) -> None:
        self.playlist_tree.clear()
        self.folder_tree.clear()

        for entry in self._entries:
            item = QTreeWidgetItem([
                STATE_TEXT.get(entry.state, ""),
                os.path.basename(entry.original) or entry.original,
                entry.original,
            ])
            item.setToolTip(COL_TRACK, entry.original)
            item.setToolTip(COL_PATH, entry.matched or "файл не найден")
            if entry.state == "missing":
                self._paint(item, BG_MISSING, FG_MISSING)
            self.playlist_tree.addTopLevelItem(item)

        for entry in self._files:
            item = QTreeWidgetItem([
                STATE_TEXT.get(entry.state, ""),
                entry.display,
                entry.full_path,
            ])
            item.setToolTip(COL_TRACK, entry.display)
            item.setToolTip(COL_PATH, entry.full_path)
            if entry.state == "new":
                self._paint(item, BG_NEW, FG_NEW)
            self.folder_tree.addTopLevelItem(item)

        name = os.path.basename(self._result.playlist_path)
        self.playlist_title.setText(f"Плейлист: {name}")
        self.folder_title.setText(f"Папка: {self._result.music_dir}")

        total = len(self._entries) + len(self._files)
        self.counts_label.setText(
            f"Общее количество записей: {total} "
            f"(в плейлисте {len(self._entries)}, в папке {len(self._files)})"
        )
        self.detail_label.setText(
            f"Нет в папке: {len(self._result.missing)}   •   "
            f"Новых файлов: {len(self._result.new)}   •   "
            f"Совпало: {len(self._result.kept)}   •   "
            f"Формат: {self._result.format}"
        )

    @staticmethod
    def _paint(item: QTreeWidgetItem, background: QColor, foreground: QColor) -> None:
        brush_bg = QBrush(background)
        brush_fg = QBrush(foreground)
        for column in (COL_STATE, COL_TRACK, COL_PATH):
            item.setBackground(column, brush_bg)
            item.setForeground(column, brush_fg)

    # ------------------------------------------------------------------
    def on_update(self) -> None:
        playlist = self.playlist_field.text()
        if not playlist:
            QMessageBox.warning(
                self, "Не указан плейлист",
                "Выберите файл плейлиста, который нужно обновить.",
            )
            return
        if not os.path.isfile(playlist):
            QMessageBox.warning(
                self, "Файл не найден",
                f"Плейлист не существует:\n{playlist}\n\n"
                "Обновлять можно только существующий файл. Чтобы создать новый, "
                "используйте вкладку «Создание плейлистов».",
            )
            return
        if not self._entries:
            QMessageBox.warning(
                self, "Нет данных",
                "Сначала откройте плейлист и папку для сканирования.",
            )
            return

        # Новые файлы дописываем в конец, чтобы пользователь видел итог в таблице.
        entries = list(self._entries)
        for entry in self._result.new:
            entries.append(engine.PlaylistEntry(
                original=entry.full_path,
                normalized=entry.normalized,
                matched=entry.full_path,
            ))

        absolute = self.absolute_check.isChecked()
        rel_base = self.rel_edit.text().strip() or None
        keep_missing = self.keep_missing_check.isChecked()

        self._pending_entries = entries
        self.start_task(
            lambda progress: engine.apply_comparison(
                playlist, entries, music_dir=self.folder_field.text() or None,
                keep_missing=keep_missing,
                absolute=absolute, rel_base=rel_base, progress=progress,
            ),
            controls=[self.run_btn, self.playlist_field, self.folder_field,
                      self.absolute_check, self.rel_edit, self.format_combo,
                      self.keep_missing_check],
            on_success=self._on_written,
            busy_text="Запись плейлиста",
        )

    def _on_written(self, result) -> None:
        if result is None:
            return
        if result.error:
            QMessageBox.warning(self, "Не удалось обновить", result.error)
            return

        QMessageBox.information(self, "Готово", result.summary)

        # Перечитываем файл, чтобы таблицы показывали уже записанное состояние.
        playlist = self.playlist_field.text()
        folder = self.folder_field.text()
        if playlist and folder:
            self._start_scan(playlist, folder)
