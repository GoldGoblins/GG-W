import QtQuick
import QtQuick.Controls

ScrollBar {
    id: root

    property bool keepVisible: false
    policy: ScrollBar.AsNeeded
    interactive: true
    padding: 0
    implicitWidth: 6
    implicitHeight: 6

    contentItem: Rectangle {
        implicitWidth: 4
        implicitHeight: 4
        radius: 1
        color: root.pressed ? "#c8cdd4" : "#8a8a8a"
        visible: root.size < 0.999
            && (root.keepVisible || root.active || root.hovered)
        opacity: root.pressed || root.hovered ? 1 : 0.8
        antialiasing: false
    }

    background: Item {
        implicitWidth: 6
        implicitHeight: 6
    }
}
