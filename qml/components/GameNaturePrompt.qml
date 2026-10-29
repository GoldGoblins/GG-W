import QtQuick
import QtQuick.Controls

Rectangle {
    id: panel
    required property var surface
    property var targetInfo: surface ? surface.natureTarget : ({})
    visible: Boolean(targetInfo.available)
    width: 252
    height: column.implicitHeight + 24
    color: "#df1b2522"
    border.color: "#899777"
    radius: 3
    Column {
        id: column
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 12
        spacing: 6
        GGText { colorKey: "ui.GameNaturePrompt.1";
            width: parent.width
            text: String(panel.targetInfo.name || "Nature")
            color: "#e8c57b"
            font.family: "monospace"
            font.pixelSize: 13
            elide: Text.ElideRight
        }
        GGText { colorKey: "ui.GameNaturePrompt.2";
            text: Number(panel.targetInfo.distance_m || 0).toFixed(1) + " m"
                + (panel.targetInfo.dead ? " · Remains" : "")
            color: "#cad7bd"
            font.pixelSize: 11
        }
        Repeater {
            // Fixed handles: changing cooldown/range does not recreate buttons.
            model: 8
            delegate: Button { property string uiColorScope: "ui.control.GameNaturePrompt.1";
                required property int index
                readonly property var modelData: (panel.targetInfo.actions || [])[index] || ({})
                visible: !!modelData.id
                width: column.width
                height: 30
                enabled: Boolean(modelData.ready)
                text: String(modelData.name || "Interact") + (modelData.reason ? " · " + modelData.reason : "")
                contentItem: GGText { colorKey: "ui.GameNaturePrompt.3";
                    text: parent.text
                    color: parent.enabled ? "#e0e7cf" : "#929e8c"
                    font.pixelSize: 11
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                }
                background: Rectangle {
                    color: parent.down ? "#405749" : "#253b32"
                    border.color: "#607365"
                    radius: 2
                }
                onClicked: panel.surface.interactNature(panel.targetInfo.id, modelData.id)
            }
        }
        GGText { colorKey: "ui.GameNaturePrompt.4";
            width: parent.width
            wrapMode: Text.WordWrap
            text: {
                var result = panel.surface ? panel.surface.nature.last_result || ({}) : ({})
                var loot = result.loot || ({})
                return loot.name ? "+" + loot.quantity + " " + loot.name : String(result.message || result.error || "E · Gather    T · Hunt")
            }
            color: "#cad7bd"
            font.pixelSize: 11
        }
    }
}
