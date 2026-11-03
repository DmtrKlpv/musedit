"""Колонки поиска дубликатов: перемещение, длительность, живой показ групп."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["HOME"] = tempfile.mkdtemp(prefix="home_cols_")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from musicsuite.engines.duplsearch import format_duration

OUT = sys.__stdout__


def ok(label, cond, extra=""):
    OUT.write(f"[{'OK ' if cond else 'FAIL'}] {label}{(' — ' + extra) if extra else ''}\n")
    OUT.flush()
    if not cond:
        raise SystemExit(1)


def pump(ms=100):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


# 1. формат длительности
OUT.write("--- 1. Формат длительности ---\n")
ok("227 с → 3:47", format_duration(227.4) == "3:47", format_duration(227.4))
ok("65 с → 1:05 (секунды с нулём)", format_duration(65) == "1:05")
ok("0 или мусор → N/A", format_duration(0) == "N/A" and format_duration("x") == "N/A")

app = QApplication.instance() or QApplication([])
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
from musicsuite.main_window import MainWindow

window = MainWindow()
window.resize(1400, 900)
window.show()
pump(100)
tab = window.duplicates_tab
window.tabs.setCurrentWidget(tab)
app.processEvents()

# 2. колонки
OUT.write("\n--- 2. Колонки ---\n")
cols = [tab.files_tree.headerItem().text(i) for i in range(tab.files_tree.columnCount())]
OUT.write(f"  {cols}\n")
ok("«Длительность» между «Размер» и «Битрейт»",
   cols.index("Длительность") == cols.index("Размер") + 1
   and cols.index("Битрейт") == cols.index("Длительность") + 1, str(cols))
ok("колонки файлов перемещаются", tab.files_tree.header().sectionsMovable())
ok("колонки групп перемещаются", tab.groups_tree.header().sectionsMovable())

# переставляем колонки и проверяем, что порядок держится
hdr = tab.files_tree.header()
hdr.moveSection(hdr.visualIndex(1), 3)
app.processEvents()
after = [tab.files_tree.headerItem().text(hdr.logicalIndex(v)) for v in range(hdr.count())]
OUT.write(f"  после перестановки: {after}\n")
ok("перестановка применилась", after != cols)

# 3. живой показ групп: во время поиска группы уже видны
OUT.write("\n--- 3. Живой показ ---\n")
tmp = tempfile.mkdtemp(prefix="live_")
root = os.path.join(tmp, "M")
for n in range(4):
    for sub in ("A", "B"):
        d = os.path.join(root, f"{sub}{n}")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"t{n}.mp3"), "wb") as f:
            f.write(b"\xFF\xFB\x90\x64" + bytes([n + 1]) * 3000)

seen = []
orig = tab._append_group
def spy(group, count):
    orig(group, count)
    seen.append(tab.groups_tree.topLevelItemCount())
tab._append_group = spy

tab.dir_field.setText(root)
tab.on_search()
for _ in range(200):
    pump(50)
    if not tab.is_busy():
        break
pump(200)
OUT.write(f"  счётчик групп по мере поступления: {seen}\n")
ok("группы добавлялись по одной", len(seen) == 4 and seen == sorted(seen), str(seen))
ok("итоговый список не потерял группы", tab.groups_tree.topLevelItemCount() == 4)

# 4. длительность в строках
OUT.write("\n--- 4. Длительность в строках ---\n")
tab.groups_tree.setCurrentItem(tab.groups_tree.topLevelItem(0))
app.processEvents()
row = tab.files_tree.topLevelItem(0)
dur = row.text(cols.index("Длительность"))
OUT.write(f"  значение: {dur!r}\n")
ok("в строке длительность в формате м:сс или N/A",
   dur == "N/A" or (":" in dur and dur.replace(":", "").isdigit()), dur)

OUT.write("\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ\n")
