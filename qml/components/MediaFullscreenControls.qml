
import "." as RuntimeTheme
import QtQuick

Item {
    id: root
    objectName: "mediaFullscreenControls"

    property bool active: false
    property real positionSeconds: 0
    property real durationSeconds: 0
    property bool seekEnabled: false
    property bool liveStream: false
    property int volumeValue: 70
    property string playbackKey: ""
    property real seekPreview: -1
    property int volumePreview: -1
    property string seekGestureKey: ""
    readonly property bool timelineDragging: timelineMouse.pressed
    readonly property bool volumeDragging: volumeMouse.pressed
    readonly property bool revealed: root.active && (zoneHover.hovered || timelineMouse.pressed
        || volumeMouse.pressed || timelineMouse.activeFocus || volumeMouse.activeFocus)
    readonly property real shownPosition: root.seekPreview >= 0 ? root.seekPreview : root.positionSeconds
    readonly property real progress: root.durationSeconds > 0
        ? Math.max(0, Math.min(1, root.shownPosition / root.durationSeconds)) : 0
    readonly property int shownVolume: Math.max(0, Math.min(100,
        root.volumePreview >= 0 ? root.volumePreview : root.volumeValue))
    signal seekRequested(real seconds)
    signal volumePreviewed(int value)
    signal volumeCommitted(int value)

    height: 34
    visible: root.active
    opacity: root.revealed ? 1 : 0
    z: 3
    Behavior on opacity { NumberAnimation { duration: 140 } }
    // One compact rectangle: the 14px handles have 10px of hover padding
    // above and below, with 10–14px gaps around the horizontal controls.
    HoverHandler { id: zoneHover }

    function clock(seconds) {
        var total = Math.max(0, Math.floor(Number(seconds) || 0))
        var hours = Math.floor(total / 3600)
        var minutes = Math.floor(total / 60) % 60
        var secs = total % 60
        return (hours > 0 ? hours + ":" : "") + (minutes < 10 ? "0" : "") + minutes
            + ":" + (secs < 10 ? "0" : "") + secs
    }
    function previewSeek(x) {
        if (root.active && root.seekEnabled && root.seekGestureKey === root.playbackKey)
            root.seekPreview = Math.max(0, Math.min(1, x / Math.max(1, timelineMouse.width))) * root.durationSeconds
    }
    function previewVolume(x) {
        if (!root.active)
            return
        root.volumePreview = Math.round(Math.max(0, Math.min(1, x / Math.max(1, volumeMouse.width))) * 100)
        root.volumePreviewed(root.volumePreview)
    }
    onPlaybackKeyChanged: {
        root.seekGestureKey = ""
        root.seekPreview = -1
    }
    onSeekEnabledChanged: {
        if (!root.seekEnabled) {
            root.seekGestureKey = ""
            root.seekPreview = -1
        }
    }
    onActiveChanged: {
        if (!root.active) {
            root.seekGestureKey = ""
            root.seekPreview = -1
            root.volumePreview = -1
            timelineMouse.focus = false
            volumeMouse.focus = false
        }
    }

    Rectangle {
        id: panel
        anchors.fill: parent
        radius: 4
        color: "#dd151515"
        border.color: RuntimeTheme.GGTheme.edge
        border.width: 1

        MouseArea {
            id: timelineMouse
            objectName: "mediaFullscreenTimeline"
            anchors.left: timeLabel.right
            anchors.right: volumeBox.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.leftMargin: 12
            anchors.rightMargin: 14
            enabled: root.seekEnabled && root.active
            hoverEnabled: true
            activeFocusOnTab: true
            cursorShape: Qt.PointingHandCursor
            Accessible.role: Accessible.Slider
            Accessible.name: "Spola i videon"
            onPressed: function(mouse) {
                root.seekGestureKey = root.playbackKey
                root.previewSeek(mouse.x)
            }
            onPositionChanged: function(mouse) { if (pressed) root.previewSeek(mouse.x) }
            onReleased: function(mouse) {
                if (root.active && root.seekEnabled && root.seekGestureKey === root.playbackKey) {
                    root.previewSeek(mouse.x)
                    root.seekRequested(root.seekPreview)
                }
                root.seekPreview = -1
                root.seekGestureKey = ""
            }
            onCanceled: { root.seekPreview = -1; root.seekGestureKey = "" }
            Keys.onPressed: function(event) {
                if (event.key === Qt.Key_Left || event.key === Qt.Key_Right
                    || event.key === Qt.Key_Home || event.key === Qt.Key_End) {
                    var value = event.key === Qt.Key_Home ? 0 : event.key === Qt.Key_End ? root.durationSeconds
                        : root.positionSeconds + (event.key === Qt.Key_Left ? -5 : 5)
                    root.seekRequested(Math.max(0, Math.min(root.durationSeconds, value)))
                    event.accepted = true
                }
            }
            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                height: 4
                radius: 2
                color: "#414141"
                Rectangle {
                    width: parent.width * root.progress
                    height: parent.height
                    radius: 2
                    color: root.seekEnabled ? "#b7c0ca" : "#606060"
                }
            }
            Rectangle {
                objectName: "mediaFullscreenTimelineHandle"
                width: 14
                height: 14
                radius: 7
                anchors.verticalCenter: parent.verticalCenter
                x: Math.max(0, Math.min(parent.width - width, root.progress * parent.width - width / 2))
                visible: root.seekEnabled
                color: timelineMouse.pressed ? RuntimeTheme.GGTheme.bright : "#d6dce2"
            }
        }

        GGText { colorKey: "ui.MediaFullscreenControls.1";
            id: timeLabel
            objectName: "mediaFullscreenTimeLabel"
            anchors.left: parent.left
            anchors.leftMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            width: panel.width < 600 ? 100 : 140
            text: root.durationSeconds > 0 ? root.clock(root.shownPosition) + " / " + root.clock(root.durationSeconds)
                : root.liveStream ? "LIVE" : "00:00 / --:--"
            color: RuntimeTheme.GGTheme.text
            font.family: "monospace"
            font.pixelSize: 11
            elide: Text.ElideRight
        }

        Item {
            id: volumeBox
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.rightMargin: 10
            width: Math.min(220, Math.max(144, panel.width * .22))
            height: parent.height
            GGText { colorKey: "ui.MediaFullscreenControls.2";
                id: volumeLabel
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                text: "VOL"
                color: RuntimeTheme.GGTheme.text
                font.family: "monospace"
                font.pixelSize: 11
            }
            GGText { colorKey: "ui.MediaFullscreenControls.3";
                id: volumePercent
                objectName: "mediaFullscreenVolumeLabel"
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                width: 36
                text: root.shownVolume + "%"
                color: RuntimeTheme.GGTheme.text
                font.family: "monospace"
                font.pixelSize: 11
                horizontalAlignment: Text.AlignRight
            }
            MouseArea {
                id: volumeMouse
                objectName: "mediaFullscreenVolume"
                anchors.left: volumeLabel.right
                anchors.right: volumePercent.left
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                height: parent.height
                hoverEnabled: true
                activeFocusOnTab: true
                cursorShape: Qt.PointingHandCursor
                Accessible.role: Accessible.Slider
                Accessible.name: "Volym"
                onPressed: function(mouse) { root.previewVolume(mouse.x) }
                onPositionChanged: function(mouse) { if (pressed) root.previewVolume(mouse.x) }
                onReleased: function(mouse) {
                    if (root.active) {
                        root.previewVolume(mouse.x)
                        root.volumeCommitted(root.shownVolume)
                    }
                    root.volumePreview = -1
                }
                onCanceled: {
                    // Finish an interrupted grab once, so audible preview
                    // cannot leave the parent pending or polling while hidden.
                    if (root.active && root.volumePreview >= 0)
                        root.volumeCommitted(root.volumePreview)
                    root.volumePreview = -1
                }
                Keys.onPressed: function(event) {
                    if (event.key === Qt.Key_Left || event.key === Qt.Key_Right
                        || event.key === Qt.Key_Home || event.key === Qt.Key_End) {
                        var value = event.key === Qt.Key_Home ? 0 : event.key === Qt.Key_End ? 100
                            : root.volumeValue + (event.key === Qt.Key_Left ? -5 : 5)
                        root.volumeCommitted(Math.max(0, Math.min(100, value)))
                        event.accepted = true
                    }
                }
                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    height: 4
                    radius: 2
                    color: "#414141"
                    Rectangle {
                        width: parent.width * root.shownVolume / 100
                        height: parent.height
                        radius: 2
                        color: "#b7c0ca"
                    }
                }
                Rectangle {
                    objectName: "mediaFullscreenVolumeHandle"
                    width: 10
                    height: 14
                    radius: 2
                    anchors.verticalCenter: parent.verticalCenter
                    x: Math.max(0, Math.min(parent.width - width, parent.width * root.shownVolume / 100 - width / 2))
                    color: volumeMouse.pressed ? RuntimeTheme.GGTheme.bright : "#d6dce2"
                }
            }
        }
    }
}
