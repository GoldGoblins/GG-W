pragma ComponentBehavior: Bound


import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

Item {
    id: root

    property real chatWidthRatio: 0.31
    property int telemetryWidth: 168
    property int utilityHeight: 112
    property bool desktopShell: false

    signal chatWidthRatioChangedByUser(real value)
    signal telemetryWidthChangedByUser(int value)
    signal utilityHeightChangedByUser(int value)
    signal desktopShellChangedByUser(bool value)

    implicitHeight: 328

    GgFrame { property string uiColorScope: "ui.widget.SettingsLayoutModule.GgFrame.1";
        anchors.fill: parent
        leftLegend: "LAYOUT"
        rightLegend: "LIVE"
        backgroundColor: RuntimeTheme.GGTheme.panel
        borderColor: RuntimeTheme.GGTheme.edge
    }

    Column {
        anchors.fill: parent
        anchors.leftMargin: 14
        anchors.rightMargin: 14
        anchors.topMargin: 22
        anchors.bottomMargin: 12
        spacing: 7

        GGText { colorKey: "ui.SettingsLayoutModule.1";
            text: "Chat width · "
                + Math.round(root.chatWidthRatio * 100)
                + "%"
            color: RuntimeTheme.GGTheme.text
            font.family: "monospace"
            font.pixelSize: 12
        }

        GgSlider { property string uiColorScope: "ui.widget.SettingsLayoutModule.GgSlider.2";
            id: chatSlider
            width: parent.width
            from: 0.24
            to: 0.42
            stepSize: 0.01
            value: root.chatWidthRatio

            onMoved:
                root.chatWidthRatioChangedByUser(
                    chatSlider.value
                )
        }

        GGText { colorKey: "ui.SettingsLayoutModule.2";
            text: "Telemetry width · "
                + String(root.telemetryWidth)
                + " px"
            color: RuntimeTheme.GGTheme.text
            font.family: "monospace"
            font.pixelSize: 12
        }

        GgSlider { property string uiColorScope: "ui.widget.SettingsLayoutModule.GgSlider.3";
            id: telemetrySlider
            width: parent.width
            from: 140
            to: 260
            stepSize: 4
            value: root.telemetryWidth

            onMoved:
                root.telemetryWidthChangedByUser(
                    Math.round(telemetrySlider.value)
                )
        }

        GGText { colorKey: "ui.SettingsLayoutModule.3";
            text: "Media / Utilities height · "
                + String(root.utilityHeight)
                + " px"
            color: RuntimeTheme.GGTheme.text
            font.family: "monospace"
            font.pixelSize: 12
        }

        GgSlider { property string uiColorScope: "ui.widget.SettingsLayoutModule.GgSlider.4";
            id: utilitySlider
            width: parent.width
            from: 72
            to: 180
            stepSize: 4
            value: root.utilityHeight

            onMoved:
                root.utilityHeightChangedByUser(
                    Math.round(utilitySlider.value)
                )
        }

        GgSwitch { property string uiColorScope: "ui.widget.SettingsLayoutModule.GgSwitch.5";
            id: desktopShellSwitch
            text: "Interactive desktop"
            checked: root.desktopShell
            onToggled: root.desktopShellChangedByUser(desktopShellSwitch.checked)
        }

        GGText { colorKey: "ui.SettingsLayoutModule.4";
            width: parent.width
            text: "Fills the work area under other windows, like a live wallpaper. "
                + "SETTINGS stays in the header. Click DESKTOP there to return to a window. "
                + "Turn off Plasma desktop icons if they steal clicks."
            color: RuntimeTheme.GGTheme.text
            wrapMode: Text.WordWrap
            font.pixelSize: 12
        }

        GGText { colorKey: "ui.SettingsLayoutModule.5";
            width: parent.width
            text: "Center Workspace keeps the remaining width. "
                + "Media / Utilities is a separate sibling surface."
            color: RuntimeTheme.GGTheme.text
            wrapMode: Text.WordWrap
            font.pixelSize: 12
        }
    }
}
