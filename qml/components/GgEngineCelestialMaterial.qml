import QtQuick
import QtQuick3D
CustomMaterial {
    property TextureInput uTexture: TextureInput { texture: Texture { } }
    property vector3d uDirection: Qt.vector3d(0,1,0)
    property vector3d uRight: Qt.vector3d(1,0,0)
    property vector3d uUp: Qt.vector3d(0,1,0)
    property real uSize: .0833
    property vector2d uSpan: Qt.vector2d(0,0)
    property vector4d uTint: Qt.vector4d(1,1,1,1)
    property real uDiscAlpha: 1
    property bool uGlare: false
    shadingMode: CustomMaterial.Unshaded
    cullMode: Material.NoCulling
    depthDrawMode: Material.NeverDepthDraw
    sourceBlend: CustomMaterial.One
    destinationBlend: uGlare ? CustomMaterial.One : CustomMaterial.OneMinusSrcAlpha
    vertexShader: Qt.resolvedUrl("../shaders/gg-engine-celestial.vert")
    fragmentShader: Qt.resolvedUrl("../shaders/gg-engine-celestial.frag")
}
