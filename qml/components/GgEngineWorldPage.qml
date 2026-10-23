pragma ComponentBehavior: Bound
import QtQuick
import QtQuick3D

Node {
    id: world
    property var stream: null
    property vector3d cameraPosition: Qt.vector3d(0,0,0)
    property var sceneCamera: null
    property real cameraAspect: 1
    property bool animate: true
    property bool live: true
    property bool textureTrilinear: true
    property real timeSeconds: 0
    readonly property real detailedFar: stream ? stream.detailedFar : 0
    readonly property var lighting: stream ? stream.lighting : null
    readonly property bool originalLight: lighting && lighting.source === "ORIGINAL_LIGHT_DBC"
    readonly property bool skyboxReplaces: stream ? stream.skyboxReplacesCelestial : false
    function color3(value) { return Qt.vector3d(value[0],value[1],value[2]) }
    function sprite(name) {
        var rows=originalLight ? lighting.celestial_sprites || [] : []
        for (var i=0;i<rows.length;i++) if (rows[i].name===name) return rows[i]
        return {name:name,direction:[0,1,0],right:[1,0,0],up:[0,1,0],size:0,span:[0,0],alpha:0,tint:[0,0,0],glare:false}
    }
    function starAlpha(weight) {
        var byte=originalLight ? Math.floor(lighting.stars_alpha*254+1) : 0
        return byte<2 ? 0 : Math.round(byte*weight)/255
    }
    Repeater3D {
        model: world.stream ? world.stream.skyboxModel : null
        delegate: Model {
            id: skyboxPart
            required property var batchData
            readonly property var s: batchData.state
            objectName: "engineOriginalSkybox_"+s.order
            geometry: batchData.geometry
            position: world.cameraPosition.plus(world.color3(s.translation || [0,0,0]))
            rotation: s.rotation ? Qt.quaternion(s.rotation[3],s.rotation[0],s.rotation[1],s.rotation[2]) : Qt.quaternion(1,0,0,0)
            visible: s.visible !== false && !!world.sceneCamera
            depthBias: 500000-s.order
            castsShadows: false
            receivesShadows: false
            materials: GgEngineModelMaterial {
                authoredMips: skyboxPart.s.mip_levels || []
                uTrilinear: world.textureTrilinear
                uWrapU: !!skyboxPart.s.wrap_u
                uWrapV: !!skyboxPart.s.wrap_v
                uSkybox: true
                uModelKind: 1
                uBlendMode: skyboxPart.s.blend
                uAlpha: skyboxPart.s.alpha
                uFadeAlphaKey: skyboxPart.s.fade_key || false
                uUnlit: skyboxPart.s.unlit
                uEnvironmentMap: skyboxPart.s.environment_map
                uCameraPosition: world.cameraPosition
                uAmbient: world.originalLight ? world.color3(world.lighting.ambient) : Qt.vector3d(.25,.25,.25)
                uDiffuse: world.originalLight ? world.color3(world.lighting.diffuse) : Qt.vector3d(.75,.75,.75)
                uToLight: world.originalLight ? world.color3(world.lighting.to_light) : Qt.vector3d(0,1,0)
                uFogNear: world.originalLight && !skyboxPart.s.no_fog ? world.lighting.fog.near : 100000
                uFogFar: world.originalLight && !skyboxPart.s.no_fog ? world.lighting.fog.far : 100001
                uFogColor: world.originalLight ? world.color3(world.lighting.fog.color) : Qt.vector3d(0,0,0)
                depthDrawMode: Material.NeverDepthDraw
                cullMode: skyboxPart.s.two_sided ? Material.NoCulling : Material.BackFaceCulling
                uTexture: TextureInput { texture: Texture { textureData:skyboxPart.batchData.textureData;generateMipmaps: !skyboxPart.s.mip_levels || skyboxPart.s.mip_levels.length === 0;mipFilter:generateMipmaps ? (world.textureTrilinear ? Texture.Linear : Texture.Nearest) : Texture.None;minFilter:Texture.Linear;magFilter:Texture.Linear;tilingModeHorizontal:skyboxPart.s.wrap_u ? Texture.Repeat : Texture.ClampToEdge;tilingModeVertical:skyboxPart.s.wrap_v ? Texture.Repeat : Texture.ClampToEdge } }
            }
        }
    }
    Repeater3D {
        model: world.stream ? world.stream.weatherModel : null
        delegate: Model {
            required property var batchData
            readonly property var modelData: batchData
            readonly property var s: modelData.state
            objectName: "engineOriginalWeather_"+s.layer
            geometry: modelData.geometry
            instancing: modelData.instancing
            visible: s.visible !== false
            depthBias: -10000
            castsShadows: false
            receivesShadows: false
            materials: GgEngineWeatherMaterial {
                uLayer: modelData.state.layer
                uMipCount: (modelData.state.mip_counts || [0])[0]
                uTrilinear: world.textureTrilinear
                uMipTable: TextureInput { texture: Texture { textureData:modelData.mipTableData;minFilter:Texture.Nearest;magFilter:Texture.Nearest } }
                uCameraAnchor: world.color3(modelData.state.camera_anchor)
                uFarClip: world.detailedFar
                uSceneFog: world.originalLight && !!world.lighting.fog
                uFogNear: world.originalLight ? world.lighting.fog.near : 100000
                uFogFar: world.originalLight ? world.lighting.fog.far : 100001
                uTexture: TextureInput { texture: Texture { textureData:modelData.textureData;minFilter:Texture.Linear;magFilter:Texture.Linear;tilingModeHorizontal:Texture.ClampToEdge;tilingModeVertical:Texture.ClampToEdge } }
            }
        }
    }
    Repeater3D {
        model: world.stream ? world.stream.horizonBatches : []
        delegate: Model {
            required property var modelData
            objectName: "engineOriginalHorizon"
            geometry: modelData.geometry
            visible: modelData.state.visible !== false && !!world.sceneCamera
            castsShadows: false
            receivesShadows: false
            materials: GgEngineHorizonMaterial {
                uFarClip: world.detailedFar
                uFogEnabled: !!(world.originalLight && world.lighting.fog)
                uFogColor: world.originalLight ? world.color3(world.lighting.fog.color) : Qt.vector3d(0,0,0)
            }
        }
    }
    Repeater3D {
        model: world.stream ? world.stream.skyStars : []
        delegate: Model {
            required property var modelData
            objectName: "engineOriginalStars"
            geometry: modelData.geometry
            visible: world.originalLight && !world.skyboxReplaces && !!world.sceneCamera && world.lighting.submersion === "DRY" && world.lighting.stars_alpha>0
            position: world.cameraPosition
            scale: Qt.vector3d(distance,distance,distance)
            readonly property real distance: world.sceneCamera ? world.sceneCamera.clipFar*.88 : 3000
            depthBias: 1000000
            castsShadows: false
            receivesShadows: false
            materials: GgEngineStarMaterial {
                uAlpha: world.starAlpha(modelData.state.weight)
                uTexture: TextureInput { texture: Texture { textureData:modelData.textureData;minFilter:Texture.Linear;magFilter:Texture.Linear } }
            }
        }
    }
    Repeater3D {
        model: world.stream ? world.stream.skySprites : []
        delegate: Model {
            required property var modelData
            readonly property var s: world.sprite(modelData.spriteName)
            readonly property real distance: s.glare ? 12 : world.sceneCamera ? world.sceneCamera.clipFar*.85 : 3000
            objectName: "engineOriginalCelestial_"+modelData.spriteName
            geometry: modelData.geometry
            position: world.cameraPosition
            scale: Qt.vector3d(distance,distance,distance)
            visible: world.originalLight && !!world.sceneCamera && s.size>0 && (s.glare ? s.alpha>0 : !world.skyboxReplaces && world.lighting.submersion === "DRY")
            depthBias: s.glare ? -20000 : s.name==="sun" ? 820000 : s.name==="moon" ? 810000 : 800000
            castsShadows: false
            receivesShadows: false
            materials: GgEngineCelestialMaterial {
                uTexture: TextureInput { texture: Texture { textureData:modelData.textureData;minFilter:Texture.Linear;magFilter:Texture.Linear } }
                uDirection: world.color3(s.direction)
                uRight: world.color3(s.right)
                uUp: world.color3(s.up)
                uSize: s.size
                uSpan: Qt.vector2d(s.span[0],s.span[1])
                uTint: Qt.vector4d(s.tint[0],s.tint[1],s.tint[2],s.glare ? s.alpha : 1)
                uDiscAlpha: s.alpha
                uGlare: s.glare
            }
        }
    }
    Model {
        objectName: "engineOriginalSky"
        visible: world.originalLight && !world.skyboxReplaces && !!world.sceneCamera && world.lighting.submersion === "DRY"
        source: "#Sphere"
        position: world.cameraPosition
        scale: Qt.vector3d(20,20,20)
        castsShadows: false
        receivesShadows: false
        materials: GgEngineSkyMaterial {
            uSky0: world.originalLight ? world.color3(world.lighting.sky[0]) : Qt.vector3d(0,0,0)
            uSky1: world.originalLight ? world.color3(world.lighting.sky[1]) : Qt.vector3d(0,0,0)
            uSky2: world.originalLight ? world.color3(world.lighting.sky[2]) : Qt.vector3d(0,0,0)
            uSky3: world.originalLight ? world.color3(world.lighting.sky[3]) : Qt.vector3d(0,0,0)
            uSky4: world.originalLight ? world.color3(world.lighting.sky[4]) : Qt.vector3d(0,0,0)
            uFog: world.originalLight ? world.color3(world.lighting.fog.color) : Qt.vector3d(0,0,0)
            uEye: world.cameraPosition
            uWarp: world.originalLight ? world.lighting.sky_warp : 0
            uSunAzimuth: world.originalLight ? world.lighting.sun_azimuth : 0
        }
    }
    Model {
        objectName: "engineOriginalClouds"
        depthBias: 600000
        visible: world.originalLight && !world.skyboxReplaces && !!world.sceneCamera && world.lighting.submersion === "DRY" && !!world.stream.cloudGeometry
        geometry: world.stream ? world.stream.cloudGeometry : null
        position: world.cameraPosition
        scale: Qt.vector3d(1,1,1).times(world.sceneCamera ? world.sceneCamera.clipFar*.87 : 87)
        castsShadows: false
        receivesShadows: false
        materials: GgEngineCloudMaterial {
            uTexture: TextureInput { texture: Texture { textureData: world.stream ? world.stream.cloudTexture : null; minFilter:Texture.Linear; magFilter:Texture.Linear } }
        }
    }
    onSceneCameraChanged: if (!sceneCamera && stream) stream.clearView()
    visible: !!stream && stream.active
    FrameAnimation {
        running: world.visible && world.live && (world.animate || !!world.sceneCamera)
        onTriggered: {
            if (world.animate) {
                var step=isFinite(frameTime) && frameTime>0 ? Math.min(frameTime,.25) : 0
                world.timeSeconds+=step
                if (world.stream) world.stream.advance(step)
            }
            var camera=world.sceneCamera
            if (camera && world.stream) {
                var p=camera.scenePosition,f=camera.mapDirectionToScene(Qt.vector3d(0,0,-1)),u=camera.up
                world.stream.setView({eye:[p.x,p.y,p.z],forward:[f.x,f.y,f.z],up:[u.x,u.y,u.z],
                    fov:camera.fieldOfView,aspect:world.cameraAspect,near:camera.clipNear,far:camera.clipFar})
            }
        }
    }
    Repeater3D {
        model: world.stream ? world.stream.model : null
        delegate: Model {
            id: page
            objectName: "originalPage_"+s.kind
            property var materialObject: null
            Component.onCompleted: {
                materialObject=(terrain ? terrainComponent : liquid ? liquidComponent : wmoComponent).createObject(page)
                Qt.callLater(function() { if (page.modelData) page.modelData.publish() })
            }
            required property var batchData
            readonly property var modelData: batchData
            readonly property var s: modelData.state
            geometry: modelData.geometry
            instancing: modelData.instancing
            visible: s.visible !== false
            pickable: true
            readonly property bool terrain: s.kind === "terrain"
            readonly property bool liquid: s.kind === "liquid"
            readonly property bool m2: s.kind === "m2"
            readonly property var fog: world.originalLight ? world.lighting.fog : s.fog || null
            function waterColor(deep) {
                if (world.originalLight && (s.liquid_kind === "STILL" || s.liquid_kind === "WATER" || s.liquid_kind === "OCEAN" || s.liquid_kind === "RAPIDS")) {
                    var colors=s.liquid_kind === "OCEAN" ? world.lighting.water_ocean : world.lighting.water_river
                    var alpha=s.liquid_kind === "OCEAN" ? world.lighting.water_ocean_alpha : world.lighting.water_river_alpha
                    return Qt.vector4d(colors[deep][0],colors[deep][1],colors[deep][2],alpha[deep])
                }
                var c=deep ? s.deep : s.shallow
                return Qt.vector4d(c[0],c[1],c[2],c[3])
            }
            function probeRow(i) {
                var p=s.prop_light && s.prop_light.probe ? s.prop_light.probe[i] : [0,0,0,i===6 ? 1 : 0]
                return Qt.vector4d(p[0],p[1],p[2],p[3])
            }
            materials: materialObject ? [materialObject] : []
            Component { id: terrainComponent
            GgEngineTerrainMaterial {
                id: terrainMaterial
                uMipCounts: Qt.vector4d(page.s.mip_counts[0],page.s.mip_counts[1],page.s.mip_counts[2],page.s.mip_counts[3])
                uTrilinear: world.textureTrilinear
                uMipTable: TextureInput { texture: Texture { textureData:page.modelData.mipTableData;minFilter:Texture.Nearest;magFilter:Texture.Nearest } }
                uFarClip: world.detailedFar
                uAmbient: world.originalLight ? world.color3(world.lighting.ambient) : Qt.vector3d(.35,.35,.35)
                uDiffuse: world.originalLight ? world.color3(world.lighting.diffuse) : Qt.vector3d(.65,.65,.65)
                uToLight: world.originalLight ? world.color3(world.lighting.to_light) : Qt.vector3d(.3,1,.2)
                uCameraPosition: world.cameraPosition
                uFogNear: page.fog ? page.fog.near : 100000
                uFogFar: page.fog ? page.fog.far : 100001
                uFogColor: page.fog ? world.color3(page.fog.color) : Qt.vector3d(0,0,0)
                uTexture: TextureInput { texture: Texture { objectName:"worldPageTexture"; textureData: page.modelData.textureData; generateMipmaps: !page.s.mip_levels || page.s.mip_levels.length === 0; minFilter:Texture.Linear; magFilter:Texture.Linear; mipFilter:generateMipmaps ? (world.textureTrilinear ? Texture.Linear : Texture.Nearest) : Texture.None; tilingModeHorizontal: Texture.Repeat; tilingModeVertical: Texture.Repeat } }
                uLayer1: TextureInput { texture: Texture { generateMipmaps:page.s.mip_counts[1] === 0; minFilter:Texture.Linear; magFilter:Texture.Linear; mipFilter:generateMipmaps ? (world.textureTrilinear ? Texture.Linear : Texture.Nearest) : Texture.None; textureData: page.terrain ? page.modelData.stages[0] : null; tilingModeHorizontal: Texture.Repeat; tilingModeVertical: Texture.Repeat } }
                uLayer2: TextureInput { texture: Texture { generateMipmaps:page.s.mip_counts[2] === 0; minFilter:Texture.Linear; magFilter:Texture.Linear; mipFilter:generateMipmaps ? (world.textureTrilinear ? Texture.Linear : Texture.Nearest) : Texture.None; textureData: page.terrain ? page.modelData.stages[1] : null; tilingModeHorizontal: Texture.Repeat; tilingModeVertical: Texture.Repeat } }
                uLayer3: TextureInput { texture: Texture { generateMipmaps:page.s.mip_counts[3] === 0; minFilter:Texture.Linear; magFilter:Texture.Linear; mipFilter:generateMipmaps ? (world.textureTrilinear ? Texture.Linear : Texture.Nearest) : Texture.None; textureData: page.terrain ? page.modelData.stages[2] : null; tilingModeHorizontal: Texture.Repeat; tilingModeVertical: Texture.Repeat } }
                uAlphaMap: TextureInput { texture: Texture { textureData: page.terrain ? page.modelData.stages[3] : null } }
                uShadowMap: TextureInput { texture: Texture { textureData: page.terrain ? page.modelData.stages[4] : null } }
            }
            }
            Component { id: liquidComponent
            GgEngineLiquidMaterial {
                uFarClip: world.detailedFar
                uMipCount: (page.s.mip_counts || [0])[0]
                uTrilinear: world.textureTrilinear
                uMipTable: TextureInput { texture: Texture { textureData:page.modelData.mipTableData;minFilter:Texture.Nearest;magFilter:Texture.Nearest } }
                uFrames: page.s.frames || 1
                uAtlasGrid: Qt.vector2d(page.s.atlas_grid[0],page.s.atlas_grid[1])
                uAtlasSize: Qt.vector2d(page.s.atlas_size[0],page.s.atlas_size[1])
                uClock: world.timeSeconds
                uScroll: !!page.s.scroll
                uFullbright: !!page.s.fullbright
                uOcean: page.s.liquid_kind === "OCEAN"
                uLiquidPath: page.s.liquid_path
                uShallow: page.waterColor(0)
                uDeep: page.waterColor(1)
                uCameraPosition: world.cameraPosition
                uFogNear: page.fog ? page.fog.near : 100000
                uFogFar: page.fog ? page.fog.far : 100001
                uFogColor: page.fog ? world.color3(page.fog.color) : Qt.vector3d(0,0,0)
                uTexture: TextureInput { texture: Texture { objectName:"worldLiquidAtlas"; textureData: page.modelData.textureData; minFilter:Texture.Linear; magFilter:Texture.Linear } }
            }
            }
            Component { id: wmoComponent
            GgEngineModelMaterial {
                id: wmoMaterial
                uFarClip: world.detailedFar
                uModelKind: page.m2 ? 1 : 0
                authoredMips: page.s.mip_levels || []
                uTrilinear: world.textureTrilinear
                uWrapU: page.s.wrap_u !== false
                uWrapV: page.s.wrap_v !== false
                uBlendMode: page.s.blend
                uVertexColors: !!page.s.vertex_colors
                uInstanced: !!page.modelData.instancing
                uWmoInterior: !!page.s.interior
                uWmoClass: page.s.wmo_class || 0
                uWmoWindow: !!page.s.window
                uUnlit: !!page.s.unlit
                uPropProbe: page.m2 && !!page.s.prop_light && !!page.s.prop_light.interior
                uProbe0: page.probeRow(0)
                uProbe1: page.probeRow(1)
                uProbe2: page.probeRow(2)
                uProbe3: page.probeRow(3)
                uProbe4: page.probeRow(4)
                uProbe5: page.probeRow(5)
                uProbe6: page.probeRow(6)
                uAmbient: (world.originalLight ? world.color3(world.lighting.ambient) : Qt.vector3d(.25,.25,.25)).times(page.s.prop_light && page.s.prop_light.shade !== undefined ? page.s.prop_light.shade : 1)
                uDiffuse: (world.originalLight ? world.color3(world.lighting.diffuse) : Qt.vector3d(.75,.75,.75)).times(page.s.prop_light && page.s.prop_light.shade !== undefined ? page.s.prop_light.shade : 1)
                uToLight: world.originalLight ? world.color3(world.lighting.to_light) : Qt.vector3d(0,1,0)
                uNightEmissive: page.s.sidn && world.originalLight ? world.color3(page.s.sidn).times(world.lighting.sidn) : Qt.vector3d(0,0,0)
                uTint: page.s.tint ? Qt.vector3d(page.s.tint[0],page.s.tint[1],page.s.tint[2]) : Qt.vector3d(1,1,1)
                uAlpha: page.s.alpha === undefined ? 1 : page.s.alpha
                uUvOffset: page.s.uv_offset ? Qt.vector2d(page.s.uv_offset[0],page.s.uv_offset[1]) : Qt.vector2d(0,0)
                uUvScale: page.s.uv_scale ? Qt.vector2d(page.s.uv_scale[0],page.s.uv_scale[1]) : Qt.vector2d(1,1)
                uUvRotation: page.s.uv_rotation ? Qt.vector2d(page.s.uv_rotation[0],page.s.uv_rotation[1]) : Qt.vector2d(1,0)
                uUvPivoted: page.m2
                uEnvironmentMap: !!page.s.env_map
                uCameraPosition: world.cameraPosition
                uFogNear: page.fog && !page.s.no_fog ? page.fog.near : 100000
                uFogFar: page.fog && !page.s.no_fog ? page.fog.far : 100001
                uFogColor: page.fog ? world.color3(page.fog.color) : Qt.vector3d(0,0,0)
                uPlanarFog: true
                cullMode: page.s.two_sided ? Material.NoCulling : Material.BackFaceCulling
                depthDrawMode: !page.s.no_depth_write && (page.s.blend <= 1 || page.m2 && page.s.no_depth_write === false) ? Material.AlwaysDepthDraw : Material.NeverDepthDraw
                uTexture: TextureInput { texture: Texture { objectName:"worldPageTexture"; textureData: page.modelData.textureData; generateMipmaps: !page.s.mip_levels || page.s.mip_levels.length === 0; minFilter:Texture.Linear; magFilter:Texture.Linear; mipFilter:generateMipmaps ? (world.textureTrilinear ? Texture.Linear : Texture.Nearest) : Texture.None; tilingModeHorizontal: page.s.wrap_u === false ? Texture.ClampToEdge : Texture.Repeat; tilingModeVertical: page.s.wrap_v === false ? Texture.ClampToEdge : Texture.Repeat } }
            }
            }
        }
    }
}
