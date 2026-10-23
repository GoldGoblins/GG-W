pragma ComponentBehavior: Bound

import QtQuick

Rectangle {
    id: root

    objectName: "settingsPopup"
    width: root.visualWidth > 0 ? root.visualWidth : 760
    height: root.visualHeight > 0
        ? root.visualHeight
        : (root.parent
            ? Math.min(root.maxHeight, Math.max(360, root.parent.height - 56))
            : root.maxHeight)
    color: "#161616"
    border.color: root.frameBorder
    border.width: 1
    radius: root.frameRadius
    focus: visible

    property color frameBorder: "#4a4a4a"
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
    property color accentColor: "#8a8a8a"
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

    signal chatWidthRatioChangedByUser(real value)
    signal telemetryWidthChangedByUser(int value)
    signal accentColorChangedByUser(color value)
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
        settingsContent.resetStandard()
        root.resetVisualRequested()
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
        color: "#181818"
        border.color: "#4a4a4a"
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

                    Text {
                        text: "☰"
                        x: root.sidebarCollapsed
                            ? (parent.width - implicitWidth) / 2
                            : 4
                        anchors.verticalCenter: parent.verticalCenter
                        color: "#e6edf3"
                        font.family: "monospace"
                        font.pixelSize: 15
                    }

                    Text {
                        visible: !root.sidebarCollapsed
                        text: "SETTINGS MENU"
                        x: 32
                        anchors.verticalCenter: parent.verticalCenter
                        color: "#8b949e"
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
                    color: "#343a40"
                }

                Item {
                    width: parent.width
                    height: root.sidebarCollapsed ? 0 : 34
                    visible: !root.sidebarCollapsed

                    GgField {
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
                                ? "#34383d"
                                : navHit.containsMouse
                                    ? "#24292e"
                                    : "transparent"
                        }

                        Text {
                            id: navIconText
                            text: root.navIcon(modelData)
                            x: root.sidebarCollapsed
                                ? (parent.width - implicitWidth) / 2
                                : 9
                            anchors.verticalCenter: parent.verticalCenter
                            color: root.page === modelData
                                ? "#c7a873"
                                : "#8b949e"
                            font.family: "monospace"
                            font.pixelSize: 13
                            font.bold: root.page === modelData
                        }

                        Text {
                            visible: !root.sidebarCollapsed
                            text: root.navLabel(modelData)
                            x: 34
                            anchors.verticalCenter: parent.verticalCenter
                            color: root.page === modelData
                                ? "#e6edf3"
                                : "#a8b0b8"
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
            color: "#1c1c1c"
            border.color: "#343a40"
            border.width: 1
            radius: 3

            Text {
                objectName: "settingsResetButton"
                text: root.sidebarCollapsed ? "↺" : "RESET STANDARD"
                x: root.sidebarCollapsed
                    ? (parent.width - implicitWidth) / 2
                    : 8
                anchors.top: parent.top
                anchors.topMargin: 7
                color: resetHit.containsMouse ? "#e6edf3" : "#c7a873"
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

            Text {
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

    SettingsSurface {
        id: settingsContent
        objectName: "settingsPopupSurface"
        z: 1
        anchors.left: sidebar.right
        anchors.leftMargin: 12
        anchors.right: parent.right
        anchors.rightMargin: 12
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.topMargin: 16
        anchors.bottomMargin: 12
        embedded: true
        section: root.page
        visible: !root.visualPage
            && !root.searchActive
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
        extensionsJson: root.extensionsJson
        workspaceFoldersJson: root.workspaceFoldersJson
        workspaceTrusted: root.workspaceTrusted

        onChatWidthRatioChangedByUser: function(value) {
            root.chatWidthRatioChangedByUser(value)
        }

        onTelemetryWidthChangedByUser: function(value) {
            root.telemetryWidthChangedByUser(value)
        }

        onAccentColorChangedByUser: function(value) {
            root.accentColorChangedByUser(value)
        }

        onFrameBorderChangedByUser: function(value) {
            root.frameBorderChangedByUser(value)
        }

        onFrameRadiusChangedByUser: function(value) {
            root.frameRadiusChangedByUser(value)
        }

        onDemoVisibilityChangedByUser: function(value) {
            root.demoVisibilityChangedByUser(value)
        }

        onProductSourceTabsChangedByUser: function(value) {
            root.productSourceTabsChangedByUser(value)
        }

        onShowOpenTabInInputChangedByUser: function(value) {
            root.showOpenTabInInputChangedByUser(value)
        }

        onShowInnerEditorChromeChangedByUser: function(value) {
            root.showInnerEditorChromeChangedByUser(value)
        }

        onHostKindChangedByUser: function(value) {
            root.hostKindChangedByUser(value)
        }

        onSpawnInstanceRequested: root.spawnInstanceRequested()

        onEngineTargetChangedByUser: function(value) {
            root.engineTargetChangedByUser(value)
        }

        onUtilityHeightChangedByUser: function(value) {
            root.utilityHeightChangedByUser(value)
        }

        onDesktopShellChangedByUser: function(value) {
            root.desktopShellChangedByUser(value)
        }

        onExtensionEnabledChangedByUser: function(extensionId, enabled) {
            root.extensionEnabledChangedByUser(extensionId, enabled)
        }

        onResetExtensionsRequested: root.resetExtensionsRequested()

        onWorkspaceFoldersChangedByUser: function(foldersJson) {
            root.workspaceFoldersChangedByUser(foldersJson)
        }

        onWorkspaceTrustedChangedByUser: function(value) {
            root.workspaceTrustedChangedByUser(value)
        }

        onCloseRequested: root.closeRequested()
    }

    VisualProfilesModule {
        id: profilesContent
        objectName: "settingsProfilesModule"
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
        themeId: root.visualThemeId
        profileId: root.visualProfileId
        themesJson: root.visualThemesJson
        profilesJson: root.visualProfilesJson

        onThemeRequested: function(value) {
            root.visualThemeRequested(value)
        }
        onSaveThemeRequested: function(value) {
            root.visualSaveThemeRequested(value)
        }
        onProfileRequested: function(value) {
            root.visualProfileRequested(value)
        }
        onSaveProfileRequested: function(value) {
            root.visualSaveProfileRequested(value)
        }
        onResetProfileRequested: root.visualResetProfileRequested()
    }

    VisualSurfacesModule {
        id: surfacesContent
        objectName: "settingsSurfacesModule"
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
        surfaceRegistryJson: root.visualSurfaceRegistryJson
        selectedSurface: root.visualSelectedSurface
        layoutLocked: root.layoutLocked

        onSurfaceSelected: function(value) {
            root.visualSurfaceRequested(value)
        }
        onSourceRequested: function(value) {
            root.visualSourceRequested(value)
        }
    }

    VisualEditorModule {
        id: editorContent
        objectName: "settingsVisualEditorModule"
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
        layoutLocked: root.layoutLocked
        editorMode: root.visualEditorMode
        selectedSurface: root.visualSelectedSurface
        surfaceRegistryJson: root.visualSurfaceRegistryJson
        sourceText: root.visualSourceText
        sourcePath: root.visualSourcePath
        sourceStatus: root.visualSourceStatus

        onLockRequested: function(value) {
            root.visualLockRequested(value)
        }
        onModeRequested: function(value) {
            root.visualModeRequested(value)
        }
        onSurfaceRequested: function(value) {
            root.visualSurfaceRequested(value)
        }
        onSourceSaveRequested: function(value) {
            root.visualSourceSaveRequested(value)
        }
        onSourceCloseRequested: root.visualSourceCloseRequested()
    }

    SettingsSearchModule {
        id: searchContent
        objectName: "settingsSearchModule"
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
        searchText: root.searchText

        onPageRequested: function(value) {
            root.page = value
            root.searchText = ""
        }
    }

    Rectangle {
        z: 3
        visible: true
        anchors.left: parent.left
        anchors.leftMargin: 12
        anchors.top: parent.top
        anchors.topMargin: -8
        height: 18
        width: settingsLegendText.implicitWidth + 12
        color: root.color
        radius: 3

        Text {
            id: settingsLegendText
            anchors.centerIn: parent
            text: "SETTINGS"
            color: "#e6edf3"
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: true
        }
    }

    Rectangle {
        z: 3
        anchors.right: parent.right
        anchors.rightMargin: 12
        anchors.top: parent.top
        anchors.topMargin: -8
        height: 18
        width: settingsLegendRow.implicitWidth + 12
        color: root.color
        radius: 3

        Row {
            id: settingsLegendRow
            anchors.centerIn: parent
            spacing: 8

            Text {
                id: gripDots
                objectName: "settingsDragBar"
                text: "⋮⋮"
                color: "#8b949e"
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

            Text {
                objectName: "settingsPopupCloseButton"
                text: "✕"
                color: "#8b949e"
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
