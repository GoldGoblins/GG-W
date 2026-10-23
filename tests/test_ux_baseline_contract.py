#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
QML = PROJECT / "qml"
CONFIG = PROJECT / "config/workbench-v1.2.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def text(rel: str) -> str:
    return (PROJECT / rel).read_text(encoding="utf-8")


def context_resolver_v1_ux_contract() -> None:
    main_qml = (
        PROJECT
        / "qml/Main.qml"
    ).read_text(
        encoding="utf-8"
    )

    workspace_qml = (
        PROJECT
        / "qml/components/WorkspaceSurface.qml"
    ).read_text(
        encoding="utf-8"
    )

    composer_qml = (
        PROJECT
        / "qml/components/ContextComposer.qml"
    ).read_text(
        encoding="utf-8"
    )

    chat_node_qml = (
        PROJECT
        / "qml/components/ChatNode.qml"
    ).read_text(
        encoding="utf-8"
    )

    require(
        (
            "function persistDesktopSettings()"
            in main_qml
        ),
        "Desktop settings persist helper missing.",
    )

    require(
        (
            "function buildContextSnapshotJson()"
            in main_qml
        ),
        (
            "Recent chat snapshot "
            "builder missing."
        ),
    )

    require(
        (
            "signal contextSnapshotSync("
            "string snapshotJson)"
            in main_qml
        ),
        (
            "Dedicated snapshot signal "
            "missing."
        ),
    )

    require(
        (
            "root.contextSnapshotSync("
            "root.buildContextSnapshotJson())"
            in main_qml
        ),
        (
            "Ordinary submit does not "
            "emit snapshot first."
        ),
    )

    require(
        (
            "function contextSnapshot("
            "maximumObjects)"
            in workspace_qml
        ),
        (
            "Workspace snapshot surface "
            "missing."
        ),
    )

    require(
        (
            "string text"
            in composer_qml
            and "string contextReference"
            in composer_qml
            and "string workspaceObjectId"
            in composer_qml
        ),
        (
            "Composer transport expanded "
            "instead of preserved."
        ),
    )

    require(
        (
            "property string contextReference"
            in chat_node_qml
        ),
        (
            "ChatNode context reference "
            "regressed."
        ),
    )

    print(
        "CONTEXT_RESOLVER_UX_CONTRACT=PASS"
    )


def explicit_orchestrator_assignment_ux_contract() -> None:
    from pathlib import Path as AssignmentPath

    project = AssignmentPath(__file__).resolve().parents[1]
    composer = (
        project
        / "qml"
        / "components"
        / "ContextComposer.qml"
    ).read_text(
        encoding="utf-8",
        errors="strict",
    )
    main_qml = (
        project
        / "qml"
        / "Main.qml"
    ).read_text(
        encoding="utf-8",
        errors="strict",
    )
    main_py = (
        project
        / "main.py"
    ).read_text(
        encoding="utf-8",
        errors="strict",
    )

    required_composer = (
        "signal assignmentSetRequested(",
        "signal assignmentClearRequested()",
        "ComboBox {",
        "TextField {",
        'text: "Assign"',
        'text: "Clear"',
        "currentIndex: -1",
    )
    for marker in required_composer:
        if marker not in composer:
            raise AssertionError(
                "Explicit assignment UX marker missing: " + marker
            )

    if composer.count("signal submitRequested(") != 1:
        raise AssertionError(
            "Composer three-argument submit seam changed."
        )
    if composer.count("root.submitRequested(") != 1:
        raise AssertionError(
            "Composer submit emit cardinality changed."
        )
    if main_qml.count("signal bridgeSubmit(") != 1:
        raise AssertionError(
            "Main QML bridgeSubmit seam changed."
        )
    if main_qml.count("root.bridgeSubmit(") != 1:
        raise AssertionError(
            "Main QML bridgeSubmit emit changed."
        )
    if "@Slot(str, str, str)" not in main_py:
        raise AssertionError(
            "ChatBridge three-argument submit slot changed."
        )
    if (
        "@Slot(str, str)\n"
        "    def _setOrchestratorAssignment"
    ) not in main_py:
        raise AssertionError(
            "Explicit assignment setter slot missing."
        )
    if (
        "@Slot()\n"
        "    def _clearOrchestratorAssignment"
    ) not in main_py:
        raise AssertionError(
            "Explicit assignment clear slot missing."
        )


