import "." as RuntimeTheme
import QtQuick
import QtQuick.Shapes
import QtQuick.Controls

// Geometry is rebuilt only when valued positions, colors or size change.
// There is no timer, animation, offscreen canvas or full-window bitmap.
Item {
    id: root
    objectName: "walletAllocationArc"
    implicitWidth: 148
    implicitHeight: 76
    property var segments: []
    property string description: "Inga värderade tillgångar"
    readonly property real radius: Math.max(0, Math.min((width-6)/2, height-3))
    readonly property real centerX: width/2
    readonly property real centerY: height-3
    readonly property int segmentCount: segments.length
    Accessible.role: Accessible.Graphic
    Accessible.name: description
    Shape {
        anchors.fill: parent
        ShapePath {
            strokeColor: RuntimeTheme.GGTheme.line
            strokeWidth: 4
            fillColor: "transparent"
            capStyle: ShapePath.FlatCap
            PathAngleArc {centerX:root.centerX;centerY:root.centerY;radiusX:root.radius;radiusY:root.radius;startAngle:180;sweepAngle:180}
        }
    }
    Repeater {
        model: root.segments
        delegate: Shape {
            id: segment
            required property var modelData
            anchors.fill: parent
            ShapePath {
                strokeColor: segment.modelData.color
                strokeWidth: 4
                fillColor: "transparent"
                capStyle: ShapePath.FlatCap
                PathAngleArc {
                    centerX:root.centerX;centerY:root.centerY;radiusX:root.radius;radiusY:root.radius
                    startAngle:180+Number(segment.modelData.start)*180+(root.segments.length>1 ? .4 : 0)
                    sweepAngle:Math.max(0,Number(segment.modelData.fraction)*180-(root.segments.length>1 ? .8 : 0))
                }
            }
        }
    }
    HoverHandler {id: hover}
    ToolTip.visible: hover.hovered
    ToolTip.delay: 500
    ToolTip.text: root.description
}
