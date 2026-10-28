"""Главное окно приложения со вкладками и общей консолью."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow, QMessageBox, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from .console import ConsoleView
from .tabs import (
    CueTab, DownloadHubTab, DuplicatesTab, PlaylistSearchTab, TagsTab,
    UpdatePlaylistTab,
)

APP_TITLE = "MusEdit 1.2.56"
COLOR_LINK = "#5b21b6"
COLOR_PRIMARY = "#2563eb"
COLOR_PRIMARY_HOVER = "#1d4ed8"
COLOR_PRIMARY_DISABLED = "#93c5fd"

STYLE_SHEET = f"""
QMainWindow {{ background: #f6f7f9; }}
QTabWidget::pane {{ border: 1px solid #d9dde3; border-radius: 6px; background: #ffffff; }}
QTabBar::tab {{
    padding: 8px 16px; margin-right: 2px; border: 1px solid #d9dde3;
    border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px;
    background: #eef0f3; color: #3f4650;
}}
QTabBar::tab:selected {{ background: #ffffff; color: {COLOR_LINK}; font-weight: 600; }}
QTabBar::tab:hover {{ background: #f4f5f7; }}
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {{
    padding: 5px 7px; border: 1px solid #cfd4db; border-radius: 5px; background: #ffffff;
    selection-background-color: #d7d0f5;
}}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {{
    border-color: {COLOR_LINK};
}}
QLineEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{
    background: #f2f3f5; color: #8a919b;
}}
QPushButton {{
    padding: 6px 14px; border: 1px solid #cfd4db; border-radius: 5px;
    background: #ffffff; color: #2f3540;
}}
QPushButton:hover {{ background: #f2f3f6; border-color: #b9c0c9; }}
QPushButton:pressed {{ background: #e8eaee; }}
QPushButton:disabled {{ color: #9aa1ab; background: #f4f5f7; }}
QPushButton#primary {{
    background: {COLOR_PRIMARY}; border-color: {COLOR_PRIMARY}; color: #ffffff; font-weight: 600;
}}
QPushButton#primary:hover {{ background: {COLOR_PRIMARY_HOVER}; border-color: {COLOR_PRIMARY_HOVER}; }}
QPushButton#primary:disabled {{ background: {COLOR_PRIMARY_DISABLED}; border-color: {COLOR_PRIMARY_DISABLED}; color: #eff6ff; }}
QPushButton#modeSwitch {{
    padding: 6px 18px; border: 1px solid #cfd4db; border-radius: 0;
    background: #f4f5f7; color: #3f4650;
}}
QPushButton#modeSwitch:hover {{ background: #e9ebef; }}
QPushButton#modeSwitch:checked {{
    background: #ffffff; color: {COLOR_LINK}; font-weight: 600;
    border-bottom: 2px solid {COLOR_PRIMARY};
}}
QPushButton#modeSwitch[segment="first"] {{
    border-top-left-radius: 6px; border-bottom-left-radius: 6px;
}}
QPushButton#modeSwitch[segment="last"] {{
    border-top-right-radius: 6px; border-bottom-right-radius: 6px;
}}
QGroupBox {{ border: 1px solid #d9dde3; border-radius: 6px; margin-top: 8px; padding-top: 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #3f4650; }}
QHeaderView::section {{
    background: #f2f4f7; border: none; border-bottom: 1px solid #d9dde3; padding: 5px;
    color: #3f4650;
}}
QTreeWidget {{ border: 1px solid #d9dde3; border-radius: 5px; background: #ffffff; }}
QTreeWidget::item:selected {{ background: #e9e4fa; color: #1f2430; }}
QSplitter::handle {{ background: #d9dde3; }}
QStatusBar {{ background: #eef0f3; color: #4b5563; }}
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1180, 860)
        self.setMinimumSize(940, 640)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(0)

        self.splitter = QSplitter(Qt.Vertical, central)

        self.tabs = QTabWidget(self.splitter)
        self.tabs.setDocumentMode(True)

        self.download_hub_tab = DownloadHubTab(self)
        self.tags_tab = TagsTab(self)
        self.cue_tab = CueTab(self)
        self.duplicates_tab = DuplicatesTab(self)
        self.update_playlist_tab = UpdatePlaylistTab(self)
        self.playlist_search_tab = PlaylistSearchTab(self)

        self.tabs.addTab(self.download_hub_tab, "Скачивание с Яндекс.Музыки")
        self.tabs.addTab(self.update_playlist_tab, "Обновление плейлиста")
        self.tabs.addTab(self.playlist_search_tab, "Поиск по плейлисту")
        self.tabs.addTab(self.tags_tab, "Исправление тегов MP3")
        self.tabs.addTab(self.cue_tab, "Конвертер CUE в MP3")
        self.tabs.addTab(self.duplicates_tab, "Поиск дубликатов")

        self.console = ConsoleView(self.splitter)

        self.splitter.addWidget(self.tabs)
        self.splitter.addWidget(self.console)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setSizes([470, 330])

        layout.addWidget(self.splitter)
        self.setCentralWidget(central)

        self._mark_primary_buttons()
        self._build_menu()

        self.statusBar().showMessage("Готово к работе")
        self.console.install()
        print(f"{APP_TITLE} — запущено.")
        print("Выберите вкладку, задайте параметры и нажмите кнопку запуска. "
              "Весь вывод утилит отображается ниже.\n")

    # ------------------------------------------------------------------
    def _mark_primary_buttons(self) -> None:
        for tab in (self.download_hub_tab, self.tags_tab, self.cue_tab,
                    self.duplicates_tab, self.update_playlist_tab,
                    self.playlist_search_tab):
            button = getattr(tab, "run_btn", None)
            if button is not None:
                button.setObjectName("primary")

    def _build_menu(self) -> None:
        tools_menu = self.menuBar().addMenu("Инструменты")

        clear_action = QAction("Очистить консоль", self)
        clear_action.setShortcut(QKeySequence("Ctrl+L"))
        clear_action.triggered.connect(self.console.clear)
        tools_menu.addAction(clear_action)

        save_action = QAction("Сохранить лог...", self)
        save_action.setShortcut(QKeySequence("Ctrl+S"))
        save_action.triggered.connect(self.console.save_log)
        tools_menu.addAction(save_action)

        tools_menu.addSeparator()

        quit_action = QAction("Выход", self)
        quit_action.setShortcut(QKeySequence("Ctrl+Q"))
        quit_action.triggered.connect(self.close)
        tools_menu.addAction(quit_action)

        help_menu = self.menuBar().addMenu("Справка")
        about_action = QAction("О программе", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _show_about(self) -> None:
        QMessageBox.about(
            self, "О программе",
            "<b>Музыкальные утилиты</b><br><br>"
            "Единая панель для пяти инструментов:<br>"
            ""
            "• скачивание треков из Яндекс.Музыки с готовым плейлистом;<br>"
            ""
            "• исправление кодировки тегов MP3;<br>"
            "• конвертация FLAC/APE + CUE в MP3;<br>"
            "• поиск дубликатов с удалением в Корзину.<br><br>"
            "Все тяжёлые операции выполняются в фоновых потоках."
        )

    # ------------------------------------------------------------------
    def show_console(self) -> None:
        """Прокручивает окно так, чтобы консоль была видна."""
        sizes = self.splitter.sizes()
        if len(sizes) == 2 and sizes[1] < 140:
            total = sum(sizes)
            self.splitter.setSizes([max(240, int(total * 0.6)), int(total * 0.4)])

    def closeEvent(self, event) -> None:
        busy = [
            tab for tab in (self.download_hub_tab, self.tags_tab, self.cue_tab,
                            self.duplicates_tab, self.update_playlist_tab,
                            self.playlist_search_tab)
            if tab.is_busy()
        ]
        if busy:
            answer = QMessageBox.question(
                self, "Операция выполняется",
                "Одна из утилит ещё работает. Прервать и закрыть приложение?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        event.accept()
