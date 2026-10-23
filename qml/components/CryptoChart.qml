import QtQuick
import QtWebEngine

Item {
    id: root
    objectName: "cryptoTape"
    property var points: []
    property var markers: []
    property var equity: []

    property string lastPayload: ""
    property bool painted: false
    property bool live: false

    function payloadJson() {
        return JSON.stringify({
            "points": root.points || [],
            "markers": root.markers || [],
            "equity": root.equity || []
        })
    }

    function push() {
        if (!engineLoader.item)
            return
        var raw = root.payloadJson()
        if (raw === root.lastPayload && root.painted)
            return
        engineLoader.item.runJavaScript(
            "(function(){ return window.setTape ? window.setTape(" + raw + ") : 0 })()",
            function(count) {
                var n = Number(count || 0)
                root.painted = n > 1
                if (n > 0)
                    root.lastPayload = raw
                else
                    root.lastPayload = ""
            }
        )
    }

    function fit() {
        if (!engineLoader.item)
            return
        engineLoader.item.runJavaScript("window.fitTape ? window.fitTape() : 0")
    }

    onPointsChanged: Qt.callLater(root.push)
    onMarkersChanged: Qt.callLater(root.push)
    onEquityChanged: Qt.callLater(root.push)
    onWidthChanged: Qt.callLater(root.fit)
    onHeightChanged: Qt.callLater(root.fit)
    onVisibleChanged: {
        if (visible) {
            Qt.callLater(root.push)
            Qt.callLater(root.fit)
        }
    }

    Timer {
        interval: 150
        repeat: true
        running: root.visible && fitBurst.ticks < 6
        onTriggered: {
            fitBurst.ticks += 1
            root.fit()
            if (!root.painted)
                root.push()
        }
    }
    QtObject { id: fitBurst; property int ticks: 0 }

    Loader {
        id: engineLoader
        anchors.fill: parent
        active: root.live
        visible: root.visible && root.width > 8 && root.height > 8
        sourceComponent: tapeEngine
    }

    Component {
        id: tapeEngine
        WebEngineView {
            backgroundColor: "#161616"
            lifecycleState: WebEngineView.LifecycleState.Active
            url: Qt.resolvedUrl("../crypto-hole/index.html")
            settings.javascriptEnabled: true
            settings.localContentCanAccessFileUrls: true
            onLoadingChanged: function(loadRequest) {
                if (Number(loadRequest.status) === WebEngineView.LoadSucceededStatus) {
                    Qt.callLater(root.push)
                    Qt.callLater(root.fit)
                }
            }
            onNavigationRequested: function(request) {
                var href = String(request.url)
                if (href.indexOf("file:") === 0)
                    request.accept()
                else
                    request.reject()
            }
        }
    }
}
