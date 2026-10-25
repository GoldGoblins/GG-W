import QtQuick
import "LiveEyesStatus.js" as EyesStatus
import QtQuick.Controls

Item {
    id: root

    property string modelState: "READY"
    property string engineTarget: "GROK_TUI"
    property string grokWalletJson: "{}"
    property string gptWalletJson: "{}"
    property string liveVisionStatusJson: '{"state":"off"}'
    readonly property var eyes: {
        try { return JSON.parse(root.liveVisionStatusJson) } catch (err) { return {state: "off"} }
    }
    property string bridgeState: "CONNECTED"
    property bool compactMode: true
    property var snippetModel: null
    property string activeSnippet: ""
    property string chatSessionsJson: "[]"
    property string activeChatSession: ""
    property string cryptoStatusJson: "{}"
    property var cryptoSnapshot: null
    signal snippetChosen(string path)
    signal chatSessionChosen(string sessionId, string engine)
    signal cryptoAccountChosen(string pubkey)

    readonly property string modelDetails:
        "Local model runner is connected.\n"
        + "Inference stays local with network disabled."

    readonly property string bridgeDetails:
        "Skriv vad du vill göra i chatten.\n"
        + "Om uppgiften behöver ett godkännande frågar chatten en gång: "
        + "svara ja för att fortsätta eller nej för att avbryta.\n"
        + "Inga hashvärden, tokens eller specialkommandon behövs.\n"
        + "Login och 2FA görs synligt av dig när en tjänst frågar efter det.\n"
        + "Lösenord stannar utanför chat, loggar och filer. Backup, verifiering "
        + "och rollback hanteras inom den aktuella uppgiften."

    property color frameBorder: "#4a4a4a"
    property int frameRadius: 4

    readonly property var wallet: {
        var empty = {
            "context_label": "—",
            "session_total_label": "—",
            "turn_label": "—",
            "live_label": "—",
            "live_tokens": 0,
            "weekly_percent": null
        }
        try {
            var parsed = JSON.parse(
                root.engineTarget === "GPT_TUI"
                    ? (root.gptWalletJson || "{}")
                    : (root.grokWalletJson || "{}")
            )
            if (!parsed || typeof parsed !== "object")
                return empty
            parsed.context_label = parsed.context_label || "—"
            parsed.session_total_label = parsed.session_total_label || "—"
            parsed.turn_label = parsed.turn_label || "—"
            parsed.live_label = parsed.live_label || "—"
            if (parsed.live_tokens === undefined)
                parsed.live_tokens = 0
            if (parsed.weekly_percent === undefined || parsed.weekly_percent === "")
                parsed.weekly_percent = null
            return parsed
        } catch (err) {
            return empty
        }
    }

    readonly property var chatSessions: {
        try {
            var parsed = JSON.parse(root.chatSessionsJson || "[]")
            if (parsed && parsed.length !== undefined)
                return parsed
        } catch (err) {
        }
        return []
    }

    readonly property var crypto: {
        var empty = {
            "legend": "",
            "signer": false,
            "accounts": [],
            "holdings": [],
            "wallet": {}
        }
        try {
            var parsed = root.cryptoSnapshot || JSON.parse(root.cryptoStatusJson || "{}")
            if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
                return empty
            return Object.assign({}, parsed, {
                holdings: Array.isArray(parsed.holdings) ? parsed.holdings : [],
                accounts: Array.isArray(parsed.accounts) ? parsed.accounts : [],
                wallet: parsed.wallet || ({})
            })
        } catch (err) {
            return empty
        }
    }

    implicitWidth: root.compactMode ? 168 : 220
    implicitHeight: 560

    Column {
        id: topStack
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        spacing: 10

        GgFrame {
            width: parent.width
            leftLegend: "MODEL"
            rightLegend: root.modelState
            busy: root.modelState === "BUSY"
            backgroundColor: "#161616"
            borderColor: root.frameBorder
            radius: root.frameRadius
            compact: true

            Column {
                width: parent.width
                spacing: 4

                Text {
                    width: parent.width
                    text: (
                        root.engineTarget === "GPT_TUI" ? "GPTUI" :
                        root.engineTarget === "GROK_TUI"
                            ? "GROK TUI"
                            : (
                                root.engineTarget === "GROK_WORKER"
                                    ? "GROK WORKER"
                                    : "LOCAL QWEN"
                            )
                    )
                        + " · "
                        + root.modelState
                    color: "#c8cdd4"
                    wrapMode: Text.WordWrap
                    font.pixelSize: 12
                }

                Column {
                    width: parent.width
                    spacing: 2
                    visible: root.engineTarget === "GROK_TUI" || root.engineTarget === "GPT_TUI"
                    objectName: "grokWallet"

                    Text {
                        objectName: "liveEyesTelemetry"
                        width: parent.width
                        visible: root.eyes.state !== "off"
                        wrapMode: Text.WordWrap
                        textFormat: Text.PlainText
                        font.pixelSize: 11
                        color: EyesStatus.fresh(root.eyes) ? "#9ed5a4" : "#e4c06a"
                        text: EyesStatus.details(root.eyes)
                    }

                    Text {
                        width: parent.width
                        text: "WALLET"
                        color: "#a8b0b8"
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                    Text {
                        width: parent.width
                        text: "CTX  " + root.wallet.context_label
                        color: "#d8dee9"
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                    Text {
                        width: parent.width
                        text: "ALL  " + root.wallet.session_total_label
                        color: "#d8dee9"
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                    Text {
                        width: parent.width
                        text: "TURN " + root.wallet.turn_label
                        color: "#c8cdd4"
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                    Text {
                        width: parent.width
                        text: "LIVE " + root.wallet.live_label
                        color: root.wallet.live_tokens > 0 ? "#c8a97e" : "#c8cdd4"
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                    Rectangle {
                        width: parent.width
                        height: 6
                        color: "#2a2a2a"
                        radius: 1

                        Rectangle {
                            height: parent.height
                            width: parent.width * Math.max(
                                0,
                                Math.min(1, Number(root.wallet.live_tokens || 0) / 100)
                            )
                            color: "#c8a97e"
                            radius: 1
                        }
                    }
                    Text {
                        width: parent.width
                        text: "LIVE RESET  " + (root.wallet.live_reset_label || "—")
                        color: "#8b949e"
                        font.family: "monospace"
                        font.pixelSize: 11
                    }
                    Text {
                        width: parent.width
                        text: "WEEK "
                            + (
                                root.wallet.weekly_percent === null
                                || root.wallet.weekly_percent === undefined
                                    ? "—"
                                    : (Number(root.wallet.weekly_percent) + "%")
                            )
                        color: "#c8cdd4"
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                    Rectangle {
                        width: parent.width
                        height: 6
                        color: "#2a2a2a"
                        radius: 1

                        Rectangle {
                            height: parent.height
                            width: parent.width * Math.max(
                                0,
                                Math.min(
                                    1,
                                    (root.wallet.weekly_percent === null
                                        ? 0
                                        : root.wallet.weekly_percent) / 100
                                )
                            )
                            color: "#8db89a"
                            radius: 1
                        }
                    }
                }
            }
        }

        GgFrame {
            width: parent.width
            leftLegend: "BRIDGE"
            rightLegend: root.bridgeState
            busy: root.bridgeState === "BUSY"
            backgroundColor: "#161616"
            borderColor: root.frameBorder
            radius: root.frameRadius
            compact: true

            Text {
                width: parent.width
                text: "CHAT → MODEL\nCONNECTED\nLOGIN / 2FA VIA WEB"
                color: "#c8cdd4"
                wrapMode: Text.WordWrap
                font.family: "monospace"
                font.pixelSize: 12
            }
        }
    }

    GgFrame {
        id: snippetFrame
        objectName: "telemetrySnippetList"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: topStack.bottom
        anchors.topMargin: 10
        height: Math.max(
            64,
            Math.round(
                (root.height - topStack.height - 20) * 2 / 5
            )
        )
        leftLegend: "SNIPPETS"
        rightLegend: "SITE"
        backgroundColor: "#161616"
        borderColor: root.frameBorder
        radius: root.frameRadius
        compact: true

        Flickable {
            id: snippetFlick
            width: parent.width
            height: Math.max(72, snippetFrame.height - 28)
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            flickableDirection: Flickable.VerticalFlick
            contentWidth: width
            contentHeight: snippetColumn.height
            interactive: contentHeight > height

            Column {
                id: snippetColumn
                width: snippetFlick.width
                spacing: 6

                Repeater {
                    model: root.snippetModel

                    delegate: Text {
                        required property string path
                        width: snippetColumn.width
                        text: path
                        color: path === root.activeSnippet
                            ? "#d8dee9"
                            : "#8b949e"
                        font.family: "monospace"
                        font.pixelSize: 12
                        font.bold: path === root.activeSnippet
                        wrapMode: Text.NoWrap
                        elide: Text.ElideMiddle

                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.snippetChosen(path)
                        }
                    }
                }
            }

            ScrollBar.vertical: GgScrollBar {}
        }
    }

    GgFrame {
        id: chatFrame
        objectName: "telemetryChatList"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: snippetFrame.bottom
        anchors.topMargin: 10
        height: Math.max(
            56,
            Math.round(
                (root.height - snippetFrame.y - snippetFrame.height - 10) / 2
            )
        )
        leftLegend: "CHATS"
        rightLegend: "MEMORY"
        backgroundColor: "#161616"
        borderColor: root.frameBorder
        radius: root.frameRadius
        compact: true

        Flickable {
            id: chatFlick
            width: parent.width
            height: Math.max(48, chatFrame.height - 28)
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            flickableDirection: Flickable.VerticalFlick
            contentWidth: width
            contentHeight: chatColumn.height
            interactive: contentHeight > height

            Column {
                id: chatColumn
                width: chatFlick.width
                spacing: 6

                Text {
                    width: chatColumn.width
                    visible: root.chatSessions.length === 0
                    text: "NO DESKTOP CHATS"
                    color: "#a8b0b8"
                    font.family: "monospace"
                    font.pixelSize: 12
                }

                Repeater {
                    model: root.chatSessions

                    delegate: Rectangle {
                        required property var modelData
                        width: chatColumn.width
                        height: 18
                        color: chatMouse.containsMouse ? "#242424" : "transparent"

                        Text {
                            anchors.fill: parent
                            text: String(modelData.label || "")
                            color: String(modelData.session_id) === root.activeChatSession
                                ? "#d8dee9"
                                : "#8b949e"
                            font.family: "monospace"
                            font.pixelSize: 12
                            font.bold: String(modelData.session_id) === root.activeChatSession
                            verticalAlignment: Text.AlignVCenter
                            wrapMode: Text.NoWrap
                            elide: Text.ElideRight
                        }

                        MouseArea {
                            id: chatMouse
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.chatSessionChosen(
                                String(modelData.session_id),
                                String(modelData.engine || "GROK_TUI")
                            )
                        }
                    }
                }
            }

            ScrollBar.vertical: GgScrollBar {}
        }
    }

    GgFrame {
        id: cryptoFrame
        objectName: "telemetryCryptoWallet"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: chatFrame.bottom
        anchors.topMargin: 10
        anchors.bottom: parent.bottom
        leftLegend: "CRYPTO"
        rightLegend: String(root.crypto.legend || "—")
        backgroundColor: "#161616"
        borderColor: root.frameBorder
        radius: root.frameRadius
        compact: true

        Flickable {
            id: cryptoFlick
            width: parent.width
            height: Math.max(48, cryptoFrame.height - 28)
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            flickableDirection: Flickable.VerticalFlick
            contentWidth: width
            contentHeight: cryptoColumn.height
            interactive: contentHeight > height

            Column {
                id: cryptoColumn
                width: cryptoFlick.width
                spacing: 8
                readonly property var wallet: root.crypto.wallet || ({})
                readonly property bool connected: String(wallet.pubkey || "").length > 12
                readonly property bool observe: ["MAINNET", "OBSERVE"].indexOf(String(root.crypto.legend || "")) >= 0
                    || String(wallet.network || "").toLowerCase() === "mainnet"

                Text {
                    width: parent.width
                    text: cryptoColumn.observe ? "MAINNET · READ ONLY"
                        : ["LOCALNET", "TESTNET"].indexOf(String(root.crypto.legend || "")) >= 0 ? "PAPER / LAB"
                        : "NÄTVERK OKÄNT"
                    color: "#e6edf3"
                    font.family: "monospace"; font.pixelSize: 10
                    elide: Text.ElideRight
                }
                Rectangle {
                    width: parent.width; height: railBalance.height + 18
                    color: "#161616"; radius: 3; border.color: "#6a6a6a"
                    Column {
                        id: railBalance
                        x: 8; y: 9; width: parent.width - 16; spacing: 4
                        Text {
                            width: parent.width
                            text: cryptoColumn.connected
                                ? String(cryptoColumn.wallet.pubkey).slice(0, 4) + "…" + String(cryptoColumn.wallet.pubkey).slice(-4)
                                : "INGET KONTO"
                            color: cryptoColumn.connected ? "#e6edf3" : "#9aa3ad"
                            font.family: "monospace"; font.pixelSize: 11; font.bold: true
                            elide: Text.ElideMiddle; textFormat: Text.PlainText
                        }
                        Text {
                            objectName: "cryptoRailBalance"
                            width: parent.width; visible: cryptoColumn.connected
                            text: String(cryptoColumn.wallet.balance_sol === undefined || cryptoColumn.wallet.balance_sol === null
                                ? "—" : cryptoColumn.wallet.balance_sol) + " SOL"
                            color: "#c8cdd4"
                            font.family: "monospace"; font.pixelSize: 11
                            elide: Text.ElideRight; textFormat: Text.PlainText
                        }
                    }
                }

                Repeater {
                    model: root.crypto.accounts || []
                    delegate: CryptoButton {
                        id: accountButton
                        required property var modelData
                        width: cryptoColumn.width; height: 26
                        enabled: String((root.crypto.ui_operation || {}).state || "") !== "running"
                        hoverEnabled: true; activeFocusOnTab: true
                        Accessible.name: "Välj kryptokonto " + String(modelData.short || "")
                        tip: String(modelData.pubkey || "")
                        text: (modelData.active ? "● " : "  ") + String(modelData.short || "Konto")
                        color: modelData.active ? "#e6edf3" : "#9aa3ad"
                        checked: Boolean(modelData.active)
                        font.family: "monospace"; font.pixelSize: 10
                        font.bold: Boolean(modelData.active)
                        horizontalAlignment: Text.AlignLeft
                        onClicked: {
                            var key = String(modelData.pubkey || "")
                            if (key && !modelData.active) root.cryptoAccountChosen(key)
                        }
                    }
                }

                Text {
                    width: parent.width
                    text: String((root.crypto.lab && root.crypto.lab.label) || "LAB · OKÄND")
                    color: (root.crypto.lab && root.crypto.lab.healthy) ? "#8db89a" : "#9aa3ad"
                    font.family: "monospace"; font.pixelSize: 10
                    elide: Text.ElideRight; textFormat: Text.PlainText
                }
                Text {
                    objectName: "cryptoRailPumpState"
                    width: parent.width
                    readonly property var pump: root.crypto.pump || ({})
                    visible: String(pump.mint || "").length > 0
                    text: "PUMP · " + String(pump.state || "idle").toUpperCase()
                        + (pump.stale === true ? " · STALE" : "") + "\nMAINNET · READ ONLY"
                    color: pump.error ? "#c98989" : "#c8cdd4"
                    font.family: "monospace"; font.pixelSize: 10
                    wrapMode: Text.WrapAnywhere; textFormat: Text.PlainText
                }
                Text {
                    objectName: "cryptoRailRpcStatus"
                    width: parent.width
                    visible: cryptoColumn.connected && (cryptoColumn.wallet.rpc_loading === true
                        || cryptoColumn.wallet.rpc_stale === true || String(cryptoColumn.wallet.rpc_error || "").length > 0)
                    text: cryptoColumn.wallet.rpc_loading ? "HÄMTAR SALDO…"
                        : cryptoColumn.wallet.rpc_error ? "HÄMTNING MISSLYCKADES" : "SENAST HÄMTADE SALDO"
                    color: "#c8a97e"
                    font.family: "monospace"; font.pixelSize: 10; wrapMode: Text.WordWrap
                }
                Rectangle { width: parent.width; height: 1; color: "#6a6a6a" }
                Text {
                    width: parent.width
                    text: "TILLGÅNGAR · " + root.crypto.holdings.length
                    color: "#9aa3ad"
                    font.family: "monospace"; font.pixelSize: 10
                }
                Text {
                    width: parent.width; visible: root.crypto.holdings.length === 0
                    text: !cryptoColumn.connected ? "Anslut en plånbok"
                        : root.crypto.refreshing || cryptoColumn.wallet.rpc_loading ? "Hämtar tillgångar…"
                        : cryptoColumn.wallet.rpc_error ? "Tillgångar ej tillgängliga" : "Inga tillgångar"
                    color: "#9aa3ad"
                    font.family: "monospace"; font.pixelSize: 11; wrapMode: Text.WordWrap
                }
                Repeater {
                    model: root.crypto.holdings
                    delegate: Item {
                        required property var modelData
                        width: cryptoColumn.width; height: 34
                        Text {
                            width: parent.width
                            text: String(modelData.symbol || "TOKEN")
                            color: "#c8cdd4"
                            font.family: "monospace"; font.pixelSize: 10; font.bold: true
                            elide: Text.ElideRight; textFormat: Text.PlainText
                        }
                        Text {
                            y: 16; width: parent.width
                            text: String(modelData.display === undefined || modelData.display === null ? "—" : modelData.display)
                            color: "#e6edf3"
                            font.family: "monospace"; font.pixelSize: 11
                            elide: Text.ElideRight; textFormat: Text.PlainText
                        }
                    }
                }
            }
            ScrollBar.vertical: GgScrollBar {}
        }
    }
}
