import QtQuick
import QtQuick3D
CustomMaterial {
    property real uFarClip: 350
    property bool uFogEnabled: true
    property vector3d uFogColor: Qt.vector3d(.4,.5,.6)
    shadingMode: CustomMaterial.Unshaded
    depthDrawMode: Material.AlwaysDepthDraw
    cullMode: Material.NoCulling
    vertexShader: Qt.resolvedUrl("../shaders/gg-engine-wdl.vert")
    fragmentShader: Qt.resolvedUrl("../shaders/gg-engine-wdl.frag")
}
