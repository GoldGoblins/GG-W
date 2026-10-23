pragma ComponentBehavior: Bound

import QtQuick

Item {
    id: root

    objectName: "workspaceCodeRunner"

    property bool editorLoaded: false
    property bool editorDirty: false
    property bool canSave: false
    property string sourceName: ""
    property string language: ""
    property string liveAidState: "IDLE"
    property var diagnostics: []
    property string evidenceSummary: ""
    property string preflightState: "NOT RUN"
    property string repairState: "IDLE"
    property bool liveFeedbackEnabled: true
    property bool externalChangePending: false
    property string externalChangePath: ""
    property string externalChangeKind: ""
    property int cursorLine: 1
    property int cursorColumn: 1
    property int editorRevision: 0

    signal runRequested()
    signal saveRequested()
    signal toggleLiveFeedbackRequested(bool enabled)
    signal repairRequested()
    signal applyRepairRequested()
    signal syncExternalRequested()
    signal keepExternalRequested()

    function firstDiagnosticText() {
        if (!root.diagnostics || root.diagnostics.length === 0)
            return ""
        var item = root.diagnostics[0] || {}
        var code = String(item.code || item.kind || "PROBLEM")
        var message = String(item.message || item.detail || "")
        return message.length > 0 ? code + " · " + message : code
    }

    implicitHeight: runnerColumn.implicitHeight

    Rectangle {
        anchors.fill: parent
        color: "#101010"
        border.width: 1
        border.color: "#454545"
        radius: 2
    }

    Column {
        id: runnerColumn
        anchors.fill: parent
        anchors.leftMargin: 8
        anchors.rightMargin: 8
        anchors.topMargin: 5
        anchors.bottomMargin: 5
        spacing: 4

        Row {
            width: parent.width
            height: 28
            spacing: 6

            Text {
                width: Math.max(96, parent.width * 0.23)
                height: parent.height
                verticalAlignment: Text.AlignVCenter
                text: "RUNNER · "
                    + (root.language.length > 0
                        ? root.language.toUpperCase()
                        : "CODE")
                color: "#c8a97e"
                font.family: "monospace"
                font.pixelSize: 11
                font.bold: true
                elide: Text.ElideRight
            }

            GgButton {
                objectName: "workspaceCodeRunButton"
                width: 92
                height: 27
                enabled: root.editorLoaded
                text: root.preflightState === "RUNNING"
                    ? "CHECKING..."
                    : "RUN CHECK"
                onClicked: root.runRequested()
            }

            GgButton {
                objectName: "workspaceCodeLiveButton"
                width: 74
                height: 27
                enabled: root.editorLoaded
                checked: root.liveFeedbackEnabled
                text: root.liveFeedbackEnabled ? "LIVE ON" : "LIVE OFF"
                onClicked: root.toggleLiveFeedbackRequested(
                    !root.liveFeedbackEnabled
                )
            }

            GgButton {
                objectName: "workspaceCodeSaveButton"
                width: 58
                height: 27
                enabled: root.editorLoaded && root.canSave && root.editorDirty
                text: "SAVE"
                onClicked: root.saveRequested()
            }

            GgButton {
                objectName: "workspaceCodeRepairButton"
                width: 68
                height: 27
                enabled: root.editorLoaded
                    && root.preflightState === "FAIL"
                    && root.repairState !== "RUNNING"
                text: root.repairState === "RUNNING"
                    ? "FIXING..."
                    : "AI FIX"
                onClicked: root.repairRequested()
            }

            GgButton {
                objectName: "workspaceCodeApplyButton"
                width: 68
                height: 27
                enabled: root.repairState === "READY"
                text: "APPLY"
                onClicked: root.applyRepairRequested()
            }

            Text {
                width: Math.max(80, parent.width - 96 - 92 - 74 - 58 - 68 - 68 - 30)
                height: parent.height
                verticalAlignment: Text.AlignVCenter
                text: root.preflightState
                    + " · " + root.liveAidState
                    + " · " + String(root.diagnostics.length)
                    + " PROBLEMS"
                    + " · L" + root.cursorLine
                    + ":" + root.cursorColumn
                color: root.diagnostics.length > 0
                    ? "#d69a9a"
                    : "#8fbba8"
                font.family: "monospace"
                font.pixelSize: 10
                elide: Text.ElideRight
            }
        }

        Text {
            width: parent.width
            height: visible ? 18 : 0
            visible: (root.evidenceSummary.length > 0
                || root.diagnostics.length > 0)
                && !root.externalChangePending
            text: root.diagnostics.length > 0
                ? "PROBLEM · " + root.firstDiagnosticText()
                : root.evidenceSummary
            color: root.diagnostics.length > 0 ? "#d69a9a" : "#7d8590"
            font.family: "monospace"
            font.pixelSize: 10
            elide: Text.ElideRight
        }

        Row {
            width: parent.width
            height: visible ? 28 : 0
            visible: root.externalChangePending
            spacing: 6

            Text {
                width: Math.max(100, parent.width - 146)
                height: parent.height
                verticalAlignment: Text.AlignVCenter
                text: "EXTERNAL CHANGE · "
                    + (root.externalChangeKind === "site"
                        ? "SITE"
                        : "FILE")
                    + " · BUFFER UNSAVED"
                color: "#d69a9a"
                font.family: "monospace"
                font.pixelSize: 10
                elide: Text.ElideRight
            }

            GgButton {
                objectName: "workspaceCodeSyncExternalButton"
                width: 66
                height: 27
                text: "SYNC"
                enabled: root.externalChangePending
                onClicked: root.syncExternalRequested()
            }

            GgButton {
                objectName: "workspaceCodeKeepBufferButton"
                width: 70
                height: 27
                text: "KEEP"
                enabled: root.externalChangePending
                onClicked: root.keepExternalRequested()
            }
        }
    }
}
