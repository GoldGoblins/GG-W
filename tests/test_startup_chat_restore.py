"""Startup waits for the selected chat's PTY and actual VT worker backlog."""
from __future__ import annotations

import os
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
_HOME = tempfile.TemporaryDirectory(prefix="gg-startup-chat-test-")
os.environ["GG_DESKTOP_STATE_ROOT"] = str(Path(_HOME.name) / "state")
os.environ["GG_DESKTOP_DATA_ROOT"] = str(Path(_HOME.name) / "data")
os.environ["GG_USER_CODEX_HOME"] = str(Path(_HOME.name) / "codex")
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtWidgets import QApplication

from backend.chat_surface_host import ChatSurfaceHost, _STARTUP_CHAT_BLOCK_S
from backend.terminal_grid import TerminalGrid
from backend.chat_restore import normalized_display_text


def application():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
        if os.name == "nt":
            fonts = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts"
            for name in ("consola.ttf", "consolab.ttf", "consolai.ttf", "consolaz.ttf"):
                QFontDatabase.addApplicationFont(str(fonts / name))
            QFont.insertSubstitution("monospace", "Consolas")
            app.setFont(QFont("Consolas"))
    return app


class StartupChatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = application()

    def setUp(self):
        self.host = ChatSurfaceHost()
        self.root = QObject()
        self.root.setProperty("engineTarget", "GPT_TUI")
        self.root.setProperty("shellLoading", True)
        self.host._qml_root = self.root
        self.hole = QQuickItem()
        self.hole.setWidth(720)
        self.hole.setHeight(384)
        self.grid = TerminalGrid(self.hole)
        self.host._gpt_grid = self.grid
        self.drain = QTimer()
        self.drain.setSingleShot(True)
        self.host._sessions["ws.tui.gpt"] = {"drain": self.drain}

    def tearDown(self):
        self.grid._ready_emitted = True
        self.host._startup_chat_timer.stop()
        self.host._sessions.clear()
        self.grid._stop_worker()
        self.host._gpt_grid = None
        self.host.shutdown()
        self.app.processEvents()

    def prepare(self):
        with patch.object(self.host, "_attach_gpt_tui") as gpt, patch.object(
            self.host, "_attach_native_tui"
        ) as grok:
            self.host.prepareStartupChat()
            self.host.prepareStartupChat()
            gpt.assert_called_once_with()
            grok.assert_not_called()
        self.host._startup_chat_checkpoint = ""  # Fresh-chat unit fixture.
        # Poll explicitly with deterministic timestamps in these tests.
        self.host._startup_chat_timer.stop()

    def wait_for_parser(self):
        deadline = time.monotonic() + 8
        while self.grid.output_pending() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertFalse(self.grid.output_pending(), "VT worker did not finish")

    def visible_text(self):
        return "\n".join("".join(cell[0] for cell in row) for row in self.grid._display_rows())

    def test_settings_settle_before_either_default_motor_starts(self):
        with patch.object(self.host, "_tui_hole") as hole:
            self.host._ensure_tui_grid()
            hole.assert_not_called()
        with patch.object(self.host, "_start_gpt_tui") as start:
            self.host._show_gpt_tui()
            start.assert_not_called()
        self.assertTrue(self.host._defer_initial_tui())
        self.prepare()
        self.assertFalse(self.host._defer_initial_tui())

    def test_long_history_waits_for_worker_then_opens_at_tail(self):
        self.prepare()
        self.assertTrue(self.host.startupChatBlocking)
        self.grid._view_offset = 8
        # Queue a real multi-chunk replay without processing GUI snapshots.
        for number in range(60):
            self.grid.feed_bytes(("history %03d " % number + "åäö " * 40 + "\r\n").encode())
        self.grid.feed_bytes("LATEST MESSAGE ✓\r\n› ".encode())
        self.assertTrue(self.grid.output_pending())
        self.host._startup_chat_output_at = time.monotonic() - 2
        self.host._poll_startup_chat()
        self.assertTrue(self.host.startupChatBlocking)
        self.wait_for_parser()
        self.host._poll_startup_chat()
        self.assertFalse(self.host.startupChatRestoring)
        self.assertFalse(self.host.startupChatBlocking)
        self.assertEqual(self.grid._view_offset, 0)
        self.assertIn("LATEST MESSAGE ✓", self.visible_text())

    def test_output_bursts_and_pty_backlog_keep_loading_visible(self):
        self.prepare()
        self.wait_for_parser()
        self.host._startup_chat_output_at = time.monotonic()
        self.host._poll_startup_chat()
        self.assertTrue(self.host.startupChatBlocking)
        self.host._startup_chat_output_at -= 2
        self.drain.start(10000)
        self.host._poll_startup_chat()
        self.assertTrue(self.host.startupChatBlocking)
        self.drain.stop()
        self.grid.feed_bytes("› ".encode())
        self.wait_for_parser()
        self.host._poll_startup_chat()
        self.assertFalse(self.host.startupChatBlocking)

    def test_slow_start_releases_desktop_but_keeps_replay_covered(self):
        self.prepare()
        self.grid.setEnabled(False)
        self.host._startup_chat_since -= _STARTUP_CHAT_BLOCK_S + 1
        self.host._poll_startup_chat()
        self.assertFalse(self.host.startupChatBlocking)
        self.assertTrue(self.host.startupChatRestoring)
        self.assertFalse(self.grid.isEnabled())
        # A login prompt or silent child remains accessible by explicit choice.
        self.host.showStartupChat()
        self.assertFalse(self.host.startupChatRestoring)
        self.assertTrue(self.grid.isEnabled())
        self.assertFalse(self.host._startup_chat_timer.isActive())

    def test_missing_cli_waits_for_its_error_to_be_rendered(self):
        self.prepare()
        self.host._sessions.clear()
        self.grid._ready_emitted = True
        self.grid.feed_bytes(b"Codex could not start\r\n")
        self.host._poll_startup_chat()
        self.assertTrue(self.host.startupChatRestoring)
        self.wait_for_parser()
        self.host._poll_startup_chat()
        self.assertFalse(self.host.startupChatRestoring)

    def test_read_observes_only_selected_terminal_and_pending_parser(self):
        self.prepare()

        class Proc:
            def poll(self):
                return None

        self.host._sessions["ws.tui.gpt"].update(master=123, proc=Proc())
        with patch("backend.chat_surface_host._read_pty", side_effect=[b"hello", BlockingIOError()]):
            self.host._read("ws.tui.gpt")
        self.assertGreater(self.host._startup_chat_output_at, 0)
        self.assertTrue(self.grid.output_pending())
        self.host._startup_chat_output_at = 0
        self.host._sessions["other"] = {"master": 456, "proc": Proc()}
        with patch("backend.chat_surface_host._read_pty", side_effect=[b"other", BlockingIOError()]):
            self.host._read("other")
        self.assertEqual(self.host._startup_chat_output_at, 0)

    def test_worker_acknowledgements_survive_terminal_reset_and_utf8_split(self):
        encoded = "åäö".encode()
        self.grid.feed_bytes(encoded[:1])
        self.wait_for_parser()
        self.grid.feed_bytes(encoded[1:])
        self.wait_for_parser()
        self.assertIn("åäö", self.visible_text())
        self.grid.reset_terminal()
        self.grid.feed_bytes(b"new chat")
        self.assertTrue(self.grid.output_pending())
        self.wait_for_parser()
        self.assertIn("new chat", self.visible_text())
        self.assertNotIn("åäö", self.visible_text())

    def test_other_chat_modes_do_not_wait_for_a_terminal(self):
        self.root.setProperty("engineTarget", "FLOW_TUI")
        with patch.object(self.host, "_attach_gpt_tui") as gpt, patch.object(
            self.host, "_attach_native_tui"
        ) as grok:
            self.host.prepareStartupChat()
            gpt.assert_not_called()
            grok.assert_not_called()
        self.assertFalse(self.host.startupChatBlocking)

    def test_grok_startup_warms_only_grok(self):
        self.root.setProperty("engineTarget", "GROK_TUI")
        with patch.object(self.host, "_attach_gpt_tui") as gpt, patch.object(
            self.host, "_attach_native_tui"
        ) as grok:
            self.host.prepareStartupChat()
            gpt.assert_not_called()
            grok.assert_called_once_with()
        self.assertEqual(self.host.startupChatTerminal, "ws.tui.grok")
        self.assertTrue(self.host.startupChatBlocking)

    def test_slow_replay_finishes_automatically_after_desktop_is_available(self):
        self.prepare()
        self.host._startup_chat_since -= _STARTUP_CHAT_BLOCK_S + 1
        self.host._poll_startup_chat()
        self.host._startup_chat_timer.stop()
        self.assertTrue(self.host.startupChatRestoring)
        self.assertFalse(self.host.startupChatBlocking)
        self.grid.feed_bytes("LATEST AFTER SLOW START\r\n› ".encode())
        self.wait_for_parser()
        self.host._startup_chat_output_at = time.monotonic() - 2
        self.host._poll_startup_chat()
        self.assertFalse(self.host.startupChatRestoring)
        self.assertIn("LATEST AFTER SLOW START", self.visible_text())

    def test_qml_compiles_with_real_startup_properties(self):
        engine = QQmlEngine()
        for relative in ("Main.qml", "components/GrokTuiHole.qml"):
            component = QQmlComponent(engine, QUrl.fromLocalFile(str(PROJECT / "qml" / relative)))
            self.assertFalse(component.isError(), [error.toString() for error in component.errors()])

    def test_prompt_before_saved_tail_does_not_finish_restore(self):
        self.prepare()
        self.host._startup_chat_checkpoint = normalized_display_text("LATEST SAVED ANSWER")
        self.grid.feed_bytes("banner only\r\n› ".encode())
        self.wait_for_parser()
        self.host._startup_chat_output_at = time.monotonic() - 3
        self.host._poll_startup_chat()
        self.assertTrue(self.host.startupChatRestoring)
        self.grid.feed_bytes("\rLATEST SAVED ANSWER\r\n› ".encode())
        self.wait_for_parser()
        self.host._poll_startup_chat()
        self.assertFalse(self.host.startupChatRestoring)

    def test_unknown_saved_tail_does_not_fall_back_to_idle_guess(self):
        self.prepare()
        self.host._startup_chat_checkpoint = None
        self.grid.feed_bytes("› ".encode())
        self.wait_for_parser()
        self.host._startup_chat_output_at = time.monotonic() - 3
        self.host._poll_startup_chat()
        self.assertTrue(self.host.startupChatRestoring)

    def test_historic_user_line_is_not_the_live_composer(self):
        self.grid.feed_bytes("› saved user question".encode())
        self.wait_for_parser()
        self.assertFalse(self.grid.startup_replay_ready(""))
        self.grid.feed_bytes("\r\n› ".encode())
        self.wait_for_parser()
        self.assertTrue(self.grid.startup_replay_ready(""))

    def test_native_painter_does_not_draw_replay_through_an_overlay(self):
        class Painter:
            backgrounds = 0

            def fillRect(self, *_args):
                self.backgrounds += 1

            def setFont(self, *_args):
                raise AssertionError("Native replay painter reached the text drawing path")

        self.grid.hide_replay(True)
        self.grid.feed_bytes(b"OLD HISTORY MUST STAY HIDDEN")
        self.wait_for_parser()
        painter = Painter()
        self.grid.paint(painter)
        self.assertEqual(painter.backgrounds, 1)


