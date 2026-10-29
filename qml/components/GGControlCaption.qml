import QtQuick
import "." as Shared

// A retained native-text caption for Qt controls whose original style supplied
// its own non-customizable QQuickMnemonicLabel. The control keeps its native
// background, indicator, action and keyboard behavior.
GGText {
    property bool withIndicator:false
    colorKey:"ui.control.caption"
    text:parent?String(parent.displayText!==undefined?parent.displayText:parent.text||""):""
    font:parent?parent.font:Qt.font({})
    color:parent&&!parent.enabled?Shared.GGTheme.dim:Shared.GGTheme.text
    horizontalAlignment:Text.AlignHCenter
    verticalAlignment:Text.AlignVCenter
    elide:Text.ElideRight
    textFormat:Text.PlainText
    leftPadding:withIndicator&&parent&&parent.indicator&&!parent.mirrored?parent.indicator.width+parent.spacing:0
    rightPadding:withIndicator&&parent&&parent.indicator&&parent.mirrored?parent.indicator.width+parent.spacing:0
}
