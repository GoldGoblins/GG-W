import QtQuick
import QtQuick.Controls

Item {
    id: root
    objectName: "workspaceMarketplacePane"

    property var surfaceHost: null
    property color frameBorder: "#6a6a6a"
    property int frameRadius: 4
    property string statusJson: "{}"
    property string page: "CATALOG"
    property string draftKind: "OBJECT"
    property string draftCategory: "ITEM"
    property string draftMaterial: "UNKNOWN"
    property var draftParts: []
    property var draftLives: []
    property string searchQuery: ""
    property string formError: ""
    readonly property var nav: [
        "CATALOG",
        "REGISTER",
        "RECEIPT",
        "ELEMENTS",
        "LIVES",
        "ACTIVITY"
    ]

    readonly property var status: {
        try {
            return JSON.parse(root.statusJson || "{}")
        } catch (err) {
            return {}
        }
    }

    readonly property var listings: {
        var rows = root.status.listings
        if (!rows || rows.length === undefined)
            return []
        var q = String(root.searchQuery || "").toLowerCase()
        if (!q)
            return rows
        var out = []
        var i
        for (i = 0; i < rows.length; i++) {
            var row = rows[i] || {}
            var hay = String(row.title || "") + " " + String(row.material || "")
                + " " + String(row.kind || "") + " " + String(row.maker || "")
            if (hay.toLowerCase().indexOf(q) >= 0)
                out.push(row)
        }
        return out
    }
    readonly property var categories: root.status.categories || []
    readonly property var elements: root.status.elements || []
    readonly property var lives: root.status.lives || []
    readonly property var ledger: root.status.ledger || []
    readonly property var filters: root.status.filters && root.status.filters.length
        ? root.status.filters
        : ["ALL", "ELEMENT", "OBJECT", "ITEM", "MATERIAL"]
    readonly property var materials: root.status.materials && root.status.materials.length
        ? root.status.materials
        : ["UNKNOWN", "MIXED", "Fe", "Cu", "Au"]
    readonly property var kinds: root.status.kinds && root.status.kinds.length
        ? root.status.kinds
        : ["ELEMENT", "SUBSTANCE", "OBJECT"]
    readonly property var wallet: root.status.wallet || {}
    readonly property var merkle: root.status.merkle || {}
    readonly property var selected: root.status.selected || null
    readonly property var proof: root.status.proof || null
    readonly property var selectedParts: (root.selected && root.selected.composition) || []
    readonly property var selectedLife: (root.selected && root.selected.lifecycle) || []
    readonly property string legend: String(root.status.legend || "TESTNET")
    readonly property string activeFilter: String(root.status.filter || "ALL")
    readonly property bool connected: root.wallet.connected === true

    function refresh() {
        if (!root.surfaceHost || !root.surfaceHost.marketplaceStatus)
            return
        var raw = root.surfaceHost.marketplaceStatus()
        if (raw === root.statusJson)
            return
        root.statusJson = raw
        root.formError = String(root.status.error || "")
    }

    function applyRaw(raw) {
        root.statusJson = String(raw || "{}")
        root.formError = String(root.status.error || "")
    }

    function setFilter(name) {
        if (!root.surfaceHost || !root.surfaceHost.marketplaceSetFilter)
            return
        root.applyRaw(root.surfaceHost.marketplaceSetFilter(name))
    }

    function selectRow(listingId) {
        if (!root.surfaceHost || !root.surfaceHost.marketplaceSelect)
            return
        root.applyRaw(root.surfaceHost.marketplaceSelect(listingId))
        root.page = "RECEIPT"
    }

    function togglePart(row) {
        var id = String((row || {}).id || "")
        if (!id)
            return
        var next = []
        var found = false
        var i
        for (i = 0; i < root.draftParts.length; i++) {
            if (String(root.draftParts[i].id || "") === id)
                found = true
            else
                next.push(root.draftParts[i])
        }
        if (!found) {
            next.push({
                "id": id,
                "kind": String(row.kind || "ELEMENT"),
                "symbol": String(row.material || row.symbol || ""),
                "title": String(row.title || ""),
                "mass_g": Number(row.mass_g || 0)
            })
        }
        root.draftParts = next
    }

    function toggleLife(listingId) {
        var id = String(listingId || "")
        if (!id)
            return
        var next = []
        var found = false
        var i
        for (i = 0; i < root.draftLives.length; i++) {
            if (String(root.draftLives[i]) === id)
                found = true
            else
                next.push(root.draftLives[i])
        }
        if (!found)
            next.push(id)
        root.draftLives = next
    }

    function submitList() {
        if (!root.surfaceHost || !root.surfaceHost.marketplaceList)
            return
        root.applyRaw(
            root.surfaceHost.marketplaceList(
                JSON.stringify({
                    "title": titleField.text,
                    "kind": root.draftKind,
                    "category": root.draftCategory,
                    "material": root.draftMaterial,
                    "mint": mintField.text,
                    "price_sol": priceField.text,
                    "description": descField.text,
                    "maker": makerField.text,
                    "origin": originField.text,
                    "mass_g": massField.text,
                    "composition": root.draftParts,
                    "previous_lives": root.draftLives
                })
            )
        )
        if (!root.formError) {
            titleField.text = ""
            mintField.text = ""
            priceField.text = "0"
            descField.text = ""
            makerField.text = ""
            originField.text = ""
            massField.text = "0"
            root.draftParts = []
            root.draftLives = []
            root.page = "RECEIPT"
        }
    }

    function registerElement(symbol) {
        if (!root.surfaceHost || !root.surfaceHost.marketplaceListElement)
            return
        root.applyRaw(root.surfaceHost.marketplaceListElement(symbol))
        if (!root.formError)
            root.page = "RECEIPT"
    }

    function rebirthSelected() {
        if (!root.surfaceHost || !root.surfaceHost.marketplaceRebirth)
            return
        if (root.draftLives.length < 1)
            return
        root.applyRaw(
            root.surfaceHost.marketplaceRebirth(
                JSON.stringify({
                    "title": rebirthField.text,
                    "previous_lives": root.draftLives,
                    "category": "ITEM",
                    "material": "MIXED"
                })
            )
        )
        if (!root.formError) {
            rebirthField.text = ""
            root.draftLives = []
            root.page = "RECEIPT"
        }
    }

    function delistSelected() {
        if (!root.surfaceHost || !root.surfaceHost.marketplaceDelist)
            return
        if (!root.selected)
            return
        root.applyRaw(
            root.surfaceHost.marketplaceDelist(String(root.selected.id || ""))
        )
    }

    function buySelected() {
        if (!root.surfaceHost || !root.surfaceHost.marketplacePaperBuy)
            return
        if (!root.selected)
            return
        root.applyRaw(
            root.surfaceHost.marketplacePaperBuy(String(root.selected.id || ""))
        )
    }

    function shortHash(value) {
        var t = String(value || "")
        if (t.length < 12)
            return t.length ? t : "—"
        return t.substring(0, 8) + "…" + t.substring(t.length - 4)
    }

    function statusColor(value) {
        var s = String(value || "")
        if (s === "LISTED")
            return "#8db89a"
        if (s === "SOLD")
            return "#c8a97e"
        if (s === "DELISTED")
            return "#c98989"
        return "#a8b0b8"
    }

    Timer {
        interval: 4000
        running: root.visible
        repeat: true
        onTriggered: root.refresh()
    }

    onVisibleChanged: {
        if (visible)
            root.refresh()
    }

    Item {
        anchors.fill: parent
        anchors.leftMargin: 6
        anchors.rightMargin: 6
        anchors.topMargin: 4
        anchors.bottomMargin: 6

        Item {
            id: topBar
            width: parent.width
            height: 20

            Row {
                spacing: 0
                Repeater {
                    model: root.nav
                    Text {
                        required property int index
                        required property string modelData
                        text: index > 0 ? ("  |  " + modelData) : modelData
                        color: root.page === modelData ? "#d8dee9" : "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                        font.bold: root.page === modelData
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.page = modelData
                        }
                    }
                }
            }

            Row {
                anchors.right: parent.right
                spacing: 12
                Text {
                    text: root.legend
                    color: root.legend === "TESTNET" ? "#8db89a" : "#c8a97e"
                    font.family: "monospace"
                    font.pixelSize: 12
                    font.bold: true
                }
                Text {
                    text: root.connected
                        ? String(root.wallet.short || "")
                        : "WALLET OFF"
                    color: root.connected ? "#c8cdd4" : "#c8a97e"
                    font.family: "monospace"
                    font.pixelSize: 12
                }
                Text {
                    text: "MERKLE " + String(root.merkle.root_short || "—")
                    color: "#b6a6c8"
                    font.family: "monospace"
                    font.pixelSize: 12
                }
            }
        }

        Item {
            id: field
            anchors.top: topBar.bottom
            anchors.topMargin: 8
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom

            Column {
                id: catalogHead
                width: parent.width
                spacing: 6
                visible: root.page === "CATALOG"

                GgField {
                    id: searchField
                    width: Math.min(parent.width, 420)
                    placeholderText: "search title, maker, material"
                    onTextChanged: root.searchQuery = text
                }

                Flow {
                    width: parent.width
                    spacing: 10
                    Repeater {
                        model: root.filters
                        Text {
                            required property string modelData
                            text: modelData
                            color: root.activeFilter === modelData ? "#d8dee9" : "#5d6670"
                            font.family: "monospace"
                            font.pixelSize: 12
                            font.bold: root.activeFilter === modelData
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.setFilter(modelData)
                            }
                        }
                    }
                }

                Text {
                    text: String(root.listings.length)
                        + " shown · "
                        + String(root.status.listing_count || 0)
                        + " receipts · NFT = kvitto, not pixels"
                    color: "#a8b0b8"
                    font.family: "monospace"
                    font.pixelSize: 12
                }
            }

            Flickable {
                anchors.fill: parent
                anchors.topMargin: catalogHead.visible ? catalogHead.height + 6 : 0
                visible: root.page === "CATALOG"
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                contentHeight: catalogFlow.height
                ScrollBar.vertical: GgScrollBar {}

                Flow {
                    id: catalogFlow
                    width: parent.width
                    spacing: 8

                    Text {
                        visible: root.listings.length === 0
                        width: catalogFlow.width
                        text: "Inga kvitton ännu. REGISTER ett föremål eller ELEMENT ett grundämne. Ett kvitto är en paper-NFT på testnet."
                        color: "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }

                    Repeater {
                        model: root.listings.length
                        delegate: TmogCard {
                            required property int index
                            width: Math.max(240, (catalogFlow.width - 8) / 2)
                            height: 92
                            leftLegend: String((root.listings[index] || {}).kind || "OBJECT")
                            rightLegend: String((root.listings[index] || {}).status || "")
                            borderColor: root.selected && String(root.selected.id || "")
                                         === String((root.listings[index] || {}).id || "")
                                ? "#8b949e" : "#3a3a3a"

                            Column {
                                anchors.fill: parent
                                spacing: 2
                                Text {
                                    width: parent.width
                                    text: String((root.listings[index] || {}).title || "")
                                    color: "#e6e6e6"
                                    font.family: "monospace"
                                    font.pixelSize: 13
                                    font.bold: true
                                    elide: Text.ElideRight
                                }
                                Text {
                                    width: parent.width
                                    text: String((root.listings[index] || {}).material || "")
                                        + " · "
                                        + String((root.listings[index] || {}).part_count || 0)
                                        + " parts · "
                                        + String((root.listings[index] || {}).life_count || 0)
                                        + " lives · "
                                        + String((root.listings[index] || {}).price_sol || "0")
                                        + " SOL"
                                    color: "#c8a97e"
                                    font.family: "monospace"
                                    font.pixelSize: 12
                                    elide: Text.ElideRight
                                }
                                Text {
                                    width: parent.width
                                    text: String((root.listings[index] || {}).receipt || "")
                                    color: "#b6a6c8"
                                    font.family: "monospace"
                                    font.pixelSize: 12
                                    elide: Text.ElideRight
                                }
                            }

                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: function(mouse) {
                                    var row = root.listings[index] || {}
                                    if (mouse.modifiers & Qt.ControlModifier)
                                        root.togglePart(row)
                                    else if (mouse.modifiers & Qt.ShiftModifier)
                                        root.toggleLife(String(row.id || ""))
                                    else
                                        root.selectRow(String(row.id || ""))
                                }
                                onPressAndHold: root.toggleLife(String((root.listings[index] || {}).id || ""))
                            }
                        }
                    }
                }
            }

            Flickable {
                anchors.fill: parent
                visible: root.page === "REGISTER" || root.page === "LIST"
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                contentHeight: listCol.height
                ScrollBar.vertical: GgScrollBar {}

                Column {
                    id: listCol
                    width: parent.width
                    spacing: 8

                    Text {
                        width: parent.width
                        text: "Blocket-enkelt: namnge föremålet, välj om det är grundämne, ämne eller sak. Kvittot mintas som paper-NFT. Sammansättning och tidigare liv kan fyllas i senare när fler producenter är med."
                        color: "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }

                    Text {
                        text: "KIND"
                        color: "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                    Flow {
                        width: parent.width
                        spacing: 10
                        Repeater {
                            model: root.kinds
                            Text {
                                required property string modelData
                                text: modelData
                                color: root.draftKind === modelData ? "#d8dee9" : "#5d6670"
                                font.family: "monospace"
                                font.pixelSize: 12
                                font.bold: root.draftKind === modelData
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        root.draftKind = modelData
                                        if (modelData === "ELEMENT")
                                            root.draftCategory = "MATERIAL"
                                        else if (modelData === "OBJECT")
                                            root.draftCategory = "ITEM"
                                    }
                                }
                            }
                        }
                    }

                    Text {
                        text: "TITLE"
                        color: "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                    GgField {
                        id: titleField
                        width: Math.min(listCol.width, 520)
                        placeholderText: "cykel, guldörhänge, stålämne, Fe…"
                    }

                    Text {
                        text: "CATEGORY"
                        color: "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                    Flow {
                        width: parent.width
                        spacing: 10
                        Repeater {
                            model: root.categories.length
                            Text {
                                required property int index
                                text: String((root.categories[index] || {}).id || "")
                                color: root.draftCategory
                                       === String((root.categories[index] || {}).id || "")
                                    ? "#d8dee9" : "#5d6670"
                                font.family: "monospace"
                                font.pixelSize: 12
                                font.bold: root.draftCategory
                                           === String((root.categories[index] || {}).id || "")
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: root.draftCategory = String(
                                        (root.categories[index] || {}).id || "ITEM"
                                    )
                                }
                            }
                        }
                    }

                    Text {
                        text: root.draftKind === "ELEMENT" ? "ELEMENT" : "MATERIAL"
                        color: "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                    Flow {
                        width: parent.width
                        spacing: 10
                        Repeater {
                            model: root.draftKind === "ELEMENT" ? ["Fe", "Cu", "Au", "Ag", "C", "Al", "Si", "O", "H", "Pb", "Sn", "Zn", "Ti", "Ni", "Cr"] : root.materials
                            Text {
                                required property string modelData
                                text: modelData
                                color: root.draftMaterial === modelData ? "#d8dee9" : "#5d6670"
                                font.family: "monospace"
                                font.pixelSize: 12
                                font.bold: root.draftMaterial === modelData
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: root.draftMaterial = modelData
                                }
                            }
                        }
                    }

                    Row {
                        spacing: 12
                        Column {
                            spacing: 4
                            Text {
                                text: "MASS g"
                                color: "#a8b0b8"
                                font.family: "monospace"
                                font.pixelSize: 12
                            }
                            GgField {
                                id: massField
                                width: 120
                                text: "0"
                            }
                        }
                        Column {
                            spacing: 4
                            Text {
                                text: "PRICE SOL"
                                color: "#a8b0b8"
                                font.family: "monospace"
                                font.pixelSize: 12
                            }
                            GgField {
                                id: priceField
                                width: 120
                                text: "0"
                            }
                        }
                    }

                    Text {
                        text: "MAKER"
                        color: "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                    GgField {
                        id: makerField
                        width: Math.min(listCol.width, 520)
                        placeholderText: "who made it"
                    }

                    Text {
                        text: "ORIGIN"
                        color: "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                    GgField {
                        id: originField
                        width: Math.min(listCol.width, 520)
                        placeholderText: "mine, mill, workshop, previous owner"
                    }

                    Text {
                        text: "DESCRIPTION"
                        color: "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                    GgField {
                        id: descField
                        width: Math.min(listCol.width, 520)
                        placeholderText: "what it is, what it is made of, where it came from"
                    }

                    Text {
                        text: "SOLANA MINT (optional · empty = paper receipt)"
                        color: "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                    GgField {
                        id: mintField
                        width: Math.min(listCol.width, 520)
                        placeholderText: "base58 mint or leave blank"
                    }

                    Text {
                        width: parent.width
                        text: "COMPOSITION  " + String(root.draftParts.length) + " parts · click an ELEMENT receipt in CATALOG then here, or register elements first"
                        color: "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        visible: root.draftParts.length > 0
                        width: parent.width
                        text: {
                            var i
                            var bits = []
                            for (i = 0; i < root.draftParts.length; i++)
                                bits.push(String(root.draftParts[i].symbol || root.draftParts[i].title || ""))
                            return bits.join(" · ")
                        }
                        color: "#8db89a"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }

                    Text {
                        visible: root.formError.length > 0
                        width: parent.width
                        text: root.formError
                        color: "#c98989"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }

                    GgButton {
                        text: "MINT RECEIPT"
                        onClicked: root.submitList()
                    }
                }
            }

            Flickable {
                anchors.fill: parent
                visible: root.page === "RECEIPT" || root.page === "PROVENANCE"
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                contentHeight: proofCol.height
                ScrollBar.vertical: GgScrollBar {}

                Column {
                    id: proofCol
                    width: parent.width
                    spacing: 6

                    Text {
                        visible: root.selected === null
                        width: parent.width
                        text: "Välj ett kvitto i CATALOG. Identity-hashen är kvittot. State-hashen rör sig när ägare byts."
                        color: "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }

                    Text {
                        visible: root.selected !== null
                        text: String((root.selected || {}).title || "")
                        color: "#e6e6e6"
                        font.family: "monospace"
                        font.pixelSize: 18
                        font.bold: true
                    }
                    Text {
                        visible: root.selected !== null
                        text: String((root.selected || {}).kind || "")
                            + " · "
                            + String((root.selected || {}).category || "")
                            + " · "
                            + String((root.selected || {}).material || "")
                            + " · "
                            + String((root.selected || {}).status || "")
                            + " · "
                            + String((root.selected || {}).mass_g || 0)
                            + " g · "
                            + String((root.selected || {}).price_sol || "0")
                            + " SOL"
                        color: "#c8cdd4"
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                    Text {
                        visible: root.selected !== null
                        width: parent.width
                        text: String((root.selected || {}).description || "")
                        color: "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        visible: root.selected !== null
                        width: parent.width
                        text: "receipt   " + String((root.selected || {}).receipt || "")
                        color: "#c8a97e"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WrapAnywhere
                    }
                    Text {
                        visible: root.selected !== null
                        width: parent.width
                        text: "identity  " + String((root.proof || {}).identity_sha256 || "")
                        color: "#b6a6c8"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WrapAnywhere
                    }
                    Text {
                        visible: root.selected !== null
                        width: parent.width
                        text: "state     " + String((root.proof || {}).state_sha256 || "")
                        color: "#b6a6c8"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WrapAnywhere
                    }
                    Text {
                        visible: root.selected !== null
                        width: parent.width
                        text: "catalog   " + String((root.proof || {}).catalog_root || "")
                        color: "#b6a6c8"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WrapAnywhere
                    }
                    Text {
                        visible: root.selected !== null
                        width: parent.width
                        text: "maker     "
                            + (String((root.selected || {}).maker || "") || "—")
                            + "   origin "
                            + (String((root.selected || {}).origin || "") || "—")
                        color: "#c8cdd4"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        visible: root.selected !== null
                        width: parent.width
                        text: "owner     "
                            + (String((root.selected || {}).owner || "") || "unowned")
                        color: "#c8cdd4"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WrapAnywhere
                    }

                    Text {
                        visible: root.selectedParts.length > 0
                        text: "COMPOSITION"
                        color: "#d8dee9"
                        font.family: "monospace"
                        font.pixelSize: 12
                        font.bold: true
                    }
                    Repeater {
                        model: root.selectedParts
                        delegate: Text {
                            required property var modelData
                            width: proofCol.width
                            text: String(modelData.symbol || "")
                                + "  "
                                + String(modelData.title || "")
                                + "  "
                                + String(modelData.mass_g || 0)
                                + " g  "
                                + String(modelData.id || "")
                            color: "#8db89a"
                            font.family: "monospace"
                            font.pixelSize: 12
                            wrapMode: Text.WordWrap
                        }
                    }

                    Text {
                        visible: root.selectedLife.length > 0
                        text: "LIFECYCLE"
                        color: "#d8dee9"
                        font.family: "monospace"
                        font.pixelSize: 12
                        font.bold: true
                    }
                    Repeater {
                        model: root.selectedLife
                        delegate: Text {
                            required property var modelData
                            text: String(modelData.kind || "")
                                + "  "
                                + String(modelData.ts || "")
                            color: "#c8a97e"
                            font.family: "monospace"
                            font.pixelSize: 12
                        }
                    }

                    Row {
                        visible: root.selected !== null
                            && String((root.selected || {}).status || "") === "LISTED"
                        spacing: 10
                        GgButton {
                            text: "PAPER BUY"
                            onClicked: root.buySelected()
                        }
                        GgButton {
                            text: "DELIST"
                            onClicked: root.delistSelected()
                        }
                        GgButton {
                            text: "USE AS PREVIOUS LIFE"
                            onClicked: root.toggleLife(String((root.selected || {}).id || ""))
                        }
                    }

                    Text {
                        visible: root.formError.length > 0 && (root.page === "RECEIPT" || root.page === "PROVENANCE")
                        width: parent.width
                        text: root.formError
                        color: "#c98989"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                }
            }

            Flickable {
                anchors.fill: parent
                visible: root.page === "ELEMENTS"
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                contentHeight: elCol.height
                ScrollBar.vertical: GgScrollBar {}

                Column {
                    id: elCol
                    width: parent.width
                    spacing: 8

                    Text {
                        width: parent.width
                        text: "Grundämnen är egna kvitton. Ett föremål är en sammansättning. Klicka för att minta paper-NFT för ämnet."
                        color: "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }

                    Flow {
                        width: parent.width
                        spacing: 8
                        Repeater {
                            model: root.elements.length
                            delegate: TmogCard {
                                required property int index
                                width: 92
                                height: 56
                                leftLegend: String((root.elements[index] || {}).symbol || "")
                                rightLegend: (root.elements[index] || {}).listed ? "ON" : ""
                                borderColor: (root.elements[index] || {}).listed ? "#8db89a" : "#3a3a3a"
                                Text {
                                    anchors.centerIn: parent
                                    text: String((root.elements[index] || {}).name || "")
                                    color: "#c8cdd4"
                                    font.family: "monospace"
                                    font.pixelSize: 12
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: root.registerElement(String((root.elements[index] || {}).symbol || ""))
                                }
                            }
                        }
                    }
                }
            }

            Flickable {
                anchors.fill: parent
                visible: root.page === "LIVES"
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                contentHeight: lifeCol.height
                ScrollBar.vertical: GgScrollBar {}

                Column {
                    id: lifeCol
                    width: parent.width
                    spacing: 8

                    Text {
                        width: parent.width
                        text: "Tidigare liv. Markera kvitton (hold i CATALOG eller USE AS PREVIOUS LIFE) och minta ett nytt föremål som bär deras material."
                        color: "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }

                    Text {
                        text: "SELECTED OBJECT LIVES  "
                            + String(root.lives.length)
                        color: "#d8dee9"
                        font.family: "monospace"
                        font.pixelSize: 12
                        font.bold: true
                    }
                    Repeater {
                        model: root.lives
                        delegate: Text {
                            required property var modelData
                            width: lifeCol.width
                            text: String(modelData.title || "")
                                + "  "
                                + String(modelData.material || "")
                                + "  "
                                + String(modelData.status || "")
                                + "  "
                                + String(modelData.id || "")
                            color: "#8db89a"
                            font.family: "monospace"
                            font.pixelSize: 12
                            wrapMode: Text.WordWrap
                            MouseArea {
                                anchors.fill: parent
                                onClicked: root.selectRow(String(modelData.id || ""))
                            }
                        }
                    }

                    Text {
                        text: "REBIRTH SET  " + String(root.draftLives.length)
                        color: "#c8a97e"
                        font.family: "monospace"
                        font.pixelSize: 12
                        font.bold: true
                    }
                    Text {
                        visible: root.draftLives.length > 0
                        width: parent.width
                        text: root.draftLives.join(" · ")
                        color: "#c8cdd4"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WrapAnywhere
                    }
                    GgField {
                        id: rebirthField
                        width: Math.min(parent.width, 520)
                        placeholderText: "new object title"
                    }
                    GgButton {
                        text: "MINT REBORN OBJECT"
                        onClicked: root.rebirthSelected()
                    }
                    Text {
                        visible: root.formError.length > 0 && root.page === "LIVES"
                        width: parent.width
                        text: root.formError
                        color: "#c98989"
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                }
            }

            Flickable {
                anchors.fill: parent
                visible: root.page === "ACTIVITY"
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                contentHeight: actCol.height
                ScrollBar.vertical: GgScrollBar {}

                Column {
                    id: actCol
                    width: parent.width
                    spacing: 6

                    Text {
                        visible: root.ledger.length === 0
                        text: "No catalog events yet."
                        color: "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                    }

                    Repeater {
                        model: root.ledger.length
                        delegate: Row {
                            required property int index
                            width: actCol.width
                            spacing: 10
                            readonly property var row: root.ledger[root.ledger.length - 1 - index] || {}

                            Text {
                                width: 72
                                text: String(row.kind || "")
                                color: String(row.kind || "") === "BUY"
                                    ? "#8db89a"
                                    : (String(row.kind || "") === "DELIST"
                                        ? "#c98989"
                                        : "#c8a97e")
                                font.family: "monospace"
                                font.pixelSize: 12
                                font.bold: true
                            }
                            Text {
                                width: parent.width - 82
                                text: String(row.listing_id || "")
                                    + "  "
                                    + String(row.txid || "PAPER")
                                    + "  "
                                    + root.shortHash(row.identity_sha256)
                                color: "#c8cdd4"
                                font.family: "monospace"
                                font.pixelSize: 12
                                wrapMode: Text.WordWrap
                            }
                        }
                    }
                }
            }
        }
    }
}
