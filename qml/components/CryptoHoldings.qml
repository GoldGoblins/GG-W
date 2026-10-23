import QtQuick
import QtQuick.Controls
import "CryptoPortfolioFormat.js" as Format

Item {
    id: table
    property var assets: []
    property string selectedSymbol: "SOL"
    signal assetSelected(string symbol)
    readonly property real priceX: width * 0.44
    readonly property real valueX: width * 0.72
    Text {
        text: "TILLGÅNGAR · " + table.assets.length
        color: "#c8a97e"; font.family: "monospace"; font.pixelSize: 11; font.bold: true
    }
    Text {
        x: table.priceX; width: table.valueX - x - 16
        text: "PRIS / 24H"
        color: "#8b949e"; font.family: "monospace"; font.pixelSize: 10
        horizontalAlignment: Text.AlignRight
    }
    Text {
        x: table.valueX; width: table.width - x - 12
        text: "VÄRDE / ANTAL"
        color: "#8b949e"; font.family: "monospace"; font.pixelSize: 10
        horizontalAlignment: Text.AlignRight
    }
    ListView {
        id: rows
        objectName: "cryptoHoldingsList"
        anchors.fill: parent
        anchors.topMargin: 24
        clip: true
        model: table.assets
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
        delegate: Rectangle {
            id: assetRow
            required property var modelData
            required property int index
            width: rows.width; height: 62
            readonly property bool selectable: String(modelData.mint) === "native" && (modelData.symbol === "SOL" || modelData.symbol === "KAS")
            readonly property bool priced: modelData.value_usd !== null && modelData.value_usd !== undefined
            color: rowMouse.containsMouse ? "#242424" : index % 2 === 0 ? "#1b1b1b" : "#181818"
            Rectangle {
                anchors.bottom: parent.bottom; width: parent.width; height: 1; color: "#303030"
            }
            Rectangle {
                x: 9; y: 16; width: 29; height: 29; radius: 15
                color: modelData.symbol === "SOL" ? "#475365" : modelData.symbol === "KAS" ? "#416b62" : "#554b3d"
                Text {
                    anchors.centerIn: parent
                    text: String(assetRow.modelData.symbol || "?").slice(0, 1)
                    font.family: "monospace"; font.pixelSize: 13; font.bold: true; color: "#e6edf3"
                }
            }
            Column {
                x: 48; y: 12; width: table.priceX - x - 12; spacing: 5
                Text {
                    width: parent.width; text: String(assetRow.modelData.name || assetRow.modelData.symbol)
                    elide: Text.ElideRight
                    color: "#e6edf3"; font.family: "monospace"; font.pixelSize: 13
                }
                Text {
                    width: parent.width; text: String(assetRow.modelData.symbol || "")
                    elide: Text.ElideRight
                    color: "#8b949e"; font.family: "monospace"; font.pixelSize: 11
                }
            }
            Column {
                x: table.priceX; y: 12; width: table.valueX - x - 16; spacing: 5
                Text {
                    width: parent.width; horizontalAlignment: Text.AlignRight
                    text: Format.money(assetRow.modelData.price_usd, "USD", true)
                    color: "#e6edf3"; font.family: "monospace"; font.pixelSize: 13
                    elide: Text.ElideRight
                }
                Text {
                    width: parent.width; horizontalAlignment: Text.AlignRight
                    text: assetRow.modelData.price_usd === null ? "Pris saknas" : Format.percent(assetRow.modelData.change_24h_pct) + (assetRow.modelData.stale ? " *" : "")
                    color: assetRow.modelData.price_usd === null || assetRow.modelData.stale ? "#c8a97e" : assetRow.modelData.change_24h_pct === null ? "#8b949e" : Number(assetRow.modelData.change_24h_pct) >= 0 ? "#8db89a" : "#c98989"
                    font.family: "monospace"; font.pixelSize: 11
                    elide: Text.ElideRight
                }
            }
            Column {
                x: table.valueX; y: 12; width: table.width - x - 12; spacing: 5
                Text {
                    width: parent.width; horizontalAlignment: Text.AlignRight
                    text: Format.money(assetRow.modelData.value_usd, "USD", false)
                    color: "#e6edf3"; font.family: "monospace"; font.pixelSize: 13
                    elide: Text.ElideRight
                }
                Text {
                    width: parent.width; horizontalAlignment: Text.AlignRight
                    text: Format.quantity(assetRow.modelData.quantity_text) + " " + String(assetRow.modelData.symbol || "")
                    color: "#8b949e"; font.family: "monospace"; font.pixelSize: 11
                    elide: Text.ElideRight
                }
            }
            MouseArea {
                id: rowMouse
                anchors.fill: parent; hoverEnabled: true
                cursorShape: assetRow.selectable ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: if (assetRow.selectable) table.assetSelected(String(assetRow.modelData.symbol))
            }
            ToolTip.visible: rowMouse.containsMouse
            ToolTip.delay: 650
            ToolTip.text: String(modelData.quantity_text) + " " + String(modelData.symbol)
                + "\n" + String(modelData.mint || "")
                + (modelData.price_source ? "\nPris: " + modelData.price_source + (modelData.stale ? " · äldre data" : "") : "\nIngen verifierad prisdata")
        }
    }
    Text {
        anchors.centerIn: rows
        visible: table.assets.length === 0
        text: "Anslut en plånbok för att se dina tillgångar."
        width: rows.width; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter
        color: "#8b949e"; font.family: "monospace"; font.pixelSize: 12
    }
}
