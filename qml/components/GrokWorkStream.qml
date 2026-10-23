pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls

Item {
    id: root

    property string authorLabel: "GG AI"
    property string nodeKind: "GROK_STREAM"
    property string stateLabel: ""
    property string contextReference: ""
    property string taskId: ""
    property string workCardsJson: "[]"
    property bool livePulse: false

    readonly property var cards: root.parseCards(root.workCardsJson)
    readonly property var workCards: root.cardsOfKind(root.cards, false)
    readonly property var userCards: root.cardsOfKind(root.cards, true)
    readonly property var narrativeCards: root.cardsOfNarrative(root.workCards)
    readonly property var terminalCards: root.cardsOfTerminal(root.workCards).concat(
        root.shellFencesFromText(root.workCards)
    )
    readonly property var codeCards: root.cardsOfCode(root.workCards).concat(
        root.codeFencesFromText(root.workCards)
    )
    readonly property string endTitle: root.firstEndTitle(root.workCards)
    readonly property string workLogText: root.joinedBoxedText(root.workCards)
    readonly property bool workLogHasError: root.boxedHasError(root.workCards)
    readonly property int workLogMaxHeight: 168
    readonly property color stateColor: root.colorForState(root.stateLabel)

    implicitWidth: 420
    implicitHeight: frame.implicitHeight

    function isPlainObject(value) {
        return value !== null
            && typeof value === "object"
            && Object.prototype.toString.call(value) === "[object Object]"
    }

    function colorForState(label) {
        if (
            label === "PASS"
            || label === "READY"
            || label === "SELECTED"
        )
            return "#8db89a"

        if (
            label === "FAIL"
            || label === "CANCELLED"
            || label === "BLOCKED"
            || label === "TIMED_OUT"
        )
            return "#c98989"

        if (
            label === "RUNNING"
            || label === "STREAMING"
            || label === "STARTING"
            || label === "GENERATING"
            || label === "WAITING"
            || label === "WAITING_FOR_USER"
            || label === "QUEUED"
            || label === "STOPPING"
        )
            return "#c8a97e"

        return "#8b949e"
    }

    function parseCards(raw) {
        var result = []

        if (raw === undefined || raw === null || String(raw).length === 0)
            return result

        var parsed = []

        try {
            parsed = JSON.parse(String(raw))
        } catch (parseError) {
            return result
        }

        if (parsed === null || typeof parsed !== "object" || parsed.length === undefined)
            return result

        for (var i = 0; i < parsed.length; ++i) {
            var card = parsed[i]

            if (!root.isPlainObject(card))
                continue

            result.push({
                "cardId": card.id ? String(card.id) : "",
                "kind": card.kind ? String(card.kind) : "",
                "title": card.title ? String(card.title) : "",
                "text": card.text ? String(card.text) : "",
                "state": card.state ? String(card.state) : ""
            })
        }

        return result
    }

    function cardsOfKind(allCards, userOnly) {
        var result = []

        for (var i = 0; i < allCards.length; ++i) {
            var isUser = allCards[i].kind === "user"
            if (isUser === userOnly)
                result.push(allCards[i])
        }

        return result
    }

    function isBoxedKind(kind) {
        return kind === "tool_call"
            || kind === "tool_call_update"
            || kind === "stdout"
            || kind === "error"
    }

    function isTerminalCard(card) {
        if (card === undefined || card === null)
            return false
        if (card.kind === "stdout")
            return true
        var title = String(card.title || "").toLowerCase()
        if (
            title === "terminal"
            || title.indexOf("terminal") >= 0
            || title.indexOf("execute") >= 0
        )
            return true
        var text = String(card.text || "").toLowerCase()
        return text.indexOf("name=run_terminal") >= 0
            || text.indexOf("kind=execute") >= 0
            || text.indexOf("$ ") === 0
    }

    function isCodeCard(card) {
        if (card === undefined || card === null)
            return false
        var title = String(card.title || "").toLowerCase()
        if (
            title === "code"
            || title === "diff"
            || title.indexOf("edit") >= 0
        )
            return true
        if (title === "read" || title.indexOf("read ") === 0)
            return true
        if (
            title === "grep"
            || title.indexOf("grep ") === 0
            || title === "found"
        )
            return true
        var text = String(card.text || "").toLowerCase()
        return text.indexOf("search_replace") >= 0
            || text.indexOf("strreplace") >= 0
    }

    function fencesFromCard(card) {
        if (card === undefined || card === null)
            return []
        if (card.kind !== "text")
            return []
        return root.fencesFromText([card])
    }

    function cardsOfTerminal(allCards) {
        var result = []

        for (var i = 0; i < allCards.length; ++i) {
            if (root.isTerminalCard(allCards[i]))
                result.push(allCards[i])
        }

        return result
    }

    function cardsOfCode(allCards) {
        var result = []

        for (var i = 0; i < allCards.length; ++i) {
            if (root.isCodeCard(allCards[i]))
                result.push(allCards[i])
        }

        return result
    }

    function terminalBody(card) {
        var text = String(card.text || "")
        if (root.isCodeCard(card) && !root.isTerminalCard(card))
            return text
        if (text.indexOf("$ ") === 0 || text.indexOf("--- ") === 0)
            return text
        var at = text.indexOf("\n")

        if (at < 0)
            return text

        var rest = text.slice(at + 1)

        if (rest.length > 0)
            return rest

        return text
    }

    function textWithoutFences(text) {
        var source = String(text || "")
        var out = ""
        var rest = source

        while (rest.length > 0) {
            var start = rest.indexOf("```")

            if (start < 0) {
                out += rest
                break
            }

            out += rest.slice(0, start)
            var after = rest.slice(start + 3)
            var closer = after.indexOf("```")

            if (closer < 0) {
                break
            }

            rest = after.slice(closer + 3)
            if (rest.charAt(0) === "\n")
                rest = rest.slice(1)
        }

        return out.replace(/\n{3,}/g, "\n\n").trim()
    }

    function isShellLang(lang) {
        var name = String(lang || "").toLowerCase()
        return (
            name === "bash"
            || name === "sh"
            || name === "zsh"
            || name === "shell"
            || name === "terminal"
        )
    }

    function looksLikeShellCommand(body) {
        var text = String(body || "").replace(/^\s+/, "")
        if (text.length === 0)
            return false
        if (text.indexOf("$ ") === 0)
            return true
        var first = text.split(" ")[0]
        return (
            first === "echo"
            || first === "pwd"
            || first === "date"
            || first === "ls"
            || first === "cat"
            || first === "cd"
        )
    }

    function fencesFromText(allCards) {
        var result = []

        for (var i = 0; i < allCards.length; ++i) {
            if (allCards[i].kind !== "text")
                continue

            var rest = String(allCards[i].text || "")
            var serial = 0
            var lastShell = false

            while (rest.length > 0) {
                var start = rest.indexOf("```")

                if (start < 0)
                    break

                var after = rest.slice(start + 3)
                var nl = after.indexOf("\n")

                if (nl < 0)
                    break

                var lang = after.slice(0, nl).trim()
                var bodyAndTail = after.slice(nl + 1)
                var closer = bodyAndTail.indexOf("```")
                var body = closer < 0
                    ? bodyAndTail
                    : bodyAndTail.slice(0, closer).replace(/\s+$/, "")
                var card = root.fenceCard(lang, body, serial, lastShell)
                if (
                    card.kind === "stdout"
                    && result.length > 0
                    && result[result.length - 1].kind === "stdout"
                    && !root.isShellLang(lang)
                ) {
                    result[result.length - 1].text = (
                        result[result.length - 1].text + "\n" + card.text
                    )
                } else {
                    result.push(card)
                    serial += 1
                }
                lastShell = card.kind === "stdout"
                if (closer < 0)
                    break
                rest = bodyAndTail.slice(closer + 3)
            }
        }

        return result
    }

    function looksLikeDiff(body) {
        var text = String(body || "")
        return (
            text.indexOf("\n+") >= 0
            || text.indexOf("\n-") >= 0
            || text.indexOf("@@") >= 0
            || text.indexOf("--- ") === 0
            || text.indexOf("+++ ") === 0
            || text.indexOf("// ") === 0
        )
    }

    function fenceCard(lang, body, serial, followShell) {
        var name = String(lang || "").trim()
        var text = String(body || "")
        var shell = root.isShellLang(name)
        if (
            !shell
            && (name.length === 0 || name.toLowerCase() === "code")
            && root.looksLikeShellCommand(text)
            && !root.looksLikeDiff(text)
        )
            shell = true
        if (
            !shell
            && followShell
            && (name.length === 0 || name.toLowerCase() === "code")
            && !root.looksLikeDiff(text)
        )
            shell = true
        if (name.length === 0)
            name = shell ? "terminal" : "code"
        if (
            shell
            && text.indexOf("$ ") !== 0
            && (
                root.isShellLang(lang)
                || root.looksLikeShellCommand(text)
            )
        )
            text = "$ " + text.replace(/^\s+/, "")
        return {
            "kind": shell ? "stdout" : "code",
            "title": shell ? "terminal" : name,
            "text": text,
            "state": "PASS",
            "cardId": "fence-" + String(serial)
        }
    }

    function shellFencesFromText(allCards) {
        var all = root.fencesFromText(allCards)
        var result = []
        for (var i = 0; i < all.length; ++i) {
            if (all[i].kind === "stdout")
                result.push(all[i])
        }
        return result
    }

    function codeFencesFromText(allCards) {
        var all = root.fencesFromText(allCards)
        var result = []
        for (var i = 0; i < all.length; ++i) {
            if (all[i].kind !== "stdout")
                result.push(all[i])
        }
        return result
    }

    function cardsOfNarrative(allCards) {
        var result = []

        for (var i = 0; i < allCards.length; ++i) {
            if (allCards[i].kind === "end")
                continue
            if (!root.isBoxedKind(allCards[i].kind))
                result.push(allCards[i])
        }

        return result
    }

    function firstEndTitle(allCards) {
        for (var i = 0; i < allCards.length; ++i) {
            if (allCards[i].kind !== "end")
                continue
            if (allCards[i].title.length > 0)
                return allCards[i].title
            return "end"
        }

        return ""
    }

    function statusFromBoxed(card) {
        var text = card.text
        var key = "status="
        var at = text.lastIndexOf(key)

        if (at < 0)
            return card.state

        var rest = text.slice(at + key.length)
        var end = rest.indexOf(" ")

        if (end < 0)
            return rest

        return rest.slice(0, end)
    }

    function tuiWorkLine(card) {
        var title = card.title.length > 0 ? card.title : card.kind

        if (card.kind === "error" && card.text.length > 0)
            return card.text

        return title
    }

    function boxedLine(card) {
        return root.tuiWorkLine(card)
    }

    function joinedBoxedText(allCards) {
        var lines = []

        for (var i = 0; i < allCards.length; ++i) {
            if (!root.isBoxedKind(allCards[i].kind))
                continue
            if (root.isTerminalCard(allCards[i]))
                continue
            if (root.isCodeCard(allCards[i]))
                continue

            var line = root.boxedLine(allCards[i])

            if (line.length > 0)
                lines.push(line)
        }

        return lines.join("\n")
    }

    function boxedHasError(allCards) {
        for (var i = 0; i < allCards.length; ++i) {
            if (allCards[i].kind === "error")
                return true
        }

        return false
    }

    function stickWorkLogToEnd() {
        if (workLogFlick.contentHeight > workLogFlick.height)
            workLogFlick.contentY = workLogFlick.contentHeight - workLogFlick.height
        else
            workLogFlick.contentY = 0
    }

    function typeShift(kind) {
        if (kind === "thought")
            return 12
        if (kind === "text")
            return 0
        if (
            kind === "tool_call"
            || kind === "tool_call_update"
            || kind === "stdout"
            || kind === "error"
        )
            return 16
        return 8
    }

    Rectangle {
        width: 2
        height: Math.max(0, parent.height - 2)
        color: root.stateColor
        opacity: root.livePulse ? 1.0 : 0.75
    }

    GgFrame {
        id: frame
        x: 8
        width: parent.width - 8
        leftLegend: root.authorLabel
        rightLegend: root.stateLabel
        backgroundColor: "#1c1c1c"
        borderColor: "#6a6a6a"
        rightLegendColor: root.stateColor

        Column {
            id: contentColumn
            width: parent.width
            spacing: 6

            Repeater {
                model: root.cards

                delegate: Column {
                    id: streamRow
                    required property var modelData

                    width: parent.width
                    spacing: 4
                    visible: streamRow.modelData.kind !== "end"
                    height: visible ? implicitHeight : 0

                    readonly property bool isThought:
                        streamRow.modelData.kind === "thought"
                    readonly property bool isSpeech:
                        streamRow.modelData.kind === "text"
                    readonly property bool isUser:
                        streamRow.modelData.kind === "user"
                    readonly property bool isError:
                        streamRow.modelData.kind === "error"
                    readonly property bool isTerminal:
                        root.isTerminalCard(streamRow.modelData)
                    readonly property bool isCode:
                        root.isCodeCard(streamRow.modelData)
                        && !streamRow.isTerminal
                    readonly property var fences:
                        root.fencesFromCard(streamRow.modelData)

                    Text {
                        visible: streamRow.isThought
                        width: parent.width
                        text: "Thought"
                        color: "#7d8590"
                        font.family: "monospace"
                        font.pixelSize: 12
                    }

                    TextEdit {
                        objectName: "grokThoughtText"
                        visible: streamRow.isThought
                            && streamRow.modelData.text.length > 0
                        width: parent.width
                        text: streamRow.modelData.text
                        color: "#9aa7b3"
                        readOnly: true
                        selectByMouse: true
                        selectByKeyboard: true
                        persistentSelection: true
                        selectionColor: "#3a3a3a"
                        selectedTextColor: "#f2f2f2"
                        textFormat: TextEdit.PlainText
                        wrapMode: TextEdit.WordWrap
                        height: implicitHeight

                        SelectionGuard {}
                        font.family: "monospace"
                        font.pixelSize: 12
                    }

                    TextEdit {
                        objectName: "grokSpeechText"
                        visible: streamRow.isSpeech
                            && root.textWithoutFences(
                                streamRow.modelData.text
                            ).length > 0
                        width: parent.width
                        text: root.textWithoutFences(streamRow.modelData.text)
                        color: "#e6edf3"
                        readOnly: true
                        selectByMouse: true
                        selectByKeyboard: true
                        persistentSelection: true
                        selectionColor: "#3a3a3a"
                        selectedTextColor: "#f2f2f2"
                        textFormat: TextEdit.PlainText
                        wrapMode: TextEdit.WordWrap
                        height: implicitHeight

                        SelectionGuard {}
                        font.pixelSize: 13
                    }

                    Repeater {
                        model: streamRow.fences

                        delegate: WorkObject {
                            required property var modelData

                            x: 16
                            width: Math.max(1, contentColumn.width - 16)
                            objectType: modelData.kind === "stdout"
                                ? "TERMINAL"
                                : "CODE"
                            title: modelData.title.length > 0
                                ? modelData.title
                                : (
                                    modelData.kind === "stdout"
                                        ? "terminal"
                                        : "code"
                                )
                            bodyText: modelData.text
                            provenanceClass: "REAL_UI_STATE"
                            activityState: modelData.state.length > 0
                                ? modelData.state
                                : "PASS"
                            realPercentage: -1
                            contextReference: root.contextReference
                        }
                    }

                    WorkObject {
                        visible: streamRow.isTerminal
                        x: 16
                        width: Math.max(1, contentColumn.width - 16)
                        objectType: "TERMINAL"
                        terminalId: (
                            String(streamRow.modelData.cardId || "").indexOf(
                                "machine-"
                            ) === 0
                        )
                            ? ""
                            : (
                                root.taskId + "-" + String(
                                    streamRow.modelData.cardId
                                    || streamRow.modelData.card_id
                                    || "term"
                                )
                            )
                        title: streamRow.modelData.title.length > 0
                            ? streamRow.modelData.title
                            : "terminal"
                        bodyText: root.terminalBody(streamRow.modelData)
                        provenanceClass: "REAL_UI_STATE"
                        activityState: streamRow.modelData.state.length > 0
                            ? streamRow.modelData.state
                            : "RUNNING"
                        realPercentage: -1
                        contextReference: root.contextReference
                        height: visible ? implicitHeight : 0
                    }

                    WorkObject {
                        visible: streamRow.isCode
                        x: 16
                        width: Math.max(1, contentColumn.width - 16)
                        objectType: "CODE"
                        title: streamRow.modelData.title.length > 0
                            ? streamRow.modelData.title
                            : "code"
                        bodyText: root.terminalBody(streamRow.modelData)
                        provenanceClass: "REAL_UI_STATE"
                        activityState: streamRow.modelData.state.length > 0
                            ? streamRow.modelData.state
                            : "RUNNING"
                        realPercentage: -1
                        contextReference: root.contextReference
                        height: visible ? implicitHeight : 0
                    }

                    TextEdit {
                        objectName: "grokUserText"
                        visible: streamRow.isUser
                        width: parent.width
                        text: streamRow.modelData.text
                        color: "#d8dee9"
                        readOnly: true
                        selectByMouse: true
                        selectByKeyboard: true
                        persistentSelection: true
                        selectionColor: "#3a3a3a"
                        selectedTextColor: "#f2f2f2"
                        textFormat: TextEdit.PlainText
                        wrapMode: TextEdit.WordWrap
                        height: implicitHeight

                        SelectionGuard {}
                        font.pixelSize: 13
                    }

                    TextEdit {
                        objectName: "grokErrorText"
                        visible: streamRow.isError
                        width: parent.width
                        text: streamRow.modelData.text
                        color: "#c98989"
                        readOnly: true
                        selectByMouse: true
                        selectByKeyboard: true
                        persistentSelection: true
                        selectionColor: "#3a3a3a"
                        selectedTextColor: "#f2f2f2"
                        textFormat: TextEdit.PlainText
                        wrapMode: TextEdit.WordWrap
                        height: implicitHeight

                        SelectionGuard {}
                        font.family: "monospace"
                        font.pixelSize: 12
                    }

                    TextEdit {
                        objectName: "grokBoxedText"
                        visible: root.isBoxedKind(streamRow.modelData.kind)
                            && !streamRow.isTerminal
                            && !streamRow.isCode
                            && !streamRow.isError
                            && root.boxedLine(streamRow.modelData) !== "tool"
                            && root.boxedLine(streamRow.modelData).length > 0
                        width: parent.width
                        text: root.boxedLine(streamRow.modelData)
                        color: "#9aa7b3"
                        readOnly: true
                        selectByMouse: true
                        selectByKeyboard: true
                        persistentSelection: true
                        selectionColor: "#3a3a3a"
                        selectedTextColor: "#f2f2f2"
                        textFormat: TextEdit.PlainText
                        wrapMode: TextEdit.WordWrap
                        height: implicitHeight

                        SelectionGuard {}
                        font.family: "monospace"
                        font.pixelSize: 12
                    }
                }
            }

            Item {
                visible: root.workLogText.length > 0
                width: parent.width
                height: visible ? workLogFlick.height : 0

                Rectangle {
                    width: 2
                    height: parent.height
                    x: 6
                    color: root.workLogHasError ? "#6a4040" : "#2a3038"
                }

                Flickable {
                    id: workLogFlick
                    x: 16
                    width: parent.width - 16
                    height: Math.min(
                        root.workLogMaxHeight,
                        Math.max(1, workLogBody.implicitHeight)
                    )
                    contentWidth: width
                    contentHeight: workLogBody.implicitHeight
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    interactive: contentHeight > height
                    flickableDirection: Flickable.VerticalFlick
                    onContentHeightChanged: root.stickWorkLogToEnd()
                    onHeightChanged: root.stickWorkLogToEnd()

                    TextEdit {
                        id: workLogBody
                        objectName: "grokWorkLogText"
                        width: workLogFlick.width
                        text: root.workLogText
                        color: root.workLogHasError ? "#c98989" : "#9aa7b3"
                        readOnly: true
                        selectByMouse: true
                        selectByKeyboard: true
                        persistentSelection: true
                        selectionColor: "#3a3a3a"
                        selectedTextColor: "#f2f2f2"
                        textFormat: TextEdit.PlainText
                        wrapMode: TextEdit.WordWrap
                        height: implicitHeight

                        SelectionGuard {}
                        font.family: "monospace"
                        font.pixelSize: 12
                    }

                    ScrollBar.vertical: GgScrollBar {
                    }
                }
            }

            Text {
                visible: root.endTitle.length > 0 && root.endTitle !== "end"
                width: parent.width
                text: root.endTitle
                color: "#7d8590"
                font.family: "monospace"
                font.pixelSize: 12
            }

            Text {
                visible: root.contextReference.length > 0
                width: parent.width
                text: "ctx " + root.contextReference
                    + (
                        root.taskId.length > 0
                            ? " · " + root.taskId
                            : ""
                    )
                color: "#a8b0b8"
                font.family: "monospace"
                font.pixelSize: 12
            }
        }
    }

    Rectangle {
        id: overlay
        visible: root.userCards.length > 0
        width: Math.min(frame.width * 0.62, 280)
        implicitHeight: overlayColumn.implicitHeight + 16
        height: visible ? implicitHeight : 0
        anchors.right: frame.right
        anchors.bottom: frame.bottom
        anchors.rightMargin: 8
        anchors.bottomMargin: 8
        radius: 2
        color: "#2a2a2a"
        border.width: 1
        border.color: "#3a3a3a"

        Column {
            id: overlayColumn
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 8
            spacing: 6

            Text {
                text: "YOU · IN STREAM"
                color: "#9a9a9a"
                font.family: "monospace"
                font.pixelSize: 12
                font.bold: true
            }

            Repeater {
                model: root.userCards

                delegate: Text {
                    id: userCard
                    required property var modelData

                    width: parent.width
                    text: userCard.modelData.text
                    color: "#d6d6d6"
                    wrapMode: Text.WordWrap
                    font.pixelSize: 12
                }
            }
        }
    }
}
