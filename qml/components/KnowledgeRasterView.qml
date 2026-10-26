import QtQuick
import QtQuick.Controls

Item {
    id: root
    objectName: "knowledgeRasterView"
    clip: true

    property url imageSource: ""
    property var hotspots: []
    property string selectedHotspotId: ""
    property real zoom: 1
    property bool annotationsVisible: true
    readonly property bool imageReady: raster.status === Image.Ready
    readonly property real imageAspect: dimensions.implicitWidth > 0 && dimensions.implicitHeight > 0
        ? dimensions.implicitWidth / dimensions.implicitHeight : 1.5
    readonly property real fitWidth: Math.min(width, height * imageAspect)
    readonly property real fitHeight: fitWidth / imageAspect
    signal hotspotActivated(var hotspot)

    function resetView() {
        root.zoom = 1
        viewport.contentX = 0
        viewport.contentY = 0
    }

    function zoomAt(factor, x, y) {
        var nx = raster.width > 0 ? (viewport.contentX + x - raster.x) / raster.width : 0.5
        var ny = raster.height > 0 ? (viewport.contentY + y - raster.y) / raster.height : 0.5
        root.zoom = Math.max(1, Math.min(8, root.zoom * factor))
        Qt.callLater(function() {
            viewport.contentX = Math.max(0, Math.min(viewport.contentWidth - viewport.width,
                raster.x + nx * raster.width - x))
            viewport.contentY = Math.max(0, Math.min(viewport.contentHeight - viewport.height,
                raster.y + ny * raster.height - y))
        })
    }

    function focusPoint(x, y, level) {
        root.zoom = Math.max(1, Math.min(8, level || 2.3))
        Qt.callLater(function() {
            viewport.contentX = Math.max(0, Math.min(viewport.contentWidth - viewport.width,
                raster.x + Number(x) * raster.width - viewport.width / 2))
            viewport.contentY = Math.max(0, Math.min(viewport.contentHeight - viewport.height,
                raster.y + Number(y) * raster.height - viewport.height / 2))
        })
    }

    onImageSourceChanged: resetView()
    onWidthChanged: viewport.returnToBounds()
    onHeightChanged: viewport.returnToBounds()

    Rectangle { anchors.fill: parent; color: "#090d12" }

    // Keep intrinsic geometry independent of the fitted image's dimensions.
    // Sharing the source and requested size reuses Qt's image cache.
    Image {
        id: dimensions
        visible: false
        source: root.imageSource
        sourceSize.width: 2800
        asynchronous: true
        cache: true
    }

    Flickable {
        id: viewport
        objectName: "knowledgeRasterViewport"
        anchors.fill: parent
        contentWidth: Math.max(width, root.fitWidth * root.zoom)
        contentHeight: Math.max(height, root.fitHeight * root.zoom)
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.HorizontalAndVerticalFlick
        interactive: root.zoom > 1
        clip: true

        Image {
            id: raster
            objectName: "knowledgeRasterImage"
            x: (viewport.contentWidth - width) / 2
            y: (viewport.contentHeight - height) / 2
            width: root.fitWidth * root.zoom
            height: root.fitHeight * root.zoom
            source: root.imageSource
            sourceSize.width: 2800
            asynchronous: true
            cache: true
            smooth: true
            mipmap: true
            fillMode: Image.PreserveAspectFit

            Repeater {
                model: root.annotationsVisible && root.imageReady ? root.hotspots : []
                delegate: Item {
                    id: point
                    required property var modelData
                    required property int index
                    readonly property bool selected: String(point.modelData.id || point.index) === root.selectedHotspotId
                    readonly property bool injury: point.modelData.injury === true
                    x: Math.max(0, Math.min(1, Number(modelData.x || 0))) * raster.width
                    y: Math.max(0, Math.min(1, Number(modelData.y || 0))) * raster.height
                    z: point.selected || target.hovered ? 4 : 2

                    Button {
                        id: target
                        objectName: "knowledgeHotspot" + point.index
                        x: -17
                        y: -17
                        width: 34
                        height: 34
                        hoverEnabled: true
                        padding: 0
                        Accessible.name: String(point.modelData.label || "Detalj")
                        background: Rectangle {
                            radius: 17
                            color: point.injury ? "#c05a2c2b" : point.selected ? "#a9c8b89a" : "#8a10171c"
                            border.color: point.injury ? "#f1a494" : point.selected || target.hovered ? "#eed5aa" : "#c8a97e"
                            border.width: point.selected || point.injury ? 2 : 1
                            Rectangle {
                                anchors.centerIn: parent
                                width: 5; height: 5; radius: 2.5
                                visible: !point.injury
                                color: point.selected ? "#e9d9bc" : "#c8a97e"
                            }
                            Text {
                                objectName: "knowledgeInjuryMarker" + point.index
                                anchors.centerIn: parent
                                visible: point.injury
                                text: "×"; textFormat: Text.PlainText
                                color: "#ffd1c6"; font.pixelSize: 25
                                Accessible.name: "Markerad skada i övningen"
                            }
                        }
                        contentItem: Item {}
                        onClicked: {
                            root.selectedHotspotId = String(point.modelData.id || point.index)
                            root.hotspotActivated(point.modelData)
                        }
                    }

                    Rectangle {
                        visible: point.selected || target.hovered
                        x: Math.max(-point.x + 8, Math.min(24, raster.width - point.x - width - 8))
                        y: -15
                        width: Math.min(210, pointLabel.implicitWidth + 22)
                        height: 30
                        radius: 4
                        color: "#ee111923"
                        border.color: "#48505b"
                        Text {
                            id: pointLabel
                            anchors.fill: parent; anchors.leftMargin: 11; anchors.rightMargin: 11
                            verticalAlignment: Text.AlignVCenter
                            text: String(point.modelData.label || "Detalj")
                            textFormat: Text.PlainText
                            color: "#ecdfca"
                            font.pixelSize: 12
                            elide: Text.ElideRight
                        }
                    }
                }
            }
        }
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.NoButton
        onWheel: function(wheel) {
            root.zoomAt(wheel.angleDelta.y > 0 ? 1.18 : 1 / 1.18, wheel.x, wheel.y)
            wheel.accepted = true
        }
    }

    PinchArea {
        anchors.fill: parent
        enabled: root.imageReady
        property real startZoom: 1
        onPinchStarted: startZoom = root.zoom
        onPinchUpdated: function(pinch) {
            root.zoomAt((startZoom * pinch.scale) / root.zoom, pinch.center.x, pinch.center.y)
        }
    }

    Column {
        anchors.centerIn: parent
        width: Math.min(330, parent.width - 48)
        spacing: 12
        visible: !root.imageReady
        Text {
            width: parent.width
            text: raster.status === Image.Error ? "Ingen bild i den här vyn" : "Bilden förbereds"
            horizontalAlignment: Text.AlignHCenter
            color: "#c8cdd4"; font.pixelSize: 17
        }
        Text {
            width: parent.width
            text: "Öppna en bild eller en PDF-sida. Klickbara detaljer ligger ovanpå bilden."
            horizontalAlignment: Text.AlignHCenter
            color: "#7f8993"; font.pixelSize: 12; wrapMode: Text.WordWrap
        }
    }

    Rectangle {
        anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 16
        width: 112; height: 76
        visible: root.imageReady && root.zoom > 1.05
        radius: 4; color: "#d9121921"; border.color: "#34424d"
        Image { anchors.fill: parent; anchors.margins: 3; source: root.imageSource; fillMode: Image.PreserveAspectFit; smooth: true }
        Rectangle {
            x: 3 + (viewport.contentX / Math.max(1, viewport.contentWidth)) * (parent.width - 6)
            y: 3 + (viewport.contentY / Math.max(1, viewport.contentHeight)) * (parent.height - 6)
            width: Math.max(6, (parent.width - 6) * viewport.width / Math.max(1, viewport.contentWidth))
            height: Math.max(6, (parent.height - 6) * viewport.height / Math.max(1, viewport.contentHeight))
            color: "#20c8a97e"; border.color: "#c8a97e"; border.width: 1
        }
    }

    Keys.onPressed: function(event) {
        if (event.key === Qt.Key_Plus || event.key === Qt.Key_Equal) {
            root.zoomAt(1.25, width / 2, height / 2); event.accepted = true
        } else if (event.key === Qt.Key_Minus) {
            root.zoomAt(0.8, width / 2, height / 2); event.accepted = true
        } else if (event.key === Qt.Key_0 || event.key === Qt.Key_Home) {
            root.resetView(); event.accepted = true
        }
    }
}
