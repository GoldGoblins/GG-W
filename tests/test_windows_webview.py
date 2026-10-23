"""Exercise the complete WEB pane with real Windows video decoding."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@unittest.skipUnless(os.name == "nt", "Native Windows browser integration")
class WindowsWebViewTests(unittest.TestCase):
    def test_native_web_pane_decodes_progressive_and_streamed_video(self):
        from backend.platform_process import run_bounded
        with tempfile.TemporaryDirectory(prefix="gg-native-browser-", ignore_cleanup_errors=True) as temporary:
            env = {"GG_DESKTOP_STATE_ROOT": str(Path(temporary) / "state"),
                   "GG_DESKTOP_DATA_ROOT": str(Path(temporary) / "data"),
                   "GG_USER_CODEX_HOME": str(Path(temporary) / "codex"),
                   "GG_WEBVIEW_TEST_ROOT": temporary, "QT_QPA_PLATFORM": "windows",
                   "QT_QUICK_CONTROLS_STYLE": "Basic",
                   "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
            from backend.windows_webview import available, extension_directory, LIBRARY_PATH
            if available():
                env["GG_WEBVIEW_LIBRARY"] = str(LIBRARY_PATH)
                env["GG_WEB_BLOCKER_PATH"] = str(extension_directory())
            code, out, err, reason = run_bounded(
                [sys.executable, "-X", "utf8", "-B", str(Path(__file__).resolve()), "--native-probe"],
                cwd=ROOT, env=env, timeout=45, max_output_bytes=128*1024)
            details = (out + b"\n" + err).decode("utf-8", "replace")
            self.assertEqual(reason, "NONE", details)
            self.assertEqual(code, 0, details)
            self.assertIn("NATIVE_WEB_VIDEO_TEST=PASS", details)


def native_probe():
    import http.server
    import shutil
    import subprocess
    import threading
    import time
    from urllib.parse import urlparse
    from backend.platform_support import find_executable
    from backend.native_webview import initialize_native_webview

    fixture_root = Path(os.environ["GG_WEBVIEW_TEST_ROOT"])
    ffmpeg = shutil.which("ffmpeg") or find_executable("ffmpeg")
    assert ffmpeg, "FFmpeg is required to generate the original test video"
    clip = fixture_root / "clip.mp4"
    encode = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
        "-t", "3", "-c:v", "libx264", "-profile:v", "baseline", "-level", "3.0",
        "-pix_fmt", "yuv420p", "-g", "30", "-c:a", "aac", "-b:a", "64k",
        "-movflags", "frag_keyframe+empty_moov+default_base_moof", str(clip)],
        capture_output=True, timeout=15)
    assert encode.returncode == 0, encode.stderr.decode("utf-8", "replace")
    media = clip.read_bytes()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/second?redirected=1")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if path == "/clip.mp4":
                data, mime = media, "video/mp4"
            elif path == "/second":
                data, mime = b"<title>Second page</title><p>SECOND PAGE</p>", "text/html"
            else:
                script = ("v.src='/clip.mp4';v.play().catch(e=>window.playError=e.name);"
                          if path != "/mse" else
                          "const m=new MediaSource();v.src=URL.createObjectURL(m);"
                          "m.addEventListener('sourceopen',async()=>{try{"
                          "const s=m.addSourceBuffer('video/mp4; codecs=\"avc1.42E01E,mp4a.40.2\"');"
                          "s.addEventListener('updateend',()=>{m.endOfStream();v.play().catch(e=>window.playError=e.name);},{once:true});"
                          "s.appendBuffer(await(await fetch('/clip.mp4')).arrayBuffer());"
                          "}catch(e){window.playError=e.name+':'+e.message;}});")
                data = ("<!doctype html><title>GG video fixture</title>"
                        "<style>body{background:#181818;color:white}video{width:80%}</style>"
                        "<video id='v' controls muted loop></video>"
                        "<a id='newtab' target='_blank' href='/second'>New tab</a>"
                        "<script>const v=document.getElementById('v');v.muted=true;" + script + "</script>").encode()
                mime = "text/html"
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    servers = [http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler) for _ in range(2)]
    for server in servers:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    initialize_native_webview()
    from PySide6.QtCore import QCoreApplication, QEvent, QUrl
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtWidgets import QApplication
    from backend.chat_surface_host import ChatSurfaceHost

    app = QApplication([])
    host = ChatSurfaceHost()
    engine = QQmlEngine()
    warnings = []
    engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
    component = QQmlComponent(engine)
    component.setData(b'''import QtQuick
import QtQuick.Controls
import QtQuick.Window
import "../../qml/components"
ApplicationWindow {
    id: fixtureWindow
    width: 1100; height: 720; visible: true
    property var surfaceHost: null
    property bool walletOpen: false
    property bool settingsOpen: false
    property bool commandPaletteOpen: false
    property bool shellLoading: false
    property real deskX: 180
    property real deskY: 150
    property alias pane: browserPane
    function setDeskCursor(item, lx, ly, shape) {
        var position = item.mapToItem(fixtureWindow.contentItem, lx, ly)
        deskX = position.x
        deskY = position.y
    }
    Rectangle { anchors.fill: parent; color: "#161616" }
    Loader {
        id: workspaceLoader; objectName: "addressWorkspaceLoader"
        anchors.fill: parent; active: false
        sourceComponent: WorkspaceSurface {}
    }
    WebPane {
        id: browserPane; anchors.fill: parent
        anchors.leftMargin: 180; anchors.rightMargin: 100
        anchors.topMargin: 40; anchors.bottomMargin: 80
        wantEngine: true; pageUrl: "about:blank"
    }
    TextArea {
        objectName: "fixtureChat"
        anchors.left: parent.left; anchors.right: parent.right
        anchors.bottom: parent.bottom; height: 70
        placeholderText: "Chat while video is playing"
    }
}''', QUrl.fromLocalFile(str(ROOT / ".runtime/windows-port/native-fixture.qml")))
    window = component.createWithInitialProperties({"surfaceHost": host})
    assert window is not None, [error.toString() for error in component.errors()]
    host._qml_root = window
    pane = window.findChild(QQuickItem, "webPane")
    if os.environ.get("GG_WEB_BLOCKER_PATH"):
        assert pane.property("blockerAvailable"), "The video regression must use the filtered native engine"
    js_pane = engine.newQObject(pane)

    def pump(seconds=0.02):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            app.processEvents()
            time.sleep(0.001)

    def wait(condition, timeout=8):
        until = time.monotonic() + timeout
        while not condition() and time.monotonic() < until:
            pump()
        assert condition(), ("Timed out", warnings[-5:])

    def evaluate(script):
        js_engine = js_pane.property("liveEngine").callWithInstance(js_pane)
        # A callback created in this QML engine can cross the WebView QJS API.
        evaluator = engine.evaluate("(function(view,script){__ggTestResult=undefined;"
                                    "view.runJavaScript(script,function(r){__ggTestResult=r;});})")
        called = evaluator.call([js_engine, engine.toScriptValue(script)])
        assert not called.isError(), called.toString()
        wait(lambda: not engine.evaluate("__ggTestResult").isUndefined())
        value = engine.evaluate("__ggTestResult").toVariant()
        return json.loads(value) if isinstance(value, str) and value[:1] in ("{", "[") else value

    results = {}
    try:
        wait(lambda: pane.property("loadState") == "PASS")
        capabilities = evaluate('''JSON.stringify({
            h264: document.createElement('video').canPlayType('video/mp4;codecs="avc1.42E01E"'),
            aac: document.createElement('audio').canPlayType('audio/mp4;codecs="mp4a.40.2"'),
            mse: MediaSource.isTypeSupported('video/mp4;codecs="avc1.42E01E,mp4a.40.2"')})''')
        assert capabilities["h264"] and capabilities["aac"] and capabilities["mse"], capabilities
        urls = [f"http://127.0.0.1:{servers[0].server_port}/progressive",
                f"http://127.0.0.1:{servers[0].server_port}/mse",
                f"http://localhost:{servers[1].server_port}/progressive"]
        for index, url in enumerate(urls):
            pane.setProperty("pageUrl", QUrl(url))
            wait(lambda: pane.property("loadState") == "PASS")
            wait(lambda: evaluate("Boolean(document.querySelector('video') && document.querySelector('video').currentTime>0.25)"))
            data = evaluate("JSON.stringify({width:v.videoWidth,height:v.videoHeight,time:v.currentTime,"
                            "frames:v.getVideoPlaybackQuality().totalVideoFrames,error:window.playError||null})")
            assert data["width"] == 160 and data["height"] == 90 and data["frames"] > 1, data
            assert not data["error"], data
            results[str(index)] = data
        current = evaluate("location.href")
        time_origin = evaluate("performance.timeOrigin")
        window.resize(1340, 820)
        window.showMaximized()
        pump(0.25)
        assert evaluate("location.href") == current
        assert evaluate("performance.timeOrigin") == time_origin
        assert evaluate("v.currentTime") > 0
        # A native child must be included in the visible browser screenshot.
        window.raise_()
        window.requestActivate()
        pump(0.1)
        from PySide6.QtCore import QPointF
        if pane.property("blockerAvailable"):
            # QTest.keyClick targets Qt directly and misses an HWND focus trap.
            # Send real Windows input to this isolated fixture instead.
            import ctypes
            from ctypes import wintypes

            class MouseInput(ctypes.Structure):
                _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                            ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                            ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

            class KeyboardInput(ctypes.Structure):
                _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                            ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                            ("dwExtraInfo", ctypes.c_size_t)]

            class InputUnion(ctypes.Union):
                _fields_ = [("mi", MouseInput), ("ki", KeyboardInput)]

            class Input(ctypes.Structure):
                _fields_ = [("type", wintypes.DWORD), ("data", InputUnion)]

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.GetFocus.restype = wintypes.HWND
            user32.GetForegroundWindow.restype = wintypes.HWND
            user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int]
            user32.SendInput.restype = wintypes.UINT
            user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
            user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
            native_window = int(window.winId())

            def send_input(*events):
                assert user32.GetForegroundWindow() == native_window, "Fixture must own foreground input"
                data = (Input * len(events))(*events)
                assert user32.SendInput(len(data), data, ctypes.sizeof(Input)) == len(data)
                pump(0.05)

            def native_click(item, x, y):
                position = item.mapToScene(QPointF(x, y))
                ratio = window.devicePixelRatio()
                point = wintypes.POINT(round(position.x() * ratio), round(position.y() * ratio))
                assert user32.ClientToScreen(native_window, ctypes.byref(point))
                assert user32.SetCursorPos(point.x, point.y)
                send_input(Input(type=0, data=InputUnion(mi=MouseInput(dwFlags=0x0002))),
                           Input(type=0, data=InputUnion(mi=MouseInput(dwFlags=0x0004))))

            def native_key(key):
                send_input(Input(type=1, data=InputUnion(ki=KeyboardInput(wVk=key))),
                           Input(type=1, data=InputUnion(ki=KeyboardInput(wVk=key, dwFlags=2))))

            chat = window.findChild(QQuickItem, "fixtureChat")
            # Model the common case where Qt still remembers chat as active.
            native_click(chat, 20, 20)
            evaluate("window.videoKeys=[];document.addEventListener('keydown',e=>{"
                     "videoKeys.push(e.key);if(e.key==='m'||e.key===' '){"
                     "e.preventDefault();e.stopImmediatePropagation();"
                     "if(e.key==='m')v.muted=!v.muted;else v.paused?v.play():v.pause();}},true);true")
            for _ in range(2):
                chat.setProperty("text", "")
                native_click(pane, 80, 30)
                assert user32.GetFocus() != native_window, "Browser click did not acquire native focus"
                evaluate("v.muted=true;v.play();videoKeys=[];true")
                native_click(chat, 20, 20)
                native_key(0x4D)  # m
                native_key(0x20)  # Space
                native_key(0x4D)
                wait(lambda: chat.property("text") == "m m", 1)
                assert user32.GetFocus() == native_window, "Video retained Windows keyboard focus"
                state = evaluate("({keys:videoKeys,muted:v.muted,paused:v.paused,"
                                 "frames:v.getVideoPlaybackQuality().totalVideoFrames})")
                assert not state["keys"] and state["muted"] and not state["paused"], state
            # Video shortcuts still work after deliberately clicking back in.
            native_click(pane, 80, 30)
            evaluate("v.muted=true;v.play();videoKeys=[];true")
            native_key(0x4D)
            wait(lambda: evaluate("!v.muted"))
            evaluate("v.play();true")
            wait(lambda: evaluate("!v.paused"))
            native_key(0x20)
            wait(lambda: evaluate("v.paused"))
            assert chat.property("text") == "m m"
            evaluate("v.play();true")
            native_click(chat, 20, 20)
            results["video_chat_keyboard_focus"] = "PASS"
        position = pane.mapToScene(QPointF(0, 0))
        capture = host.webCapturePane(round(position.x()), round(position.y()), round(pane.width()), round(pane.height()))
        assert capture, "Native browser screenshot missing"
        from PIL import Image
        import numpy as np
        pixels = np.asarray(Image.open(capture).convert("RGB"))
        Image.open(capture).save(ROOT / ".runtime/windows-port/web-native-preview.png")
        assert ((pixels[:, :, 1] > 150) & (pixels[:, :, 0] < 80) & (pixels[:, :, 2] < 80)).sum() > 100, "Video is absent from the native screenshot"
        # The agent pointer must stay visible over the native child window.
        wait(lambda: evaluate("Boolean(document.getElementById('__ggNativePointer'))"))
        tabs = []
        pane.openNewTab.connect(tabs.append)
        evaluate("document.getElementById('newtab').click();true")
        wait(lambda: len(tabs) == 1)
        assert tabs[0].endswith("/second"), tabs
        # Browser history and normal website storage survive navigation.
        evaluate("document.cookie='gg_fixture=ready;path=/';true")
        evaluate("location.href='/second';true")
        wait(lambda: evaluate("document.title") == "Second page")
        evaluate("history.back();true")
        wait(lambda: evaluate("Boolean(document.querySelector('video'))"))
        assert "gg_fixture=ready" in evaluate("document.cookie")
        assert abs(evaluate("innerWidth") - pane.width()) <= 2, "Native browser DPI/viewport mismatch"
        # Exercise the existing visible operator over the new native view.
        operation = engine.evaluate("(function(pane){__ggOperatorResult=undefined;"
                                    "pane.playOperator({action:'SNAPSHOT'},function(r){__ggOperatorResult=r;});})")
        operation.call([js_pane])
        wait(lambda: not engine.evaluate("__ggOperatorResult").isUndefined())
        observed = engine.evaluate("__ggOperatorResult").toVariant()
        assert observed["ok"] and observed["image"] and observed["title"] == "GG video fixture", observed
        # The browser profile belongs to user state, not the application tree.
        profile = fixture_root / "state/webview2-profile"
        assert profile.is_dir() and any(profile.iterdir()), "Native browser profile location was ignored"
        window.setProperty("commandPaletteOpen", True)
        pump(0.05)
        assert not window.findChild(QQuickItem, "nativeBrowserContent").isVisible()
        window.setProperty("commandPaletteOpen", False)
        pump(0.05)
        assert window.findChild(QQuickItem, "nativeBrowserContent").isVisible()
        pane.setProperty("pageUrl", QUrl("file:///C:/forbidden.html"))
        pump(0.05)
        assert pane.property("loadState") == "BLOCKED"
        assert evaluate("location.href") == current
        # Use the real workspace address field, including a user-typed URL.
        pane.setVisible(False)
        window.findChild(QQuickItem, "addressWorkspaceLoader").setProperty("active", True)
        workspace = window.findChild(QQuickItem, "workspaceSurface")
        js_workspace = engine.newQObject(workspace)

        def workspace_call(name, *args):
            result = js_workspace.property(name).callWithInstance(
                js_workspace, [engine.toScriptValue(arg) for arg in args])
            assert not result.isError(), result.toString()
            return result

        workspace_call("setHostKind", "WEB")
        wait(lambda: workspace.property("liveWebPane") is not None)
        pane = workspace.property("liveWebPane")
        js_pane = engine.newQObject(pane)
        bar = workspace.property("liveBrowseBar")
        wait(lambda: pane.property("loadState") == "PASS")
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        window.requestActivate()
        bar.forceActiveFocus()
        QTest.keyClick(window, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        for character in urls[0]:
            QTest.keyClick(window, character)
        QTest.keyClick(window, Qt.Key.Key_Return)
        wait(lambda: pane.property("loadState") == "PASS")
        wait(lambda: evaluate("Boolean(document.querySelector('video') && v.currentTime>0.1)"))
        origin = evaluate("performance.timeOrigin")
        href = urls[0].rsplit("/", 1)[0] + "/video/item?episode=2#player"
        evaluate("history.pushState({},''," + json.dumps(href) + ");true")
        wait(lambda: bar.property("text") == href)
        assert evaluate("performance.timeOrigin") == origin, "Address sync reloaded the video"
        assert js_pane.property("currentHref").callWithInstance(js_pane).toString() == href
        changed = href.replace("episode=2#player", "episode=3#details")
        evaluate("history.replaceState({},''," + json.dumps(changed) + ");true")
        wait(lambda: bar.property("text") == changed)
        evaluate("history.back();true")
        wait(lambda: bar.property("text") == urls[0])
        evaluate("history.forward();true")
        wait(lambda: bar.property("text") == changed)
        evaluate("location.hash='chapters';true")
        wait(lambda: bar.property("text") == changed.replace("#details", "#chapters"))
        assert evaluate("performance.timeOrigin") == origin, "History sync reloaded the document"
        assert evaluate("v.currentTime") > 0, "History sync interrupted video playback"
        # A typed URL may equal WebView's stale URL after a same-document change.
        workspace_call("goBrowse", urls[0])
        wait(lambda: evaluate("location.href") == urls[0])
        wait(lambda: bar.property("text") == urls[0])
        evaluate("location.href='/second';true")
        second = urls[0].rsplit("/", 1)[0] + "/second"
        wait(lambda: bar.property("text") == second)
        wait(lambda: evaluate("document.title") == "Second page")
        workspace_call("goBrowse", second.replace("/second", "/redirect"))
        wait(lambda: bar.property("text") == second + "?redirected=1")
        wait(lambda: evaluate("location.href") == bar.property("text"))
        results["workspace_address"] = "PASS"
        if pane.property("blockerAvailable"):
            from PySide6.QtCore import QPoint
            wait(lambda: pane.property("blockerReady"))
            toolbar = bar.parentItem()
            button = next((candidate for candidate in toolbar.childItems()
                           if candidate.objectName() == "workspaceWebBlocker"), None)
            assert button and button.isVisible(), ("The active WEB filter switch is missing",
                [(candidate.objectName(), candidate.isVisible()) for candidate in toolbar.childItems()])

            def click_button(button):
                position = button.mapToScene(QPointF(button.width() / 2, button.height() / 2))
                QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                                 QPoint(round(position.x()), round(position.y())))

            click_button(button)
            wait(lambda: not pane.property("blockerEnabled"))
            wait(lambda: button.property("text") == "uBO AV")
            wait(lambda: pane.property("loadState") == "PASS")
            click_button(button)
            wait(lambda: pane.property("blockerEnabled"))
            wait(lambda: button.property("text") == "uBO PÅ")
            # Open the actual extension dashboard through the real WEB toolbar.
            settings = next((candidate for candidate in toolbar.childItems()
                             if candidate.objectName() == "workspaceWebBlockerSettings"), None)
            assert settings, "The active WEB filter settings button is missing"
            click_button(settings)
            wait(lambda: workspace.property("liveWebPane") is not pane)
            pane = workspace.property("liveWebPane")
            js_pane = engine.newQObject(pane)
            wait(lambda: pane.property("loadState") == "PASS", 12)
            assert evaluate("location.href").split("#", 1)[0].endswith("/dashboard.html"), evaluate("location.href")
            assert evaluate("location.protocol") == "chrome-extension:"
            assert "uBlock" in evaluate("document.title")
            results["ublock_toolbar_and_dashboard"] = "PASS"
        results["capabilities"] = capabilities
        results["tabs"] = "PASS"
        results["resize"] = "PASS"
        results["history_and_cookies"] = "PASS"
        results["native_screenshot"] = "PASS"
        results["visible_operator"] = "PASS"
        results["private_profile"] = "PASS"
        results["file_navigation"] = "BLOCKED"
        faults = [message for message in warnings
                  if "Window.window only supports types derived from Item" not in message]
        assert not faults, faults
        (ROOT / ".runtime/windows-port/native-web-video.json").write_text(json.dumps(results, indent=2)+"\n", encoding="utf-8")
        print("NATIVE_WEB_VIDEO_TEST=PASS", json.dumps(results), flush=True)
        hold = min(30, max(0, int(os.environ.get("GG_WEBVIEW_TEST_HOLD", "0"))))
        if hold:
            print("VISUAL_READY", flush=True)
            pump(hold)
    finally:
        host.shutdown()
        window.close()
        from shiboken6 import delete
        delete(engine)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        for server in servers:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    if "--native-probe" in sys.argv:
        native_probe()
    else:
        unittest.main()
