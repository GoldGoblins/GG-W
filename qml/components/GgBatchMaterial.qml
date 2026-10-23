import QtQuick3D

// One shared material per complete render lane, reused across retained batches.
CustomMaterial {
    property int renderLane: 0 // 0 OPAQUE, 1 MASK, 2 BLEND, 3 ADD, 4 MOD, 5 ADD_NO_ALPHA, 6 MOD2X
    sourceBlend: renderLane === 2 ? CustomMaterial.SrcAlpha
        : renderLane === 3 ? CustomMaterial.SrcAlpha
        : renderLane === 4 || renderLane === 6 ? CustomMaterial.DstColor
        : renderLane === 5 ? CustomMaterial.One : CustomMaterial.NoBlend
    destinationBlend: renderLane === 6 ? CustomMaterial.SrcColor
        : renderLane === 2 ? CustomMaterial.OneMinusSrcAlpha
        : renderLane === 3 || renderLane === 5 ? CustomMaterial.One
        : renderLane === 4 ? CustomMaterial.Zero : CustomMaterial.NoBlend
    depthDrawMode: renderLane === 0 || renderLane === 1
        ? Material.OpaqueOnlyDepthDraw : Material.NeverDepthDraw
}
