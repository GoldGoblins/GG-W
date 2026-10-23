import QtQuick
import QtQuick.Controls

TextField {
    id: root

    color: "#e6e6e6"
    placeholderTextColor: "#5d6670"
    selectedTextColor: "#f2f2f2"
    selectionColor: "#3a3a3a"
    font.family: "monospace"
    font.pixelSize: 12
    selectByMouse: true
    leftPadding: 8
    rightPadding: 8
    topPadding: 4
    bottomPadding: 4
    implicitHeight: 26

    background: Rectangle {
        color: "#121212"
        border.width: 1
        border.color: root.activeFocus ? "#8a8a8a" : "#6a6a6a"
        radius: 2
        antialiasing: false
    }
}
