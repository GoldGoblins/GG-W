import QtQuick

Item {
    id: root

    property string activityState: "IDLE"
    property string phase: ""
    property string headline: ""
    property real percentage: -1
    property int elapsedSeconds: -1
    property string lastActivity: ""

    readonly property bool neverSilentWhileBusy: true
    readonly property bool hasRealPercentage:
        root.percentage >= 0 && root.percentage <= 100
    readonly property bool busy:
        ["QUEUED", "STARTING", "RUNNING", "STREAMING", "GENERATING",
         "WAITING", "STOPPING"].indexOf(root.activityState) >= 0
    readonly property string statusText: {
        if (root.headline.length > 0)
            return root.headline
        if (root.lastActivity.length > 0)
            return root.lastActivity
        if (root.phase.length > 0)
            return root.phase
        if (root.activityState.length > 0)
            return root.activityState
        return "Working"
    }

    property int elapsedMs: 0
    property int segmentMs: 0
    property string clockStatus: ""

    implicitHeight: root.busy || root.elapsedSeconds >= 0 ? 22 : 0
    implicitWidth: 260
    visible: implicitHeight > 0
    clip: true

    function pad2(value) {
        return value < 10 ? "0" + value : "" + value
    }

    function formatElapsed(ms) {
        var hundredths = Math.floor(Math.max(0, ms) / 10)
        var minutes = Math.floor(hundredths / 6000)
        var seconds = Math.floor((hundredths % 6000) / 100)
        var rest = hundredths % 100
        return minutes + "m" + root.pad2(seconds) + "." + root.pad2(rest) + "s"
    }

    function formatSegment(ms) {
        var hundredths = Math.floor(Math.max(0, ms) / 10)
        if (hundredths < 6000)
            return Math.floor(hundredths / 100) + "." + root.pad2(hundredths % 100) + "s"
        return root.formatElapsed(ms)
    }

    onBusyChanged: {
        if (root.busy) {
            root.elapsedMs = 0
            root.segmentMs = 0
            root.clockStatus = root.statusText
        }
    }

    onStatusTextChanged: {
        if (!root.busy)
            return
        if (root.statusText === root.clockStatus)
            return
        root.clockStatus = root.statusText
        root.segmentMs = 0
    }

    Timer {
        interval: 100
        repeat: true
        running: root.busy
        onTriggered: {
            root.elapsedMs += interval
            root.segmentMs += interval
        }
    }

    Text {
        id: statusLine
        anchors.left: parent.left
        anchors.right: totalLine.left
        anchors.rightMargin: 8
        anchors.verticalCenter: parent.verticalCenter
        text: ":: " + root.statusText + "  " + root.formatSegment(root.segmentMs)
        color: "#c8a97e"
        font.family: "monospace"
        font.pixelSize: 12
        elide: Text.ElideRight
    }

    Text {
        id: totalLine
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        text: root.formatElapsed(
            root.elapsedSeconds >= 0 && !root.busy
                ? root.elapsedSeconds * 1000
                : root.elapsedMs
        )
        color: "#c8cdd4"
        font.family: "monospace"
        font.pixelSize: 12
    }
}
