import QtQuick

Item {
    id: root

    property string leftLegend: ""
    property string rightLegend: ""
    property string bottomLeftLegend: ""
    property string bottomRightLegend: ""
    property color backgroundColor: "#161616"
    property color borderColor: "#4a4a4a"
    property color leftLegendColor: "#e6edf3"
    property color rightLegendColor: "#c8cdd4"
    property int radius: 4
    property int padding: 8
    property int legendGap: 8
    property bool compact: false
    property bool busy: false

    default property alias contentData: content.data

    readonly property bool hasTopLegend:
        root.leftLegend.length > 0 || root.rightLegend.length > 0
    readonly property bool hasBottomLegend:
        root.bottomLeftLegend.length > 0 || root.bottomRightLegend.length > 0

    readonly property int topChrome:
        root.hasTopLegend ? (root.compact ? 18 : 20) : (root.compact ? 6 : 8)
    readonly property int bottomChrome:
        root.hasBottomLegend ? (root.compact ? 12 : 14) : (root.compact ? 6 : 8)

    implicitWidth: 320
    implicitHeight: Math.max(
        36,
        content.implicitHeight + root.topChrome + root.bottomChrome
    )

    Rectangle {
        id: frame
        anchors.fill: parent
        radius: root.radius
        color: root.backgroundColor
        border.width: 1
        border.color: root.borderColor
        antialiasing: true
        clip: false
    }

    Rectangle {
        id: leftLegendPlate
        visible: root.leftLegend.length > 0
        anchors.left: parent.left
        anchors.leftMargin: 12
        anchors.top: parent.top
        anchors.topMargin: -8
        height: Math.max(18, leftLegendText.implicitHeight + 4)
        width: leftLegendRow.implicitWidth + 12
        color: root.backgroundColor
        radius: Math.min(3, Math.max(1, root.radius - 1))
        antialiasing: true

        Row {
            id: leftLegendRow
            anchors.centerIn: parent
            spacing: 6

            Text {
                id: leftLegendText
                text: root.leftLegend
                color: root.leftLegendColor
                font.family: "monospace"
                font.pixelSize: 12
                font.bold: true
                verticalAlignment: Text.AlignVCenter
            }

            BufferMark {
                objectName: "frameBufferMark"
                anchors.verticalCenter: parent.verticalCenter
                active: root.busy
                cell: 5
            }
        }
    }

    Rectangle {
        visible: root.rightLegend.length > 0
        anchors.right: parent.right
        anchors.rightMargin: 12
        anchors.top: parent.top
        anchors.topMargin: -8
        height: Math.max(18, rightLegendText.implicitHeight + 4)
        width: rightLegendText.implicitWidth + 12
        color: root.backgroundColor
        radius: Math.min(3, Math.max(1, root.radius - 1))
        antialiasing: true

        Text {
            id: rightLegendText
            anchors.centerIn: parent
            text: root.rightLegend
            color: root.rightLegendColor
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: true
            verticalAlignment: Text.AlignVCenter
        }
    }

    Rectangle {
        visible: root.bottomLeftLegend.length > 0
        anchors.left: parent.left
        anchors.leftMargin: 12
        anchors.bottom: parent.bottom
        anchors.bottomMargin: -8
        height: Math.max(18, bottomLeftLegendText.implicitHeight + 4)
        width: bottomLeftLegendText.implicitWidth + 12
        color: root.backgroundColor
        radius: Math.min(3, Math.max(1, root.radius - 1))
        antialiasing: true

        Text {
            id: bottomLeftLegendText
            anchors.centerIn: parent
            text: root.bottomLeftLegend
            color: root.leftLegendColor
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: true
            verticalAlignment: Text.AlignVCenter
        }
    }

    Rectangle {
        visible: root.bottomRightLegend.length > 0
        anchors.right: parent.right
        anchors.rightMargin: 12
        anchors.bottom: parent.bottom
        anchors.bottomMargin: -8
        height: Math.max(18, bottomRightLegendText.implicitHeight + 4)
        width: bottomRightLegendText.implicitWidth + 12
        color: root.backgroundColor
        radius: Math.min(3, Math.max(1, root.radius - 1))
        antialiasing: true

        Text {
            id: bottomRightLegendText
            anchors.centerIn: parent
            text: root.bottomRightLegend
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
        anchors.leftMargin: root.compact ? 6 : root.padding
        anchors.rightMargin: root.compact ? 6 : root.padding
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
