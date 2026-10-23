from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRect, QTimer, Qt, Signal
from PySide6.QtGui import QWindow
from PySide6.QtQuick import QQuickItem
from PySide6.QtWidgets import QApplication, QWidget

from backend.grok_worker_contract import (
    DEV_GROK_HOME,
    GROK_CWD,
    build_grok_tui_argv,
)

KONSOLE = Path("/usr/bin/konsole")
XPROP = Path("/usr/bin/xprop")
TITLE = "gg-ai-grok-tui"


def drop_qt_wrap(obj: object | None) -> None:
    if obj is None:
        return
    try:
        from shiboken6 import Shiboken
    except ImportError:
        Shiboken = None
    try:
        if Shiboken is not None and not Shiboken.isValid(obj):
            return
        hide = getattr(obj, "hide", None)
        if callable(hide):
            hide()
        parent = getattr(obj, "setParent", None)
        if callable(parent):
            parent(None)
        if Shiboken is not None:
            Shiboken.delete(obj)
            return
        later = getattr(obj, "deleteLater", None)
        if callable(later):
            later()
    except RuntimeError:
        return


def release_embed_windows(foreign: object | None, holder: object | None) -> None:
    drop_qt_wrap(foreign)
    drop_qt_wrap(holder)


def cached_quick_item(
    root: QObject | None, name: str, current: QQuickItem | None
) -> QQuickItem | None:
    if current is not None:
        try:
            if current.objectName() == name:
                return current
        except RuntimeError:
            pass
    if root is None:
        return None
    found = root.findChild(QQuickItem, name)
    return found if isinstance(found, QQuickItem) else None


def _descendants(pid: int) -> set[int]:
    if os.name == "nt":
        import psutil
        try:
            return {pid, *(child.pid for child in psutil.Process(pid).children(recursive=True))}
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return {pid}
    found = {pid}
    stack = [pid]
    while stack:
        current = stack.pop()
        child_file = Path("/proc") / str(current) / "task" / str(current) / "children"
        try:
            raw = child_file.read_text()
        except OSError:
            continue
        for part in raw.split():
            child = int(part)
            if child not in found:
                found.add(child)
                stack.append(child)
    return found


def konsole_xids(pids: set[int], title: str = TITLE) -> list[int]:
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
    wanted = str(title or "")
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
        if "konsole" not in lower:
            continue
        pid_ok = any(re.search(r"\b" + str(pid) + r"\b", info) for pid in pids)
        if (wanted and wanted in info) or pid_ok:
            found.append(int(token, 16))
    return found


def _konsole_xids(pids: set[int]) -> list[int]:
    return konsole_xids(pids, TITLE)


class GrokTuiEmbed(QObject):
    attachFailed = Signal()

    def __init__(self, qml_root: QObject) -> None:
        super().__init__(qml_root)
        self._root = qml_root
        self._proc: subprocess.Popen | None = None
        self._holder: QWidget | None = None
        self._foreign: QWindow | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._sync_geometry)
        self._attach_tries = 0
        self._attached = False
        self._geo: tuple[int, int, int, int] | None = None
        self._hole: QQuickItem | None = None

    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def attached(self) -> bool:
        return self._attached and self.running()

    def start(self) -> bool:
        if QApplication.instance() is None:
            return False
        if not KONSOLE.is_file() or not os.access(KONSOLE, os.X_OK):
            return False
        if self.attached():
            if self._holder is not None:
                self._holder.show()
                self._sync_geometry()
                self._timer.start()
            return True
        self.stop()
        env = os.environ.copy()
        env["GROK_HOME"] = str(DEV_GROK_HOME)
        env["QT_QPA_PLATFORM"] = "xcb"
        argv = [
            str(KONSOLE),
            "--hide-menubar",
            "--hide-tabbar",
            "-e",
            *build_grok_tui_argv(full_screen_tui=True),
        ]
        try:
            self._proc = subprocess.Popen(
                argv,
                cwd=str(GROK_CWD),
                env=env,
                start_new_session=True,
                close_fds=True,
            )
        except OSError:
            self._proc = None
            return False
        self._attach_tries = 0
        self._attached = False
        QTimer.singleShot(250, self._try_attach)
        return True

    def _try_attach(self) -> None:
        proc = self._proc
        if proc is None:
            return
        if proc.poll() is not None:
            self._proc = None
            self.attachFailed.emit()
            return
        ids = _konsole_xids(_descendants(int(proc.pid)))
        if ids:
            if self._embed_window(ids[0]):
                return
        self._attach_tries += 1
        if self._attach_tries < 40:
            QTimer.singleShot(100, self._try_attach)
            return
        self.stop()
        self.attachFailed.emit()

    def _hole_item(self) -> QQuickItem | None:
        self._hole = cached_quick_item(self._root, "grokTuiHost", self._hole)
        return self._hole

    def _main_xid(self) -> int:
        item = self._hole_item()
        if item is None:
            return 0
        window = item.window()
        if window is None:
            return 0
        try:
            return int(window.winId())
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
            return False
        foreign.setParent(handle)
        foreign.show()
        self._foreign = foreign
        self._attached = True
        self._timer.start()
        self._sync_geometry()
        return True

    def stop(self) -> None:
        self._timer.stop()
        self._attached = False
        proc = self._proc
        self._proc = None
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
            int(origin.x()) + 2,
            int(origin.y()) + 20,
            max(16, int(width) - 4),
            max(16, int(height) - 22),
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
