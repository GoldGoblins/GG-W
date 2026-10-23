import QtQuick
import QtQuick.Controls

Item {
    id: root
    property string title: "current draft"
    property string activityState: "IDLE"
    property var diagnostics: []
    property string evidenceSummary: ""
    readonly property int bodyMaxHeight: 98

    implicitWidth: 350
    implicitHeight: 132

    function stickDiagnosticsToEnd() {
        if (diagnosticsFlick.contentHeight > diagnosticsFlick.height)
            diagnosticsFlick.contentY =
                diagnosticsFlick.contentHeight - diagnosticsFlick.height
        else
            diagnosticsFlick.contentY = 0
    }

    GgFrame {
        id: frame
        width: root.width
        height: root.height
        leftLegend: "LIVE AID · " + root.title
        rightLegend: root.activityState
        backgroundColor: "#0b1117"
        borderColor: "#6a6a6a"
        rightLegendColor: "#8b949e"

        Flickable {
            id: diagnosticsFlick
            width: parent.width
            height: Math.min(
                root.bodyMaxHeight,
                Math.max(1, diagnosticsColumn.implicitHeight)
            )
            contentWidth: width
            contentHeight: diagnosticsColumn.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            interactive: contentHeight > height
            flickableDirection: Flickable.VerticalFlick
            onContentHeightChanged: root.stickDiagnosticsToEnd()
            onHeightChanged: root.stickDiagnosticsToEnd()

            Column {
                id: diagnosticsColumn
                width: diagnosticsFlick.width
                spacing: 5

                Repeater {
                    model: root.diagnostics
                    delegate: LiveAidLineAnnotation {
                        id: annotation
                        required property var modelData
                        width: annotation.parent.width
                        status: annotation.modelData.status || "UNKNOWN"
                        sourceLine: annotation.modelData.line || -1
                        code: annotation.modelData.code || ""
                        message: annotation.modelData.message || ""
                        suggestion: annotation.modelData.suggestion || ""
                        blocking: annotation.modelData.blocking || false
                    }
                }

                Text {
                    visible: root.evidenceSummary.length > 0
                    width: parent.width
                    text: root.evidenceSummary
                    color: "#a8b0b8"
                    wrapMode: Text.WordWrap
                    font.family: "monospace"
                    font.pixelSize: 12
                }
            }

            ScrollBar.vertical: GgScrollBar {
            }
        }
    }
}
