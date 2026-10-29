
import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

Dialog {
    id:dialog
    required property var game
    readonly property var cursor:game.localServiceState.item_targeting || ({})
    property string error:""
    objectName:"gameEnchantingDialog"
    parent:game
    visible:cursor.active===true && (cursor.stage==="BIND" || cursor.stage==="REPLACE")
    modal:true;focus:true;closePolicy:Popup.NoAutoClose
    width:Math.min(440,game.width-24);height:Math.min(240,game.height-24)
    x:(game.width-width)/2;y:(game.height-height)/2
    title:cursor.stage==="BIND" ? "Bind föremålet med enchanting?" : "Ersätt föremålets enchant?"
    palette.windowText:RuntimeTheme.GGTheme.bright;palette.text:RuntimeTheme.GGTheme.bright;palette.button:RuntimeTheme.GGTheme.selected;palette.buttonText:RuntimeTheme.GGTheme.bright
    background:Rectangle { color:RuntimeTheme.GGTheme.raised;border.color:RuntimeTheme.GGTheme.edge;radius:5 }
    onVisibleChanged:if(visible)Qt.callLater(function(){if(dialog.visible)game.clearMovementInput()})
    onCursorChanged:error=""
    function answer(accept) {
        var command={kind:"service",target_generation:cursor.generation,
            op:accept ? (cursor.stage==="BIND" ? "EnchantBindConfirm" : "EnchantReplaceConfirm") : "EnchantCancel"}
        var result=JSON.parse(game.surfaceHost.gameEngineClientControl(JSON.stringify(command)))
        game.localServiceState=((result.player || {}).client_controls || {}).services || game.localServiceState
        if(result.error)error="Föremålet eller scrollen har ändrats, eller ändringen kunde inte sparas."
        game.refresh()
    }
    contentItem:GGLabel { colorKey: "ui.GameEnchantingDialog.1";
        text:(dialog.cursor.name || "")+" · "+(dialog.cursor.enchant_name || "")
            +"\n\n"+(dialog.cursor.stage==="BIND" ? "Enchantingen binder föremålet till den här karaktären." : "Den tidigare enchantingen i den permanenta platsen ersätts.")
            +" Scrollen förbrukas när ändringen genomförs."+(dialog.error ? "\n\n"+dialog.error : "")
        wrapMode:Text.WordWrap
    }
    footer:DialogButtonBox {
        Button { property string uiColorScope: "ui.control.GameEnchantingDialog.1"; objectName:"gameEnchantingAccept";text:"Bekräfta";onClicked:dialog.answer(true) 
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignHCenter }
}
        Button { property string uiColorScope: "ui.control.GameEnchantingDialog.2"; objectName:"gameEnchantingCancel";text:"Avbryt";onClicked:dialog.answer(false) 
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignHCenter }
}
    }
}
