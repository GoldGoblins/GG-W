import QtQuick
import QtQuick3D

CustomMaterial {
    property bool uTrilinear: true
    property int uMipCount: 0
    property TextureInput uMipTable: TextureInput { texture: Texture { source:Qt.resolvedUrl("engine/white.png");minFilter:Texture.Nearest;magFilter:Texture.Nearest } }
    property TextureInput uTexture: TextureInput { texture: Texture { source:"../game/textures/white.png" } }
    property int uFrames: 1
    property vector2d uAtlasGrid: Qt.vector2d(1,1)
    property vector2d uAtlasSize: Qt.vector2d(1,1)
    property real uClock: 0
    property bool uScroll: false
    property bool uFullbright: false
    property bool uOcean: false
    property int uLiquidPath: 0
    property vector4d uShallow: Qt.vector4d(.08,.42,.55,.25)
    property vector4d uDeep: Qt.vector4d(.02,.15,.27,.85)
    property vector3d uAmbient: Qt.vector3d(.25,.25,.25)
    property vector3d uDiffuse: Qt.vector3d(.75,.75,.75)
    property vector3d uToLight: Qt.vector3d(0,1,0)
    property vector3d uSpecular: Qt.vector3d(.12,.12,.12)
    property vector3d uCameraPosition: Qt.vector3d(0,0,0)
    property vector3d uFogColor: Qt.vector3d(0,0,0)
    property real uFarClip: 0
    property real uFogNear: 100000
    property real uFogFar: 100001
    shadingMode: CustomMaterial.Unshaded
    cullMode: Material.NoCulling
    depthDrawMode: uFullbright ? Material.AlwaysDepthDraw : Material.NeverDepthDraw
    sourceBlend: uFullbright ? CustomMaterial.NoBlend : CustomMaterial.SrcAlpha
    destinationBlend: uFullbright ? CustomMaterial.NoBlend : CustomMaterial.OneMinusSrcAlpha
    vertexShader: "../shaders/gg-engine-liquid.vert"
    fragmentShader: "../shaders/gg-engine-liquid.frag"
}
