import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

import "MarketFormat.js" as Format

// Public references use the same category / image catalog / passport geometry.
Item {
    id:root;objectName:"publicMarketplace"
    property var state:({})
    property bool busy:false
    property string query:""
    property bool detailOpen:false
    property var pending:({})
    property string networkFilter:""
    property string previewPageKey:""
    property string catalogMode:"ATLAS"
    property string sortChoice:"recent"
    readonly property var previewJob:state.preview_job || ({})
    readonly property bool previewsRunning:previewJob.state==="running" && previewJob.worker_active===true
    readonly property bool previewActive:previewJob.worker_active===true
    readonly property var sourceRows:(state.rows || []).map(function(row){return root.catalogRow(row)})
    readonly property var rows:{var values=sourceRows.filter(function(row){return (!root.networkFilter || row.network_key===root.networkFilter) && (!root.query || (row.name+" "+row.symbol+" "+row.collection+" "+row.platform).toLowerCase().indexOf(root.query.toLowerCase())>=0)});if(sortChoice==="name")values.sort(function(a,b){return a.title.localeCompare(b.title)});return values}
    readonly property string focusedId:{var desired=pending.id || (state.selected || {}).id || "";for(var i=0;i<rows.length;i++)if(rows[i].id===desired)return desired;return rows.length ? rows[0].id : ""}
    readonly property var selected:{var base=rows.filter(function(row){return row.id===root.focusedId})[0] || ({});return base.id && (state.selected || {}).id===base.id ? catalogRow(Object.assign({},base,state.selected)) : base}
    signal refreshRequested(string provider,int page)
    signal selectRequested(string id)
    signal inspectRequested(var binding)
    signal copyRequested(string reference)
    signal previewsRequested(var ids)
    signal stopPreviewsRequested()
    function catalogRow(row){
        var value=Object.assign({},row)
        value.title=String(row.name || row.title || "Samling")
        value.kind="COLLECTION"
        value.network_key=row.chain_id || "platform:"+String(row.platform || "Okänt nätverk")
        value.subtitle=String(row.platform || "Okänt nätverk")+" · samling"
        value.reference_label=row.collection ? Format.shortAddress(row.collection) : String(row.provider_id || "")
        value.price_label=row.floor_usd!==null && row.floor_usd!==undefined ? "Golvpris · "+Format.money(row.floor_usd) : "Golvpris ej hämtat"
        value.image_caption=row.image_error ? "Bilden kunde inte hämtas" : row.detail_state==="CURRENT" || row.detail_state==="STALE" ? "Källan saknar bild" : "Bild ej hämtad"
        return value
    }
    function choose(row){if(busy || !row || !row.id)return;pending=row;detailOpen=true;selectRequested(row.id);if(!browser.showPassport)browser.openPassport()}
    function chooseId(id){var row=rows.filter(function(row){return row.id===id})[0];if(row)choose(row)}
    function openCategories(){browser.openCategories()}
    function changePage(provider,page){if(busy)return;pending=({});detailOpen=false;networkFilter="";refreshRequested(provider,page)}
    function readPreviews(){if(busy || previewJob.worker_active)return;var ids=rows.filter(function(row){return !row.image_url && row.detail_state!=="CURRENT"}).slice(0,6).map(function(row){return row.id});if(ids.length)previewsRequested(ids)}
    function maybePreviews(){if(!visible || busy || !(state.rows || []).length || previewJob.worker_active)return;var key=String(state.provider || "coingecko")+":"+String(state.page || 1)+":"+String(state.observed_at || "");if(key===previewPageKey)return;previewPageKey=key;readPreviews()}
    onStateChanged:{if(pending.id && !(state.rows || []).some(function(row){return row.id===root.pending.id})){pending=({});detailOpen=false}Qt.callLater(root.maybePreviews)}
    onVisibleChanged:{if(visible)Qt.callLater(root.maybePreviews);else if(previewJob.worker_active)stopPreviewsRequested()}
    onBusyChanged:if(!busy)Qt.callLater(root.maybePreviews)
    Component.onCompleted:Qt.callLater(root.maybePreviews)
    component PublicLabel:GGText {color:RuntimeTheme.GGTheme.text;font.family:"monospace";font.pixelSize:11;textFormat:Text.PlainText;elide:Text.ElideRight}
    MarketplaceBrowser { property string uiColorScope: "ui.widget.MarketplaceDiscovery.MarketplaceBrowser.1";
        id:browser;objectName:"publicCollectionBrowser";anchors.fill:parent
        rows:root.rows;sourceRows:root.sourceRows;fullRows:root.sourceRows;events:root.state.events || [];receipt:root.selected;focusedId:root.focusedId;busy:root.busy;mode:root.catalogMode;sort:root.sortChoice
        eventScopeLabel:"Publika kataloghändelser";eventEmptyMessage:"Inga kataloghändelser registrerade."
        emptyTitle:root.query || root.networkFilter ? "Inga matchande samlingar" : "Publika samlingsreferenser"
        emptyMessage:root.busy ? "Läser katalogen från den valda källan…" : root.state.source_state==="FAILED" ? "Katalogen kunde inte läsas. Försök igen eller välj en annan källa." : root.query || root.networkFilter ? "Justera sökningen eller nätverket för att se fler samlingar på den här sidan." : "Välj Uppdatera för att läsa katalogen. Samlingsdata är publika referenser, inte säljorder eller ägarbevis."
        categoryComponent:Component {MarketplaceNetworkTree { property string uiColorScope: "ui.widget.MarketplaceDiscovery.MarketplaceNetworkTree.2";rows:root.sourceRows;networkFilter:root.networkFilter;busy:root.busy;previewJob:root.previewJob;provider:root.state.provider || "coingecko";sourceState:root.state.source_state || "NOT_FETCHED";observedAt:root.state.observed_at || 0;onNetworkRequested:function(network){root.networkFilter=network}}}
        passportComponent:Component {MarketplaceCollectionPassport { property string uiColorScope: "ui.widget.MarketplaceDiscovery.MarketplaceCollectionPassport.3";collection:root.selected;state:root.state;busy:root.busy;onInspectRequested:function(binding){root.inspectRequested(binding)};onCopyRequested:function(reference){root.copyRequested(reference)}}}
        catalogToolsComponent:Component {
            Flow {id:toolbar;objectName:"publicCatalogToolbar";width:parent.width;spacing:5
                CryptoPick { property string uiColorScope: "ui.control.MarketplaceDiscovery.1";objectName:"publicCatalogProvider";width:Math.min(140,parent.width*.3);height:26;font.pixelSize:10;enabled:!root.busy;model:[{id:"coingecko",name:"CoinGecko · NFT"},{id:"kat",name:"Kaspa · KRC-721"}];textRole:"name";currentIndex:root.state.provider==="kat" ? 1 : 0;onActivated:root.changePage(model[currentIndex].id,1)}
                CryptoButton { property string uiColorScope: "ui.control.MarketplaceDiscovery.2";objectName:"publicCatalogRefresh";width:28;implicitWidth:28;height:26;text:"↻";tip:root.busy ? "Läser katalogen…" : "Uppdatera katalogen";enabled:!root.busy;onClicked:root.changePage(root.state.provider || "coingecko",root.state.page || 1)}
                CryptoButton { property string uiColorScope: "ui.control.MarketplaceDiscovery.3";objectName:"publicCatalogPreviews";width:28;implicitWidth:28;height:26;text:root.previewActive ? "■" : "▧";tip:root.previewActive ? root.previewsRunning ? "Stoppa läsning av samlingsbilder" : "Avslutar föregående bildläsning" : "Läs bilder för upp till sex samlingar utan bild";enabled:!root.busy && (!root.previewActive || root.previewsRunning);onClicked:{if(root.previewsRunning)root.stopPreviewsRequested();else root.readPreviews()}}
                PublicLabel { colorKey: "ui.MarketplaceDiscovery.1";width:Math.max(48,Math.min(156,toolbar.width-Math.min(140,toolbar.width*.3)-28-28-24-42-24-30));height:26;verticalAlignment:Text.AlignVCenter;font.pixelSize:10;text:root.previewsRunning ? "Kontroll "+String(root.previewJob.completed || 0)+" / "+String(root.previewJob.total || 0) : root.previewActive ? "Avslutar…" : "Visar "+root.rows.length+" / "+root.sourceRows.length;color:root.state.source_state==="FAILED" ? RuntimeTheme.GGTheme.negative : RuntimeTheme.GGTheme.muted}
                CryptoButton { property string uiColorScope: "ui.control.MarketplaceDiscovery.4";objectName:"publicCatalogPrevious";width:24;implicitWidth:24;height:26;text:"←";tip:"Föregående katalogsida";enabled:!root.busy && root.state.page>1;onClicked:root.changePage(root.state.provider,root.state.page-1)}
                PublicLabel { colorKey: "ui.MarketplaceDiscovery.2";width:42;height:26;text:"Sida "+(root.state.page || 1);verticalAlignment:Text.AlignVCenter;horizontalAlignment:Text.AlignHCenter;font.pixelSize:10}
                CryptoButton { property string uiColorScope: "ui.control.MarketplaceDiscovery.5";objectName:"publicCatalogNext";width:24;implicitWidth:24;height:26;text:"→";tip:"Nästa katalogsida";enabled:!root.busy && root.state.provider!=="kat" && (root.state.page || 1)<50;onClicked:root.changePage(root.state.provider || "coingecko",(root.state.page || 1)+1)}
            }
        }
        onSortRequested:function(sort){root.sortChoice=sort}
        onModeRequested:function(mode){root.catalogMode=mode}
        onObjectFocused:function(id){root.chooseId(id)}
        onObjectOpened:function(id){root.chooseId(id)}
    }
}
