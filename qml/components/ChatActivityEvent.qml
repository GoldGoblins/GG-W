pragma ComponentBehavior: Bound


import "." as RuntimeTheme
import QtQuick

Item {
    id: root

    property string authorLabel: ""
    property string nodeKind: ""
    property string bodyText: ""
    property string stateLabel: ""
    property string contextReference: ""
    property string taskId: ""
    property string workStagesJson: ""
    property bool livePulse: false

    readonly property color stateColor: root.colorForState(root.stateLabel)
    readonly property var stageRows: root.parseStageRows(root.workStagesJson)

    implicitHeight: eventColumn.implicitHeight + 6
    implicitWidth: 420

    function colorForState(label) {
        if (label === "WAITING_FOR_USER" || label === "WAITING")
            return RuntimeTheme.GGTheme.warning

        if (
            label === "PASS"
            || label === "READY"
            || label === "SELECTED"
        )
            return RuntimeTheme.GGTheme.positive

        if (
            label === "FAIL"
            || label === "CANCELLED"
            || label === "BLOCKED"
            || label === "TIMED_OUT"
        )
            return RuntimeTheme.GGTheme.negative

        if (
            label === "RUNNING"
            || label === "STREAMING"
            || label === "STARTING"
            || label === "GENERATING"
            || label === "QUEUED"
            || label === "STOPPING"
        )
            return RuntimeTheme.GGTheme.accent

        // IDLE and unknown labels stay neutral. IDLE is not busy and
        // is not a PASS/FAIL claim.
        return RuntimeTheme.GGTheme.dim
    }

    function isPlainObject(value) {
        return value !== null
            && typeof value === "object"
            && Object.prototype.toString.call(value) === "[object Object]"
    }

    function parseStageRows(raw) {
        var result = []

        if (raw === undefined || raw === null || String(raw).length === 0)
            return result

        var stages = ({})

        try {
            stages = JSON.parse(String(raw))
        } catch (parseError) {
            return result
        }

        if (!root.isPlainObject(stages))
            return result

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
            var stage = stages[name]

            if (!root.isPlainObject(stage))
                continue

            result.push({
                "phase": name,
                "state": stage.state ? String(stage.state) : "",
                "text": stage.text ? String(stage.text) : ""
            })
        }

        return result
    }

    Rectangle {
        width: 2
        height: Math.max(0, parent.height - 2)
        color: root.stateColor
        opacity: root.livePulse ? 1.0 : 0.75
    }

    Column {
        id: eventColumn
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: 10
        spacing: 2

        Row {
            width: parent.width
            spacing: 8

            GGText { colorKey: "ui.ChatActivityEvent.1";
                text: root.stateLabel.length > 0
                    ? root.stateLabel
                    : root.nodeKind
                color: root.stateColor
                font.family: "monospace"
                font.pixelSize: 12
                font.bold: true
            }

            GGText { colorKey: "ui.ChatActivityEvent.2";
                visible: root.authorLabel.length > 0
                text: root.authorLabel
                color: RuntimeTheme.GGTheme.muted
                font.family: "monospace"
                font.pixelSize: 12
            }

            GGText { colorKey: "ui.ChatActivityEvent.3";
                text: root.nodeKind
                color: RuntimeTheme.GGTheme.muted
                font.family: "monospace"
                font.pixelSize: 12
            }

            GGText { colorKey: "ui.ChatActivityEvent.4";
                visible: root.taskId.length > 0
                text: root.taskId
                color: RuntimeTheme.GGTheme.muted
                font.family: "monospace"
                font.pixelSize: 12
            }
        }

        TextEdit { property bool colorCustomizationExcluded:true;
            objectName: "chatActivityBodyText"
            visible: root.bodyText.length > 0
            width: parent.width
            text: root.bodyText
            color: "#c7d0d9"
            readOnly: true
            selectByMouse: true
            selectByKeyboard: true
            persistentSelection: true
            selectionColor: RuntimeTheme.GGTheme.selected
            selectedTextColor: RuntimeTheme.GGTheme.bright
            textFormat: TextEdit.PlainText
            wrapMode: TextEdit.WordWrap
            height: implicitHeight
            font.family: "monospace"
            font.pixelSize: 12

            SelectionGuard { property string uiColorScope: "ui.widget.ChatActivityEvent.SelectionGuard.1";}
        }

        Repeater {
            model: root.stageRows

            delegate: TextEdit { property bool colorCustomizationExcluded:true;
                required property var modelData

                width: eventColumn.width
                text: "  "
                    + String(modelData.phase || "")
                    + " · "
                    + String(modelData.state || "")
                    + (
                        String(modelData.text || "").length > 0
                            ? " · " + String(modelData.text)
                            : ""
                    )
                color: RuntimeTheme.GGTheme.text
                readOnly: true
                selectByMouse: true
                selectByKeyboard: true
                persistentSelection: true
                selectionColor: RuntimeTheme.GGTheme.selected
                selectedTextColor: RuntimeTheme.GGTheme.bright
                textFormat: TextEdit.PlainText
                wrapMode: TextEdit.WordWrap
                height: implicitHeight
                font.family: "monospace"
                font.pixelSize: 12

                SelectionGuard { property string uiColorScope: "ui.widget.ChatActivityEvent.SelectionGuard.2";}
            }
        }

        GGText { colorKey: "ui.ChatActivityEvent.5";
            visible: root.contextReference.length > 0
            width: parent.width
            text: "ctx " + root.contextReference
            color: RuntimeTheme.GGTheme.muted
            font.family: "monospace"
            font.pixelSize: 12
        }
    }
}
