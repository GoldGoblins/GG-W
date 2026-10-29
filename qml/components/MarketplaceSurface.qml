
import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import "MarketplaceBrowse.js" as Browse

Item {
    id: root
    objectName: "workspaceMarketplacePane"

    property var surfaceHost: null
    property bool embedded:false
    property string catalogScope:"LOCAL"
    property bool discoveryRequested:false
    property bool stopPreviewsPending:false
    readonly property bool showPublic:catalogScope==="PUBLIC" || (catalogScope==="AUTO" && !Number(status.listing_count || 0))
    signal cryptoRequested(string section)
    property color frameBorder: RuntimeTheme.GGTheme.dim
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
    property string settlementAssetId: ""
    readonly property var settlementAssets: root.status.settlement_assets || []
    readonly property var operation: root.status.ui_operation || ({})
    readonly property bool operationBusy: operation.state === "running"
    property bool awaitingList: false
    property bool awaitingImage: false
    property var draftImage: ({})
    property string collectionFilter:""
    property string networkFilter:""
    property string currencyFilter:""
    property string kindFilter:""
    property string categoryFilter:""
    property string materialFilter:""
    property string facetKindFilter:""
    property string facetCollectionFilter:""
    property string facetOriginFilter:""
    property string facetMakerFilter:""
    property string saleFilter:""
    property string sortChoice:"recent"
    property bool imagesOnly:false
    property bool catalogFiltersOpen:false
    property string catalogMode:"ATLAS"
    property string catalogFocusId:""
    property string requestedReceiptId:""
    property bool linkNft:false
    property bool legacyMintOpen:false
    readonly property var nav: [
        "CATALOG",
        "REGISTER",
        "RECEIPT",
        "ELEMENTS",
        "LIVES",
        "ACTIVITY",
        "OMNI",
        "NFT"
    ]

    readonly property var status: {
        try {
            return JSON.parse(root.statusJson || "{}")
        } catch (err) {
            return {}
        }
    }

    readonly property var browseRows: {
        return Browse.apply(root.status.listings || [],{query:root.searchQuery,collection:root.collectionFilter,network:root.networkFilter,currency:root.currencyFilter,kind:root.kindFilter,status:root.saleFilter,sort:root.sortChoice,imagesOnly:root.imagesOnly})
    }
    readonly property var listings:browseRows.filter(function(row){return (!root.categoryFilter || row.category===root.categoryFilter) && (!root.materialFilter || row.material===root.materialFilter || (row.composition || []).some(function(part){return part.symbol===root.materialFilter})) && (!root.facetKindFilter || (root.facetKindFilter==="OBJECTS" ? row.kind!=="SERVICE" : row.kind===root.facetKindFilter)) && (!root.facetCollectionFilter || row.collection_name===root.facetCollectionFilter) && (!root.facetOriginFilter || row.origin===root.facetOriginFilter) && (!root.facetMakerFilter || row.maker===root.facetMakerFilter)})
    function choiceIndex(choices,value){for(var i=0;i<choices.length;i++)if(choices[i].id===value)return i;return 0}
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
    readonly property var selected: root.status.selected && (!root.requestedReceiptId || root.status.selected.id===root.requestedReceiptId) ? root.status.selected : null
    readonly property var proof: root.status.proof || null
    readonly property var selectedParts: (root.selected && root.selected.composition) || []
    readonly property var selectedLife: (root.selected && root.selected.lifecycle) || []
    readonly property string legend: String(root.status.legend || "TESTNET")
    readonly property string workspaceNetworkLabel:root.page==="CATALOG" && root.showPublic ? "PUBLIK LÄSNING" : root.page==="NFT" ? "NFT · LÄSLÄGE" : "LOKALA OBJEKTPASS"
    readonly property string activeFilter: String(root.status.filter || "ALL")
    readonly property bool connected: root.wallet.connected === true

    function discover(args){if(!operationBusy && surfaceHost && surfaceHost.marketplaceDiscover)applyRaw(surfaceHost.marketplaceDiscover(JSON.stringify(args)))}
    function requestPreviewStop(){stopPreviewsPending=true;Qt.callLater(flushPreviewStop)}
    function flushPreviewStop(){if(stopPreviewsPending && !operationBusy && surfaceHost && surfaceHost.marketplaceDiscover){stopPreviewsPending=false;discover({action:"stop_previews"})}}
    onOperationBusyChanged:if(!operationBusy)Qt.callLater(flushPreviewStop)
    function maybeDiscover(){if(visible && page==="CATALOG" && showPublic && !discoveryRequested && !operationBusy && surfaceHost && surfaceHost.marketplaceDiscover && (status.public_catalog || {}).source_state==="NOT_FETCHED"){discoveryRequested=true;discover({action:"refresh",provider:"coingecko",page:1})}}
    function refresh() {
        if (!root.surfaceHost || !root.surfaceHost.marketplaceStatus)
            return
        var raw = root.surfaceHost.marketplaceStatus()
        if (raw === root.statusJson)
            return
        root.applyRaw(raw)
    }

    function importImage(source) {
        if(root.operationBusy || !root.surfaceHost || !root.surfaceHost.marketplaceImportImage)return
        root.awaitingImage=true
        root.applyRaw(root.surfaceHost.marketplaceImportImage(String(source)))
    }

    function applyRaw(raw) {
        try {
            var previousMediaId=(root.status.draft_media || {}).id || ""
            var next=JSON.parse(String(raw || "{}"))
            if(!root.settlementAssetId && next.default_settlement_asset)root.settlementAssetId=next.default_settlement_asset
            root.formError=String(next.error || (next.ui_operation || {}).error || "")
            if (next.listings) {root.statusJson=raw;Qt.callLater(root.maybeDiscover)}
            else if ((next.ui_operation || {}).state === "running") root.statusJson=raw
            if((next.ui_operation || {}).name === "market_image" && (next.ui_operation || {}).state !== "running") {
                if((next.ui_operation || {}).state === "done" && next.draft_media && (root.awaitingImage || previousMediaId!==next.draft_media.id))root.draftImage=next.draft_media
                root.awaitingImage=false
            }
            if(root.awaitingList && !root.operationBusy) {
                root.awaitingList=false
                if(!root.formError && root.operation.state === "done" && root.operation.name === "market_list") root.finishList()
            }
        } catch(e) { root.formError="MARKETPLACE_INVALID_RESPONSE" }
    }

    function setFilter(name) {
        if (!root.surfaceHost || !root.surfaceHost.marketplaceSetFilter)
            return
        root.applyRaw(root.surfaceHost.marketplaceSetFilter(name))
    }

    function focusCatalog(listingId) {
        if(root.operationBusy)return
        root.catalogFocusId=listingId
        root.requestedReceiptId=""
        if (!root.operationBusy && root.surfaceHost && root.surfaceHost.marketplaceSelect)
            root.applyRaw(root.surfaceHost.marketplaceSelect(listingId))
    }
    function applyFacet(field,value,kind){if(operationBusy)return;if(field==="all"){facetKindFilter="";categoryFilter="";materialFilter="";facetCollectionFilter="";facetOriginFilter="";facetMakerFilter=""}else if(field==="category"){facetKindFilter=kind;categoryFilter=value}else if(field==="material")materialFilter=value;else if(field==="collection_name")facetCollectionFilter=value;else if(field==="origin")facetOriginFilter=value;else if(field==="maker")facetMakerFilter=value}
    function clearCatalogFilters(){collectionFilter="";networkFilter="";currencyFilter="";kindFilter="";applyFacet("all","","");saleFilter="";imagesOnly=false;sortChoice="recent";if(activeFilter!=="ALL")setFilter("ALL")}
    readonly property int filterCount:(collectionFilter?1:0)+(networkFilter?1:0)+(currencyFilter?1:0)+(kindFilter?1:0)+(categoryFilter?1:0)+(materialFilter?1:0)+(facetKindFilter?1:0)+(facetCollectionFilter?1:0)+(facetOriginFilter?1:0)+(facetMakerFilter?1:0)+(saleFilter?1:0)+(imagesOnly?1:0)+(activeFilter!=="ALL"?1:0)
    function selectRow(listingId) {
        if (root.operationBusy || !root.surfaceHost || !root.surfaceHost.marketplaceSelect)
            return
        root.requestedReceiptId=listingId
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
        if (root.operationBusy || !root.surfaceHost || !root.surfaceHost.marketplaceList)
            return
        root.applyRaw(
            root.surfaceHost.marketplaceList(
                JSON.stringify({
                    "title": titleField.text,
                    "kind": root.draftKind,
                    "category": root.draftCategory,
                    "material": root.draftMaterial,
                    "mint": root.legacyMintOpen ? mintField.text : "",
                    "price_sol": priceField.text,
                    "price": priceField.text,
                    "settlement_asset_id": root.settlementAssetId,
                    "image_id": root.draftImage.id || "",
                    "collection_name": collectionField.text,
                    "nft_binding": root.linkNft && nftChainChoice.currentIndex>=0 ? {chain_id:nftChainChoice.model[nftChainChoice.currentIndex].id,standard:nftStandardChoice.currentText,collection:nftCollectionField.text.trim(),token_id:nftTokenField.text.trim()} : null,
                    "description": descField.text,
                    "maker": makerField.text,
                    "origin": originField.text,
                    "mass_g": massField.text,
                    "composition": root.draftParts,
                    "previous_lives": root.draftLives
                })
            )
        )
        if(root.operationBusy) root.awaitingList=true
        else if (!root.formError) root.finishList()
    }

    function finishList() {
            root.requestedReceiptId=(root.status.selected || {}).id || ""
            root.linkNft=false;nftCollectionField.text="";nftTokenField.text=""
            root.draftImage=({});collectionField.text=""
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
            return RuntimeTheme.GGTheme.positive
        if (s === "SOLD")
            return RuntimeTheme.GGTheme.accent
        if (s === "DELISTED")
            return RuntimeTheme.GGTheme.negative
        return RuntimeTheme.GGTheme.muted
    }

    Timer {
        interval: root.operationBusy || root.stopPreviewsPending || ((root.status.public_catalog || {}).preview_job || {}).worker_active || !root.status.listings ? 250 : 4000
        running: root.visible || root.stopPreviewsPending
        repeat: true
        onTriggered: {root.refresh();root.flushPreviewStop()}
    }

    onVisibleChanged: {
        if (visible)
            root.refresh()
    }
    FileDialog {
        id:imageDialog;title:"Välj bild som beskriver varan eller tjänsten";fileMode:FileDialog.OpenFile;nameFilters:["Bilder (*.png *.jpg *.jpeg *.webp)"]
        onAccepted:root.importImage(selectedFile)
    }

    CryptoSpaceFrame { property string uiColorScope: "ui.widget.MarketplaceSurface.CryptoSpaceFrame.1";
        id:spaceFrame;objectName:"marketplacePrimarySpace";anchors.fill:parent;visible:!root.embedded;section:"MARKETPLACE";title:"Marketplace"
        surfaceHost:root.surfaceHost;operation:root.operation
        events:(root.status.public_catalog || {}).events || []
        context:root.workspaceNetworkLabel
        onNavigate:function(section){if(section==="MARKETPLACE")root.page="CATALOG";else root.cryptoRequested(section)}
    }
    Item {
        parent:root.embedded ? root : spaceFrame.contentItem
        anchors.fill: parent
        anchors.leftMargin: 10
        anchors.rightMargin: 10
        anchors.topMargin: 0
        anchors.bottomMargin: 0

        Item {
            id: topBar
            width: parent.width
            height: (root.page==="CATALOG" ? 0 : navFlow.height+4) + (marketError.visible ? marketError.implicitHeight+4 : 0)

            Flow {
                id: navFlow
                visible:root.page!=="CATALOG"
                width: parent.width
                spacing: 4
                GGText { colorKey: "ui.MarketplaceSurface.1";visible:false;text:"MARKETPLACE";width:root.width<500 ? parent.width : 175;height:30;verticalAlignment:Text.AlignVCenter;color:RuntimeTheme.GGTheme.bright;font.family:"monospace";font.pixelSize:15;font.letterSpacing:1.4}
                CryptoButton { property string uiColorScope: "ui.control.MarketplaceSurface.1";objectName:"marketBrowseButton";text:root.page==="RECEIPT" ? "← Utforska" : "Utforska";checked:root.page==="CATALOG";onClicked:root.page="CATALOG"}
                CryptoButton { property string uiColorScope: "ui.control.MarketplaceSurface.2";objectName:"marketRegisterButton";text:"+ Registrera";checked:root.page==="REGISTER";onClicked:root.page="REGISTER"}
                CryptoButton { property string uiColorScope: "ui.control.MarketplaceSurface.3";id:toolsButton;objectName:"marketToolsSubpageButton";text:"Verktyg ⌄";quiet:true;onClicked:marketTools.open()}
                Popup {
                    id:marketTools;parent:root;objectName:"marketToolsMenu";x:Math.max(0,root.width-width-10);y:54;width:Math.min(300,root.width-24);padding:12;focus:true;closePolicy:Popup.CloseOnEscape | Popup.CloseOnPressOutside
                    background:Rectangle {color:RuntimeTheme.GGTheme.panel;border.color:RuntimeTheme.GGTheme.edge;radius:4}
                    contentItem:Column {spacing:5
                        GGText { colorKey: "ui.MarketplaceSurface.2";text:"VERKTYG & DOKUMENTATION";color:RuntimeTheme.GGTheme.muted;font.family:"monospace";font.pixelSize:10}
                        Repeater {model:[{id:"RECEIPT",name:"Valt objekt / kvitto"},{id:"ELEMENTS",name:"Materialbibliotek"},{id:"LIVES",name:"Tidigare liv & återbruk"},{id:"ACTIVITY",name:"Aktivitetslogg"},{id:"OMNI",name:"Wallet & nätverk"},{id:"NFT",name:"Inspektera NFT"}]
                            CryptoButton { property string uiColorScope: "ui.control.MarketplaceSurface.4";required property var modelData;width:parent.width;text:modelData.name;flat:true;horizontalAlignment:Text.AlignLeft;checked:root.page===modelData.id;onClicked:{root.page=modelData.id;marketTools.close()}}
                        }
                    }
                }
            }

            Flow {
                id: marketSummary
                visible:false
                anchors.top: navFlow.bottom
                anchors.topMargin: 6
                width: parent.width
                spacing: 12
                BusyIndicator { width:18; height:18; running:root.operationBusy; visible:running }
                GGText { colorKey: "ui.MarketplaceSurface.3";
                    text: "PAPER / LOKALT"
                    color: RuntimeTheme.GGTheme.accent
                    font.family: "monospace"
                    font.pixelSize: 12
                    font.bold: true
                }
                GGText { colorKey: "ui.MarketplaceSurface.4";
                    text: Number(root.wallet.account_count || 0)>0 ? Number(root.wallet.account_count)+" konton"
                        : root.connected
                        ? String(root.wallet.short || "")
                        : "Inget bevakningskonto"
                    color: root.connected ? RuntimeTheme.GGTheme.text : RuntimeTheme.GGTheme.accent
                    font.family: "monospace"
                    font.pixelSize: 12
                }
                GGText { colorKey: "ui.MarketplaceSurface.5";text:({CATALOG:"Objekt, innehåll och ursprung",REGISTER:"Registrera vara eller tjänst",RECEIPT:"Objektpass",ELEMENTS:"Materialbibliotek",LIVES:"Tidigare liv",ACTIVITY:"Aktivitet",OMNI:"Wallet & nätverk",NFT:"NFT-inspektör"})[root.page] || "Objektpass";color:RuntimeTheme.GGTheme.muted;font.family:"monospace";font.pixelSize:11}

            }
            GGText { colorKey: "ui.MarketplaceSurface.6";
                id:marketError
                anchors.top:root.page==="CATALOG" ? parent.top : navFlow.bottom
                width:parent.width
                visible:root.formError.length>0
                text:root.formError;color:RuntimeTheme.GGTheme.negative;font.family:"monospace";font.pixelSize:11;wrapMode:Text.WordWrap
            }
        }

        Item {
            id: field
            anchors.top: topBar.bottom
            anchors.topMargin: 4
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom

            OmniSurface { property string uiColorScope: "ui.widget.MarketplaceSurface.OmniSurface.6";
                embedded:true
                anchors.fill: parent
                visible: root.page === "OMNI"
                surfaceHost: root.surfaceHost
            }
            OmniSurface { property string uiColorScope: "ui.widget.MarketplaceSurface.OmniSurface.7";
                id:nftInspector
                embedded:true
                objectName:"marketNftInspector"
                anchors.fill: parent
                visible: root.page === "NFT"
                page: "NFT"
                surfaceHost: root.surfaceHost
            }

            Column {
                id: catalogHead
                width: parent.width
                spacing: 0
                visible: root.page === "CATALOG"

                Flow {objectName:"marketSearchSourceRow";width:parent.width;spacing:6
                    GgField { property string uiColorScope: "ui.widget.MarketplaceSurface.GgField.8";id:searchField;objectName:"marketCatalogSearch";width:parent.width<760 ? parent.width : parent.width-404;height:34;font.pixelSize:12;leftPadding:28;placeholderText:root.showPublic ? "Sök samling, nätverk eller kontrakt…" : "Sök föremål, tjänst, material…";onTextChanged:root.searchQuery=text
                        GGText { colorKey: "ui.MarketplaceSurface.7";x:10;anchors.verticalCenter:parent.verticalCenter;text:"⌕";color:RuntimeTheme.GGTheme.muted;font.family:"monospace";font.pixelSize:21}
                    }
                    Row {objectName:"marketSourceSegment";width:228;height:34;spacing:0
                        GGText { colorKey: "ui.MarketplaceSurface.8";width:42;height:34;text:"Källa:";verticalAlignment:Text.AlignVCenter;color:RuntimeTheme.GGTheme.muted;font.family:"monospace";font.pixelSize:10}
                        CryptoButton { property string uiColorScope: "ui.control.MarketplaceSurface.5";id:localSourceButton;objectName:"marketLocalSource";width:64;height:34;font.pixelSize:11;text:"Lokalt";checked:!root.showPublic;color:!root.showPublic ? RuntimeTheme.GGTheme.accent : RuntimeTheme.GGTheme.text;enabled:!root.operationBusy;onClicked:root.catalogScope="LOCAL"
                            background:Rectangle {color:RuntimeTheme.GGTheme.base;border.width:1;border.color:!root.showPublic ? RuntimeTheme.GGTheme.accent : RuntimeTheme.GGTheme.line}
                        }
                        CryptoButton { property string uiColorScope: "ui.control.MarketplaceSurface.6";id:publicSourceButton;objectName:"marketPublicSource";width:122;height:34;font.pixelSize:11;text:"Publika samlingar";checked:root.showPublic;color:root.showPublic ? RuntimeTheme.GGTheme.accent : RuntimeTheme.GGTheme.text;enabled:!root.operationBusy;onClicked:{root.catalogScope="PUBLIC";Qt.callLater(root.maybeDiscover)}
                            background:Rectangle {color:RuntimeTheme.GGTheme.base;border.width:1;border.color:root.showPublic ? RuntimeTheme.GGTheme.accent : RuntimeTheme.GGTheme.line}
                        }
                    }
                    CryptoButton { property string uiColorScope: "ui.control.MarketplaceSurface.7";objectName:"marketCatalogRegister";width:96;height:34;font.pixelSize:11;text:"Registrera  +";tip:"Registrera objekt eller tjänst";enabled:!root.operationBusy;onClicked:root.page="REGISTER"}
                    CryptoButton { property string uiColorScope: "ui.control.MarketplaceSurface.8";objectName:"marketFiltersButton";width:28;implicitWidth:28;height:34;text:"☷";tip:root.showPublic ? "Filtrera samlingar efter nätverk" : "Filter"+(root.filterCount ? " · "+root.filterCount : "");quiet:true;checked:!root.showPublic && root.catalogFiltersOpen;onClicked:{if(root.showPublic)publicCatalog.openCategories();else root.catalogFiltersOpen=!root.catalogFiltersOpen}}
                    CryptoButton { property string uiColorScope: "ui.control.MarketplaceSurface.9";objectName:"marketToolsButton";width:28;implicitWidth:28;height:34;text:"⋯";tip:"Material, tidigare liv och andra verktyg";onClicked:marketTools.open()}
                }
                Flow {
                    width:parent.width;spacing:6;visible:!root.showPublic && root.catalogFiltersOpen
                    CryptoPick { property string uiColorScope: "ui.control.MarketplaceSurface.10";width:Math.min(210,parent.width);model:[{id:"",name:"Alla samlingar"}].concat((root.status.collections || []).map(function(name){return {id:name,name:name}}));textRole:"name";Accessible.name:"Samling";currentIndex:root.choiceIndex(model,root.collectionFilter);onActivated:root.collectionFilter=model[currentIndex].id}
                    CryptoPick { property string uiColorScope: "ui.control.MarketplaceSurface.11";width:160;model:[{id:"",name:"Alla typer"},{id:"OBJECT",name:"Varor / objekt"},{id:"SERVICE",name:"Tjänster"},{id:"ELEMENT",name:"Grundämnen"},{id:"SUBSTANCE",name:"Ämnen"}];textRole:"name";Accessible.name:"Objekttyp";currentIndex:root.choiceIndex(model,root.kindFilter);onActivated:root.kindFilter=model[currentIndex].id}
                    CryptoPick { property string uiColorScope: "ui.control.MarketplaceSurface.12";width:Math.min(220,parent.width);model:[{id:"",name:"Alla ursprungsnätverk"}].concat((root.status.settlement_networks || []).map(function(n){return {id:n.id,name:n.name}})).concat([{id:"mainnet",name:"Solana · äldre mainnetkvitton"},{id:"testnet",name:"Solana · äldre labbkvitton"}]);textRole:"name";Accessible.name:"MP ursprungsnätverk";currentIndex:root.choiceIndex(model,root.networkFilter);onActivated:root.networkFilter=model[currentIndex].id}
                    CryptoPick { property string uiColorScope: "ui.control.MarketplaceSurface.13";width:160;model:[{id:"",name:"Alla status"},{id:"LISTED",name:"Till salu"},{id:"SOLD",name:"Dokumenterade köp"},{id:"DELISTED",name:"Avpublicerade"}];textRole:"name";Accessible.name:"Försäljningsstatus";currentIndex:root.choiceIndex(model,root.saleFilter);onActivated:root.saleFilter=model[currentIndex].id}
                    CryptoPick { property string uiColorScope: "ui.control.MarketplaceSurface.14";width:Math.min(220,parent.width);model:[{id:"",name:"Alla prisvalutor"}].concat(root.settlementAssets.map(function(a){return {id:a.id,name:a.symbol+" · "+a.chain_id}}));textRole:"name";Accessible.name:"Prisets valuta och nätverk";currentIndex:root.choiceIndex(model,root.currencyFilter);onActivated:{root.currencyFilter=model[currentIndex].id;if(!root.currencyFilter && root.sortChoice==="price")root.sortChoice="recent"}}
                    CryptoPick { property string uiColorScope: "ui.control.MarketplaceSurface.15";width:170;model:[{id:"recent",name:"Senast registrerat"},{id:"name",name:"Namn"}].concat(root.currencyFilter ? [{id:"price",name:"Lägst begärt pris"}] : []);textRole:"name";Accessible.name:"Katalogsortering";currentIndex:root.choiceIndex(model,root.sortChoice);onActivated:root.sortChoice=model[currentIndex].id}
                    CryptoPick { property string uiColorScope: "ui.control.MarketplaceSurface.16";width:170;model:root.filters;Accessible.name:"Materialkategori";currentIndex:Math.max(0,root.filters.indexOf(root.activeFilter));onActivated:root.setFilter(currentText)}
                    CryptoToggle { property string uiColorScope: "ui.control.MarketplaceSurface.17";text:"Med bild";checked:root.imagesOnly;onClicked:root.imagesOnly=checked}
                    CryptoButton { property string uiColorScope: "ui.control.MarketplaceSurface.18";visible:root.filterCount>0;text:"Rensa filter";quiet:true;onClicked:root.clearCatalogFilters()}
                }

            }

            MarketplaceDiscovery { property string uiColorScope: "ui.widget.MarketplaceSurface.MarketplaceDiscovery.23";
                id:publicCatalog
                anchors.fill:parent;anchors.topMargin:catalogHead.height+6;visible:root.page==="CATALOG" && root.showPublic
                state:root.status.public_catalog || ({});busy:root.operationBusy;query:root.searchQuery
                onRefreshRequested:function(provider,page){root.discover({action:"refresh",provider:provider,page:page})}
                onPreviewsRequested:function(ids){root.discover({action:"previews",ids:ids})}
                onStopPreviewsRequested:root.requestPreviewStop()
                onSelectRequested:function(id){root.discover({action:"select",id:id})}
                onInspectRequested:function(binding){root.page="NFT";nftInspector.inspectBinding(binding)}
                onCopyRequested:function(ref){if(root.surfaceHost && root.surfaceHost.tmogCopy)root.surfaceHost.tmogCopy(ref)}
            }
            MarketplaceBrowser { property string uiColorScope: "ui.widget.MarketplaceSurface.MarketplaceBrowser.24";
                anchors.fill:parent;anchors.topMargin:catalogHead.height+10
                visible:root.page==="CATALOG" && !root.showPublic
                rows:root.listings;sourceRows:root.browseRows;fullRows:root.status.listings || [];events:root.ledger;receipt:root.selected || ({});focusedId:root.catalogFocusId;busy:root.operationBusy;mode:root.catalogMode
                category:root.categoryFilter;material:root.materialFilter;kind:root.facetKindFilter;collection:root.facetCollectionFilter;origin:root.facetOriginFilter;maker:root.facetMakerFilter;sort:root.sortChoice;priceSortAvailable:!!root.currencyFilter
                onFacetRequested:function(field,value,kind){root.applyFacet(field,value,kind)}
                onSortRequested:function(sort){root.sortChoice=sort}
                onModeRequested:function(mode){root.catalogMode=mode}
                onObjectFocused:function(id){root.focusCatalog(id)}
                onObjectOpened:function(id){root.selectRow(id)}
                onNftRequested:function(binding){root.page="NFT";nftInspector.inspectBinding(binding)}
                onRegisterRequested:root.page="REGISTER"
            }

            Flickable {
                anchors.fill: parent
                visible: root.page === "REGISTER" || root.page === "LIST"
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                contentHeight: listCol.height
                ScrollBar.vertical: GgScrollBar { property string uiColorScope: "ui.widget.MarketplaceSurface.GgScrollBar.25";}

                Column {
                    id: listCol
                    width: parent.width
                    spacing: 8

                    GGText { colorKey: "ui.MarketplaceSurface.9";
                        width: parent.width
                        text: "Blocket-enkelt: namnge föremålet, välj om det är grundämne, ämne eller sak. Kvittot mintas som paper-NFT. Sammansättning och tidigare liv kan fyllas i senare när fler producenter är med."
                        color: RuntimeTheme.GGTheme.muted
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }

                    GGText { colorKey: "ui.MarketplaceSurface.10";
                        text: "KIND"
                        color: RuntimeTheme.GGTheme.muted
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                    Flow {
                        width: parent.width
                        spacing: 10
                        Repeater {
                            model: root.kinds
                            GGText { colorKey: "ui.MarketplaceSurface.11";
                                required property string modelData
                                text: modelData
                                color: root.draftKind === modelData ? RuntimeTheme.GGTheme.text : RuntimeTheme.GGTheme.dim
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
                                        else if (modelData === "SERVICE")
                                            root.draftCategory = "SERVICE"
                                    }
                                }
                            }
                        }
                    }

                    GGText { colorKey: "ui.MarketplaceSurface.12";
                        text: "TITLE"
                        color: RuntimeTheme.GGTheme.muted
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                    GgField { property string uiColorScope: "ui.widget.MarketplaceSurface.GgField.26";
                        id: titleField
                        objectName: "marketTitleField"
                        width: Math.min(listCol.width, 520)
                        placeholderText: "cykel, guldörhänge, stålämne, Fe…"
                    }
                    GgField { property string uiColorScope: "ui.widget.MarketplaceSurface.GgField.27"; id:collectionField;width:Math.min(listCol.width,520);placeholderText:"Samling / produktserie (valfritt)" }
                    Flow { width:parent.width;spacing:8
                        CryptoButton { property string uiColorScope: "ui.control.MarketplaceSurface.19"; text:"Lägg till bild";enabled:!root.operationBusy;onClicked:imageDialog.open() }
                        CryptoButton { property string uiColorScope: "ui.control.MarketplaceSurface.20"; text:"Ta bort bild från utkast";enabled:!!root.draftImage.id && !root.operationBusy;quiet:true;onClicked:root.draftImage=({}) }
                    }
                    Image { width:Math.min(parent.width,260);height:root.draftImage.url ? 140 : 0;source:root.draftImage.url || "";fillMode:Image.PreserveAspectFit;asynchronous:true }

                    GGText { colorKey: "ui.MarketplaceSurface.13";
                        text: "CATEGORY"
                        color: RuntimeTheme.GGTheme.muted
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                    Flow {
                        width: parent.width
                        spacing: 10
                        Repeater {
                            model: root.categories.length
                            GGText { colorKey: "ui.MarketplaceSurface.14";
                                required property int index
                                text: String((root.categories[index] || {}).id || "")
                                color: root.draftCategory
                                       === String((root.categories[index] || {}).id || "")
                                    ? RuntimeTheme.GGTheme.text : RuntimeTheme.GGTheme.dim
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

                    GGText { colorKey: "ui.MarketplaceSurface.15";
                        text: root.draftKind === "ELEMENT" ? "ELEMENT" : "MATERIAL"
                        color: RuntimeTheme.GGTheme.muted
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                    Flow {
                        width: parent.width
                        spacing: 10
                        Repeater {
                            model: root.draftKind === "ELEMENT" ? ["Fe", "Cu", "Au", "Ag", "C", "Al", "Si", "O", "H", "Pb", "Sn", "Zn", "Ti", "Ni", "Cr"] : root.materials
                            GGText { colorKey: "ui.MarketplaceSurface.16";
                                required property string modelData
                                text: modelData
                                color: root.draftMaterial === modelData ? RuntimeTheme.GGTheme.text : RuntimeTheme.GGTheme.dim
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

                    CryptoPick { property string uiColorScope: "ui.control.MarketplaceSurface.21";
                        width: Math.min(listCol.width, 520)
                        model: root.settlementAssets
                        textRole: "id"
                        displayText: root.settlementAssetId || "SOL · befintligt paper-format"
                        Accessible.name: "Tillgång och nätverk för priset"
                        onActivated: root.settlementAssetId = root.settlementAssets[currentIndex].id
                    }
                    GGText { colorKey: "ui.MarketplaceSurface.17";
                        width: parent.width; wrapMode: Text.WordWrap
                        text: "Vald valuta används i det lokala kvittot. Köp är paper: inga token skickas och inget saldo debiteras."
                        color: RuntimeTheme.GGTheme.muted; font.family: "monospace"; font.pixelSize: 11
                    }
                    Row {
                        spacing: 12
                        Column {
                            spacing: 4
                            GGText { colorKey: "ui.MarketplaceSurface.18";
                                text: "MASS g"
                                color: RuntimeTheme.GGTheme.muted
                                font.family: "monospace"
                                font.pixelSize: 12
                            }
                            GgField { property string uiColorScope: "ui.widget.MarketplaceSurface.GgField.31";
                                id: massField
                                width: 120
                                text: "0"
                            }
                        }
                        Column {
                            spacing: 4
                            GGText { colorKey: "ui.MarketplaceSurface.19";
                                text: root.settlementAssetId ? "PRICE · vald tillgång" : "PRICE SOL"
                                color: RuntimeTheme.GGTheme.muted
                                font.family: "monospace"
                                font.pixelSize: 12
                            }
                            GgField { property string uiColorScope: "ui.widget.MarketplaceSurface.GgField.32";
                                id: priceField
                                objectName: "marketPriceField"
                                width: 120
                                text: "0"
                            }
                        }
                    }

                    GGText { colorKey: "ui.MarketplaceSurface.20";
                        text: "MAKER"
                        color: RuntimeTheme.GGTheme.muted
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                    GgField { property string uiColorScope: "ui.widget.MarketplaceSurface.GgField.33";
                        id: makerField
                        objectName:"marketMakerField"
                        width: Math.min(listCol.width, 520)
                        placeholderText: "who made it"
                    }

                    GGText { colorKey: "ui.MarketplaceSurface.21";
                        text: "ORIGIN"
                        color: RuntimeTheme.GGTheme.muted
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                    GgField { property string uiColorScope: "ui.widget.MarketplaceSurface.GgField.34";
                        id: originField
                        objectName:"marketOriginField"
                        width: Math.min(listCol.width, 520)
                        placeholderText: "mine, mill, workshop, previous owner"
                    }

                    GGText { colorKey: "ui.MarketplaceSurface.22";
                        text: "DESCRIPTION"
                        color: RuntimeTheme.GGTheme.muted
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                    GgField { property string uiColorScope: "ui.widget.MarketplaceSurface.GgField.35";
                        id: descField
                        width: Math.min(listCol.width, 520)
                        placeholderText: "what it is, what it is made of, where it came from"
                    }

                    CryptoToggle { property string uiColorScope: "ui.control.MarketplaceSurface.22";text:"Länka ett befintligt NFT (valfritt)";checked:root.linkNft;onClicked:root.linkNft=checked}
                    Column {width:parent.width;spacing:6;visible:root.linkNft
                        CryptoPick { property string uiColorScope: "ui.control.MarketplaceSurface.23";id:nftStandardChoice;width:Math.min(parent.width,320);model:["erc721","erc1155","krc721"];Accessible.name:"Länkat NFT-protokoll"}
                        CryptoPick { property string uiColorScope: "ui.control.MarketplaceSurface.24";id:nftChainChoice;objectName:"marketNftSourceChain";width:Math.min(parent.width,420);model:(root.status.settlement_networks || []).filter(function(n){return nftStandardChoice.currentText==="krc721" ? n.family==="kaspa" : n.family==="evm"});textRole:"name";Accessible.name:"Länkad NFT:s ursprungsnätverk"}
                        GgField { property string uiColorScope: "ui.widget.MarketplaceSurface.GgField.39";id:nftCollectionField;objectName:"marketNftCollection";width:Math.min(parent.width,520);placeholderText:"NFT-kontrakt eller samlingsticker";Accessible.name:placeholderText}
                        GgField { property string uiColorScope: "ui.widget.MarketplaceSurface.GgField.40";id:nftTokenField;objectName:"marketNftTokenId";width:Math.min(parent.width,320);placeholderText:"Token-ID · heltal som text";Accessible.name:placeholderText}
                        GGText { colorKey: "ui.MarketplaceSurface.23";width:parent.width;text:"Referensen kopplas till objektpasset. Ägande måste kontrolleras separat; inget NFT överförs vid registrering.";font.family:"monospace";font.pixelSize:11;color:RuntimeTheme.GGTheme.muted;wrapMode:Text.WordWrap}
                    }
                    CryptoToggle { property string uiColorScope: "ui.control.MarketplaceSurface.25";text:"Äldre Solanamint-format";checked:root.legacyMintOpen;onClicked:root.legacyMintOpen=checked}
                    GGText { colorKey: "ui.MarketplaceSurface.24";
                        visible:root.legacyMintOpen
                        text: "Solanamint (valfritt i äldre kvittoformat)"
                        color: RuntimeTheme.GGTheme.muted
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                    GgField { property string uiColorScope: "ui.widget.MarketplaceSurface.GgField.42";
                        id: mintField
                        visible:root.legacyMintOpen
                        width: Math.min(listCol.width, 520)
                        placeholderText: "base58 mint or leave blank"
                    }

                    GGText { colorKey: "ui.MarketplaceSurface.25";
                        width: parent.width
                        text: "COMPOSITION  " + String(root.draftParts.length) + " parts · click an ELEMENT receipt in CATALOG then here, or register elements first"
                        color: RuntimeTheme.GGTheme.muted
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                    GGText { colorKey: "ui.MarketplaceSurface.26";
                        visible: root.draftParts.length > 0
                        width: parent.width
                        text: {
                            var i
                            var bits = []
                            for (i = 0; i < root.draftParts.length; i++)
                                bits.push(String(root.draftParts[i].symbol || root.draftParts[i].title || ""))
                            return bits.join(" · ")
                        }
                        color: RuntimeTheme.GGTheme.positive
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }

                    GGText { colorKey: "ui.MarketplaceSurface.27";
                        visible: root.formError.length > 0
                        width: parent.width
                        text: root.formError
                        color: RuntimeTheme.GGTheme.negative
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }

                    GgButton { property string uiColorScope: "ui.control.MarketplaceSurface.26";
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
                ScrollBar.vertical: GgScrollBar { property string uiColorScope: "ui.widget.MarketplaceSurface.GgScrollBar.44";}

                Column {
                    id: proofCol
                    width: parent.width
                    spacing: 6
                    MarketplacePassport { property string uiColorScope: "ui.widget.MarketplaceSurface.MarketplacePassport.45";
                        id: passport
                        visible:root.selected!==null
                        receipt:root.selected || ({})
                        width:parent.width
                        onObjectRequested:function(id){root.selectRow(id)}
                        onNftRequested:function(binding){root.page="NFT";nftInspector.inspectBinding(binding)}
                    }

                    GGText { colorKey: "ui.MarketplaceSurface.28";
                        visible: root.selected === null
                        width: parent.width
                        text: root.operationBusy ? "Öppnar valt objekt…" : root.requestedReceiptId ? "Det valda objektet kunde inte öppnas." : "Välj ett objekt i Utforska för att öppna dess pass."
                        color: RuntimeTheme.GGTheme.muted
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }

                    Column {
                        width:parent.width
                        visible:passport.technical
                        spacing:6
                    GGText { colorKey: "ui.MarketplaceSurface.29";
                        visible: root.selected !== null
                        text: String((root.selected || {}).title || "")
                        color: RuntimeTheme.GGTheme.bright
                        font.family: "monospace"
                        font.pixelSize: 18
                        font.bold: true
                    }
                    GGText { colorKey: "ui.MarketplaceSurface.30";
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
                            + String((root.selected || {}).price_label || "0 SOL")
                        color: RuntimeTheme.GGTheme.text
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                    GGText { colorKey: "ui.MarketplaceSurface.31";
                        visible: root.selected !== null
                        width: parent.width
                        text: String((root.selected || {}).description || "")
                        color: RuntimeTheme.GGTheme.muted
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                    GGText { colorKey: "ui.MarketplaceSurface.32";
                        visible: root.selected !== null
                        width: parent.width
                        text: "receipt   " + String((root.selected || {}).receipt || "")
                        color: RuntimeTheme.GGTheme.accent
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WrapAnywhere
                    }
                    GGText { colorKey: "ui.MarketplaceSurface.33";
                        visible: root.selected !== null && passport.technical
                        width: parent.width
                        text: "identity  " + String((root.proof || {}).identity_sha256 || "")
                        color: RuntimeTheme.GGTheme.muted
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WrapAnywhere
                    }
                    GGText { colorKey: "ui.MarketplaceSurface.34";
                        visible: root.selected !== null && passport.technical
                        width: parent.width
                        text: "state     " + String((root.proof || {}).state_sha256 || "")
                        color: RuntimeTheme.GGTheme.muted
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WrapAnywhere
                    }
                    GGText { colorKey: "ui.MarketplaceSurface.35";
                        visible: root.selected !== null && passport.technical
                        width: parent.width
                        text: "catalog   " + String((root.proof || {}).catalog_root || "")
                        color: RuntimeTheme.GGTheme.muted
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WrapAnywhere
                    }
                    GGText { colorKey: "ui.MarketplaceSurface.36";
                        visible: root.selected !== null
                        width: parent.width
                        text: "maker     "
                            + (String((root.selected || {}).maker || "") || "—")
                            + "   origin "
                            + (String((root.selected || {}).origin || "") || "—")
                        color: RuntimeTheme.GGTheme.text
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                    GGText { colorKey: "ui.MarketplaceSurface.37";
                        visible: root.selected !== null
                        width: parent.width
                        text: "owner     "
                            + (String((root.selected || {}).owner || "") || "unowned")
                        color: RuntimeTheme.GGTheme.text
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WrapAnywhere
                    }

                    GGText { colorKey: "ui.MarketplaceSurface.38";
                        visible: root.selectedParts.length > 0
                        text: "COMPOSITION"
                        color: RuntimeTheme.GGTheme.text
                        font.family: "monospace"
                        font.pixelSize: 12
                        font.bold: true
                    }
                    Repeater {
                        model: root.selectedParts
                        delegate: GGText { colorKey: "ui.MarketplaceSurface.39";
                            required property var modelData
                            width: proofCol.width
                            text: String(modelData.symbol || "")
                                + "  "
                                + String(modelData.title || "")
                                + "  "
                                + String(modelData.mass_g || 0)
                                + " g  "
                                + String(modelData.id || "")
                            color: RuntimeTheme.GGTheme.positive
                            font.family: "monospace"
                            font.pixelSize: 12
                            wrapMode: Text.WordWrap
                        }
                    }

                    GGText { colorKey: "ui.MarketplaceSurface.40";
                        visible: root.selectedLife.length > 0
                        text: "LIFECYCLE"
                        color: RuntimeTheme.GGTheme.text
                        font.family: "monospace"
                        font.pixelSize: 12
                        font.bold: true
                    }
                    Repeater {
                        model: root.selectedLife
                        delegate: GGText { colorKey: "ui.MarketplaceSurface.41";
                            required property var modelData
                            text: String(modelData.kind || "")
                                + "  "
                                + String(modelData.ts || "")
                            color: RuntimeTheme.GGTheme.accent
                            font.family: "monospace"
                            font.pixelSize: 12
                        }
                    }

                    }
                    Flow {
                        width:parent.width
                        visible: root.selected !== null
                            && String((root.selected || {}).status || "") === "LISTED"
                        spacing: 10
                        GgButton { property string uiColorScope: "ui.control.MarketplaceSurface.27";
                            text: "Dokumentera paperköp"
                            onClicked: root.buySelected()
                        }
                        GgButton { property string uiColorScope: "ui.control.MarketplaceSurface.28";
                            text: "Avpublicera"
                            onClicked: root.delistSelected()
                        }
                        GgButton { property string uiColorScope: "ui.control.MarketplaceSurface.29";
                            text: "Använd som tidigare liv"
                            onClicked: root.toggleLife(String((root.selected || {}).id || ""))
                        }
                    }

                    GGText { colorKey: "ui.MarketplaceSurface.42";
                        visible: root.formError.length > 0 && (root.page === "RECEIPT" || root.page === "PROVENANCE")
                        width: parent.width
                        text: root.formError
                        color: RuntimeTheme.GGTheme.negative
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
                ScrollBar.vertical: GgScrollBar { property string uiColorScope: "ui.widget.MarketplaceSurface.GgScrollBar.49";}

                Column {
                    id: elCol
                    width: parent.width
                    spacing: 8

                    GGText { colorKey: "ui.MarketplaceSurface.43";
                        width: parent.width
                        text: "Grundämnen är egna kvitton. Ett föremål är en sammansättning. Klicka för att minta paper-NFT för ämnet."
                        color: RuntimeTheme.GGTheme.muted
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }

                    Flow {
                        width: parent.width
                        spacing: 8
                        Repeater {
                            model: root.elements.length
                            delegate: TmogCard { property string uiColorScope: "ui.widget.MarketplaceSurface.TmogCard.50";
                                required property int index
                                width: 92
                                height: 56
                                leftLegend: String((root.elements[index] || {}).symbol || "")
                                rightLegend: (root.elements[index] || {}).listed ? "ON" : ""
                                borderColor: (root.elements[index] || {}).listed ? RuntimeTheme.GGTheme.positive : RuntimeTheme.GGTheme.line
                                GGText { colorKey: "ui.MarketplaceSurface.44";
                                    anchors.centerIn: parent
                                    text: String((root.elements[index] || {}).name || "")
                                    color: RuntimeTheme.GGTheme.text
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
                ScrollBar.vertical: GgScrollBar { property string uiColorScope: "ui.widget.MarketplaceSurface.GgScrollBar.51";}

                Column {
                    id: lifeCol
                    width: parent.width
                    spacing: 8

                    GGText { colorKey: "ui.MarketplaceSurface.45";
                        width: parent.width
                        text: "Tidigare liv. Markera kvitton (hold i CATALOG eller USE AS PREVIOUS LIFE) och minta ett nytt föremål som bär deras material."
                        color: RuntimeTheme.GGTheme.muted
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }

                    GGText { colorKey: "ui.MarketplaceSurface.46";
                        text: "SELECTED OBJECT LIVES  "
                            + String(root.lives.length)
                        color: RuntimeTheme.GGTheme.text
                        font.family: "monospace"
                        font.pixelSize: 12
                        font.bold: true
                    }
                    Repeater {
                        model: root.lives
                        delegate: GGText { colorKey: "ui.MarketplaceSurface.47";
                            required property var modelData
                            width: lifeCol.width
                            text: String(modelData.title || "")
                                + "  "
                                + String(modelData.material || "")
                                + "  "
                                + String(modelData.status || "")
                                + "  "
                                + String(modelData.id || "")
                            color: RuntimeTheme.GGTheme.positive
                            font.family: "monospace"
                            font.pixelSize: 12
                            wrapMode: Text.WordWrap
                            MouseArea {
                                anchors.fill: parent
                                onClicked: root.selectRow(String(modelData.id || ""))
                            }
                        }
                    }

                    GGText { colorKey: "ui.MarketplaceSurface.48";
                        text: "REBIRTH SET  " + String(root.draftLives.length)
                        color: RuntimeTheme.GGTheme.accent
                        font.family: "monospace"
                        font.pixelSize: 12
                        font.bold: true
                    }
                    GGText { colorKey: "ui.MarketplaceSurface.49";
                        visible: root.draftLives.length > 0
                        width: parent.width
                        text: root.draftLives.join(" · ")
                        color: RuntimeTheme.GGTheme.text
                        font.family: "monospace"
                        font.pixelSize: 12
                        wrapMode: Text.WrapAnywhere
                    }
                    GgField { property string uiColorScope: "ui.widget.MarketplaceSurface.GgField.52";
                        id: rebirthField
                        width: Math.min(parent.width, 520)
                        placeholderText: "new object title"
                    }
                    GgButton { property string uiColorScope: "ui.control.MarketplaceSurface.30";
                        text: "MINT REBORN OBJECT"
                        onClicked: root.rebirthSelected()
                    }
                    GGText { colorKey: "ui.MarketplaceSurface.50";
                        visible: root.formError.length > 0 && root.page === "LIVES"
                        width: parent.width
                        text: root.formError
                        color: RuntimeTheme.GGTheme.negative
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
                ScrollBar.vertical: GgScrollBar { property string uiColorScope: "ui.widget.MarketplaceSurface.GgScrollBar.54";}

                Column {
                    id: actCol
                    width: parent.width
                    spacing: 6

                    GGText { colorKey: "ui.MarketplaceSurface.51";
                        visible: root.ledger.length === 0
                        text: "No catalog events yet."
                        color: RuntimeTheme.GGTheme.muted
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

                            GGText { colorKey: "ui.MarketplaceSurface.52";
                                width: 72
                                text: String(row.kind || "")
                                color: String(row.kind || "") === "BUY"
                                    ? RuntimeTheme.GGTheme.positive
                                    : (String(row.kind || "") === "DELIST"
                                        ? RuntimeTheme.GGTheme.negative
                                        : RuntimeTheme.GGTheme.accent)
                                font.family: "monospace"
                                font.pixelSize: 12
                                font.bold: true
                            }
                            GGText { colorKey: "ui.MarketplaceSurface.53";
                                width: parent.width - 82
                                text: String(row.listing_id || "")
                                    + "  "
                                    + String(row.txid || "PAPER")
                                    + "  "
                                    + root.shortHash(row.identity_sha256)
                                color: RuntimeTheme.GGTheme.text
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
