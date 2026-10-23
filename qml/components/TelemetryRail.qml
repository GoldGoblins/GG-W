import QtQuick
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
            "legend": "TESTNET",
            "signer": false,
            "accounts": [],
            "holdings": [],
            "wallet": {}
        }
        try {
            var parsed = JSON.parse(root.cryptoStatusJson || "{}")
            if (!parsed || typeof parsed !== "object")
                return empty
            if (!parsed.holdings)
                parsed.holdings = []
            if (!parsed.wallet)
                parsed.wallet = {}
            return parsed
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
                        width: parent.width
                        visible: root.eyes.state !== "off"
                        wrapMode: Text.WordWrap
                        font.pixelSize: 11
                        color: root.eyes.state === "live" && root.eyes.frame_age_ms <= 2000 ? "#9ed5a4" : "#e4c06a"
                        text: {
                            if (root.eyes.state === "live") {
                                var delivered = root.eyes.last_delivered_age_ms
                                return "ÖGON · " + (root.eyes.received_fps || 0) + " fps\n"
                                    + (delivered === null || delivered === undefined
                                       ? "Ingen bild hämtad av AI ännu"
                                       : "Bild hämtad " + Math.round(delivered / 1000) + " s sedan")
                                    + "\nRAM " + ((root.eyes.buffer_bytes || 0) / 1048576).toFixed(1) + " MiB"
                            }
                            return "ÖGON · " + (root.eyes.reason || "Väntar på skärmdelning")
                        }
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
        rightLegend: String(root.crypto.legend || "TESTNET")
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
                spacing: 4

                Text {
                    width: parent.width
                    visible: (root.crypto.accounts || []).length === 0
                    text: {
                        var w = root.crypto.wallet || {}
                        if (!w.pubkey)
                            return "DISCONNECTED"
                        var key = String(w.pubkey)
                        if (key.length > 12)
                            return key.slice(0, 4) + "…" + key.slice(-4)
                        return key
                    }
                    color: (root.crypto.wallet && root.crypto.wallet.pubkey)
                        ? "#8db89a"
                        : "#6a6a6a"
                    font.family: "monospace"
                    font.pixelSize: 12
                    wrapMode: Text.NoWrap
                    elide: Text.ElideMiddle
                }

                Repeater {
                    model: root.crypto.accounts || []
                    delegate: Text {
                        required property var modelData
                        width: cryptoColumn.width
                        text: String(modelData.short || "")
                        color: modelData.active ? "#8db89a" : "#8b949e"
                        font.family: "monospace"
                        font.pixelSize: 12
                        font.bold: Boolean(modelData.active)
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                var key = String(modelData.pubkey || "")
                                if (key)
                                    root.cryptoAccountChosen(key)
                            }
                        }
                    }
                }

                Text {
                    width: parent.width
                    text: String((root.crypto.lab && root.crypto.lab.label) || "LAB OFF")
                    color: (root.crypto.lab && root.crypto.lab.running)
                        ? "#8db89a"
                        : "#8b949e"
                    font.family: "monospace"
                    font.pixelSize: 12
                }

                Text {
                    width: parent.width
                    visible: root.crypto.holdings.length === 0
                    text: "NO TOKENS"
                    color: "#a8b0b8"
                    font.family: "monospace"
                    font.pixelSize: 12
                }

                Repeater {
                    model: root.crypto.holdings

                    delegate: Column {
                        required property var modelData
                        width: cryptoColumn.width
                        spacing: 0

                        Text {
                            width: parent.width
                            text: String(modelData.symbol || "")
                            color: "#c8cdd4"
                            font.family: "monospace"
                            font.pixelSize: 12
                        }
                        Text {
                            width: parent.width
                            text: String(modelData.display || "")
                            color: "#d8dee9"
                            font.family: "monospace"
                            font.pixelSize: 12
                            wrapMode: Text.WrapAnywhere
                        }
                    }
                }
            }

            ScrollBar.vertical: GgScrollBar {}
        }
    }
}
