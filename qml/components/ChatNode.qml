import QtQuick

Item {
    id: root

    property string authorLabel: "GG SYSTEM"
    property string nodeKind: "SYSTEM"
    property string bodyText: ""
    property string contextReference: ""
    property string provenanceClass: "REAL_UI_STATE"
    property string stateLabel: ""
    property int laneOffset: 0
    property string taskId: ""
    property string workStagesJson: ""
    property int maxBubbleWidth: 720

    readonly property bool grokMotor:
        String(root.authorLabel).toUpperCase() === "GROK TUI"
    readonly property bool gptMotor:
        String(root.authorLabel).toUpperCase() === "GPTUI"
    readonly property bool syntheticFixture:
        root.provenanceClass === "SYNTHETIC_UI_FIXTURE"
    readonly property string provenanceLegend:
        root.syntheticFixture
            ? "DEMO · SAMPLE · NO EXECUTION"
            : "REAL UI STATE"
    readonly property var codeFences: root.fencesFromText(root.bodyText)
    readonly property string speechText: root.textWithoutFences(root.bodyText)

    readonly property int hugWidth: {
        var textWidth = Math.max(
            bodyMetrics.width,
            contextMetrics.width
        )
        var legendWidth = leftLegendMetrics.width + 24
        var codeMin = root.codeFences.length > 0 ? 420 : 0
        return Math.min(
            root.maxBubbleWidth,
            Math.max(legendWidth + 36, textWidth + 32, codeMin)
        )
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

    function fencesFromText(text) {
        var result = []
        var rest = String(text || "")
        var serial = 0

        while (rest.length > 0) {
            var start = rest.indexOf("```")

            if (start < 0)
                break

            var after = rest.slice(start + 3)
            var nl = after.indexOf("\n")

            if (nl < 0)
                break

            var lang = after.slice(0, nl).trim()
            if (lang.length === 0)
                lang = "code"
            var bodyAndTail = after.slice(nl + 1)
            var closer = bodyAndTail.indexOf("```")

            if (closer < 0) {
                result.push({
                    "title": lang,
                    "text": bodyAndTail,
                    "state": "PASS",
                    "cardId": "fence-" + String(serial)
                })
                break
            }

            result.push({
                "title": lang,
                "text": bodyAndTail.slice(0, closer).replace(/\s+$/, ""),
                "state": "PASS",
                "cardId": "fence-" + String(serial)
            })
            serial += 1
            rest = bodyAndTail.slice(closer + 3)
        }

        return result
    }

    implicitHeight: frame.implicitHeight
    implicitWidth: root.hugWidth
    width: root.hugWidth
    x: root.laneOffset

    TextMetrics {
        id: bodyMetrics
        font.pixelSize: 13
        text: root.speechText
    }

    TextMetrics {
        id: contextMetrics
        font.family: "monospace"
        font.pixelSize: 12
        text: root.contextReference.length > 0
            ? "context " + root.contextReference
            : ""
    }

    TextMetrics {
        id: leftLegendMetrics
        font.family: "monospace"
        font.pixelSize: 12
        font.bold: true
        text: root.authorLabel + " · " + root.nodeKind
    }

    GgFrame {
        id: frame
        width: root.width
        leftLegend: root.authorLabel + " · " + root.nodeKind
        rightLegend: root.syntheticFixture
            ? root.provenanceLegend
            : root.stateLabel
        backgroundColor: root.nodeKind === "REQUEST"
            ? "#2a2a2a"
            : "#1c1c1c"
        borderColor: root.grokMotor ? "#c8a97e" : (root.gptMotor ? "#8db89a" : "#6a6a6a")
        leftLegendColor: root.grokMotor ? "#c8a97e" : (root.gptMotor ? "#8db89a" : "#e6edf3")
        rightLegendColor: root.syntheticFixture ? "#d2b48c" : "#8b949e"

        Column {
            id: attachedWorkLayer
            visible: root.nodeKind === "AUTONOMY"
            width: parent.width
            spacing: 6

            property var stages: {
                if (root.workStagesJson.length === 0)
                    return ({})

                try {
                    return JSON.parse(root.workStagesJson)
                } catch (error) {
                    return ({})
                }
            }

            property var stageRows: {
                var result = []
                var names = [
                    "INTENT",
                    "REVALIDATE",
                    "WHY",
                    "OBSERVE",
                    "CANDIDATE",
                    "HYPOTHESIZE",
                    "REPLAN",
                    "REPAIR",
                    "VERIFY",
                    "CHANGESET",
                    "BOUNDARY",
                    "RESULT",
                    "STOP"
                ]

                for (var i = 0; i < names.length; ++i) {
                    var name = names[i]

                    result.push({
                        "phase": name,
                        "stage": attachedWorkLayer.stages[name],
                        "availableWidth": attachedWorkLayer.width,
                        "taskId": root.taskId,
                        "contextReference": root.contextReference
                    })
                }

                return result
            }

            Repeater {
                model: attachedWorkLayer.stageRows

                delegate: WorkObject {
                    required property var modelData

                    width: modelData.availableWidth
                    visible: modelData.stage !== undefined
                    objectType: modelData.phase
                    title: modelData.taskId
                    bodyText: modelData.stage === undefined
                        ? ""
                        : modelData.stage.text
                    provenanceClass: "REAL_UI_STATE"
                    activityState: modelData.stage === undefined
                        ? "IDLE"
                        : modelData.stage.state
                    contextReference: modelData.contextReference
                }
            }
        }

        TextEdit {
            id: bodyTextView
            objectName: "chatMessageText"
            width: parent.width
            text: root.speechText
            color: "#e6edf3"
            readOnly: true
            selectByMouse: true
            selectByKeyboard: true
            persistentSelection: true
            textFormat: TextEdit.PlainText
            wrapMode: TextEdit.WordWrap
            height: implicitHeight
            font.pixelSize: 13
            selectionColor: "#3a3a3a"
            selectedTextColor: "#f2f2f2"

            SelectionGuard {
                editor: bodyTextView
            }
        }

        Repeater {
            model: root.codeFences

            delegate: WorkObject {
                required property var modelData

                width: parent.width
                objectType: "CODE"
                title: modelData.title.length > 0 ? modelData.title : "code"
                bodyText: modelData.text
                provenanceClass: "REAL_UI_STATE"
                activityState: modelData.state
                realPercentage: -1
                contextReference: root.contextReference
            }
        }

        Text {
            visible: root.contextReference.length > 0
            width: parent.width
            text: "context " + root.contextReference
            color: "#a8b0b8"
            font.family: "monospace"
            font.pixelSize: 12
        }

        Text {
            visible: root.syntheticFixture
            width: parent.width
            text: "SYNTHETIC FIXTURE · NO EXECUTION"
            color: "#c8a97e"
            font.family: "monospace"
            font.pixelSize: 12
            font.bold: true
        }
    }
}
