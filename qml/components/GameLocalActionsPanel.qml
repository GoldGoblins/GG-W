
import "." as RuntimeTheme
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
                GGText { colorKey: "ui.GameLocalActionsPanel.1";
                    width: parent.width - 90
                    text: "◆  TILLVERKNING"
                    color: RuntimeTheme.GGTheme.orange
                    font.family: "serif"
                    font.pixelSize: 18
                    font.bold: true
                }
                GameInventoryAction { property string uiColorScope: "ui.widget.GameLocalActionsPanel.GameInventoryAction.1";
                    objectName: "ggCraftingClose"
                    text: "STÄNG ×"
                    onClicked: panel.game.closeCrafting()
                }
            }
            Row {
                spacing: 8
                GameInventoryAction { property string uiColorScope: "ui.widget.GameLocalActionsPanel.GameInventoryAction.2";
                    objectName: "ggCraftingField"
                    text: "FÄLTRECEPT"
                    onClicked: panel.game.openCrafting("")
                }
                GameInventoryAction { property string uiColorScope: "ui.widget.GameLocalActionsPanel.GameInventoryAction.3";
                    objectName: "ggCraftingStation"
                    text: "NÄRMASTE ARBETSSTATION"
                    onClicked: panel.game.openCrafting("NEAREST")
                }
            }
            GGText { colorKey: "ui.GameLocalActionsPanel.2";
                width: parent.width
                text: Number(panel.book.repeat_count) > 0 ? (panel.game.status.state === "RUNNING" ? "Tillverkar" : "Tillverkningen är pausad") + " · " + panel.book.repeat_count + " återstår"
                      : panel.book.station_id ? "Recept vid den valda arbetsstationen" : "Recept som kan tillverkas direkt i fält"
                color: RuntimeTheme.GGTheme.text
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
                        GGText { colorKey: "ui.GameLocalActionsPanel.3"; text: modelData.name; color: RuntimeTheme.GGTheme.orange; font.pixelSize: 14; font.bold: true }
                        GGText { colorKey: "ui.GameLocalActionsPanel.4";
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
                            GameInventoryAction { property string uiColorScope: "ui.widget.GameLocalActionsPanel.GameInventoryAction.4";
                                objectName: "ggCraftRecipe_" + String(modelData.ref)
                                text: "SKAPA"
                                enabled: Number(modelData.available) > 0 && !Number(panel.book.repeat_count)
                                onClicked: panel.game.craftBookRecipe(String(modelData.ref), 1)
                            }
                            GameInventoryAction { property string uiColorScope: "ui.widget.GameLocalActionsPanel.GameInventoryAction.5";
                                text: "SKAPA ALLA (" + String(Number(modelData.available || 0)) + ")"
                                visible: Number(modelData.available) > 1
                                enabled: Number(modelData.available) > 1 && !Number(panel.book.repeat_count)
                                onClicked: panel.game.craftBookRecipe(String(modelData.ref), Number(modelData.available))
                            }
                            GGText { colorKey: "ui.GameLocalActionsPanel.5"; width: Math.max(50, parent.width - 180); text: modelData.description; color: RuntimeTheme.GGTheme.text; font.pixelSize: 11; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter }
                        }
                    }
                }
            }
            GGText { colorKey: "ui.GameLocalActionsPanel.6";
                width: parent.width
                text: panel.game ? panel.game.itemNotice : ""
                color: "#f0c67a"
                font.pixelSize: 12
                wrapMode: Text.WordWrap
            }
            GameInventoryAction { property string uiColorScope: "ui.widget.GameLocalActionsPanel.GameInventoryAction.6";
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
                GGText { colorKey: "ui.GameLocalActionsPanel.7"; width: parent.width - 80; text: "◆  INNEHÅLL"; color: RuntimeTheme.GGTheme.orange; font.pixelSize: 16; font.bold: true }
                GameInventoryAction { property string uiColorScope: "ui.widget.GameLocalActionsPanel.GameInventoryAction.7"; objectName: "ggLootClose"; text: "STÄNG ×"; onClicked: panel.game.closeLoot() }
            }
            ListView {
                objectName: "ggLootItems"
                width: parent.width
                height: Math.max(70, parent.height - 80)
                model: panel.loot.rows || []
                clip: true
                spacing: 6
                ScrollBar.vertical: ScrollBar { }
                delegate: GameInventoryAction { property string uiColorScope: "ui.widget.GameLocalActionsPanel.GameInventoryAction.8";
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
            GGText { colorKey: "ui.GameLocalActionsPanel.8"; width: parent.width; text: panel.game ? panel.game.itemNotice : ""; color: "#f0c67a"; font.pixelSize: 11; wrapMode: Text.WordWrap }
        }
    }
}
