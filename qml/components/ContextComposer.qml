pragma ComponentBehavior: Bound


import "." as RuntimeTheme
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
    property color frameBorder: RuntimeTheme.GGTheme.edge
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

    function setDraft(value) {
        input.text = String(value || "")
        input.forceActiveFocus()
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

    GgFrame { property string uiColorScope: "ui.widget.ContextComposer.GgFrame.1";
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
        bottomGaps: {
            var gaps = []
            if (peopleRow.visible && peopleRow.width > 0)
                gaps.push({start: peopleRow.x - inputFrame.x - 6,
                           end: peopleRow.x - inputFrame.x + peopleRow.width + 6})
            if (sendRow.visible && sendRow.width > 0)
                gaps.push({start: sendRow.x - inputFrame.x - 6,
                           end: sendRow.x - inputFrame.x + sendRow.width + 6})
            return gaps
        }
        backgroundColor: RuntimeTheme.GGTheme.panel
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

                ComboBox { property string uiColorScope: "ui.control.ContextComposer.1";
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
                        color: RuntimeTheme.GGTheme.canvas
                        border.width: 1
                        border.color: participantSelector.activeFocus
                            ? RuntimeTheme.GGTheme.dim
                            : RuntimeTheme.GGTheme.edge
                        radius: 2
                        antialiasing: false
                    }
                    contentItem: GGText { colorKey: "ui.ContextComposer.1";
                        leftPadding: 8
                        rightPadding: 18
                        text: participantSelector.displayText
                        color: participantSelector.currentIndex >= 0
                            ? RuntimeTheme.GGTheme.bright
                            : RuntimeTheme.GGTheme.dim
                        font.family: "monospace"
                        font.pixelSize: 12
                        verticalAlignment: Text.AlignVCenter
                        elide: Text.ElideRight
                    }
                    indicator: GGText { colorKey: "ui.ContextComposer.2";
                        x: participantSelector.width - 16
                        y: (participantSelector.height - implicitHeight) / 2
                        text: "v"
                        color: RuntimeTheme.GGTheme.dim
                        font.family: "monospace"
                        font.pixelSize: 10
                    }
                    delegate: ItemDelegate { property string uiColorScope: "ui.control.ContextComposer.2";
                        id: optionDelegate
                        required property int index
                        required property var modelData
                        width: participantSelector.width
                        height: 26
                        highlighted: participantSelector.highlightedIndex === index
                        contentItem: GGText { colorKey: "ui.ContextComposer.3";
                            text: String(optionDelegate.modelData)
                            color: optionDelegate.highlighted
                                ? RuntimeTheme.GGTheme.bright
                                : RuntimeTheme.GGTheme.text
                            font.family: "monospace"
                            font.pixelSize: 12
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                        }
                        background: Rectangle {
                            color: optionDelegate.highlighted
                                ? RuntimeTheme.GGTheme.hover
                                : RuntimeTheme.GGTheme.panel
                        }
                    }
                    popup: Popup {
                        y: participantSelector.height + 2
                        width: participantSelector.width
                        padding: 1
                        background: Rectangle {
                            color: RuntimeTheme.GGTheme.panel
                            border.color: RuntimeTheme.GGTheme.edge
                            border.width: 1
                        }
                        contentItem: ListView {
                            clip: true
                            implicitHeight: contentHeight
                            model: participantSelector.popup.visible
                                ? participantSelector.delegateModel
                                : null
                            currentIndex: participantSelector.highlightedIndex
                            ScrollBar.vertical: GgScrollBar { property string uiColorScope: "ui.widget.ContextComposer.GgScrollBar.2";}
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
                    placeholderTextColor: RuntimeTheme.GGTheme.dim
                    color: RuntimeTheme.GGTheme.bright
                    font.family: "monospace"
                    font.pixelSize: 12
                    selectByMouse: true
                    leftPadding: 8
                    rightPadding: 8
                    background: Rectangle {
                        color: RuntimeTheme.GGTheme.canvas
                        border.width: 1
                        border.color: creatorActorInput.activeFocus
                            ? RuntimeTheme.GGTheme.dim
                            : RuntimeTheme.GGTheme.edge
                        radius: 2
                        antialiasing: false
                    }
                }

                GGText { colorKey: "ui.ContextComposer.4";
                    id: assignmentButton
                    objectName: "orchestratorAssignmentSetButton"
                    text: "Assign"
                    height: 28
                    verticalAlignment: Text.AlignVCenter
                    color: participantSelector.currentIndex >= 0
                        && creatorActorInput.text.trim().length > 0
                        ? RuntimeTheme.GGTheme.text
                        : RuntimeTheme.GGTheme.dim
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

                GGText { colorKey: "ui.ContextComposer.5";
                    id: clearAssignmentButton
                    objectName: "orchestratorAssignmentClearButton"
                    text: "Clear"
                    height: 28
                    verticalAlignment: Text.AlignVCenter
                    color: RuntimeTheme.GGTheme.text
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

                GGText { colorKey: "ui.ContextComposer.6";
                    text: ">"
                    color: RuntimeTheme.GGTheme.text
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
                    color: RuntimeTheme.GGTheme.bright
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
        GGText { colorKey: "ui.ContextComposer.7";
            id: assignmentOptionsButton
            objectName: "orchestratorAssignmentOptionsButton"
            text: root.assignmentExpanded
                ? "People · close"
                : "People"
            color: RuntimeTheme.GGTheme.text
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
        GGText { colorKey: "ui.ContextComposer.8";
            id: sendButton
            text: "Send"
            visible: !root.busy
            color: root.canSend ? RuntimeTheme.GGTheme.text : RuntimeTheme.GGTheme.muted
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

        BufferMark { property string uiColorScope: "ui.widget.ContextComposer.BufferMark.3";
            objectName: "composerBuffer"
            anchors.verticalCenter: parent.verticalCenter
            active: root.busy
            cell: 5
        }

        GGText { colorKey: "ui.ContextComposer.9";
            id: stopButton
            text: "Stop"
            visible: root.busy
            enabled: root.busy
            color: root.busy ? RuntimeTheme.GGTheme.text : RuntimeTheme.GGTheme.muted
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

        GGText { colorKey: "ui.ContextComposer.10";
            id: grokTuiEngineTarget
            text: "GROK TUI"
            color: root.engineTarget === "GROK_TUI"
                ? RuntimeTheme.GGTheme.text
                : RuntimeTheme.GGTheme.dim
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: root.engineTarget === "GROK_TUI"

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.engineTargetRequested("GROK_TUI")
            }
        }
        GGText { colorKey: "ui.ContextComposer.11";
            text: " | "
            color: RuntimeTheme.GGTheme.muted
            font.family: "monospace"
            font.pixelSize: 12
        }
        GGText { colorKey: "ui.ContextComposer.12";
            id: gptTuiEngineTarget
            text: "GPTUI"
            color: root.engineTarget === "GPT_TUI"
                ? RuntimeTheme.GGTheme.text
                : RuntimeTheme.GGTheme.dim
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: root.engineTarget === "GPT_TUI"

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.engineTargetRequested("GPT_TUI")
            }
        }
        GGText { colorKey: "ui.ContextComposer.13";
            text: " | "
            color: RuntimeTheme.GGTheme.muted
            font.family: "monospace"
            font.pixelSize: 12
        }
        GGText { colorKey: "ui.ContextComposer.14";
            id: flowTuiEngineTarget
            text: "FLOW TUI"
            color: root.engineTarget === "FLOW_TUI"
                ? RuntimeTheme.GGTheme.text
                : RuntimeTheme.GGTheme.dim
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

        Rectangle { GGColorTarget { colorKey: "ui.fill.ContextComposer.1"; colorActive:root.cpuLampOn;fallbackColor:RuntimeTheme.GGTheme.positive }
            objectName: "chatCpuLamp"
            width: 8
            height: 8
            radius: 4
            color: root.cpuLampOn ? RuntimeTheme.GGTheme.positive : "#2a1515"
            MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                ToolTip.visible: containsMouse
                ToolTip.delay: 400
                ToolTip.text: "CPU"
            }
        }
        Rectangle { GGColorTarget { colorKey: "ui.fill.ContextComposer.2"; colorActive:root.gpuLampOn;fallbackColor:RuntimeTheme.GGTheme.purple }
            objectName: "chatGpuLamp"
            visible: root.gpuLampPresent
            width: 8
            height: 8
            radius: 4
            color: root.gpuLampOn ? RuntimeTheme.GGTheme.purple : "#2a1515"
            MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                ToolTip.visible: containsMouse
                ToolTip.delay: 400
                ToolTip.text: "GPU"
            }
        }
        Rectangle { GGColorTarget { colorKey: "ui.fill.ContextComposer.3"; colorActive:root.netLampOn;fallbackColor:RuntimeTheme.GGTheme.accent }
            objectName: "chatNetworkLamp"
            width: 8
            height: 8
            radius: 4
            color: root.netLampOn ? RuntimeTheme.GGTheme.accent : "#2a1515"
            MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                ToolTip.visible: containsMouse
                ToolTip.delay: 400
                ToolTip.text: "NET"
            }
        }
        Rectangle { GGColorTarget { colorKey: "ui.fill.ContextComposer.4"; colorActive:root.diskLampOn;fallbackColor:RuntimeTheme.GGTheme.negative }
            objectName: "chatDiskLamp"
            width: 8
            height: 8
            radius: 4
            color: root.diskLampOn ? RuntimeTheme.GGTheme.negative : "#2a1515"
            MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                ToolTip.visible: containsMouse
                ToolTip.delay: 400
                ToolTip.text: "DISK"
            }
        }
        Rectangle {
            GGColorTarget {colorKey:"ui.activity.stream";colorActive:root.chatLampOn;fallbackColor:RuntimeTheme.GGTheme.text}
            objectName: "chatActivityLamp"
            width: 8
            height: 8
            radius: 4
            color: root.chatLampOn ? RuntimeTheme.GGTheme.text : "#2a1515"
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
        objectName: "chatActivityLampTimer"
        interval: 16
        running: root.visible && root.surfaceHost
        repeat: true
        onTriggered: {
            if (!root.surfaceHost || !root.surfaceHost.tmogPulse)
                return
            root.diskLampTick += 1
            var tui = false
            try {
                if (root.surfaceHost.chatIoActive)
                    tui = root.surfaceHost.chatIoActive()
            } catch (err) {}
            root.chatLampOn = root.lampBlink(root.busy || tui, 3)
            try {
                var p = JSON.parse(root.surfaceHost.tmogPulse() || "{}")
                if (p.pending || p.error) {
                    root.cpuLampOn = false
                    root.gpuLampOn = false
                    root.netLampOn = false
                    root.diskLampOn = false
                    return
                }
                var errors = p.sample_errors || {}
                var ioFresh = !errors.io
                var diskIo = ioFresh ? Number(p.disk_read_bps || 0) + Number(p.disk_write_bps || 0) : 0
                var netIo = ioFresh ? Number(p.net_rx_bps || 0) + Number(p.net_tx_bps || 0) : 0
                var cpuFresh = p.cpu_pending !== true && !errors.cpu
                    && (p.cpu_sample_age_ms === undefined || Number(p.cpu_sample_age_ms) <= 1000)
                var cpu = cpuFresh ? Number(p.cpu_busy) : NaN
                var gpu = p.gpu_busy
                root.gpuLampPresent = gpu !== undefined && gpu !== null
                root.cpuLampOn = root.lampBlink(cpu >= 12, 4)
                root.gpuLampOn = root.lampBlink(
                    root.gpuLampPresent && Number(gpu) >= 5,
                    1
                )
                root.netLampOn = root.lampBlink(netIo >= 1024, 2)
                root.diskLampOn = root.lampBlink(diskIo >= 1024, 0)
            } catch (err) {
                root.cpuLampOn = false
                root.gpuLampOn = false
                root.netLampOn = false
                root.diskLampOn = false
            }
        }
    }
}
