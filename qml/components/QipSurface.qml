pragma ComponentBehavior: Bound


import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs

Item {
    id: root
    objectName: "workspaceQipPane"

    property var surfaceHost: null
    property string modulePath: ""
    property string reportJson: "{}"
    property string jobId: ""
    property string jobState: ""
    property string notice: ""

    readonly property var report: {
        try {
            return JSON.parse(root.reportJson || "{}")
        } catch (err) {
            return {}
        }
    }
    readonly property var inspection: root.report.inspection || root.report
    readonly property bool loaded: String(root.inspection.name || "").length > 0
    readonly property bool ready: String(root.inspection.state || "") === "READY"
    readonly property bool running: jobState === "RUNNING" || jobState === "QUEUED" || jobState === "CANCELLING"

    function parseResponse(raw) {
        try {
            var result = JSON.parse(String(raw || "{}"))
            if (!result || typeof result !== "object" || (!result.state && !result.status))
                throw new Error("Missing state")
            return result
        } catch (error) {
            return {state: "ERROR", reason: "Invalid response from the WASM service. Your input is retained."}
        }
    }

    function applyResult(result) {
        root.jobState = String(result.state || result.status || "ERROR")
        root.notice = String(result.reason || result.error || result.detail || root.jobState)
        if (!result.inspection && root.loaded) result.inspection = root.inspection
        root.reportJson = JSON.stringify(result)
    }

    function inspectFile(raw) {
        var value = String(raw || "")
        if (root.running) return false
        if (!value.length || !root.surfaceHost || !root.surfaceHost.qipInspect) {
            root.notice = "WASM Lab is connecting. Your input is retained."
            return false
        }
        var result = root.parseResponse(root.surfaceHost.qipInspect(value))
        root.notice = String(result.reason || result.state || result.status || "")
        if (result.state === "ERROR" || result.error) {
            root.jobState = "ERROR"
            if (root.loaded) root.notice += " Previous module retained."
            return false
        }
        root.modulePath = value
        root.reportJson = JSON.stringify(result)
        root.jobId = ""
        root.jobState = ""
        return true
    }

    function runModule() {
        if (root.running) return false
        if (!root.modulePath.length || !root.surfaceHost || !root.ready) return false
        if (root.surfaceHost.qipStart && root.surfaceHost.qipStatus) {
            var result = root.parseResponse(root.surfaceHost.qipStart(root.modulePath, inputArea.text))
            root.jobId = String(result.job_id || "")
            root.jobState = String(result.state || result.status || "ERROR")
            root.notice = String(result.reason || result.detail || root.jobState)
            if (root.running && !root.jobId) {
                root.jobState = "ERROR"
                root.notice = "The WASM service did not return a job. Your input is retained."
                return false
            }
            if (!root.running) root.applyResult(result)
            return root.running
        }
        if (!root.surfaceHost.qipRun) { root.notice = "WASM runtime is connecting."; return false }
        root.applyResult(root.parseResponse(root.surfaceHost.qipRun(root.modulePath, inputArea.text)))
        return root.jobState === "DONE"
    }

    function pollModule() {
        if (!root.jobId || !root.surfaceHost || !root.surfaceHost.qipStatus) return
        var result = root.parseResponse(root.surfaceHost.qipStatus(root.jobId))
        var state = String(result.state || result.status || "ERROR")
        if (state === "RUNNING" || state === "QUEUED" || state === "CANCELLING") {
            root.jobState = state
            root.notice = String(result.reason || result.detail || state)
        } else root.applyResult(result)
    }

    function cancelModule() {
        if (!root.running || !root.jobId || !root.surfaceHost || !root.surfaceHost.qipCancel) return false
        var result = root.parseResponse(root.surfaceHost.qipCancel(root.jobId))
        var state = String(result.state || result.status || "ERROR")
        if (state === "CANCELLING" || state === "RUNNING" || state === "QUEUED") {
            root.jobState = "CANCELLING"
            root.notice = "Cancelling WASM render…"
        } else root.applyResult(result)
        return true
    }

    function clearModule() {
        if (root.running) return false
        root.modulePath = ""
        root.reportJson = "{}"
        root.jobId = ""
        root.jobState = ""
        root.notice = ""
        inputArea.text = ""
    }

    Timer { interval: 150; repeat: true; running: root.running; onTriggered: root.pollModule() }

    function exportText() {
        var rows = root.inspection.exports || []
        var out = []
        for (var i = 0; i < rows.length; i++) {
            var row = rows[i] || {}
            out.push(String(row.name || "") + ":" + String(row.kind || ""))
        }
        return out.length ? out.join("  ·  ") : "none"
    }

    function memoryText() {
        var rows = root.inspection.memories || []
        var out = []
        for (var i = 0; i < rows.length; i++) {
            var row = rows[i] || {}
            out.push(String(row.min || 0) + " pages"
                + (row.max !== null && row.max !== undefined
                    ? "–" + String(row.max) : "–∞"))
        }
        return out.length ? out.join("  ·  ") : "none"
    }

    function tableText() {
        var rows = root.inspection.tables || []
        var out = []
        for (var i = 0; i < rows.length; i++) {
            var row = rows[i] || {}
            out.push(String(row.min || 0) + " entries"
                + (row.max !== null && row.max !== undefined
                    ? "–" + String(row.max) : "–∞"))
        }
        return out.length ? out.join("  ·  ") : "none"
    }

    function stateColor(state) {
        var value = String(state || "")
        if (value === "READY" || value === "DONE")
            return RuntimeTheme.GGTheme.positive
        if (value === "BLOCKED" || value === "ERROR" || value === "TIMEOUT")
            return RuntimeTheme.GGTheme.negative
        return RuntimeTheme.GGTheme.accent
    }

    FileDialog {
        id: wasmDialog
        title: "OPEN LOCAL QIP / WASM COMPONENT"
        fileMode: FileDialog.OpenFile
        nameFilters: ["WebAssembly (*.wasm)", "All files (*)"]
        onAccepted: root.inspectFile(String(wasmDialog.selectedFile))
    }

    GgFrame { property string uiColorScope: "ui.widget.QipSurface.GgFrame.1";
        anchors.fill: parent
        leftLegend: "QIP / WASM LAB"
        rightLegend: "LOCAL · NO HOST IMPORTS"
        backgroundColor: RuntimeTheme.GGTheme.panel
        borderColor: RuntimeTheme.GGTheme.edge
    }

    Item {
        anchors.fill: parent
        anchors.leftMargin: 14
        anchors.rightMargin: 14
        anchors.topMargin: 26
        anchors.bottomMargin: 12

        Row {
            id: labActions
            width: parent.width
            height: 30
            spacing: 8

            GgButton { property string uiColorScope: "ui.control.QipSurface.1";
                text: "OPEN .WASM"
                enabled: !root.running
                onClicked: wasmDialog.open()
            }
            GgButton { property string uiColorScope: "ui.control.QipSurface.2";
                text: "RUN RENDER"
                objectName: "qipRunRender"
                enabled: root.ready && !root.running
                onClicked: root.runModule()
            }
            GgButton { property string uiColorScope: "ui.control.QipSurface.3";
                objectName: "qipCancelRender"
                text: "CANCEL"
                visible: !!root.surfaceHost && !!root.surfaceHost.qipCancel
                enabled: root.running && root.jobState !== "CANCELLING"
                onClicked: root.cancelModule()
            }
            GgButton { property string uiColorScope: "ui.control.QipSurface.4";
                text: "RESET"
                enabled: !root.running
                onClicked: root.clearModule()
            }
            GGText { colorKey: "ui.QipSurface.1";
                anchors.verticalCenter: parent.verticalCenter
                text: String(root.jobState || root.report.state || root.inspection.state || "IDLE")
                    .toUpperCase()
                color: root.stateColor(root.jobState || root.report.state || root.inspection.state)
                font.family: "monospace"
                font.pixelSize: 12
            }
        }

        Flickable {
            id: labScroll
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: labActions.bottom
            anchors.topMargin: 8
            anchors.bottom: parent.bottom
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            contentHeight: labColumn.height
            ScrollBar.vertical: GgScrollBar { property string uiColorScope: "ui.widget.QipSurface.GgScrollBar.6";}

            Column {
                id: labColumn
                width: labScroll.width
                height: childrenRect.height
                spacing: 8

                GGText { colorKey: "ui.QipSurface.2";
                    text: "QIP COMPONENT · LOCAL WASM"
                    color: RuntimeTheme.GGTheme.text
                    font.family: "monospace"
                    font.pixelSize: 16
                }
                GGText { colorKey: "ui.QipSurface.3";
                    width: labColumn.width
                    visible: root.notice.length > 0
                    text: root.notice
                    textFormat: Text.PlainText
                    color: root.stateColor(root.jobState)
                    font.family: "monospace"
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }
                GGText { colorKey: "ui.QipSurface.4";
                    width: labColumn.width
                    text: "Explicit UTF-8 input → deterministic WASM render → output. "
                        + "The selected module stays local; imports, network and host I/O are blocked."
                    color: RuntimeTheme.GGTheme.muted
                    font.family: "monospace"
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }
                GGText { colorKey: "ui.QipSurface.5";
                    width: labColumn.width
                    text: root.loaded
                        ? "MODULE · " + String(root.inspection.name || "")
                            + "  ·  " + String(root.inspection.bytes || 0) + " bytes"
                            + "\nPATH · " + root.modulePath
                        : "MODULE · none selected"
                    color: RuntimeTheme.GGTheme.cyan
                    font.family: "monospace"
                    font.pixelSize: 12
                    wrapMode: Text.WrapAnywhere
                }
                GGText { colorKey: "ui.QipSurface.6";
                    width: labColumn.width
                    visible: root.loaded
                    text: "SECTIONS " + String(root.inspection.sections || 0)
                        + "  ·  FUNCTIONS " + String(root.inspection.function_count || 0)
                        + "  ·  IMPORTS " + String((root.inspection.imports || []).length)
                        + "\nMEMORY " + root.memoryText()
                        + "  ·  TABLE " + root.tableText()
                    color: RuntimeTheme.GGTheme.text
                    font.family: "monospace"
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }
                GGText { colorKey: "ui.QipSurface.7";
                    width: labColumn.width
                    visible: root.loaded
                    text: "EXPORTS · " + root.exportText()
                        + "\nQIP ABI · render="
                        + String((root.inspection.qip_abi || {}).render_export || false)
                        + "  memory="
                        + String((root.inspection.qip_abi || {}).memory_export || false)
                        + "  input_ptr="
                        + String((root.inspection.qip_abi || {}).input_pointer_export || false)
                    color: RuntimeTheme.GGTheme.dim
                    font.family: "monospace"
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                }
                GGText { colorKey: "ui.QipSurface.8";
                    width: labColumn.width
                    visible: String(root.inspection.reason || root.report.reason || "").length > 0
                    text: "BOUNDARY · " + String(root.inspection.reason || root.report.reason || "")
                    color: root.stateColor(root.report.state || root.inspection.state)
                    font.family: "monospace"
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }

                GGText { colorKey: "ui.QipSurface.9";
                    text: "INPUT · UTF-8"
                    color: RuntimeTheme.GGTheme.muted
                    font.family: "monospace"
                    font.pixelSize: 12
                }
                TextArea {
                    id: inputArea
                    objectName: "qipInput"
                    width: labColumn.width
                    height: 84
                    placeholderText: "text sent to the QIP render export"
                    color: RuntimeTheme.GGTheme.bright
                    placeholderTextColor: RuntimeTheme.GGTheme.dim
                    selectionColor: RuntimeTheme.GGTheme.selected
                    selectedTextColor: RuntimeTheme.GGTheme.bright
                    font.family: "monospace"
                    font.pixelSize: 12
                    wrapMode: TextArea.Wrap
                    selectByMouse: true
                    readOnly: root.running
                    padding: 8
                    background: Rectangle {
                        color: RuntimeTheme.GGTheme.canvas
                        border.width: 1
                        border.color: inputArea.activeFocus ? RuntimeTheme.GGTheme.dim : RuntimeTheme.GGTheme.edge
                        radius: 2
                    }
                }
                GGText { colorKey: "ui.QipSurface.10";
                    width: labColumn.width
                    visible: String(root.report.state || "") === "DONE"
                    text: "OUTPUT · " + String(root.report.output_bytes || 0) + " bytes"
                        + "  ·  deterministic=" + String(root.report.deterministic || false)
                        + "  ·  " + String(root.report.duration_ms || 0) + " ms"
                    color: RuntimeTheme.GGTheme.positive
                    font.family: "monospace"
                    font.pixelSize: 12
                }
                GGText { colorKey: "ui.QipSurface.11";
                    width: labColumn.width
                    visible: String(root.report.state || "") === "DONE"
                    text: String(root.report.output_text || "")
                    color: RuntimeTheme.GGTheme.text
                    font.family: "monospace"
                    font.pixelSize: 12
                    wrapMode: Text.WrapAnywhere
                    textFormat: Text.PlainText
                }
                GGText { colorKey: "ui.QipSurface.12";
                    width: labColumn.width
                    visible: !root.loaded
                    text: "No module loaded. OPEN .WASM selects a local component."
                    color: RuntimeTheme.GGTheme.muted
                    font.family: "monospace"
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }
                GGText { colorKey: "ui.QipSurface.13";
                    width: labColumn.width
                    text: "Render uses the local QIP ABI. The inspection above shows"
                        + " the module exports, memory limits and supported inputs."
                    color: RuntimeTheme.GGTheme.dim
                    font.family: "monospace"
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                }
            }
        }
    }
}
