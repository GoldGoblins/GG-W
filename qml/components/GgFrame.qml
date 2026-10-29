
import "." as RuntimeTheme
import QtQuick

Item {
    id: root

    property string leftLegend: ""
    property string rightLegend: ""
    property string bottomLeftLegend: ""
    property string bottomRightLegend: ""
    property color backgroundColor: RuntimeTheme.GGTheme.panel
    property color borderColor: RuntimeTheme.GGTheme.edge
    property color leftLegendColor: RuntimeTheme.GGTheme.bright
    property color rightLegendColor: RuntimeTheme.GGTheme.text
    property int radius: 4
    property int padding: 8
    property int legendGap: 8
    property bool compact: false
    property bool busy: false
    property bool edgeContent: false
    property var topGaps: []
    property var bottomGaps: []
    property real topRightReserved: 0
    readonly property Item contentItem: contentClip

    default property alias contentData: content.data

    readonly property bool hasTopLegend:
        root.leftLegend.length > 0 || root.rightLegend.length > 0
    readonly property bool hasBottomLegend:
        root.bottomLeftLegend.length > 0 || root.bottomRightLegend.length > 0

    readonly property real topAvailable: Math.max(0, width - 24 - topRightReserved)
    readonly property real leftNaturalWidth: leftLegendText.implicitWidth + 12
        + (busyMark.visible ? busyMark.width + leftLegendRow.spacing : 0)
    readonly property real rightCaptionWidth: rightLegend.length > 0
        ? Math.min(rightLegendText.implicitWidth + 12,
            Math.max(0, topAvailable - (leftLegend.length > 0 ? Math.min(leftNaturalWidth, topAvailable * 0.55) + legendGap : 0))) : 0
    readonly property real bottomAvailable: Math.max(0, width - 24)
    readonly property real bottomRightCaptionWidth: bottomRightLegend.length > 0
        ? Math.min(bottomRightLegendText.implicitWidth + 12,
            Math.max(0, bottomAvailable - (bottomLeftLegend.length > 0 ? Math.min(bottomLeftLegendText.implicitWidth + 12, bottomAvailable * 0.55) + legendGap : 0))) : 0

    readonly property int topChrome:
        root.edgeContent ? (root.hasTopLegend ? 12 : 1) : root.hasTopLegend ? (root.compact ? 18 : 20) : (root.compact ? 6 : 8)
    readonly property int bottomChrome:
        root.edgeContent ? 1 : root.hasBottomLegend ? (root.compact ? 12 : 14) : (root.compact ? 6 : 8)

    implicitWidth: 320
    implicitHeight: Math.max(
        36,
        content.implicitHeight + root.topChrome + root.bottomChrome
    )

    Rectangle {
        id: frame
        objectName: "frameInterior"
        anchors.fill: parent
        anchors.margins: 1
        radius: Math.max(0, root.radius - 1)
        color: root.backgroundColor
        antialiasing: true
    }

    LedgerBorder { property string uiColorScope: "ui.widget.GgFrame.LedgerBorder.1";
        objectName: "frameOutline"
        anchors.fill: parent
        radius: root.radius
        color: root.borderColor
        topGaps: root.topGaps.concat([
            {start: leftCaption.x, end: leftCaption.x + leftCaption.width},
            {start: rightCaption.x, end: rightCaption.x + rightCaption.width}
        ])
        bottomGaps: root.bottomGaps.concat([
            {start: bottomLeftCaption.x, end: bottomLeftCaption.x + bottomLeftCaption.width},
            {start: bottomRightCaption.x, end: bottomRightCaption.x + bottomRightCaption.width}
        ])
    }

    Item {
        id: leftCaption
        objectName: "frameLeftCaption"
        visible: root.leftLegend.length > 0
        anchors.left: parent.left
        anchors.leftMargin: 12
        anchors.top: parent.top
        anchors.topMargin: -8
        height: Math.max(18, leftLegendText.implicitHeight + 4)
        width: visible ? Math.min(root.leftNaturalWidth,
            Math.max(0, root.topAvailable - root.rightCaptionWidth - (root.rightCaptionWidth > 0 ? root.legendGap : 0))) : 0

        Row {
            id: leftLegendRow
            anchors.centerIn: parent
            width: Math.max(0, parent.width - 12)
            spacing: 6

            GGText { colorKey: "ui.GgFrame.1";
                id: leftLegendText
                width: Math.max(0, parent.width - (busyMark.visible ? busyMark.width + parent.spacing : 0))
                text: root.leftLegend
                textFormat: Text.PlainText
                elide: Text.ElideRight
                color: root.leftLegendColor
                font.family: "monospace"
                font.pixelSize: 12
                font.bold: true
                verticalAlignment: Text.AlignVCenter
            }

            BufferMark { property string uiColorScope: "ui.widget.GgFrame.BufferMark.2";
                id: busyMark
                objectName: "frameBufferMark"
                anchors.verticalCenter: parent.verticalCenter
                active: root.busy && root.visible
                cell: 5
            }
        }
    }

    Item {
        id: rightCaption
        objectName: "frameRightCaption"
        visible: root.rightLegend.length > 0
        anchors.right: parent.right
        anchors.rightMargin: 12 + root.topRightReserved
        anchors.top: parent.top
        anchors.topMargin: -8
        height: Math.max(18, rightLegendText.implicitHeight + 4)
        width: root.rightCaptionWidth

        GGText { colorKey: "ui.GgFrame.2";
            id: rightLegendText
            anchors.centerIn: parent
            width: Math.max(0, parent.width - 12)
            text: root.rightLegend
            textFormat: Text.PlainText
            elide: Text.ElideRight
            color: root.rightLegendColor
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: true
            verticalAlignment: Text.AlignVCenter
        }
    }

    Item {
        id: bottomLeftCaption
        objectName: "frameBottomLeftCaption"
        visible: root.bottomLeftLegend.length > 0
        anchors.left: parent.left
        anchors.leftMargin: 12
        anchors.bottom: parent.bottom
        anchors.bottomMargin: -8
        height: Math.max(18, bottomLeftLegendText.implicitHeight + 4)
        width: visible ? Math.min(bottomLeftLegendText.implicitWidth + 12,
            Math.max(0, root.bottomAvailable - root.bottomRightCaptionWidth - (root.bottomRightCaptionWidth > 0 ? root.legendGap : 0))) : 0

        GGText { colorKey: "ui.GgFrame.3";
            id: bottomLeftLegendText
            anchors.centerIn: parent
            width: Math.max(0, parent.width - 12)
            text: root.bottomLeftLegend
            textFormat: Text.PlainText
            elide: Text.ElideRight
            color: root.leftLegendColor
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: true
            verticalAlignment: Text.AlignVCenter
        }
    }

    Item {
        id: bottomRightCaption
        objectName: "frameBottomRightCaption"
        visible: root.bottomRightLegend.length > 0
        anchors.right: parent.right
        anchors.rightMargin: 12
        anchors.bottom: parent.bottom
        anchors.bottomMargin: -8
        height: Math.max(18, bottomRightLegendText.implicitHeight + 4)
        width: root.bottomRightCaptionWidth

        GGText { colorKey: "ui.GgFrame.4";
            id: bottomRightLegendText
            anchors.centerIn: parent
            width: Math.max(0, parent.width - 12)
            text: root.bottomRightLegend
            textFormat: Text.PlainText
            elide: Text.ElideRight
            color: root.rightLegendColor
            font.family: "monospace"
            font.pixelSize: 12
            verticalAlignment: Text.AlignVCenter
        }
    }

    Item {
        id: contentClip
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.leftMargin: root.edgeContent ? 1 : root.compact ? 6 : root.padding
        anchors.rightMargin: root.edgeContent ? 1 : root.compact ? 6 : root.padding
        anchors.topMargin: root.topChrome
        anchors.bottomMargin: root.bottomChrome
        clip: true

        Column {
            id: content
            width: parent.width
            spacing: 8
        }
    }
}
