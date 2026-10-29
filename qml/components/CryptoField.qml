
import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

TextField {
    id: control
    color: RuntimeTheme.GGTheme.bright
    placeholderTextColor: RuntimeTheme.GGTheme.muted
    selectedTextColor: RuntimeTheme.GGTheme.bright
    selectionColor: RuntimeTheme.GGTheme.line
    font.family: "monospace"
    font.pixelSize: 12
    selectByMouse: true
    leftPadding: 8
    rightPadding: 8
    topPadding: 5
    bottomPadding: 5
    implicitHeight: 26
    background: Rectangle {
        color: RuntimeTheme.GGTheme.canvas
        border.width: 1
        border.color: control.activeFocus ? RuntimeTheme.GGTheme.muted : RuntimeTheme.GGTheme.dim
        radius: 2
        antialiasing: false
    }
}
