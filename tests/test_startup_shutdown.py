"""A closed desktop must release its process even when cleanup gets stuck."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[1]


class DesktopShutdownTests(unittest.TestCase):
    def run_desktop(self, scenario: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory(prefix="gg-shutdown-test-") as temporary:
            env = os.environ.copy()
            env.update(
                QT_QPA_PLATFORM="offscreen",
                QT_QUICK_BACKEND="software",
                QT_QUICK_CONTROLS_STYLE="Basic",
                PYTHONDONTWRITEBYTECODE="1",
                GG_DATA_HOME=str(Path(temporary) / "data"),
                GG_USER_HOME=str(Path(temporary) / "user"),
                GG_DESKTOP_STATE_ROOT=str(Path(temporary) / "state"),
                GG_DESKTOP_DATA_ROOT=str(Path(temporary) / "data"),
                GG_USER_CODEX_HOME=str(Path(temporary) / "codex"),
                CODEX_HOME=str(Path(temporary) / "codex"),
            )
            code = r'''
import sys, threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from PySide6.QtWidgets import QApplication
from startup import install_shutdown_guard, run_event_loop

app = QApplication([])
engine = QQmlApplicationEngine()
engine.loadData(b"""import QtQuick
Window {
    visible: true; width: 100; height: 100
    property bool rejectClose: false
    onClosing: function(close) { close.accepted = !rejectClose }
}""", QUrl.fromLocalFile(str(Path('tests/shutdown-fixture.qml').resolve())))
assert engine.rootObjects(), 'test window missing'
window = engine.rootObjects()[0]
mode = sys.argv[1]
guard = install_shutdown_guard(app, window, timeout_s=.7)
assert install_shutdown_guard(app, window) is guard
if mode == 'quit-handler':
    app.aboutToQuit.connect(lambda: threading.Event().wait(60))
elif mode == 'executor':
    ready = threading.Event()
    pool = ThreadPoolExecutor(max_workers=1)
    def work():
        ready.set()
        threading.Event().wait(60)
    pool.submit(work)
    assert ready.wait(2)
    app.aboutToQuit.connect(lambda: pool.shutdown(wait=False, cancel_futures=True))
elif mode == 'tool-window':
    tool = QQuickWindow()
    tool.show()
elif mode == 'minimize':
    window.showMinimized()
    QTimer.singleShot(1000, lambda: print('MINIMIZE_SURVIVED', flush=True))
elif mode == 'hide':
    window.hide()
    def show_again():
        print('HIDE_SURVIVED', flush=True)
        window.show()
    QTimer.singleShot(1000, show_again)
elif mode == 'reject-close':
    window.setProperty('rejectClose', True)
    QTimer.singleShot(10, window.close)
    def accept_close():
        print('REJECTED_CLOSE_SURVIVED', flush=True)
        window.setProperty('rejectClose', False)
        window.close()
    QTimer.singleShot(1000, accept_close)

if mode != 'reject-close':
    QTimer.singleShot(1200 if mode in ('minimize', 'hide') else 10, window.close)
result = run_event_loop(app, engine)
print('QML_RELEASED', flush=True)
raise SystemExit(result)
'''
            return subprocess.run(
                [sys.executable, "-X", "utf8", "-B", "-c", code, scenario],
                cwd=PROJECT, env=env, capture_output=True, text=True,
                encoding="utf-8", timeout=8,
            )

    def test_normal_close_releases_qml_and_exits_cleanly(self):
        result = self.run_desktop("normal")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("QML_RELEASED", result.stdout)
        self.assertNotIn("shutdown timed out", result.stderr)

    def test_blocked_qt_cleanup_cannot_keep_a_hidden_desktop_alive(self):
        result = self.run_desktop("quit-handler")
        self.assertEqual(result.returncode, 70, result.stdout + result.stderr)
        self.assertIn("shutdown timed out", result.stderr)

    def test_running_executor_cannot_retain_process_after_qml_release(self):
        result = self.run_desktop("executor")
        self.assertEqual(result.returncode, 70, result.stdout + result.stderr)
        self.assertIn("QML_RELEASED", result.stdout)
        self.assertIn("shutdown timed out", result.stderr)

    def test_main_close_exits_with_a_secondary_window_still_open(self):
        result = self.run_desktop("tool-window")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("QML_RELEASED", result.stdout)

    def test_minimize_does_not_arm_the_shutdown_deadline(self):
        result = self.run_desktop("minimize")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("MINIMIZE_SURVIVED", result.stdout)

    def test_rejected_close_does_not_arm_the_shutdown_deadline(self):
        result = self.run_desktop("reject-close")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("REJECTED_CLOSE_SURVIVED", result.stdout)

    def test_hide_alone_does_not_arm_the_shutdown_deadline(self):
        result = self.run_desktop("hide")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("HIDE_SURVIVED", result.stdout)


if __name__ == "__main__":
    unittest.main()
