import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs

Item {
    id: root
    objectName: "workspaceReversePane"
    property var surfaceHost: null
    property string reportJson: "{}"
    property string toolsJson: "{}"
    property string reportProducer: "Ghidra"
    property string targetPath: ""
    property string jobId: ""
    property string jobState: ""
    property string savedMethodId: ""
    property bool showRawReport: false
    property bool showLimits: false
    readonly property bool busy: jobState === "QUEUED" || jobState === "RUNNING" || jobState === "CANCELLING"
    property string notice: "Select a local artifact or import an analysis report."
    signal findingSaved()
    signal documentationRequested(string url)
    readonly property var report: { try { return JSON.parse(root.reportJson) } catch (e) { return {} } }
    readonly property var tools: { try { return JSON.parse(root.toolsJson) } catch (e) { return {} } }
    readonly property bool selected: String(root.report.report_id || "").length > 0
    readonly property var analysisResult: root.report.content ? root.report.content.normalized_result : null
    readonly property string pseudocode: typeof root.analysisResult === "string" ? root.analysisResult
        : String((root.analysisResult || {}).pseudocode || "")
    readonly property var graphEdges: ((root.analysisResult || {}).graph || {}).edges || []
    readonly property string functionSummary: {
        var result = root.analysisResult || {}
        if (!result.procedure) return ""
        return String(result.procedure.signature || result.procedure.name || "") + "\n"
            + String(result.procedure.address || "") + " · callers: "
            + (result.callers || []).map(function(item) { return String(item.name || item.address || "") }).join(", ")
    }

    function request(op, payload) {
        if (!root.surfaceHost || !root.surfaceHost.researchCommand)
            return "{}"
        return String(root.surfaceHost.researchCommand(JSON.stringify({op: op, payload: payload || {}})))
    }
    function refresh() { root.toolsJson = root.request("lab_tools", {}) }
    function startAnalysis() {
        var result = {}
        try { result = JSON.parse(root.request("lab_start", {path: root.targetPath,
            operation: operationPicker.currentText, query: queryField.text})) } catch (e) { }
        root.jobState = String(result.status || "ERROR")
        root.notice = String(result.reason || result.phase || result.status || "")
        if (result.engine_error) root.notice += " · " + String(result.engine_error.code || result.engine_error.message || "")
        if (result.job_id) root.jobId = String(result.job_id)
    }
    function pollJob() {
        var result = {}
        try { result = JSON.parse(root.request("lab_status", {job_id: root.jobId})) } catch (e) { }
        root.jobState = String(result.status || "ERROR")
        root.notice = String(result.reason || result.phase || result.status || "")
        if (result.engine_error) root.notice += " · " + String(result.engine_error.code || result.engine_error.message || "")
        if (result.report) {
            root.reportJson = JSON.stringify(result.report)
            root.notice = String(result.report.summary || "Report ready")
        }
    }
    function restoreLastReport() {
        var result = {}
        try { result = JSON.parse(root.request("lab_history", {})) } catch (e) { }
        var jobs = result.jobs || []
        for (var i = 0; i < jobs.length; i++) {
            if (jobs[i].status === "COMPLETE" || jobs[i].status === "RUNNING" || jobs[i].status === "QUEUED") {
                root.jobId = String(jobs[i].job_id)
                root.targetPath = String(jobs[i].target || "")
                root.pollJob()
                return
            }
        }
        root.notice = "No retained analysis reports."
    }
    function inspectArtifact(path) {
        root.targetPath = String(path)
        root.reportJson = root.request("lab_inspect", {path: String(path)})
        root.notice = String(root.report.reason || root.report.summary || root.report.status || "")
    }
    function importReport(path, producer) {
        root.reportJson = root.request("lab_import", {path: String(path), engine: String(producer)})
        root.notice = String(root.report.reason || root.report.summary || root.report.status || "")
    }
    function saveFinding() {
        var raw = root.request("lab_save", {report_id: String(root.report.report_id || ""),
            title: findingTitle.text, claim: findingText.text, lesson: lessonText.text})
        var result = {}
        try { result = JSON.parse(raw) } catch (e) { }
        root.notice = String(result.reason || result.status || "")
        if (result.status === "FINDING_SAVED") {
            root.savedMethodId = String(result.method_id || "")
            root.findingSaved()
        }
    }
    Component.onCompleted: root.refresh()
    onSurfaceHostChanged: root.refresh()
    onVisibleChanged: { if (visible) root.refresh() }
    Timer { interval: 600; repeat: true; running: root.busy && root.visible; onTriggered: root.pollJob() }

    FileDialog {
        id: artifactDialog
        title: "SELECT LOCAL ARTIFACT"
        fileMode: FileDialog.OpenFile
        nameFilters: ["Programs and source (*.wasm *.so *.exe *.bin *.js *.mjs *.cjs *.py *.qml *.asar)", "All files (*)"]
        onAccepted: root.inspectArtifact(String(selectedFile))
    }
    FolderDialog {
        id: projectDialog
        title: "SELECT JAVASCRIPT PROJECT"
        onAccepted: { root.targetPath = String(selectedFolder); root.notice = "Project selected. Run analyze to inspect its source graph." }
    }
    FileDialog {
        id: reportDialog
        title: "IMPORT LOCAL ANALYSIS REPORT"
        fileMode: FileDialog.OpenFile
        nameFilters: ["JSON analysis (*.json)"]
        onAccepted: root.importReport(String(selectedFile), root.reportProducer)
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 8
        Flow {
            Layout.fillWidth: true
            spacing: 6
            GgButton { text: "OPEN FILE"; onClicked: artifactDialog.open() }
            GgButton { text: "OPEN PROJECT"; onClicked: projectDialog.open() }
            GgButton { text: "GHIDRA REPORT"; onClicked: { root.reportProducer = "Ghidra"; reportDialog.open() } }
            GgButton { text: "REA REPORT"; onClicked: { root.reportProducer = "REA"; reportDialog.open() } }
            GgButton { text: "REFRESH TOOLS"; onClicked: root.refresh() }
            GgButton { text: "LAST ANALYSIS"; onClicked: root.restoreLastReport() }
        }
        GgField { Layout.fillWidth: true; text: root.targetPath;
            placeholderText: "Selected local file or JavaScript project";
            onTextEdited: root.targetPath = text }
        RowLayout {
            Layout.fillWidth: true
            ComboBox { id: operationPicker; objectName: "reverseOperation";
                model: ["analyze", "search", "function", "decompile", "xrefs"];
                Layout.preferredWidth: 130; enabled: !root.busy }
            GgField { id: queryField; objectName: "reverseQuery"; Layout.fillWidth: true;
                enabled: !root.busy && operationPicker.currentText !== "analyze";
                placeholderText: "Function name, address or search text" }
            GgButton { text: "ANALYZE"; objectName: "reverseAnalyze";
                enabled: !root.busy && root.targetPath.length > 0;
                onClicked: root.startAnalysis() }
            GgButton { text: "CANCEL"; enabled: root.busy;
                onClicked: { root.request("lab_cancel", {job_id: root.jobId}); root.jobState = "CANCELLING"; root.notice = "Cancelling analysis…" } }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Repeater {
                model: root.tools.engines || []
                delegate: Rectangle {
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.preferredHeight: 82
                    color: "#1d1d1d"
                    border.color: "#42484e"
                    Column {
                        anchors.fill: parent; anchors.margins: 8; spacing: 5
                        Text { width: parent.width; text: modelData.name + " · " + modelData.state;
                            color: modelData.state === "READY" ? "#8db89a" : "#c8a97e";
                            font.family: "monospace"; font.pixelSize: 12; elide: Text.ElideRight }
                        Text { width: parent.width; text: modelData.detail; color: "#a8b0b8";
                            font.family: "monospace"; font.pixelSize: 10; wrapMode: Text.WordWrap }
                    }
                }
            }
        }
        Text { Layout.fillWidth: true; text: root.notice; textFormat: Text.PlainText;
            color: root.report.status === "ERROR" ? "#c98989" : "#a8b0b8";
            font.family: "monospace"; font.pixelSize: 11; wrapMode: Text.WordWrap }
        Text { Layout.fillWidth: true; text: "Local static analysis · files ≤32 MiB · projects ≤64 MiB · 5 min per job · temporary work is removed";
            color: "#7f8993"; font.family: "monospace"; font.pixelSize: 10; wrapMode: Text.WordWrap }
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 10
            ResearchFrame {
                Layout.fillWidth: true
                Layout.fillHeight: true
                leftLegend: "OBSERVATIONS / SOURCE LOCATIONS"
                ScrollView {
                    id: observations
                    anchors.fill: parent; anchors.margins: 10
                    clip: true
                    contentWidth: availableWidth
                    Column {
                        width: observations.availableWidth
                        spacing: 10
                        Text { width: parent.width; text: root.selected
                                ? String(root.report.name) + " · " + String(root.report.format) + " · " + String(root.report.bytes) + " bytes\n" + String(root.report.path)
                                : "Inspect a program, source file or WASM component. Strings show their byte offsets. Import Ghidra or REA JSON to bring deeper analysis into the same evidence workflow.";
                            color: "#d8dee9"; font.family: "monospace"; font.pixelSize: 12;
                            textFormat: Text.PlainText; wrapMode: Text.WrapAnywhere }
                        Text { width: parent.width; text: (root.report.facts || []).join("\n");
                            color: "#8db89a"; font.family: "monospace"; font.pixelSize: 12;
                            textFormat: Text.PlainText; wrapMode: Text.WordWrap }
                        Text { visible: root.selected; width: parent.width;
                            text: "Static observations · verify behavioral conclusions";
                            color: "#c8a97e"; font.family: "monospace"; font.pixelSize: 11; wrapMode: Text.WordWrap }
                        GgButton { visible: root.selected; text: root.showLimits ? "HIDE ANALYSIS COVERAGE" : "ANALYSIS COVERAGE";
                            onClicked: root.showLimits = !root.showLimits }
                        Text { visible: root.showLimits; width: parent.width; text: (root.report.limits || []).join("\n");
                            color: "#c8a97e"; font.family: "monospace"; font.pixelSize: 11;
                            textFormat: Text.PlainText; wrapMode: Text.WordWrap }
                        TextArea {
                            visible: root.functionSummary.length > 0
                            width: parent.width; text: root.functionSummary
                            readOnly: true; selectByMouse: true
                            color: "#8db89a"; font.family: "monospace"; font.pixelSize: 12
                            wrapMode: TextArea.Wrap; background: Rectangle { color: "#121212" }
                        }
                        TextArea {
                            visible: root.pseudocode.length > 0
                            width: parent.width; text: root.pseudocode
                            readOnly: true; selectByMouse: true
                            color: "#d8dee9"; font.family: "monospace"; font.pixelSize: 12
                            wrapMode: TextArea.Wrap; background: Rectangle { color: "#121212" }
                        }
                        Repeater {
                            model: root.graphEdges
                            delegate: Text {
                                required property var modelData
                                width: parent.width
                                text: String(modelData.relation || "") + " · "
                                    + String((modelData.properties || {}).imported_name || (modelData.properties || {}).exported_name || "")
                                    + " · " + String((modelData.properties || {}).specifier || (modelData.properties || {}).resolved_path
                                        || (modelData.properties || {}).logical_module_key || (modelData.properties || {}).declared_path || "")
                                color: "#a8b0b8"; font.family: "monospace"; font.pixelSize: 11
                                textFormat: Text.PlainText; wrapMode: Text.WordWrap
                            }
                        }
                        GgButton { visible: root.report.content !== undefined
                            text: root.showRawReport ? "HIDE REPORT DETAILS" : "SHOW REPORT DETAILS"
                            onClicked: root.showRawReport = !root.showRawReport }
                        TextArea {
                            visible: root.report.content !== undefined && (root.showRawReport || (!root.pseudocode && root.graphEdges.length === 0 && !root.functionSummary))
                            width: parent.width
                            text: JSON.stringify(root.report.content || {}, null, 2)
                            readOnly: true; selectByMouse: true
                            color: "#c8cdd4"; font.family: "monospace"; font.pixelSize: 11
                            wrapMode: TextArea.Wrap
                            background: Rectangle { color: "#121212" }
                        }
                        Repeater {
                            model: root.report.strings || []
                            delegate: Text {
                                required property var modelData
                                width: parent.width
                                text: "0x" + Number(modelData.offset).toString(16) + "  " + String(modelData.text)
                                color: "#c8cdd4"; font.family: "monospace"; font.pixelSize: 11
                                textFormat: Text.PlainText; wrapMode: Text.WrapAnywhere
                            }
                        }
                    }
                }
            }
            ResearchFrame {
                Layout.preferredWidth: Math.min(320, root.width * 0.38)
                Layout.fillHeight: true
                leftLegend: "FINDING / REUSABLE LESSON"
                ColumnLayout {
                    anchors.fill: parent; anchors.margins: 10; spacing: 8
                    GgField { id: findingTitle; objectName: "reverseFindingTitle";
                        Layout.fillWidth: true; placeholderText: "Finding title" }
                    TextArea { id: findingText; objectName: "reverseFindingText";
                        Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 70
                        placeholderText: "Your conclusion and the observations supporting it"
                        color: "#e6e6e6"; placeholderTextColor: "#5d6670"; font.family: "monospace"; font.pixelSize: 11
                        wrapMode: TextArea.Wrap; selectByMouse: true
                        background: Rectangle { color: "#121212"; border.color: "#6a6a6a" }
                    }
                    TextArea { id: lessonText; objectName: "reverseLessonText";
                        Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 70
                    placeholderText: "Optional reusable method: one step per line"
                        color: "#e6e6e6"; placeholderTextColor: "#5d6670"; font.family: "monospace"; font.pixelSize: 11
                        wrapMode: TextArea.Wrap; selectByMouse: true
                        background: Rectangle { color: "#121212"; border.color: "#6a6a6a" }
                    }
                    Text { Layout.fillWidth: true; text: "Findings retain their source. Lessons remain proposed until independently tested.";
                        color: "#7f8993"; font.family: "monospace"; font.pixelSize: 10; wrapMode: Text.WordWrap }
                    GgButton { text: "SAVE FINDING + LESSON"; Layout.fillWidth: true;
                        enabled: root.selected && findingTitle.text.trim().length > 0 && findingText.text.trim().length > 0
                        onClicked: root.saveFinding() }
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Repeater {
                model: root.tools.references || []
                delegate: GgButton { required property var modelData;
                    text: modelData.name + " DOCS"; onClicked: root.documentationRequested(modelData.url) }
            }
            Item { Layout.fillWidth: true }
            GgButton { text: "SAVE WORKFLOW REFERENCES";
                onClicked: { var raw = root.request("lab_references", {}); try { root.notice = JSON.parse(raw).status } catch (e) { } } }
        }
    }
}
