pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Window
import GG.NativeWeb 1.0

Item {
    id: root
    objectName: "windowsWebView"
    property var pane: null
    property alias url: browser.url
    // Qt WebView's Windows backend misses same-document history changes.
    // Keep the observed document URL separate from the navigation setter.
    property url currentUrl: ""
    property string reportedUrl: ""
    readonly property alias title: browser.title
    readonly property alias canGoBack: browser.canGoBack
    readonly property alias canGoForward: browser.canGoForward
    readonly property bool nativeBrowser: true
    readonly property bool blockerAvailable: true
    readonly property alias blockerReady: browser.blockerReady
    readonly property alias blockerEnabled: browser.blockerEnabled
    readonly property alias blockerError: browser.blockerError
    function toggleBlocker() { browser.toggleBlocker() }
    function openBlockerSettings() { browser.openBlockerSettings() }
    property bool bridgePending: false
    property int navigationEpoch: 0
    readonly property var appWindow: Window.window
    readonly property bool obscured: Boolean(root.appWindow && (
        root.appWindow.walletOpen || root.appWindow.settingsOpen
        || root.appWindow.commandPaletteOpen || root.appWindow.shellLoading))

    function runJavaScript(script, callback) {
        browser.runJavaScript(script, function(value) {
            if (typeof callback === "function")
                callback(value)
        })
    }
    function reload() { browser.reload() }
    function stop() { browser.stop() }
    function goBack() { browser.goBack() }
    function goForward() { browser.goForward() }

    function allowed(href) {
        return root.pane && root.pane.hrefAllowed(String(href || ""))
    }

    function observeUrl(href) {
        href = String(href || "")
        if (!href.length || !root.pane)
            return
        if (!root.allowed(href)) {
            browser.stop()
            root.pane.loadState = "BLOCKED"
            return
        }
        root.currentUrl = href
        if (href === root.reportedUrl)
            return
        root.reportedUrl = href
        root.pane._applyingUrl = true
        root.pane.navigated(href)
        root.pane._applyingUrl = false
    }

    // The native child window is above the Qt scene. Draw GG's gold pointer
    // in the document and relay links to GG's existing tab controller.
    function syncBridge() {
        if (root.bridgePending || browser.loading || !root.visible || root.obscured)
            return
        var win = root.appWindow
        var position = win && win.contentItem && win.deskX !== undefined
            ? root.mapFromItem(win.contentItem, Number(win.deskX), Number(win.deskY))
            : Qt.point(-30, -30)
        var show = position.x >= 0 && position.y >= 0
            && position.x < root.width && position.y < root.height
        var state = JSON.stringify({x: position.x, y: position.y, show: show})
        var epoch = root.navigationEpoch
        root.bridgePending = true
        browser.runJavaScript("(function(s){"
            + "if(!document.documentElement)return '[]';"
            + "var b=window.__ggNativeBridge;"
            + "if(!b){b={tabs:[]};window.__ggNativeBridge=b;"
            + "function tab(u){try{u=new URL(String(u||'about:blank'),location.href).href;"
            + "if(b.tabs.length<8)b.tabs.push(u);}catch(e){}}"
            + "function link(e){var a=e.target&&e.target.closest?e.target.closest('a[href]'):null;"
            + "if(a&&(a.target==='_blank'||e.ctrlKey||e.metaKey||e.button===1)){"
            + "e.preventDefault();e.stopImmediatePropagation();tab(a.href);}}"
            + "document.addEventListener('click',link,true);document.addEventListener('auxclick',link,true);"
            + "}"
            + "var c=document.getElementById('__ggNativePointer');"
            + "if(!c){c=document.createElement('div');c.id='__ggNativePointer';"
            + "Object.assign(c.style,{position:'fixed',width:'17px',height:'23px',"
            + "background:'#c8a97e',clipPath:'polygon(0 0,0 84%,25% 64%,44% 100%,60% 91%,41% 57%,77% 57%)',"
            + "pointerEvents:'none',zIndex:'2147483647'});"
            + "document.documentElement.appendChild(c);}"
            + "c.style.left=(s.x-2)+'px';c.style.top=(s.y-2)+'px';c.style.display=s.show?'block':'none';"
            + "return JSON.stringify({href:location.href,tabs:b.tabs.splice(0,8)});"
            + "})(" + state + ")", function(raw) {
                if (epoch !== root.navigationEpoch)
                    return
                root.bridgePending = false
                if (browser.loading)
                    return
                var state = {}
                try { state = JSON.parse(String(raw || "{}")) } catch (err) {}
                root.observeUrl(state.href)
                var tabs = state.tabs || []
                for (var i = 0; i < tabs.length; ++i) {
                    if (root.allowed(tabs[i]))
                        root.pane.openNewTab(String(tabs[i]))
                }
            })
    }

    GGNativeWebView {
        id: browser
        objectName: "nativeBrowserContent"
        anchors.fill: parent
        visible: !root.obscured
        onNewWindowRequested: function(href) {
            if (root.allowed(href))
                root.pane.openNewTab(href)
        }
        onUrlChanged: root.observeUrl(browser.url)
        onTitleChanged: {
            if (root.pane)
                root.pane.titled(String(browser.title || ""))
        }
        onLoadingChanged: function(request) {
            if (request.status === 0)
                root.navigationEpoch += 1
            root.bridgePending = false
            if (!root.pane)
                return
            if (request.status === 0 && !root.allowed(request.url)) {
                browser.stop()
                root.pane.loadState = "BLOCKED"
                return
            }
            root.pane.handleEngineLoad(Number(request.status), root)
            if (request.status === 2)
                root.syncBridge()
        }
    }

    Timer {
        interval: 16
        repeat: true
        running: root.visible && !root.obscured
        onTriggered: root.syncBridge()
    }
}
