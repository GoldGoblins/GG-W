pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls

Item {
    id: root
    objectName: "workspaceNodePane"

    property var surfaceHost: null
    property color frameBorder: "#6a6a6a"
    property int frameRadius: 4
    property string statusJson: "{}"
    property string pendingFromNode: ""
    property string pendingFromPort: ""
    property real pendingX: 0
    property real pendingY: 0
    property string dragNode: ""
    property real dragOffX: 0
    property real dragOffY: 0
    readonly property int blockW: 176
    readonly property int portPitch: 16
    readonly property int portTop: 36

    readonly property var status: {
        try {
            return JSON.parse(root.statusJson || "{}")
        } catch (err) {
            return {}
        }
    }
    readonly property var blocks: root.status.blocks || []
    readonly property var wires: root.status.wires || []
    readonly property var evalRow: root.status.eval || {}
    readonly property var values: root.evalRow.values || {}
    readonly property string legend: "FLOW · MACHINE GRAPH"

    function applyRaw(raw) {
        if (raw === undefined || raw === null)
            return
        root.statusJson = String(raw)
        wireCanvas.requestPaint()
    }

    function refresh() {
        if (root.surfaceHost && root.surfaceHost.nodeFlowStatus)
            root.applyRaw(root.surfaceHost.nodeFlowStatus())
    }

    function resetFlow() {
        if (root.surfaceHost && root.surfaceHost.nodeFlowReset)
            root.applyRaw(root.surfaceHost.nodeFlowReset())
    }

    function blockById(nodeId) {
        var rows = root.blocks
        for (var i = 0; i < rows.length; i++) {
            if (String((rows[i] || {}).node_id || "") === String(nodeId || ""))
                return rows[i]
        }
        return ({})
    }

    function portsOf(block, direction) {
        var ports = (block || {}).ports || []
        var out = []
        for (var i = 0; i < ports.length; i++) {
            if (String((ports[i] || {}).direction || "") === direction)
                out.push(ports[i])
        }
        return out
    }

    function portY(block, direction, portId) {
        var ports = root.portsOf(block, direction)
        for (var i = 0; i < ports.length; i++) {
            if (String((ports[i] || {}).port_id || "") === String(portId || ""))
                return Number(block.y || 0) + root.portTop + i * root.portPitch
        }
        return Number(block.y || 0) + root.portTop
    }

    function portX(block, direction) {
        var x = Number(block.x || 0)
        return direction === "OUTPUT" ? x + root.blockW : x
    }

    function blockHeight(block) {
        var ins = root.portsOf(block, "INPUT").length
        var outs = root.portsOf(block, "OUTPUT").length
        return Math.max(118, root.portTop + Math.max(ins, outs) * root.portPitch + 52)
    }

    function hitInput(px, py) {
        var rows = root.blocks
        for (var i = 0; i < rows.length; i++) {
            var block = rows[i] || {}
            var ports = root.portsOf(block, "INPUT")
            var x = Number(block.x || 0)
            for (var p = 0; p < ports.length; p++) {
                var y = Number(block.y || 0) + root.portTop + p * root.portPitch
                if (Math.abs(px - x) <= 10 && Math.abs(py - y) <= 10)
                    return {
                        "node": String(block.node_id || ""),
                        "port": String((ports[p] || {}).port_id || "")
                    }
            }
        }
        return null
    }

    function connectPending(px, py) {
        if (!root.pendingFromNode.length || !root.surfaceHost || !root.surfaceHost.nodeFlowConnect)
            return
        var hit = root.hitInput(px, py)
        if (hit && hit.node.length && hit.port.length)
            root.applyRaw(root.surfaceHost.nodeFlowConnect(
                root.pendingFromNode,
                root.pendingFromPort,
                hit.node,
                hit.port
            ))
        root.pendingFromNode = ""
        root.pendingFromPort = ""
        wireCanvas.requestPaint()
    }

    function dropWire(edgeId) {
        if (!root.surfaceHost || !root.surfaceHost.nodeFlowDisconnect)
            return
        root.applyRaw(root.surfaceHost.nodeFlowDisconnect(String(edgeId || "")))
    }

    function moveBlock(nodeId, x, y) {
        if (!root.surfaceHost || !root.surfaceHost.nodeFlowMove)
            return
        root.applyRaw(root.surfaceHost.nodeFlowMove(String(nodeId || ""), x, y))
    }

    function setParam(nodeId, key, value) {
        if (!root.surfaceHost || !root.surfaceHost.nodeFlowSetParam)
            return
        root.applyRaw(root.surfaceHost.nodeFlowSetParam(
            String(nodeId || ""),
            String(key || ""),
            Number(value)
        ))
    }

    Component.onCompleted: root.refresh()
    onVisibleChanged: if (root.visible)
        root.refresh()

    Rectangle {
        anchors.fill: parent
        color: "#101010"
        border.width: 1
        border.color: root.frameBorder
        radius: root.frameRadius
    }

    Text {
        anchors.left: parent.left
        anchors.leftMargin: 12
        anchors.top: parent.top
        anchors.topMargin: 8
        text: "NODES"
        color: "#d8dee9"
        font.family: "monospace"
        font.pixelSize: 12
        font.bold: true
        z: 8
    }

    Text {
        anchors.right: parent.right
        anchors.rightMargin: 12
        anchors.top: parent.top
        anchors.topMargin: 8
        text: "STREAM " + String(root.evalRow.stream || 0)
            + "  ·  CONTRAST " + String(root.evalRow.contrast || 0)
            + "  ·  RESET"
        color: "#c8a97e"
        font.family: "monospace"
        font.pixelSize: 12
        z: 8
        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: root.resetFlow()
        }
    }

    Flickable {
        id: board
        objectName: "nodeFlowBoard"
        anchors.fill: parent
        anchors.topMargin: 26
        anchors.margins: 8
        clip: true
        contentWidth: 1600
        contentHeight: 900
        boundsBehavior: Flickable.StopAtBounds

        Canvas {
            id: wireCanvas
            width: board.contentWidth
            height: board.contentHeight
            z: 1
            onPaint: {
                var ctx = getContext("2d")
                ctx.clearRect(0, 0, width, height)
                var rows = root.wires
                for (var i = 0; i < rows.length; i++) {
                    var wire = rows[i] || {}
                    if (wire.enabled === false)
                        continue
                    var src = root.blockById(wire.from_node_id)
                    var dst = root.blockById(wire.to_node_id)
                    if (!src.node_id || !dst.node_id)
                        continue
                    var x1 = root.portX(src, "OUTPUT")
                    var y1 = root.portY(src, "OUTPUT", wire.from_port_id)
                    var x2 = root.portX(dst, "INPUT")
                    var y2 = root.portY(dst, "INPUT", wire.to_port_id)
                    var mid = (x1 + x2) / 2
                    ctx.strokeStyle = "#c8a97e"
                    ctx.lineWidth = 1.5
                    ctx.beginPath()
                    ctx.moveTo(x1, y1)
                    ctx.bezierCurveTo(mid, y1, mid, y2, x2, y2)
                    ctx.stroke()
                }
                if (root.pendingFromNode.length) {
                    var pend = root.blockById(root.pendingFromNode)
                    if (pend.node_id) {
                        var px = root.portX(pend, "OUTPUT")
                        var py = root.portY(pend, "OUTPUT", root.pendingFromPort)
                        ctx.strokeStyle = "#8db89a"
                        ctx.beginPath()
                        ctx.moveTo(px, py)
                        ctx.lineTo(root.pendingX, root.pendingY)
                        ctx.stroke()
                    }
                }
            }
            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.RightButton
                onClicked: {
                    var rows = root.wires
                    for (var i = 0; i < rows.length; i++) {
                        var wire = rows[i] || {}
                        if (wire.enabled === false)
                            continue
                        var src = root.blockById(wire.from_node_id)
                        var dst = root.blockById(wire.to_node_id)
                        if (!src.node_id || !dst.node_id)
                            continue
                        var x1 = root.portX(src, "OUTPUT")
                        var y1 = root.portY(src, "OUTPUT", wire.from_port_id)
                        var x2 = root.portX(dst, "INPUT")
                        var y2 = root.portY(dst, "INPUT", wire.to_port_id)
                        var mx = (x1 + x2) / 2
                        var my = (y1 + y2) / 2
                        if (Math.abs(mouse.x - mx) < 24 && Math.abs(mouse.y - my) < 18) {
                            root.dropWire(wire.edge_id)
                            return
                        }
                    }
                }
            }
        }

        Repeater {
            model: root.blocks.length
            delegate: Rectangle {
                id: blockCard
                required property int index
                readonly property var block: root.blocks[index] || ({})
                readonly property var inPorts: root.portsOf(blockCard.block, "INPUT")
                readonly property var outPorts: root.portsOf(blockCard.block, "OUTPUT")
                x: Number(blockCard.block.x || 0)
                y: Number(blockCard.block.y || 0)
                width: root.blockW
                height: root.blockHeight(blockCard.block)
                z: 2
                color: "#181818"
                border.width: 1
                border.color: blockCard.block.enabled === false ? "#4c4c4c" : "#6a6a6a"
                radius: 2

                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: 10
                    anchors.top: parent.top
                    anchors.topMargin: 8
                    text: String(blockCard.block.node_id || "BLOCK")
                    color: "#d8dee9"
                    font.family: "monospace"
                    font.pixelSize: 12
                    font.bold: true
                }

                Text {
                    anchors.right: parent.right
                    anchors.rightMargin: 10
                    anchors.top: parent.top
                    anchors.topMargin: 8
                    text: String((root.values[blockCard.block.node_id] !== undefined)
                                 ? root.values[blockCard.block.node_id] : "—")
                    color: "#8db89a"
                    font.family: "monospace"
                    font.pixelSize: 12
                }

                MouseArea {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    height: 28
                    cursorShape: Qt.SizeAllCursor
                    onPressed: {
                        root.dragNode = String(blockCard.block.node_id || "")
                        root.dragOffX = mouse.x
                        root.dragOffY = mouse.y
                    }
                    onPositionChanged: {
                        if (!root.dragNode.length)
                            return
                        root.moveBlock(
                            root.dragNode,
                            blockCard.x + mouse.x - root.dragOffX,
                            blockCard.y + mouse.y - root.dragOffY
                        )
                    }
                    onReleased: root.dragNode = ""
                }

                Repeater {
                    model: blockCard.inPorts.length
                    delegate: Rectangle {
                        required property int index
                        width: 8
                        height: 8
                        radius: 4
                        x: -4
                        y: root.portTop + index * root.portPitch - 4
                        color: "#8db89a"
                        border.width: 1
                        border.color: "#101010"
                    }
                }

                Repeater {
                    model: blockCard.outPorts.length
                    delegate: Rectangle {
                        required property int index
                        width: 8
                        height: 8
                        radius: 4
                        x: blockCard.width - 4
                        y: root.portTop + index * root.portPitch - 4
                        color: "#c8a97e"
                        border.width: 1
                        border.color: "#101010"
                        MouseArea {
                            anchors.fill: parent
                            anchors.margins: -6
                            cursorShape: Qt.CrossCursor
                            onPressed: {
                                root.pendingFromNode = String(blockCard.block.node_id || "")
                                root.pendingFromPort = String((blockCard.outPorts[index] || {}).port_id || "")
                                root.pendingX = blockCard.x + blockCard.width
                                root.pendingY = blockCard.y + root.portTop + index * root.portPitch
                                wireCanvas.requestPaint()
                            }
                            onPositionChanged: {
                                root.pendingX = blockCard.x + blockCard.width + mouse.x
                                root.pendingY = blockCard.y + root.portTop + index * root.portPitch + mouse.y
                                wireCanvas.requestPaint()
                            }
                            onReleased: {
                                root.connectPending(
                                    blockCard.x + blockCard.width + mouse.x,
                                    blockCard.y + root.portTop + index * root.portPitch + mouse.y
                                )
                            }
                        }
                    }
                }

                Column {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.margins: 8
                    spacing: 2

                    GgSlider {
                        width: parent.width
                        from: 0
                        to: 2
                        value: Number((blockCard.block.params || {}).gain || 1)
                        onMoved: root.setParam(blockCard.block.node_id, "gain", value)
                    }
                    Text {
                        text: "GAIN " + Number((blockCard.block.params || {}).gain || 1).toFixed(2)
                        color: "#7f8993"
                        font.family: "monospace"
                        font.pixelSize: 10
                    }
                    GgSlider {
                        width: parent.width
                        from: 0
                        to: 1
                        value: Number((blockCard.block.params || {}).mix || 1)
                        onMoved: root.setParam(blockCard.block.node_id, "mix", value)
                    }
                    Text {
                        text: "MIX " + Number((blockCard.block.params || {}).mix || 1).toFixed(2)
                        color: "#7f8993"
                        font.family: "monospace"
                        font.pixelSize: 10
                    }
                }
            }
        }
    }

    Text {
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.margins: 10
        width: parent.width - 20
        text: "Drag a gold output to a green input. Right-click a wire midpoint to cut it. "
            + "GAIN/MIX retune the stream. Same machine-graph as the workbench, not a second brain."
        color: "#7f8993"
        font.family: "monospace"
        font.pixelSize: 11
        wrapMode: Text.WordWrap
        z: 8
    }
}
