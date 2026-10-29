
import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls
import QtQuick.Shapes
import QtMultimedia
import QtQuick.Window

Item {
    id: root
    objectName: "workspaceMediaPane"

    property var surfaceHost: null
    property color frameBorder: RuntimeTheme.GGTheme.edge
    property int frameRadius: 4
    property string statusJson: "{}"
    property var catalogItems: []
    property int catalogRevision: -1
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
    property bool autoNextEpisodes: false
    property string autoNextHandledKey: ""
    property bool playerResolving: false
    property int playerResolveTicket: 0
    property int playerGeneration: -1
    property real playerStartedAt: 0
    property real playerLastFrameAt: 0
    property real playerStableSince: 0
    property bool videoFullscreen: false
    property bool fullscreenMasterAudioReady: false
    property int fullscreenMasterVolume: 70
    property int fullscreenVolumePreview: -1
    readonly property int fullscreenVolume: root.fullscreenVolumePreview >= 0 ? root.fullscreenVolumePreview
        : root.fullscreenMasterAudioReady ? root.fullscreenMasterVolume
        : Math.max(0, Math.min(100, Number(root.status.volume === undefined ? 70 : root.status.volume)))
    property string libraryPage: "music"
    property string libraryLetter: "all"
    property string categoryFilter: "all"
    property string languageFilter: "all"
    property bool availableOnly: false
    property var discoveryLanguages: ["sv", "en"]
    property var discoveryTypes: ["live", "movies", "series", "music", "radio", "downloads", "games"]
    property var discoveryLanguageOptions: [{value: "sv", label: "Svenska"}, {value: "en", label: "Engelska"}]
    property string removedItemId: ""
    property string removedItemTitle: ""
    property string diagnosticTitle: ""
    readonly property bool videoLibrary: ["live", "movies", "series"].indexOf(root.libraryPage) >= 0
    readonly property string defaultLanguageFilter: root.videoLibrary ? "sv; en" : "all"
    property string seasonFilter: "all"
    property string localQuery: ""
    property var localCollection: []
    property string localCollectionTitle: ""
    property bool changingLibraryMode: false
    property bool browsePending: false
    property int pageOffset: 0
    property int catalogTotal: 0
    property int catalogPageSize: 80
    property bool catalogHasMore: false
    property string catalogBrowseKey: ""
    property var catalogCategories: []
    property var catalogLanguages: []
    property var catalogSeasons: []
    property string catalogCollection: ""
    property string catalogCollectionKey: ""
    property string expectedCollectionKey: ""
    property string expectedCollectionTitle: ""
    property bool catalogRowsReady: false
    property bool restoringParentView: false
    property string browseError: ""
    property string listContextKey: ""
    property var parentLibraryView: null
    property var pendingListRestore: null
    readonly property bool restoringCatalogPosition: !!root.pendingListRestore && root.pendingListRestore.recheck === true
    property var catalogModel: initialCatalogModel
    property bool chunkBusy: false
    property string chunkError: ""
    property bool chunkNeedsRefresh: false
    property int chunkTicket: 0
    property int chunkOffset: -1
    property string chunkContext: ""
    property string catalogStructureRevision: ""
    property bool catalogSyncing: false
    property bool catalogUpdatePending: false
    property string acceptedCatalogSnapshot: ""
    property var acceptedCatalogHost: null
    property real lastAutomaticSnapshotResetAt: 0
    readonly property bool continuousLibrary: root.pagedLibrary && !!root.surfaceHost.mediaLibraryChunk
    readonly property string streamContext: root.browseKey(root.libraryPage, root.libraryLetter,
        root.categoryFilter, root.languageFilter, root.seasonFilter, root.localQuery, 0) + "|"
        + (root.catalogCollectionKey || root.collectionTitle)
    readonly property bool canLoadMore: root.continuousLibrary && root.displayedPageMatches
        && (root.catalogRowsReady || root.restoringCatalogPosition)
        && root.catalogModel.count > 0 && root.catalogModel.count < root.catalogTotal
    readonly property bool hasLibraryFilters: root.libraryLetter !== "all" || root.categoryFilter !== "all"
        || root.languageFilter !== root.defaultLanguageFilter || root.availableOnly || root.seasonFilter !== "all" || root.localQuery.trim().length > 0
    readonly property bool pagedLibrary: !!root.surfaceHost && !!root.surfaceHost.mediaLibraryBrowse
    readonly property string desiredBrowseKey: root.browseKey(root.libraryPage, root.libraryLetter,
        root.categoryFilter, root.languageFilter, root.seasonFilter, root.localQuery, root.pageOffset)
    readonly property bool displayedPageMatches: !root.pagedLibrary || root.catalogBrowseKey === root.desiredBrowseKey
    readonly property int pageTotal: root.pagedLibrary ? root.catalogTotal : root.filteredItems.length
    readonly property bool hasNextPage: root.pagedLibrary && root.displayedPageMatches
        && root.catalogHasMore && root.pageOffset + root.catalogPageSize < root.catalogTotal
    readonly property color ink: RuntimeTheme.GGTheme.bright
    readonly property color muted: RuntimeTheme.GGTheme.muted
    readonly property color gold: RuntimeTheme.GGTheme.accent
    readonly property var libraryNav: [
        {id: "live", label: "Kanaler", mode: "TV"},
        {id: "movies", label: "Filmer", mode: "TV"},
        {id: "series", label: "Serier", mode: "TV"},
        {id: "music", label: "Musik", mode: "MUSIC"},
        {id: "radio", label: "Radio", mode: "RADIO"},
        {id: "downloads", label: "Hämtat", mode: "FETCH"},
        {id: "games", label: "Spel", mode: "GAME"}
    ]
    readonly property bool libraryBusy: root.searchBusy || root.status.library_busy === true
        || root.browsePending || browseTimer.running
    readonly property bool libraryIndexing: root.status.library_indexing === true
    readonly property var libraryAudit: root.status.library_audit || ({})
    readonly property var libraryBackground: root.status.library_background || ({})
    readonly property bool backgroundRunning: root.libraryBackground.running === true
    readonly property bool backgroundPausing: root.libraryBackground.pausing === true
    readonly property bool hasBackgroundControl: !!root.surfaceHost && !!root.surfaceHost.mediaLibraryBackground
    readonly property bool hasSourceCheckControl: !!root.surfaceHost && !!root.surfaceHost.mediaLibraryCheck
    readonly property bool sourceCheckRunning: root.backgroundRunning
        && (root.libraryBackground.operation === "check" || root.libraryBackground.external === true && root.hasSourceCheckControl)
    readonly property bool expansionRunning: root.backgroundRunning && !root.sourceCheckRunning
    readonly property string backgroundCountDetails: root.discoveryTypes.map(function(key) {
        return root.mediaTypeLabel(key) + " +" + Number(root.libraryBackground["new_" + key] || 0)
    }).concat(root.discoveryTypes.indexOf("series") >= 0
        ? ["Avsnitt +" + Number(root.libraryBackground.new_episodes || 0)] : []).join(" · ")
    readonly property string backgroundCounts: root.discoveryTypes.length <= 2 ? root.backgroundCountDetails
        : (root.discoveryTypes.length === root.libraryNav.length ? "Alla medier" : root.discoveryTypes.length + " mediatyper")
            + " +" + root.discoveryTypes.reduce(function(total, key) { return total + Number(root.libraryBackground["new_" + key] || 0) }, 0)
    readonly property string sourceCheckProgress: root.libraryBackground.check_video_prepared === true && Number(root.libraryAudit.total || 0) > 0
        ? Number(root.libraryAudit.done || 0) + "/" + Number(root.libraryAudit.total)
        : Number(root.libraryBackground.checked_existing || 0) + " kontrollerade"
    readonly property string backgroundSummary: root.backgroundPausing ? "Pausar · sparar framsteg…"
        : root.libraryBackground.phase === "error" ? String(root.libraryBackground.notice || "Källkontrollen kunde inte starta.")
        : root.libraryBackground.operation === "check" ? (root.sourceCheckRunning ? "Källkontroll · "
            : root.libraryBackground.phase === "complete" ? "Kontroll klar · " : "Kontroll pausad · ") + root.sourceCheckProgress
        : root.backgroundRunning ? (String(root.libraryBackground.phase || "").indexOf("discovering_") === 0
            ? "Söker · " + root.mediaTypeLabel(String(root.libraryBackground.phase).slice(12))
            : "Kontrollerar · " + root.backgroundCounts)
        : root.discoveryTypes.some(function(key) { return Number(root.libraryBackground["new_" + key] || 0) > 0 })
            || root.discoveryTypes.indexOf("series") >= 0 && Number(root.libraryBackground.new_episodes || 0) > 0
            ? (root.libraryBackground.phase === "complete" ? "Klar · " : "Pausad · ") + root.backgroundCounts : ""
    readonly property string auditProgressText: Number(root.libraryAudit.total || 0) > 0
        ? "Källkontroll " + Number(root.libraryAudit.done || 0) + "/" + Number(root.libraryAudit.total)
            + " · Bibliotek " + root.pageTotal
        : ""
    readonly property string loadingItemId: String(root.status.library_loading_id === undefined
        ? root.pendingPlayId : root.status.library_loading_id || "")
    readonly property string collectionTitle: root.pagedLibrary ? root.catalogCollection
        : root.localCollectionTitle || String(root.status.library_collection || "")
    readonly property string libraryError: root.pagedLibrary
        ? root.browseError || String(root.status.library_selection_error || "")
        : String(root.status.library_error || "")
    readonly property string libraryQuery: String(root.status.library_query || "")
    readonly property var pageItems: root.pagedLibrary ? root.catalogItems : root.makePageItems()
    readonly property var filteredItems: root.pagedLibrary
        ? (root.displayedPageMatches ? root.catalogItems : []) : root.filterItems()
    readonly property var categoryOptions: root.pagedLibrary
        ? root.catalogCategories : root.filterOptions(root.libraryPage === "music" ? "artist" : "category",
            root.libraryPage === "music" ? "Alla artister" : "Alla kategorier")
    readonly property var languageOptions: root.pagedLibrary
        ? root.catalogLanguages : root.filterOptions("language", "Alla språk")
    readonly property var seasonOptions: root.pagedLibrary
        ? root.catalogSeasons : root.makeSeasonOptions()
    signal nowPlayingChanged(string label)

    readonly property var status: {
        try {
            return JSON.parse(root.statusJson || "{}")
        } catch (err) {
            return {}
        }
    }

    readonly property var items: root.catalogItems

    readonly property string mode: String(root.status.mode || "MUSIC")
    readonly property bool screenOn: String(root.status.screen || "") === "EMBED"
    readonly property var now: root.status.now || {}
    readonly property bool qmlVideo: String(root.status.backend || "") === "qml"
    readonly property bool liveVideo: root.qmlVideo
        && root.now.is_live !== false && root.now.media !== "vod"
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

    function browseKey(page, letter, category, language, season, query, offset, available) {
        return JSON.stringify([String(page), String(letter || "all"), String(category || "all"),
            String(language || "all"), String(season || "all"), String(query || "").trim(), Number(offset || 0),
            available === undefined ? root.availableOnly : available === true])
    }

    function snapshotBrowseKey(snapshot) {
        return root.browseKey(snapshot.library_page, snapshot.library_letter, snapshot.library_category,
            snapshot.library_language, snapshot.library_season, snapshot.library_query, snapshot.library_offset,
            snapshot.library_available_only === true)
    }

    function queueBrowse(resetOffset) {
        if (!root.pagedLibrary || !root.playerReady || !root.visible)
            return
        if (resetOffset && root.pageOffset !== 0)
            root.pageOffset = 0
        root.browseError = ""
        root.cancelChunk()
        if (!root.restoringParentView && !root.displayedPageMatches) {
            root.catalogRowsReady = false
            root.catalogItems = []
            root.catalogModel.clear()
            catalogList.currentIndex = -1
            catalogList.forceLayout()
        }
        browseTimer.restart()
    }

    function browseNow() {
        if (!root.pagedLibrary || !root.visible)
            return
        browseTimer.stop()
        root.browsePending = true
        root.browseError = ""
        try {
            if (root.surfaceHost.mediaLibraryBrowseFiltered)
                root.applyStatus(root.surfaceHost.mediaLibraryBrowseFiltered(root.libraryPage, root.libraryLetter,
                root.categoryFilter, root.languageFilter, root.seasonFilter, root.localQuery.trim(), root.pageOffset,
                root.availableOnly))
            else
                root.applyStatus(root.surfaceHost.mediaLibraryBrowse(root.libraryPage, root.libraryLetter,
                    root.categoryFilter, root.languageFilter, root.seasonFilter, root.localQuery.trim(), root.pageOffset))
        } catch (err) {
            root.browsePending = false
            root.browseError = "Kunde inte läsa biblioteket. Försök igen."
        }
    }

    function browsePage(direction) {
        if (root.continuousLibrary) {
            root.loadMore(true)
            return
        }
        if (!root.pagedLibrary || root.libraryBusy)
            return
        if ((direction > 0 && !root.hasNextPage) || (direction < 0 && root.pageOffset <= 0))
            return
        root.pageOffset = Math.max(0, root.pageOffset + direction * root.catalogPageSize)
        root.browseNow()
        catalogList.currentIndex = -1
        catalogList.positionViewAtBeginning()
    }

    function cancelChunk() {
        root.chunkTicket += 1
        root.chunkBusy = false
        root.chunkError = ""
        root.chunkNeedsRefresh = false
        root.chunkOffset = -1
        chunkTimeout.stop()
    }

    function maybeLoadMore() {
        if (!root.canLoadMore || root.chunkBusy || root.chunkError || root.libraryBusy
            || !root.visible || catalogSyncTimer.running || root.catalogSyncing)
            return
        if (root.restoringCatalogPosition) {
            root.restoreCatalogPosition()
            return
        }
        // Keep one complete block in front of the viewport, with up to one
        // additional block for a fast flick. The next read starts long before
        // the last visible row instead of stopping at every80-row boundary.
        var first = Math.max(0, Math.floor((catalogList.contentY - catalogList.originY) / 50))
        var visibleRows = Math.max(1, Math.ceil(catalogList.height / 50))
        var velocityRows = Math.min(80, Math.ceil(Math.max(0, catalogList.verticalVelocity) * .9 / 50))
        var ahead = 80 + velocityRows
        if (first + visibleRows + ahead > root.catalogModel.count)
            root.loadMore(false)
    }

    function loadMore(retry) {
        if (!root.canLoadMore || root.chunkBusy || root.libraryBusy || !root.visible)
            return
        if (root.chunkError && !retry)
            return
        root.chunkError = ""
        root.chunkBusy = true
        root.chunkOffset = root.catalogModel.count
        root.chunkContext = root.streamContext
        root.chunkTicket += 1
        chunkTimeout.restart()
        try {
            if (root.surfaceHost.mediaLibraryChunkFiltered)
                root.surfaceHost.mediaLibraryChunkFiltered(root.libraryPage, root.libraryLetter,
                root.categoryFilter, root.languageFilter, root.seasonFilter, root.localQuery.trim(),
                root.chunkOffset, root.chunkTicket, root.availableOnly)
            else
                root.surfaceHost.mediaLibraryChunk(root.libraryPage, root.libraryLetter,
                    root.categoryFilter, root.languageFilter, root.seasonFilter, root.localQuery.trim(), root.chunkOffset, root.chunkTicket)
        } catch (err) {
            root.chunkBusy = false
            root.chunkError = "Kunde inte läsa fler titlar. Försök igen."
            chunkTimeout.stop()
        }
    }

    function retryChunk() {
        if (root.chunkNeedsRefresh) {
            root.rememberCatalogPosition()
            root.cancelChunk()
            root.catalogRowsReady = false
            root.catalogItems = []
            root.catalogBrowseKey = ""
            root.catalogModel.clear()
            root.listContextKey = ""
            catalogList.forceLayout()
            root.browseNow()
        } else {
            root.loadMore(true)
        }
    }

    function acceptChunk(ticket, raw) {
        if (!root.chunkBusy || Number(ticket) !== root.chunkTicket || root.chunkContext !== root.streamContext)
            return
        var page
        try { page = JSON.parse(String(raw || "{}")) } catch (err) { page = {} }
        var context = root.browseKey(page.library_page, page.library_letter, page.library_category,
            page.library_language, page.library_season, page.library_query, 0)
            + "|" + String(page.library_collection_key || page.library_collection || "")
        if (context !== root.chunkContext || Number(page.library_offset) !== root.chunkOffset)
            return
        root.chunkBusy = false
        chunkTimeout.stop()
        if (page.library_snapshot_invalid === true) {
            root.chunkNeedsRefresh = true
            // Real withdrawals invalidate this immutable browsing session.
            // Refresh locally once; repeated invalidation stays an explicit
            // retry instead of creating an endless automatic request loop.
            if (Date.now() - root.lastAutomaticSnapshotResetAt >= 1000) {
                root.lastAutomaticSnapshotResetAt = Date.now()
                Qt.callLater(root.retryChunk)
            } else {
                root.chunkError = "Katalogen har ändrats. Uppdatera listan för att fortsätta."
            }
            return
        }
        if (page.library_chunk_error) {
            root.chunkError = String(page.library_chunk_error)
            return
        }
        if (root.catalogStructureRevision.length > 0 && page.library_catalog_revision !== undefined
            && String(page.library_catalog_revision) !== root.catalogStructureRevision) {
            root.chunkNeedsRefresh = true
            root.chunkError = "Katalogen har ändrats. Uppdatera listan för att fortsätta."
            return
        }
        var rows = page.items || []
        if (root.catalogModel.count !== root.chunkOffset || !rows.length) {
            root.chunkNeedsRefresh = true
            root.chunkError = "Katalogen har ändrats. Uppdatera listan för att fortsätta."
            return
        }
        // Append only this block. Previously visited titles and their delegates
        // keep their identity; the ListView creates just visible delegates.
        for (var i = 0; i < Math.min(80, rows.length); ++i)
            root.catalogModel.append({key: String(rows[i].id || root.chunkOffset + i),
                signature: JSON.stringify(rows[i]), entry: rows[i]})
        root.catalogTotal = Math.max(root.catalogModel.count, Number(page.library_total || 0))
        root.catalogHasMore = root.catalogModel.count < root.catalogTotal
        root.chunkOffset = -1
        if (root.restoringCatalogPosition)
            root.restoreCatalogPosition()
        Qt.callLater(root.maybeLoadMore)
    }

    function rememberCatalogPosition() {
        if (root.restoringCatalogPosition || root.pendingListRestore || !root.catalogModel.count)
            return
        var y = catalogList.contentY - catalogList.originY
        if (y <= 1 && catalogList.currentIndex < 0)
            return
        var first = Math.max(0, Math.min(root.catalogModel.count - 1, Math.floor(y / 50)))
        var anchors = []
        for (var i = first; i < Math.min(first + 3, root.catalogModel.count); ++i) {
            var row = root.catalogModel.get(i).entry
            anchors.push({id: String(row.id || ""), title: root.rowTitle(row), offset: y - i * 50})
        }
        var selected = catalogList.currentIndex >= 0 && catalogList.currentIndex < root.catalogModel.count
            ? root.catalogModel.get(catalogList.currentIndex).entry : ({})
        root.pendingListRestore = {recheck: true, context: root.streamContext, firstIndex: first,
            firstOffset: y - first * 50, anchors: anchors, selectedId: String(selected.id || ""),
            selectedTitle: selected.id ? root.rowTitle(selected) : "",
            target: Math.min(root.catalogModel.count,
                Math.max(first + Math.ceil(catalogList.height / 50) + 1, catalogList.currentIndex + 1))}
        root.catalogRowsReady = false
    }

    function restoreCatalogPosition() {
        var saved = root.pendingListRestore
        if (!saved || saved.recheck !== true)
            return
        if (saved.context !== root.streamContext) {
            root.pendingListRestore = null
            return
        }
        if (root.catalogModel.count < Math.min(saved.target, root.catalogTotal) && root.canLoadMore) {
            if (!root.chunkBusy && !root.chunkError && !root.libraryBusy)
                root.loadMore(false)
            return
        }
        var selected = -1
        var anchor = -1
        var anchorOffset = saved.firstOffset
        for (var a = 0; a < saved.anchors.length && anchor < 0; ++a) {
            for (var i = 0; i < root.catalogModel.count; ++i) {
                var row = root.catalogModel.get(i).entry
                if (String(row.id) === saved.anchors[a].id) {
                    anchor = i
                    anchorOffset = saved.anchors[a].offset
                    break
                }
            }
        }
        for (var j = 0; j < root.catalogModel.count; ++j) {
            if (String(root.catalogModel.get(j).entry.id) === saved.selectedId) { selected = j; break }
        }
        // A different healthy source may represent the same displayed title.
        for (var k = 0; k < root.catalogModel.count && (anchor < 0 || selected < 0); ++k) {
            var title = root.rowTitle(root.catalogModel.get(k).entry)
            if (anchor < 0 && saved.anchors.length && title === saved.anchors[0].title) anchor = k
            if (selected < 0 && saved.selectedTitle && title === saved.selectedTitle) selected = k
        }
        if (anchor < 0) anchor = Math.min(saved.firstIndex, root.catalogModel.count - 1)
        root.catalogSyncing = true
        catalogList.currentIndex = selected
        catalogList.forceLayout()
        if (anchor >= 0)
            catalogList.contentY = Math.max(catalogList.originY,
                Math.min(catalogList.originY + Math.max(0, catalogList.contentHeight - catalogList.height),
                    catalogList.originY + anchor * 50 + anchorOffset))
        root.pendingListRestore = null
        root.catalogRowsReady = true
        root.catalogSyncing = false
    }

    function optionRows(rows, label, maximum) {
        var output = [{value: "all", label: label}]
        if (!rows || rows.length === undefined)
            return output
        // Option lists are also bounded; a corrupt provider cannot grow the menu indefinitely.
        for (var i = 0; i < Math.min(Number(maximum || 256), rows.length); ++i) {
            var row = rows[i]
            var value = typeof row === "object" ? String(row.value) : String(row)
            if (value !== "all")
                output.push({value: value, label: typeof row === "object" ? String(row.label || value) : value})
        }
        return output
    }

    // Health checks append titles while the user browses. Keep delegate identity,
    // the focused title and the first visible row instead of resetting the view.
    function syncCatalogModel() {
        var rows = root.filteredItems
        var context = root.desiredBrowseKey + "|" + (root.catalogCollectionKey || root.collectionTitle)
        var sameContext = context === root.listContextKey
        if (root.restoringCatalogPosition && root.pendingListRestore.context !== root.streamContext)
            root.pendingListRestore = null
        if (root.continuousLibrary) {
            if (!root.displayedPageMatches)
                return
            root.catalogSyncing = true
            if (!sameContext)
                root.catalogModel.clear()
            // A normal player/status refresh updates just the first catalogue
            // block. It must not discard blocks already visited by scrolling.
            var changedOrder = false
            for (var c = 0; sameContext && c < Math.min(rows.length, root.catalogModel.count); ++c) {
                var current = root.catalogModel.get(c).entry
                if (String(current.id) !== String(rows[c].id) && root.rowTitle(current) !== root.rowTitle(rows[c])) {
                    changedOrder = true
                    break
                }
            }
            if (changedOrder && root.catalogModel.count > rows.length)
                root.catalogModel.clear()
            for (var p = 0; p < rows.length; ++p) {
                var record = {key: String(rows[p].id || p), signature: JSON.stringify(rows[p]), entry: rows[p]}
                if (p >= root.catalogModel.count)
                    root.catalogModel.append(record)
                else if (root.catalogModel.get(p).signature !== record.signature)
                    root.catalogModel.set(p, record)
            }
            if (root.catalogModel.count > root.catalogTotal)
                root.catalogModel.remove(root.catalogTotal, root.catalogModel.count - root.catalogTotal)
            root.listContextKey = context
            if (root.restoringCatalogPosition) {
                catalogList.forceLayout()
                root.catalogSyncing = false
                root.restoreCatalogPosition()
                return
            }
            root.catalogRowsReady = true
            catalogList.forceLayout()
            var saved = root.pendingListRestore
            if (saved && rows.length) {
                root.pendingListRestore = null
                catalogList.currentIndex = Math.min(root.catalogModel.count - 1, Number(saved.selectedIndex || 0))
                Qt.callLater(function() {
                    catalogList.contentY = Math.max(catalogList.originY,
                        Math.min(catalogList.originY + Math.max(0, catalogList.contentHeight - catalogList.height),
                            catalogList.originY + Number(saved.scrollY || 0)))
                    root.catalogSyncing = false
                    root.maybeLoadMore()
                })
            } else if (!sameContext || changedOrder) {
                catalogList.currentIndex = -1
                catalogList.positionViewAtBeginning()
                Qt.callLater(function() {
                    catalogList.positionViewAtBeginning()
                    catalogList.contentY = catalogList.originY
                    root.catalogSyncing = false
                    root.maybeLoadMore()
                })
            } else {
                root.catalogSyncing = false
                Qt.callLater(root.maybeLoadMore)
            }
            return
        }
        var oldY = catalogList.contentY
        var firstIndex = Math.max(0, Math.floor((oldY - catalogList.originY) / 50))
        var firstId = firstIndex < catalogModel.count ? String(catalogModel.get(firstIndex).key) : ""
        var firstOffset = oldY - catalogList.originY - firstIndex * 50
        var selectedId = catalogList.currentIndex >= 0 && catalogList.currentIndex < catalogModel.count
            ? String(catalogModel.get(catalogList.currentIndex).key) : ""
        for (var i = 0; i < rows.length; ++i) {
            var key = String(rows[i].id || i)
            var signature = JSON.stringify(rows[i])
            if (i >= catalogModel.count) {
                catalogModel.append({key: key, signature: signature, entry: rows[i]})
            } else if (String(catalogModel.get(i).key) !== key) {
                var found = -1
                for (var j = i + 1; j < catalogModel.count; ++j) {
                    if (String(catalogModel.get(j).key) === key) { found = j; break }
                }
                if (found >= 0)
                    catalogModel.move(found, i, 1)
                else
                    catalogModel.insert(i, {key: key, signature: signature, entry: rows[i]})
            }
            if (catalogModel.get(i).signature !== signature)
                catalogModel.set(i, {key: key, signature: signature, entry: rows[i]})
        }
        if (catalogModel.count > rows.length)
            catalogModel.remove(rows.length, catalogModel.count - rows.length)
        root.listContextKey = context
        root.catalogRowsReady = true
        catalogList.forceLayout()
        var restore = root.pendingListRestore
        if (restore && rows.length > 0) {
            root.pendingListRestore = null
            selectedId = String(restore.selectedId || "")
            firstId = String(restore.firstId || "")
            firstOffset = Number(restore.firstOffset || 0)
            sameContext = true
        }
        var selectedIndex = -1
        var anchorIndex = -1
        for (var k = 0; k < catalogModel.count; ++k) {
            if (String(catalogModel.get(k).key) === selectedId) selectedIndex = k
            if (String(catalogModel.get(k).key) === firstId) anchorIndex = k
        }
        catalogList.currentIndex = sameContext ? selectedIndex : -1
        if (sameContext && anchorIndex >= 0)
            catalogList.contentY = Math.max(catalogList.originY,
                Math.min(catalogList.originY + Math.max(0, catalogList.contentHeight - catalogList.height),
                    catalogList.originY + anchorIndex * 50 + firstOffset))
        else if (!sameContext)
            catalogList.positionViewAtBeginning()
    }

    function rememberParentView() {
        var first = Math.max(0, Math.floor((catalogList.contentY - catalogList.originY) / 50))
        root.parentLibraryView = {letter: root.libraryLetter, category: root.categoryFilter,
            availableOnly: root.availableOnly,
            language: root.languageFilter, query: root.localQuery, offset: root.pageOffset,
            selectedId: catalogList.currentIndex >= 0 && catalogList.currentIndex < catalogModel.count
                ? String(catalogModel.get(catalogList.currentIndex).key) : "",
            firstId: first < catalogModel.count ? String(catalogModel.get(first).key) : "",
            firstOffset: catalogList.contentY - catalogList.originY - first * 50,
            selectedIndex: catalogList.currentIndex, scrollY: catalogList.contentY - catalogList.originY,
            items: root.catalogItems, total: root.catalogTotal, pageSize: root.catalogPageSize,
            hasMore: root.catalogHasMore, browseKey: root.catalogBrowseKey,
            categories: root.catalogCategories, languages: root.catalogLanguages, seasons: root.catalogSeasons}
        if (root.continuousLibrary) {
            root.catalogRowsReady = false
            root.parentLibraryView.model = root.catalogModel
            root.parentLibraryView.modelContext = root.listContextKey
            root.parentLibraryView.structureRevision = root.catalogStructureRevision
            root.catalogModel = catalogModelComponent.createObject(root)
            root.catalogItems = []
            root.listContextKey = ""
            root.cancelChunk()
            catalogList.forceLayout()
        }
    }

    onFilteredItemsChanged: catalogSyncTimer.restart()
    Timer { id: catalogSyncTimer; interval: 0; onTriggered: root.syncCatalogModel() }
    ListModel { id: initialCatalogModel; dynamicRoles: true }
    Component { id: catalogModelComponent; ListModel { dynamicRoles: true } }
    Timer {
        id: chunkTimeout
        interval: 10000
        onTriggered: {
            root.chunkTicket += 1
            root.chunkBusy = false
            root.chunkError = "Det tog för lång tid att läsa fler titlar. Försök igen."
        }
    }

    onPagedLibraryChanged: root.queueBrowse(true)
    onLibraryPageChanged: root.queueBrowse(true)
    onLibraryLetterChanged: root.queueBrowse(true)
    onCategoryFilterChanged: root.queueBrowse(true)
    onLanguageFilterChanged: root.queueBrowse(true)
    onAvailableOnlyChanged: root.queueBrowse(true)
    onSeasonFilterChanged: root.queueBrowse(true)
    onLocalQueryChanged: root.queueBrowse(true)
    onPageOffsetChanged: root.queueBrowse(false)

    function contentType(row) {
        if (row.content_type)
            return String(row.content_type).toLowerCase()
        if (row.season !== undefined || row.episode !== undefined || row.series)
            return "episode"
        if (row.kind === "MUSIC" || row.kind === "RADIO" || row.media === "audio")
            return "music"
        return row.stream === true || row.media === "stream" ? "live" : "movie"
    }

    function rowValue(row, field) {
        var value = row[field]
        if (value === undefined || value === null)
            return ""
        if (Array.isArray(value))
            return value.join(" / ")
        return String(value)
    }

    function languageLabel(row) {
        if (row.language_label) return String(row.language_label)
        var names = {sv: "Svenska", en: "Engelska", no: "Norska", da: "Danska", fi: "Finska",
            de: "Tyska", fr: "Franska", es: "Spanska", it: "Italienska", ar: "Arabiska"}
        return root.rowValue(row, "language").split(/\s*[;,/]\s*/).map(function(code) {
            if (names[code]) return names[code]
            var option = root.discoveryLanguageOptions.filter(function(item) { return item.value === code })[0]
            return option ? option.label : "Okänt språk"
        }).join(" / ")
    }

    function chooseDiscoveryLanguage(value) {
        var chosen = root.discoveryLanguages.slice()
        var index = chosen.indexOf(value)
        if (index >= 0) {
            if (chosen.length === 1) return
            chosen.splice(index, 1)
        } else chosen.push(value)
        root.discoveryLanguages = chosen
        if (root.surfaceHost && root.surfaceHost.mediaLibraryLanguages)
            root.applyStatus(root.surfaceHost.mediaLibraryLanguages(chosen.join("; ")))
    }

    function mediaTypeLabel(value) {
        var option = root.libraryNav.filter(function(row) { return row.id === value })[0]
        return option ? option.label : "Media"
    }

    function setDiscoveryTypes(chosen) {
        if (!chosen.length || root.backgroundRunning || root.backgroundPausing) return
        root.discoveryTypes = root.libraryNav.filter(function(row) { return chosen.indexOf(row.id) >= 0 })
            .map(function(row) { return row.id })
        if (root.surfaceHost && root.surfaceHost.mediaLibraryTypes)
            root.applyStatus(root.surfaceHost.mediaLibraryTypes(root.discoveryTypes.join("; ")))
    }

    function chooseDiscoveryType(value) {
        var chosen = root.discoveryTypes.slice()
        var index = chosen.indexOf(value)
        if (index >= 0) {
            if (chosen.length === 1) return
            chosen.splice(index, 1)
        } else chosen.push(value)
        root.setDiscoveryTypes(chosen)
    }

    function diagnoseItem(row) {
        if (!root.surfaceHost || !root.surfaceHost.mediaLibraryDiagnose) return
        root.diagnosticTitle = root.rowTitle(row)
        root.applyStatus(root.surfaceHost.mediaLibraryDiagnose(String(row.id)))
        diagnosticPopup.open()
    }

    function removeItem(row) {
        if (!root.surfaceHost || !root.surfaceHost.mediaLibraryHideSource) return
        root.removedItemId = String(row.id)
        root.removedItemTitle = root.rowTitle(row)
        root.applyStatus(root.surfaceHost.mediaLibraryHideSource(root.removedItemId, true))
    }

    function undoRemove() {
        if (root.removedItemId && root.surfaceHost && root.surfaceHost.mediaLibraryHideSource)
            root.applyStatus(root.surfaceHost.mediaLibraryHideSource(root.removedItemId, false))
        root.removedItemId = ""
        root.removedItemTitle = ""
    }

    function rowTitle(row) {
        return String(row.title || row.series || row.source || "Namnlös")
    }

    function compareTitles(a, b) {
        var left = root.rowTitle(a).toLocaleLowerCase()
        var right = root.rowTitle(b).toLocaleLowerCase()
        var result = left.localeCompare(right)
        return result || String(a.id || "").localeCompare(String(b.id || ""))
    }

    function makePageItems() {
        // Compatibility for an old/offline bridge only. Production receives a prepared page.
        var rows = (root.localCollectionTitle ? root.localCollection : root.items).slice(0, 120)
        var output = []
        var groups = {}
        var parents = {}
        var collection = root.collectionTitle.length > 0
        if (!collection) {
            rows.forEach(function(row) {
                if (root.contentType(row) === "series" || root.contentType(row) === "collection") {
                    parents[root.rowTitle(row)] = true
                    if (row.collection_id)
                        parents[String(row.collection_id)] = true
                }
            })
        }
        for (var i = 0; i < rows.length; ++i) {
            var row = rows[i]
            var type = root.contentType(row)
            if (!collection && root.mode === "TV") {
                if (root.libraryPage === "live" && type !== "live")
                    continue
                if (root.libraryPage === "movies" && type !== "movie" && type !== "video")
                    continue
                if (root.libraryPage === "series") {
                    if (type !== "series" && type !== "episode" && type !== "collection")
                        continue
                    var series = String(row.series || row.series_title || "")
                    if (type === "episode" && (parents[series] || parents[String(row.collection_id || "")]))
                        continue
                    if (type === "episode" && series) {
                        if (!groups[series]) {
                            groups[series] = {
                                id: "ui-series:" + series, title: series,
                                content_type: "series", language: row.language,
                                category: row.category, provider: row.provider,
                                _members: []
                            }
                            output.push(groups[series])
                        }
                        groups[series]._members.push(row)
                        continue
                    }
                }
            }
            output.push(row)
        }
        output.sort(collection ? function(a, b) {
            var season = Number(a.season || 0) - Number(b.season || 0)
            var episode = Number(a.episode || 0) - Number(b.episode || 0)
            return season || episode || root.compareTitles(a, b)
        } : root.compareTitles)
        return output
    }

    function filterItems() {
        var query = root.localQuery.trim().toLocaleLowerCase()
        return root.pageItems.filter(function(row) {
            if (root.libraryLetter !== "all") {
                var first = root.rowTitle(row).trim().charAt(0).toLocaleUpperCase()
                if (root.libraryLetter === "#" ? /^[A-ZÅÄÖ]$/.test(first) : first !== root.libraryLetter)
                    return false
            }
            if (root.categoryFilter !== "all" && root.rowValue(row, "category") !== root.categoryFilter)
                return false
            var rowLanguages = root.rowValue(row, "language").split(/\s*[;,/]\s*/)
            var chosenLanguages = root.languageFilter.split(/\s*[;,/]\s*/)
            if (root.languageFilter === "unknown" ? rowLanguages.join("").length > 0
                : root.languageFilter !== "all" && !chosenLanguages.some(function(code) { return rowLanguages.indexOf(code) >= 0 }))
                return false
            if (root.availableOnly && ["verified", "available"].indexOf(String(row.availability || "")) < 0)
                return false
            if (root.seasonFilter !== "all" && String(row.season === undefined ? 1 : row.season) !== root.seasonFilter)
                return false
            if (!query || root.libraryQuery === root.localQuery)
                return true
            return [root.rowTitle(row), row.series, row.artist, row.provider, row.source_label,
                row.category, row.language, row.system_label].join(" ").toLocaleLowerCase().indexOf(query) >= 0
        })
    }

    function filterOptions(field, label) {
        if (field === "language") {
            var languageRows = [{value: "all", label: "Alla språk"}, {value: "sv; en", label: "Svenska och engelska"}]
            var languageCodes = ["sv", "en"]
            root.pageItems.forEach(function(row) {
                root.rowValue(row, "language").split(/\s*[;,/]\s*/).forEach(function(code) {
                    if (code && languageCodes.indexOf(code) < 0) languageCodes.push(code)
                })
            })
            return languageRows.concat(languageCodes.map(function(code) { return {value: code, label: root.languageLabel({language: code})} }))
                .concat([{value: "unknown", label: "Okänt språk · identifiering väntar"}])
        }
        var values = []
        var seen = {}
        root.pageItems.forEach(function(row) {
            var value = root.rowValue(row, field)
            if (value && !seen[value]) {
                seen[value] = true
                values.push({value: value, label: value})
            }
        })
        values.sort(function(a, b) { return a.label.localeCompare(b.label) })
        return [{value: "all", label: label}].concat(values)
    }

    function makeSeasonOptions() {
        var values = []
        var seen = {}
        if (root.collectionTitle) {
            root.pageItems.forEach(function(row) {
                var value = String(row.season === undefined ? 1 : row.season)
                if (!seen[value]) {
                    seen[value] = true
                    values.push({value: value, label: Number(value) === 0 ? "Utan säsongsnummer" : "Säsong " + value})
                }
            })
        }
        values.sort(function(a, b) { return Number(a.value) - Number(b.value) })
        return [{value: "all", label: "Alla säsonger"}].concat(values)
    }

    function itemDetail(row) {
        var type = root.contentType(row)
        if (String(row.kind || "") === "MUSIC") {
            var musicParts = [row.media === "file" || row.local === true ? "LOKAL" : "ONLINE",
                String(row.artist || "Okänd artist")]
            if (row.album) musicParts.push(String(row.album))
            return musicParts.join(" · ")
        }
        if (String(row.kind || "") === "RADIO") {
            var radioParts = ["RADIO"]
            if (row.language) radioParts.push(root.languageLabel(row))
            if (row.country || row.provider) radioParts.push(String(row.country || row.provider))
            return radioParts.join(" · ")
        }
        var labels = {live: "LIVE", movie: "FILM", video: "VIDEO", series: "SERIE", collection: "SAMLING", music: "MUSIK"}
        var parts = []
        if (type === "episode") {
            var season = String(row.season === undefined ? 1 : row.season)
            var episode = String(row.episode === undefined ? "?" : row.episode)
            var position = []
            if (Number(season) > 0)
                position.push("S" + (season.length < 2 ? "0" : "") + season)
            if (Number(episode) > 0)
                position.push("E" + (episode.length < 2 ? "0" : "") + episode)
            parts.push(position.length ? position.join("") : "AVSNITT / INSPELNING")
        } else {
            parts.push(labels[type] || row.system_label || (root.mode === "RADIO" ? "RADIO" : "LOKALT"))
        }
        if (row._members)
            parts.push(row._members.length + " avsnitt")
        if (type !== "episode" && row.year)
            parts.push(String(row.year))
        if (row.language || root.videoLibrary)
            parts.push(root.languageLabel(row))
        if (["live", "movie", "episode", "series"].indexOf(type) >= 0)
            parts.push(["available", "verified"].indexOf(String(row.availability || "")) >= 0 ? "Tillgänglig" : "Ej kontrollerad")
        var provider = row.provider || row.source_label || row.artist || row.country || row.year
        if (provider)
            parts.push(String(provider))
        return parts.join(" · ")
    }

    function displayTitle(row) {
        var title = root.rowTitle(row)
        if (root.contentType(row) === "episode" && Number(row.episode || 0) > 0)
            title = title.replace(/^S\d+\s*E\d+\s*[-–—:.]?\s*/i, "")
        return title || root.rowTitle(row)
    }

    function availabilityDetail(row) {
        if (row.media === "file" || row.local === true)
            return "Lokal fil · spelas direkt från datorn."
        if (row.availability === "failed")
            return "Senast otillgänglig. Välj titeln för att försöka igen."
        if (row.availability === "available")
            return "Källan är tillgänglig enligt senaste snabbkontrollen."
        if (row.availability === "verified") {
            if (row.availability_scope === "checked_episodes")
                return "Avsnitt finns tillgängliga. Välj ett avsnitt för att spela."
            if (row.availability_fresh === false)
                return "Tidigare provspelad. En ny källkontroll görs när du trycker på play."
            return "Provspelad vid senaste källkontrollen."
        }
        return "Katalogpost · källan öppnas när du trycker Play."
    }

    function clearFilters() {
        root.pageOffset = 0
        root.libraryLetter = "all"
        root.categoryFilter = "all"
        root.languageFilter = root.defaultLanguageFilter
        root.availableOnly = false
        root.seasonFilter = "all"
        root.localQuery = ""
        searchBox.text = ""
    }

    function selectPage(page) {
        var target = root.libraryNav.filter(function(row) { return row.id === page })[0]
        if (!target)
            return
        var sameLibrary = target.mode === root.mode
        if (root.collectionTitle)
            root.goBack()
        var selectedLetter = root.libraryLetter
        var selectedQuery = root.localQuery
        root.libraryPage = page
        if (!sameLibrary)
            root.clearFilters()
        else
            root.seasonFilter = "all"
        if (sameLibrary) {
            root.libraryLetter = selectedLetter
            root.localQuery = selectedQuery
            searchBox.text = selectedQuery
        }
        if (target.mode !== root.mode)
            root.setMode(target.mode)
        if (!sameLibrary && selectedQuery.length > 0) {
            root.localQuery = selectedQuery
            searchBox.text = selectedQuery
        }
        catalogList.currentIndex = -1
        catalogList.positionViewAtBeginning()
    }

    function activateItem(row) {
        if (!row)
            return
        if (row._members) {
            root.rememberParentView()
            root.localCollection = row._members
            root.localCollectionTitle = root.rowTitle(row)
            root.clearFilters()
            root.languageFilter = "all"
        } else if ((root.contentType(row) === "series" || root.contentType(row) === "collection")
                   && root.surfaceHost && root.surfaceHost.mediaOpenCollection) {
            root.rememberParentView()
            root.expectedCollectionKey = String(row.collection_key || "")
            root.expectedCollectionTitle = root.rowTitle(row)
            root.clearFilters()
            root.languageFilter = "all"
            root.availableOnly = false
            if (root.pagedLibrary) {
                browseTimer.stop()
                root.browsePending = true
                root.catalogBrowseKey = ""
                root.catalogCollection = root.rowTitle(row)
                root.catalogCollectionKey = root.expectedCollectionKey
                root.catalogTotal = 0
            }
            root.applyStatus(root.surfaceHost.mediaOpenCollection(String(row.id)))
        } else {
            root.playItem(String(row.id || ""))
        }
    }

    function goBack() {
        var parentView = root.parentLibraryView
        root.restoringParentView = true
        root.catalogRowsReady = false
        root.expectedCollectionKey = ""
        root.expectedCollectionTitle = ""
        root.localCollection = []
        root.localCollectionTitle = ""
        root.clearFilters()
        if (root.pagedLibrary) {
            browseTimer.stop()
            root.browsePending = true
            root.catalogCollection = ""
            root.catalogCollectionKey = ""
            root.catalogBrowseKey = ""
        }
        if (root.surfaceHost && root.surfaceHost.mediaLibraryBack)
            root.applyStatus(root.surfaceHost.mediaLibraryBack())
        if (parentView) {
            root.parentLibraryView = null
            if (root.continuousLibrary && parentView.model) {
                var discarded = root.catalogModel
                root.catalogModel = parentView.model
                root.listContextKey = parentView.modelContext
                root.catalogStructureRevision = String(parentView.structureRevision || "")
                root.catalogItems = parentView.items
                root.catalogTotal = parentView.total
                root.catalogPageSize = parentView.pageSize
                root.catalogHasMore = parentView.hasMore
                root.catalogBrowseKey = parentView.browseKey
                root.catalogCategories = parentView.categories
                root.catalogLanguages = parentView.languages
                root.catalogSeasons = parentView.seasons
                if (discarded !== initialCatalogModel)
                    discarded.destroy()
            }
            root.libraryLetter = parentView.letter
            root.categoryFilter = parentView.category
            root.languageFilter = parentView.language
            root.availableOnly = parentView.availableOnly === true
            root.localQuery = parentView.query
            searchBox.text = parentView.query
            root.pageOffset = parentView.offset
            root.pendingListRestore = parentView
            root.queueBrowse(false)
        }
        root.restoringParentView = false
        catalogList.forceLayout()
        root.catalogRowsReady = !root.pagedLibrary || root.displayedPageMatches
    }

    function refreshLibrary() {
        root.cancelChunk()
        if (root.surfaceHost && root.surfaceHost.mediaLibraryRefresh)
            root.applyStatus(root.surfaceHost.mediaLibraryRefresh())
        else
            root.refresh()
    }

    function toggleBackgroundLibrary() {
        if (!root.hasBackgroundControl || root.backgroundPausing || root.sourceCheckRunning)
            return
        try {
            root.applyStatus(root.surfaceHost.mediaLibraryBackground(!root.expansionRunning))
        } catch (err) {
            root.browseError = "Kunde inte ändra bakgrundsarbetet. Försök igen."
        }
    }

    function toggleSourceCheck() {
        if (!root.hasSourceCheckControl || root.backgroundPausing || root.expansionRunning) return
        try {
            root.applyStatus(root.surfaceHost.mediaLibraryCheck(!root.sourceCheckRunning))
        } catch (err) {
            root.browseError = "Källkontrollen kunde inte ändras. Försök igen."
        }
    }

    onModeChanged: {
        if (root.changingLibraryMode || (root.pagedLibrary && (root.browsePending || browseTimer.running)))
            return
        var expected = {TV: "live", MUSIC: "music", RADIO: "radio", FETCH: "downloads", GAME: "games"}
        var active = root.libraryNav.filter(function(row) { return row.id === root.libraryPage })[0]
        if (!active || active.mode !== root.mode) {
            root.libraryPage = expected[root.mode] || "live"
            root.clearFilters()
        }
    }

    function applyStatus(raw) {
        var text = String(raw || "")
        if (text === root.statusJson)
            return
        try {
            var incoming = JSON.parse(text || "{}")
            if (incoming.mode === undefined && incoming.backend === undefined && incoming.items === undefined) {
                if (incoming.error) {
                    root.browsePending = false
                    root.browseError = String(incoming.error).slice(0, 240)
                }
                return
            }
            if (root.pagedLibrary && root.catalogRevision >= 0 && incoming.library_revision !== undefined
                && Number(incoming.library_revision) < root.catalogRevision)
                return
        } catch (err) {
            return
        }
        root.statusJson = text
        if (String(root.status.backend || "") === "qt_audio")
            root.playerError = root.status.reconnecting
                ? "Återansluter · " + root.status.retry_attempt + "/" + root.status.retry_limit
                : String(root.status.error || "")
        root.rememberCatalog()
        var title = String((root.status.now || {}).title || root.status.legend || "MEDIA")
        root.nowPlayingChanged(title)
        if (root.status.library_loading_id !== undefined)
            root.pendingPlayId = String(root.status.library_loading_id || "")
        else if (root.status.error || (String(root.now.id || "") === root.pendingPlayId
            && (root.status.playing === true || root.status.paused === true)))
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
        if (root.pagedLibrary) {
            if (root.status.library_page === undefined
                || root.snapshotBrowseKey(root.status) !== root.desiredBrowseKey)
                return
            var collectionKey = String(root.status.library_collection_key || "")
            var collection = String(root.status.library_collection || "")
            if ((root.expectedCollectionKey && collectionKey !== root.expectedCollectionKey)
                || (!root.expectedCollectionKey && root.expectedCollectionTitle && collection !== root.expectedCollectionTitle)
                || (!root.expectedCollectionKey && !root.expectedCollectionTitle && (collectionKey || collection)))
                return
            if (root.status.library_busy !== true) {
                root.browsePending = false
                root.browseError = String(root.status.library_error || "")
            }
            if (rows === undefined || rows === null || rows.length === undefined || root.status.library_busy === true)
                return
            var structuralRevision = String(root.status.library_catalog_revision === undefined
                ? "" : root.status.library_catalog_revision)
            if (root.continuousLibrary && root.status.library_background_refresh === true
                && root.status.library_requires_reset !== true
                && root.catalogBrowseKey === root.desiredBrowseKey
                && root.catalogStructureRevision.length > 0 && structuralRevision !== root.catalogStructureRevision
                && catalogList.contentY - catalogList.originY > 1) {
                // Keep a coherent visited snapshot while someone is reading
                // farther down. New admissions appear on return to the first
                // block; chunk revision checks still reject mixed offsets.
                root.catalogUpdatePending = true
                return
            }
            root.catalogUpdatePending = false
            if (root.continuousLibrary && (structuralRevision !== root.catalogStructureRevision
                    || root.status.library_requires_reset === true)) {
                if (root.catalogBrowseKey === root.desiredBrowseKey
                    && String(root.catalogCollectionKey || root.collectionTitle) === String(collectionKey || collection))
                    root.rememberCatalogPosition()
                root.cancelChunk()
                // A membership change may occur entirely beyond the first
                // block, for example when a visited source expires. Retain
                // only the newly confirmed first block before fetching again.
                if (root.catalogStructureRevision.length > 0 && root.catalogModel.count > rows.length) {
                    var relativeY = catalogList.contentY - catalogList.originY
                    root.catalogSyncing = true
                    root.catalogModel.remove(rows.length, root.catalogModel.count - rows.length)
                    if (catalogList.currentIndex >= rows.length)
                        catalogList.currentIndex = -1
                    Qt.callLater(function() {
                        catalogList.contentY = Math.max(catalogList.originY,
                            Math.min(catalogList.originY + Math.max(0, catalogList.contentHeight - catalogList.height),
                                catalogList.originY + relativeY))
                    })
                }
            }
            root.catalogStructureRevision = structuralRevision
            root.catalogItems = rows.slice(0, 80)
            root.catalogBrowseKey = root.desiredBrowseKey
            root.catalogRevision = Number(root.status.library_revision || 0)
            root.catalogTotal = Math.max(0, Number(root.status.library_total || 0))
            root.catalogPageSize = Math.max(1, Math.min(80, Number(root.status.library_page_size || 80)))
            root.catalogHasMore = root.status.library_has_more === true
            root.catalogCollection = String(root.status.library_collection || "")
            root.catalogCollectionKey = collectionKey
            root.catalogCategories = root.optionRows(root.status.library_categories,
                root.libraryPage === "music" ? "Alla artister" : "Alla kategorier", root.libraryPage === "music" ? 2048 : 256)
            root.catalogLanguages = root.optionRows(root.status.library_languages, "Alla språk")
            root.catalogSeasons = root.optionRows(root.status.library_seasons, "Alla säsonger")
            // Data and collection identity commit together. A filter can keep
            // the same80 IDs/count; relying only on filteredItemsChanged would
            // otherwise leave reused parent delegates until a scroll repaints.
            catalogSyncTimer.stop()
            if (structuralRevision && root.surfaceHost && root.surfaceHost.mediaLibraryAcceptSnapshot
                && (root.acceptedCatalogHost !== root.surfaceHost || root.acceptedCatalogSnapshot !== structuralRevision)) {
                try {
                    root.surfaceHost.mediaLibraryAcceptSnapshot(structuralRevision)
                    root.acceptedCatalogHost = root.surfaceHost
                    root.acceptedCatalogSnapshot = structuralRevision
                } catch (err) {
                    // Older hosts use the same local browse/chunk contract
                    // without an acknowledgement lane.
                }
            }
            // Restoration may request its next block synchronously. Bind the
            // accepted cursor before that request can capture the old session.
            root.syncCatalogModel()
            return
        }
        if (rows !== undefined && rows !== null && rows.length !== undefined) {
            root.catalogItems = rows.slice(0, 120)
            root.catalogRevision = Number(root.status.library_revision || 0)
        }
    }

    function setMode(mode) {
        if (!root.surfaceHost)
            return
        root.changingLibraryMode = true
        root.applyStatus(root.surfaceHost.mediaSetMode(mode))
        root.changingLibraryMode = false
        if (!root.pagedLibrary)
            root.refresh()
    }

    function playItem(itemId) {
        if (!root.surfaceHost)
            return
        root.pendingPlayId = String(itemId || "")
        root.applyStatus(root.surfaceHost.mediaPlay(itemId))
        if (!root.pagedLibrary)
            root.refresh()
    }

    function playbackIndex() {
        var identifier = String(root.now.id || "")
        for (var i = 0; i < root.catalogModel.count; ++i)
            if (String(root.catalogModel.get(i).entry.id || "") === identifier) return i
        return -1
    }

    function canStepPlayback(direction) {
        if (!root.now.id || root.loadingItemId || root.status.library_playback_busy === true) return false
        var field = direction < 0 ? "library_playback_can_previous" : "library_playback_can_next"
        if (root.surfaceHost && root.surfaceHost.mediaLibraryStep)
            return root.status[field] !== false
        var index = root.playbackIndex()
        return index >= 0 && index + direction >= 0 && index + direction < root.catalogModel.count
    }

    function stepPlayback(direction, automatic) {
        if (!root.surfaceHost || root.loadingItemId || root.status.library_playback_busy === true) return
        if (automatic && !root.autoNextEpisodes) return
        if (root.surfaceHost.mediaLibraryStep) {
            root.applyStatus(root.surfaceHost.mediaLibraryStep(direction, automatic === true))
            return
        }
        var index = root.playbackIndex() + direction
        if (index < 0 || index >= root.catalogModel.count) return
        var row = root.catalogModel.get(index).entry
        if (automatic && (root.contentType(row) !== "episode"
            || String(row.series_title || "") !== String(root.now.series_title || ""))) return
        catalogList.currentIndex = index
        catalogList.positionViewAtIndex(index, ListView.Contain)
        root.activateItem(row)
    }

    function toggleAutoNext() {
        root.autoNextEpisodes = !root.autoNextEpisodes
        if (root.surfaceHost && root.surfaceHost.mediaLibraryAutoNext)
            root.applyStatus(root.surfaceHost.mediaLibraryAutoNext(root.autoNextEpisodes))
    }

    function finishVideo() {
        if (root.playerResetting || !root.qmlVideo || holePlayer.mediaStatus !== MediaPlayer.EndOfMedia
            || Number(root.status.playback_generation || 0) !== root.playerGeneration) return
        root.playerEnded = true
        root.playerWantsPlay = false
        if (!root.autoNextEpisodes || root.liveVideo || root.contentType(root.now) !== "episode"
            || root.status.paused === true || root.loadingItemId || holePlayer.error !== MediaPlayer.NoError)
            return
        var duration = Number(holePlayer.duration || 0)
        if (duration > 0 && Number(holePlayer.position || 0) + 1500 < duration) return
        var key = JSON.stringify([String(root.now.id || ""), root.lastPlayUrl, root.playerGeneration])
        if (root.autoNextHandledKey === key) return
        root.autoNextHandledKey = key
        root.stepPlayback(1, true)
    }

    function openCliamp() {
        if (!root.surfaceHost)
            return
        root.applyStatus(root.surfaceHost.mediaStartCliamp())
        if (!root.pagedLibrary)
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
            root.applyStatus(raw)
        } catch (err) {
            root.playerError = String(err)
        }
        root.refresh()
    }

    function search(query) {
        if (root.pagedLibrary) {
            root.localQuery = String(query || "")
            if (root.localQuery.trim().length > 0 && root.surfaceHost.mediaLibraryTypes
                && root.discoveryTypes.indexOf(root.libraryPage) < 0)
                root.selectPage(String(root.discoveryTypes[0]))
            root.pageOffset = 0
            root.browseNow()
            if (root.surfaceHost.mediaLibrarySearch)
                root.applyStatus(root.surfaceHost.mediaLibrarySearch(root.localQuery))
            return
        }
        if (!root.surfaceHost || !root.surfaceHost.mediaSearch)
            return
        root.searchBusy = true
        if (root.mode === "TV" && root.surfaceHost.mediaLibrarySearch)
            root.applyStatus(root.surfaceHost.mediaLibrarySearch(query))
        else
            root.applyStatus(root.surfaceHost.mediaSearch(query))
        root.searchBusy = false
        root.refresh()
    }

    function toMediaUrl(raw) {
        var s = String(raw || "")
        if (!s)
            return ""
        if (s.indexOf("://") >= 0)
            return s
        if (/^[A-Za-z]:[\\/]/.test(s))
            return "file:///" + encodeURI(s.replace(/\\/g, "/")).replace(/#/g, "%23").replace(/\?/g, "%3F")
        if (s.indexOf("\\\\") === 0)
            return "file:" + encodeURI(s.replace(/\\/g, "/")).replace(/#/g, "%23").replace(/\?/g, "%3F")
        if (s.charAt(0) === "/")
            return "file://" + encodeURI(s).replace(/#/g, "%23").replace(/\?/g, "%3F")
        return s
    }

    function toggleFullscreen() {
        root.videoFullscreen = !root.videoFullscreen
    }

    function refreshFullscreenVolume() {
        if (!root.videoFullscreen)
            return
        root.fullscreenMasterAudioReady = false
        if (!root.surfaceHost || !root.surfaceHost.appAudioStatus
            || !root.surfaceHost.appPreviewAudioVolume || !root.surfaceHost.appSetAudioVolume)
            return
        try {
            var audio = JSON.parse(root.surfaceHost.appAudioStatus())
            root.fullscreenMasterAudioReady = audio.available === true
            if (root.fullscreenMasterAudioReady && isFinite(Number(audio.volume)))
                root.fullscreenMasterVolume = Math.max(0, Math.min(100, Number(audio.volume)))
        } catch (err) {
            root.fullscreenMasterAudioReady = false
        }
    }

    function previewFullscreenVolume(value) {
        root.fullscreenVolumePreview = Math.max(0, Math.min(100, Math.round(value)))
        if (root.fullscreenMasterAudioReady && root.surfaceHost && root.surfaceHost.appPreviewAudioVolume) {
            root.surfaceHost.appPreviewAudioVolume(root.fullscreenVolumePreview)
        } else {
            holeAudio.volume = root.fullscreenVolumePreview / 100
        }
    }

    function commitFullscreenVolume(value) {
        var volume = Math.max(0, Math.min(100, Math.round(value)))
        if (root.surfaceHost) {
            if (root.fullscreenMasterAudioReady && root.surfaceHost.appSetAudioVolume) {
                var audio = JSON.parse(root.surfaceHost.appSetAudioVolume(volume))
                root.fullscreenMasterVolume = audio.volume === undefined ? volume : Number(audio.volume)
            } else if (root.surfaceHost.mediaSetVolume) {
                root.applyStatus(root.surfaceHost.mediaSetVolume(volume))
            }
        }
        root.fullscreenVolumePreview = -1
    }

    function seekFullscreenVideo(seconds) {
        if (!root.videoFullscreen || !fullscreenControls.seekEnabled || !root.surfaceHost || !root.surfaceHost.mediaSeek)
            return
        root.applyStatus(root.surfaceHost.mediaSeek(Math.max(0, Math.min(holePlayer.duration / 1000, seconds))))
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
            if (root.surfaceHost && root.surfaceHost.mediaReportSourceFailure)
                root.surfaceHost.mediaReportSourceFailure(String(root.now.id || ""), root.playerGeneration)
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
            root.finishVideo()
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
        var volume = !root.fullscreenMasterAudioReady && root.fullscreenVolumePreview >= 0
            ? root.fullscreenVolumePreview : root.status.volume === undefined ? 70 : Number(root.status.volume)
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
            root.refreshFullscreenVolume()
            fullscreenWindow.showFullScreen()
            fullscreenWindow.requestActivate()
        } else {
            if (root.fullscreenVolumePreview >= 0)
                root.commitFullscreenVolume(root.fullscreenVolumePreview)
            fullscreenWindow.hide()
        }
    }

    Timer {
        interval: 250
        running: root.videoFullscreen && (fullscreenControls.revealed || root.fullscreenVolumePreview >= 0)
        repeat: true
        onTriggered: root.refreshFullscreenVolume()
    }

    onStatusJsonChanged: {
        // Let status/now/backend bindings settle before touching the decoder.
        // Reports can synchronously publish another status through Python.
        Qt.callLater(root.syncStatusPlayer)
    }

    function syncStatusPlayer() {
        if (root.status.library_discovery_languages)
            root.discoveryLanguages = root.status.library_discovery_languages
        if (root.status.library_discovery_language_options)
            root.discoveryLanguageOptions = root.status.library_discovery_language_options
        if (root.status.library_discovery_types)
            root.discoveryTypes = root.status.library_discovery_types
        if (root.status.library_auto_next !== undefined)
            root.autoNextEpisodes = root.status.library_auto_next === true
        root.rememberCatalog()
        root.syncPlayer()
    }

    Component.onCompleted: {
        root.playerReady = true
        if (Window.window)
            fullscreenWindow.transientParent = Window.window
        root.syncPlayer()
        if (root.pagedLibrary) {
            root.refresh()
            if (root.surfaceHost && root.surfaceHost.mediaLibraryActive)
                root.surfaceHost.mediaLibraryActive(root.visible)
            root.queueBrowse(false)
        }
    }

    Component.onDestruction: {
        root.cancelPlayerResolution()
        if (root.surfaceHost && root.surfaceHost.mediaLibraryActive)
            root.surfaceHost.mediaLibraryActive(false)
    }

    function reportClock(force) {
        if (!root.qmlVideo || !root.surfaceHost || !root.surfaceHost.mediaReportClock)
            return
        var now = Date.now()
        if (!force && now - root._clockStamp < 250)
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
            var prev = root.mode
            var previousRevision = Number(root.status.library_revision || 0)
            // Utilities controls the same decoder from every workspace tab.
            // Hidden catalogues stay idle, but transport state must still sync.
            root.refreshLive()
            if (root.visible && (root.mode !== prev || Number(root.status.library_revision || 0) !== previousRevision))
                root.refresh()
        }
        function onMediaSeekChanged(seconds) {
            if (!root.qmlVideo || !root.playerReady)
                return
            holePlayer.position = Math.max(0, Number(seconds) * 1000)
            root.reportClock(true)
        }
        function onMediaLibraryChunkReady(ticket, raw) { root.acceptChunk(ticket, raw) }
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
        id: browseTimer
        objectName: "mediaLibraryBrowseTimer"
        interval: 120
        repeat: false
        onTriggered: root.browseNow()
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
        if (root.surfaceHost && root.surfaceHost.mediaLibraryActive)
            root.surfaceHost.mediaLibraryActive(visible)
        if (visible) {
            root.refresh()
            if (root.surfaceHost && root.surfaceHost.mediaLibraryActive)
                root.surfaceHost.mediaLibraryActive(true)
            root.queueBrowse(false)
            Qt.callLater(root.maybeLoadMore)
        } else if (root.surfaceHost && root.surfaceHost.hideMedia)
            root.surfaceHost.hideMedia()
        if (!visible)
            browseTimer.stop()
        if (!visible)
            root.cancelChunk()
    }

    Popup {
        id: discoveryPopup
        objectName: "mediaDiscoveryFilterPopup"
        parent: root
        x: Math.max(8, (root.width - width) / 2)
        y: Math.max(8, (root.height - height) / 2)
        width: Math.min(420, root.width - 16)
        height: Math.min(580, root.height - 16)
        padding: 16
        focus: true
        modal: true
        background: Rectangle { color: "#191919"; radius: 6; border.color: "#686057" }
        contentItem: Column {
            id: discoveryContent
            spacing: 10
            GGText { colorKey: "ui.MediaSurface.1"; id: discoveryHeading; text: "Utöka / sök"; color: root.ink; font.pixelSize: 16; font.bold: true }
            GGText { colorKey: "ui.MediaSurface.2";
                id: discoveryIntro
                width: parent.width
                text: "Välj en, flera eller alla mediatyper och vilka språk du vill söka efter. Träffar visas på respektive flik."
                color: root.muted; wrapMode: Text.WordWrap; font.pixelSize: 12
            }
            GGText { colorKey: "ui.MediaSurface.3";
                id: discoveryExplanation
                width: parent.width
                text: root.backgroundRunning || root.backgroundPausing ? "Pausa Utöka för att ändra sökfiltret."
                    : "Okänt språk undersöks via källans metadata och ljudspårens språktaggar. Osäkra fynd sparas för fortsatt identifiering."
                color: root.gold; wrapMode: Text.WordWrap; font.pixelSize: 11
            }
            ScrollView {
                width: parent.width
                height: Math.max(50, discoveryPopup.availableHeight - discoveryHeading.height - discoveryIntro.height
                    - discoveryExplanation.height - discoveryDone.height - 4 * discoveryContent.spacing)
                clip: true
                contentWidth: availableWidth
                ScrollBar.vertical: GgScrollBar { property string uiColorScope: "ui.widget.MediaSurface.GgScrollBar.1";
                    keepVisible: true
                    orientation: Qt.Vertical
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                }
                Column {
                    width: parent.width
                    spacing: 4
                    Row {
                        width: parent.width
                        visible: !!root.surfaceHost && !!root.surfaceHost.mediaLibraryTypes
                        height: visible ? 28 : 0
                        GGText { colorKey: "ui.MediaSurface.4";
                            width: Math.max(0, parent.width - allMediaTypesButton.width - 8)
                            height: 28
                            text: "Mediatyper"
                            color: root.ink
                            font.pixelSize: 13
                            font.bold: true
                            verticalAlignment: Text.AlignVCenter
                        }
                        MediaAction { property string uiColorScope: "ui.control.MediaSurface.1";
                            id: allMediaTypesButton
                            objectName: "mediaDiscoveryTypesAll"
                            text: "Välj alla"
                            enabled: !root.backgroundRunning && !root.backgroundPausing
                                && root.discoveryTypes.length < root.libraryNav.length
                            onClicked: root.setDiscoveryTypes(root.libraryNav.map(function(row) { return row.id }))
                        }
                    }
                    Grid {
                        width: parent.width
                        visible: !!root.surfaceHost && !!root.surfaceHost.mediaLibraryTypes
                        height: visible ? implicitHeight : 0
                        columns: width >= 300 ? 2 : 1
                        Repeater {
                            model: root.libraryNav
                            delegate: MediaSearchChoice { property string uiColorScope: "ui.control.MediaSurface.2";
                                required property var modelData
                                objectName: "mediaDiscoveryType_" + modelData.id
                                width: (parent.width / parent.columns)
                                text: modelData.label
                                checked: root.discoveryTypes.indexOf(modelData.id) >= 0
                                enabled: !root.backgroundRunning && !root.backgroundPausing
                                    && (!checked || root.discoveryTypes.length > 1)
                                onClicked: root.chooseDiscoveryType(modelData.id)
                            }
                        }
                    }
                    GGText { colorKey: "ui.MediaSurface.5";
                        width: parent.width
                        topPadding: 8
                        text: "Språk"
                        color: root.ink
                        font.pixelSize: 13
                        font.bold: true
                    }
                    Repeater {
                        model: root.discoveryLanguageOptions
                        delegate: MediaSearchChoice { property string uiColorScope: "ui.control.MediaSurface.3";
                            id: languageChoice
                            required property var modelData
                            objectName: "mediaDiscoveryLanguage_" + modelData.value
                            width: parent.width
                            text: modelData.label
                            checked: root.discoveryLanguages.indexOf(modelData.value) >= 0
                            enabled: !root.backgroundRunning && !root.backgroundPausing
                                && (!checked || root.discoveryLanguages.length > 1)
                            onClicked: root.chooseDiscoveryLanguage(modelData.value)
                        }
                    }
                }
            }
            MediaAction { property string uiColorScope: "ui.control.MediaSurface.4"; id: discoveryDone; text: "Klart"; width: parent.width; onClicked: discoveryPopup.close() }
        }
    }

    Popup {
        id: diagnosticPopup
        objectName: "mediaDiagnosticPopup"
        parent: root
        x: Math.max(8, (root.width - width) / 2)
        y: Math.max(8, (root.height - height) / 2)
        width: Math.min(460, root.width - 16)
        height: Math.min(root.height - 16, diagnosticContent.implicitHeight + 32)
        padding: 16
        focus: true
        modal: true
        background: Rectangle { color: "#191919"; radius: 6; border.color: "#686057" }
        contentItem: Column {
            id: diagnosticContent
            spacing: 12
            GGText { colorKey: "ui.MediaSurface.6"; text: "Felsök källa"; color: root.ink; font.pixelSize: 16; font.bold: true }
            GGText { colorKey: "ui.MediaSurface.7"; width: parent.width; text: root.diagnosticTitle; wrapMode: Text.WordWrap; color: root.gold; font.pixelSize: 13 }
            GGText { colorKey: "ui.MediaSurface.8";
                objectName: "mediaDiagnosticMessage"
                width: parent.width
                text: root.status.library_diagnostic && root.status.library_diagnostic.running ? "Kontrollerar länken och kända alternativ…"
                    : String((root.status.library_diagnostic || {}).message || "Förbereder källkontroll…")
                color: root.ink; wrapMode: Text.WordWrap; font.pixelSize: 12
            }
            MediaAction { property string uiColorScope: "ui.control.MediaSurface.5";
                objectName: "mediaUseReplacement"
                width: parent.width
                visible: !!(root.status.library_diagnostic || {}).replacement_id
                text: String((root.status.library_diagnostic || {}).action_label || "Spela ersättningskällan")
                onClicked: {
                    root.playItem(String(root.status.library_diagnostic.replacement_id))
                    diagnosticPopup.close()
                }
            }
            MediaAction { property string uiColorScope: "ui.control.MediaSurface.6"; text: "Stäng"; width: parent.width; onClicked: diagnosticPopup.close() }
        }
    }

    component MediaSearchChoice: CheckBox {
        id: searchChoice
        height: 28
        padding: 3
        font.pixelSize: 12
        hoverEnabled: true
        background: Rectangle { color: searchChoice.hovered ? "#252525" : "transparent"; radius: 3 }
        indicator: Rectangle {
            width: 18; height: 18; x: 4; y: (searchChoice.height - height) / 2
            color: searchChoice.checked ? "#393227" : RuntimeTheme.GGTheme.canvas
            border.color: searchChoice.checked ? root.gold : "#636363"
            radius: 3
            GGText { colorKey: "ui.MediaSurface.9"; anchors.centerIn: parent; text: searchChoice.checked ? "✓" : ""; color: root.gold; font.pixelSize: 14 }
        }
        contentItem: GGText { colorKey: "ui.MediaSurface.10";
            text: searchChoice.text; leftPadding: 28
            verticalAlignment: Text.AlignVCenter
            color: searchChoice.checked ? root.ink : root.muted
            font: searchChoice.font
        }
    }

    component MediaRowAction: ToolButton {
        id: rowAction
        property bool removeIcon: false
        property string tip: ""
        width: 22
        height: 22
        padding: 2
        hoverEnabled: true
        Accessible.name: tip
        ToolTip.visible: hovered
        ToolTip.text: tip
        ToolTip.delay: 500
        background: Rectangle {
            radius: 3
            color: rowAction.down ? "#38312a" : rowAction.hovered ? RuntimeTheme.GGTheme.selected : "transparent"
            border.color: rowAction.visualFocus ? root.gold : "transparent"
        }
        contentItem: Shape {
            objectName: "mediaRowActionGlyph"
            opacity: rowAction.hovered || rowAction.visualFocus || rowAction.down ? 1 : 0.20
        preferredRendererType: Shape.GeometryRenderer
            ShapePath {
                strokeColor: rowAction.removeIcon && rowAction.hovered ? "#f29999" : RuntimeTheme.GGTheme.text
                strokeWidth: 1.2
                capStyle: ShapePath.RoundCap
                joinStyle: ShapePath.RoundJoin
                fillColor: "transparent"
                PathSvg {
                    path: rowAction.removeIcon ? "M4 4 L14 14 M14 4 L4 14"
                        : "M10 16 H3 V2 H10 L14 6 V8 M10 2 V6 H14 M7 3 L8 7 L6 9 L8 12 M15.5 12.5 A3 3 0 1 1 9.5 12.5 A3 3 0 1 1 15.5 12.5 M14.7 14.7 L17 17"
                }
            }
        }
    }

    component MediaAction: Button {
        id: action
        property string tip: ""
        implicitHeight: 26
        implicitWidth: Math.max(26, contentItem.implicitWidth + 16)
        padding: 6
        hoverEnabled: true
        focusPolicy: Qt.StrongFocus
        Accessible.name: text
        font.family: "monospace"
        font.pixelSize: 11
        ToolTip.visible: hovered && tip.length > 0
        ToolTip.text: tip
        ToolTip.delay: 500
        background: Rectangle {
            radius: 3
            color: action.down ? RuntimeTheme.GGTheme.line : action.checked ? "#292d32"
                : action.hovered ? "#242424" : RuntimeTheme.GGTheme.panel
            border.color: action.visualFocus ? RuntimeTheme.GGTheme.text : action.checked ? "#747b84" : RuntimeTheme.GGTheme.selected
            opacity: action.enabled ? 1 : 0.45
        }
        contentItem: GGText { colorKey: "ui.MediaSurface.11";
            text: action.text
            textFormat: Text.PlainText
            font: action.font
            color: action.checked ? root.ink : action.enabled ? "#bdc4cd" : "#666b73"
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
    }

    component MediaSelect: ComboBox {
        id: selector
        property string selectedValue: "all"
        textRole: "label"
        valueRole: "value"
        implicitHeight: 26
        leftPadding: 7
        rightPadding: 20
        font.family: "monospace"
        font.pixelSize: 10
        Accessible.name: displayText
        ToolTip.visible: hovered
        ToolTip.text: displayText
        ToolTip.delay: 500
        currentIndex: {
            for (var i = 0; i < model.length; ++i)
                if (String(model[i].value) === selector.selectedValue)
                    return i
            return 0
        }
        background: Rectangle {
            color: RuntimeTheme.GGTheme.panel
            radius: 3
            border.color: selector.activeFocus ? RuntimeTheme.GGTheme.muted : selector.hovered ? "#656a72" : RuntimeTheme.GGTheme.selected
        }
        contentItem: GGText { colorKey: "ui.MediaSurface.12";
            text: selector.displayText
            textFormat: Text.PlainText
            color: selector.selectedValue === "all" ? root.muted : root.ink
            font: selector.font
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        indicator: GGText { colorKey: "ui.MediaSurface.13";
            x: selector.width - width - 7
            anchors.verticalCenter: parent.verticalCenter
            text: "▾"
            color: root.muted
            font.pixelSize: 11
        }
        delegate: ItemDelegate { property string uiColorScope: "ui.control.MediaSurface.7";
            required property var modelData
            required property int index
            width: Math.max(selector.width, 180)
            height: 28
            highlighted: selector.highlightedIndex === index
            contentItem: GGText { colorKey: "ui.MediaSurface.14";
                text: modelData.label
                textFormat: Text.PlainText
                color: root.ink
                font: selector.font
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
            }
            background: Rectangle { color: parent.highlighted ? RuntimeTheme.GGTheme.line : RuntimeTheme.GGTheme.raised }
        }
        popup: Popup {
            y: selector.height + 2
            width: Math.max(selector.width, 192)
            padding: 3
            implicitHeight: Math.min(300, contentItem.implicitHeight + 6)
            background: Rectangle { color: RuntimeTheme.GGTheme.raised; border.color: "#656a72"; radius: 3 }
            contentItem: ListView {
                clip: true
                implicitHeight: contentHeight
                model: selector.popup.visible ? selector.delegateModel : null
                currentIndex: selector.highlightedIndex
                ScrollBar.vertical: GgScrollBar { property string uiColorScope: "ui.widget.MediaSurface.GgScrollBar.8"; keepVisible: true }
            }
        }
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
                height: 28
            Flickable {
                id: navigationStrip
                anchors.left: parent.left
                width: Math.max(40, parent.width - (backgroundControls.visible ? backgroundControls.width + 6 : 0))
                height: parent.height
                clip: true
                contentWidth: navigationButtons.width
                contentHeight: height
                boundsBehavior: Flickable.StopAtBounds
                flickableDirection: Flickable.HorizontalFlick

                Row {
                    id: navigationButtons
                    height: parent.height
                    spacing: 4
                    Repeater {
                        model: root.libraryNav
                        delegate: MediaAction { property string uiColorScope: "ui.control.MediaSurface.8";
                            required property var modelData
                            objectName: "mediaNav_" + modelData.id
                            text: modelData.label
                            checked: root.libraryPage === modelData.id
                            height: 28
                            font.pixelSize: 12
                            onClicked: root.selectPage(modelData.id)
                        }
                    }
                }
                ScrollBar.horizontal: GgScrollBar { property string uiColorScope: "ui.widget.MediaSurface.GgScrollBar.10";}
            }
            Row {
                id: backgroundControls
                anchors.right: parent.right
                height: parent.height
                spacing: 7
                visible: root.hasBackgroundControl
                MediaAction { property string uiColorScope: "ui.control.MediaSurface.9";
                    id: discoveryFilterButton
                    objectName: "mediaDiscoveryFilterButton"
                    visible: !!root.surfaceHost && !!root.surfaceHost.mediaLibraryLanguages
                    height: 28
                    text: "Sökfilter"
                    tip: "Välj mediatyper och språk för Utöka och sökning"
                    onClicked: discoveryPopup.open()
                }
                GGText { colorKey: "ui.MediaSurface.15";
                    objectName: "mediaBackgroundCounts"
                    visible: mediaFrame.width > navigationButtons.width + backgroundToggle.width
                        + (discoveryFilterButton.visible ? discoveryFilterButton.width : 0) + implicitWidth + 40
                    height: parent.height
                    verticalAlignment: Text.AlignVCenter
                    text: root.backgroundCounts
                    textFormat: Text.PlainText
                    color: root.muted
                    font.family: "monospace"
                    font.pixelSize: 10
                    ToolTip.visible: backgroundCountsHover.containsMouse
                    ToolTip.text: root.backgroundCountDetails
                    MouseArea { id: backgroundCountsHover; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                }
                MediaAction { property string uiColorScope: "ui.control.MediaSurface.10";
                    id: backgroundToggle
                    objectName: "mediaBackgroundToggle"
                    height: 28
                    checked: root.expansionRunning
                    enabled: !root.backgroundPausing && !root.sourceCheckRunning
                    text: root.backgroundPausing && root.libraryBackground.operation !== "check" ? "PAUSAR…" : root.expansionRunning ? "UTÖKA · PÅ" : "UTÖKA · AV"
                    tip: (root.backgroundRunning
                        ? "Pausa sökning och källkontroll. Framstegen sparas."
                        : "Sök i valda mediatyper och språk. Uppdatera biblioteket och kontrollera videokällor. Högst fem minuter per start.")
                        + "\nMediatyper: " + root.discoveryTypes.map(root.mediaTypeLabel).join(", ")
                        + "\nNytt i biblioteket: " + root.backgroundCountDetails
                        + "\nHittade kandidater: " + root.discoveryTypes.map(function(key) {
                            return Number(root.libraryBackground["discovered_" + key] || 0) + " " + root.mediaTypeLabel(key).toLowerCase()
                        }).join(" · ")
                        + (root.libraryBackground.notice ? "\n" + String(root.libraryBackground.notice) : "")
                    Accessible.name: "Utöka mediebiblioteket " + (root.expansionRunning ? "på" : "av")
                    onClicked: root.toggleBackgroundLibrary()
                }
            }
            }

            Row {
                width: parent.width
                height: 26
                spacing: 4
                TextField {
                    id: searchBox
                    objectName: "workspaceMediaSearch"
                    width: Math.max(20, parent.width - searchButton.width - 4)
                    height: 26
                    leftPadding: 9
                    rightPadding: 26
                    color: root.ink
                    placeholderTextColor: root.muted
                    placeholderText: root.mode === "TV"
                        ? "Sök titel, kanal eller arkiv · klistra in en länk"
                        : root.mode === "FETCH" ? "Sök bland hämtade filmer, avsnitt och musik"
                        : root.mode === "RADIO" ? "Sök radiostation eller klistra in en strömlänk"
                        : root.mode === "GAME" ? "Sök spel eller homebrew" : "Sök i musikbiblioteket"
                    selectByMouse: true
                    maximumLength: 512
                    font.family: "monospace"
                    font.pixelSize: 11
                    Accessible.name: "Sök i mediebiblioteket"
                    onTextEdited: root.localQuery = text
                    onAccepted: root.search(text.trim())
                    Keys.onEscapePressed: {
                        text = ""
                        root.localQuery = ""
                        if (root.status.library_query)
                            root.search("")
                    }
                    background: Rectangle {
                        radius: 3
                        color: RuntimeTheme.GGTheme.canvas
                        border.color: searchBox.activeFocus ? RuntimeTheme.GGTheme.muted : "#464646"
                    }
                    BufferMark { property string uiColorScope: "ui.widget.MediaSurface.BufferMark.13";
                        objectName: "mediaSearchBuffer"
                        anchors.right: parent.right
                        anchors.rightMargin: 7
                        anchors.verticalCenter: parent.verticalCenter
                        active: root.libraryBusy
                        cell: 4
                    }
                }
                MediaAction { property string uiColorScope: "ui.control.MediaSurface.11";
                    id: searchButton
                    objectName: "mediaLibrarySearchButton"
                    text: "Sök"
                    tip: "Sök i biblioteket och tillgängliga källor"
                    onClicked: root.search(searchBox.text.trim())
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

                Rectangle {
                    id: catalogPanel
                    objectName: "mediaLibraryPanel"
                    width: root.listCollapsed
                        ? 0
                        : (root.showDisplay
                            ? Math.min(240, Math.max(140, stage.width * 0.32))
                            : stage.width)
                    height: parent.height
                    visible: width > 8
                    color: RuntimeTheme.GGTheme.base
                    radius: 3
                    border.color: "#363636"
                    clip: true

                    Column {
                        id: catalogHeader
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 6
                        spacing: 5

                        Item {
                            width: parent.width
                            height: 25
                            GGText { colorKey: "ui.MediaSurface.16";
                                anchors.left: parent.left
                                anchors.right: libraryRefresh.left
                                anchors.rightMargin: 5
                                anchors.verticalCenter: parent.verticalCenter
                                text: {
                                    var selected = root.libraryNav.filter(function(row) { return row.id === root.libraryPage })[0]
                                    return String(root.collectionTitle ? "Avsnitt" : selected ? selected.label : "Bibliotek").toLocaleUpperCase()
                                        + " · " + root.pageTotal.toLocaleString(Qt.locale("sv_SE"), "f", 0)
                                }
                                textFormat: Text.PlainText
                                color: root.gold
                                font.family: "monospace"
                                font.pixelSize: 11
                                font.bold: true
                                elide: Text.ElideRight
                            }
                            MediaAction { property string uiColorScope: "ui.control.MediaSurface.12";
                                id: libraryRefresh
                                objectName: "mediaLibraryRefresh"
                                anchors.right: parent.right
                                text: "↻"
                                tip: "Uppdatera bibliotek och källor"
                                enabled: !root.libraryBusy
                                onClicked: root.refreshLibrary()
                            }
                        }

                        Row {
                            width: parent.width
                            height: visible ? 26 : 0
                            spacing: 5
                            visible: root.collectionTitle.length > 0
                            MediaAction { property string uiColorScope: "ui.control.MediaSurface.13";
                                objectName: "mediaLibraryBack"
                                text: "‹"
                                tip: "Tillbaka till biblioteket"
                                onClicked: root.goBack()
                            }
                            GGText { colorKey: "ui.MediaSurface.17";
                                id: collectionHeading
                                width: Math.max(0, parent.width - 35)
                                height: 26
                                text: root.collectionTitle
                                textFormat: Text.PlainText
                                color: root.ink
                                font.family: "monospace"
                                font.pixelSize: 11
                                verticalAlignment: Text.AlignVCenter
                                elide: Text.ElideRight
                                ToolTip.visible: collectionHover.containsMouse
                                ToolTip.delay: 500
                                ToolTip.text: root.collectionTitle
                                MouseArea { id: collectionHover; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                            }
                        }

                        Row {
                            width: parent.width
                            height: visible ? 26 : 0
                            spacing: 4
                            visible: root.collectionTitle.length === 0
                            MediaSelect { property string uiColorScope: "ui.control.MediaSurface.14";
                                objectName: "mediaLetterSelector"
                                width: parent.width - (clearLibraryFilters.visible ? clearLibraryFilters.width + 4 : 0)
                                selectedValue: root.libraryLetter
                                model: [{value: "all", label: "A–Ö · Alla"}, {value: "#", label: "# · Siffror och symboler"}]
                                    .concat("ABCDEFGHIJKLMNOPQRSTUVWXYZÅÄÖ".split("").map(function(letter) {
                                        return {value: letter, label: letter}
                                    }))
                                onActivated: root.libraryLetter = String(currentValue)
                            }
                            MediaAction { property string uiColorScope: "ui.control.MediaSurface.15";
                                id: clearLibraryFilters
                                objectName: "mediaClearFilters"
                                visible: root.hasLibraryFilters
                                text: "×"
                                width: 26
                                tip: "Rensa bokstav, sökning och filter"
                                Accessible.name: "Rensa alla biblioteksfilter"
                                onClicked: root.clearFilters()
                            }
                        }

                        Grid {
                            width: parent.width
                            height: visible ? implicitHeight : 0
                            columns: width < 340 ? 1 : 2
                            spacing: 4
                            visible: root.collectionTitle.length === 0
                                && (root.categoryOptions.length > 1 || root.languageOptions.length > 1)
                            MediaSelect { property string uiColorScope: "ui.control.MediaSurface.16";
                                objectName: "mediaCategorySelector"
                                width: parent.columns === 2 && root.languageOptions.length > 1
                                    ? (parent.width - 4) / 2 : parent.width
                                visible: root.categoryOptions.length > 1
                                selectedValue: root.categoryFilter
                                model: root.categoryOptions
                                onActivated: root.categoryFilter = String(currentValue)
                            }
                            MediaSelect { property string uiColorScope: "ui.control.MediaSurface.17";
                                objectName: "mediaLanguageSelector"
                                width: parent.columns === 2 && root.categoryOptions.length > 1
                                    ? (parent.width - 4) / 2 : parent.width
                                visible: root.languageOptions.length > 1
                                selectedValue: root.languageFilter
                                model: root.languageOptions
                                onActivated: root.languageFilter = String(currentValue)
                            }
                        }

                        MediaSelect { property string uiColorScope: "ui.control.MediaSurface.18";
                            objectName: "mediaAvailabilitySelector"
                            width: parent.width
                            visible: root.videoLibrary
                            height: visible ? 26 : 0
                            selectedValue: root.availableOnly ? "available" : "all"
                            model: [{value: "all", label: "Alla katalogposter"},
                                {value: "available", label: "Bara kontrollerat tillgängliga"}]
                            onActivated: root.availableOnly = String(currentValue) === "available"
                        }

                        MediaSelect { property string uiColorScope: "ui.control.MediaSurface.19";
                            objectName: "mediaSeasonSelector"
                            width: parent.width
                            visible: root.collectionTitle.length > 0 && root.seasonOptions.length > 1
                            height: visible ? 26 : 0
                            selectedValue: root.seasonFilter
                            model: root.seasonOptions
                            onActivated: root.seasonFilter = String(currentValue)
                        }

                        Rectangle { width: parent.width; height: 1; color: RuntimeTheme.GGTheme.line }
                    }

                    ListView {
                        id: catalogList
                        objectName: "workspaceMediaCatalog"
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: catalogHeader.bottom
                        anchors.bottom: catalogTools.top
                        anchors.margins: 5
                        clip: true
                        enabled: !root.continuousLibrary || root.displayedPageMatches
                        opacity: enabled ? 1 : 0.55
                        spacing: 3
                        model: catalogModel
                        currentIndex: -1
                        boundsBehavior: Flickable.StopAtBounds
                        keyNavigationEnabled: true
                        reuseItems: root.catalogRowsReady
                        cacheBuffer: 100
                        activeFocusOnTab: true
                        onContentYChanged: {
                            if (root.catalogUpdatePending && contentY - originY < root.catalogPageSize * 50)
                                Qt.callLater(root.rememberCatalog)
                            root.maybeLoadMore()
                        }
                        onHeightChanged: Qt.callLater(root.maybeLoadMore)
                        onVerticalVelocityChanged: root.maybeLoadMore()
                        ScrollBar.vertical: GgScrollBar { property string uiColorScope: "ui.widget.MediaSurface.GgScrollBar.23"; keepVisible: true }
                        Keys.onReturnPressed: {
                            if (currentIndex >= 0 && currentIndex < catalogModel.count)
                                root.activateItem(catalogModel.get(currentIndex).entry)
                        }
                        Keys.onEnterPressed: {
                            if (currentIndex >= 0 && currentIndex < catalogModel.count)
                                root.activateItem(catalogModel.get(currentIndex).entry)
                        }
                        Keys.onPressed: function(event) {
                            if (event.key === Qt.Key_Backspace && root.collectionTitle) {
                                root.goBack()
                                event.accepted = true
                            } else if (event.key === Qt.Key_End && catalogModel.count > 0) {
                                currentIndex = catalogModel.count - 1
                                positionViewAtEnd()
                                root.maybeLoadMore()
                                event.accepted = true
                            } else if (event.key === Qt.Key_Home && catalogModel.count > 0) {
                                currentIndex = 0
                                positionViewAtBeginning()
                                event.accepted = true
                            }
                        }

                        delegate: ItemDelegate { property string uiColorScope: "ui.control.MediaSurface.20";
                            id: catalogRow
                            required property var entry
                            required property string signature
                            readonly property var modelData: JSON.parse(signature || "{}")
                            required property int index
                            visible: root.catalogRowsReady && (!root.pagedLibrary || root.displayedPageMatches)
                            objectName: "mediaCatalogRow_" + String(modelData.id || index)
                            width: catalogList.width - 5
                            height: 47
                            padding: 6
                            hoverEnabled: true
                            focusPolicy: Qt.StrongFocus
                            Accessible.name: root.rowTitle(modelData) + ", " + root.itemDetail(modelData)
                            readonly property bool rowActive: String(root.now.id || "") === String(modelData.id)
                            readonly property bool rowBuffering:
                                String(modelData.id) === root.loadingItemId
                                || (root.streamBuffering && (String(modelData.id) === root.bufferingId
                                    || (!!modelData.source && !!root.status.buffering_source
                                        && String(modelData.source) === String(root.status.buffering_source))))
                            background: Rectangle {
                                radius: 3
                                color: catalogRow.rowActive ? "#292d32"
                                    : catalogRow.highlighted || catalogRow.hovered ? RuntimeTheme.GGTheme.raised : RuntimeTheme.GGTheme.panel
                                border.color: catalogRow.activeFocus ? RuntimeTheme.GGTheme.muted : catalogRow.rowActive ? "#646b73" : "transparent"
                            }
                            highlighted: ListView.isCurrentItem
                            contentItem: Item {
                                GGText { colorKey: "ui.MediaSurface.18";
                                    id: rowTitleText
                                    objectName: "mediaRowTitle_" + String(catalogRow.modelData.id)
                                    anchors.left: parent.left
                                    anchors.right: rowTools.left
                                    anchors.rightMargin: rowChevron.visible ? 16 : 3
                                    anchors.top: parent.top
                                    height: 18
                                    text: (catalogRow.rowActive ? "▶ " : "") + root.displayTitle(catalogRow.modelData)
                                    textFormat: Text.PlainText
                                    color: catalogRow.rowActive ? root.ink : RuntimeTheme.GGTheme.text
                                    font.family: "monospace"
                                    font.pixelSize: 11
                                    font.bold: catalogRow.rowActive
                                    verticalAlignment: Text.AlignVCenter
                                    elide: Text.ElideRight
                                }
                                Row {
                                    id: rowTools
                                    anchors.right: parent.right
                                    anchors.top: parent.top
                                    spacing: 1
                                    z: 2
                                    MediaRowAction { property string uiColorScope: "ui.control.MediaSurface.21";
                                        objectName: "mediaDiagnose_" + String(catalogRow.modelData.id)
                                        visible: !!root.surfaceHost && !!root.surfaceHost.mediaLibraryDiagnose
                                        tip: "Felsök källa och leta efter en ersättning"
                                        onClicked: root.diagnoseItem(catalogRow.modelData)
                                    }
                                    MediaRowAction { property string uiColorScope: "ui.control.MediaSurface.22";
                                        objectName: "mediaRemove_" + String(catalogRow.modelData.id)
                                        visible: !!root.surfaceHost && !!root.surfaceHost.mediaLibraryHideSource
                                        removeIcon: true
                                        tip: "Ta bort från min lista"
                                        onClicked: root.removeItem(catalogRow.modelData)
                                    }
                                }
                                GGText { colorKey: "ui.MediaSurface.19";
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.bottom: parent.bottom
                                    height: 16
                                    text: root.itemDetail(catalogRow.modelData)
                                    textFormat: Text.PlainText
                                    color: root.muted
                                    font.family: "monospace"
                                    font.pixelSize: 9
                                    verticalAlignment: Text.AlignVCenter
                                    elide: Text.ElideRight
                                }
                                BufferMark { property string uiColorScope: "ui.widget.MediaSurface.BufferMark.26";
                                    id: rowMark
                                    objectName: "mediaItemBuffer"
                                    anchors.right: rowTools.left
                                    anchors.top: parent.top
                                    anchors.topMargin: 4
                                    active: catalogRow.rowBuffering
                                    cell: 4
                                }
                                GGText { colorKey: "ui.MediaSurface.20";
                                    id: rowChevron
                                    anchors.right: parent.right
                                    anchors.verticalCenter: parent.verticalCenter
                                    visible: !catalogRow.rowBuffering && (root.contentType(catalogRow.modelData) === "series"
                                        || root.contentType(catalogRow.modelData) === "collection")
                                    text: "›"
                                    color: root.gold
                                    font.pixelSize: 17
                                }
                            }
                            ToolTip.visible: hovered
                            ToolTip.delay: 700
                            ToolTip.text: root.rowTitle(modelData) + "\n" + root.itemDetail(modelData)
                                + "\n" + root.availabilityDetail(modelData)
                            onClicked: {
                                catalogList.currentIndex = index
                                root.activateItem(modelData)
                            }
                        }

                        GGText { colorKey: "ui.MediaSurface.21";
                            visible: catalogList.count === 0
                            anchors.centerIn: parent
                            width: Math.max(0, parent.width - 16)
                            text: root.libraryBusy ? "Laddar katalog…"
                                : root.loadingItemId ? "Laddar avsnitt…"
                                : root.libraryIndexing ? "Uppdaterar katalog…"
                                : root.localQuery || root.libraryLetter !== "all" || root.categoryFilter !== "all"
                                    || root.languageFilter !== "all" ? "Inga träffar. Välj Alla eller ändra sökningen."
                                : root.mode === "FETCH" ? "Dina färdiga hämtningar visas här."
                                : root.mode === "GAME" ? "Inga spel ännu. Sök homebrew eller lägg till egna ROM-filer."
                                : root.mode === "MUSIC" ? "Lägg till musik i ditt lokala bibliotek."
                                : root.hasBackgroundControl ? "Inga kontrollerade titlar ännu. Slå på UTÖKA för att fylla biblioteket."
                                : "Inga kontrollerade titlar i den här vyn ännu."
                            textFormat: Text.PlainText
                            color: root.muted
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.WordWrap
                            font.pixelSize: 11
                        }
                        GGText { colorKey: "ui.MediaSurface.22";
                            visible: root.restoringCatalogPosition && !root.chunkError && catalogList.count > 0
                            anchors.centerIn: parent
                            text: "Uppdaterar listan…"
                            color: root.muted
                            font.pixelSize: 11
                        }
                    }

                    Column {
                        id: catalogTools
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        anchors.margins: 6
                        spacing: 4
                        Row {
                            objectName: "mediaPlaybackNavigation"
                            width: parent.width
                            height: visible ? 28 : 0
                            spacing: 4
                            visible: !!root.surfaceHost && !!root.surfaceHost.mediaPlay
                            MediaAction { property string uiColorScope: "ui.control.MediaSurface.23";
                                objectName: "mediaPlayPrevious"
                                width: 30; height: 28
                                text: "‹"
                                font.pixelSize: 18
                                enabled: root.canStepPlayback(-1)
                                tip: "Spela föregående avsnitt, film, låt eller kanal i uppspelningslistan"
                                Accessible.name: "Spela föregående"
                                onClicked: root.stepPlayback(-1, false)
                            }
                            MediaAction { property string uiColorScope: "ui.control.MediaSurface.24";
                                objectName: "mediaPlayNext"
                                width: 30; height: 28
                                text: "›"
                                font.pixelSize: 18
                                enabled: root.canStepPlayback(1)
                                tip: "Spela nästa avsnitt, film, låt eller kanal i uppspelningslistan"
                                Accessible.name: "Spela nästa"
                                onClicked: root.stepPlayback(1, false)
                            }
                            MediaAction { property string uiColorScope: "ui.control.MediaSurface.25";
                                objectName: "mediaAutoNextEpisodes"
                                width: Math.max(26, parent.width - 68); height: 28
                                text: width < 90 ? "Auto" : "Auto nästa"
                                checked: root.autoNextEpisodes
                                tip: "Spela nästa avsnitt automatiskt i samma serie. Ett valt säsongsfilter begränsar uppspelningen till den säsongen."
                                Accessible.name: "Automatiskt nästa avsnitt " + (root.autoNextEpisodes ? "på" : "av")
                                onClicked: root.toggleAutoNext()
                            }
                        }
                        MediaAction { property string uiColorScope: "ui.control.MediaSurface.26";
                            objectName: "mediaSourceCheckToggle"
                            width: parent.width
                            visible: root.hasSourceCheckControl
                            height: visible ? 26 : 0
                            checked: root.sourceCheckRunning
                            enabled: !root.backgroundPausing && !root.expansionRunning
                            text: root.backgroundPausing && root.libraryBackground.operation === "check" ? "Källkontroll · pausar…"
                                : (width < 190 ? "Kontroll" : "Källkontroll") + (root.sourceCheckRunning ? " · Pausa" : " · Starta")
                            Accessible.name: root.sourceCheckRunning ? "Pausa källkontrollen" : "Starta eller fortsätt källkontrollen"
                            tip: root.expansionRunning ? "Pausa Utöka för att starta en separat källkontroll."
                                : root.sourceCheckRunning ? "Pausa kontrollen. Framstegen sparas så att du kan fortsätta senare."
                                : "Kontrollera befintliga källor enligt valda mediatyper och språk. Söker inte efter nya titlar. Högst fem minuter per omgång."
                            onClicked: root.toggleSourceCheck()
                        }
                        Row {
                            visible: root.removedItemId.length > 0
                            width: parent.width
                            height: visible ? 26 : 0
                            spacing: 4
                            GGText { colorKey: "ui.MediaSurface.23";
                                width: Math.max(0, parent.width - undoRemoveButton.width - 4)
                                height: 26
                                text: "Borttagen: " + root.removedItemTitle
                                elide: Text.ElideRight
                                color: root.muted
                                font.pixelSize: 11
                                verticalAlignment: Text.AlignVCenter
                            }
                            MediaAction { property string uiColorScope: "ui.control.MediaSurface.27";
                                id: undoRemoveButton
                                objectName: "mediaUndoRemove"
                                text: "Ångra"
                                onClicked: root.undoRemove()
                            }
                        }
                        GGText { colorKey: "ui.MediaSurface.24";
                            objectName: "mediaLibraryLoadState"
                            width: parent.width
                            height: 15
                            text: root.chunkError || root.libraryError || String(root.status.library_playback_notice || "") || (root.loadingItemId ? "Laddar vald titel…"
                                : root.chunkBusy ? "Laddar fler titlar…"
                                : root.libraryBusy ? "Laddar katalog…"
                                : root.libraryIndexing ? "Uppdaterar katalog…"
                                : root.backgroundSummary ? root.backgroundSummary
                                : root.catalogUpdatePending ? "Nya titlar · visas överst i listan"
                                : root.auditProgressText ? root.auditProgressText
                                : root.collectionTitle ? "Välj avsnitt · Enter spelar"
                                : root.libraryPage === "series" ? "Välj serie → säsong → avsnitt"
                                : "Välj titel · Enter spelar")
                            textFormat: Text.PlainText
                            color: root.chunkError || root.libraryError ? root.gold : root.muted
                            font.pixelSize: 9
                            elide: Text.ElideRight
                            ToolTip.visible: loadStateHover.containsMouse
                            ToolTip.delay: 500
                            ToolTip.text: root.chunkError || root.libraryError || (root.loadingItemId
                                ? "Laddar information och uppspelningskälla för den valda titeln."
                                : root.libraryIndexing ? "Uppdaterar den sparade katalogen i bakgrunden."
                                : root.catalogUpdatePending ? "Nya kontrollerade titlar har lagts till. Gå till början för att visa den uppdaterade listan utan att avbryta din scrollning."
                                : root.auditProgressText ? "Källkontrollen räknar färdiga kontroller av källor, även underkända. Biblioteket räknar provspelade titlar i den här vyn; äldre kontroller förnyas vid play."
                                : "Piltangenter väljer · Enter öppnar/spelar · Backsteg går tillbaka")
                            MouseArea { id: loadStateHover; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
                        }
                        Row {
                            width: parent.width
                            height: visible ? 26 : 0
                            spacing: 4
                            visible: root.pagedLibrary && (root.continuousLibrary || root.pageTotal > root.catalogPageSize || root.pageOffset > 0 || root.catalogHasMore)
                            MediaAction { property string uiColorScope: "ui.control.MediaSurface.28";
                                objectName: "mediaLibraryPrevious"
                                text: "‹"
                                tip: "Föregående sida"
                                width: 26
                                visible: !root.continuousLibrary
                                enabled: !root.libraryBusy && root.pageOffset > 0
                                onClicked: root.browsePage(-1)
                            }
                            GGText { colorKey: "ui.MediaSurface.25";
                                objectName: "mediaLibraryPageRange"
                                width: Math.max(0, parent.width - (root.continuousLibrary ? 0 : 60))
                                height: 26
                                text: root.continuousLibrary
                                    ? root.catalogModel.count.toLocaleString(Qt.locale("sv_SE"), "f", 0)
                                        + " av " + root.pageTotal.toLocaleString(Qt.locale("sv_SE"), "f", 0) + " titlar"
                                    : root.displayedPageMatches && root.filteredItems.length > 0
                                    ? String(root.pageOffset + 1) + "–"
                                        + (root.pageOffset + root.filteredItems.length)
                                        + " av " + root.pageTotal.toLocaleString(Qt.locale("sv_SE"), "f", 0)
                                    : root.libraryBusy
                                        ? "Laddar katalog…"
                                        : "Inga fler titlar"
                                textFormat: Text.PlainText
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                                color: root.muted
                                font.family: "monospace"
                                font.pixelSize: 10
                                elide: Text.ElideRight
                            }
                            MediaAction { property string uiColorScope: "ui.control.MediaSurface.29";
                                objectName: "mediaLibraryNext"
                                text: "›"
                                tip: "Nästa sida"
                                width: 26
                                visible: !root.continuousLibrary
                                enabled: !root.libraryBusy && root.hasNextPage
                                onClicked: root.browsePage(1)
                            }
                        }
                        MediaAction { property string uiColorScope: "ui.control.MediaSurface.30";
                            objectName: "mediaLibraryChunkRetry"
                            visible: root.continuousLibrary && root.chunkError.length > 0
                            width: parent.width
                            text: root.chunkNeedsRefresh ? "Uppdatera listan" : "Försök läsa fler titlar igen"
                            onClicked: root.retryChunk()
                        }
                        MediaAction { property string uiColorScope: "ui.control.MediaSurface.31";
                            width: parent.width
                            visible: root.mode === "FETCH" && !!(root.status.fetch && root.status.fetch.present)
                            text: root.status.fetch && root.status.fetch.running ? "Öppna hämtaren ↗" : "Hämtverktyg ↗"
                            tip: "Öppna Torlink. Färdiga filer spelas direkt i biblioteket."
                            onClicked: root.openFetch()
                        }
                        MediaAction { property string uiColorScope: "ui.control.MediaSurface.32";
                            width: parent.width
                            visible: (root.mode === "MUSIC" || root.mode === "RADIO")
                                && !!(root.status.tools && root.status.tools.cliamp && root.status.tools.cliamp.present)
                            text: "Öppna musikverktyg ↗"
                            onClicked: root.openCliamp()
                        }
                    }
                }

                Item {
                    id: hole
                    objectName: "workspaceMediaHole"
                    width: root.showDisplay
                        ? Math.max(16, stage.width - catalogPanel.width - (catalogPanel.visible ? 8 : 0))
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
                            if (!root.liveVideo && root.surfaceHost && root.surfaceHost.mediaReportSourceFailure)
                                root.surfaceHost.mediaReportSourceFailure(String(root.now.id || ""), root.playerGeneration)
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
                                root.reportClock(true)
                                if (root.liveVideo)
                                    root.schedulePlayerRetry()
                                else {
                                    root.finishVideo()
                                }
                            }
                            root.reportPlayerState()
                        }
                        onPlaybackStateChanged: {
                            if (root.playerResetting)
                                return
                            root.reportClock(true)
                            root.reportPlayerState()
                            if (root.qmlVideo
                                && root.playerWantsPlay
                                && root.status.paused !== true
                                && holePlayer.playbackState === MediaPlayer.StoppedState)
                                root.schedulePlayerRetry()
                        }
                        onPositionChanged: root.reportClock(holePlayer.duration > 0 && holePlayer.position >= holePlayer.duration)
                        onDurationChanged: root.reportClock(true)
                    }

                    Window {
                        id: fullscreenWindow
                        objectName: "mediaVideoFullscreenWindow"
                        color: "#000000"
                        flags: Qt.FramelessWindowHint
                        visible: false
                        onClosing: root.videoFullscreen = false

                        Shortcut {
                            sequence: "Escape"
                            context: Qt.WindowShortcut
                            enabled: fullscreenWindow.visible
                            onActivated: root.videoFullscreen = false
                        }

                        VideoOutput {
                            id: fullscreenVideo
                            objectName: "mediaFullscreenVideo"
                            anchors.fill: parent
                            fillMode: VideoOutput.PreserveAspectFit
                        }

                        MediaFullscreenControls { property string uiColorScope: "ui.widget.MediaSurface.MediaFullscreenControls.37";
                            id: fullscreenControls
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            anchors.margins: 12
                            active: root.videoFullscreen && root.qmlVideo
                            positionSeconds: Number(holePlayer.position || 0) / 1000
                            durationSeconds: Number(holePlayer.duration || 0) / 1000
                            seekEnabled: root.qmlVideo && !!root.surfaceHost && !!root.surfaceHost.mediaSeek
                                && holePlayer.seekable === true && holePlayer.duration > 500
                            liveStream: root.liveVideo
                            volumeValue: root.fullscreenVolume
                            playbackKey: JSON.stringify([String(root.now.id || ""), root.lastPlayUrl, root.playerGeneration])
                            onSeekRequested: function(seconds) { root.seekFullscreenVideo(seconds) }
                            onVolumePreviewed: function(value) { root.previewFullscreenVolume(value) }
                            onVolumeCommitted: function(value) { root.commitFullscreenVolume(value) }
                            onRevealedChanged: if (revealed) root.refreshFullscreenVolume()
                        }

                        Rectangle {
                            id: fullscreenExitButton
                            objectName: "mediaFullscreenExitButton"
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 18
                            width: fullscreenExitLabel.implicitWidth + 18
                            height: 24
                            radius: 2
                            color: fullscreenExitMouse.containsMouse ? RuntimeTheme.GGTheme.selected : RuntimeTheme.GGTheme.panel
                            opacity: fullscreenExitMouse.containsMouse ? 1.0 : 0.0
                            border.color: RuntimeTheme.GGTheme.edge
                            border.width: 1
                            z: 2

                            Behavior on opacity {
                                NumberAnimation { duration: 140 }
                            }

                            GGText { colorKey: "ui.MediaSurface.26";
                                id: fullscreenExitLabel
                                anchors.centerIn: parent
                                text: "EXIT FULLSCREEN"
                                color: RuntimeTheme.GGTheme.bright
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

                    GGText { colorKey: "ui.MediaSurface.27";
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
                        color: RuntimeTheme.GGTheme.selected
                        font.family: "monospace"
                        font.pixelSize: 18
                        font.bold: true
                    }

                    BufferMark { property string uiColorScope: "ui.widget.MediaSurface.BufferMark.38";
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
                        color: fullscreenMouse.containsMouse ? RuntimeTheme.GGTheme.selected : RuntimeTheme.GGTheme.panel
                        opacity: fullscreenMouse.containsMouse ? 1.0 : 0.0
                        border.color: RuntimeTheme.GGTheme.edge
                        border.width: 1
                        visible: root.qmlVideo
                        z: 4

                        Behavior on opacity {
                            NumberAnimation { duration: 140 }
                        }

                        GGText { colorKey: "ui.MediaSurface.28";
                            id: fullscreenLabel
                            anchors.centerIn: parent
                            text: root.videoFullscreen ? "EXIT FULLSCREEN" : "FULLSCREEN"
                            color: RuntimeTheme.GGTheme.bright
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

                    GGText { colorKey: "ui.MediaSurface.29";
                        id: holeError
                        objectName: "workspaceMediaVideoError"
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        anchors.margins: 8
                        text: root.playerError || String(root.status.embed_error || "")
                        visible: text.length > 0
                        color: RuntimeTheme.GGTheme.accent
                        wrapMode: Text.WordWrap
                        horizontalAlignment: Text.AlignHCenter
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                }
            }
        }
    }
