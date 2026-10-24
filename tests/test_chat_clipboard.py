#!/usr/bin/env python3
from __future__ import annotations

import sys
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from PySide6.QtCore import QEvent, QMimeData, QObject, Property, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QImage, QKeyEvent

from backend.chat_surface_host import ChatSurfaceHost
from backend.terminal_grid import TerminalGrid


class _GridProbe:
    _clipboard_text = TerminalGrid._clipboard_text
    _clipboard_payload = TerminalGrid._clipboard_payload
    _map_key = TerminalGrid._map_key
    _emit_paste = TerminalGrid._emit_paste

    def __init__(self) -> None:
        self.payloads: list[str] = []
        self.errors: list[str] = []
        self.dataProduced = SimpleNamespace(emit=self.payloads.append)
        self.pasteError = SimpleNamespace(emit=self.errors.append)
        self._vt = SimpleNamespace(bracket_paste=True)
        self._paste_image_paths = True


def _clipboard(*, image: bool = False, text: str = "", readable: bool = True):
    mime = QMimeData()
    bitmap = QImage()
    if image:
        if readable:
            bitmap = QImage(2, 2, QImage.Format.Format_ARGB32)
            bitmap.fill(Qt.GlobalColor.red)
        mime.setImageData(bitmap)
    if text:
        mime.setText(text)
    return SimpleNamespace(
        text=mime.text, mimeData=lambda: mime,
        image=lambda: bitmap, setImage=Mock(),
    )


def _host(writer, notice=None):
    return SimpleNamespace(
        _write_chat_terminal=writer,
        chatClipboardNotice=SimpleNamespace(emit=notice or Mock()),
    )


