import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    objectName: "workspaceResearchPane"
    signal documentationRequested(string url)

    property var surfaceHost: null
    property color frameBorder: "#4a4a4a"
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
    property string notice: "LOCAL · READY"
    property var sqlPreview: ({})
    readonly property var tabs: ["BACKLOG", "EVIDENCE", "MEMORY", "WEB SKILLS", "SQL", "EVALS", "WASM LAB", "REVERSE", "GAMES"]

    readonly property var status: {
        try { return JSON.parse(root.statusJson || "{}") } catch (err) { return {} }
    }
    readonly property var tasks: root.status.tasks || []
    readonly property var evidence: root.status.evidence || []
    readonly property var sources: root.status.sources || []
    readonly property var methods: root.status.methods || []
    readonly property var skills: root.status.skills || []
    readonly property var runs: root.status.runs || []

    function applyRaw(raw) {
        if (raw === undefined || raw === null)
            return
        root.statusJson = String(raw)
        try {
            var parsed = JSON.parse(root.statusJson)
            if (parsed.status)
                root.notice = String(parsed.status)
        } catch (err) { }
    }

    function refresh() {
        if (root.surfaceHost && root.surfaceHost.researchCommand)
            root.applyRaw(root.surfaceHost.researchCommand(JSON.stringify({"op": "snapshot", "payload": {}})))
    }

    function command(op, payload) {
        if (!root.surfaceHost || !root.surfaceHost.researchCommand)
            return
        var raw = root.surfaceHost.researchCommand(JSON.stringify({
            "op": String(op || ""),
            "payload": payload || {}
        }))
        if (String(op || "") === "sql_preview") {
            root.sqlResult = String(raw || "{}")
            try { root.sqlPreview = JSON.parse(root.sqlResult) } catch (err) { root.sqlPreview = {} }
            root.notice = String(root.sqlPreview.summary || root.sqlPreview.status || "PREVIEW")
            return
        }
        if (String(op || "") === "lab_verify") {
            try { var check = JSON.parse(String(raw || "{}")); root.notice = String(check.detail || check.status || "") } catch (err) { }
            return
        }
        try {
            var result = JSON.parse(String(raw || "{}"))
            root.notice = String(result.status || "DONE")
        } catch (err) { }
        root.refresh()
    }

    function addTask(mode) {
        root.command("add_task", {"title": root.taskTitle, "body": root.taskBody, "mode": mode})
        root.taskTitle = ""
        root.taskBody = ""
    }

    function addEvidence() {
        root.command("add_evidence", {"kind": "RESEARCH", "title": root.evidenceTitle,
            "claim": root.evidenceClaim, "source_url": root.evidenceUrl,
            "provenance": "USER_REVIEW", "confidence": 0.5})
        root.evidenceTitle = ""
        root.evidenceClaim = ""
        root.evidenceUrl = ""
    }

    function addSource() {
        root.command("ingest_source", {"title": root.sourceTitle, "content": root.sourceText,
            "kind": "RESEARCH_NOTE", "origin": "LOCAL_UI", "remember": true})
        root.sourceTitle = ""
        root.sourceText = ""
    }

    function addMethod() {
        var steps = root.methodSteps.split("\n").filter(function(item) { return String(item).trim().length > 0 })
        root.command("add_method", {"name": root.methodName, "trigger": root.methodTrigger,
            "steps": steps, "proof": "Recorded in Research Desk"})
        root.methodName = ""
        root.methodTrigger = ""
        root.methodSteps = ""
    }

    function addSkill() {
        root.command("add_web_skill", {"name": root.skillName, "template": root.skillTemplate,
            "script": root.skillScript, "parameters": []})
        root.skillName = ""
        root.skillTemplate = ""
        root.skillScript = ""
    }

    function evidenceContext(card) {
        var details = {}
        try { details = JSON.parse(String(card.details_json || "{}")) } catch (err) { }
        if (!details.collection)
            return "Recorded: " + String(card.observed_at || "unknown")
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
        return "Collected: " + String(details.collected_at || "unknown")
            + " · Event time: " + String(details.event_time || "unknown")
            + " · " + String(details.freshness || "unknown")
            + " · " + location
            + (measurements.length ? " · " + measurements.join(" · ") : "")
            + " · Awaiting independent corroboration"
    }

    Component.onCompleted: root.refresh()
    onSurfaceHostChanged: root.refresh()
    onVisibleChanged: { if (visible) root.refresh() }

    Rectangle { anchors.fill: parent; color: "#161616" }

    Column {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 8

        RowLayout {
            id: heading
            width: parent.width
            spacing: 12
            Text {
                text: "RESEARCH"
                color: "#d8dee9"
                font.family: "monospace"
                font.pixelSize: 16
                font.bold: true
            }
            Text {
                text: "Sources · experiments · reusable methods"
                color: "#8db89a"
                font.family: "monospace"
                font.pixelSize: 11
                Layout.fillWidth: true
                elide: Text.ElideRight
            }
            GgButton { text: "REFRESH"; onClicked: root.refresh() }
        }

        Flow {
            id: sectionBar
            width: parent.width
            spacing: 0
            Repeater {
                model: root.tabs
                delegate: GgButton {
                    required property string modelData
                    text: modelData
                    checked: root.page === modelData
                    width: Math.max(86, (parent ? parent.width : 500) / root.tabs.length)
                    onClicked: root.page = modelData
                }
            }
        }

        Text {
            id: summary
            width: parent.width
            text: root.notice + " · tasks " + root.tasks.length
                + " · evidence " + root.evidence.length
                + " · methods " + root.methods.length
                + " · skills " + root.skills.length
            color: "#a8b0b8"
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
                    ResearchFrame {
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
                                GgField { width: parent.width - 190; placeholderText: "Task title"; text: root.taskTitle; onTextChanged: root.taskTitle = text }
                                GgButton { text: "ADD SCOUT"; onClicked: root.addTask("SCOUT") }
                                GgButton { text: "ADD SHIP"; onClicked: root.addTask("SHIP") }
                            }
                            GgField { width: parent.width; placeholderText: "Context / acceptance notes"; text: root.taskBody; onTextChanged: root.taskBody = text }
                        }
                    }
                    ListView {
                        width: parent.width
                        height: Math.max(60, parent.height - 126)
                        clip: true
                        model: root.tasks
                        spacing: 5
                        ScrollBar.vertical: GgScrollBar {}
                        delegate: Rectangle {
                            required property var modelData
                            width: ListView.view.width
                            height: 52
                            color: "#1d1d1d"
                            border.color: "#42484e"
                            border.width: 1
                            Column {
                                anchors.left: parent.left; anchors.right: promote.left
                                anchors.margins: 7; spacing: 2
                                Text { text: String(modelData.title || ""); color: "#e6edf3"; font.family: "monospace"; font.pixelSize: 12; elide: Text.ElideRight; width: parent.width }
                                Text { text: String(modelData.mode || "SCOUT") + " · " + String(modelData.status || "BACKLOG") + " · " + String(modelData.body || ""); color: "#8f9aa4"; font.family: "monospace"; font.pixelSize: 10; elide: Text.ElideRight; width: parent.width }
                            }
                            GgButton { id: promote; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; anchors.rightMargin: 6; text: String(modelData.mode || "SCOUT") === "SHIP" ? "SHIP" : "→ SHIP"; enabled: String(modelData.mode || "") !== "SHIP"; onClicked: root.command("promote_task", {"task_id": String(modelData.id || ""), "mode": "SHIP"}) }
                        }
                    }
                }
            }

            Item {
                Column {
                    anchors.fill: parent; spacing: 8
                    ResearchFrame {
                        width: parent.width; height: 112; leftLegend: "EVIDENCE CARD"
                        Column { anchors.fill: parent; anchors.margins: 8; spacing: 5
                            Row {
                                width: parent.width
                                spacing: 6
                                GgField { width: parent.width * 0.34; placeholderText: "Title"; text: root.evidenceTitle; onTextChanged: root.evidenceTitle = text }
                                GgField { width: parent.width * 0.34; placeholderText: "Claim"; text: root.evidenceClaim; onTextChanged: root.evidenceClaim = text }
                                GgButton { text: "RECORD"; onClicked: root.addEvidence() }
                            }
                            GgField { width: parent.width; placeholderText: "Source URL / reference"; text: root.evidenceUrl; onTextChanged: root.evidenceUrl = text }
                        }
                    }
                    ListView { width: parent.width; height: Math.max(60, parent.height - 122); clip: true; model: root.evidence; spacing: 5; ScrollBar.vertical: GgScrollBar {}
                        delegate: Column { required property var modelData; width: ListView.view.width; spacing: 2
                            Text { textFormat: Text.PlainText; text: String(modelData.title || "") + " · " + String(modelData.provenance || ""); color: "#c8a97e"; font.family: "monospace"; font.pixelSize: 12; elide: Text.ElideRight; width: parent.width }
                            Text { textFormat: Text.PlainText; text: String(modelData.claim || "") + (String(modelData.source_url || "").length ? " · " + String(modelData.source_url) : ""); color: "#c8cdd4"; font.family: "monospace"; font.pixelSize: 11; wrapMode: Text.WordWrap; width: parent.width }
                            Text { textFormat: Text.PlainText; text: root.evidenceContext(modelData); color: "#7f8993"; font.family: "monospace"; font.pixelSize: 10; wrapMode: Text.WordWrap; width: parent.width }
                        }
                    }
                }
            }

            Item {
                Row { anchors.fill: parent; spacing: 10
                    ResearchFrame { width: parent.width * 0.47; height: parent.height; leftLegend: "SOURCE / MEMORY"
                        Column { anchors.fill: parent; anchors.margins: 8; spacing: 6
                            GgField { width: parent.width; placeholderText: "Source title"; text: root.sourceTitle; onTextChanged: root.sourceTitle = text }
                            TextArea { width: parent.width; height: 150; placeholderText: "Paste a bounded note, transcript excerpt or observation"; text: root.sourceText; onTextChanged: root.sourceText = text; color: "#e6e6e6"; placeholderTextColor: "#5d6670"; font.family: "monospace"; font.pixelSize: 11; wrapMode: TextArea.Wrap; background: Rectangle { color: "#121212"; border.color: "#6a6a6a"; border.width: 1 } }
                            GgButton { text: "INGEST + REMEMBER"; onClicked: root.addSource() }
                            Text { text: "Sources are clipped, hashed and optionally copied into long memory."; color: "#7f8993"; font.family: "monospace"; font.pixelSize: 10; wrapMode: Text.WordWrap; width: parent.width }
                        }
                    }
                    ResearchFrame { width: parent.width * 0.53 - 10; height: parent.height; leftLegend: "PROCEDURAL METHODS"
                        Column { anchors.fill: parent; anchors.margins: 8; spacing: 6
                            GgField { width: parent.width; placeholderText: "Method name"; text: root.methodName; onTextChanged: root.methodName = text }
                            GgField { width: parent.width; placeholderText: "Trigger / when useful"; text: root.methodTrigger; onTextChanged: root.methodTrigger = text }
                            TextArea { width: parent.width; height: 100; placeholderText: "One bounded step per line"; text: root.methodSteps; onTextChanged: root.methodSteps = text; color: "#e6e6e6"; placeholderTextColor: "#5d6670"; font.family: "monospace"; font.pixelSize: 11; wrapMode: TextArea.Wrap; background: Rectangle { color: "#121212"; border.color: "#6a6a6a"; border.width: 1 } }
                            GgButton { text: "SAVE METHOD"; onClicked: root.addMethod() }
                            ListView {
                                width: parent.width; height: Math.max(40, parent.height - 240)
                                clip: true; model: root.methods; spacing: 6
                                ScrollBar.vertical: GgScrollBar {}
                                delegate: Rectangle {
                                    required property var modelData
                                    width: ListView.view.width; height: 116
                                    color: "#1d1d1d"; border.color: modelData.status === "VERIFIED" ? "#8db89a" : "#42484e"
                                    Column {
                                        anchors.left: parent.left; anchors.right: parent.right
                                        anchors.margins: 8; y: 7; spacing: 5
                                        Text { width: parent.width; text: String(modelData.name || "") + " · " + String(modelData.status || "PROPOSED")
                                            color: "#d8dee9"; font.family: "monospace"; font.pixelSize: 11; elide: Text.ElideRight }
                                        Text { width: parent.width; height: 45
                                            text: { try { return JSON.parse(String(modelData.steps_json || "[]")).slice(0, 3).join("\n") } catch (e) { return "" } }
                                            color: "#a8b0b8"; font.family: "monospace"; font.pixelSize: 10
                                            wrapMode: Text.WordWrap; maximumLineCount: 3; elide: Text.ElideRight }
                                        Row {
                                            width: parent.width; spacing: 6
                                            GgButton { text: "TEST STATUS"; onClicked: root.command("lab_verify", {"method_id": String(modelData.id || "")}) }
                                            Text { width: parent.width - 115; anchors.verticalCenter: parent.verticalCenter
                                                text: String(modelData.proof || "Independent test pending")
                                                color: "#7f8993"; font.family: "monospace"; font.pixelSize: 10; elide: Text.ElideRight }
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
                    ResearchFrame { width: parent.width; height: 174; leftLegend: "WEB SKILL FACTORY · REPLAY SHAPE ONLY"
                        Column { anchors.fill: parent; anchors.margins: 8; spacing: 5
                            Row {
                                width: parent.width
                                spacing: 6
                                GgField { width: parent.width - 150; placeholderText: "Skill name"; text: root.skillName; onTextChanged: root.skillName = text }
                                GgButton { text: "SAVE DRAFT"; onClicked: root.addSkill() }
                            }
                            GgField { width: parent.width; placeholderText: "Template / parameters / evidence expectation"; text: root.skillTemplate; onTextChanged: root.skillTemplate = text }
                            TextArea { width: parent.width; height: 58; placeholderText: "Playwright-style script text; stored and checked, never executed by this surface"; text: root.skillScript; onTextChanged: root.skillScript = text; color: "#e6e6e6"; placeholderTextColor: "#5d6670"; font.family: "monospace"; font.pixelSize: 10; background: Rectangle { color: "#121212"; border.color: "#6a6a6a"; border.width: 1 } }
                        }
                    }
                    ListView { width: parent.width; height: Math.max(60, parent.height - 184); clip: true; model: root.skills; spacing: 5; ScrollBar.vertical: GgScrollBar {}
                        delegate: Rectangle { required property var modelData; width: ListView.view.width; height: 48; color: "#1d1d1d"; border.color: String(modelData.status || "") === "VERIFIED" ? "#8db89a" : "#42484e"; border.width: 1
                            Text { anchors.left: parent.left; anchors.right: verify.left; anchors.margins: 7; anchors.verticalCenter: parent.verticalCenter; text: String(modelData.name || "") + " · " + String(modelData.status || "DRAFT") + " · NOT_EXECUTED"; color: "#c8cdd4"; font.family: "monospace"; font.pixelSize: 11; elide: Text.ElideRight }
                            GgButton { id: verify; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; anchors.rightMargin: 6; text: "VERIFY"; onClicked: root.command("verify_web_skill", {"skill_id": String(modelData.id || "")}) }
                        }
                    }
                }
            }

            Item {
                Row { anchors.fill: parent; spacing: 8
                    ResearchFrame { width: parent.width * 0.55; height: parent.height; leftLegend: "SQL LOGICAL PREVIEW · NO DATABASE"
                        Column { anchors.fill: parent; anchors.margins: 8; spacing: 6
                            TextArea { width: parent.width; height: 180; text: root.sqlText; onTextChanged: root.sqlText = text; color: "#e6e6e6"; font.family: "monospace"; font.pixelSize: 12; wrapMode: TextArea.Wrap; background: Rectangle { color: "#121212"; border.color: "#6a6a6a"; border.width: 1 } }
                            GgButton { text: "PREVIEW ONLY"; onClicked: root.command("sql_preview", {"sql": root.sqlText}) }
                            Text { width: parent.width; text: root.sqlPreview.summary ? String(root.sqlPreview.summary) + " · risk " + String(root.sqlPreview.risk || "LOW") + " · executed=" + String(root.sqlPreview.executed) : "Nothing executed. Preview exposes statement, tables, CTEs and warnings."; color: "#c8cdd4"; font.family: "monospace"; font.pixelSize: 10; wrapMode: Text.WordWrap }
                        }
                    }
                    ResearchFrame { width: parent.width * 0.45 - 8; height: parent.height; leftLegend: "PREVIEW GRAPH"
                        ListView { anchors.fill: parent; anchors.margins: 8; clip: true; model: root.sqlPreview.nodes || []; delegate: Text { required property var modelData; width: ListView.view.width; text: String(modelData.kind || "") + " · " + String(modelData.label || ""); color: "#c8a97e"; font.family: "monospace"; font.pixelSize: 11; elide: Text.ElideRight } }
                    }
                }
            }

            Item {
                Column { anchors.fill: parent; spacing: 8
                    ResearchFrame { width: parent.width; height: 80; leftLegend: "EVAL / OBSERVABILITY"
                        Row { anchors.fill: parent; anchors.margins: 8; spacing: 6
                            GgField { width: parent.width - 260; placeholderText: "Evaluation name"; text: root.evalName; onTextChanged: root.evalName = text }
                            GgButton { text: "START RUN"; onClicked: root.command("start_run", {"task_id": "", "eval_name": root.evalName}) }
                            GgButton { text: "REFRESH"; onClicked: root.refresh() }
                        }
                    }
                    Text { text: "events=" + String((root.status.observability || {}).events || 0) + " · runs=" + String((root.status.observability || {}).runs || 0) + " · bounded local traces"; color: "#8db89a"; font.family: "monospace"; font.pixelSize: 12 }
                    ListView { width: parent.width; height: Math.max(60, parent.height - 120); clip: true; model: root.runs; spacing: 5; ScrollBar.vertical: GgScrollBar {}
                        delegate: Text { required property var modelData; width: ListView.view.width; text: String(modelData.eval_name || "WORKBENCH") + " · " + String(modelData.status || "RUNNING") + " · score " + String(modelData.score === null ? "—" : modelData.score); color: "#c8cdd4"; font.family: "monospace"; font.pixelSize: 11; elide: Text.ElideRight }
                    }
                }
            }

            QipSurface { surfaceHost: root.surfaceHost }

            ResearchReverseSurface {
                id: reversePane
                surfaceHost: root.surfaceHost
                onFindingSaved: { root.refresh(); root.page = "EVIDENCE" }
                onDocumentationRequested: function(url) { root.documentationRequested(url) }
            }
            ResearchGamesSurface {
                surfaceHost: root.surfaceHost
                onAnalysisRequested: function(path) {
                    root.page = "REVERSE"
                    if (path.length > 0) reversePane.inspectArtifact(path)
                }
            }
        }
    }
}
