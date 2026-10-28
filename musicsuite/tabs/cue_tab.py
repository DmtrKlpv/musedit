"""Вкладка 5: Конвертер CUE в MP3 (cue2mp3.py)."""

from __future__ import annotations

import argparse

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QMessageBox, QVBoxLayout,
)

from ..engines import cue2mp3
from ..widgets import ActionButton, PathField, action_row
from .base import BaseTab


class CueTab(BaseTab):
    TITLE = "Конвертер CUE в MP3"

    def __init__(self, main_window, parent=None):
        super().__init__(main_window, parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        form = self.make_form()

        self.input_field = PathField("both", "Путь к .cue файлу или папке с альбомом")
        form.addRow("Источник (CUE или папка):", self.input_field)

        self.output_field = PathField("dir", "Папка вывода MP3")
        self.output_field.setText("mp3_output")
        form.addRow("Папка вывода:", self.output_field)

        self.quality_combo = QComboBox()
        self.quality_combo.addItems(["v0", "320"])
        form.addRow("Качество MP3:", self.quality_combo)

        self.debug_check = QCheckBox("Режим отладки")
        form.addRow("Отладка:", self.debug_check)

        layout.addLayout(form)

        layout.addWidget(self.make_hint(
            "Нарезает FLAC/APE по меткам INDEX 01 из CUE, кодирует через FFmpeg "
            "(v0 — LAME VBR, 320 — CBR 320 kbps), прописывает ID3v2.4 (UTF-8) "
            "и встраивает обложку из тегов или из файла cover.jpg/folder.jpg. "
            "Если FFmpeg отсутствует в системе, портативная сборка автоматически "
            "скачивается в папку ffmpeg_bin — ход загрузки и распаковки виден "
            "на полосе прогресса ниже."
        ))

        self.run_btn = ActionButton("Старт конвертации", self, minimum_width=190)
        self.run_btn.clicked.connect(self.on_convert)
        layout.addLayout(action_row(self.run_btn))

        self.add_progress(layout)
        layout.addStretch(1)

    # ------------------------------------------------------------------
    def on_convert(self) -> None:
        source = self.input_field.text()
        if not source:
            QMessageBox.warning(self, "Не указан источник",
                                "Выберите .cue файл или папку с альбомом.")
            return

        output = self.output_field.text() or "mp3_output"

        args = argparse.Namespace(
            input=source,
            output=output,
            quality=self.quality_combo.currentText(),
            debug=self.debug_check.isChecked(),
        )

        print("\n=== Конвертация CUE -> MP3 ===")

        self.start_task(
            lambda progress: cue2mp3.main(args, progress=progress),
            controls=[
                self.run_btn, self.input_field, self.output_field,
                self.quality_combo, self.debug_check,
            ],
            on_success=self._on_finished,
            busy_text="Подготовка конвертации",
        )

    def _on_finished(self, result) -> None:
        if isinstance(result, dict):
            tracks = result.get("tracks", 0)
            failed = result.get("failed", 0)
            out_dir = result.get("out_dir", "")
            text = f"Обработано треков: {tracks}.\nПапка: {out_dir}"
            if failed:
                text += f"\n\nС ошибками: {failed}."
            QMessageBox.information(self, "Готово", text)
            return

        QMessageBox.information(
            self, "Готово", "Конвертация завершена."
        )