class ChatClipboardTests(unittest.TestCase):
    def test_image_shortcuts_prefer_image_even_when_text_is_available(self):
        for with_text in (False, True):
            for key, modifiers in (
                (Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier),
                (
                    Qt.Key.Key_V,
                    Qt.KeyboardModifier.ControlModifier
                    | Qt.KeyboardModifier.ShiftModifier,
                ),
                (Qt.Key.Key_Insert, Qt.KeyboardModifier.ShiftModifier),
            ):
                with self.subTest(with_text=with_text, key=key, modifiers=modifiers):
                    grid = _GridProbe()
                    clip = _clipboard(image=True, text="image caption" if with_text else "")
                    event = QKeyEvent(QEvent.Type.KeyPress, key, modifiers)
                    with patch("PySide6.QtGui.QGuiApplication.clipboard", return_value=clip):
                        mapped = grid._map_key(event)
                    self.assertEqual(mapped, "")
                    self.assertEqual(len(grid.payloads), 1)
                    payload = grid.payloads[0]
                    self.assertTrue(payload.startswith('\x1b[200~"'))
                    self.assertTrue(payload.endswith('"\x1b[201~'))
                    path = Path(payload[len('\x1b[200~"'):-len('"\x1b[201~')])
                    self.assertEqual(QImage(str(path)), clip.image())
                    self.assertEqual(grid.errors, [""])
                    clip.setImage.assert_not_called()

    def test_text_shortcuts_preserve_bracketed_multiline_paste(self):
        for key, modifiers in (
            (Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier),
            (
                Qt.Key.Key_V,
                Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
            ),
            (Qt.Key.Key_Insert, Qt.KeyboardModifier.ShiftModifier),
        ):
            with self.subTest(key=key, modifiers=modifiers):
                grid = _GridProbe()
                clip = _clipboard(text="https://example.test/image.png\nnext line")
                event = QKeyEvent(QEvent.Type.KeyPress, key, modifiers)
                with patch("PySide6.QtGui.QGuiApplication.clipboard", return_value=clip):
                    self.assertEqual(grid._map_key(event), "")
                self.assertEqual(
                    grid.payloads,
                    ["\x1b[200~https://example.test/image.png\rnext line\x1b[201~"],
                )

    def test_host_image_paste_sends_stable_attachment_path(self):
        for text in ("", "image caption"):
            with self.subTest(text=text):
                writer = Mock(return_value=True)
                host = _host(writer)
                with patch(
                    "PySide6.QtGui.QGuiApplication.clipboard",
                    return_value=_clipboard(image=True, text=text),
                ):
                    self.assertTrue(ChatSurfaceHost.pasteChatTerminal(host, "ws.tui.gpt"))
                writer.assert_called_once()
                args, kwargs = writer.call_args
                self.assertEqual(args[0], "ws.tui.gpt")
                self.assertEqual(kwargs, {"user_input": True})
                payload = args[1]
                self.assertTrue(payload.startswith('\x1b[200~"'))
                self.assertTrue(payload.endswith('"\x1b[201~'))
                path = Path(payload[len('\x1b[200~"'):-len('"\x1b[201~')])
                self.assertFalse(QImage(str(path)).isNull())

    def test_unreadable_image_shows_notice_without_sending_cli_command(self):
        for text in ("", "image caption"):
            with self.subTest(text=text):
                grid = _GridProbe()
                writer = Mock()
                notice = Mock()
                host = _host(writer, notice)
                clip = _clipboard(image=True, text=text, readable=False)
                event = QKeyEvent(
                    QEvent.Type.KeyPress, Qt.Key.Key_V,
                    Qt.KeyboardModifier.ControlModifier,
                )
                with patch("PySide6.QtGui.QGuiApplication.clipboard", return_value=clip):
                    self.assertEqual(grid._map_key(event), "")
                    self.assertFalse(ChatSurfaceHost.pasteChatTerminal(host, "ws.tui.gpt"))
                self.assertEqual(grid.payloads, [])
                self.assertEqual(len(grid.errors), 1)
                notice.assert_called_once_with("ws.tui.gpt", grid.errors[0])
                writer.assert_not_called()
                clip.setImage.assert_not_called()

    def test_host_text_paste_preserves_text_and_write_failure(self):
        for accepted in (False, True):
            with self.subTest(accepted=accepted):
                writer = Mock(return_value=accepted)
                host = _host(writer)
                clip = _clipboard(text="hello\nworld")
                with patch("PySide6.QtGui.QGuiApplication.clipboard", return_value=clip):
                    self.assertEqual(
                        ChatSurfaceHost.pasteChatTerminal(host, "ws.tui.gpt"), accepted,
                    )
                writer.assert_called_once_with(
                    "ws.tui.gpt", "\x1b[200~hello\rworld\x1b[201~", user_input=True)
                clip.setImage.assert_not_called()

    def test_empty_clipboard_does_not_trigger_native_image_paste(self):
        for clip in (None, _clipboard()):
            with self.subTest(clipboard_missing=clip is None):
                grid = _GridProbe()
                writer = Mock()
                host = _host(writer)
                event = QKeyEvent(
                    QEvent.Type.KeyPress,
                    Qt.Key.Key_V,
                    Qt.KeyboardModifier.ControlModifier,
                )
                with patch("PySide6.QtGui.QGuiApplication.clipboard", return_value=clip):
                    self.assertEqual(grid._map_key(event), "")
                    self.assertFalse(ChatSurfaceHost.pasteChatTerminal(host, "ws.tui.gpt"))
                self.assertEqual(grid.payloads, [])
                writer.assert_not_called()

    def test_successful_retry_clears_previous_clipboard_error(self):
        grid = _GridProbe()
        with patch(
            "PySide6.QtGui.QGuiApplication.clipboard",
            return_value=_clipboard(image=True, readable=False),
        ):
            self.assertEqual(grid._clipboard_payload(), "")
        with patch(
            "PySide6.QtGui.QGuiApplication.clipboard",
            return_value=_clipboard(image=True),
        ):
            path = grid._clipboard_payload()
            self.assertTrue(path.startswith('"') and path.endswith('"'))
            self.assertFalse(QImage(path[1:-1]).isNull())
        self.assertTrue(grid.errors[0])
        self.assertEqual(grid.errors[1], "")

    def test_repeated_images_keep_distinct_files_after_clipboard_changes(self):
        from backend.chat_clipboard import read_paste

        paths = []
        for _ in range(12):
            with patch(
                "PySide6.QtGui.QGuiApplication.clipboard",
                return_value=_clipboard(image=True),
            ):
                payload, error = read_paste()
                self.assertFalse(error)
                paths.append(Path(payload[1:-1]))
        self.assertEqual(len(set(paths)), 12)
        self.assertTrue(all(not QImage(str(path)).isNull() for path in paths))

    def test_image_save_failure_does_not_paste_a_missing_attachment(self):
        from backend.chat_clipboard import read_paste

        with patch(
            "PySide6.QtGui.QGuiApplication.clipboard",
            return_value=_clipboard(image=True),
        ), patch("PySide6.QtGui.QImage.save", return_value=False):
            payload, error = read_paste()
        self.assertFalse(payload)
        self.assertTrue(error)

    @unittest.skipUnless(os.name == "nt", "Windows clipboard retry")
    def test_transient_clipboard_lock_retries_before_reporting_failure(self):
        from backend.chat_clipboard import read_paste

        clip = _clipboard(image=True)
        image = clip.image()
        clip.image = Mock(side_effect=[QImage(), image])
        with patch("PySide6.QtGui.QGuiApplication.clipboard", return_value=clip), patch(
            "backend.chat_clipboard._wait_for_clipboard",
        ) as wait:
            payload, error = read_paste()
        self.assertFalse(error)
        self.assertEqual(QImage(payload[1:-1]), image)
        self.assertEqual(clip.image.call_count, 2)
        wait.assert_called_once_with(15)

    def test_other_terminal_keeps_its_native_image_paste_protocol(self):
        clip = _clipboard(image=True)
        grid = _GridProbe()
        grid._paste_image_paths = False
        writer = Mock(return_value=True)
        event = QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_V,
            Qt.KeyboardModifier.ControlModifier,
        )
        with patch("PySide6.QtGui.QGuiApplication.clipboard", return_value=clip):
            self.assertEqual(grid._map_key(event), "\x16")
            self.assertTrue(ChatSurfaceHost.pasteChatTerminal(_host(writer), "ws.tui.grok"))
        self.assertEqual(grid.payloads, [])
        writer.assert_called_once_with("ws.tui.grok", "\x16", user_input=True)


