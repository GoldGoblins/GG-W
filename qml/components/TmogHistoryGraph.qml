import QtQuick

Item {
    id: root

    property var values: []
    property var overlayValues: []
    property color stroke: "#8db89a"
    property color overlayStroke: "#c8a97e"
    property color fill: "#1c2a22"
    property real yMax: 100
    property bool selectable: false
    property bool rangeActive: false
    property real rangeStart: 0.72
    property real rangeEnd: 1.0
    property bool dragging: false
    signal rangeSelected(real start, real end)

    function clamp(value) {
        return Math.max(0, Math.min(1, Number(value || 0)))
    }

    function updateRange(x) {
        var point = root.width > 0 ? root.clamp(x / root.width) : 0
        if (!root.dragging)
            return
        root.rangeEnd = point
    }

    TmogSpark {
        anchors.fill: parent
        values: root.values
        yMax: root.yMax
        stroke: root.stroke
        fill: root.fill
    }

    TmogSpark {
        anchors.fill: parent
        visible: root.overlayValues && root.overlayValues.length > 0
        values: root.overlayValues
        yMax: root.yMax
        stroke: root.overlayStroke
        fill: "#00000000"
    }

    Rectangle {
        visible: root.selectable && (root.rangeActive || root.dragging)
        x: Math.min(root.rangeStart, root.rangeEnd) * root.width
        width: Math.max(2, Math.abs(root.rangeEnd - root.rangeStart) * root.width)
        y: 0
        height: root.height
        color: "#6f9d9a33"
        border.color: "#8db89a"
        border.width: 1
    }

    MouseArea {
        anchors.fill: parent
        enabled: root.selectable
        hoverEnabled: true
        cursorShape: Qt.CrossCursor
        onPressed: function(mouse) {
            root.dragging = true
            var point = root.width > 0 ? root.clamp(mouse.x / root.width) : 0
            root.rangeStart = point
            root.rangeEnd = point
        }
        onPositionChanged: function(mouse) {
            root.updateRange(mouse.x)
        }
        onReleased: {
            root.dragging = false
            var start = Math.min(root.rangeStart, root.rangeEnd)
            var end = Math.max(root.rangeStart, root.rangeEnd)
            root.rangeStart = start
            root.rangeEnd = end
            root.rangeSelected(start, end)
        }
    }
}
