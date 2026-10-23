pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Window
import "components"

ApplicationWindow {
    id: root

    property string workbenchVersion: "1.1"
    property string dataMode: "LOCAL_UI_ONLY"
    property string interactionModel: "GG_INTENT_NATIVE_DESKTOP"
    property string visualChangePolicy: "PROPOSE_PREVIEW_DISCUSS_APPROVE_APPLY"
    property string operatorTerminalPolicy: "FORBIDDEN"
    property string reasoningEvidencePolicy: "REQUIRED"
    property string liveAidDraftBlocking: "NO"
    property string shadowVerificationMode: "NOT_CONNECTED"

    property string narrowPane: "CHAT"
    property bool bridgeBusy: false
    property bool followChatTail: true
    property string activeTaskId: ""
    property string engineTarget: "GROK_TUI"
    property string lastSelectedObjectId: ""
    property real alphaChatWidthRatio: 0.31
    property int alphaTelemetryWidth: 168
    property int alphaUtilityHeight: 112
    property bool alphaShowDemoFixtures: false
    property bool showProductSourceTabs: false
    property var surfaceHost: null
    property var liveAidBackend: null
    readonly property var workspace: workspaceLoader.item
    property string grokWalletJson: "{}"
    property string gptWalletJson: "{}"
    readonly property string liveVisionStatusJson: root.surfaceHost && root.surfaceHost.liveVisionStatus !== undefined
                                                 ? root.surfaceHost.liveVisionStatus : '{"state":"off"}'
    readonly property var liveEyes: {
        try { return JSON.parse(root.liveVisionStatusJson) } catch (err) { return {state: "off"} }
    }
    property string cryptoStatusJson: "{}"
    property bool walletOpen: false
    property real walletX: -1
    property real walletY: -1
    property bool settingsOpen: false
    property real settingsX: -1
    property real settingsY: -1
    property bool settingsMoved: false
    // Presentation state is intentionally separate from the legacy desktop
    // settings above.  All engines and Settings use this same object.
    property var visualLayoutData: ({})
    property int visualLayoutRevision: 0
    property string visualThemeId: "obsidian-ledger"
    property string visualProfileId: "standard"
    property bool visualLayoutLocked: true
    property string visualEditorMode: "NORMAL"
    property string visualSelectedSurface: ""
    property string visualSourceText: ""
    property string visualSourcePath: ""
    property string visualSourceStatus: ""
    property bool visualStateReady: false
    // The registry is the workbench's contribution seam.  It is a JSON view
    // of code-owned manifests, never a path from which QML/Python is loaded.
    property string workbenchExtensionsJson: "[]"
    property bool commandPaletteOpen: false
    property string commandPaletteMode: "COMMAND"
    property var workspaceFolders: []
    property bool workspaceTrusted: true

    onSurfaceHostChanged: {
        root.pullCryptoStatus()
        root.applyDesktopShellNow()
        root.loadVisualLayoutState()
        root.loadWorkbenchExtensions()
    }

    onDesktopShellChanged: {
        root.persistDesktopSettings()
        root.applyDesktopShellNow()
    }

    onActiveChanged: {
        if (root.active && root.desktopShell)
            root.applyDesktopShellNow()
    }
    property string chatSessionsJson: "[]"
    property string activeChatSession: ""
    property bool shellLoading: true
    readonly property bool startupChatBlocking: Boolean(
        root.surfaceHost && root.surfaceHost.startupChatBlocking)
    property string shellLoadLabel: "STARTING DESKTOP..."
    property int shellLoadPercent: 0
    property string shellLoadCurrent: "Loading desktop modules and local services"
    property string shellLoadLog: ""
    property int startupServiceProgress: 0
    property int startupStepNumber: 0
    property int startupStepCount: 0
    property bool startupStepBusy: false
    property bool startupFailed: false
    property bool _initialStartupComplete: false
    property string shellLoadQueueJson: "[]"
    property bool startupModulesReady: false
    property bool _startupShellLoadRequested: false
    property bool startupReady: false
    property bool workspaceLoadFailed: false
    property var _shellQueue: []
    property int _shellQueueIndex: 0
    property var _shellComp: null
    property bool _workspaceLoaderReady: false
    property bool _utilityLoaderReady: false
    readonly property int alphaBottomStripMargin: 8

    property int shellNonce: 0
    property bool _shellHydrated: false
    property bool _utilityBound: false
    property bool _workspaceBound: false

    onStartupReadyChanged: {
        if (root.startupReady) {
            root.updateShellProgress()
            root.finishShellLoad()
        }
    }

    onStartupServiceProgressChanged: root.updateShellProgress()

    onStartupModulesReadyChanged: root.requestStartupShellLoad()

    function requestStartupShellLoad() {
        if (!root.startupModulesReady || root._startupShellLoadRequested)
            return
        root._startupShellLoadRequested = true
        root.beginShellLoad("LOADING...")
    }
    property real deskX: 420
    property real deskY: 240
    property string deskShape: "default"
    property bool deskFromChrome: false
    property bool deskGrabReady: false

    function grabDesk(path) {
        root.deskGrabReady = false
        var item = root.contentItem
        if (!item || !item.grabToImage) {
            root.deskGrabReady = false
            return false
        }
        item.grabToImage(function(result) {
            var ok = false
            try {
                ok = result.saveToFile(path)
            } catch (err) {
                ok = false
            }
            root.deskGrabReady = ok
        })
        return true
    }

    function setDeskCursor(item, lx, ly, shape) {
        if (!item)
            return
        var p = item.mapToItem(root.contentItem, Number(lx), Number(ly))
        root.deskX = p.x
        root.deskY = p.y
        if (shape && String(shape).length > 0)
            root.deskShape = String(shape)
    }

    function workspaceUrl() {
        return Qt.resolvedUrl("components/WorkspaceSurface.qml")
            + "?r=" + String(root.shellNonce)
    }

    function utilityUrl() {
        return Qt.resolvedUrl("components/UtilitySurface.qml")
            + "?r=" + String(root.shellNonce)
    }

    function unloadDesktopShell() {
        root.shellLoadPercent = 0
        root.shellLoadCurrent = ""
        root.shellLoadLog = ""
        root._shellQueue = []
        root._shellQueueIndex = 0
        root._shellComp = null
        root._workspaceLoaderReady = false
        root._utilityLoaderReady = false
        root.workspaceLoadFailed = false
        root._shellHydrated = false
        root._utilityBound = false
        root._workspaceBound = false
        workspaceLoader.source = ""
        utilitySurface.source = ""
    }

    function parseShellQueue() {
        var raw = root.shellLoadQueueJson
        if (root.surfaceHost && root.surfaceHost.shellLoadQueue)
            raw = root.surfaceHost.shellLoadQueue()
        var rows = []
        try {
            rows = JSON.parse(raw || "[]")
        } catch (err) {
            rows = []
        }
        if (!rows || !rows.length)
            return ["qml/components/WorkspaceSurface.qml"]
        return rows
    }

    function shellUrl(rel) {
        var path = String(rel || "")
        if (path.indexOf("qml/") === 0)
            path = path.slice(4)
        return Qt.resolvedUrl(path)
    }

    function appendShellLog(name) {
        var lines = root.shellLoadLog.length > 0
            ? root.shellLoadLog.split("\n")
            : []
        lines.push(name)
        if (lines.length > 12)
            lines = lines.slice(lines.length - 12)
        root.shellLoadLog = lines.join("\n")
    }

    function updateShellProgress() {
        if (!root._initialStartupComplete) {
            var assetTotal = Math.max(1, root._shellQueue.length + 2)
            var assetsComplete = Math.min(
                root._shellQueueIndex,
                root._shellQueue.length
            )
            if (root._workspaceLoaderReady)
                assetsComplete += 1
            if (root._utilityLoaderReady)
                assetsComplete += 1
            var assetProgress = assetsComplete / assetTotal
            var serviceProgress = Math.max(
                0,
                Math.min(100, root.startupServiceProgress)
            ) / 100
            root.shellLoadPercent = Math.min(99, Math.round(
                (assetProgress * 0.9 + serviceProgress * 0.1) * 100
            ))
            return
        }

        // Later manual reloads only recreate QML surfaces; local services are
        // already connected, so show the existing surface-load progress.
        var reloadTotal = Math.max(1, root._shellQueue.length + 2)
        var reloadComplete = Math.min(
            root._shellQueueIndex,
            root._shellQueue.length
        )
        if (root._workspaceLoaderReady)
            reloadComplete += 1
        if (root._utilityLoaderReady)
            reloadComplete += 1
        root.shellLoadPercent = Math.round(
            reloadComplete * 100 / reloadTotal
        )
    }

    function loadNextShellFile() {
        if (root._shellQueueIndex >= root._shellQueue.length) {
            root.updateShellProgress()
            root.loadDesktopShell()
            return
        }
        var rel = String(root._shellQueue[root._shellQueueIndex] || "")
        root.shellLoadCurrent = rel
        root.appendShellLog(rel)
        root.updateShellProgress()
        var comp = Qt.createComponent(
            root.shellUrl(rel),
            Component.Asynchronous
        )
        root._shellComp = comp
        if (!comp) {
            root.onShellCompFinished()
            return
        }
        if (comp.status === Component.Ready
            || comp.status === Component.Error)
            root.onShellCompFinished()
        else
            comp.statusChanged.connect(root.onShellCompFinished)
    }

    function onShellCompFinished() {
        var comp = root._shellComp
        if (comp && comp.status === Component.Loading)
            return
        if (comp) {
            if (comp.status === Component.Error)
                root.appendShellLog(String(comp.errorString() || "component error"))
            try {
                comp.statusChanged.disconnect(root.onShellCompFinished)
            } catch (err) {
            }
        }
        root._shellComp = null
        root._shellQueueIndex += 1
        root.updateShellProgress()
        Qt.callLater(root.loadNextShellFile)
    }

    function loadDesktopShell() {
        var rel = "qml/components/WorkspaceSurface.qml"
        root.shellLoadCurrent = rel
        root.appendShellLog(rel)
        root.appendShellLog("qml/components/UtilitySurface.qml")
        utilitySurface.setSource(root.utilityUrl())
        workspaceLoader.setSource(
            root.workspaceUrl(),
            { "shellNonce": root.shellNonce }
        )
    }

    function bindUtility(item) {
        if (!item || root._utilityBound)
            return
        root._utilityBound = true
        item.surfaceHost = Qt.binding(function() {
            return root.surfaceHost
        })
        item.accentColor = Qt.binding(function() {
            return root.cyan
        })
        item.frameBorder = Qt.binding(function() {
            return root.frameBorder
        })
        item.frameRadius = Qt.binding(function() {
            return root.frameRadius
        })
        item.surfaceHeight = Qt.binding(function() {
            return root.alphaUtilityHeight
        })
        item.surfaceRequested.connect(function(kind) {
            if (workspace)
                workspace.setHostKind(kind)
        })
    }

    function bindWorkspace(item) {
        if (!item || root._workspaceBound)
            return
        root._workspaceBound = true
        item.shellNonce = Qt.binding(function() {
            return root.shellNonce
        })
        item.showDemoFixtures = Qt.binding(function() {
            return root.alphaShowDemoFixtures
        })
        item.showProductSourceTabs = Qt.binding(function() {
            return root.showProductSourceTabs
        })
        item.chatWidthRatio = Qt.binding(function() {
            return root.alphaChatWidthRatio
        })
        item.telemetryWidth = Qt.binding(function() {
            return root.alphaTelemetryWidth
        })
        item.accentColor = Qt.binding(function() {
            return root.cyan
        })
        item.frameBorder = Qt.binding(function() {
            return root.frameBorder
        })
        item.frameRadius = Qt.binding(function() {
            return root.frameRadius
        })
        item.showOpenTabInInput = Qt.binding(function() {
            return root.showOpenTabInInput
        })
        item.showInnerEditorChrome = Qt.binding(function() {
            return root.showInnerEditorChrome
        })
        item.chatBusy = Qt.binding(function() {
            return root.bridgeBusy
        })
        item.engineTarget = Qt.binding(function() {
            return root.engineTarget
        })
        item.utilityHeight = Qt.binding(function() {
            return root.alphaUtilityHeight
        })
        item.desktopShell = Qt.binding(function() {
            return root.desktopShell
        })
        item.workbenchExtensionsJson = Qt.binding(function() {
            return root.workbenchExtensionsJson
        })
        item.liveAidBackend = Qt.binding(function() {
            return root.liveAidBackend
        })
        item.chatWidthRatioRequested.connect(function(value) {
            root.alphaChatWidthRatio = value
            root.persistDesktopSettings()
        })
        item.telemetryWidthRequested.connect(function(value) {
            root.alphaTelemetryWidth = value
            root.persistDesktopSettings()
        })
        item.accentColorRequested.connect(function(value) {
            root.cyan = value
            root.persistDesktopSettings()
        })
        item.frameBorderRequested.connect(function(value) {
            root.frameBorder = value
            root.persistDesktopSettings()
        })
        item.frameRadiusRequested.connect(function(value) {
            root.frameRadius = value
            root.persistDesktopSettings()
        })
        item.demoVisibilityRequested.connect(function(value) {
            root.alphaShowDemoFixtures = value
            root.persistDesktopSettings()
        })
        item.productSourceTabsRequested.connect(function(value) {
            root.showProductSourceTabs = value
            root.persistDesktopSettings()
        })
        item.showOpenTabInInputRequested.connect(function(value) {
            root.showOpenTabInInput = value
            root.persistDesktopSettings()
        })
        item.showInnerEditorChromeRequested.connect(function(value) {
            root.showInnerEditorChrome = value
            root.persistDesktopSettings()
        })
        item.engineTargetRequested.connect(function(value) {
            root.engineTarget = value
            root.persistDesktopSettings()
        })
        item.utilityHeightRequested.connect(function(value) {
            root.alphaUtilityHeight = value
            root.persistDesktopSettings()
        })
        item.desktopShellRequested.connect(function(value) {
            root.desktopShell = value
        })
        item.activeObjectChanged.connect(function(objectId, title) {
            if (objectId === root.lastSelectedObjectId)
                return
            root.lastSelectedObjectId = objectId
            root.appendRealNode(
                "GG SYSTEM",
                "CONTEXT",
                "Active Workspace object changed to "
                    + title
                    + ". @current now resolves to "
                    + objectId
                    + ".",
                "@current",
                "SELECTED",
                20,
                ""
            )
        })
    }

    function beginShellLoad(label) {
        root.shellNonce += 1
        root.shellLoadLabel = label
        root.shellLoading = true
        root.unloadDesktopShell()
        root._shellQueue = root.parseShellQueue()
        root._shellQueueIndex = 0
        if (String(label) !== "RELOAD")
            Qt.callLater(root.loadNextShellFile)
    }

    function finishShellLoad() {
        if (root._shellHydrated)
            return
        if (!root.startupReady)
            return
        if (workspaceLoader.status !== Loader.Ready || !workspaceLoader.item)
            return
        if (
            utilitySurface.status === Loader.Loading
            || utilitySurface.status === Loader.Null
        )
            return
        try {
            root.bindWorkspace(workspaceLoader.item)
            if (utilitySurface.item)
                root.bindUtility(utilitySurface.item)
            root.applyVisualProfile()
        } catch (err) {
            root.shellLoadCurrent = "LOAD FAILED"
            root.appendShellLog("shell bind · " + String(err))
        }
        if (!root._initialStartupComplete && root.surfaceHost
                && root.surfaceHost.prepareStartupChat) {
            root.surfaceHost.prepareStartupChat()
            if (root.startupChatBlocking) {
                root.shellLoadLabel = "PICKING UP WHERE YOU LEFT OFF"
                root.shellLoadCurrent = "Restoring your latest chat · opening at the newest messages"
                root.updateShellProgress()
                return
            }
        }
        root._shellHydrated = true
        root.startupServiceProgress = 100
        root.startupStepBusy = false
        root.startupStepNumber = 0
        root.startupStepCount = 0
        root.startupFailed = false
        root._initialStartupComplete = true
        root.updateShellProgress()
        root.shellLoading = false
        // The visual shell is ready now. Run the optional wallet/session
        // refresh after the first paint so a slow scan cannot strand the
        // full-window loading overlay at 100%.
        var hydratedNonce = root.shellNonce
        Qt.callLater(function() {
            if (root.shellNonce === hydratedNonce && root._shellHydrated)
                root.hydrateDesktopShell()
        })
    }

    function applyCryptoWalletLabel() {
        var label = "WALLET · DISCONNECTED"
        try {
            var parsed = JSON.parse(root.cryptoStatusJson || "{}")
            var w = parsed.wallet || {}
            if (w.label)
                label = String(w.label)
            else {
                var key = String(w.pubkey || "")
                if (key.length >= 8)
                    label = "WALLET · " + key.slice(0, 4) + "…" + key.slice(-4)
                else if (key.length > 0)
                    label = "WALLET · " + key
            }
        } catch (err) {
        }
        if (workspace)
            workspace.cryptoWalletLabel = label
    }

    function hydrateDesktopShell() {
        root.shellLoadLabel = "HYDRATING..."
        root.appendShellLog("hydrate · tui")
        root.appendShellLog("hydrate · wallet")
        root.appendShellLog("hydrate · chats")
        root.appendShellLog("hydrate · crypto")
        root.appendShellLog("hydrate · snippets")
        root.appendShellLog("hydrate · media")
        root.shellLoadCurrent = "desktop state"
        try {
            var raw = ""
            if (root.surfaceHost && root.surfaceHost.hydrateDesktop)
                raw = root.surfaceHost.hydrateDesktop()
            if (raw)
                root.cryptoStatusJson = raw
            else
                root.pullCryptoStatus()
            root.applyCryptoWalletLabel()
            if (workspace && workspace.refreshSiteFiles)
                workspace.refreshSiteFiles()
            if (workspace && workspace.applyCryptoWalletLabel)
                workspace.applyCryptoWalletLabel()
            if (utilitySurface.item && utilitySurface.item.refresh)
                utilitySurface.item.refresh()
        } catch (err) {
            // Optional hydration must never block the usable desktop shell.
            root.appendShellLog("hydrate · " + String(err))
        }
    }

    Component.onCompleted: Qt.callLater(root.requestStartupShellLoad)

    readonly property bool narrowLayout: width < 1050
    readonly property bool compactTelemetry: width < 1450

    property color canvas: "#121212"
    property color surface: "#161616"
    readonly property color line: "#6a6a6a"
    readonly property color textMain: "#e6e6e6"
    readonly property color textMuted: "#8a8a8a"
    property color cyan: "#8a8a8a"
    property color frameBorder: "#4a4a4a"
    property int frameRadius: 4
    property bool showOpenTabInInput: false
    property bool showInnerEditorChrome: true
    property bool desktopShell: false
    property bool appFullscreen: false
    readonly property color violet: "#b6a6c8"
    readonly property color green: "#8db89a"
    readonly property color amber: "#c8a97e"

    signal bridgeSubmit(
        string text,
        string contextReference,
        string workspaceObjectId
    )
    signal contextSnapshotSync(string snapshotJson)
    signal bridgeStop()
    signal bridgeAssignmentSet(
        string participant,
        string creatorActor
    )
    signal bridgeAssignmentClear()

    Connections {
        target: root.surfaceHost
        function onStartupChatChanged() {
            if (root.shellLoading)
                Qt.callLater(root.finishShellLoad)
        }
        function onGrokWalletChanged(payload) {
            root.grokWalletJson = payload
        }
        function onGptWalletChanged(payload) {
            root.gptWalletJson = payload
        }
        function onQmlLiveReload() {
            if (!root.shellLoading)
                root.beginShellLoad("RELOAD")
            Qt.callLater(root.loadNextShellFile)
        }
        function onWebOperatorCommand(payload) {
            if (root.workspace && root.workspace.applyWebOperator)
                root.workspace.applyWebOperator(payload)
        }
        function onChatSessionsChanged(payload) {
            root.chatSessionsJson = payload
            try {
                var rows = JSON.parse(payload || "[]")
                var i
                for (i = 0; i < rows.length; i++) {
                    if (rows[i] && rows[i].current) {
                        root.activeChatSession = String(rows[i].session_id)
                        break
                    }
                }
            } catch (err) {
            }
        }
        function onVisualCommandRequested(payload) {
            root.handleVisualCommand(payload)
        }
        function onWorkbenchExtensionsChanged(payload) {
            if (payload)
                root.workbenchExtensionsJson = payload
        }
    }

    // VS Code's command-first workbench is exposed through the GG chrome,
    // while the visual language remains unchanged.
    Shortcut {
        sequence: "Ctrl+Shift+P"
        enabled: !root.shellLoading
        onActivated: root.openCommandPalette()
    }

    Shortcut {
        sequence: "F1"
        enabled: !root.shellLoading
        onActivated: root.openCommandPalette()
    }

    Shortcut {
        sequence: "Ctrl+P"
        enabled: !root.shellLoading
        onActivated: root.openQuickOpen()
    }

    function loadWorkbenchExtensions() {
        if (!root.surfaceHost)
            return
        var raw = ""
        if (root.surfaceHost.loadWorkbenchExtensionsForProfile) {
            raw = root.surfaceHost.loadWorkbenchExtensionsForProfile(
                root.visualThemeId,
                root.visualProfileId
            )
        } else if (root.surfaceHost.loadWorkbenchExtensions) {
            raw = root.surfaceHost.loadWorkbenchExtensions()
        }
        if (raw)
            root.workbenchExtensionsJson = raw
    }

    function workbenchExtensionRows() {
        try {
            var rows = JSON.parse(root.workbenchExtensionsJson || "[]")
            return rows instanceof Array ? rows : []
        } catch (err) {
            return []
        }
    }

    function workbenchHostEnabled(kind) {
        var wanted = String(kind || "").toUpperCase()
        if (!wanted.length)
            return true
        var rows = root.workbenchExtensionRows()
        for (var i = 0; i < rows.length; ++i) {
            var row = rows[i] || {}
            if (String(row.hostKind || "").toUpperCase() === wanted)
                return row.enabled !== false
        }
        return true
    }

    function setWorkbenchExtensionEnabled(extensionId, enabled) {
        if (!root.surfaceHost
                || !root.surfaceHost.setWorkbenchExtensionEnabled)
            return
        var raw = ""
        if (root.surfaceHost.setWorkbenchExtensionEnabledForProfile) {
            raw = root.surfaceHost.setWorkbenchExtensionEnabledForProfile(
                String(extensionId || ""),
                Boolean(enabled),
                root.visualThemeId,
                root.visualProfileId
            )
        } else if (root.surfaceHost.setWorkbenchExtensionEnabled) {
            raw = root.surfaceHost.setWorkbenchExtensionEnabled(
                String(extensionId || ""),
                Boolean(enabled)
            )
        }
        if (raw)
            root.workbenchExtensionsJson = raw
        if (workspace && !root.workbenchHostEnabled(workspace.hostKind))
            workspace.setHostKind("CODE")
    }

    function resetWorkbenchExtensions() {
        if (!root.surfaceHost)
            return
        var raw = ""
        if (root.surfaceHost.resetWorkbenchExtensionsForProfile) {
            raw = root.surfaceHost.resetWorkbenchExtensionsForProfile(
                root.visualThemeId,
                root.visualProfileId
            )
        } else if (root.surfaceHost.resetWorkbenchExtensions) {
            raw = root.surfaceHost.resetWorkbenchExtensions()
        }
        if (raw)
            root.workbenchExtensionsJson = raw
    }

    function copyWorkbenchProfileExtensions(sourceProfileId, targetProfileId) {
        if (!root.surfaceHost
                || !root.surfaceHost.copyWorkbenchExtensionsProfile)
            return
        var raw = root.surfaceHost.copyWorkbenchExtensionsProfile(
            root.visualThemeId,
            String(sourceProfileId || ""),
            String(targetProfileId || "")
        )
        if (raw)
            root.workbenchExtensionsJson = raw
    }

    function copyWorkbenchThemeExtensions(
        sourceThemeId,
        targetThemeId,
        profileId
    ) {
        if (!root.surfaceHost
                || !root.surfaceHost.copyWorkbenchExtensionsTheme)
            return
        var raw = root.surfaceHost.copyWorkbenchExtensionsTheme(
            String(sourceThemeId || ""),
            String(targetThemeId || ""),
            String(profileId || root.visualProfileId)
        )
        if (raw)
            root.workbenchExtensionsJson = raw
    }

    function commandPaletteRows() {
        var rows = [
            { "id": "workbench.openSettings", "label": "Open Settings", "category": "Workbench", "keybinding": "", "description": "Open the GG settings workbench" },
            { "id": "settings.PROFILES", "label": "Open Settings: Profiles", "category": "Settings", "description": "Switch themes and presentation profiles" },
            { "id": "settings.SURFACES", "label": "Open Settings: Surfaces", "category": "Settings", "description": "Select a visual surface or source buffer" },
            { "id": "settings.EDITOR", "label": "Open Settings: Editor", "category": "Settings", "description": "Lock layout, resize handles and source mode" },
            { "id": "settings.APPEARANCE", "label": "Open Settings: Appearance", "category": "Settings", "description": "Change live frame and accent tokens" },
            { "id": "settings.LAYOUT", "label": "Open Settings: Layout", "category": "Settings", "description": "Change chat, telemetry and utility geometry" },
            { "id": "settings.CHAT", "label": "Open Settings: Chat", "category": "Settings", "description": "Choose the active chat motor" },
            { "id": "settings.WORKSPACE", "label": "Open Settings: Workspace", "category": "Settings", "description": "Choose a named host surface" },
            { "id": "settings.EXTENSIONS", "label": "Open Settings: Extensions", "category": "Settings", "description": "Enable or disable built-in contributions" },
            { "id": "code.runCheck", "label": "Run Code Check", "category": "Code", "keybinding": "F5", "description": "Run the safe Live Aid/QML check against the current buffer" },
            { "id": "code.toggleLiveFeedback", "label": "Toggle Live Code Feedback", "category": "Code", "keybinding": "Ctrl+Shift+L", "description": "Enable or pause debounced feedback while typing" },
            { "id": "code.saveBuffer", "label": "Save Current Buffer", "category": "Code", "keybinding": "Ctrl+S", "description": "Save the current local or profile-owned code buffer" },
            { "id": "workbench.toggleLayout", "label": root.visualLayoutLocked ? "Unlock Layout" : "Lock Layout", "category": "Layout", "keybinding": "", "description": "Toggle the six-dot and corner-handle presentation editor" },
            { "id": "workbench.resetLayout", "label": "Reset Standard Layout", "category": "Layout", "description": "Restore the current Standard presentation baseline" },
            { "id": "editor.showSource", "label": "Show Selected Surface Source", "category": "Editor", "description": "Open the profile-local source buffer for a surface" },
            { "id": "workbench.openWallet", "label": "Open Wallet", "category": "GG", "description": "Open the top-right wallet overlay" },
            { "id": "workbench.focusChat", "label": "Focus Chat", "category": "View", "description": "Move the primary focus to the operational stream" },
            { "id": "workbench.focusWorkspace", "label": "Focus Workspace", "category": "View", "description": "Move the primary focus to the central workbench" },
            { "id": "workbench.fullscreen", "label": "Toggle Fullscreen", "category": "Window", "description": "Toggle the existing GG fullscreen mode" },
            { "id": "workbench.reload", "label": "Reload QML Shell", "category": "Developer", "description": "Recreate the current visual shell" }
        ]
        var hostRows = root.workbenchExtensionRows()
        for (var i = 0; i < hostRows.length; ++i) {
            var contribution = hostRows[i] || {}
            var kind = String(contribution.hostKind || "").toUpperCase()
            if (!kind || contribution.enabled === false)
                continue
            rows.push({
                "id": "workspace." + kind,
                "label": "Open " + String(contribution.name || kind),
                "category": "Workspace",
                "description": String(contribution.description || "")
            })
        }
        rows.push(
            { "id": "engine.GROK_TUI", "label": "Use GROK TUI", "category": "Chat", "description": "Use the native GROK TUI motor" },
            { "id": "engine.GPT_TUI", "label": "Use GPTUI", "category": "Chat", "description": "Use the native GPTUI motor" },
            { "id": "engine.FLOW_TUI", "label": "Use FLOW TUI", "category": "Chat", "description": "Use the native FLOW TUI motor" },
            { "id": "engine.GROK_WORKER", "label": "Use GROK Worker", "category": "Chat", "description": "Use the resident GROK worker motor" },
            { "id": "engine.LOCAL_QWEN", "label": "Use Local QWEN", "category": "Chat", "description": "Use the local QWEN motor" }
        )
        try {
            var sessions = JSON.parse(root.chatSessionsJson || "[]")
            if (sessions instanceof Array) {
                for (var j = 0; j < sessions.length; ++j) {
                    var session = sessions[j] || {}
                    var sessionId = String(session.session_id || "")
                    if (!sessionId.length)
                        continue
                    var engine = String(session.engine || "")
                    var title = String(session.title || session.label || "")
                    if (!title.length)
                        title = session.current ? "Current session" : "Saved session"
                    rows.push({
                        "id": "session.resume." + sessionId,
                        "label": "Resume " + title,
                        "category": "Sessions",
                        "description": engine + (session.current ? " · current" : "")
                    })
                }
            }
        } catch (err) {
        }
        return rows
    }

    function quickOpenRows() {
        var rows = []
        if (workspace && workspace.quickOpenRows)
            rows = workspace.quickOpenRows()
        if (!rows || !(rows instanceof Array))
            rows = []
        rows.push({
            "id": "settings.WORKSPACE",
            "label": "Workspace Settings",
            "category": "Settings",
            "description": "Open workspace folders and host views"
        })
        rows.push({
            "id": "settings.EDITOR",
            "label": "Visual Editor",
            "category": "Settings",
            "description": "Open layout lock, source mode and surface handles"
        })
        return rows
    }

    function commandPaletteItems() {
        return root.commandPaletteMode === "QUICK_OPEN"
            ? root.quickOpenRows()
            : root.commandPaletteRows()
    }

    function openSettingsPage(page) {
        root.commandPaletteOpen = false
        root.walletOpen = false
        if (settingsPopup)
            settingsPopup.searchText = ""
        root.openSettings()
        if (settingsPopup)
            settingsPopup.page = String(page || "APPEARANCE")
    }

    function resumeChatSessionFromPalette(sessionId) {
        var wanted = String(sessionId || "")
        if (!wanted.length)
            return
        var rows = []
        try {
            rows = JSON.parse(root.chatSessionsJson || "[]")
        } catch (err) {
            rows = []
        }
        for (var i = 0; i < rows.length; ++i) {
            var row = rows[i] || {}
            if (String(row.session_id || "") !== wanted)
                continue
            var engine = String(row.engine || "")
            root.activeChatSession = wanted
            if (engine === "GPT_TUI" || engine === "GROK_TUI"
                    || engine === "GROK_WORKER" || engine === "LOCAL_QWEN"
                    || engine === "FLOW_TUI")
                root.engineTarget = engine
            if (engine === "GPT_TUI" && root.surfaceHost) {
                Qt.callLater(function() {
                    if (root.surfaceHost && root.surfaceHost.activateGptTui)
                        root.surfaceHost.activateGptTui(wanted)
                })
            } else if (engine === "GROK_TUI" && root.surfaceHost
                    && root.surfaceHost.resumeGrokTui) {
                root.surfaceHost.resumeGrokTui(wanted)
            }
            return
        }
    }

    function executeCommand(commandId) {
        var id = String(commandId || "")
        root.commandPaletteOpen = false
        if (id === "workbench.openSettings") {
            root.openSettings()
            return
        }
        if (id.indexOf("settings.") === 0) {
            root.openSettingsPage(id.slice(9))
            return
        }
        if (id === "workbench.toggleLayout") {
            root.setVisualLock(!root.visualLayoutLocked)
            root.openSettingsPage("EDITOR")
            return
        }
        if (id === "workbench.resetLayout") {
            root.resetVisualStandard()
            root.openSettingsPage("EDITOR")
            return
        }
        if (id === "editor.showSource") {
            if (root.visualSelectedSurface.length > 0)
                root.openVisualSource(root.visualSelectedSurface)
            else
                root.openSettingsPage("EDITOR")
            return
        }
        if (id === "code.runCheck") {
            if (workspace && workspace.runCodeCheck)
                workspace.runCodeCheck()
            return
        }
        if (id === "code.toggleLiveFeedback") {
            if (workspace && workspace.liveFeedbackEnabled !== undefined) {
                workspace.liveFeedbackEnabled = !workspace.liveFeedbackEnabled
                if (workspace.liveFeedbackEnabled && workspace.scheduleLiveAidAnalysis)
                    workspace.scheduleLiveAidAnalysis()
            }
            return
        }
        if (id === "code.saveBuffer") {
            if (workspace && workspace.saveCodeBuffer)
                workspace.saveCodeBuffer()
            return
        }
        if (id === "workbench.openWallet") {
            root.closeSettings()
            root.walletOpen = true
            if (root.walletX < 0) {
                root.walletX = Math.max(12, root.width - 346)
                root.walletY = 44
            }
            root.pullCryptoStatus()
            return
        }
        if (id.indexOf("quick.object.") === 0) {
            if (workspace && workspace.focusObject)
                workspace.focusObject(id.slice(13))
            return
        }
        if (id === "workbench.focusChat") {
            if (composer)
                composer.forceActiveFocus()
            return
        }
        if (id === "workbench.focusWorkspace") {
            if (workspace && workspace.forceActiveFocus)
                workspace.forceActiveFocus()
            return
        }
        if (id === "workbench.fullscreen") {
            root.toggleAppFullscreen()
            return
        }
        if (id === "workbench.reload") {
            if (!root.shellLoading)
                root.beginShellLoad("RELOAD")
            if (root.surfaceHost && root.surfaceHost.restartDesktop)
                root.surfaceHost.restartDesktop()
            return
        }
        if (id.indexOf("workspace.") === 0) {
            var kind = id.slice(10)
            if (workspace && workspace.setHostKind
                    && root.workbenchHostEnabled(kind))
                workspace.setHostKind(kind)
            return
        }
        if (id.indexOf("engine.") === 0) {
            root.engineTarget = id.slice(7)
            root.persistDesktopSettings()
            return
        }
        if (id.indexOf("session.resume.") === 0) {
            root.resumeChatSessionFromPalette(id.slice(15))
        }
    }

    function openCommandPalette() {
        root.walletOpen = false
        root.closeSettings()
        root.commandPaletteMode = "COMMAND"
        root.commandPaletteOpen = false
        root.commandPaletteOpen = true
    }

    function openQuickOpen() {
        root.walletOpen = false
        root.closeSettings()
        root.commandPaletteMode = "QUICK_OPEN"
        root.commandPaletteOpen = false
        root.commandPaletteOpen = true
    }

    function colorHex(value) {
        var text = String(value || "")
        if (text.length === 9 && text.indexOf("#ff") === 0)
            return "#" + text.slice(3)
        if (text.length === 9 && text.indexOf("#FF") === 0)
            return "#" + text.slice(3)
        if (text.length >= 7 && text.charAt(0) === "#")
            return text.slice(0, 7)
        return text
    }

    function pullCryptoStatus() {
        if (!root.surfaceHost)
            return
        var raw = ""
        if (root.surfaceHost.cryptoRailStatus)
            raw = root.surfaceHost.cryptoRailStatus()
        else if (root.surfaceHost.cryptoStatus)
            raw = root.surfaceHost.cryptoStatus()
        else
            return
        if (raw === root.cryptoStatusJson)
            return
        root.cryptoStatusJson = raw
        root.applyCryptoWalletLabel()
    }

    function openSettings() {
        // Keep the legacy workspace state closed while Settings is a top-level
        // window. This also makes an in-flight QML reload harmless.
        if (workspace && workspace.closeSettings)
            workspace.closeSettings()
        root.walletOpen = false
        if (!root.settingsMoved || root.settingsX < 0)
            root.positionSettingsPopup()
        root.settingsOpen = true
    }

    function closeSettings() {
        root.settingsOpen = false
        if (workspace && workspace.closeSettings)
            workspace.closeSettings()
    }

    function toggleSettings() {
        root.settingsOpen ? root.closeSettings() : root.openSettings()
    }

    function positionSettingsPopup() {
        if (!settingsButton)
            return
        var anchor = settingsButton.mapToItem(
            root.contentItem,
            0,
            settingsButton.height
        )
        var popupWidth = settingsPopup ? settingsPopup.width : 760
        var popupHeight = settingsPopup ? settingsPopup.height : 700
        root.settingsX = Math.max(
            12,
            Math.min(root.width - popupWidth - 12, anchor.x - 12)
        )
        root.settingsY = Math.max(
            12,
            Math.min(root.height - popupHeight - 12, anchor.y + 8)
        )
    }

    Timer {
        interval: 30000
        running: true
        repeat: true
        onTriggered: root.pullCryptoStatus()
    }

    function persistDesktopSettings() {
        if (!root.surfaceHost)
            return
        root.surfaceHost.saveDesktopSettings(JSON.stringify({
            "engineTarget": root.engineTarget,
            "chatWidthRatio": root.alphaChatWidthRatio,
            "telemetryWidth": root.alphaTelemetryWidth,
            "utilityHeight": root.alphaUtilityHeight,
            "accentColor": root.colorHex(root.cyan),
            "frameBorder": root.colorHex(root.frameBorder),
            "frameRadius": root.frameRadius,
            "showOpenTabInInput": root.showOpenTabInInput,
            "showInnerEditorChrome": root.showInnerEditorChrome,
            "showProductSourceTabs": root.showProductSourceTabs,
            "showDemoFixtures": root.alphaShowDemoFixtures,
            "desktopShell": root.desktopShell,
            "workspaceFolders": root.workspaceFolders || [],
            "workspaceTrusted": root.workspaceTrusted
        }))
    }

    function visualClone() {
        try {
            return JSON.parse(JSON.stringify(root.visualLayoutData || {}))
        } catch (err) {
            return {}
        }
    }

    function visualThemeObject(data, themeId) {
        var themes = data && data.themes ? data.themes : {}
        var id = String(themeId || (data ? data.activeTheme : ""))
        return themes[id] || null
    }

    function visualProfileObject(data, themeId, profileId) {
        var theme = root.visualThemeObject(data, themeId)
        if (!theme || !theme.profiles)
            return null
        var id = String(profileId || (data ? data.activeProfile : ""))
        return theme.profiles[id] || null
    }

    function visualProfileRows() {
        var revision = root.visualLayoutRevision
        var data = root.visualLayoutData || {}
        var theme = root.visualThemeObject(data, root.visualThemeId)
        var profiles = theme && theme.profiles ? theme.profiles : {}
        var rows = []
        for (var id in profiles) {
            var profile = profiles[id] || {}
            rows.push({
                "id": id,
                "name": String(profile.name || id),
                "locked": profile.locked !== false,
                "theme": root.visualThemeId
            })
        }
        return rows
    }

    function visualThemeRows() {
        var revision = root.visualLayoutRevision
        var data = root.visualLayoutData || {}
        var themes = data.themes || {}
        var rows = []
        for (var id in themes) {
            var theme = themes[id] || {}
            rows.push({
                "id": id,
                "name": String(theme.name || id),
                "profiles": theme.profiles
                    ? Object.keys(theme.profiles).length
                    : 0
            })
        }
        return rows
    }

    readonly property string visualProfilesJson: JSON.stringify(
        root.visualProfileRows()
    )
    readonly property string visualThemesJson: JSON.stringify(
        root.visualThemeRows()
    )
    readonly property string visualSurfaceRegistryJson: JSON.stringify(
        (root.visualLayoutData && root.visualLayoutData.surfaceRegistry)
            ? root.visualLayoutData.surfaceRegistry
            : []
    )

    function visualSurfaceEntry(surfaceId) {
        var revision = root.visualLayoutRevision
        var profile = root.visualProfileObject(
            root.visualLayoutData || {},
            root.visualThemeId,
            root.visualProfileId
        )
        var surfaces = profile && profile.surfaces ? profile.surfaces : {}
        return surfaces[String(surfaceId || "")] || {}
    }

    function visualSurfaceMetric(surfaceId, key, fallback) {
        var entry = root.visualSurfaceEntry(surfaceId)
        var value = entry[key]
        if (value === undefined || value === null)
            return fallback
        var number = Number(value)
        return isNaN(number) ? fallback : number
    }

    function visualSurfaceModel() {
        // The target references are live QML objects.  The registry metadata
        // remains in the backend state; this list only joins metadata to the
        // objects that are already rendered by Main.qml.
        return [
            { "surfaceId": "chat", "title": "Chat", "target": chatSurface },
            { "surfaceId": "workspace", "title": "Workspace", "target": workspaceLoader },
            { "surfaceId": "utility", "title": "Media / Utilities", "target": utilitySurface },
            { "surfaceId": "telemetry", "title": "Telemetry", "target": telemetry },
            { "surfaceId": "wallet", "title": "Wallet", "target": walletPopup },
            { "surfaceId": "settings", "title": "Settings", "target": settingsPopup }
        ]
    }

    function applyVisualThemeTokens(data) {
        var theme = root.visualThemeObject(data, root.visualThemeId)
        var tokens = theme && theme.tokens ? theme.tokens : {}
        if (tokens.canvas)
            root.canvas = String(tokens.canvas)
        if (tokens.surface)
            root.surface = String(tokens.surface)
        if (tokens.accent)
            root.cyan = String(tokens.accent)
        if (tokens.frameBorder)
            root.frameBorder = String(tokens.frameBorder)
        if (tokens.frameRadius !== undefined)
            root.frameRadius = Number(tokens.frameRadius)
    }

    function applyVisualTarget(surfaceId, target, entry) {
        if (!target || !entry)
            return
        if (target.visualOffsetX !== undefined) {
            target.visualOffsetX = Number(entry.offsetX || 0)
            target.visualOffsetY = Number(entry.offsetY || 0)
            target.visualScale = Number(entry.scale || 1)
        }
        // Popup width/height are bound to visualSurfaceMetric in their Main
        // instances.  Keep those bindings intact; changing the profile below
        // is enough to update them.
        if (surfaceId === "wallet") {
            root.walletX = Number(entry.x === undefined ? -1 : entry.x)
            root.walletY = Number(entry.y === undefined ? -1 : entry.y)
        } else if (surfaceId === "settings") {
            root.settingsX = Number(entry.x === undefined ? -1 : entry.x)
            root.settingsY = Number(entry.y === undefined ? -1 : entry.y)
            root.settingsMoved = root.settingsX >= 0 || root.settingsY >= 0
        }
    }

    function applyVisualProfile() {
        var data = root.visualLayoutData || {}
        var profile = root.visualProfileObject(
            data,
            root.visualThemeId,
            root.visualProfileId
        )
        if (!profile)
            return
        root.visualLayoutLocked = profile.locked !== false
        root.visualEditorMode = String(profile.editorMode || "NORMAL")
        root.visualSelectedSurface = String(profile.sourceSurface || "")
        var surfaces = profile.surfaces || {}
        root.applyVisualTarget("chat", chatSurface, surfaces.chat || {})
        root.applyVisualTarget("workspace", workspaceLoader, surfaces.workspace || {})
        root.applyVisualTarget("utility", utilitySurface, surfaces.utility || {})
        root.applyVisualTarget("telemetry", telemetry, surfaces.telemetry || {})
        root.applyVisualTarget("wallet", walletPopup, surfaces.wallet || {})
        root.applyVisualTarget("settings", settingsPopup, surfaces.settings || {})
    }

    function commitVisualState(data, persistDesktop) {
        if (!data || !data.themes)
            return
        root.visualLayoutData = data
        root.visualThemeId = String(data.activeTheme || root.visualThemeId)
        root.visualProfileId = String(data.activeProfile || root.visualProfileId)
        root.visualLayoutRevision += 1
        root.applyVisualThemeTokens(data)
        root.applyVisualProfile()
        root.loadWorkbenchExtensions()
        if (persistDesktop)
            root.persistDesktopSettings()
        root.scheduleVisualLayoutSave()
    }

    function loadVisualLayoutState() {
        if (!root.surfaceHost || !root.surfaceHost.loadVisualLayoutState)
            return
        var raw = root.surfaceHost.loadVisualLayoutState()
        try {
            var data = JSON.parse(raw || "{}")
            if (data && data.themes) {
                root.visualStateReady = true
                root.commitVisualState(data, false)
                if (root.visualEditorMode === "SOURCE"
                        && root.visualSelectedSurface.length > 0) {
                    var sourceId = root.visualSelectedSurface
                    Qt.callLater(function() {
                        root.openVisualSource(sourceId)
                    })
                }
            }
        } catch (err) {
            root.visualStateReady = false
        }
    }

    function flushVisualLayoutSave() {
        if (!root.surfaceHost || !root.surfaceHost.saveVisualLayoutState)
            return
        var raw = root.surfaceHost.saveVisualLayoutState(
            JSON.stringify(root.visualLayoutData || {})
        )
        if (!raw)
            return
        try {
            var data = JSON.parse(raw)
            if (data && data.themes) {
                root.visualLayoutData = data
                root.visualThemeId = String(data.activeTheme || root.visualThemeId)
                root.visualProfileId = String(data.activeProfile || root.visualProfileId)
                root.visualLayoutRevision += 1
            }
        } catch (err) {
        }
    }

    function scheduleVisualLayoutSave() {
        if (visualSaveTimer)
            visualSaveTimer.restart()
    }

    function updateVisualProfile(mutator) {
        var data = root.visualClone()
        var profile = root.visualProfileObject(
            data,
            root.visualThemeId,
            root.visualProfileId
        )
        if (!profile || !mutator)
            return
        mutator(profile)
        root.commitVisualState(data, false)
    }

    function setVisualTheme(themeId) {
        var data = root.visualClone()
        var id = String(themeId || "").trim().toLowerCase()
        if (!data.themes || !data.themes[id])
            return
        var theme = data.themes[id]
        var profiles = theme.profiles || {}
        var nextProfile = profiles[root.visualProfileId]
            ? root.visualProfileId
            : (profiles.standard ? "standard" : Object.keys(profiles)[0])
        data.activeTheme = id
        data.activeProfile = nextProfile
        root.commitVisualState(data, true)
        root.flushVisualLayoutSave()
    }

    function saveVisualThemeAs(themeId) {
        var id = String(themeId || "").trim().toLowerCase()
            .replace(/\s+/g, "-")
        if (!/^[a-z][a-z0-9._-]{0,47}$/.test(id))
            return
        var data = root.visualClone()
        var source = root.visualThemeObject(data, root.visualThemeId)
        var sourceThemeId = root.visualThemeId
        if (!source || !data.themes)
            return
        data.themes[id] = root.visualCloneObject(source)
        data.themes[id].name = id
        data.activeTheme = id
        data.activeProfile = root.visualProfileId
        if (!data.themes[id].profiles[data.activeProfile])
            data.activeProfile = "standard"
        root.commitVisualState(data, true)
        root.flushVisualLayoutSave()
        root.copyWorkbenchThemeExtensions(
            sourceThemeId,
            id,
            root.visualProfileId
        )
    }

    function setVisualProfile(profileId) {
        var data = root.visualClone()
        var theme = root.visualThemeObject(data, root.visualThemeId)
        var id = String(profileId || "").trim().toLowerCase()
        if (!theme || !theme.profiles || !theme.profiles[id])
            return
        data.activeProfile = id
        root.commitVisualState(data, false)
        root.flushVisualLayoutSave()
    }

    function saveVisualProfileAs(profileId) {
        var id = String(profileId || "").trim().toLowerCase()
            .replace(/\s+/g, "-")
        if (!/^[a-z][a-z0-9._-]{0,47}$/.test(id))
            return
        var data = root.visualClone()
        var theme = root.visualThemeObject(data, root.visualThemeId)
        var source = root.visualProfileObject(
            data,
            root.visualThemeId,
            root.visualProfileId
        )
        if (!theme || !source)
            return
        var sourceProfileId = root.visualProfileId
        theme.profiles = theme.profiles || {}
        theme.profiles[id] = root.visualCloneObject(source)
        theme.profiles[id].name = id
        data.activeProfile = id
        root.commitVisualState(data, false)
        root.flushVisualLayoutSave()
        root.copyWorkbenchProfileExtensions(sourceProfileId, id)
    }

    function visualCloneObject(value) {
        try {
            return JSON.parse(JSON.stringify(value || {}))
        } catch (err) {
            return {}
        }
    }

    function resetVisualProfile() {
        var data = root.visualClone()
        var theme = root.visualThemeObject(data, root.visualThemeId)
        if (!theme || !theme.profiles || !theme.profiles.standard)
            return
        var profileName = String(
            (theme.profiles[root.visualProfileId] || {}).name
                || root.visualProfileId
        )
        theme.profiles[root.visualProfileId] = root.visualCloneObject(
            theme.profiles.standard
        )
        theme.profiles[root.visualProfileId].name = profileName
        data.activeProfile = root.visualProfileId
        root.commitVisualState(data, false)
        root.flushVisualLayoutSave()
        root.resetWorkbenchExtensions()
        if (root.settingsOpen)
            Qt.callLater(root.positionSettingsPopup)
    }

    function resetVisualStandard() {
        if (root.surfaceHost && root.surfaceHost.resetVisualLayoutState) {
            var raw = root.surfaceHost.resetVisualLayoutState()
            try {
                var data = JSON.parse(raw || "{}")
                root.walletX = -1
                root.walletY = -1
                root.settingsX = -1
                root.settingsY = -1
                root.settingsMoved = false
                root.commitVisualState(data, true)
                root.resetWorkbenchExtensions()
                if (root.settingsOpen)
                    Qt.callLater(root.positionSettingsPopup)
                return
            } catch (err) {
            }
        }
    }

    function selectVisualSurface(surfaceId) {
        var id = String(surfaceId || "")
        var registry = root.visualLayoutData
            ? root.visualLayoutData.surfaceRegistry || []
            : []
        var found = false
        for (var i = 0; i < registry.length; i++) {
            if (String(registry[i].id || "") === id) {
                found = true
                break
            }
        }
        if (!found)
            return
        var entry = root.visualSurfaceEntry(id)
        if (!entry || !root.visualLayoutData)
            return
        root.visualSelectedSurface = id
        root.updateVisualProfile(function(profile) {
            profile.sourceSurface = id
        })
    }

    function openVisualSource(surfaceId) {
        var id = String(surfaceId || "").trim()
        if (!id)
            return
        root.selectVisualSurface(id)
        if (root.visualSelectedSurface !== id)
            return
        if (id === "wallet") {
            root.closeSettings()
            root.walletOpen = true
        } else if (id === "settings") {
            root.walletOpen = false
            root.settingsOpen = true
        }
        root.visualEditorMode = "SOURCE"
        root.updateVisualProfile(function(profile) {
            profile.editorMode = "SOURCE"
            profile.sourceSurface = id
        })
        if (settingsPopup && root.settingsOpen)
            settingsPopup.page = "EDITOR"
        if (!root.surfaceHost || !root.surfaceHost.loadVisualSource)
            return
        // Profile/theme selection may still be in the short debounce window.
        // Flush it before reading a profile-local source buffer.
        root.flushVisualLayoutSave()
        var raw = root.surfaceHost.loadVisualSource(
            id,
            root.visualThemeId,
            root.visualProfileId
        )
        try {
            var payload = JSON.parse(raw || "{}")
            root.visualSourceText = String(payload.source || "")
            root.visualSourcePath = String(payload.relativePath || "")
            root.visualSourceStatus = payload.status === "PASS"
                ? (payload.isBuffer ? "BUFFER" : "DISK")
                : String(payload.status || "FAIL")
        } catch (err) {
            root.visualSourceStatus = "FAIL"
        }
    }

    function closeVisualSource() {
        root.visualEditorMode = "NORMAL"
        root.updateVisualProfile(function(profile) {
            profile.editorMode = "NORMAL"
        })
        root.flushVisualLayoutSave()
    }

    function saveVisualSource(source) {
        var id = root.visualSelectedSurface
        if (!id || !root.surfaceHost || !root.surfaceHost.saveVisualSourceBuffer)
            return
        root.flushVisualLayoutSave()
        var raw = root.surfaceHost.saveVisualSourceBuffer(
            id,
            root.visualThemeId,
            root.visualProfileId,
            String(source || "")
        )
        try {
            var payload = JSON.parse(raw || "{}")
            root.visualSourceText = String(source || "")
            root.visualSourceStatus = String(payload.status || "FAIL")
            if (payload.status === "BUFFER_SAVED") {
                root.updateVisualProfile(function(profile) {
                    if (profile.surfaces && profile.surfaces[id])
                        profile.surfaces[id].sourceBuffer = String(source || "")
                })
                root.flushVisualLayoutSave()
            }
        } catch (err) {
            root.visualSourceStatus = "FAIL"
        }
    }

    function moveVisualSurface(surfaceId, dx, dy) {
        var id = String(surfaceId || "")
        var target = null
        if (id === "chat") target = chatSurface
        else if (id === "workspace") target = workspaceLoader
        else if (id === "utility") target = utilitySurface
        else if (id === "telemetry") target = telemetry
        else if (id === "wallet") target = walletPopup
        else if (id === "settings") target = settingsPopup
        if (!target)
            return
        var entry = root.visualSurfaceEntry(id)
        root.updateVisualProfile(function(profile) {
            var surface = profile.surfaces[id]
            if (!surface)
                return
            if (id === "wallet" || id === "settings") {
                var x = Number(surface.x)
                var y = Number(surface.y)
                if (x < 0) {
                    var point = target.mapToItem(root.contentItem, 0, 0)
                    x = point.x
                }
                if (y < 0) {
                    var pointY = target.mapToItem(root.contentItem, 0, 0)
                    y = pointY.y
                }
                surface.x = Math.max(0, x + Number(dx || 0))
                surface.y = Math.max(0, y + Number(dy || 0))
                if (id === "wallet") {
                    root.walletX = surface.x
                    root.walletY = surface.y
                } else {
                    root.settingsX = surface.x
                    root.settingsY = surface.y
                    root.settingsMoved = true
                }
            } else {
                surface.offsetX = Number(surface.offsetX || 0) + Number(dx || 0)
                surface.offsetY = Number(surface.offsetY || 0) + Number(dy || 0)
            }
        })
    }

    function resizeVisualSurface(surfaceId, corner, dx, dy) {
        var id = String(surfaceId || "")
        var amount = (Number(dx || 0) + Number(dy || 0)) / 2
        if (corner === "TOP_LEFT" || corner === "BOTTOM_LEFT")
            amount = -amount
        if (corner === "TOP_RIGHT" || corner === "BOTTOM_RIGHT")
            amount = amount
        root.updateVisualProfile(function(profile) {
            var surface = profile.surfaces[id]
            if (!surface)
                return
            if (id === "wallet" || id === "settings") {
                var currentWidth = Number(surface.width)
                if (currentWidth < 0)
                    currentWidth = id === "wallet" ? 328 : 760
                var currentHeight = Number(surface.height)
                if (currentHeight < 0)
                    currentHeight = id === "wallet" ? 360 : 620
                surface.width = Math.max(260, currentWidth + amount)
                surface.height = Math.max(260, currentHeight + amount)
            } else {
                surface.scale = Math.max(
                    0.45,
                    Math.min(2.5, Number(surface.scale || 1) + amount / 500)
                )
            }
        })
    }

    function handleVisualCommand(payload) {
        var parsed = {}
        try {
            parsed = JSON.parse(payload || "{}")
        } catch (err) {
            return
        }
        if (!parsed.valid) {
            root.settingsOpen = true
            if (settingsPopup)
                settingsPopup.page = "EDITOR"
            return
        }
        var command = String(parsed.command || "")
        var action = String(parsed.action || "")
        if (command === "/theme") {
            if (action === "use")
                root.setVisualTheme(parsed.id)
            else if (action === "save")
                root.saveVisualThemeAs(parsed.id)
            root.settingsOpen = true
            if (settingsPopup)
                settingsPopup.page = "PROFILES"
        } else if (command === "/profile") {
            if (action === "use")
                root.setVisualProfile(parsed.id)
            else if (action === "save")
                root.saveVisualProfileAs(parsed.id)
            else if (action === "reset")
                root.resetVisualProfile()
            root.settingsOpen = true
            if (settingsPopup)
                settingsPopup.page = "PROFILES"
        } else if (command === "/layout") {
            if (action === "lock")
                root.setVisualLock(true)
            else if (action === "unlock")
                root.setVisualLock(false)
            else if (action === "reset")
                root.resetVisualStandard()
            root.settingsOpen = true
            if (settingsPopup)
                settingsPopup.page = action === "surfaces"
                    ? "SURFACES"
                    : "EDITOR"
        } else if (command === "/source") {
            if (action === "close")
                root.closeVisualSource()
            else if (String(parsed.surface || "").length > 0)
                root.openVisualSource(parsed.surface)
            else {
                root.settingsOpen = true
                if (settingsPopup)
                    settingsPopup.page = "EDITOR"
            }
        } else if (command === "/view") {
            if (action === "open" && workspace
                    && root.workbenchHostEnabled(parsed.kind)) {
                workspace.setHostKind(String(parsed.kind || "CODE"))
                root.closeSettings()
            } else {
                root.openSettingsPage("WORKSPACE")
            }
        } else if (command === "/engine") {
            if (action === "use") {
                root.engineTarget = String(parsed.target || root.engineTarget)
                root.persistDesktopSettings()
            } else {
                root.openSettingsPage("CHAT")
            }
        } else if (command === "/extension") {
            if (action === "enable" || action === "disable")
                root.setWorkbenchExtensionEnabled(
                    String(parsed.id || ""),
                    action === "enable"
                )
            root.openSettingsPage("EXTENSIONS")
        } else if (command === "/settings") {
            root.openSettingsPage(String(parsed.page || "APPEARANCE"))
        } else if (command === "/quickopen") {
            root.openQuickOpen()
        }
    }

    function setVisualLock(locked) {
        var value = Boolean(locked)
        root.visualLayoutLocked = value
        root.updateVisualProfile(function(profile) {
            profile.locked = value
        })
        root.flushVisualLayoutSave()
    }

    function setVisualEditorMode(mode) {
        var value = String(mode || "NORMAL").toUpperCase()
        if (value !== "SOURCE")
            value = "NORMAL"
        if (value === "SOURCE" && root.visualSelectedSurface.length > 0) {
            root.openVisualSource(root.visualSelectedSurface)
            return
        }
        root.visualEditorMode = value
        root.updateVisualProfile(function(profile) {
            profile.editorMode = value
        })
        root.flushVisualLayoutSave()
    }

    Timer {
        id: visualSaveTimer
        interval: 180
        repeat: false
        onTriggered: root.flushVisualLayoutSave()
    }

    function applyDesktopShellNow() {
        if (!root.surfaceHost || !root.surfaceHost.applyDesktopShell)
            return
        root.surfaceHost.applyDesktopShell(root.desktopShell)
    }

    function toggleAppFullscreen() {
        if (root.surfaceHost && root.surfaceHost.prepareWindowModeChange)
            root.surfaceHost.prepareWindowModeChange()
        root.appFullscreen = !root.appFullscreen
    }

    title: "GG AI Desktop · Alpha"
    width: 1280
    height: 800
    minimumWidth: 820
    minimumHeight: 620
    flags: root.desktopShell && !root.appFullscreen
        ? (Qt.FramelessWindowHint | Qt.WindowStaysOnBottomHint)
        : Qt.Window
    visibility: root.appFullscreen
        ? Window.FullScreen
        : (root.desktopShell ? Window.Windowed : Window.Maximized)
    color: root.canvas
    font.family: "monospace"

    ListModel {
        id: chatModel

        ListElement {
            authorLabel: "GG SYSTEM"
            nodeKind: "BASELINE"
            bodyText: "Local alpha is ready. @current follows the active real Workspace object. Local Chat Bridge is connected."
            contextReference: "@workspace"
            provenanceClass: "REAL_UI_STATE"
            stateLabel: "READY"
            laneOffset: 0
            taskId: ""
            workStagesJson: ""
            workCardsJson: ""
        }
    }

    function upsertAutonomyNode(
        taskId,
        phase,
        stateLabel,
        stageText,
        contextReference
    ) {
        for (var i = chatModel.count - 1; i >= 0; --i) {
            var item = chatModel.get(i)

            if (item.nodeKind === "AUTONOMY" && item.taskId === taskId) {
                var current = {}

                if (item.workStagesJson && item.workStagesJson.length > 0)
                    current = JSON.parse(item.workStagesJson)

                current[phase] = {
                    "phase": phase,
                    "state": stateLabel,
                    "text": stageText
                }

                chatModel.setProperty(
                    i,
                    "workStagesJson",
                    JSON.stringify(current)
                )
                chatModel.setProperty(i, "stateLabel", stateLabel)
                return
            }
        }

        var first = {}

        first[phase] = {
            "phase": phase,
            "state": stateLabel,
            "text": stageText
        }

        chatModel.append({
            "authorLabel": "GG AI",
            "nodeKind": "AUTONOMY",
            "bodyText": "",
            "contextReference": contextReference,
            "provenanceClass": "REAL_UI_STATE",
            "stateLabel": stateLabel,
            "laneOffset": 28,
            "taskId": taskId,
            "workStagesJson": JSON.stringify(first)
        })

        root.scrollChatToLatest()
    }

    function boundedContextString(value, maximum) {
        if (value === undefined || value === null)
            return ""

        return String(value).slice(0, maximum)
    }

    function buildContextSnapshotJson() {
        var workspaceSnapshot = workspace
            ? workspace.contextSnapshot(32)
            : {}
        var recentChat = []
        var start = Math.max(
            0,
            chatModel.count - 12
        )

        for (var i = start; i < chatModel.count; ++i) {
            var item = chatModel.get(i)

            recentChat.push({
                "authorLabel": root.boundedContextString(
                    item.authorLabel,
                    1024
                ),
                "nodeKind": root.boundedContextString(
                    item.nodeKind,
                    1024
                ),
                "bodyText": root.boundedContextString(
                    item.bodyText,
                    2000
                ),
                "contextReference": root.boundedContextString(
                    item.contextReference,
                    1024
                ),
                "provenanceClass": root.boundedContextString(
                    item.provenanceClass,
                    1024
                )
            })
        }

        return JSON.stringify({
            "schema": "gg.workbench.context-snapshot.v1",
            "workspace": workspaceSnapshot,
            "workspaceFolders": root.workspaceFolders || [],
            "workspaceTrusted": root.workspaceTrusted,
            "recentChat": recentChat
        })
    }

    function parseWorkCards(raw) {
        if (raw === undefined || raw === null || String(raw).length === 0)
            return []

        try {
            var parsed = JSON.parse(String(raw))
            if (parsed !== null && typeof parsed === "object" && parsed.length !== undefined)
                return parsed
        } catch (parseError) {
            return []
        }

        return []
    }

    function beginGrokWorkerStream(requestId, contextReference) {
        for (var i = chatModel.count - 1; i >= 0; --i) {
            var existing = chatModel.get(i)
            if (
                existing.nodeKind === "GROK_STREAM"
                && existing.taskId === requestId
            )
                return
        }

        var streamContext = contextReference
        if (workspace && workspace.currentObjectTitle.length > 0)
            streamContext = contextReference
                + " · "
                + workspace.currentObjectTitle

        chatModel.append({
            "authorLabel": "GG AI",
            "nodeKind": "GROK_STREAM",
            "bodyText": "",
            "contextReference": streamContext,
            "provenanceClass": "REAL_UI_STATE",
            "stateLabel": "STARTING",
            "laneOffset": 28,
            "taskId": requestId,
            "workStagesJson": "",
            "workCardsJson": "[]"
        })
        root.scrollChatToLatest()
    }

    function chatFenceLooksLikeShell(body) {
        var text = String(body || "").replace(/^\s+/, "")
        if (text.length === 0)
            return false
        if (text.indexOf("$ ") === 0)
            return true
        var first = text.split(" ")[0]
        return (
            first === "echo"
            || first === "pwd"
            || first === "date"
            || first === "ls"
            || first === "cat"
            || first === "cd"
        )
    }

    function chatFenceIsEditorCode(lang) {
        var name = String(lang || "").toLowerCase()
        return (
            name === "qml"
            || name === "javascript"
            || name === "js"
            || name === "typescript"
            || name === "ts"
            || name === "python"
            || name === "py"
            || name === "json"
            || name === "css"
            || name === "html"
            || name === "php"
            || name === "c"
            || name === "cpp"
            || name === "h"
            || name === "rs"
            || name === "rust"
            || name === "go"
            || name === "java"
            || name === "xml"
            || name === "yaml"
            || name === "yml"
            || name === "sql"
            || name === "lua"
            || name === "vue"
        )
    }

    function extractEditorCodeFence(kind, title, text) {
        var body = String(text || "")
        var label = String(title || "").toLowerCase()
        if (kind === "stdout" || kind === "thought" || kind === "error")
            return ""
        if (label === "diff")
            return root.diffAddedSource(body)
        if (
            label === "terminal"
            || label.indexOf("read") === 0
            || label.indexOf("grep") === 0
        )
            return ""
        var rest = body
        var last = ""
        while (rest.length > 0) {
            var start = rest.indexOf("```")
            if (start < 0)
                break
            var after = rest.slice(start + 3)
            var nl = after.indexOf("\n")
            if (nl < 0)
                break
            var lang = after.slice(0, nl).trim()
            var tail = after.slice(nl + 1)
            var closer = tail.indexOf("```")
            if (closer < 0)
                break
            var chunk = tail.slice(0, closer).replace(/\s+$/, "")
            if (lang.toLowerCase() === "diff") {
                var added = root.diffAddedSource(chunk)
                if (added.length > 0)
                    last = added
            } else if (
                chunk.length > 0
                && root.chatFenceIsEditorCode(lang)
                && !root.chatFenceLooksLikeShell(chunk)
            )
                last = chunk
            rest = tail.slice(closer + 3)
        }
        if (last.length > 0)
            return last
        if (
            kind === "code"
            && body.indexOf("function") >= 0
            && !root.chatFenceLooksLikeShell(body)
        )
            return body
        return ""
    }

    function diffAddedSource(body) {
        var lines = String(body || "").split("\n")
        var added = []
        for (var i = 0; i < lines.length; ++i) {
            var line = lines[i]
            if (
                line.indexOf("+++") === 0
                || line.indexOf("---") === 0
                || line.indexOf("@@") === 0
            )
                continue
            if (line.charAt(0) === "+")
                added.push(line.slice(1))
        }
        return added.join("\n").replace(/\s+$/, "")
    }

    function applyChatFenceToScratch(kind, title, text) {
        var source = root.extractEditorCodeFence(kind, title, text)
        if (source.length === 0)
            return false
        if (workspace && workspace.applyChatCodeToCurrent)
            return workspace.applyChatCodeToCurrent(source)
        return false
    }

    function upsertGrokWorkerCard(
        requestId,
        cardId,
        kind,
        title,
        text,
        state
    ) {
        for (var i = chatModel.count - 1; i >= 0; --i) {
            var item = chatModel.get(i)
            if (
                !root.isGrokStreamNode(item.nodeKind)
                || item.taskId !== requestId
            )
                continue

            var cards = root.parseWorkCards(item.workCardsJson)
            var found = false
            var card = {
                "id": cardId,
                "kind": kind,
                "title": title,
                "text": text,
                "state": state
            }

            for (var j = 0; j < cards.length; ++j) {
                if (String(cards[j].id) === String(cardId)) {
                    var previousTitle = String(cards[j].title || "")
                    if (
                        (
                            String(title || "") === "tool"
                            || String(title || "").length === 0
                        )
                        && previousTitle.length > 0
                        && previousTitle !== "tool"
                    )
                        card.title = previousTitle
                    cards[j] = card
                    found = true
                    break
                }
            }

            if (!found)
                cards.push(card)

            chatModel.setProperty(
                i,
                "workCardsJson",
                JSON.stringify(cards)
            )
            chatModel.setProperty(i, "stateLabel", state)
            root.applyChatFenceToScratch(kind, title, text)
            root.scrollChatToLatest()
            return true
        }

        return false
    }

    function updateGrokWorkerState(requestId, stateLabel) {
        for (var i = chatModel.count - 1; i >= 0; --i) {
            var item = chatModel.get(i)
            if (
                root.isGrokStreamNode(item.nodeKind)
                && item.taskId === requestId
            ) {
                chatModel.setProperty(i, "stateLabel", stateLabel)
                return true
            }
        }

        return false
    }

    function beginStreamingResponse(requestId, contextReference) {
        for (var i = chatModel.count - 1; i >= 0; --i) {
            var existing = chatModel.get(i)
            if (
                root.isGrokStreamNode(existing.nodeKind)
                && existing.taskId === requestId
            )
                return
        }

        var streamContext = contextReference
        if (workspace && workspace.currentObjectTitle.length > 0)
            streamContext = contextReference
                + " · "
                + workspace.currentObjectTitle

        chatModel.append({
            "authorLabel": "GG AI",
            "nodeKind": "STREAM",
            "bodyText": "",
            "contextReference": streamContext,
            "provenanceClass": "REAL_UI_STATE",
            "stateLabel": "STARTING",
            "laneOffset": 28,
            "taskId": requestId,
            "workStagesJson": "",
            "workCardsJson": "[]"
        })
        root.scrollChatToLatest()
    }

    function updateStreamingResponse(requestId, bodyText, stateLabel) {
        for (var i = chatModel.count - 1; i >= 0; --i) {
            var item = chatModel.get(i)
            if (
                item.taskId !== requestId
                || (
                    item.nodeKind !== "RESPONSE"
                    && !root.isGrokStreamNode(item.nodeKind)
                )
            )
                continue
            chatModel.setProperty(i, "bodyText", bodyText)
            chatModel.setProperty(i, "stateLabel", stateLabel)
            root.scrollChatToLatest()
            return true
        }
        return false
    }

  function appendRealNode(
        authorLabel,
        nodeKind,
        bodyText,
        contextReference,
        stateLabel,
        laneOffset,
        taskId
    ) {
        chatModel.append({
            "authorLabel": authorLabel,
            "nodeKind": nodeKind,
            "bodyText": bodyText,
            "contextReference": contextReference,
            "provenanceClass": "REAL_UI_STATE",
            "stateLabel": stateLabel,
            "laneOffset": laneOffset,
            "taskId": taskId || ""
        })
        root.scrollChatToLatest()
    }

    function isUserChatNode(kind) {
        return kind === "REQUEST"
    }

    function isAiSpeechNode(kind) {
        return kind === "RESPONSE"
    }

    function isActivityNode(kind) {
        return kind !== "REQUEST"
            && kind !== "RESPONSE"
            && kind !== "TOOL"
            && kind !== "GROK_STREAM"
            && kind !== "STREAM"
    }

    function isToolNode(kind) {
        return kind === "TOOL"
    }

    function isGrokStreamNode(kind) {
        return kind === "GROK_STREAM" || kind === "STREAM"
    }

    function countNodeKind(kind) {
        var total = 0
        for (var i = 0; i < chatModel.count; ++i) {
            if (chatModel.get(i).nodeKind === kind)
                total += 1
        }
        return total
    }

    function activeWorkState() {
        if (!root.bridgeBusy)
            return ""

        for (var i = chatModel.count - 1; i >= 0; --i) {
            var item = chatModel.get(i)
            if (
                item.taskId === root.activeTaskId
                && item.stateLabel
                && item.stateLabel.length > 0
            )
                return item.stateLabel
        }

        return "RUNNING"
    }

    function activeWorkLabel() {
        if (!root.bridgeBusy)
            return ""

        var state = root.activeWorkState()
        for (var i = chatModel.count - 1; i >= 0; --i) {
            var item = chatModel.get(i)
            if (item.taskId !== root.activeTaskId)
                continue

            if (root.isGrokStreamNode(item.nodeKind)) {
                var cards = root.parseWorkCards(item.workCardsJson)
                for (var j = cards.length - 1; j >= 0; --j) {
                    var card = cards[j]
                    var kind = String(card.kind || "")
                    if (kind === "end" || kind === "user")
                        continue
                    var title = String(card.title || "")
                    if (kind === "thought")
                        return "Thinking"
                    if (kind === "text")
                        return "Writing"
                    if (
                        kind === "tool_call"
                        || kind === "tool_call_update"
                    ) {
                        if (title.length > 0)
                            return title
                        return "Working"
                    }
                    if (kind === "stdout")
                        return "Terminal"
                }
            }

            if (item.nodeKind === "RESPONSE") {
                if (state === "STARTING")
                    return "Starting"
                if (state === "GENERATING")
                    return "Waiting for response"
                if (state === "STREAMING")
                    return "Writing"
                if (state === "RUNNING")
                    return "Working"
            }
            break
        }

        if (state === "STARTING")
            return "Starting"
        if (state === "GENERATING" || state === "WAITING")
            return "Waiting for response"
        if (state === "STREAMING")
            return "Writing"
        if (state === "STOPPING")
            return "Stopping"
        return state.length > 0 ? state : "Working"
    }

    function latestKindState(kind) {
        for (var i = chatModel.count - 1; i >= 0; --i) {
            var item = chatModel.get(i)
            if (item.nodeKind === kind)
                return item.stateLabel || kind
        }
        return "EMPTY"
    }

    function liveAidWorkVisible() {
        if (!workspace)
            return false
        if (
            !workspace.editorLoaded
            || workspace.editorLanguage !== "qml"
        )
            return false

        if (workspace.postDraftBusy)
            return true

        if (
            workspace.preflightState === "RUNNING"
            || workspace.preflightState === "FAIL"
            || workspace.preflightState === "PASS"
        )
            return true

        if (
            workspace.repairState === "RUNNING"
            || workspace.repairState === "READY"
        )
            return true

        return false
    }

    function stickChatToLatest() {
        if (chatFlick.height <= 0)
            return
        chatFlick.contentY = Math.max(
            0,
            chatFlick.contentHeight - chatFlick.height
        )
    }

    function scrollChatToLatest() {
        // Keep a reader's manual position.  New streamed nodes may request a
        // tail update, but they must not silently yank the viewport back down
        // after the user has scrolled up to inspect an earlier message.
        if (!root.followChatTail)
            return
        root.stickChatToLatest()
        Qt.callLater(function() {
            if (root.followChatTail)
                root.stickChatToLatest()
        })
    }

    function setBridgeActivity(busy, taskId) {
        root.bridgeBusy = busy
        root.activeTaskId = busy ? taskId : ""
        if (busy) {
            root.followChatTail = true
            root.scrollChatToLatest()
        }
    }

    GgFrame {
        id: topBar
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: 12
        anchors.rightMargin: 12
        anchors.topMargin: 12
        height: 54
        leftLegend: "GG AI DESKTOP"
        backgroundColor: root.surface
        borderColor: root.frameBorder
        radius: root.frameRadius
        padding: 12
        leftLegendColor: "#e6edf3"

        Item {
            width: parent.width
            height: 22

            Row {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                spacing: 14

                Text {
                    text: "OBSIDIAN / LEDGER"
                    color: "#c8cdd4"
                    font.family: "monospace"
                    font.pixelSize: 13
                }

                Text {
                    text: "·"
                    color: "#a8b0b8"
                    font.family: "monospace"
                    font.pixelSize: 13
                }

                Text {
                    visible: root.desktopShell
                    text: "DESKTOP"
                    color: "#c8a97e"
                    font.family: "monospace"
                    font.pixelSize: 13
                    font.bold: true
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.desktopShell = false
                    }
                }

                Text {
                    visible: root.desktopShell
                    text: "·"
                    color: "#a8b0b8"
                    font.family: "monospace"
                    font.pixelSize: 13
                }

                Text {
                    id: settingsButton
                    objectName: "topBarSettingsButton"
                    text: "SETTINGS"
                    color: root.settingsOpen ? "#e6edf3" : "#c8cdd4"
                    font.family: "monospace"
                    font.pixelSize: 13
                    font.bold: root.settingsOpen

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.toggleSettings()
                    }
                }

                Text {
                    text: "·"
                    color: "#a8b0b8"
                    font.family: "monospace"
                    font.pixelSize: 13
                }

                Text {
                    id: commandPaletteButton
                    objectName: "topBarCommandPaletteButton"
                    text: "COMMANDS"
                    color: root.commandPaletteOpen ? "#e6edf3" : "#c8cdd4"
                    font.family: "monospace"
                    font.pixelSize: 13
                    font.bold: root.commandPaletteOpen

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.openCommandPalette()
                    }
                }

                Text {
                    text: "·"
                    color: "#a8b0b8"
                    font.family: "monospace"
                    font.pixelSize: 13
                }

                Text {
                    id: reloadButton
                    objectName: "topBarReloadButton"
                    text: "RELOAD"
                    color: "#c8cdd4"
                    font.family: "monospace"
                    font.pixelSize: 13

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            if (root.shellLoading)
                                return
                            root.beginShellLoad("RELOAD")
                            // RELOAD clears both loaders first. Queue the
                            // normal shell pipeline again so the button cannot
                            // strand the desktop in an empty workspace.
                            Qt.callLater(root.loadNextShellFile)
                            if (root.surfaceHost && root.surfaceHost.restartDesktop)
                                root.surfaceHost.restartDesktop()
                        }
                    }
                }

                Text {
                    text: "·"
                    color: "#a8b0b8"
                    font.family: "monospace"
                    font.pixelSize: 13
                }

                Text {
                    id: fullscreenButton
                    objectName: "topBarFullscreenButton"
                    text: root.appFullscreen ? "EXIT FULLSCREEN" : "FULLSCREEN"
                    color: root.appFullscreen ? root.amber : "#c8cdd4"
                    font.family: "monospace"
                    font.pixelSize: 13
                    font.bold: root.appFullscreen

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.toggleAppFullscreen()
                    }
                }
            }

            Row {
                visible: root.narrowLayout
                anchors.centerIn: parent
                spacing: 6

                GgButton {
                    text: "CHAT"
                    checkable: true
                    checked: root.narrowPane === "CHAT"
                    onClicked: root.narrowPane = "CHAT"
                }

                GgButton {
                    text: "WORKSPACE"
                    checkable: true
                    checked: root.narrowPane === "WORKSPACE"
                    onClicked: root.narrowPane = "WORKSPACE"
                }
            }

            Row {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: 16

                Text {
                    visible: root.liveEyes.state !== "off"
                    text: root.liveEyes.state === "live"
                          ? "ÖGON · " + (root.liveEyes.received_fps || 0) + " fps"
                          : "ÖGON · " + (root.liveEyes.state === "error" ? "FEL" : "VÄNTAR")
                    color: root.liveEyes.state === "live" && root.liveEyes.frame_age_ms <= 2000
                           ? root.green : root.amber
                    font.family: "monospace"
                    font.pixelSize: 13
                    ToolTip.visible: eyesStopArea.containsMouse
                    ToolTip.text: (root.liveEyes.reason || "Skärmfångst aktiv")
                                  + "\nKlicka för att stoppa skärmdelningen."
                    MouseArea {
                        id: eyesStopArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            if (root.surfaceHost && root.surfaceHost.liveVisionStop)
                                root.surfaceHost.liveVisionStop()
                        }
                    }
                }

                Text {
                    text: "LOCAL · ALPHA"
                    color: root.cyan
                    font.family: "monospace"
                    font.pixelSize: 13
                }

                Item {
                    objectName: "topBarWalletChip"
                    width: walletChipRow.width
                    height: walletChipRow.height
                    readonly property string walletShort: {
                        if (workspace) {
                            var live = String(workspace.cryptoWalletLabel || "")
                            if (live.indexOf("WALLET · ") === 0
                                    && live.indexOf("DISCONNECTED") < 0)
                                return live.slice(9)
                        }
                        try {
                            var parsed = JSON.parse(root.cryptoStatusJson || "{}")
                            var w = parsed.wallet || {}
                            var key = String(w.pubkey || "")
                            if (key.length >= 8)
                                return key.slice(0, 4) + "…" + key.slice(-4)
                            if (key.length > 0)
                                return key
                        } catch (err) {
                        }
                        return ""
                    }
                    readonly property bool walletOn: walletShort.length > 0

                    Row {
                        id: walletChipRow
                        spacing: 0
                        Text {
                            text: "WALLET"
                            color: walletChipRow.parent.walletOn ? root.green : "#c8cdd4"
                            font.family: "monospace"
                            font.pixelSize: 13
                            font.bold: walletChipRow.parent.walletOn
                        }
                        Text {
                            text: walletChipRow.parent.walletOn
                                ? (" · " + walletChipRow.parent.walletShort)
                                : " · DISCONNECTED"
                            color: walletChipRow.parent.walletOn ? "#e6edf3" : "#c8cdd4"
                            font.family: "monospace"
                            font.pixelSize: 13
                        }
                        Text {
                            text: root.walletOpen ? "  ▴" : "  ▾"
                            color: walletChipRow.parent.walletOn ? root.green : "#c8cdd4"
                            font.family: "monospace"
                            font.pixelSize: 13
                        }
                    }
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            if (root.walletOpen) {
                                root.walletOpen = false
                                return
                            }
                            root.closeSettings()
                            root.walletOpen = true
                            if (root.walletOpen) {
                                if (root.walletX < 0) {
                                    root.walletX = Math.max(12, root.width - 346)
                                    root.walletY = 44
                                }
                                if (root.surfaceHost
                                        && root.surfaceHost.cryptoStatus)
                                    root.cryptoStatusJson = root.surfaceHost.cryptoStatus()
                            }
                        }
                    }
                }
            }
        }
    }

    Item {
        id: body
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: topBar.bottom
        anchors.bottom: parent.bottom
        anchors.leftMargin: 12
        anchors.rightMargin: 12
        anchors.bottomMargin: 12
        anchors.topMargin: 10

        Row {
            anchors.fill: parent
            spacing: 10

            Item {
                id: chatSurface
                objectName: "chatSurface"
                property real visualOffsetX: 0
                property real visualOffsetY: 0
                property real visualScale: 1
                transform: [
                    Translate {
                        x: chatSurface.visualOffsetX
                        y: chatSurface.visualOffsetY
                    },
                    Scale {
                        xScale: chatSurface.visualScale
                        yScale: chatSurface.visualScale
                    }
                ]
                visible: !root.narrowLayout || root.narrowPane === "CHAT"
                width: root.narrowLayout
                    ? body.width
                      : Math.max(
                          420,
                          body.width * root.alphaChatWidthRatio
                      )
                height: body.height
                // A1.2.1.1: GgFrame is visual chrome only.
                GgFrame {
                    id: chatChrome
                    anchors.fill: parent
                    leftLegend: "CHAT · UNIVERSAL OPERATIONAL STREAM"
                    rightLegend: "BRIDGE · CONNECTED"
                    busy: root.bridgeBusy
                    backgroundColor: root.surface
                    borderColor: root.frameBorder
                    radius: root.frameRadius
                }

                GrokTuiHole {
                    id: grokTuiHost
                    objectName: "grokTuiHost"
                    terminalId: "ws.tui.grok"
                    visible: root.engineTarget === "GROK_TUI"
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.bottom: composer.top
                    anchors.leftMargin: chatChrome.padding
                    anchors.rightMargin: chatChrome.padding
                    anchors.topMargin: chatChrome.topChrome
                    anchors.bottomMargin: 0
                    surfaceHost: root.surfaceHost
                }

                GrokTuiHole {
                    id: gptTuiHost
                    objectName: "gptTuiHost"
                    terminalId: "ws.tui.gpt"
                    visible: root.engineTarget === "GPT_TUI"
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.bottom: composer.top
                    anchors.leftMargin: chatChrome.padding
                    anchors.rightMargin: chatChrome.padding
                    anchors.topMargin: chatChrome.topChrome
                    anchors.bottomMargin: 0
                    surfaceHost: root.surfaceHost
                }

                FlowTuiHole {
                    id: flowTuiHost
                    objectName: "flowTuiHost"
                    visible: root.engineTarget === "FLOW_TUI"
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.bottom: composer.top
                    anchors.leftMargin: chatChrome.padding
                    anchors.rightMargin: chatChrome.padding
                    anchors.topMargin: chatChrome.topChrome
                    anchors.bottomMargin: 0
                    surfaceHost: root.surfaceHost
                }

                Flickable {
                    id: chatFlick
                    objectName: "chatCockpit"
                    visible: root.engineTarget !== "GROK_TUI" && root.engineTarget !== "GPT_TUI" && root.engineTarget !== "FLOW_TUI"
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.bottom: chatStatusDock.top
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    anchors.topMargin: 14
                    anchors.bottomMargin: 8
                    clip: true
                    contentWidth: width
                    contentHeight: Math.max(
                        height,
                        streamWrap.height
                    )
                    enabled: visible
                    flickableDirection: Flickable.VerticalFlick
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: GgScrollBar {
                        objectName: "chatScrollBar"
                        keepVisible: true
                        policy: chatFlick.visible
                            ? ScrollBar.AsNeeded
                            : ScrollBar.AlwaysOff
                    }
                    onContentHeightChanged: {
                        if (root.followChatTail)
                            root.stickChatToLatest()
                    }
                    onHeightChanged: {
                        if (root.followChatTail)
                            root.stickChatToLatest()
                    }
                    onContentYChanged: {
                        // Drop tail-follow as soon as a real drag moves the
                        // viewport away from the newest line.  This happens
                        // before the next streamed update can snap it back.
                        if (
                            chatFlick.moving
                            && chatFlick.contentY
                                + chatFlick.height
                                < chatFlick.contentHeight - 32
                        )
                            root.followChatTail = false
                    }
                    onMovementStarted: {
                        root.followChatTail = (
                            chatFlick.contentY
                            + chatFlick.height
                            >= chatFlick.contentHeight - 32
                        )
                    }
                    onMovementEnded: {
                        root.followChatTail = (
                            chatFlick.contentY
                            + chatFlick.height
                            >= chatFlick.contentHeight - 32
                        )
                    }

                    Item {
                        id: streamWrap
                        width: chatFlick.width
                        height: Math.max(
                            chatFlick.height,
                            streamColumn.implicitHeight + 16
                        )

                    Column {
                        id: streamColumn
                        objectName: "chatActivityStream"
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        spacing: 8
                        onImplicitHeightChanged: {
                            if (root.followChatTail)
                                root.stickChatToLatest()
                        }

                        Repeater {
                            model: chatModel

                            delegate: Item {
                                id: streamDelegate
                                required property var model

                                width: streamColumn.width
                                height: Math.max(
                                    grokLoader.height,
                                    activityLoader.height,
                                    toolLoader.height,
                                    speechLoader.height
                                )

                                Loader {
                                    id: grokLoader
                                    width: Math.min(
                                        parent.width,
                                        parent.width * 0.92
                                    )
                                    height: item ? item.implicitHeight : 0
                                    active: root.isGrokStreamNode(
                                        streamDelegate.model.nodeKind
                                    )
                                    sourceComponent: Component {
                                        GrokWorkStream {
                                            width: grokLoader.width
                                            authorLabel: streamDelegate.model.authorLabel
                                            nodeKind: streamDelegate.model.nodeKind
                                            stateLabel: streamDelegate.model.stateLabel
                                            contextReference: streamDelegate.model.contextReference
                                            taskId: streamDelegate.model.taskId || ""
                                            workCardsJson: streamDelegate.model.workCardsJson || "[]"
                                            livePulse: root.bridgeBusy
                                                && streamDelegate.model.taskId === root.activeTaskId
                                            onImplicitHeightChanged: {
                                                if (root.followChatTail)
                                                    root.stickChatToLatest()
                                            }
                                        }
                                    }
                                }

                                Loader {
                                    id: activityLoader
                                    width: Math.min(
                                        parent.width,
                                        parent.width * 0.92
                                    )
                                    height: item ? item.implicitHeight : 0
                                    active: root.isActivityNode(
                                        streamDelegate.model.nodeKind
                                    )
                                    sourceComponent: Component {
                                        ChatActivityEvent {
                                            width: activityLoader.width
                                            authorLabel: streamDelegate.model.authorLabel
                                            nodeKind: streamDelegate.model.nodeKind
                                            bodyText: streamDelegate.model.bodyText
                                            stateLabel: streamDelegate.model.stateLabel
                                            contextReference: streamDelegate.model.contextReference
                                            taskId: streamDelegate.model.taskId || ""
                                            workStagesJson: streamDelegate.model.workStagesJson || ""
                                            livePulse: root.bridgeBusy
                                                && streamDelegate.model.taskId === root.activeTaskId
                                        }
                                    }
                                }

                                Loader {
                                    id: toolLoader
                                    width: Math.min(
                                        parent.width,
                                        parent.width * 0.92
                                    )
                                    height: item ? item.implicitHeight : 0
                                    active: root.isToolNode(
                                        streamDelegate.model.nodeKind
                                    )
                                    sourceComponent: Component {
                                        WorkObject {
                                            width: toolLoader.width
                                            objectType: {
                                                var body = String(
                                                    streamDelegate.model.bodyText || ""
                                                )
                                                if (body.indexOf("READ ") === 0)
                                                    return "CODE"
                                                return "TERMINAL"
                                            }
                                            title: {
                                                var body = String(
                                                    streamDelegate.model.bodyText || ""
                                                )
                                                if (body.indexOf("READ ") === 0)
                                                    return "read"
                                                if (body.indexOf("SEARCH ") === 0)
                                                    return "search"
                                                if (
                                                    body.indexOf("TEST ") === 0
                                                    || body.indexOf("RUN ") === 0
                                                )
                                                    return "terminal"
                                                return streamDelegate.model.taskId || "tool"
                                            }
                                            bodyText: streamDelegate.model.bodyText
                                            provenanceClass: "REAL_UI_STATE"
                                            activityState: streamDelegate.model.stateLabel
                                            realPercentage: -1
                                            contextReference: streamDelegate.model.contextReference
                                        }
                                    }
                                }

                                Loader {
                                    id: speechLoader
                                    width: parent.width
                                    height: item ? item.implicitHeight : 0
                                    active: root.isUserChatNode(
                                        streamDelegate.model.nodeKind
                                    )
                                        || root.isAiSpeechNode(
                                            streamDelegate.model.nodeKind
                                        )
                                    sourceComponent: Component {
                                        ChatNode {
                                            authorLabel: streamDelegate.model.authorLabel
                                            nodeKind: streamDelegate.model.nodeKind
                                            bodyText: streamDelegate.model.bodyText
                                            contextReference: streamDelegate.model.contextReference
                                            provenanceClass: streamDelegate.model.provenanceClass
                                            stateLabel: streamDelegate.model.stateLabel
                                            laneOffset: 0
                                            taskId: streamDelegate.model.taskId || ""
                                            workStagesJson: streamDelegate.model.workStagesJson || ""
                                            maxBubbleWidth: Math.floor(
                                                streamDelegate.width * (
                                                    root.isUserChatNode(
                                                        streamDelegate.model.nodeKind
                                                    ) ? 0.78 : 0.92
                                                )
                                            )
                                            x: root.isUserChatNode(
                                                streamDelegate.model.nodeKind
                                            )
                                                ? streamDelegate.width - width
                                                : 0
                                            onImplicitHeightChanged: {
                                                if (root.followChatTail)
                                                    root.stickChatToLatest()
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        Item {
                            id: artifactRow
                            objectName: "chatArtifactPane"
                            width: parent.width
                            visible: root.liveAidWorkVisible()
                            height: visible
                                ? Math.max(
                                    180,
                                    chatLiveAidWork.implicitHeight
                                )
                                : 0

                            Row {
                                anchors.fill: parent
                                anchors.leftMargin: 16
                                spacing: 6

                                GgFrame {
                                    id: chatCodeblock
                                    width: parent.width
                                        - liveAidColumn.width
                                        - parent.spacing
                                    height: parent.height
                                    leftLegend: "CODEBLOCK · "
                                        + (
                                            workspace
                                            && workspace.currentObjectTitle.length > 0
                                                ? workspace.currentObjectTitle
                                                : "FILE"
                                        )
                                    rightLegend: workspace && workspace.editorDirty
                                        ? "BUFFER · UNSAVED"
                                        : "BUFFER · DISK BASE"
                                    backgroundColor: "#070a0e"
                                    borderColor: "#6a6a6a"

                                    Flickable {
                                        id: codeblockFlick
                                        width: parent.width
                                        height: Math.max(
                                            1,
                                            chatCodeblock.height - 36
                                        )
                                        clip: true
                                        boundsBehavior: Flickable.StopAtBounds
                                        contentWidth: Math.max(
                                            width,
                                            codeblockView.contentWidth
                                        )
                                        contentHeight: Math.max(
                                            height,
                                            codeblockView.contentHeight
                                        )
                                        interactive: contentHeight > height
                                            || contentWidth > width
                                        visible: !root.alphaShowDemoFixtures

                                        TextEdit {
                                            id: codeblockView
                                            text: workspace && workspace.editorLoaded
                                                ? workspace.editorText
                                                : ""
                                            color: "#d8dee9"
                                            readOnly: true
                                            selectByMouse: true
                                            selectByKeyboard: true
                                            persistentSelection: true
                                            textFormat: TextEdit.PlainText
                                            wrapMode: TextEdit.NoWrap
                                            font.family: "monospace"
                                            font.pixelSize: 12
                                            selectionColor: "#3a3a3a"
                                            selectedTextColor: "#f2f2f2"

                                            SelectionGuard {
                                                editor: codeblockView
                                            }
                                        }

                                        ScrollBar.vertical: GgScrollBar {}
                                        ScrollBar.horizontal: GgScrollBar {}
                                    }
                                }

                                Item {
                                    id: liveAidColumn
                                    width: Math.max(
                                        168,
                                        Math.min(214, parent.width * 0.38)
                                    )
                                    height: parent.height

                                    ChatLiveAidWork {
                                        id: chatLiveAidWork
                                        width: parent.width
                                        height: parent.height
                                        objectTitle: workspace
                                            ? workspace.currentObjectTitle
                                            : ""
                                        editorLoaded: workspace
                                            ? workspace.editorLoaded
                                            : false
                                        editorLanguage: workspace
                                            ? workspace.editorLanguage
                                            : ""
                                        liveAidState: workspace
                                            ? workspace.liveAidState
                                            : "IDLE"
                                        diagnostics: workspace
                                            ? workspace.liveAidDiagnostics
                                            : []
                                        evidenceSummary: workspace
                                            ? workspace.liveAidEvidenceSummary
                                            : ""
                                        preflightState: workspace
                                            ? workspace.preflightState
                                            : "NOT RUN"
                                        repairState: workspace
                                            ? workspace.repairState
                                            : ""
                                        repairProposalId: workspace
                                            ? workspace.repairProposalId
                                            : ""
                                        postDraftBusy: workspace
                                            ? workspace.postDraftBusy
                                            : false
                                        postDraftState: workspace
                                            ? workspace.postDraftState
                                            : ""

                                        onPostDraftRequested: {
                                            if (workspace)
                                                workspace.requestPostDraftAutomaticRepair()
                                        }
                                        onPreflightRequested: {
                                            if (workspace)
                                                workspace.requestLiveAidPreflight()
                                        }
                                        onRepairRequested: {
                                            if (workspace)
                                                workspace.requestLiveAidRepair()
                                        }
                                        onApplyRequested: {
                                            if (workspace)
                                                workspace.requestApplyRepair()
                                        }
                                    }
                                }
                            }
                        }

                        WorkObject {
                            visible: root.alphaShowDemoFixtures
                            width: parent.width
                            objectType: "TERMINAL"
                            title: "tool stream"
                            provenanceClass: "SYNTHETIC_UI_FIXTURE"
                            activityState: "IDLE"
                            realPercentage: -1
                            bodyText: "$ sample only\n"
                                + "No process started.\n"
                                + "No exit status claimed."
                        }

                        WorkObject {
                            visible: root.alphaShowDemoFixtures
                            width: parent.width
                            objectType: "CODE"
                            title: "header.css"
                            provenanceClass: "SYNTHETIC_UI_FIXTURE"
                            activityState: "IDLE"
                            realPercentage: -1
                            bodyText: "/* DEMO / SAMPLE — not a real edit */\n"
                                + ".hero {\n"
                                + "    padding-block: var(--space-xl);\n"
                                + "}"
                        }
                    }
                    }
                }

                Item {
                    id: chatStatusDock
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: composer.top
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    height: root.bridgeBusy ? chatStatusStrip.implicitHeight : 0

                    ActivityStrip {
                        id: chatStatusStrip
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        width: parent.width
                        visible: root.bridgeBusy
                        activityState: root.activeWorkState()
                        headline: root.activeWorkLabel()
                        percentage: -1
                    }
                }

                // A1.2.1.1: ordinary chatSurface owns composer geometry.
                ContextComposer {
                    id: composer
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.leftMargin: 8
                    anchors.rightMargin: 8
                    anchors.bottomMargin: 0
                    height: composer.implicitHeight
                    contextReference: workspace
                        ? workspace.currentContextReference
                        : "@current"
                    workspaceObjectId: (
                        workspace
                        && workspace.currentObjectType === "SITE_PROJECT"
                        && workspace.siteRelativePath.length > 0
                    )
                        ? workspace.siteFileObjectId(
                            workspace.siteRelativePath
                        )
                        : (workspace ? workspace.currentObjectId : "")
                    workspaceObjectTitle: workspace
                        ? workspace.currentObjectTitle
                        : ""
                    bridgeState: "CONNECTED"
                    busy: root.bridgeBusy
                    activeTaskId: root.activeTaskId
                    engineTarget: root.engineTarget
                    frameBorder: root.frameBorder
                    frameRadius: root.frameRadius
                    showOpenTab: root.showOpenTabInInput
                    surfaceHost: root.surfaceHost
                    onEngineTargetRequested: function(value) {
                        if (
                            value === "LOCAL_QWEN"
                            || value === "GROK_WORKER"
                            || value === "GROK_TUI"
                            || value === "GPT_TUI"
                            || value === "FLOW_TUI"
                        ) {
                            root.engineTarget = value
                            root.persistDesktopSettings()
                        }
                    }

                    onAssignmentSetRequested: function(participant, creatorActor) {
                        root.bridgeAssignmentSet(
                            participant,
                            creatorActor
                        )
                    }

                    onAssignmentClearRequested: function() {
                        root.bridgeAssignmentClear()
                    }

                    onSubmitRequested: function(text, contextReference, workspaceObjectId) {
                        if (root.surfaceHost) {
                            var kind = root.surfaceHost.parseSurfaceIntent(text)
                            if (kind && kind.length > 0) {
                                if (workspace)
                                    workspace.setHostKind(kind)
                                return
                            }
                        }
                        root.contextSnapshotSync(root.buildContextSnapshotJson())
                        if (
                            !(
                                root.bridgeBusy
                                && root.engineTarget === "GROK_WORKER"
                            )
                        ) {
                            root.appendRealNode(
                                "YOU",
                                "REQUEST",
                                text,
                                contextReference
                                    + " · "
                                    + (
                                        workspace
                                        && workspace.currentObjectTitle.length > 0
                                            ? workspace.currentObjectTitle
                                            : workspaceObjectId
                                    ),
                                "SUBMITTED",
                                0,
                                ""
                            )
                        }

                        root.bridgeSubmit(
                            text,
                            contextReference,
                            workspaceObjectId
                        )
                    }

                    onStopRequested: root.bridgeStop()
                }
}

            Item {
                id: centerColumn
                objectName: "centerColumn"
                visible: !root.narrowLayout || root.narrowPane === "WORKSPACE"
                width: root.narrowLayout
                    ? body.width
                    : Math.max(
                        380,
                        body.width
                            - chatSurface.width
                            - (telemetry.visible ? telemetry.width : 0)
                            - (telemetry.visible ? 20 : 10)
                    )
                height: body.height

                Loader {
                    id: workspaceLoader
                    objectName: "workspaceLoader"
                    property real visualOffsetX: 0
                    property real visualOffsetY: 0
                    property real visualScale: 1
                    transform: [
                        Translate {
                            x: workspaceLoader.visualOffsetX
                            y: workspaceLoader.visualOffsetY
                        },
                        Scale {
                            xScale: workspaceLoader.visualScale
                            yScale: workspaceLoader.visualScale
                        }
                    ]
                    asynchronous: true
                    visible: !root.narrowLayout || root.narrowPane === "WORKSPACE"
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.bottom: utilitySurface.top
                    anchors.bottomMargin: 8
                    onLoaded: {
                        root._workspaceLoaderReady = true
                        root.updateShellProgress()
                        root.finishShellLoad()
                    }
                    onStatusChanged: {
                        if (status === Loader.Ready) {
                            root._workspaceLoaderReady = true
                            root.updateShellProgress()
                            root.finishShellLoad()
                        }
                        if (status === Loader.Error) {
                            root.workspaceLoadFailed = true
                            root.shellLoadCurrent = "LOAD FAILED"
                            root.appendShellLog(String(errorString() || "workspace"))
                        }
                    }
                }

                Loader {
                    id: utilitySurface
                    property real visualOffsetX: 0
                    property real visualOffsetY: 0
                    property real visualScale: 1
                    transform: [
                        Translate {
                            x: utilitySurface.visualOffsetX
                            y: utilitySurface.visualOffsetY
                        },
                        Scale {
                            xScale: utilitySurface.visualScale
                            yScale: utilitySurface.visualScale
                        }
                    ]
                    anchors.bottomMargin: 0
                    objectName: "utilitySurfaceLoader"
                    asynchronous: true
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    height: utilitySurface.implicitHeight
                    onLoaded: {
                        root._utilityLoaderReady = true
                        root.updateShellProgress()
                        root.bindUtility(utilitySurface.item)
                        root.finishShellLoad()
                    }
                    onStatusChanged: {
                        if (
                            status === Loader.Ready
                            || status === Loader.Error
                        ) {
                            root._utilityLoaderReady = true
                            root.updateShellProgress()
                            root.finishShellLoad()
                        }
                    }
                }
            }

            TelemetryRail {
                id: telemetry
                property real visualOffsetX: 0
                property real visualOffsetY: 0
                property real visualScale: 1
                transform: [
                    Translate {
                        x: telemetry.visualOffsetX
                        y: telemetry.visualOffsetY
                    },
                    Scale {
                        xScale: telemetry.visualScale
                        yScale: telemetry.visualScale
                    }
                ]
                visible: !root.compactTelemetry && !root.narrowLayout
                width: root.alphaTelemetryWidth
                height: body.height
                compactMode: true
                modelState: root.bridgeBusy ? "BUSY" : "READY"
                engineTarget: root.engineTarget
                grokWalletJson: root.grokWalletJson
                gptWalletJson: root.gptWalletJson
                liveVisionStatusJson: root.liveVisionStatusJson
                bridgeState: root.bridgeBusy ? "BUSY" : "CONNECTED"
                frameBorder: root.frameBorder
                frameRadius: root.frameRadius
                snippetModel: workspace ? workspace.snippetModel : null
                activeSnippet: workspace ? workspace.siteRelativePath : ""
                chatSessionsJson: root.chatSessionsJson
                activeChatSession: root.activeChatSession
                cryptoStatusJson: root.cryptoStatusJson
                onCryptoAccountChosen: function(pubkey) {
                    if (!root.surfaceHost || !root.surfaceHost.cryptoSelectAccount)
                        return
                    var raw = root.surfaceHost.cryptoSelectAccount(pubkey)
                    if (raw)
                        root.cryptoStatusJson = raw
                    root.applyCryptoWalletLabel()
                }
                onSnippetChosen: function(path) {
                    if (workspace)
                        workspace.chooseSnippet(path)
                }
                onChatSessionChosen: function(sessionId, engine) {
                    root.activeChatSession = sessionId
                    if (engine === "GPT_TUI" || engine === "GROK_TUI" || engine === "GROK_WORKER" || engine === "LOCAL_QWEN")
                        root.engineTarget = engine
                    if (engine === "GPT_TUI" && root.surfaceHost) {
                        // Let the visibility binding commit before the host
                        // validates/resumes the selected PTY.
                        Qt.callLater(function() {
                            if (root.surfaceHost)
                                root.surfaceHost.activateGptTui(sessionId)
                        })
                    }
                    if (engine === "GROK_TUI" && root.surfaceHost)
                        root.surfaceHost.resumeGrokTui(sessionId)
                }
            }
        }
    }

    Rectangle {
        id: shellLoadOverlay
        objectName: "shellLoadOverlay"
        z: 10000
        anchors.fill: parent
        visible: root.shellLoading
        color: root.canvas

        Column {
            objectName: "shellLoadFileLog"
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.margins: 18
            width: Math.min(parent.width - 36, 640)
            spacing: 4

            Text {
                width: parent.width
                text: root.shellLoadLog
                color: "#a8b0b8"
                font.family: "monospace"
                font.pixelSize: 12
                wrapMode: Text.NoWrap
            }

            Text {
                width: parent.width
                visible: root.shellLoadCurrent.length > 0
                text: root.shellLoadCurrent
                color: "#c8a97e"
                font.family: "monospace"
                font.pixelSize: 12
                wrapMode: Text.NoWrap
                elide: Text.ElideMiddle
            }
        }

        Column {
            anchors.centerIn: parent
            spacing: 14
            width: 280

            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: root.shellLoadLabel
                color: "#c8a97e"
                font.family: "monospace"
                font.pixelSize: 14
                font.bold: true
            }

            Rectangle {
                id: shellLoadTrack
                width: parent.width
                height: 8
                color: "#161616"
                border.color: root.line
                border.width: 1

                Rectangle {
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    anchors.margins: 1
                    width: Math.max(
                        0,
                        (parent.width - 2) * root.shellLoadPercent / 100
                    )
                    color: "#c8a97e"
                }

                Rectangle {
                    id: startupActivity
                    visible: root.startupStepBusy || root.startupChatBlocking
                    width: 24
                    height: parent.height - 2
                    y: 1
                    color: "#f0d6ad"

                    XAnimator {
                        target: startupActivity
                        from: 2
                        to: Math.max(
                            2,
                            shellLoadTrack.width - startupActivity.width - 2
                        )
                        duration: 750
                        loops: Animation.Infinite
                        running: root.startupStepBusy || root.startupChatBlocking
                    }
                }
            }

            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: String(Math.round(root.shellLoadPercent)) + "%"
                color: root.textMuted
                font.family: "monospace"
                font.pixelSize: 12
            }

            Text {
                width: parent.width
                visible: root.startupStepNumber > 0
                horizontalAlignment: Text.AlignHCenter
                text: "LOCAL SERVICES · STEP "
                    + String(root.startupStepNumber)
                    + "/"
                    + String(root.startupStepCount)
                    + (root.startupStepBusy
                        ? " · WORKING"
                        : (root.startupFailed ? " · FAILED" : " · STEP DONE"))
                color: root.textMuted
                font.family: "monospace"
                font.pixelSize: 10
            }

            BufferMark {
                objectName: "shellLoadBuffer"
                anchors.horizontalCenter: parent.horizontalCenter
                active: root.shellLoading
                cell: 6
            }
        }
    }

    WalletPopup {
        id: walletPopup
        objectName: "walletPopup"
        z: 9999
        visible: root.walletOpen
        x: root.walletX < 0 ? Math.max(12, root.width - 346) : root.walletX
        y: root.walletY < 0 ? 44 : root.walletY
        surfaceHost: root.surfaceHost
        frameBorder: root.frameBorder
        frameRadius: root.frameRadius
        layoutLocked: root.visualLayoutLocked
        visualWidth: root.visualSurfaceMetric("wallet", "width", -1)
        visualHeight: root.visualSurfaceMetric("wallet", "height", -1)
        statusJson: root.cryptoStatusJson
        onRequestClose: root.walletOpen = false
        onWalletStatusUpdated: function(raw) {
            root.cryptoStatusJson = raw
            root.applyCryptoWalletLabel()
        }
        onOpenDesk: {
            if (workspace)
                workspace.setHostKind("CRYPTO")
        }
        onXChanged: {
            if (visible)
                root.walletX = x
        }
        onYChanged: {
            if (visible)
                root.walletY = y
        }
        onVisibleChanged: {
            if (visible)
                walletPopup.pull()
        }
    }

    SettingsPopup {
        id: settingsPopup
        objectName: "settingsPopup"
        z: 9999
        visible: root.settingsOpen
        x: root.settingsX < 0
            ? 12
            : root.settingsX
        y: root.settingsY < 0 ? 60 : root.settingsY
        chatWidthRatio: root.alphaChatWidthRatio
        telemetryWidth: root.alphaTelemetryWidth
        accentColor: root.cyan
        frameBorder: root.frameBorder
        frameRadius: root.frameRadius
        layoutLocked: root.visualLayoutLocked
        visualWidth: root.visualSurfaceMetric("settings", "width", -1)
        visualHeight: root.visualSurfaceMetric("settings", "height", -1)
        showDemoFixtures: root.alphaShowDemoFixtures
        showProductSourceTabs: root.showProductSourceTabs
        showOpenTabInInput: root.showOpenTabInInput
        showInnerEditorChrome: root.showInnerEditorChrome
        hostKind: workspace ? workspace.hostKind : "CODE"
        engineTarget: root.engineTarget
        utilityHeight: root.alphaUtilityHeight
        desktopShell: root.desktopShell
        visualThemeId: root.visualThemeId
        visualProfileId: root.visualProfileId
        visualThemesJson: root.visualThemesJson
        visualProfilesJson: root.visualProfilesJson
        visualSurfaceRegistryJson: root.visualSurfaceRegistryJson
        visualSelectedSurface: root.visualSelectedSurface
        visualEditorMode: root.visualEditorMode
        visualSourceText: root.visualSourceText
        visualSourcePath: root.visualSourcePath
        visualSourceStatus: root.visualSourceStatus
        extensionsJson: root.workbenchExtensionsJson
        workspaceFoldersJson: JSON.stringify(root.workspaceFolders || [])
        workspaceTrusted: root.workspaceTrusted

        onCloseRequested: root.closeSettings()
        onChatWidthRatioChangedByUser: function(value) {
            root.alphaChatWidthRatio = value
            root.persistDesktopSettings()
        }
        onTelemetryWidthChangedByUser: function(value) {
            root.alphaTelemetryWidth = value
            root.persistDesktopSettings()
        }
        onAccentColorChangedByUser: function(value) {
            root.cyan = value
            root.persistDesktopSettings()
        }
        onFrameBorderChangedByUser: function(value) {
            root.frameBorder = value
            root.persistDesktopSettings()
        }
        onFrameRadiusChangedByUser: function(value) {
            root.frameRadius = value
            root.persistDesktopSettings()
        }
        onDemoVisibilityChangedByUser: function(value) {
            root.alphaShowDemoFixtures = value
            root.persistDesktopSettings()
        }
        onProductSourceTabsChangedByUser: function(value) {
            root.showProductSourceTabs = value
            root.persistDesktopSettings()
        }
        onShowOpenTabInInputChangedByUser: function(value) {
            root.showOpenTabInInput = value
            root.persistDesktopSettings()
        }
        onShowInnerEditorChromeChangedByUser: function(value) {
            root.showInnerEditorChrome = value
            root.persistDesktopSettings()
        }
        onHostKindChangedByUser: function(value) {
            if (workspace && workspace.setHostKind)
                workspace.setHostKind(value)
            root.closeSettings()
        }
        onSpawnInstanceRequested: {
            if (workspace && workspace.spawnHostInstance)
                workspace.spawnHostInstance()
            root.closeSettings()
        }
        onEngineTargetChangedByUser: function(value) {
            root.engineTarget = value
            root.persistDesktopSettings()
        }
        onUtilityHeightChangedByUser: function(value) {
            root.alphaUtilityHeight = value
            root.persistDesktopSettings()
        }
        onDesktopShellChangedByUser: function(value) {
            root.desktopShell = value
        }
        onExtensionEnabledChangedByUser: function(extensionId, enabled) {
            root.setWorkbenchExtensionEnabled(extensionId, enabled)
        }
        onResetExtensionsRequested: root.resetWorkbenchExtensions()
        onWorkspaceFoldersChangedByUser: function(foldersJson) {
            try {
                var folders = JSON.parse(foldersJson || "[]")
                root.workspaceFolders = folders instanceof Array ? folders : []
            } catch (err) {
                root.workspaceFolders = []
            }
            root.persistDesktopSettings()
        }
        onWorkspaceTrustedChangedByUser: function(value) {
            root.workspaceTrusted = Boolean(value)
            root.persistDesktopSettings()
        }
        onVisualThemeRequested: function(value) {
            root.setVisualTheme(value)
        }
        onVisualSaveThemeRequested: function(value) {
            root.saveVisualThemeAs(value)
        }
        onVisualProfileRequested: function(value) {
            root.setVisualProfile(value)
        }
        onVisualSaveProfileRequested: function(value) {
            root.saveVisualProfileAs(value)
        }
        onVisualResetProfileRequested: root.resetVisualProfile()
        onVisualSurfaceRequested: function(value) {
            root.selectVisualSurface(value)
            if (settingsPopup && settingsPopup.page === "EDITOR")
                root.openVisualSource(value)
        }
        onVisualSourceRequested: function(value) {
            root.openVisualSource(value)
        }
        onVisualLockRequested: function(value) {
            root.setVisualLock(value)
        }
        onVisualModeRequested: function(value) {
            root.setVisualEditorMode(value)
        }
        onVisualSourceSaveRequested: function(value) {
            root.saveVisualSource(value)
        }
        onVisualSourceCloseRequested: root.closeVisualSource()
        onResetVisualRequested: root.resetVisualStandard()
        onXChanged: {
            if (visible) {
                root.settingsX = x
                root.settingsMoved = true
            }
        }
        onYChanged: {
            if (visible) {
                root.settingsY = y
                root.settingsMoved = true
            }
        }
    }

    CommandPalette {
        id: commandPalette
        objectName: "commandPalette"
        parent: root.contentItem
        anchors.fill: parent
        z: 11000
        visible: root.commandPaletteOpen
        title: root.commandPaletteMode === "QUICK_OPEN"
            ? "QUICK OPEN"
            : "COMMAND PALETTE"
        placeholderText: root.commandPaletteMode === "QUICK_OPEN"
            ? "Search files, views or settings..."
            : "Type a command..."
        footerHint: root.commandPaletteMode === "QUICK_OPEN"
            ? "Ctrl+P"
            : "Ctrl+Shift+P / F1"
        commands: root.commandPaletteItems()

        onCommandRequested: function(commandId) {
            root.executeCommand(commandId)
        }
        onDismissed: root.commandPaletteOpen = false
    }

    VisualLayoutOverlay {
        id: visualLayoutOverlay
        objectName: "visualLayoutOverlay"
        parent: root.contentItem
        anchors.fill: parent
        z: 10000
        surfaceModel: root.visualSurfaceModel()
        layoutUnlocked: !root.visualLayoutLocked
        editorMode: root.visualEditorMode
        sourceSurface: root.visualSelectedSurface
        sourceText: root.visualSourceText
        sourcePath: root.visualSourcePath
        sourceStatus: root.visualSourceStatus
        frameBorder: root.frameBorder
        accentColor: root.cyan

        onSurfaceResizeRequested: function(surfaceId, corner, dx, dy) {
            root.resizeVisualSurface(surfaceId, corner, dx, dy)
        }
        onSurfaceMoveRequested: function(surfaceId, dx, dy) {
            root.moveVisualSurface(surfaceId, dx, dy)
        }
        onSourceSaveRequested: function(surfaceId, source) {
            if (root.visualSelectedSurface !== surfaceId)
                root.selectVisualSurface(surfaceId)
            root.saveVisualSource(source)
        }
        onSourceCloseRequested: root.closeVisualSource()
    }

    WebAgentCursor {
        id: deskAgentCursor
        objectName: "deskAgentCursor"
        parent: root.contentItem
        z: 10001
        visible: true
        shape: root.deskShape
        x: root.deskX - deskAgentCursor.hotX
        y: root.deskY - deskAgentCursor.hotY
    }
}
