from __future__ import annotations
from backend.platform_support import platform_path

import ctypes
import os
import re
import subprocess
from ctypes import POINTER, byref, c_uint, c_ulong, c_void_p
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRect, QTimer, Qt
from PySide6.QtGui import QGuiApplication, QWindow
from PySide6.QtQuick import QQuickItem

from backend.blender_contract import (
    SCENE_BLEND,
    SIDECAR_SCRIPT,
    blender_bin,
    ensure_user_config,
    gui_environment,
    sidecar_reachable,
)
from backend.grok_tui_embed import cached_quick_item, _descendants

XPROP = Path("/usr/bin/xprop")
HOLE_NAME = "workspaceExternalHole"
TOKENS = ("blender",)
LOG_PATH = Path(platform_path("/tmp/gg-blender-embed.log"))
_X11 = None


def _log(message: str) -> None:
    try:
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(message.rstrip() + "\n")
    except OSError:
        return


def _x11_env() -> dict[str, str]:
    env = os.environ.copy()
    if not str(env.get("DISPLAY") or "").strip():
        env["DISPLAY"] = ":0"
    return env


def _xprop(*args: str) -> str:
    if not XPROP.is_file():
        return ""
    try:
        return subprocess.check_output(
            [str(XPROP), *args],
            text=True,
            timeout=1.5,
            env=_x11_env(),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        _log("xprop_fail " + type(exc).__name__)
        return ""


def _sidecar_pids() -> set[int]:
    if os.name == "nt":
        import psutil
        found = set()
        for process in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                if process.info["name"].lower() == "blender.exe" and any("gg_blender_sidecar" in arg for arg in process.info["cmdline"] or []):
                    found.add(process.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return found
    found: set[int] = set()
    proc = Path("/proc")
    try:
        entries = list(proc.iterdir())
    except OSError:
        return found
    for path in entries:
        if not path.name.isdigit():
            continue
        try:
            cmd = (path / "cmdline").read_bytes()
        except OSError:
            continue
        if b"blender" not in cmd:
            continue
        if b"gg_blender_sidecar" in cmd or b"blender-5" in cmd:
            found.add(int(path.name))
    return found


def _x11_lib():
    global _X11
    if _X11 is not None:
        return _X11
    try:
        lib = ctypes.cdll.LoadLibrary("libX11.so.6")
        lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        lib.XOpenDisplay.restype = c_void_p
        lib.XDefaultRootWindow.argtypes = [c_void_p]
        lib.XDefaultRootWindow.restype = c_ulong
        lib.XQueryTree.argtypes = [
            c_void_p,
            c_ulong,
            POINTER(c_ulong),
            POINTER(c_ulong),
            POINTER(POINTER(c_ulong)),
            POINTER(c_uint),
        ]
        lib.XQueryTree.restype = c_uint
        lib.XFree.argtypes = [c_void_p]
        lib.XCloseDisplay.argtypes = [c_void_p]
    except OSError:
        _X11 = False
        return None
    _X11 = lib
    return lib


def _x11_children(display: int, wid: int) -> list[int]:
    lib = _x11_lib()
    if not lib:
        return []
    root_ret = c_ulong()
    parent = c_ulong()
    children = POINTER(c_ulong)()
    count = c_uint()
    if not lib.XQueryTree(
        display, wid, byref(root_ret), byref(parent), byref(children), byref(count)
    ):
        return []
    ids = [int(children[index]) for index in range(count.value)]
    if children:
        lib.XFree(children)
    return ids


def _x11_tree_xids(pids: set[int], tokens: tuple[str, ...]) -> list[int]:
    """Find Blender windows even when withdrawn and missing from the client list."""
    lib = _x11_lib()
    if not lib:
        return []
    display = lib.XOpenDisplay(None)
    if not display:
        return []
    found: list[int] = []
    try:
        root = int(lib.XDefaultRootWindow(display))
        queue = [root]
        seen: set[int] = set()
        lowered = tuple(token.lower() for token in tokens if token)
        while queue and len(seen) < 512:
            wid = queue.pop(0)
            if wid in seen:
                continue
            seen.add(wid)
            if wid != root:
                info = _xprop("-id", hex(wid), "WM_CLASS", "WM_NAME", "_NET_WM_PID")
                lower = info.lower()
                if info and "gg ai desktop" not in lower:
                    pid_ok = any(
                        re.search(r"\b" + str(pid) + r"\b", info) for pid in pids
                    )
                    class_ok = any(name in lower for name in lowered)
                    if pid_ok or class_ok:
                        found.append(wid)
            queue.extend(_x11_children(display, wid))
    finally:
        lib.XCloseDisplay(display)
    return found


def _window_xids(pids: set[int], tokens: tuple[str, ...]) -> list[int]:
    if os.name == "nt":
        from backend.windows_windows import window_ids
        return window_ids(pids, tokens)
    raw = _xprop("-root", "_NET_CLIENT_LIST")
    found: list[int] = []
    seen: set[int] = set()
    lowered = tuple(token.lower() for token in tokens if token)
    for token in re.findall(r"0x[0-9a-fA-F]+", (raw or "").split(":", 1)[-1]):
        info = _xprop("-id", token, "WM_CLASS", "WM_NAME", "_NET_WM_PID")
        if not info:
            continue
        lower = info.lower()
        if "gg ai desktop" in lower:
            continue
        pid_ok = any(re.search(r"\b" + str(pid) + r"\b", info) for pid in pids)
        class_ok = any(name in lower for name in lowered)
        if pid_ok or class_ok:
            wid = int(token, 16)
            if wid not in seen:
                seen.add(wid)
                found.append(wid)
    for wid in _x11_tree_xids(pids, tokens):
        if wid not in seen:
            seen.add(wid)
            found.append(wid)
    return found


class BlenderEmbed(QObject):
    """Parent Blender as a native child of the GG AI Desktop window.

    The host must be X11/XWayland (xcb).  The child is the EXT hole, not a
    Tool window and not an override-redirect overlay, so other programs cover
    it with the rest of the desktop.
    """

    def __init__(self, qml_root: QObject) -> None:
        super().__init__(qml_root)
        self._root = qml_root
        self._proc: subprocess.Popen[bytes] | None = None
        self._child: QWindow | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._sync_geometry)
        self._attach_tries = 0
        self._attached = False
        self._error = ""
        self._geo: tuple[int, int, int, int] | None = None
        self._hole: QQuickItem | None = None
        self._qml_rect: QRect | None = None
        self._adopted_pid = 0

    def running(self) -> bool:
        if self._proc is not None and self._proc.poll() is None:
            return True
        if self._adopted_pid > 0:
            return Path("/proc/%d" % self._adopted_pid).exists()
        return False

    def attached(self) -> bool:
        return self._attached and self.running()

    def error(self) -> str:
        return self._error

    def set_hole_rect(self, x: float, y: float, width: float, height: float) -> None:
        """EXT pane reports the hole in the desktop window's content coordinates."""
        rect = QRect(
            int(round(x)),
            int(round(y)),
            max(16, int(round(width))),
            max(16, int(round(height))),
        )
        if self._qml_rect != rect:
            _log(
                "hole_from_qml x=%s y=%s w=%s h=%s"
                % (rect.x(), rect.y(), rect.width(), rect.height())
            )
        self._qml_rect = rect
        if self._attached:
            self._sync_geometry()

    def start(self, wayland_socket: str = "") -> bool:
        app = QGuiApplication.instance()
        if app is None:
            self._error = "BLENDER_QT_MISSING"
            return False
        platform = str(app.platformName() or "")
        if platform not in ("xcb", "windows"):
            self._error = "EXT_UNSUPPORTED_HOST platform=" + platform
            _log(self._error)
            return False
        path = blender_bin()
        if not path:
            self._error = "BLENDER_BIN_MISSING"
            return False
        if not SIDECAR_SCRIPT.is_file():
            self._error = "BLENDER_SIDECAR_MISSING"
            return False
        if self.attached():
            self.show()
            return True
        if self.running():
            self.show()
            QTimer.singleShot(200, self._try_attach)
            return True
        # One Blender, the one already holding the sidecar.  Never spawn a
        # second GUI (that became the default cube / black hole).
        if sidecar_reachable():
            if self._adopt_existing():
                self.show()
                return True
            self._error = "BLENDER_EMBED_WAITING"
            _log("adopt_miss sidecar live, retry")
            QTimer.singleShot(400, self._retry_start)
            return True
        self.stop()
        ensure_user_config()
        env = gui_environment()
        argv = [path]
        if SCENE_BLEND.is_file():
            argv.append(str(SCENE_BLEND))
        argv.extend(
            [
                "--python",
                str(SIDECAR_SCRIPT),
                "--window-geometry",
                "80",
                "80",
                "1280",
                "800",
            ]
        )
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
            self._error = "BLENDER_SPAWN_FAILED:" + type(exc).__name__
            return False
        self._attach_tries = 0
        self._attached = False
        self._error = ""
        _log("start x11-child pid=" + str(self._proc.pid))
        QTimer.singleShot(800, self._try_attach)
        return True

    def _retry_start(self) -> None:
        if not self.attached():
            self.start()

    def _adopt_existing(self) -> bool:
        """Embed the already-running sidecar Blender instead of spawning."""
        pids = _sidecar_pids()
        ids = _window_xids(pids, TOKENS)
        if not ids:
            self._error = "BLENDER_WINDOW_MISSING"
            _log("adopt_no_window pids=" + ",".join(str(pid) for pid in sorted(pids)))
            return False
        chosen = ids[-1]
        info = _xprop("-id", hex(chosen), "_NET_WM_PID")
        match = re.search(r"(\d+)", info or "")
        pid = int(match.group(1)) if match else (next(iter(pids)) if pids else 0)
        if not self._embed_window(chosen):
            return False
        self._adopted_pid = pid
        _log("adopted sidecar wid=" + hex(chosen) + " pid=" + str(pid))
        return True

    def hide(self) -> None:
        self._timer.stop()
        child = self._child
        if child is not None:
            child.hide()

    def show(self) -> None:
        if self._child is not None:
            self._child.show()
            self._timer.start()
            self._sync_geometry()

    def stop(self) -> None:
        self._timer.stop()
        self._attached = False
        child = self._child
        self._child = None
        if child is not None:
            try:
                child.setParent(None)
                child.hide()
            except RuntimeError:
                pass
        proc = self._proc
        self._proc = None
        adopted = self._adopted_pid
        self._adopted_pid = 0
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        elif adopted > 0 and Path("/proc/%d" % adopted).exists():
            try:
                os.kill(adopted, 15)
            except OSError:
                pass

    def _try_attach(self) -> None:
        proc = self._proc
        if proc is None:
            return
        if proc.poll() is not None:
            self._proc = None
            self._error = "BLENDER_EXITED"
            return
        pids = _descendants(int(proc.pid))
        ids = _window_xids(pids, TOKENS)
        chosen = ids[-1] if ids else 0
        if chosen and self._embed_window(chosen):
            _log("embedded child wid=" + hex(chosen))
            return
        self._attach_tries += 1
        if self._attach_tries in {1, 8, 20}:
            _log(
                "attach_miss try="
                + str(self._attach_tries)
                + " ids="
                + ",".join(hex(item) for item in ids)
                + " err="
                + self._error
            )
        delay = 200 if self._attach_tries < 40 else 1000
        if not self._error:
            self._error = "BLENDER_EMBED_WAITING"
        QTimer.singleShot(delay, self._try_attach)

    def _hole_item(self) -> QQuickItem | None:
        self._hole = cached_quick_item(self._root, HOLE_NAME, self._hole)
        return self._hole

    def _embed_window(self, wid: int) -> bool:
        if self._child is not None:
            self._sync_geometry()
            return True
        hole = self._hole_item()
        if hole is None or hole.window() is None:
            self._error = "BLENDER_HOLE_NOT_READY"
            return False
        host = hole.window()
        try:
            child = QWindow.fromWinId(wid)
        except Exception as exc:
            self._error = "BLENDER_FOREIGN_WINDOW_FAILED:" + type(exc).__name__
            return False
        if child is None:
            self._error = "BLENDER_FOREIGN_WINDOW_FAILED"
            return False
        child.setFlags(Qt.WindowType.FramelessWindowHint)
        child.setParent(host)
        self._child = child
        self._attached = True
        self._error = ""
        self._sync_geometry()
        child.show()
        self._timer.start()
        return True

    def _host_rect(self) -> QRect | None:
        if self._qml_rect is not None and self._qml_rect.width() >= 16:
            return QRect(self._qml_rect)
        item = self._hole_item()
        if item is None or not item.isVisible() or item.window() is None:
            return None
        width = float(item.width())
        height = float(item.height())
        if width < 16 or height < 16:
            return None
        window = item.window()
        global_pos = item.mapToGlobal(QPointF(0.0, 0.0))
        local = window.mapFromGlobal(global_pos.toPoint())
        return QRect(
            int(local.x()),
            int(local.y()),
            max(16, int(round(width))),
            max(16, int(round(height))),
        )

    def _sync_geometry(self) -> None:
        child = self._child
        if child is None:
            return
        rect = self._host_rect()
        if rect is None:
            child.hide()
            self._geo = None
            return
        key = (rect.x(), rect.y(), rect.width(), rect.height())
        if child.isVisible() and self._geo == key:
            return
        self._geo = key
        child.setPosition(rect.x(), rect.y())
        child.resize(rect.width(), rect.height())
        if not child.isVisible():
            child.show()


# Keep X11's foreign-window path on Linux. Windows must retain Blender's
# native HWND and perform network/process discovery away from Qt's thread.
if os.name == "nt":
    from backend.windows_blender_embed import WindowsBlenderEmbed as BlenderEmbed
