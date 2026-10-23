pragma ComponentBehavior: Bound
import QtQuick
import QtQuick3D

// Vertices and original event markers already share the native world anchor.
Node {
    id: actors
    objectName: "engineOriginalWorldActors"
    property var provider: null
    property var stream: null
    property vector3d cameraPosition: Qt.vector3d(0, 0, 0)
    property bool hidePlayer: false
    property bool textureTrilinear: true
    readonly property var lighting: stream ? stream.lighting : null
    readonly property bool originalLight: lighting && lighting.source === "ORIGINAL_LIGHT_DBC"
    function color3(v) { return Qt.vector3d(v[0], v[1], v[2]) }
    Repeater3D {
        model: actors.provider ? actors.provider.batches : []
        delegate: Model {
            id: part
            required property var modelData
            readonly property var s: modelData.state
            readonly property var fog: actors.originalLight ? actors.lighting.fog : s.fog || null
            property string worldEntityId: String(s.world_actor_id || "")
            objectName: "engineOriginalActor_" + worldEntityId
            geometry: modelData.geometry
            instancing: modelData.instancing
            pickable: s.kind !== "particle" && s.kind !== "ribbon"
            visible: s.visible !== false && !(actors.hidePlayer && s.world_actor_kind === "PLAYER")
            castsShadows: !s.no_depth_write && s.kind !== "particle" && s.kind !== "ribbon"
            materials: GgEngineModelMaterial {
                uModelKind: 1
                authoredMips: part.s.mip_levels || []
                uTrilinear: actors.textureTrilinear
                uWrapU: part.s.wrap_u !== false
                uWrapV: part.s.wrap_v !== false
                uBlendMode: part.s.blend || 0
                uVertexColors: !!part.s.vertex_colors
                uInstanced: !!part.modelData.instancing
                uUnlit: !!part.s.unlit
                uAmbient: actors.originalLight ? actors.color3(actors.lighting.ambient) : Qt.vector3d(.25, .25, .25)
                uDiffuse: actors.originalLight ? actors.color3(actors.lighting.diffuse) : Qt.vector3d(.75, .75, .75)
                uToLight: actors.originalLight ? actors.color3(actors.lighting.to_light) : Qt.vector3d(0, 1, 0)
                uTint: part.s.tint ? actors.color3(part.s.tint) : Qt.vector3d(1, 1, 1)
                uAlpha: part.s.alpha === undefined ? 1 : part.s.alpha
                uUvOffset: part.s.uv_offset ? Qt.vector2d(part.s.uv_offset[0], part.s.uv_offset[1]) : Qt.vector2d(0, 0)
                uUvScale: part.s.uv_scale ? Qt.vector2d(part.s.uv_scale[0], part.s.uv_scale[1]) : Qt.vector2d(1, 1)
                uUvRotation: part.s.uv_rotation ? Qt.vector2d(part.s.uv_rotation[0], part.s.uv_rotation[1]) : Qt.vector2d(1, 0)
                uUvPivoted: true
                uEnvironmentMap: !!part.s.env_map
                uCameraPosition: actors.cameraPosition
                uFarClip: actors.stream ? actors.stream.detailedFar : 0
                uFogNear: part.fog && !part.s.no_fog ? part.fog.near : 100000
                uFogFar: part.fog && !part.s.no_fog ? part.fog.far : 100001
                uFogColor: part.fog ? actors.color3(part.fog.color) : Qt.vector3d(0, 0, 0)
                uPlanarFog: true
                cullMode: part.s.two_sided ? Material.NoCulling : Material.BackFaceCulling
                depthDrawMode: !part.s.no_depth_write && (part.s.blend <= 1 || part.s.no_depth_write === false) ? Material.AlwaysDepthDraw : Material.NeverDepthDraw
                uTexture: TextureInput {
                    texture: Texture {
                        textureData: part.modelData.textureData
                        generateMipmaps: !part.s.mip_levels || part.s.mip_levels.length === 0
                        mipFilter: generateMipmaps ? (actors.textureTrilinear ? Texture.Linear : Texture.Nearest) : Texture.None
                        minFilter: Texture.Linear
                        magFilter: Texture.Linear
                        tilingModeHorizontal: part.s.wrap_u === false ? Texture.ClampToEdge : Texture.Repeat
                        tilingModeVertical: part.s.wrap_v === false ? Texture.ClampToEdge : Texture.Repeat
                    }
                }
            }
        }
    }
}
