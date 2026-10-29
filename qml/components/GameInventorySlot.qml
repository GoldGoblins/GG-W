import QtQuick
import QtQuick.Controls

Rectangle {
    id: slot
    property var itemData: null
    property string slotLabel: ""
    property string gearCode: ""
    property string dropZone: "BAG"
    property int slotIndex: -1
    property bool selected: false
    property bool dropHovered: false
    property Item dragRoot: null
    readonly property bool occupied: Boolean(itemData && itemData.instance_id)
    readonly property string itemId: occupied ? String(itemData.instance_id) : ""
    readonly property string iconSource: {
        if (!slot.occupied)
            return ""
        return String(slot.itemData.icon || "../assets/authored/items/icons/unknown.png")
    }
    signal activated()
    signal doubleActivated()
    signal itemDragMoved(string instanceId, real x, real y)
    signal itemDragFinished(string instanceId, real x, real y)
    signal itemDragCanceled()

    color: slot.dropHovered ? "#74613a"
        : (slot.selected ? "#3b3d32" : "#1b252a")
    border.width: slot.dropHovered ? 3 : (slot.selected ? 2 : 1)
    border.color: slot.dropHovered ? "#ffe08a"
        : (slot.selected ? "#d9ad5e"
            : (slot.occupied ? String(slot.itemData.rarity_color || "#877c66")
                : "#5a5d54"))
    radius: 2

    Rectangle {
        anchors.fill: parent
        anchors.margins: 3
        color: "#11191e"
        border.color: "#39464a"
        border.width: 1
    }

    Image {
        id: icon
        visible: slot.occupied
        anchors.fill: parent
        anchors.margins: 2
        source: slot.iconSource
        fillMode: Image.PreserveAspectFit
        smooth: true
        mipmap: true
        asynchronous: true
    }

    Image {
        visible: slot.occupied && icon.status === Image.Error
        anchors.fill: parent
        anchors.margins: 3
        source: "../assets/authored/items/icons/unknown.png"
        fillMode: Image.PreserveAspectFit
    }

    Rectangle {
        visible: slot.occupied && Number(slot.itemData.quantity || 1) > 1
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 1
        width: quantityLabel.implicitWidth + 5
        height: quantityLabel.implicitHeight + 2
        color: "#11191e"
        GGText { colorKey: "ui.GameInventorySlot.1";
            id: quantityLabel
            anchors.centerIn: parent
            text: slot.occupied ? String(slot.itemData.quantity || 1) : ""
            color: "#f7dfa7"
            font.family: "monospace"
            font.pixelSize: 9
            font.bold: true
        }
    }

    MouseArea {
        id: hit
        anchors.fill: parent
        enabled: slot.occupied
        hoverEnabled: true
        preventStealing: true
        cursorShape: slot.occupied ? Qt.OpenHandCursor : Qt.ArrowCursor
        property real pressX: 0
        property real pressY: 0
        property bool draggingItem: false
        onPressed: function(mouse) {
            pressX = mouse.x
            pressY = mouse.y
            draggingItem = false
        }
        onPositionChanged: function(mouse) {
            if (!pressed || !slot.occupied || !slot.dragRoot)
                return
            if (!draggingItem && Math.hypot(mouse.x - pressX, mouse.y - pressY) > 5)
                draggingItem = true
            if (draggingItem) {
                var point = slot.mapToItem(slot.dragRoot, mouse.x, mouse.y)
                slot.itemDragMoved(slot.itemId, point.x, point.y)
            }
        }
        onReleased: function(mouse) {
            if (draggingItem && slot.dragRoot) {
                var point = slot.mapToItem(slot.dragRoot, mouse.x, mouse.y)
                slot.itemDragFinished(slot.itemId, point.x, point.y)
            } else {
                slot.activated()
            }
            draggingItem = false
        }
        onCanceled: {
            if (draggingItem)
                slot.itemDragCanceled()
            draggingItem = false
        }
        onDoubleClicked: slot.doubleActivated()
    }
    ToolTip.visible: hit.containsMouse && slot.occupied && !hit.draggingItem
    ToolTip.text: slot.occupied
        ? String(slot.itemData.name || "Föremål")
            + " · " + String(slot.itemData.rarity || "COMMON")
            + (slot.itemData.scroll_description ? "\n" + slot.itemData.scroll_description : "")
            + (slot.itemData.gear && slot.itemData.gear.enchantments
                ? slot.itemData.gear.enchantments.map(function(enchant) {
                    return "\n" + String(enchant.name || "Enchant") + ": " + String(enchant.description || "")
                  }).join("") : "")
        : slot.slotLabel
}
