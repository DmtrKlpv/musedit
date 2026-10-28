"""Вкладка 6: Поиск дубликатов (duplsearch.py).

Помимо поиска: живое наполнение списка групп, сравнение файлов по размеру и
битрейту, удаление выбранной копии в Корзину через send2trash.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
    QPushButton, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..engines import duplsearch
from ..widgets import ActionButton, PathField, action_row
from .base import BaseTab

try:
    from send2trash import send2trash
    _HAS_SEND2TRASH = True
except Exception:
    send2trash = None
    _HAS_SEND2TRASH = False

COL_GROUP_NAME = 0
COL_GROUP_COPIES = 1

COL_FILE_PATH = 0
COL_FILE_SIZE = 1
COL_FILE_BITRATE = 2


class DuplicatesTab(BaseTab):
    TITLE = "Поиск дубликатов"

    group_found = Signal(object, int)

    def __init__(self, main_window, parent=None):
        super().__init__(main_window, parent)

        self._groups = []
        self.group_found.connect(self._append_group)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        form = self.make_form()
        self.dir_field = PathField("dir", "Папка, в которой искать дубликаты")
        form.addRow("Директория для поиска:", self.dir_field)
        layout.addLayout(form)

        layout.addWidget(self.make_hint(
            "Дубликаты определяются по SHA-256 содержимого файла. "
            "Слева — группы одинаковых файлов, справа — файлы выбранной группы "
            "с размером и битрейтом. Во время сканирования группы появляются "
            "по мере обнаружения. Кнопка удаления отправляет выбранный файл "
            "в Корзину (библиотека send2trash), поэтому его можно восстановить."
        ))

        splitter = QSplitter(Qt.Horizontal, self)

        # Левая панель: группы
        left = QWidget(self)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)
        left_layout.addWidget(self._bold("Группы дубликатов"))
        self.groups_tree = QTreeWidget(left)
        self.groups_tree.setHeaderLabels(["Файл", "Копий"])
        self.groups_tree.setRootIsDecorated(False)
        self.groups_tree.setAlternatingRowColors(True)
        self.groups_tree.setUniformRowHeights(True)
        self.groups_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.groups_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.groups_tree.header().setSectionResizeMode(
            1, QHeaderView.ResizeToContents
        )
        self.groups_tree.currentItemChanged.connect(self._on_group_changed)
        left_layout.addWidget(self.groups_tree, 1)

        # Правая панель: файлы группы
        right = QWidget(self)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)
        right_layout.addWidget(self._bold("Файлы в выбранной группе"))
        self.files_tree = QTreeWidget(right)
        self.files_tree.setHeaderLabels(["Путь", "Размер", "Битрейт"])
        self.files_tree.setRootIsDecorated(False)
        self.files_tree.setAlternatingRowColors(True)
        self.files_tree.setUniformRowHeights(True)
        self.files_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.files_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.files_tree.header().setSectionResizeMode(
            1, QHeaderView.ResizeToContents
        )
        self.files_tree.header().setSectionResizeMode(
            2, QHeaderView.ResizeToContents
        )
        self.files_tree.itemSelectionChanged.connect(self._on_file_selection)
        self.files_tree.itemDoubleClicked.connect(self._on_file_double_clicked)
        right_layout.addWidget(self.files_tree, 1)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([380, 620])
        layout.addWidget(splitter, 1)

        self.trash_btn = QPushButton(
            "Удалить выбранный файл в Корзину" if _HAS_SEND2TRASH
            else "Удалить выбранный файл (без Корзины)", self
        )
        self.trash_btn.setMinimumHeight(32)
        self.trash_btn.setEnabled(False)
        self.trash_btn.clicked.connect(self.on_delete_selected)

        self.run_btn = ActionButton("Начать поиск", self, minimum_width=190)
        self.run_btn.clicked.connect(self.on_search)

        layout.addLayout(action_row(self.trash_btn, self.run_btn))

        self.status_label = QLabel("Поиск ещё не выполнялся.")
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
    def on_search(self) -> None:
        directory = self.dir_field.text()
        if not directory:
            QMessageBox.warning(self, "Не указана папка",
                                "Выберите директорию для поиска дубликатов.")
            return

        self._clear_results()
        print("\n=== Поиск дубликатов ===")
        self.status_label.setText("Идёт сканирование...")

        self.start_task(
            lambda progress: duplsearch.find_duplicates(
                directory, progress=progress,
                on_group=lambda group, count: self.group_found.emit(group, count),
            ),
            controls=[self.run_btn, self.dir_field, self.trash_btn],
            on_success=self._on_results,
            busy_text="Сканирование папки",
            busy_progress=True,
        )

    def _clear_results(self) -> None:
        self.groups_tree.clear()
        self.files_tree.clear()
        self._groups = []
        self.trash_btn.setEnabled(False)

    # ------------------------------------------------------------------
    def _append_group(self, group, count: int) -> None:
        """Добавляет найденную группу сразу, не дожидаясь конца сканирования."""
        self._groups.append(group)
        item = QTreeWidgetItem([group["filename"], str(len(group["files"]))])
        item.setData(0, Qt.UserRole, len(self._groups) - 1)
        item.setToolTip(0, group["filename"])
        self.groups_tree.addTopLevelItem(item)

        self.status_label.setText(f"Найдено групп: {count}")

        if self.groups_tree.currentItem() is None:
            self.groups_tree.setCurrentItem(item)

    def _on_results(self, groups) -> None:
        # При живом наполнении группы уже добавлены — синхронизируемся.
        if groups and len(groups) != len(self._groups):
            self._groups = []
            self.groups_tree.clear()
            for group in groups:
                self._append_group(group, len(self._groups) + 1)

        if not self._groups:
            self.status_label.setText("Дубликаты не найдены.")
            return

        total_wasted = 0
        for group in self._groups:
            for file_index, entry in enumerate(group["files"]):
                if file_index > 0:
                    total_wasted += entry["size_bytes"]

        wasted_mb = round(total_wasted / (1024 * 1024), 2)
        self.status_label.setText(
            f"Найдено групп: {len(self._groups)}. "
            f"Потенциально освобождается: {wasted_mb} МБ "
            f"(все копии, кроме первой в группе). "
            f"Отчёт сохранён в duplicates_report.csv"
        )

    def _on_group_changed(self, current, _previous) -> None:
        self.files_tree.clear()
        self.trash_btn.setEnabled(False)
        if current is None:
            return

        index = current.data(0, Qt.UserRole)
        if not isinstance(index, int) or index >= len(self._groups):
            return

        for entry in self._groups[index]["files"]:
            item = QTreeWidgetItem([
                entry["path"], entry["size_str"], entry["bitrate"]
            ])
            item.setData(0, Qt.UserRole, entry["path"])
            item.setToolTip(0, entry["path"])
            self.files_tree.addTopLevelItem(item)

    def _on_file_selection(self) -> None:
        self.trash_btn.setEnabled(bool(self.files_tree.selectedItems()))

    def _on_file_double_clicked(self, item, _column) -> None:
        path = item.data(0, Qt.UserRole)
        if not path:
            return
        folder = os.path.dirname(path)
        if os.path.isdir(folder):
            try:
                os.startfile(folder)  # Windows
            except AttributeError:
                import subprocess
                subprocess.Popen(["xdg-open", folder])

    # ------------------------------------------------------------------
    def on_delete_selected(self) -> None:
        items = self.files_tree.selectedItems()
        if not items:
            QMessageBox.information(
                self, "Ничего не выбрано",
                "Выберите файл, который нужно удалить."
            )
            return

        path = items[0].data(0, Qt.UserRole)
        if not path or not os.path.exists(path):
            QMessageBox.warning(
                self, "Файл недоступен",
                "Выбранный файл не существует на диске."
            )
            return

        current = self.groups_tree.currentItem()
        group_index = current.data(0, Qt.UserRole) if current else None
        group_name = current.text(0) if current else ""

        copies = 0
        if isinstance(group_index, int) and group_index < len(self._groups):
            copies = len(self._groups[group_index]["files"])

        extra = ""
        if copies <= 2:
            extra = ("\n\nВнимание: в группе останется только один файл — "
                     "проверьте, что удаляете именно лишнюю копию.")

        method = ("в Корзину" if _HAS_SEND2TRASH
                  else "с диска без возможности восстановления")
        answer = QMessageBox.question(
            self, "Подтверждение удаления",
            f"Удалить файл {method}?\n\n{path}\n\n"
            f"Группа: {group_name}{extra}",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if answer != QMessageBox.Yes:
            return

        try:
            if _HAS_SEND2TRASH:
                send2trash(path)
                print(f"[УДАЛЕНО В КОРЗИНУ] {path}")
            else:
                os.remove(path)
                print(f"[УДАЛЕНО С ДИСКА] {path}")
        except Exception as exc:
            QMessageBox.critical(
                self, "Ошибка удаления",
                f"Не удалось удалить файл:\n{exc}"
            )
            return

        self._remove_from_results(path)
        QMessageBox.information(self, "Готово", "Файл удалён.")

    def _remove_from_results(self, path: str) -> None:
        for group in list(self._groups):
            group["files"] = [f for f in group["files"] if f["path"] != path]
            if len(group["files"]) <= 1:
                self._groups.remove(group)

        current_index = None
        if self.groups_tree.currentItem() is not None:
            current_index = self.groups_tree.currentItem().data(0, Qt.UserRole)

        self.groups_tree.clear()
        self.files_tree.clear()

        if not self._groups:
            self.status_label.setText("Дубликатов больше не осталось.")
            self.trash_btn.setEnabled(False)
            return

        for index, group in enumerate(self._groups):
            item = QTreeWidgetItem([group["filename"], str(len(group["files"]))])
            item.setData(0, Qt.UserRole, index)
            self.groups_tree.addTopLevelItem(item)

        target = 0
        if isinstance(current_index, int) and current_index < self.groups_tree.topLevelItemCount():
            target = current_index
        self.groups_tree.setCurrentItem(self.groups_tree.topLevelItem(target))
        self.status_label.setText(f"Осталось групп: {len(self._groups)}.")
