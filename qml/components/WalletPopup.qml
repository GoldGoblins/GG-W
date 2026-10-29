
import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs

Item {
    id: root
    objectName: "walletPopup"
    width: root.visualWidth > 0 ? root.visualWidth : 328
    height: root.visualHeight > 0 ? root.visualHeight : Math.min(600, bodyCol.height + 42)
    property color color: RuntimeTheme.GGTheme.panel

    property color frameBorder: RuntimeTheme.GGTheme.dim
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
    readonly property color ink: RuntimeTheme.GGTheme.bright
    readonly property color muted: RuntimeTheme.GGTheme.muted
    readonly property color gold: RuntimeTheme.GGTheme.accent
    readonly property color green: RuntimeTheme.GGTheme.positive
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
    property bool omniOpen: false
    readonly property bool unifiedWallet:!!root.surfaceHost && !!root.surfaceHost.omniStatus
    property bool legacyToolsOpen:false
    property string unifiedPage:"WALLET"
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
    Rectangle {
        anchors.fill: parent; anchors.margins: 1
        color: root.color; radius: Math.max(0, root.frameRadius - 1)
    }
    LedgerBorder { property string uiColorScope: "ui.widget.WalletPopup.LedgerBorder.1";
        anchors.fill: parent; color: root.frameBorder; radius: root.frameRadius
        topGaps: [
            {start: walletTitle.x, end: walletTitle.x + walletTitle.width},
            {start: walletControls.x - 3, end: walletControls.x + walletControls.width + 3}
        ]
    }
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.LeftButton; onClicked: {} }
    Item {
        id: walletTitle
        z: 3
        anchors.left: parent.left; anchors.leftMargin: 12
        anchors.top: parent.top; anchors.topMargin: -8
        height: 18; width: leftLegendText.implicitWidth + 12
        GGText { colorKey: "ui.WalletPopup.1";
            id: leftLegendText; anchors.centerIn: parent; text: "WALLET"
            color: root.ink; font.family: "monospace"; font.pixelSize: 12; font.bold: true
        }
    }
    Row {
        id: walletControls
        z: 3
        anchors.right: parent.right; anchors.rightMargin: 9
        anchors.top: parent.top; anchors.topMargin: -12
        spacing: 3
        GGText { colorKey: "ui.WalletPopup.2";
            id: gripDots; objectName: "walletDragBar"; text: "⋮⋮"
            width: 26; height: 26
            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
            color: root.muted; font.family: "monospace"; font.pixelSize: 13
            MouseArea {
                anchors.fill: parent
                drag.target: root; drag.smoothed: false
                drag.minimumX: 0; drag.minimumY: 0
                drag.maximumX: root.parent ? Math.max(0, root.parent.width - root.width) : 4096
                drag.maximumY: root.parent ? Math.max(0, root.parent.height - 48) : 4096
                cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
            }
        }
        WalletButton { property string uiColorScope: "ui.control.WalletPopup.1";
            id: walletMenu
            visible:root.unifiedWallet;text:"⋯";width:26;height:26;padding:0;tip:"Walletverktyg";onClicked:walletOptions.open()
            background: Rectangle { color: walletMenu.hovered || walletMenu.down || walletMenu.visualFocus ? RuntimeTheme.GGTheme.raised : "transparent"; border.width: walletMenu.visualFocus ? 1 : 0; border.color: root.muted }
        }
        WalletButton { property string uiColorScope: "ui.control.WalletPopup.2";
            id: walletClose
            objectName: "walletCloseButton"
            width: 26; height: 26; padding: 0; text: "×"; Accessible.name: "Stäng wallet"
            background: Rectangle { color: walletClose.hovered || walletClose.down || walletClose.visualFocus ? RuntimeTheme.GGTheme.raised : "transparent"; border.width: walletClose.visualFocus ? 1 : 0; border.color: root.muted }
            onClicked: root.requestClose()
        }
    }
    Popup {id:walletOptions;x:Math.max(0,root.width-width-10);y:18;width:220;padding:10;focus:true;closePolicy:Popup.CloseOnEscape|Popup.CloseOnPressOutside
        background:Rectangle {color:RuntimeTheme.GGTheme.panel;border.color:RuntimeTheme.GGTheme.edge;radius:3}
        contentItem:Column {spacing:5
            WalletButton { property string uiColorScope: "ui.control.WalletPopup.3";width:parent.width;text:"Konton & token";onClicked:{root.omniOpen=true;root.legacyToolsOpen=false;walletOmni.page="WALLET";walletOptions.close()}}
            WalletButton { property string uiColorScope: "ui.control.WalletPopup.4";width:parent.width;text:"SOL-labbverktyg";onClicked:{root.legacyToolsOpen=true;root.omniOpen=false;walletOptions.close()}}
            WalletButton { property string uiColorScope: "ui.control.WalletPopup.5";width:parent.width;text:"Tillgångsöversikt";onClicked:{root.legacyToolsOpen=false;root.omniOpen=false;root.unifiedPage="WALLET";walletOptions.close()}}
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
        anchors.leftMargin: root.unifiedWallet && !root.legacyToolsOpen ? 8 : 14; anchors.rightMargin: root.unifiedWallet && !root.legacyToolsOpen ? 8 : 14; anchors.topMargin: 22; anchors.bottomMargin: 8
        contentWidth: width; contentHeight: root.unifiedWallet && !root.legacyToolsOpen ? height : bodyCol.height
        clip: true; boundsBehavior: Flickable.StopAtBounds; interactive: (!root.unifiedWallet || root.legacyToolsOpen) && contentHeight > height
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
        Column {
            id: bodyCol; width: walletBody.width; spacing: 12
            WalletButton { property string uiColorScope: "ui.control.WalletPopup.6";
                id: overviewBack; objectName: "walletPopupBack"
                visible: root.unifiedWallet && (root.omniOpen || root.legacyToolsOpen || root.unifiedPage !== "WALLET")
                text: "← Tillgångar"; height: 26; font.pixelSize: 10; topPadding: 2; bottomPadding: 2
                onClicked: {root.omniOpen=false;root.legacyToolsOpen=false;root.unifiedPage="WALLET"}
            }
            OmniWalletPanel { property string uiColorScope: "ui.widget.WalletPopup.OmniWalletPanel.8"; id:walletOverview;compactPopup:true;width:parent.width;height:root.unifiedWallet && !root.omniOpen && !root.legacyToolsOpen && root.unifiedPage==="WALLET" ? walletBody.height : 0;visible:height>0;surfaceHost:root.surfaceHost;onToolsRequested:{root.omniOpen=true;walletOmni.page="WALLET"} onMarketRequested:root.unifiedPage="MARKET"
                onWorkspaceRequested:{root.openDesk();root.requestClose()}
                onAssetRequested:function(id){root.unifiedPage="MARKET";Qt.callLater(function(){walletMarket.openAsset(id)})}
            }
            MarketExplorer { property string uiColorScope: "ui.widget.WalletPopup.MarketExplorer.9";id:walletMarket;width:parent.width;height:root.unifiedWallet && !root.omniOpen && !root.legacyToolsOpen && root.unifiedPage==="MARKET" ? walletBody.height-overviewBack.height-bodyCol.spacing : 0;visible:height>0;surfaceHost:root.surfaceHost
                onWalletRequested:root.unifiedPage="WALLET"
                onBotsRequested:{root.omniOpen=true;walletOmni.page="BOTS"}
                onNetworkRequested:{root.omniOpen=true;walletOmni.page="LAB"}
            }
            WalletButton { property string uiColorScope: "ui.control.WalletPopup.7"; visible:!root.unifiedWallet;text: root.omniOpen ? "Stäng OMNI" : "Alla nätverk · OMNI"; checkable:true; checked:root.omniOpen; onClicked:root.omniOpen=checked }
            OmniSurface { property string uiColorScope: "ui.widget.WalletPopup.OmniSurface.11"; id:walletOmni;embedded:true;width:parent.width; height:root.omniOpen ? Math.max(0,walletBody.height-overviewBack.height-bodyCol.spacing) : 0; visible:root.omniOpen; surfaceHost:root.surfaceHost }
            WalletButton { property string uiColorScope: "ui.control.WalletPopup.8";visible:root.unifiedWallet && root.legacyToolsOpen;text:root.legacyToolsOpen ? "Dölj SOL-labbverktyg" : "Avancerat · SOL-labbverktyg";checkable:true;checked:root.legacyToolsOpen;onClicked:root.legacyToolsOpen=checked}
            Column {width:parent.width;spacing:12;visible:!root.unifiedWallet || root.legacyToolsOpen
            Column {
                width: parent.width; spacing: 4
                GGText { colorKey: "ui.WalletPopup.3";
                    width: parent.width
                    text: "SOLANA · " + (root.observe ? "LIVE" : root.network === "TESTNET" || root.legend === "LOCALNET" ? "LOCAL LAB" : root.network || "NÄTVERK OKÄNT")
                    color: root.ink; font.family: "monospace"; font.pixelSize: 11; font.bold: true
                    elide: Text.ElideRight
                }
                GGText { colorKey: "ui.WalletPopup.4";
                    text: root.observe ? "READ ONLY" : root.network.length || root.legend.length ? "PAPER / LAB" : "NÄTVERK OKÄNT"
                    color: root.muted; font.family: "monospace"; font.pixelSize: 10
                }
            }
            Item {
                id: balanceFrame
                width: parent.width; height: balanceCol.height + 24
                Rectangle {
                    anchors.fill: parent; anchors.margins: 1; color: RuntimeTheme.GGTheme.panel; radius: 3
                }
                LedgerBorder { property string uiColorScope: "ui.widget.WalletPopup.LedgerBorder.13";
                    anchors.fill: parent; color: RuntimeTheme.GGTheme.dim; radius: 4
                    topGaps: [{start: balanceTitle.x, end: balanceTitle.x + balanceTitle.width}]
                }
                Item {
                    id: balanceTitle
                    x: 10; y: -7; width: balanceLegend.implicitWidth + 10; height: 16
                    GGText { colorKey: "ui.WalletPopup.5";
                        id: balanceLegend; anchors.centerIn: parent; text: "SALDO"
                        color: root.ink; font.family: "monospace"; font.pixelSize: 10; font.bold: true
                    }
                }
                Column {
                    id: balanceCol; x: 12; y: 12; width: parent.width - 24; spacing: 6
                    GGText { colorKey: "ui.WalletPopup.6";
                        text: root.connected ? "SALDO · " + root.shortKey : "DIN PLÅNBOK"
                        color: root.muted; font.family: "monospace"; font.pixelSize: 10
                    }
                    GGText { colorKey: "ui.WalletPopup.7";
                        width: parent.width
                        text: root.connected ? String(root.wallet.balance_sol === undefined || root.wallet.balance_sol === null ? "—" : root.wallet.balance_sol) + " SOL" : "Anslut ett konto"
                        color: root.ink; font.family: "monospace"; font.pixelSize: root.connected ? 23 : 20; font.bold: true
                        elide: Text.ElideRight; textFormat: Text.PlainText
                    }
                    GGText { colorKey: "ui.WalletPopup.8";
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
                GGText { colorKey: "ui.WalletPopup.9"; text: "OFFENTLIG ADRESS"; color: root.muted; font.family: "monospace"; font.pixelSize: 10 }
                Row {
                    width: parent.width; spacing: 6
                    CryptoField { property string uiColorScope: "ui.widget.WalletPopup.CryptoField.14";
                        width: Math.max(70, parent.width - copyButton.width - parent.spacing); height: 32
                        readOnly: true; selectByMouse: true; text: root.pubkey
                        color: root.ink
                        font.family: "monospace"; font.pixelSize: 10
                        Accessible.name: "Offentlig Solana-adress"
                    }
                    WalletButton { property string uiColorScope: "ui.control.WalletPopup.9";
                        id: copyButton; objectName: "walletCopyAddress"
                        text: root.copied.length ? root.copied : "KOPIERA"
                        enabled: root.connected && Boolean(root.surfaceHost && root.surfaceHost.tmogCopy)
                        onClicked: root.copyAddr()
                    }
                }
            }
            GGText { colorKey: "ui.WalletPopup.10";
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
                WalletButton { property string uiColorScope: "ui.control.WalletPopup.10";
                    width: (parent.width - parent.spacing) / 2
                    text: "LOCAL LAB"; primary: !root.observe && (["TESTNET", "LOCALNET"].indexOf(root.legend) >= 0 || root.network === "TESTNET"); enabled: !root.operationBusy
                    checked: primary
                    Accessible.name: "Välj Solanas lokala labb"
                    onClicked: {
                        if (root.surfaceHost && root.surfaceHost.cryptoSetNetwork)
                            root.applyRaw(root.surfaceHost.cryptoSetNetwork("testnet"))
                    }
                }
                WalletButton { property string uiColorScope: "ui.control.WalletPopup.11";
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
            GGText { colorKey: "ui.WalletPopup.11";
                width: parent.width
                text: root.observe ? "Mainnet är läsläge. Inga riktiga överföringar."
                    : "Simulerad handel. Testtransaktioner kräver testnet eller lokal labb."
                color: root.muted; font.family: "monospace"; font.pixelSize: 10; wrapMode: Text.WordWrap
            }
            GGText { colorKey: "ui.WalletPopup.12";
                visible: root.connected && !root.status.signer; width: parent.width
                text: "WATCH ONLY · Kontot saknar lokal signeringsnyckel."
                color: root.muted; font.family: "monospace"; font.pixelSize: 10; wrapMode: Text.WordWrap
            }
            GGText { colorKey: "ui.WalletPopup.13";
                objectName: "walletOperationStatus"
                visible: root.operationBusy || String(root.operation.error || "").length > 0; width: parent.width
                text: root.operationBusy ? "Arbetar…" : String(root.operation.error || "")
                color: root.operationBusy ? root.muted : root.gold
                font.family: "monospace"; font.pixelSize: 10; wrapMode: Text.WrapAnywhere; textFormat: Text.PlainText
            }
            Rectangle { width: parent.width; height: 1; color: RuntimeTheme.GGTheme.dim }
            GGText { colorKey: "ui.WalletPopup.14";
                text: "TILLGÅNGAR  /  " + root.holdings.length
                color: root.ink; font.family: "monospace"; font.pixelSize: 10; font.bold: true
            }
            Repeater {
                model: Math.min(root.holdings.length, 5)
                delegate: Rectangle {
                    id: assetRow
                    readonly property var row: root.holdings[index] || {}
                    readonly property string mint: String(row.mint || "")
                    width: bodyCol.width; height: 46; color: RuntimeTheme.GGTheme.panel; radius: 3
                    border.color: RuntimeTheme.GGTheme.dim
                    Column {
                        x: 10; y: 7
                        width: parent.width - (pumpInspectButton.visible ? pumpInspectButton.width + 26 : 20); spacing: 3
                        GGText { colorKey: "ui.WalletPopup.15";
                            width: parent.width; text: String(assetRow.row.symbol || "TOKEN")
                            color: root.ink; font.family: "monospace"; font.pixelSize: 11; font.bold: true
                            elide: Text.ElideRight; textFormat: Text.PlainText
                        }
                        GGText { colorKey: "ui.WalletPopup.16";
                            width: parent.width
                            text: String(assetRow.row.display || "—") + (assetRow.row.usd ? " · " + String(assetRow.row.usd) : "")
                            color: root.muted; font.family: "monospace"; font.pixelSize: 10
                            elide: Text.ElideRight; textFormat: Text.PlainText
                        }
                    }
                    WalletButton { property string uiColorScope: "ui.control.WalletPopup.12";
                        id: pumpInspectButton; objectName: "walletPumpInspect"
                        anchors.right: parent.right; anchors.rightMargin: 7; anchors.verticalCenter: parent.verticalCenter
                        property string mint: assetRow.mint
                        visible: mint.length > 0 && mint !== "native"; enabled: !root.operationBusy
                        text: "INSPECT"; Accessible.name: "Inspect " + String(assetRow.row.symbol || "token")
                        height: 30; onClicked: root.inspectToken(mint)
                    }
                }
            }
            GGText { colorKey: "ui.WalletPopup.17";
                visible: root.holdings.length > 5
                text: "+ " + (root.holdings.length - 5) + " tillgångar i CRYPTO"
                color: root.muted; font.family: "monospace"; font.pixelSize: 10
            }
            GGText { colorKey: "ui.WalletPopup.18";
                visible: root.holdings.length === 0
                text: !root.connected ? "Anslut ett konto för att visa tillgångar."
                    : root.status.refreshing || root.wallet.rpc_loading ? "Hämtar tillgångar…"
                    : root.wallet.rpc_error ? "Tillgångarna kunde inte hämtas. Försök igen." : "Inga tillgångar på det här nätverket."
                color: root.muted; font.family: "monospace"; font.pixelSize: 11
                width: parent.width; wrapMode: Text.WordWrap
            }
            GGText { colorKey: "ui.WalletPopup.19";
                objectName: "walletPumpSelection"; width: parent.width
                visible: String(root.pump.mint || "").length > 0
                text: "PUMP · " + String(root.pump.state || "idle").toUpperCase()
                    + (root.pump.stale === true ? " · STALE" : "") + "\n" + String(root.pump.mint || "")
                    + (root.pump.error ? "\n" + String(root.pump.error) : "\nÖppna CRYPTO → Pump för estimat och paper trading.")
                color: root.pump.error ? RuntimeTheme.GGTheme.negative : RuntimeTheme.GGTheme.text
                font.family: "monospace"; font.pixelSize: 10; wrapMode: Text.WrapAnywhere; textFormat: Text.PlainText
            }
            WalletButton { property string uiColorScope: "ui.control.WalletPopup.13";
                width: parent.width; text: "ÖPPNA CRYPTO  →"; primary: true
                onClicked: { root.openDesk(); root.requestClose() }
            }
            WalletButton { property string uiColorScope: "ui.control.WalletPopup.14";
                width: parent.width; text: (root.accountToolsOpen ? "▾ " : "▸ ") + "KONTOHANTERING"; subdued: true
                onClicked: root.accountToolsOpen = !root.accountToolsOpen
            }
            Column {
                width: parent.width; spacing: 6; visible: root.accountToolsOpen
                Repeater {
                    model: root.status.accounts || []
                    delegate: WalletButton { property string uiColorScope: "ui.control.WalletPopup.15";
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
                    WalletButton { property string uiColorScope: "ui.control.WalletPopup.16";
                        text: "SKAPA TESTKONTO"; enabled: !root.operationBusy
                        onClicked: {
                            if (root.surfaceHost && root.surfaceHost.cryptoCreateTestWallet)
                                root.applyRaw(root.surfaceHost.cryptoCreateTestWallet())
                        }
                    }
                    WalletButton { property string uiColorScope: "ui.control.WalletPopup.17"; text: "IMPORTERA"; enabled: !root.operationBusy; onClicked: keypairDialog.open() }
                    WalletButton { property string uiColorScope: "ui.control.WalletPopup.18";
                        text: "TEST-AIRDROP"; visible: !root.observe; enabled: !root.operationBusy && root.connected
                        onClicked: {
                            if (root.surfaceHost && root.surfaceHost.cryptoAirdrop) root.applyRaw(root.surfaceHost.cryptoAirdrop())
                        }
                    }
                    WalletButton { property string uiColorScope: "ui.control.WalletPopup.19";
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
}
