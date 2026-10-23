pragma ComponentBehavior: Bound

import QtQuick

Item {
    id: root

    property string surfaceRegistryJson: "[]"
    property string selectedSurface: ""
    property bool layoutLocked: true

    signal surfaceSelected(string surfaceId)
    signal sourceRequested(string surfaceId)

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
            text: "SURFACES · MODULE REGISTRY"
            color: "#e6edf3"
            font.family: "monospace"
            font.pixelSize: 13
            font.bold: true
        }

        Text {
            width: parent.width
            text: "Every visual box is addressed by a stable surface id. The registry connects layout handles, Settings and both native chat motors to the same presentation object."
            color: "#a8b0b8"
            wrapMode: Text.WordWrap
            font.family: "monospace"
            font.pixelSize: 11
        }

        Rectangle {
            width: parent.width
            height: 1
            color: "#343a40"
        }

        Repeater {
            model: root.rows()
            delegate: Rectangle {
                required property var modelData
                width: body.width
                height: 48
                color: root.selectedSurface === String(modelData.id || "")
                    ? "#24292e"
                    : "#181818"
                border.color: root.selectedSurface === String(modelData.id || "")
                    ? "#8a8a8a"
                    : "#343a40"
                border.width: 1
                radius: 2

                Column {
                    anchors.left: parent.left
                    anchors.leftMargin: 9
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 2

                    Text {
                        text: String(modelData.title || modelData.id || "SURFACE")
                        color: "#e6edf3"
                        font.family: "monospace"
                        font.pixelSize: 11
                        font.bold: true
                    }

                    Text {
                        text: String(modelData.id || "") + "  ·  "
                            + String(modelData.sourcePath || "")
                        color: "#8b949e"
                        font.family: "monospace"
                        font.pixelSize: 9
                        elide: Text.ElideRight
                        width: Math.max(80, body.width - 180)
                    }
                }

                Row {
                    anchors.right: parent.right
                    anchors.rightMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 5

                    GgButton {
                        text: "SELECT"
                        width: 58
                        height: 24
                        onClicked: root.surfaceSelected(String(modelData.id || ""))
                    }

                    GgButton {
                        text: "</>"
                        width: 38
                        height: 24
                        onClicked: root.sourceRequested(String(modelData.id || ""))
                    }
                }

                MouseArea {
                    anchors.fill: parent
                    z: -1
                    onClicked: root.surfaceSelected(String(modelData.id || ""))
                }
            }
        }

        Text {
            text: root.layoutLocked
                ? "LAYOUT LOCKED · unlock in EDITOR to move or resize surfaces"
                : "LAYOUT UNLOCKED · drag the six-dot bars or corner handles"
            color: root.layoutLocked ? "#8b949e" : "#8db89a"
            font.family: "monospace"
            font.pixelSize: 10
        }
    }
}
