import QtQuick
import QtQuick3D

// GgEngine M2/WMO blend numbering: opaque, key, alpha, add, alpha-add, mod, mod2x.
CustomMaterial {
    property var authoredMips: []
    property int uMipCount: authoredMips.length
    property bool uTrilinear: true
    property bool uWrapU: true
    property bool uWrapV: true
    function mipRectangle(index) {
        var row=authoredMips[index]
        return row ? Qt.vector4d(row[0],row[1],row[2],row[3]) : Qt.vector4d(0,0,1,1)
    }
    property vector4d uMip0: mipRectangle(0)
    property vector4d uMip1: mipRectangle(1)
    property vector4d uMip2: mipRectangle(2)
    property vector4d uMip3: mipRectangle(3)
    property vector4d uMip4: mipRectangle(4)
    property vector4d uMip5: mipRectangle(5)
    property vector4d uMip6: mipRectangle(6)
    property vector4d uMip7: mipRectangle(7)
    property vector4d uMip8: mipRectangle(8)
    property vector4d uMip9: mipRectangle(9)
    property vector4d uMip10: mipRectangle(10)
    property vector4d uMip11: mipRectangle(11)
    property vector4d uMip12: mipRectangle(12)
    property vector4d uMip13: mipRectangle(13)
    property vector4d uMip14: mipRectangle(14)
    property vector4d uMip15: mipRectangle(15)
    property int uBlendMode: 0
    property int uModelKind: 0 // 0 WMO/clutter Lambert; 1 M2 order-2 sun lobe
    property bool uUnlit: false
    property bool uVertexColors: false
    property bool uInstanced: false
    property bool uSkybox: false
    property bool uFadeAlphaKey: false
    property bool uWmoInterior: false
    property int uWmoClass: 0 // 0 EXT, 1 TRANS, 2 INT
    property bool uWmoWindow: false
    property bool uPropProbe: false
    property vector4d uProbe0: Qt.vector4d(0,0,0,0)
    property vector4d uProbe1: Qt.vector4d(0,0,0,0)
    property vector4d uProbe2: Qt.vector4d(0,0,0,0)
    property vector4d uProbe3: Qt.vector4d(0,0,0,0)
    property vector4d uProbe4: Qt.vector4d(0,0,0,0)
    property vector4d uProbe5: Qt.vector4d(0,0,0,0)
    property vector4d uProbe6: Qt.vector4d(0,0,0,1)
    property vector3d uAmbient: Qt.vector3d(0.25,0.25,0.25)
    property vector3d uDiffuse: Qt.vector3d(0.75,0.75,0.75)
    property vector3d uToLight: Qt.vector3d(0,1,0)
    property vector3d uNightEmissive: Qt.vector3d(0,0,0)
    property bool uModelSpaceLight: false
    property bool uPointLight: false
    property bool uEnvironmentMap: false
    property vector3d uLightPosition: Qt.vector3d(0,0,0)
    property vector3d uTint: Qt.vector3d(1,1,1)
    property real uAlpha: 1
    property vector3d uFogColor: Qt.vector3d(0.4,0.5,0.6)
    property real uFarClip: 0
    property real uFogNear: 100000
    property real uFogFar: 100001
    property bool uPlanarFog: false
    property vector3d uCameraPosition: Qt.vector3d(0,0,0)
    property real uFadeNear: 100000
    property real uFadeFar: 100001
    property vector2d uUvOffset: Qt.vector2d(0,0)
    property vector2d uUvScale: Qt.vector2d(1,1)
    property vector2d uUvRotation: Qt.vector2d(1,0)
    property bool uUvPivoted: false
    property TextureInput uTexture: TextureInput {
        texture: Texture { source: Qt.resolvedUrl("engine/white.png") }
    }
    shadingMode: CustomMaterial.Unshaded
    vertexShader: uSkybox ? Qt.resolvedUrl("../shaders/gg-engine-skybox.vert") : uInstanced ? Qt.resolvedUrl("../shaders/gg-engine-model-instanced.vert") : Qt.resolvedUrl("../shaders/gg-engine-model.vert")
    fragmentShader: Qt.resolvedUrl("../shaders/gg-engine-model.frag")
    sourceBlend: uBlendMode >= 5 ? CustomMaterial.DstColor
        : uBlendMode === 3 ? CustomMaterial.One
        : uBlendMode === 2 || uBlendMode === 4 ? CustomMaterial.SrcAlpha : CustomMaterial.NoBlend
    destinationBlend: uBlendMode === 6 ? CustomMaterial.SrcColor
        : uBlendMode === 5 ? CustomMaterial.Zero
        : uBlendMode === 3 || uBlendMode === 4 ? CustomMaterial.One
        : uBlendMode === 2 ? CustomMaterial.OneMinusSrcAlpha : CustomMaterial.NoBlend
    depthDrawMode: uBlendMode <= 1 ? Material.OpaqueOnlyDepthDraw : Material.NeverDepthDraw
    cullMode: Material.NoCulling
}
