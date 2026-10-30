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

    from musicsuite.appicon import app_icon
    from musicsuite.main_window import MainWindow
    from musicsuite.theme import apply_theme
    from musicsuite.version import APP_NAME, APP_VERSION, ORGANIZATION

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName(f"{APP_NAME} {APP_VERSION}")
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(ORGANIZATION)

    # Иконка нужна и QApplication, и главному окну: первая даёт значок
    # всем диалогам, второе — рамке окна и Alt+Tab.
    icon = app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)

    if sys.platform == "win32":
        app.setFont(QFont("Segoe UI", 9))

    # Стили собираются из системной палитры: приложение следует за темой
    # Windows, но не полагается на её цвета для фонов — иначе на Win11
    # с тёмной темой получался белый текст на светлом фоне.
    apply_theme(app)

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
