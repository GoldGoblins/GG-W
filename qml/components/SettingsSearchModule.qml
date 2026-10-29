pragma ComponentBehavior: Bound


import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

Item {
    id: root

    property string searchText: ""
    signal pageRequested(string page)

    readonly property var entries: [
        { "page": "PROFILES", "title": "Profiles", "keywords": "profile theme appearance layout source buffer" },
        { "page": "SURFACES", "title": "Surfaces", "keywords": "surface module registry window panel view" },
        { "page": "EDITOR", "title": "Editor / Layout lock / Source", "keywords": "editor lock unlock move resize source code block geometry" },
        { "page": "APPEARANCE", "title": "Appearance", "keywords": "appearance color border radius accent theme" },
        { "page": "LAYOUT", "title": "Layout", "keywords": "layout chat width telemetry media utilities height desktop shell" },
        { "page": "CHAT", "title": "Chat / Engine", "keywords": "chat engine qwen grok gptui flow tui input tab" },
        { "page": "WORKSPACE", "title": "Workspace / Views", "keywords": "workspace host code terminal web site crypto marketplace tmog osint qip media draw nodes flow" },
        { "page": "ACTIVITY", "title": "Activity", "keywords": "activity status running waiting busy progress task" },
        { "page": "DEVELOPER", "title": "Developer", "keywords": "developer fixtures product source debug" },
        { "page": "EXTENSIONS", "title": "Extensions / Contributions", "keywords": "extension contribution module enable disable built in registry" }
    ]

    function filteredEntries() {
        var query = root.searchText.trim().toLowerCase()
        if (!query)
            return []
        var result = []
        for (var i = 0; i < root.entries.length; ++i) {
            var row = root.entries[i]
            var haystack = String(row.title || "") + " "
                + String(row.page || "") + " "
                + String(row.keywords || "")
            if (haystack.toLowerCase().indexOf(query) >= 0)
                result.push(row)
        }
        return result
    }

    implicitHeight: 470

    GgFrame { property string uiColorScope: "ui.widget.SettingsSearchModule.GgFrame.1";
        anchors.fill: parent
        leftLegend: "SETTINGS SEARCH"
        rightLegend: root.filteredEntries().length + " MATCHES"
        backgroundColor: RuntimeTheme.GGTheme.panel
        borderColor: RuntimeTheme.GGTheme.edge
    }

    Column {
        anchors.fill: parent
        anchors.leftMargin: 14
        anchors.rightMargin: 14
        anchors.topMargin: 22
        anchors.bottomMargin: 12
        spacing: 8

        GGText { colorKey: "ui.SettingsSearchModule.1";
            width: parent.width
            text: "Search finds a settings module or contribution by name, scope or keyword. Select a result to open the existing live controls."
            color: RuntimeTheme.GGTheme.text
            wrapMode: Text.WordWrap
            font.family: "monospace"
            font.pixelSize: 11
        }

        ListView {
            id: resultList
            width: parent.width
            height: Math.max(100, parent.height - 72)
            clip: true
            spacing: 5
            model: root.filteredEntries()
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: GgScrollBar { property string uiColorScope: "ui.widget.SettingsSearchModule.GgScrollBar.2";}

            delegate: Rectangle {
                required property var modelData
                width: resultList.width - 8
                height: 42
                color: resultHit.containsMouse ? RuntimeTheme.GGTheme.raised : RuntimeTheme.GGTheme.panel
                border.color: resultHit.containsMouse ? RuntimeTheme.GGTheme.dim : RuntimeTheme.GGTheme.line
                border.width: 1
                radius: 2

                GGText { colorKey: "ui.SettingsSearchModule.2";
                    anchors.left: parent.left
                    anchors.leftMargin: 9
                    anchors.verticalCenter: parent.verticalCenter
                    text: String(modelData.title || modelData.page || "SETTING")
                    color: RuntimeTheme.GGTheme.bright
                    font.family: "monospace"
                    font.pixelSize: 11
                    font.bold: true
                }

                GGText { colorKey: "ui.SettingsSearchModule.3";
                    anchors.right: parent.right
                    anchors.rightMargin: 10
                    anchors.verticalCenter: parent.verticalCenter
                    text: String(modelData.page || "") + "  →"
                    color: RuntimeTheme.GGTheme.accent
                    font.family: "monospace"
                    font.pixelSize: 10
                }

                MouseArea {
                    id: resultHit
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.pageRequested(String(modelData.page || ""))
                }
            }
        }

        GGText { colorKey: "ui.SettingsSearchModule.4";
            visible: root.filteredEntries().length === 0
            width: parent.width
            text: "No settings module matches the current filter."
            color: RuntimeTheme.GGTheme.accent
            font.family: "monospace"
            font.pixelSize: 11
        }
    }
}
