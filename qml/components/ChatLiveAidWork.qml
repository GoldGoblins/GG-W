pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls

Item {
    id: root

    objectName: "chatLiveAidWork"

    property string objectTitle: ""
    property bool editorLoaded: false
    property string editorLanguage: ""
    property string liveAidState: "IDLE"
    property var diagnostics: []
    property string evidenceSummary: ""
    property string preflightState: "NOT RUN"
    property string repairState: "IDLE"
    property string repairProposalId: ""
    property bool postDraftBusy: false
    property string postDraftState: "IDLE"

    signal postDraftRequested()
    signal preflightRequested()
    signal repairRequested()
    signal applyRequested()

    implicitHeight: 322

    GgFrame {
        anchors.fill: parent
        leftLegend: "LIVE AID · CONTEXTUAL WORK"
        rightLegend: root.liveAidState
        backgroundColor: "#090d12"
        borderColor: "#6a6a6a"
    }

    Column {
        anchors.fill: parent
        anchors.leftMargin: 14
        anchors.rightMargin: 14
        anchors.topMargin: 22
        anchors.bottomMargin: 12
        spacing: 6

        LiveAidObject {
            width: parent.width
            height: 132
            title: root.objectTitle
            activityState: root.liveAidState
            diagnostics: root.diagnostics
            evidenceSummary: root.evidenceSummary
        }

        GgButton {
            objectName: "workspacePostDraftAutoRepairButton"
            width: parent.width
            height: 30
            enabled:
                root.editorLoaded
                && root.editorLanguage === "qml"
                && !root.postDraftBusy
                && root.preflightState !== "RUNNING"
                && root.repairState !== "RUNNING"
            text: root.postDraftBusy
                ? "POST-DRAFT · " + root.postDraftState
                : "DRAFT COMPLETE · VERIFY + AUTO-REPAIR"
            onClicked: root.postDraftRequested()
        }

        GgButton {
            objectName: "workspacePreflightButton"
            width: parent.width
            height: 30
            enabled:
                root.editorLoaded
                && !root.postDraftBusy
                && root.preflightState !== "RUNNING"
                && root.repairState !== "RUNNING"
            text: root.preflightState === "RUNNING"
                ? "QML PREFLIGHT · RUNNING"
                : "QML PREFLIGHT · " + root.preflightState
            onClicked: root.preflightRequested()
        }

        GgButton {
            objectName: "workspaceRepairButton"
            width: parent.width
            height: 30
            enabled:
                root.editorLoaded
                && !root.postDraftBusy
                && root.preflightState === "FAIL"
                && root.diagnostics.length > 0
                && root.repairState !== "RUNNING"
            text: root.repairState === "RUNNING"
                ? "AI REPAIR · GENERATING"
                : "AI REPAIR · " + root.repairState
            onClicked: root.repairRequested()
        }

        GgButton {
            objectName: "workspaceApplyRepairButton"
            width: parent.width
            height: 30
            enabled:
                !root.postDraftBusy
                && root.repairState === "READY"
                && root.repairProposalId.length > 0
            text: "APPLY PROPOSAL · BUFFER ONLY"
            onClicked: root.applyRequested()
        }
    }
}
