
import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls
import QtQuick.Shapes

Button { property string uiColorScope: "ui.control.ResearchAction.1";
    id: control
    property string hint: ""
    property string iconKind: ""
    property bool quiet: true
    implicitHeight: 28
    implicitWidth: iconKind ? 30 : Math.max(30, contentItem.implicitWidth + 18)
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.name: hint || text
    opacity: !enabled ? 0.18 : (hovered || activeFocus || checked || !quiet ? 1 : (iconKind ? 0.26 : 0.68))
    contentItem: Item {
        implicitWidth: label.implicitWidth
        implicitHeight: 18
        GGText { colorKey: "ui.ResearchAction.1";
            id: label
            anchors.centerIn: parent
            visible: !control.iconKind
            text: control.text
            textFormat: Text.PlainText
            color: control.checked ? RuntimeTheme.GGTheme.accent : RuntimeTheme.GGTheme.text
            font.family: "monospace"
            font.pixelSize: 12
        }
        Shape {
            id: glyph
            width: 18; height: 18; anchors.centerIn: parent
            visible: !!control.iconKind
        preferredRendererType: Shape.GeometryRenderer
            readonly property string glyphPath: {
                switch (control.iconKind) {
                case "play": return "M6 4 L13 9 L6 14 Z"
                case "pause": return "M6 4 V14 M12 4 V14"
                case "stop": return "M5 5 L13 13 M13 5 L5 13"
                case "refresh": return "M13.387913 11.397128 A5 5 0 1 1 13.173564 6.246572 M14 3 V7 L10 6"
                case "open": return "M10 4 H14 V8 M14 4 L7 11 M6 5 H4 V14 H13 V12"
                case "previous": return "M12 4 L6 9 L12 14"
                case "next": return "M6 4 L12 9 L6 14"
                default: return ""
                }
            }
            ShapePath {
                strokeColor: RuntimeTheme.GGTheme.text
                strokeWidth: 1.4
                fillColor: "transparent"
                capStyle: ShapePath.RoundCap
                joinStyle: ShapePath.RoundJoin
                PathSvg { path: glyph.glyphPath }
            }
        }
    }
    background: Rectangle {
        color: control.down ? RuntimeTheme.GGTheme.hover : RuntimeTheme.GGTheme.panel
        border.color: control.activeFocus || control.checked ? RuntimeTheme.GGTheme.accent : RuntimeTheme.GGTheme.selected
        radius: 3
    }
    ToolTip.visible: hovered && hint.length > 0
    ToolTip.delay: 550
    ToolTip.text: hint
}
