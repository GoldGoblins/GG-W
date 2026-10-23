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
            ? "#1c1c1c"
            : (root.checked ? "#1a1a1a" : "#161616")
        border.width: 1
        border.color: (
            pressArea.containsMouse || root.checked
        ) ? "#8a8a8a" : "#6a6a6a"
        radius: 2
        antialiasing: false
    }

    Text {
        id: label
        anchors.centerIn: parent
        text: root.text
        color: (
            root.checked || pressArea.containsMouse
        ) ? "#e6e6e6" : "#c8cdd4"
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
