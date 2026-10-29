
import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id:room
    required property var game
    readonly property var state:game.localServiceState.dressup || ({})
    objectName:"gameDressingRoom"
    parent:game;visible:state.open===true
    modal:true;focus:true;closePolicy:Popup.CloseOnEscape
    title:"GG · Provrum"
    width:Math.min(540,game.width-24);height:Math.min(590,game.height-24)
    x:(game.width-width)/2;y:(game.height-height)/2
    palette.windowText:RuntimeTheme.GGTheme.bright;palette.text:RuntimeTheme.GGTheme.bright;palette.button:RuntimeTheme.GGTheme.selected;palette.buttonText:RuntimeTheme.GGTheme.bright
    background:Rectangle { color:RuntimeTheme.GGTheme.raised;border.color:RuntimeTheme.GGTheme.edge;radius:5 }
    onOpened:Qt.callLater(function(){if(room.visible)game.clearMovementInput()})
    onClosed:Qt.callLater(function(){if(!room.visible && room.state.open)room.command("DressupClose")})
    function command(op,fields) {
        var data=fields || ({});data.kind="service";data.op=op
        var result=JSON.parse(game.surfaceHost.gameEngineClientControl(JSON.stringify(data)))
        game.localServiceState=((result.player || {}).client_controls || {}).services || game.localServiceState
    }
    contentItem:ColumnLayout {
        spacing:8
        Loader {
            Layout.fillWidth:true;Layout.fillHeight:true;active:room.visible
            sourceComponent:GameCharacterPreview { property string uiColorScope: "ui.widget.GameDressingRoom.GameCharacterPreview.1";
                objectName:"gameDressingPreview";game:room.game
                equipment:room.state.equipment || [];avatarYaw:room.state.angle || 0
            }
        }
        GGLabel { colorKey: "ui.GameDressingRoom.1"; text:"Du provar utseendet. Din utrustning och ryggsäck påverkas inte.";wrapMode:Text.WordWrap;Layout.fillWidth:true }
        RowLayout {
            Layout.alignment:Qt.AlignHCenter
            Button { property string uiColorScope: "ui.control.GameDressingRoom.1"; objectName:"gameDressingLeft";text:"↶";onClicked:room.command("DressupRotate",{angle:(room.state.angle || 0)-30}) 
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignHCenter }
}
            Button { property string uiColorScope: "ui.control.GameDressingRoom.2"; objectName:"gameDressingUndress";text:"Ta av kläder";onClicked:room.command("DressupUndress") 
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignHCenter }
}
            Button { property string uiColorScope: "ui.control.GameDressingRoom.3"; objectName:"gameDressingReset";text:"Återställ";onClicked:room.command("DressupDress") 
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignHCenter }
}
            Button { property string uiColorScope: "ui.control.GameDressingRoom.4"; objectName:"gameDressingRight";text:"↷";onClicked:room.command("DressupRotate",{angle:(room.state.angle || 0)+30}) 
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignHCenter }
}
        }
    }
    footer:DialogButtonBox { standardButtons:DialogButtonBox.Close;onRejected:room.command("DressupClose") }
}
