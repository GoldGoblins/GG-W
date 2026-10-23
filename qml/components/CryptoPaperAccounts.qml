import QtQuick
import QtQuick.Controls

Column {
    id: panel
    property var engine: ({})
    property var surfaceHost: null
    property bool canStart: true
    signal statusChanged(string json)
    spacing: 8
    function number(value, digits) {
        if (value === null || value === undefined || !isFinite(Number(value))) return "—"
        return Number(value).toLocaleString(Qt.locale("sv_SE"), "f", digits)
    }
    function statusLabel(status) {
        return ({"RUNNING":"KÖR", "WAITING_FOR_CLOSED_BAR":"VÄNTAR PÅ STÄNGT LJUS", "IDLE":"EJ STARTAD", "PAUSED":"PAUSAD", "DATA_ERROR":"DATA SAKNAS", "ERROR":"FEL", "GAP":"LUCKA I HISTORIKEN", "RISK_HALT":"RISKSTOPP"})[status] || String(status)
    }
    Text {
        width: parent.width
        text: "PAPPERSDRIFT · " + String(panel.engine.base_asset || "SOL") + "/USDT · " + String(panel.engine.primary || "1h")
        color: "#e6edf3"; font.pixelSize: 15; font.bold: true
    }
    Flow {
        width: parent.width; spacing: 12
        Repeater {
            model: [{label:"STARTA ALLA SEX", enabled:true}, {label:"PAUSA ALLA", enabled:false}]
            delegate: Button {
                required property var modelData
                text: modelData.label
                enabled: !modelData.enabled || panel.canStart
                onClicked: {
                    if (panel.surfaceHost && panel.surfaceHost.cryptoPaperAll)
                        panel.statusChanged(panel.surfaceHost.cryptoPaperAll(modelData.enabled))
                }
            }
        }
    }
    Text {
        width: parent.width
        text: panel.engine.error ? String(panel.engine.error) : "Varje bot har ett eget simulerat startkapital på 200 USDT. Inga börsorder skickas."
        color: panel.engine.error ? "#d98989" : "#8b949e"; font.pixelSize: 12; wrapMode: Text.WordWrap
    }
    Repeater {
        model: panel.engine.accounts || []
        delegate: Rectangle {
            required property var modelData
            width: panel.width; height: row.height + 18; radius: 4
            color: "#202020"; border.color: modelData.enabled ? "#496c58" : "#424242"
            Column {
                id: row; x: 9; y: 9; width: parent.width - 18; spacing: 4
                Text {
                    width: parent.width
                    text: String(modelData.name || modelData.book) + "  ·  " + panel.statusLabel(modelData.status || "IDLE")
                    color: modelData.enabled ? "#8db89a" : "#c8cdd4"; font.pixelSize: 13; font.bold: true; wrapMode: Text.WordWrap
                }
                Text {
                    width: parent.width
                    text: "Innehav " + panel.number(modelData.tokens, 6) + " " + String(panel.engine.base_asset || "SOL")
                        + "   ·   Kassa " + panel.number(modelData.quote, 2) + " USDT"
                        + "   ·   Totalt " + panel.number(modelData.equity_quote, 2) + " USDT"
                        + "   ·   Resultat " + panel.number(modelData.pnl_quote, 2) + " USDT"
                    color: "#d8dee9"; font.pixelSize: 12; wrapMode: Text.WordWrap
                }
                Text {
                    width: parent.width
                    text: "Köp och behåll " + panel.number(modelData.buy_hold_quote, 2) + " USDT"
                        + "   ·   Tokenmotsvarande " + panel.number(modelData.token_equivalent, 6)
                        + "   ·   Affärer " + String(modelData.fills || 0)
                        + "   ·   Återspelade ljus " + String(modelData.recovery_bars || 0)
                        + (modelData.processed_ts ? "   ·   Senaste ljus " + new Date(Number(modelData.processed_ts) * 1000).toISOString().slice(0,16).replace("T"," ") + " UTC" : "")
                    color: "#8b949e"; font.pixelSize: 11; wrapMode: Text.WordWrap
                }
                Text {
                    width: parent.width; visible: !!(modelData.error || modelData.halt_reason)
                    text: modelData.halt_reason ? "Riskgränsen är nådd. Återställ kontot med RESET för att börja en ny körning." : String(modelData.error || "")
                    color: "#d98989"; font.pixelSize: 11; wrapMode: Text.WordWrap
                }
            }
        }
    }
    Text {
        width: parent.width
        text: "Källa: " + String(panel.engine.source || "väntar på data")
            + " · Pris: " + panel.number(panel.engine.price, 6) + " USDT"
            + "\nHypotetisk kostnad: 0,35 % per köp/sälj. Nätverksavgifter är inte uppskattade."
            + "\nRiskstopp: 20 % från högsta portföljvärde eller 5 % dagsförlust. Stopp säljer det simulerade innehavet och kräver RESET."
            + "\nTotalt och resultat inkluderar innehavets orealiserade värde vid senaste kurs.\nTokenmotsvarande räknar om hela värdet inklusive kassan; det är inte antalet tokens i innehavet. Återspelade ljus efter driftavbrott är historisk simulering."
        color: "#8b949e"; font.pixelSize: 11; wrapMode: Text.WordWrap
    }
}
