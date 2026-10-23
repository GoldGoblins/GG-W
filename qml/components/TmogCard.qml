import QtQuick

Item {
    id: root
    property string leftLegend: ""
    property string rightLegend: ""
    property var tabs: []
    property string activeTab: ""
    property color borderColor: "#4a4a4a"
    property color fill: "#141414"
    property bool fitContent: false
    property bool lamp: false
    property bool lampOn: false
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
        color: root.fill
        border.color: root.borderColor
        border.width: 1
        radius: 4
        antialiasing: true
    }

    Rectangle {
        visible: root.tabs && root.tabs.length > 0
        anchors.left: parent.left
        anchors.leftMargin: 10
        anchors.top: parent.top
        anchors.topMargin: -7
        height: 18
        width: tabRow.implicitWidth + 10
        color: root.fill
        Row {
            id: tabRow
            anchors.centerIn: parent
            spacing: 8
            Repeater {
                model: root.tabs
                Text {
                    text: {
                        var item = (typeof modelData === "object" && modelData) ? modelData : {}
                        var label = String(item.label || item.id || "")
                        return index > 0 ? ("|  " + label) : label
                    }
                    color: {
                        var item = (typeof modelData === "object" && modelData) ? modelData : {}
                        return String(item.id || "") === root.activeTab ? "#d8dee9" : "#5d6670"
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

    Rectangle {
        visible: root.leftLegend.length > 0 && !(root.tabs && root.tabs.length)
        anchors.left: parent.left
        anchors.leftMargin: 10
        anchors.top: parent.top
        anchors.topMargin: -7
        height: 20
        width: leftTxt.implicitWidth + 10 + (root.lamp ? 14 : 0)
        color: root.fill
        Row {
            anchors.centerIn: parent
            spacing: 6
            Text {
                id: leftTxt
                text: root.leftLegend
                color: "#d8dee9"
                font.family: "monospace"
                font.pixelSize: 12
                font.bold: true
            }
            Rectangle {
                visible: root.lamp
                width: 8
                height: 8
                radius: 4
                anchors.verticalCenter: parent.verticalCenter
                color: root.lampOn ? "#e05050" : "#2a1515"
            }
        }
    }

    Rectangle {
        visible: root.rightLegend.length > 0
        anchors.right: parent.right
        anchors.rightMargin: 10
        anchors.top: parent.top
        anchors.topMargin: -7
        height: 20
        width: rightTxt.implicitWidth + 10
        color: root.fill
        Text {
            id: rightTxt
            anchors.centerIn: parent
            text: root.rightLegend
            color: "#c8cdd4"
            font.family: "monospace"
            font.pixelSize: 12
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
