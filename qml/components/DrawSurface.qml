pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs

Item {
    id: root
    objectName: "workspaceDrawPane"

    property var surfaceHost: null
    property string statusJson: "{}"
    property string editorId: "sketch"
    property color frameBorder: "#6a6a6a"
    property int frameRadius: 4
    property int docW: 1280
    property int docH: 720
    property string tool: "brush"
    property color paintColor: "#e6e6e6"
    property int brushSize: 8
    property real zoom: 0.55
    property int layerIndex: 0
    property bool strokeOn: false
    property real lastX: 0
    property real lastY: 0
    property real startX: 0
    property real startY: 0
    property var undoStack: []
    property var redoStack: []
    property string statusLine: "1280 × 720"
    property string pendingImage: ""

    readonly property var status: {
        try {
            return JSON.parse(root.statusJson || "{}")
        } catch (err) {
            return {}
        }
    }
    readonly property var editors: {
        var rows = root.status.editors
        if (rows && rows.length !== undefined)
            return rows
        return []
    }
    readonly property bool sketchMode: root.editorId === "sketch"

    function refresh() {
        if (!root.surfaceHost || !root.surfaceHost.drawStatus)
            return
        root.statusJson = root.surfaceHost.drawStatus()
        if (root.editorId !== "sketch")
            return
        var chosen = String(root.status.default || "sketch")
        if (chosen && chosen !== "sketch")
            root.editorId = chosen
    }

    function openEditor(id) {
        root.editorId = id
        if (id === "sketch") {
            root.hideEmbed()
            return
        }
        if (!root.surfaceHost || !root.surfaceHost.drawStart)
            return
        root.surfaceHost.drawStart(id)
        root.refresh()
    }

    function hideEmbed() {
        if (root.surfaceHost && root.surfaceHost.hideDraw)
            root.surfaceHost.hideDraw()
    }

    onVisibleChanged: {
        if (visible) {
            root.refresh()
            if (!root.sketchMode)
                root.openEditor(root.editorId)
        } else {
            root.hideEmbed()
        }
    }

    Component.onCompleted: root.refresh()

    readonly property var swatches: [
        "#e6e6e6", "#121212", "#c8a97e", "#8db89a",
        "#c98989", "#6aa8c8", "#b6a6c8", "#d4c84a",
        "#e09040", "#4eb8b0", "#7cc86a", "#8a8a8a"
    ]

    function activeCanvas() {
        if (layerRepeater.count <= 0)
            return null
        var i = Math.max(0, Math.min(root.layerIndex, layerRepeater.count - 1))
        return layerRepeater.itemAt(i)
    }

    function docPoint(mx, my) {
        return Qt.point(mx / Math.max(0.05, root.zoom), my / Math.max(0.05, root.zoom))
    }

    function snapshot() {
        var canvas = root.activeCanvas()
        if (!canvas)
            return
        var ctx = canvas.getContext("2d")
        if (!ctx || !ctx.getImageData)
            return
        var copy = ctx.getImageData(0, 0, root.docW, root.docH)
        var stack = root.undoStack.slice()
        stack.push(copy)
        if (stack.length > 16)
            stack.shift()
        root.undoStack = stack
        root.redoStack = []
    }

    function restore(data) {
        var canvas = root.activeCanvas()
        if (!canvas || !data)
            return
        var ctx = canvas.getContext("2d")
        if (!ctx || !ctx.putImageData)
            return
        ctx.putImageData(data, 0, 0)
        canvas.requestPaint()
    }

    function undo() {
        if (root.undoStack.length === 0)
            return
        var canvas = root.activeCanvas()
        if (!canvas)
            return
        var ctx = canvas.getContext("2d")
        var current = null
        if (ctx && ctx.getImageData)
            current = ctx.getImageData(0, 0, root.docW, root.docH)
        var stack = root.undoStack.slice()
        var prev = stack.pop()
        root.undoStack = stack
        if (current) {
            var redo = root.redoStack.slice()
            redo.push(current)
            root.redoStack = redo
        }
        root.restore(prev)
    }

    function redo() {
        if (root.redoStack.length === 0)
            return
        root.snapshot()
        var stack = root.redoStack.slice()
        var next = stack.pop()
        root.redoStack = stack
        root.restore(next)
    }

    function clearActive() {
        var canvas = root.activeCanvas()
        if (!canvas)
            return
        root.snapshot()
        var ctx = canvas.getContext("2d")
        ctx.clearRect(0, 0, root.docW, root.docH)
        canvas.requestPaint()
    }

    function addLayer() {
        layers.append({
            "name": "Layer " + (layers.count + 1),
            "hidden": false
        })
        root.layerIndex = layers.count - 1
    }

    function removeLayer() {
        if (layers.count <= 1)
            return
        layers.remove(root.layerIndex)
        if (root.layerIndex >= layers.count)
            root.layerIndex = layers.count - 1
    }

    function bakeShape(x1, y1, x2, y2) {
        var canvas = root.activeCanvas()
        if (!canvas)
            return
        var ctx = canvas.getContext("2d")
        ctx.save()
        ctx.strokeStyle = root.paintColor
        ctx.fillStyle = root.paintColor
        ctx.lineWidth = Math.max(1, root.brushSize)
        ctx.lineCap = "round"
        ctx.lineJoin = "round"
        if (root.tool === "line") {
            ctx.beginPath()
            ctx.moveTo(x1, y1)
            ctx.lineTo(x2, y2)
            ctx.stroke()
        } else if (root.tool === "rect") {
            ctx.strokeRect(
                Math.min(x1, x2),
                Math.min(y1, y2),
                Math.abs(x2 - x1),
                Math.abs(y2 - y1)
            )
        } else if (root.tool === "oval") {
            var cx = (x1 + x2) / 2
            var cy = (y1 + y2) / 2
            var rx = Math.max(0.5, Math.abs(x2 - x1) / 2)
            var ry = Math.max(0.5, Math.abs(y2 - y1) / 2)
            ctx.beginPath()
            ctx.save()
            ctx.translate(cx, cy)
            ctx.scale(rx, ry)
            ctx.arc(0, 0, 1, 0, Math.PI * 2)
            ctx.restore()
            ctx.stroke()
        }
        ctx.restore()
        canvas.requestPaint()
    }

    function paintStroke(x1, y1, x2, y2) {
        var canvas = root.activeCanvas()
        if (!canvas)
            return
        var ctx = canvas.getContext("2d")
        ctx.save()
        if (root.tool === "eraser") {
            ctx.globalCompositeOperation = "destination-out"
            ctx.strokeStyle = "#ffffff"
        } else {
            ctx.globalCompositeOperation = "source-over"
            ctx.strokeStyle = root.paintColor
        }
        ctx.lineWidth = Math.max(1, root.brushSize)
        ctx.lineCap = "round"
        ctx.lineJoin = "round"
        ctx.beginPath()
        ctx.moveTo(x1, y1)
        ctx.lineTo(x2, y2)
        ctx.stroke()
        ctx.restore()
        canvas.requestPaint()
    }

    function pickAt(x, y) {
        var canvas = root.activeCanvas()
        if (!canvas)
            return
        var ctx = canvas.getContext("2d")
        if (!ctx.getImageData)
            return
        var data = ctx.getImageData(Math.floor(x), Math.floor(y), 1, 1)
        var px = data.data
        if (!px || px.length < 4 || px[3] < 8)
            return
        function hex(n) {
            var h = Math.max(0, Math.min(255, n)).toString(16)
            return h.length < 2 ? "0" + h : h
        }
        root.paintColor = "#" + hex(px[0]) + hex(px[1]) + hex(px[2])
    }

    function exportPng(path) {
        paper.grabToImage(function(result) {
            result.saveToFile(path)
            root.statusLine = "saved " + path
        })
    }

    function loadImage(url) {
        var canvas = root.activeCanvas()
        if (!canvas)
            return
        root.pendingImage = url
        canvas.loadImage(url)
    }

    ListModel {
        id: layers
        ListElement { name: "Layer 1"; hidden: false }
    }

    FileDialog {
        id: openDialog
        title: "OPEN IMAGE"
        fileMode: FileDialog.OpenFile
        nameFilters: ["Images (*.png *.jpg *.jpeg *.webp *.bmp)", "All files (*)"]
        onAccepted: root.loadImage(String(openDialog.selectedFile))
    }

    FileDialog {
        id: saveDialog
        title: "SAVE PNG"
        fileMode: FileDialog.SaveFile
        nameFilters: ["PNG (*.png)"]
        defaultSuffix: "png"
        currentFolder: "file:///home/GG/.local/state/goldgoblins/gg-ai-desktop/draw"
        onAccepted: {
            var raw = String(saveDialog.selectedFile || "")
            if (raw.indexOf("file://") === 0)
                raw = raw.substring(7)
            root.exportPng(raw)
        }
    }

    Item {
        anchors.fill: parent
        anchors.leftMargin: 6
        anchors.rightMargin: 6
        anchors.topMargin: 4
        anchors.bottomMargin: 6

        Column {
            width: parent.width
            height: parent.height
            spacing: 8

            Row {
                spacing: 10
                Text {
                    text: "SKETCH"
                    color: root.editorId === "sketch" ? "#d8dee9" : "#a8b0b8"
                    font.family: "monospace"
                    font.pixelSize: 12
                    font.bold: root.editorId === "sketch"
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.openEditor("sketch")
                    }
                }
                Repeater {
                    model: root.editors
                    delegate: Text {
                        required property var modelData
                        text: String(modelData.label || modelData.id)
                        color: root.editorId === String(modelData.id)
                            ? "#d8dee9"
                            : (modelData.present ? "#8b949e" : "#3a3a3a")
                        font.family: "monospace"
                        font.pixelSize: 12
                        font.bold: root.editorId === String(modelData.id)
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            enabled: modelData.present === true
                            onClicked: root.openEditor(String(modelData.id))
                        }
                    }
                }
            }

            Text {
                width: parent.width
                visible: !root.sketchMode
                text: {
                    var i
                    for (i = 0; i < root.editors.length; i++) {
                        if (String(root.editors[i].id) === root.editorId)
                            return String(root.editors[i].detail || "")
                    }
                    return "Install Krita, GIMP, Inkscape or darktable for the real desks."
                }
                color: "#c8cdd4"
                wrapMode: Text.WordWrap
                font.pixelSize: 12
            }

            Text {
                visible: !root.sketchMode
                text: "OPEN " + root.editorId.toUpperCase()
                color: "#c8a97e"
                font.family: "monospace"
                font.pixelSize: 12
                font.bold: true
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.openEditor(root.editorId)
                }
            }

            Item {
                objectName: "workspaceDrawHole"
                width: parent.width
                height: Math.max(80, parent.height - 72)
                visible: !root.sketchMode
                Rectangle {
                    anchors.fill: parent
                    color: "#0a0a0a"
                    border.color: root.frameBorder
                    border.width: 1
                }
                Text {
                    anchors.centerIn: parent
                    text: root.editorId.toUpperCase()
                    color: "#3a3a3a"
                    font.family: "monospace"
                    font.pixelSize: 18
                    font.bold: true
                }
            }

            Column {
                width: parent.width
                height: Math.max(80, parent.height - 28)
                visible: root.sketchMode
                spacing: 8

            Row {
                spacing: 10
                Repeater {
                    model: ["brush", "eraser", "line", "rect", "oval", "pick", "pan"]
                    delegate: Text {
                        required property string modelData
                        text: modelData.toUpperCase()
                        color: root.tool === modelData ? "#d8dee9" : "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                        font.bold: root.tool === modelData
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.tool = modelData
                        }
                    }
                }
                Text {
                    text: "SIZE " + root.brushSize
                    color: "#c8cdd4"
                    font.family: "monospace"
                    font.pixelSize: 12
                }
            }

            Row {
                spacing: 12
                Text {
                    text: "NEW"
                    color: "#c8a97e"
                    font.family: "monospace"
                    font.pixelSize: 12
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            root.snapshot()
                            root.clearActive()
                        }
                    }
                }
                Text {
                    text: "OPEN"
                    color: "#c8a97e"
                    font.family: "monospace"
                    font.pixelSize: 12
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: openDialog.open()
                    }
                }
                Text {
                    text: "SAVE"
                    color: "#c8a97e"
                    font.family: "monospace"
                    font.pixelSize: 12
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: saveDialog.open()
                    }
                }
                Text {
                    text: "UNDO"
                    color: "#c8a97e"
                    font.family: "monospace"
                    font.pixelSize: 12
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.undo()
                    }
                }
                Text {
                    text: "REDO"
                    color: "#c8a97e"
                    font.family: "monospace"
                    font.pixelSize: 12
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.redo()
                    }
                }
                Text {
                    text: "LAYER+"
                    color: "#c8a97e"
                    font.family: "monospace"
                    font.pixelSize: 12
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.addLayer()
                    }
                }
                Text {
                    text: "LAYER-"
                    color: "#c8a97e"
                    font.family: "monospace"
                    font.pixelSize: 12
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.removeLayer()
                    }
                }
            }

            Row {
                width: parent.width
                height: Math.max(120, parent.height - 72)
                spacing: 8

                Flickable {
                    id: hole
                    width: Math.max(80, parent.width - 168)
                    height: parent.height
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    contentWidth: root.docW * root.zoom + 24
                    contentHeight: root.docH * root.zoom + 24
                    interactive: root.tool === "pan"

                    Item {
                        id: paper
                        objectName: "workspaceDrawPaper"
                        x: 12
                        y: 12
                        width: root.docW * root.zoom
                        height: root.docH * root.zoom

                        Rectangle {
                            anchors.fill: parent
                            color: "#0d0d0d"
                        }

                        Canvas {
                            anchors.fill: parent
                            onPaint: {
                                var ctx = getContext("2d")
                                var s = 8
                                var x
                                var y
                                for (y = 0; y < height; y += s) {
                                    for (x = 0; x < width; x += s) {
                                        ctx.fillStyle = ((x + y) / s) % 2 === 0
                                            ? "#1a1a1a"
                                            : "#141414"
                                        ctx.fillRect(x, y, s, s)
                                    }
                                }
                            }
                            Component.onCompleted: requestPaint()
                        }

                        Item {
                            id: stack
                            width: root.docW
                            height: root.docH
                            scale: root.zoom
                            transformOrigin: Item.TopLeft

                            Repeater {
                                id: layerRepeater
                                model: layers
                                delegate: Canvas {
                                    required property int index
                                    required property string name
                                    required property bool hidden
                                    width: root.docW
                                    height: root.docH
                                    visible: !hidden
                                    renderTarget: Canvas.Image
                                    renderStrategy: Canvas.Immediate
                                    onImageLoaded: {
                                        if (!root.pendingImage)
                                            return
                                        if (!isImageLoaded(root.pendingImage))
                                            return
                                        var ctx = getContext("2d")
                                        ctx.drawImage(
                                            root.pendingImage,
                                            0,
                                            0,
                                            root.docW,
                                            root.docH
                                        )
                                        requestPaint()
                                        root.pendingImage = ""
                                    }
                                }
                            }
                        }

                        Canvas {
                            id: overlay
                            anchors.fill: parent
                            visible: root.strokeOn
                                && (root.tool === "line"
                                    || root.tool === "rect"
                                    || root.tool === "oval")
                            onPaint: {
                                var ctx = getContext("2d")
                                ctx.clearRect(0, 0, width, height)
                                if (!root.strokeOn)
                                    return
                                var z = Math.max(0.05, root.zoom)
                                ctx.strokeStyle = root.paintColor
                                ctx.lineWidth = Math.max(1, root.brushSize * z)
                                ctx.beginPath()
                                if (root.tool === "line") {
                                    ctx.moveTo(root.startX * z, root.startY * z)
                                    ctx.lineTo(root.lastX * z, root.lastY * z)
                                    ctx.stroke()
                                } else if (root.tool === "rect") {
                                    ctx.strokeRect(
                                        Math.min(root.startX, root.lastX) * z,
                                        Math.min(root.startY, root.lastY) * z,
                                        Math.abs(root.lastX - root.startX) * z,
                                        Math.abs(root.lastY - root.startY) * z
                                    )
                                } else if (root.tool === "oval") {
                                    ctx.save()
                                    ctx.translate(
                                        ((root.startX + root.lastX) / 2) * z,
                                        ((root.startY + root.lastY) / 2) * z
                                    )
                                    ctx.scale(
                                        Math.max(0.5, Math.abs(root.lastX - root.startX) / 2 * z),
                                        Math.max(0.5, Math.abs(root.lastY - root.startY) / 2 * z)
                                    )
                                    ctx.arc(0, 0, 1, 0, Math.PI * 2)
                                    ctx.restore()
                                    ctx.stroke()
                                }
                            }
                        }

                        MouseArea {
                            anchors.fill: parent
                            hoverEnabled: true
                            acceptedButtons: Qt.LeftButton
                            cursorShape: root.tool === "pan"
                                ? Qt.OpenHandCursor
                                : Qt.CrossCursor
                            onPressed: function(mouse) {
                                if (root.tool === "pan")
                                    return
                                var p = root.docPoint(mouse.x, mouse.y)
                                root.startX = p.x
                                root.startY = p.y
                                root.lastX = p.x
                                root.lastY = p.y
                                root.strokeOn = true
                                if (root.tool === "pick") {
                                    root.pickAt(p.x, p.y)
                                    return
                                }
                                if (root.tool === "brush" || root.tool === "eraser") {
                                    root.snapshot()
                                    root.paintStroke(p.x, p.y, p.x, p.y)
                                }
                            }
                            onPositionChanged: function(mouse) {
                                var p = root.docPoint(mouse.x, mouse.y)
                                root.statusLine = Math.round(p.x) + "," + Math.round(p.y)
                                if (!root.strokeOn)
                                    return
                                if (root.tool === "brush" || root.tool === "eraser")
                                    root.paintStroke(root.lastX, root.lastY, p.x, p.y)
                                root.lastX = p.x
                                root.lastY = p.y
                                if (root.tool === "line" || root.tool === "rect" || root.tool === "oval")
                                    overlay.requestPaint()
                            }
                            onReleased: function(mouse) {
                                if (!root.strokeOn)
                                    return
                                var p = root.docPoint(mouse.x, mouse.y)
                                if (root.tool === "line" || root.tool === "rect" || root.tool === "oval") {
                                    root.snapshot()
                                    root.bakeShape(root.startX, root.startY, p.x, p.y)
                                }
                                root.strokeOn = false
                                overlay.requestPaint()
                            }
                            onWheel: function(wheel) {
                                var next = root.zoom + (wheel.angleDelta.y > 0 ? 0.08 : -0.08)
                                if (next < 0.15)
                                    next = 0.15
                                if (next > 4)
                                    next = 4
                                root.zoom = next
                            }
                        }
                    }
                }

                Column {
                    width: 160
                    height: parent.height
                    spacing: 6

                    Text {
                        text: "COLOR"
                        color: "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                    }

                    Rectangle {
                        width: 28
                        height: 28
                        color: root.paintColor
                        border.color: "#d8dee9"
                        border.width: 1
                    }

                    Flow {
                        width: parent.width
                        spacing: 4
                        Repeater {
                            model: root.swatches
                            delegate: Rectangle {
                                required property string modelData
                                width: 16
                                height: 16
                                color: modelData
                                border.color: root.paintColor === modelData
                                    ? "#e6e6e6"
                                    : "#2a2a2a"
                                border.width: 1
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: root.paintColor = modelData
                                }
                            }
                        }
                    }

                    Text {
                        text: "SIZE · " + String(root.brushSize)
                        color: "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                    }

                    GgSlider {
                        width: parent.width
                        from: 1
                        to: 64
                        stepSize: 1
                        value: root.brushSize
                        onMoved: root.brushSize = Math.round(value)
                    }

                    Text {
                        text: "ZOOM · " + String(Math.round(root.zoom * 100)) + "%"
                        color: "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                    }

                    GgSlider {
                        width: parent.width
                        from: 0.2
                        to: 2.5
                        stepSize: 0.05
                        value: root.zoom
                        onMoved: root.zoom = value
                    }

                    Text {
                        text: "LAYERS"
                        color: "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                    }

                    Repeater {
                        model: layers
                        delegate: Text {
                            required property int index
                            required property string name
                            required property bool hidden
                            width: 160
                            text: (root.layerIndex === index ? "▶ " : "  ")
                                + name
                                + (hidden ? " · off" : "")
                            color: root.layerIndex === index ? "#d8dee9" : "#c8cdd4"
                            font.family: "monospace"
                            font.pixelSize: 12
                            elide: Text.ElideRight
                            MouseArea {
                                anchors.fill: parent
                                acceptedButtons: Qt.LeftButton | Qt.RightButton
                                cursorShape: Qt.PointingHandCursor
                                onClicked: function(event) {
                                    if (event.button === Qt.RightButton) {
                                        layers.setProperty(index, "hidden", !hidden)
                                        return
                                    }
                                    root.layerIndex = index
                                }
                            }
                        }
                    }

                    Text {
                        width: parent.width
                        text: "Wheel zoom. PAN to move. Right-click a layer to hide it."
                        color: "#a8b0b8"
                        wrapMode: Text.WordWrap
                        font.pixelSize: 12
                    }
                }
            }
            }
        }
    }
}
