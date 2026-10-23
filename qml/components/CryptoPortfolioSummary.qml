import QtQuick
import "CryptoPortfolioFormat.js" as Format

Item {
    id: summary
    property var snapshot: ({})
    property string symbol: "SOL"
    property string mode: "SIMULERAT · LOCALNET"
    property string quantity: ""
    height: 92
    Rectangle {
        anchors.fill: parent
        color: "#1d1d1d"
        border.color: "#353535"
        radius: 5
    }
    Column {
        anchors.left: parent.left
        anchors.leftMargin: 14
        anchors.top: parent.top
        anchors.topMargin: 9
        width: parent.width * 0.55 - 24
        spacing: 3
        Text {
            width: parent.width
            text: summary.snapshot.complete || !(summary.snapshot.assets || []).length ? "INNEHAV · " + summary.mode : "VÄRDERAD DEL · " + summary.mode
            color: "#c8a97e"; font.family: "monospace"; font.pixelSize: 10
            elide: Text.ElideRight
        }
        Text {
            objectName: "portfolioTotalValue"
            width: parent.width
            text: Format.money(summary.snapshot.value_usd, "USD", false)
            color: "#e6edf3"; font.family: "monospace"; font.pixelSize: summary.width < 550 ? 23 : 27; font.bold: true
            elide: Text.ElideRight
        }
        Text {
            width: parent.width
            text: (summary.snapshot.value_sek !== null && summary.snapshot.value_sek !== undefined ? Format.money(summary.snapshot.value_sek, "SEK", false) + " · " : "")
                + String(summary.snapshot.valued_count || 0) + "/" + String((summary.snapshot.assets || []).length) + " värderade"
                + (summary.snapshot.stale_count > 0 ? " · äldre pris" : "")
            color: "#8b949e"; font.family: "monospace"; font.pixelSize: 11
            elide: Text.ElideRight
        }
    }
    Rectangle {
        x: parent.width * 0.55
        y: 12; width: 1; height: parent.height - 24; color: "#353535"
    }
    Column {
        x: parent.width * 0.55 + 14
        y: 9
        width: parent.width * 0.45 - 28
        spacing: 3
        Text {
            width: parent.width; elide: Text.ElideRight
            text: summary.symbol + " · MARKNADSPRIS / TOKEN"
            color: "#8b949e"; font.family: "monospace"; font.pixelSize: 10
        }
        Row {
            spacing: 12
            Text {
                text: Format.money(summary.snapshot.price_usd, "USD", true)
                color: "#e6edf3"; font.family: "monospace"; font.pixelSize: summary.width < 550 ? 20 : 25; font.bold: true
            }
            Text {
                visible: summary.width >= 680
                anchors.verticalCenter: parent.verticalCenter
                text: Format.percent(summary.snapshot.change_24h_pct) + " / 24h"
                color: summary.snapshot.change_24h_pct === null ? "#8b949e" : Number(summary.snapshot.change_24h_pct) >= 0 ? "#8db89a" : "#c98989"
                font.family: "monospace"; font.pixelSize: 12
            }
        }
        Text {
            width: parent.width
            text: summary.width < 680 ? Format.percent(summary.snapshot.change_24h_pct) + " / 24h i prisserien"
                : Format.quantity(summary.quantity) + " " + summary.symbol + " · 24h i prisserien"
            color: "#8b949e"; font.family: "monospace"; font.pixelSize: 11
            elide: Text.ElideRight
        }
    }
}
