pragma ComponentBehavior: Bound


import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

Item {
    id: root

    property var commands: []
    property string query: ""
    property string title: "COMMAND PALETTE"
    property string placeholderText: "Type a command..."
    property string footerHint: "Ctrl+Shift+P / F1"
    signal commandRequested(string commandId)
    signal dismissed()

    focus: visible
    visible: false

    function filteredCommands() {
        var queryText = root.query.trim().toLowerCase()
        var source = root.commands || []
        if (!queryText)
            return source
        var result = []
        for (var i = 0; i < source.length; ++i) {
            var row = source[i] || {}
            var haystack = [
                row.id,
                row.label,
                row.category,
                row.description,
                row.keybinding
            ].join(" ").toLowerCase()
            if (haystack.indexOf(queryText) >= 0)
                result.push(row)
        }
        return result
    }

    function executeCurrent() {
        var rows = root.filteredCommands()
        if (rows.length === 0)
            return
        var index = resultList.currentIndex
        if (index < 0 || index >= rows.length)
            index = 0
        var row = rows[index] || {}
        var commandId = String(row.id || "")
        if (!commandId.length)
            return
        root.commandRequested(commandId)
    }

    onVisibleChanged: {
        if (!visible)
            return
        root.query = ""
        resultList.currentIndex = 0
        Qt.callLater(function() {
            if (root.visible)
                commandField.forceActiveFocus()
        })
    }

    Rectangle {
        anchors.fill: parent
        color: "#000000"
        opacity: 0.32

        MouseArea {
            anchors.fill: parent
            onClicked: root.dismissed()
        }
    }

    Item {
        id: palettePanel
        z: 1
        width: Math.min(720, Math.max(340, root.width - 40))
        height: Math.min(560, Math.max(240, root.height - 40))
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: 54

        GgFrame { property string uiColorScope: "ui.widget.CommandPalette.GgFrame.1";
            anchors.fill: parent
            leftLegend: root.title
            rightLegend: "ESC"
            backgroundColor: RuntimeTheme.GGTheme.panel
            borderColor: RuntimeTheme.GGTheme.edge

            Column {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                anchors.topMargin: 22
                anchors.bottomMargin: 10
                spacing: 8

                GgField { property string uiColorScope: "ui.widget.CommandPalette.GgField.2";
                    id: commandField
                    objectName: "commandPaletteField"
                    width: parent.width
                    height: 30
                    placeholderText: root.placeholderText
                    text: root.query
                    onTextChanged: {
                        root.query = text
                        resultList.currentIndex = 0
                    }
                    onAccepted: root.executeCurrent()

                    Keys.onPressed: function(event) {
                        if (event.key === Qt.Key_Down) {
                            resultList.currentIndex = Math.min(
                                resultList.count - 1,
                                resultList.currentIndex + 1
                            )
                            event.accepted = true
                        } else if (event.key === Qt.Key_Up) {
                            resultList.currentIndex = Math.max(
                                0,
                                resultList.currentIndex - 1
                            )
                            event.accepted = true
                        } else if (event.key === Qt.Key_Escape) {
                            root.dismissed()
                            event.accepted = true
                        }
                    }
                }

                GGText { colorKey: "ui.CommandPalette.1";
                    width: parent.width
                    text: root.filteredCommands().length + " results · ↑ ↓ navigate · Enter open"
                    color: RuntimeTheme.GGTheme.dim
                    font.family: "monospace"
                    font.pixelSize: 10
                }

                ListView {
                    id: resultList
                    width: parent.width
                    height: Math.max(120, parent.height - 72)
                    clip: true
                    spacing: 3
                    currentIndex: 0
                    model: root.filteredCommands()
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: GgScrollBar { property string uiColorScope: "ui.widget.CommandPalette.GgScrollBar.3";}

                    delegate: Rectangle {
                        required property var modelData
                        required property int index
                        width: resultList.width - 8
                        height: 42
                        color: index === resultList.currentIndex
                            ? RuntimeTheme.GGTheme.line
                            : commandHit.containsMouse
                                ? RuntimeTheme.GGTheme.raised
                                : RuntimeTheme.GGTheme.panel
                        border.width: 1
                        border.color: index === resultList.currentIndex
                            ? RuntimeTheme.GGTheme.dim
                            : RuntimeTheme.GGTheme.line
                        radius: 2

                        GGText { colorKey: "ui.CommandPalette.2";
                            anchors.left: parent.left
                            anchors.leftMargin: 9
                            anchors.verticalCenter: parent.verticalCenter
                            text: String(modelData.label || modelData.id || "COMMAND")
                            color: RuntimeTheme.GGTheme.bright
                            font.family: "monospace"
                            font.pixelSize: 11
                            font.bold: index === resultList.currentIndex
                        }

                        GGText { colorKey: "ui.CommandPalette.3";
                            anchors.right: parent.right
                            anchors.rightMargin: 10
                            anchors.verticalCenter: parent.verticalCenter
                            text: String(modelData.keybinding || modelData.category || "")
                            color: RuntimeTheme.GGTheme.accent
                            font.family: "monospace"
                            font.pixelSize: 10
                        }

                        GGText { colorKey: "ui.CommandPalette.4";
                            anchors.left: parent.left
                            anchors.leftMargin: 9
                            anchors.right: parent.right
                            anchors.rightMargin: 145
                            anchors.bottom: parent.bottom
                            anchors.bottomMargin: 4
                            text: String(modelData.description || "")
                            color: RuntimeTheme.GGTheme.dim
                            font.family: "monospace"
                            font.pixelSize: 8
                            elide: Text.ElideRight
                        }

                        MouseArea {
                            id: commandHit
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onEntered: resultList.currentIndex = index
                            onClicked: root.executeCurrent()
                        }
                    }
                }

                Row {
                    width: parent.width
                    spacing: 8

                    GgButton { property string uiColorScope: "ui.control.CommandPalette.1";
                        text: "CLOSE"
                        onClicked: root.dismissed()
                    }

                    GGText { colorKey: "ui.CommandPalette.5";
                        anchors.verticalCenter: parent.verticalCenter
                        text: root.footerHint
                        color: "#6f7882"
                        font.family: "monospace"
                        font.pixelSize: 10
                    }
                }
            }
        }
    }
}
