import QtQuick

Item {
    id: root

    property string text: ""
    property bool checked: false
    signal toggled()

    implicitWidth: box.width + (label.text.length > 0 ? 8 + label.implicitWidth : 0)
    implicitHeight: 22

    Rectangle {
        id: box
        width: 12
        height: 12
        anchors.verticalCenter: parent.verticalCenter
        color: root.checked ? "#1a1a1a" : "#121212"
        border.width: 1
        border.color: root.checked ? "#c8cdd4" : "#6a6a6a"
        radius: 1
        antialiasing: false

        Rectangle {
            visible: root.checked
            anchors.centerIn: parent
            width: 6
            height: 6
            color: "#e6e6e6"
            antialiasing: false
        }
    }

    Text {
        id: label
        anchors.left: box.right
        anchors.leftMargin: 8
        anchors.verticalCenter: parent.verticalCenter
        text: root.text
        color: "#e6e6e6"
        font.family: "monospace"
        font.pixelSize: 12
        wrapMode: Text.NoWrap
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
