import QtQuick
import QtQuick3D
CustomMaterial {
    property TextureInput uTexture: TextureInput { texture: Texture { } }
    property real uAlpha: 0
    shadingMode: CustomMaterial.Unshaded
    cullMode: Material.NoCulling
    depthDrawMode: Material.NeverDepthDraw
    sourceBlend: CustomMaterial.One
    destinationBlend: CustomMaterial.OneMinusSrcAlpha
    vertexShader: Qt.resolvedUrl("../shaders/gg-engine-star.vert")
    fragmentShader: Qt.resolvedUrl("../shaders/gg-engine-star.frag")
}
