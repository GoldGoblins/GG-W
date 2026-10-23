import QtQuick
import QtQuick.Controls
import QtQuick.Window

Item {
    id: root

    property string objectType: "CODE"
    property string title: "sample"
    property string bodyText: ""
    property string provenanceClass: "SYNTHETIC_UI_FIXTURE"
    property string activityState: "IDLE"
    property string activityPhase: ""
    property real realPercentage: -1
    property int elapsedSeconds: -1
    property string lastActivity: ""
    property string contextReference: ""
    property string terminalId: ""
    property bool grokTui: false
    property bool hideCommand: false
    property bool fillHost: false
    readonly property int bodyMaxHeight: root.fillHost ? 100000 : 168
    readonly property bool liveSurface:
        !root.syntheticFixture
        && (
            root.objectType === "CODE"
            || root.objectType === "TERMINAL"
        )
    readonly property var surfaceHost: {
        var win = Window.window
        if (win && win.surfaceHost)
            return win.surfaceHost
        return null
    }

    readonly property bool syntheticFixture:
        root.provenanceClass === "SYNTHETIC_UI_FIXTURE"

    implicitHeight: root.fillHost && parent
        ? parent.height
        : frame.implicitHeight
    implicitWidth: root.fillHost && parent
        ? parent.width
        : 760

    function stickBodyToEnd() {
        if (bodyFlick.contentHeight > bodyFlick.height)
            bodyFlick.contentY = bodyFlick.contentHeight - bodyFlick.height
        else
            bodyFlick.contentY = 0
    }

    function attachTerminal() {
        if (!root.liveSurface || root.objectType !== "TERMINAL")
            return
        if (root.surfaceHost === null)
            return
        if (root.terminalId.length === 0)
            return
        if (root.grokTui)
            root.surfaceHost.startGrokTui(root.terminalId)
        else
            root.surfaceHost.startChatTerminal(root.terminalId)
    }

    function sendTerminalLine() {
        var line = commandInput.text
        if (!root.liveSurface || root.objectType !== "TERMINAL")
            return
        if (root.surfaceHost === null)
            return
        if (root.terminalId.length === 0)
            return
        root.attachTerminal()
        if (!root.surfaceHost.writeChatTerminal(root.terminalId, line + "\n"))
            return
        commandInput.text = ""
    }

    onBodyTextChanged: {
        if (root.objectType !== "TERMINAL")
            return
        if (
            root.activityState === "RUNNING"
            || root.activityState === "STREAMING"
            || root.activityState === "STARTING"
        ) {
            if (bodyView.text !== root.bodyText)
                bodyView.text = root.bodyText
        }
    }

    Component.onCompleted: {
        if (!root.grokTui)
            root.attachTerminal()
        else
            Qt.callLater(root.attachTerminal)
    }
    onSurfaceHostChanged: root.attachTerminal()
    onTerminalIdChanged: root.attachTerminal()

    GgFrame {
        id: frame
        anchors.fill: root.fillHost ? parent : undefined
        width: root.fillHost ? undefined : root.width
        leftLegend: root.fillHost ? "" : (root.objectType + " · " + root.title)
        rightLegend: root.fillHost
            ? ""
            : (
                root.syntheticFixture
                    ? "DEMO · SAMPLE · NO EXECUTION"
                    : root.activityState
            )
        backgroundColor: "#1c1c1c"
        borderColor: root.fillHost ? "#1c1c1c" : "#6a6a6a"
        rightLegendColor: root.syntheticFixture ? "#d2b48c" : "#8b949e"

        Flickable {
            id: bodyFlick
            objectName: root.objectType === "TERMINAL"
                ? "terminalOutputScroll"
                : "workObjectBodyScroll"
            visible: !root.grokTui
            width: parent.width
            height: root.fillHost
                ? Math.max(
                    72,
                    // Leave one full status-line row plus bottom breathing
                    // room inside GgFrame's clipped content area.  Without
                    // this inset the input/status pair sits under the frame
                    // edge and the last line is visibly cut in half.
                    root.height - terminalInputRow.height - 56
                )
                : Math.min(
                    root.bodyMaxHeight,
                    Math.max(72, bodyView.implicitHeight)
                )
            contentWidth: width
            // TextArea does not always grow its implicit height while a
            // terminal is receiving PTY chunks.  Track the real document
            // height so output is readable, selectable and scrollable instead
            // of collapsing to the first prompt line.
            contentHeight: Math.max(
                bodyFlick.height,
                bodyView.contentHeight,
                bodyView.implicitHeight
            )
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            interactive: contentHeight > height
            flickableDirection: Flickable.VerticalFlick
            onContentHeightChanged: root.stickBodyToEnd()
            onHeightChanged: root.stickBodyToEnd()

            TextArea {
                id: bodyView
                objectName: root.objectType === "TERMINAL"
                    ? "terminalOutput"
                    : "workObjectBody"
                width: bodyFlick.width
                height: Math.max(
                    bodyFlick.height,
                    bodyView.contentHeight,
                    bodyView.implicitHeight
                )
                text: root.bodyText
                readOnly: !root.liveSurface || root.objectType === "TERMINAL"
                selectByMouse: true
                selectByKeyboard: true
                persistentSelection: true
                selectionColor: "#3a3a3a"
                selectedTextColor: "#f2f2f2"

                SelectionGuard {
                    editor: bodyView
                }
                color: root.objectType === "CODE" || root.objectType === "TERMINAL"
                    ? "#d8dee9" : "#e6edf3"
                font.family: "monospace"
                font.pixelSize: 12
                wrapMode: root.grokTui
                    ? TextEdit.NoWrap
                    : (
                        root.objectType === "CODE" || root.objectType === "TERMINAL"
                            ? TextEdit.WrapAnywhere : TextEdit.Wrap
                    )
                background: Rectangle {
                    color: "transparent"
                    border.width: 0
                }

                onTextChanged: {
                    if (
                        root.liveSurface
                        && root.objectType === "CODE"
                    )
                        root.bodyText = bodyView.text
                }
            }

            ScrollBar.vertical: GgScrollBar {
                keepVisible: root.objectType === "TERMINAL"
            }
        }

        Row {
            id: terminalInputRow
            objectName: "terminalInputRow"
            visible:
                root.liveSurface
                && root.objectType === "TERMINAL"
                && root.terminalId.length > 0
                && !root.hideCommand
            width: parent.width
            spacing: 6

            Text {
                text: "$"
                color: "#8a8a8a"
                font.family: "monospace"
                font.pixelSize: 12
                height: commandInput.height
                verticalAlignment: Text.AlignVCenter
            }

            GgField {
                id: commandInput
                objectName: "terminalCommandInput"
                width: parent.width - 18
                Keys.onReturnPressed: root.sendTerminalLine()
                Keys.onEnterPressed: root.sendTerminalLine()
            }
        }

        Connections {
            target: root.surfaceHost
            enabled: root.liveSurface && root.objectType === "TERMINAL"

            function onChatTerminalOutput(identity, chunk) {
                if (identity !== root.terminalId)
                    return
                if (root.grokTui)
                    bodyView.text = chunk
                else
                    bodyView.text += chunk
                root.bodyText = bodyView.text
                root.stickBodyToEnd()
            }
        }

        ActivityStrip {
            id: activityStrip
            visible: root.activityState === "RUNNING"
                || root.activityState === "STREAMING"
                || root.activityState === "STARTING"
                || root.activityState === "GENERATING"
                || root.activityState === "WAITING"
            width: parent.width
            activityState: root.activityState
            headline: root.activityPhase.length > 0
                ? root.activityPhase
                : (
                    root.objectType === "TERMINAL"
                        ? "Terminal"
                        : (
                            root.objectType === "CODE"
                                ? "Code"
                                : root.activityState
                        )
                )
            percentage: root.syntheticFixture ? -1 : root.realPercentage
            elapsedSeconds: root.elapsedSeconds
            lastActivity: root.lastActivity
        }

        Text {
            visible: root.syntheticFixture
            width: parent.width
            text: "fixture provenance: SYNTHETIC_UI_FIXTURE"
            color: "#7d7368"
            font.family: "monospace"
            font.pixelSize: 12
        }
    }
}
