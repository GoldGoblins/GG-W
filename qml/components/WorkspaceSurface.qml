pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Window

Item {
    id: root
    objectName: "workspaceSurface"

    signal activeObjectChanged(string objectId, string title)

    property var liveAidBackend: null
    property bool editorLoaded: false
    property bool editorDirty: false
    property string editorBaseText: ""
    property string editorSourceName: ""
    property string editorLanguage: ""
    property string editorBaseSha256: ""
    property bool liveFeedbackEnabled: true
    property string liveAidAnalysisSourceText: ""
    property int editorRevision: 0
    property int editorLine: 1
    property int editorColumn: 1
    property string editorFeedbackState: "IDLE"
    property string lastEditorCheck: "NOT RUN"
    property bool externalChangePending: false
    property string externalChangePath: ""
    property string externalChangeText: ""
    property string externalChangeKind: ""
    readonly property bool codeAuthoringActive:
        root.editorLoaded
        && root.currentObjectType === "CODE_FILE"
        && root.currentObjectProvenance !== "SYNTHETIC_UI_FIXTURE"
    readonly property bool codeSaveAvailable:
        root.currentObjectType === "CODE_FILE"
        && root.currentObjectProvenance === "REAL_UI_STATE"
    readonly property string editorText: codeEditor.text
    property string liveAidState: "IDLE"
    property var liveAidDiagnostics: []
    property string liveAidEvidenceSummary: ""
    property string preflightState: "NOT RUN"
    property string preflightSourceText: ""
    property string preflightReportSha256: ""
    property string repairState: "IDLE"
    property string repairProposalId: ""
    property string repairSourceText: ""
    property string repairOldText: ""
    property string repairNewText: ""
    property string postDraftState: "IDLE"
    property string postDraftSourceText: ""
    property string postDraftGateReportSha256: ""
    property bool postDraftApplyingCandidate: false
    readonly property bool postDraftBusy:
        root.postDraftState === "VERIFYING"
        || root.postDraftState === "GENERATING"
        || root.postDraftState === "REPAIRING"

    property int currentIndex: 0
    property string currentObjectId: ""
    property string currentObjectTitle: ""
    property string currentObjectType: ""
    property string currentObjectProvenance: ""
    property string currentObjectSourcePath: ""
    property var liveWebPane: null
    property var liveBrowseBar: null
    property string pendingWebOpPayload: ""
    property int pendingWebOpTries: 0
    property bool addressTyping: false
    property string addressDraft: ""
    property bool chromeOn: false
    property string chromeShape: "default"
    property real chromeX: 48
    property real chromeY: 12
    property var _chromeDone: null
    property var _addrCmd: null
    property var _addrPane: null
    property var _webOpCurrent: ({})
    property var _webOpPane: null
    property int _webOpEpoch: 0
    property string _addrTarget: ""
    property int _addrIndex: 0
    Connections {
        target: root.scratchHost()
        ignoreUnknownSignals: true
        function onWebOperatorCancelled(commandId, reason) {
            root.cancelWebOperator(commandId, reason)
        }
    }
    onLiveWebPaneChanged: {
        var action = String(root._webOpCurrent.action || "")
        if (root._webOpPane && root._webOpPane !== root.liveWebPane
                && ["TAB_NEW", "TAB_CLOSE", "TAB_NEXT", "TAB_PREV"].indexOf(action) < 0)
            root.cancelWebOperator(String(root._webOpCurrent.command_id || ""), "PANE_CHANGED")
    }
    readonly property string currentContextReference:
        root.currentObjectId.length > 0 ? "@current" : "@workspace"
    readonly property string slashCommandTemplate:
        "//** GoldGoblins shared slash-command guide (helper text) **//\n"
        + "//** /flush        Save the current session knowledge to memory. **//\n"
        + "//** /dream        Consolidate saved memory into durable topics. **//\n"
        + "//** /memory       Browse shared memory and session notes. **//\n"
        + "//** /remember X   Save X as a durable shared memory note. **//\n"
        + "//** /skills       List or load a workspace skill. **//\n"
        + "//** /plugins      List or reload installed plugins. **//\n"
        + "//** /hooks-list   Show the active knowledge and tool hooks. **//\n"
        + "//** /hooks-trust  Trust this workspace for its hooks. **//\n"
        + "//** /hooks-add X  Add a hook file or directory. **//\n"
        + "//** /model X      Switch the active model. **//\n"
        + "//** /resume X     Resume a saved chat session. **//\n"
        + "//** /new          Start a new session. **//\n"
        + "//** /load X       Load a saved workspace session. **//\n"
        + "//** /rewind X     Rewind to an earlier prompt. **//\n"
        + "//** /compact      Compact the current conversation. **//\n"
        + "//** /always-approve on|off  Set approval mode. **//\n"
        + "//** /multiline    Toggle multiline input. **//\n"
        + "//** /feedback X   Send feedback to the active motor. **//\n"
        + "//** /exit         Close the active TUI session. **//\n"
        + "//** /view X       Open a named GG workbench surface. **//\n"
        + "//** /engine X     Select the active chat motor. **//\n"
        + "//** /settings X   Open a settings module. **//\n"
        + "//** /extension X  List, enable or disable a built-in contribution. **//\n"
        + "//** /quickopen    Search workspace objects and settings. **//\n"
        + "//** This is helper text. It is stripped when a scratch file is saved. **//\n\n"

    function stripSlashCommandTemplate(body) {
        var text = String(body || "")
        return text.indexOf(root.slashCommandTemplate) === 0
            ? text.slice(root.slashCommandTemplate.length)
            : text
    }

    function updateEditorCursor() {
        if (!codeEditor)
            return

        var position = Math.max(
            0,
            Math.min(codeEditor.cursorPosition, codeEditor.text.length)
        )
        var before = codeEditor.text.slice(0, position)
        var lastBreak = before.lastIndexOf("\n")
        root.editorLine = before.split("\n").length
        root.editorColumn = position - lastBreak
    }

    function scheduleLiveAidAnalysis() {
        if (!root.liveFeedbackEnabled)
            return
        if (!root.editorLoaded)
            return
        if (root.liveAidBackend === null)
            return
        if (root.currentObjectProvenance !== "REAL_LOCAL_FILE")
            return
        root.editorFeedbackState = "QUEUED"
        analysisTimer.restart()
    }

    function runCodeCheck() {
        if (!root.codeAuthoringActive)
            return

        root.lastEditorCheck = "RUNNING"
        root.editorFeedbackState = "CHECKING"

        if (root.editorLanguage === "qml") {
            root.requestLiveAidPreflight()
            return
        }

        if (root.currentObjectProvenance !== "REAL_LOCAL_FILE") {
            root.lastEditorCheck = "BUFFER"
            root.editorFeedbackState = "BUFFER"
            root.liveAidEvidenceSummary =
                "SAFE CODE RUNNER · SAVE BUFFER OR OPEN A REAL SOURCE FILE"
            return
        }

        root.liveAidEvidenceSummary =
            "SAFE CODE RUNNER · LIVE AID ANALYSIS · NO EXECUTION"
        root.requestLiveAidAnalysis()
    }

    function saveCodeBuffer() {
        if (!root.codeSaveAvailable) {
            root.liveAidEvidenceSummary =
                "LOCAL FILE BUFFER · SAVE THROUGH CODEX OR TERMINAL"
            return false
        }
        return root.saveScratchBuffer()
    }

    function clearExternalChange() {
        root.externalChangePending = false
        root.externalChangePath = ""
        root.externalChangeText = ""
        root.externalChangeKind = ""
    }

    function externalChangeMatchesCurrent(path, kind) {
        var p = String(path || "")
        var k = String(kind || "")

        if (k === "site") {
            return root.currentObjectType === "CODE_FILE"
                && String(root.currentObjectId).indexOf(
                    "ws.site.file."
                ) === 0
                && root.siteRelativePath.length > 0
                && p.indexOf(root.siteRelativePath) >= 0
        }

        if (k === "scratch") {
            return root.currentObjectType === "CODE_FILE"
                && String(root.currentObjectId).indexOf(
                    "ws.file.scratch."
                ) === 0
                && (
                    p.indexOf(root.scratchFileName()) >= 0
                    || p.indexOf("untitled.txt") >= 0
                )
        }

        return false
    }

    function queueExternalFile(path, text, kind) {
        var p = String(path || "")
        var body = String(text || "")
        var k = String(kind || "")

        if (k.endsWith("-dir")) {
            var currentDir =
                (k === "site-dir" && root.hostKind === "SITE")
                || (
                    k === "scratch-dir"
                    && String(root.currentObjectId).indexOf(
                        "ws.file.scratch."
                    ) === 0
                )
            if (!currentDir)
                return root.applyExternalFile(p, body, k)
            if (root.editorDirty) {
                root.externalChangePending = true
                root.externalChangePath = p
                root.externalChangeText = body
                root.externalChangeKind = k
                root.liveAidEvidenceSummary =
                    "EXTERNAL DIRECTORY CHANGE · BUFFER UNSAVED · "
                    + "SYNC OR KEEP"
                return
            }
            return root.applyExternalFile(p, body, k)
        }

        if (!root.externalChangeMatchesCurrent(p, k))
            return root.applyExternalFile(p, body, k)

        root.externalChangePath = p
        root.externalChangeText = body
        root.externalChangeKind = k
        root.externalChangePending = true

        if (!root.editorDirty)
            externalChangeTimer.restart()
        else
            root.liveAidEvidenceSummary =
                "EXTERNAL CHANGE · BUFFER UNSAVED · "
                + "SYNC OR KEEP"
    }

    function applyQueuedExternalChange() {
        if (!root.externalChangePending)
            return false

        var path = root.externalChangePath
        var body = root.externalChangeText
        var kind = root.externalChangeKind
        root.clearExternalChange()
        root.applyExternalFile(path, body, kind)
        return true
    }

    function keepExternalBuffer() {
        if (!root.externalChangePending)
            return
        root.clearExternalChange()
        root.liveAidEvidenceSummary =
            "EXTERNAL CHANGE · BUFFER KEPT · DISK VERSION IGNORED"
    }

    function contextSnapshot(maximumObjects) {
        var maximum = Math.max(
            0,
            Math.floor(maximumObjects)
        )
        var limit = Math.min(
            workspaceObjects.count,
            maximum
        )
        var objects = []

        for (var i = 0; i < limit; ++i) {
            var item = workspaceObjects.get(i)

            objects.push({
                "objectId": String(item.objectId || ""),
                "title": String(item.title || ""),
                "objectType": String(item.objectType || ""),
                "provenanceClass": String(item.provenanceClass || ""),
                "sourcePath": String(item.sourcePath || ""),
                "activityState": String(item.activityState || "")
            })
        }

        return {
            "currentIndex": workspaceObjects.count > 0
                ? root.currentIndex
                : -1,
            "currentObjectId": workspaceObjects.count > 0
                ? root.currentObjectId
                : "",
            "activeEditor": {
                "title": String(root.currentObjectTitle || ""),
                "sourcePath": String(root.currentObjectSourcePath || ""),
                "sourceName": String(root.editorSourceName || ""),
                "language": String(root.editorLanguage || ""),
                "loaded": root.editorLoaded,
                "dirty": root.editorDirty,
                "revision": root.editorRevision,
                "line": root.editorLine,
                "column": root.editorColumn,
                "selectedText": String(codeEditor.selectedText || ""),
                "liveFeedback": root.liveFeedbackEnabled,
                "liveAidState": String(root.liveAidState || ""),
                "preflightState": String(root.preflightState || ""),
                "diagnosticCount": root.liveAidDiagnostics.length,
                "externalChangePending": root.externalChangePending
            },
            "objects": objects
        }
    }

    function resetAuthoringBuffer() {
        root.editorLoaded = false
        root.editorDirty = false
        root.editorBaseText = ""
        root.editorSourceName = ""
        root.editorLanguage = ""
        root.editorBaseSha256 = ""
        root.liveAidAnalysisSourceText = ""
        root.editorRevision = 0
        root.editorLine = 1
        root.editorColumn = 1
        root.editorFeedbackState = "IDLE"
        root.lastEditorCheck = "NOT RUN"
        root.clearExternalChange()
        root.liveAidState = "IDLE"
        root.liveAidDiagnostics = []
        root.liveAidEvidenceSummary = ""
        root.preflightState = "NOT RUN"
        root.preflightSourceText = ""
        root.preflightReportSha256 = ""
        root.repairState = "IDLE"
        root.repairProposalId = ""
        root.repairSourceText = ""
        root.repairOldText = ""
        root.repairNewText = ""
        root.postDraftState = "IDLE"
        root.postDraftSourceText = ""
        root.postDraftGateReportSha256 = ""
        root.postDraftApplyingCandidate = false
    }

    function loadCurrentAuthoringBuffer() {
        if (root.liveAidBackend === null)
            return

        if (root.currentObjectProvenance !== "REAL_LOCAL_FILE")
            return

        var raw = root.liveAidBackend.loadSource(
            root.currentObjectId
        )
        var payload = JSON.parse(raw)

        if (payload.status !== "PASS") {
            root.editorLoaded = false
            root.liveAidState = "BLOCKED"
            root.liveAidDiagnostics = []
            root.liveAidEvidenceSummary =
                payload.message || "source load failed"
            return
        }

        root.editorLoaded = false
        root.editorBaseText = payload.source
        root.editorSourceName = payload.source_name
        root.editorLanguage = payload.language
        root.editorBaseSha256 = payload.source_sha256
        codeEditor.text = payload.source
        root.editorDirty = false
        root.editorLoaded = true
        root.liveAidState = "QUEUED"
        root.editorFeedbackState = "QUEUED"
        root.liveAidDiagnostics = []
        root.liveAidEvidenceSummary =
            "DISK SHA · " + payload.source_sha256
        root.preflightState = "NOT RUN"
        root.preflightSourceText = ""
        root.preflightReportSha256 = ""
        root.repairState = "IDLE"
        root.repairProposalId = ""
        root.repairSourceText = ""
        root.repairOldText = ""
        root.repairNewText = ""
        root.postDraftState = "IDLE"
        root.postDraftSourceText = ""
        root.postDraftGateReportSha256 = ""
        root.postDraftApplyingCandidate = false
        root.updateEditorCursor()
        root.scheduleLiveAidAnalysis()
    }

    function requestLiveAidAnalysis() {
        if (!root.editorLoaded)
            return

        if (root.liveAidBackend === null)
            return

        if (root.currentObjectProvenance !== "REAL_LOCAL_FILE")
            return

        root.liveAidAnalysisSourceText = codeEditor.text
        root.liveAidState = "RUNNING"
        root.editorFeedbackState = "RUNNING"
        root.liveAidBackend.analyze(
            root.currentObjectId,
            root.editorSourceName,
            codeEditor.text,
            root.editorLanguage
        )
    }

    function requestLiveAidPreflight() {
        if (!root.editorLoaded)
            return

        if (root.liveAidBackend === null)
            return

        if (root.preflightState === "RUNNING")
            return

        analysisTimer.stop()
        root.preflightSourceText = codeEditor.text
        root.preflightState = "RUNNING"
        root.liveAidState = "PREFLIGHT"
        root.editorFeedbackState = "CHECKING"
        root.lastEditorCheck = "RUNNING"
        root.liveAidDiagnostics = []
        root.liveAidEvidenceSummary =
            "QML GATE PREFLIGHT · RUNNING · "
            + "NO EXECUTION · NO SAVE"

        root.liveAidBackend.preflight(
            root.currentObjectId,
            root.editorSourceName,
            codeEditor.text,
            root.editorLanguage
        )
    }

    function requestLiveAidRepair() {
        if (!root.editorLoaded)
            return

        if (root.liveAidBackend === null)
            return

        if (root.preflightState !== "FAIL")
            return

        if (root.liveAidDiagnostics.length === 0)
            return

        if (root.repairState === "RUNNING")
            return

        root.repairSourceText = codeEditor.text
        root.repairState = "RUNNING"
        root.repairProposalId = ""
        root.repairOldText = ""
        root.repairNewText = ""
        root.liveAidState = "GENERATING"
        root.liveAidEvidenceSummary =
            "LOCAL AI REPAIR · GENERATING · "
            + "UNTRUSTED PROPOSAL ONLY · NO APPLY"

        root.liveAidBackend.requestRepair(
            root.currentObjectId,
            root.editorSourceName,
            codeEditor.text,
            root.editorLanguage
        )
    }

    function requestApplyRepair() {
        if (root.liveAidBackend === null)
            return

        if (root.repairState !== "READY")
            return

        if (root.repairProposalId.length === 0)
            return

        root.liveAidBackend.applyRepair(
            root.repairProposalId,
            root.currentObjectId,
            codeEditor.text
        )
    }


    function requestPostDraftAutomaticRepair() {
        if (!root.editorLoaded)
            return

        if (root.liveAidBackend === null)
            return

        if (root.editorLanguage !== "qml")
            return

        if (root.postDraftBusy)
            return

        analysisTimer.stop()

        root.postDraftSourceText = codeEditor.text
        root.postDraftGateReportSha256 = ""
        root.postDraftState = "VERIFYING"
        root.liveAidState = "VERIFYING"
        root.liveAidDiagnostics = []
        root.liveAidEvidenceSummary =
            "POST-DRAFT · DRAFT COMPLETE · VERIFYING · "
            + "AUTOMATIC PRIVATE-BUFFER REPAIR · "
            + "NO SAVE · NO EXECUTION"

        root.liveAidBackend.runPostDraftRepair(
            root.currentObjectId,
            root.editorSourceName,
            codeEditor.text,
            root.editorLanguage
        )
    }

    onLiveAidBackendChanged: {
        if (
            root.liveAidBackend !== null
            && root.currentObjectProvenance === "REAL_LOCAL_FILE"
        ) {
            Qt.callLater(root.loadCurrentAuthoringBuffer)
        }
    }

    property bool showDemoFixtures: false
    property bool showProductSourceTabs: false
    property real chatWidthRatio: 0.31
    property int telemetryWidth: 168
    property color accentColor: "#8a8a8a"
    property color frameBorder: "#6a6a6a"
    property int frameRadius: 4
    property bool showOpenTabInInput: false
    property bool showInnerEditorChrome: true
    property bool settingsOpen: false
    property bool chatBusy: false
    property string engineTarget: "GROK_TUI"
    property string hostKind: "CODE"
    property bool keepGameEngine: false
    property bool keepResearch: false
    property string pendingResearchSection: ""
    onHostKindChanged: {
        if (hostKind !== "WEB" && root.pendingWebOpPayload.length === 0)
            root.cancelWebOperator(String(root._webOpCurrent.command_id || ""), "PANE_HIDDEN")
        if (hostKind === "QIP") {
            root.openResearch("WASM LAB")
            return
        }
        if (hostKind === "RESEARCH")
            keepResearch = true
        if (hostKind === "GAME_ENGINE")
            keepGameEngine = true
        if (root.hostKind !== "SITE")
            root.sitePreviewFullscreen = false
    }
    property string workbenchExtensionsJson: "[]"
    property int shellNonce: 0
    property var pendingAdoptedView: null
    readonly property string webPaneSource:
        "WebPane.qml?r=" + String(root.shellNonce)
    property string cryptoWalletLabel: "WALLET · DISCONNECTED"
    property int liveEpoch: 0

    function applyLiveReload() {
        root.liveEpoch = root.liveEpoch + 1
    }
    property int utilityHeight: 112
    property bool desktopShell: false
    property int nextInstanceSerial: 2
    property string siteRelativePath: "index.html"
    property string webPageUrl: ""
    property string browseUrl: "about:blank"
    property string browseBarText: ""
    property int sitePreviewNonce: 0
    property string siteImportStatus: "SITE · waiting for import"
    property string siteJobId: ""
    property string siteJobState: "IDLE"
    property string siteJobKind: ""
    readonly property bool siteImportBusy: siteJobState === "RUNNING" || siteJobState === "CANCELLING"
    property string siteHealthSummary: "PHP · not checked · CHECK PHP inspects the local runtime"
    property string siteHealthDetail: ""
    property string siteVersionSummary: "Version evidence only · running server not verified"

    Timer {
        interval: 120
        repeat: true
        running: root.siteImportBusy && root.siteJobId.length > 0
        onTriggered: root.pollSiteJob()
    }
    property bool sitePreviewRunning: false
    property string sitePreviewOrigin: ""
    property bool sitePreviewFullscreen: false
    property alias snippetModel: siteFileModel
    ListModel { id: siteFileModel }

    signal chatWidthRatioRequested(real value)
    signal telemetryWidthRequested(int value)
    signal accentColorRequested(color value)
    signal frameBorderRequested(color value)
    signal frameRadiusRequested(int value)
    signal demoVisibilityRequested(bool value)
    signal productSourceTabsRequested(bool value)
    signal showOpenTabInInputRequested(bool value)
    signal showInnerEditorChromeRequested(bool value)
    signal engineTargetRequested(string value)
    signal utilityHeightRequested(int value)
    signal desktopShellRequested(bool value)

    function openSettings() {
        root.settingsOpen = true
    }

    function closeSettings() {
        root.settingsOpen = false
    }

    // Escape is handled locally by SettingsSurface via Keys, avoiding a
    // global accelerator during QML reload.

    implicitWidth: 620
    implicitHeight: 620

    ListModel {
        id: workspaceObjects

        ListElement {
            objectId: "ws.file.scratch.1"
            title: "untitled"
            objectType: "CODE_FILE"
            provenanceClass: "REAL_UI_STATE"
            sourcePath: ""
            activityState: "IDLE"
        }
        ListElement {
            objectId: "ws.file.context-composer"
            title: "ContextComposer.qml"
            objectType: "CODE_FILE"
            provenanceClass: "REAL_LOCAL_FILE"
            sourcePath: "qml/components/ContextComposer.qml"
            activityState: "IDLE"
        }
        ListElement {
            objectId: "ws.file.grok-work-stream"
            title: "GrokWorkStream.qml"
            objectType: "CODE_FILE"
            provenanceClass: "REAL_LOCAL_FILE"
            sourcePath: "qml/components/GrokWorkStream.qml"
            activityState: "IDLE"
        }
        ListElement {
            objectId: "ws.file.chat-node"
            title: "ChatNode.qml"
            objectType: "CODE_FILE"
            provenanceClass: "REAL_LOCAL_FILE"
            sourcePath: "qml/components/ChatNode.qml"
            activityState: "IDLE"
        }
        ListElement {
            objectId: "ws.file.workspace-object-node"
            title: "WorkspaceObjectNode.qml"
            objectType: "CODE_FILE"
            provenanceClass: "REAL_LOCAL_FILE"
            sourcePath: "qml/components/WorkspaceObjectNode.qml"
            activityState: "IDLE"
        }
        ListElement {
            objectId: "ws.terminal.user"
            title: "Terminal"
            objectType: "USER_TERMINAL"
            provenanceClass: "REAL_UI_STATE"
            sourcePath: ""
            activityState: "IDLE"
        }
        ListElement {
            objectId: "ws.app.external"
            title: "External app"
            objectType: "EXTERNAL_APP"
            provenanceClass: "REAL_UI_STATE"
            sourcePath: ""
            activityState: "IDLE"
        }
        ListElement {
            objectId: "ws.web.stub"
            title: "Web"
            objectType: "WEBSITE"
            provenanceClass: "REAL_UI_STATE"
            sourcePath: "about:blank"
            activityState: "IDLE"
        }
        ListElement {
            objectId: "ws.site.current"
            title: "Site"
            objectType: "SITE_PROJECT"
            provenanceClass: "REAL_UI_STATE"
            sourcePath: "index.html"
            activityState: "IDLE"
        }
        ListElement {
            objectId: "ws.website.goldgoblins"
            title: "Website"
            objectType: "WEBSITE"
            provenanceClass: "SYNTHETIC_UI_FIXTURE"
            sourcePath: ""
            activityState: "IDLE"
        }
        ListElement {
            objectId: "ws.code.header-css"
            title: "header.css"
            objectType: "CODE_FILE"
            provenanceClass: "SYNTHETIC_UI_FIXTURE"
            sourcePath: ""
            activityState: "IDLE"
        }
        ListElement {
            objectId: "ws.document.invoice-pdf"
            title: "invoice.pdf"
            objectType: "PDF"
            provenanceClass: "SYNTHETIC_UI_FIXTURE"
            sourcePath: ""
            activityState: "IDLE"
        }
        ListElement {
            objectId: "ws.image.product"
            title: "product-image"
            objectType: "IMAGE"
            provenanceClass: "SYNTHETIC_UI_FIXTURE"
            sourcePath: ""
            activityState: "IDLE"
        }
    }

    function focusObject(objectId) {
        for (var i = 0; i < workspaceObjects.count; i++) {
            if (workspaceObjects.get(i).objectId === objectId) {
                activate(i)
                return true
            }
        }
        return false
    }

    function quickOpenRows() {
        var rows = []
        for (var i = 0; i < workspaceObjects.count; ++i) {
            var item = workspaceObjects.get(i)
            if (!item || item.provenanceClass === "SYNTHETIC_UI_FIXTURE")
                continue
            var title = String(item.title || item.objectId || "OBJECT")
            var path = String(item.sourcePath || "")
            rows.push({
                "id": "quick.object." + String(item.objectId || ""),
                "label": title,
                "category": String(item.objectType || "WORKSPACE"),
                "description": path.length > 0 ? path : "@current workspace object"
            })
        }
        return rows
    }

    function boundObjectActivityState() {
        if (root.currentObjectProvenance === "SYNTHETIC_UI_FIXTURE")
            return "IDLE"

        if (root.postDraftBusy) {
            if (
                root.postDraftState === "GENERATING"
                || root.postDraftState === "REPAIRING"
            )
                return "GENERATING"

            return "RUNNING"
        }

        if (root.repairState === "RUNNING")
            return "GENERATING"

        if (
            root.preflightState === "RUNNING"
            || root.liveAidState === "RUNNING"
            || root.liveAidState === "PREFLIGHT"
        )
            return "RUNNING"

        if (
            root.liveAidState === "GENERATING"
            || root.liveAidState === "VERIFYING"
        )
            return "GENERATING"

        if (root.liveAidState === "WAITING_FOR_USER")
            return "WAITING_FOR_USER"

        if (
            root.liveAidState === "BLOCKED"
            || root.preflightState === "BLOCKED"
            || root.repairState === "BLOCKED"
        )
            return "BLOCKED"

        if (root.preflightState === "FAIL")
            return "FAIL"

        if (root.preflightState === "PASS")
            return "PASS"

        if (root.liveAidState === "QUEUED")
            return "QUEUED"

        if (root.chatBusy)
            return root.engineTarget === "GROK_WORKER"
                ? "STREAMING"
                : "GENERATING"

        return "IDLE"
    }

    function syncObjectActivities() {
        for (var i = 0; i < workspaceObjects.count; i++) {
            var item = workspaceObjects.get(i)
            var nextState = "IDLE"

            if (item.objectId === root.currentObjectId)
                nextState = root.boundObjectActivityState()

            if (item.activityState !== nextState)
                workspaceObjects.setProperty(
                    i,
                    "activityState",
                    nextState
                )
        }
    }

    function hostKindForType(objectType) {
        if (objectType === "USER_TERMINAL")
            return "TERMINAL"
        if (objectType === "EXTERNAL_APP")
            return "EXTERNAL"
        if (objectType === "WEBSITE")
            return "WEB"
        if (objectType === "SITE_PROJECT")
            return "SITE"
        if (objectType === "CRYPTO_DESK")
            return "CRYPTO"
        if (objectType === "MARKETPLACE_DESK")
            return "MARKETPLACE"
        if (objectType === "TMOG_DESK")
            return "TMOG"
        if (objectType === "OSINT_DESK")
            return "OSINT"
        if (objectType === "QIP_DESK")
            return "RESEARCH"
        if (objectType === "DRAW_DESK" || objectType === "IMAGE")
            return "DRAW"
        if (objectType === "PDF")
            return "WEB"
        return "CODE"
    }

    function objectVisibleForKind(item, kind) {
        if (root.hostKindForType(item.objectType) !== kind)
            return false
        if (
            !root.showDemoFixtures
            && item.provenanceClass === "SYNTHETIC_UI_FIXTURE"
        )
            return false
        if (
            !root.showProductSourceTabs
            && item.provenanceClass === "REAL_LOCAL_FILE"
        )
            return false
        return true
    }

    function hostKindEnabled(kind) {
        var wanted = String(kind || "").toUpperCase()
        if (!wanted.length)
            return true
        var rows = []
        try {
            var parsed = JSON.parse(root.workbenchExtensionsJson || "[]")
            rows = parsed instanceof Array ? parsed : []
        } catch (err) {
            rows = []
        }
        if (rows.length === 0)
            return true
        for (var i = 0; i < rows.length; ++i) {
            var row = rows[i] || {}
            if (String(row.hostKind || "").toUpperCase() === wanted)
                return row.enabled !== false
        }
        return true
    }

    function openResearch(section) {
        root.pendingResearchSection = String(section || "")
        root.setHostKind("RESEARCH")
        if (researchPane.item) {
            if (root.pendingResearchSection.length)
                researchPane.item.page = root.pendingResearchSection
            root.pendingResearchSection = ""
            researchPane.item.refresh()
        }
    }

    function setHostKind(kind) {
        var requestedKind = String(kind || "").toUpperCase()
        if (requestedKind === "QIP") {
            root.openResearch("WASM LAB")
            return
        }
        if (!root.hostKindEnabled(requestedKind)) {
            if (requestedKind !== "CODE")
                root.setHostKind("CODE")
            return
        }
        kind = requestedKind
        if (
            (kind === "WEB" || kind === "SITE")
            && root.scratchHost()
            && root.scratchHost().ensureWebEngine
        )
            root.scratchHost().ensureWebEngine()
        root.hostKind = kind
        if (kind === "GAME_ENGINE")
            root.keepGameEngine = true
        if (kind === "CRYPTO" || kind === "MARKETPLACE" || kind === "TMOG" || kind === "OSINT" || kind === "QIP" || kind === "MEDIA" || kind === "DRAW" || kind === "GAME_ENGINE" || kind === "NODES" || kind === "FLOW" || kind === "RESEARCH")
            return
        if (
            kind === "CODE"
            && root.currentObjectType === "SITE_PROJECT"
            && root.siteRelativePath.length > 0
        ) {
            root.activate(root.ensureSiteCodeObject(root.siteRelativePath))
            return
        }
        for (var i = 0; i < workspaceObjects.count; ++i) {
            var item = workspaceObjects.get(i)
            if (!root.objectVisibleForKind(item, kind))
                continue
            root.activate(i)
            return
        }
        if (kind === "CODE")
            root.spawnHostInstance()
    }

    function spawnHostInstance() {
        var kind = root.hostKind
        var serial = root.nextInstanceSerial
        root.nextInstanceSerial = serial + 1
        var objectId = ""
        var title = ""
        var objectType = "CODE_FILE"
        if (kind === "TERMINAL") {
            objectId = "ws.terminal.user." + serial
            title = "Terminal " + serial
            objectType = "USER_TERMINAL"
        } else if (kind === "WEB") {
            objectId = "ws.web.stub." + serial
            title = "Web " + serial
            objectType = "WEBSITE"
        } else if (kind === "EXTERNAL") {
            objectId = "ws.app.external." + serial
            title = "External app " + serial
            objectType = "EXTERNAL_APP"
        } else if (kind === "SITE") {
            objectId = "ws.site.current." + serial
            title = "Site " + serial
            objectType = "SITE_PROJECT"
        } else {
            objectId = "ws.file.scratch." + serial
            title = "untitled-" + serial
            objectType = "CODE_FILE"
        }
        workspaceObjects.append({
            "objectId": objectId,
            "title": title,
            "objectType": objectType,
            "provenanceClass": "REAL_UI_STATE",
            "sourcePath": kind === "WEB" ? "about:blank" : "",
            "activityState": "IDLE"
        })
        root.activate(workspaceObjects.count - 1)
    }

    function isSpawnedObject(objectId) {
        var id = String(objectId || "")
        return id.indexOf("ws.file.scratch.") === 0
            || id.indexOf("ws.terminal.user.") === 0
            || id.indexOf("ws.app.external.") === 0
            || id.indexOf("ws.web.stub.") === 0
            || id.indexOf("ws.site.current.") === 0
            || id.indexOf("ws.site.file.") === 0
    }

    function scratchHost() {
        var win = Window.window
        if (win && win.surfaceHost)
            return win.surfaceHost
        return null
    }

    function scratchFileName() {
        var name = String(root.currentObjectTitle || "untitled")
        name = name.replace(/[^A-Za-z0-9._-]+/g, "-")
        if (name.length === 0)
            name = "untitled"
        if (name.indexOf(".") < 0)
            name += ".txt"
        return name
    }

    function scratchNameFromUrl(url) {
        var raw = String(url || "").replace(/^file:\/\//, "")
        try {
            raw = decodeURIComponent(raw)
        } catch (e) {
        }
        var parts = raw.split("/")
        return parts[parts.length - 1] || ""
    }

    function saveScratchAs(fileName) {
        var name = String(fileName || "").replace(/[^A-Za-z0-9._-]+/g, "-")
        if (name.length === 0)
            return false
        if (root.currentObjectType !== "CODE_FILE")
            return false
        if (root.currentObjectProvenance !== "REAL_UI_STATE")
            return false
        var host = root.scratchHost()
        if (host === null)
            return false
        var saved = host.saveScratchFile(
            name,
            root.stripSlashCommandTemplate(codeEditor.text)
        )
        if (!saved || String(saved).length === 0)
            return false
        if (root.currentIndex >= 0)
            workspaceObjects.setProperty(root.currentIndex, "title", name)
        root.editorSourceName = name
        root.editorBaseText = codeEditor.text
        root.editorDirty = false
        root.clearExternalChange()
        root.editorFeedbackState = "SAVED"
        root.liveAidEvidenceSummary = "SAVED · " + String(saved)
        return true
    }

    function saveScratchBuffer() {
        if (String(root.currentObjectId).indexOf("ws.site.file.") === 0)
            return root.saveSiteBuffer()
        return root.saveScratchAs(root.scratchFileName())
    }

    function filePathFromUrl(url) {
        var raw = String(url || "").replace(/^file:\/\//, "")
        try {
            raw = decodeURIComponent(raw)
        } catch (e) {
        }
        return raw
    }

    function openSaveAsDialog() {
        var host = root.scratchHost()
        var folder = "file:///home/GG/.local/state/goldgoblins/gg-ai-desktop/scratch"
        var name = root.scratchFileName()
        if (
            String(root.currentObjectId).indexOf("ws.site.file.") === 0
            && host !== null
        ) {
            folder = "file://" + String(host.siteRoot())
            if (String(root.siteRelativePath).length > 0)
                name = String(root.siteRelativePath)
        }
        scratchSaveDialog.currentFolder = folder
        scratchSaveDialog.selectedFile = folder + "/" + name
        scratchSaveDialog.open()
    }

    function applySaveAsUrl(url) {
        var path = root.filePathFromUrl(url)
        var host = root.scratchHost()
        if (host !== null) {
            var siteRoot = String(host.siteRoot())
            if (siteRoot.length > 0 && path.indexOf(siteRoot) === 0) {
                var rel = path.slice(siteRoot.length).replace(/^\//, "")
                if (rel.length === 0)
                    return false
                var saved = host.writeSiteFile(rel, codeEditor.text)
                if (!saved)
                    return false
                root.editorBaseText = codeEditor.text
                root.editorDirty = false
                root.clearExternalChange()
                root.editorFeedbackState = "SAVED"
                root.liveAidEvidenceSummary = "SAVED AS · site:" + rel
                return true
            }
        }
        return root.saveScratchAs(root.scratchNameFromUrl(url))
    }

    function webTabCount() {
        return root.webTabIndices().length
    }

    function webTabIndices() {
        var out = []
        var i
        for (i = 0; i < workspaceObjects.count; ++i) {
            var item = workspaceObjects.get(i)
            if (
                item.objectType === "WEBSITE"
                && item.provenanceClass === "REAL_UI_STATE"
            )
                out.push(i)
        }
        return out
    }

    function focusWebTabDelta(delta) {
        var tabs = root.webTabIndices()
        if (tabs.length === 0)
            return false
        var at = tabs.indexOf(root.currentIndex)
        if (at < 0)
            at = 0
        var next = tabs[(at + delta + tabs.length) % tabs.length]
        root.activate(next)
        return true
    }

    function openWebTab(url) {
        root.setHostKind("WEB")
        root.spawnHostInstance()
        if (String(url || "").length > 0)
            root.goBrowse(url)
    }

    function adoptPopupView(view) {
        if (!view)
            return
        root.pendingAdoptedView = view
        root.setHostKind("WEB")
        root.spawnHostInstance()
        var pane = root.liveWebPane
        if (pane && pane.takeView && root.pendingAdoptedView) {
            pane.takeView(root.pendingAdoptedView)
            root.pendingAdoptedView = null
        }
    }

    function resetWebTab(index) {
        if (index < 0 || index >= workspaceObjects.count)
            return
        workspaceObjects.setProperty(index, "sourcePath", "about:blank")
        workspaceObjects.setProperty(index, "title", "Web")
        if (index === root.currentIndex) {
            root.browseUrl = "about:blank"
            root.browseBarText = ""
        }
        root.activate(index)
    }

    function closeHostInstance(index) {
        if (index < 0 || index >= workspaceObjects.count)
            return
        var item = workspaceObjects.get(index)
        if (
            item.objectType === "WEBSITE"
            && item.provenanceClass === "REAL_UI_STATE"
        ) {
            if (
                item.objectId === "ws.web.stub"
                || root.webTabCount() <= 1
            ) {
                root.resetWebTab(index)
                return
            }
        } else if (!root.isSpawnedObject(item.objectId))
            return
        if (
            index === root.currentIndex
            && item.objectType === "CODE_FILE"
            && item.provenanceClass === "REAL_UI_STATE"
            && root.editorDirty
        )
            root.saveScratchBuffer()
        var host = root.scratchHost()
        if (
            host !== null
            && item.objectType === "USER_TERMINAL"
        )
            host.stopChatTerminal(item.objectId)
        var closedKind = root.hostKindForType(item.objectType)
        var wasCurrent = index === root.currentIndex
        workspaceObjects.remove(index)
        if (root.currentIndex > index)
            root.currentIndex -= 1
        if (!wasCurrent)
            return
        root.setHostKind(closedKind)
    }

    function applyCryptoWalletLabel() {
        var host = root.scratchHost()
        if (host === null)
            return
        var raw = ""
        if (host.cryptoRailStatus)
            raw = host.cryptoRailStatus()
        else if (host.cryptoStatus)
            raw = host.cryptoStatus()
        if (!raw)
            return
        try {
            var parsed = JSON.parse(raw)
            var w = parsed.wallet || {}
            var label = String(w.label || "")
            if (!label && w.pubkey) {
                var key = String(w.pubkey)
                label = key.length >= 8
                    ? ("WALLET · " + key.slice(0, 4) + "…" + key.slice(-4))
                    : ("WALLET · " + key)
            }
            if (label)
                root.cryptoWalletLabel = label
        } catch (err) {
        }
    }

    function refreshSiteFiles() {
        var host = root.scratchHost()
        if (host === null)
            return
        var raw = host.listSiteFiles()
        var rows = []
        try {
            rows = JSON.parse(raw)
        } catch (e) {
            rows = []
        }
        siteFileModel.clear()
        for (var i = 0; i < rows.length; ++i)
            siteFileModel.append(rows[i])
        if (
            !root.sitePreviewRunning
            && root.siteImportStatus.indexOf("IMPORT") !== 0
            && root.siteImportStatus.indexOf("PREVIEW") !== 0
            && rows.length > 0
        )
            root.siteImportStatus = "SITE · local · " + String(rows.length) + " listed"
        var preferred = host.preferredSiteFile
            ? host.preferredSiteFile()
            : ""
        if (root.siteRelativePath.length === 0 && preferred.length > 0)
            root.openSiteFile(preferred)
        else if (root.siteRelativePath.length === 0 && rows.length > 0)
            root.openSiteFile(rows[0].path)
    }

    function siteFileObjectId(relative) {
        return "ws.site.file." + String(relative || "")
    }

    function ensureSiteCodeObject(relative) {
        var objectId = root.siteFileObjectId(relative)
        for (var i = 0; i < workspaceObjects.count; ++i) {
            if (workspaceObjects.get(i).objectId === objectId)
                return i
        }
        workspaceObjects.append({
            "objectId": objectId,
            "title": relative,
            "objectType": "CODE_FILE",
            "provenanceClass": "REAL_UI_STATE",
            "sourcePath": relative,
            "activityState": "IDLE"
        })
        return workspaceObjects.count - 1
    }

    function chooseSnippet(relative) {
        root.ensureSiteCodeObject(relative)
        if (root.hostKind === "CODE")
            root.activate(root.ensureSiteCodeObject(relative))
        else
            root.openSiteFile(relative)
    }

    function openSiteFile(relative) {
        var host = root.scratchHost()
        if (host === null)
            return
        var body = host.readSiteFile(relative)
        root.siteRelativePath = relative
        root.currentObjectSourcePath = relative
        root.editorLoaded = false
        root.editorBaseText = body
        codeEditor.text = body
        root.editorDirty = false
        root.editorLoaded = true
        root.editorFeedbackState = "SYNCED"
        root.lastEditorCheck = "NOT RUN"
        root.updateEditorCursor()
        root.webPageUrl = host.siteFileUrl(relative)
        if (root.sitePreviewRunning)
            root.applySitePreviewUrl()
        if (host.watchLivePath && host.siteRoot)
            host.watchLivePath(host.siteRoot() + "/" + relative)
    }

    function rememberBrowse(index, href) {
        if (index < 0 || index >= workspaceObjects.count)
            return
        var item = workspaceObjects.get(index)
        if (item.objectType !== "WEBSITE")
            return
        workspaceObjects.setProperty(index, "sourcePath", href)
        if (index === root.currentIndex) {
            root.browseUrl = href
            root.browseBarText = href === "about:blank" ? "" : href
        }
    }

    function goBrowse(raw) {
        var host = root.scratchHost()
        if (host === null)
            return
        var next = host.normalizeBrowseUrl(raw)
        if (!next)
            return
        root.rememberBrowse(root.currentIndex, next)
    }

    function syncChromeDesk() {
        var win = Window.window
        if (!win || !win.setDeskCursor)
            return
        win.deskFromChrome = root.chromeOn
        if (root.chromeOn)
            win.setDeskCursor(root, root.chromeX, root.chromeY, root.chromeShape)
    }

    function moveChromeTo(item, ox, oy, done) {
        done = root._webGuard(root._webOpCurrent, done)
        if (!item) {
            if (typeof done === "function")
                done()
            return
        }
        var win = Window.window
        if (win && win.deskX !== undefined) {
            var here = root.mapFromItem(
                win.contentItem,
                Number(win.deskX),
                Number(win.deskY)
            )
            root.chromeX = here.x
            root.chromeY = here.y
        }
        var p = item.mapToItem(root, ox, oy)
        var nx = Math.max(4, Number(p.x))
        var ny = Math.max(4, Number(p.y))
        root.chromeOn = true
        root.syncChromeDesk()
        var dist = Math.sqrt(
            Math.pow(nx - root.chromeX, 2) + Math.pow(ny - root.chromeY, 2)
        )
        if (dist < 1.5) {
            root.chromeX = nx
            root.chromeY = ny
            if (typeof done === "function")
                Qt.callLater(done)
            return
        }
        chromeMove.doneFn = done
        chromeXAnim.from = root.chromeX
        chromeXAnim.to = nx
        chromeYAnim.from = root.chromeY
        chromeYAnim.to = ny
        var ms = Math.max(180, Math.min(560, 120 + dist * 0.6))
        chromeXAnim.duration = ms
        chromeYAnim.duration = ms
        chromeMove.start()
    }

    function typeAddressThenGo(url, cmd) {
        var pane = root.liveWebPane
        if (pane) {
            pane.agentActive = false
            pane.operatorLabel = "GROK · OPEN"
            pane.agentShape = "text"
        }
        root.chromeShape = "text"
        root._addrCmd = cmd
        root._addrPane = pane
        root._addrTarget = String(url || "")
        root._addrIndex = 0
        root.addressTyping = true
        root.addressDraft = ""
        var bar = root.liveBrowseBar
        if (bar && bar.forceActiveFocus)
            bar.forceActiveFocus()
        root.moveChromeTo(bar, 18, 13, function() {
            addrTypeTimer.start()
        })
    }

    function _addrTick() {
        if (!root._webCommandLive(root._addrCmd))
            return
        if (root._addrPane !== root.liveWebPane) {
            root.cancelWebOperator(String(root._addrCmd.command_id || ""), "PANE_CHANGED")
            return
        }
        if (root._addrIndex >= root._addrTarget.length) {
            addrTypeTimer.stop()
            root.addressTyping = false
            var pane = root.liveWebPane
            var cmd = root._addrCmd
            root.goBrowse(root._addrTarget)
            if (pane && pane.waitLoad) {
                pane.agentActive = true
                pane.agentShape = "wait"
                pane.waitLoad(root._webGuard(cmd, function(state) {
                    root.chromeOn = false
                    var href = pane.currentHref()
                    root.reportWebOperator(
                        cmd,
                        state === "PASS",
                        state === "PASS" ? "OPENED_WEB_TAB" : "OPEN_" + state,
                        href || root._addrTarget,
                        "",
                        "",
                        []
                    )
                }))
                return
            }
            root.chromeOn = false
            root.reportWebOperator(cmd, true, "OPENED_WEB_TAB", root._addrTarget, "", "", [])
            return
        }
        root.addressDraft += root._addrTarget.charAt(root._addrIndex)
        root._addrIndex += 1
        if (root.liveWebPane)
            root.liveWebPane.operatorLabel = "GROK · OPEN · " + root._addrIndex + "/" + root._addrTarget.length
    }

    function clickPlusThen(done) {
        done = root._webGuard(root._webOpCurrent, done)
        var pane = root.liveWebPane
        if (pane) {
            pane.agentActive = false
            pane.operatorLabel = "GROK · TAB"
            pane.agentShape = "pointer"
        }
        root.chromeShape = "pointer"
        root.moveChromeTo(spawnInstanceButton, spawnInstanceButton.width - 7, 9, function() {
            chromeRipple.play()
            root.spawnHostInstance()
            Qt.callLater(function() {
                if (typeof done === "function")
                    done()
            })
        })
    }

    function _webCommandLive(cmd) {
        if (!cmd || !cmd.command_id || cmd.command_id !== root._webOpCurrent.command_id)
            return false
        if (Number(cmd.expires_at || 0) > 0 && Date.now() / 1000 >= Number(cmd.expires_at)) {
            root.cancelWebOperator(String(cmd.command_id), "OPERATOR_TIMEOUT")
            return false
        }
        return true
    }

    function _webGuard(cmd, fn) {
        var epoch = root._webOpEpoch
        return function(value) {
            if (epoch !== root._webOpEpoch || !root._webCommandLive(cmd))
                return
            if (typeof fn === "function")
                fn(value)
        }
    }

    function cancelWebOperator(commandId, reason) {
        var cmd = root._webOpCurrent
        if (!commandId || !cmd || String(cmd.command_id || "") !== String(commandId))
            return
        root.pendingWebOpPayload = ""
        webOpRetry.stop()
        addrTypeTimer.stop()
        chromeMove.doneFn = null
        chromeMove.stop()
        root.addressTyping = false
        root.chromeOn = false
        var pane = root._webOpPane
        if (pane && pane.cancelLoadWait)
            pane.cancelLoadWait()
        if (pane && pane.cancelOperator)
            pane.cancelOperator(commandId, reason || "OPERATOR_CANCELLED")
        if (String(root._webOpCurrent.command_id || "") === String(commandId))
            root.reportWebOperator(cmd, false, reason || "OPERATOR_CANCELLED", "", "", "", [])
    }

    function reportWebOperator(cmd, ok, reason, url, title, text, links, image, completionUncertain) {
        if (!cmd || !cmd.command_id || cmd.command_id !== root._webOpCurrent.command_id)
            return
        root._webOpCurrent = ({})
        root._webOpEpoch += 1
        root._webOpPane = null
        root._addrCmd = null
        root._addrPane = null
        var host = root.scratchHost()
        if (!host || !host.webOperatorReport)
            return
        var authorization = (cmd && cmd.task_scoped_authorization)
                ? cmd.task_scoped_authorization : null
        var scoped = authorization
                && String(authorization.action_authority || "") === "TASK_SCOPED"
                && String(authorization.general_action_authority || "") === "TASK_SCOPED"
        host.webOperatorReport(JSON.stringify({
            "schema": "gg.web-operator-result.v1",
            "command_id": cmd.command_id,
            "ok": ok,
            "reason_code": reason,
            "risk_class": cmd.risk_class || "GREEN",
            "action": String(cmd.action || ""),
            "url": url || "",
            "title": title || "",
            "text": text || "",
            "links": links || [],
            "image": image || "",
            "completion_uncertain": completionUncertain === true,
            "action_authority": scoped ? "TASK_SCOPED" : "NONE",
            "general_action_authority": scoped ? "TASK_SCOPED" : "NONE",
            "scope_authority": scoped
                    ? String(authorization.scope_authority || "NONE") : "NONE",
            "task_scoped_authorization": authorization,
            "visible_web_tab": true,
            "visible_cursor": true
        }))
    }

    function applyWebOperator(payload) {
        var cmd
        try { cmd = JSON.parse(String(payload || "{}")) } catch (err) { return }
        if (!cmd.command_id || cmd.command_id === root._webOpCurrent.command_id)
            return
        if (root._webOpCurrent.command_id)
            root.cancelWebOperator(String(root._webOpCurrent.command_id), "OPERATOR_REPLACED")
        root._webOpCurrent = cmd
        root._webOpEpoch += 1
        if (!root._webCommandLive(cmd))
            return
        if (root.hostKind !== "WEB") {
            // An approved visible-WEB action may arrive while the user is
            // looking at CODE, SITE or another workspace surface.  Switch
            // the visible host and keep the command queued until its pane is
            // ready; the user should not have to manually focus the tab.
            root.pendingWebOpPayload = String(payload || "")
            root.pendingWebOpTries = 0
            root.setHostKind("WEB")
            webOpRetry.restart()
            return
        }
        var pane = root.liveWebPane
        if (!pane || !pane.playOperator) {
            root.pendingWebOpPayload = String(payload || "")
            root.pendingWebOpTries = 0
            webOpRetry.restart()
            return
        }
        root.runWebOperator(String(payload || ""))
    }

    function flushPendingWebOp() {
        if (root.pendingWebOpPayload.length === 0)
            return
        var pane = root.liveWebPane
        if (pane && pane.playOperator) {
            var payload = root.pendingWebOpPayload
            root.pendingWebOpPayload = ""
            root.runWebOperator(payload)
            return
        }
        root.pendingWebOpTries += 1
        if (root.pendingWebOpTries > 40) {
            var cmd = {}
            try {
                cmd = JSON.parse(root.pendingWebOpPayload)
            } catch (err) {
                cmd = {}
            }
            root.pendingWebOpPayload = ""
            root.reportWebOperator(
                cmd,
                false,
                "WEB_PANE_NOT_READY",
                "",
                "",
                "",
                []
            )
            return
        }
        webOpRetry.restart()
    }

    function runWebOperator(payload) {
        var cmd = {}
        try {
            cmd = JSON.parse(String(payload || "{}"))
        } catch (err) {
            return
        }
        var action = String(cmd.action || "")
        if (!root._webCommandLive(cmd))
            return
        root._webOpPane = root.liveWebPane
        if (action === "TAB_NEW") {
            var sel = String(cmd.selector || "")
            var url = String(cmd.url || "")
            if (sel.length > 0) {
                var paneHit = root.liveWebPane
                if (!paneHit || !paneHit.playOperator) {
                    root.reportWebOperator(cmd, false, "WEB_PANE_NOT_READY", "", "", "", [])
                    return
                }
                paneHit.agentActive = true
                paneHit.playOperator({
                    "schema": cmd.schema,
                    "command_id": cmd.command_id,
                    "action": "CLICK",
                    "url": "",
                    "selector": sel,
                    "text": "aux",
                    "risk_class": cmd.risk_class,
                    "expires_at": Number(cmd.expires_at || 0),
                    "task_scoped_authorization": cmd.task_scoped_authorization || null
                }, root._webGuard(cmd, function(result) {
                    var value = result || {}
                    if (value.ok !== true) {
                        root.reportWebOperator(cmd, false, String(value.reason || "FAIL"), "", "", "", [], "", value.completion_uncertain)
                        return
                    }
                    var href = String(value.url || "")
                    var before = root.webTabCount()
                    Qt.callLater(root._webGuard(cmd, function() {
                        if (root.webTabCount() === before && href.length > 0)
                            root.openWebTab(href)
                        root.reportWebOperator(
                            cmd,
                            true,
                            "TAB_OPENED",
                            href,
                            "",
                            String(root.webTabCount()),
                            []
                        )
                    }))
                }))
                return
            }
            root.clickPlusThen(function() {
                if (url.length === 0) {
                    root.chromeOn = false
                    root.reportWebOperator(
                        cmd,
                        true,
                        "TAB_OPENED",
                        "about:blank",
                        "",
                        String(root.webTabCount()),
                        []
                    )
                    return
                }
                root.pendingWebOpPayload = JSON.stringify({
                    "schema": cmd.schema,
                    "command_id": cmd.command_id,
                    "action": "OPEN",
                    "url": url,
                    "selector": "",
                    "text": "",
                    "risk_class": cmd.risk_class,
                    "general_action_authority": cmd.general_action_authority || "NONE",
                    "action_authority": cmd.action_authority || "NONE",
                    "scope_authority": cmd.scope_authority || "NONE",
                    "task_scoped_authorization": cmd.task_scoped_authorization || null
                    , "expires_at": Number(cmd.expires_at || 0)
                })
                root.pendingWebOpTries = 0
                webOpRetry.restart()
            })
            return
        }
        if (action === "TAB_CLOSE") {
            root.closeHostInstance(root.currentIndex)
            root.reportWebOperator(
                cmd,
                true,
                "TAB_CLOSED",
                "",
                "",
                String(root.webTabCount()),
                []
            )
            return
        }
        if (action === "TAB_NEXT" || action === "TAB_PREV") {
            var moved = root.focusWebTabDelta(action === "TAB_NEXT" ? 1 : -1)
            var href = root.liveWebPane ? root.liveWebPane.currentHref() : ""
            root.reportWebOperator(
                cmd,
                moved,
                moved ? "TAB_FOCUSED" : "TAB_MISSING",
                href,
                "",
                String(root.webTabCount()),
                []
            )
            return
        }
        var pane = root.liveWebPane
        if (!pane || !pane.playOperator) {
            root.reportWebOperator(cmd, false, "WEB_PANE_NOT_READY", "", "", "", [])
            return
        }
        pane.agentActive = true
        if (action === "OPEN") {
            root.typeAddressThenGo(String(cmd.url || ""), cmd)
            return
        }
        pane.playOperator(cmd, root._webGuard(cmd, function(result) {
            var value = result || {}
            root.reportWebOperator(
                cmd,
                value.ok === true,
                String(value.reason || "FAIL"),
                String(value.url || pane.currentHref()),
                String(value.title || ""),
                String(value.text || ""),
                value.links || [],
                String(value.image || ""),
                value.completion_uncertain
            )
        }))
    }

    function applySitePreviewUrl() {
        if (!root.sitePreviewRunning || root.sitePreviewOrigin.length === 0) {
            var host = root.scratchHost()
            if (host !== null && root.siteRelativePath.length > 0)
                root.webPageUrl = host.siteFileUrl(root.siteRelativePath)
            return
        }
        var rel = root.siteRelativePath
        if (
            rel === "index.php"
            || rel === "index.html"
            || rel.length === 0
        )
            rel = ""
        root.webPageUrl = root.sitePreviewOrigin + rel
        root.sitePreviewNonce = root.sitePreviewNonce + 1
    }

    function ensureSitePreview() {
        if (root.siteImportBusy)
            return false
        var host = root.scratchHost()
        if (host === null)
            return false
        if (root.sitePreviewRunning && root.sitePreviewOrigin.length > 0) {
            root.applySitePreviewUrl()
            return true
        }
        var existing = host.sitePreviewOrigin
            ? String(host.sitePreviewOrigin())
            : ""
        if (existing.length > 0) {
            root.sitePreviewOrigin = existing
            root.sitePreviewRunning = true
            root.siteImportStatus = "PREVIEW · localhost"
            root.applySitePreviewUrl()
            return true
        }
        root.siteImportStatus = "PREVIEW · starting"
        var raw = host.startSitePreview()
        var lines = String(raw).split("\n")
        var origin = lines[0] || ""
        var kind = lines.length > 1 ? lines[1] : "STATIC"
        if (origin.length === 0) {
            root.siteImportStatus = "FAIL: local preview did not start"
            return false
        }
        root.sitePreviewOrigin = origin
        root.sitePreviewRunning = true
        root.siteImportStatus = (
            kind === "PHP"
                ? "PREVIEW · localhost PHP"
                : "PREVIEW · localhost static · PHP not installed · WP will not execute"
        )
        root.applySitePreviewUrl()
        return true
    }

    function toggleSitePreview() {
        var host = root.scratchHost()
        if (host === null)
            return
        if (root.sitePreviewRunning) {
            root.sitePreviewFullscreen = false
            host.stopSitePreview()
            root.sitePreviewRunning = false
            root.sitePreviewOrigin = ""
            root.siteImportStatus = "PREVIEW · stopped"
            root.applySitePreviewUrl()
            return
        }
        root.ensureSitePreview()
    }

    function toggleSitePreviewFullscreen() {
        if (root.sitePreviewFullscreen) {
            root.exitSitePreviewFullscreen()
            return
        }
        if (!root.sitePreviewRunning && !root.ensureSitePreview())
            return
        root.sitePreviewFullscreen = true
    }

    function exitSitePreviewFullscreen() {
        root.sitePreviewFullscreen = false
    }

    function assessSitePhpVersion(value) {
        var host = root.scratchHost()
        if (!host || !host.sitePhpVersionAssessment)
            return false
        try {
            var result = JSON.parse(String(host.sitePhpVersionAssessment(value)))
            root.siteVersionSummary = String(result.status || "UNKNOWN")
                + " · version evidence only · running server not verified · " + String(result.detail || "")
            return true
        } catch (error) {
            root.siteVersionSummary = "UNKNOWN · version could not be assessed"
            return false
        }
    }

    function applySiteJobReply(reply) {
        var state = String(reply.state || "ERROR")
        if (reply.job_id) {
            root.siteJobId = String(reply.job_id)
            root.siteJobKind = String(reply.kind || root.siteJobKind)
        }
        root.siteJobState = state
        if (root.siteJobKind !== "HEALTH" && root.siteImportBusy) {
            root.sitePreviewRunning = false
            root.sitePreviewOrigin = ""
            root.sitePreviewFullscreen = false
        }
        if (state === "RUNNING" || state === "CANCELLING") {
            root.siteImportStatus = (state === "CANCELLING" ? "CANCELLING" : "IMPORT " + root.siteJobKind)
                + " · " + String(reply.phase || "starting")
                + (Number(reply.total) > 0 ? " · " + String(reply.current || 0) + "/" + String(reply.total) : "")
            return
        }
        if (reply.health) {
            var health = reply.health
            root.siteHealthSummary = "PHP · " + String(health.version || health.runtime || "UNKNOWN")
                + " · " + String(health.status || "UNKNOWN")
                + (health.restart_required ? " · RESTART PREVIEW REQUIRED" : "")
                + " · rules " + String(health.rules_date || "unknown")
            root.siteHealthDetail = String(health.detail || "")
        }
        if (root.siteJobKind === "TREE") {
            root.refreshSiteFiles()
            if (state === "DONE") {
                var host = root.scratchHost()
                var preferred = host && host.preferredSiteFile ? String(host.preferredSiteFile()) : ""
                if (preferred.length > 0)
                    root.openSiteFile(preferred)
            }
        }
        root.siteImportStatus = String(reply.summary || reply.reason || state)
        root.liveAidEvidenceSummary = root.siteImportStatus
    }

    function startSiteJob(kind, source) {
        var host = root.scratchHost()
        if (!host || !host.siteStart)
            return false
        if (root.siteImportBusy)
            return true
        try {
            var reply = JSON.parse(String(host.siteStart(kind, source)))
            root.siteJobKind = kind
            root.applySiteJobReply(reply)
        } catch (error) {
            root.siteImportStatus = "FAIL: SITE job could not start"
        }
        return true
    }

    function pollSiteJob() {
        var host = root.scratchHost()
        if (!host || !host.siteStatus)
            return
        try {
            var reply = JSON.parse(String(host.siteStatus(root.siteJobId)))
            if (reply.job_id && String(reply.job_id) !== root.siteJobId)
                return
            root.applySiteJobReply(reply)
        } catch (error) {
            root.siteImportStatus = "SITE · waiting for job status"
        }
    }

    function cancelSiteJob() {
        var host = root.scratchHost()
        if (host && host.siteCancel && root.siteImportBusy) {
            try { root.applySiteJobReply(JSON.parse(String(host.siteCancel(root.siteJobId)))) }
            catch (error) { root.siteImportStatus = "SITE · cancellation status unavailable" }
        }
    }

    function importSiteSqlFromDialog(urlString) {
        if (root.startSiteJob("SQL", urlString))
            return
        var host = root.scratchHost()
        if (host === null)
            return
        root.siteImportStatus = "IMPORT SQL · starting"
        var result = host.importSiteSql(urlString)
        root.siteImportStatus = String(result)
        root.liveAidEvidenceSummary = String(result)
    }

    function importSiteFromDialog(urlString) {
        if (root.startSiteJob("TREE", urlString))
            return
        var host = root.scratchHost()
        if (host === null)
            return
        root.siteImportStatus = "IMPORT · starting"
        var result = host.importSite(urlString)
        root.siteImportStatus = String(result)
        root.refreshSiteFiles()
        if (String(result).indexOf("PASS") === 0) {
            var preview = host.preferredSiteFile()
            if (preview.length > 0)
                root.openSiteFile(preview)
            else if (siteFileModel.count > 0)
                root.openSiteFile(siteFileModel.get(0).path)
            root.sitePreviewNonce = root.sitePreviewNonce + 1
        }
        root.liveAidEvidenceSummary = String(result)
    }

    function saveSiteBuffer() {
        if (root.siteImportBusy)
            return false
        var host = root.scratchHost()
        if (host === null)
            return false
        var saved = host.writeSiteFile(
            root.siteRelativePath,
            codeEditor.text
        )
        if (!saved)
            return false
        root.editorBaseText = codeEditor.text
        root.editorDirty = false
        root.clearExternalChange()
        root.editorFeedbackState = "SAVED"
        root.liveAidEvidenceSummary = "SAVED · site:" + root.siteRelativePath
        if (root.sitePreviewRunning) {
            root.sitePreviewNonce = root.sitePreviewNonce + 1
            root.siteImportStatus = "SAVED · " + root.siteRelativePath + " · preview reload"
        } else {
            root.webPageUrl = host.siteFileUrl(root.siteRelativePath)
            root.siteImportStatus = "SAVED · " + root.siteRelativePath
        }
        return true
    }

    function applyChatCodeToCurrent(source) {
        var body = String(source || "")
        if (body.length === 0)
            return false
        if (root.currentObjectType !== "CODE_FILE")
            return false
        if (root.currentObjectProvenance !== "REAL_UI_STATE")
            return false
        root.editorLoaded = true
        codeEditor.text = body
        root.editorDirty = body !== root.editorBaseText
        return true
    }

    function openScratchBuffer() {
        var host = root.scratchHost()
        var name = root.scratchFileName()
        var body = ""
        if (host !== null && host.readScratchFile)
            body = host.readScratchFile(name)
        if (body.length === 0)
            body = root.slashCommandTemplate
        root.editorLoaded = false
        root.editorBaseText = body
        root.editorSourceName = name
        root.editorLanguage = "text"
        root.editorBaseSha256 = ""
        codeEditor.text = body
        root.editorDirty = false
        root.editorLoaded = true
        root.editorFeedbackState = "SYNCED"
        root.lastEditorCheck = "NOT RUN"
        root.updateEditorCursor()
        root.liveAidState = "IDLE"
        root.liveAidDiagnostics = []
        root.liveAidEvidenceSummary = "SCRATCH · " + name
        if (host !== null && host.watchLivePath)
            host.watchLivePath(
                host.saveScratchFile(
                    name,
                    root.stripSlashCommandTemplate(body)
                )
            )
    }

    function applyExternalFile(path, text, kind) {
        var p = String(path || "")
        var body = String(text || "")
        var k = String(kind || "")
        if (k === "site-dir") {
            root.refreshSiteFiles()
            if (
                root.currentObjectType === "CODE_FILE"
                && String(root.currentObjectId).indexOf("ws.site.file.") === 0
                && root.siteRelativePath.length > 0
            )
                root.openSiteFile(root.siteRelativePath)
            return
        }
        if (k === "scratch-dir") {
            if (
                root.currentObjectType === "CODE_FILE"
                && String(root.currentObjectId).indexOf("ws.file.scratch.") === 0
            )
                root.openScratchBuffer()
            return
        }
        if (
            k === "site"
            && p.length > 0
            && root.siteRelativePath.length > 0
            && p.indexOf(root.siteRelativePath) >= 0
        ) {
            root._applyingExternal = true
            root.editorLoaded = true
            codeEditor.text = body
            root.editorBaseText = body
            root.editorDirty = false
            root._applyingExternal = false
            root.editorFeedbackState = "SYNCED"
            root.lastEditorCheck = "STALE"
            root.updateEditorCursor()
            if (root.sitePreviewRunning)
                root.sitePreviewNonce = root.sitePreviewNonce + 1
            return
        }
        if (
            k === "scratch"
            && root.currentObjectType === "CODE_FILE"
            && String(root.currentObjectId).indexOf("ws.file.scratch.") === 0
            && (
                p.indexOf(root.scratchFileName()) >= 0
                || p.indexOf("untitled.txt") >= 0
            )
        ) {
            root._applyingExternal = true
            root.editorLoaded = true
            codeEditor.text = body
            root.editorBaseText = body
            root.editorDirty = false
            root._applyingExternal = false
            root.editorFeedbackState = "SYNCED"
            root.lastEditorCheck = "STALE"
            root.updateEditorCursor()
        }
    }

    function activate(index) {
        if (index < 0 || index >= workspaceObjects.count)
            return
        var item = workspaceObjects.get(index)
        if (
            root.currentIndex === index
            && root.currentObjectId === item.objectId
        ) {
            root.settingsOpen = false
            root.hostKind = root.hostKindForType(item.objectType)
            return
        }
        root.settingsOpen = false
        root.currentIndex = index
        root.currentObjectId = item.objectId
        root.currentObjectTitle = item.title
        root.currentObjectType = item.objectType
        root.currentObjectProvenance = item.provenanceClass
        root.currentObjectSourcePath = item.sourcePath
        root.hostKind = root.hostKindForType(item.objectType)
        root.activeObjectChanged(item.objectId, item.title)

        root.resetAuthoringBuffer()
        root.syncObjectActivities()

        if (
            item.objectType === "CODE_FILE"
            && item.provenanceClass === "REAL_UI_STATE"
        ) {
            if (String(item.sourcePath || "").length > 0)
                Qt.callLater(function() {
                    root.openSiteFile(item.sourcePath)
                })
            else
                Qt.callLater(root.openScratchBuffer)
            return
        }

        if (item.objectType === "SITE_PROJECT") {
            Qt.callLater(function() {
                root.refreshSiteFiles()
                var host = root.scratchHost()
                var preferred = host && host.preferredSiteFile
                    ? host.preferredSiteFile()
                    : ""
                var rel = preferred.length > 0
                    ? preferred
                    : (item.sourcePath.length > 0 ? item.sourcePath : "index.php")
                root.ensureSitePreview()
                root.openSiteFile(rel)
            })
            return
        }

        if (item.objectType === "WEBSITE") {
            var stored = String(item.sourcePath || "")
            if (stored.length === 0)
                stored = "about:blank"
            root.browseUrl = stored
            root.browseBarText = stored === "about:blank" ? "" : stored
            return
        }

        if (
            item.provenanceClass === "REAL_LOCAL_FILE"
            && root.liveAidBackend !== null
        ) {
            Qt.callLater(root.loadCurrentAuthoringBuffer)
        }
    }

    property bool _applyingExternal: false

    Component.onCompleted: {
        activate(0)
        root.refreshSiteFiles()
        root.applyCryptoWalletLabel()
        var host = root.scratchHost()
        if (host !== null && host.watchDesktopWorkspace)
            host.watchDesktopWorkspace()
        if (Window.window)
            sitePreviewFullscreenWindow.transientParent = Window.window
    }

    onLiveAidStateChanged: root.syncObjectActivities()
    onPreflightStateChanged: root.syncObjectActivities()
    onPostDraftStateChanged: root.syncObjectActivities()
    onRepairStateChanged: root.syncObjectActivities()
    onEditorDirtyChanged: root.syncObjectActivities()
    onCurrentObjectIdChanged: root.syncObjectActivities()
    onChatBusyChanged: root.syncObjectActivities()
    onEngineTargetChanged: root.syncObjectActivities()
    onSettingsOpenChanged: {
        if (root.settingsOpen)
            root.sitePreviewFullscreen = false
    }
    onSitePreviewRunningChanged: {
        if (!root.sitePreviewRunning)
            root.sitePreviewFullscreen = false
    }
    onSitePreviewFullscreenChanged: {
        if (root.sitePreviewFullscreen && root.sitePreviewRunning) {
            sitePreviewFullscreenWindow.showFullScreen()
            sitePreviewFullscreenWindow.requestActivate()
        } else {
            sitePreviewFullscreenWindow.hide()
        }
    }

    Timer {
        id: analysisTimer
        interval: 280
        repeat: false
        onTriggered: {
            if (root.liveFeedbackEnabled)
                root.requestLiveAidAnalysis()
        }
    }

    Timer {
        id: externalChangeTimer
        interval: 16
        repeat: false
        onTriggered: {
            if (root.externalChangePending && !root.editorDirty)
                root.applyQueuedExternalChange()
        }
    }

    Shortcut {
        sequence: "F5"
        enabled: root.codeAuthoringActive
        onActivated: root.runCodeCheck()
    }

    Shortcut {
        sequence: "Ctrl+S"
        enabled: root.codeAuthoringActive && root.codeSaveAvailable
        onActivated: root.saveCodeBuffer()
    }

    Shortcut {
        sequence: "Ctrl+Shift+L"
        enabled: root.codeAuthoringActive
        onActivated: {
            root.liveFeedbackEnabled = !root.liveFeedbackEnabled
            if (root.liveFeedbackEnabled)
                root.scheduleLiveAidAnalysis()
        }
    }

    Timer {
        id: webOpRetry
        interval: 80
        repeat: false
        onTriggered: root.flushPendingWebOp()
    }

    Timer {
        id: addrTypeTimer
        interval: 28
        repeat: true
        onTriggered: root._addrTick()
    }

    ParallelAnimation {
        id: chromeMove
        property var doneFn: null
        NumberAnimation {
            id: chromeXAnim
            target: root
            property: "chromeX"
            duration: 280
            easing.type: Easing.InOutCubic
        }
        NumberAnimation {
            id: chromeYAnim
            target: root
            property: "chromeY"
            duration: 280
            easing.type: Easing.InOutCubic
        }
        onStopped: {
            var fn = chromeMove.doneFn
            chromeMove.doneFn = null
            if (typeof fn === "function")
                fn()
        }
    }

    Rectangle {
        id: chromeRipple
        z: 51
        width: 8
        height: 8
        radius: 4
        visible: false
        color: "#00c8a97e"
        border.width: 2
        border.color: "#c8a97e"
        x: root.chromeX - width / 2
        y: root.chromeY - height / 2

        function play() {
            chromeRipple.visible = true
            chromeRippleAnim.start()
        }
    }

    SequentialAnimation {
        id: chromeRippleAnim
        ParallelAnimation {
            NumberAnimation {
                target: chromeRipple
                property: "width"
                from: 10
                to: 36
                duration: 180
            }
            NumberAnimation {
                target: chromeRipple
                property: "height"
                from: 10
                to: 36
                duration: 180
            }
            NumberAnimation {
                target: chromeRipple
                property: "opacity"
                from: 1
                to: 0
                duration: 180
            }
        }
        ScriptAction {
            script: {
                chromeRipple.visible = false
                chromeRipple.opacity = 1
                chromeRipple.width = 8
                chromeRipple.height = 8
            }
        }
    }

    onChromeXChanged: root.syncChromeDesk()
    onChromeYChanged: root.syncChromeDesk()
    onChromeOnChanged: root.syncChromeDesk()
    onChromeShapeChanged: root.syncChromeDesk()

    Timer {
        id: scratchLiveTimer
        interval: 220
        repeat: false
        onTriggered: {
            if (root._applyingExternal)
                return
            if (root.currentObjectType !== "CODE_FILE")
                return
            if (String(root.currentObjectId).indexOf("ws.file.scratch.") !== 0)
                return
            root.saveScratchBuffer()
        }
    }

    Connections {
        target: Window.window && Window.window.surfaceHost
            ? Window.window.surfaceHost
            : null
        ignoreUnknownSignals: true

        function onWorkspaceFileChanged(path, text, kind) {
            root.queueExternalFile(path, text, kind)
        }
    }

    Connections {
        target: root.liveAidBackend
        enabled: root.liveAidBackend !== null
        ignoreUnknownSignals: true

        function onResultReady(objectId, payloadJson) {
            if (objectId !== root.currentObjectId)
                return

            if (root.preflightState === "RUNNING")
                return

            var result = JSON.parse(payloadJson)

            if (
                root.liveAidAnalysisSourceText.length > 0
                && codeEditor.text !== root.liveAidAnalysisSourceText
            ) {
                root.liveAidState = "QUEUED"
                root.editorFeedbackState = "QUEUED"
                root.liveAidEvidenceSummary =
                    "LIVE AID RESULT STALE · BUFFER CHANGED"
                root.scheduleLiveAidAnalysis()
                return
            }

            root.liveAidState = result.status || "UNKNOWN"
            root.liveAidDiagnostics = result.diagnostics || []
            root.lastEditorCheck = "LIVE"
            root.editorFeedbackState = result.status || "UNKNOWN"
            root.liveAidEvidenceSummary =
                "EXECUTION READY · "
                + String(result.execution_ready).toUpperCase()
                + " · NETWORK " + (result.network_authority || "NONE")
        }

        function onAnalysisFailed(objectId, message) {
            if (objectId !== root.currentObjectId)
                return

            root.liveAidState = "BLOCKED"
            root.editorFeedbackState = "BLOCKED"
            root.lastEditorCheck = "ERROR"
            root.liveAidDiagnostics = []
            root.liveAidEvidenceSummary =
                "LIVE AID BRIDGE ERROR · " + message
        }

        function onPreflightReady(objectId, payloadJson) {
            if (objectId !== root.currentObjectId)
                return

            var result = JSON.parse(payloadJson)

            if (codeEditor.text !== root.preflightSourceText) {
                root.preflightState = "STALE"
                root.preflightReportSha256 = ""
                root.repairState = "STALE"
                root.repairProposalId = ""
                root.repairOldText = ""
                root.repairNewText = ""
                root.liveAidState = "QUEUED"
                root.editorFeedbackState = "QUEUED"
                root.liveAidDiagnostics = []
                root.liveAidEvidenceSummary =
                    "PREFLIGHT RESULT STALE · "
                    + "BUFFER CHANGED DURING CHECK"
                root.scheduleLiveAidAnalysis()
                return
            }

            root.preflightState = result.gate_status
            root.preflightReportSha256 =
                result.gate_report_sha256 || ""
            root.repairProposalId = ""
            root.repairSourceText = ""
            root.repairOldText = ""
            root.repairNewText = ""

            if (result.gate_status === "FAIL")
                root.repairState = "AVAILABLE"
            else
                root.repairState = "IDLE"

            root.liveAidState = result.status
            root.liveAidDiagnostics =
                result.diagnostics || []
            root.lastEditorCheck = result.gate_status
            root.editorFeedbackState = result.gate_status
            root.liveAidEvidenceSummary =
                "QML GATE " + result.gate_status
                + " · PROFILE BOUND · REPORT "
                + result.gate_report_sha256.substring(0, 12)
                + " · NO EXECUTION · DISK UNCHANGED"
        }

        function onPreflightFailed(objectId, message) {
            if (objectId !== root.currentObjectId)
                return

            if (codeEditor.text !== root.preflightSourceText) {
                root.preflightState = "STALE"
                root.preflightReportSha256 = ""
                root.repairState = "STALE"
                root.repairProposalId = ""
                root.repairOldText = ""
                root.repairNewText = ""
                root.liveAidState = "QUEUED"
                root.editorFeedbackState = "QUEUED"
                root.liveAidEvidenceSummary =
                    "PREFLIGHT FAILURE STALE · "
                    + "BUFFER CHANGED DURING CHECK"
                root.scheduleLiveAidAnalysis()
                return
            }

            root.preflightState = "BLOCKED"
            root.preflightReportSha256 = ""
            root.repairState = "BLOCKED"
            root.repairProposalId = ""
            root.repairOldText = ""
            root.repairNewText = ""
            root.liveAidState = "BLOCKED"
            root.editorFeedbackState = "BLOCKED"
            root.lastEditorCheck = "ERROR"
            root.liveAidDiagnostics = []
            root.liveAidEvidenceSummary =
                "QML PREFLIGHT HARNESS ERROR · " + message
        }

        function onRepairReady(objectId, payloadJson) {
            if (objectId !== root.currentObjectId)
                return

            var result = JSON.parse(payloadJson)

            if (codeEditor.text !== root.repairSourceText) {
                root.repairState = "STALE"
                root.repairProposalId = ""
                root.repairOldText = ""
                root.repairNewText = ""
                root.liveAidState = "QUEUED"
                root.liveAidEvidenceSummary =
                    "AI REPAIR PROPOSAL STALE · "
                    + "BUFFER CHANGED DURING MODEL RUN"
                root.scheduleLiveAidAnalysis()
                return
            }

            root.repairProposalId = result.proposal_id
            root.repairOldText = result.old_text
            root.repairNewText = result.new_text
            root.repairState = "READY"
            root.liveAidState = "WAITING_FOR_USER"
            root.liveAidEvidenceSummary =
                "AI PROPOSAL · UNTRUSTED · OLD: "
                + result.old_text
                + " → NEW: " + result.new_text
                + " · WHY " + result.why
                + " · APPLY REQUIRES CLICK"
        }

        function onRepairFailed(objectId, message) {
            if (objectId !== root.currentObjectId)
                return

            root.repairState = "BLOCKED"
            root.repairProposalId = ""
            root.repairOldText = ""
            root.repairNewText = ""
            root.liveAidState = "BLOCKED"
            root.liveAidEvidenceSummary =
                "AI REPAIR ERROR · " + message
        }

        function onRepairApplied(
            objectId,
            proposalId,
            candidateSource
        ) {
            if (objectId !== root.currentObjectId)
                return

            if (proposalId !== root.repairProposalId)
                return

            codeEditor.text = candidateSource

            root.repairState = "APPLIED"
            root.repairProposalId = ""
            root.repairOldText = ""
            root.repairNewText = ""
            root.preflightState = "STALE"
            root.preflightReportSha256 = ""
            root.liveAidState = "QUEUED"
            root.editorFeedbackState = "QUEUED"
            root.liveAidDiagnostics = []
            root.liveAidEvidenceSummary =
                "AI REPAIR APPLIED TO BUFFER ONLY · "
                + "PREFLIGHT REQUIRED · NO SAVE · NO EXECUTION"

            root.scheduleLiveAidAnalysis()
        }

        function onPostDraftEvent(
            objectId,
            payloadJson
        ) {
            if (objectId !== root.currentObjectId)
                return

            if (root.postDraftState === "STALE")
                return

            if (codeEditor.text !== root.postDraftSourceText) {
                root.postDraftState = "STALE"
                root.liveAidState = "QUEUED"
                root.liveAidDiagnostics = []
                root.liveAidEvidenceSummary =
                    "POST-DRAFT RESULT STALE · "
                    + "BUFFER CHANGED DURING AUTOMATIC REPAIR · "
                    + "RESULT WILL NOT BE APPLIED"
                return
            }

            var event = JSON.parse(payloadJson)
            var name = event.event || "UNKNOWN"

            if (name === "DRAFT_COMPLETE") {
                root.postDraftState = "VERIFYING"
                root.liveAidState = "VERIFYING"
            } else if (name === "VERIFYING") {
                root.postDraftState = "VERIFYING"
                root.liveAidState = "VERIFYING"
            } else if (name === "REPAIRING") {
                root.postDraftState = "GENERATING"
                root.liveAidState = "GENERATING"
            } else if (name === "CANDIDATE_APPLIED_IN_MEMORY") {
                root.postDraftState = "REPAIRING"
                root.liveAidState = "REPAIRING"
            } else if (name === "PREFLIGHT_RESPONSE") {
                if (event.gate_status)
                    root.preflightState = event.gate_status

                if (event.gate_report_sha256) {
                    root.postDraftGateReportSha256 =
                        event.gate_report_sha256
                }
            } else if (name === "READY_TO_RUN") {
                root.postDraftState = "REPAIRING"
                root.liveAidState = "REPAIRING"
            } else if (name === "BLOCKED") {
                root.postDraftState = "BLOCKED"
                root.liveAidState = "BLOCKED"
            }

            root.liveAidEvidenceSummary =
                "POST-DRAFT · " + name
                + " · REPAIRS "
                + String(event.repair_attempts || 0)
                + " · MODEL DISPATCH "
                + String(event.model_dispatch_count || 0)
                + " · NO SAVE · NO EXECUTION"
        }

        function onPostDraftReady(
            objectId,
            payloadJson
        ) {
            if (objectId !== root.currentObjectId)
                return

            if (
                root.postDraftState === "STALE"
                || codeEditor.text !== root.postDraftSourceText
            ) {
                root.postDraftState = "STALE"
                root.liveAidState = "QUEUED"
                root.liveAidDiagnostics = []
                root.liveAidEvidenceSummary =
                    "POST-DRAFT VERIFIED RESULT DISCARDED · "
                    + "BUFFER CHANGED DURING RUN"
                root.scheduleLiveAidAnalysis()
                return
            }

            var result = JSON.parse(payloadJson)

            if (
                result.state !== "READY_TO_RUN"
                || result.execution_ready !== true
            ) {
                root.postDraftState = "BLOCKED"
                root.liveAidState = "BLOCKED"
                root.liveAidEvidenceSummary =
                    "POST-DRAFT BLOCKED · "
                    + (result.blocked_fault_layer || "UNKNOWN")
                    + " · "
                    + (result.blocked_reason || "no ready result")
                return
            }

            root.postDraftApplyingCandidate = true
            codeEditor.text = result.source
            root.postDraftApplyingCandidate = false

            root.postDraftSourceText = result.source
            root.postDraftState = "READY_TO_RUN"

            root.preflightState = "PASS"
            root.preflightSourceText = result.source
            root.preflightReportSha256 =
                root.postDraftGateReportSha256

            root.repairState = "IDLE"
            root.repairProposalId = ""
            root.repairSourceText = ""
            root.repairOldText = ""
            root.repairNewText = ""

            root.liveAidState = "READY_TO_RUN"
            root.liveAidDiagnostics = []
            root.liveAidEvidenceSummary =
                "POST-DRAFT AUTO REPAIR · READY TO RUN · "
                + "REPAIRS "
                + String(result.repair_attempts)
                + " · MODEL DISPATCH "
                + String(result.model_dispatch_count)
                + " · BUFFER ONLY · DISK UNCHANGED · "
                + "NO EXECUTION"
        }

        function onPostDraftFailed(
            objectId,
            message
        ) {
            if (objectId !== root.currentObjectId)
                return

            if (
                root.postDraftState === "STALE"
                || codeEditor.text !== root.postDraftSourceText
            ) {
                root.postDraftState = "STALE"
                root.liveAidState = "QUEUED"
                root.liveAidEvidenceSummary =
                    "POST-DRAFT FAILURE STALE · "
                    + "BUFFER CHANGED DURING RUN"
                root.scheduleLiveAidAnalysis()
                return
            }

            root.postDraftState = "BLOCKED"
            root.liveAidState = "BLOCKED"
            root.liveAidDiagnostics = []
            root.liveAidEvidenceSummary =
                "POST-DRAFT ASYNC ERROR · " + message
        }

    }

    Rectangle {
        z: 5
        anchors.left: tabs.left
        anchors.leftMargin: -6
        anchors.top: tabs.top
        width: tabs.width + 12
        height: 18
        color: "#161616"
        visible: tabs.width > 0
    }

    readonly property string frameKindLabel: root.settingsOpen
        ? "SETTINGS"
        : (root.hostKind === "GAME_ENGINE"
            ? "GAME ENGINE"
            : (root.hostKind === "NODES"
                ? "NODES"
                : (root.hostKind === "FLOW"
                    ? "FLOW"
                    : (root.hostKind === "RESEARCH"
                        ? "RESEARCH"
                        : String(root.hostKind || "")))))
    readonly property int tabStripLeft:
        root.frameKindLabel.length > 0
            ? (20 + root.frameKindLabel.length * 8)
            : 14

    Row {
        id: tabs
        z: 6
        anchors.left: parent.left
        anchors.leftMargin: root.tabStripLeft
        anchors.top: parent.top
        anchors.topMargin: -8
        height: 18
        spacing: 0

        Repeater {
            model: workspaceObjects

            delegate: Item {
                id: tabButton

                required property int index
                required property string objectId
                required property string title
                required property string objectType
                required property string activityState
                required property string provenanceClass

                readonly property bool kindMatch:
                    root.hostKindForType(tabButton.objectType) === root.hostKind
                readonly property bool tabVisible:
                    tabButton.kindMatch
                    && (
                        root.showDemoFixtures
                        || tabButton.provenanceClass
                            !== "SYNTHETIC_UI_FIXTURE"
                    )
                    && (
                        root.showProductSourceTabs
                        || tabButton.provenanceClass
                            !== "REAL_LOCAL_FILE"
                    )
                readonly property bool tabCurrent:
                    tabButton.index === root.currentIndex

                visible: tabButton.tabVisible
                width: visible
                    ? sepText.implicitWidth
                        + tabText.implicitWidth
                        + closeText.implicitWidth
                    : 0
                height: 18

                Text {
                    id: sepText
                    text: " | "
                    height: 18
                    verticalAlignment: Text.AlignVCenter
                    visible: {
                        if (!tabButton.tabVisible)
                            return false
                        for (var i = 0; i < tabButton.index; ++i) {
                            var prev = workspaceObjects.get(i)
                            if (
                                !root.objectVisibleForKind(
                                    prev,
                                    root.hostKind
                                )
                            )
                                continue
                            return true
                        }
                        return false
                    }
                    color: "#a8b0b8"
                    font.family: "monospace"
                    font.pixelSize: 12
                }

                Text {
                    id: tabText
                    anchors.left: sepText.visible ? sepText.right : parent.left
                    height: 18
                    verticalAlignment: Text.AlignVCenter
                    text: tabButton.title
                    color: tabButton.tabCurrent ? "#d8dee9" : "#a8b0b8"
                    font.family: "monospace"
                    font.pixelSize: 12
                    font.bold: tabButton.tabCurrent
                }

                Text {
                    id: closeText
                    objectName: "workspaceCloseInstanceButton"
                    z: 12
                    anchors.left: tabText.right
                    width: visible ? 14 : 0
                    height: 18
                    verticalAlignment: Text.AlignVCenter
                    text: " ×"
                    color: "#c8a97e"
                    font.family: "monospace"
                    font.pixelSize: 12
                    visible: root.isSpawnedObject(tabButton.objectId)
                        || (
                            tabButton.objectType === "WEBSITE"
                            && tabButton.provenanceClass === "REAL_UI_STATE"
                        )

                    MouseArea {
                        anchors.fill: parent
                        z: 13
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.closeHostInstance(tabButton.index)
                    }
                }

                MouseArea {
                    z: 1
                    anchors.fill: parent
                    anchors.rightMargin: closeText.visible
                        ? closeText.width
                        : 0
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.activate(tabButton.index)
                }
            }
        }

        Item {
            id: spawnInstanceButton
            objectName: "workspaceSpawnInstanceButton"
            visible: !root.settingsOpen
                && root.hostKind !== "CRYPTO"
                && root.hostKind !== "MARKETPLACE"
                && root.hostKind !== "TMOG"
                && root.hostKind !== "OSINT"
                && root.hostKind !== "QIP"
                && root.hostKind !== "MEDIA"
                && root.hostKind !== "DRAW"
                && root.hostKind !== "EXTERNAL"
                && root.hostKind !== "GAME_ENGINE"
                && root.hostKind !== "RESEARCH"
            width: visible ? spawnTabRow.width : 0
            height: 18

            Row {
                id: spawnTabRow
                spacing: 0

                Text {
                    text: " | "
                    color: "#a8b0b8"
                    font.family: "monospace"
                    font.pixelSize: 12
                }

                Text {
                    text: "+"
                    color: "#c8cdd4"
                    font.family: "monospace"
                    font.pixelSize: 12
                }
            }

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.spawnHostInstance()
            }
        }

        Item {
            visible: root.settingsOpen
            width: visible ? settingsTabRow.width : 0
            height: 18

            Row {
                id: settingsTabRow
                spacing: 0

                Text {
                    text: " | "
                    color: "#a8b0b8"
                    font.family: "monospace"
                    font.pixelSize: 12
                }

                Text {
                    text: "Settings"
                    color: "#d8dee9"
                    font.family: "monospace"
                    font.pixelSize: 12
                    font.bold: true
                }

                Text {
                    objectName: "settingsTabCloseButton"
                    text: " ×"
                    color: "#c8cdd4"
                    font.family: "monospace"
                    font.pixelSize: 12

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.closeSettings()
                    }
                }
            }
        }
    }

    Item {
        id: codeActions
        objectName: "workspaceSaveScratchRow"
        z: 6
        visible:
            !root.settingsOpen
            && root.hostKind === "CODE"
            && root.currentObjectProvenance === "REAL_UI_STATE"
            && root.currentObjectType === "CODE_FILE"
        anchors.right: parent.right
        anchors.rightMargin: 88
        anchors.top: parent.top
        anchors.topMargin: -8
        height: 18
        width: scratchSaveRow.implicitWidth + 12

        Rectangle {
            anchors.fill: parent
            color: "#161616"
        }

        Row {
            id: scratchSaveRow
            anchors.centerIn: parent
            spacing: 10

            Text {
                height: 18
                verticalAlignment: Text.AlignVCenter
                text: root.editorDirty ? "SAVE" : "SAVED"
                color: "#c8cdd4"
                font.family: "monospace"
                font.pixelSize: 12
                font.bold: true

                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.saveScratchBuffer()
                }
            }

            Text {
                objectName: "workspaceSaveScratchButton"
                height: 18
                verticalAlignment: Text.AlignVCenter
                text: "SAVE AS"
                color: "#c8cdd4"
                font.family: "monospace"
                font.pixelSize: 12
                font.bold: true

                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.openSaveAsDialog()
                }
            }
        }
    }

    GgFrame {
        id: workspaceFrame
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 8
        leftLegend: root.frameKindLabel
        busy: root.chatBusy
            || root.liveAidState === "QUEUED"
            || root.liveAidState === "RUNNING"
            || root.liveAidState === "PREFLIGHT"
            || root.liveAidState === "GENERATING"
            || root.liveAidState === "VERIFYING"
            || root.postDraftBusy
            || String(root.siteImportStatus).indexOf("IMPORT") === 0
        rightLegend: root.chatBusy
            ? (
                root.engineTarget === "GROK_WORKER"
                    ? "STREAMING"
                    : "GENERATING"
            )
            : (root.hostKind === "CRYPTO"
                ? ((cryptoPane.item && cryptoPane.item.legend) || "TESTNET")
                : (root.hostKind === "MARKETPLACE"
                    ? ((marketplacePane.item && marketplacePane.item.legend) || "TESTNET")
                    : (root.hostKind === "GAME_ENGINE"
                        ? ((gameEnginePane.item && gameEnginePane.item.legend)
                            || "LOCAL · FIXED 60 HZ")
                        : (
                            root.currentObjectTitle.length > 0
                                ? "@current"
                                : "@workspace"
                        ))))
        bottomLeftLegend: ""
        bottomRightLegend: root.editorDirty
            ? (
                root.currentObjectProvenance === "REAL_LOCAL_FILE"
                    ? "BUFFER · UNSAVED · DISK UNCHANGED"
                    : "BUFFER · UNSAVED"
            )
            : (
                root.hostKind === "CODE"
                    ? "BUFFER · DISK BASE"
                    : "DISK BASE"
            )
        backgroundColor: "#161616"
        borderColor: root.frameBorder
        radius: root.frameRadius

        Flow {
            id: objectNodeRail
            objectName: "workspaceObjectNodeRail"
            width: parent.width
            spacing: 8
            visible: false
            height: 0

            Repeater {
                model: workspaceObjects

                delegate: Item {
                    id: objectNodeWrap
                    objectName: "workspaceObjectNodeWrap"

                    required property int index
                    required property string objectId
                    required property string title
                    required property string objectType
                    required property string provenanceClass
                    required property string sourcePath
                    required property string activityState

                    width: 0
                    height: 0

                    WorkspaceObjectNode {
                        id: objectNode
                        width: objectNodeWrap.width
                        height: objectNodeWrap.height
                        objectId: objectNodeWrap.objectId
                        title: objectNodeWrap.title
                        objectType: objectNodeWrap.objectType
                        provenanceClass: objectNodeWrap.provenanceClass
                        sourcePath: objectNodeWrap.sourcePath
                        activityState: objectNodeWrap.activityState
                        current:
                            objectNodeWrap.index === root.currentIndex
                        editorDirty:
                            objectNode.current
                            && root.editorDirty
                            && objectNodeWrap.provenanceClass
                                === "REAL_LOCAL_FILE"
                        accentColor: root.accentColor
                        onActivated: function(value) {
                            root.focusObject(value)
                        }
                    }
                }
            }
        }

        Item {
            width: parent.width
            height: Math.max(
                160,
                root.height - 44
            )

            Row {
                id: authoringSurface
                anchors.fill: parent
                spacing: 10
                visible:
                    !root.settingsOpen
                    && root.hostKind !== "CRYPTO"
                    && root.hostKind !== "MARKETPLACE"
                    && root.hostKind !== "TMOG"
                    && root.hostKind !== "OSINT"
                    && root.hostKind !== "QIP"
                    && root.hostKind !== "MEDIA"
                    && root.hostKind !== "DRAW"
                    && root.hostKind !== "EXTERNAL"
                    && root.hostKind !== "GAME_ENGINE"
                    && root.hostKind !== "RESEARCH"
                    && root.hostKind !== "NODES"
                    && root.hostKind !== "FLOW"
                    && (
                        root.currentObjectProvenance === "REAL_LOCAL_FILE"
                        || (
                            root.currentObjectType === "CODE_FILE"
                            && root.currentObjectProvenance === "REAL_UI_STATE"
                        )
                    )

                Item {
                    id: codeHost
                    width: authoringSurface.width
                    height: authoringSurface.height

                    CodeRunnerBar {
                        id: codeRunnerBar
                        objectName: "workspaceCodeRunnerBar"
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.leftMargin: 2
                        anchors.rightMargin: 2
                        anchors.topMargin: 2
                        editorLoaded: root.editorLoaded
                        editorDirty: root.editorDirty
                        canSave: root.codeSaveAvailable
                        sourceName: root.editorSourceName
                        language: root.editorLanguage
                        liveAidState: root.liveAidState
                        diagnostics: root.liveAidDiagnostics
                        evidenceSummary: root.liveAidEvidenceSummary
                        preflightState: root.preflightState
                        repairState: root.repairState
                        liveFeedbackEnabled: root.liveFeedbackEnabled
                        externalChangePending: root.externalChangePending
                        externalChangePath: root.externalChangePath
                        externalChangeKind: root.externalChangeKind
                        cursorLine: root.editorLine
                        cursorColumn: root.editorColumn
                        editorRevision: root.editorRevision

                        onRunRequested: root.runCodeCheck()
                        onSaveRequested: root.saveCodeBuffer()
                        onToggleLiveFeedbackRequested: function(enabled) {
                            root.liveFeedbackEnabled = enabled
                            if (enabled)
                                root.scheduleLiveAidAnalysis()
                        }
                        onRepairRequested: root.requestLiveAidRepair()
                        onApplyRepairRequested: root.requestApplyRepair()
                        onSyncExternalRequested: root.applyQueuedExternalChange()
                        onKeepExternalRequested: root.keepExternalBuffer()
                    }

                    ScrollView {
                        id: codeScroll
                        objectName: "workspaceCodeScroll"
                        anchors.fill: parent
                        anchors.leftMargin: 2
                        anchors.rightMargin: 2
                        anchors.topMargin: codeRunnerBar.implicitHeight + 6
                        anchors.bottomMargin: 8
                        clip: true
                        ScrollBar.horizontal: GgScrollBar {}
                        ScrollBar.vertical: GgScrollBar {}

                        TextArea {
                            id: codeEditor
                            objectName: "workspaceCodeEditor"
                            enabled: root.editorLoaded
                            readOnly: false
                            selectByMouse: true
                            selectByKeyboard: true
                            persistentSelection: true
                            textFormat: TextEdit.PlainText
                            wrapMode: TextEdit.NoWrap
                            color: "#e6e6e6"
                            selectionColor: "#3a3a3a"
                            selectedTextColor: "#f2f2f2"
                            font.family: "monospace"
                            font.pixelSize: 12
                            leftPadding: 12
                            rightPadding: 12
                            topPadding: 8
                            bottomPadding: 12

                            SelectionGuard {
                                editor: codeEditor
                            }

                            Keys.onPressed: function(event) {
                                if (event.key !== Qt.Key_Tab)
                                    return
                                var start = codeEditor.selectionStart
                                var end = codeEditor.selectionEnd
                                if (start === end)
                                    return
                                var from = Math.min(start, end)
                                var to = Math.max(start, end)
                                var text = codeEditor.text
                                var lineStart = text.lastIndexOf("\n", Math.max(0, from - 1)) + 1
                                var block = text.slice(lineStart, to)
                                var indented
                                if (event.modifiers & Qt.ShiftModifier)
                                    indented = block.replace(/^ {1,4}|\t/gm, "")
                                else
                                    indented = block.replace(/^/gm, "    ")
                                codeEditor.remove(lineStart, to)
                                codeEditor.insert(lineStart, indented)
                                codeEditor.select(lineStart, lineStart + indented.length)
                                event.accepted = true
                            }
                            implicitWidth: Math.max(
                                codeScroll.availableWidth,
                                contentWidth + 24
                            )
                            implicitHeight: Math.max(
                                codeScroll.availableHeight,
                                contentHeight + 20
                            )

                            background: Rectangle {
                                color: "#161616"
                                border.width: 0
                            }

                        onTextChanged: {
                            if (!root.editorLoaded)
                                return

                            root.editorRevision += 1
                            root.updateEditorCursor()
                            root.editorDirty =
                                codeEditor.text !== root.editorBaseText
                            if (!root._applyingExternal) {
                                root.editorFeedbackState = "EDITING"
                                root.lastEditorCheck = "STALE"
                            }
                            if (
                                !root._applyingExternal
                                && String(root.currentObjectId).indexOf(
                                    "ws.file.scratch."
                                ) === 0
                            )
                                scratchLiveTimer.restart()

                            if (root.postDraftApplyingCandidate)
                                return

                            if (root.postDraftBusy) {
                                root.postDraftState = "STALE"
                                root.liveAidState = "QUEUED"
                                root.liveAidEvidenceSummary =
                                    "POST-DRAFT STALE · "
                                    + "BUFFER CHANGED DURING RUN · "
                                    + "RESULT WILL NOT BE APPLIED"
                                return
                            }

                            if (
                                root.postDraftState !== "IDLE"
                                && root.postDraftState !== "STALE"
                            ) {
                                root.postDraftState = "STALE"
                                root.postDraftGateReportSha256 = ""
                            }

                            if (root.preflightState !== "RUNNING") {
                                root.preflightState = "STALE"
                                root.preflightReportSha256 = ""
                            }

                            if (
                                root.repairState !== "RUNNING"
                                && root.repairState !== "IDLE"
                            ) {
                                root.repairState = "STALE"
                                root.repairProposalId = ""
                                root.repairOldText = ""
                                root.repairNewText = ""
                            }

                            root.liveAidState = "QUEUED"
                            root.scheduleLiveAidAnalysis()
                        }

                        onCursorPositionChanged: root.updateEditorCursor()
                        }
                    }
                }
            }

            SettingsSurface {
                id: settingsSurface
                anchors.fill: parent
                anchors.margins: 10
                visible: root.settingsOpen
                chatWidthRatio: root.chatWidthRatio
                telemetryWidth: root.telemetryWidth
                accentColor: root.accentColor
                frameBorder: root.frameBorder
                frameRadius: root.frameRadius
                showDemoFixtures: root.showDemoFixtures
                showProductSourceTabs: root.showProductSourceTabs
                showOpenTabInInput: root.showOpenTabInInput
                showInnerEditorChrome: root.showInnerEditorChrome
                hostKind: root.hostKind
                engineTarget: root.engineTarget
                utilityHeight: root.utilityHeight
                desktopShell: root.desktopShell

                onChatWidthRatioChangedByUser: function(value) {
                    root.chatWidthRatioRequested(value)
                }

                onTelemetryWidthChangedByUser: function(value) {
                    root.telemetryWidthRequested(value)
                }

                onAccentColorChangedByUser: function(value) {
                    root.accentColorRequested(value)
                }

                onFrameBorderChangedByUser: function(value) {
                    root.frameBorderRequested(value)
                }

                onFrameRadiusChangedByUser: function(value) {
                    root.frameRadiusRequested(value)
                }

                onDemoVisibilityChangedByUser: function(value) {
                    root.demoVisibilityRequested(value)
                }

                onProductSourceTabsChangedByUser: function(value) {
                    root.showProductSourceTabs = value
                    root.productSourceTabsRequested(value)
                }

                onShowOpenTabInInputChangedByUser: function(value) {
                    root.showOpenTabInInputRequested(value)
                }

                onShowInnerEditorChromeChangedByUser: function(value) {
                    root.showInnerEditorChromeRequested(value)
                }

                onHostKindChangedByUser: function(value) {
                    root.setHostKind(value)
                }

                onSpawnInstanceRequested: root.spawnHostInstance()

                onEngineTargetChangedByUser: function(value) {
                    root.engineTargetRequested(value)
                }

                onUtilityHeightChangedByUser: function(value) {
                    root.utilityHeightRequested(value)
                }

                onDesktopShellChangedByUser: function(value) {
                    root.desktopShellRequested(value)
                }

                onCloseRequested: root.closeSettings()
            }

            Item {
                id: siteHost
                objectName: "workspaceSiteHost"
                anchors.fill: parent
                anchors.margins: 10
                visible:
                    !root.settingsOpen
                    && root.hostKind === "SITE"
                    && root.currentObjectType === "SITE_PROJECT"

                FileDialog {
                    id: siteZipDialog
                    fileMode: FileDialog.OpenFile
                    nameFilters: ["Zip (*.zip)"]
                    onAccepted: root.importSiteFromDialog(
                        String(siteZipDialog.selectedFile)
                    )
                }

                FileDialog {
                    id: siteSqlDialog
                    fileMode: FileDialog.OpenFile
                    nameFilters: ["SQL (*.sql)"]
                    onAccepted: root.importSiteSqlFromDialog(
                        String(siteSqlDialog.selectedFile)
                    )
                }

                FolderDialog {
                    id: siteFolderDialog
                    onAccepted: root.importSiteFromDialog(
                        String(siteFolderDialog.selectedFolder)
                    )
                }

                Connections {
                    target: Window.window && Window.window.surfaceHost
                        ? Window.window.surfaceHost
                        : null
                    ignoreUnknownSignals: true

                    function onSiteImportProgress(phase, current, total, extra) {
                        if (String(phase) === "JOB_STARTED") {
                            try { root.applySiteJobReply(JSON.parse(String(extra))) }
                            catch (error) { root.siteImportStatus = "FAIL: SITE job status unavailable" }
                            return
                        }
                        var line = String(phase)
                        if (Number(total) > 0)
                            line += " · " + String(current) + "/" + String(total)
                        if (String(extra).length > 0)
                            line += " · " + String(extra)
                        root.siteImportStatus = line
                    }
                }

                Text {
                    objectName: "workspaceSiteImportStatus"
                    z: 8
                    anchors.left: parent.left
                    anchors.right: siteImportBar.left
                    anchors.rightMargin: 12
                    anchors.top: parent.top
                    height: 18
                    text: root.siteImportStatus
                    textFormat: Text.PlainText
                    color: root.siteImportStatus.indexOf("FAIL") === 0
                        || root.siteImportStatus.indexOf("PARTIAL") === 0
                        ? "#c98989"
                        : "#8b949e"
                    font.family: "monospace"
                    font.pixelSize: 12
                    elide: Text.ElideMiddle
                }

                Row {
                    id: siteImportBar
                    objectName: "workspaceSiteImportBar"
                    z: 8
                    spacing: 12
                    anchors.top: parent.top
                    anchors.right: parent.right
                    height: 18

                    Text {
                        text: "EDIT IN CODE"
                        color: "#c8a97e"
                        font.family: "monospace"
                        font.pixelSize: 12
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.setHostKind("CODE")
                        }
                    }

                    Text {
                        text: root.sitePreviewRunning ? "STOP PREVIEW" : "PREVIEW"
                        color: root.sitePreviewRunning ? "#d8dee9" : "#c8a97e"
                        font.family: "monospace"
                        font.pixelSize: 12
                        font.bold: root.sitePreviewRunning
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.toggleSitePreview()
                        }
                    }

                    Text {
                        objectName: "workspaceSiteFullscreenButton"
                        text: root.sitePreviewFullscreen
                            ? "EXIT FULLSCREEN"
                            : "FULLSCREEN"
                        color: root.sitePreviewFullscreen
                            ? "#d8dee9"
                            : "#c8a97e"
                        opacity: root.sitePreviewRunning ? 1.0 : 0.55
                        font.family: "monospace"
                        font.pixelSize: 12
                        font.bold: root.sitePreviewFullscreen
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.toggleSitePreviewFullscreen()
                        }
                    }

                    Text {
                        text: "IMPORT SQL"
                        color: "#c8a97e"
                        font.family: "monospace"
                        font.pixelSize: 12
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            enabled: !root.siteImportBusy
                            onClicked: siteSqlDialog.open()
                        }
                    }

                    Text {
                        text: "IMPORT ZIP"
                        color: "#c8a97e"
                        font.family: "monospace"
                        font.pixelSize: 12
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            enabled: !root.siteImportBusy
                            onClicked: siteZipDialog.open()
                        }
                    }

                    Text {
                        text: "IMPORT FOLDER"
                        color: "#c8a97e"
                        font.family: "monospace"
                        font.pixelSize: 12
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            enabled: !root.siteImportBusy
                            onClicked: siteFolderDialog.open()
                        }
                    }

                    Text {
                        objectName: "workspaceSiteHealthButton"
                        text: root.siteImportBusy ? "CANCEL" : "CHECK PHP"
                        color: "#c8a97e"
                        font.family: "monospace"
                        font.pixelSize: 12
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.siteImportBusy ? root.cancelSiteJob() : root.startSiteJob("HEALTH", "")
                        }
                    }
                }

                Text {
                    objectName: "workspaceSiteHealthStatus"
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.topMargin: 21
                    height: 18
                    text: root.siteHealthSummary + (root.siteHealthDetail.length ? " · " + root.siteHealthDetail : "")
                    textFormat: Text.PlainText
                    font.family: "monospace"
                    font.pixelSize: 11
                    color: "#8b949e"
                    elide: Text.ElideRight
                }

                Row {
                    id: siteVersionRow
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.topMargin: 43
                    spacing: 8
                    height: 20
                    TextField {
                        id: siteVersionInput
                        objectName: "workspaceSitePhpVersionInput"
                        width: 180
                        height: 20
                        font.family: "monospace"
                        font.pixelSize: 11
                        placeholderText: "PHP version / vendor revision"
                        color: "#d8dee9"
                        selectByMouse: true
                        maximumLength: 100
                        topPadding: 0
                        bottomPadding: 0
                        background: Rectangle { color: "#161616"; border.color: "#454545" }
                        onAccepted: root.assessSitePhpVersion(text)
                    }
                    Text {
                        objectName: "workspaceSitePhpVersionAssess"
                        text: "ASSESS"
                        color: "#c8a97e"
                        font.family: "monospace"
                        font.pixelSize: 11
                        height: 20
                        verticalAlignment: Text.AlignVCenter
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.assessSitePhpVersion(siteVersionInput.text)
                        }
                    }
                }
                Text {
                    objectName: "workspaceSitePhpVersionResult"
                    anchors.left: siteVersionRow.right
                    anchors.leftMargin: 12
                    anchors.right: parent.right
                    anchors.top: siteVersionRow.top
                    height: 20
                    text: root.siteVersionSummary
                    textFormat: Text.PlainText
                    font.family: "monospace"
                    font.pixelSize: 11
                    color: "#8b949e"
                    elide: Text.ElideRight
                    verticalAlignment: Text.AlignVCenter
                }

                Loader {
                    anchors.fill: parent
                    anchors.topMargin: 68
                    active: siteHost.visible && !root.sitePreviewFullscreen
                    source: active ? root.webPaneSource : ""
                    onLoaded: {
                        item.siteOnly = true
                        item.pageUrl = Qt.binding(function() {
                            return root.webPageUrl
                        })
                        item.reloadNonce = Qt.binding(function() {
                            return root.sitePreviewNonce
                        })
                        item.wantEngine = siteHost.visible
                        if (root.sitePreviewRunning)
                            root.applySitePreviewUrl()
                    }
                }

                Window {
                    id: sitePreviewFullscreenWindow
                    objectName: "sitePreviewFullscreenWindow"
                    color: "#161616"
                    flags: Qt.FramelessWindowHint
                    visible: false
                    title: "SITE PREVIEW"
                    onClosing: root.exitSitePreviewFullscreen()

                    Loader {
                        id: sitePreviewFullscreenLoader
                        objectName: "sitePreviewFullscreenLoader"
                        anchors.fill: parent
                        active: root.sitePreviewFullscreen
                        source: active ? root.webPaneSource : ""
                        onLoaded: {
                            item.siteOnly = true
                            item.pageUrl = Qt.binding(function() {
                                return root.webPageUrl
                            })
                            item.reloadNonce = Qt.binding(function() {
                                return root.sitePreviewNonce
                            })
                            item.wantEngine = sitePreviewFullscreenWindow.visible
                        }
                    }

                    MouseArea {
                        id: sitePreviewFullscreenHoverZone
                        objectName: "sitePreviewFullscreenHoverZone"
                        anchors.right: parent.right
                        anchors.top: parent.top
                        width: Math.min(parent.width, 280)
                        height: 78
                        hoverEnabled: true
                        acceptedButtons: Qt.NoButton
                        z: 10
                    }

                    Rectangle {
                        id: sitePreviewFullscreenExitButton
                        objectName: "sitePreviewFullscreenExitButton"
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 18
                        width: sitePreviewFullscreenExitLabel.implicitWidth + 18
                        height: 24
                        radius: 2
                        color: sitePreviewFullscreenExitMouse.containsMouse
                            ? "#303030"
                            : "#181818"
                        opacity: sitePreviewFullscreenHoverZone.containsMouse
                            || sitePreviewFullscreenExitMouse.containsMouse
                            ? 1.0
                            : 0.0
                        border.color: "#6a6a6a"
                        border.width: 1
                        z: 11

                        Behavior on opacity {
                            NumberAnimation { duration: 140 }
                        }

                        Text {
                            id: sitePreviewFullscreenExitLabel
                            anchors.centerIn: parent
                            text: "EXIT FULLSCREEN"
                            color: "#e6edf3"
                            font.family: "monospace"
                            font.pixelSize: 11
                            font.bold: true
                        }

                        MouseArea {
                            id: sitePreviewFullscreenExitMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.exitSitePreviewFullscreen()
                        }
                    }

                    Shortcut {
                        sequence: "Escape"
                        onActivated: root.exitSitePreviewFullscreen()
                    }

                    Keys.onPressed: function(event) {
                        if (event.key === Qt.Key_Escape) {
                            root.exitSitePreviewFullscreen()
                            event.accepted = true
                        }
                    }
                }
            }

            Loader {
                id: cryptoPane
                objectName: "workspaceCryptoPane"
                z: 20
                anchors.fill: parent
                anchors.bottomMargin: 18
                active: !root.settingsOpen && root.hostKind === "CRYPTO"
                visible: active
                sourceComponent: Component {
                    CryptoSurface {
                        objectName: "workspaceCryptoPane"
                        surfaceHost: root.scratchHost()
                        frameBorder: root.frameBorder
                        frameRadius: root.frameRadius
                        onWalletLabelChanged: function(label) {
                            root.cryptoWalletLabel = label
                            var win = Window.window
                            if (win)
                                win.cryptoStatusJson = cryptoPane.item
                                    ? cryptoPane.item.statusJson
                                    : win.cryptoStatusJson
                        }
                    }
                }
            }

            Loader {
                id: marketplacePane
                objectName: "workspaceMarketplacePane"
                z: 20
                anchors.fill: parent
                anchors.bottomMargin: 18
                active: !root.settingsOpen && root.hostKind === "MARKETPLACE"
                visible: active
                sourceComponent: Component {
                    MarketplaceSurface {
                        objectName: "workspaceMarketplacePane"
                        surfaceHost: root.scratchHost()
                        frameBorder: root.frameBorder
                        frameRadius: root.frameRadius
                    }
                }
            }

            Loader {
                id: tmogPane
                objectName: "workspaceTmogPane"
                z: 20
                anchors.fill: parent
                anchors.leftMargin: 2
                anchors.rightMargin: 4
                anchors.topMargin: 4
                anchors.bottomMargin: 18
                active: !root.settingsOpen && root.hostKind === "TMOG"
                visible: active
                sourceComponent: Component {
                    TmogSurface {
                        objectName: "workspaceTmogPane"
                        surfaceHost: root.scratchHost()
                        frameBorder: root.frameBorder
                        frameRadius: root.frameRadius
                    }
                }
            }

            Loader {
                id: osintPane
                objectName: "workspaceOsintPane"
                z: 20
                anchors.fill: parent
                anchors.leftMargin: 2
                anchors.rightMargin: 4
                anchors.topMargin: 4
                anchors.bottomMargin: 18
                active: !root.settingsOpen && root.hostKind === "OSINT"
                visible: !root.settingsOpen && root.hostKind === "OSINT"
                sourceComponent: Component {
                    OsintSurface {
                        objectName: "workspaceOsintPane"
                        surfaceHost: root.scratchHost()
                        frameBorder: root.frameBorder
                        frameRadius: root.frameRadius
                        onResearchRequested: function(section) { root.openResearch(section) }
                    }
                }
            }

            Loader {
                id: mediaPane
                objectName: "workspaceMediaPane"
                z: 20
                anchors.fill: parent
                active: !root.settingsOpen && root.hostKind === "MEDIA"
                visible: active
                sourceComponent: Component {
                    MediaSurface {
                        objectName: "workspaceMediaPane"
                        surfaceHost: root.scratchHost()
                        frameBorder: root.frameBorder
                        frameRadius: root.frameRadius
                    }
                }
            }

            Loader {
                id: drawPane
                objectName: "workspaceDrawPane"
                z: 20
                anchors.fill: parent
                active: !root.settingsOpen && root.hostKind === "DRAW"
                visible: active
                sourceComponent: Component {
                    DrawSurface {
                        objectName: "workspaceDrawPane"
                        surfaceHost: root.scratchHost()
                        frameBorder: root.frameBorder
                        frameRadius: root.frameRadius
                    }
                }
            }

            Loader {
                id: externalPane
                objectName: "workspaceExternalPane"
                z: 20
                anchors.fill: parent
                anchors.leftMargin: 2
                anchors.rightMargin: 4
                anchors.topMargin: 4
                anchors.bottomMargin: 18
                // Keep the pane alive when leaving EXT.  Destroying it used
                // to spawn a second Blender (default cube) because the sidecar
                // port was still held by the hidden first process.
                active: true
                visible: !root.settingsOpen && root.hostKind === "EXTERNAL"
                sourceComponent: Component {
                    ExternalSurface {
                        objectName: "workspaceExternalPane"
                        surfaceHost: root.scratchHost()
                        frameBorder: root.frameBorder
                        frameRadius: root.frameRadius
                    }
                }
            }

            Loader {
                id: gameEnginePane
                objectName: "workspaceGameEnginePane"
                z: 20
                anchors.fill: parent
                anchors.leftMargin: 2
                anchors.rightMargin: 4
                anchors.topMargin: 4
                anchors.bottomMargin: 18
                // Keep the playground alive after the first visit.  Tearing
                // the Loader down rebuilt every native mesh and RuntimeLoader
                // asset, which lagged the desktop and made props pop in.
                active: root.keepGameEngine || root.hostKind === "GAME_ENGINE"
                visible: !root.settingsOpen && root.hostKind === "GAME_ENGINE"
                sourceComponent: Component {
                    GameEngineSurface {
                        objectName: "workspaceGameEnginePane"
                        surfaceHost: root.scratchHost()
                        frameBorder: root.frameBorder
                        frameRadius: root.frameRadius
                        paneLive: gameEnginePane.visible
                    }
                }
            }

            Loader {
                id: nodePane
                objectName: "workspaceNodePane"
                z: 20
                anchors.fill: parent
                anchors.leftMargin: 2
                anchors.rightMargin: 4
                anchors.topMargin: 4
                anchors.bottomMargin: 18
                active: !root.settingsOpen && root.hostKind === "NODES"
                visible: active
                sourceComponent: Component {
                    NodeSurface {
                        objectName: "workspaceNodePane"
                        surfaceHost: root.scratchHost()
                        frameBorder: root.frameBorder
                        frameRadius: root.frameRadius
                    }
                }
            }

            Loader {
                id: agentFlowPane
                objectName: "workspaceAgentFlowPane"
                z: 20
                anchors.fill: parent
                anchors.leftMargin: 2
                anchors.rightMargin: 4
                anchors.topMargin: 4
                anchors.bottomMargin: 18
                active: !root.settingsOpen && root.hostKind === "FLOW"
                visible: active
                sourceComponent: Component {
                    AgentFlowSurface {
                        objectName: "workspaceAgentFlowPane"
                        surfaceHost: root.scratchHost()
                        frameBorder: root.frameBorder
                        frameRadius: root.frameRadius
                    }
                }
            }

            Loader {
                id: researchPane
                objectName: "workspaceResearchPane"
                z: 20
                anchors.fill: parent
                anchors.leftMargin: 2
                anchors.rightMargin: 4
                anchors.topMargin: 4
                anchors.bottomMargin: 18
                active: root.keepResearch || root.hostKind === "RESEARCH"
                visible: !root.settingsOpen && root.hostKind === "RESEARCH"
                sourceComponent: Component {
                    ResearchSurface {
                        objectName: "workspaceResearchPane"
                        surfaceHost: root.scratchHost()
                        frameBorder: root.frameBorder
                        frameRadius: root.frameRadius
                        onDocumentationRequested: function(url) { root.goBrowse(url) }
                    }
                }
                onLoaded: {
                    if (root.pendingResearchSection.length)
                        item.page = root.pendingResearchSection
                    root.pendingResearchSection = ""
                }
            }

            Item {
                id: webHost
                objectName: "workspaceWebHost"
                anchors.fill: parent
                anchors.margins: 10
                visible:
                    !root.settingsOpen
                    && root.hostKind === "WEB"
                    && root.currentObjectType === "WEBSITE"
                    && root.currentObjectProvenance === "REAL_UI_STATE"

                Repeater {
                    model: workspaceObjects

                    delegate: Item {
                        id: webTab
                        required property int index
                        required property string objectId
                        required property string objectType
                        required property string provenanceClass
                        required property string sourcePath

                        property bool holdWebEngine: false
                        readonly property bool isWebTab:
                            webTab.objectType === "WEBSITE"
                            && webTab.provenanceClass === "REAL_UI_STATE"
                        readonly property bool isCurrent:
                            webTab.objectId === root.currentObjectId

                        onIsCurrentChanged: {
                            if (webTab.isCurrent && webTab.isWebTab) {
                                webTab.holdWebEngine = true
                            } else if (webTab.isWebTab) {
                                if (webPaneLoader.item && webPaneLoader.item.haltEngine)
                                    webPaneLoader.item.haltEngine()
                                webTab.holdWebEngine = false
                            }
                            if (webTab.isCurrent) {
                                root.liveBrowseBar = tabBrowseBar
                                if (webPaneLoader.item)
                                    root.liveWebPane = webPaneLoader.item
                            }
                        }
                        Component.onCompleted: {
                            if (webTab.isCurrent && webTab.isWebTab)
                                webTab.holdWebEngine = true
                        }

                        anchors.fill: parent
                        visible: webTab.isWebTab
                        opacity: webTab.isCurrent ? 1 : 0
                        enabled: webTab.isCurrent
                        z: webTab.isCurrent ? 2 : 0

                        Column {
                            anchors.fill: parent
                            spacing: 6

                            Row {
                                id: webAddressRow
                                width: parent.width
                                height: 26
                                spacing: 6

                                GgField {
                                    id: tabBrowseBar
                                    objectName: "workspaceWebAddress"
                                    width: parent.width - (webBlocker.visible ? webBlocker.width + webBlockerSettings.width + 12 : 0)
                                    height: parent.height
                                    text: webTab.isCurrent && root.addressTyping
                                        ? root.addressDraft
                                        : (
                                            webTab.sourcePath === "about:blank"
                                                ? ""
                                                : webTab.sourcePath
                                        )
                                    placeholderText: "https://"
                                    onAccepted: root.goBrowse(tabBrowseBar.text)
                                }

                                GgButton {
                                    id: webBlocker
                                    objectName: "workspaceWebBlocker"
                                    width: 82
                                    height: parent.height
                                    readonly property bool engineReady: Boolean(webPaneLoader.item && webPaneLoader.item.blockerReady)
                                    readonly property bool pageIsWebsite: webTab.sourcePath.indexOf("http://") === 0
                                        || webTab.sourcePath.indexOf("https://") === 0
                                    visible: Boolean(webPaneLoader.item && webPaneLoader.item.blockerAvailable)
                                    enabled: engineReady && pageIsWebsite
                                    checked: Boolean(webPaneLoader.item && webPaneLoader.item.blockerEnabled)
                                    text: webPaneLoader.item && webPaneLoader.item.blockerError
                                        ? "uBO FEL"
                                        : (!engineReady ? "uBO ..." : (!pageIsWebsite ? "uBO" : (checked ? "uBO PÅ" : "uBO AV")))
                                    onClicked: webPaneLoader.item.toggleBlocker()
                                    HoverHandler { id: blockerHover }
                                    ToolTip.visible: blockerHover.hovered
                                    ToolTip.text: webPaneLoader.item && webPaneLoader.item.blockerError
                                        ? webPaneLoader.item.blockerError
                                        : "uBlock Origin · slå på eller av för den här webbplatsen"
                                }

                                GgButton {
                                    id: webBlockerSettings
                                    objectName: "workspaceWebBlockerSettings"
                                    width: 30
                                    height: parent.height
                                    visible: webBlocker.visible
                                    enabled: webBlocker.engineReady
                                    text: "⋯"
                                    onClicked: webPaneLoader.item.openBlockerSettings()
                                    HoverHandler { id: blockerSettingsHover }
                                    ToolTip.visible: blockerSettingsHover.hovered
                                    ToolTip.text: "uBlock Origin · filter och inställningar"
                                }
                            }

                            Loader {
                                id: webPaneLoader
                                width: parent.width
                                height: parent.height - tabBrowseBar.height - 6
                                active: webTab.isWebTab && webTab.holdWebEngine
                                source: active ? root.webPaneSource : ""
                                onLoaded: {
                                    item.siteOnly = false
                                    item.pageUrl = Qt.binding(function() {
                                        return webTab.sourcePath.length > 0
                                            ? webTab.sourcePath
                                            : "about:blank"
                                    })
                                    if (root.pendingAdoptedView && item.takeView) {
                                        item.takeView(root.pendingAdoptedView)
                                        root.pendingAdoptedView = null
                                    } else {
                                        item.wantEngine = true
                                    }
                                    if (webTab.isCurrent) {
                                        root.liveWebPane = item
                                        root.liveBrowseBar = tabBrowseBar
                                    }
                                    item.navigated.connect(function(href) {
                                        root.rememberBrowse(webTab.index, href)
                                    })
                                    item.openNewTab.connect(function(href) {
                                        root.openWebTab(href)
                                    })
                                    item.popupViewReady.connect(function(view) {
                                        root.adoptPopupView(view)
                                    })
                                    item.titled.connect(function(title) {
                                        var label = String(title || "").trim()
                                        if (label.length > 40)
                                            label = label.slice(0, 37) + "..."
                                        if (label.length > 0)
                                            workspaceObjects.setProperty(webTab.index, "title", label)
                                    })
                                    if (webTab.isCurrent)
                                        Qt.callLater(root.flushPendingWebOp)
                                }
                            }
                        }
                    }
                }
            }

            Item {
                id: userTerminalHost
                anchors.fill: parent
                anchors.margins: 10
                visible:
                    !root.settingsOpen
                    && root.hostKind === "TERMINAL"
                    && root.currentObjectType === "USER_TERMINAL"

                WorkObject {
                    anchors.fill: parent
                    fillHost: true
                    objectType: "TERMINAL"
                    title: root.currentObjectTitle
                    terminalId: root.currentObjectId
                    provenanceClass: "REAL_UI_STATE"
                    activityState: "RUNNING"
                    bodyText: ""
                    contextReference: "@current"
                }
            }

            Column {
                anchors.centerIn: parent
                width: Math.min(parent.width - 60, 560)
                spacing: 12
                visible:
                    !root.settingsOpen
                    && root.hostKind !== "CRYPTO"
                    && root.hostKind !== "MARKETPLACE"
                    && root.hostKind !== "TMOG"
                    && root.hostKind !== "OSINT"
                    && root.hostKind !== "QIP"
                    && root.hostKind !== "MEDIA"
                    && root.hostKind !== "DRAW"
                    && root.hostKind !== "EXTERNAL"
                    && root.hostKind !== "GAME_ENGINE"
                    && root.hostKind !== "RESEARCH"
                    && root.currentObjectProvenance === "SYNTHETIC_UI_FIXTURE"

                Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text: root.currentObjectTitle
                    color: "#e6edf3"
                    font.pixelSize: 22
                    font.bold: true
                }

                Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text: root.currentObjectType
                        + " · "
                        + root.currentObjectProvenance
                        + " · DEMO / SAMPLE"
                    color: "#c8a97e"
                    font.family: "monospace"
                    font.pixelSize: 12
                }

                Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text:
                        "Visual renderer/editor adapter is not connected "
                        + "for this SAMPLE object.\n"
                        + "Synthetic fixtures remain blocked from real "
                        + "@current context."
                    color: "#c8cdd4"
                    wrapMode: Text.WordWrap
                    font.pixelSize: 12
                }
            }
        }
    }

    Rectangle {
        z: 5
        anchors.left: hostKindFooter.left
        anchors.leftMargin: -6
        anchors.bottom: hostKindFooter.bottom
        width: hostKindFooter.width + 12
        height: 18
        color: "#161616"
        visible: hostKindFooter.width > 0
    }

    Row {
        id: hostKindFooter
        objectName: "workspaceHostKindSelector"
        z: 6
        anchors.left: parent.left
        anchors.leftMargin: 14
        anchors.bottom: workspaceFrame.bottom
        anchors.bottomMargin: -7
        height: 18
        spacing: 0

        Text {
            objectName: "workspaceKindCODE"
            text: "CODE"
            color: root.hostKind === "CODE" ? "#d8dee9" : "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: root.hostKind === "CODE"

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.setHostKind("CODE")
            }
        }

        Text {
            text: " | "
            color: "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
        }

        Text {
            objectName: "workspaceKindTERMINAL"
            text: "CMD"
            color: root.hostKind === "TERMINAL" ? "#d8dee9" : "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: root.hostKind === "TERMINAL"

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.setHostKind("TERMINAL")
            }
        }

        Text {
            text: " | "
            color: "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
        }

        Text {
            objectName: "workspaceKindWEB"
            text: "WEB"
            color: root.hostKind === "WEB" ? "#d8dee9" : "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: root.hostKind === "WEB"

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.setHostKind("WEB")
            }
        }

        Text {
            text: " | "
            color: "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
        }

        Text {
            text: "EXT"
            color: root.hostKind === "EXTERNAL" ? "#d8dee9" : "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: root.hostKind === "EXTERNAL"

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.setHostKind("EXTERNAL")
            }
        }

        Text {
            text: " | "
            color: "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
        }

        Text {
            objectName: "workspaceKindSITE"
            text: "SITE"
            color: root.hostKind === "SITE" ? "#d8dee9" : "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: root.hostKind === "SITE"

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.setHostKind("SITE")
            }
        }

        Text {
            text: " | "
            color: "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
        }

        Text {
            text: "CRYPTO"
            color: root.hostKind === "CRYPTO" ? "#d8dee9" : "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: root.hostKind === "CRYPTO"

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.setHostKind("CRYPTO")
            }
        }

        Text {
            text: " | "
            color: "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
        }

        Text {
            text: "MP"
            color: root.hostKind === "MARKETPLACE" ? "#d8dee9" : "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: root.hostKind === "MARKETPLACE"

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.setHostKind("MARKETPLACE")
            }
        }

        Text {
            text: " | "
            color: "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
        }

        Text {
            objectName: "workspaceKindTMOG"
            text: "TMOG"
            color: root.hostKind === "TMOG" ? "#d8dee9" : "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: root.hostKind === "TMOG"

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.setHostKind("TMOG")
            }
        }

        Text {
            text: " | "
            color: "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
        }

        Text {
            objectName: "workspaceKindOSINT"
            text: "OSINT"
            color: root.hostKind === "OSINT" ? "#d8dee9" : "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: root.hostKind === "OSINT"

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.setHostKind("OSINT")
            }
        }

        Text {
            text: " | "
            color: "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
        }

        Text {
            objectName: "workspaceKindResearch"
            text: "RESEARCH"
            color: root.hostKind === "RESEARCH" ? "#d8dee9" : "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: root.hostKind === "RESEARCH"

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.setHostKind("RESEARCH")
            }
        }

        Text {
            text: " | "
            color: "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
        }

        Text {
            text: "MEDIA"
            color: root.hostKind === "MEDIA" ? "#d8dee9" : "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: root.hostKind === "MEDIA"

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.setHostKind("MEDIA")
            }
        }

        Text {
            text: " | "
            color: "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
        }

        Text {
            text: "DRAW"
            color: root.hostKind === "DRAW" ? "#d8dee9" : "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: root.hostKind === "DRAW"

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.setHostKind("DRAW")
            }
        }

        Text {
            text: " | "
            color: "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
        }

        Text {
            objectName: "workspaceKindGameEngine"
            text: "GAME ENGINE"
            color: root.hostKind === "GAME_ENGINE" ? "#d8dee9" : "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: root.hostKind === "GAME_ENGINE"

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.setHostKind("GAME_ENGINE")
            }
        }

        Text {
            text: " | "
            color: "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
        }

        Text {
            objectName: "workspaceKindNodes"
            text: "NODES"
            color: root.hostKind === "NODES" ? "#d8dee9" : "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: root.hostKind === "NODES"

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.setHostKind("NODES")
            }
        }

        Text {
            text: " | "
            color: "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
        }

        Text {
            objectName: "workspaceKindFlow"
            text: "FLOW"
            color: root.hostKind === "FLOW" ? "#d8dee9" : "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: root.hostKind === "FLOW"

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.setHostKind("FLOW")
            }
        }

    }

    FileDialog {
        id: scratchSaveDialog
        title: "SAVE AS"
        fileMode: FileDialog.SaveFile
        nameFilters: [
            "Text (*.txt)",
            "JavaScript (*.js)",
            "QML (*.qml)",
            "Python (*.py)",
            "JSON (*.json)",
            "HTML (*.html)",
            "CSS (*.css)",
            "PHP (*.php)",
            "All files (*)"
        ]
        defaultSuffix: "txt"
        currentFolder: "file:///home/GG/.local/state/goldgoblins/gg-ai-desktop/scratch"
        onAccepted: root.applySaveAsUrl(
            String(scratchSaveDialog.selectedFile)
        )
    }
}
