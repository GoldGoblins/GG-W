import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs

Item {
    id: root
    objectName: "workspaceKnowledgePane"
    property var surfaceHost: null
    property color frameBorder: "#4a4a4a"
    property int frameRadius: 4
    signal requestToChat(string prompt)

    readonly property color ink: "#e9edf1"
    readonly property color muted: "#84909f"
    readonly property color gold: "#c8a97e"
    readonly property bool compact: width < 1060
    readonly property bool narrow: width < 790
    property bool browserVisible: true
    property bool detailsVisible: true
    property bool importBusy: false
    property bool pageBusy: false
    property int viewRevision: 0
    property var requestedPage: null
    property var queuedPage: null
    property string searchQuery: ""
    property string filterKind: "ALL"
    property string mode: "BILD"
    property bool bodySourceOpen: false
    property string bodySourceTitle: "WEST"
    property string notice: ""
    property string importSummary: ""
    property var importMessages: []
    property var payload: ({nodes: [], edges: [], sources: [], hits: [], counts: {}})
    property var selectedNode: null
    property var selectedHotspot: null
    property var selectedDetail: ({passages: []})
    property var pageView: null
    property var navigation: []
    readonly property var exampleScene: ({
        title: "Cellens inre värld",
        image_url: Qt.resolvedUrl("../assets/knowledge-cell.png"),
        illustrative: true,
        hotspots: [
            {id: "nucleus", label: "Cellkärna", x: 0.47, y: 0.40,
                summary: "En detalj i den illustrativa exempelbilden. Klicka på Zooma in för att undersöka den på nära håll.", citations: []},
            {id: "golgi", label: "Golgiapparat", x: 0.72, y: 0.60,
                summary: "Exempel på en markerad struktur. Egna illustrationer kan knytas till dokument, sidnummer och förklaringar.", citations: []},
            {id: "mitochondrion", label: "Mitokondrie", x: 0.34, y: 0.68,
                summary: "Bildens klickpunkter kan användas för att gå från en helhet till en specifik del.", citations: []},
            {id: "membrane", label: "Cellmembran", x: 0.20, y: 0.45,
                summary: "Exempelbildens yttre gräns. Bilden är illustrativ och dess proportioner är inte ett mätresultat.", citations: []}
        ]
    })
    property var scene: exampleScene
    readonly property var libraryNodes: payload.nodes || []
    readonly property var searchHits: payload.hits || []
    readonly property var libraryEntries: {
        var entries = []
        var scenes = payload.scenes || []
        for (var i = 0; i < scenes.length; ++i) {
            if (filterKind === "SOURCE") continue
            if (searchQuery.length && String(scenes[i].title || "").toLowerCase().indexOf(searchQuery.toLowerCase()) < 0) continue
            entries.push({id: scenes[i].id, label: scenes[i].title, kind: "SCENE", hotspot_count: scenes[i].hotspot_count})
        }
        return entries.concat(searchQuery.length && searchHits.length ? searchHits : libraryNodes)
    }
    readonly property var graphNodes: libraryNodes.slice(0, 64)
    readonly property string selectionTitle: bodySourceOpen ? bodySourceTitle : selectedHotspot ? String(selectedHotspot.label || "Detalj")
        : (selectedNode ? String(selectedNode.label || "Material") : String(scene.title || "Kunskapsvärld"))
    readonly property string selectionSummary: selectedHotspot ? String(selectedHotspot.summary || "")
        : (selectedNode ? String(selectedNode.summary || "") : "Utforska helheten. Klicka på en detalj för att komma närmare.")
    readonly property var passages: selectedHotspot && selectedHotspot.citations && selectedHotspot.citations.length
        ? selectedHotspot.citations : (selectedDetail.passages || [])
    readonly property real leftWidth: !browserVisible || narrow || bodySourceOpen ? 0 : (compact ? 180 : 214)
    readonly property real rightWidth: !detailsVisible || narrow || bodySourceOpen ? 0 : (compact ? 238 : 284)
    readonly property bool showingText: !!root.pageView && root.pageView.status === "TEXT_READY"
    readonly property bool sceneStale: !!root.scene.stale || !!root.scene.source_changed
    readonly property bool canPrepareQuestion: Number((root.payload.counts || {}).sources || 0) > 0
        && (!root.sceneStale || root.selectedNode !== null || root.pageView !== null)

    function parse(raw) {
        try { return JSON.parse(String(raw || "{}")) } catch (err) { return {status: "ERROR"} }
    }

    function reasonLabel(reason) {
        var labels = {
            INVALID_PDF: "PDF-filen kunde inte läsas.",
            PDF_PASSWORD_REQUIRED: "PDF-filen är lösenordsskyddad.",
            PDF_PAGE_LIMIT: "PDF-filen har fler sidor än importgränsen.",
            PDF_TIMEOUT: "PDF-läsningen tog för lång tid.",
            PDF_WORKER_FAILED: "PDF-läsningen avbröts.",
            FILE_SIZE_LIMIT: "Filen är större än importgränsen.",
            TEXT_CHARACTER_LIMIT: "Texten är större än importgränsen.",
            SOURCE_EMPTY: "Filen innehåller inget läsbart material.",
            INVALID_IMAGE: "Bilden kunde inte läsas.",
            IMAGE_PIXEL_LIMIT: "Bilden är större än importgränsen.",
            TEXT_MUST_BE_UTF8: "Textfilen behöver vara sparad som UTF-8.",
            BINARY_TEXT_NOT_ALLOWED: "Filen är inte en textfil.",
            UNSUPPORTED_FILE_TYPE: "Filtypen stöds inte.",
            NO_SUPPORTED_FILES: "Inga filer av en typ som stöds hittades.",
            SELECT_ONE_TO_32_FILES: "Välj högst 32 filer åt gången."
        }
        return labels[String(reason || "")] || String(reason || "Filen kunde inte läsas.")
    }

    function applySnapshot(result) {
        root.payload = result
        if (root.scene && root.scene.id) {
            // Revalidate the displayed scene only. Library summaries do not
            // carry page revisions and a quote can survive a context edit.
            if (root.surfaceHost && root.surfaceHost.knowledgeScene) {
                var checked = parse(root.surfaceHost.knowledgeScene(String(root.scene.id)))
                if (checked.status === "SCENE_READY" && checked.scene) {
                    root.scene = checked.scene
                } else {
                    var missing = {}
                    for (var field in root.scene) missing[field] = root.scene[field]
                    missing.stale = true
                    missing.notice = "Den sparade vyn behöver kontrolleras innan den används."
                    root.scene = missing
                }
            } else {
                var scenes = result.scenes || []
                for (var i = 0; i < scenes.length; ++i) {
                    if (String(scenes[i].id) !== String(root.scene.id) || !scenes[i].stale) continue
                var updated = {}
                for (var key in root.scene) updated[key] = root.scene[key]
                updated.stale = true
                updated.notice = scenes[i].notice || "Källorna har ändrats. Hänvisningarna behöver kontrolleras på nytt."
                root.scene = updated
                }
            }
        }
        graph.requestPaint()
    }

    function refresh() {
        if (!root.surfaceHost || !root.surfaceHost.knowledgeSnapshot) return
        var result = parse(root.surfaceHost.knowledgeSnapshot(root.searchQuery, root.filterKind))
        if (result.status === "ERROR") {
            root.notice = String(result.message || result.reason || "Materialet kunde inte läsas.")
            return
        }
        root.applySnapshot(result)
    }

    function loadScene(value) {
        if (!value || !value.image_url) return false
        var url = String(value.image_url)
        if (/^https?:/i.test(url) || /^data:/i.test(url)) {
            root.notice = "Välj en lokal bild för den här vyn."
            return false
        }
        root.scene = value
        root.viewRevision += 1
        root.queuedPage = null
        root.pageView = null
        root.selectedHotspot = null
        root.selectedNode = null
        root.selectedDetail = {passages: []}
        root.mode = "BILD"
        root.notice = value.stale || value.source_changed
            ? String(value.notice || "Källorna har ändrats. Uppdatera den visuella förklaringen innan den används.") : ""
        raster.resetView()
        return true
    }

    function openScene(id) {
        if (!root.surfaceHost || !root.surfaceHost.knowledgeScene) return
        var result = root.parse(root.surfaceHost.knowledgeScene(String(id)))
        if (result.status !== "SCENE_READY" || !result.scene) {
            root.notice = String(result.message || result.reason || "Vyn kunde inte öppnas.")
            return
        }
        if (root.loadScene(result.scene)) {
            root.selectedNode = null
            root.selectedDetail = {passages: []}
            if (!root.sceneStale) root.notice = ""
        }
    }

    function showExample() {
        root.loadScene(root.exampleScene)
        root.selectedNode = null
        root.selectedDetail = {passages: []}
        root.notice = ""
    }

    function importFiles(files) {
        if (!root.surfaceHost || !root.surfaceHost.knowledgeImport || root.importBusy) return
        var paths = []
        for (var i = 0; i < files.length; ++i) paths.push(String(files[i]))
        if (!paths.length) return
        root.importBusy = root.surfaceHost.knowledgeImport(JSON.stringify(paths))
        root.notice = root.importBusy ? "Läser ditt material…" : "Importen kunde inte starta."
    }

    function selectNode(id, remember, sourcePage) {
        if (!root.surfaceHost || !root.surfaceHost.knowledgeDetail) return
        var detail = parse(root.surfaceHost.knowledgeDetail(String(id)))
        if (!detail.node) { root.notice = String(detail.message || detail.reason || "Detaljen kunde inte öppnas."); return }
        if (remember !== false && root.selectedNode)
            root.navigation = root.navigation.concat([String(root.selectedNode.id)])
        root.selectedNode = detail.node
        root.viewRevision += 1
        root.queuedPage = null
        root.pageView = null
        root.selectedDetail = detail
        root.selectedHotspot = null
        root.detailsVisible = true
        if (detail.node.kind === "CONCEPT") root.mode = "KARTA"
        if (detail.image_url) loadScene({title: detail.node.label, image_url: detail.image_url, illustrative: false, hotspots: []})
        if (detail.node.kind === "OBJECT" || detail.node.kind === "SOURCE") {
            var sourceId = String(detail.source_id || detail.node.source_id || detail.node.id || "")
            if (sourceId) root.openPage(sourceId, Number(sourcePage || 1))
        }
        graph.requestPaint()
    }

    function selectHotspot(point) {
        root.viewRevision += 1
        root.queuedPage = null
        root.selectedHotspot = point
        root.selectedNode = null
        root.selectedDetail = {passages: []}
        root.detailsVisible = true
        if (point.node_id && root.surfaceHost && root.surfaceHost.knowledgeDetail) {
            var result = parse(root.surfaceHost.knowledgeDetail(String(point.node_id)))
            root.selectedDetail = result
        }
    }

    function openPage(sourceId, page) {
        if (!root.surfaceHost || !root.surfaceHost.knowledgePage) return
        var request = {source_id: String(sourceId), page: Number(page || 1), revision: root.viewRevision}
        if (root.pageBusy) { root.queuedPage = request; return }
        root.requestedPage = request
        root.pageBusy = root.surfaceHost.knowledgePage(request.source_id, request.page)
        if (!root.pageBusy) root.requestedPage = null
        if (root.pageBusy) root.notice = "Öppnar källsidan…"
    }

    function back() {
        if (root.bodySourceOpen) {
            root.showBody()
        } else if (root.navigation.length) {
            var previous = root.navigation.slice()
            var target = previous.pop()
            root.navigation = previous
            root.selectNode(target, false)
        } else {
            root.viewRevision += 1
            root.queuedPage = null
            root.pageView = null
            root.selectedNode = null
            root.selectedHotspot = null
            root.selectedDetail = {passages: []}
            root.mode = "BILD"
            raster.resetView()
        }
    }

    function showBody() {
        root.viewRevision += 1
        root.queuedPage = null
        root.pageView = null
        root.bodySourceOpen = false
        root.mode = "KROPP"
        root.notice = "Fiktiva övningsfall · originalets källsidor finns vid varje ämne"
    }

    function graphPoint(index) {
        var count = Math.max(1, root.graphNodes.length)
        var angle = index * 2.399963229728653
        var radius = Math.sqrt((index + 0.8) / count)
        return {x: graph.width / 2 + Math.cos(angle) * radius * Math.max(40, graph.width / 2 - 70),
            y: graph.height / 2 + Math.sin(angle) * radius * Math.max(40, graph.height / 2 - 70)}
    }

    function explainSelection() {
        var prompt = "Förklara " + root.selectionTitle + " utifrån mitt importerade kunskapsmaterial. "
            + "Ange dokument och sidnummer. Skilj det som står i källorna från slutsatser och osäkerheter."
        if (!root.selectedNode && root.scene.illustrative) prompt += " Den visade cellbilden är bara ett illustrativt exempel."
        root.requestToChat(prompt)
        root.notice = "Frågan ligger i chatten. Tryck Enter för att skicka."
    }

    function visualizeSelection() {
        root.requestToChat("Skapa en vacker, källgrundad rasterillustration med klickbar navigation för "
            + root.selectionTitle + ". Använd mitt importerade kunskapsmaterial, återanvänd befintliga bilder "
            + "när det går och koppla förklaringar till dokument och sidnummer. Märk illustrativa detaljer tydligt.")
        root.notice = "Frågan ligger i chatten. Tryck Enter för att skicka."
    }

    Component.onCompleted: refresh()
    onSurfaceHostChanged: if (surfaceHost) refresh()
    onVisibleChanged: if (visible) refresh()

    Connections {
        target: root.surfaceHost
        ignoreUnknownSignals: true
        function onKnowledgeUpdated(raw) {
            var result = root.parse(raw)
            if (result.nodes) root.applySnapshot(result)
        }
        function onKnowledgeImportFinished(raw) {
            var result = root.parse(raw)
            root.importBusy = false
            var imported = Number(result.imported || result.imported_count || 0)
            var cached = Number(result.cached || 0)
            var errors = Number(result.errors || (result.status === "ERROR" ? 1 : 0))
            root.importSummary = imported + " nya · " + cached + " återanvända · " + errors + " kunde inte läsas"
            var messages = []
            var rows = result.results || []
            for (var i = 0; i < rows.length; ++i) {
                if (rows[i].status === "ERROR") messages.push(String(rows[i].title || "Fil") + ": " + root.reasonLabel(rows[i].reason))
            }
            if (!messages.length && result.status === "ERROR") messages.push(root.reasonLabel(result.reason))
            root.importMessages = messages
            root.notice = root.importSummary + (messages.length ? " · " + messages[0] : "")
            root.refresh()
            if (messages.length) importReport.open()
        }
        function onKnowledgePageReady(raw) {
            var result = root.parse(raw)
            var request = root.requestedPage
            root.requestedPage = null
            root.pageBusy = false
            if (root.queuedPage) {
                var next = root.queuedPage
                root.queuedPage = null
                if (next.revision === root.viewRevision) root.openPage(next.source_id, next.page)
                return
            }
            if (!request || request.revision !== root.viewRevision) return
            if (result.source_id && String(result.source_id) !== request.source_id) return
            if (result.page && Number(result.page) !== request.page) return
            if ((result.status === "PAGE_READY" && result.image_url) || result.status === "TEXT_READY") {
                root.pageView = result
                root.mode = "BILD"
                root.notice = ""
            } else root.notice = String(result.message || result.reason || "Sidan kunde inte visas som bild.")
        }
    }

    FileDialog {
        id: materialDialog
        title: "Välj kunskapsmaterial eller föremålsbilder"
        fileMode: FileDialog.OpenFiles
        nameFilters: ["Kunskapsmaterial (*.pdf *.md *.txt *.rst *.json *.png *.jpg *.jpeg *.webp)", "Alla filer (*)"]
        onAccepted: root.importFiles(selectedFiles)
    }

    Dialog {
        id: importReport
        objectName: "knowledgeImportReport"
        title: "Importresultat"
        modal: true
        anchors.centerIn: parent
        width: Math.min(560, root.width - 40)
        height: Math.min(390, root.height - 40)
        standardButtons: Dialog.Ok
        contentItem: ScrollView {
            clip: true
            TextArea {
                text: root.importSummary + "\n\n" + root.importMessages.join("\n\n")
                readOnly: true; selectByMouse: true; wrapMode: TextArea.Wrap
                textFormat: TextEdit.PlainText
                color: "#d6dee7"; font.pixelSize: 13
                background: Rectangle { color: "#151c25" }
            }
        }
        background: Rectangle { color: "#151c25"; border.color: "#4a5866"; radius: 7 }
    }

    component AtlasButton: Button {
        id: control
        property bool accent: false
        property bool active: false
        implicitHeight: 32
        implicitWidth: label.implicitWidth + 26
        padding: 0
        hoverEnabled: true
        background: Rectangle {
            radius: 5
            color: control.accent ? (control.hovered ? "#ddc199" : "#c8a97e")
                : (control.active ? "#27333b" : (control.hovered ? "#222b34" : "#172029"))
            border.color: control.active ? "#73877d" : "#2e3944"
            border.width: control.accent ? 0 : 1
            opacity: control.enabled ? 1 : 0.4
        }
        contentItem: Text {
            id: label
            text: control.text
            color: control.accent ? "#171819" : (control.active ? "#e4eae5" : "#bdc7d1")
            font.pixelSize: 12
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
    }

    Rectangle { anchors.fill: parent; color: "#10151c"; radius: root.frameRadius }

    RowLayout {
        id: header
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
        anchors.margins: 16
        height: 46; spacing: root.width < 650 ? 5 : 14
        Column {
            visible: root.width >= 650
            spacing: 3
            Text { text: "ATLAS"; color: root.gold; font.pixelSize: 12; font.letterSpacing: 4 }
            Text { text: "Kunskap att utforska"; color: root.ink; font.pixelSize: root.compact ? 17 : 21 }
        }
        Item { Layout.fillWidth: true }
        AtlasButton {
            objectName: "knowledgeBodyButton"
            text: root.bodySourceOpen ? "‹ Kroppen" : "Kropp / WEST"
            active: root.mode === "KROPP"
            onClicked: root.showBody()
        }
        AtlasButton {
            objectName: "knowledgeAtlasButton"
            visible: root.mode === "KROPP"
            text: "Atlas"
            onClicked: { root.mode = "BILD"; root.notice = "" }
        }
        AtlasButton { visible: root.mode !== "KROPP" && !root.bodySourceOpen; text: root.width < 650 ? "☰" : "Material"; active: root.browserVisible; onClicked: root.browserVisible = !root.browserVisible }
        AtlasButton { visible: root.mode !== "KROPP" && !root.bodySourceOpen; text: root.width < 650 ? "i" : "Detaljer"; active: root.detailsVisible; onClicked: root.detailsVisible = !root.detailsVisible }
        AtlasButton {
            objectName: "knowledgeImportButton"
            text: root.importBusy ? "Läser…" : (root.width < 650 ? "+" : "+ Lägg till")
            accent: true; enabled: !root.importBusy
            onClicked: materialDialog.open()
        }
    }

    Item {
        id: content
        visible: root.mode !== "KROPP"
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: header.bottom; anchors.bottom: footer.top
        anchors.leftMargin: 14; anchors.rightMargin: 14; anchors.topMargin: 18; anchors.bottomMargin: 10

        Rectangle {
            id: browser
            width: root.narrow ? Math.min(270, content.width - 32) : root.leftWidth
            height: parent.height
            visible: root.browserVisible && !root.bodySourceOpen
            z: root.narrow ? 10 : 1
            radius: 7; color: root.narrow ? "#f0151c25" : "#151c25"
            border.color: "#26313e"
            ColumnLayout {
                anchors.fill: parent; anchors.margins: 13; spacing: 10
                Text { text: "DITT MATERIAL"; color: root.muted; font.pixelSize: 10; font.letterSpacing: 1.5 }
                TextField {
                    id: search
                    objectName: "knowledgeSearch"
                    Layout.fillWidth: true
                    implicitHeight: 34
                    placeholderText: "Sök i dokument…"
                    text: root.searchQuery
                    color: root.ink; placeholderTextColor: "#75818f"; font.pixelSize: 12
                    selectByMouse: true
                    background: Rectangle { color: "#0e151d"; radius: 5; border.color: search.activeFocus ? "#718879" : "#2a3744" }
                    onTextEdited: { root.searchQuery = text; searchDelay.restart() }
                    onAccepted: { searchDelay.stop(); root.refresh() }
                }
                RowLayout {
                    Layout.fillWidth: true; spacing: 5
                    Repeater {
                        model: [{label: "Alla", kind: "ALL"}, {label: "Källor", kind: "SOURCE"}, {label: "Föremål", kind: "OBJECT"}]
                        delegate: AtlasButton {
                            required property var modelData
                            Layout.fillWidth: true; implicitWidth: 0; implicitHeight: 27
                            text: modelData.label; active: root.filterKind === modelData.kind
                            onClicked: { root.filterKind = modelData.kind; root.refresh() }
                        }
                    }
                }
                ListView {
                    id: materialList
                    objectName: "knowledgeMaterialList"
                    Layout.fillWidth: true; Layout.fillHeight: true
                    clip: true; spacing: 5
                    model: root.libraryEntries
                    ScrollBar.vertical: GgScrollBar {}
                    delegate: Button {
                        id: materialRow
                        required property var modelData
                        width: ListView.view.width; height: root.searchQuery.length ? 76 : 58
                        hoverEnabled: true; padding: 9
                        readonly property string nodeId: String(modelData.node_id || modelData.id || modelData.source_id || "")
                        background: Rectangle {
                            radius: 4
                            color: root.selectedNode && String(root.selectedNode.id) === materialRow.nodeId
                                ? "#273530" : (materialRow.hovered ? "#212c38" : "#19232e")
                        }
                        contentItem: Column {
                            spacing: 4
                            Text {
                                width: parent.width; text: String(materialRow.modelData.label || materialRow.modelData.source_title || "Material")
                                color: root.ink; font.pixelSize: 12; elide: Text.ElideRight; textFormat: Text.PlainText
                            }
                            Text {
                                width: parent.width
                                text: materialRow.modelData.page ? "Sida " + materialRow.modelData.page
                                    : (materialRow.modelData.kind === "SCENE" ? "Klickbar vy · " + Number(materialRow.modelData.hotspot_count || 0) + " detaljer"
                                        : (materialRow.modelData.kind === "CONCEPT" ? "Begrepp · " + Number(materialRow.modelData.source_count || 0) + " källor"
                                            : (materialRow.modelData.kind === "OBJECT" ? "Föremålsbild" : "Dokument")))
                                color: "#8da594"; font.pixelSize: 10; elide: Text.ElideRight
                            }
                            Text {
                                width: parent.width; visible: root.searchQuery.length > 0
                                text: String(materialRow.modelData.text || materialRow.modelData.summary || "")
                                color: root.muted; font.pixelSize: 10; elide: Text.ElideRight; textFormat: Text.PlainText
                            }
                        }
                        onClicked: {
                            if (modelData.kind === "SCENE") root.openScene(nodeId)
                            else root.selectNode(nodeId, true, modelData.page || 1)
                            if (root.narrow) root.browserVisible = false
                        }
                    }
                    Column {
                        anchors.centerIn: parent
                        width: parent.width - 12; spacing: 9
                        visible: materialList.count === 0
                        Text {
                            width: parent.width
                            text: root.searchQuery.length ? "Ingen träff i materialet" : "Börja med ditt material"
                            color: root.ink; font.pixelSize: 13; wrapMode: Text.WordWrap
                        }
                        Text {
                            width: parent.width
                            text: root.searchQuery.length ? "Prova ett annat ord." : "Lägg till PDF:er, anteckningar eller föremålsbilder. Originalens sidor och källor följer med."
                            color: root.muted; font.pixelSize: 12; wrapMode: Text.WordWrap
                        }
                    }
                }
                Rectangle { Layout.fillWidth: true; height: 1; color: "#29333d" }
                AtlasButton { Layout.fillWidth: true; text: "Visa illustrativt exempel"; onClicked: root.showExample() }
                Text {
                    Layout.fillWidth: true; wrapMode: Text.WordWrap
                    text: Number((root.payload.counts || {}).sources || 0) + " källor  ·  "
                        + Number((root.payload.counts || {}).pages || 0) + " sidor"
                    color: root.muted; font.pixelSize: 11
                }
                Text {
                    Layout.fillWidth: true; visible: (root.payload.notices || []).length > 0
                    text: (root.payload.notices || []).join("\n")
                    color: "#b6a081"; font.pixelSize: 10; wrapMode: Text.WordWrap
                    maximumLineCount: 6; elide: Text.ElideRight; textFormat: Text.PlainText
                }
                AtlasButton {
                    Layout.fillWidth: true; visible: root.importMessages.length > 0
                    text: "Visa importresultat"; onClicked: importReport.open()
                }
            }
        }

        Rectangle {
            id: stage
            x: root.leftWidth > 0 ? root.leftWidth + 12 : 0
            width: Math.max(120, parent.width - x - (root.rightWidth > 0 ? root.rightWidth + 12 : 0))
            height: parent.height
            color: "#090d12"; radius: 8; clip: true; border.color: "#2d3742"

            KnowledgeRasterView {
                id: raster
                anchors.fill: parent
                visible: root.mode === "BILD" && !root.showingText
                imageSource: root.pageView ? String(root.pageView.image_url || "") : String(root.scene.image_url || "")
                hotspots: root.pageView ? [] : (root.scene.hotspots || [])
                selectedHotspotId: root.selectedHotspot ? String(root.selectedHotspot.id || "") : ""
                onHotspotActivated: function(hotspot) { root.selectHotspot(hotspot) }
            }

            Flickable {
                id: sourceTextViewport
                objectName: "knowledgeSourceTextViewport"
                anchors.fill: parent; anchors.topMargin: 80; anchors.bottomMargin: 66
                visible: root.mode === "BILD" && root.showingText
                contentWidth: width
                contentHeight: sourceText.implicitHeight + 36
                clip: true; boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: GgScrollBar {}
                TextEdit {
                    id: sourceText
                    objectName: "knowledgeSourceText"
                    x: 25; y: 14; width: parent.width - 50
                    text: root.showingText ? String(root.pageView.text || "") : ""
                    textFormat: TextEdit.PlainText
                    color: "#c8d0da"; selectionColor: "#4d655b"; selectedTextColor: "#ffffff"
                    font.pixelSize: 13; wrapMode: TextEdit.Wrap
                    readOnly: true; selectByMouse: true
                }
            }

            Item {
                id: mapView
                anchors.fill: parent; anchors.topMargin: 70; anchors.bottomMargin: 58
                visible: root.mode === "KARTA"
                Canvas {
                    id: graph
                    anchors.fill: parent
                    onWidthChanged: requestPaint()
                    onHeightChanged: requestPaint()
                    onPaint: {
                        var ctx = getContext("2d")
                        ctx.clearRect(0, 0, width, height)
                        var nodes = root.graphNodes
                        var positions = {}
                        for (var n = 0; n < nodes.length; ++n) positions[String(nodes[n].id)] = root.graphPoint(n)
                        var edges = root.payload.edges || []
                        ctx.lineWidth = 1
                        ctx.strokeStyle = "#314452"
                        for (var i = 0; i < Math.min(400, edges.length); ++i) {
                            var from = positions[String(edges[i].source)]
                            var to = positions[String(edges[i].target)]
                            if (from && to) { ctx.beginPath(); ctx.moveTo(from.x, from.y); ctx.lineTo(to.x, to.y); ctx.stroke() }
                        }
                    }
                }
                Repeater {
                    model: root.graphNodes
                    delegate: Button {
                        id: graphNode
                        required property var modelData
                        required property int index
                        readonly property var point: root.graphPoint(index)
                        x: point.x - width / 2; y: point.y - height / 2
                        width: modelData.kind === "SOURCE" || modelData.kind === "OBJECT" ? 34 : 20
                        height: width
                        padding: 0; hoverEnabled: true
                        Accessible.name: String(modelData.label || "Begrepp")
                        background: Rectangle {
                            radius: graphNode.width / 2
                            color: graphNode.modelData.kind === "OBJECT" ? "#7b654e"
                                : (graphNode.modelData.kind === "SOURCE" ? "#3b6158" : "#345363")
                            border.color: graphNode.hovered || (root.selectedNode && root.selectedNode.id === graphNode.modelData.id)
                                ? "#e1ca9c" : "#729197"
                        }
                        contentItem: Item {}
                        Text {
                            anchors.top: parent.bottom; anchors.topMargin: 5; anchors.horizontalCenter: parent.horizontalCenter
                            text: String(graphNode.modelData.label || "")
                            textFormat: Text.PlainText; color: graphNode.hovered ? "#edd8b2" : "#aab8c2"
                            font.pixelSize: 10; width: 104; elide: Text.ElideRight; horizontalAlignment: Text.AlignHCenter
                        }
                        onClicked: root.selectNode(modelData.id)
                    }
                }
                Text {
                    anchors.centerIn: parent; width: parent.width - 50
                    visible: root.graphNodes.length === 0
                    text: "Lägg till material för att se begrepp och källor här."
                    color: root.muted; font.pixelSize: 14; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap
                }
            }

            Rectangle {
                anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                height: 95
                gradient: Gradient { GradientStop { position: 0; color: "#f0090d12" } GradientStop { position: 1; color: "#00090d12" } }
            }
            Column {
                anchors.left: parent.left; anchors.top: parent.top; anchors.margins: 19
                width: parent.width - 172; spacing: 5
                Text {
                    text: root.pageView ? "KÄLLSIDA · " + String(root.pageView.page || 1)
                        : (root.scene.illustrative ? "ILLUSTRATIVT EXEMPEL" : "DITT MATERIAL")
                    color: root.scene.illustrative && !root.pageView ? "#c8a97e" : "#8db89a"
                    font.pixelSize: 9; font.letterSpacing: 1.5
                }
                Text {
                    width: parent.width
                    text: root.mode === "KARTA" ? "Samband i materialet" : (root.pageView ? root.selectionTitle : String(root.scene.title || "Kunskapsvärld"))
                    color: "#eef2f4"; font.pixelSize: root.compact ? 18 : 23; elide: Text.ElideRight; textFormat: Text.PlainText
                }
            }
            Row {
                anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 14; spacing: 5
                AtlasButton { text: "Bild"; active: root.mode === "BILD"; onClicked: root.mode = "BILD" }
                AtlasButton { text: "Karta"; active: root.mode === "KARTA"; onClicked: { root.mode = "KARTA"; graph.requestPaint() } }
            }

            Row {
                anchors.left: parent.left; anchors.bottom: parent.bottom; anchors.margins: 14
                spacing: 5
                AtlasButton { objectName: "knowledgeBack"; text: "‹ Tillbaka"; onClicked: root.back() }
                AtlasButton {
                    objectName: "knowledgeZoomOut"; text: "−"; visible: root.mode === "BILD" && !root.showingText
                    implicitWidth: 32; onClicked: raster.zoomAt(0.8, raster.width / 2, raster.height / 2)
                }
                AtlasButton {
                    objectName: "knowledgeZoomReset"; text: Math.round(raster.zoom * 100) + "%"; visible: root.mode === "BILD" && !root.showingText
                    onClicked: raster.resetView()
                }
                AtlasButton {
                    objectName: "knowledgeZoomIn"; text: "+"; visible: root.mode === "BILD" && !root.showingText
                    implicitWidth: 32; onClicked: raster.zoomAt(1.25, raster.width / 2, raster.height / 2)
                }
                AtlasButton {
                    text: "Punkter"; active: raster.annotationsVisible
                    visible: root.mode === "BILD" && !root.pageView && stage.width > 490
                    onClicked: raster.annotationsVisible = !raster.annotationsVisible
                }
            }

            Row {
                anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 14
                spacing: 5; visible: root.pageView !== null && root.mode === "BILD"
                AtlasButton {
                    text: "‹"; implicitWidth: 30
                    enabled: !root.pageBusy && root.pageView && Number(root.pageView.page) > 1
                    onClicked: root.openPage(root.pageView.source_id, Number(root.pageView.page) - 1)
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: root.pageView ? root.pageView.page + " / " + root.pageView.pages : ""
                    color: root.ink; font.pixelSize: 11
                }
                AtlasButton {
                    text: "›"; implicitWidth: 30
                    enabled: !root.pageBusy && root.pageView && Number(root.pageView.page) < Number(root.pageView.pages)
                    onClicked: root.openPage(root.pageView.source_id, Number(root.pageView.page) + 1)
                }
            }

            DropArea {
                id: drop
                anchors.fill: parent
                onDropped: function(event) {
                    if (event.hasUrls) { root.importFiles(event.urls); event.acceptProposedAction() }
                }
                Rectangle {
                    anchors.fill: parent; anchors.margins: 8
                    visible: drop.containsDrag
                    color: "#d917252c"; radius: 6; border.width: 2; border.color: root.gold
                    Text { anchors.centerIn: parent; text: "Släpp materialet här"; color: root.ink; font.pixelSize: 20 }
                }
            }
        }

        Rectangle {
            id: details
            x: root.narrow ? Math.max(0, content.width - width) : content.width - width
            width: root.narrow ? Math.min(290, content.width - 32) : root.rightWidth
            height: parent.height
            visible: root.detailsVisible && !root.bodySourceOpen
            z: root.narrow ? 11 : 1
            color: root.narrow ? "#f0151c25" : "#151c25"; radius: 7; border.color: "#26313e"
            ColumnLayout {
                anchors.fill: parent; anchors.margins: 17; spacing: 13
                RowLayout {
                    Layout.fillWidth: true
                    Text { Layout.fillWidth: true; text: "NÄRMARE"; color: root.muted; font.pixelSize: 10; font.letterSpacing: 1.5 }
                    AtlasButton { visible: root.narrow; text: "Stäng"; implicitHeight: 26; onClicked: root.detailsVisible = false }
                }
                Text {
                    Layout.fillWidth: true
                    text: root.selectionTitle; textFormat: Text.PlainText
                    color: root.ink; font.pixelSize: 23; wrapMode: Text.WordWrap
                    maximumLineCount: 3; elide: Text.ElideRight
                }
                Rectangle { Layout.fillWidth: true; height: 2; color: "#5e786d" }
                Text {
                    Layout.fillWidth: true
                    text: root.selectionSummary
                    textFormat: Text.PlainText
                    color: "#b7c3cf"; font.pixelSize: 12; wrapMode: Text.WordWrap
                    maximumLineCount: 5; elide: Text.ElideRight
                }
                Text {
                    objectName: "knowledgeStaleNotice"
                    Layout.fillWidth: true
                    visible: root.sceneStale && !root.selectedNode && !root.pageView
                    text: String(root.scene.notice || "Källorna har ändrats sedan den här vyn skapades. Hänvisningarna behöver kontrolleras på nytt.")
                    color: "#d5af78"; font.pixelSize: 12; wrapMode: Text.WordWrap
                    textFormat: Text.PlainText
                }
                AtlasButton {
                    objectName: "knowledgeFocusDetail"
                    Layout.fillWidth: true; visible: !!root.selectedHotspot && root.mode === "BILD"
                    text: "Zooma in på detaljen"
                    onClicked: {
                        raster.focusPoint(root.selectedHotspot.x, root.selectedHotspot.y, 2.7)
                        if (root.narrow) root.detailsVisible = false
                    }
                }
                Text {
                    Layout.fillWidth: true
                    text: root.passages.length ? "KÄLLOR OCH SIDOR" : (root.scene.illustrative && !root.selectedNode ? "OM EXEMPLET" : "KÄLLUNDERLAG")
                    color: root.muted; font.pixelSize: 10; font.letterSpacing: 1
                }
                ListView {
                    id: passageList
                    objectName: "knowledgePassageList"
                    Layout.fillWidth: true; Layout.fillHeight: true
                    clip: true; spacing: 13; model: root.passages
                    ScrollBar.vertical: GgScrollBar {}
                    delegate: Column {
                        required property var modelData
                        width: ListView.view.width; spacing: 7
                        Text {
                            width: parent.width
                            text: String(modelData.source_title || modelData.title || "Källa") + " · s. " + Number(modelData.page || 1)
                            textFormat: Text.PlainText
                            color: "#a7c5b2"; font.pixelSize: 11; wrapMode: Text.WordWrap
                        }
                        Text {
                            width: parent.width
                            text: String(modelData.text || modelData.quote || "")
                            textFormat: Text.PlainText
                            color: "#acb8c5"; font.pixelSize: 12; wrapMode: Text.WordWrap
                        }
                        AtlasButton {
                            text: "Öppna källsidan ↗"
                            visible: !!modelData.source_id
                            enabled: !root.pageBusy
                            onClicked: {
                                root.openPage(String(modelData.source_id), Number(modelData.page || 1))
                                if (root.narrow) root.detailsVisible = false
                            }
                        }
                        Rectangle { width: parent.width; height: 1; color: "#2a3540" }
                    }
                    Text {
                        width: parent.width; visible: passageList.count === 0
                        text: root.scene.illustrative && !root.selectedNode
                            ? "Illustrationen visar hur navigationen fungerar. Den är inte ett mätresultat eller hämtad ur dina dokument. Lägg till eget material för källbelagda förklaringar."
                            : "Ingen textkälla är kopplad till den här detaljen ännu. En bild i sig verifierar inte ett påstående."
                        color: root.muted; font.pixelSize: 12; wrapMode: Text.WordWrap
                    }
                }
                Text {
                    Layout.fillWidth: true
                    visible: root.mode === "KARTA"
                    text: "Linjer visar omnämnanden i källorna. De bevisar inte orsakssamband."
                    color: root.muted; font.pixelSize: 11; wrapMode: Text.WordWrap
                }
                Text {
                    Layout.fillWidth: true
                    visible: !!root.selectedDetail.passages_limited
                    text: "Visar " + root.passages.length + " av " + Number(root.selectedDetail.total_passages || 0)
                        + " källsidor. Öppna en källsida för att bläddra vidare."
                    color: root.muted; font.pixelSize: 11; wrapMode: Text.WordWrap
                }
                AtlasButton {
                    objectName: "knowledgeExplainButton"
                    Layout.fillWidth: true; text: "Förbered fråga med källor"
                    enabled: root.canPrepareQuestion
                    onClicked: root.explainSelection()
                }
                AtlasButton {
                    objectName: "knowledgeVisualizeButton"
                    Layout.fillWidth: true; text: "Förbered visuell förklaring"; accent: true
                    enabled: root.canPrepareQuestion
                    onClicked: root.visualizeSelection()
                }
            }
        }
    }

    KnowledgeBodyView {
        id: bodyView
        anchors.left: parent.left; anchors.right: parent.right
        anchors.top: header.bottom; anchors.bottom: footer.top
        anchors.leftMargin: 14; anchors.rightMargin: 14; anchors.topMargin: 18; anchors.bottomMargin: 10
        visible: root.mode === "KROPP"
        surfaceHost: root.surfaceHost
        onRequestSourcePage: function(sourceId, page) {
            root.bodySourceOpen = true
            root.bodySourceTitle = String(bodyView.currentTopic.label || bodyView.bundle.title || "WEST")
            root.viewRevision += 1
            root.mode = "BILD"
            root.openPage(sourceId, page)
        }
    }

    RowLayout {
        id: footer
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        anchors.leftMargin: 17; anchors.rightMargin: 17; anchors.bottomMargin: 10
        height: 20; spacing: 12
        Rectangle { width: 5; height: 5; radius: 2.5; color: root.importBusy || root.pageBusy ? root.gold : "#8db89a" }
        Text {
            Layout.fillWidth: true; elide: Text.ElideRight
            text: root.notice || (root.mode === "KARTA" ? "Klicka på en källa eller ett begrepp" : "Scrolla för att zooma · dra för att flytta · klicka för att utforska")
            color: root.muted; font.pixelSize: 11; textFormat: Text.PlainText
        }
        Text { visible: !root.narrow; text: "Navigation utan AI-kostnad"; color: "#8da594"; font.pixelSize: 11 }
    }

    Timer { id: searchDelay; interval: 220; onTriggered: root.refresh() }
}
