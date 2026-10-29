import QtQuick
import "." as RuntimeTheme

// A scene-graph presentation clock, never a sampler or a block producer.
// Only one clock is needed per visible chart. The observed timestamp is
// supplied by the real bounded measurement history; no new values are made up.
Item {
    id: root
    property bool active: false
    property real observationTime: NaN // Unix seconds, from the actual sample.
    property real cadenceMs: 2000
    property real nowMillis: Date.now()
    readonly property bool hasObservation: isFinite(observationTime) && observationTime > 0
    readonly property bool rendering: active && hasObservation && visible
        && RuntimeTheme.GGColorContext.applicationVisible
        && (!Window.window || (Window.window.visible && Window.window.visibility !== Window.Minimized))
    readonly property real ageSeconds: hasObservation ? Math.max(0, (nowMillis - observationTime * 1000) / 1000) : NaN
    // Progress toward the configured observation cadence, not block finality,
    // latency, an extra sample, or a promise of the next observation.
    readonly property real phase: hasObservation && isFinite(cadenceMs) && cadenceMs > 0
        ? Math.max(0, Math.min(1, ageSeconds * 1000 / cadenceMs)) : 0

    onObservationTimeChanged: nowMillis = Date.now()
    onRenderingChanged: if (rendering) nowMillis = Date.now()
    FrameAnimation {
        running: root.rendering
        onTriggered: root.nowMillis = Date.now()
    }
}
