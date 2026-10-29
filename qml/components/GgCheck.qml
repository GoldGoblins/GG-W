
import "." as RuntimeTheme
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
        color: root.checked ? RuntimeTheme.GGTheme.raised : RuntimeTheme.GGTheme.canvas
        border.width: 1
        border.color: root.checked ? RuntimeTheme.GGTheme.text : RuntimeTheme.GGTheme.edge
        radius: 1
        antialiasing: false

        Rectangle {
            visible: root.checked
            anchors.centerIn: parent
            width: 6
            height: 6
            color: RuntimeTheme.GGTheme.bright
            antialiasing: false
        }
    }

    GGText { colorKey: "ui.GgCheck.1";
        id: label
        anchors.left: box.right
        anchors.leftMargin: 8
        anchors.verticalCenter: parent.verticalCenter
        text: root.text
        color: RuntimeTheme.GGTheme.bright
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
