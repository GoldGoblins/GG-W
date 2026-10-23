import QtQuick
import QtMultimedia
import QtQuick.Window

Item {
    id: root
    objectName: "workspaceMediaPane"

    property var surfaceHost: null
    property color frameBorder: "#6a6a6a"
    property int frameRadius: 4
    property string statusJson: "{}"
    property var catalogItems: []
    property string lastPlayUrl: ""
    property string playerError: ""
    property bool playerReady: false
    property string pendingPlayId: ""
    property bool searchBusy: false
    property real _clockStamp: 0
    property bool playerWantsPlay: false
    property int playerRetryCount: 0
    readonly property int playerRetryLimit: 5
    property bool playerRetryExhausted: false
    property bool playerResetting: false
    property bool playerEnded: false
    property bool playerResolving: false
    property int playerResolveTicket: 0
    property int playerGeneration: -1
    property real playerStartedAt: 0
    property real playerLastFrameAt: 0
    property real playerStableSince: 0
    property bool videoFullscreen: false
    signal nowPlayingChanged(string label)

    readonly property var status: {
        try {
            return JSON.parse(root.statusJson || "{}")
        } catch (err) {
            return {}
        }
    }

    readonly property var items: {
        var rows = root.status.items
        if (rows !== undefined && rows !== null && rows.length !== undefined)
            return rows
        return root.catalogItems
    }

    readonly property string mode: String(root.status.mode || "MUSIC")
    readonly property bool screenOn: String(root.status.screen || "") === "EMBED"
    readonly property var now: root.status.now || {}
    readonly property bool qmlVideo: String(root.status.backend || "") === "qml"
    readonly property bool liveVideo: root.qmlVideo
        && (root.now.stream === true || root.now.media === "stream")
        && /^https?:\/\//i.test(root.lastPlayUrl)
    readonly property bool libretro: String(root.status.backend || "") === "libretro"
    readonly property bool showDisplay:
        root.mode === "TV"
        || root.mode === "GAME"
        || root.mode === "FETCH"
        || root.screenOn
        || root.qmlVideo
    readonly property bool listCollapsed:
        root.screenOn
        && root.mode === "GAME"
    readonly property bool streamBuffering: root.status.buffering === true
    readonly property string bufferingId: String(
        root.status.buffering_id || root.pendingPlayId || root.now.id || ""
    )

    function applyStatus(raw) {
        var text = String(raw || "")
        if (text === root.statusJson)
            return
        root.statusJson = text
        if (String(root.status.backend || "") === "qt_audio")
            root.playerError = root.status.reconnecting
                ? "Återansluter · " + root.status.retry_attempt + "/" + root.status.retry_limit
                : String(root.status.error || "")
        root.rememberCatalog()
        var title = String((root.status.now || {}).title || root.status.legend || "MEDIA")
        root.nowPlayingChanged(title)
        if (root.status.playing === true || root.status.paused === true || root.status.error)
            root.pendingPlayId = ""
        if (root.status.buffering !== true && root.status.playing === true)
            root.pendingPlayId = ""
    }

    function refresh() {
        if (!root.surfaceHost || !root.surfaceHost.mediaStatus)
            return
        root.applyStatus(root.surfaceHost.mediaStatus())
    }

    function refreshLive() {
        if (!root.surfaceHost)
            return
        if (root.surfaceHost.mediaLiveStatus)
            root.applyStatus(root.surfaceHost.mediaLiveStatus())
        else if (root.surfaceHost.mediaStatus)
            root.applyStatus(root.surfaceHost.mediaStatus())
    }

    function rememberCatalog() {
        var rows = root.status.items
        if (rows !== undefined && rows !== null && rows.length !== undefined)
            root.catalogItems = rows
    }

    function setMode(mode) {
        if (!root.surfaceHost)
            return
        root.statusJson = root.surfaceHost.mediaSetMode(mode)
        if (mode === "FETCH")
            root.openFetch()
        else
            root.refresh()
    }

    function playItem(itemId) {
        if (!root.surfaceHost)
            return
        root.pendingPlayId = String(itemId || "")
        root.statusJson = root.surfaceHost.mediaPlay(itemId)
        root.refresh()
    }

    function openCliamp() {
        if (!root.surfaceHost)
            return
        root.statusJson = root.surfaceHost.mediaStartCliamp()
        root.refresh()
    }

    function openFetch() {
        if (!root.surfaceHost)
            return
        var raw = root.surfaceHost.mediaStartFetch()
        try {
            var parsed = JSON.parse(raw || "{}")
            if (parsed.error) {
                root.playerError = String(parsed.error)
                root.refresh()
                return
            }
            root.playerError = ""
            root.statusJson = raw
        } catch (err) {
            root.playerError = String(err)
        }
        root.refresh()
    }

    function search(query) {
        if (!root.surfaceHost || !root.surfaceHost.mediaSearch)
            return
        root.searchBusy = true
        root.statusJson = root.surfaceHost.mediaSearch(query)
        root.searchBusy = false
        root.refresh()
    }

    function toMediaUrl(raw) {
        var s = String(raw || "")
        if (!s)
            return ""
        if (s.indexOf("://") >= 0)
            return s
        if (s.charAt(0) === "/")
            return "file://" + s
        return s
    }

    function toggleFullscreen() {
        root.videoFullscreen = !root.videoFullscreen
    }

    function reportPlayerState() {
        if (!root.surfaceHost || !root.surfaceHost.mediaReportPlayerState)
            return
        var status = holePlayer.mediaStatus
        var fresh = root.playerLastFrameAt > 0
            && Date.now() - root.playerLastFrameAt < 3000
        var playing = root.qmlVideo
            && root.status.paused !== true
            && root.playerWantsPlay && !root.playerRetryExhausted
            && holePlayer.error === MediaPlayer.NoError
            && holePlayer.playbackState === MediaPlayer.PlayingState
            && fresh
        // BufferingMedia can still deliver video. Only show a stall when
        // frames actually stop, not whenever the network buffer refills.
        var buffering = root.qmlVideo
            && root.status.paused !== true
            && root.playerWantsPlay && !root.playerRetryExhausted
            && !playing && (
                playerRetryTimer.running || root.playerResolving
                || holePlayer.playbackState === MediaPlayer.PlayingState
                || status === MediaPlayer.LoadedMedia
                || status === MediaPlayer.NoMedia
                || status === MediaPlayer.LoadingMedia
                || status === MediaPlayer.BufferingMedia
                || status === MediaPlayer.StalledMedia
            )
        root.surfaceHost.mediaReportPlayerState(playing, buffering)
    }

    function schedulePlayerRetry() {
        if (!root.liveVideo || root.status.paused === true
            || !root.playerWantsPlay || root.playerResetting || root.playerResolving
            || root.playerRetryExhausted)
            return
        if (playerRetryTimer.running)
            return
        if (root.playerRetryCount >= root.playerRetryLimit) {
            root.playerRetryExhausted = true
            root.playerWantsPlay = false
            root.playerError = "Sändningen är inte tillgänglig. Välj kanalen igen för att försöka på nytt."
            root.playerResetting = true
            holePlayer.stop()
            root.playerResetting = false
            root.reportPlayerState()
            return
        }
        playerRetryTimer.interval = Math.min(10000, 1000 * Math.pow(2, root.playerRetryCount))
        root.playerStableSince = 0
        root.playerError = "Återansluter · " + (root.playerRetryCount + 1) + "/" + root.playerRetryLimit
        playerRetryTimer.start()
        root.reportPlayerState()
    }

    function resetPlayerWatchdog() {
        root.playerStartedAt = Date.now()
        root.playerLastFrameAt = 0
        root.playerStableSince = 0
    }

    function cancelPlayerResolution() {
        root.playerResolveTicket += 1
        if (root.playerResolving && root.surfaceHost && root.surfaceHost.mediaCancelVideoSource)
            root.surfaceHost.mediaCancelVideoSource()
        root.playerResolving = false
    }

    function preparePlayerSource() {
        if (!root.playerWantsPlay || root.status.paused === true || !root.lastPlayUrl)
            return
        if (root.liveVideo && root.surfaceHost && root.surfaceHost.mediaResolveVideoSource) {
            root.playerResolving = true
            root.playerResolveTicket += 1
            root.resetPlayerWatchdog()
            root.surfaceHost.mediaResolveVideoSource(root.lastPlayUrl,
                root.playerRetryCount, root.playerResolveTicket)
            root.reportPlayerState()
        } else {
            root.loadPlayerSource(root.lastPlayUrl)
        }
    }

    function noteVideoFrame() {
        if (!root.qmlVideo || root.playerResetting || !root.playerWantsPlay
            || root.status.paused === true || holePlayer.error !== MediaPlayer.NoError
            || holePlayer.playbackState !== MediaPlayer.PlayingState)
            return
        var stamp = Date.now()
        var wasWaiting = !root.playerLastFrameAt
            || stamp - root.playerLastFrameAt >= 3000 || playerRetryTimer.running
        if (!root.playerStableSince || stamp - root.playerLastFrameAt >= 3000)
            root.playerStableSince = stamp
        root.playerLastFrameAt = stamp
        // A recovered stream must not be torn down by an old retry timer.
        playerRetryTimer.stop()
        if (root.playerResolving)
            root.cancelPlayerResolution()
        root.playerError = ""
        // Loading a manifest is not success: replenish the retry budget
        // only after 30 seconds of continuous decoded video.
        if (stamp - root.playerStableSince >= 30000)
            root.playerRetryCount = 0
        if (wasWaiting)
            root.reportPlayerState()
    }

    function watchPlayer() {
        if (!root.qmlVideo || root.status.paused === true || !root.playerWantsPlay
            || root.playerResetting || root.playerResolving || playerRetryTimer.running)
            return
        root.reportPlayerState()
        var status = holePlayer.mediaStatus
        if (status === MediaPlayer.EndOfMedia && !root.liveVideo) {
            root.playerEnded = true
            root.playerWantsPlay = false
            root.reportPlayerState()
            return
        }
        var loading = status === MediaPlayer.LoadingMedia || status === MediaPlayer.NoMedia
        var idle = Date.now() - (root.playerLastFrameAt || root.playerStartedAt)
        // Give a slow HLS manifest time to load and short stalls time to
        // refill. Frames, rather than the media clock, detect frozen video
        // even on live feeds whose position/duration are always zero.
        if (holePlayer.error !== MediaPlayer.NoError
            || status === MediaPlayer.InvalidMedia || status === MediaPlayer.EndOfMedia
            || idle >= (loading ? 30000 : 15000))
            root.schedulePlayerRetry()
    }

    function loadPlayerSource(url) {
        root.playerResetting = true
        root.resetPlayerWatchdog()
        holePlayer.stop()
        holePlayer.source = ""
        // Qt 6.10+ supports a socket timeout. Keep Qt's robust buffering
        // defaults; low-latency streaming deliberately reduces that buffer.
        if (holePlayer.playbackOptions !== undefined)
            holePlayer.playbackOptions.networkTimeoutMs = 15000
        holePlayer.source = url
        root.playerResetting = false
        root.playWhenReady()
        root.reportPlayerState()
    }

    function playWhenReady() {
        if (root.playerResetting || !root.qmlVideo || !root.playerWantsPlay
            || root.playerRetryExhausted || root.status.paused === true)
            return
        if ((holePlayer.mediaStatus === MediaPlayer.LoadedMedia
                || holePlayer.mediaStatus === MediaPlayer.BufferedMedia)
            && holePlayer.playbackState !== MediaPlayer.PlayingState)
            holePlayer.play()
    }

    function retryPlayer() {
        if (!root.liveVideo || root.status.paused === true || !root.playerWantsPlay
            || root.playerResetting || root.playerRetryExhausted)
            return
        if (holePlayer.error === MediaPlayer.NoError && root.playerLastFrameAt > 0
            && Date.now() - root.playerLastFrameAt < 3000)
            return
        root.playerRetryCount += 1
        root.preparePlayerSource()
    }

    function syncPlayer() {
        if (!root.playerReady || root.playerResetting)
            return
        if (!root.qmlVideo) {
            root.cancelPlayerResolution()
            root.videoFullscreen = false
            playerRetryTimer.stop()
            root.resetPlayerWatchdog()
            root.playerWantsPlay = false
            root.lastPlayUrl = ""
            root.playerGeneration = -1
            root.playerRetryExhausted = false
            root.playerEnded = false
            root.playerResetting = true
            holePlayer.stop()
            holePlayer.source = ""
            root.playerResetting = false
            if (root.mode !== "FETCH")
                root.playerError = ""
            return
        }
        var url = root.toMediaUrl(String((root.status.now || {}).source || ""))
        var volume = root.status.volume === undefined ? 70 : Number(root.status.volume)
        holeAudio.volume = Math.max(0, Math.min(1, volume / 100))
        var generation = Number(root.status.playback_generation || 0)
        if (url !== root.lastPlayUrl || generation !== root.playerGeneration) {
            playerRetryTimer.stop()
            root.cancelPlayerResolution()
            root.lastPlayUrl = url
            root.playerGeneration = generation
            root.playerRetryCount = 0
            root.playerRetryExhausted = false
            root.playerEnded = false
            root.playerWantsPlay = root.status.paused !== true && !!url
            root.playerError = ""
            // A previous channel must not keep sending frames while this
            // channel's manifest is being resolved.
            root.playerResetting = true
            holePlayer.stop()
            holePlayer.source = ""
            root.playerResetting = false
            root.preparePlayerSource()
            if (root.status.paused === true)
                holePlayer.pause()
            root.reportPlayerState()
            return
        }
        if (root.status.paused === true) {
            playerRetryTimer.stop()
            root.cancelPlayerResolution()
            root.playerWantsPlay = false
            if (holePlayer.playbackState !== MediaPlayer.PausedState)
                holePlayer.pause()
            root.reportPlayerState()
            return
        }
        if (!url || root.playerRetryExhausted || root.playerEnded || root.playerResolving)
            return
        if (!root.playerWantsPlay)
            root.resetPlayerWatchdog()
        root.playerWantsPlay = true
        if (!String(holePlayer.source)) {
            root.preparePlayerSource()
            return
        }
        root.playWhenReady()
        root.reportPlayerState()
    }

    onLibretroChanged: {
        if (root.libretro)
            hole.forceActiveFocus()
    }

    onVideoFullscreenChanged: {
        if (root.videoFullscreen && root.qmlVideo) {
            fullscreenWindow.showFullScreen()
            fullscreenWindow.requestActivate()
        } else {
            fullscreenWindow.hide()
        }
    }

    onStatusJsonChanged: {
        // Let status/now/backend bindings settle before touching the decoder.
        // Reports can synchronously publish another status through Python.
        Qt.callLater(root.syncStatusPlayer)
    }

    function syncStatusPlayer() {
        root.rememberCatalog()
        root.syncPlayer()
    }

    Component.onCompleted: {
        root.playerReady = true
        if (Window.window)
            fullscreenWindow.transientParent = Window.window
        root.syncPlayer()
    }

    Component.onDestruction: root.cancelPlayerResolution()

    function reportClock() {
        if (!root.qmlVideo || !root.surfaceHost || !root.surfaceHost.mediaReportClock)
            return
        var now = Date.now()
        if (now - root._clockStamp < 250)
            return
        root._clockStamp = now
        var pos = Number(holePlayer.position || 0) / 1000
        var dur = Number(holePlayer.duration || 0) / 1000
        if (!(pos >= 0))
            pos = 0
        if (!(dur >= 0))
            dur = 0
        root.surfaceHost.mediaReportClock(pos, dur)
    }

    Connections {
        target: root.surfaceHost || null
        ignoreUnknownSignals: true
        function onMediaStateChanged() {
            if (!root.visible)
                return
            var prev = root.mode
            root.refreshLive()
            if (root.mode !== prev)
                root.refresh()
        }
        function onMediaSeekChanged(seconds) {
            if (!root.qmlVideo || !root.playerReady)
                return
            holePlayer.position = Math.max(0, Number(seconds) * 1000)
        }
        function onMediaVideoSourceReady(ticket, original, selected) {
            if (!root.playerResolving || ticket !== root.playerResolveTicket
                || original !== root.lastPlayUrl || !root.qmlVideo || root.status.paused === true)
                return
            root.playerResolving = false
            if (root.playerLastFrameAt > 0 && Date.now() - root.playerLastFrameAt < 3000)
                return
            root.loadPlayerSource(selected)
        }
    }

    Timer {
        // State changes arrive through mediaStateChanged.  This is only a
        // recovery poll while a stream negotiates, not a second render loop.
        interval: root.streamBuffering || root.pendingPlayId.length > 0 ? 250 : 5000
        running: root.visible
        repeat: true
        onTriggered: root.refreshLive()
    }

    Timer {
        id: playerRetryTimer
        objectName: "mediaVideoRetryTimer"
        repeat: false
        onTriggered: root.retryPlayer()
    }

    Timer {
        id: playerWatchdogTimer
        objectName: "mediaVideoWatchdogTimer"
        interval: 1000
        running: root.qmlVideo && root.playerWantsPlay
        repeat: true
        onTriggered: root.watchPlayer()
    }

    Connections {
        target: root.videoFullscreen ? fullscreenVideo.videoSink : holeVideo.videoSink
        function onVideoFrameChanged() { root.noteVideoFrame() }
    }

    onVisibleChanged: {
        if (visible) {
            root.refresh()
            if (root.mode === "FETCH")
                root.openFetch()
        } else if (root.surfaceHost && root.surfaceHost.hideMedia)
            root.surfaceHost.hideMedia()
    }

    Item {
        id: mediaFrame
        anchors.fill: parent
        anchors.leftMargin: 6
        anchors.rightMargin: 6
        anchors.topMargin: 4
        anchors.bottomMargin: 6

        Column {
            id: chrome
            width: parent.width
            spacing: 6

                Item {
                    width: parent.width
                    height: 18

                    Row {
                        spacing: 12
                        Repeater {
                            model: ["MUSIC", "RADIO", "TV", "GAME", "FETCH"]
                            delegate: Text {
                                required property string modelData
                                text: modelData
                                color: root.mode === modelData ? "#d8dee9" : "#a8b0b8"
                                font.family: "monospace"
                                font.pixelSize: 12
                                font.bold: root.mode === modelData
                                verticalAlignment: Text.AlignVCenter
                                height: 18
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: root.setMode(modelData)
                                }
                            }
                        }
                    }

                    Text {
                        anchors.right: parent.right
                        height: 18
                        verticalAlignment: Text.AlignVCenter
                        text: root.showDisplay ? "SCREEN · " + root.mode : root.mode
                        color: "#c8cdd4"
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                }

                Text {
                    width: parent.width
                    text: {
                        if (root.playerError)
                            return root.playerError
                        if (root.mode === "FETCH")
                            return String((root.status.fetch || {}).detail || "Torrent search TUI in the workspace. Finished files on the left.")
                        if (root.mode === "MUSIC")
                            return "Choose music from your library. Playback controls are in the strip."
                        if (root.mode === "RADIO")
                            return "Search Radio Browser or paste a stream URL."
                        if (root.mode === "TV")
                            return "Channels on the left. The workspace box is the screen."
                        if (root.mode === "GAME") {
                            var cores = root.status.cores || {}
                            var on = []
                            var names = ["nes", "snes", "n64", "gb", "gba", "genesis", "ps1"]
                            var i
                            for (i = 0; i < names.length; i++) {
                                var row = cores[names[i]] || {}
                                if (row.present)
                                    on.push(row.label || names[i])
                            }
                            if (on.length === 0)
                                return "No emulator binary on PATH yet."
                            return "Ready: " + on.join(" · ") + ". Homebrew Hub on the left. Own dumps go in ~/ROMs/<system>."
                        }
                        return "Pick a ROM. The workspace box becomes the console screen."
                    }
                    color: "#c8cdd4"
                    wrapMode: Text.WordWrap
                    font.pixelSize: 12
                }

                Row {
                    spacing: 12
                    visible: !!(root.status.tools && root.status.tools.cliamp && root.status.tools.cliamp.present)
                        && (root.mode === "MUSIC" || root.mode === "RADIO")
                    Text {
                        text: "OPEN CLIAMP"
                        color: "#c8a97e"
                        font.family: "monospace"
                        font.pixelSize: 12
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.openCliamp()
                        }
                    }
                }

                Rectangle {
                    width: parent.width
                    height: 24
                    color: "#121212"
                    border.color: root.frameBorder
                    border.width: 1
                    visible: root.mode === "RADIO" || root.mode === "TV" || root.mode === "MUSIC" || root.mode === "GAME" || root.mode === "FETCH"

                    TextInput {
                        id: searchBox
                        objectName: "workspaceMediaSearch"
                        anchors.fill: parent
                        anchors.leftMargin: 8
                        anchors.rightMargin: 22
                        color: "#e6e6e6"
                        font.family: "monospace"
                        font.pixelSize: 12
                        clip: true
                        onAccepted: root.search(searchBox.text)
                    }

                    BufferMark {
                        objectName: "mediaSearchBuffer"
                        anchors.right: parent.right
                        anchors.rightMargin: 6
                        anchors.verticalCenter: parent.verticalCenter
                        active: root.searchBusy
                        cell: 5
                    }

                    Text {
                        anchors.fill: searchBox
                        text: root.mode === "RADIO"
                            ? "search radio or paste URL"
                            : (root.mode === "TV"
                                ? "search TV / paste URL / youtube"
                                : (root.mode === "GAME"
                                    ? "search homebrew or local ROM"
                                    : (root.mode === "FETCH"
                                        ? "search finished downloads"
                                        : "search local tracks")))
                        color: "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                        verticalAlignment: Text.AlignVCenter
                        visible: searchBox.text.length === 0 && !searchBox.activeFocus
                    }
                }

                Row {
                    spacing: 12
                    visible: root.mode === "FETCH"
                    Text {
                        text: {
                            var fetch = root.status.fetch || {}
                            if (!fetch.present)
                                return String(fetch.label || "TORLINK MISSING")
                            if (fetch.running)
                                return "REATTACH TORLINK"
                            return "OPEN TORLINK"
                        }
                        color: (root.status.fetch && root.status.fetch.present)
                            ? "#c8a97e"
                            : "#8b949e"
                        font.family: "monospace"
                        font.pixelSize: 12
                        font.bold: true
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            enabled: !!(root.status.fetch && root.status.fetch.present)
                            onClicked: root.openFetch()
                        }
                    }
                    Text {
                        visible: !!(root.status.fetch && root.status.fetch.files)
                        text: "FILES 127.0.0.1:9160"
                        color: "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                }
            }

            Row {
                id: stage
                objectName: "workspaceMediaStage"
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: chrome.bottom
                anchors.topMargin: 8
                anchors.bottom: parent.bottom
                spacing: 8

                ListView {
                    id: catalogList
                    objectName: "workspaceMediaCatalog"
                    width: root.listCollapsed
                        ? 0
                        : (root.showDisplay
                            ? Math.min(240, Math.max(140, stage.width * 0.32))
                            : stage.width)
                    height: parent.height
                    visible: width > 8
                    clip: true
                    spacing: 2
                    model: root.items

                    delegate: Item {
                        required property var modelData
                        width: catalogList.width
                        height: 16

                        readonly property bool rowActive:
                            String(root.now.id || "") === String(modelData.id)
                        readonly property bool rowBuffering:
                            (root.streamBuffering || root.pendingPlayId.length > 0)
                            && (
                                String(modelData.id) === root.bufferingId
                                || String(modelData.id) === root.pendingPlayId
                                || String(modelData.source || "")
                                    === String(root.status.buffering_source || "")
                            )

                        Row {
                            anchors.fill: parent
                            spacing: 6

                            Text {
                                width: Math.max(
                                    24,
                                    parent.width
                                        - (rowMark.visible ? rowMark.width + 6 : 0)
                                )
                                height: 16
                                verticalAlignment: Text.AlignVCenter
                                text: {
                                    var row = modelData
                                    var mark = parent.parent.rowActive ? "▶ " : "  "
                                    var extra = row.system_label
                                        ? (" · " + row.system_label)
                                        : ""
                                    return mark
                                        + String(row.title || row.source || "")
                                        + extra
                                }
                                color: parent.parent.rowActive
                                    ? "#d8dee9"
                                    : "#8b949e"
                                font.family: "monospace"
                                font.pixelSize: 12
                                elide: Text.ElideMiddle
                            }

                            BufferMark {
                                id: rowMark
                                objectName: "mediaItemBuffer"
                                anchors.verticalCenter: parent.verticalCenter
                                active: parent.parent.rowBuffering
                                cell: 5
                            }
                        }

                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.playItem(String(modelData.id || ""))
                        }
                    }

                    Text {
                        visible: catalogList.count === 0 && catalogList.visible
                        anchors.centerIn: parent
                        width: parent.width - 16
                        horizontalAlignment: Text.AlignHCenter
                        text: root.mode === "GAME"
                            ? "No games yet. Search Homebrew Hub or drop files in ~/ROMs."
                            : (root.mode === "FETCH"
                                ? "No finished downloads yet. Search in the TUI, press d to download. Files land in ~/Downloads/torlink."
                                : "No local files in this mode yet.")
                        color: "#c8cdd4"
                        wrapMode: Text.WordWrap
                        font.pixelSize: 12
                    }
                }

                Item {
                    id: hole
                    objectName: "workspaceMediaHole"
                    width: root.showDisplay
                        ? Math.max(16, stage.width - catalogList.width - (catalogList.visible ? 8 : 0))
                        : 0
                    height: parent.height
                    visible: root.showDisplay
                    clip: true

                    Rectangle {
                        anchors.fill: parent
                        color: "#0a0a0a"
                        border.color: root.frameBorder
                        border.width: 1
                    }

                    VideoOutput {
                        id: holeVideo
                        objectName: "workspaceMediaVideo"
                        anchors.fill: parent
                        anchors.margins: 1
                        fillMode: VideoOutput.PreserveAspectFit
                        visible: root.qmlVideo && !root.videoFullscreen
                    }

                    Image {
                        id: holeFrame
                        objectName: "workspaceMediaFrame"
                        anchors.fill: parent
                        anchors.margins: 1
                        fillMode: Image.PreserveAspectFit
                        cache: false
                        asynchronous: false
                        visible: root.libretro
                        source: {
                            if (!root.libretro || !root.surfaceHost)
                                return ""
                            return "image://console/" + String(root.surfaceHost.mediaFrameSeq || 0)
                        }
                    }

                    MouseArea {
                        anchors.fill: parent
                        enabled: root.libretro
                        hoverEnabled: true
                        onClicked: hole.forceActiveFocus()
                    }

                    Keys.onPressed: function(event) {
                        if (!root.libretro || !root.surfaceHost || !root.surfaceHost.mediaGameKey)
                            return
                        root.surfaceHost.mediaGameKey(event.key, true)
                        event.accepted = true
                    }
                    Keys.onReleased: function(event) {
                        if (!root.libretro || !root.surfaceHost || !root.surfaceHost.mediaGameKey)
                            return
                        root.surfaceHost.mediaGameKey(event.key, false)
                        event.accepted = true
                    }
                    focus: root.libretro

                    AudioOutput {
                        id: holeAudio
                    }

                    MediaPlayer {
                        id: holePlayer
                        objectName: "mediaVideoPlayer"
                        videoOutput: root.videoFullscreen ? fullscreenVideo : holeVideo
                        audioOutput: holeAudio
                        onErrorOccurred: function(error, errorString) {
                            if (root.playerResetting)
                                return
                            // Decoder messages can contain signed stream URLs.
                            root.playerError = "Kunde inte spela upp sändningen."
                            root.reportPlayerState()
                            root.schedulePlayerRetry()
                        }
                        onMediaStatusChanged: {
                            if (root.playerResetting || !root.qmlVideo || root.status.paused === true)
                                return
                            if (
                                holePlayer.mediaStatus === MediaPlayer.LoadedMedia
                                || holePlayer.mediaStatus === MediaPlayer.BufferedMedia
                            ) {
                                root.playWhenReady()
                            } else if (holePlayer.mediaStatus === MediaPlayer.InvalidMedia) {
                                root.schedulePlayerRetry()
                            } else if (holePlayer.mediaStatus === MediaPlayer.EndOfMedia && root.lastPlayUrl) {
                                if (root.liveVideo)
                                    root.schedulePlayerRetry()
                                else {
                                    root.playerEnded = true
                                    root.playerWantsPlay = false
                                }
                            }
                            root.reportPlayerState()
                        }
                        onPlaybackStateChanged: {
                            if (root.playerResetting)
                                return
                            root.reportPlayerState()
                            if (root.qmlVideo
                                && root.playerWantsPlay
                                && root.status.paused !== true
                                && holePlayer.playbackState === MediaPlayer.StoppedState)
                                root.schedulePlayerRetry()
                        }
                        onPositionChanged: root.reportClock()
                        onDurationChanged: root.reportClock()
                    }

                    Window {
                        id: fullscreenWindow
                        objectName: "mediaVideoFullscreenWindow"
                        color: "#000000"
                        flags: Qt.FramelessWindowHint
                        visible: false
                        onClosing: root.videoFullscreen = false

                        VideoOutput {
                            id: fullscreenVideo
                            objectName: "mediaFullscreenVideo"
                            anchors.fill: parent
                            fillMode: VideoOutput.PreserveAspectFit
                        }

                        Rectangle {
                            id: fullscreenExitButton
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 18
                            width: fullscreenExitLabel.implicitWidth + 18
                            height: 24
                            radius: 2
                            color: fullscreenExitMouse.containsMouse ? "#303030" : "#181818"
                            opacity: fullscreenExitMouse.containsMouse ? 1.0 : 0.0
                            border.color: "#6a6a6a"
                            border.width: 1
                            z: 2

                            Behavior on opacity {
                                NumberAnimation { duration: 140 }
                            }

                            Text {
                                id: fullscreenExitLabel
                                anchors.centerIn: parent
                                text: "EXIT FULLSCREEN"
                                color: "#e6edf3"
                                font.family: "monospace"
                                font.pixelSize: 11
                                font.bold: true
                            }

                            MouseArea {
                                id: fullscreenExitMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.videoFullscreen = false
                            }
                        }

                        Keys.onPressed: function(event) {
                            if (event.key === Qt.Key_Escape) {
                                root.videoFullscreen = false
                                event.accepted = true
                            }
                        }
                    }

                    Text {
                        anchors.centerIn: parent
                        visible: !root.qmlVideo && !root.libretro && !root.screenOn
                        width: parent.width - 24
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.WordWrap
                        text: root.mode === "TV"
                            ? "SCREEN"
                            : (root.mode === "GAME"
                                ? "CONSOLE"
                                : (root.mode === "FETCH"
                                    ? "TORLINK"
                                    : "DISPLAY"))
                        color: "#3a3a3a"
                        font.family: "monospace"
                        font.pixelSize: 18
                        font.bold: true
                    }

                    BufferMark {
                        objectName: "mediaHoleBuffer"
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.rightMargin: 8
                        anchors.topMargin: root.qmlVideo ? 36 : 8
                        active: root.qmlVideo && root.streamBuffering
                        cell: 6
                    }

                    Rectangle {
                        id: fullscreenButton
                        objectName: "mediaFullscreenButton"
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 8
                        width: fullscreenLabel.implicitWidth + 18
                        height: 22
                        radius: 2
                        color: fullscreenMouse.containsMouse ? "#303030" : "#181818"
                        opacity: fullscreenMouse.containsMouse ? 1.0 : 0.0
                        border.color: "#6a6a6a"
                        border.width: 1
                        visible: root.qmlVideo
                        z: 4

                        Behavior on opacity {
                            NumberAnimation { duration: 140 }
                        }

                        Text {
                            id: fullscreenLabel
                            anchors.centerIn: parent
                            text: root.videoFullscreen ? "EXIT FULLSCREEN" : "FULLSCREEN"
                            color: "#e6edf3"
                            font.family: "monospace"
                            font.pixelSize: 11
                            font.bold: true
                        }

                        MouseArea {
                            id: fullscreenMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.toggleFullscreen()
                        }
                    }

                    Text {
                        id: holeError
                        objectName: "workspaceMediaVideoError"
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        anchors.margins: 8
                        text: root.playerError || String(root.status.embed_error || "")
                        visible: text.length > 0
                        color: "#c8a97e"
                        wrapMode: Text.WordWrap
                        horizontalAlignment: Text.AlignHCenter
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                }
            }
        }
    }
