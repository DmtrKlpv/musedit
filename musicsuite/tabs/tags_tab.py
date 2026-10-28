"""Вкладка 4: Исправление тегов MP3 (fixtags.py) с таблицей правок и кнопками.

Сканирование и запись выполняются в фоновом потоке; каждая правка применяется
независимо, чтобы одна ошибка не срывала весь пакет.
"""

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QSizePolicy,
    QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from ..engines import fixtags
from ..widgets import ActionButton, PathField
from .base import BaseTab

COL_CHECK = 0
COL_FILE = 1
COL_FIELD = 2
COL_OLD = 3
COL_NEW = 4
COL_STATUS = 5
COL_ACTION = 6

COLOR_DONE = QColor("#15803d")
COLOR_OLD = QColor("#b91c1c")


class TagsTab(BaseTab):
    TITLE = "Исправление тегов MP3"

    def __init__(self, main_window, parent=None):
        super().__init__(main_window, parent)

        self._items = []
        self._row_items = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        form = self.make_form()

        self.music_field = PathField("dir", "Папка с музыкой")
        form.addRow("Музыкальная папка:", self.music_field)

        self.ext_edit = QLineEdit(".mp3")
        self.ext_edit.setPlaceholderText(".mp3")
        self.ext_edit.setMaximumWidth(160)
        form.addRow("Расширение файлов:", self.ext_edit)

        self.dry_run_check = QCheckBox(
            "Режим тестирования (только показать, не сохранять)"
        )
        form.addRow("Изменения:", self.dry_run_check)

        layout.addLayout(form)

        layout.addWidget(self.make_hint(
            "Восстанавливает повреждённые кодировки в ID3-тегах: UTF-8, ошибочно "
            "прочитанный как CP1251/KOI8-R/CP866, а также CP1251, прочитанный как Latin-1. "
            "Корректные названия не изменяются — «Vallée» и «Düsseldorf» остаются как есть. "
            "Теги сохраняются в UTF-8 (ID3v2.4) без создания v1-тегов."
        ))

        # ---- кнопки управления сканированием ----
        scan_row = QHBoxLayout()

        self.scan_btn = QPushButton("Сканировать", self)
        self.scan_btn.setMinimumHeight(34)
        self.scan_btn.setMinimumWidth(170)
        self.scan_btn.clicked.connect(self.on_scan)
        scan_row.addWidget(self.scan_btn)

        self.fix_all_btn = ActionButton("Исправить все", self, minimum_width=170)
        self.fix_all_btn.setEnabled(False)
        self.fix_all_btn.clicked.connect(self.on_fix_all)
        scan_row.addWidget(self.fix_all_btn)

        self.select_all_btn = QPushButton("Выбрать все", self)
        self.select_all_btn.setEnabled(False)
        self.select_all_btn.clicked.connect(lambda: self._set_all_checked(True))
        scan_row.addWidget(self.select_all_btn)

        self.select_none_btn = QPushButton("Снять выбор", self)
        self.select_none_btn.setEnabled(False)
        self.select_none_btn.clicked.connect(lambda: self._set_all_checked(False))
        scan_row.addWidget(self.select_none_btn)

        scan_row.addStretch(1)

        self.export_btn = QPushButton("Сохранить отчёт...", self)
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self.on_export)
        scan_row.addWidget(self.export_btn)

        layout.addLayout(scan_row)

        # ---- таблица правок ----
        self.table = QTreeWidget(self)
        self.table.setHeaderLabels(
            ["", "Файл", "Поле", "Было", "Станет", "Статус", ""]
        )
        self.table.setRootIsDecorated(False)
        self.table.setAlternatingRowColors(True)
        self.table.setUniformRowHeights(True)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setWordWrap(False)

        header = self.table.header()
        header.setSectionResizeMode(COL_CHECK, QHeaderView.Fixed)
        header.setSectionResizeMode(COL_FILE, QHeaderView.Interactive)
        header.setSectionResizeMode(COL_FIELD, QHeaderView.Interactive)
        header.setSectionResizeMode(COL_OLD, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_NEW, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_STATUS, QHeaderView.Interactive)
        header.setSectionResizeMode(COL_ACTION, QHeaderView.Fixed)
        self.table.setColumnWidth(COL_CHECK, 28)
        self.table.setColumnWidth(COL_FILE, 190)
        self.table.setColumnWidth(COL_FIELD, 130)
        self.table.setColumnWidth(COL_STATUS, 110)
        self.table.setColumnWidth(COL_ACTION, 92)

        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self.table, 1)

        self.status_label = QLabel("Нажмите «Сканировать», чтобы найти правки.")
        self.status_label.setStyleSheet("color:#6b7280;")
        layout.addWidget(self.status_label)

        self.add_progress(layout)

    # ------------------------------------------------------------------
    @staticmethod
    def _bold(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("font-weight:600;")
        return label

    # ------------------------------------------------------------------
    # Сканирование
    # ------------------------------------------------------------------
    def on_scan(self) -> None:
        directory = self.music_field.text()
        if not directory:
            QMessageBox.warning(
                self, "Не указана папка", "Выберите музыкальную папку."
            )
            return
        if not os.path.isdir(directory):
            QMessageBox.warning(
                self, "Папка не найдена", f"Папка не существует:\n{directory}"
            )
            return

        ext = self.ext_edit.text().strip() or ".mp3"
        if not ext.startswith("."):
            ext = "." + ext
            self.ext_edit.setText(ext)

        self._clear_table()
        print("\n=== Исправление тегов MP3: сканирование ===")
        self.status_label.setText("Идёт сканирование...")

        self.start_task(
            lambda progress: fixtags.scan_directory(directory, ext, progress=progress),
            controls=[self.scan_btn, self.music_field, self.ext_edit,
                      self.dry_run_check, self.fix_all_btn,
                      self.select_all_btn, self.select_none_btn],
            on_success=self._on_scan_done,
            busy_text="Сканирование тегов",
            busy_progress=True,
        )

    def _on_scan_done(self, items) -> None:
        self._items = list(items or [])
        self._fill_table()
        if not self._items:
            self.status_label.setText(
                "Правок не найдено — все теги в корректной кодировке."
            )
            return
        files = len({item.filepath for item in self._items})
        self.status_label.setText(
            f"Найдено правок: {len(self._items)} в файлах: {files}. "
            "Снимите галочки с ненужных и нажмите «Исправить все»."
        )

    # ------------------------------------------------------------------
    # Таблица
    # ------------------------------------------------------------------
    def _clear_table(self) -> None:
        self.table.blockSignals(True)
        self.table.clear()
        self.table.blockSignals(False)
        self._items = []
        self._row_items = {}
        self.fix_all_btn.setEnabled(False)
        self.select_all_btn.setEnabled(False)
        self.select_none_btn.setEnabled(False)
        self.export_btn.setEnabled(False)

    def _fill_table(self) -> None:
        self.table.blockSignals(True)
        self.table.clear()
        self._row_items = {}

        for item in self._items:
            row = QTreeWidgetItem()
            row.setText(COL_FILE, item.filename)
            row.setToolTip(COL_FILE, item.filepath)
            row.setText(COL_FIELD, item.display_field)
            row.setText(COL_OLD, item.old_text)
            row.setText(COL_NEW, item.new_text)
            row.setText(COL_STATUS, "Готово" if item.applied else "Не исправлено")
            row.setFlags(row.flags() | Qt.ItemIsUserCheckable)
            row.setCheckState(
                COL_CHECK, Qt.Checked if not item.applied else Qt.Unchecked
            )
            if item.applied:
                for column in (COL_FILE, COL_FIELD, COL_OLD, COL_NEW, COL_STATUS):
                    row.setForeground(column, QBrush(COLOR_DONE))
            else:
                row.setForeground(COL_OLD, QBrush(COLOR_OLD))
            row.setToolTip(COL_OLD, item.old_text)
            row.setToolTip(COL_NEW, item.new_text)

            self.table.addTopLevelItem(row)

            button = QPushButton("Исправить", self.table)
            # Фиксированная короткая длина: раньше кнопка растягивалась по
            # ширине колонки и занимала половину строки.
            button.setFixedWidth(96)
            button.setFixedHeight(24)
            button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            button.setEnabled(not item.applied)
            button.clicked.connect(lambda _=False, it=item: self.on_fix_one(it))
            self.table.setItemWidget(row, COL_ACTION, button)

            self._row_items[id(item)] = row

        self.table.blockSignals(False)
        pending = any(not item.applied for item in self._items)
        self.fix_all_btn.setEnabled(pending)
        self.select_all_btn.setEnabled(pending)
        self.select_none_btn.setEnabled(pending)
        self.export_btn.setEnabled(bool(self._items))

    def _set_all_checked(self, checked: bool) -> None:
        self.table.blockSignals(True)
        for index in range(self.table.topLevelItemCount()):
            row = self.table.topLevelItem(index)
            item = self._item_for_row(row)
            if item is None or item.applied:
                continue
            row.setCheckState(COL_CHECK, Qt.Checked if checked else Qt.Unchecked)
        self.table.blockSignals(False)

    def _item_for_row(self, row: QTreeWidgetItem):
        for item in self._items:
            if self._row_items.get(id(item)) is row:
                return item
        return None

    def _on_item_changed(self, row: QTreeWidgetItem, column: int) -> None:
        if column != COL_CHECK:
            return
        item = self._item_for_row(row)
        if item is None:
            return
        if row.checkState(COL_CHECK) == Qt.Checked and item.applied:
            row.setCheckState(COL_CHECK, Qt.Unchecked)

    def _on_double_click(self, row: QTreeWidgetItem, _column: int) -> None:
        item = self._item_for_row(row)
        if item is None:
            return
        folder = os.path.dirname(item.filepath)
        try:
            os.startfile(folder)  # type: ignore[attr-defined]
        except AttributeError:
            QMessageBox.information(self, "Путь", item.filepath)
        except OSError as exc:
            QMessageBox.warning(
                self, "Ошибка", f"Не удалось открыть папку:\n{exc}"
            )

    # ------------------------------------------------------------------
    # Применение правок
    # ------------------------------------------------------------------
    def on_fix_one(self, item) -> None:
        if item.applied:
            return
        print(f"\n=== Исправление: {item.filename} ===")
        print(f"  {item.field_name}: '{item.old_text}' -> '{item.new_text}'")

        self.start_task(
            lambda: self._apply_single(item),
            controls=[self.scan_btn, self.fix_all_btn, self.music_field,
                      self.ext_edit, self.dry_run_check],
            on_success=lambda success: self._after_single(item, success),
        )

    def _apply_single(self, item) -> bool:
        if self.dry_run_check.isChecked():
            item.applied = True
            print("  [DRY-RUN] Изменения не записаны.")
            return True
        ok = fixtags.apply_item(item, save=True)
        if ok:
            print("  Сохранено.")
        else:
            print("  Не удалось сохранить.")
        return ok

    def _after_single(self, item, success) -> None:
        if not success:
            QMessageBox.warning(
                self, "Не удалось",
                f"Файл не был изменён:\n{item.filepath}\n\n"
                "Подробности — в консоли."
            )
            return
        row = self._row_items.get(id(item))
        if row is not None:
            self.table.blockSignals(True)
            row.setText(COL_STATUS, "Исправлено")
            row.setCheckState(COL_CHECK, Qt.Unchecked)
            for column in (COL_FILE, COL_FIELD, COL_OLD, COL_NEW, COL_STATUS):
                row.setForeground(column, QBrush(COLOR_DONE))
            self.table.blockSignals(False)
            widget = self.table.itemWidget(row, COL_ACTION)
            if isinstance(widget, QPushButton):
                widget.setEnabled(False)
        self._update_pending_state()

    def on_fix_all(self) -> None:
        pending = []
        for index in range(self.table.topLevelItemCount()):
            row = self.table.topLevelItem(index)
            if row.checkState(COL_CHECK) != Qt.Checked:
                continue
            item = self._item_for_row(row)
            if item is not None and not item.applied:
                pending.append(item)

        if not pending:
            QMessageBox.information(
                self, "Нечего исправлять",
                "Отметьте галочками правки, которые нужно применить."
            )
            return

        dry_run = self.dry_run_check.isChecked()
        files = len({item.filepath for item in pending})
        method = (
            "Файлы не будут изменены — включён режим тестирования."
            if dry_run
            else "Теги будут перезаписаны в UTF-8 (ID3v2.4)."
        )
        answer = QMessageBox.question(
            self, "Подтверждение",
            f"Применить правок: {len(pending)}\nФайлов: {files}\n\n{method}\n\n"
            "Рекомендуется сначала сделать резервную копию папки.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        print("\n=== Исправление всех отмеченных правок ===")
        print(f"Правок: {len(pending)}, файлов: {files}")
        if dry_run:
            print("Режим: DRY-RUN (файлы не изменяются)")

        self.start_task(
            lambda: self._apply_batch(pending, dry_run),
            controls=[self.scan_btn, self.fix_all_btn, self.music_field,
                      self.ext_edit, self.dry_run_check,
                      self.select_all_btn, self.select_none_btn],
            on_success=lambda saved: self._after_batch(pending, saved, dry_run),
        )

    def _apply_batch(self, items, dry_run: bool) -> int:
        if dry_run:
            for item in items:
                item.applied = True
                print(f"  [DRY-RUN] {item.filename}: "
                      f"{item.field_name}: '{item.old_text}' -> '{item.new_text}'")
            print(f"\n[DRY-RUN] Обработано правок: {len(items)}")
            return len(items)

        saved = fixtags.apply_items(
            items,
            progress=lambda i, total, name: print(f"  [{i}/{total}] {name}"),
        )
        print(f"\nОбновлено файлов: {saved}, применено правок: {len(items)}")
        return saved

    def _after_batch(self, items, saved, dry_run: bool) -> None:
        for item in items:
            if not item.applied:
                continue
            row = self._row_items.get(id(item))
            if row is None:
                continue
            self.table.blockSignals(True)
            row.setText(COL_STATUS, "Исправлено")
            row.setCheckState(COL_CHECK, Qt.Unchecked)
            for column in (COL_FILE, COL_FIELD, COL_OLD, COL_NEW, COL_STATUS):
                row.setForeground(column, QBrush(COLOR_DONE))
            self.table.blockSignals(False)
            widget = self.table.itemWidget(row, COL_ACTION)
            if isinstance(widget, QPushButton):
                widget.setEnabled(False)

        self._update_pending_state()

        if dry_run:
            QMessageBox.information(
                self, "Тестовый режим",
                f"Обработано правок: {len(items)}.\n"
                "Файлы не изменялись — включён режим тестирования."
            )
        else:
            QMessageBox.information(
                self, "Готово",
                f"Обновлено файлов: {saved}.\n"
                f"Применено правок: {len(items)}.\n\n"
                "Подробности — в системной консоли."
            )

    def _update_pending_state(self) -> None:
        pending = [item for item in self._items if not item.applied]
        self.fix_all_btn.setEnabled(bool(pending))
        self.select_all_btn.setEnabled(bool(pending))
        self.select_none_btn.setEnabled(bool(pending))
        if not self._items:
            self.status_label.setText("Нажмите «Сканировать», чтобы найти правки.")
        elif not pending:
            self.status_label.setText(
                f"Все правки применены (всего {len(self._items)})."
            )
        else:
            files = len({item.filepath for item in pending})
            self.status_label.setText(
                f"Осталось правок: {len(pending)} в файлах: {files}."
            )

    # ------------------------------------------------------------------
    def on_export(self) -> None:
        if not self._items:
            return
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить отчёт", "tag_fixes.csv",
            "CSV (*.csv);;Текстовые файлы (*.txt);;Все файлы (*.*)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as handle:
                import csv

                writer = csv.writer(handle, delimiter=";")
                writer.writerow(
                    ["Файл", "Поле", "Было", "Станет", "Статус"]
                )
                for item in self._items:
                    writer.writerow([
                        item.filepath,
                        item.display_field,
                        item.old_text,
                        item.new_text,
                        "Исправлено" if item.applied else "Не исправлено",
                    ])
        except OSError as exc:
            QMessageBox.critical(
                self, "Ошибка записи", f"Не удалось сохранить отчёт:\n{exc}"
            )
            return
        QMessageBox.information(self, "Готово", f"Отчёт сохранён:\n{path}")

    # ------------------------------------------------------------------
    # Совместимость со старым именем кнопки
    # ------------------------------------------------------------------
    def on_fix(self) -> None:
        self.on_scan()
