
import "." as RuntimeTheme
import QtQuick
import QtQuick.Shapes

// Transparent retained outline, independent of panel fill and captions.
// Straight edges are native quads; only tiny corners use vector geometry.
// No bitmap, mask, offscreen layer or paint loop.
Item {
    id: root
    property color color: RuntimeTheme.GGTheme.edge
    property real radius: 4
    property var topGaps: []
    property var bottomGaps: []
    readonly property real corner: Math.max(0, Math.min(radius, width / 2, height / 2))
    LedgerRule { property string uiColorScope: "ui.widget.LedgerBorder.LedgerRule.1";
        objectName: "ledgerTopEdge"
        x: root.corner
        width: Math.max(0, root.width - 2 * root.corner)
        height: 1
        color: root.color
        gaps: root.topGaps.map(function(g) { return {start: g.start - x, end: g.end - x} })
    }
    LedgerRule { property string uiColorScope: "ui.widget.LedgerBorder.LedgerRule.2";
        objectName: "ledgerBottomEdge"
        x: root.corner
        y: root.height - 1
        width: Math.max(0, root.width - 2 * root.corner)
        height: 1
        color: root.color
        gaps: root.bottomGaps.map(function(g) { return {start: g.start - x, end: g.end - x} })
    }
    Rectangle {
        y: root.corner
        width: 1
        height: Math.max(0, root.height - 2 * root.corner)
        color: root.color
        antialiasing: false
    }
    Rectangle {
        x: root.width - 1
        y: root.corner
        width: 1
        height: Math.max(0, root.height - 2 * root.corner)
        color: root.color
        antialiasing: false
    }
    Shape {
        anchors.fill: parent
        visible: root.corner > 0.5
        preferredRendererType: Shape.GeometryRenderer
        ShapePath {
            strokeColor: root.color
            strokeWidth: 1
            fillColor: "transparent"
            capStyle: ShapePath.FlatCap
            PathSvg {
                path: {
                    var c = root.corner
                    var r = c - 0.5
                    var w = root.width - 0.5
                    var h = root.height - 0.5
                    return "M .5 " + c + " A " + r + " " + r + " 0 0 1 " + c + " .5"
                        + " M " + (root.width-c) + " .5 A " + r + " " + r + " 0 0 1 " + w + " " + c
                        + " M " + w + " " + (root.height-c) + " A " + r + " " + r + " 0 0 1 " + (root.width-c) + " " + h
                        + " M " + c + " " + h + " A " + r + " " + r + " 0 0 1 .5 " + (root.height-c)
                }
            }
        }
    }
}
