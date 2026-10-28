"""Вкладка 3: Создание плейлистов (plscreate.py)."""

from __future__ import annotations

import argparse

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QLabel, QLineEdit, QMessageBox, QVBoxLayout,
)

from ..engines import plscreate
from ..widgets import ActionButton, PathField, action_row
from .base import BaseTab

FORMATS = ["m3u", "m3u8", "pls", "xspf", "wpl"]


class PlaylistTab(BaseTab):
    TITLE = "Создание плейлистов"

    def __init__(self, main_window, parent=None):
        super().__init__(main_window, parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        form = self.make_form()

        self.music_field = PathField("dir", "Папка с музыкой")
        form.addRow("Путь к музыке:", self.music_field)

        self.save_field = PathField("dir", "Куда сохранять плейлисты")
        form.addRow("Папка для сохранения:", self.save_field)

        self.format_combo = QComboBox()
        self.format_combo.addItems(FORMATS)
        self.format_combo.setCurrentText("m3u8")
        form.addRow("Формат плейлиста:", self.format_combo)

        self.list_field = PathField("file", "TXT-файл со списком треков (необязательно)")
        form.addRow("Список треков из TXT:", self.list_field)

        self.mass_field = PathField("dir", "Папка с TXT-файлами (необязательно)")
        form.addRow("Массовое создание из TXT:", self.mass_field)

        self.search_field = PathField("dir", "Где искать треки (необязательно)")
        form.addRow("Папка для поиска треков:", self.search_field)

        self.absolute_check = QCheckBox("Использовать абсолютные пути")
        form.addRow("Пути:", self.absolute_check)

        self.rel_edit = QLineEdit()
        self.rel_edit.setPlaceholderText("например: /music")
        form.addRow("Префикс относительного пути:", self.rel_edit)

        self.name_check = QCheckBox(
            "Использовать название папки как название плейлиста"
        )
        form.addRow("Заголовок:", self.name_check)

        layout.addLayout(form)

        layout.addWidget(self.make_hint(
            "Выберите один из режимов, заполнив соответствующее поле:\n"
            "• Папка с музыкой — каждая вложенная папка становится отдельным плейлистом "
            "со всеми треками из неё. Поля TXT ниже оставьте пустыми.\n"
            "• TXT-файл со списком треков — создаётся один плейлист; каждая строка файла "
            "ищется как название трека в папке для поиска.\n"
            "• Папка с TXT-файлами — для каждого TXT-файла создаётся свой плейлист.\n"
            "Галочка «Абсолютные пути» записывает полные пути на диске. Без неё пути относительные. "
            "Префикс (например /music) добавляется перед путём — это нужно для Navidrome и других серверов."
        ))

        self.run_btn = ActionButton("Сгенерировать", self, minimum_width=190)
        self.run_btn.clicked.connect(self.on_generate)
        layout.addLayout(action_row(self.run_btn))

        self.add_progress(layout)
        layout.addStretch(1)

    # ------------------------------------------------------------------
    def _build_namespace(self) -> argparse.Namespace:
        return argparse.Namespace(
            path=self.music_field.text() or None,
            format=self.format_combo.currentText(),
            savedir=self.save_field.text() or None,
            from_list=self.list_field.text() or None,
            mass=self.mass_field.text() or None,
            searchdir=self.search_field.text() or None,
            absolute=self.absolute_check.isChecked(),
            relative_base=self.rel_edit.text().strip() or None,
            use_folder_name=self.name_check.isChecked(),
        )

    def on_generate(self) -> None:
        args = self._build_namespace()

        if not (args.path or args.savedir or args.from_list or args.mass):
            QMessageBox.warning(
                self, "Нужны данные",
                "Укажите путь к музыке (или папку сохранения, или TXT-файл)."
            )
            return

        if (args.from_list or args.mass) and not args.searchdir:
            QMessageBox.warning(
                self, "Нужна папка поиска",
                "Для создания из TXT-списка укажите папку для поиска треков "
                "(иначе поиск идёт по текущей рабочей папке)."
            )
            return

        print("\n=== Создание плейлистов ===")

        self.start_task(
            lambda progress: plscreate.main(args, progress=progress),
            controls=[
                self.run_btn, self.music_field, self.save_field, self.format_combo,
                self.list_field, self.mass_field, self.search_field,
                self.absolute_check, self.rel_edit, self.name_check,
            ],
            on_success=self._on_finished,
            busy_text="Индексация файлов",
        )

    def _on_finished(self, result) -> None:
        if isinstance(result, dict):
            created = result.get("created", 0)
            lists = result.get("lists", 0)
            QMessageBox.information(
                self, "Готово",
                f"Обработано списков: {lists}.\nСоздано плейлистов: {created}.\n\n"
                "Подробности — в системной консоли."
            )
            return

        QMessageBox.information(
            self, "Готово", "Генерация плейлистов завершена."
        )
