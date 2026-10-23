pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls

Item {
    id: root

    signal submitRequested(
        string text,
        string contextReference,
        string workspaceObjectId
    )
    signal stopRequested()
    signal assignmentSetRequested(
        string participant,
        string creatorActor
    )
    signal assignmentClearRequested()
    signal engineTargetRequested(string value)

    property string contextReference: "@current"
    property string workspaceObjectId: ""
    property string workspaceObjectTitle: ""
    property string bridgeState: "NOT CONNECTED"
    property bool busy: false
    property string activeTaskId: ""
    property bool assignmentExpanded: false
    property string engineTarget: "GROK_TUI"
    property color frameBorder: "#6a6a6a"
    property int frameRadius: 4
    property bool showOpenTab: false
    property var surfaceHost: null
    property bool diskLampOn: false
    property bool netLampOn: false
    property bool cpuLampOn: false
    property bool gpuLampOn: false
    property bool chatLampOn: false
    property bool gpuLampPresent: false
    property int diskLampTick: 0
    readonly property bool nativeTuiTarget:
        root.engineTarget === "GROK_TUI"
        || root.engineTarget === "GPT_TUI"
        || root.engineTarget === "FLOW_TUI"

    function lampBlink(active, phase) {
        return active && ((root.diskLampTick + phase) % 6) < 3
    }

    // implicitHeight: root.engineTarget === "GROK_TUI" (legacy contract marker)
    implicitHeight: (root.engineTarget === "GROK_TUI" || root.engineTarget === "GPT_TUI" || root.engineTarget === "FLOW_TUI")
        ? 28
        : (root.assignmentExpanded ? 166 : 102)
    implicitWidth: 720

    function submit() {
        var value = input.text.trim()
        if (value.length === 0)
            return
        var wasBusy = root.busy
        root.submitRequested(
            value,
            root.contextReference,
            root.workspaceObjectId
        )
        if (
            !wasBusy
            || root.engineTarget === "GROK_WORKER"
            || root.engineTarget === "GROK_TUI"
        )
            input.text = ""
    }

    readonly property bool canSend: input.text.trim().length > 0
    readonly property string engineLabel: root.engineTarget === "FLOW_TUI" ? "FLOW TUI" :
        root.engineTarget === "GPT_TUI" ? "GPTUI" :
        root.engineTarget === "GROK_TUI"
            ? "GROK TUI"
            : (
                root.engineTarget === "GROK_WORKER"
                    ? "GROK WORKER"
                    : "LOCAL QWEN"
            )

    GgFrame {
        id: inputFrame
        visible: !root.nativeTuiTarget
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: engineFooter.top
        anchors.bottomMargin: 18
        leftLegend: root.showOpenTab
            && root.workspaceObjectTitle.length > 0
                ? "INPUT · " + root.workspaceObjectTitle
                : "INPUT"
        rightLegend: root.busy
            ? root.engineLabel + " · RUNNING " + root.activeTaskId
            : root.engineLabel + " · BRIDGE " + root.bridgeState
        bottomLeftLegend: ""
        bottomRightLegend: ""
        backgroundColor: "#161616"
        borderColor: root.frameBorder
        radius: root.frameRadius

        Column {
            width: parent.width
            spacing: 6

            Row {
                width: parent.width
                height: visible ? 28 : 0
                spacing: 8
                visible: root.assignmentExpanded

                ComboBox {
                    id: participantSelector
                    objectName: "orchestratorParticipantSelector"
                    width: 240
                    height: 28
                    currentIndex: -1
                    model: [
                        "GG-AI-installator",
                        "GG-Agentarkitekt-agentskapare",
                        "GG-Content-Studio",
                        "GG-Marknadsföring",
                        "GG-Metaarkitekt-gptskapare",
                        "GG-Webmaster",
                        "GG-idekompassen"
                    ]
                    displayText: currentIndex >= 0
                        ? currentText
                        : "Explicit participant…"
                    font.family: "monospace"
                    font.pixelSize: 12
                    background: Rectangle {
                        implicitWidth: 240
                        implicitHeight: 28
                        color: "#121212"
                        border.width: 1
                        border.color: participantSelector.activeFocus
                            ? "#8a8a8a"
                            : "#6a6a6a"
                        radius: 2
                        antialiasing: false
                    }
                    contentItem: Text {
                        leftPadding: 8
                        rightPadding: 18
                        text: participantSelector.displayText
                        color: participantSelector.currentIndex >= 0
                            ? "#e6e6e6"
                            : "#8a8a8a"
                        font.family: "monospace"
                        font.pixelSize: 12
                        verticalAlignment: Text.AlignVCenter
                        elide: Text.ElideRight
                    }
                    indicator: Text {
                        x: participantSelector.width - 16
                        y: (participantSelector.height - implicitHeight) / 2
                        text: "v"
                        color: "#8a8a8a"
                        font.family: "monospace"
                        font.pixelSize: 10
                    }
                    delegate: ItemDelegate {
                        id: optionDelegate
                        required property int index
                        required property var modelData
                        width: participantSelector.width
                        height: 26
                        highlighted: participantSelector.highlightedIndex === index
                        contentItem: Text {
                            text: String(optionDelegate.modelData)
                            color: optionDelegate.highlighted
                                ? "#e6e6e6"
                                : "#c8cdd4"
                            font.family: "monospace"
                            font.pixelSize: 12
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                        }
                        background: Rectangle {
                            color: optionDelegate.highlighted
                                ? "#2a2a2a"
                                : "#161616"
                        }
                    }
                    popup: Popup {
                        y: participantSelector.height + 2
                        width: participantSelector.width
                        padding: 1
                        background: Rectangle {
                            color: "#161616"
                            border.color: "#6a6a6a"
                            border.width: 1
                        }
                        contentItem: ListView {
                            clip: true
                            implicitHeight: contentHeight
                            model: participantSelector.popup.visible
                                ? participantSelector.delegateModel
                                : null
                            currentIndex: participantSelector.highlightedIndex
                            ScrollBar.vertical: GgScrollBar {}
                        }
                    }
                }

                TextField {
                    id: creatorActorInput
                    objectName: "orchestratorCreatorActorInput"
                    width: parent.width
                        - participantSelector.width
                        - assignmentButton.width
                        - clearAssignmentButton.width
                        - 24
                    height: 28
                    placeholderText: "Explicit creator actor"
                    placeholderTextColor: "#5d6670"
                    color: "#e6e6e6"
                    font.family: "monospace"
                    font.pixelSize: 12
                    selectByMouse: true
                    leftPadding: 8
                    rightPadding: 8
                    background: Rectangle {
                        color: "#121212"
                        border.width: 1
                        border.color: creatorActorInput.activeFocus
                            ? "#8a8a8a"
                            : "#6a6a6a"
                        radius: 2
                        antialiasing: false
                    }
                }

                Text {
                    id: assignmentButton
                    objectName: "orchestratorAssignmentSetButton"
                    text: "Assign"
                    height: 28
                    verticalAlignment: Text.AlignVCenter
                    color: participantSelector.currentIndex >= 0
                        && creatorActorInput.text.trim().length > 0
                        ? "#d8dee9"
                        : "#5d6670"
                    font.family: "monospace"
                    font.pixelSize: 12
                    font.bold: participantSelector.currentIndex >= 0
                        && creatorActorInput.text.trim().length > 0

                    MouseArea {
                        anchors.fill: parent
                        enabled: participantSelector.currentIndex >= 0
                            && creatorActorInput.text.trim().length > 0
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.assignmentSetRequested(
                            participantSelector.currentText,
                            creatorActorInput.text.trim()
                        )
                    }
                }

                Text {
                    id: clearAssignmentButton
                    objectName: "orchestratorAssignmentClearButton"
                    text: "Clear"
                    height: 28
                    verticalAlignment: Text.AlignVCenter
                    color: "#d8dee9"
                    font.family: "monospace"
                    font.pixelSize: 12
                    font.bold: true

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            participantSelector.currentIndex = -1
                            creatorActorInput.text = ""
                            root.assignmentClearRequested()
                        }
                    }
                }
            }

            Row {
                width: parent.width
                spacing: 8

                Text {
                    text: ">"
                    color: "#c8cdd4"
                    font.family: "monospace"
                    font.pixelSize: 13
                    verticalAlignment: Text.AlignVCenter
                    height: 22
                }

                TextArea {
                    id: input
                    width: parent.width - 18
                    height: 22
                    // The native TUI owns the keyboard while GPT/Grok TUI is
                    // selected.  Leaving this hidden editor focusable lets
                    // it reclaim focus after the first PTY response.
                    enabled: !root.nativeTuiTarget
                    focus: !root.nativeTuiTarget
                    placeholderText: ""
                    color: "#e6edf3"
                    wrapMode: TextEdit.NoWrap
                    selectByMouse: true
                    font.family: "monospace"
                    font.pixelSize: 13
                    leftPadding: 0
                    rightPadding: 0
                    topPadding: 2
                    bottomPadding: 0

                    background: Rectangle {
                        color: "transparent"
                        border.width: 0
                    }

                    Keys.onPressed: function(event) {
                        if (
                            (
                                event.key === Qt.Key_Return
                                || event.key === Qt.Key_Enter
                            )
                            && !(event.modifiers & Qt.ShiftModifier)
                        ) {
                            root.submit()
                            event.accepted = true
                        }
                    }
                }
            }
        }
    }

    Rectangle {
        z: 5
        anchors.left: peopleRow.left
        anchors.leftMargin: -6
        anchors.bottom: peopleRow.bottom
        width: peopleRow.width + 12
        height: 20
        color: "#161616"
        visible: peopleRow.width > 0 && !root.nativeTuiTarget
    }

    Row {
        id: peopleRow
        z: 6
        anchors.left: inputFrame.left
        anchors.leftMargin: 14
        anchors.bottom: inputFrame.bottom
        anchors.bottomMargin: -8
        height: 20
        spacing: 0
        visible: !root.nativeTuiTarget
        Text {
            id: assignmentOptionsButton
            objectName: "orchestratorAssignmentOptionsButton"
            text: root.assignmentExpanded
                ? "People · close"
                : "People"
            color: "#d8dee9"
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: true

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked:
                    root.assignmentExpanded = !root.assignmentExpanded
            }
        }
    }

    Rectangle {
        z: 5
        anchors.left: sendRow.left
        anchors.leftMargin: -6
        anchors.bottom: sendRow.bottom
        width: sendRow.width + 12
        height: 20
        color: "#161616"
        visible: sendRow.width > 0 && !root.nativeTuiTarget
    }

    Row {
        id: sendRow
        z: 6
        anchors.right: inputFrame.right
        anchors.rightMargin: 14
        anchors.bottom: inputFrame.bottom
        anchors.bottomMargin: -8
        height: 20
        spacing: 0
        visible: !root.nativeTuiTarget
        Text {
            id: sendButton
            text: "Send"
            visible: !root.busy
            color: root.canSend ? "#d8dee9" : "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: root.canSend

            MouseArea {
                anchors.fill: parent
                enabled: root.canSend
                cursorShape: root.canSend
                    ? Qt.PointingHandCursor
                    : Qt.ArrowCursor
                onClicked: root.submit()
            }
        }

        BufferMark {
            objectName: "composerBuffer"
            anchors.verticalCenter: parent.verticalCenter
            active: root.busy
            cell: 5
        }

        Text {
            id: stopButton
            text: "Stop"
            visible: root.busy
            enabled: root.busy
            color: root.busy ? "#d8dee9" : "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: root.busy

            MouseArea {
                anchors.fill: parent
                enabled: root.busy
                cursorShape: Qt.PointingHandCursor
                onClicked: root.stopRequested()
            }
        }
    }

    Row {
        id: engineFooter
        objectName: "engineTargetSelector"
        z: 6
        anchors.left: parent.left
        anchors.leftMargin: 14
        anchors.verticalCenter: chatLampRail.verticalCenter
        height: 18
        spacing: 0

        Text {
            id: qwenEngineTarget
            text: "QWEN"
            color: root.engineTarget === "LOCAL_QWEN"
                ? "#d8dee9"
                : "#5d6670"
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: root.engineTarget === "LOCAL_QWEN"

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.engineTargetRequested("LOCAL_QWEN")
            }
        }

        Text {
            text: " | "
            color: "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
        }

        Text {
            id: grokEngineTarget
            text: "GROK"
            color: root.engineTarget === "GROK_WORKER"
                ? "#d8dee9"
                : "#5d6670"
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: root.engineTarget === "GROK_WORKER"

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.engineTargetRequested("GROK_WORKER")
            }
        }

        Text {
            text: " | "
            color: "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
        }

        Text {
            id: grokTuiEngineTarget
            text: "GROK TUI"
            color: root.engineTarget === "GROK_TUI"
                ? "#d8dee9"
                : "#5d6670"
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: root.engineTarget === "GROK_TUI"

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.engineTargetRequested("GROK_TUI")
            }
        }
        Text {
            text: " | "
            color: "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
        }
        Text {
            id: gptTuiEngineTarget
            text: "GPTUI"
            color: root.engineTarget === "GPT_TUI"
                ? "#d8dee9"
                : "#5d6670"
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: root.engineTarget === "GPT_TUI"

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.engineTargetRequested("GPT_TUI")
            }
        }
        Text {
            text: " | "
            color: "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
        }
        Text {
            id: flowTuiEngineTarget
            text: "FLOW TUI"
            color: root.engineTarget === "FLOW_TUI"
                ? "#d8dee9"
                : "#5d6670"
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: root.engineTarget === "FLOW_TUI"

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.engineTargetRequested("FLOW_TUI")
            }
        }
    }

    Row {
        id: chatLampRail
        objectName: "chatLampRail"
        anchors.right: parent.right
        anchors.rightMargin: 14
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 10
        spacing: 6

        Rectangle {
            width: 8
            height: 8
            radius: 4
            color: root.cpuLampOn ? "#8db89a" : "#2a1515"
            MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                ToolTip.visible: containsMouse
                ToolTip.delay: 400
                ToolTip.text: "CPU"
            }
        }
        Rectangle {
            visible: root.gpuLampPresent
            width: 8
            height: 8
            radius: 4
            color: root.gpuLampOn ? "#b6a6c8" : "#2a1515"
            MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                ToolTip.visible: containsMouse
                ToolTip.delay: 400
                ToolTip.text: "GPU"
            }
        }
        Rectangle {
            width: 8
            height: 8
            radius: 4
            color: root.netLampOn ? "#c8a97e" : "#2a1515"
            MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                ToolTip.visible: containsMouse
                ToolTip.delay: 400
                ToolTip.text: "NET"
            }
        }
        Rectangle {
            objectName: "chatDiskLamp"
            width: 8
            height: 8
            radius: 4
            color: root.diskLampOn ? "#e05050" : "#2a1515"
            MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                ToolTip.visible: containsMouse
                ToolTip.delay: 400
                ToolTip.text: "DISK"
            }
        }
        Rectangle {
            width: 8
            height: 8
            radius: 4
            color: root.chatLampOn ? "#d8dee9" : "#2a1515"
            MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                ToolTip.visible: containsMouse
                ToolTip.delay: 400
                ToolTip.text: "CHAT"
            }
        }
    }

    Timer {
        interval: 16
        running: root.visible && root.surfaceHost
        repeat: true
        onTriggered: {
            if (!root.surfaceHost || !root.surfaceHost.tmogPulse)
                return
            try {
                var p = JSON.parse(root.surfaceHost.tmogPulse() || "{}")
                var diskIo = Number(p.disk_read_bps || 0) + Number(p.disk_write_bps || 0)
                var netIo = Number(p.net_rx_bps || 0) + Number(p.net_tx_bps || 0)
                var cpu = Number(p.cpu_busy || 0)
                var gpu = p.gpu_busy
                root.gpuLampPresent = gpu !== undefined && gpu !== null
                root.diskLampTick += 1
                root.cpuLampOn = root.lampBlink(cpu >= 12, 4)
                root.gpuLampOn = root.lampBlink(
                    root.gpuLampPresent && Number(gpu) >= 5,
                    1
                )
                root.netLampOn = root.lampBlink(netIo >= 1024, 2)
                root.diskLampOn = root.lampBlink(diskIo >= 1024, 0)
                var tui = false
                if (root.surfaceHost.chatIoActive)
                    tui = root.surfaceHost.chatIoActive()
                root.chatLampOn = root.lampBlink(root.busy || tui, 3)
            } catch (err) {
                root.cpuLampOn = false
                root.gpuLampOn = false
                root.netLampOn = false
                root.diskLampOn = false
                root.chatLampOn = false
            }
        }
    }
}
