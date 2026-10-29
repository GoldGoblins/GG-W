pragma ComponentBehavior: Bound


import "." as RuntimeTheme
import QtQuick

FocusScope {
    id: root
    objectName: "grokTuiHost"
    clip: true
    focus: visible

    property var surfaceHost: null
    // Both engines use the same terminal surface and input styling.  The
    // identity only selects which PTY receives paste/shortcut events.
    property string terminalId: "ws.tui.grok"
    // TerminalGrid uses this space exclusively for the scrollbar.
    property real terminalRightInset: terminalScrollBar.width
    property int scrollOffset: 0
    property int scrollMaximum: 0
    property int scrollPage: 1
    property string noticeText: ""
    property string clipboardNoticeText: ""
    readonly property bool restoringChat: Boolean(root.surfaceHost
        && root.surfaceHost.startupChatRestoring
        && root.surfaceHost.startupChatTerminal === root.terminalId)

    function applyScrollMetrics(offset, maximum, page) {
        var safeMaximum = Math.max(0, Number(maximum) || 0)
        root.scrollMaximum = safeMaximum
        root.scrollOffset = Math.max(
            0,
            Math.min(safeMaximum, Number(offset) || 0)
        )
        root.scrollPage = Math.max(1, Number(page) || 1)
    }

    function scrollFromBar(y) {
        if (root.scrollMaximum <= 0)
            return
        var track = Math.max(1, root.height)
        var thumb = Math.max(24, track * root.scrollPage /
            (root.scrollMaximum + root.scrollPage))
        var travel = Math.max(1, track - thumb)
        var visualRatio = Math.max(
            0,
            Math.min(1, (y - thumb / 2) / travel)
        )
        // offset 0 is the live tail, which belongs at the bottom of the
        // scrollbar; the largest offset is the oldest visible text at top.
        var offset = Math.round(
            (1 - visualRatio) * root.scrollMaximum
        )
        if (root.surfaceHost && root.surfaceHost.scrollChatTerminalTo)
            root.surfaceHost.scrollChatTerminalTo(
                root.terminalId,
                offset
            )
    }

    function scrollFromWheel(wheel) {
        var delta = Number(wheel.angleDelta.y)
        if (delta === 0)
            delta = Number(wheel.pixelDelta.y)
        if (
            !isFinite(delta)
            || delta === 0
            || !root.surfaceHost
            || !root.surfaceHost.scrollChatTerminal
        )
            return false
        return Boolean(root.surfaceHost.scrollChatTerminal(
            root.terminalId,
            delta
        ))
    }

    function focusTerminal() {
        if (
            !root.visible
            || !root.surfaceHost
            || !root.surfaceHost.focusChatTerminal
        )
            return false
        return Boolean(root.surfaceHost.focusChatTerminal(root.terminalId))
    }

    function showNotice(text) {
        root.noticeText = String(text || "")
        noticeTimer.restart()
        // A notice can arrive while the operator is typing in another
        // control.  Do not let feedback from the PTY steal that focus.
        if (root.activeFocus)
            Qt.callLater(root.focusTerminal)
    }

    Connections {
        target: root.surfaceHost
        function onTerminalScrollChanged(id, offset, maximum, page) {
            if (id === root.terminalId)
                root.applyScrollMetrics(offset, maximum, page)
        }
        function onChatTerminalNotice(id, text) {
            if (id === root.terminalId)
                root.showNotice(text)
        }
        function onChatTerminalFocusRequested(id) {
            if (id === root.terminalId && root.visible && root.activeFocus)
                Qt.callLater(root.focusTerminal)
        }
    }

    onVisibleChanged: {
        if (visible) {
            root.forceActiveFocus()
            // The Python-created TerminalGrid is attached just after the
            // visibility change.  Refocus it on the next QML turn so the
            // hidden composer cannot win the first-input race.
            Qt.callLater(root.focusTerminal)
        }
    }

    Connections {
        target: root.surfaceHost
        // A QML reload may precede the backend restart after an update.
        ignoreUnknownSignals: true
        function onChatClipboardNotice(id, text) {
            if (id === root.terminalId)
                root.clipboardNoticeText = String(text || "")
        }
    }

    Item {
        objectName: "grokTuiPrompt"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 30
        height: 38
        enabled: false
    }

    // QQuickPaintedItem normally receives wheel events itself, but a QML
    // FocusScope can win the event-routing race depending on which child was
    // created first.  This transparent proxy keeps wheel scrolling reliable
    // without participating in ordinary clicks or drag-selection.
    MouseArea {
        objectName: "grokTuiWheelProxy"
        anchors.fill: parent
        z: 1000
        acceptedButtons: Qt.NoButton
        propagateComposedEvents: true
        onWheel: function(wheel) {
            wheel.accepted = root.scrollFromWheel(wheel)
        }
    }

    WheelHandler {
        id: terminalWheelHandler
        target: null
        onWheel: function(wheel) {
            wheel.accepted = root.scrollFromWheel(wheel)
        }
    }

    Timer {
        id: noticeTimer
        interval: 5000
        repeat: false
        onTriggered: root.noticeText = ""
    }

    Rectangle {
        id: terminalNotice
        objectName: "grokTuiNotice"
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: 8
        height: visible ? 34 : 0
        z: 1200
        visible: root.noticeText.length > 0
        color: "#24292f"
        border.color: RuntimeTheme.GGTheme.edge
        border.width: 1
        radius: 3

        GGText { colorKey: "ui.GrokTuiHole.1";
            id: noticeLabel
            anchors.fill: parent
            anchors.margins: 6
            text: root.noticeText
            color: RuntimeTheme.GGTheme.bright
            font.family: "monospace"
            font.pixelSize: 12
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
    }

    Rectangle {
        objectName: "chatClipboardNotice"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: 8
        anchors.rightMargin: 8
        anchors.bottomMargin: 72
        height: clipboardNoticeLabel.implicitHeight + 16
        z: 1200
        visible: root.clipboardNoticeText.length > 0
        color: "#30251b"
        border.color: RuntimeTheme.GGTheme.accent
        border.width: 1
        radius: 3

        GGText { colorKey: "ui.GrokTuiHole.2";
            id: clipboardNoticeLabel
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.margins: 8
            text: root.clipboardNoticeText
            color: "#f0e5d7"
            font.family: "monospace"
            font.pixelSize: 12
            wrapMode: Text.Wrap
        }
    }

    Rectangle {
        objectName: "startupChatOverlay"
        anchors.fill: parent
        z: 1300
        visible: root.restoringChat
        color: RuntimeTheme.GGTheme.panel

        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.AllButtons
            onWheel: function(wheel) { wheel.accepted = true }
        }

        Column {
            anchors.centerIn: parent
            width: Math.max(180, parent.width - 40)
            spacing: 12

            BufferMark { property string uiColorScope: "ui.widget.GrokTuiHole.BufferMark.1";
                anchors.horizontalCenter: parent.horizontalCenter
                active: root.restoringChat
                cell: 5
            }
            GGText { colorKey: "ui.GrokTuiHole.3";
                width: parent.width
                text: "Restoring your latest chat"
                color: RuntimeTheme.GGTheme.accent
                font.family: "monospace"
                font.pixelSize: 13
                horizontalAlignment: Text.AlignHCenter
            }
            GGText { colorKey: "ui.GrokTuiHole.4";
                width: parent.width
                text: "Opening at the newest messages"
                color: RuntimeTheme.GGTheme.dim
                font.family: "monospace"
                font.pixelSize: 11
                horizontalAlignment: Text.AlignHCenter
            }
            GgButton { property string uiColorScope: "ui.control.GrokTuiHole.1";
                objectName: "showStartupChatButton"
                anchors.horizontalCenter: parent.horizontalCenter
                visible: root.surfaceHost && !root.surfaceHost.startupChatBlocking
                text: "SHOW CHAT"
                onClicked: root.surfaceHost.showStartupChat()
            }
        }
    }

    // TerminalGrid is intentionally not a Flickable, so expose its bounded
    // inline history with the same visible grab handle as the rest of the UI.
    Rectangle {
        id: terminalScrollBar
        objectName: "grokTuiScrollBar"
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        width: 9
        z: 1100
        color: "#1b1e22"
        opacity: root.scrollMaximum > 0 ? 0.9 : 0.35
        visible: true

        Rectangle {
            id: terminalScrollThumb
            x: 2
            width: parent.width - 4
            height: Math.max(
                24,
                parent.height * root.scrollPage /
                    (root.scrollMaximum + root.scrollPage)
            )
            y: (parent.height - height) *
                (root.scrollMaximum > 0
                    ? 1 - Math.max(
                        0,
                        Math.min(1, root.scrollOffset / root.scrollMaximum)
                    )
                    : 0)
            radius: 2
            visible: root.scrollMaximum > 0
            color: terminalScrollMouse.pressed
                ? RuntimeTheme.GGTheme.text
                : (terminalScrollMouse.containsMouse ? RuntimeTheme.GGTheme.muted : "#707780")
            opacity: terminalScrollMouse.pressed || terminalScrollMouse.containsMouse
                ? 1.0 : 0.82
        }

        MouseArea {
            id: terminalScrollMouse
            anchors.fill: parent
            acceptedButtons: Qt.LeftButton
            enabled: root.scrollMaximum > 0
            hoverEnabled: true
            onPressed: function(mouse) {
                root.scrollFromBar(mouse.y)
            }
            onPositionChanged: function(mouse) {
                if (pressed)
                    root.scrollFromBar(mouse.y)
            }
            onWheel: function(wheel) {
                wheel.accepted = root.scrollFromWheel(wheel)
            }
        }
    }
}
