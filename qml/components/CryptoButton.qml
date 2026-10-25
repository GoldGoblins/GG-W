import QtQuick
import QtQuick.Controls

// Scoped to the crypto workspace; the desktop's shared controls stay independent.
Button {
    id: control
    property bool primary: false
    property bool destructive: false
    property string tip: ""
    property color color: destructive ? "#c98989" : primary || checked ? "#e6edf3" : "#c8cdd4"
    property int horizontalAlignment: Text.AlignHCenter
    property int wrapMode: Text.NoWrap
    implicitWidth: Math.max(56, contentItem.implicitWidth + leftPadding + rightPadding)
    implicitHeight: 28
    leftPadding: 8
    rightPadding: 8
    topPadding: 5
    bottomPadding: 5
    focusPolicy: Qt.StrongFocus
    hoverEnabled: true
    font.family: "monospace"
    font.pixelSize: 12
    Accessible.name: text
    ToolTip.visible: hovered && tip.length > 0
    ToolTip.text: tip
    ToolTip.delay: 600
    background: Rectangle {
        radius: control.flat ? 4 : 2
        color: control.down ? "#1c1c1c" : control.flat
            ? (control.checked ? "#34383d" : control.hovered ? "#242424" : "transparent")
            : control.checked ? "#1a1a1a" : "#161616"
        border.width: 1
        border.color: control.visualFocus ? "#8a8a8a" : control.flat ? "transparent"
            : control.hovered || control.checked ? "#8a8a8a" : "#6a6a6a"
        antialiasing: false
        opacity: control.enabled ? 1 : 0.45
    }
    contentItem: Text {
        text: control.text
        textFormat: Text.PlainText
        font: control.font
        color: control.enabled ? control.color : "#7c7c7c"
        horizontalAlignment: control.horizontalAlignment
        verticalAlignment: Text.AlignVCenter
        wrapMode: control.wrapMode
        elide: Text.ElideRight
    }
}
