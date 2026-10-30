"""Тема приложения строится на системной палитре.

Принцип: приложение НЕ навязывает свою тему. Берём палитру, которую даёт
операционная система (светлую или тёмную), и генерируем из неё таблицу
стилей. Стиль виджетов тоже остаётся системным — Fusion не включается,
палитра не подменяется.

Почему это было нужно
---------------------
Раньше в QSS были жёстко прописаны светлые фоны (#f6f7f9, #ffffff), а цвет
текста у QLabel брался из системной палитры. На Windows 11 с тёмной темой
палитра отдаёт белый WindowText — получался белый текст на светлом фоне,
подписи пропадали. На Windows 10 со светлой темой совпадало случайно.

Теперь и фон, и текст берутся из одной палитры, поэтому контраст сохраняется
при любой системной теме. При переключении темы на лету стили пересобираются
по сигналу QStyleHints.colorSchemeChanged.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication


# ---------------------------------------------------------------------------
# Сигнал смены темы: таблицы перекрашивают строки, не пересобирая содержимое
# ---------------------------------------------------------------------------

class ThemeSignals(QObject):
    changed = Signal()


theme_signals = ThemeSignals()


# ---------------------------------------------------------------------------
# Вспомогательные функции цвета
# ---------------------------------------------------------------------------

def _luminance(color: QColor) -> float:
    """Относительная яркость по WCAG: 0 (чёрный) … 1 (белый)."""
    def channel(value: int) -> float:
        srgb = value / 255.0
        return srgb / 12.92 if srgb <= 0.04045 else ((srgb + 0.055) / 1.055) ** 2.4

    return (0.2126 * channel(color.red())
            + 0.7152 * channel(color.green())
            + 0.0722 * channel(color.blue()))


def is_dark_palette(palette: QPalette | None = None) -> bool:
    """Тёмная ли системная тема.

    Ориентируемся на цвет окна: у тёмных тем он тёмный. Если палитра
    недоступна, спрашиваем у Qt предпочитаемую схему.
    """
    if palette is None:
        app = QApplication.instance()
        palette = app.palette() if app is not None else None

    if palette is not None:
        return _luminance(palette.color(QPalette.Window)) < 0.5

    hints = QGuiApplication.styleHints() if QGuiApplication.instance() else None
    if hints is not None:
        try:
            return hints.colorScheme() == Qt.ColorScheme.Dark
        except (AttributeError, RuntimeError):
            pass
    return False


def _blend(foreground: QColor, background: QColor, alpha: float) -> QColor:
    """Смешивает два цвета: alpha=0 → background, alpha=1 → foreground."""
    alpha = max(0.0, min(1.0, alpha))
    return QColor(
        round(foreground.red() * alpha + background.red() * (1 - alpha)),
        round(foreground.green() * alpha + background.green() * (1 - alpha)),
        round(foreground.blue() * alpha + background.blue() * (1 - alpha)),
    )


def _tint(base: QColor, other: QColor, alpha: float) -> QColor:
    """Подмешивает other в base — для пастельных фонов строк."""
    return _blend(other, base, alpha)


# ---------------------------------------------------------------------------
# Набор цветов темы
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Tokens:
    """Цвета, вычисленные из системной палитры."""

    dark: bool

    window: str
    surface: str
    surface_alt: str
    border: str
    border_input: str

    text: str
    text_muted: str
    text_disabled: str

    accent: str
    accent_hover: str
    accent_disabled: str
    accent_text: str

    selection: str
    selection_text: str
    tab_selected_text: str

    row_missing_bg: str
    row_missing_fg: str
    row_new_bg: str
    row_new_fg: str
    row_done_bg: str
    row_done_fg: str
    manual_bg: str
    manual_border: str

    console_bg: str
    console_fg: str
    console_border: str


def _from_light_palette(palette: QPalette) -> Tokens:
    base = palette.color(QPalette.Base)
    window = palette.color(QPalette.Window)
    text = palette.color(QPalette.Text)
    surface = base.name() if base.isValid() else "#ffffff"
    window_hex = window.name() if window.isValid() else "#f6f7f9"
    text_hex = text.name() if text.isValid() else "#1f2430"

    accent = QColor("#2563eb")

    return Tokens(
        dark=False,
        window=window_hex,
        surface=surface,
        surface_alt=_tint(QColor(surface), QColor("#000000"), 0.04).name(),
        border=QColor("#d9dde3").name(),
        border_input=QColor("#cfd4db").name(),
        text=text_hex,
        text_muted=QColor("#5a6472").name(),
        text_disabled=QColor("#9aa1ab").name(),
        accent=accent.name(),
        accent_hover=QColor("#1d4ed8").name(),
        accent_disabled=QColor("#93c5fd").name(),
        accent_text="#ffffff",
        selection=QColor("#e9e4fa").name(),
        selection_text=text_hex,
        tab_selected_text=QColor("#5b21b6").name(),
        row_missing_bg=QColor("#fde2e4").name(),
        row_missing_fg=QColor("#9f1239").name(),
        row_new_bg=QColor("#e3f6e5").name(),
        row_new_fg=QColor("#166534").name(),
        row_done_bg=QColor("#e8f5e9").name(),
        row_done_fg=QColor("#1b5e20").name(),
        manual_bg=QColor("#fff4d6").name(),
        manual_border=QColor("#d9a441").name(),
        console_bg="#111418",
        console_fg="#d6dde5",
        console_border="#2b3138",
    )


def _from_dark_palette(palette: QPalette) -> Tokens:
    base = palette.color(QPalette.Base)
    window = palette.color(QPalette.Window)
    text = palette.color(QPalette.Text)

    surface = base.name() if base.isValid() else "#2b2b2b"
    window_hex = window.name() if window.isValid() else "#202020"
    text_hex = text.name() if text.isValid() else "#e8e8e8"

    surface_q = QColor(surface)
    accent = QColor("#60a5fa")

    return Tokens(
        dark=True,
        window=window_hex,
        surface=surface,
        surface_alt=_tint(surface_q, QColor("#ffffff"), 0.06).name(),
        border=_tint(surface_q, QColor("#ffffff"), 0.18).name(),
        border_input=_tint(surface_q, QColor("#ffffff"), 0.24).name(),
        text=text_hex,
        # Приглушённый текст — светлее фона, но темнее основного
        text_muted=_blend(QColor(text_hex), surface_q, 0.68).name(),
        text_disabled=_blend(QColor(text_hex), surface_q, 0.40).name(),
        accent=accent.name(),
        accent_hover=QColor("#93c5fd").name(),
        accent_disabled=_blend(accent, surface_q, 0.45).name(),
        accent_text=QColor("#0b1220").name(),
        selection=_tint(surface_q, accent, 0.35).name(),
        selection_text=text_hex,
        tab_selected_text=QColor("#c4b5fd").name(),
        # Пастельные фоны строк делаем тёмными оттенками того же тона,
        # чтобы текст оставался контрастным
        row_missing_bg=_tint(surface_q, QColor("#ef4444"), 0.28).name(),
        row_missing_fg=QColor("#fecdd3").name(),
        row_new_bg=_tint(surface_q, QColor("#22c55e"), 0.26).name(),
        row_new_fg=QColor("#bbf7d0").name(),
        row_done_bg=_tint(surface_q, QColor("#22c55e"), 0.20).name(),
        row_done_fg=QColor("#d9fbe3").name(),
        manual_bg=_tint(surface_q, QColor("#f59e0b"), 0.28).name(),
        manual_border=QColor("#fbbf24").name(),
        console_bg=_tint(window, QColor("#000000"), 0.55).name(),
        console_fg=QColor("#d6dde5").name(),
        console_border=_tint(surface_q, QColor("#ffffff"), 0.20).name(),
    )


def tokens(palette: QPalette | None = None) -> Tokens:
    """Цвета текущей системной темы."""
    app = QApplication.instance()
    if palette is None and app is not None:
        palette = app.palette()

    if palette is None:
        palette = QPalette()

    return _from_dark_palette(palette) if is_dark_palette(palette) \
        else _from_light_palette(palette)


# ---------------------------------------------------------------------------
# Таблица стилей
# ---------------------------------------------------------------------------

def build_stylesheet(t: Tokens | None = None) -> str:
    """Собирает QSS из системных цветов.

    Все цвета подставляются из Tokens, ни один не зашит в шаблон: иначе
    при тёмной теме снова получилось бы светлое на светлом.
    """
    t = t or tokens()

    return f"""
