
import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    objectName: "workspaceResearchPane"
    signal documentationRequested(string url)

    property var surfaceHost: null
    property color frameBorder: RuntimeTheme.GGTheme.edge
    property int frameRadius: 4
    property string statusJson: "{}"
    property string page: "BACKLOG"
    property string taskTitle: ""
    property string taskBody: ""
    property string evidenceTitle: ""
    property string evidenceClaim: ""
    property string evidenceUrl: ""
    property string sourceTitle: ""
    property string sourceText: ""
    property string methodName: ""
    property string methodTrigger: ""
    property string methodSteps: ""
    property string skillName: ""
    property string skillTemplate: ""
    property string skillScript: ""
    property string sqlText: "SELECT * FROM sources WHERE status = 'OK'"
    property string sqlResult: ""
    property string evalName: "WORKBENCH"
    property string activeRunId: ""
    property string eventStage: "OBSERVATION"
    property string eventNote: ""
    property string evalScore: ""
    property string notice: "LOCAL · READY"
    property var sqlPreview: ({})
    readonly property var tabs: ["BACKLOG", "EVIDENCE", "MEMORY", "WEB SKILLS", "SQL", "EVALS", "WASM LAB", "REVERSE", "GAMES", "WORKBENCH"]

    readonly property var status: {
        try { return JSON.parse(root.statusJson || "{}") } catch (err) { return {} }
    }
    readonly property var tasks: root.status.tasks || []
    readonly property var evidence: root.status.evidence || []
    readonly property var sources: root.status.sources || []
    readonly property var methods: root.status.methods || []
    readonly property var skills: root.status.skills || []
    readonly property var runs: root.status.runs || []

    function resultNotice(result) {
        return String(result.detail || result.reason || result.error || result.summary || result.status || "No result returned")
    }

    function failed(result) {
        var state = String(result.status || "ERROR")
        return state === "ERROR" || state === "UNKNOWN_COMMAND" || state === "BLOCKED"
            || state.indexOf("NOT_FOUND") >= 0 || state.indexOf("REJECTED") >= 0 || state.indexOf("EMPTY") >= 0
    }

    function applyRaw(raw, preserveNotice) {
        try {
            var parsed = JSON.parse(String(raw || "{}"))
            if (!parsed || root.failed(parsed) || !Array.isArray(parsed.tasks)) {
                if (!preserveNotice) root.notice = root.resultNotice(parsed || {})
                return false
            }
            root.statusJson = JSON.stringify(parsed)
            if (!preserveNotice) root.notice = root.resultNotice(parsed)
            var pending = (parsed.runs || []).filter(function(run) { return run.status === "RUNNING" })
            if (root.activeRunId && !pending.some(function(run) { return String(run.id) === root.activeRunId }))
                root.activeRunId = ""
            if (!root.activeRunId && pending.length) root.activeRunId = String(pending[0].id || "")
            return true
        } catch (err) {
            if (!preserveNotice) root.notice = "Invalid response from Research Desk. Your drafts are retained."
            return false
        }
    }

    function refresh(preserveNotice) {
        if (root.surfaceHost && root.surfaceHost.researchCommand)
            return root.applyRaw(root.surfaceHost.researchCommand(JSON.stringify({"op": "snapshot", "payload": {}})), preserveNotice === true)
        root.notice = "Research Desk is connecting. Your drafts are retained."
        return false
    }

    function command(op, payload) {
        if (!root.surfaceHost || !root.surfaceHost.researchCommand) {
            root.notice = "Research Desk is connecting. Your drafts are retained."
            return {status: "ERROR", reason: root.notice}
        }
        var raw = "{}"
        var result = {}
        try {
            raw = root.surfaceHost.researchCommand(JSON.stringify({"op": String(op || ""), "payload": payload || {}}))
            result = JSON.parse(String(raw || "{}"))
            if (!result || (!result.status && !(op === "sql_preview" && result.schema === "gg.sql.intent-preview.v1" && result.executed === false)))
                throw new Error("Missing status")
        } catch (err) {
            result = {status: "ERROR", reason: "Invalid response from Research Desk. Your drafts are retained."}
        }
        root.notice = root.resultNotice(result)
        if (String(op || "") === "sql_preview") {
            root.sqlResult = JSON.stringify(result)
            root.sqlPreview = result
            return result
        }
        if (String(op || "") !== "lab_verify" && !root.failed(result)) root.refresh(true)
        return result
    }

    function addTask(mode) {
        if (!root.taskTitle.trim()) { root.notice = "Enter a task title."; return false }
        if (root.command("add_task", {"title": root.taskTitle, "body": root.taskBody, "mode": mode}).status !== "TASK_CREATED") return false
        root.taskTitle = ""
        root.taskBody = ""
        return true
    }

    function addEvidence() {
        if (!root.evidenceTitle.trim() || !root.evidenceClaim.trim()) { root.notice = "Enter an evidence title and claim."; return false }
        var result = root.command("add_evidence", {"kind": "RESEARCH", "title": root.evidenceTitle,
            "claim": root.evidenceClaim, "source_url": root.evidenceUrl,
            "provenance": "USER_REVIEW", "confidence": 0.5})
        if (result.status !== "EVIDENCE_RECORDED") return false
        root.evidenceTitle = ""
        root.evidenceClaim = ""
        root.evidenceUrl = ""
        return true
    }

    function openSavedFinding(evidenceId) {
        if (reversePane.busy) { root.notice = "Finish or cancel the current analysis before opening another report."; return false }
        var result = root.command("lab_saved_report", {evidence_id: evidenceId})
        if (result.status !== "FINDING_REPORT_READY" || !result.report) return false
        reversePane.reportJson = JSON.stringify(result.report)
        reversePane.targetPath = String(result.report.path || "")
        reversePane.jobId = ""
        reversePane.jobState = ""
        reversePane.notice = "Saved observation reopened. The current source has not been reanalyzed."
        root.page = "REVERSE"
        return true
    }

    function addSource() {
        if (!root.sourceText.trim()) { root.notice = "Enter source text to remember."; return false }
        var result = root.command("ingest_source", {"title": root.sourceTitle, "content": root.sourceText,
            "kind": "RESEARCH_NOTE", "origin": "LOCAL_UI", "remember": true})
        if (result.status !== "SOURCE_INGESTED") return false
        root.sourceTitle = ""
        root.sourceText = ""
        return true
    }

    function addMethod() {
        var steps = root.methodSteps.split("\n").filter(function(item) { return String(item).trim().length > 0 })
        if (!root.methodName.trim() || !steps.length) { root.notice = "Enter a method name and at least one step."; return false }
        var result = root.command("add_method", {"name": root.methodName, "trigger": root.methodTrigger,
            "steps": steps, "proof": "Recorded in Research Desk"})
        if (result.status !== "METHOD_RECORDED") return false
        root.methodName = ""
        root.methodTrigger = ""
        root.methodSteps = ""
        return true
    }

    function addSkill() {
        if (!root.skillName.trim() || !root.skillScript.trim()) { root.notice = "Enter a web skill name and script draft."; return false }
        var result = root.command("add_web_skill", {"name": root.skillName, "template": root.skillTemplate,
            "script": root.skillScript, "parameters": []})
        if (result.status !== "WEB_SKILL_DRAFT" && result.status !== "WEB_SKILL_STRUCTURE_CHECKED") return false
        root.skillName = ""
        root.skillTemplate = ""
        root.skillScript = ""
        return true
    }

    function startEvaluation() {
        if (root.activeRunId) { root.notice = "Finish or cancel the selected evaluation before starting another."; return false }
        if (!root.evalName.trim()) { root.notice = "Enter an evaluation name."; return false }
        var result = root.command("start_run", {task_id: "", eval_name: root.evalName})
        if (result.status !== "RUN_STARTED") return false
        root.activeRunId = String(result.run_id)
        return true
    }

    function recordEvaluationEvent() {
        if (!root.activeRunId) { root.notice = "Select or start a running evaluation."; return false }
        var result = root.command("record_event", {run_id: root.activeRunId, stage: root.eventStage || "OBSERVATION",
            status: "OBSERVED", metadata: {note: root.eventNote, provenance: "USER_REVIEW"}})
        if (result.status !== "EVENT_RECORDED") return false
        root.eventNote = ""
        return true
    }

    function finishEvaluation(outcome) {
        if (!root.activeRunId) { root.notice = "Select or start a running evaluation."; return false }
        var score = root.evalScore.trim() ? Number(root.evalScore) : null
        if (score !== null && (!isFinite(score) || score < 0 || score > 1)) {
            root.notice = "Score must be a number between 0 and 1, or empty."
            return false
        }
        var result = root.command("finish_run", {run_id: root.activeRunId, status: outcome, score: score,
            metrics: {review_note: root.eventNote, provenance: "USER_REVIEW"}})
        if (result.status !== "RUN_FINISHED") return false
        root.activeRunId = ""
        root.eventNote = ""
        root.evalScore = ""
        return true
    }

    function evidenceContext(card) {
        var sourceState = card.source_freshness && card.source_freshness !== "UNREVIEWED"
            ? "Source: " + String(card.source_freshness) + " · " : ""
        var details = {}
        try { details = JSON.parse(String(card.details_json || "{}")) } catch (err) { }
        if (!details.collection)
            return sourceState + "Recorded: " + String(card.observed_at || "unknown")
        var location = details.location_precision === "PLACE_NAME_ESTIMATE"
            ? "Estimated place from headline"
            : (details.location_precision === "REFERENCE_LOCATION" ? "Reference location" : "Source-reported location")
        if (details.lat !== undefined && details.lon !== undefined)
            location += " " + String(details.lat) + ", " + String(details.lon)
        var measurements = []
        if (details.magnitude !== undefined)
            measurements.push("M" + String(details.magnitude))
        if (details.depth_km !== undefined)
            measurements.push("Depth " + String(details.depth_km) + " km")
        if (details.alt_m !== undefined)
            measurements.push("Altitude " + String(details.alt_m) + " m")
        if (details.heading !== undefined)
            measurements.push("Heading " + String(details.heading) + "°")
        return sourceState + "Collected: " + String(details.collected_at || "unknown")
            + " · Event time: " + String(details.event_time || "unknown")
            + " · " + String(details.freshness || "unknown")
            + " · " + location
            + (measurements.length ? " · " + measurements.join(" · ") : "")
            + " · Awaiting independent corroboration"
    }

    Component.onCompleted: root.refresh()
    onSurfaceHostChanged: root.refresh()
    onVisibleChanged: { if (visible) root.refresh() }

    Rectangle { anchors.fill: parent; color: RuntimeTheme.GGTheme.panel }

    Flickable {
        id: deskViewport
        objectName: "researchViewport"
        anchors.fill: parent
        contentWidth: root.page === "WORKBENCH" ? width : Math.max(760, width)
        contentHeight: height
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.horizontal: GgScrollBar { property string uiColorScope: "ui.widget.ResearchSurface.GgScrollBar.1"; keepVisible: true }

    Column {
        x: 10; y: 10
        width: deskViewport.contentWidth - 20
        height: deskViewport.height - 20
        spacing: 8

        RowLayout {
            id: heading
            width: parent.width
            spacing: 12
            GGText { colorKey: "ui.ResearchSurface.1";
                text: "RESEARCH"
                color: RuntimeTheme.GGTheme.text
                font.family: "monospace"
                font.pixelSize: 16
                font.bold: true
            }
            GGText { colorKey: "ui.ResearchSurface.2";
                text: "Sources · experiments · reusable methods"
                color: RuntimeTheme.GGTheme.positive
                font.family: "monospace"
                font.pixelSize: 11
                Layout.fillWidth: true
                elide: Text.ElideRight
            }
            GgButton { property string uiColorScope: "ui.control.ResearchSurface.1"; text: "REFRESH"; onClicked: root.refresh() }
        }

        Flow {
            id: sectionBar
            width: parent.width
            spacing: 0
            Repeater {
                model: root.tabs
                delegate: GgButton { property string uiColorScope: "ui.control.ResearchSurface.2";
                    required property string modelData
                    text: modelData
                    checked: root.page === modelData
                    width: Math.max(86, (parent ? parent.width : 500) / root.tabs.length)
                    objectName: "researchTab_" + modelData.replace(/ /g, "_")
                    onClicked: root.page = modelData
                }
            }
        }

        GGText { colorKey: "ui.ResearchSurface.3";
            id: summary
            width: parent.width
            text: root.notice + " · tasks " + root.tasks.length
                + " · evidence " + root.evidence.length
                + " · methods " + root.methods.length
                + " · skills " + root.skills.length
            color: RuntimeTheme.GGTheme.muted
            font.family: "monospace"
            font.pixelSize: 11
            elide: Text.ElideRight
        }

        StackLayout {
            id: pages
            width: parent.width
            height: Math.max(120, parent.height - heading.height - sectionBar.height - summary.height - 24)
            currentIndex: Math.max(0, root.tabs.indexOf(root.page))

            Item {
                Column {
                    anchors.fill: parent
                    spacing: 8
                    ResearchFrame { property string uiColorScope: "ui.widget.ResearchSurface.ResearchFrame.4";
                        width: parent.width
                        height: 116
                        leftLegend: "SCOUT / SHIP BACKLOG"
                        Column {
                            anchors.fill: parent
                            anchors.margins: 8
                            spacing: 6
                            Row {
                                width: parent.width
                                spacing: 6
                                GgField { property string uiColorScope: "ui.widget.ResearchSurface.GgField.5"; width: parent.width - 190; placeholderText: "Task title"; text: root.taskTitle; onTextChanged: root.taskTitle = text }
                                GgButton { property string uiColorScope: "ui.control.ResearchSurface.3"; objectName: "researchAddTask"; text: "ADD SCOUT"; onClicked: root.addTask("SCOUT") }
                                GgButton { property string uiColorScope: "ui.control.ResearchSurface.4"; text: "ADD SHIP"; onClicked: root.addTask("SHIP") }
                            }
                            GgField { property string uiColorScope: "ui.widget.ResearchSurface.GgField.8"; width: parent.width; placeholderText: "Context / acceptance notes"; text: root.taskBody; onTextChanged: root.taskBody = text }
                        }
                    }
                    ListView {
                        width: parent.width
                        height: Math.max(60, parent.height - 126)
                        clip: true
                        model: root.tasks
                        spacing: 5
                        ScrollBar.vertical: GgScrollBar { property string uiColorScope: "ui.widget.ResearchSurface.GgScrollBar.9";}
                        delegate: Rectangle {
                            required property var modelData
                            width: ListView.view.width
                            height: 52
                            color: RuntimeTheme.GGTheme.raised
                            border.color: RuntimeTheme.GGTheme.edge
                            border.width: 1
                            Column {
                                anchors.left: parent.left; anchors.right: promote.left
                                anchors.margins: 7; spacing: 2
                                GGText { colorKey: "ui.ResearchSurface.4"; textFormat: Text.PlainText; text: String(modelData.title || ""); color: RuntimeTheme.GGTheme.bright; font.family: "monospace"; font.pixelSize: 12; elide: Text.ElideRight; width: parent.width }
                                GGText { colorKey: "ui.ResearchSurface.5"; textFormat: Text.PlainText; text: String(modelData.mode || "SCOUT") + " · " + String(modelData.status || "BACKLOG") + " · " + String(modelData.body || ""); color: "#8f9aa4"; font.family: "monospace"; font.pixelSize: 10; elide: Text.ElideRight; width: parent.width }
                            }
                            GgButton { property string uiColorScope: "ui.control.ResearchSurface.5"; id: promote; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; anchors.rightMargin: 6; text: String(modelData.mode || "SCOUT") === "SHIP" ? "SHIP" : "→ SHIP"; enabled: String(modelData.mode || "") !== "SHIP"; onClicked: root.command("promote_task", {"task_id": String(modelData.id || ""), "mode": "SHIP"}) }
                        }
                    }
                }
            }

            Item {
                Column {
                    anchors.fill: parent; spacing: 8
                    ResearchFrame { property string uiColorScope: "ui.widget.ResearchSurface.ResearchFrame.11";
                        width: parent.width; height: 112; leftLegend: "EVIDENCE CARD"
                        Column { anchors.fill: parent; anchors.margins: 8; spacing: 5
                            Row {
                                width: parent.width
                                spacing: 6
                                GgField { property string uiColorScope: "ui.widget.ResearchSurface.GgField.12"; width: parent.width * 0.34; placeholderText: "Title"; text: root.evidenceTitle; onTextChanged: root.evidenceTitle = text }
                                GgField { property string uiColorScope: "ui.widget.ResearchSurface.GgField.13"; width: parent.width * 0.34; placeholderText: "Claim"; text: root.evidenceClaim; onTextChanged: root.evidenceClaim = text }
                                GgButton { property string uiColorScope: "ui.control.ResearchSurface.6"; objectName: "researchAddEvidence"; text: "RECORD"; onClicked: root.addEvidence() }
                            }
                            GgField { property string uiColorScope: "ui.widget.ResearchSurface.GgField.15"; width: parent.width; placeholderText: "Source URL / reference"; text: root.evidenceUrl; onTextChanged: root.evidenceUrl = text }
                        }
                    }
                    ListView { width: parent.width; height: Math.max(60, parent.height - 122); clip: true; model: root.evidence; spacing: 5; ScrollBar.vertical: GgScrollBar { property string uiColorScope: "ui.widget.ResearchSurface.GgScrollBar.16";}
                        delegate: Column { required property var modelData; width: ListView.view.width; spacing: 2
                            GGText { colorKey: "ui.ResearchSurface.6"; textFormat: Text.PlainText; text: String(modelData.title || "") + " · " + String(modelData.provenance || ""); color: RuntimeTheme.GGTheme.accent; font.family: "monospace"; font.pixelSize: 12; elide: Text.ElideRight; width: parent.width }
                            GGText { colorKey: "ui.ResearchSurface.7"; textFormat: Text.PlainText; text: String(modelData.claim || "") + (String(modelData.source_url || "").length ? " · " + String(modelData.source_url) : ""); color: RuntimeTheme.GGTheme.text; font.family: "monospace"; font.pixelSize: 11; wrapMode: Text.WordWrap; width: parent.width }
                            GGText { colorKey: "ui.ResearchSurface.8"; textFormat: Text.PlainText; text: root.evidenceContext(modelData); color: RuntimeTheme.GGTheme.dim; font.family: "monospace"; font.pixelSize: 10; wrapMode: Text.WordWrap; width: parent.width }
                            GgButton { property string uiColorScope: "ui.control.ResearchSurface.7"; visible: modelData.has_snapshot === true; text: "OPEN SAVED REPORT";
                                onClicked: root.openSavedFinding(String(modelData.id || "")) }
                        }
                    }
                }
            }

            Item {
                Row { anchors.fill: parent; spacing: 10
                    ResearchFrame { property string uiColorScope: "ui.widget.ResearchSurface.ResearchFrame.18"; width: parent.width * 0.47; height: parent.height; leftLegend: "SOURCE / MEMORY"
                        Column { anchors.fill: parent; anchors.margins: 8; spacing: 6
                            GgField { property string uiColorScope: "ui.widget.ResearchSurface.GgField.19"; width: parent.width; placeholderText: "Source title"; text: root.sourceTitle; onTextChanged: root.sourceTitle = text }
                            TextArea { width: parent.width; height: 150; placeholderText: "Paste a bounded note, transcript excerpt or observation"; text: root.sourceText; onTextChanged: root.sourceText = text; color: RuntimeTheme.GGTheme.bright; placeholderTextColor: RuntimeTheme.GGTheme.dim; font.family: "monospace"; font.pixelSize: 11; wrapMode: TextArea.Wrap; background: Rectangle { color: RuntimeTheme.GGTheme.canvas; border.color: RuntimeTheme.GGTheme.edge; border.width: 1 } }
                            GgButton { property string uiColorScope: "ui.control.ResearchSurface.8"; objectName: "researchAddSource"; text: "INGEST + REMEMBER"; onClicked: root.addSource() }
                            GGText { colorKey: "ui.ResearchSurface.9"; text: "Sources are clipped, hashed and optionally copied into long memory."; color: RuntimeTheme.GGTheme.dim; font.family: "monospace"; font.pixelSize: 10; wrapMode: Text.WordWrap; width: parent.width }
                            ListView {
                                objectName: "researchSources"
                                width: parent.width; height: Math.max(50, parent.height - 260)
                                clip: true; model: root.sources; spacing: 6
                                ScrollBar.vertical: GgScrollBar { property string uiColorScope: "ui.widget.ResearchSurface.GgScrollBar.21";}
                                delegate: Column {
                                    required property var modelData
                                    width: ListView.view.width; spacing: 3
                                    GGText { colorKey: "ui.ResearchSurface.10"; width: parent.width; text: String(modelData.title || "") + " · " + String(modelData.kind || "SOURCE"); textFormat: Text.PlainText; color: RuntimeTheme.GGTheme.positive; font.family: "monospace"; font.pixelSize: 11; elide: Text.ElideRight }
                                    GGText { colorKey: "ui.ResearchSurface.11"; width: parent.width; text: String(modelData.excerpt || ""); textFormat: Text.PlainText; color: RuntimeTheme.GGTheme.text; font.family: "monospace"; font.pixelSize: 10; wrapMode: Text.WordWrap; maximumLineCount: 4; elide: Text.ElideRight }
                                    GGText { colorKey: "ui.ResearchSurface.12"; width: parent.width; text: String(modelData.origin || "") + " · " + String(modelData.created_at || ""); textFormat: Text.PlainText; color: RuntimeTheme.GGTheme.dim; font.family: "monospace"; font.pixelSize: 10; elide: Text.ElideMiddle }
                                }
                            }
                        }
                    }
                    ResearchFrame { property string uiColorScope: "ui.widget.ResearchSurface.ResearchFrame.22"; width: parent.width * 0.53 - 10; height: parent.height; leftLegend: "PROCEDURAL METHODS"
                        Column { anchors.fill: parent; anchors.margins: 8; spacing: 6
                            GgField { property string uiColorScope: "ui.widget.ResearchSurface.GgField.23"; width: parent.width; placeholderText: "Method name"; text: root.methodName; onTextChanged: root.methodName = text }
                            GgField { property string uiColorScope: "ui.widget.ResearchSurface.GgField.24"; width: parent.width; placeholderText: "Trigger / when useful"; text: root.methodTrigger; onTextChanged: root.methodTrigger = text }
                            TextArea { width: parent.width; height: 100; placeholderText: "One bounded step per line"; text: root.methodSteps; onTextChanged: root.methodSteps = text; color: RuntimeTheme.GGTheme.bright; placeholderTextColor: RuntimeTheme.GGTheme.dim; font.family: "monospace"; font.pixelSize: 11; wrapMode: TextArea.Wrap; background: Rectangle { color: RuntimeTheme.GGTheme.canvas; border.color: RuntimeTheme.GGTheme.edge; border.width: 1 } }
                            GgButton { property string uiColorScope: "ui.control.ResearchSurface.9"; objectName: "researchAddMethod"; text: "SAVE METHOD"; onClicked: root.addMethod() }
                            ListView {
                                width: parent.width; height: Math.max(40, parent.height - 240)
                                clip: true; model: root.methods; spacing: 6
                                ScrollBar.vertical: GgScrollBar { property string uiColorScope: "ui.widget.ResearchSurface.GgScrollBar.26";}
                                delegate: Rectangle {
                                    required property var modelData
                                    width: ListView.view.width; height: 116
                                    color: RuntimeTheme.GGTheme.raised; border.color: modelData.status === "VERIFIED" ? RuntimeTheme.GGTheme.positive : RuntimeTheme.GGTheme.edge
                                    Column {
                                        anchors.left: parent.left; anchors.right: parent.right
                                        anchors.margins: 8; y: 7; spacing: 5
                                        GGText { colorKey: "ui.ResearchSurface.13"; textFormat: Text.PlainText; width: parent.width; text: String(modelData.name || "") + " · " + String(modelData.status || "PROPOSED")
                                            color: RuntimeTheme.GGTheme.text; font.family: "monospace"; font.pixelSize: 11; elide: Text.ElideRight }
                                        GGText { colorKey: "ui.ResearchSurface.14"; textFormat: Text.PlainText; width: parent.width; height: 45
                                            text: { try { return JSON.parse(String(modelData.steps_json || "[]")).slice(0, 3).join("\n") } catch (e) { return "" } }
                                            color: RuntimeTheme.GGTheme.muted; font.family: "monospace"; font.pixelSize: 10
                                            wrapMode: Text.WordWrap; maximumLineCount: 3; elide: Text.ElideRight }
                                        Row {
                                            width: parent.width; spacing: 6
                                            GgButton { property string uiColorScope: "ui.control.ResearchSurface.10"; text: "TEST STATUS"; onClicked: root.command("lab_verify", {"method_id": String(modelData.id || "")}) }
                                            GGText { colorKey: "ui.ResearchSurface.15"; textFormat: Text.PlainText; width: parent.width - 115; anchors.verticalCenter: parent.verticalCenter
                                                text: String(modelData.proof || "Independent test pending")
                                                color: RuntimeTheme.GGTheme.dim; font.family: "monospace"; font.pixelSize: 10; elide: Text.ElideRight }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Item {
                Column { anchors.fill: parent; spacing: 8
                    ResearchFrame { property string uiColorScope: "ui.widget.ResearchSurface.ResearchFrame.28"; width: parent.width; height: 174; leftLegend: "WEB SKILL FACTORY · REPLAY SHAPE ONLY"
                        Column { anchors.fill: parent; anchors.margins: 8; spacing: 5
                            Row {
                                width: parent.width
                                spacing: 6
                                GgField { property string uiColorScope: "ui.widget.ResearchSurface.GgField.29"; width: parent.width - 150; placeholderText: "Skill name"; text: root.skillName; onTextChanged: root.skillName = text }
                                GgButton { property string uiColorScope: "ui.control.ResearchSurface.11"; objectName: "researchAddSkill"; text: "SAVE DRAFT"; onClicked: root.addSkill() }
                            }
                            GgField { property string uiColorScope: "ui.widget.ResearchSurface.GgField.31"; width: parent.width; placeholderText: "Template / parameters / evidence expectation"; text: root.skillTemplate; onTextChanged: root.skillTemplate = text }
                            TextArea { width: parent.width; height: 58; placeholderText: "Playwright-style script text; stored and checked, never executed by this surface"; text: root.skillScript; onTextChanged: root.skillScript = text; color: RuntimeTheme.GGTheme.bright; placeholderTextColor: RuntimeTheme.GGTheme.dim; font.family: "monospace"; font.pixelSize: 10; background: Rectangle { color: RuntimeTheme.GGTheme.canvas; border.color: RuntimeTheme.GGTheme.edge; border.width: 1 } }
                        }
                    }
                    ListView { width: parent.width; height: Math.max(60, parent.height - 184); clip: true; model: root.skills; spacing: 5; ScrollBar.vertical: GgScrollBar { property string uiColorScope: "ui.widget.ResearchSurface.GgScrollBar.32";}
                        delegate: Rectangle { required property var modelData; width: ListView.view.width; height: 48; color: RuntimeTheme.GGTheme.raised; border.color: RuntimeTheme.GGTheme.edge; border.width: 1
                            GGText { colorKey: "ui.ResearchSurface.16"; textFormat: Text.PlainText; anchors.left: parent.left; anchors.right: verify.left; anchors.margins: 7; anchors.verticalCenter: parent.verticalCenter; text: String(modelData.name || "") + " · " + String(modelData.status || "DRAFT") + " · NOT_EXECUTED"; color: RuntimeTheme.GGTheme.text; font.family: "monospace"; font.pixelSize: 11; elide: Text.ElideRight }
                            GgButton { property string uiColorScope: "ui.control.ResearchSurface.12"; id: verify; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; anchors.rightMargin: 6; text: "CHECK SHAPE"; onClicked: root.command("verify_web_skill", {"skill_id": String(modelData.id || "")}) }
                        }
                    }
                }
            }

            Item {
                Row { anchors.fill: parent; spacing: 8
                    ResearchFrame { property string uiColorScope: "ui.widget.ResearchSurface.ResearchFrame.34"; width: parent.width * 0.55; height: parent.height; leftLegend: "SQL LOGICAL PREVIEW · NO DATABASE"
                        Column { anchors.fill: parent; anchors.margins: 8; spacing: 6
                            TextArea { width: parent.width; height: 180; text: root.sqlText; onTextChanged: root.sqlText = text; color: RuntimeTheme.GGTheme.bright; font.family: "monospace"; font.pixelSize: 12; wrapMode: TextArea.Wrap; background: Rectangle { color: RuntimeTheme.GGTheme.canvas; border.color: RuntimeTheme.GGTheme.edge; border.width: 1 } }
                            GgButton { property string uiColorScope: "ui.control.ResearchSurface.13"; objectName: "researchSqlPreview"; text: "PREVIEW ONLY"; onClicked: root.command("sql_preview", {"sql": root.sqlText}) }
                            GGText { colorKey: "ui.ResearchSurface.17"; width: parent.width; text: root.sqlPreview.summary ? String(root.sqlPreview.summary) + " · risk " + String(root.sqlPreview.risk || "LOW") + " · executed=" + String(root.sqlPreview.executed) : "Nothing executed. Preview exposes statement, tables, CTEs and warnings."; color: RuntimeTheme.GGTheme.text; font.family: "monospace"; font.pixelSize: 10; wrapMode: Text.WordWrap }
                        }
                    }
                    ResearchFrame { property string uiColorScope: "ui.widget.ResearchSurface.ResearchFrame.36"; width: parent.width * 0.45 - 8; height: parent.height; leftLegend: "PREVIEW GRAPH"
                        ListView { anchors.fill: parent; anchors.margins: 8; clip: true; model: root.sqlPreview.nodes || []; delegate: GGText { colorKey: "ui.ResearchSurface.18"; required property var modelData; textFormat: Text.PlainText; width: ListView.view.width; text: String(modelData.kind || "") + " · " + String(modelData.label || ""); color: RuntimeTheme.GGTheme.accent; font.family: "monospace"; font.pixelSize: 11; elide: Text.ElideRight } }
                    }
                }
            }

            Item {
                Column { anchors.fill: parent; spacing: 8
                    ResearchFrame { property string uiColorScope: "ui.widget.ResearchSurface.ResearchFrame.37"; width: parent.width; height: 158; leftLegend: "EVAL / OBSERVABILITY · RECORDED REVIEW"
                        Column { anchors.fill: parent; anchors.margins: 8; spacing: 6
                            RowLayout { width: parent.width; spacing: 6
                                GgField { property string uiColorScope: "ui.widget.ResearchSurface.GgField.38"; Layout.fillWidth: true; placeholderText: "Evaluation name"; text: root.evalName; onTextChanged: root.evalName = text }
                                GgButton { property string uiColorScope: "ui.control.ResearchSurface.14"; objectName: "researchEvalStart"; text: "START RUN"; enabled: !root.activeRunId; onClicked: root.startEvaluation() }
                                GgButton { property string uiColorScope: "ui.control.ResearchSurface.15"; text: "REFRESH"; onClicked: root.refresh() }
                            }
                            RowLayout { width: parent.width; spacing: 6
                                GgField { property string uiColorScope: "ui.widget.ResearchSurface.GgField.41"; Layout.preferredWidth: 130; placeholderText: "Stage"; text: root.eventStage; onTextChanged: root.eventStage = text }
                                GgField { property string uiColorScope: "ui.widget.ResearchSurface.GgField.42"; Layout.fillWidth: true; placeholderText: "Observed result / review note"; text: root.eventNote; onTextChanged: root.eventNote = text }
                                GgButton { property string uiColorScope: "ui.control.ResearchSurface.16"; objectName: "researchEvalEvent"; text: "RECORD"; enabled: root.activeRunId.length > 0; onClicked: root.recordEvaluationEvent() }
                            }
                            RowLayout { width: parent.width; spacing: 6
                                GgField { property string uiColorScope: "ui.widget.ResearchSurface.GgField.44"; Layout.fillWidth: true; placeholderText: "Optional score: 0–1"; text: root.evalScore; onTextChanged: root.evalScore = text }
                                GgButton { property string uiColorScope: "ui.control.ResearchSurface.17"; objectName: "researchEvalPass"; text: "PASS"; enabled: root.activeRunId.length > 0; onClicked: root.finishEvaluation("PASS") }
                                GgButton { property string uiColorScope: "ui.control.ResearchSurface.18"; objectName: "researchEvalFail"; text: "FAIL"; enabled: root.activeRunId.length > 0; onClicked: root.finishEvaluation("FAIL") }
                                GgButton { property string uiColorScope: "ui.control.ResearchSurface.19"; objectName: "researchEvalCancel"; text: "CANCEL"; enabled: root.activeRunId.length > 0; onClicked: root.finishEvaluation("CANCELLED") }
                            }
                            GGText { colorKey: "ui.ResearchSurface.19"; width: parent.width; text: "Record your own checks here. Starting a run creates a trace; it does not execute a test suite."; color: RuntimeTheme.GGTheme.dim; font.family: "monospace"; font.pixelSize: 10; wrapMode: Text.WordWrap }
                        }
                    }
                    GGText { colorKey: "ui.ResearchSurface.20"; text: "events=" + String((root.status.observability || {}).events || 0) + " · runs=" + String((root.status.observability || {}).runs || 0) + " · bounded local traces"; color: RuntimeTheme.GGTheme.positive; font.family: "monospace"; font.pixelSize: 12 }
                    ListView { width: parent.width; height: Math.max(60, parent.height - 198); clip: true; model: root.runs; spacing: 5; ScrollBar.vertical: GgScrollBar { property string uiColorScope: "ui.widget.ResearchSurface.GgScrollBar.48";}
                        delegate: RowLayout { required property var modelData; width: ListView.view.width
                            GGText { colorKey: "ui.ResearchSurface.21"; Layout.fillWidth: true; text: String(modelData.eval_name || "WORKBENCH") + " · " + String(modelData.status || "RUNNING") + " · score " + String(modelData.score === null ? "—" : modelData.score); textFormat: Text.PlainText; color: RuntimeTheme.GGTheme.text; font.family: "monospace"; font.pixelSize: 11; elide: Text.ElideRight }
                            GgButton { property string uiColorScope: "ui.control.ResearchSurface.20"; text: root.activeRunId === String(modelData.id) ? "SELECTED" : "SELECT"; visible: modelData.status === "RUNNING"; onClicked: root.activeRunId = String(modelData.id) }
                        }
                    }
                }
            }

            QipSurface { property string uiColorScope: "ui.widget.ResearchSurface.QipSurface.50"; surfaceHost: root.surfaceHost }

            ResearchReverseSurface { property string uiColorScope: "ui.widget.ResearchSurface.ResearchReverseSurface.51";
                id: reversePane
                surfaceHost: root.surfaceHost
                onFindingSaved: { root.refresh(); root.page = "EVIDENCE" }
                onDocumentationRequested: function(url) { root.documentationRequested(url) }
            }
            ResearchGamesSurface { property string uiColorScope: "ui.widget.ResearchSurface.ResearchGamesSurface.52";
                surfaceHost: root.surfaceHost
                onAnalysisRequested: function(path) {
                    root.page = "REVERSE"
                    if (path.length > 0) reversePane.inspectArtifact(path)
                }
            }
            ResearchWorkbenchSurface { property string uiColorScope: "ui.widget.ResearchSurface.ResearchWorkbenchSurface.53"; surfaceHost: root.surfaceHost }
        }
    }
    }
}
