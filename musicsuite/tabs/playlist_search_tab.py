"""Вкладка «Поиск по плейлисту»: замена путей в плейлисте на актуальные.

Сценарий: плейлист ссылается на файлы по старым путям (переехала папка,
сменилась буква диска, музыка разложена иначе). Указываем плейлист и
папку для поиска — утилита находит каждый трек и предлагает новый путь.

Состав плейлиста не меняется: правятся только строки с путями, и каждую
замену можно подтвердить отдельно или применить все сразу.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout,
)

from ..engines import playlist_search as engine
from ..engines import plscreate
from ..widgets import ActionButton, PathField, action_row
from .base import BaseTab

COL_TRACK = 0        # Трек
COL_OLD = 1          # Старый путь
COL_COUNT = 2        # Путей
COL_LINE = 3         # Запись в файле (выпадающий список)
COL_PICK = 4         # Указать явно (кнопка)
COL_ACTION = 5       # Изменить путь (кнопка)
COL_NEW = 6          # Новый путь

# Колонки с данными: перекрашиваются при подсветке, кнопки не трогаем.
COL_DATA = (COL_TRACK, COL_OLD, COL_COUNT, COL_LINE, COL_NEW)

COLOR_OK = "#15803d"
COLOR_MISSING = "#b91c1c"

BG_MISSING = QColor("#fde2e4")
FG_MISSING = QColor("#9f1239")
BG_DONE = QColor("#e3f6e5")
FG_DONE = QColor("#166534")


class PlaylistSearchTab(BaseTab):
    TITLE = "Поиск по плейлисту"

    scan_finished = Signal(object)

    def __init__(self, main_window, parent=None):
        super().__init__(main_window, parent)

        self._result = engine.SearchResult()
        self._rows = {}          # id(TrackRow) -> QTreeWidgetItem
        self._items = []         # порядок TrackRow, как в таблице

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        form = self.make_form()

        self.playlist_field = PathField(
            "file", "Файл плейлиста: m3u, m3u8, pls, xspf или wpl"
        )
        form.addRow("Плейлист:", self.playlist_field)

        self.folder_field = PathField(
            "dir", "Папка, в которой искать треки (включая подпапки)"
        )
        form.addRow("Папка для поиска:", self.folder_field)

        self.absolute_check = QCheckBox("Записывать полные пути")
        form.addRow("Пути:", self.absolute_check)

        self.rel_edit = QLineEdit()
        self.rel_edit.setPlaceholderText("например: /music")
        form.addRow("Префикс пути:", self.rel_edit)

        self.tags_check = QCheckBox("Так же искать в mp3-тегах")
        self.tags_check.setToolTip(
            "Дополнительно сопоставлять треки по ID3-тегам (исполнитель и "
            "название). Помогает, когда имя файла не совпадает с записью "
            "в плейлисте. Замедляет сканирование: теги читаются с диска."
        )
        form.addRow("Теги:", self.tags_check)

        # Кнопка запуска стоит сразу под полем префикса: сначала задаются
        # все параметры, потом запускается поиск. Автоматического старта нет —
        # иначе поиск срабатывал бы на каждое нажатие клавиши в поле префикса.
        self.scan_btn = ActionButton("Начать сканирование", self,
                                     minimum_width=190)
        self.scan_btn.clicked.connect(self.on_scan)

        layout.addLayout(form)

        # Кнопка в отдельной строке основного layout, а не ячейкой формы:
        # внутри QFormLayout addStretch не растягивает ячейку, и кнопка
        # оставалась у левого края.
        scan_row = QHBoxLayout()
        scan_row.setContentsMargins(0, 4, 0, 0)
        scan_row.setSpacing(6)
        scan_row.addStretch(1)          # прижимает кнопку вправо
        scan_row.addWidget(self.scan_btn)
        layout.addLayout(scan_row)

        layout.addWidget(self.make_hint(
            "Утилита ищет каждый трек из плейлиста в указанной папке и всех "
            "подпапках — по имени файла. Состав плейлиста не меняется, "
            "заменяются только строки с путями.\n"
            "• Кнопка в строке меняет путь одного трека.\n"
            "• «Поменять все пути» записывает сразу все найденные.\n"
            "• Треки, которых нет в папке, остаются как были и подсвечены розовым.\n"
            "Формат путей задаётся полями выше и применяется при поиске, "
            "поэтому после смены папки, префикса или галочки нажмите "
            "«Начать сканирование» ещё раз."
        ))

        layout.addWidget(self._bold("Строки плейлиста:"))

        self.table = QTreeWidget(self)
        self.table.setHeaderLabels([
            "Трек", "Старый путь", "Путей", "Запись в файле",
            "Указать явно", "Изменить путь", "Новый путь",
        ])
        self.table.setRootIsDecorated(False)
        self.table.setAlternatingRowColors(True)
        self.table.setUniformRowHeights(True)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)

        header = self.table.header()
        header.setSectionResizeMode(COL_TRACK, QHeaderView.Interactive)
        header.setSectionResizeMode(COL_OLD, QHeaderView.Interactive)
        header.setSectionResizeMode(COL_COUNT, QHeaderView.Fixed)
        header.setSectionResizeMode(COL_LINE, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_PICK, QHeaderView.Fixed)
        header.setSectionResizeMode(COL_ACTION, QHeaderView.Fixed)
        header.setSectionResizeMode(COL_NEW, QHeaderView.Stretch)
        self.table.setColumnWidth(COL_TRACK, 190)
        self.table.setColumnWidth(COL_OLD, 220)
        self.table.setColumnWidth(COL_COUNT, 62)
        self.table.setColumnWidth(COL_PICK, 118)
        self.table.setColumnWidth(COL_ACTION, 126)
        self.table.setMinimumHeight(180)
        layout.addWidget(self.table, 1)

        self.status_label = QLabel(
            "Укажите плейлист, папку для поиска и нажмите «Начать сканирование»."
        )
        self.status_label.setStyleSheet("color:#4b5563;")
        layout.addWidget(self.status_label)

        buttons_row = QHBoxLayout()
        buttons_row.setContentsMargins(0, 0, 0, 0)
        buttons_row.setSpacing(6)

        self.change_all_btn = ActionButton("Поменять все пути", self,
                                           minimum_width=190)
        self.change_all_btn.setEnabled(False)
        self.change_all_btn.clicked.connect(self.on_change_all)

        buttons_row.addStretch(1)
        buttons_row.addWidget(self.change_all_btn)
        layout.addLayout(buttons_row)

        self.add_progress(layout)

        # Сканирование запускается только кнопкой. При смене параметров
        # результаты прошлого поиска устаревают: помечаем их как неактуальные,
        # чтобы «Поменять все пути» не записала пути из старого расчёта.
        self.playlist_field.edit.textChanged.connect(self._mark_stale)
        self.folder_field.edit.textChanged.connect(self._mark_stale)
        self.rel_edit.textChanged.connect(self._mark_stale)
        self.absolute_check.toggled.connect(self._mark_stale)
        self.tags_check.toggled.connect(self._mark_stale)
        self.scan_finished.connect(self._on_scan_ready)

    # ------------------------------------------------------------------
    @staticmethod
    def _bold(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("font-weight:600;")
        return label

    def _mark_stale(self) -> None:
        """Помечает результаты прошлого поиска как устаревшие.

        Параметры изменились — пути в таблице пересчитаны под старое
        состояние, и записывать их в файл нельзя.
        """
        if not self._items:
            return
        self.change_all_btn.setEnabled(False)
        self.status_label.setText(
            "Параметры изменились — нажмите «Начать сканирование», "
            "чтобы пересчитать пути."
        )

    def on_scan(self) -> None:
        """Запускает поиск по кнопке."""
        playlist = self.playlist_field.text()
        folder = self.folder_field.text()

        if not playlist:
            QMessageBox.warning(
                self, "Не указан плейлист",
                "Выберите файл плейлиста, в котором нужно заменить пути."
            )
            return
        if not os.path.isfile(playlist):
            QMessageBox.warning(
                self, "Файл не найден",
                f"Плейлист не существует:\n{playlist}"
            )
            return
        if not folder:
            QMessageBox.warning(
                self, "Не указана папка",
                "Выберите папку, в которой искать треки."
            )
            return
        if not os.path.isdir(folder):
            QMessageBox.warning(
                self, "Папка не найдена",
                f"Папка для поиска не существует:\n{folder}"
            )
            return

        self._start_search(playlist, folder)

    def _start_search(self, playlist: str, folder: str) -> None:
        self.table.clear()
        self._rows.clear()
        self._items.clear()
        self.change_all_btn.setEnabled(False)
        self.status_label.setText("Поиск треков в папке...")

        absolute = self.absolute_check.isChecked()
        rel_base = self.rel_edit.text().strip() or None
        search_tags = self.tags_check.isChecked()

        self.start_task(
            lambda progress: engine.find_playlist_matches(
                playlist, folder, absolute=absolute, rel_base=rel_base,
                search_tags=search_tags, progress=progress,
            ),
            controls=[self.playlist_field, self.folder_field,
                      self.absolute_check, self.rel_edit, self.tags_check,
                      self.change_all_btn],
            on_success=self.scan_finished.emit,
            busy_text="Поиск по плейлисту",
        )

    # ------------------------------------------------------------------
    def _on_scan_ready(self, result) -> None:
        if result is None:
            return

        self._result = result
        if result.error:
            self.status_label.setText(result.error)
            QMessageBox.warning(self, "Не удалось выполнить поиск", result.error)
            return

        self._items = list(result.rows)
        self._fill_table()
        self.status_label.setText(
            f"{result.summary}  Кнопка «Поменять все пути» запишет "
            f"{len(result.found)} найденных."
        )
        self.change_all_btn.setEnabled(bool(result.found))

    def _fill_table(self) -> None:
        self.table.clear()
        self._rows.clear()

        for row in self._items:
            chosen = row.new_path or row.old_path
            item = QTreeWidgetItem([
                row.track_name,
                row.old_path,
                str(row.option_count),
                chosen,
                "",
                "",
                row.new_path or "—",
            ])
            item.setToolTip(COL_TRACK, row.track_name)
            item.setToolTip(COL_OLD, row.old_path)
            item.setToolTip(
                COL_COUNT,
                f"Найдено вариантов: {row.option_count}"
                + (" (в том числе по названию трека)" if row.fuzzy else "")
                if row.option_count
                else "Файл не найден в папке",
            )
            item.setToolTip(COL_LINE, chosen)
            item.setToolTip(COL_NEW, row.new_path or "файл не найден в папке")

            if not row.new_path:
                for column in COL_DATA:
                    item.setBackground(column, QBrush(BG_MISSING))
                    item.setForeground(column, QBrush(FG_MISSING))
            elif row.applied:
                self._paint_done(item)

            self.table.addTopLevelItem(item)

            # «Запись в файле» — выпадающий список найденных вариантов.
            combo = QComboBox(self.table)
            combo.setEditable(True)
            combo.setFixedHeight(24)
            combo.setMaxVisibleItems(14)

            for path in row.candidates:
                combo.addItem(path)
            if row.new_path and row.new_path not in row.candidates:
                combo.addItem(row.new_path)
            if not row.candidates:
                combo.addItem(row.old_path)

            combo.setCurrentText(chosen)
            self._style_changed(combo, row)
            combo.setToolTip(
                f"Найдено вариантов: {row.option_count}. Выберите нужный — "
                "он попадёт в плейлист."
                if row.option_count > 1
                else "Путь, который будет записан в плейлист"
            )
            combo.setEnabled(not row.applied)
            combo.currentTextChanged.connect(
                lambda text, r=row: self._on_line_changed(r, text)
            )
            self.table.setItemWidget(item, COL_LINE, combo)

            # «Указать явно» — выбор любого файла на диске.
            pick = QPushButton("Указать явно", self.table)
            pick.setFixedWidth(110)
            pick.setFixedHeight(24)
            pick.setToolTip(
                "Выбрать файл вручную. Путь будет пересчитан под текущий "
                "префикс и настройки путей."
            )
            pick.setEnabled(not row.applied)
            pick.clicked.connect(lambda _checked=False, r=row: self.on_pick_file(r))
            self.table.setItemWidget(item, COL_PICK, pick)

            # «Изменить путь» — записать текущий выбор в плейлист.
            button = QPushButton("Изменить путь", self.table)
            button.setFixedWidth(120)
            button.setFixedHeight(24)
            button.setEnabled(bool(row.new_path) and not row.applied)
            button.clicked.connect(
                lambda _checked=False, r=row: self.on_change_one(r)
            )
            self.table.setItemWidget(item, COL_ACTION, button)

            self._rows[id(row)] = item

    # ------------------------------------------------------------------
    def on_pick_file(self, row: engine.TrackRow) -> None:
        """Ручной выбор файла на диске для строки плейлиста.

        Путь пересчитывается через тот же format_path, что и при поиске,
        поэтому результат совпадает по виду с остальными строками:
        с префиксом вроде /music или абсолютный, по галочке.
        """
        if row.applied:
            return

        folder = self.folder_field.text()
        start_dir = folder if folder and os.path.isdir(folder) else ""

        chosen, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите файл для этого трека",
            start_dir,
            "Аудиофайлы (*.mp3 *.flac *.wav *.m4a *.ogg *.ape *.dsf *.dff);;"
            "Все файлы (*.*)",
        )
        if not chosen:
            return

        folder = folder or os.path.dirname(chosen)
        absolute = self.absolute_check.isChecked()
        rel_base = self.rel_edit.text().strip() or None

        try:
            write_path = plscreate.format_path(
                chosen, base_dir=folder, absolute=absolute, rel_base=rel_base
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self, "Не удалось построить путь",
                f"Файл выбран, но путь не пересчитан:\n{exc}"
            )
            return

        # Свой выбор становится первым в списке и сразу подставляется.
        if write_path not in row.candidates:
            row.candidates.insert(0, write_path)
        row.new_path = write_path
        row.found_file = chosen

        item = self._rows.get(id(row))
        if item is not None:
            item.setText(COL_NEW, write_path)
            item.setText(COL_LINE, write_path)
            item.setToolTip(COL_NEW, write_path)
            item.setToolTip(COL_LINE, write_path)

            combo = self.table.itemWidget(item, COL_LINE)
            if isinstance(combo, QComboBox):
                combo.blockSignals(True)
                if combo.findText(write_path) < 0:
                    combo.insertItem(0, write_path)
                combo.setCurrentText(write_path)
                combo.blockSignals(False)
                self._style_changed(combo, row)

            button = self.table.itemWidget(item, COL_ACTION)
            if isinstance(button, QPushButton):
                button.setEnabled(True)

            # Снимаем розовую подсветку: путь теперь есть.
            for column in COL_DATA:
                item.setBackground(column, QBrush(QColor("#ffffff")))
                item.setForeground(column, QBrush(QColor("#1f2430")))

            self.table.scrollToItem(item, QAbstractItemView.EnsureVisible)

        self._update_change_all_state()

    # ------------------------------------------------------------------
    @staticmethod
    def _style_changed(combo: QComboBox, row: engine.TrackRow) -> None:
        """Подсвечивает список, если выбран не тот путь, что предложил поиск.

        Первый вариант — результат поиска, его менять не нужно. Как только
        пользователь выбрал другой файл или вписал путь руками, он должен
        видеть, что строка отличается от автоматического результата.
        """
        chosen = (combo.currentText() or "").strip()
        suggested = (row.default_path or "").strip()
        changed = bool(chosen) and bool(suggested) and chosen != suggested

        if changed:
            combo.setStyleSheet(
                "QComboBox { background: #fff4d6; border: 1px solid #d9a441; }"
            )
            if not combo.toolTip().startswith("Выбран вручную"):
                combo.setToolTip(
                    "Выбран вручную — отличается от предложенного поиском.\n"
                    f"Поиск предлагал: {suggested}"
                )
        else:
            combo.setStyleSheet("")
            if combo.toolTip().startswith("Выбран вручную"):
                combo.setToolTip(
                    "Путь, который будет записан в плейлист"
                )

    def _on_line_changed(self, row: engine.TrackRow, text: str) -> None:
        """Пользователь выбрал или ввёл путь в выпадающем списке."""
        text = (text or "").strip()
        if not text or row.applied:
            return

        row.new_path = text

        item = self._rows.get(id(row))
        if item is not None:
            item.setText(COL_NEW, text)
            item.setToolTip(COL_NEW, text)
            item.setToolTip(COL_LINE, text)

            combo = self.table.itemWidget(item, COL_LINE)
            if isinstance(combo, QComboBox):
                self._style_changed(combo, row)

            button = self.table.itemWidget(item, COL_ACTION)
            if isinstance(button, QPushButton):
                button.setEnabled(True)

            # Выбранный вручную путь снимает розовую подсветку «не найден».
            if row.new_path:
                for column in COL_DATA:
                    item.setBackground(column, QBrush(QColor("#ffffff")))
                    item.setForeground(column, QBrush(QColor("#1f2430")))
                item.setForeground(COL_LINE, QBrush(QColor("#1f2430")))

        self._update_change_all_state()

    @staticmethod
    def _paint_done(item: QTreeWidgetItem) -> None:
        for column in COL_DATA:
            item.setBackground(column, QBrush(BG_DONE))
            item.setForeground(column, QBrush(FG_DONE))

    # ------------------------------------------------------------------
    def on_change_one(self, row: engine.TrackRow) -> None:
        """Заменяет путь одной строки плейлиста."""
        if row.applied or not row.new_path:
            return

        playlist = self.playlist_field.text()
        if not os.path.isfile(playlist):
            QMessageBox.warning(self, "Файл не найден",
                                f"Плейлист не существует:\n{playlist}")
            return

        self.start_task(
            lambda: engine.apply_single(playlist, row),
            controls=[self.change_all_btn, self.playlist_field,
                      self.folder_field, self.absolute_check, self.rel_edit],
            on_success=lambda changed: self._after_single(row, changed),
            busy_text="Запись строки",
        )

    def _after_single(self, row: engine.TrackRow, changed) -> None:
        if not changed:
            QMessageBox.warning(
                self, "Не изменено",
                "Не удалось изменить строку. Возможно, файл плейлиста "
                "изменился после поиска — запустите поиск заново."
            )
            return

        item = self._rows.get(id(row))
        if item is not None:
            item.setText(COL_LINE, row.new_path)
            self._paint_done(item)
            widget = self.table.itemWidget(item, COL_ACTION)
            if isinstance(widget, QPushButton):
                widget.setEnabled(False)

        self._update_change_all_state()

    def _update_change_all_state(self) -> None:
        pending = [r for r in self._items if r.new_path and not r.applied]
        self.change_all_btn.setEnabled(bool(pending))
        if pending:
            self.status_label.setText(
                f"Осталось заменить: {len(pending)} из {len(self._items)}."
            )
        else:
            self.status_label.setText(
                f"Все найденные пути заменены. Строк в плейлисте: {len(self._items)}."
            )

    # ------------------------------------------------------------------
    def on_change_all(self) -> None:
        playlist = self.playlist_field.text()
        if not os.path.isfile(playlist):
            QMessageBox.warning(self, "Файл не найден",
                                f"Плейлист не существует:\n{playlist}")
            return

        pending = [r for r in self._items if r.new_path and not r.applied]
        if not pending:
            QMessageBox.information(self, "Нечего менять",
                                    "Все найденные пути уже заменены.")
            return

        answer = QMessageBox.question(
            self, "Подтверждение",
            f"Заменить пути в плейлисте?\n\n"
            f"Будет изменено строк: {len(pending)}\n"
            f"Файл: {playlist}\n\n"
            "Рекомендуется сделать резервную копию плейлиста.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self.start_task(
            lambda progress: engine.apply_rows(playlist, pending,
                                               progress=progress),
            controls=[self.change_all_btn, self.playlist_field,
                      self.folder_field, self.absolute_check, self.rel_edit],
            on_success=self._after_all,
            busy_text="Запись плейлиста",
        )

    def _after_all(self, changed) -> None:
        for row in self._items:
            if not row.applied:
                continue
            item = self._rows.get(id(row))
            if item is None:
                continue
            item.setText(COL_LINE, row.new_path)
            self._paint_done(item)
            widget = self.table.itemWidget(item, COL_ACTION)
            if isinstance(widget, QPushButton):
                widget.setEnabled(False)

        self._update_change_all_state()
        QMessageBox.information(
            self, "Готово",
            f"Изменено строк в плейлисте: {changed}.\n\n"
            f"Файл: {self.playlist_field.text()}"
        )
