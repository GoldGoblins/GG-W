
import "." as RuntimeTheme
import QtQuick
import "LedgerGeometry.js" as Geometry

// Only surviving one-pixel native quads, no paint beneath the openings.
Item {
    id: root
    property color color: RuntimeTheme.GGTheme.edge
    property var gaps: []
    implicitHeight: 1
    readonly property var segments: Geometry.segments(0, width, gaps)
    Repeater {
        model: root.segments
        delegate: Rectangle {
            required property var modelData
            x: modelData.start
            width: modelData.end - modelData.start
            height: root.height
            color: root.color
            antialiasing: false
        }
    }
}
