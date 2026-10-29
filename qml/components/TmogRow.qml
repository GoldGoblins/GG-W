
import "." as RuntimeTheme
import QtQuick

Item {
    id: root
    property string text: ""
    property bool selected: false
    property color textColor: RuntimeTheme.GGTheme.text
    signal chosen()
    signal menuRequested()

    width: parent ? parent.width : 120
    height: 18

    Rectangle {
        anchors.fill: parent
        color: root.selected || hit.containsMouse ? RuntimeTheme.GGTheme.raised : "transparent"
        radius: 1
    }

    GGText { colorKey: "ui.TmogRow.1";
        anchors.fill: parent
        anchors.leftMargin: 2
        anchors.rightMargin: 2
        text: root.text
        color: root.selected ? RuntimeTheme.GGTheme.bright : root.textColor
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
