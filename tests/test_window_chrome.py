"""Exercise the real window controls without touching the running desktop."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]


class WindowChromeTests(unittest.TestCase):
    def test_controls_window_modes_and_desktop_frame(self):
        with tempfile.TemporaryDirectory(prefix="gg-window-chrome-") as temporary:
            env = os.environ.copy()
            env.update(
                QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
                QT_QUICK_CONTROLS_STYLE="Basic", PYTHONDONTWRITEBYTECODE="1",
                GG_DESKTOP_STATE_ROOT=str(Path(temporary) / "state"),
                GG_DESKTOP_DATA_ROOT=str(Path(temporary) / "data"),
            )
            code = r'''
from pathlib import Path
from PySide6.QtCore import QPoint, QPointF, QUrl, Qt
from PySide6.QtGui import QWindow
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import delete
from backend.desktop_shell import apply_desktop_shell_window

app = QApplication([])
app.setQuitOnLastWindowClosed(False)
engine = QQmlApplicationEngine()
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
engine.load(QUrl.fromLocalFile(str(Path('qml/Main.qml').resolve())))
assert engine.rootObjects(), 'Main window failed to load'
window = engine.rootObjects()[0]
window.setProperty('shellLoading', False)
app.processEvents()

def item(name):
    found = window.findChild(QQuickItem, name)
    assert found is not None, name + ' missing'
    return found

def click(name):
    button = item(name)
    center = button.mapToScene(QPointF(button.width() / 2, button.height() / 2))
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, center.toPoint())
    QTest.qWait(30)

def visual_items(parent):
    for child in parent.childItems():
        yield child
        yield from visual_items(child)

assert window.flags() & Qt.FramelessWindowHint, 'Native title bar is visible'
assert window.visibility() == QWindow.Maximized
plate = item('windowControlsPlate')
assert 0 <= plate.y() < 12, 'Controls left the frame legend line'
assert plate.x() + plate.width() < window.width(), 'Controls extend outside the window'
click('windowMaximizeButton')
assert window.visibility() == QWindow.Windowed, 'Restore click was intercepted'
handles = [child for child in visual_items(window.contentItem())
           if child.objectName().startswith('windowResize_')]
assert len(handles) == 8 and all(h.property('enabled') for h in handles)
assert all(h.width() > 0 and h.height() > 0 for h in handles)
assert window.minimumWidth() == 820 and window.minimumHeight() == 620

drag = item('windowTitleDragArea')
point = drag.mapToScene(QPointF(350, drag.height() / 2)).toPoint()
mode_changes = QSignalSpy(drag.parentItem().windowModeChangeRequested)
QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, point)
QTest.mouseMove(window, point + QPoint(60, 0), 10)
QTest.mouseMove(window, point + QPoint(90, 0), 10)
QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, point + QPoint(90, 0))
assert mode_changes.count() == 1, 'Title drag did not start a system move'
corner = handles[0].mapToScene(QPointF(3, 3)).toPoint()
QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, corner)
QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, corner)
assert mode_changes.count() == 2, 'Corner press did not start a system resize'
QTest.mouseDClick(window, Qt.LeftButton, Qt.NoModifier, point)
QTest.qWait(30)
assert window.visibility() == QWindow.Maximized, 'Title double click did not maximize'
assert not any(h.property('enabled') for h in handles), 'Resize handles active while maximized'

click('windowMinimizeButton')
assert window.visibility() == QWindow.Minimized, 'Minimize click was intercepted'
window.showMaximized()
window.toggleAppFullscreen()
app.processEvents()
assert window.visibility() == QWindow.FullScreen
click('windowMaximizeButton')
assert not window.property('appFullscreen')
assert window.visibility() == QWindow.Maximized
assert window.flags() & Qt.FramelessWindowHint

window.setProperty('desktopShell', True)
apply_desktop_shell_window(window, True)
assert window.flags() & Qt.WindowStaysOnBottomHint
assert window.flags() & Qt.FramelessWindowHint
app.processEvents()
assert not any(h.property('enabled') for h in handles), 'Desktop shell must keep fixed screen geometry'
click('windowMaximizeButton')
apply_desktop_shell_window(window, False)
assert not window.property('desktopShell')
assert window.flags() & Qt.FramelessWindowHint, 'Desktop shell restored the native title bar'
assert not window.flags() & Qt.WindowStaysOnBottomHint
assert window.visibility() == QWindow.Maximized

window.showNormal()
window.resize(820, 620)
app.processEvents()
assert plate.x() > drag.x() and plate.x() + plate.width() < window.width()
click('windowCloseButton')
assert not window.isVisible(), 'Close click was intercepted'
faults = [message for message in warnings if 'GgWindowChrome.qml' in message
          or any(marker in message for marker in
                 ('ReferenceError:', 'TypeError:', 'is not a type', 'Cannot assign'))]
assert not faults, '\n'.join(faults)
delete(engine)
print('WINDOW_CHROME_TEST=PASS')
'''
            result = subprocess.run(
                [sys.executable, "-X", "utf8", "-B", "-c", code],
                cwd=PROJECT, env=env, capture_output=True, text=True,
                encoding="utf-8", timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("WINDOW_CHROME_TEST=PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
