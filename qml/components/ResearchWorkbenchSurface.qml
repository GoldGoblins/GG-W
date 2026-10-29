
import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    objectName: "researchWorkbench"
    property var surfaceHost: null
    property var deskData: ({})
    property string section: "Källkö"
    property string batchId: ""
    property string taskFilter: ""
    property string ticket: ""
    property string pendingOperation: ""
    property string titleDraft: ""
    property string linksDraft: ""
    property string notice: "Källor granskas av AI:n i det godkända arbetet. Kön startar inga hämtningar på egen hand."
    property var opened: ({})
    property int firstLine: 1
    property var historySource: ({})
    readonly property bool busy: ticket.length > 0
    readonly property var batches: deskData.batches || []
    readonly property var items: deskData.items || []
    readonly property var selectedBatch: batches.filter(function(b) { return b.id === root.batchId })[0] || ({})

    function bridge(op, payload) {
        if (!surfaceHost || !surfaceHost.researchCommand) return {status: "ERROR", reason: "Research ansluter"}
        try { return JSON.parse(surfaceHost.researchCommand(JSON.stringify({op: op, payload: payload}))) }
        catch (e) { return {status: "ERROR", reason: "Ogiltigt svar. Dina utkast finns kvar."} }
    }
    function request(operation, parameters) {
        if (busy) return false
        var response = bridge("workbench_submit", {operation: operation, arguments: parameters || {}})
        if (response.status !== "QUEUED" || !response.ticket) {
            notice = response.reason || response.status || "Kunde inte starta"
            return false
        }
        pendingOperation = operation
        ticket = response.ticket
        return true
    }
    function refresh() { return request("snapshot", {batch_id: batchId, task: taskFilter}) }
    function poll() {
        var response = bridge("workbench_result", {ticket: ticket})
        if (response.status === "RUNNING") return
        var result = response.status === "COMPLETE" && response.result ? response.result
            : {status: "ERROR", reason: response.reason || "Ofullständigt svar från researcharbetaren"}
        var operation = pendingOperation
        ticket = ""
        pendingOperation = ""
        if (result.status === "ERROR") { notice = result.reason || "Kunde inte läsa arbetsytan"; return }
        if (operation === "snapshot") {
            if (!Array.isArray(result.items) || !Array.isArray(result.batches)) {
                notice = "Ofullständigt svar. Den senaste vyn finns kvar."
                return
            }
            deskData = result
            batchId = String(result.batch_id || "")
        } else if (operation === "observation") {
            opened = result
        } else {
            if (operation === "create_batch" && (result.status === "BATCH_CREATED" || result.status === "BATCH_EXISTS")) {
                batchId = result.batch_id
                titleDraft = ""
                linksDraft = ""
                notice = result.unique + " unika källor · " + result.duplicates + " dubbletter sammanslagna"
            } else if (operation === "control_batch") {
                notice = result.status === "RUNNING" ? "Kön är tillgänglig för AI:n. Ingen källa hämtas automatiskt."
                    : (result.status === "PAUSED" ? "Pausad. Sena svar kan inte avsluta en avbruten källa." : "Kön är stoppad. Underlaget finns kvar.")
            } else notice = result.status
            refresh()
        }
    }
    function label(state) {
        var labels = {PENDING: "Väntar", IN_PROGRESS: "Pågår", READ: "Underlag sparat", BLOCKED: "Blockerad", SKIPPED: "Överhoppad",
            RUNNING: "Aktiv", PAUSED: "Pausad", CANCELLED: "Stoppad", PASS: "Godkänt", FAIL: "Underkänt", STALE: "Inaktuellt",
            UNVERIFIED: "Ej verifierat", CURRENT: "Aktuell", UNREVIEWED: "Ej omprövad", CONTESTED: "Bestridd", SUPERSEDED: "Ersatt",
            NOT_YET_VALID: "Gäller senare", NO_TESTS: "Inga tester kördes", INCOMPLETE: "Ofullständigt", ERROR: "Fel", TIMEOUT: "Tidsgräns", INTERRUPTED: "Avbruten", INVALID_OUTPUT: "Oläsbar testutdata", OUTPUT_LIMIT: "För stor testutdata"}
        return labels[state] || state || "Okänd"
    }
    function stateColor(state) {
        return state === "PASS" || state === "READ" || state === "CURRENT" ? RuntimeTheme.GGTheme.positive
            : (state === "FAIL" || state === "BLOCKED" || state === "CONTESTED" ? "#ca9486" : "#9a9486")
    }
    function openObservation(session, id, start) {
        firstLine = start || 1
        request("observation", {session: session, observation_id: id, start: firstLine, count: 80})
    }
    function originalText() {
        if (typeof opened.text === "string") return opened.text
        return (opened.lines || []).map(function(line) { return String(line.line) + "  " + line.text + (line.clipped ? " [raden fortsätter]\n" : "") }).join("")
    }
    function openFragment(offset) {
        return request("observation", {session: opened.session, observation_id: opened.observation_id,
            expected_version: opened.version, offset: Math.max(0, offset), length: 16000})
    }
    function usageText(bucket) {
        var basis = bucket.basis === "PROVIDER_REPORTED" ? "Rapporterat" : (bucket.basis === "ESTIMATED" ? "Uppskattat" : "Okänt")
        var costs = Object.keys(bucket.known_costs || {}).map(function(currency) { return Number(bucket.known_costs[currency]).toFixed(4) + " " + currency })
        return basis + " · " + bucket.attempts + " försök · " + bucket.failed + " avbrutna/misslyckade"
            + " · token in/ut " + (bucket.input_tokens === null ? "?" : bucket.input_tokens) + "/" + (bucket.output_tokens === null ? "?" : bucket.output_tokens)
            + " · " + (costs.length ? costs.join(" + ") : "kostnad okänd")
            + (bucket.missing_costs ? " · " + bucket.missing_costs + " utan kostnadsuppgift" : "")
    }
    Component.onCompleted: if (visible) refresh()
    onVisibleChanged: if (visible) refresh()
    onSurfaceHostChanged: if (visible && surfaceHost) refresh()
    Timer { interval: 150; repeat: true; running: root.busy; onTriggered: root.poll() }
    Timer { interval: 5000; repeat: true; running: root.visible && !root.busy; onTriggered: root.refresh() }

    ColumnLayout {
        anchors.fill: parent
        spacing: 8
        Flow {
            Layout.fillWidth: true
            spacing: 4
            Repeater {
                model: ["Källkö", "Original", "Tester", "Källstatus"]
                ResearchAction { property string uiColorScope: "ui.widget.ResearchWorkbenchSurface.ResearchAction.1";
                    required property string modelData
                    required property int index
                    text: modelData; checked: root.section === modelData
                    objectName: "workbenchSection_" + index
                    onClicked: { root.section = modelData; root.refresh() }
                }
            }
            ResearchAction { property string uiColorScope: "ui.widget.ResearchWorkbenchSurface.ResearchAction.2"; iconKind: "refresh"; hint: "Uppdatera"; enabled: !root.busy; onClicked: root.refresh() }
        }
        GGText { colorKey: "ui.ResearchWorkbenchSurface.1";
            Layout.fillWidth: true
            text: root.notice
            textFormat: Text.PlainText
            color: "#89919b"; font.pixelSize: 11; wrapMode: Text.WordWrap
        }
        ColumnLayout {
            visible: root.section === "Källkö"
            Layout.fillWidth: true; Layout.fillHeight: true; spacing: 7
            GgField { property string uiColorScope: "ui.widget.ResearchWorkbenchSurface.GgField.3"; Layout.fillWidth: true; placeholderText: "Namn på researchjobbet"; text: root.titleDraft; onTextChanged: root.titleDraft = text }
            ScrollView {
                Layout.fillWidth: true; Layout.preferredHeight: 64
                TextArea {
                    objectName: "workbenchLinks"
                    text: root.linksDraft; onTextChanged: root.linksDraft = text
                    placeholderText: "Klistra in källänkar – dubbletter slås ihop"
                    color: "#cbd0d7"; placeholderTextColor: "#65707b"; font.pixelSize: 12
                    wrapMode: TextEdit.Wrap; selectByMouse: true
                    background: Rectangle { color: RuntimeTheme.GGTheme.canvas; border.color: RuntimeTheme.GGTheme.selected; radius: 3 }
                }
            }
            Flow {
                Layout.fillWidth: true; spacing: 6
                ResearchAction { property string uiColorScope: "ui.widget.ResearchWorkbenchSurface.ResearchAction.4"; objectName: "workbenchCreate"; text: "Skapa källkö"; quiet: false; enabled: !root.busy && root.linksDraft.trim().length > 0; onClicked: root.request("create_batch", {title: root.titleDraft, links: root.linksDraft}) }
                ResearchAction { property string uiColorScope: "ui.widget.ResearchWorkbenchSurface.ResearchAction.5"; objectName: "workbenchPause"; iconKind: root.selectedBatch.state === "RUNNING" ? "pause" : "play"; hint: root.selectedBatch.state === "RUNNING" ? "Pausa källkön" : "Gör kön tillgänglig för AI:n"; enabled: !root.busy && !!root.batchId && root.selectedBatch.state !== "CANCELLED"; onClicked: root.request("control_batch", {batch_id: root.batchId, action: root.selectedBatch.state === "RUNNING" ? "pause" : "resume"}) }
                ResearchAction { property string uiColorScope: "ui.widget.ResearchWorkbenchSurface.ResearchAction.6"; objectName: "workbenchStop"; iconKind: "stop"; hint: "Stoppa kön och behåll sparat underlag"; enabled: !root.busy && !!root.batchId && root.selectedBatch.state !== "CANCELLED"; onClicked: root.request("control_batch", {batch_id: root.batchId, action: "cancel"}) }
            }
            ComboBox { property string uiColorScope: "ui.control.ResearchWorkbenchSurface.1";
                Layout.fillWidth: true; model: root.batches; textRole: "title"
                currentIndex: Math.max(0, root.batches.findIndex(function(b) { return b.id === root.batchId }))
                onActivated: { root.batchId = root.batches[currentIndex].id; root.refresh() }
                visible: root.batches.length > 1
            
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignLeft }
}
            GGText { colorKey: "ui.ResearchWorkbenchSurface.2";
                Layout.fillWidth: true; textFormat: Text.PlainText
                text: root.selectedBatch.title ? root.selectedBatch.title + " · " + root.label(root.selectedBatch.state)
                    + " · " + root.selectedBatch.read + "/" + root.selectedBatch.total + " sparade · " + root.selectedBatch.blocked + " blockerade" : "Ingen källkö ännu"
                color: "#b3b8be"; font.pixelSize: 12; wrapMode: Text.WordWrap
            }
            ListView {
                objectName: "workbenchSources"
                Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 4; model: root.items
                ScrollBar.vertical: GgScrollBar { property string uiColorScope: "ui.widget.ResearchWorkbenchSurface.GgScrollBar.7";}
                delegate: Rectangle {
                    required property var modelData
                    width: ListView.view.width; height: 76; color: RuntimeTheme.GGTheme.raised; radius: 3
                    RowLayout {
                        anchors.fill: parent; anchors.margins: 8; spacing: 5
                        ColumnLayout {
                            Layout.fillWidth: true; spacing: 3
                            GGText { colorKey: "ui.ResearchWorkbenchSurface.3"; Layout.fillWidth: true; text: modelData.url; textFormat: Text.PlainText; color: "#bac1ca"; font.pixelSize: 12; elide: Text.ElideMiddle }
                            GGText { colorKey: "ui.ResearchWorkbenchSurface.4"; text: root.label(modelData.state); color: root.stateColor(modelData.state); font.pixelSize: 11 }
                            GGText { colorKey: "ui.ResearchWorkbenchSurface.5"; Layout.fillWidth: true; text: modelData.note || "Inväntar granskning"; textFormat: Text.PlainText; color: "#717b87"; font.pixelSize: 10; elide: Text.ElideRight }
                        }
                        ResearchAction { property string uiColorScope: "ui.widget.ResearchWorkbenchSurface.ResearchAction.8"; iconKind: "open"; hint: "Visa sparat underlag"; visible: !!modelData.observation_id; enabled: !root.busy; onClicked: { root.section = "Original"; root.openObservation(root.batchId, modelData.observation_id, 1) } }
                        ResearchAction { property string uiColorScope: "ui.widget.ResearchWorkbenchSurface.ResearchAction.9"; iconKind: "refresh"; hint: "Försök denna källa igen"; visible: modelData.state === "BLOCKED" || modelData.state === "SKIPPED"; enabled: !root.busy; onClicked: root.request("retry_source", {item_id: modelData.id}) }
                    }
                }
            }
        }
        ColumnLayout {
            visible: root.section === "Original"
            Layout.fillWidth: true; Layout.fillHeight: true
            GGText { colorKey: "ui.ResearchWorkbenchSurface.6"; Layout.fillWidth: true; text: "Senaste 32 underlagen. Sparat original efter maskning; utdrag anger vad som utelämnats."; color: "#858e99"; font.pixelSize: 11; wrapMode: Text.WordWrap }
            ListView {
                Layout.fillWidth: true; Layout.preferredHeight: 100; clip: true; model: root.deskData.observations || []
                ScrollBar.vertical: GgScrollBar { property string uiColorScope: "ui.widget.ResearchWorkbenchSurface.GgScrollBar.10";}
                delegate: ResearchAction { property string uiColorScope: "ui.widget.ResearchWorkbenchSurface.ResearchAction.11";
                    required property var modelData
                    width: ListView.view.width; text: modelData.title || modelData.source
                    hint: "Öppna underlag · " + modelData.created_at
                    enabled: !root.busy
                    onClicked: root.openObservation(modelData.session, modelData.id, 1)
                }
            }
            GGText { colorKey: "ui.ResearchWorkbenchSurface.7"; Layout.fillWidth: true; textFormat: Text.PlainText; text: (root.opened.title || "Välj ett underlag") + (root.opened.status === "OBSERVATION_FRAGMENT" ? " · tecken " + (root.opened.offset+1) + "–" + root.opened.next_offset + " av " + root.opened.total_characters : (root.opened.status ? " · " + root.opened.total_lines + " rader · " + root.opened.omitted_lines + " utelämnade" : "")) + (root.opened.status ? " · exit " + (root.opened.exit_code === null ? "okänd" : root.opened.exit_code) : ""); color: "#a8b0b9"; font.pixelSize: 11; wrapMode: Text.WordWrap }
            ScrollView {
                Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                TextArea {
                    objectName: "workbenchOriginal"
                    text: root.originalText(); textFormat: TextEdit.PlainText; readOnly: true; selectByMouse: true
                    color: "#b9c0c9"; font.family: "monospace"; font.pixelSize: 12; wrapMode: TextEdit.Wrap
                    background: Rectangle { color: RuntimeTheme.GGTheme.canvas; radius: 3 }
                }
            }
            Row {
                spacing: 6
                ResearchAction { property string uiColorScope: "ui.widget.ResearchWorkbenchSurface.ResearchAction.12"; iconKind: "previous"; hint: "Föregående del"; enabled: !root.busy && (root.opened.status === "OBSERVATION_FRAGMENT" ? root.opened.offset > 0 : root.firstLine > 1); onClicked: root.opened.status === "OBSERVATION_FRAGMENT" ? root.openFragment(root.opened.offset-16000) : root.openObservation(root.opened.session, root.opened.observation_id, Math.max(1, root.firstLine-80)) }
                ResearchAction { property string uiColorScope: "ui.widget.ResearchWorkbenchSurface.ResearchAction.13"; iconKind: "next"; hint: "Nästa del"; enabled: !root.busy && !!root.opened.observation_id && (root.opened.status === "OBSERVATION_FRAGMENT" ? !root.opened.eof : root.firstLine+80 <= root.opened.total_lines); onClicked: root.opened.status === "OBSERVATION_FRAGMENT" ? root.openFragment(root.opened.next_offset) : root.openObservation(root.opened.session, root.opened.observation_id, root.firstLine+80) }
                ResearchAction { property string uiColorScope: "ui.widget.ResearchWorkbenchSurface.ResearchAction.14"; text: root.opened.status === "OBSERVATION_FRAGMENT" ? "Visa rader" : "Läs hela texten"; visible: root.opened.status === "OBSERVATION_FRAGMENT" || (root.opened.lines || []).some(function(line) { return line.clipped }); enabled: !root.busy; onClicked: root.opened.status === "OBSERVATION_FRAGMENT" ? root.openObservation(root.opened.session, root.opened.observation_id, 1) : root.openFragment(0) }
            }
        }
        ColumnLayout {
            visible: root.section === "Tester"
            Layout.fillWidth: true; Layout.fillHeight: true
            ComboBox { property string uiColorScope: "ui.control.ResearchWorkbenchSurface.2";
                Layout.fillWidth: true
                model: ["Alla uppgifter"].concat(root.deskData.tasks || [])
                currentIndex: Math.max(0, (root.deskData.tasks || []).indexOf(root.taskFilter) + 1)
                onActivated: { root.taskFilter = currentIndex > 0 ? root.deskData.tasks[currentIndex-1] : ""; root.refresh() }
            
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignLeft }
}
            GGText { colorKey: "ui.ResearchWorkbenchSurface.8"; Layout.fillWidth: true; text: "Krav → källversion → körd kontroll. Ändrad källa gör kvittot inaktuellt. Senaste 64 kraven visas; välj uppgift för att avgränsa."; color: "#858e99"; font.pixelSize: 11; wrapMode: Text.WordWrap }
            GGText { colorKey: "ui.ResearchWorkbenchSurface.9"; Layout.fillWidth: true; visible: !!root.deskData.usage; text: root.deskData.usage ? String(root.deskData.usage.attempts) + " modellförsök · " + (root.deskData.usage.complete_cost ? "rapporterad kostnad finns för alla" : "kostnad ofullständig eller okänd") : ""; color: "#9a9486"; font.pixelSize: 11; wrapMode: Text.WordWrap }
            Repeater {
                model: root.deskData.usage ? root.deskData.usage.buckets.filter(function(b) { return b.attempts > 0 }) : []
                GGText { colorKey: "ui.ResearchWorkbenchSurface.10";
                    required property var modelData
                    Layout.fillWidth: true
                    text: root.usageText(modelData); textFormat: Text.PlainText; color: "#85919d"; font.pixelSize: 11; wrapMode: Text.WordWrap
                }
            }
            GGText { colorKey: "ui.ResearchWorkbenchSurface.11"; visible: !(root.deskData.requirements || []).length; Layout.fillWidth: true; text: "Inga kontroller registrerade ännu. AI:n kopplar konkreta krav till tester under arbetet."; color: "#7f8995"; font.pixelSize: 12; wrapMode: Text.WordWrap }
            ListView {
                Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 6; model: root.deskData.requirements || []
                ScrollBar.vertical: GgScrollBar { property string uiColorScope: "ui.widget.ResearchWorkbenchSurface.GgScrollBar.15";}
                delegate: Rectangle {
                    required property var modelData
                    width: ListView.view.width; height: 82; color: RuntimeTheme.GGTheme.raised; radius: 3
                    RowLayout {
                        anchors.fill: parent; anchors.margins: 8
                        ColumnLayout {
                            Layout.fillWidth: true; spacing: 4
                            GGText { colorKey: "ui.ResearchWorkbenchSurface.12"; Layout.fillWidth: true; text: modelData.title; textFormat: Text.PlainText; color: "#c3cad2"; font.pixelSize: 12; elide: Text.ElideRight }
                            GGText { colorKey: "ui.ResearchWorkbenchSurface.13"; text: root.label(modelData.state); color: root.stateColor(modelData.state); font.pixelSize: 11 }
                            GGText { colorKey: "ui.ResearchWorkbenchSurface.14"; Layout.fillWidth: true; text: modelData.test_module; textFormat: Text.PlainText; color: "#727c88"; font.pixelSize: 10; elide: Text.ElideRight }
                        }
                        ResearchAction { property string uiColorScope: "ui.widget.ResearchWorkbenchSurface.ResearchAction.16"; iconKind: "open"; hint: "Öppna verklig testutdata"; visible: !!modelData.receipt && !!modelData.receipt.observation_id; enabled: !root.busy; onClicked: { root.section = "Original"; root.openObservation(modelData.task, modelData.receipt.observation_id, 1) } }
                    }
                }
            }
        }
        ColumnLayout {
            visible: root.section === "Källstatus"
            Layout.fillWidth: true; Layout.fillHeight: true
            GGText { colorKey: "ui.ResearchWorkbenchSurface.15"; Layout.fillWidth: true; text: "Senaste 96 källkorten. Markera osäkra källor för omprövning. Historiken bevaras; omprövning återverifierar inte gamla slutsatser."; color: "#858e99"; font.pixelSize: 11; wrapMode: Text.WordWrap }
            ListView {
                Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 5; model: root.deskData.sources || []
                ScrollBar.vertical: GgScrollBar { property string uiColorScope: "ui.widget.ResearchWorkbenchSurface.GgScrollBar.17";}
                delegate: Rectangle {
                    required property var modelData
                    width: ListView.view.width; height: 84; color: RuntimeTheme.GGTheme.raised; radius: 3
                    RowLayout {
                        anchors.fill: parent; anchors.margins: 8
                        ColumnLayout {
                            Layout.fillWidth: true; spacing: 4
                            GGText { colorKey: "ui.ResearchWorkbenchSurface.16"; Layout.fillWidth: true; text: modelData.title; textFormat: Text.PlainText; color: "#c3cad2"; font.pixelSize: 12; elide: Text.ElideRight }
                            GGText { colorKey: "ui.ResearchWorkbenchSurface.17"; text: root.label(modelData.state) + " · " + modelData.history_count + " statusnoteringar"; color: root.stateColor(modelData.state); font.pixelSize: 11 }
                            GGText { colorKey: "ui.ResearchWorkbenchSurface.18"; Layout.fillWidth: true; text: modelData.history.length ? modelData.history[0].note : "Källans giltighet har inte omprövats"; textFormat: Text.PlainText; color: "#727c88"; font.pixelSize: 10; elide: Text.ElideRight }
                        }
                        ResearchAction { property string uiColorScope: "ui.widget.ResearchWorkbenchSurface.ResearchAction.18"; text: "?"; hint: "Markera som bestridd och begär omprövning"; enabled: !root.busy && modelData.state !== "CONTESTED"; onClicked: root.request("source_event", {source_id: modelData.id, state: "CONTESTED", note: "Användaren begär omprövning i RESEARCH"}) }
                        ResearchAction { property string uiColorScope: "ui.widget.ResearchWorkbenchSurface.ResearchAction.19"; iconKind: "open"; hint: "Visa källans statushistorik"; enabled: modelData.history.length > 0; onClicked: { root.historySource = modelData; historyPopup.open() } }
                        ResearchAction { property string uiColorScope: "ui.widget.ResearchWorkbenchSurface.ResearchAction.20"; iconKind: "refresh"; hint: "Markera inaktuell – behöver kontrolleras på nytt"; enabled: !root.busy && modelData.state !== "STALE"; onClicked: root.request("source_event", {source_id: modelData.id, state: "STALE", note: "Användaren begär ny källkontroll i RESEARCH"}) }
                    }
                }
            }
        }
    }
    Popup {
        id: historyPopup
        anchors.centerIn: parent
        width: Math.min(560, root.width-16); height: Math.min(360, root.height-16)
        modal: true; focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { color: "#191919"; border.color: "#555047"; radius: 4 }
        contentItem: ColumnLayout {
            RowLayout {
                Layout.fillWidth: true
                GGText { colorKey: "ui.ResearchWorkbenchSurface.19"; Layout.fillWidth: true; text: root.historySource.title || "Källhistorik"; textFormat: Text.PlainText; color: "#c8cfd7"; font.pixelSize: 13; elide: Text.ElideRight }
                ResearchAction { property string uiColorScope: "ui.widget.ResearchWorkbenchSurface.ResearchAction.21"; iconKind: "stop"; hint: "Stäng historiken"; onClicked: historyPopup.close() }
            }
            GGText { colorKey: "ui.ResearchWorkbenchSurface.20"; Layout.fillWidth: true; visible: root.historySource.history_truncated === true; text: "De senaste 32 av " + root.historySource.history_count + " noteringar visas. Äldre historik finns kvar i källjournalen."; color: "#86919d"; font.pixelSize: 11; wrapMode: Text.WordWrap }
            ListView {
                Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 12; model: root.historySource.history || []
                ScrollBar.vertical: GgScrollBar { property string uiColorScope: "ui.widget.ResearchWorkbenchSurface.GgScrollBar.22";}
                delegate: Column {
                    required property var modelData
                    width: ListView.view.width; spacing: 4
                    GGText { colorKey: "ui.ResearchWorkbenchSurface.21"; text: root.label(modelData.state) + " · " + modelData.observed_at; color: root.stateColor(modelData.state); font.pixelSize: 11 }
                    GGText { colorKey: "ui.ResearchWorkbenchSurface.22"; width: parent.width; text: modelData.note; textFormat: Text.PlainText; color: "#aab1ba"; font.pixelSize: 12; wrapMode: Text.WordWrap }
                    GGText { colorKey: "ui.ResearchWorkbenchSurface.23"; width: parent.width; text: "Gäller från " + (modelData.valid_at || "ej angivet") + " · till " + (modelData.valid_until || "ej angivet"); color: "#78828e"; font.pixelSize: 10; wrapMode: Text.WordWrap }
                }
            }
        }
    }
}
