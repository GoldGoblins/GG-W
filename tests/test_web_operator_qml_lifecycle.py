"""Real local browser DOM effects and controlled asynchronous QML completions."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@unittest.skipUnless(os.name == "nt", "Windows browser lifecycle integration")
class WebOperatorQmlLifecycleTests(unittest.TestCase):
    def test_real_dom_effects_and_late_callbacks(self):
        from backend.platform_process import run_bounded
        with tempfile.TemporaryDirectory(prefix="gg-web-qml-lifecycle-", ignore_cleanup_errors=True) as temporary:
            environment = {"GG_WEB_QML_TEST_ROOT": temporary,
                "GG_DESKTOP_STATE_ROOT": str(Path(temporary) / "state"),
                "GG_DESKTOP_DATA_ROOT": str(Path(temporary) / "data"),
                "QT_QPA_PLATFORM": "windows", "QT_QUICK_CONTROLS_STYLE": "Basic", "PYTHONUTF8": "1"}
            code, out, err, reason = run_bounded(
                [sys.executable, "-X", "utf8", "-X", "faulthandler", "-B", str(Path(__file__).resolve()), "--probe"],
                cwd=ROOT, env=environment, timeout=45, max_output_bytes=128 * 1024)
            detail = (out + b"\n" + err).decode("utf-8", "replace")
            self.assertEqual(reason, "NONE", detail)
            self.assertEqual(code, 0, detail)
            self.assertIn("WEB_QML_LIFECYCLE_PASS", detail)


def probe():
    import time
    from backend.native_webview import initialize_native_webview
    initialize_native_webview()
    from PySide6.QtCore import QObject, Property, QUrl, Slot
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtWidgets import QApplication

    app = QApplication([])
    engine = QQmlEngine()
    folder = Path(os.environ["GG_WEB_QML_TEST_ROOT"])
    warnings = []
    engine.warnings.connect(lambda rows: warnings.extend(row.toString() for row in rows))

    class Bridge(QObject):
        nativeWebViewReady = Property(bool, lambda self: False, constant=True)
        @Slot(result=str)
        def webProfilePath(self):
            return str(folder / "profile")
        @Slot(result=str)
        def webOperatorViewPath(self):
            return str(folder / "view.png")

    bridge = Bridge()
    component = QQmlComponent(engine)
    source = '''import QtQuick
import QtQuick.Window
import QtWebEngine
import QtWebView as Native
import "COMPONENTS"
Window {
    id: fixture
    width: 800; height: 600; visible: true
    property var surfaceHost: null
    property alias browser: dom
    property alias proxy: testEngine
    property bool documentReady: false
    property int lateGrabSaves: 0
    function setDeskCursor(item, x, y, shape) {}
    function loadDocument(html) { documentReady=false;dom.loadHtml(html,"about:blank") }
    function documentStarted() { pane.handleEngineLoad(WebEngineView.LoadStartedStatus, testEngine) }
    function releaseScript() { var entry=testEngine.held.shift();testEngine.execute(entry.script,entry.callback) }
    function releaseGrab() {
        var callback=testEngine.heldGrabs.shift()
        callback({saveToFile:function(path){fixture.lateGrabSaves++;return true}})
    }
    Native.WebView {
        id: dom; anchors.fill: parent
        onLoadingChanged: function(request) {
            if (request.status===Native.WebView.LoadSucceededStatus) fixture.documentReady=true
        }
    }
    QtObject {
        id: testEngine
        property alias url: dom.url
        property url currentUrl: dom.url
        property string holdMatch: ""
        property var held: []
        property var heldGrabs: []
        property var deferred: []
        property int callbackDelay: 0
        property bool navigateAfterLocate: false
        function runJavaScript(script, callback) {
            if(holdMatch.length>0&&script.indexOf(holdMatch)>=0) {held.push({script:script,callback:callback});return}
            execute(script,callback)
        }
        function execute(script, callback) {
            dom.runJavaScript(script,function(value){
                if(callbackDelay>0) {deferred.push({script:script,callback:callback,value:value});deferTimer.restart()}
                else deliver(script,callback,value)
            })
        }
        function deliver(script,callback,value) {
            callback(value)
            if(navigateAfterLocate&&script.indexOf('scrollIntoView')>=0) {
                navigateAfterLocate=false
                fixture.documentStarted()
            }
        }
        function grabToImage(callback) {heldGrabs.push(callback)}
    }
    Timer {
        id: deferTimer; interval: testEngine.callbackDelay; repeat: false
        onTriggered: {
            var entry=testEngine.deferred.shift()
            if(entry)testEngine.deliver(entry.script,entry.callback,entry.value)
            if(testEngine.deferred.length>0)restart()
        }
    }
    WebPane { id: pane; anchors.fill: parent; adoptedEngine: testEngine }
}'''.replace("COMPONENTS", QUrl.fromLocalFile(str(ROOT / "qml/components")).toString())
    component.setData(source.encode(), QUrl.fromLocalFile(str(folder / "fixture.qml")))

    def pump(seconds=.015):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            app.processEvents()
            time.sleep(.001)

    def wait(condition, timeout=8):
        until = time.monotonic() + timeout
        while not condition() and time.monotonic() < until:
            pump()
        assert condition(), ("Timed out", warnings[-5:])

    wait(lambda: component.status() != QQmlComponent.Status.Loading)
    window = component.createWithInitialProperties({"surfaceHost": bridge})
    assert window is not None, [error.toString() for error in component.errors()]
    pane = window.findChild(QQuickItem, "webPane")
    js_pane = engine.newQObject(pane)
    js_window = engine.newQObject(window)
    proxy = window.property("proxy")
    js_dom = js_window.property("browser")
    engine.evaluate("var __results={};var __domValue;")

    html = '''<!doctype html><title>Local lifecycle fixture</title>
<form id="form"><button id="go" type="submit">Go</button></form>
<button id="other" type="button">Other</button><input id="q">
<script>window.goCount=0;window.otherCount=0;window.submitCount=0;window.inputCount=0;
go.addEventListener('click',()=>goCount++);
other.addEventListener('click',()=>otherCount++);
form.addEventListener('submit',e=>{e.preventDefault();submitCount++});
q.addEventListener('input',()=>inputCount++);window.ready=true;</script>'''

    def evaluate(script):
        fn = engine.evaluate("(function(view,script){__domValue=undefined;view.runJavaScript(script,function(value){__domValue=value})})")
        fn.call([js_dom, engine.toScriptValue(script)])
        wait(lambda: not engine.evaluate("__domValue").isUndefined())
        return engine.evaluate("__domValue").toVariant()

    def window_call(name, *arguments):
        result = js_window.property(name).callWithInstance(js_window, [engine.toScriptValue(arg) for arg in arguments])
        assert not result.isError(), result.toString()
        return result

    def reset_document():
        window_call("loadDocument", html)
        wait(lambda: window.property("documentReady"))
        assert evaluate("window.ready")
        pane.setProperty("loadState", "PASS")

    def call(name, *arguments):
        result = js_pane.property(name).callWithInstance(js_pane, [engine.toScriptValue(arg) for arg in arguments])
        assert not result.isError(), result.toString()
        return result

    counter = 0
    def start(action, key, **values):
        nonlocal counter
        counter += 1
        command = {"action": action, "command_id": "fixture-" + str(counter),
                   "expires_at": time.time() + 10, **values}
        fn = engine.evaluate("(function(pane,command,key){__results[key]=null;"
            "pane.playOperator(command,function(result){__results[key]=result;});})")
        result = fn.call([js_pane, engine.toScriptValue(command), engine.toScriptValue(key)])
        assert not result.isError(), result.toString()
        return command

    def result(key):
        return engine.evaluate("__results[" + json.dumps(key) + "]").toVariant()

    def done(key):
        wait(lambda: result(key) is not None)
        return result(key)

    try:
        reset_document()
        start("CLICK", "single", selector="#go")
        assert done("single")["ok"]
        assert evaluate("goCount") == 1 and evaluate("submitCount") == 1

        proxy.setProperty("callbackDelay", 60)
        wanted = "Åäö four chunks!"
        start("TYPE", "typed", selector="#q", text=wanted)
        assert done("typed")["ok"]
        assert evaluate("q.value") == wanted and evaluate("inputCount") == 4
        proxy.setProperty("callbackDelay", 0)

        reset_document()
        proxy.setProperty("holdMatch", "scrollIntoView")
        old = start("CLICK", "old", selector="#go")
        wait(lambda: proxy.property("held").property("length").toInt() == 1)
        call("cancelOperator", old["command_id"], "TEST_CANCELLED")
        assert done("old")["reason"] == "TEST_CANCELLED"
        proxy.setProperty("holdMatch", "")
        start("CLICK", "next", selector="#other")
        assert done("next")["ok"]
        window_call("releaseScript")
        pump(.15)
        assert evaluate("goCount") == 0 and evaluate("otherCount") == 1

        # Cancellation must retire a queued MUTATION on the same Document,
        # including when another operation has already completed there.
        reset_document()
        proxy.setProperty("holdMatch", "MouseEvent('mousedown'")
        old = start("CLICK", "old-mutation", selector="#go")
        wait(lambda: proxy.property("held").property("length").toInt() == 1)
        call("cancelOperator", old["command_id"], "TEST_CANCELLED")
        assert done("old-mutation")["completion_uncertain"] is True
        proxy.setProperty("holdMatch", "")
        start("CLICK", "next-mutation", selector="#other")
        assert done("next-mutation")["ok"]
        window_call("releaseScript")
        pump(.15)
        assert evaluate("goCount") == 0 and evaluate("otherCount") == 1

        # A probe delayed before cancellation may not reinstall A after B.
        reset_document()
        proxy.setProperty("holdMatch", "if(!document.__ggOperatorIdentity)")
        old = start("CLICK", "old-probe", selector="#go")
        wait(lambda: proxy.property("held").property("length").toInt() == 1)
        call("cancelOperator", old["command_id"], "TEST_CANCELLED")
        proxy.setProperty("holdMatch", "")
        start("CLICK", "after-old-probe", selector="#other")
        assert done("after-old-probe")["ok"]
        window_call("releaseScript")
        pump(.15)
        assert evaluate("goCount") == 0 and evaluate("otherCount") == 1

        # Retirement in the old document is gone after navigation. A delayed
        # A probe must still not lower the current generation while B is live
        # in the new document.
        reset_document()
        proxy.setProperty("holdMatch", "if(!document.__ggOperatorIdentity)")
        old = start("CLICK", "old-document-probe", selector="#go")
        wait(lambda: proxy.property("held").property("length").toInt() == 1)
        call("cancelOperator", old["command_id"], "TEST_CANCELLED")
        reset_document()
        proxy.setProperty("holdMatch", "MouseEvent('mousedown'")
        start("CLICK", "new-document-live", selector="#other")
        wait(lambda: proxy.property("held").property("length").toInt() == 2)
        proxy.setProperty("holdMatch", "")
        window_call("releaseScript")
        pump(.1)
        window_call("releaseScript")
        assert done("new-document-live")["ok"]
        assert evaluate("goCount") == 0 and evaluate("otherCount") == 1

        reset_document()
        proxy.setProperty("holdMatch", "MouseEvent('mousedown'")
        start("CLICK", "new-document", selector="#go")
        wait(lambda: proxy.property("held").property("length").toInt() == 1)
        reset_document()
        proxy.setProperty("holdMatch", "")
        window_call("releaseScript")
        assert done("new-document")["reason"] == "DOCUMENT_CHANGED"
        assert evaluate("goCount") == 0

        proxy.setProperty("navigateAfterLocate", True)
        start("CLICK", "during-aim", selector="#go")
        assert done("during-aim")["reason"] == "DOCUMENT_CHANGED"
        pump(.6)
        assert evaluate("goCount") == 0

        pane.setProperty("loadState", "PASS")
        old = start("SNAPSHOT", "grab-old")
        wait(lambda: proxy.property("heldGrabs").property("length").toInt() == 1)
        call("cancelOperator", old["command_id"], "TEST_CANCELLED")
        start("CLICK", "after-grab", selector="#other")
        assert done("after-grab")["ok"]
        window_call("releaseGrab")
        pump(.1)
        assert window.property("lateGrabSaves") == 0 and result("after-grab")["ok"]
        assert not warnings, warnings
        print("WEB_QML_LIFECYCLE_PASS click-once, submit-once, serial-typing, late-callback, document-change, late-grab", flush=True)
    finally:
        from shiboken6 import delete
        window.close()
        delete(engine)


if __name__ == "__main__":
    if "--probe" in sys.argv:
        probe()
    else:
        unittest.main()
