"""Smoke-тест GUI: создание окна, все вкладки, консоль, потоки, дубликаты."""

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "/home/user/music_suite")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from musicsuite.main_window import MainWindow


def pump(ms=300):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


app = QApplication([])
_real_stdout = sys.stdout
_real_stderr = sys.stderr
win = MainWindow()
win.show()
pump(200)

# консоль перехватила вывод — возвращаем тесту собственные потоки
sys.stdout = _real_stdout
sys.stderr = _real_stderr

print("Заголовок окна:", win.windowTitle())
print("Вкладок:", win.tabs.count())
for i in range(win.tabs.count()):
    print(f"  {i + 1}. {win.tabs.tabText(i)}")

# --- консоль: прогресс-бар через перехваченный поток, как в yamd ---
from musicsuite.console import StreamRedirector

stream = StreamRedirector(win.console.emitter)
stream.write("Трек 1 ")
stream.write("\rТрек 1 ЗАГРУЗКА | 10%")
stream.write("\rТрек 1 ЗАГРУЗКА | 99%")
stream.write("\rТрек 1 OK\n")
pump(150)
stream.write("[+] Трек 2 сохранён\n")
pump(150)
text = win.console.editor.toPlainText()
print("\n--- Консоль после прогресса ---")
print(text.strip() or "(пусто)")
assert "10%" not in text and "99%" not in text, "прогресс-строки попали в консоль"
assert "Трек 2 сохранён" in text, "информационная строка не отобразилась"
print("OK: прогресс скрыт, информационные строки видны")
