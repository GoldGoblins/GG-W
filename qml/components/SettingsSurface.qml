pragma ComponentBehavior: Bound


import "." as RuntimeTheme
import "GGPalette.js" as BasePalette
import QtQuick
import QtQuick.Controls

Item {
    id: root

    objectName: "workspaceSettingsSurface"
    focus: visible
    Keys.priority: Keys.BeforeItem
    Keys.onPressed: function(event) {
        if (event.key !== Qt.Key_Escape)
            return
        root.closeRequested()
        event.accepted = true
    }

    property real chatWidthRatio: 0.31
    property int telemetryWidth: 168
    property color accentColor: RuntimeTheme.GGTheme.accent
    property var paletteRoles: ({})
    property color frameBorder: RuntimeTheme.GGTheme.edge
    property int frameRadius: 4
    property bool showDemoFixtures: false
    property bool showProductSourceTabs: false
    property bool showOpenTabInInput: false
    property bool showInnerEditorChrome: true
    property string hostKind: "CODE"
    property string engineTarget: "GROK_TUI"
    property int utilityHeight: 112
    property bool desktopShell: false
    property string extensionsJson: "[]"
    property string workspaceFoldersJson: "[]"
    property bool workspaceTrusted: true
    property bool embedded: false
    property string section: "ALL"
    readonly property string themeId: "obsidian-ledger-standard"

    signal chatWidthRatioChangedByUser(real value)
    signal telemetryWidthChangedByUser(int value)
    signal accentColorChangedByUser(color value)
    signal paletteRolesChangedByUser(var value)
    signal frameBorderChangedByUser(color value)
    signal frameRadiusChangedByUser(int value)
    signal demoVisibilityChangedByUser(bool value)
    signal productSourceTabsChangedByUser(bool value)
    signal showOpenTabInInputChangedByUser(bool value)
    signal showInnerEditorChromeChangedByUser(bool value)
    signal hostKindChangedByUser(string value)
    signal spawnInstanceRequested()
    signal engineTargetChangedByUser(string value)
    signal utilityHeightChangedByUser(int value)
    signal desktopShellChangedByUser(bool value)
    signal extensionEnabledChangedByUser(string extensionId, bool enabled)
    signal resetExtensionsRequested()
    signal workspaceFoldersChangedByUser(string foldersJson)
    signal workspaceTrustedChangedByUser(bool value)
    signal closeRequested()

    implicitWidth: 620
    implicitHeight: 560

    function sectionVisible(name) {
        return root.section === "ALL" || root.section === name
    }

    function resetStandard() {
        root.chatWidthRatioChangedByUser(0.31)
        root.telemetryWidthChangedByUser(168)
        root.accentColorChangedByUser(BasePalette.accent)
        root.paletteRolesChangedByUser({})
        root.frameBorderChangedByUser(RuntimeTheme.GGTheme.edge)
        root.frameRadiusChangedByUser(4)
        root.demoVisibilityChangedByUser(false)
        root.productSourceTabsChangedByUser(false)
        root.showOpenTabInInputChangedByUser(false)
        root.showInnerEditorChromeChangedByUser(true)
        root.hostKindChangedByUser("CODE")
        root.engineTargetChangedByUser("GROK_TUI")
        root.utilityHeightChangedByUser(112)
        root.desktopShellChangedByUser(false)
        root.workspaceFoldersChangedByUser("[]")
        root.workspaceTrustedChangedByUser(true)
        root.resetExtensionsRequested()
    }

    GgFrame { property string uiColorScope: "ui.widget.SettingsSurface.GgFrame.1";
        id: settingsChrome
        anchors.fill: parent
        visible: !root.embedded
        leftLegend: ""
        rightLegend: ""
        backgroundColor: RuntimeTheme.GGTheme.panel
        borderColor: root.frameBorder
        radius: root.frameRadius
    }

    Flickable {
        id: settingsFlick
        anchors.fill: parent
        anchors.leftMargin: 14
        anchors.rightMargin: 14
        anchors.topMargin: 8
        anchors.bottomMargin: 14
        clip: true
        contentWidth: width
        contentHeight: modulesColumn.y + modulesColumn.implicitHeight
        flickableDirection: Flickable.VerticalFlick
        boundsBehavior: Flickable.StopAtBounds

        ScrollBar.vertical: GgScrollBar { property string uiColorScope: "ui.widget.SettingsSurface.GgScrollBar.2";}

        Column {
            id: modulesColumn
            // Captions straddle the border by8px; retain them inside the clip.
            y: 8
            width: settingsFlick.width
            spacing: 10

            GGText { colorKey: "ui.SettingsSurface.1";
                width: parent.width
                visible: root.section === "ALL"
                text: "Settings modules are separated by concern. "
                    + "Only controls with real alpha wiring are interactive."
                color: RuntimeTheme.GGTheme.text
                wrapMode: Text.WordWrap
                font.pixelSize: 12
            }

            SettingsAppearanceModule {
                width: parent.width
                height: root.sectionVisible("APPEARANCE")
                    ? implicitHeight
                    : 0
                visible: root.sectionVisible("APPEARANCE")
                accentColor: root.accentColor
                paletteRoles: root.paletteRoles
                frameBorder: root.frameBorder
                frameRadius: root.frameRadius

                onAccentColorChangedByUser: function(value) {
                    root.accentColorChangedByUser(value)
                }
                onPaletteRolesChangedByUser: function(value) {
                    root.paletteRolesChangedByUser(value)
                }

                onFrameBorderChangedByUser: function(value) {
                    root.frameBorderChangedByUser(value)
                }

                onFrameRadiusChangedByUser: function(value) {
                    root.frameRadiusChangedByUser(value)
                }
            }

            SettingsLayoutModule { property string uiColorScope: "ui.widget.SettingsSurface.SettingsLayoutModule.3";
                width: parent.width
                height: root.sectionVisible("LAYOUT")
                    ? implicitHeight
                    : 0
                visible: root.sectionVisible("LAYOUT")
                chatWidthRatio: root.chatWidthRatio
                telemetryWidth: root.telemetryWidth
                utilityHeight: root.utilityHeight
                desktopShell: root.desktopShell

                onChatWidthRatioChangedByUser: function(value) {
                    root.chatWidthRatioChangedByUser(value)
                }

                onTelemetryWidthChangedByUser: function(value) {
                    root.telemetryWidthChangedByUser(value)
                }

                onUtilityHeightChangedByUser: function(value) {
                    root.utilityHeightChangedByUser(value)
                }

                onDesktopShellChangedByUser: function(value) {
                    root.desktopShellChangedByUser(value)
                }
            }

            SettingsChatModule { property string uiColorScope: "ui.widget.SettingsSurface.SettingsChatModule.4";
                width: parent.width
                height: root.sectionVisible("CHAT")
                    ? implicitHeight
                    : 0
                visible: root.sectionVisible("CHAT")
                showOpenTabInInput: root.showOpenTabInInput
                engineTarget: root.engineTarget

                onShowOpenTabInInputChangedByUser: function(value) {
                    root.showOpenTabInInputChangedByUser(value)
                }

                onEngineTargetChangedByUser: function(value) {
                    root.engineTargetChangedByUser(value)
                }
            }

            SettingsWorkspaceModule { property string uiColorScope: "ui.widget.SettingsSurface.SettingsWorkspaceModule.5";
                width: parent.width
                height: root.sectionVisible("WORKSPACE")
                    ? implicitHeight
                    : 0
                visible: root.sectionVisible("WORKSPACE")
                showInnerEditorChrome: root.showInnerEditorChrome
                hostKind: root.hostKind
                extensionsJson: root.extensionsJson
                workspaceFoldersJson: root.workspaceFoldersJson
                workspaceTrusted: root.workspaceTrusted

                onShowInnerEditorChromeChangedByUser: function(value) {
                    root.showInnerEditorChromeChangedByUser(value)
                }

                onHostKindChangedByUser: function(value) {
                    root.hostKindChangedByUser(value)
                }

                onSpawnInstanceRequested: root.spawnInstanceRequested()

                onWorkspaceFoldersChangedByUser: function(foldersJson) {
                    root.workspaceFoldersChangedByUser(foldersJson)
                }

                onWorkspaceTrustedChangedByUser: function(value) {
                    root.workspaceTrustedChangedByUser(value)
                }
            }

            SettingsActivityModule { property string uiColorScope: "ui.widget.SettingsSurface.SettingsActivityModule.6";
                width: parent.width
                height: root.sectionVisible("ACTIVITY")
                    ? implicitHeight
                    : 0
                visible: root.sectionVisible("ACTIVITY")
            }

            SettingsDeveloperModule { property string uiColorScope: "ui.widget.SettingsSurface.SettingsDeveloperModule.7";
                width: parent.width
                height: root.sectionVisible("DEVELOPER")
                    ? implicitHeight
                    : 0
                visible: root.sectionVisible("DEVELOPER")
                showDemoFixtures: root.showDemoFixtures
                showProductSourceTabs: root.showProductSourceTabs

                onDemoVisibilityChangedByUser: function(value) {
                    root.demoVisibilityChangedByUser(value)
                }

                onProductSourceTabsChangedByUser: function(value) {
                    root.productSourceTabsChangedByUser(value)
                }
            }

            SettingsExtensionsModule { property string uiColorScope: "ui.widget.SettingsSurface.SettingsExtensionsModule.8";
                width: parent.width
                height: root.sectionVisible("EXTENSIONS")
                    ? implicitHeight
                    : 0
                visible: root.sectionVisible("EXTENSIONS")

                extensionsJson: root.extensionsJson

                onExtensionEnabledChangedByUser: function(extensionId, enabled) {
                    root.extensionEnabledChangedByUser(extensionId, enabled)
                }

                onResetExtensionsRequested: root.resetExtensionsRequested()
            }

            Row {
                width: parent.width
                height: root.section === "ALL" ? 44 : 0
                visible: root.section === "ALL"
                spacing: 8

                GgButton { property string uiColorScope: "ui.control.SettingsSurface.1";
                    text: "Reset standard layout"
                    onClicked: root.resetStandard()
                }

                GgButton { property string uiColorScope: "ui.control.SettingsSurface.2";
                    text: "Close settings"
                    onClicked: root.closeRequested()
                }

                GGText { colorKey: "ui.SettingsSurface.2";
                    anchors.verticalCenter: parent.verticalCenter
                    text: "theme-id · " + root.themeId
                    color: RuntimeTheme.GGTheme.muted
                    font.family: "monospace"
                    font.pixelSize: 12
                }
            }

            Item {
                width: 1
                height: 6
            }
        }
    }
}
