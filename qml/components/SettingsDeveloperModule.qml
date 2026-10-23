pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls

Item {
    id: root

    property bool showDemoFixtures: false
    property bool showProductSourceTabs: false
    signal demoVisibilityChangedByUser(bool value)
    signal productSourceTabsChangedByUser(bool value)

    implicitHeight: 196

    GgFrame {
        anchors.fill: parent
        leftLegend: "DEVELOPER"
        rightLegend: "ALPHA"
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

        GgSwitch {
            id: demoSwitch
            width: parent.width
            text: "Show DEMO / SAMPLE fixtures"
            checked: root.showDemoFixtures

            onToggled:
                root.demoVisibilityChangedByUser(
                    demoSwitch.checked
                )
        }

        Text {
            width: parent.width
            text: "LIVE alpha hides synthetic fixtures by default. "
                + "This switch exposes legacy examples only for comparison."
            color: "#c8cdd4"
            wrapMode: Text.WordWrap
            font.pixelSize: 12
        }

        GgSwitch {
            id: productSourceSwitch
            width: parent.width
            text: "Show product source files"
            checked: root.showProductSourceTabs

            onToggled:
                root.productSourceTabsChangedByUser(
                    productSourceSwitch.checked
                )
        }

        Text {
            width: parent.width
            text: "ContextComposer.qml and the other desk papers are "
                + "internal sources. They stay off the CODE tabs unless "
                + "this is on."
            color: "#c8cdd4"
            wrapMode: Text.WordWrap
            font.pixelSize: 12
        }
    }
}
