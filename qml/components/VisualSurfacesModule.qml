pragma ComponentBehavior: Bound


import "." as RuntimeTheme
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

        GGText { colorKey: "ui.VisualSurfacesModule.1";
            text: "SURFACES · MODULE REGISTRY"
            color: RuntimeTheme.GGTheme.bright
            font.family: "monospace"
            font.pixelSize: 13
            font.bold: true
        }

        GGText { colorKey: "ui.VisualSurfacesModule.2";
            width: parent.width
            text: "Every visual box is addressed by a stable surface id. The registry connects layout handles, Settings and both native chat motors to the same presentation object."
            color: RuntimeTheme.GGTheme.muted
            wrapMode: Text.WordWrap
            font.family: "monospace"
            font.pixelSize: 11
        }

        Rectangle {
            width: parent.width
            height: 1
            color: RuntimeTheme.GGTheme.line
        }

        Repeater {
            model: root.rows()
            delegate: Rectangle {
                required property var modelData
                width: body.width
                height: 48
                color: root.selectedSurface === String(modelData.id || "")
                    ? RuntimeTheme.GGTheme.raised
                    : RuntimeTheme.GGTheme.panel
                border.color: root.selectedSurface === String(modelData.id || "")
                    ? RuntimeTheme.GGTheme.dim
                    : RuntimeTheme.GGTheme.line
                border.width: 1
                radius: 2

                Column {
                    anchors.left: parent.left
                    anchors.leftMargin: 9
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 2

                    GGText { colorKey: "ui.VisualSurfacesModule.3";
                        text: String(modelData.title || modelData.id || "SURFACE")
                        color: RuntimeTheme.GGTheme.bright
                        font.family: "monospace"
                        font.pixelSize: 11
                        font.bold: true
                    }

                    GGText { colorKey: "ui.VisualSurfacesModule.4";
                        text: String(modelData.id || "") + "  ·  "
                            + String(modelData.sourcePath || "")
                        color: RuntimeTheme.GGTheme.dim
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

                    GgButton { property string uiColorScope: "ui.control.VisualSurfacesModule.1";
                        text: "SELECT"
                        width: 58
                        height: 24
                        onClicked: root.surfaceSelected(String(modelData.id || ""))
                    }

                    GgButton { property string uiColorScope: "ui.control.VisualSurfacesModule.2";
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

        GGText { colorKey: "ui.VisualSurfacesModule.5";
            text: root.layoutLocked
                ? "LAYOUT LOCKED · unlock in EDITOR to move or resize surfaces"
                : "LAYOUT UNLOCKED · drag the six-dot bars or corner handles"
            color: root.layoutLocked ? RuntimeTheme.GGTheme.dim : RuntimeTheme.GGTheme.positive
            font.family: "monospace"
            font.pixelSize: 10
        }
    }
}
