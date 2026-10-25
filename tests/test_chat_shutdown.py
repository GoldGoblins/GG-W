"""Exercise cleanup ordering and failures without starting user services."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))


class ChatShutdownTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtCore import QCoreApplication
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def make_host(self, failures=(), reentrant=False):
        from PySide6.QtCore import QObject, QTimer
        from backend.chat_surface_host import ChatSurfaceHost

        events = []
        host = QObject()
        host._sessions = {"first": object(), "second": object()}
        host._startup_chat_restoring = True
        host._startup_chat_blocking = True
        host._tui_focus_terminal = "fixture"
        # Include the producer timers omitted by the old shutdown, plus a
        # nested timer: all belong to this host and must stop before cleanup.
        host._timers = []
        nested = QObject(host)
        for parent in (host, host, host, nested):
            timer = QTimer(parent)
            timer.start(60_000)
            host._timers.append(timer)

        def action(name):
            def run():
                self.assertTrue(all(not timer.isActive() for timer in host._timers))
                events.append(name)
                if reentrant and name == "crypto":
                    ChatSurfaceHost.shutdown(host)
                if name in failures:
                    raise RuntimeError("private fixture data must not enter diagnostics")
            return run

        host._crypto_ui = SimpleNamespace(close=action("crypto"))
        host._tmog_sampler = SimpleNamespace(close=action("telemetry"))
        host._gpt_storage_guard = SimpleNamespace(poll=lambda: None, terminate=action("guard"))
        host._flow_tui_stop = action("flow")
        def close_terminal(key):
            host._sessions.pop(key)
            action("terminal_" + key)()
        host._close = close_terminal
        host._qml_reload_safety_barrier = action("qml")
        host.stopSitePreview = action("preview")
        for name in ("_tui_embed", "_tmog_embed", "_media_embed",
                     "_torlink_embed", "_external_embed", "_draw_embed"):
            setattr(host, name, SimpleNamespace(stop=action(name)))
        host._osint = SimpleNamespace(shutdown=action("osint"))
        return host, events, action

    def run_shutdown(self, host, action):
        from backend.chat_surface_host import ChatSurfaceHost
        with patch("backend.site_jobs.cancel", side_effect=action("jobs")), \
             patch("backend.site_database.stop_mysqld", side_effect=lambda **kwargs: action("database")()) as database, \
             patch("backend.game_engine_host.shutdown", side_effect=action("game")), \
             patch("backend.media_host.stop", side_effect=action("media")):
            ChatSurfaceHost.shutdown(host)
        database.assert_called_once_with(timeout=3.0, only_started=True)

    def test_all_producers_stop_before_cleanup(self):
        host, events, action = self.make_host()
        self.run_shutdown(host, action)
        self.assertFalse(host._sessions)
        self.assertEqual(events[-3:], ["osint", "game", "media"])
        self.assertEqual(host._shutdown_errors, ())
        self.assertFalse(host._startup_chat_restoring)
        self.assertFalse(host._startup_chat_blocking)
        self.assertIsNone(host._gpt_storage_guard)
        self.assertIsNone(host._external_embed)

    def test_failed_child_does_not_abandon_remaining_resources(self):
        host, events, action = self.make_host({"crypto", "guard", "terminal_first", "_media_embed"})
        self.run_shutdown(host, action)
        self.assertEqual(events[-3:], ["osint", "game", "media"])
        self.assertIn("terminal_second", events)
        self.assertIn("_draw_embed", events)
        self.assertFalse(host._sessions)
        self.assertEqual(host._shutdown_errors, (
            ("crypto", "RuntimeError"), ("storage_guard", "RuntimeError"),
            ("terminal", "RuntimeError"), ("_media_embed", "RuntimeError")))

    def test_nested_shutdown_does_not_repeat_cleanup(self):
        host, events, action = self.make_host(reentrant=True)
        self.run_shutdown(host, action)
        self.assertEqual(events.count("crypto"), 1)
        self.assertEqual(events.count("flow"), 1)
        self.assertFalse(host._shutdown_in_progress)

    def test_later_shutdown_can_release_newly_owned_resources(self):
        host, events, action = self.make_host()
        self.run_shutdown(host, action)
        host._external_embed = SimpleNamespace(stop=action("new_external"))
        for timer in host._timers:
            timer.start(60_000)
        self.run_shutdown(host, action)
        self.assertEqual(events.count("new_external"), 1)
        self.assertIsNone(host._external_embed)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="gg shutdown fixture ") as temporary:
        os.environ.update(GG_DATA_HOME=temporary, GG_USER_HOME=temporary,
                          GG_USER_CODEX_HOME=str(Path(temporary) / "codex"),
                          CODEX_HOME=str(Path(temporary) / "codex"))
        for name in ("XDG_STATE_HOME", "GG_DESKTOP_STATE_ROOT", "GG_DESKTOP_DATA_ROOT",
                     "GG_RUNTIME_DIR", "GG_WORKSPACE"):
            os.environ.pop(name, None)
        unittest.main()
