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
    palette.windowText:"#e9e3d6";palette.text:"#e9e3d6";palette.button:"#303137";palette.buttonText:"#e9e3d6"
    background:Rectangle { color:"#202126";border.color:"#92794b";radius:5 }
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
            sourceComponent:GameCharacterPreview {
                objectName:"gameDressingPreview";game:room.game
                equipment:room.state.equipment || [];avatarYaw:room.state.angle || 0
            }
        }
        Label { text:"Du provar utseendet. Din utrustning och ryggsäck påverkas inte.";wrapMode:Text.WordWrap;Layout.fillWidth:true }
        RowLayout {
            Layout.alignment:Qt.AlignHCenter
            Button { objectName:"gameDressingLeft";text:"↶";onClicked:room.command("DressupRotate",{angle:(room.state.angle || 0)-30}) }
            Button { objectName:"gameDressingUndress";text:"Ta av kläder";onClicked:room.command("DressupUndress") }
            Button { objectName:"gameDressingReset";text:"Återställ";onClicked:room.command("DressupDress") }
            Button { objectName:"gameDressingRight";text:"↷";onClicked:room.command("DressupRotate",{angle:(room.state.angle || 0)+30}) }
        }
    }
    footer:DialogButtonBox { standardButtons:DialogButtonBox.Close;onRejected:room.command("DressupClose") }
}
