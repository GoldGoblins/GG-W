import QtQuick
import QtQuick3D

GgBatchMaterial { property string uiColorScope: "ui.widget.GroundCoverMaterial.GgBatchMaterial.1";
    renderLane: 1
    property url imageSource
    property vector3d uCameraRight: Qt.vector3d(1,0,0)
    property real uTime: 0
    shadingMode: CustomMaterial.Shaded
    cullMode: Material.NoCulling
    vertexShader: Qt.resolvedUrl("../shaders/gg-ground-cover.vert")
    fragmentShader: Qt.resolvedUrl("../shaders/gg-ground-cover.frag")
    property TextureInput foliageMap: TextureInput {
        texture: Texture {
            source: imageSource
            generateMipmaps: true
            minFilter: Texture.Linear
            mipFilter: Texture.Linear
            tilingModeHorizontal: Texture.ClampToEdge
            tilingModeVertical: Texture.ClampToEdge
        }
    }
}
