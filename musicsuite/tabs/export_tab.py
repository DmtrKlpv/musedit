"""Вкладка 1: Экспорт из Яндекс.Музыки (plsgen.py)."""

from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QVBoxLayout,
)

from ..engines import plsgen
from ..widgets import ActionButton, SavePathField, action_row
from .base import BaseTab


class ExportTab(BaseTab):
    TITLE = "Экспорт из Яндекс.Музыки"

    def __init__(self, main_window, parent=None):
        super().__init__(main_window, parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        layout.addWidget(self._label_bold("Код HTML / iframe плейлиста:"))
        self.iframe_edit = QPlainTextEdit(self)
        self.iframe_edit.setPlaceholderText(
            'Вставьте сюда HTML-код iframe плейлиста, например:\n'
            '<iframe frameborder="0" style="border:none;width:100%;height:180px;" '
            'src="https://music.yandex.ru/iframe/#playlist/username/1234567"></iframe>'
        )
        self.iframe_edit.setMinimumHeight(150)
        layout.addWidget(self.iframe_edit, 1)

        layout.addWidget(self._label_bold("Путь к файлу для сохранения:"))
        self.save_field = SavePathField(
            "например: D:\\Музыка\\плейлисты\\мой_плейлист.txt",
            "Текстовые файлы (*.txt);;Все файлы (*.*)",
            default_suffix=".txt",
        )
        layout.addWidget(self.save_field)

        layout.addWidget(self._label_bold("Имя файла (если путь не указан):"))
        self.filename_edit = QLineEdit(self)
        self.filename_edit.setPlaceholderText("playlist_export")
        layout.addWidget(self.filename_edit)

        layout.addWidget(self.make_hint(
            "Если путь к файлу указан, плейлист сохраняется именно туда. "
            "Если поле пустое, файл попадает в подпапку pls рядом с приложением "
            "и называется по полю «Имя файла» (по умолчанию playlist_export.txt). "
            "Расширение .txt добавляется автоматически."
        ))

        self.run_btn = ActionButton("Экспортировать", self, minimum_width=190)
        self.run_btn.clicked.connect(self.on_export)
        layout.addLayout(action_row(self.run_btn))

        self.add_progress(layout)
        layout.addStretch(1)

    # ------------------------------------------------------------------
    @staticmethod
    def _label_bold(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("font-weight:600;")
        return label

    # ------------------------------------------------------------------
    def on_export(self) -> None:
        iframe_code = self.iframe_edit.toPlainText().strip()
        filename = self.filename_edit.text().strip()
        output_path = self.save_field.text()

        if not iframe_code:
            QMessageBox.warning(self, "Нужны данные",
                                "Вставьте HTML-код (iframe) плейлиста.")
            return

        print("\n=== Экспорт плейлиста Яндекс.Музыки ===")

        self.start_task(
            lambda progress: plsgen.get_playlist_tracks(
                iframe_code, filename, output_path or None, progress=progress
            ),
            controls=[self.run_btn, self.iframe_edit, self.filename_edit,
                      self.save_field],
            on_success=self._on_done,
            busy_text="Получение плейлиста",
        )

    def _on_done(self, path) -> None:
        if not path:
            QMessageBox.warning(
                self, "Не удалось экспортировать",
                "Проверьте, что вставлен корректный код iframe плейлиста. "
                "Подробности — в системной консоли."
            )
            return

        target_dir = os.path.dirname(path)
        QMessageBox.information(
            self, "Готово",
            f"Плейлист успешно экспортирован:\n{path}\n\nПапка: {target_dir}"
        )
