import QtQuick
import QtQuick.Controls
import "CryptoPortfolioFormat.js" as Format

Item {
    id: table
    property var assets: []
    property string selectedSymbol: "SOL"
    property string filterText: ""
    property string sortMode: "default"
    property bool tokenInspectionEnabled: false
    signal assetSelected(string symbol)
    signal tokenSelected(string mint)
    readonly property real priceX: width * 0.45
    readonly property real valueX: width * 0.72
    readonly property bool compact: width < 500
    readonly property var visibleAssets: {
        var needle = table.filterText.trim().toLowerCase()
        var output = []
        for (var i = 0; i < table.assets.length; ++i) {
            var row = table.assets[i] || {}
            if (!needle || (String(row.symbol || "") + " " + String(row.name || "")
                    + " " + String(row.mint || "")).toLowerCase().indexOf(needle) >= 0)
                output.push({row: row, order: i})
        }
        if (table.sortMode === "value")
            output.sort(function(a, b) {
                var av = a.row.value_usd, bv = b.row.value_usd
                var ak = av !== null && av !== undefined && isFinite(Number(av))
                var bk = bv !== null && bv !== undefined && isFinite(Number(bv))
                if (ak !== bk) return ak ? -1 : 1
                return ak && Number(av) !== Number(bv) ? Number(bv) - Number(av) : a.order - b.order
            })
        else if (table.sortMode === "name")
            output.sort(function(a, b) {
                return String(a.row.symbol || "").localeCompare(String(b.row.symbol || "")) || a.order - b.order
            })
        return output.map(function(entry) { return entry.row })
    }

    Text {
        x: 1; y: 7; width: Math.max(80, table.width - search.width - 18)
        text: "TILLGÅNGAR  " + table.visibleAssets.length
            + (table.filterText.length ? " / " + table.assets.length : "")
        color: "#e6edf3"; font.family: "monospace"; font.pixelSize: 11; font.bold: true
        elide: Text.ElideRight; textFormat: Text.PlainText
    }
    TextField {
        id: search
        objectName: "cryptoHoldingsSearch"
        anchors.right: parent.right
        width: Math.min(210, table.width * 0.48); height: 28
        maximumLength: 256
        text: table.filterText
        onTextEdited: table.filterText = text
        placeholderText: "Sök tillgång eller mint"
        color: "#e6edf3"; placeholderTextColor: "#8b949e"; selectionColor: "#3a3a3a"
        font.family: "monospace"; font.pixelSize: 11
        leftPadding: 9; rightPadding: 24; selectByMouse: true
        Accessible.name: "Filtrera tillgångar efter namn, symbol eller mint"
        background: Rectangle { color: "#121212"; radius: 2; border.color: search.activeFocus ? "#8a8a8a" : "#6a6a6a" }
        Keys.onEscapePressed: table.filterText = ""
        ToolButton {
            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
            width: 24; height: 26; visible: search.text.length > 0
            text: "×"; font.pixelSize: 15
            Accessible.name: "Rensa tillgångsfilter"
            contentItem: Text { text: parent.text; color: "#c8cdd4"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
            background: Rectangle { color: parent.hovered || parent.activeFocus ? "#303030" : "transparent"; radius: 2 }
            onClicked: { table.filterText = ""; search.forceActiveFocus() }
        }
    }
    Item {
        y: 35; width: parent.width; height: 19
        Text {
            x: 8; width: table.priceX - 20
            text: "TILLGÅNG" + (table.sortMode === "name" ? " ↑" : "")
            color: nameSort.activeFocus ? "#e6edf3" : "#8b949e"
            font.family: "monospace"; font.pixelSize: 9; font.letterSpacing: 0.3
            elide: Text.ElideRight
        }
        MouseArea {
            id: nameSort; objectName: "cryptoHoldingsNameSort"; x: 0; width: table.priceX - 8; height: parent.height
            cursorShape: Qt.PointingHandCursor; activeFocusOnTab: true
            Accessible.role: Accessible.Button; Accessible.name: "Sortera tillgångar efter symbol"
            onClicked: table.sortMode = table.sortMode === "name" ? "default" : "name"
            Keys.onReturnPressed: clicked(null)
            Keys.onSpacePressed: clicked(null)
        }
        Text {
            x: table.priceX; width: table.valueX - x - 16
            text: "PRIS / 24H"; color: "#8b949e"; font.family: "monospace"; font.pixelSize: 9
            horizontalAlignment: Text.AlignRight
        }
        Text {
            x: table.valueX; width: table.width - x - 12
            text: "VÄRDE" + (table.sortMode === "value" ? " ↓" : "") + " / ANTAL"
            color: valueSort.activeFocus ? "#e6edf3" : "#8b949e"
            font.family: "monospace"; font.pixelSize: 9; horizontalAlignment: Text.AlignRight
            elide: Text.ElideRight
        }
        MouseArea {
            id: valueSort; objectName: "cryptoHoldingsValueSort"; x: table.valueX; width: table.width - x; height: parent.height
            cursorShape: Qt.PointingHandCursor; activeFocusOnTab: true
            Accessible.role: Accessible.Button; Accessible.name: "Sortera tillgångar efter högsta värde, okända sist"
            onClicked: table.sortMode = table.sortMode === "value" ? "default" : "value"
            Keys.onReturnPressed: clicked(null)
            Keys.onSpacePressed: clicked(null)
        }
    }
    Rectangle { y: 53; width: parent.width; height: 1; color: "#6a6a6a" }
    ListView {
        id: rows
        objectName: "cryptoHoldingsList"
        anchors.fill: parent; anchors.topMargin: 54
        clip: true; model: table.visibleAssets
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
        delegate: Rectangle {
            id: assetRow
            required property var modelData
            required property int index
            width: rows.width; height: 62
            readonly property bool nativeAsset: String(modelData.mint) === "native" && (modelData.symbol === "SOL" || modelData.symbol === "KAS")
            readonly property bool selectable: nativeAsset || (table.tokenInspectionEnabled && String(modelData.mint || "").length > 20)
            readonly property bool selected: nativeAsset && String(modelData.symbol) === table.selectedSymbol
            readonly property bool priceKnown: modelData.price_usd !== null && modelData.price_usd !== undefined
                && isFinite(Number(modelData.price_usd))
            readonly property bool changeKnown: modelData.change_24h_pct !== null && modelData.change_24h_pct !== undefined
                && isFinite(Number(modelData.change_24h_pct))
            color: rowMouse.containsMouse || rowMouse.activeFocus ? "#292c30" : selected ? "#34383d" : index % 2 === 0 ? "#1b1b1b" : "#181818"
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: "#2b2b2b" }
            Rectangle { width: 1; height: parent.height - 1; visible: assetRow.selected || rowMouse.activeFocus; color: "#8a8a8a" }
            Rectangle {
                x: 10; y: 17; width: 28; height: 28; radius: 5
                color: "#202020"
                border.color: "#6a6a6a"
                Text {
                    anchors.centerIn: parent
                    text: String(assetRow.modelData.symbol || "?").slice(0, 1)
                    font.family: "monospace"; font.pixelSize: 13; font.bold: true; color: "#e6edf3"; textFormat: Text.PlainText
                }
            }
            Column {
                x: 48; y: 13; width: table.priceX - x - 12; spacing: 5
                Text {
                    width: parent.width; text: String(assetRow.modelData.name || assetRow.modelData.symbol || "Okänd tillgång")
                    elide: Text.ElideRight; textFormat: Text.PlainText
                    color: "#e6edf3"; font.family: "monospace"; font.pixelSize: table.compact ? 11 : 12
                }
                Text {
                    width: parent.width; text: String(assetRow.modelData.symbol || "") + (assetRow.selected ? " · VALD" : "")
                    elide: Text.ElideRight; textFormat: Text.PlainText
                    color: assetRow.selected ? "#e6edf3" : "#8b949e"; font.family: "monospace"; font.pixelSize: 10
                }
            }
            Column {
                x: table.priceX; y: 13; width: table.valueX - x - 16; spacing: 5
                Text {
                    width: parent.width; horizontalAlignment: Text.AlignRight
                    text: Format.money(assetRow.modelData.price_usd, "USD", true)
                    color: "#e6edf3"; font.family: "monospace"; font.pixelSize: table.compact ? 11 : 12
                    elide: Text.ElideRight; textFormat: Text.PlainText
                }
                Text {
                    width: parent.width; horizontalAlignment: Text.AlignRight
                    text: !assetRow.priceKnown ? "Pris saknas" : assetRow.modelData.stale ? "Äldre pris"
                        : Format.percent(assetRow.modelData.change_24h_pct)
                    color: !assetRow.priceKnown || assetRow.modelData.stale ? "#c8a97e"
                        : !assetRow.changeKnown ? "#8b949e" : Number(assetRow.modelData.change_24h_pct) >= 0 ? "#8db89a" : "#c98989"
                    font.family: "monospace"; font.pixelSize: 10; elide: Text.ElideRight; textFormat: Text.PlainText
                }
            }
            Column {
                x: table.valueX; y: 13; width: table.width - x - 12; spacing: 5
                Text {
                    width: parent.width; horizontalAlignment: Text.AlignRight
                    text: Format.money(assetRow.modelData.value_usd, "USD", false)
                    color: "#e6edf3"; font.family: "monospace"; font.pixelSize: table.compact ? 11 : 12
                    elide: Text.ElideRight; textFormat: Text.PlainText
                }
                Text {
                    width: parent.width; horizontalAlignment: Text.AlignRight
                    text: (assetRow.modelData.quantity_text === undefined || assetRow.modelData.quantity_text === null
                        ? "—" : Format.quantity(assetRow.modelData.quantity_text)) + " " + String(assetRow.modelData.symbol || "")
                    color: "#8b949e"; font.family: "monospace"; font.pixelSize: 10
                    elide: Text.ElideRight; textFormat: Text.PlainText
                }
            }
            MouseArea {
                id: rowMouse
                anchors.fill: parent; hoverEnabled: true; activeFocusOnTab: assetRow.selectable
                cursorShape: assetRow.selectable ? Qt.PointingHandCursor : Qt.ArrowCursor
                Accessible.role: assetRow.selectable ? Accessible.Button : Accessible.ListItem
                Accessible.name: String(assetRow.modelData.name || assetRow.modelData.symbol || "Tillgång")
                    + ", " + String(assetRow.modelData.quantity_text || "okänt antal")
                    + ", " + (assetRow.priceKnown ? Format.money(assetRow.modelData.value_usd, "USD", false) : "pris saknas")
                onClicked: {
                    if (assetRow.nativeAsset) table.assetSelected(String(assetRow.modelData.symbol))
                    else if (assetRow.selectable) table.tokenSelected(String(assetRow.modelData.mint))
                }
                Keys.onReturnPressed: clicked(null)
                Keys.onSpacePressed: clicked(null)
            }
            ToolTip {
                id: rowTip
                width: Math.min(420, Math.max(200, table.width))
                visible: rowMouse.containsMouse || rowMouse.activeFocus
                delay: 650
                text: String(assetRow.modelData.quantity_text === undefined ? "Okänt antal" : assetRow.modelData.quantity_text)
                    + " " + String(assetRow.modelData.symbol || "") + "\n" + String(assetRow.modelData.mint || "")
                    + (assetRow.modelData.price_source ? "\nPris: " + assetRow.modelData.price_source
                        + (assetRow.modelData.stale ? " · äldre data" : "") : "\nIngen verifierad prisdata")
                    + (assetRow.selectable ? "\n" + (assetRow.nativeAsset ? "Öppna prisgraf" : "Inspektera token i Pump") : "")
                contentItem: Text {
                    text: rowTip.text; textFormat: Text.PlainText
                    color: "#e6edf3"; font.family: "monospace"; font.pixelSize: 11
                    wrapMode: Text.WrapAnywhere
                }
                background: Rectangle { color: "#161616"; border.color: "#6a6a6a"; radius: 2 }
            }
        }
    }
    Column {
        anchors.centerIn: rows; width: rows.width - 24; spacing: 8
        visible: table.visibleAssets.length === 0
        Text {
            width: parent.width; horizontalAlignment: Text.AlignHCenter
            text: table.assets.length ? "INGEN TRÄFF" : "INGA TILLGÅNGAR ÄNNU"
            color: "#c8cdd4"; font.family: "monospace"; font.pixelSize: 11
        }
        Text {
            width: parent.width; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter
            text: table.assets.length ? "Sök efter namn, symbol eller mint. Rensa sökningen för att visa allt."
                : "Anslut en plånbok för att se dina tillgångar."
            color: "#8b949e"; font.family: "monospace"; font.pixelSize: 11
        }
    }
}
