import QtQuick
import QtQuick3D

// QML color uniforms arrive in linear light. The horizon is exactly the Fog
// color; a broad flat band hides the last pixels of the terrain/sea far plane.
CustomMaterial {
    property color uTopColor: "#418ecf"
    property color uHorizonColor: "#a4ccd7"
    property color uBottomColor: "#527565"
    property color uCloudColor: "#e6edf1"
    property real uTime: 0
    property real uNight: 0
    Behavior on uTopColor { ColorAnimation { duration: 1600 } }
    Behavior on uBottomColor { ColorAnimation { duration: 1600 } }
    Behavior on uCloudColor { ColorAnimation { duration: 1600 } }
    shadingMode: CustomMaterial.Unshaded
    cullMode: Material.NoCulling
    vertexShader: Qt.resolvedUrl("../shaders/gg-atmosphere-sky.vert")
    fragmentShader: Qt.resolvedUrl("../shaders/gg-atmosphere-sky.frag")
}
