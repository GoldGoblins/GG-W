
import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

Dialog {
    id:dialog
    required property var game
    readonly property var binding:game.localServiceState.item_binding || ({})
    readonly property var question:binding.use || (binding.equips || []).slice(-1)[0] || null
    property string error:""
    objectName:"gameItemBindingDialog"
    parent:game
    visible:!!question
    modal:true;focus:true;closePolicy:Popup.NoAutoClose
    title:"Bind föremålet till karaktären?"
    width:Math.min(440,game.width-24)
    height:Math.min(220,game.height-24)
    x:(game.width-width)/2;y:(game.height-height)/2
    palette.windowText:RuntimeTheme.GGTheme.bright;palette.text:RuntimeTheme.GGTheme.bright
    palette.button:RuntimeTheme.GGTheme.selected;palette.buttonText:RuntimeTheme.GGTheme.bright
    background:Rectangle { color:RuntimeTheme.GGTheme.raised;border.color:RuntimeTheme.GGTheme.edge;radius:5 }
    onVisibleChanged:if(visible)Qt.callLater(function(){if(dialog.visible)game.clearMovementInput()})
    onQuestionChanged:error=""
    function answer(accept) {
        if (!question) return
        var command={kind:"service",binding_generation:binding.generation}
        if (question.kind==="USE_BIND_CONFIRM")command.op=accept ? "ItemBindingUseConfirm" : "ItemBindingUseCancel"
        else {command.op="ItemBindingEquipAnswer";command.index=question.index;command.accept=accept}
        var result=JSON.parse(game.surfaceHost.gameEngineClientControl(JSON.stringify(command)))
        game.localServiceState=((result.player || {}).client_controls || {}).services || game.localServiceState
        if(result.error)error="Åtgärden kunde inte sparas eller föremålet har ändrats. Försök igen eller avbryt."
        game.refresh()
    }
    contentItem:GGLabel { colorKey: "ui.GameItemBindingDialog.1";
        text:(dialog.question ? dialog.question.name : "")+" blir bundet när du använder eller utrustar det. Föremålet kan sedan inte skickas eller handlas till en annan karaktär."
            +(dialog.error ? "\n\n"+dialog.error : "")
        wrapMode:Text.WordWrap
    }
    footer:DialogButtonBox {
        Button { property string uiColorScope: "ui.control.GameItemBindingDialog.1"; objectName:"gameItemBindingAccept";text:"Bind och fortsätt";onClicked:dialog.answer(true) 
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignHCenter }
}
        Button { property string uiColorScope: "ui.control.GameItemBindingDialog.2"; objectName:"gameItemBindingCancel";text:"Avbryt";onClicked:dialog.answer(false) 
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignHCenter }
}
    }
}
