import QtQuick
import QtQuick.Controls
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
    property bool playerResolving: false
    property int playerResolveTicket: 0
    property int playerGeneration: -1
    property real playerStartedAt: 0
    property real playerLastFrameAt: 0
    property real playerStableSince: 0
    property bool videoFullscreen: false
    property string libraryPage: "music"
    property string libraryLetter: "all"
    property string categoryFilter: "all"
    property string languageFilter: "all"
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
        && root.catalogRowsReady && root.catalogModel.count > 0 && root.catalogModel.count < root.catalogTotal
    readonly property bool hasLibraryFilters: root.libraryLetter !== "all" || root.categoryFilter !== "all"
        || root.languageFilter !== "all" || root.seasonFilter !== "all" || root.localQuery.trim().length > 0
    readonly property bool pagedLibrary: !!root.surfaceHost && !!root.surfaceHost.mediaLibraryBrowse
    readonly property string desiredBrowseKey: root.browseKey(root.libraryPage, root.libraryLetter,
        root.categoryFilter, root.languageFilter, root.seasonFilter, root.localQuery, root.pageOffset)
    readonly property bool displayedPageMatches: !root.pagedLibrary || root.catalogBrowseKey === root.desiredBrowseKey
    readonly property int pageTotal: root.pagedLibrary ? root.catalogTotal : root.filteredItems.length
    readonly property bool hasNextPage: root.pagedLibrary && root.displayedPageMatches
        && root.catalogHasMore && root.pageOffset + root.catalogPageSize < root.catalogTotal
    readonly property color ink: "#e6edf3"
    readonly property color muted: "#9299a3"
    readonly property color gold: "#c8a97e"
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
        ? root.catalogCategories : root.filterOptions("category", "Alla kategorier")
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

    function browseKey(page, letter, category, language, season, query, offset) {
        return JSON.stringify([String(page), String(letter || "all"), String(category || "all"),
            String(language || "all"), String(season || "all"), String(query || "").trim(), Number(offset || 0)])
    }

    function snapshotBrowseKey(snapshot) {
        return root.browseKey(snapshot.library_page, snapshot.library_letter, snapshot.library_category,
            snapshot.library_language, snapshot.library_season, snapshot.library_query, snapshot.library_offset)
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
            root.surfaceHost.mediaLibraryChunk(root.libraryPage, root.libraryLetter,
                root.categoryFilter, root.languageFilter, root.seasonFilter, root.localQuery.trim(),
                root.chunkOffset, root.chunkTicket)
        } catch (err) {
            root.chunkBusy = false
            root.chunkError = "Kunde inte läsa fler titlar. Försök igen."
            chunkTimeout.stop()
        }
    }

    function retryChunk() {
        if (root.chunkNeedsRefresh) {
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
        Qt.callLater(root.maybeLoadMore)
    }

    function optionRows(rows, label) {
        var output = [{value: "all", label: label}]
        if (!rows || rows.length === undefined)
            return output
        // Option lists are also bounded; a corrupt provider cannot grow the menu indefinitely.
        for (var i = 0; i < Math.min(256, rows.length); ++i) {
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
            if (root.languageFilter !== "all" && root.rowValue(row, "language") !== root.languageFilter)
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
        if (row.language)
            parts.push(root.rowValue(row, "language"))
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
        if (row.availability === "failed")
            return "Senast otillgänglig. Välj titeln för att försöka igen."
        if (row.availability === "verified") {
            if (row.availability_scope === "checked_episodes")
                return "Serien har provspelade avsnitt. Äldre kontroller förnyas när du trycker på play."
            if (row.availability_fresh === false)
                return "Tidigare provspelad. En ny källkontroll görs när du trycker på play."
            return "Provspelad vid senaste källkontrollen."
        }
        return "Information och uppspelningskälla laddas när du väljer titeln."
    }

    function clearFilters() {
        root.pageOffset = 0
        root.libraryLetter = "all"
        root.categoryFilter = "all"
        root.languageFilter = "all"
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
        } else if ((root.contentType(row) === "series" || root.contentType(row) === "collection")
                   && root.surfaceHost && root.surfaceHost.mediaOpenCollection) {
            root.rememberParentView()
            root.expectedCollectionKey = String(row.collection_key || "")
            root.expectedCollectionTitle = root.rowTitle(row)
            root.clearFilters()
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
                && root.catalogModel.count > root.catalogPageSize
                && catalogList.contentY - catalogList.originY >= root.catalogPageSize * 50) {
                // Keep a coherent visited snapshot while someone is reading
                // farther down. New admissions appear on return to the first
                // block; chunk revision checks still reject mixed offsets.
                root.catalogUpdatePending = true
                return
            }
            root.catalogUpdatePending = false
            if (root.continuousLibrary && (structuralRevision !== root.catalogStructureRevision
                    || root.status.library_requires_reset === true)) {
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
            root.catalogCategories = root.optionRows(root.status.library_categories, "Alla kategorier")
            root.catalogLanguages = root.optionRows(root.status.library_languages, "Alla språk")
            root.catalogSeasons = root.optionRows(root.status.library_seasons, "Alla säsonger")
            // Data and collection identity commit together. A filter can keep
            // the same80 IDs/count; relying only on filteredItemsChanged would
            // otherwise leave reused parent delegates until a scroll repaints.
            catalogSyncTimer.stop()
            root.syncCatalogModel()
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
            color: action.down ? "#34383d" : action.checked ? "#292d32"
                : action.hovered ? "#242424" : "#161616"
            border.color: action.visualFocus ? "#c8cdd4" : action.checked ? "#747b84" : "#3a3a3a"
            opacity: action.enabled ? 1 : 0.45
        }
        contentItem: Text {
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
        currentIndex: {
            for (var i = 0; i < model.length; ++i)
                if (String(model[i].value) === selector.selectedValue)
                    return i
            return 0
        }
        background: Rectangle {
            color: "#161616"
            radius: 3
            border.color: selector.activeFocus ? "#9299a3" : selector.hovered ? "#656a72" : "#3a3a3a"
        }
        contentItem: Text {
            text: selector.displayText
            textFormat: Text.PlainText
            color: selector.selectedValue === "all" ? root.muted : root.ink
            font: selector.font
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        indicator: Text {
            x: selector.width - width - 7
            anchors.verticalCenter: parent.verticalCenter
            text: "▾"
            color: root.muted
            font.pixelSize: 11
        }
        delegate: ItemDelegate {
            required property var modelData
            required property int index
            width: Math.max(selector.width, 180)
            height: 28
            highlighted: selector.highlightedIndex === index
            contentItem: Text {
                text: modelData.label
                textFormat: Text.PlainText
                color: root.ink
                font: selector.font
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
            }
            background: Rectangle { color: parent.highlighted ? "#34383d" : "#1a1a1a" }
        }
        popup: Popup {
            y: selector.height + 2
            width: Math.max(selector.width, 192)
            padding: 3
            implicitHeight: Math.min(300, contentItem.implicitHeight + 6)
            background: Rectangle { color: "#1a1a1a"; border.color: "#656a72"; radius: 3 }
            contentItem: ListView {
                clip: true
                implicitHeight: contentHeight
                model: selector.popup.visible ? selector.delegateModel : null
                currentIndex: selector.highlightedIndex
                ScrollBar.vertical: GgScrollBar { keepVisible: true }
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

            Flickable {
                id: navigationStrip
                width: parent.width
                height: 28
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
                        delegate: MediaAction {
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
                ScrollBar.horizontal: GgScrollBar {}
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
                        color: "#121212"
                        border.color: searchBox.activeFocus ? "#9299a3" : "#464646"
                    }
                    BufferMark {
                        objectName: "mediaSearchBuffer"
                        anchors.right: parent.right
                        anchors.rightMargin: 7
                        anchors.verticalCenter: parent.verticalCenter
                        active: root.libraryBusy
                        cell: 4
                    }
                }
                MediaAction {
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
                    color: "#111111"
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
                            Text {
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
                            MediaAction {
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
                            MediaAction {
                                objectName: "mediaLibraryBack"
                                text: "‹"
                                tip: "Tillbaka till biblioteket"
                                onClicked: root.goBack()
                            }
                            Text {
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
                            MediaSelect {
                                objectName: "mediaLetterSelector"
                                width: parent.width - (clearLibraryFilters.visible ? clearLibraryFilters.width + 4 : 0)
                                selectedValue: root.libraryLetter
                                model: [{value: "all", label: "A–Ö · Alla"}, {value: "#", label: "# · Siffror och symboler"}]
                                    .concat("ABCDEFGHIJKLMNOPQRSTUVWXYZÅÄÖ".split("").map(function(letter) {
                                        return {value: letter, label: letter}
                                    }))
                                onActivated: root.libraryLetter = String(currentValue)
                            }
                            MediaAction {
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
                            columns: width < 190 ? 1 : 2
                            spacing: 4
                            visible: root.collectionTitle.length === 0
                                && (root.categoryOptions.length > 1 || root.languageOptions.length > 1)
                            MediaSelect {
                                objectName: "mediaCategorySelector"
                                width: parent.columns === 2 && root.languageOptions.length > 1
                                    ? (parent.width - 4) / 2 : parent.width
                                visible: root.categoryOptions.length > 1
                                selectedValue: root.categoryFilter
                                model: root.categoryOptions
                                onActivated: root.categoryFilter = String(currentValue)
                            }
                            MediaSelect {
                                objectName: "mediaLanguageSelector"
                                width: parent.columns === 2 && root.categoryOptions.length > 1
                                    ? (parent.width - 4) / 2 : parent.width
                                visible: root.languageOptions.length > 1
                                selectedValue: root.languageFilter
                                model: root.languageOptions
                                onActivated: root.languageFilter = String(currentValue)
                            }
                        }

                        MediaSelect {
                            objectName: "mediaSeasonSelector"
                            width: parent.width
                            visible: root.collectionTitle.length > 0 && root.seasonOptions.length > 1
                            height: visible ? 26 : 0
                            selectedValue: root.seasonFilter
                            model: root.seasonOptions
                            onActivated: root.seasonFilter = String(currentValue)
                        }

                        Rectangle { width: parent.width; height: 1; color: "#333333" }
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
                        ScrollBar.vertical: GgScrollBar { keepVisible: true }
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

                        delegate: ItemDelegate {
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
                                    : catalogRow.highlighted || catalogRow.hovered ? "#202020" : "#161616"
                                border.color: catalogRow.activeFocus ? "#9299a3" : catalogRow.rowActive ? "#646b73" : "transparent"
                            }
                            highlighted: ListView.isCurrentItem
                            contentItem: Item {
                                Text {
                                    anchors.left: parent.left
                                    anchors.right: rowMark.left
                                    anchors.rightMargin: rowChevron.visible ? 16 : 3
                                    anchors.top: parent.top
                                    height: 18
                                    text: (catalogRow.rowActive ? "▶ " : "") + root.displayTitle(catalogRow.modelData)
                                    textFormat: Text.PlainText
                                    color: catalogRow.rowActive ? root.ink : "#c9cfd7"
                                    font.family: "monospace"
                                    font.pixelSize: 11
                                    font.bold: catalogRow.rowActive
                                    verticalAlignment: Text.AlignVCenter
                                    elide: Text.ElideRight
                                }
                                Text {
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
                                BufferMark {
                                    id: rowMark
                                    objectName: "mediaItemBuffer"
                                    anchors.right: parent.right
                                    anchors.top: parent.top
                                    anchors.topMargin: 4
                                    active: catalogRow.rowBuffering
                                    cell: 4
                                }
                                Text {
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

                        Text {
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
                                : "Inga kontrollerade titlar i den här vyn ännu."
                            textFormat: Text.PlainText
                            color: root.muted
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.WordWrap
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
                        Text {
                            objectName: "mediaLibraryLoadState"
                            width: parent.width
                            height: 15
                            text: root.chunkError || root.libraryError || (root.loadingItemId ? "Laddar vald titel…"
                                : root.chunkBusy ? "Laddar fler titlar…"
                                : root.libraryBusy ? "Laddar katalog…"
                                : root.libraryIndexing ? "Uppdaterar katalog…"
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
                            MediaAction {
                                objectName: "mediaLibraryPrevious"
                                text: "‹"
                                tip: "Föregående sida"
                                width: 26
                                visible: !root.continuousLibrary
                                enabled: !root.libraryBusy && root.pageOffset > 0
                                onClicked: root.browsePage(-1)
                            }
                            Text {
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
                            MediaAction {
                                objectName: "mediaLibraryNext"
                                text: "›"
                                tip: "Nästa sida"
                                width: 26
                                visible: !root.continuousLibrary
                                enabled: !root.libraryBusy && root.hasNextPage
                                onClicked: root.browsePage(1)
                            }
                        }
                        MediaAction {
                            objectName: "mediaLibraryChunkRetry"
                            visible: root.continuousLibrary && root.chunkError.length > 0
                            width: parent.width
                            text: root.chunkNeedsRefresh ? "Uppdatera listan" : "Försök läsa fler titlar igen"
                            onClicked: root.retryChunk()
                        }
                        MediaAction {
                            width: parent.width
                            visible: root.mode === "FETCH" && !!(root.status.fetch && root.status.fetch.present)
                            text: root.status.fetch && root.status.fetch.running ? "Öppna hämtaren ↗" : "Hämtverktyg ↗"
                            tip: "Öppna Torlink. Färdiga filer spelas direkt i biblioteket."
                            onClicked: root.openFetch()
                        }
                        MediaAction {
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
                                    root.playerEnded = true
                                    root.playerWantsPlay = false
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
