import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

// Four owned CometBFT processes on one computer. This view reports their real
// certificates and samples; it never presents the local setup as a public L1.
Item {
    id: root
    objectName: "consensusDashboard"
    property var state: ({})
    property var surfaceHost: null
    property bool sidePanelOpen: true
    property int senderIndex: 0
    property int recipientIndex: 1
    readonly property var consensus: state.consensus || ({})
    readonly property var operation: state.ui_operation || ({})
    readonly property var validators: consensus.validators || []
    readonly property var accounts: consensus.accounts || []
    readonly property var proof: consensus.proof || ({})
    readonly property var review: consensus.review || null
    readonly property var transactions: (consensus.transactions || []).slice(0, 64)
    readonly property var events: (consensus.events || []).slice(0, 48)
    readonly property var measurements: (consensus.measurements || []).filter(function(m) { return typeof m.elapsed_ms === "number" && isFinite(m.elapsed_ms) && m.elapsed_ms >= 0 }).slice(-32)
    readonly property var lastTest: consensus.last_test || ({})
    readonly property var benchmark: consensus.benchmark || ({})
    readonly property var webNode: state.consensus_web || ({})
    readonly property var publicSample: state.consensus_sample || null
    readonly property bool sampleReady: !!publicSample && !!publicSample.genesis && publicSample.genesis.chain_id === consensus.chain_id && !!publicSample.state
    readonly property bool busy: operation.state === "running"
    readonly property bool approvalPending: operation.state === "approval_required"
    readonly property bool canAct: !busy && !approvalPending
    readonly property bool stopped: consensus.state === "STOPPED"
    readonly property bool nodeOwned: ["RUNNING", "DEGRADED", "NO_QUORUM", "READ_FAILED"].indexOf(consensus.state) >= 0
    readonly property int onlineCount: validators.filter(function(v) { return v.alive === true && v.identity_verified === true }).length
    readonly property bool proofReady: proof.verified === true && proof.validator_count === 4 && proof.quorum_required === 3 && validators.length === 4 && validHash(proof.state_root) && validHash(proof.account_root) && typeof proof.state_height === "number" && proof.state_height >= 0 && proof.state_height % 1 === 0 && proof.state_height === consensus.state_height && proof.certificate_height === proof.state_height + 1
    readonly property bool quorumReady: onlineCount >= 3 && Number(consensus.online) >= 3 && consensus.quorum_required === 3
    readonly property bool running: ["RUNNING", "DEGRADED"].indexOf(consensus.state) >= 0 && quorumReady && proofReady
    readonly property bool readFailed: consensus.state === "READ_FAILED"
    readonly property bool hasReview: !!review
    readonly property int reviewedSenderIndex: review ? accounts.findIndex(function(a) { return a.address === review.sender }) : -1
    readonly property int reviewedRecipientIndex: review ? accounts.findIndex(function(a) { return a.address === review.recipient }) : -1
    readonly property bool unresolved: consensus.unresolved === true || transactions.some(function(t) { return t.state === "SUBMITTED" || t.state === "BROADCAST_UNKNOWN" })
    readonly property bool editable: canAct && running && !hasReview && !unresolved
    readonly property bool validAmount: validQuantity(amount.text.trim())
    readonly property string sourceAddress: sender.currentIndex >= 0 && sender.currentIndex < accounts.length ? String(accounts[sender.currentIndex].address || "") : ""
    readonly property string recipientAddress: recipient.currentIndex >= 0 && recipient.currentIndex < accounts.length ? String(accounts[recipient.currentIndex].address || "") : ""
    readonly property bool canPrepare: editable && validAmount && validHash(sourceAddress) && validHash(recipientAddress) && sourceAddress !== recipientAddress
    readonly property bool validReview: reviewValid()
    readonly property bool dockAvailable: width >= 820
    readonly property bool railVisible: dockAvailable && sidePanelOpen
    readonly property bool detailsVisible: railVisible || factsDrawer.visible
    readonly property real railWidth: Math.max(248, Math.min(360, width * .27))
    readonly property real mainWidth: Math.max(0, width - (railVisible ? railWidth : 0))
    readonly property bool compactDensity: width < 1200 || height < 760
    readonly property var accountChoices: accounts.map(function(a, i) { return { name: "Konto " + (i + 1), address: a.address } })
    readonly property string stateLabel: ({ STOPPED: "Stoppat", RUNNING: "Igång", DEGRADED: "Reducerat · quorum finns", NO_QUORUM: "Quorum saknas", READ_FAILED: "Läsfel · äldre data" })[consensus.state] || "Inväntar status"
    readonly property var resourceSummary: {
        var bytes = 0, cpu = 0, memorySamples = 0, cpuSamples = 0
        for (var i = 0; i < validators.length; i++) {
            var v = validators[i]
            if (typeof v.memory_private_bytes === "number" && isFinite(v.memory_private_bytes) && v.memory_private_bytes >= 0) { bytes += v.memory_private_bytes; memorySamples++ }
            if (typeof v.cpu_seconds === "number" && isFinite(v.cpu_seconds) && v.cpu_seconds >= 0) { cpu += v.cpu_seconds; cpuSamples++ }
        }
        return { bytes: memorySamples ? bytes : null, cpu: cpuSamples ? cpu : null, memory_samples: memorySamples, cpu_samples: cpuSamples }
    }
    signal actionRequested(string name, var args)
    signal refreshRequested()
    signal pageRequested(string page)
    signal webRequested(string url)
    onDockAvailableChanged: if (dockAvailable) factsDrawer.close()
    onReviewChanged: syncReview()
    Component.onCompleted: syncReview()

    function validHash(value) { return typeof value === "string" && /^[0-9a-fA-F]{64}$/.test(value) }
    function validQuantity(value) { return typeof value === "string" && value.length <= 32 && /^(?:0|[1-9]\d*)(?:\.\d{1,6})?$/.test(value) && /[1-9]/.test(value) }
    function syncReview() { if (review && amount) amount.text = String(review.amount || "") }
    function short(value) { value = String(value || ""); return value.length > 22 ? value.slice(0, 8) + "…" + value.slice(-6) : value || "—" }
    function present(value) { return value === undefined || value === null ? "—" : String(value) }
    function timeText(value) { return value ? new Date(Number(value) * 1000).toLocaleTimeString(Qt.locale(), "HH:mm:ss") : "—" }
    function accountName(value) { for (var i = 0; i < accounts.length; i++) if (accounts[i].address === value) return "Konto " + (i + 1); return "Okänt konto" }
    function stateText(value) { return ({ FINALIZED: "Slutförd", SUBMITTED: "Inskickad", BROADCAST_UNKNOWN: "Utfall okänt", REJECTED: "Avvisad", PASS: "Godkänd", FAIL: "Underkänd", RUNNING: "Pågår" })[value] || String(value || "—") }
    function statusColor(value) { return /FAIL|ERROR|REJECT|INVALID/.test(value) ? RuntimeTheme.GGTheme.negative : /UNKNOWN|SUBMITTED|QUORUM|DEGRADED|RUNNING/.test(value) ? RuntimeTheme.GGTheme.accent : /FINALIZED|PASS|VERIFIED|READY/.test(value) ? RuntimeTheme.GGTheme.positive : RuntimeTheme.GGTheme.muted }
    function sampleSeries(value) { return value.state === "FAIL" ? "error" : value.operation === "transfer" ? "transfer" : value.operation === "verify" ? "verify" : "other" }
    function sampleColor(value) { return RuntimeTheme.GGColorContext.colorFor("ui.chart.consensus."+sampleSeries(value), value.state === "FAIL" ? RuntimeTheme.GGTheme.negative : value.operation === "transfer" ? RuntimeTheme.GGTheme.cyan : value.operation === "verify" ? RuntimeTheme.GGTheme.purple : RuntimeTheme.GGTheme.muted) }
    function copyPublic(value) { value = String(value || ""); if (canAct && validHash(value) && surfaceHost && surfaceHost.tmogCopy) surfaceHost.tmogCopy(value) }
    function copySample() { if (canAct && sampleReady && surfaceHost && surfaceHost.tmogCopy) surfaceHost.tmogCopy(JSON.stringify(publicSample)) }
    function openWeb() { var url = String(webNode.url || ""); if (canAct && webNode.state === "RUNNING" && webNode.pinned_chain_id === consensus.chain_id && /^http:\/\/127\.0\.0\.1:\d+\/$/.test(url)) webRequested(url) }
    function reviewValid() { return !!review && typeof review.id === "string" && review.id.length > 0 && validHash(review.review_digest) && validHash(review.sender) && validHash(review.recipient) && review.sender !== review.recipient && reviewedSenderIndex >= 0 && reviewedRecipientIndex >= 0 && review.sender_index === reviewedSenderIndex && validQuantity(review.amount) && review.symbol === "GG-NET-TEST" && typeof review.nonce === "number" && review.nonce >= 0 && review.nonce % 1 === 0 && review.chain_id === consensus.chain_id && typeof review.expires_at === "number" && review.expires_at > Date.now() / 1000 }
    function toggleDetails() { if (dockAvailable) { factsDrawer.close(); sidePanelOpen = !sidePanelOpen } else if (factsDrawer.visible) factsDrawer.close(); else factsDrawer.open() }
    function run(name, args) {
        if (!canAct) return
        args = args || {}
        if (name === "consensus_start") { if (!stopped || consensus.available !== true) return }
        else if (name === "consensus_stop") { if (!nodeOwned) return }
        else if (name === "consensus_stop_node" || name === "consensus_restart_node") {
            if (!nodeOwned || typeof args.index !== "number" || args.index % 1 !== 0 || args.index < 0 || args.index >= validators.length) return
            if (name === "consensus_stop_node" && validators[args.index].alive !== true) return
            if (name === "consensus_restart_node" && validators[args.index].alive === true) return
        } else if (name === "consensus_cancel") { if (!nodeOwned || !hasReview) return }
        else {
            if (!running || unresolved) return
            if (name === "consensus_prepare" && !canPrepare) return
            if (name === "consensus_send" && !reviewValid()) return
            if ((name === "consensus_self_test" || name === "consensus_benchmark") && (onlineCount !== 4 || hasReview)) return
        }
        actionRequested(name, args)
    }
    function prepare() { if (canPrepare) run("consensus_prepare", { sender: sender.currentIndex, recipient: recipientAddress, amount: amount.text.trim() }) }
    function send() { if (running && reviewValid() && !unresolved) run("consensus_send", { id: review.id, review_digest: review.review_digest }) }

    component Label: GGText { ToolTip.visible:labelHover.hovered&&truncated;ToolTip.text:text;ToolTip.delay:400;HoverHandler{id:labelHover} color: RuntimeTheme.GGTheme.text; font.family: "monospace"; font.pixelSize: 11; textFormat: Text.PlainText; elide: Text.ElideRight }
    component Rule: Rectangle { width: (parent ? parent.width : 0); height: 1; color: RuntimeTheme.GGTheme.line }
    component Action: CryptoButton { height: 24; font.pixelSize: 10; enabled: root.canAct }
    component Head: Item {
        property string title: ""
        property string detail: ""
        width: (parent ? parent.width : 0); height: 18
        Label { colorKey: "ui.GGConsensusDashboard.1"; height: (parent ? parent.height : 0) - 1; width: (parent ? parent.width : 0) - detailText.implicitWidth - 10; text: parent.title; color: RuntimeTheme.GGTheme.muted; font.pixelSize: 10; font.letterSpacing: .4; verticalAlignment: Text.AlignVCenter }
        Label { colorKey: "ui.GGConsensusDashboard.2"; id: detailText; anchors.right: parent.right; height: (parent ? parent.height : 0) - 1; text: parent.detail; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 9; verticalAlignment: Text.AlignVCenter }
        Rule { property string uiColorScope: "ui.widget.GGConsensusDashboard.Rule.1"; anchors.bottom: parent.bottom }
    }
    component Fact: Item {
        property string name: ""
        property string value: "—"
        property color valueColor: RuntimeTheme.GGTheme.text
        width:parent?parent.width:0;height:14
        Label { colorKey: "ui.GGConsensusDashboard.3";y:1;width:parent.width*.43-6;text:parent.name;color:RuntimeTheme.GGTheme.dim;font.pixelSize:9}
        Rectangle {x:Math.max(parent.width*.43-7,parent.width-Math.min(factValue.implicitWidth,factValue.width)-8);y:5;width:4;height:4;radius:2;color:parent.valueColor;visible:parent.name==="Status"}
        Label { colorKey: "ui.GGConsensusDashboard.4";id:factValue;y:1;x:parent.width*.43;width:parent.width-x;text:parent.value;color:parent.valueColor;horizontalAlignment:Text.AlignRight;font.pixelSize:9;wrapMode:Text.NoWrap;elide:Text.ElideRight}
        Rectangle {y:13;width:parent.width;height:1;color:RuntimeTheme.GGTheme.line;opacity:.35}
        Accessible.role:Accessible.StaticText;Accessible.name:name+": "+value
    }
    component CopyAction: Action {
        id: copyButton
        property string value: ""
        property Item viewport: null
        width: 24; height: 24; flat: true; quiet: true; enabled: root.canAct && root.validHash(value); tip: "Kopiera offentlig referens"; Accessible.name: tip
        contentItem: Item { LedgerGlyph { property string uiColorScope: "ui.widget.GGConsensusDashboard.LedgerGlyph.2"; anchors.centerIn: parent; width: 13; height: 13; name: "copy"; viewport: copyButton.viewport; color: copyButton.enabled ? RuntimeTheme.GGTheme.muted : RuntimeTheme.GGTheme.dim } }
        onClicked: root.copyPublic(value)
    }

    Item {
        id: toolbar; objectName: "consensusToolbar"; width: (parent ? parent.width : 0); height: root.width < 600 ? 62 : 32
        Row { x: 8; y: root.width < 600 ? 33 : 3; spacing: 6
            Action { property string uiColorScope: "ui.control.GGConsensusDashboard.1"; objectName: "consensusTestnetMode"; text: root.width<600?"EVM":"GG TESTNÄT"; flat: true; enabled: true; onClicked: root.pageRequested("TESTNET") }
            Action { property string uiColorScope: "ui.control.GGConsensusDashboard.2"; objectName: "consensusLabMode"; text: root.width<600?"LABB":"SIGNERAT LABB"; flat: true; enabled: true; onClicked: root.pageRequested("LAB") }
            Action { property string uiColorScope: "ui.control.GGConsensusDashboard.3"; objectName: "consensusValidatorMode"; text: root.width<600?"BFT":"VALIDATORER"; flat: true; checked: true; enabled: true; onClicked: root.pageRequested("CONSENSUS") }
            Action { property string uiColorScope: "ui.control.GGConsensusDashboard.4";objectName:"consensusDagMode";text:root.width<600?"DAG":"DAGoblin";flat:true;enabled:true;tip:"Parallella signerade förslag · separat experimentlabb";onClicked:root.pageRequested("DAG")}
        }
        Row { id: toolbarActions; y: 3; anchors.right: parent.right; anchors.rightMargin: 12; spacing: 6
            Action { property string uiColorScope: "ui.control.GGConsensusDashboard.5"; objectName: "consensusRefresh"; width: 28; tip: "Uppdatera validatorernas status"; Accessible.name: tip; onClicked: root.refreshRequested(); contentItem: Item { LedgerGlyph { property string uiColorScope: "ui.widget.GGConsensusDashboard.LedgerGlyph.8"; anchors.centerIn: parent; width: 15; height: 15; name: "refresh"; color: parent.parent.enabled ? RuntimeTheme.GGTheme.text : RuntimeTheme.GGTheme.dim } } }
            Action { property string uiColorScope: "ui.control.GGConsensusDashboard.6"; objectName: "consensusStart"; text: "▷ Starta"; enabled: root.canAct && root.stopped && root.consensus.available === true; onClicked: root.run("consensus_start", {}) }
            Action { property string uiColorScope: "ui.control.GGConsensusDashboard.7"; objectName: "consensusStop"; text: "■ Stoppa"; enabled: root.canAct && root.nodeOwned; onClicked: root.run("consensus_stop", {}) }
            Action { property string uiColorScope: "ui.control.GGConsensusDashboard.8"; objectName: "consensusAdvanced"; width: 28; text: "⋯"; enabled: true; tip: "Nätverksverktyg"; Accessible.name: tip; onClicked: advancedMenu.open() }
        }
        Rule { property string uiColorScope: "ui.widget.GGConsensusDashboard.Rule.12"; anchors.bottom: parent.bottom }
    }
    Item {
        objectName: "consensusMainViewport"; x: 0; y: toolbar.height; width: root.mainWidth; height: Math.max(0, root.height - y); clip: true
        NetworkWorkspaceLayout { property string uiColorScope: "ui.widget.GGConsensusDashboard.NetworkWorkspaceLayout.13";
        id:mainScroll;objectName:"consensusMainScroll";prefix:"consensus"
        anchors.fill:parent
        summaryPanel: Column {width:(parent ? parent.width : 0);spacing:4;Column { width: (parent ? parent.width : 0); spacing: 7
                    Label { colorKey: "ui.GGConsensusDashboard.5"; width: (parent ? parent.width : 0); text: "CometBFT · fyra separata validatorprocesser · en dator · endast testmedel"; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10; wrapMode: Text.NoWrap; elide: Text.ElideRight }
                    Label { colorKey: "ui.GGConsensusDashboard.6"; objectName: "consensusOperationNotice"; width: (parent ? parent.width : 0); visible: root.busy || root.approvalPending || root.readFailed || root.consensus.state === "NO_QUORUM" || !!root.operation.error || !!root.consensus.error || (root.nodeOwned && !root.proofReady); color: root.readFailed || root.operation.error || root.consensus.error ? RuntimeTheme.GGTheme.negative : RuntimeTheme.GGTheme.accent; text: root.readFailed ? "Läsfel. Äldre avläsningar kan visas; överföringar är blockerade." : root.consensus.state === "NO_QUORUM" ? "Färre än tre verifierade validatorer. Ny finalisering väntar tills quorum återställts." : root.operation.error || root.consensus.error || (root.approvalPending ? "Väntar på godkännande i chatten." : root.busy ? "Arbetar · " + String(root.operation.name || "") : "Verifierat tillståndsbevis saknas; överföringar är blockerade."); font.pixelSize: 10; wrapMode: Text.NoWrap; elide: Text.ElideRight }
                    Label { colorKey: "ui.GGConsensusDashboard.7"; width: (parent ? parent.width : 0); visible: root.unresolved; text: "En inskickad överföring saknar slutligt utfall. Uppdatera för kvitto; betalningen skickas inte om automatiskt."; color: RuntimeTheme.GGTheme.accent; font.pixelSize: 10; wrapMode: Text.NoWrap; elide: Text.ElideRight }
                    Row { width: (parent ? parent.width : 0); visible: root.stopped && root.consensus.available === false; spacing: 8
                        Action { property string uiColorScope: "ui.control.GGConsensusDashboard.9"; objectName: "consensusInstallHelp"; text: "Installationshjälp"; onClicked: setupHelp.open() }
                        Label { colorKey: "ui.GGConsensusDashboard.8"; width: Math.max(0, (parent ? parent.width : 0) - 160); height: 28; text: "Den lokala CometBFT-motorn saknas."; font.pixelSize: 10; color: RuntimeTheme.GGTheme.dim; wrapMode: Text.NoWrap; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter }
                    }
                } Grid { id: metrics; objectName: "consensusMetrics"; width: (parent ? parent.width : 0); columns: width >= 500 ? 4 : 2; columnSpacing: 14; rowSpacing: 10
                    Repeater { model: [
                        { title: "VERIFIERADE NODER", value: root.nodeOwned ? root.onlineCount + " / 4" : "—", detail: "fyra processer · en dator" },
                        { title: "QUORUM", value: root.nodeOwned ? "3 av 4" : "—", detail: root.quorumReady ? "signaturer kan samlas" : "väntar på validatorer" },
                        { title: "TILLSTÅNDSHÖJD", value: root.present(root.consensus.state_height), detail: root.proofReady ? "kontrollerad app-hash" : "ej verifierat" },
                        { title: "CERTIFIKATHÖJD", value: root.present(root.proof.certificate_height), detail: root.proofReady ? "verifierat BFT-certifikat" : "certifikat saknas" }
                    ]
                        Column { required property var modelData; required property int index; objectName: "consensusMetric"; width: (metrics.width - (metrics.columns - 1) * 14) / metrics.columns; height: 45; spacing: 2
                            Label { colorKey: "ui.GGConsensusDashboard.9"; width: (parent ? parent.width : 0); text: modelData.title; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 9 }
                            Label { colorKey: "ui.GGConsensusDashboard.10"; width: (parent ? parent.width : 0); text: modelData.value; color: RuntimeTheme.GGTheme.bright; font.pixelSize: 18; font.bold: true; Rectangle { x:-5;y:-13;width:1;height:44;color:RuntimeTheme.GGTheme.edge;visible:parent.parent.index>0 } }
                            Label { colorKey: "ui.GGConsensusDashboard.11"; width: (parent ? parent.width : 0); text: modelData.detail; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 9 }
                        }
                    }
                }}
        measurementPanel: Column { width: (parent ? parent.width : 0); spacing: 6
                    Head { property string uiColorScope: "ui.widget.GGConsensusDashboard.Head.15"; title: "UPPMÄTT TID"; detail: "ms · " + root.measurements.length + " observationer" }
                    Item { id: chart; objectName: "consensusMeasurements"; width: (parent ? parent.width : 0); height: Math.max(28, (parent ? parent.height : 0) - 22)
                        readonly property real ceiling: Math.max(1, Math.max.apply(null, root.measurements.map(function(m) { return m.elapsed_ms })))
                        readonly property real plotWidth: Math.max(0, width - 38)
                        readonly property real plotHeight: height - 16
                        Repeater { model: root.measurements.length ? 3 : 0
                            Item { required property int index; width: (parent ? parent.width : 0); height: 1; y: index * chart.plotHeight / 2
                                Rectangle { width: chart.plotWidth; height: 1; color: RuntimeTheme.GGTheme.line; opacity: .6 }
                                Label { colorKey: "ui.GGConsensusDashboard.12"; x: chart.plotWidth + 6; y: -5; width: 32; text: (chart.ceiling * (1 - index / 2)).toFixed(chart.ceiling < 10 ? 1 : 0); font.pixelSize: 9; color: RuntimeTheme.GGTheme.dim; horizontalAlignment: Text.AlignRight }
                            }
                        }
                        Row { y: 1; width: chart.plotWidth; height: chart.plotHeight - 1; spacing: 3
                            Repeater { model: root.measurements
                                Item { id: sample; required property var modelData; objectName: "consensusMeasurementBar"; width: Math.max(1, (chart.plotWidth - Math.max(0, root.measurements.length - 1) * 3) / Math.max(1, root.measurements.length)); height: (parent ? parent.height : 0)
                                    Rectangle { anchors.bottom: parent.bottom; width: (parent ? parent.width : 0); height: Math.max(1, (parent ? parent.height : 0) * sample.modelData.elapsed_ms / chart.ceiling); color: root.sampleColor(sample.modelData);GGColorTarget{colorKey:"ui.chart.consensus."+root.sampleSeries(sample.modelData)} }
                                    HoverHandler { id: sampleHover }
                                    TapHandler { onTapped:if(consensusRelations.selectMeasurement(sample.modelData))mainScroll.chartPage=1 }
                                    ToolTip.visible: sampleHover.hovered; ToolTip.delay: 400; ToolTip.text: String(modelData.operation) + " · " + modelData.elapsed_ms.toFixed(2) + " ms\n" + root.timeText(modelData.observed_at) + " · " + root.stateText(modelData.state)
                                }
                            }
                        }
                        Row { anchors.bottom: parent.bottom; spacing: 10; visible: root.measurements.length > 0
                            Repeater { model: [{name: "Överföring",series:"transfer",color:root.sampleColor({operation:"transfer"})}, {name: "Verifiering",series:"verify",color:root.sampleColor({operation:"verify"})}, {name: "Övrigt",series:"other",color:root.sampleColor({})}, {name: "Fel",series:"error",color:root.sampleColor({state:"FAIL"})}]
                                Row { required property var modelData; spacing: 4
                                    Rectangle { y: 3; width: 5; height: 5; color: modelData.color;GGColorTarget{colorKey:"ui.chart.consensus."+modelData.series} }
                                    Label { colorKey: "ui.chartlabel.consensus."+modelData.series; text: modelData.name; font.pixelSize: 8; color: RuntimeTheme.GGTheme.dim }
                                }
                            }
                        }
                        Label { colorKey: "ui.GGConsensusDashboard.14"; anchors.centerIn: parent; visible: !root.measurements.length; text: "Inga uppmätta operationer ännu."; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10 }
                    }
                }
        relationsPanel: BlockRelationsGraph { property string uiColorScope: "ui.widget.GGConsensusDashboard.BlockRelationsGraph.16";id:consensusRelations;graph:root.consensus.block_graph || ({});measurements:root.measurements;surfaceHost:root.surfaceHost}
        accountsPanel:Item {id:consensusBooks;property int bookPage:0;objectName:"consensusBooks"
            Item {width:parent.width;height:20
                Label { colorKey: "ui.GGConsensusDashboard.15";y:3;width:parent.width-95;text:consensusBooks.bookPage===0?"TESTKONTON · GG-NET-TEST":"VALIDATORER · LOKALT P2P";color:RuntimeTheme.GGTheme.muted;font.pixelSize:9}
                Action { property string uiColorScope: "ui.control.GGConsensusDashboard.10";objectName:"consensusValidatorsTab";anchors.right:parent.right;height:20;width:90;text:consensusBooks.bookPage===0?"Validatorer":"Konton";flat:true;font.pixelSize:9;onClicked:consensusBooks.bookPage=1-consensusBooks.bookPage}
                Rule { property string uiColorScope: "ui.widget.GGConsensusDashboard.Rule.18";anchors.bottom:parent.bottom}
            }
            Item {y:23;width:parent.width;height:parent.height-y;visible:consensusBooks.bookPage===0
                Item {width:parent.width;height:16
                    Label { colorKey: "ui.GGConsensusDashboard.16";text:"#";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim}
                    Label { colorKey: "ui.GGConsensusDashboard.17";x:18;width:parent.width*.39-18;text:"ADRESS";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim}
                    Label { colorKey: "ui.GGConsensusDashboard.18";x:parent.width*.45;width:parent.width*.17;text:"KONTO";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim}
                    Label { colorKey: "ui.GGConsensusDashboard.19";x:parent.width*.62;width:parent.width*.38;text:"GG-NET-TEST";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim;horizontalAlignment:Text.AlignRight}
                }
                ListView {objectName:"consensusAccountsList";y:16;width:parent.width;height:Math.max(0,parent.height-y);clip:true;model:root.accounts;boundsBehavior:Flickable.StopAtBounds;ScrollBar.vertical:ScrollBar {}
                    delegate:Item {id:account;required property var modelData;required property int index;objectName:"consensusAccountRow";width:ListView.view.width;height:25
                        Label { colorKey: "ui.GGConsensusDashboard.20";y:5;width:16;text:index+1;font.pixelSize:9;color:RuntimeTheme.GGTheme.dim}
                        Label { colorKey: "ui.type.account.identity";x:18;y:5;width:parent.width*.39-20;text:root.short(modelData.address);font.pixelSize:9;color:RuntimeTheme.GGTheme.muted}
                        CopyAction { property string uiColorScope: "ui.control.GGConsensusDashboard.11";objectName:"consensusCopyAccount";x:parent.width*.39-1;y:2;width:18;height:20;value:String(account.modelData.address||"");viewport:mainScroll}
                        Label { colorKey: "ui.type.account.identity";x:parent.width*.45;y:5;width:parent.width*.17;text:"Konto "+(index+1);font.pixelSize:9}
                        Label { colorKey: "ui.GGConsensusDashboard.23";objectName:"consensusQuantity";x:parent.width*.62;y:5;width:parent.width*.38;text:root.present(modelData.quantity);color:RuntimeTheme.GGTheme.bright;font.pixelSize:9;horizontalAlignment:Text.AlignRight;Accessible.name:"Konto "+(index+1)+": "+text+" GG-NET-TEST"}
                        Rule { property string uiColorScope: "ui.widget.GGConsensusDashboard.Rule.20";anchors.bottom:parent.bottom;opacity:.6}
                    }
                }
            }
            Item {y:23;width:parent.width;height:parent.height-y;visible:consensusBooks.bookPage===1
                Item {width:parent.width;height:16
                    Label { colorKey: "ui.GGConsensusDashboard.24";width:parent.width*.36;text:"NOD / IDENTITET";color:RuntimeTheme.GGTheme.dim;font.pixelSize:8}
                    Label { colorKey: "ui.GGConsensusDashboard.25";x:parent.width*.38;width:parent.width*.12;text:"H";color:RuntimeTheme.GGTheme.dim;font.pixelSize:8}
                    Label { colorKey: "ui.GGConsensusDashboard.26";x:parent.width*.52;width:parent.width*.15;text:"PEERS";color:RuntimeTheme.GGTheme.dim;font.pixelSize:8}
                }
                ListView {objectName:"consensusValidatorsList";y:16;width:parent.width;height:Math.max(0,parent.height-y);clip:true;model:root.validators;boundsBehavior:Flickable.StopAtBounds;ScrollBar.vertical:ScrollBar {}
                    delegate:Item {id:validator;required property var modelData;required property int index;objectName:"consensusValidatorRow";width:ListView.view.width;height:27
                        Rectangle {x:0;y:11;width:5;height:5;radius:3;color:modelData.alive===true?modelData.identity_verified===true?RuntimeTheme.GGTheme.positive:RuntimeTheme.GGTheme.accent:RuntimeTheme.GGTheme.dim}
                        Label { colorKey: "ui.GGConsensusDashboard.27";x:11;y:6;width:parent.width*.36-13;text:"V"+(index+1)+" · "+root.short(modelData.public_key||modelData.node_id);font.pixelSize:9}
                        Label { colorKey: "ui.GGConsensusDashboard.28";x:parent.width*.38;y:6;width:parent.width*.12;text:root.present(modelData.height);font.pixelSize:9}
                        Label { colorKey: "ui.GGConsensusDashboard.29";x:parent.width*.52;y:6;width:parent.width*.15;text:root.present(modelData.peers);font.pixelSize:9}
                        Action { property string uiColorScope: "ui.control.GGConsensusDashboard.12";objectName:modelData.alive===true?"consensusStopNode":"consensusRestartNode";property int validatorIndex:validator.index;anchors.right:parent.right;y:3;width:Math.min(92,parent.width*.29);height:21;text:modelData.alive===true?"Pausa":"Starta om";font.pixelSize:9;enabled:root.canAct&&root.nodeOwned;tip:modelData.alive===true?"Stoppa endast denna validatorprocess":"Starta samma validator och återhämta dess tillstånd";onClicked:root.run(validator.modelData.alive===true?"consensus_stop_node":"consensus_restart_node",{index:validator.index})}
                        Rule { property string uiColorScope: "ui.widget.GGConsensusDashboard.Rule.22";anchors.bottom:parent.bottom;opacity:.6}
                    }
                }
            }
        }
        transferPanel: Column {height:(parent ? parent.height : 0); width: (parent ? parent.width : 0); spacing: 4
                    Head { property string uiColorScope: "ui.widget.GGConsensusDashboard.Head.23"; title: "ÖVERFÖRING"; detail: "endast GG-NET-TEST" }
                    Grid { id: transferForm; objectName: "consensusTransferForm"; width: (parent ? parent.width : 0); columns: width >= 540 ? 4 : 2; columnSpacing: 6; rowSpacing: 5
                        Column { width: (transferForm.width - (transferForm.columns - 1) * 8) / transferForm.columns; spacing: 2
                            Label { colorKey: "ui.GGConsensusDashboard.30"; text: "Från"; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10 }
                            CryptoPick { property string uiColorScope: "ui.control.GGConsensusDashboard.13"; id: sender; objectName: "consensusSender"; width: (parent ? parent.width : 0); height: 24; model: root.accountChoices; textRole: "name"; currentIndex: root.hasReview ? root.reviewedSenderIndex : root.senderIndex; enabled: root.editable; Accessible.name: "Avsändande testkonto"; onActivated: root.senderIndex = currentIndex }
                        }
                        Column { width: (transferForm.width - (transferForm.columns - 1) * 8) / transferForm.columns; spacing: 2
                            Label { colorKey: "ui.GGConsensusDashboard.31"; text: "Till"; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10 }
                            CryptoPick { property string uiColorScope: "ui.control.GGConsensusDashboard.14"; id: recipient; objectName: "consensusRecipient"; width: (parent ? parent.width : 0); height: 24; model: root.accountChoices; textRole: "name"; currentIndex: root.hasReview ? root.reviewedRecipientIndex : root.recipientIndex; enabled: root.editable; Accessible.name: "Mottagande testkonto"; onActivated: root.recipientIndex = currentIndex }
                        }
                        Column { width: (transferForm.width - (transferForm.columns - 1) * 8) / transferForm.columns; spacing: 2
                            Label { colorKey: "ui.GGConsensusDashboard.32"; text: "Belopp"; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10 }
                            CryptoField { property string uiColorScope: "ui.widget.GGConsensusDashboard.CryptoField.26"; id: amount; objectName: "consensusAmount"; width: (parent ? parent.width : 0); height: 24; text: "1"; enabled: root.editable; Accessible.name: "Exakt belopp GG-NET-TEST" }
                        }
                        Item { width: (transferForm.width - (transferForm.columns - 1) * 8) / transferForm.columns; height: 45
                            Action { property string uiColorScope: "ui.control.GGConsensusDashboard.15"; objectName: "consensusPrepare"; y: 17; width: (parent ? parent.width : 0); text: "Förhandsgranska"; enabled: root.canPrepare; onClicked: root.prepare() }
                        }
                    }
                    Label { colorKey: "ui.GGConsensusDashboard.33"; width: (parent ? parent.width : 0); visible: root.hasReview; text: "Granskningen är låst. Avbryt för att ändra uppgifterna."; color: RuntimeTheme.GGTheme.accent; font.pixelSize: 10; wrapMode:Text.NoWrap;elide:Text.ElideRight;ToolTip.visible:infoHover3.hovered;ToolTip.text:text;HoverHandler{id:infoHover3} }
                    Label { colorKey: "ui.GGConsensusDashboard.34"; width: (parent ? parent.width : 0); visible: !root.hasReview; text: "Fast testutbud 1 000 000 · ingen gasavgift i denna native-testhuvudbok."; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 9; wrapMode:Text.NoWrap;elide:Text.ElideRight;ToolTip.visible:infoHover4.hovered;ToolTip.text:text;HoverHandler{id:infoHover4} }
                    
                }
        historyPanel:Item {
            Head { property string uiColorScope: "ui.widget.GGConsensusDashboard.Head.28";title:"SENASTE ÖVERFÖRINGAR";detail:root.transactions.length+" st"}
            Item {y:19;width:parent.width;height:16
                Label { colorKey: "ui.GGConsensusDashboard.35";text:"HASH";width:parent.width*.27;font.pixelSize:8;color:RuntimeTheme.GGTheme.dim}
                Label { colorKey: "ui.GGConsensusDashboard.36";x:parent.width*.28;width:parent.width*.24;text:"BELOPP";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim;horizontalAlignment:Text.AlignRight}
                Label { colorKey: "ui.GGConsensusDashboard.37";x:parent.width*.54;width:parent.width*.10;text:"H";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim;horizontalAlignment:Text.AlignRight}
                Label { colorKey: "ui.GGConsensusDashboard.38";x:parent.width*.65;width:parent.width*.10;text:"CERT";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim;horizontalAlignment:Text.AlignRight}
                Label { colorKey: "ui.GGConsensusDashboard.39";x:parent.width*.79;width:parent.width*.21;text:"STATUS";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim}
            }
            ListView {id:receiptList;objectName:"consensusTransactionsList";y:35;width:parent.width;height:Math.max(0,parent.height-y);clip:true;model:root.transactions;boundsBehavior:Flickable.StopAtBounds;ScrollBar.vertical:ScrollBar {}
                delegate:Item {id:receipt;required property var modelData;objectName:"consensusTransactionRow";width:ListView.view.width;height:25
                    Label { colorKey: "ui.GGConsensusDashboard.40";y:5;width:parent.width*.27-18;text:root.short(modelData.hash);color:RuntimeTheme.GGTheme.muted;font.pixelSize:9}
                    CopyAction { property string uiColorScope: "ui.control.GGConsensusDashboard.16";x:parent.width*.27-19;y:2;width:18;height:20;value:String(receipt.modelData.hash||"");viewport:mainScroll}
                    Label { colorKey: "ui.GGConsensusDashboard.41";x:parent.width*.28;y:5;width:parent.width*.24;text:root.present(modelData.amount);horizontalAlignment:Text.AlignRight;font.pixelSize:9}
                    Label { colorKey: "ui.GGConsensusDashboard.42";x:parent.width*.54;y:5;width:parent.width*.10;text:root.present(modelData.height);horizontalAlignment:Text.AlignRight;font.pixelSize:9;color:RuntimeTheme.GGTheme.dim}
                    Label { colorKey: "ui.GGConsensusDashboard.43";x:parent.width*.65;y:5;width:parent.width*.10;text:root.present(modelData.certificate_height);horizontalAlignment:Text.AlignRight;font.pixelSize:9;color:RuntimeTheme.GGTheme.dim}
                    Rectangle {x:parent.width*.79;y:9;width:5;height:5;radius:3;color:root.statusColor(receipt.modelData.state)}
                    Label { colorKey: "ui.GGConsensusDashboard.44";x:parent.width*.79+9;y:5;width:parent.width*.21-9;text:root.stateText(modelData.state);font.pixelSize:9;color:root.statusColor(modelData.state)}
                    HoverHandler {id:receiptHover}
                    ToolTip.visible:receiptHover.hovered;ToolTip.delay:400;ToolTip.text:root.accountName(modelData.sender)+" → "+root.accountName(modelData.recipient)+" · "+root.present(modelData.amount)+" GG-NET-TEST"
                    Rule { property string uiColorScope: "ui.widget.GGConsensusDashboard.Rule.30";anchors.bottom:parent.bottom;opacity:.6}
                }
            }
            Label { colorKey: "ui.GGConsensusDashboard.45";anchors.centerIn:receiptList;width:parent.width;visible:!root.transactions.length;text:"Inga överföringar i sessionen";color:RuntimeTheme.GGTheme.dim;font.pixelSize:10;horizontalAlignment:Text.AlignHCenter}
        }
    }
    }

    Component { id: telemetryComponent
        Item { objectName: "consensusTelemetry"
            Rectangle { width: 1; height: (parent ? parent.height : 0); color: RuntimeTheme.GGTheme.line; visible: root.railVisible }
            NetworkRailLayout { property string uiColorScope: "ui.widget.GGConsensusDashboard.NetworkRailLayout.31";
        id:telemetryScroll;objectName:"consensusTelemetryScroll";prefix:"consensus"
        x:12;y:6;width:Math.max(0,(parent ? parent.width : 0)-24);height:Math.max(0,(parent ? parent.height : 0)-12)
        titles:["NÄTVERK & MODELL", "CERTIFIKAT & TILLSTÅND", "LÄTT KLIENT · WEBB", "RESURSER", "FUNKTIONSTEST", "PRESTANDATEST"]
        sections:[Column { width: (parent ? parent.width : 0); spacing: 0
                        Head { property string uiColorScope: "ui.widget.GGConsensusDashboard.Head.32"; title: "NÄTVERK & MODELL" }
                        Fact { property string uiColorScope: "ui.widget.GGConsensusDashboard.Fact.33"; name: "Status"; value: root.stateLabel; valueColor: root.running ? RuntimeTheme.GGTheme.positive : root.stopped ? RuntimeTheme.GGTheme.dim : RuntimeTheme.GGTheme.accent }
                        Fact { property string uiColorScope: "ui.widget.GGConsensusDashboard.Fact.34"; name: "Motor"; value: String(root.consensus.engine || "CometBFT") }
                        Fact { property string uiColorScope: "ui.widget.GGConsensusDashboard.Fact.35"; name: "Validatorer"; value: root.nodeOwned ? root.onlineCount + " / 4 verifierade" : "Ej startade" }
                        Fact { property string uiColorScope: "ui.widget.GGConsensusDashboard.Fact.36"; name: "Modell / maskiner"; value: "Fasta noder · en dator" }
                        Fact { property string uiColorScope: "ui.widget.GGConsensusDashboard.Fact.37"; name: "Bindning"; value: root.nodeOwned ? "127.0.0.1 · lokalt" : "—" }
                        Fact { property string uiColorScope: "ui.widget.GGConsensusDashboard.Fact.38"; name: "Nätverks-ID"; value: root.short(root.consensus.chain_id) }
                        Label { colorKey: "ui.GGConsensusDashboard.46"; visible:false; width: (parent ? parent.width : 0); topPadding: 8; text: "Fyra separata processer kör riktig CometBFT-konsensus. Lokal testmiljö med kända validatorer; inget publikt GG-mainnet."; font.pixelSize: 10; color: RuntimeTheme.GGTheme.dim; wrapMode:Text.NoWrap;elide:Text.ElideRight;ToolTip.visible:infoHover6.hovered;ToolTip.text:text;HoverHandler{id:infoHover6} }
                    },
Column { width: (parent ? parent.width : 0); spacing: 0
                        Head { property string uiColorScope: "ui.widget.GGConsensusDashboard.Head.39"; title: "CERTIFIKAT & TILLSTÅND" }
                        Fact { property string uiColorScope: "ui.widget.GGConsensusDashboard.Fact.40"; name: "BFT-signaturer"; value: root.proofReady ? "Verifierade · minst 3 av 4" : "Ej verifierade"; valueColor: root.proofReady ? RuntimeTheme.GGTheme.positive : RuntimeTheme.GGTheme.accent }
                        Fact { property string uiColorScope: "ui.widget.GGConsensusDashboard.Fact.41"; name: "Transaktionsbevis"; value: root.proof.transaction_inclusion_verified === true ? "Kontrollerat" : "Ej begärt"; valueColor: root.proof.transaction_inclusion_verified === true ? RuntimeTheme.GGTheme.positive : RuntimeTheme.GGTheme.dim }
                        Fact { property string uiColorScope: "ui.widget.GGConsensusDashboard.Fact.42"; name: "Exekveringsutfall"; value: root.proof.execution_status_verified === true ? "Kontrollerat" : "Ej begärt"; valueColor: root.proof.execution_status_verified === true ? RuntimeTheme.GGTheme.positive : RuntimeTheme.GGTheme.dim }
                        Row { width: (parent ? parent.width : 0); height: 24
                            Label { colorKey: "ui.GGConsensusDashboard.47"; width: (parent ? parent.width : 0) - 28; height: 28; verticalAlignment: Text.AlignVCenter; text: "Tillståndsrot · " + root.short(root.proof.state_root); color: RuntimeTheme.GGTheme.muted; font.pixelSize: 10 }
                            CopyAction { property string uiColorScope: "ui.control.GGConsensusDashboard.17"; objectName: "consensusCopyStateRoot"; value: String(root.proof.state_root || ""); viewport: telemetryScroll }
                        }
                        Label { colorKey: "ui.GGConsensusDashboard.48"; visible:false; width: (parent ? parent.width : 0); text: "App-tillståndet vid H verifieras mot certifikatet vid H+1. Merklebevis visar kontomedlemskap; inget SNARK-bevis för godtycklig kod."; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10; wrapMode:Text.NoWrap;elide:Text.ElideRight;ToolTip.visible:infoHover7.hovered;ToolTip.text:text;HoverHandler{id:infoHover7} }
                    },
Column { width: (parent ? parent.width : 0); spacing: 2
                        Head { property string uiColorScope: "ui.widget.GGConsensusDashboard.Head.44"; title: "LÄTT KLIENT · WEBB"; detail: root.webNode.state === "RUNNING" ? "lokal verifierare" : "stoppad" }
                        Label { colorKey: "ui.GGConsensusDashboard.49"; visible:false; width: (parent ? parent.width : 0); text: "Verifiera en certifierad saldobild i webbläsaren med samma kryptografiska kontroller. Sessionens validatorer är förankrade av GG. Paketet innehåller bara offentliga uppgifter."; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10; wrapMode:Text.NoWrap;elide:Text.ElideRight;ToolTip.visible:infoHover8.hovered;ToolTip.text:text;HoverHandler{id:infoHover8} }
                        Flow { width: (parent ? parent.width : 0); spacing: 6
                            Action { property string uiColorScope: "ui.control.GGConsensusDashboard.18"; objectName: "consensusExportProof"; text: "Bevis"; enabled: root.canAct && root.running; onClicked: root.run("consensus_export_proof", { account: root.senderIndex }) }
                            Action { property string uiColorScope: "ui.control.GGConsensusDashboard.19"; objectName: "consensusCopyProof"; text: "Kopiera"; enabled: root.canAct && root.sampleReady; onClicked: root.copySample() }
                            Action { property string uiColorScope: "ui.control.GGConsensusDashboard.20"; objectName: "consensusStartWeb"; text: "Starta webb"; enabled: root.canAct && root.running && root.webNode.state !== "RUNNING"; onClicked: root.run("consensus_start_web", {}) }
                            Action { property string uiColorScope: "ui.control.GGConsensusDashboard.21"; objectName: "consensusOpenWeb"; text: "Öppna"; enabled: root.canAct && root.webNode.state === "RUNNING" && root.webNode.pinned_chain_id === root.consensus.chain_id; onClicked: root.openWeb() }
                            Action { property string uiColorScope: "ui.control.GGConsensusDashboard.22"; objectName: "consensusStopWeb"; text: "Stoppa webb"; enabled: root.canAct && root.webNode.state === "RUNNING"; onClicked: root.run("consensus_stop_web", {}) }
                        }
                        Label { colorKey: "ui.GGConsensusDashboard.50"; visible:false; width: (parent ? parent.width : 0); text: root.sampleReady ? "Bevisets tillståndshöjd: " + root.publicSample.state.height + ". Ett historiskt saldo kan vara korrekt utan att vara aktuellt." : "Förbered och kopiera ett offentligt bevis, öppna webbvy och klistra in det där."; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 9; wrapMode:Text.NoWrap;elide:Text.ElideRight;ToolTip.visible:infoHover9.hovered;ToolTip.text:text;HoverHandler{id:infoHover9} }
                    },
Column { width: (parent ? parent.width : 0); spacing: 2
                        Head { property string uiColorScope: "ui.widget.GGConsensusDashboard.Head.50"; title: "RESURSER"; detail: "uppmätta processvärden" }
                        Fact { property string uiColorScope: "ui.widget.GGConsensusDashboard.Fact.51"; name: "Privat minne"; value: root.resourceSummary.bytes === null ? "Ej uppmätt" : (root.resourceSummary.bytes / 1048576).toFixed(1) + " MiB" }
                        Fact { property string uiColorScope: "ui.widget.GGConsensusDashboard.Fact.52"; name: "CPU-tid"; value: root.resourceSummary.cpu === null ? "Ej uppmätt" : root.resourceSummary.cpu.toFixed(2) + " s" }
                        Label { colorKey: "ui.GGConsensusDashboard.51"; visible:false; width: (parent ? parent.width : 0); text: "Minne: " + root.resourceSummary.memory_samples + "/4 avläsningar · CPU: " + root.resourceSummary.cpu_samples + "/4. CPU-värdet är ackumulerad processtid."; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 9; wrapMode:Text.NoWrap;elide:Text.ElideRight;ToolTip.visible:infoHover10.hovered;ToolTip.text:text;HoverHandler{id:infoHover10} }
                    },
Column { width: (parent ? parent.width : 0); spacing: 2
                        Item {width:parent.width;height:22
                            Label { colorKey: "ui.GGConsensusDashboard.52";y:5;width:parent.width-132;text:"FUNKTIONSTEST";font.pixelSize:9;color:RuntimeTheme.GGTheme.muted}
                            Action { property string uiColorScope: "ui.control.GGConsensusDashboard.23";objectName:"consensusSelfTest";anchors.right:parent.right;width:128;height:22;text:"Testa nodfel";tip:"Kontrollera överföringar och återhämtning efter nodfel";enabled:root.canAct&&root.running&&root.onlineCount===4&&!root.hasReview&&!root.unresolved;onClicked:root.run("consensus_self_test",{})}
                        }
                        Label { colorKey: "ui.GGConsensusDashboard.53"; visible:false; width: (parent ? parent.width : 0); text: "Provar testhuvudbokens överföringar och återhämtning. Bara lokala testmedel används."; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10; wrapMode:Text.NoWrap;elide:Text.ElideRight;ToolTip.visible:infoHover11.hovered;ToolTip.text:text;HoverHandler{id:infoHover11} }
                        Repeater { model: root.lastTest.checks || []
                            Item { required property var modelData; objectName: "consensusSelfTestCheck"; width: (parent ? parent.width : 0); height: 14
                                Rectangle { y: 5; width: 6; height: 6; radius: 3; color: root.statusColor(modelData.state) }
                                Label { colorKey: "ui.GGConsensusDashboard.54"; id: checkText; x: 14; width: (parent ? parent.width : 0) - x; text: String(modelData.name || "Kontroll") + " · " + root.stateText(modelData.state); color: root.statusColor(modelData.state); font.pixelSize: 10; wrapMode:Text.NoWrap;elide:Text.ElideRight;ToolTip.visible:infoHover12.hovered;ToolTip.text:text;HoverHandler{id:infoHover12} }
                            }
                        }
                    },
Column { width: (parent ? parent.width : 0); spacing: 2
                        Item {width:parent.width;height:22
                            Label { colorKey: "ui.GGConsensusDashboard.55";y:5;width:parent.width-132;text:"PRESTANDATEST";font.pixelSize:9;color:RuntimeTheme.GGTheme.muted}
                            Action { property string uiColorScope: "ui.control.GGConsensusDashboard.24";objectName:"consensusBenchmark";anchors.right:parent.right;width:128;height:22;text:"Mät 32 överföringar";font.pixelSize:9;enabled:root.canAct&&root.running&&root.onlineCount===4&&!root.hasReview&&!root.unresolved;onClicked:root.run("consensus_benchmark",{count:32})}
                        }
                        Fact { property string uiColorScope: "ui.widget.GGConsensusDashboard.Fact.55"; objectName: "consensusBenchmarkTps"; name: "Slutförda / s"; value: root.benchmark.state === "PASS" && typeof root.benchmark.tps === "number" && isFinite(root.benchmark.tps) ? root.benchmark.tps.toFixed(2) : "Ej uppmätt" }
                        Fact { property string uiColorScope: "ui.widget.GGConsensusDashboard.Fact.56"; name: "Median / p95"; value: root.benchmark.state === "PASS" ? root.present(root.benchmark.p50_ms) + " / " + root.present(root.benchmark.p95_ms) + " ms" : "Ej uppmätt" }
                        Fact { property string uiColorScope: "ui.widget.GGConsensusDashboard.Fact.57"; name: "p99"; value: root.benchmark.state === "PASS" ? root.present(root.benchmark.p99_ms) + " ms" : "Ej uppmätt" }
                        Label { colorKey: "ui.GGConsensusDashboard.56"; visible:false; width: (parent ? parent.width : 0); text: "Avgränsad lokal körning med fyra fasta validatorer på en dator. Siffran är inte global nätverkskapacitet."; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10; wrapMode:Text.NoWrap;elide:Text.ElideRight;ToolTip.visible:infoHover13.hovered;ToolTip.text:text;HoverHandler{id:infoHover13} }
                    }]
        eventsPanel:Column { width: (parent ? parent.width : 0); spacing: 3
                        Item { width: (parent ? parent.width : 0); height: 24
                            Label { colorKey: "ui.GGConsensusDashboard.57"; y: 8; text: "HÄNDELSER"; color: RuntimeTheme.GGTheme.muted; font.pixelSize: 10 }
                            Action { property string uiColorScope: "ui.control.GGConsensusDashboard.25"; objectName: "consensusAllEvents"; anchors.right: parent.right; height: 27; text: "Visa alla"; flat: true; enabled: true; onClicked: eventsPopup.open() }
                            Rule { property string uiColorScope: "ui.widget.GGConsensusDashboard.Rule.59"; anchors.bottom: parent.bottom }
                        }
                        ListView { objectName:"consensusEventsList";width:(parent ? parent.width : 0);height:Math.max(0,(parent ? parent.height : 0)-40);clip:true;model:root.events.slice(0, 12);boundsBehavior:Flickable.StopAtBounds;ScrollBar.vertical:ScrollBar {}
 delegate:Column { required property var modelData; objectName: "consensusEventRow"; width: ListView.view.width; spacing: 5
                                Label { colorKey: "ui.GGConsensusDashboard.58"; width: (parent ? parent.width : 0); text: root.timeText(modelData.ts) + " · " + String(modelData.kind || "").replace(/_/g, " "); color: root.statusColor(modelData.kind); font.pixelSize: 9 }
                                Label { colorKey: "ui.GGConsensusDashboard.59"; width: (parent ? parent.width : 0); text: String(modelData.message || ""); color: RuntimeTheme.GGTheme.muted; font.pixelSize: 9; wrapMode: Text.NoWrap; elide: Text.ElideRight }
                            }
}
                        Label { colorKey: "ui.GGConsensusDashboard.60"; width: (parent ? parent.width : 0); visible: !root.events.length; text: "Inga validatorhändelser registrerade."; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10; wrapMode:Text.NoWrap;elide:Text.ElideRight;ToolTip.visible:infoHover14.hovered;ToolTip.text:text;HoverHandler{id:infoHover14} }
                    }
    }
        }
    }
    Loader { x: root.mainWidth; y: toolbar.height; width: root.railWidth; height: Math.max(0, root.height - y); active: root.railVisible; visible: active; sourceComponent: telemetryComponent }
    Popup { id: factsDrawer; objectName: "consensusFactsDrawer"; x: Math.max(0, root.width - width); y: toolbar.height; width: Math.min(360, root.width); height: Math.max(0, root.height - y); padding: 0; modal: true; focus: true; closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { color: RuntimeTheme.GGTheme.base; LedgerBorder { property string uiColorScope: "ui.widget.GGConsensusDashboard.LedgerBorder.60"; anchors.fill: parent; color: RuntimeTheme.GGTheme.edge; radius: 0 } }
        contentItem: Item {
            Action { property string uiColorScope: "ui.control.GGConsensusDashboard.26"; anchors.right: parent.right; anchors.rightMargin: 8; y: 2; width: 28; text: "×"; enabled: true; tip: "Stäng validatorpanelen"; Accessible.name: tip; onClicked: factsDrawer.close() }
            Loader { y: 30; width: (parent ? parent.width : 0); height: Math.max(0, (parent ? parent.height : 0) - y); active: factsDrawer.visible; sourceComponent: telemetryComponent }
        }
    }
    Menu { id: advancedMenu; objectName: "consensusAdvancedMenu"; x: Math.max(0, root.width - width - 12); y: toolbar.height; width: Math.min(260, root.width - 24)
        MenuItem { text: root.detailsVisible ? "Dölj sidopanel" : "Visa sidopanel"; onTriggered: root.toggleDetails() 
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignLeft }
}
        MenuItem { text: "Alla validatorhändelser"; onTriggered: eventsPopup.open() 
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignLeft }
}
        MenuItem { text: "GG EVM-testnät"; onTriggered: root.pageRequested("TESTNET") 
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignLeft }
}
        MenuItem { text: "Signerat lokalt labb"; onTriggered: root.pageRequested("LAB") 
        contentItem: GGControlCaption { horizontalAlignment:Text.AlignLeft }
}
        background: Rectangle { color: RuntimeTheme.GGTheme.panel; border.color: RuntimeTheme.GGTheme.edge }
    }
    Popup { id: setupHelp; objectName: "consensusSetupHelp"; x: 8; y: 52; width: Math.min(450, root.width - 16); padding: 16; modal: true; focus: true; closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { color: RuntimeTheme.GGTheme.panel; LedgerBorder { property string uiColorScope: "ui.widget.GGConsensusDashboard.LedgerBorder.62"; anchors.fill: parent; color: RuntimeTheme.GGTheme.edge; radius: 2 } }
        contentItem: Column { width: (parent ? parent.width : 0); spacing: 4
            Label { colorKey: "ui.GGConsensusDashboard.61"; width: (parent ? parent.width : 0); text: "Valfri lokal konsensusmotor"; color: RuntimeTheme.GGTheme.bright; font.pixelSize: 13 }
            Label { colorKey: "ui.GGConsensusDashboard.62"; width: (parent ? parent.width : 0); text: "CometBFT-verktyget måste installeras separat. Den här hjälpen läser bara information och gör inga nätverksanrop."; color: RuntimeTheme.GGTheme.muted; wrapMode:Text.NoWrap;elide:Text.ElideRight;ToolTip.visible:infoHover15.hovered;ToolTip.text:text;HoverHandler{id:infoHover15} }
            Label { colorKey: "ui.GGConsensusDashboard.63"; width: (parent ? parent.width : 0); text: ".venv-windows/Scripts/python.exe support/gg-consensus/install_toolchain.py"; font.pixelSize: 10; wrapMode: Text.WrapAnywhere; elide: Text.ElideNone }
            Action { property string uiColorScope: "ui.control.GGConsensusDashboard.27"; text: "Stäng"; enabled: true; onClicked: setupHelp.close() }
        }
    }
    Popup { id: eventsPopup; objectName: "consensusEventsPopup"; x: 8; y: 8; width: Math.max(0, root.width - 16); height: Math.max(0, root.height - 16); padding: 14; modal: true; focus: true; closePolicy: Popup.CloseOnEscape
        background: Rectangle { color: RuntimeTheme.GGTheme.base; LedgerBorder { property string uiColorScope: "ui.widget.GGConsensusDashboard.LedgerBorder.64"; anchors.fill: parent; color: RuntimeTheme.GGTheme.edge; radius: 2 } }
        contentItem: Item {
            Label { colorKey: "ui.GGConsensusDashboard.64"; width: (parent ? parent.width : 0) - 40; height: 28; text: "GG VALIDATORER · HÄNDELSER · " + root.events.length; color: RuntimeTheme.GGTheme.bright; verticalAlignment: Text.AlignVCenter }
            Action { property string uiColorScope: "ui.control.GGConsensusDashboard.28"; anchors.right: parent.right; width: 28; text: "×"; enabled: true; onClicked: eventsPopup.close() }
            ListView { objectName: "consensusAllEventsList"; y: 38; width: (parent ? parent.width : 0); height: Math.max(0, (parent ? parent.height : 0) - y); clip: true; spacing: 4; model: root.events; ScrollBar.vertical: ScrollBar {}
                delegate: Column { required property var modelData; width: ListView.view.width; spacing: 5
                    Label { colorKey: "ui.GGConsensusDashboard.65"; width: (parent ? parent.width : 0); text: root.timeText(modelData.ts) + " · " + String(modelData.kind || ""); color: root.statusColor(modelData.kind); font.pixelSize: 10 }
                    Label { colorKey: "ui.GGConsensusDashboard.66"; width: (parent ? parent.width : 0); text: String(modelData.message || ""); color: RuntimeTheme.GGTheme.muted; wrapMode: Text.WrapAnywhere; elide: Text.ElideNone }
                }
            }
        }
    }

    Popup {
        objectName:"consensusReviewPopup";visible:root.visible&&root.hasReview
        x:Math.max(8,(root.width-width)/2);y:Math.max(8,(root.height-height)/2)
        width:Math.min(540,root.width-16);height:Math.min(root.height-16,reviewContent.implicitHeight+24)
        padding:12;modal:true;focus:true;closePolicy:Popup.NoAutoClose
        background:Rectangle{color:RuntimeTheme.GGTheme.panel;LedgerBorder{ property string uiColorScope: "ui.widget.GGConsensusDashboard.LedgerBorder.66";anchors.fill:parent;color:RuntimeTheme.GGTheme.edge;radius:2}}
        contentItem: Column { id:reviewContent; objectName: "consensusReview"; width: (parent ? parent.width : 0); visible: root.hasReview; spacing: 4
                        Head { property string uiColorScope: "ui.widget.GGConsensusDashboard.Head.67"; title: "GRANSKA TESTÖVERFÖRING"; detail: "låst underlag" }
                        Fact { property string uiColorScope: "ui.widget.GGConsensusDashboard.Fact.68"; name: "Från"; value: root.review ? root.accountName(root.review.sender) + " · " + String(root.review.sender) : "—" }
                        Fact { property string uiColorScope: "ui.widget.GGConsensusDashboard.Fact.69"; name: "Till"; value: root.review ? root.accountName(root.review.recipient) + " · " + String(root.review.recipient) : "—" }
                        Fact { property string uiColorScope: "ui.widget.GGConsensusDashboard.Fact.70"; name: "Belopp"; value: root.review ? String(root.review.amount) + " " + String(root.review.symbol || "GG-NET-TEST") : "—"; valueColor: RuntimeTheme.GGTheme.bright }
                        Fact { property string uiColorScope: "ui.widget.GGConsensusDashboard.Fact.71"; name: "Nätverk"; value: String(root.review && root.review.chain_id || root.consensus.chain_id || "—") }
                        Fact { property string uiColorScope: "ui.widget.GGConsensusDashboard.Fact.72"; name: "Nonce"; value: root.review ? root.present(root.review.nonce) : "—" }
                        Label { colorKey: "ui.GGConsensusDashboard.67"; width: (parent ? parent.width : 0); text: "Fyra lokala validatorprocesser på en dator. Testmedel och statisk validatorlista; ingen produktionsbetalning."; color: RuntimeTheme.GGTheme.accent; font.pixelSize: 10; wrapMode: Text.WordWrap; elide: Text.ElideNone }
                        Row { spacing: 8
                            Action { property string uiColorScope: "ui.control.GGConsensusDashboard.29"; objectName: "consensusSend"; text: "Skicka på testnätet"; enabled: root.canAct && root.running && root.validReview && !root.unresolved; onClicked: root.send() }
                            Action { property string uiColorScope: "ui.control.GGConsensusDashboard.30"; objectName: "consensusCancel"; text: "Avbryt"; enabled: root.canAct && root.nodeOwned && root.hasReview; onClicked: root.run("consensus_cancel", {}) }
                        }
                    }
    }

}

