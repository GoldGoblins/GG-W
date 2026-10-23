"""Native WebView2 item with the original uBlock Origin extension.

No debug socket, page host objects, synchronous waits, or browser profile scans.
The native library queues bounded events; Qt consumes them on its GUI thread.
"""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import re
import time

from PySide6.QtCore import Property, QCoreApplication, QEvent, QPointF, QTimer, QUrl, Signal, Slot
from PySide6.QtQml import QJSValue, qmlEngine, qmlRegisterType
from PySide6.QtQuick import QQuickItem

from backend.application_paths import PROJECT_ROOT, STATE_ROOT

LIBRARY_PATH = Path(os.environ.get("GG_WEBVIEW_LIBRARY", PROJECT_ROOT / "backend/native/windows-x86_64/gg_webview.dll"))
_library = None
_registered = False
_extension_ids: set[str] = set()
_focus_api = None


def _return_window_keyboard(window) -> None:
    """Give Qt its HWND back after a user selects a control outside WebView2."""
    global _focus_api
    if _focus_api is None:
        api = ctypes.WinDLL("user32", use_last_error=True)
        api.GetFocus.argtypes, api.GetFocus.restype = [], ctypes.c_void_p
        api.IsChild.argtypes, api.IsChild.restype = [ctypes.c_void_p, ctypes.c_void_p], ctypes.c_int
        api.SetFocus.argtypes, api.SetFocus.restype = [ctypes.c_void_p], ctypes.c_void_p
        _focus_api = api
    focused = _focus_api.GetFocus()
    parent = int(window.winId())
    # Stay within this window and the owning GUI thread. Do not activate a
    # background app or interfere with a native control in another window.
    if focused and focused != parent and _focus_api.IsChild(parent, focused):
        _focus_api.SetFocus(parent)


def extension_directory() -> Path | None:
    override = os.environ.get("GG_WEB_BLOCKER_PATH")
    if override:
        path = Path(override)
    else:
        try:
            info = json.loads((STATE_ROOT / "web-extensions/install.json").read_text(encoding="utf-8"))
            path = Path(info["directory"])
            if not path.resolve().is_relative_to((STATE_ROOT / "web-extensions").resolve()):
                return None
        except (OSError, ValueError, KeyError, TypeError):
            return None
    try:
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("name") == "uBlock Origin" and manifest.get("manifest_version") == 2:
            return path.resolve()
    except (OSError, ValueError, TypeError):
        pass
    return None


def available() -> bool:
    return os.name == "nt" and LIBRARY_PATH.is_file() and extension_directory() is not None


def extension_url_allowed(url: str) -> bool:
    parsed = QUrl(url)
    if parsed.scheme() != "chrome-extension":
        return False
    if parsed.host() in _extension_ids:
        return True
    try:
        info = json.loads((STATE_ROOT / "web-extensions/install.json").read_text(encoding="utf-8"))
        saved = info.get("extension_id", "")
        return bool(re.fullmatch("[a-p]{32}", saved)) and parsed.host() == saved
    except (OSError, ValueError, TypeError):
        return False


def library():
    global _library
    if _library is not None:
        return _library
    # CDLL keeps the GIL released during native calls; all calls still originate
    # on the owning Qt GUI thread. The browser itself runs out of process.
    lib = ctypes.CDLL(str(LIBRARY_PATH))
    u64, wide, integer = ctypes.c_uint64, ctypes.c_wchar_p, ctypes.c_int
    signatures = {
        "create": ([u64, wide, wide], u64),
        "destroy": ([u64], None),
        "bounds": ([u64, integer, integer, integer, integer], None),
        "show": ([u64, integer], None),
        "navigate": ([u64, wide], integer),
        "command": ([u64, integer], integer),
        "eval": ([u64, u64, wide], integer),
        "devtools": ([u64, u64, wide, wide, wide], integer),
        "poll": ([u64, ctypes.c_void_p, ctypes.c_uint], ctypes.c_uint),
    }
    for name, (args, result) in signatures.items():
        method = getattr(lib, "ggwv_" + name)
        method.argtypes, method.restype = args, result
    _library = lib
    return lib


def _release(token: list[int]) -> None:
    if token[0] and _library is not None:
        _library.ggwv_destroy(token[0])
        token[0] = 0


