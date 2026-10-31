import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Window
import "."
import "." as RuntimeTheme

// Explicit pairing controls. Public documents never include producer/wallet keys.
Item {
    id:root;objectName:"lanDagSetupPopup"
    visible:false
    focus:visible
    z:9999
    property Item placementAnchor:null
    property bool positioned:false
    property color frameBorder:RuntimeTheme.GGTheme.dim
    property int frameRadius:4
    property var state:({})
    property var setupCapabilities:({})
    property var surfaceHost:null
    property bool canAct:true
    property bool localRunning:false
    property bool stopPending:false
    readonly property var lan:state.lan||({})
    readonly property var setup:state.lan_setup||({})
    readonly property bool owned:setup.active===true
    readonly property bool coordinator:setup.coordinator===true
    readonly property bool ready:lan.state==="READY"
    readonly property bool transportExhausted:!!lan.transport&&lan.transport.state==="EXHAUSTED"
    readonly property bool producing:!!state.live&&state.live.enabled===true
    readonly property var candidates:setup.invites||[]
    readonly property var tokens:state.test_tokens||({})
    readonly property var circle:state.token_circle||({})
    readonly property var hardware:state.dag_resources||({})
    readonly property var hardwareTest:hardware.test||({})
    readonly property bool hardwareTesting:hardwareTest.state==="RUNNING"
    property var draftBudget:null
    readonly property var resourceBudget:draftBudget||hardware.budget||({overall:100,cpu:100,gpu:100,ram:100,network:100})
    readonly property var resourcePreview:previewResources()
    function changeBudget(name,value){
        var next=Object.assign({},resourceBudget)
        next[name]=Math.round(value)
        draftBudget=next
        budgetCommit.restart()
    }
    Timer {id:budgetCommit;interval:180;onTriggered:{if(!root.owned){root.draftBudget=null;return}if(!root.canAct){restart();return}root.run("lan_resources",{budget:root.draftBudget})}}
    onHardwareChanged:{
        if(draftBudget&&hardware.budget&&["overall","cpu","gpu","ram","network"].every(function(name){return draftBudget[name]===hardware.budget[name]}))draftBudget=null
    }
    function previewResources(){
        var profile=hardwareTest.profile||({}),caps=profile.capacities_tps||({})
        var active=profile.active_resources||["cpu","ram","network"]
        var rows={},unknown=[],minimum=Infinity,bottlenecks=[]
        ;["cpu","gpu","ram","network"].forEach(function(name){
            var used=active.indexOf(name)>=0,c=caps[name],selected=Number(resourceBudget[name])
            var known=typeof c==="number"&&Number.isFinite(c)&&c>=0
            var ceiling=used&&known?c*selected/100:null
            rows[name]={active:used,selected:selected,relative:null,ceiling:ceiling}
            if(used&&!known)unknown.push(name)
            if(used&&known)minimum=Math.min(minimum,ceiling)
        })
        var count=Number(stressTransactions.text),facts=hardware.hardware||({}),cost=profile.wire_bytes_per_transaction
        var headroom=typeof facts.memory_total_bytes==="number"&&typeof facts.memory_available_bytes==="number"?Math.max(0,Math.min(facts.memory_total_bytes*Number(resourceBudget.ram)/100,facts.memory_available_bytes)-Number(hardware.memory_committed_bytes||0)):null
        var memoryLimit=headroom!==null&&typeof cost==="number"&&count>0&&Math.ceil(cost*count*16)>headroom
        var paused=memoryLimit||Number(resourceBudget.overall)===0||active.some(function(name){return rows[name].selected===0||rows[name].ceiling===0})
        if(unknown.length&&!paused)return {tps:null,bps:null,resources:rows,bottlenecks:[],state:"NEEDS_BENCHMARK"}
        var target=paused?0:minimum*Number(resourceBudget.overall)/100
        active.forEach(function(name){
            rows[name].relative=caps[name]?Math.min(rows[name].selected,target/caps[name]*100):0
            if(memoryLimit?name==="ram":paused?(rows[name].selected===0||rows[name].ceiling===0):Math.abs(rows[name].ceiling-minimum)<.000001)bottlenecks.push(name)
        })
        return {tps:target,bps:count>0?target/count:null,resources:rows,bottlenecks:bottlenecks,state:memoryLimit?"MEMORY_LIMIT":target?"ESTIMATED":"PAUSED"}
    }
    function resourceName(name){return ({overall:"Totalt",cpu:"CPU",gpu:"GPU",ram:"RAM",network:"Nätverk"})[name]||name}
    function relativeResourceText(name){
        if(name==="overall")return "Andel av kapaciteten vid den aktuella flaskhalsen"
        var row=resourcePreview.resources[name]
        if(!row||!row.active)return "Används inte av denna DAG-backend"
        if(row.relative===null)return "Relativt behov: okänt · kör hårdvarutest"
        return "Relativt behov: "+row.relative.toFixed(1)+" % · eget tak: "+row.selected.toFixed(0)+" %"+(resourcePreview.bottlenecks.indexOf(name)>=0?" · flaskhals":"")
    }
    function resourceEstimateText(){
        if(resourcePreview.state==="MEMORY_LIMIT")return "RAM-budgeten räcker inte för valt block · teoretiskt tak: 0 TX/s"
        if(resourcePreview.tps===null)return "Teoretiskt tak: okänt · hårdvarutest behövs"
        return "Teoretiskt tak: "+resourcePreview.tps.toFixed(1)+" TX/s · "+measuredRate(resourcePreview.bps)+" block/s · "+stressTransactions.text+" TX/block · flaskhals: "+resourcePreview.bottlenecks.map(resourceName).join(", ")
    }
    // Resolve capability fallback after the owner has bound both snapshots.
    property bool bindingsReady:false
    Component.onCompleted:bindingsReady=true
    readonly property var stress:bindingsReady?(state.dag_stress||(!owned?setupCapabilities:({}))):({})
    readonly property var stressLimits:stress.limits||({})
    readonly property bool stressSupported:stress.supported===true
    readonly property bool stressRunning:["STARTING","RUNNING","STOPPING"].indexOf(String(stress.state||""))>=0
    readonly property bool stressParticipantsReady:(stress.participants||[]).length===3&&(stress.participants||[]).every(function(peer){return peer.opted_in===true})
    readonly property bool stressSettingsValid:boundedInteger(stressDuration.text,stressLimits.min_duration_ms,stressLimits.max_duration_ms,1000)&&boundedInteger(stressTransactions.text,1,stressLimits.max_tx_per_block,1)&&boundedInteger(stressInterval.text,stressLimits.min_interval_ms,stressLimits.max_interval_ms,1)
    readonly property bool canStartStress:root.canAct&&root.ready&&!root.transportExhausted&&root.coordinator&&root.stressSupported&&stress.enabled===true&&stress.local_opt_in===true&&stress.role==="COORDINATOR"&&stress.can_start===true&&stressParticipantsReady&&!stressRunning&&!hardwareTesting&&!circleRunning&&stressSettingsValid&&["MEMORY_LIMIT","PAUSED"].indexOf(resourcePreview.state)<0
    readonly property bool circleRunning:["RUNNING","STOPPING"].indexOf(String(circle.state||""))>=0
    readonly property bool circleFinished:["COMPLETE","STOPPED","ERROR","TIME_BUDGET","NO_TRANSFERS"].indexOf(String(circle.state||""))>=0
    readonly property bool circleSettingsValid:/^[0-9]{1,2}$/.test(circleBatch.text)&&Number(circleBatch.text)>=1&&Number(circleBatch.text)<=16&&/^[0-9]{1,2}$/.test(circleDuration.text)&&Number(circleDuration.text)>=1&&Number(circleDuration.text)<=60
    readonly property bool allTokenOptedIn:candidates.length===3&&candidates.every(function(peer){return peer.allow_test_tokens===true})
    readonly property bool allDagOptedIn:candidates.length===3&&candidates.every(function(peer){return peer.allow_dag_transactions===true})
    readonly property bool canStart:root.canAct&&!root.owned&&!root.localRunning&&labelField.text.trim().length>0&&/^[0-9]{4,5}$/.test(portField.text)&&Number(portField.text)>=1024&&Number(portField.text)<=65535
    property string formError:""
    property string operationError:""
    signal actionRequested(string name,var args)
    signal priorityStopRequested()
    signal refreshRequested()
    width:Math.min(720,parent?Math.max(0,parent.width-24):720)
    height:Math.min(650,parent?Math.max(0,parent.height-32):650)
    function keepWithinParent(){
        if(!positioned||!parent)return
        x=Math.max(0,Math.min(x,parent.width-width))
        y=Math.max(12,Math.min(y,Math.max(12,parent.height-height-12)))
    }
    function open(){
        if(!positioned){
            var anchor=placementAnchor||parent
            var origin=anchor&&parent?anchor.mapToItem(parent,0,0):Qt.point(0,0)
            x=origin.x+(anchor?anchor.width-width:0)/2
            y=origin.y+(anchor?anchor.height-height:0)/2
            positioned=true
        }
        keepWithinParent()
        visible=true
        forceActiveFocus()
    }
    function close(){visible=false}
    Keys.onEscapePressed:root.close()
    onWidthChanged:keepWithinParent()
    onHeightChanged:keepWithinParent()
    Connections {
        target:root.parent
        function onWidthChanged(){root.keepWithinParent()}
        function onHeightChanged(){root.keepWithinParent()}
    }
    Rectangle {anchors.fill:parent;anchors.margins:1;color:RuntimeTheme.GGTheme.panel;radius:Math.max(0,root.frameRadius-1)}
    LedgerBorder {
        anchors.fill:parent;color:root.frameBorder;radius:root.frameRadius
        topGaps:[{start:title.x,end:title.x+title.width},{start:frameControls.x-3,end:frameControls.x+frameControls.width+3}]
    }
    MouseArea {anchors.fill:parent;acceptedButtons:Qt.LeftButton;onClicked:{}}
    GGText {
        id:title;objectName:"lanSetupTitle";colorKey:"ui.lan.title"
        x:12;y:-8;width:Math.min(implicitWidth,Math.max(0,root.width-frameControls.width-36));height:18
        text:"DAGoblin · privat LAN-session";font.family:"monospace";font.pixelSize:12;font.bold:true
        color:RuntimeTheme.GGTheme.bright;elide:Text.ElideRight;verticalAlignment:Text.AlignVCenter
    }
    Row {
        id:frameControls;z:3;anchors.right:parent.right;anchors.rightMargin:9;y:-12;spacing:3
        Item {
            objectName:"lanDragBar";width:26;height:26
            Accessible.name:"Flytta LAN-panel"
            Grid {
                anchors.centerIn:parent;columns:2;spacing:3
                Repeater {model:6;Rectangle {width:2;height:2;radius:1;color:RuntimeTheme.GGTheme.dim}}
            }
            MouseArea {
                objectName:"lanDragHandle";anchors.fill:parent
                drag.target:root;drag.smoothed:false
                drag.minimumX:0;drag.minimumY:12
                drag.maximumX:root.parent?Math.max(0,root.parent.width-root.width):4096
                drag.maximumY:root.parent?Math.max(12,root.parent.height-root.height-12):4096
                cursorShape:pressed?Qt.ClosedHandCursor:Qt.OpenHandCursor
            }
        }
        CryptoButton {
            id:closeButton;objectName:"lanSetupCloseButton";property string uiColorScope:"ui.lan.close"
            width:26;height:26;padding:0;text:"×";Accessible.name:"Stäng LAN-panel"
            background:Rectangle {color:closeButton.hovered||closeButton.down||closeButton.visualFocus?RuntimeTheme.GGTheme.raised:"transparent";border.width:closeButton.visualFocus?1:0;border.color:root.frameBorder}
            onClicked:root.close()
        }
    }
    function run(name,args){if(!canAct)return;if((name==="lan_produce"||name==="lan_pause")&&stress.enabled===true)return;if(name==="lan_circle_start"&&transportExhausted)return;if(name==="lan_dag_stress_start"&&!canStartStress)return;if(name==="lan_dag_stress_stop"&&(!stressSupported||stress.role!=="COORDINATOR"||!stressRunning))return;formError="";actionRequested(name,args||{})}
    function copy(value){if(surfaceHost&&surfaceHost.tmogCopy)surfaceHost.tmogCopy(String(value||""))}
    function wholeTokenAtomic(){var d=Number(root.tokens.decimals);return Number.isInteger(d)&&d>=0&&d<=18?"1"+"0".repeat(d):""}
    function tokenAmount(value){
        var text=String(value===undefined?"":value),d=Number(root.tokens.decimals)
        if(!/^[0-9]+$/.test(text)||!Number.isInteger(d)||d<0||d>18)return "—"
        if(d===0)return text
        while(text.length<=d)text="0"+text
        var fraction=text.slice(-d).replace(/0+$/,"")
        return text.slice(0,-d)+(fraction?"."+fraction:"")
    }
    function circleCode(value){
        var text=String(value||"")
        return !text?"":/^[A-Z][A-Z0-9_]{0,95}$/.test(text)?text:"Okänd orsak"
    }
    function circleDiagnostic(value){
        var text=String(value||"")
        return /^[A-Za-z][A-Za-z0-9_]{0,47}$/.test(text)?text:""
    }
    function diagnosticParts(details){
        details=details||({})
        var parts=[],operation=circleDiagnostic(details.operation),stage=circleDiagnostic(details.stage),errorClass=circleDiagnostic(details.error_class)
        if(operation)parts.push("Operation: "+operation)
        if(stage)parts.push("Steg: "+stage)
        if(errorClass)parts.push("Felklass: "+errorClass)
        return parts
    }
    function transportErrorText(){
        var error=root.lan.last_error?(resultCode(root.lan.last_error)||"Okänd orsak"):""
        var age=diagnosticAge(root.lan.last_error_at)
        return error?["Senast registrerat transportfel"+(age?" ("+age+")":"")+": "+error].concat(diagnosticParts(root.lan.last_error_details)).join(" · "):""
    }
    function circleDetails(){
        var error=circleCode(root.circle.last_error),reason=circleCode(root.circle.stop_reason)
        var parts=[]
        if(error)parts.push("Fel: "+error)
        if(reason)parts.push("Stopporsak: "+reason)
        if(error)parts=parts.concat(diagnosticParts(root.circle.last_error_details))
        return parts.join(" · ")
    }
    function circleSyncText(){
        if(root.circleRunning)return root.circle.all_peers_synced===true?"Pågår · senaste kvittokedjan bekräftad av alla tre peers; slutkontroll återstår.":"Pågår · gemensam kvittokedja ännu inte bekräftad."
        if(root.circle.all_peers_synced===true)return "Avslutat · alla tre peers har bekräftat samma kvittokedja."
        if(root.circleFinished)return Number(root.circle.transactions)>0?"Avslutat · delresultat: alla tre peers har inte bekräftat samma kvittokedja.":"Avslutat · gemensam kvittokedja kunde inte bekräftas."
        return "Redo · gemensam kvittokedja verifieras under cirkelprovet."
    }
    function boundedInteger(text,minimum,maximum,scale){
        if(!/^(0|[1-9][0-9]{0,8})$/.test(String(text))||typeof minimum!=="number"||typeof maximum!=="number"||!isFinite(minimum)||!isFinite(maximum))return false
        var value=Number(text)*scale
        return Number.isSafeInteger(value)&&value>=minimum&&value<=maximum
    }
    function measured(value){return typeof value==="number"&&isFinite(value)&&value>=0}
    function measuredNumber(value){return measured(value)?String(value):"—"}
    function measuredRate(value){return measured(value)?value.toFixed(1):"—"}
    function stressAckText(){
        if(stress.all_peers_synced!==true||!measured(stress.acknowledged_blocks)||!measured(stress.acknowledged_transactions))return "Nätkvittens: — · gemensam leverans ännu inte bekräftad av alla tre."
        return "Nätkvittens från alla tre: "+measuredNumber(stress.acknowledged_blocks)+" förslag · "+measuredNumber(stress.acknowledged_transactions)+" DAG-TX · "+measuredRate(stress.acknowledged_bps)+" förslag/s · "+measuredRate(stress.acknowledged_tps)+" TX/s"
    }
    function stressDetails(){
        var parts=[],error=circleCode(stress.last_error),reason=circleCode(stress.stop_reason)
        if(error)parts.push("Fel: "+error)
        if(reason)parts.push("Stopporsak: "+reason)
        return parts.join(" · ")
    }
    function resultEnum(value,allowed){return typeof value==="string"&&allowed.indexOf(value)>=0?value:null}
    function resultNumber(value,integer,maximum){return typeof value==="number"&&isFinite(value)&&value>=0&&value<=maximum&&(!integer||Number.isSafeInteger(value))?value:null}
    function resultCode(value){return typeof value==="string"&&/^GG_[A-Z0-9_]{1,80}$/.test(value)&&!/[0-9a-f]{16,}/i.test(value)?value:null}
    function resultTime(value){return resultNumber(value,false,4102444800)}
    function diagnosticAge(value){
        var at=resultTime(value),now=Date.now()/1000
        if(at===null||at<=0||at>now)return ""
        var seconds=Math.floor(now-at)
        return seconds<60?seconds+" s sedan":seconds<3600?Math.floor(seconds/60)+" min sedan":Math.floor(seconds/3600)+" h sedan"
    }
    function transportOperation(value){return resultEnum(value,["PAGE","GET","INCOMING","TOKEN_STATUS","TOKEN_SYNC","TOKEN_SUBMIT","TOKEN_APPLY","CIRCLE_SIGN","CIRCLE_END","DAG_STRESS_PREPARE","DAG_STRESS_BEGIN","DAG_STRESS_STOP","DAG_STRESS_STATUS"])}
    function transportStage(value){return resultEnum(value,["ACCEPT","CHECK","WAIT","CONNECT","AUTH","SEND","RECEIVE","VALIDATE","EXECUTE"])}
    function transportDiagnostics(){
        var source=root.lan.transport
        if(!source||typeof source!=="object"||Array.isArray(source))return null
        var counters=source.counters||({}),drops=counters.admission_drops||({}),history=[],rows=Array.isArray(source.history)?source.history:[]
        for(var i=Math.max(0,rows.length-32);i<rows.length;i++){
            var row=rows[i]
            if(!row||typeof row!=="object"||Array.isArray(row))continue
            var code=resultCode(row.code),at=resultTime(row.at)
            if(code===null||at===null)continue
            history.push({at:at,operation:transportOperation(row.operation),stage:transportStage(row.stage),code:code,peer_label:resultPeerLabel(row.peer_label),expected:typeof row.expected==="boolean"?row.expected:null,reason:resultEnum(row.reason,["","RATE","HANDLERS","SESSION","BYTES"])})
        }
        var details=root.lan.last_error_details||({})
        return {state:resultEnum(source.state,["ACTIVE","EXHAUSTED","STOPPED"]),exhausted_reason:resultEnum(source.exhausted_reason,["","SESSION","BYTES","FRAMES"]),
            connections_admitted:resultNumber(source.connections_admitted,true,Number.MAX_SAFE_INTEGER),active_handlers:resultNumber(source.active_handlers,true,4),
            counters:{failures:resultNumber(counters.failures,true,Number.MAX_SAFE_INTEGER),expected_closures:resultNumber(counters.expected_closures,true,Number.MAX_SAFE_INTEGER),successes:resultNumber(counters.successes,true,Number.MAX_SAFE_INTEGER),
                admission_drops:{RATE:resultNumber(drops.RATE,true,Number.MAX_SAFE_INTEGER),HANDLERS:resultNumber(drops.HANDLERS,true,Number.MAX_SAFE_INTEGER),SESSION:resultNumber(drops.SESSION,true,Number.MAX_SAFE_INTEGER),BYTES:resultNumber(drops.BYTES,true,Number.MAX_SAFE_INTEGER)}},
            last_failure:{code:resultCode(root.lan.last_error),at:resultTime(root.lan.last_error_at),transport:{operation:transportOperation(details.operation),stage:transportStage(details.stage),error_class:resultEnum(details.error_class,["TimeoutError","ConnectionResetError","ConnectionRefusedError","BrokenPipeError","OSError","ValueError","TypeError","JSONDecodeError","Exception"])}},history:history,history_omitted:0}
    }
    function transportSummaryText(){
        var value=transportDiagnostics()
        if(value===null||value.state===null)return ""
        var title=value.state==="EXHAUSTED"?"sessionsgräns nådd · "+(value.exhausted_reason||"orsak saknas")+" · nya prov spärrade":value.state==="STOPPED"?"stoppad":"mottagning aktiv"
        return "Transport · "+title+" · anslutningar "+measuredNumber(value.connections_admitted)+" · hanterare "+measuredNumber(value.active_handlers)+"\nRegistrerat: fel "+measuredNumber(value.counters.failures)+" · väntade stängningar "+measuredNumber(value.counters.expected_closures)+" · lyckade anrop "+measuredNumber(value.counters.successes)
    }
    function transportHistoryText(){
        var value=transportDiagnostics()
        if(value===null)return ""
        var parts=[],drops=value.counters.admission_drops
        for(var name in drops)if(drops[name]!==null&&drops[name]>0)parts.push(name+" "+drops[name])
        var lines=parts.length?["Avvisade anslutningar · "+parts.join(" · ")]:[]
        for(var i=Math.max(0,value.history.length-3);i<value.history.length;i++){
            var row=value.history[i],age=diagnosticAge(row.at),kind=row.expected===true?"Väntad stängning":row.expected===false?"Registrerat fel":"Registrerad händelse"
            lines.push(kind+" · "+[row.operation,row.stage,row.code,row.peer_label,age].filter(function(part){return !!part}).join(" · "))
        }
        return lines.join("\n")
    }
    function resultPhase(value){return resultEnum(value,["PREPARE","BEGIN","PRODUCE","STOP","CONVERGENCE","CLEANUP","FINALIZE","FINAL_EVIDENCE"])}
    function resultState(value){return resultEnum(value,["IDLE","STARTING","RUNNING","STOPPING","STOPPED","COMPLETE","ERROR","TIME_BUDGET","LIMIT_REACHED","UNOBSERVED"])}
    function resultTransport(){
        var details=stress.last_error_details||({})
        return {operation:resultEnum(details.operation,["DAG_STRESS_PREPARE","DAG_STRESS_BEGIN","DAG_STRESS_STOP","DAG_STRESS_STATUS"]),stage:resultEnum(details.stage,["CHECK","WAIT","CONNECT","AUTH","SEND","RECEIVE","VALIDATE","EXECUTE"]),error_class:resultEnum(details.error_class,["TimeoutError","ConnectionResetError","ConnectionRefusedError","BrokenPipeError","OSError","ValueError","TypeError","JSONDecodeError","Exception"])}
    }
    function resultPhaseTimes(){
        var result={},source=stress.phase_ms||({}),names=["PREPARE","BEGIN","PRODUCE","STOP","CONVERGENCE","CLEANUP","FINALIZE"]
        for(var i=0;i<names.length;i++)result[names[i]]=resultNumber(source[names[i]],false,600000)
        return result
    }
    function phaseTitle(value){var names={PREPARE:"Förberedelse",BEGIN:"Start",PRODUCE:"Produktion",STOP:"Stopp",CONVERGENCE:"Samstämmighet",CLEANUP:"Städning",FINALIZE:"Avslut",FINAL_EVIDENCE:"Slutkontroll"};return resultPhase(value)?names[value]:""}
    function stressPhaseSummary(){
        var parts=[],phase=resultPhase(stress.failure_phase),polls=resultNumber(stress.status_polls,true,1000000)
        if(phase)parts.push("Fel i fas: "+phaseTitle(phase))
        if(polls!==null)parts.push("Statusfrågor: "+polls)
        return parts.join(" · ")
    }
    function stressPhaseTimings(){
        var parts=[],times=resultPhaseTimes()
        for(var name in times)if(times[name]!==null)parts.push(phaseTitle(name)+" "+times[name].toFixed(1)+" ms")
        return parts.length?"Faser · "+parts.join(" · "):""
    }
    function stressTransportText(){return diagnosticParts(resultTransport()).join(" · ")}
    function resultPeerLabel(value){return typeof value==="string"&&/^[A-Za-zÅÄÖåäöÉé][A-Za-zÅÄÖåäöÉé0-9 _-]{0,63}$/.test(value)&&!/[0-9a-f]{16,}/i.test(value)&&!/[A-Za-z0-9]{24,}/.test(value)&&!/[0-9a-f]{8}-[0-9a-f]{4}-/i.test(value)?value:""}
    function resultLabel(value,index){return resultPeerLabel(value)||"Apparat "+(index+1)}
    function stressResultDocument(){
        var status=resultState(stress.state)
        if(!stressSupported||stress.enabled!==true||status===null)return null
        var blocks=resultNumber(stress.acknowledged_blocks,true,Number.MAX_SAFE_INTEGER),transactions=resultNumber(stress.acknowledged_transactions,true,Number.MAX_SAFE_INTEGER)
        var confirmed=stress.all_peers_synced===true&&blocks!==null&&transactions!==null,participants=[],source=Array.isArray(stress.participants)?stress.participants:[]
        for(var i=0;i<Math.min(3,source.length);i++){var peer=source[i]||({});participants.push({label:resultLabel(peer.label,i),state:resultState(peer.state)})}
        return {schema:"gg.lan-dag-stress.result.v1",state:status,
            parameters:{duration_ms:resultNumber(stress.duration_ms,true,600000),transactions_per_block:resultNumber(stress.transactions_per_block,true,Number.MAX_SAFE_INTEGER),interval_ms:resultNumber(stress.interval_ms,true,60000)},
            local:{blocks:resultNumber(stress.blocks,true,Number.MAX_SAFE_INTEGER),transactions:resultNumber(stress.transactions,true,Number.MAX_SAFE_INTEGER),elapsed_ms:resultNumber(stress.elapsed_ms,false,600000)},
            acknowledgement:{confirmed:confirmed,basis:confirmed?resultEnum(stress.acknowledgement_basis,["STOP_OBSERVATIONS","STOP_AND_STATUS_OBSERVATIONS"]):null,blocks:confirmed?blocks:null,transactions:confirmed?transactions:null,bps:confirmed?resultNumber(stress.acknowledged_bps,false,Number.MAX_SAFE_INTEGER):null,tps:confirmed?resultNumber(stress.acknowledged_tps,false,Number.MAX_SAFE_INTEGER):null},
            failure:{code:resultCode(stress.last_error),reason:resultEnum(stress.stop_reason,["DURATION","CANCELLED","SOFTWARE_PROFILE_LIMIT","FAILED"]),phase:resultPhase(stress.failure_phase),transport:resultTransport()},
            phase_ms:resultPhaseTimes(),status_polls:resultNumber(stress.status_polls,true,1000000),participants:participants,transport_diagnostics:transportDiagnostics()}
    }
    function copyStressResult(){
        var result=stressResultDocument()
        if(result===null)return
        var diagnostics=result.transport_diagnostics,text=JSON.stringify(result)
        while(text.length>4000&&diagnostics&&diagnostics.history.length>0){
            diagnostics.history.shift();diagnostics.history_omitted++
            text=JSON.stringify(result)
        }
        if(text.length>4000){formError="Provresultatet är för stort för att kopieras säkert (4000 tecken).";return}
        copy(text)
    }
    function startOptions(options){if(stressSupported&&dagOptIn.checked)options.allow_dag_transactions=true;return options}
    function sessionOptions(){var options={label:"GG LAN",distribute:true,enable_test_tokens:root.setup.allow_dag_transactions!==true&&root.allTokenOptedIn};if(root.setup.allow_dag_transactions===true&&root.allDagOptedIn)options.enable_dag_transactions=true;return options}
    function command(label){return (label==="Termux"?'python':'python3')+' gg-cli.py --foreground --command "lan.start label='+label+' auto_produce=false'+(root.setup.allow_test_tokens===true?' allow_test_tokens=true':'')+(root.setup.allow_dag_transactions===true?' allow_dag_transactions=true':'')+'" --bootstrap-file gg-lan-bootstrap.json'}
    function addPasted(){try{var value=JSON.parse(inviteInput.text);run("lan_peer_add",{invite:value});inviteInput.text=""}catch(error){formError="Klistra in en signerad publik inbjudan som JSON."}}
    function joinBootstrap(path){if(root.canStart)root.run("lan_join_file",startOptions({path:String(path),label:labelField.text.trim(),port:Number(portField.text),bind_host:"auto",allow_test_tokens:tokenOptIn.checked}))}
    component Label:GGText {font.family:"monospace";font.pixelSize:10;color:RuntimeTheme.GGTheme.text;textFormat:Text.PlainText;wrapMode:Text.Wrap}
    component Action:CryptoButton {height:27;font.pixelSize:10;enabled:root.canAct}
    component Section:Rectangle {color:"transparent";border.width:1;border.color:RuntimeTheme.GGTheme.line;width:body.width;radius:2}
    component BudgetRow:Column {
        required property string resource
        width:parent.width;spacing:2
        Row {width:parent.width;spacing:7
            Label {width:65;height:26;verticalAlignment:Text.AlignVCenter;text:root.resourceName(resource)}
            Slider {
                id:budgetSlider;objectName:"lanResource_"+resource
                width:Math.max(60,parent.width-129);height:26
                from:0;to:100;stepSize:1
                value:Number(root.resourceBudget[resource])
                enabled:root.canAct&&root.owned&&(resource!=="gpu"||(root.hardware.hardware||{}).gpu_compute_supported===true)
                Accessible.name:root.resourceName(resource)+" resurstak i procent"
                onMoved:root.changeBudget(resource,value)
            }
            Label {objectName:"lanResourceValue_"+resource;width:50;height:26;verticalAlignment:Text.AlignVCenter;text:Math.round(budgetSlider.value)+" %";horizontalAlignment:Text.AlignRight}
        }
        Label {objectName:"lanResourceRelative_"+resource;width:parent.width;text:root.relativeResourceText(resource);font.pixelSize:9;color:RuntimeTheme.GGTheme.dim}
    }
    component Line:Rectangle {width:parent.width;height:1;color:RuntimeTheme.GGTheme.line}
    Item {
        anchors.fill:parent;anchors.margins:12;anchors.topMargin:20
        ScrollView {anchors.fill:parent;clip:true;contentWidth:availableWidth
            Column {id:body;width:parent.width;spacing:8
                Label {colorKey:"ui.lan.scope";width:parent.width;text:"Tre parade peers · två egna producenter per apparat. Riktiga signerade förslag över TCP; ingen kanonisk finalitet eller finansiell handel.";color:RuntimeTheme.GGTheme.dim}
                Row {width:parent.width;spacing:8
                    Label {objectName:"lanSetupStatus";colorKey:"ui.lan.status";width:parent.width-146;text:root.owned?String(root.lan.state||"STARTING")+" · "+String(root.lan.endpoint?root.lan.endpoint.host+":"+root.lan.endpoint.port:"")+" · "+(root.lan.authenticated_peers||[]).length+" autentiserade peers":"Ingen LAN-peer startad";color:root.ready?RuntimeTheme.GGTheme.positive:RuntimeTheme.GGTheme.dim}
                    Action {width:30;text:"↻";enabled:root.canAct;onClicked:root.refreshRequested()}
                    Action {objectName:"lanPriorityStop";width:100;text:root.stopPending?"Stoppar…":"■ Stoppa";enabled:root.owned&&!root.stopPending;onClicked:root.priorityStopRequested()}
                }
                Label {objectName:"lanSetupError";colorKey:"ui.lan.error";width:parent.width;visible:text.length>0;text:root.formError||root.operationError||String(root.setup.announcement_error||"")||root.transportErrorText();color:RuntimeTheme.GGTheme.negative}
                Label {objectName:"lanTransportStatus";colorKey:"ui.lan.transport.status";width:parent.width;visible:text.length>0;text:root.transportSummaryText();color:root.transportExhausted?RuntimeTheme.GGTheme.negative:RuntimeTheme.GGTheme.dim;font.pixelSize:9}
                Label {objectName:"lanTransportHistory";colorKey:"ui.lan.transport.history";width:parent.width;visible:text.length>0;text:root.transportHistoryText();color:RuntimeTheme.GGTheme.dim;font.pixelSize:9}
                Section {height:startBody.height+18
                    Column {id:startBody;x:9;y:9;width:parent.width-18;spacing:7
                        Label {colorKey:"ui.lan.step.start";text:"1 · Starta koordinator eller anslut den här datorn";font.bold:true}
                        Row {width:parent.width;spacing:7
                            CryptoField {id:labelField;objectName:"lanLabel";property string uiColorScope:"ui.lan.field.label";width:Math.max(70,parent.width-229);height:27;text:Qt.platform.os==="linux"?"GG Linux":"GG Windows";maximumLength:64;enabled:root.canAct&&!root.owned&&!root.localRunning;placeholderText:"Nodnamn"}
                            CryptoField {id:portField;objectName:"lanPort";property string uiColorScope:"ui.lan.field.port";width:75;height:27;text:"16120";maximumLength:5;enabled:labelField.enabled;inputMethodHints:Qt.ImhDigitsOnly;Accessible.name:"Privat TCP-port"}
                            Action {objectName:"lanStart";width:140;text:"Starta LAN · auto";enabled:root.canStart;onClicked:root.run("lan_start",root.startOptions({label:labelField.text.trim(),port:Number(portField.text),bind_host:"auto",allow_test_tokens:tokenOptIn.checked}))}
                        }
                        CryptoToggle {id:tokenOptIn;objectName:"lanAllowTestTokens";property string uiColorScope:"ui.lan.token.optin";width:parent.width;text:"Tillåt privata GG-LAN-testtokens och koordinatorstyrt cirkelprov";enabled:labelField.enabled;checked:false;onCheckedChanged:if(checked)dagOptIn.checked=false}
                        CryptoToggle {id:dagOptIn;objectName:"lanAllowDagTransactions";property string uiColorScope:"ui.lan.dag.optin";width:parent.width;visible:root.stressSupported;text:"Tillåt signerade DAG-testtransaktioner och koordinatorstyrt, tidsbegränsat prov med tre apparater";enabled:labelField.enabled&&root.stressSupported;checked:false;onCheckedChanged:if(checked)tokenOptIn.checked=false}
                        Action {objectName:"lanBootstrapJoin";text:"Anslut med publik bootstrap…";enabled:root.canStart;onClicked:bootstrapJoinFile.open()}
                        Label {colorKey:"ui.lan.join.note";width:parent.width;text:"Har Windows redan startat koordinatorn? Läs dess delade gg-lan-bootstrap.json här för att ansluta. Koordinatorn godkänner sedan de tre apparaterna.";color:RuntimeTheme.GGTheme.dim;font.pixelSize:9}
                        Label {colorKey:"ui.lan.start.note";width:parent.width;text:root.localRunning&&!root.owned?"Stoppa den lokala DAG-sessionen före LAN-start.":"Lokal privat IPv4 väljs automatiskt först när du startar. Ingenting ansluts vid vanlig statusvisning.";color:RuntimeTheme.GGTheme.dim;font.pixelSize:9}
                    }
                }
                Section {height:bootstrapBody.height+18
                    Column {id:bootstrapBody;x:9;y:9;width:parent.width-18;spacing:7
                        Label {colorKey:"ui.lan.step.bootstrap";text:"2 · Dela publik bootstrap till Linux och Termux";font.bold:true}
                        Row {spacing:7
                            Action {objectName:"lanBootstrapSave";text:"Spara bootstrap…";enabled:root.canAct&&root.owned&&root.coordinator&&!!root.setup.bootstrap;onClicked:bootstrapFile.open()}
                            Action {objectName:"lanBootstrapCopy";text:"Kopiera publik JSON";enabled:root.owned&&!!root.setup.bootstrap;onClicked:root.copy(JSON.stringify(root.setup.bootstrap,null,2))}
                            Action {text:"Spara egen inbjudan…";enabled:root.canAct&&root.owned;onClicked:inviteExport.open()}
                            Action {objectName:"lanAnnounce";text:"Annonsera igen";visible:root.owned&&!root.coordinator;enabled:root.canAct&&!root.ready;onClicked:root.run("lan_announce",{})}
                        }
                        Label {colorKey:"ui.lan.bootstrap.note";width:parent.width;text:"I Linux Desktop: välj Anslut med publik bootstrap i steg 1 och läs filen. I Termux: lägg gg-lan-bootstrap.json bredvid gg-cli.py och kör telefonkommandot. Egen adress hittas automatiskt och signerad inbjudan återannonseras till koordinatorn.";color:RuntimeTheme.GGTheme.dim;font.pixelSize:9}
                        Row {width:parent.width;spacing:7
                            Action {objectName:"lanLinuxCommand";text:"Linux CLI (valfritt)";enabled:root.owned&&root.coordinator;onClicked:root.copy(root.command("Linux"))}
                            Action {objectName:"lanTermuxCommand";text:"Kopiera Termux-kommando";enabled:root.owned&&root.coordinator;onClicked:root.copy(root.command("Termux"))}
                        }
                        Label {colorKey:"ui.lan.bootstrap.keys";width:parent.width;text:"Endast publika inbjudningar och konfiguration delas. Varje peer behåller sina egna två producentnycklar i RAM. Omstart kräver ny parning; walletnycklar berörs inte.";color:RuntimeTheme.GGTheme.dim;font.pixelSize:9}
                    }
                }
                Section {height:peersBody.height+18
                    Column {id:peersBody;x:9;y:9;width:parent.width-18;spacing:7
                        Row {width:parent.width
                            Label {colorKey:"ui.lan.step.roster";width:parent.width-100;text:"3 · Granska och godkänn de tre apparaterna";font.bold:true}
                            Label {colorKey:"ui.lan.roster.count";width:100;text:root.candidates.length+" / 3 inbjudna";horizontalAlignment:Text.AlignRight;color:RuntimeTheme.GGTheme.cyan}
                        }
                        Repeater {model:root.candidates
                            Column {required property var modelData;width:peersBody.width;spacing:3
                                Row {width:parent.width;spacing:6
                                    Rectangle {width:5;height:5;radius:3;y:4;color:RuntimeTheme.GGTheme.cyan}
                                    Label {colorKey:"ui.lan.peer.label";width:Math.max(40,parent.width-160);text:String(modelData.label)+(modelData.local?" · den här apparaten":" · kandidat")+(modelData.allow_test_tokens===true?" · testtokens":"")+(modelData.allow_dag_transactions===true?" · DAG-TX":"")}
                                    Label {colorKey:"ui.lan.peer.endpoint";width:148;text:String(modelData.host)+":"+String(modelData.port);horizontalAlignment:Text.AlignRight;color:RuntimeTheme.GGTheme.dim}
                                }
                                Line {}
                            }
                        }
                        Row {spacing:7
                            Action {objectName:"lanInviteOpen";text:"Läs publik inbjudan…";enabled:root.canAct&&root.owned&&root.coordinator&&!root.ready;onClicked:inviteFile.open()}
                            Action {objectName:"lanCreateSession";text:root.setup.allow_dag_transactions===true&&!root.allDagOptedIn?"Väntar på 3 DAG-TX-val":root.setup.allow_dag_transactions!==true&&root.setup.allow_test_tokens===true&&!root.allTokenOptedIn?"Väntar på 3 testtokenval":"Godkänn 3 · skapa och distribuera";enabled:root.canAct&&root.owned&&root.coordinator&&!root.ready&&root.candidates.length===3&&(root.setup.allow_dag_transactions===true||root.setup.allow_test_tokens!==true||root.allTokenOptedIn)&&(root.setup.allow_dag_transactions!==true||root.allDagOptedIn);onClicked:root.run("lan_session_create",root.sessionOptions())}
                            Action {objectName:"lanDistribute";text:"Distribuera igen";enabled:root.canAct&&root.coordinator&&root.ready&&root.setup.bundle_available===true;onClicked:root.run("lan_distribute",{})}
                        }
                        Label {colorKey:"ui.lan.roster.trust";width:parent.width;text:"En annonserad inbjudan är en kandidat. Sessionens roster binds först när koordinatorn uttryckligen godkänner alla tre. Fysiskt skilda apparater är ännu inte verifierade.";color:RuntimeTheme.GGTheme.dim;font.pixelSize:9}
                        TextArea {id:inviteInput;objectName:"lanInvitePaste";property string uiColorScope:"ui.lan.field.invite";width:parent.width;height:48;wrapMode:TextEdit.Wrap;font.family:"monospace";font.pixelSize:9;placeholderText:"Valfritt: klistra in signerad publik inbjudan som JSON";enabled:root.canAct&&root.owned&&root.coordinator&&!root.ready;selectByMouse:true;color:RuntimeTheme.GGTheme.text;background:Rectangle {color:RuntimeTheme.GGTheme.canvas;border.width:1;border.color:RuntimeTheme.GGTheme.line}}
                        Action {objectName:"lanInviteAdd";text:"Lägg till publik inbjudan";enabled:inviteInput.enabled&&inviteInput.text.length>0&&inviteInput.length<=4096;onClicked:root.addPasted()}
                    }
                }
                Section {height:produceBody.height+18
                    Column {id:produceBody;x:9;y:9;width:parent.width-18;spacing:7
                        Label {colorKey:"ui.lan.step.produce";text:root.stress.enabled===true?"4 · DAG-TX-session · tidsbegränsade prov":"4 · Kör den här apparatens två producenter";font.bold:true}
                        Row {spacing:7;visible:root.stress.enabled!==true
                            CryptoField {id:cadence;objectName:"lanInterval";property string uiColorScope:"ui.lan.field.interval";width:80;height:27;text:"250";maximumLength:5;inputMethodHints:Qt.ImhDigitsOnly;enabled:root.canAct&&root.ready&&!root.producing&&!root.stressRunning&&root.stress.enabled!==true;Accessible.name:"Producentintervall i millisekunder, 100 till 60000"}
                            Action {objectName:"lanProduce";text:"▷ Producera lokalt";enabled:cadence.enabled&&/^[0-9]{3,5}$/.test(cadence.text)&&Number(cadence.text)>=100&&Number(cadence.text)<=60000;onClicked:root.run("lan_produce",{interval_ms:Number(cadence.text)})}
                            Action {objectName:"lanPause";text:"Ⅱ Pausa lokalt";enabled:root.canAct&&root.ready&&root.producing&&!root.stressRunning&&root.stress.enabled!==true;onClicked:root.run("lan_pause",{})}
                        }
                        Label {objectName:"lanProducerModeNote";colorKey:"ui.lan.produce.note";width:parent.width;text:root.stress.enabled===true?"Använd DAG-provet nedan eller Starta-knappen. Koordinatorn styr ett gemensamt, tidsbegränsat prov med tre apparater. Varje apparat använder sina egna signerare; Stoppa LAN-peer avslutar den här apparatens LAN-peer.":"Paus stoppar bara lokal produktion; verifiering och relä fortsätter. Stoppa avslutar denna ägda peer. MAINNET är inte aktiverat, trafiken är inte krypterad och protokollet är ännu ett privat LAN-experiment.";color:RuntimeTheme.GGTheme.dim;font.pixelSize:9}
                    }
                }
                Section {objectName:"lanDagStressSection";height:stressBody.height+18;visible:root.stressSupported&&root.owned
                    Column {id:stressBody;x:9;y:9;width:parent.width-18;spacing:7
                        Label {colorKey:"ui.lan.dag.stress.title";text:"5 · DAG-stressprov · tre apparaters egna signerare";font.bold:true}
                        Label {objectName:"lanDagStressScope";colorKey:"ui.lan.dag.stress.scope";width:parent.width;text:root.stress.enabled===true?"Varje apparat signerar med sina två egna producenter. Samma graf visar lokalt verifierade förslag och DAG-TX; mottagna förslag ingår. Nätkvittens redovisas separat. Testtokenkvitton räknas inte som DAG-TX.":"Den här sessionen saknar uttryckligt DAG-TX-val från alla tre. Starta en ny parning med DAG-testtransaktioner valda på varje apparat.";color:RuntimeTheme.GGTheme.dim;font.pixelSize:9}
                        Repeater {model:root.stress.participants||[]
                            Label {required property var modelData;objectName:"lanDagStressParticipant";colorKey:"ui.lan.dag.stress.participant";width:stressBody.width;text:String(modelData.label||"Peer")+(modelData.local?" · den här apparaten":"")+" · "+(modelData.opted_in===true?"DAG-TX valt":"DAG-TX inte valt")+(modelData.state?" · "+String(modelData.state):"")}
                        }
                        Line {}
                        Label {text:"Den här nodens hårdvara och resurstak";font.bold:true}
                        Label {width:parent.width;text:"Reglagen sätter egna tak. Relativt behov räknas mot samma TX/s och den svagaste aktiva resursen. Noden reglerar sitt DAG-arbete efter detta; andra apparater har egna lokala inställningar.";color:RuntimeTheme.GGTheme.dim;font.pixelSize:9}
                        Repeater {model:["overall","cpu","gpu","ram","network"]
                            BudgetRow {required property string modelData;resource:modelData}
                        }
                        Label {objectName:"lanResourceEstimate";width:parent.width;text:root.resourceEstimateText();color:RuntimeTheme.GGTheme.cyan;font.pixelSize:9}
                        Label {objectName:"lanResourcePending";width:parent.width;visible:root.draftBudget!==null;text:"Ändrade resurstak väntar på nodens bekräftelse";color:RuntimeTheme.GGTheme.dim;font.pixelSize:9}
                        Label {objectName:"lanHardwareBasis";width:parent.width;text:"Hårdvarutest: "+String(root.hardwareTest.state||"UNMEASURED")+" · största uppmätta block: "+root.measuredNumber((root.hardwareTest.profile||{}).largest_measured_transactions_per_block)+" TX. "+((root.hardwareTest.profile||{}).network_basis==="MEASURED_AUTHENTICATED_LAN_PROBE"?"Nätverk: uppmätt dubbelriktat LAN-prov.":(root.hardwareTest.profile||{}).network_basis==="OS_REPORTED_LINK_SPEED_NOT_MEASURED_THROUGHPUT"?"Nätverk: operativsystemets länkhastighet, teoretisk uppskattning.":"Nätverk: ännu inte uppmätt.")+" RAM: kopieringsprov och minnesbudget. GPU: "+((root.hardware.hardware||{}).gpu_compute_supported===true?"aktiv beräkningsbackend.":"DAG-beräkning saknas i denna backend.");color:RuntimeTheme.GGTheme.dim;font.pixelSize:9}
                        Flow {width:parent.width;spacing:7
                            Action {objectName:"lanHardwareTestStart";text:"▷ Hårdvarutest · 10 s";enabled:root.canAct&&root.owned&&!root.hardwareTesting&&!root.stressRunning&&!root.producing&&!root.circleRunning;onClicked:root.run("lan_hardware_test_start",{duration_ms:10000,max_transactions_per_block:50000})}
                            Action {objectName:"lanHardwareTestStop";text:"■ Stoppa hårdvarutest";enabled:root.canAct&&root.hardwareTesting;onClicked:root.run("lan_hardware_test_stop",{})}
                        }
                        Label {width:parent.width;visible:text.length>0;text:root.circleCode(root.hardwareTest.last_error)||root.circleCode((root.hardwareTest.profile||{}).network_error);color:RuntimeTheme.GGTheme.negative;font.pixelSize:9}
                        Line {}
                        Label {objectName:"lanDagStressLimits";colorKey:"ui.lan.dag.stress.limits";width:parent.width;text:"Nuvarande programgränser: "+root.measuredNumber(root.stressLimits.min_duration_ms/1000)+"–"+root.measuredNumber(root.stressLimits.max_duration_ms/1000)+" s · 1–"+root.measuredNumber(root.stressLimits.max_tx_per_block)+" DAG-TX/förslag · "+root.measuredNumber(root.stressLimits.min_interval_ms)+"–"+root.measuredNumber(root.stressLimits.max_interval_ms)+" ms. Dessa gränser är inte uppmätt hårdvarukapacitet.";color:RuntimeTheme.GGTheme.dim;font.pixelSize:9}
                        Row {width:parent.width;spacing:7
                            Column {width:(parent.width-14)/3;spacing:3
                                Label {text:"Längd · sekunder";font.pixelSize:9}
                                CryptoField {id:stressDuration;objectName:"lanDagStressDuration";property string uiColorScope:"ui.lan.dag.stress.duration";width:parent.width;height:27;text:"10";maximumLength:6;inputMethodHints:Qt.ImhDigitsOnly;enabled:root.canAct&&root.stress.enabled===true&&root.coordinator&&root.stress.role==="COORDINATOR"&&!root.stressRunning;Accessible.name:"DAG-provets längd i sekunder, inom backendens gränser"}
                            }
                            Column {width:(parent.width-14)/3;spacing:3
                                Label {text:"DAG-TX / block";font.pixelSize:9}
                                CryptoField {id:stressTransactions;objectName:"lanDagStressTransactions";property string uiColorScope:"ui.lan.dag.stress.transactions";width:parent.width;height:27;text:"1";maximumLength:7;inputMethodHints:Qt.ImhDigitsOnly;enabled:stressDuration.enabled;Accessible.name:"Signerade DAG-testtransaktioner per förslag, inom backendens gränser"}
                            }
                            Column {width:(parent.width-14)/3;spacing:3
                                Label {text:"Intervall · ms · 0 = auto";font.pixelSize:9}
                                CryptoField {id:stressInterval;objectName:"lanDagStressInterval";property string uiColorScope:"ui.lan.dag.stress.interval";width:parent.width;height:27;text:"250";maximumLength:7;inputMethodHints:Qt.ImhDigitsOnly;enabled:stressDuration.enabled;Accessible.name:"DAG-producenternas målintervall i millisekunder"}
                            }
                        }
                        Flow {objectName:"lanDagStressActions";width:parent.width;spacing:7
                            Action {objectName:"lanDagStressStart";text:"▷ Kör DAG-prov · 3 apparater";tip:"Kör ett tidsbegränsat DAG-prov med tre uttryckligen anslutna apparater";enabled:root.canStartStress;onClicked:root.run("lan_dag_stress_start",{duration_ms:Number(stressDuration.text)*1000,transactions_per_block:Number(stressTransactions.text),interval_ms:Number(stressInterval.text)})}
                            Action {objectName:"lanDagStressStop";text:"■ Stoppa DAG-prov";enabled:root.canAct&&root.stressSupported&&root.stress.role==="COORDINATOR"&&root.stressRunning;onClicked:root.run("lan_dag_stress_stop",{})}
                            Action {objectName:"lanDagStressCopyResult";text:"Kopiera provresultat";enabled:root.stressSupported&&root.stress.enabled===true&&root.resultState(root.stress.state)!==null&&!!root.surfaceHost&&!!root.surfaceHost.tmogCopy;onClicked:root.copyStressResult()}
                        }
                        Label {objectName:"lanDagStressStatus";colorKey:"ui.lan.dag.stress.status";width:parent.width;text:"DAG-prov · "+String(root.stress.state||"IDLE")+" · "+root.measuredNumber(root.stress.elapsed_ms)+" ms";color:root.stress.last_error?RuntimeTheme.GGTheme.negative:RuntimeTheme.GGTheme.cyan}
                        Label {objectName:"lanDagStressLocal";colorKey:"ui.lan.dag.stress.local";width:parent.width;text:"Lokalt verifierat under provet: "+root.measuredNumber(root.stress.blocks)+" förslag · "+root.measuredNumber(root.stress.transactions)+" DAG-TX"}
                        Label {objectName:"lanDagStressRates";colorKey:"ui.lan.dag.stress.rates";width:parent.width;text:"DAG · senaste mätfönstret: "+root.measuredRate((root.state.block_graph||{}).metrics?root.state.block_graph.metrics.bps:undefined)+" block/s · "+(root.stress.blocks>0?(root.stress.transactions/root.stress.blocks).toFixed(1):"—")+" TX/block under provet · "+root.measuredRate((root.state.block_graph||{}).metrics?root.state.block_graph.metrics.tps:undefined)+" TX/s · lokal validering";color:RuntimeTheme.GGTheme.dim;font.pixelSize:9}
                        Label {objectName:"lanDagStressAcknowledged";colorKey:"ui.lan.dag.stress.acknowledged";width:parent.width;text:root.stressAckText();color:RuntimeTheme.GGTheme.dim;font.pixelSize:9}
                        Label {objectName:"lanDagStressDetails";colorKey:"ui.lan.dag.stress.details";width:parent.width;text:root.stressDetails();visible:text.length>0;color:root.stress.last_error?RuntimeTheme.GGTheme.negative:RuntimeTheme.GGTheme.dim;font.pixelSize:9}
                        Label {objectName:"lanDagStressPhaseSummary";colorKey:"ui.lan.dag.stress.phase.summary";width:parent.width;text:root.stressPhaseSummary();visible:text.length>0;color:root.resultPhase(root.stress.failure_phase)?RuntimeTheme.GGTheme.negative:RuntimeTheme.GGTheme.dim;font.pixelSize:9}
                        Label {objectName:"lanDagStressPhaseTimings";colorKey:"ui.lan.dag.stress.phase.timings";width:parent.width;text:root.stressPhaseTimings();visible:text.length>0;color:RuntimeTheme.GGTheme.dim;font.pixelSize:9}
                        Label {objectName:"lanDagStressTransport";colorKey:"ui.lan.dag.stress.transport";width:parent.width;text:root.stressTransportText();visible:text.length>0;color:RuntimeTheme.GGTheme.dim;font.pixelSize:9}
                    }
                }
                Section {height:tokenBody.height+18;visible:root.tokens.enabled===true
                    Column {id:tokenBody;x:9;y:9;width:parent.width-18;spacing:7
                        Label {colorKey:"ui.lan.token.title";text:(root.stressSupported?"6":"5")+" · GG-LAN(TEST) · separat kvittoprov";font.bold:true}
                        Label {colorKey:"ui.lan.token.trust";width:parent.width;text:"Koordinatorn ordnar och kvitterar testöverföringarna. Varje apparat signerar själv och verifierar kvitton och saldon. Testtillgång utan ekonomiskt värde; DAG-slutlighet är fortfarande 0.";color:RuntimeTheme.GGTheme.dim;font.pixelSize:9}
                        Repeater {model:root.tokens.accounts||[]
                            Row {required property var modelData;width:tokenBody.width;spacing:7
                                Label {colorKey:"ui.lan.token.account";width:Math.max(50,parent.width-230);text:String(modelData.label||"Peer")}
                                Label {colorKey:"ui.lan.token.balance";width:120;text:root.tokenAmount(modelData.balance_atomic);horizontalAlignment:Text.AlignRight}
                                Action {width:95;text:"Skicka 1";enabled:root.canAct&&root.ready&&!root.circleRunning&&root.wholeTokenAtomic().length>0&&String(modelData.peer_key)!==String(root.lan.public_key);onClicked:root.run("lan_token_send",{recipient_peer_key:String(modelData.peer_key),amount_atomic:root.wholeTokenAtomic()})}
                            }
                        }
                        Row {spacing:7
                            Label {text:"Längd (1–60 s)";height:27;verticalAlignment:Text.AlignVCenter}
                            CryptoField {id:circleDuration;objectName:"lanCircleDuration";property string uiColorScope:"ui.lan.field.circle.duration";width:48;height:27;text:"10";maximumLength:2;inputMethodHints:Qt.ImhDigitsOnly;enabled:root.canAct&&root.coordinator&&!root.circleRunning;Accessible.name:"Cirkelprovets längd i sekunder, 1 till 60"}
                            Label {text:"Batch (1–16)";height:27;verticalAlignment:Text.AlignVCenter}
                            CryptoField {id:circleBatch;objectName:"lanCircleBatch";property string uiColorScope:"ui.lan.field.circle.batch";width:48;height:27;text:"1";maximumLength:2;inputMethodHints:Qt.ImhDigitsOnly;enabled:circleDuration.enabled;Accessible.name:"Överföringar per batch, 1 till 16"}
                        }
                        Row {spacing:7
                            Action {objectName:"lanCircleStart";text:"▷ Cirkulera "+circleDuration.text+" s · batch "+circleBatch.text;enabled:root.canAct&&root.ready&&!root.transportExhausted&&root.coordinator&&!root.circleRunning&&root.circleSettingsValid&&root.wholeTokenAtomic().length>0;onClicked:root.run("lan_circle_start",{duration_ms:Number(circleDuration.text)*1000,batch:Number(circleBatch.text),amount_atomic:root.wholeTokenAtomic()})}
                            Action {objectName:"lanCircleStop";text:"■ Stoppa prov";enabled:root.canAct&&root.circleRunning;onClicked:root.run("lan_circle_stop",{})}
                        }
                        Label {objectName:"lanCircleStatus";colorKey:"ui.lan.token.circle";width:parent.width;text:String(root.circle.state||"Redo")+" · "+String(root.circle.transactions===undefined?"—":root.circle.transactions)+" TX · "+(typeof root.circle.tps==="number"?root.circle.tps.toFixed(1):"—")+" TX/s · "+String(root.circle.completed_rounds===undefined?"—":root.circle.completed_rounds)+" varv";color:root.circle.last_error?RuntimeTheme.GGTheme.negative:RuntimeTheme.GGTheme.cyan}
                        Label {objectName:"lanCircleDetails";colorKey:"ui.lan.token.circle.details";width:parent.width;text:root.circleDetails();visible:text.length>0;font.pixelSize:9;color:root.circle.last_error?RuntimeTheme.GGTheme.negative:RuntimeTheme.GGTheme.dim}
                        Label {objectName:"lanCircleSync";colorKey:"ui.lan.token.synced";width:parent.width;text:root.circleSyncText();font.pixelSize:9;color:root.circleFinished&&root.circle.all_peers_synced!==true?RuntimeTheme.GGTheme.negative:RuntimeTheme.GGTheme.dim}
                    }
                }
            }
        }
    }
    FileDialog {id:bootstrapFile;objectName:"lanBootstrapFileDialog";title:"Spara publik LAN-bootstrap som gg-lan-bootstrap.json (ny fil)";fileMode:FileDialog.SaveFile;defaultSuffix:"json";nameFilters:["JSON (*.json)"];onAccepted:root.run("lan_export_bootstrap",{path:String(selectedFile)})}
    FileDialog {id:bootstrapJoinFile;objectName:"lanBootstrapJoinFileDialog";title:"Anslut med koordinatorns publika gg-lan-bootstrap.json";fileMode:FileDialog.OpenFile;nameFilters:["JSON (*.json)"];onAccepted:root.joinBootstrap(selectedFile)}
    FileDialog {id:inviteExport;objectName:"lanInviteExportDialog";title:"Spara egen publik LAN-inbjudan (ny fil)";fileMode:FileDialog.SaveFile;defaultSuffix:"json";nameFilters:["JSON (*.json)"];onAccepted:root.run("lan_export_invite",{path:String(selectedFile)})}
    FileDialog {id:inviteFile;objectName:"lanInviteFileDialog";title:"Läs signerad publik LAN-inbjudan";fileMode:FileDialog.OpenFile;nameFilters:["JSON (*.json)"];onAccepted:root.run("lan_peer_file",{path:String(selectedFile)})}
}
