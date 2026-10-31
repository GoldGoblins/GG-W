import QtQuick
import QtQuick.Controls
import QtQuick.Window
import "." as RuntimeTheme

// Bounded live signed proposal-DAG jobs. Admission and speculative preview
// are separate from canonical finality and from the financial wallet.
Item {
    id:root;objectName:"parallelDagDashboard"
    property var state:({})
    property var surfaceHost:null
    property bool stopRequested:false
    property string stopError:""
    property bool sidePanelOpen:true
    readonly property var dag:state.parallel_dag||({})
    readonly property var lan:dag.lan||({})
    readonly property var lanSetup:dag.lan_setup||({})
    readonly property var testTokens:dag.test_tokens||({})
    readonly property var tokenCircle:dag.token_circle||({})
    readonly property var dagStress:dag.dag_stress||({})
    readonly property bool dagStressRunning:["STARTING","RUNNING","STOPPING"].indexOf(String(dagStress.state||""))>=0
    readonly property bool hasDagAcknowledgement:dagStress.all_peers_synced===true&&measured(dagStress.acknowledged_blocks)&&measured(dagStress.acknowledged_transactions)
    readonly property bool dagTransactionMode:lanOwned&&dagStress.enabled===true
    readonly property var defaultStressArguments:defaultDagStressArguments()
    readonly property bool canStartDefaultStress:dagTransactionMode&&dagStress.supported===true&&dagStress.local_opt_in===true&&lanSetup.coordinator===true&&dagStress.role==="COORDINATOR"&&dagStress.can_start===true&&(dagStress.participants||[]).length===3&&(dagStress.participants||[]).every(function(peer){return peer.opted_in===true})&&!dagStressRunning&&defaultStressArguments!==null
    readonly property bool primaryActionEnabled:canAct&&(lanOwned?lan.state==="READY"&&(dagTransactionMode?(dagStressRunning?dagStress.role==="COORDINATOR"&&dagStress.state!=="STOPPING":canStartDefaultStress):!dagStressRunning):!running)
    readonly property string primaryActionText:dagTransactionMode?dagStress.role!=="COORDINATOR"?"DAG-deltagare":dagStressRunning?dagStress.state==="STOPPING"?"■ Stoppar prov…":width<600?"■ DAG-prov":"■ Stoppa DAG-prov":width<600||!defaultStressArguments?"▷ DAG-prov":"▷ DAG-prov · "+(defaultStressArguments.duration_ms/1000)+" s":lanOwned?width<600?liveRunning?"Ⅱ Pausa 2":"▷ Egna 2":liveRunning?"Ⅱ Pausa egna 2":"▷ Kör egna 2":"▷ Starta"
    readonly property string primaryActionTip:dagTransactionMode?dagStress.role!=="COORDINATOR"?"Koordinatorn startar och stoppar det gemensamma DAG-provet":dagStressRunning?"Stoppa det pågående tidsbegränsade DAG-provet":defaultStressArguments?"Starta prov med tre apparater · "+defaultStressArguments.duration_ms+" ms · "+defaultStressArguments.transactions_per_block+" DAG-TX/förslag · "+defaultStressArguments.interval_ms+" ms målintervall":"Väntar på giltiga programgränser och tre uttryckliga DAG-TX-val":lanOwned?"Starta eller pausa endast den här apparatens två producenter":"Starta lokal DAG-session"
    readonly property bool lanOwned:lanSetup.active===true
    readonly property var operation:state.ui_operation||({})
    readonly property var limits:dag.limits||({})
    readonly property var admission:dag.admission||({})
    readonly property var preview:dag.preview||({})
    readonly property var lastWave:dag.last_wave||({})
    readonly property var graph:dag.block_graph||({})
    readonly property var live:dag.live||({})
    readonly property bool asynchronous:live.mode==="ASYNC_INDEPENDENT_PRODUCERS"
    readonly property int producerCount:lanOwned&&dag.producer_count===0?0:Number.isInteger(dag.producer_count)&&dag.producer_count>=1&&dag.producer_count<=16?dag.producer_count:4
    readonly property bool liveRunning:live.enabled===true
    readonly property bool liveLimited:live.state==="LIMIT_REACHED"
    readonly property var measurements:(dag.measurements||[]).filter(function(m){return typeof m.total_ms==="number"&&isFinite(m.total_ms)&&m.total_ms>=0}).slice(-32)
    readonly property var producerRows:{
        var result=[],stats=dag.producers||[],blocks=graph.blocks||[]
        for(var i=0;i<producerCount;i++){
            var measured=null
            for(var j=0;j<stats.length;j++)if(stats[j].index===i){measured=stats[j];break}
            var seen=blocks.filter(function(b){return b.proposer_index===i})
            result.push({index:i,blocks:measured?measured.proposals:seen.length,
                transactions:measured?measured.transactions:seen.reduce(function(n,b){return n+Number(b.transaction_count||0)},0),
                sequence:seen.length?Math.max.apply(null,seen.map(function(b){return Number(b.producer_sequence||0)})):null,
                rate:measured&&typeof measured.observed_proposal_bps==="number"?measured.observed_proposal_bps:null,
                interval_ms:measured?measured.configured_interval_ms:null})
        }
        return result
    }
    readonly property string liveLabel:dagTransactionMode?"DAG-prov · "+String(dagStress.state||"IDLE"):lanOwned&&!running?String(lan.state||"STARTING"):liveRunning?"Löpande":liveLimited?"Kvot nådd":live.state==="ERROR"?"Fel":running?"Pausad":"Stoppad"
    readonly property string notice:stopError||operation.error||dag.error||(lanOwned&&lan.last_error?String(lan.last_error):lanOwned&&dagStress.last_error?String(dagStress.last_error):liveLimited?"Kvot nådd · förslag bevarade · "+(lanOwned?"stoppa LAN-peer för en ny session":"Stoppa/Starta för en ny session"):live.state==="ERROR"?String(live.stop_reason||"Löpande körning stoppades vid fel"):busy?"Arbetar · "+String(operation.name||""):sequenceRunning&&!lanOwned?"Våg "+sequenceSent+" / 3 · minst 2 s mellan jobb":sequenceResult&&!lanOwned?sequenceResult:lanOwned?lan.state!=="READY"?"LAN · "+String(lan.state||"STARTING")+" · väntar på godkänd session":dagTransactionMode?dagStress.state&&dagStress.state!=="IDLE"?stressResultText():"DAG-TX-session · kör ett tidsbegränsat prov med tre apparater; inställningar finns under DAG-stressprov & LAN":liveRunning?"2 egna producenter · förslag och DAG-TX räknas vid lokal validering":"Egna 2 pausade · mottagning och verifiering fortsätter":liveRunning?asynchronous?producerCount+" oberoende producenter · mål "+number(live.target_proposal_bps)+" förslag/s":"Löpande · "+number(live.blocks)+" förslag / "+number(live.interval_ms)+" ms · "+number(live.transactions_per_block)+" TX / förslag":"Lokal testdata · godtagande är inte finalitet")
    readonly property var rows:(graph.blocks||[]).slice().sort(function(a,b){return asynchronous?Number(b.admission_index)-Number(a.admission_index):Number(b.rank)-Number(a.rank)||Number(b.producer_sequence)-Number(a.producer_sequence)||Number(a.proposer_index)-Number(b.proposer_index)})
    readonly property var events:(dag.events||[]).slice(-48).reverse()
    readonly property color producerSeriesColor:RuntimeTheme.GGColorContext.colorFor("ui.chart.dag.producer",RuntimeTheme.GGTheme.purple)
    readonly property color validationSeriesColor:RuntimeTheme.GGColorContext.colorFor("ui.chart.dag.validation",RuntimeTheme.GGTheme.cyan)
    readonly property color totalSeriesColor:RuntimeTheme.GGColorContext.colorFor("ui.chart.dag.total",RuntimeTheme.GGTheme.blue)
    readonly property var producerColors:{var result=[],indices=[0,2,1,4,5,3,6,7,8,9,10,11,12,13,14,15];for(var i=0;i<producerCount;i++)result.push(RuntimeTheme.GGColorContext.colorFor("ui.graph.block.producer."+i,RuntimeTheme.GGTheme.color(indices[i])));return result}
    readonly property bool busy:operation.state==="running"
    readonly property bool approvalPending:operation.state==="approval_required"
    readonly property bool canAct:!busy&&!approvalPending
    readonly property bool running:dag.state==="RUNNING"
    readonly property bool dockAvailable:width>=820
    readonly property bool railVisible:dockAvailable&&sidePanelOpen
    readonly property bool detailsVisible:railVisible||factsDrawer.visible
    readonly property real railWidth:Math.max(248,Math.min(360,width*.27))
    readonly property real mainWidth:Math.max(0,width-(railVisible?railWidth:0))
    readonly property bool activeView:visible&&(!root.Window.window||root.Window.window.visible&&root.Window.window.visibility!==Window.Minimized)
    property bool sequenceRunning:false
    property int sequenceSent:0
    property int sequenceBlocks:0
    property int sequenceTx:0
    property real sequenceDeadline:0
    property real sequenceNextAt:0
    property string sequenceResult:""
    readonly property bool sequenceCapacity:typeof admission.remaining_bytes==="number"&&admission.remaining_bytes>0&&Number(dag.blocks_admitted||0)+Number(blockCount.text)+1<=Number(limits.max_records||4096)
    readonly property bool validJob:/^[1-9][0-9]{0,2}$/.test(blockCount.text)&&/^(0|[1-9][0-9]{0,2})$/.test(txPerBlock.text)&&Number(blockCount.text)<=Number(limits.max_wave_blocks||32)&&Number(txPerBlock.text)<=Number(limits.max_tx_per_block||128)&&Number(blockCount.text)*Number(txPerBlock.text)<=Number(limits.max_wave_transactions||512)
    readonly property bool validInterval:/^[1-9][0-9]{1,4}$/.test(intervalField.text)&&Number(intervalField.text)>=Number(limits.min_live_interval_ms||10)&&Number(intervalField.text)<=Number(limits.max_live_interval_ms||60000)
    signal actionRequested(string name,var args)
    signal refreshRequested()
    signal pageRequested(string page)
    function toggleDetails(){if(dockAvailable){factsDrawer.close();sidePanelOpen=!sidePanelOpen}else factsDrawer.visible?factsDrawer.close():factsDrawer.open()}
    function run(name,args){if(name==="dag_stop"){if((!running&&!lanOwned)||stopRequested)return;cancelSequence("Kommande vågor avbrutna")}else if(!canAct)return;if(name==="dag_start"&&(running||lanOwned))return;if(name==="dag_wave"&&(!running||lanOwned))return;if((name==="lan_produce"||name==="lan_pause")&&(!lanOwned||lan.state!=="READY"||dagStressRunning||dagTransactionMode))return;if(name==="lan_dag_stress_start"&&!canStartDefaultStress)return;if(name==="lan_dag_stress_stop"&&(!lanOwned||dagStress.supported!==true||dagStress.role!=="COORDINATOR"||!dagStressRunning))return;actionRequested(name,args||{})}
    function triggerPrimary(){if(!primaryActionEnabled)return;if(dagTransactionMode)run(dagStressRunning?"lan_dag_stress_stop":"lan_dag_stress_start",dagStressRunning?{}:defaultStressArguments);else run(lanOwned?(liveRunning?"lan_pause":"lan_produce"):"dag_start",{})}
    function defaultDagStressArguments(){
        var bounds=dagStress.limits||({}),values=[bounds.min_duration_ms,bounds.max_duration_ms,bounds.min_interval_ms,bounds.max_interval_ms,bounds.max_tx_per_block]
        if(!values.every(function(value){return Number.isSafeInteger(value)&&value>=1})||bounds.min_duration_ms>bounds.max_duration_ms||bounds.min_interval_ms>bounds.max_interval_ms)return null
        return {duration_ms:Math.max(bounds.min_duration_ms,Math.min(bounds.max_duration_ms,10000)),transactions_per_block:Math.min(bounds.max_tx_per_block,16),interval_ms:Math.max(bounds.min_interval_ms,Math.min(bounds.max_interval_ms,100))}
    }
    function stressResultText(){return "DAG-prov · "+String(dagStress.state)+" · "+number(dagStress.blocks)+" förslag / "+number(dagStress.transactions)+" DAG-TX lokalt · "+(hasDagAcknowledgement?"nätkvittens från alla tre":"nätkvittens ej bekräftad")}
    function wave(){if(running&&canAct&&validJob&&!sequenceRunning&&!liveRunning)run("dag_wave",{blocks:Number(blockCount.text),transactions_per_block:Number(txPerBlock.text)})}
    function toggleLive(){
        if(!canAct||!running||sequenceRunning||lanOwned)return
        if(liveRunning)run("dag_live_stop",{})
        else if(validJob&&validInterval&&!liveLimited)run("dag_live_start",{blocks:Number(blockCount.text),transactions_per_block:Number(txPerBlock.text),interval_ms:Number(intervalField.text)})
    }
    function syncLiveFields(){if(!liveRunning)return;if(typeof live.blocks==="number")blockCount.text=String(live.blocks);if(typeof live.transactions_per_block==="number")txPerBlock.text=String(live.transactions_per_block);if(typeof live.interval_ms==="number")intervalField.text=String(live.interval_ms)}
    onLiveChanged:Qt.callLater(syncLiveFields)
    function seriesColor(kind){return kind==="producer"?producerSeriesColor:kind==="validation"?validationSeriesColor:totalSeriesColor}
    function producerColor(index){return producerColors.length?producerColors[index%producerColors.length]:RuntimeTheme.GGTheme.muted}
    function metricAt(index){
        if(index===0)return {name:"FÖRSLAG I DAG",value:number(dag.blocks_admitted),detail:lanOwned?"lokalt godtagna förslag":"lokal experiment-DAG"}
        if(index===1)return {name:lanOwned?"VALIDERAD DAG-TX":"VALIDERAD TX",value:number(dag.transactions_validated),detail:lanOwned?"lokalt verifierade signaturer":"verifierade signaturer"}
        if(index===2)return {name:"FRONTIER",value:number(dag.frontier_size),detail:"öppna spetsar"}
        return lanOwned?{name:"PRODUCENTER",value:number(dag.producer_count)+" · LAN",detail:lan.state==="READY"?"2 egna · "+number(lan.configured_peers)+" parade apparater":number(lanSetup.invite_count)+" / 3 inbjudna"}:{name:"PRODUCENTER",value:number(dag.producer_count)+" · lokalt",detail:"en dator · inget P2P"}
    }
    function cancelSequence(message){sequenceRunning=false;sequenceResult=String(message||"")}
    function issueSequenceWave(){
        if(!sequenceRunning)return
        if(!activeView||!running||approvalPending||Date.now()>=sequenceDeadline||operation.error||dag.error){cancelSequence("Kommande vågor avbrutna");return}
        if(Date.now()<sequenceNextAt){sequenceClock.interval=Math.max(16,sequenceNextAt-Date.now());sequenceClock.restart();return}
        if(!canAct){sequenceClock.interval=250;sequenceClock.restart();return}
        if(typeof admission.remaining_bytes!=="number"||admission.remaining_bytes<=0||Number(dag.blocks_admitted||0)+sequenceBlocks+1>Number(limits.max_records||4096)){cancelSequence("Sessionskvoten räcker inte för nästa våg");return}
        sequenceNextAt=Date.now()+2000;sequenceSent++
        run("dag_wave",{blocks:sequenceBlocks,transactions_per_block:sequenceTx})
        if(sequenceSent>=3)cancelSequence("Tre vågor skickade · inga fler jobb körs")
        else if(sequenceRunning){sequenceClock.interval=2000;sequenceClock.restart()}
    }
    function startSequence(){
        if(sequenceRunning){cancelSequence("Kommande vågor avbrutna");return}
        if(!activeView||!running||!canAct||!validJob||!sequenceCapacity||liveRunning||lanOwned)return
        sequenceBlocks=Number(blockCount.text);sequenceTx=Number(txPerBlock.text);sequenceSent=0;sequenceNextAt=0
        sequenceDeadline=Date.now()+20000;sequenceResult="";sequenceRunning=true;issueSequenceWave()
    }
    onActiveViewChanged:if(!activeView)cancelSequence("Kommande vågor avbrutna")
    onRunningChanged:if(!running)cancelSequence("")
    onApprovalPendingChanged:if(approvalPending)cancelSequence("Väntar på godkännande · sekvensen avbruten")
    onOperationChanged:if(sequenceRunning&&(operation.error||["error","failed","rejected","cancelled"].indexOf(String(operation.state||"").toLowerCase())>=0))cancelSequence("Jobbet misslyckades · inga fler vågor körs")
    onDagChanged:if(sequenceRunning&&dag.error)cancelSequence("Jobbet misslyckades · inga fler vågor körs")
    Component.onDestruction:cancelSequence("")
    Timer {id:sequenceClock;interval:2000;running:root.sequenceRunning;repeat:true;onTriggered:root.issueSequenceWave()}
    Timer {interval:20000;running:root.sequenceRunning;repeat:false;onTriggered:root.cancelSequence("Tidsgränsen nådd · inga fler vågor körs")}
    function number(value){return typeof value==="number"&&isFinite(value)?String(value):"—"}
    function measured(value){return typeof value==="number"&&isFinite(value)&&value>=0}
    function acknowledgedRate(name){return hasDagAcknowledgement&&measured(dagStress[name])?dagStress[name].toFixed(1):"—"}
    function millis(value){return typeof value==="number"&&isFinite(value)&&value>=0?value.toFixed(2)+" ms":"—"}
    function bytes(value){return typeof value==="number"&&isFinite(value)&&value>=0?(value>=1048576?(value/1048576).toFixed(2)+" MiB":(value/1024).toFixed(1)+" KiB"):"—"}
    function shortId(value){value=String(value||"");return value.length>18?value.slice(0,8)+"…"+value.slice(-5):value||"—"}
    function copy(value){value=String(value||"");if(/^[0-9a-f]{64}$/.test(value)&&surfaceHost&&surfaceHost.tmogCopy)surfaceHost.tmogCopy(value)}
    function eventColor(kind){return /REJECT|FAIL|ERROR|CONFLICT/.test(String(kind||""))?RuntimeTheme.GGTheme.negative:/ADMIT|READY|START|WAVE/.test(String(kind||""))?RuntimeTheme.GGTheme.positive:RuntimeTheme.GGTheme.muted}
    onDockAvailableChanged:if(dockAvailable)factsDrawer.close()
    component Label:GGText {font.family:"monospace";font.pixelSize:10;color:RuntimeTheme.GGTheme.text;textFormat:Text.PlainText;elide:Text.ElideRight;ToolTip.visible:tipHover.hovered&&truncated;ToolTip.text:text;ToolTip.delay:350;HoverHandler{id:tipHover}}
    component Action:CryptoButton {height:24;font.pixelSize:10;enabled:root.canAct}
    component Frame:Rectangle {color:"transparent";border.color:RuntimeTheme.GGTheme.line;border.width:1;antialiasing:false;clip:true}
    component Head:Item {property string title:"";property string detail:"";height:19;width:parent.width
        Label { colorKey: "ui.GGParallelDagDashboard.1";y:2;width:parent.width-detailText.implicitWidth-8;text:parent.title;font.pixelSize:9;color:RuntimeTheme.GGTheme.muted}
        Label { colorKey: "ui.GGParallelDagDashboard.2";id:detailText;y:2;anchors.right:parent.right;text:parent.detail;font.pixelSize:9;color:RuntimeTheme.GGTheme.dim}
        Rectangle {anchors.bottom:parent.bottom;width:parent.width;height:1;color:RuntimeTheme.GGTheme.line}
    }
    component Fact:Item {property string name:"";property string value:"—";property color valueColor:RuntimeTheme.GGTheme.text;width:parent.width;height:14
        Label { colorKey: "ui.GGParallelDagDashboard.3";y:1;width:parent.width*.46-4;text:parent.name;font.pixelSize:9;color:RuntimeTheme.GGTheme.dim}
        Label { colorKey: "ui.GGParallelDagDashboard.4";x:parent.width*.46;y:1;width:parent.width*.54;text:parent.value;font.pixelSize:9;color:parent.valueColor;horizontalAlignment:Text.AlignRight}
        Rectangle {y:13;width:parent.width;height:1;color:RuntimeTheme.GGTheme.line;opacity:.35}
    }
    component Quota:Item {id:quota;property string title:"";property var used:null;property var limit:null;readonly property bool known:typeof used==="number"&&used>=0&&typeof limit==="number"&&limit>0;readonly property real fraction:known?Math.max(0,Math.min(1,used/limit)):0;property string valueText:"";width:parent.width;height:30
        Label { colorKey: "ui.GGParallelDagDashboard.5";width:parent.width*.45;text:parent.title;font.pixelSize:9;color:RuntimeTheme.GGTheme.dim}
        Label { colorKey: "ui.GGParallelDagDashboard.6";x:parent.width*.45;width:parent.width*.55;text:parent.valueText;font.pixelSize:9;horizontalAlignment:Text.AlignRight}
        Rectangle {y:20;width:Math.max(0,parent.width-36);height:3;color:RuntimeTheme.GGTheme.line;Rectangle{id:meterFill;width:parent.width*parent.parent.fraction;height:3;color:RuntimeTheme.GGTheme.cyan} GGColorTarget{target:meterFill;colorKey:"ui.meter.dag."+quota.objectName;percentageCapable:true;fraction:quota.known?quota.fraction:NaN}}
        Label { colorKey: "ui.GGParallelDagDashboard.7";y:15;anchors.right:parent.right;text:parent.known?(parent.fraction*100).toFixed(1)+" %":"—";font.pixelSize:9;color:RuntimeTheme.GGTheme.dim}
    }
    Item {id:toolbar;objectName:"dagToolbar";readonly property bool stacked:root.width<(root.lanOwned?820:600);width:parent.width;height:stacked?62:32
        Row {objectName:"dagModeControls";x:8;y:toolbar.stacked?33:3;spacing:5
            Action { property string uiColorScope: "ui.control.GGParallelDagDashboard.1";objectName:"dagTestnetMode";text:root.width<600?"EVM":"GG TESTNÄT";flat:true;enabled:true;onClicked:root.pageRequested("TESTNET")}
            Action { property string uiColorScope: "ui.control.GGParallelDagDashboard.2";objectName:"dagLabMode";text:root.width<600?"LABB":"SIGNERAT LABB";flat:true;enabled:true;onClicked:root.pageRequested("LAB")}
            Action { property string uiColorScope: "ui.control.GGParallelDagDashboard.3";objectName:"dagValidatorMode";text:root.width<600?"BFT":"VALIDATORER";flat:true;enabled:true;onClicked:root.pageRequested("CONSENSUS")}
            Action { property string uiColorScope: "ui.control.GGParallelDagDashboard.4";objectName:"dagDagMode";text:root.width<600?"DAG":"DAGoblin";flat:true;checked:true;enabled:true}
        }
        Row {objectName:"dagPrimaryControls";anchors.right:parent.right;anchors.rightMargin:8;y:3;spacing:5
            Action {property string uiColorScope:"ui.control.dag.lan";objectName:"dagLanSetup";text:root.lanOwned?"LAN · "+String(root.lan.state||""):"LAN";enabled:true;onClicked:lanPopup.open()}
            Action { property string uiColorScope: "ui.control.GGParallelDagDashboard.5";objectName:"dagRefresh";width:26;tip:"Läs aktuell lokal DAG-status";onClicked:root.refreshRequested();contentItem:Item{LedgerGlyph{ property string uiColorScope: "ui.widget.GGParallelDagDashboard.LedgerGlyph.6";anchors.centerIn:parent;width:13;height:13;name:"refresh";color:RuntimeTheme.GGTheme.text}}}
            Action { property string uiColorScope: "ui.control.GGParallelDagDashboard.6";objectName:"dagStart";text:root.primaryActionText;tip:root.primaryActionTip;enabled:root.primaryActionEnabled;onClicked:root.triggerPrimary()}
            Action { property string uiColorScope: "ui.control.GGParallelDagDashboard.7";objectName:"dagStop";text:root.stopRequested?"■ Stoppar…":root.lanOwned?(root.width<600?"■ LAN-peer":"■ Stoppa LAN-peer"):"■ Stoppa";tip:root.lanOwned?"Avsluta den här apparatens LAN-peer":"Stoppa lokal DAG-session";enabled:(root.running||root.lanOwned)&&!root.stopRequested;onClicked:root.run("dag_stop",{})}
            Action { property string uiColorScope: "ui.control.GGParallelDagDashboard.8";objectName:"dagDetails";width:26;text:"⋯";enabled:true;tip:"Visa DAG-fakta";onClicked:root.toggleDetails()}
        }
        Rectangle {anchors.bottom:parent.bottom;width:parent.width;height:1;color:RuntimeTheme.GGTheme.line}
    }
    Item {id:main;objectName:"dagMainViewport";y:toolbar.height;width:root.mainWidth;height:Math.max(0,root.height-y);clip:true
        NetworkWorkspaceLayout {id:workspace;objectName:"dagMainLayout";property string uiColorScope:"ui.widget.dag.workspace";anchors.fill:parent;prefix:"dag";bookTitles:["Producenter","Skapa","Förslag","Mätning"];page:desktop?0:1
            summaryPanel:Column {spacing:5
                Label {objectName:"dagSummaryScope";colorKey:"ui.dag.summary.caption";width:parent.width;text:root.lanOwned?"Privat LAN · "+root.number(root.dag.producer_count)+" producenter · 2 egna · lokal validering, nätkvittens separat":"Signerade förslag · "+root.producerCount+" lokala producenter · kontrollpunkt krävs för finalitet";font.pixelSize:9;color:RuntimeTheme.GGTheme.dim}
                Label {objectName:"dagLimitNotice";colorKey:"ui.dag.summary.limit";width:parent.width;visible:root.liveLimited||root.live.state==="ERROR";text:root.notice;font.pixelSize:9;color:root.liveLimited?RuntimeTheme.GGTheme.warning:RuntimeTheme.GGTheme.negative}
                Grid {id:metrics;width:parent.width;columns:width>=500?4:2;columnSpacing:8;rowSpacing:4
                    Repeater {model:4
                        Column {required property int index;readonly property var modelData:root.metricAt(index);objectName:"dagMetric";width:(metrics.width-(metrics.columns-1)*8)/metrics.columns;spacing:2
                            Label {colorKey:"ui.dag.metric.name";width:parent.width;text:modelData.name;font.pixelSize:9;color:RuntimeTheme.GGTheme.dim}
                            Label {colorKey:"ui.dag.metric.value";width:parent.width;text:modelData.value;font.pixelSize:18;font.bold:true;color:RuntimeTheme.GGTheme.bright
                                Rectangle {x:-5;y:-12;width:1;height:44;color:RuntimeTheme.GGTheme.line;visible:parent.parent.index>0}}
                            Label {colorKey:"ui.dag.metric.detail";width:parent.width;text:modelData.detail;font.pixelSize:9;color:RuntimeTheme.GGTheme.dim}
                        }
                    }
                }
            }
            measurementPanel:Item {id:timings;objectName:"dagMeasurementChart";readonly property real ceiling:Math.max(1,Math.max.apply(null,root.measurements.map(function(m){return m.total_ms})));readonly property real plotWidth:Math.max(0,width-35);readonly property real plotHeight:Math.max(1,height-41)
                GGStreamClock {id:sampleClock;objectName:"dagSampleClock";active:root.liveRunning&&root.activeView;observationTime:root.measurements.length?root.measurements[root.measurements.length-1].timestamp:NaN;cadenceMs:Number(root.live.interval_ms||125)}
                Head {property string uiColorScope:"ui.widget.dag.timings.head";title:"SIGNERING & TRANSAKTIONSTID";detail:"ms · "+root.measurements.length+" jobb"+(root.liveRunning&&isFinite(sampleClock.ageSeconds)?" · senast "+sampleClock.ageSeconds.toFixed(2)+" s":"")}
                Repeater {model:3
                    Item {required property int index;objectName:"dagMeasurementAxis";y:22+index*timings.plotHeight/2;width:parent.width;height:1
                        Rectangle {width:timings.plotWidth;height:1;color:RuntimeTheme.GGTheme.line;opacity:.6}
                        Label {colorKey:"ui.dag.timings.axis";x:timings.plotWidth+3;y:-5;width:32;text:(timings.ceiling*(1-index/2)).toFixed(timings.ceiling<10?1:0);font.pixelSize:8;color:RuntimeTheme.GGTheme.dim;horizontalAlignment:Text.AlignRight}
                    }
                }
                Item {x:0;y:22;width:timings.plotWidth;height:timings.plotHeight;clip:true
                    Row {width:parent.width;height:parent.height;spacing:2
                        Repeater {model:root.measurements.length
                            Item {id:sampleGroup;required property int index;readonly property var modelData:root.measurements[index]||({});objectName:"dagMeasurementGroup";width:Math.max(1,(timings.plotWidth-Math.max(0,root.measurements.length-1)*2)/Math.max(1,root.measurements.length));height:parent.height
                                Repeater {model:3
                                    GGMeasurementBar {required property int index;readonly property string kind:["producer","validation","total"][index];objectName:"dagMeasurementBar";x:index*parent.width/3;width:Math.max(1,parent.width/3-1);height:parent.height;fraction:Number(sampleGroup.modelData[["producer_ms","validation_ms","total_ms"][index]]||0)/timings.ceiling;barColor:root.seriesColor(kind);seriesKey:"ui.chart.dag."+kind}
                                }
                                HoverHandler {id:sampleHover}
                                ToolTip.visible:sampleHover.hovered;ToolTip.text:sampleHover.hovered?(modelData.kind==="async_proposal"?"Producent "+(Number(modelData.producer_index)+1):"Våg "+modelData.sequence)+" · "+root.millis(modelData.producer_ms)+" signering · "+root.millis(modelData.validation_ms)+" validering · "+root.millis(modelData.total_ms)+" totalt":""
                            }
                        }
                    }
                }
                Row {y:parent.height-13;spacing:8
                    Repeater {model:[{kind:"producer",label:"Signering"},{kind:"validation",label:"Validering"},{kind:"total",label:"Totalt"}]
                        Row {required property var modelData;spacing:4
                            Rectangle {id:seriesMarker;objectName:"dagLegendDot_"+modelData.kind;y:3;width:5;height:5;color:root.seriesColor(modelData.kind);GGColorTarget{target:seriesMarker;colorKey:"ui.chart.dag."+modelData.kind}}
                            Label {colorKey:"ui.chartlabel.dag."+modelData.kind;text:modelData.label;font.pixelSize:8;color:RuntimeTheme.GGTheme.dim}
                        }
                    }
                }
                Label {colorKey:"ui.dag.timings.empty";anchors.centerIn:parent;visible:!root.measurements.length;text:root.liveRunning?"Väntar på första mätningen…":"Inga uppmätta jobb ännu";font.pixelSize:9;color:RuntimeTheme.GGTheme.dim}
                Rectangle {objectName:"dagObservationAgeBar";anchors.bottom:parent.bottom;width:timings.plotWidth*sampleClock.phase;height:1;visible:root.liveRunning&&sampleClock.hasObservation;color:root.seriesColor("total");opacity:.65}
            }
            relationsPanel:BlockRelationsGraph {property string uiColorScope:"ui.widget.dag.graph";objectName:"dagBlockRelationsGraph";graph:root.graph;surfaceHost:root.surfaceHost}
            accountsPanel:Item {objectName:"dagProducersPanel"
                Head {property string uiColorScope:"ui.widget.dag.producers.head";title:"PRODUCENTER";detail:(root.dag.producers||[]).length?"sessionens mätvärden":"hämtad delvy"}
                Item {y:20;width:parent.width;height:15
                    Label {colorKey:"ui.dag.producer.column.node";width:parent.width*.30;text:"NOD";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim}
                    Label {colorKey:"ui.dag.producer.column.blocks";x:parent.width*.30;width:parent.width*.20;text:"FÖRSLAG";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim;horizontalAlignment:Text.AlignRight}
                    Label {colorKey:"ui.dag.producer.column.tx";x:parent.width*.53;width:parent.width*.17;text:"TX";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim;horizontalAlignment:Text.AlignRight}
                    Label {colorKey:"ui.dag.producer.column.seq";x:parent.width*.74;width:parent.width*.26;text:root.asynchronous?"MÄTT /s":"SEKVENS";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim;horizontalAlignment:Text.AlignRight}
                }
                ListView {objectName:"dagProducersList";y:35;width:parent.width;height:Math.max(0,parent.height-y-15);clip:true;model:root.producerRows.length;boundsBehavior:Flickable.StopAtBounds;ScrollBar.vertical:ScrollBar{}
                    delegate:Item {required property int index;readonly property var modelData:root.producerRows[index]||({});objectName:"dagProducerRow";width:ListView.view.width;height:25
                        Rectangle {id:producerMarker;x:1;y:10;width:5;height:5;radius:3;color:root.producerColor(modelData.index);GGColorTarget{target:producerMarker;colorKey:"ui.graph.block.producer."+modelData.index}}
                        Label {colorKey:"ui.dag.producer.name";x:12;y:5;width:parent.width*.30-12;text:"Producent "+(modelData.index+1);font.pixelSize:9}
                        Label {colorKey:"ui.dag.producer.blocks";x:parent.width*.30;y:5;width:parent.width*.20;text:modelData.blocks;font.pixelSize:9;horizontalAlignment:Text.AlignRight}
                        Label {colorKey:"ui.dag.producer.tx";x:parent.width*.53;y:5;width:parent.width*.17;text:modelData.transactions;font.pixelSize:9;horizontalAlignment:Text.AlignRight}
                        Label {colorKey:"ui.dag.producer.seq";x:parent.width*.74;y:5;width:parent.width*.26;text:root.asynchronous?typeof modelData.rate==="number"?modelData.rate.toFixed(1):"—":root.number(modelData.sequence);font.pixelSize:9;color:RuntimeTheme.GGTheme.dim;horizontalAlignment:Text.AlignRight}
                        Rectangle {anchors.bottom:parent.bottom;width:parent.width;height:1;color:RuntimeTheme.GGTheme.line;opacity:.6}
                    }
                }
                Label {objectName:"dagProducerScope";colorKey:"ui.dag.producer.scope";y:parent.height-13;width:parent.width;text:root.producerCount+" producenter · "+root.number(root.dag.worker_count)+" aktiva trådar · "+(root.lanOwned?"2 egna, övriga från LAN":"en dator");font.pixelSize:8;color:RuntimeTheme.GGTheme.dim}
            }
            historyPanel:Item {objectName:"dagProposalsViewport"
                Head {property string uiColorScope:"ui.widget.dag.proposals.head";title:"SENASTE FÖRSLAG";detail:root.rows.length+" st · ej finalitet"}
                Item {y:20;width:parent.width;height:15
                    Label {colorKey:"ui.dag.proposal.column.hash";width:parent.width*.38;text:"HASH / NOD";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim}
                    Label {colorKey:"ui.dag.proposal.column.rank";x:parent.width*.38;width:parent.width*.15;text:"RANG";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim;horizontalAlignment:Text.AlignRight}
                    Label {colorKey:"ui.dag.proposal.column.parents";x:parent.width*.55;width:parent.width*.16;text:"LÄNKAR";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim;horizontalAlignment:Text.AlignRight}
                    Label {colorKey:"ui.dag.proposal.column.tx";x:parent.width*.73;width:parent.width*.11;text:"TX";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim;horizontalAlignment:Text.AlignRight}
                    Label {colorKey:"ui.dag.proposal.column.status";x:parent.width*.87;width:parent.width*.13;text:"OK";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim}
                }
                ListView {objectName:"dagProposalsList";y:35;width:parent.width;height:Math.max(0,parent.height-y);clip:true;model:root.rows.length;boundsBehavior:Flickable.StopAtBounds;ScrollBar.vertical:ScrollBar{}
                    delegate:Item {required property int index;readonly property var modelData:root.rows[index]||({});objectName:"dagProposalRow";width:ListView.view.width;height:25
                        Label {colorKey:"ui.dag.proposal.hash";y:5;width:parent.width*.38;text:root.shortId(modelData.hash);font.pixelSize:9;color:RuntimeTheme.GGTheme.muted}
                        Label {colorKey:"ui.dag.proposal.rank";x:parent.width*.38;y:5;width:parent.width*.15;text:root.number(modelData.rank);font.pixelSize:9;horizontalAlignment:Text.AlignRight}
                        Label {colorKey:"ui.dag.proposal.parents";x:parent.width*.55;y:5;width:parent.width*.16;text:(modelData.parent_hashes||[]).length;font.pixelSize:9;horizontalAlignment:Text.AlignRight}
                        Label {colorKey:"ui.dag.proposal.tx";x:parent.width*.73;y:5;width:parent.width*.11;text:root.number(modelData.transaction_count);font.pixelSize:9;horizontalAlignment:Text.AlignRight}
                        Rectangle {x:parent.width*.87;y:10;width:5;height:5;radius:3;color:modelData.signature_verified?RuntimeTheme.GGTheme.cyan:RuntimeTheme.GGTheme.dim}
                        Label {colorKey:"ui.dag.proposal.node";x:parent.width*.87+8;y:5;width:parent.width*.13-8;text:Number(modelData.proposer_index)>=0?"P"+(modelData.proposer_index+1):"G";font.pixelSize:8;color:RuntimeTheme.GGTheme.cyan}
                        Rectangle {anchors.bottom:parent.bottom;width:parent.width;height:1;color:RuntimeTheme.GGTheme.line;opacity:.6}
                    }
                }
            }
            transferPanel:Column {objectName:"dagJobsViewport";spacing:4
                Item {width:parent.width;height:22
                    Label {colorKey:"ui.dag.job.title";y:5;width:Math.max(0,parent.width-(root.lanOwned?0:257));text:root.lanOwned?"PRIVAT LAN · EGNA PRODUCENTER":root.asynchronous?"TAKT & MANUELLA JOBB":"SKAPA PARALLELL VÅG";font.pixelSize:9;color:RuntimeTheme.GGTheme.muted}
                    Action {property string uiColorScope:"ui.control.dag.timed";objectName:"dagTimedWaves";visible:!root.lanOwned;anchors.right:liveAction.left;anchors.rightMargin:5;width:112;height:22;font.pixelSize:9;text:root.sequenceRunning?"Avbryt "+root.sequenceSent+" / 3":"3 vågor · 2 s";enabled:root.sequenceRunning||root.canAct&&root.running&&!root.liveRunning&&root.validJob&&root.sequenceCapacity;onClicked:root.startSequence()}
                    Action {id:liveAction;property string uiColorScope:"ui.control.dag.live";objectName:"dagLiveToggle";visible:!root.lanOwned;anchors.right:parent.right;width:root.liveRunning?137:128;height:22;font.pixelSize:9;text:root.liveRunning?"Ⅱ Pausa löpande":"▷ Kör löpande";enabled:root.canAct&&root.running&&!root.sequenceRunning&&(root.liveRunning||root.validJob&&root.validInterval&&!root.liveLimited);onClicked:root.toggleLive()}
                    Rectangle {anchors.bottom:parent.bottom;width:parent.width;height:1;color:RuntimeTheme.GGTheme.line}
                }
                Row {visible:!root.lanOwned;width:parent.width;spacing:7
                    Column {width:(parent.width-21)*.24;spacing:2
                        Label {colorKey:"ui.dag.job.blocks";text:root.asynchronous?"FÖRSLAG / MÅLINTERVALL":"FÖRSLAG / VÅG";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim}
                        CryptoField {property string uiColorScope:"ui.widget.dag.blocks";id:blockCount;objectName:"dagWaveBlocks";width:parent.width;height:24;text:"8";maximumLength:3;font.pixelSize:10;enabled:root.canAct&&!root.sequenceRunning&&!root.liveRunning;inputMethodHints:Qt.ImhDigitsOnly;Accessible.name:"Antal förslag i måltakten eller den manuella vågen"}
                    }
                    Column {width:(parent.width-21)*.23;spacing:2
                        Label {colorKey:"ui.dag.job.tx";text:"TX / FÖRSLAG";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim}
                        CryptoField {property string uiColorScope:"ui.widget.dag.tx";id:txPerBlock;objectName:"dagTxPerBlock";width:parent.width;height:24;text:"0";maximumLength:3;font.pixelSize:10;enabled:root.canAct&&!root.sequenceRunning&&!root.liveRunning;inputMethodHints:Qt.ImhDigitsOnly;Accessible.name:"Antal signerade testtransaktioner per förslag, noll för tomma förslag"}
                    }
                    Column {width:(parent.width-21)*.23;spacing:2
                        Label {colorKey:"ui.dag.job.interval";text:"INTERVALL · MS";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim}
                        CryptoField {property string uiColorScope:"ui.widget.dag.interval";id:intervalField;objectName:"dagLiveInterval";width:parent.width;height:24;text:"125";maximumLength:5;font.pixelSize:10;enabled:root.canAct&&!root.sequenceRunning&&!root.liveRunning;inputMethodHints:Qt.ImhDigitsOnly;Accessible.name:"Målintervall i millisekunder, 10 till 60000; producenterna kör oberoende"}
                    }
                    Column {width:(parent.width-21)*.30;spacing:2
                        Label {colorKey:"ui.dag.job.single";text:"ENSTAKA JOBB";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim}
                        Action {property string uiColorScope:"ui.control.dag.wave";objectName:"dagCreateWave";width:parent.width;height:24;text:"Skapa våg";enabled:root.canAct&&root.running&&root.validJob&&!root.sequenceRunning&&!root.liveRunning&&!root.liveLimited;onClicked:root.wave()}
                    }
                }
                Row {visible:root.lanOwned;width:parent.width;spacing:7
                    Action {property string uiColorScope:"ui.control.dag.lan.produce";objectName:"dagLanProduce";text:root.dagTransactionMode?root.primaryActionText:root.liveRunning?"Ⅱ Pausa egna 2":"▷ Kör egna 2";tip:root.primaryActionTip;enabled:root.primaryActionEnabled;onClicked:root.triggerPrimary()}
                    Action {objectName:"dagLanSettings";property string uiColorScope:"ui.control.dag.lan.settings";text:root.dagStress.supported===true?"DAG-stressprov & LAN":root.testTokens.enabled===true?"LAN & testtokenprov":"Parning & LAN-inställningar";enabled:true;onClicked:lanPopup.open()}
                    Label {colorKey:"ui.dag.lan.peer.count";y:6;text:(root.lan.authenticated_peers||[]).length+" autentiserade peers";color:RuntimeTheme.GGTheme.cyan}
                }
                Label {objectName:"dagOperationNotice";colorKey:"ui.dag.job.notice";width:parent.width;text:root.notice;font.pixelSize:9;color:root.operation.error||root.dag.error||(root.lanOwned&&(root.lan.last_error||root.dagStress.last_error))||root.live.state==="ERROR"?RuntimeTheme.GGTheme.negative:root.liveLimited?RuntimeTheme.GGTheme.warning:RuntimeTheme.GGTheme.dim}
            }
        }
    }
    Component {id:factsComponent
        Item {objectName:"dagFacts"
            Rectangle {width:1;height:parent.height;color:RuntimeTheme.GGTheme.line;visible:root.railVisible}
            NetworkRailLayout {property string uiColorScope:"ui.widget.dag.rail";objectName:"dagTelemetryLayout";prefix:"dag";x:12;y:6;width:Math.max(0,parent.width-24);height:Math.max(0,parent.height-12);titles:["MIN DAG-NOD","SIGNATURER & FÖRHANDSVY","SESSION & RESURSER","SENASTE JOBBET"]
                sections:[
                    Column {spacing:0
                        Head {property string uiColorScope:"ui.widget.dag.rail.status.head";title:"MIN DAG-NOD"}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.status";name:"Status";value:root.liveLabel;valueColor:root.liveLimited?RuntimeTheme.GGTheme.warning:root.liveRunning?RuntimeTheme.GGTheme.positive:RuntimeTheme.GGTheme.dim}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.engine";name:"Motor";value:"DAGoblin · experiment"}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.producers";name:"Producenter / trådar";value:root.number(root.dag.producer_count)+" / "+root.number(root.dag.worker_count)}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.peers";name:"Peers";value:root.lanOwned?(root.lan.authenticated_peers||[]).length+" autentiserade / "+root.number(root.lan.configured_peers)+" parade":"0 · inget P2P"}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.parents";name:"Föräldrar / förslag";value:"Högst "+root.number(root.limits.max_parents||7)}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.cadence";name:root.asynchronous?"Målintervall":"Vågintervall";value:typeof root.live.interval_ms==="number"?root.number(root.live.interval_ms)+" ms":"—"}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.target";name:"Mål · förslag / s";value:typeof root.live.target_proposal_bps==="number"?root.live.target_proposal_bps.toFixed(1):typeof root.live.interval_ms==="number"&&root.live.interval_ms>0?(Number(root.live.blocks)*1000/root.live.interval_ms).toFixed(1):"—"}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.measured";name:"Uppmätt / s · 5 s";value:root.graph.metrics&&typeof root.graph.metrics.bps==="number"?root.graph.metrics.bps.toFixed(1):"—";valueColor:RuntimeTheme.GGTheme.cyan}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.measured.tx";name:"Lokalt validerad TX / s";value:root.graph.metrics&&typeof root.graph.metrics.tps==="number"?root.graph.metrics.tps.toFixed(1):"—";valueColor:RuntimeTheme.GGTheme.cyan}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.session";name:"Session";value:root.shortId(root.dag.chain_id)}
                    },
                    Column {spacing:0
                        Head {property string uiColorScope:"ui.widget.dag.rail.sign.head";title:"SIGNATURER & FÖRHANDSVY"}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.sign";name:"Signaturkontroller";value:root.number(root.admission.signature_checks)}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.preview";name:"Accepterat i förhandsvy";value:root.number(root.preview.accepted);valueColor:RuntimeTheme.GGTheme.cyan}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.conflicts";name:"Konflikter / dubbletter";value:root.number(root.preview.conflicts)+" / "+root.number(root.preview.duplicates)}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.finality";name:"Finalitet";value:"Kontrollpunkt krävs";valueColor:RuntimeTheme.GGTheme.warning}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.finalized";name:"Kanoniskt finaliserade";value:root.number(root.dag.canonical_finalized)}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.test.tokens";visible:root.testTokens.enabled===true;name:"Testledger · kvitterad TX";value:root.number(root.testTokens.sequence);valueColor:RuntimeTheme.GGTheme.cyan}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.test.rate";visible:root.testTokens.enabled===true;name:"Testledger · TX/s";value:typeof root.tokenCircle.tps==="number"?root.tokenCircle.tps.toFixed(1):"—"}
                        Fact {objectName:"dagStressLocalCounts";property string uiColorScope:"ui.widget.dag.rail.stress.local";visible:root.dagStress.supported===true&&root.dagStress.enabled===true;name:"Prov · lokala förslag / TX";value:root.number(root.dagStress.blocks)+" / "+root.number(root.dagStress.transactions)}
                        Fact {objectName:"dagStressAckStatus";property string uiColorScope:"ui.widget.dag.rail.stress.ack.status";visible:root.dagStress.supported===true&&root.dagStress.enabled===true;name:"Prov · nätkvittens";value:root.hasDagAcknowledgement?"Alla tre bekräftade":"Ej bekräftad"}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.stress.ack.blocks";visible:root.dagStress.supported===true&&root.dagStress.enabled===true;name:"Kvitterade förslag / TX";value:root.hasDagAcknowledgement?root.number(root.dagStress.acknowledged_blocks)+" / "+root.number(root.dagStress.acknowledged_transactions):"—"}
                        Fact {objectName:"dagStressAckBlockRate";property string uiColorScope:"ui.widget.dag.rail.stress.ack.bps";visible:root.dagStress.supported===true&&root.dagStress.enabled===true;name:"Kvitterade förslag / s";value:root.acknowledgedRate("acknowledged_bps")}
                        Fact {objectName:"dagStressAckTransactionRate";property string uiColorScope:"ui.widget.dag.rail.stress.ack.tps";visible:root.dagStress.supported===true&&root.dagStress.enabled===true;name:"Kvitterad TX / s";value:root.acknowledgedRate("acknowledged_tps")}
                    },
                    Column {spacing:2
                        Head {property string uiColorScope:"ui.widget.dag.rail.quota.head";title:"SESSION & RESURSER"}
                        Quota {property string uiColorScope:"ui.widget.dag.rail.bytes";objectName:"dagBytesQuota";title:"Förslagsdata i RAM";used:root.admission.charged_bytes;limit:root.limits.max_session_bytes;valueText:root.bytes(used)+" / "+root.bytes(limit)}
                        Quota {property string uiColorScope:"ui.widget.dag.rail.records";objectName:"dagRecordsQuota";title:"Sparade förslag";used:root.running?Number(root.dag.blocks_admitted||0)+1:0;limit:root.limits.max_records;valueText:root.number(used)+" / "+root.number(limit)}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.rejected";name:"Avvisade / dubbletter";value:root.number(root.admission.rejected)+" / "+root.number(root.admission.duplicates)}
                    },
                    Column {spacing:0
                        Head {property string uiColorScope:"ui.widget.dag.rail.wave.head";title:"SENASTE JOBBET";detail:"uppmätt"}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.wave.blocks";name:"Förslag / TX";value:root.number(root.lastWave.blocks)+" / "+root.number(root.lastWave.transactions)}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.wave.produce";name:"Signering";value:root.millis(root.lastWave.producer_ms)}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.wave.validate";name:"Validering";value:root.millis(root.lastWave.validation_ms)}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.wave.total";name:"Total tid";value:root.millis(root.lastWave.total_ms)}
                    }
                ]
                eventsPanel:Item {
                    Head {property string uiColorScope:"ui.widget.dag.events.head";title:"HÄNDELSER";detail:root.events.length+" st"}
                    ListView {objectName:"dagEventsList";y:22;width:parent.width;height:Math.max(0,parent.height-y);clip:true;model:root.events.length;boundsBehavior:Flickable.StopAtBounds;ScrollBar.vertical:ScrollBar{}
                        delegate:Item {required property int index;readonly property var modelData:root.events[index]||({});objectName:"dagEventRow";width:ListView.view.width;height:32
                            Rectangle {y:5;width:5;height:5;radius:3;color:root.eventColor(modelData.kind)}
                            Label {colorKey:"ui.dag.event.kind";x:10;width:parent.width-10;text:String(modelData.kind||"Händelse");font.pixelSize:9;color:root.eventColor(modelData.kind)}
                            Label {colorKey:"ui.dag.event.message";x:10;y:14;width:parent.width-10;text:String(modelData.message||"");font.pixelSize:9;color:RuntimeTheme.GGTheme.dim}
                        }
                    }
                }
            }
        }
    }
    Loader {x:root.mainWidth;y:toolbar.height;width:root.railWidth;height:Math.max(0,root.height-y);active:root.railVisible;visible:active;sourceComponent:factsComponent}
    LanDagSetupPopup {id:lanPopup;parent:root.Window.window?root.Window.window.contentItem:root;placementAnchor:root;state:root.dag;setupCapabilities:(root.state.lan_dag||({})).dag_stress||({});surfaceHost:root.surfaceHost;canAct:root.canAct;localRunning:root.running&&!root.lanOwned;stopPending:root.stopRequested;operationError:root.stopError||String(root.operation.error||"");onActionRequested:function(name,args){root.run(name,args)};onPriorityStopRequested:root.run("dag_stop",{});onRefreshRequested:root.refreshRequested()}
    Popup {id:factsDrawer;objectName:"dagFactsDrawer";x:Math.max(0,root.width-width);y:toolbar.height;width:Math.min(360,root.width);height:Math.max(0,root.height-y);padding:0;modal:true;focus:true;closePolicy:Popup.CloseOnEscape|Popup.CloseOnPressOutside
        background:Frame {property string uiColorScope:"ui.widget.dag.drawer";color:RuntimeTheme.GGTheme.base}
        contentItem:Item {Action {property string uiColorScope:"ui.control.dag.drawer.close";anchors.right:parent.right;y:3;width:28;text:"×";enabled:true;onClicked:factsDrawer.close()}
            Loader {y:28;width:parent.width;height:Math.max(0,parent.height-y);active:factsDrawer.visible;sourceComponent:factsComponent}
        }
    }
}
