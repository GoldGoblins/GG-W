pragma ComponentBehavior: Bound


import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls
import QtQuick.Shapes

// One editor overlay is shared by every top-level presentation surface.  It
// does not reimplement the surface: it only supplies handles and a source
// view, then reports the user's intent back to Main.qml.
Item {
    id: root

    property var surfaceModel: []
    property bool layoutUnlocked: false
    property string editorMode: "NORMAL"
    property string sourceSurface: ""
    property string sourceText: ""
    property string sourcePath: ""
    property string sourceStatus: ""
    property color frameBorder: RuntimeTheme.GGTheme.edge
    property color accentColor: RuntimeTheme.GGTheme.accent

    signal surfaceResizeRequested(
        string surfaceId,
        string corner,
        real dx,
        real dy
    )
    signal surfaceMoveRequested(string surfaceId, real dx, real dy)
    signal sourceSaveRequested(string surfaceId, string source)
    signal sourceCloseRequested()

    Repeater {
        model: root.surfaceModel

        delegate: Item {
            required property var modelData
            property var target: modelData && modelData.target
                ? modelData.target
                : null
            property string surfaceId: modelData
                ? String(modelData.surfaceId || "")
                : ""
            property string surfaceTitle: modelData
                ? String(modelData.title || surfaceId)
                : surfaceId

            visible: (root.layoutUnlocked
                || (root.editorMode === "SOURCE"
                    && root.sourceSurface === surfaceId))
                && target !== null
                && target.visible
            x: target ? target.mapToItem(root, 0, 0).x : 0
            y: target ? target.mapToItem(root, 0, 0).y : 0
            width: target
                ? target.width * (target.visualScale !== undefined
                    ? target.visualScale
                    : 1)
                : 0
            height: target
                ? target.height * (target.visualScale !== undefined
                    ? target.visualScale
                    : 1)
                : 0
            z: 110

            component ResizeHandle: Item {
                required property string corner
                width: 12
                height: 12
                visible: root.layoutUnlocked
                    && surfaceId !== "wallet"
                    && surfaceId !== "settings"

                Shape {
                    id: triangle
                    objectName: "visualResizeGlyph_" + surfaceId + "_" + handleRoot.corner
                    anchors.fill: parent
        preferredRendererType: Shape.GeometryRenderer
                    readonly property string glyphPath: {
                        if (handleRoot.corner === "TOP_LEFT") {
                            return "M0 0 H" + width + " L0 " + height + " Z"
                        } else if (handleRoot.corner === "TOP_RIGHT") {
                            return "M" + width + " 0 H0 L" + width + " " + height + " Z"
                        } else if (handleRoot.corner === "BOTTOM_LEFT") {
                            return "M0 " + height + " V0 L" + width + " " + height + " Z"
                        } else {
                            return "M" + width + " " + height + " H0 L" + width + " 0 Z"
                        }
                    }
                    ShapePath {
                        fillColor: root.accentColor
                        strokeColor: "transparent"
                        strokeWidth: 0
                        PathSvg { path: triangle.glyphPath }
                    }
                }

                MouseArea {
                    anchors.fill: parent
                    cursorShape: handleRoot.corner === "TOP_LEFT"
                        || handleRoot.corner === "BOTTOM_RIGHT"
                        ? Qt.SizeFDiagCursor
                        : Qt.SizeBDiagCursor
                    property real pressX: 0
                    property real pressY: 0
                    onPressed: {
                        pressX = mouse.x
                        pressY = mouse.y
                    }
                    onPositionChanged: {
                        if (pressed)
                            {
                                var deltaX = mouse.x - pressX
                                var deltaY = mouse.y - pressY
                                pressX = mouse.x
                                pressY = mouse.y
                                root.surfaceResizeRequested(
                                    surfaceId,
                                    handleRoot.corner,
                                    deltaX,
                                    deltaY
                                )
                            }
                    }
                }

                id: handleRoot
            }

            Item {
                id: moveBar
                objectName: "visualMoveBar_" + surfaceId
                visible: root.layoutUnlocked
                    && surfaceId !== "wallet"
                    && surfaceId !== "settings"
                width: 46
                height: 14
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: parent.top
                anchors.topMargin: -7
                z: 30

                Row {
                    anchors.centerIn: parent
                    spacing: 3

                    Repeater {
                        model: 6

                        delegate: Rectangle {
                            required property int index
                            width: 4
                            height: 4
                            radius: 1
                            color: root.accentColor
                            opacity: moveBarMouse.pressed ? 1.0 : 0.82
                        }
                    }
                }

                MouseArea {
                    id: moveBarMouse
                    anchors.fill: parent
                    anchors.margins: -5
                    cursorShape: pressed
                        ? Qt.ClosedHandCursor
                        : Qt.OpenHandCursor
                    property real lastX: 0
                    property real lastY: 0
                    onPressed: {
                        lastX = mouse.x
                        lastY = mouse.y
                    }
                    onPositionChanged: {
                        if (!pressed)
                            return
                        var deltaX = mouse.x - lastX
                        var deltaY = mouse.y - lastY
                        lastX = mouse.x
                        lastY = mouse.y
                        root.surfaceMoveRequested(
                            surfaceId,
                            deltaX,
                            deltaY
                        )
                    }
                }
            }

            ResizeHandle { property string uiColorScope: "ui.widget.VisualLayoutOverlay.ResizeHandle.1";
                corner: "TOP_LEFT"
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.leftMargin: -6
                anchors.topMargin: -6
            }
            ResizeHandle { property string uiColorScope: "ui.widget.VisualLayoutOverlay.ResizeHandle.2";
                corner: "TOP_RIGHT"
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.rightMargin: -6
                anchors.topMargin: -6
            }
            ResizeHandle { property string uiColorScope: "ui.widget.VisualLayoutOverlay.ResizeHandle.3";
                corner: "BOTTOM_LEFT"
                anchors.left: parent.left
                anchors.bottom: parent.bottom
                anchors.leftMargin: -6
                anchors.bottomMargin: -6
            }
            ResizeHandle { property string uiColorScope: "ui.widget.VisualLayoutOverlay.ResizeHandle.4";
                corner: "BOTTOM_RIGHT"
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.rightMargin: -6
                anchors.bottomMargin: -6
            }

            Rectangle {
                id: sourceCard
                anchors.fill: parent
                anchors.margins: 2
                visible: root.editorMode === "SOURCE"
                    && root.sourceSurface === surfaceId
                color: "#111315"
                border.color: root.accentColor
                border.width: 1
                z: 20

                Column {
                    anchors.fill: parent
                    anchors.margins: 6
                    spacing: 5

                    Row {
                        width: parent.width
                        height: 22
                        spacing: 8

                        GGText { colorKey: "ui.VisualLayoutOverlay.1";
                            text: "SOURCE · " + surfaceTitle
                            color: RuntimeTheme.GGTheme.bright
                            font.family: "monospace"
                            font.pixelSize: 10
                            font.bold: true
                            elide: Text.ElideRight
                            width: Math.max(50, parent.width - 164)
                            anchors.verticalCenter: parent.verticalCenter
                        }

                        GGText { colorKey: "ui.VisualLayoutOverlay.2";
                            text: root.sourceStatus.length
                                ? root.sourceStatus
                                : root.sourcePath
                            color: root.sourceStatus.indexOf("FAIL") >= 0
                                ? "#d18b8b"
                                : root.accentColor
                            font.family: "monospace"
                            font.pixelSize: 9
                            elide: Text.ElideMiddle
                            width: 76
                            anchors.verticalCenter: parent.verticalCenter
                        }

                        GgButton { property string uiColorScope: "ui.control.VisualLayoutOverlay.1";
                            text: "SAVE BUFFER"
                            width: 76
                            height: 22
                            onClicked: root.sourceSaveRequested(
                                surfaceId,
                                sourceEdit.text
                            )
                        }
                    }

                    ScrollView {
                        id: sourceScroll
                        width: parent.width
                        height: Math.max(20, parent.height - 27)
                        clip: true
                        ScrollBar.vertical: GgScrollBar { property string uiColorScope: "ui.widget.VisualLayoutOverlay.GgScrollBar.6";}

                        TextArea {
                            id: sourceEdit
                            width: Math.max(40, sourceScroll.width - 8)
                            height: Math.max(
                                sourceScroll.height,
                                contentHeight + 12
                            )
                            text: root.sourceText
                            color: "#d9e0e7"
                            selectedTextColor: RuntimeTheme.GGTheme.bright
                            selectionColor: RuntimeTheme.GGTheme.line
                            placeholderTextColor: "#68727c"
                            font.family: "monospace"
                            font.pixelSize: 10
                            wrapMode: TextEdit.NoWrap
                            selectByMouse: true
                            background: Rectangle {
                                color: "#0d0f10"
                                border.color: RuntimeTheme.GGTheme.line
                                border.width: 1
                            }
                        }
                    }

                    Row {
                        width: parent.width
                        height: 22
                        spacing: 8

                        GGText { colorKey: "ui.VisualLayoutOverlay.3";
                            text: "Editable profile buffer · canonical disk write: NONE"
                            color: RuntimeTheme.GGTheme.dim
                            font.family: "monospace"
                            font.pixelSize: 9
                            anchors.verticalCenter: parent.verticalCenter
                            elide: Text.ElideRight
                            width: Math.max(40, parent.width - 92)
                        }

                        GgButton { property string uiColorScope: "ui.control.VisualLayoutOverlay.2";
                            text: "CLOSE"
                            width: 70
                            height: 22
                            onClicked: root.sourceCloseRequested()
                        }
                    }
                }
            }
        }
    }
}
