import QtQuick

Item {
    id: root
    property var values: []
    property var marks: []
    property color stroke: "#8db89a"
    property color fill: "#1c2a22"
    property color grid: "#242424"
    property real yMax: 0
    property bool fromZero: true
    property bool linear: false

    function redraw() {
        if (!root.visible)
            return
        if (width < 8 || height < 8)
            return
        plot.requestPaint()
    }

    Canvas {
        id: plot
        anchors.fill: parent
        renderTarget: Canvas.Image
        renderStrategy: Canvas.Threaded
        antialiasing: true
        onPaint: {
            var ctx = getContext("2d")
            var w = width
            var h = height
            ctx.clearRect(0, 0, w, h)
            if (w < 8 || h < 8)
                return
            var gx
            var gy
            ctx.lineJoin = "round"
            ctx.lineCap = "round"
            ctx.strokeStyle = root.grid
            ctx.lineWidth = 1
            for (gx = 0; gx <= 6; gx++) {
                var x = gx / 6 * w
                ctx.beginPath()
                ctx.moveTo(x, 0)
                ctx.lineTo(x, h)
                ctx.stroke()
            }
            for (gy = 0; gy <= 4; gy++) {
                var y = gy / 4 * h
                ctx.beginPath()
                ctx.moveTo(0, y)
                ctx.lineTo(w, y)
                ctx.stroke()
            }
            var pts = root.values
            if (!pts || pts.length < 1)
                return
            var maxv = Number(root.yMax || 0)
            var minv = root.fromZero ? 0 : Number.POSITIVE_INFINITY
            var i
            for (i = 0; i < pts.length; i++) {
                var v = Number(pts[i] || 0)
                if (v > maxv)
                    maxv = v
                if (!root.fromZero && v < minv)
                    minv = v
            }
            if (minv === Number.POSITIVE_INFINITY)
                minv = 0
            if (maxv <= minv)
                maxv = minv + 1
            if (!root.fromZero) {
                var pad = (maxv - minv) * 0.12
                if (pad <= 0)
                    pad = Math.abs(maxv) * 0.02 || 1
                minv -= pad
                maxv += pad
            }
            function yAt(val) {
                return h - ((Number(val || 0) - minv) / (maxv - minv)) * (h - 8) - 4
            }
            var last = pts.length < 2 ? 2 : pts.length
            var logSpan = Math.log(1 + last - 1)
            function xAt(index) {
                if (pts.length === 1)
                    return w
                if (root.linear)
                    return index / (pts.length - 1) * w
                // New samples enter at the right with generous spacing, then
                // compact toward the older left-side history.  This makes
                // fresh activity immediate without throwing away context.
                var fraction = logSpan > 0
                    ? 1 - Math.log(last - index) / logSpan
                    : index / (last - 1)
                return fraction * w
            }
            function traceHills(startAtBase) {
                var n = pts.length
                var x0 = xAt(0)
                var y0 = yAt(pts[0])
                if (startAtBase) {
                    ctx.moveTo(0, h)
                    ctx.lineTo(x0, y0)
                } else {
                    ctx.moveTo(x0, y0)
                }
                if (n === 1) {
                    if (startAtBase) {
                        ctx.lineTo(w, h)
                        ctx.closePath()
                    }
                    return
                }
                for (i = 1; i < n - 1; i++) {
                    var xc = (xAt(i) + xAt(i + 1)) / 2
                    var yc = (yAt(pts[i]) + yAt(pts[i + 1])) / 2
                    ctx.quadraticCurveTo(xAt(i), yAt(pts[i]), xc, yc)
                }
                ctx.quadraticCurveTo(
                    xAt(n - 1),
                    yAt(pts[n - 1]),
                    xAt(n - 1),
                    yAt(pts[n - 1])
                )
                if (startAtBase) {
                    ctx.lineTo(w, h)
                    ctx.closePath()
                }
            }
            ctx.beginPath()
            traceHills(true)
            ctx.fillStyle = root.fill
            ctx.fill()
            ctx.beginPath()
            traceHills(false)
            ctx.strokeStyle = root.stroke
            ctx.lineWidth = 1.6
            ctx.lineJoin = "round"
            ctx.lineCap = "round"
            ctx.stroke()
            if (root.linear && pts.length > 1) {
                var lastY = yAt(pts[pts.length - 1])
                ctx.save()
                ctx.setLineDash([3, 4])
                ctx.globalAlpha = 0.45
                ctx.beginPath()
                ctx.moveTo(0, lastY)
                ctx.lineTo(w, lastY)
                ctx.stroke()
                ctx.restore()
            }
            var marks = root.marks || []
            var n = pts.length
            for (i = 0; i < marks.length; i++) {
                var m = marks[i] || {}
                var mi = Number(m.i)
                if (mi < 0)
                    continue
                if (mi > n - 1)
                    mi = n - 1
                var mx = xAt(mi)
                var my = yAt(m.px !== undefined && m.px !== null && Number(m.px) > 0
                    ? m.px
                    : pts[Math.round(mi)])
                var buy = String(m.side || "") === "buy"
                ctx.beginPath()
                if (buy) {
                    ctx.moveTo(mx, my - 6)
                    ctx.lineTo(mx - 4.5, my + 3)
                    ctx.lineTo(mx + 4.5, my + 3)
                } else {
                    ctx.moveTo(mx, my + 6)
                    ctx.lineTo(mx - 4.5, my - 3)
                    ctx.lineTo(mx + 4.5, my - 3)
                }
                ctx.closePath()
                ctx.fillStyle = buy ? "#8db89a" : "#c98989"
                ctx.fill()
            }
        }
    }

    onValuesChanged: root.redraw()
    onMarksChanged: root.redraw()
    onYMaxChanged: root.redraw()
    onFromZeroChanged: root.redraw()
    onLinearChanged: root.redraw()
    onWidthChanged: root.redraw()
    onHeightChanged: root.redraw()
    onVisibleChanged: {
        if (visible)
            root.redraw()
    }
}
