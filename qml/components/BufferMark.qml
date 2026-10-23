import QtQuick

Item {
    id: root
    objectName: "bufferMark"

    property bool active: false
    property int cells: 4
    property int cell: 5
    property int gap: 2
    property color markColor: "#c8a97e"
    property int _on: 0

    visible: root.active
    implicitWidth: root.active
        ? (root.cells * root.cell + (root.cells - 1) * root.gap)
        : 0
    implicitHeight: root.cell
    width: implicitWidth
    height: implicitHeight
    clip: true

    onActiveChanged: {
        if (root.active)
            root._on = 0
    }

    Row {
        spacing: root.gap
        Repeater {
            model: root.cells
            delegate: Rectangle {
                required property int index
                width: root.cell
                height: root.cell
                color: root.markColor
                opacity: index === root._on ? 1 : 0.18
            }
        }
    }

    Timer {
        interval: 110
        running: root.active
        repeat: true
        onTriggered: root._on = (root._on + 1) % root.cells
    }
}
