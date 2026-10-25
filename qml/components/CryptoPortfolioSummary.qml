import QtQuick
import "CryptoPortfolioFormat.js" as Format

Item {
    id: summary
    property var snapshot: ({})
    property string symbol: "SOL"
    property string mode: "SIMULERAT · LOCALNET"
    property string quantity: ""
    property string quoteCurrency: "USD"
    readonly property bool quantityKnown: /^[0-9]+(?:\.[0-9]+)?$/.test(quantity)
    readonly property bool changeKnown: snapshot.change_24h_pct !== null
        && snapshot.change_24h_pct !== undefined && isFinite(Number(snapshot.change_24h_pct))
    readonly property color changeColor: !changeKnown ? "#8b949e"
        : Number(snapshot.change_24h_pct) >= 0 ? "#8db89a" : "#c98989"
    readonly property int totalAssets: (snapshot.assets || []).length
    readonly property bool partial: totalAssets > 0 && snapshot.complete !== true
    height: 108

    GgFrame {
        anchors.fill: parent
        leftLegend: "PORTFÖLJ"
        rightLegend: summary.symbol
        backgroundColor: "#161616"
        borderColor: "#6a6a6a"
        radius: 4
    }
    Column {
        x: 16; y: 12; width: parent.width * 0.53 - 30; spacing: 6
        Text {
            width: parent.width
            text: summary.partial ? "VÄRDERAT INNEHAV · DELVIS" : "PORTFÖLJVÄRDE"
            color: "#c8cdd4"; font.family: "monospace"; font.pixelSize: 10; font.letterSpacing: 0.6
            elide: Text.ElideRight; textFormat: Text.PlainText
        }
        Text {
            objectName: "portfolioTotalValue"
            width: parent.width
            text: Format.money(summary.snapshot.value_usd, "USD", false)
            color: "#e6edf3"; font.family: "monospace"; font.pixelSize: summary.width < 550 ? 20 : 22
            font.bold: true; elide: Text.ElideRight; textFormat: Text.PlainText
        }
        Text {
            width: parent.width
            text: (summary.snapshot.value_sek !== null && summary.snapshot.value_sek !== undefined
                ? Format.money(summary.snapshot.value_sek, "SEK", false) + " · " : "")
                + String(summary.snapshot.valued_count || 0) + "/" + summary.totalAssets + " värderade"
            color: summary.partial ? "#c8a97e" : "#8b949e"
            font.family: "monospace"; font.pixelSize: 10; elide: Text.ElideRight; textFormat: Text.PlainText
        }
        Text {
            width: parent.width
            text: summary.mode + (summary.snapshot.stale_count > 0 ? " · ÄLDRE PRIS" : "")
            color: "#8b949e"; font.family: "monospace"; font.pixelSize: 9
            elide: Text.ElideRight; textFormat: Text.PlainText
        }
    }
    Rectangle {
        x: parent.width * 0.53; y: 14; width: 1; height: parent.height - 28; color: "#6a6a6a"
    }
    Column {
        x: parent.width * 0.53 + 16; y: 12; width: parent.width * 0.47 - 30; spacing: 6
        Text {
            width: parent.width
            text: summary.symbol + (summary.quoteCurrency === "USDT" ? " / USDT ≈ USD" : " / USD")
            color: "#8b949e"; font.family: "monospace"; font.pixelSize: 10; font.letterSpacing: 0.6
            elide: Text.ElideRight; textFormat: Text.PlainText
        }
        Text {
            width: parent.width
            text: Format.money(summary.snapshot.price_usd, "USD", true)
            color: "#e6edf3"; font.family: "monospace"; font.pixelSize: summary.width < 550 ? 20 : 22
            font.bold: true; elide: Text.ElideRight; textFormat: Text.PlainText
        }
        Text {
            width: parent.width
            text: Format.percent(summary.snapshot.change_24h_pct) + "  ·  24h prisförändring"
            color: summary.changeColor; font.family: "monospace"; font.pixelSize: 10
            elide: Text.ElideRight; textFormat: Text.PlainText
        }
        Text {
            width: parent.width
            text: summary.quantityKnown ? Format.quantity(summary.quantity) + " " + summary.symbol + " i innehav" : "Innehav saknas"
            color: "#8b949e"; font.family: "monospace"; font.pixelSize: 9
            elide: Text.ElideRight; textFormat: Text.PlainText
        }
    }
}
