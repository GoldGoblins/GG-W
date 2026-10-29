import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

// The network workspace owns its geometry. All values come from the current
// local lab snapshot; measurements are observations, never decorative traffic.
Item {
    id: root
    objectName: "networkDashboard"
    property var state: ({})
    property var surfaceHost: null
    property bool sidePanelOpen: true
    property int senderIndex: 0
    property int recipientIndex: 1
    readonly property var lab: state.lab || ({})
    readonly property var dashboard: lab.dashboard || ({})
    readonly property var participants: lab.participants || []
    readonly property var operation: state.ui_operation || ({})
    readonly property var transport: lab.transport || ({})
    readonly property var quorum: dashboard.quorum || ({})
    readonly property var conservation: dashboard.conservation || ({})
    readonly property var verification: lab.verification || ({})
    readonly property var webNode: state.web_node || ({})
    readonly property var pendingTransactions: dashboard.pending_transactions || []
    readonly property var recentBlocks: dashboard.recent_blocks || []
    readonly property var measurements: (dashboard.measurements || []).filter(function(m) { return typeof m.elapsed_ms === "number" && isFinite(m.elapsed_ms) && m.elapsed_ms >= 0 }).slice(-32)
    readonly property var events: (state.events || []).filter(function(e) { return ["lab", "node", "transport", "operations"].indexOf(e.scope) >= 0 }).slice(-12).reverse()
    readonly property bool busy: operation.state === "running"
    readonly property bool approvalPending: operation.state === "approval_required"
    readonly property bool canAct: !busy && !approvalPending
    readonly property bool labReady: lab.state === "ACTIVE_SESSION"
    readonly property bool hasSession: !!lab.chain_id
    readonly property bool dockAvailable: width >= 820
    readonly property bool railVisible: dockAvailable && sidePanelOpen
    readonly property bool detailsVisible: railVisible || factsDrawer.visible
    readonly property real railWidth: Math.max(248, Math.min(360, width * .27))
    readonly property real mainWidth: Math.max(0, width - (railVisible ? railWidth : 0))
    readonly property int enabledCount: quorum.enabled === undefined ? participants.filter(function(p) { return p.enabled === true }).length : quorum.enabled
    readonly property int requiredCount: quorum.required === undefined ? 3 : quorum.required
    readonly property bool hasQuorum: hasSession && enabledCount >= requiredCount
    readonly property string sessionLabel: labReady ? "Aktiv lokal session" : lab.state === "INVALID_SESSION" ? "Ogiltig session · åtgärder blockerade" : lab.state === "SEALED_SESSION" ? "Förseglad session" : lab.state === "NOT_CREATED" ? "Ingen session skapad" : "Läser nätverksstatus…"
    readonly property string errorText: String(operation.error || state.error || "")
    readonly property bool transportReady: labReady && lab.participating === true
    readonly property var participantChoices: participants.map(function(p, i) { return { index: i, name: "Deltagare " + (i + 1) + " · " + root.shortAddress(p.address) } })
    signal actionRequested(string name, var args)
    signal refreshRequested()
    signal pageRequested(string page)
    signal webRequested(string url)
    onDockAvailableChanged: if (dockAvailable) factsDrawer.close()

    function run(name, args) { if (canAct) actionRequested(name, args || {}) }
    function toggleDetails() { if (dockAvailable) { factsDrawer.close(); sidePanelOpen = !sidePanelOpen } else if (factsDrawer.visible) factsDrawer.close(); else factsDrawer.open() }
    function shortAddress(value) { value = String(value || ""); return value.length > 20 ? value.slice(0, 7) + "…" + value.slice(-6) : value || "—" }
    function timeText(value) { return value ? new Date(Number(value) * 1000).toLocaleTimeString(Qt.locale(), "HH:mm:ss") : "—" }
    function byteText(value) { if (typeof value !== "number" || !isFinite(value)) return "—"; return value < 1024 ? value + " B" : value < 1048576 ? (value / 1024).toFixed(value % 1024 ? 1 : 0) + " KiB" : (value / 1048576).toFixed(1) + " MiB" }
    function atomicText(value) { var text = String(value === undefined || value === null ? "" : value); if (!/^\d+$/.test(text)) return "—"; while (text.length < 7) text = "0" + text; var whole = text.slice(0, -6), fraction = text.slice(-6).replace(/0+$/, ""); return whole + (fraction ? "." + fraction : "") }
    function percentage(value) { return typeof value === "number" ? (value / 100).toFixed(value % 100 ? 2 : 0) + " %" : "—" }
    function operationLabel(name) { return ({ verify: "Verifiering", commit: "Finalisering", transport_test: "Transporttest", retry_transport: "Återförsök" })[name] || String(name || "Mätning") }
    function measurementColor(name) { return RuntimeTheme.GGColorContext.colorFor("ui.chart.lab."+name, name === "verify" ? RuntimeTheme.GGTheme.purple : name === "commit" ? RuntimeTheme.GGTheme.cyan : name === "retry_transport" ? RuntimeTheme.GGTheme.negative : RuntimeTheme.GGTheme.muted) }
    function eventColor(kind) { return /FAIL|INVALID|ERROR|REJECT/.test(kind) ? RuntimeTheme.GGTheme.negative : /WAIT|RETRY|PARTIAL|PAUSED|SEALED/.test(kind) ? RuntimeTheme.GGTheme.accent : /VERIFIED|FINALIZED|DELIVERED|CREATED|STARTED/.test(kind) ? RuntimeTheme.GGTheme.positive : RuntimeTheme.GGTheme.muted }
    function setValidator(index, enabled) { if (!labReady || !canAct || index < 0 || index >= participants.length) return; var flags = participants.map(function(p) { return p.enabled === true }); flags[index] = enabled; run("configure_lab", { enabled: flags }) }
    function createSession() { if (!canAct) return; if (hasSession) sessionConfirm.open(); else run("create_lab", {}) }
    function copySample() { if (canAct && state.web_sample && surfaceHost && surfaceHost.tmogCopy) surfaceHost.tmogCopy(JSON.stringify(state.web_sample)) }
    function openWeb() { var url = String(webNode.url || ""); if (canAct && webNode.state === "RUNNING" && /^http:\/\/127\.0\.0\.1:\d+\/$/.test(url)) webRequested(url) }

    component Label: GGText { ToolTip.visible:labelHover.hovered&&truncated;ToolTip.text:text;ToolTip.delay:400;HoverHandler{id:labelHover} color: RuntimeTheme.GGTheme.text; font.family: "monospace"; font.pixelSize: 11; textFormat: Text.PlainText; elide: Text.ElideRight }
    component Rule: Rectangle { width: (parent ? parent.width : 0); height: 1; color: RuntimeTheme.GGTheme.line }
    component NetworkAction: CryptoButton { height: 24; font.pixelSize: 10; enabled: root.canAct }
    component NetworkMenuItem: MenuItem {
        id: menuControl
        contentItem: Label { colorKey: "ui.NetworkDashboard.1"; text: menuControl.text; color: menuControl.enabled ? RuntimeTheme.GGTheme.text : RuntimeTheme.GGTheme.dim; verticalAlignment: Text.AlignVCenter }
        background: Rectangle { color: menuControl.highlighted ? RuntimeTheme.GGTheme.raised : "transparent" }
    }
    component SectionHead: Item {
        property string title: ""
        property string detail: ""
        width: (parent ? parent.width : 0); height: 24
        Label { colorKey: "ui.NetworkDashboard.2"; anchors.left: parent.left; anchors.right: headingDetail.left; anchors.rightMargin: 8; height: 27; verticalAlignment: Text.AlignVCenter; text: parent.title; color: RuntimeTheme.GGTheme.muted; font.pixelSize: 10; font.letterSpacing: .5 }
        Label { colorKey: "ui.NetworkDashboard.3"; id: headingDetail; anchors.right: parent.right; height: 27; verticalAlignment: Text.AlignVCenter; text: parent.detail; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10 }
        Rule { property string uiColorScope: "ui.widget.NetworkDashboard.Rule.1"; anchors.bottom: parent.bottom }
    }
    component Fact: Item {
        property string name: ""
        property string value: "—"
        property color valueColor: RuntimeTheme.GGTheme.text
        width:parent?parent.width:0;height:14
        Label { colorKey: "ui.NetworkDashboard.4";y:1;width:parent.width*.43-6;text:parent.name;color:RuntimeTheme.GGTheme.dim;font.pixelSize:9}
        Rectangle {x:Math.max(parent.width*.43-7,parent.width-Math.min(factValue.implicitWidth,factValue.width)-8);y:5;width:4;height:4;radius:2;color:parent.valueColor;visible:parent.name==="Status"}
        Label { colorKey: "ui.NetworkDashboard.5";id:factValue;y:1;x:parent.width*.43;width:parent.width-x;text:parent.value;color:parent.valueColor;horizontalAlignment:Text.AlignRight;font.pixelSize:9;wrapMode:Text.NoWrap;elide:Text.ElideRight}
        Rectangle {y:13;width:parent.width;height:1;color:RuntimeTheme.GGTheme.line;opacity:.35}
        Accessible.role:Accessible.StaticText;Accessible.name:name+": "+value
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
        Label { colorKey: "ui.NetworkDashboard.6";y:0;width:parent.width*.48;text:quota.title;color:RuntimeTheme.GGTheme.dim;font.pixelSize:9}
        Label { colorKey: "ui.NetworkDashboard.7";x:parent.width*.48;y:0;width:parent.width*.52;text:quota.sampled?quota.valueText:"Ej uppmätt";horizontalAlignment:Text.AlignRight;color:RuntimeTheme.GGTheme.muted;font.pixelSize:9}
        Rectangle {y:17;width:Math.max(0,parent.width-32);height:3;color:RuntimeTheme.GGTheme.line;Rectangle{id:meterFill;width:parent.width*quota.fraction;height:3;color:quota.barColor} GGColorTarget{target:meterFill;colorKey:"ui.meter.lab."+quota.objectName;percentageCapable:true;fraction:quota.available?quota.fraction:NaN}}
        Label { colorKey: "ui.NetworkDashboard.8";anchors.right:parent.right;y:12;text:quota.available?(quota.fraction*100).toFixed(1)+" %":"—";color:RuntimeTheme.GGTheme.dim;font.pixelSize:8}
        Accessible.role:Accessible.ProgressBar;Accessible.name:title+": "+(sampled?valueText:"Ej uppmätt")
    }

    Item {
        id: toolbar; objectName: "networkToolbar"
        width: (parent ? parent.width : 0); height: root.width < 600 ? 62 : 34
        Row { x: 8; y: root.width < 600 ? 33 : 3; height: 28; spacing: 6
            NetworkAction { property string uiColorScope: "ui.control.NetworkDashboard.1"; objectName: "networkTestnetMode"; text: root.width<600?"EVM":"GG TESTNÄT"; flat: true; enabled: true; onClicked: root.pageRequested("TESTNET") }
            NetworkAction { property string uiColorScope: "ui.control.NetworkDashboard.2"; objectName: "networkLabMode"; text: root.width<600?"LABB":"SIGNERAT LABB"; flat: true; checked: true; enabled: true; onClicked: root.pageRequested("LAB") }
            NetworkAction { property string uiColorScope: "ui.control.NetworkDashboard.3"; objectName: "networkValidatorMode"; text: root.width<600?"BFT":"VALIDATORER"; flat: true; enabled: true; onClicked: root.pageRequested("CONSENSUS") }
            NetworkAction { property string uiColorScope: "ui.control.NetworkDashboard.4";objectName:"networkDagMode";text:root.width<600?"DAG":"DAGoblin";flat:true;enabled:true;tip:"Parallella signerade förslag · separat experimentlabb";onClicked:root.pageRequested("DAG")}
        }
        Row { id: toolbarActions; anchors.right: parent.right; anchors.rightMargin: 8; y: 3; height: 28; spacing: 6
            NetworkAction { property string uiColorScope: "ui.control.NetworkDashboard.5"; objectName: "networkVerify"; text: root.width < 560 ? "✓" : "Verifiera"; width: root.width < 560 ? 28 : implicitWidth; enabled: root.canAct && root.hasSession; tip: "Verifiera hela labbhistoriken"; Accessible.name: tip; onClicked: root.run("verify_lab", {}) }
            NetworkAction { property string uiColorScope: "ui.control.NetworkDashboard.6"; objectName: "networkRefresh"; width: 28; tip: "Uppdatera nätverksstatus"; Accessible.name: tip; onClicked: root.refreshRequested(); contentItem: Item { LedgerGlyph { property string uiColorScope: "ui.widget.NetworkDashboard.LedgerGlyph.8"; anchors.centerIn: parent; width: 15; height: 15; name: "refresh"; color: parent.parent.enabled ? RuntimeTheme.GGTheme.text : RuntimeTheme.GGTheme.dim } } }
            NetworkAction { property string uiColorScope: "ui.control.NetworkDashboard.7"; objectName: "networkNewSession"; text: root.hasSession ? "Ny session" : "Skapa labb"; tip: root.hasSession ? "Skapa en separat lokal labbsession" : "Skapa fyra lokala testdeltagare"; onClicked: root.createSession() }
            NetworkAction { property string uiColorScope: "ui.control.NetworkDashboard.8"; id: advancedButton; objectName: "networkAdvanced"; text: "⋯"; width: 28; tip: "Alla nätverksverktyg"; Accessible.name: tip; enabled: true; onClicked: advancedMenu.open() }
        }
        Rule { property string uiColorScope: "ui.widget.NetworkDashboard.Rule.11"; anchors.bottom: parent.bottom }
    }

    NetworkWorkspaceLayout { property string uiColorScope: "ui.widget.NetworkDashboard.NetworkWorkspaceLayout.12";
        id:mainScroll;objectName:"networkMainScroll";prefix:"network"
        x:0;y:toolbar.height;width:root.mainWidth;height:Math.max(0,root.height-y)
        summaryPanel: Column {width:(parent ? parent.width : 0);spacing:4;Column { width: (parent ? parent.width : 0); spacing: 7
                Item { width: (parent ? parent.width : 0); height: 18
                    Rectangle { x: 0; y: 5; width: 6; height: 6; radius: 3; color: root.labReady ? RuntimeTheme.GGTheme.positive : root.hasSession ? RuntimeTheme.GGTheme.accent : RuntimeTheme.GGTheme.dim }
                    Label { colorKey: "ui.NetworkDashboard.9"; x: 14; width: (parent ? parent.width : 0) - x; text: root.sessionLabel + (root.hasSession && !root.hasQuorum ? " · väntar på quorum" : ""); color: root.labReady && root.hasQuorum ? RuntimeTheme.GGTheme.positive : RuntimeTheme.GGTheme.accent; font.pixelSize: 11 }
                }
                Label { colorKey: "ui.NetworkDashboard.10"; width: (parent ? parent.width : 0); text: "Fyra lokala deltagare · en process · GG-LAB är testtillgångar"; font.pixelSize: 10; color: RuntimeTheme.GGTheme.dim; wrapMode: Text.NoWrap; elide: Text.ElideRight }
                Label { colorKey: "ui.NetworkDashboard.11"; objectName: "networkOperationNotice"; width: (parent ? parent.width : 0); visible: root.busy || root.approvalPending || !!root.errorText; text: root.errorText || (root.approvalPending ? "Väntar på godkännande i chatten." : "Arbetar · " + String(root.operation.name || "")); color: root.errorText ? RuntimeTheme.GGTheme.negative : RuntimeTheme.GGTheme.accent; wrapMode: Text.NoWrap; elide: Text.ElideRight }
            } Grid {
                id: metrics; objectName: "networkMetrics"; width: (parent ? parent.width : 0); columns: width >= 500 ? 4 : 2; columnSpacing: 8; rowSpacing: 4
                Repeater { model: [
                    { title: "BLOCKHÖJD", value: root.hasSession ? String(root.lab.height || 0) : "—", detail: "av " + String((root.dashboard.limits || {}).blocks || 256) + " labbblock", good: false },
                    { title: "VÄNTANDE", value: root.hasSession ? String(root.lab.pending || 0) : "—", detail: "av " + String((root.dashboard.limits || {}).pending || 64) + " transaktioner", good: false },
                    { title: "AKTIVA SIGNERARE", value: root.hasSession ? root.enabledCount + " / " + root.participants.length : "—", detail: root.hasSession ? root.hasQuorum ? root.requiredCount + " krävs för ett block" : "saknar " + Math.max(0, root.requiredCount - root.enabledCount) : "kräver 3 av 4", good: root.hasQuorum },
                    { title: "HISTORIK", value: root.verification.state === "VERIFIED" ? "Verifierad" : root.verification.state === "INVALID" ? "Ogiltig" : "—", detail: root.hasSession ? String(root.verification.blocks || 0) + " block kontrollerade" : "ingen historik ännu", good: root.verification.state === "VERIFIED" }
                ]
                    Column { required property var modelData; required property int index; objectName: "networkMetric"; width: (metrics.width - (metrics.columns - 1) * metrics.columnSpacing) / metrics.columns; height: 45; spacing: 2
                        Label { colorKey: "ui.NetworkDashboard.12"; width: (parent ? parent.width : 0); text: modelData.title; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 9; font.letterSpacing: .3 }
                        Label { colorKey: "ui.NetworkDashboard.13"; width: (parent ? parent.width : 0); text: modelData.value; color: modelData.good ? RuntimeTheme.GGTheme.positive : modelData.value === "Ogiltig" ? RuntimeTheme.GGTheme.negative : RuntimeTheme.GGTheme.bright; font.pixelSize: modelData.title === "HISTORIK" ? 17 : 18; font.bold: true; Rectangle { x:-5;y:-13;width:1;height:44;color:RuntimeTheme.GGTheme.edge;visible:parent.parent.index>0 } }
                        Label { colorKey: "ui.NetworkDashboard.14"; width: (parent ? parent.width : 0); text: modelData.detail; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 9 }
                    }
                }
            }}
        measurementPanel: Column { width: (parent ? parent.width : 0); spacing: 4
                SectionHead { property string uiColorScope: "ui.widget.NetworkDashboard.SectionHead.13"; title: "UPPMÄTTA OPERATIONER"; detail: "senaste " + root.measurements.length + " · ms" }
                Item {
                    id: measurementChart; objectName: "networkMeasurements"; width: (parent ? parent.width : 0); height: Math.max(28, (parent ? parent.height : 0) - 24)
                    readonly property real ceiling: Math.max(1, Math.max.apply(null, root.measurements.map(function(m) { return m.elapsed_ms })))
                    readonly property real plotWidth: Math.max(0, width - 38)
                    readonly property real plotHeight: height - 21
                    Repeater { model: root.measurements.length ? 3 : 0
                        Item { required property int index; y: index * measurementChart.plotHeight / 2; width: (parent ? parent.width : 0); height: 1
                            Rectangle { x: 0; width: measurementChart.plotWidth; height: 1; color: RuntimeTheme.GGTheme.line; opacity: .6 }
                            Label { colorKey: "ui.NetworkDashboard.15"; x: measurementChart.plotWidth + 6; y: -5; width: 32; text: (measurementChart.ceiling * (1 - index / 2)).toFixed(measurementChart.ceiling < 10 ? 1 : 0); font.pixelSize: 9; color: RuntimeTheme.GGTheme.dim; horizontalAlignment: Text.AlignRight }
                        }
                    }
                    Row { x: 0; y: 1; width: measurementChart.plotWidth; height: measurementChart.plotHeight - 1; spacing: 3
                        Repeater { model: root.measurements
                            Item { id: measurement; required property int index; required property var modelData; objectName: "networkMeasurementBar"; width: Math.max(1, (measurementChart.plotWidth - Math.max(0, root.measurements.length - 1) * 3) / Math.max(1, root.measurements.length)); height: (parent ? parent.height : 0)
                                Rectangle { anchors.bottom: parent.bottom; width: (parent ? parent.width : 0); height: Math.max(1, (parent ? parent.height : 0) * measurement.modelData.elapsed_ms / measurementChart.ceiling); color: root.measurementColor(measurement.modelData.operation); opacity: measurementHover.hovered ? 1 : .8;GGColorTarget{colorKey:"ui.chart.lab."+measurement.modelData.operation} }
                                HoverHandler { id: measurementHover }
                                ToolTip.visible: measurementHover.hovered; ToolTip.delay: 400; ToolTip.text: root.operationLabel(modelData.operation) + " · " + modelData.elapsed_ms.toFixed(2) + " ms\n" + root.timeText(modelData.observed_at) + " · " + String(modelData.state || "")
                                Accessible.role: Accessible.Graphic; Accessible.name: root.operationLabel(modelData.operation) + " " + modelData.elapsed_ms + " millisekunder"
                            }
                        }
                    }
                    Label { colorKey: "ui.NetworkDashboard.16"; anchors.centerIn: parent; visible: !root.measurements.length; text: "Inga tidsmätningar ännu · verifiera eller kör ett test"; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10; width: (parent ? parent.width : 0) - 48; wrapMode:Text.NoWrap;elide:Text.ElideRight;ToolTip.visible:infoHover1.hovered;ToolTip.text:text;HoverHandler{id:infoHover1}  horizontalAlignment: Text.AlignHCenter }
                    Flow { y: measurementChart.plotHeight + 6; width: (parent ? parent.width : 0); spacing: 4; visible: root.measurements.length > 0
                        Repeater { model: ["verify", "commit", "transport_test", "retry_transport"]
                            Row { required property string modelData; spacing: 4
                                Rectangle { y: 3; width: 5; height: 5; color: root.measurementColor(modelData); GGColorTarget{colorKey:"ui.chart.lab."+modelData} }
                                Label { colorKey: "ui.NetworkDashboard.17"; text: root.operationLabel(modelData); color: RuntimeTheme.GGTheme.dim; font.pixelSize: 9 }
                            }
                        }
                    }
                    Label { colorKey: "ui.NetworkDashboard.18"; y: measurementChart.plotHeight + 6; width: (parent ? parent.width : 0); visible: !root.measurements.length; text: "Diagrammet fylls av uppmätta operationer"; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 9 }
                }
            }

        relationsPanel:Item {
            SectionHead { property string uiColorScope: "ui.widget.NetworkDashboard.SectionHead.14";title:"PAKET & RESURSBUDGET";detail:root.lab.participating?"lokalt test på":"pausat"}
            Row {y:24;width:parent.width;spacing:8
                Repeater {model:[{name:"Mottaget",value:root.byteText(root.transport.received_bytes)},{name:"Levererat",value:root.transport.delivered},{name:"Avvisat",value:root.transport.rejected},{name:"Dubbletter",value:root.transport.duplicates}]
                    Item {required property var modelData;width:(parent.width-24)/4;height:14
                        Label { colorKey: "ui.NetworkDashboard.19";width:parent.width*.58;text:modelData.name;font.pixelSize:9;color:RuntimeTheme.GGTheme.dim}
                        Label { colorKey: "ui.NetworkDashboard.20";x:parent.width*.58;width:parent.width*.42;text:modelData.value===undefined?"—":String(modelData.value);font.pixelSize:9;horizontalAlignment:Text.AlignRight}
                    }
                }
            }
            QuotaBar { property string uiColorScope: "ui.widget.NetworkDashboard.QuotaBar.15";objectName:"networkStorageBar";x:0;y:43;width:(parent.width-12)/2;title:"Fragmentlagring";used:root.transport.storage_used===undefined?-1:root.transport.storage_used;limit:root.transport.storage_limit===undefined?-1:root.transport.storage_limit;valueText:root.byteText(used)+" / "+root.byteText(limit)}
            QuotaBar { property string uiColorScope: "ui.widget.NetworkDashboard.QuotaBar.16";objectName:"networkBudgetBar";x:(parent.width+12)/2;y:43;width:(parent.width-12)/2;title:"Tillgänglig bytebudget";used:root.transport.global_credit===undefined?-1:root.transport.global_credit;limit:root.transport.bytes_per_minute===undefined?-1:root.transport.bytes_per_minute;valueText:root.byteText(used)+" / "+root.byteText(limit)+" per min";barColor:RuntimeTheme.GGTheme.positive}
            Flow {y:76;width:parent.width;spacing:5
                NetworkAction { property string uiColorScope: "ui.control.NetworkDashboard.9";objectName:"networkTransportTest";height:22;text:"Testa paket";enabled:root.canAct&&root.transportReady;onClicked:root.run("transport_test",{loss:false})}
                NetworkAction { property string uiColorScope: "ui.control.NetworkDashboard.10";objectName:"networkLossTest";height:22;text:"Testa paketförlust";enabled:root.canAct&&root.transportReady;onClicked:root.run("transport_test",{loss:true})}
                NetworkAction { property string uiColorScope: "ui.control.NetworkDashboard.11";objectName:"networkRetryTransport";height:22;text:"Återförsök · "+String(root.lab.retry_packets||0);enabled:root.canAct&&root.transportReady&&root.lab.retry_packets>0;onClicked:root.run("retry_transport",{})}
                NetworkAction { property string uiColorScope: "ui.control.NetworkDashboard.12";objectName:"networkCancelTransport";height:22;text:"Avbryt paket";enabled:root.canAct&&root.labReady&&root.lab.retry_packets>0;onClicked:root.run("cancel_transport",{})}
            }
        }
        accountsPanel: Column {height:(parent ? parent.height : 0); width: (parent ? parent.width : 0); spacing: 0
                SectionHead { property string uiColorScope: "ui.widget.NetworkDashboard.SectionHead.21"; title: "LOKALA DELTAGARE"; detail: root.hasSession ? root.enabledCount + " av " + root.participants.length + " aktiverade" : "4 skapas med sessionen" }
                Item { width: (parent ? parent.width : 0); height: 25
                    Label { colorKey: "ui.NetworkDashboard.21"; x: 0; y: 2; width: (parent ? parent.width : 0) * .52; text: "DELTAGARE / ADRESS"; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 9 }
                    Label { colorKey: "ui.NetworkDashboard.22"; x: (parent ? parent.width : 0) * .52; y: 2; width: (parent ? parent.width : 0) * .48 - 72; text: "SALDO · GG-LAB"; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 9; horizontalAlignment: Text.AlignRight }
                    Label { colorKey: "ui.NetworkDashboard.23"; anchors.right: parent.right; y: 7; text: "SIGNERING"; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 9 }
                }
                ListView { objectName:"networkParticipantsList";width:(parent ? parent.width : 0);height:Math.max(0,(parent ? parent.height : 0)-48);clip:true;model:root.participants;boundsBehavior:Flickable.StopAtBounds;ScrollBar.vertical:ScrollBar {}
 delegate:Item { id: participant; required property int index; required property var modelData; objectName: "networkParticipantRow"; width: ListView.view.width; height: 43
                        Rectangle { x: 0; y: 12; width: 6; height: 6; radius: 3; color: participant.modelData.enabled && root.labReady ? RuntimeTheme.GGTheme.positive : RuntimeTheme.GGTheme.dim }
                        Label { colorKey: "ui.NetworkDashboard.24"; x: 15; y: 4; width: (parent ? parent.width : 0) * .52 - 20; text: "Deltagare " + (participant.index + 1); color: RuntimeTheme.GGTheme.bright }
                        Label { colorKey: "ui.NetworkDashboard.25"; x: 15; y: 22; width: (parent ? parent.width : 0) * .52 - 20; text: root.shortAddress(participant.modelData.address); color: RuntimeTheme.GGTheme.dim; font.pixelSize: 9 }
                        Label { colorKey: "ui.NetworkDashboard.26"; objectName: "networkParticipantBalance"; x: (parent ? parent.width : 0) * .52; y: 11; width: Math.max(0, (parent ? parent.width : 0) * .48 - 72); text: String(participant.modelData.balance); color: RuntimeTheme.GGTheme.text; font.pixelSize: 11; horizontalAlignment: Text.AlignRight; ToolTip.visible: balanceHover.hovered; ToolTip.text: text + " GG-LAB"; HoverHandler { id: balanceHover } }
                        CryptoToggle { property string uiColorScope: "ui.control.NetworkDashboard.13"; objectName: "networkParticipantEnabled"; anchors.right: parent.right; y: 6; width: 60; height: 28; text: participant.modelData.enabled ? "På" : "Av"; checked: participant.modelData.enabled === true; enabled: root.canAct && root.labReady; Accessible.name: "Aktivera signering för deltagare " + (participant.index + 1); onClicked: root.setValidator(participant.index, checked) }
                        Rule { property string uiColorScope: "ui.widget.NetworkDashboard.Rule.23"; anchors.bottom: parent.bottom; opacity: .65 }
                        Accessible.role: Accessible.Grouping; Accessible.name: "Deltagare " + (index + 1) + ", " + modelData.address + ", " + modelData.balance + " GG-LAB"
                    }
}
                Label { colorKey: "ui.NetworkDashboard.27"; width: (parent ? parent.width : 0); visible: !root.participants.length; topPadding: 18; bottomPadding: 18; text: "Skapa ett lokalt labb för att visa deltagare och testsaldon."; color: RuntimeTheme.GGTheme.dim; wrapMode:Text.NoWrap;elide:Text.ElideRight;ToolTip.visible:infoHover2.hovered;ToolTip.text:text;HoverHandler{id:infoHover2} }
            }
        transferPanel: Column {height:(parent ? parent.height : 0); width: (parent ? parent.width : 0); spacing: 4
                SectionHead { property string uiColorScope: "ui.widget.NetworkDashboard.SectionHead.24"; title: "ÖVERFÖR GG-LAB"; detail: "signerat · lokal testhuvudbok" }
                Grid { id: transferForm; width: (parent ? parent.width : 0); columns: width >= 530 ? 4 : 2; columnSpacing: 8; rowSpacing: 8
                    Column { width: (transferForm.width - (transferForm.columns - 1) * 8) / transferForm.columns; spacing: 3
                        Label { colorKey: "ui.NetworkDashboard.28"; text: "Från"; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10 }
                        CryptoPick { property string uiColorScope: "ui.control.NetworkDashboard.14"; id: sender; objectName: "networkSender"; width: (parent ? parent.width : 0); height: 24; model: root.participantChoices; textRole: "name"; currentIndex: root.participants.length ? root.senderIndex : -1; displayText: currentIndex >= 0 ? "Deltagare " + (currentIndex + 1) : "Välj deltagare"; enabled: root.canAct && root.labReady; Accessible.name: "Avsändare för lokal labböverföring"; onActivated: root.senderIndex = currentIndex }
                    }
                    Column { width: (transferForm.width - (transferForm.columns - 1) * 8) / transferForm.columns; spacing: 3
                        Label { colorKey: "ui.NetworkDashboard.29"; text: "Till"; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10 }
                        CryptoPick { property string uiColorScope: "ui.control.NetworkDashboard.15"; id: recipient; objectName: "networkRecipient"; width: (parent ? parent.width : 0); height: 24; model: root.participantChoices; textRole: "name"; currentIndex: root.participants.length ? root.recipientIndex : -1; displayText: currentIndex >= 0 ? "Deltagare " + (currentIndex + 1) : "Välj deltagare"; enabled: root.canAct && root.labReady; Accessible.name: "Mottagare för lokal labböverföring"; onActivated: root.recipientIndex = currentIndex }
                    }
                    Column { width: (transferForm.width - (transferForm.columns - 1) * 8) / transferForm.columns; spacing: 3
                        Label { colorKey: "ui.NetworkDashboard.30"; text: "Belopp · GG-LAB"; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10 }
                        CryptoField { property string uiColorScope: "ui.widget.NetworkDashboard.CryptoField.27"; id: amount; objectName: "networkAmount"; width: (parent ? parent.width : 0); height: 24; text: "1"; maximumLength: 25; enabled: root.canAct && root.labReady; Accessible.name: "Exakt GG-LAB-belopp, högst sex decimaler"; inputMethodHints: Qt.ImhFormattedNumbersOnly }
                    }
                    Column { width: (transferForm.width - (transferForm.columns - 1) * 8) / transferForm.columns; spacing: 3
                        Label { colorKey: "ui.NetworkDashboard.31"; text: "Testavgift 0.001 GG-LAB"; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 9 }
                        NetworkAction { property string uiColorScope: "ui.control.NetworkDashboard.16"; objectName: "networkQueueTransfer"; width: (parent ? parent.width : 0); text: "Köa överföring"; enabled: root.canAct && root.labReady && sender.currentIndex >= 0 && recipient.currentIndex >= 0 && sender.currentIndex !== recipient.currentIndex && /^(?:0|[1-9]\d*)(?:\.\d{1,6})?$/.test(amount.text.trim()) && /[1-9]/.test(amount.text) && Number(root.lab.pending || 0) < Number((root.dashboard.limits || {}).pending || 64); onClicked: root.run("lab_send", { sender: sender.currentIndex, recipient: recipient.currentIndex, amount: amount.text.trim() }) }
                    }
                }
                Label { colorKey: "ui.NetworkDashboard.32"; width: (parent ? parent.width : 0); visible: root.lab.state === "SEALED_SESSION" || (root.labReady && sender.currentIndex === recipient.currentIndex); text: root.lab.state === "SEALED_SESSION" ? "Sessionen är förseglad. Historiken kan läsas och verifieras; nya signaturer kräver en ny session." : "Välj olika deltagare som avsändare och mottagare."; color: RuntimeTheme.GGTheme.accent; wrapMode:Text.NoWrap;elide:Text.ElideRight;ToolTip.visible:infoHover3.hovered;ToolTip.text:text;HoverHandler{id:infoHover3}  font.pixelSize: 10 }
            }
        historyPanel: Item {property int listPage:0;objectName:"networkHistoryBooks"
            Row {width:(parent ? parent.width : 0);height:26;spacing:4
                NetworkAction { property string uiColorScope: "ui.control.NetworkDashboard.17";text:"Kö";height:24;flat:true;checked:parent.parent.listPage===0;onClicked:parent.parent.listPage=0}
                NetworkAction { property string uiColorScope: "ui.control.NetworkDashboard.18";text:"Block";height:24;flat:true;checked:parent.parent.listPage===1;onClicked:parent.parent.listPage=1}
            }
            Column {y:26;visible:parent.listPage===0;height:Math.max(0,(parent ? parent.height : 0)-26); width: (parent ? parent.width : 0); spacing: 6
                SectionHead { property string uiColorScope: "ui.widget.NetworkDashboard.SectionHead.31"; title: "TRANSAKTIONSKÖ"; detail: String(root.lab.pending || 0) + " väntande" }
                ListView { objectName:"networkPendingList";width:(parent ? parent.width : 0);height:Math.max(0,(parent ? parent.height : 0)-78);clip:true;model:root.pendingTransactions;boundsBehavior:Flickable.StopAtBounds;ScrollBar.vertical:ScrollBar {}
 delegate:Item { required property var modelData; objectName: "networkPendingRow"; width: ListView.view.width; height: 25
                        Label { colorKey: "ui.NetworkDashboard.33"; y: 5; width: (parent ? parent.width : 0) * .42; text: "D" + (modelData.sender_index + 1) + " → D" + (modelData.recipient_index + 1) + " · nonce " + modelData.nonce; color: RuntimeTheme.GGTheme.muted; font.pixelSize: 10 }
                        Label { colorKey: "ui.NetworkDashboard.34"; x: (parent ? parent.width : 0) * .42; y: 5; width: (parent ? parent.width : 0) * .58; text: String(modelData.amount) + " GG-LAB"; horizontalAlignment: Text.AlignRight; color: RuntimeTheme.GGTheme.text; font.pixelSize: 10 }
                        Rule { property string uiColorScope: "ui.widget.NetworkDashboard.Rule.32"; anchors.bottom: parent.bottom; opacity: .5 }
                    }
}
                Label { colorKey: "ui.NetworkDashboard.35"; width: (parent ? parent.width : 0); visible: !root.pendingTransactions.length; text: Number(root.lab.pending || 0) ? "Ködetaljer inväntas från labbet." : "Ingen överföring väntar på finalisering."; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10 }
                Label { colorKey: "ui.NetworkDashboard.36"; visible: root.pendingTransactions.length > 4; text: "+ " + (root.pendingTransactions.length - 4) + " ytterligare i kön"; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10 }
                Row { width: (parent ? parent.width : 0); spacing: 10
                    NetworkAction { property string uiColorScope: "ui.control.NetworkDashboard.19"; objectName: "networkCommit"; text: "Finalisera nästa"; enabled: root.canAct && root.labReady && Number(root.lab.pending || 0) > 0 && root.hasQuorum; onClicked: root.run("lab_commit", {}) }
                    Label { colorKey: "ui.NetworkDashboard.37"; width: Math.max(0, (parent ? parent.width : 0) - 150); height: 28; verticalAlignment: Text.AlignVCenter; text: root.hasSession && !root.hasQuorum ? "Väntar på " + Math.max(0, root.requiredCount - root.enabledCount) + " signaturaktivering" : "Kräver 3 av 4 signaturer"; color: root.hasQuorum ? RuntimeTheme.GGTheme.dim : RuntimeTheme.GGTheme.accent; font.pixelSize: 10; wrapMode:Text.NoWrap;elide:Text.ElideRight;ToolTip.visible:infoHover4.hovered;ToolTip.text:text;HoverHandler{id:infoHover4} }
                }
            }
Column {y:26;visible:parent.listPage===1;height:Math.max(0,(parent ? parent.height : 0)-26); width: (parent ? parent.width : 0); spacing: 0
                SectionHead { property string uiColorScope: "ui.widget.NetworkDashboard.SectionHead.34"; title: "SENASTE FINALISERADE BLOCK"; detail: String(root.recentBlocks.length) + " visas" }
                ListView { objectName:"networkBlocksList";width:(parent ? parent.width : 0);height:Math.max(0,(parent ? parent.height : 0)-30);clip:true;model:root.recentBlocks;boundsBehavior:Flickable.StopAtBounds;ScrollBar.vertical:ScrollBar {}
 delegate:Item { required property var modelData; objectName: "networkBlockRow"; width: ListView.view.width; height: 29
                        Label { colorKey: "ui.NetworkDashboard.38"; y: 8; width: 54; text: "#" + modelData.height; color: RuntimeTheme.GGTheme.accent; font.pixelSize: 10 }
                        Label { colorKey: "ui.NetworkDashboard.39"; x: 56; y: 8; width: Math.max(0, (parent ? parent.width : 0) - 210); text: "D" + (modelData.sender_index + 1) + " → D" + (modelData.recipient_index + 1) + " · " + String(modelData.amount) + " GG-LAB"; color: RuntimeTheme.GGTheme.text; font.pixelSize: 10 }
                        Label { colorKey: "ui.NetworkDashboard.40"; anchors.right: parent.right; y: 8; text: String(modelData.signatures) + " signaturer"; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10 }
                        Rule { property string uiColorScope: "ui.widget.NetworkDashboard.Rule.35"; anchors.bottom: parent.bottom; opacity: .5 }
                    }
}
                Label { colorKey: "ui.NetworkDashboard.41"; width: (parent ? parent.width : 0); visible: !root.recentBlocks.length; topPadding: 12; text: "Inga finaliserade block i denna session."; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10 }
            }
        }
    }

    Component {
        id: telemetryComponent
        Item {
            id: telemetry; objectName: "networkTelemetry"
            Rectangle { width: 1; height: (parent ? parent.height : 0); color: RuntimeTheme.GGTheme.line; visible: root.railVisible }
            NetworkRailLayout { property string uiColorScope: "ui.widget.NetworkDashboard.NetworkRailLayout.36";
        id:telemetryScroll;objectName:"networkTelemetryScroll";prefix:"network"
        x:12;y:6;width:Math.max(0,(parent ? parent.width : 0)-24);height:Math.max(0,(parent ? parent.height : 0)-12)
        titles:["SESSION & BEVIS", "NODPROFIL", "AVGIFTSFÖRDELNING", "LOKAL WEBBVERIFIERARE", "ANSLUTNINGAR"]
        sections:[Column { width: (parent ? parent.width : 0); spacing: 0
                        SectionHead { property string uiColorScope: "ui.widget.NetworkDashboard.SectionHead.37"; title: "SESSION & BEVIS"; detail: root.labReady ? "RAM" : "" }
                        Fact { property string uiColorScope: "ui.widget.NetworkDashboard.Fact.38"; name: "Miljö"; value: "En lokal process" }
                        Fact { property string uiColorScope: "ui.widget.NetworkDashboard.Fact.39"; name: "Historik"; value: root.verification.state === "VERIFIED" ? "Verifierad" : root.verification.state === "INVALID" ? "Ogiltig" : "Ej verifierad"; valueColor: root.verification.state === "VERIFIED" ? RuntimeTheme.GGTheme.positive : root.verification.state === "INVALID" ? RuntimeTheme.GGTheme.negative : RuntimeTheme.GGTheme.dim }
                        Fact { property string uiColorScope: "ui.widget.NetworkDashboard.Fact.40"; name: "Signaturer"; value: "Ed25519 · 3 av 4" }
                        Fact { property string uiColorScope: "ui.widget.NetworkDashboard.Fact.41"; name: "Tillståndsbevis"; value: "Merklemedlemskap" }
                        Fact { property string uiColorScope: "ui.widget.NetworkDashboard.Fact.42"; name: "Nycklar"; value: root.labReady ? "Endast denna process" : root.hasSession ? "Förseglade" : "Inte skapade"; valueColor: root.labReady ? RuntimeTheme.GGTheme.positive : RuntimeTheme.GGTheme.dim }
                        Fact { property string uiColorScope: "ui.widget.NetworkDashboard.Fact.43"; name: "Tillgångsbalans"; value: root.conservation.state === "BALANCED" ? "Bevarad" : root.conservation.state === "INVALID" ? "Avvikelse" : "Ej kontrollerad"; valueColor: root.conservation.state === "BALANCED" ? RuntimeTheme.GGTheme.positive : root.conservation.state === "INVALID" ? RuntimeTheme.GGTheme.negative : RuntimeTheme.GGTheme.dim }
                        Fact { property string uiColorScope: "ui.widget.NetworkDashboard.Fact.44"; name: "Nätverks-ID"; value: root.hasSession ? root.shortAddress(root.lab.chain_id) : "Inte skapat" }
                        Label { colorKey: "ui.NetworkDashboard.42"; visible:false; width: (parent ? parent.width : 0); topPadding: 8; text: "Labb för signerad huvudbok och felhantering. Distribuerad konsensus och SNARK-bevis ingår inte."; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10; wrapMode:Text.NoWrap;elide:Text.ElideRight;ToolTip.visible:infoHover5.hovered;ToolTip.text:text;HoverHandler{id:infoHover5} }
                    },
Column { width: (parent ? parent.width : 0); spacing: 2
                        SectionHead { property string uiColorScope: "ui.widget.NetworkDashboard.SectionHead.45"; title: "NODPROFIL"; detail: "lokalt" }
                        Label { colorKey: "ui.NetworkDashboard.43"; text: "Enhetens resursprofil"; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10 }
                        CryptoPick { property string uiColorScope: "ui.control.NetworkDashboard.20"; id: preset; objectName: "networkPreset"; width: (parent ? parent.width : 0); height: 28; model: ["mobile", "radio", "desktop", "server"]; currentIndex: Math.max(0, model.indexOf((root.lab.config || {}).preset || "mobile")); enabled: root.canAct && root.labReady; Accessible.name: "Enhetens resursprofil"; onActivated: root.run("configure_lab", { preset: currentText }) }
                        Label { colorKey: "ui.NetworkDashboard.44"; text: "Bidragsroll"; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10 }
                        CryptoPick { property string uiColorScope: "ui.control.NetworkDashboard.21"; id: role; objectName: "networkRole"; width: (parent ? parent.width : 0); height: 28; model: ["light", "relay", "archive", "validator", "gateway"]; currentIndex: Math.max(0, model.indexOf((root.lab.config || {}).role || "light")); enabled: root.canAct && root.labReady; Accessible.name: "Bidragsroll i lokalt labb"; onActivated: root.run("configure_lab", { role: currentText }) }
                        CryptoToggle { property string uiColorScope: "ui.control.NetworkDashboard.22"; objectName: "networkParticipating"; width: (parent ? parent.width : 0); text: root.lab.participating ? "Lokalt deltagande på" : "Lokalt deltagande pausat"; checked: root.lab.participating === true; enabled: root.canAct && root.labReady; onClicked: root.run("configure_lab", { participating: checked }) }
                        Label { colorKey: "ui.NetworkDashboard.45"; visible:false; width: (parent ? parent.width : 0); text: "Profilen styr labbets transportbudget. Rollval startar inga separata tjänster eller belöningar."; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10; wrapMode:Text.NoWrap;elide:Text.ElideRight;ToolTip.visible:infoHover6.hovered;ToolTip.text:text;HoverHandler{id:infoHover6} }
                    },
Column { width: (parent ? parent.width : 0); spacing: 2
                        SectionHead { property string uiColorScope: "ui.widget.NetworkDashboard.SectionHead.49"; title: "AVGIFTSFÖRDELNING"; detail: "testscenario" }
                        CryptoPick { property string uiColorScope: "ui.control.NetworkDashboard.23"; objectName: "networkEconomics"; width: (parent ? parent.width : 0); height: 28; model: ["Bidragspool 100 %", "Burn 20 % · bidrag 80 %", "Burn 10 · innehav 20 · bidrag 70 %"]
                            currentIndex: { var e = root.lab.economics || {}; return e.burn_bps === 0 && e.holder_bps === 0 && e.contributor_bps === 10000 ? 0 : e.burn_bps === 2000 && e.holder_bps === 0 && e.contributor_bps === 8000 ? 1 : e.burn_bps === 1000 && e.holder_bps === 2000 && e.contributor_bps === 7000 ? 2 : -1 }
                            enabled: root.canAct && root.labReady; Accessible.name: "Ekonomiskt testscenario"; onActivated: root.run("configure_lab", { economics: currentIndex === 0 ? { burn_bps: 0, holder_bps: 0, contributor_bps: 10000 } : currentIndex === 1 ? { burn_bps: 2000, holder_bps: 0, contributor_bps: 8000 } : { burn_bps: 1000, holder_bps: 2000, contributor_bps: 7000 } })
                        }
                        Row { width: (parent ? parent.width : 0); height: 5
                            Rectangle { width: (parent ? parent.width : 0) * Number((root.lab.economics || {}).burn_bps || 0) / 10000; height: 5; color: RuntimeTheme.GGTheme.negative }
                            Rectangle { width: (parent ? parent.width : 0) * Number((root.lab.economics || {}).holder_bps || 0) / 10000; height: 5; color: RuntimeTheme.GGTheme.muted }
                            Rectangle { width: (parent ? parent.width : 0) * Number((root.lab.economics || {}).contributor_bps || 0) / 10000; height: 5; color: RuntimeTheme.GGTheme.accent }
                        }
                        Fact { property string uiColorScope: "ui.widget.NetworkDashboard.Fact.51"; name: "Burn / innehavare"; value: root.percentage((root.lab.economics || {}).burn_bps) + " / " + root.percentage((root.lab.economics || {}).holder_bps) }
                        Fact { property string uiColorScope: "ui.widget.NetworkDashboard.Fact.52"; name: "Bränt · GG-LAB"; value: root.atomicText(root.conservation.burned_atomic === undefined ? root.lab.burned : root.conservation.burned_atomic) }
                        Fact { property string uiColorScope: "ui.widget.NetworkDashboard.Fact.53"; name: "Bidragspool"; value: root.atomicText(root.conservation.contributor_pool_atomic === undefined ? root.lab.contributor_pool : root.conservation.contributor_pool_atomic) + " GG-LAB" }
                        Label { colorKey: "ui.NetworkDashboard.46"; visible:false; width: (parent ? parent.width : 0); text: "Endast betalda testavgifter fördelas. Inga automatiska uttag eller utlovad avkastning."; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10; wrapMode:Text.NoWrap;elide:Text.ElideRight;ToolTip.visible:infoHover7.hovered;ToolTip.text:text;HoverHandler{id:infoHover7} }
                    },
Column { width: (parent ? parent.width : 0); spacing: 2
                        SectionHead { property string uiColorScope: "ui.widget.NetworkDashboard.SectionHead.54"; title: "LOKAL WEBBVERIFIERARE"; detail: root.webNode.state === "RUNNING" ? "på" : "av" }
                        Fact { property string uiColorScope: "ui.widget.NetworkDashboard.Fact.55"; name: "Status"; value: root.webNode.state === "RUNNING" ? "Startad · loopback" : "Stoppad"; valueColor: root.webNode.state === "RUNNING" ? RuntimeTheme.GGTheme.positive : RuntimeTheme.GGTheme.dim }
                        Fact { property string uiColorScope: "ui.widget.NetworkDashboard.Fact.56"; name: "Signernyckel"; value: "Ingen i webbvyn" }
                        Flow { width: (parent ? parent.width : 0); spacing: 6
                            NetworkAction { property string uiColorScope: "ui.control.NetworkDashboard.24"; objectName: "networkPrepareWeb"; text: "Förbered paket"; enabled: root.canAct && root.labReady; onClicked: root.run("prepare_web_sample", {}) }
                            NetworkAction { property string uiColorScope: "ui.control.NetworkDashboard.25"; objectName: "networkCopyWeb"; text: "Kopiera"; enabled: root.canAct && !!root.state.web_sample; onClicked: root.copySample() }
                            NetworkAction { property string uiColorScope: "ui.control.NetworkDashboard.26"; objectName: "networkStartWeb"; text: "Starta webb"; enabled: root.canAct && root.webNode.state !== "RUNNING"; onClicked: root.run("start_web_node", {}) }
                            NetworkAction { property string uiColorScope: "ui.control.NetworkDashboard.27"; objectName: "networkStopWeb"; text: "Stoppa"; enabled: root.canAct && root.webNode.state === "RUNNING"; onClicked: root.run("stop_web_node", {}) }
                            NetworkAction { property string uiColorScope: "ui.control.NetworkDashboard.28"; objectName: "networkOpenWeb"; text: "Öppna ↗"; enabled: root.webNode.state === "RUNNING"; onClicked: root.openWeb() }
                        }
                        Label { colorKey: "ui.NetworkDashboard.47"; visible:false; width: (parent ? parent.width : 0); text: "Kopiera testpaketet till webbvyn för lokal verifiering. Efter nästa block behövs ett nytt paket."; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10; wrapMode:Text.NoWrap;elide:Text.ElideRight;ToolTip.visible:infoHover8.hovered;ToolTip.text:text;HoverHandler{id:infoHover8} }
                    },
Column { width: (parent ? parent.width : 0); spacing: 0
                        SectionHead { property string uiColorScope: "ui.widget.NetworkDashboard.SectionHead.62"; title: "ANSLUTNINGAR" }
                        Fact { property string uiColorScope: "ui.widget.NetworkDashboard.Fact.63"; name: "Extern peertransport"; value: "Inte ansluten"; valueColor: RuntimeTheme.GGTheme.dim }
                        Fact { property string uiColorScope: "ui.widget.NetworkDashboard.Fact.64"; name: "Brygga mellan kedjor"; value: "Inte konfigurerad"; valueColor: RuntimeTheme.GGTheme.dim }
                        Label { colorKey: "ui.NetworkDashboard.48"; visible:false; width: (parent ? parent.width : 0); topPadding: 8; text: "Publika tillgångar och saldokällor hanteras separat i kontoöversikten."; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10; wrapMode:Text.NoWrap;elide:Text.ElideRight;ToolTip.visible:infoHover9.hovered;ToolTip.text:text;HoverHandler{id:infoHover9} }
                    }
            ]
        eventsPanel:Column { width: (parent ? parent.width : 0); spacing: 3
                        SectionHead { property string uiColorScope: "ui.widget.NetworkDashboard.SectionHead.65"; title: "HÄNDELSER"; detail: "labb · nod · transport" }
                        ListView { objectName:"networkEventsList";width:(parent ? parent.width : 0);height:Math.max(0,(parent ? parent.height : 0)-40);clip:true;model:root.events;boundsBehavior:Flickable.StopAtBounds;ScrollBar.vertical:ScrollBar {}
 delegate:Column { required property var modelData; objectName: "networkEventRow"; width: ListView.view.width; spacing: 5
                                Item { width: (parent ? parent.width : 0); height: 13
                                    Rectangle { x: 0; y: 4; width: 5; height: 5; radius: 3; color: root.eventColor(modelData.kind) }
                                    Label { colorKey: "ui.NetworkDashboard.49"; x: 12; width: 58; text: root.timeText(modelData.ts); color: RuntimeTheme.GGTheme.dim; font.pixelSize: 9 }
                                    Label { colorKey: "ui.NetworkDashboard.50"; x: 76; width: Math.max(0, (parent ? parent.width : 0) - x); text: String(modelData.kind || "").replace(/_/g, " "); color: root.eventColor(modelData.kind); font.pixelSize: 9 }
                                }
                                Label { colorKey: "ui.NetworkDashboard.51"; x: 12; width: (parent ? parent.width : 0) - 12; text: modelData.message || ""; color: RuntimeTheme.GGTheme.muted; font.pixelSize: 9; wrapMode: Text.NoWrap; elide: Text.ElideRight }
                            }
}
                        Label { colorKey: "ui.NetworkDashboard.52"; width: (parent ? parent.width : 0); visible: !root.events.length; text: "Inga nätverkshändelser registrerade."; color: RuntimeTheme.GGTheme.dim; font.pixelSize: 10; wrapMode:Text.NoWrap;elide:Text.ElideRight;ToolTip.visible:infoHover11.hovered;ToolTip.text:text;HoverHandler{id:infoHover11} }
                    }
    }
        }
    }
    Loader { id: rail; x: root.mainWidth; y: toolbar.height; width: root.railWidth; height: Math.max(0, root.height - y); active: root.railVisible; visible: active; sourceComponent: telemetryComponent }
    Popup {
        id: factsDrawer; objectName: "networkFactsDrawer"; x: Math.max(0, root.width - width); y: toolbar.height; width: Math.min(360, root.width); height: Math.max(0, root.height - y); padding: 0; modal: true; focus: true; closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { color: RuntimeTheme.GGTheme.base; LedgerBorder { property string uiColorScope: "ui.widget.NetworkDashboard.LedgerBorder.66"; anchors.fill: parent; color: RuntimeTheme.GGTheme.edge; radius: 0 } }
        contentItem: Item {
            NetworkAction { property string uiColorScope: "ui.control.NetworkDashboard.29"; anchors.right: parent.right; anchors.rightMargin: 8; y: 2; height: 28; width: 28; text: "×"; enabled: true; tip: "Stäng nätverkspanelen"; Accessible.name: tip; onClicked: factsDrawer.close() }
            Loader { y: 30; width: (parent ? parent.width : 0); height: Math.max(0, (parent ? parent.height : 0) - y); active: factsDrawer.visible; sourceComponent: telemetryComponent }
        }
    }
    Menu {
        id: advancedMenu; objectName: "networkAdvancedMenu"; x: Math.max(0, root.width - width - 12); y: toolbar.height; width: Math.min(250, root.width - 24)
        NetworkMenuItem { property string uiColorScope: "ui.widget.NetworkDashboard.NetworkMenuItem.68"; text: "GG TESTNÄT"; onTriggered: root.pageRequested("TESTNET") }
        NetworkMenuItem { property string uiColorScope: "ui.widget.NetworkDashboard.NetworkMenuItem.69"; text: "SIGNERAT LABB"; enabled: false }
        MenuSeparator {}
        NetworkMenuItem { property string uiColorScope: "ui.widget.NetworkDashboard.NetworkMenuItem.70"; text: root.detailsVisible ? "Dölj sidopanel" : "Visa sidopanel"; onTriggered: root.toggleDetails() }
        MenuSeparator {}
        NetworkMenuItem { property string uiColorScope: "ui.widget.NetworkDashboard.NetworkMenuItem.71"; text: "Konton & tillgångar"; onTriggered: root.pageRequested("WALLET") }
        NetworkMenuItem { property string uiColorScope: "ui.widget.NetworkDashboard.NetworkMenuItem.72"; text: "NFT-inspektör"; onTriggered: root.pageRequested("NFT") }
        NetworkMenuItem { property string uiColorScope: "ui.widget.NetworkDashboard.NetworkMenuItem.73"; text: "Paperbotar"; onTriggered: root.pageRequested("BOTS") }
        NetworkMenuItem { property string uiColorScope: "ui.widget.NetworkDashboard.NetworkMenuItem.74"; text: "Alla händelser"; onTriggered: root.pageRequested("ACTIVITY") }
        background: Rectangle { color: RuntimeTheme.GGTheme.panel; border.color: RuntimeTheme.GGTheme.edge }
    }
    Popup {
        id: sessionConfirm; objectName: "networkSessionConfirm"; x: Math.max(8, (root.width - width) / 2); y: 52; width: Math.min(390, root.width - 16); padding: 16; modal: true; focus: true; closePolicy: Popup.CloseOnEscape
        background: Rectangle { color: RuntimeTheme.GGTheme.panel; LedgerBorder { property string uiColorScope: "ui.widget.NetworkDashboard.LedgerBorder.75"; anchors.fill: parent; color: RuntimeTheme.GGTheme.edge; radius: 2 } }
        contentItem: Column { width: (parent ? parent.width : 0); spacing: 4
            Label { colorKey: "ui.NetworkDashboard.53"; width: (parent ? parent.width : 0); text: "Skapa en separat labbsession?"; color: RuntimeTheme.GGTheme.bright; font.pixelSize: 13; wrapMode:Text.NoWrap;elide:Text.ElideRight;ToolTip.visible:infoHover12.hovered;ToolTip.text:text;HoverHandler{id:infoHover12} }
            Label { colorKey: "ui.NetworkDashboard.54"; width: (parent ? parent.width : 0); text: "Nuvarande historik arkiveras. Dess signernycklar finns bara i RAM och ersätts, så den gamla sessionen kan därefter enbart verifieras. Fyra nya deltagare får lika testtilldelning."; wrapMode:Text.NoWrap;elide:Text.ElideRight;ToolTip.visible:infoHover13.hovered;ToolTip.text:text;HoverHandler{id:infoHover13}  color: RuntimeTheme.GGTheme.muted }
            Row { spacing: 8
                NetworkAction { property string uiColorScope: "ui.control.NetworkDashboard.30"; objectName: "networkConfirmNewSession"; text: "Skapa ny session"; onClicked: { sessionConfirm.close(); root.run("create_lab", {}) } }
                NetworkAction { property string uiColorScope: "ui.control.NetworkDashboard.31"; text: "Avbryt"; enabled: true; onClicked: sessionConfirm.close() }
            }
        }
    }

}


