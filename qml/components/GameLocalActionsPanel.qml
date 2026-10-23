import QtQuick
import QtQuick.Controls

Item {
    id: panel
    property var game: null
    readonly property var book: game ? (game.crafting.book || ({})) : ({})
    readonly property var loot: game ? game.loot : ({})
    visible: Boolean(book.open || loot.open)

    Rectangle {
        objectName: "ggCraftingWindow"
        visible: Boolean(panel.book.open)
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.rightMargin: 12
        width: Math.min(490, parent.width - 24)
        height: Math.min(530, parent.height - 24)
        color: "#10191d"
        border.color: "#c5a365"
        border.width: 2
        radius: 3
        MouseArea { anchors.fill: parent; onWheel: function(wheel) { wheel.accepted = true } }

        Column {
            anchors.fill: parent
            anchors.margins: 14
            spacing: 10
            Row {
                width: parent.width
                spacing: 8
                Text {
                    width: parent.width - 90
                    text: "◆  TILLVERKNING"
                    color: "#f4d99e"
                    font.family: "serif"
                    font.pixelSize: 18
                    font.bold: true
                }
                GameInventoryAction {
                    objectName: "ggCraftingClose"
                    text: "STÄNG ×"
                    onClicked: panel.game.closeCrafting()
                }
            }
            Row {
                spacing: 8
                GameInventoryAction {
                    objectName: "ggCraftingField"
                    text: "FÄLTRECEPT"
                    onClicked: panel.game.openCrafting("")
                }
                GameInventoryAction {
                    objectName: "ggCraftingStation"
                    text: "NÄRMASTE ARBETSSTATION"
                    onClicked: panel.game.openCrafting("NEAREST")
                }
            }
            Text {
                width: parent.width
                text: Number(panel.book.repeat_count) > 0 ? (panel.game.status.state === "RUNNING" ? "Tillverkar" : "Tillverkningen är pausad") + " · " + panel.book.repeat_count + " återstår"
                      : panel.book.station_id ? "Recept vid den valda arbetsstationen" : "Recept som kan tillverkas direkt i fält"
                color: "#d1bd8f"
                font.pixelSize: 12
                wrapMode: Text.WordWrap
            }
            ListView {
                objectName: "ggCraftingRecipes"
                width: parent.width
                height: Math.max(70, parent.height - 160)
                clip: true
                spacing: 8
                model: panel.book.rows || []
                ScrollBar.vertical: ScrollBar { }
                delegate: Rectangle {
                    required property var modelData
                    width: ListView.view.width
                    height: recipeColumn.implicitHeight + 18
                    color: "#1d2929"
                    border.color: "#625538"
                    radius: 2
                    Column {
                        id: recipeColumn
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 9
                        spacing: 5
                        Text { text: modelData.name; color: "#f4d99e"; font.pixelSize: 14; font.bold: true }
                        Text {
                            width: parent.width
                            text: (modelData.reagents || []).map(function(r) {
                                return r.name + " " + r.have + "/" + r.need
                            }).join("  ·  ")
                            color: Number(modelData.available) > 0 ? "#c4ddbe" : "#d6a292"
                            font.pixelSize: 11
                            wrapMode: Text.WordWrap
                        }
                        Row {
                            width: parent.width
                            spacing: 8
                            GameInventoryAction {
                                objectName: "ggCraftRecipe_" + String(modelData.ref)
                                text: "SKAPA"
                                enabled: Number(modelData.available) > 0 && !Number(panel.book.repeat_count)
                                onClicked: panel.game.craftBookRecipe(String(modelData.ref), 1)
                            }
                            GameInventoryAction {
                                text: "SKAPA ALLA (" + String(Number(modelData.available || 0)) + ")"
                                visible: Number(modelData.available) > 1
                                enabled: Number(modelData.available) > 1 && !Number(panel.book.repeat_count)
                                onClicked: panel.game.craftBookRecipe(String(modelData.ref), Number(modelData.available))
                            }
                            Text { width: Math.max(50, parent.width - 180); text: modelData.description; color: "#d1bd8f"; font.pixelSize: 11; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter }
                        }
                    }
                }
            }
            Text {
                width: parent.width
                text: panel.game ? panel.game.itemNotice : ""
                color: "#f0c67a"
                font.pixelSize: 12
                wrapMode: Text.WordWrap
            }
            GameInventoryAction {
                objectName: "ggCraftingStop"
                visible: Number(panel.book.repeat_count) > 0
                text: "AVBRYT TILLVERKNING"
                onClicked: panel.game.stopCrafting()
            }
        }
    }

    Rectangle {
        objectName: "ggLootWindow"
        visible: Boolean(panel.loot.open)
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        anchors.leftMargin: 12
        width: Math.min(310, parent.width - 24)
        height: Math.min(390, parent.height - 24)
        color: "#10191d"
        border.color: "#c5a365"
        border.width: 2
        radius: 3
        MouseArea { anchors.fill: parent; onWheel: function(wheel) { wheel.accepted = true } }
        Column {
            anchors.fill: parent
            anchors.margins: 12
            spacing: 10
            Row {
                width: parent.width
                Text { width: parent.width - 80; text: "◆  INNEHÅLL"; color: "#f4d99e"; font.pixelSize: 16; font.bold: true }
                GameInventoryAction { objectName: "ggLootClose"; text: "STÄNG ×"; onClicked: panel.game.closeLoot() }
            }
            ListView {
                objectName: "ggLootItems"
                width: parent.width
                height: Math.max(70, parent.height - 80)
                model: panel.loot.rows || []
                clip: true
                spacing: 6
                ScrollBar.vertical: ScrollBar { }
                delegate: GameInventoryAction {
                    required property var modelData
                    width: ListView.view.width
                    height: modelData ? 38 : 0
                    visible: Boolean(modelData)
                    enabled: Boolean(modelData)
                    objectName: modelData ? "ggLootItem_" + String(modelData.instance_id) : ""
                    text: modelData ? String(modelData.name) + " × " + String(modelData.quantity || 1) : ""
                    onClicked: if (modelData) panel.game.lootItem(String(modelData.instance_id))
                }
            }
            Text { width: parent.width; text: panel.game ? panel.game.itemNotice : ""; color: "#f0c67a"; font.pixelSize: 11; wrapMode: Text.WordWrap }
        }
    }
}