class _NoticeHost(QObject):
    terminalScrollChanged = Signal(str, int, int, int)
    chatTerminalNotice = Signal(str, str)
    chatTerminalFocusRequested = Signal(str)
    chatClipboardNotice = Signal(str, str)
    startupChatRestoring = Property(bool, lambda self: False, constant=True)
    startupChatTerminal = Property(str, lambda self: "", constant=True)

    @Slot(str, result=bool)
    def focusChatTerminal(self, _terminal):
        return False


class ClipboardNoticeTests(unittest.TestCase):
    def test_paste_error_wraps_near_composer_until_a_successful_retry(self):
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQml import QQmlComponent, QQmlEngine

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QGuiApplication.instance() or QGuiApplication([])
        engine = QQmlEngine()
        component = QQmlComponent(engine, QUrl.fromLocalFile(
            str(PROJECT / "qml/components/GrokTuiHole.qml")))
        self.assertFalse(component.isError(), [error.toString() for error in component.errors()])
        host = _NoticeHost()
        surface = component.createWithInitialProperties({
            "surfaceHost": host, "terminalId": "ws.tui.gpt", "width": 240, "height": 400,
        })
        self.assertIsNotNone(surface)
        notice = surface.findChild(QObject, "chatClipboardNotice")
        self.assertFalse(notice.property("visible"))
        host.chatClipboardNotice.emit("ws.tui.grok", "other terminal")
        self.assertFalse(notice.property("visible"))
        message = "Bilden i urklipp kunde inte läsas. Kopiera bilden på nytt från källan."
        host.chatClipboardNotice.emit("ws.tui.gpt", message)
        app.processEvents()
        self.assertTrue(notice.property("visible"))
        self.assertGreater(notice.property("height"), 34)
        self.assertGreater(notice.property("y"), surface.property("height") / 2)
        host.chatTerminalNotice.emit("ws.tui.gpt", "another notice")
        self.assertEqual(surface.property("clipboardNoticeText"), message)
        host.chatClipboardNotice.emit("ws.tui.gpt", "")
        self.assertFalse(notice.property("visible"))
        surface.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
