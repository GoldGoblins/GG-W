pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs

Item {
    id: root

    property bool showInnerEditorChrome: true
    property string hostKind: "CODE"
    property string extensionsJson: "[]"
    property string workspaceFoldersJson: "[]"
    property bool workspaceTrusted: true
    signal showInnerEditorChromeChangedByUser(bool value)
    signal hostKindChangedByUser(string value)
    signal spawnInstanceRequested()
    signal workspaceFoldersChangedByUser(string foldersJson)
    signal workspaceTrustedChangedByUser(bool value)

    implicitHeight: 430

    function folderRows() {
        try {
            var value = JSON.parse(root.workspaceFoldersJson || "[]")
            return value instanceof Array ? value : []
        } catch (err) {
            return []
        }
    }

    function addFolder(rawUrl) {
        var value = String(rawUrl || "").trim()
        if (value.indexOf("file://") === 0)
            value = decodeURIComponent(value.slice(7))
        if (!value.length || value.charAt(0) !== "/")
            return
        var rows = root.folderRows()
        if (rows.indexOf(value) >= 0 || rows.length >= 8)
            return
        rows.push(value)
        root.workspaceFoldersChangedByUser(JSON.stringify(rows))
    }

    function removeFolder(index) {
        var rows = root.folderRows()
        if (index < 0 || index >= rows.length)
            return
        rows.splice(index, 1)
        root.workspaceFoldersChangedByUser(JSON.stringify(rows))
    }

    function hostEnabled(kind) {
        var wanted = String(kind || "").toUpperCase()
        if (!wanted.length)
            return true
        var rows = []
        try {
            var parsed = JSON.parse(root.extensionsJson || "[]")
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

    GgFrame {
        anchors.fill: parent
        leftLegend: "WORKSPACE"
        rightLegend: "NAMED SURFACES"
        backgroundColor: "#161616"
        borderColor: "#6a6a6a"
    }

    Column {
        anchors.fill: parent
        anchors.leftMargin: 14
        anchors.rightMargin: 14
        anchors.topMargin: 22
        anchors.bottomMargin: 12
        spacing: 8

        Text {
            text: "Host"
            color: "#d8dee9"
            font.family: "monospace"
            font.pixelSize: 12
        }

        Row {
            spacing: 0
            height: 18

            Repeater {
                model: ["CODE", "TERMINAL", "WEB", "EXTERNAL", "SITE", "CRYPTO", "MARKETPLACE", "TMOG", "OSINT", "KNOWLEDGE", "RESEARCH", "MEDIA", "DRAW", "GAME_ENGINE", "NODES", "FLOW"]

                delegate: Text {
                    required property string modelData
                    required property int index
                    text: (index === 0 ? "" : " | ")
                        + (modelData === "GAME_ENGINE" ? "GAME ENGINE" : modelData)
                    color: root.hostKind === modelData
                        ? "#d8dee9"
                        : root.hostEnabled(modelData)
                            ? "#5d6670"
                            : "#3f464d"
                    opacity: root.hostEnabled(modelData) ? 1.0 : 0.7
                    font.family: "monospace"
                    font.pixelSize: 12
                    font.bold: root.hostKind === modelData

                    MouseArea {
                        anchors.fill: parent
                        enabled: root.hostEnabled(modelData)
                        cursorShape: enabled
                            ? Qt.PointingHandCursor
                            : Qt.ArrowCursor
                        onClicked: root.hostKindChangedByUser(modelData)
                    }
                }
            }
        }

        Row {
            spacing: 10

            GgCheck {
                id: innerChromeBox
                text: "Show inner CODE frame"
                checked: root.showInnerEditorChrome
                onToggled:
                    root.showInnerEditorChromeChangedByUser(
                        innerChromeBox.checked
                    )
            }

            GgButton {
                text: "New tab +"
                onClicked: root.spawnInstanceRequested()
            }
        }

        Text {
            text: "Workspace folders · MULTI-ROOT"
            color: "#c7a873"
            font.family: "monospace"
            font.pixelSize: 11
            font.bold: true
        }

        Column {
            width: parent.width
            spacing: 4

            Repeater {
                model: root.folderRows()
                delegate: Row {
                    required property string modelData
                    required property int index
                    width: parent.width
                    height: 26
                    spacing: 6

                    Text {
                        width: parent.width - removeFolderButton.width - 6
                        anchors.verticalCenter: parent.verticalCenter
                        text: "ROOT " + (index + 1) + " · " + modelData
                        color: "#c8cdd4"
                        font.family: "monospace"
                        font.pixelSize: 10
                        elide: Text.ElideMiddle
                    }

                    GgButton {
                        id: removeFolderButton
                        width: 70
                        height: 24
                        text: "REMOVE"
                        onClicked: root.removeFolder(index)
                    }
                }
            }
        }

        Row {
            spacing: 8

            GgButton {
                text: "ADD FOLDER"
                onClicked: folderDialog.open()
            }

            GgCheck {
                id: trustWorkspaceBox
                text: "Trust workspace"
                checked: root.workspaceTrusted
                onToggled: root.workspaceTrustedChangedByUser(
                    trustWorkspaceBox.checked
                )
            }
        }

        Text {
            width: parent.width
            text: "Folders are stored as workspace context, like a VS Code multi-root workspace. Trust is an explicit UI flag; it does not bypass GG task approval, safe-tool or network policy."
            color: "#77818b"
            wrapMode: Text.WordWrap
            font.family: "monospace"
            font.pixelSize: 10
        }

        Text {
            width: parent.width
            text: "Same as the workspace footer and top tabs. "
                + "WEB is your browser in this box. SITE is the local "
                + "WordPress copy (files + MariaDB 3307). PREVIEW runs "
                + "PHP on 127.0.0.1 only. After you approve the requested "
                + "task in chat, network, production and one.com actions "
                + "can use the visible operator flow. EXTERNAL "
                + "hosts Blender in this box for clay assets. MEDIA is playlists, radio, TV "
                + "and older-console games; the bottom strip is the player. "
                + "DRAW hosts Krita, GIMP, Inkscape or darktable in this box "
                + "when they are on PATH, plus a small sketch pad. OSINT is "
                + "the native OSIRIS public-feed dashboard; its RECON page "
                + "stays read-only and target-free. KNOWLEDGE combines local PDF/text import, "
                + "page citations and clickable raster illustrations. RESEARCH combines evidence, "
                + "method memory, reverse engineering and the local WASM lab. GAME ENGINE "
                + "is a separate local Quick3D playground with fixed-step "
                + "simulation, bounded pools and deterministic replay. NODES is "
                + "the Geometry Nodes-style editor for agent and information "
                + "streams: blocks, edge ports, and wires on the machine graph."
            color: "#8a8a8a"
            wrapMode: Text.WordWrap
            font.pixelSize: 12
        }
    }

    FolderDialog {
        id: folderDialog
        title: "ADD WORKSPACE FOLDER"
        onAccepted: root.addFolder(String(folderDialog.selectedFolder))
    }
}
