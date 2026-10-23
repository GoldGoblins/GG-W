import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    objectName: "workspaceOsintPane"
    signal researchRequested(string section)

    property var surfaceHost: null
    property color frameBorder: "#4a4a4a"
    property int frameRadius: 4
    readonly property color ink: "#e6edf3"
    readonly property color text: "#c8cdd4"
    readonly property color muted: "#7f8993"
    readonly property color panel: "#181818"
    readonly property color panelRaised: "#202020"
    readonly property color selectedPanel: "#34383d"
    readonly property color ledgerGold: "#c8a97e"
    readonly property color ledgerGreen: "#8db89a"
    readonly property color signalBlue: "#7fa9c4"
    readonly property color signalRed: "#c98989"
    readonly property color signalViolet: "#b6a6c8"
    property string statusJson: "{}"
    property string page: "OVERVIEW"
    property bool sidebarCollapsed: false
    property bool fetchBusy: false
    property string streamMode: "NEWS"
    property bool nearbyEnabled: false
    property var nearbyPayload: ({status: "PAUSED", rows: [], sources: []})
    readonly property bool nearbyActive: root.nearbyEnabled && root.visible && overviewGlobe.visible && overviewGlobe.mapReady
        && ((root.navMode && overviewGlobe.savedRoute.length > 0)
            || (overviewGlobe.savedView && Number(overviewGlobe.savedView.zoom) >= 15))
    property var payload: ({})
    property var selectedEvent: null
    property bool navMode: false
    property string navDraft: ""
    property var navPlaces: []
    property string navMeta: ""
    property real lastViewportQueryAt: 0
    property string lastViewportKey: ""
    property string evidenceNotice: ""

    readonly property var nav: [
        "OVERVIEW",
        "MAP",
        "FLIGHTS",
        "SEISMIC",
        "FIRES",
        "SPACE",
        "NEWS",
        "CONFLICT",
        "CAMERAS",
        "SOURCES",
        "RECON"
    ]

    function applyRaw(raw) {
        if (!raw)
            return
        try {
            var parsed = JSON.parse(String(raw))
            root.statusJson = String(raw)
            root.payload = parsed
            if (parsed.fetching !== undefined)
                root.fetchBusy = !!parsed.fetching
            if (root.selectedEvent && root.selectedEvent.id) {
                var rebound = root.findById(String(root.selectedEvent.id))
                if (rebound)
                    root.selectedEvent = root.mergeKeep(root.selectedEvent, rebound)
            }
        } catch (err) {
            root.fetchBusy = false
        }
    }

    function refresh() {
        if (!root.surfaceHost)
            return
        root.lastViewportKey = ""
        if (root.surfaceHost.osintSnapshot)
            root.applyRaw(root.surfaceHost.osintSnapshot(root.page))
        if (root.surfaceHost.osintRefresh) {
            var queued = root.surfaceHost.osintRefresh(root.page)
            if (queued)
                root.fetchBusy = true
        }
    }

    function viewportKey(view) {
        if (!view)
            return ""
        var bounds = view.bounds || []
        function q(value) { return Number(value || 0).toFixed(3) }
        return [q(view.lng), q(view.lat), q(view.zoom), q(view.bearing), q(view.pitch), JSON.stringify(bounds)].join("|")
    }

    function refreshViewport(view) {
        if (!root.surfaceHost || !root.surfaceHost.osintViewportSnapshot)
            return
        var now = Date.now()
        if (now - root.lastViewportQueryAt < 220)
            return
        var key = root.viewportKey(view)
        if (!key || key === root.lastViewportKey)
            return
        root.lastViewportQueryAt = now
        root.lastViewportKey = key
        root.applyRaw(root.surfaceHost.osintViewportSnapshot(JSON.stringify(view || {})))
    }

    function rows(name) {
        var value = root.payload[name]
        return value && value.length !== undefined ? value : []
    }

    function count(name) {
        var counts = root.payload.counts || {}
        return Number(counts[name] || 0)
    }

    function renderedPointCount() {
        var counts = root.payload.render_counts || {}
        var total = 0
        for (var key in counts)
            total += Number(counts[key] || 0)
        return total
    }

    function history(name) {
        var values = (root.payload.histories || {})[name]
        return values && values.length !== undefined && values.length
            ? values
            : [0]
    }

    function navLabel(value) {
        var labels = {
            "OVERVIEW": "Overview",
            "MAP": "Event Map",
            "FLIGHTS": "Flights",
            "SEISMIC": "Seismic",
            "FIRES": "Fires",
            "SPACE": "Space Weather",
            "NEWS": "News",
            "CONFLICT": "Conflict watch",
            "CAMERAS": "Cameras",
            "SOURCES": "Sources",
            "RECON": "Recon boundary"
        }
        return labels[String(value || "")] || String(value || "")
    }

    function navIcon(value) {
        var icons = {
            "OVERVIEW": "⌂",
            "MAP": "◎",
            "FLIGHTS": "✈",
            "SEISMIC": "∿",
            "FIRES": "◆",
            "SPACE": "✦",
            "NEWS": "▤",
            "CONFLICT": "◇",
            "CAMERAS": "▣",
            "SOURCES": "▦",
            "RECON": "⌁"
        }
        return icons[String(value || "")] || "·"
    }

    function number(value, decimals) {
        var n = Number(value)
        if (!isFinite(n))
            return "—"
        return n.toFixed(decimals === undefined ? 0 : decimals)
    }

    function shortTime(value) {
        var s = String(value || "")
        if (!s)
            return "—"
        if (s.indexOf("T") >= 0)
            return s.replace("T", " ").replace("Z", "").slice(0, 16) + (s.endsWith("Z") ? " UTC" : "")
        return s.slice(0, 24)
    }

    function statusText() {
        if (root.fetchBusy)
            return "FETCHING"
        return String(root.payload.status || "READY")
    }

    function statusColor() {
        var value = statusText()
        if (value === "LIVE")
            return root.ledgerGreen
        if (value === "DEGRADED")
            return root.ledgerGold
        if (value === "OFFLINE")
            return root.signalRed
        if (value === "FETCHING")
            return root.signalBlue
        return root.muted
    }

    function markerColor(kind) {
        if (kind === "aircraft")
            return root.signalBlue
        if (kind === "earthquakes")
            return root.ledgerGold
        if (kind === "fires")
            return root.signalRed
        if (kind === "conflicts")
            return root.signalViolet
        if (kind === "cameras")
            return "#6ec4d8"
        if (kind === "gdelt" || kind === "news")
            return "#7fa9c4"
        return root.text
    }

    function mapPoints() {
        var result = []
        function add(items, kind, limit) {
            var values = items || []
            var cap = Math.min(values.length, limit)
            for (var i = 0; i < cap; i++) {
                var item = values[i] || {}
                if (item.lat === undefined || item.lon === undefined)
                    continue
                result.push({
                    id: String(item.id || item.callsign || item.title || item.label || kind),
                    lat: Number(item.lat),
                    lon: Number(item.lon),
                    kind: kind,
                    label: String(item.callsign || item.place || item.title || item.label || kind),
                    callsign: String(item.callsign || ""),
                    country: String(item.country || ""),
                    color: root.markerColor(kind),
                    heading: Number(item.heading || 0),
                    speed_mps: Number(item.speed_mps || 0),
                    alt_m: Number(item.alt_m || 0),
                    on_ground: Boolean(item.on_ground),
                    squawk: String(item.squawk || ""),
                    magnitude: Number(item.magnitude || 0),
                    severity: Number(item.severity || 0),
                    camera_count: Number(item.camera_count || 0),
                    aircraft_count: Number(item.aircraft_count || 0),
                    event_count: Number(item.event_count || 0),
                    cluster_count: Number(item.cluster_count || 0),
                    cluster: Boolean(item.cluster),
                    summary: String(item.summary || item.category || item.zone || item.city || ""),
                    place: String(item.place || item.city || ""),
                    source: String(item.source || kind),
                    location_precision: String(item.location_precision || ""),
                    url: String(item.url || ""),
                    photo: String(item.photo || item.media_url || item.feed_url || ""),
                    city: String(item.city || ""),
                    country: String(item.country || ""),
                    live_video: Boolean(item.live_video),
                    media_kind: String(item.media_kind || ""),
                    availability: String(item.availability || "")
                })
            }
        }
        add(root.rows("aircraft"), "aircraft", 10000)
        add(root.rows("earthquakes"), "earthquakes", 80)
        add(root.rows("fires"), "fires", 80)
        add(root.rows("conflicts"), "conflicts", 40)
        add(root.rows("gdelt"), "gdelt", 1200)
        add(root.rows("news"), "news", 1000)
        add(root.rows("cameras"), "cameras", 2500)
        return result
    }

    function streamRows() {
        if (root.streamMode === "SIGNALS")
            return root.payload.stream || []
        var values = root.payload.news_stream || root.rows("news")
        if (root.streamMode === "SVENSKA")
            return values.filter(function(row) { return row.language === "sv" })
        return values
    }

    function mergeKeep(base, next) {
        var out = {}
        var key
        if (base) {
            for (key in base)
                out[key] = base[key]
        }
        if (next) {
            for (key in next) {
                if (next[key] !== undefined && next[key] !== null && next[key] !== "")
                    out[key] = next[key]
            }
        }
        return out
    }

    function asEvent(item, kind) {
        if (!item)
            return null
        var k = String(item.kind || kind || "event")
        var title = String(item.title || item.callsign || item.place || item.label || k)
        return root.mergeKeep({
            "id": String(item.id || item.callsign || title),
            "kind": k,
            "title": title,
            "callsign": String(item.callsign || ""),
            "country": String(item.country || ""),
            "summary": String(item.summary || item.description || item.category || item.zone || ""),
            "source": String(item.source || k).toUpperCase(),
            "time": String(item.time || item.published || item.last_contact || ""),
            "url": String(item.url || ""),
            "photo": String(item.photo || ""),
            "lat": item.lat,
            "lon": item.lon,
            "alt_m": item.alt_m,
            "speed_mps": item.speed_mps,
            "heading": item.heading,
            "squawk": item.squawk,
            "on_ground": item.on_ground,
            "vert_rate_mps": item.vert_rate_mps,
            "magnitude": item.magnitude,
            "depth_km": item.depth_km,
            "camera_count": item.camera_count,
            "media_kind": item.media_kind,
            "availability": item.availability,
            "place": item.place,
            "route": item.route,
            "airline": item.airline,
            "type": item.type,
            "registration": item.registration,
            "owner": item.owner,
            "origin": item.origin,
            "destination": item.destination
        }, item)
    }

    function findById(id) {
        var wanted = String(id || "")
        if (!wanted)
            return null
        var names = ["aircraft", "earthquakes", "fires", "conflicts", "news", "gdelt", "cameras"]
        for (var n = 0; n < names.length; n++) {
            var rows = root.rows(names[n])
            for (var i = 0; i < rows.length; i++) {
                if (String(rows[i].id || "") === wanted)
                    return root.asEvent(rows[i], names[n])
            }
        }
        var stream = root.streamRows()
        for (var s = 0; s < stream.length; s++) {
            if (String(stream[s].id || "") === wanted)
                return root.asEvent(stream[s], stream[s].kind)
        }
        return null
    }

    function selectEvent(item, fly) {
        var event = root.asEvent(item, item && item.kind)
        if (!event)
            return
        root.navMode = false
        overviewGlobe.setNavOpen(false)
        root.selectedEvent = event
        if (fly && event.lat !== undefined && event.lon !== undefined)
            overviewGlobe.focusPoint(event.lat, event.lon, event.kind === "aircraft" ? 6.2 : 5.4)
        overviewGlobe.showPopup(event)
        if (event.kind === "aircraft")
            root.enrichFlight(event)
        root.saveUi()
    }

    function focusGlobe(item) {
        root.selectEvent(item, true)
    }

    function enrichFlight(item) {
        if (!item || !root.surfaceHost || !root.surfaceHost.osintLookupFlight)
            return
        var raw = root.surfaceHost.osintLookupFlight(
            String(item.callsign || ""),
            String(item.id || "")
        )
        root.mergeFlight(raw)
    }

    function mergeFlight(raw) {
        if (!raw || !root.selectedEvent)
            return
        var extra = {}
        try {
            extra = JSON.parse(String(raw))
        } catch (err) {
            return
        }
        if (!extra || !extra.ok)
            return
        var cur = root.selectedEvent
        var sameCall = extra.callsign && String(extra.callsign) === String(cur.callsign || "")
        var sameIcao = extra.icao24 && String(extra.icao24) === String(cur.id || "")
        if (!sameCall && !sameIcao)
            return
        root.selectedEvent = root.mergeKeep(cur, extra)
        overviewGlobe.showPopup(root.selectedEvent)
    }

    function knots(mps) {
        var n = Number(mps)
        if (!isFinite(n))
            return "—"
        return Math.round(n * 1.94384) + " kt"
    }

    function flightLevel(meters) {
        var n = Number(meters)
        if (!isFinite(n) || n <= 0)
            return "—"
        return "FL " + Math.round(n / 30.48)
    }

    function airportLabel(row) {
        if (!row)
            return ""
        if (typeof row === "string")
            return row
        return String(row.label || row.iata || row.icao || row.name || "")
    }

    function eventFacts(item) {
        if (!item)
            return []
        var lines = []
        if (item.location_precision === "PLACE_NAME_ESTIMATE")
            lines.push("ESTIMATED PLACE FROM HEADLINE · NOT EXACT EVENT COORDINATES")
        if (item.kind === "conflicts")
            lines.push("REFERENCE LOCATION · NOT A VERIFIED LIVE INCIDENT")
        if (item.kind === "aircraft") {
            lines.push((item.on_ground ? "GROUND" : "AIRBORNE")
                + (item.country ? " · " + item.country : ""))
            lines.push(root.flightLevel(item.alt_m)
                + " · " + root.number(item.alt_m) + " m"
                + " · " + root.knots(item.speed_mps)
                + " · HDG " + root.number(item.heading))
            if (item.squawk)
                lines.push("SQUAWK " + String(item.squawk))
            if (item.route)
                lines.push(String(item.route))
            else if (root.airportLabel(item.origin) || root.airportLabel(item.destination))
                lines.push(root.airportLabel(item.origin) + " → " + root.airportLabel(item.destination))
            if (item.airline)
                lines.push(String(item.airline))
            var airframe = String(item.type || "")
            if (airframe === "aircraft" || airframe === "alpr" || airframe === "earthquake")
                airframe = ""
            if (airframe || item.registration)
                lines.push([airframe, item.registration].filter(function(v) { return v }).join(" · "))
            if (item.owner)
                lines.push(String(item.owner))
        } else if (item.kind === "earthquakes") {
            lines.push("M" + root.number(item.magnitude, 1)
                + (item.depth_km !== undefined ? " · " + root.number(item.depth_km, 0) + " km depth" : ""))
            if (item.place)
                lines.push(String(item.place))
        } else if (item.kind === "fires") {
            if (item.summary)
                lines.push(String(item.summary))
        } else if (item.kind === "cameras") {
            if (item.media_kind)
                lines.push(String(item.media_kind).replace(/_/g, " ") + " · " + String(item.source || "CCTV").toUpperCase())
            else if (item.live_video || item.photo || item.media_url)
                lines.push("PUBLIC SNAPSHOT · " + String(item.source || "CCTV").toUpperCase())
            else
                lines.push("LOCATION PIN · NO LIVE VIDEO")
            if (item.city || item.country)
                lines.push([item.city, item.country].filter(function(v) { return v }).join(" · "))
        }
        if (item.lat !== undefined)
            lines.push(root.number(item.lat, 2) + ", " + root.number(item.lon, 2))
        return lines
    }

    function uiPayload() {
        var route = null
        try {
            if (overviewGlobe.savedRoute)
                route = JSON.parse(overviewGlobe.savedRoute)
        } catch (err) {
            route = null
        }
        return JSON.stringify({
            "page": root.page,
            "navMode": root.navMode,
            "navPlaces": root.navPlaces,
            "navDraft": root.navDraft,
            "navMeta": root.navMeta,
            "route": route,
            "selected": root.selectedEvent,
            "view": overviewGlobe.savedView,
            "sidebarCollapsed": root.sidebarCollapsed,
            "streamMode": root.streamMode
        })
    }

    function saveUi() {
        if (root.surfaceHost && root.surfaceHost.osintSaveUi)
            root.surfaceHost.osintSaveUi(root.uiPayload())
    }

    function restoreUi() {
        if (!root.surfaceHost || !root.surfaceHost.osintLoadUi)
            return
        var parsed = {}
        try {
            parsed = JSON.parse(String(root.surfaceHost.osintLoadUi() || "{}"))
        } catch (err) {
            parsed = {}
        }
        if (!parsed || typeof parsed !== "object")
            return
        if (root.nav.indexOf(String(parsed.page || "")) >= 0)
            root.page = String(parsed.page)
        if (parsed.navPlaces && parsed.navPlaces.length !== undefined)
            root.navPlaces = parsed.navPlaces
        if (parsed.navDraft !== undefined)
            root.navDraft = String(parsed.navDraft || "")
        if (parsed.navMeta !== undefined)
            root.navMeta = String(parsed.navMeta || "")
        if (parsed.sidebarCollapsed !== undefined)
            root.sidebarCollapsed = Boolean(parsed.sidebarCollapsed)
        if (["NEWS", "SVENSKA", "SIGNALS"].indexOf(parsed.streamMode) >= 0)
            root.streamMode = parsed.streamMode
        if (parsed.view)
            overviewGlobe.savedView = parsed.view
        if (parsed.route) {
            var routeRaw = JSON.stringify(parsed.route)
            overviewGlobe.savedRoute = routeRaw
            overviewGlobe.applyRoute(routeRaw)
        }
        if (parsed.selected)
            root.selectedEvent = parsed.selected
        if (parsed.navMode) {
            root.navMode = true
            overviewGlobe.setNavOpen(true)
        } else if (parsed.selected) {
            overviewGlobe.showPopup(parsed.selected)
        }
    }

    function openNav() {
        root.navMode = true
        root.selectedEvent = null
        overviewGlobe.setNavOpen(true)
    }

    function commitNavPlace() {
        var place = String(root.navDraft || "").trim()
        if (!place)
            return false
        if (root.navPlaces.length >= 26)
            return false
        var next = root.navPlaces.slice()
        if (next.length >= 2)
            next.splice(next.length - 1, 0, place)
        else
            next.push(place)
        root.navPlaces = next
        root.navDraft = ""
        return true
    }

    function removeNavPlace(index) {
        var next = []
        for (var i = 0; i < root.navPlaces.length; i++) {
            if (i !== index)
                next.push(root.navPlaces[i])
        }
        root.navPlaces = next
    }

    function moveNavPlace(fromIndex, toIndex) {
        var from = Number(fromIndex)
        var to = Number(toIndex)
        if (from === to || from < 0 || to < 0)
            return
        if (from >= root.navPlaces.length || to >= root.navPlaces.length)
            return
        var next = root.navPlaces.slice()
        var item = next.splice(from, 1)[0]
        next.splice(to, 0, item)
        root.navPlaces = next
    }

    function runNavRoute() {
        root.commitNavPlace()
        if (root.navPlaces.length < 2) {
            root.navMeta = "Add at least two places, then ROUTE."
            return
        }
        var places = root.navPlaces
        var gps = null
        if (String(places[0]).toLowerCase() === "gps") {
            if (!overviewGlobe.positionState.fresh || !overviewGlobe.gpsFix) {
                root.navMeta = "Aktivera POSITION och invänta en aktuell position."
                overviewGlobe.locateGps()
                return
            }
            gps = overviewGlobe.gpsFix
        }
        root.navMeta = "ROUTING…"
        var raw = "{}"
        if (root.surfaceHost && root.surfaceHost.osintPlanRoute)
            raw = root.surfaceHost.osintPlanRoute(JSON.stringify({
                "places": places,
                "gps": gps
            }))
        var result = {}
        try {
            result = JSON.parse(String(raw || "{}"))
        } catch (err) {
            result = {}
        }
        if (!result.ok) {
            root.navMeta = String(result.error || "Routing unavailable.")
            return
        }
        var km = (Number(result.distance_m || 0) / 1000).toFixed(1)
        var min = Math.round(Number(result.duration_s || 0) / 60)
        root.navMeta = km + " km · " + min + " min · " + places.length + " places"
        overviewGlobe.applyRoute(raw)
        overviewGlobe.savedRoute = raw
        root.saveUi()
    }

    function clearNav() {
        root.navDraft = ""
        root.navPlaces = []
        root.navMeta = ""
        overviewGlobe.clearRoute()
        overviewGlobe.savedRoute = ""
        root.saveUi()
    }

    function paintMap(ctx, width, height) {
        ctx.clearRect(0, 0, width, height)
        ctx.fillStyle = "#111315"
        ctx.fillRect(0, 0, width, height)
        ctx.strokeStyle = "#25292d"
        ctx.lineWidth = 1
        for (var longitude = -180; longitude <= 180; longitude += 30) {
            var gx = (longitude + 180) / 360 * width
            ctx.beginPath()
            ctx.moveTo(gx, 0)
            ctx.lineTo(gx, height)
            ctx.stroke()
        }
        for (var latitude = -60; latitude <= 90; latitude += 30) {
            var gy = (90 - latitude) / 180 * height
            ctx.beginPath()
            ctx.moveTo(0, gy)
            ctx.lineTo(width, gy)
            ctx.stroke()
        }
        ctx.strokeStyle = "#394047"
        ctx.beginPath()
        ctx.moveTo(width / 2, 0)
        ctx.lineTo(width / 2, height)
        ctx.moveTo(0, height / 2)
        ctx.lineTo(width, height / 2)
        ctx.stroke()

        var points = root.mapPoints()
        for (var i = 0; i < points.length; i++) {
            var point = points[i]
            var x = (point.lon + 180) / 360 * width
            var y = (90 - point.lat) / 180 * height
            if (x < -8 || x > width + 8 || y < -8 || y > height + 8)
                continue
            var radius = point.kind === "conflicts" ? 4 : 2.5
            ctx.globalAlpha = point.kind === "conflicts" ? 0.75 : 0.88
            ctx.fillStyle = point.color
            ctx.beginPath()
            ctx.arc(x, y, radius, 0, Math.PI * 2)
            ctx.fill()
            if (point.kind === "conflicts") {
                ctx.globalAlpha = 0.22
                ctx.beginPath()
                ctx.arc(x, y, 10, 0, Math.PI * 2)
                ctx.strokeStyle = point.color
                ctx.stroke()
            }
        }
        ctx.globalAlpha = 1
        ctx.fillStyle = "#6c757d"
        ctx.font = "10px monospace"
        ctx.fillText("90N", 6, 12)
        ctx.fillText("0", 6, height / 2 - 4)
        ctx.fillText("60S", 6, height - 6)
        ctx.fillText("GLOBAL PUBLIC FEEDS · POINTS ONLY", 14, height - 8)
    }

    function copyText(value) {
        if (root.surfaceHost && root.surfaceHost.osintCopy)
            root.surfaceHost.osintCopy(String(value || ""))
    }

    function saveEvidence() {
        if (!root.selectedEvent || !root.surfaceHost || !root.surfaceHost.osintRecordEvidence)
            return
        try {
            var result = JSON.parse(root.surfaceHost.osintRecordEvidence(
                String(root.selectedEvent.kind || ""), String(root.selectedEvent.id || "")))
            if (result.status === "EVIDENCE_RECORDED") {
                root.evidenceNotice = "Saved in Research · source report, awaiting corroboration"
                root.researchRequested("EVIDENCE")
            } else {
                root.evidenceNotice = result.status === "OBSERVATION_NOT_FOUND"
                    ? "Observation no longer in cache. Refresh and select it again."
                    : "Could not save observation. Try again."
            }
        } catch (err) {
            root.evidenceNotice = "Could not save observation. Try again."
        }
    }

    function sourceHealthText(source) {
        var age = source.age_seconds
        var ageText = age === undefined || age === null ? "age unknown"
            : (Number(age) < 60 ? Math.round(Number(age)) + "s old"
                : Math.floor(Number(age) / 60) + "m old")
        return String(source.status || "IDLE") + " · " + String(source.count || 0)
            + " rows · " + (source.status === "REFERENCE" ? "reference layer" : ageText)
    }

    onNearbyActiveChanged: {
        if (root.surfaceHost && root.surfaceHost.osintSetNearbyActive)
            root.surfaceHost.osintSetNearbyActive(root.nearbyActive)
        if (!root.nearbyActive)
            root.nearbyPayload = {status: "PAUSED", rows: [], sources: []}
    }
    Timer {
        interval: 5000
        repeat: true
        running: root.nearbyActive
        onTriggered: {
            if (root.surfaceHost && root.surfaceHost.osintNearbySnapshot) {
                try { root.nearbyPayload = JSON.parse(root.surfaceHost.osintNearbySnapshot()) } catch (err) { }
            }
        }
    }
    function positionLabel() {
        var state = overviewGlobe.positionState || {}
        var fix = state.fix
        return String(state.status || "POSITION OFF")
            + (fix ? " · ±" + Math.round(Number(fix.accuracy_m)) + " m" : "")
            + (fix && !state.fresh ? " · SENASTE POSITION" : "")
    }
    function navigationLabel() {
        var progress = overviewGlobe.positionState.progress
        if (!progress)
            return root.positionLabel()
        if (progress.approximate)
            return "Positionen är för ungefärlig för svänganvisningar"
        if (progress.off_route)
            return "Utanför rutten · välj ROUTE för att planera om"
        if (progress.arrived)
            return "Framme vid målet"
        var next = progress.next_step
        var modifiers = {left: "vänster", right: "höger", "slight left": "svagt vänster", "slight right": "svagt höger", "sharp left": "skarpt vänster", "sharp right": "skarpt höger", straight: "rakt fram", uturn: "vänd"}
        var instruction = next ? (next.type === "arrive" ? "Framme"
            : next.type === "roundabout" || next.type === "rotary" ? "Rondell · avfart " + String(next.exit || "—")
            : next.modifier === "uturn" ? "Vänd"
            : next.type === "turn" || next.type === "end of road" ? "Sväng " + String(modifiers[next.modifier] || next.modifier || "")
            : "Fortsätt " + String(modifiers[next.modifier] || next.modifier || "rakt fram")) : "Följ rutten"
        return instruction + (next ? " om " + Math.round(progress.next_step_m) + " m" + (next.name ? " · " + next.name : "") : "")
            + "\n" + (Number(progress.remaining_m) / 1000).toFixed(1) + " km kvar · ca " + Math.round(Number(progress.eta_s) / 60) + " min"
    }
    onStreamModeChanged: root.saveUi()

    onPageChanged: {
        if (root.visible)
            root.refresh()
        root.saveUi()
    }

    onVisibleChanged: {
        if (visible)
            root.refresh()
        else
            root.saveUi()
    }

    Connections {
        target: root.surfaceHost
        ignoreUnknownSignals: true
        function onOsintNearbyUpdated(raw) {
            if (!root.nearbyActive)
                return
            try { root.nearbyPayload = JSON.parse(String(raw)) } catch (err) { }
        }
        function onOsintUpdated(raw) {
            root.applyRaw(raw)
        }
        function onOsintFlightLookedUp(raw) {
            root.mergeFlight(raw)
        }
    }

    Connections {
        target: overviewGlobe
        ignoreUnknownSignals: true
        function onNavOpenChanged() {
            if (overviewGlobe.navOpen)
                root.openNav()
            else if (!root.selectedEvent)
                root.navMode = false
        }
        function onLastPickChanged() {
            if (overviewGlobe.lastPick && !root.navMode)
                root.selectEvent(overviewGlobe.lastPick, false)
        }
        function onRouteMetaChanged() {
            if (overviewGlobe.routeMeta)
                root.navMeta = overviewGlobe.routeMeta
        }

        function onMapReadyChanged() {
            if (!overviewGlobe.mapReady)
                return
            if (overviewGlobe.savedRoute)
                overviewGlobe.applyRoute(overviewGlobe.savedRoute)
            if (root.selectedEvent && !root.navMode)
                overviewGlobe.showPopup(root.selectedEvent)
        }
    }

    Timer {
        interval: 90000
        repeat: true
        running: root.visible
        onTriggered: root.refresh()
    }

    Component.onCompleted: {
        root.restoreUi()
        root.refresh()
    }
    Component.onDestruction: {
        if (root.surfaceHost && root.surfaceHost.osintSetNearbyActive)
            root.surfaceHost.osintSetNearbyActive(false)
        root.saveUi()
    }

    OsintGlobe {
        id: overviewGlobe
        visible: true
        anchors.fill: parent
        z: 0
        points: root.mapPoints()
        catalogCounts: root.payload.catalog_counts || root.payload.counts || ({})
        muted: root.muted
        signalBlue: root.signalBlue
        ledgerGold: root.ledgerGold
        panel: "#05070c"
        onViewportChanged: function(view) { root.refreshViewport(view) }
    }

    Rectangle {
        id: sidebar
        z: 3
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: root.sidebarCollapsed ? 44 : 168
        color: "#e605070c"
        border.width: 0

        Behavior on width {
            NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
        }

        Flickable {
            id: navScroll
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: sidebarFooter.top
            anchors.margins: 10
            clip: true
            contentWidth: width
            contentHeight: navColumn.height
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: GgScrollBar { }

            Column {
                id: navColumn
                width: navScroll.width
                spacing: 3

            Item {
                width: navColumn.width
                height: 30
                Text {
                    anchors.centerIn: parent
                    text: "☰"
                    color: root.ink
                    font.family: "monospace"
                    font.pixelSize: 19
                }
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.sidebarCollapsed = !root.sidebarCollapsed
                }
            }

            Repeater {
                model: root.nav
                delegate: Item {
                    required property string modelData
                    width: navColumn.width
                    height: 29
                    Rectangle {
                        anchors.fill: parent
                        radius: 3
                        color: root.page === modelData
                            ? root.selectedPanel
                            : (navHit.containsMouse ? "#2a2a2a" : "transparent")
                    }
                    Text {
                        visible: !root.sidebarCollapsed
                        anchors.left: parent.left
                        anchors.leftMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        text: root.navIcon(modelData)
                        color: root.page === modelData ? root.ledgerGold : root.muted
                        font.family: "monospace"
                        font.pixelSize: 14
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
                        style: Text.Outline
                        styleColor: "#05070c"
                    }
                    Text {
                        visible: root.sidebarCollapsed
                        anchors.centerIn: parent
                        text: root.navIcon(modelData)
                        color: root.page === modelData ? root.ledgerGold : root.muted
                        font.family: "monospace"
                        font.pixelSize: 14
                    }
                    MouseArea {
                        id: navHit
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.page = modelData
                    }
                }
            }
            }
        }

        Item {
            id: sidebarFooter
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: root.sidebarCollapsed ? 50 : 82
            Text {
                visible: !root.sidebarCollapsed
                anchors.left: parent.left
                anchors.leftMargin: 14
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 43
                text: "OSINT"
                color: root.ledgerGold
                font.family: "monospace"
                font.pixelSize: 17
                font.bold: true
                font.letterSpacing: 1.1
                style: Text.Outline
                styleColor: "#05070c"
            }
            Text {
                visible: !root.sidebarCollapsed
                anchors.left: parent.left
                anchors.leftMargin: 14
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 14
                text: "PUBLIC · READ ONLY"
                color: root.muted
                font.family: "monospace"
                font.pixelSize: 10
                style: Text.Outline
                styleColor: "#05070c"
            }
            Text {
                visible: root.sidebarCollapsed
                anchors.centerIn: parent
                text: "⌁"
                color: root.ledgerGold
                font.pixelSize: 17
            }
        }
    }

    Item {
        id: mainArea
        z: 2
        anchors.left: sidebar.right
        anchors.leftMargin: 4
        anchors.right: parent.right
        anchors.rightMargin: 10
        anchors.top: parent.top
        anchors.topMargin: 8
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 8

        Row {
            id: metricRow
            visible: root.page === "OVERVIEW"
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.topMargin: 36
            height: 44
            spacing: 22
            Repeater {
                model: [
                    {key: "aircraft", label: "AIRCRAFT", color: root.signalBlue},
                    {key: "earthquakes", label: "EARTHQUAKES", color: root.ledgerGold},
                    {key: "fires", label: "FIRES", color: root.signalRed},
                    {key: "cameras", label: "CCTV", color: "#6ec4d8"},
                    {key: "news", label: "NEWS", color: root.text}
                ]
                delegate: Item {
                    required property var modelData
                    width: Math.max(metricLegend.implicitWidth, metricCount.implicitWidth)
                    height: 44
                    Text {
                        id: metricLegend
                        anchors.top: parent.top
                        text: String(modelData.label)
                        color: root.muted
                        font.family: "monospace"
                        font.pixelSize: 10
                        font.bold: true
                        style: Text.Outline
                        styleColor: "#05070c"
                    }
                    Text {
                        id: metricCount
                        anchors.left: parent.left
                        anchors.bottom: parent.bottom
                        text: root.number(root.count(String(modelData.key)))
                        color: modelData.color
                        font.family: "monospace"
                        font.pixelSize: 20
                        style: Text.Outline
                        styleColor: "#05070c"
                    }
                }
            }
        }

        Rectangle {
            id: nearbyCard
            visible: root.nearbyEnabled && (root.page === "OVERVIEW" || root.page === "MAP")
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.topMargin: 76
            width: Math.min(270, parent.width - intelCard.width - 12)
            height: Math.min(230, parent.height * 0.38)
            radius: 5
            color: "#ed05070c"
            border.color: root.frameBorder
            Column {
                anchors.fill: parent
                anchors.margins: 8
                spacing: 5
                Text { text: "NEARBY · Wi-Fi / Bluetooth"; color: root.ledgerGold; font.family: "monospace"; font.pixelSize: 10 }
                Text {
                    width: parent.width
                    text: !root.nearbyActive ? "Pausad · aktiveras vid NAV-rutt eller zoom ≥15"
                        : root.nearbyPayload.status === "UNAVAILABLE" ? "Sensorkällor är inte tillgängliga"
                        : "Systemets observationer · cache med okänd ålder"
                    color: root.muted; font.pixelSize: 10; wrapMode: Text.WordWrap
                }
                ListView {
                    objectName: "osintNearbyList"
                    width: parent.width
                    height: Math.max(0, nearbyCard.height - 78)
                    clip: true
                    model: root.nearbyPayload.rows || []
                    delegate: Text {
                        required property var modelData
                        width: ListView.view.width
                        height: 34
                        textFormat: Text.PlainText
                        text: String(modelData.name) + "\n" + String(modelData.kind).toUpperCase()
                            + " · " + modelData.signal + " " + modelData.signal_unit + (modelData.connected ? " · ANSLUTEN" : "")
                        color: root.text; font.family: "monospace"; font.pixelSize: 10
                        elide: Text.ElideRight
                    }
                }
            }
        }
        Item {
            id: intelCard
            visible: root.page === "OVERVIEW" || root.page === "MAP"
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.topMargin: 8
            anchors.bottom: detailCard.visible ? detailCard.top : parent.bottom
            anchors.bottomMargin: detailCard.visible ? 8 : 0
            width: Math.min(300, parent.width * 0.28)

            Rectangle {
                anchors.fill: parent
                anchors.margins: -4
                color: "#ed05070c"
                radius: 5
            }
            Item {
                id: intelHeader
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                height: 22
                Text {
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    text: "INTELLIGENCE STREAM"
                    color: root.ink
                    font.family: "monospace"
                    font.pixelSize: 12
                    font.bold: true
                    style: Text.Outline
                    styleColor: "#05070c"
                }
                Text {
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    text: root.fetchBusy ? "FETCHING" : (root.statusText() + "  ↻")
                    color: refreshHit.containsMouse ? root.ledgerGold : root.statusColor()
                    font.family: "monospace"
                    font.pixelSize: 10
                    style: Text.Outline
                    styleColor: "#05070c"
                    MouseArea {
                        id: refreshHit
                        anchors.fill: parent
                        anchors.margins: -4
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.refresh()
                    }
                }
            }

            Row {
                id: streamFilters
                anchors.top: intelHeader.bottom
                anchors.topMargin: 4
                spacing: 6
                Repeater {
                    model: ["NEWS", "SVENSKA", "SIGNALS"]
                    delegate: Rectangle {
                        required property string modelData
                        width: filterLabel.implicitWidth + 16
                        height: 24
                        radius: 3
                        color: root.streamMode === modelData ? root.selectedPanel : "#181818cc"
                        border.color: root.streamMode === modelData ? root.ledgerGold : root.frameBorder
                        Text {
                            id: filterLabel
                            anchors.centerIn: parent
                            text: modelData
                            color: root.streamMode === modelData ? root.ledgerGold : root.muted
                            font.family: "monospace"
                            font.pixelSize: 10
                        }
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.streamMode = modelData
                        }
                    }
                }
            }
            Text {
                anchors.top: streamFilters.bottom
                anchors.topMargin: 16
                visible: overviewNewsList.count === 0
                text: root.fetchBusy ? "Hämtar nyheter…" : "Inga artiklar i detta flöde"
                color: root.muted
                font.pixelSize: 11
            }
            ListView {
                id: overviewNewsList
                objectName: "overviewNewsList"
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: streamFilters.bottom
                anchors.topMargin: 4
                anchors.bottom: parent.bottom
                clip: true
                spacing: 1
                model: root.streamRows()
                delegate: Item {
                    required property var modelData
                    width: overviewNewsList.width
                    height: 68
                    Rectangle {
                        anchors.fill: parent
                        radius: 3
                        color: root.selectedEvent && root.selectedEvent.id === modelData.id
                            ? root.selectedPanel
                            : (newsHit.containsMouse ? "#2a2a2a" : "transparent")
                    }
                    Text {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.leftMargin: 8
                        anchors.rightMargin: 8
                        anchors.topMargin: 5
                        height: 40
                        textFormat: Text.PlainText
                        wrapMode: Text.WordWrap
                        maximumLineCount: 2
                        text: String(modelData.title || "UNTITLED")
                        color: root.selectedEvent && root.selectedEvent.id === modelData.id
                            ? root.ink : root.text
                        font.family: "monospace"
                        font.pixelSize: 11
                        font.bold: root.selectedEvent && root.selectedEvent.id === modelData.id
                        elide: Text.ElideRight
                        style: Text.Outline
                        styleColor: "#05070c"
                    }
                    Text {
                        anchors.left: parent.left
                        anchors.bottom: parent.bottom
                        anchors.leftMargin: 8
                        anchors.bottomMargin: 4
                        anchors.right: parent.right
                        anchors.rightMargin: 8
                        elide: Text.ElideRight
                        textFormat: Text.PlainText
                        text: String(modelData.source || modelData.kind || "news").toUpperCase()
                            + " · "
                            + root.shortTime(modelData.time || modelData.published)
                            + (modelData.feed_stale ? " · CACHE" : "")
                        color: Number(modelData.risk_score || 0) >= 7 ? root.signalRed : root.muted
                        font.family: "monospace"
                        font.pixelSize: 9
                        style: Text.Outline
                        styleColor: "#05070c"
                    }
                    MouseArea {
                        id: newsHit
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.focusGlobe(modelData)
                    }
                }
            }
        }

        Item {
            id: detailCard
            visible: (root.page === "OVERVIEW" || root.page === "MAP")
                     && (root.navMode || root.selectedEvent)
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            width: Math.min(300, parent.width * 0.28)
            height: root.navMode
                ? Math.min(470, parent.height * 0.68)
                : Math.min(Math.max(168, detailColumn.height + 28), parent.height * 0.48)
            Rectangle {
                anchors.fill: parent
                color: root.navMode ? "#1a1a1a" : "#181818"
                opacity: 0.96
            }
            Item {
                id: detailPane
                objectName: "osintSharedPane"
                anchors.fill: parent
                Column {
                    visible: root.navMode
                    anchors.fill: parent
                    spacing: 5
                    Text {
                        width: parent.width
                        text: root.navMeta !== ""
                            ? root.navMeta
                            : "TYPE A PLACE + ENTER · FIRST START · LAST END · DRAG TO REORDER"
                        color: root.muted
                        wrapMode: Text.WordWrap
                        font.family: "monospace"
                        font.pixelSize: 9
                    }
                    Text {
                        width: parent.width
                        text: root.navigationLabel()
                        color: overviewGlobe.positionState.fresh ? root.signalBlue : root.muted
                        font.pixelSize: 11
                        textFormat: Text.PlainText
                        wrapMode: Text.WordWrap
                    }
                    GgButton {
                        objectName: "osintFollowPositionButton"
                        text: overviewGlobe.positionState.following ? "STOP FOLLOWING" : "FOLLOW POSITION"
                        onClicked: overviewGlobe.setFollowing(!overviewGlobe.positionState.following)
                    }
                    ListView {
                        id: navPlaceList
                        width: parent.width
                        height: Math.min(25 * Math.max(root.navPlaces.length, 0), 140)
                        clip: true
                        visible: root.navPlaces.length > 0
                        model: root.navPlaces
                        spacing: 3
                        delegate: Item {
                            id: placeRow
                            required property string modelData
                            required property int index
                            width: navPlaceList.width
                            height: 22
                            z: placeDrag.drag.active ? 2 : 0
                            Rectangle {
                                id: placeChip
                                width: parent.width
                                height: 22
                                color: placeDrag.drag.active ? "#2a2a2a" : "#202020"
                                border.color: root.frameBorder
                                border.width: 1
                                radius: 4
                                antialiasing: true
                                Text {
                                    anchors.left: parent.left
                                    anchors.leftMargin: 8
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: "⋮⋮  " + placeRow.modelData
                                    color: root.text
                                    font.family: "monospace"
                                    font.pixelSize: 10
                                }
                                Text {
                                    anchors.right: parent.right
                                    anchors.rightMargin: 8
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: "✕"
                                    color: root.muted
                                    font.family: "monospace"
                                    font.pixelSize: 10
                                }
                                MouseArea {
                                    id: placeDrag
                                    anchors.fill: parent
                                    anchors.rightMargin: 22
                                    hoverEnabled: true
                                    cursorShape: Qt.OpenHandCursor
                                    drag.target: placeChip
                                    drag.axis: Drag.YAxis
                                    onReleased: {
                                        var localY = placeChip.mapToItem(navPlaceList.contentItem, 0, placeChip.height / 2).y
                                        var target = Math.round(localY / 25)
                                        if (target < 0)
                                            target = 0
                                        if (target > root.navPlaces.length - 1)
                                            target = root.navPlaces.length - 1
                                        root.moveNavPlace(placeRow.index, target)
                                        placeChip.x = 0
                                        placeChip.y = 0
                                    }
                                }
                                MouseArea {
                                    anchors.right: parent.right
                                    width: 22
                                    height: parent.height
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: root.removeNavPlace(placeRow.index)
                                }
                            }
                        }
                    }
                    GgField {
                        id: navDraftField
                        width: parent.width
                        placeholderText: root.navPlaces.length < 1
                            ? "START  (enter)"
                            : (root.navPlaces.length === 1 ? "END  (enter)" : "NEXT PLACE  (enter · goes between)")
                        text: root.navDraft
                        onTextChanged: root.navDraft = text
                        Keys.onReturnPressed: root.commitNavPlace()
                        Keys.onEnterPressed: root.commitNavPlace()
                    }
                    Row {
                        spacing: 6
                        Repeater {
                            model: [
                                {label: "GPS", action: "gps"},
                                {label: "ADD", action: "stop"},
                                {label: "ROUTE", action: "route"},
                                {label: "CLEAR", action: "clear"}
                            ]
                            delegate: Rectangle {
                                required property var modelData
                                width: navBtnLabel.implicitWidth + 12
                                height: 22
                                color: navBtnHit.containsMouse ? "#2a2a2a" : "#202020"
                                border.color: navBtnHit.containsMouse ? "#8a8a8a" : root.frameBorder
                                border.width: 1
                                radius: 4
                                antialiasing: true
                                Text {
                                    id: navBtnLabel
                                    anchors.centerIn: parent
                                    text: modelData.label
                                    color: root.text
                                    font.family: "monospace"
                                    font.pixelSize: 9
                                }
                                MouseArea {
                                    id: navBtnHit
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        if (modelData.action === "gps") {
                                            if (root.navPlaces.length === 0
                                                    || String(root.navPlaces[0]).toLowerCase() !== "gps")
                                                root.navPlaces = ["GPS"].concat(root.navPlaces)
                                            overviewGlobe.locateGps()
                                        } else if (modelData.action === "stop") {
                                            root.commitNavPlace()
                                        } else if (modelData.action === "route") {
                                            root.runNavRoute()
                                        } else {
                                            root.clearNav()
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                Flickable {
                    visible: !root.navMode && root.selectedEvent
                    anchors.fill: parent
                    clip: true
                    contentWidth: width
                    contentHeight: detailColumn.height
                    Column {
                        id: detailColumn
                        width: parent.width
                        spacing: 5
                        Text {
                            width: parent.width
                            text: root.selectedEvent ? String(root.selectedEvent.title || "") : ""
                            color: root.ink
                            wrapMode: Text.WordWrap
                            font.family: "monospace"
                            font.pixelSize: 12
                            font.bold: true
                            style: Text.Outline
                            styleColor: "#05070c"
                        }
                        Text {
                            width: parent.width
                            text: root.selectedEvent
                                ? String(root.selectedEvent.source || "")
                                    + " · "
                                    + String(root.selectedEvent.kind || "").toUpperCase()
                                : ""
                            color: root.ledgerGold
                            font.family: "monospace"
                            font.pixelSize: 9
                            style: Text.Outline
                            styleColor: "#05070c"
                        }
                        Image {
                            visible: !!(root.selectedEvent && (root.selectedEvent.photo || root.selectedEvent.media_url))
                            width: parent.width
                            height: visible ? 132 : 0
                            source: root.selectedEvent
                                ? String(root.selectedEvent.photo || root.selectedEvent.media_url || "")
                                : ""
                            fillMode: Image.PreserveAspectCrop
                            asynchronous: true
                        }
                        Repeater {
                            model: root.eventFacts(root.selectedEvent)
                            Text {
                                required property string modelData
                                width: detailColumn.width
                                text: modelData
                                color: root.text
                                wrapMode: Text.WordWrap
                                font.family: "monospace"
                                font.pixelSize: 10
                            }
                        }
                        Text {
                            width: parent.width
                            visible: root.selectedEvent
                                && root.selectedEvent.kind !== "aircraft"
                                && root.selectedEvent.kind !== "cameras"
                                && String(root.selectedEvent.summary || "") !== ""
                            text: root.selectedEvent ? String(root.selectedEvent.summary || "") : ""
                            color: root.text
                            wrapMode: Text.WordWrap
                            font.family: "monospace"
                            font.pixelSize: 10
                        }
                        GgButton {
                            objectName: "osintCopyArticleButton"
                            visible: root.selectedEvent && root.selectedEvent.kind === "news" && !!root.selectedEvent.url
                            text: "COPY ARTICLE URL"
                            onClicked: root.copyText(root.selectedEvent.url)
                        }
                        GgButton {
                            objectName: "osintSaveEvidenceButton"
                            text: "SAVE TO RESEARCH"
                            enabled: root.selectedEvent && !root.selectedEvent.cluster
                                && root.surfaceHost && !!root.surfaceHost.osintRecordEvidence
                            onClicked: root.saveEvidence()
                        }
                        Text {
                            width: parent.width
                            visible: root.evidenceNotice.length > 0
                            text: root.evidenceNotice
                            color: root.ledgerGold
                            wrapMode: Text.WordWrap
                            font.family: "monospace"
                            font.pixelSize: 10
                        }
                    }
                }
            }
        }

        Item {
            id: globeHud
            visible: root.page === "OVERVIEW" || root.page === "MAP"
            anchors.left: parent.left
            anchors.bottom: parent.bottom
            width: Math.min(470, parent.width - intelCard.width - 16)
            height: 92
            Column {
                spacing: 4
                Row {
                    spacing: 6
                    Repeater {
                        model: [
                            {label: "3D", mode: "globe"},
                            {label: "2D", mode: "mercator"},
                            {label: "TERRAIN", mode: "terrain"},
                            {label: "BUILDINGS", mode: "buildings"},
                            {label: "RESET", mode: "reset"},
                            {label: "NAV", mode: "nav"},
                            {label: "POS", mode: "position"},
                            {label: "NEARBY", mode: "nearby"}
                        ]
                        delegate: Rectangle {
                            required property var modelData
                            width: hudBtnText.implicitWidth + 16
                            height: 24
                            color: hudBtnHit.containsMouse ? "#202020" : "#181818cc"
                            border.color: (
                                (modelData.mode === "globe" && !(overviewGlobe.savedView && overviewGlobe.savedView.projection === "mercator"))
                                || (modelData.mode === "mercator" && overviewGlobe.savedView && overviewGlobe.savedView.projection === "mercator")
                                || (modelData.mode === "nav" && root.navMode)
                                || (modelData.mode === "position" && overviewGlobe.positionEnabled)
                                || (modelData.mode === "nearby" && root.nearbyEnabled)
                                || (modelData.mode === "terrain" && overviewGlobe.savedView && overviewGlobe.savedView.terrainEnabled)
                                || (modelData.mode === "buildings" && overviewGlobe.savedView && overviewGlobe.savedView.buildingsEnabled)
                            ) ? root.ledgerGold : root.frameBorder
                            border.width: 1
                            radius: 4
                            antialiasing: true
                            Text {
                                id: hudBtnText
                                anchors.centerIn: parent
                                text: modelData.label
                                color: parent.border.color === root.ledgerGold ? root.ledgerGold : root.text
                                font.family: "monospace"
                                font.pixelSize: 10
                            }
                            MouseArea {
                                id: hudBtnHit
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    if (modelData.mode === "reset")
                                        overviewGlobe.resetView()
                                    else if (modelData.mode === "nav")
                                        root.openNav()
                                    else if (modelData.mode === "position")
                                        overviewGlobe.setPositionEnabled(!overviewGlobe.positionEnabled)
                                    else if (modelData.mode === "nearby")
                                        root.nearbyEnabled = !root.nearbyEnabled
                                    else if (modelData.mode === "terrain")
                                        overviewGlobe.setTerrain(!(overviewGlobe.savedView && overviewGlobe.savedView.terrainEnabled))
                                    else if (modelData.mode === "buildings")
                                        overviewGlobe.setBuildings(!(overviewGlobe.savedView && overviewGlobe.savedView.buildingsEnabled))
                                    else
                                        overviewGlobe.setProjection(modelData.mode)
                                }
                            }
                        }
                    }
                }
                Text {
                    width: parent.width
                    text: root.positionLabel()
                    color: overviewGlobe.positionState.fresh ? root.signalBlue : root.muted
                    font.family: "monospace"
                    font.pixelSize: 10
                    elide: Text.ElideRight
                }
                Text {
                    text: (overviewGlobe.savedView ? overviewGlobe.savedView.terrainStatus : "TERRAIN OFF")
                        + (overviewGlobe.savedView && overviewGlobe.savedView.buildingsEnabled ? " · BUILDINGS ≥14" : "")
                    color: root.muted
                    font.family: "monospace"
                    font.pixelSize: 10
                }
                Text {
                    text: (
                        overviewGlobe.savedView && overviewGlobe.savedView.projection === "mercator"
                            ? "2D MAP"
                            : "3D GLOBE"
                    )
                    + " · "
                    + root.number(overviewGlobe.pointCount)
                    + " EVENTS · ZOOM "
                    + (overviewGlobe.savedView && overviewGlobe.savedView.zoom !== undefined
                        ? Number(overviewGlobe.savedView.zoom).toFixed(1)
                        : "—")
                    color: root.muted
                    font.family: "monospace"
                    font.pixelSize: 10
                    style: Text.Outline
                    styleColor: "#05070c"
                }
            }
        }

        StackLayout {
            id: pages
            visible: root.page !== "OVERVIEW" && root.page !== "MAP"
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            currentIndex: Math.max(0, root.nav.indexOf(root.page))

            Item {
                id: overviewPage
                objectName: "osintOverviewPage"
            }

            Item {
                id: mapPage
                objectName: "osintMapPage"
                TmogCard {
                    visible: false
                    leftLegend: "EVENT MAP"
                    rightLegend: root.number(root.renderedPointCount()) + " POINTS"
                    borderColor: root.frameBorder
                    fill: root.panel
                }
                TmogCard {
                    visible: false
                    leftLegend: "LAYER COUNTS"
                    borderColor: root.frameBorder
                    fill: root.panel
                        Column {
                            anchors.fill: parent
                            spacing: 8
                            Repeater {
                                model: [
                                    {key: "aircraft", label: "AIRCRAFT"},
                                    {key: "earthquakes", label: "SEISMIC"},
                                    {key: "fires", label: "FIRES"},
                                    {key: "satellites", label: "SATELLITES"},
                                    {key: "news", label: "NEWS"},
                                    {key: "conflicts", label: "WATCHLIST"},
                                    {key: "cameras", label: "ALPR PINS"}
                                ]
                                delegate: Item {
                                    required property var modelData
                                    width: parent.width
                                    height: 23
                                    Text {
                                        anchors.left: parent.left
                                        text: modelData.label
                                        color: root.muted
                                        font.family: "monospace"
                                        font.pixelSize: 10
                                    }
                                    Text {
                                        anchors.right: parent.right
                                        text: root.number(root.count(modelData.key))
                                        color: root.ink
                                        font.family: "monospace"
                                        font.pixelSize: 11
                                    }
                                }
                            }
                            Text {
                                width: parent.width
                                text: "MapLibre 3D globe with OpenFreeMap dark tiles, local land fallback, and bounded public feed points."
                                color: root.muted
                                wrapMode: Text.WordWrap
                                font.family: "monospace"
                                font.pixelSize: 9
                            }
                        }
                    }
            }

            Item {
                id: flightsPage
                objectName: "osintFlightsPage"
                Column {
                    anchors.fill: parent
                    spacing: 10
                    Row {
                        width: parent.width
                        height: 100
                        spacing: 10
                        TmogCard {
                            width: parent.width * 0.33 - 7
                            height: parent.height
                            leftLegend: "AIRCRAFT"
                            borderColor: root.frameBorder
                            fill: root.panel
                            Text {
                                anchors.left: parent.left
                                anchors.leftMargin: 6
                                anchors.bottom: parent.bottom
                                anchors.bottomMargin: 7
                                text: root.number(root.count("aircraft"))
                                color: root.signalBlue
                                font.family: "monospace"
                                font.pixelSize: 25
                            }
                        }
                        TmogCard {
                            width: parent.width * 0.67 - 3
                            height: parent.height
                            leftLegend: "FLIGHT SNAPSHOT"
                            rightLegend: String(root.payload.focus && root.payload.focus.label || "REGION")
                            borderColor: root.frameBorder
                            fill: root.panel
                            TmogSpark {
                                anchors.fill: parent
                                values: root.history("aircraft")
                                stroke: root.signalBlue
                                fill: "#192631"
                                yMax: 0
                            }
                            Text {
                                anchors.left: parent.left
                                anchors.leftMargin: 6
                                anchors.bottom: parent.bottom
                                anchors.bottomMargin: 5
                                text: "OPEN SKY · POSITION SNAPSHOT"
                                color: root.muted
                                font.family: "monospace"
                                font.pixelSize: 9
                            }
                        }
                    }
                    TmogCard {
                        width: parent.width
                        height: parent.height - 110
                        leftLegend: "AIRCRAFT TABLE"
                        rightLegend: "COPY CALLSIGN / ID"
                        borderColor: root.frameBorder
                        fill: root.panel
                        ListView {
                            id: aircraftList
                            anchors.fill: parent
                            clip: true
                            model: root.rows("aircraft")
                            delegate: Item {
                                required property var modelData
                                required property int index
                                width: aircraftList.width
                                height: 27
                                Rectangle {
                                    anchors.fill: parent
                                    color: rowHit.containsMouse ? "#20262d" : (index % 2 ? "#171717" : "transparent")
                                }
                                Text {
                                    anchors.left: parent.left
                                    anchors.leftMargin: 6
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: parent.width * 0.23
                                    text: String(modelData.callsign || modelData.id || "UNKNOWN")
                                    color: root.ink
                                    font.family: "monospace"
                                    font.pixelSize: 10
                                    elide: Text.ElideRight
                                }
                                Text {
                                    anchors.left: parent.left
                                    anchors.leftMargin: parent.width * 0.25
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: parent.width * 0.21
                                    text: String(modelData.country || "—")
                                    color: root.text
                                    font.family: "monospace"
                                    font.pixelSize: 10
                                    elide: Text.ElideRight
                                }
                                Text {
                                    anchors.left: parent.left
                                    anchors.leftMargin: parent.width * 0.48
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: parent.width * 0.18
                                    text: root.number(modelData.lat, 2) + " / " + root.number(modelData.lon, 2)
                                    color: root.signalBlue
                                    font.family: "monospace"
                                    font.pixelSize: 10
                                }
                                Text {
                                    anchors.right: parent.right
                                    anchors.rightMargin: 8
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: root.number(modelData.alt_m) + "m"
                                    color: root.muted
                                    font.family: "monospace"
                                    font.pixelSize: 10
                                }
                                MouseArea {
                                    id: rowHit
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        root.page = "OVERVIEW"
                                        root.selectEvent(root.asEvent(modelData, "aircraft"), true)
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Item {
                id: seismicPage
                objectName: "osintSeismicPage"
                Row {
                    anchors.fill: parent
                    spacing: 10
                    TmogCard {
                        width: parent.width * 0.36
                        height: parent.height
                        leftLegend: "SEISMIC ACTIVITY"
                        rightLegend: "M2.5+ · 24H"
                        borderColor: root.frameBorder
                        fill: root.panel
                        TmogSpark {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.bottom: summaryText.top
                            values: root.history("earthquakes")
                            stroke: root.ledgerGold
                            fill: "#2b2418"
                        }
                        Text {
                            id: summaryText
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            anchors.bottomMargin: 8
                            text: root.number(root.count("earthquakes")) + " events in USGS feed"
                            color: root.text
                            font.family: "monospace"
                            font.pixelSize: 10
                        }
                    }
                    TmogCard {
                        width: parent.width * 0.64 - 10
                        height: parent.height
                        leftLegend: "EARTHQUAKES"
                        rightLegend: "USGS"
                        borderColor: root.frameBorder
                        fill: root.panel
                        ListView {
                            id: quakeList
                            anchors.fill: parent
                            clip: true
                            model: root.rows("earthquakes")
                            delegate: Item {
                                required property var modelData
                                width: quakeList.width
                                height: 32
                                Rectangle {
                                    anchors.fill: parent
                                    color: quakeHit.containsMouse ? "#20262d" : "transparent"
                                }
                                Text {
                                    anchors.left: parent.left
                                    anchors.leftMargin: 7
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: "M" + root.number(modelData.magnitude, 1)
                                    color: root.ledgerGold
                                    font.family: "monospace"
                                    font.pixelSize: 12
                                }
                                Text {
                                    anchors.left: parent.left
                                    anchors.leftMargin: 52
                                    anchors.right: parent.right
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: String(modelData.place || "UNKNOWN LOCATION")
                                    color: root.text
                                    font.family: "monospace"
                                    font.pixelSize: 10
                                    elide: Text.ElideRight
                                }
                                Text {
                                    anchors.right: parent.right
                                    anchors.rightMargin: 7
                                    anchors.bottom: parent.bottom
                                    anchors.bottomMargin: 3
                                    text: root.number(modelData.depth_km, 0) + "km · " + root.shortTime(modelData.time)
                                    color: root.muted
                                    font.family: "monospace"
                                    font.pixelSize: 8
                                }
                                MouseArea {
                                    id: quakeHit
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        root.page = "OVERVIEW"
                                        root.selectEvent(root.asEvent(modelData, "earthquakes"), true)
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Item {
                id: firesPage
                objectName: "osintFiresPage"
                Row {
                    anchors.fill: parent
                    spacing: 10
                    TmogCard {
                        width: parent.width * 0.34
                        height: parent.height
                        leftLegend: "FIRES / EVENTS"
                        rightLegend: "NASA EONET"
                        borderColor: root.frameBorder
                        fill: root.panel
                        Column {
                            anchors.fill: parent
                            spacing: 10
                            Text {
                                text: root.number(root.count("fires"))
                                color: root.signalRed
                                font.family: "monospace"
                                font.pixelSize: 28
                            }
                            TmogMeter {
                                width: parent.width
                                ratio: Math.min(1, root.count("fires") / 100)
                                segments: 22
                                onColor: root.signalRed
                            }
                            Text {
                                width: parent.width
                                text: "Open EONET wildfire and volcano events with coordinates."
                                color: root.text
                                wrapMode: Text.WordWrap
                                font.family: "monospace"
                                font.pixelSize: 10
                            }
                        }
                    }
                    TmogCard {
                        width: parent.width * 0.66 - 10
                        height: parent.height
                        leftLegend: "ACTIVE EVENTS"
                        borderColor: root.frameBorder
                        fill: root.panel
                        ListView {
                            id: firesList
                            anchors.fill: parent
                            clip: true
                            model: root.rows("fires")
                            delegate: Item {
                                required property var modelData
                                width: firesList.width
                                height: 38
                                Rectangle {
                                    anchors.fill: parent
                                    color: fireHit.containsMouse ? "#20262d" : "transparent"
                                }
                                Text {
                                    anchors.left: parent.left
                                    anchors.leftMargin: 7
                                    anchors.top: parent.top
                                    anchors.topMargin: 5
                                    anchors.right: parent.right
                                    text: String(modelData.title || "EVENT")
                                    color: root.text
                                    font.family: "monospace"
                                    font.pixelSize: 10
                                    elide: Text.ElideRight
                                }
                                Text {
                                    anchors.left: parent.left
                                    anchors.leftMargin: 7
                                    anchors.bottom: parent.bottom
                                    anchors.bottomMargin: 5
                                    text: String(modelData.category || "EVENT") + " · " + root.number(modelData.lat, 2) + "," + root.number(modelData.lon, 2)
                                    color: root.signalRed
                                    font.family: "monospace"
                                    font.pixelSize: 9
                                }
                                MouseArea {
                                    id: fireHit
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        root.page = "OVERVIEW"
                                        root.selectEvent(root.asEvent(modelData, "fires"), true)
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Item {
                id: spacePage
                objectName: "osintSpacePage"
                Column {
                    anchors.fill: parent
                    spacing: 10
                    Row {
                        width: parent.width
                        height: 112
                        spacing: 10
                        TmogCard {
                            width: parent.width * 0.34
                            height: parent.height
                            leftLegend: "SOLAR WEATHER"
                            rightLegend: "NOAA SWPC"
                            borderColor: root.frameBorder
                            fill: root.panel
                            Text {
                                anchors.left: parent.left
                                anchors.leftMargin: 7
                                anchors.bottom: parent.bottom
                                anchors.bottomMargin: 7
                                text: "KP " + root.number(root.payload.solar && root.payload.solar.kp_index, 1)
                                color: root.ledgerGold
                                font.family: "monospace"
                                font.pixelSize: 22
                            }
                            Text {
                                anchors.right: parent.right
                                anchors.rightMargin: 7
                                anchors.bottom: parent.bottom
                                anchors.bottomMargin: 10
                                text: String(root.payload.solar && root.payload.solar.storm_level || "UNKNOWN")
                                color: root.text
                                font.family: "monospace"
                                font.pixelSize: 10
                            }
                        }
                        TmogCard {
                            width: parent.width * 0.66 - 10
                            height: parent.height
                            leftLegend: "STATION CATALOG"
                            rightLegend: "CELESTRAK"
                            borderColor: root.frameBorder
                            fill: root.panel
                            Text {
                                anchors.left: parent.left
                                anchors.leftMargin: 7
                                anchors.bottom: parent.bottom
                                anchors.bottomMargin: 8
                                text: root.number(root.count("satellites")) + " tracked station objects"
                                color: root.signalViolet
                                font.family: "monospace"
                                font.pixelSize: 15
                            }
                        }
                    }
                    TmogCard {
                        width: parent.width
                        height: parent.height - 122
                        leftLegend: "SATELLITES"
                        rightLegend: "NORAD / STATIONS"
                        borderColor: root.frameBorder
                        fill: root.panel
                        ListView {
                            id: satelliteList
                            anchors.fill: parent
                            clip: true
                            model: root.rows("satellites")
                            delegate: Item {
                                required property var modelData
                                required property int index
                                width: satelliteList.width
                                height: 26
                                Rectangle {
                                    anchors.fill: parent
                                    color: satelliteHit.containsMouse ? "#20262d" : (index % 2 ? "#171717" : "transparent")
                                }
                                Text {
                                    anchors.left: parent.left
                                    anchors.leftMargin: 7
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: parent.width * 0.55
                                    text: String(modelData.name || "UNKNOWN")
                                    color: root.text
                                    font.family: "monospace"
                                    font.pixelSize: 10
                                    elide: Text.ElideRight
                                }
                                Text {
                                    anchors.right: parent.right
                                    anchors.rightMargin: 7
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: "NORAD " + String(modelData.norad || "—") + " · INC " + root.number(modelData.inclination, 1) + "°"
                                    color: root.signalViolet
                                    font.family: "monospace"
                                    font.pixelSize: 9
                                }
                                MouseArea {
                                    id: satelliteHit
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: root.copyText(modelData.name)
                                }
                            }
                        }
                    }
                }
            }

            Item {
                id: newsPage
                objectName: "osintNewsPage"
                TmogCard {
                    anchors.fill: parent
                    leftLegend: "WORLD NEWS"
                    rightLegend: "BBC WORLD · RISK HEURISTIC"
                    borderColor: root.frameBorder
                    fill: root.panel
                    ListView {
                        id: newsList
                        anchors.fill: parent
                        clip: true
                        spacing: 5
                        model: root.rows("news")
                        delegate: Item {
                            required property var modelData
                            width: newsList.width
                            height: 58
                            Rectangle {
                                anchors.fill: parent
                                color: newsPageHit.containsMouse ? "#20262d" : "transparent"
                                radius: 3
                            }
                            Text {
                                anchors.left: parent.left
                                anchors.right: riskLabel.left
                                anchors.top: parent.top
                                anchors.leftMargin: 8
                                anchors.rightMargin: 8
                                anchors.topMargin: 7
                                text: String(modelData.title || "UNTITLED")
                                color: root.ink
                                font.family: "monospace"
                                font.pixelSize: 11
                                elide: Text.ElideRight
                            }
                            Text {
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.bottom: parent.bottom
                                anchors.leftMargin: 8
                                anchors.rightMargin: 8
                                anchors.bottomMargin: 7
                                text: String(modelData.source || "SOURCE") + " · " + root.shortTime(modelData.published)
                                color: root.muted
                                font.family: "monospace"
                                font.pixelSize: 9
                                elide: Text.ElideRight
                            }
                            Text {
                                id: riskLabel
                                anchors.right: parent.right
                                anchors.top: parent.top
                                anchors.rightMargin: 8
                                anchors.topMargin: 7
                                text: "R" + String(modelData.risk_score || 1)
                                color: Number(modelData.risk_score || 0) >= 7 ? root.signalRed : root.ledgerGold
                                font.family: "monospace"
                                font.pixelSize: 10
                            }
                            MouseArea {
                                id: newsPageHit
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    root.page = "OVERVIEW"
                                    root.selectEvent(root.asEvent(modelData, "news"), true)
                                }
                            }
                        }
                    }
                }
            }

            Item {
                id: conflictPage
                objectName: "osintConflictPage"
                Row {
                    anchors.fill: parent
                    spacing: 10
                    TmogCard {
                        width: parent.width * 0.48
                        height: parent.height
                        leftLegend: "REFERENCE WATCHLIST"
                        rightLegend: "NOT LIVE VERIFIED"
                        borderColor: root.frameBorder
                        fill: root.panel
                        ListView {
                            id: conflictList
                            anchors.fill: parent
                            clip: true
                            model: root.rows("conflicts")
                            delegate: Item {
                                required property var modelData
                                width: conflictList.width
                                height: 29
                                Rectangle {
                                    anchors.fill: parent
                                    color: conflictHit.containsMouse ? "#20262d" : "transparent"
                                }
                                Rectangle {
                                    anchors.left: parent.left
                                    anchors.leftMargin: 7
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: 7
                                    height: 7
                                    radius: 4
                                    color: Number(modelData.severity || 0) >= 4 ? root.signalRed : root.signalViolet
                                }
                                Text {
                                    anchors.left: parent.left
                                    anchors.leftMargin: 22
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: String(modelData.label || "ZONE")
                                    color: root.text
                                    font.family: "monospace"
                                    font.pixelSize: 10
                                }
                                Text {
                                    anchors.right: parent.right
                                    anchors.rightMargin: 8
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: "S" + String(modelData.severity || "—")
                                    color: root.muted
                                    font.family: "monospace"
                                    font.pixelSize: 9
                                }
                                MouseArea {
                                    id: conflictHit
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        root.page = "OVERVIEW"
                                        root.selectEvent(root.asEvent(modelData, "conflicts"), true)
                                    }
                                }
                            }
                        }
                    }
                    TmogCard {
                        width: parent.width * 0.52 - 10
                        height: parent.height
                        leftLegend: "INTERPRETATION"
                        borderColor: root.frameBorder
                        fill: root.panel
                        Column {
                            anchors.fill: parent
                            spacing: 14
                            Text {
                                width: parent.width
                                text: "OSIRIS REFERENCE LAYER"
                                color: root.signalViolet
                                font.family: "monospace"
                                font.pixelSize: 15
                            }
                            Text {
                                width: parent.width
                                text: "The locations are a stable orientation layer for the map. They are not presented as a live incident feed and do not replace source verification."
                                color: root.text
                                wrapMode: Text.WordWrap
                                font.family: "monospace"
                                font.pixelSize: 11
                            }
                            TmogRail {
                                leftLegend: "SOURCE"
                                rightLegend: "OSIRIS / README"
                            }
                            Text {
                                width: parent.width
                                text: "Use NEWS, USGS, NASA and the source panel for current evidence."
                                color: root.muted
                                wrapMode: Text.WordWrap
                                font.family: "monospace"
                                font.pixelSize: 10
                            }
                        }
                    }
                }
            }

            Item {
                id: camerasPage
                objectName: "osintCamerasPage"
                Column {
                    anchors.fill: parent
                    spacing: 10
                    TmogCard {
                        width: parent.width
                        height: 78
                        leftLegend: "PUBLIC CCTV"
                        rightLegend: "SNAPSHOT FEEDS"
                        borderColor: root.frameBorder
                        fill: root.panel
                        Text {
                            anchors.left: parent.left
                            anchors.leftMargin: 6
                            anchors.bottom: parent.bottom
                            anchors.bottomMargin: 8
                            text: root.number(root.count("cameras")) + " public cameras · snapshot on click"
                            color: "#6ec4d8"
                            font.family: "monospace"
                            font.pixelSize: 13
                        }
                    }
                    TmogCard {
                        width: parent.width
                        height: parent.height - 88
                        leftLegend: "PUBLIC OSM PINS"
                        rightLegend: "COPY OSM URL"
                        borderColor: root.frameBorder
                        fill: root.panel
                        ListView {
                            id: cameraList
                            anchors.fill: parent
                            clip: true
                            model: root.rows("cameras")
                            delegate: Item {
                                required property var modelData
                                required property int index
                                width: cameraList.width
                                height: 27
                                Rectangle {
                                    anchors.fill: parent
                                    color: camHit.containsMouse ? "#20262d" : (index % 2 ? "#171717" : "transparent")
                                }
                                Text {
                                    anchors.left: parent.left
                                    anchors.leftMargin: 6
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: parent.width * 0.38
                                    text: String(modelData.brand || modelData.label || "ALPR")
                                    color: root.ink
                                    font.family: "monospace"
                                    font.pixelSize: 10
                                    elide: Text.ElideRight
                                }
                                Text {
                                    anchors.left: parent.left
                                    anchors.leftMargin: parent.width * 0.42
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: root.number(modelData.lat, 2) + " / " + root.number(modelData.lon, 2)
                                    color: "#6ec4d8"
                                    font.family: "monospace"
                                    font.pixelSize: 10
                                }
                                Text {
                                    anchors.right: parent.right
                                    anchors.rightMargin: 8
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: String(modelData.zone || "PIN")
                                    color: root.muted
                                    font.family: "monospace"
                                    font.pixelSize: 10
                                }
                                MouseArea {
                                    id: camHit
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        root.page = "OVERVIEW"
                                        root.selectEvent(root.asEvent(modelData, "cameras"), true)
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Item {
                id: sourcesPage
                objectName: "osintSourcesPage"
                TmogCard {
                    anchors.fill: parent
                    leftLegend: "SOURCE HEALTH"
                    rightLegend: String(root.payload.generated_at || "NOT FETCHED")
                    borderColor: root.frameBorder
                    fill: root.panel
                    Flickable {
                        anchors.fill: parent
                        contentWidth: width
                        contentHeight: sourceColumn.height
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds
                        ScrollBar.vertical: GgScrollBar { }
                        Column {
                            id: sourceColumn
                            width: parent.width
                            spacing: 5
                            Repeater {
                                model: root.rows("sources")
                            delegate: Item {
                                required property var modelData
                                width: parent.width
                                height: Math.max(88, sourceDetail.implicitHeight + 48)
                                Rectangle {
                                    anchors.fill: parent
                                    color: sourceHit.containsMouse ? "#20262d" : "transparent"
                                    radius: 3
                                }
                                Rectangle {
                                    anchors.left: parent.left
                                    anchors.leftMargin: 8
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: 7
                                    height: 7
                                    radius: 4
                                    color: String(modelData.status || "IDLE") === "OK"
                                        ? root.ledgerGreen
                                        : (String(modelData.status || "") === "REFERENCE"
                                            ? root.signalViolet
                                            : (String(modelData.status || "") === "ERROR" ? root.signalRed
                                                : (String(modelData.status || "") === "IDLE" ? root.muted : root.ledgerGold)))
                                }
                                Text {
                                    anchors.left: parent.left
                                    anchors.leftMargin: 24
                                    anchors.top: parent.top
                                    anchors.topMargin: 6
                                    text: String(modelData.label || "SOURCE") + " · " + String(modelData.provider || "")
                                    color: root.ink
                                    font.family: "monospace"
                                    font.pixelSize: 10
                                }
                                Text {
                                    anchors.left: parent.left
                                    anchors.leftMargin: 24
                                    anchors.top: parent.top
                                    anchors.topMargin: 25
                                    text: root.sourceHealthText(modelData)
                                    color: root.muted
                                    font.family: "monospace"
                                    font.pixelSize: 9
                                }
                                Text {
                                    id: sourceDetail
                                    anchors.left: parent.left
                                    anchors.leftMargin: 24
                                    anchors.right: parent.right
                                    anchors.rightMargin: 76
                                    anchors.top: parent.top
                                    anchors.topMargin: 42
                                    text: "Success: " + String(modelData.last_success_at || "never")
                                        + " · Attempt: " + String(modelData.last_attempt_at || "never")
                                        + (modelData.feeds && modelData.feeds.length ? "\n" + modelData.feeds.map(function(feed) { return feed.provider + ": " + feed.status + " · " + feed.count }).join(" | ") : "")
                                        + (modelData.error ? "\n" + String(modelData.error) : "")
                                    color: modelData.error ? root.signalRed : root.muted
                                    wrapMode: Text.WordWrap
                                    font.family: "monospace"
                                    font.pixelSize: 9
                                }
                                Text {
                                    anchors.right: parent.right
                                    anchors.rightMargin: 8
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: "COPY URL"
                                    color: root.ledgerGold
                                    font.family: "monospace"
                                    font.pixelSize: 9
                                }
                                MouseArea {
                                    id: sourceHit
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: root.copyText(modelData.url)
                                }
                            }
                        }
                        }
                    }
                }
            }

            Item {
                id: reconPage
                objectName: "osintReconPage"
                Row {
                    anchors.fill: parent
                    spacing: 10
                    TmogCard {
                        width: parent.width * 0.55
                        height: parent.height
                        leftLegend: "RECON BOUNDARY"
                        rightLegend: "SAFE MODE"
                        borderColor: root.frameBorder
                        fill: root.panel
                        Column {
                            anchors.fill: parent
                            spacing: 14
                            Text {
                                width: parent.width
                                text: "PUBLIC READ-ONLY RECON"
                                color: root.ledgerGreen
                                font.family: "monospace"
                                font.pixelSize: 16
                            }
                            Text {
                                width: parent.width
                                text: "The native surface implements the observation side of OSIRIS: fixed public feeds, source health, event mapping and copyable references."
                                color: root.text
                                wrapMode: Text.WordWrap
                                font.family: "monospace"
                                font.pixelSize: 11
                            }
                            TmogRail {
                                leftLegend: "ENABLED"
                                rightLegend: "PUBLIC FEEDS"
                            }
                            Repeater {
                                model: root.payload.recon && root.payload.recon.available || []
                                delegate: Text {
                                    required property string modelData
                                    width: parent.width
                                    text: "✓  " + modelData
                                    color: root.ledgerGreen
                                    font.family: "monospace"
                                    font.pixelSize: 10
                                }
                            }
                        }
                    }
                    TmogCard {
                        width: parent.width * 0.45 - 10
                        height: parent.height
                        leftLegend: "NOT ENABLED"
                        rightLegend: "AUTHORIZATION REQUIRED"
                        borderColor: root.frameBorder
                        fill: root.panel
                        Column {
                            anchors.fill: parent
                            spacing: 10
                            Repeater {
                                model: root.payload.recon && root.payload.recon.not_enabled || []
                                delegate: Item {
                                    required property string modelData
                                    width: parent.width
                                    height: 27
                                    Text {
                                        anchors.left: parent.left
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: "—  " + modelData
                                        color: root.muted
                                        font.family: "monospace"
                                        font.pixelSize: 10
                                    }
                                }
                            }
                            Text {
                                width: parent.width
                                text: "Public feeds accept no user-supplied target, URL or credential. Save observations to the shared RESEARCH workspace to investigate and corroborate them."
                                color: root.ledgerGold
                                wrapMode: Text.WordWrap
                                font.family: "monospace"
                                font.pixelSize: 10
                            }
                        }
                    }
                }
            }

        }
    }
}
