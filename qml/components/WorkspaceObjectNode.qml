pragma ComponentBehavior: Bound

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
    property color accentColor: "#8b949e"

    signal activated(string objectId)

    readonly property bool syntheticFixture:
        root.provenanceClass === "SYNTHETIC_UI_FIXTURE"
    readonly property bool realLocalFile:
        root.provenanceClass === "REAL_LOCAL_FILE"

    width: 188
    height: 128
    clip: true

    GgFrame {
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
        borderColor: "#6a6a6a"
        rightLegendColor: root.current
            ? root.accentColor
            : (
                root.syntheticFixture
                    ? "#c8a97e"
                    : "#8b949e"
            )
        padding: 10

        Text {
            width: parent.width
            text: root.title
            color: "#e6edf3"
            elide: Text.ElideRight
            font.pixelSize: 12
            font.bold: true
        }

        Text {
            width: parent.width
            text: root.objectId
            color: "#7d8590"
            elide: Text.ElideMiddle
            font.family: "monospace"
            font.pixelSize: 12
        }

        Text {
            width: parent.width
            text: root.realLocalFile
                ? "REAL_LOCAL_FILE"
                : root.provenanceClass
            color: root.syntheticFixture ? "#c8a97e" : "#c8cdd4"
            font.family: "monospace"
            font.pixelSize: 12
        }

        ActivityStrip {
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

        Text {
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
