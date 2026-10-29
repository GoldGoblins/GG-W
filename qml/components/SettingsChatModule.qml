pragma ComponentBehavior: Bound


import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

Item {
    id: root

    property bool showOpenTabInInput: false
    property string engineTarget: "GROK_TUI"
    signal showOpenTabInInputChangedByUser(bool value)
    signal engineTargetChangedByUser(string value)

    implicitHeight: 168

    GgFrame { property string uiColorScope: "ui.widget.SettingsChatModule.GgFrame.1";
        anchors.fill: parent
        leftLegend: "CHAT"
        rightLegend: "MOTOR"
        backgroundColor: RuntimeTheme.GGTheme.panel
        borderColor: RuntimeTheme.GGTheme.edge
    }

    Column {
        anchors.fill: parent
        anchors.leftMargin: 14
        anchors.rightMargin: 14
        anchors.topMargin: 22
        anchors.bottomMargin: 12
        spacing: 8

        GGText { colorKey: "ui.SettingsChatModule.1";
            text: "Engine"
            color: RuntimeTheme.GGTheme.text
            font.family: "monospace"
            font.pixelSize: 12
        }

        Row {
            spacing: 0
            height: 18

            GGText { colorKey: "ui.SettingsChatModule.2";
                text: "GROK TUI"
                color: root.engineTarget === "GROK_TUI"
                    ? RuntimeTheme.GGTheme.text
                    : RuntimeTheme.GGTheme.dim
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
            GGText { colorKey: "ui.SettingsChatModule.3";
                text: " | "
                color: RuntimeTheme.GGTheme.muted
                font.family: "monospace"
                font.pixelSize: 12
            }
            GGText { colorKey: "ui.SettingsChatModule.4";
                text: "GPTUI"
                color: root.engineTarget === "GPT_TUI"
                    ? RuntimeTheme.GGTheme.text
                    : RuntimeTheme.GGTheme.dim
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
            GGText { colorKey: "ui.SettingsChatModule.5";
                text: " | "
                color: RuntimeTheme.GGTheme.muted
                font.family: "monospace"
                font.pixelSize: 12
            }
            GGText { colorKey: "ui.SettingsChatModule.6";
                text: "FLOW TUI"
                color: root.engineTarget === "FLOW_TUI"
                    ? RuntimeTheme.GGTheme.text
                    : RuntimeTheme.GGTheme.dim
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

        GgCheck { property string uiColorScope: "ui.widget.SettingsChatModule.GgCheck.2";
            id: openTabBox
            width: parent.width
            text: "Show the open tab name in the input frame"
            checked: root.showOpenTabInInput
            onToggled:
                root.showOpenTabInInputChangedByUser(openTabBox.checked)
        }

        GGText { colorKey: "ui.SettingsChatModule.7";
            width: parent.width
            text: "Same GROK TUI | GPTUI | FLOW TUI switch as under INPUT. Motor only. "
                + "The open tab name is optional chrome, not something "
                + "you type."
            color: RuntimeTheme.GGTheme.dim
            wrapMode: Text.WordWrap
            font.pixelSize: 12
        }
    }
}
