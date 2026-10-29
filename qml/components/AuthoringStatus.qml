
import "." as RuntimeTheme
import QtQuick

Row {
    id: root
    property string status: "IDLE"
    property int diagnosticCount: 0
    property int unresolvedCount: 0
    spacing: 8

    GGText { colorKey: "ui.AuthoringStatus.1";
        text: "LIVE AID · " + root.status
        color: RuntimeTheme.GGTheme.text
        font.family: "monospace"
        font.pixelSize: 12
        font.bold: true
    }
    GGText { colorKey: "ui.AuthoringStatus.2";
        text: "diagnostics " + root.diagnosticCount + " · unresolved " + root.unresolvedCount
        color: RuntimeTheme.GGTheme.dim
        font.family: "monospace"
        font.pixelSize: 12
    }
}
