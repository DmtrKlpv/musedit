"""Вкладка 6: Поиск дубликатов (duplsearch.py).

Помимо поиска: живое наполнение списка групп, сравнение файлов по размеру и
битрейту, удаление выбранной копии в Корзину через send2trash.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QFileDialog, QHBoxLayout,
    QHeaderView, QLabel, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..engines import duplsearch
from ..exclusions import ExclusionStore, describe, group_signature
from ..widgets import ActionButton, PathField, action_row
from .base import BaseTab

try:
    from send2trash import send2trash
    _HAS_SEND2TRASH = True
except Exception:
    send2trash = None
    _HAS_SEND2TRASH = False

def _theme_color(role: str):
    """Цвет из текущей темы для подсветки строк."""
    from ..theme import color as theme_color
    return theme_color(role)


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
        # Исключённые группы: «это не дубликаты». Хранятся между запусками,
        # чтобы не отвлекать пользователя одним и тем же случаем каждый раз.
        self.exclusions = ExclusionStore()
        self._hidden_by_exclusion = 0
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
        self.groups_tree.itemSelectionChanged.connect(self._update_exclude_state)
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

        # Загрузить отчёт, сохранённый в прошлый раз: сканировать заново
        # не нужно, если список уже есть.
        self.import_btn = QPushButton("Импортировать CSV…", self)
        self.import_btn.setMinimumHeight(32)
        self.import_btn.setToolTip(
            "Открыть ранее сохранённый отчёт duplicates_report.csv "
            "и продолжить работу с найденными группами."
        )
        self.import_btn.clicked.connect(self.on_import_csv)

        # Пересобрать отчёт по текущему состоянию списка: после удаления
        # файлов старый CSV содержит уже несуществующие пути.
        self.recreate_btn = QPushButton("Пересоздать CSV…", self)
        self.recreate_btn.setMinimumHeight(32)
        self.recreate_btn.setEnabled(False)
        self.recreate_btn.setToolTip(
            "Сохранить отчёт заново по текущему списку. Удалённые файлы "
            "в него уже не попадут."
        )
        self.recreate_btn.clicked.connect(self.on_recreate_csv)

        # Исключить выбранную группу: файлы совпадают по имени или хешу,
        # но это разные записи (например, версия с текстом и минус).
        self.exclude_btn = QPushButton("Исключить группу", self)
        self.exclude_btn.setMinimumHeight(32)
        self.exclude_btn.setEnabled(False)
        self.exclude_btn.setToolTip(
            "Убрать выбранную группу из результатов и больше не показывать "
            "её при поиске. Файлы на диске остаются нетронутыми."
        )
        self.exclude_btn.clicked.connect(self.on_exclude_group)

        self.excluded_list_btn = QPushButton("Исключённые: 0", self)
        self.excluded_list_btn.setMinimumHeight(32)
        self.excluded_list_btn.setToolTip(
            "Показать список исключённых групп и вернуть любую обратно."
        )
        self.excluded_list_btn.clicked.connect(self.on_show_exclusions)

        layout.addLayout(action_row(self.run_btn))
        layout.addLayout(action_row(self.import_btn, self.recreate_btn))
        layout.addLayout(action_row(self.exclude_btn,
                                    self.excluded_list_btn))

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
        # Счётчик скрытых обнуляем: он относится к текущему прогону,
        # а исключения остаются в хранилище.
        self._hidden_by_exclusion = 0
        self.exclude_btn.setEnabled(False)
        self._update_excluded_button()

    # ------------------------------------------------------------------
    def _append_group(self, group, count: int) -> None:
        """Добавляет найденную группу сразу, не дожидаясь конца сканирования."""
        # Исключённые группы не показываем: пользователь уже решил,
        # что дубликатами они не являются.
        if self.exclusions.is_excluded(group):
            self._hidden_by_exclusion += 1
            self._update_excluded_button()
            return

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

    # ------------------------------------------------------------------
    # Исключения
    # ------------------------------------------------------------------
    def _current_group(self):
        """Группа, выбранная в левой таблице, или None."""
        item = self.groups_tree.currentItem()
        if item is None:
            return None
        index = item.data(0, Qt.UserRole)
        if not isinstance(index, int) or index >= len(self._groups):
            return None
        return self._groups[index]

    def _update_exclude_state(self) -> None:
        """Кнопка исключения активна только при выбранной группе."""
        self.exclude_btn.setEnabled(self._current_group() is not None)
        self._update_excluded_button()

    def _update_excluded_button(self) -> None:
        """Счётчик исключённых групп на кнопке."""
        total = len(self.exclusions)
        text = f"Исключённые: {total}"
        if self._hidden_by_exclusion and self._hidden_by_exclusion != total:
            text += f" (скрыто {self._hidden_by_exclusion})"
        self.excluded_list_btn.setText(text)
        self.excluded_list_btn.setEnabled(True)

    # ------------------------------------------------------------------
    def on_exclude_group(self) -> None:
        """Исключает выбранную группу из результатов и из будущих поисков."""
        group = self._current_group()
        if group is None:
            QMessageBox.information(
                self, "Группа не выбрана",
                "Выберите группу в левом списке, которую нужно исключить."
            )
            return

        names = ", ".join(sorted({
            os.path.basename(e.get("path", "")) for e in group.get("files", [])
        }))
        paths = "\n".join(e.get("path", "") for e in group.get("files", []))

        answer = QMessageBox.question(
            self, "Исключить группу",
            f"Исключить эту группу из дубликатов?\n\n"
            f"Файлы: {names}\n"
            f"Совпадение: {group.get('match', 'SHA256')}\n\n"
            f"Файлы на диске останутся нетронутыми — они просто перестанут "
            f"попадать в список дубликатов.\n\n{paths}",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if answer != QMessageBox.Yes:
            return

        self.exclusions.exclude(group)
        print(f"[ИСКЛЮЧЕНО] {names} "
              f"(совпадение: {group.get('match', 'SHA256')})")

        # Убираем из текущего списка без повторного поиска
        if group in self._groups:
            index = self._groups.index(group)
            self._groups.remove(group)
            self._hidden_by_exclusion += 1
            self._refill_groups(min(index, max(0, len(self._groups) - 1)))

        self.status_label.setText(
            f"Группа исключена. Осталось групп: {len(self._groups)}. "
            f"Вернуть можно кнопкой «{self.excluded_list_btn.text()}»."
        )
        self._update_exclude_state()

    # ------------------------------------------------------------------
    def on_show_exclusions(self) -> None:
        """Диалог со списком исключённых групп."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Исключённые группы")
        dialog.resize(760, 460)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        hint = QLabel(
            "Эти группы не считаются дубликатами и не показываются при "
            "поиске. Вернуть группу обратно можно кнопкой ниже."
        )
        hint.setWordWrap(True)
        hint.setProperty("role", "hint")
        layout.addWidget(hint)

        listing = QListWidget(dialog)
        entries = list(self.exclusions.entries())
        for signature, payload in entries:
            stored_match = (payload.get("match") or "").strip()
            match, names = describe(signature, stored_match)
            match = match or "—"
            # Одинаковые имена сворачиваем: «07 - Иод.mp3 ×2»
            unique = list(dict.fromkeys(names))
            shown = ", ".join(
                f"{name} ×{names.count(name)}" if names.count(name) > 1
                else name
                for name in unique
            )
            label = f"[{match}] {shown}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, signature)
            paths = payload.get("paths") or []
            if paths:
                item.setToolTip("\n".join(paths))
            listing.addItem(item)
        layout.addWidget(listing, 1)

        if not entries:
            empty = QLabel("Исключённых групп пока нет.")
            empty.setProperty("role", "hint")
            layout.addWidget(empty)

        buttons = QHBoxLayout()

        restore_btn = QPushButton("Вернуть выбранную", dialog)
        restore_btn.setMinimumHeight(30)
        restore_btn.setEnabled(bool(entries))

        def restore() -> None:
            current = listing.currentItem()
            if current is None:
                return
            signature = current.data(Qt.UserRole)
            if self.exclusions.restore(signature):
                print(f"[ВОЗВРАТ] {signature}")
                row = listing.row(current)
                listing.takeItem(row)
                if self._hidden_by_exclusion:
                    self._hidden_by_exclusion -= 1
                self._update_excluded_button()
                self.status_label.setText(
                    "Группа возвращена. Запустите поиск или импорт, "
                    "чтобы увидеть её снова."
                )

        restore_btn.clicked.connect(restore)

        clear_btn = QPushButton("Очистить все", dialog)
        clear_btn.setMinimumHeight(30)
        clear_btn.setEnabled(bool(entries))

        def clear_all() -> None:
            if not entries:
                return
            answer = QMessageBox.question(
                dialog, "Очистить исключения",
                f"Вернуть все группы ({len(entries)})? После этого они снова "
                f"будут считаться дубликатами.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if answer != QMessageBox.Yes:
                return
            self.exclusions.clear()
            listing.clear()
            self._hidden_by_exclusion = 0
            self._update_excluded_button()
            self.status_label.setText(
                "Все исключения сняты. Запустите поиск заново."
            )
            clear_btn.setEnabled(False)
            restore_btn.setEnabled(False)

        clear_btn.clicked.connect(clear_all)

        close_btn = QPushButton("Закрыть", dialog)
        close_btn.setMinimumHeight(30)
        close_btn.clicked.connect(dialog.accept)

        buttons.addWidget(restore_btn)
        buttons.addWidget(clear_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

        dialog.exec()

    # ------------------------------------------------------------------
    def _refill_groups(self, select_index: int = 0) -> None:
        """Перерисовывает список групп и правую таблицу из self._groups.

        Общая точка для импорта CSV и удаления файла: одна функция вместо
        копий кода в нескольких местах.
        """
        self.groups_tree.clear()
        self.files_tree.clear()

        if not self._groups:
            self.recreate_btn.setEnabled(False)
            return

        for index, group in enumerate(self._groups):
            item = QTreeWidgetItem([
                group["filename"],
                group.get("match", "SHA256"),
                str(len(group["files"])),
            ])
            item.setData(0, Qt.UserRole, index)
            item.setToolTip(0, group["filename"])
            self.groups_tree.addTopLevelItem(item)

        last = self.groups_tree.topLevelItemCount() - 1
        target = max(0, min(select_index, last))
        self.groups_tree.setCurrentItem(self.groups_tree.topLevelItem(target))
        self.recreate_btn.setEnabled(True)

    def _count_missing(self) -> int:
        """Сколько файлов из списка уже отсутствует на диске."""
        return sum(
            1
            for group in self._groups
            for entry in group["files"]
            if not os.path.isfile(entry["path"])
        )

    # ------------------------------------------------------------------
    def on_import_csv(self) -> None:
        """Загружает ранее сохранённый отчёт о дубликатах."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Импорт отчёта о дубликатах", "",
            "CSV-отчёты (*.csv);;Все файлы (*.*)",
        )
        if not path:
            return

        try:
            groups = duplsearch.read_csv(path)
        except duplsearch.CsvImportError as exc:
            QMessageBox.warning(self, "Не удалось импортировать", str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(
                self, "Ошибка чтения",
                f"Файл не удалось прочитать:\n{exc}"
            )
            return

        kept = self.exclusions.filter_groups(groups)
        hidden = len(groups) - len(kept)
        self._groups = kept
        self._hidden_by_exclusion = hidden
        self._refill_groups()
        self._update_excluded_button()
        print(f"[ИМПОРТ] {path}: групп {len(self._groups)}")

        total_files = sum(len(g["files"]) for g in self._groups)
        missing = self._count_missing()
        text = (f"Импортировано групп: {len(self._groups)}, "
                f"файлов: {total_files}.")
        if missing:
            text += (f" Отсутствует на диске: {missing} — "
                     f"они помечены серым.")
        self.status_label.setText(text)

    # ------------------------------------------------------------------
    def on_recreate_csv(self) -> None:
        """Сохраняет отчёт заново по текущему списку групп."""
        if not self._groups:
            QMessageBox.information(
                self, "Нечего сохранять",
                "Список групп пуст — сначала выполните поиск или импорт."
            )
            return

        suggested = os.path.join(
            self.dir_field.text() or os.getcwd(),
            duplsearch.DEFAULT_CSV_NAME,
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить отчёт", suggested,
            "CSV-отчёты (*.csv);;Все файлы (*.*)",
        )
        if not path:
            return

        try:
            saved = duplsearch.write_csv(self._groups, path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(
                self, "Ошибка записи",
                f"Не удалось сохранить отчёт:\n{exc}"
            )
            return

        missing = self._count_missing()
        groups_count = len(self._groups)
        files_count = sum(len(g["files"]) for g in self._groups)
        print(f"[CSV] {saved}: групп {groups_count}, файлов {files_count}")

        text = (f"Отчёт пересоздан: групп {groups_count}, "
                f"файлов {files_count}.")
        if missing:
            text += f" Отсутствующих на диске: {missing}."
        self.status_label.setText(text)

        QMessageBox.information(
            self, "Отчёт сохранён",
            f"{saved}\n\nГрупп: {groups_count}\nФайлов: {files_count}"
            + (f"\nОтсутствует на диске: {missing}" if missing else "")
        )

    # ------------------------------------------------------------------
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
            exists = entry.get("exists", os.path.isfile(entry["path"]))

            button = QPushButton("Удалить", self.files_tree)
            button.setFixedWidth(100)
            button.setFixedHeight(24)
            button.setEnabled(exists)
            button.setToolTip(
                ("Отправить этот файл в Корзину"
                 if _HAS_SEND2TRASH
                 else "Удалить этот файл с диска")
                if exists
                else "Файла уже нет на диске — удалять нечего"
            )
            button.clicked.connect(
                lambda _checked=False, p=entry["path"]: self.on_delete_path(p)
            )
            self.files_tree.setItemWidget(item, COL_FILE_ACTION, button)

            # Файл, импортированный из отчёта, мог быть удалён раньше:
            # помечаем строку, чтобы это было видно сразу.
            if not exists:
                for column in range(COL_FILE_ACTION):
                    item.setForeground(column, QBrush(_theme_color("text_disabled")))
                item.setToolTip(
                    COL_FILE_PATH,
                    f"{entry['path']}\nФайл отсутствует на диске"
                )

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
        """Убирает файл из результатов и перерисовывает таблицы.

        Группа из одного файла перестаёт быть группой дубликатов и
        удаляется целиком.
        """
        for group in list(self._groups):
            group["files"] = [f for f in group["files"] if f["path"] != path]
            if len(group["files"]) <= 1:
                self._groups.remove(group)

        current_index = 0
        if self.groups_tree.currentItem() is not None:
            stored = self.groups_tree.currentItem().data(0, Qt.UserRole)
            if isinstance(stored, int):
                current_index = stored

        self._refill_groups(current_index)

        if not self._groups:
            self.status_label.setText("Дубликатов больше не осталось.")
            return

        missing = self._count_missing()
        text = f"Осталось групп: {len(self._groups)}."
        if missing:
            text += f" Отсутствует на диске: {missing}."
        self.status_label.setText(text)
