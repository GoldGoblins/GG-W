
import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

Item {
    id: root
    objectName: "workspaceAgentFlowPane"

    property var surfaceHost: null
    property color frameBorder: RuntimeTheme.GGTheme.edge
    property int frameRadius: 4
    property string statusJson: "{}"
    property string askText: ""

    readonly property var status: {
        try {
            return JSON.parse(root.statusJson || "{}")
        } catch (err) {
            return {}
        }
    }
    readonly property var graph: root.status.graph || root.status
    readonly property var packets: root.graph.packets || root.status.packets || []
    readonly property var stages: root.graph.stages || root.status.stages || []
    readonly property var frontMan: root.graph.front_man || root.status.front_man || {}
    readonly property var gates: root.status.user_gates || []
    readonly property string light: String(root.frontMan.light || "HOLD")

    function applyRaw(raw) {
        if (raw === undefined || raw === null)
            return
        root.statusJson = String(raw)
    }

    function refresh() {
        if (root.surfaceHost && root.surfaceHost.flowTuiStatus)
            root.applyRaw(root.surfaceHost.flowTuiStatus())
        else if (root.surfaceHost && root.surfaceHost.agentFlowStatus)
            root.applyRaw(root.surfaceHost.agentFlowStatus())
    }

    function runFlow() {
        if (!root.surfaceHost)
            return
        if (root.surfaceHost.flowTuiSubmit) {
            root.applyRaw(root.surfaceHost.flowTuiSubmit(root.askText))
            return
        }
        if (root.surfaceHost.agentFlowRun)
            root.applyRaw(root.surfaceHost.agentFlowRun(root.askText))
    }

    function resetFlow() {
        if (root.surfaceHost && root.surfaceHost.agentFlowReset)
            root.applyRaw(root.surfaceHost.agentFlowReset())
    }

    function stageColor(id) {
        var kind = String(id || "")
        if (kind === "GATE")
            return root.light === "GO" ? RuntimeTheme.GGTheme.positive : (root.light === "HOLD" ? RuntimeTheme.GGTheme.negative : RuntimeTheme.GGTheme.accent)
        if (kind === "REFLECT")
            return RuntimeTheme.GGTheme.purple
        if (kind === "BUILD")
            return RuntimeTheme.GGTheme.positive
        if (kind === "TOOLS")
            return RuntimeTheme.GGTheme.cyan
        if (kind === "PLAN")
            return RuntimeTheme.GGTheme.accent
        return RuntimeTheme.GGTheme.text
    }

    Component.onCompleted: root.refresh()

    Rectangle {
        anchors.fill: parent
        color: RuntimeTheme.GGTheme.panel
    }

    Column {
        anchors.fill: parent
        anchors.leftMargin: 8
        anchors.rightMargin: 8
        anchors.topMargin: 6
        anchors.bottomMargin: 8
        spacing: 8

        GGText { colorKey: "ui.AgentFlowSurface.1";
            text: "FLOW  ·  FOUR PATTERNS, ONE GRAPH"
            color: RuntimeTheme.GGTheme.text
            font.family: "monospace"
            font.pixelSize: 16
        }
        GGText { colorKey: "ui.AgentFlowSurface.2";
            width: parent.width
            text: String(root.status.hint || "Planning, tools, build, reflect. Critic is not the author. No extra brain.")
            color: RuntimeTheme.GGTheme.muted
            font.family: "monospace"
            font.pixelSize: 12
            wrapMode: Text.WordWrap
        }

        Row {
            spacing: 10
            width: parent.width
            GgField { property string uiColorScope: "ui.widget.AgentFlowSurface.GgField.1";
                id: askField
                width: Math.max(120, parent.width - 140)
                text: root.askText
                onTextChanged: root.askText = text
                Keys.onReturnPressed: root.runFlow()
            }
            GGText { colorKey: "ui.AgentFlowSurface.3";
                text: "RUN"
                color: RuntimeTheme.GGTheme.positive
                font.family: "monospace"
                font.pixelSize: 12
                font.bold: true
                anchors.verticalCenter: parent.verticalCenter
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.runFlow()
                }
            }
            GGText { colorKey: "ui.AgentFlowSurface.4";
                text: "RESET"
                color: RuntimeTheme.GGTheme.accent
                font.family: "monospace"
                font.pixelSize: 12
                font.bold: true
                anchors.verticalCenter: parent.verticalCenter
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.resetFlow()
                }
            }
        }

        Row {
            id: graphRow
            spacing: 6
            width: parent.width
            Repeater {
                model: root.stages
                delegate: Rectangle {
                    required property var modelData
                    width: Math.max(72, (graphRow.width - 30) / 6)
                    height: 72
                    color: RuntimeTheme.GGTheme.panel
                    border.color: root.stageColor(modelData.id)
                    border.width: 1
                    radius: 3
                    Column {
                        anchors.fill: parent
                        anchors.margins: 6
                        spacing: 2
                        GGText { colorKey: "ui.AgentFlowSurface.5";
                            text: String(modelData.id || "")
                            color: root.stageColor(modelData.id)
                            font.family: "monospace"
                            font.pixelSize: 11
                            font.bold: true
                        }
                        GGText { colorKey: "ui.AgentFlowSurface.6";
                            text: String(modelData.role || "")
                            color: RuntimeTheme.GGTheme.text
                            font.family: "monospace"
                            font.pixelSize: 10
                        }
                        GGText { colorKey: "ui.AgentFlowSurface.7";
                            text: "→ " + String(modelData.handoff_to || "")
                            color: RuntimeTheme.GGTheme.dim
                            font.family: "monospace"
                            font.pixelSize: 10
                        }
                    }
                }
            }
        }

        GGText { colorKey: "ui.AgentFlowSurface.8";
            text: "FRONT MAN  " + root.light
                + "  ·  critic≠dev  ·  brain=" + String(root.status.parallel_agent_brain || "FORBIDDEN")
                + "  ·  " + String(root.status.parallel_execution || "BOUNDED_ADAPTIVE_DAG")
                + "  ·  lanes=" + String((root.status.execution || {}).lanes || "—")
                + "  ·  loops=" + String((root.status.execution || {}).loops || root.status.loops || "—")
            color: root.light === "GO" ? RuntimeTheme.GGTheme.positive : (root.light === "HOLD" ? RuntimeTheme.GGTheme.negative : RuntimeTheme.GGTheme.accent)
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: true
        }

        Flickable {
            width: parent.width
            height: Math.max(80, parent.height - 220)
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            contentHeight: packCol.height
            ScrollBar.vertical: GgScrollBar { property string uiColorScope: "ui.widget.AgentFlowSurface.GgScrollBar.2";}

            Column {
                id: packCol
                width: parent.width
                spacing: 6
                GGText { colorKey: "ui.AgentFlowSurface.9";
                    visible: root.packets.length === 0
                    text: "Type a task and RUN. Packets will hand off ASK → PLAN → TOOLS → BUILD → REFLECT → GATE."
                    color: RuntimeTheme.GGTheme.muted
                    font.family: "monospace"
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                    width: packCol.width
                }
                Repeater {
                    model: root.packets
                    delegate: Column {
                        required property var modelData
                        width: packCol.width
                        spacing: 2
                        GGText { colorKey: "ui.AgentFlowSurface.10";
                            text: String(modelData.kind || "")
                                + "  " + String(modelData.from || "")
                                + " → " + String(modelData.to || "")
                            color: root.stageColor(modelData.kind)
                            font.family: "monospace"
                            font.pixelSize: 12
                            font.bold: true
                        }
                        GGText { colorKey: "ui.AgentFlowSurface.11";
                            width: packCol.width
                            text: String(modelData.body || "")
                            color: RuntimeTheme.GGTheme.text
                            font.family: "monospace"
                            font.pixelSize: 11
                            wrapMode: Text.WordWrap
                        }
                    }
                }
            }
        }
    }
}
