"""Real Blender in an isolated EXT window and private sidecar port/profile."""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@unittest.skipUnless(os.name == "nt" and os.environ.get("GG_TEST_BLENDER_LIVE") == "1",
                     "Explicit GUI test only after the requested desktop restart")
class WindowsBlenderLiveTests(unittest.TestCase):
    def test_ext_and_mcp_share_one_responsive_blender(self):
        from backend.blender_contract import blender_bin
        from backend.platform_process import run_bounded
        binary = blender_bin()
        if not binary:
            self.skipTest("Blender is not installed")
        with socket.socket() as address:
            address.bind(("127.0.0.1", 0))
            port = address.getsockname()[1]
        with tempfile.TemporaryDirectory(prefix="gg-ext-live-", ignore_cleanup_errors=True) as folder:
            env = {"GG_DESKTOP_STATE_ROOT": str(Path(folder) / "state"),
                   "GG_DESKTOP_DATA_ROOT": str(Path(folder) / "data"),
                   "GG_BLENDER_SIDECAR_PORT": str(port), "GG_BLENDER": binary,
                   "GG_EXT_LIVE_FIXTURE": folder, "QT_QPA_PLATFORM": "windows",
                   "GG_EXT_LIVE_HOLD": os.environ.get("GG_EXT_LIVE_HOLD", "0"),
                   "QT_QUICK_CONTROLS_STYLE": "Basic", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
            code, out, err, reason = run_bounded(
                [sys.executable, "-X", "utf8", "-B", str(Path(__file__).resolve()), "--probe"],
                cwd=ROOT, env=env, timeout=75, max_output_bytes=96*1024)
            details = (out + b"\n" + err).decode("utf-8", "replace")
            self.assertEqual(reason, "NONE", details)
            self.assertEqual(code, 0, details)
            self.assertIn("BLENDER_WINDOWS_LIVE=PASS", details)


def probe():
    import subprocess
    import threading
    import time
    from concurrent.futures import Future
    from PySide6.QtCore import QCoreApplication, QEvent, QTimer, QUrl
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtWidgets import QApplication
    from backend.chat_surface_host import ChatSurfaceHost
    from backend import blender_contract as contract

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
    flags: Qt.Window | Qt.WindowDoesNotAcceptFocus
    x: 100; y: 80; width: 1100; height: 800; visible: true
    property var surfaceHost
    property real deskX: 100
    property real deskY: 100
    property string deskShape: "default"
    property bool deskFromChrome: false
    Rectangle { anchors.fill: parent; color: "#161616" }
    ExternalSurface {
        objectName: "isolatedExt"
        anchors.fill: parent
        anchors.margins: 15; anchors.bottomMargin: 120
        surfaceHost: fixtureWindow.surfaceHost
    }
    TextArea {
        objectName: "fixtureChat"
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        height: 100; placeholderText: "Isolated chat input"
    }
}''', QUrl.fromLocalFile(str(ROOT / ".runtime/windows-port/ext-fixture.qml")))
    window = component.createWithInitialProperties({"surfaceHost": host})
    assert window is not None, [error.toString() for error in component.errors()]
    host._qml_root = window
    pane = window.findChild(QQuickItem, "isolatedExt")
    chat = window.findChild(QQuickItem, "fixtureChat")
    beats = []
    heartbeat = QTimer()
    heartbeat.setInterval(10)
    heartbeat.timeout.connect(lambda: beats.append(time.monotonic()))
    heartbeat.start()

    def pump(seconds=0.02):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            app.processEvents()
            time.sleep(0.001)

    def wait(condition, timeout=12):
        end = time.monotonic() + timeout
        while not condition() and time.monotonic() < end:
            pump()
        assert condition(), ("Timed out", host._external_embed.error() if host._external_embed else None, warnings[-5:])

    def background(call):
        future = Future()
        def work():
            try:
                future.set_result(call())
            except Exception as exc:
                future.set_exception(exc)
        threading.Thread(target=work, daemon=True).start()
        wait(future.done, 15)
        return future.result()

    def sidecar(command, **fields):
        result = background(lambda: contract.sidecar_call(command, **fields))
        assert result.get("ok"), result
        return result

    def cli(entry, *arguments):
        result = background(lambda: subprocess.run([sys.executable, "-X", "utf8", "-B", str(ROOT / entry), *arguments],
                                cwd=ROOT, capture_output=True, timeout=12))
        assert result.returncode == 0, (result.stdout.decode(), result.stderr.decode())
        return json.loads(result.stdout)

    owned = None
    try:
        assert host.externalStart("blender", "")
        embed = host._external_embed
        wait(lambda: embed.attached() and embed.sidecar_up(), 30)
        owned = embed._proc
        assert owned is not None, "Fixture must own its isolated Blender"
        ping = sidecar("ping")
        assert ping["pid"] == owned.pid and ping["protocol"] == 3 and ping["agent_input"], ping
        assert embed._native.api.GetParent(embed._native.handle) == int(window.winId())
        # A slow/partial client must not stop Blender from serving another.
        partial = socket.create_connection((contract.SIDECAR_HOST, contract.SIDECAR_PORT), 2)
        partial.sendall(b'{"cmd":')
        begin = time.monotonic()
        sidecar("ping")
        assert time.monotonic() - begin < 1, "Partial client blocked Blender"
        partial.close()
        requests = [
            {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}},
            {"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"exec","arguments":{"code":
                "o=bpy.data.objects.new('GG_EXT_LINK_CHECK',None);bpy.context.scene.collection.objects.link(o);print('MCP_LINK_OK')"}}},
        ]
        result = background(lambda: subprocess.run([sys.executable, "-B", str(ROOT / "gg-blender"), "mcp"],
            input="".join(json.dumps(request)+"\n" for request in requests).encode(),capture_output=True,timeout=8,cwd=ROOT))
        replies = [json.loads(line) for line in result.stdout.splitlines()]
        assert result.returncode == 0 and not replies[-1]["result"].get("isError"), (replies,result.stderr.decode())
        assert "GG_EXT_LINK_CHECK" in {o["name"] for o in cli("gg-blender", "scene")["objects"]}
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32")
        user32.GetForegroundWindow.restype = wintypes.HWND
        foreground = user32.GetForegroundWindow()
        hold = min(25, max(0, int(os.environ.get("GG_EXT_LIVE_HOLD", "0"))))
        # Test input coordinates come from Blender's actual editor layout.
        layout = sidecar("exec", code="import json;print(json.dumps({'height':bpy.context.window.height,'areas':[{'type':a.type,'x':a.x,'y':a.y,'w':a.width,'h':a.height} for a in bpy.context.screen.areas]}))")
        layout = json.loads(layout["stdout"])
        area = next(area for area in layout["areas"] if area["type"] == "VIEW_3D")
        ratio = window.devicePixelRatio()
        x = embed._rect.x() + (area["x"] + area["w"] / 2) / ratio
        y = embed._rect.y() + (layout["height"] - area["y"] - area["h"] / 2) / ratio
        sidecar("exec", code="bpy.ops.object.select_all(action='DESELECT');o=bpy.data.objects['Cube'];o.select_set(True);bpy.context.view_layer.objects.active=o")
        host._arm_desktop_operator()
        cli("gg-desk", "click", "--x", str(round(x)), "--y", str(round(y)))
        wait(lambda: embed._input.pending()==0)
        if hold:
            # Visible inspection of GG's own cursor; no focus or device use.
            native_api=embed._native.api
            native_api.SetWindowPos(int(window.winId()),None,0,0,0,0,0x0013)
            print("VISUAL_READY", flush=True)
            pump(hold)
        cli("gg-desk", "key", "Tab")
        wait(lambda: embed._input.pending()==0)
        pump(0.25)
        state = sidecar("scene")
        if state["mode"] != "EDIT_MESH":
            detail = sidecar("exec", code="print(bpy.data.objects['Cube'].mode,bpy.context.mode,bpy.context.active_object, bpy.context.area)")
            print("INPUT_DIAGNOSTIC", detail, flush=True)
        assert state["mode"] == "EDIT_MESH", ("Native mouse/key did not reach Blender",state,
            embed._input.active(),embed._input.keyboard_owned(embed._native.handle),x,y,layout)
        cli("gg-desk", "key", "Tab")
        wait(lambda: embed._input.pending()==0)
        pump(0.1)
        assert sidecar("scene")["mode"] == "OBJECT"
        assert user32.GetForegroundWindow()==foreground, "GG agent input changed the user's foreground window"
        assert chat.property("text")=="", "Blender agent keys leaked into the chat"
        original_pid = owned.pid
        pane.setVisible(False)
        pump(0.1)
        pane.setVisible(True)
        pump(0.25)
        assert host._external_embed._pid == original_pid
        assert "GG_EXT_LINK_CHECK" in {o["name"] for o in sidecar("scene")["objects"]}
        window.resize(1240, 880)
        pump(0.2)
        r = embed._native.old_rect.__class__()
        embed._native.api.GetWindowRect(embed._native.handle, __import__('ctypes').byref(r))
        assert abs((r.right-r.left) - round(embed._rect.width()*ratio)) <= 2
        handle = embed._native.handle
        native_api = embed._native.api
        embed.stop()
        pump(0.1)
        assert native_api.IsWindow(handle) and not native_api.GetParent(handle), "Detaching destroyed Blender's window"
        assert sidecar("ping")["pid"] == original_pid
        gaps = [b-a for a,b in zip(beats, beats[1:])]
        assert max(gaps) < 0.35, ("Qt UI stalled", max(gaps))
        assert not warnings, warnings
        report={"mcp_stdio":"PASS","cli":"PASS","gg_agent_mouse_keyboard":"PASS","user_focus_preserved":"PASS",
                "partial_client":"PASS","same_process_after_tab_switch":"PASS","resize":"PASS",
                "detach_preserves_blender":"PASS","max_ui_gap_ms":round(max(gaps)*1000,1)}
        report_path=ROOT/".runtime/windows-port/blender-ext-virtual-input.json"
        report_path.parent.mkdir(parents=True,exist_ok=True)
        report_path.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
        print("BLENDER_WINDOWS_LIVE=PASS",json.dumps(report),flush=True)
    finally:
        heartbeat.stop()
        if owned is None and host._external_embed is not None:
            owned = host._external_embed._proc
        host.shutdown()
        window.close()
        if owned is not None and owned.poll() is None:
            owned.terminate()
            try:
                owned.wait(timeout=5)
            except subprocess.TimeoutExpired:
                owned.kill()
                owned.wait(timeout=5)
        from shiboken6 import delete
        delete(engine)
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)


if __name__ == "__main__":
    if "--probe" in sys.argv:
        probe()
    else:
        unittest.main()
