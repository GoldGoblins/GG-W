
import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

// Scoped to the crypto workspace; the desktop's shared controls stay independent.
Button { property string uiColorScope: "ui.control.CryptoButton.1";
    id: control
    property bool primary: false
    property bool destructive: false
    property string tip: ""
    property bool quiet: false
    property color color: destructive ? RuntimeTheme.GGTheme.negative : primary || checked ? RuntimeTheme.GGTheme.bright : RuntimeTheme.GGTheme.text
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
    opacity: !quiet || hovered || visualFocus || checked || down ? 1 : 0.65
    ToolTip.visible: hovered && tip.length > 0
    ToolTip.text: tip
    ToolTip.delay: 600
    background: Rectangle {
        radius: control.flat ? 4 : 2
        color: control.down ? RuntimeTheme.GGTheme.panel : control.flat
            ? (control.checked ? RuntimeTheme.GGTheme.line : control.hovered ? RuntimeTheme.GGTheme.raised : "transparent")
            : control.checked ? RuntimeTheme.GGTheme.panel : RuntimeTheme.GGTheme.panel
        border.width: 1
        border.color: control.visualFocus ? RuntimeTheme.GGTheme.muted : control.flat ? "transparent"
            : control.hovered || control.checked ? RuntimeTheme.GGTheme.muted : RuntimeTheme.GGTheme.dim
        antialiasing: false
        opacity: control.enabled ? 1 : 0.45
    }
    contentItem: GGText { colorKey: "ui.CryptoButton.1";
        text: control.text
        textFormat: Text.PlainText
        font: control.font
        color: control.enabled ? control.color : RuntimeTheme.GGTheme.dim
        horizontalAlignment: control.horizontalAlignment
        verticalAlignment: Text.AlignVCenter
        wrapMode: control.wrapMode
        elide: Text.ElideRight
    }
}
