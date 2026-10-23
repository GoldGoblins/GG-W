import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs

Rectangle {
    id: root
    objectName: "walletPopup"
    width: root.visualWidth > 0 ? root.visualWidth : 328
    height: root.visualHeight > 0
        ? root.visualHeight
        : Math.min(520, 18 + bodyCol.height + 16)
    color: "#161616"
    border.color: root.frameBorder
    border.width: 1
    radius: root.frameRadius

    property color frameBorder: "#4a4a4a"
    property int frameRadius: 4
    property real visualWidth: -1
    property real visualHeight: -1
    property bool layoutLocked: true
    property var surfaceHost: null
    property string statusJson: "{}"
    signal requestClose()
    signal openDesk()
    signal walletStatusUpdated(string raw)

    readonly property color ink: "#e6edf3"
    readonly property color muted: "#8b949e"
    readonly property color gold: "#c8a97e"
    readonly property color green: "#8db89a"

    readonly property var status: {
        try {
            return JSON.parse(root.statusJson || "{}")
        } catch (err) {
            return {}
        }
    }
    readonly property var wallet: root.status.wallet || {}
    readonly property var quote: root.status.quote || {}
    readonly property var holdings: root.status.holdings || []
    readonly property var lab: root.status.lab || {}
    readonly property string pubkey: String(root.wallet.pubkey || "")
    readonly property bool connected: root.pubkey.length > 12
    readonly property string shortKey: root.connected
        ? (root.pubkey.slice(0, 4) + "…" + root.pubkey.slice(-4))
        : "NONE"
    readonly property string legend: String(root.status.legend || "TESTNET")
    readonly property bool observe: root.legend === "OBSERVE" || root.legend === "MAINNET"
    property string copied: ""

    function pull() {
        if (!root.surfaceHost || !root.surfaceHost.cryptoStatus)
            return
        var raw = root.surfaceHost.cryptoStatus()
        if (raw && raw !== root.statusJson) {
            root.statusJson = raw
            root.walletStatusUpdated(raw)
        }
    }

    function applyRaw(raw) {
        if (!raw)
            return
        root.statusJson = raw
        root.walletStatusUpdated(raw)
    }

    function copyAddr() {
        if (!root.connected)
            return
        if (root.surfaceHost && root.surfaceHost.tmogCopy)
            root.surfaceHost.tmogCopy(root.pubkey)
        root.copied = "COPIED"
        copyReset.restart()
    }

    Timer {
        id: copyReset
        interval: 1400
        onTriggered: root.copied = ""
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        onClicked: {}
    }

    Rectangle {
        z: 3
        visible: true
        anchors.left: parent.left
        anchors.leftMargin: 12
        anchors.top: parent.top
        anchors.topMargin: -8
        height: 18
        width: leftLegendText.implicitWidth + 12
        color: root.color
        radius: 3
        Text {
            id: leftLegendText
            anchors.centerIn: parent
            text: {
                if (!root.connected)
                    return "NO ACCOUNT"
                if (!root.status.signer)
                    return root.shortKey + "  ·  WATCH"
                return root.shortKey
            }
            color: root.ink
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: true
        }
    }

    Rectangle {
        z: 3
        anchors.right: parent.right
        anchors.rightMargin: 12
        anchors.top: parent.top
        anchors.topMargin: -8
        height: 18
        width: rightLegendRow.implicitWidth + 12
        color: root.color
        radius: 3

        Row {
            id: rightLegendRow
            anchors.centerIn: parent
            spacing: 8

            Text {
                id: gripDots
                objectName: "walletDragBar"
                text: "⋮⋮"
                color: root.muted
                font.family: "monospace"
                font.pixelSize: 11
                anchors.verticalCenter: parent.verticalCenter
                MouseArea {
                    anchors.fill: parent
                    anchors.margins: -4
                    drag.target: root
                    drag.smoothed: false
                    drag.minimumX: 0
                    drag.minimumY: 0
                    drag.maximumX: root.parent ? Math.max(0, root.parent.width - root.width) : 4096
                    drag.maximumY: root.parent ? Math.max(0, root.parent.height - 48) : 4096
                    cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                }
            }

            Rectangle {
                width: 1
                height: 12
                color: root.frameBorder
                anchors.verticalCenter: parent.verticalCenter
            }

            Text {
                text: "✕"
                color: root.muted
                font.family: "monospace"
                font.pixelSize: 12
                anchors.verticalCenter: parent.verticalCenter
                MouseArea {
                    anchors.fill: parent
                    anchors.margins: -4
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.requestClose()
                }
            }
        }
    }

    FileDialog {
        id: keypairDialog
        title: "IMPORT SOLANA KEYPAIR"
        fileMode: FileDialog.OpenFile
        nameFilters: ["JSON (*.json)", "All files (*)"]
        onAccepted: {
            if (root.surfaceHost && root.surfaceHost.cryptoImportKeypair)
                root.applyRaw(root.surfaceHost.cryptoImportKeypair(
                    String(keypairDialog.selectedFile)))
        }
    }

    Column {
        id: bodyCol
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: 12
        anchors.rightMargin: 12
        anchors.topMargin: 16
        spacing: 8

        Text {
            visible: String(root.quote.usd || "").length > 0
            text: String(root.quote.usd || "")
            color: root.ink
            font.family: "monospace"
            font.pixelSize: 22
            font.bold: true
        }
        Text {
            text: String(root.wallet.balance_sol || "0") + " SOL"
            color: root.muted
            font.family: "monospace"
            font.pixelSize: 12
        }

        Text {
            text: "SOLANA"
            color: root.gold
            font.family: "monospace"
            font.pixelSize: 10
            font.bold: true
        }
        Row {
            spacing: 8
            Rectangle {
                width: tnLab.implicitWidth + 18
                height: 24
                color: "#161616"
                border.color: !root.observe ? root.gold : root.frameBorder
                border.width: 1
                radius: 3
                Text {
                    id: tnLab
                    anchors.centerIn: parent
                    text: "TESTNET"
                    color: !root.observe ? root.ink : root.muted
                    font.family: "monospace"
                    font.pixelSize: 10
                    font.bold: !root.observe
                }
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        if (root.surfaceHost && root.surfaceHost.cryptoSetNetwork)
                            root.applyRaw(root.surfaceHost.cryptoSetNetwork("testnet"))
                    }
                }
            }
            Rectangle {
                width: obLab.implicitWidth + 18
                height: 24
                color: "#161616"
                border.color: root.observe ? root.gold : root.frameBorder
                border.width: 1
                radius: 3
                Text {
                    id: obLab
                    anchors.centerIn: parent
                    text: "OBSERVE"
                    color: root.observe ? root.ink : root.muted
                    font.family: "monospace"
                    font.pixelSize: 10
                    font.bold: root.observe
                }
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        if (root.surfaceHost && root.surfaceHost.cryptoSetNetwork)
                            root.applyRaw(root.surfaceHost.cryptoSetNetwork("mainnet"))
                    }
                }
            }
        }
        Text {
            visible: root.connected && !root.status.signer
            text: "Watch only. This account has no key on disk, so it cannot sign."
            width: parent.width
            wrapMode: Text.WordWrap
            color: root.muted
            font.family: "monospace"
            font.pixelSize: 10
        }
        Text {
            text: root.observe
                ? "Live Solana is watch-only. Sends stay on testnet/lab."
                : "Paper and lab fills. KAS is the other wallet on the same portfolio."
            width: parent.width
            wrapMode: Text.WordWrap
            color: root.muted
            font.family: "monospace"
            font.pixelSize: 10
        }

        Row {
            spacing: 12
            Text {
                text: root.copied.length ? root.copied : "RECEIVE"
                color: root.copied.length ? root.green : root.gold
                font.family: "monospace"
                font.pixelSize: 11
                font.bold: true
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.copyAddr()
                }
            }
            Text {
                text: "CREATE"
                color: root.gold
                font.family: "monospace"
                font.pixelSize: 11
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        if (root.surfaceHost && root.surfaceHost.cryptoCreateTestWallet)
                            root.applyRaw(root.surfaceHost.cryptoCreateTestWallet())
                    }
                }
            }
            Text {
                text: "AIRDROP"
                visible: !root.observe
                color: root.green
                font.family: "monospace"
                font.pixelSize: 11
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        if (root.surfaceHost && root.surfaceHost.cryptoAirdrop)
                            root.applyRaw(root.surfaceHost.cryptoAirdrop())
                    }
                }
            }
            Text {
                text: "IMPORT"
                color: root.gold
                font.family: "monospace"
                font.pixelSize: 11
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: keypairDialog.open()
                }
            }
            Text {
                text: "DISCONNECT"
                color: root.muted
                font.family: "monospace"
                font.pixelSize: 11
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        if (root.surfaceHost && root.surfaceHost.cryptoDisconnect)
                            root.applyRaw(root.surfaceHost.cryptoDisconnect())
                    }
                }
            }
        }

        Text {
            text: "ASSETS"
            color: root.muted
            font.family: "monospace"
            font.pixelSize: 10
        }
        Repeater {
            model: Math.min(root.holdings.length, 5)
            delegate: Text {
                width: bodyCol.width
                readonly property var row: root.holdings[index] || {}
                text: String(row.symbol || "")
                    + "  "
                    + String(row.display || "")
                    + (row.usd ? ("  " + String(row.usd)) : "")
                color: root.ink
                font.family: "monospace"
                font.pixelSize: 11
                elide: Text.ElideRight
            }
        }
        Text {
            visible: root.holdings.length === 0
            text: "No assets. CREATE a test account, then AIRDROP."
            color: root.muted
            font.family: "monospace"
            font.pixelSize: 10
            width: parent.width
            wrapMode: Text.WordWrap
        }

        Text {
            text: "OPEN DESK  →"
            color: root.green
            font.family: "monospace"
            font.pixelSize: 11
            font.bold: true
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    root.openDesk()
                    root.requestClose()
                }
            }
        }
    }
}
