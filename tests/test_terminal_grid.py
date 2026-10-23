#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def main() -> int:
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QGuiApplication, QKeyEvent, QMouseEvent
    from PySide6.QtQuick import QQuickItem

    from backend.terminal_grid import TerminalGrid

    app = QApplication.instance() or QApplication(sys.argv)
    host = QQuickItem()
    host.setWidth(800)
    host.setHeight(400)
    grid = TerminalGrid(host)
    grid.setWidth(800)
    grid.setHeight(400)
    grid.feed_text("\x1b[2J\x1b[Hhello")
    shown = grid.vt().display()
    if "hello" not in shown:
        raise AssertionError("grid feed missed text: " + repr(shown))

    grid._selection_anchor = (0, 0)
    grid._selection_cursor = (4, 0)
    grid._selection_moved = True
    clipboard = QGuiApplication.clipboard()
    clipboard.clear()
    if not grid._copy_selection() or clipboard.text() != "hello":
        raise AssertionError("terminal selection did not copy")
    clipboard.clear()
    copy_event = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_C,
        Qt.KeyboardModifier.ControlModifier,
        "c",
    )
    grid.keyPressEvent(copy_event)
    if clipboard.text() != "hello":
        raise AssertionError("Ctrl+C did not copy terminal selection")
    menu_event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(20, 20),
        QPointF(20, 20),
        QPointF(20, 20),
        Qt.MouseButton.RightButton,
        Qt.MouseButton.RightButton,
        Qt.KeyboardModifier.NoModifier,
    )
    if not grid._show_selection_menu(menu_event):
        raise AssertionError("right-click did not open selection menu")
    app.processEvents()
    grid._context_menu.actions()[0].trigger()
    if clipboard.text() != "hello":
        raise AssertionError("context-menu Copy did not copy selection")
    grid._context_menu.close()
    grid._selection_anchor = None
    grid._selection_cursor = None
    grid._selection_moved = False
    if grid._map_key(copy_event) != "":
        raise AssertionError("Ctrl+C without selection lost terminal interrupt")

    grid._vt.feed("old-session\n")
    grid._view_offset = 4
    grid._selection_anchor = (0, 0)
    grid._selection_cursor = (3, 0)
    grid._selection_moved = True
    grid._snap = {"history": grid._vt.history, "buf": grid._vt.buf}
    grid.reset_terminal()
    if grid.vt().display().strip() or grid.vt().history:
        raise AssertionError("terminal reset retained old session output")
    if grid._view_offset != 0 or grid._snap is not None:
        raise AssertionError("terminal reset retained viewport state")
    if grid._selection_anchor is not None or grid._selection_cursor is not None:
        raise AssertionError("terminal reset retained selection state")

    user_input: list[str] = []
    replies: list[str] = []
    grid.dataProduced.connect(user_input.append)
    grid.terminalReplyProduced.connect(replies.append)
    grid.feed_text("\x1b[6n")
    if not any("R" in item for item in replies):
        raise AssertionError("grid did not emit cursor report")
    if user_input:
        raise AssertionError("terminal reply leaked into user input signal")
    pasted_url = "https://x.com/davepl1968/status/2097312063714729991"
    clipboard.setText(pasted_url)
    paste_event = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_V,
        Qt.KeyboardModifier.ControlModifier,
        "\x16",
    )
    grid.keyPressEvent(paste_event)
    if user_input != [pasted_url]:
        raise AssertionError("Ctrl+V did not preserve the complete URL")
    enter = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_Return,
        Qt.KeyboardModifier.NoModifier,
        "\r",
    )
    grid.keyPressEvent(enter)
    if user_input != [pasted_url, "\r"]:
        raise AssertionError("Return did not stay on the user input signal")
    mapped = grid._map_key

    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier)
    if mapped(event) != "\x1b[A":
        raise AssertionError("arrow mapping failed")
    src = (PROJECT / "backend" / "terminal_grid.py").read_text(encoding="utf-8")
    if "class _VtHost" not in src or "QueuedConnection" not in src:
        raise AssertionError("TUI parse still runs on the GUI thread")
    if "font.setBold" in src or "font.setItalic" in src:
        raise AssertionError("TUI paint still mutates a new QFont per glyph run")
    if "_font_bold" not in src:
        raise AssertionError("TUI paint has no cached bold font")
    if "self._blink.start()" in src.split("def _sync_blink")[0]:
        raise AssertionError("TUI cursor blink still runs before the hole is focused")
    if "def _flush_paint" not in src or "def _row_rect" not in src:
        raise AssertionError("TUI still repaints the full grid on every cell change")
    if "max_cols" not in src:
        raise AssertionError("TUI paint still draws columns past the hole")
    if "def _scroll_view" not in src or '"history"' not in src:
        raise AssertionError("TUI has no local inline scrollback viewport")
    if "would mutate the live prompt" not in src:
        raise AssertionError("TUI wheel can still leak into prompt input")
    if "_base_cell_w" not in src:
        raise AssertionError("TUI cell metrics missing")
    if "float(width) / float(cols)" in src:
        raise AssertionError("TUI cell stretch still magnifies the composer corner")
    if "AlignVCenter" not in src:
        raise AssertionError("TUI glyphs still paint without a cell clip rect")
    if "QThread(self)" in src:
        raise AssertionError("VT QThread is still parented to the Quick item")
    if "def itemChange" not in src or "aboutToQuit" not in src:
        raise AssertionError("VT thread is not stopped when the scene goes away")
    grid._stop_worker()
    _ = app
    print("TERMINAL_GRID_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
