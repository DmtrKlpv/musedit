"""Базовый класс вкладки: запуск задачи в потоке, прогресс, блокировка, статус."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout, QLabel, QMessageBox, QVBoxLayout, QWidget,
)

from ..widgets import ProgressPanel
from ..workers import TaskWorker


class BaseTab(QWidget):
    """Общая обвязка для всех вкладок-утилит."""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self._worker = None
        self.progress_panel: ProgressPanel | None = None

    # ------------------------------------------------------------------
    # Построение форм
    # ------------------------------------------------------------------
    @staticmethod
    def make_form() -> QFormLayout:
        form = QFormLayout()
        form.setLabelAlignment(form.labelAlignment())
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        return form

    def make_hint(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet("color:#6b7280; font-size:8pt;")
        return label

    def add_progress(self, layout: QVBoxLayout) -> ProgressPanel:
        """Создаёт полосу прогресса внизу вкладки и запоминает её."""
        self.progress_panel = ProgressPanel(self)
        layout.addWidget(self.progress_panel)
        return self.progress_panel

    # ------------------------------------------------------------------
    # Запуск задач
    # ------------------------------------------------------------------
    def start_task(self, func, controls, on_success=None,
                   busy_text="Выполняется...", use_progress=None,
                   busy_progress: bool = False):
        """Запускает func() в фоновом потоке.

        controls — виджеты, блокируемые на время работы.

        use_progress: None — определить автоматически по сигнатуре func
        (TaskWorker._accepts_progress). Явное True/False нужно редко: раньше
        здесь стояло True по умолчанию, из-за чего лямбда без параметров
        падала с «takes 0 positional arguments but 1 was given».
        """
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(
                self, "Подождите", "Текущая операция ещё выполняется."
            )
            return False

        for widget in controls:
            if widget is not None:
                widget.setEnabled(False)

        panel = self.progress_panel
        if panel is not None:
            if busy_progress:
                panel.set_busy(busy_text)
            else:
                panel.bar.setRange(0, 100)
                panel.bar.setValue(0)
                panel.set_text(busy_text)
                panel.counter_label.setText("")

        def restore():
            for widget in controls:
                if widget is not None:
                    widget.setEnabled(True)

        worker = TaskWorker(func, self, with_progress=use_progress)
        self._worker = worker

        def handle_progress(done, total, text):
            if panel is not None:
                panel.set_progress(done, total, text)

        def handle_success(result):
            restore()
            if panel is not None:
                # Полосу не трогаем: её уже довёл до 100% сам движок через
                # finish(). Раньше здесь шёл set_progress(1, 1), и полоса
                # на мгновение откатывалась в начало шкалы.
                panel.finish(self._success_text(result))
            if on_success is not None:
                on_success(result)

        def handle_failure(message):
            restore()
            if panel is not None:
                panel.bar.setRange(0, 100)
                panel.set_text("Ошибка выполнения")
            print(f"\n[ОШИБКА] {message}\n")
            QMessageBox.critical(self, "Ошибка выполнения", message)

        worker.progressed.connect(handle_progress)
        worker.succeeded.connect(handle_success)
        worker.failed.connect(handle_failure)
        worker.finished.connect(lambda: setattr(self, "_worker", None))
        worker.start()
        return True

    @staticmethod
    def _success_text(result) -> str:
        if isinstance(result, str) and result:
            return "Готово"
        return "Готово"

    def is_busy(self) -> bool:
        return self._worker is not None and self._worker.isRunning()
