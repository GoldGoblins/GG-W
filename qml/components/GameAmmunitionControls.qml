
import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

Column {
    id: panel
    property var game: null
    property var targetItem: null
    readonly property var recipes: game ? game.crafting.ammunition_recipes || [] : []
    readonly property var recipe: recipes[ammoPicker.currentIndex] || ({})
    readonly property var station: game ? (game.crafting.workstations || []).filter(
        function(row) { return row.id === "station.workbench" })[0] : null
    readonly property bool nearby: !!station && Math.hypot(game.player.x-station.x,
        game.player.z-station.z,game.player.y-station.y-.65)<=3.75
    spacing: 5
    onTargetItemChanged: {
        if (!targetItem || !targetItem.firearm) return
        for (var i=0;i<recipes.length;++i)
            if (recipes[i].ammo_id===targetItem.firearm.ammo_id) { ammoPicker.currentIndex=i;return }
    }
    GGText { colorKey: "ui.GameAmmunitionControls.1";
        text: "AMMUNITION · ARBETSBÄNK"
        color: RuntimeTheme.GGTheme.orange; font.family: "monospace"; font.bold: true
    }
    ComboBox { property string uiColorScope: "ui.control.GameAmmunitionControls.1";
        id: ammoPicker
        objectName: "gameAmmoRecipePicker"
        width: parent.width; implicitHeight: 30
        model: panel.recipes; textRole: "name"
        palette.text: RuntimeTheme.GGTheme.text; palette.buttonText: RuntimeTheme.GGTheme.text
        palette.base: "#172126"; palette.button: "#28383b"
        palette.highlight: "#75613b"; palette.highlightedText: "#fff1c7"
    
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignLeft }
}
    GGText { colorKey: "ui.GameAmmunitionControls.2";
        width: parent.width
        text: "Tillverkar " + String(panel.recipe.quantity || 0) + " ammunition. Kostnad: "
            +Object.keys(panel.recipe.inputs || {}).map(function(k) {
                return panel.recipe.inputs[k]+" "+k.replace("material.","").replace(/_/g," ")
            }).join(" + ")
            +(panel.nearby ? " · Arbetsbänken är inom räckhåll." : " · Gå till arbetsbänken i startlägret.")
        color: "#b5c9a1"; font.pixelSize: 11; wrapMode: Text.WordWrap
    }
    GgButton { property string uiColorScope: "ui.control.GameAmmunitionControls.2";
        objectName: "gameCraftAmmunition"
        width: parent.width
        text: "TILLVERKA "+String(panel.recipe.name || "AMMUNITION").toUpperCase()
        enabled: panel.nearby && !!panel.recipe.id && !!panel.recipe.can_craft
        onClicked: panel.game.craftGear(panel.recipe.id,"station.workbench")
    }
}
