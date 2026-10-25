pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Window

Item {
    id: root

    objectName: "utilitySurface"

    property color accentColor: "#8a8a8a"
    property color frameBorder: "#6a6a6a"
    property int frameRadius: 4
    property int surfaceHeight: 112
    property var surfaceHost: null
    property string statusJson: "{}"
    signal surfaceRequested(string kind)
    readonly property string capabilityState: "REAL_LOCAL_MEDIA"

    implicitHeight: root.surfaceHeight

    readonly property var status: {
        try {
            return JSON.parse(root.statusJson || "{}")
        } catch (err) {
            return {}
        }
    }

    readonly property string mode: String(root.status.mode || "MUSIC")
    property bool meterPlaying: false
    property bool meterPaused: false
    readonly property bool playing: root.meterPlaying
    readonly property bool paused: root.meterPaused
    readonly property string nowTitle: String((root.status.now || {}).title || "")
    readonly property string nowArtist: String((root.status.now || {}).artist || "")
    property bool masterAudioReady: false
    property bool appMeterReady: false
    property bool appAudioActive: false
    property int masterVolume: 100
    property int volumePreview: -1
    readonly property int volume: volumePreview >= 0 ? volumePreview
        : masterAudioReady ? masterVolume
        : Number(root.status.volume === undefined ? 70 : root.status.volume)
    readonly property var spectrum: {
        var rows = root.status.spectrum
        if (rows && rows.length !== undefined)
            return rows
        return []
    }
    readonly property var eqBands: {
        var rows = root.status.eq_bands
        if (rows && rows.length !== undefined)
            return rows
        return [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    }
    readonly property real duration: Number(root.status.duration || 0)
    readonly property real position: Number(root.status.position || 0)
    readonly property bool seekable: root.duration > 0.5
    readonly property real progress: {
        if (!root.seekable)
            return 0
        return Math.max(0, Math.min(1, root.position / root.duration))
    }
    property string meterClock: "00:00"
    property string meterLength: "00:00"
    property real liveFreq: 0
    property string liveRf: "NONE"
    property string liveRfLabel: "NO RF"
    property var liveMarks: []
    readonly property real fmLo: 87.5
    readonly property real fmHi: 108.0
    readonly property int spectrumBars: 120
    readonly property int spectrumSegs: 18
    readonly property int peakHoldTicks: 10
    readonly property real spectrumAttack: 18
    readonly property real spectrumRelease: 2.4
    readonly property bool buffering:
        root.status.buffering === true && !root.playing && !root.paused
    // Focus and occlusion do not stop live indicators. Only skip drawing when
    // the utility or its window cannot be seen at all.
    readonly property bool visualActive: root.visible && (!root.Window.window
        || (root.Window.window.visible && root.Window.window.visibility !== Window.Minimized))
    property bool spectrumSettling: false
    property bool spectrumDirty: true
    property string frequencyVisualKey: ""
    property bool lastSpectrumActive: false
    readonly property bool liveMeters:
        root.meterActive || (root.visualActive && root.spectrumSettling)
    readonly property bool meterActive: root.appMeterReady ? root.appAudioActive : root.playing
    readonly property bool hasSpectrum: root.spectrum.length > 0
    readonly property string frameRightLegend: {
        if (root.appAudioActive && !root.playing)
            return "LIVE · GG AUDIO"
        var head = root.buffering
            ? "BUFFER · " + root.mode
            : (root.playing ? "LIVE · " + root.mode : root.mode)
        if (root.liveFreq > 0)
            head += " · " + root.liveFreq.toFixed(1) + " MHz"
        if (root.mode === "RADIO")
            head += " · " + root.liveRfLabel
        return head
    }

    function pullLiveRaw() {
        if (!root.surfaceHost)
            return ""
        var raw = ""
        if (root.surfaceHost.mediaLiveStatus)
            raw = root.surfaceHost.mediaLiveStatus()
        if (!raw || raw === "{}")
            return ""
        return raw
    }

    function chromeBlob(parsed) {
        return JSON.stringify({
            "mode": String(parsed.mode || "MUSIC"),
            "playing": parsed.playing === true,
            "paused": parsed.paused === true,
            "now": parsed.now || {},
            "volume": Number(parsed.volume || 0),
            "duration": Number(parsed.duration || 0),
            "eq_preset": String(parsed.eq_preset || "Flat"),
            "eq_bands": parsed.eq_bands || [],
            "player": String(parsed.player || ""),
            "shuffle": parsed.shuffle === true,
            "repeat": String(parsed.repeat || "off"),
            "buffering": parsed.buffering === true,
            "error": String(parsed.error || ""),
            "reconnecting": parsed.reconnecting === true,
            "retry_attempt": Number(parsed.retry_attempt || 0),
            "retry_limit": Number(parsed.retry_limit || 0),
            "buffering_id": String(parsed.buffering_id || ""),
            "buffering_source": String(parsed.buffering_source || "")
        })
    }

    function applyChrome(parsed) {
        var blob = root.chromeBlob(parsed)
        if (blob !== root.statusJson)
            root.statusJson = blob
    }

    function refresh(forceVisual) {
        var raw = root.pullLiveRaw()
        if (raw) {
            try {
                root.applyChrome(JSON.parse(raw))
            } catch (err) {
                return
            }
        }
        root.refreshMeters(raw || "{}", forceVisual === true)
    }

    function refreshMeters(raw, forceVisual) {
        var text = raw || root.pullLiveRaw() || "{}"
        var parsed
        try {
            parsed = JSON.parse(text)
        } catch (err) {
            return
        }
        root.applyChrome(parsed)
        var spec = parsed.spectrum
        if (root.surfaceHost && root.surfaceHost.appAudioStatus) {
            try {
                var audio = JSON.parse(root.surfaceHost.appAudioStatus() || "{}")
                root.masterAudioReady = audio.available === true
                root.appMeterReady = audio.meter_available === true
                root.appAudioActive = audio.active === true
                if (audio.volume !== undefined)
                    root.masterVolume = Number(audio.volume)
                if (root.appMeterReady)
                    spec = audio.spectrum || []
            } catch (err) {
                root.appAudioActive = false
            }
        }
        if (!spec || spec.length === undefined)
            spec = []
        var levelsChanged = false
        if (spectrumCanvas) {
            var before = spectrumCanvas.levels || []
            levelsChanged = before.length !== spec.length
            for (var i = 0; !levelsChanged && i < spec.length; i++)
                levelsChanged = Number(before[i] || 0) !== Number(spec[i] || 0)
            if (levelsChanged)
                spectrumCanvas.levels = spec
        }
        var clock = String(parsed.clock || "00:00")
        var length = String(parsed.length || "00:00")
        if (clock !== root.meterClock)
            root.meterClock = clock
        if (length !== root.meterLength)
            root.meterLength = length
        root.meterPlaying = parsed.playing === true
        root.meterPaused = parsed.paused === true
        root.liveFreq = Number(parsed.freq_mhz || 0)
        var rf = parsed.rf || {}
        root.liveRf = String(rf.kind || "NONE")
        root.liveRfLabel = String(rf.label || "NO RF")
        if (parsed.tuner && parsed.tuner.length !== undefined)
            root.liveMarks = parsed.tuner
        var activeChanged = root.lastSpectrumActive !== root.meterActive
        root.lastSpectrumActive = root.meterActive
        root.spectrumDirty = root.spectrumDirty || levelsChanged || activeChanged
        var frequencyKey = JSON.stringify([root.liveFreq, root.liveRf, root.liveRfLabel, root.liveMarks])
        var frequencyChanged = frequencyKey !== root.frequencyVisualKey
        root.frequencyVisualKey = frequencyKey
        if (root.visualActive) {
            if (spectrumCanvas && (forceVisual === true || root.spectrumDirty || root.spectrumSettling))
                spectrumCanvas.requestPaint()
            if (freqCanvas && (forceVisual === true || frequencyChanged))
                freqCanvas.requestPaint()
        }
    }

    function setMode(mode) {
        if (!root.surfaceHost)
            return
        root.surfaceRequested("MEDIA")
        root.statusJson = root.surfaceHost.mediaSetMode(mode)
        if (mode === "FETCH" && root.surfaceHost.mediaStartFetch)
            root.statusJson = root.surfaceHost.mediaStartFetch()
        root.refresh()
    }

    function playPause() {
        if (!root.surfaceHost)
            return
        root.surfaceRequested("MEDIA")
        if (root.playing)
            root.statusJson = root.surfaceHost.mediaPause()
        else if (root.paused)
            root.statusJson = root.surfaceHost.mediaPause()
        else
            root.statusJson = root.surfaceHost.mediaSkip(0)
        root.refresh()
    }

    function stop() {
        if (!root.surfaceHost)
            return
        root.statusJson = root.surfaceHost.mediaStop()
        root.refresh()
    }

    function skip(delta) {
        if (!root.surfaceHost)
            return
        root.surfaceRequested("MEDIA")
        root.statusJson = root.surfaceHost.mediaSkip(delta)
        root.refresh()
    }

    function previewVolume(value) {
        root.volumePreview = Math.max(0, Math.min(100, Math.round(value)))
        if (root.masterAudioReady && root.surfaceHost && root.surfaceHost.appPreviewAudioVolume) {
            root.surfaceHost.appPreviewAudioVolume(root.volumePreview)
            root.refreshMeters()
        }
        volumeCommitTimer.restart()
    }

    function commitVolume() {
        volumeCommitTimer.stop()
        if (!root.surfaceHost || root.volumePreview < 0)
            return
        if (root.masterAudioReady && root.surfaceHost.appSetAudioVolume) {
            var audio = JSON.parse(root.surfaceHost.appSetAudioVolume(root.volumePreview))
            root.masterVolume = Number(audio.volume)
        } else if (root.surfaceHost.mediaSetVolume) {
            root.applyChrome(JSON.parse(root.surfaceHost.mediaSetVolume(root.volumePreview)))
        }
        root.volumePreview = -1
    }

    function cycleEq() {
        if (!root.surfaceHost || !root.surfaceHost.mediaSetEqPreset)
            return
        root.statusJson = root.surfaceHost.mediaSetEqPreset("cycle")
        root.refresh()
    }

    function flattenEq() {
        if (!root.surfaceHost || !root.surfaceHost.mediaSetEqPreset)
            return
        root.statusJson = root.surfaceHost.mediaSetEqPreset("Flat")
        root.refresh()
    }

    function setEqFromY(index, y, height) {
        if (!root.surfaceHost || !root.surfaceHost.mediaSetEqBand)
            return
        var span = Math.max(1, Number(height))
        var db = 12 - (Number(y) / span) * 24
        if (db > 12)
            db = 12
        if (db < -12)
            db = -12
        root.statusJson = root.surfaceHost.mediaSetEqBand(index, db)
        root.refresh()
    }

    function seekAt(x, width) {
        if (!root.surfaceHost || !root.surfaceHost.mediaSeek)
            return
        if (!root.seekable)
            return
        var frac = Math.max(0, Math.min(1, Number(x) / Math.max(1, Number(width))))
        root.statusJson = root.surfaceHost.mediaSeek(frac * root.duration)
        root.refresh()
    }

    function tuneAt(x, width) {
        if (!root.surfaceHost || !root.surfaceHost.mediaTuneMhz)
            return
        var span = root.fmHi - root.fmLo
        var mhz = root.fmLo + span * Math.max(0, Math.min(1, Number(x) / Math.max(1, Number(width))))
        root.surfaceRequested("MEDIA")
        root.statusJson = root.surfaceHost.mediaTuneMhz(mhz)
        root.refresh()
    }

    function toolMark(name) {
        var tools = root.status.tools || {}
        var row = tools[name] || {}
        return name.toUpperCase() + (row.present ? " ON" : " OFF")
    }

    function bandAt(index) {
        var rows = spectrumCanvas ? spectrumCanvas.levels : root.spectrum
        if (!rows || rows.length === 0)
            return 0
        if (index < rows.length)
            return Number(rows[index] || 0)
        return 0
    }

    function ledColor(frac) {
        if (frac < 0.32)
            return "#4eb8b0"
        if (frac < 0.52)
            return "#7cc86a"
        if (frac < 0.72)
            return "#d4c84a"
        if (frac < 0.88)
            return "#e09040"
        return "#e05050"
    }

    function eqAt(index) {
        var rows = root.eqBands
        if (!rows || index >= rows.length)
            return 0
        return Number(rows[index] || 0)
    }

    Connections {
        target: root.surfaceHost || null
        ignoreUnknownSignals: true
        function onMediaStateChanged() {
            root.refresh()
        }
    }

    Timer {
        id: volumeCommitTimer
        interval: 150
        repeat: false
        onTriggered: root.commitVolume()
    }

    Timer {
        objectName: "utilityActiveMeterTimer"
        // Keep real audio data current even while hidden; refreshMeters only
        // requests a visible, changed or settling Canvas to be painted.
        interval: 16
        running: root.liveMeters
        repeat: true
        onTriggered: root.refreshMeters()
    }

    Timer {
        objectName: "utilityIdleStatusTimer"
        interval: root.visualActive ? 400 : 1000
        running: !root.liveMeters
        repeat: true
        onTriggered: root.refresh()
    }

    onVisualActiveChanged: {
        if (root.visualActive)
            root.refresh(true)
    }

    Component.onCompleted: root.refresh()

    Item {
        anchors.fill: parent

        Rectangle {
            anchors.fill: parent
            color: "#161616"
            border.color: root.frameBorder
            border.width: 1
            radius: root.frameRadius
            antialiasing: true
        }

        Rectangle {
            anchors.left: parent.left
            anchors.leftMargin: 12
            anchors.top: parent.top
            anchors.topMargin: -8
            height: 18
            width: utilLeftLegend.implicitWidth + 12
            color: "#161616"
            radius: 3
            z: 2

            Text {
                id: utilLeftLegend
                anchors.centerIn: parent
                text: "MEDIA / UTILITIES"
                color: "#e6edf3"
                font.family: "monospace"
                font.pixelSize: 12
                font.bold: true
                verticalAlignment: Text.AlignVCenter
            }
        }

        Rectangle {
            anchors.right: parent.right
            anchors.rightMargin: 12
            anchors.top: parent.top
            anchors.topMargin: -8
            height: 18
            width: utilRightLegend.implicitWidth + 12
            color: "#161616"
            radius: 3
            z: 2

            Text {
                id: utilRightLegend
                anchors.centerIn: parent
                text: root.frameRightLegend
                color: "#c8cdd4"
                font.family: "monospace"
                font.pixelSize: 12
                font.bold: true
                verticalAlignment: Text.AlignVCenter
            }
        }

        Item {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.leftMargin: 10
            anchors.rightMargin: 10
            anchors.topMargin: 10
            anchors.bottomMargin: 8

            Row {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.bottom: timeline.top
                anchors.bottomMargin: 4
                spacing: 10

                Column {
                    width: 248
                    spacing: 4

                    Row {
                        objectName: "utilityModeRow"
                        spacing: 8

                        Repeater {
                            model: ["MUSIC", "RADIO", "TV", "GAME", "FETCH"]
                            delegate: Text {
                                required property string modelData
                                text: modelData
                                color: root.mode === modelData ? "#d8dee9" : "#a8b0b8"
                                font.family: "monospace"
                                font.pixelSize: 12
                                font.bold: root.mode === modelData
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: root.setMode(modelData)
                                }
                            }
                        }
                    }

                    Row {
                        objectName: "utilityTransport"
                        spacing: 10

                        Text {
                            text: "|<"
                            color: "#c8a97e"
                            font.family: "monospace"
                            font.pixelSize: 12
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.skip(-1)
                            }
                        }
                        Text {
                            text: root.playing ? "PAUSE" : "PLAY"
                            color: "#d8dee9"
                            font.family: "monospace"
                            font.pixelSize: 12
                            font.bold: true
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.playPause()
                            }
                        }
                        Text {
                            text: ">|"
                            color: "#c8a97e"
                            font.family: "monospace"
                            font.pixelSize: 12
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.skip(1)
                            }
                        }
                        Text {
                            text: "STOP"
                            color: "#c8cdd4"
                            font.family: "monospace"
                            font.pixelSize: 12
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.stop()
                            }
                        }
                    }

                    Row {
                        width: parent.width
                        spacing: 6

                        Text {
                            objectName: "utilityNow"
                            width: Math.max(
                                40,
                                parent.width
                                    - (nowMark.visible ? nowMark.width + 6 : 0)
                            )
                            text: root.status.reconnecting
                                ? "Återansluter · " + root.status.retry_attempt + "/" + root.status.retry_limit
                                : root.status.error
                                ? String(root.status.error)
                                : root.buffering
                                ? (
                                    (root.nowTitle.length > 0
                                        ? root.nowTitle
                                        : "NOW")
                                    + " · buffer"
                                )
                                : (
                                    root.nowTitle.length > 0
                                        ? root.nowTitle
                                        : (root.appAudioActive ? "GG AUDIO" : "NOW · idle")
                                )
                            color: root.playing || root.buffering
                                ? "#d8dee9"
                                : "#c8cdd4"
                            font.family: "monospace"
                            font.pixelSize: 12
                            font.bold: root.playing || root.buffering
                            elide: Text.ElideRight
                        }

                        BufferMark {
                            id: nowMark
                            objectName: "utilityNowBuffer"
                            anchors.verticalCenter: parent.verticalCenter
                            active: root.buffering
                            cell: 5
                        }
                    }

                    Text {
                        width: parent.width
                        text: {
                            var who = root.nowArtist.length > 0
                                ? root.nowArtist + " · "
                                : ""
                            return who + root.meterClock + " / " + root.meterLength
                        }
                        color: "#c8cdd4"
                        font.family: "monospace"
                        font.pixelSize: 12
                        elide: Text.ElideRight
                    }
                }

                Column {
                    width: Math.max(
                        120,
                        parent.width - 248 - 132 - 20
                    )
                    height: parent.height
                    spacing: 2

                    Canvas {
                        id: spectrumCanvas
                        objectName: "utilitySpectrum"
                        width: parent.width
                        height: Math.max(18, parent.height - 14)
                        renderTarget: Canvas.Image
                        renderStrategy: Canvas.Immediate
                        antialiasing: false
                        property var levels: []
                        property var shown: []
                        property var peaks: []
                        property var holds: []
                        onWidthChanged: requestPaint()
                        onHeightChanged: requestPaint()
                        onPaint: {
                            var ctx = getContext("2d")
                            var cols = root.spectrumBars
                            var segs = root.spectrumSegs
                            var w = width
                            var h = height
                            if (w < 2 || h < 2)
                                return
                            ctx.clearRect(0, 0, w, h)
                            var gapX = 1
                            var gapY = 1
                            var colW = Math.max(1, Math.floor((w - (cols - 1) * gapX) / cols))
                            var blockH = Math.max(1, Math.floor((h - (segs - 1) * gapY) / segs))
                            var usedH = segs * blockH + (segs - 1) * gapY
                            var yBase = h - usedH
                            var rows = spectrumCanvas.levels
                            var shown = spectrumCanvas.shown
                            var peaks = spectrumCanvas.peaks
                            var holds = spectrumCanvas.holds
                            if (!peaks || peaks.length !== cols || !shown || shown.length !== cols) {
                                shown = []
                                peaks = []
                                holds = []
                                var p
                                for (p = 0; p < cols; p++) {
                                    shown.push(0)
                                    peaks.push(0)
                                    holds.push(0)
                                }
                                spectrumCanvas.shown = shown
                                spectrumCanvas.peaks = peaks
                                spectrumCanvas.holds = holds
                            }
                            var x = 0
                            var i
                            var s
                            var step = 1 / Math.max(1, segs)
                            var up = step * root.spectrumAttack
                            var down = step * root.spectrumRelease
                            var litLevels = []
                            var peakLevels = []
                            var peakVisible = []
                            var settling = false
                            for (i = 0; i < cols; i++) {
                                var target = 0
                                if (root.meterActive && rows && i < rows.length)
                                    target = Math.min(1, Number(rows[i] || 0))
                                var cur = Number(shown[i] || 0)
                                if (target > cur)
                                    cur = Math.min(target, cur + up)
                                else
                                    cur = Math.max(target, cur - down)
                                if (cur < 0.002)
                                    cur = 0
                                shown[i] = cur
                                var level = cur
                                var peak = Number(peaks[i] || 0)
                                var hold = Number(holds[i] || 0)
                                if (level >= peak) {
                                    peak = level
                                    hold = root.peakHoldTicks
                                } else if (!root.meterActive) {
                                    hold = 0
                                    peak = Math.max(0, peak - step * 2)
                                } else if (hold > 0) {
                                    hold -= 1
                                } else {
                                    peak = Math.max(level, peak - step)
                                }
                                peaks[i] = peak
                                holds[i] = hold
                                litLevels.push(Math.round(level * segs))
                                var peakSeg = Math.round(peak * segs) - 1
                                if (peak > 0 && peakSeg < 0)
                                    peakSeg = 0
                                peakLevels.push(peakSeg)
                                peakVisible.push(peak > 0.02)
                                // Unchanged input still needs frames until the
                                // release and peak-hold display have converged.
                                if (Math.abs(cur - target) > 0.002 || peak > level + 0.002)
                                    settling = true
                                x += colW + gapX
                                if (x >= w)
                                    break
                            }
                            root.spectrumSettling = settling
                            root.spectrumDirty = false
                            // Paint row-wise with one fill style per LED color.
                            // Small square cells are intentionally used here:
                            // they read as crisp LED dots and avoid thousands
                            // of expensive path/arc operations per frame.
                            var dotW = Math.max(1, colW - 1)
                            var dotH = Math.max(1, blockH - 1)
                            for (s = 0; s < segs; s++) {
                                var frac = segs <= 1 ? 0 : s / (segs - 1)
                                ctx.fillStyle = root.ledColor(frac)
                                var rowY = yBase + (segs - 1 - s) * (blockH + gapY)
                                for (i = 0; i < litLevels.length; i++) {
                                    if (s < litLevels[i]) {
                                        var dotX = i * (colW + gapX)
                                        ctx.fillRect(
                                            dotX + Math.floor((colW - dotW) * 0.5),
                                            rowY + Math.floor((blockH - dotH) * 0.5),
                                            dotW,
                                            dotH
                                        )
                                    }
                                }
                            }
                            ctx.fillStyle = "#f0e6c0"
                            for (i = 0; i < peakLevels.length; i++) {
                                if (!peakVisible[i] || peakLevels[i] < litLevels[i])
                                    continue
                                var peakX = i * (colW + gapX)
                                var peakY = yBase + (segs - 1 - peakLevels[i]) * (blockH + gapY)
                                ctx.fillRect(
                                    peakX + Math.floor((colW - dotW) * 0.5),
                                    peakY + Math.floor((blockH - dotH) * 0.5),
                                    dotW,
                                    dotH
                                )
                            }
                        }
                    }

                    Canvas {
                        id: freqCanvas
                        objectName: "utilityFreqBand"
                        width: parent.width
                        height: 12
                        renderTarget: Canvas.Image
                        renderStrategy: Canvas.Immediate
                        antialiasing: true
                        onWidthChanged: requestPaint()
                        onHeightChanged: requestPaint()
                        onPaint: {
                            var ctx = getContext("2d")
                            ctx.reset()
                            var w = width
                            var h = height
                            if (w < 8 || h < 4)
                                return
                            var lo = root.fmLo
                            var hi = root.fmHi
                            var span = hi - lo
                            function xAt(mhz) {
                                return (Number(mhz) - lo) / span * w
                            }
                            ctx.fillStyle = "#141414"
                            ctx.fillRect(0, 0, w, h)
                            ctx.strokeStyle = "#2a2a2a"
                            ctx.lineWidth = 1
                            ctx.beginPath()
                            ctx.moveTo(0, h - 1)
                            ctx.lineTo(w, h - 1)
                            ctx.stroke()
                            var mhz
                            for (mhz = Math.ceil(lo); mhz <= hi; mhz++) {
                                var tx = xAt(mhz)
                                var major = mhz % 5 === 0
                                ctx.strokeStyle = major ? "#6a6a6a" : "#2a2a2a"
                                ctx.beginPath()
                                ctx.moveTo(tx, major ? 1 : h - 5)
                                ctx.lineTo(tx, h - 1)
                                ctx.stroke()
                            }
                            var marks = root.liveMarks || []
                            var i
                            for (i = 0; i < marks.length; i++) {
                                var mark = marks[i] || {}
                                var mx = xAt(mark.mhz)
                                ctx.fillStyle = "#8db89a"
                                ctx.fillRect(mx - 1, 2, 2, h - 3)
                            }
                            if (root.liveFreq > 0) {
                                var nx = xAt(root.liveFreq)
                                ctx.strokeStyle = "#c8a97e"
                                ctx.lineWidth = 1.4
                                ctx.beginPath()
                                ctx.moveTo(nx, 0)
                                ctx.lineTo(nx, h)
                                ctx.stroke()
                            }
                        }
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: function(event) {
                                root.tuneAt(event.x, freqCanvas.width)
                            }
                        }
                    }
                }

                Column {
                    id: eqControls
                    width: 132
                    height: parent.height
                    spacing: 4

                    Text {
                        id: eqPresetLabel
                        width: parent.width
                        text: "EQ · " + String(root.status.eq_preset || "Flat")
                        color: "#c8a97e"
                        font.family: "monospace"
                        font.pixelSize: 12
                        elide: Text.ElideRight
                        MouseArea {
                            anchors.fill: parent
                            acceptedButtons: Qt.LeftButton | Qt.RightButton
                            cursorShape: Qt.PointingHandCursor
                            onClicked: function(event) {
                                if (event.button === Qt.RightButton)
                                    root.flattenEq()
                                else
                                    root.cycleEq()
                            }
                        }
                    }

                    Row {
                        id: eqRow
                        objectName: "utilityEq"
                        width: parent.width
                        height: Math.max(20, eqControls.height - eqPresetLabel.implicitHeight - 26)
                        spacing: 2

                        Repeater {
                            model: 10
                            delegate: Item {
                                id: eqBand
                                required property int index
                                width: Math.max(8, (eqRow.width - 18) / 10)
                                height: eqRow.height

                                Rectangle {
                                    anchors.fill: parent
                                    color: "#141414"
                                }

                                Rectangle {
                                    width: parent.width
                                    height: 1
                                    y: parent.height / 2
                                    color: "#2a2a2a"
                                }

                                Rectangle {
                                    width: parent.width - 2
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    height: Math.max(
                                        2,
                                        parent.height * Math.abs(root.eqAt(eqBand.index)) / 12 * 0.5
                                    )
                                    y: root.eqAt(eqBand.index) >= 0
                                        ? parent.height / 2 - height
                                        : parent.height / 2
                                    color: root.eqAt(eqBand.index) >= 0 ? "#8db89a" : "#c8a97e"
                                }

                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    preventStealing: true
                                    onPressed: function(event) {
                                        root.setEqFromY(
                                            eqBand.index,
                                            event.y,
                                            eqBand.height
                                        )
                                    }
                                    onPositionChanged: function(event) {
                                        if (pressed)
                                            root.setEqFromY(
                                                eqBand.index,
                                                event.y,
                                                eqBand.height
                                            )
                                    }
                                    onDoubleClicked: root.setEqFromY(
                                        eqBand.index,
                                        eqBand.height / 2,
                                        eqBand.height
                                    )
                                }
                            }
                        }
                    }

                    Row {
                        objectName: "utilityMasterVolume"
                        width: parent.width
                        height: 18
                        spacing: 4

                        GgSlider {
                            objectName: "utilityMasterVolumeSlider"
                            width: 96
                            height: parent.height
                            from: 0
                            to: 100
                            stepSize: 1
                            value: root.volume
                            enabled: root.surfaceHost !== null
                            Accessible.name: "GG AI Desktop huvudvolym"
                            onMoved: root.previewVolume(value)
                            onPressedChanged: {
                                if (!pressed)
                                    root.commitVolume()
                            }
                        }

                        Text {
                            objectName: "utilityMasterVolumeValue"
                            width: 32
                            anchors.verticalCenter: parent.verticalCenter
                            text: root.volume + "%"
                            horizontalAlignment: Text.AlignRight
                            color: "#c8cdd4"
                            font.family: "monospace"
                            font.pixelSize: 11
                        }
                    }

                }
            }

            Item {
                id: timeline
                objectName: "utilityTimeline"
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: root.seekable ? 10 : 0
                visible: root.seekable

                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width
                    height: 4
                    radius: 2
                    color: "#1a1a1a"
                    border.color: "#2a2a2a"
                    border.width: 1
                }

                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    width: root.seekable
                        ? Math.max(0, parent.width * root.progress)
                        : 0
                    height: 4
                    radius: 2
                    color: "#c8a97e"
                    visible: root.seekable
                }

                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    x: Math.max(
                        0,
                        Math.min(parent.width - 8, parent.width * root.progress - 4)
                    )
                    width: 8
                    height: 8
                    radius: 4
                    color: "#d8dee9"
                    visible: root.seekable
                }

                MouseArea {
                    anchors.fill: parent
                    enabled: root.seekable
                    cursorShape: root.seekable
                        ? Qt.PointingHandCursor
                        : Qt.ArrowCursor
                    preventStealing: true
                    onPressed: function(event) {
                        root.seekAt(event.x, timeline.width)
                    }
                    onPositionChanged: function(event) {
                        if (pressed)
                            root.seekAt(event.x, timeline.width)
                    }
                }
            }
        }
    }
}
