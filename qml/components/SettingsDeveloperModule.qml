pragma ComponentBehavior: Bound


import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

Item {
    id: root

    property bool showDemoFixtures: false
    property bool showProductSourceTabs: false
    signal demoVisibilityChangedByUser(bool value)
    signal productSourceTabsChangedByUser(bool value)

    implicitHeight: 196

    GgFrame { property string uiColorScope: "ui.widget.SettingsDeveloperModule.GgFrame.1";
        anchors.fill: parent
        leftLegend: "DEVELOPER"
        rightLegend: "ALPHA"
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

        GgSwitch { property string uiColorScope: "ui.widget.SettingsDeveloperModule.GgSwitch.2";
            id: demoSwitch
            width: parent.width
            text: "Show DEMO / SAMPLE fixtures"
            checked: root.showDemoFixtures

            onToggled:
                root.demoVisibilityChangedByUser(
                    demoSwitch.checked
                )
        }

        GGText { colorKey: "ui.SettingsDeveloperModule.1";
            width: parent.width
            text: "LIVE alpha hides synthetic fixtures by default. "
                + "This switch exposes legacy examples only for comparison."
            color: RuntimeTheme.GGTheme.text
            wrapMode: Text.WordWrap
            font.pixelSize: 12
        }

        GgSwitch { property string uiColorScope: "ui.widget.SettingsDeveloperModule.GgSwitch.3";
            id: productSourceSwitch
            width: parent.width
            text: "Show product source files"
            checked: root.showProductSourceTabs

            onToggled:
                root.productSourceTabsChangedByUser(
                    productSourceSwitch.checked
                )
        }

        GGText { colorKey: "ui.SettingsDeveloperModule.2";
            width: parent.width
            text: "ContextComposer.qml and the other desk papers are "
                + "internal sources. They stay off the CODE tabs unless "
                + "this is on."
            color: RuntimeTheme.GGTheme.text
            wrapMode: Text.WordWrap
            font.pixelSize: 12
        }
    }
}
