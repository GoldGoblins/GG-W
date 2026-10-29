pragma ComponentBehavior: Bound


import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

Item {
    id: root

    property string extensionsJson: "[]"
    signal extensionEnabledChangedByUser(string extensionId, bool enabled)
    signal resetExtensionsRequested()

    implicitHeight: 520

    function rows() {
        try {
            var value = JSON.parse(root.extensionsJson || "[]")
            return value instanceof Array ? value : []
        } catch (err) {
            return []
        }
    }

    function filteredRows() {
        var query = root.searchText.trim().toLowerCase()
        var source = root.rows()
        if (!query)
            return source
        var result = []
        for (var i = 0; i < source.length; ++i) {
            var row = source[i] || {}
            var haystack = [
                row.id,
                row.name,
                row.kind,
                row.group,
                row.description,
                row.hostKind,
                row.activation,
                (row.commands || []).join(" "),
                (row.views || []).join(" "),
                (row.settings || []).join(" ")
            ].join(" ").toLowerCase()
            if (haystack.indexOf(query) >= 0)
                result.push(row)
        }
        return result
    }

    function enabledCount() {
        var source = root.rows()
        var count = 0
        for (var i = 0; i < source.length; ++i) {
            if (source[i] && source[i].enabled)
                count += 1
        }
        return count
    }

    property string searchText: ""

    GgFrame { property string uiColorScope: "ui.widget.SettingsExtensionsModule.GgFrame.1";
        anchors.fill: parent
        leftLegend: "EXTENSIONS · CONTRIBUTIONS"
        rightLegend: root.enabledCount() + " / " + root.rows().length
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

        GGText { colorKey: "ui.SettingsExtensionsModule.1";
            width: parent.width
            text: "Built-in contributions are the VS Code-style extension seam "
                + "for the existing GG surfaces. Standard keeps every current "
                + "surface enabled. Required core rows cannot be disabled."
            color: RuntimeTheme.GGTheme.text
            wrapMode: Text.WordWrap
            font.family: "monospace"
            font.pixelSize: 11
        }

        Row {
            width: parent.width
            spacing: 8

            GgField { property string uiColorScope: "ui.widget.SettingsExtensionsModule.GgField.2";
                id: extensionSearch
                width: Math.max(160, parent.width - resetButton.implicitWidth - 8)
                placeholderText: "Filter extensions, views, commands..."
                text: root.searchText
                onTextChanged: root.searchText = text
            }

            GgButton { property string uiColorScope: "ui.control.SettingsExtensionsModule.1";
                id: resetButton
                text: "RESET STANDARD"
                onClicked: root.resetExtensionsRequested()
            }
        }

        GGText { colorKey: "ui.SettingsExtensionsModule.2";
            width: parent.width
            text: "The registry describes what is already in the app; it never "
                + "loads arbitrary code. Activation is presentation availability only."
            color: RuntimeTheme.GGTheme.dim
            wrapMode: Text.WordWrap
            font.family: "monospace"
            font.pixelSize: 10
        }

        ListView {
            id: extensionList
            width: parent.width
            height: Math.max(120, parent.height - 128)
            clip: true
            spacing: 5
            model: root.filteredRows()
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: GgScrollBar { property string uiColorScope: "ui.widget.SettingsExtensionsModule.GgScrollBar.4";}

            delegate: Rectangle {
                required property var modelData
                required property int index
                width: extensionList.width - 8
                height: 58
                color: modelData.enabled ? "#1c211f" : RuntimeTheme.GGTheme.panel
                border.width: 1
                border.color: modelData.enabled ? "#51675a" : RuntimeTheme.GGTheme.line
                radius: 2

                Column {
                    anchors.left: parent.left
                    anchors.leftMargin: 9
                    anchors.right: actionButton.left
                    anchors.rightMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 2

                    GGText { colorKey: "ui.SettingsExtensionsModule.3";
                        width: parent.width
                        text: String(modelData.name || modelData.id || "EXTENSION")
                            + "  ·  " + String(modelData.version || "")
                        color: RuntimeTheme.GGTheme.bright
                        font.family: "monospace"
                        font.pixelSize: 11
                        font.bold: true
                        elide: Text.ElideRight
                    }

                    GGText { colorKey: "ui.SettingsExtensionsModule.4";
                        width: parent.width
                        text: String(modelData.id || "")
                            + "  ·  " + String(modelData.description || "")
                        color: RuntimeTheme.GGTheme.dim
                        font.family: "monospace"
                        font.pixelSize: 9
                        elide: Text.ElideRight
                    }
                }

                GgButton { property string uiColorScope: "ui.control.SettingsExtensionsModule.2";
                    id: actionButton
                    anchors.right: parent.right
                    anchors.rightMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    width: 92
                    height: 25
                    text: modelData.required
                        ? "REQUIRED"
                        : (modelData.enabled ? "DISABLE" : "ENABLE")
                    enabled: !modelData.required
                    checkable: !modelData.required
                    checked: Boolean(modelData.enabled)
                    onClicked: root.extensionEnabledChangedByUser(
                        String(modelData.id || ""),
                        !Boolean(modelData.enabled)
                    )
                }
            }
        }

        GGText { colorKey: "ui.SettingsExtensionsModule.5";
            visible: root.filteredRows().length === 0
            width: parent.width
            text: "No contribution matches the current filter."
            color: RuntimeTheme.GGTheme.accent
            font.family: "monospace"
            font.pixelSize: 11
        }
    }
}
