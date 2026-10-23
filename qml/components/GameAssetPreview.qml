pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick3D
import QtQuick3D.AssetUtils

Rectangle {
    id: preview
    required property var controller
    readonly property var selected: controller.assetEditorState.selected || ({})
    property real yaw: -25
    property real pitch: -8
    property real zoom: 1
    color: "#1b2326"
    border.color: controller.frameBorder
    objectName: "gameAssetPreview"
    implicitHeight: 240
    View3D {
        id: assetView
        anchors.fill: parent
        environment: SceneEnvironment {backgroundMode:SceneEnvironment.Color;clearColor:"#1b2326";antialiasingMode:SceneEnvironment.MSAA}
        Node {
            id: orbit
            readonly property vector3d center: Qt.vector3d(
                (model.bounds.minimum.x+model.bounds.maximum.x)*.5,
                (model.bounds.minimum.y+model.bounds.maximum.y)*.5,
                (model.bounds.minimum.z+model.bounds.maximum.z)*.5)
            readonly property real extent: Math.max(.05,model.bounds.maximum.x-model.bounds.minimum.x,
                model.bounds.maximum.y-model.bounds.minimum.y,model.bounds.maximum.z-model.bounds.minimum.z)
            position: center
            eulerRotation: Qt.vector3d(preview.pitch,preview.yaw,0)
            PerspectiveCamera {id:previewCamera;z:orbit.extent*2*preview.zoom;clipNear:.001;clipFar:Math.max(1000,orbit.extent*10);fieldOfView:35}
        }
        DirectionalLight {eulerRotation:Qt.vector3d(-35,-30,0);brightness:1.2}
        DirectionalLight {eulerRotation:Qt.vector3d(30,140,0);brightness:.7}
        RuntimeLoader {
            id:model
            objectName:"gameAssetPreviewLoader"
            Component.onDestruction:preview.controller.forgetAssetMaterials(model)
            source:preview.selected.source || ""
            onStatusChanged: if(status===RuntimeLoader.Success)preview.controller.applyAssetMaterial(model,preview.selected.identity || "")
        }
        Connections {target:preview.controller
            function onAssetEditorRevisionChanged(){preview.controller.applyAssetMaterial(model,preview.selected.identity || "")}}
        camera:previewCamera
    }
    MouseArea {
        anchors.fill:parent
        property real lastX:0;property real lastY:0
        cursorShape:pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
        onPressed:function(mouse){lastX=mouse.x;lastY=mouse.y}
        onPositionChanged:function(mouse){if(pressed){preview.yaw+=(mouse.x-lastX)*.5;preview.pitch=Math.max(-85,Math.min(85,preview.pitch+(mouse.y-lastY)*.4));lastX=mouse.x;lastY=mouse.y}}
        onWheel:function(wheel){preview.zoom=Math.max(.35,Math.min(5,preview.zoom-wheel.angleDelta.y/120*.1))}
    }
    Text {anchors.left:parent.left;anchors.bottom:parent.bottom;anchors.margins:7;color:preview.controller.muted;font.pixelSize:10
        text:model.status===RuntimeLoader.Error ? model.errorString : "Dra för att rotera · scrolla för zoom"}
}
