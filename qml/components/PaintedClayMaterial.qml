import QtQuick
import QtQuick3D

// Shared image atlas, mapped in stable object coordinates for native instances.
GgBatchMaterial {
    property real uLampEmission: 0
    property int uSurfaceKind: 0 // architecture / flora / terrain / character
    shadingMode: CustomMaterial.Shaded
    vertexShader: Qt.resolvedUrl("../shaders/gg-painted-architecture.vert")
    fragmentShader: Qt.resolvedUrl("../shaders/gg-painted-architecture.frag")
    property TextureInput clayAtlas: TextureInput {
        texture: Texture {
            source: "../assets/authored/world/textures/clay-v4/runtime-atlas.png"
            generateMipmaps: true
            minFilter: Texture.Linear
            magFilter: Texture.Linear
            mipFilter: Texture.Linear
            tilingModeHorizontal: Texture.ClampToEdge
            tilingModeVertical: Texture.ClampToEdge
        }
    }
    cullMode: Material.NoCulling
}
