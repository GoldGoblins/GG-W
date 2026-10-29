
import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

Item {
    id: panel
    property bool enchantingExpanded: false
    property bool ammunitionExpanded: false
    property var game: null
    readonly property var equipmentRows: game ? (game.items.equipment || []) : []
    readonly property var bagRows: game ? (game.items.inventory || []) : []
    readonly property var bankRows: game ? (game.bank.items || []) : []
    readonly property bool bankAccessible: Boolean(game && game.bank.accessible)
    readonly property bool nearBank: Boolean(game && game.bank.nearby)
    readonly property var leftSlots: ["HEAD", "SHOULDERS", "BACK", "CHEST", "SHIRT", "TABARD", "WRISTS", "MAIN_HAND"]
    readonly property var rightSlots: ["NECK", "HANDS", "WAIST", "LEGS", "FEET", "RING_1", "RING_2", "OFF_HAND"]
    readonly property var lowerSlots: ["RANGED", "TRINKET_1", "TRINKET_2"]
    property string dragId: ""
    property real dragX: 0
    property real dragY: 0
    property var hoveredTarget: null
    readonly property var selectedRow: panel.rowById(game ? game.selectedItemId : "")
    readonly property var wrapping:game ? (game.localServiceState.inventory_cursor || {}).wrap || null : null
    readonly property var enchantCursor:game ? game.localServiceState.item_targeting || ({}) : ({})
    readonly property var draggedRow: panel.rowById(panel.dragId)

    function rowById(instanceId) {
        var wanted = String(instanceId || "")
        if (!wanted)
            return null
        var all = panel.equipmentRows.concat(panel.bagRows, panel.bankRows)
        for (var i = 0; i < all.length; ++i) {
            if (String(all[i].instance_id || "") === wanted)
                return all[i]
        }
        return null
    }

    function iconSourceFor(row) {
        return String(row && row.icon || "../assets/authored/items/icons/unknown.png")
    }

    function rowAt(rows, index) {
        var assigned = false
        for (var i = 0; i < rows.length; ++i) {
            var slot = Number(rows[i].slot_index)
            if (slot >= 0 && !isNaN(slot)) {
                assigned = true
                if (slot === index)
                    return rows[i]
            }
        }
        return assigned ? null : (index < rows.length ? rows[index] : null)
    }

    function equippedFor(code) {
        for (var i = 0; i < panel.equipmentRows.length; ++i) {
            if (String(panel.equipmentRows[i].equipped_slot || "") === code)
                return panel.equipmentRows[i]
        }
        return null
    }

    function fitsSlot(row, code) {
        if (!row) return false
        var slots = row.equip_slots || [row.equip_slot]
        for (var i=0; i<slots.length; ++i)
            if (String(slots[i]) === code) return true
        return false
    }

    function slotName(code) {
        var names = {
            "HEAD": "HUVUD", "NECK": "HALS", "SHOULDERS": "AXLAR",
            "BACK": "RYGG", "CHEST": "BRÖST", "WRISTS": "HANDLEDER",
            "HANDS": "HÄNDER", "WAIST": "MIDJA", "LEGS": "BEN",
            "FEET": "FÖTTER", "MAIN_HAND": "VAPEN", "OFF_HAND": "ANDRA",
            "RANGED": "DISTANS", "TRINKET_1": "TALISMAN", "TRINKET_2": "TALISMAN",
            "SHIRT": "SKJORTA", "TABARD": "TABARD", "RING_1": "RING", "RING_2": "RING"
        }
        return names[code] || code
    }

    function ensureBankOpen() {
        if (panel.bankAccessible)
            return true
        if (!panel.nearBank) {
            panel.game.itemNotice = "Gå fram till försörjningskistan för att öppna den."
            return false
        }
        return panel.game.openContainer(String(panel.game.bank.container_id || ""))
    }

    function storeSelected() {
        if (panel.selectedRow && panel.ensureBankOpen()
                && panel.game.depositToBank(String(panel.selectedRow.instance_id)))
            panel.game.selectedItemId = ""
    }

    function activateTwice(instanceId) {
        var row = panel.rowById(instanceId)
        if (!row)
            return
        panel.game.selectedItemId = String(instanceId)
        if (panel.enchantCursor.active && row.gear && ["INVENTORY","EQUIPPED"].indexOf(row.location)>=0)
            panel.enchantItem(row.instance_id)
        else if (row.location === "INVENTORY" && row.scroll_enchant_id)
            panel.useItem(row)
        else if (row.location === "INVENTORY" && panel.wrapping && panel.wrapping.paper!==row.instance_id)
            panel.wrapItem(row.instance_id)
        else if (row.location === "INVENTORY" && (row.wrapped || row.definition_id==="item.gg_wrapping_paper"))
            panel.useItem(row)
        else if (row.location === "INVENTORY" && String(row.equip_slot || ""))
            panel.game.equipItem(String(instanceId))
        else if (row.location === "EQUIPPED")
            panel.game.unequipItem(String(instanceId))
        else if (row.location === "BANK" && panel.ensureBankOpen())
            panel.game.withdrawFromBank(String(instanceId))
    }

    function service(command) {
        command.kind="service"
        var result=JSON.parse(panel.game.surfaceHost.gameEngineClientControl(JSON.stringify(command)))
        panel.game.applyGameplay(JSON.stringify(result))
        panel.game.localServiceState=((result.player || {}).client_controls || {}).services || panel.game.localServiceState
        return !result.error
    }
    function wrapItem(id) {
        if(panel.wrapping)panel.service({op:"InventoryWrap",item:id,paper:panel.wrapping.paper,wrap_generation:panel.wrapping.generation})
    }
    function enchantItem(id) {
        panel.service({op:"EnchantPick",item:id,target_generation:panel.enchantCursor.generation})
    }
    function useItem(row) {
        panel.game.applyGameplay(panel.game.surfaceHost.gameEngineContainerUseItem(String(row.definition_id),String(row.instance_id)))
        panel.game.refresh()
    }

    function slotAt(x, y) {
        var repeaters = [leftGearRepeater, rightGearRepeater, lowerGearRepeater,
                         bagRepeater, bankRepeater]
        for (var r = 0; r < repeaters.length; ++r) {
            if (r === 4 && !(panel.nearBank || panel.bankAccessible))
                continue
            var repeater = repeaters[r]
            for (var i = 0; i < repeater.count; ++i) {
                var target = repeater.itemAt(i)
                if (target && target.dropSlot)
                    target = target.dropSlot
                if (!target)
                    continue
                var point = target.mapToItem(panel, 0, 0)
                if (x >= point.x && y >= point.y
                        && x < point.x + target.width
                        && y < point.y + target.height)
                    return target
            }
        }
        return null
    }

    function dragMoved(instanceId, x, y) {
        panel.dragId = String(instanceId)
        panel.dragX = x
        panel.dragY = y
        panel.game.inventoryActionDrag(panel.rowById(instanceId),x,y,panel,false)
        var target = panel.slotAt(x, y)
        var dragged = panel.rowById(instanceId)
        if (target && target.dropZone === "EQUIPMENT"
                && (!dragged || dragged.location === "EQUIPPED"
                    || !panel.fitsSlot(dragged, target.gearCode)))
            target = null
        panel.hoveredTarget = target
    }

    function finishDrag(instanceId, x, y) {
        var row = panel.rowById(instanceId)
        var target = panel.slotAt(x, y)
        panel.dragId = ""
        panel.hoveredTarget = null
        if (row && panel.game.inventoryActionDrag(row,x,y,panel,true)) return
        panel.game.cancelActionDrag()
        if (!row || !target)
            return
        var id = String(instanceId)
        var origin = String(row.location || "")
        if (target.dropZone === "BAG") {
            if (origin === "INVENTORY")
                panel.game.moveInventorySlot(id, target.slotIndex)
            else if (origin === "EQUIPPED") {
                if (panel.game.unequipItem(id))
                    panel.game.moveInventorySlot(id, target.slotIndex)
            } else if (origin === "BANK" && panel.ensureBankOpen())
                panel.game.withdrawFromBank(id, target.slotIndex)
        } else if (target.dropZone === "BANK") {
            if (!panel.ensureBankOpen())
                return
            if (origin === "BANK")
                panel.game.moveBankSlot(id, target.slotIndex)
            else if (origin === "INVENTORY" || origin === "EQUIPPED")
                panel.game.depositToBank(id, target.slotIndex)
        } else if (target.dropZone === "EQUIPMENT") {
            if (origin === "EQUIPPED" && String(row.equipped_slot) === target.gearCode)
                return
            if (!panel.fitsSlot(row, target.gearCode)) {
                panel.game.itemNotice = "Det föremålet passar inte i "
                    + panel.slotName(target.gearCode).toLowerCase() + "."
                return
            }
            if (origin === "INVENTORY")
                panel.game.equipItem(id, target.gearCode)
            else if (origin === "BANK" && panel.ensureBankOpen()) {
                if (panel.game.withdrawFromBank(id))
                    panel.game.equipItem(id, target.gearCode)
            }
        }
    }

    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(0.015, 0.025, 0.03, 0.20)
        MouseArea { anchors.fill: parent; onClicked: panel.game.page = "PLAY" }
    }

    Rectangle {
        id: window
        objectName: "gameCharacterInventoryWindow"
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.rightMargin: 10
        width: Math.min(560, Math.max(360, parent.width * 0.52))
        height: Math.min(690, parent.height - 16)
        color: "#10191d"
        border.color: "#c5a365"
        border.width: 2
        radius: 3

        Rectangle {
            anchors.fill: parent
            anchors.margins: 5
            color: "transparent"
            border.color: "#625538"
            border.width: 1
        }
        MouseArea {
            anchors.fill: parent
            onPressed: function(mouse) { mouse.accepted = true }
            onWheel: function(wheel) { wheel.accepted = true }
        }

        Rectangle {
            id: header
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: 43
            gradient: Gradient {
                GradientStop { position: 0; color: "#44504c" }
                GradientStop { position: 0.45; color: "#263431" }
                GradientStop { position: 1; color: "#1b2628" }
            }
            border.color: RuntimeTheme.GGTheme.edge
            border.width: 1
            GGText { colorKey: "ui.GameInventoryPanel.1";
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 13
                text: window.width < 470 ? "◆  VÄSKA" : "◆  KARAKTÄR   ·   VÄSKA"
                color: RuntimeTheme.GGTheme.orange
                font.family: "serif"
                font.pixelSize: 17
                font.bold: true
            }
            GGText { colorKey: "ui.GameInventoryPanel.2";
                anchors.right: craftButton.left
                anchors.verticalCenter: parent.verticalCenter
                anchors.rightMargin: 12
                text: "LV " + String(panel.game.progression.level || 1)
                visible: window.width >= 500
                color: RuntimeTheme.GGTheme.text
                font.family: "monospace"
                font.pixelSize: 10
            }
            GameInventoryAction { property string uiColorScope: "ui.widget.GameInventoryPanel.GameInventoryAction.1";
                id: craftButton
                objectName: "ggInventoryCraftingOpen"
                anchors.right: closeButton.left
                anchors.verticalCenter: parent.verticalCenter
                anchors.rightMargin: 8
                text: "TILLVERKA"
                onClicked: panel.game.openCrafting("")
            }
            GameInventoryAction { property string uiColorScope: "ui.widget.GameInventoryPanel.GameInventoryAction.2";
                id: closeButton
                objectName: "ggInventoryClose"
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.rightMargin: 8
                text: "STÄNG ×"
                implicitWidth: 75
                implicitHeight: 27
                onClicked: panel.game.page = "PLAY"
            }
        }

        Flickable {
            id: scroll
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: header.bottom
            anchors.bottom: parent.bottom
            anchors.margins: 9
            clip: true
            contentWidth: width
            contentHeight: contents.implicitHeight
            boundsBehavior: Flickable.StopAtBounds

            Column {
                id: contents
                width: parent.width
                spacing: 7

                Column {
                    width: parent.width
                    spacing: 8
                    Rectangle {
                        id: equipmentPanel
                        width: parent.width
                        height: 284
                        color: "#172126"
                        border.color: RuntimeTheme.GGTheme.edge
                        border.width: 1
                        GGText { colorKey: "ui.GameInventoryPanel.3";
                            anchors.top: parent.top
                            anchors.horizontalCenter: parent.horizontalCenter
                            anchors.topMargin: 4
                            text: "❖  UTRUSTNING  ❖"
                            color: RuntimeTheme.GGTheme.orange
                            font.family: "serif"
                            font.pixelSize: 12
                            font.bold: true
                        }
                        Row {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.topMargin: 25
                            anchors.leftMargin: 7
                            anchors.rightMargin: 7
                            height: 230
                            spacing: 5
                            Column {
                                width: 91
                                spacing: 1
                                Repeater {
                                    id: leftGearRepeater
                                    model: panel.leftSlots
                                    delegate: Row {
                                        required property var modelData
                                        property var dropSlot: leftGearSlot
                                        width: 91; height: 28; spacing: 3
                                        GGText { colorKey: "ui.GameInventoryPanel.4";
                                            width: 53
                                            anchors.verticalCenter: parent.verticalCenter
                                            text: panel.slotName(String(modelData))
                                            color: "#9fa69a"
                                            font.family: "monospace"
                                            font.pixelSize: 8
                                            elide: Text.ElideRight
                                            horizontalAlignment: Text.AlignRight
                                        }
                                        GameInventorySlot { property string uiColorScope: "ui.widget.GameInventoryPanel.GameInventorySlot.3";
                                            id: leftGearSlot
                                            width: 27; height: 27
                                            gearCode: String(modelData)
                                            slotLabel: panel.slotName(gearCode)
                                            dropZone: "EQUIPMENT"
                                            itemData: panel.equippedFor(gearCode)
                                            dragRoot: panel
                                            selected: occupied && panel.game.selectedItemId === itemId
                                            dropHovered: panel.hoveredTarget === this
                                            onActivated: panel.game.selectedItemId = itemId
                                            onDoubleActivated: panel.activateTwice(itemId)
                                            onItemDragMoved: function(id, x, y) { panel.dragMoved(id, x, y) }
                                            onItemDragFinished: function(id, x, y) { panel.finishDrag(id, x, y) }
                                            onItemDragCanceled: { panel.dragId = ""; panel.hoveredTarget = null; panel.game.cancelActionDrag() }
                                        }
                                    }
                                }
                            }
                            Rectangle {
                                id: portrait
                                width: parent.width - 187
                                height: 228
                                color: "#303b3d"
                                border.color: "#746744"
                                border.width: 1
                                GameCharacterPreview { property string uiColorScope: "ui.widget.GameInventoryPanel.GameCharacterPreview.4";
                                    anchors.fill: parent
                                    anchors.margins: 2
                                    game: panel.game
                                    equipment: panel.equipmentRows
                                }
                            }
                            Column {
                                width: 91
                                spacing: 1
                                Repeater {
                                    id: rightGearRepeater
                                    model: panel.rightSlots
                                    delegate: Row {
                                        required property var modelData
                                        property var dropSlot: rightGearSlot
                                        width: 91; height: 28; spacing: 3
                                        GameInventorySlot { property string uiColorScope: "ui.widget.GameInventoryPanel.GameInventorySlot.5";
                                            id: rightGearSlot
                                            width: 27; height: 27
                                            gearCode: String(modelData)
                                            slotLabel: panel.slotName(gearCode)
                                            dropZone: "EQUIPMENT"
                                            itemData: panel.equippedFor(gearCode)
                                            dragRoot: panel
                                            selected: occupied && panel.game.selectedItemId === itemId
                                            dropHovered: panel.hoveredTarget === this
                                            onActivated: panel.game.selectedItemId = itemId
                                            onDoubleActivated: panel.activateTwice(itemId)
                                            onItemDragMoved: function(id, x, y) { panel.dragMoved(id, x, y) }
                                            onItemDragFinished: function(id, x, y) { panel.finishDrag(id, x, y) }
                                            onItemDragCanceled: { panel.dragId = ""; panel.hoveredTarget = null; panel.game.cancelActionDrag() }
                                        }
                                        GGText { colorKey: "ui.GameInventoryPanel.5";
                                            width: 53
                                            anchors.verticalCenter: parent.verticalCenter
                                            text: panel.slotName(String(modelData))
                                            color: "#9fa69a"
                                            font.family: "monospace"
                                            font.pixelSize: 8
                                            elide: Text.ElideRight
                                        }
                                    }
                                }
                            }
                        }
                        Row {
                            anchors.horizontalCenter: parent.horizontalCenter
                            anchors.bottom: parent.bottom
                            anchors.bottomMargin: 3
                            spacing: 16
                            Repeater {
                                id: lowerGearRepeater
                                model: panel.lowerSlots
                                delegate: Row {
                                    required property var modelData
                                    property var dropSlot: lowerGearSlot
                                    spacing: 3
                                    GameInventorySlot { property string uiColorScope: "ui.widget.GameInventoryPanel.GameInventorySlot.6";
                                        id: lowerGearSlot
                                        width: 25; height: 25
                                        gearCode: String(modelData)
                                        slotLabel: panel.slotName(gearCode)
                                        dropZone: "EQUIPMENT"
                                        itemData: panel.equippedFor(gearCode)
                                        dragRoot: panel
                                        selected: occupied && panel.game.selectedItemId === itemId
                                        dropHovered: panel.hoveredTarget === this
                                        onActivated: panel.game.selectedItemId = itemId
                                        onDoubleActivated: panel.activateTwice(itemId)
                                        onItemDragMoved: function(id, x, y) { panel.dragMoved(id, x, y) }
                                        onItemDragFinished: function(id, x, y) { panel.finishDrag(id, x, y) }
                                        onItemDragCanceled: { panel.dragId = ""; panel.hoveredTarget = null; panel.game.cancelActionDrag() }
                                    }
                                    GGText { colorKey: "ui.GameInventoryPanel.6";
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: panel.slotName(String(modelData))
                                        color: "#9fa69a"
                                        font.family: "monospace"
                                        font.pixelSize: 8
                                    }
                                }
                            }
                        }
                    }

                    Rectangle {
                        id: detailPanel
                        width: parent.width
                        height: 192
                        color: "#172126"
                        border.color: RuntimeTheme.GGTheme.edge
                        border.width: 1
                        GGText { colorKey: "ui.GameInventoryPanel.7";
                            anchors.top: parent.top
                            anchors.horizontalCenter: parent.horizontalCenter
                            anchors.topMargin: 4
                            text: "❖  FÖREMÅL & HANDLINGAR  ❖"
                            color: RuntimeTheme.GGTheme.orange
                            font.family: "serif"
                            font.pixelSize: 12
                            font.bold: true
                        }
                        Rectangle {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.topMargin: 23
                            anchors.margins: 9
                            height: 1
                            color: "#65583b"
                        }
                        Image {
                            anchors.left: parent.left
                            anchors.top: parent.top
                            anchors.leftMargin: 12
                            anchors.topMargin: 35
                            width: 52; height: 52
                            visible: Boolean(panel.selectedRow)
                            source: panel.selectedRow ? panel.iconSourceFor(panel.selectedRow) : ""
                            fillMode: Image.PreserveAspectFit
                            smooth: true
                        }
                        Column {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.leftMargin: panel.selectedRow ? 72 : 13
                            anchors.rightMargin: 9
                            anchors.topMargin: 39
                            spacing: 5
                            GGText { colorKey: "ui.GameInventoryPanel.8";
                                width: parent.width
                                text: panel.selectedRow
                                    ? String(panel.selectedRow.name || "Föremål")
                                    : "Välj ett föremål"
                                color: panel.selectedRow
                                    ? String(panel.selectedRow.rarity_color || "#eed59f")
                                    : "#eed59f"
                                font.family: "serif"
                                font.pixelSize: 16
                                font.bold: true
                                elide: Text.ElideRight
                            }
                            GGText { colorKey: "ui.GameInventoryPanel.9";
                                width: parent.width
                                text: panel.selectedRow
                                    ? String(panel.selectedRow.kind || "ITEM") + " · "
                                        + String(panel.selectedRow.rarity || "COMMON")
                                        + (panel.selectedRow.wielding_reference ? " · "+String(panel.selectedRow.wielding_reference) : "")
                                        + " · ×" + String(panel.selectedRow.quantity || 1)
                                    : "Dra föremål mellan utrustning, väska och kista."
                                color: "#abbab3"
                                font.family: "monospace"
                                font.pixelSize: 10
                                wrapMode: Text.WordWrap
                            }
                            GGText { colorKey: "ui.GameInventoryPanel.10";
                                width: parent.width
                                text: panel.selectedRow && panel.selectedRow.firearm
                                    ? panel.selectedRow.firearm.ammo_name+"\n"
                                        +panel.selectedRow.firearm.rounds_per_s+" skott/s · "
                                        +panel.selectedRow.firearm.range_m+" m · magasin "
                                        +panel.selectedRow.firearm.capacity
                                    : panel.selectedRow && panel.selectedRow.equip_slot
                                    ? "Utrustningsplats: " + panel.slotName(String(panel.selectedRow.equip_slot))
                                    : "Dubbelklicka på utrustning för att ta på eller av."
                                color: "#d4bd8e"
                                font.family: "monospace"
                                font.pixelSize: 9
                                wrapMode: Text.WordWrap
                            }
                        }
                        Flow {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.leftMargin: 11
                            anchors.rightMargin: 11
                            anchors.topMargin: 116
                            spacing: 5
                            GameInventoryAction { property string uiColorScope: "ui.widget.GameInventoryPanel.GameInventoryAction.7";
                                objectName:"inventoryTryOn";text:"PROVA UTSEENDET"
                                enabled:!!panel.selectedRow && !!panel.selectedRow.equip_slot
                                onClicked:{
                                    var rows=panel.game.localServiceState.item_templates || []
                                    var template=rows.filter(function(row){return row.definition_id===panel.selectedRow.definition_id})[0]
                                    if(template)panel.service({op:"DressupTryOn",id:template.item_id})
                                }
                            }
                            GameInventoryAction { property string uiColorScope: "ui.widget.GameInventoryPanel.GameInventoryAction.8";
                                objectName:"inventoryEnchantScroll"
                                text:"ANVÄND ENCHANT-SCROLL";visible:!!panel.selectedRow && !!panel.selectedRow.scroll_enchant_id
                                enabled:visible && panel.selectedRow.location==="INVENTORY"
                                onClicked:panel.useItem(panel.selectedRow)
                            }
                            GameInventoryAction { property string uiColorScope: "ui.widget.GameInventoryPanel.GameInventoryAction.9";
                                objectName:"inventoryEnchantTarget"
                                text:"APPLICERA ENCHANT";visible:panel.enchantCursor.active===true
                                enabled:visible && !!panel.selectedRow && !!panel.selectedRow.gear && ["INVENTORY","EQUIPPED"].indexOf(panel.selectedRow.location)>=0
                                onClicked:panel.enchantItem(panel.selectedRow.instance_id)
                            }
                            GameInventoryAction { property string uiColorScope: "ui.widget.GameInventoryPanel.GameInventoryAction.10";
                                text:"AVBRYT ENCHANTING";visible:panel.enchantCursor.active===true
                                onClicked:panel.service({op:"EnchantCancel",target_generation:panel.enchantCursor.generation})
                            }
                            GameInventoryAction { property string uiColorScope: "ui.widget.GameInventoryPanel.GameInventoryAction.11";
                                objectName:"inventoryWrapPaper"
                                text:panel.selectedRow && panel.selectedRow.wrapped ? "ÖPPNA PAKET" : "ANVÄND PAPPER"
                                visible:!!panel.selectedRow && (panel.selectedRow.wrapped || panel.selectedRow.definition_id==="item.gg_wrapping_paper")
                                enabled:visible && panel.selectedRow.location==="INVENTORY"
                                onClicked:panel.useItem(panel.selectedRow)
                            }
                            GameInventoryAction { property string uiColorScope: "ui.widget.GameInventoryPanel.GameInventoryAction.12";
                                objectName:"inventoryWrapTarget"
                                text:"SLÅ IN VALT FÖREMÅL";visible:!!panel.wrapping
                                enabled:!!panel.wrapping && !!panel.selectedRow && panel.selectedRow.location==="INVENTORY" && panel.selectedRow.instance_id!==panel.wrapping.paper
                                onClicked:panel.wrapItem(panel.selectedRow.instance_id)
                            }
                            GameInventoryAction { property string uiColorScope: "ui.widget.GameInventoryPanel.GameInventoryAction.13";
                                text:"AVBRYT INSLAGNING";visible:!!panel.wrapping
                                onClicked:panel.service({op:"InventoryWrapCancel",wrap_generation:panel.wrapping.generation})
                            }
                            GameInventoryAction { property string uiColorScope: "ui.widget.GameInventoryPanel.GameInventoryAction.14";
                                text: "TA PÅ"
                                enabled: Boolean(panel.selectedRow)
                                    && panel.selectedRow.location === "INVENTORY"
                                    && Boolean(panel.selectedRow.equip_slot)
                                onClicked: panel.game.equipItem(String(panel.selectedRow.instance_id))
                            }
                            GameInventoryAction { property string uiColorScope: "ui.widget.GameInventoryPanel.GameInventoryAction.15";
                                text: "HUVUDHAND"
                                visible: panel.fitsSlot(panel.selectedRow, "MAIN_HAND") && panel.fitsSlot(panel.selectedRow, "OFF_HAND")
                                enabled: visible && panel.selectedRow.location === "INVENTORY"
                                onClicked: panel.game.equipItem(String(panel.selectedRow.instance_id), "MAIN_HAND")
                            }
                            GameInventoryAction { property string uiColorScope: "ui.widget.GameInventoryPanel.GameInventoryAction.16";
                                text: "ANDRA HANDEN"
                                visible: panel.fitsSlot(panel.selectedRow, "MAIN_HAND") && panel.fitsSlot(panel.selectedRow, "OFF_HAND")
                                enabled: visible && panel.selectedRow.location === "INVENTORY"
                                onClicked: panel.game.equipItem(String(panel.selectedRow.instance_id), "OFF_HAND")
                            }
                            GameInventoryAction { property string uiColorScope: "ui.widget.GameInventoryPanel.GameInventoryAction.17";
                                text: "TA AV"
                                enabled: Boolean(panel.selectedRow)
                                    && panel.selectedRow.location === "EQUIPPED"
                                onClicked: panel.game.unequipItem(String(panel.selectedRow.instance_id))
                            }
                            GameInventoryAction { property string uiColorScope: "ui.widget.GameInventoryPanel.GameInventoryAction.18";
                                text: "LÄGG I KISTAN"
                                enabled: Boolean(panel.selectedRow)
                                    && (panel.selectedRow.location === "INVENTORY"
                                        || panel.selectedRow.location === "EQUIPPED")
                                    && (panel.nearBank || panel.bankAccessible)
                                onClicked: panel.storeSelected()
                            }
                            GameInventoryAction { property string uiColorScope: "ui.widget.GameInventoryPanel.GameInventoryAction.19";
                                text: "TA UR KISTAN"
                                enabled: Boolean(panel.selectedRow)
                                    && panel.selectedRow.location === "BANK"
                                    && (panel.nearBank || panel.bankAccessible)
                                onClicked: {
                                    if (panel.ensureBankOpen()
                                            && panel.game.withdrawFromBank(String(panel.selectedRow.instance_id)))
                                        panel.game.selectedItemId = ""
                                }
                            }
                            GameInventoryAction { property string uiColorScope: "ui.widget.GameInventoryPanel.GameInventoryAction.20";
                                text: "SLÄPP PÅ MARKEN"
                                enabled: Boolean(panel.selectedRow)
                                    && panel.selectedRow.location !== "BANK"
                                onClicked: {
                                    if (panel.game.dropItem(String(panel.selectedRow.instance_id)))
                                        panel.game.selectedItemId = ""
                                }
                            }
                            GameInventoryAction { property string uiColorScope: "ui.widget.GameInventoryPanel.GameInventoryAction.21";
                                text: "SOCKET"
                                enabled: Boolean(panel.selectedRow)
                                    && panel.selectedRow.location !== "BANK"
                                onClicked: panel.game.socketItem(String(panel.selectedRow.instance_id), "")
                            }
                            GameInventoryAction { property string uiColorScope: "ui.widget.GameInventoryPanel.GameInventoryAction.22";
                                text: "ENCHANTING"
                                enabled: Boolean(panel.game)
                                onClicked: panel.enchantingExpanded = !panel.enchantingExpanded
                            }
                            GameInventoryAction { property string uiColorScope: "ui.widget.GameInventoryPanel.GameInventoryAction.23";
                                text: "AMMUNITION"
                                enabled: Boolean(panel.game)
                                onClicked: panel.ammunitionExpanded = !panel.ammunitionExpanded
                            }
                        }
                        GGText { colorKey: "ui.GameInventoryPanel.11";
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            anchors.margins: 11
                            height: 17
                            text: String(panel.game.itemNotice || "")
                            color: "#f0d391"
                            font.family: "monospace"
                            font.pixelSize: 10
                            wrapMode: Text.WordWrap
                        }
                    }
                }

                GameEnchantingControls { property string uiColorScope: "ui.widget.GameInventoryPanel.GameEnchantingControls.24";
                    objectName: "gameStandaloneEnchantControls"
                    width: parent.width
                    visible: panel.enchantingExpanded
                    game: panel.game
                }
                GameAmmunitionControls { property string uiColorScope: "ui.widget.GameInventoryPanel.GameAmmunitionControls.25";
                    objectName: "gameAmmunitionControls"
                    width: parent.width
                    visible: panel.ammunitionExpanded
                    game: panel.game
                    targetItem: panel.selectedRow
                }
                Row {
                    width: parent.width
                    spacing: 8
                    Rectangle {
                        id: bagPanel
                        width: Math.round((parent.width - 8) * 0.51)
                        height: 289
                        color: "#172126"
                        border.color: RuntimeTheme.GGTheme.edge
                        border.width: 1
                        GGText { colorKey: "ui.GameInventoryPanel.12";
                            anchors.left: parent.left
                            anchors.top: parent.top
                            anchors.leftMargin: 10
                            anchors.topMargin: 5
                            text: "◆  ENVÄSKA   " + panel.bagRows.length + " / 64"
                            color: "#f0d391"
                            font.family: "serif"
                            font.pixelSize: 13
                            font.bold: true
                        }
                        GGText { colorKey: "ui.GameInventoryPanel.13";
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.rightMargin: 10
                            anchors.topMargin: 8
                            text: "1 FÖREMÅL / PLATS"
                            color: "#8da39d"
                            font.family: "monospace"
                            font.pixelSize: 9
                        }
                        Grid {
                            anchors.left: parent.left
                            anchors.top: parent.top
                            anchors.leftMargin: 10
                            anchors.topMargin: 25
                            columns: 8
                            spacing: 3
                            Repeater {
                                id: bagRepeater
                                model: 64
                                delegate: GameInventorySlot { property string uiColorScope: "ui.widget.GameInventoryPanel.GameInventorySlot.26";
                                    required property int index
                                    width: 29; height: 29
                                    slotIndex: index
                                    dropZone: "BAG"
                                    itemData: panel.rowAt(panel.bagRows, index)
                                    dragRoot: panel
                                    selected: occupied && panel.game.selectedItemId === itemId
                                    dropHovered: panel.hoveredTarget === this
                                    onActivated: panel.game.selectedItemId = itemId
                                    onDoubleActivated: panel.activateTwice(itemId)
                                    onItemDragMoved: function(id, x, y) { panel.dragMoved(id, x, y) }
                                    onItemDragFinished: function(id, x, y) { panel.finishDrag(id, x, y) }
                                    onItemDragCanceled: { panel.dragId = ""; panel.hoveredTarget = null; panel.game.cancelActionDrag() }
                                }
                            }
                        }
                    }

                    Rectangle {
                        id: bankPanel
                        width: parent.width - bagPanel.width - 8
                        height: 289
                        color: "#172126"
                        border.color: RuntimeTheme.GGTheme.edge
                        border.width: 1
                        GGText { colorKey: "ui.GameInventoryPanel.14";
                            anchors.left: parent.left
                            anchors.top: parent.top
                            anchors.leftMargin: 10
                            anchors.topMargin: 5
                            text: "◆  GEMENSAM KISTA   " + panel.bankRows.length
                                + " / " + String(panel.game.bank.capacity || 48)
                            color: "#f0d391"
                            font.family: "serif"
                            font.pixelSize: 13
                            font.bold: true
                        }
                        GGText { colorKey: "ui.GameInventoryPanel.15";
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.rightMargin: 10
                            anchors.topMargin: 8
                            text: panel.bankAccessible ? "ÖPPEN" : (panel.nearBank ? "INOM RÄCKHÅLL" : "LÅST")
                            color: panel.bankAccessible ? "#a6cead" : "#bc9c72"
                            font.family: "monospace"
                            font.pixelSize: 9
                        }
                        Grid {
                            visible: panel.nearBank || panel.bankAccessible
                            anchors.left: parent.left
                            anchors.top: parent.top
                            anchors.leftMargin: 10
                            anchors.topMargin: 25
                            columns: 6
                            spacing: 3
                            Repeater {
                                id: bankRepeater
                                model: 48
                                delegate: GameInventorySlot { property string uiColorScope: "ui.widget.GameInventoryPanel.GameInventorySlot.27";
                                    required property int index
                                    width: 29; height: 29
                                    slotIndex: index
                                    dropZone: "BANK"
                                    itemData: panel.bankAccessible
                                        ? panel.rowAt(panel.bankRows, index) : null
                                    dragRoot: panel
                                    selected: occupied && panel.game.selectedItemId === itemId
                                    dropHovered: panel.hoveredTarget === this
                                    onActivated: panel.game.selectedItemId = itemId
                                    onDoubleActivated: panel.activateTwice(itemId)
                                    onItemDragMoved: function(id, x, y) { panel.dragMoved(id, x, y) }
                                    onItemDragFinished: function(id, x, y) { panel.finishDrag(id, x, y) }
                                    onItemDragCanceled: { panel.dragId = ""; panel.hoveredTarget = null; panel.game.cancelActionDrag() }
                                }
                            }
                        }
                        Column {
                            visible: !(panel.nearBank || panel.bankAccessible)
                            anchors.centerIn: parent
                            spacing: 10
                            Image {
                                width: 78; height: 78
                                anchors.horizontalCenter: parent.horizontalCenter
                                source: "../assets/authored/items/icons/container-supply_crate.png"
                                fillMode: Image.PreserveAspectFit
                            }
                            GGText { colorKey: "ui.GameInventoryPanel.16";
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: "Gå fram till kistan på startön"
                                color: RuntimeTheme.GGTheme.text
                                font.family: "serif"
                                font.pixelSize: 13
                            }
                        }
                        GameInventoryAction { property string uiColorScope: "ui.widget.GameInventoryPanel.GameInventoryAction.28";
                            visible: panel.nearBank && !panel.bankAccessible
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            anchors.margins: 8
                            text: "ÖPPNA KISTAN"
                            onClicked: panel.ensureBankOpen()
                        }
                        GameInventoryAction { property string uiColorScope: "ui.widget.GameInventoryPanel.GameInventoryAction.29";
                            visible: panel.bankAccessible
                                && Number(panel.game.bank.loot_count || 0) > 0
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            anchors.margins: 8
                            text: "PLUNDRA " + String(panel.game.bank.loot_count || 0)
                            onClicked: panel.game.lootContainer(String(panel.game.bank.container_id || ""))
                        }
                    }
                }

                Rectangle {
                    width: parent.width
                    height: 30
                    color: "#25332f"
                    border.color: "#6c623f"
                    border.width: 1
                    GGText { colorKey: "ui.GameInventoryPanel.17";
                        anchors.centerIn: parent
                        text: "DRA EN IKON TILL EN NY PLATS   ·   DUBBELKLICKA FÖR ATT TA PÅ / AV   ·   B ELLER I STÄNGER"
                        color: "#dcc694"
                        font.family: "monospace"
                        font.pixelSize: 10
                    }
                }
            }
        }
    }

    Rectangle {
        visible: panel.dragId !== ""
        x: panel.dragX - 19
        y: panel.dragY - 19
        width: 40; height: 40
        z: 1000
        color: "#27332f"
        opacity: 0.85
        border.color: "#f3d38b"
        border.width: 2
        Image {
            anchors.fill: parent
            anchors.margins: 2
            source: panel.draggedRow ? panel.iconSourceFor(panel.draggedRow) : ""
            fillMode: Image.PreserveAspectFit
        }
    }
}
