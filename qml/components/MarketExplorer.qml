import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls
import QtQuick.Window

import "MarketFormat.js" as Format

FocusScope {
    id:root;objectName:"cryptoMarketExplorer"
    property var surfaceHost:null
    property var state:({})
    property bool initialized:false
    property bool initialRequest:false
    property bool detailOpen:false
    property bool filtersOpen:false
    property string lastStatus:""
    property var pendingRow:({})
    property string requestedAssetId:""
    property string queuedAssetId:""
    property int chartDays:7
    readonly property var settings:state.settings || ({})
    readonly property var operation:state.ui_operation || ({})
    readonly property bool busy:operation.state==="running"
    readonly property var selected:queuedAssetId ? ({name:"Väntar på pågående jobb…"}) : requestedAssetId && (state.selected || {}).asset_id!==requestedAssetId ? ({name:busy ? "Läser vald tillgång…" : "Tillgången kunde inte läsas"}) : busy && pendingRow.id ? pendingRow : state.selected || ({})
    readonly property var rows:state.rows || []
    readonly property bool narrow:width<650
    function tableColumns(){var w=Math.max(0,width-32);return narrow ? [Math.max(50,w-184),96,0,0,88] : [w*.32,w*.16,w*.15,w*.17,w*.20]}
    readonly property bool activeView:visible && (!root.Window.window || (root.Window.window.visible && root.Window.window.visibility!==Window.Minimized))
    readonly property var curve:{
        var chart=selected.chart || ({}),spark=selected.sparkline || ({})
        if(chart.kind==="PRICE_SAMPLES_NOT_OHLC" || !((spark.prices || []).length))return chart
        if(spark.period==="OBSERVED")return chart.kind==="OBSERVED_SAMPLES_NOT_OHLC" ? chart : {prices:spark.prices,times:spark.times || [],source:spark.source,kind:"OBSERVED_SAMPLES_NOT_OHLC"}
        return {prices:spark.prices,times:[],source:spark.source,kind:"PROVIDER_WEEK_SAMPLES"}
    }
    signal walletRequested()
    signal botsRequested()
    signal networkRequested()
    function apply(raw){if(raw===lastStatus)return;try{var value=JSON.parse(raw);if(value.schema==="gg.explorer.v1"){lastStatus=raw;state=value;initialized=true;if(!initialRequest && value.needs_refresh && !value.settings.paused){initialRequest=true;Qt.callLater(function(){run("refresh")})}}}catch(e){}}
    function pull(){if(visible && surfaceHost && surfaceHost.explorerStatus)apply(surfaceHost.explorerStatus())}
    function run(name,args){if(!busy && surfaceHost && surfaceHost.explorerAction)apply(surfaceHost.explorerAction(name,JSON.stringify(args || {})))}
    function choose(row){if(busy)return;forceActiveFocus();queuedAssetId="";requestedAssetId="";pendingRow=row;detailOpen=true;chartDays=7;run("select",{id:row.id,history:true})}
    function openAsset(id){if(!id)return;queuedAssetId=id;pendingRow=({});detailOpen=true;flushQueuedAsset()}
    function flushQueuedAsset(){if(busy || !visible || !queuedAssetId)return;var id=queuedAssetId;queuedAssetId="";requestedAssetId=id;chartDays=7;run("open_asset",{asset_id:id})}
    function closeDetail(){detailOpen=false;pendingRow=({});queuedAssetId="";requestedAssetId=""}
    onBusyChanged:if(!busy && queuedAssetId)Qt.callLater(root.flushQueuedAsset)
    Keys.onPressed:function(event){if(event.key===Qt.Key_Slash && !search.activeFocus){if(root.detailOpen)root.closeDetail();search.forceActiveFocus();event.accepted=true}else if(event.key===Qt.Key_F5 && !root.busy){root.run("refresh",{force:true});event.accepted=true}else if(event.key===Qt.Key_Escape){if(root.detailOpen){root.closeDetail();event.accepted=true}else if(root.filtersOpen){root.filtersOpen=false;event.accepted=true}}}
    function networkName(id){var nets=state.networks || [];for(var i=0;i<nets.length;i++)if(nets[i].id===id)return nets[i].name;return id || "Nätverksvariant finns i detaljer"}
    function tokenImportSupported(id){var nets=state.networks || [];for(var i=0;i<nets.length;i++)if(nets[i].id===id)return ["evm","solana"].indexOf(nets[i].family)>=0;return false}
    function importVariant(chain,reference){run("add_asset",{id:selected.id,chain_id:chain || "",reference:reference || ""})}
    function errorText(error){return ({EXPLORER_SOURCE_UNAVAILABLE:"Källan svarade inte. Senast hämtade data finns kvar.",EXPLORER_SOURCE_COOLDOWN:"Datakällan behöver en kort paus. Försök igen om en stund.",EXPLORER_QUERY_REQUIRED:"Skriv ett namn, en symbol eller en offentlig adress.",EXPLORER_PUBLIC_QUERY_REQUIRED:"Använd ett namn eller en offentlig kontraktsadress."})[error] || String(error || "")}
    Component.onCompleted:pull()
    onVisibleChanged:if(visible){pull();flushQueuedAsset()}
    Connections {target:root.surfaceHost;ignoreUnknownSignals:true;function onExplorerStatusUpdated(raw){if(root.visible)root.apply(raw)}}
    Timer {interval:root.busy || !root.initialized ? 200 : 3000;repeat:true;running:root.visible;onTriggered:root.pull()}
    Timer {interval:["dex","search"].indexOf(root.settings.view)>=0 ? 30000 : 120000;repeat:true;running:root.activeView && root.initialized && !root.busy && !root.settings.paused;onTriggered:root.run("refresh")}
    component Label:GGText {color:RuntimeTheme.GGTheme.text;font.family:"monospace";font.pixelSize:11;textFormat:Text.PlainText;elide:Text.ElideRight}
    component Action:CryptoButton {font.pixelSize:10;enabled:!root.busy && !root.queuedAssetId}
    Column {id:toolbar;x:16;y:14;width:Math.max(0,parent.width-32);spacing:8;visible:!root.detailOpen
        Flow {width:parent.width;spacing:6
            CryptoPick { property string uiColorScope: "ui.control.MarketExplorer.1";width:110;model:[{id:"overview",name:"Marknaden"},{id:"native",name:"Native coins"},{id:"dex",name:"DEX-token"},{id:"watchlist",name:"Bevakning"},{id:"registered",name:"Mina tillgångar"}];textRole:"name";displayText:root.settings.view==="search" ? "Sökresultat" : textAt(currentIndex);currentIndex:{for(var i=0;i<model.length;i++)if(model[i].id===root.settings.view)return i;return 0} onActivated:{root.run("configure",{view:model[currentIndex].id,page:1,query:""});search.text=""}}
            CryptoField { property string uiColorScope: "ui.widget.MarketExplorer.CryptoField.2";id:search;objectName:"marketSearch";width:Math.max(100,parent.width-224);height:32;placeholderText:"Sök token, namn eller kontrakt…";Accessible.name:placeholderText;onAccepted:root.run("search",{query:text.trim()})}
            Action { property string uiColorScope: "ui.control.MarketExplorer.2";objectName:"marketSearchButton";width:30;implicitWidth:30;height:32;text:"⌕";tip:"Sök";enabled:!root.busy && search.text.trim().length>0;onClicked:root.run("search",{query:search.text.trim()})}
            Action { property string uiColorScope: "ui.control.MarketExplorer.3";objectName:"marketRefresh";width:30;implicitWidth:30;height:32;text:root.busy ? "…" : "↻";tip:"Uppdatera";enabled:!root.busy && !root.settings.paused;onClicked:root.run("refresh",{force:true})}
            Action { property string uiColorScope: "ui.control.MarketExplorer.4";objectName:"marketFilterToggle";width:30;implicitWidth:30;height:32;text:"☷";tip:"Filter och uppdatering";checked:root.filtersOpen;onClicked:root.filtersOpen=!root.filtersOpen}
        }
        Flow {width:parent.width;spacing:6;visible:root.filtersOpen
            CryptoPick { property string uiColorScope: "ui.control.MarketExplorer.5";width:180;model:[{id:"",name:"Alla nätverk"}].concat((root.state.networks || []).map(function(n){return {id:n.id,name:n.name}}));textRole:"name";currentIndex:{for(var i=0;i<model.length;i++)if(model[i].id===(root.settings.chain || ""))return i;return 0} onActivated:root.run("configure",{chain:model[currentIndex].id})}
            CryptoPick { property string uiColorScope: "ui.control.MarketExplorer.6";width:150;model:[{id:"rank",name:"Börsvärdesrank"},{id:"market_cap",name:"Börsvärde"},{id:"volume_24h",name:"Volym 24 h"},{id:"liquidity_usd",name:"Likviditet"},{id:"change_24h",name:"Förändring 24 h"},{id:"name",name:"Namn"}];textRole:"name";onActivated:root.run("configure",{sort:model[currentIndex].id})}
            CryptoToggle { property string uiColorScope: "ui.control.MarketExplorer.7";text:"Prissatta";checked:root.settings.hide_unpriced===true;onClicked:root.run("configure",{hide_unpriced:checked})}
            Action { property string uiColorScope: "ui.control.MarketExplorer.8";text:"Likviditet ≥ $10K";checked:Number(root.settings.min_liquidity || 0)>0;onClicked:root.run("configure",{min_liquidity:checked ? 0 : 10000})}
            CryptoToggle { property string uiColorScope: "ui.control.MarketExplorer.9";text:"Pausa";checked:root.settings.paused===true;onClicked:root.run("configure",{paused:checked})}
        }
    }
    Item {id:marketList;objectName:"marketListArea";anchors.top:toolbar.bottom;anchors.topMargin:12;anchors.bottom:footer.top;anchors.bottomMargin:5;x:16;width:Math.max(0,parent.width-32);visible:!root.detailOpen
        Row {id:columns;width:parent.width;height:32;spacing:0
            Label { colorKey: "ui.MarketExplorer.1";width:root.tableColumns()[0];height:32;verticalAlignment:Text.AlignVCenter;text:"TILLGÅNG / NÄTVERK";font.pixelSize:11;color:RuntimeTheme.GGTheme.muted}
            Label { colorKey: "ui.MarketExplorer.2";width:root.tableColumns()[1];height:32;verticalAlignment:Text.AlignVCenter;text:"PRIS / 24 H";font.pixelSize:11;color:RuntimeTheme.GGTheme.muted}
            Label { colorKey: "ui.MarketExplorer.3";width:root.tableColumns()[2];height:32;verticalAlignment:Text.AlignVCenter;visible:!root.narrow;text:"BÖRSVÄRDE";font.pixelSize:11;color:RuntimeTheme.GGTheme.muted}
            Label { colorKey: "ui.MarketExplorer.4";width:root.tableColumns()[3];height:32;verticalAlignment:Text.AlignVCenter;visible:!root.narrow;text:"VOLYM / LIKVIDITET";font.pixelSize:11;color:RuntimeTheme.GGTheme.muted}
            Label { colorKey: "ui.MarketExplorer.5";width:root.tableColumns()[4];height:32;verticalAlignment:Text.AlignVCenter;text:"7 DAGAR";horizontalAlignment:Text.AlignRight;font.pixelSize:11;color:RuntimeTheme.GGTheme.muted}
        }
        Rectangle {y:31;width:parent.width;height:1;color:RuntimeTheme.GGTheme.line}
        ListView {id:list;objectName:"marketTokenList";y:32;width:parent.width;height:Math.max(0,parent.height-y);clip:true;model:root.rows;spacing:0;cacheBuffer:80;ScrollBar.vertical:ScrollBar {}
            delegate:Rectangle {
                id:tokenRow;required property var modelData;required property int index;objectName:"marketTokenRow";width:list.width;height:68;enabled:!root.busy
                color:rowMouse.containsMouse ? RuntimeTheme.GGTheme.hover : root.selected.id===modelData.id ? RuntimeTheme.GGTheme.panel : "transparent"
                Rectangle {anchors.bottom:parent.bottom;width:parent.width;height:1;color:RuntimeTheme.GGTheme.line;opacity:.6}
                Row {y:15;width:parent.width;spacing:0
                    Item {width:root.tableColumns()[0];height:40
                        AssetIcon { property string uiColorScope: "ui.widget.MarketExplorer.AssetIcon.11";width:32;height:32;anchors.verticalCenter:parent.verticalCenter;symbol:tokenRow.modelData.symbol;assetId:tokenRow.modelData.asset_id || tokenRow.modelData.id;chainId:tokenRow.modelData.chain_id || ""}
                        Column {x:44;width:Math.max(0,parent.width-52);spacing:5
                            Label { colorKey: "ui.MarketExplorer.6";width:parent.width;text:tokenRow.modelData.symbol+" · "+tokenRow.modelData.name;color:RuntimeTheme.GGTheme.bright;font.pixelSize:root.narrow ? 12 : 14}
                            Label { colorKey: "ui.MarketExplorer.7";width:parent.width;text:root.networkName(tokenRow.modelData.chain_id);color:RuntimeTheme.GGTheme.muted;font.pixelSize:11}
                        }
                    }
                    Column {width:root.tableColumns()[1];spacing:5
                        Label { colorKey: "ui.MarketExplorer.8";width:parent.width;text:Format.money(tokenRow.modelData.price_usd);font.pixelSize:root.narrow ? 12 : 14}
                        Label { colorKey: "ui.MarketExplorer.9";text:Format.percent(tokenRow.modelData.change_24h);color:tokenRow.modelData.change_24h>0 ? RuntimeTheme.GGTheme.positive : tokenRow.modelData.change_24h<0 ? RuntimeTheme.GGTheme.negative : RuntimeTheme.GGTheme.muted;font.pixelSize:11}
                    }
                    Column {width:root.tableColumns()[2];spacing:5;visible:!root.narrow
                        Label { colorKey: "ui.MarketExplorer.10";width:parent.width;text:Format.compact(tokenRow.modelData.market_cap);font.pixelSize:14}
                        Label { colorKey: "ui.MarketExplorer.11";width:parent.width;text:tokenRow.modelData.kind==="NATIVE" ? "Native coin" : "Coin / token";font.pixelSize:11;color:RuntimeTheme.GGTheme.dim}
                    }
                    Column {width:root.tableColumns()[3];spacing:5;visible:!root.narrow
                        Label { colorKey: "ui.MarketExplorer.12";width:parent.width;text:Format.compact(tokenRow.modelData.volume_24h);font.pixelSize:14}
                        Label { colorKey: "ui.MarketExplorer.13";text:Format.compact(tokenRow.modelData.liquidity_usd);font.pixelSize:11;color:RuntimeTheme.GGTheme.dim}
                    }
                    PriceSparkline { property string uiColorScope: "ui.widget.MarketExplorer.PriceSparkline.12";width:Math.max(20,root.tableColumns()[4]-4);height:38;samples:(tokenRow.modelData.sparkline || {}).prices || [];periodLabel:(tokenRow.modelData.sparkline || {}).period==="OBSERVED" ? "Observerad historik" : "7 dagar";sourceLabel:(tokenRow.modelData.sparkline || {}).source || "Historik saknas";stale:tokenRow.modelData.stale===true}
                }
                MouseArea {id:rowMouse;anchors.fill:parent;hoverEnabled:true;cursorShape:Qt.PointingHandCursor;onClicked:root.choose(tokenRow.modelData)}
                activeFocusOnTab:true;Accessible.role:Accessible.Button;Accessible.name:modelData.name;Keys.onReturnPressed:root.choose(modelData)
            }
            Label { colorKey: "ui.MarketExplorer.14";anchors.centerIn:parent;width:parent.width-30;visible:list.count===0;text:root.busy ? "Hämtar marknad…" : "Inga träffar. Justera sökning eller filter.";wrapMode:Text.WordWrap;elide:Text.ElideNone;color:RuntimeTheme.GGTheme.muted}
        }
    }
    Column {id:detailHead;x:16;y:14;width:Math.max(0,parent.width-32);spacing:8;visible:root.detailOpen
        Flow {width:parent.width;spacing:8
            Action { property string uiColorScope: "ui.control.MarketExplorer.10";text:"←";tip:"Till marknaden";implicitWidth:32;enabled:true;onClicked:root.closeDetail()}
            Label { colorKey: "ui.MarketExplorer.15";text:String(root.selected.symbol || "Tillgång")+" · "+String(root.selected.name || "");font.pixelSize:17;color:RuntimeTheme.GGTheme.bright;height:30;verticalAlignment:Text.AlignVCenter}
            Label { colorKey: "ui.MarketExplorer.16";text:Format.money(root.selected.price_usd);font.pixelSize:20;color:RuntimeTheme.GGTheme.bright;height:30;verticalAlignment:Text.AlignVCenter}
            Label { colorKey: "ui.MarketExplorer.17";text:Format.percent(root.selected.change_24h)+" · 24 h";color:root.selected.change_24h<0 ? RuntimeTheme.GGTheme.negative : RuntimeTheme.GGTheme.positive;height:30;verticalAlignment:Text.AlignVCenter}
        }
        Flow {width:parent.width;spacing:6
            CryptoPick { property string uiColorScope: "ui.control.MarketExplorer.11";width:105;model:[{days:1,name:"1 dag"},{days:7,name:"7 dagar"},{days:30,name:"1 månad"}];textRole:"name";currentIndex:root.chartDays===1 ? 0 : root.chartDays===30 ? 2 : 1;enabled:!root.busy && root.selected.provider==="coingecko";onActivated:{root.chartDays=model[currentIndex].days;root.run("chart",{id:root.selected.id,days:root.chartDays})}}
            Action { property string uiColorScope: "ui.control.MarketExplorer.12";text:root.selected.starred ? "★ Bevakar" : "☆ Bevaka";enabled:!root.busy && root.selected.provider!=="registered";onClicked:root.run("star",{id:root.selected.id,enabled:!root.selected.starred})}
            Action { property string uiColorScope: "ui.control.MarketExplorer.13";text:"Portfölj";onClicked:root.walletRequested()}
            Action { property string uiColorScope: "ui.control.MarketExplorer.14";text:"Info / pooler";onClicked:info.open()}
            BusyIndicator {width:24;height:24;running:root.busy;visible:running}
        }
    }
    MarketPriceChart { property string uiColorScope: "ui.widget.MarketExplorer.MarketPriceChart.18";objectName:"assetChartStage";anchors.top:detailHead.bottom;anchors.topMargin:10;anchors.bottom:stats.top;anchors.bottomMargin:10;x:16;width:Math.max(0,parent.width-32);visible:root.detailOpen;series:root.curve;period:root.curve.kind==="OBSERVED_SAMPLES_NOT_OHLC" ? "Observerad historik" : (root.curve.period_days || 7)+" dagar"}
    Flow {id:stats;anchors.bottom:footer.top;anchors.bottomMargin:8;x:16;width:Math.max(0,parent.width-32);spacing:14;visible:root.detailOpen
        Label { colorKey: "ui.MarketExplorer.18";text:"Börsvärde  "+Format.compact(root.selected.market_cap)}
        Label { colorKey: "ui.MarketExplorer.19";text:"Volym 24 h  "+Format.compact(root.selected.volume_24h)}
        Label { colorKey: "ui.MarketExplorer.20";text:"Likviditet  "+Format.compact(root.selected.liquidity_usd)}
    }
    Column {id:footer;anchors.bottom:parent.bottom;anchors.bottomMargin:8;x:16;width:Math.max(0,parent.width-32);spacing:3
        Label { colorKey: "ui.MarketExplorer.21";width:parent.width;visible:!!root.operation.error;text:root.errorText(root.operation.error);color:RuntimeTheme.GGTheme.negative;wrapMode:Text.WordWrap;elide:Text.ElideNone}
        Row {width:parent.width;spacing:6
            Repeater {model:root.state.sources || []
                Label { colorKey: "ui.MarketExplorer.22";required property var modelData;verticalAlignment:Text.AlignVCenter;height:26;text:modelData.name+" · "+({CURRENT:"aktuell",STALE:"äldre data",FAILED:"otillgänglig",NOT_FETCHED:"ej hämtad"}[modelData.state] || modelData.state);font.pixelSize:9;color:modelData.state==="CURRENT" ? RuntimeTheme.GGTheme.muted : RuntimeTheme.GGTheme.accent}
            }
            Item {width:Math.max(0,parent.width-prev.width-next.width-pageLabel.width-((root.state.sources || []).length>1 ? 260 : 132)-30);height:1}
            Action { property string uiColorScope: "ui.control.MarketExplorer.15";id:prev;visible:!root.detailOpen;text:"←";implicitWidth:26;height:24;enabled:!root.busy && Number(root.settings.page || 1)>1;onClicked:root.run("configure",{page:Number(root.settings.page)-1})}
            Label { colorKey: "ui.MarketExplorer.23";id:pageLabel;visible:!root.detailOpen;text:root.rows.length+" · sida "+Number(root.settings.page || 1);height:24;verticalAlignment:Text.AlignVCenter;font.pixelSize:9}
            Action { property string uiColorScope: "ui.control.MarketExplorer.16";id:next;visible:!root.detailOpen;text:"→";implicitWidth:26;height:24;enabled:!root.busy && Number(root.settings.page || 1)<50 && ["overview","native"].indexOf(root.settings.view)>=0;onClicked:root.run("configure",{page:Number(root.settings.page || 1)+1})}
        }
    }
    Popup {id:info;objectName:"assetInfoPanel";x:Math.max(0,root.width-width);y:0;width:Math.min(350,root.width);height:root.height;padding:14;focus:true;closePolicy:Popup.CloseOnEscape|Popup.CloseOnPressOutside
        background:Rectangle {color:RuntimeTheme.GGTheme.panel;border.color:RuntimeTheme.GGTheme.edge;radius:4}
        contentItem:Flickable {clip:true;contentWidth:width;contentHeight:infoBody.height;ScrollBar.vertical:ScrollBar {}
            Column {id:infoBody;width:parent.width;spacing:12
                Action { property string uiColorScope: "ui.control.MarketExplorer.17";text:"← Till grafen";enabled:true;onClicked:info.close()}
                Label { colorKey: "ui.MarketExplorer.24";width:parent.width;text:root.networkName(root.selected.chain_id);font.pixelSize:15;color:RuntimeTheme.GGTheme.bright;wrapMode:Text.WordWrap;elide:Text.ElideNone}
                Label { colorKey: "ui.MarketExplorer.25";width:parent.width;text:String(root.selected.reference || root.selected.asset_id || root.selected.id || "");wrapMode:Text.WrapAnywhere;elide:Text.ElideNone;color:RuntimeTheme.GGTheme.muted}
                Label { colorKey: "ui.MarketExplorer.26";width:parent.width;text:"Tokenrisk: ej bedömd. Pris är ingen säkerhetsverifiering.";wrapMode:Text.WordWrap;elide:Text.ElideNone;color:RuntimeTheme.GGTheme.accent}
                Action { property string uiColorScope: "ui.control.MarketExplorer.18";text:"Välj i wallet";visible:root.selected.kind==="NATIVE" && !!root.selected.asset_id;onClicked:root.importVariant()}
                Repeater {model:root.selected.variants || []
                    Action { property string uiColorScope: "ui.control.MarketExplorer.19";required property var modelData;width:Math.min(implicitWidth,infoBody.width);text:(root.tokenImportSupported(modelData.chain_id) ? "Lägg till · " : "Adapter saknas · ")+root.networkName(modelData.chain_id);enabled:!root.busy && root.tokenImportSupported(modelData.chain_id);onClicked:root.importVariant(modelData.chain_id,modelData.reference)}
                }
                Action { property string uiColorScope: "ui.control.MarketExplorer.20";text:"Identifiera och lägg till token";visible:root.selected.provider==="dexscreener";enabled:!root.busy && root.tokenImportSupported(root.selected.chain_id);onClicked:root.importVariant(root.selected.chain_id,root.selected.reference)}
                Action { property string uiColorScope: "ui.control.MarketExplorer.21";text:"Paperbotar";enabled:!root.busy && root.selected.registered===true;onClicked:{info.close();root.botsRequested()}}
                Label { colorKey: "ui.MarketExplorer.27";text:"HANDELSPOOLER";color:RuntimeTheme.GGTheme.muted;font.pixelSize:10}
                Repeater {model:root.selected.pools || []
                    Column {required property var modelData;width:infoBody.width;spacing:4
                        Label { colorKey: "ui.MarketExplorer.28";width:parent.width;text:modelData.dex+" / "+modelData.quote_symbol+" · "+Format.money(modelData.price_usd)}
                        Label { colorKey: "ui.MarketExplorer.29";width:parent.width;text:"Likviditet "+Format.compact(modelData.liquidity_usd)+" · "+Format.shortAddress(modelData.address);color:RuntimeTheme.GGTheme.dim;font.pixelSize:10}
                    }
                }
                Label { colorKey: "ui.MarketExplorer.30";width:parent.width;text:String(root.curve.source || "")+" · historiska prisobservationer";color:RuntimeTheme.GGTheme.dim;wrapMode:Text.WordWrap;elide:Text.ElideNone;font.pixelSize:10}
            }
        }
    }
}
