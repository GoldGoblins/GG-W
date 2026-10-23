from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRect, QTimer, Qt
from PySide6.QtGui import QGuiApplication, QWindow
from PySide6.QtQuick import QQuickItem
from PySide6.QtWidgets import QApplication, QWidget

from backend.grok_tui_embed import cached_quick_item, _descendants, release_embed_windows

XPROP = Path("/usr/bin/xprop")
HOLE_NAME = "workspaceMediaHole"


def _window_xids(pids: set[int], tokens: tuple[str, ...]) -> list[int]:
    if os.name == "nt":
        from backend.windows_windows import window_ids
        return window_ids(pids, tokens)
    if not XPROP.is_file() or not pids:
        return []
    try:
        raw = subprocess.check_output(
            [str(XPROP), "-root", "_NET_CLIENT_LIST"],
            text=True,
            timeout=1.0,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []
    found: list[int] = []
    lowered = tuple(token.lower() for token in tokens if token)
    for token in re.findall(r"0x[0-9a-fA-F]+", raw.split(":", 1)[-1]):
        try:
            info = subprocess.check_output(
                [str(XPROP), "-id", token, "WM_CLASS", "WM_NAME", "_NET_WM_PID"],
                text=True,
                timeout=1.0,
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            continue
        lower = info.lower()
        if "gg ai desktop" in lower:
            continue
        if lowered and not any(name in lower for name in lowered):
            continue
        if not any(re.search(r"\b" + str(pid) + r"\b", info) for pid in pids):
            continue
        found.append(int(token, 16))
    return found


class MediaEmbed(QObject):
    def __init__(self, qml_root: QObject) -> None:
        super().__init__(qml_root)
        self._root = qml_root
        self._holder: QWidget | None = None
        self._foreign: QWindow | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._sync_geometry)
        self._attach_tries = 0
        self._attached = False
        self._error = ""
        self._pid = 0
        self._tokens: tuple[str, ...] = ()
        self._geo: tuple[int, int, int, int] | None = None
        self._hole: QQuickItem | None = None

    def attached(self) -> bool:
        return self._attached

    def error(self) -> str:
        return self._error

    def holder_xid(self) -> int:
        app = QApplication.instance()
        if app is None or not isinstance(app, QApplication):
            self._error = "MEDIA_QT_WIDGETS_MISSING"
            return 0
        holder = self._ensure_holder()
        if holder is None:
            return 0
        holder.show()
        holder.winId()
        self._timer.start()
        self._sync_geometry()
        try:
            return int(holder.winId())
        except Exception:
            return 0

    def attach(self, pid: int, tokens: tuple[str, ...]) -> bool:
        app = QApplication.instance()
        if app is None or not isinstance(app, QApplication):
            self._error = "MEDIA_QT_WIDGETS_MISSING"
            return False
        if pid <= 0:
            self._error = "MEDIA_PID_MISSING"
            return False
        if self._attached and self._pid == pid:
            if self._holder is not None:
                self._holder.show()
                self._sync_geometry()
                self._timer.start()
            return True
        self.detach_window()
        self._pid = int(pid)
        self._tokens = tokens
        self._attach_tries = 0
        self._attached = False
        self._error = ""
        QTimer.singleShot(300, self._try_attach)
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
        self.detach_window()
        self._pid = 0
        self._tokens = ()

    def detach_window(self) -> None:
        self._timer.stop()
        self._attached = False
        foreign = self._foreign
        self._foreign = None
        holder = self._holder
        self._holder = None
        release_embed_windows(foreign, holder)

    def _ensure_holder(self) -> QWidget | None:
        if self._holder is not None:
            return self._holder
        holder = QWidget(None)
        holder.setWindowFlags(
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        )
        holder.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        holder.setStyleSheet("background:#161616")
        self._holder = holder
        self._sync_geometry()
        return holder

    def _try_attach(self) -> None:
        if self._pid <= 0:
            return
        try:
            os.kill(self._pid, 0)
        except OSError:
            self._error = "MEDIA_EXITED"
            return
        ids = _window_xids(_descendants(self._pid), self._tokens)
        if ids:
            if self._embed_window(ids[0]):
                return
        self._attach_tries += 1
        if self._attach_tries < 50:
            QTimer.singleShot(120, self._try_attach)
            return
        self._error = "MEDIA_EMBED_TIMEOUT"

    def _hole_item(self) -> QQuickItem | None:
        self._hole = cached_quick_item(self._root, HOLE_NAME, self._hole)
        return self._hole

    def _main_xid(self) -> int:
        window = QGuiApplication.focusWindow()
        item = self._hole_item()
        if item is not None and item.window() is not None:
            window = item.window()
        if window is None:
            return 0
        try:
            return int(window.winId())
        except Exception:
            return 0

    def _embed_window(self, wid: int) -> bool:
        if self._foreign is not None:
            return True
        main_xid = self._main_xid()
        if wid == 0 or (main_xid and wid == main_xid):
            return False
        holder = self._ensure_holder()
        if holder is None:
            return False
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
