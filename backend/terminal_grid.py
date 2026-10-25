from __future__ import annotations

import base64
import codecs

from PySide6.QtCore import (
    QObject,
    QRect,
    QRectF,
    Qt,
    QThread,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QKeyEvent,
    QPainter,
)
from PySide6.QtQuick import QQuickItem, QQuickPaintedItem
from PySide6.QtWidgets import QMenu

from backend.mini_vt import (
    BOLD,
    DEFAULT_BG_RGB,
    DEFAULT_FG_RGB,
    DIM,
    HIDDEN,
    INVERSE,
    ITALIC,
    MiniVt,
    STRIKE,
    UNDERLINE,
    rgb_of,
)
from backend.chat_restore import normalized_display_text
from backend.chat_clipboard import read_paste
_COLOR_CACHE: dict[tuple[int, int, int], QColor] = {}


def _color(rgb: tuple[int, int, int]) -> QColor:
    cached = _COLOR_CACHE.get(rgb)
    if cached is None:
        cached = QColor(rgb[0], rgb[1], rgb[2])
        _COLOR_CACHE[rgb] = cached
    return cached


_VT_SNAP_MS = 33


class _VtHost(QObject):
    snapshotReady = Signal(object)
    repliesReady = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._vt = MiniVt(24, 80)
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._pulse: QTimer | None = None
        self._dirty = False
        self._history_sent_version = -1
        self._bytes_processed = 0
        self._generation = 0
        self._snapshot_serial = 0
        self._snapshot_in_flight: tuple[int, int] | None = None
        self._closed = False

    @Slot()
    def start(self) -> None:
        if self._closed or self._pulse is not None:
            return
        pulse = QTimer(self)
        pulse.setInterval(_VT_SNAP_MS)
        pulse.setSingleShot(True)
        pulse.timeout.connect(self._emit_snapshot)
        self._pulse = pulse
        self._schedule_snapshot()

    def _schedule_snapshot(self) -> None:
        # The GUI owns at most one full snapshot. Keep parsing into the VT
        # while it is busy, then publish the latest state after its receipt.
        pulse = self._pulse
        if (not self._closed and self._dirty
                and self._snapshot_in_flight is None
                and pulse is not None and not pulse.isActive()):
            pulse.start()

    @Slot(object)
    def feed(self, raw: object) -> None:
        if self._closed:
            return
        blob = raw if isinstance(raw, (bytes, bytearray)) else b""
        if blob:
            text = self._decoder.decode(bytes(blob))
            if text:
                self._vt.feed(text)
            self._bytes_processed += len(blob)
            if self._vt.out:
                reply = "".join(self._vt.out)
                self._vt.out.clear()
                if reply:
                    self.repliesReady.emit(reply)
        self._dirty = True
        self._schedule_snapshot()

    @Slot(int, int)
    def resize(self, rows: int, cols: int) -> None:
        if self._closed:
            return
        self._vt.resize(int(rows), int(cols))
        self._dirty = True
        self._schedule_snapshot()

    @Slot(int)
    def reset(self, generation: int) -> None:
        """Clear the renderer before it is attached to another PTY."""
        if self._closed:
            return
        self._generation = generation
        self._vt.reset()
        self._vt.out.clear()
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._history_sent_version = -1
        self._dirty = True
        # An older delivery still occupies the GUI queue until acknowledged.
        # Do not create a second full snapshot when a session resets.
        self._schedule_snapshot()

    @Slot(int, int)
    def acknowledge(self, generation: int, serial: int) -> None:
        if self._closed or self._snapshot_in_flight != (generation, serial):
            return
        self._snapshot_in_flight = None
        self._schedule_snapshot()

    @Slot()
    def _emit_snapshot(self) -> None:
        pulse = self._pulse
        if pulse is not None:
            pulse.stop()
        if self._closed or not self._dirty or self._snapshot_in_flight is not None:
            return
        self._dirty = False
        vt = self._vt
        history = None
        if vt.history_version != self._history_sent_version:
            history = [row[:] for row in vt.history]
            self._history_sent_version = vt.history_version
        self._snapshot_serial += 1
        self._snapshot_in_flight = (self._generation, self._snapshot_serial)
        self.snapshotReady.emit(
            {
                "generation": self._generation,
                "serial": self._snapshot_serial,
                "buf": [row[:] for row in vt.buf],
                "bytes_processed": self._bytes_processed,
                "history": history,
                "history_version": vt.history_version,
                "r": vt.r,
                "c": vt.c,
                "rows": vt.rows,
                "cols": vt.cols,
                "cursor_visible": vt.cursor_visible,
                "app_cursor": vt.app_cursor,
                "mouse_mode": vt.mouse_mode,
                "mouse_sgr": vt.mouse_sgr,
                "bracket_paste": vt.bracket_paste,
                "alt_screen": vt.alt_screen,
            }
        )

    @Slot()
    def shutdown(self) -> None:
        self._closed = True
        self._dirty = False
        self._snapshot_in_flight = None
        pulse = self._pulse
        self._pulse = None
        if pulse is not None:
            pulse.stop()
        thread = self.thread()
        if thread is not None:
            thread.quit()


