"""Вкладка 2: Создание плейлистов из папок (folderplaylists.py).

Сценарий: папка с дискографиями, внутри — папки артистов, внутри них —
альбомы. Нужен плейлист на каждого артиста, а не на каждый альбом.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QHeaderView,
    QLabel, QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout,
)

from ..engines import folderplaylists
from ..widgets import ActionButton, PathField, action_row
from .base import BaseTab

COL_NAME = 0        # Плейлист
COL_TRACKS = 1      # Треков
COL_STATUS = 2      # Статус
COL_FOLDER = 3      # Папка


class CreatePlaylistsTab(BaseTab):
    TITLE = "Создание плейлиста"

    # Плейлист готов. Сигнал нужен потому что движок работает
    # в фоновом потоке: трогать виджеты оттуда нельзя, а queued-соединение
    # переносит вызов в главный поток Qt.
    playlist_ready = Signal(object, int, int)

    def __init__(self, main_window, parent=None):
        super().__init__(main_window, parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        form = self.make_form()

        self.folder_field = PathField(
            "dir", "Например: D:\\Music\\Дискографии"
        )
        form.addRow("Папка для сканирования:", self.folder_field)

        # Галочка определяет, будет ли один плейлист на подпапку
        # или один общий на всю выбранную папку.
        self.main_folder_check = QCheckBox(
            "Использовать папку как основную (создать плейлисты из подпапок)"
        )
        self.main_folder_check.setChecked(True)
        self.main_folder_check.setToolTip(
            "Включено: плейлисты создаются по папкам первого уровня.\n"
            "Например, выбрана «Дискографии» с папками «Арист1», «Арист2» — "
            "получатся плейлисты «Арист1» и «Арист2», и в каждый войдут все "
            "треки из его подпапок.\n\n"
            "Выключено: один плейлист из всех треков папки, имя — по имени "
            "папки."
        )
        form.addRow("Режим:", self.main_folder_check)

        self.save_field = PathField(
            "dir", "Пусто — сохранять рядом со сканируемой папкой"
        )
        self.save_field.setToolTip(
            "Куда записать готовые плейлисты. Если оставить пустым, "
            "файлы появятся в самой сканируемой папке."
        )
        form.addRow("Папка для сохранения:", self.save_field)

        self.prefix_edit = PathField("none", "/music")
        self.prefix_edit.setText("/music")
        self.prefix_edit.setToolTip(
            "С какого пути записывать треки в плейлисте.\n\n"
            "Префикс подставляется целиком, вместе со всеми папками:\n"
            "  /music/Дискографии + Арист1/01.mp3 →\n"
            "  /music/Дискографии/Арист1/01.mp3\n\n"
            "Если в префиксе указать папку, которая уже есть в начале "
            "пути, повтор не появится: /music/Дискографии при папке "
            "«Дискографии» даст /music/Дискографии/Арист1/…, а не "
            "/music/Дискографии/Дискографии/…\n\n"
            "Очистите поле, чтобы писать пути относительно сканируемой папки."
        )
        form.addRow("Префикс пути:", self.prefix_edit)

        self.absolute_check = QCheckBox("Записывать полные пути к файлам")
        self.absolute_check.setToolTip(
            "В плейлист попадёт путь целиком, как он есть на диске. "
            "Префикс пути при этом не используется."
        )
        form.addRow("Пути:", self.absolute_check)

        self.format_combo = QComboBox()
        self.format_combo.addItems(list(folderplaylists.FORMATS))
        self.format_combo.setCurrentText("m3u")
        self.format_combo.setToolTip(
            "m3u / m3u8 — обычный список путей (m3u8 — UTF-8).\n"
            "pls — INI-подобный формат Winamp.\n"
            "xspf — XML, его понимают большинство плееров.\n"
            "wpl — XML для Windows Media Player."
        )
        form.addRow("Формат плейлиста:", self.format_combo)

        self.sort_combo = QComboBox()
        self.sort_combo.addItems(list(folderplaylists.SORT_LABELS))
        self.sort_combo.setCurrentText(folderplaylists.DEFAULT_SORT_LABEL)
        self.sort_combo.setToolTip(
            "По алфавиту пути: альбомы идут в порядке папок, треки внутри — "
            "в порядке имён. Треки, лежащие прямо в папке, оказываются "
            "в начале.\n\n"
            "По названию трека: сортировка по тегу title. Если тега нет, "
            "берётся имя файла."
        )
        form.addRow("Порядок треков:", self.sort_combo)

        layout.addLayout(form)

        layout.addWidget(self.make_hint(
            "Плейлисты собираются из папок. С включённой галочкой «основная "
            "папка» каждая подпапка первого уровня даёт отдельный плейлист "
            "со всеми треками внутри неё, включая вложенные альбомы. "
            "Музыкальные файлы: mp3, flac, ape, wav, ogg, opus, m4a, aac, "
            "wma, wv, tta, dsf, aiff, alac."
        ))

        self.run_btn = ActionButton("Создать плейлисты", self,
                                    minimum_width=190)
        self.run_btn.clicked.connect(self.on_create)

        self.clear_btn = QPushButton("Очистить список", self)
        self.clear_btn.setMinimumHeight(32)
        self.clear_btn.setEnabled(False)
        self.clear_btn.clicked.connect(self._clear_table)

        layout.addLayout(action_row(self.run_btn, self.clear_btn))

        self.result_tree = QTreeWidget(self)
        self.result_tree.setHeaderLabels(
            ["Плейлист", "Треков", "Статус", "Папка"]
        )
        self.result_tree.setRootIsDecorated(False)
        self.result_tree.setAlternatingRowColors(True)
        self.result_tree.setUniformRowHeights(True)
        self.result_tree.setSelectionMode(QAbstractItemView.SingleSelection)

        # Ширины заданы явно, а не ResizeToContents: при авторазмере колонки
        # прижимаются к тексту и слипаются — заголовки «Плейлист», «Треков»,
        # «Статус» шли вплотную. QSS задаёт padding 5 px для секции заголовка
        # и 2 px для ячейки, этого хватает только если заложить запас в ширину.
        header = self.result_tree.header()
        header.setMinimumSectionSize(80)
        header.setSectionResizeMode(COL_NAME, QHeaderView.Interactive)
        header.setSectionResizeMode(COL_TRACKS, QHeaderView.Fixed)
        header.setSectionResizeMode(COL_STATUS, QHeaderView.Interactive)
        header.setSectionResizeMode(COL_FOLDER, QHeaderView.Stretch)
        self.result_tree.setColumnWidth(COL_NAME, 240)
        self.result_tree.setColumnWidth(COL_TRACKS, 90)
        self.result_tree.setColumnWidth(COL_STATUS, 150)
        header.setSectionsMovable(True)
        self.result_tree.itemDoubleClicked.connect(self._on_double_click)
        self.playlist_ready.connect(self._append_playlist)
        layout.addWidget(self.result_tree, 1)

        self.status_label = QLabel("Плейлисты ещё не создавались.")
        self.status_label.setProperty("role", "status")
        layout.addWidget(self.status_label)

        self.add_progress(layout)

    # ------------------------------------------------------------------
    # Вспомогательное
    # ------------------------------------------------------------------
    def _controls(self):
        return [
            self.run_btn, self.folder_field, self.save_field,
            self.prefix_edit, self.main_folder_check, self.absolute_check,
            self.format_combo, self.sort_combo,
        ]

    def _clear_table(self) -> None:
        self.result_tree.clear()
        self.clear_btn.setEnabled(False)
        self.status_label.setText("Плейлисты ещё не создавались.")

    def _on_double_click(self, item, _column) -> None:
        """Двойной клик открывает папку с плейлистом."""
        folder = item.data(COL_NAME, Qt.UserRole)
        if not folder or not os.path.isdir(folder):
            return
        from ..subproc import popen

        try:
            if os.name == "nt":
                os.startfile(folder)  # noqa: S606 — штатное открытие папки
            else:
                popen(["xdg-open", folder])
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    def on_create(self) -> None:
        folder = self.folder_field.text()
        if not folder:
            QMessageBox.warning(
                self, "Не указана папка",
                "Выберите папку, в которой лежит музыка."
            )
            return

        if not os.path.isdir(folder):
            QMessageBox.warning(
                self, "Папка не найдена",
                f"Такой папки нет:\n{folder}"
            )
            return

        save_dir = self.save_field.text()
        if save_dir and not os.path.isdir(save_dir):
            try:
                os.makedirs(save_dir, exist_ok=True)
            except OSError as exc:
                QMessageBox.warning(
                    self, "Не удалось создать папку",
                    f"{save_dir}\n\n{exc}"
                )
                return

        options = dict(
            use_main_folder=self.main_folder_check.isChecked(),
            prefix=self.prefix_edit.text(),
            absolute=self.absolute_check.isChecked(),
            playlist_format=self.format_combo.currentText(),
            sort_by=self.sort_combo.currentText(),
            save_dir=save_dir,
        )

        print("\n=== Создание плейлистов ===")

        self.result_tree.clear()
        self.clear_btn.setEnabled(False)
        self.status_label.setText("Идёт создание плейлистов...")

        self.start_task(
            lambda progress: folderplaylists.build_playlists(
                folder, progress=progress,
                on_playlist=lambda entry, index, total:
                    self.playlist_ready.emit(entry, index, total),
                **options
            ),
            controls=self._controls(),
            on_success=self._on_finished,
            busy_text="Поиск треков и запись плейлистов",
        )

    # ------------------------------------------------------------------
    def _append_playlist(self, entry, index: int, total: int) -> None:
        """Добавляет строку сразу после записи очередного плейлиста.

        Вызывается из главного потока через сигнал: движок работает
        в фоновом потоке, а виджеты можно трогать только здесь.
        """
        item = QTreeWidgetItem([
            entry["name"],
            str(entry["tracks"]),
            entry["status"],
            entry["folder"],
        ])
        item.setData(COL_NAME, Qt.UserRole, entry["folder"])
        item.setToolTip(COL_NAME, entry["path"] or entry["folder"])
        item.setToolTip(COL_FOLDER, entry["folder"])
        item.setTextAlignment(COL_TRACKS, Qt.AlignRight | Qt.AlignVCenter)
        self.result_tree.addTopLevelItem(item)

        # Показываем, что происходит прямо сейчас, а не только итог.
        self.status_label.setText(
            f"Создано {index} из {total}: {entry['name']}"
        )
        self.result_tree.scrollToItem(item)
        self.clear_btn.setEnabled(True)

    def _on_finished(self, results) -> None:
        """Подводит итог. Строки уже добавлены по ходу через _append_playlist."""
        if not results:
            self.status_label.setText("Плейлисты не созданы: треков не найдено.")
            self.clear_btn.setEnabled(False)
            return

        created = updated = unchanged = empty = 0
        total_tracks = 0

        for entry in results:
            total_tracks += entry["tracks"]
            status = entry["status"]
            if status == folderplaylists.STATUS_CREATED:
                created += 1
            elif status == folderplaylists.STATUS_UPDATED:
                updated += 1
            elif status == folderplaylists.STATUS_UNCHANGED:
                unchanged += 1
            else:
                empty += 1

        parts = [f"Плейлистов: {len(results)}"]
        if created:
            parts.append(f"создано {created}")
        if updated:
            parts.append(f"обновлено {updated}")
        if unchanged:
            parts.append(f"без изменений {unchanged}")
        if empty:
            parts.append(f"без треков {empty}")
        parts.append(f"всего треков: {total_tracks}")

        self.status_label.setText(". ".join(parts) + ".")
        self.clear_btn.setEnabled(True)

        self.main_window.show_console()
