import QtQuick
import QtQuick.Controls
import "TmogReadings.js" as Readings

Item {
    id: root
    objectName: "workspaceTmogPane"

    property var surfaceHost: null
    property color frameBorder: "#6a6a6a"
    property int frameRadius: 4
    readonly property color ink: "#e6edf3"
    readonly property color text: "#c8cdd4"
    readonly property color muted: "#8b949e"
    readonly property color panel: "#181818"
    readonly property color panelRaised: "#202020"
    readonly property color selectedPanel: "#34383d"
    readonly property color ledgerGold: "#c8a97e"
    readonly property color ledgerGreen: "#8db89a"
    property bool sidebarCollapsed: false
    property string statusJson: "{}"
    property int selectedPid: -1
    property string page: "SUMMARY"
    property string perfKey: "CPU"
    property string processSortKey: "cpu_pct"
    property bool processSortDescending: true
    property real rangeStart: 0.72
    property real rangeEnd: 1.0
    property bool rangeActive: false
    readonly property var emptyHist: [0]
    readonly property int liveCap: 120
    property int liveTicks: 0
    // Keep the 60 Hz pulse, but let the displayed meters settle over ~0.3 s.
    // Raw telemetry and recorded backend samples remain unchanged.
    readonly property real visualTimeConstant: 0.14
    property real lastVisualTickMs: 0
    property real liveCpu: 0
    property real cpuVelocity: 0
    property var coreVelocities: []
    property var readingPulse: ({})
    property bool hasReadingPulse: false
    readonly property var pulseReadingFields: ["cpu_busy", "cores", "gpu_busy", "temp_c", "mhz", "mhz_max",
        "mem_used_kb", "mem_total_kb", "disk_read_bps", "disk_write_bps",
        "net_rx_bps", "net_tx_bps", "energy_w"]
    property real liveGpu: 0
    property real liveMemUsed: 0
    property real liveMemTotal: 0
    property real liveTemp: 0
    property real liveLoad1: 0
    property real liveLoad5: 0
    property real liveLoad15: 0
    property real liveMhz: 0
    property int liveMhzMax: 0
    property int liveDiskRead: 0
    property int liveDiskWrite: 0
    property int liveNetRx: 0
    property int liveNetTx: 0
    property var liveCpuHist: []
    property var liveGpuHist: []
    property var liveMemHist: []
    property var liveTempHist: []
    property var liveDiskHist: []
    property var liveNetHist: []
    property var liveEnergyHist: []
    property var liveCoreHists: []
    property real liveEnergy: 0
    property real liveEnergyYMax: 40
    property var menuRow: ({})
    property string menuKind: ""
    property real netRxPos: 0
    property real netRxVel: 0
    property real netTxPos: 0
    property real netTxVel: 0
    property real diskRPos: 0
    property real diskRVel: 0
    property real diskWPos: 0
    property real diskWVel: 0
    property real liveNetYMax: 64
    property real liveDiskYMax: 256
    property bool diskLampOn: false

    readonly property var nav: [
        "SUMMARY",
        "PERFORMANCE",
        "PROCESSES",
        "SYSTEM",
        "STARTUP",
        "USERS",
        "SERVICES",
        "FREQ",
        "FLIGHT",
        "CONNECTIONS",
        "APPS",
        "DRIVERS",
        "DISK",
        "BENCHMARKS"
    ]

    readonly property var status: {
        try {
            return JSON.parse(root.statusJson || "{}")
        } catch (err) {
            return {}
        }
    }

    readonly property var processes: {
        var rows = root.status.processes
        if (rows && rows.length !== undefined)
            return rows
        return []
    }

    readonly property var selected: {
        var i
        for (i = 0; i < root.processes.length; i++) {
            if (Number(root.processes[i].pid) === root.selectedPid)
                return root.processes[i]
        }
        return null
    }

    readonly property var energy: root.status.energy || {}

    function navLabel(value) {
        var labels = {
            "SUMMARY": "Summary",
            "PERFORMANCE": "Performance",
            "PROCESSES": "Processes",
            "SYSTEM": "System Info",
            "STARTUP": "Startup apps",
            "USERS": "Users",
            "SERVICES": "Services",
            "FREQ": "Power & Freq",
            "FLIGHT": "Flight Recorder",
            "CONNECTIONS": "Connections",
            "APPS": "Installed Apps",
            "DRIVERS": "Drivers",
            "DISK": "Disk Space",
            "BENCHMARKS": "Benchmarks"
        }
        return labels[String(value || "")] || String(value || "")
    }

    function navIcon(value) {
        var icons = {
            "SUMMARY": "⌂",
            "PERFORMANCE": "▥",
            "PROCESSES": "▤",
            "SYSTEM": "ⓘ",
            "STARTUP": "▷",
            "USERS": "♙",
            "SERVICES": "⚙",
            "FREQ": "ϟ",
            "FLIGHT": "✈",
            "CONNECTIONS": "◎",
            "APPS": "▦",
            "DRIVERS": "⌁",
            "DISK": "▣",
            "BENCHMARKS": "◒"
        }
        return icons[String(value || "")] || "·"
    }

    function isProPage(value) {
        return ["FREQ", "FLIGHT", "CONNECTIONS", "APPS", "DRIVERS", "DISK", "BENCHMARKS"]
            .indexOf(String(value || "")) >= 0
    }

    function sortedProcesses(limit) {
        var rows = root.processes ? root.processes.slice() : []
        var key = root.processSortKey
        rows.sort(function(a, b) {
            var av = key === "name"
                ? String(a.comm || "").toLowerCase()
                : Number(a[key] || 0)
            var bv = key === "name"
                ? String(b.comm || "").toLowerCase()
                : Number(b[key] || 0)
            if (av < bv)
                return root.processSortDescending ? 1 : -1
            if (av > bv)
                return root.processSortDescending ? -1 : 1
            return Number(a.pid || 0) - Number(b.pid || 0)
        })
        if (limit !== undefined)
            return rows.slice(0, Math.max(0, Number(limit)))
        return rows
    }

    function toggleProcessSort(key) {
        if (root.processSortKey === key)
            root.processSortDescending = !root.processSortDescending
        else {
            root.processSortKey = key
            root.processSortDescending = key !== "name"
        }
    }

    function pressureLoad() {
        var pressure = root.status.pressure || {}
        if (pressure.cpu_some !== undefined && pressure.cpu_some !== null)
            return Math.min(100, Number(pressure.cpu_some || 0))
        var cores = Math.max(1, Number(root.status.core_count || 1))
        return Math.min(100, Number(root.n("load1") || 0) / cores * 100)
    }

    function memoryPressure() {
        var pressure = root.status.pressure || {}
        if (pressure.memory_some !== undefined && pressure.memory_some !== null)
            return Number(pressure.memory_some).toFixed(1) + "%"
        return "—"
    }

    function gpuLabel() {
        var rows = root.status.gpus
        if (rows && rows.length !== undefined && rows.length > 0)
            return String(rows[0].name || rows[0].model || "GPU 0")
        return "GPU 0"
    }

    function rangeLabel() {
        if (!root.rangeActive)
            return "SELECT A HISTORY RANGE"
        var samples = root.status.flight_history
        var count = samples && samples.length !== undefined ? samples.length : 120
        var span = Math.max(1, Math.round((root.rangeEnd - root.rangeStart) * count))
        return "RANGE " + span + " SAMPLES"
    }

    function flightRows() {
        var samples = root.status.flight_history
        if (!root.rangeActive
                || !samples
                || samples.length === undefined
                || samples.length === 0)
            return root.sortedProcesses(17)
        var lo = Math.floor(Math.min(root.rangeStart, root.rangeEnd) * samples.length)
        var hi = Math.ceil(Math.max(root.rangeStart, root.rangeEnd) * samples.length)
        lo = Math.max(0, Math.min(samples.length - 1, lo))
        hi = Math.max(lo + 1, Math.min(samples.length, hi))
        var table = ({})
        var i
        for (i = lo; i < hi; i++) {
            var rows = samples[i].processes || []
            var j
            for (j = 0; j < rows.length; j++) {
                var row = rows[j] || {}
                var pid = String(row.pid || "")
                if (!pid)
                    continue
                if (!table[pid]) {
                    table[pid] = {
                        pid: Number(row.pid || 0),
                        comm: String(row.comm || ""),
                        cpu_pct: 0,
                        rss_kb: 0,
                        samples: 0
                    }
                }
                table[pid].cpu_pct += Number(row.cpu_pct || 0)
                table[pid].rss_kb = Math.max(table[pid].rss_kb, Number(row.rss_kb || 0))
                table[pid].samples += 1
            }
        }
        var out = []
        var keys = Object.keys(table)
        for (i = 0; i < keys.length; i++) {
            var item = table[keys[i]]
            item.cpu_pct = item.samples ? item.cpu_pct / item.samples : 0
            out.push(item)
        }
        out.sort(function(a, b) {
            return Number(b.cpu_pct || 0) - Number(a.cpu_pct || 0)
        })
        return out.slice(0, 17)
    }

    function clearRange() {
        root.rangeActive = false
        root.rangeStart = 0.72
        root.rangeEnd = 1.0
    }

    function refresh() {
        if (!root.surfaceHost || !root.surfaceHost.tmogSnapshot)
            return
        var raw = root.surfaceHost.tmogSnapshot(root.page)
        if (raw === root.statusJson)
            return
        root.statusJson = raw
        if (root.liveCpuHist.length < 2) {
            try {
                var parsed = JSON.parse(raw)
                if (parsed.cpu_hist && parsed.cpu_hist.length)
                    root.liveCpuHist = parsed.cpu_hist.slice()
                if (parsed.gpu_hist && parsed.gpu_hist.length)
                    root.liveGpuHist = parsed.gpu_hist.slice()
                if (parsed.mem_hist && parsed.mem_hist.length)
                    root.liveMemHist = parsed.mem_hist.slice()
                if (parsed.temp_hist && parsed.temp_hist.length)
                    root.liveTempHist = parsed.temp_hist.slice()
                if (parsed.disk_hist && parsed.disk_hist.length)
                    root.liveDiskHist = parsed.disk_hist.slice()
                if (parsed.net_hist && parsed.net_hist.length)
                    root.liveNetHist = parsed.net_hist.slice()
                root.liveCpu = Number(parsed.cpu_busy || 0)
                root.liveMemUsed = Number(parsed.mem_used_kb || 0)
                root.liveMemTotal = Number(parsed.mem_total_kb || 0)
                root.liveTemp = Number(parsed.temp_c || 0)
                root.liveMhz = Number(parsed.mhz || 0)
                root.liveMhzMax = Number(parsed.mhz_max || 0)
            } catch (err) {
            }
        }
    }

    function copyText(text) {
        if (root.surfaceHost && root.surfaceHost.tmogCopy)
            root.surfaceHost.tmogCopy(String(text || ""))
    }

    function armMenu(kind, row) {
        root.menuKind = kind
        root.menuRow = row || {}
    }

    function rowLabel(row) {
        if (!row)
            return ""
        if (row.name)
            return String(row.name)
        if (row.comm)
            return String(row.comm)
        if (row.path)
            return String(row.path)
        if (row.local)
            return String(row.local)
        return ""
    }

    function shortName(value) {
        var s = String(value || "")
        var at = s.indexOf("@")
        if (at > 0)
            return s.slice(0, at)
        return s
    }

    function openFullTmog() {
        if (!root.surfaceHost || !root.surfaceHost.openTmog)
            return
        root.surfaceHost.openTmog()
        root.refresh()
    }

    function hideEmbed() {
        if (root.surfaceHost && root.surfaceHost.hideTmog)
            root.surfaceHost.hideTmog()
    }

    function kib(value) {
        var amount = Number(value || 0)
        if (amount >= 1024 * 1024)
            return (amount / 1024 / 1024).toFixed(1) + "G"
        if (amount >= 1024)
            return (amount / 1024).toFixed(1) + "M"
        return String(Math.round(amount)) + "K"
    }

    function bps(value) {
        var amount = Number(value || 0)
        if (amount >= 1024 * 1024)
            return (amount / 1024 / 1024).toFixed(1) + " MB/s"
        if (amount >= 1024)
            return (amount / 1024).toFixed(1) + " KB/s"
        return String(Math.round(amount)) + " B/s"
    }

    function clock(seconds) {
        var s = Math.max(0, Number(seconds || 0))
        var h = Math.floor(s / 3600)
        var m = Math.floor((s % 3600) / 60)
        var r = Math.floor(s % 60)
        return String(h).padStart(2, "0") + ":"
            + String(m).padStart(2, "0") + ":"
            + String(r).padStart(2, "0")
    }

    function arr(name) {
        if (name === "cpu_hist")
            return root.liveCpuHist.length ? root.liveCpuHist : (root.status.cpu_hist || root.emptyHist)
        if (name === "gpu_hist")
            return root.liveGpuHist.length ? root.liveGpuHist : (root.status.gpu_hist || root.emptyHist)
        if (name === "mem_hist")
            return root.liveMemHist.length ? root.liveMemHist : (root.status.mem_hist || root.emptyHist)
        if (name === "temp_hist")
            return root.liveTempHist.length ? root.liveTempHist : (root.status.temp_hist || root.emptyHist)
        if (name === "disk_hist")
            return root.liveDiskHist.length ? root.liveDiskHist : (root.status.disk_hist || root.emptyHist)
        if (name === "net_hist")
            return root.liveNetHist.length ? root.liveNetHist : (root.status.net_hist || root.emptyHist)
        if (name === "energy_hist")
            return root.liveEnergyHist.length ? root.liveEnergyHist : (root.status.energy_hist || root.emptyHist)
        if (name === "core_hist")
            return root.liveCoreHists
        var rows = root.status[name]
        if (rows && rows.length !== undefined)
            return rows
        return []
    }

    function metricText(name, digits, suffix) {
        return Readings.text(root.readingSource(name), name, digits, suffix)
    }

    function readingSource(name) {
        return root.hasReadingPulse && root.pulseReadingFields.indexOf(name) >= 0 ? root.readingPulse : root.status
    }

    function metricKib(name) {
        var value = Readings.value(root.readingSource(name), name)
        return value === null ? "--" : root.kib(value)
    }

    function coreText(index) {
        return Readings.coreText(root.readingSource("cores"), index, 1)
    }

    function energySource() {
        return String(root.hasReadingPulse && root.readingPulse.energy_source !== undefined
            ? root.readingPulse.energy_source : (root.energy.source || "UNKNOWN"))
    }

    function n(name, fallback) {
        var fb = fallback === undefined ? 0 : fallback
        if (name === "cpu_busy")
            return root.liveTicks > 0 ? root.liveCpu : Number(root.status.cpu_busy || fb)
        if (name === "gpu_busy")
            return root.liveTicks > 0 ? root.liveGpu : Number(root.status.gpu_busy || fb)
        if (name === "mem_used_kb")
            return root.liveTicks > 0 ? root.liveMemUsed : Number(root.status.mem_used_kb || fb)
        if (name === "mem_total_kb")
            return root.liveTicks > 0
                ? (root.liveMemTotal || fb)
                : Number(root.status.mem_total_kb || fb)
        if (name === "temp_c")
            return root.liveTicks > 0 ? root.liveTemp : Number(root.status.temp_c || fb)
        if (name === "load1")
            return root.liveTicks > 0 ? root.liveLoad1 : Number(root.status.load1 || fb)
        if (name === "load5")
            return root.liveTicks > 0 ? root.liveLoad5 : Number(root.status.load5 || fb)
        if (name === "load15")
            return root.liveTicks > 0 ? root.liveLoad15 : Number(root.status.load15 || fb)
        if (name === "mhz")
            return root.liveTicks > 0 ? root.liveMhz : Number(root.status.mhz || fb)
        if (name === "mhz_max")
            return root.liveTicks > 0 ? root.liveMhzMax : Number(root.status.mhz_max || fb)
        if (name === "disk_read_bps")
            return root.liveTicks > 0 ? root.liveDiskRead : Number(root.status.disk_read_bps || fb)
        if (name === "disk_write_bps")
            return root.liveTicks > 0 ? root.liveDiskWrite : Number(root.status.disk_write_bps || fb)
        if (name === "net_rx_bps")
            return root.liveTicks > 0 ? root.liveNetRx : Number(root.status.net_rx_bps || fb)
        if (name === "net_tx_bps")
            return root.liveTicks > 0 ? root.liveNetTx : Number(root.status.net_tx_bps || fb)
        if (name === "energy_w")
            return root.liveTicks > 0
                ? root.liveEnergy
                : Number(root.status.energy && root.status.energy.watts || fb)
        if (name === "disk_led")
            return Math.min(1, (root.liveDiskRead + root.liveDiskWrite) / (8 * 1024 * 1024))
        var v = root.status[name]
        if (v === undefined || v === null)
            return fb
        return Number(v)
    }

    function pushHist(hist, value) {
        var next = hist && hist.length !== undefined ? hist.slice() : []
        next.push(Number(value || 0))
        if (next.length > root.liveCap)
            next.splice(0, next.length - root.liveCap)
        return next
    }

    function dampValue(current, target, dt) {
        var goal = Math.max(0, Number(target || 0))
        if (!isFinite(goal))
            return current
        if (root.liveTicks === 0)
            return goal
        var weight = 1 - Math.exp(-dt / root.visualTimeConstant)
        return current + (goal - current) * weight
    }

    function springFollow(pos, vel, target, dt) {
        var goal = Math.max(0, Number(target || 0))
        // Exact critically damped step: stable under uneven frame spacing,
        // with a gentle release and no oscillating underdamped envelope.
        var omega = goal > pos ? 12 : 9
        var offset = pos - goal
        var impulse = vel + omega * offset
        var decay = Math.exp(-omega * dt)
        pos = goal + (offset + impulse * dt) * decay
        vel = (vel - omega * impulse * dt) * decay
        if (pos < 0) {
            pos = 0
            vel = 0
        }
        return [pos, vel]
    }

    function applyPulse(payload, elapsedSeconds) {
        var p = payload || {}
        root.readingPulse = p
        root.hasReadingPulse = true
        var dt = Number(elapsedSeconds || p.dt || 1 / 60)
        if (!isFinite(dt) || dt <= 0)
            dt = 1 / 60
        dt = Math.min(0.05, dt)
        var sprung
        sprung = root.springFollow(root.netRxPos, root.netRxVel, p.net_rx_bps, dt)
        root.netRxPos = sprung[0]
        root.netRxVel = sprung[1]
        sprung = root.springFollow(root.netTxPos, root.netTxVel, p.net_tx_bps, dt)
        root.netTxPos = sprung[0]
        root.netTxVel = sprung[1]
        sprung = root.springFollow(root.diskRPos, root.diskRVel, p.disk_read_bps, dt)
        root.diskRPos = sprung[0]
        root.diskRVel = sprung[1]
        sprung = root.springFollow(root.diskWPos, root.diskWVel, p.disk_write_bps, dt)
        root.diskWPos = sprung[0]
        root.diskWVel = sprung[1]
        // User-approved: use the existing disk/network spring, unchanged.
        sprung = root.springFollow(root.liveCpu, root.cpuVelocity, p.cpu_busy, dt)
        root.liveCpu = sprung[0]
        root.cpuVelocity = sprung[1]
        root.liveGpu = root.dampValue(root.liveGpu, p.gpu_busy, dt)
        root.liveMemUsed = root.dampValue(root.liveMemUsed, p.mem_used_kb, dt)
        root.liveMemTotal = Number(p.mem_total_kb || 0)
        root.liveTemp = root.dampValue(root.liveTemp, p.temp_c, dt)
        root.liveLoad1 = root.dampValue(root.liveLoad1, p.load1, dt)
        root.liveLoad5 = root.dampValue(root.liveLoad5, p.load5, dt)
        root.liveLoad15 = root.dampValue(root.liveLoad15, p.load15, dt)
        root.liveMhz = root.dampValue(root.liveMhz, p.mhz, dt)
        root.liveMhzMax = Number(p.mhz_max || 0)
        root.liveDiskRead = root.diskRPos
        root.liveDiskWrite = root.diskWPos
        root.liveNetRx = root.netRxPos
        root.liveNetTx = root.netTxPos
        root.liveCpuHist = root.pushHist(root.liveCpuHist, root.liveCpu)
        root.liveGpuHist = root.pushHist(root.liveGpuHist, root.liveGpu)
        root.liveMemHist = root.pushHist(
            root.liveMemHist,
            root.liveMemTotal ? (root.liveMemUsed / root.liveMemTotal * 100) : 0
        )
        root.liveTempHist = root.pushHist(root.liveTempHist, root.liveTemp)
        root.liveDiskHist = root.pushHist(
            root.liveDiskHist,
            (root.liveDiskRead + root.liveDiskWrite) / 1024.0
        )
        root.liveNetHist = root.pushHist(
            root.liveNetHist,
            (root.liveNetRx + root.liveNetTx) / 1024.0
        )
        if (p.energy_w !== undefined && p.energy_w !== null)
            root.liveEnergy = root.dampValue(root.liveEnergy, p.energy_w, dt)
        root.liveEnergyHist = root.pushHist(root.liveEnergyHist, root.liveEnergy)
        if (root.liveEnergy * 1.3 > root.liveEnergyYMax)
            root.liveEnergyYMax = Math.max(40, root.liveEnergy * 1.3)
        var netNow = (root.liveNetRx + root.liveNetTx) / 1024.0
        var diskNow = (root.liveDiskRead + root.liveDiskWrite) / 1024.0
        if (netNow * 1.2 > root.liveNetYMax)
            root.liveNetYMax = netNow * 1.2
        else
            root.liveNetYMax += (Math.max(64, netNow * 1.2) - root.liveNetYMax) * 0.01
        if (diskNow * 1.2 > root.liveDiskYMax)
            root.liveDiskYMax = diskNow * 1.2
        else
            root.liveDiskYMax += (Math.max(256, diskNow * 1.2) - root.liveDiskYMax) * 0.01
        var diskIo = Number(p.disk_read_bps || 0) + Number(p.disk_write_bps || 0)
        if (diskIo < 1024)
            root.diskLampOn = false
        else
            root.diskLampOn = (root.liveTicks % 6) < 3
        // Per-core history has no consumers outside the performance page.
        if (root.page !== "PERFORMANCE")
            return
        var cores = p.cores || []
        var rows = root.liveCoreHists && root.liveCoreHists.length
            ? root.liveCoreHists.slice()
            : []
        var velocities = root.coreVelocities.slice(0, cores.length)
        var i
        for (i = 0; i < cores.length; i++) {
            var hist = rows[i] || []
            var previous = hist.length ? hist[hist.length - 1] : Number(cores[i] || 0)
            sprung = root.springFollow(previous, Number(velocities[i] || 0), cores[i], dt)
            rows[i] = root.pushHist(hist, sprung[0])
            velocities[i] = sprung[1]
        }
        root.coreVelocities = velocities
        root.liveCoreHists = rows
    }

    function tick() {
        if (!root.surfaceHost || !root.surfaceHost.tmogPulse)
            return
        var now = Date.now()
        var elapsed = root.lastVisualTickMs > 0 ? (now - root.lastVisualTickMs) / 1000 : 1 / 60
        root.lastVisualTickMs = now
        try {
            root.applyPulse(JSON.parse(root.surfaceHost.tmogPulse() || "{}"), elapsed)
        } catch (err) {
        }
        root.liveTicks += 1
        if (root.liveTicks % 60 === 0) {
            root.refresh()
        }
    }

    Timer {
        interval: 16
        running: root.visible
        repeat: true
        onTriggered: root.tick()
    }

    onPageChanged: {
        if (root.visible)
            root.refresh()
    }

    onVisibleChanged: {
        root.lastVisualTickMs = 0
        if (visible)
            root.refresh()
        else
            root.hideEmbed()
    }

    Component.onCompleted: root.refresh()

    Item {
        id: chrome
        anchors.fill: parent
        anchors.leftMargin: 8
        anchors.rightMargin: 12
        anchors.topMargin: 8
        anchors.bottomMargin: 10

        Rectangle {
            anchors.fill: parent
            color: "#161616"
            border.color: "#4a4a4a"
            border.width: 1
            radius: 4
            antialiasing: true
        }

        Rectangle {
            id: sidebar
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: root.sidebarCollapsed ? 48 : Math.max(154, Math.min(210, parent.width * 0.17))
            color: "#181818"
            border.color: "#4a4a4a"
            border.width: 1
            radius: 4
            antialiasing: true

            Behavior on width {
                NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
            }

            Column {
                id: navCol
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.bottom: navBottom.top
                anchors.margins: 10
                spacing: 3

                Item {
                    width: navCol.width
                    height: 30
                    Text {
                        anchors.centerIn: parent
                        text: "☰"
                        color: root.ink
                        font.pixelSize: 20
                        font.family: "monospace"
                    }
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.sidebarCollapsed = !root.sidebarCollapsed
                    }
                }

                Repeater {
                    model: root.nav.slice(0, 7)
                    delegate: Item {
                        required property string modelData
                        width: navCol.width
                        height: 30
                        Rectangle {
                            anchors.fill: parent
                            color: root.page === modelData ? root.selectedPanel
                                : (hit.containsMouse ? "#202a35" : "transparent")
                            radius: 4
                        }
                        Text {
                            visible: !root.sidebarCollapsed
                            anchors.left: parent.left
                            anchors.leftMargin: 12
                            anchors.verticalCenter: parent.verticalCenter
                            text: root.navIcon(modelData)
                            color: root.page === modelData ? root.ledgerGold : root.muted
                            font.family: "monospace"
                            font.pixelSize: 15
                        }
                        Text {
                            visible: !root.sidebarCollapsed
                            anchors.left: parent.left
                            anchors.leftMargin: 38
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            text: root.navLabel(modelData)
                            color: root.page === modelData ? root.ink : root.text
                            font.family: "monospace"
                            font.pixelSize: 12
                            font.bold: root.page === modelData
                            elide: Text.ElideRight
                        }
                        Text {
                            visible: root.sidebarCollapsed
                            anchors.centerIn: parent
                            text: root.navIcon(modelData)
                            color: root.page === modelData ? root.ledgerGold : root.muted
                            font.family: "monospace"
                            font.pixelSize: 15
                        }
                        MouseArea {
                            id: hit
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.page = modelData
                        }
                    }
                }

                Item { width: 1; height: 7 }

                Rectangle {
                    width: navCol.width
                    height: 1
                    color: "#3a3a3a"
                }

                Text {
                    width: navCol.width
                    text: root.sidebarCollapsed ? "" : "PRO"
                    color: root.ledgerGold
                    font.family: "monospace"
                    font.pixelSize: 10
                    font.bold: true
                    leftPadding: 12
                    topPadding: 4
                    bottomPadding: 2
                }

                Repeater {
                    model: root.nav.slice(7)
                    delegate: Item {
                        required property string modelData
                        width: navCol.width
                        height: 30
                        Rectangle {
                            anchors.fill: parent
                            color: root.page === modelData ? root.selectedPanel
                                : (hit.containsMouse ? "#202a35" : "transparent")
                            radius: 4
                        }
                        Text {
                            visible: !root.sidebarCollapsed
                            anchors.left: parent.left
                            anchors.leftMargin: 12
                            anchors.verticalCenter: parent.verticalCenter
                            text: root.navIcon(modelData)
                            color: root.page === modelData ? root.ledgerGold : root.muted
                            font.family: "monospace"
                            font.pixelSize: 15
                        }
                        Text {
                            visible: !root.sidebarCollapsed
                            anchors.left: parent.left
                            anchors.leftMargin: 38
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            text: root.navLabel(modelData)
                            color: root.page === modelData ? root.ink : root.text
                            font.family: "monospace"
                            font.pixelSize: 12
                            font.bold: root.page === modelData
                            elide: Text.ElideRight
                        }
                        Text {
                            visible: root.sidebarCollapsed
                            anchors.centerIn: parent
                            text: root.navIcon(modelData)
                            color: root.page === modelData ? root.ledgerGold : root.muted
                            font.family: "monospace"
                            font.pixelSize: 15
                        }
                        MouseArea {
                            id: hit
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.page = modelData
                        }
                    }
                }
            }

            Item {
                id: navBottom
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: root.sidebarCollapsed ? 50 : 74

                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    height: 1
                    color: "#3a3a3a"
                }
                Text {
                    visible: !root.sidebarCollapsed
                    anchors.left: parent.left
                    anchors.leftMargin: 14
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 42
                    text: "TMOG"
                    color: "#6f9d9a"
                    font.family: "monospace"
                    font.pixelSize: 16
                    font.bold: true
                    font.letterSpacing: 1.2
                }
                Text {
                    visible: !root.sidebarCollapsed
                    anchors.left: parent.left
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 12
                    text: "⚙  SETTINGS       ◈  COLORS"
                    color: root.muted
                    font.family: "monospace"
                    font.pixelSize: 11
                }
                Text {
                    visible: root.sidebarCollapsed
                    anchors.centerIn: parent
                    text: "⚙"
                    color: root.muted
                    font.family: "monospace"
                    font.pixelSize: 16
                }
            }
        }

        Rectangle {
            id: navSep
            anchors.left: sidebar.right
            anchors.leftMargin: 12
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: 1
            color: "#3a3a3a"
        }

        Item {
            id: mainHeader
            anchors.left: navSep.right
            anchors.leftMargin: 18
            anchors.right: parent.right
            anchors.top: parent.top
            height: 54

            Text {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                text: String(root.page)
                color: root.ink
                font.family: "monospace"
                font.pixelSize: 18
                font.bold: false
            }
            Text {
                anchors.left: parent.left
                anchors.leftMargin: 2
                anchors.top: parent.top
                anchors.topMargin: 5
                text: "GG / TMOG · BETA 3 · LIVE"
                color: root.muted
                font.family: "monospace"
                font.pixelSize: 9
                visible: parent.height > 40
            }
            Rectangle {
                anchors.right: fullTmogButton.left
                anchors.rightMargin: 8
                anchors.verticalCenter: parent.verticalCenter
                width: refreshLabel.implicitWidth + 24
                height: 28
                color: refreshHit.pressed ? "#20262d" : "#181b1f"
                border.color: refreshHit.containsMouse ? root.ledgerGold : "#3c444d"
                border.width: 1
                radius: 3
                Text {
                    id: refreshLabel
                    anchors.centerIn: parent
                    text: "↻  REFRESH"
                    color: root.text
                    font.family: "monospace"
                    font.pixelSize: 11
                }
                MouseArea {
                    id: refreshHit
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.refresh()
                }
            }
            Rectangle {
                id: fullTmogButton
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                width: fullTmogLabel.implicitWidth + 24
                height: 28
                color: fullTmogHit.pressed ? "#2d382f" : "#1a2820"
                border.color: fullTmogHit.containsMouse ? root.ledgerGreen : "#486553"
                border.width: 1
                radius: 3
                Text {
                    id: fullTmogLabel
                    anchors.centerIn: parent
                    text: "OPEN FULL TMOG"
                    color: root.ledgerGreen
                    font.family: "monospace"
                    font.pixelSize: 11
                    font.bold: true
                }
                MouseArea {
                    id: fullTmogHit
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.openFullTmog()
                }
            }
        }

        Item {
            id: field
            anchors.left: navSep.right
            anchors.leftMargin: 18
            anchors.right: parent.right
            anchors.top: mainHeader.bottom
            anchors.topMargin: 4
            anchors.bottom: parent.bottom

                    Loader {
                        anchors.fill: parent
                        active: root.page === "SUMMARY"
                        visible: active
                        sourceComponent: summaryPage
                    }

                    Component {
                        id: summaryPage
                        Item {
                            anchors.fill: parent

                        TmogCard {
                            id: barsCard
                            anchors.left: parent.left
                            anchors.top: parent.top
                            width: Math.max(128, parent.width * 0.18)
                            height: parent.height * 0.42
                            leftLegend: "SYS"
                            rightLegend: root.metricText("cpu_busy", 1, "%")

                            Row {
                                id: sysBars
                                anchors.fill: parent
                                spacing: 6

                                Repeater {
                                    model: 4
                                    delegate: Item {
                                        required property int index
                                        readonly property string barKey: index === 0
                                            ? "cpu_busy"
                                            : (index === 1 ? "mhz" : (index === 2 ? "temp_c" : "gpu_busy"))
                                        readonly property real barCap: index === 0
                                            ? 100
                                            : (index === 1 ? Math.max(1, root.n("mhz_max"))
                                                : (index === 2 ? 105 : 100))
                                        readonly property color barColor: index === 0
                                            ? "#8db89a"
                                            : (index === 1 ? "#d58b8b"
                                                : (index === 2 ? "#c8a97e" : "#78a8d8"))
                                        width: Math.max(
                                            2,
                                            (sysBars.width - sysBars.spacing * 3) / 4
                                        )
                                        height: parent.height
                                        Rectangle {
                                            anchors.fill: parent
                                            color: "#1c1c1c"
                                            border.color: "#2a2a2a"
                                        }
                                        Rectangle {
                                            anchors.left: parent.left
                                            anchors.right: parent.right
                                            anchors.bottom: parent.bottom
                                            height: parent.height * Math.max(
                                                0.02,
                                                Math.min(1, (index === 3 ? root.liveGpu : root.n(barKey)) / barCap)
                                            )
                                            color: barColor
                                        }
                                        Text {
                                            anchors.top: parent.top
                                            anchors.topMargin: 4
                                            anchors.horizontalCenter: parent.horizontalCenter
                                            text: index === 0 ? "CPU" : (index === 1 ? "CLK" : (index === 2 ? "TMP" : "GPU"))
                                            color: barColor
                                            font.family: "monospace"
                                            font.pixelSize: 7
                                        }
                                        Text {
                                            anchors.bottom: parent.bottom
                                            anchors.bottomMargin: 4
                                            anchors.horizontalCenter: parent.horizontalCenter
                                            text: index === 0
                                                ? root.metricText("cpu_busy", 0, "%")
                                                : (index === 1
                                                    ? root.metricText("mhz", 0, "")
                                                    : (index === 2
                                                        ? root.metricText("temp_c", 0, "C")
                                                        : root.metricText("gpu_busy", 0, "%")))
                                            color: "#d8dee9"
                                            font.family: "monospace"
                                            font.pixelSize: 7
                                        }
                                    }
                                }
                            }
                        }

                        TmogCard {
                            id: cpuCard
                            anchors.left: barsCard.right
                            anchors.leftMargin: 8
                            anchors.right: topCard.left
                            anchors.rightMargin: 8
                            anchors.top: parent.top
                            height: barsCard.height
                            leftLegend: "CPU OVERVIEW"
                            rightLegend: root.metricText("cpu_busy", 1, "%")

                            Row {
                                anchors.fill: parent
                                anchors.margins: 8
                                spacing: 6
                                Repeater {
                                    model: [
                                        { "label": "CPU", "key": "cpu_hist", "max": 100, "color": "#8db89a", "fill": "#1c2a22" },
                                        { "label": "TEMP", "key": "temp_hist", "max": 105, "color": "#c8a97e", "fill": "#2a2418" },
                                        { "label": "GPU", "key": "gpu_hist", "max": 100, "color": "#78a8d8", "fill": "#182536" }
                                    ]
                                    delegate: Item {
                                        required property var modelData
                                        width: (parent.width - 12) / 3
                                        height: parent.height
                                        Text {
                                            anchors.left: parent.left
                                            anchors.top: parent.top
                                            text: modelData.label
                                            color: modelData.color
                                            font.family: "monospace"
                                            font.pixelSize: 10
                                        }
                                        TmogSpark {
                                            anchors.left: parent.left
                                            anchors.right: parent.right
                                            anchors.top: parent.top
                                            anchors.bottom: parent.bottom
                                            anchors.topMargin: 14
                                            values: root.arr(modelData.key)
                                            yMax: modelData.max
                                            stroke: modelData.color
                                            fill: modelData.fill
                                        }
                                    }
                                }
                            }
                        }

                        TmogCard {
                            id: topCard
                            anchors.right: parent.right
                            anchors.top: parent.top
                            width: Math.max(238, parent.width * 0.30)
                            height: barsCard.height
                            leftLegend: "TOP CPU PROCESSES"
                            rightLegend: String(Math.min(17, root.processes.length))

                            Column {
                                anchors.fill: parent
                                spacing: 2
                                Text {
                                    width: parent.width
                                    text: "PID       NAME              CPU    GPU   MEMORY"
                                    color: "#8793a0"
                                    font.family: "monospace"
                                    font.pixelSize: 9
                                    elide: Text.ElideRight
                                }
                                Repeater {
                                    model: root.sortedProcesses(17)
                                    delegate: TmogRow {
                                        required property var modelData
                                        width: parent.width
                                        text: String(modelData.pid).padStart(7, " ")
                                            + "  " + String(modelData.comm || "")
                                                .padEnd(16, " ").slice(0, 16)
                                            + "  " + String(modelData.cpu_pct).padStart(5, " ") + "%"
                                            + "  " + "—".padStart(4, " ")
                                            + "  " + root.kib(modelData.rss_kb).padStart(7, " ")
                                        selected: Number(modelData.pid) === root.selectedPid
                                        onChosen: root.selectedPid = Number(modelData.pid)
                                        onMenuRequested: {
                                            root.selectedPid = Number(modelData.pid)
                                            root.armMenu("proc", modelData)
                                            tmogMenu.popup()
                                        }
                                    }
                                }
                            }
                        }

                        TmogCard {
                            id: memCard
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: barsCard.bottom
                            anchors.topMargin: 10
                            height: parent.height * 0.25
                            leftLegend: "MEMORY UTILIZATION"
                            rightLegend: root.kib(root.n("mem_used_kb"))
                                + " / " + root.kib(root.n("mem_total_kb"))

                            Column {
                                anchors.fill: parent
                                spacing: 6
                                TmogMeter {
                                    width: parent.width
                                    ratio: root.n("mem_total_kb")
                                        ? root.n("mem_used_kb") / root.n("mem_total_kb")
                                        : 0
                                    onColor: "#b6a6c8"
                                    segments: 32
                                }
                                TmogSpark {
                                    width: parent.width
                                    height: parent.height - 22
                                    values: root.arr("mem_hist")
                                    yMax: 100
                                    stroke: "#b6a6c8"
                                    fill: "#241c28"
                                }
                            }
                        }

                        Row {
                            id: bottomRow
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: memCard.bottom
                            anchors.topMargin: 10
                            anchors.bottom: parent.bottom
                            spacing: 8

                            TmogCard {
                                id: pressureCard
                                width: (parent.width - 24) / 4
                                height: parent.height
                                leftLegend: "SYSTEM PRESSURE"
                                rightLegend: root.pressureLoad().toFixed(1) + "%"
                                Column {
                                    anchors.fill: parent
                                    spacing: 7
                                    Text {
                                        width: parent.width
                                        text: "LOW · Load demand " + root.pressureLoad().toFixed(1)
                                            + "% · Memory stalls " + root.memoryPressure()
                                        color: root.text
                                        font.family: "monospace"
                                        font.pixelSize: 10
                                        wrapMode: Text.WordWrap
                                    }
                                    TmogMeter {
                                        width: parent.width
                                        height: 12
                                        ratio: root.pressureLoad() / 100
                                        onColor: root.ledgerGreen
                                        segments: 22
                                    }
                                    Text {
                                        width: parent.width
                                        text: "LOAD " + String(root.n("load1")) + "  "
                                            + String(root.n("load5")) + "  "
                                            + String(root.n("load15"))
                                        color: root.muted
                                        font.family: "monospace"
                                        font.pixelSize: 10
                                    }
                                    Text {
                                        width: parent.width
                                        text: "TASKS " + String(root.n("tasks_running"))
                                            + " / " + String(root.n("process_count"))
                                        color: root.text
                                        font.family: "monospace"
                                        font.pixelSize: 11
                                    }
                                }
                            }
                            TmogCard {
                                width: (parent.width - 24) / 4
                                height: parent.height
                                leftLegend: "NETWORK"
                                rightLegend: String(root.status.net_iface || "—")
                                Column {
                                    anchors.fill: parent
                                    spacing: 5
                                    TmogSpark {
                                        width: parent.width
                                        height: Math.max(34, parent.height - 34)
                                        values: root.arr("net_hist")
                                        yMax: root.liveNetYMax
                                        stroke: "#8a8a8a"
                                        fill: "#1c2024"
                                    }
                                    Text {
                                        width: parent.width
                                        text: "R " + root.bps(root.n("net_rx_bps"))
                                            + " · S " + root.bps(root.n("net_tx_bps"))
                                        color: root.text
                                        font.family: "monospace"
                                        font.pixelSize: 10
                                    }
                                }
                            }
                            TmogCard {
                                width: (parent.width - 24) / 4
                                height: parent.height
                                leftLegend: "DISK"
                                lamp: true
                                lampOn: root.diskLampOn
                                rightLegend: root.bps(root.n("disk_read_bps")
                                    + root.n("disk_write_bps"))
                                Column {
                                    anchors.fill: parent
                                    spacing: 5
                                    TmogSpark {
                                        width: parent.width
                                        height: Math.max(34, parent.height - 34)
                                        values: root.arr("disk_hist")
                                        yMax: root.liveDiskYMax
                                        stroke: root.ledgerGreen
                                        fill: "#1c2a22"
                                    }
                                    Text {
                                        width: parent.width
                                        text: "R " + root.bps(root.n("disk_read_bps"))
                                            + " · W " + root.bps(root.n("disk_write_bps"))
                                        color: root.text
                                        font.family: "monospace"
                                        font.pixelSize: 10
                                    }
                                }
                            }
                            TmogCard {
                                width: (parent.width - 24) / 4
                                height: parent.height
                                leftLegend: "GPUs"
                                rightLegend: root.metricText("gpu_busy", 0, "%")
                                Column {
                                    anchors.fill: parent
                                    spacing: 7
                                    Text {
                                        width: parent.width
                                        text: root.gpuLabel()
                                        color: root.text
                                        font.family: "monospace"
                                        font.pixelSize: 11
                                        elide: Text.ElideRight
                                    }
                                    TmogMeter {
                                        width: parent.width
                                        ratio: root.n("gpu_busy") / 100
                                        onColor: "#78a8d8"
                                        segments: 22
                                    }
                                    Text {
                                        width: parent.width
                                        text: "SYS TEMP " + root.metricText("temp_c", 0, " C")
                                            + " · PKG " + root.metricText("energy_w", 1, " W")
                                        color: root.muted
                                        font.family: "monospace"
                                        font.pixelSize: 10
                                        wrapMode: Text.WordWrap
                                    }
                                    TmogSpark {
                                        width: parent.width
                                        height: Math.max(30, parent.height - 74)
                                        values: root.arr("gpu_hist")
                                        yMax: 100
                                        stroke: "#78a8d8"
                                        fill: "#182536"
                                    }
                                }
                            }
                        }
                    }
                    }

                    Loader {
                        anchors.fill: parent
                        active: root.page === "PERFORMANCE"
                        visible: active
                        sourceComponent: performancePage
                    }

                    Component {
                        id: performancePage
                        Item {
                            anchors.fill: parent

                        Column {
                            id: perfNav
                            width: 148
                            anchors.left: parent.left
                            anchors.top: parent.top
                            anchors.bottom: parent.bottom
                            spacing: 6

                            Repeater {
                                model: [
                                    { "k": "CPU", "c": "#8db89a", "h": "cpu_hist" },
                                    { "k": "GPU", "c": "#78a8d8", "h": "gpu_hist" },
                                    { "k": "MEMORY", "c": "#b6a6c8", "h": "mem_hist" },
                                    { "k": "ENERGY", "c": "#c8a97e", "h": "energy_hist" },
                                    { "k": "THERMALS", "c": "#c8a97e", "h": "temp_hist" },
                                    { "k": "DISK", "c": "#8db89a", "h": "disk_hist" },
                                    { "k": "NETWORK", "c": "#8a8a8a", "h": "net_hist" }
                                ]
                                delegate: TmogCard {
                                    required property var modelData
                                    width: perfNav.width
                                    height: 52
                                    leftLegend: modelData.k
                                    borderColor: root.perfKey === modelData.k
                                        ? "#8b949e"
                                        : "#3a3a3a"
                                    TmogSpark {
                                        anchors.fill: parent
                                        values: root.arr(modelData.h)
                                        stroke: modelData.c
                                        fill: "#161616"
                                        yMax: modelData.k === "CPU" || modelData.k === "MEMORY" || modelData.k === "GPU"
                                            ? 100
                                            : (modelData.k === "THERMALS"
                                                ? 105
                                                : (modelData.k === "ENERGY"
                                                    ? root.liveEnergyYMax
                                                    : (modelData.k === "DISK"
                                                        ? root.liveDiskYMax
                                                        : (modelData.k === "NETWORK"
                                                            ? root.liveNetYMax
                                                            : 0))))
                                    }
                                    MouseArea {
                                        anchors.fill: parent
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: root.perfKey = modelData.k
                                    }
                                }
                            }
                        }

                        TmogCard {
                            anchors.left: perfNav.right
                            anchors.leftMargin: 10
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.bottom: parent.bottom
                            leftLegend: root.perfKey
                            rightLegend: root.perfKey === "CPU"
                                ? root.metricText("cpu_busy", 1, "%")
                                : (root.perfKey === "GPU"
                                    ? root.metricText("gpu_busy", 1, "%")
                                    : (root.perfKey === "MEMORY"
                                    ? root.kib(root.n("mem_used_kb"))
                                    : (root.perfKey === "THERMALS"
                                        ? root.metricText("temp_c", 0, " C")
                                        : (root.perfKey === "DISK"
                                            ? root.bps(root.n("disk_read_bps"))
                                            : (root.perfKey === "NETWORK"
                                                ? root.bps(root.n("net_rx_bps") + root.n("net_tx_bps"))
                                                : (Readings.value(root.readingSource("energy_w"), "energy_w") !== null
                                                    ? root.metricText("energy_w", 1, " W")
                                                    : root.energySource()))))))

                            Column {
                                anchors.fill: parent
                                spacing: 8

                                TmogMeter {
                                    width: parent.width
                                    height: 16
                                    ratio: root.perfKey === "CPU"
                                        ? root.n("cpu_busy") / 100
                                        : (root.perfKey === "GPU"
                                            ? root.n("gpu_busy") / 100
                                            : (root.perfKey === "MEMORY"
                                            ? (root.n("mem_total_kb")
                                                ? root.n("mem_used_kb") / root.n("mem_total_kb")
                                                : 0)
                                            : (root.perfKey === "THERMALS"
                                                ? Math.min(1, root.n("temp_c") / 105)
                                                : (root.perfKey === "ENERGY"
                                                    ? (root.energy.battery_pct
                                                        ? Number(root.energy.battery_pct) / 100
                                                        : Math.min(1, root.n("energy_w") / Math.max(40, root.liveEnergyYMax)))
                                                    : 0.05))))
                                    onColor: root.perfKey === "GPU"
                                        ? "#78a8d8"
                                        : (root.perfKey === "MEMORY"
                                            ? "#b6a6c8"
                                            : (root.perfKey === "THERMALS" || root.perfKey === "ENERGY"
                                                ? "#c8a97e"
                                                : "#8db89a"))
                                    segments: 36
                                }

                                TmogHistoryGraph {
                                    id: perfHistoryGraph
                                    width: parent.width
                                    height: root.perfKey === "CPU"
                                        ? Math.max(96, parent.height * 0.30)
                                        : Math.max(120, parent.height * 0.55)
                                    selectable: true
                                    rangeActive: root.rangeActive
                                    values: root.perfKey === "GPU"
                                        ? root.arr("gpu_hist")
                                        : (root.perfKey === "MEMORY"
                                            ? root.arr("mem_hist")
                                            : (root.perfKey === "THERMALS"
                                            ? root.arr("temp_hist")
                                            : (root.perfKey === "ENERGY"
                                                ? root.arr("energy_hist")
                                            : (root.perfKey === "DISK"
                                                ? root.arr("disk_hist")
                                                : (root.perfKey === "NETWORK"
                                                    ? root.arr("net_hist")
                                                    : root.arr("cpu_hist"))))))
                                    yMax: root.perfKey === "CPU" || root.perfKey === "MEMORY" || root.perfKey === "GPU"
                                        ? 100
                                        : (root.perfKey === "THERMALS"
                                            ? 105
                                            : (root.perfKey === "ENERGY"
                                                ? root.liveEnergyYMax
                                            : (root.perfKey === "DISK"
                                                ? root.liveDiskYMax
                                                : (root.perfKey === "NETWORK"
                                                    ? root.liveNetYMax
                                                    : 0))))
                                    stroke: root.perfKey === "GPU"
                                        ? "#78a8d8"
                                        : (root.perfKey === "MEMORY"
                                            ? "#b6a6c8"
                                            : (root.perfKey === "THERMALS" || root.perfKey === "ENERGY"
                                                ? "#c8a97e"
                                                : "#8db89a"))
                                    fill: root.perfKey === "GPU"
                                        ? "#182536"
                                        : (root.perfKey === "MEMORY"
                                            ? "#241c28"
                                            : (root.perfKey === "THERMALS" || root.perfKey === "ENERGY"
                                                ? "#2a2418"
                                                : "#1c2a22"))
                                    rangeStart: root.rangeStart
                                    rangeEnd: root.rangeEnd
                                    onRangeSelected: function(start, end) {
                                        root.rangeStart = start
                                        root.rangeEnd = end
                                        root.rangeActive = true
                                    }
                                }

                                Row {
                                    width: parent.width
                                    spacing: 10
                                    Text {
                                        text: root.rangeLabel()
                                        color: root.rangeActive ? root.ledgerGold : root.muted
                                        font.family: "monospace"
                                        font.pixelSize: 10
                                    }
                                    Text {
                                        text: "DRAG OVER GRAPH TO INSPECT"
                                        color: root.muted
                                        font.family: "monospace"
                                        font.pixelSize: 10
                                    }
                                    Text {
                                        visible: root.rangeActive
                                        text: "· process sample at selected interval"
                                        color: root.text
                                        font.family: "monospace"
                                        font.pixelSize: 10
                                    }
                                    Text {
                                        visible: root.rangeActive
                                        text: "CLEAR"
                                        color: root.ledgerGold
                                        font.family: "monospace"
                                        font.pixelSize: 10
                                        MouseArea {
                                            anchors.fill: parent
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: root.clearRange()
                                        }
                                    }
                                }

                                Flow {
                                    width: parent.width
                                    spacing: 6
                                    visible: root.perfKey === "CPU"
                                    Repeater {
                                        model: root.arr("cores")
                                        delegate: TmogCard {
                                            required property var modelData
                                            required property int index
                                            width: 92
                                            height: 56
                                            compactLegend: true
                                            leftLegend: "CPU " + modelData.id
                                            rightLegend: root.coreText(Number(modelData.id))
                                            TmogSpark {
                                                anchors.fill: parent
                                                values: {
                                                    var all = root.arr("core_hist")
                                                    if (all && all.length > index)
                                                        return all[index]
                                                    return root.emptyHist
                                                }
                                                yMax: 100
                                                stroke: "#8db89a"
                                                fill: "#1c2a22"
                                            }
                                        }
                                    }
                                }

                                Text {
                                    width: parent.width
                                    wrapMode: Text.WordWrap
                                    color: "#c8cdd4"
                                    font.family: "monospace"
                                    font.pixelSize: 12
                                    text: root.perfKey === "CPU"
                                        ? (root.status.cpu_model || "")
                                            + "\n" + String(root.status.core_count || root.arr("cores").length) + " logical   "
                                            + root.metricText("mhz", 0, "") + " MHz   up "
                                            + root.clock(root.n("uptime_s"))
                                            + "   processes " + String(root.n("process_count"))
                                        : (root.perfKey === "GPU"
                                            ? "gpu " + root.metricText("gpu_busy", 1, "%")
                                            : (root.perfKey === "MEMORY"
                                            ? "capacity " + root.kib(root.n("mem_total_kb"))
                                                + "   used " + root.kib(root.n("mem_used_kb"))
                                                + "   avail " + root.kib(root.n("mem_avail_kb"))
                                                + "   cached " + root.metricKib("mem_cached_kb")
                                                + "\nswap " + root.kib(root.n("swap_used_kb"))
                                                + "   buffers " + root.metricKib("mem_buffers_kb")
                                                + "   shared " + root.metricKib("mem_shared_kb")
                                                + "   slab " + root.metricKib("mem_slab_kb")
                                            : (root.perfKey === "THERMALS"
                                                ? "whole machine  " + root.metricText("temp_c", 1, " C")
                                                : (root.perfKey === "DISK"
                                                    ? "read " + root.bps(root.n("disk_read_bps"))
                                                        + "   write " + root.bps(root.n("disk_write_bps"))
                                                    : (root.perfKey === "NETWORK"
                                                        ? String(root.status.net_iface || "—")
                                                            + "   ↓ " + root.bps(root.n("net_rx_bps"))
                                                            + "   ↑ " + root.bps(root.n("net_tx_bps"))
                                                        : root.energySource()
                                                            + (Readings.value(root.readingSource("energy_w"), "energy_w") !== null
                                                                ? "   " + root.metricText("energy_w", 1, " W package")
                                                                : "   power --"))))))
                                }
                            }
                        }
                    }
                    }

                    Loader {
                        anchors.fill: parent
                        active: root.page !== "SUMMARY" && root.page !== "PERFORMANCE"
                        visible: active
                        sourceComponent: listPage
                    }

                    Component {
                        id: listPage
                        Item {
                            TmogCard {
                                anchors.fill: parent
                                visible: root.page === "PROCESSES"
                                leftLegend: "PROCESSES"
                                rightLegend: String(root.n("process_count"))
                                    + (
                                        root.n("tombstones") > 0
                                            ? (" · " + String(root.n("tombstones")) + " GONE")
                                            : ""
                                    )
                            Flickable {
                                anchors.fill: parent
                                clip: true
                                boundsBehavior: Flickable.StopAtBounds
                                contentWidth: width
                                contentHeight: procCol.height
                                flickableDirection: Flickable.VerticalFlick
                            Column {
                                id: procCol
                                width: parent.width
                                spacing: 2
                                Row {
                                    width: parent.width
                                    height: 22
                                    Text {
                                        width: Math.max(150, parent.width * 0.32)
                                        text: "NAME" + (root.processSortKey === "name" ? " ↕" : "")
                                        color: root.processSortKey === "name" ? root.ledgerGold : root.muted
                                        font.family: "monospace"
                                        font.pixelSize: 11
                                        MouseArea {
                                            anchors.fill: parent
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: root.toggleProcessSort("name")
                                        }
                                    }
                                    Text {
                                        width: 76
                                        text: "PID"
                                        color: root.muted
                                        font.family: "monospace"
                                        font.pixelSize: 11
                                    }
                                    Text {
                                        width: 96
                                        text: "STATUS"
                                        color: root.muted
                                        font.family: "monospace"
                                        font.pixelSize: 11
                                    }
                                    Text {
                                        width: 110
                                        text: "USER"
                                        color: root.muted
                                        font.family: "monospace"
                                        font.pixelSize: 11
                                    }
                                    Text {
                                        width: 72
                                        text: "CPU" + (root.processSortKey === "cpu_pct" ? " ↕" : "")
                                        color: root.processSortKey === "cpu_pct" ? root.ledgerGold : root.muted
                                        font.family: "monospace"
                                        font.pixelSize: 11
                                        MouseArea {
                                            anchors.fill: parent
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: root.toggleProcessSort("cpu_pct")
                                        }
                                    }
                                    Text {
                                        text: "RSS     THR"
                                        color: root.muted
                                        font.family: "monospace"
                                        font.pixelSize: 11
                                    }
                                }
                                Repeater {
                                    model: root.sortedProcesses()
                                    delegate: TmogRow {
                                        required property var modelData
                                        width: parent.width
                                        selected: Number(modelData.pid) === root.selectedPid
                                        textColor: modelData.tombstone ? "#c98989" : "#c8cdd4"
                                        text: String(modelData.comm || "").padEnd(14, " ").slice(0, 14)
                                            + " " + String(modelData.pid).padStart(6, " ")
                                            + "  " + String(modelData.status || "").padEnd(11, " ").slice(0, 11)
                                            + " " + String(modelData.user || "").padEnd(10, " ").slice(0, 10)
                                            + " " + String(modelData.cpu_pct).padStart(5, " ") + "%"
                                            + " " + root.kib(modelData.rss_kb).padStart(7, " ")
                                            + " " + String(modelData.threads).padStart(4, " ")
                                        onChosen: root.selectedPid = Number(modelData.pid)
                                        onMenuRequested: {
                                            root.selectedPid = Number(modelData.pid)
                                            root.armMenu("proc", modelData)
                                            tmogMenu.popup()
                                        }
                                    }
                                }
                                Text {
                                    width: parent.width
                                    visible: root.selected !== null
                                    text: root.selected
                                        ? "#" + root.selected.pid + "  "
                                            + (root.selected.cmdline || "")
                                        : ""
                                    color: "#c8a97e"
                                    font.family: "monospace"
                                    font.pixelSize: 12
                                    wrapMode: Text.WrapAnywhere
                                }
                            }
                            }
                            }

                            TmogCard {
                                anchors.fill: parent
                                visible: root.page === "SYSTEM"
                                leftLegend: "SYSTEM"
                            Flickable {
                                anchors.fill: parent
                                clip: true
                                boundsBehavior: Flickable.StopAtBounds
                                contentWidth: width
                                contentHeight: sysCol.height
                                flickableDirection: Flickable.VerticalFlick
                            Column {
                                id: sysCol
                                width: parent.width
                            Text {
                                width: parent.width
                                text: "HOST     " + (root.status.hostname || "—")
                                    + "\nOS       " + (root.status.os || "—")
                                    + "\nKERNEL   " + (root.status.kernel || "—")
                                    + "\nCPU      " + (root.status.cpu_model || "—")
                                    + "\nCORES    " + String(root.status.core_count || 0)
                                    + "   " + root.metricText("mhz", 0, "") + " MHz"
                                    + "\nMEM      " + root.kib(root.n("mem_used_kb"))
                                    + " / " + root.kib(root.n("mem_total_kb"))
                                    + "\nLOAD     " + String(root.n("load1"))
                                    + "  " + String(root.n("load5"))
                                    + "  " + String(root.n("load15"))
                                    + "\nTASKS    " + String(root.n("tasks_running"))
                                    + " running / " + String(root.n("process_count"))
                                    + "\nNET      " + String(root.status.net_iface || "—")
                                    + "\nUP       " + root.clock(root.n("uptime_s"))
                                color: "#d8dee9"
                                font.family: "monospace"
                                font.pixelSize: 12
                                wrapMode: Text.WordWrap
                            }
                            }
                            }
                            }

                            TmogCard {
                                anchors.fill: parent
                                visible: root.page === "FLIGHT"
                                leftLegend: "FLIGHT RECORDER"
                                rightLegend: root.rangeLabel()
                                Column {
                                    anchors.fill: parent
                                    spacing: 8
                                    Text {
                                        width: parent.width
                                        text: "Select a CPU or memory history range to inspect the live sample."
                                        color: root.text
                                        font.family: "monospace"
                                        font.pixelSize: 11
                                        wrapMode: Text.WordWrap
                                    }
                                    TmogHistoryGraph {
                                        width: parent.width
                                        height: Math.max(120, parent.height * 0.34)
                                        selectable: true
                                        rangeActive: root.rangeActive
                                        values: root.arr("cpu_hist")
                                        overlayValues: root.arr("mem_hist")
                                        stroke: root.ledgerGreen
                                        overlayStroke: "#b6a6c8"
                                        fill: "#1c2a22"
                                        yMax: 100
                                        rangeStart: root.rangeStart
                                        rangeEnd: root.rangeEnd
                                        onRangeSelected: function(start, end) {
                                            root.rangeStart = start
                                            root.rangeEnd = end
                                            root.rangeActive = true
                                        }
                                    }
                                    Row {
                                        spacing: 16
                                        Text {
                                            text: "CPU " + root.metricText("cpu_busy", 1, "%")
                                            color: root.ledgerGreen
                                            font.family: "monospace"
                                            font.pixelSize: 11
                                        }
                                        Text {
                                            text: "MEM " + root.kib(root.n("mem_used_kb"))
                                            color: "#b6a6c8"
                                            font.family: "monospace"
                                            font.pixelSize: 11
                                        }
                                        Text {
                                            text: "RANGE " + root.rangeLabel()
                                            color: root.ledgerGold
                                            font.family: "monospace"
                                            font.pixelSize: 11
                                        }
                                        Text {
                                            visible: root.rangeActive
                                            text: "CLEAR"
                                            color: root.ledgerGold
                                            font.family: "monospace"
                                            font.pixelSize: 11
                                            MouseArea {
                                                anchors.fill: parent
                                                cursorShape: Qt.PointingHandCursor
                                                onClicked: root.clearRange()
                                            }
                                        }
                                    }
                                    Text {
                                        width: parent.width
                                        text: "PROCESSES ACTIVE IN SELECTED RANGE"
                                        color: root.muted
                                        font.family: "monospace"
                                        font.pixelSize: 10
                                    }
                                    Repeater {
                                        model: root.flightRows()
                                        delegate: TmogRow {
                                            required property var modelData
                                            width: parent.width
                                            text: String(modelData.pid).padStart(7, " ")
                                                + "  " + String(modelData.comm || "")
                                                    .padEnd(24, " ").slice(0, 24)
                                                + "  CPU " + String(modelData.cpu_pct) + "%"
                                                + "  RSS " + root.kib(modelData.rss_kb)
                                            onChosen: root.selectedPid = Number(modelData.pid)
                                            onMenuRequested: {
                                                root.selectedPid = Number(modelData.pid)
                                                root.armMenu("proc", modelData)
                                                tmogMenu.popup()
                                            }
                                        }
                                    }
                                }
                            }

                            TmogCard {
                                anchors.fill: parent
                                visible: root.page === "DRIVERS"
                                leftLegend: "DRIVERS"
                                rightLegend: String(root.arr("drivers").length)
                                Flickable {
                                    anchors.fill: parent
                                    clip: true
                                    boundsBehavior: Flickable.StopAtBounds
                                    contentWidth: width
                                    contentHeight: driverCol.height
                                    flickableDirection: Flickable.VerticalFlick
                                    Column {
                                        id: driverCol
                                        width: parent.width
                                        spacing: 2
                                        Text {
                                            width: parent.width
                                            text: "DRIVER MODULE                         SIZE       USERS"
                                            color: root.muted
                                            font.family: "monospace"
                                            font.pixelSize: 11
                                        }
                                        Repeater {
                                            model: root.arr("drivers")
                                            delegate: TmogRow {
                                                required property var modelData
                                                width: parent.width
                                                text: String(modelData.name || "")
                                                    .padEnd(36, " ").slice(0, 36)
                                                    + "  " + String(modelData.size || "0")
                                                        .padStart(10, " ")
                                                    + "  " + String(modelData.users || "0")
                                                onMenuRequested: {
                                                    root.armMenu("driver", modelData)
                                                    tmogMenu.popup()
                                                }
                                            }
                                        }
                                    }
                                }
                            }

                            TmogCard {
                                anchors.fill: parent
                                visible: root.page === "USERS"
                                leftLegend: "USERS"
                                rightLegend: String(root.arr("users").length)
                            Flickable {
                                anchors.fill: parent
                                clip: true
                                boundsBehavior: Flickable.StopAtBounds
                                contentWidth: width
                                contentHeight: userCol.height
                                flickableDirection: Flickable.VerticalFlick
                            Column {
                                id: userCol
                                width: parent.width
                                spacing: 2
                                Text {
                                    text: "USER            PROCS"
                                    color: "#a8b0b8"
                                    font.family: "monospace"
                                    font.pixelSize: 12
                                }
                                Repeater {
                                    model: root.arr("users")
                                    delegate: TmogRow {
                                        required property var modelData
                                        width: parent.width
                                        text: String(modelData.name || "").padEnd(16, " ")
                                            + "  " + String(modelData.procs)
                                        onMenuRequested: {
                                            root.armMenu("user", modelData)
                                            tmogMenu.popup()
                                        }
                                    }
                                }
                            }
                            }
                            }

                            TmogCard {
                                anchors.fill: parent
                                visible: root.page === "CONNECTIONS"
                                leftLegend: "CONNECTIONS"
                                rightLegend: String(root.arr("connections").length)
                            Flickable {
                                anchors.fill: parent
                                clip: true
                                boundsBehavior: Flickable.StopAtBounds
                                contentWidth: width
                                contentHeight: connCol.height
                                flickableDirection: Flickable.VerticalFlick
                            Column {
                                id: connCol
                                width: parent.width
                                spacing: 2
                                Repeater {
                                    model: root.arr("connections")
                                    delegate: TmogRow {
                                        required property var modelData
                                        width: parent.width
                                        text: String(modelData.state || "").padEnd(11, " ").slice(0, 11)
                                            + "  " + String(modelData.comm || "—").padEnd(12, " ").slice(0, 12)
                                            + "  " + String(modelData.local)
                                            + "  →  " + String(modelData.remote)
                                        onMenuRequested: {
                                            root.armMenu("conn", modelData)
                                            tmogMenu.popup()
                                        }
                                    }
                                }
                            }
                            }
                            }

                            TmogCard {
                                anchors.fill: parent
                                visible: root.page === "DISK"
                                leftLegend: "DISK"
                                lamp: true
                                lampOn: root.diskLampOn
                                rightLegend: root.bps(root.n("disk_read_bps") + root.n("disk_write_bps"))
                            Flickable {
                                anchors.fill: parent
                                clip: true
                                boundsBehavior: Flickable.StopAtBounds
                                contentWidth: width
                                contentHeight: diskCol.height
                                flickableDirection: Flickable.VerticalFlick
                            Column {
                                id: diskCol
                                width: parent.width
                                spacing: 8
                                Rectangle {
                                    width: parent.width
                                    height: 8
                                    color: "#1a1a1a"
                                    radius: 2
                                    Rectangle {
                                        width: Math.max(4, parent.width * Math.min(1, root.n("disk_led")))
                                        height: parent.height
                                        color: root.n("disk_led") > 0.04 ? "#e05050" : "#3a3a3a"
                                        radius: 2
                                    }
                                }
                                Repeater {
                                    model: root.arr("mounts")
                                    delegate: Item {
                                        required property var modelData
                                        width: parent.width
                                        height: 40
                                        Text {
                                            text: String(modelData.path || "")
                                                + "   " + root.kib(Number(modelData.used || 0) / 1024)
                                                + " / " + root.kib(Number(modelData.total || 0) / 1024)
                                                + "   " + String(modelData.fstype || "")
                                            color: "#c8cdd4"
                                            font.family: "monospace"
                                            font.pixelSize: 12
                                            elide: Text.ElideRight
                                            width: parent.width
                                        }
                                        TmogMeter {
                                            anchors.left: parent.left
                                            anchors.right: parent.right
                                            anchors.bottom: parent.bottom
                                            height: 14
                                            ratio: Number(modelData.total)
                                                ? Number(modelData.used) / Number(modelData.total)
                                                : 0
                                            onColor: "#8db89a"
                                        }
                                        MouseArea {
                                            anchors.fill: parent
                                            acceptedButtons: Qt.RightButton
                                            onClicked: {
                                                root.armMenu("mount", modelData)
                                                tmogMenu.popup()
                                            }
                                        }
                                    }
                                }
                            }
                            }
                            }

                            TmogCard {
                                anchors.fill: parent
                                visible: root.page === "FREQ"
                                leftLegend: "FREQ"
                                rightLegend: String(root.arr("cores").length)
                            Flickable {
                                anchors.fill: parent
                                clip: true
                                boundsBehavior: Flickable.StopAtBounds
                                contentWidth: width
                                contentHeight: freqCol.height
                                flickableDirection: Flickable.VerticalFlick
                            Column {
                                id: freqCol
                                width: parent.width
                                spacing: 8
                                Repeater {
                                    model: root.arr("cores")
                                    delegate: Item {
                                        required property var modelData
                                        width: parent.width
                                        height: 28
                                        Text {
                                            text: "CPU " + modelData.id
                                                + "   " + (Readings.metadataAvailable(root.readingSource("mhz"), "mhz")
                                                    ? Readings.text({mhz:modelData.mhz}, "mhz", 0, " MHz") : "--") + "   "
                                                + root.coreText(Number(modelData.id))
                                            color: "#c8cdd4"
                                            font.family: "monospace"
                                            font.pixelSize: 12
                                        }
                                        TmogMeter {
                                            anchors.left: parent.left
                                            anchors.right: parent.right
                                            anchors.bottom: parent.bottom
                                            height: 12
                                            ratio: Math.min(1, Number(modelData.pct || 0) / 100)
                                            onColor: "#8db89a"
                                            segments: 24
                                        }
                                    }
                                }
                            }
                            }
                            }

                            TmogCard {
                                anchors.fill: parent
                                visible: root.page === "STARTUP"
                                leftLegend: "STARTUP"
                                rightLegend: String(root.arr("startup").length)
                            Flickable {
                                anchors.fill: parent
                                clip: true
                                boundsBehavior: Flickable.StopAtBounds
                                contentWidth: width
                                contentHeight: startCol.height
                                flickableDirection: Flickable.VerticalFlick
                            Column {
                                id: startCol
                                width: parent.width
                                spacing: 2
                                Text {
                                    visible: root.arr("startup").length === 0
                                    text: "no autostart entries"
                                    color: "#a8b0b8"
                                    font.family: "monospace"
                                    font.pixelSize: 12
                                }
                                Repeater {
                                    model: root.arr("startup")
                                    delegate: TmogRow {
                                        required property var modelData
                                        width: parent.width
                                        text: String(modelData.name || modelData.id || "")
                                            + (modelData.hidden ? "  hidden" : "")
                                        onMenuRequested: {
                                            root.armMenu("app", modelData)
                                            tmogMenu.popup()
                                        }
                                    }
                                }
                            }
                            }
                            }

                            TmogCard {
                                anchors.fill: parent
                                visible: root.page === "APPS"
                                leftLegend: "APPS"
                                rightLegend: String(root.arr("apps").length)
                            Flickable {
                                anchors.fill: parent
                                clip: true
                                boundsBehavior: Flickable.StopAtBounds
                                contentWidth: width
                                contentHeight: appCol.height
                                flickableDirection: Flickable.VerticalFlick
                            Column {
                                id: appCol
                                width: parent.width
                                spacing: 2
                                Text {
                                    visible: root.arr("apps").length === 0
                                    text: "no desktop applications found"
                                    color: "#a8b0b8"
                                    font.family: "monospace"
                                    font.pixelSize: 12
                                }
                                Repeater {
                                    model: root.arr("apps")
                                    delegate: TmogRow {
                                        required property var modelData
                                        width: parent.width
                                        text: String(modelData.name || modelData.id || "")
                                        onMenuRequested: {
                                            root.armMenu("app", modelData)
                                            tmogMenu.popup()
                                        }
                                    }
                                }
                            }
                            }
                            }

                            TmogCard {
                                anchors.fill: parent
                                visible: root.page === "BENCHMARKS"
                                leftLegend: "BENCHMARKS"
                                rightLegend: "BETA 3"
                                Column {
                                    anchors.fill: parent
                                    spacing: 10
                                    Text {
                                        width: parent.width
                                        text: "LIVE HARDWARE BASELINE"
                                        color: root.ledgerGold
                                        font.family: "monospace"
                                        font.pixelSize: 11
                                        font.bold: true
                                    }
                                    Text {
                                        width: parent.width
                                        text: (root.status.cpu_model || "CPU") + "\n"
                                            + String(root.status.core_count || 0) + " logical cores · "
                                            + root.metricText("mhz", 0, "") + " MHz\n"
                                            + "memory " + root.kib(root.n("mem_used_kb"))
                                            + " / " + root.kib(root.n("mem_total_kb"))
                                        color: root.text
                                        font.family: "monospace"
                                        font.pixelSize: 12
                                        wrapMode: Text.WordWrap
                                    }
                                    TmogMeter {
                                        width: parent.width
                                        height: 14
                                        ratio: root.n("cpu_busy") / 100
                                        onColor: root.ledgerGreen
                                        segments: 30
                                    }
                                    Text {
                                        width: parent.width
                                        text: "CPU " + root.metricText("cpu_busy", 1, "%") + "  ·  "
                                            + "TEMP " + root.metricText("temp_c", 1, " C") + "  ·  "
                                            + "GPU " + root.metricText("gpu_busy", 1, "%")
                                        color: root.muted
                                        font.family: "monospace"
                                        font.pixelSize: 11
                                    }
                                    Rectangle {
                                        width: Math.min(parent.width, 200)
                                        height: 28
                                        color: "#1a2820"
                                        border.color: "#486553"
                                        border.width: 1
                                        radius: 3
                                        Text {
                                            anchors.centerIn: parent
                                            text: "OPEN FULL TMOG BENCHMARKS"
                                            color: root.ledgerGreen
                                            font.family: "monospace"
                                            font.pixelSize: 10
                                        }
                                        MouseArea {
                                            anchors.fill: parent
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: root.openFullTmog()
                                        }
                                    }
                                }
                            }

                            TmogCard {
                                anchors.fill: parent
                                visible: root.page === "SERVICES"
                                leftLegend: "SERVICES"
                                rightLegend: String(root.arr("services").length) + " running"
                            Flickable {
                                anchors.fill: parent
                                clip: true
                                boundsBehavior: Flickable.StopAtBounds
                                contentWidth: width
                                contentHeight: svcCol.height
                                flickableDirection: Flickable.VerticalFlick
                            Column {
                                id: svcCol
                                width: parent.width
                                spacing: 2
                                Text {
                                    visible: root.arr("services").length === 0
                                    text: "no running units in cgroup"
                                    color: "#a8b0b8"
                                    font.family: "monospace"
                                    font.pixelSize: 12
                                }
                                Repeater {
                                    model: root.arr("services")
                                    delegate: TmogRow {
                                        required property var modelData
                                        width: parent.width
                                        text: String(modelData.scope || "").padEnd(7, " ")
                                            + "  " + String(modelData.state || "").padEnd(8, " ")
                                            + "  " + root.shortName(modelData.name || modelData.id || "")
                                        onMenuRequested: {
                                            root.armMenu("svc", modelData)
                                            tmogMenu.popup()
                                        }
                                    }
                                }
                            }
                            }
                        }
                    }
                }
            }
        }

    Menu {
        id: tmogMenu
        padding: 4
        overlap: 0
        font.family: "monospace"
        font.pixelSize: 12
        background: Rectangle {
            color: "#161616"
            border.width: 1
            border.color: "#6a6a6a"
            radius: 2
            implicitWidth: 168
        }
        delegate: MenuItem {
            id: item
            visible: true
            implicitHeight: item.visible ? 24 : 0
            leftPadding: 10
            rightPadding: 10
            font.family: "monospace"
            font.pixelSize: 12
            contentItem: Text {
                text: item.text
                font.family: "monospace"
                font.pixelSize: 12
                color: item.highlighted ? "#e6e6e6" : "#c8cdd4"
                verticalAlignment: Text.AlignVCenter
            }
            background: Rectangle {
                color: item.highlighted ? "#1c1c1c" : "transparent"
                radius: 1
            }
        }
        MenuItem {
            text: "Copy PID"
            visible: root.menuKind === "proc"
            height: visible ? implicitHeight : 0
            onTriggered: root.copyText(String(root.menuRow.pid || ""))
        }
        MenuItem {
            text: "Copy name"
            visible: root.menuKind === "proc" || root.menuKind === "app"
                || root.menuKind === "svc" || root.menuKind === "user"
                || root.menuKind === "driver"
            height: visible ? implicitHeight : 0
            onTriggered: root.copyText(root.rowLabel(root.menuRow))
        }
        MenuItem {
            text: "Copy command"
            visible: root.menuKind === "proc"
            height: visible ? implicitHeight : 0
            onTriggered: root.copyText(String(root.menuRow.cmdline || root.menuRow.comm || ""))
        }
        MenuItem {
            text: "Copy local"
            visible: root.menuKind === "conn"
            height: visible ? implicitHeight : 0
            onTriggered: root.copyText(String(root.menuRow.local || ""))
        }
        MenuItem {
            text: "Copy remote"
            visible: root.menuKind === "conn"
            height: visible ? implicitHeight : 0
            onTriggered: root.copyText(String(root.menuRow.remote || ""))
        }
        MenuItem {
            text: "Copy path"
            visible: root.menuKind === "mount" || root.menuKind === "app"
            height: visible ? implicitHeight : 0
            onTriggered: root.copyText(String(root.menuRow.path || root.menuRow.src || ""))
        }
        MenuItem {
            text: "Copy id"
            visible: root.menuKind === "svc" || root.menuKind === "app"
            height: visible ? implicitHeight : 0
            onTriggered: root.copyText(String(root.menuRow.id || ""))
        }
    }

    Item {
        id: hole
        objectName: "workspaceTmogHole"
        enabled: false
        anchors.fill: parent
        anchors.margins: 12
        anchors.topMargin: 86
        anchors.bottomMargin: 18
    }
}
