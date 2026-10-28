"""Вкладка «Яндекс.Музыка и плейлисты»: три утилиты в одном месте.

Объединяет три панели, которые раньше были отдельными вкладками:

  * экспорт плейлиста из HTML/iframe (движок plsgen);
  * скачивание треков по TXT-списку (движок yamd);
  * создание плейлистов из папки или TXT-списка (движок plscreate).

Панели — это те же классы вкладок, что были раньше, поэтому логика,
поля и фоновые задачи не менялись: изменилась только навигация.
Переключение идёт через сегментированный переключатель сверху — он
компактнее вложенных вкладок и не плодит второй ряд заголовков.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QHBoxLayout, QPushButton, QStackedWidget, QVBoxLayout,
)

from .base import BaseTab
from .download_tab import DownloadTab
from .export_tab import ExportTab
from .playlist_tab import PlaylistTab

# Порядок режимов совпадает с прежним порядком вкладок, чтобы пользователь
# не переучивался: экспорт → скачивание → создание плейлистов.
MODE_EXPORT = 0
MODE_DOWNLOAD = 1
MODE_PLAYLIST = 2

MODES = (
    (MODE_EXPORT, "Экспорт из Яндекс.Музыки"),
    (MODE_DOWNLOAD, "Скачивание из Яндекс.Музыки"),
    (MODE_PLAYLIST, "Создание плейлистов"),
)


class MusicHubTab(BaseTab):
    TITLE = "Яндекс.Музыка и плейлисты"

    def __init__(self, main_window, parent=None):
        super().__init__(main_window, parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        layout.addLayout(self._build_switch())

        # ---- стек панелей ----
        self.stack = QStackedWidget(self)

        self.export_panel = ExportTab(main_window, self)
        self.download_panel = DownloadTab(main_window, self)
        self.playlist_panel = PlaylistTab(main_window, self)

        self.stack.addWidget(self.export_panel)
        self.stack.addWidget(self.download_panel)
        self.stack.addWidget(self.playlist_panel)

        layout.addWidget(self.stack, 1)

        self.set_mode(MODE_EXPORT)

    # ------------------------------------------------------------------
    def _build_switch(self) -> QHBoxLayout:
        """Сегментированный переключатель режимов."""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        self._buttons = QButtonGroup(self)
        self._buttons.setExclusive(True)

        for position, (index, label) in enumerate(MODES):
            button = QPushButton(label, self)
            button.setObjectName("modeSwitch")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setMinimumHeight(32)
            button.clicked.connect(lambda _checked, i=index: self.set_mode(i))

            # Крайние кнопки скругляем только с внешней стороны — так ряд
            # читается как единый сегментированный контрол.
            if position == 0:
                button.setProperty("segment", "first")
            elif position == len(MODES) - 1:
                button.setProperty("segment", "last")
            else:
                button.setProperty("segment", "middle")

            self._buttons.addButton(button, index)
            row.addWidget(button)

        row.addStretch(1)
        return row

    # ------------------------------------------------------------------
    def set_mode(self, index: int) -> None:
        """Переключает активную панель. Вызывается кнопками и из тестов."""
        if self.stack.count() == 0:
            return
        index = max(0, min(index, self.stack.count() - 1))
        self.stack.setCurrentIndex(index)
        button = self._buttons.button(index)
        if button is not None:
            button.setChecked(True)

    def current_mode(self) -> int:
        return self.stack.currentIndex()

    def active_panel(self) -> BaseTab:
        return self.stack.currentWidget()

    def panels(self) -> tuple:
        return (self.export_panel, self.download_panel, self.playlist_panel)

    # ------------------------------------------------------------------
    @property
    def run_btn(self) -> QPushButton:
        """Кнопка запуска активной панели (для кода, ждущего одну кнопку)."""
        return getattr(self.stack.currentWidget(), "run_btn", None)

    def mark_primary_buttons(self) -> None:
        """Красит кнопку запуска в каждой панели.

        Все три кнопки акцентные намеренно: переключатель меняет содержимое
        мгновенно, и синяя кнопка должна быть на виду в любом режиме.
        """
        for panel in self.panels():
            button = getattr(panel, "run_btn", None)
            if button is None:
                continue
            button.setObjectName("primary")
            # Qt не перерисовывает виджет после смены objectName —
            # стиль нужно применить заново.
            button.style().unpolish(button)
            button.style().polish(button)

    def is_busy(self) -> bool:
        """Занят ли хоть один режим.

        Нужно главному окну при закрытии: если идёт скачивание в скрытой
        панели, приложение не должно закрыться молча.
        """
        return any(panel.is_busy() for panel in self.panels())