QMainWindow, QDialog {{ background: {t.window}; }}
QWidget {{ color: {t.text}; }}

QTabWidget::pane {{
    border: 1px solid {t.border}; border-radius: 6px;
    background: {t.surface};
}}
QTabBar::tab {{
    padding: 8px 16px; margin-right: 2px; border: 1px solid {t.border};
    border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px;
    background: {t.surface_alt}; color: {t.text};
}}
QTabBar::tab:selected {{
    background: {t.surface}; color: {t.tab_selected_text}; font-weight: 600;
}}
QTabBar::tab:hover {{ background: {t.selection}; }}

QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    padding: 5px 7px; border: 1px solid {t.border_input}; border-radius: 5px;
    background: {t.surface}; color: {t.text};
    selection-background-color: {t.selection}; selection-color: {t.selection_text};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QComboBox:focus, QSpinBox:focus {{ border-color: {t.accent}; }}
QLineEdit:disabled, QPlainTextEdit:disabled, QTextEdit:disabled,
QComboBox:disabled, QSpinBox:disabled {{
    background: {t.surface_alt}; color: {t.text_disabled};
}}

QPushButton {{
    padding: 6px 14px; border: 1px solid {t.border_input}; border-radius: 5px;
    background: {t.surface}; color: {t.text};
}}
QPushButton:hover {{ background: {t.surface_alt}; border-color: {t.accent}; }}
QPushButton:pressed {{ background: {t.selection}; }}
QPushButton:disabled {{ color: {t.text_disabled}; background: {t.surface_alt}; }}
QPushButton#primary {{
    background: {t.accent}; border-color: {t.accent};
    color: {t.accent_text}; font-weight: 600;
}}
QPushButton#primary:hover {{
    background: {t.accent_hover}; border-color: {t.accent_hover};
}}
QPushButton#primary:disabled {{
    background: {t.accent_disabled}; border-color: {t.accent_disabled};
    color: {t.text_muted};
}}
QPushButton#modeSwitch {{
    padding: 6px 18px; border: 1px solid {t.border_input}; border-radius: 0;
    background: {t.surface_alt}; color: {t.text};
}}
QPushButton#modeSwitch:hover {{ background: {t.selection}; }}
QPushButton#modeSwitch:checked {{
    background: {t.surface}; color: {t.tab_selected_text}; font-weight: 600;
    border-bottom: 2px solid {t.accent};
}}
QPushButton#modeSwitch[segment="first"] {{
    border-top-left-radius: 6px; border-bottom-left-radius: 6px;
}}
QPushButton#modeSwitch[segment="last"] {{
    border-top-right-radius: 6px; border-bottom-right-radius: 6px;
}}

