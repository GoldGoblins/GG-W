import QtQuick
import "." as RuntimeTheme

// Native retained geometry. Actual fractions are updated only by real samples;
// Qt interpolates presentation changes at the display's frame cadence.
Item {
    id: root
    property real fraction: 0
    property color barColor: RuntimeTheme.GGTheme.muted
    property string seriesKey: ""
    property bool animateChanges: true
    readonly property real boundedFraction: isFinite(fraction) ? Math.max(0, Math.min(1, fraction)) : 0
    property real renderedFraction: boundedFraction
    readonly property bool animationRunning: transition.running
    Behavior on renderedFraction {
        enabled: root.animateChanges && root.visible && RuntimeTheme.GGColorContext.applicationVisible
            && (!root.Window.window || (root.Window.window.visible && root.Window.window.visibility !== Window.Minimized))
        NumberAnimation { id: transition; duration: 220; easing.type: Easing.OutCubic }
    }
    Rectangle {
        id: fill
        objectName: "measurementBarFill"
        anchors.bottom: parent.bottom
        width: parent.width
        height: Math.min(parent.height, Math.max(1, parent.height * root.renderedFraction))
        color: root.barColor
        GGColorTarget { target: fill; colorKey: root.seriesKey; enabled: !!root.seriesKey }
    }
}
