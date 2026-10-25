import QtQuick
import QtQuick.Controls

Column {
    id: panel
    property var engine: ({})
    property var surfaceHost: null
    property bool canStart: true
    property bool busy: false
    signal statusChanged(string json)
    spacing: 10
    function number(value, digits) {
        if (value === null || value === undefined || !isFinite(Number(value))) return "—"
        return Number(value).toLocaleString(Qt.locale("sv_SE"), "f", digits)
    }
    function statusLabel(status) {
        return ({"RUNNING":"KÖR", "WAITING_FOR_CLOSED_BAR":"VÄNTAR PÅ STÄNGT LJUS", "IDLE":"EJ STARTAD", "PAUSED":"PAUSAD", "DATA_ERROR":"DATA SAKNAS", "ERROR":"FEL", "GAP":"LUCKA I HISTORIKEN", "RISK_HALT":"RISKSTOPP"})[status] || String(status)
    }
    component PaperButton: CryptoButton {}
    Text {
        width: parent.width
        text: "PAPPERSKONTON  /  " + String(panel.engine.base_asset || "SOL") + "/USDT"
        color: "#e6edf3"; font.family: "monospace"; font.pixelSize: 12; font.bold: true
        wrapMode: Text.WordWrap; textFormat: Text.PlainText
    }
    Flow {
        width: parent.width; spacing: 8
        Repeater {
            model: [{label:"STARTA ALLA SEX", enabled:true}, {label:"PAUSA ALLA", enabled:false}]
            delegate: PaperButton {
                required property var modelData
                text: modelData.label
                enabled: !panel.busy && (!modelData.enabled || panel.canStart)
                onClicked: {
                    if (panel.surfaceHost && panel.surfaceHost.cryptoPaperAll)
                        panel.statusChanged(panel.surfaceHost.cryptoPaperAll(modelData.enabled))
                }
            }
        }
    }
    Text {
        width: parent.width
        text: panel.engine.error ? String(panel.engine.error) : "Sex separata konton · 200 USDT simulerat startkapital per konto · "
            + String(panel.engine.primary || "1h") + " ljusintervall"
        color: panel.engine.error ? "#c98989" : "#8b949e"; font.family: "monospace"; font.pixelSize: 11
        wrapMode: Text.WordWrap; textFormat: Text.PlainText
    }
    Repeater {
        model: panel.engine.accounts || []
        delegate: Item {
            id: accountCard
            required property var modelData
            readonly property string runState: String(modelData.status || "IDLE")
            readonly property bool trouble: !!(modelData.error || modelData.halt_reason)
            width: panel.width; height: accountBody.height + 32
            GgFrame {
                anchors.fill: parent
                leftLegend: String(accountCard.modelData.name || accountCard.modelData.book || "Konto")
                backgroundColor: "#161616"; borderColor: "#6a6a6a"
                radius: 4
            }
            Column {
                id: accountBody; x: 12; y: 20; width: parent.width - 24; spacing: 9
                Text {
                    width: parent.width
                    text: panel.statusLabel(accountCard.runState)
                    color: accountCard.trouble ? "#c98989" : accountCard.modelData.enabled ? "#8db89a" : "#8b949e"
                    font.family: "monospace"; font.pixelSize: 10; wrapMode: Text.WordWrap; textFormat: Text.PlainText
                }
                Rectangle { width: parent.width; height: 1; color: "#303030" }
                Flow {
                    id: metrics; width: parent.width; spacing: 8
                    Repeater {
                        model: [
                            {label:"KONTOVÄRDE", value:panel.number(accountCard.modelData.equity_quote, 2), unit:"USDT"},
                            {label:"RESULTAT", value:panel.number(accountCard.modelData.pnl_quote, 2), unit:"USDT", pnl:true},
                            {label:"INNEHAV", value:panel.number(accountCard.modelData.tokens, 6), unit:String(panel.engine.base_asset || "SOL")},
                            {label:"KASSA", value:panel.number(accountCard.modelData.quote, 2), unit:"USDT"}
                        ]
                        delegate: Column {
                            required property var modelData
                            width: (metrics.width - (metrics.width >= 600 ? 24 : 8)) / (metrics.width >= 600 ? 4 : 2)
                            spacing: 4
                            Text {
                                width: parent.width; text: modelData.label
                                color: "#8b949e"; font.family: "monospace"; font.pixelSize: 9; elide: Text.ElideRight
                            }
                            Text {
                                width: parent.width; text: modelData.value
                                color: modelData.pnl && accountCard.modelData.pnl_quote !== null && accountCard.modelData.pnl_quote !== undefined
                                    && isFinite(Number(accountCard.modelData.pnl_quote))
                                    ? Number(accountCard.modelData.pnl_quote) >= 0 ? "#8db89a" : "#c98989" : "#e6edf3"
                                font.family: "monospace"; font.pixelSize: 15; font.bold: true; elide: Text.ElideRight
                            }
                            Text { text: modelData.unit; color: "#8b949e"; font.family: "monospace"; font.pixelSize: 9; textFormat: Text.PlainText }
                        }
                    }
                }
                Text {
                    width: parent.width
                    text: "Köp & behåll " + panel.number(accountCard.modelData.buy_hold_quote, 2) + " USDT"
                        + "   ·   Affärer " + String(accountCard.modelData.fills || 0)
                        + "   ·   Tokenmotsvarande " + panel.number(accountCard.modelData.token_equivalent, 6)
                        + "   ·   Återspelade ljus " + String(accountCard.modelData.recovery_bars || 0)
                        + (accountCard.modelData.processed_ts ? "\nSenaste ljus " + new Date(Number(accountCard.modelData.processed_ts) * 1000).toISOString().slice(0,16).replace("T"," ") + " UTC" : "")
                    color: "#8b949e"; font.family: "monospace"; font.pixelSize: 10; wrapMode: Text.WordWrap; textFormat: Text.PlainText
                }
                Text {
                    width: parent.width; visible: accountCard.trouble
                    text: accountCard.modelData.halt_reason ? "Riskgränsen är nådd. Återställ kontot med RESET för att börja en ny körning." : String(accountCard.modelData.error || "")
                    color: "#c98989"; font.family: "monospace"; font.pixelSize: 11; wrapMode: Text.WordWrap; textFormat: Text.PlainText
                }
            }
        }
    }
    Text {
        width: parent.width
        text: "Källa: " + String(panel.engine.source || "väntar på data")
            + " · Pris: " + panel.number(panel.engine.price, 6) + " USDT"
            + "\nInga börsorder skickas. Hypotetisk kostnad: 0,35 % per köp/sälj. Nätverksavgifter är inte uppskattade."
            + "\nRiskstopp: 20 % från högsta portföljvärde eller 5 % dagsförlust. Stopp säljer det simulerade innehavet och kräver RESET."
            + "\nKontovärde och resultat inkluderar innehavets orealiserade värde vid senaste kurs. Tokenmotsvarande räknar om hela värdet inklusive kassan. Återspelade ljus är historisk simulering."
        color: "#8b949e"; font.family: "monospace"; font.pixelSize: 10; wrapMode: Text.WordWrap; textFormat: Text.PlainText
    }
}
