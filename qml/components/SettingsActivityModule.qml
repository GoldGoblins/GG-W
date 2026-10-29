pragma ComponentBehavior: Bound


import "." as RuntimeTheme
import QtQuick

Item {
    id: root

    implicitHeight: 106

    GgFrame { property string uiColorScope: "ui.widget.SettingsActivityModule.GgFrame.1";
        anchors.fill: parent
        leftLegend: "ACTIVITY"
        rightLegend: "TRUTHFUL"
        backgroundColor: RuntimeTheme.GGTheme.panel
        borderColor: RuntimeTheme.GGTheme.edge
    }

    GGText { colorKey: "ui.SettingsActivityModule.1";
        anchors.fill: parent
        anchors.leftMargin: 14
        anchors.rightMargin: 14
        anchors.topMargin: 22
        anchors.bottomMargin: 12
        text: "Activity may show real state, elapsed time and verified "
            + "evidence. Fabricated percentages remain forbidden when "
            + "there is no real denominator."
        color: RuntimeTheme.GGTheme.text
        wrapMode: Text.WordWrap
        font.pixelSize: 12
    }
}
