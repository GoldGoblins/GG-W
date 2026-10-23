"""Windows Blender child window; socket/process discovery never runs in Qt."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from concurrent.futures import Future
import os
import subprocess
import threading
import time

from PySide6.QtCore import QEvent, QObject, QPointF, QRect, QTimer

from backend import blender_contract as contract
from backend.grok_tui_embed import cached_quick_item
from backend.windows_windows import window_ids


class NativeBlenderWindow:
    """Preserve the foreign HWND instead of giving its lifetime to QWindow."""
    def __init__(self, handle, parent):
        self.handle, self.parent = handle, parent
        api = self.api = ctypes.WinDLL("user32", use_last_error=True)
        signatures = {
            "IsWindow": ([wintypes.HWND], wintypes.BOOL),
            "GetParent": ([wintypes.HWND], wintypes.HWND),
            "SetParent": ([wintypes.HWND, wintypes.HWND], wintypes.HWND),
            "GetWindowLongPtrW": ([wintypes.HWND, ctypes.c_int], ctypes.c_ssize_t),
            "SetWindowLongPtrW": ([wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t], ctypes.c_ssize_t),
            "GetWindowRect": ([wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
            "SetWindowPos": ([wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, wintypes.UINT], wintypes.BOOL),
            "ShowWindowAsync": ([wintypes.HWND, ctypes.c_int], wintypes.BOOL),
        }
        for name, (args, result) in signatures.items():
            getattr(api, name).argtypes, getattr(api, name).restype = args, result
        if not api.IsWindow(handle) or not api.IsWindow(parent):
            raise OSError("BLENDER_WINDOW_MISSING")
        self.old_parent = api.GetParent(handle)
        self.old_style = api.GetWindowLongPtrW(handle, -16)
        self.old_extended = api.GetWindowLongPtrW(handle, -20)
        self.old_rect = wintypes.RECT()
        api.GetWindowRect(handle, ctypes.byref(self.old_rect))
        # WS_CHILD with no top-level caption/frame. No Qt foreign-window
        # wrapper can recreate or destroy Blender's native OpenGL window.
        api.SetWindowLongPtrW(handle, -16,
                             (self.old_style & ~0x80CF0000) | 0x46000000)
        api.SetWindowLongPtrW(handle, -20, self.old_extended & ~0x00040000)
        api.SetParent(handle, parent)
        if api.GetParent(handle) != parent:
            self.detach()
            raise OSError("BLENDER_PARENT_FAILED")
        self._geometry = None
        self._shown = None

    def valid(self):
        return bool(self.api.IsWindow(self.handle))

    def geometry(self, rect, ratio):
        values = tuple(round(value * ratio) for value in
                       (rect.x(), rect.y(), rect.width(), rect.height()))
        if values != self._geometry and self.valid():
            self._geometry = values
            # Cross-process move/resize is posted, never a synchronous wait.
            self.api.SetWindowPos(self.handle, None, *values, 0x4000 | 0x0034)

    def visible(self, shown):
        if self.valid() and shown != self._shown:
            self.api.ShowWindowAsync(self.handle, 4 if shown else 0)
            self._shown = shown

    def detach(self):
        if not self.valid():
            return
        self.api.SetParent(self.handle, self.old_parent)
        self.api.SetWindowLongPtrW(self.handle, -16, self.old_style)
        self.api.SetWindowLongPtrW(self.handle, -20, self.old_extended)
        r = self.old_rect
        self.api.SetWindowPos(self.handle, None, r.left, r.top, r.right-r.left, r.bottom-r.top,
                              0x4000 | 0x0034)
        self._shown = None
        self.visible(True)


def _probe(path, owned, launch, recover):
    """Only a bounded daemon worker may call socket or enumerate processes."""
    info = contract.sidecar_call("ping", timeout=0.35)
    if info.get("ok"):
        import psutil
        pid = int(info.get("pid") or 0)
        if not pid:
            # Older sidecars do not report their PID. Match the actual listener.
            try:
                pid = next((c.pid for c in psutil.net_connections(kind="tcp4")
                            if c.laddr.port == contract.SIDECAR_PORT and c.status == "LISTEN"), 0)
            except (OSError, psutil.AccessDenied):
                pid = 0
        if not pid or psutil.Process(pid).name().lower() != "blender.exe":
            return {"up": True, "error": "BLENDER_LISTENER_OWNER_UNKNOWN"}
        if info.get("protocol", 0) < 3:
            # Upgrade our earlier sidecar in place, preserving the scene and
            # process. Its exec frame owns the old registered timer/socket.
            args = psutil.Process(pid).cmdline()
            if any(arg.lower().endswith("gg_blender_sidecar.py") for arg in args):
                upgrade = (
                    "import inspect,runpy\n"
                    "g=inspect.currentframe().f_back.f_globals\n"
                    "p=g.get('_pump')\n"
                    "if p and bpy.app.timers.is_registered(p): bpy.app.timers.unregister(p)\n"
                    "s=g.get('_SERVER')\n"
                    "if s: s.close()\n"
                    f"runpy.run_path({str(contract.SIDECAR_SCRIPT)!r},run_name='gg_blender_sidecar')\n"
                )
                answer = contract.sidecar_call("exec", timeout=5, code=upgrade)
                if not answer.get("ok"):
                    return {"up": True, "error": "BLENDER_SIDECAR_UPGRADE_FAILED"}
        windows = window_ids({pid}, ("blender",), include_hidden=True,
                             include_children=True, main_only=True)
        recovered = False
        if not windows and recover and not info.get("background"):
            # Preserve the live scene when the former Qt wrapper destroyed
            # only its HWND. Recreate a GUI window, never reset scene data.
            answer = contract.sidecar_call("exec", timeout=5, code=
                "if bpy.app.background: raise RuntimeError('Blender GUI required')\n"
                "bpy.ops.wm.window_new()\n")
            recovered = True
            if answer.get("ok"):
                windows = window_ids({pid}, ("blender",), include_hidden=True,
                                     include_children=True, main_only=True)
        return {"up": True, "pid": pid, "windows": windows, "recovered": recovered}
    if owned is not None:
        return {"up": False, "exited": owned.poll() is not None}
    if launch:
        contract.ensure_user_config()
        args = [path, "--enable-event-simulate"]
        if contract.SCENE_BLEND.is_file():
            args.append(str(contract.SCENE_BLEND))
        args += ["--python", str(contract.SIDECAR_SCRIPT), "--window-geometry", "80", "80", "1280", "800"]
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 4
        process = subprocess.Popen(args, env=contract.gui_environment(), startupinfo=startup,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
        return {"up": False, "process": process}
    return {"up": False}


class WindowsBlenderEmbed(QObject):
    def __init__(self, qml_root):
        super().__init__(qml_root)
        self._root, self._hole, self._host = qml_root, None, None
        self._rect = None
        self._native = None
        self._input = None
        self._proc = None
        self._pid = 0
        self._up = False
        self._wanted = False
        self._closed = False
        self._launched = False
        self._recovered = False
        self._error = ""
        self._future = None
        self._next_probe = 0
        self._path = ""
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._tick)

    def running(self):
        # Cached worker results only; no /proc or process scans in QML.
        return self._up or (self._proc is not None and self._proc.poll() is None)

    def attached(self):
        return self._native is not None and self._native.valid()

    def error(self):
        return self._error or (self._input.error() if self._input else "")

    def sidecar_up(self):
        return self._up

    def move_pointer(self, x, y, shape="default"):
        if not self._wanted or self._input is None or self._host is None:
            return False
        return self._input.move(x, y, self._host.devicePixelRatio(), shape=shape)

    def click(self, x, y, button):
        return bool(self._wanted and self._input and self._host and
                    self._input.click(x, y, self._host.devicePixelRatio(), button))

    def key(self, key):
        return bool(self._native and self._input and self._wanted and
                    self._input.keyboard_owned(self._native.handle) and self._input.key(key))

    def char(self, char):
        return bool(self._native and self._input and self._wanted and
                    self._input.keyboard_owned(self._native.handle) and self._input.char(char))

    def set_hole_rect(self, x, y, width, height):
        self._rect = QRect(round(x), round(y), max(16, round(width)), max(16, round(height)))
        self._sync_geometry()

    def start(self, wayland_socket=""):
        if self._closed:
            return False
        self._path = self._path or contract.blender_bin()
        if not self._path:
            self._error = "BLENDER_BIN_MISSING"
            return False
        self._wanted = True
        self._timer.start()
        self._tick()
        return True

    def show(self):
        self.start()

    def hide(self):
        self._wanted = False
        if self._input is not None:
            self._input.hide_cursor()
        if self._future is None:
            self._timer.stop()
        if self._native:
            self._native.visible(False)

    def stop(self):
        self._closed = True
        self.hide()
        self._timer.stop()
        if self._input is not None:
            self._input.close()
        if self._native:
            # Detach before Qt destroys its parent. Keep the Blender scene.
            self._native.detach()
            self._native = None
        if self._host is not None:
            self._host.removeEventFilter(self)
            self._host = None

    def eventFilter(self, watched, event):
        if watched is self._host and event.type() == QEvent.Type.Close:
            self.stop()
        return False

    def _sync_geometry(self):
        if self._native is None:
            return
        self._hole = cached_quick_item(self._root, "workspaceExternalHole", self._hole)
        if self._hole is None or self._hole.window() is None:
            self._native.visible(False)
            return
        shown = self._wanted and self._hole.isVisible() and self._hole.window().isVisible()
        if shown:
            point = self._hole.mapToScene(QPointF())
            rect = QRect(round(point.x()), round(point.y()), round(self._hole.width()), round(self._hole.height()))
            self._rect = rect
            if self._input is not None:
                self._input.set_region(rect.x(), rect.y(), rect.width(), rect.height(),
                                       self._hole.window().devicePixelRatio())
            self._native.geometry(rect, self._hole.window().devicePixelRatio())
        self._native.visible(shown)

    def _tick(self):
        if self._closed:
            return
        if self._future is not None and self._future.done():
            future, self._future = self._future, None
            try:
                result = future.result()
                self._up = result.get("up", False)
                self._proc = result.get("process", self._proc)
                self._recovered |= result.get("recovered", False)
                self._pid = result.get("pid", self._pid)
                if result.get("exited"):
                    self._error = "BLENDER_EXITED"
                elif result.get("error"):
                    self._error = result["error"]
                elif result.get("windows") and not self.attached():
                    self._hole = cached_quick_item(self._root, "workspaceExternalHole", self._hole)
                    if self._hole is not None and self._hole.window() is not None:
                        self._host = self._hole.window()
                        self._native = NativeBlenderWindow(result["windows"][0], int(self._host.winId()))
                        from backend.windows_input import WindowInput
                        self._input = WindowInput(int(self._host.winId()), target_pid=self._pid)
                        self._host.installEventFilter(self)
                        self._error = ""
                elif self._up and not self.attached():
                    self._error = "BLENDER_WINDOW_UNAVAILABLE"
            except Exception as exc:
                self._error = "BLENDER_CONNECT_FAILED:" + type(exc).__name__
            self._next_probe = time.monotonic() + (1.5 if self.attached() else 0.4)
        self._sync_geometry()
        if not self._wanted and self._future is None:
            self._timer.stop()
        if not self._wanted or self._future is not None or time.monotonic() < self._next_probe:
            return
        future = self._future = Future()
        launch = not self._launched
        self._launched = True
        owned, path, recover = self._proc, self._path, not self._recovered
        def work():
            try:
                future.set_result(_probe(path, owned, launch, recover))
            except Exception as exc:
                future.set_exception(exc)
        threading.Thread(target=work, name="GG-Blender-probe", daemon=True).start()
