
import "." as RuntimeTheme
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
        color: root.checked ? "#1c2a22" : RuntimeTheme.GGTheme.canvas
        border.width: 1
        border.color: root.checked ? RuntimeTheme.GGTheme.positive : RuntimeTheme.GGTheme.edge
        radius: 2
        antialiasing: false

        Rectangle { GGColorTarget { colorKey: "ui.fill.GgSwitch.1"; }
            width: 8
            height: 8
            y: 3
            x: root.checked ? track.width - 11 : 3
            color: root.checked ? RuntimeTheme.GGTheme.positive : RuntimeTheme.GGTheme.dim
            antialiasing: false
        }
    }

    GGText { colorKey: "ui.GgSwitch.1";
        id: label
        anchors.left: track.right
        anchors.leftMargin: 8
        anchors.verticalCenter: parent.verticalCenter
        text: root.text
        color: RuntimeTheme.GGTheme.bright
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
