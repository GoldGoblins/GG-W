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
    readonly property var sourceState:state.local_node_sources||({})
    readonly property bool sourcePickerVisible:(sourceState.sources||[]).length>0||sourceState.selection==="EXPLICIT"
    readonly property bool sourceUnavailable:sourcePickerVisible&&sourceState.view_available!==false&&!state.parallel_dag
    readonly property var sourceOptions:{
        var values=(sourceState.sources||[]).slice(),selected=sourceState.selected_source
        if(sourceState.selection==="EXPLICIT"&&selected&&!values.some(function(row){return row.handle===sourceState.selected_handle}))values.push(Object.assign({},selected,{available:false}))
        return values.map(function(row){return Object.assign({},row,{display:String(row.label||"CLI")+(row.source_profile?" · "+String(row.source_profile):"")+(row.node_role?" · "+String(row.node_role):"")+(row.environment?" · "+String(row.environment):"")+" · "+(row.available===false?"Ej tillgänglig":row.stale===true?"Äldre data":"live")})})
    }
    readonly property var observation:dag.observation||({})
    readonly property bool observerReadOnly:observation.read_only===true||sourcePickerVisible&&sourceState.view_available!==false
    readonly property var ownTestAccounts:(dag.test_accounts||[]).filter(function(account){return account.local===true})
    readonly property var lan:dag.lan||({})
    readonly property var lanSetup:dag.lan_setup||({})
    readonly property var dagConsensus:dag.dag_consensus||({})
    readonly property var nativeObservers:dag.native_observers||({})
    readonly property var nativeObserverRows:(nativeObservers.profiles||[]).slice(0,2)
    readonly property var dagProofs:dag.dag_proofs||({})
    readonly property var localHistory:dag.local_history||({})
    readonly property var localHistoryReport:localHistory.report||({})
    readonly property bool hasLocalHistoryReport:!sourceUnavailable&&!!localHistory.report&&["READY","STALE"].indexOf(String(localHistory.state))>=0
    function localHistoryLabel(){
        if(sourceUnavailable)return "Ingen vald CLI-källa";
        if(observation.stale===true)return "Äldre CLI-data";
        return ({READY:"Full replay vid nodstart",STALE:"Äldre lokal rapport",NOT_APPLICABLE:"Lättklient · ingen lokal replay",UNAVAILABLE:"Ej tillgänglig",UNOBSERVED:"Ännu ej observerad"})[String(localHistory.state)]||"Ännu ej observerad";
    }
    readonly property string localHistoryDetails:"Lokal rapport från den valda nodprocessen. Full historik kontrolleras vid kallstart och arkivdata när de läses. Rapporten är inget SDK-certifikat eller tecken på aktuell nätkontakt."+
        (hasLocalHistoryReport?"\nKall replay t.o.m. höjd "+String(localHistoryReport.verified_through)+" · bevarat t.o.m. "+String(localHistoryReport.retained_through)+
            "\nAktiv historik: "+String(localHistoryReport.active_bytes)+" byte · arkiv: "+String(localHistoryReport.archive_bytes)+" byte i "+String(localHistoryReport.archive_segments)+" segment"+
            "\nStorlekarna avser historikposter och är inte total diskanvändning. Ingen checkpoint betros som ersättning för full replay.":"")+
        (localHistory.last_error?"\n"+String(localHistory.last_error):"")
    readonly property var archiveStartup:(dag.protocol_network||{}).recovery_startup||(dag.protocol_network||{}).archive_startup||({})
    readonly property bool hasArchiveStartup:!sourceUnavailable&&["VALIDATOR","REPLICA"].indexOf(String((dag.protocol_network||{}).node_role))>=0&&["gg.owned.recovery-observation.v1","gg.owned.archive-start-observation.v1"].indexOf(String(archiveStartup.schema))>=0
    function archiveHeight(value){return typeof value==="string"&&/^(0|[1-9][0-9]{0,18})$/.test(value)&&(value.length<19||value<="9223372036854775807")?value:"—"}
    readonly property bool archiveStartupValid:hasArchiveStartup&&archiveStartup.basis==="LOCAL_OWNED_NATIVE_PIPE_REPORT"&&archiveStartup.snapshot_trust_used===false&&archiveStartup.certificate_is_network_liveness===false&&archiveStartup.network_contact_asserted===false&&(archiveStartup.consensus_signing===false||(archiveStartup.phase==="READY"&&archiveStartup.node_ready===true&&archiveStartup.requested_role==="VALIDATOR"&&archiveStartup.consensus_signing===true))&&typeof archiveStartup.node_ready==="boolean"&&typeof archiveStartup.full_original_audit_completed==="boolean"&&["STARTING","INVENTORY","ARCHIVE_AUDIT","ARCHIVE_RESTORE","VERIFY_HISTORY","VERIFY_SDK_BINDINGS","FULL_ORIGINAL_AUDIT","RESTORING_APPLICATION","APPLICATION_RESTORED","SDK_START","READY","FAILED","STOP_PENDING","STOPPED","UNAVAILABLE"].indexOf(String(archiveStartup.phase))>=0&&(archiveStartup.processed_height===null||archiveHeight(archiveStartup.processed_height)!=="—")&&(archiveStartup.verified_through===null||archiveHeight(archiveStartup.verified_through)!=="—")
    function archiveStartupLabel(){
        if(sourceUnavailable)return "Ingen vald CLI-källa";
        if(observation.stale===true)return "Äldre CLI-data";
        if(!archiveStartupValid)return "Ej tillgänglig";
        if(archiveStartup.phase==="READY")return archiveStartup.node_ready===true&&archiveStartup.full_original_audit_completed===true?"Nodstart bekräftad":"Nodstart ej bekräftad";
        return ({INVENTORY:"Kontrollerar lokala filer",ARCHIVE_AUDIT:"Verifierar arkivets original",ARCHIVE_RESTORE:"Återställer lokalt tillstånd",VERIFY_HISTORY:"Verifierar hela historiken",VERIFY_SDK_BINDINGS:"Verifierar SDK och lokalt tillstånd",STOP_PENDING:"Inväntar stoppad process",STARTING:"Förbereder nodstart",FULL_ORIGINAL_AUDIT:"Verifierar arkivets original",RESTORING_APPLICATION:"Återställer lokalt tillstånd",APPLICATION_RESTORED:"Tillstånd återställt",SDK_START:"Startar noden",FAILED:"Nodstart stoppad",STOPPED:"Noden stoppad",UNAVAILABLE:"Ej tillgänglig"})[String(archiveStartup.phase)]||"Ej observerad";
    }
    readonly property string archiveStartupDetails:"Status för nodstarten. Bearbetad höjd är pågående arbete. Full verifiering och nodstart bekräftas först när alla kontroller är klara. Aktuell nätanslutning visas under Kontakt nu."+(archiveStartupValid&&archiveStartup.last_error?"\n"+String(archiveStartup.last_error):"")
    readonly property var ownJournalAccounts:(((dag.protocol_network||{}).own_journals||{}).accounts||[]).slice(0,16)
    readonly property var ownJournalPools:((dag.protocol_network||{}).pools||[]).slice(0,16)
    function ownJournalCounter(value){return typeof value==="string"&&/^(0|[1-9][0-9]{0,19})$/.test(value)?value:"—"}
    function ownJournalDetails(journal){
        journal=journal||({});
        return "Egen skyddad journal · "+ownJournalCounter(journal.total_records)+" poster, varav "+ownJournalCounter(journal.active_records)+" aktiva och "+ownJournalCounter(journal.archived_records)+" arkiverade."+
            "\nAktiva originaldata: "+ownJournalCounter(journal.active_payload_bytes)+" byte. Hela kedjan läses och verifieras vid kall öppning; ett historiskt original autentiseras när det används."+
            "\nEgna signaturer och poolhändelser är inte bevis för att en betalning utförts. Journalen ersätter inga nätverksbevis och skyddar inte mot återställning av hela disken.";
    }
    readonly property var payloadRecovery:dagProofs.payload_recovery||({})
    readonly property string payloadRecoveryText:payloadRecoveryLabel()
    function payloadRecoveryLabel() {
        if (payloadRecovery.state==="FAULT") return "Återhämtning stoppad";
        if (payloadRecovery.state==="RECOVERING") {
            if (payloadRecovery.phase==="VALIDATING") return "Validerar hämtat block";
            var received=payloadRecovery.partial_downloaded_bytes;
            var total=payloadRecovery.partial_reserved_bytes;
            if (typeof received==="number"&&typeof total==="number"&&isFinite(received)&&isFinite(total)
                    &&Math.floor(received)===received&&Math.floor(total)===total&&received>=0&&received<=total&&total>0&&total<=67108864)
                return "Hämtar "+bytes(received)+" / "+bytes(total)+" · "+number(payloadRecovery.pending)+" väntar";
            return "Hämtar · "+number(payloadRecovery.pending)+" väntar";
        }
        return payloadRecovery.last_error?"Väntar på giltig data · "+number(payloadRecovery.recovered_blocks)+" block":
            number(payloadRecovery.recovered_blocks)+" block · "+(Number(payloadRecovery.recovered_bytes||0)/1048576).toFixed(2)+" MiB";
    }
    readonly property var certifiedOwnAccounts:(dag.certified_test_accounts||[]).filter(function(account){return account.local===true})
    readonly property var proofRows:(dagProofs.proven_blocks||[]).slice().sort(function(a,b){return compareCounter(b.global_index===undefined?b.index:b.global_index,a.global_index===undefined?a.index:a.global_index)}).map(function(leaf){return {hash:leaf.hash,canonical_index:leaf.global_index===undefined?leaf.index:leaf.global_index,canonical_membership_verified:true,transaction_count:leaf.transactions,proposer_index:leaf.producer_index,producer_sequence:leaf.sequence,proposer_key:leaf.producer_key,worker_key:leaf.worker_key,work_hash:leaf.work_hash}})
    readonly property string consensusMembers:(dagConsensus.members||[]).map(function(member){return String(member.label||"")+" · "+String(member.owner_label||"")+(member.local_owner?" · egen":"")+" · "+String(member.state||"UNOBSERVED")}).join("\n")
    readonly property var testTokens:dag.test_tokens||({})
    readonly property var tokenCircle:dag.token_circle||({})
    readonly property var dagStress:dag.dag_stress||({})
    readonly property var ownNode:dag.dag_production||({})
    readonly property bool ownSupported:ownNode.supported===true
    readonly property bool ownRunning:ownNode.worker_active===true
    readonly property bool lightOnly:!!lan.participation&&lan.participation.light_client===true
    readonly property bool segmentedSource:dag.mode==="SEGMENTED_SDK_CERTIFIED_VIEW"
    readonly property bool financialSource:dag.mode==="FINANCIAL_SDK_CERTIFIED_VIEW"
    readonly property bool protocolSource:!!dag.protocol_network
    readonly property bool sdkSource:segmentedSource||financialSource
    readonly property var ownFinancialAccounts:dag.own_financial_accounts||[]
    readonly property var financialRelay:dag.financial_account_relay||({})
    readonly property var financialRelayOutbound:financialRelay.outbound||[]
    readonly property string financialRelayText:protocolSource?protocolRelayText():financialRelay.enabled===true?
        "Tar emot · "+number(financialRelay.queued_or_working)+" i kö":
        financialRelayOutbound.length?financialRelayLabel(financialRelayOutbound[financialRelayOutbound.length-1]):
        "Mottagning avstängd"
    function protocolRelayText(){
        var data=dag.protocol_network||{}, inbox=data.receiver_inbox||{}, relay=data.proof_relay||{}, transfers=data.account_transfers||{}, names=Object.keys(transfers)
        if(names.length){var row=transfers[names[names.length-1]];return String(row.state||"Ej observerad")+(row.total_bytes?" · "+String(row.uploaded_bytes||0)+" / "+String(row.total_bytes)+" byte":"")}
        if(relay.accounts_enabled===true)return "Tar emot · "+String(inbox.retained_documents||0)+" beständiga dokument"
        if(inbox.retained_documents)return String(inbox.retained_documents)+" bevarade dokument · relä stoppat"
        return "Mottagning avstängd"
    }
    function financialRelayLabel(row) {
        var report=row.producer_report||({});
        if (report.state==="REJECTED") return "Förmedlingen avvisades";
        if (report.state==="NONCE_CONSUMED_OUTCOME_UNRESOLVED") return "Kontrollera betalningsutfall";
        if (report.state==="BUSY"||row.state==="RELAY_BUSY") return "Producenten är upptagen";
        if (row.state==="RELAY_UNAVAILABLE") return "Ingen producent tar emot";
        return "Väntar på betalningskvitto";
    }
    readonly property string financialAccountLabel:selectedFinancialAccountLabel()
    readonly property bool membershipOnly:lightOnly||sdkSource
    function originalParentCount(hash) {var rows=graph.blocks||[];for(var i=0;i<rows.length;i++)if(rows[i].hash===hash&&(rows[i].payload_authenticated===true||graph.topology==="SDK_CERTIFIED_DAG_SUMMARY_WINDOW"&&rows[i].sdk_admission_verified===true&&rows[i].canonical_membership_verified===true))return (rows[i].parent_hashes||[]).length;return "—"}
    readonly property bool replicaOnly:!!lan.participation&&lan.participation.producer===false&&(lan.participation.replica===true||lightOnly||sdkSource)
    readonly property int localProducerCount:lan.participation&&typeof lan.participation.local_producer_count==="number"?lan.participation.local_producer_count:2
    readonly property var eligibleProducerCount:protocolSource?registeredProducerCount:lan.participation&&typeof lan.participation.eligible_network_producers==="number"?lan.participation.eligible_network_producers:producerCount
    readonly property var defaultOwnArguments:defaultOwnProductionArguments()
    readonly property bool canStartOwn:dagTransactionMode&&ownSupported&&ownNode.enabled===true&&ownNode.can_start===true&&!ownRunning&&!dagStressRunning&&defaultOwnArguments!==null
    readonly property bool dagStressRunning:["STARTING","RUNNING","STOPPING"].indexOf(String(dagStress.state||""))>=0
    readonly property bool hasDagAcknowledgement:dagStress.all_peers_synced===true&&measured(dagStress.acknowledged_blocks)&&measured(dagStress.acknowledged_transactions)
    readonly property bool dagTransactionMode:lanOwned&&dagStress.enabled===true
    readonly property var defaultStressArguments:defaultDagStressArguments()
    readonly property bool canStartDefaultStress:dagTransactionMode&&dagStress.supported===true&&dagStress.local_opt_in===true&&lanSetup.coordinator===true&&dagStress.role==="COORDINATOR"&&dagStress.can_start===true&&(dagStress.participants||[]).length===3&&(dagStress.participants||[]).every(function(peer){return peer.opted_in===true})&&!dagStressRunning&&!ownRunning&&((dag.dag_resources||{}).test||{}).state!=="RUNNING"&&defaultStressArguments!==null
    readonly property bool primaryActionEnabled:canAct&&!replicaOnly&&(lanOwned?lan.state==="READY"&&(dagTransactionMode?(ownSupported?(ownRunning?ownNode.state!=="STOPPING":canStartOwn):(dagStressRunning?dagStress.role==="COORDINATOR"&&dagStress.state!=="STOPPING":canStartDefaultStress)):!dagStressRunning):!running)
    readonly property string primaryActionText:segmentedSource&&replicaOnly&&!lightOnly?"Observatör":lightOnly?"Lättklient":replicaOnly?"Replika":dagTransactionMode&&ownSupported?(ownRunning?ownNode.state==="STOPPING"?"Ⅱ Pausar…":"Ⅱ Pausa egna producenter":"▷ Egna producenter · 60 s"):dagTransactionMode?dagStress.role!=="COORDINATOR"?"DAG-deltagare":dagStressRunning?dagStress.state==="STOPPING"?"■ Stoppar prov…":width<600?"■ DAG-prov":"■ Stoppa DAG-prov":width<600||!defaultStressArguments?"▷ DAG-prov":"▷ DAG-prov · "+(defaultStressArguments.duration_ms/1000)+" s":lanOwned?width<600?liveRunning?"Ⅱ Pausa 2":"▷ Egna 2":liveRunning?"Ⅱ Pausa egna 2":"▷ Kör egna 2":"▷ Starta"
    readonly property string primaryActionTip:lightOnly?"Verifierar SDK-certifikat och relevanta konto-/blockbevis. Hämtar inga globala blockpayloads.":replicaOnly?"Tar emot och verifierar historik. Den valda rollen producerar inga block.":dagTransactionMode&&ownSupported?"Starta eller pausa bara denna nod. Övriga noder fortsätter i egen takt; synkprovet finns i LAN-panelen.":dagTransactionMode?dagStress.role!=="COORDINATOR"?"Koordinatorn startar och stoppar det gemensamma DAG-provet":dagStressRunning?"Stoppa det pågående tidsbegränsade DAG-provet":defaultStressArguments?"Starta prov med tre apparater · "+defaultStressArguments.duration_ms+" ms · "+defaultStressArguments.transactions_per_block+" DAG-TX/förslag · "+defaultStressArguments.interval_ms+" ms målintervall":"Väntar på giltiga programgränser och tre uttryckliga DAG-TX-val":lanOwned?"Starta eller pausa endast den här apparatens två producenter":"Starta lokal DAG-session"
    readonly property bool lanOwned:lanSetup.active===true
    readonly property var operation:state.ui_operation||({})
    readonly property var limits:dag.limits||({})
    readonly property var admission:dag.admission||({})
    readonly property var preview:dag.preview||({})
    readonly property var lastWave:dag.last_wave||({})
    readonly property var graph:dag.block_graph||({})
    readonly property var live:dag.live||({})
    readonly property bool asynchronous:["ASYNC_INDEPENDENT_PRODUCERS","LAN_DAG_INDEPENDENT_OWN_PRODUCERS"].indexOf(String(live.mode))>=0
    readonly property var registeredProducerCount:protocolSource?(Number.isInteger(dag.producer_count)&&dag.producer_count>=0&&dag.producer_count<=4294967296?dag.producer_count:null):producerCount
    readonly property int producerCount:sourceUnavailable?0:protocolSource?Math.min((dag.producers||[]).length,32):lanOwned&&dag.producer_count===0?0:Number.isInteger(dag.producer_count)&&dag.producer_count>=1&&dag.producer_count<=16?dag.producer_count:4
    readonly property bool liveRunning:live.enabled===true
    readonly property bool liveLimited:live.state==="LIMIT_REACHED"
    readonly property var measurements:(dag.measurements||[]).filter(function(m){return typeof m.total_ms==="number"&&isFinite(m.total_ms)&&m.total_ms>=0}).slice(-32)
    readonly property var producerRows:{
        var result=[],stats=dag.producers||[],blocks=graph.blocks||[]
        for(var i=0;i<producerCount;i++){
            var measured=null
            for(var j=0;j<stats.length;j++)if(stats[j].index===i){measured=stats[j];break}
            if(measured&&measured.producer_enabled===false)continue
            var seen=blocks.filter(function(b){return b.proposer_index===i})
            var blocked=measured?String(measured.production_blocked_reason||""):""
            result.push({index:i,name:producerName(i)+(measured&&measured.quarantined===true?" · karantän":blocked==="GG_DAG_CANONICAL_PARENT_PENDING"?" · väntar på gren":""),blocks:measured?measured.proposals:seen.length,
                transactions:measured?measured.transactions:seen.reduce(function(n,b){return n+Number(b.transaction_count||0)},0),
                sequence:measured&&measured.certified_sequence!==undefined?measured.certified_sequence:seen.length?Math.max.apply(null,seen.map(function(b){return Number(b.producer_sequence||0)})):null,
                rate:measured&&typeof measured.observed_proposal_bps==="number"?measured.observed_proposal_bps:null,
                interval_ms:measured?measured.configured_interval_ms:null})
        }
        return result
    }
    readonly property string dagStressLabel:dagStress.role==="PARTICIPANT"&&dagStress.state==="COMPLETE"?"Lokal del klar":String(dagStress.state||"IDLE")
    readonly property string liveLabel:financialSource?"Betalningar · "+String(dagProofs.state||"WAITING_FOR_CERTIFICATE"):replicaOnly?"Replika":dagTransactionMode&&ownSupported&&ownNode.selected===true?"Egen nod · "+String(ownNode.state||"IDLE"):dagTransactionMode?"DAG-prov · "+dagStressLabel:lanOwned&&!running?String(lan.state||"STARTING"):liveRunning?"Löpande":liveLimited?"Kvot nådd":live.state==="ERROR"?"Fel":running?"Pausad":"Stoppad"
    readonly property string notice:stopError||operation.error||dag.error||(lanOwned&&lan.last_error?((connectionState==="CONNECTED"||connectionState==="STALE"?"Senaste transportfel: ":"")+String(lan.last_error)):lanOwned&&dagStress.last_error?String(dagStress.last_error):liveLimited?"Kvot nådd · förslag bevarade · "+(lanOwned?"stoppa LAN-peer för en ny session":"Stoppa/Starta för en ny session"):live.state==="ERROR"?String(live.stop_reason||"Löpande körning stoppades vid fel"):busy?"Arbetar · "+String(operation.name||""):sequenceRunning&&!lanOwned?"Våg "+sequenceSent+" / 3 · minst 2 s mellan jobb":sequenceResult&&!lanOwned?sequenceResult:lanOwned?financialSource?"SDK-certifierade betalningar och konton · blockägare visas från verifierade kvitton.":segmentedSource?(ownRunning?ownNodeNotice():"SDK-certifierade nätverksräknare och konton · blocklistan visar det aktiva segmentet."):lightOnly?"Lättklient · verifierar SDK-certifikat och relevanta medlemsbevis.":replicaOnly?"Replika · verifierar mottagen DAG-historik i lokal takt.":lan.state!=="READY"?"LAN · "+String(lan.state||"STARTING")+" · väntar på godkänd session":dagTransactionMode?ownSupported&&(ownNode.selected===true||dagStress.state==="IDLE")?ownNodeNotice():dagStress.state&&dagStress.state!=="IDLE"?stressResultText():"DAG-TX-session · kör ett tidsbegränsat prov med tre apparater; inställningar finns under DAG-stressprov & LAN":liveRunning?"2 egna producenter · förslag och DAG-TX räknas vid lokal validering":"Egna 2 pausade · mottagning och verifiering fortsätter":liveRunning?asynchronous?producerCount+" oberoende producenter · mål "+number(live.target_proposal_bps)+" förslag/s":"Löpande · "+number(live.blocks)+" förslag / "+number(live.interval_ms)+" ms · "+number(live.transactions_per_block)+" TX / förslag":"Lokal testdata · godtagande är inte finalitet")
    readonly property var rows:(graph.blocks||[]).slice().sort(function(a,b){return asynchronous?Number(b.admission_index)-Number(a.admission_index):Number(b.rank)-Number(a.rank)||Number(b.producer_sequence)-Number(a.producer_sequence)||Number(a.proposer_index)-Number(b.proposer_index)})
    readonly property var events:(dag.events||[]).slice(-48).reverse()
    readonly property color producerSeriesColor:RuntimeTheme.GGColorContext.colorFor("ui.chart.dag.producer",RuntimeTheme.GGTheme.purple)
    readonly property color validationSeriesColor:RuntimeTheme.GGColorContext.colorFor("ui.chart.dag.validation",RuntimeTheme.GGTheme.cyan)
    readonly property color totalSeriesColor:RuntimeTheme.GGColorContext.colorFor("ui.chart.dag.total",RuntimeTheme.GGTheme.blue)
    readonly property var producerColors:{var result=[],indices=[0,2,1,4,5,3,6,7,8,9,10,11,12,13,14,15];for(var i=0;i<producerCount;i++)result.push(RuntimeTheme.GGColorContext.colorFor("ui.graph.block.producer."+i,RuntimeTheme.GGTheme.color(indices[i])));return result}
    readonly property bool busy:operation.state==="running"
    readonly property bool approvalPending:operation.state==="approval_required"
    readonly property bool canAct:!observerReadOnly&&!busy&&!approvalPending
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
    signal sourceSelectionRequested(string handle)
    function toggleDetails(){if(dockAvailable){factsDrawer.close();sidePanelOpen=!sidePanelOpen}else factsDrawer.visible?factsDrawer.close():factsDrawer.open()}
    function run(name,args){if(observerReadOnly)return;if(name==="dag_stop"){if((!running&&!lanOwned)||stopRequested)return;cancelSequence("Kommande vågor avbrutna")}else if(!canAct)return;if(name==="dag_start"&&(running||lanOwned))return;if(name==="dag_wave"&&(!running||lanOwned))return;if((name==="lan_produce"||name==="lan_pause")&&(!lanOwned||lan.state!=="READY"||dagStressRunning||dagTransactionMode||replicaOnly))return;if(name==="lan_dag_produce_start"&&!canStartOwn)return;if(name==="lan_dag_produce_stop"&&(!dagTransactionMode||!ownSupported||!ownRunning||ownNode.state==="STOPPING"))return;if(name==="lan_dag_stress_start"&&!canStartDefaultStress)return;if(name==="lan_dag_stress_stop"&&(!lanOwned||dagStress.supported!==true||dagStress.role!=="COORDINATOR"||!dagStressRunning))return;actionRequested(name,args||{})}
    function triggerPrimary(){if(!primaryActionEnabled)return;if(dagTransactionMode&&ownSupported)run(ownRunning?"lan_dag_produce_stop":"lan_dag_produce_start",ownRunning?{}:defaultOwnArguments);else if(dagTransactionMode)run(dagStressRunning?"lan_dag_stress_stop":"lan_dag_stress_start",dagStressRunning?{}:defaultStressArguments);else run(lanOwned?(liveRunning?"lan_pause":"lan_produce"):"dag_start",{})}
    function defaultDagStressArguments(source){
        var bounds=source||dagStress.limits||({}),values=[bounds.min_duration_ms,bounds.max_duration_ms,bounds.min_interval_ms,bounds.max_interval_ms,bounds.max_tx_per_block]
        if(!values.every(function(value,index){return Number.isSafeInteger(value)&&value>=(index===2?0:1)})||bounds.min_duration_ms>bounds.max_duration_ms||bounds.min_interval_ms>bounds.max_interval_ms)return null
        return {duration_ms:Math.max(bounds.min_duration_ms,Math.min(bounds.max_duration_ms,10000)),transactions_per_block:1,interval_ms:Math.max(bounds.min_interval_ms,Math.min(bounds.max_interval_ms,1000))}
    }
    function ownNodeNotice(){var work=ownNode.production||({});return "Egen nod · "+String(ownNode.state||"IDLE")+" · "+number(work.blocks)+" egna block · "+number(work.transactions)+" TX. Övriga noder arbetar i sin egen takt; synkprov väljs separat i LAN-panelen."}
    function defaultOwnProductionArguments(){var bounds=ownNode.limits||({}),args=defaultDagStressArguments(bounds);if(args)args.duration_ms=Math.max(bounds.min_duration_ms,Math.min(bounds.max_duration_ms,60000));return args}
    function producerName(index){
        var identities=lan.producer_identities||graph.producer_identities||[]
        for(var i=0;i<identities.length;i++)if(identities[i].index===index)return String(identities[i].display_name)+(identities[i].local===true?" · egen":"")
        return lanOwned?"Okänd nod · P"+(index+1):"Producent "+(index+1)
    }
    function producerAccountText(index){
        if(protocolSource){var records=dag.producers||[];for(var r=0;r<records.length;r++)if(records[r].index===index)return "\nProducent: "+String(records[r].producer_key)+"\nÄgare: "+String(records[r].owner_peer_key)+"\nNod: "+String(records[r].node_key)+"\nCertifierad post vid höjd "+String(records[r].record_height)+"\nPlattformen är en signerad deklaration";return ""}
        var rows=(dag.certified_test_accounts||[]).concat(dag.test_accounts||[])
        for(var i=0;i<rows.length;i++)if(rows[i].producer_index===index)return "\nDAG-testkonto · saldo "+String(rows[i].balance_atomic)+" atomer · nonce "+String(rows[i].nonce)+(rows[i].verification_scope==="SDK_CERTIFIED_MEMBERSHIP"?" · SDK-verifierat medlemskap":" · lokal förhandsvy")
        return ""
    }
    function producerKeyName(key){var identities=lan.producer_identities||[];for(var i=0;i<identities.length;i++)if(identities[i].producer_key===key)return String(identities[i].display_name)+(identities[i].local===true?" · egen":"");return "Nod "+shortId(key)}
    function workerKeyName(key){var identities=lan.producer_identities||[];for(var i=0;i<identities.length;i++)if(identities[i].node_key===key||identities[i].owner_peer_key===key)return String(identities[i].display_name);return "Arbetare "+shortId(key)}
    function connectionLabel(value){return ({CONNECTED:"Ansluten",DEGRADED:"Störd kontakt",DISCONNECTED:"Ingen kontakt",EXHAUSTED:"Kvotstopp",STALE:"Äldre data",UNOBSERVED:"Ej observerad",PAIRING:"Parar",STOPPED:"Stoppad"})[String(value)]||"Ej uppmätt"}
    function nativeObserverText(row){
        if(observation.stale===true)return "Äldre data";
        if(row.state==="FAULT")return "Process- eller verifieringsfel";
        if(row.state==="STARTING")return "Startar";
        if(row.state==="STOPPING")return "Stoppar";
        var contact=row.native_connection||({});
        return contact.state==="SYNCING"?"Synkar · höjd "+number(contact.latest_height):connectionLabel(contact.state||"UNOBSERVED");
    }
    function nativeObserverDetails(row){
        var contact=row.native_connection||({}),enrollment=row.enrollment||({});
        return String(row.display_name||row.profile||"")+" · nod "+shortId(row.native_node_key)+
            "\nFull observer · 0 röster · producentdelegat "+shortId(row.delegating_producer_key)+
            "\nSDK-peers: "+number(contact.peer_count)+" · höjd "+number(contact.latest_height)+
            "\nSDK RX/TX: "+number(contact.received_bytes)+" / "+number(contact.sent_bytes)+" byte (aktuella peeranslutningar)"+
            "\nVerifierat certifikat: "+number(row.certificate_height)+" · kvitterade kommittéägare: "+number(enrollment.owners_acknowledged)+
            (row.last_error?"\n"+String(row.last_error):"");
    }
    readonly property string connectionState:observation.stale===true?"STALE":String(lan.connection_state||"")
    readonly property bool activeTransportError:lanOwned&&!!lan.last_error&&connectionState!=="CONNECTED"&&connectionState!=="STALE"
    readonly property string protocolRoleLabel:protocolSource?({VALIDATOR:"Validator",REPLICA:"Replika · full verifiering",LIGHT:"Lättklient · SDK-bevis"})[String((dag.protocol_network||{}).node_role||dag.role||"")]||"":""
    readonly property string participationLabel:(protocolRoleLabel||(lightOnly?"Lättklient · SDK-bevis":segmentedSource?(lan.participation&&lan.participation.producer===true?"Producent · SDK-bevis":"Observatör · SDK-bevis"):lan.participation&&lan.participation.producer===true&&lan.participation.replica===true?"Producent + replika":replicaOnly?"Replika · full verifiering":"Ej rapporterad"))+(nativeObservers.own_running>0?" + full SDK-observer":"")
    readonly property string certifiedStateRoot:protocolSource&&financialSource&&dagProofs.canonical_finality===true&&dagConsensus.state!=="FAULT"&&typeof dag.state_root==="string"&&/^[0-9a-f]{64}$/.test(dag.state_root)?dag.state_root:""
    readonly property string connectionDetails:(lan.peer_status||[]).map(function(peer){return String(peer.label)+": "+connectionLabel(peer.state)+(typeof peer.age_seconds==="number"?" · senast "+peer.age_seconds.toFixed(1)+" s":"")+" · "+peerSyncText(peer)}).join("\n")
    function peerSyncText(peer){
        var sync=peer.sync||({})
        if(typeof sync.remote_records!=="number"||typeof sync.received_records!=="number")return "hämtning ej observerad"
        var admission=typeof sync.validated_prefix==="number"?" lästa · "+sync.validated_prefix+" sammanhängande validerade"+(sync.unresolved_records>0?" · "+sync.unresolved_records+" ej validerade":""):" hämtade"
        return sync.received_records+" / "+sync.remote_records+admission+(sync.state==="BLOCK_EXCEEDS_LOCAL_LIMIT"?" · nästa block över lokal gräns":sync.pending_records>0?" · "+sync.pending_records+" kvar":" · vid senaste kontroll")
    }
    readonly property string syncSummary:{
        var peers=lan.peer_status||[],seen=0,pending=0,blocked=0,unresolved=0
        for(var i=0;i<peers.length;i++){var sync=peers[i].sync||({});if(typeof sync.pending_records==="number"){seen++;pending=Math.max(pending,sync.pending_records);unresolved=Math.max(unresolved,Number(sync.unresolved_records)||0);if(sync.state==="BLOCK_EXCEEDS_LOCAL_LIMIT")blocked++}}
        return !seen?"Ej observerad":(blocked?blocked+" över blockgräns":seen+" / "+peers.length+" · max "+pending+" kvar")+(unresolved>0?" · "+unresolved+" ej validerade":"")
    }
    function stressResultText(){return "DAG-prov · "+dagStressLabel+" · "+number(dagStress.blocks)+" förslag / "+number(dagStress.transactions)+" DAG-TX lokalt · "+(hasDagAcknowledgement?"nätkvittens från alla tre":"nätkvittens ej bekräftad")}
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
        if(sourceUnavailable)return {name:["BLOCK","BETALNINGAR","FRONTIER","PRODUCENTER"][index],value:"—",detail:"Välj en tillgänglig CLI-källa"}
        if(protocolSource&&index===3)return {name:"PRODUCENTER",value:number(registeredProducerCount),detail:(dag.producers||[]).length+" observerade poster · "+number(localProducerCount)+" egna"}
        if(financialSource){
            if(index===0)return {name:"CERTIFIERADE BLOCK",value:number(dag.certified_blocks),detail:"SDK-certifierat tillstånd"}
            if(index===1)return {name:"UTFÖRDA BETALNINGAR",value:number(dag.certified_transactions),detail:"kontoändringar i SDK-ordning"}
            if(index===2)return {name:"AVVISADE BETALNINGAR",value:number(dag.rejected_transactions),detail:"inga utförda överföringar"}
        }
        if(segmentedSource){
            if(index===0)return {name:"SDK-VALDA BLOCK",value:number(dag.certified_blocks),detail:"certifierat nätverkstillstånd"}
            if(index===1)return {name:"SDK-VALDA DAG-TX",value:number(dag.certified_transactions),detail:"certifierat nätverkstillstånd"}
            if(index===2)return {name:"SEGMENT",value:number((dagProofs.dag_segmented_commitment||{}).epoch),detail:"aktivt segment"}
        }
        if(index===0)return {name:"FÖRSLAG I DAG",value:number(dag.blocks_admitted),detail:lanOwned?"lokalt godtagna förslag":"lokal experiment-DAG"}
        if(index===1)return {name:lanOwned?"VALIDERAD DAG-TX":"VALIDERAD TX",value:number(dag.transactions_validated),detail:lanOwned?"lokalt verifierade signaturer":"verifierade signaturer"}
        if(index===2)return {name:"FRONTIER",value:number(dag.frontier_size),detail:"öppna spetsar"}
        return lanOwned?{name:"PRODUCENTER",value:number(eligibleProducerCount)+" · LAN",detail:lan.state==="READY"?number(localProducerCount)+" egna · "+number(lan.configured_peers)+" parade apparater":number(lanSetup.invite_count)+" / 3 inbjudna"}:{name:"PRODUCENTER",value:number(dag.producer_count)+" · lokalt",detail:"en dator · inget P2P"}
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
    function selectedFinancialAccountLabel(){var info=dag.financial_account_profiles||({});var rows=info.profiles||[];for(var i=0;i<rows.length;i++)if(rows[i].profile===info.selected_profile&&rows[i].public_key===dagProofs.selected_account)return String(rows[i].label||rows[i].profile);return ""}
    function financialAccountText(row){return row.exists===false?"Verifierad frånvaro":String(row.balance_atomic)+" atomer · nonce "+String(row.nonce)}
    function financialAccountDetail(row){return String(row.address)+" · "+(row.exists===false?"Kontot finns inte i verifierat tillstånd":financialAccountText(row))+(row.certificate_height!==undefined?" · certifikat "+String(row.certificate_height):"")}
    function compareCounter(a,b){a=String(a);b=String(b);if(!/^(0|[1-9][0-9]*)$/.test(a)||!/^(0|[1-9][0-9]*)$/.test(b))return 0;return a.length-b.length||(a<b?-1:a>b?1:0)}
    function number(value){if(typeof value==="string"&&/^(0|[1-9][0-9]{0,18})$/.test(value)&&(value.length<19||value<="9223372036854775807"))return value;return typeof value==="number"&&isFinite(value)?String(value):"—"}
    function measured(value){return typeof value==="number"&&isFinite(value)&&value>=0}
    function acknowledgedRate(name){return hasDagAcknowledgement&&measured(dagStress[name])?dagStress[name].toFixed(1):"—"}
    function productionRate(name){var value=(ownNode.selected===true?ownNode.production:dagStress.production)||({});return value.basis==="LOCAL_OWN_PRODUCTION_NOT_NETWORK_CAPACITY"&&measured(value[name])?value[name].toFixed(1):"—"}
    function millis(value){return typeof value==="number"&&isFinite(value)&&value>=0?value.toFixed(2)+" ms":"—"}
    function bytes(value){return typeof value==="number"&&isFinite(value)&&value>=0?(value>=1048576?(value/1048576).toFixed(2)+" MiB":(value/1024).toFixed(1)+" KiB"):"—"}
    function shortId(value){value=String(value||"");return value.length>18?value.slice(0,8)+"…"+value.slice(-5):value||"—"}
    function copy(value){value=String(value||"");if(/^[0-9a-f]{64}$/.test(value)&&surfaceHost&&surfaceHost.tmogCopy)surfaceHost.tmogCopy(value)}
    function eventColor(kind){return /REJECT|FAIL|ERROR|CONFLICT/.test(String(kind||""))?RuntimeTheme.GGTheme.negative:/ADMIT|READY|START|WAVE/.test(String(kind||""))?RuntimeTheme.GGTheme.positive:RuntimeTheme.GGTheme.muted}
    onDockAvailableChanged:if(dockAvailable)factsDrawer.close()
    component PlainTip:ToolTip {id:plainTip;objectName:"dagPlainTooltip";contentItem:Text {objectName:"dagPlainTooltipText";text:plainTip.text;textFormat:Text.PlainText;font:plainTip.font;wrapMode:Text.Wrap;color:RuntimeTheme.GGTheme.text}}
    component Label:GGText {id:label;property string tip:text;property bool tipActive:tipHover.hovered&&truncated;property int tipDelay:350;font.family:"monospace";font.pixelSize:10;color:RuntimeTheme.GGTheme.text;textFormat:Text.PlainText;elide:Text.ElideRight;HoverHandler{id:tipHover}Loader {active:label.tipActive;sourceComponent:PlainTip {parent:label;visible:true;text:label.tip;delay:label.tipDelay}}}
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
            Action {property string uiColorScope:"ui.control.dag.lan";objectName:"dagLanSetup";text:root.lanOwned?"LAN · "+(root.connectionState?root.connectionLabel(root.connectionState):String(root.lan.state||"")):"LAN";enabled:true;onClicked:lanPopup.open()}
            Action { property string uiColorScope: "ui.control.GGParallelDagDashboard.5";objectName:"dagRefresh";width:26;tip:"Läs aktuell lokal DAG-status";onClicked:root.refreshRequested();contentItem:Item{LedgerGlyph{ property string uiColorScope: "ui.widget.GGParallelDagDashboard.LedgerGlyph.6";anchors.centerIn:parent;width:13;height:13;name:"refresh";color:RuntimeTheme.GGTheme.text}}}
            Action { property string uiColorScope: "ui.control.GGParallelDagDashboard.6";objectName:"dagStart";text:root.primaryActionText;tip:root.primaryActionTip;enabled:root.primaryActionEnabled;onClicked:root.triggerPrimary()}
            Action { property string uiColorScope: "ui.control.GGParallelDagDashboard.7";objectName:"dagStop";text:root.stopRequested?"■ Stoppar…":root.lanOwned?(root.width<600?"■ LAN-peer":"■ Stoppa LAN-peer"):"■ Stoppa";tip:root.lanOwned?"Avsluta den här apparatens LAN-peer":"Stoppa lokal DAG-session";enabled:!root.observerReadOnly&&(root.running||root.lanOwned)&&!root.stopRequested;onClicked:root.run("dag_stop",{})}
            Action { property string uiColorScope: "ui.control.GGParallelDagDashboard.8";objectName:"dagDetails";width:26;text:"⋯";enabled:true;tip:"Visa DAG-fakta";onClicked:root.toggleDetails()}
        }
        Rectangle {anchors.bottom:parent.bottom;width:parent.width;height:1;color:RuntimeTheme.GGTheme.line}
    }
    Item {id:sourceBar;objectName:"dagSourceBar";y:toolbar.height;width:parent.width;height:visible?38:0;visible:root.sourcePickerVisible
        ComboBox {id:sourcePicker;objectName:"dagObservationSourcePicker";x:8;y:3;width:Math.max(100,Math.min(parent.width-16,520));height:30
            model:root.sourceOptions;textRole:"display";enabled:root.sourceState.view_available!==false
            currentIndex:{for(var i=0;i<root.sourceOptions.length;i++)if(root.sourceOptions[i].handle===root.sourceState.selected_handle)return i;return -1}
            displayText:currentIndex<0||currentIndex>=root.sourceOptions.length?"Välj CLI-källa · skrivskyddad vy":String(root.sourceOptions[currentIndex].display)
            contentItem:Text {text:sourcePicker.displayText;textFormat:Text.PlainText;verticalAlignment:Text.AlignVCenter;elide:Text.ElideRight;font.pixelSize:11;color:RuntimeTheme.GGTheme.text}
            delegate:ItemDelegate {required property var modelData;width:sourcePicker.width;enabled:modelData.available!==false
                contentItem:Text {text:String(modelData.display);textFormat:Text.PlainText;elide:Text.ElideRight;font.pixelSize:11;color:RuntimeTheme.GGTheme.text}}
            onActivated:function(index){var row=root.sourceOptions[index];if(row&&row.available!==false)root.sourceSelectionRequested(String(row.handle))}
        }
        Label {objectName:"dagSourceAvailability";anchors.left:sourcePicker.right;anchors.leftMargin:8;anchors.right:parent.right;anchors.rightMargin:8;y:10
            visible:width>90;textFormat:Text.PlainText;elide:Text.ElideRight;font.pixelSize:10;color:RuntimeTheme.GGTheme.warning
            text:root.sourceState.view_available===false?"Egen Desktop-nod aktiv":root.sourceState.state==="UNAVAILABLE"?"Vald källa är inte tillgänglig":root.sourceState.state==="CHOICE_REQUIRED"?"Välj en nod. Inga konton blandas.":"Styrning i CLI"}
    }
    Item {id:main;objectName:"dagMainViewport";y:toolbar.height+sourceBar.height;width:root.mainWidth;height:Math.max(0,root.height-y);clip:true
        NetworkWorkspaceLayout {id:workspace;objectName:"dagMainLayout";property string uiColorScope:"ui.widget.dag.workspace";anchors.fill:parent;prefix:"dag";bookTitles:["Producenter","Skapa","Förslag","Mätning"];page:desktop?0:1
            summaryPanel:Column {spacing:5
                Label {visible:root.sourceUnavailable;width:parent.width;text:"Ingen tillgänglig CLI-källa vald";textFormat:Text.PlainText;font.pixelSize:10;color:RuntimeTheme.GGTheme.warning}
                Label {objectName:"dagSummaryScope";visible:!root.sourceUnavailable;textFormat:Text.PlainText;colorKey:"ui.dag.summary.caption";width:parent.width;text:root.protocolSource?"Testnät · "+String(root.lan.label||"Egen nod")+" · "+root.number(root.registeredProducerCount)+" registrerade producenter · "+root.number(root.localProducerCount)+" egna · SDK-certifierad vy":root.lanOwned?"Privat LAN · "+String(root.lan.label||"Egen nod")+" · "+root.number(root.eligibleProducerCount)+" producenter · "+root.number(root.localProducerCount)+" egna · lokal validering, nätkvittens separat":"Signerade förslag · "+root.producerCount+" lokala producenter · kontrollpunkt krävs för finalitet";font.pixelSize:9;color:RuntimeTheme.GGTheme.dim}
                Label {objectName:"dagObservationSource";textFormat:Text.PlainText;width:parent.width;visible:root.observerReadOnly;text:"Visar CLI-noden "+String(root.observation.node_label||"")+" · "+(root.observation.stale===true?"ÄLDRE DATA":"live")+" · styrning i CLI";font.pixelSize:9;color:root.observation.stale===true?RuntimeTheme.GGTheme.warning:RuntimeTheme.GGTheme.cyan}
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
                                PlainTip {visible:sampleHover.hovered;text:sampleHover.hovered?(modelData.kind==="async_proposal"?"Producent "+(Number(modelData.producer_index)+1):"Våg "+modelData.sequence)+" · "+root.millis(modelData.producer_ms)+" signering · "+root.millis(modelData.validation_ms)+" validering · "+root.millis(modelData.total_ms)+" totalt":""}
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
            relationsPanel:Item {
                BlockRelationsGraph {anchors.fill:parent;visible:!root.sdkSource||(root.graph.blocks||[]).length>0;property string uiColorScope:"ui.widget.dag.graph";objectName:"dagBlockRelationsGraph";graph:root.graph;surfaceHost:root.surfaceHost}
                Label {objectName:"dagSparseProofScope";anchors.centerIn:parent;width:Math.max(0,parent.width-24);visible:root.sdkSource&&!(root.graph.blocks||[]).length;horizontalAlignment:Text.AlignHCenter;wrapMode:Text.WordWrap;font.pixelSize:10;color:RuntimeTheme.GGTheme.dim;text:(root.financialSource?"Valda betalningsblock · ":"Aktivt segment · ")+root.proofRows.length+" verifierade blockbevis. Föräldralänkar visas när originalblocken har hämtats."}
            }
            accountsPanel:Item {objectName:"dagProducersPanel"
                Head {property string uiColorScope:"ui.widget.dag.producers.head";title:"PRODUCENTER";detail:root.sdkSource?"SDK-certifierade räknare":(root.dag.producers||[]).length?"sessionens mätvärden":"hämtad delvy"}
                Item {y:20;width:parent.width;height:15
                    Label {colorKey:"ui.dag.producer.column.node";width:parent.width*.46;text:"NOD";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim}
                    Label {colorKey:"ui.dag.producer.column.blocks";x:parent.width*.46;width:parent.width*.14;text:root.segmentedSource?"BLOCK":"FÖRSLAG";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim;horizontalAlignment:Text.AlignRight}
                    Label {objectName:"dagProducerTransactionColumn";colorKey:"ui.dag.producer.column.tx";x:parent.width*.63;width:parent.width*.15;text:root.protocolSource?"TX-försök":"TX";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim;horizontalAlignment:Text.AlignRight}
                    Label {colorKey:"ui.dag.producer.column.seq";x:parent.width*.81;width:parent.width*.19;text:root.asynchronous?"MÄTT /s":"SEKVENS";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim;horizontalAlignment:Text.AlignRight}
                }
                ListView {objectName:"dagProducersList";y:35;width:parent.width;height:Math.max(0,parent.height-y-15);clip:true;model:root.producerRows.length;boundsBehavior:Flickable.StopAtBounds;ScrollBar.vertical:ScrollBar{}
                    delegate:Item {required property int index;readonly property var modelData:root.producerRows[index]||({});objectName:"dagProducerRow";width:ListView.view.width;height:25
                        Rectangle {id:producerMarker;x:1;y:10;width:5;height:5;radius:3;color:root.producerColor(modelData.index);GGColorTarget{target:producerMarker;colorKey:"ui.graph.block.producer."+modelData.index}}
                        Label {objectName:"dagProducerName";colorKey:"ui.dag.producer.name";x:12;y:5;width:parent.width*.46-12;text:modelData.name;font.pixelSize:9;elide:Text.ElideRight;HoverHandler{id:producerNameHover}tipActive:producerNameHover.hovered;tip:modelData.name+root.producerAccountText(modelData.index)}
                        Label {colorKey:"ui.dag.producer.blocks";x:parent.width*.46;y:5;width:parent.width*.14;text:root.number(modelData.blocks);font.pixelSize:9;horizontalAlignment:Text.AlignRight}
                        Label {colorKey:"ui.dag.producer.tx";x:parent.width*.63;y:5;width:parent.width*.15;text:root.number(modelData.transactions);font.pixelSize:9;horizontalAlignment:Text.AlignRight}
                        Label {colorKey:"ui.dag.producer.seq";x:parent.width*.81;y:5;width:parent.width*.19;text:root.asynchronous?typeof modelData.rate==="number"?modelData.rate.toFixed(1):"—":root.number(modelData.sequence);font.pixelSize:9;color:RuntimeTheme.GGTheme.dim;horizontalAlignment:Text.AlignRight}
                        Rectangle {anchors.bottom:parent.bottom;width:parent.width;height:1;color:RuntimeTheme.GGTheme.line;opacity:.6}
                    }
                }
                Label {objectName:"dagProducerScope";colorKey:"ui.dag.producer.scope";y:parent.height-13;width:parent.width;text:root.eligibleProducerCount+" producenter · "+root.number(root.dag.worker_count)+" aktiva trådar · "+(root.lanOwned?root.number(root.localProducerCount)+" egna, övriga från LAN":"en dator");font.pixelSize:8;color:RuntimeTheme.GGTheme.dim}
            }
            historyPanel:Item {objectName:"dagProposalsViewport"
                Head {property string uiColorScope:"ui.widget.dag.proposals.head";title:root.membershipOnly?"VERIFIERADE BLOCKBEVIS":"SENASTE FÖRSLAG";detail:root.membershipOnly?root.proofRows.length+" bevis · "+(root.graph.blocks||[]).length+(root.protocolSource?" SDK-summeringar":" verifierade original"):root.rows.length+" st · "+(Number(root.dag.canonical_finalized)>0?"✓ = SDK-medlemsbevis":"ej finalitet")}
                Item {y:20;width:parent.width;height:15
                    Label {colorKey:"ui.dag.proposal.column.hash";width:parent.width*.32;text:"HASH";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim}
                    Label {colorKey:"ui.dag.proposal.column.rank";x:parent.width*.32;width:parent.width*.10;text:root.membershipOnly?"POS":"RANG";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim;horizontalAlignment:Text.AlignRight}
                    Label {colorKey:"ui.dag.proposal.column.parents";x:parent.width*.44;width:parent.width*.11;text:"LÄNKAR";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim;horizontalAlignment:Text.AlignRight}
                    Label {colorKey:"ui.dag.proposal.column.tx";x:parent.width*.57;width:parent.width*.11;text:"TX";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim;horizontalAlignment:Text.AlignRight}
                    Label {colorKey:"ui.dag.proposal.column.status";x:parent.width*.70;width:parent.width*.30;text:root.membershipOnly?"NOD / SDK-BEVIS":"NOD / SIGNATUR";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim}
                }
                ListView {objectName:"dagProposalsList";y:35;width:parent.width;height:Math.max(0,parent.height-y);clip:true;model:root.membershipOnly?root.proofRows.length:root.rows.length;boundsBehavior:Flickable.StopAtBounds;ScrollBar.vertical:ScrollBar{}
                    delegate:Item {required property int index;readonly property var modelData:(root.membershipOnly?root.proofRows:root.rows)[index]||({});objectName:"dagProposalRow";width:ListView.view.width;height:25
                        Label {objectName:"dagProposalMembership";colorKey:"ui.dag.proposal.hash";y:5;width:parent.width*.32;text:(modelData.canonical_membership_verified===true?"✓ ":"")+root.shortId(modelData.hash);font.pixelSize:9;color:modelData.canonical_membership_verified===true?RuntimeTheme.GGTheme.positive:RuntimeTheme.GGTheme.muted;HoverHandler{id:proposalMembershipHover}tipActive:proposalMembershipHover.hovered;tip:modelData.canonical_membership_verified===true?"SDK-verifierat medlemskap · kanonisk position "+String(modelData.canonical_index):"Lokalt godtaget · ej finaliserat"}
                        Label {colorKey:"ui.dag.proposal.rank";x:parent.width*.32;y:5;width:parent.width*.10;text:root.number(root.membershipOnly?modelData.canonical_index:modelData.rank);font.pixelSize:9;horizontalAlignment:Text.AlignRight}
                        Label {colorKey:"ui.dag.proposal.parents";x:parent.width*.44;y:5;width:parent.width*.11;text:root.membershipOnly?root.originalParentCount(modelData.hash):(modelData.parent_hashes||[]).length;font.pixelSize:9;horizontalAlignment:Text.AlignRight}
                        Label {colorKey:"ui.dag.proposal.tx";x:parent.width*.57;y:5;width:parent.width*.11;text:root.number(modelData.transaction_count);font.pixelSize:9;horizontalAlignment:Text.AlignRight}
                        Rectangle {x:parent.width*.70;y:10;width:5;height:5;radius:3;color:modelData.canonical_membership_verified===true?RuntimeTheme.GGTheme.positive:modelData.signature_verified?RuntimeTheme.GGTheme.cyan:RuntimeTheme.GGTheme.dim}
                        Label {objectName:"dagProposalOwner";colorKey:"ui.dag.proposal.node";x:parent.width*.70+8;y:5;width:parent.width*.30-8;text:modelData.proposer_key?root.producerKeyName(modelData.proposer_key):Number(modelData.proposer_index)>=0?root.producerName(modelData.proposer_index):"Genesis";font.pixelSize:8;elide:Text.ElideRight;color:RuntimeTheme.GGTheme.cyan;HoverHandler{id:proposalOwnerHover}tipActive:proposalOwnerHover.hovered;tip:text+(modelData.worker_key?"\nMiningarbete: "+root.workerKeyName(modelData.worker_key)+"\nArbetarnyckel: "+modelData.worker_key+"\nArbetsbevis: "+modelData.work_hash:"")}
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
                Label {objectName:"dagOperationNotice";colorKey:"ui.dag.job.notice";width:parent.width;text:root.notice;font.pixelSize:9;color:root.operation.error||root.dag.error||(root.activeTransportError||(root.lanOwned&&root.dagStress.last_error))||root.live.state==="ERROR"?RuntimeTheme.GGTheme.negative:root.liveLimited?RuntimeTheme.GGTheme.warning:RuntimeTheme.GGTheme.dim}
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
                        Fact {property string uiColorScope:"ui.widget.dag.rail.storage";objectName:"dagNodeStorage";name:"Lagring";value:root.lanOwned&&root.lan.storage&&root.lan.storage.enabled===true?"Profil "+String(root.lan.storage.profile||"")+(root.lan.storage.restored===true?" · återläst":" · beständig"):"RAM · ny parning efter omstart";visible:root.lanOwned}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.status";name:"Status";value:root.liveLabel;valueColor:root.liveLimited?RuntimeTheme.GGTheme.warning:root.liveRunning?RuntimeTheme.GGTheme.positive:RuntimeTheme.GGTheme.dim}
                        Fact {objectName:"dagNodeOwner";visible:root.lanOwned;name:"Egen nod";value:String(root.lan.label||"—")}
                        Fact {objectName:"dagParticipationRole";visible:root.lanOwned;name:"Roll";value:root.participationLabel}
                        Fact {objectName:"dagQuarantinedProducers";visible:root.lanOwned&&(root.dag.producers||[]).some(function(row){return row.quarantined===true});name:"Producentkarantän";value:(root.dag.producers||[]).filter(function(row){return row.quarantined===true}).length+" · övriga kan fortsätta"}
                        Fact {objectName:"dagProofStatus";visible:root.lanOwned&&!!root.dag.dag_proofs;name:"SDK-bevis";value:String(root.dagProofs.state||"WAITING_FOR_CERTIFICATE")}
                        Fact {objectName:"dagPayloadRecovery";visible:root.lanOwned&&!root.membershipOnly&&root.payloadRecovery.enabled===true;name:"Data från SDK";value:root.payloadRecoveryText}
                        Fact {objectName:"dagCertifiedAccount";visible:root.lanOwned&&!root.financialSource&&!!root.dag.dag_proofs;name:"Bevisat eget testkonto";value:root.certifiedOwnAccounts.length?String(root.certifiedOwnAccounts[0].balance_atomic)+" atomer · nonce "+String(root.certifiedOwnAccounts[0].nonce):"Väntar på kontobevis";HoverHandler{id:accountProofHover}PlainTip {visible:accountProofHover.hovered;text:root.certifiedOwnAccounts.map(function(row){return String(row.display_name)+" · "+String(row.balance_atomic)+" atomer · nonce "+String(row.nonce)}).join("\n")}}
                        Fact {objectName:"dagFinancialAccount";visible:root.financialSource;name:root.financialAccountLabel?"Konto · "+root.financialAccountLabel:"Verifierat eget konto";value:root.ownFinancialAccounts.length?root.financialAccountText(root.ownFinancialAccounts[0]):"Väntar på certifierat kontotillstånd";HoverHandler{id:financialAccountHover}PlainTip {visible:financialAccountHover.hovered;text:root.ownFinancialAccounts.map(function(row){return root.financialAccountDetail(row)}).join("\n")}}
                        Fact {objectName:"dagFinancialRelay";visible:root.financialSource&&root.dagProofs.account_tree!==undefined&&root.dagProofs.account_tree!==null;name:"Betalningsförmedling";value:root.financialRelayText;HoverHandler{id:financialRelayHover}PlainTip {visible:financialRelayHover.hovered;text:"Köstatus visar förmedlingen. Betalningens utfall och saldo kommer från nätverkets verifierade kvitton och konton."}}
                        Fact {objectName:"dagFinancialAccountCount";visible:root.financialSource&&!!root.dagProofs.account_tree;name:"Verifierade konton";value:root.dagProofs.account_tree?String(root.dagProofs.account_tree.count):"—"}
                        Fact {objectName:"dagFinancialPolicy";visible:root.financialSource;name:"Ekonomi";value:root.protocolSource?"PoW · epok "+String((root.dag.economic_state||{}).next_epoch||"0")+" · utgivet "+String((root.dag.economic_state||{}).issued_atomic||"—")+" atomiska":"Fast testtilldelning · ingen mining"}
                        Fact {objectName:"dagConsensusBinding";visible:root.lanOwned&&root.dagConsensus.anchor_bound===true;name:"Kommitté";value:root.number(root.dagConsensus.validator_count)+" · kvorum "+String(root.protocolSource?root.dagConsensus.quorum_voting_power_required:root.dagConsensus.quorum_required);HoverHandler{id:consensusHover}PlainTip {visible:consensusHover.hovered;text:root.consensusMembers}}
                        Fact {objectName:"dagValidatorProfiles";visible:root.lanOwned&&(root.dagConsensus.profiles||[]).length>0;name:"Egna validatorer";value:root.number(root.dagConsensus.own_running)+" igång / "+(root.dagConsensus.profiles||[]).length+" profiler"}
                        Repeater {objectName:"dagNativeObservers";model:root.lanOwned?root.nativeObserverRows:[]
                            Fact {required property var modelData;objectName:"dagNativeObserver_"+String(modelData.profile);width:parent.width;name:String(modelData.profile);value:root.nativeObserverText(modelData);valueColor:!root.observation.stale&&modelData.native_connection&&modelData.native_connection.state==="CONNECTED"?RuntimeTheme.GGTheme.positive:RuntimeTheme.GGTheme.warning
                                HoverHandler{id:nativeObserverHover}
                                ToolTip {id:nativeObserverInfo;objectName:"dagNativeObserverInfo";visible:nativeObserverHover.hovered;text:root.nativeObserverDetails(modelData)
                                    contentItem:Text {text:nativeObserverInfo.text;textFormat:Text.PlainText;font.family:"monospace";font.pixelSize:10;color:RuntimeTheme.GGTheme.text}
                                }
                            }
                        }
                        Fact {objectName:"dagConsensusCertificate";visible:root.lanOwned&&root.dagConsensus.anchor_bound===true;name:"Verifierat certifikat";value:root.dagConsensus.state==="FAULT"?"Verifieringsfel":typeof root.dagConsensus.certificate_height==="number"?"Höjd "+root.number(root.dagConsensus.certificate_height):"Väntar";valueColor:root.dagConsensus.state==="FAULT"?RuntimeTheme.GGTheme.warning:RuntimeTheme.GGTheme.dim}
                        Fact {objectName:"dagConsensusCertifiedBlocks";visible:root.lanOwned&&root.dagConsensus.anchor_bound===true;name:root.protocolSource&&root.financialSource?"Certifierad tillståndsrot":"Certifierad DAG-rot";value:root.protocolSource&&root.financialSource?(root.certifiedStateRoot?root.shortId(root.certifiedStateRoot):"Saknas"):root.number(root.dagConsensus.certified_dag_blocks)!=="—"?root.number(root.dagConsensus.certified_dag_blocks)+" block / "+root.number(root.dagConsensus.certified_dag_transactions)+" TX":"Saknas";HoverHandler{id:stateRootHover}PlainTip {visible:stateRootHover.hovered&&!!root.certifiedStateRoot;text:root.certifiedStateRoot}}
                        Fact {objectName:"dagConnectionStatus";visible:root.lanOwned;name:"Kontakt nu";value:root.connectionLabel(root.connectionState);valueColor:root.connectionState==="CONNECTED"?RuntimeTheme.GGTheme.positive:RuntimeTheme.GGTheme.warning;HoverHandler{id:connectionHover}PlainTip {visible:connectionHover.hovered;text:root.connectionDetails}}
                        Fact {objectName:"dagArchiveStartupStatus";visible:root.protocolSource&&root.hasArchiveStartup;name:"Nodstart och historikverifiering";value:root.archiveStartupLabel();HoverHandler{id:archiveStartupHover}PlainTip {visible:archiveStartupHover.hovered;text:root.archiveStartupDetails}}
                        Fact {objectName:"dagArchiveStartupProgress";visible:root.protocolSource&&root.hasArchiveStartup;name:"Bearbetad / verifierad höjd";value:(root.archiveStartupValid?root.archiveHeight(root.archiveStartup.processed_height):"—")+" / "+(root.archiveStartupValid&&root.archiveStartup.full_original_audit_completed===true?root.archiveHeight(root.archiveStartup.verified_through):"—")}
                        Fact {objectName:"dagLocalHistoryStatus";visible:root.protocolSource;name:"Lokal historik";value:root.localHistoryLabel();HoverHandler{id:localHistoryHover}PlainTip {visible:localHistoryHover.hovered;text:root.localHistoryDetails}}
                        Fact {objectName:"dagLocalHistoryAudit";visible:root.protocolSource&&root.hasLocalHistoryReport;name:"Kall replay / bevarad höjd";value:String(root.localHistoryReport.verified_through)+" / "+String(root.localHistoryReport.retained_through)}
                        Fact {objectName:"dagLocalHistoryActive";visible:root.protocolSource&&root.hasLocalHistoryReport;name:"Aktiv historik";value:String(root.localHistoryReport.active_bytes)+" byte"}
                        Fact {objectName:"dagLocalHistoryArchive";visible:root.protocolSource&&root.hasLocalHistoryReport;name:"Historikarkiv";value:String(root.localHistoryReport.archive_segments)+" segment · "+String(root.localHistoryReport.archive_bytes)+" byte"}
                        Repeater {objectName:"dagOwnAccountJournals";model:root.protocolSource?root.ownJournalAccounts:[]
                            Fact {required property var modelData;objectName:"dagOwnAccountJournal_"+String(modelData.profile);name:"Original · "+String(modelData.profile);value:root.ownJournalCounter(modelData.signed_batches_exact)+" batch · "+root.ownJournalCounter((modelData.journal||{}).archive_segments)+" arkiv";HoverHandler{id:ownAccountJournalHover}PlainTip {visible:ownAccountJournalHover.hovered;text:root.ownJournalDetails(modelData.journal)}}
                        }
                        Repeater {objectName:"dagOwnPoolJournals";model:root.protocolSource?root.ownJournalPools:[]
                            Fact {required property var modelData;objectName:"dagOwnPoolJournal_"+String(modelData.name);name:"Pool · "+String(modelData.name);value:root.ownJournalCounter(modelData.retained_events_exact)+" händelser · "+root.ownJournalCounter((modelData.own_journal||{}).archive_segments)+" arkiv";HoverHandler{id:ownPoolJournalHover}PlainTip {visible:ownPoolJournalHover.hovered;text:root.ownJournalDetails(modelData.own_journal)}}
                        }
                        Fact {objectName:"dagCertifiedClock";visible:root.protocolSource;name:"Certifierad tid";value:root.dag.certified_time_ns?Qt.formatDateTime(new Date(Number(root.dag.certified_time_ns)/1000000),"HH:mm:ss"):"—"}
                        Fact {objectName:"dagReceivedTraffic";visible:root.lanOwned;name:"TCP mottaget";value:root.bytes(root.lan.traffic_bytes)}
                        Fact {objectName:"dagCatchupStatus";visible:root.lanOwned;name:"Senast hämtat";value:root.syncSummary;HoverHandler{id:syncHover}PlainTip {visible:syncHover.hovered;text:root.connectionDetails}}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.engine";name:"Motor";value:"DAGoblin · experiment"}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.producers";name:"Producenter / trådar";value:root.number(root.lanOwned?root.eligibleProducerCount:root.dag.producer_count)+" / "+root.number(root.dag.worker_count)}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.peers";name:"Peers";value:root.lanOwned?(root.lan.authenticated_peers||[]).length+" autentiserade / "+root.number(root.lan.configured_peers)+" parade":"0 · inget P2P"}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.parents";name:"Föräldrar / förslag";value:"Högst "+root.number(root.limits.max_parents||7)}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.cadence";name:root.asynchronous?"Målintervall":"Vågintervall";value:typeof root.live.interval_ms==="number"?root.number(root.live.interval_ms)+" ms":"—"}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.target";name:"Mål · förslag / s";value:typeof root.live.target_proposal_bps==="number"?root.live.target_proposal_bps.toFixed(1):typeof root.live.interval_ms==="number"&&root.live.interval_ms>0?(Number(root.live.blocks)*1000/root.live.interval_ms).toFixed(1):"—"}
                        Fact {objectName:"dagObservedBlockRate";property string uiColorScope:"ui.widget.dag.rail.measured";name:root.protocolSource?"Observerade block / s":"Uppmätt / s · 5 s";value:root.graph.metrics&&typeof root.graph.metrics.bps==="number"?root.graph.metrics.bps.toFixed(1):"—";valueColor:RuntimeTheme.GGTheme.cyan}
                        Fact {objectName:"dagObservedPaymentRate";property string uiColorScope:"ui.widget.dag.rail.measured.tx";name:root.protocolSource?"Observerad utförd TX / s":"Lokalt validerad TX / s";value:root.graph.metrics&&typeof root.graph.metrics.tps==="number"?root.graph.metrics.tps.toFixed(1):"—";valueColor:RuntimeTheme.GGTheme.cyan}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.session";name:"Session";value:root.shortId(root.dag.chain_id)}
                    },
                    Column {spacing:0
                        Head {property string uiColorScope:"ui.widget.dag.rail.sign.head";title:root.financialSource?"BETALNINGAR & FINALITET":"SIGNATURER & FÖRHANDSVY"}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.sign";visible:!root.financialSource;name:"Signaturkontroller";value:root.number(root.admission.signature_checks)}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.preview";visible:!root.financialSource;name:"Accepterat i förhandsvy";value:root.number(root.preview.accepted);valueColor:RuntimeTheme.GGTheme.cyan}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.conflicts";visible:!root.financialSource;name:"Konflikter / dubbletter";value:root.number(root.preview.conflicts)+" / "+root.number(root.preview.duplicates)}
                        Fact {objectName:"dagCanonicalFinality";property string uiColorScope:"ui.widget.dag.rail.finality";name:"Finalitet";value:root.dagConsensus.state==="FAULT"?"Verifieringsfel":root.sdkSource?(root.dagProofs.canonical_finality===true?"SDK-certifierat tillstånd":"Väntar på SDK-certifikat"):(root.lightOnly?root.proofRows.length>0:Number(root.dag.canonical_finalized)>0)?"SDK-verifierat medlemskap":"Kontrollpunkt krävs";valueColor:(root.sdkSource?root.dagProofs.canonical_finality===true:(root.lightOnly?root.proofRows.length>0:Number(root.dag.canonical_finalized)>0))?RuntimeTheme.GGTheme.positive:RuntimeTheme.GGTheme.warning}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.finalized";name:root.sdkSource?"SDK-valda block":root.lightOnly?"Verifierade blockbevis":"Kanoniskt finaliserade";value:root.number(root.sdkSource?root.dag.certified_blocks:root.lightOnly?root.proofRows.length:root.dag.canonical_finalized)}
                        Fact {objectName:"dagFinancialApplied";visible:root.financialSource;name:"Utförda betalningar";value:root.number(root.dag.certified_transactions)}
                        Fact {objectName:"dagFinancialRejected";visible:root.financialSource;name:"Avvisade betalningar";value:root.number(root.dag.rejected_transactions)}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.test.tokens";visible:root.testTokens.enabled===true;name:"Testledger · kvitterad TX";value:root.number(root.testTokens.sequence);valueColor:RuntimeTheme.GGTheme.cyan}
                        Fact {property string uiColorScope:"ui.widget.dag.rail.test.rate";visible:root.testTokens.enabled===true;name:"Testledger · TX/s";value:typeof root.tokenCircle.tps==="number"?root.tokenCircle.tps.toFixed(1):"—"}
                        Fact {objectName:"dagStressLocalCounts";property string uiColorScope:"ui.widget.dag.rail.stress.local";visible:root.dagStress.supported===true&&root.dagStress.enabled===true;name:"Prov · lokala förslag / TX";value:root.number(root.dagStress.blocks)+" / "+root.number(root.dagStress.transactions)}
                        Fact {objectName:"dagOwnProductionBlockRate";visible:root.dagStress.supported===true&&root.dagStress.enabled===true;name:"Egen produktion · block/s";value:root.productionRate("bps")}
                        Fact {objectName:"dagOwnProductionTxRate";visible:root.dagStress.supported===true&&root.dagStress.enabled===true;name:"Egen produktion · TX/s";value:root.productionRate("tps")}
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
    Loader {x:root.mainWidth;y:toolbar.height+sourceBar.height;width:root.railWidth;height:Math.max(0,root.height-y);active:root.railVisible;visible:active;sourceComponent:factsComponent}
    LanDagSetupPopup {id:lanPopup;parent:root.Window.window?root.Window.window.contentItem:root;placementAnchor:root;state:root.dag;setupCapabilities:(root.state.lan_dag||({})).dag_stress||({});surfaceHost:root.surfaceHost;canAct:root.canAct;localRunning:root.running&&!root.lanOwned;stopPending:root.stopRequested;operationError:root.stopError||String(root.operation.error||"");onActionRequested:function(name,args){root.run(name,args)};onPriorityStopRequested:root.run("dag_stop",{});onRefreshRequested:root.refreshRequested()}
    Popup {id:factsDrawer;objectName:"dagFactsDrawer";x:Math.max(0,root.width-width);y:toolbar.height+sourceBar.height;width:Math.min(360,root.width);height:Math.max(0,root.height-y);padding:0;modal:true;focus:true;closePolicy:Popup.CloseOnEscape|Popup.CloseOnPressOutside
        background:Frame {property string uiColorScope:"ui.widget.dag.drawer";color:RuntimeTheme.GGTheme.base}
        contentItem:Item {Action {property string uiColorScope:"ui.control.dag.drawer.close";anchors.right:parent.right;y:3;width:28;text:"×";enabled:true;onClicked:factsDrawer.close()}
            Loader {y:28;width:parent.width;height:Math.max(0,parent.height-y);active:factsDrawer.visible;sourceComponent:factsComponent}
        }
    }
}
