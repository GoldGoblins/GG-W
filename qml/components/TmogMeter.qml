
import "." as RuntimeTheme
import QtQuick

Item {
    id: root
    property real ratio: 0
    property int segments: 28
    property color onColor: RuntimeTheme.GGTheme.positive
    property color offColor: RuntimeTheme.GGTheme.hover
    property string seriesColorKey: ""
    readonly property string resolvedSeriesKey: seriesColorKey || RuntimeTheme.GGColorContext.keyFor(root)
    readonly property bool percentageCapable: true
    readonly property real fraction: isFinite(ratio) ? Math.max(0,Math.min(1,ratio)) : NaN
    readonly property color seriesOnColor: RuntimeTheme.GGColorContext.colorForValue(resolvedSeriesKey,onColor,fraction)
    height: 14

    Row {
        anchors.fill: parent
        spacing: 2

        Repeater {
            model: Math.max(4, root.segments)
            delegate: Rectangle {
                required property int index
                width: Math.max(
                    2,
                    (root.width - (root.segments - 1) * 2) / root.segments
                )
                height: root.height
                radius: 1
                color: index < Math.round(root.ratio * root.segments)
                    ? root.seriesOnColor
                    : root.offColor
            }
        }
    }
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.RightButton
        onPressed: function(mouse) {
            var p=RuntimeTheme.GGColorContext.hostOverlay ? root.mapToItem(RuntimeTheme.GGColorContext.hostOverlay,mouse.x,mouse.y) : root.mapToItem(null,mouse.x,mouse.y)
            RuntimeTheme.GGColorContext.openWhole(root,root.resolvedSeriesKey,root.seriesOnColor,p.x,p.y)
            mouse.accepted=true
        }
    }
}
