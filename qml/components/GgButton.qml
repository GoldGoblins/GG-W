
import "." as RuntimeTheme
import QtQuick

Item {
    id: root

    property string text: ""
    property bool checkable: false
    property bool checked: false
    signal clicked()

    implicitWidth: Math.max(56, label.implicitWidth + 16)
    implicitHeight: 28
    opacity: root.enabled ? 1 : 0.42

    Rectangle {
        anchors.fill: parent
        color: pressArea.pressed
            ? RuntimeTheme.GGTheme.raised
            : (root.checked ? RuntimeTheme.GGTheme.raised : RuntimeTheme.GGTheme.panel)
        border.width: 1
        border.color: (
            pressArea.containsMouse || root.checked
        ) ? RuntimeTheme.GGTheme.dim : RuntimeTheme.GGTheme.edge
        radius: 2
        antialiasing: false
    }

    GGText { colorKey: "ui.GgButton.1";
        id: label
        anchors.centerIn: parent
        text: root.text
        color: (
            root.checked || pressArea.containsMouse
        ) ? RuntimeTheme.GGTheme.bright : RuntimeTheme.GGTheme.text
        font.family: "monospace"
        font.pixelSize: 12
        font.bold: root.checked
    }

    MouseArea {
        id: pressArea
        anchors.fill: parent
        enabled: root.enabled
        hoverEnabled: true
        cursorShape: root.enabled
            ? Qt.PointingHandCursor
            : Qt.ArrowCursor
        onClicked: root.clicked()
    }
}
