import QtQuick
import QtQuick.Controls

Slider {
    id: root

    implicitHeight: 18
    padding: 0
    live: true

    background: Item {
        x: root.leftPadding
        y: root.topPadding
        implicitWidth: 140
        implicitHeight: 18
        width: root.availableWidth
        height: root.availableHeight

        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width
            height: 4
            color: "#2a2a2a"
            antialiasing: false

            Rectangle {
                width: root.visualPosition * parent.width
                height: parent.height
                color: "#8a8a8a"
                antialiasing: false
            }
        }
    }

    handle: Rectangle {
        x: root.leftPadding
            + root.visualPosition * (root.availableWidth - width)
        y: root.topPadding + (root.availableHeight - height) / 2
        width: 10
        height: 10
        color: root.pressed ? "#e6e6e6" : "#c8cdd4"
        border.width: 1
        border.color: "#6a6a6a"
        antialiasing: false
    }
}
