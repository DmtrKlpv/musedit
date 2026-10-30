"""Вкладка «Скачивание с Яндекс.Музыки»: полный цикл в одном окне.

Пользователь вставляет код плейлиста (или выбирает готовый TXT), указывает
папку для музыки и имя плейлиста — на выходе получает папку с треками и
файл плейлиста, который на неё указывает.

Поля собраны из трёх прежних утилит: экспорт из Яндекс.Музыки, скачивание
и создание плейлистов. Логика каждого шага — в соответствующем движке,
здесь только сбор параметров и отображение хода работы.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..engines import pipeline, yamd
from ..widgets import ActionButton, PathField, action_row, make_spin
from .base import BaseTab

COL_TITLE = 0
COL_BITRATE = 1
COL_SIZE = 2
COL_STATUS = 3

# Цвета статусов берутся из темы: на тёмном фоне тёмно-зелёный нечитаем.
def _status_color(role: str) -> QColor:
    from ..theme import color as theme_color
    return theme_color(role)

FORMATS = ("m3u8", "m3u", "pls", "xspf", "wpl")


class DownloadHubTab(BaseTab):
    TITLE = "Скачивание с Яндекс.Музыки"

    # Строка трека из рабочего потока в GUI. Сигнал, а не прямой вызов:
    # таблицу можно менять безопасно в любой момент.
    track_row = Signal(dict)

    def __init__(self, main_window, parent=None):
        super().__init__(main_window, parent)

        self.track_row.connect(self._append_track_row)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Верхняя часть (источник + параметры + токен) может не поместиться
        # в невысоком окне. Без прокрутки QFormLayout начинал сжимать строки,
        # и поля превращались в полоски высотой 9 px. Поэтому верхняя часть
        # живёт в QScrollArea: при нехватке места появляется полоса
        # прокрутки, а высота полей остаётся нормальной.
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        top = QWidget(scroll)
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 6, 0)
        top_layout.setSpacing(8)

        # ---- источник списка треков ----
        top_layout.addWidget(self._bold("Источник списка треков (заполните одно из двух):"))

        self.iframe_edit = QPlainTextEdit(top)
        self.iframe_edit.setPlaceholderText(
            'Код iframe плейлиста Яндекс.Музыки, например:\n'
            '<iframe frameborder="0" style="border:none;width:100%;height:180px;" '
            'src="https://music.yandex.ru/iframe/#playlist/username/1234567"></iframe>'
        )
        self.iframe_edit.setMinimumHeight(72)
        self.iframe_edit.setMaximumHeight(96)
        top_layout.addWidget(self.iframe_edit)

        self.txt_field = PathField("file", "или готовый TXT-файл со списком треков")
        top_layout.addWidget(self.txt_field)

        # ---- параметры ----
        form = self.make_form()

        self.music_field = PathField("dir", "Куда скачивать музыку")
        form.addRow("Папка для музыки:", self.music_field)

        self.playlist_dir_field = PathField(
            "dir", "Куда сохранить плейлист (по умолчанию — папка для музыки)"
        )
        form.addRow("Папка для плейлиста:", self.playlist_dir_field)

        self.name_edit = QLineEdit(self)
        self.name_edit.setPlaceholderText("Например: Любимое")
        form.addRow("Имя плейлиста:", self.name_edit)

        self.format_combo = QComboBox()
        self.format_combo.addItems(FORMATS)
        self.format_combo.setCurrentText("m3u8")
        form.addRow("Формат плейлиста:", self.format_combo)

        self.timeout_spin = make_spin(1, 600, 15, " сек")
        form.addRow("Таймаут соединения:", self.timeout_spin)

        self.retries_spin = make_spin(1, 50, 3)
        form.addRow("Макс. количество попыток:", self.retries_spin)

        self.flac_check = QCheckBox("Скачивать FLAC, если доступно")
        form.addRow("Качество:", self.flac_check)

        self.absolute_check = QCheckBox("Записывать полные пути в плейлисте")
        form.addRow("Пути:", self.absolute_check)

        self.rel_edit = QLineEdit()
        self.rel_edit.setPlaceholderText("например: /music")
        form.addRow("Префикс пути:", self.rel_edit)

        top_layout.addLayout(form)

        # ---- токен ----
        token_row = QHBoxLayout()
        token_row.setContentsMargins(0, 0, 0, 0)
        token_row.setSpacing(6)
        token_row.addWidget(self._bold("Яндекс-токен:"))
        self.token_edit = QLineEdit(self)
        self.token_edit.setPlaceholderText("OAuth-токен; сохраняется в init.tok")
        token_row.addWidget(self.token_edit, 1)

        self.save_token_btn = QPushButton("Сохранить токен", self)
        self.save_token_btn.setMinimumHeight(32)
        self.save_token_btn.setFixedWidth(150)
        self.save_token_btn.clicked.connect(self.on_save_token)
        token_row.addWidget(self.save_token_btn)
        top_layout.addLayout(token_row)

        top_layout.addWidget(self.make_hint(
            "Что произойдёт по нажатию кнопки:\n"
            "1. Из кода плейлиста будет получен список треков "
            "(если выбрано поле iframe).\n"
            "2. Треки скачаются в папку для музыки, в подпапку с именем плейлиста.\n"
            "3. В папке для плейлиста появится файл с тем же именем — он ссылается "
            "на скачанные треки.\n"
            "Служебный TXT-список удаляется автоматически. "
            "Если указан готовый TXT-файл, шаг 1 пропускается."
        ))

        top_layout.addStretch(1)
        scroll.setWidget(top)
        layout.addWidget(scroll, 0)

        # ---- таблица треков ----
        layout.addWidget(self._bold("Скачанные треки:"))

        self.tracks_tree = QTreeWidget(self)
        self.tracks_tree.setHeaderLabels(["Название", "Битрейт", "Размер", "Статус"])
        self.tracks_tree.setRootIsDecorated(False)
        self.tracks_tree.setAlternatingRowColors(True)
        self.tracks_tree.setUniformRowHeights(True)
        self.tracks_tree.setSelectionMode(QTreeWidget.SingleSelection)
        self.tracks_tree.setEditTriggers(QTreeWidget.NoEditTriggers)

        header = self.tracks_tree.header()
        header.setSectionResizeMode(COL_TITLE, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_BITRATE, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_SIZE, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_STATUS, QHeaderView.ResizeToContents)
        self.tracks_tree.setMinimumHeight(140)
        layout.addWidget(self.tracks_tree, 1)

        self.run_btn = ActionButton("Скачать и создать плейлист", self,
                                    minimum_width=250)
        self.run_btn.clicked.connect(self.on_run)
        layout.addLayout(action_row(self.run_btn))

        self.add_progress(layout)

        self._load_config()

    # ------------------------------------------------------------------
    @staticmethod
    def _bold(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("font-weight:600;")
        return label

    def _load_config(self) -> None:
        try:
            config = yamd.load_config()
        except Exception:
            return
        token = config.get("TOKEN", "")
        if token:
            self.token_edit.setText(token)
        download_dir = config.get("DOWNLOAD_DIR", "")
        if download_dir:
            self.music_field.setText(download_dir)
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
    def on_run(self) -> None:
        iframe_code = self.iframe_edit.toPlainText().strip()
        txt_path = self.txt_field.text()

        if not iframe_code and not txt_path:
            QMessageBox.warning(
                self, "Нет источника",
                "Вставьте код iframe плейлиста или выберите TXT-файл со списком треков."
            )
            return

        music_root = self.music_field.text()
        if not music_root:
            QMessageBox.warning(self, "Не указана папка",
                                "Выберите папку, куда скачивать музыку.")
            return
        if not os.path.isdir(music_root):
            QMessageBox.warning(self, "Папка не найдена",
                                f"Папка для музыки не существует:\n{music_root}")
            return

        name = self.name_edit.text().strip()
        if not name:
            if txt_path:
                name = os.path.splitext(os.path.basename(txt_path))[0]
            else:
                QMessageBox.warning(self, "Не указано имя",
                                    "Введите имя плейлиста.")
                return
            self.name_edit.setText(name)

        token = self.token_edit.text().strip()
        if not token:
            token = yamd.load_config().get("TOKEN", "")
        if not token:
            QMessageBox.warning(
                self, "Нужен токен",
                "Укажите Яндекс-токен: без него авторизация невозможна."
            )
            return

        self.tracks_tree.clear()
        print("\n=== Скачивание с Яндекс.Музыки ===")

        params = dict(
            iframe_code=iframe_code,
            txt_path=txt_path,
            music_root=music_root,
            playlist_dir=self.playlist_dir_field.text() or None,
            playlist_name=name,
            playlist_format=self.format_combo.currentText(),
            absolute=self.absolute_check.isChecked(),
            rel_base=self.rel_edit.text().strip() or None,
            token=token,
            timeout=self.timeout_spin.value(),
            retries=self.retries_spin.value(),
            use_flac=self.flac_check.isChecked(),
            on_track=self.track_row.emit,
        )

        self.start_task(
            lambda progress: pipeline.run(progress=progress, **params),
            controls=[
                self.run_btn, self.iframe_edit, self.txt_field,
                self.music_field, self.playlist_dir_field, self.name_edit,
                self.format_combo, self.timeout_spin, self.retries_spin,
                self.flac_check, self.absolute_check, self.rel_edit,
                self.token_edit, self.save_token_btn,
            ],
            on_success=self._on_done,
            busy_text="Скачивание и сборка плейлиста",
        )

    # ------------------------------------------------------------------
    def _append_track_row(self, row) -> None:
        """Добавляет строку сразу после обработки трека."""
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
            colour = _status_color("row_new_fg")
        elif status == "Уже был":
            colour = _status_color("manual_border")
        elif status.startswith("Ошибка") or status == "Не найдено":
            colour = _status_color("row_missing_fg")
        else:
            colour = None
        if colour is not None:
            item.setForeground(COL_STATUS, QBrush(colour))

        self.tracks_tree.addTopLevelItem(item)
        self.tracks_tree.scrollToItem(item)

    def _on_done(self, result) -> None:
        if result is None:
            return

        rows = getattr(result, "rows", []) or []
        if self.tracks_tree.topLevelItemCount() < len(rows):
            for row in rows[self.tracks_tree.topLevelItemCount():]:
                self._append_track_row(row)

        if result.error:
            QMessageBox.warning(self, "Не удалось завершить", result.error)
            return

        QMessageBox.information(
            self, "Готово",
            f"{result.summary}\n\n"
            f"Музыка: {result.music_dir}\n"
            f"Плейлист: {result.playlist_path}"
        )
