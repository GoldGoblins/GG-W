pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls

Item {
    id: root

    property bool showOpenTabInInput: false
    property string engineTarget: "GROK_TUI"
    signal showOpenTabInInputChangedByUser(bool value)
    signal engineTargetChangedByUser(string value)

    implicitHeight: 168

    GgFrame {
        anchors.fill: parent
        leftLegend: "CHAT"
        rightLegend: "MOTOR"
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
            text: "Engine"
            color: "#d8dee9"
            font.family: "monospace"
            font.pixelSize: 12
        }

        Row {
            spacing: 0
            height: 18

            Text {
                text: "QWEN"
                color: root.engineTarget === "LOCAL_QWEN"
                    ? "#d8dee9"
                    : "#5d6670"
                font.family: "monospace"
                font.pixelSize: 12
                font.bold: root.engineTarget === "LOCAL_QWEN"

                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked:
                        root.engineTargetChangedByUser("LOCAL_QWEN")
                }
            }

            Text {
                text: " | "
                color: "#a8b0b8"
                font.family: "monospace"
                font.pixelSize: 12
            }

            Text {
                text: "GROK"
                color: root.engineTarget === "GROK_WORKER"
                    ? "#d8dee9"
                    : "#5d6670"
                font.family: "monospace"
                font.pixelSize: 12
                font.bold: root.engineTarget === "GROK_WORKER"

                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked:
                        root.engineTargetChangedByUser("GROK_WORKER")
                }
            }

            Text {
                text: " | "
                color: "#a8b0b8"
                font.family: "monospace"
                font.pixelSize: 12
            }

            Text {
                text: "GROK TUI"
                color: root.engineTarget === "GROK_TUI"
                    ? "#d8dee9"
                    : "#5d6670"
                font.family: "monospace"
                font.pixelSize: 12
                font.bold: root.engineTarget === "GROK_TUI"

                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked:
                        root.engineTargetChangedByUser("GROK_TUI")
                }
            }
            Text {
                text: " | "
                color: "#a8b0b8"
                font.family: "monospace"
                font.pixelSize: 12
            }
            Text {
                text: "GPTUI"
                color: root.engineTarget === "GPT_TUI"
                    ? "#d8dee9"
                    : "#5d6670"
                font.family: "monospace"
                font.pixelSize: 12
                font.bold: root.engineTarget === "GPT_TUI"

                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked:
                        root.engineTargetChangedByUser("GPT_TUI")
                }
            }
            Text {
                text: " | "
                color: "#a8b0b8"
                font.family: "monospace"
                font.pixelSize: 12
            }
            Text {
                text: "FLOW TUI"
                color: root.engineTarget === "FLOW_TUI"
                    ? "#d8dee9"
                    : "#5d6670"
                font.family: "monospace"
                font.pixelSize: 12
                font.bold: root.engineTarget === "FLOW_TUI"

                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked:
                        root.engineTargetChangedByUser("FLOW_TUI")
                }
            }
        }

        GgCheck {
            id: openTabBox
            width: parent.width
            text: "Show the open tab name in the input frame"
            checked: root.showOpenTabInInput
            onToggled:
                root.showOpenTabInInputChangedByUser(openTabBox.checked)
        }

        Text {
            width: parent.width
            text: "Same QWEN | GROK | GROK TUI | GPTUI switch as under INPUT. Motor only. "
                + "The open tab name is optional chrome, not something "
                + "you type."
            color: "#8a8a8a"
            wrapMode: Text.WordWrap
            font.pixelSize: 12
        }
    }
}
