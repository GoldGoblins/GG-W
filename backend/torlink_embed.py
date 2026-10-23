from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRect, QTimer, Qt
from PySide6.QtGui import QWindow
from PySide6.QtQuick import QQuickItem
from PySide6.QtWidgets import QApplication, QWidget

from backend.grok_tui_embed import (
    cached_quick_item,
    _descendants,
    konsole_xids,
    release_embed_windows,
)
from backend.media_contract import FETCH_TUI_TITLE
from backend.media_host import bind_fetch_proc, fetch_argv, fetch_download_dir

HOLE_NAME = "workspaceMediaHole"


class TorlinkEmbed(QObject):
    def __init__(self, qml_root: QObject) -> None:
        super().__init__(qml_root)
        self._root = qml_root
        self._proc: subprocess.Popen[bytes] | None = None
        self._holder: QWidget | None = None
        self._foreign: QWindow | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._sync_geometry)
        self._attach_tries = 0
        self._attached = False
        self._error = ""
        self._geo: tuple[int, int, int, int] | None = None
        self._hole: QQuickItem | None = None

    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def attached(self) -> bool:
        return self._attached and self.running()

    def error(self) -> str:
        return self._error

    def start(self) -> bool:
        app = QApplication.instance()
        if app is None or not isinstance(app, QApplication):
            self._error = "MEDIA_QT_WIDGETS_MISSING"
            return False
        if self.attached():
            self.show()
            return True
        self.stop()
        try:
            argv = fetch_argv()
        except RuntimeError as exc:
            self._error = str(exc)
            return False
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "xcb"
        try:
            self._proc = subprocess.Popen(
                argv,
                cwd=str(Path.home()),
                env=env,
                start_new_session=True,
                close_fds=True,
            )
        except OSError as exc:
            self._proc = None
            self._error = "MEDIA_SPAWN_FAILED:" + type(exc).__name__
            return False
        fetch_download_dir().mkdir(mode=0o700, parents=True, exist_ok=True)
        bind_fetch_proc(self._proc)
        self._attach_tries = 0
        self._attached = False
        self._error = ""
        QTimer.singleShot(250, self._try_attach)
        return True

    def hide(self) -> None:
        self._timer.stop()
        holder = self._holder
        if holder is None:
            return
        try:
            holder.hide()
        except RuntimeError:
            self._holder = None

    def show(self) -> None:
        if self._holder is not None:
            self._holder.show()
            self._timer.start()
            self._sync_geometry()

    def stop(self) -> None:
        self._timer.stop()
        self._attached = False
        proc = self._proc
        self._proc = None
        bind_fetch_proc(None)
        foreign = self._foreign
        self._foreign = None
        holder = self._holder
        self._holder = None
        release_embed_windows(foreign, holder)
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()

    def _try_attach(self) -> None:
        proc = self._proc
        if proc is None:
            return
        if proc.poll() is not None:
            self._proc = None
            bind_fetch_proc(None)
            self._error = "MEDIA_EXITED"
            return
        ids = konsole_xids(_descendants(int(proc.pid)), FETCH_TUI_TITLE)
        if ids:
            if self._embed_window(ids[0]):
                return
        self._attach_tries += 1
        if self._attach_tries < 40:
            QTimer.singleShot(100, self._try_attach)
            return
        self.stop()
        self._error = "MEDIA_EMBED_TIMEOUT"

    def _hole_item(self) -> QQuickItem | None:
        self._hole = cached_quick_item(self._root, HOLE_NAME, self._hole)
        return self._hole

    def _main_xid(self) -> int:
        item = self._hole_item()
        if item is None or item.window() is None:
            return 0
        try:
            return int(item.window().winId())
        except Exception:
            return 0

    def _embed_window(self, wid: int) -> bool:
        if self._holder is not None:
            return True
        main_xid = self._main_xid()
        if wid == 0 or (main_xid and wid == main_xid):
            return False
        holder = QWidget(None)
        holder.setWindowFlags(
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        )
        holder.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        holder.setStyleSheet("background:#161616")
        self._holder = holder
        self._sync_geometry()
        holder.show()
        holder.winId()
        holder_xid = int(holder.winId())
        if main_xid and holder_xid == main_xid:
            self.stop()
            return False
        foreign = QWindow.fromWinId(wid)
        handle = holder.windowHandle()
        if foreign is None or handle is None:
            self.stop()
            self._error = "MEDIA_FOREIGN_WINDOW_FAILED"
            return False
        foreign.setParent(handle)
        foreign.show()
        self._foreign = foreign
        self._attached = True
        self._error = ""
        self._timer.start()
        self._sync_geometry()
        return True

    def _host_rect(self) -> QRect | None:
        item = self._hole_item()
        if item is None or not item.isVisible():
            return None
        width = float(item.width())
        height = float(item.height())
        if width < 16 or height < 16:
            return None
        origin = item.mapToGlobal(QPointF(0, 0))
        return QRect(
            int(origin.x()),
            int(origin.y()),
            max(16, int(width)),
            max(16, int(height)),
        )

    def _sync_geometry(self) -> None:
        holder = self._holder
        if holder is None:
            return
        rect = self._host_rect()
        if rect is None:
            self._geo = None
            holder.hide()
            return
        key = (rect.x(), rect.y(), rect.width(), rect.height())
        if holder.isVisible() and self._geo == key:
            return
        self._geo = key
        holder.setGeometry(rect)
        if not holder.isVisible():
            holder.show()
        foreign = self._foreign
        if foreign is not None:
            foreign.setPosition(0, 0)
            foreign.resize(rect.width(), rect.height())
