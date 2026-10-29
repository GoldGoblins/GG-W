import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ScrollView {
    id: root
    objectName: "localGameSessionsScroll"
    property var services: ({})
    readonly property var arena: services.battlefields || ({})
    readonly property var expeditions: services.instance_sessions || ({})
    readonly property var queue: (arena.queue || [])[0] || ({})
    readonly property var meeting: expeditions.meeting || ({})
    signal requested(string operation, var fields)
    clip: true
    contentWidth: availableWidth
    contentHeight: sessionContent.implicitHeight
    ScrollBar.vertical.policy: ScrollBar.AsNeeded

    ColumnLayout {
        id: sessionContent
        width: root.availableWidth
        height: implicitHeight
        spacing: 10
        GGLabel { colorKey: "ui.LocalGameSessions.1"; text: "KUSTARENAN"; color: "#ebcf84"; font.bold: true }
        GGLabel { colorKey: "ui.LocalGameSessions.2";
            text: "Träna mot en verklig lokal invånare. Kampen slutar vid 1 HP och ger träningspoäng vid seger."
            wrapMode: Text.WordWrap; Layout.fillWidth: true
        }
        GGLabel { colorKey: "ui.LocalGameSessions.3";
            text: root.arena.ended ? "Kampen är avgjord." : root.arena.active ? "Kampen pågår · stäng tjänstefönstret för att spela."
                : root.queue.status === 2 ? "Din plats är klar · " + Math.ceil(Number(root.queue.remaining_ms || 0) / 1000) + " sekunder kvar att svara."
                : root.queue.status === 1 ? "Du väntar på en plats."
                : Number(root.arena.recovery_seconds || 0) > 0 ? "Nästa kamp kan börja om " + Number(root.arena.recovery_seconds) + " sekunder." : "Du står utanför kön."
            Layout.fillWidth: true; wrapMode: Text.WordWrap
        }
        RowLayout {
            Button { property string uiColorScope: "ui.control.LocalGameSessions.1"; objectName: "localArenaJoin"; text: "Ställ dig i kö"; enabled: !(root.arena.queue || []).length && !root.arena.active && !Number(root.arena.recovery_seconds || 0); onClicked: root.requested("BattlefieldJoin", {map:root.arena.map,instance:root.arena.instance,as_group:false}) 
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignHCenter }
}
            Button { property string uiColorScope: "ui.control.LocalGameSessions.2"; objectName: "localArenaEnter"; text: "Börja kampen"; enabled: root.queue.status === 2; onClicked: root.requested("BattlefieldPort", {slot:1,queue_id:root.queue.id,accept:true}) 
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignHCenter }
}
            Button { property string uiColorScope: "ui.control.LocalGameSessions.3"; objectName: "localArenaCancel"; text: root.arena.active ? "Avbryt kampen" : "Lämna kön"; enabled: !!root.queue.id && !root.arena.ended; onClicked: root.requested("BattlefieldPort", {slot:1,queue_id:root.queue.id,accept:false}) 
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignHCenter }
}
            Button { property string uiColorScope: "ui.control.LocalGameSessions.4"; objectName: "localArenaLeave"; text: "Avsluta"; enabled: !!root.arena.ended; onClicked: root.requested("BattlefieldLeave", {}) 
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignHCenter }
}
        }
        Repeater {
            model: root.arena.scores || []
            delegate: RowLayout {
                required property var modelData
                GGLabel { colorKey: "ui.LocalGameSessions.4"; text: modelData.name; Layout.fillWidth:true }
                GGLabel { colorKey: "ui.LocalGameSessions.5"; text: "Vinster " + Number(modelData.wins || 0) + "  ·  Poäng " + Number(modelData.honor || 0) }
            }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: "#665431" }
        GGLabel { colorKey: "ui.LocalGameSessions.6"; text: "EXPEDITIONER OCH KOMPANJONER"; color: "#ebcf84"; font.bold: true }
        GGLabel { colorKey: "ui.LocalGameSessions.7";
            text: "Välj en plats i världen. Du behöver nå entrén innan du kan gå in eller söka lokala kompanjoner."
            wrapMode:Text.WordWrap; Layout.fillWidth:true
        }
        ComboBox { property string uiColorScope: "ui.control.LocalGameSessions.5";
            id: place
            objectName: "localExpeditionPlace"
            model: root.expeditions.places || []
            textRole: "name"
            valueRole: "id"
            property string selectedId: ""
            function restoreSelection() {
                var rows = model || []
                for (var i = 0; i < rows.length; ++i) {
                    if (rows[i].id === selectedId) { currentIndex = i; return }
                }
                if (!selectedId && rows.length) selectedId = rows[0].id
            }
            onActivated: selectedId = String(currentValue || "")
            onSelectedIdChanged: restoreSelection()
            onModelChanged: Qt.callLater(restoreSelection)
            Layout.fillWidth:true
            readonly property var selected: {
                var rows = model || []
                for (var i = 0; i < rows.length; ++i) if (rows[i].id === selectedId) return rows[i]
                return ({})
            }
        
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignLeft }
}
        GGLabel { colorKey: "ui.LocalGameSessions.8"; text: "Avstånd till entrén: " + Number(place.selected.distance || 0).toFixed(0) + " m"; visible: !!place.selected.id }
        RowLayout {
            Button { property string uiColorScope: "ui.control.LocalGameSessions.6"; objectName: "localExpeditionEnter"; text: "Gå in"; enabled: !!place.selected.id && Number(place.selected.distance) <= 64 && !root.expeditions.active; onClicked: root.requested("InstanceEnter", {ref:place.selected.id}) 
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignHCenter }
}
            Button { property string uiColorScope: "ui.control.LocalGameSessions.7"; objectName: "localExpeditionExit"; text: "Till entrén"; enabled: !!root.expeditions.active; onClicked: root.requested("InstanceExit", {}) 
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignHCenter }
}
            Button { property string uiColorScope: "ui.control.LocalGameSessions.8"; objectName: "localExpeditionReset"; text: "Återställ expedition"; enabled: !!root.expeditions.can_reset; onClicked: root.requested("InstanceReset", {}) 
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignHCenter }
}
        }
        GGLabel { colorKey: "ui.LocalGameSessions.9";
            text: "Återställning kräver att gruppen är ute. Föremål du redan tagit behåller du."
            wrapMode:Text.WordWrap; Layout.fillWidth:true
        }
        RowLayout {
            Button { property string uiColorScope: "ui.control.LocalGameSessions.9"; objectName: "localMeetingJoin"; text: "Sök kompanjoner"; enabled: !!place.selected.id && Number(place.selected.distance) <= 64 && !root.meeting.ref && !((root.services.group || {}).members || []).length; onClicked: root.requested("MeetingStoneJoin", {ref:place.selected.id}) 
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignHCenter }
}
            Button { property string uiColorScope: "ui.control.LocalGameSessions.10"; objectName: "localMeetingAccept"; text: "Bilda gruppen"; enabled: root.meeting.stage === "OFFER"; onClicked: root.requested("MeetingStoneAccept", {}) 
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignHCenter }
}
            Button { property string uiColorScope: "ui.control.LocalGameSessions.11"; objectName: "localMeetingCancel"; text: "Avbryt sökningen"; enabled: !!root.meeting.ref; onClicked: root.requested("MeetingStoneCancel", {}) 
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignHCenter }
}
        }
        GGLabel { colorKey: "ui.LocalGameSessions.10";
            visible: !!root.meeting.ref
            text: root.meeting.stage === "OFFER" ? Number((root.meeting.candidates || []).length) + " kompanjoner väntar på ditt svar."
                : "Söker nära " + String(root.meeting.name || "entrén") + " · " + Number(root.meeting.remaining || 0) + " sekunder kvar."
            wrapMode:Text.WordWrap; Layout.fillWidth:true
        }
        Repeater {
            model: root.expeditions.lockouts || []
            delegate: GGLabel { colorKey: "ui.LocalGameSessions.11";
                required property var modelData
                text: modelData.name + " · " + Number((modelData.defeated || []).length) + " avgjorda möten · " + Math.ceil(Number(modelData.remaining || 0)/60) + " minuter kvar"
                wrapMode:Text.WordWrap; Layout.fillWidth:true
            }
        }
    }
}
