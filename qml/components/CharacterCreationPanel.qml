pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick3D
import QtQuick3D.AssetUtils
import QtQuick3D.Helpers

Rectangle {
    id: creator
    objectName: "gameCharacterCreationPanel"
    property var surfaceHost: null
    property var localSession: null
    property var catalog: ({races: [], classes: [], fur_colors: [], eye_colors: []})
    property var selection: ({})
    property string previewSource: ""
    property string notice: ""
    property bool busy: false
    property real heading: -18
    property real distance: 3.1
    property var previewInfo: ({})
    property bool modelReady: false
    property bool modelLoading: false
    property var previewActor: null
    signal applied()
    signal closed()
    color: "#151a1e"

    function send(op) {
        if (!localSession && (!surfaceHost || !surfaceHost.gameEngineCharacterCreate)) {
            notice = "Öppna den uppdaterade spelklienten för karaktärsval."
            return
        }
        busy = true
        try {
            var result
            if (localSession) {
                result = localSession.previewCharacter(selection)
                if (op === "APPLY" && !result.error) {
                    result.applied = localSession.create(localName.text.trim(), result.selection)
                    if (!result.applied) result.error = localSession.state.error
                }
            } else result = JSON.parse(surfaceHost.gameEngineCharacterCreate(JSON.stringify({op: op, selection: selection})))
            if (result.error) { notice = String(result.error); return }
            catalog = result.catalog
            selection = result.selection
            previewInfo = result.preview || ({})
            previewSource = String(previewInfo.source || "")
            notice = result.applied ? "Karaktären är sparad." : ""
            if (result.applied) creator.applied()
        } catch(e) { notice = String(e) }
        finally { busy = false }
    }
    function choose(key, value) {
        selection = Object.assign({}, selection)
        selection[key] = value
        send("PREVIEW")
    }
    Component.onCompleted: send("CATALOG")
    onPreviewSourceChanged: {
        modelReady=false
        modelLoading=true
        previewHost.active=false
        reloadPreview.restart()
    }
    Timer {
        id: reloadPreview
        interval: 60
        onTriggered: previewHost.active=creator.previewSource!==""
    }
    FrameAnimation {
        id: previewClock
        running: creator.visible && creator.modelReady && creator.previewActor !== null
        onTriggered: {
            // The native clip driver owns the animation clock; its third
            // argument is cadence, not elapsed preview time.
            if (creator.surfaceHost) creator.surfaceHost.gameEngineRuntimeClip(creator.previewActor,"Idle",0,"")
        }
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: 18
        spacing: 20
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumWidth: 260
            color: "#202930"
            radius: 6
            View3D {
                id: scene
                anchors.fill: parent
                environment: SceneEnvironment {
                    backgroundMode: SceneEnvironment.Color
                    clearColor: "#202930"
                    antialiasingMode: SceneEnvironment.MSAA
                    antialiasingQuality: SceneEnvironment.High
                    lightProbe: Texture {
                        textureData: ProceduralSkyTextureData {
                            textureQuality: ProceduralSkyTextureData.SkyTextureQualityLow
                            skyTopColor: "#8fa2b5"
                            skyHorizonColor: "#c4d0d6"
                            groundBottomColor: "#45464b"
                            groundHorizonColor: "#797f86"
                        }
                    }
                }
                PerspectiveCamera {
                    id: camera
                    position: Qt.vector3d(0, .83, creator.distance)
                    clipNear: .01
                    clipFar: 30
                    fieldOfView: 35
                }
                camera: camera
                DirectionalLight { eulerRotation: Qt.vector3d(-25,-30,0); brightness: 1.7 }
                DirectionalLight { eulerRotation: Qt.vector3d(-20,135,0); brightness: .8 }
                Node {
                    eulerRotation.y: creator.heading
                    Loader3D {
                        id: previewHost
                        active: false
                        sourceComponent: RuntimeLoader {
                            objectName: "characterCreationPreview"
                            // One source per importer lifetime. Qt's imported
                            // skinned timelines are released before the next model.
                            Component.onCompleted: { creator.previewActor=this; source=creator.previewSource }
                            Component.onDestruction: if (creator.previewActor===this) creator.previewActor=null
                            onStatusChanged: {
                                creator.modelReady=status===RuntimeLoader.Success
                                creator.modelLoading=status===RuntimeLoader.Loading
                                if (status === RuntimeLoader.Error) creator.notice = "Modellen kunde inte öppnas: " + errorString
                                if (status === RuntimeLoader.Success && creator.surfaceHost)
                                    creator.surfaceHost.gameEngineRuntimeClip(this,"Idle",0,"")
                            }
                        }
                    }
                }
            }
            MouseArea {
                anchors.fill: parent
                property real lastX: 0
                onPressed: function(mouse) { lastX = mouse.x }
                onPositionChanged: function(mouse) {
                    if (pressed) { creator.heading += (mouse.x-lastX)*.65; lastX=mouse.x }
                }
                onWheel: function(wheel) { creator.distance = Math.max(1.6,Math.min(5,creator.distance-wheel.angleDelta.y*.002)) }
            }
            Text {
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.margins: 16
                text: "RÄVEKORRE"
                color: "#e9cf91"
                font.pixelSize: 18
                font.family: "monospace"
            }
            Text {
                anchors.bottom: parent.bottom
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottomMargin: 16
                text: creator.modelLoading ? "Laddar…" : "Dra för att rotera · scrolla för zoom"
                color: "#94a6ae"
                font.pixelSize: 11
            }
        }
        ColumnLayout {
            Layout.preferredWidth: Math.min(350,creator.width*.40)
            Layout.fillHeight: true
        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: availableWidth
            ColumnLayout {
                width: parent.width
                spacing: 12
                Text { text: "SKAPA KARAKTÄR"; color: "#e9cf91"; font.pixelSize: 19; font.family: "monospace" }
                TextField {
                    id: localName
                    objectName: "ggLocalCharacterName"
                    visible: creator.localSession !== null
                    Layout.fillWidth: true
                    placeholderText: "Karaktärens namn"
                    maximumLength: 24
                }
                Text { text: "RAS"; color: "#a1b3be"; font.pixelSize: 12 }
                Flow {
                    Layout.fillWidth: true
                    spacing: 6
                    Repeater {
                        model: creator.catalog.races || []
                        delegate: Button {
                            required property var modelData
                            text: modelData.name
                            enabled: modelData.ready
                            checkable: true
                            checked: creator.selection.race_id === modelData.id
                            onClicked: creator.choose("race_id",modelData.id)
                            ToolTip.visible: hovered && !modelData.ready
                            ToolTip.text: "Sparad för att färdigställas senare"
                        }
                    }
                }
                Text {
                    Layout.fillWidth: true
                    text: "De nio tidigare figurerna är sparade. Rävekorren är först ut med klassutrustning och färgval."
                    wrapMode: Text.WordWrap; color: "#8a9aa3"; font.pixelSize: 11
                }
                Text { text: "KLASS"; color: "#a1b3be"; font.pixelSize: 12 }
                Flow {
                    Layout.fillWidth: true
                    spacing: 6
                    Repeater {
                        model: creator.catalog.classes || []
                        delegate: Button {
                            required property var modelData
                            text: modelData.name
                            checkable: true
                            checked: creator.selection.class_id === modelData.id
                            onClicked: creator.choose("class_id",modelData.id)
                        }
                    }
                }
                Text {
                    Layout.fillWidth: true
                    text: {
                        var rows=creator.catalog.classes || []
                        for (var i=0;i<rows.length;++i) if (rows[i].id===creator.selection.class_id) return rows[i].description
                        return ""
                    }
                    color: "#b6c5ca"; wrapMode: Text.WordWrap; font.pixelSize: 12
                }
                Text { text: "PÄLS"; color: "#a1b3be"; font.pixelSize: 12 }
                Flow {
                    Layout.fillWidth: true
                    spacing: 8
                    Repeater {
                        model: creator.catalog.fur_colors || []
                        delegate: Rectangle {
                            required property var modelData
                            width: 46; height: 40; radius: 4
                            color: modelData.color
                            border.width: creator.selection.fur_id===modelData.id ? 3 : 1
                            border.color: creator.selection.fur_id===modelData.id ? "#ffe2a1" : "#71818a"
                            MouseArea { anchors.fill: parent; onClicked: creator.choose("fur_id",parent.modelData.id) }
                            ToolTip.visible: hoverFur.hovered
                            ToolTip.text: modelData.name
                            HoverHandler { id: hoverFur }
                        }
                    }
                }
                Text { text: "ÖGON"; color: "#a1b3be"; font.pixelSize: 12 }
                Flow {
                    Layout.fillWidth: true
                    spacing: 8
                    Repeater {
                        model: creator.catalog.eye_colors || []
                        delegate: Rectangle {
                            required property var modelData
                            width: 38; height: 38; radius: 19
                            color: modelData.color
                            border.width: creator.selection.eye_id===modelData.id ? 3 : 1
                            border.color: creator.selection.eye_id===modelData.id ? "#ffe2a1" : "#71818a"
                            Rectangle { anchors.centerIn: parent; width: 12; height: 18; radius: 6; color: "#111820" }
                            MouseArea { anchors.fill: parent; onClicked: creator.choose("eye_id",parent.modelData.id) }
                            ToolTip.visible: hoverEye.hovered
                            ToolTip.text: modelData.name
                            HoverHandler { id: hoverEye }
                        }
                    }
                }
                Text {
                    Layout.fillWidth: true
                    text: creator.notice
                    visible: text!==""
                    color: "#e9cf91"; wrapMode: Text.WordWrap; font.pixelSize: 12
                }
            }
        }
            Button {
                Layout.fillWidth: true
                objectName: "ggCharacterSave"
                text: creator.localSession ? "Skapa karaktären" : "Spara och använd karaktären"
                enabled: !creator.busy && creator.modelReady && (!creator.localSession || localName.text.trim().length > 0)
                onClicked: creator.send("APPLY")
            }
            Button { Layout.fillWidth: true; text: creator.localSession ? "Tillbaka till karaktärsval" : "Tillbaka till spelet"; onClicked: creator.closed() }
        }
    }
}
