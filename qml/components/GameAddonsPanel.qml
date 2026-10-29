pragma ComponentBehavior: Bound

import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

Item {
    id: root
    required property var runtime
    property bool paneLive: true
    property bool expanded: false
    readonly property var state: runtime ? JSON.parse(runtime.addonsJson) : ({})
    readonly property var rows: state.rows || []
    width: expanded ? Math.max(180, Math.min(360, parent.width - 28)) : 76
    height: expanded ? Math.min(380, parent.height - 90, Math.max(190, 148 + rows.length * 62)) : 28
    visible: paneLive && Boolean(runtime)
    onExpandedChanged: if (runtime) {
        if (expanded) {runtime.refreshAddons();if(root.state.can_select_characters)runtime.beginAddonChoices(root.state.generation)}
        else runtime.finishAddonChoices(false,root.state.generation)
    }

    Timer {
        interval: 500
        running: root.expanded && root.visible
        repeat: true
        onTriggered: if (root.runtime) root.runtime.refreshAddons()
    }
    Rectangle {
        anchors.fill: parent
        visible: root.expanded
        color: "#f019232b"
        radius: 4
        border.color: RuntimeTheme.GGTheme.edge
    }
    GgButton { property string uiColorScope: "ui.control.GameAddonsPanel.1";
        objectName: "gameAddonsToggle"
        anchors.right: parent.right
        width: 76; height: 28
        text: root.expanded ? "Stäng" : "Tillägg"
        onClicked: root.expanded = !root.expanded
    }
    Column {
        visible: root.expanded
        x: 12; y: 10
        width: parent.width - 100
        spacing: 3
        GGText { colorKey: "ui.GameAddonsPanel.1";
            text: "KARAKTÄRENS TILLÄGG"
            color: RuntimeTheme.GGTheme.text; font.pixelSize: 11; font.bold: true
        }
        GGText { colorKey: "ui.GameAddonsPanel.2";
            width: parent.width
            text: root.state.can_edit ? "Valet sparas på datorn." : "Välj en karaktär först."
            color: RuntimeTheme.GGTheme.muted; font.pixelSize: 10; wrapMode: Text.WordWrap
        }
    }
    ListView {
        id: list
        objectName: "gameAddonsList"
        visible: root.expanded
        x: 12; y: root.state.editing ? 90 : 55; width: parent.width - 24
        height: Math.max(0, parent.height - (root.state.editing ? 210 : 148))
        clip: true
        model: root.rows
        delegate: Item {
            id: addon
            required property var modelData
            width: list.width; height: 62
            GgButton { property string uiColorScope: "ui.control.GameAddonsPanel.2";
                objectName: "gameAddonToggle_" + addon.modelData.id
                width: 44; height: 25
                enabled: Boolean(root.state.can_edit)
                checked: Boolean(addon.modelData.enabled)
                text: addon.modelData.mixed ? "DEL" : addon.modelData.enabled ? "PÅ" : "AV"
                onClicked: if (root.runtime) {
                    if (root.state.editing) root.runtime.stageAddonChoice(addon.modelData.id,!addon.modelData.enabled,root.state.generation)
                    else root.runtime.setAddon(addon.modelData.id,!addon.modelData.enabled,root.state.generation)
                }
            }
            Column {
                x: 52; width: parent.width - 52; spacing: 2
                GGText { colorKey: "ui.GameAddonsPanel.3";
                    width: parent.width
                    text: addon.modelData.title || addon.modelData.id
                    elide: Text.ElideRight; color: RuntimeTheme.GGTheme.text; font.pixelSize: 11
                }
                GGText { colorKey: "ui.GameAddonsPanel.4";
                    width: parent.width; wrapMode: Text.WordWrap
                    text: addon.modelData.mixed ? "Olika val för karaktärerna"
                        : root.state.editing ? (addon.modelData.enabled ? "Aktiveras vid nästa omladdning" : "Avstängt vid nästa omladdning")
                        : !addon.modelData.enabled && addon.modelData.loaded ? "Stängs av vid omladdning"
                        : addon.modelData.loaded ? "Aktivt"
                        : !addon.modelData.enabled ? "Avstängt"
                        : addon.modelData.reason === "NOT_DEMAND_LOADED"
                            || addon.modelData.reason === "DEP_NOT_DEMAND_LOADED" ? "Aktiveras vid omladdning"
                        : addon.modelData.reason ? "Kan inte laddas: " + addon.modelData.reason
                        : addon.modelData.load_on_demand ? "Laddas när det behövs"
                        : "Aktiveras vid omladdning"
                    color: RuntimeTheme.GGTheme.muted; font.pixelSize: 10
                }
            }
        }
        GGText { colorKey: "ui.GameAddonsPanel.5";
            anchors.centerIn: parent
            visible: root.rows.length === 0
            text: "Inga tillägg hittades."
            color: RuntimeTheme.GGTheme.muted; font.pixelSize: 11
        }
    }
    ComboBox { property string uiColorScope: "ui.control.GameAddonsPanel.3";
        objectName:"gameAddonCharacter"
        visible:root.expanded && Boolean(root.state.editing)
        x:12;y:52;width:parent.width-24;height:30
        model:root.state.characters || []
        textRole:"name";valueRole:"id"
        currentIndex:{var rows=root.state.characters || [];for(var i=0;i<rows.length;i++)if(rows[i].id===root.state.selected)return i;return 0}
        onActivated:if(root.runtime)root.runtime.selectAddonCharacter(currentValue,root.state.generation)
    
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignLeft }
}
    GGText { colorKey: "ui.GameAddonsPanel.6";
        visible: root.expanded
        x: 12; y: parent.height - (root.state.editing ? 118 : 86); width: parent.width - 24; height: 44
        text: root.state.error || (root.state.editing ? "Spara valet för den valda karaktären eller alla. Avbryt återgår till sparade val." : "Ladda om gränssnittet för att börja eller sluta köra tilläggen.")
        color: root.state.error ? "#f3ad88" : RuntimeTheme.GGTheme.muted
        font.pixelSize: 10; wrapMode: Text.WordWrap; elide: Text.ElideRight
    }
    Row {
        visible:root.expanded && Boolean(root.state.editing)
        x:12;y:parent.height-68;width:parent.width-24;spacing:8
        GgButton { property string uiColorScope: "ui.control.GameAddonsPanel.4";
            objectName:"gameAddonsSave";width:(parent.width-8)/2;height:25;text:"SPARA";enabled:Boolean(root.state.can_edit)
            onClicked:if(root.runtime && root.runtime.finishAddonChoices(true,root.state.generation))root.expanded=false
        }
        GgButton { property string uiColorScope: "ui.control.GameAddonsPanel.5";
            objectName:"gameAddonsCancel";width:(parent.width-8)/2;height:25;text:"AVBRYT"
            onClicked:root.expanded=false
        }
    }
    GgButton { property string uiColorScope: "ui.control.GameAddonsPanel.6";
        objectName: "gameAddonsReload"
        visible: root.expanded
        x: 12; y: parent.height - 36; width: parent.width - 24; height: 25
        text: "LADDA OM GRÄNSSNITT"
        enabled: Boolean(root.state.can_edit)
        onClicked: if (root.runtime && root.runtime.finishAddonChoices(true,root.state.generation)) {
            root.runtime.reloadAddons(root.state.generation)
            if(root.state.can_select_characters)root.runtime.beginAddonChoices(root.state.generation)
        }
    }
}
