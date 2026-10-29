pragma ComponentBehavior: Bound


import "." as RuntimeTheme
import QtQuick

Item {
    id: root

    objectName: "workspaceObjectNode"

    property string objectId: ""
    property string title: ""
    property string objectType: ""
    property string provenanceClass: ""
    property string sourcePath: ""
    property string activityState: "IDLE"
    property bool current: false
    property bool editorDirty: false
    property color accentColor: RuntimeTheme.GGTheme.accent

    signal activated(string objectId)

    readonly property bool syntheticFixture:
        root.provenanceClass === "SYNTHETIC_UI_FIXTURE"
    readonly property bool realLocalFile:
        root.provenanceClass === "REAL_LOCAL_FILE"

    width: 188
    height: 128
    clip: true

    GgFrame { property string uiColorScope: "ui.widget.WorkspaceObjectNode.GgFrame.1";
        id: frame
        anchors.fill: parent
        leftLegend: root.objectType
        rightLegend: root.current
            ? "@current"
            : (
                root.syntheticFixture
                    ? "DEMO"
                    : root.activityState
            )
        backgroundColor: root.current ? "#121416" : "#090d12"
        borderColor: RuntimeTheme.GGTheme.edge
        rightLegendColor: root.current
            ? root.accentColor
            : (
                root.syntheticFixture
                    ? RuntimeTheme.GGTheme.accent
                    : RuntimeTheme.GGTheme.dim
            )
        padding: 10

        GGText { colorKey: "ui.WorkspaceObjectNode.1";
            width: parent.width
            text: root.title
            color: RuntimeTheme.GGTheme.bright
            elide: Text.ElideRight
            font.pixelSize: 12
            font.bold: true
        }

        GGText { colorKey: "ui.WorkspaceObjectNode.2";
            width: parent.width
            text: root.objectId
            color: RuntimeTheme.GGTheme.dim
            elide: Text.ElideMiddle
            font.family: "monospace"
            font.pixelSize: 12
        }

        GGText { colorKey: "ui.WorkspaceObjectNode.3";
            width: parent.width
            text: root.realLocalFile
                ? "REAL_LOCAL_FILE"
                : root.provenanceClass
            color: root.syntheticFixture ? RuntimeTheme.GGTheme.accent : RuntimeTheme.GGTheme.text
            font.family: "monospace"
            font.pixelSize: 12
        }

        ActivityStrip { property string uiColorScope: "ui.widget.WorkspaceObjectNode.ActivityStrip.2";
            width: parent.width
            visible: !root.syntheticFixture
            activityState: root.activityState
            phase: root.editorDirty
                ? "BUFFER UNSAVED"
                : (
                    root.current
                        ? "@current"
                        : ""
                )
            percentage: -1
        }

        GGText { colorKey: "ui.WorkspaceObjectNode.4";
            visible: root.syntheticFixture
            width: parent.width
            text: "DEMO / SAMPLE · NO EXECUTION"
            color: "#7d7368"
            font.family: "monospace"
            font.pixelSize: 12
        }
    }

    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: root.activated(root.objectId)
    }
}
