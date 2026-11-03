"""Вкладка 5: Конвертер CUE в треки FLAC или MP3 (cue2mp3.py)."""

from __future__ import annotations

import argparse

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QMessageBox, QVBoxLayout,
)

from ..engines import cue2mp3
from ..widgets import ActionButton, PathField, action_row
from .base import BaseTab


class CueTab(BaseTab):
    TITLE = "Конвертер CUE в треки"

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

        # Формат треков. FLAC идёт первым и выбран по умолчанию:
        # альбом режется без потери качества, MP3 из FLAC делается
        # в любой момент, а обратно — уже нет.
        self.format_combo = QComboBox()
        self.format_combo.addItems(list(cue2mp3.FORMAT_LABELS))
        self.format_combo.setCurrentText(cue2mp3.DEFAULT_FORMAT_LABEL)
        self.format_combo.setToolTip(
            "FLAC — сжатие без потерь, качество исходника сохраняется.\n"
            "MP3 — с потерями, зато файлы меньше. Качество MP3 "
            "выбирается в следующем поле."
        )
        self.format_combo.currentTextChanged.connect(self._on_format_changed)
        form.addRow("Формат треков:", self.format_combo)

        self.quality_combo = QComboBox()
        self.quality_combo.addItems(list(cue2mp3.QUALITY_PRESETS))
        self.quality_combo.setCurrentText(cue2mp3.DEFAULT_QUALITY)
        self.quality_combo.setToolTip(
            "VBR — переменный битрейт, LAME сам выбирает значение под "
            "сложность музыки. CBR — постоянный битрейт.\n"
            "V0 и CBR 320 — максимальное качество, V6 и CBR 128 — экономные."
        )
        form.addRow("Качество MP3:", self.quality_combo)
        # Качество относится только к MP3: для FLAC поле неактивно.
        self._quality_row_hint = True

        # Обложка — файл на диске, а не ссылка: конвертация не должна
        # зависеть от доступности сайта, а картинка должна быть под рукой.
        self.cover_field = PathField(
            "file",
            "Файл обложки, например cover.jpg — можно оставить пустым",
            file_filter=("Изображения (*.jpg *.jpeg *.png *.gif *.webp *.bmp);;"
                         "Все файлы (*.*)"),
            file_title="Выберите файл обложки",
        )
        self.cover_field.setToolTip(
            "Файл картинки на диске (JPEG, PNG, GIF, WEBP, BMP). Будет "
            "встроен в теги каждого трека.\n"
            "Если поле пустое, обложка берётся из тегов исходного файла "
            "или из cover.jpg / folder.jpg рядом с альбомом."
        )
        form.addRow("Обложка (файл):", self.cover_field)

        self.debug_check = QCheckBox("Режим отладки")
        form.addRow("Отладка:", self.debug_check)

        layout.addLayout(form)

        layout.addWidget(self.make_hint(
            "Нарезает FLAC/APE по меткам INDEX 01 из CUE и кодирует через FFmpeg "
            "в FLAC (без потерь, по умолчанию) или MP3 (VBR/CBR). Для FLAC "
            "пишутся Vorbis-комментарии, для MP3 — ID3v2.4 (UTF-8); "
            "встраивает обложку из выбранного файла, иначе из тегов исходника "
            "или из cover.jpg/folder.jpg рядом с альбомом. "
            "Если FFmpeg отсутствует в системе, портативная сборка автоматически "
            "скачивается в папку ffmpeg_bin — ход загрузки и распаковки виден "
            "на полосе прогресса ниже."
        ))

        self.run_btn = ActionButton("Старт конвертации", self, minimum_width=190)
        self.run_btn.clicked.connect(self.on_convert)
        layout.addLayout(action_row(self.run_btn))

        self.add_progress(layout)
        layout.addStretch(1)

        # Приводим поля в согласованный вид сразу: по умолчанию FLAC,
        # значит качество MP3 неактивно.
        self._on_format_changed(self.format_combo.currentText())

    # ------------------------------------------------------------------
    def _on_format_changed(self, label: str) -> None:
        """Качество MP3 имеет смысл только для MP3."""
        fmt = cue2mp3.resolve_format(label)
        is_mp3 = fmt == cue2mp3.FORMAT_MP3

        self.quality_combo.setEnabled(is_mp3)
        self.quality_combo.setToolTip(
            "VBR — переменный битрейт, LAME сам выбирает значение под "
            "сложность музыки. CBR — постоянный битрейт.\n"
            "V0 и CBR 320 — максимальное качество, V6 и CBR 128 — экономные."
            if is_mp3
            else "Для FLAC не используется: сжатие без потерь, "
                 "качество всегда равно исходнику."
        )

        # Подсказка о выходном расширении — чтобы не искать глазами,
        # куда попадёт результат.
        default_out = self.output_field.text().strip()
        if default_out in ("mp3_output", "flac_output"):
            self.output_field.setText("mp3_output" if is_mp3 else "flac_output")

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
            format=self.format_combo.currentText(),
            cover=self.cover_field.text(),
            debug=self.debug_check.isChecked(),
        )

        print("\n=== Конвертация CUE -> MP3 ===")

        self.start_task(
            lambda progress: cue2mp3.main(args, progress=progress),
            controls=[
                self.run_btn, self.input_field, self.output_field,
                self.format_combo, self.quality_combo, self.cover_field,
                self.debug_check,
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
