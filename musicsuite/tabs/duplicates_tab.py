"""Вкладка 6: Поиск дубликатов (duplsearch.py).

Помимо поиска: живое наполнение списка групп, сравнение файлов по размеру и
битрейту, удаление выбранной копии в Корзину через send2trash.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
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
COL_FILE_MATCH = 3
COL_FILE_ACTION = 4


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

        # Три независимых способа сравнения. SHA-256 включён всегда:
        # совпадение содержимого — единственный признак, который не даёт
        # ложных срабатываний.
        modes_row = QHBoxLayout()
        modes_row.setContentsMargins(0, 0, 0, 0)
        modes_row.setSpacing(16)

        self.sha_check = QCheckBox("По содержимому (SHA-256)")
        self.sha_check.setChecked(True)
        self.sha_check.setEnabled(False)
        self.sha_check.setToolTip(
            "Сравнение по SHA-256 всегда включено: это единственный способ, "
            "который гарантирует одинаковое содержимое файлов."
        )
        modes_row.addWidget(self.sha_check)

        self.name_check = QCheckBox("По имени файла")
        self.name_check.setToolTip(
            "Считать дубликатами файлы с одинаковым именем, даже если "
            "содержимое разное. Полезно для поиска одной песни в разных "
            "качествах."
        )
        modes_row.addWidget(self.name_check)

        self.tags_check = QCheckBox("По mp3-тегам")
        self.tags_check.setToolTip(
            "Считать дубликатами файлы с одинаковыми исполнителем и названием "
            "в тегах. Медленнее: теги читаются с диска."
        )
        modes_row.addWidget(self.tags_check)

        modes_row.addStretch(1)
        form.addRow("Сравнивать:", modes_row)

        layout.addLayout(form)

        layout.addWidget(self.make_hint(
            "Дубликаты определяются по SHA-256 содержимого файла, а также "
            "по имени файла или mp3-тегам — выберите способы выше. "
            "Слева — группы одинаковых файлов, справа — файлы выбранной группы "
            "с размером и битрейтом. Во время сканирования группы появляются "
            "по мере обнаружения. Кнопка удаления отправляет выбранный файл "
            "в Корзину (библиотека send2trash), поэтому его можно восстановить. "
            "Кнопка «Удалить» есть в каждой строке правой таблицы."
        ))

        splitter = QSplitter(Qt.Horizontal, self)

        # Левая панель: группы
        left = QWidget(self)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)
        left_layout.addWidget(self._bold("Группы дубликатов"))
        self.groups_tree = QTreeWidget(left)
        self.groups_tree.setHeaderLabels(["Файл", "Совпадение", "Копий"])
        self.groups_tree.setRootIsDecorated(False)
        self.groups_tree.setAlternatingRowColors(True)
        self.groups_tree.setUniformRowHeights(True)
        self.groups_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        groups_header = self.groups_tree.header()
        groups_header.setSectionResizeMode(0, QHeaderView.Stretch)
        groups_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        groups_header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.groups_tree.currentItemChanged.connect(self._on_group_changed)
        left_layout.addWidget(self.groups_tree, 1)

        # Правая панель: файлы группы
        right = QWidget(self)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)
        right_layout.addWidget(self._bold("Файлы в выбранной группе"))
        self.files_tree = QTreeWidget(right)
        self.files_tree.setHeaderLabels(
            ["Путь", "Размер", "Битрейт", "Совпадение", ""]
        )
        self.files_tree.setRootIsDecorated(False)
        self.files_tree.setAlternatingRowColors(True)
        self.files_tree.setUniformRowHeights(True)
        self.files_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        files_header = self.files_tree.header()
        files_header.setSectionResizeMode(COL_FILE_PATH, QHeaderView.Stretch)
        files_header.setSectionResizeMode(COL_FILE_SIZE,
                                          QHeaderView.ResizeToContents)
        files_header.setSectionResizeMode(COL_FILE_BITRATE,
                                          QHeaderView.ResizeToContents)
        files_header.setSectionResizeMode(COL_FILE_MATCH,
                                          QHeaderView.ResizeToContents)
        files_header.setSectionResizeMode(COL_FILE_ACTION, QHeaderView.Fixed)
        self.files_tree.setColumnWidth(COL_FILE_ACTION, 116)
        self.files_tree.itemDoubleClicked.connect(self._on_file_double_clicked)
        right_layout.addWidget(self.files_tree, 1)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([380, 620])
        layout.addWidget(splitter, 1)

        # Кнопка удаления переехала в строки правой таблицы: так видно,
        # какой именно файл удаляется, и не нужно сначала выделять строку.
        self.run_btn = ActionButton("Начать поиск", self, minimum_width=190)
        self.run_btn.clicked.connect(self.on_search)

        layout.addLayout(action_row(self.run_btn))

        self.status_label = QLabel("Поиск ещё не выполнялся.")
        self.status_label.setProperty("role", "status")
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

        modes = [duplsearch.MODE_SHA256]
        if self.name_check.isChecked():
            modes.append(duplsearch.MODE_NAME)
        if self.tags_check.isChecked():
            modes.append(duplsearch.MODE_TAGS)

        self.start_task(
            lambda progress: duplsearch.find_duplicates(
                directory, progress=progress, modes=modes,
                on_group=lambda group, count: self.group_found.emit(group, count),
            ),
            controls=[self.run_btn, self.dir_field, self.name_check,
                      self.tags_check],
            on_success=self._on_results,
            busy_text="Сканирование папки",
            busy_progress=True,
        )

    def _clear_results(self) -> None:
        self.groups_tree.clear()
        self.files_tree.clear()
        self._groups = []

    # ------------------------------------------------------------------
    def _append_group(self, group, count: int) -> None:
        """Добавляет найденную группу сразу, не дожидаясь конца сканирования."""
        self._groups.append(group)
        item = QTreeWidgetItem([
            group["filename"],
            group.get("match", "SHA256"),
            str(len(group["files"])),
        ])
        item.setData(0, Qt.UserRole, len(self._groups) - 1)
        item.setToolTip(0, group["filename"])
        self.groups_tree.addTopLevelItem(item)

        self.status_label.setText(f"Найдено групп: {count}, "
                                  f"совпадение: {group.get('match', '—')}")

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
        if current is None:
            return

        index = current.data(0, Qt.UserRole)
        if not isinstance(index, int) or index >= len(self._groups):
            return

        group = self._groups[index]
        match_label = group.get("match", "SHA256")

        for entry in group["files"]:
            item = QTreeWidgetItem([
                entry["path"],
                entry["size_str"],
                entry["bitrate"],
                match_label,
                "",
            ])
            item.setData(0, Qt.UserRole, entry["path"])
            item.setToolTip(0, entry["path"])
            item.setToolTip(
                COL_FILE_MATCH,
                f"Способ, которым этот файл признан дубликатом: {match_label}"
            )
            self.files_tree.addTopLevelItem(item)

            # Кнопка «Удалить» в строке: не нужно выделять файл, чтобы
            # отправить его в Корзину.
            button = QPushButton("Удалить", self.files_tree)
            button.setFixedWidth(100)
            button.setFixedHeight(24)
            button.setToolTip(
                "Отправить этот файл в Корзину"
                if _HAS_SEND2TRASH
                else "Удалить этот файл с диска"
            )
            button.clicked.connect(
                lambda _checked=False, p=entry["path"]: self.on_delete_path(p)
            )
            self.files_tree.setItemWidget(item, COL_FILE_ACTION, button)

    def _on_file_double_clicked(self, item, _column) -> None:
        path = item.data(0, Qt.UserRole)
        if not path:
            return
        folder = os.path.dirname(path)
        if os.path.isdir(folder):
            try:
                os.startfile(folder)  # Windows
            except AttributeError:
                from ..subproc import popen
                popen(["xdg-open", folder])

    # ------------------------------------------------------------------
    def on_delete_path(self, path: str) -> None:
        """Удаляет конкретный файл, выбранный кнопкой в строке.

        Раньше удаление шло по выделенной строке — сначала нужно было
        кликнуть по файлу, потом нажать кнопку внизу. Теперь кнопка
        в строке знает свой путь, и лишний шаг не нужен.
        """
        if not path:
            return
        if not os.path.exists(path):
            QMessageBox.warning(
                self, "Файл недоступен",
                "Выбранный файл не существует на диске."
            )
            self._remove_from_results(path)
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
            return

        for index, group in enumerate(self._groups):
            item = QTreeWidgetItem([
                group["filename"],
                group.get("match", "SHA256"),
                str(len(group["files"])),
            ])
            item.setData(0, Qt.UserRole, index)
            self.groups_tree.addTopLevelItem(item)

        target = 0
        if isinstance(current_index, int) and current_index < self.groups_tree.topLevelItemCount():
            target = current_index
        self.groups_tree.setCurrentItem(self.groups_tree.topLevelItem(target))
        self.status_label.setText(f"Осталось групп: {len(self._groups)}.")