class WindowsFilteredWebView(QQuickItem):
    urlChanged = Signal()
    titleChanged = Signal()
    loadingStateChanged = Signal()
    historyChanged = Signal()
    loadingChanged = Signal("QVariant")
    newWindowRequested = Signal(str)
    blockerChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._token = [0]
        self._url = QUrl()
        self._title = ""
        self._loading = False
        self._history = (False, False)
        self._ready = False
        self._enabled = True
        self._error = ""
        self._extension_id = ""
        self._session = ""
        self._sequence = 0
        self._callbacks: dict[int, tuple[float, object]] = {}
        self._geometry = None
        self._shown = None
        self._focus_window = None
        self._deadline = time.monotonic() + 30
        self._checking = False
        self._closed = False
        self._buffer = ctypes.create_string_buffer(65536)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(150)
        self._refresh_timer.timeout.connect(self._read_blocker_state)
        self.windowChanged.connect(self._window_changed)
        self.visibleChanged.connect(self._sync_geometry)
        token = self._token
        self.destroyed.connect(lambda: _release(token))
        app = QCoreApplication.instance()
        if app:
            app.aboutToQuit.connect(self.close)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._pump)
        self._timer.start()

    @Property(QUrl, notify=urlChanged)
    def url(self):
        return self._url

    @url.setter
    def url(self, value):
        value = QUrl(value)
        if value == self._url:
            return
        self._url = value
        self.urlChanged.emit()
        if self._ready:
            self._navigate()

    @Property(str, notify=titleChanged)
    def title(self):
        return self._title

    @Property(bool, notify=loadingStateChanged)
    def loading(self):
        return self._loading

    @Property(bool, notify=historyChanged)
    def canGoBack(self):
        return self._history[0]

    @Property(bool, notify=historyChanged)
    def canGoForward(self):
        return self._history[1]

    @Property(bool, notify=blockerChanged)
    def blockerReady(self):
        return self._ready

    @Property(bool, notify=blockerChanged)
    def blockerEnabled(self):
        return self._enabled

    @Property(str, notify=blockerChanged)
    def blockerError(self):
        return self._error

    @Property(str, notify=blockerChanged)
    def extensionId(self):
        return self._extension_id

    def geometryChange(self, new, old):
        super().geometryChange(new, old)
        self._sync_geometry()

    def _window_changed(self, window):
        self._watch_focus(window)
        if self._token[0]:
            _release(self._token)
        self._geometry, self._shown = None, None
        if window:
            window.visibleChanged.connect(self._sync_geometry)
            QTimer.singleShot(0, self._ensure_view)

    def _watch_focus(self, window):
        if self._focus_window is not None:
            self._focus_window.removeEventFilter(self)
        self._focus_window = window
        if window is not None:
            window.installEventFilter(self)

    def _return_keyboard(self):
        if not self._closed and self._token[0] and self._focus_window is not None:
            _return_window_keyboard(self._focus_window)

    def eventFilter(self, watched, event):
        if watched is self._focus_window and event.type() in (
                QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick, QEvent.Type.TouchBegin):
            # Native child clicks go straight to WebView2. Events delivered to
            # Qt belong to its controls, including an already-focused chat.
            # QML focus alone cannot move Windows focus out of the child HWND.
            self._return_keyboard()
        return False

    def _ensure_view(self):
        if self._closed or self._token[0] or self._error:
            return
        window = self.window()
        if not window or not window.isVisible():
            return
        directory = extension_directory()
        if directory is None:
            self._fail("uBlock Origin is not installed")
            return
        profile = STATE_ROOT / "webview2-profile"
        profile.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._token[0] = library().ggwv_create(int(window.winId()), str(profile), str(directory))
        if not self._token[0]:
            self._fail("The native browser could not start")
            return
        self._deadline = time.monotonic() + 30
        self._sync_geometry()

    def _sync_geometry(self):
        if not self._token[0] or self._closed:
            return
        window = self.window()
        if not window:
            return
        position = self.mapToScene(QPointF())
        ratio = window.devicePixelRatio()
        geometry = tuple(round(number * ratio) for number in (position.x(), position.y(), self.width(), self.height()))
        if geometry != self._geometry:
            library().ggwv_bounds(self._token[0], *geometry)
            self._geometry = geometry
        visible = self.isVisible() and window.isVisible() and self.width() > 0 and self.height() > 0
        if visible != self._shown:
            library().ggwv_show(self._token[0], int(visible))
            self._shown = visible

    def _fail(self, message):
        self._error = message
        self._loading = False
        self._ready = False
        self.blockerChanged.emit()
        self.loadingStateChanged.emit()
        self.loadingChanged.emit({"status": 3, "url": self._url.toString(), "errorString": message})
        callbacks, self._callbacks = self._callbacks, {}
        for _, callback in callbacks.values():
            callback(None)

    def _pump(self):
        if self._closed:
            return
        self._ensure_view()
        if not self._token[0]:
            return
        self._sync_geometry()
        lib = library()
        for _ in range(32):
            size = lib.ggwv_poll(self._token[0], self._buffer, len(self._buffer))
            if not size:
                break
            if size > len(self._buffer):
                if size > 2 * 1024 * 1024:
                    self._fail("Browser result exceeded its limit")
                    break
                self._buffer = ctypes.create_string_buffer(size)
                lib.ggwv_poll(self._token[0], self._buffer, len(self._buffer))
            try:
                self._event(json.loads(self._buffer.value))
            except (ValueError, UnicodeError):
                self._fail("Invalid browser result")
                break
        now = time.monotonic()
        expired = [key for key, (deadline, _) in self._callbacks.items() if now >= deadline]
        for key in expired:
            entry = self._callbacks.pop(key, None)
            if entry:
                entry[1](None)
        if not self._ready and not self._error and now >= self._deadline:
            self._fail("uBlock Origin did not become ready in time")

    def _event(self, event):
        kind = event.get("type")
        if kind in ("script", "devtools"):
            entry = self._callbacks.pop(event.get("request"), None)
            if entry:
                entry[1](event.get("result") if event.get("ok") else None)
        elif kind == "ready":
            self._extension_id = str(event["extensionId"])
            _extension_ids.add(self._extension_id)
            install_file = STATE_ROOT / "web-extensions/install.json"
            try:
                info = json.loads(install_file.read_text(encoding="utf-8"))
                if info.get("extension_id") != self._extension_id:
                    info["extension_id"] = self._extension_id
                    temporary = install_file.with_suffix(".tmp")
                    temporary.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
                    temporary.replace(install_file)
            except (OSError, ValueError, TypeError):
                pass
            self._check_background()
        elif kind == "url":
            value = QUrl(event["url"])
            if value != self._url:
                self._url = value
                self.urlChanged.emit()
            if self._ready:
                self._refresh_blocker()
        elif kind == "title":
            self._title = event["title"]
            self.titleChanged.emit()
        elif kind == "history":
            self._history = (event["back"], event["forward"])
            self.historyChanged.emit()
        elif kind == "load":
            self._loading = event["status"] == 0
            self.loadingStateChanged.emit()
            self.loadingChanged.emit({"status": event["status"], "url": event.get("url", self._url.toString())})
        elif kind == "newtab":
            self.newWindowRequested.emit(event["url"])
        elif kind == "blocked":
            self.loadingChanged.emit({"status": 3, "url": self._url.toString(), "errorString": "Blocked URL"})
        elif kind in ("error", "fatal"):
            message = event.get("message") or ("Browser " + event.get("stage", "error") + " failed (" + str(event.get("code")) + ")")
            self._fail(message)

    def devtools(self, method, parameters, callback, *, session=""):
        self._sequence += 1
        request = self._sequence
        if len(self._callbacks) >= 128 or not self._token[0]:
            callback(None)
            return
        self._callbacks[request] = (time.monotonic() + 8, callback)
        ok = library().ggwv_devtools(self._token[0], request, method, json.dumps(parameters), session)
        if not ok:
            self._callbacks.pop(request, None)
            callback(None)

    def _background(self, expression, callback):
        script = "(async()=>{const u=(await import(chrome.runtime.getURL('js/background.js'))).default;return (" + expression + ");})()"
        self.devtools("Runtime.evaluate", {"expression": script, "awaitPromise": True, "returnByValue": True},
                      lambda result: callback(result.get("result", {}).get("value") if isinstance(result, dict) else None),
                      session=self._session)

    def _check_background(self):
        if self._checking or self._closed or self._error:
            return
        self._checking = True

        def check(result):
            self._checking = False
            if isinstance(result, dict) and result.get("ready"):
                self._ready = True
                self.blockerChanged.emit()
                self._navigate()
            elif time.monotonic() < self._deadline:
                QTimer.singleShot(100, self._check_background)

        if self._session:
            # Importing an internal uBO module before start.js has evaluated can
            # change its module evaluation order. Observe an existing startup
            # marker first; only then read its already initialized module.
            def initialized(result):
                if (result or {}).get("result", {}).get("value") is True:
                    self._background("({ready:u.readyToFilter,css:typeof chrome.tabs.insertCSS})", check)
                else:
                    check(None)

            self.devtools("Runtime.evaluate", {
                "expression": "typeof globalThis.vAPI?.app?.onShutdown === 'function'",
                "returnByValue": True,
            }, initialized, session=self._session)
            return

        def targets(result):
            wanted = "chrome-extension://" + self._extension_id + "/background.html"
            target = next((item for item in (result or {}).get("targetInfos", []) if item.get("url") == wanted), None)
            if not target:
                check(None)
                return

            def attached(result):
                self._session = (result or {}).get("sessionId", "")
                self._checking = False
                if self._session:
                    self._check_background()
                else:
                    QTimer.singleShot(100, self._check_background)

            self.devtools("Target.attachToTarget", {"targetId": target["targetId"], "flatten": True}, attached)

        self.devtools("Target.getTargets", {}, targets)

    def _navigate(self):
        if self._ready and self._url.isValid() and not self._url.isEmpty():
            if not library().ggwv_navigate(self._token[0], self._url.toString()):
                self._fail("Navigation was refused")

    def _refresh_blocker(self):
        self._refresh_timer.start()

    def _read_blocker_state(self):
        if self._closed or not self._ready:
            return
        url = self._url.toString()

        def updated(enabled):
            if isinstance(enabled, bool) and self._url.toString() == url:
                self._enabled = enabled
                self.blockerChanged.emit()

        self._background("u.getNetFilteringSwitch(" + json.dumps(url) + ")", updated)

    @Slot()
    def toggleBlocker(self):
        if not self._ready or self._url.scheme() not in ("http", "https"):
            return
        url = json.dumps(self._url.toString())
        expression = "(u.toggleNetFilteringSwitch(" + url + ",''," + ("false" if self._enabled else "true") + "),u.getNetFilteringSwitch(" + url + "))"

        def toggled(enabled):
            if isinstance(enabled, bool):
                self._enabled = enabled
                self.blockerChanged.emit()
                self.reload()

        self._background(expression, toggled)

    @Slot()
    def openBlockerSettings(self):
        if self._ready:
            self.newWindowRequested.emit("chrome-extension://" + self._extension_id + "/dashboard.html")

    @Slot(str, QJSValue)
    def runJavaScript(self, script, callback):
        if not self._ready or len(script) > 1024 * 1024 or len(self._callbacks) >= 128:
            if callback.isCallable():
                callback.call([QJSValue("")])
            return
        self._sequence += 1
        request = self._sequence

        def done(result):
            engine = qmlEngine(self)
            if callback.isCallable() and engine:
                callback.call([engine.toScriptValue(result if result is not None else "")])

        self._callbacks[request] = (time.monotonic() + 8, done)
        if not library().ggwv_eval(self._token[0], request, script):
            self._callbacks.pop(request, None)
            done(None)

    @Slot()
    def reload(self):
        if self._ready:
            library().ggwv_command(self._token[0], 2)

    @Slot()
    def stop(self):
        if self._token[0]:
            library().ggwv_command(self._token[0], 3)

    @Slot()
    def goBack(self):
        if self._ready:
            library().ggwv_command(self._token[0], 0)

    @Slot()
    def goForward(self):
        if self._ready:
            library().ggwv_command(self._token[0], 1)

    @Slot()
    def close(self):
        if self._closed:
            return
        self._closed = True
        self._watch_focus(None)
        self._timer.stop()
        self._refresh_timer.stop()
        if self._session and self._token[0]:
            # Closing this view automatically releases its DevTools sessions.
            self._session = ""
        self._callbacks.clear()
        _release(self._token)


def register() -> bool:
    global _registered
    if not available():
        return False
    if not _registered:
        qmlRegisterType(WindowsFilteredWebView, "GG.NativeWeb", 1, 0, "GGNativeWebView")
        _registered = True
    return True
