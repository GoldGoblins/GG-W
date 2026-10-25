"""A slow VT parser leaves excess output in the pipe and loses no bytes."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TerminalInputBackpressureTests(unittest.TestCase):
    def fixture(self, source):
        from backend import chat_surface_host as module
        class Grid:
            pending = 0
            received = bytearray()
            def pending_input_bytes(self):
                return self.pending
            def feed_bytes(self, data):
                self.received.extend(data)
                self.pending += len(data)
        grid = Grid()
        pipe = SimpleNamespace(offset=0, calls=0)
        def read(master, size):
            self.assertGreater(size, 0)
            pipe.calls += 1
            if pipe.offset == len(source):
                raise BlockingIOError()
            chunk = source[pipe.offset:pipe.offset + size]
            pipe.offset += len(chunk)
            return chunk
        exits = []
        host = SimpleNamespace(
            _sessions={"ws.tui.gpt": {"master": object(), "proc": SimpleNamespace(poll=lambda: None, returncode=0)}},
            _gpt_grid=grid, _startup_chat_restoring=False,
            _commands_from_gpt_output=lambda _: [], _arm_tui_focus=lambda _: None,
            chatTerminalExit=SimpleNamespace(emit=lambda *args: exits.append(args)),
            _exits=exits)
        host._close = lambda key: host._sessions.pop(key, None)
        return module, host, grid, pipe, read

    def test_full_queue_pauses_pipe_reads_then_delivers_exact_complete_output(self):
        source = ("rad åäö\r\n".encode() + b"\x1b[31mcolored\x1b[0m\r\n") * 25000
        module, host, grid, pipe, read = self.fixture(source)
        with patch.object(module, "_read_pty", side_effect=read):
            while grid.pending < module._PTY_MAX_UNAPPLIED_BYTES:
                self.assertTrue(module.ChatSurfaceHost._read(host, "ws.tui.gpt"))
            stopped_at = pipe.offset
            calls = pipe.calls
            for _ in range(100):
                self.assertTrue(module.ChatSurfaceHost._read(host, "ws.tui.gpt"))
            self.assertEqual(pipe.offset, stopped_at)
            self.assertEqual(pipe.calls, calls)
            self.assertEqual(grid.pending, module._PTY_MAX_UNAPPLIED_BYTES)
            while pipe.offset < len(source):
                grid.pending = 0  # GUI applied the last full snapshot.
                module.ChatSurfaceHost._read(host, "ws.tui.gpt")
                self.assertLessEqual(grid.pending, module._PTY_MAX_UNAPPLIED_BYTES)
        self.assertEqual(bytes(grid.received), source)

    def test_nearly_full_queue_reads_only_remaining_capacity(self):
        module, host, grid, pipe, read = self.fixture(b"new data" * 100)
        grid.pending = module._PTY_MAX_UNAPPLIED_BYTES - 7
        with patch.object(module, "_read_pty", side_effect=read):
            self.assertTrue(module.ChatSurfaceHost._read(host, "ws.tui.gpt"))
        self.assertEqual(pipe.offset, 7)
        self.assertEqual(grid.pending, module._PTY_MAX_UNAPPLIED_BYTES)

    def test_exited_child_keeps_pipe_until_complete_tail_is_delivered(self):
        source = b"exit tail\r\n" * 800
        module, host, grid, pipe, read = self.fixture(source)
        host._sessions["ws.tui.gpt"]["proc"].poll = lambda: 0
        grid.pending = module._PTY_MAX_UNAPPLIED_BYTES - 7
        with patch.object(module, "_read_pty", side_effect=read):
            self.assertTrue(module.ChatSurfaceHost._read(host, "ws.tui.gpt"))
            self.assertIn("ws.tui.gpt", host._sessions)
            self.assertEqual(pipe.offset, 7)
            grid.pending = 0
            self.assertFalse(module.ChatSurfaceHost._read(host, "ws.tui.gpt"))
        self.assertNotIn("ws.tui.gpt", host._sessions)
        self.assertEqual(bytes(grid.received), source)
        self.assertEqual(host._exits, [("ws.tui.gpt", 0)])

    def test_broken_pipe_after_final_bytes_does_not_discard_those_bytes(self):
        source = b"last output before EOF\r\n"
        module, host, grid, pipe, read = self.fixture(source)
        host._sessions["ws.tui.gpt"]["proc"].poll = lambda: 0
        def eof_after_tail(master, size):
            if pipe.offset == len(source):
                raise OSError("fixture pipe ended")
            return read(master, size)
        with patch.object(module, "_read_pty", side_effect=eof_after_tail):
            self.assertFalse(module.ChatSurfaceHost._read(host, "ws.tui.gpt"))
        self.assertEqual(bytes(grid.received), source)
        self.assertEqual(host._exits, [("ws.tui.gpt", 0)])


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="gg input queue fixture ") as temporary:
        for name in ("XDG_STATE_HOME", "GG_RUNTIME_DIR", "GG_WORKSPACE"):
            os.environ.pop(name, None)
        os.environ.update(GG_DESKTOP_STATE_ROOT=str(Path(temporary) / "state"),
                          GG_DESKTOP_DATA_ROOT=str(Path(temporary) / "data"),
                          GG_USER_CODEX_HOME=str(Path(temporary) / "codex"))
        unittest.main()
