import QtQuick

// Fixed workspace panels need a body with an independent available height.
Item {
    id: root
    property string leftLegend: ""
    default property alias contentData: body.data
    implicitWidth: 320
    implicitHeight: 80
    GgFrame { anchors.fill: parent; leftLegend: root.leftLegend }
    Item {
        id: body
        anchors.fill: parent
        anchors.leftMargin: 8
        anchors.rightMargin: 8
        anchors.topMargin: 20
        anchors.bottomMargin: 8
        clip: true
    }
}
