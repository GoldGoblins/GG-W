
import "." as RuntimeTheme
import QtQuick

Item {
    id: root
    property string leftLegend: ""
    property string rightLegend: ""
    readonly property real legendInset: Math.min(10, root.width / 2)
    readonly property real legendAvailable: Math.max(0, root.width - 2 * root.legendInset)
    readonly property real rightCaptionWidth: root.rightLegend.length > 0
        ? Math.min(rightTxt.implicitWidth + 12, Math.max(0, root.legendAvailable
            - (root.leftLegend.length > 0 ? Math.min(leftTxt.implicitWidth + 12, root.legendAvailable / 2) + 6 : 0)))
        : 0

    width: parent ? parent.width : 120
    height: 20

    LedgerRule { property string uiColorScope: "ui.widget.TmogRail.LedgerRule.1";
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        height: 1
        color: RuntimeTheme.GGTheme.edge
        gaps: [
            {start: leftLegend.x, end: leftLegend.x + (leftLegend.visible ? leftLegend.width : 0)},
            {start: rightLegend.x, end: rightLegend.x + (rightLegend.visible ? rightLegend.width : 0)}
        ]
    }

    Item {
        id: leftLegend
        objectName: "tmogRailLeftCaption"
        visible: root.leftLegend.length > 0
        anchors.left: parent.left
        anchors.leftMargin: root.legendInset
        anchors.verticalCenter: parent.verticalCenter
        height: 18
        width: root.leftLegend.length > 0
            ? Math.min(leftTxt.implicitWidth + 12, Math.max(0, root.legendAvailable
                - (root.rightCaptionWidth > 0 ? root.rightCaptionWidth + 6 : 0))) : 0
        GGText { colorKey: "ui.TmogRail.1";
            id: leftTxt
            anchors.centerIn: parent
            width: Math.max(0, parent.width - 12)
            text: root.leftLegend
            textFormat: Text.PlainText
            elide: Text.ElideRight
            color: RuntimeTheme.GGTheme.text
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: true
        }
    }

    Item {
        id: rightLegend
        objectName: "tmogRailRightCaption"
        visible: root.rightLegend.length > 0
        anchors.right: parent.right
        anchors.rightMargin: root.legendInset
        anchors.verticalCenter: parent.verticalCenter
        height: 18
        width: root.rightCaptionWidth
        GGText { colorKey: "ui.TmogRail.2";
            id: rightTxt
            anchors.centerIn: parent
            width: Math.max(0, parent.width - 12)
            text: root.rightLegend
            textFormat: Text.PlainText
            elide: Text.ElideRight
            color: RuntimeTheme.GGTheme.text
            font.family: "monospace"
            font.pixelSize: 12
        }
    }
}
