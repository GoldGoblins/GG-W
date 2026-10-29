import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

// A local EVM development node. This view never borrows a production wallet,
// invents node traffic, or changes a prepared transfer through editable fields.
Item {
    id: root
    objectName: "testnetDashboard"
    property var state: ({})
    property var liveObservation: ({})
    property var surfaceHost: null
    property bool stopRequested: false
    property string stopError: ""
    property bool sidePanelOpen: true
    property int senderIndex: 0
    property int recipientIndex: 1
    property bool externalRecipient: false
    readonly property var testnet: state.testnet || ({})
    readonly property var observed: liveObservation && (!testnet.session || !liveObservation.session || testnet.session===liveObservation.session) ? liveObservation : ({})
    readonly property string observedState: observed.state || testnet.state || ""
    readonly property var observedHeight: observed.height===undefined ? testnet.height : observed.height
    readonly property string observationError: stopError || (observed.error===undefined ? String(testnet.error||"") : String(observed.error))
    readonly property var operation: state.ui_operation || ({})
    readonly property var accounts: testnet.accounts || []
    readonly property var review: testnet.review || null
    readonly property var transactions: (testnet.transactions || []).length <= 64 ? (testnet.transactions || []) : testnet.transactions.slice(0, 64)
    readonly property var measurements: (observed.measurements || testnet.measurements || []).filter(function(m) { return typeof m.elapsed_ms === "number" && isFinite(m.elapsed_ms) && m.elapsed_ms >= 0 }).slice(-32)
    readonly property var events: (testnet.events || []).length <= 48 ? (testnet.events || []) : testnet.events.slice(0, 48)
    readonly property var lastTest: testnet.last_test || ({})
    readonly property var resourceMetrics: testnet.resource_metrics || ({})
    readonly property var resourceLimits: testnet.resource_limits || ({})
    readonly property bool busy: operation.state === "running"
    readonly property bool approvalPending: operation.state === "approval_required"
    readonly property bool canAct: !busy && !approvalPending
    readonly property bool identityReady: testnet.production === false && testnet.chain_number === 31337 && testnet.binding === "LOOPBACK_ONLY"
    readonly property bool running: observedState === "RUNNING" && identityReady
    readonly property bool readFailed: observedState === "READ_FAILED" || (observedState === "RUNNING" && !identityReady)
    readonly property bool nodeOwned: observedState === "RUNNING" || observedState === "READ_FAILED"
    readonly property bool stopped: observedState === "STOPPED"
    readonly property bool hasReview: !!review
    readonly property bool editable: canAct && running && !hasReview
    readonly property bool unresolved: testnet.unresolved === true || transactions.some(function(t) { return t.state === "PENDING" || t.state === "BROADCAST_UNKNOWN" })
    readonly property bool quotaAvailable: Number(testnet.session_transactions || 0) < Number(testnet.transaction_limit || 256)
    readonly property string recipientAddress: externalRecipient ? externalAddress.text.trim() : recipient.currentIndex >= 0 && recipient.currentIndex < accounts.length ? String(accounts[recipient.currentIndex].address) : ""
    readonly property string sourceAddress: sender.currentIndex >= 0 && sender.currentIndex < accounts.length ? String(accounts[sender.currentIndex].address) : ""
    readonly property string assetId: asset.currentIndex === 1 ? "NATIVE" : "GG-TEST"
    readonly property bool amountValid: (assetId === "NATIVE" ? /^(?:0|[1-9]\d*)(?:\.\d{1,18})?$/ : /^(?:0|[1-9]\d*)(?:\.\d{1,6})?$/).test(amount.text.trim()) && /[1-9]/.test(amount.text)
    readonly property bool recipientValid: /^0x[0-9a-fA-F]{40}$/.test(recipientAddress) && !/^0x0{40}$/i.test(recipientAddress) && recipientAddress.toLowerCase() !== sourceAddress.toLowerCase()
    readonly property bool canPrepare: editable && quotaAvailable && !unresolved && sender.currentIndex >= 0 && recipientValid && amountValid && (assetId === "NATIVE" || !!testnet.contract)
    readonly property bool dockAvailable: width >= 820
    readonly property bool railVisible: dockAvailable && sidePanelOpen
    readonly property bool detailsVisible: railVisible || factsDrawer.visible
    readonly property real railWidth: Math.max(248, Math.min(360, width * .27))
    readonly property real mainWidth: Math.max(0, width - (railVisible ? railWidth : 0))
    readonly property bool wideTable: (mainWidth - 32) / 2 >= 500
    readonly property bool compactDensity: width < 1200 || height < 760
    readonly property var accountChoices: accounts.map(function(a, i) { return { name: "Konto " + (i + 1) + " · " + root.shortAddress(a.address), address: a.address } })
    readonly property string stateLabel: running ? "Igång" : readFailed ? "Läsfel · äldre data" : stopped ? "Stoppad" : "Inväntar status"
    readonly property color rpcSeriesColor: RuntimeTheme.GGColorContext.colorFor("ui.chart.testnet.rpc", RuntimeTheme.GGTheme.muted)
    readonly property color transactionSeriesColor: RuntimeTheme.GGColorContext.colorFor("ui.chart.testnet.transaction", RuntimeTheme.GGTheme.cyan)
    readonly property color selfTestSeriesColor: RuntimeTheme.GGColorContext.colorFor("ui.chart.testnet.self_test", RuntimeTheme.GGTheme.purple)
    signal actionRequested(string name, var args)
    signal refreshRequested()
    signal pageRequested(string page)
    onDockAvailableChanged: if (dockAvailable) factsDrawer.close()

    function run(name, args) {
        if (name === "testnet_stop") { if (!nodeOwned || stopRequested) return }
        else if (!canAct) return
        else if (name === "testnet_start") { if (!stopped || testnet.available !== true) return }
        else if (!running) return
        actionRequested(name, args || {})
    }
    function prepare() { if (canPrepare) run("testnet_prepare", { sender: sender.currentIndex, recipient: recipientAddress, amount: amount.text.trim(), asset: assetId }) }
    function send() { if (running && hasReview && review.id && review.review_digest && !unresolved && quotaAvailable) run("testnet_send", { id: review.id, review_digest: review.review_digest }) }
    function toggleDetails() { if (dockAvailable) { factsDrawer.close(); sidePanelOpen = !sidePanelOpen } else if (factsDrawer.visible) factsDrawer.close(); else factsDrawer.open() }
    function shortAddress(value) { value = String(value || ""); return value.length > 20 ? value.slice(0, 8) + "…" + value.slice(-6) : value || "—" }
    function accountLabel(address) { for (var i = 0; i < accounts.length; i++) if (String(accounts[i].address).toLowerCase() === String(address).toLowerCase()) return "Konto " + (i + 1); return "Extern testadress" }
    function copyPublic(value) { value = String(value || ""); if (canAct && (/^0x[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?$/.test(value) || /^http:\/\/127\.0\.0\.1:\d+$/.test(value)) && surfaceHost && surfaceHost.tmogCopy) surfaceHost.tmogCopy(value) }
    function timeText(value) { return value ? new Date(Number(value) * 1000).toLocaleTimeString(Qt.locale(), "HH:mm:ss") : "—" }
    function stateText(value) { return ({ CONFIRMED: "Bekräftad", REVERTED: "Återställd", PENDING: "Väntar", BROADCAST_UNKNOWN: "Utfall okänt", PASS: "Godkänd", FAIL: "Underkänd" })[value] || String(value || "—") }
    function stateColor(value) { return /FAIL|ERROR|REVERTED/.test(value) ? RuntimeTheme.GGTheme.negative : /UNKNOWN|PENDING|RUNNING/.test(value) ? RuntimeTheme.GGTheme.accent : /CONFIRMED|PASS|READY|STARTED/.test(value) ? RuntimeTheme.GGTheme.positive : RuntimeTheme.GGTheme.muted }
    function measurementColor(name) { return name === "rpc" ? rpcSeriesColor : name === "transaction" ? transactionSeriesColor : name === "self_test" ? selfTestSeriesColor : RuntimeTheme.GGColorContext.colorFor("ui.chart.testnet."+name, RuntimeTheme.GGTheme.muted) }
    function measurementLabel(name) { return ({ rpc: "RPC", transaction: "Transaktion", self_test: "Funktionstest" })[name] || String(name || "Mätning") }
    function numberOrMissing(value) { return value === undefined || value === null ? "—" : String(value) }
    function metricAt(index) {
        if(index===0)return {title:"BLOCKHÖJD",value:running||readFailed?numberOrMissing(observedHeight):"—",detail:readFailed?"äldre avläsning":"lokal utvecklingskedja"}
        if(index===1)return {title:"CHAIN ID",value:numberOrMissing(testnet.chain_number),detail:"endast lokalt testnät"}
        if(index===2)return {title:"VALIDERAD NOD",value:running?"1 · lokalt":"0",detail:running?"ingen P2P-transport":"ingen verifierad nodstatus"}
        return {title:"TRANSAKTIONER",value:String(testnet.session_transactions||0)+" / "+String(testnet.transaction_limit||256),detail:"begränsning per session"}
    }

    component Label: GGText { ToolTip.visible:labelHover.hovered&&truncated;ToolTip.text:text;ToolTip.delay:400;HoverHandler{id:labelHover} color: RuntimeTheme.GGTheme.text; font.family: "monospace"; font.pixelSize: 11; textFormat: Text.PlainText; elide: Text.ElideRight }
    component Rule: Rectangle { width: (parent ? parent.width : 0); height: 1; color: RuntimeTheme.GGTheme.line }
    component TestAction: CryptoButton { height: 24; font.pixelSize: 10; enabled: root.canAct }
    component TestMenuItem: MenuItem {
        id: menuControl
        contentItem: Label { colorKey: "ui.GGTestnetDashboard.1"; text: menuControl.text; color: menuControl.enabled ? RuntimeTheme.GGTheme.text : RuntimeTheme.GGTheme.dim; verticalAlignment: Text.AlignVCenter }
        background: Rectangle { color: menuControl.highlighted ? RuntimeTheme.GGTheme.raised : "transparent" }
    }
    component SectionHead: Item {
        property string title: ""
        property string detail: ""
        width: (parent ? parent.width : 0); height: 18
        Label { colorKey: "ui.GGTestnetDashboard.2"; anchors.left: parent.left; anchors.right: sectionDetail.left; anchors.rightMargin: 8; height: (parent ? parent.height : 0) - 1; verticalAlignment: Text.AlignVCenter; text: parent.title; color: RuntimeTheme.GGTheme.muted; font.pixelSize: 10; font.letterSpacing: .5 }
        Label { colorKey: "ui.GGTestnetDashboard.3"; id: sectionDetail; anchors.right: parent.right; height: (parent ? parent.height : 0) - 1; verticalAlignment: Text.AlignVCenter; text: parent.detail; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10 }
        Rule { property string uiColorScope: "ui.widget.GGTestnetDashboard.Rule.1"; anchors.bottom: parent.bottom }
    }
    component Fact: Item {
        property string name: ""
        property string value: "—"
        property color valueColor: RuntimeTheme.GGTheme.text
        width:parent?parent.width:0;height:14
        Label { colorKey: "ui.GGTestnetDashboard.4";y:1;width:parent.width*.43-6;text:parent.name;color:RuntimeTheme.GGTheme.dim;font.pixelSize:9}
        Rectangle {x:Math.max(parent.width*.43-7,parent.width-Math.min(factValue.implicitWidth,factValue.width)-8);y:5;width:4;height:4;radius:2;color:parent.valueColor;visible:parent.name==="Status"}
        Label { colorKey: "ui.GGTestnetDashboard.5";id:factValue;y:1;x:parent.width*.43;width:parent.width-x;text:parent.value;color:parent.valueColor;horizontalAlignment:Text.AlignRight;font.pixelSize:9;wrapMode:Text.NoWrap;elide:Text.ElideRight}
        Rectangle {y:13;width:parent.width;height:1;color:RuntimeTheme.GGTheme.line;opacity:.35}
        Accessible.role:Accessible.StaticText;Accessible.name:name+": "+value
    }
    component CopyAction: TestAction {
        id: copyControl
        property string value: ""
        property Item viewport: null
        width: 24; height: 24; flat: true; quiet: true; tip: "Kopiera offentlig referens"; Accessible.name: tip; enabled: root.canAct && !!value
        contentItem: Item { LedgerGlyph { property string uiColorScope: "ui.widget.GGTestnetDashboard.LedgerGlyph.2"; anchors.centerIn: parent; width: 13; height: 13; name: "copy"; viewport: copyControl.viewport; color: copyControl.enabled ? RuntimeTheme.GGTheme.muted : RuntimeTheme.GGTheme.dim } }
        onClicked: root.copyPublic(value)
    }
    component QuotaBar: Item {
        id:quota
        property string title:""
        property var used:null
        property var limit:null
        readonly property real numericUsed:Number(used)
        readonly property real numericLimit:Number(limit)
        readonly property bool sampled:used!==null&&used!==undefined&&isFinite(numericUsed)&&numericUsed>=0
        readonly property bool available:sampled&&limit!==null&&limit!==undefined&&isFinite(numericLimit)&&numericLimit>0
        readonly property real fraction:available?Math.max(0,Math.min(1,numericUsed/numericLimit)):0
        property color barColor:RuntimeTheme.GGTheme.blue
        property string valueText:available?String(used)+" / "+String(limit):sampled?String(used)+" · gräns saknas":"Ej uppmätt"
        width:parent?parent.width:0;height:24
        Label { colorKey: "ui.GGTestnetDashboard.6";y:0;width:parent.width*.48;text:quota.title;color:RuntimeTheme.GGTheme.dim;font.pixelSize:9}
        Label { colorKey: "ui.GGTestnetDashboard.7";x:parent.width*.48;y:0;width:parent.width*.52;text:quota.sampled?quota.valueText:"Ej uppmätt";horizontalAlignment:Text.AlignRight;color:RuntimeTheme.GGTheme.muted;font.pixelSize:9}
        Rectangle {y:17;width:Math.max(0,parent.width-32);height:3;color:RuntimeTheme.GGTheme.line;Rectangle{id:meterFill;width:parent.width*quota.fraction;height:3;color:quota.barColor} GGColorTarget{target:meterFill;colorKey:"ui.meter.testnet."+quota.objectName;percentageCapable:true;fraction:quota.available?quota.fraction:NaN}}
        Label { colorKey: "ui.GGTestnetDashboard.8";anchors.right:parent.right;y:12;text:quota.available?(quota.fraction*100).toFixed(1)+" %":"—";color:RuntimeTheme.GGTheme.dim;font.pixelSize:8}
        Accessible.role:Accessible.ProgressBar;Accessible.name:title+": "+(sampled?valueText:"Ej uppmätt")
    }

    Item {
        id: toolbar; objectName: "testnetToolbar"; width: (parent ? parent.width : 0); height: root.width < 600 ? 62 : 32
        Row { x: 8; y: root.width < 600 ? 33 : 3; height: 28; spacing: 6
            TestAction { property string uiColorScope: "ui.control.GGTestnetDashboard.1"; objectName: "testnetTestnetMode"; text: root.width<600?"EVM":"GG TESTNÄT"; flat: true; checked: true; enabled: true; onClicked: root.pageRequested("TESTNET") }
            TestAction { property string uiColorScope: "ui.control.GGTestnetDashboard.2"; objectName: "testnetLabMode"; text: root.width<600?"LABB":"SIGNERAT LABB"; flat: true; enabled: true; onClicked: root.pageRequested("LAB") }
            TestAction { property string uiColorScope: "ui.control.GGTestnetDashboard.3"; objectName: "testnetValidatorMode"; text: root.width<600?"BFT":"VALIDATORER"; flat: true; enabled: true; onClicked: root.pageRequested("CONSENSUS") }
            TestAction { property string uiColorScope: "ui.control.GGTestnetDashboard.4";objectName:"testnetDagMode";text:root.width<600?"DAG":"DAGoblin";flat:true;enabled:true;tip:"Parallella signerade förslag · separat experimentlabb";onClicked:root.pageRequested("DAG")}
        }
        Row { id: toolbarActions; anchors.right: parent.right; anchors.rightMargin: 8; y: 3; height: 28; spacing: 6
            TestAction { property string uiColorScope: "ui.control.GGTestnetDashboard.5"; objectName: "testnetRefresh"; width: root.width < 1100 ? 28 : 94; text: root.width < 1100 ? "" : "Uppdatera"; tip: "Uppdatera testnodens status"; Accessible.name: tip; onClicked: root.refreshRequested()
                contentItem: Item { LedgerGlyph { property string uiColorScope: "ui.widget.GGTestnetDashboard.LedgerGlyph.8"; x: root.width < 1100 ? ((parent ? parent.width : 0) - 15) / 2 : 0; anchors.verticalCenter: parent.verticalCenter; width: 15; height: 15; name: "refresh"; color: parent.parent.enabled ? RuntimeTheme.GGTheme.text : RuntimeTheme.GGTheme.dim } Label { colorKey: "ui.GGTestnetDashboard.9"; x: 21; width: (parent ? parent.width : 0) - x; height: (parent ? parent.height : 0); visible: root.width >= 1100; text: "Uppdatera"; verticalAlignment: Text.AlignVCenter } }
            }
            TestAction { property string uiColorScope: "ui.control.GGTestnetDashboard.6"; objectName: "testnetStart"; text: "▷ Starta"; enabled: root.canAct && root.stopped && root.testnet.available === true; onClicked: root.run("testnet_start", {}) }
            TestAction { property string uiColorScope: "ui.control.GGTestnetDashboard.7"; objectName: "testnetStop"; text: root.stopRequested?"■ Stoppar…":"■ Stoppa"; enabled: root.nodeOwned && !root.stopRequested; onClicked: root.run("testnet_stop", {}) }
            TestAction { property string uiColorScope: "ui.control.GGTestnetDashboard.8"; objectName: "testnetAdvanced"; text: "⋯"; width: 28; enabled: true; tip: "Nätverksverktyg och händelser"; Accessible.name: tip; onClicked: advancedMenu.open() }
        }
        Rule { property string uiColorScope: "ui.widget.GGTestnetDashboard.Rule.12"; anchors.bottom: parent.bottom }
    }

    Item {
        objectName: "testnetMainViewport"; x: 0; y: toolbar.height; width: root.mainWidth; height: Math.max(0, root.height - y); clip: true
    NetworkWorkspaceLayout { property string uiColorScope: "ui.widget.GGTestnetDashboard.NetworkWorkspaceLayout.13";
        id:mainScroll;objectName:"testnetMainScroll";prefix:"testnet"
        anchors.fill:parent
        summaryPanel: Column {width:(parent ? parent.width : 0);spacing:4;Column { width: (parent ? parent.width : 0); spacing: 7
                Label { colorKey: "ui.GGTestnetDashboard.10"; width: (parent ? parent.width : 0); text: "Hardhat · lokal EVM · tillfälliga testkonton · ny session vid omstart"; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10; wrapMode: Text.NoWrap; elide: Text.ElideRight }
                Label { colorKey: "ui.GGTestnetDashboard.11"; objectName: "testnetOperationNotice"; width: (parent ? parent.width : 0); visible: root.busy || root.approvalPending || root.readFailed || !!root.observationError || !!root.operation.error; color: root.readFailed || root.observationError || root.operation.error ? RuntimeTheme.GGTheme.negative : RuntimeTheme.GGTheme.accent; text: root.readFailed ? "Läsningen misslyckades. Visade konton och mätvärden kan vara äldre; överföringar är blockerade." : root.operation.error || root.observationError || (root.approvalPending ? "Väntar på godkännande i chatten." : "Arbetar · " + String(root.operation.name || "")); wrapMode: Text.NoWrap; elide: Text.ElideRight }
                Row { visible: root.stopped && root.testnet.available === false; width: (parent ? parent.width : 0); spacing: 8
                    TestAction { property string uiColorScope: "ui.control.GGTestnetDashboard.9"; objectName: "testnetInstall"; text: "Installationshjälp"; enabled: root.canAct; onClicked: setupHelp.open() }
                    Label { colorKey: "ui.GGTestnetDashboard.12"; width: Math.max(0, (parent ? parent.width : 0) - 160); height: 28; verticalAlignment: Text.AlignVCenter; text: "Hardhat krävs för det lokala testnätet."; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10; wrapMode: Text.NoWrap; elide: Text.ElideRight }
                }
            } Grid { id: metrics; objectName: "testnetMetrics"; width: (parent ? parent.width : 0); columns: width >= 500 ? 4 : 2; columnSpacing: 8; rowSpacing: 4
                // Stable four slots: new observed heights update text without
                // destroying captions, handlers or palette scopes at RPC rate.
                Repeater { model: 4
                    Column { required property int index; readonly property var modelData:root.metricAt(index); objectName: "testnetMetric"; width: (metrics.width - (metrics.columns - 1) * metrics.columnSpacing) / metrics.columns; height: 45; spacing: 2
                        Label { colorKey: "ui.GGTestnetDashboard.13"; width: (parent ? parent.width : 0); text: modelData.title; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 9; font.letterSpacing: .3 }
                        Label { colorKey: "ui.GGTestnetDashboard.14"; width: (parent ? parent.width : 0); text: modelData.value; color: RuntimeTheme.GGTheme.bright; font.pixelSize: 18; font.bold: true; Rectangle { x:-5;y:-13;width:1;height:44;color:RuntimeTheme.GGTheme.edge;visible:parent.parent.index>0 } }
                        Label { colorKey: "ui.GGTestnetDashboard.15"; width: (parent ? parent.width : 0); text: modelData.detail; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 9 }
                    }
                }
            }}
        measurementPanel: Column { width: (parent ? parent.width : 0); spacing: 4
                SectionHead { property string uiColorScope: "ui.widget.GGTestnetDashboard.SectionHead.15"; title: "RPC & TRANSAKTIONSTID"; detail: "ms · " + root.measurements.length + " mätningar" + (sampleClock.hasObservation && root.running ? " · senast " + sampleClock.ageSeconds.toFixed(1) + " s" : "") }
                Item {
                    id: chart; objectName: "testnetMeasurements"; width: (parent ? parent.width : 0); height: Math.max(28, (parent ? parent.height : 0) - 24)
                    readonly property real ceiling: Math.max(1, Math.max.apply(null, root.measurements.map(function(m) { return m.elapsed_ms })))
                    readonly property real plotWidth: Math.max(0, width - 38)
                    readonly property real plotHeight: height - 21
                    readonly property real slotWidth: Math.max(1, (plotWidth - Math.max(0, root.measurements.length - 1) * 3) / Math.max(1, root.measurements.length))
                    GGStreamClock {
                        id: sampleClock
                        objectName: "testnetStreamClock"
                        active: root.running && !root.readFailed
                        observationTime: root.measurements.length ? Number(root.measurements[root.measurements.length - 1].observed_at) : NaN
                        cadenceMs: Math.max(1, Number(root.testnet.observation_interval_ms || root.testnet.block_interval_target_ms || 2000))
                    }
                    Repeater { model: root.measurements.length ? 3 : 0
                        Item { required property int index; objectName:"testnetMeasurementAxis"; y: index * chart.plotHeight / 2; width: (parent ? parent.width : 0); height: 1
                            Rectangle { width: chart.plotWidth; height: 1; color: RuntimeTheme.GGTheme.line; opacity: .6 }
                            Label { colorKey: "ui.GGTestnetDashboard.16"; x: chart.plotWidth + 6; y: -5; width: 32; text: (chart.ceiling * (1 - index / 2)).toFixed(chart.ceiling < 10 ? 1 : 0); font.pixelSize: 9; color: RuntimeTheme.GGTheme.dim; horizontalAlignment: Text.AlignRight }
                        }
                    }
                    Item { width: chart.plotWidth; height: chart.plotHeight - 1; y: 1; clip: true
                      Row { width: parent.width; height: parent.height; spacing: 3
                        // Leave room for the next actual observation. A pause
                        // leaves an empty slot, never an invented RPC sample.
                        x: root.running && !root.readFailed ? -sampleClock.phase * Math.min(24, chart.slotWidth + 3) : 0
                        Repeater { model: root.measurements.length
                            Item { id: bar; required property int index; readonly property var modelData: root.measurements[index] || ({}); objectName: "testnetMeasurementBar"; width: chart.slotWidth; height: (parent ? parent.height : 0)
                                GGMeasurementBar { anchors.fill: parent; fraction: Number(bar.modelData.elapsed_ms) / chart.ceiling; barColor: root.measurementColor(bar.modelData.operation); seriesKey: "ui.chart.testnet." + bar.modelData.operation; animateChanges: sampleClock.cadenceMs >= 50; opacity: hover.hovered ? 1 : .8 }
                                HoverHandler { id: hover }
                                TapHandler { onTapped:if(testnetRelations.selectMeasurement(bar.modelData))mainScroll.chartPage=1 }
                                ToolTip.visible: hover.hovered; ToolTip.delay: 400; ToolTip.text: hover.hovered ? root.measurementLabel(modelData.operation) + " · " + Number(modelData.elapsed_ms).toFixed(2) + " ms\n" + root.timeText(modelData.observed_at) + " · " + root.stateText(modelData.state) : ""
                                Accessible.role: Accessible.Graphic; Accessible.name: root.measurementLabel(modelData.operation) + " " + modelData.elapsed_ms + " millisekunder"
                            }
                        }
                      }
                    }
                    Label { colorKey: "ui.GGTestnetDashboard.17"; anchors.centerIn: parent; width: (parent ? parent.width : 0) - 48; visible: !root.measurements.length; text: "Inga mätningar ännu · starta testnoden för faktiska RPC-värden"; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10; horizontalAlignment: Text.AlignHCenter; wrapMode:Text.NoWrap;elide:Text.ElideRight;ToolTip.visible:infoHover1.hovered;ToolTip.text:text;HoverHandler{id:infoHover1} }
                    Flow { y: chart.plotHeight + 6; width: (parent ? parent.width : 0); spacing: 4; visible: root.measurements.length > 0
                        Repeater { model: ["rpc", "transaction", "self_test"]
                            Row { required property string modelData; spacing: 4; Rectangle { y: 3; width: 5; height: 5; color: root.measurementColor(modelData); GGColorTarget{colorKey:"ui.chart.testnet."+modelData} } Label { colorKey: "ui.chartlabel.testnet."+modelData; text: root.measurementLabel(modelData); color: RuntimeTheme.GGTheme.dim; font.pixelSize: 9 } }
                        }
                    }
                }
            }
        relationsPanel: BlockRelationsGraph { property string uiColorScope: "ui.widget.GGTestnetDashboard.BlockRelationsGraph.16";id:testnetRelations;graph:root.observed.block_graph || root.testnet.block_graph || ({});measurements:root.measurements;surfaceHost:root.surfaceHost}
        accountsPanel:Item {
            id:accountBook
            SectionHead { property string uiColorScope: "ui.widget.GGTestnetDashboard.SectionHead.17";title:"TESTKONTON";detail:root.running?"4 st · enbart testmedel":"skapas vid start"}
            Item {id:accountColumns;y:19;width:parent.width;height:16
                Label { colorKey: "ui.GGTestnetDashboard.19";text:"#";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim}
                Label { colorKey: "ui.GGTestnetDashboard.20";x:18;width:parent.width*.31-18;text:"ADRESS";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim}
                Label { colorKey: "ui.GGTestnetDashboard.21";x:parent.width*.38;width:parent.width*.17-4;text:"ETIKETT";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim}
                Label { colorKey: "ui.GGTestnetDashboard.22";x:parent.width*.55;width:parent.width*.225-4;text:"DEV";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim;horizontalAlignment:Text.AlignRight}
                Label { colorKey: "ui.GGTestnetDashboard.23";x:parent.width*.775;width:parent.width*.225;text:"GG-TEST";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim;horizontalAlignment:Text.AlignRight}
            }
            ListView {id:accountList;objectName:"testnetAccountsList";y:35;width:parent.width;height:Math.max(0,parent.height-y-15);clip:true;model:root.accounts.length;boundsBehavior:Flickable.StopAtBounds;ScrollBar.vertical:ScrollBar {}
                delegate:Item {id:account;required property int index;readonly property var modelData:root.accounts[index]||({});objectName:"testnetAccountRow";width:ListView.view.width;height:25
                    Label { colorKey: "ui.GGTestnetDashboard.24";y:5;width:16;text:index+1;font.pixelSize:9;color:RuntimeTheme.GGTheme.dim}
                    Label { colorKey: "ui.type.account.identity";x:18;y:5;width:parent.width*.31-20;text:root.shortAddress(modelData.address);font.pixelSize:9;color:RuntimeTheme.GGTheme.muted}
                    CopyAction { property string uiColorScope: "ui.control.GGTestnetDashboard.10";objectName:"testnetCopyAccount";x:parent.width*.31-1;y:2;width:18;height:20;value:account.modelData.address;viewport:mainScroll;tip:"Kopiera offentlig adress för konto "+(account.index+1)}
                    Label { colorKey: "ui.type.account.identity";x:parent.width*.38;y:5;width:parent.width*.17-4;text:"Konto "+(index+1);font.pixelSize:9}
                    Label { colorKey: "ui.GGTestnetDashboard.27";objectName:"testnetNativeBalance";x:parent.width*.55;y:5;width:parent.width*.225-4;text:root.numberOrMissing(modelData.native);horizontalAlignment:Text.AlignRight;font.pixelSize:9;Accessible.name:"Konto "+(index+1)+": "+text+" DEV"}
                    Label { colorKey: "ui.GGTestnetDashboard.28";objectName:"testnetTokenBalance";x:parent.width*.775;y:5;width:parent.width*.225;text:root.numberOrMissing(modelData.token);horizontalAlignment:Text.AlignRight;font.pixelSize:9;Accessible.name:"Konto "+(index+1)+": "+text+" GG-TEST"}
                    Rule { property string uiColorScope: "ui.widget.GGTestnetDashboard.Rule.19";anchors.bottom:parent.bottom;opacity:.6}
                }
            }
            Label { colorKey: "ui.GGTestnetDashboard.29";y:Math.max(35,parent.height-12);width:parent.width;text:root.testnet.contract?"GG-TEST · ERC-20 · 6 decimaler · fast utbud 1 000 000":"Testtoken ej deployad · DEV är endast testgas";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim}
            Label { colorKey: "ui.GGTestnetDashboard.30";anchors.centerIn:accountList;width:parent.width;visible:!root.accounts.length;text:"Fyra tillfälliga konton skapas vid start";font.pixelSize:10;color:RuntimeTheme.GGTheme.dim;horizontalAlignment:Text.AlignHCenter}
        }
        transferPanel:Column {height:parent?parent.height:0;width:parent?parent.width:0;spacing:4
            Item {width:parent.width;height:22
                Label { colorKey: "ui.GGTestnetDashboard.31";y:4;width:parent.width*.38;text:"SKICKA TOKEN · TESTNÄT";font.pixelSize:10;color:RuntimeTheme.GGTheme.muted}
                Label { colorKey: "ui.GGTestnetDashboard.32";x:parent.width*.38;y:5;width:Math.max(0,parent.width*.62-190);text:root.testnet.contract?"Kontrakt "+root.shortAddress(root.testnet.contract):"GG-TEST · ERC-20 · 6 decimaler";font.pixelSize:9;color:RuntimeTheme.GGTheme.dim}
                CopyAction { property string uiColorScope: "ui.control.GGTestnetDashboard.11";x:parent.width-190;y:0;width:20;height:22;visible:!!root.testnet.contract;value:root.testnet.contract||"";viewport:mainScroll}
                TestAction { property string uiColorScope: "ui.control.GGTestnetDashboard.12";objectName:"testnetDeploy";anchors.right:parent.right;height:22;width:166;text:root.running&&root.testnet.contract?"Testtoken deployad":"Deploya testtoken";enabled:root.canAct&&root.running&&!root.hasReview&&!root.testnet.contract&&root.quotaAvailable&&!root.unresolved;onClicked:root.run("testnet_deploy",{})}
                Rule { property string uiColorScope: "ui.widget.GGTestnetDashboard.Rule.22";anchors.bottom:parent.bottom}
            }
            Grid {id:transferForm;objectName:"testnetTransferForm";width:parent.width;columns:width>=580?5:2;columnSpacing:6;rowSpacing:5
                Column {width:(transferForm.width-(transferForm.columns-1)*6)/transferForm.columns;spacing:2
                    Label { colorKey: "ui.GGTestnetDashboard.33";text:"FRÅN";font.pixelSize:9;color:RuntimeTheme.GGTheme.dim}
                    CryptoPick { property string uiColorScope: "ui.control.GGTestnetDashboard.13";id:sender;objectName:"testnetSender";width:parent.width;height:24;model:root.accountChoices;textRole:"name";currentIndex:root.hasReview&&typeof root.review.sender_index==="number"?root.review.sender_index:root.senderIndex;enabled:root.editable;Accessible.name:"Avsändande testkonto";onActivated:root.senderIndex=currentIndex;font.pixelSize:10}
                }
                Column {width:(transferForm.width-(transferForm.columns-1)*6)/transferForm.columns;spacing:2
                    Label { colorKey: "ui.GGTestnetDashboard.34";text:"TILL";font.pixelSize:9;color:RuntimeTheme.GGTheme.dim}
                    CryptoPick { property string uiColorScope: "ui.control.GGTestnetDashboard.14";id:recipient;objectName:"testnetRecipient";width:parent.width;height:24;model:root.accountChoices;textRole:"name";currentIndex:root.recipientIndex;enabled:root.editable&&!root.externalRecipient;Accessible.name:"Mottagande testkonto";onActivated:root.recipientIndex=currentIndex;font.pixelSize:10}
                }
                Column {width:(transferForm.width-(transferForm.columns-1)*6)/transferForm.columns;spacing:2
                    Label { colorKey: "ui.GGTestnetDashboard.35";text:"TILLGÅNG";font.pixelSize:9;color:RuntimeTheme.GGTheme.dim}
                    CryptoPick { property string uiColorScope: "ui.control.GGTestnetDashboard.15";id:asset;objectName:"testnetAsset";width:parent.width;height:24;model:["GG-TEST","DEV · testgas"];enabled:root.editable;Accessible.name:"Testtillgång";font.pixelSize:10}
                }
                Column {width:(transferForm.width-(transferForm.columns-1)*6)/transferForm.columns;spacing:2
                    Label { colorKey: "ui.GGTestnetDashboard.36";text:"BELOPP";font.pixelSize:9;color:RuntimeTheme.GGTheme.dim}
                    CryptoField { property string uiColorScope: "ui.widget.GGTestnetDashboard.CryptoField.26";id:amount;objectName:"testnetAmount";width:parent.width;height:24;text:"1";maximumLength:60;enabled:root.editable;inputMethodHints:Qt.ImhFormattedNumbersOnly;Accessible.name:"Exakt belopp i vald testtillgång";font.pixelSize:10}
                }
                Column {width:(transferForm.width-(transferForm.columns-1)*6)/transferForm.columns;spacing:2
                    Label { colorKey: "ui.GGTestnetDashboard.37";text:" ";visible:transferForm.columns===5;font.pixelSize:9}
                    TestAction { property string uiColorScope: "ui.control.GGTestnetDashboard.16";objectName:"testnetPrepare";width:parent.width;height:24;text:"Förhandsgranska";enabled:root.canPrepare;onClicked:root.prepare()}
                }
            }
            Item {width:parent.width;height:20
                CryptoToggle { property string uiColorScope: "ui.control.GGTestnetDashboard.17";objectName:"testnetExternalRecipient";width:Math.min(310,parent.width);height:20;text:"Annan offentlig testadress";checked:root.externalRecipient;enabled:root.editable;onClicked:root.externalRecipient=checked;font.pixelSize:9}
                Label { colorKey: "ui.GGTestnetDashboard.38";x:Math.min(310,parent.width);y:4;width:Math.max(0,parent.width-x);text:root.hasReview?"Granskningen är låst":root.unresolved?"Inväntar kvitto":root.running&&root.assetId==="GG-TEST"&&!root.testnet.contract?"Deploya testtoken före överföring":"Enbart testmedel · inga riktiga tillgångar";font.pixelSize:9;color:root.hasReview||root.unresolved?RuntimeTheme.GGTheme.accent:RuntimeTheme.GGTheme.dim}
            }
            CryptoField { property string uiColorScope: "ui.widget.GGTestnetDashboard.CryptoField.29";id:externalAddress;objectName:"testnetExternalAddress";width:parent.width;height:24;visible:root.externalRecipient;placeholderText:"0x… · offentlig adress på detta lokala testnät";maximumLength:42;enabled:root.editable;Accessible.name:"Annan offentlig testmottagaradress";font.pixelSize:10}
        }
        historyPanel:Item {
            SectionHead { property string uiColorScope: "ui.widget.GGTestnetDashboard.SectionHead.30";title:"SENASTE TRANSAKTIONER";detail:root.transactions.length+" st"}
            Item {y:19;width:parent.width;height:16
                Label { colorKey: "ui.GGTestnetDashboard.39";text:"HASH";width:parent.width*.24;font.pixelSize:8;color:RuntimeTheme.GGTheme.dim}
                Label { colorKey: "ui.GGTestnetDashboard.40";x:parent.width*.24;width:parent.width*.25;text:"BELOPP";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim;horizontalAlignment:Text.AlignRight}
                Label { colorKey: "ui.GGTestnetDashboard.41";x:parent.width*.50;width:parent.width*.16;text:"GAS";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim;horizontalAlignment:Text.AlignRight}
                Label { colorKey: "ui.GGTestnetDashboard.42";x:parent.width*.67;width:parent.width*.09;text:"H";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim;horizontalAlignment:Text.AlignRight}
                Label { colorKey: "ui.GGTestnetDashboard.43";x:parent.width*.79;width:parent.width*.21;text:"STATUS";font.pixelSize:8;color:RuntimeTheme.GGTheme.dim}
            }
            ListView {id:transactionList;objectName:"testnetTransactionsList";y:35;width:parent.width;height:Math.max(0,parent.height-y);clip:true;model:root.transactions.length;boundsBehavior:Flickable.StopAtBounds;ScrollBar.vertical:ScrollBar {}
                delegate:Item {id:transaction;required property int index;readonly property var modelData:root.transactions[index]||({});objectName:"testnetTransactionRow";width:ListView.view.width;height:25
                    Label { colorKey: "ui.GGTestnetDashboard.44";y:5;width:parent.width*.24-18;text:modelData.txid?root.shortAddress(modelData.txid):"Väntar";font.pixelSize:9;color:RuntimeTheme.GGTheme.muted}
                    CopyAction { property string uiColorScope: "ui.control.GGTestnetDashboard.18";x:parent.width*.24-19;y:2;width:18;height:20;value:transaction.modelData.txid;viewport:mainScroll;tip:"Kopiera offentlig transaktionshash"}
                    Label { colorKey: "ui.GGTestnetDashboard.45";x:parent.width*.24;y:5;width:parent.width*.25;text:String(modelData.amount);font.pixelSize:9;horizontalAlignment:Text.AlignRight}
                    Label { colorKey: "ui.GGTestnetDashboard.46";x:parent.width*.50;y:5;width:parent.width*.16;text:root.numberOrMissing(modelData.gas_used);font.pixelSize:9;color:RuntimeTheme.GGTheme.dim;horizontalAlignment:Text.AlignRight}
                    Label { colorKey: "ui.GGTestnetDashboard.47";x:parent.width*.67;y:5;width:parent.width*.09;text:root.numberOrMissing(modelData.block);font.pixelSize:9;color:RuntimeTheme.GGTheme.dim;horizontalAlignment:Text.AlignRight}
                    Rectangle {x:parent.width*.79;y:9;width:5;height:5;radius:3;color:root.stateColor(transaction.modelData.state)}
                    Label { colorKey: "ui.GGTestnetDashboard.48";x:parent.width*.79+9;y:5;width:parent.width*.21-9;text:root.stateText(modelData.state);font.pixelSize:9;color:root.stateColor(modelData.state)}
                    HoverHandler {id:transactionHover}
                    ToolTip.visible:transactionHover.hovered;ToolTip.delay:400;ToolTip.text:transactionHover.hovered?root.accountLabel(modelData.sender)+" → "+root.accountLabel(modelData.recipient)+" · "+String(modelData.amount)+" "+String(modelData.symbol):""
                    Rule { property string uiColorScope: "ui.widget.GGTestnetDashboard.Rule.32";anchors.bottom:parent.bottom;opacity:.6}
                }
            }
            Label { colorKey: "ui.GGTestnetDashboard.49";anchors.centerIn:transactionList;width:parent.width;visible:!root.transactions.length;text:"Inga överföringar i sessionen";font.pixelSize:10;color:RuntimeTheme.GGTheme.dim;horizontalAlignment:Text.AlignHCenter}
        }
    }

    }
    Component {
        id: telemetryComponent
        Item {
            objectName: "testnetTelemetry"
            Rectangle { width: 1; height: (parent ? parent.height : 0); color: RuntimeTheme.GGTheme.line; visible: root.railVisible }
            NetworkRailLayout { property string uiColorScope: "ui.widget.GGTestnetDashboard.NetworkRailLayout.33";
        id:telemetryScroll;objectName:"testnetTelemetryScroll";prefix:"testnet"
        x:12;y:6;width:Math.max(0,(parent ? parent.width : 0)-24);height:Math.max(0,(parent ? parent.height : 0)-12)
        titles:["MIN TESTNOD", "KONTRAKT & KONTROLLER", "BLOCK & AVGIFTER", "RESURSER", "FUNKTIONSTEST"]
        sections:[Column { width: (parent ? parent.width : 0); spacing: 0
                        SectionHead { property string uiColorScope: "ui.widget.GGTestnetDashboard.SectionHead.34"; title: "MIN TESTNOD" }
                        Fact { property string uiColorScope: "ui.widget.GGTestnetDashboard.Fact.35"; name: "Status"; value: root.stateLabel; valueColor: root.running ? RuntimeTheme.GGTheme.positive : root.readFailed ? RuntimeTheme.GGTheme.negative : RuntimeTheme.GGTheme.dim }
                        Fact { property string uiColorScope: "ui.widget.GGTestnetDashboard.Fact.36"; name: "Motor"; value: String(root.testnet.engine || "Hardhat") }
                        Fact { property string uiColorScope: "ui.widget.GGTestnetDashboard.Fact.37"; name: "Bindning"; value: root.testnet.binding === "LOOPBACK_ONLY" ? "127.0.0.1 · lokalt" : "Ej verifierad" }
                        Fact { property string uiColorScope: "ui.widget.GGTestnetDashboard.Fact.38"; name: "Peers"; value: root.running ? String(root.testnet.peer_count) + " · inget P2P" : "—" }
                        Item { width: (parent ? parent.width : 0); height: 18
                            Label { colorKey: "ui.GGTestnetDashboard.50"; y: 2; width: (parent ? parent.width : 0) * .30; text: "RPC"; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10 }
                            Label { colorKey: "ui.GGTestnetDashboard.51"; id: rpcLabel; x: (parent ? parent.width : 0) * .30; y: 2; width: (parent ? parent.width : 0) * .70 - 28; text: /^http:\/\/127\.0\.0\.1:\d+$/.test(String(root.testnet.rpc_url || "")) ? root.testnet.rpc_url : "Inte startad"; color: RuntimeTheme.GGTheme.muted; font.pixelSize: 10; wrapMode: Text.NoWrap; elide: Text.ElideRight; horizontalAlignment: Text.AlignRight }
                            CopyAction { property string uiColorScope: "ui.control.GGTestnetDashboard.19"; objectName: "testnetCopyRpc"; anchors.right: parent.right; y: 2; value: root.testnet.rpc_url || ""; viewport: telemetryScroll; tip: "Kopiera lokal RPC-adress" }
                        }
                        Label { colorKey: "ui.GGTestnetDashboard.52"; visible:false; width: (parent ? parent.width : 0); topPadding: 8; text: "Tillfälliga testkonton. Ingen produktionsnod. Noden och testnycklarna kastas när testnätet stoppas."; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10; wrapMode:Text.NoWrap;elide:Text.ElideRight;ToolTip.visible:infoHover6.hovered;ToolTip.text:text;HoverHandler{id:infoHover6} }
                    },
Column { width: (parent ? parent.width : 0); spacing: 0
                        SectionHead { property string uiColorScope: "ui.widget.GGTestnetDashboard.SectionHead.40"; title: "KONTRAKT & KONTROLLER" }
                        Fact { property string uiColorScope: "ui.widget.GGTestnetDashboard.Fact.41"; name: "ERC-20-bytekod"; value: root.running && !!root.testnet.contract ? "Kontrollerad" : root.readFailed ? "Ej aktuell kontroll" : "Inte deployad"; valueColor: root.running && !!root.testnet.contract ? RuntimeTheme.GGTheme.positive : RuntimeTheme.GGTheme.dim }
                        Fact { property string uiColorScope: "ui.widget.GGTestnetDashboard.Fact.42"; name: "Fast testutbud"; value: "1 000 000 GG-TEST" }
                        Fact { property string uiColorScope: "ui.widget.GGTestnetDashboard.Fact.43"; name: "Decimaler"; value: root.numberOrMissing(root.testnet.decimals) }
                        Fact { property string uiColorScope: "ui.widget.GGTestnetDashboard.Fact.44"; name: "Signerare / nycklar"; value: root.nodeOwned ? "Tillfälliga testkonton" : "Inga aktiva testnycklar" }
                        Fact { property string uiColorScope: "ui.widget.GGTestnetDashboard.Fact.45"; name: "Nätverksbindning"; value: root.running ? "Chain + genesis" : "Ej aktuell kontroll"; valueColor: root.running ? RuntimeTheme.GGTheme.positive : RuntimeTheme.GGTheme.dim }
                    },
Column { width: (parent ? parent.width : 0); spacing: 2
                        SectionHead { property string uiColorScope: "ui.widget.GGTestnetDashboard.SectionHead.46"; title: "BLOCK & AVGIFTER" }
                        QuotaBar { property string uiColorScope: "ui.widget.GGTestnetDashboard.QuotaBar.47"; objectName: "testnetGasBar"; title: "Gas i senast lästa block"; used: root.running || root.readFailed ? root.testnet.gas_used : null; limit: root.running || root.readFailed ? root.testnet.gas_limit : null }
                        Fact { property string uiColorScope: "ui.widget.GGTestnetDashboard.Fact.48"; name: "Basavgift · wei"; value: root.running || root.readFailed ? root.numberOrMissing(root.testnet.base_fee_atomic) : "—" }
                        QuotaBar { property string uiColorScope: "ui.widget.GGTestnetDashboard.QuotaBar.49"; objectName: "testnetQuotaBar"; title: "Sessionskvot · transaktioner"; used: root.testnet.session_transactions === undefined ? null : root.testnet.session_transactions; limit: root.testnet.transaction_limit === undefined ? null : root.testnet.transaction_limit }
                    },
Column { width: (parent ? parent.width : 0); spacing: 2
                        SectionHead { property string uiColorScope: "ui.widget.GGTestnetDashboard.SectionHead.50"; title: "RESURSER"; detail: "uppmätt" }
                        QuotaBar { property string uiColorScope: "ui.widget.GGTestnetDashboard.QuotaBar.51"; objectName: "testnetMemoryBar"; title: "Nodprocess · privat minne"; used: root.resourceMetrics.memory_committed_bytes; limit: root.resourceLimits.verified === true ? root.resourceLimits.memory_bytes : null; valueText: sampled ? (numericUsed / 1048576).toFixed(1) + (available ? " / " + (numericLimit / 1048576).toFixed(0) + " MiB" : " MiB · gräns saknas") : "Ej uppmätt" }
                        QuotaBar { property string uiColorScope: "ui.widget.GGTestnetDashboard.QuotaBar.52"; objectName: "testnetCpuBar"; title: "Ackumulerad CPU-tid"; used: root.resourceMetrics.cpu_seconds; limit: root.resourceLimits.verified === true ? root.resourceLimits.cpu_seconds : null; valueText: sampled ? numericUsed.toFixed(2) + (available ? " / " + numericLimit.toFixed(0) + " s" : " s · gräns saknas") : "Ej uppmätt" }
                        Label { colorKey: "ui.GGTestnetDashboard.53"; visible:false; width: (parent ? parent.width : 0); text: root.resourceLimits.verified === true && root.resourceLimits.provider === "WINDOWS_JOB_OBJECT" ? "Verifierade processbudgetar · Windows-jobb. CPU-måttet är förbrukad processtid." : "Processbudgetar är inte verifierade på den här plattformen. CPU-måttet är förbrukad processtid."; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10; wrapMode:Text.NoWrap;elide:Text.ElideRight;ToolTip.visible:infoHover7.hovered;ToolTip.text:text;HoverHandler{id:infoHover7} }
                    },
Column { width: (parent ? parent.width : 0); spacing: 2
                        Item {width:parent.width;height:22
                            Label { colorKey: "ui.GGTestnetDashboard.54";y:5;width:parent.width-132;text:"FUNKTIONSTEST";font.pixelSize:9;color:RuntimeTheme.GGTheme.muted}
                            TestAction { property string uiColorScope: "ui.control.GGTestnetDashboard.20";objectName:"testnetSelfTest";anchors.right:parent.right;width:128;height:22;text:"Kör fram/tillbaka";tip:"Skicka och kontrollera GG-TEST och DEV i båda riktningar";enabled:root.canAct&&root.running&&!root.hasReview&&!root.unresolved&&Number(root.testnet.session_transactions||0)<=Number(root.testnet.transaction_limit||256)-5;onClicked:root.run("testnet_self_test",{})}
                        }
                        Label { colorKey: "ui.GGTestnetDashboard.55"; visible:false; width: (parent ? parent.width : 0); text: "Skickar GG-TEST och DEV mellan konto 1 och 2 i båda riktningarna. Kontrollerar verkliga testkvitton och tokensaldon."; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10; wrapMode:Text.NoWrap;elide:Text.ElideRight;ToolTip.visible:infoHover8.hovered;ToolTip.text:text;HoverHandler{id:infoHover8} }
                        Repeater { model: (root.lastTest.checks || []).length
                            Item { required property int index; readonly property var modelData:(root.lastTest.checks||[])[index]||({}); objectName: "testnetSelfTestCheck"; width: (parent ? parent.width : 0); height: 14
                                Rectangle { y: 5; width: 6; height: 6; radius: 3; color: root.stateColor(modelData.state) }
                                Label { colorKey: "ui.GGTestnetDashboard.56"; x: 14; width: (parent ? parent.width : 0) - x; text: (modelData.asset === "NATIVE" ? "DEV" : String(modelData.asset)) + " · Konto " + (modelData.from + 1) + " → " + (modelData.to + 1) + " · " + root.stateText(modelData.state); color: root.stateColor(modelData.state); font.pixelSize: 10 }
                            }
                        }
                        Label { colorKey: "ui.GGTestnetDashboard.57"; width: (parent ? parent.width : 0); visible: false && root.lastTest.token_balances_restored === true && root.lastTest.supply_verified === true && root.lastTest.state === "PASS"; text: "Tokensaldon återställda och fast utbud kontrollerat. DEV minskar med testgas."; color: RuntimeTheme.GGTheme.positive; font.pixelSize: 10; wrapMode:Text.NoWrap;elide:Text.ElideRight;ToolTip.visible:infoHover9.hovered;ToolTip.text:text;HoverHandler{id:infoHover9} }
                    }]
        eventsPanel:Column { width: (parent ? parent.width : 0); spacing: 3
                        Item { width: (parent ? parent.width : 0); height: 24
                            Label { colorKey: "ui.GGTestnetDashboard.58"; y: 8; text: "HÄNDELSER"; color: RuntimeTheme.GGTheme.muted; font.pixelSize: 10; font.letterSpacing: .5 }
                            TestAction { property string uiColorScope: "ui.control.GGTestnetDashboard.21"; objectName: "testnetAllEvents"; anchors.right: parent.right; height: 27; text: "Visa alla"; flat: true; enabled: true; onClicked: eventsPopup.open() }
                            Rule { property string uiColorScope: "ui.widget.GGTestnetDashboard.Rule.55"; anchors.bottom: parent.bottom }
                        }
                        ListView { objectName:"testnetEventsList";width:(parent ? parent.width : 0);height:Math.max(0,(parent ? parent.height : 0)-40);clip:true;model:Math.min(12,root.events.length);boundsBehavior:Flickable.StopAtBounds;ScrollBar.vertical:ScrollBar {}
 delegate:Column { required property int index; readonly property var modelData:root.events[index]||({}); objectName: "testnetEventRow"; width: ListView.view.width; spacing: 5
                                Item { width: (parent ? parent.width : 0); height: 13
                                    Rectangle { y: 4; width: 5; height: 5; radius: 3; color: root.stateColor(modelData.kind) }
                                    Label { colorKey: "ui.GGTestnetDashboard.59"; x: 12; width: 58; text: root.timeText(modelData.ts); color: RuntimeTheme.GGTheme.dim; font.pixelSize: 9 }
                                    Label { colorKey: "ui.GGTestnetDashboard.60"; x: 76; width: (parent ? parent.width : 0) - x; text: String(modelData.kind || "").replace(/_/g, " "); color: root.stateColor(modelData.kind); font.pixelSize: 9 }
                                }
                                Label { colorKey: "ui.GGTestnetDashboard.61"; x: 12; width: (parent ? parent.width : 0) - 12; text: modelData.message || ""; color: RuntimeTheme.GGTheme.muted; font.pixelSize: 9; wrapMode: Text.NoWrap; elide: Text.ElideRight }
                            }
}
                        Label { colorKey: "ui.GGTestnetDashboard.62"; width: (parent ? parent.width : 0); visible: !root.events.length; text: "Inga testnätshändelser registrerade."; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10; wrapMode:Text.NoWrap;elide:Text.ElideRight;ToolTip.visible:infoHover10.hovered;ToolTip.text:text;HoverHandler{id:infoHover10} }
                    }
    }
        }
    }
    Loader { x: root.mainWidth; y: toolbar.height; width: root.railWidth; height: Math.max(0, root.height - y); active: root.railVisible; visible: active; sourceComponent: telemetryComponent }
    Popup {
        id: factsDrawer; objectName: "testnetFactsDrawer"; x: Math.max(0, root.width - width); y: toolbar.height; width: Math.min(360, root.width); height: Math.max(0, root.height - y); padding: 0; modal: true; focus: true; closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { color: RuntimeTheme.GGTheme.base; LedgerBorder { property string uiColorScope: "ui.widget.GGTestnetDashboard.LedgerBorder.56"; anchors.fill: parent; color: RuntimeTheme.GGTheme.edge; radius: 0 } }
        contentItem: Item {
            TestAction { property string uiColorScope: "ui.control.GGTestnetDashboard.22"; anchors.right: parent.right; anchors.rightMargin: 8; y: 2; width: 28; text: "×"; enabled: true; tip: "Stäng testnodspanelen"; Accessible.name: tip; onClicked: factsDrawer.close() }
            Loader { y: 30; width: (parent ? parent.width : 0); height: Math.max(0, (parent ? parent.height : 0) - y); active: factsDrawer.visible; sourceComponent: telemetryComponent }
        }
    }
    Menu {
        id: advancedMenu; objectName: "testnetAdvancedMenu"; x: Math.max(0, root.width - width - 12); y: toolbar.height; width: Math.min(260, root.width - 24)
        TestMenuItem { property string uiColorScope: "ui.widget.GGTestnetDashboard.TestMenuItem.58"; text: root.detailsVisible ? "Dölj sidopanel" : "Visa sidopanel"; onTriggered: root.toggleDetails() }
        TestMenuItem { property string uiColorScope: "ui.widget.GGTestnetDashboard.TestMenuItem.59"; text: "Alla testnätshändelser"; onTriggered: eventsPopup.open() }
        MenuSeparator {}
        TestMenuItem { property string uiColorScope: "ui.widget.GGTestnetDashboard.TestMenuItem.60"; text: "Signerat nätverkslabb"; onTriggered: root.pageRequested("LAB") }
        TestMenuItem { property string uiColorScope: "ui.widget.GGTestnetDashboard.TestMenuItem.61"; text: "Konton & tillgångar"; onTriggered: root.pageRequested("WALLET") }
        TestMenuItem { property string uiColorScope: "ui.widget.GGTestnetDashboard.TestMenuItem.62"; text: "NFT-inspektör"; onTriggered: root.pageRequested("NFT") }
        TestMenuItem { property string uiColorScope: "ui.widget.GGTestnetDashboard.TestMenuItem.63"; text: "Paperbotar"; onTriggered: root.pageRequested("BOTS") }
        background: Rectangle { color: RuntimeTheme.GGTheme.panel; border.color: RuntimeTheme.GGTheme.edge }
    }
    Popup {
        id: setupHelp; objectName: "testnetSetupHelp"; x: 8; y: 52; width: Math.min(450, root.width - 16); padding: 16; modal: true; focus: true; closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { color: RuntimeTheme.GGTheme.panel; LedgerBorder { property string uiColorScope: "ui.widget.GGTestnetDashboard.LedgerBorder.64"; anchors.fill: parent; color: RuntimeTheme.GGTheme.edge; radius: 2 } }
        contentItem: Column { width: (parent ? parent.width : 0); spacing: 4
            Label { colorKey: "ui.GGTestnetDashboard.63"; width: (parent ? parent.width : 0); text: "Valfri lokal testmotor"; color: RuntimeTheme.GGTheme.bright; font.pixelSize: 13 }
            Label { colorKey: "ui.GGTestnetDashboard.64"; width: (parent ? parent.width : 0); text: "Hardhat behöver installeras innan testnoden kan startas. Installationen hämtar utvecklingsverktyg från nätet och startas separat. Den här hjälpen gör inga nätverksanrop."; color: RuntimeTheme.GGTheme.muted; wrapMode:Text.NoWrap;elide:Text.ElideRight;ToolTip.visible:infoHover11.hovered;ToolTip.text:text;HoverHandler{id:infoHover11} }
            Label { colorKey: "ui.GGTestnetDashboard.65"; width: (parent ? parent.width : 0); text: ".venv-windows/Scripts/python.exe support/gg-testnet/install_toolchain.py"; color: RuntimeTheme.GGTheme.text; font.pixelSize: 10; wrapMode: Text.WrapAnywhere; elide: Text.ElideNone }
            Row { spacing: 8
                TestAction { property string uiColorScope: "ui.control.GGTestnetDashboard.23"; objectName: "testnetCopySetupCommand"; text: "Kopiera installationskommando"; onClicked: if (root.surfaceHost && root.surfaceHost.tmogCopy) root.surfaceHost.tmogCopy(".venv-windows/Scripts/python.exe support/gg-testnet/install_toolchain.py") }
                TestAction { property string uiColorScope: "ui.control.GGTestnetDashboard.24"; text: "Stäng"; enabled: true; onClicked: setupHelp.close() }
            }
        }
    }
    Popup {
        id: eventsPopup; objectName: "testnetEventsPopup"; x: 8; y: 8; width: Math.max(0, root.width - 16); height: Math.max(0, root.height - 16); padding: 14; modal: true; focus: true; closePolicy: Popup.CloseOnEscape
        background: Rectangle { color: RuntimeTheme.GGTheme.base; LedgerBorder { property string uiColorScope: "ui.widget.GGTestnetDashboard.LedgerBorder.67"; anchors.fill: parent; color: RuntimeTheme.GGTheme.edge; radius: 2 } }
        contentItem: Item {
            Label { colorKey: "ui.GGTestnetDashboard.66"; width: (parent ? parent.width : 0) - 40; height: 28; verticalAlignment: Text.AlignVCenter; text: "GG TESTNÄT · HÄNDELSER · " + root.events.length; color: RuntimeTheme.GGTheme.bright }
            TestAction { property string uiColorScope: "ui.control.GGTestnetDashboard.25"; anchors.right: parent.right; width: 28; text: "×"; enabled: true; tip: "Stäng händelser"; Accessible.name: tip; onClicked: eventsPopup.close() }
            ListView { objectName: "testnetAllEventsList"; y: 38; width: (parent ? parent.width : 0); height: Math.max(0, (parent ? parent.height : 0) - y); clip: true; spacing: 4; model: root.events.length; ScrollBar.vertical: ScrollBar {}
                delegate: Column { required property int index; readonly property var modelData:root.events[index]||({}); width: ListView.view.width; spacing: 5
                    Label { colorKey: "ui.GGTestnetDashboard.67"; width: (parent ? parent.width : 0); text: root.timeText(modelData.ts) + " · " + String(modelData.kind || "").replace(/_/g, " "); color: root.stateColor(modelData.kind); font.pixelSize: 10 }
                    Label { colorKey: "ui.GGTestnetDashboard.68"; width: (parent ? parent.width : 0); text: modelData.message || ""; color: RuntimeTheme.GGTheme.muted; font.pixelSize: 11; wrapMode: Text.WrapAnywhere; elide: Text.ElideNone }
                }
            }
        }
    }

    Popup {
        objectName:"testnetReviewPopup";visible:root.visible&&root.hasReview
        x:Math.max(8,(root.width-width)/2);y:Math.max(8,(root.height-height)/2)
        width:Math.min(540,root.width-16);height:Math.min(root.height-16,reviewContent.implicitHeight+24)
        padding:12;modal:true;focus:true;closePolicy:Popup.NoAutoClose
        background:Rectangle{color:RuntimeTheme.GGTheme.panel;LedgerBorder{ property string uiColorScope: "ui.widget.GGTestnetDashboard.LedgerBorder.69";anchors.fill:parent;color:RuntimeTheme.GGTheme.edge;radius:2}}
        contentItem: Column { id:reviewContent; objectName: "testnetReview"; width: (parent ? parent.width : 0); spacing: 4; visible: root.hasReview
                    SectionHead { property string uiColorScope: "ui.widget.GGTestnetDashboard.SectionHead.70"; title: "GRANSKA TESTÖVERFÖRING"; detail: "låst förhandsgranskning" }
                    Fact { property string uiColorScope: "ui.widget.GGTestnetDashboard.Fact.71"; name: "Från"; value: root.review ? root.accountLabel(root.review.sender) + " · " + String(root.review.sender) : "—" }
                    Fact { property string uiColorScope: "ui.widget.GGTestnetDashboard.Fact.72"; name: "Till"; value: root.review ? root.accountLabel(root.review.recipient) + " · " + String(root.review.recipient) : "—" }
                    Fact { property string uiColorScope: "ui.widget.GGTestnetDashboard.Fact.73"; name: "Belopp"; value: root.review ? String(root.review.amount) + " " + String(root.review.symbol) : "—"; valueColor: RuntimeTheme.GGTheme.bright }
                    Fact { property string uiColorScope: "ui.widget.GGTestnetDashboard.Fact.74"; name: "Nätverk"; value: root.review ? String(root.review.chain_id) + " · lokal EVM" : "—" }
                    Fact { property string uiColorScope: "ui.widget.GGTestnetDashboard.Fact.75"; name: "Kontrakt"; value: root.review ? root.review.asset === "GG-TEST" ? String(root.review.contract) : "Native DEV · inget tokenkontrakt" : "—" }
                    Fact { property string uiColorScope: "ui.widget.GGTestnetDashboard.Fact.76"; name: "Högsta gasavgift"; value: root.review ? String(root.review.max_fee) + " DEV" : "—" }
                    Label { colorKey: "ui.GGTestnetDashboard.69"; width: (parent ? parent.width : 0); text: "Skickar endast till det här lokala testnätet. Testmedlen saknar koppling till GGHB, Solana och andra huvudnät."; color: RuntimeTheme.GGTheme.accent; font.pixelSize: 10; wrapMode: Text.WordWrap; elide: Text.ElideNone }
                    Row { spacing: 8
                        TestAction { property string uiColorScope: "ui.control.GGTestnetDashboard.26"; objectName: "testnetSend"; text: "Skicka på testnätet"; enabled: root.canAct && root.running && root.hasReview && !!root.review.id && !!root.review.review_digest && !root.unresolved && root.quotaAvailable; onClicked: root.send() }
                        TestAction { property string uiColorScope: "ui.control.GGTestnetDashboard.27"; objectName: "testnetCancel"; text: "Avbryt"; enabled: root.canAct && root.running && root.hasReview; onClicked: root.run("testnet_cancel", {}) }
                    }
                }
    }

}

