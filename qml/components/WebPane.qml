pragma ComponentBehavior: Bound


import "." as RuntimeTheme
import QtQuick
import QtQuick.Window
import QtWebEngine
import "webCursorPack.js" as Cursors

Item {
    id: root
    objectName: "webPane"

    property url pageUrl: ""
    property string loadState: "IDLE"
    property string loadFailReason: ""
    property int pageLoadTimeoutMs: 60000
    property int _loadRetriesLeft: 0
    property string _loadWatchUrl: ""
    property bool _abortingLoad: false
    property bool siteOnly: false
    property int reloadNonce: 0
    property bool wantEngine: false
    property bool engineArmed: false
    property bool _applyingUrl: false
    readonly property string profileStoragePath: {
        var win = Window.window
        var host = win && win.surfaceHost ? win.surfaceHost : null
        if (host && host.webProfilePath)
            return String(host.webProfilePath())
        return "/home/GG/.local/state/goldgoblins/gg-ai-desktop/web-profile"
    }
    property bool operatorBusy: false
    property string operatorLabel: ""
    property real agentX: 48
    property real agentY: 72
    property bool agentActive: false

    function syncDesk() {
        var win = Window.window
        if (!win || !win.setDeskCursor || win.deskFromChrome)
            return
        if (!root.agentActive && !root.operatorBusy)
            return
        win.setDeskCursor(root, root.agentX, root.agentY, root.agentCursorShape)
    }

    function adoptDeskPosition() {
        var win = Window.window
        if (!win || win.deskX === undefined)
            return
        var p = root.mapFromItem(win.contentItem, Number(win.deskX), Number(win.deskY))
        var nx = Math.max(4, Math.min(Math.max(8, root.width - 8), p.x))
        var ny = Math.max(4, Math.min(Math.max(8, root.height - 8), p.y))
        if (root.width <= 8 || root.height <= 8)
            return
        root.agentX = nx
        root.agentY = ny
    }
    property string agentShape: "default"
    readonly property string agentCursorShape:
        root.loadState === "LOADING" ? "wait" : root.agentShape
    signal navigated(string href)
    signal openNewTab(string href)
    signal popupViewReady(var view)
    signal titled(string title)
    property var adoptedEngine: null
    readonly property bool useNativeBrowser: {
        var win = Window.window
        var host = win && win.surfaceHost ? win.surfaceHost : null
        return Qt.platform.os === "windows" && !root.siteOnly
            && host && host.nativeWebViewReady === true
    }

    readonly property bool engineActive: true
    readonly property bool blockerAvailable: {
        var engine = root.liveEngine()
        return engine && engine.blockerAvailable === true
    }
    readonly property bool blockerReady: {
        var engine = root.liveEngine()
        return engine && engine.blockerReady === true
    }
    readonly property bool blockerEnabled: {
        var engine = root.liveEngine()
        return engine && engine.blockerEnabled === true
    }
    readonly property string blockerError: {
        var engine = root.liveEngine()
        return engine && engine.blockerError ? String(engine.blockerError) : ""
    }

    function toggleBlocker() {
        var engine = root.liveEngine()
        if (engine && engine.toggleBlocker)
            engine.toggleBlocker()
    }

    function openBlockerSettings() {
        var engine = root.liveEngine()
        if (engine && engine.openBlockerSettings)
            engine.openBlockerSettings()
    }

    property var _opDone: null
    property var _opCmd: ({})
    property var _opQueue: []
    property var _loadDone: null
    property bool _needLoading: false
    property string _typeSelector: ""
    property string _typeText: ""
    property int _typeIndex: 0
    property bool _typeReset: true
    property var _scriptOnce: null
    property int _opEpoch: 0
    property int _documentEpoch: 0
    property string _opDocumentToken: ""
    property string _opDocumentHref: ""
    property bool _allowNavigation: false
    property bool _typingInFlight: false
    property var _opEngine: null
    property string _pageSession: String(Date.now()) + "-" + String(Math.random())
    property bool _mutationSubmitted: false
    property string lastGrab: ""
    property string _stageHtml: "<!DOCTYPE html><html lang=\"sv\"><head><meta charset=\"utf-8\"><title>GG WEB stage</title><style>body{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;background:#121212;color:#e6e6e6;margin:2rem}button,input,select{font:16px monospace;padding:.4rem .7rem;margin:.4rem 0}a{color:#c8a97e}.tall{height:900px}.page{display:none}.page.on{display:block}</style></head><body><section id=\"home\" class=\"page on\"><h1>Visible WEB stage</h1><p>Local fixture. No network.</p><form id=\"f\"><input id=\"q\" placeholder=\"type here\"><p><button id=\"go\" type=\"submit\">Go</button></p></form><p id=\"out\"></p><p><label><input id=\"agree\" type=\"checkbox\"> I agree</label></p><p><select id=\"city\"><option value=\"\">City</option><option value=\"lidkoping\">Lidkoping</option><option value=\"skara\">Skara</option></select></p><p><a id=\"link\" href=\"#bottom\">Scroll link</a></p><p><a id=\"next\" href=\"#two\">Next page</a></p><p><a id=\"blank\" href=\"#two\" target=\"_blank\">Open page two in new tab</a></p><div class=\"tall\"></div><p id=\"bottom\">bottom</p></section><section id=\"two\" class=\"page\"><h1>Page two</h1><p id=\"p2\">Second page.</p><p><a id=\"home\" href=\"#home\">Back home</a></p></section><script>function show(){var h=location.hash||\"#home\";document.querySelectorAll(\".page\").forEach(function(p){p.classList.remove(\"on\")});var el=document.querySelector(h===\"#two\"?\"#two\":\"#home\");if(el)el.classList.add(\"on\");}show();window.addEventListener(\"hashchange\",show);document.getElementById(\"f\").addEventListener(\"submit\",function(e){e.preventDefault();document.getElementById(\"out\").textContent=\"clicked: \"+document.getElementById(\"q\").value;});</script></body></html>"

    onWantEngineChanged: {
        if (root.wantEngine)
            root.engineArmed = true
    }
    Component.onCompleted: {
        if (root.wantEngine)
            root.engineArmed = true
    }

    WebEngineProfile {
        id: sessionProfile
        objectName: "webSessionProfile"
        storageName: "gg-web"
        offTheRecord: false
        persistentCookiesPolicy: WebEngineProfile.ForcePersistentCookies
        httpCacheType: WebEngineProfile.DiskHttpCache
        persistentStoragePath: root.profileStoragePath
        cachePath: root.profileStoragePath + "/cache"
    }

    Connections {
        target: sessionProfile
        function onDownloadRequested(download) {
            var win = root.Window.window
            var host = win && win.surfaceHost ? win.surfaceHost : null
            var directory = host && host.webDownloadDirectory
                ? String(host.webDownloadDirectory())
                : ""
            if (directory.length > 0)
                download.downloadDirectory = directory
            download.accept()
        }
    }

    function hrefAllowed(target) {
        var href = String(target || "")
        if (href === "about:blank" || href.indexOf("about:blank") === 0)
            return true
        if (root.siteOnly) {
            if (href.indexOf("http://127.0.0.1:") === 0)
                return true
            if (href.indexOf("http://127.0.0.1/") === 0)
                return true
            if (href.indexOf("http://localhost:") === 0)
                return true
            if (href.indexOf("http://localhost/") === 0)
                return true
            return false
        }
        if (href.indexOf("chrome-extension://") === 0) {
            var win = Window.window
            var host = win && win.surfaceHost ? win.surfaceHost : null
            return host && host.webExtensionUrlAllowed
                && host.webExtensionUrlAllowed(href)
        }
        if (
            href.indexOf("https://") === 0
            || href.indexOf("http://") === 0
        )
            return true
        return false
    }

    function liveEngine() {
        return root.adoptedEngine || (root.useNativeBrowser ? nativeLoader.item : engineLoader.item)
    }

    function reload() {
        var engine = root.liveEngine()
        if (engine)
            engine.reload()
    }

    function goBack() {
        var engine = root.liveEngine()
        if (engine)
            engine.goBack()
    }

    function goForward() {
        var engine = root.liveEngine()
        if (engine)
            engine.goForward()
    }

    function currentHref() {
        var engine = root.liveEngine()
        if (engine)
            return String(engine.currentUrl || engine.url || root.pageUrl || "")
        return String(root.pageUrl || "")
    }

    function takeView(view) {
        if (!view)
            return
        root.cancelOperator("", "ENGINE_CHANGED")
        root.adoptedEngine = view
        root.engineArmed = false
        view.parent = engineHost
        view.anchors.fill = engineHost
        view.visible = true
        view.z = 2
        function syncUrl() {
            var href = String(view.url || "")
            if (!href.length)
                return
            root._applyingUrl = true
            root.navigated(href)
            root._applyingUrl = false
        }
        view.urlChanged.connect(syncUrl)
        view.loadingChanged.connect(function(loadRequest) {
            root.handleEngineLoad(Number(loadRequest.status), view)
        })
        syncUrl()
    }

    function handleEngineLoad(status, view) {
        if (view && view !== root.liveEngine())
            return
        if (status === WebEngineView.LoadStartedStatus) {
            root._documentEpoch += 1
            if (root.operatorBusy && !root._allowNavigation)
                root.cancelOperator("", "DOCUMENT_CHANGED")
            if (root._abortingLoad) {
                pageLoadWatch.stop()
                return
            }
            root.loadFailReason = ""
            root.loadState = "LOADING"
            root._loadWatchUrl = String((view && view.url) || root.currentHref() || "")
            pageLoadWatch.restart()
            return
        }
        if (status === WebEngineView.LoadSucceededStatus) {
            pageLoadWatch.stop()
            if (root._abortingLoad) {
                root.loadState = "FAIL"
                return
            }
            root._loadRetriesLeft = 0
            root.loadFailReason = ""
            root.loadState = "PASS"
            if (view && view.runJavaScript)
                view.runJavaScript("document.title", function(title) {
                    root.titled(String(title || ""))
                })
            return
        }
        if (status === WebEngineView.LoadFailedStatus) {
            pageLoadWatch.stop()
            if (root._abortingLoad)
                return
            root._loadRetriesLeft = 0
            root.loadFailReason = "ENGINE"
            root.loadState = "FAIL"
        }
    }

    function haltEngine() {
        pageLoadWatch.stop()
        root._loadDone = null
        var engine = root.liveEngine()
        if (engine && engine.stop)
            engine.stop()
    }

    function cancelLoadWait() {
        root._loadDone = null
        loadWaitTimer.stop()
    }

    function cancelOperator(commandId, reason) {
        if (!root.operatorBusy)
            return
        if (commandId && String(root._opCmd.command_id || "") !== String(commandId))
            return
        root._finish(false, reason || "OPERATOR_CANCELLED", root.currentHref(), "", "", [])
    }

    function _expired() {
        return Number(root._opCmd.expires_at || 0) > 0
            && Date.now() / 1000 >= Number(root._opCmd.expires_at)
    }

    function _guard(done, allowDocumentChange) {
        var epoch = root._opEpoch
        var documentEpoch = root._documentEpoch
        return function(value) {
            if (!root.operatorBusy || epoch !== root._opEpoch)
                return
            if (root._expired()) {
                root.cancelOperator("", "OPERATOR_TIMEOUT")
                return
            }
            if (!allowDocumentChange && documentEpoch !== root._documentEpoch) {
                root.cancelOperator("", "DOCUMENT_CHANGED")
                return
            }
            done(value)
        }
    }

    function abortStuckLoad() {
        if (root._abortingLoad)
            return
        root.haltEngine()
        if (
            root._loadRetriesLeft > 0
            && root._loadWatchUrl.length > 0
            && root._loadWatchUrl.indexOf("about:blank") !== 0
        ) {
            root._loadRetriesLeft -= 1
            root.loadState = "LOADING"
            pageLoadWatch.restart()
            var retryEngine = root.liveEngine()
            if (retryEngine)
                retryEngine.url = root._loadWatchUrl
            return
        }
        root._abortingLoad = true
        var engine = root.liveEngine()
        if (engine)
            engine.url = "about:blank"
        root.loadFailReason = "TIMEOUT"
        root.loadState = "FAIL"
        if (root._loadDone) {
            var fn = root._loadDone
            root._loadDone = null
            fn("TIMEOUT")
        }
    }

    function runPageScript(script, done, allowDocumentChange, mutating) {
        var guarded = root._guard(done, allowDocumentChange === true)
        function once(raw) {
            if (root._scriptOnce !== once)
                return
            root._scriptOnce = null
            scriptWatch.stop()
            var parsed = root._parse(raw)
            if (["DOCUMENT_CHANGED", "OPERATION_REPLACED", "OPERATOR_TIMEOUT"].indexOf(parsed.reason) >= 0) {
                root.cancelOperator("", parsed.reason)
                return
            }
            guarded(raw)
        }
        root._scriptOnce = once
        scriptWatch.restart()
        var engine = root._opEngine
        if (!engine || !engine.runJavaScript) {
            once("")
            return
        }
        if (root._opDocumentToken.length > 0)
            script = "(function(){if(" + Number(root._opCmd.expires_at || 0)
                + ">0&&Date.now()/1000>=" + Number(root._opCmd.expires_at || 0)
                + ")return JSON.stringify({ok:false,reason:'OPERATOR_TIMEOUT'});"
                + "if(document.__ggOperatorIdentity!=="
                + JSON.stringify(root._opDocumentToken)
                + "||String(location.href)!==" + JSON.stringify(root._opDocumentHref)
                + ")return JSON.stringify({ok:false,reason:'DOCUMENT_CHANGED'});"
                + "var s=document.__ggOperatorSessions&&document.__ggOperatorSessions["
                + JSON.stringify(root._pageSession) + "];if(!s||s.current!==" + root._opEpoch
                + "||s.retiredThrough>=" + root._opEpoch
                + ")return JSON.stringify({ok:false,reason:'OPERATION_REPLACED'});return ("
                + script + ");})()"
        if (mutating === true)
            root._mutationSubmitted = true
        engine.runJavaScript(script, once)
    }

    function playOperator(cmd, done) {
        if (root.operatorBusy) {
            if (typeof done === "function")
                done({ok: false, reason: "OPERATOR_BUSY", url: root.currentHref()})
            return
        }
        root._opEpoch += 1
        root._opCmd = cmd || {}
        root._opEngine = root.liveEngine()
        root._mutationSubmitted = false
        root._opDone = done
        root.operatorBusy = true
        root._opDocumentToken = ""
        root._opDocumentHref = ""
        root._allowNavigation = false
        root.lastGrab = ""
        if (root._expired()) {
            root.cancelOperator("", "OPERATOR_TIMEOUT")
            return
        }
        var remaining = Number(root._opCmd.expires_at || 0) * 1000 - Date.now()
        busyWatch.interval = remaining > 0 ? Math.max(1, Math.min(180000, remaining)) : 12000
        busyWatch.restart()
        root.agentActive = true
        root.adoptDeskPosition()
        var action = String(root._opCmd.action || "")
        root.operatorLabel = "GROK · " + action
        root._primeShape(action)
        if (["WAIT", "RELOAD", "BACK", "FORWARD"].indexOf(action) >= 0) {
            root._dispatchOperator()
            return
        }
        // Capture the actual Document identity before locating or mutating.
        // Every later script checks it inside the page, including scripts
        // queued just before the browser begins a new navigation.
        root.runPageScript("(function(){if(" + Number(root._opCmd.expires_at || 0)
            + ">0&&Date.now()/1000>=" + Number(root._opCmd.expires_at || 0)
            + ")return JSON.stringify({ok:false,reason:'OPERATOR_TIMEOUT'});"
            + "var a=document.__ggOperatorSessions;if(!a){a=Object.create(null);"
            + "Object.defineProperty(document,'__ggOperatorSessions',{value:a});}"
            + "var s=a[" + JSON.stringify(root._pageSession) + "]||(a["
            + JSON.stringify(root._pageSession) + "]={retiredThrough:0,current:0});"
            + "if(s.retiredThrough>=" + root._opEpoch
            + "||s.current>" + root._opEpoch
            + ")return JSON.stringify({ok:false,reason:'OPERATION_REPLACED'});s.current=" + root._opEpoch + ";"
            + "if(!document.__ggOperatorIdentity)"
            + "Object.defineProperty(document,'__ggOperatorIdentity',{value:"
            + "String(Date.now())+'-'+String(Math.random()),configurable:false});"
            + "return JSON.stringify({token:String(document.__ggOperatorIdentity),href:String(location.href)});})()", function(raw) {
                var identity = root._parse(raw)
                if (!identity.token || !identity.href) {
                    root.cancelOperator("", "SCRIPT_TIMEOUT")
                    return
                }
                root._opDocumentToken = String(identity.token)
                root._opDocumentHref = String(identity.href)
                root._dispatchOperator()
            })
    }

    function _dispatchOperator() {
        var action = String(root._opCmd.action || "")
        if (action === "SNAPSHOT") {
            root._moveCursorTo(root.width / 2, Math.max(56, root.height / 3), function() {
                root._snapshot()
            })
            return
        }
        if (action === "RELOAD") {
            root._allowNavigation = true
            root.reload()
            root._finish(true, "RELOADED", root.currentHref(), "", "", [])
            return
        }
        if (action === "BACK") {
            root._allowNavigation = true
            root.goBack()
            root._finish(true, "BACK", root.currentHref(), "", "", [])
            return
        }
        if (action === "FORWARD") {
            root._allowNavigation = true
            root.goForward()
            root._finish(true, "FORWARD", root.currentHref(), "", "", [])
            return
        }
        if (action === "WAIT") {
            root.waitLoad(function(state) {
                root._finish(
                    state === "PASS",
                    state === "PASS" ? "WAITED" : "WAIT_" + state,
                    root.currentHref(),
                    "",
                    "",
                    []
                )
            })
            return
        }
        if (action === "STAGE") {
            root._loadStage()
            return
        }
        if (action === "SCROLL") {
            root._scroll()
            return
        }
        if (action === "MOVE") {
            root._move()
            return
        }
        if (action === "HOVER" || action === "CLICK" || action === "TYPE" || action === "SELECT") {
            root._aimThenAct()
            return
        }
        if (action === "KEY") {
            root._key()
            return
        }
        root._finish(false, "ACTION_INVALID", root.currentHref(), "", "", [])
    }

    function waitLoad(done) {
        if (root.operatorBusy)
            done = root._guard(done, true)
        root.agentShape = "wait"
        root._loadDone = done
        root._needLoading = root.loadState !== "LOADING"
        loadWaitTimer.restart()
        if (
            !root._needLoading
            && (
                root.loadState === "PASS"
                || root.loadState === "FAIL"
                || root.loadState === "BLOCKED"
            )
        ) {
            var fn = root._loadDone
            root._loadDone = null
            loadWaitTimer.stop()
            Qt.callLater(function() { fn(root.loadState) })
        }
    }

    function _primeShape(action) {
        if (
            action === "WAIT"
            || action === "OPEN"
            || action === "RELOAD"
            || action === "BACK"
            || action === "FORWARD"
            || action === "STAGE"
        )
            root.agentShape = "wait"
        else if (action === "SNAPSHOT")
            root.agentShape = "progress"
        else if (action === "TYPE")
            root.agentShape = "text"
        else if (action === "SCROLL")
            root.agentShape = "openhand"
        else if (action === "KEY")
            root.agentShape = "text"
        else if (action === "CLICK" || action === "HOVER")
            root.agentShape = "pointer"
        else
            root.agentShape = "default"
    }

    function applyCssCursor(raw) {
        root.agentShape = Cursors.fromCss(raw)
    }

    function applyHitShape(hit, action) {
        var mapped = Cursors.fromCss(hit && hit.cursor ? hit.cursor : "")
        if (action === "TYPE")
            root.agentShape = "text"
        else if (mapped !== "default")
            root.agentShape = mapped
        else if (action === "CLICK" || action === "HOVER")
            root.agentShape = "pointer"
        else
            root.agentShape = mapped
    }

    function _finish(ok, reason, url, title, text, links) {
        if (!root.operatorBusy)
            return
        var fn = root._opDone
        root._opDone = null
        var retiredEpoch = root._opEpoch
        var engine = root._opEngine
        var uncertain = !ok && root._mutationSubmitted
        // Retire even a probe that has not executed yet. Monotonic retirement
        // prevents a late old probe from reinstalling its operation after B.
        if (engine && engine.runJavaScript)
            engine.runJavaScript("(function(){var a=document.__ggOperatorSessions;"
                + "if(!a){a=Object.create(null);Object.defineProperty(document,'__ggOperatorSessions',{value:a});}"
                + "var s=a[" + JSON.stringify(root._pageSession) + "]||(a["
                + JSON.stringify(root._pageSession) + "]={retiredThrough:0,current:0});"
                + "s.retiredThrough=Math.max(s.retiredThrough," + retiredEpoch + ");"
                + "if(s.current===" + retiredEpoch + ")s.current=0;})()", function() {})
        root._opEpoch += 1
        root._scriptOnce = null
        scriptWatch.stop()
        grabWait.stop()
        grabWait._done = null
        moveAnim.doneFn = null
        moveAnim.stop()
        typeTimer.stop()
        loadWaitTimer.stop()
        root._typingInFlight = false
        root._typeText = ""
        root._typeSelector = ""
        root._loadDone = null
        root.operatorBusy = false
        if (ok)
            root.operatorLabel = "GROK · " + reason
        else
            root.operatorLabel = "GROK · " + reason
        var doneAction = String((root._opCmd && root._opCmd.action) || "")
        if (!ok && (reason === "MISS" || reason === "PASSWORD" || reason === "ACTION_INVALID"))
            root.agentShape = "not-allowed"
        else if (
            doneAction === "SNAPSHOT"
            || doneAction === "WAIT"
            || doneAction === "RELOAD"
            || doneAction === "BACK"
            || doneAction === "STAGE"
        )
            root.agentShape = "default"
        hudFade.restart()
        if (typeof fn === "function") {
            fn({
                "ok": ok,
                "reason": reason,
                "url": url || root.currentHref(),
                "title": title || "",
                "text": text || "",
                "links": links || [],
                "image": root.lastGrab || ""
                , "completion_uncertain": uncertain
            })
        }
        root._opQueue = []
    }

    function _grabView(done) {
        done = root._guard(done, false)
        var engine = root.liveEngine()
        if (engine && engine.update)
            engine.update()
        var win = Window.window
        if (win && win.update)
            win.update()
        grabWait._done = done
        grabWait.restart()
    }

    function _grabViewNow(done) {
        done = root._guard(done, false)
        var win = Window.window
        if (root.useNativeBrowser && win && win.surfaceHost && win.surfaceHost.webCapturePane) {
            var point = root.mapToItem(win.contentItem, 0, 0)
            root.lastGrab = String(win.surfaceHost.webCapturePane(
                Math.round(point.x), Math.round(point.y), Math.round(root.width), Math.round(root.height)) || "")
            done(root.lastGrab)
            return
        }
        var target = root
        var engine = root.liveEngine()
        if (engine && engine.grabToImage)
            target = engine
        if (!target.grabToImage) {
            done("")
            return
        }
        target.grabToImage(root._guard(function(result) {
            var host = win && win.surfaceHost ? win.surfaceHost : null
            var path = host && host.webOperatorViewPath ? String(host.webOperatorViewPath()) : ""
            var ok = false
            try {
                ok = path.length > 0 && result.saveToFile(path)
            } catch (err) {
                ok = false
            }
            root.lastGrab = ok ? path : ""
            done(root.lastGrab)
        }, false))
    }

    function _snapshot() {
        var script = "(function(){var t=document.body?document.body.innerText:'';if(t.length>8000)t=t.slice(0,8000);var links=[];var as=document.querySelectorAll('a[href]');var i;for(i=0;i<as.length&&i<40;i++){links.push({t:(as[i].innerText||'').trim().slice(0,80),h:as[i].href});}return JSON.stringify({url:location.href,title:document.title,text:t,links:links});})()"
        root._grabView(function() {
            root.runPageScript(script, function(raw) {
                var parsed = root._parse(raw)
                root._finish(
                    Boolean(parsed.url),
                    parsed.url ? "SNAPSHOT" : "SCRIPT_TIMEOUT",
                    String(parsed.url || root.currentHref()),
                    String(parsed.title || ""),
                    String(parsed.text || ""),
                    parsed.links || []
                )
            })
        })
    }

    function _loadStage() {
        var script = "(function(){document.open();document.write(" + JSON.stringify(root._stageHtml) + ");document.close();return JSON.stringify({ok:true,url:location.href,title:document.title});})()"
        root.runPageScript(script, function(raw) {
            var parsed = root._parse(raw)
            root.operatorLabel = "GROK · STAGE"
            root._finish(
                parsed.ok === true,
                parsed.ok === true ? "STAGED" : "STAGE_FAIL",
                String(parsed.url || root.currentHref()),
                String(parsed.title || "GG WEB stage"),
                "local visible WEB rehearsal",
                []
            )
        })
    }

    function _scroll() {
        var selector = String(root._opCmd.selector || "")
        var dx = Number(root._opCmd.dx || 0)
        var dy = Number(root._opCmd.dy || 0)
        function wheelAt(x, y) {
            root.agentShape = "dnd-move"
            var script = "(function(){var dx=" + dx + ";var dy=" + dy + ";var x=" + Number(x) + ";var y=" + Number(y) + ";var before=window.scrollY;var el=document.elementFromPoint(x,y)||document.scrollingElement||document.documentElement;try{el.dispatchEvent(new WheelEvent('wheel',{bubbles:true,cancelable:true,deltaX:dx,deltaY:dy,deltaMode:0,clientX:x,clientY:y}))}catch(e){}window.scrollBy({left:dx,top:dy,behavior:'instant'});return JSON.stringify({ok:true,url:location.href,title:document.title,x:window.scrollX,y:window.scrollY,before:before});})()"
            root.runPageScript(script, function(raw) {
                var parsed = root._parse(raw)
                root._grabView(function() {
                    root._finish(
                        parsed.ok !== false,
                        "SCROLLED",
                        String(parsed.url || root.currentHref()),
                        String(parsed.title || ""),
                        parsed.y !== undefined ? String(parsed.y) : "",
                        []
                    )
                })
            })
        }
        if (selector.length > 0) {
            root._locate(selector, function(hit) {
                if (!hit || !hit.ok) {
                    root._finish(false, "MISS", root.currentHref(), "", "", [])
                    return
                }
                root._showHit(hit)
                root._moveCursorTo(hit.x, hit.y, function() {
                    if (dx === 0 && dy === 0)
                        root._grabView(function() {
                            root._finish(
                                true,
                                "SCROLLED",
                                String(hit.url || root.currentHref()),
                                String(hit.title || ""),
                                "",
                                []
                            )
                        })
                    else
                        wheelAt(hit.x, hit.y)
                })
            })
            return
        }
        var cx = root.width / 2
        var cy = Math.max(48, root.height / 3)
        root._moveCursorTo(cx, cy, function() {
            wheelAt(cx, cy)
        })
    }

    function _move() {
        var selector = String(root._opCmd.selector || "")
        if (selector.length > 0) {
            root._locate(selector, function(hit) {
                if (!hit || !hit.ok) {
                    root._finish(false, "MISS", root.currentHref(), "", "", [])
                    return
                }
                root._showHit(hit)
                root.applyHitShape(hit, "MOVE")
                root._moveCursorTo(hit.x, hit.y, function() {
                    root._finish(true, "MOVED", String(hit.url || root.currentHref()), String(hit.title || ""), "", [])
                })
            })
            return
        }
        var x = Number(root._opCmd.x || 0)
        var y = Number(root._opCmd.y || 0)
        root._moveCursorTo(x, y, function() {
            var script = "(function(){var el=document.elementFromPoint(" + x + "," + y + ");if(!el)return JSON.stringify({cursor:'default'});var css='';try{css=String(getComputedStyle(el).cursor||'')}catch(e){}return JSON.stringify({cursor:css});})()"
            root.runPageScript(script, function(raw) {
                root.applyCssCursor(root._parse(raw).cursor)
                root._finish(true, "MOVED", root.currentHref(), "", "", [])
            })
        })
    }

    function _aimThenAct() {
        var selector = String(root._opCmd.selector || "")
        root._locate(selector, function(hit) {
            if (!hit || !hit.ok) {
                root._finish(false, "MISS", root.currentHref(), "", "", [])
                return
            }
            root._showHit(hit)
            root.applyHitShape(hit, String(root._opCmd.action || ""))
            root._moveCursorTo(hit.x, hit.y, function() {
                var action = String(root._opCmd.action || "")
                if (action === "HOVER")
                    root._hover(selector, hit)
                else if (action === "CLICK")
                    root._click(selector, hit)
                else if (action === "SELECT")
                    root._select(selector, hit)
                else
                    root._typeStart(selector, hit)
            })
        })
    }

    function _hover(selector, hit) {
        var script = "(function(){" + root._elFindJs(selector) + ";if(!el)return JSON.stringify({ok:false,reason:'MISS'});el.dispatchEvent(new MouseEvent('mouseover',{bubbles:true,clientX:" + hit.x + ",clientY:" + hit.y + "}));el.dispatchEvent(new MouseEvent('mouseenter',{bubbles:true,clientX:" + hit.x + ",clientY:" + hit.y + "}));return JSON.stringify({ok:true,url:location.href,title:document.title});})()"
        root.runPageScript(script, function(raw) {
            var parsed = root._parse(raw)
            root._finish(
                parsed.ok === true,
                parsed.ok === true ? "HOVERED" : String(parsed.reason || "FAIL"),
                String(parsed.url || root.currentHref()),
                String(parsed.title || ""),
                "",
                []
            )
        })
    }

    function _select(selector, hit) {
        var wanted = String(root._opCmd.text || "")
        var script = "(function(){" + root._elFindJs(selector) + ";if(!el)return JSON.stringify({ok:false,reason:'MISS'});var want=" + JSON.stringify(wanted) + ";var ok=false;if(el.tagName==='SELECT'){var i;for(i=0;i<el.options.length;i++){var o=el.options[i];if(o.value===want||(o.text||'').trim()===want){el.selectedIndex=i;ok=true;break;}}if(!ok&&want){el.value=want;ok=true;}el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));return JSON.stringify({ok:ok,reason:ok?'SELECTED':'MISS',url:location.href,title:document.title,text:el.value});}el.value=want;el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));return JSON.stringify({ok:true,reason:'SELECTED',url:location.href,title:document.title,text:want});})()"
        root._allowNavigation = true
        root.runPageScript(script, function(raw) {
            var parsed = root._parse(raw)
            root._finish(
                parsed.ok === true,
                parsed.ok === true ? "SELECTED" : String(parsed.reason || "FAIL"),
                String(parsed.url || root.currentHref()),
                String(parsed.title || ""),
                String(parsed.text || wanted),
                []
            )
        }, true, true)
    }

    function _click(selector, hit) {
        if (ripple && ripple.play)
            ripple.play()
        var aux = String(root._opCmd.text || "") === "aux"
        var script = aux
            ? "(function(){" + root._elFindJs(selector) + ";if(!el)return JSON.stringify({ok:false,reason:'MISS'});var href=el.href||el.getAttribute('href')||'';el.dispatchEvent(new MouseEvent('auxclick',{bubbles:true,cancelable:true,button:1,which:2,buttons:4,clientX:" + hit.x + ",clientY:" + hit.y + "}));el.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,button:1,which:2,clientX:" + hit.x + ",clientY:" + hit.y + "}));return JSON.stringify({ok:true,reason:'MIDDLE',url:href,title:document.title});})()"
            : "(function(){" + root._elFindJs(selector) + ";if(!el)return JSON.stringify({ok:false,reason:'MISS'});var r=el.getBoundingClientRect();var x=r.left+r.width/2,y=r.top+r.height/2;var opts={bubbles:true,cancelable:true,view:window,clientX:x,clientY:y,button:0,buttons:1};el.dispatchEvent(new MouseEvent('mousedown',opts));el.dispatchEvent(new MouseEvent('mouseup',Object.assign({},opts,{buttons:0})));if(typeof el.click==='function')el.click();else el.dispatchEvent(new MouseEvent('click',Object.assign({},opts,{buttons:0})));return JSON.stringify({ok:true,reason:'CLICKED',url:location.href,title:document.title});})()"
        root._allowNavigation = true
        root.runPageScript(script, function(raw) {
            var parsed = root._parse(raw)
            function doneClick() {
                root._finish(
                    parsed.ok === true,
                    parsed.ok === true ? "CLICKED" : String(parsed.reason || "FAIL"),
                    String(parsed.url || root.currentHref()),
                    String(parsed.title || ""),
                    "",
                    []
                )
            }
            if (root.loadState === "LOADING")
                root.waitLoad(function() { doneClick() })
            else
                doneClick()
        }, true, true)
    }

    function _key() {
        var key = String(root._opCmd.text || "")
        var selector = String(root._opCmd.selector || "")
        var codes = {
            "Enter": [13, "Enter"],
            "Tab": [9, "Tab"],
            "Escape": [27, "Escape"],
            "Space": [32, "Space"],
            "Backspace": [8, "Backspace"],
            "Delete": [46, "Delete"],
            "Home": [36, "Home"],
            "End": [35, "End"],
            "ArrowUp": [38, "ArrowUp"],
            "ArrowDown": [40, "ArrowDown"],
            "ArrowLeft": [37, "ArrowLeft"],
            "ArrowRight": [39, "ArrowRight"]
        }
        var spec = codes[key]
        if (!spec) {
            root._finish(false, "KEY_INVALID", root.currentHref(), "", "", [])
            return
        }
        function fire() {
            var script = "(function(){" + (selector ? root._elFindJs(selector) + ";if(!el)return JSON.stringify({ok:false,reason:'MISS'});" : "var el=document.activeElement;") + "if(el&&el.focus)el.focus();var t=el||document.body;var key=" + JSON.stringify(key) + ";var code=" + JSON.stringify(spec[1]) + ";var kc=" + spec[0] + ";['keydown','keypress','keyup'].forEach(function(type){t.dispatchEvent(new KeyboardEvent(type,{key:key,code:code,keyCode:kc,which:kc,bubbles:true,cancelable:true}));});if(key==='Enter'){if(t.form){if(t.form.requestSubmit)t.form.requestSubmit();else t.form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));}else if(t.click&&(t.tagName==='BUTTON'||t.type==='submit'))t.click();}return JSON.stringify({ok:true,reason:'KEYED',url:location.href,title:document.title,key:key});})()"
            root._allowNavigation = true
            root.runPageScript(script, function(raw) {
                var parsed = root._parse(raw)
                function doneKey() {
                    root._finish(
                        parsed.ok === true,
                        parsed.ok === true ? "KEYED" : String(parsed.reason || "FAIL"),
                        String(parsed.url || root.currentHref()),
                        String(parsed.title || ""),
                        key,
                        []
                    )
                }
                if (root.loadState === "LOADING")
                    root.waitLoad(function() { doneKey() })
                else
                    doneKey()
            }, true, true)
        }
        if (selector.length > 0) {
            root._locate(selector, function(hit) {
                if (!hit || !hit.ok) {
                    root._finish(false, "MISS", root.currentHref(), "", "", [])
                    return
                }
                root._showHit(hit)
                root.applyHitShape(hit, "KEY")
                root._moveCursorTo(hit.x, hit.y, fire)
            })
            return
        }
        fire()
    }

    function _typeStart(selector, hit) {
        root._typeSelector = selector
        root._typeText = String(root._opCmd.text || "")
        root._typeIndex = 0
        root._typeReset = true
        if (root._typeText.length === 0) {
            root._finish(false, "TEXT_REQUIRED", root.currentHref(), "", "", [])
            return
        }
        root.agentShape = "text"
        typeTimer.start()
    }

    function _typeTick() {
        if (!root.operatorBusy || root._typingInFlight)
            return
        root._typingInFlight = true
        if (root._typeIndex >= root._typeText.length) {
            typeTimer.stop()
            var script = "(function(){" + root._elFindJs(root._typeSelector) + ";if(!el)return JSON.stringify({ok:false,reason:'MISS'});el.dispatchEvent(new Event('change',{bubbles:true}));return JSON.stringify({ok:true,url:location.href,title:document.title,text:String(el.value||'')});})()"
            root.runPageScript(script, function(raw) {
                var parsed = root._parse(raw)
                root._finish(
                    parsed.ok === true,
                    parsed.ok === true ? "TYPED" : String(parsed.reason || "FAIL"),
                    String(parsed.url || root.currentHref()),
                    String(parsed.title || ""),
                    String(parsed.text || root._typeText),
                    []
                )
            }, false, true)
            return
        }
        var ch = root._typeText.slice(root._typeIndex, root._typeIndex + 4)
        var reset = root._typeReset
        root._typeReset = false
        root._typeIndex += ch.length
        root.operatorLabel = "GROK · TYPE · " + root._typeIndex + "/" + root._typeText.length
        var script = "(function(){" + root._elFindJs(root._typeSelector) + ";if(!el)return JSON.stringify({ok:false,reason:'MISS'});var typ=String(el.type||'').toLowerCase();if(typ==='password')return JSON.stringify({ok:false,reason:'PASSWORD'});el.focus();if(" + (reset ? "true" : "false") + ")el.value='';el.value=String(el.value||'')+" + JSON.stringify(ch) + ";el.dispatchEvent(new Event('input',{bubbles:true}));return JSON.stringify({ok:true});})()"
        root.runPageScript(script, function(raw) {
            var parsed = root._parse(raw)
            if (parsed.ok !== true) {
                typeTimer.stop()
                root._finish(false, String(parsed.reason || "FAIL"), root.currentHref(), "", "", [])
            } else {
                root._typingInFlight = false
                typeTimer.restart()
            }
        }, false, true)
    }

    function _elFindJs(selector) {
        return "var sel=" + JSON.stringify(selector) + ";var el=null;if(String(sel).indexOf('text=')===0){var want=String(sel).slice(5).trim().toLowerCase();var nodes=document.querySelectorAll('button,a,[role=button],input,label');var i;for(i=0;i<nodes.length;i++){var t=String(nodes[i].innerText||nodes[i].value||'').replace(/\\s+/g,' ').trim().toLowerCase();if(t===want||(want.length>2&&t.indexOf(want)>=0&&t.length<64)){el=nodes[i];break;}}}else{try{el=document.querySelector(sel)}catch(e){el=null}}"
    }

    function _locate(selector, done) {
        var script = "(function(){" + root._elFindJs(selector) + ";if(!el)return JSON.stringify({ok:false,reason:'MISS'});el.scrollIntoView({block:'center',inline:'nearest',behavior:'instant'});var r=el.getBoundingClientRect();var css='';try{css=String(getComputedStyle(el).cursor||'')}catch(e2){}return JSON.stringify({ok:true,x:r.left+r.width/2,y:r.top+r.height/2,l:r.left,t:r.top,w:r.width,h:r.height,url:location.href,title:document.title,cursor:css});})()"
        root.runPageScript(script, function(raw) {
            done(root._parse(raw))
        })
    }

    function _showHit(hit) {
        hitBox.x = Number(hit.l || 0)
        hitBox.y = Number(hit.t || 0)
        hitBox.width = Math.max(8, Number(hit.w || 0))
        hitBox.height = Math.max(8, Number(hit.h || 0))
        hitBox.visible = true
        hitFade.restart()
    }

    function _moveCursorTo(x, y, done) {
        done = root._guard(done, false)
        var nx = Math.max(4, Math.min(root.width - 8, Number(x)))
        var ny = Math.max(4, Math.min(root.height - 8, Number(y)))
        var dist = Math.sqrt(
            Math.pow(nx - root.agentX, 2) + Math.pow(ny - root.agentY, 2)
        )
        if (dist < 1.0) {
            root.agentX = nx
            root.agentY = ny
            if (typeof done === "function")
                Qt.callLater(done)
            return
        }
        if (moveAnim.running) {
            moveAnim.doneFn = null
            moveAnim.stop()
        }
        moveAnim.doneFn = done
        agentXAnim.from = root.agentX
        agentXAnim.to = nx
        agentYAnim.from = root.agentY
        agentYAnim.to = ny
        var ms = Math.max(160, Math.min(520, 140 + dist * 0.55))
        agentXAnim.duration = ms
        agentYAnim.duration = ms
        moveAnim.start()
    }

    function _parse(raw) {
        try {
            var parsed = JSON.parse(String(raw || "{}"))
            if (parsed && typeof parsed === "object")
                return parsed
        } catch (err) {
        }
        return {}
    }

    onAgentXChanged: root.syncDesk()
    onAgentYChanged: root.syncDesk()
    onAgentCursorShapeChanged: root.syncDesk()
    onReloadNonceChanged: root.reload()
    onVisibleChanged: {
        if (!root.visible)
            root.cancelOperator("", "PANE_HIDDEN")
    }
    Component.onDestruction: root.cancelOperator("", "PANE_DESTROYED")
    onLoadStateChanged: {
        if (root._needLoading && root.loadState === "LOADING")
            root._needLoading = false
        if (
            root._loadDone
            && !root._needLoading
            && (
                root.loadState === "PASS"
                || root.loadState === "FAIL"
                || root.loadState === "BLOCKED"
            )
        ) {
            var fn = root._loadDone
            root._loadDone = null
            loadWaitTimer.stop()
            fn(root.loadState)
        }
        if (root.loadState === "BLOCKED" || root.loadState === "FAIL")
            root.agentShape = "not-allowed"
        else if (root.loadState === "PASS" && !root.operatorBusy)
            root.agentShape = "default"
    }

    function applyPageUrl() {
        var engine = root.liveEngine()
        if (!engine || root._applyingUrl)
            return
        var next = String(root.pageUrl || "")
        var cur = root.currentHref()
        if (next.length === 0 || next === cur)
            return
        if (root.useNativeBrowser && !root.hrefAllowed(next)) {
            root.loadState = "BLOCKED"
            return
        }
        root._abortingLoad = false
        root._loadRetriesLeft = 0
        root.loadFailReason = ""
        engine.url = next
    }

    onPageUrlChanged: root.applyPageUrl()

    Item {
        id: engineHost
        objectName: "webEngineHost"
        anchors.fill: parent

        Loader {
            id: engineLoader
            anchors.fill: parent
            active: root.engineArmed && !root.useNativeBrowser && root.adoptedEngine === null
            sourceComponent: webEngineComp
            onLoaded: root.applyPageUrl()
        }
        Loader {
            id: nativeLoader
            anchors.fill: parent
            active: root.engineArmed && root.useNativeBrowser && root.adoptedEngine === null
            source: {
                if (!active)
                    return ""
                var win = root.Window.window
                var host = win && win.surfaceHost ? win.surfaceHost : null
                return host && host.nativeWebFilteringReady === true
                    ? "WindowsFilteredWebView.qml" : "WindowsWebView.qml"
            }
            onLoaded: {
                item.pane = root
                root.applyPageUrl()
            }
        }
    }

    Component {
        id: popupEngineComp
        WebEngineView {
            anchors.fill: parent
            profile: sessionProfile
            backgroundColor: RuntimeTheme.GGTheme.panel
            settings.javascriptEnabled: true
            settings.localContentCanAccessFileUrls: true
        }
    }

    Component {
        id: webEngineComp
        WebEngineView {
        id: view
        anchors.fill: parent
        profile: sessionProfile
        backgroundColor: RuntimeTheme.GGTheme.panel
        settings.javascriptEnabled: true
        settings.localContentCanAccessFileUrls: true

        Component.onCompleted: root.applyPageUrl()

        onUrlChanged: {
            var href = String(view.url)
            if (href.length === 0)
                return
            root._applyingUrl = true
            root.navigated(href)
            root._applyingUrl = false
        }

        onLoadingChanged: function(loadRequest) {
            root.handleEngineLoad(Number(loadRequest.status), view)
        }

        onNavigationRequested: function(request) {
            var target = String(request.url)
            if (root.hrefAllowed(target)) {
                request.accept()
                return
            }
            var win = Window.window
            var host = win && win.surfaceHost ? win.surfaceHost : null
            var allowed = false
            if (host !== null)
                allowed = root.siteOnly
                    ? host.urlAllowed(target)
                    : host.browseUrlAllowed(target)
            if (!allowed) {
                request.reject()
                root.loadState = "BLOCKED"
                return
            }
            request.accept()
        }

        onNewWindowRequested: function(request) {
            var popup = popupEngineComp.createObject(engineHost)
            if (!popup) {
                request.openIn(view)
                return
            }
            popup.visible = false
            request.openIn(popup)
            root.popupViewReady(popup)
        }
        }
    }

    Rectangle {
        id: hitBox
        objectName: "webAgentHit"
        visible: false
        color: "#22c8a97e"
        border.width: 1
        border.color: RuntimeTheme.GGTheme.accent
        radius: 2
        z: 20
    }

    SequentialAnimation {
        id: hitFade
        PauseAnimation { duration: 420 }
        NumberAnimation {
            target: hitBox
            property: "opacity"
            from: 1
            to: 0
            duration: 280
        }
        ScriptAction {
            script: {
                hitBox.visible = false
                hitBox.opacity = 1
            }
        }
    }

    Rectangle {
        id: ripple
        objectName: "webAgentRipple"
        width: 8
        height: 8
        radius: 4
        z: 21
        visible: false
        color: "#00c8a97e"
        border.width: 2
        border.color: RuntimeTheme.GGTheme.accent
        x: root.agentX - width / 2
        y: root.agentY - height / 2

        function play() {
            ripple.visible = true
            rippleAnim.start()
        }
    }

    SequentialAnimation {
        id: rippleAnim
        ParallelAnimation {
            NumberAnimation {
                target: ripple
                property: "width"
                from: 10
                to: 44
                duration: 220
            }
            NumberAnimation {
                target: ripple
                property: "height"
                from: 10
                to: 44
                duration: 220
            }
            NumberAnimation {
                target: ripple
                property: "radius"
                from: 5
                to: 22
                duration: 220
            }
            NumberAnimation {
                target: ripple
                property: "opacity"
                from: 1
                to: 0
                duration: 220
            }
        }
        ScriptAction {
            script: {
                ripple.visible = false
                ripple.opacity = 1
                ripple.width = 8
                ripple.height = 8
                ripple.radius = 4
            }
        }
    }

    WebAgentCursor { property string uiColorScope: "ui.widget.WebPane.WebAgentCursor.1";
        id: agentCursor
        objectName: "webAgentCursor"
        z: 30
        shape: root.agentCursorShape
        x: root.agentX - agentCursor.hotX
        y: root.agentY - agentCursor.hotY
        opacity: 1
        visible: false
    }

    Rectangle {
        objectName: "webAgentHud"
        z: 31
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.margins: 8
        height: 18
        width: hudLabel.implicitWidth + 12
        color: RuntimeTheme.GGTheme.panel
        border.width: 1
        border.color: RuntimeTheme.GGTheme.edge
        visible: root.operatorLabel.length > 0
        opacity: hudLabel.opacity

        GGText { colorKey: "ui.WebPane.1";
            id: hudLabel
            anchors.centerIn: parent
            text: root.operatorLabel
            color: RuntimeTheme.GGTheme.accent
            font.family: "monospace"
            font.pixelSize: 11
        }
    }

    SequentialAnimation {
        id: hudFade
        PauseAnimation { duration: 1400 }
        NumberAnimation {
            target: hudLabel
            property: "opacity"
            from: 1
            to: 0.35
            duration: 400
        }
    }

    ParallelAnimation {
        id: moveAnim
        property var doneFn: null
        NumberAnimation {
            id: agentXAnim
            target: root
            property: "agentX"
            duration: 280
            easing.type: Easing.InOutCubic
        }
        NumberAnimation {
            id: agentYAnim
            target: root
            property: "agentY"
            duration: 280
            easing.type: Easing.InOutCubic
        }
        onStopped: {
            var fn = moveAnim.doneFn
            moveAnim.doneFn = null
            if (typeof fn === "function")
                fn()
        }
    }

    Timer {
        id: typeTimer
        interval: 32
        repeat: false
        onTriggered: root._typeTick()
    }

    Timer {
        id: loadWaitTimer
        interval: 20000
        repeat: false
        onTriggered: {
            if (root._loadDone) {
                var fn = root._loadDone
                root._loadDone = null
                fn(root.loadState === "IDLE" ? "TIMEOUT" : root.loadState)
            }
        }
    }

    Timer {
        id: pageLoadWatch
        interval: root.pageLoadTimeoutMs
        repeat: false
        onTriggered: root.abortStuckLoad()
    }

    Timer {
        id: scriptWatch
        interval: 2500
        repeat: false
        onTriggered: {
            if (typeof root._scriptOnce === "function")
                root._scriptOnce("")
        }
    }

    Timer {
        id: grabWait
        interval: 90
        repeat: false
        property var _done: null
        onTriggered: {
            var fn = grabWait._done
            grabWait._done = null
            if (typeof fn === "function")
                root._grabViewNow(fn)
        }
    }

    Timer {
        id: busyWatch
        interval: 12000
        repeat: false
        running: root.operatorBusy
        onTriggered: {
            if (root.operatorBusy)
                root._finish(
                    false,
                    "OPERATOR_TIMEOUT",
                    root.currentHref(),
                    "",
                    "",
                    []
                )
        }
    }

    BufferMark { property string uiColorScope: "ui.widget.WebPane.BufferMark.2";
        objectName: "webPaneBuffer"
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 8
        active: root.loadState === "LOADING" || root.operatorBusy
        cell: 6
    }

    GGText { colorKey: "ui.WebPane.2";
        visible: root.loadState === "FAIL" || root.loadState === "BLOCKED"
        anchors.centerIn: parent
        width: parent.width - 40
        horizontalAlignment: Text.AlignHCenter
        text: root.loadState === "BLOCKED"
            ? (
                root.siteOnly
                    ? "URL is outside the local SITE root."
                    : "This address cannot be opened here."
            )
            : (
                root.loadFailReason === "TIMEOUT"
                    ? "Sidan laddade inte inom 60 sekunder. Laddningen avbröts."
                    : "WebEngine could not load this page."
            )
        color: RuntimeTheme.GGTheme.accent
        wrapMode: Text.WordWrap
        font.family: "monospace"
        font.pixelSize: 12
        z: 5
    }
}
