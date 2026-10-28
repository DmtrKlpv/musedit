"""Точка входа приложения «Музыкальные утилиты»."""

import os
import sys


def _prepare_environment() -> None:
    """Корректная работа путей при запуске из PyInstaller (onefile/onedir)."""
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir)


def main() -> int:
    _prepare_environment()

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QMessageBox

    from musicsuite.main_window import STYLE_SHEET, MainWindow

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Музыкальные утилиты")
    app.setOrganizationName("MusicTools")

    if sys.platform == "win32":
        app.setFont(QFont("Segoe UI", 9))

    app.setStyleSheet(STYLE_SHEET)

    try:
        window = MainWindow()
    except Exception as exc:  # noqa: BLE001 — показываем ошибку вместо падения
        QMessageBox.critical(
            None, "Ошибка запуска",
            f"Не удалось создать главное окно:\n{exc}\n\n"
            "Проверьте, что установлены зависимости: pip install -r requirements.txt"
        )
        return 1

    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
