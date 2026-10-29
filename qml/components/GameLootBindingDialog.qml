
import "." as RuntimeTheme
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
    palette.windowText:RuntimeTheme.GGTheme.bright;palette.text:RuntimeTheme.GGTheme.bright
    palette.button:RuntimeTheme.GGTheme.selected;palette.buttonText:RuntimeTheme.GGTheme.bright
    background:Rectangle {color:RuntimeTheme.GGTheme.raised;border.color:RuntimeTheme.GGTheme.edge;radius:5}
    onVisibleChanged:if(visible)Qt.callLater(function(){if(dialog.visible)game.clearMovementInput()})
    function answer(accept) {
        if(!question)return
        var command={kind:"service",op:accept ? "LootBindConfirm" : "LootBindCancel",
            loot_session:Number(game.loot.session),source:String(game.loot.container_id),item:question.item}
        game.applyItemAction(game.surfaceHost.gameEngineClientControl(JSON.stringify(command)))
    }
    contentItem:GGLabel { colorKey: "ui.GameLootBindingDialog.1";
        text:(dialog.question ? dialog.question.name : "")+" binds till den här karaktären när du plockar upp det."
        wrapMode:Text.WordWrap
    }
    footer:DialogButtonBox {
        Button { property string uiColorScope: "ui.control.GameLootBindingDialog.1";objectName:"gameLootBindingAccept";text:"Plocka upp";onClicked:dialog.answer(true)
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignHCenter }
}
        Button { property string uiColorScope: "ui.control.GameLootBindingDialog.2";objectName:"gameLootBindingCancel";text:"Avbryt";onClicked:dialog.answer(false)
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignHCenter }
}
    }
}
