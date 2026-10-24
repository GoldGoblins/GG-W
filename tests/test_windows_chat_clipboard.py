"""Opt-in test of chat shortcuts through Windows clipboard and ConPTY.

Run with GG_TEST_SYSTEM_CLIPBOARD=1. Clipboard contents stay in memory and
are restored afterwards; no provider, account, or network is used.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

_READER = r'''
import msvcrt
from PySide6.QtGui import QImage
print('READY', flush=True)
text = ''
images = 0
while True:
    key = msvcrt.getwch()
    if key == '\x16':
        print('IMAGE_BAD: unexpected native clipboard request', flush=True)
        break
    elif key == '\r':
        expected = ('copy me', '\x1b[200~copy me\x1b[201~')
        print('TEXT_OK' if text in expected else 'TEXT_BAD', flush=True)
        text = ''
    else:
        text += key
        text = text.replace('\x1b[200~', '').replace('\x1b[201~', '')
        if text.startswith('"') and text.endswith('.png"'):
            image = QImage(text[1:-1])
            valid = (not image.isNull() and image.width() == 7 + images
                     and image.height() == 5 + images)
            images += 1
            print('IMAGE_OK_' + str(images) if valid else 'IMAGE_BAD', flush=True)
            text = ''
            if not valid or images == 12:
                break
'''


@unittest.skipUnless(
    os.name == "nt" and os.environ.get("GG_TEST_SYSTEM_CLIPBOARD") == "1",
    "requires Windows and explicit system clipboard test opt-in",
)
class WindowsChatClipboardTests(unittest.TestCase):
    def test_copy_text_and_image_paste_reach_native_console(self):
        with tempfile.TemporaryDirectory(prefix="gg-native-clipboard-") as directory:
            with patch.dict(os.environ, {
                "QT_QPA_PLATFORM": "windows",
                "GG_DESKTOP_STATE_ROOT": str(Path(directory) / "state"),
                "GG_USER_CODEX_HOME": str(Path(directory) / "codex"),
            }):
                self._exercise_console()

    def _exercise_console(self):
        from PySide6.QtCore import QEvent, QMimeData, QPointF, Qt
        from PySide6.QtGui import QImage, QKeyEvent, QMouseEvent
        from PySide6.QtQuick import QQuickItem
        from PySide6.QtWidgets import QApplication
        from backend.chat_surface_host import ChatSurfaceHost
        from backend.terminal_grid import TerminalGrid
        from backend.windows_pty import WindowsPty

        app = QApplication.instance() or QApplication([])
        clipboard = app.clipboard()
        original = clipboard.mimeData()
        saved = QMimeData()
        if original is not None:
            for fmt in original.formats():
                saved.setData(fmt, original.data(fmt))
            if original.hasImage():
                image = clipboard.image()
                if not image.isNull():
                    saved.setImageData(image.copy())

        terminal = WindowsPty(
            [sys.executable, "-B", "-u", "-c", _READER],
            cwd=PROJECT, env=os.environ.copy(), cols=80, rows=10,
        )
        host = ChatSurfaceHost()
        host._sessions["ws.tui.gpt"] = {
            "master": terminal, "write_queue": bytearray(),
            "write_notifier": None,
        }
        pane = QQuickItem()
        pane.setWidth(400)
        pane.setHeight(200)
        grid = TerminalGrid(pane, paste_image_paths=True)
        grid._stop_worker()
        grid.dataProduced.connect(host.gptTuiWrite)
        sent: list[str] = []
        errors: list[str] = []
        grid.dataProduced.connect(sent.append)
        grid.pasteError.connect(errors.append)
        output = bytearray()

        def until(marker: bytes):
            deadline = time.monotonic() + 5
            while marker not in output and time.monotonic() < deadline:
                app.processEvents()
                try:
                    output.extend(terminal.read(65536))
                except BlockingIOError:
                    pass
                if b"TEXT_BAD" in output or b"IMAGE_BAD" in output:
                    self.fail("native console rejected test clipboard data: " + output.decode("utf-8", "replace"))
                time.sleep(0.01)
            self.assertIn(marker, output, "native console roundtrip failed")

        copy = QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_C,
            Qt.KeyboardModifier.ControlModifier, "\x03",
        )
        paste = QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_V,
            Qt.KeyboardModifier.ControlModifier, "\x16",
        )
        try:
            until(b"READY")
            clipboard.setText("retained")
            grid.keyPressEvent(copy)
            grid.keyPressEvent(copy)
            self.assertEqual(sent, [])
            self.assertEqual(clipboard.text(), "retained")
            self.assertIsNone(terminal.poll())

            grid.feed_text("\x1b[2J\x1b[Hcopy me")
            start = QPointF(grid._cell_w / 2, grid._cell_h / 2)
            end = QPointF(grid._cell_w * 6.5, grid._cell_h / 2)
            grid.mousePressEvent(QMouseEvent(
                QEvent.Type.MouseButtonPress, start, start, start,
                Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            ))
            grid.mouseMoveEvent(QMouseEvent(
                QEvent.Type.MouseMove, end, end, end,
                Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            ))
            grid.mouseReleaseEvent(QMouseEvent(
                QEvent.Type.MouseButtonRelease, end, end, end,
                Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            ))
            grid.keyPressEvent(copy)
            self.assertEqual(clipboard.text(), "copy me")
            self.assertEqual(sent, [])

            grid._vt.bracket_paste = True
            grid.keyPressEvent(paste)
            grid.keyPressEvent(QKeyEvent(
                QEvent.Type.KeyPress, Qt.Key.Key_Return,
                Qt.KeyboardModifier.NoModifier, "\r",
            ))
            until(b"TEXT_OK")

            for number in range(1, 13):
                bitmap = QImage(6 + number, 4 + number, QImage.Format.Format_ARGB32)
                bitmap.fill(Qt.GlobalColor.blue)
                clipboard.setImage(bitmap)
                previous = len(sent)
                grid.keyPressEvent(paste)
                self.assertEqual(len(sent), previous + 1,
                                 "paste was dropped: " + (errors[-1] if errors else "no feedback"))
                self.assertTrue(sent[-1].startswith('\x1b[200~"'))
                self.assertTrue(sent[-1].endswith('"\x1b[201~'))
                until(("IMAGE_OK_" + str(number) + "\r\n").encode("ascii"))
            self.assertEqual(sum(payload.startswith('\x1b[200~"') for payload in sent), 12)
            self.assertNotIn("\x16", sent)
            self.assertNotIn("\x03", sent)
        finally:
            host._sessions.clear()
            host.shutdown()
            terminal.close()
            grid._stop_worker()
            if saved.formats():
                clipboard.setMimeData(saved)
                app.processEvents()
                # Materialize restored data before this test owner exits.
                import ctypes
                flush = ctypes.WinDLL("ole32").OleFlushClipboard
                deadline = time.monotonic() + 1
                while flush() != 0 and time.monotonic() < deadline:
                    app.processEvents()
                    time.sleep(0.01)
            else:
                clipboard.clear()


if __name__ == "__main__":
    unittest.main()