QLabel {{ color: {t.text}; background: transparent; }}
QLabel:disabled {{ color: {t.text_disabled}; }}
QLabel[role="hint"] {{ color: {t.text_muted}; font-size: 8pt; }}
QLabel[role="status"] {{ color: {t.text_muted}; }}
QLabel[role="heading"] {{ color: {t.text}; font-weight: 600; }}

QCheckBox, QRadioButton {{ color: {t.text}; background: transparent; }}
QCheckBox:disabled, QRadioButton:disabled {{ color: {t.text_disabled}; }}

QGroupBox {{
    border: 1px solid {t.border}; border-radius: 6px;
    margin-top: 8px; padding-top: 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {t.text};
}}

QMenuBar {{ background: {t.window}; color: {t.text}; }}
QMenuBar::item {{ background: transparent; color: {t.text}; padding: 4px 10px; }}
QMenuBar::item:selected {{ background: {t.selection}; color: {t.selection_text}; }}
QMenu {{
    background: {t.surface}; color: {t.text};
    border: 1px solid {t.border}; padding: 4px;
}}
QMenu::item {{ padding: 5px 22px; color: {t.text}; }}
QMenu::item:selected {{ background: {t.selection}; color: {t.selection_text}; }}
QMenu::separator {{ height: 1px; background: {t.border}; margin: 4px 8px; }}

