import QtQuick
import "." as Colors

// Opt-in fill target for bars, status dots and accent geometry. Only a right
// button is handled; ordinary actions and model bindings keep their behavior.
Item {
    id: root
    anchors.fill: parent
    property Item target: parent
    property string colorKey: ""
    property bool percentageCapable: false
    property real fraction: NaN
    property color fallbackColor: "#858585"
    // Activity indicators keep their native off-state binding. A chosen
    // colour replaces only the on-state, never the signal that drives it.
    property bool colorActive: true
    readonly property string resolvedKey: colorKey || Colors.GGColorContext.keyFor(root.target)
    readonly property color selectedColor: Colors.GGColorContext.colorForValue(resolvedKey, fallbackColor, fraction)
    readonly property bool customized: !!resolvedKey && Colors.GGColorContext.hasColor(resolvedKey)
    Binding {
        target: root.target
        property: "color"
        value: root.selectedColor
        when: root.target !== null && root.customized && root.colorActive
        restoreMode: Binding.RestoreBindingOrValue
    }
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.RightButton
        onPressed: function(mouse) {
            var p = Colors.GGColorContext.hostOverlay ? root.mapToItem(Colors.GGColorContext.hostOverlay, mouse.x, mouse.y) : root.mapToItem(null, mouse.x, mouse.y)
            Colors.GGColorContext.openFor(root, root.resolvedKey, "", -1, -1, p.x, p.y, false, String(root.colorActive ? root.target.color : root.fallbackColor))
            mouse.accepted = true
        }
    }
}
