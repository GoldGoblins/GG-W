import "." as RuntimeTheme
import QtQuick
import QtQuick.Shapes

// Retained line geometry: no bitmap surface or scripted repaint pass.
Item {
    id: root
    implicitWidth: 20
    implicitHeight: 20
    property string name: ""
    property color color: RuntimeTheme.GGTheme.muted
    property Item viewport: null
    // Retained paths must not be submitted when wholly outside a clipped
    // scroller. Reading the ancestor positions also tracks relayout/scroll.
    readonly property bool inViewport: {
        if (!viewport) return true
        var item = root
        var px = 0, py = 0
        while (item && item !== viewport.contentItem) {
            px += item.x
            py += item.y
            item = item.parent
        }
        return !!item && px + width > viewport.contentX && px < viewport.contentX + viewport.width
            && py + height > viewport.contentY && py < viewport.contentY + viewport.height
    }
    readonly property string glyphPath: {
        switch (root.name) {
        case "lock":
            return "M5 10 H19 V21 H5 Z M8 9 A4 4 0 0 1 16 9 M8 9 V10 M16 9 V10 M12 14 V17"
        case "shield":
            return "M12 2 L21 6 L20 14 L17 19 L12 22 L7 19 L4 14 L3 6 Z M12 6 V17"
        case "backup":
        case "vault":
            return "M6 3 H18 L22 14 L21 21 H3 L2 14 Z M3 14 H21 M9 17 H15 V18 H9 Z"
        case "copy":
            return "M8 7 H20 V21 H8 Z M15 7 V3 H3 V17 H8"
        case "clock":
            return "M21 12 A9 9 0 1 1 3 12 A9 9 0 1 1 21 12 M12 6 V12 L16 15"
        case "endpoint":
            return "M3 15 H6 V21 H3 Z M10 10 H13 V21 H10 Z M17 4 H20 V21 H17 Z"
        case "network":
            return "M21 12 A9 9 0 1 1 3 12 A9 9 0 1 1 21 12 M3 12 H21 M12 3 A4 9 0 1 1 12 21 A4 9 0 1 1 12 3"
        case "refresh":
            return "M18.602685 16.517140 A8 8 0 1 1 17.669358 6.355678 M18 2 V7 H23"
        case "key":
            return "M13 8 A5 5 0 1 1 3 8 A5 5 0 1 1 13 8 M11 12 L20 21 L22 19 L20 17 L18 19"
        default:
            return "M5 4 H19 V20 H5 Z M9 8 H15 M9 12 H15 M9 16 H13"
        }
    }

    Loader {
        // Hidden action pages retain their state, but need no path objects or
        // render nodes. Dispose those explicitly when leaving the page.
        active: root.visible && root.inViewport && root.width > 0 && root.height > 0
        sourceComponent: Shape {
            width: root.width
            height: root.height
            preferredRendererType: Shape.GeometryRenderer
            ShapePath {
                scale: Qt.size(root.width / 24, root.height / 24)
                strokeColor: root.color
                strokeWidth: 1.4 * Math.min(root.width, root.height) / 24
                fillColor: "transparent"
                capStyle: ShapePath.RoundCap
                joinStyle: ShapePath.RoundJoin
                PathSvg { path: root.glyphPath }
            }
        }
    }
    Accessible.ignored: true
}
