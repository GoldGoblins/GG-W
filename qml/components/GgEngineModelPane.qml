import QtQuick
import QtQuick3D
import QtQuick3D.AssetUtils

// Original M2 geometry stays retained while the supervised reader updates its pose.
Item {
    id: pane
    property url modelSource
    property var animationHost: null
    property var textureSettings: null
    readonly property bool textureTrilinear: textureSettings ? textureSettings.textureTrilinear : true
    property var originalRows: []
    property vector3d originalMinimum: Qt.vector3d(0,0,0)
    property vector3d originalMaximum: Qt.vector3d(0,0,0)
    property var originalCamera: ({})
    property quaternion originalCameraRotation: Qt.quaternion(1,0,0,0)
    property var originalLight: ({})
    property var originalFog: ({})
    property real originalPixelsPerUnit: 1280
    property vector3d originalScreenPosition: Qt.vector3d(0,0,0)
    property real originalRootScale: 1
    property real facing: 0
    property real modelScale: 1
    property vector3d modelPosition: Qt.vector3d(0,0,0)
    property real paneWidth: width
    property real paneHeight: height
    property real contentX: 0
    property real contentY: 0
    readonly property bool original: originalRows.length > 0
    readonly property bool authoredCamera: original && originalCamera.position !== undefined
    readonly property bool modelReady: original || mesh.status === RuntimeLoader.Success
    readonly property string modelError: mesh.status === RuntimeLoader.Error ? mesh.errorString : ""
    function vec(v, fallback) { return v ? Qt.vector3d(v[0],v[1],v[2]) : fallback }
    clip: true
    View3D {
        id: view
        width: pane.paneWidth; height: pane.paneHeight; x: pane.contentX; y: pane.contentY
        environment: SceneEnvironment { backgroundMode: SceneEnvironment.Transparent; antialiasingMode: SceneEnvironment.MSAA }
        camera: pane.authoredCamera ? recordCamera : pane.original ? screenCamera : fittedCamera
        OrthographicCamera {
            id: screenCamera
            x: pane.paneWidth/2; y: pane.paneHeight/2; z: 1000
            clipNear: .1; clipFar: 2000
            horizontalMagnification: 1; verticalMagnification: 1
        }
        Node {
            id: centre
            readonly property vector3d minimum: pane.original ? pane.originalMinimum : mesh.bounds.minimum
            readonly property vector3d maximum: pane.original ? pane.originalMaximum : mesh.bounds.maximum
            readonly property vector3d middle: minimum.plus(maximum).times(0.5)
            readonly property real extent: Math.max(.05,maximum.x-minimum.x,maximum.y-minimum.y,maximum.z-minimum.z)
            position: middle
            PerspectiveCamera { id: fittedCamera; z: centre.extent*2.1; clipNear: .001; clipFar: Math.max(1000,centre.extent*12); fieldOfView: 35 }
        }
        Node {
            eulerRotation.y: pane.facing*180/Math.PI
            scale: Qt.vector3d(pane.originalRootScale,pane.originalRootScale,pane.originalRootScale)
            position: pane.modelPosition
            PerspectiveCamera {
                id: recordCamera
                position: pane.vec(pane.originalCamera.position,Qt.vector3d(0,0,1))
                rotation: pane.originalCameraRotation
                fieldOfView: (pane.originalCamera.fov || .61)/Math.sqrt(1+Math.pow(pane.paneWidth/Math.max(1,pane.paneHeight),2))*180/Math.PI
                clipNear: Math.max(.0001,pane.originalCamera.near || .001)
                clipFar: Math.max(clipNear+.001,pane.originalCamera.far || 1000)
            }
        }
        DirectionalLight { eulerRotation: Qt.vector3d(-35,-30,0); brightness: 1.2 }
        DirectionalLight { eulerRotation: Qt.vector3d(30,140,0); brightness: .6 }
        RuntimeLoader {
            id: mesh; source: pane.modelSource
            onStatusChanged: {
                if(status===RuntimeLoader.Success && pane.animationHost
                    && typeof pane.animationHost.gameEngineRuntimeClip === "function")
                    pane.animationHost.gameEngineRuntimeClip(this,"idle",0,"")
            }
            Component.onDestruction: {
                if(pane.animationHost && typeof pane.animationHost.gameEngineReleaseRuntimeClip === "function")
                    pane.animationHost.gameEngineReleaseRuntimeClip(this)
            }
            eulerRotation.y: pane.facing*180/Math.PI
            scale: Qt.vector3d(pane.modelScale,pane.modelScale,pane.modelScale)
            position: pane.modelPosition
        }
        Node {
            // Without a file camera, WoW X/Y span the screen and +Z faces the eye.
            eulerRotation.x: pane.authoredCamera ? 0 : 90
            position: pane.authoredCamera ? pane.modelPosition : pane.originalScreenPosition
            scale: {
                var s = pane.authoredCamera ? pane.originalRootScale : pane.originalPixelsPerUnit
                return Qt.vector3d(s,s,s)
            }
            Node {
              eulerRotation.y: pane.facing*180/Math.PI
              Repeater3D {
                model: pane.originalRows
                delegate: Model {
                    required property var modelData
                    geometry: modelData.geometry
                    instancing: modelData.instancing
                    visible: modelData.state.alpha > 0 && modelData.state.visible !== false
                    materials: GgEngineModelMaterial { property string uiColorScope: "ui.widget.GgEngineModelPane.GgEngineModelMaterial.1";
                        authoredMips: modelData.state.mip_levels || []
                        uTrilinear: pane.textureTrilinear
                        uWrapU: !!modelData.state.wrap_u
                        uWrapV: !!modelData.state.wrap_v
                        uModelKind: 1
                        uVertexColors: !!modelData.state.vertex_colors
                        uInstanced: !!modelData.instancing
                        uBlendMode: modelData.state.blend
                        uUnlit: modelData.state.unlit
                        uAlpha: modelData.state.alpha
                        uTint: pane.vec(modelData.state.tint,Qt.vector3d(1,1,1))
                        uUvPivoted: true
                        uUvOffset: Qt.vector2d(modelData.state.uv_offset[0],modelData.state.uv_offset[1])
                        uUvScale: Qt.vector2d(modelData.state.uv_scale[0],modelData.state.uv_scale[1])
                        uUvRotation: Qt.vector2d(modelData.state.uv_rotation[0],modelData.state.uv_rotation[1])
                        uModelSpaceLight: true
                        uEnvironmentMap: !!modelData.state.env_map
                        uPointLight: !!(pane.originalLight.enabled && pane.originalLight.omni)
                        uLightPosition: pane.originalLight.vector ? Qt.vector3d(pane.originalLight.vector[0],pane.originalLight.vector[2],-pane.originalLight.vector[1]) : Qt.vector3d(0,0,0)
                        uAmbient: pane.originalLight.enabled && !pane.originalLight.omni ? pane.vec(pane.originalLight.ambient,Qt.vector3d(0,0,0)) : Qt.vector3d(0,0,0)
                        uDiffuse: pane.originalLight.enabled ? pane.vec(pane.originalLight.diffuse,Qt.vector3d(0,0,0)) : Qt.vector3d(0,0,0)
                        uToLight: uLightPosition.times(-1)
                        uFogColor: pane.vec(pane.originalFog.color,Qt.vector3d(0,0,0))
                        uPlanarFog: true
                        uFogNear: modelData.state.no_fog || pane.originalFog.near === undefined ? 100000 : pane.originalFog.near
                        uFogFar: modelData.state.no_fog || pane.originalFog.far === undefined ? 100001 : pane.originalFog.far
                        uCameraPosition: pane.authoredCamera ? recordCamera.scenePosition : screenCamera.scenePosition
                        cullMode: modelData.state.two_sided ? Material.NoCulling : Material.BackFaceCulling
                        depthDrawMode: modelData.state.no_depth_write ? Material.NeverDepthDraw : Material.AlwaysDepthDraw
                        uTexture: TextureInput {
                            texture: Texture {
                                textureData: modelData.textureData
                                generateMipmaps: !modelData.state.mip_levels || modelData.state.mip_levels.length === 0
                                minFilter: Texture.Linear
                                magFilter: Texture.Linear
                                mipFilter: generateMipmaps ? (pane.textureTrilinear ? Texture.Linear : Texture.Nearest) : Texture.None
                                tilingModeHorizontal: modelData.state.wrap_u ? Texture.Repeat : Texture.ClampToEdge
                                tilingModeVertical: modelData.state.wrap_v ? Texture.Repeat : Texture.ClampToEdge
                            }
                        }
                    }
                }
            }
            }
        }
    }
}
