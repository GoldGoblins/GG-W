
import "." as RuntimeTheme
import QtQuick

Item {
    id: root
    property string leftLegend: ""
    property string rightLegend: ""
    property var tabs: []
    property string activeTab: ""
    property color borderColor: RuntimeTheme.GGTheme.edge
    property color fill: RuntimeTheme.GGTheme.panel
    property bool fitContent: false
    property bool lamp: false
    property bool lampOn: false
    property string lampColorKey: "ui.fill.TmogCard.1"
    property color lampOnColor: RuntimeTheme.GGTheme.negative
    property color lampOffColor: "#2a1515"
    property bool lampPercentageCapable: false
    property real lampFraction: NaN
    property bool compactLegend: false
    readonly property real legendInset: Math.min(root.compactLegend ? 4 : 10, root.width / 2)
    readonly property real legendPadding: root.compactLegend ? 8 : 10
    readonly property real legendAvailable: Math.max(0, root.width - 2 * root.legendInset)
    readonly property bool hasTabs: !!root.tabs && root.tabs.length > 0
    readonly property bool hasLeftCaption: root.hasTabs || root.leftLegend.length > 0
    readonly property real leftNaturalWidth: root.hasTabs ? tabRow.implicitWidth + 10
        : leftTxt.implicitWidth + root.legendPadding + (root.lamp ? 14 : 0)
    readonly property real rightCaptionWidth: root.rightLegend.length > 0
        ? Math.min(rightTxt.implicitWidth + root.legendPadding, Math.max(0, root.legendAvailable
            - (root.hasLeftCaption ? Math.min(root.leftNaturalWidth, root.legendAvailable / 2) + 6 : 0)))
        : 0
    readonly property real leftCaptionWidth: root.hasLeftCaption
        ? Math.min(root.leftNaturalWidth, Math.max(0, root.legendAvailable
            - (root.rightCaptionWidth > 0 ? root.rightCaptionWidth + 6 : 0)))
        : 0
    default property alias body: inner.data
    signal tabChosen(string tabId)

    implicitHeight: root.fitContent
        ? Math.max(
            48,
            (inner.children.length > 0
                ? inner.children[0].implicitHeight
                : inner.childrenRect.height)
                + inner.anchors.topMargin
                + 12
        )
        : 80

    Rectangle {
        anchors.fill: parent
        anchors.margins: 1
        color: root.fill
        radius: 3
    }

    LedgerBorder { property string uiColorScope: "ui.widget.TmogCard.LedgerBorder.1";
        anchors.fill: parent
        color: root.borderColor
        radius: 4
        topGaps: [
            {start: tabsLegend.x, end: tabsLegend.x + (tabsLegend.visible ? tabsLegend.width : 0)},
            {start: leftLegend.x, end: leftLegend.x + (leftLegend.visible ? leftLegend.width : 0)},
            {start: rightLegend.x, end: rightLegend.x + (rightLegend.visible ? rightLegend.width : 0)}
        ]
    }

    Item {
        id: tabsLegend
        objectName: "tmogCardTabsCaption"
        visible: root.hasTabs
        anchors.left: parent.left
        anchors.leftMargin: root.legendInset
        anchors.top: parent.top
        anchors.topMargin: -7
        height: 18
        width: root.leftCaptionWidth
        Flickable {
            anchors.fill: parent
            anchors.leftMargin: Math.min(5, parent.width / 2)
            anchors.rightMargin: Math.min(5, parent.width / 2)
            contentWidth: tabRow.implicitWidth
            contentHeight: height
            clip: contentWidth > width
            interactive: contentWidth > width
            flickableDirection: Flickable.HorizontalFlick
            boundsBehavior: Flickable.StopAtBounds
            Row {
                id: tabRow
                anchors.verticalCenter: parent.verticalCenter
                spacing: 8
                Repeater {
                    model: root.tabs
                    GGText { colorKey: "ui.TmogCard.1";
                        text: {
                            var item = (typeof modelData === "object" && modelData) ? modelData : {}
                            var label = String(item.label || item.id || "")
                            return index > 0 ? ("|  " + label) : label
                        }
                        color: {
                            var item = (typeof modelData === "object" && modelData) ? modelData : {}
                            return String(item.id || "") === root.activeTab ? RuntimeTheme.GGTheme.text : RuntimeTheme.GGTheme.dim
                        }
                        font.family: "monospace"
                        font.pixelSize: 12
                        font.bold: {
                            var item = (typeof modelData === "object" && modelData) ? modelData : {}
                            return String(item.id || "") === root.activeTab
                        }
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                var item = (typeof modelData === "object" && modelData) ? modelData : {}
                                root.tabChosen(String(item.id || ""))
                            }
                        }
                    }
                }
            }
        }
    }

    Item {
        id: leftLegend
        objectName: "tmogCardLeftCaption"
        visible: root.leftLegend.length > 0 && !(root.tabs && root.tabs.length)
        anchors.left: parent.left
        anchors.leftMargin: root.legendInset
        anchors.top: parent.top
        anchors.topMargin: -7
        height: 20
        width: root.leftCaptionWidth
        Row {
            anchors.centerIn: parent
            spacing: 6
            GGText { colorKey: "ui.TmogCard.2";
                id: leftTxt
                width: Math.max(0, leftLegend.width - root.legendPadding - (legendLamp.visible ? 14 : 0))
                text: root.leftLegend
                textFormat: Text.PlainText
                elide: Text.ElideRight
                color: RuntimeTheme.GGTheme.text
                font.family: "monospace"
                font.pixelSize: root.compactLegend ? 10 : 12
                font.bold: true
            }
            Rectangle { GGColorTarget { colorKey: root.lampColorKey; colorActive: root.lampOn; fallbackColor: root.lampOnColor; percentageCapable:root.lampPercentageCapable;fraction:root.lampFraction }
                id: legendLamp
                objectName: "tmogActivityLamp"
                visible: root.lamp && leftLegend.width >= root.legendPadding + 14
                width: 8
                height: 8
                radius: 4
                anchors.verticalCenter: parent.verticalCenter
                color: root.lampOn ? root.lampOnColor : root.lampOffColor
            }
        }
    }

    Item {
        id: rightLegend
        objectName: "tmogCardRightCaption"
        visible: root.rightLegend.length > 0
        anchors.right: parent.right
        anchors.rightMargin: root.legendInset
        anchors.top: parent.top
        anchors.topMargin: -7
        height: 20
        width: root.rightCaptionWidth
        GGText { colorKey: "ui.TmogCard.3";
            id: rightTxt
            anchors.centerIn: parent
            width: Math.max(0, parent.width - root.legendPadding)
            text: root.rightLegend
            textFormat: Text.PlainText
            elide: Text.ElideRight
            color: RuntimeTheme.GGTheme.text
            font.family: "monospace"
            font.pixelSize: root.compactLegend ? 10 : 12
        }
    }

    Item {
        id: inner
        clip: true
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: root.fitContent ? undefined : parent.bottom
        anchors.leftMargin: 10
        anchors.rightMargin: 10
        anchors.topMargin: 16
        anchors.bottomMargin: root.fitContent ? 0 : 8
    }
}
