import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs

Rectangle {
    id: root
    objectName: "walletPopup"
    width: root.visualWidth > 0 ? root.visualWidth : 328
    height: root.visualHeight > 0 ? root.visualHeight : Math.min(600, bodyCol.height + 42)
    color: "#161616"
    border.color: root.frameBorder
    border.width: 1
    radius: root.frameRadius

    property color frameBorder: "#6a6a6a"
    property int frameRadius: 4
    property real visualWidth: -1
    property real visualHeight: -1
    property bool layoutLocked: true
    property var surfaceHost: null
    property string statusJson: "{}"
    property var statusSnapshot: null
    property bool externallyManagedStatus: false
    signal requestClose()
    signal openDesk()
    signal walletStatusUpdated(string raw)
    readonly property color ink: "#e6edf3"
    readonly property color muted: "#9aa3ad"
    readonly property color gold: "#c8a97e"
    readonly property color green: "#8db89a"
    readonly property var status: {
        try {
            var parsed = root.statusSnapshot || JSON.parse(root.statusJson || "{}")
            return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : ({})
        } catch (err) { return {} }
    }
    readonly property var wallet: root.status.wallet || {}
    readonly property var quote: root.status.quote || {}
    readonly property var holdings: root.status.holdings || []
    readonly property var lab: root.status.lab || {}
    readonly property string pubkey: String(root.wallet.pubkey || "")
    readonly property bool connected: root.pubkey.length > 12
    readonly property string shortKey: root.connected ? root.pubkey.slice(0, 4) + "…" + root.pubkey.slice(-4) : "INGET KONTO"
    readonly property string legend: String(root.status.legend || "")
    readonly property string network: String(root.wallet.network || "").toUpperCase()
    readonly property bool observe: root.legend === "OBSERVE" || root.legend === "MAINNET" || root.network === "MAINNET"
    property string copied: ""
    property bool accountToolsOpen: !root.connected
    readonly property var operation: root.status.ui_operation || ({})
    readonly property bool operationBusy: String(root.operation.state || "") === "running"
        || root.pump.loading === true || ["running", "loading"].indexOf(String(root.pump.state || "")) >= 0
    readonly property var pump: root.status.pump || ({})

    component WalletButton: CryptoButton {
        property bool subdued: false
        font.family: "monospace"; font.pixelSize: 12
        padding: 9; topPadding: 7; bottomPadding: 7
        implicitHeight: 32
        color: subdued ? root.muted : root.ink
    }
    function inspectToken(mint) {
        if (root.operationBusy || !mint || !root.surfaceHost || !root.surfaceHost.cryptoPumpInspect) return
        root.applyRaw(root.surfaceHost.cryptoPumpInspect(String(mint), ""))
    }
    function pull() {
        if (!root.visible || !root.surfaceHost || !root.surfaceHost.cryptoStatus) return
        var raw = root.surfaceHost.cryptoStatus()
        if (raw && raw !== root.statusJson) root.applyRaw(raw)
    }
    function applyRaw(raw) {
        if (!raw) return
        // Main owns the binding. Assigning it here would detach future pushes.
        if (!root.externallyManagedStatus) root.statusJson = raw
        root.walletStatusUpdated(raw)
    }
    function copyAddr() {
        if (!root.connected || !root.surfaceHost || !root.surfaceHost.tmogCopy) return
        root.surfaceHost.tmogCopy(root.pubkey)
        root.copied = "KOPIERAD"
        copyReset.restart()
    }
    Connections {
        target: root.surfaceHost
        ignoreUnknownSignals: true
        function onCryptoStatusUpdated(raw) {
            if (root.visible && !root.externallyManagedStatus && raw !== root.statusJson) root.applyRaw(raw)
        }
    }
    Timer {
        interval: 1000; repeat: true
        running: root.visible && (root.operationBusy || root.status.refreshing === true || root.wallet.rpc_loading === true)
        onTriggered: root.pull()
    }
    Timer { id: copyReset; interval: 1400; onTriggered: root.copied = "" }
    Keys.onEscapePressed: root.requestClose()
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.LeftButton; onClicked: {} }
    Rectangle {
        z: 3
        anchors.left: parent.left; anchors.leftMargin: 12
        anchors.top: parent.top; anchors.topMargin: -8
        height: 18; width: leftLegendText.implicitWidth + 12
        color: root.color; radius: 3
        Text {
            id: leftLegendText; anchors.centerIn: parent; text: "WALLET"
            color: root.ink; font.family: "monospace"; font.pixelSize: 12; font.bold: true
        }
    }
    Row {
        z: 3
        anchors.right: parent.right; anchors.rightMargin: 9
        anchors.top: parent.top; anchors.topMargin: -12
        spacing: 3
        Text {
            id: gripDots; objectName: "walletDragBar"; text: "⋮⋮"
            width: 26; height: 26
            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
            color: root.muted; font.family: "monospace"; font.pixelSize: 13
            Rectangle { anchors.fill: parent; z: -1; color: root.color; radius: 3 }
            MouseArea {
                anchors.fill: parent
                drag.target: root; drag.smoothed: false
                drag.minimumX: 0; drag.minimumY: 0
                drag.maximumX: root.parent ? Math.max(0, root.parent.width - root.width) : 4096
                drag.maximumY: root.parent ? Math.max(0, root.parent.height - 48) : 4096
                cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
            }
        }
        WalletButton {
            objectName: "walletCloseButton"
            width: 26; height: 26; padding: 0; text: "×"; Accessible.name: "Stäng wallet"
            background: Rectangle { color: root.color; border.width: 0 }
            onClicked: root.requestClose()
        }
    }
    FileDialog {
        id: keypairDialog; title: "IMPORT SOLANA KEYPAIR"
        fileMode: FileDialog.OpenFile; nameFilters: ["JSON (*.json)", "All files (*)"]
        onAccepted: {
            if (root.surfaceHost && root.surfaceHost.cryptoImportKeypair)
                root.applyRaw(root.surfaceHost.cryptoImportKeypair(String(keypairDialog.selectedFile)))
        }
    }
    Flickable {
        id: walletBody; objectName: "walletBodyScroll"
        anchors.fill: parent
        anchors.leftMargin: 14; anchors.rightMargin: 14; anchors.topMargin: 24; anchors.bottomMargin: 14
        contentWidth: width; contentHeight: bodyCol.height
        clip: true; boundsBehavior: Flickable.StopAtBounds; interactive: contentHeight > height
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
        Column {
            id: bodyCol; width: walletBody.width; spacing: 12
            Column {
                width: parent.width; spacing: 4
                Text {
                    width: parent.width
                    text: "SOLANA · " + (root.network || (root.observe ? "MAINNET" : root.legend) || "NÄTVERK OKÄNT")
                    color: root.ink; font.family: "monospace"; font.pixelSize: 11; font.bold: true
                    elide: Text.ElideRight
                }
                Text {
                    text: root.observe ? "READ ONLY" : root.network.length || root.legend.length ? "PAPER / LAB" : "NÄTVERK OKÄNT"
                    color: root.muted; font.family: "monospace"; font.pixelSize: 10
                }
            }
            Rectangle {
                width: parent.width; height: balanceCol.height + 24
                color: "#161616"; border.color: "#6a6a6a"; radius: 4
                Rectangle {
                    x: 10; y: -7; width: balanceLegend.implicitWidth + 10; height: 16
                    color: "#161616"
                    Text {
                        id: balanceLegend; anchors.centerIn: parent; text: "SALDO"
                        color: root.ink; font.family: "monospace"; font.pixelSize: 10; font.bold: true
                    }
                }
                Column {
                    id: balanceCol; x: 12; y: 12; width: parent.width - 24; spacing: 6
                    Text {
                        text: root.connected ? "SALDO · " + root.shortKey : "DIN PLÅNBOK"
                        color: root.muted; font.family: "monospace"; font.pixelSize: 10
                    }
                    Text {
                        width: parent.width
                        text: root.connected ? String(root.wallet.balance_sol === undefined || root.wallet.balance_sol === null ? "—" : root.wallet.balance_sol) + " SOL" : "Anslut ett konto"
                        color: root.ink; font.family: "monospace"; font.pixelSize: root.connected ? 23 : 20; font.bold: true
                        elide: Text.ElideRight; textFormat: Text.PlainText
                    }
                    Text {
                        width: parent.width
                        text: !root.connected ? "Visa saldo, tillgångar och tokenanalys."
                            : String(root.quote.usd || "").length ? String(root.quote.usd) + " · uppskattat värde" : "Värdering saknas"
                        color: root.muted; font.family: "monospace"; font.pixelSize: 11
                        wrapMode: Text.WordWrap; textFormat: Text.PlainText
                    }
                }
            }
            Column {
                width: parent.width; spacing: 6; visible: root.connected
                Text { text: "OFFENTLIG ADRESS"; color: root.muted; font.family: "monospace"; font.pixelSize: 10 }
                Row {
                    width: parent.width; spacing: 6
                    CryptoField {
                        width: Math.max(70, parent.width - copyButton.width - parent.spacing); height: 32
                        readOnly: true; selectByMouse: true; text: root.pubkey
                        color: root.ink
                        font.family: "monospace"; font.pixelSize: 10
                        Accessible.name: "Offentlig Solana-adress"
                    }
                    WalletButton {
                        id: copyButton; objectName: "walletCopyAddress"
                        text: root.copied.length ? root.copied : "KOPIERA"
                        enabled: root.connected && Boolean(root.surfaceHost && root.surfaceHost.tmogCopy)
                        onClicked: root.copyAddr()
                    }
                }
            }
            Text {
                objectName: "walletRpcStatus"
                visible: root.connected && (root.wallet.rpc_loading === true || root.wallet.rpc_stale === true || String(root.wallet.rpc_error || "").length > 0)
                width: parent.width
                text: root.wallet.rpc_loading ? "Hämtar saldo och tillgångar…"
                    : root.wallet.rpc_error ? "Hämtning misslyckades · " + String(root.wallet.rpc_error) : "Visar senast hämtade saldo."
                color: root.gold; font.family: "monospace"; font.pixelSize: 10
                wrapMode: Text.WrapAnywhere; textFormat: Text.PlainText
            }
            Row {
                width: parent.width; spacing: 6
                WalletButton {
                    width: (parent.width - parent.spacing) / 2
                    text: "TESTNET"; primary: !root.observe && (["TESTNET", "LOCALNET"].indexOf(root.legend) >= 0 || root.network === "TESTNET"); enabled: !root.operationBusy
                    checked: primary
                    Accessible.name: "Välj Solana testnet"
                    onClicked: {
                        if (root.surfaceHost && root.surfaceHost.cryptoSetNetwork)
                            root.applyRaw(root.surfaceHost.cryptoSetNetwork("testnet"))
                    }
                }
                WalletButton {
                    width: (parent.width - parent.spacing) / 2
                    text: "MAINNET · LÄS"; primary: root.observe; enabled: !root.operationBusy
                    checked: primary
                    Accessible.name: "Välj Solana mainnet, endast läsning"
                    onClicked: {
                        if (root.surfaceHost && root.surfaceHost.cryptoSetNetwork)
                            root.applyRaw(root.surfaceHost.cryptoSetNetwork("mainnet"))
                    }
                }
            }
            Text {
                width: parent.width
                text: root.observe ? "Mainnet är läsläge. Inga riktiga överföringar."
                    : "Simulerad handel. Testtransaktioner kräver testnet eller lokal labb."
                color: root.muted; font.family: "monospace"; font.pixelSize: 10; wrapMode: Text.WordWrap
            }
            Text {
                visible: root.connected && !root.status.signer; width: parent.width
                text: "WATCH ONLY · Kontot saknar lokal signeringsnyckel."
                color: root.muted; font.family: "monospace"; font.pixelSize: 10; wrapMode: Text.WordWrap
            }
            Text {
                objectName: "walletOperationStatus"
                visible: root.operationBusy || String(root.operation.error || "").length > 0; width: parent.width
                text: root.operationBusy ? "Arbetar…" : String(root.operation.error || "")
                color: root.operationBusy ? root.muted : root.gold
                font.family: "monospace"; font.pixelSize: 10; wrapMode: Text.WrapAnywhere; textFormat: Text.PlainText
            }
            Rectangle { width: parent.width; height: 1; color: "#6a6a6a" }
            Text {
                text: "TILLGÅNGAR  /  " + root.holdings.length
                color: root.ink; font.family: "monospace"; font.pixelSize: 10; font.bold: true
            }
            Repeater {
                model: Math.min(root.holdings.length, 5)
                delegate: Rectangle {
                    id: assetRow
                    readonly property var row: root.holdings[index] || {}
                    readonly property string mint: String(row.mint || "")
                    width: bodyCol.width; height: 46; color: "#181818"; radius: 3
                    border.color: "#6a6a6a"
                    Column {
                        x: 10; y: 7
                        width: parent.width - (pumpInspectButton.visible ? pumpInspectButton.width + 26 : 20); spacing: 3
                        Text {
                            width: parent.width; text: String(assetRow.row.symbol || "TOKEN")
                            color: root.ink; font.family: "monospace"; font.pixelSize: 11; font.bold: true
                            elide: Text.ElideRight; textFormat: Text.PlainText
                        }
                        Text {
                            width: parent.width
                            text: String(assetRow.row.display || "—") + (assetRow.row.usd ? " · " + String(assetRow.row.usd) : "")
                            color: root.muted; font.family: "monospace"; font.pixelSize: 10
                            elide: Text.ElideRight; textFormat: Text.PlainText
                        }
                    }
                    WalletButton {
                        id: pumpInspectButton; objectName: "walletPumpInspect"
                        anchors.right: parent.right; anchors.rightMargin: 7; anchors.verticalCenter: parent.verticalCenter
                        property string mint: assetRow.mint
                        visible: mint.length > 0 && mint !== "native"; enabled: !root.operationBusy
                        text: "INSPECT"; Accessible.name: "Inspect " + String(assetRow.row.symbol || "token")
                        height: 30; onClicked: root.inspectToken(mint)
                    }
                }
            }
            Text {
                visible: root.holdings.length > 5
                text: "+ " + (root.holdings.length - 5) + " tillgångar i CRYPTO"
                color: root.muted; font.family: "monospace"; font.pixelSize: 10
            }
            Text {
                visible: root.holdings.length === 0
                text: !root.connected ? "Anslut ett konto för att visa tillgångar."
                    : root.status.refreshing || root.wallet.rpc_loading ? "Hämtar tillgångar…"
                    : root.wallet.rpc_error ? "Tillgångarna kunde inte hämtas. Försök igen." : "Inga tillgångar på det här nätverket."
                color: root.muted; font.family: "monospace"; font.pixelSize: 11
                width: parent.width; wrapMode: Text.WordWrap
            }
            Text {
                objectName: "walletPumpSelection"; width: parent.width
                visible: String(root.pump.mint || "").length > 0
                text: "PUMP · " + String(root.pump.state || "idle").toUpperCase()
                    + (root.pump.stale === true ? " · STALE" : "") + "\n" + String(root.pump.mint || "")
                    + (root.pump.error ? "\n" + String(root.pump.error) : "\nÖppna CRYPTO → Pump för estimat och paper trading.")
                color: root.pump.error ? "#c98989" : "#c8cdd4"
                font.family: "monospace"; font.pixelSize: 10; wrapMode: Text.WrapAnywhere; textFormat: Text.PlainText
            }
            WalletButton {
                width: parent.width; text: "ÖPPNA CRYPTO  →"; primary: true
                onClicked: { root.openDesk(); root.requestClose() }
            }
            WalletButton {
                width: parent.width; text: (root.accountToolsOpen ? "▾ " : "▸ ") + "KONTOHANTERING"; subdued: true
                onClicked: root.accountToolsOpen = !root.accountToolsOpen
            }
            Column {
                width: parent.width; spacing: 6; visible: root.accountToolsOpen
                Repeater {
                    model: root.status.accounts || []
                    delegate: WalletButton {
                        required property var modelData
                        width: bodyCol.width
                        text: (modelData.active ? "●  " : "   ") + String(modelData.short || "Konto")
                        enabled: !root.operationBusy && !modelData.active
                        Accessible.name: "Välj konto " + String(modelData.short || "")
                        onClicked: {
                            if (root.surfaceHost && root.surfaceHost.cryptoSelectAccount)
                                root.applyRaw(root.surfaceHost.cryptoSelectAccount(String(modelData.pubkey || "")))
                        }
                    }
                }
                Flow {
                    width: parent.width; spacing: 6
                    WalletButton {
                        text: "SKAPA TESTKONTO"; enabled: !root.operationBusy
                        onClicked: {
                            if (root.surfaceHost && root.surfaceHost.cryptoCreateTestWallet)
                                root.applyRaw(root.surfaceHost.cryptoCreateTestWallet())
                        }
                    }
                    WalletButton { text: "IMPORTERA"; enabled: !root.operationBusy; onClicked: keypairDialog.open() }
                    WalletButton {
                        text: "TEST-AIRDROP"; visible: !root.observe; enabled: !root.operationBusy && root.connected
                        onClicked: {
                            if (root.surfaceHost && root.surfaceHost.cryptoAirdrop) root.applyRaw(root.surfaceHost.cryptoAirdrop())
                        }
                    }
                    WalletButton {
                        text: "KOPPLA FRÅN"; subdued: true; enabled: !root.operationBusy && root.connected
                        onClicked: {
                            if (root.surfaceHost && root.surfaceHost.cryptoDisconnect) root.applyRaw(root.surfaceHost.cryptoDisconnect())
                        }
                    }
                }
            }
        }
    }
}
