"""Проверка вкладок и консоли в offscreen-режиме."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from musicsuite.console import ConsoleView
from musicsuite.tabs import (
    CueTab, DownloadHubTab, DuplicatesTab, TagsTab, UpdatePlaylistTab,
)


class FakeWindow:
    def show_console(self):
        pass


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    window = FakeWindow()

    for cls in (DownloadHubTab, UpdatePlaylistTab, TagsTab, CueTab, DuplicatesTab):
        tab = cls(window)
        assert tab.progress_panel is not None, f"{cls.__name__}: нет прогресс-бара"
        assert tab.progress_panel.bar is not None
        print(f"[OK] {cls.__name__} — вкладка и прогресс-бар созданы")

    console = ConsoleView()

    # Фильтр: служебный шум не должен попадать в консоль
    console.feed("[INFO] Найдено треков: 10\n")
    console.feed("track_01.mp3  45%|####      | 10/100\n")
    console.feed("[ОШИБКА] Файл не найден\n")
    text = console.editor.toPlainText()
    assert "[INFO]" in text, text
    assert "[ОШИБКА]" in text, text
    assert "####" not in text, text
    print("[OK] консоль отбрасывает прогресс-строки")

    # Режим «всё»
    console.clear()
    console.set_show_all(True)
    console.feed("track_01.mp3  45%|####      | 10/100\n")
    assert "####" in console.editor.toPlainText()
    print("[OK] режим «Все сообщения» показывает полный поток")

    print("\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")


if __name__ == "__main__":
    main()