class TerminalGrid(QQuickPaintedItem):
    # User input and terminal-generated replies travel in opposite directions.
    # Keeping them on separate signals prevents device/status replies (for
    # example cursor reports) from being mistaken for typed text.
    dataProduced = Signal(str)
    pasteError = Signal(str)
    terminalReplyProduced = Signal(str)
    resized = Signal(int, int)
    # offset, maximum offset, visible page height.  The QML host uses this
    # for a real scrollbar instead of guessing from the painted surface.
    scrollMetricsChanged = Signal(int, int, int)
    ready = Signal()
    _bytesIn = Signal(object)
    _resizeTo = Signal(int, int)
    _reset = Signal(int)
    _snapshotApplied = Signal(int, int)

    def __init__(self, parent: QQuickItem | None = None, *,
                 retain_session_size: bool = False,
                 paste_image_paths: bool = False) -> None:
        super().__init__(parent)
        self._paste_image_paths = paste_image_paths
        self._vt = MiniVt(24, 80)
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._font = QFont("monospace")
        self._font.setPixelSize(13)
        self._font.setStyleHint(QFont.StyleHint.Monospace)
        self._font.setFixedPitch(True)
        self._font_bold = QFont(self._font)
        self._font_bold.setBold(True)
        self._font_italic = QFont(self._font)
        self._font_italic.setItalic(True)
        self._font_both = QFont(self._font)
        self._font_both.setBold(True)
        self._font_both.setItalic(True)
        self._base_cell_w = 8.0
        self._base_cell_h = 16.0
        self._cell_w = 8.0
        self._cell_h = 16.0
        self._ascent = 12
        self._cursor_on = True
        self._last_cols = 0
        self._last_rows = 0
        self._ready_emitted = False
        self._snap: dict | None = None
        self._bytes_submitted = 0
        self._bytes_applied = 0
        self._snapshot_generation = 0
        self._replay_hidden = False
        self._selection_anchor: tuple[int, int] | None = None
        self._selection_cursor: tuple[int, int] | None = None
        self._selecting = False
        self._selection_moved = False
        self._selection_passthrough_click = False
        self._context_menu_open = False
        self._context_menu: QMenu | None = None
        self._view_offset = 0
        # Chat CLIs redraw/replay their transcript on terminal resize. Keep
        # their character grid for the session and fit its presentation into
        # the pane, including native maximize/restore and interactive drags.
        self._retain_session_size = retain_session_size
        self._window_geometry: tuple[float, float] | None = None
        self._window_mode_changing = False
        self._parent_extent: tuple[float, float] | None = None
        self._window_mode_timer = QTimer(self)
        self._window_mode_timer.setSingleShot(True)
        self._window_mode_timer.setInterval(350)
        self._window_mode_timer.timeout.connect(self._finish_window_mode_change)
        self._last_scroll_metrics: tuple[int, int, int] | None = None
        self.setFillColor(_color(DEFAULT_BG_RGB))
        self.setAntialiasing(False)
        self.setOpaquePainting(True)
        self.setRenderTarget(QQuickPaintedItem.RenderTarget.Image)
        self._dirty_union = QRect()
        self.setAcceptedMouseButtons(
            Qt.MouseButton.LeftButton
            | Qt.MouseButton.RightButton
            | Qt.MouseButton.MiddleButton
        )
        self.setAcceptHoverEvents(True)
        self.setFlag(QQuickItem.Flag.ItemAcceptsInputMethod, True)
        self.setFlag(QQuickItem.Flag.ItemHasContents, True)
        self.setKeepMouseGrab(False)
        self.setFocus(True)
        self._blink = QTimer(self)
        self._blink.setInterval(530)
        self._blink.timeout.connect(self._toggle_cursor)
        self._coalesce = QTimer(self)
        self._coalesce.setSingleShot(True)
        self._coalesce.setInterval(_VT_SNAP_MS)
        self._coalesce.timeout.connect(self._flush_paint)
        self.widthChanged.connect(self._refit)
        self.heightChanged.connect(self._refit)
        self._host = _VtHost()
        self._thread = QThread()
        self._thread.setObjectName("gg-vt-host")
        self._host.moveToThread(self._thread)
        self._bytesIn.connect(self._host.feed, Qt.ConnectionType.QueuedConnection)
        self._resizeTo.connect(self._host.resize, Qt.ConnectionType.QueuedConnection)
        self._reset.connect(self._host.reset, Qt.ConnectionType.QueuedConnection)
        self._snapshotApplied.connect(self._host.acknowledge, Qt.ConnectionType.QueuedConnection)
        self._host.snapshotReady.connect(self._apply_snapshot)
        self._host.repliesReady.connect(self.terminalReplyProduced.emit)
        self._thread.started.connect(self._host.start)
        app = QGuiApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._stop_worker)
        self._thread.start()
        if parent is not None:
            self.setParentItem(parent)
            parent.widthChanged.connect(self._fill_parent)
            parent.heightChanged.connect(self._fill_parent)
            self._fill_parent()
        self._measure()
        QTimer.singleShot(0, self._emit_ready)

    def vt(self) -> MiniVt:
        return self._vt

    def reset_terminal(self) -> None:
        """Drop all visible state before reusing this grid for a new PTY."""
        self._snapshot_generation += 1
        self._vt.reset()
        self._vt.out.clear()
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._snap = None
        self._view_offset = 0
        self._last_scroll_metrics = None
        self._selection_anchor = None
        self._selection_cursor = None
        self._selecting = False
        self._selection_moved = False
        self._selection_passthrough_click = False
        self._cursor_on = True
        if self._thread is not None and self._thread.isRunning():
            self._reset.emit(self._snapshot_generation)
        self._emit_scroll_metrics()
        self._touch()

    def _stop_worker(self) -> None:
        thread = self._thread
        if thread is None:
            return
        self._window_mode_timer.stop()
        if self._context_menu is not None:
            self._context_menu.close()
            self._context_menu.deleteLater()
            self._context_menu = None
            self._context_menu_open = False
        self._thread = None
        # Disconnect queued deliveries before stopping the worker.  During
        # application shutdown a queued snapshot can otherwise target a
        # QQuick item after its scene has already been torn down (the observed
        # Python SIGSEGV on window close).
        try:
            self._host.snapshotReady.disconnect(self._apply_snapshot)
        except (AttributeError, TypeError, RuntimeError):
            pass
        try:
            self._host.repliesReady.disconnect(
                self.terminalReplyProduced.emit
            )
        except (AttributeError, TypeError, RuntimeError):
            pass
        if thread.isRunning():
            thread.quit()
            # The worker only owns a lightweight timer/event loop, so a normal
            # quit is sufficient and avoids terminating Qt from underneath a
            # queued callback.
            thread.wait(3000)

    def itemChange(self, change, value):  # type: ignore[no-untyped-def]
        if change == QQuickItem.ItemChange.ItemSceneChange:
            window = getattr(value, "window", None)
            if window is None:
                self._stop_worker()
        elif change == QQuickItem.ItemChange.ItemParentHasChanged and value is None:
            # QML loaders can remove the host item before the scene-change
            # notification arrives.  Stop queued VT deliveries as soon as
            # the painted item loses its parent as well.
            self._stop_worker()
        if change in (
            QQuickItem.ItemChange.ItemVisibleHasChanged,
            QQuickItem.ItemChange.ItemActiveFocusHasChanged,
        ):
            self._sync_blink()
        return super().itemChange(change, value)

    def _fill_parent(self) -> None:
        parent = self.parentItem()
        if parent is None:
            return
        right_inset = max(0.0, float(parent.property("terminalRightInset") or 0.0))
        extent = (max(0.0, float(parent.width()) - right_inset),
                  max(0.0, float(parent.height())))
        if (not self._retain_session_size and self._window_geometry is not None
                and not self._window_mode_changing
                and extent != self._parent_extent):
            # Generic terminals can resume normal reflow after a temporary
            # mode transition. Live chats retain their grid for the session.
            self._window_geometry = None
        self._parent_extent = extent
        self.setX(0)
        if self._window_geometry is not None:
            if self._window_mode_changing:
                self._window_mode_timer.start()
            width, height = self._window_geometry
            scale = min(1.0, extent[0] / width, extent[1] / height)
            self.setTransformOrigin(QQuickItem.TransformOrigin.TopLeft)
            self.setScale(scale)
            self.setY(max(0.0, extent[1] - height * scale))
            self.setWidth(width)
            self.setHeight(height)
            return
        self.setScale(1.0)
        self.setY(0)
        self.setWidth(extent[0])
        self.setHeight(extent[1])

    def preserve_window_geometry(self) -> None:
        """Keep the live PTY size while fitting it to the available pane.

        Inline TUIs can replay their entire transcript after SIGWINCH/ConPTY
        resize. Fit the existing terminal into the new pane instead, keeping
        its input, scroll position and parser alive without that resize.
        """
        if self._last_cols <= 0 or self._last_rows <= 0:
            return
        if self._window_geometry is None:
            width, height = float(self.width()), float(self.height())
            if width <= 0 or height <= 0:
                return
            self._window_geometry = (width, height)
        self._window_mode_changing = not self._retain_session_size
        if self._window_mode_changing:
            self._window_mode_timer.start()
        self._fill_parent()

    def _finish_window_mode_change(self) -> None:
        # Generic terminals keep this fit until their next ordinary resize.
        self._window_mode_changing = False

    def _measure(self) -> None:
        # Keep subpixel advances: rounding each cell down clips long runs.
        cell_w = 6.0
        cell_h = 10.0
        ascent = 8.0
        for font in (
            self._font,
            self._font_bold,
            self._font_italic,
            self._font_both,
        ):
            metrics = QFontMetricsF(font)
            cell_w = max(
                cell_w,
                metrics.horizontalAdvance("M"),
                metrics.averageCharWidth(),
            )
            cell_h = max(cell_h, metrics.height())
            ascent = max(ascent, metrics.ascent())
        self._base_cell_w = cell_w
        self._base_cell_h = cell_h
        self._cell_w = float(cell_w)
        self._cell_h = float(cell_h)
        self._ascent = ascent

    def _emit_ready(self) -> None:
        if self._ready_emitted:
            return
        self._refit()
        if (self.width() <= 0 or self.height() <= 0
                or self._last_cols <= 0 or self._last_rows <= 0):
            QTimer.singleShot(16, self._emit_ready)
            return
        if self._retain_session_size:
            # Choose the measured initial layout before ready starts the PTY.
            # No native window event needs to anticipate a later size change.
            self.preserve_window_geometry()
        self._ready_emitted = True
        self.ready.emit()

    def _toggle_cursor(self) -> None:
        if not self.isVisible() or not self.hasActiveFocus():
            if not self._cursor_on:
                self._cursor_on = True
                self.update()
            return
        self._cursor_on = not self._cursor_on
        snap = self._snap
        if snap is not None:
            self._touch(self._row_rect(int(snap.get("r") or 0)))
        else:
            self._touch()

    def _sync_blink(self) -> None:
        if self.isVisible() and self.hasActiveFocus():
            if not self._blink.isActive():
                self._blink.start()
            return
        if self._blink.isActive():
            self._blink.stop()
        if not self._cursor_on:
            self._cursor_on = True
            self.update()

    def _touch(self, rect: QRect | None = None) -> None:
        if rect is None or not rect.isValid():
            self._dirty_union = QRect(
                0, 0, max(1, int(self.width())), max(1, int(self.height()))
            )
        elif self._dirty_union.isNull():
            self._dirty_union = QRect(rect)
        else:
            self._dirty_union = self._dirty_union.united(rect)
        if not self._coalesce.isActive():
            self._coalesce.start()

    def _flush_paint(self) -> None:
        rect = self._dirty_union
        self._dirty_union = QRect()
        if rect.isNull() or not rect.isValid():
            self.update()
            return
        self.update(rect)

    def _row_rect(self, row: int) -> QRect:
        top = int(row * self._cell_h)
        return QRect(
            0,
            top,
            max(1, int(self.width())),
            max(1, int(round(self._cell_h)) + 1),
        )

    def _selection_bounds(self) -> tuple[tuple[int, int], tuple[int, int]] | None:
        anchor = self._selection_anchor
        cursor = self._selection_cursor
        if (
            anchor is None
            or cursor is None
            or not self._selection_moved
        ):
            return None
        anchor_before = (
            anchor[1] < cursor[1]
            or (anchor[1] == cursor[1] and anchor[0] <= cursor[0])
        )
        if anchor_before:
            return anchor, cursor
        return cursor, anchor

    def _selection_contains(self, row: int, col: int) -> bool:
        bounds = self._selection_bounds()
        if bounds is None:
            return False
        start, end = bounds
        if row < start[1] or row > end[1]:
            return False
        if start[1] == end[1]:
            return start[0] <= col <= end[0]
        if row == start[1]:
            return col >= start[0]
        if row == end[1]:
            return col <= end[0]
        return True

    def _selected_text(self) -> str:
        bounds = self._selection_bounds()
        if bounds is None:
            return ""
        source = self._display_rows()
        start, end = bounds
        lines: list[str] = []
        for row in range(start[1], min(end[1], len(source) - 1) + 1):
            cells = source[row]
            left = start[0] if row == start[1] else 0
            right = end[0] if row == end[1] else len(cells) - 1
            text = "".join(
                (cells[col][0] if cells[col][0] else " ")
                for col in range(max(0, left), min(right, len(cells) - 1) + 1)
            )
            lines.append(text.rstrip())
        return "\n".join(lines)

    def _display_rows(self) -> list[list[tuple[str, int, int, int]]]:
        """Return the current viewport, including the VT's line scrollback."""
        snap = self._snap or {}
        current = snap.get("buf") or self._vt.buf
        history = snap.get("history") or getattr(self._vt, "history", [])
        if not bool(snap.get("alt_screen")) and history:
            rows = int(snap.get("rows") or len(current) or self._last_rows or 1)
            combined = list(history) + list(current)
            max_offset = max(0, len(combined) - rows)
            self._view_offset = max(0, min(self._view_offset, max_offset))
            end = len(combined) - self._view_offset
            start = max(0, end - rows)
            visible = combined[start:end]
            if len(visible) < rows:
                visible = ([self._vt._blank_row()] * (rows - len(visible))) + visible
            return visible
        self._view_offset = 0
        return current

    def _scroll_view(self, lines: int) -> bool:
        snap = self._snap or {}
        history = snap.get("history") or getattr(self._vt, "history", [])
        if not bool(snap.get("alt_screen")) and history:
            rows = int(snap.get("rows") or self._last_rows or 1)
            current = snap.get("buf") or self._vt.buf
            max_offset = max(0, len(history) + len(current) - rows)
            previous = self._view_offset
            self._view_offset = max(0, min(max_offset, previous + int(lines)))
            changed = self._view_offset != previous
            if changed:
                self._emit_scroll_metrics()
                self.update()
            return changed
        return False

    @Slot(int, result=bool)
    def scrollToOffset(self, offset: int) -> bool:
        """Move the inline scrollback viewport to an absolute line offset."""
        snap = self._snap or {}
        history = snap.get("history") or getattr(self._vt, "history", [])
        if not bool(snap.get("alt_screen")) and history:
            rows = int(snap.get("rows") or self._last_rows or 1)
            current = snap.get("buf") or self._vt.buf
            maximum = max(0, len(history) + len(current) - rows)
            previous = self._view_offset
            self._view_offset = max(0, min(maximum, int(offset)))
            changed = self._view_offset != previous
            if changed:
                self._emit_scroll_metrics()
                self.update()
            return changed
        return False

    def _emit_scroll_metrics(self) -> None:
        snap = self._snap or {}
        history = snap.get("history") or getattr(self._vt, "history", [])
        rows = int(snap.get("rows") or self._last_rows or 1)
        current = snap.get("buf") or self._vt.buf
        if not bool(snap.get("alt_screen")) and history:
            maximum = max(0, len(history) + len(current) - rows)
            self._view_offset = max(
                0,
                min(maximum, int(self._view_offset)),
            )
            metrics = (
                self._view_offset,
                maximum,
                max(1, rows),
            )
        else:
            self._view_offset = 0
            metrics = (0, 0, max(1, rows))
        if metrics == self._last_scroll_metrics:
            return
        self._last_scroll_metrics = metrics
        self.scrollMetricsChanged.emit(*metrics)

    def _begin_selection(self, event) -> None:
        col, row = self._cell_at(event.position().x(), event.position().y())
        self._selection_anchor = (col, row)
        self._selection_cursor = (col, row)
        self._selecting = True
        self._selection_moved = False
        self.update()

    def _extend_selection(self, event) -> None:
        if not self._selecting:
            return
        col, row = self._cell_at(event.position().x(), event.position().y())
        next_cursor = (col, row)
        if next_cursor != self._selection_cursor:
            self._selection_cursor = next_cursor
            self._selection_moved = True
            self.update()

    def _finish_selection(self) -> None:
        self._selecting = False
        self.update()

    def _copy_selection(self) -> bool:
        """Copy the current terminal selection without sending PTY input."""
        if self._selection_bounds() is None:
            return False
        clipboard = QGuiApplication.clipboard()
        if clipboard is None:
            return False
        clipboard.setText(self._selected_text())
        return True

    def _context_menu_hidden(self) -> None:
        self._context_menu_open = False

    def _show_selection_menu(self, event) -> bool:
        if self._selection_bounds() is None:
            return False
        menu = self._context_menu
        if menu is None:
            menu = QMenu()
            action = menu.addAction("Copy")
            action.triggered.connect(self._copy_selection)
            menu.aboutToHide.connect(self._context_menu_hidden)
            self._context_menu = menu
        self._context_menu_open = True
        menu.popup(event.globalPosition().toPoint())
        return True

    def _schedule(self) -> None:
        self._touch()

    def _flush_replies(self) -> None:
        if not self._vt.out:
            return
        blob = "".join(self._vt.out)
        self._vt.out.clear()
        self.terminalReplyProduced.emit(blob)

    def _refit(self) -> None:
        if self._window_geometry is not None:
            self._touch()
            return
        width = float(self.width())
        height = float(self.height())
        if width <= 0 or height <= 0:
            return
        base_w = max(1.0, self._base_cell_w)
        base_h = max(1.0, self._base_cell_h)
        cols = max(16, min(240, int(width // base_w)))
        rows = max(8, min(80, int(height // base_h)))
        self._cell_w = float(base_w)
        self._cell_h = float(base_h)
        if cols != self._last_cols or rows != self._last_rows:
            self._vt.resize(rows, cols)
            self._last_cols = cols
            self._last_rows = rows
            self._resizeTo.emit(rows, cols)
            self.resized.emit(cols, rows)
        self._emit_scroll_metrics()
        self._touch()

    @Slot(str)
    def feedB64(self, blob: str) -> None:
        try:
            raw = base64.b64decode(blob.encode("ascii"), validate=False)
        except Exception:
            return
        self.feed_bytes(raw)

    def feed_bytes(self, raw: bytes) -> None:
        if not raw:
            return
        self._bytes_submitted += len(raw)
        if self._thread is not None and self._thread.isRunning():
            self._bytesIn.emit(bytes(raw))
            return
        text = self._decoder.decode(raw)
        self._bytes_applied = self._bytes_submitted
        if not text:
            return
        self._vt.feed(text)
        self._flush_replies()
        self._schedule()

    def output_pending(self) -> bool:
        """Wait for queued parsing and the final coalesced paint request."""
        return self._bytes_applied < self._bytes_submitted or self._coalesce.isActive()

    def pending_input_bytes(self) -> int:
        """Bytes not yet represented by a GUI-applied worker snapshot."""
        return max(0, self._bytes_submitted - self._bytes_applied)

    def hide_replay(self, hidden: bool) -> None:
        """Suppress replay in the native painter as well as the QML overlay."""
        self._replay_hidden = bool(hidden)
        self.setEnabled(not hidden)
        self.update()

    def startup_replay_ready(self, marker: str) -> bool:
        snap = self._snap
        if snap is None or not snap.get("cursor_visible"):
            return False
        rows = snap.get("buf") or []
        cursor_row = int(snap.get("r") or 0)
        if not 0 <= cursor_row < len(rows):
            return False
        line = "".join(cell[0] for cell in rows[cursor_row])
        prompt = line.lstrip()
        if not prompt.startswith(("›", "❯", ">")):
            return False
        # A printed historic user message can start with the same glyph.
        # The live empty composer parks its cursor just after that glyph,
        # including when a dim suggestion is displayed to its right.
        prefix_width = len(line) - len(prompt) + 2
        if prompt[1:].strip() and int(snap.get("c") or 0) > prefix_width:
            return False
        if not marker:
            return True  # A genuinely new chat has no history to replay.
        tail = list((snap.get("history") or [])[-128:]) + rows
        text = "\n".join("".join(cell[0] for cell in row) for row in tail)
        return marker in normalized_display_text(text)

    @Slot(object)
    def _apply_snapshot(self, snap: object) -> None:
        if not isinstance(snap, dict):
            return
        generation, serial = snap.get("generation"), snap.get("serial")
        try:
            if self._thread is None or generation != self._snapshot_generation:
                return
            self._apply_current_snapshot(snap)
        finally:
            # A reset rejects old contents, but must still release that exact
            # delivery so the worker can publish the new session's state.
            if self._thread is not None and isinstance(generation, int) and isinstance(serial, int):
                self._snapshotApplied.emit(generation, serial)

    def _apply_current_snapshot(self, snap: dict) -> None:
        self._bytes_applied = int(snap.get("bytes_processed", self._bytes_applied))
        previous = self._snap
        if snap.get("history") is None and previous is not None:
            snap = dict(snap)
            snap["history"] = previous.get("history") or []
        self._snap = snap
        vt = self._vt
        vt.app_cursor = bool(snap.get("app_cursor"))
        vt.mouse_mode = int(snap.get("mouse_mode") or 0)
        vt.mouse_sgr = bool(snap.get("mouse_sgr"))
        vt.bracket_paste = bool(snap.get("bracket_paste"))
        vt.alt_screen = bool(snap.get("alt_screen"))
        new_buf = snap.get("buf") or []
        old_buf = (previous or {}).get("buf") or []
        old_history = (previous or {}).get("history") or []
        new_history = snap.get("history") or []
        if (
            not bool(snap.get("alt_screen"))
            and self._view_offset > 0
            and len(new_history) > len(old_history)
        ):
            # Keep the same document lines under the cursor while new output
            # grows below the user's manually scrolled viewport.
            self._view_offset += len(new_history) - len(old_history)
        elif bool(snap.get("alt_screen")):
            self._view_offset = 0
        self._emit_scroll_metrics()
        if (not old_buf) or len(old_buf) != len(new_buf):
            self._touch()
            return
        if old_history != new_history:
            self._touch()
        self._touch(self._row_rect(int((previous or {}).get("r") or 0)))
        self._touch(self._row_rect(int(snap.get("r") or 0)))
        for index, row in enumerate(new_buf):
            if index >= len(old_buf) or old_buf[index] != row:
                self._touch(self._row_rect(index))

    def feed_text(self, text: str) -> None:
        if not text:
            return
        self._vt.feed(text)
        self._flush_replies()
        self._schedule()

    def paint(self, painter: QPainter) -> None:
        if self._replay_hidden:
            painter.fillRect(QRectF(0, 0, self.width(), self.height()), _color(DEFAULT_BG_RGB))
            return
        painter.setFont(self._font)
        cell_w = self._cell_w
        cell_h = self._cell_h
        clip = (painter.clipBoundingRect() if painter.hasClipping()
                else QRectF(0, 0, self.width(), self.height()))
        clip_top = clip.top()
        clip_bottom = clip.bottom()
        screen_bg = _color(DEFAULT_BG_RGB)
        max_cols = self._last_cols if self._last_cols > 0 else max(
            1, int(float(self.width()) / max(1.0, float(cell_w)))
        )
        snap = self._snap
        if snap is not None:
            buf = self._display_rows()
            cursor_r = int(snap.get("r") or 0)
            cursor_c = int(snap.get("c") or 0)
            cursor_visible = bool(snap.get("cursor_visible"))
        else:
            buf = self._display_rows()
            cursor_r = self._vt.r
            cursor_c = self._vt.c
            cursor_visible = self._vt.cursor_visible
        width = float(self.width() or 0)
        if width <= 0 or cell_h <= 0:
            return
        for y, row in enumerate(buf):
            y0 = y * cell_h
            if y0 < 0 or y0 > 100000:
                continue
            if y0 + cell_h < clip_top or y0 > clip_bottom:
                continue
            try:
                painter.fillRect(QRectF(0, y0, width, cell_h), screen_bg)
            except (OverflowError, ValueError):
                continue
            x = 0
            limit = min(len(row), max_cols)
            while x < limit:
                ch, fg, bg, flags = row[x]
                if ch == "":
                    x += 1
                    continue
                run_fg, run_bg, run_flags = fg, bg, flags
                text = ch
                nx = x + 1
                while nx < limit:
                    nch, nfg, nbg, nflags = row[nx]
                    if nch == "":
                        nx += 1
                        continue
                    if nfg != run_fg or nbg != run_bg or nflags != run_flags:
                        break
                    text += nch
                    nx += 1
                span = nx - x
                paint_fg, paint_bg = run_fg, run_bg
                if run_flags & INVERSE:
                    paint_fg, paint_bg = paint_bg, paint_fg
                if run_flags & BOLD and 0 <= paint_fg <= 7:
                    paint_fg += 8
                bg_rgb = rgb_of(paint_bg, False)
                fg_rgb = rgb_of(paint_fg, True)
                if run_flags & DIM:
                    fg_rgb = (fg_rgb[0] // 2, fg_rgb[1] // 2, fg_rgb[2] // 2)
                rect = QRectF(x * cell_w, y * cell_h, span * cell_w, cell_h)
                if bg_rgb != DEFAULT_BG_RGB:
                    painter.fillRect(rect, _color(bg_rgb))
                if any(self._selection_contains(y, sx) for sx in range(x, nx)):
                    selection_bg = QColor(53, 91, 120)
                    for sx in range(x, nx):
                        if self._selection_contains(y, sx):
                            painter.fillRect(
                                QRectF(sx * cell_w, y * cell_h, cell_w, cell_h),
                                selection_bg,
                            )
                visible = "".join(part for part in text if part)
                if visible and not (run_flags & HIDDEN) and visible.strip() != "":
                    if run_flags & BOLD and run_flags & ITALIC:
                        painter.setFont(self._font_both)
                    elif run_flags & BOLD:
                        painter.setFont(self._font_bold)
                    elif run_flags & ITALIC:
                        painter.setFont(self._font_italic)
                    else:
                        painter.setFont(self._font)
                    painter.setPen(_color(fg_rgb))
                    painter.drawText(
                        rect,
                        int(
                            Qt.AlignmentFlag.AlignLeft
                            | Qt.AlignmentFlag.AlignVCenter
                        ),
                        visible,
                    )
                    if run_flags & UNDERLINE:
                        painter.drawLine(
                            int(rect.x()),
                            int((y + 1) * cell_h - 2),
                            int(rect.x() + rect.width()),
                            int((y + 1) * cell_h - 2),
                        )
                    if run_flags & STRIKE:
                        painter.drawLine(
                            int(rect.x()),
                            int(y * cell_h + self._ascent * 0.6),
                            int(rect.x() + rect.width()),
                            int(y * cell_h + self._ascent * 0.6),
                        )
                x = nx
        rows = len(buf)
        cols = len(buf[0]) if buf else 0
        if (
            cursor_visible
            and self._cursor_on
            and self._view_offset == 0
            and 0 <= cursor_r < rows
            and 0 <= cursor_c < cols
            and cursor_c < max_cols
        ):
            cx = cursor_c * cell_w
            cy = cursor_r * cell_h
            painter.fillRect(QRectF(cx, cy, cell_w, cell_h), _color(DEFAULT_FG_RGB))
            ch = buf[cursor_r][cursor_c][0]
            if ch:
                painter.setPen(_color(DEFAULT_BG_RGB))
                painter.setFont(self._font)
                painter.drawText(cx, int(cy + self._ascent), ch)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        mods = event.modifiers()
        if event.key() == Qt.Key.Key_PageUp:
            if self._scroll_view(-max(1, self._last_rows - 2)):
                event.accept()
                return
        if event.key() == Qt.Key.Key_PageDown:
            if self._scroll_view(max(1, self._last_rows - 2)):
                event.accept()
                return
        if (
            event.key() == Qt.Key.Key_C
            and mods & Qt.KeyboardModifier.ControlModifier
        ):
            # This is a desktop chat surface. Copy must never fall through
            # to the CLI's Ctrl+C interrupt/exit when there is no selection.
            self._copy_selection()
            event.accept()
            return
        mapped = self._map_key(event)
        if mapped is None:
            super().keyPressEvent(event)
            return
        if mapped:
            self.dataProduced.emit(mapped)
        event.accept()

    def inputMethodEvent(self, event) -> None:
        commit = event.commitString()
        if commit:
            self.dataProduced.emit(commit)
            event.accept()
            return
        super().inputMethodEvent(event)

    def mousePressEvent(self, event) -> None:
        self.forceActiveFocus()
        if (
            event.button() == Qt.MouseButton.RightButton
            and self._show_selection_menu(event)
        ):
            event.accept()
            return
        shift_select = bool(
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        )
        if event.button() == Qt.MouseButton.LeftButton:
            # Start a local drag selection even when the TUI has enabled
            # mouse reporting.  A click without movement is handed back to
            # the TUI on release, so buttons and links still work normally;
            # an actual drag remains available without requiring Shift.
            self._begin_selection(event)
            self._selection_passthrough_click = (
                self._vt.mouse_mode != 0 and not shift_select
            )
            event.accept()
            return
        report = self._mouse(event, pressed=True)
        if report:
            self.dataProduced.emit(report)
            event.accept()
            return
        if event.button() == Qt.MouseButton.MiddleButton:
            paste = self._clipboard_text()
            if paste:
                self._emit_paste(paste)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if (
            event.button() == Qt.MouseButton.RightButton
            and self._context_menu_open
        ):
            event.accept()
            return
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._selecting
        ):
            self._extend_selection(event)
            passthrough = self._selection_passthrough_click
            moved = self._selection_moved
            anchor = self._selection_anchor
            self._finish_selection()
            self._selection_passthrough_click = False
            if not moved:
                # Preserve a normal TUI click when the gesture was not a
                # selection drag.  In mouse-reporting mode the terminal
                # protocol receives both the press and release at the
                # original cell; otherwise this is simply a focus click.
                if passthrough and anchor is not None:
                    col, row = anchor
                    press = self._vt.mouse_report(col, row, 0, True)
                    release = self._vt.mouse_report(col, row, 0, False)
                    if press:
                        self.dataProduced.emit(press)
                    if release:
                        self.dataProduced.emit(release)
                self._selection_anchor = None
                self._selection_cursor = None
                self.update()
            event.accept()
            return
        report = self._mouse(event, pressed=False)
        if report:
            self.dataProduced.emit(report)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._selecting:
            self._extend_selection(event)
            event.accept()
            return
        if self._vt.mouse_mode >= 1002 and event.buttons():
            report = self._mouse(event, pressed=True, motion=True)
            if report:
                self.dataProduced.emit(report)
                event.accept()
                return
        super().mouseMoveEvent(event)

    @Slot(int, result=bool)
    def scrollWheel(self, delta: int) -> bool:
        delta = int(delta)
        if delta == 0:
            return False
        # Inline Codex sessions intentionally keep terminal scrollback local
        # to this renderer.  Consume the wheel here so it cannot become a
        # prompt keystroke.
        steps = max(1, abs(int(delta / 120)))
        snap = self._snap or {}
        history = snap.get("history") or getattr(
            self._vt, "history", []
        )
        if not bool(snap.get("alt_screen")) and history:
            self._scroll_view((3 if delta > 0 else -3) * steps)
            return True
        if self._vt.mouse_mode:
            button = 64 if delta > 0 else 65
            col, row = self._cell_at(self.width() / 2, self.height() / 2)
            report = self._vt.mouse_report(col, row, button, True)
            if report:
                self.dataProduced.emit(report)
            return bool(report)
        # There is no local scrollback yet.  Still consume the event: sending
        # PageUp/PageDown to the PTY would mutate the live prompt instead of
        # scrolling the rendered text.
        return True

    def wheelEvent(self, event) -> None:
        if self.scrollWheel(event.angleDelta().y()):
            event.accept()
            return
        event.ignore()
        event.accept()

    def _cell_at(self, px: float, py: float) -> tuple[int, int]:
        cols = int((self._snap or {}).get("cols") or self._vt.cols)
        rows = int((self._snap or {}).get("rows") or self._vt.rows)
        col = max(0, min(cols - 1, int(px // self._cell_w)))
        row = max(0, min(rows - 1, int(py // self._cell_h)))
        return col, row

    def _mouse(self, event, pressed: bool, motion: bool = False) -> str:
        if self._vt.mouse_mode == 0:
            return ""
        button = 0
        if event.button() == Qt.MouseButton.RightButton:
            button = 2
        elif event.button() == Qt.MouseButton.MiddleButton:
            button = 1
        elif motion:
            button = 0
        col, row = self._cell_at(event.position().x(), event.position().y())
        return self._vt.mouse_report(col, row, button, pressed, motion)

    def _clipboard_text(self) -> str:
        clip = QGuiApplication.clipboard()
        if clip is None:
            return ""
        return clip.text() or ""

    def _clipboard_payload(self) -> str:
        payload, error = read_paste(image_paths=self._paste_image_paths)
        # An empty error clears feedback from the previous paste attempt.
        self.pasteError.emit(error)
        return payload

    def _emit_paste(self, text: str) -> None:
        payload = text.replace("\n", "\r")
        if self._vt.bracket_paste:
            payload = "\x1b[200~" + payload + "\x1b[201~"
        self.dataProduced.emit(payload)

    def _map_key(self, event: QKeyEvent) -> str | None:
        key = event.key()
        mods = event.modifiers()
        text = event.text()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        if key == Qt.Key.Key_Shift or key == Qt.Key.Key_Control or key == Qt.Key.Key_Alt:
            return ""
        # Text and image attachment paths both use the CLI's paste handling.
        if (key == Qt.Key.Key_Insert and shift) or (ctrl and key == Qt.Key.Key_V):
            paste = self._clipboard_payload()
            if paste:
                if paste == "\x16" and not self._paste_image_paths:
                    return paste
                self._emit_paste(paste)
            return ""
        if ctrl and key == Qt.Key.Key_C:
            return ""
        arrows = {
            Qt.Key.Key_Up: ("A", "OA"),
            Qt.Key.Key_Down: ("B", "OB"),
            Qt.Key.Key_Right: ("C", "OC"),
            Qt.Key.Key_Left: ("D", "OD"),
        }
        if key in arrows:
            normal, app = arrows[key]
            if self._vt.app_cursor:
                return "\x1b" + app
            return "\x1b[" + normal
        extras = {
            Qt.Key.Key_Home: "\x1b[H",
            Qt.Key.Key_End: "\x1b[F",
            Qt.Key.Key_PageUp: "\x1b[5~",
            Qt.Key.Key_PageDown: "\x1b[6~",
            Qt.Key.Key_Insert: "\x1b[2~",
            Qt.Key.Key_Delete: "\x1b[3~",
            Qt.Key.Key_F1: "\x1bOP",
            Qt.Key.Key_F2: "\x1bOQ",
            Qt.Key.Key_F3: "\x1bOR",
            Qt.Key.Key_F4: "\x1bOS",
            Qt.Key.Key_F5: "\x1b[15~",
            Qt.Key.Key_F6: "\x1b[17~",
            Qt.Key.Key_F7: "\x1b[18~",
            Qt.Key.Key_F8: "\x1b[19~",
            Qt.Key.Key_F9: "\x1b[20~",
            Qt.Key.Key_F10: "\x1b[21~",
            Qt.Key.Key_F11: "\x1b[23~",
            Qt.Key.Key_F12: "\x1b[24~",
        }
        if key in extras:
            return extras[key]
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            return "\r"
        if key == Qt.Key.Key_Backspace:
            return "\x7f"
        if key == Qt.Key.Key_Tab:
            return "\x1b[Z" if shift else "\t"
        if key == Qt.Key.Key_Escape:
            return "\x1b"
        if ctrl and Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
            return chr(key - Qt.Key.Key_A + 1)
        if ctrl and text:
            return text
        if alt and text:
            return "\x1b" + text
        if text:
            return text
        return None
