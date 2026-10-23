import QtQuick
import QtQuick.Controls
import "engine/WorldFx.js" as WorldFx

Column {
    id: panel
    property var game: null
    readonly property var targetItem: game ? (game.items.inventory || []).concat(game.items.equipment || []).filter(
        function(row) { return row.instance_id === panel.game.selectedItemId })[0] : null
    spacing: 5
    component EnchantPicker: ComboBox {
        id: picker
        implicitHeight: 30
        font.family: "monospace"
        font.pixelSize: 11
        palette.text: "#ead4a0"
        palette.buttonText: "#ead4a0"
        palette.base: "#172126"
        palette.button: "#28383b"
        palette.highlight: "#75613b"
        palette.highlightedText: "#fff1c7"
        background: Rectangle { color: "#28383b"; border.color: "#88724c"; radius: 2 }
        contentItem: Text {
            text: picker.displayText
            color: "#ead4a0"
            font: picker.font
            leftPadding: 8
            rightPadding: 26
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
    }
    Text {
        width: parent.width
        text: "ENCHANTING · SKAPA EGNA SCROLLS"
        color: "#e5c785"
        font.family: "monospace"
        font.bold: true
    }
    EnchantPicker {
        objectName: "gameEnchantRecipeMode"
        width: parent.width
        model: ["Vapen: offensiv / försvar / återhämtning", "Gear: stat boosts"]
        currentIndex: panel.game.enchantRecipeMode
        onActivated: panel.game.enchantRecipeMode = currentIndex
    }
    EnchantPicker {
        objectName: "gameEnchantPrimaryPicker"
        width: parent.width
        visible: panel.game.enchantRecipeMode === 0
        model: WorldFx.ENCHANT_CHOICES.map(function(row) {
            return "T" + row.tier + " · " + row.style.replace(/_/g, " / ") + " · " + row.families.join(" + ") + " · " + row.name
        })
        currentIndex: panel.game.enchantPrimaryIndex
        onActivated: panel.game.enchantPrimaryIndex = currentIndex
    }
    EnchantPicker {
        objectName: "gameEnchantSecondPicker"
        width: parent.width
        visible: panel.game.enchantRecipeMode === 0
            && WorldFx.ENCHANT_CHOICES[panel.game.enchantPrimaryIndex].tier === 1
        model: ["Andra effekt: ingen"].concat(WorldFx.singleChoices().map(
            function(row) { return row.style + " · " + row.name }))
        currentIndex: panel.game.enchantSecondIndex
        onActivated: panel.game.enchantSecondIndex = currentIndex
    }
    EnchantPicker {
        objectName: "gameEnchantThirdPicker"
        width: parent.width
        visible: panel.game.enchantRecipeMode === 0
            && WorldFx.ENCHANT_CHOICES[panel.game.enchantPrimaryIndex].tier === 1
        model: ["Tredje effekt (artifact): ingen"].concat(WorldFx.singleChoices().map(
            function(row) { return row.style + " · " + row.name }))
        currentIndex: panel.game.enchantThirdIndex
        onActivated: panel.game.enchantThirdIndex = currentIndex
    }
    EnchantPicker {
        objectName: "gameEnchantGearPicker"
        width: parent.width
        visible: panel.game.enchantRecipeMode === 1
        model: WorldFx.GEAR_ENCHANT_CHOICES.map(function(row) { return row.description })
        currentIndex: panel.game.enchantGearIndex
        onActivated: panel.game.enchantGearIndex = currentIndex
    }
    Text {
        width: parent.width
        text: String(panel.game.enchantRecipe.description || "")
            + (panel.game.enchantRecipe.tier === 3 ? " · Requires level 60" : "")
        color: "#b5c9a1"
        font.pixelSize: 11
        wrapMode: Text.WordWrap
    }
    Text {
        width: parent.width
        text: "Cost: " + String(panel.game.enchantRecipe.tier || 1) + " fiber + "
            + String(panel.game.enchantRecipe.tier || 1) + " runic oil + "
            + String(panel.game.enchantRecipe.tier === 3 ? 2 : 1) + " moon shard(s)."
            + " Bordet står vid startlägret."
        color: "#abb3a5"
        font.pixelSize: 10
        wrapMode: Text.WordWrap
    }
    GgButton {
        objectName: "gameCraftEnchantScroll"
        text: "SKAPA SCROLL VID ENCHANTING-BORDET"
        width: parent.width
        enabled: !!panel.game.enchantRecipe.id
        onClicked: panel.game.craftGear("recipe.enchant_scroll." + panel.game.enchantRecipe.id,
                                 "station.enchanting_altar")
    }
    EnchantPicker {
        id: scrollInventoryPicker
        currentIndex: panel.game.ownedEnchantScrolls.length > 0
            ? Math.min(panel.game.enchantOwnedScrollIndex, panel.game.ownedEnchantScrolls.length-1) : -1
        onActivated: panel.game.enchantOwnedScrollIndex = currentIndex
        objectName: "gameOwnedEnchantScrollPicker"
        width: parent.width
        model: panel.game.ownedEnchantScrolls
        textRole: "name"
        displayText: currentIndex >= 0 ? currentText : "Inga enchanting-scrolls i väskan"
    }
    GgButton {
        objectName: "gameApplyEnchantScroll"
        width: parent.width
        text: "APPLICERA SCROLL PÅ VALT FÖREMÅL"
        enabled: !!panel.targetItem && !!panel.targetItem.gear && panel.game.selectedEnchantScrollId !== ""
        onClicked: panel.game.enchantGear(panel.game.selectedItemId, panel.game.selectedEnchantScrollId)
    }
    Text {
        width: parent.width
        text: WorldFx.scrollError(String(panel.game.status.error || ""))
        color: "#e69286"
        wrapMode: Text.WordWrap
    }
}
