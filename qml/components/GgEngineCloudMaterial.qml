import QtQuick
import QtQuick3D
CustomMaterial {
    property TextureInput uTexture: TextureInput { texture: Texture { } }
    shadingMode: CustomMaterial.Unshaded
    cullMode: Material.NoCulling
    depthDrawMode: Material.NeverDepthDraw
    sourceBlend: CustomMaterial.One
    destinationBlend: CustomMaterial.OneMinusSrcAlpha
    vertexShader: Qt.resolvedUrl("../shaders/gg-engine-cloud.vert")
    fragmentShader: Qt.resolvedUrl("../shaders/gg-engine-cloud.frag")
}
