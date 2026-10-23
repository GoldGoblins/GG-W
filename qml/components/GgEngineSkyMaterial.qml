import QtQuick
import QtQuick3D
CustomMaterial {
    property vector3d uSky0: Qt.vector3d(0,0,0)
    property vector3d uSky1: Qt.vector3d(0,0,0)
    property vector3d uSky2: Qt.vector3d(0,0,0)
    property vector3d uSky3: Qt.vector3d(0,0,0)
    property vector3d uSky4: Qt.vector3d(0,0,0)
    property vector3d uFog: Qt.vector3d(0,0,0)
    property vector3d uEye: Qt.vector3d(0,0,0)
    property real uWarp: 0
    property real uSunAzimuth: 0
    shadingMode: CustomMaterial.Unshaded
    cullMode: Material.FrontFaceCulling
    depthDrawMode: Material.NeverDepthDraw
    vertexShader: Qt.resolvedUrl("../shaders/gg-engine-sky.vert")
    fragmentShader: Qt.resolvedUrl("../shaders/gg-engine-sky.frag")
}
