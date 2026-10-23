pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Window

Item {
    id: root
    objectName: "workspaceExternalPane"

    property var surfaceHost: null
    property string statusJson: "{}"
    property color frameBorder: "#6a6a6a"
    property int frameRadius: 4

    readonly property var status: {
        try {
            return JSON.parse(root.statusJson || "{}")
        } catch (err) {
            return {}
        }
    }
    readonly property bool blenderPresent: root.status.present === true
    readonly property bool sidecarUp: root.status.sidecar_up === true
    readonly property bool attached: root.status.attached === true

    function reportHole() {
        var win = hole.Window.window
        if (!win || !root.surfaceHost || !root.surfaceHost.externalSetHole)
            return
        var p = hole.mapToItem(win.contentItem, 0, 0)
        root.surfaceHost.externalSetHole(p.x, p.y, hole.width, hole.height)
    }

    function refresh() {
        root.reportHole()
        if (!root.surfaceHost || !root.surfaceHost.externalStatus)
            return
        root.statusJson = root.surfaceHost.externalStatus()
    }

    function openBlender() {
        if (!root.surfaceHost || !root.surfaceHost.externalStart)
            return
        root.surfaceHost.externalStart("blender", "")
        root.refresh()
    }

    function hideEmbed() {
        if (root.surfaceHost && root.surfaceHost.hideExternal)
            root.surfaceHost.hideExternal()
    }

    onVisibleChanged: {
        if (visible) {
            root.refresh()
            if (root.blenderPresent)
                root.openBlender()
        } else {
            root.hideEmbed()
        }
    }

    Component.onCompleted: root.refresh()
    Component.onDestruction: root.hideEmbed()

    Timer {
        interval: 1500
        running: root.visible
        repeat: true
        onTriggered: {
            root.refresh()
            if (root.blenderPresent && !root.attached)
                root.openBlender()
        }
    }

    Column {
        anchors.fill: parent
        anchors.leftMargin: 10
        anchors.rightMargin: 10
        anchors.topMargin: 8
        anchors.bottomMargin: 8
        spacing: 8

        Row {
            width: parent.width
            spacing: 14

            Text {
                text: "BLENDER"
                color: "#d8dee9"
                font.family: "monospace"
                font.pixelSize: 12
                font.bold: true
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.openBlender()
                }
            }

            Text {
                text: root.blenderPresent ? "OPEN" : "NOT ON PATH"
                color: root.blenderPresent ? "#c8a97e" : "#c98989"
                font.family: "monospace"
                font.pixelSize: 12
                font.bold: true
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    enabled: root.blenderPresent
                    onClicked: root.openBlender()
                }
            }

            Text {
                text: root.attached ? "IN BOX" : (root.blenderPresent ? "EMBED…" : "")
                color: root.attached ? "#8db89a" : "#8a8a8a"
                font.family: "monospace"
                font.pixelSize: 12
            }

            Text {
                text: root.sidecarUp ? "MCP LIVE" : "MCP WAIT"
                color: root.sidecarUp ? "#8db89a" : "#8a8a8a"
                font.family: "monospace"
                font.pixelSize: 12
            }
        }

        Text {
            width: parent.width
            text: root.blenderPresent
                ? "Clay asset desk. Blender is a child of this window, only in EXT."
                : "Install or point GG_BLENDER at the local Blender binary."
            color: "#c8cdd4"
            wrapMode: Text.WordWrap
            font.pixelSize: 12
        }

        Item {
            id: hole
            objectName: "workspaceExternalHole"
            width: parent.width
            height: Math.max(80, parent.height - 64)
            onXChanged: root.reportHole()
            onYChanged: root.reportHole()
            onWidthChanged: root.reportHole()
            onHeightChanged: root.reportHole()

            Rectangle {
                anchors.fill: parent
                color: "#0a0a0a"
                border.color: root.frameBorder
                border.width: 1
                radius: root.frameRadius
            }

            Text {
                anchors.centerIn: parent
                width: parent.width - 40
                horizontalAlignment: Text.AlignHCenter
                visible: !root.attached
                text: {
                    var err = String(root.status.error || "")
                    if (err)
                        return err
                    if (root.blenderPresent)
                        return "Starting Blender in this pane…"
                    return "Blender is not installed on this machine."
                }
                color: "#6a6a6a"
                wrapMode: Text.WordWrap
                font.family: "monospace"
                font.pixelSize: 14
            }
        }
    }
}
