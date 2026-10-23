from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QWindow

XPROP = Path("/usr/bin/xprop")
WMCTRL = Path("/usr/bin/wmctrl")


def apply_desktop_shell_window(window: object, enabled: bool) -> None:
    if window is None:
        return
    on = bool(enabled)
    changed = False
    state_key = "_ggDesktopShellApplied"
    property_reader = getattr(window, "property", None)
    property_writer = getattr(window, "setProperty", None)
    previous_state = (
        property_reader(state_key) if callable(property_reader) else None
    )
    set_flag = getattr(window, "setFlag", None)
    current_flags = getattr(window, "flags", None)
    if callable(set_flag):
        if callable(current_flags):
            try:
                current = current_flags()
                for flag, desired in (
                    (Qt.WindowType.FramelessWindowHint, True),
                    (Qt.WindowType.WindowStaysOnBottomHint, on),
                ):
                    if bool(current & flag) != desired:
                        set_flag(flag, desired)
                        changed = True
            except RuntimeError:
                return
        else:
            set_flag(Qt.WindowType.FramelessWindowHint, True)
            set_flag(Qt.WindowType.WindowStaysOnBottomHint, on)
            changed = True
    screen = None
    getter = getattr(window, "screen", None)
    if callable(getter):
        try:
            screen = getter()
        except RuntimeError:
            screen = None
    if screen is None:
        screen = QGuiApplication.primaryScreen()
    if on and screen is not None:
        geo = screen.availableGeometry()
        setter = getattr(window, "setGeometry", None)
        geometry = getattr(window, "geometry", None)
        if callable(setter) and (not callable(geometry) or geometry() != geo):
            setter(geo)
            changed = True
        is_visible = getattr(window, "isVisible", None)
        show = getattr(window, "show", None)
        if callable(show) and (not callable(is_visible) or not is_visible()):
            show()
            changed = True
    elif not on:
        maximize = getattr(window, "showMaximized", None)
        visibility = getattr(window, "visibility", None)
        try:
            is_maximized = (
                callable(visibility)
                and visibility() == QWindow.Visibility.Maximized
            )
        except RuntimeError:
            return
        if callable(maximize) and not is_maximized:
            maximize()
            changed = True
    stack_state_changed = (
        (previous_state is None and on)
        or (
            previous_state is not None
            and bool(previous_state) != on
        )
    )
    if changed or stack_state_changed:
        _apply_x11_stack(window, on)
        if callable(property_writer):
            property_writer(state_key, on)


def _window_xid(window: object) -> int:
    if str(QGuiApplication.platformName() or "") != "xcb":
        return 0
    win_id = getattr(window, "winId", None)
    if not callable(win_id):
        return 0
    try:
        return int(win_id())
    except (TypeError, ValueError, RuntimeError):
        return 0


def _apply_x11_stack(window: object, enabled: bool) -> None:
    xid = _window_xid(window)
    if xid <= 0:
        return
    hex_id = hex(xid)
    if WMCTRL.is_file() and os.access(WMCTRL, os.X_OK):
        action = "add" if enabled else "remove"
        _run(
            [
                str(WMCTRL),
                "-i",
                "-r",
                hex_id,
                "-b",
                action + ",below,skip_taskbar,skip_pager",
            ]
        )
        return
    if not XPROP.is_file() or not os.access(XPROP, os.X_OK):
        return
    value = (
        "_NET_WM_STATE_BELOW,_NET_WM_STATE_SKIP_TASKBAR,_NET_WM_STATE_SKIP_PAGER"
        if enabled
        else ""
    )
    _run(
        [
            str(XPROP),
            "-id",
            hex_id,
            "-f",
            "_NET_WM_STATE",
            "32a",
            "-set",
            "_NET_WM_STATE",
            value,
        ]
    )


def _run(argv: list[str]) -> None:
    try:
        subprocess.run(
            argv,
            timeout=1.0,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return
