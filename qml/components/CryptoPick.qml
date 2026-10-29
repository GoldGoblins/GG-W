
import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

ComboBox { property string uiColorScope: "ui.control.CryptoPick.1";
    id:control
    implicitHeight:34; font.family:"monospace"; font.pixelSize:11
    leftPadding:10; rightPadding:28; topPadding:6; bottomPadding:6
    focusPolicy:Qt.StrongFocus; hoverEnabled:true
    contentItem:GGText { colorKey: "ui.CryptoPick.1"; text:control.displayText; font:control.font; color:control.enabled ? RuntimeTheme.GGTheme.text : RuntimeTheme.GGTheme.dim; verticalAlignment:Text.AlignVCenter; elide:Text.ElideMiddle; textFormat:Text.PlainText }
    indicator:GGText { colorKey: "ui.CryptoPick.2"; x:control.width-width-10; anchors.verticalCenter:parent.verticalCenter; text:"⌄"; color:RuntimeTheme.GGTheme.muted; font.pixelSize:15 }
    background:Rectangle { color:RuntimeTheme.GGTheme.panel; border.color:control.visualFocus || control.hovered ? RuntimeTheme.GGTheme.muted : RuntimeTheme.GGTheme.edge; radius:3 }
    delegate:ItemDelegate { property string uiColorScope: "ui.control.CryptoPick.2";
        required property int index
        width:control.width
        contentItem:GGText { colorKey: "ui.CryptoPick.3"; text:control.textAt(index); font:control.font; color:RuntimeTheme.GGTheme.text; elide:Text.ElideRight; textFormat:Text.PlainText }
        highlighted:control.highlightedIndex===index
        background:Rectangle { color:parent.highlighted ? RuntimeTheme.GGTheme.line : RuntimeTheme.GGTheme.panel }
    }
    popup:Popup {
        y:control.height+2; width:control.width; implicitHeight:Math.min(300,list.contentHeight+12); padding:6
        background:Rectangle { color:RuntimeTheme.GGTheme.panel; border.color:RuntimeTheme.GGTheme.edge; radius:3 }
        contentItem:ListView { id:list; clip:true; implicitHeight:contentHeight; model:control.popup.visible ? control.delegateModel : null; currentIndex:control.highlightedIndex; ScrollBar.vertical:ScrollBar {} }
    }
}
