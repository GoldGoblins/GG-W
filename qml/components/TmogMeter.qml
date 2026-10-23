import QtQuick

Item {
    id: root
    property real ratio: 0
    property int segments: 28
    property color onColor: "#8db89a"
    property color offColor: "#2a2a2a"
    height: 14

    Row {
        anchors.fill: parent
        spacing: 2

        Repeater {
            model: Math.max(4, root.segments)
            delegate: Rectangle {
                required property int index
                width: Math.max(
                    2,
                    (root.width - (root.segments - 1) * 2) / root.segments
                )
                height: root.height
                radius: 1
                color: index < Math.round(root.ratio * root.segments)
                    ? root.onColor
                    : root.offColor
            }
        }
    }
}
