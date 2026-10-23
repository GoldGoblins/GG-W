pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls

Item {
    id: root

    property color accentColor: "#8a8a8a"
    property color frameBorder: "#6a6a6a"
    property int frameRadius: 4
    signal accentColorChangedByUser(color value)
    signal frameBorderChangedByUser(color value)
    signal frameRadiusChangedByUser(int value)

    implicitHeight: 268

    function grayToken(value) {
        var n = Math.max(40, Math.min(160, Math.round(value)))
        var hex = n.toString(16)
        if (hex.length < 2)
            hex = "0" + hex
        return "#" + hex + hex + hex
    }

    function borderChannel() {
        var t = String(root.frameBorder)
        if (t.length === 7 && t.charAt(0) === "#") {
            var parsed = parseInt(t.substring(1, 3), 16)
            if (!isNaN(parsed))
                return parsed
        }
        return 106
    }

    GgFrame {
        anchors.fill: parent
        leftLegend: "APPEARANCE"
        rightLegend: "LIVE"
        backgroundColor: "#161616"
        borderColor: root.frameBorder
        radius: root.frameRadius
    }

    Column {
        anchors.fill: parent
        anchors.leftMargin: 14
        anchors.rightMargin: 14
        anchors.topMargin: 22
        anchors.bottomMargin: 12
        spacing: 7

        Text {
            width: parent.width
            text: "Frame border · " + String(root.frameBorder)
            color: "#e6e6e6"
            font.family: "monospace"
            font.pixelSize: 12
        }

        Row {
            spacing: 9
            height: 28

            Repeater {
                model: ["#4a4a4a", "#6a6a6a", "#8a8a8a", "#9a9a9a"]

                delegate: Rectangle {
                    required property string modelData
                    width: 28
                    height: 28
                    radius: 2
                    color: modelData
                    border.width: 1
                    border.color: String(root.frameBorder) === modelData
                        ? "#e6e6e6"
                        : "#6a6a6a"

                    TapHandler {
                        onTapped:
                            root.frameBorderChangedByUser(modelData)
                    }
                }
            }
        }

        GgSlider {
            id: borderSlider
            width: parent.width
            from: 64
            to: 154
            stepSize: 2
            value: root.borderChannel()

            onMoved:
                root.frameBorderChangedByUser(
                    root.grayToken(borderSlider.value)
                )
        }

        Text {
            text: "Corner radius · " + String(root.frameRadius) + " px"
            color: "#e6e6e6"
            font.family: "monospace"
            font.pixelSize: 12
        }

        GgSlider {
            id: radiusSlider
            width: parent.width
            from: 0
            to: 8
            stepSize: 1
            value: root.frameRadius

            onMoved:
                root.frameRadiusChangedByUser(
                    Math.round(radiusSlider.value)
                )
        }

        Text {
            width: parent.width
            text: "Accent · telemetry and status only, not frame borders"
            color: "#e6e6e6"
            font.family: "monospace"
            font.pixelSize: 12
        }

        Row {
            spacing: 9
            height: 28

            Repeater {
                model: [
                    "#8a8a8a",
                    "#8fb8c5",
                    "#73c7a1",
                    "#c7a873",
                    "#b394d6",
                    "#d18787"
                ]

                delegate: Rectangle {
                    required property string modelData
                    width: 28
                    height: 28
                    radius: 2
                    color: modelData
                    border.width: 1
                    border.color: String(root.accentColor) === modelData
                        ? "#e6e6e6"
                        : "#6a6a6a"

                    TapHandler {
                        onTapped:
                            root.accentColorChangedByUser(modelData)
                    }
                }
            }
        }
    }
}
