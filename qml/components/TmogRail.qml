import QtQuick

Item {
    id: root
    property string leftLegend: ""
    property string rightLegend: ""

    width: parent ? parent.width : 120
    height: 20

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        height: 1
        color: "#4a4a4a"
    }

    Rectangle {
        visible: root.leftLegend.length > 0
        anchors.left: parent.left
        anchors.leftMargin: 10
        anchors.verticalCenter: parent.verticalCenter
        height: 18
        width: leftTxt.implicitWidth + 12
        color: "#1c1c1c"
        Text {
            id: leftTxt
            anchors.centerIn: parent
            text: root.leftLegend
            color: "#d8dee9"
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: true
        }
    }

    Rectangle {
        visible: root.rightLegend.length > 0
        anchors.right: parent.right
        anchors.rightMargin: 10
        anchors.verticalCenter: parent.verticalCenter
        height: 18
        width: rightTxt.implicitWidth + 12
        color: "#1c1c1c"
        Text {
            id: rightTxt
            anchors.centerIn: parent
            text: root.rightLegend
            color: "#c8cdd4"
            font.family: "monospace"
            font.pixelSize: 12
        }
    }
}
