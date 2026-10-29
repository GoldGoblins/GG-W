pragma ComponentBehavior: Bound


import "." as RuntimeTheme
import QtQuick

Item {
    id: root

    objectName: "settingsPopup"
    width: root.visualWidth > 0 ? root.visualWidth : 760
    height: root.visualHeight > 0
        ? root.visualHeight
        : (root.parent
            ? Math.min(root.maxHeight, Math.max(360, root.parent.height - 56))
            : root.maxHeight)
    property color color: RuntimeTheme.GGTheme.panel
    focus: visible

    property color frameBorder: RuntimeTheme.GGTheme.edge
    property int frameRadius: 4
    property int maxHeight: 760
    property real visualWidth: -1
    property real visualHeight: -1
    property string page: "APPEARANCE"
    property bool sidebarCollapsed: false
    readonly property var nav: [
        "PROFILES",
        "SURFACES",
        "EDITOR",
        "APPEARANCE",
        "LAYOUT",
        "CHAT",
        "WORKSPACE",
        "ACTIVITY",
        "DEVELOPER",
        "EXTENSIONS"
    ]
    property real chatWidthRatio: 0.31
    property int telemetryWidth: 168
    property color accentColor: RuntimeTheme.GGTheme.accent
    property var paletteRoles: ({})
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
    property bool layoutLocked: true
    property string visualThemeId: "obsidian-ledger"
    property string visualProfileId: "standard"
    property string visualThemesJson: "[]"
    property string visualProfilesJson: "[]"
    property string visualSurfaceRegistryJson: "[]"
    property string visualSelectedSurface: ""
    property string visualEditorMode: "NORMAL"
    property string visualSourceText: ""
    property string visualSourcePath: ""
    property string visualSourceStatus: ""
    property string searchText: ""
    property bool _panelsCreated: false
    property bool _resetStandardPending: false
    onVisibleChanged: if (visible) root._panelsCreated = true
    Component.onCompleted: if (visible) root._panelsCreated = true

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
    signal visualThemeRequested(string themeId)
    signal visualSaveThemeRequested(string themeId)
    signal visualProfileRequested(string profileId)
    signal visualSaveProfileRequested(string profileId)
    signal visualResetProfileRequested()
    signal visualSurfaceRequested(string surfaceId)
    signal visualSourceRequested(string surfaceId)
    signal visualLockRequested(bool locked)
    signal visualModeRequested(string mode)
    signal visualSourceSaveRequested(string source)
    signal visualSourceCloseRequested()
    signal resetVisualRequested()
    signal closeRequested()

    readonly property bool searchActive: root.searchText.trim().length > 0

    function filteredNav() {
        var query = root.searchText.trim().toLowerCase()
        if (!query)
            return root.nav
        var rows = []
        for (var i = 0; i < root.nav.length; ++i) {
            var pageName = String(root.nav[i])
            var haystack = pageName + " " + root.navLabel(pageName)
            if (haystack.toLowerCase().indexOf(query) >= 0)
                rows.push(pageName)
        }
        return rows
    }

    readonly property bool visualPage: root.page === "PROFILES"
        || root.page === "SURFACES"
        || root.page === "EDITOR"

    function navLabel(value) {
        if (value === "PROFILES")
            return "Profiles"
        if (value === "SURFACES")
            return "Surfaces"
        if (value === "EDITOR")
            return "Editor"
        if (value === "APPEARANCE")
            return "Appearance"
        if (value === "LAYOUT")
            return "Layout"
        if (value === "CHAT")
            return "Chat"
        if (value === "WORKSPACE")
            return "Workspace"
        if (value === "ACTIVITY")
            return "Activity"
        if (value === "DEVELOPER")
            return "Developer"
        return "Extensions"
    }

    function navIcon(value) {
        if (value === "PROFILES")
            return "◎"
        if (value === "SURFACES")
            return "▦"
        if (value === "EDITOR")
            return "✎"
        if (value === "APPEARANCE")
            return "◈"
        if (value === "LAYOUT")
            return "⌗"
        if (value === "CHAT")
            return "▤"
        if (value === "WORKSPACE")
            return "□"
        if (value === "ACTIVITY")
            return "◷"
        if (value === "DEVELOPER")
            return "</>"
        return "+"
    }

    Keys.onPressed: function(event) {
        if (event.key !== Qt.Key_Escape)
            return
        root.closeRequested()
        event.accepted = true
    }

    function resetStandard() {
        if (settingsContent.item)
            settingsContent.item.resetStandard()
        else {
            root._resetStandardPending = true
            root._panelsCreated = true
        }
        root.resetVisualRequested()
    }

    Rectangle {
        anchors.fill: parent
        anchors.margins: 1
        color: root.color
        radius: Math.max(0, root.frameRadius - 1)
    }

    LedgerBorder { property string uiColorScope: "ui.widget.SettingsPopup.LedgerBorder.1";
        anchors.fill: parent
        color: root.frameBorder
        radius: root.frameRadius
        topGaps: [
            {start: settingsTitle.x, end: settingsTitle.x + settingsTitle.width},
            {start: settingsControls.x, end: settingsControls.x + settingsControls.width}
        ]
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        onClicked: {}
    }

    Rectangle {
        id: sidebar
        z: 1
        anchors.left: parent.left
        anchors.leftMargin: 12
        anchors.top: parent.top
        anchors.topMargin: 16
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 12
        width: root.sidebarCollapsed ? 48 : 174
        color: RuntimeTheme.GGTheme.panel
        border.color: RuntimeTheme.GGTheme.edge
        border.width: 1
        radius: 4

        Behavior on width {
            NumberAnimation {
                duration: 140
                easing.type: Easing.OutCubic
            }
        }

        Flickable {
            id: navFlick
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: sidebarFooter.top
            anchors.margins: 8
            anchors.bottomMargin: 6
            clip: true
            contentWidth: width
            contentHeight: navColumn.implicitHeight
            flickableDirection: Flickable.VerticalFlick
            boundsBehavior: Flickable.StopAtBounds

            Column {
                id: navColumn
                width: navFlick.width
                spacing: 3

                Item {
                    width: parent.width
                    height: 30

                    GGText { colorKey: "ui.SettingsPopup.1";
                        text: "☰"
                        x: root.sidebarCollapsed
                            ? (parent.width - implicitWidth) / 2
                            : 4
                        anchors.verticalCenter: parent.verticalCenter
                        color: RuntimeTheme.GGTheme.bright
                        font.family: "monospace"
                        font.pixelSize: 15
                    }

                    GGText { colorKey: "ui.SettingsPopup.2";
                        visible: !root.sidebarCollapsed
                        text: "SETTINGS MENU"
                        x: 32
                        anchors.verticalCenter: parent.verticalCenter
                        color: RuntimeTheme.GGTheme.dim
                        font.family: "monospace"
                        font.pixelSize: 11
                        font.bold: true
                    }

                    MouseArea {
                        anchors.fill: parent
                        objectName: "settingsSidebarToggle"
                        cursorShape: Qt.PointingHandCursor
                        onClicked:
                            root.sidebarCollapsed = !root.sidebarCollapsed
                    }
                }

                Rectangle {
                    width: parent.width
                    height: 1
                    color: RuntimeTheme.GGTheme.line
                }

                Item {
                    width: parent.width
                    height: root.sidebarCollapsed ? 0 : 34
                    visible: !root.sidebarCollapsed

                    GgField { property string uiColorScope: "ui.widget.SettingsPopup.GgField.2";
                        id: settingsSearchField
                        objectName: "settingsSearchField"
                        anchors.fill: parent
                        placeholderText: "Filter settings..."
                        text: root.searchText
                        onTextChanged: root.searchText = text
                    }
                }

                Repeater {
                    model: root.filteredNav()

                    delegate: Item {
                        required property string modelData
                        objectName: "settingsNav" + modelData
                        width: navColumn.width
                        height: 30

                        Rectangle {
                            anchors.fill: parent
                            radius: 3
                            color: root.page === modelData
                                ? RuntimeTheme.GGTheme.line
                                : navHit.containsMouse
                                    ? RuntimeTheme.GGTheme.raised
                                    : "transparent"
                        }

                        GGText { colorKey: "ui.SettingsPopup.3";
                            id: navIconText
                            text: root.navIcon(modelData)
                            x: root.sidebarCollapsed
                                ? (parent.width - implicitWidth) / 2
                                : 9
                            anchors.verticalCenter: parent.verticalCenter
                            color: root.page === modelData
                                ? RuntimeTheme.GGTheme.accent
                                : RuntimeTheme.GGTheme.dim
                            font.family: "monospace"
                            font.pixelSize: 13
                            font.bold: root.page === modelData
                        }

                        GGText { colorKey: "ui.SettingsPopup.4";
                            visible: !root.sidebarCollapsed
                            text: root.navLabel(modelData)
                            x: 34
                            anchors.verticalCenter: parent.verticalCenter
                            color: root.page === modelData
                                ? RuntimeTheme.GGTheme.bright
                                : RuntimeTheme.GGTheme.muted
                            font.family: "monospace"
                            font.pixelSize: 12
                            font.bold: root.page === modelData
                        }

                        MouseArea {
                            id: navHit
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.page = modelData
                        }
                    }
                }
            }
        }

        Rectangle {
            id: sidebarFooter
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: 8
            height: root.sidebarCollapsed ? 40 : 58
            color: RuntimeTheme.GGTheme.raised
            border.color: RuntimeTheme.GGTheme.line
            border.width: 1
            radius: 3

            GGText { colorKey: "ui.SettingsPopup.5";
                objectName: "settingsResetButton"
                text: root.sidebarCollapsed ? "↺" : "RESET STANDARD"
                x: root.sidebarCollapsed
                    ? (parent.width - implicitWidth) / 2
                    : 8
                anchors.top: parent.top
                anchors.topMargin: 7
                color: resetHit.containsMouse ? RuntimeTheme.GGTheme.bright : RuntimeTheme.GGTheme.accent
                font.family: "monospace"
                font.pixelSize: root.sidebarCollapsed ? 16 : 11
                font.bold: true

                MouseArea {
                    id: resetHit
                    anchors.fill: parent
                    anchors.margins: -5
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.resetStandard()
                }
            }

            GGText { colorKey: "ui.SettingsPopup.6";
                visible: !root.sidebarCollapsed
                text: "LIVE · " + root.navLabel(root.page)
                x: 8
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 7
                color: "#6f7882"
                font.family: "monospace"
                font.pixelSize: 10
            }
        }
    }

    DeferredSurface { property string uiColorScope: "ui.widget.SettingsPopup.DeferredSurface.3";
        id: settingsContent
        objectName: "settingsPopupSurfaceLoader"
        z: 1
        anchors.left: sidebar.right
        anchors.leftMargin: 12
        anchors.right: parent.right
        anchors.rightMargin: 12
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.topMargin: 16
        anchors.bottomMargin: 12
        active: root._panelsCreated || root.visible
        surfaceUrl: Qt.resolvedUrl("SettingsSurface.qml")
        surfaceProperties: ({
            objectName: "settingsPopupSurface",
            embedded: true,
            section: Qt.binding(function() { return root.page }),
            chatWidthRatio: Qt.binding(function() { return root.chatWidthRatio }),
            telemetryWidth: Qt.binding(function() { return root.telemetryWidth }),
            accentColor: Qt.binding(function() { return root.accentColor }),
            paletteRoles: Qt.binding(function() { return root.paletteRoles }),
            frameBorder: Qt.binding(function() { return root.frameBorder }),
            frameRadius: Qt.binding(function() { return root.frameRadius }),
            showDemoFixtures: Qt.binding(function() { return root.showDemoFixtures }),
            showProductSourceTabs: Qt.binding(function() { return root.showProductSourceTabs }),
            showOpenTabInInput: Qt.binding(function() { return root.showOpenTabInInput }),
            showInnerEditorChrome: Qt.binding(function() { return root.showInnerEditorChrome }),
            hostKind: Qt.binding(function() { return root.hostKind }),
            engineTarget: Qt.binding(function() { return root.engineTarget }),
            utilityHeight: Qt.binding(function() { return root.utilityHeight }),
            desktopShell: Qt.binding(function() { return root.desktopShell }),
            extensionsJson: Qt.binding(function() { return root.extensionsJson }),
            workspaceFoldersJson: Qt.binding(function() { return root.workspaceFoldersJson }),
            workspaceTrusted: Qt.binding(function() { return root.workspaceTrusted })
        })
        onLoaded: {
            if (root._resetStandardPending) {
                root._resetStandardPending = false
                item.resetStandard()
            }
        }
        Connections {
            target: settingsContent.item
            function onChatWidthRatioChangedByUser(value) {
                root.chatWidthRatioChangedByUser(value)
            }

            function onTelemetryWidthChangedByUser(value) {
                root.telemetryWidthChangedByUser(value)
            }

            function onAccentColorChangedByUser(value) {
                root.accentColorChangedByUser(value)
            }
            function onPaletteRolesChangedByUser(value) {
                root.paletteRolesChangedByUser(value)
            }

            function onFrameBorderChangedByUser(value) {
                root.frameBorderChangedByUser(value)
            }

            function onFrameRadiusChangedByUser(value) {
                root.frameRadiusChangedByUser(value)
            }

            function onDemoVisibilityChangedByUser(value) {
                root.demoVisibilityChangedByUser(value)
            }

            function onProductSourceTabsChangedByUser(value) {
                root.productSourceTabsChangedByUser(value)
            }

            function onShowOpenTabInInputChangedByUser(value) {
                root.showOpenTabInInputChangedByUser(value)
            }

            function onShowInnerEditorChromeChangedByUser(value) {
                root.showInnerEditorChromeChangedByUser(value)
            }

            function onHostKindChangedByUser(value) {
                root.hostKindChangedByUser(value)
            }

            function onSpawnInstanceRequested() { root.spawnInstanceRequested() }

            function onEngineTargetChangedByUser(value) {
                root.engineTargetChangedByUser(value)
            }

            function onUtilityHeightChangedByUser(value) {
                root.utilityHeightChangedByUser(value)
            }

            function onDesktopShellChangedByUser(value) {
                root.desktopShellChangedByUser(value)
            }

            function onExtensionEnabledChangedByUser(extensionId, enabled) {
                root.extensionEnabledChangedByUser(extensionId, enabled)
            }

            function onResetExtensionsRequested() { root.resetExtensionsRequested() }

            function onWorkspaceFoldersChangedByUser(foldersJson) {
                root.workspaceFoldersChangedByUser(foldersJson)
            }

            function onWorkspaceTrustedChangedByUser(value) {
                root.workspaceTrustedChangedByUser(value)
            }

            function onCloseRequested() { root.closeRequested() }
        }
    }

    DeferredSurface { property string uiColorScope: "ui.widget.SettingsPopup.DeferredSurface.4";
        id: profilesContent
        objectName: "settingsProfilesLoader"
        z: 2
        visible: root.page === "PROFILES" && !root.searchActive
        anchors.left: sidebar.right
        anchors.leftMargin: 12
        anchors.right: parent.right
        anchors.rightMargin: 12
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.topMargin: 22
        anchors.bottomMargin: 18
        active: root._panelsCreated || root.visible
        surfaceUrl: Qt.resolvedUrl("VisualProfilesModule.qml")
        surfaceProperties: ({
            objectName: "settingsProfilesModule",
            themeId: Qt.binding(function() { return root.visualThemeId }),
            profileId: Qt.binding(function() { return root.visualProfileId }),
            themesJson: Qt.binding(function() { return root.visualThemesJson }),
            profilesJson: Qt.binding(function() { return root.visualProfilesJson })
        })
        Connections {
            target: profilesContent.item
            function onThemeRequested(value) {
                root.visualThemeRequested(value)
            }
            function onSaveThemeRequested(value) {
                root.visualSaveThemeRequested(value)
            }
            function onProfileRequested(value) {
                root.visualProfileRequested(value)
            }
            function onSaveProfileRequested(value) {
                root.visualSaveProfileRequested(value)
            }
            function onResetProfileRequested() { root.visualResetProfileRequested() }
        }
    }

    DeferredSurface { property string uiColorScope: "ui.widget.SettingsPopup.DeferredSurface.5";
        id: surfacesContent
        objectName: "settingsSurfacesLoader"
        z: 2
        visible: root.page === "SURFACES" && !root.searchActive
        anchors.left: sidebar.right
        anchors.leftMargin: 12
        anchors.right: parent.right
        anchors.rightMargin: 12
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.topMargin: 22
        anchors.bottomMargin: 18
        active: root._panelsCreated || root.visible
        surfaceUrl: Qt.resolvedUrl("VisualSurfacesModule.qml")
        surfaceProperties: ({
            objectName: "settingsSurfacesModule",
            surfaceRegistryJson: Qt.binding(function() { return root.visualSurfaceRegistryJson }),
            selectedSurface: Qt.binding(function() { return root.visualSelectedSurface }),
            layoutLocked: Qt.binding(function() { return root.layoutLocked })
        })
        Connections {
            target: surfacesContent.item
            function onSurfaceSelected(value) {
                root.visualSurfaceRequested(value)
            }
            function onSourceRequested(value) {
                root.visualSourceRequested(value)
            }
        }
    }

    DeferredSurface { property string uiColorScope: "ui.widget.SettingsPopup.DeferredSurface.6";
        id: editorContent
        objectName: "settingsVisualEditorLoader"
        z: 2
        visible: root.page === "EDITOR" && !root.searchActive
        anchors.left: sidebar.right
        anchors.leftMargin: 12
        anchors.right: parent.right
        anchors.rightMargin: 12
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.topMargin: 22
        anchors.bottomMargin: 18
        active: root._panelsCreated || root.visible
        surfaceUrl: Qt.resolvedUrl("VisualEditorModule.qml")
        surfaceProperties: ({
            objectName: "settingsVisualEditorModule",
            layoutLocked: Qt.binding(function() { return root.layoutLocked }),
            editorMode: Qt.binding(function() { return root.visualEditorMode }),
            selectedSurface: Qt.binding(function() { return root.visualSelectedSurface }),
            surfaceRegistryJson: Qt.binding(function() { return root.visualSurfaceRegistryJson }),
            sourceText: Qt.binding(function() { return root.visualSourceText }),
            sourcePath: Qt.binding(function() { return root.visualSourcePath }),
            sourceStatus: Qt.binding(function() { return root.visualSourceStatus })
        })
        Connections {
            target: editorContent.item
            function onLockRequested(value) {
                root.visualLockRequested(value)
            }
            function onModeRequested(value) {
                root.visualModeRequested(value)
            }
            function onSurfaceRequested(value) {
                root.visualSurfaceRequested(value)
            }
            function onSourceSaveRequested(value) {
                root.visualSourceSaveRequested(value)
            }
            function onSourceCloseRequested() { root.visualSourceCloseRequested() }
        }
    }

    DeferredSurface { property string uiColorScope: "ui.widget.SettingsPopup.DeferredSurface.7";
        id: searchContent
        objectName: "settingsSearchLoader"
        z: 3
        visible: root.searchActive
        anchors.left: sidebar.right
        anchors.leftMargin: 12
        anchors.right: parent.right
        anchors.rightMargin: 12
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.topMargin: 22
        anchors.bottomMargin: 18
        active: root._panelsCreated || root.visible
        surfaceUrl: Qt.resolvedUrl("SettingsSearchModule.qml")
        surfaceProperties: ({
            objectName: "settingsSearchModule",
            searchText: Qt.binding(function() { return root.searchText })
        })
        Connections {
            target: searchContent.item
            function onPageRequested(value) {
                root.page = value
                root.searchText = ""
            }
        }
    }

    Item {
        id: settingsTitle
        z: 3
        visible: true
        anchors.left: parent.left
        anchors.leftMargin: 12
        anchors.top: parent.top
        anchors.topMargin: -8
        height: 18
        width: settingsLegendText.implicitWidth + 12

        GGText { colorKey: "ui.SettingsPopup.7";
            id: settingsLegendText
            anchors.centerIn: parent
            text: "SETTINGS"
            color: RuntimeTheme.GGTheme.bright
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: true
        }
    }

    Item {
        id: settingsControls
        z: 3
        anchors.right: parent.right
        anchors.rightMargin: 12
        anchors.top: parent.top
        anchors.topMargin: -8
        height: 18
        width: settingsLegendRow.implicitWidth + 12

        Row {
            id: settingsLegendRow
            anchors.centerIn: parent
            spacing: 8

            GGText { colorKey: "ui.SettingsPopup.8";
                id: gripDots
                objectName: "settingsDragBar"
                text: "⋮⋮"
                color: RuntimeTheme.GGTheme.dim
                font.family: "monospace"
                font.pixelSize: 11
                anchors.verticalCenter: parent.verticalCenter

                MouseArea {
                    anchors.fill: parent
                    anchors.margins: -4
                    drag.target: root
                    drag.smoothed: false
                    drag.minimumX: 0
                    drag.minimumY: 0
                    drag.maximumX: root.parent
                        ? Math.max(0, root.parent.width - root.width - 12)
                        : 4096
                    drag.maximumY: root.parent
                        ? Math.max(0, root.parent.height - root.height - 12)
                        : 4096
                    cursorShape: pressed
                        ? Qt.ClosedHandCursor
                        : Qt.OpenHandCursor
                }
            }

            Rectangle {
                width: 1
                height: 12
                color: root.frameBorder
                anchors.verticalCenter: parent.verticalCenter
            }

            GGText { colorKey: "ui.SettingsPopup.9";
                objectName: "settingsPopupCloseButton"
                text: "✕"
                color: RuntimeTheme.GGTheme.dim
                font.family: "monospace"
                font.pixelSize: 12
                anchors.verticalCenter: parent.verticalCenter

                MouseArea {
                    anchors.fill: parent
                    anchors.margins: -4
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.closeRequested()
                }
            }
        }
    }
}
