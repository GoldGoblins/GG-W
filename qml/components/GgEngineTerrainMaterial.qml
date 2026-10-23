import QtQuick
import QtQuick3D
CustomMaterial {
    property bool uTrilinear: true
    property vector4d uMipCounts: Qt.vector4d(0,0,0,0)
    property TextureInput uMipTable: TextureInput { texture: Texture { source:Qt.resolvedUrl("engine/white.png");minFilter:Texture.Nearest;magFilter:Texture.Nearest } }
    property TextureInput uTexture: TextureInput { texture: Texture { source: Qt.resolvedUrl("engine/white.png") } }
    property TextureInput uLayer1: TextureInput { texture: Texture { source: Qt.resolvedUrl("engine/white.png") } }
    property TextureInput uLayer2: TextureInput { texture: Texture { source: Qt.resolvedUrl("engine/white.png") } }
    property TextureInput uLayer3: TextureInput { texture: Texture { source: Qt.resolvedUrl("engine/white.png") } }
    property TextureInput uAlphaMap: TextureInput { texture: Texture { source: Qt.resolvedUrl("engine/white.png") } }
    property TextureInput uShadowMap: TextureInput { texture: Texture { source: Qt.resolvedUrl("engine/white.png") } }
    property bool uModelSpaceLight: false
    property bool uVertexColors: false
    property bool uPointLight: false
    property bool uEnvironmentMap: false
    property vector3d uLightPosition: Qt.vector3d(0,0,0)
    property real uTiling: 8
    property vector3d uAmbient: Qt.vector3d(0.35,0.35,0.35)
    property vector3d uDiffuse: Qt.vector3d(0.65,0.65,0.65)
    property vector3d uToLight: Qt.vector3d(0.3,1,0.2)
    property vector3d uCameraPosition: Qt.vector3d(0,0,0)
    property vector3d uFogColor: Qt.vector3d(0,0,0)
    property real uFarClip: 0
    property real uFogNear: 100000
    property real uFogFar: 100001
    shadingMode: CustomMaterial.Unshaded
    vertexShader: Qt.resolvedUrl("../shaders/gg-engine-model.vert")
    fragmentShader: Qt.resolvedUrl("../shaders/gg-engine-terrain.frag")
    depthDrawMode: Material.AlwaysDepthDraw
    cullMode: Material.BackFaceCulling
}
