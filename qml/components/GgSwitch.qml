import QtQuick

Item {
    id: root

    property string text: ""
    property bool checked: false
    signal toggled()

    implicitWidth: track.width + (label.text.length > 0 ? 8 + label.implicitWidth : 0)
    implicitHeight: 22

    Rectangle {
        id: track
        width: 28
        height: 14
        anchors.verticalCenter: parent.verticalCenter
        color: root.checked ? "#1c2a22" : "#121212"
        border.width: 1
        border.color: root.checked ? "#8db89a" : "#6a6a6a"
        radius: 2
        antialiasing: false

        Rectangle {
            width: 8
            height: 8
            y: 3
            x: root.checked ? track.width - 11 : 3
            color: root.checked ? "#8db89a" : "#8a8a8a"
            antialiasing: false
        }
    }

    Text {
        id: label
        anchors.left: track.right
        anchors.leftMargin: 8
        anchors.verticalCenter: parent.verticalCenter
        text: root.text
        color: "#e6e6e6"
        font.family: "monospace"
        font.pixelSize: 12
    }

    MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: {
            root.checked = !root.checked
            root.toggled()
        }
    }
}
