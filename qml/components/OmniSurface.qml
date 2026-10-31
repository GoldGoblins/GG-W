
import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls
import QtQuick.Window

Item {
    id: root
    objectName: "omniHub"
    property var surfaceHost: null
    signal browseRequested(string url)
    property bool embedded:false
    property var state: ({})
    property string page: "WALLET"
    property string selectedId: ""
    property bool eventsPaused: false
    property bool followEvents: true
    property string scope: ""
    property var frozenEvents: []
    property var telemetryPatch: ({})
    property real lastDagObservationMonotonic:-1
    readonly property var networkState: mergeTelemetry(state,telemetryPatch)
    property string pendingTelemetry: ""
    property var requestedNetworkStops: ({})
    property var networkStopErrors: ({})
    readonly property var telemetryWindow: root.Window.window
    readonly property bool telemetryWindowVisible: !telemetryWindow || telemetryWindow.visible && telemetryWindow.visibility !== Window.Minimized
    readonly property bool telemetryVisible: visible && telemetryWindowVisible
    property var pendingNftBinding:null
    property string nftSourceChainId:""
    readonly property var assets: state.assets || []
    readonly property var networks: state.networks || []
    readonly property var lab: state.lab || ({})
    readonly property var operation: state.ui_operation || ({})
    readonly property bool busy: operation.state === "running"
    readonly property bool approvalPending: operation.state === "approval_required"
    readonly property bool networkPage: page === "CONSENSUS" || page === "TESTNET" || page === "LAB" || page === "NODE" || page === "DAG"
    readonly property bool detailsVisible: networkPage && !!networkLoader.item && networkLoader.item.detailsVisible
    function toggleDetails() { if (networkLoader.item) networkLoader.item.toggleDetails() }
    readonly property var selectedAsset: {
        for (var i=0;i<assets.length;i++) if (assets[i].id === (selectedId || state.selected_asset)) return assets[i]
        return assets.length ? assets[0] : ({})
    }
    readonly property var accounts: (state.accounts || []).filter(function(a) { return a.chain_id === root.selectedAsset.chain_id })
    readonly property var rows: (eventsPaused ? frozenEvents : state.events || []).filter(function(e) { return !root.scope || e.scope === root.scope })
    readonly property bool labReady: lab.state === "ACTIVE_SESSION"
    function apply(raw) {
        try {
            var next=JSON.parse(raw)
            if (next && !Array.isArray(next) && next.assets) {
                reconcileTelemetrySession(next)
                next=mergeTelemetry(next,telemetryPatch)
                next=preserveNewerObservation(next,"testnet")
                next=preserveNewerObservation(next,"parallel_dag")
                state=next
                if(page!=="NFT" && (next.ui_operation || {}).state!=="running")selectedId=next.selected_asset || selectedId
            }
        } catch(e) {}
    }
    function reconcileTelemetrySession(next) {
        var key=telemetryPatch.network_page==="TESTNET"?"testnet":telemetryPatch.network_page==="DAG"?"parallel_dag":""
        if(!key || !next[key] || !telemetryPatch[key])return
        var identity=key==="testnet"?"session":"chain_id", incoming=next[key], patch=telemetryPatch[key]
        // A full action response establishes the new engine session. An idle
        // patch from before Start has no authority over that new session.
        if(incoming[identity]!==patch[identity] || incoming.state==="STOPPED") {
            telemetryPatch=({})
            pendingTelemetry=""
        }
    }
    function observationTime(body){return Number((body||{}).observation_at||((body||{}).block_graph||{}).observed_at||0)}
    function preserveNewerObservation(next,key){
        var old=networkState[key], incoming=next[key]
        if(!old || !incoming || incoming.state==="STOPPED")return next
        var identity=key==="testnet"?"session":"chain_id"
        if(!old[identity] || old[identity]!==incoming[identity] || observationTime(old)<=observationTime(incoming))return next
        var body=Object.assign({},incoming)
        // Full balance/review snapshots still apply; only a newer observation
        // of this exact engine session protects its live presentation fields.
        var fields=key==="testnet"?["state","error","height","block_graph","measurements","rpc_totals","observation_at"]:Object.keys(old)
        for(var i=0;i<fields.length;i++)if(old[fields[i]]!==undefined)body[fields[i]]=old[fields[i]]
        if(body.state==="READ_FAILED")body.review=null
        var result=Object.assign({},next);result[key]=body;return result
    }
    function mergeTelemetry(body,patch) {
        var key=patch.network_page==="TESTNET"?"testnet":patch.network_page==="DAG"?"parallel_dag":""
        if(!key || !patch[key])return body
        var old=body[key]||({}), fresh=patch[key]
        if(key==="parallel_dag") {
            var oldCli=(old.observation||{}).read_only===true
            var freshCli=(fresh.observation||{}).read_only===true&&(fresh.observation||{}).source==="LOCAL_CLI"
            if(freshCli&&oldCli&&fresh.observation.publisher_started_at===old.observation.publisher_started_at&&typeof fresh.observation.publication_sequence==="number"&&fresh.observation.publication_sequence<Number(old.observation.publication_sequence||0))return body
            // Observing an already running CLI is a read-only source change,
            // never permission to start/adopt a node or replace an owned peer.
            if(freshCli&&(oldCli||(!old.state||old.state==="STOPPED")&&!(old.lan_setup||{}).active)||oldCli&&!freshCli&&fresh.state==="STOPPED") {
                var observed=Object.assign({},body);observed[key]=fresh;return observed
            }
        }
        var identity=key==="testnet"?"session":"chain_id"
        if(old[identity] && fresh[identity]!==undefined && old[identity]!==fresh[identity])return body
        // A normal account/wallet response may have been queued before the
        // current lightweight header. It must not move the live graph back.
        var oldTime=observationTime(old), freshTime=observationTime(fresh)
        if(fresh.state!=="STOPPED" && oldTime>freshTime || old.state==="STOPPED" && fresh.state!=="STOPPED")return body
        var result=Object.assign({},body)
        result[key]=Object.assign({},old,fresh)
        return result
    }
    function applyTelemetry(raw) {
        if(!telemetryVisible)return
        try {
            var patch=JSON.parse(raw)
            if(patch.network_page!==page)return
            if(page==="DAG"&&typeof patch.observed_monotonic==="number"&&patch.observed_monotonic<lastDagObservationMonotonic)return
            if(patch.error) {
                var key=page==="TESTNET"?"testnet":"parallel_dag", failed=Object.assign({},networkState[key]||({}))
                failed.error=patch.error
                failed.observation_at=Date.now()/1000
                failed.block_graph=Object.assign({},failed.block_graph||({}),{stale:true,error:patch.error})
                if(page==="TESTNET"){failed.state="READ_FAILED";failed.review=null}
                var failure={network_page:page};failure[key]=failed;telemetryPatch=failure
                return
            }
            var current=networkState, merged=mergeTelemetry(current,patch)
            if(merged===current)return
            telemetryPatch=patch
              if(page==="DAG"&&typeof patch.observed_monotonic==="number")lastDagObservationMonotonic=patch.observed_monotonic
        } catch(e) {}
    }
    function flushTelemetry(){var raw=pendingTelemetry;pendingTelemetry="";if(raw)applyTelemetry(raw)}
    function queueTelemetry(raw){
        if(!telemetryVisible || (page!=="TESTNET" && page!=="DAG"))return
        pendingTelemetry=raw
        if(!telemetryFlush.running)telemetryFlush.start()
    }
    function setTelemetryView() {
        var selected=telemetryVisible && (page==="TESTNET" || page==="DAG")?page:""
        if(surfaceHost && surfaceHost.setNetworkTelemetryOwner)
            surfaceHost.setNetworkTelemetryOwner(root,selected)
        else if(surfaceHost && surfaceHost.setNetworkTelemetryView)
            surfaceHost.setNetworkTelemetryView(selected)
    }
    function pull() { if (visible && surfaceHost && surfaceHost.omniStatus) apply(surfaceHost.omniStatus()) }
    function run(name,args) {
        if((name==="testnet_stop" || name==="dag_stop") && surfaceHost && surfaceHost.requestNetworkStop) {
            var target=name==="testnet_stop"?"TESTNET":"DAG"
            if(requestedNetworkStops[target])return
            var errors=Object.assign({},networkStopErrors);errors[target]="";networkStopErrors=errors
            if(surfaceHost.requestNetworkStop(target)) {
                var pending=Object.assign({},requestedNetworkStops);pending[target]=true;requestedNetworkStops=pending
            } else {
                errors=Object.assign({},networkStopErrors);errors[target]="Stoppbegäran kunde inte skickas";networkStopErrors=errors
            }
            return
        }
        if (!busy && !approvalPending && surfaceHost && surfaceHost.omniAction) apply(surfaceHost.omniAction(name,JSON.stringify(args || {})))
    }
    function networkStopFinished(target,error) {
        var pending=Object.assign({},requestedNetworkStops);pending[target]=false;requestedNetworkStops=pending
        var errors=Object.assign({},networkStopErrors);errors[target]=error?"Stoppet misslyckades. Försök igen.":"";networkStopErrors=errors
        pull()
    }
    function networkName(id) { for (var i=0;i<networks.length;i++) if(networks[i].id===id) return networks[i].name; return id || "" }
    function inspectBinding(binding){pendingNftBinding=binding;page="NFT";applyNftBinding();pull()}
    function applyNftBinding(){
        if(!pendingNftBinding || busy || !assets.length)return
        var binding=pendingNftBinding;pendingNftBinding=null;nftSourceChainId=binding.chain_id
        for(var i=0;i<assets.length;i++)if(assets[i].chain_id===binding.chain_id){selectedId=assets[i].id;break}
        nftStandard.currentIndex=["erc721","erc1155","krc721"].indexOf(binding.standard)
        nftCollection.text=binding.collection;nftId.text=binding.token_id
        if(binding.standard!=="erc1155" && binding.token_id)run("mp_inspect_nft",{chain_id:binding.chain_id,standard:binding.standard,collection:binding.collection,token_id:binding.token_id})
    }
    onStateChanged:Qt.callLater(applyNftBinding)
    function balance(accountId) {
        var obs=state.observations || []
        for(var i=0;i<obs.length;i++) if(obs[i].account_id===accountId && obs[i].asset_id===selectedAsset.id) {
            var age=obs[i].observed_at ? Math.max(0,Math.floor(Date.now()/1000-obs[i].observed_at))+" s sedan" : "aldrig verifierat"
            return String(obs[i].quantity)+" "+selectedAsset.symbol+" · "+obs[i].state+" · "+age
        }
        return "Saldo ej hämtat"
    }
    onVisibleChanged: if (visible) pull()
    onTelemetryVisibleChanged: setTelemetryView()
    onPageChanged: {telemetryPatch=({});pendingTelemetry="";setTelemetryView()}
    onSurfaceHostChanged: setTelemetryView()
    Component.onCompleted: {pull();setTelemetryView()}
    Component.onDestruction: {
        telemetryFlush.stop();pendingTelemetry=""
        if(surfaceHost && surfaceHost.setNetworkTelemetryOwner)surfaceHost.setNetworkTelemetryOwner(root,"")
        else if(surfaceHost && surfaceHost.setNetworkTelemetryView)surfaceHost.setNetworkTelemetryView("")
    }
    Connections {target:root.surfaceHost;ignoreUnknownSignals:true;function onOmniStatusUpdated(raw){if(root.visible)root.apply(raw)} function onNetworkTelemetryUpdated(raw){root.queueTelemetry(raw)} function onNetworkStopFinished(target,error){root.networkStopFinished(target,error)}}
    Timer {id:telemetryFlush;interval:0;repeat:false;onTriggered:root.flushTelemetry()}
    Timer { interval: root.busy || !root.state.assets ? 100 : 2000; running: root.visible; repeat:true; onTriggered:root.pull() }
    component Label: GGText {
        color: RuntimeTheme.GGTheme.text; font.family: "monospace"; font.pixelSize: 12
        textFormat: Text.PlainText; wrapMode: Text.WrapAnywhere
    }
    component Action: CryptoButton {
        font.family: "monospace"; font.pixelSize:11; enabled: !root.busy && !root.approvalPending
    }
    Loader {
        id: networkLoader; objectName: "omniNetworkLoader"; anchors.fill: parent
        active: root.networkPage; visible: active
        sourceComponent: root.page === "DAG" ? dagComponent : root.page === "CONSENSUS" ? consensusComponent : root.page === "TESTNET" ? testnetComponent : labComponent
    }
    Component {
        id:dagComponent
        GGParallelDagDashboard { property string uiColorScope: "ui.widget.OmniSurface.GGParallelDagDashboard.1";
            state:root.networkState;surfaceHost:root.surfaceHost
            stopRequested:!!root.requestedNetworkStops.DAG;stopError:String(root.networkStopErrors.DAG||"")
            onActionRequested:function(name,args){root.run(name,args)}
            onRefreshRequested:root.pull()
            onPageRequested:function(page){root.page=page}
        }
    }
    Component {
        id: consensusComponent
        GGConsensusDashboard { property string uiColorScope: "ui.widget.OmniSurface.GGConsensusDashboard.2";
            state: root.state; surfaceHost: root.surfaceHost
            onWebRequested: function(url) { root.browseRequested(url) }
            onActionRequested: function(name, args) { root.run(name, args) }
            onRefreshRequested: root.pull()
            onPageRequested: function(page) { root.page = page }
        }
    }
    Component {
        id: testnetComponent
        GGTestnetDashboard { property string uiColorScope: "ui.widget.OmniSurface.GGTestnetDashboard.3";
            state: root.state; liveObservation:root.networkState.testnet||({});surfaceHost: root.surfaceHost
            stopRequested:!!root.requestedNetworkStops.TESTNET;stopError:String(root.networkStopErrors.TESTNET||"")
            onActionRequested: function(name, args) { root.run(name, args) }
            onRefreshRequested: root.pull()
            onPageRequested: function(page) { root.page = page }
        }
    }
    Component {
        id: labComponent
        NetworkDashboard { property string uiColorScope: "ui.widget.OmniSurface.NetworkDashboard.4";
            state: root.state; surfaceHost: root.surfaceHost
            onWebRequested: function(url) { root.browseRequested(url) }
            onActionRequested: function(name, args) { root.run(name, args) }
            onRefreshRequested: root.pull()
            onPageRequested: function(page) { root.page = page }
        }
    }
    Flickable {
        id: scroll; visible: !root.networkPage
        anchors.fill: parent; contentWidth: width; contentHeight: content.height+12
        clip:true; boundsBehavior:Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar {}
        Column {
            id:content; width:scroll.width; spacing:12
            Label { colorKey: "ui.OmniSurface.1"; visible:!root.embedded; width:parent.width; text:"OMNI · plånbok / bidrag / nätverkslabb"; color:RuntimeTheme.GGTheme.bright; font.bold:true; font.pixelSize:15 }
            Flow {
                width:parent.width; spacing:6
                CryptoPick { property string uiColorScope: "ui.control.OmniSurface.1";visible:root.embedded;width:190;model:[{id:"WALLET",name:"Konton & tillgångar"},{id:"BOTS",name:"Paperbotar"},{id:"LAB",name:"Nätverkslabb"},{id:"NODE",name:"Nod & webbvy"},{id:"NFT",name:"NFT-inspektör"},{id:"ACTIVITY",name:"Aktivitet"}];textRole:"name";currentIndex:{for(var i=0;i<model.length;i++)if(model[i].id===root.page)return i;return 0} onActivated:root.page=model[currentIndex].id}
                Repeater {
                    model:root.embedded ? [] : ["WALLET","NFT","BOTS","NODE","LAB","ACTIVITY"]
                    Action { property string uiColorScope: "ui.control.OmniSurface.2"; required property string modelData; text:modelData; checkable:true; checked:root.page===modelData; onClicked:root.page=modelData }
                }
                Action { property string uiColorScope: "ui.control.OmniSurface.3"; text:"Uppdatera"; onClicked:root.pull() }
                BusyIndicator { width:28; height:28; running:root.busy; visible:running }
            }
            Label { colorKey: "ui.OmniSurface.2";
                width:parent.width; visible:root.busy || !!root.operation.error || !!root.state.error
                color:root.operation.error || root.state.error ? RuntimeTheme.GGTheme.negative : RuntimeTheme.GGTheme.accent
                text:root.busy ? "Arbetar · "+String(root.operation.name || "") : String(root.operation.error || root.state.error || "")
                Accessible.role: Accessible.StaticText; Accessible.name:text
            }
            Column {
                width:parent.width; spacing:9; visible:root.page==="WALLET"
                Label { colorKey: "ui.OmniSurface.3"; width:parent.width; text:"Välj tillgång med nätverk och kontraktsadress. Samma ticker på två nätverk är två olika tillgångar." }
                CryptoPick { property string uiColorScope: "ui.control.OmniSurface.4";
                    id:assetChoice; objectName:"omniAssetPicker"; width:parent.width; model:root.assets; textRole:"symbol"
                    currentIndex:{for(var i=0;i<root.assets.length;i++)if(root.assets[i].id===root.selectedAsset.id)return i;return -1}
                    displayText:root.selectedAsset.symbol ? root.selectedAsset.symbol+" · "+root.networkName(root.selectedAsset.chain_id) : "Läser tillgångar…"
                    delegate:ItemDelegate { property string uiColorScope: "ui.control.OmniSurface.5";
                        required property var modelData;required property int index;width:assetChoice.width
                        highlighted:assetChoice.highlightedIndex===index
                        contentItem:GGText { colorKey: "ui.OmniSurface.4"; text:modelData.symbol+" · "+root.networkName(modelData.chain_id)+" · "+modelData.reference;color:RuntimeTheme.GGTheme.text;font.family:"monospace";font.pixelSize:11;elide:Text.ElideRight;textFormat:Text.PlainText }
                        background:Rectangle { color:parent.highlighted || parent.hovered ? RuntimeTheme.GGTheme.line : RuntimeTheme.GGTheme.panel }
                    }
                    Accessible.name:"Tillgång och nätverk"
                    onActivated: { root.nftSourceChainId="";root.selectedId=root.assets[currentIndex].id; root.run("select_asset",{id:root.selectedId}) }
                }
                Label { colorKey: "ui.OmniSurface.5"; width:parent.width; color:RuntimeTheme.GGTheme.muted; font.pixelSize:10; text:String(root.selectedAsset.id || "")+" · "+String(root.selectedAsset.metadata || "") }
                Repeater {
                    model:root.accounts
                    Column {
                        required property var modelData
                        width:content.width; spacing:5
                        Label { colorKey: "ui.OmniSurface.6"; width:parent.width; text:modelData.label+" · "+modelData.address }
                        Label { colorKey: "ui.OmniSurface.7"; width:parent.width; color:RuntimeTheme.GGTheme.accent; text:root.balance(modelData.id) }
                        Flow { width:parent.width; spacing:6
                            Action { property string uiColorScope: "ui.control.OmniSurface.6"; text:"Hämta saldo"; enabled:!root.busy && root.selectedAsset.namespace!==undefined && root.selectedAsset.chain_id.indexOf("gglab:")!==0; onClicked:root.run("refresh_balance",{asset_id:root.selectedAsset.id,account_id:modelData.id}) }
                            Action { property string uiColorScope: "ui.control.OmniSurface.7"; text:"Koppla från"; onClicked:root.run("remove_watch",{id:modelData.id}) }
                        }
                    }
                }
                CryptoField { property string uiColorScope: "ui.widget.OmniSurface.CryptoField.11"; id:watchAddress; objectName:"omniWatchAddress";width:parent.width; placeholderText:"Offentlig adress på valt nätverk"; Accessible.name:placeholderText }
                Action { property string uiColorScope: "ui.control.OmniSurface.8"; text:"Lägg till bevakningskonto"; enabled:!root.busy && watchAddress.text.trim().length>0; onClicked:root.run("watch",{chain_id:root.selectedAsset.chain_id,address:watchAddress.text.trim()}) }
                CryptoField { property string uiColorScope: "ui.widget.OmniSurface.CryptoField.13"; id:tokenAddress; width:parent.width; placeholderText:"EVM-kontrakt eller Solana mint på valt nätverk"; Accessible.name:placeholderText }
                Action { property string uiColorScope: "ui.control.OmniSurface.9"; text:"Identifiera och lägg till token"; enabled:!root.busy && tokenAddress.text.trim().length>0; onClicked:root.run("import_token",{chain_id:root.selectedAsset.chain_id,reference:tokenAddress.text.trim()}) }
                Label { colorKey: "ui.OmniSurface.8"; width:parent.width; color:RuntimeTheme.GGTheme.muted; text:"Publika saldon läses från valt RPC. Signering, börskonton och hårdvaruplånböcker kräver egna anslutningar. Ingen brygga eller växling är ansluten." }
                Flow { width:parent.width; spacing:8
                    Repeater { model:root.state.providers || []
                        Label { colorKey: "ui.OmniSurface.9"; required property var modelData; text:modelData.name+" · "+modelData.state; color:RuntimeTheme.GGTheme.muted; font.pixelSize:10 }
                    }
                }
            }
            Column {
                width:parent.width; spacing:9; visible:root.page==="NFT"
                Label { colorKey: "ui.OmniSurface.10"; width:parent.width; text:"GG-721 · objekt, samlingar och ägande"; font.bold:true }
                Label { colorKey: "ui.OmniSurface.11"; width:parent.width; text:"GG-20 beskriver delbara tillgångar, GG-721 unika objekt och GG-1155 utgåvor. Adaptern bevarar betydelsen på valt nätverk. Lokal objekthistorik finns kvar i MP:s kvitton, material och tidigare liv." }
                Label { colorKey: "ui.OmniSurface.12"; width:parent.width; color:RuntimeTheme.GGTheme.accent; text:"Nätverk: "+root.networkName(root.nftSourceChainId || root.selectedAsset.chain_id)+" · välj ett annat under WALLET" }
                CryptoPick { property string uiColorScope: "ui.control.OmniSurface.10"; id:nftStandard; width:parent.width; model:["erc721","erc1155","krc721"]; Accessible.name:"NFT-protokoll" }
                CryptoField { property string uiColorScope: "ui.widget.OmniSurface.CryptoField.16"; id:nftCollection; width:parent.width; placeholderText:"Kontraktsadress eller KRC-721 samlingsticker"; Accessible.name:placeholderText }
                CryptoField { property string uiColorScope: "ui.widget.OmniSurface.CryptoField.17"; id:nftId; width:parent.width; placeholderText:"Token-ID · heltal som text"; Accessible.name:placeholderText; maximumLength:78 }
                CryptoField { property string uiColorScope: "ui.widget.OmniSurface.CryptoField.18"; id:nftHolder; width:parent.width; visible:nftStandard.currentText==="erc1155"; placeholderText:"Ägaradress för ERC-1155 saldokontroll"; Accessible.name:placeholderText }
                Action { property string uiColorScope: "ui.control.OmniSurface.11"; text:"Inspektera NFT"; enabled:!root.busy && nftCollection.text.length>0 && nftId.text.length>0; onClicked:root.run("mp_inspect_nft",{chain_id:root.nftSourceChainId || root.selectedAsset.chain_id,standard:nftStandard.currentText,collection:nftCollection.text.trim(),token_id:nftId.text.trim(),holder:nftHolder.text.trim()}) }
                Label { colorKey: "ui.OmniSurface.13"; width:parent.width; color:RuntimeTheme.GGTheme.muted; text:"Läsning av ägande från RPC eller indexer. Metadataadresser öppnas inte automatiskt. Inspektion ger ingen överföringsbehörighet och skapar ingen säljorder." }
                Label { colorKey: "ui.OmniSurface.14"; width:parent.width; text:"Moduler"; font.bold:true }
                Repeater {
                    model:(root.state.marketplace || {}).modules || []
                    Column {
                        required property var modelData; width:content.width; spacing:3
                        CryptoToggle { property string uiColorScope: "ui.control.OmniSurface.12"; width:parent.width; text:modelData.name; checked:modelData.enabled; enabled:!root.busy && !modelData.required; onClicked:root.run("mp_module",{id:modelData.id,enabled:checked}) }
                        Label { colorKey: "ui.OmniSurface.15"; width:parent.width; font.pixelSize:10; color:RuntimeTheme.GGTheme.muted; text:modelData.state+" · "+modelData.operations.join(" / ")+(modelData.required ? " · kärnmodul" : "") }
                    }
                }
                Label { colorKey: "ui.OmniSurface.16"; width:parent.width; text:"Bevakade NFT: "+String((root.state.marketplace || {}).watched_count || 0); font.bold:true }
                ListView {
                    id:nftList; width:parent.width; height:count>0 ? 320 : 0; clip:true; spacing:10
                    model:(root.state.marketplace || {}).watched_nfts || []; ScrollBar.vertical:ScrollBar {}
                    delegate:Column {
                        required property var modelData; width:nftList.width; spacing:4
                        Label { colorKey: "ui.OmniSurface.17"; width:parent.width; text:modelData.standard+" · "+modelData.collection+" #"+modelData.token_id; font.bold:true }
                        Label { colorKey: "ui.OmniSurface.18"; width:parent.width; text:String(modelData.owner || modelData.holder || "")+" · antal "+modelData.quantity }
                        Label { colorKey: "ui.OmniSurface.19"; width:parent.width; color:RuntimeTheme.GGTheme.muted; font.pixelSize:10; text:modelData.trust+" · "+new Date(modelData.observed_at*1000).toLocaleString()+"\n"+modelData.id+"\n"+String(modelData.metadata_uri || "Metadata-URI saknas") }
                    }
                }
            }
            Column {
                width:parent.width; spacing:9; visible:root.page==="BOTS"
                Label { colorKey: "ui.OmniSurface.20"; width:parent.width; text:"Botar · "+String(root.selectedAsset.symbol || "")+" · "+root.networkName(root.selectedAsset.chain_id); font.bold:true }
                Label { colorKey: "ui.OmniSurface.21"; width:parent.width; text:"Sex separata paperkonton per tillgång. Välj tillgång under WALLET. Kopplingen till ett börspar är din valda prisreferens; en ticker bevisar inte tokenkontraktets identitet." }
                CryptoField { property string uiColorScope: "ui.widget.OmniSurface.CryptoField.21"; id:marketPair; width:parent.width; placeholderText:"Spotpar mot USDT, t.ex. BTCUSDT"; Accessible.name:placeholderText }
                Action { property string uiColorScope: "ui.control.OmniSurface.13"; text:"Koppla vald prisreferens"; enabled:!root.busy && marketPair.text.trim().length>0; onClicked:root.run("bind_market",{asset_id:root.selectedAsset.id,pair:marketPair.text.trim().toUpperCase()}) }
                Label { colorKey: "ui.OmniSurface.22"; width:parent.width; color:RuntimeTheme.GGTheme.muted; text:String((root.state.bots || {}).state || "MARKET_MAPPING_REQUIRED")+" · "+String((root.state.bots || {}).pair || "")+"\nAnalys sker per manuellt startat steg, på stängda staplar. Inga riktiga order skickas." }
                Action { property string uiColorScope: "ui.control.OmniSurface.14"; text:"Kör nästa analyssteg · paper"; enabled:!root.busy && (root.state.bots || {}).state==="PAPER_MANUAL_STEPS"; onClicked:root.run("bot_step",{asset_id:root.selectedAsset.id}) }
                Repeater {
                    model:(root.state.bots || {}).accounts || []
                    Column {
                        required property var modelData; width:content.width; spacing:5
                        Label { colorKey: "ui.OmniSurface.23"; width:parent.width; text:modelData.name+" · "+modelData.status+" · "+Number(modelData.equity_quote || 0).toFixed(2)+" USDT" }
                        Label { colorKey: "ui.OmniSurface.24"; width:parent.width; color:RuntimeTheme.GGTheme.negative; visible:!!modelData.error; text:String(modelData.error || "") }
                        Flow { width:parent.width; spacing:6
                            CryptoToggle { property string uiColorScope: "ui.control.OmniSurface.15"; text:modelData.enabled ? "Aktiverad för nästa steg" : "Pausad"; checked:modelData.enabled; enabled:!root.busy; onClicked:root.run("bot_enabled",{asset_id:root.selectedAsset.id,book:modelData.book,enabled:checked}) }
                            Action { property string uiColorScope: "ui.control.OmniSurface.16"; text:"Nytt paperkonto"; onClicked:root.run("bot_reset",{asset_id:root.selectedAsset.id,book:modelData.book}) }
                        }
                    }
                }
            }
            Column {
                width:parent.width; spacing:7; visible:root.page==="ACTIVITY"
                Flow { width:parent.width; spacing:6
                    CryptoToggle { property string uiColorScope: "ui.control.OmniSurface.17"; text:"Pausa visning"; checked:root.eventsPaused; onClicked:{root.frozenEvents=(root.state.events || []).slice();root.eventsPaused=checked} }
                    CryptoToggle { property string uiColorScope: "ui.control.OmniSurface.18"; text:"Följ senaste"; checked:root.followEvents; onClicked:root.followEvents=checked }
                    CryptoPick { property string uiColorScope: "ui.control.OmniSurface.19"; model:["Alla","wallet","assets","bots","market","lab","node","transport"]; Accessible.name:"Aktivitetsfilter"; onActivated:root.scope=currentIndex===0 ? "" : currentText }
                }
                Rectangle {
                    width:parent.width; height:Math.min(420,Math.max(150,root.height-160)); color:RuntimeTheme.GGTheme.canvas; border.color:RuntimeTheme.GGTheme.line; radius:4
                    ListView {
                        id:eventConsole; anchors.fill:parent; anchors.margins:8; clip:true; model:root.rows; spacing:6
                        ScrollBar.vertical:ScrollBar {}
                        onCountChanged:if(root.followEvents && !root.eventsPaused) positionViewAtEnd()
                        delegate:Label { colorKey: "ui.OmniSurface.25";
                            required property var modelData; width:eventConsole.width; font.pixelSize:11
                            text:new Date(modelData.ts*1000).toLocaleTimeString()+"  "+modelData.scope+"  "+modelData.kind+"  "+modelData.message
                            color:["READ_FAILED","WAITING_QUORUM","RETRY_REQUIRED"].indexOf(modelData.kind)>=0 ? RuntimeTheme.GGTheme.accent : RuntimeTheme.GGTheme.text
                        }
                        Label { colorKey: "ui.OmniSurface.26"; anchors.centerIn:parent; visible:eventConsole.count===0; text:"Inga händelser i detta filter"; color:RuntimeTheme.GGTheme.muted }
                    }
                }
            }
        }
    }
}
