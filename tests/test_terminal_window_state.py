"""Window resizing retains the live chat instead of replaying its PTY."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
_TEST_STATE = tempfile.TemporaryDirectory(prefix="gg-window-mode-test-")
os.environ["GG_DESKTOP_STATE_ROOT"] = str(Path(_TEST_STATE.name) / "state")
os.environ["GG_DESKTOP_DATA_ROOT"] = str(Path(_TEST_STATE.name) / "data")
os.environ["GG_USER_CODEX_HOME"] = str(Path(_TEST_STATE.name) / "codex")
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from PySide6.QtCore import QMetaObject, QUrl
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtWidgets import QApplication

from backend.chat_surface_host import ChatSurfaceHost, _terminal_process
from backend.terminal_grid import TerminalGrid


class WindowModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        if os.name == "nt":
            fonts = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts"
            for name in ("consola.ttf", "consolab.ttf", "consolai.ttf", "consolaz.ttf"):
                QFontDatabase.addApplicationFont(str(fonts / name))
            QFont.insertSubstitution("monospace", "Consolas")
            cls.app.setFont(QFont("Consolas"))

    def pump(self, duration=0.1):
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)

    def wait_until(self, condition):
        deadline = time.monotonic() + 10
        while not condition() and time.monotonic() < deadline:
            self.pump(0.01)
        self.assertTrue(condition(), "Live chat did not reach expected state")

    @staticmethod
    def text(grid):
        snap = grid._snap or {}
        rows = list(snap.get("history") or []) + list(snap.get("buf") or [])
        return "\n".join("".join(cell[0] for cell in row) for row in rows)

    def test_temporary_scene_detach_does_not_stop_live_text_reader(self):
        window = QQuickWindow()
        pane = QQuickItem(window.contentItem())
        pane.setWidth(720)
        pane.setHeight(384)
        grid = TerminalGrid(pane)
        worker = grid._thread
        try:
            grid.feed_bytes(b"BEFORE SCENE CHANGE\r\n")
            self.wait_until(lambda: not grid.output_pending())
            pane.setParentItem(None)
            pane.setParentItem(window.contentItem())
            self.pump()
            self.assertIs(grid._thread, worker, "Window transition stopped the VT worker")
            self.assertTrue(worker.isRunning())
            grid.feed_bytes(b"AFTER SCENE CHANGE\r\n")
            self.wait_until(lambda: not grid.output_pending())
            self.assertIn("BEFORE SCENE CHANGE", self.text(grid))
            self.assertIn("AFTER SCENE CHANGE", self.text(grid))
        finally:
            grid._ready_emitted = True
            grid._stop_worker()
            grid.setParentItem(None)
            window.close()
            self.app.processEvents()

    def test_ordinary_resize_still_updates_terminal_after_a_mode_transition(self):
        pane = QQuickItem()
        pane.setWidth(720)
        pane.setHeight(480)
        grid = TerminalGrid(pane)
        try:
            self.pump()
            original = (grid._last_cols, grid._last_rows)
            sizes = []
            grid.resized.connect(lambda cols, rows: sizes.append((cols, rows)))
            grid.preserve_window_geometry()
            pane.setWidth(620)
            pane.setHeight(400)
            self.pump(0.5)
            self.assertEqual((grid._last_cols, grid._last_rows), original)
            self.assertEqual(sizes, [])
            self.assertLessEqual(grid.width() * grid.scale(), pane.width())
            self.assertLessEqual(grid.height() * grid.scale(), pane.height())
            self.assertAlmostEqual(grid.y() + grid.height() * grid.scale(), pane.height())
            # A later manual resize is a different action: it can change the
            # text layout normally instead of permanently pinning the grid.
            pane.setWidth(900)
            self.pump()
            self.assertTrue(sizes)
            self.assertNotEqual((grid._last_cols, grid._last_rows), original)
            self.assertEqual(grid.scale(), 1.0)
            self.assertEqual(grid.width(), pane.width())
        finally:
            grid._ready_emitted = True
            grid._stop_worker()
            grid.setParentItem(None)

    def test_fullscreen_keeps_pty_worker_scrollback_and_unsubmitted_input(self):
        self.check_live_chat_window_changes(fullscreen=True)

    def test_native_maximize_restore_and_drag_keep_loaded_chat(self):
        self.check_live_chat_window_changes(fullscreen=False)

    def test_grok_chat_keeps_initial_grid_through_later_pane_resizes(self):
        pane = QQuickItem()
        pane.setWidth(720)
        pane.setHeight(480)
        host = ChatSurfaceHost()
        starts = []
        try:
            with patch.object(host, "_tui_hole", return_value=pane), \
                 patch.object(host, "_defer_initial_tui", return_value=False), \
                 patch.object(host, "_on_native_tui_ready", side_effect=lambda: starts.append(
                     (host._tui_grid._last_cols, host._tui_grid._last_rows))):
                host._ensure_tui_grid()
                grid = host._tui_grid
                self.wait_until(lambda: bool(starts))
                dimensions = starts[0]
                sizes = []
                grid.resized.connect(lambda cols, rows: sizes.append((cols, rows)))
                grid.feed_bytes("GROK saved chat: åäö\r\n".encode())
                self.wait_until(lambda: not grid.output_pending())
                transcript = self.text(grid)
                # The old transition guard expired after 350 ms. Later drags
                # and pane changes must still keep this session's layout.
                self.pump(0.4)
                for width, height in ((940, 600), (620, 400), (720, 480)):
                    pane.setWidth(width)
                    pane.setHeight(height)
                    host._ensure_tui_grid()
                    self.pump()
                    self.assertIs(host._tui_grid, grid)
                    self.assertEqual((grid._last_cols, grid._last_rows), dimensions)
                    self.assertEqual(self.text(grid), transcript)
                    self.assertLessEqual(grid.width() * grid.scale(), width)
                    self.assertLessEqual(grid.height() * grid.scale(), height)
                self.assertEqual(starts, [dimensions])
                self.assertEqual(sizes, [])
        finally:
            host.shutdown()

    def check_live_chat_window_changes(self, *, fullscreen):
        engine = QQmlEngine()
        component = QQmlComponent(engine, QUrl.fromLocalFile(str(PROJECT / "qml/Main.qml")))
        window = component.create()
        self.assertIsNotNone(window, [error.toString() for error in component.errors()])
        host = ChatSurfaceHost()
        host._gpt_session_id = ""
        host._qml_root = window
        window.setProperty("engineTarget", "GPT_TUI")
        window.setProperty("shellLoading", False)
        window.setProperty("surfaceHost", host)
        window.showNormal()
        window.resize(1280, 800)
        directory = Path(_TEST_STATE.name)
        child = directory / "live_chat.py"
        child.write_text(
            "import sys\n"
            "for n in range(100): print('HISTORY '+str(n),flush=True)\n"
            "print('LIVE CHAT READY',flush=True)\n"
            "for line in sys.stdin: print('INPUT:'+line.strip(),flush=True)\n", encoding="utf-8")
        launched = []

        def launch(argv, master, slave, env, cols=72, rows=36):
            if "--no-alt-screen" in argv:
                argv = [sys.executable, "-u", str(child)]
                launched.append(tuple(argv))
            return _terminal_process(argv, master, slave, env, cols, rows)

        try:
            with patch("backend.platform_support.windows_codex_binary", return_value=sys.executable), \
                 patch("backend.chat_surface_host.shutil.which", return_value=sys.executable), \
                 patch.object(host, "_ensure_gpt_codex_home", return_value=True), \
                 patch.object(host, "_gptui_developer_instructions", return_value="offline fixture"), \
                 patch("backend.chat_surface_host.start_codex_image_guard", side_effect=RuntimeError("offline fixture")), \
                 patch("backend.chat_surface_host._terminal_process", side_effect=launch):
                host._attach_gpt_tui()
                self.wait_until(lambda: host._gpt_grid is not None and "LIVE CHAT READY" in self.text(host._gpt_grid))
                grid = host._gpt_grid
                self.wait_until(lambda: not grid.output_pending())
                process = host._sessions["ws.tui.gpt"]["proc"]
                worker = grid._thread
                dimensions = (grid._last_cols, grid._last_rows)
                history = len(grid._snap["history"])
                self.assertGreater(history, 0)
                sizes = []
                grid.resized.connect(lambda cols, rows: sizes.append((cols, rows)))
                host.writeChatTerminal("ws.tui.gpt", "unfinished draft")
                self.wait_until(lambda: "unfinished draft" in self.text(grid) and not grid.output_pending())
                transcript = self.text(grid)
                grid.scrollToOffset(12)
                offset = grid._view_offset
                self.assertGreater(offset, 0)
                for maximized, width, height in ((True, 1700, 1000), (False, 1280, 800),
                                                 (True, 1700, 1000), (False, 1180, 760),
                                                 (False, 1480, 900), (False, 1280, 800)):
                    if fullscreen:
                        if maximized != bool(window.property("appFullscreen")):
                            self.assertTrue(QMetaObject.invokeMethod(window, "toggleAppFullscreen"))
                        self.assertEqual(window.property("appFullscreen"), maximized)
                    elif maximized:
                        # The Windows titlebar button bypasses GG's own
                        # toggleAppFullscreen handler entirely.
                        window.showMaximized()
                    else:
                        window.showNormal()
                    # Offscreen Qt has no real monitor; supply the geometry
                    # that the window manager/resize drag supplies instead.
                    window.resize(width, height)
                    self.pump(0.5)
                    self.assertIs(host._gpt_grid, grid)
                    self.assertIs(grid._thread, worker)
                    self.assertTrue(worker.isRunning())
                    self.assertIs(host._sessions["ws.tui.gpt"]["proc"], process)
                    self.assertEqual((grid._last_cols, grid._last_rows), dimensions)
                    self.assertEqual(len(grid._snap["history"]), history)
                    self.assertEqual(self.text(grid), transcript)
                    self.assertEqual(grid._view_offset, offset)
                    self.assertIn("HISTORY 0", self.text(grid))
                    self.assertIn("LIVE CHAT READY", self.text(grid))
                    pane = grid.parentItem()
                    available_width = pane.width() - float(pane.property("terminalRightInset") or 0)
                    self.assertLessEqual(grid.width() * grid.scale(), available_width + 0.01)
                    self.assertLessEqual(grid.height() * grid.scale(), pane.height() + 0.01)
                self.assertEqual(sizes, [], "Window resizing makes the CLI replay history")
                self.assertEqual(len(launched), 1)
                self.assertIsNone(process.poll())
                host.writeChatTerminal("ws.tui.gpt", "\n")
                self.wait_until(lambda: "INPUT:unfinished draft" in self.text(grid))
        finally:
            host.shutdown()
            window.close()
            window.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
