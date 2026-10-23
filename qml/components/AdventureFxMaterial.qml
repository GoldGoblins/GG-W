import QtQuick
import QtQuick3D

// Both batches retain their per-vertex colour and center-to-edge alpha.
// Smoke/foam absorb light; magic/fire add HDR energy to the scene.
CustomMaterial {
    property real uTime: 0
    property bool additive: false
    property real uEnergy: additive ? 1.6 : 1.0
    property real uFogNear: 1000000
    property real uFogFar: 1000001
    property real uBeaconFar: 1000001
    property vector3d uCameraPosition: Qt.vector3d(0,0,0)
    property matrix4x4 uEnchantMatrix0: Qt.matrix4x4()
    property matrix4x4 uEnchantMatrix1: Qt.matrix4x4()
    shadingMode: CustomMaterial.Unshaded
    sourceBlend: CustomMaterial.SrcAlpha
    destinationBlend: additive ? CustomMaterial.One : CustomMaterial.OneMinusSrcAlpha
    depthDrawMode: Material.OpaqueOnlyDepthDraw
    cullMode: Material.NoCulling
    vertexShader: Qt.resolvedUrl("../shaders/gg-adventure-fx.vert")
    fragmentShader: Qt.resolvedUrl("../shaders/gg-adventure-fx.frag")
}
