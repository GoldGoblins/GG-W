#!/usr/bin/env python3
"""Show the real desktop window before loading its backend modules."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

# EXT hosts Blender as a native child of this window, so the desktop uses
# X11/XWayland rather than a Tool overlay.
if sys.platform.startswith("linux"):
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
if sys.platform == "win32":
    # The desktop supplies its own controls; the native Windows style does
    # not support their custom content/background delegates.
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--disable-extensions --disable-background-networking --disable-sync "
    "--ignore-gpu-blocklist --enable-webgl --enable-webgl2 "
    "--enable-unsafe-swiftshader --renderer-process-limit=4",
)

try:
    from PySide6.QtCore import QEvent, QObject, QTimer, QUrl, Qt
    from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    # Register concrete window/item wrappers before QML creates them. Loading
    # QtQuick later for the game canvas can invalidate retained QWindow wrappers.
    from PySide6.QtQuick import QQuickWindow
    from PySide6.QtWidgets import QApplication
except Exception:
    print(
        "FAIL: PySide6/Qt missing. Install the desktop dependencies with "
        "python -m pip install -r requirements.txt",
        file=sys.stderr,
    )
    raise SystemExit(2)

PROJECT = Path(__file__).resolve().parent
QML_PATH = PROJECT / "qml" / "Main.qml"
SHUTDOWN_TIMEOUT_S = 15.0
SHUTDOWN_TIMEOUT_EXIT_CODE = 70


class DesktopShutdownGuard(QObject):
    """Bound process exit after the user has closed the desktop.

    Qt quit callbacks and Python executor joins can both block indefinitely.
    A Qt timer cannot cover either case, so a daemon watchdog stays armed
    through QML destruction and interpreter finalization. Normal shutdown
    still runs first; the fallback exits only this desktop process.
    """

    def __init__(self, app: QApplication, timeout_s: float) -> None:
        super().__init__(app)
        self._app = app
        self._window: QObject | None = None
        self._timeout_s = timeout_s
        self._armed = False
        # lastWindowClosed runs before aboutToQuit, including when backend
        # quit handlers were connected before run_event_loop was entered.
        app.lastWindowClosed.connect(self.arm)
        app.aboutToQuit.connect(self.arm)

    def watch_window(self, window: QObject) -> None:
        if self._window is window:
            return
        if self._window is not None:
            self._window.removeEventFilter(self)
        self._window = window
        window.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._window and event.type() == QEvent.Type.Close:
            # Check after QML onClosing has accepted or rejected the event.
            # A primary close must also quit when a tool window remains open.
            QTimer.singleShot(0, self._finish_window_close)
        return False

    def _finish_window_close(self) -> None:
        from shiboken6 import isValid

        window = self._window
        if window is not None and isValid(window) and window.isVisible():
            return
        self.arm()
        self._app.quit()

    def arm(self) -> None:
        if self._armed:
            return
        self._armed = True
        # Do not cancel when app.exec returns: non-daemon executor workers
        # can otherwise retain the process during Python's shutdown joins.
        threading.Thread(
            target=self._enforce_deadline,
            name="gg-shutdown-watchdog",
            daemon=True,
        ).start()

    def _enforce_deadline(self) -> None:
        threading.Event().wait(self._timeout_s)
        try:
            os.write(2, b"GG desktop shutdown timed out; exiting this process.\n")
        except OSError:
            pass
        os._exit(SHUTDOWN_TIMEOUT_EXIT_CODE)


def install_shutdown_guard(
    app: QApplication,
    window: QObject | None = None,
    *,
    timeout_s: float = SHUTDOWN_TIMEOUT_S,
) -> DesktopShutdownGuard:
    guard = getattr(app, "_gg_shutdown_guard", None)
    if guard is None:
        guard = DesktopShutdownGuard(app, timeout_s)
        app._gg_shutdown_guard = guard  # type: ignore[attr-defined]
    if window is not None:
        guard.watch_window(window)
    return guard


class FirstFrameBootstrap(QObject):
    """Import backend code only after the integrated loading screen paints."""

    def __init__(
        self,
        root: QObject,
        app: QApplication,
        engine: QQmlApplicationEngine,
    ) -> None:
        super().__init__(app)
        self._root = root
        self._app = app
        self._engine = engine
        self._frame_swapped = None
        self._started = False
        # Connect before importing services with aboutToQuit cleanup slots.
        install_shutdown_guard(app, root)

    def start(self) -> None:
        frame_swapped = getattr(self._root, "frameSwapped", None)
        if frame_swapped is None:
            self._show_failure("Qt did not expose the desktop render signal")
            return
        try:
            frame_swapped.connect(
                self._on_first_frame,
                Qt.ConnectionType.QueuedConnection,
            )
            self._frame_swapped = frame_swapped
        except (AttributeError, TypeError, RuntimeError) as exc:
            self._show_failure(
                "Could not connect the desktop render signal: " + str(exc)
            )
            return

        self._root.showMaximized()

    def _on_first_frame(self) -> None:
        if self._started:
            return
        self._started = True
        if self._frame_swapped is not None:
            try:
                self._frame_swapped.disconnect(self._on_first_frame)
            except (AttributeError, TypeError, RuntimeError):
                pass
            self._frame_swapped = None
        QTimer.singleShot(0, self._load_backend)

    def _load_backend(self) -> None:
        try:
            project_path = str(PROJECT)
            if project_path not in sys.path:
                sys.path.insert(0, project_path)
            import main as desktop_main

            desktop_main.initialize_loaded_window(self._root, self._app)
        except Exception as exc:
            self._show_failure(type(exc).__name__ + ": " + str(exc))

    def _show_failure(self, reason: str) -> None:
        self._root.setProperty("shellLoadLabel", "STARTUP FAILED")
        self._root.setProperty("shellLoadCurrent", reason)
        self._root.setProperty("shellLoading", True)
        append_log = getattr(self._root, "appendShellLog", None)
        if callable(append_log):
            append_log("startup · " + reason)
        print("GG AI Desktop startup failed: " + reason, file=sys.stderr)


def run_event_loop(app: QApplication, engine: QQmlApplicationEngine) -> int:
    """Release QML while its Python bridges and native libraries still exist."""
    from shiboken6 import delete, isValid

    roots = engine.rootObjects()
    install_shutdown_guard(app, roots[0] if roots else None)
    try:
        return app.exec()
    finally:
        if isValid(engine):
            delete(engine)


def launch(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv if argv is None else argv)
    QGuiApplication.setDesktopFileName("org.goldgoblins.gg-ai-desktop")
    QGuiApplication.setApplicationName("GG AI Desktop")
    QGuiApplication.setApplicationDisplayName("GG AI Desktop")

    from backend.native_webview import initialize_native_webview
    initialize_native_webview()
    app = QApplication(arguments)
    if os.name == "nt":
        fonts = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts"
        for name in ("consola.ttf", "consolab.ttf", "consolai.ttf", "consolaz.ttf"):
            if (fonts / name).is_file():
                QFontDatabase.addApplicationFont(str(fonts / name))
        QFont.insertSubstitution("monospace", "Consolas")
    desk_font = QFont("Consolas" if os.name == "nt" else "monospace")
    desk_font.setStyleHint(QFont.StyleHint.Monospace)
    app.setFont(desk_font)

    engine = QQmlApplicationEngine()
    engine.load(QUrl.fromLocalFile(str(QML_PATH)))
    roots = engine.rootObjects()
    if not roots:
        print(
            "GG AI Desktop startup failed: Main.qml did not create a window",
            file=sys.stderr,
        )
        return 2

    root = roots[0]
    bootstrap = FirstFrameBootstrap(root, app, engine)
    app._gg_qml_engine = engine  # type: ignore[attr-defined]
    app._gg_startup_bootstrap = bootstrap  # type: ignore[attr-defined]
    bootstrap.start()
    return run_event_loop(app, engine)


if __name__ == "__main__":
    raise SystemExit(launch())
