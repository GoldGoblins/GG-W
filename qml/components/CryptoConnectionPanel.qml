
import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Popup {
    id: root
    objectName: "cryptoConnectionPanel"
    property string asset: "SOL"
    property string network: "testnet"
    property var connection: ({})
    property var lab: ({})
    property bool busy: false
    property string watchDraft: ""
    signal networkRequested(string network)
    signal labRequested(bool running)
    signal refreshRequested()
    signal watchRequested(string address)
    function errorText(code) {
        var messages = {KASPA_WATCH_NETWORK_MISMATCH: "Adressen tillhör ett annat nät. Använd kaspa: för LIVE och kaspasim: för lokalt simnet.",
            KASPA_BALANCE_UNAVAILABLE: "Adressen kunde inte läsas. Kontrollera adressen och försök igen.",
            CRYPTO_CONNECTION_UNAVAILABLE: "Datakällan svarade inte. Kontrollera anslutningen och försök igen.",
            CRYPTO_WRONG_NETWORK: "Datakällan svarar från fel nätverk.", KASPA_WRONG_NETWORK: "Kaspa-noden svarar från fel nätverk.",
            CRYPTO_NODE_UNHEALTHY: "Noden rapporterar att den inte är redo.", CRYPTO_VALIDATOR_MISSING: "Lokal validator saknas.",
            KASPA_NODE_MISSING: "Kaspa-noden behöver installeras med programmets runtime-installation."}
        return messages[code] || "Kontrollen kunde inte slutföras. Försök igen."
    }
    anchors.centerIn: parent
    width: Math.min(520, parent.width-20)
    height: Math.min(530, parent.height-20)
    modal: true; focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    background: Rectangle { color: RuntimeTheme.GGTheme.panel; border.color: "#555047"; radius: 5 }
    contentItem: ScrollView {
        clip: true
        contentWidth: availableWidth
        ColumnLayout {
            width: parent.width
            spacing: 12
            RowLayout {
                Layout.fillWidth: true
                GGText { colorKey: "ui.CryptoConnectionPanel.1"; Layout.fillWidth: true; text: root.asset + " · Anslutning och labb"; color: "#d4dce6"; font.pixelSize: 15 }
                ResearchAction { property string uiColorScope: "ui.widget.CryptoConnectionPanel.ResearchAction.1"; iconKind: "stop"; hint: "Stäng anslutningspanelen"; onClicked: root.close() }
            }
            Flow {
                Layout.fillWidth: true; spacing: 6
                CryptoButton { property string uiColorScope: "ui.control.CryptoConnectionPanel.1"; objectName: "cryptoModeLive"; text: "LIVE · läsläge"; checked: root.network === "mainnet"; enabled: !root.busy; onClicked: root.networkRequested("mainnet") }
                CryptoButton { property string uiColorScope: "ui.control.CryptoConnectionPanel.2"; objectName: "cryptoModeLocal"; text: "LOCAL LAB"; checked: root.network === "testnet"; enabled: !root.busy; onClicked: root.networkRequested("testnet") }
                CryptoButton { property string uiColorScope: "ui.control.CryptoConnectionPanel.3"; visible: root.asset === "KAS"; text: "PAPER"; checked: root.network === "paper"; enabled: !root.busy; onClicked: root.networkRequested("paper") }
            }
            RowLayout {
                Rectangle { GGColorTarget { colorKey: "ui.fill.CryptoConnectionPanel.1"; } width: 7; height: 7; radius: 4; color: root.connection.healthy && !root.connection.stale ? RuntimeTheme.GGTheme.positive : RuntimeTheme.GGTheme.warning }
                GGText { colorKey: "ui.CryptoConnectionPanel.2"; Layout.fillWidth: true; color: "#c5cdd7"; font.pixelSize: 12; wrapMode: Text.WordWrap; text: root.connection.loading ? "Kontrollerar anslutningen…" : root.connection.healthy ? (root.connection.stale ? "Tidigare ansluten · uppgiften är inaktuell" : "Ansluten · " + String(root.connection.label || root.connection.backend || "")) : "Inte ansluten" }
                ResearchAction { property string uiColorScope: "ui.widget.CryptoConnectionPanel.ResearchAction.5"; objectName: "cryptoConnectionRefresh"; iconKind: "refresh"; hint: "Kontrollera anslutningen igen"; enabled: !root.busy && !root.connection.loading; onClicked: root.refreshRequested() }
            }
            GGText { colorKey: "ui.CryptoConnectionPanel.3"; Layout.fillWidth: true; visible: !!root.connection.error || !!root.connection.watch_error; text: root.errorText(root.connection.error || root.connection.watch_error); textFormat: Text.PlainText; color: "#ca998d"; font.pixelSize: 11; wrapMode: Text.WordWrap }
            GGText { colorKey: "ui.CryptoConnectionPanel.4"; Layout.fillWidth: true; text: root.network === "mainnet" ? "Verkliga kedjedata och bevakningsadresser. Huvudnätet används i läsläge." : root.asset === "KAS" ? (root.network === "paper" ? "Lokal papperssimulering av covenant-räknaren." : "Egen Kaspa-nod i isolerat simnet. Covenant-räknaren är en separat papperssimulering; den skickar inga transaktioner.") : "Lokal Solana VM på Windows eller en installerad validator. Konton sparas lokalt. En VM kör transaktioner men deltar inte i nätverkets konsensus."; color: "#9ba5b2"; font.pixelSize: 12; wrapMode: Text.WordWrap }
            GGText { colorKey: "ui.CryptoConnectionPanel.5"; Layout.fillWidth: true; text: root.connection.endpoint || root.lab.rpc || ""; textFormat: Text.PlainText; color: "#788696"; font.pixelSize: 11; wrapMode: Text.WrapAnywhere }
            GGText { colorKey: "ui.CryptoConnectionPanel.6"; Layout.fillWidth: true; text: (root.connection.height === undefined || root.connection.height === null ? "" : (root.asset === "SOL" ? "Slot " : "DAA ") + root.connection.height + " · ") + (root.connection.latency_ms === undefined ? "" : root.connection.latency_ms + " ms") + (root.connection.observed_at ? " · " + new Date(root.connection.observed_at*1000).toLocaleTimeString() : ""); color: "#788696"; font.pixelSize: 11; wrapMode: Text.WordWrap }
            CryptoButton { property string uiColorScope: "ui.control.CryptoConnectionPanel.4"; objectName: "cryptoConnectionLabToggle"; Layout.fillWidth: true; visible: root.network === "testnet"; text: root.lab.running ? "Stoppa lokalt labb" : "Starta lokalt labb"; enabled: !root.busy; onClicked: root.labRequested(root.lab.running === true) }
            GGText { colorKey: "ui.CryptoConnectionPanel.7"; Layout.fillWidth: true; visible: root.network === "testnet" && !!root.lab.diagnostic; text: root.errorText(root.lab.diagnostic); textFormat: Text.PlainText; color: RuntimeTheme.GGTheme.warning; font.pixelSize: 11; wrapMode: Text.WordWrap }
            GGText { colorKey: "ui.CryptoConnectionPanel.8"; Layout.fillWidth: true; visible: root.asset === "KAS" && root.network !== "paper"; text: "Bevakningsadress · endast publika adresser"; color: "#a7b1be"; font.pixelSize: 12 }
            CryptoField { property string uiColorScope: "ui.widget.CryptoConnectionPanel.CryptoField.7"; objectName: "cryptoKasWatchAddress"; Layout.fillWidth: true; visible: root.asset === "KAS" && root.network !== "paper"; placeholderText: root.network === "mainnet" ? "kaspa:…" : "kaspasim:…"; text: root.watchDraft; onTextChanged: root.watchDraft = text }
            CryptoButton { property string uiColorScope: "ui.control.CryptoConnectionPanel.5"; objectName: "cryptoKasWatchSave"; visible: root.asset === "KAS" && root.network !== "paper"; text: "Spara bevakningsadress"; enabled: !root.busy; onClicked: root.watchRequested(root.watchDraft) }
        }
    }
}
