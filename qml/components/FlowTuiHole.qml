pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls

FocusScope {
    id: root
    objectName: "flowTuiHost"
    clip: true
    focus: visible

    property var surfaceHost: null
    property string statusJson: "{}"
    property string draft: ""

    readonly property var status: {
        try {
            return JSON.parse(root.statusJson || "{}")
        } catch (err) {
            return {}
        }
    }
    readonly property var transcript: root.status.transcript || []
    readonly property bool busy: String((root.status.merge || {}).status || "") === "RUNNING"

    function applyRaw(raw) {
        if (raw === undefined || raw === null)
            return
        var value = String(raw)
        if (value === root.statusJson)
            return
        root.statusJson = value
        Qt.callLater(function() {
            logFlick.contentY = Math.max(0, logFlick.contentHeight - logFlick.height)
        })
    }

    function refresh() {
        if (root.surfaceHost && root.surfaceHost.flowTuiStatus)
            root.applyRaw(root.surfaceHost.flowTuiStatus())
    }

    function submit() {
        var value = String(root.draft || "").trim()
        if (root.busy || !value.length || !root.surfaceHost || !root.surfaceHost.flowTuiSubmit)
            return
        root.applyRaw(root.surfaceHost.flowTuiSubmit(value))
        root.draft = ""
        input.text = ""
        Qt.callLater(function() { input.forceActiveFocus() })
    }

    function resetBoard() {
        if (root.busy)
            return
        if (root.surfaceHost && root.surfaceHost.flowTuiReset)
            root.applyRaw(root.surfaceHost.flowTuiReset())
        Qt.callLater(function() { input.forceActiveFocus() })
    }

    function speakerKind(row) {
        var role = String((row && row.role) || "").toUpperCase()
        if (role === "YOU")
            return "REQUEST"
        return "REPLY"
    }

    Connections {
        target: root.surfaceHost
        function onFlowTuiChanged(raw) { root.applyRaw(raw) }
    }

    Component.onCompleted: root.refresh()
    onVisibleChanged: {
        if (visible) {
            root.refresh()
            Qt.callLater(function() { input.forceActiveFocus() })
        }
    }

    Rectangle {
        anchors.fill: parent
        color: "#161616"
    }

    Flickable {
        id: logFlick
        objectName: "flowTuiLog"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: inputBar.top
        anchors.leftMargin: 8
        anchors.rightMargin: 8
        anchors.topMargin: 8
        anchors.bottomMargin: 6
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        contentWidth: width
        contentHeight: logCol.height
        ScrollBar.vertical: GgScrollBar {}

        Column {
            id: logCol
            width: logFlick.width
            spacing: 10

            Text {
                visible: root.transcript.length === 0
                width: parent.width
                text: "FLOW TUI · one task ledger · one motor works at a time.\nGROK TUI scopes and reviews; GPTUI owns the assigned work. Each handoff stays in this chat."
                color: "#8a8a8a"
                font.family: "monospace"
                font.pixelSize: 12
                wrapMode: Text.WordWrap
            }

            Text {
                visible: root.transcript.length > 0
                width: parent.width
                text: {
                    var work = (root.status.shared_memory || {}).work || {}
                    var merge = root.status.merge || {}
                    var completed = work.completed || []
                    var openItems = work.open || []
                    var owner = String(work.owner || "none")
                    return "SHARED LEDGER · " + String(merge.status || "")
                        + " · " + owner + " owns " + String(work.phase || "")
                        + " · DONE " + completed.length + " · OPEN " + openItems.length
                }
                color: root.busy ? "#8db89a" : "#8a8a8a"
                font.family: "monospace"
                font.pixelSize: 11
                wrapMode: Text.WordWrap
            }

            Repeater {
                model: root.transcript
                delegate: ChatNode {
                    required property var modelData
                    authorLabel: String(modelData.role || "FLOW")
                        + (modelData.stage ? " · " + String(modelData.stage) : "")
                    nodeKind: root.speakerKind(modelData)
                    bodyText: String(modelData.text || "")
                    maxBubbleWidth: Math.max(240, logCol.width - 8)
                }
            }
        }
    }

    Row {
        id: inputBar
        objectName: "flowTuiInputBar"
        z: 8
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: 8
        anchors.rightMargin: 8
        anchors.bottomMargin: 6
        spacing: 8
        height: 28

        GgField {
            id: input
            objectName: "flowTuiPrompt"
            width: Math.max(80, parent.width - 90)
            enabled: !root.busy
            placeholderText: root.busy ? "one owner is working…" : "give FLOW one shared task"
            text: root.draft
            onTextChanged: root.draft = text
            Keys.onReturnPressed: root.submit()
        }
        Text {
            text: "SEND"
            color: root.busy ? "#555555" : "#8db89a"
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: true
            anchors.verticalCenter: parent.verticalCenter
            MouseArea {
                anchors.fill: parent
                enabled: !root.busy
                cursorShape: Qt.PointingHandCursor
                onClicked: root.submit()
            }
        }
        Text {
            text: "RESET"
            color: root.busy ? "#555555" : "#c8a97e"
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: true
            anchors.verticalCenter: parent.verticalCenter
            MouseArea {
                anchors.fill: parent
                enabled: !root.busy
                cursorShape: Qt.PointingHandCursor
                onClicked: root.resetBoard()
            }
        }
    }
}
