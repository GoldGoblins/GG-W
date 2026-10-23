import QtQuick

Item {
    id: root
    property string status: "UNKNOWN"
    property int sourceLine: -1
    property string code: ""
    property string message: ""
    property string suggestion: ""
    property bool blocking: false

    implicitWidth: 320
    implicitHeight: column.implicitHeight + 12

    Rectangle {
        anchors.fill: parent
        radius: 3
        color: "#0b1117"
        border.width: 1
        border.color: root.status === "PASS" ? "#365344"
            : root.status === "FAIL" || root.status === "BLOCKED" ? "#6b3d3d"
            : root.status === "WARNING" ? "#6a5838"
            : "#344b59"

        Column {
            id: column
            anchors.fill: parent
            anchors.margins: 6
            spacing: 3

            Text {
                width: parent.width
                text: root.status + (root.sourceLine > 0 ? " · L" + root.sourceLine : "")
                    + (root.code.length > 0 ? " · " + root.code : "")
                color: "#d8dee9"
                font.family: "monospace"
                font.pixelSize: 12
                font.bold: true
            }
            Text {
                width: parent.width
                text: root.message
                color: "#c7d0d9"
                wrapMode: Text.WordWrap
                font.pixelSize: 12
            }
            Text {
                visible: root.suggestion.length > 0
                width: parent.width
                text: "FIX · " + root.suggestion
                color: "#9eb6c3"
                wrapMode: Text.WordWrap
                font.pixelSize: 12
            }
        }
    }
}