class StartupPtyTests(unittest.TestCase):
    def test_resumed_process_pause_does_not_reveal_older_history(self):
        app = application()
        engine = QQmlEngine()
        component = QQmlComponent(engine, QUrl.fromLocalFile(str(PROJECT / "qml/Main.qml")))
        root = component.create()
        self.assertIsNotNone(root, [error.toString() for error in component.errors()])
        host = ChatSurfaceHost()
        root.setProperty("engineTarget", "GPT_TUI")
        host._qml_root = root
        root.setProperty("surfaceHost", host)
        root.showNormal()
        root.resize(1280, 800)
        terminal_id = "ws.tui.gpt"
        host._gpt_session_id = "00000000-0000-0000-0000-000000000012"
        with tempfile.TemporaryDirectory(prefix="gg-replay-process-") as temporary:
            directory = Path(temporary)
            sessions = directory / "sessions"
            sessions.mkdir()
            rollout = sessions / "fixture.jsonl"
            final = "LATEST SAVED ANSWER reached the actual end of this conversation."
            rollout.write_text(json.dumps({"type": "response_item", "payload": {
                "type": "message", "role": "assistant", "phase": "final_answer",
                "content": [{"type": "output_text", "text": final}]
            }}) + "\n", encoding="utf-8")
            child = directory / "offline_cli.py"
            child.write_text(
                "import sys,time\n"
                "sys.stdout.reconfigure(encoding='utf-8')\n"
                "print('STARTUP HEADER',flush=True)\n"
                "print('\\u203a ',end='',flush=True)\n"
                "time.sleep(1.4)\n"
                "print('\\r\\x1b[2K',end='',flush=True)\n"
                "for n in range(40):\n"
                " print('OLD HISTORY '+str(n),flush=True)\n"
                " time.sleep(0.01)\n"
                "time.sleep(1.2)\n"
                f"print({final!r},flush=True)\n"
                "print('\\u203a ',end='',flush=True)\n"
                "for line in sys.stdin:\n"
                " print('INPUT:'+line.strip(),flush=True)\n", encoding="utf-8")
            from backend.chat_surface_host import _terminal_process

            def launch(argv, master, slave, env, cols=72, rows=36):
                if "resume" in argv:
                    argv = [sys.executable, "-u", str(child)]
                return _terminal_process(argv, master, slave, env, cols, rows)

            def wait_until(condition, timeout=10):
                deadline = time.monotonic() + timeout
                while not condition() and time.monotonic() < deadline:
                    app.processEvents()
                    time.sleep(0.005)
                self.assertTrue(condition(), "Resumed terminal process did not reach expected state")

            def capture(name):
                output = os.environ.get("GG_TEST_ARTIFACTS")
                if output:
                    destination = Path(output)
                    destination.mkdir(parents=True, exist_ok=True)
                    frame = root.grabWindow()
                    self.assertGreaterEqual(frame.width(), 820)
                    self.assertTrue(frame.save(str(destination / name)))

            try:
                with patch.object(host, "_gpt_session_location", return_value=(directory, sessions)), \
                     patch("backend.chat_surface_host.codex_session_path", return_value=rollout), \
                     patch("backend.chat_surface_host.prepare_codex_resume", return_value={"status": "unchanged"}), \
                     patch("backend.chat_surface_host.start_codex_image_guard", side_effect=RuntimeError("offline fixture")), \
                     patch.object(host, "_gptui_developer_instructions", return_value="offline fixture"), \
                     patch("backend.chat_surface_host.shutil.which", return_value=sys.executable), \
                     patch("backend.platform_support.windows_codex_binary", return_value=sys.executable), \
                     patch("backend.chat_surface_host._terminal_process", side_effect=launch), \
                     patch.object(host, "hydrateDesktop", return_value=""):
                    root.setProperty("startupReady", True)
                    root.setProperty("startupModulesReady", True)
                    wait_until(lambda: host._startup_chat_output_at > 0, timeout=20)
                    # Real PTY, notifier, worker and timer; no fabricated idle
                    # timestamps and no replacement for the attach/start path.
                    until = time.monotonic() + 0.95
                    while time.monotonic() < until:
                        app.processEvents()
                        time.sleep(0.005)
                    self.assertTrue(host.startupChatRestoring,
                                    "A gap after the CLI header exposed replay before its saved tail")
                    self.assertTrue(root.property("shellLoading"))
                    grid = host._gpt_grid
                    self.assertTrue(grid._replay_hidden)
                    # Exercise the real QML timeout handoff too: only the
                    # desktop opens; both overlay and native paint stay held.
                    host._startup_chat_since -= _STARTUP_CHAT_BLOCK_S + 1
                    host._poll_startup_chat()
                    wait_until(lambda: not root.property("shellLoading"))
                    overlay = grid.parentItem().findChild(QObject, "startupChatOverlay")
                    self.assertTrue(overlay.property("visible"))
                    self.assertTrue(grid._replay_hidden)
                    self.assertFalse(grid.isEnabled())
                    capture("paused-replay-covered.png")
                    wait_until(lambda: normalized_display_text(final) in normalized_display_text("\n".join(
                        "".join(cell[0] for cell in row) for row in grid._display_rows())))
                    wait_until(lambda: not host.startupChatRestoring)
                    self.assertEqual(grid._view_offset, 0)
                    self.assertTrue(grid.isEnabled())
                    self.assertFalse(grid._replay_hidden)
                    self.assertFalse(overlay.property("visible"))
                    app.processEvents()
                    capture("paused-replay-ready.png")
                    self.assertTrue(host.writeChatTerminal(terminal_id, "hello\n"))
                    wait_until(lambda: "INPUT:hello" in "\n".join(
                        "".join(cell[0] for cell in row) for row in grid._display_rows()))
            finally:
                host.shutdown()
                root.close()
                root.deleteLater()
                app.processEvents()


