import QtQuick

Item {
    id: root
    property string text: ""
    property bool selected: false
    property color textColor: "#c8cdd4"
    signal chosen()
    signal menuRequested()

    width: parent ? parent.width : 120
    height: 18

    Rectangle {
        anchors.fill: parent
        color: root.selected || hit.containsMouse ? "#1c1c1c" : "transparent"
        radius: 1
    }

    Text {
        anchors.fill: parent
        anchors.leftMargin: 2
        anchors.rightMargin: 2
        text: root.text
        color: root.selected ? "#e6edf3" : root.textColor
        font.family: "monospace"
        font.pixelSize: 12
        elide: Text.ElideRight
        verticalAlignment: Text.AlignVCenter
    }

    MouseArea {
        id: hit
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        cursorShape: Qt.PointingHandCursor
        onClicked: function (mouse) {
            if (mouse.button === Qt.RightButton)
                root.menuRequested()
            else
                root.chosen()
        }
    }
}
