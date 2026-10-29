import "." as RuntimeTheme
import QtQuick

// The wallet uses the same 64-colour menu and controls as other UI elements.
// Canonical asset identity preserves network separation and legacy choices.
GGColorPopup {
    id: root
    objectName: "walletTokenColorPicker"
    property string assetId: ""
    property string symbol: ""
    signal colorChosen(string assetId, string color)

    function showFor(asset, name, color) {
        assetId=String(asset || "");symbol=String(name || "Tillgång")
        targetLabel="FÄRG FÖR "+symbol
        selectionTarget=null
        var owner=parent
        openTarget("ui.asset."+assetId,"",-1,-1,String(color),false,
                   owner?Math.max(8,(owner.width-width)/2):8,100)
    }
    function choose(color) {
        if(!assetId || !RuntimeTheme.GGTheme.validColor(color))return
        if(RuntimeTheme.GGColorContext.backend && !RuntimeTheme.GGColorContext.choose(targetKey,"",-1,-1,color,true))return
        // Keep the existing asset registry in sync for other wallet views.
        colorChosen(assetId,color)
        close()
    }
    function resetTarget() {
        if(!assetId)return
        if(RuntimeTheme.GGColorContext.backend && !RuntimeTheme.GGColorContext.reset(targetKey))return
        colorChosen(assetId,RuntimeTheme.GGTheme.defaultColor(assetId))
        close()
    }
}
