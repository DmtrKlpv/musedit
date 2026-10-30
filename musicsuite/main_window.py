"""Главное окно приложения со вкладками и общей консолью."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QMessageBox, QSplitter, QTabWidget,
    QVBoxLayout, QWidget,
)

from .appicon import app_icon
from .console import ConsoleView
from . import theme as app_theme
from .tabs import (
    CueTab, DownloadHubTab, DuplicatesTab, PlaylistSearchTab, TagsTab,
    UpdatePlaylistTab,
)

from .version import APP_TITLE, APP_VERSION, ORGANIZATION  # noqa: E402
COLOR_LINK = "#5b21b6"
COLOR_PRIMARY = "#2563eb"
COLOR_PRIMARY_HOVER = "#1d4ed8"
COLOR_PRIMARY_DISABLED = "#93c5fd"

# Таблица стилей больше не константа: она собирается из системной
# палитры в musicsuite.theme.build_stylesheet(), поэтому подписи
# остаются читаемыми и в светлой, и в тёмной теме Windows.



class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        # Стили собираются из системной палитры. Палитру и стиль виджетов
        # не трогаем — приложение следует за темой Windows.
        app_theme.apply_theme(QApplication.instance())

        # При смене темы на лету перекрашиваем таблицы вкладок: цвета строк
        # задаются объектами QColor, а не через QSS, поэтому сами не обновятся.
        app_theme.theme_signals.changed.connect(self._on_theme_changed)

        self.setWindowTitle(APP_TITLE)

        # Иконка в заголовке задаётся отдельно от .ico в EXE: Qt рисует
        # рамку сам и ресурсы исполняемого файла не читает.
        icon = app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)

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
    def _on_theme_changed(self) -> None:
        """Перекрашивает строки таблиц после смены системной темы."""
        for tab in (self.download_hub_tab, self.update_playlist_tab,
                    self.playlist_search_tab, self.tags_tab,
                    self.cue_tab, self.duplicates_tab):
            refresh = getattr(tab, "refresh_theme", None)
            if callable(refresh):
                try:
                    refresh()
                except Exception:  # noqa: BLE001 — тема не должна ломать окно
                    pass

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
            f"<b>{APP_TITLE}</b><br><br>"
            "Единая панель для пяти инструментов:<br>"
            ""
            "• скачивание треков из Яндекс.Музыки с готовым плейлистом;<br>"
            ""
            "• исправление кодировки тегов MP3;<br>"
            "• конвертация FLAC/APE + CUE в MP3;<br>"
            "• поиск дубликатов с удалением в Корзину.<br><br>"
            f"Все тяжёлые операции выполняются в фоновых потоках.<br><br>"
            f"{ORGANIZATION}"
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
