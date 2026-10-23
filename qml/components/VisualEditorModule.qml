pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls

Item {
    id: root

    property bool layoutLocked: true
    property string editorMode: "NORMAL"
    property string selectedSurface: ""
    property string surfaceRegistryJson: "[]"
    property string sourceText: ""
    property string sourcePath: ""
    property string sourceStatus: ""

    signal lockRequested(bool locked)
    signal modeRequested(string mode)
    signal surfaceRequested(string surfaceId)
    signal sourceSaveRequested(string source)
    signal sourceCloseRequested()

    implicitHeight: body.implicitHeight + 20

    function rows() {
        try {
            var value = JSON.parse(root.surfaceRegistryJson || "[]")
            return value instanceof Array ? value : []
        } catch (err) {
            return []
        }
    }

    Column {
        id: body
        width: parent.width
        spacing: 8

        Text {
            text: "EDITOR · LOCK / SOURCE"
            color: "#e6edf3"
            font.family: "monospace"
            font.pixelSize: 13
            font.bold: true
        }

        Row {
            spacing: 7

            GgButton {
                text: root.layoutLocked ? "UNLOCK LAYOUT" : "LOCK LAYOUT"
                checkable: true
                checked: !root.layoutLocked
                onClicked: root.lockRequested(!root.layoutLocked)
            }

            GgButton {
                text: "NORMAL"
                checkable: true
                checked: root.editorMode === "NORMAL"
                onClicked: root.modeRequested("NORMAL")
            }

            GgButton {
                text: "SHOW SOURCE"
                checkable: true
                checked: root.editorMode === "SOURCE"
                onClicked: root.modeRequested("SOURCE")
            }
        }

        Text {
            width: parent.width
            text: root.layoutLocked
                ? "Locked is the safe default. Unlocking exposes six-dot move bars and diagonal corner resize handles."
                : "Unlocked presentation mode. Geometry is saved to the active profile, while the current UI components remain the renderer."
            color: root.layoutLocked ? "#a8b0b8" : "#8db89a"
            wrapMode: Text.WordWrap
            font.family: "monospace"
            font.pixelSize: 10
        }

        Rectangle {
            width: parent.width
            height: 1
            color: "#343a40"
        }

        Text {
            text: "SELECT SURFACE · " + (root.selectedSurface.length
                ? root.selectedSurface
                : "none")
            color: "#c7a873"
            font.family: "monospace"
            font.pixelSize: 11
            font.bold: true
        }

        Flow {
            width: parent.width
            spacing: 5

            Repeater {
                model: root.rows()
                delegate: GgButton {
                    required property var modelData
                    text: String(modelData.title || modelData.id || "SURFACE")
                    checkable: true
                    checked: root.selectedSurface === String(modelData.id || "")
                    onClicked: root.surfaceRequested(String(modelData.id || ""))
                }
            }
        }

        Row {
            width: parent.width
            spacing: 8

            Text {
                text: root.sourcePath.length
                    ? root.sourcePath
                    : "Select a surface to load its source buffer."
                color: "#8b949e"
                font.family: "monospace"
                font.pixelSize: 10
                elide: Text.ElideMiddle
                width: Math.max(80, parent.width - 160)
                anchors.verticalCenter: parent.verticalCenter
            }

            GgButton {
                text: "CLOSE SOURCE"
                width: 112
                height: 24
                enabled: root.editorMode === "SOURCE"
                onClicked: root.sourceCloseRequested()
            }
        }

        ScrollView {
            width: parent.width
            height: Math.max(150, Math.min(430, root.height - 135))
            clip: true
            ScrollBar.vertical: GgScrollBar {}

            TextArea {
                id: sourceEditor
                width: Math.max(80, parent.width - 8)
                height: Math.max(parent.height, contentHeight + 14)
                text: root.sourceText
                enabled: root.editorMode === "SOURCE"
                color: "#d9e0e7"
                selectedTextColor: "#f2f2f2"
                selectionColor: "#343a40"
                font.family: "monospace"
                font.pixelSize: 10
                wrapMode: TextEdit.NoWrap
                selectByMouse: true
                background: Rectangle {
                    color: "#0d0f10"
                    border.color: sourceEditor.activeFocus
                        ? "#8a8a8a"
                        : "#343a40"
                    border.width: 1
                }
            }
        }

        Row {
            spacing: 8

            GgButton {
                text: "SAVE BUFFER"
                enabled: root.selectedSurface.length > 0
                    && root.editorMode === "SOURCE"
                onClicked: root.sourceSaveRequested(sourceEditor.text)
            }

            Text {
                text: root.sourceStatus.length
                    ? root.sourceStatus
                    : "profile-local buffer · canonical write authority: NONE"
                color: root.sourceStatus.indexOf("FAIL") >= 0
                    ? "#d18b8b"
                    : "#8b949e"
                font.family: "monospace"
                font.pixelSize: 10
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }
}
