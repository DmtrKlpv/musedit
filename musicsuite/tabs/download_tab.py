"""Вкладка 2: Скачивание из Яндекс.Музыки (yamd.py)."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from ..engines import yamd
from ..widgets import ActionButton, PathField, action_row, make_spin
from .base import BaseTab

COL_TITLE = 0
COL_BITRATE = 1
COL_SIZE = 2
COL_STATUS = 3

COLOR_OK = "#15803d"
COLOR_SKIP = "#a16207"
COLOR_ERROR = "#b91c1c"


class DownloadTab(BaseTab):
    TITLE = "Скачивание из Яндекс.Музыки"

    # Строка скачанного трека из рабочего потока в GUI-поток.
    # Сигнал, а не прямой вызов: Qt поставит обработчик в очередь главного
    # потока, поэтому таблицу можно менять безопасно в любой момент.
    track_row = Signal(dict)

    def __init__(self, main_window, parent=None):
        super().__init__(main_window, parent)

        self.track_row.connect(self._append_track_row)
        self._row_count = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        form = self.make_form()

        self.playlist_field = PathField("file", "Путь к TXT-файлу со списком треков")
        form.addRow("TXT-файл плейлиста:", self.playlist_field)

        self.dir_field = PathField("dir", "Папка для скачивания")
        form.addRow("Папка для скачивания:", self.dir_field)

        self.timeout_spin = make_spin(1, 600, 15, " сек")
        form.addRow("Таймаут соединения:", self.timeout_spin)

        self.retries_spin = make_spin(1, 50, 3)
        form.addRow("Макс. количество попыток:", self.retries_spin)

        self.flac_check = QCheckBox("Скачивать FLAC, если доступно")
        self.flac_check.setChecked(False)
        form.addRow("Качество:", self.flac_check)

        layout.addLayout(form)

        layout.addWidget(self._separator())

        layout.addWidget(self._label_bold("Яндекс-токен (сохраняется в init.tok):"))
        token_row = QHBoxLayout()
        self.token_edit = QLineEdit(self)
        self.token_edit.setPlaceholderText("Вставьте OAuth-токен Яндекс.Музыки")
        token_row.addWidget(self.token_edit, 1)

        self.save_token_btn = QPushButton("Сохранить токен", self)
        self.save_token_btn.setMinimumHeight(34)
        self.save_token_btn.setMinimumWidth(150)
        self.save_token_btn.clicked.connect(self.on_save_token)
        token_row.addWidget(self.save_token_btn)
        layout.addLayout(token_row)

        layout.addWidget(self.make_hint(
            "Токен нужен для авторизации через API Яндекс.Музыки. "
            "При успешной авторизации он автоматически записывается в файл init.tok "
            "рядом с приложением и подставляется при следующем запуске. "
            "Настройки DOWNLOAD_DIR, TIMEOUT и MAX_RETRIES также читаются из init.tok, "
            "если поля выше оставлены по умолчанию."
        ))

        # ---- таблица скачанных треков ----
        layout.addWidget(self._label_bold("Скачанные треки:"))
        self.tracks_tree = QTreeWidget(self)
        self.tracks_tree.setHeaderLabels(["Название", "Битрейт", "Размер", "Статус"])
        self.tracks_tree.setRootIsDecorated(False)
        self.tracks_tree.setAlternatingRowColors(True)
        self.tracks_tree.setUniformRowHeights(True)
        self.tracks_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tracks_tree.setEditTriggers(QAbstractItemView.NoEditTriggers)

        header = self.tracks_tree.header()
        header.setSectionResizeMode(COL_TITLE, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_BITRATE, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_SIZE, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_STATUS, QHeaderView.ResizeToContents)
        self.tracks_tree.setColumnWidth(COL_BITRATE, 130)
        self.tracks_tree.setColumnWidth(COL_SIZE, 100)
        self.tracks_tree.setColumnWidth(COL_STATUS, 130)
        self.tracks_tree.setMinimumHeight(150)
        layout.addWidget(self.tracks_tree, 1)

        self.run_btn = ActionButton("Начать скачивание", self, minimum_width=190)
        self.run_btn.clicked.connect(self.on_download)
        layout.addLayout(action_row(self.run_btn))

        self.add_progress(layout)

        self._load_token()

    # ------------------------------------------------------------------
    @staticmethod
    def _label_bold(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("font-weight:600;")
        return label

    @staticmethod
    def _separator() -> QLabel:
        line = QLabel()
        line.setFixedHeight(1)
        line.setStyleSheet("background:#e0e0e0;")
        return line

    def _load_token(self) -> None:
        try:
            config = yamd.load_config()
        except Exception:
            return
        token = config.get("TOKEN", "")
        if token:
            self.token_edit.setText(token)
        download_dir = config.get("DOWNLOAD_DIR", "")
        if download_dir:
            self.dir_field.setText(download_dir)
        try:
            self.timeout_spin.setValue(int(config.get("TIMEOUT", 15)))
            self.retries_spin.setValue(int(config.get("MAX_RETRIES", 3)))
        except (TypeError, ValueError):
            pass

    def on_save_token(self) -> None:
        token = self.token_edit.text().strip()
        if not token:
            QMessageBox.warning(self, "Нет токена",
                                "Введите токен перед сохранением.")
            return
        try:
            config = yamd.load_config()
            config["TOKEN"] = token
            yamd.save_config(config)
        except OSError as exc:
            QMessageBox.critical(self, "Ошибка",
                                 f"Не удалось записать init.tok:\n{exc}")
            return
        print(f"[+] Токен сохранён в init.tok ({os.path.abspath('init.tok')})")
        QMessageBox.information(
            self, "Сохранено",
            "Токен записан в init.tok и будет использован при скачивании."
        )

    # ------------------------------------------------------------------
    def on_download(self) -> None:
        playlist = self.playlist_field.text()
        if not playlist:
            QMessageBox.warning(self, "Не указан файл",
                                "Выберите TXT-файл со списком треков.")
            return

        token = self.token_edit.text().strip()
        if not token:
            config = yamd.load_config()
            token = config.get("TOKEN", "")
        if not token:
            QMessageBox.warning(
                self, "Нужен токен",
                "Укажите Яндекс-токен: без него авторизация невозможна."
            )
            return

        download_dir = self.dir_field.text()
        timeout = self.timeout_spin.value()
        retries = self.retries_spin.value()
        use_flac = self.flac_check.isChecked()

        self.tracks_tree.clear()
        self._row_count = 0
        print("\n=== Скачивание из Яндекс.Музыки ===")

        self.start_task(
            lambda progress: yamd.download(
                playlist, download_dir, timeout, retries, use_flac, token,
                progress=progress,
                on_track=self.track_row.emit,
            ),
            controls=[
                self.run_btn, self.playlist_field, self.dir_field,
                self.timeout_spin, self.retries_spin, self.flac_check,
                self.token_edit, self.save_token_btn,
            ],
            on_success=self._on_finished,
            busy_text="Подготовка к скачиванию",
        )

    # ------------------------------------------------------------------
    def _append_track_row(self, row) -> None:
        """Добавляет одну строку в таблицу сразу после обработки трека."""
        if not isinstance(row, dict):
            return

        status = str(row.get("status", ""))
        item = QTreeWidgetItem([
            str(row.get("title", "")),
            str(row.get("bitrate", "—")),
            str(row.get("size", "—")),
            status,
        ])
        item.setToolTip(COL_TITLE, str(row.get("title", "")))

        if status == "Скачано":
            colour = COLOR_OK
        elif status == "Уже был":
            colour = COLOR_SKIP
        elif status.startswith("Ошибка") or status == "Не найдено":
            colour = COLOR_ERROR
        else:
            colour = None
        if colour:
            item.setForeground(COL_STATUS, QBrush(QColor(colour)))

        self.tracks_tree.addTopLevelItem(item)
        self.tracks_tree.scrollToItem(item)
        self._row_count = getattr(self, "_row_count", 0) + 1

    def _on_finished(self, result) -> None:
        if not isinstance(result, dict):
            QMessageBox.information(
                self, "Готово",
                "Процесс скачивания завершён. Подробности — в консоли."
            )
            return

        rows = result.get("rows") or []
        for row in rows:
            item = QTreeWidgetItem([
                str(row.get("title", "")),
                str(row.get("bitrate", "—")),
                str(row.get("size", "—")),
                str(row.get("status", "")),
            ])
            item.setToolTip(COL_TITLE, str(row.get("title", "")))
            self.tracks_tree.addTopLevelItem(item)

        downloaded = result.get("downloaded", 0)
        total = result.get("total", 0)
        target = result.get("target_dir", "")

        QMessageBox.information(
            self, "Готово",
            f"Скачано треков: {downloaded} из {total}.\n\nПапка: {target}"
        )
