import QtQuick
import QtQuick.Controls

Dialog {
    id:dialog
    required property var game
    readonly property var question:game.loot.pending_bind || null
    objectName:"gameLootBindingDialog"
    parent:game;visible:!!question;modal:true;focus:true
    closePolicy:Popup.NoAutoClose
    title:"Plocka upp ett bundet föremål?"
    width:Math.min(420,game.width-24);height:220
    x:(game.width-width)/2;y:(game.height-height)/2
    palette.windowText:"#e9e3d6";palette.text:"#e9e3d6"
    palette.button:"#303137";palette.buttonText:"#e9e3d6"
    background:Rectangle {color:"#202126";border.color:"#92794b";radius:5}
    onVisibleChanged:if(visible)Qt.callLater(function(){if(dialog.visible)game.clearMovementInput()})
    function answer(accept) {
        if(!question)return
        var command={kind:"service",op:accept ? "LootBindConfirm" : "LootBindCancel",
            loot_session:Number(game.loot.session),source:String(game.loot.container_id),item:question.item}
        game.applyItemAction(game.surfaceHost.gameEngineClientControl(JSON.stringify(command)))
    }
    contentItem:Label {
        text:(dialog.question ? dialog.question.name : "")+" binds till den här karaktären när du plockar upp det."
        wrapMode:Text.WordWrap
    }
    footer:DialogButtonBox {
        Button {objectName:"gameLootBindingAccept";text:"Plocka upp";onClicked:dialog.answer(true)}
        Button {objectName:"gameLootBindingCancel";text:"Avbryt";onClicked:dialog.answer(false)}
    }
}
