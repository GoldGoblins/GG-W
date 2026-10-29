
import "." as RuntimeTheme
import QtQuick
import "CryptoPortfolioFormat.js" as Format

Item {
    id: summary
    property var snapshot: ({})
    property bool compact:false
    property string symbol: "SOL"
    property string mode: "SIMULERAT · LOCALNET"
    property string quantity: ""
    property string quoteCurrency: "USD"
    readonly property bool quantityKnown: /^[0-9]+(?:\.[0-9]+)?$/.test(quantity)
    readonly property bool changeKnown: snapshot.change_24h_pct !== null
        && snapshot.change_24h_pct !== undefined && isFinite(Number(snapshot.change_24h_pct))
    readonly property color changeColor: !changeKnown ? RuntimeTheme.GGTheme.dim
        : Number(snapshot.change_24h_pct) >= 0 ? RuntimeTheme.GGTheme.positive : RuntimeTheme.GGTheme.negative
    readonly property int totalAssets: (snapshot.assets || []).length
    readonly property bool partial: totalAssets > 0 && snapshot.complete !== true
    height: compact ? 74 : 108

    GgFrame { property string uiColorScope: "ui.widget.CryptoPortfolioSummary.GgFrame.1";
        anchors.fill: parent
        leftLegend: "PORTFÖLJ"
        rightLegend: summary.symbol
        backgroundColor: RuntimeTheme.GGTheme.panel
        borderColor: RuntimeTheme.GGTheme.edge
        radius: 4
    }
    Column {
        x: 12; y: summary.compact ? 7 : 12; width: parent.width * 0.53 - 30; spacing: summary.compact ? 3 : 6
        GGText { colorKey: "ui.CryptoPortfolioSummary.1";
            width: parent.width
            text: summary.partial ? "VÄRDERAT INNEHAV · DELVIS" : "PORTFÖLJVÄRDE"
            color: RuntimeTheme.GGTheme.text; font.family: "monospace"; font.pixelSize: 10; font.letterSpacing: 0.6
            elide: Text.ElideRight; textFormat: Text.PlainText
        }
        GGText { colorKey: "ui.CryptoPortfolioSummary.2";
            objectName: "portfolioTotalValue"
            width: parent.width
            text: Format.money(summary.snapshot.value_usd, "USD", false)
            color: RuntimeTheme.GGTheme.bright; font.family: "monospace"; font.pixelSize: summary.width < 550 ? 20 : 22
            font.bold: true; elide: Text.ElideRight; textFormat: Text.PlainText
        }
        GGText { colorKey: "ui.CryptoPortfolioSummary.3";
            width: parent.width
            text: (summary.snapshot.value_sek !== null && summary.snapshot.value_sek !== undefined
                ? Format.money(summary.snapshot.value_sek, "SEK", false) + " · " : "")
                + String(summary.snapshot.valued_count || 0) + "/" + summary.totalAssets + " värderade"
            color: summary.partial ? RuntimeTheme.GGTheme.accent : RuntimeTheme.GGTheme.dim
            font.family: "monospace"; font.pixelSize: 10; elide: Text.ElideRight; textFormat: Text.PlainText
        }
        GGText { colorKey: "ui.CryptoPortfolioSummary.4";
            width: parent.width
            visible:!summary.compact
            text: summary.mode + (summary.snapshot.stale_count > 0 ? " · ÄLDRE PRIS" : "")
            color: RuntimeTheme.GGTheme.dim; font.family: "monospace"; font.pixelSize: 9
            elide: Text.ElideRight; textFormat: Text.PlainText
        }
    }
    Rectangle {
        x: parent.width * 0.53; y: 14; width: 1; height: parent.height - 28; color: RuntimeTheme.GGTheme.edge
    }
    Column {
        x: parent.width * 0.53 + 12; y: summary.compact ? 7 : 12; width: parent.width * 0.47 - 30; spacing: summary.compact ? 3 : 6
        GGText { colorKey: "ui.CryptoPortfolioSummary.5";
            width: parent.width
            text: summary.symbol + (summary.quoteCurrency === "USDT" ? " / USDT ≈ USD" : " / USD")
            color: RuntimeTheme.GGTheme.dim; font.family: "monospace"; font.pixelSize: 10; font.letterSpacing: 0.6
            elide: Text.ElideRight; textFormat: Text.PlainText
        }
        GGText { colorKey: "ui.CryptoPortfolioSummary.6";
            width: parent.width
            text: Format.money(summary.snapshot.price_usd, "USD", true)
            color: RuntimeTheme.GGTheme.bright; font.family: "monospace"; font.pixelSize: summary.width < 550 ? 20 : 22
            font.bold: true; elide: Text.ElideRight; textFormat: Text.PlainText
        }
        GGText { colorKey: "ui.CryptoPortfolioSummary.7";
            width: parent.width
            text: Format.percent(summary.snapshot.change_24h_pct) + "  ·  24h prisförändring"
            color: summary.changeColor; font.family: "monospace"; font.pixelSize: 10
            elide: Text.ElideRight; textFormat: Text.PlainText
        }
        GGText { colorKey: "ui.CryptoPortfolioSummary.8";
            width: parent.width
            visible:!summary.compact
            text: summary.quantityKnown ? Format.quantity(summary.quantity) + " " + summary.symbol + " i innehav" : "Innehav saknas"
            color: RuntimeTheme.GGTheme.dim; font.family: "monospace"; font.pixelSize: 9
            elide: Text.ElideRight; textFormat: Text.PlainText
        }
    }
}