def main() -> int:
    explicit_orchestrator_assignment_ux_contract()
    context_resolver_v1_ux_contract()
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    main_qml = text("qml/Main.qml")
    telemetry = text("qml/components/TelemetryRail.qml")
    composer = text("qml/components/ContextComposer.qml")
    chat_node = text("qml/components/ChatNode.qml")
    main_py = text("main.py")
    settings_surface = text("qml/components/SettingsSurface.qml")
    settings_appearance = text(
        "qml/components/SettingsAppearanceModule.qml"
    )
    settings_developer = text(
        "qml/components/SettingsDeveloperModule.qml"
    )
    settings_extensions = text(
        "qml/components/SettingsExtensionsModule.qml"
    )
    settings_workspace = text(
        "qml/components/SettingsWorkspaceModule.qml"
    )
    settings_chat = text("qml/components/SettingsChatModule.qml")
    settings_layout = text("qml/components/SettingsLayoutModule.qml")
    require(
        "Interactive desktop" in settings_layout
        and "desktopShellChangedByUser" in settings_layout,
        "Interactive desktop setting missing.",
    )
    workspace_alpha = text("qml/components/WorkspaceSurface.qml")

    for marker in (
        'property bool alphaShowDemoFixtures: false',
        'property real alphaChatWidthRatio: 0.31',
        'property int alphaTelemetryWidth: 168',
        'property int alphaUtilityHeight: 112',
        'objectName: "topBarSettingsButton"',
        'objectName: "topBarReloadButton"',
        'objectName: "topBarFullscreenButton"',
        'text: "RELOAD"',
        'text: root.appFullscreen ? "EXIT FULLSCREEN" : "FULLSCREEN"',
        'property bool appFullscreen: false',
        'Window.FullScreen',
        'objectName: "shellLoadOverlay"',
        'objectName: "shellLoadFileLog"',
        'shellLoadLabel: "LOADING..."',
        "function beginShellLoad(",
        "function unloadDesktopShell(",
        "function loadDesktopShell(",
        "function finishShellLoad(",
        "function hydrateDesktopShell(",
        "function applyCryptoWalletLabel(",
        "function loadNextShellFile(",
        "Qt.createComponent(",
        'objectName: "workspaceLoader"',
        "asynchronous: true",
        "shellLoadQueueJson",
        'text: "LOCAL · ALPHA"',
        'objectName: "topBarWalletChip"',
        "body.width * root.alphaChatWidthRatio",
        "width: root.alphaTelemetryWidth",
        'property string engineTarget: "GROK_TUI"',
        "parseSurfaceIntent(text)",
        "function beginGrokWorkerStream(",
        'objectName: "grokTuiHost"',
        'objectName: "gptTuiHost"',
        'objectName: "flowTuiHost"',
        'leftLegend: "CHAT · UNIVERSAL OPERATIONAL STREAM"',
        "chatChrome.padding",
        "chatChrome.topChrome",
        "ScrollBar.AlwaysOff",
        "GrokTuiHole {",
        "GrokWorkStream {",
        "Loader {",
        'rightLegend: "BRIDGE · CONNECTED"',
    ):
        require(
            marker in main_qml,
            "Alpha A1 Main marker missing: " + marker,
        )

    require(
        "function pullShellSources(" not in main_qml,
        "Fake shell source list still drives loading.",
    )
    require(
        "id: shellLoadTimer" not in main_qml,
        "Fake loading timer still present.",
    )
    require(
        "function advanceShellLoad(" not in main_qml,
        "Fake loading ticker still present.",
    )
    require(
        "hydrateDesktop()" in main_qml,
        "Shell overlay still hides before desktop hydrate.",
    )
    require(
        "utilitySurface.status === Loader.Loading" in main_qml,
        "Shell overlay still hides before UtilitySurface is ready.",
    )
    require(
        "function applyCryptoWalletLabel(" in workspace_alpha,
        "Workspace still waits for the CRYPTO tab to show the wallet chip.",
    )
    require(
        "property bool busy: false" in text("qml/components/GgFrame.qml"),
        "Frame busy mark missing.",
    )
    require(
        "objectName: \"bufferMark\"" in text("qml/components/BufferMark.qml"),
        "BufferMark component missing.",
    )

    for marker in (
        'objectName: "telemetrySnippetList"',
        "signal snippetChosen(string path)",
        'leftLegend: "SNIPPETS"',
        "* 2 / 5",
        'objectName: "grokWallet"',
        'objectName: "telemetryChatList"',
        "snippetFrame.height - 10) / 2",
        'leftLegend: "CHATS"',
        'rightLegend: "MEMORY"',
        'objectName: "telemetryCryptoWallet"',
        'leftLegend: "CRYPTO"',
        "signal chatSessionChosen(string sessionId, string engine)",
        "cursorShape: Qt.PointingHandCursor",
        "cryptoStatusJson",
        "CTX  ",
        "ALL  ",
        "TURN ",
        "LIVE ",
        "WEEK ",
    ):
        require(
            marker in telemetry,
            "Telemetry snippet rail marker missing: " + marker,
        )

    for marker in (
        'property bool assignmentExpanded: false',
        "visible: root.assignmentExpanded",
        'objectName: "orchestratorAssignmentOptionsButton"',
        "visible: root.busy",
        'objectName: "engineTargetSelector"',
        '"LOCAL QWEN"',
        '"GROK WORKER"',
        '"GROK TUI"',
        'property string engineTarget: "GROK_TUI"',
        "signal engineTargetRequested(string value)",
        "People · close",
        "GG-AI-installator",
        "id: engineFooter",
        "id: peopleRow",
        "id: sendRow",
        'anchors.right: inputFrame.right',
        'text: "QWEN"',
        'text: "GROK"',
        'text: "GROK TUI"',
        'objectName: "chatDiskLamp"',
        'objectName: "chatLampRail"',
        'anchors.verticalCenter: chatLampRail.verticalCenter',
        'text: " | "',
        "chatIoActive",
        "anchors.bottom: engineFooter.top",
        "implicitHeight: root.engineTarget === \"GROK_TUI\"",
        "leftLegend: root.showOpenTab",
        'property string contextReference: "@current"',
        'property bool showOpenTab: false',
    ):
        require(
            marker in composer,
            "Alpha A1 composer marker missing: " + marker,
        )
    require(
        "engineFooterLegendPlate" not in composer,
        "Composer still uses the GPTUI-only footer mask plate.",
    )

    for marker in (
        "property bool compactMode: true",
        "root.compactMode ? 168 : 220",
        "readonly property string bridgeDetails:",
    ):
        require(
            marker in telemetry,
            "Alpha A1 telemetry marker missing: " + marker,
        )

    for marker in (
        "function openSettings()",
        "function closeSettings()",
        "SettingsSurface {",
        "root.showDemoFixtures",
        "root.settingsOpen",
        'objectName: "workspaceObjectNodeRail"',
        "function boundObjectActivityState()",
        "function syncObjectActivities()",
        "WorkspaceObjectNode {",
    ):
        require(
            marker in workspace_alpha,
            "Alpha A1 Workspace marker missing: " + marker,
        )

    workspace_object_node = text(
        "qml/components/WorkspaceObjectNode.qml"
    )
    for marker in (
        'objectName: "workspaceObjectNode"',
        "signal activated(string objectId)",
        'text: "DEMO / SAMPLE · NO EXECUTION"',
        "percentage: -1",
        "REAL_LOCAL_FILE",
        "SYNTHETIC_UI_FIXTURE",
        "@current",
    ):
        require(
            marker in workspace_object_node,
            "Workspace object node marker missing: " + marker,
        )

    workspace_surface = text("qml/components/WorkspaceSurface.qml")
    for marker in (
        'objectId: "ws.terminal.user"',
        'objectType: "USER_TERMINAL"',
        'objectId: "ws.app.external"',
        'objectType: "EXTERNAL_APP"',
        'objectId: "ws.web.stub"',
        "ExternalSurface",
        "id: userTerminalHost",
        "fillHost: true",
        'objectName: "workspaceHostKindSelector"',
        "function setHostKind(",
        "function spawnHostInstance()",
        "function closeHostInstance(",
        "function saveScratchBuffer()",
        "function saveScratchAs(",
        "function applyExternalFile(",
        "onWorkspaceFileChanged(",
        "function scratchNameFromUrl(",
        'text: "SAVE AS"',
        "id: scratchSaveDialog",
        "function applyChatCodeToCurrent(",
        'objectId: "ws.file.scratch.1"',
        "showProductSourceTabs",
        'objectName: "workspaceSpawnInstanceButton"',
        'objectName: "workspaceCloseInstanceButton"',
        'objectName: "workspaceSaveScratchButton"',
        'objectName: "workspaceSaveScratchRow"',
        "scratchSaveRow.implicitWidth",
        "function openSaveAsDialog()",
        "function applySaveAsUrl(",
        'title: "SAVE AS"',
        'text: "CODE"',
        'text: "CMD"',
        'text: "WEB"',
        'text: "EXT"',
        'text: "SITE"',
        'text: "CRYPTO"',
        'text: "MP"',
        'text: "TMOG"',
        'text: "OSINT"',
        'text: "RESEARCH"',
        'text: "MEDIA"',
        'text: "DRAW"',
        'text: "GAME ENGINE"',
        'text: "NODES"',
        'text: "FLOW"',
        'hostKind === "CRYPTO"',
        'hostKind === "MARKETPLACE"',
        'hostKind === "TMOG"',
        'hostKind === "OSINT"',
        'hostKind === "MEDIA"',
        'hostKind === "DRAW"',
        'hostKind === "GAME_ENGINE"',
        'hostKind === "NODES"',
        'hostKind === "FLOW"',
        'objectName: "workspaceMarketplacePane"',
        'objectName: "workspaceTmogPane"',
        'objectName: "workspaceOsintPane"',
        'objectName: "workspaceResearchPane"',
        'objectName: "workspaceMediaPane"',
        'objectName: "workspaceDrawPane"',
        'objectName: "workspaceGameEnginePane"',
        'objectName: "workspaceNodePane"',
        'objectName: "workspaceAgentFlowPane"',
        "MarketplaceSurface {",
        "MediaSurface {",
        "DrawSurface {",
        "GameEngineSurface {",
        "NodeSurface {",
        "function applyLiveReload()",
        "liveEpoch",
        'objectName: "workspaceWebHost"',
        'objectName: "workspaceWebAddress"',
        "function goBrowse(",
        "function resetWebTab(",
        "function webTabCount(",
        "function rememberBrowse(",
        "siteFileObjectId(",
        'objectName: "workspaceSiteHost"',
        'objectName: "workspaceSiteImportBar"',
        "function importSiteFromDialog(",
        "function importSiteSqlFromDialog(",
        "IMPORT SQL",
        "function toggleSitePreview()",
        "function toggleSitePreviewFullscreen()",
        "function ensureSitePreview()",
        "STOP PREVIEW",
        "EDIT IN CODE",
        'objectName: "workspaceSiteFullscreenButton"',
        'property bool sitePreviewFullscreen: false',
        'objectName: "sitePreviewFullscreenWindow"',
        'objectName: "sitePreviewFullscreenLoader"',
        'objectName: "sitePreviewFullscreenHoverZone"',
        "acceptedButtons: Qt.NoButton",
        "Shortcut {",
        "showFullScreen()",
        "Key_Escape",
        "function saveSiteBuffer()",
        'objectName: "workspaceSiteImportStatus"',
        "onSiteImportProgress(",
        'objectType: "SITE_PROJECT"',
        "anchors.bottom: workspaceFrame.bottom",
        "anchors.bottomMargin: -7",
        'objectName: "workspaceCodeScroll"',
    ):
        require(
            marker in workspace_surface,
            "Workspace host MVP marker missing: " + marker,
        )
    external_surface = text("qml/components/ExternalSurface.qml")
    require(
        'objectName: "workspaceExternalHole"' in external_surface,
        "EXT Blender hole missing.",
    )
    web_pane = text("qml/components/WebPane.qml")
    require(
        "function hrefAllowed(" in web_pane,
        "WEB pane missing local href allow check.",
    )
    require(
        'href.indexOf("http://127.0.0.1:") === 0' in web_pane,
        "SITE pane hrefAllowed still rejects localhost PHP preview.",
    )
    require(
        "engineActive: true" in web_pane,
        "WEB engine still tears down on opacity.",
    )
    require(
        "wantEngine" in web_pane and "engineArmed" in web_pane,
        "WEB engine is not lazily armed.",
    )
    require(
        "active: root.engineArmed" in web_pane,
        "WEB engine still constructs Chromium before first use.",
    )
    require(
        "active: root.visible" not in web_pane,
        "WEB engine still tears down on visibility.",
    )
    require(
        "request.openIn(popup)" in web_pane
        and "function takeView(" in web_pane
        and "popupViewReady" in web_pane
        and "function adoptPopupView(" in workspace_surface,
        "WP Admin new-window still does not open a real tab like a browser.",
    )
    require(
        'storageName: "gg-web"' in web_pane
        and "ForcePersistentCookies" in web_pane
        and "offTheRecord: false" in web_pane
        and "profile: sessionProfile" in web_pane,
        "WEB tabs still use an off-the-record profile, so login cookies die.",
    )
    require(
        "function abortStuckLoad(" in web_pane
        and "function haltEngine(" in web_pane
        and "pageLoadTimeoutMs: 60000" in web_pane
        and "id: pageLoadWatch" in web_pane
        and "engine.stop" in web_pane
        and 'engine.url = "about:blank"' in web_pane
        and "Sidan laddade inte inom 60 sekunder" in web_pane,
        "WEB pane still lets Chromium load forever without aborting.",
    )
    require(
        "webTab.holdWebEngine = false" in workspace_surface
        and "haltEngine" in workspace_surface,
        "Background WEB tabs still keep extra Chromium engines alive.",
    )
    web_cursor = text("qml/components/WebAgentCursor.qml")
    require(
        "enabled: false" in web_cursor,
        "Gold pointer still swallows mouse events before Chromium.",
    )
    grok_tui_hole = text("qml/components/GrokTuiHole.qml")
    require(
        "QtWebEngine" not in grok_tui_hole,
        "GROK TUI still boots Chromium for a cell grid.",
    )
    require(
        'objectName: "grokTuiHost"' in grok_tui_hole
        and 'objectName: "grokTuiPrompt"' in grok_tui_hole,
        "GROK TUI hole lost its host id.",
    )
    require(
        "clip: true" in grok_tui_hole,
        "GROK TUI hole still lets glyphs paint past the right edge.",
    )
    require(
        "ensureWebEngine" in workspace_surface
        and "webPaneSource" in workspace_surface
        and "WebPane.qml?r=" in workspace_surface
        and "function applyPageUrl(" in web_pane
        and "url: root.pageUrl" not in web_pane
        and "function applyWebOperator(" in workspace_surface
        and 'root.setHostKind("WEB")' in workspace_surface[workspace_surface.index("function applyWebOperator(") : workspace_surface.index("function flushPendingWebOp(")]
        and "WEB_NOT_FOCUSED" not in workspace_surface
        and "function playOperator(" in web_pane
        and 'objectName: "webAgentCursor"' in web_pane
        and 'objectName: "deskAgentCursor"' in main_qml
        and "WebAgentCursor" in web_pane
        and "agentCursorShape" in web_pane
        and "function flushPendingWebOp(" in workspace_surface
        and "holdWebEngine" in workspace_surface
        and "clickRipple" not in web_pane
        and "ripple.play()" in web_pane
        and "function _elFindJs(" in web_pane
        and "WheelEvent" in web_pane
        and "function _scroll(" in web_pane
        and "function _grabViewNow(" in web_pane
        and "id: grabWait" in web_pane,
        "WEB Chromium is still type-bound into workspace boot.",
    )
    host_py = text("backend/chat_surface_host.py")
    require(
        "def _desk_walk_visible" in host_py
        and "childItems" in host_py
        and "RenderWidget" in host_py
        and "grokTuiHost" in host_py
        and "findChildren(" not in host_py[host_py.index("def _desk_list_names") : host_py.index("def _desk_find_label")]
        and 'property("workspace")' in host_py[host_py.index("def _desk_visible_items") : host_py.index("def _desk_item_shown")]
        and "findChild(" not in host_py[host_py.index("def _desk_find") : host_py.index("def _desk_class_name")]
        and "names = self._desk_list_names" in host_py[host_py.index('if action == "SNAPSHOT"') : host_py.index('if action == "KEY"')],
        "Desk FIND still walks Chromium internals.",
    )
    require(
        "grabWindow" in host_py[host_py.index("def _desk_grab") : host_py.index("def _desk_send_move")],
        "Desk snapshot still skips QQuickWindow.grabWindow.",
    )
    require(
        "WebPane {" not in workspace_surface,
        "WEB Chromium still compiles with WorkspaceSurface.",
    )
    require(
        (PROJECT / "qml/components/webCursorPack.js").is_file()
        and (PROJECT / "qml/components/WebAgentCursor.qml").is_file()
        and (PROJECT / "qml/components/web-cursors/pointer.png").is_file()
        and (PROJECT / "qml/components/web-cursors/wait.png").is_file()
        and (PROJECT / "qml/components/web-cursors/text.png").is_file()
        and (PROJECT / "qml/components/web-cursors/default.png").is_file(),
        "Visible WEB cursor pack is incomplete.",
    )

    for marker in (
        'objectName: "workspaceSettingsSurface"',
        'readonly property string themeId: "obsidian-ledger-standard"',
        "signal chatWidthRatioChangedByUser(real value)",
        "signal telemetryWidthChangedByUser(int value)",
        "signal accentColorChangedByUser(color value)",
        "signal frameBorderChangedByUser(color value)",
        "signal frameRadiusChangedByUser(int value)",
        "signal demoVisibilityChangedByUser(bool value)",
        "signal showOpenTabInInputChangedByUser(bool value)",
        "signal hostKindChangedByUser(string value)",
        "signal engineTargetChangedByUser(string value)",
        "signal utilityHeightChangedByUser(int value)",
        "SettingsAppearanceModule {",
        "SettingsLayoutModule {",
        "SettingsChatModule {",
        "SettingsWorkspaceModule {",
        "SettingsActivityModule {",
        "SettingsDeveloperModule {",
        "SettingsExtensionsModule {",
    ):
        require(
            marker in settings_surface,
            "Alpha A1/A1.2 Settings shell marker missing: " + marker,
        )

    for marker in (
        "signal frameBorderChangedByUser(color value)",
        "signal frameRadiusChangedByUser(int value)",
        "TapHandler {",
        "GgSlider {",
        "grayToken",
    ):
        require(
            marker in settings_appearance,
            "Settings Appearance marker missing: " + marker,
        )

    for rel, marker in (
        ("qml/components/GgButton.qml", "signal clicked()"),
        ("qml/components/GgSwitch.qml", "signal toggled()"),
        ("qml/components/GgSlider.qml", "handle: Rectangle {"),
        ("qml/components/GgCheck.qml", "signal toggled()"),
        ("qml/components/GgField.qml", 'placeholderTextColor: "#5d6670"'),
        ("qml/components/GgScrollBar.qml", "interactive: true"),
    ):
        require(
            marker in text(rel),
            "Themed primitive missing: " + rel,
        )
    require(
        "GgButton {" in settings_surface
        and settings_surface.count("Button {")
        == settings_surface.count("GgButton {"),
        "Settings still uses stock Qt buttons.",
    )
    require(
        "GgSwitch {" in settings_layout
        and settings_layout.count("Switch {")
        == settings_layout.count("GgSwitch {"),
        "Layout still uses stock Qt switches.",
    )
    require(
        "GgCheck {" in settings_chat
        and "CheckBox {" not in settings_chat,
        "Chat settings still uses stock Qt checkboxes.",
    )
    live_aid_work = text("qml/components/ChatLiveAidWork.qml")
    require(
        "GgButton {" in live_aid_work
        and live_aid_work.count("Button {")
        == live_aid_work.count("GgButton {"),
        "Live Aid still uses stock Qt buttons.",
    )

    for marker in (
        'text: "Show DEMO / SAMPLE fixtures"',
        'text: "Show product source files"',
        "LIVE alpha hides synthetic fixtures by default. ",
    ):
        require(
            marker in settings_developer,
            "Settings Developer marker missing: " + marker,
        )

    for marker in (
        'leftLegend: "WORKSPACE"',
        "signal hostKindChangedByUser(string value)",
        'text: "New tab +"',
        'model: ["CODE", "TERMINAL", "WEB", "EXTERNAL", "SITE", "CRYPTO", "MARKETPLACE", "TMOG", "OSINT", "RESEARCH", "MEDIA", "DRAW", "GAME_ENGINE", "NODES", "FLOW"]',
    ):
        require(
            marker in settings_workspace,
            "Settings Workspace marker missing: " + marker,
        )

    for marker in (
        'leftLegend: "CHAT"',
        "signal engineTargetChangedByUser(string value)",
        'text: "QWEN"',
        'text: "GROK"',
    ):
        require(
            marker in settings_chat,
            "Settings Chat marker missing: " + marker,
        )

    for marker in (
        "signal utilityHeightChangedByUser(int value)",
        "Media / Utilities height · ",
    ):
        require(
            marker in settings_layout,
            "Settings Layout marker missing: " + marker,
        )

    for marker in (
        "Built-in contributions are the VS Code-style extension seam ",
        "The registry describes what is already in the app; it never ",
    ):
        require(
            marker in settings_extensions,
            "Settings Extensions marker missing: " + marker,
        )

    require(
        cfg["primary_surfaces"]["chat"] == "UNIVERSAL_OPERATIONAL_STREAM",
        "Chat ownership mismatch.",
    )
    require(
        cfg["primary_surfaces"]["workspace"] == "VISUAL_MULTI_OBJECT_SURFACE",
        "Workspace ownership mismatch.",
    )
    require(cfg["composer"]["editable"] is True, "Composer not editable.")
    require(
        cfg["composer"]["bridge"] == "CONNECTED_LOCAL_MODEL",
        "Composer bridge mismatch.",
    )
    require(
        cfg["integrations"]["model"] == "ENABLED_LOCAL_CHAT",
        "Model integration mismatch.",
    )
    require(
        cfg["integrations"]["real_command_execution"]
        == "ENABLED_FIXED_GREEN_SAFE_TOOLS",
        "Safe Tools execution integration mismatch.",
    )
    require(
        cfg["safe_tools"]["authority"]
        == "GREEN_LOCAL_TYPED_SAFE_TOOLS_V1",
        "Safe Tools authority mismatch.",
    )
    require(
        cfg["safe_tools"]["profiles"]
        == ["READ", "SEARCH", "GIT", "TEST", "RUN"],
        "Safe Tools profile list mismatch.",
    )
    require(
        cfg["limited_write"]["authority"]
        == "YELLOW_LOCAL_CURRENT_EXACT_PATCH_V1",
        "Limited Write authority mismatch.",
    )
    require(
        cfg["limited_write"]["target_workspace_object_id"]
        == "ws.file.context-composer",
        "Limited Write Workspace target mismatch.",
    )
    require(
        cfg["limited_write"]["target_source_path"]
        == "qml/components/ContextComposer.qml",
        "Limited Write source target mismatch.",
    )
    require(
        cfg["limited_write"]["model_autonomous_write_invocation"]
        == "DISABLED_V1",
        "Autonomous Limited Write invocation enabled.",
    )
    require(
        cfg["limited_write"]["status"] == "VERIFIED_LIVE",
        "Limited Write human E2E status not promoted.",
    )
    require(
        cfg["integrations"]["autonomy"]
        == "ENABLED_TASK_BOUND_CANDIDATE_V1",
        "Autonomy integration mismatch.",
    )
    require(
        cfg["integrations"]["control_plane"]
        == "ENABLED_TYPED_CONTROL_PLANE_V1",
        "Control Plane integration mismatch.",
    )
    require(
        cfg["control_plane"]["stop_priority"]
        == "PARSED_BEFORE_BUSY_GATE",
        "Control Plane stop priority mismatch.",
    )
    autonomy = cfg["autonomy"]
    require(
        autonomy["status"] == "IMPLEMENTED_PENDING_HUMAN_E2E",
        "Autonomy candidate status mismatch.",
    )
    require(
        autonomy["architecture"]
        == "REUSE_EXISTING_K7_COGNITIVE_HIERARCHY",
        "Autonomy cognitive hierarchy binding mismatch.",
    )
    require(
        autonomy["parallel_agent_brain"] == "FORBIDDEN",
        "Parallel agent brain unexpectedly enabled.",
    )
    require(
        autonomy["flat_model_command_loop"] == "FORBIDDEN",
        "Flat model command loop unexpectedly enabled.",
    )
    require(
        autonomy["host_write_authority"]
        == "NONE_BEFORE_SEPARATE_APPROVAL",
        "Autonomy host write boundary mismatch.",
    )
    require(
        autonomy["self_authorization"] == "FORBIDDEN",
        "Autonomy self-authorization boundary mismatch.",
    )
    selection = cfg.get("chat_text_selection")
    require(
        isinstance(selection, dict),
        "Chat text selection configuration missing.",
    )
    require(
        selection["body_renderer"] == "READ_ONLY_TEXTEDIT",
        "Chat body renderer is not read-only TextEdit.",
    )
    require(selection["editable"] is False, "Chat body became editable.")
    require(
        selection["mouse_selection"] is True,
        "Chat mouse selection disabled.",
    )
    require(
        selection["keyboard_selection"] is True,
        "Chat keyboard selection disabled.",
    )
    require(
        selection["copy_support"] == "NATIVE_TEXTEDIT_CLIPBOARD",
        "Chat clipboard contract mismatch.",
    )
    require(
        selection["status"] == "VERIFIED_LIVE"
        and selection["human_e2e_status"] == "VERIFIED_LIVE",
        "Chat text selection human E2E status not reconciled.",
    )
    require(
        cfg["workspace"]["current_context_mode"]
        == "ALLOWLISTED_LOCAL_FILE_READ_AT_SUBMIT",
        "Real @current context mode mismatch.",
    )
    require(
        cfg["workspace"]["synthetic_fixture_context_policy"] == "BLOCK",
        "Synthetic context policy mismatch.",
    )
    require(
        cfg["workspace"]["object_nodes"] == "VISIBLE_LIVING_BLOCKS",
        "Workspace object-node grammar mismatch.",
    )
    require(
        cfg["workspace"]["object_node_activity"]
        == "BOUND_TO_REAL_OBJECT_STATE",
        "Workspace object-node activity binding mismatch.",
    )
    require(
        cfg["workspace"]["object_node_layout_persistence"] == "NONE",
        "Workspace object-node layout persistence expanded.",
    )
    require(
        cfg["workspace"]["object_node_synthetic_policy"]
        == "DEMO_SAMPLE_NO_EXECUTION",
        "Workspace object-node synthetic policy mismatch.",
    )

    workspace = (
        text("qml/components/WorkspaceSurface.qml")
        + "\n"
        + text("qml/components/ChatLiveAidWork.qml")
    )


    for marker in (
        'objectName: "workspaceSurface"',
        "property var liveAidBackend: null",
        'objectName: "workspaceCodeEditor"',
        "selectByKeyboard: true",
        "persistentSelection: true",
        "SelectionGuard {",
        "function loadCurrentAuthoringBuffer()",
        "function requestLiveAidAnalysis()",
        "analysisTimer.restart()",
        "function onResultReady(objectId, payloadJson)",
        "function onAnalysisFailed(objectId, message)",
        "LiveAidObject {",
        '"BUFFER · UNSAVED · DISK UNCHANGED"',
        "disk_write_authority",
    ):
        require(
            marker in workspace or marker in main_py,
            "Missing Stage B Live Aid marker: " + marker,
        )

    for marker in (
        "class LiveAidQtBridge(QObject):",
        "resultReady = Signal(str, str)",
        "analysisFailed = Signal(str, str)",
        "@Slot(str, result=str)",
        "@Slot(str, str, str, str)",
        "LiveAidService(self._repo_root)",
        'root.findChild(',
        '"workspaceSurface"',
        '"liveAidBackend"',
        "live_aid_bridge",
    ):
        require(
            marker in main_py,
            "Missing Stage B backend bridge marker: " + marker,
        )

    require(
        "PERSISTENT_DISK_WRITE_FROM_EDITOR" not in workspace,
        "Workspace editor gained implicit persistent-write semantics.",
    )

    for marker in (
        'property string repairState: "IDLE"',
        'property string repairOldText: ""',
        'property string repairNewText: ""',
        "function requestLiveAidRepair()",
        "function requestApplyRepair()",
        "root.liveAidBackend.requestRepair(",
        "root.liveAidBackend.applyRepair(",
        "function onRepairReady(objectId, payloadJson)",
        "function onRepairFailed(objectId, message)",
        "function onRepairApplied(",
        'objectName: "workspaceRepairButton"',
        'objectName: "workspaceApplyRepairButton"',
        '"UNTRUSTED PROPOSAL ONLY · NO APPLY"',
        '"AI PROPOSAL · UNTRUSTED · OLD: "',
        '"APPLY PROPOSAL · BUFFER ONLY"',
        '"PREFLIGHT REQUIRED · NO SAVE · NO EXECUTION"',
    ):
        require(
            marker in workspace,
            "Missing Stage D repair marker: " + marker,
        )

    for marker in (
        "REPAIR_MODEL_RUNNER_PATH",
        "repairReady = Signal(str, str)",
        "repairFailed = Signal(str, str)",
        "repairApplied = Signal(str, str, str)",
        "def requestRepair(",
        "def applyRepair(",
        "repair_model_runner.validate_request(",
        "repair_model_runner.validate_response(",
    ):
        require(
            marker in main_py
            or marker in "".join(main_py.split()),
            "Missing Stage D backend marker: " + marker,
        )

    for marker in (
        'property string preflightState: "NOT RUN"',
        "function requestLiveAidPreflight()",
        "root.liveAidBackend.preflight(",
        "function onPreflightReady(objectId, payloadJson)",
        "function onPreflightFailed(objectId, message)",
        'objectName: "workspacePreflightButton"',
        '"QML PREFLIGHT · RUNNING"',
        '"QML GATE PREFLIGHT · RUNNING · "',
        '"PREFLIGHT RESULT STALE · "',
        '" · PROFILE BOUND · REPORT "',
    ):
        require(
            marker in workspace,
            "Missing Stage C QML preflight marker: " + marker,
        )

    for marker in (
        "PREFLIGHT_RUNNER_PATH",
        "preflightReady = Signal(str, str)",
        "preflightFailed = Signal(str, str)",
        "def _preflight_finished(",
        "def preflight(",
        "qml_preflight_runner.validate_request(",
        "qml_preflight_runner.validate_response(",
    ):
        require(
            marker in main_py,
            "Missing Stage C backend preflight marker: " + marker,
        )

    for marker in (
        '"ws.file.context-composer"',
        'title: "ContextComposer.qml"',
        'provenanceClass: "REAL_LOCAL_FILE"',
        'sourcePath: "qml/components/ContextComposer.qml"',
        'objectName: "workspaceSurface"',
        'objectName: "workspaceCodeEditor"',
        '"BUFFER · DISK BASE"',
        '"BUFFER · UNSAVED · DISK UNCHANGED"',
        "function loadCurrentAuthoringBuffer()",
        "function requestLiveAidAnalysis()",
        "LiveAidObject {",
        '"DISK SHA · " + payload.source_sha256',
    ):
        require(
            marker in workspace,
            "Missing real Workspace marker: " + marker,
        )

    for marker in (
        "signal bridgeSubmit(",
        "signal bridgeStop()",
        "root.bridgeSubmit(",
        "function setBridgeActivity(",
        "onStopRequested: root.bridgeStop()",
        "function appendRealNode(",
        'rightLegend: "BRIDGE · CONNECTED"',
        'modelState: root.bridgeBusy ? "BUSY" : "READY"',
        'bridgeState: "CONNECTED"',
        "SYNTHETIC_UI_FIXTURE",
        "REAL_UI_STATE",
    ):
        require(marker in main_qml, "Missing Main.qml marker: " + marker)

    require(
        "LOCAL CHAT BRIDGE · NOT CONNECTED" not in main_qml,
        "Stale blocked bridge node remains.",
    )
    require(
        'rightLegend: "BRIDGE · NOT CONNECTED"' not in main_qml,
        "Stale chat legend remains.",
    )

    require(
        "signal submitRequested(" in composer,
        "Composer submit seam missing.",
    )
    require(
        "root.submitRequested(" in composer,
        "Composer submit emit missing.",
    )
    submit_start = composer.find(
        "function submit()"
    )
    submit_end = composer.find(
        "readonly property bool canSend:",
        submit_start,
    )
    require(
        submit_start >= 0
        and submit_end > submit_start,
        "Composer submit function boundary missing.",
    )
    submit_source = composer[
        submit_start:submit_end
    ]
    submit_markers = (
        "var wasBusy = root.busy",
        "root.submitRequested(",
        "root.engineTarget === \"GROK_WORKER\"",
        "root.engineTarget === \"GROK_TUI\"",
        'input.text = ""',
    )
    for marker in submit_markers:
        require(
            submit_source.count(marker) == 1,
            "Busy composer regression marker mismatch: "
            + marker,
        )
    submit_positions = [
        submit_source.index(marker)
        for marker in submit_markers
    ]
    require(
        submit_positions == sorted(
            submit_positions
        ),
        "Busy composer submit ordering mismatch.",
    )
    for marker in (
        "signal stopRequested()",
        "id: stopButton",
        "enabled: root.busy",
        "onClicked: root.stopRequested()",
    ):
        require(marker in composer, "Composer Stop seam missing: " + marker)

    require(
        chat_node.count("TextEdit {") == 1,
        "ChatNode must contain exactly one selectable body TextEdit.",
    )
    for marker in (
        "id: bodyTextView",
        "text: root.speechText",
        "function fencesFromText(",
        "function textWithoutFences(",
        "readOnly: true",
        "selectByMouse: true",
        "selectByKeyboard: true",
        "persistentSelection: true",
        "textFormat: TextEdit.PlainText",
        "wrapMode: TextEdit.WordWrap",
        "SelectionGuard {",
    ):
        require(
            marker in chat_node,
            "Selectable ChatNode marker missing: " + marker,
        )
    require(
        "wrapMode: Text.WordWrap" not in chat_node,
        "Legacy non-selectable ChatNode body renderer remains.",
    )

    for marker in (
        'property string modelState: "READY"',
        'property string bridgeState: "CONNECTED"',
        "Local model runner is connected.",
        "Skriv vad du vill göra i chatten.",
        "svara ja för att fortsätta eller nej för att avbryta.",
        "Inga hashvärden, tokens eller specialkommandon behövs.",
        "Login och 2FA görs synligt av dig",
    ):
        require(marker in telemetry, "Telemetry marker missing: " + marker)

    for forbidden in (
        'leftLegend: "AUTHORITY"',
        'rightLegend: root.actionAuthority',
        "SAFE TOOLS · BOUND",
        "WRITE · APPROVAL",
        "mandateRailJson",
        "setMandateRail",
        "actionAuthority",
        "scopeAuthority",
        "mandateLabel",
        "networkAuthority",
    ):
        require(
            forbidden not in telemetry,
            "Telemetry still exposes a legacy authority marker: " + forbidden,
        )
    for forbidden in (
        "mandateRailJson",
        "setMandateRail",
        "actionAuthority",
        "scopeAuthority",
        "mandateLabel",
        "networkAuthority",
    ):
        require(
            forbidden not in main_qml,
            "Main still carries the removed authority rail state: " + forbidden,
        )
    require(
        'rightLegend: "AUTHORITY · " + root.actionAuthority' not in main_qml,
        "Main header still exposes the legacy authority marker.",
    )

    all_qml = "\n".join(
        p.read_text(encoding="utf-8")
        for p in sorted(QML.rglob("*.qml"))
    )
    for forbidden in (
        "XMLHttpRequest",
        "WebSocket",
        "Qt.openUrlExternally",
        "Process {",
        "QProcess",
        "subprocess",
        "gg_orchestrator",
    ):
        require(forbidden not in all_qml, "Forbidden QML marker: " + forbidden)

    require("class ChatBridge(QObject)" in main_py, "ChatBridge missing.")
    require("@Slot(str, str, str)" in main_py, "Submit slot missing.")
    for marker in (
        "def resolve_workspace_context(",
        "def build_effective_prompt(",
        "GROK_WORKSPACE_ALLOWLIST as WORKSPACE_CONTEXTS",
        "compile_chat_prompt(",
    ):
        require(marker in main_py, "Missing @current backend marker: " + marker)
    grok_contract = text("backend/grok_worker_contract.py")
    for marker in (
        '"provenance": "REAL_LOCAL_FILE"',
        '"qml/components/ContextComposer.qml"',
        '"ws.file.context-composer"',
    ):
        require(
            marker in grok_contract,
            "Missing shared workspace allowlist marker: " + marker,
        )

    context_compiler = text("backend/chat_context_compiler.py")
    for marker in (
        "Workspace content sha256:",
        "DEMAND_DRIVEN_PRIMARY_CURRENT",
        "----- BEGIN SELECTED WORKSPACE CONTEXT -----",
        "----- END SELECTED WORKSPACE CONTEXT -----",
        "LASER_IDENTITY",
        "----- USER -----",
    ):
        require(
            marker in context_compiler,
            "Missing demand-driven @current context marker: " + marker,
        )

    for marker in (
        "def parse_safe_tool_command(",
        "def _submit_tool(",
        "def _tool_finished(",
        "SAFE_TOOL_RUNNER_PATH",
        "tool_contract.validate_request(",
        "tool_contract.validate_response(",
    ):
        require(marker in main_py, "Missing Safe Tools backend marker: " + marker)

    for marker in (
        "def parse_write_command(",
        "def _submit_write(",
        "def _write_finished(",
        "WRITE_RUNNER_PATH",
        "write_contract.validate_request(",
        "write_contract.validate_response(",
    ):
        require(
            marker in main_py,
            "Missing Limited Write backend marker: " + marker,
        )

    for marker in (
        "def parse_autonomy_command(",
        "def _submit_autonomy(",
        "def _autonomy_finished(",
        "def _resume_autonomy_verify(",
        "def _autonomy_verify_finished(",
        "AUTONOMY_CONTROLLER_PATH",
        "autonomy_contract.validate_grant(",
        "autonomy_contract.validate_result(",
    ):
        require(
            marker in main_py,
            "Missing Autonomy backend marker: " + marker,
        )

    for marker in (
        "control_contract.parse_control_command(value)",
        "def _submit_control(",
        "def _stop_active(",
        "def stopActive(",
        "def _control_apply_finished(",
        "QTimer.singleShot(3000",
        "stop_signal.connect(bridge.stopActive)",
    ):
        require(
            marker in main_py,
            "Missing Control Plane backend marker: " + marker,
        )

    visible_repair_main = text("qml/Main.qml")
    visible_repair_workspace = text(
        "qml/components/WorkspaceSurface.qml"
    )
    visible_repair_settings = text(
        "qml/components/SettingsSurface.qml"
    )
    visible_repair_appearance = text(
        "qml/components/SettingsAppearanceModule.qml"
    )

    assert 'objectName: "chatSurface"' in visible_repair_main
    assert (
        "// A1.2.1.1: ordinary chatSurface owns composer geometry."
        in visible_repair_main
    )
    assert "workspace.closeSettings()" in visible_repair_main
    assert (
        'objectName: "settingsTabCloseButton"'
        in visible_repair_workspace
    )
    assert 'sequence: "Esc"' not in visible_repair_workspace
    assert "Keys.onPressed: function(event)" in visible_repair_settings
    assert "Qt.Key_Escape" in visible_repair_settings
    assert (
        "signal accentColorRequested(color value)"
        in visible_repair_workspace
    )
    assert (
        "signal accentColorChangedByUser(color value)"
        in visible_repair_settings
    )
    assert "TapHandler {" in visible_repair_appearance
    print("A1_2_VISIBLE_UX_REPAIR_CONTRACT=PASS")

    a1_2_main = text("qml/Main.qml")
    a1_2_workspace = text(
        "qml/components/WorkspaceSurface.qml"
    )
    a1_2_utility = text(
        "qml/components/UtilitySurface.qml"
    )
    a1_2_live_aid = text(
        "qml/components/ChatLiveAidWork.qml"
    )
    a1_2_settings = text(
        "qml/components/SettingsSurface.qml"
    )
    a1_2_composer = text(
        "qml/components/ContextComposer.qml"
    )

    for marker in (
        'id: centerColumn',
        'function utilityUrl(',
        'id: utilitySurface',
        'ChatLiveAidWork {',
        'id: chatLiveAidWork',
        'objectName: "chatSurface"',
        'id: chatChrome',
    ):
        require(
            marker in a1_2_main,
            "A1.2 Main structural marker missing: " + marker,
        )

    require(
        'GgFrame {\n                id: chatSurface'
        not in a1_2_main,
        "Chat structural owner regressed to GgFrame.",
    )

    require(
        "id: liveAidColumn" not in a1_2_workspace,
        "Fixed Workspace Live Aid column remains.",
    )

    for marker in (
        "function requestPostDraftAutomaticRepair()",
        "function requestLiveAidPreflight()",
        "function requestLiveAidRepair()",
        "function requestApplyRepair()",
        "root.liveAidBackend.applyRepair(",
    ):
        require(
            marker in a1_2_workspace,
            "Workspace Live Aid state machine marker missing: "
            + marker,
        )

    for marker in (
        'objectName: "workspacePostDraftAutoRepairButton"',
        'objectName: "workspacePreflightButton"',
        'objectName: "workspaceRepairButton"',
        'objectName: "workspaceApplyRepairButton"',
    ):
        require(
            marker in a1_2_live_aid,
            "Contextual Chat Live Aid control missing: " + marker,
        )
        require(
            marker not in a1_2_workspace,
            "Live Aid control still rendered inside Workspace: "
            + marker,
        )

    require(
        'objectName: "utilitySurface"' in a1_2_utility,
        "Independent UtilitySurface identity missing.",
    )
    require(
        a1_2_utility.count("Button {")
        == a1_2_utility.count("GgButton {"),
        "UtilitySurface gained fake controls.",
    )
    require(
        'objectName: "utilityTransport"' in a1_2_utility,
        "UtilitySurface transport missing.",
    )
    require(
        'objectName: "utilitySpectrum"' in a1_2_utility
        and "spectrumBars: 120" in a1_2_utility
        and "peakHoldTicks" in a1_2_utility
        and "function ledColor(" in a1_2_utility,
        "UtilitySurface spectrum missing.",
    )
    a1_2_frame = text("qml/components/GgFrame.qml")
    require(
        "antialiasing: true" in a1_2_frame,
        "GgFrame corners are still aliased.",
    )
    require(
        "property int padding: 8" in a1_2_frame
        and "property bool compact: false" in a1_2_frame
        and "verticalAlignment: Text.AlignVCenter" in a1_2_frame,
        "GgFrame chrome still clips legend text.",
    )
    require(
        'leftLegend: "MEDIA"' not in text("qml/components/MediaSurface.qml"),
        "MediaSurface still double-frames the workspace MEDIA box.",
    )
    require(
        "bottomRightLegend: \"drag band" not in a1_2_utility
        and "MEDIA / UTILITIES" in a1_2_utility,
        "UtilitySurface still spends height on hanging GgFrame legends.",
    )
    require(
        'objectName: "utilityTimeline"' in a1_2_utility
        and "function seekAt(" in a1_2_utility
        and "playing ? 1" not in a1_2_utility,
        "UtilitySurface timeline missing or still fills gold on live streams.",
    )
    ws_qml = text("qml/components/WorkspaceSurface.qml")
    require(
        "Loader {" in ws_qml
        and "active: !root.settingsOpen && root.hostKind === \"CRYPTO\"" in ws_qml
        and "active: !root.settingsOpen && root.hostKind === \"MARKETPLACE\"" in ws_qml
        and "active: !root.settingsOpen && root.hostKind === \"TMOG\"" in ws_qml
        and "active: !root.settingsOpen && root.hostKind === \"OSINT\"" in ws_qml
        and "keepResearch" in ws_qml
        and 'visible: !root.settingsOpen && root.hostKind === "RESEARCH"' in ws_qml
        and "active: !root.settingsOpen && root.hostKind === \"DRAW\"" in ws_qml
        and "active: !root.settingsOpen && root.hostKind === \"NODES\"" in ws_qml
        and "id: gameEnginePane" in ws_qml
        and "keepGameEngine" in ws_qml
        and "paneLive: gameEnginePane.visible" in ws_qml
        and "active: !root.settingsOpen && root.hostKind === \"GAME_ENGINE\"" not in ws_qml,
        "Unused workspace function panes are still kept alive.",
    )
    require(
        'leftLegend: "CODE · "' not in ws_qml
        and "tabStripLeft" in ws_qml
        and "frameKindLabel" in ws_qml,
        "Workspace CODE tabs still collide with hanging CODE · title.",
    )
    require(
        "WEEK undefined" not in text("qml/components/TelemetryRail.qml")
        and "weekly_percent === undefined" in text("qml/components/TelemetryRail.qml"),
        "Wallet week label can still print undefined%.",
    )
    require(
        "visible: root.seekable" in a1_2_utility,
        "Empty utility timeline still draws a hairline when nothing is seekable.",
    )
    require(
        'objectName: "utilityEq"' in a1_2_utility,
        "UtilitySurface equalizer missing.",
    )
    require(
        "function setEqFromY(" in a1_2_utility,
        "EQ bands are not adjustable.",
    )
    require(
        "function cycleEq(" in a1_2_utility,
        "EQ preset cycle missing.",
    )
    require(
        "workspaceMediaHole" not in a1_2_utility,
        "Media display hole leaked into the utility strip.",
    )
    a1_2_media = text("qml/components/MediaSurface.qml")
    require(
        'objectName: "workspaceMediaHole"' in a1_2_media,
        "Workspace media display hole missing.",
    )
    require(
        'objectName: "workspaceMediaStage"' in a1_2_media,
        "Workspace media stage missing.",
    )
    require(
        "import QtMultimedia" in a1_2_media
        and 'objectName: "workspaceMediaVideo"' in a1_2_media
        and 'objectName: "workspaceMediaFrame"' in a1_2_media
        and "search homebrew or local ROM" in a1_2_media,
        "Workspace media screen/search missing.",
    )
    require(
        "QtMultimedia" not in a1_2_utility,
        "Video output leaked into the utility strip.",
    )
    for marker in ("MUSIC", "RADIO", "TV", "GAME", "FETCH"):
        require(
            marker in a1_2_utility,
            "UtilitySurface mode missing: " + marker,
        )

    require(
        "readonly property int alphaBottomStripMargin: 8"
        in a1_2_main,
        "Shared bottom-strip margin contract missing.",
    )
    utility_loader_start = a1_2_main.index("id: utilitySurface")
    utility_loader_end = a1_2_main.index(
        "\n                }\n            }\n\n            TelemetryRail {",
        utility_loader_start,
    )
    utility_loader = a1_2_main[
        utility_loader_start:utility_loader_end
    ]
    require(
        "id: composer" in a1_2_main
        and a1_2_main[
            a1_2_main.index("id: composer")
            : a1_2_main.index("id: composer") + 420
        ].count("anchors.bottomMargin: 0")
        == 1,
        "INPUT top is not bound to the same bottom origin as UTILITIES.",
    )
    require(
        "anchors.bottom: parent.bottom" in utility_loader
        and utility_loader.count("anchors.bottomMargin: 0") == 1,
        "UtilitySurface is not kant-i-kant with the CHAT frame bottom.",
    )
    require(
        "height: utilitySurface.implicitHeight" in a1_2_main,
        "UtilitySurface does not use its independent implicit height.",
    )
    require(
        "utilitySurface.setSource(root.utilityUrl())" in a1_2_main,
        "RELOAD does not recreate UtilitySurface.",
    )
    require(
        "?r=" in a1_2_main and "shellNonce" in a1_2_main,
        "RELOAD QML cache-bust nonce missing.",
    )
    require(
        "property int surfaceHeight: 112" in a1_2_utility,
        "UtilitySurface default height is not the shared bottom-strip height.",
    )
    require(
        "implicitHeight: root.engineTarget === \"GROK_TUI\""
        in text("qml/components/ContextComposer.qml"),
        "Chat composer default height is not kant-i-kant with UtilitySurface.",
    )
    require(
        "workspace." not in a1_2_utility,
        "Independent UtilitySurface gained Workspace state coupling.",
    )

    for marker in (
        "SettingsAppearanceModule {",
        "SettingsLayoutModule {",
        "SettingsChatModule {",
        "SettingsWorkspaceModule {",
        "SettingsActivityModule {",
        "SettingsDeveloperModule {",
        "SettingsExtensionsModule {",
    ):
        require(
            marker in a1_2_settings,
            "Settings modular shell marker missing: " + marker,
        )

    for marker in (
        "var wasBusy = root.busy",
        "root.engineTarget === \"GROK_WORKER\"",
        "root.engineTarget === \"GROK_TUI\"",
        'input.text = ""',
    ):
        require(
            marker in a1_2_composer,
            "D76 composer retention marker missing: " + marker,
        )

    a1_3_main_py = text("main.py")
    a1_3_chat_runner = text(
        "backend/local_ai_chat_runner.py"
    )
    for marker in (
        "parse_natural_safe_tool_command(",
        "if action_proposal is None:",
        '"status": "NOT_APPLICABLE"',
        '"ordinary_chat_blocked": False',
        "if action_proposal is not None:",
        'if contract.get("execution_authority") == "NONE":',
        "Cognitive uncertainty stop · reason=",
        "orchestrator_mandate_evaluation_adapter."
        "evaluate_not_required(",
        "_natural_intent_route(",
        '"request_id": "chat-" + uuid.uuid4().hex',
    ):
        require(
            marker in a1_3_main_py,
            "A1.3A ordinary-chat marker missing: "
            + marker,
        )
    for marker in (
        "LaserFocus source-bound route unavailable · ",
        "LaserFocus source-bound · intent=",
        "Read-only cognitive ingress · decision=",
    ):
        require(
            marker not in a1_3_main_py,
            "A1.3A routine system card remains: "
            + marker,
        )
    require(
        "char{1,1024}" in a1_3_chat_runner,
        "A1.3A chat grammar bound missing.",
    )
    require(
        "Svara naturligt, hjälpsamt och konkret på "
        "användarens meddelande. Följ användarens språk."
        in a1_3_chat_runner,
        "A1.3A natural chat prompt missing.",
    )
    require(
        "height: composer.height" not in a1_2_main,
        "UtilitySurface still tracks composer height.",
    )
    print("A1_3A_ORDINARY_CHAT_UTILITY_CONTRACT=PASS")
    print("UX_LOCAL_CHAT_CONTRACT=PASS")
    print("CHAT_SURFACE=UNIVERSAL_OPERATIONAL_STREAM")
    print("WORKSPACE_SURFACE=VISUAL_MULTI_OBJECT_SURFACE")
    print("WORKSPACE_OBJECT_NODES=VISIBLE_LIVING_BLOCKS")
    print("COMPOSER_TO_LOCAL_MODEL=CONNECTED")
    print("REAL_CURRENT_WORKSPACE_CONTEXT=CONNECTED_READ_ONLY")
    print("SAFE_TOOLS=READ_SEARCH_GIT_TEST_RUN")
    print("SAFE_TOOL_AUTHORITY=GREEN_LOCAL_TYPED_SAFE_TOOLS_V1")
    print("LIMITED_WRITE_AUTHORITY=YELLOW_LOCAL_CURRENT_EXACT_PATCH_V1")
    print("LIMITED_WRITE_STATUS=VERIFIED_LIVE")
    print("CHAT_TEXT_SELECTION=READ_ONLY_SELECTABLE_COPYABLE")
    print("CHAT_TEXT_SELECTION_STATUS=VERIFIED_LIVE")
    print("AUTONOMY_CORE=TASK_BOUND_CANDIDATE_V1")
    print("AUTONOMY_STATUS=IMPLEMENTED_PENDING_HUMAN_E2E")
    print("CONTROL_PLANE=IMPLEMENTED_PENDING_HUMAN_E2E")
    print("STOP_BEFORE_BUSY_GATE=PASS")
    print("STOP_BUTTON=PASS")
    print("HOST_WRITE_BOUNDARY=SEPARATE_EXISTING_LIMITED_WRITE")
    print("FAKE_PROGRESS=FORBIDDEN")
    print("NETWORK_AUTHORITY=NONE")
    print("GENERAL_ACTION_AUTHORITY=NONE")
    return 0




def test_autonomy_events_group_into_one_chat_work_object():
    main_qml = text("qml/Main.qml")
    chat_qml = text("qml/components/ChatNode.qml")
    main_py = text("main.py")

    require(
        "function upsertAutonomyNode(" in main_qml,
        "Autonomy grouped upsert missing.",
    )
    require(
        '"nodeKind": "AUTONOMY"' in main_qml,
        "Autonomy ChatNode creation missing.",
    )
    require(
        '"workStagesJson"' in main_qml,
        "Autonomy work-stage state missing.",
    )
    require(
        "chatModel.setProperty(" in main_qml,
        "Autonomy stage update missing.",
    )
    require(
        "property string workStagesJson" in chat_qml,
        "ChatNode attached work state missing.",
    )
    require(
        "id: attachedWorkLayer" in chat_qml,
        "AttachedWorkLayer missing.",
    )
    require(
        '"upsertAutonomyNode"' in main_py,
        "Python to QML autonomy upsert lookup missing.",
    )
    require(
        'getattr(' in main_py and 'self._root' in main_py,
        "Python to QML root bridge missing.",
    )


if __name__ == "__main__":
    test_autonomy_events_group_into_one_chat_work_object()
    raise SystemExit(main())