QToolTip {{
    background: {t.surface}; color: {t.text};
    border: 1px solid {t.border_input}; padding: 4px; border-radius: 4px;
}}

QHeaderView::section {{
    background: {t.surface_alt}; border: none;
    border-bottom: 1px solid {t.border}; padding: 5px; color: {t.text};
}}
QTreeWidget, QTreeView, QListView, QTableWidget, QListWidget {{
    border: 1px solid {t.border}; border-radius: 5px;
    background: {t.surface}; color: {t.text};
    alternate-background-color: {t.surface_alt};
}}
QTreeWidget::item, QTreeView::item, QListView::item,
QTableWidget::item, QListWidget::item {{ color: {t.text}; padding: 2px; }}
QTreeWidget::item:selected, QTreeView::item:selected,
QListView::item:selected, QTableWidget::item:selected,
QListWidget::item:selected {{
    background: {t.selection}; color: {t.selection_text};
}}
QTreeWidget::item:hover, QTreeView::item:hover, QListView::item:hover {{
    background: {t.surface_alt};
}}

QComboBox QAbstractItemView {{
    background: {t.surface}; color: {t.text};
    border: 1px solid {t.border_input};
    selection-background-color: {t.selection};
    selection-color: {t.selection_text}; outline: none;
}}
QComboBox::drop-down {{ border: none; width: 18px; }}

QProgressBar {{
    background: {t.surface_alt}; border: 1px solid {t.border};
    border-radius: 4px; text-align: center; color: {t.text}; height: 18px;
}}
QProgressBar::chunk {{ background: #22c55e; border-radius: 3px; }}
QProgressBar:disabled {{ color: {t.text_disabled}; }}

QSplitter::handle {{ background: {t.border}; }}
QStatusBar {{ background: {t.window}; color: {t.text_muted}; }}
QStatusBar QLabel {{ color: {t.text_muted}; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{
    background: {t.surface_alt}; width: 12px; margin: 0; border: none;
}}
QScrollBar::handle:vertical {{
    background: {t.border_input}; border-radius: 6px; min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: {t.text_disabled}; }}
QScrollBar:horizontal {{
    background: {t.surface_alt}; height: 12px; margin: 0; border: none;
}}
QScrollBar::handle:horizontal {{
    background: {t.border_input}; border-radius: 6px; min-width: 28px;
}}
QScrollBar::handle:horizontal:hover {{ background: {t.text_disabled}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
"""


# ---------------------------------------------------------------------------
# Применение
# ---------------------------------------------------------------------------

def apply_theme(app: QApplication | None = None) -> None:
    """Пересобирает стили под текущую системную тему.

    Стиль виджетов и палитра НЕ меняются — приложение следует за системой.
    При смене темы в Windows вызывается повторно автоматически.
    """
    app = app or QApplication.instance()
    if app is None:
        return

    current = tokens(app.palette())
    app.setStyleSheet(build_stylesheet(current))
    app.setProperty("themeIsDark", current.dark)

    # Один раз подписываемся на смену схемы, чтобы тема подхватывалась
    # без перезапуска приложения.
    if not app.property("themeConnected"):
        hints = QGuiApplication.styleHints()
        if hints is not None and hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(
                lambda _scheme: apply_theme(app)
            )
            app.setProperty("themeConnected", True)

    theme_signals.changed.emit()


def color(role: str, palette: QPalette | None = None) -> QColor:
    """Цвет из текущей темы по имени поля Tokens.

    Нужен там, где цвет задаётся не в QSS, а объектом QColor —
    например, для подсветки строк таблицы.
    """
    current = tokens(palette)
    value = getattr(current, role, None)
    if value is None:
        raise KeyError(f"неизвестная роль цвета: {role}")
    return QColor(value)
