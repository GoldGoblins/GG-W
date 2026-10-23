pragma ComponentBehavior: Bound

import QtQuick

Item {
    id: root

    implicitHeight: 106

    GgFrame {
        anchors.fill: parent
        leftLegend: "ACTIVITY"
        rightLegend: "TRUTHFUL"
        backgroundColor: "#161616"
        borderColor: "#6a6a6a"
    }

    Text {
        anchors.fill: parent
        anchors.leftMargin: 14
        anchors.rightMargin: 14
        anchors.topMargin: 22
        anchors.bottomMargin: 12
        text: "Activity may show real state, elapsed time and verified "
            + "evidence. Fabricated percentages remain forbidden when "
            + "there is no real denominator."
        color: "#c8cdd4"
        wrapMode: Text.WordWrap
        font.pixelSize: 12
    }
}
