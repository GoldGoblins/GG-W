
import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

CheckBox { property string uiColorScope: "ui.control.CryptoToggle.1";
    id:control
    implicitWidth:label.implicitWidth+30; implicitHeight:Math.max(28,label.implicitHeight+8)
    leftPadding:25; rightPadding:2; topPadding:4; bottomPadding:4
    focusPolicy:Qt.StrongFocus; hoverEnabled:true
    indicator:Rectangle {
        width:14; height:14; x:3; anchors.verticalCenter:parent.verticalCenter
        radius:2; color:RuntimeTheme.GGTheme.panel; border.color:control.visualFocus || control.hovered ? RuntimeTheme.GGTheme.muted : RuntimeTheme.GGTheme.dim
        Rectangle { GGColorTarget { colorKey: "ui.fill.CryptoToggle.1"; } anchors.centerIn:parent; width:6; height:6; radius:1; color:RuntimeTheme.GGTheme.accent; visible:control.checked }
    }
    contentItem:GGText { colorKey: "ui.CryptoToggle.1"; id:label; text:control.text; font.family:"monospace"; font.pixelSize:11; color:control.enabled ? RuntimeTheme.GGTheme.text : RuntimeTheme.GGTheme.dim; wrapMode:Text.WordWrap; textFormat:Text.PlainText; verticalAlignment:Text.AlignVCenter }
}
