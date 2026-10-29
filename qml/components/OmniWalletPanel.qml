import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

import "MarketFormat.js" as Format

Item {
    id:root;objectName:"omniWalletOverview"
    property var surfaceHost:null
    property bool embedded:false
    property bool dashboard:false
    property bool compactPopup:false
    property bool showZero:false
    property var state:({})
    property bool showLab:false
    property bool showActivity:false
    property bool connectOpen:false
    property bool detailOpen:false
    property bool actionOpen:false
    property bool sidePanelOpen:true
    property string query:""
    property string chain:""
    property string accountFilter:""
    property string accountRoleFilter:""
    property var accountRoles:({})
    property var accountRoleDetails:[]
    property string accountRoleError:""
    property string roleManagerAccountId:""
    readonly property bool accountRoleEditingAvailable:!!surfaceHost && !!surfaceHost.walletSetAccountRole
    readonly property var accountFilterChoices:[{id:"",role:"",name:"Alla konton"}]
        .concat(accountRoleEditingAvailable ? [{id:"",role:"TRADING",name:"Trading"},{id:"",role:"STORAGE",name:"Förvaring"}] : [])
        .concat((wallet.accounts || []).map(function(a){return {id:a.id,role:"",name:(root.accountRoleEditingAvailable && root.accountRoles[a.id] ? root.roleName(root.accountRoles[a.id])+" · " : "")+a.label}}))
    readonly property string selectedAccountRole:accountRoleFilter || accountRoles[accountFilter] || ""
    property string connectChainId:""
    property string pendingExternalPurpose:""
    property string pendingExternalAddress:""
    property string pendingExternalChain:""
    property var selected:({})
    property string lastStatus:""
    property var tokenColors:({})
    property string tokenColorError:""
    readonly property bool tokenColorEditingAvailable:!!surfaceHost && !!surfaceHost.walletSetTokenColor
    readonly property var allocation:buildAllocation()
    readonly property var wallet:state.wallet_overview || ({})
    readonly property var operation:state.ui_operation || ({})
    readonly property bool busy:operation.state==="running"
    readonly property bool approvalPending:operation.state==="approval_required"
    readonly property bool dockAvailable:dashboard && width>=820
    readonly property bool railVisible:dockAvailable && sidePanelOpen && !showLab && !showActivity
    readonly property bool detailsVisible:railVisible || walletFactsDrawer.visible
    readonly property real edgeInset:compactPopup ? 8 : width>=1200 ? 28 : 16
    readonly property real railGap:width>=1200 ? 28 : 16
    readonly property real railWidth:Math.max(256,Math.min(450,width*.28))
    readonly property real mainWidth:Math.max(0,width-edgeInset-(railVisible ? railWidth+railGap : edgeInset))
    readonly property real overviewScale:dashboard ? Math.min(1,Math.max(.62,width/1586)) : compactPopup ? .7 : 1
    readonly property bool tableWide:dashboard && mainWidth>=600
    readonly property bool headerInline:mainWidth>=(dashboard ? 600 : 700)
    readonly property real overviewRowHeight:compactPopup ? 52 : dashboard ? Math.max(tableWide ? 40 : 56,Math.round(66*overviewScale)) : 76
    readonly property real overviewIconSize:compactPopup ? 28 : dashboard ? Math.round(40*overviewScale) : 40
    readonly property real amountFontSize:compactPopup ? 11 : dashboard ? Math.max(10,Math.round(15*overviewScale)) : 15
    readonly property real narrowNameFraction:compactPopup ? .44 : .57
    readonly property real overviewHeaderBottom:compactPopup ? (popupHeader.visible ? popupHeader.y+popupHeader.height : 0) : (header.visible ? header.y+header.height : 0)
    readonly property var transfers:state.wallet_transfers || []
    readonly property var publicNetworks:(wallet.networks || []).filter(function(n){return n.family!=="gglab"})
    readonly property var rows:(showLab ? wallet.lab_rows || [] : wallet.rows || []).filter(function(r){return root.positionInScope(r) && (root.showLab || root.showZero || r.atomic===null || r.atomic===undefined || !/^0+$/.test(String(r.atomic))) && (!root.query || (r.symbol+" "+r.name+" "+r.network).toLowerCase().indexOf(root.query.toLowerCase())>=0)}).sort(function(a,b){if(a.value_usd!==null && a.value_usd!==undefined && b.value_usd!==null && b.value_usd!==undefined)return Format.compareExact(b.value_usd,a.value_usd);if(a.value_usd!==null && a.value_usd!==undefined)return -1;if(b.value_usd!==null && b.value_usd!==undefined)return 1;return String(a.symbol).localeCompare(String(b.symbol))})
    readonly property bool noAccounts:!showLab && (wallet.accounts || []).length===0
    readonly property var scopedAccounts:(wallet.accounts || []).filter(function(a){return (!root.accountFilter || a.id===root.accountFilter) && (!root.chain || a.chain_id===root.chain) && (!root.accountRoleFilter || root.accountRoles[a.id]===root.accountRoleFilter)})
    readonly property var summary:accountRoleFilter ? roleScopeSummary() : accountFilter ? (scopedAccounts.length ? (wallet.account_summaries || {})[accountFilter] || ({}) : ({})) : chain ? (wallet.network_summaries || {})[chain] || ({}) : wallet.summary || wallet
    readonly property string readStatus:summary.failed_count ? summary.failed_count+" läsfel" : summary.stale_count ? summary.stale_count+" äldre saldon" : summary.unread_count ? summary.unread_count+" ej hämtade" : summary.last_read_at ? "Saldon lästa" : "Inget läst saldo"
    readonly property bool listVisible:!detailOpen && !showActivity && !connectOpen && !actionOpen && (!noAccounts || dashboard || compactPopup)
    signal toolsRequested()
    signal marketRequested()
    signal assetRequested(string assetId)
    signal workspaceRequested()
    TokenColorPicker { property string uiColorScope: "ui.widget.OmniWalletPanel.TokenColorPicker.1";id:colorPicker;onColorChosen:function(assetId,color){root.saveTokenColor(assetId,color)}}
    Popup {
        id:accountRoleManager;objectName:"walletAccountRoleManager"
        x:Math.max(6,(root.width-width)/2);y:Math.max(8,Math.min(80,root.height-height-8))
        width:Math.min(310,root.width-12);padding:12;focus:true
        closePolicy:Popup.CloseOnEscape|Popup.CloseOnPressOutside
        background:Rectangle {color:RuntimeTheme.GGTheme.panel;border.color:RuntimeTheme.GGTheme.edge;radius:3}
        contentItem:Column {
            spacing:9
            Label { colorKey: "ui.OmniWalletPanel.1";width:parent.width;text:"KONTOROLL";color:RuntimeTheme.GGTheme.bright}
            CryptoPick { property string uiColorScope: "ui.control.OmniWalletPanel.1";
                objectName:"walletRoleAccount";width:parent.width;height:30
                model:[{id:"",name:"Välj konto"}].concat((root.wallet.accounts || []).map(function(a){return {id:a.id,name:a.label}}))
                textRole:"name"
                currentIndex:{for(var i=0;i<model.length;i++)if(model[i].id===root.roleManagerAccountId)return i;return 0}
                onActivated:root.roleManagerAccountId=model[currentIndex].id
            }
            Row {width:parent.width;spacing:6
                Action { property string uiColorScope: "ui.control.OmniWalletPanel.2";objectName:"walletAssignTrading";width:(parent.width-6)/2;text:"Trading";enabled:!!root.roleManagerAccountId;onClicked:root.saveAccountRole(root.roleManagerAccountId,"TRADING")}
                Action { property string uiColorScope: "ui.control.OmniWalletPanel.3";objectName:"walletAssignStorage";width:(parent.width-6)/2;text:"Förvaring";enabled:!!root.roleManagerAccountId;onClicked:root.saveAccountRole(root.roleManagerAccountId,"STORAGE")}
            }
            Label { colorKey: "ui.OmniWalletPanel.2";width:parent.width;text:root.roleManagerAccountId ? root.roleName(root.accountRoles[root.roleManagerAccountId])+" · "+root.accountSigningLabel(root.roleManagerAccountId) : "Välj kontot som ska få rollen.";wrapMode:Text.WordWrap;elide:Text.ElideNone;color:RuntimeTheme.GGTheme.muted}
            Label { colorKey: "ui.OmniWalletPanel.3";width:parent.width;text:"Trading och Förvaring beskriver användningen. Nyckelmetoden väljs separat. En krypterad nyckel på den här datorn är online; rollen Förvaring gör den inte fysiskt kall.";wrapMode:Text.WordWrap;elide:Text.ElideNone;font.pixelSize:10;color:RuntimeTheme.GGTheme.muted}
            Label { colorKey: "ui.OmniWalletPanel.4";width:parent.width;visible:!!root.accountRoleError;text:root.accountRoleError;wrapMode:Text.WordWrap;elide:Text.ElideNone;color:RuntimeTheme.GGTheme.negative}
            Action { property string uiColorScope: "ui.control.OmniWalletPanel.4";text:"Klart";onClicked:accountRoleManager.close()}
        }
    }
    function roleName(role){return role==="TRADING" ? "Trading" : role==="STORAGE" ? "Förvaring" : "Ej tilldelat"}
    function positionInScope(row){return (!root.chain || row.chain_id===root.chain) && (!root.accountFilter || row.account_id===root.accountFilter) && (!root.accountRoleFilter || root.accountRoles[row.account_id]===root.accountRoleFilter)}
    function selectAccountScope(choice){accountFilter=choice.id || "";accountRoleFilter=choice.role || ""}
    function accountScopeIndex(){for(var i=0;i<accountFilterChoices.length;i++)if(accountFilterChoices[i].id===accountFilter && accountFilterChoices[i].role===accountRoleFilter)return i;return 0}
    function accountHasLocalKey(id){return (wallet.local_wallets || []).some(function(key){return key.account_id===id}) || accountRoleDetails.some(function(row){return row.account_id===id && ["LOCAL_ENCRYPTED","LOCAL_KEY_UNAVAILABLE"].indexOf(row.signer_state)>=0})}
    function accountSigningLabel(id){var key=(wallet.local_wallets || []).filter(function(key){return key.account_id===id})[0];if(key)return key.vault_available===true ? "lokal krypterad nyckel · online" : "lokal nyckel otillgänglig";var detail=accountRoleDetails.filter(function(row){return row.account_id===id})[0] || ({});return detail.signer_state==="LOCAL_ENCRYPTED" ? "lokal krypterad nyckel · online" : detail.signer_state==="LOCAL_KEY_UNAVAILABLE" ? "lokal nyckel otillgänglig" : "extern signering / bevakning"}
    function applyAccountRoles(raw){
        try {
            var value=typeof raw==="string" ? JSON.parse(raw) : raw
            if(!value || value.error){accountRoleError="Kontorollen kunde inte läsas eller ändras.";return}
            if(value.schema!=="gg.wallet-account-roles.v1" || !value.roles || Array.isArray(value.roles) || !Array.isArray(value.accounts) || Object.keys(value.roles).length>128 || value.accounts.length>128)return
            var clean=({});Object.keys(value.roles).forEach(function(id){if(["TRADING","STORAGE"].indexOf(value.roles[id])>=0)clean[id]=value.roles[id]})
            accountRoles=clean;accountRoleDetails=value.accounts;accountRoleError=""
        }catch(error){accountRoleError="Kontorollen kunde inte läsas eller ändras."}
    }
    function loadAccountRoles(){if(surfaceHost && surfaceHost.walletAccountRoles)applyAccountRoles(surfaceHost.walletAccountRoles())}
    function saveAccountRole(id,role){if(accountRoleEditingAvailable && id){try{applyAccountRoles(surfaceHost.walletSetAccountRole(id,role))}catch(error){accountRoleError="Kontorollen kunde inte ändras."}}}
    function openRoleManager(){loadAccountRoles();roleManagerAccountId=accountFilter || selected.account_id || "";accountRoleManager.open()}
    function openRoleMove(targetRole,row){
        if(busy || approvalPending || ["TRADING","STORAGE"].indexOf(targetRole)<0)return
        row=row || selected || ({})
        var source=row.account_id || accountFilter || (scopedAccounts.length===1 ? scopedAccounts[0].id : "")
        actionOpen=true;detailOpen=false;connectOpen=false;showActivity=false
        walletActions.openOwnMove(targetRole,source,row.asset_id || "")
    }
    function addExactValue(a,b){
        var left=a.split("."),right=b.split("."),precision=Math.max((left[1] || "").length,(right[1] || "").length)
        var x=left[0]+(left[1] || "").padEnd(precision,"0"),y=right[0]+(right[1] || "").padEnd(precision,"0")
        var width=Math.max(x.length,y.length);x=x.padStart(width,"0");y=y.padStart(width,"0")
        var carry=0,digits=""
        for(var i=width-1;i>=0;i--){var n=x.charCodeAt(i)+y.charCodeAt(i)-96+carry;digits=String(n%10)+digits;carry=Math.floor(n/10)}
        if(carry)digits=String(carry)+digits
        digits=digits.replace(/^0+/,"") || "0"
        if(!precision)return digits
        digits=digits.padStart(precision+1,"0");return digits.slice(0,-precision)+"."+digits.slice(-precision)
    }
    function roleScopeSummary(){
        var positions=(wallet.rows || []).filter(function(row){return root.positionInScope(row)}),total="0",priced=0,failed=0,unread=0,stale=0,last=0,networks=({})
        for(var i=0;i<positions.length;i++){
            var row=positions[i]
            if(typeof row.value_usd==="string" && Format.exactQuantity(row.value_usd)!=="—"){total=addExactValue(total,row.value_usd);priced++}
            if(row.balance_state==="READ_FAILED")failed++
            if(row.balance_state==="NOT_FETCHED")unread++
            if(row.balance_state==="VERIFIED_READ" && !row.balance_current)stale++
            if(row.balance_state==="VERIFIED_READ")last=Math.max(last,Number(row.observed_at || 0))
        }
        scopedAccounts.forEach(function(account){networks[account.chain_id]=true})
        return {known_value_usd:priced ? total : null,priced_count:priced,unpriced_count:positions.length-priced,position_count:positions.length,account_count:scopedAccounts.length,network_count:Object.keys(networks).length,failed_count:failed,unread_count:unread,stale_count:stale,last_read_at:last}
    }
    function priceProvenance(row){
        var observed=Number(row.price_source_timestamp || row.price_observed_at || 0)
        var text="Priskälla: "+String(row.price_source || "saknas")+" · "+String(row.price_quality || row.price_state || "okänd kvalitet")
        if(observed>0 && isFinite(observed))text+="\nPrisets tid: "+new Date(observed*1000).toLocaleString(Qt.locale())
        if(row.price_basis)text+="\nPrisunderlag: "+String(row.price_basis)
        if(row.liquidity_usd!==null && row.liquidity_usd!==undefined)text+="\nLikviditet: "+Format.money(row.liquidity_usd)
        if(row.price_stale===true)text+=" · äldre prisdata"
        return text
    }
    function openAccountMenu(){accountMenu.open()}
    function applyTokenColors(raw){
        try {
            var value=typeof raw==="string" ? JSON.parse(raw) : raw
            if(!value || typeof value!=="object" || Array.isArray(value))return
            if(value.error){tokenColorError="Färgen kunde inte sparas.";return}
            if(value.schema!=="gg.wallet-token-colors.v1" || !value.colors || Array.isArray(value.colors) || typeof value.colors!=="object")return
            var keys=Object.keys(value.colors)
            if(keys.length>2048)return
            var clean=({})
            for(var i=0;i<keys.length;i++)if(RuntimeTheme.GGTheme.validColor(value.colors[keys[i]]))clean[keys[i]]=value.colors[keys[i]].toLowerCase()
            tokenColors=clean;tokenColorError=""
        }catch(error){tokenColorError="Färgerna kunde inte läsas."}
    }
    function loadTokenColors(){if(surfaceHost && surfaceHost.walletTokenColors)applyTokenColors(surfaceHost.walletTokenColors())}
    function tokenColor(row){var key=String(row.asset_id || "");return RuntimeTheme.GGColorContext.colorFor("ui.asset."+key,tokenColors[key] || RuntimeTheme.GGTheme.defaultColor(key))}
    function editTokenColor(row){if(tokenColorEditingAvailable && row && row.asset_id && !showLab)colorPicker.showFor(row.asset_id,String(row.symbol || "Tillgång"),tokenColor(row))}
    function saveTokenColor(assetId,color){
        if(!tokenColorEditingAvailable || !RuntimeTheme.GGTheme.validColor(color))return
        try{applyTokenColors(surfaceHost.walletSetTokenColor(assetId,color))}catch(error){tokenColorError="Färgen kunde inte sparas."}
    }
    function buildAllocation(){
        if(showLab)return {segments:[],description:"Lokala labbtillgångar saknar marknadsvärdering.",unpricedCount:0,valuedCount:0}
        var positions=(wallet.rows || []).filter(function(row){return root.positionInScope(row)})
        var byColor=({}),byAsset=({}),total=0,unpriced=0,valued=0
        for(var i=0;i<positions.length;i++){
            var row=positions[i],value=Number(row.value_usd)
            if(row.value_usd===null || row.value_usd===undefined || !isFinite(value) || value<0){unpriced++;continue}
            if(value===0)continue
            var color=tokenColor(row)
            total+=value;valued++
            byColor[color]=(byColor[color] || 0)+value
            var id=String(row.asset_id || "")
            if(!byAsset[id])byAsset[id]={symbol:String(row.symbol || "Tillgång"),value:0}
            byAsset[id].value+=value
        }
        var segments=[],start=0,colors=Object.keys(byColor)
        if(total>0 && isFinite(total))for(var c=0;c<colors.length;c++){
            var fraction=byColor[colors[c]]/total
            segments.push({color:colors[c],start:start,fraction:fraction});start+=fraction
        }
        var lines=[total>0 ? "Fördelning av värderad del" : "Inga värderade tillgångar"]
        Object.keys(byAsset).slice(0,64).forEach(function(id){lines.push(byAsset[id].symbol+" · "+(byAsset[id].value/total*100).toFixed(1)+" %")})
        if(Object.keys(byAsset).length>64)lines.push("Fler värderade tillgångar ingår i bågen.")
        if(unpriced)lines.push(unpriced+" ej prissatta positioner ingår inte i fördelningen.")
        return {segments:segments,description:lines.join("\n"),unpricedCount:unpriced,valuedCount:valued}
    }
    function apply(raw){if(raw===lastStatus)return;try{var value=JSON.parse(raw);if(value && value.assets){lastStatus=raw;state=value;if(selected.id)selected=rows.filter(function(r){return r.id===root.selected.id})[0] || ({});if(operation.name==="connect_watch" && operation.state==="done"){connectOpen=false;finishExternalPurpose()}}}catch(e){}}
    function finishExternalPurpose(){
        if(!pendingExternalPurpose || !pendingExternalAddress || !pendingExternalChain)return
        var matches=(wallet.accounts || []).filter(function(a){return a.chain_id===root.pendingExternalChain && (a.chain_id.indexOf("eip155:")===0 ? a.address.toLowerCase()===root.pendingExternalAddress.toLowerCase() : a.address===root.pendingExternalAddress)})
        if(matches.length===1){saveAccountRole(matches[0].id,pendingExternalPurpose);pendingExternalPurpose="";pendingExternalAddress="";pendingExternalChain=""}
    }
    function pull(){if(visible && surfaceHost && surfaceHost.omniStatus)apply(surfaceHost.omniStatus())}
    function run(name,args){if(!busy && !approvalPending && surfaceHost && surfaceHost.omniAction)apply(surfaceHost.omniAction(name,JSON.stringify(args || {})))}
    function choose(row){
        if(approvalPending){actionOpen=true;detailOpen=false;connectOpen=false;showActivity=false;return}
        if(busy || !row)return
        if(row.scope==="LOCAL_LAB"){
            var lab=(wallet.lab_rows || []).filter(function(r){return r.id===row.id && r.asset_id===row.asset_id})[0]
            if(lab){selected=lab;detailOpen=true;actionOpen=false}
            return
        }
        var position=(wallet.rows || []).filter(function(r){return r.account_id===row.account_id && r.asset_id===row.asset_id && (!row.id || r.id===row.id)})[0]
        var account=(wallet.accounts || []).filter(function(a){return position && a.id===position.account_id})[0]
        var asset=(state.assets || []).filter(function(a){return position && a.id===position.asset_id})[0]
        if(!position || !account || !asset || account.chain_id!==asset.chain_id || position.chain_id!==asset.chain_id)return
        selected=position;openActions("receive",position);run("select_asset",{id:position.asset_id})
    }
    function openActions(mode,row){if(approvalPending){actionOpen=true;return}if(busy)return;row=row || ({});actionOpen=true;detailOpen=false;connectOpen=false;showActivity=false;walletActions.open(mode,row.account_id || accountFilter || "",row.asset_id || "")}
    function assetInfo(row){return (state.assets || []).filter(function(a){return a.id===row.asset_id})[0] || ({})}
    function copyAddress(){if(selected.address && surfaceHost && surfaceHost.tmogCopy)surfaceHost.tmogCopy(selected.address)}
    function toggleDetails(){if(dockAvailable && !showLab && !showActivity){walletFactsDrawer.close();sidePanelOpen=!sidePanelOpen}else if(walletFactsDrawer.visible)walletFactsDrawer.close();else walletFactsDrawer.open()}
    function openActivity(){walletFactsDrawer.close();showActivity=true}
    function refreshOverview(){if(scopedAccounts.length)run("refresh_wallet",{account_ids:scopedAccounts.map(function(a){return a.id})})}
    function operationError(){return ({OMNI_WALLET_REFRESH_LIMIT:"Välj ett konto eller en tillgång för en mindre saldouppdatering.",OMNI_WALLET_REFRESH_PARTIAL:"Vissa saldon eller priser kunde inte uppdateras. Kontrollera aktivitetsloggen.",WALLET_APPROVAL_REQUIRED:"Åtgärden behöver godkännas med ja i chatten innan den kan utföras.",WALLET_BACKUP_REQUIRED:"Säkerhetskopiera den krypterade walleten först.",WALLET_INSUFFICIENT_SOL_FOR_FEE:"GG-kontot behöver mer SOL till nätverksavgift och eventuell kontohyra.",WALLET_INSUFFICIENT_TOKEN_BALANCE:"Otillräckligt tillgängligt tokensaldo på GG-kontot.",WALLET_DRAFT_EXPIRED:"Offerten har löpt ut. Förbered överföringen på nytt.",WALLET_TOKEN_TRANSFER_ADAPTER_REQUIRED:"Tokenets överföringsregler saknar ännu en verifierad sändningsadapter.",WALLET_BROADCAST_NOT_CONFIRMED:"Utfallet är okänt. Kontrollera signaturen; skapa ingen ny överföring ännu.",WALLET_BACKUP_INVALID_OR_WRONG_PASSWORD:"Backupen kunde inte verifieras med detta lösenord."})[operation.error] || String(operation.error || "")}
    function balanceLabel(row){return ({NOT_FETCHED:"Saldo ej hämtat",READ_FAILED:"Läsning misslyckades",LOCAL_LEDGER_VERIFIED:"Lokalt labb",VERIFIED_READ:row.balance_current ? "Läst från källa" : "Äldre saldo"})[row.balance_state] || row.balance_state || ""}
    Component.onCompleted:{pull();loadTokenColors();loadAccountRoles()}
    onSurfaceHostChanged:{loadTokenColors();loadAccountRoles()}
    onAccountRoleFilterChanged:selected=({})
    onAccountFilterChanged:selected=({})
    onVisibleChanged:if(visible)pull()
    onDockAvailableChanged:if(dockAvailable && walletFactsDrawer.visible){sidePanelOpen=true;walletFactsDrawer.close()}
    onShowLabChanged:{selected=({});detailOpen=false;connectOpen=false;actionOpen=false;showActivity=false;chain="";accountFilter="";accountRoleFilter=""}
    Connections {target:root.surfaceHost;ignoreUnknownSignals:true;function onOmniStatusUpdated(raw){if(root.visible)root.apply(raw)}}
    Connections {target:root.surfaceHost;ignoreUnknownSignals:true;function onWalletTokenColorsUpdated(raw){root.applyTokenColors(raw)}}
    Connections {target:root.surfaceHost;ignoreUnknownSignals:true;function onWalletAccountRolesUpdated(raw){root.applyAccountRoles(raw)}}
    Timer {interval:root.busy || !root.state.assets ? 200 : 3000;repeat:true;running:root.visible;onTriggered:root.pull()}
    component Label:GGText {color:RuntimeTheme.GGTheme.text;font.family:"monospace";font.pixelSize:11;textFormat:Text.PlainText;elide:Text.ElideRight}
    component Action:CryptoButton {font.pixelSize:10;enabled:!root.busy && !root.approvalPending}
    Column {id:header;objectName:root.compactPopup ? "" : "walletOverviewHeader";x:root.edgeInset;y:root.dashboard ? Math.round(36*root.overviewScale) : 22;width:root.mainWidth;spacing:0;visible:!root.compactPopup && !root.detailOpen && !root.actionOpen
        Item {width:parent.width;height:Math.max(Math.round(100*root.overviewScale),Math.max(totalColumn.height,headerControls.y+headerControls.height)+Math.round(12*root.overviewScale))
            Column {id:totalColumn;width:root.headerInline ? Math.round(250*root.overviewScale) : parent.width;spacing:Math.round(5*root.overviewScale)
                Label { colorKey: "ui.OmniWalletPanel.5";objectName:root.compactPopup ? "" : "walletTotalValue";width:parent.width;text:root.showLab ? "GG-LAB" : root.summary.known_value_usd===null || root.summary.known_value_usd===undefined ? "\u2014" : Format.exactMoney(root.summary.known_value_usd);color:RuntimeTheme.GGTheme.bright;font.pixelSize:root.dashboard ? Math.round(48*root.overviewScale) : 32;font.bold:true}
                Label { colorKey: "ui.OmniWalletPanel.6";width:parent.width;text:root.showLab ? "Separata sessionstillgångar" : "Värderad del av innehaven";color:RuntimeTheme.GGTheme.text;font.pixelSize:Math.max(10,Math.round(14*root.overviewScale))}
            }
            Flow {id:headerControls;x:root.headerInline ? totalColumn.width+Math.round(20*root.overviewScale) : 0;y:root.headerInline ? Math.round(6*root.overviewScale) : totalColumn.height+Math.round(12*root.overviewScale);width:parent.width-x;spacing:Math.round(10*root.overviewScale)
                Action { property string uiColorScope: "ui.control.OmniWalletPanel.5";objectName:root.compactPopup ? "" : "walletPublicHoldings";width:Math.max(140,180*root.overviewScale);height:Math.round(44*root.overviewScale);text:"← Publika innehav";visible:root.showLab;onClicked:root.showLab=false}
                CryptoPick { property string uiColorScope: "ui.control.OmniWalletPanel.6";objectName:root.compactPopup ? "" : "walletAccountFilter";width:Math.max(146,Math.round(190*root.overviewScale));height:Math.round(44*root.overviewScale);font.pixelSize:Math.max(10,Math.round(13*root.overviewScale));visible:!root.showLab && !root.noAccounts;model:root.accountFilterChoices;textRole:"name";currentIndex:root.accountScopeIndex();onActivated:root.selectAccountScope(model[currentIndex])}
                Action { property string uiColorScope: "ui.control.OmniWalletPanel.7";objectName:root.compactPopup ? "" : "walletReceive";width:Math.max(76,Math.round(110*root.overviewScale));height:Math.round(44*root.overviewScale);font.pixelSize:Math.max(10,Math.round(13*root.overviewScale));text:"↓ Ta emot";visible:!root.showLab && !root.noAccounts;onClicked:root.openActions("receive")}
                Action { property string uiColorScope: "ui.control.OmniWalletPanel.8";objectName:root.compactPopup ? "" : "walletRefreshOverview";width:Math.max(86,Math.round(120*root.overviewScale));height:Math.round(44*root.overviewScale);font.pixelSize:Math.max(10,Math.round(13*root.overviewScale));text:root.busy ? "Läser…" : "↻ Uppdatera";visible:!root.showLab && !root.noAccounts;enabled:!root.busy && !root.approvalPending && root.scopedAccounts.length>0;tip:"Läs saldon och identitetsbundna priser för valda konton";onClicked:root.refreshOverview()}
                Label { colorKey: "ui.OmniWalletPanel.7";width:Math.min(Math.max(210,Math.round(285*root.overviewScale)),parent.width);height:root.overviewScale<.85 ? Math.max(18,implicitHeight) : 44;verticalAlignment:Text.AlignVCenter;text:root.showLab ? "GG-labb \u00b7 sessionstillgångar" : (root.summary.account_count || 0)+" konton  │ "+(root.summary.network_count || 0)+" nätverk  │ "+(root.summary.unpriced_count || 0)+" värden saknas";color:RuntimeTheme.GGTheme.muted;font.pixelSize:Math.max(9,Math.round(12*root.overviewScale));wrapMode:Text.WordWrap;elide:Text.ElideNone}
                BusyIndicator {width:18;height:18;running:root.busy;visible:running}
            }
        }
        Rectangle {width:parent.width;height:1;color:RuntimeTheme.GGTheme.line}
        Flow {width:parent.width;spacing:6;topPadding:Math.round(9*root.overviewScale);bottomPadding:Math.round(9*root.overviewScale);visible:!root.showLab
            CryptoField { property string uiColorScope: "ui.widget.OmniWalletPanel.CryptoField.10";objectName:root.compactPopup ? "" : "walletAssetSearch";width:parent.width<500 ? parent.width : parent.width-(root.transfers.length>0 ? 242 : 196);height:Math.max(26,Math.round(36*root.overviewScale));font.pixelSize:Math.max(10,Math.round(13*root.overviewScale));placeholderText:"⌕  Sök tillgång, symbol eller nätverk …";onTextChanged:root.query=text;background:Rectangle {color:"transparent"}}
            CryptoPick { property string uiColorScope: "ui.control.OmniWalletPanel.9";width:126;height:Math.max(26,Math.round(36*root.overviewScale));font.pixelSize:Math.max(10,Math.round(12*root.overviewScale));model:[{id:"",name:"Nätverk: alla"}].concat(root.publicNetworks.map(function(n){return {id:n.id,name:n.name}}));textRole:"name";currentIndex:{for(var i=0;i<model.length;i++)if(model[i].id===root.chain)return i;return 0} onActivated:root.chain=model[currentIndex].id;background:Rectangle {color:"transparent";border.color:RuntimeTheme.GGTheme.line}}
            Action { property string uiColorScope: "ui.control.OmniWalletPanel.10";implicitWidth:26;width:26;height:Math.max(26,Math.round(36*root.overviewScale));text:"+";tip:"Lägg till eller skapa wallet";onClicked:accountMenu.open()}
            Action { property string uiColorScope: "ui.control.OmniWalletPanel.11";objectName:root.compactPopup ? "" : "walletTools";implicitWidth:26;width:26;height:Math.max(26,Math.round(36*root.overviewScale));text:"⋯";tip:"Konton, överföringar, labb och aktivitet";onClicked:walletTools.open()}
            Action { property string uiColorScope: "ui.control.OmniWalletPanel.12";objectName:root.compactPopup ? "" : "walletTransferHistory";width:40;implicitWidth:40;height:Math.max(26,Math.round(36*root.overviewScale));text:"↗ "+root.transfers.length;tip:"Överföringar · "+root.transfers.length;visible:!root.showLab && root.transfers.length>0;onClicked:root.openActions("history")}
        }
        Rectangle {width:parent.width;height:1;color:RuntimeTheme.GGTheme.line}
        Label { colorKey: "ui.OmniWalletPanel.8";width:parent.width;visible:root.wallet.truncated===true;text:"Visar "+root.wallet.displayed_positions+" av "+root.wallet.position_count+" positioner \u00b7 värdet är en delsumma";color:RuntimeTheme.GGTheme.accent;font.pixelSize:12;wrapMode:Text.WordWrap;elide:Text.ElideNone}
    }
    Loader {id:popupHeader;objectName:root.compactPopup ? "walletOverviewHeader" : "";active:root.compactPopup;x:root.edgeInset;y:4;width:root.mainWidth;height:item ? item.implicitHeight : 0;visible:root.compactPopup && !root.detailOpen && !root.actionOpen && !root.showActivity && !root.connectOpen;sourceComponent:WalletCompactHeader { property string uiColorScope: "ui.widget.OmniWalletPanel.WalletCompactHeader.15";walletPanel:root}}
    Label { colorKey: "ui.OmniWalletPanel.9";id:operationError;objectName:"walletOperationError";x:root.edgeInset;y:root.overviewHeaderBottom>0 ? root.overviewHeaderBottom+8 : 12;width:root.mainWidth;visible:!!root.operation.error || !!root.tokenColorError || !!root.accountRoleError;text:root.accountRoleError || root.tokenColorError || root.operationError();color:RuntimeTheme.GGTheme.negative;wrapMode:Text.WordWrap;elide:Text.ElideNone}
    WalletTelemetry { property string uiColorScope: "ui.widget.OmniWalletPanel.WalletTelemetry.16";objectName:"walletFactsRail";x:root.edgeInset+root.mainWidth+root.railGap;width:root.railWidth;height:parent.height;visible:root.railVisible;state:root.state;accounts:root.scopedAccounts;accountId:root.actionOpen ? walletActions.accountId : root.detailOpen ? root.selected.account_id || "" : root.accountFilter;chainId:root.chain;showAccounts:!root.actionOpen && !root.detailOpen;onAccountRequested:function(id){root.accountFilter=id} onActivityRequested:root.openActivity()}
    Item {objectName:"walletPrimaryContent";x:root.edgeInset;y:(root.overviewHeaderBottom>0 ? root.overviewHeaderBottom+(root.compactPopup ? 4 : Math.round(18*root.overviewScale)) : root.compactPopup ? 4 : 24)+(operationError.visible ? operationError.height+20 : 0);height:Math.max(0,parent.height-y-(compactFooter.visible ? compactFooter.height+8 : 0));width:root.mainWidth
        Row {id:listHead;width:parent.width;height:Math.max(24,Math.round(36*root.overviewScale));visible:root.listVisible;spacing:0
            Label { colorKey: "ui.OmniWalletPanel.10";width:parent.width*(root.tableWide ? .27 : root.narrowNameFraction);text:"TILLGÅNG / NÄTVERK";color:RuntimeTheme.GGTheme.muted;font.pixelSize:Math.max(9,Math.round(13*root.overviewScale))}
            Label { colorKey: "ui.OmniWalletPanel.11";width:parent.width*.19;visible:root.tableWide;text:"SALDO";color:RuntimeTheme.GGTheme.muted;font.pixelSize:Math.max(9,Math.round(13*root.overviewScale))}
            Label { colorKey: "ui.OmniWalletPanel.12";width:parent.width*.18;visible:root.tableWide;text:"PRIS";color:RuntimeTheme.GGTheme.muted;font.pixelSize:Math.max(9,Math.round(13*root.overviewScale))}
            Label { colorKey: "ui.OmniWalletPanel.13";width:parent.width*(root.tableWide ? .14 : 1-root.narrowNameFraction)-8;text:root.tableWide ? "VÄRDE" : "VÄRDE / SALDO";horizontalAlignment:root.compactPopup ? Text.AlignRight : Text.AlignLeft;color:RuntimeTheme.GGTheme.muted;font.pixelSize:Math.max(9,Math.round(13*root.overviewScale))}
            Label { colorKey: "ui.OmniWalletPanel.14";width:parent.width*.22+8;visible:root.tableWide;text:"7 DAGAR / 24 H";horizontalAlignment:Text.AlignRight;color:RuntimeTheme.GGTheme.muted;font.pixelSize:Math.max(9,Math.round(12*root.overviewScale))}
        }
        ListView {id:positions;objectName:"walletPositionList";anchors.top:listHead.bottom;anchors.bottom:parent.bottom;width:parent.width;clip:true;spacing:0;model:root.rows;visible:root.listVisible;cacheBuffer:80;ScrollBar.vertical:ScrollBar {}
            delegate:Rectangle {
                id:position;required property var modelData;required property int index;readonly property var identity:root.assetInfo(modelData);readonly property string accountTarget:modelData.account_id || "";readonly property string assetTarget:modelData.asset_id || "";objectName:"walletAssetRow";width:positions.width;height:root.overviewRowHeight;color:walletMouse.containsMouse ? RuntimeTheme.GGTheme.hover : "transparent"
                Rectangle {anchors.top:parent.top;width:parent.width;height:1;color:RuntimeTheme.GGTheme.line;opacity:.65}
                AssetIcon { property string uiColorScope: "ui.widget.OmniWalletPanel.AssetIcon.17";x:2;anchors.verticalCenter:parent.verticalCenter;width:root.overviewIconSize;height:width;symbol:position.modelData.symbol || "";assetId:position.modelData.asset_id || "";chainId:position.modelData.chain_id || "";assetNamespace:position.identity.namespace || "";assetReference:position.identity.reference || "";sourceUrl:position.identity.image_url || ""}
                Column {id:tokenName;z:2;x:root.overviewIconSize+(root.compactPopup ? 9 : Math.round(20*root.overviewScale));anchors.verticalCenter:parent.verticalCenter;width:root.compactPopup ? Math.min(72,Math.max(50,parent.width*.25)) : Math.max(50,parent.width*(root.tableWide ? .27 : root.narrowNameFraction)-x-8);spacing:Math.round(4*root.overviewScale)
                    Row {width:parent.width;height:Math.max(18,tokenSymbol.implicitHeight);spacing:2
                        Label { colorKey: "ui.OmniWalletPanel.15";id:tokenSymbol;width:Math.min(implicitWidth,Math.max(0,parent.width-20));height:parent.height;verticalAlignment:Text.AlignVCenter;text:position.modelData.symbol;font.pixelSize:Math.max(11,Math.round(16*root.overviewScale));color:RuntimeTheme.GGTheme.bright}
                        CryptoButton { property string uiColorScope: "ui.control.OmniWalletPanel.13";
                            objectName:"walletTokenColorDot";z:2;width:18;height:18;implicitWidth:18;implicitHeight:18;padding:0
                            enabled:root.tokenColorEditingAvailable && !root.showLab
                            Accessible.name:"Välj färg för "+String(position.modelData.symbol || "tillgång")+" på "+String(position.modelData.network || "nätverket")
                            tip:Accessible.name
                            background:Item {
                                Rectangle {anchors.centerIn:parent;width:7;height:7;radius:4;color:root.tokenColor(position.modelData)}
                                Rectangle {anchors.fill:parent;anchors.margins:1;color:"transparent";border.width:parent.parent.visualFocus ? 1 : 0;border.color:RuntimeTheme.GGTheme.muted;radius:3}
                            }
                            onClicked:root.editTokenColor(position.modelData)
                            TapHandler {acceptedButtons:Qt.RightButton;onTapped:root.editTokenColor(position.modelData)}
                        }
                    }
                    Label { colorKey: "ui.OmniWalletPanel.16";width:parent.width;text:position.modelData.network+(position.modelData.balance_state==="READ_FAILED" ? " \u00b7 Läsfel" : "");font.pixelSize:Math.max(9,Math.round(12*root.overviewScale));color:position.modelData.balance_state==="READ_FAILED" ? RuntimeTheme.GGTheme.negative : RuntimeTheme.GGTheme.muted}
                    Label { colorKey: "ui.OmniWalletPanel.17";width:parent.width;visible:!root.tableWide && !root.compactPopup;text:root.showLab ? position.modelData.label : root.balanceLabel(position.modelData);font.pixelSize:10;color:RuntimeTheme.GGTheme.dim}
                }
                Label { colorKey: "ui.OmniWalletPanel.18";objectName:"walletRowBalance";x:parent.width*.27;height:parent.height;verticalAlignment:Text.AlignVCenter;width:parent.width*.19-8;visible:root.tableWide;text:Format.exactQuantity(position.modelData.quantity);font.pixelSize:root.amountFontSize}
                Label { colorKey: "ui.OmniWalletPanel.19";objectName:"walletRowPrice";x:parent.width*.46;height:parent.height;verticalAlignment:Text.AlignVCenter;width:parent.width*.18-8;visible:root.tableWide;text:position.modelData.price_usd===null || position.modelData.price_usd===undefined ? "Ej prissatt" : Format.money(position.modelData.price_usd);font.pixelSize:Math.max(10,Math.round(14*root.overviewScale))}
                Column {id:tokenAmounts;x:parent.width*(root.tableWide ? .64 : root.narrowNameFraction);anchors.verticalCenter:parent.verticalCenter;width:parent.width*(root.tableWide ? .14 : 1-root.narrowNameFraction)-8;spacing:Math.round(4*root.overviewScale)
                    readonly property real textWidth:Math.max(tokenValue.implicitWidth,tokenQuantity.visible ? tokenQuantity.implicitWidth : 0,tokenPending.visible ? tokenPending.implicitWidth : 0)
                    Label { colorKey: "ui.OmniWalletPanel.20";id:tokenValue;width:parent.width;text:position.modelData.value_usd===null || position.modelData.value_usd===undefined ? "\u2014" : Format.exactMoney(position.modelData.value_usd);horizontalAlignment:root.compactPopup ? Text.AlignRight : Text.AlignLeft;color:RuntimeTheme.GGTheme.bright;font.pixelSize:Math.max(11,root.amountFontSize)}
                    Label { colorKey: "ui.OmniWalletPanel.21";id:tokenQuantity;objectName:"walletCompactQuantity";width:parent.width;visible:!root.tableWide;text:Format.exactQuantity(position.modelData.quantity);horizontalAlignment:root.compactPopup ? Text.AlignRight : Text.AlignLeft;font.pixelSize:Math.max(10,Math.round(12*root.overviewScale))}
                    Label { colorKey: "ui.OmniWalletPanel.22";id:tokenPending;width:parent.width;visible:!!position.modelData.pending_atomic && position.modelData.pending_atomic!=="0";text:"Väntande förändring";color:RuntimeTheme.GGTheme.accent;font.pixelSize:10}
                }
                PriceSparkline { property string uiColorScope: "ui.widget.OmniWalletPanel.PriceSparkline.19";objectName:root.compactPopup ? "walletTokenSparkline" : "tokenSparkline";x:root.compactPopup ? tokenName.x+tokenName.width+8 : parent.width*.78;anchors.verticalCenter:parent.verticalCenter;width:root.compactPopup ? Math.max(0,tokenAmounts.x+tokenAmounts.width-tokenAmounts.textWidth-8-x) : Math.max(30,parent.width*.14);height:root.compactPopup ? 24 : Math.max(20,Math.round(34*root.overviewScale));visible:root.tableWide || root.compactPopup && !root.showLab && available && width>=28;samples:(position.modelData.sparkline || {}).prices || [];periodLabel:(position.modelData.sparkline || {}).period==="OBSERVED" ? "Observerad historik" : "7 dagar";sourceLabel:(position.modelData.sparkline || {}).source || "Prisdata för tillgången";stale:position.modelData.price_state!=="CURRENT"}
                Label { colorKey: "ui.OmniWalletPanel.23";x:parent.width*.92;height:parent.height;verticalAlignment:Text.AlignVCenter;width:parent.width*.08;visible:root.tableWide;text:Format.percent(position.modelData.change_24h);horizontalAlignment:Text.AlignRight;font.pixelSize:Math.max(10,Math.round(14*root.overviewScale));color:position.modelData.change_24h>0 ? RuntimeTheme.GGTheme.positive : position.modelData.change_24h<0 ? RuntimeTheme.GGTheme.negative : RuntimeTheme.GGTheme.muted}
                MouseArea {id:walletMouse;anchors.fill:parent;enabled:!root.busy;hoverEnabled:true;cursorShape:Qt.PointingHandCursor;onClicked:root.choose(position.modelData)}
                ToolTip.visible:walletMouse.containsMouse
                ToolTip.delay:500
                ToolTip.text:String(position.modelData.name || position.modelData.symbol)+" · "+root.balanceLabel(position.modelData)+"\n"+Format.exactQuantity(position.modelData.quantity)+" "+String(position.modelData.symbol || "")+"\n"+root.priceProvenance(position.modelData)
                activeFocusOnTab:true;Accessible.role:Accessible.Button;Accessible.name:modelData.symbol+" \u00b7 "+modelData.network+" \u00b7 "+root.balanceLabel(modelData);Keys.onReturnPressed:root.choose(modelData)
            }
            Column {anchors.horizontalCenter:parent.horizontalCenter;y:Math.min(50,parent.height/5);width:Math.min(440,parent.width-30);spacing:12;visible:positions.count===0
                Label { colorKey: "ui.OmniWalletPanel.24";width:parent.width;text:root.noAccounts ? "Dina tillgångar, en samlad översikt." : root.showLab ? "Ingen aktiv labbsession" : "Inga synliga tillgångar";font.pixelSize:16;color:RuntimeTheme.GGTheme.bright;wrapMode:Text.WordWrap;elide:Text.ElideNone}
                Label { colorKey: "ui.OmniWalletPanel.25";width:parent.width;text:root.noAccounts ? "Lägg till ett offentligt konto. Saldo och värde visas här när de har lästs från källorna." : root.showLab ? "Öppna Nätverk & labb för att skapa en session." : "Justera filtret, visa nollsaldo eller uppdatera dina saldon.";color:RuntimeTheme.GGTheme.muted;wrapMode:Text.WordWrap;elide:Text.ElideNone}
                Action { property string uiColorScope: "ui.control.OmniWalletPanel.14";text:"+ Lägg till / skapa wallet";visible:root.noAccounts;onClicked:accountMenu.open()}
            }
        }
        Flickable {anchors.fill:parent;clip:true;contentWidth:width;contentHeight:connectBody.height;visible:!root.showActivity && !root.actionOpen && !root.showLab && !root.detailOpen && ((root.noAccounts && !root.dashboard && !root.compactPopup) || root.connectOpen);ScrollBar.vertical:ScrollBar {}
            Column {id:connectBody;width:parent.width;spacing:12
                Label { colorKey: "ui.OmniWalletPanel.26";width:parent.width;text:"Läs ett offentligt konto";color:RuntimeTheme.GGTheme.bright;font.pixelSize:16}
                Label { colorKey: "ui.OmniWalletPanel.27";width:parent.width;text:"Välj nätverk och ange den publika adressen. Inga privata nycklar eller seedfraser behövs för bevakning.";wrapMode:Text.WordWrap;elide:Text.ElideNone;color:RuntimeTheme.GGTheme.muted;font.pixelSize:10}
                CryptoPick { property string uiColorScope: "ui.control.OmniWalletPanel.15";id:connectNetwork;objectName:"walletConnectNetwork";width:parent.width;model:root.publicNetworks;textRole:"name";Accessible.name:"Kontots nätverk";currentIndex:{var desired=root.connectChainId;if(!desired){var assets=root.state.assets || [];for(var a=0;a<assets.length;a++)if(assets[a].id===root.state.selected_asset){desired=assets[a].chain_id;break}}for(var i=0;i<model.length;i++)if(model[i].id===desired)return i;return model.length ? 0 : -1} onActivated:root.connectChainId=model[currentIndex].id}
                CryptoField { property string uiColorScope: "ui.widget.OmniWalletPanel.CryptoField.22";id:connectAddress;objectName:"walletConnectAddress";width:parent.width;placeholderText:"Offentlig adress";Accessible.name:placeholderText;maximumLength:180}
                CryptoField { property string uiColorScope: "ui.widget.OmniWalletPanel.CryptoField.23";id:connectLabel;width:parent.width;placeholderText:"Kontonamn (valfritt)";maximumLength:64}
                Flow {width:parent.width;spacing:6
                    Action { property string uiColorScope: "ui.control.OmniWalletPanel.16";objectName:"walletReadAccount";text:root.busy ? "Läser konto…" : "Lägg till & läs saldo";enabled:!root.busy && connectNetwork.currentIndex>=0 && connectAddress.text.trim().length>0;onClicked:{root.pendingExternalAddress=connectAddress.text.trim();root.pendingExternalChain=connectNetwork.model[connectNetwork.currentIndex].id;root.run("connect_watch",{chain_id:root.pendingExternalChain,address:root.pendingExternalAddress,label:connectLabel.text.trim()})}}
                    Action { property string uiColorScope: "ui.control.OmniWalletPanel.17";text:"Avbryt";visible:root.dashboard || root.compactPopup || !root.noAccounts;onClicked:root.connectOpen=false}
                }
                Label { colorKey: "ui.OmniWalletPanel.28";width:parent.width;text:"Publika konton är bevakning. Importera en token under Konton / token om den saknas i registret.";color:RuntimeTheme.GGTheme.dim;font.pixelSize:10;wrapMode:Text.WordWrap;elide:Text.ElideNone}
            }
        }
        SpaceActivityFeed { property string uiColorScope: "ui.widget.OmniWalletPanel.SpaceActivityFeed.26";objectName:"walletActivityFeed";anchors.fill:parent;visible:root.showActivity;events:root.wallet.events || [];onCloseRequested:root.showActivity=false}
        WalletActions { property string uiColorScope: "ui.widget.OmniWalletPanel.WalletActions.27";id:walletActions;anchors.fill:parent;visible:root.actionOpen && !root.showActivity;surfaceHost:root.surfaceHost;state:root.state;accountRoles:root.accountRoles;onCloseRequested:{walletActions.pendingAction="";root.actionOpen=false} onToolsRequested:root.toolsRequested();onFactsRequested:walletFactsDrawer.open();onAssetRequested:function(id){root.assetRequested(id)} onActionRequested:function(name,args){root.run(name,args)} onExternalWalletRequested:function(method,purpose){root.pendingExternalPurpose=purpose;root.actionOpen=false;root.detailOpen=false;root.connectOpen=true;connectLabel.text=method+" · "+root.roleName(purpose)}}
        Flickable {anchors.fill:parent;clip:true;contentWidth:width;contentHeight:detailBody.height;visible:root.detailOpen && !root.showActivity && !root.actionOpen;ScrollBar.vertical:ScrollBar {}
            Column {id:detailBody;width:parent.width;spacing:13
                Action { property string uiColorScope: "ui.control.OmniWalletPanel.18";text:"← Tillgångar";enabled:true;onClicked:root.detailOpen=false}
                Label { colorKey: "ui.OmniWalletPanel.29";width:parent.width;text:root.selected.symbol || "Tillgång";font.pixelSize:22;font.bold:true;color:RuntimeTheme.GGTheme.bright}
                Label { colorKey: "ui.OmniWalletPanel.30";width:parent.width;text:String(root.selected.quantity || "—")+" "+String(root.selected.symbol || "");font.pixelSize:20;color:RuntimeTheme.GGTheme.bright;wrapMode:Text.WrapAnywhere;elide:Text.ElideNone}
                Label { colorKey: "ui.OmniWalletPanel.31";width:parent.width;text:root.selected.value_usd===null || root.selected.value_usd===undefined ? "Värdering saknas" : "$"+root.selected.value_usd+" · uppskattat värde";color:RuntimeTheme.GGTheme.muted}
                Label { colorKey: "ui.OmniWalletPanel.32";width:parent.width;text:String(root.selected.label || "")+" · "+String(root.selected.network || "")+"\n"+root.balanceLabel(root.selected);color:RuntimeTheme.GGTheme.muted;wrapMode:Text.WordWrap;elide:Text.ElideNone}
                Label { colorKey: "ui.OmniWalletPanel.33";width:parent.width;visible:!!root.selected.pending_atomic && root.selected.pending_atomic!=="0";text:"Väntande förändring: "+root.selected.pending_atomic+" basenheter. Bekräftat saldo visas ovan.";color:RuntimeTheme.GGTheme.accent;wrapMode:Text.WrapAnywhere;elide:Text.ElideNone}
                Rectangle {width:parent.width;height:1;color:RuntimeTheme.GGTheme.line}
                Label { colorKey: "ui.OmniWalletPanel.34";text:"ADRESS / TA EMOT";font.pixelSize:9;color:RuntimeTheme.GGTheme.dim;font.letterSpacing:1}
                Label { colorKey: "ui.OmniWalletPanel.35";width:parent.width;text:root.selected.address || "";wrapMode:Text.WrapAnywhere;elide:Text.ElideNone;color:RuntimeTheme.GGTheme.muted}
                Flow {width:parent.width;spacing:6
                    Action { property string uiColorScope: "ui.control.OmniWalletPanel.19";text:"Ta emot";visible:root.selected.scope!=="LOCAL_LAB";onClicked:root.openActions("receive",root.selected)}
                    Action { property string uiColorScope: "ui.control.OmniWalletPanel.20";objectName:"walletOpenSend";text:"Skicka";visible:root.selected.signer_state==="LOCAL_ENCRYPTED";onClicked:root.openActions("send",root.selected)}
                    Action { property string uiColorScope: "ui.control.OmniWalletPanel.21";text:"Kopiera adress";enabled:!!root.selected.address;onClicked:root.copyAddress()}
                    Action { property string uiColorScope: "ui.control.OmniWalletPanel.22";text:"Uppdatera saldo";enabled:!root.busy && !!root.selected.account_id;onClicked:root.run("refresh_balance",{asset_id:root.selected.asset_id,account_id:root.selected.account_id})}
                    Action { property string uiColorScope: "ui.control.OmniWalletPanel.23";objectName:"walletShowAssetMarket";text:"Visa marknad";visible:root.selected.scope!=="LOCAL_LAB";onClicked:root.assetRequested(root.selected.asset_id)}
                }
                Column {width:parent.width;spacing:8;visible:root.selected.scope==="LOCAL_LAB"
                    Label { colorKey: "ui.OmniWalletPanel.36";text:"ÖVERFÖR I GG-LABBET";color:RuntimeTheme.GGTheme.accent;font.pixelSize:10}
                    CryptoField { property string uiColorScope: "ui.widget.OmniWalletPanel.CryptoField.34";id:labAmount;width:parent.width;text:"1";placeholderText:"GG-LAB belopp";Accessible.name:placeholderText}
                    CryptoPick { property string uiColorScope: "ui.control.OmniWalletPanel.24";id:labRecipient;width:parent.width;model:(root.wallet.lab_rows || []).map(function(a){return {index:a.lab_index,name:a.label}});textRole:"name";Accessible.name:"Mottagare i labbet"}
                    Flow {width:parent.width;spacing:6
                        Action { property string uiColorScope: "ui.control.OmniWalletPanel.25";text:"Köa överföring";enabled:!root.busy && labRecipient.currentIndex>=0 && root.selected.lab_index!==labRecipient.model[labRecipient.currentIndex].index;onClicked:root.run("lab_send",{sender:root.selected.lab_index,recipient:labRecipient.model[labRecipient.currentIndex].index,amount:labAmount.text})}
                        Action { property string uiColorScope: "ui.control.OmniWalletPanel.26";text:"Finalisera · "+Number((root.state.lab || {}).pending || 0)+" i kö";enabled:!root.busy && Number((root.state.lab || {}).pending || 0)>0;onClicked:root.run("lab_commit")}
                    }
                }
                Label { colorKey: "ui.OmniWalletPanel.37";width:parent.width;text:root.selected.scope==="LOCAL_LAB" ? "Lokala sessionstillgångar, separat från publika innehav." : root.selected.signer_state==="LOCAL_ENCRYPTED" ? "GG-wallet · nyckel i krypterat Windows-valv. Varje sändning kräver granskning och godkännande." : "Publikt bevakningskonto. Signera överföringar i din externa wallet.";color:RuntimeTheme.GGTheme.dim;font.pixelSize:10;wrapMode:Text.WordWrap;elide:Text.ElideNone}
            }
        }
    }
    Item {id:compactFooter;objectName:"walletCompactFooter";x:root.edgeInset;y:root.height-height;width:root.mainWidth;height:30;visible:root.compactPopup && !root.actionOpen && !root.detailOpen && !root.connectOpen
        Rectangle {width:parent.width;height:1;color:RuntimeTheme.GGTheme.line}
        component Tab:CryptoButton {id:tab;height:28;width:compactFooter.width/3;implicitWidth:0;font.pixelSize:10;leftPadding:3;rightPadding:3;topPadding:2;bottomPadding:2;color:checked ? RuntimeTheme.GGTheme.accent : RuntimeTheme.GGTheme.muted;background:Rectangle {color:tab.hovered || tab.visualFocus ? RuntimeTheme.GGTheme.raised : "transparent";Rectangle { GGColorTarget { colorKey: "ui.fill.OmniWalletPanel.1"; }anchors.bottom:parent.bottom;width:parent.width;height:1;visible:tab.checked;color:RuntimeTheme.GGTheme.accent}}}
        Row {y:2;width:parent.width
            Tab { property string uiColorScope: "ui.control.OmniWalletPanel.27";objectName:"walletAssetsTab";text:"Tillgångar";checked:!root.showActivity;onClicked:root.showActivity=false}
            Tab { property string uiColorScope: "ui.control.OmniWalletPanel.28";objectName:"walletActivityTab";text:"Aktivitet";checked:root.showActivity;onClicked:root.openActivity()}
            Tab { property string uiColorScope: "ui.control.OmniWalletPanel.29";objectName:"walletTools";text:"Verktyg ⋯";enabled:!root.busy && !root.approvalPending;onClicked:walletTools.open()}
        }
    }
    Popup {id:accountMenu;objectName:"walletAccountMenu";x:Math.max(0,root.mainWidth-270);y:root.compactPopup ? Math.min(root.height-height-8,76) : 40;width:Math.min(270,root.mainWidth);padding:10;focus:true;closePolicy:Popup.CloseOnEscape|Popup.CloseOnPressOutside
        background:Rectangle {color:RuntimeTheme.GGTheme.panel;border.color:RuntimeTheme.GGTheme.edge;radius:4}
        contentItem:Column {spacing:5
            Action { property string uiColorScope: "ui.control.OmniWalletPanel.30";width:parent.width;text:"Bevaka en offentlig adress";onClicked:{root.actionOpen=false;root.detailOpen=false;root.connectOpen=true;accountMenu.close()}}
            Action { property string uiColorScope: "ui.control.OmniWalletPanel.31";objectName:"walletNewSolana";width:parent.width;text:"Skapa GG-wallet · Solana";onClicked:{root.openActions("create");accountMenu.close()}}
            Action { property string uiColorScope: "ui.control.OmniWalletPanel.32";width:parent.width;text:"Återställ krypterad backup";onClicked:{root.openActions("restore");accountMenu.close()}}
            Action { property string uiColorScope: "ui.control.OmniWalletPanel.33";width:parent.width;text:"Säkerhetskopiera GG-wallet";visible:(root.wallet.local_wallets || []).length>0;onClicked:{root.openActions("backup");accountMenu.close()}}
        }
    }
    Popup {id:walletTools;objectName:"walletToolsMenu";x:Math.max(0,root.mainWidth-250);y:root.compactPopup ? Math.max(8,root.height-height-36) : 40;width:Math.min(250,root.mainWidth);padding:10;focus:true;closePolicy:Popup.CloseOnEscape|Popup.CloseOnPressOutside
        background:Rectangle {color:RuntimeTheme.GGTheme.panel;border.color:RuntimeTheme.GGTheme.edge;radius:3}
        contentItem:Column {spacing:5
            Action { property string uiColorScope: "ui.control.OmniWalletPanel.34";objectName:"walletOpenFacts";width:parent.width;text:"Skydd / källstatus";onClicked:{walletTools.close();walletFactsDrawer.open()}}
            Action { property string uiColorScope: "ui.control.OmniWalletPanel.35";width:parent.width;text:"Konton / token";onClicked:{walletTools.close();root.toolsRequested()}}
            Action { property string uiColorScope: "ui.control.OmniWalletPanel.36";objectName:"walletManageRoles";width:parent.width;text:"Trading / Förvaring · kontoroller";visible:root.accountRoleEditingAvailable;onClicked:{walletTools.close();root.openRoleManager()}}
            Action { property string uiColorScope: "ui.control.OmniWalletPanel.37";width:parent.width;text:root.showZero ? "Dölj nollsaldo" : "Visa nollsaldo";onClicked:{walletTools.close();root.showZero=!root.showZero}}
            Action { property string uiColorScope: "ui.control.OmniWalletPanel.38";width:parent.width;text:"Aktivitet";onClicked:{walletTools.close();root.actionOpen=false;root.showActivity=true}}
            Action { property string uiColorScope: "ui.control.OmniWalletPanel.39";objectName:root.compactPopup ? "walletTransferHistory" : "";width:parent.width;visible:root.compactPopup && root.transfers.length>0;text:"Överföringar · "+root.transfers.length;onClicked:{walletTools.close();root.openActions("history")}}
            Action { property string uiColorScope: "ui.control.OmniWalletPanel.40";width:parent.width;text:root.showLab ? "Publika innehav" : "GG-labb · sessionstillgångar";onClicked:{walletTools.close();root.showLab=!root.showLab}}
            Action { property string uiColorScope: "ui.control.OmniWalletPanel.41";width:parent.width;text:"Marknad";onClicked:{walletTools.close();root.marketRequested()}}
        }
    }
    Popup {id:walletFactsDrawer;objectName:"walletFactsDrawer";x:Math.max(8,root.width-width-8);y:8;width:Math.min(440,root.width-16);height:Math.max(160,Math.min(760,root.height-16));padding:12;focus:true;closePolicy:Popup.CloseOnEscape|Popup.CloseOnPressOutside
        background:Rectangle {color:RuntimeTheme.GGTheme.base;border.color:RuntimeTheme.GGTheme.edge;radius:3}
        contentItem:Item {
            CryptoButton { property string uiColorScope: "ui.control.OmniWalletPanel.42";objectName:"walletCloseFacts";anchors.right:parent.right;width:80;height:28;text:"Stäng ×";onClicked:walletFactsDrawer.close()}
            WalletTelemetry { property string uiColorScope: "ui.widget.OmniWalletPanel.WalletTelemetry.54";objectName:"walletDrawerTelemetry";y:36;width:parent.width;height:Math.max(0,parent.height-36);state:root.state;accounts:root.scopedAccounts;accountId:root.actionOpen ? walletActions.accountId : root.detailOpen ? root.selected.account_id || "" : root.accountFilter;chainId:root.chain;showAccounts:!root.actionOpen && !root.detailOpen;onAccountRequested:function(id){root.accountFilter=id;walletFactsDrawer.close()} onActivityRequested:root.openActivity()}
        }
    }
}