class StartupQmlTests(unittest.TestCase):
    def test_real_shell_stays_covered_until_selected_chat_is_ready(self):
        app = application()
        engine = QQmlEngine()
        component = QQmlComponent(engine, QUrl.fromLocalFile(str(PROJECT / "qml/Main.qml")))
        window = component.create()
        self.assertIsNotNone(window, [error.toString() for error in component.errors()])
        host = ChatSurfaceHost()
        host._qml_root = window
        window.setProperty("engineTarget", "GPT_TUI")
        window.setProperty("surfaceHost", host)
        window.showNormal()
        window.resize(1280, 800)
        grids = []

        def attach_selected():
            if grids:
                return
            hole = window.findChild(QQuickItem, "gptTuiHost")
            grid = TerminalGrid(hole)
            grid.hide_replay(True)
            grids.append(grid)
            host._gpt_grid = grid
            host._sessions["ws.tui.gpt"] = {}
            host._startup_chat_checkpoint = ""

        def wait_until(condition, timeout=15):
            deadline = time.monotonic() + timeout
            while not condition() and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.005)
            self.assertTrue(condition(), "QML startup did not reach the expected state")

        def capture(name):
            output = os.environ.get("GG_TEST_ARTIFACTS")
            if output:
                destination = Path(output)
                destination.mkdir(parents=True, exist_ok=True)
                frame = window.grabWindow()
                self.assertGreaterEqual(frame.width(), 820)
                self.assertTrue(frame.save(str(destination / name)))

        try:
            # Real shell loaders and property bindings; only the external
            # engines and unrelated wallet hydration are replaced.
            with patch.object(host, "_attach_gpt_tui", side_effect=attach_selected), patch.object(
                host, "_attach_native_tui"
            ) as grok, patch.object(host, "hydrateDesktop", return_value=""):
                window.setProperty("startupReady", True)
                window.setProperty("startupModulesReady", True)
                wait_until(lambda: host.startupChatRestoring)
                host._startup_chat_timer.stop()
                self.assertTrue(window.property("shellLoading"))
                self.assertLess(window.property("shellLoadPercent"), 100)
                grok.assert_not_called()
                capture("startup-restoring.png")
                grid = grids[0]
                grid.feed_bytes("old history\r\nLATEST MESSAGE\r\n› ".encode())
                host._startup_chat_output_at = time.monotonic() - 2
                host._poll_startup_chat()
                self.assertTrue(window.property("shellLoading"))
                wait_until(lambda: not grid.output_pending())
                host._poll_startup_chat()
                wait_until(lambda: not window.property("shellLoading"))
                self.assertEqual(window.property("shellLoadPercent"), 100)
                self.assertFalse(host.startupChatRestoring)
                self.assertTrue(grid.isEnabled())
                capture("startup-ready.png")
        finally:
            host._sessions.clear()
            host.shutdown()
            window.close()
            window.deleteLater()
            app.processEvents()


if __name__ == "__main__":
    unittest.main()
