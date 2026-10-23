import QtQuick
import QtQuick.Controls

Item {
    id: root
    objectName: "workspaceAgentFlowPane"

    property var surfaceHost: null
    property color frameBorder: "#6a6a6a"
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
            return root.light === "GO" ? "#8db89a" : (root.light === "HOLD" ? "#c98989" : "#c8a97e")
        if (kind === "REFLECT")
            return "#b6a6c8"
        if (kind === "BUILD")
            return "#8db89a"
        if (kind === "TOOLS")
            return "#8fa8a0"
        if (kind === "PLAN")
            return "#c8a97e"
        return "#c8cdd4"
    }

    Component.onCompleted: root.refresh()

    Rectangle {
        anchors.fill: parent
        color: "#161616"
    }

    Column {
        anchors.fill: parent
        anchors.leftMargin: 8
        anchors.rightMargin: 8
        anchors.topMargin: 6
        anchors.bottomMargin: 8
        spacing: 8

        Text {
            text: "FLOW  ·  FOUR PATTERNS, ONE GRAPH"
            color: "#d8dee9"
            font.family: "monospace"
            font.pixelSize: 16
        }
        Text {
            width: parent.width
            text: String(root.status.hint || "Planning, tools, build, reflect. Critic is not the author. No extra brain.")
            color: "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
            wrapMode: Text.WordWrap
        }

        Row {
            spacing: 10
            width: parent.width
            GgField {
                id: askField
                width: Math.max(120, parent.width - 140)
                text: root.askText
                onTextChanged: root.askText = text
                Keys.onReturnPressed: root.runFlow()
            }
            Text {
                text: "RUN"
                color: "#8db89a"
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
            Text {
                text: "RESET"
                color: "#c8a97e"
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
                    color: "#161616"
                    border.color: root.stageColor(modelData.id)
                    border.width: 1
                    radius: 3
                    Column {
                        anchors.fill: parent
                        anchors.margins: 6
                        spacing: 2
                        Text {
                            text: String(modelData.id || "")
                            color: root.stageColor(modelData.id)
                            font.family: "monospace"
                            font.pixelSize: 11
                            font.bold: true
                        }
                        Text {
                            text: String(modelData.role || "")
                            color: "#c8cdd4"
                            font.family: "monospace"
                            font.pixelSize: 10
                        }
                        Text {
                            text: "→ " + String(modelData.handoff_to || "")
                            color: "#7f8994"
                            font.family: "monospace"
                            font.pixelSize: 10
                        }
                    }
                }
            }
        }

        Text {
            text: "FRONT MAN  " + root.light
                + "  ·  critic≠dev  ·  brain=" + String(root.status.parallel_agent_brain || "FORBIDDEN")
                + "  ·  " + String(root.status.parallel_execution || "BOUNDED_ADAPTIVE_DAG")
                + "  ·  lanes=" + String((root.status.execution || {}).lanes || "—")
                + "  ·  loops=" + String((root.status.execution || {}).loops || root.status.loops || "—")
            color: root.light === "GO" ? "#8db89a" : (root.light === "HOLD" ? "#c98989" : "#c8a97e")
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
            ScrollBar.vertical: GgScrollBar {}

            Column {
                id: packCol
                width: parent.width
                spacing: 6
                Text {
                    visible: root.packets.length === 0
                    text: "Type a task and RUN. Packets will hand off ASK → PLAN → TOOLS → BUILD → REFLECT → GATE."
                    color: "#a8b0b8"
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
                        Text {
                            text: String(modelData.kind || "")
                                + "  " + String(modelData.from || "")
                                + " → " + String(modelData.to || "")
                            color: root.stageColor(modelData.kind)
                            font.family: "monospace"
                            font.pixelSize: 12
                            font.bold: true
                        }
                        Text {
                            width: packCol.width
                            text: String(modelData.body || "")
                            color: "#c8cdd4"
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
