import QtQuick

Rectangle {
    id: action
    property string text: ""
    signal clicked()
    implicitWidth: Math.max(72, label.implicitWidth + 18)
    implicitHeight: 28
    radius: 2
    opacity: enabled ? 1 : 0.44
    color: pointer.pressed ? "#80643a" : (pointer.containsMouse ? "#4a3d2c" : "#2b302f")
    border.color: pointer.containsMouse ? "#e5be70" : "#8d7750"
    border.width: 1

    Rectangle {
        anchors.fill: parent
        anchors.margins: 3
        color: "transparent"
        border.color: "#465451"
        border.width: 1
    }
    GGText { colorKey: "ui.GameInventoryAction.1";
        id: label
        anchors.centerIn: parent
        text: action.text
        color: pointer.containsMouse ? "#ffe4a2" : "#e4d2a9"
        font.family: "serif"
        font.pixelSize: 11
        font.bold: true
    }
    MouseArea {
        id: pointer
        anchors.fill: parent
        enabled: action.enabled
        hoverEnabled: true
        cursorShape: action.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: action.clicked()
    }
}
