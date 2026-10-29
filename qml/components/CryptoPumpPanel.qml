
import "." as RuntimeTheme
import QtQuick
import QtQuick.Controls

ScrollView {
    id: root
    objectName: "cryptoPumpPanel"
    clip: true
    contentWidth: availableWidth
    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

    property var snapshot: ({})
    property var operation: ({})
    property var surfaceHost: null
    property string requestError: ""
    property string submittedQuoteKey: ""
    property string lastSelectedMint: ""
    readonly property var data: root.snapshot || ({})
    readonly property var token: root.data.token || ({})
    readonly property var market: root.data.market || ({})
    readonly property var quote: root.data.quote || ({})
    readonly property var stress: root.data.stress || ({})
    readonly property var simulation: root.data.simulation || ({})
    readonly property var paper: root.data.paper || ({})
    readonly property bool busy: String((root.operation || {}).state || "") === "running"
        || root.data.loading === true
        || ["running", "loading"].indexOf(String(root.data.state || "")) >= 0
        || ["running", "loading"].indexOf(String(root.simulation.state || "")) >= 0
    readonly property bool inspected: String(root.data.state || "") === "ready"
        && String(root.data.mint || root.token.mint || "") === mintInput.text.trim()
        && (poolInput.text.trim().length === 0 || poolInput.text.trim() === String(root.data.pool || root.market.address || ""))
    readonly property bool fresh: root.inspected && root.data.stale !== true
    readonly property bool currentQuote: root.fresh && root.submittedQuoteKey === root.inputKey()
        && root.submittedQuoteKey.length > 0 && root.quote.supported !== false
        && root.quote.stale !== true && root.quote.valid !== false
        && !root.quote.error && String(root.quote.amount_out || root.quote.amount_out_atoms || "").length > 0
    readonly property string quoteSymbol: String(root.market.quote_symbol || root.paper.quote_symbol || "SOL")
    readonly property color ink: RuntimeTheme.GGTheme.bright
    readonly property color muted: RuntimeTheme.GGTheme.muted
    readonly property color gold: RuntimeTheme.GGTheme.accent
    readonly property color red: "#d99a9a"
    signal statusReturned(string raw)

    function value(object, key, fallback) {
        var v = (object || {})[key]
        return v === undefined || v === null || v === "" ? (fallback === undefined ? "—" : String(fallback)) : String(v)
    }

    function quantity(object, key, symbol) {
        var row = object || {}
        var display = row[key + "_display"]
        if (display !== undefined && display !== null && display !== "")
            return String(display) + (symbol && !/[a-z]/i.test(String(display)) ? " " + symbol : "")
        var atoms = row[key + "_atoms"]
        if (atoms !== undefined && atoms !== null)
            return String(atoms) + " atoms" + (symbol ? " · " + symbol : "")
        return root.value(row, key) + (row[key] !== undefined && symbol && !/[a-z]/i.test(String(row[key])) ? " " + symbol : "")
    }

    function authority(key) {
        return root.token[key] === null ? "None" : root.value(root.token, key, "Unavailable")
    }

    function inputKey() {
        return [mintInput.text.trim(), poolInput.text.trim(), sideInput.currentText,
                amountInput.text.trim(), slippageInput.text.trim()].join("|")
    }

    function run(action) {
        if (root.busy || !root.surfaceHost)
            return
        root.requestError = ""
        var raw = ""
        try {
            if (action === "inspect" && root.surfaceHost.cryptoPumpInspect) {
                root.submittedQuoteKey = ""
                raw = root.surfaceHost.cryptoPumpInspect(mintInput.text.trim(), poolInput.text.trim())
            } else if (action === "quote" && root.surfaceHost.cryptoPumpQuote) {
                root.submittedQuoteKey = root.inputKey()
                raw = root.surfaceHost.cryptoPumpQuote(sideInput.currentText, amountInput.text.trim(), slippageInput.text.trim())
            } else if (action === "simulate" && root.surfaceHost.cryptoPumpSimulate)
                raw = root.surfaceHost.cryptoPumpSimulate()
            else if (action === "paper" && root.surfaceHost.cryptoPumpPaperTrade) {
                raw = root.surfaceHost.cryptoPumpPaperTrade()
                root.submittedQuoteKey = ""
            } else if (action === "reset" && root.surfaceHost.cryptoPumpPaperReset) {
                raw = root.surfaceHost.cryptoPumpPaperReset()
                root.submittedQuoteKey = ""
            } else
                root.requestError = "This action is unavailable."
            if (raw)
                root.statusReturned(raw)
        } catch (err) {
            root.requestError = "The action could not be started. Try again."
        }
    }

    onDataChanged: {
        var selected = String(root.data.mint || (root.data.token || {}).mint || "")
        if (selected.length && selected !== root.lastSelectedMint) {
            if (!mintInput.activeFocus && mintInput.text !== selected) {
                mintInput.text = selected
                poolInput.text = ""
            }
            root.lastSelectedMint = selected
        }
    }


    property bool technicalDetailsOpen: false
    property bool simulationLogsOpen: false

    component Note: GGText {
        width: parent.width
        color: root.muted
        font.family: "monospace"
        font.pixelSize: 12
        lineHeight: 1.2
        wrapMode: Text.Wrap
        textFormat: Text.PlainText
    }

    component Label: Note {
        color: root.ink
        font.pixelSize: 10
        font.letterSpacing: 0.7
    }

    component Card: Item {
        id: card
        property string title: ""
        property string kicker: ""
        default property alias contents: cardContent.data
        width: parent.width
        height: cardContent.implicitHeight + 32
        GgFrame { property string uiColorScope: "ui.widget.CryptoPumpPanel.GgFrame.1";
            anchors.fill: parent
            leftLegend: card.kicker
            backgroundColor: RuntimeTheme.GGTheme.panel
            borderColor: RuntimeTheme.GGTheme.edge
            radius: 4
        }
        Column {
            id: cardContent
            x: 14; y: 20
            width: parent.width - 28
            spacing: 10
            Note { colorKey: "ui.CryptoPumpPanel.1"; visible: card.title.length > 0; text: card.title; font.pixelSize: 12; font.bold: true; color: root.ink }
        }
    }

    component CopyValue: TextArea {
        width: parent.width
        readOnly: true
        selectByMouse: true
        activeFocusOnTab: true
        wrapMode: TextEdit.WrapAnywhere
        textFormat: TextEdit.PlainText
        color: root.ink
        selectionColor: RuntimeTheme.GGTheme.selected
        selectedTextColor: root.ink
        font.family: "monospace"
        font.pixelSize: 11
        padding: 10
        background: Rectangle { color: RuntimeTheme.GGTheme.canvas; border.color: parent.activeFocus ? RuntimeTheme.GGTheme.dim : RuntimeTheme.GGTheme.edge; radius: 2 }
    }

    component Action: CryptoButton {
        implicitHeight: 34
        font.pixelSize: 12
    }

    Column {
        id: body
        width: Math.max(0, root.availableWidth - 12)
        spacing: 12

        Row {
            width: parent.width
            spacing: 8
            Rectangle { width: 1; height: 34; color: RuntimeTheme.GGTheme.edge }
            Column {
                width: parent.width - 12
                spacing: 4
                Note { colorKey: "ui.CryptoPumpPanel.2"; text: "ON-CHAIN RESEARCH"; font.pixelSize: 12; font.bold: true; color: root.ink }
                Label { colorKey: "ui.CryptoPumpPanel.3"; text: "INSPECT  /  COMPARE  /  SIMULATE" }
            }
        }
        Note { colorKey: "ui.CryptoPumpPanel.4";
            objectName: "cryptoPumpProvenance"
            text: root.value(root.data, "network", "Solana mainnet").toUpperCase()
                + " · WATCH ONLY · PAPER TRADING"
                + "\nSlot " + root.value(root.data, "slot") + " · Fetched " + root.value(root.data, "fetched_at_text", root.value(root.data, "fetched_at"))
                + (root.data.stale === true ? " · STALE" : "")
            color: root.data.stale === true ? root.gold : root.muted
        }

        Card { property string uiColorScope: "ui.widget.CryptoPumpPanel.Card.2";
            kicker: "01 / DISCOVER"
            title: "Inspect a token"
            Note { colorKey: "ui.CryptoPumpPanel.5"; text: "Read the token, pool and authorities before comparing a swap. Risk flags describe observations, not token safety." }
            Label { colorKey: "ui.CryptoPumpPanel.6"; text: "TOKEN MINT" }
            CryptoField { property string uiColorScope: "ui.widget.CryptoPumpPanel.CryptoField.3";
                id: mintInput
                objectName: "cryptoPumpMint"
                width: parent.width
                height: 36
                enabled: !root.busy
                placeholderText: "Paste a Solana token mint"
                placeholderTextColor: root.muted
                Accessible.name: "Token mint"
                KeyNavigation.tab: poolInput
                onAccepted: if (inspectButton.enabled) root.run("inspect")
            }
            Label { colorKey: "ui.CryptoPumpPanel.7"; text: "POOL ADDRESS · OPTIONAL" }
            CryptoField { property string uiColorScope: "ui.widget.CryptoPumpPanel.CryptoField.4";
                id: poolInput
                objectName: "cryptoPumpPool"
                width: parent.width
                height: 36
                enabled: !root.busy
                placeholderText: "Automatic canonical pool"
                placeholderTextColor: root.muted
                Accessible.name: "Pool address, optional"
                KeyNavigation.tab: inspectButton
                onAccepted: if (inspectButton.enabled) root.run("inspect")
            }
            Flow {
                width: parent.width
                spacing: 10
                Action { property string uiColorScope: "ui.control.CryptoPumpPanel.1";
                    id: inspectButton
                    objectName: "cryptoPumpInspect"
                    text: root.busy && !root.inspected ? "Inspecting…" : "Inspect token"
                    primary: true
                    enabled: !root.busy && mintInput.text.trim().length > 0
                    KeyNavigation.tab: sideInput
                    onClicked: root.run("inspect")
                }
                Note { colorKey: "ui.CryptoPumpPanel.8";
                    width: Math.min(220, parent.width)
                    topPadding: 8
                    text: root.busy ? "Working…" : root.value(root.data, "state", "Ready for a mint").toUpperCase()
                    color: root.data.stale === true ? root.gold : root.inspected ? RuntimeTheme.GGTheme.positive : root.muted
                }
            }
            Note { colorKey: "ui.CryptoPumpPanel.9";
                objectName: "cryptoPumpError"
                visible: text.length > 0
                color: root.red
                text: root.requestError || String(root.data.error || "") || String((root.operation || {}).error || "")
            }
            Note { colorKey: "ui.CryptoPumpPanel.10"; visible: (root.data.warnings || []).length > 0; color: root.gold; text: (root.data.warnings || []).slice(0, 12).join("\n") }
        }

        Card { property string uiColorScope: "ui.widget.CryptoPumpPanel.Card.6";
            visible: root.inspected || String(root.token.mint || "").length > 0
            kicker: "TOKEN & MARKET"
            title: root.value(root.token, "symbol", "Selected token")
            Note { colorKey: "ui.CryptoPumpPanel.11"; visible: !root.inspected; text: "PREVIOUS SELECTION · Inspect the edited mint to replace these details."; color: root.gold; font.pixelSize: 11 }
            Note { colorKey: "ui.CryptoPumpPanel.12"; text: root.value(root.market, "kind", "Market unavailable") + " · " + root.value(root.market, "lifecycle", "Lifecycle unavailable"); color: root.ink }
            Grid {
                width: parent.width
                columns: width < 400 ? 1 : 2
                columnSpacing: 12
                rowSpacing: 10
                Column {
                    width: parent.columns === 1 ? parent.width : (parent.width - 12) / 2
                    spacing: 4
                    Label { colorKey: "ui.CryptoPumpPanel.13"; text: "BASE LIQUIDITY" }
                    Note { colorKey: "ui.CryptoPumpPanel.14"; text: root.quantity(root.market, "base_reserves", "TOKEN"); color: root.ink }
                }
                Column {
                    width: parent.columns === 1 ? parent.width : (parent.width - 12) / 2
                    spacing: 4
                    Label { colorKey: "ui.CryptoPumpPanel.15"; text: "QUOTE LIQUIDITY" }
                    Note { colorKey: "ui.CryptoPumpPanel.16"; text: root.quantity(root.market, "quote_reserves", root.quoteSymbol); color: root.ink }
                }
            }
            Repeater {
                model: (root.data.risks || []).slice(0, 24)
                delegate: Rectangle {
                    id: riskRow
                    required property var modelData
                    width: parent.width
                    height: riskText.implicitHeight + 16
                    readonly property bool high: ["high", "critical", "error"].indexOf(String(modelData.severity || "").toLowerCase()) >= 0
                    color: RuntimeTheme.GGTheme.panel
                    border.color: RuntimeTheme.GGTheme.edge
                    radius: 2
                    Note { colorKey: "ui.CryptoPumpPanel.17";
                        id: riskText
                        x: 8; y: 8; width: parent.width - 16
                        text: root.value(riskRow.modelData, "severity", "unknown").toUpperCase() + " · "
                            + root.value(riskRow.modelData, "label", root.value(riskRow.modelData, "code"))
                        color: riskRow.high ? root.red : root.gold
                    }
                }
            }
            Note { colorKey: "ui.CryptoPumpPanel.18"; visible: (root.data.risks || []).length === 0; text: "No risk flags supplied. Coverage may be incomplete." }
            Action { property string uiColorScope: "ui.control.CryptoPumpPanel.2"; text: (root.technicalDetailsOpen ? "▾ " : "▸ ") + "Addresses & authorities"; onClicked: root.technicalDetailsOpen = !root.technicalDetailsOpen }
            CopyValue { property string uiColorScope: "ui.widget.CryptoPumpPanel.CopyValue.8";
                objectName: "cryptoPumpTokenState"
                visible: root.technicalDetailsOpen
                Accessible.name: "Token and market details"
                text: "Mint: " + root.value(root.token, "mint", root.data.mint || "—")
                    + "\nToken program: " + root.value(root.token, "token_program")
                    + "\nDecimals: " + root.value(root.token, "decimals")
                    + " · Supply: " + root.quantity(root.token, "supply", "TOKEN")
                    + "\nMint authority: " + root.authority("mint_authority")
                    + "\nFreeze authority: " + root.authority("freeze_authority")
                    + "\nMarket: " + root.value(root.market, "kind") + " · " + root.value(root.market, "lifecycle")
                    + "\nPool: " + root.value(root.market, "address", root.data.pool || "—")
                    + "\nQuote mint: " + root.value(root.market, "quote_mint")
                    + "\nBase reserves: " + root.quantity(root.market, "base_reserves", "TOKEN")
                    + "\nQuote reserves: " + root.quantity(root.market, "quote_reserves", root.quoteSymbol)
            }
        }

        Card { property string uiColorScope: "ui.widget.CryptoPumpPanel.Card.9";
            kicker: "02 / COMPARE"
            title: "Build a swap estimate"
            Flow {
                width: parent.width
                spacing: 10
                Column {
                    width: Math.min(100, parent.width)
                    spacing: 5
                    Label { colorKey: "ui.CryptoPumpPanel.19"; text: "SIDE" }
                    ComboBox { property string uiColorScope: "ui.control.CryptoPumpPanel.3";
                        id: sideInput
                        objectName: "cryptoPumpSide"
                        width: parent.width
                        height: 36
                        model: ["BUY", "SELL"]
                        enabled: !root.busy
                        Accessible.name: "Trade side"
                        KeyNavigation.tab: amountInput
                        font.family: "monospace"
                        font.pixelSize: 12
                        contentItem: GGText { colorKey: "ui.CryptoPumpPanel.20"; text: sideInput.currentText; color: sideInput.currentText === "BUY" ? RuntimeTheme.GGTheme.positive : root.red; font: sideInput.font; verticalAlignment: Text.AlignVCenter; leftPadding: 10 }
                        background: Rectangle { color: RuntimeTheme.GGTheme.canvas; border.color: sideInput.activeFocus ? RuntimeTheme.GGTheme.dim : RuntimeTheme.GGTheme.edge; radius: 2 }
                        indicator: GGText { colorKey: "ui.CryptoPumpPanel.21"; x: sideInput.width - width - 10; anchors.verticalCenter: parent.verticalCenter; text: "▾"; color: root.muted; font.family: "monospace"; font.pixelSize: 12 }
                        delegate: ItemDelegate { property string uiColorScope: "ui.control.CryptoPumpPanel.4";
                            id: sideChoice
                            required property string modelData
                            required property int index
                            width: sideInput.width
                            height: 34
                            highlighted: sideInput.highlightedIndex === index
                            contentItem: GGText { colorKey: "ui.CryptoPumpPanel.22"; text: sideChoice.modelData; color: sideChoice.modelData === "BUY" ? RuntimeTheme.GGTheme.positive : root.red; font: sideInput.font; verticalAlignment: Text.AlignVCenter }
                            background: Rectangle { color: sideChoice.highlighted ? RuntimeTheme.GGTheme.line : RuntimeTheme.GGTheme.panel }
                        }
                        popup: Popup {
                            y: sideInput.height + 3
                            width: sideInput.width
                            padding: 1
                            implicitHeight: sideList.implicitHeight + 2
                            background: Rectangle { color: RuntimeTheme.GGTheme.panel; border.color: RuntimeTheme.GGTheme.edge; radius: 2 }
                            contentItem: ListView {
                                id: sideList
                                clip: true
                                implicitHeight: contentHeight
                                model: sideInput.popup.visible ? sideInput.delegateModel : null
                                currentIndex: sideInput.highlightedIndex
                                boundsBehavior: Flickable.StopAtBounds
                            }
                        }
                    }
                }
                Column {
                    width: Math.min(220, parent.width)
                    spacing: 5
                    Label { colorKey: "ui.CryptoPumpPanel.23"; text: sideInput.currentText === "BUY" ? "SPEND · " + root.quoteSymbol : "SELL · TOKEN" }
                    CryptoField { property string uiColorScope: "ui.widget.CryptoPumpPanel.CryptoField.10";
                        id: amountInput
                        objectName: "cryptoPumpAmount"
                        width: parent.width
                        height: 36
                        enabled: !root.busy
                        placeholderText: "Amount, e.g. 0.1"
                        placeholderTextColor: root.muted
                        inputMethodHints: Qt.ImhFormattedNumbersOnly
                        validator: RegularExpressionValidator { regularExpression: /[0-9]+(\.[0-9]*)?/ }
                        Accessible.name: "Input amount in decimal units"
                        KeyNavigation.tab: slippageInput
                        onAccepted: if (quoteButton.enabled) root.run("quote")
                    }
                }
                Column {
                    width: Math.min(140, parent.width)
                    spacing: 5
                    Label { colorKey: "ui.CryptoPumpPanel.24"; text: "SLIPPAGE · BPS" }
                    CryptoField { property string uiColorScope: "ui.widget.CryptoPumpPanel.CryptoField.11";
                        id: slippageInput
                        objectName: "cryptoPumpSlippage"
                        width: parent.width
                        height: 36
                        enabled: !root.busy
                        text: "100"
                        validator: IntValidator { bottom: 0; top: 10000 }
                        Accessible.name: "Slippage in basis points; 100 means one percent"
                        KeyNavigation.tab: quoteButton
                    }
                }
            }
            Note { colorKey: "ui.CryptoPumpPanel.25"; text: "100 bps = 1%. A fresh estimate is required after editing any input."; font.pixelSize: 11 }
            Note { colorKey: "ui.CryptoPumpPanel.26";
                visible: root.data.stale === true || (root.inspected && !root.currentQuote)
                text: root.data.stale === true ? "Snapshot is stale. Inspect again before quoting." : "Request a quote to unlock simulation and a paper fill."
                color: root.gold
            }
            Flow {
                width: parent.width
                spacing: 8
                Action { property string uiColorScope: "ui.control.CryptoPumpPanel.5";
                    id: quoteButton
                    objectName: "cryptoPumpQuote"
                    text: "Get estimate"
                    primary: true
                    enabled: !root.busy && root.fresh && amountInput.acceptableInput && amountInput.text.length > 0 && slippageInput.acceptableInput
                    KeyNavigation.tab: simulateButton
                    onClicked: root.run("quote")
                }
                Action { property string uiColorScope: "ui.control.CryptoPumpPanel.6";
                    id: simulateButton
                    objectName: "cryptoPumpSimulate"
                    text: "Simulate unsigned"
                    enabled: !root.busy && root.currentQuote
                    KeyNavigation.tab: paperButton
                    onClicked: root.run("simulate")
                }
                Action { property string uiColorScope: "ui.control.CryptoPumpPanel.7";
                    id: paperButton
                    objectName: "cryptoPumpPaperTrade"
                    text: "Record paper fill"
                    enabled: !root.busy && root.currentQuote
                    KeyNavigation.tab: resetButton
                    onClicked: root.run("paper")
                }
            }
            Note { colorKey: "ui.CryptoPumpPanel.27"; text: "Paper uses simulated cash. Unsigned simulation does not submit a transaction."; font.pixelSize: 11 }
            Note { colorKey: "ui.CryptoPumpPanel.28"; visible: !!root.quote.error; color: root.red; text: String(root.quote.error || "") }
            Column {
                width: parent.width
                spacing: 5
                visible: String(root.quote.amount_out || root.quote.amount_out_atoms || "").length > 0
                Label { colorKey: "ui.CryptoPumpPanel.29"; text: root.currentQuote ? "ESTIMATED RECEIVE" : "PREVIOUS ESTIMATE · REFRESH REQUIRED" }
                Note { colorKey: "ui.CryptoPumpPanel.30"; text: root.quantity(root.quote, "amount_out", sideInput.currentText === "BUY" ? "TOKEN" : root.quoteSymbol); font.pixelSize: 22; font.bold: true; color: root.currentQuote ? root.ink : root.muted }
            }
            CopyValue { property string uiColorScope: "ui.widget.CryptoPumpPanel.CopyValue.15";
                objectName: "cryptoPumpQuoteDetails"
                visible: String(root.quote.amount_out || root.quote.amount_out_atoms || "").length > 0
                Accessible.name: "Quote and total wallet costs"
                text: "Side: " + root.value(root.quote, "side")
                    + "\nInput: " + root.quantity(root.quote, "amount_in", sideInput.currentText === "BUY" ? root.quoteSymbol : "TOKEN")
                    + "\nOutput: " + root.quantity(root.quote, "amount_out", sideInput.currentText === "BUY" ? "TOKEN" : root.quoteSymbol)
                    + "\nWallet debit: " + root.quantity(root.quote, "wallet_debit", root.quoteSymbol)
                    + "\nWallet credit: " + root.quantity(root.quote, "wallet_credit", root.quoteSymbol)
                    + "\nMinimum received: " + root.quantity(root.quote, "min_out")
                    + "\nMaximum cost: " + root.quantity(root.quote, "max_cost", root.quoteSymbol)
                    + "\nPrice impact: " + (root.quote.price_impact_pct !== undefined ? root.value(root.quote, "price_impact_pct") + "%" : root.value(root.quote, "price_impact_bps") + " bps")
            }
            Repeater {
                model: (root.quote.fees || []).slice(0, 20)
                delegate: Note { colorKey: "ui.CryptoPumpPanel.31";
                    required property var modelData
                    text: root.value(modelData, "label", "Fee") + ": "
                        + root.quantity(modelData, "amount", root.value(modelData, "symbol", root.quoteSymbol))
                    font.pixelSize: 11
                }
            }
        }

        Card { property string uiColorScope: "ui.widget.CryptoPumpPanel.Card.16";
            objectName: "cryptoPumpStressCard"
            visible: root.currentQuote && !root.busy && (root.stress.rows || []).length > 0
            kicker: "COST & LIQUIDITY"
            title: "Stress the estimate"
            Note { colorKey: "ui.CryptoPumpPanel.32"; text: "Independent hypothetical scenarios against the original slippage bounds. These are assumptions, not forecast probabilities." }
            Repeater {
                model: (root.stress.rows || []).slice(0, 10)
                delegate: Rectangle {
                    id: stressItem
                    objectName: "cryptoPumpStressRow"
                    required property var modelData
                    width: parent.width
                    height: stressRow.implicitHeight + 18
                    color: "#151515"
                    border.color: RuntimeTheme.GGTheme.edge
                    radius: 2
                    Column {
                        id: stressRow
                        x: 9; y: 9
                        width: parent.width - 18
                        spacing: 4
                        Note { colorKey: "ui.CryptoPumpPanel.33"; text: root.value(stressItem.modelData, "label", "Scenario"); font.bold: true; color: root.ink }
                        Note { colorKey: "ui.CryptoPumpPanel.34"; visible: stressItem.modelData.supported === true; text: "Debit " + root.value(stressItem.modelData, "debit_display") + " → Receive " + root.value(stressItem.modelData, "received_display"); font.pixelSize: 11 }
                        Label { colorKey: "ui.CryptoPumpPanel.35";
                            text: stressItem.modelData.supported !== true ? "UNSUPPORTED · " + root.value(stressItem.modelData, "error")
                                : stressItem.modelData.within_slippage === true ? "WITHIN ORIGINAL BOUNDS" : "BREACHES ORIGINAL BOUNDS"
                            color: stressItem.modelData.supported !== true ? root.red : stressItem.modelData.within_slippage === true ? RuntimeTheme.GGTheme.positive : root.gold
                        }
                    }
                }
            }
            Note { colorKey: "ui.CryptoPumpPanel.36"; text: "Swap costs only. Network fees, rent, MEV and inclusion are outside these estimates."; font.pixelSize: 11 }
        }

        Card { property string uiColorScope: "ui.widget.CryptoPumpPanel.Card.17";
            kicker: "03 / VERIFY"
            title: "Unsigned simulation"
            Note { colorKey: "ui.CryptoPumpPanel.37";
                objectName: "cryptoPumpSimulationWallet"
                visible: root.value(root.simulation, "wallet", "").length > 0
                text: {
                    var address = root.value(root.simulation, "wallet", "")
                    return "Public payer · " + (address.length > 16 ? address.slice(0, 6) + "…" + address.slice(-6) : address)
                }
            }
            Note { colorKey: "ui.CryptoPumpPanel.38";
                objectName: "cryptoPumpSimulationState"
                text: root.value(root.simulation, "state", "Not run").toUpperCase()
                    + " · Units: " + root.value(root.simulation, "units")
                    + " · Network fee: " + root.value(root.simulation, "fee_lamports") + " lamports"
                    + (root.simulation.error ? "\n" + String(root.simulation.error) : "")
                color: root.simulation.error ? root.red : root.muted
            }
            Repeater {
                model: (root.simulation.balance_changes || []).slice(0, 32)
                delegate: Note { colorKey: "ui.CryptoPumpPanel.39";
                    required property var modelData
                    font.pixelSize: 11
                    wrapMode: Text.WrapAnywhere
                    text: typeof modelData === "string" ? modelData : root.value(modelData, "account", root.value(modelData, "address", root.value(modelData, "mint")))
                        + " · " + root.quantity(modelData, "delta", root.value(modelData, "symbol", ""))
                }
            }
            Action { property string uiColorScope: "ui.control.CryptoPumpPanel.8"; visible: (root.simulation.logs || []).length > 0; text: (root.simulationLogsOpen ? "▾ " : "▸ ") + "Program logs"; onClicked: root.simulationLogsOpen = !root.simulationLogsOpen }
            ScrollView {
                id: logScroll
                width: parent.width
                height: Math.min(200, logText.implicitHeight)
                visible: root.simulationLogsOpen && (root.simulation.logs || []).length > 0
                clip: true
                contentWidth: availableWidth
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                CopyValue { property string uiColorScope: "ui.widget.CryptoPumpPanel.CopyValue.19";
                    id: logText
                    objectName: "cryptoPumpSimulationLogs"
                    width: logScroll.availableWidth
                    Accessible.name: "Simulation logs"
                    text: (root.simulation.logs || []).slice(-80).map(function(line) { return String(line).slice(0, 600) }).join("\n")
                }
            }
        }

        Card { property string uiColorScope: "ui.widget.CryptoPumpPanel.Card.20";
            kicker: "PAPER / SEPARATE LEDGER"
            title: "Simulated account"
            Note { colorKey: "ui.CryptoPumpPanel.40";
                objectName: "cryptoPumpPaperSummary"
                text: "Cash: " + root.quantity(root.paper, "cash", root.value(root.paper, "quote_symbol", root.quoteSymbol))
                    + "\nEquity: " + root.quantity(root.paper, "equity", root.value(root.paper, "quote_symbol", root.quoteSymbol))
                    + (root.paper.error ? "\n" + String(root.paper.error) : "")
                color: root.paper.error ? root.red : root.ink
                font.pixelSize: 14
            }
            Note { colorKey: "ui.CryptoPumpPanel.41"; visible: (root.paper.positions || []).length === 0; text: "No positions yet. An executed paper estimate appears here." }
            Repeater {
                model: (root.paper.positions || []).slice(0, 40)
                delegate: CopyValue { property string uiColorScope: "ui.widget.CryptoPumpPanel.CopyValue.21";
                    required property var modelData
                    Accessible.name: "Paper position"
                    text: root.value(modelData, "symbol", "TOKEN") + " · " + root.value(modelData, "mint")
                        + "\nQuantity: " + root.quantity(modelData, "quantity")
                        + " · Value: " + root.quantity(modelData, "value", root.quoteSymbol)
                }
            }
            Label { colorKey: "ui.CryptoPumpPanel.42"; visible: (root.paper.fills || []).length > 0; text: "RECENT PAPER FILLS" }
            Repeater {
                model: (root.paper.fills || []).slice(-40).reverse()
                delegate: Note { colorKey: "ui.CryptoPumpPanel.43";
                    required property var modelData
                    font.pixelSize: 11
                    wrapMode: Text.WrapAnywhere
                    text: "PAPER · " + root.value(modelData, "side") + " · " + root.value(modelData, "mint")
                        + "\n" + root.value(modelData, "timestamp", root.value(modelData, "ts"))
                        + " · Input " + root.quantity(modelData, "amount_in") + " · Output " + root.quantity(modelData, "amount_out")
                }
            }
            Action { property string uiColorScope: "ui.control.CryptoPumpPanel.9";
                id: resetButton
                objectName: "cryptoPumpPaperReset"
                text: "Reset paper account"
                destructive: true
                enabled: !root.busy
                KeyNavigation.tab: mintInput
                onClicked: root.run("reset")
            }
        }
        Item { width: 1; height: 8 }
    }
}
