
import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

TextField {
    id: root

    color: RuntimeTheme.GGTheme.bright
    placeholderTextColor: RuntimeTheme.GGTheme.dim
    selectedTextColor: RuntimeTheme.GGTheme.bright
    selectionColor: RuntimeTheme.GGTheme.selected
    font.family: "monospace"
    font.pixelSize: 12
    selectByMouse: true
    leftPadding: 8
    rightPadding: 8
    topPadding: 4
    bottomPadding: 4
    implicitHeight: 26

    background: Rectangle {
        color: RuntimeTheme.GGTheme.canvas
        border.width: 1
        border.color: root.activeFocus ? RuntimeTheme.GGTheme.dim : RuntimeTheme.GGTheme.edge
        radius: 2
        antialiasing: false
    }
}
