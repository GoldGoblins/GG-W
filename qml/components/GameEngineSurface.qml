pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Window
import QtQuick3D
import QtQuick3D.AssetUtils
import QtQuick3D.Helpers
import "engine/WorldFx.js" as WorldFx
import "engine/WorldAtmosphere.js" as WorldAtmosphere
import "engine/FlailPhysics.js" as FlailPhysics
import "LocalServiceState.js" as LocalServiceState

Item {
    id: root
    objectName: "workspaceGameEnginePane"

    // The workbench preview and the standalone player share this renderer and
    // simulation, but the standalone window owns its own HUD and menus.
    property var actionBarWidget: null
    property var actionDrag: ({})
    property real actionDragX: 0
    property real actionDragY: 0
    property var worldHoverInfo: ({})
    property real worldMouseX: 0
    property real worldMouseY: 0
    property bool worldMouseInside: false
    property double lastHoverAt: 0
    property real snapshotBridgeMs: 0
    property real snapshotBindingsMs: 0
    property real snapshotModelsMs: 0
    readonly property var actionState: root.renderStatus.actions || root.status.actions || ({})
    readonly property string abilityCatalogJson: JSON.stringify(root.actionState.abilities || [])
    readonly property var abilityCatalog: JSON.parse(root.abilityCatalogJson)
    property bool standalonePlayerMode: false
    property bool controlsLocked: false
    signal gameMenuRequested()

    property var surfaceHost: null
    readonly property var nativeScenePresentation: surfaceHost && surfaceHost.gameEnginePresentation
        ? surfaceHost.gameEnginePresentation() : null
    readonly property var originalWorldActors: nativeScenePresentation ? nativeScenePresentation.worldActors : null
    property var localServiceState: ({})
    property var engineWorld: surfaceHost && surfaceHost.gameEngineImportedWorld ? surfaceHost.gameEngineImportedWorld() : null
    readonly property bool originalWorldActive: !!engineWorld && engineWorld.active
    property string worldLoadMessage: ""
    property var mountedWorldState: ({status:"GG",message:""})
    function selectGgEngineWorld(manifest) {
        if (!surfaceHost || !surfaceHost.gameEngineLoadImportedWorld) return
        var result=JSON.parse(surfaceHost.gameEngineLoadImportedWorld(String(manifest)))
        worldLoadMessage=result.ok ? "" : String(result.error || "World load failed")
        engineWorld=surfaceHost.gameEngineImportedWorld()
        refresh()
    }
    FileDialog {
        id: worldManifestDialog
        title: "Select a world"
        nameFilters: ["World manifest (*.json)"]
        currentFolder: Qt.resolvedUrl("../game")
        onAccepted: root.selectGgEngineWorld(selectedFile)
    }
    property color frameBorder: "#6a6a6a"
    property int frameRadius: 4
    // WorkspaceSurface keeps this pane loaded while hidden.  paneLive is
    // the Loader's visible flag; local `visible` stays true on the child.
    property bool paneLive: true
    property bool resumeWhenShown: false
    property string statusJson: "{}"
    // The full status drives inspectors at a bounded cadence.  The render
    // status is a compact transform/pose stream and may update every frame
    // without reparsing inventories, NPC identities and content catalogs.
    property string renderStatusJson: "{}"
    // UI deltas replace only dynamic inspector sections over the last full
    // snapshot.  They never own simulation state or the render model.
    property string uiStatusJson: "{}"
    property bool fullStatusApplyInProgress: false
    property bool fullStatusReady: false
    property bool renderStreamPrimed: false
    property string page: "PLAY"
    property string selectedItemId: ""
    property string itemNotice: ""
    property bool bankViewOpen: false
    property real throttle: 0
    property real steer: 0
    property real strafe: 0
    property real brake: 0
    property real vertical: 0
    property bool boost: false
    property bool jump: false
    property bool grapple: false
    // Presentation is disposable; the simulation remains authoritative when
    // the rich scene is unavailable.  This local flag is also useful for a
    // future native graphics watchdog that cannot safely mutate game state.
    property bool localGraphicsFailure: false
    // A/D turns the character; E interacts and Q fires/releases the grapple.
    // Camera orbit stays relative to player heading so the default view
    // remains behind the +Z-facing Blender avatar. The 180 degree base offset
    // puts the camera at its back.
    property var pressedTokens: ({})
    property string bindingCaptureAction: ""
    property real orbitYaw: 0
    property bool mouseRightHeld: false
    property bool mouseLeftHeld: false
    property real mouseLookHeading: 0
    property real leftLookHeading: 0
    readonly property real characterHeading: root.number(root.player.yaw, 0) * 57.29577951308232
    readonly property real cameraHeading: root.mouseRightHeld ? root.mouseLookHeading
        : (root.mouseLeftHeld ? root.leftLookHeading : root.characterHeading + root.orbitYaw)
    readonly property real cameraWorldYaw: root.wrapDegrees(root.cameraHeading + 180)
    // Meter-based framing: chest/head pivot, six-meter boom, mild downward pitch.
    // Character GLBs stay at their authored human scale.
    property real cameraDistance: 6
    property real orbitPitch: -8
    property int cameraViewRevision: -1
    property var clientDisplay: ({})
    readonly property bool firstPersonView: root.cameraDistance < 0.01
    function syncClientCamera(snapshot) {
        var control=(snapshot.player || {}).client_controls
        if (!control || control.revision === undefined)
            return
        root.clientDisplay=control.display || ({})
        if (control.revision === root.cameraViewRevision) return
        root.cameraViewRevision=control.revision
        root.cameraDistance=root.number(control.distance,6)
        root.orbitPitch=root.number(control.pitch,-8)
        root.orbitYaw=root.wrapDegrees(root.number(control.yaw,0))
        root.mouseLookHeading=root.characterHeading+root.orbitYaw
        root.leftLookHeading=root.mouseLookHeading
        root.importedCameraReady=false
    }
    readonly property real cameraPivotOffsetM: 0.8
    property vector3d importedCameraSeat: Qt.vector3d(0,0,0)
    property bool importedCameraReady: false
    property bool cameraWaterCollision: true
    function updateImportedCamera(delta) {
        if (!root.originalWorldActive || !root.engineWorld) {
            root.importedCameraReady=false
            return
        }
        root.importedCameraSeat=root.engineWorld.solveCamera({
            feet:[root.number(root.player.x,0),root.number(root.player.y,0)-.65,root.number(root.player.z,0)],
            head_height:1.4,pivot_height:.65+root.cameraPivotOffsetM,
            yaw:root.cameraWorldYaw,pitch:root.orbitPitch,
            distance:root.cameraDistance*root.cameraDistanceScale,
            delta:Math.max(0,Math.min(1,delta)),water_collision:root.cameraWaterCollision})
        root.importedCameraReady=true
    }
    onOriginalWorldActiveChanged: { importedCameraReady=false; updateImportedCamera(0) }
    // The navigation rail and the inspector are independent overlays.  Their
    // collapsed forms deliberately keep a small click target over the scene
    // instead of removing the route or stealing space from the engine view.
    property bool leftMenuCollapsed: false
    property bool inspectorCollapsed: false
    property var assetEditorState: ({})
    property string assetEditorError: ""
    property int assetEditorRevision: 0
    property var assetMaterialRecords: []
    property string assetTool: "SELECT"
    readonly property bool assetEditorMode: !root.standalonePlayerMode && (root.page === "EDIT" || root.page === "ASSETS")
    property var assetDrag: ({})
    property double assetDragSentAt: 0
    property bool floraEnabled: true
    property bool frustumCullingEnabled: true
    // Actual Qt counters belong to the View3D/window, not the simulation.
    readonly property string rendererMeasurementsJson: JSON.stringify({
        fps: view3d.renderStats.fps,
        frame_ms: view3d.renderStats.frameTime,
        sync_cpu_ms: view3d.renderStats.syncTime,
        render_cpu_ms: view3d.renderStats.renderTime,
        gpu_window_ms: view3d.renderStats.lastCompletedGpuTime > 0
            ? view3d.renderStats.lastCompletedGpuTime : null,
        draw_calls: view3d.renderStats.extendedDataCollectionEnabled
            ? view3d.renderStats.drawCallCount : null,
        render_passes: view3d.renderStats.extendedDataCollectionEnabled
            ? view3d.renderStats.renderPassCount : null,
        graphics_api: view3d.renderStats.graphicsApiName
    })
    // QtQuick3D's built-in primitive meshes are authored at 100 units.  The
    // simulation uses compact gameplay coordinates, so keep the conversion in
    // one place instead of distorting the physics data.
    readonly property real sceneScale: 0.01
    readonly property real terrainCellSize: 16.0
    readonly property bool ps2ClassicRenderer:
        String(root.render.profile || "PS2_CLASSIC") === "PS2_CLASSIC"
    // The console-era profile uses baked/environment shading and the
    // existing low-cost player blob; it does not allocate a dynamic shadow
    // map. Point-light shadows are off because they cost six cubemap passes.
    readonly property bool shadowMappingEnabled:
        String(root.render.profile || "PS2_CLASSIC") !== "POTATO"
        && !root.ps2ClassicRenderer
    readonly property real internalResolutionScale: {
        var policy = root.render.policy || ({})
        return Math.max(
            0.5,
            Math.min(1.25, root.number(policy.resolution_scale, 0.67))
        )
    }
    property bool applyingRenderStatus: false
    property var waterWaveGeometry: null
    property var particleBatchGeometry: null
    property int particleBatchCount: 0
    property var additiveParticleGeometry: null
    property int additiveParticleCount: 0
    property var worldFxAnchors: []
    property var worldAmbientAnchors: []
    property var worldLightBeacons: []
    property var localLightSources: []
    property double lastWorldFxAnchorUpdate: 0
    property var equipmentFxNodes: ({})
    property var enchantMesh0: null
    property var enchantMesh1: null
    property var lastVisualSnapshot: ({})
    property var lastVisualRenderView: ({})
    readonly property vector3d groundCoverRight: Qt.vector3d(
        Math.cos(root.cameraWorldYaw*Math.PI/180),0,-Math.sin(root.cameraWorldYaw*Math.PI/180))
    property int enchantOwnedScrollIndex: 0
    readonly property string selectedEnchantScrollId: root.ownedEnchantScrolls.length > 0
        ? root.ownedEnchantScrolls[Math.min(root.enchantOwnedScrollIndex, root.ownedEnchantScrolls.length-1)].scroll_enchant_id : ""
    property int enchantPrimaryIndex: 0
    property int enchantSecondIndex: 0
    property int enchantThirdIndex: 0
    property int enchantGearIndex: 0
    property int enchantRecipeMode: 0
    readonly property var enchantRecipe: WorldFx.recipeForChoices(
        root.enchantPrimaryIndex, root.enchantSecondIndex, root.enchantThirdIndex,
        root.enchantGearIndex, root.enchantRecipeMode)
    readonly property var ownedEnchantScrolls: (root.items.inventory || []).filter(
        function(row) { return !!row.scroll_enchant_id })
    readonly property var enchantStation: ((root.status.crafting || {}).workstations || []).filter(
        function(row) { return row.id === "station.enchanting_altar" })[0] || ({})
    property int fxPreviewIndex: -1
    readonly property string fxPreviewStyle:
        root.fxPreviewIndex >= 0
            ? WorldFx.PREVIEW_STYLES[root.fxPreviewIndex] : ""
    property bool sandoverBirdClipBound: false
    property bool sandoverFishClipBound: false
    property var renderModelIndex: ({
        "terrainRow": ({}),
        "entityRow": ({})
    })
    // Replace Qt's dense convenience sphere with one shared native mesh.
    // GG_CLAY_ASSET_KIT is the shared item/prop style contract: one cached
    // indexed mesh family, vertex-colored matte clay, no primitive disguise.
    // The QML helper is a capability fallback for an already-running host
    // whose Python bridge predates this property.  It is deliberately
    // configured to the same 12-segment/6-ring budget, never Qt's dense
    // built-in #Sphere.
    SphereGeometry {
        id: lowPolySphereGeometryFallback
        objectName: "gameLowPolySphereGeometryFallback"
        radius: 50
        rings: 6
        segments: 12
        asynchronous: false
    }
    readonly property var lowPolySphereGeometry:
        root.surfaceHost
        && typeof root.surfaceHost.gameEngineLowPolySphereGeometry === "function"
            ? (root.surfaceHost.gameEngineLowPolySphereGeometry()
                || lowPolySphereGeometryFallback)
            : lowPolySphereGeometryFallback
    // The target is intentionally UI state.  The authoritative edit and its
    // undo history remain in the bounded backend terrain document.
    property bool terrainTargetSelected: false
    property int terrainTargetX: 0
    property int terrainTargetZ: 0
    property string terrainTargetKey: ""
    property real terrainBrushX: terrainCellSize * 0.5
    property real terrainBrushZ: terrainCellSize * 0.5
    property real terrainBrushRadius: 4.0
    property string terrainBrushFalloff: "SMOOTH"
    property bool terrainBrushEnabled: false
    property string terrainBrushOperation: "RAISE"

    readonly property color ink: "#e6edf3"
    readonly property color text: "#c8cdd4"
    readonly property color muted: "#7f8993"
    readonly property color panel: "#181818"
    readonly property color panelRaised: "#202020"
    readonly property color selectedPanel: "#34383d"
    readonly property color ledgerGold: "#c8a97e"
    readonly property color ledgerGreen: "#8db89a"
    readonly property color signalBlue: "#7fa9c4"
    readonly property color signalRed: "#c98989"
    readonly property color signalViolet: "#b6a6c8"
    // OSINT density: overlays carry the data while the 3D scene remains
    // visible underneath. Raised cards are still transparent enough to read
    // as instrumentation rather than a second application window.
    readonly property color panelOverlay: Qt.rgba(0.067, 0.082, 0.09, 0.24)
    readonly property color panelOverlayRaised: Qt.rgba(0.067, 0.082, 0.09, 0.30)
    readonly property var nav: [
        "PLAY", "CHAR", "EDIT", "MAP", "BAG", "SCENE", "PERF", "NET", "ASSETS", "UI"
    ]
    readonly property var terrainBrushFalloffs: [
        "SMOOTH", "LINEAR", "SHARP", "GAUSSIAN"
    ]

    // The 3D repeaters must receive a stable model identity. Replacing a JavaScript
    // array each frame makes QtQuick3D destroy and recreate every delegate,
    // which is visible as asset flicker and can briefly expose an empty scene.
    // Each list keeps one bounded row per render object and updates it by the
    // authoritative stable key.  A cell/NPC/item entering or leaving the view
    // must not tear down unrelated RuntimeLoader or pose delegates.
    ListModel {
        id: terrainRenderModel
        objectName: "gameEngineTerrainRenderModel"
    }
    ListModel {
        id: entityRenderModel
        objectName: "gameEngineEntityRenderModel"
    }

    readonly property var baseStatus: {
        try {
            return JSON.parse(root.statusJson || "{}")
        } catch (err) {
            return {}
        }
    }
    readonly property var uiStatus: {
        try {
            return JSON.parse(root.uiStatusJson || "{}")
        } catch (err) {
            return {}
        }
    }
    readonly property var status: {
        // Keep the full snapshot as the authoritative catalogue/document and
        // overlay only explicitly supplied top-level UI sections.  This is a
        // shallow transport merge: nested gameplay data is never invented or
        // reconstructed in QML.
        var merged = ({})
        var base = root.baseStatus || ({})
        var delta = root.uiStatus || ({})
        var baseKey
        for (baseKey in base)
            merged[baseKey] = base[baseKey]
        var deltaKey
        for (deltaKey in delta) {
            if (deltaKey !== "schema")
                merged[deltaKey] = delta[deltaKey]
        }
        return merged
    }
    property var retainedStatusCache: ({value: ({})})
    function retainRenderValue(value, previous) {
        if (value === previous) return previous
        if (value === null || previous === null || typeof value !== 'object'
                || typeof previous !== 'object') return value
        if (Array.isArray(value) !== Array.isArray(previous)) return value
        var keys=Object.keys(value),oldKeys=Object.keys(previous)
        var unchanged=keys.length === oldKeys.length
        for (var i=0;i<keys.length;++i) {
            var key=keys[i]
            value[key]=root.retainRenderValue(value[key],previous[key])
            if (value[key] !== previous[key] || !Object.prototype.hasOwnProperty.call(previous,key)) unchanged=false
        }
        return unchanged ? previous : value
    }
    readonly property var renderStatus: {
        try {
            var value=root.retainRenderValue(JSON.parse(root.renderStatusJson || "{}"),root.retainedStatusCache.value)
            root.retainedStatusCache.value=value
            return value
        } catch (err) {
            return {}
        }
    }
    readonly property var simulation: root.renderStatus.simulation
        || root.status.simulation || ({})
    readonly property var player: root.renderStatus.player
        || root.status.player || ({})
    readonly property var inputState: root.status.input || ({})
    readonly property var render: root.renderStatus.render
        || root.status.render || ({})
    readonly property var presentation: root.render.presentation || ({})
    readonly property var fallbackView: root.render.fallback
        || (root.status.render ? root.status.render.fallback : ({}))
    readonly property string presentationMode: String(
        root.presentation.mode || "RICH_3D"
    )
    readonly property string presentationReason: String(
        root.presentation.reason || "NONE"
    )
    readonly property bool dosFallbackActive: root.localGraphicsFailure
        || root.presentationMode === "DOS_2D"
    readonly property var network: root.status.network || ({})
    readonly property var replay: root.status.replay || ({})
    readonly property var chunks: root.status.chunks || ({})
    readonly property var world: root.status.world || ({})
    readonly property var worldStreaming: root.world.streaming || ({})
    readonly property var combat: {
        var merged=Object.assign({},root.status.combat || ({}),root.renderStatus.combat_live || ({}))
        return merged
    }
    readonly property var controller: root.status.controller || ({})
    readonly property var inventory: root.status.inventory || ({})
    readonly property var items: root.status.items || ({})
    readonly property var firearms: root.renderStatus.firearms || root.status.firearms || ({hands:[],shots:[]})
    readonly property var bank: root.status.bank || ({})
    readonly property var economy: root.status.economy || ({})
    readonly property var itemInteraction: root.items.interaction_target || ({})
    readonly property bool hasInteractableTarget:
        Boolean(root.natureTarget.available) || Boolean(root.npcInteraction.available)
        || Boolean(String(root.itemInteraction.instance_id || ""))
    readonly property var life: root.status.life || ({})
    readonly property var crafting: root.status.crafting || ({})
    readonly property var loot: root.status.loot || ({})
    readonly property var progression: root.status.progression || ({})
    readonly property var quests: root.status.quests || ({})
    readonly property var factions: root.status.factions || ({})
    readonly property var dialogue: root.status.dialogue || ({})
    readonly property var social: root.status.social || ({})
    readonly property var livingWorld: root.status.living_world || ({})
    readonly property var worldEvents: root.status.world_events || ({})
    readonly property var contentPacks: root.status.content_packs || ({})
    readonly property var editor: root.status.editor || ({})
    readonly property var cinematic: root.status.cinematic || ({})
    function skipOpeningCinematic() {
        if (root.surfaceHost && root.surfaceHost.gameEngineClientControl)
            root.applyRaw(root.surfaceHost.gameEngineClientControl(JSON.stringify({kind:"service",op:"CinematicStop"})))
    }
    Rectangle {
        visible: !!root.cinematic.active
        anchors.top: parent.top
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.topMargin: 64
        width: 330; height: 52; radius: 10; z: 2000
        color: "#e6182928"; border.color: "#b89750"
        Text { anchors.left: parent.left; anchors.leftMargin: 16; anchors.verticalCenter: parent.verticalCenter; text: "Introduktion"; color: "#eadca8" }
        GgButton { objectName: "gameCinematicSkip"; anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter; text: "Hoppa över"; onClicked: root.skipOpeningCinematic() }
    }
    readonly property var content: root.status.content || ({})
    // The stream contract, rather than a renderer-only constant, owns the
    // amount of world that the presentation must cover.  The render ring is
    // deliberately larger than gameplay interest: its outer cells are HLOD
    // only and do not expand physics, NPC navigation or network state.
    readonly property real streamInterestRadius: Math.max(
        0,
        root.number(
            root.worldStreaming.render_radius,
            root.number(root.worldStreaming.interest_radius, 3)
        )
    )
    readonly property real streamCoverageSize: Math.max(
        80,
        root.number(
            root.worldStreaming.render_coverage_diameter_m,
            (2 * root.streamInterestRadius + 1) * root.terrainCellSize
        )
    )
    // Diameter of the near sea disk. The horizon ring starts at half of this.
    readonly property real waterWaveSpanM: 560
    readonly property real planetRadiusM: Math.max(
        10000,
        root.number(root.world.planet ? root.world.planet.radius_m : 1000000, 1000000)
    )
    readonly property var ggAtmosphere: WorldAtmosphere.palette(
        String(root.player.biome || root.terrainSurface.biome || "FIRST_ISLAND"),
        Math.floor(root.number(root.player.time_s, 0) / 2) * 2,
        root.number((root.life.clock || {}).day_length_s, 120))
    readonly property var atmosphere: {
        var a=Object.assign({},root.ggAtmosphere)
        var light=root.originalWorldActive && root.engineWorld ? root.engineWorld.lighting : null
        if (light && light.source === "ORIGINAL_LIGHT_DBC") {
            function c(rgb) { return Qt.rgba(rgb[0],rgb[1],rgb[2],1) }
            a.sky=c(light.sky[0]);a.horizon=c(light.fog.color);a.cloud=c(light.cloud_colors[1])
            a.key=c(light.diffuse);a.fill=c(light.ambient);a.keyEnergy=1;a.fillEnergy=1
            a.night=light.sidn;a.glowStrength=light.glow;a.glowIntensity=light.glow
            a.fogNear=light.fog.near;a.fogFar=light.fog.far
        }
        return a
    }
    property color oceanHorizonColor: root.atmosphere.horizon
    Behavior on oceanHorizonColor { ColorAnimation { duration: 1600 } }
    readonly property real cameraDistanceScale:
        root.cinematic.preset === "ORBIT_WORLD_SCALE" ? 2.2 : 1.0
    readonly property real renderCameraX:
        root.originalWorldActive && root.importedCameraReady ? root.importedCameraSeat.x : root.number(root.player.x, 0)
        + Math.sin(root.cameraWorldYaw * Math.PI / 180)
            * Math.cos(root.orbitPitch * Math.PI / 180) * root.cameraDistance * root.cameraDistanceScale
    readonly property real renderCameraY:
        root.originalWorldActive && root.importedCameraReady ? root.importedCameraSeat.y : root.number(root.player.y, 0)
        + root.cameraPivotOffsetM
        - Math.sin(root.orbitPitch * Math.PI / 180)
            * root.cameraDistance * root.cameraDistanceScale
    readonly property real renderCameraZ:
        root.originalWorldActive && root.importedCameraReady ? root.importedCameraSeat.z : root.number(root.player.z, 0)
        + Math.cos(root.cameraWorldYaw * Math.PI / 180)
            * Math.cos(root.orbitPitch * Math.PI / 180) * root.cameraDistance * root.cameraDistanceScale
    readonly property real cameraAltitudeAboveSea: Math.max(
        0.75,
        root.planetRenderY(
            root.renderCameraX,
            root.renderCameraY,
            root.renderCameraZ
        ) - root.planetRenderY(
            root.renderCameraX,
            root.number(
                root.terrain.water ? root.terrain.water.sea_level_m : 0,
                0
            ),
            root.renderCameraZ
        )
    )
    readonly property real geometricHorizonM: Math.sqrt(Math.max(
        1,
        2 * root.planetRadiusM * root.cameraAltitudeAboveSea
            + root.cameraAltitudeAboveSea * root.cameraAltitudeAboveSea
    ))
    readonly property real distantIslandRangeM: Math.max(
        Math.sqrt(root.renderCameraX * root.renderCameraX
            + root.renderCameraZ * root.renderCameraZ) + 96,
        root.number(root.planetMap.bounds_m ? root.planetMap.bounds_m.max_x : 0, 0) * Math.SQRT2
    )
    readonly property real worldViewDistanceM: WorldAtmosphere.farClip(
        root.number((root.render.policy || {}).world_view_distance_m, 3200),
        root.geometricHorizonM, root.planetRadiusM)
    readonly property real renderFarClipM: WorldAtmosphere.coveredDistance(
        root.worldViewDistanceM, root.planetSurfaceAssetVisible,
        root.streamInterestRadius, root.terrainCellSize,
        root.cameraDistance * root.cameraDistanceScale)
    // Only lightweight light sprites use the outer 18%. Terrain fog and map
    // residency retain the ordinary distance; distant lights allocate no AI.
    readonly property real lightBeaconRangeM: root.renderFarClipM * 1.18
    readonly property real cameraClipFarM: root.lightBeaconRangeM * 1.04
    readonly property var distanceFog: WorldAtmosphere.fogRange(
        root.renderFarClipM, root.planetSurfaceAssetVisible,
        root.streamInterestRadius, root.terrainCellSize,
        root.cameraDistance * root.cameraDistanceScale, root.atmosphere.fogNear)
    readonly property var assets: root.status.assets || ({})
    readonly property var characterVisual: root.assets.character_visual || ({})
    readonly property var selectedAsset: root.assets.selected || ({})
    readonly property int assetInstanceBudget: Math.max(
        0,
        Math.floor(root.number(root.assets.instance_budget, 0))
    )
    readonly property var terrain: root.status.terrain || ({})
    readonly property var planetMap: root.terrain.planet || ({})
    readonly property string nearbyWorldPlace: {
        if (root.originalWorldActive) {
            var imported = root.player.engine_world || ({})
            return String(imported.subzone || imported.zone || "")
        }
        var list = root.planetMap.places || []
        var nearest = 220 * 220
        var name = ""
        for (var i = 0; i < list.length; ++i) {
            var dx = root.number(root.player.x, 0) - list[i].x
            var dz = root.number(root.player.z, 0) - list[i].z
            var distance = dx * dx + dz * dz
            if (distance < nearest) { nearest = distance; name = list[i].name }
        }
        return name
    }
    readonly property var navigation: root.status.navigation || ({})
    readonly property var terrainCells: root.terrain.cells || []
    readonly property var terrainSurface: root.uiStatus.terrain_surface
        || root.terrain.player_surface || ({})
    readonly property var terrainEditor: root.status.terrain_editor
        || root.terrain.authoring || ({})
    readonly property int terrainGeometryRevision: Math.max(
        0,
        Math.floor(root.number(root.terrainEditor.revision, 0))
    )
    readonly property real worldFeelScale: root.number(
        root.world.feel ? root.world.feel.scale : 1.85,
        1.85
    )
    readonly property real worldLayoutScale: root.number(
        root.world.feel ? root.world.feel.layout_scale : root.worldFeelScale, root.worldFeelScale)
    readonly property real worldPropScale: root.number(
        root.world.feel ? root.world.feel.prop_scale : root.worldFeelScale, root.worldFeelScale)
    readonly property bool largeEnvironment: root.number(
        root.world.feel ? root.world.feel.environment_revision : 1, 1) >= 2
    readonly property var fauna: root.renderStatus.fauna || root.status.fauna || ({})
    readonly property var ecology: root.renderStatus.ecology || root.status.ecology || ({})
    readonly property var nature: root.renderStatus.nature || root.status.nature || ({})
    readonly property var natureTarget: root.nature.target || ({})
    readonly property int natureRevision: Math.floor(root.number(root.nature.revision, 0))
    readonly property var naturePlants: ["sea_bell","sun_daisy","moon_orchid","red_poppy","blue_lupin","berry_bush","sage","broad_fern","aloe","cattail","amanita","chanterelle"]
    readonly property var natureAnimals: ["rabbit","squirrel","hedgehog","frog","lizard","crab","boar","fox","goat","sheep","sunfin","reef_perch","needlefish","lanternfish","puffer","turtle","octopus","gull","songbird","parrot","bee","butterfly"]
    property var natureBatchKeys: []
    property var floraBatchKeys: []
    function retainNearbyBatchKeys(previous, groups, limit) {
        var active = Object.keys(groups || ({})).filter(function(key) { return Number(groups[key]) > 0 })
        var kept = previous.filter(function(key) { return active.indexOf(key) >= 0 })
        var idle = previous.filter(function(key) { return active.indexOf(key) < 0 })
        kept = kept.concat(idle.slice(0, Math.max(0, limit - active.length)))
        for (var i=0; i<active.length; ++i)
            if (kept.indexOf(active[i]) < 0) kept.push(active[i])
        // Retain ordering and object identity on settled/moving frames. New
        // silhouettes are admitted only when their physical instances arrive.
        var ordered = previous.filter(function(key) { return kept.indexOf(key) >= 0 })
        for (var j=0; j<kept.length; ++j)
            if (ordered.indexOf(kept[j]) < 0) ordered.push(kept[j])
        return ordered.join("|") === previous.join("|") ? previous : ordered
    }
    onNatureRevisionChanged: natureBatchKeys = retainNearbyBatchKeys(natureBatchKeys, nature.groups, 192)
    onEcologyRevisionChanged: floraBatchKeys = retainNearbyBatchKeys(floraBatchKeys, ecology.groups, 320)
    readonly property var combatTarget: (root.renderStatus.targeting || root.status.targeting || ({})).selected || ({})
    readonly property int ecologyRevision: Math.floor(root.number(root.ecology.revision, 0))
    readonly property var floraSpecies: [
        "oak", "oak_arch", "pine", "jungle", "palm", "mangrove",
        "scrub", "fern", "grass", "flowers", "deadwood"
    ].concat(root.naturePlants)
    readonly property real sandoverIslandHalfExtent: 27.0 * root.worldLayoutScale
    readonly property var sandoverBakedAssetIds: [
        "gg-sandover-stilt-hut",
        "gg-sandover-roundhouse",
        "gg-sandover-longhouse",
        "gg-sandover-market-hut",
        "gg-sandover-palm",
        "gg-sandover-mangrove",
        "gg-sandover-windmill",
        "gg-sandover-cove-pier",
        "gg-sandover-waterwheel",
        "gg-sandover-tide-beacon"
    ]
    readonly property bool planetSurfaceAssetReady:
        planetSurfaceLoader.status === RuntimeLoader.Success
    readonly property bool planetSurfaceAssetVisible:
        root.planetSurfaceAssetReady
        && !root.dosFallbackActive
        && root.paneLive
        && root.terrainGeometryRevision === 0
    readonly property bool sandoverIslandTerrainReady:
        sandoverIslandTerrainLoader.status === RuntimeLoader.Success
    readonly property bool sandoverIslandEnvironmentReady:
        sandoverIslandEnvironmentLoader.status === RuntimeLoader.Success
    readonly property bool sandoverTerrainUsesNativeCells: {
        var authoring = root.terrain.authoring || ({})
        var cells = Array.isArray(authoring.cells) ? authoring.cells : []
        for (var index = 0; index < cells.length; ++index) {
            var cell = cells[index] || ({})
            var minX = root.number(cell.x, 10000) * root.terrainCellSize
            var minZ = root.number(cell.z, 10000) * root.terrainCellSize
            if (root.sandoverBoundsOverlapIsland(
                minX,
                minZ,
                minX + root.terrainCellSize,
                minZ + root.terrainCellSize
            ))
                return true
        }
        var brushes = Array.isArray(authoring.brushes) ? authoring.brushes : []
        for (var brushIndex = 0; brushIndex < brushes.length; ++brushIndex) {
            var brush = brushes[brushIndex] || ({})
            var brushX = root.number(brush.center_x_m, 10000)
            var brushZ = root.number(brush.center_z_m, 10000)
            var radius = Math.max(0, root.number(brush.radius_m, 0))
            if (root.sandoverBoundsOverlapIsland(
                brushX - radius,
                brushZ - radius,
                brushX + radius,
                brushZ + radius
            ))
                return true
        }
        return false
    }
    readonly property bool sandoverIslandTerrainVisible:
        root.sandoverIslandTerrainReady
        && !root.planetSurfaceAssetVisible
        && !root.sandoverTerrainUsesNativeCells
        && !root.dosFallbackActive
        && root.paneLive
    function sandoverBoundsOverlapIsland(minX, minZ, maxX, maxZ) {
        var extent = root.sandoverIslandHalfExtent
        return maxX > -extent && minX < extent
            && maxZ > -extent && minZ < extent
    }
    function sandoverTerrainCellCoveredByBlender(row) {
        if (!root.sandoverIslandTerrainVisible || !row)
            return false
        var bounds = row.bounds_m || ({})
        return root.sandoverBoundsOverlapIsland(
            root.number(bounds.min_x, 10000),
            root.number(bounds.min_z, 10000),
            root.number(bounds.max_x, -10000),
            root.number(bounds.max_z, -10000)
        )
    }
    function sandoverEntityBakedByEnvironment(assetId, kind, x, z) {
        if (!root.sandoverIslandEnvironmentReady
            || Math.abs(root.number(x, 10000)) > root.sandoverIslandHalfExtent
            || Math.abs(root.number(z, 10000)) > root.sandoverIslandHalfExtent)
            return false
        return root.sandoverBakedAssetIds.indexOf(String(assetId || "")) >= 0
            || String(kind || "").toUpperCase() === "ROCK"
    }
    readonly property var npc: root.status.npc || ({})
    readonly property var npcInteraction: root.npc.interaction || ({})
    readonly property var people: root.status.people || ({})
    readonly property var gear: root.status.gear || ({})
    readonly property var physics: root.status.physics || ({})
    readonly property var terrainTargetCell: root.terrainCellForKey(
        root.terrainTargetKey
    ) || ({})
    readonly property var events: root.status.events || []
    readonly property var eventJournal: root.status.event_journal || ({})
    readonly property var dos: root.status.dos || ({})
    readonly property var capabilities: root.status.capabilities || []
    readonly property var keyBindings: root.status.keybindings || ({})
    readonly property var addonState: root.status.addons || ({})
    property var retainedEntityRows: ({})
    property var retainedRenderRows: []
    readonly property var renderEntities: root.retainedRenderRows

    function runtimeLoaderHasVisualContent(loader) {
        // RuntimeLoader.Success means decoding completed, but the imported
        // scene is represented by child nodes.  Keep the one primitive
        // rectangle visible until at least one actual Model/geometry child
        // is present; this closes the small status-success/first-scene-frame
        // gap without inventing a second gameplay state.
        if (!loader || loader.status !== RuntimeLoader.Success)
            return false
        function hasVisual(node) {
            if (!node)
                return false
            var sourceValue = node.source
            if (sourceValue !== undefined && String(sourceValue) !== "")
                return node.visible !== false
            var geometryValue = node.geometry
            if (geometryValue !== undefined && geometryValue !== null)
                return node.visible !== false
            var nested = node.children || []
            for (var childIndex = 0; childIndex < nested.length; ++childIndex) {
                if (hasVisual(nested[childIndex]))
                    return true
            }
            return false
        }
        var children = loader.children || []
        for (var index = 0; index < children.length; ++index) {
            if (hasVisual(children[index]))
                return true
        }
        return false
    }
    function authoredClipForMotionState(value) {
        var state = String(value || "IDLE").toUpperCase()
        if (state === "WALK")
            return "Walk"
        if (state === "SPRINT")
            return "Sprint"
        if (state === "AIR")
            return "Air"
        if (state === "DOUBLE_JUMP")
            return "DoubleJump"
        if (state === "GRAPPLE")
            return "Grapple"
        if (state === "SWIM")
            return "Swim"
        if (state === "FLY")
            return "Fly"
        if (state === "HOVERBOARD")
            return "Board"
        if (state === "HOVERBOARD_AIR")
            return "BoardAir"
        if (state === "BOAT")
            return "Skiff"
        if (state === "SIT") return "Sit"
        if (state === "SLEEP") return "Sleep"
        if (state === "KNEEL") return "Kneel"
        return "Idle"
    }
    readonly property bool stress: root.renderStatus.stress !== undefined
        ? Boolean(root.renderStatus.stress) : Boolean(root.status.stress)
    readonly property bool running: String(
        root.renderStatus.state || root.status.state || ""
    ) === "RUNNING"
    readonly property bool recording: Boolean(root.replay.recording)
    readonly property bool replaying: Boolean(root.replay.replaying)
    readonly property string movementMode: String(
        root.player.movement_mode || root.inputState.movement_mode || "GROUND"
    )
    readonly property int renderUpdateHz: Math.max(
        1,
        Math.floor(root.number(
            root.render.update_hz,
            60
        ))
    )
    readonly property int renderUpdateIntervalMs: Math.max(
        16,
        Math.round(1000 / root.renderUpdateHz)
    )
    // Full status construction remains available for commands and initial
    // binding.  During movement the inspector samples an authoritative delta
    // at 2 Hz (1 Hz under stress), leaving the fixed-step/render paths alone.
    readonly property int statusUpdateIntervalMs: root.stress ? 750 : 500
    readonly property string legend: root.stress
        ? "LOCAL · FIXED 60 HZ · RENDER 60 HZ"
        : "LOCAL · FIXED 60 HZ · RENDER 60 HZ"

    function installFullStatus(raw, immediateRender) {
        if (raw === undefined || raw === null)
            return
        root.fullStatusApplyInProgress = true
        root.uiStatusJson = "{}"
        root.statusJson = String(raw)
        root.renderStatusJson = String(raw)
        root.fullStatusApplyInProgress = false
        root.fullStatusReady = true
        // Commands need an immediate visual response.  Periodic full UI
        // refreshes do not: the compact render stream will carry transforms
        // and structural changes on its next bounded tick.
        if (immediateRender || !root.renderStreamPrimed) {
            root.syncRenderModels(root.renderStatusJson)
            root.renderStreamPrimed = true
        }
    }

    function applyGameplay(raw) {
        var response
        try {response=JSON.parse(String(raw || '{}'))} catch(e) {return false}
        if (response.schema==='gg.game-engine.render-snapshot.v1') root.installRenderStatus(raw)
        else if (!response.error) root.applyRaw(raw)
        if (response.error) {
            var codes={FIREARM_NO_AMMO:"Rätt ammunition saknas i väskan.",
                FIREARM_RELOADING:"Vapnet laddas om.",FIREARM_COOLDOWN:"Vapnet är inte redo än.",
                FIREARM_LINE_OF_SIGHT_BLOCKED:"Målet är skymt.",FIREARM_TARGET_OUT_OF_RANGE:"Målet är för långt bort."}
            root.itemNotice=codes[response.error] || String(response.error);return false
        }
        return true
    }
    function useActionSlot(index) {
        if (root.surfaceHost && root.surfaceHost.gameEngineActionUse)
            root.applyGameplay(root.surfaceHost.gameEngineActionUse(index))
    }
    function editActionBar(edit) {
        if (root.surfaceHost && root.surfaceHost.gameEngineActionBarEdit)
            root.applyGameplay(root.surfaceHost.gameEngineActionBarEdit(JSON.stringify(edit)))
    }
    function moveActionDrag(kind,ref,source,x,y) {
        root.actionDrag={kind:kind,ref:ref,source:source};root.actionDragX=x;root.actionDragY=y
    }
    function cancelActionDrag() {root.actionDrag=({})}
    function finishActionDrag() {
        if (!root.actionBarWidget || !root.actionDrag.kind) {root.cancelActionDrag();return false}
        var index=root.actionBarWidget.dropIndex(root.actionDragX,root.actionDragY)
        if (index<0) {root.cancelActionDrag();return false}
        var edit=root.actionDrag.source>=0 ? {verb:'MOVE',source:root.actionDrag.source,index:index}
            : {index:index,kind:root.actionDrag.kind,ref:root.actionDrag.ref}
        root.editActionBar(edit);root.cancelActionDrag();return true
    }
    function inventoryActionDrag(row,x,y,panel,finish) {
        var point=root.mapFromItem(panel,x,y)
        if (row && ['INVENTORY','EQUIPPED'].indexOf(String(row.location))>=0)
            root.moveActionDrag('ITEM',String(row.definition_id),-1,point.x,point.y)
        if (!finish) return false
        return root.finishActionDrag()
    }
    function assetEdit(request) {
        if (!root.surfaceHost || !root.surfaceHost.gameEngineAssetEditor) {
            root.assetEditorError = "Starta om GG AI Desktop för att läsa in assetredigeraren."
            return ({ok:false})
        }
        try {
            var response=JSON.parse(root.surfaceHost.gameEngineAssetEditor(root,null,JSON.stringify(request)))
            root.assetEditorError=response.ok ? "" : String(response.error || "Redigeringen misslyckades.")
            if (!response.ok || response.preview) return response
            var nextState=Object.assign({},response)
            delete nextState.snapshot
            root.assetEditorState=Object.assign({},root.assetEditorState,nextState)
            root.assetEditorRevision=Number(response.revision || 0)
            if (response.snapshot) root.installFullStatus(JSON.stringify(response.snapshot),true)
            return response
        } catch(error) {
            root.assetEditorError=String(error)
            return ({ok:false})
        }
    }
    function assetIdentity(entityId) {
        var rows=root.assetEditorState.scene || []
        for(var i=0;i<rows.length;i++) if(rows[i].id===entityId) return String(rows[i].identity)
        return String(entityId || "")
    }
    function applyAssetMaterial(loader,entityId) {
        if (!loader || !root.surfaceHost || !root.surfaceHost.gameEngineAssetEditor) return
        if(loader.status!==RuntimeLoader.Success)return
        var raw=root.surfaceHost.gameEngineAssetEditor(root,loader,JSON.stringify({op:"APPLY_MATERIAL",identity:root.assetIdentity(entityId)}))
        try {
            var result=JSON.parse(raw)
            if(!result.ok){root.assetEditorError=result.error;return}
            var settings=result.materials || [], ordinal=0,seen=[]
            var changed=settings.some(function(row){return Object.keys(row.values || {}).length>0})
            var cached=root.assetMaterialRecords.some(function(row){return row.loader===loader})
            if(!changed && !cached)return
            function visit(node) {
                var materials=node.materials || []
                for(var i=0;i<materials.length;i++) {
                    var material=materials[i];if(seen.indexOf(material)>=0)continue;seen.push(material)
                    var index=ordinal++
                    var values=({})
                    var matched=settings.filter(function(row){return row.name===String(material.objectName || "")})[0]
                    if(!matched)matched=settings.filter(function(row){return row.ordinal===index})[0]
                    if(matched)values=matched.values || ({})
                    var record=root.assetMaterialRecords.filter(function(row){return row.material===material && row.loader===loader})[0]
                    if(!record) {
                        record={loader:loader,material:material,color:material.baseColor,roughness:material.roughness,metalness:material.metalness,map:material.baseColorMap,texture:null}
                        if(record.map)record.uv={positionU:record.map.positionU,positionV:record.map.positionV,scaleU:record.map.scaleU,scaleV:record.map.scaleV}
                        root.assetMaterialRecords=root.assetMaterialRecords.concat([record])
                    }
                    material.baseColor=values.color!==undefined ? values.color : record.color
                    material.roughness=values.roughness!==undefined ? values.roughness : record.roughness
                    material.metalness=values.metalness!==undefined ? values.metalness : record.metalness
                    material.baseColorMap=record.map
                    if(values.image) {
                        if(!record.texture) {
                            record.texture=Qt.createQmlObject('import QtQuick3D; Texture {}',material,"assetPaintTexture")
                            if(record.map){record.texture.flipV=record.map.flipV;record.texture.indexUV=record.map.indexUV
                                record.texture.tilingModeHorizontal=record.map.tilingModeHorizontal;record.texture.tilingModeVertical=record.map.tilingModeVertical}
                        }
                        record.texture.source=values.image;material.baseColorMap=record.texture
                    }
                    var texture=material.baseColorMap
                    if(texture){var props=["positionU","positionV","scaleU","scaleV"]
                        for(var p=0;p<props.length;p++){var key=props[p];texture[key]=values[key]!==undefined ? values[key] : record.uv ? record.uv[key] : key.indexOf("scale")===0 ? 1 : 0}}
                }
                var children=node.children || [];for(var j=0;j<children.length;j++){
                    if(children[j].materials!==undefined || children[j].position!==undefined)visit(children[j])
                }
            }
            visit(loader)
        } catch(error) {root.assetEditorError=String(error)}
    }
    function forgetAssetMaterials(loader) {
        root.assetMaterialRecords=root.assetMaterialRecords.filter(function(row){return row.loader!==loader})
    }
    function assetPick(x,y) {
        var hit=view3d.pick(x,y),node=hit.objectHit
        if (!node) return ""
        if(node.treeKey!==undefined) {
            var kind=String(node.objectName).indexOf("WorldTree")>=0 ? "TREE" : String(node.objectName).indexOf("GroundCover")>=0 ? "COVER" : "PLACE"
            var picked=root.assetEdit({op:"PICK_BATCH",batchKind:kind,batchKey:String(node.treeKey),index:Number(hit.instanceIndex)})
            return picked && picked.selected ? String(picked.selected.identity || "") : ""
        }
        if (node.batchKey!==undefined && root.surfaceHost.gameEngineInstanceIdentity)
            return root.surfaceHost.gameEngineInstanceIdentity(String(node.batchKey),Number(hit.instanceIndex),Boolean(node.isNatureBatch))
        for(var i=0;node && i<40;i++,node=node.parent) {
            if (node.worldEntityId!==undefined) return root.assetIdentity(String(node.worldEntityId))
            if (String(node.objectName || "").indexOf("ggPick:")===0 && String(node.objectName).length>7)
                return String(node.objectName).substring(7)
        }
        return ""
    }
    onAssetEditorModeChanged: {
        if (root.assetEditorMode) {
            root.pauseRuntime()
            root.inspectorCollapsed=false
            root.assetEdit({op:"OPEN"})
        } else {root.assetDrag=({})}
    }
    function worldPick(x,y) {
        if (!root.surfaceHost || !root.surfaceHost.gameEngineWorldHover) return ({})
        var hit=view3d.pick(x,y),node=hit.objectHit,identity=''
        if (!node) return ({})
        if (node.batchKey!==undefined && root.surfaceHost.gameEngineInstanceIdentity)
            identity=root.surfaceHost.gameEngineInstanceIdentity(String(node.batchKey),Number(hit.instanceIndex),Boolean(node.isNatureBatch))
        else if (String(node.objectName || '').indexOf('ggPick:')===0) identity=String(node.objectName).substring(7)
        else {
            for (var i=0;node && i<32;i++,node=node.parent) {
                if (node.worldEntityId!==undefined && root.surfaceHost.gameEngineEntityIdentity) {
                    identity=root.surfaceHost.gameEngineEntityIdentity(String(node.worldEntityId));break
                }
            }
        }
        if (identity && root.surfaceHost.gameEngineEntityIdentity && ['e-','item-'].some(function(prefix) {return identity.indexOf(prefix)===0}))
            identity=root.surfaceHost.gameEngineEntityIdentity(identity)
        if (!identity) return ({})
        try {return JSON.parse(root.surfaceHost.gameEngineWorldHover(identity))} catch(e) {return ({})}
    }
    function worldPointToScreen(x,y,z) {
        return view3d.mapFrom3DScene(Qt.vector3d(x,root.planetRenderY(x,y,z),z))
    }
    function nameplateProjection(x,y,z) {
        var point=root.worldPointToScreen(x,y,z)
        if(!isFinite(point.x) || !isFinite(point.y) || point.z<=0 || point.x<0 || point.y<0 || point.x>view3d.width || point.y>view3d.height)
            return ({visible:false,reason:"frustum",point:[point.x,point.y,point.z],viewport:[view3d.width,view3d.height],eye:[camera.scenePosition.x,camera.scenePosition.y,camera.scenePosition.z],angles:[camera.eulerRotation.x,camera.eulerRotation.y,camera.eulerRotation.z],anchor:[x,root.planetRenderY(x,y,z),z]})
        var anchor=Qt.vector3d(x,root.planetRenderY(x,y,z),z)
        var eye=camera.scenePosition
        var dx=anchor.x-eye.x,dy=anchor.y-eye.y,dz=anchor.z-eye.z
        var distance=Math.sqrt(dx*dx+dy*dy+dz*dz)
        if(distance<=0.01) return ({visible:false,reason:"camera"})
        var hit=view3d.rayPick(eye,Qt.vector3d(dx/distance,dy/distance,dz/distance))
        if(hit.objectHit && hit.distance<distance-0.35) return ({visible:false,reason:"occluded",hit:hit.objectHit.objectName,distance:distance,hitDistance:hit.distance})
        var local=root.mapFromItem(view3d,point.x,point.y)
        return ({visible:true,x:local.x,y:local.y})
    }
    function setRenderCountersEnabled(enabled) {
        view3d.renderStats.extendedDataCollectionEnabled=enabled
    }
    function setWorldRenderMode(underlay) {
        view3d.renderMode=underlay ? View3D.Underlay : View3D.Offscreen
    }
    function updateWorldHover(x,y,force) {
        var point=cameraMouse.mapToItem(root,x,y)
        root.worldMouseX=point.x;root.worldMouseY=point.y
        var now=Date.now()
        if (!force && now-root.lastHoverAt<16) return
        root.lastHoverAt=now;root.worldHoverInfo=root.worldPick(x,y)
    }
    function selectWorld(identity) {
        if (root.surfaceHost && root.surfaceHost.gameEngineWorldSelect)
            root.applyGameplay(root.surfaceHost.gameEngineWorldSelect(String(identity || '')))
    }
    function contextWorld(identity) {
        if (root.surfaceHost && root.surfaceHost.gameEngineWorldContext)
            root.applyGameplay(root.surfaceHost.gameEngineWorldContext(String(identity || '')))
    }

    function applyRaw(raw) {
        root.installFullStatus(raw, true)
        try {
            var response = JSON.parse(String(raw || "{}"))
            var code = String(response.error || "")
            var errors = {
                "ITEM_INVENTORY_FULL": "Väskan är full.",
                "ACCOUNT_STASH_FULL": "Kistan är full.",
                "ACCOUNT_STASH_OUT_OF_REACH": "Gå närmare den öppnade kistan.",
                "ACCOUNT_STASH_INVENTORY_ITEM_REQUIRED": "Välj ett föremål i väskan.",
                "ACCOUNT_STASH_ITEM_MISSING": "Föremålet finns inte längre i kistan.",
                "ITEM_CONTAINER_TARGET_REQUIRED": "Ingen kista inom räckhåll.",
                "FIREARM_NO_AMMO": "Rätt ammunition saknas i väskan.",
                "FIREARM_MAGAZINE_FULL": "Magasinet är fullt.",
                "FIREARM_RELOADING": "Vapnet laddas om.",
                "FIREARM_COOLDOWN": "Vapnet är inte redo att skjuta än.",
                "FIREARM_LINE_OF_SIGHT_BLOCKED": "Målet är skymt.",
                "FIREARM_TARGET_OUT_OF_RANGE": "Målet är för långt bort.",
                "AMMO_WORKBENCH_OUT_OF_REACH": "Gå närmare arbetsbänken för att tillverka ammunition."
            }
            if (code)
                root.itemNotice = errors[code] || WorldFx.scrollError(code)
            else {
                if (response.gear_craft_result && response.gear_craft_result.action === "CRAFT_ENCHANT_SCROLL")
                    root.itemNotice = "Scroll skapad: " + String(response.gear_craft_result.name || "")
                else if (response.gear_result && response.gear_result.action === "ENCHANT")
                    root.itemNotice = "Enchant applicerad: " + String(response.gear_result.enchantment.name || "")
                var result = response.item_result || ({})
                var labels = {
                    "OPEN": "Kistan är öppen.",
                    "LOOT": "Kistan plundrad.",
                    "BANK_DEPOSIT": "Föremålet ligger i den gemensamma kistan.",
                    "BANK_WITHDRAW": "Föremålet ligger i väskan.",
                    "UNEQUIP": "Utrustningen ligger i väskan.",
                    "EQUIP": "Föremålet är utrustat.",
                    "PICKUP": "Föremålet ligger i väskan.",
                    "DROP": "Föremålet ligger på marken."
                }
                if (result.action && labels[String(result.action)])
                    root.itemNotice = labels[String(result.action)]
            }
        } catch (err) {
            // installFullStatus owns malformed response reporting.
        }
    }

    function applyItemAction(raw) {
        root.applyRaw(raw)
        try {
            return !Boolean(JSON.parse(String(raw || "{}")).error)
        } catch (err) {
            return false
        }
    }

    function renderSignature(value, roleName) {
        if (!value)
            return "NULL"
        if (roleName === "terrainRow") {
            var authoring = value.authoring || ({})
            return [
                value.key,
                value.lod,
                value.visibility ? value.visibility.render : true,
                authoring.overridden,
                authoring.brush_count,
                authoring.height_delta_m,
                authoring.biome,
                authoring.water_mode
            ].join("|")
        }
        if (roleName === "entityRow") {
            // Static bindings (assets, equipment and entity kind) are kept in
            // the delegate's entityRow role.  Positions and poses travel in
            // entityDynamic so a moving NPC does not cause RuntimeLoader,
            // materials or nested equipment repeaters to reevaluate.
            var staticAsset = value.asset || ({})
            var staticItem = value.item || ({})
            var staticItemAsset = staticItem.asset || ({})
            var staticEquipment = value.equipment || []
            var equipmentKeys = ""
            for (var equipmentIndex = 0;
                 equipmentIndex < staticEquipment.length;
                 ++equipmentIndex) {
                var equipped = staticEquipment[equipmentIndex] || ({})
                equipmentKeys += String(equipped.instance_id || "")
                    + ":" + String(equipped.equipped_slot || "")
                    + ":" + String(equipped.visual_stowed) + ":" + String(equipped.visual_visible)
                    + ":" + JSON.stringify(equipped.attachment || {}) + ";"
            }
            return [
                value.id,
                value.kind,
                value.sx,
                value.sy,
                value.sz,
                value.color,
                staticAsset.id,
                staticAsset.mode,
                staticAsset.source,
                staticAsset.root_offset_m,
                staticAsset.instance_rank,
                staticAsset.instance_budget,
                staticItem.instance_id,
                staticItem.location,
                staticItemAsset.mode,
                staticItemAsset.source,
                equipmentKeys
            ].join("|")
        }
        var animation = value.animation || ({})
        var asset = value.asset || ({})
        var item = value.item || ({})
        var itemAsset = item.asset || ({})
        var itemVisual = item.visual || ({})
        return [
            value.id,
            value.kind,
            value.x,
            value.y,
            value.z,
            value.yaw,
            value.sx,
            value.sy,
            value.sz,
            value.lod,
            value.speed,
            value.motion_state,
            animation.state,
            animation.phase,
            animation.bob_m,
            animation.lean_deg,
            animation.sway_deg,
            animation.squash,
            asset.mode,
            asset.source,
            asset.instance_rank,
            asset.root_offset_m,
            item.instance_id,
            item.location,
            itemAsset.mode,
            itemVisual.bob_m,
            itemVisual.rotation_y
        ].join("|")
    }

    function renderDynamicSignature(value) {
        if (!value)
            return "NULL"
        var animation = value.animation || ({})
        var asset = value.asset || ({})
        var item = value.item || ({})
        var visual = item.visual || ({})
        if (root.surfaceHost && root.surfaceHost.gameEngineRegisterEntityNode) {
            // Native scene handles carry position/rotation every frame. Only
            // locomotion/visibility changes rebind imported rig metadata.
            return [value.id,value.vehicle,value.hidden,value.motion_state,
                    animation.state,animation.action_serial,asset.clip,asset.runtime_clip,
                    Math.round(root.number(animation.cadence_hz,0)*8)].join('|')
        }
        return [
            value.id,
            value.x,
            value.y,
            value.z,
            value.yaw,
            value.pitch,
            value.roll,
            value.speed,
            value.vehicle,
            value.hidden,
            value.lod,
            value.motion_state,
            animation.state,
            animation.action_serial,
            animation.phase,
            animation.bob_m,
            animation.lean_deg,
            animation.sway_deg,
            animation.squash,
            asset.clip,
            asset.clip_status,
            asset.runtime_clip,
            visual.bob_m,
            visual.rotation_y
        ].join("|")
    }

    function renderDynamicValue(value) {
        if (!value)
            return ({})
        return {
            id: value.id,
            x: value.x,
            y: value.y,
            z: value.z,
            yaw: value.yaw,
            pitch: value.pitch,
            roll: value.roll,
            speed: value.speed,
            vehicle: value.vehicle,
            hidden: value.hidden,
            lod: value.lod,
            motion_state: value.motion_state,
            animation: value.animation || ({}),
            asset: value.asset || ({}),
            item: value.item || ({})
        }
    }

    function rebuildRenderModelIndex(model, roleName) {
        var map = ({})
        for (var index = 0; index < model.count; ++index)
            map[String(model.get(index).renderKey)] = index
        root.renderModelIndex[roleName] = map
    }

    function syncRenderModel(model, rows, roleName, residentIds) {
        if (!Array.isArray(rows))
            return
        var indexByKey = root.renderModelIndex[roleName]
        if (!indexByKey)
            indexByKey = ({})
        var keyCount = 0
        var mappedKey
        for (mappedKey in indexByKey)
            keyCount += 1
        if (keyCount !== model.count) {
            root.rebuildRenderModelIndex(model, roleName)
            indexByKey = root.renderModelIndex[roleName]
        }
        var nextKeys = ({})
        if (Array.isArray(residentIds)) {
            for (var residentIndex = 0; residentIndex < residentIds.length; ++residentIndex)
                nextKeys[roleName + '::' + residentIds[residentIndex]] = true
        }
        var structural = false
        for (var rowIndex = 0; rowIndex < rows.length; ++rowIndex) {
            var value = rows[rowIndex]
            var sourceKey = value && (value.id !== undefined
                ? value.id
                : (value.key !== undefined ? value.key : rowIndex))
            var stableKey = roleName + "::" + String(sourceKey)
            var signature = root.renderSignature(value, roleName)
            var dynamicSignature = roleName === "entityRow"
                ? root.renderDynamicSignature(value) : ""
            nextKeys[stableKey] = true
            var existingIndex = indexByKey[stableKey]
            if (existingIndex === undefined || existingIndex === null)
                existingIndex = -1
            if (existingIndex < 0) {
                var row = {
                    "renderKey": stableKey,
                    "renderSignature": signature
                }
                // Nested maps become nested ListModels on append while
                // setProperty receives QVariantMap. Typed JSON roles retain
                // stable delegates without recursive QObject reconstruction.
                row[roleName + "Json"] = JSON.stringify(value)
                if (roleName === "entityRow") {
                    row.entityDynamicJson = JSON.stringify(root.renderDynamicValue(value))
                    row.renderDynamicSignature = dynamicSignature
                }
                model.append(row)
                structural = true
            } else {
                var current = model.get(existingIndex)
                if (String(current.renderSignature) !== signature) {
                    model.setProperty(existingIndex, roleName + "Json", JSON.stringify(value))
                    model.setProperty(existingIndex, "renderSignature", signature)
                }
                if (roleName === "entityRow"
                    && String(current.renderDynamicSignature) !== dynamicSignature) {
                    model.setProperty(
                        existingIndex,
                        "entityDynamicJson",
                        JSON.stringify(root.renderDynamicValue(value))
                    )
                    model.setProperty(
                        existingIndex,
                        "renderDynamicSignature",
                        dynamicSignature
                    )
                }
            }
        }
        for (var removeIndex = model.count - 1; removeIndex >= 0; --removeIndex) {
            if (!nextKeys[String(model.get(removeIndex).renderKey)]) {
                model.remove(removeIndex)
                structural = true
            }
        }
        if (structural)
            root.rebuildRenderModelIndex(model, roleName)
    }

    function denseTerrainCells(cells) {
        // Play draws the nearby heightfield only. ORBIT is one sea/horizon
        // plane, not a QQuick3D node per 16 m cell out to 336 m.
        if (!Array.isArray(cells))
            return []
        var dense = []
        for (var index = 0; index < cells.length; ++index) {
            var cell = cells[index] || ({})
            var geometry = cell.geometry || ({})
            if (root.number(geometry.vertex_grid, 1) > 1)
                dense.push(cell)
        }
        return dense
    }

    function syncTerrainModel(raw) {
        var snapshot = root.status
        if (raw !== undefined && raw !== null) {
            try {
                snapshot = JSON.parse(String(raw))
            } catch (err) {
                snapshot = {}
            }
        }
        var terrainView = snapshot.terrain || ({})
        if (Array.isArray(terrainView.cells))
            root.syncRenderModel(
                terrainRenderModel,
                root.denseTerrainCells(terrainView.cells),
                "terrainRow"
            )
    }

    function syncRenderModels(raw) {
        // A QML change handler can run before dependent readonly properties
        // have re-evaluated. Parse the changed value directly so PLAY never
        // observes a one-frame empty render list. The 60 Hz path passes the
        // already-parsed renderStatus object so PLAY does not JSON.parse twice.
        var snapshot = root.status
        if (raw !== undefined && raw !== null && typeof raw === "object")
            snapshot = raw
        else if (raw !== undefined && raw !== null) {
            try {
                snapshot = JSON.parse(String(raw))
            } catch (err) {
                snapshot = {}
            }
        }
        root.syncClientCamera(snapshot)
        var renderView = snapshot.render || ({})
        var terrainView = snapshot.terrain || ({})
        // Compact render snapshots intentionally omit terrain cells; the full
        // status stream owns that static geometry and updates it only when the
        // terrain document/cell interest set actually changes.
        if (Array.isArray(terrainView.cells)) {
            root.syncRenderModel(
                terrainRenderModel,
                root.denseTerrainCells(terrainView.cells),
                "terrainRow"
            )
        }
        var delta = Array.isArray(renderView.entities_delta)
        var entityRows = delta ? renderView.entities_delta
            : (Array.isArray(renderView.entities) ? renderView.entities : [])
        var residentIds = delta ? renderView.entity_ids : undefined
        root.syncRenderModel(entityRenderModel, entityRows, 'entityRow', residentIds)
        if (entityRows.length || !delta || root.retainedRenderRows.length !== residentIds.length) {
            var retained = delta ? root.retainedEntityRows : ({})
            for (var entityIndex=0; entityIndex<entityRows.length; ++entityIndex)
                retained[entityRows[entityIndex].id] = entityRows[entityIndex]
            var retainedRows=[]
            if (delta) {
                for (var idIndex=0; idIndex<residentIds.length; ++idIndex)
                    if (retained[residentIds[idIndex]]) retainedRows.push(retained[residentIds[idIndex]])
            } else retainedRows=entityRows
            root.retainedEntityRows=({})
            for (var retainIndex=0; retainIndex<retainedRows.length; ++retainIndex)
                root.retainedEntityRows[retainedRows[retainIndex].id]=retainedRows[retainIndex]
            root.retainedRenderRows=retainedRows
        }
        root.lastVisualSnapshot=snapshot
        root.lastVisualRenderView=renderView
        root.refreshVisualEffects()
    }

    function refreshVisualEffects() {
        var snapshot=root.lastVisualSnapshot,renderView=root.lastVisualRenderView
        if (!snapshot.player) return
        var particleRows = Array.isArray(renderView.particles)
            ? renderView.particles.slice() : []
        var visualFx = WorldFx.rows(
            snapshot.player || ({}),
            root.items.equipment || [],
            root.fxPreviewStyle,
            root.worldFeelScale,
            snapshot.fauna || root.fauna,
            root.equipmentFxPoints()
        )
        var fxNow=Date.now()
        if (root.surfaceHost && fxNow-root.lastWorldFxAnchorUpdate >= 250) {
            root.lastWorldFxAnchorUpdate=fxNow
            if (typeof root.surfaceHost.gameEngineWorldFxAnchors === "function")
                root.worldFxAnchors = root.surfaceHost.gameEngineWorldFxAnchors(
                    root.number(snapshot.player.x, 0), root.number(snapshot.player.z, 0))
            if (typeof root.surfaceHost.gameEngineEnvironmentFxAnchors === "function")
                root.worldAmbientAnchors = root.surfaceHost.gameEngineEnvironmentFxAnchors(
                    root.number(snapshot.player.x, 0), root.number(snapshot.player.z, 0))
            if (typeof root.surfaceHost.gameEngineLightBeacons === "function")
                root.worldLightBeacons=root.surfaceHost.gameEngineLightBeacons(root.lightBeaconRangeM)
        }
        WorldFx.emitLamps(visualFx, root.worldFxAnchors,
            root.number(snapshot.player.time_s, 0), root.atmosphere.night)
        WorldFx.emitGunfire(visualFx,(snapshot.firearms || root.firearms).shots || [],
            root.number(snapshot.player.time_s,0),root.equipmentFxPoints())
        WorldFx.emitEnvironment(visualFx, root.worldAmbientAnchors,
            root.number(snapshot.player.time_s, 0), root.atmosphere)
        var particleLimit=Math.max(0,root.number(
            (root.render.policy || {}).max_visible_particles,256))
        particleRows=particleRows.slice(0,particleLimit)
        for (var fxIndex = 0; fxIndex < visualFx.length
            && particleRows.length < particleLimit; ++fxIndex)
            particleRows.push(visualFx[fxIndex])
        var lightCamera={x:root.renderCameraX,y:root.renderCameraY,z:root.renderCameraZ}
        var sources=WorldFx.lightSources(particleRows,root.worldFxAnchors,
            lightCamera,root.atmosphere.night)
        for (var lightIndex=0;lightIndex<sources.length;++lightIndex) {
            var light=sources[lightIndex],lightItem=root.equipmentFxNodes[light.attachment_slot]
            if (!lightItem) continue
            var lightLocal=lightItem.fxMesh().mapPositionFromScene(Qt.vector3d(light.x,
                root.planetRenderY(light.x,light.y,light.z),light.z))
            light.attachment_point=[lightLocal.x,lightLocal.y,lightLocal.z]
        }
        root.localLightSources=WorldFx.nearbyLights(sources,
            root.number((root.render.policy || {}).max_dynamic_lights,6))
        var beacons=[]
        WorldFx.emitLightBeacons(beacons,sources,root.worldLightBeacons,lightCamera,
            root.lightBeaconRangeM,root.atmosphere.night,
            root.number((root.render.policy || {}).max_light_beacons,24))
        // Dense nearby sparks cannot consume every distant signal slot.
        particleRows=particleRows.slice(0,Math.max(0,particleLimit-beacons.length))
        for (var b=0;b<beacons.length && particleRows.length<particleLimit;++b)
            particleRows.push(beacons[b])
        var alphaRows = [], additiveRows = []
        for (var particleIndex = 0; particleIndex < particleRows.length; ++particleIndex) {
            var fx = Object.assign({}, particleRows[particleIndex])
            fx.y = root.planetRenderY(fx.x, fx.y, fx.z)
            if (fx.ex !== undefined) fx.ey = root.planetRenderY(fx.ex, fx.ey, fx.ez)
            if (fx.kind === "ENCHANT") {
                var yaw = root.cameraWorldYaw * Math.PI / 180
                var pitch = root.orbitPitch * Math.PI / 180
                fx.rx=Math.cos(yaw); fx.ry=0; fx.rz=-Math.sin(yaw)
                fx.ux=Math.sin(yaw)*Math.sin(pitch); fx.uy=Math.cos(pitch)
                fx.uz=Math.cos(yaw)*Math.sin(pitch)
                root.attachEnchantmentParticle(fx)
            }
            if (WorldFx.isAdditive(fx)) additiveRows.push(fx)
            else alphaRows.push(fx)
        }
        root.particleBatchCount = alphaRows.length
        root.additiveParticleCount = additiveRows.length
        if (root.surfaceHost) {
            if (!root.particleBatchGeometry
                && typeof root.surfaceHost.gameEngineParticleGeometry
                    === "function") {
                root.particleBatchGeometry =
                    root.surfaceHost.gameEngineParticleGeometry()
            }
            if (typeof root.surfaceHost.gameEngineParticleUpdate === "function")
                root.surfaceHost.gameEngineParticleUpdate(alphaRows)
            if (typeof root.surfaceHost.gameEngineAdditiveParticleGeometry === "function") {
                if (!root.additiveParticleGeometry)
                    root.additiveParticleGeometry = root.surfaceHost.gameEngineAdditiveParticleGeometry()
                root.surfaceHost.gameEngineAdditiveParticleUpdate(additiveRows)
            }
        }
    }

    onStatusJsonChanged: {
        if (root.fullStatusApplyInProgress)
            root.syncTerrainModel(root.statusJson)
        else {
            root.fullStatusReady = true
            root.syncRenderModels(root.statusJson)
            root.renderStreamPrimed = true
        }
        if (root.dosFallbackActive && dosFallbackCanvas)
            dosFallbackCanvas.requestPaint()
    }

    function equipmentFxPoints() {
        var points = ({})
        var playerY = root.number(root.player.y,0)
        var curve = playerY-root.planetRenderY(root.number(root.player.x,0),playerY,root.number(root.player.z,0))
        for (var slot in root.equipmentFxNodes) {
            var item = root.equipmentFxNodes[slot]
            if (!item) continue
            var frame = item.enchantFrame()
            function uncurve(p) { return {x:p.x,y:p.y+curve,z:p.z} }
            // Flail paths share endpoint objects. Copy them before converting
            // coordinates, otherwise their curvature correction runs twice.
            frame.base=uncurve(frame.base)
            frame.tip=uncurve(frame.tip)
            if (frame.path) frame.path=frame.path.map(uncurve)
            if (frame.muzzles) {
                for (var m=0;m<frame.muzzles.length;++m) frame.muzzles[m].y+=curve
            }
            if (frame.magic && frame.magic.point) frame.magic.point.y+=curve
            points[slot] = frame
        }
        return points
    }

    function attachEnchantmentParticle(fx) {
        var item=root.equipmentFxNodes[fx.attachment_slot]
        if (!item || fx.attachment_index===undefined) return
        var mesh=item.fxMesh(),world=Qt.vector3d(fx.x,fx.y,fx.z)
        var local=mesh.mapPositionFromScene(world)
        var right=mesh.mapPositionFromScene(Qt.vector3d(world.x+fx.rx,world.y+fx.ry,world.z+fx.rz))
        var up=mesh.mapPositionFromScene(Qt.vector3d(world.x+fx.ux,world.y+fx.uy,world.z+fx.uz))
        fx.attachment_bounds=[world.x,world.y,world.z]
        fx.x=local.x;fx.y=local.y;fx.z=local.z
        fx.rx=right.x-local.x;fx.ry=right.y-local.y;fx.rz=right.z-local.z
        fx.ux=up.x-local.x;fx.uy=up.y-local.y;fx.uz=up.z-local.z
        fx.attachment_local=true
        if (fx.attachment_index===0) root.enchantMesh0=mesh
        else root.enchantMesh1=mesh
    }

    function attachedLightPosition(source) {
        var mesh=source.attachment_index===0 ? root.enchantMesh0 : root.enchantMesh1
        if (source.attachment_point && mesh) {
            // Explicit dependency on the animated scene transform.
            var transform=mesh.sceneTransform
            var p=source.attachment_point
            return mesh.mapPositionToScene(Qt.vector3d(p[0],p[1],p[2]))
        }
        return Qt.vector3d(root.number(source.x,0),
            root.planetRenderY(root.number(source.x,0),root.number(source.y,0),root.number(source.z,0)),
            root.number(source.z,0))
    }

    onRenderStatusJsonChanged: {
        if (!root.fullStatusApplyInProgress && !root.applyingRenderStatus) {
            root.syncRenderModels(root.renderStatusJson)
            root.renderStreamPrimed = true
        }
        if (root.dosFallbackActive && dosFallbackCanvas)
            dosFallbackCanvas.requestPaint()
    }

    onUiStatusJsonChanged: {
        root.syncClientCamera(root.uiStatus)
        // UI deltas deliberately do not touch any 3D repeater model.  The
        // DOS view reads the same merged status and may repaint cheaply.
        if (root.dosFallbackActive && dosFallbackCanvas)
            dosFallbackCanvas.requestPaint()
    }

    onDosFallbackActiveChanged: {
        if (dosFallbackCanvas)
            dosFallbackCanvas.requestPaint()
    }

    function refresh() {
        if (!root.surfaceHost)
            return
        if (!root.fullStatusReady || !root.surfaceHost.gameEngineUiStatus) {
            if (root.surfaceHost.gameEngineStatus)
                root.installFullStatus(root.surfaceHost.gameEngineStatus(), false)
            return
        }
        var raw = root.surfaceHost.gameEngineUiStatus()
        if (raw !== undefined && raw !== null)
            root.uiStatusJson = String(raw)
    }

    function refreshRender() {
        if (root.surfaceHost && root.surfaceHost.gameEngineRenderStatus) {
            if (root.surfaceHost.gameEngineSetView)
                root.surfaceHost.gameEngineSetView(JSON.stringify({
                    x:root.renderCameraX,
                    y:root.planetRenderY(root.renderCameraX,root.renderCameraY,root.renderCameraZ),
                    z:root.renderCameraZ,heading:root.cameraHeading,pitch:root.orbitPitch,
                    fov:45,aspect:view3d.width/Math.max(1,view3d.height),far:root.renderFarClipM
                }))
            // Loading a saved character may replace the Qt world owner while
            // retaining this pane. Bind the live owner before publishing its
            // coordinates and models into the scene.
            if (root.surfaceHost.gameEngineImportedWorld) {
                var provider=root.surfaceHost.gameEngineImportedWorld()
                if (root.engineWorld!==provider) root.engineWorld=provider
            }
            var started=Date.now()
            var raw = root.surfaceHost.gameEngineRenderStatus()
            root.snapshotBridgeMs=Date.now()-started
            root.installRenderStatus(raw)
        } else {
            // Test bridges and older embedding hosts may expose only the full
            // status slot; keep that compatibility path explicit.
            root.refresh()
        }
    }

    function updateWaterGeometry() {
        if (!root.paneLive || !root.surfaceHost) return
        if (!root.waterWaveGeometry && root.surfaceHost.gameEngineWaterGeometry)
            root.waterWaveGeometry = root.surfaceHost.gameEngineWaterGeometry()
        if (root.surfaceHost.gameEnginePrepareWaterGpu)
            root.surfaceHost.gameEnginePrepareWaterGpu(root.waterWaveSpanM)
    }

    function installRenderStatus(raw) {
        if (raw === undefined || raw === null)
            return
        var text = String(raw)
        if (text === root.renderStatusJson)
            return
        root.applyingRenderStatus = true
        var started=Date.now()
        root.renderStatusJson = text
        root.snapshotBindingsMs=Date.now()-started
        root.applyingRenderStatus = false
        started=Date.now()
        root.syncRenderModels(root.renderStatus)
        root.snapshotModelsMs=Date.now()-started
        root.renderStreamPrimed = true
        if (root.worldMouseInside && root.worldHoverInfo.id && !root.mouseLeftHeld && !root.mouseRightHeld) {
            try {
                root.worldHoverInfo=JSON.parse(root.surfaceHost.gameEngineWorldHover(root.worldHoverInfo.id))
            } catch(e) {root.worldHoverInfo=({})}
        }
    }

    function startRuntime() {
        if (root.surfaceHost && root.surfaceHost.gameEngineStartRender)
            root.installRenderStatus(root.surfaceHost.gameEngineStartRender())
        else if (root.surfaceHost && root.surfaceHost.gameEngineStart)
            root.applyRaw(root.surfaceHost.gameEngineStart())
    }

    function pauseRuntime() {
        root.clearMovementInput()
        if (root.surfaceHost && root.surfaceHost.gameEnginePauseRender)
            root.installRenderStatus(root.surfaceHost.gameEnginePauseRender())
        else if (root.surfaceHost && root.surfaceHost.gameEnginePause)
            root.applyRaw(root.surfaceHost.gameEnginePause())
    }

    function resetRuntime() {
        if (root.surfaceHost && root.surfaceHost.gameEngineReset)
            root.applyRaw(root.surfaceHost.gameEngineReset())
    }

    function stepRuntime() {
        if (root.surfaceHost && root.surfaceHost.gameEngineStep)
            root.applyRaw(root.surfaceHost.gameEngineStep())
    }

    function burstRuntime() {
        if (root.surfaceHost && root.surfaceHost.gameEngineBurst)
            root.applyRaw(root.surfaceHost.gameEngineBurst())
    }

    function stressRuntime() {
        if (root.surfaceHost && root.surfaceHost.gameEngineStress)
            root.applyRaw(root.surfaceHost.gameEngineStress(!root.stress))
    }

    function setMovementMode(mode) {
        if (root.surfaceHost && root.surfaceHost.gameEngineMovementMode)
            root.applyRaw(root.surfaceHost.gameEngineMovementMode(String(mode)))
        else
            root.sendInput()
    }

    function useAbility(abilityId) {
        if (root.surfaceHost && root.surfaceHost.gameEngineAbility)
            root.applyRaw(root.surfaceHost.gameEngineAbility(
                String(abilityId || "ability.surge")
            ))
    }

    function claimLoot() {
        if (root.surfaceHost && root.surfaceHost.gameEngineLoot)
            root.applyRaw(root.surfaceHost.gameEngineLoot())
    }

    function craftRecipe(recipeId) {
        if (root.surfaceHost && root.surfaceHost.gameEngineCraft)
            root.applyRaw(root.surfaceHost.gameEngineCraft(
                String(recipeId || "recipe.field_ration")
            ))
    }

    function openCrafting(stationId) {
        if (!root.surfaceHost || !root.surfaceHost.gameEngineCraftingOpen)
            return false
        var station = String(stationId || "")
        if (station === "NEAREST") {
            var rows = root.crafting.workstations || []
            var closest = null
            var distance = Infinity
            for (var i = 0; i < rows.length; ++i) {
                var nextDistance = Math.hypot(Number(rows[i].x) - Number(root.player.x), Number(rows[i].z) - Number(root.player.z))
                if (nextDistance < distance) { closest = rows[i]; distance = nextDistance }
            }
            if (!closest) { root.itemNotice = "Ingen arbetsstation finns i den här världen."; return false }
            station = String(closest.id)
        }
        return root.applyItemAction(root.surfaceHost.gameEngineCraftingOpen("TRADE_SKILL", station))
    }

    function closeCrafting() {
        if (root.surfaceHost && root.surfaceHost.gameEngineCraftingClose)
            return root.applyItemAction(root.surfaceHost.gameEngineCraftingClose(Number(root.crafting.book.session)))
        return false
    }

    function craftBookRecipe(recipeId, count) {
        if (root.surfaceHost && root.surfaceHost.gameEngineCraftBookRecipe)
            return root.applyItemAction(root.surfaceHost.gameEngineCraftBookRecipe(Number(root.crafting.book.session), String(recipeId), Number(count)))
        return false
    }

    function stopCrafting() {
        if (root.surfaceHost && root.surfaceHost.gameEngineCraftingStop)
            return root.applyItemAction(root.surfaceHost.gameEngineCraftingStop())
        return false
    }

    function lootItem(instanceId) {
        if (root.surfaceHost && root.surfaceHost.gameEngineLootSlot)
            return root.applyItemAction(root.surfaceHost.gameEngineLootSlot(Number(root.loot.session), String(root.loot.container_id), String(instanceId)))
        return false
    }

    function closeLoot() {
        if (root.surfaceHost && root.surfaceHost.gameEngineLootClose)
            return root.applyItemAction(root.surfaceHost.gameEngineLootClose(Number(root.loot.session)))
        return false
    }

    function craftGear(recipeId, stationId) {
        if (root.surfaceHost && root.surfaceHost.gameEngineGearCraft)
            root.applyRaw(root.surfaceHost.gameEngineGearCraft(
                String(recipeId || "recipe.fiber_rope"),
                String(stationId || "")
            ))
    }

    function findAttachmentNode(loader, name) {
        if (!loader || !name || loader.status !== RuntimeLoader.Success)
            return null
        if (root.surfaceHost
            && typeof root.surfaceHost.gameEngineFindNamedNode === "function")
            return root.surfaceHost.gameEngineFindNamedNode(loader, String(name))
        return null
    }

    function updateEquipmentPhysics(dt) {
        for (var slot in root.equipmentFxNodes) {
            var item=root.equipmentFxNodes[slot]
            if(item && item.stepFlail)item.stepFlail(dt)
        }
    }

    function socketItem(instanceId, insertableId) {
        if (root.surfaceHost && root.surfaceHost.gameEngineItemSocket)
            root.applyRaw(root.surfaceHost.gameEngineItemSocket(
                String(instanceId || root.selectedItemId || ""),
                String(insertableId || "")
            ))
    }

    function enchantGear(instanceId, enchantId) {
        if (root.surfaceHost && root.surfaceHost.gameEngineGearEnchant)
            root.applyRaw(root.surfaceHost.gameEngineGearEnchant(
                String(instanceId || root.selectedItemId || ""),
                String(enchantId || "")
            ))
    }

    function enchantLoot(enchantId) {
        if (root.surfaceHost && root.surfaceHost.gameEngineEnchant)
            root.applyRaw(root.surfaceHost.gameEngineEnchant(
                String(enchantId || "enchant.wayfinder")
            ))
    }

    function interactItem() {
        if (root.surfaceHost && root.surfaceHost.gameEngineItemInteract) {
            var raw = root.surfaceHost.gameEngineItemInteract()
            root.applyRaw(raw)
            root.showOpenedBank(raw)
        }
    }

    function showOpenedBank(raw) {
        try {
            var value = JSON.parse(String(raw || "{}"))
            if (String((value.item_result || {}).action || "") === "OPEN"
                    && Boolean((value.bank || {}).accessible)) {
                root.bankViewOpen = true
                root.page = "BAG"
                root.forceActiveFocus()
            }
        } catch (err) {
            // The normal status path reports malformed command data.
        }
    }

    function nearestSkiffDistance() {
        var entities = (root.render && root.render.entities) || []
        var px = root.number(root.player.x, 0)
        var pz = root.number(root.player.z, 0)
        var best = 100000
        for (var index = 0; index < entities.length; ++index) {
            var row = entities[index]
            if (!row || String(row.kind || "") !== "BOAT")
                continue
            var distance = Math.hypot(
                root.number(row.x, 0) - px,
                root.number(row.z, 0) - pz
            )
            if (distance < best)
                best = distance
        }
        return best
    }

    function interactNearby() {
        if (root.surfaceHost && root.surfaceHost.gameEngineWorldContext && root.combatTarget.id) {
            root.contextWorld(root.combatTarget.id);return true
        }
        if (root.natureTarget.available && root.natureTarget.distance_m <= Math.min(
                root.number(root.npcInteraction.target_distance_m,1000000),
                root.number(root.itemInteraction.distance_m,1000000))) {
            root.interactNature("", "")
            return true
        }
        // The chest in front of the player opens its shared storage view.
        if (Boolean(root.bank.focused)
                && String(root.player.vehicle || "NONE") === "NONE") {
            root.openContainer(String(root.bank.container_id || ""))
            return true
        }
        // E also boards nearby skiffs and dispatches NPC/item interactions.
        if (String(root.player.vehicle || "") === "BOAT"
                || root.nearestSkiffDistance() <= 5.2) {
            root.performMobilityAction("MOUNT_BOAT")
            return true
        }
        var npcAvailable = Boolean(root.npcInteraction.available)
        var itemAvailable = Boolean(
            String(root.itemInteraction.instance_id || "")
        )
        if (!npcAvailable && !itemAvailable)
            return false

        var npcDistance = root.number(
            root.npcInteraction.target_distance_m, 1000000
        )
        var itemDistance = root.number(
            root.itemInteraction.distance_m, 1000000
        )
        if (npcAvailable && (!itemAvailable || npcDistance <= itemDistance))
            root.interactNpc()
        else
            root.interactItem()
        return true
    }

    function pickupItem(instanceId) {
        if (root.surfaceHost && root.surfaceHost.gameEngineItemPickup)
            root.applyRaw(root.surfaceHost.gameEngineItemPickup(
                String(instanceId || "")
            ))
    }

    function openContainer(instanceId) {
        if (root.surfaceHost && root.surfaceHost.gameEngineContainerOpen) {
            var raw = root.surfaceHost.gameEngineContainerOpen(
                String(instanceId || "")
            )
            root.applyRaw(raw)
            root.showOpenedBank(raw)
            try {
                return !Boolean(JSON.parse(String(raw || "{}")).error)
            } catch (err) {
                return false
            }
        }
        return false
    }

    function lootContainer(instanceId) {
        if (root.surfaceHost && root.surfaceHost.gameEngineContainerLoot)
            root.applyRaw(root.surfaceHost.gameEngineContainerLoot(
                String(instanceId || "")
            ))
    }

    function equipItem(instanceId, slot) {
        if (root.surfaceHost && root.surfaceHost.gameEngineItemEquip)
            return root.applyItemAction(root.surfaceHost.gameEngineItemEquip(
                String(instanceId || ""), String(slot || "")
            ))
        return false
    }

    function unequipItem(instanceId) {
        if (root.surfaceHost && root.surfaceHost.gameEngineItemUnequip)
            return root.applyItemAction(root.surfaceHost.gameEngineItemUnequip(
                String(instanceId || "")
            ))
        return false
    }

    function moveInventorySlot(instanceId, slotIndex) {
        if (root.surfaceHost && root.surfaceHost.gameEngineInventoryMove)
            return root.applyItemAction(root.surfaceHost.gameEngineInventoryMove(
                String(instanceId || ""), Number(slotIndex)
            ))
        return false
    }

    function depositToBank(instanceId, slotIndex) {
        if (!root.surfaceHost)
            return false
        if (Number(slotIndex) >= 0 && root.surfaceHost.gameEngineBankDepositAt)
            return root.applyItemAction(root.surfaceHost.gameEngineBankDepositAt(
                String(instanceId || ""), Number(slotIndex)
            ))
        if (root.surfaceHost.gameEngineBankDeposit)
            return root.applyItemAction(root.surfaceHost.gameEngineBankDeposit(
                String(instanceId || "")
            ))
        return false
    }

    function withdrawFromBank(instanceId, slotIndex) {
        if (!root.surfaceHost)
            return false
        if (Number(slotIndex) >= 0 && root.surfaceHost.gameEngineBankWithdrawAt)
            return root.applyItemAction(root.surfaceHost.gameEngineBankWithdrawAt(
                String(instanceId || ""), Number(slotIndex)
            ))
        if (root.surfaceHost.gameEngineBankWithdraw)
            return root.applyItemAction(root.surfaceHost.gameEngineBankWithdraw(
                String(instanceId || "")
            ))
        return false
    }

    function moveBankSlot(instanceId, slotIndex) {
        if (root.surfaceHost && root.surfaceHost.gameEngineBankMove)
            return root.applyItemAction(root.surfaceHost.gameEngineBankMove(
                String(instanceId || ""), Number(slotIndex)
            ))
        return false
    }

    function dropItem(instanceId) {
        if (root.surfaceHost && root.surfaceHost.gameEngineItemDrop)
            return root.applyItemAction(root.surfaceHost.gameEngineItemDrop(
                String(instanceId || "")
            ))
        return false
    }

    function gainXp(amount) {
        if (root.surfaceHost && root.surfaceHost.gameEngineXp)
            root.applyRaw(root.surfaceHost.gameEngineXp(Number(amount || 25)))
    }

    function spendTalent(talentId) {
        if (root.surfaceHost && root.surfaceHost.gameEngineTalent)
            root.applyRaw(root.surfaceHost.gameEngineTalent(
                String(talentId || "trailblazer")
            ))
    }

    function selectRace(race) {
        if (root.surfaceHost && root.surfaceHost.gameEngineRace)
            root.applyRaw(root.surfaceHost.gameEngineRace(String(race)))
    }

    function selectSpec(spec) {
        if (root.surfaceHost && root.surfaceHost.gameEngineSpec)
            root.applyRaw(root.surfaceHost.gameEngineSpec(String(spec)))
    }

    function placeEditorObject(kind) {
        if (root.surfaceHost && root.surfaceHost.gameEngineEditorPlace)
            root.applyRaw(root.surfaceHost.gameEngineEditorPlace(String(kind || "PROP")))
    }

    function undoEditorObject() {
        if (root.surfaceHost && root.surfaceHost.gameEngineEditorUndo)
            root.applyRaw(root.surfaceHost.gameEngineEditorUndo())
    }

    function interactNpc() {
        if (root.surfaceHost && root.surfaceHost.gameEngineNpcInteract)
            root.applyRaw(root.surfaceHost.gameEngineNpcInteract())
    }

    function talkNpc(choiceId, npcId) {
        if (root.surfaceHost && root.surfaceHost.gameEngineNpcTalk)
            root.applyRaw(root.surfaceHost.gameEngineNpcTalk(
                String(npcId || (root.dialogue.active || {}).npc_id
                    || root.npcInteraction.target_id || ""),
                String(choiceId || "")
            ))
    }

    function closeDialogue() {
        if (root.surfaceHost && root.surfaceHost.gameEngineNpcDialogueClose)
            root.applyRaw(root.surfaceHost.gameEngineNpcDialogueClose())
    }

    function activateContentPack(packId) {
        if (root.surfaceHost && root.surfaceHost.gameEngineContentPack)
            root.applyRaw(root.surfaceHost.gameEngineContentPack(
                String(packId || "pack.tidefall-frontier")
            ))
    }

    function attackNpc(targetId, automatic) {
        if (root.firearms.hands && root.firearms.hands.length && root.surfaceHost && root.surfaceHost.gameEngineAttack) {
            root.applyGameplay(root.surfaceHost.gameEngineAttack(String(targetId || ""), automatic ? "automatic_fire" : "basic_attack"))
            return
        }
        if (root.surfaceHost && root.surfaceHost.gameEngineActionCommand) {
            if (targetId && String(root.combatTarget.id || '') !== String(targetId))
                root.selectWorld(targetId)
            root.applyGameplay(root.surfaceHost.gameEngineActionCommand('ATTACK'))
            return
        }
        if (!targetId && root.natureTarget.available && !root.natureTarget.dead
                && root.natureAnimals.indexOf(root.natureTarget.species) >= 0) {
            root.interactNature(root.natureTarget.id, "ATTACK")
            return
        }
        if (root.surfaceHost && root.surfaceHost.gameEngineAttack)
            root.applyRaw(root.surfaceHost.gameEngineAttack(
                String(targetId || "")
            ))
    }

    function reloadFirearms() {
        if (root.surfaceHost && root.surfaceHost.gameEngineFirearmReload)
            root.applyRaw(root.surfaceHost.gameEngineFirearmReload())
    }

    function interactNature(targetId, action) {
        if (root.surfaceHost && root.surfaceHost.gameEngineNatureAction)
            root.applyRaw(root.surfaceHost.gameEngineNatureAction(
                String(targetId || root.natureTarget.id || ""), String(action || "")))
    }

    function cycleCombatTarget(reverse) {
        if (root.surfaceHost && root.surfaceHost.gameEngineWorldTargetCycle) {
            root.applyGameplay(root.surfaceHost.gameEngineWorldTargetCycle(JSON.stringify({
                x:camera.scenePosition.x,y:camera.scenePosition.y,z:camera.scenePosition.z,
                heading:root.cameraHeading,pitch:root.orbitPitch,aspect:view3d.width/view3d.height,fov:camera.fieldOfView}),Boolean(reverse)))
            return
        }
        if (root.surfaceHost && root.surfaceHost.gameEngineTargetNext)
            root.applyRaw(root.surfaceHost.gameEngineTargetNext(Boolean(reverse)))
    }

    function clearCombatTarget() {
        if (root.surfaceHost && root.surfaceHost.gameEngineTargetClear)
            root.applyRaw(root.surfaceHost.gameEngineTargetClear())
    }

    function exploreRegion(regionId) {
        if (root.surfaceHost && root.surfaceHost.gameEngineExploreRegion) {
            root.pressedTokens = ({})
            root.throttle = 0; root.strafe = 0; root.vertical = 0; root.steer = 0
            root.updateInputStates()
            root.applyRaw(root.surfaceHost.gameEngineExploreRegion(String(regionId)))
            root.page = "PLAY"
        }
    }

    function acceptQuest(questId) {
        if (root.surfaceHost && root.surfaceHost.gameEngineQuestAccept)
            root.applyRaw(root.surfaceHost.gameEngineQuestAccept(
                String(questId || "quest.shoreline-first")
            ))
    }

    function claimQuest(questId) {
        if (root.surfaceHost && root.surfaceHost.gameEngineQuestClaim)
            root.applyRaw(root.surfaceHost.gameEngineQuestClaim(
                String(questId || "")
            ))
    }

    function tradeItems(npcId, giveInstanceId, receiveInstanceId) {
        if (root.surfaceHost && root.surfaceHost.gameEngineTrade)
            root.applyRaw(root.surfaceHost.gameEngineTrade(
                String(npcId || ""),
                String(giveInstanceId || ""),
                String(receiveInstanceId || "")
            ))
    }

    function buyFromVendor(vendorId, instanceId) {
        if (root.surfaceHost && root.surfaceHost.gameEngineVendorBuy)
            root.applyRaw(root.surfaceHost.gameEngineVendorBuy(
                String(vendorId || ""),
                String(instanceId || "")
            ))
    }

    function sellToVendor(vendorId, instanceId) {
        if (root.surfaceHost && root.surfaceHost.gameEngineVendorSell)
            root.applyRaw(root.surfaceHost.gameEngineVendorSell(
                String(vendorId || ""),
                String(instanceId || "")
            ))
    }

    function terrainCellForKey(key) {
        var wanted = String(key || "")
        if (!wanted)
            return null
        var cells = root.terrainCells || []
        for (var index = 0; index < cells.length; ++index) {
            var cell = cells[index]
            if (cell && String(cell.key || "") === wanted)
                return cell
        }
        return null
    }

    function setTerrainBrushPoint(cell, worldX, worldZ) {
        if (!cell)
            return
        var minX = root.number(cell.x, 0) * root.terrainCellSize
        var maxX = (root.number(cell.x, 0) + 1) * root.terrainCellSize
        var minZ = root.number(cell.z, 0) * root.terrainCellSize
        var maxZ = (root.number(cell.z, 0) + 1) * root.terrainCellSize
        var pointX = Number(worldX)
        var pointZ = Number(worldZ)
        if (!isFinite(pointX))
            pointX = (minX + maxX) * 0.5
        if (!isFinite(pointZ))
            pointZ = (minZ + maxZ) * 0.5
        terrainBrushX = Math.max(minX, Math.min(maxX, pointX))
        terrainBrushZ = Math.max(minZ, Math.min(maxZ, pointZ))
    }

    function setTerrainTarget(cell, worldX, worldZ) {
        if (!cell)
            return ""
        terrainTargetX = Math.floor(root.number(cell.x, 0))
        terrainTargetZ = Math.floor(root.number(cell.z, 0))
        terrainTargetKey = String(
            cell.key || ("0:" + terrainTargetX + ":" + terrainTargetZ)
        )
        terrainTargetSelected = true
        root.setTerrainBrushPoint(cell, worldX, worldZ)
        return terrainTargetKey
    }

    function adjustTerrainBrushRadius(delta) {
        terrainBrushRadius = Math.max(
            0.75,
            Math.min(
                root.terrainCellSize * 1.25,
                root.number(terrainBrushRadius, 4) + Number(delta || 0)
            )
        )
    }

    function cycleTerrainBrushFalloff() {
        var current = root.terrainBrushFalloffs.indexOf(
            String(root.terrainBrushFalloff || "SMOOTH").toUpperCase()
        )
        terrainBrushFalloff = root.terrainBrushFalloffs[
            (current + 1) % root.terrainBrushFalloffs.length
        ]
    }

    function clearTerrainTarget() {
        terrainTargetSelected = false
        terrainTargetKey = ""
    }

    function pickTerrainCell(viewX, viewY) {
        var pickedCell = null
        var pickedPointX = Number.NaN
        var pickedPointZ = Number.NaN
        try {
            var hit = view3d.pick(Number(viewX), Number(viewY))
            if (hit && hit.objectHit && hit.objectHit.modelData) {
                var hitData = hit.objectHit.modelData
                if (root.terrainCellForKey(String(hitData.key || ""))) {
                    pickedCell = hitData
                    if (hit.scenePosition) {
                        var sceneX = Number(hit.scenePosition.x)
                        var sceneZ = Number(hit.scenePosition.z)
                        if (isFinite(sceneX) && isFinite(sceneZ)) {
                            pickedPointX = sceneX
                            pickedPointZ = sceneZ
                        }
                    }
                }
            }
        } catch (err) {
            pickedCell = null
        }

        // Deep-water cells have no visible slab in the cheap preview.  The
        // projected center fallback still lets the editor target every loaded
        // cell, while never inventing an unloaded world coordinate.
        if (!pickedCell) {
            var bestCell = null
            var bestDistance = Number.POSITIVE_INFINITY
            var bestScreenX = 0
            var bestScreenY = 0
            var cells = root.terrainCells || []
            for (var index = 0; index < cells.length; ++index) {
                var cell = cells[index]
                var center = cell && cell.center_m
                if (!center)
                    continue
                try {
                    var screen = view3d.mapFrom3DScene(Qt.vector3d(
                        root.number(center.x, 0),
                        root.number(center.y, 0),
                        root.number(center.z, 0)
                    ))
                    var screenX = Number(screen.x)
                    var screenY = Number(screen.y)
                    if (!isFinite(screenX) || !isFinite(screenY))
                        continue
                    var distance = Math.hypot(
                        screenX - Number(viewX),
                        screenY - Number(viewY)
                    )
                    if (distance < bestDistance) {
                        bestDistance = distance
                        bestCell = cell
                        bestScreenX = screenX
                        bestScreenY = screenY
                    }
                } catch (projectionError) {
                    // The first frame can be before View3D has a projection.
                }
            }
            var selectionRadius = Math.max(
                42,
                Math.min(stage.width, stage.height) * 0.18
            )
            if (bestCell && bestDistance <= selectionRadius) {
                pickedCell = bestCell
                var offsetX = Math.max(
                    -0.5,
                    Math.min(
                        0.5,
                        (Number(viewX) - bestScreenX) / selectionRadius
                    )
                )
                var offsetZ = Math.max(
                    -0.5,
                    Math.min(
                        0.5,
                        (Number(viewY) - bestScreenY) / selectionRadius
                    )
                )
                pickedPointX = (
                    root.number(bestCell.x, 0) + 0.5 + offsetX
                ) * root.terrainCellSize
                pickedPointZ = (
                    root.number(bestCell.z, 0) + 0.5 + offsetZ
                ) * root.terrainCellSize
            }
        }

        // Before the first renderer frame, projection/picking can legitimately
        // be unavailable.  Keep the editor usable with a deterministic local
        // grid estimate until QtQuick3D has a valid scene hit.
        if (!pickedCell) {
            var gridCells = root.terrainCells || []
            var horizontal = (
                Number(viewX) / Math.max(1, stage.width) - 0.5
            ) * root.terrainCellSize * 5.0
            var depth = (
                Number(viewY) / Math.max(1, stage.height) - 0.5
            ) * root.terrainCellSize * 5.0
            var yawRadians = root.cameraWorldYaw * Math.PI / 180.0
            var projectedX = root.number(root.player.x, 0)
                + horizontal * Math.cos(yawRadians)
                + depth * Math.sin(yawRadians)
            var projectedZ = root.number(root.player.z, 0)
                - horizontal * Math.sin(yawRadians)
                + depth * Math.cos(yawRadians)
            var wantedX = Math.floor(projectedX / root.terrainCellSize)
            var wantedZ = Math.floor(projectedZ / root.terrainCellSize)
            var bestGridDistance = Number.POSITIVE_INFINITY
            for (var gridIndex = 0; gridIndex < gridCells.length; ++gridIndex) {
                var gridCell = gridCells[gridIndex]
                if (!gridCell)
                    continue
                var gridDistance = Math.abs(
                    root.number(gridCell.x, 0) - wantedX
                ) + Math.abs(root.number(gridCell.z, 0) - wantedZ)
                if (gridDistance < bestGridDistance) {
                    bestGridDistance = gridDistance
                    pickedCell = gridCell
                }
            }
        }
        return root.setTerrainTarget(pickedCell, pickedPointX, pickedPointZ)
    }

    function editTerrain(operation) {
        var normalized = String(operation || "RAISE").toUpperCase()
        terrainBrushOperation = normalized
        if (!root.surfaceHost)
            return
        var target = root.terrainTargetSelected
            ? root.terrainCellForKey(root.terrainTargetKey)
            : null
        if (!target && root.terrainTargetSelected)
            root.clearTerrainTarget()
        var targetX = target
            ? root.terrainTargetX
            : Math.floor(root.number(root.player.x, 0) / root.terrainCellSize)
        var targetZ = target
            ? root.terrainTargetZ
            : Math.floor(root.number(root.player.z, 0) / root.terrainCellSize)
        if (
            (normalized === "RAISE" || normalized === "LOWER")
            && root.surfaceHost.gameEngineTerrainBrush
        ) {
            var brushX = target ? root.terrainBrushX : root.number(root.player.x, 0)
            var brushZ = target ? root.terrainBrushZ : root.number(root.player.z, 0)
            root.applyRaw(
                root.surfaceHost.gameEngineTerrainBrush(
                    normalized,
                    targetX,
                    targetZ,
                    brushX,
                    brushZ,
                    root.terrainBrushRadius,
                    root.terrainBrushFalloff
                )
            )
        } else if (root.surfaceHost.gameEngineTerrainEdit) {
            root.applyRaw(root.surfaceHost.gameEngineTerrainEdit(
                normalized,
                targetX,
                targetZ
            ))
        }
    }

    function undoTerrain() {
        if (root.surfaceHost && root.surfaceHost.gameEngineTerrainUndo)
            root.applyRaw(root.surfaceHost.gameEngineTerrainUndo())
    }

    function saveGameState() {
        if (root.surfaceHost && root.surfaceHost.gameEngineSave)
            root.applyRaw(root.surfaceHost.gameEngineSave())
    }

    function loadGameState() {
        if (root.surfaceHost && root.surfaceHost.gameEngineLoad)
            root.applyRaw(root.surfaceHost.gameEngineLoad())
    }

    function setRenderProfile(profile) {
        if (root.surfaceHost && root.surfaceHost.gameEngineRenderProfile)
            root.applyRaw(root.surfaceHost.gameEngineRenderProfile(String(profile)))
    }

    function setPresentationMode(mode) {
        var normalized = String(mode || "RICH_3D").toUpperCase()
        if (root.surfaceHost && root.surfaceHost.gameEnginePresentationMode) {
            root.localGraphicsFailure = false
            root.applyRaw(root.surfaceHost.gameEnginePresentationMode(normalized))
        } else {
            root.localGraphicsFailure = normalized === "DOS_2D"
        }
        // The DOS and low-poly buttons sit on top of the stage.  Without
        // this, the click leaves focus on the button and WASD never reaches
        // the surface, so the new picture has nothing to follow.
        root.forceActiveFocus()
    }

    function togglePresentationMode() {
        root.setPresentationMode(root.dosFallbackActive ? "RICH_3D" : "DOS_2D")
    }

    function reportGraphicsFailure(reason) {
        root.localGraphicsFailure = true
        if (root.surfaceHost && root.surfaceHost.gameEngineGraphicsFailure)
            root.applyRaw(root.surfaceHost.gameEngineGraphicsFailure(
                String(reason || "GRAPHICS_STAGE_FAILURE")
            ))
    }

    function setCinematicPreset(preset) {
        if (root.surfaceHost && root.surfaceHost.gameEngineCinematic)
            root.applyRaw(root.surfaceHost.gameEngineCinematic(String(preset)))
    }

    function performMobilityAction(action) {
        if (!root.surfaceHost || !root.surfaceHost.gameEngineMobilityAction)
            return
        var raw = root.surfaceHost.gameEngineMobilityAction(String(action || ""))
        if (raw !== undefined && raw !== null)
            root.applyRaw(raw)
    }

    function sendInput() {
        if (!root.surfaceHost || !root.surfaceHost.gameEngineInput)
            return
        var payload = JSON.stringify({
            throttle: root.throttle,
            steer: root.steer,
            turn: root.steer,
            brake: root.brake,
            boost: root.boost,
            forward: root.throttle,
            strafe: root.strafe,
            vertical: root.vertical,
            jump: root.jump,
            grapple: root.grapple,
            camera_yaw: root.cameraWorldYaw,
            mouse_look: root.mouseRightHeld,
            facing_yaw: root.mouseLookHeading,
            camera_pitch: root.orbitPitch,
            camera_distance: root.cameraDistance
        })
        if (root.surfaceHost.gameEngineInputRender) {
            // Movement is already committed to the authoritative fixed-step
            // runtime.  Do not parse/rebind the full inspector document for a
            // key transition; the compact render stream gives the scene its
            // immediate position/camera response and UI cadence updates the
            // inspector separately.
            var renderRaw = root.surfaceHost.gameEngineInputRender(payload)
            if (renderRaw !== undefined && renderRaw !== null)
                root.renderStatusJson = String(renderRaw)
        } else {
            // Compatibility path for older embedding hosts that expose only
            // the original full input slot.
            root.applyRaw(root.surfaceHost.gameEngineInput(payload))
        }
    }

    function dosCommand(command) {
        if (root.surfaceHost && root.surfaceHost.gameEngineDosCommand)
            root.applyRaw(root.surfaceHost.gameEngineDosCommand(
                String(command || "")
            ))
    }

    function startRecording() {
        if (root.surfaceHost && root.surfaceHost.gameEngineRecordStart)
            root.applyRaw(root.surfaceHost.gameEngineRecordStart())
    }

    function stopRecording() {
        if (root.surfaceHost && root.surfaceHost.gameEngineRecordStop)
            root.applyRaw(root.surfaceHost.gameEngineRecordStop())
    }

    function replayRuntime() {
        if (root.surfaceHost && root.surfaceHost.gameEngineReplay)
            root.applyRaw(root.surfaceHost.gameEngineReplay())
    }

    function number(value, fallback) {
        var parsed = Number(value)
        return isFinite(parsed) ? parsed : (fallback || 0)
    }

    function planetRenderY(x, y, z) {
        if (root.originalWorldActive) return y
        var radius = root.planetRadiusM
        var radial = Math.max(1, radius + root.number(y, 0))
        var radialHeight = Math.sqrt(Math.max(
            1,
            radial * radial
                - root.number(x, 0) * root.number(x, 0)
                - root.number(z, 0) * root.number(z, 0)
        ))
        return radialHeight - radius
    }

    function bindFaunaRepeater(repeater, clip) {
        if (!repeater
            || !root.paneLive
            || !root.surfaceHost
            || typeof root.surfaceHost.gameEngineRuntimeClip !== "function")
            return
        var count = repeater.count || 0
        for (var index = 0; index < count; ++index) {
            var loader = repeater.objectAt(index)
            if (loader && loader.status === RuntimeLoader.Success)
                root.surfaceHost.gameEngineRuntimeClip(loader, clip, 0, "")
        }
    }

    function refreshSandoverLifeClips() {
        root.bindFaunaRepeater(faunaBirdRepeater, "SandoverBirdFly")
        root.bindFaunaRepeater(faunaFishRepeater, "SandoverFishSwim")
    }

    function fixed(value, decimals) {
        return number(value, 0).toFixed(decimals === undefined ? 1 : decimals)
    }

    function combatActor(actorId) {
        if (String(actorId)==='player' && root.renderStatus.combat_live
                && root.renderStatus.combat_live.player) return root.renderStatus.combat_live.player
        var actors = root.combat.actors || []
        for (var index = 0; index < actors.length; ++index) {
            if (actors[index] && String(actors[index].id || "") === String(actorId || ""))
                return actors[index]
        }
        return ({})
    }

    function fallbackTerminalText() {
        var terminal = root.fallbackView.terminal || ({})
        var lines = terminal.lines || []
        return Array.isArray(lines) ? lines.join("\n") : String(lines || "")
    }

    function assetClipSummary() {
        var clips = root.selectedAsset.clips || []
        var names = []
        for (var index = 0; index < clips.length; ++index) {
            if (clips[index] && clips[index].name)
                names.push(String(clips[index].name))
        }
        return names.length ? names.join(", ") : "-"
    }

    function percent(value, maximum) {
        var max = Math.max(1, number(maximum, 1))
        return Math.max(0, Math.min(1, number(value, 0) / max))
    }

    function biomeColor(value) {
        var biome = String(value || "")
        if (biome === "FIRST_ISLAND")
            return "#4f8339"
        if (biome === "LAND")
            return "#5a8c3c"
        if (biome === "BEACH")
            return "#efd090"
        if (biome === "CLIFF")
            return "#9e653b"
        if (biome === "REEF")
            return "#43b49c"
        if (biome === "DEEP_WATER")
            return "#1e7185"
        return "#39b7c1"
    }

    function terrainMaterialFor(biome, waterCell) {
        // The terrain mesh blends its coast, grass and rock colors per
        // vertex.  A material per 16 m cell made those regions look like
        // separate square tiles even though their heightfield was shared.
        return terrainSurfaceMaterial
    }

    function terrainHlodMaterialFor(biome) {
        // ORBIT cells use one inexpensive tile without vertex colors, so
        // retain a single shared palette material for each far-field biome.
        var value = String(biome || "")
        if (value === "BEACH")
            return terrainHlodBeachMaterial
        if (value === "CLIFF")
            return terrainHlodCliffMaterial
        if (value === "REEF")
            return terrainHlodReefMaterial
        if (value === "DEEP_WATER")
            return terrainHlodDeepWaterMaterial
        if (value === "SHALLOW_WATER")
            return terrainHlodShallowWaterMaterial
        return terrainHlodGrassMaterial
    }

    function stateColor(value) {
        var state = String(value || "")
        if (state === "RUNNING" || state === "READY")
            return root.ledgerGreen
        if (state === "PAUSED" || state === "IDLE")
            return root.ledgerGold
        if (state.indexOf("NOT") === 0 || state === "BLOCKED")
            return root.signalRed
        return root.text
    }

    function bindingMap() {
        return root.keyBindings.bindings || ({})
    }

    function keysFor(action) {
        var keys = bindingMap()[String(action || "")] || []
        if (typeof keys === "string")
            return keys
        return keys.join(" / ")
    }

    function isActionBound(action, token) {
        var keys = bindingMap()[String(action || "")] || []
        if (typeof keys === "string")
            return keys === token
        for (var index = 0; index < keys.length; ++index) {
            if (String(keys[index]) === String(token))
                return true
        }
        return false
    }

    function actionDown(action) {
        var keys = bindingMap()[String(action || "")] || []
        if (typeof keys === "string")
            keys = [keys]
        for (var index = 0; index < keys.length; ++index) {
            if (Boolean(root.pressedTokens[String(keys[index])]))
                return true
        }
        return false
    }

    function axisFor(negativeAction, positiveAction) {
        return (root.actionDown(positiveAction) ? 1 : 0)
            - (root.actionDown(negativeAction) ? 1 : 0)
    }

    function wrapDegrees(value) {
        return value - 360 * Math.floor((value + 180) / 360)
    }

    function beginCameraLook(button) {
        var heading = root.cameraHeading
        if (button === Qt.RightButton) {
            root.mouseLookHeading = heading
            root.mouseRightHeld = true
            root.orbitYaw = 0
        } else {
            root.leftLookHeading = heading
            root.mouseLeftHeld = true
        }
        root.updateInputStates()
        root.sendInput()
    }

    function dragCameraLook(dx, dy) {
        // GgEngine's normal pitch and yaw rate law, adapted to our +Z facing.
        if (root.mouseRightHeld)
            root.mouseLookHeading = root.wrapDegrees(root.mouseLookHeading - dx * 0.225)
        else
            root.leftLookHeading = root.wrapDegrees(root.leftLookHeading - dx * 0.225)
        root.orbitPitch = Math.max(-75, Math.min(75, root.orbitPitch - dy * 0.15))
        root.sendInput()
    }

    function endCameraLook(button) {
        if (button === Qt.RightButton && root.mouseRightHeld) {
            root.sendInput() // Commit facing before releasing the heading lock.
            root.leftLookHeading = root.mouseLookHeading
            root.mouseRightHeld = false
            root.orbitYaw = 0
        } else if (button === Qt.LeftButton && root.mouseLeftHeld) {
            if (!root.mouseRightHeld)
                root.orbitYaw = root.wrapDegrees(root.leftLookHeading - root.characterHeading)
            root.mouseLeftHeld = false
        }
        root.updateInputStates()
        root.sendInput()
    }

    function clearMovementInput() {
        if (root.mouseLeftHeld && !root.mouseRightHeld)
            root.orbitYaw = root.wrapDegrees(root.leftLookHeading - root.characterHeading)
        root.mouseLeftHeld = false
        root.mouseRightHeld = false
        root.pressedTokens = ({})
        root.updateInputStates()
        root.vertical = 0
        root.boost = false
        root.jump = false
        root.grapple = false
        root.brake = 0
        if (root.surfaceHost && root.surfaceHost.gameEngineClientControl)
            root.applyRaw(root.surfaceHost.gameEngineClientControl(JSON.stringify({kind:'input',op:'Cancel'})))
        root.sendInput()
    }

    onControlsLockedChanged: {
        if (root.controlsLocked)
            Qt.callLater(function(){if(root.controlsLocked)root.clearMovementInput()})
    }
    onActiveFocusChanged: {
        if (!root.activeFocus)
            Qt.callLater(function(){if(!root.activeFocus)root.clearMovementInput()})
    }

    function followCamera(dt) {
        if (root.mouseLeftHeld || root.mouseRightHeld)
            return
        if (Math.abs(root.throttle) + Math.abs(root.steer) + Math.abs(root.strafe) > 0.01
                || root.number(root.player.speed, 0) > 0.1) {
            var offset = root.wrapDegrees(root.orbitYaw)
            var step = Math.min(Math.abs(offset), 180 * dt)
            root.orbitYaw = offset - Math.sign(offset) * step
        }
    }

    function crewSource(asset, entityId, kind) {
        if (asset.editor_model) return String(asset.source || "")
        var names = ["brinekip", "copperwake", "glassfin", "mosswake", "tideclaw",
                     "reefrunner", "riftclaw", "briarstride", "mossjaw"]
        var ids = ["gg-codex-original", "gg-codex-character-flow", "gg-codex-cartoon-flow",
                   "gg-codex-art-flow", "gg-codex-sculpt-flow", "gg-codex-style-flow",
                   "gg-codex-riftclaw", "gg-codex-briarstride", "gg-codex-mossjaw"]
        var source = String(asset.source || "")
        var filename = source.split("/").pop()
        var compact = String(asset.mode || "") === "AUTHORED_CROWD_LOD"
            || /-compact(?:-v[0-9]+)?\.glb$/.test(filename)
            || root.number(asset.instance_rank,0)>=8
        var bank = compact ? "compact" : "articulated"
        for (var i = 0; i < names.length; ++i) {
            var match = filename.match(new RegExp("^gg-crew-" + names[i]
                + "(?:-(?:animated|articulated|compact))?(?:-v([0-9]+))?\\.glb$"))
            if (match && match[1] && Number(match[1]) > 0 && Number(match[1]) < 36)
                return Qt.resolvedUrl("../assets/authored/variants/characters/gg-crew-"
                    + names[i] + "-" + bank + "-v" + Number(match[1]) + ".glb")
            if (match || String(asset.id || "") === ids[i])
                return Qt.resolvedUrl("../assets/authored/characters/gg-crew-" + names[i] + "-" + bank + ".glb")
        }
        var hash = 0; var identity = String(entityId || "")
        for (var j = 0; j < identity.length; ++j)
            hash = (hash * 31 + identity.charCodeAt(j)) >>> 0
        var index = kind === "PLAYER" ? 0 : hash % names.length
        return Qt.resolvedUrl("../assets/authored/characters/gg-crew-" + names[index] + "-" + bank + ".glb")
    }

    function updateInputStates() {
        root.throttle = root.axisFor("MOVE_BACK", "MOVE_FORWARD")
        var sideAxis = root.axisFor("TURN_LEFT", "TURN_RIGHT")
        // A/D rotate the +Z-facing avatar; Q grapples and E interacts.
        // W/S never changes the meaning of A/D.
        root.steer = root.mouseRightHeld ? 0 : -sideAxis
        var strafeAxis = root.axisFor("STRAFE_LEFT", "STRAFE_RIGHT")
        root.strafe = root.mouseRightHeld ? strafeAxis + sideAxis : strafeAxis
        if (root.mouseLeftHeld && root.mouseRightHeld)
            root.throttle = 1
        root.vertical = root.axisFor("VERTICAL_DOWN", "VERTICAL_UP")
        root.boost = root.actionDown("SPRINT")
        root.jump = root.actionDown("JUMP")
        root.grapple = root.actionDown("GRAPPLE")
    }

    function keyToken(key) {
        if (key === Qt.Key_Space)
            return "SPACE"
        if (key === Qt.Key_Shift)
            return "SHIFT"
        if (key === Qt.Key_Control)
            return "CONTROL"
        if (key === Qt.Key_Alt)
            return "ALT"
        if (key === Qt.Key_Tab || key === Qt.Key_Backtab)
            return "TAB"
        if (key === Qt.Key_Return || key === Qt.Key_Enter)
            return "ENTER"
        if (key === Qt.Key_Escape)
            return "ESCAPE"
        if (key === Qt.Key_Backspace)
            return "BACKSPACE"
        if (key === Qt.Key_Delete)
            return "DELETE"
        if (key === Qt.Key_Up)
            return "UP"
        if (key === Qt.Key_Down)
            return "DOWN"
        if (key === Qt.Key_Left)
            return "LEFT"
        if (key === Qt.Key_Right)
            return "RIGHT"
        if (key >= Qt.Key_A && key <= Qt.Key_Z)
            return String.fromCharCode(key)
        if (key >= Qt.Key_0 && key <= Qt.Key_9)
            return String.fromCharCode(key)
        return ""
    }

    function rebindKey(action, token) {
        if (!root.surfaceHost || !root.surfaceHost.gameEngineKeybinding)
            return
        root.applyRaw(root.surfaceHost.gameEngineKeybinding(
            String(action || ""),
            String(token || "")
        ))
        root.bindingCaptureAction = ""
        root.pressedTokens = ({})
        root.updateInputStates()
    }

    function resetKeybindings() {
        if (root.surfaceHost && root.surfaceHost.gameEngineKeybindingsReset)
            root.applyRaw(root.surfaceHost.gameEngineKeybindingsReset())
        root.bindingCaptureAction = ""
        root.pressedTokens = ({})
        root.updateInputStates()
    }

    function toggleAddon(addonId, currentlyEnabled) {
        if (root.surfaceHost && root.surfaceHost.gameEngineAddon)
            root.applyRaw(root.surfaceHost.gameEngineAddon(
                String(addonId || ""),
                !Boolean(currentlyEnabled)
            ))
    }

    function addonEnabled(addonId) {
        var rows = root.addonState.addons || []
        for (var index = 0; index < rows.length; ++index) {
            if (String(rows[index].id || "") === String(addonId || ""))
                return Boolean(rows[index].enabled)
        }
        return false
    }

    function bindingRows() {
        return [
            { id: "TARGET_NEXT", label: "CYCLE TARGET (SHIFT REVERSES)" },
            { id: "PRIMARY_ATTACK", label: "PRIMARY ATTACK" },
            { id: "MOVE_FORWARD", label: "MOVE FORWARD" },
            { id: "MOVE_BACK", label: "MOVE BACK" },
            { id: "TURN_LEFT", label: "TURN LEFT" },
            { id: "TURN_RIGHT", label: "TURN RIGHT" },
            { id: "STRAFE_LEFT", label: "STRAFE LEFT" },
            { id: "STRAFE_RIGHT", label: "STRAFE RIGHT" },
            { id: "JUMP", label: "JUMP" },
            { id: "SPRINT", label: "SPRINT" },
            { id: "TOGGLE_FLIGHT", label: "TAKE OFF / LAND" },
            { id: "TOGGLE_HOVERBOARD", label: "TOGGLE HOVERBOARD" },
            { id: "MOUNT_BOAT", label: "BOARD / LEAVE SKIFF" },
            { id: "VERTICAL_UP", label: "SWIM / FLY UP" },
            { id: "VERTICAL_DOWN", label: "SWIM / FLY DOWN" },
            { id: "ABILITY_SURGE", label: "ABILITY SURGE" },
            { id: "ABILITY_UNDERTOW", label: "ABILITY UNDERTOW" },
            { id: "ABILITY_SKY_LEAP", label: "ABILITY SKY LEAP" },
        ]
    }

    function setKeyState(key, pressed) {
        var token = root.keyToken(key)
        if (!token)
            return false
        if ((root.standalonePlayerMode && root.controlsLocked) || localServices.visible)
            return true

        // The UI captures the next physical key, just like a conventional
        // WoW keybinding screen.  Capture happens before gameplay actions so
        // a requested rebind never also turns, strafes or fires an ability.
        if (pressed && root.bindingCaptureAction !== "") {
            root.rebindKey(root.bindingCaptureAction, token)
            return true
        }

        var wasPressed = Boolean(root.pressedTokens[token])
        root.pressedTokens[token] = Boolean(pressed)
        var pressedEdge = pressed && !wasPressed
        if (pressedEdge && (key === Qt.Key_B || key === Qt.Key_I)) {
            root.page = root.page === "BAG" ? "PLAY" : "BAG"
            return true
        }
        if (root.page === "BAG")
            return true
        if (pressedEdge) {
            var commands={POSTURE_TOGGLE:"SitOrStand",SHEATH_TOGGLE:"ToggleSheath",WALK_TOGGLE:"ToggleRun",AUTORUN_TOGGLE:"ToggleAutoRun"}
            for (var action in commands) {
                if (root.isActionBound(action,token)) {
                    if (root.surfaceHost && root.surfaceHost.gameEngineClientControl)
                        root.applyRaw(root.surfaceHost.gameEngineClientControl(JSON.stringify({kind:"input",op:"Fire",key:commands[action]})))
                    return true
                }
            }
        }
        if (pressedEdge && root.isActionBound("TARGET_NEXT", token)) {
            root.cycleCombatTarget(Boolean(root.pressedTokens["SHIFT"]))
            return true
        }
        if (pressedEdge && key === Qt.Key_Escape && root.combatTarget.id) {
            root.clearCombatTarget()
            return true
        }
        if (pressedEdge && root.isActionBound("TOGGLE_HOVERBOARD", token)) {
            root.performMobilityAction("TOGGLE_HOVERBOARD")
            return true
        }
        if (pressedEdge && root.isActionBound("PRIMARY_ATTACK", token) && token !== "V") {
            root.attackNpc(String(root.combatTarget.id || ""))
            return true
        }
        if (pressedEdge && root.isActionBound("RELOAD_FIREARM", token)) {
            root.reloadFirearms()
            return true
        }
        if (pressedEdge && key === Qt.Key_1) {
            root.setMovementMode("GROUND")
            return true
        }
        if (pressedEdge && key === Qt.Key_2) {
            root.setMovementMode("SWIM")
            return true
        }
        if (pressedEdge && key === Qt.Key_3) {
            root.setMovementMode("FLY")
            return true
        }
        if (pressedEdge && root.isActionBound("TOGGLE_FLIGHT", token)) {
            root.performMobilityAction("TOGGLE_FLIGHT")
            return true
        }
        if (pressedEdge && root.isActionBound("TOGGLE_HOVERBOARD", token)) {
            root.performMobilityAction("TOGGLE_HOVERBOARD")
            return true
        }
        if (pressedEdge && root.isActionBound("MOUNT_BOAT", token)) {
            root.performMobilityAction("MOUNT_BOAT")
            return true
        }
        if (pressedEdge && root.isActionBound("INTERACT", token)) {
            root.interactNearby()
            return true
        }
        if (root.isActionBound("ABILITY_SURGE", token)) {
            if (pressedEdge)
                root.useAbility("ability.surge")
            return true
        }
        if (root.isActionBound("ABILITY_UNDERTOW", token)) {
            if (pressedEdge)
                root.useAbility("ability.undertow")
            return true
        }
        if (root.isActionBound("ABILITY_SKY_LEAP", token)) {
            if (pressedEdge)
                root.useAbility("ability.sky_leap")
            return true
        }

        var movementAction = root.isActionBound("MOVE_FORWARD", token)
            || root.isActionBound("MOVE_BACK", token)
            || root.isActionBound("TURN_LEFT", token)
            || root.isActionBound("TURN_RIGHT", token)
            || root.isActionBound("STRAFE_LEFT", token)
            || root.isActionBound("STRAFE_RIGHT", token)
            || root.isActionBound("JUMP", token)
            || root.isActionBound("GRAPPLE", token)
            || root.isActionBound("SPRINT", token)
            || root.isActionBound("VERTICAL_UP", token)
            || root.isActionBound("VERTICAL_DOWN", token)
        if (!movementAction)
            return false
        root.updateInputStates()
        root.sendInput()
        return true
    }

    focus: true
    activeFocusOnTab: true

    FrameAnimation {
        id: refreshTimer
        objectName: "gameRenderFrameAnimation"
        running: root.paneLive
            && root.surfaceHost !== null
            && (root.running || root.replaying)
        onTriggered: {
            if (!root.controlsLocked && !root.cinematic.active)
                root.followCamera(refreshTimer.frameTime)
            root.refreshRender()
            root.updateEquipmentPhysics(refreshTimer.frameTime)
        }
    }

    FrameAnimation {
        id: importedCameraFrame
        objectName: "importedWorldCameraFrame"
        running: root.paneLive && root.originalWorldActive
        onTriggered: root.updateImportedCamera(importedCameraFrame.frameTime)
    }

    Timer {
        interval: 16; repeat: true
        running: root.paneLive && root.enabled && root.page === "PLAY" && !root.controlsLocked && !root.cinematic.active
        onTriggered: {
            var hands=root.firearms.hands || []
            if (!hands.length) return
            var held=false,automatic=false,ready=false,time=root.number(root.player.time_s,0)
            for (var token in root.pressedTokens)
                if (root.pressedTokens[token] && root.isActionBound("PRIMARY_ATTACK",token)) held=true
            for (var i=0;i<hands.length;++i) {
                if (hands[i].profile.automatic) automatic=true
                var mag=hands[i].magazine
                if (hands[i].profile.automatic && mag.next_fire<=time && !mag.pending
                        && (mag.rounds>=hands[i].profile.rounds_per_shot || hands[i].reserve>0)) ready=true
            }
            if (held && automatic && ready) root.attackNpc(String(root.combatTarget.id || ""),true)
        }
    }

    Rectangle {
        objectName: "gameFirearmAmmoHud"
        z: 50
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom; anchors.bottomMargin: 104
        width: 460; height: 18+gunAmmoColumn.implicitHeight
        visible: root.page === "PLAY" && (root.firearms.hands || []).length>0
        color: "#dd16242a"; border.color: "#aa9a72"; radius: 3
        Column {
            id: gunAmmoColumn; x:10; y:6; width: parent.width-20; spacing: 3
            Repeater {
                model: root.firearms.hands || []
                delegate: Text {
                    required property var modelData
                    width: gunAmmoColumn.width
                    text: (modelData.slot==="MAIN_HAND" ? "H: " : "V: ")
                        +modelData.profile.name+" · "+modelData.magazine.rounds+"/"+modelData.profile.capacity
                        +" · "+modelData.reserve+" "+modelData.profile.ammo_name
                        +(modelData.magazine.pending ? " · LADDAR" : " · Y: LADDA OM")
                    color: modelData.magazine.pending ? "#f2c178" : "#d9e4df"
                    font.pixelSize: 11; elide: Text.ElideRight
                }
            }
        }
        MouseArea { anchors.fill: parent; onClicked: root.reloadFirearms() }
    }

    Timer {
        id: waterGeometryTimer
        // Mesh preparation only; water animates in the shader every frame.
        interval: 1000
        repeat: true
        running: root.paneLive
            && root.surfaceHost !== null
            && (root.running || root.replaying)
        onTriggered: root.updateWaterGeometry()
    }

    Timer {
        id: sandoverLifeClipTimer
        interval: 500
        repeat: true
        running: root.paneLive && root.surfaceHost !== null
        onTriggered: root.refreshSandoverLifeClips()
    }

    Timer {
        id: graphicsProbe
        interval: 3000
        repeat: true
        running: root.paneLive && root.running && !root.dosFallbackActive
        property int misses: 0
        onTriggered: {
            var api = String(view3d.renderStats.graphicsApiName || "")
            var frame = root.number(
                view3d.renderStats ? view3d.renderStats.frameTime : 0,
                0
            )
            if (api === "" && frame <= 0) {
                graphicsProbe.misses += 1
                if (graphicsProbe.misses >= 2)
                    root.reportGraphicsFailure("GRAPHICS_API_UNAVAILABLE")
            } else {
                graphicsProbe.misses = 0
            }
        }
    }

    Timer {
        id: statusRefreshTimer
        interval: root.statusUpdateIntervalMs
        repeat: true
        running: root.paneLive
            && root.surfaceHost !== null
            && (root.running || root.replaying || localServices.visible)
        onTriggered: root.refresh()
    }
    Timer {
        interval:100;repeat:true
        running:root.paneLive && root.surfaceHost!==null && (root.mountedWorldState.status==="LOADING" || (root.engineWorld && root.engineWorld.loading) || (root.originalWorldActive && !root.running && !root.replaying))
        onTriggered: {root.refreshRender();root.refresh()}
    }

    Component.onCompleted: {
        if (!root.paneLive)
            return
        root.refresh()
        root.updateWaterGeometry()
        root.forceActiveFocus()
    }

    onPageChanged: {
        root.refresh()
        if (root.page === "BAG" || root.page === "CHAR") {
            root.clearMovementInput()
        }
    }
    onSurfaceHostChanged: {
        root.sandoverBirdClipBound = false
        root.sandoverFishClipBound = false
        root.refreshSandoverLifeClips()
    }
    onVisibleChanged: {
        if (visible && root.paneLive) {
            root.refresh()
            root.forceActiveFocus()
        } else if (!visible) {
            root.suspendRuntime()
        }
    }

    onPaneLiveChanged: {
        root.refreshSandoverLifeClips()
        if (root.paneLive) {
            if (root.resumeWhenShown)
                root.startRuntime()
            root.resumeWhenShown = false
            root.refresh()
            root.refreshRender()
            root.forceActiveFocus()
        } else {
            root.resumeWhenShown = root.running
            root.suspendRuntime()
        }
    }

    function suspendRuntime() {
        root.clearMovementInput()
        if (root.running)
            root.pauseRuntime()
    }

    // The workspace keeps this surface loaded after the first visit.
    // Hidden tabs must still stop the render timers and the host tick.
    Component.onDestruction: root.suspendRuntime()

    Shortcut {
        sequence: "F8"
        context: Qt.ApplicationShortcut
        onActivated: root.togglePresentationMode()
    }

    Keys.onPressed: function(event) {
        if (root.cinematic.active) {
            if (event.key === Qt.Key_Escape) root.skipOpeningCinematic()
            event.accepted = true
            return
        }
        if (root.page === "CHAR") {
            if (event.key === Qt.Key_Escape) {
                root.page = "PLAY"
                if (root.standalonePlayerMode) root.startRuntime()
            }
            event.accepted = true
            return
        }
        if (!event.isAutoRepeat && !root.controlsLocked) {
            var slot=-1
            if (event.key>=Qt.Key_1 && event.key<=Qt.Key_9) slot=event.key-Qt.Key_1
            else if (event.key===Qt.Key_0) slot=9
            else if (event.key===Qt.Key_Minus) slot=10
            else if (event.key===Qt.Key_Equal) slot=11
            if (slot>=0) {root.useActionSlot(Number(root.actionState.page || 0)*12+slot);event.accepted=true;return}
        }
        if (event.isAutoRepeat)
            return
        if (root.page === "BAG" && event.key === Qt.Key_Escape) {
            root.page = "PLAY"
            event.accepted = true
            return
        }
        if (event.key === Qt.Key_Escape && root.dialogue.open) {
            root.closeDialogue()
            event.accepted = true
            return
        }
        if (root.standalonePlayerMode && event.key === Qt.Key_Escape && !root.combatTarget.id) {
            root.gameMenuRequested()
            event.accepted = true
            return
        }
        if (root.setKeyState(event.key, true))
            event.accepted = true
    }

    Keys.onReleased: function(event) {
        if (event.isAutoRepeat)
            return
        if (root.setKeyState(event.key, false))
            event.accepted = true
    }


    GameActionBar {
        surface: root
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 14
        z: 100
        visible: root.paneLive && (root.page==='PLAY' || root.page==='BAG') && root.addonEnabled('ACTION_BAR')
    }
    Rectangle {
        z:150;visible:!!root.actionDrag.kind
        x:root.actionDragX-20;y:root.actionDragY-20;width:40;height:40
        color:'#b0354840';border.color:'#efcd83'
        Text {anchors.centerIn:parent;text:root.actionDrag.kind==='ITEM' ? '◆' : '✦';color:'#efcd83';font.pixelSize:28}
    }
    Image {
        z:160;visible:root.worldMouseInside && !!root.worldHoverInfo.id && !root.mouseLeftHeld && !root.mouseRightHeld && !root.controlsLocked
        x:root.worldMouseX+14;y:root.worldMouseY+18;width:24;height:24
        source:'../assets/authored/ui/'+String(root.worldHoverInfo.cursor || 'pet').toLowerCase()+'.svg'
        opacity:root.worldHoverInfo.in_range ? 1 : .4
    }
    Rectangle {
        z:159;visible:root.worldMouseInside && !!root.worldHoverInfo.id && !root.mouseLeftHeld && !root.mouseRightHeld && !root.controlsLocked
        x:Math.min(root.width-width-10,root.worldMouseX+42);y:Math.min(root.height-height-90,root.worldMouseY+18)
        width:hoverLabel.implicitWidth+16;height:hoverLabel.implicitHeight+12
        color:'#e0182427';border.color:root.worldHoverInfo.in_range ? '#d7bf78' : '#9a7060';radius:3
        Text {id:hoverLabel;anchors.centerIn:parent;color:'#e9dcb8';font.pixelSize:11
            text:String(root.worldHoverInfo.name || '')+' · '+Number(root.worldHoverInfo.distance_m || 0).toFixed(1)+' m'
                +(root.worldHoverInfo.reason ? '\n'+root.worldHoverInfo.reason : '')}
    }
    Rectangle {
        anchors.fill: parent
        color: "#161616"
        border.color: root.frameBorder
        border.width: root.standalonePlayerMode ? 0 : 1
        radius: root.standalonePlayerMode ? 0 : root.frameRadius
        antialiasing: false
    }

    Item {
        id: chrome
        anchors.fill: parent
        anchors.leftMargin: root.standalonePlayerMode ? 0 : 10
        anchors.rightMargin: root.standalonePlayerMode ? 0 : 12
        anchors.topMargin: root.standalonePlayerMode ? 0 : 9
        anchors.bottomMargin: root.standalonePlayerMode ? 0 : 9

        Rectangle {
            id: toolbar
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: 34
            visible: !root.standalonePlayerMode
            color: root.panelOverlayRaised
            border.color: "#333333"
            border.width: 1

            Text {
                anchors.left: parent.left
                anchors.leftMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                text: "GG / GAME ENGINE · LOCAL PLAYGROUND"
                color: root.ledgerGold
                font.family: "monospace"
                font.pixelSize: 11
            }

            Row {
                anchors.right: parent.right
                anchors.rightMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                spacing: 6

                GgButton {
                    objectName: "gameEngineWorldLoadButton"
                    text: root.originalWorldActive ? "GG WORLD" : "LOAD WORLD"
                    implicitWidth: 96
                    implicitHeight: 25
                    HoverHandler { id: worldLoadHover }
                    ToolTip.text: root.worldLoadMessage || (root.engineWorld ? root.engineWorld.error : "")
                    ToolTip.visible: worldLoadHover.hovered && ToolTip.text.length > 0
                    onClicked: root.originalWorldActive ? root.selectGgEngineWorld("") : worldManifestDialog.open()
                }

                GgButton {
                    objectName: "gameEngineWorldDemoButton"
                    text: "DEMO WORLD"
                    implicitWidth: 96
                    implicitHeight: 25
                    enabled: !root.originalWorldActive
                    onClicked: root.selectGgEngineWorld("game/worlds/engine-demo/world.json")
                }

                GgButton {
                    objectName: "gameEnginePlayButton"
                    text: root.running ? "PAUSE" : "PLAY"
                    implicitWidth: 66
                    implicitHeight: 25
                    checked: root.running
                    onClicked: root.running
                        ? root.pauseRuntime()
                        : root.startRuntime()
                }

                GgButton {
                    text: "RESET"
                    implicitWidth: 62
                    implicitHeight: 25
                    onClicked: root.resetRuntime()
                }

                GgButton {
                    text: "BURST"
                    implicitWidth: 62
                    implicitHeight: 25
                    onClicked: root.burstRuntime()
                }
            }
        }

        Item {
            id: body
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: root.standalonePlayerMode ? parent.top : toolbar.bottom
            anchors.bottom: parent.bottom
            anchors.topMargin: root.standalonePlayerMode ? 0 : 8

            Loader {
                anchors.fill: parent
                anchors.leftMargin: root.standalonePlayerMode ? 0 : sidebar.width + 8
                z: 29
                active: root.page === "CHAR"
                sourceComponent: CharacterCreationPanel {
                    surfaceHost: root.surfaceHost
                    onApplied: root.applyRaw(root.surfaceHost.gameEngineStatus())
                    onClosed: {
                        root.page = "PLAY"
                        if (root.standalonePlayerMode) root.startRuntime()
                        root.forceActiveFocus()
                    }
                }
            }

            Rectangle {
                id: sidebar
                objectName: "gameEngineSidebar"
                z: 30
                visible: !root.standalonePlayerMode
                anchors.left: parent.left
                anchors.top: parent.top
                width: root.leftMenuCollapsed ? 34 : 124
                height: root.leftMenuCollapsed
                    ? 49
                    : 16 + 25 + 3 + root.nav.length * 29
                        + Math.max(0, root.nav.length - 1) * 3
                color: root.panelOverlay
                border.color: "#46504f"
                border.width: 1

                Column {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 8
                    spacing: 3

                    Rectangle {
                        id: leftMenuToggle
                        objectName: "gameEngineLeftMenuToggle"
                        width: parent.width
                        height: 25
                        color: root.leftMenuCollapsed
                            ? root.selectedPanel : "transparent"
                        border.color: root.leftMenuCollapsed
                            ? "#5f646a" : "transparent"
                        border.width: 1

                        Text {
                            anchors.fill: parent
                            text: root.leftMenuCollapsed ? "›" : "☰"
                            color: root.ink
                            font.pixelSize: root.leftMenuCollapsed ? 18 : 16
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }

                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.leftMenuCollapsed =
                                !root.leftMenuCollapsed
                        }
                    }

                    Repeater {
                        model: root.leftMenuCollapsed ? [] : root.nav

                        delegate: Rectangle {
                            required property string modelData
                            width: parent.width
                            height: 29
                            radius: 2
                            color: root.page === modelData
                                ? root.selectedPanel
                                : "transparent"
                            border.color: root.page === modelData
                                ? "#5f646a"
                                : "transparent"
                            border.width: 1

                            Text {
                                anchors.left: parent.left
                                anchors.leftMargin: 10
                                anchors.verticalCenter: parent.verticalCenter
                                text: parent.modelData
                                color: root.page === parent.modelData
                                    ? root.ink
                                    : root.text
                                font.family: "monospace"
                                font.pixelSize: 11
                                font.bold: root.page === parent.modelData
                            }

                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    root.page = parent.modelData
                                    root.forceActiveFocus()
                                }
                            }
                        }
                    }
                }

            }

            Rectangle {
                id: engineRail
                objectName: "gameEngineEngineRail"
                z: 30
                visible: !root.standalonePlayerMode
                anchors.left: sidebar.left
                anchors.bottom: parent.bottom
                width: sidebar.width
                height: root.leftMenuCollapsed ? 36 : 72
                color: root.panelOverlay
                border.color: "#46504f"
                border.width: 1

                Text {
                    anchors.centerIn: parent
                    visible: root.leftMenuCollapsed
                    text: "E"
                    color: root.ledgerGreen
                    font.family: "monospace"
                    font.pixelSize: 13
                    font.bold: true
                }

                Column {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.margins: 10
                    spacing: 4
                    visible: !root.leftMenuCollapsed

                    Text {
                        text: "ENGINE"
                        color: root.ledgerGreen
                        font.family: "monospace"
                        font.pixelSize: 12
                        font.bold: true
                    }
                    Text {
                        width: parent.width
                        text: "BOUNDED\nLOCAL\nDETERMINISTIC"
                        color: root.muted
                        font.family: "monospace"
                        font.pixelSize: 10
                        lineHeight: 1.1
                    }
                }
            }

            Item {
                id: stage
                objectName: "gameEngineStage"
                anchors.fill: parent

                GgButton {
                    objectName: "gameEnginePresentationToggle"
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 8
                    z: 40
                    implicitWidth: 92
                    implicitHeight: 26
                    text: root.dosFallbackActive ? "LOW POLY" : "DOS"
                    checked: root.dosFallbackActive
                    onClicked: root.togglePresentationMode()
                }

                View3D {
                    id: view3d
                    objectName: "gameEngineView3D"
                    anchors.fill: parent
                    // The bounded console-era profiles render color/depth at
                    // their internal scale, then composite to the viewport.
                    // This changes presentation cost only, not gameplay data.
                    explicitTextureWidth: Math.max(
                        1,
                        Math.round(width * Screen.devicePixelRatio
                            * root.internalResolutionScale)
                    )
                    explicitTextureHeight: Math.max(
                        1,
                        Math.round(height * Screen.devicePixelRatio
                            * root.internalResolutionScale)
                    )
                    // Hiding the rich renderer is presentation-only.  The
                    // fixed-step host keeps producing the same entity/item/
                    // NPC rows for the DOS canvas below.
                    visible: !root.dosFallbackActive && root.paneLive
                    camera: camera
                    environment: ExtendedSceneEnvironment {
                        objectName: "gamePaintedSceneEnvironment"
                        // Only HDR sources bloom; ordinary painted surfaces
                        // remain readable. Two blur levels keep cost bounded.
                        glowEnabled: !root.originalWorldActive && root.render.profile !== "POTATO"
                        effects: root.originalWorldActive || originalFfx.ghost ? [originalFfx] : []
                        glowBlendMode: ExtendedSceneEnvironment.Additive
                        glowHDRMinimumValue: 1.1
                        glowBloom: 0.0
                        glowStrength: root.atmosphere.glowStrength
                        glowIntensity: root.atmosphere.glowIntensity
                        glowLevel: ExtendedSceneEnvironment.Two | ExtendedSceneEnvironment.Three
                        glowQualityHigh: false
                        glowUseBicubicUpscale: false
                        // The ambient probe is generated once. Sky colours
                        // animate on the cheap skydome below, without rebuilding
                        // and prefiltering a 512px HDR cubemap every clock tick.
                        clearColor: root.oceanHorizonColor
                        backgroundMode: SceneEnvironment.Color
                        lightProbe: Texture {
                            textureData: ProceduralSkyTextureData {
                                textureQuality:
                                    ProceduralSkyTextureData.SkyTextureQualityLow
                                skyTopColor: "#799bbd"
                                skyHorizonColor: "#adbac9"
                                groundHorizonColor: "#adbac9"
                                groundBottomColor: "#526568"
                                skyEnergy: 1.0
                                groundEnergy: 0.9
                                sunEnergy: 0.0
                            }
                        }
                        probeExposure: root.atmosphere.probeEnergy
                        skyboxBlurAmount: 0.0
                        fog: Fog {
                            objectName: "gameDistanceFog"
                            enabled: true
                            depthEnabled: true
                            depthNear: root.distanceFog.near
                            Behavior on depthNear { NumberAnimation { duration: 1200 } }
                            depthFar: root.distanceFog.far
                            depthCurve: root.distanceFog.curve
                            density: 1.0
                            color: root.oceanHorizonColor
                        }
                        antialiasingMode: root.render.profile === "POTATO"
                            || root.ps2ClassicRenderer
                            ? SceneEnvironment.NoAA
                            : (root.render.profile === "CINEMATIC"
                                ? SceneEnvironment.SSAA : SceneEnvironment.MSAA)
                        antialiasingQuality: root.render.profile === "CINEMATIC"
                            ? SceneEnvironment.VeryHigh
                            : (root.render.profile === "MODERN"
                                ? SceneEnvironment.High : SceneEnvironment.Medium)
                        temporalAAEnabled: !root.ps2ClassicRenderer
                            && (root.render.profile === "MODERN"
                                || root.render.profile === "CINEMATIC")
                        temporalAAStrength: root.render.profile === "CINEMATIC" ? 0.85 : 0.55
                        tonemapMode: root.originalWorldActive || root.ps2ClassicRenderer
                            ? SceneEnvironment.TonemapModeLinear
                            : SceneEnvironment.TonemapModeFilmic
                        aoEnabled: root.render.profile !== "POTATO"
                            && !root.ps2ClassicRenderer
                        aoStrength: root.render.profile === "CINEMATIC" ? 0.32 : 0.14
                    }

                    PerspectiveCamera {
                        id: camera
                        fieldOfView: 45
                        fieldOfViewOrientation: PerspectiveCamera.Vertical
                        frustumCullingEnabled: root.frustumCullingEnabled
                        position: Qt.vector3d(
                            root.renderCameraX,
                            root.planetRenderY(
                                root.renderCameraX,
                                root.renderCameraY,
                                root.renderCameraZ
                            ),
                            root.renderCameraZ
                        )
                        eulerRotation: Qt.vector3d(
                            root.cinematic.preset === "ORBIT_WORLD_SCALE"
                                ? -42 : root.orbitPitch,
                            root.cameraWorldYaw,
                            0
                        )
                        clipNear: Math.max(
                            root.number(
                                root.world.camera
                                    ? root.world.camera.clip_near_m : 0.1,
                                0.1
                            ),
                            Math.min(2.0, root.renderFarClipM / 500000)
                        )
                        clipFar: root.cameraClipFarM
                    }

                    Model {
                        objectName: "gameAtmosphereSkyDome"
                        visible: !(root.originalWorldActive && root.engineWorld && root.engineWorld.lighting.source === "ORIGINAL_LIGHT_DBC")
                        geometry: root.lowPolySphereGeometry
                        position: camera.position
                        scale: Qt.vector3d(root.cameraClipFarM*.99/50,
                            root.cameraClipFarM*.99/50, root.cameraClipFarM*.99/50)
                        castsShadows: false
                        receivesShadows: false
                        materials: AdventureSkyMaterial {
                            uTopColor: root.atmosphere.sky
                            uHorizonColor: root.oceanHorizonColor
                            uBottomColor: root.atmosphere.ground
                            uCloudColor: root.atmosphere.cloud
                            uTime: root.number(root.player.time_s,0)
                            uNight: root.atmosphere.night
                        }
                    }

                    DirectionalLight {
                        objectName: "gameKeyLight"
                        eulerRotation: Qt.vector3d(-58, 42, 0)
                        brightness: root.atmosphere.keyEnergy
                        color: root.atmosphere.key
                        Behavior on color { ColorAnimation { duration: 1600 } }
                        Behavior on brightness { NumberAnimation { duration: 1600 } }
                        castsShadow: root.shadowMappingEnabled
                        shadowMapQuality: root.render.profile === "CINEMATIC"
                            ? Light.ShadowMapQualityHigh
                            : Light.ShadowMapQualityMedium
                        shadowMapFar: root.render.profile === "CINEMATIC"
                            ? Math.max(root.streamCoverageSize * 1.5, 180)
                            : 80
                        shadowFactor: 32
                    }

                    DirectionalLight {
                        objectName: "gameSkyFillLight"
                        eulerRotation: Qt.vector3d(-18, -135, 0)
                        brightness: root.atmosphere.fillEnergy
                        color: root.atmosphere.fill
                        Behavior on color { ColorAnimation { duration: 1600 } }
                        Behavior on brightness { NumberAnimation { duration: 1600 } }
                        castsShadow: false
                    }

                    DirectionalLight {
                        objectName: "gameMoonRimLight"
                        eulerRotation: Qt.vector3d(-28, 145, 0)
                        brightness: .08 + root.atmosphere.night * .10
                        color: root.atmosphere.fill
                        castsShadow: false
                    }

                    Model {
                        id: grappleRopeModel
                        objectName: "gameGrappleRope"
                        source: "#Cube"
                        property var grappleState: root.player.grapple || ({})
                        property bool grappleAttached:
                            Boolean(grappleState.attached)
                        property bool hookFlying:
                            Boolean(grappleState.projectile_active)
                        property real ropeEndX: grappleAttached
                            ? root.number(grappleState.anchor_x, 0)
                            : root.number(grappleState.projectile_x, 0)
                        property real ropeEndY: grappleAttached
                            ? root.number(grappleState.anchor_y, 0)
                            : root.number(grappleState.projectile_y, 0)
                        property real ropeEndZ: grappleAttached
                            ? root.number(grappleState.anchor_z, 0)
                            : root.number(grappleState.projectile_z, 0)
                        property real ropeStartY:
                            root.number(root.player.y, 0) + 0.85
                        property real ropeDx:
                            ropeEndX - root.number(root.player.x, 0)
                        property real ropeDy:
                            ropeEndY - ropeStartY
                        property real ropeDz:
                            ropeEndZ - root.number(root.player.z, 0)
                        property real ropeHorizontal:
                            Math.sqrt(ropeDx * ropeDx + ropeDz * ropeDz)
                        visible: grappleAttached || hookFlying
                        position: Qt.vector3d(
                            root.number(root.player.x, 0) + ropeDx * 0.5,
                            ropeStartY + ropeDy * 0.5,
                            root.number(root.player.z, 0) + ropeDz * 0.5
                        )
                        eulerRotation: Qt.vector3d(
                            Math.atan2(ropeHorizontal, ropeDy) * 57.2957795,
                            Math.atan2(ropeDx, ropeDz) * 57.2957795,
                            0
                        )
                        scale: Qt.vector3d(
                            0.045 * root.sceneScale,
                            Math.sqrt(
                                ropeDx * ropeDx + ropeDy * ropeDy + ropeDz * ropeDz
                            ) * root.sceneScale,
                            0.045 * root.sceneScale
                        )
                        castsShadows: false
                        receivesShadows: false
                        materials: PrincipledMaterial {
                            baseColor: "#d8bd78"
                            roughness: 0.72
                            metalness: 0.0
                        }
                    }

                    RuntimeLoader {
                        objectName: "gameGrappleHook"
                        source: Qt.resolvedUrl(
                            "../assets/authored/props/gg-grapple-hook.glb"
                        )
                        property var grappleState: root.player.grapple || ({})
                        visible: Boolean(grappleState.attached)
                            || Boolean(grappleState.projectile_active)
                        position: Qt.vector3d(
                            Boolean(grappleState.attached)
                                ? root.number(grappleState.anchor_x, 0)
                                : root.number(grappleState.projectile_x, 0),
                            Boolean(grappleState.attached)
                                ? root.number(grappleState.anchor_y, 0)
                                : root.number(grappleState.projectile_y, 0),
                            Boolean(grappleState.attached)
                                ? root.number(grappleState.anchor_z, 0)
                                : root.number(grappleState.projectile_z, 0)
                        )
                        // The Blender GLB is authored in meters and follows
                        // local +Z after its Y-up export, matching the rope.
                        scale: Qt.vector3d(1, 1, 1)
                        eulerRotation.x: -Math.atan2(
                            grappleRopeModel.ropeDy,
                            grappleRopeModel.ropeHorizontal
                        ) * 57.2957795
                        eulerRotation.y: Math.atan2(
                            grappleRopeModel.ropeDx,
                            grappleRopeModel.ropeDz
                        ) * 57.2957795
                    }

                    RuntimeLoader {
                        id: planetSurfaceLoader
                        onStatusChanged: if (status===RuntimeLoader.Success && root.surfaceHost.gameEngineEnablePicking)
                            root.surfaceHost.gameEngineEnablePicking(this,'')
                        objectName: "gamePlanetSurfaceLoader"
                        source: Qt.resolvedUrl(
                            root.largeEnvironment
                                ? "../assets/authored/world/gg-sandover-planet-surface-landscape.glb"
                                : "../assets/authored/world/gg-sandover-planet-surface.glb"
                        )
                        visible: !root.originalWorldActive && root.planetSurfaceAssetVisible
                        // This mesh and the water/terrain collision data share
                        // world-meter coordinates. sceneScale only sizes local
                        // primitives and must not shrink world-space geometry.
                        scale: Qt.vector3d(1, 1, 1)
                    }

                    GgEngineWorldPage {
                        id: originalWorldPage
                        stream: root.engineWorld
                        textureTrilinear: root.nativeScenePresentation ? root.nativeScenePresentation.textureTrilinear : true
                        cameraPosition: camera.scenePosition
                        sceneCamera: camera
                        cameraAspect: Math.max(.05,view3d.width/Math.max(1,view3d.height))
                        live: root.paneLive
                        animate: root.running || root.replaying
                    }
                    GgEngineWorldActorsPage {
                        provider: root.originalWorldActors
                        textureTrilinear: root.nativeScenePresentation ? root.nativeScenePresentation.textureTrilinear : true
                        stream: root.engineWorld
                        cameraPosition: camera.scenePosition
                        hidePlayer: root.firstPersonView
                        visible: root.originalWorldActive
                    }

                    GgEngineFfxEffect {
                        id: originalFfx
                        objectName: "ggGgEngineFfx"
                        property var state: root.engineWorld ? root.engineWorld.ffx : ({})
                        glowWeight: state.gain || 0
                        hazeWeight: state.haze || 0
                        ghost: state.ghost || false
                        underwaterWave: state.wave || false
                        timeSeconds: originalWorldPage.timeSeconds
                        viewportWidth: view3d.explicitTextureWidth
                        viewportHeight: view3d.explicitTextureHeight
                        waveTexture: root.originalWorldActive && root.surfaceHost
                            && typeof root.surfaceHost.gameEngineImportedWaveTexture === "function"
                            ? root.surfaceHost.gameEngineImportedWaveTexture() : null
                    }

                    PaintedClayMaterial {
                        id: floraMaterial
                        uSurfaceKind: 1
                    }

                    PaintedClayMaterial {
                        id: paintedArchitectureMaterial
                    }

                    PaintedClayMaterial {
                        id: paintedRoadMaterial
                        uSurfaceKind: 2
                    }

                    CustomMaterial {
                        id: inlandWaterMaterial
                        shadingMode: CustomMaterial.Shaded
                        vertexShader: "../shaders/gg-inland-water.vert"
                        fragmentShader: "../shaders/gg-inland-water.frag"
                        property real uTime: root.number(root.player.time_s, 0)
                        property color uWaterTint: root.atmosphere.waterTint
                        property TextureInput waterMap: TextureInput {
                            texture: Texture {
                                source: "../assets/authored/world/textures/clay-v4/water.png"
                                generateMipmaps: true
                                tilingModeHorizontal: Texture.Repeat
                                tilingModeVertical: Texture.Repeat
                            }
                        }
                        cullMode: Material.NoCulling
                    }

                    Repeater3D {
                        model: root.surfaceHost && root.surfaceHost.gameEngineLandscape
                            ? root.surfaceHost.gameEngineLandscape() : null
                        delegate: Model {
                            required property var treeGeometry
                            required property var treeInstances
                            required property int treeLod
                            required property int treeCount
                            required property string treeKey
                            required property bool treeResident
                            objectName: "gameLandscapeBatch"
                            geometry: treeGeometry
                            instancing: treeInstances
                            instancingLodMax: -1
                            readonly property bool waterPage: treeKey.indexOf("/road-water-") >= 0
                            materials: waterPage ? [inlandWaterMaterial] : [paintedArchitectureMaterial]
                            visible: !root.originalWorldActive && treeResident && root.paneLive && !root.dosFallbackActive && treeCount > 0
                            castsShadows: root.shadowMappingEnabled && !waterPage
                            receivesShadows: root.shadowMappingEnabled && !waterPage
                        }
                    }

                    // Fixed map placements. The camera clips these models at
                    // the same far plane as land/buildings. Sector/species
                    // buffers persist when the shared LOD mesh changes.
                    Repeater3D {
                        model: root.surfaceHost && root.surfaceHost.gameEngineWorldTrees
                            ? root.surfaceHost.gameEngineWorldTrees() : null
                        delegate: Model {
                            required property var treeGeometry
                            required property var treeInstances
                            required property int treeLod
                            required property int treeCount
                            required property string treeKey
                            required property bool treeResident
                            objectName: "gameWorldTreeBatch"
                            pickable: root.assetEditorMode
                            geometry: treeGeometry
                            instancing: treeInstances
                            readonly property real nearDistance: root.render.profile === "POTATO" ? 128 : 256
                            readonly property real midDistance: root.render.profile === "POTATO" ? 512 : 1024
                            instancingLodMin: treeLod === 0 ? 0 : treeLod === 1 ? nearDistance : midDistance
                            instancingLodMax: treeLod === 0 ? Math.min(nearDistance,root.renderFarClipM)
                                : treeLod === 1 ? Math.min(midDistance,root.renderFarClipM) : root.renderFarClipM
                            materials: [floraMaterial]
                            visible: !root.originalWorldActive && treeResident && root.floraEnabled && root.paneLive
                                && !root.dosFallbackActive && treeCount > 0
                            castsShadows: root.shadowMappingEnabled && treeLod === 0
                            receivesShadows: root.shadowMappingEnabled && treeLod < 2
                        }
                    }

                    // Saved towns, landmarks and road pages share terrain
                    // range. Their scene nodes survive turning away/returning.
                    GroundCoverMaterial {
                        id: grassCardMaterial
                        imageSource: "../assets/authored/world/ground-cover/tuft.png"
                        uCameraRight: root.groundCoverRight
                        uTime: root.number(root.player.time_s,0)
                    }
                    GroundCoverMaterial {
                        id: fernCardMaterial
                        imageSource: "../assets/authored/world/ground-cover/fern-card.png"
                        uCameraRight: root.groundCoverRight
                        uTime: root.number(root.player.time_s,0)
                    }
                    GroundCoverMaterial {
                        id: flowerCardMaterial
                        imageSource: "../assets/authored/world/ground-cover/flowers-card.png"
                        uCameraRight: root.groundCoverRight
                        uTime: root.number(root.player.time_s,0)
                    }
                    GroundCoverMaterial {
                        id: leafCardMaterial
                        imageSource: "../assets/authored/world/ground-cover/leaves-card.png"
                        uCameraRight: root.groundCoverRight
                        uTime: root.number(root.player.time_s,0)
                    }
                    Repeater3D {
                        model: root.surfaceHost && root.surfaceHost.gameEngineGroundCover
                            ? root.surfaceHost.gameEngineGroundCover() : null
                        delegate: Model {
                            required property var treeGeometry
                            required property var treeInstances
                            required property int treeLod
                            required property int treeCount
                            required property string treeKey
                            required property bool treeResident
                            objectName: "gameCosmeticGroundCoverBatch"
                            pickable: root.assetEditorMode
                            geometry: treeGeometry
                            instancing: treeInstances
                            instancingLodMax: root.render.profile === "POTATO" ? 64
                                : root.render.profile === "PS2_CLASSIC" ? 128
                                : root.render.profile === "CINEMATIC" ? 224
                                : root.render.profile === "MODERN" ? 192 : 160
                            visible: !root.originalWorldActive && treeResident && root.floraEnabled && root.paneLive
                                && !root.dosFallbackActive && treeCount>0
                            castsShadows: false
                            receivesShadows: root.shadowMappingEnabled
                            materials: treeKey.indexOf("/fern-card")>=0 ? [fernCardMaterial]
                                : treeKey.indexOf("/flowers-card")>=0 ? [flowerCardMaterial]
                                : treeKey.indexOf("/leaves-card")>=0 ? [leafCardMaterial] : [grassCardMaterial]
                        }
                    }
                    Repeater3D {
                        model: root.surfaceHost && root.surfaceHost.gameEngineWorldPlaces
                            ? root.surfaceHost.gameEngineWorldPlaces() : null
                        delegate: Model {
                            required property var treeGeometry
                            required property var treeInstances
                            required property int treeLod
                            required property int treeCount
                            required property string treeKey
                            required property bool treeResident
                            objectName: "gameWorldPlaceBatch"
                            readonly property bool roadPage: treeKey.indexOf("/road-") >= 0
                            pickable: root.assetEditorMode
                            geometry: treeGeometry
                            instancing: treeInstances
                            readonly property real nearDistance: root.render.profile === "POTATO" ? 128 : 256
                            readonly property real midDistance: root.render.profile === "POTATO" ? 512 : 1024
                            instancingLodMin: treeLod === 0 ? 0 : treeLod === 1 ? nearDistance : midDistance
                            instancingLodMax: roadPage ? -1 : treeLod === 0 ? Math.min(nearDistance,root.renderFarClipM)
                                : treeLod === 1 ? Math.min(midDistance,root.renderFarClipM) : root.renderFarClipM
                            materials: roadPage ? [paintedRoadMaterial]
                                : treeKey.indexOf("/lantern")>=0 ? [paintedLampMaterial] : [paintedArchitectureMaterial]
                            visible: !root.originalWorldActive && treeResident && root.paneLive && !root.dosFallbackActive && treeCount > 0
                            castsShadows: root.shadowMappingEnabled && treeLod === 0 && !roadPage
                            receivesShadows: root.shadowMappingEnabled && treeLod < 2
                        }
                    }

                    // Stable species/LOD slots, one native GPU table per mesh.
                    // Placements stay in the backend cache, not in frame JSON
                    // or one scene Node/RuntimeLoader for each tree.
                    Repeater3D {
                        model: root.floraBatchKeys
                        delegate: Model {
                            id: floraBatch
                            pickable: true
                            property bool isNatureBatch: false
                            required property string modelData
                            objectName: "gameFloraBatch"
                            readonly property string batchKey: modelData
                            readonly property int batchRevision: root.ecologyRevision
                                + root.assetEditorRevision
                            readonly property int plantCount:
                                Math.floor(root.number((root.ecology.groups || ({}))[batchKey], 0))
                            property var sharedMesh: null
                            property var instanceTable: null
                            function refreshBatch() {
                                if (!root.surfaceHost || plantCount <= 0
                                        || !root.surfaceHost.gameEngineFloraGeometry
                                        || !root.surfaceHost.gameEngineFloraInstances)
                                    return
                                if (sharedMesh === null)
                                    sharedMesh = root.surfaceHost.gameEngineFloraGeometry(batchKey)
                                instanceTable = root.surfaceHost.gameEngineFloraInstances(batchKey)
                            }
                            onBatchRevisionChanged: Qt.callLater(refreshBatch)
                            onPlantCountChanged: Qt.callLater(refreshBatch)
                            Component.onCompleted: Qt.callLater(refreshBatch)
                            Connections {
                                target: root
                                function onSurfaceHostChanged() { Qt.callLater(floraBatch.refreshBatch) }
                            }
                            geometry: sharedMesh
                            instancing: instanceTable
                            materials: [floraMaterial]
                            visible: !root.originalWorldActive && root.floraEnabled && root.paneLive && !root.dosFallbackActive && plantCount > 0
                                && sharedMesh !== null && instanceTable !== null
                            castsShadows: root.shadowMappingEnabled && batchKey.endsWith(":0")
                                && ["oak","oak_arch","pine","jungle","palm","mangrove","deadwood"].indexOf(batchKey.split(":")[0].split("-v")[0]) >= 0
                            receivesShadows: root.shadowMappingEnabled
                        }
                    }

                    Repeater3D {
                        model: root.natureBatchKeys
                        delegate: Model {
                            id: natureBatch
                            pickable: true
                            property string batchKey: modelData
                            property bool isNatureBatch: true
                            required property string modelData
                            objectName: "gameNatureBatch"
                            readonly property int batchRevision: root.natureRevision
                                + root.assetEditorRevision
                            readonly property int instanceCount: root.number((root.nature.groups || ({}))[modelData],0)
                            property var sharedMesh: null
                            property var instanceTable: null
                            function refreshBatch() {
                                if (instanceCount <= 0 || !root.surfaceHost
                                        || !root.surfaceHost.gameEngineNatureGeometry
                                        || !root.surfaceHost.gameEngineNatureInstances) return
                                if (sharedMesh === null) sharedMesh = root.surfaceHost.gameEngineNatureGeometry(modelData)
                                instanceTable = root.surfaceHost.gameEngineNatureInstances(modelData)
                            }
                            onInstanceCountChanged: Qt.callLater(refreshBatch)
                            Component.onCompleted: Qt.callLater(refreshBatch)
                            Connections {
                                target: root
                                function onSurfaceHostChanged() { Qt.callLater(natureBatch.refreshBatch) }
                            }
                            geometry: sharedMesh
                            instancing: instanceTable
                            materials: [floraMaterial]
                            visible: !root.originalWorldActive && root.paneLive && !root.dosFallbackActive && instanceCount > 0
                                && sharedMesh !== null && instanceTable !== null
                            receivesShadows: root.shadowMappingEnabled
                        }
                    }

                    RuntimeLoader {
                        id: sandoverIslandTerrainLoader
                        onStatusChanged: if (status===RuntimeLoader.Success && root.surfaceHost.gameEngineEnablePicking)
                            root.surfaceHost.gameEngineEnablePicking(this,'')
                        objectName: "gameSandoverIslandTerrainLoader"
                        source: Qt.resolvedUrl(
                            "../assets/authored/world/gg-sandover-island-terrain.glb"
                        )
                        visible: !root.originalWorldActive && root.sandoverIslandTerrainVisible
                        scale: Qt.vector3d(
                            root.worldLayoutScale,
                            root.worldFeelScale,
                            root.worldLayoutScale
                        )
                    }

                    RuntimeLoader {
                        id: sandoverIslandEnvironmentLoader
                        onStatusChanged: if (status===RuntimeLoader.Success && root.surfaceHost.gameEngineEnablePicking)
                            root.surfaceHost.gameEngineEnablePicking(this,'')
                        objectName: "gameSandoverIslandEnvironmentLoader"
                        source: Qt.resolvedUrl(
                            root.largeEnvironment
                                ? "../assets/authored/world/gg-sandover-island-environment-coastal-v3.glb"
                                : "../assets/authored/world/gg-sandover-island-environment.glb"
                        )
                        visible: !root.originalWorldActive && !root.dosFallbackActive && root.paneLive
                        scale: Qt.vector3d(
                            root.worldPropScale,
                            root.worldPropScale,
                            root.worldPropScale
                        )
                    }

                    // Each bird has its own skinned flight path inside this
                    // mesh. World cells only place the authored bird groups;
                    // fish schools and sparse clouds keep their group motion.
                    Repeater3D {
                        id: faunaBirdRepeater
                        model: root.nature.schema ? 0 : 3
                        delegate: RuntimeLoader {
                            required property int index
                            objectName: "gameSandoverBirdFlock"
                            source: Qt.resolvedUrl(
                                "../assets/authored/world/gg-sandover-bird-flock.glb"
                            )
                            property var group: {
                                var rows = root.fauna.birds || []
                                return index < rows.length ? rows[index] : ({})
                            }
                            visible: !root.originalWorldActive && root.paneLive
                                && root.sandoverIslandEnvironmentReady
                                && !root.dosFallbackActive
                                && group.x !== undefined
                            position: Qt.vector3d(
                                root.number(group.x, 0),
                                root.planetRenderY(
                                    root.number(group.x, 0),
                                    root.number(group.y, 12),
                                    root.number(group.z, 0)
                                ),
                                root.number(group.z, 0)
                            )
                            eulerRotation.y: root.number(group.yaw, 0) * 57.2957795
                            scale: Qt.vector3d(
                                root.number(group.scale, 1),
                                root.number(group.scale, 1),
                                root.number(group.scale, 1)
                            )
                            onStatusChanged: root.refreshSandoverLifeClips()
                        }
                    }
                    Repeater3D {
                        id: faunaFishRepeater
                        model: root.nature.schema ? 0 : 8
                        delegate: RuntimeLoader {
                            required property int index
                            objectName: "gameSandoverFishSchool"
                            source: Qt.resolvedUrl(
                                "../assets/authored/world/gg-sandover-fish-school.glb"
                            )
                            property var group: {
                                var rows = root.fauna.fish || []
                                return index < rows.length ? rows[index] : ({})
                            }
                            visible: !root.originalWorldActive && root.paneLive
                                && root.sandoverIslandEnvironmentReady
                                && !root.dosFallbackActive
                                && group.x !== undefined
                            position: Qt.vector3d(
                                root.number(group.x, 0),
                                root.planetRenderY(
                                    root.number(group.x, 0),
                                    root.number(group.y, 0.2),
                                    root.number(group.z, 0)
                                ),
                                root.number(group.z, 0)
                            )
                            eulerRotation.y: root.number(group.yaw, 0) * 57.2957795
                            scale: Qt.vector3d(
                                root.number(group.scale, 1),
                                root.number(group.scale, 1),
                                root.number(group.scale, 1)
                            )
                            onStatusChanged: root.refreshSandoverLifeClips()
                        }
                    }
                    Repeater3D {
                        id: faunaCloudRepeater
                        model: 2
                        delegate: RuntimeLoader {
                            required property int index
                            objectName: "gameSandoverCloudBank"
                            readonly property var motion: group.motion || ({})
                            readonly property real cloudTime: root.number(root.player.time_s,0)
                            readonly property real cloudAngle: cloudTime*root.number(motion.rate,0)+root.number(motion.phase,0)
                            readonly property real cloudX: motion.anchor_x !== undefined
                                ? motion.anchor_x+Math.cos(cloudAngle)*motion.radius : root.number(group.x,0)
                            readonly property real cloudZ: motion.anchor_z !== undefined
                                ? motion.anchor_z+Math.sin(cloudAngle)*motion.radius : root.number(group.z,0)
                            readonly property real cloudY: motion.altitude !== undefined
                                ? motion.altitude+Math.sin(cloudTime*motion.bob_rate+motion.bob_phase)*.35 : root.number(group.y,24)
                            source: Qt.resolvedUrl(
                                index % 4 === 0 ? "../assets/authored/world/gg-sandover-cloud-bank.glb"
                                : "../assets/authored/variants/world/gg-sandover-cloud-bank-v" + (index % 4) + ".glb"
                            )
                            property var group: {
                                var rows = root.fauna.clouds || []
                                return index < rows.length ? rows[index] : ({})
                            }
                            visible: !root.originalWorldActive && root.paneLive
                                && root.sandoverIslandEnvironmentReady
                                && !root.dosFallbackActive
                                && group.x !== undefined
                            position: Qt.vector3d(
                                cloudX,
                                root.planetRenderY(
                                    cloudX,cloudY,cloudZ
                                ),
                                cloudZ
                            )
                            eulerRotation.y: motion.rate !== undefined ? -cloudAngle*57.2957795 : root.number(group.yaw,0)*57.2957795
                            scale: Qt.vector3d(
                                root.number(group.scale, 1),
                                root.number(group.scale, 1),
                                root.number(group.scale, 1)
                            )
                        }
                    }

                    // One material object per look, not one per Model.  Same
                    // sun, same albedo; the Repeater must not allocate a new
                    // PBR material for every palm, hut and terrain cell.
                    PaintedClayMaterial {
                        id: clayPropMaterial
                        objectName: "gameClayPropMaterial"
                    }
                    PaintedClayMaterial {
                        id: paintedLampMaterial
                        uLampEmission: 1
                    }
                    PaintedClayMaterial {
                        id: clayCharacterMaterial
                        objectName: "gameClayCharacterMaterial"
                        uSurfaceKind: 3
                    }
                    PaintedClayMaterial {
                        id: terrainSurfaceMaterial
                        objectName: "gameTerrainVertexColorMaterial"
                        uSurfaceKind: 2
                    }
                    AdventureFxMaterial {
                        id: clayParticleMaterial
                        objectName: "gameParticleVertexColorMaterial"
                        uEnergy: 0.72
                        uTime: root.number(root.player.time_s,0)
                        uFogNear: root.distanceFog.near
                        uFogFar: root.distanceFog.far
                        uBeaconFar: root.lightBeaconRangeM
                        uEnchantMatrix0: root.enchantMesh0 ? root.enchantMesh0.sceneTransform : Qt.matrix4x4()
                        uEnchantMatrix1: root.enchantMesh1 ? root.enchantMesh1.sceneTransform : Qt.matrix4x4()
                        uCameraPosition: camera.position
                    }
                    AdventureFxMaterial {
                        id: luminousParticleMaterial
                        objectName: "gameAdditiveParticleMaterial"
                        additive: true
                        uTime: root.number(root.player.time_s,0)
                        uFogNear: root.distanceFog.near
                        uFogFar: root.distanceFog.far
                        uBeaconFar: root.lightBeaconRangeM
                        uEnchantMatrix0: root.enchantMesh0 ? root.enchantMesh0.sceneTransform : Qt.matrix4x4()
                        uEnchantMatrix1: root.enchantMesh1 ? root.enchantMesh1.sceneTransform : Qt.matrix4x4()
                        uCameraPosition: camera.position
                    }
                    PrincipledMaterial {
                        id: terrainHlodGrassMaterial
                        baseColor: "#5a8c3c"
                        roughness: 0.94
                        specularAmount: 0.08
                    }
                    PrincipledMaterial {
                        id: terrainHlodBeachMaterial
                        baseColor: "#efd090"
                        roughness: 0.94
                        specularAmount: 0.08
                    }
                    PrincipledMaterial {
                        id: terrainHlodCliffMaterial
                        baseColor: "#9e653b"
                        roughness: 0.94
                        specularAmount: 0.08
                    }
                    PrincipledMaterial {
                        id: terrainHlodReefMaterial
                        baseColor: "#43b49c"
                        roughness: 0.82
                        specularAmount: 0.08
                    }
                    PrincipledMaterial {
                        id: terrainHlodShallowWaterMaterial
                        baseColor: "#39b7c1"
                        roughness: 0.58
                        specularAmount: 0.12
                    }
                    PrincipledMaterial {
                        id: terrainHlodDeepWaterMaterial
                        baseColor: "#1e7185"
                        roughness: 0.62
                        specularAmount: 0.10
                    }
                    CustomMaterial {
                        id: seaPlaneMaterial
                        shadingMode: CustomMaterial.Shaded
                        vertexShader: "../shaders/gg-sea.vert"
                        fragmentShader: "../shaders/gg-sea.frag"
                        property real uTime: root.number(root.player.time_s,0)
                        property real uSea: root.number((root.terrain.water || {}).sea_level_m,0)
                        property real uPlanet: 1000000
                        property real uBedExtent: 600
                        property color uWaterTint: root.atmosphere.waterTint
                        property TextureInput seaMap: TextureInput {
                            texture: Texture {
                                source: "../assets/authored/world/textures/clay-v4/water.png"
                                generateMipmaps: true
                                tilingModeHorizontal: Texture.Repeat
                                tilingModeVertical: Texture.Repeat
                            }
                        }
                        property TextureInput seaBed: TextureInput {
                            texture: Texture {
                                textureData: root.surfaceHost && root.surfaceHost.gameEngineSeaBedField
                                    ? root.surfaceHost.gameEngineSeaBedField() : null
                                minFilter: Texture.Linear
                                magFilter: Texture.Linear
                            }
                        }
                        sourceBlend: CustomMaterial.SrcAlpha
                        destinationBlend: CustomMaterial.OneMinusSrcAlpha
                        depthDrawMode: Material.OpaqueOnlyDepthDraw
                        cullMode: Material.BackFaceCulling
                    }
                    Model {
                        id: planetWaterSurface
                        objectName: "gamePlanetWaterHorizon"
                        source: ""
                        geometry: root.surfaceHost
                            && typeof root.surfaceHost.gameEnginePlanetWaterGeometry
                                === "function"
                            ? root.surfaceHost.gameEnginePlanetWaterGeometry()
                            : null
                        visible: !root.originalWorldActive && Boolean(root.terrain.water)
                        // Vertices are already world XZ. Do not add the player
                        // position or the sea slides off the island.
                        position: Qt.vector3d(
                            root.number(root.player.x,0),
                            root.number(root.terrain.water
                                ? root.terrain.water.sea_level_m : 0, 0),
                            root.number(root.player.z,0)
                        )
                        castsShadows: false
                        receivesShadows: false
                        materials: [seaPlaneMaterial]
                    }

                    Model {
                        id: waterSurface
                        source: ""
                        geometry: root.waterWaveGeometry
                        visible: !root.originalWorldActive && Boolean(root.terrain.water)
                            && Boolean(root.waterWaveGeometry)
                        // World-space vertices. Keep this at the origin.
                        position: Qt.vector3d(
                            root.number(root.player.x,0),
                            root.number(root.terrain.water
                                ? root.terrain.water.sea_level_m : 0, 0),
                            root.number(root.player.z,0)
                        )
                        // Metre-sized native geometry. The 0.01 primitive scale
                        // would shrink the sea disk to a puddle.
                        scale: Qt.vector3d(1, 1, 1)
                        castsShadows: false
                        receivesShadows: false
                        materials: [seaPlaneMaterial]
                    }

                    Repeater3D {
                        model: terrainRenderModel

                        delegate: Model {
                            id: terrainModel
                            pickable: true
                            objectName: "terrainPatchModel"
                            required property string terrainRowJson
                            readonly property var terrainRow: JSON.parse(terrainRowJson)
                            property var modelData: terrainModel.terrainRow
                            property var center: terrainModel.modelData.center_m || ({})
                            property var bounds: terrainModel.modelData.bounds_m || ({})
                            property int vertexGrid: Math.max(
                                1,
                                Math.floor(root.number(
                                    terrainModel.modelData.geometry
                                        ? terrainModel.modelData.geometry.vertex_grid
                                        : 1,
                                    1
                                ))
                            )
                            property var patchGeometry: {
                                // Reading the grid makes this binding refresh
                                // when an authored patch changes in place.
                                var heightGrid = terrainModel.modelData.height_grid_m
                                var key = String(terrainModel.modelData.key || "")
                                var revision = root.terrainGeometryRevision
                                if (!heightGrid
                                    || terrainModel.vertexGrid <= 1
                                    || !key
                                    || revision < 0
                                    || !root.surfaceHost
                                    || !root.surfaceHost.gameEngineTerrainGeometry)
                                    return null
                                return root.surfaceHost.gameEngineTerrainGeometry(key)
                            }
                            property var visibilityData:
                                terrainModel.modelData.visibility || ({})
                            property string biome: String(
                                terrainModel.modelData.biome || "LAND"
                            )
                            property bool waterCell:
                                String(terrainModel.modelData.surface || "LAND") === "WATER"
                            source: ""
                            geometry: terrainModel.patchGeometry
                            castsShadows: root.shadowMappingEnabled
                                && !terrainModel.waterCell
                                && Boolean(terrainModel.visibilityData.shadow_caster)
                            receivesShadows: root.shadowMappingEnabled
                                && Boolean(terrainModel.visibilityData.shadow_caster)
                            visible: !root.originalWorldActive && root.cinematic.preset !== "ORBIT_WORLD_SCALE"
                                && Boolean(terrainModel.visibilityData.render)
                                && !root.planetSurfaceAssetVisible
                                && !root.sandoverTerrainCellCoveredByBlender(
                                    terrainModel.modelData
                                )
                            position: Qt.vector3d(
                                root.number(terrainModel.bounds.min_x,
                                    root.number(terrainModel.center.x, 0)),
                                root.planetRenderY(
                                    root.number(terrainModel.bounds.min_x,
                                        root.number(terrainModel.center.x, 0)),
                                    0,
                                    root.number(terrainModel.bounds.min_z,
                                        root.number(terrainModel.center.z, 0))
                                ),
                                root.number(terrainModel.bounds.min_z,
                                    root.number(terrainModel.center.z, 0))
                            )
                            materials: [
                                root.terrainMaterialFor(
                                    terrainModel.biome,
                                    terrainModel.waterCell
                                )
                            ]

                            // ORBIT cells intentionally carry no dense
                            // height grid.  They still need a real visual
                            // representation, otherwise increasing the
                            // interest radius only creates an invisible
                            // horizon.  This thin tile is the bounded HLOD
                            // representation of that authoritative cell;
                            // nearby cells continue to use the heightfield
                            // mesh above.
                            Model {
                                objectName: "terrainHlodTileModel"
                                visible: !root.originalWorldActive && root.cinematic.preset !== "ORBIT_WORLD_SCALE"
                                    && Boolean(terrainModel.visibilityData.render)
                                    && !root.planetSurfaceAssetVisible
                                    && terrainModel.vertexGrid <= 1
                                source: "#Cube"
                                position: Qt.vector3d(
                                    root.terrainCellSize * 0.5,
                                    root.number(terrainModel.center.y, 0),
                                    root.terrainCellSize * 0.5
                                )
                                scale: Qt.vector3d(
                                    root.terrainCellSize * root.sceneScale,
                                    0.025 * root.sceneScale,
                                    root.terrainCellSize * root.sceneScale
                                )
                                castsShadows: false
                                receivesShadows: root.shadowMappingEnabled
                                    && Boolean(terrainModel.visibilityData.shadow_caster)
                                materials: [
                                    root.terrainHlodMaterialFor(
                                        terrainModel.biome
                                    )
                                ]
                            }
                        }
                    }

                    Model {
                        id: terrainTargetMarker
                        source: "#Cube"
                        property var targetCenter:
                            root.terrainTargetCell.center_m || ({})
                        property bool targetIsWater:
                            String(root.terrainTargetCell.surface || "LAND")
                            === "WATER"
                        visible: !root.originalWorldActive && root.cinematic.preset !== "ORBIT_WORLD_SCALE"
                            && root.terrainTargetSelected
                            && Boolean(root.terrainTargetCell.key)
                        position: Qt.vector3d(
                            root.terrainBrushX,
                            terrainTargetMarker.targetIsWater
                                ? root.number(root.terrain.water
                                    ? root.terrain.water.sea_level_m : 0, 0)
                                    + 0.22
                                : root.number(terrainTargetMarker.targetCenter.y,
                                    0) + 0.45,
                            root.terrainBrushZ
                        )
                        scale: Qt.vector3d(
                            root.terrainBrushRadius * 2 * root.sceneScale,
                            0.16 * root.sceneScale,
                            root.terrainBrushRadius * 2 * root.sceneScale
                        )
                        materials: [
                            PrincipledMaterial {
                                baseColor: root.terrainBrushEnabled
                                    ? "#e3bd63" : "#d6e1a0"
                                roughness: 0.38
                                metalness: 0.12
                            }
                        ]
                    }

                    Repeater3D {
                        model: entityRenderModel

                        delegate: Node {
                            id: entityModel
                            property string worldEntityId: String(entityModel.modelData.id || '')
                            readonly property bool originalActorRequested: !!root.originalWorldActors
                                && root.originalWorldActors.requestedIds.indexOf(worldEntityId) >= 0
                            property bool nativeVisible: true
                            Component.onCompleted: if (root.surfaceHost && root.surfaceHost.gameEngineRegisterEntityNode)
                                root.surfaceHost.gameEngineRegisterEntityNode(entityModel,worldEntityId)
                            objectName: "gameEntityFigure"
                            required property string entityRowJson
                            required property string entityDynamicJson
                            readonly property var entityRow: JSON.parse(entityRowJson)
                            readonly property var entityDynamic: JSON.parse(entityDynamicJson)
                            property var modelData: entityModel.entityRow
                            property var dynamicData:
                                entityModel.entityDynamic || entityModel.entityRow
                            visible: !Boolean(entityModel.dynamicData.hidden) && nativeVisible && !originalActorRequested
                                && !(entityModel.entityKind === "PLAYER" && root.firstPersonView)
                                && !(root.originalWorldActive && !entityModel.entityAsset.editor_model
                                     && ["TREE","HOUSE","ROCK","PROP","RAMP"].indexOf(entityModel.entityKind)>=0)
                            property string entityKind: String(
                                entityModel.modelData.kind || "PROP"
                            )
                            property color tint: String(
                                entityModel.modelData.color || "#8fa8a0"
                            )
                            property bool characterLike: entityModel.entityKind === "PLAYER"
                                || entityModel.entityKind === "NPC"
                                || entityModel.entityKind === "ACTOR"
                                || entityModel.entityKind.indexOf("NPC") >= 0
                            property real entitySx: Math.max(
                                0.01,
                                root.number(entityModel.modelData.sx, 1)
                            )
                            property real entitySy: Math.max(
                                0.01,
                                root.number(entityModel.modelData.sy, 1)
                            )
                            property real entitySz: Math.max(
                                0.01,
                                root.number(entityModel.modelData.sz, 1)
                            )
                            property real characterYScale: Math.max(
                                0.01,
                                entityModel.entityAsset.editor_scale ? entityModel.entitySy : Math.max(.9,Math.min(1.25, entityModel.entitySy))
                            )
                            property var entityPose: entityModel.dynamicData.animation
                                || ({})
                            property var entityAsset: entityModel.modelData.asset
                                || ({})
                            property var entityAssetMotion:
                                entityModel.dynamicData.asset
                                || entityModel.entityAsset
                                || ({})
                            property var itemState: entityModel.dynamicData.item
                                || ({})
                            property var itemVisual: {
                                var visual=Object.assign({},entityModel.itemState.visual || ({}))
                                if (entityModel.itemState.location==='GROUND') {
                                    var clock=root.number(root.player.time_s,0)
                                    visual.bob_m=Math.sin(clock*1.7+root.number(entityModel.itemState.visual_phase,0))*root.number(visual.float_m,0)
                                    visual.rotation_y=root.number(visual.rotation ? visual.rotation[1] : 0,0)+clock*root.number(visual.spin_deg_s,0)
                                }
                                return visual
                            }
                            property var itemAsset: entityModel.itemState.asset
                                || ({})
                            property bool itemLike: entityModel.entityKind === "GROUND_ITEM"
                                || entityModel.entityKind === "CHEST"
                            // All non-authored item families resolve to one
                            // cached native clay mesh. The geometry key is
                            // data-driven by the item table, not by a QML
                            // primitive name, so a weapon/chest/loot object
                            // cannot silently regress to a cube.
                            property var itemGeometry:
                                entityModel.itemLike
                                && root.surfaceHost
                                && typeof root.surfaceHost
                                    .gameEngineItemGeometry === "function"
                                    ? root.surfaceHost.gameEngineItemGeometry(
                                        String(
                                            entityModel.itemAsset.geometry_key
                                                || entityModel.itemVisual.asset_id
                                                || "item.unknown"
                                        ),
                                        String(
                                            entityModel.itemAsset.asset_class
                                                || entityModel.itemState.kind
                                                || entityModel.entityKind
                                        )
                                    ) : null
                            property bool authoredWorldProp:
                                !entityModel.characterLike
                                && !entityModel.itemLike
                                && String(entityModel.entityAsset.mode || "")
                                    === "AUTHORED_STATIC"
                                && String(entityModel.entityAsset.source || "") !== ""
                            property bool sandoverEnvironmentEntity:
                                !entityModel.entityAsset.editor_model && root.sandoverEntityBakedByEnvironment(
                                    entityModel.entityAsset.asset_id,
                                    entityModel.entityKind,
                                    entityModel.dynamicData.x,
                                    entityModel.dynamicData.z
                                )
                            property string authoredWorldSource: {
                                var uri = String(entityModel.entityAsset.source || "")
                                if (uri.indexOf("file:") === 0 || uri.indexOf("/") === 0)
                                    return uri
                                var relative = String(
                                    entityModel.entityAsset.relative_source || ""
                                )
                                if (relative.length > 0)
                                    return Qt.resolvedUrl("../" + relative)
                                return uri
                            }
                            property var authoredWorldRuntimeLoader:
                                authoredWorldLoader.item || null
                            property bool authoredWorldVisible:
                                entityModel.authoredWorldProp
                                && !entityModel.sandoverEnvironmentEntity
                                && !Boolean(entityModel.worldPropGeometry)
                                && root.runtimeLoaderHasVisualContent(
                                    entityModel.authoredWorldRuntimeLoader
                                )
                            property var worldPropGeometry:
                                !entityModel.characterLike
                                && !entityModel.itemLike
                                && !entityModel.entityAsset.editor_model
                                && !entityModel.sandoverEnvironmentEntity
                                && root.surfaceHost
                                && typeof root.surfaceHost
                                    .gameEngineWorldPropGeometry === "function"
                                ? root.surfaceHost.gameEngineWorldPropGeometry(
                                    String(
                                        entityModel.entityAsset.geometry_key
                                            || entityModel.entityKind
                                    ),
                                    String(
                                        entityModel.entityAsset.variant
                                            !== undefined
                                            ? entityModel.entityAsset.variant
                                            : (entityModel.modelData.id || "0")
                                    )
                                ) : null
                            // QtQuick3D resolves Model.source once during
                            // delegate construction.  The host is attached
                            // immediately after the root is created, so the
                            // first evaluation may still be the primitive
                            // path even though the cache is already ready.
                            // Apply the real geometry at the change boundary
                            // as well; this is a presentation binding only
                            // and never creates a second visual object.
                            function applyNativeGeometry(model, geometry) {
                                if (!model || !geometry)
                                    return
                                model.source = ""
                                model.geometry = geometry
                            }
                            onItemGeometryChanged: {
                                if (itemGeometry)
                                    entityModel.applyNativeGeometry(
                                        gameWorldItemModel,
                                        itemGeometry
                                    )
                            }
                            onWorldPropGeometryChanged: {
                                if (worldPropGeometry)
                                    entityModel.applyNativeGeometry(
                                        gameEntityProxyModel,
                                        worldPropGeometry
                                    )
                            }
                            property string lodTier: String(
                                entityModel.dynamicData.lod || "NEAR"
                            )
                            property var equipment: entityModel.modelData.equipment
                                || []
                            property var equippedVisual: entityModel.equipment.length > 0
                                && entityModel.equipment[0]
                                ? (entityModel.equipment[0].visual || ({}))
                                : ({})
                            // Resolve every character to the nine approved crew files,
                            // including historical snapshots from an older desktop.
                            // Loading/animation failures never restore a prototype body.
                            property string authoredCharacterSource: root.crewSource(
                                entityModel.entityAsset, String(entityModel.modelData.id || ""), entityModel.entityKind)
                            property bool authoredAssetEligible: entityModel.characterLike
                                && !entityModel.originalActorRequested
                                && root.number(entityModel.entityAsset.instance_rank, 0) < 32
                            property bool authoredItemEligible:
                                entityModel.itemLike
                                && String(entityModel.itemAsset.mode || "")
                                    === "AUTHORED_STATIC"
                                && String(entityModel.itemAsset.source || "")
                                    !== ""
                                && root.number(
                                    entityModel.itemAsset.instance_rank,
                                    -1
                                ) >= 0
                                && root.number(
                                    entityModel.itemAsset.instance_rank,
                                    -1
                                ) < root.number(
                                    entityModel.itemAsset.instance_budget,
                                    0
                                )
                            property string authoredAssetClipStatus: String(
                                entityModel.entityAssetMotion.clip_status
                                    || entityModel.entityAsset.clip_status
                                    || "NOT_LOADED"
                            )
                            property string authoredAssetClip: String(
                                entityModel.entityAssetMotion.clip
                                    || entityModel.entityAsset.clip
                                    || ""
                            )
                            property string authoredAssetRuntimeClip: String(
                                entityModel.entityAssetMotion.runtime_clip
                                    || entityModel.entityAsset.runtime_clip
                                    || entityModel.authoredAssetClip
                                    || ""
                            )
                            property string requestedAuthoredClip: String(
                                root.authoredClipForMotionState(
                                    entityModel.entityPose.locomotion
                                        || entityModel.entityPose.state
                                        || "IDLE"
                                )
                            )
                            property bool authoredAssetVisualContent:
                                entityModel.authoredAssetEligible
                                && root.runtimeLoaderHasVisualContent(
                                    entityModel.authoredAssetRuntimeLoader
                                )
                            property bool authoredAssetVisible: entityModel.authoredAssetVisualContent
                            property bool authoredItemVisible:
                                entityModel.authoredItemEligible
                                && root.runtimeLoaderHasVisualContent(
                                    entityModel.authoredItemRuntimeLoader
                                )
                            property var authoredAssetRuntimeLoader:
                                authoredAssetLoader.item || null
                            property var authoredItemRuntimeLoader:
                                authoredItemLoader.item || null
                            property int authoredSocketRevision: 0
                            property real poseBob: root.number(
                                entityModel.entityPose.bob_m, 0
                            )
                            property real poseLean: root.number(
                                entityModel.entityPose.lean_deg, 0
                            )
                            property real poseSway: root.number(
                                entityModel.entityPose.sway_deg, 0
                            )
                            property real poseSquash: root.number(
                                entityModel.entityPose.squash, 0
                            )
                            property string lastRuntimeClipRequest: ""
                            property string lastRuntimeActionSerial: ""
                            property real lastRuntimeCadenceRequest: -1
                            property double lastRuntimeClipRequestAt: 0
                            function applyAuthoredRuntimeClip(force) {
                                if (!entityModel.authoredAssetEligible
                                    || !entityModel.authoredAssetRuntimeLoader
                                    || !root.surfaceHost
                                    || typeof root.surfaceHost.gameEngineRuntimeClip
                                        !== "function")
                                    return
                                var clip = String(
                                    entityModel.authoredAssetRuntimeClip || ""
                                )
                                var cadence = root.number(
                                    entityModel.entityPose.cadence_hz, 0
                                )
                                var actionSerial = String(
                                    entityModel.entityPose.action_serial || ""
                                )
                                var now = Date.now()
                                if (!force
                                    && clip === entityModel.lastRuntimeClipRequest
                                    && actionSerial === entityModel.lastRuntimeActionSerial
                                    && Math.abs(cadence
                                        - entityModel.lastRuntimeCadenceRequest) < 0.12
                                    && now - entityModel.lastRuntimeClipRequestAt < 260)
                                    return
                                root.surfaceHost.gameEngineRuntimeClip(
                                    entityModel.authoredAssetRuntimeLoader,
                                    clip,
                                    cadence,
                                    actionSerial
                                )
                                entityModel.lastRuntimeClipRequest = clip
                                entityModel.lastRuntimeActionSerial = actionSerial
                                entityModel.lastRuntimeCadenceRequest = cadence
                                entityModel.lastRuntimeClipRequestAt = now
                            }
                            onAuthoredAssetVisibleChanged:
                                entityModel.applyAuthoredRuntimeClip(true)
                            Connections {
                                target: root
                                function onAssetEditorRevisionChanged() {
                                    root.applyAssetMaterial(entityModel.authoredAssetRuntimeLoader,entityModel.worldEntityId)
                                    root.applyAssetMaterial(entityModel.authoredWorldRuntimeLoader,entityModel.worldEntityId)
                                    root.applyAssetMaterial(entityModel.authoredItemRuntimeLoader,entityModel.worldEntityId)
                                }
                            }
                            onAuthoredAssetClipChanged:
                                entityModel.applyAuthoredRuntimeClip(true)
                            onAuthoredAssetRuntimeClipChanged:
                                entityModel.applyAuthoredRuntimeClip(true)
                            onRequestedAuthoredClipChanged:
                                entityModel.applyAuthoredRuntimeClip(true)
                            onEntityPoseChanged:
                                entityModel.applyAuthoredRuntimeClip(false)
                            Connections {
                                target: entityModel.authoredAssetRuntimeLoader
                                function onStatusChanged() {
                                    entityModel.applyAuthoredRuntimeClip(true)
                                    entityModel.authoredSocketRevision += 1
                                    root.applyAssetMaterial(entityModel.authoredAssetRuntimeLoader,entityModel.worldEntityId)
                                }
                            }
                            position: Qt.vector3d(
                                root.number(entityModel.dynamicData.x, 0),
                                root.planetRenderY(
                                    root.number(entityModel.dynamicData.x, 0),
                                    root.number(entityModel.dynamicData.y, 0),
                                    root.number(entityModel.dynamicData.z, 0)
                                ),
                                root.number(entityModel.dynamicData.z, 0)
                            )
                            eulerRotation.y:
                                root.number(entityModel.dynamicData.yaw, 0)
                                * 57.2958
                            eulerRotation.x: root.number(entityModel.dynamicData.pitch, 0)
                            eulerRotation.z: root.number(entityModel.dynamicData.roll, 0)
                            // One native geometry slot serves each prop and
                            // ramp. Item fallbacks keep their named model
                            // below so the asset test and authored handoff
                            // remain explicit. This removes one hidden Model
                            // from every mixed entity delegate.
                            Model {
                                id: gameEntityProxyModel
                                pickable: true
                                objectName: "gameEntityProxyModel"
                                // ORBIT is a presentation LOD, not a vanish
                                // distance. Keep this single cheap primitive
                                // alive until Qt's camera frustum/clip plane
                                // removes it at the actual horizon.
                                visible: !entityModel.characterLike
                                    && !entityModel.itemLike
                                    && !entityModel.sandoverEnvironmentEntity
                                    && !entityModel.authoredWorldVisible
                                property bool usesNativeGeometry:
                                    Boolean(entityModel.worldPropGeometry)
                                property bool usesLowPolySphere:
                                    !Boolean(entityModel.worldPropGeometry)
                                    && entityModel.entityKind !== "RAMP"
                                source: entityModel.worldPropGeometry
                                    ? ""
                                    : (Boolean(root.lowPolySphereGeometry)
                                    && entityModel.entityKind !== "RAMP"
                                    && root.lowPolySphereGeometry
                                    ? ""
                                    : "#Cube")
                                geometry: entityModel.worldPropGeometry
                                    ? entityModel.worldPropGeometry
                                    : (Boolean(root.lowPolySphereGeometry)
                                        && entityModel.entityKind !== "RAMP"
                                        ? root.lowPolySphereGeometry : null)
                                position: Qt.vector3d(0, 0, 0)
                                eulerRotation.x: entityModel.entityKind === "RAMP"
                                    ? -12 : 0
                                scale: Qt.vector3d(
                                    entityModel.entitySx * (entityModel.worldPropGeometry ? 1 : root.sceneScale),
                                    entityModel.entitySy * (entityModel.worldPropGeometry ? 1 : root.sceneScale),
                                    entityModel.entitySz * (entityModel.worldPropGeometry ? 1 : root.sceneScale)
                                )
                                castsShadows: root.shadowMappingEnabled
                                receivesShadows: root.shadowMappingEnabled
                                materials: [clayPropMaterial]
                            }

                            Component {
                                id: authoredWorldComponent
                                RuntimeLoader {
                                    objectName: "gameAuthoredWorldLoader"
                                    source: entityModel.authoredWorldSource
                                    visible: true
                                    Component.onDestruction: {
                                        if(root.surfaceHost && typeof root.surfaceHost.gameEngineReleaseRuntimeClip === "function")
                                            root.surfaceHost.gameEngineReleaseRuntimeClip(this)
                                        root.forgetAssetMaterials(this)
                                    }
                                    onStatusChanged: if(status===RuntimeLoader.Success) {
                                        if(root.surfaceHost.gameEngineEnablePicking)root.surfaceHost.gameEngineEnablePicking(this,entityModel.worldEntityId)
                                        root.applyAssetMaterial(this,entityModel.worldEntityId)
                                    }
                                }
                            }
                            Loader3D {
                                id: authoredWorldLoader
                                objectName: "gameAuthoredWorldLoaderHost"
                                active: entityModel.authoredWorldProp
                                    && !entityModel.sandoverEnvironmentEntity
                                    && !Boolean(entityModel.worldPropGeometry)
                                asynchronous: false
                                sourceComponent: authoredWorldComponent
                                visible: entityModel.authoredWorldVisible
                                position: Qt.vector3d(
                                    0,
                                    String(entityModel.entityAsset.anchor || "") === "FEET"
                                        ? -entityModel.entitySy
                                        : 0,
                                    0
                                )
                                scale: {
                                    if(entityModel.entityAsset.editor_model)
                                        return Qt.vector3d(entityModel.entitySx,entityModel.entitySy,entityModel.entitySz)
                                    var height = Math.max(
                                        0.5,
                                        root.number(
                                            entityModel.entityAsset.height_m,
                                            4.16
                                        )
                                    )
                                    return Qt.vector3d(
                                        (2.0 * entityModel.entitySx) / height,
                                        (2.0 * entityModel.entitySy) / height,
                                        (2.0 * entityModel.entitySz) / height
                                    )
                                }
                            }

                            // Every world item has a real native 3D state. The
                            // item definition selects a cached family mesh,
                            // rarity material and a context-specific pose;
                            // ground items also receive deterministic motion.
                            Model {
                                id: gameWorldItemModel
                                pickable: true
                                objectName: "gameWorldItemModel"
                                visible: entityModel.itemLike
                                    && !entityModel.authoredItemVisible
                                property string requestedModel: String(
                                    entityModel.itemVisual.model || "#Sphere"
                                )
                                property bool usesNativeGeometry:
                                    Boolean(entityModel.itemGeometry)
                                property bool usesLowPolySphere:
                                    !Boolean(entityModel.itemGeometry)
                                    && entityModel.requestedModel === "#Sphere"
                                source: entityModel.itemGeometry
                                    ? ""
                                    : (Boolean(root.lowPolySphereGeometry)
                                    && entityModel.requestedModel === "#Sphere"
                                    && root.lowPolySphereGeometry
                                    ? ""
                                    : (entityModel.requestedModel === "#Sphere"
                                        ? "#Cube" : String(entityModel.requestedModel || "#Cube")))
                                geometry: entityModel.itemGeometry
                                    ? entityModel.itemGeometry
                                    : (Boolean(root.lowPolySphereGeometry)
                                        && entityModel.requestedModel === "#Sphere"
                                        ? root.lowPolySphereGeometry : null)
                                position: Qt.vector3d(
                                    0,
                                    root.number(
                                        entityModel.itemVisual.offset_y,
                                        0.16
                                    ) + root.number(
                                        entityModel.itemVisual.bob_m,
                                        0
                                    ),
                                    0
                                )
                                eulerRotation: Qt.vector3d(
                                    root.number(
                                        entityModel.itemVisual.rotation
                                            ? entityModel.itemVisual.rotation[0] : 0,
                                        0
                                    ),
                                    root.number(entityModel.itemVisual.rotation_y, 0),
                                    root.number(
                                        entityModel.itemVisual.rotation
                                            ? entityModel.itemVisual.rotation[2] : 0,
                                        0
                                    )
                                )
                                scale: Qt.vector3d(
                                    root.number(
                                        entityModel.itemVisual.scale
                                            ? entityModel.itemVisual.scale[0] : 0.16,
                                        0.16
                                        ) * entityModel.entitySx * (entityModel.itemGeometry ? 1 : root.sceneScale),
                                    root.number(
                                        entityModel.itemVisual.scale
                                            ? entityModel.itemVisual.scale[1] : 0.16,
                                        0.16
                                        ) * entityModel.entitySy * (entityModel.itemGeometry ? 1 : root.sceneScale),
                                    root.number(
                                        entityModel.itemVisual.scale
                                            ? entityModel.itemVisual.scale[2] : 0.16,
                                        0.16
                                        ) * entityModel.entitySz * (entityModel.itemGeometry ? 1 : root.sceneScale)
                                )
                                castsShadows: root.shadowMappingEnabled
                                receivesShadows: root.shadowMappingEnabled
                                materials: [clayPropMaterial]
                            }

                            // Static authored item meshes take over only after
                            // the nested RuntimeLoader succeeds.  Loader3D is
                            // active only for an eligible item, so ordinary
                            // entities do not carry an empty asset loader.
                            Component {
                                id: authoredItemComponent
                                RuntimeLoader {
                                    objectName: "gameAuthoredItemLoader"
                                    Component.onDestruction: {
                                        if(root.surfaceHost && typeof root.surfaceHost.gameEngineReleaseRuntimeClip === "function")
                                            root.surfaceHost.gameEngineReleaseRuntimeClip(this)
                                        root.forgetAssetMaterials(this)
                                    }
                                    onStatusChanged: if (status===RuntimeLoader.Success) {
                                        if (root.surfaceHost.gameEngineEnablePicking)
                                            root.surfaceHost.gameEngineEnablePicking(this,entityModel.worldEntityId)
                                        if (root.surfaceHost.gameEngineRegisterRig)
                                            root.surfaceHost.gameEngineRegisterRig(this,entityModel.worldEntityId)
                                        Qt.callLater(function(){root.applyAssetMaterial(authoredItemLoader.item,entityModel.worldEntityId)})
                                    }
                                    source: String(
                                        entityModel.itemAsset.source || ""
                                    )
                                    visible: true
                                }
                            }
                            Loader3D {
                                id: authoredItemLoader
                                objectName: "gameAuthoredItemLoaderHost"
                                active: entityModel.authoredItemEligible
                                asynchronous: false
                                sourceComponent: authoredItemComponent
                                visible: entityModel.authoredItemVisible
                                position: Qt.vector3d(
                                    0,
                                    root.number(
                                        entityModel.itemVisual.offset_y,
                                        0.16
                                    ) + root.number(
                                        entityModel.itemVisual.bob_m,
                                        0
                                    ),
                                    0
                                )
                                eulerRotation: Qt.vector3d(
                                    root.number(
                                        entityModel.itemVisual.rotation
                                            ? entityModel.itemVisual.rotation[0] : 0,
                                        0
                                    ),
                                    root.number(entityModel.itemVisual.rotation_y, 0),
                                    root.number(
                                        entityModel.itemVisual.rotation
                                            ? entityModel.itemVisual.rotation[2] : 0,
                                        0
                                    )
                                )
                                scale: Qt.vector3d(
                                    root.number(
                                        entityModel.itemVisual.scale
                                            ? entityModel.itemVisual.scale[0] : 0.16,
                                        0.16
                                    ) * root.number(
                                        entityModel.itemAsset.unit_scale
                                            ? entityModel.itemAsset.unit_scale[0] : 1,
                                        1
                                    ) * entityModel.entitySx,
                                    root.number(
                                        entityModel.itemVisual.scale
                                            ? entityModel.itemVisual.scale[1] : 0.16,
                                        0.16
                                    ) * root.number(
                                        entityModel.itemAsset.unit_scale
                                            ? entityModel.itemAsset.unit_scale[1] : 1,
                                        1
                                    ) * entityModel.entitySy,
                                    root.number(
                                        entityModel.itemVisual.scale
                                            ? entityModel.itemVisual.scale[2] : 0.16,
                                        0.16
                                    ) * root.number(
                                        entityModel.itemAsset.unit_scale
                                            ? entityModel.itemAsset.unit_scale[2] : 1,
                                        1
                                    ) * entityModel.entitySz
                                )
                            }

                            // Authored files enter through one bounded
                            // RuntimeLoader per eligible character.  The
                            // loader inherits the entity root transform and
                            // the existing deterministic pose accents.  A
                            // missing clip is still a valid root-only
                            // authored model, so it does not summon a second
                            // character body.
                            Component {
                                id: authoredCharacterComponent
                                RuntimeLoader {
                                    objectName: "gameAuthoredAssetLoader"
                                    Component.onDestruction: {
                                        if(root.surfaceHost && typeof root.surfaceHost.gameEngineReleaseRuntimeClip === "function")
                                            root.surfaceHost.gameEngineReleaseRuntimeClip(this)
                                        root.forgetAssetMaterials(this)
                                    }
                                    source: entityModel.authoredCharacterSource
                                    visible: true
                                    onStatusChanged: if (status===RuntimeLoader.Success) {
                                        // Imported GLB clips default to running. Own the
                                        // exact loader before its first animated frame;
                                        // Loader3D.item may not yet be bound for Connections.
                                        if(root.surfaceHost && typeof root.surfaceHost.gameEngineRuntimeClip === "function")
                                            root.surfaceHost.gameEngineRuntimeClip(this,entityModel.authoredAssetRuntimeClip,
                                                root.number(entityModel.entityPose.cadence_hz,0),String(entityModel.entityPose.action_serial || ""))
                                        if (root.surfaceHost && typeof root.surfaceHost.gameEngineRegisterRig === "function")
                                            root.surfaceHost.gameEngineRegisterRig(this,entityModel.worldEntityId)
                                        if(root.surfaceHost.gameEngineEnablePicking)root.surfaceHost.gameEngineEnablePicking(this,entityModel.worldEntityId)
                                        root.applyAssetMaterial(this,entityModel.worldEntityId)
                                    }
                                }
                            }
                            Loader3D {
                                id: authoredAssetLoader
                                objectName: "gameAuthoredAssetLoaderHost"
                                active: entityModel.authoredAssetEligible
                                asynchronous: false
                                sourceComponent: authoredCharacterComponent
                                visible: entityModel.authoredAssetVisible
                                position: Qt.vector3d(
                                    0,
                                    root.number(
                                        entityModel.entityAsset.root_offset_m,
                                        -0.65
                                    ) + entityModel.poseBob,
                                    0
                                )
                                eulerRotation: Qt.vector3d(
                                    entityModel.poseLean,
                                    entityModel.poseSway,
                                    0
                                )
                                scale: Qt.vector3d(
                                    entityModel.entityAsset.editor_scale ? entityModel.entitySx : Math.min(1.25, entityModel.entitySx),
                                    entityModel.characterYScale
                                        * (1 + entityModel.poseSquash),
                                    entityModel.entityAsset.editor_scale ? entityModel.entitySz : Math.min(1.25, entityModel.entitySz)
                                )
                            }

                            // The board is a vehicle prop under the authored player.
                            Model {
                                objectName: "playerHoverboardProxy"
                                visible: entityModel.entityKind === "PLAYER"
                                    && String(entityModel.dynamicData.vehicle || "")
                                        === "HOVERBOARD"
                                source: "#Cube"
                                position: Qt.vector3d(0, -0.53, 0)
                                scale: Qt.vector3d(
                                    0.72 * root.sceneScale,
                                    0.10 * root.sceneScale,
                                    1.32 * root.sceneScale
                                )
                                castsShadows: root.shadowMappingEnabled
                                receivesShadows: false
                                materials: [
                                    PrincipledMaterial {
                                        baseColor: "#bd6938"
                                        roughness: 0.72
                                        metalness: 0.04
                                    }
                                ]
                            }

                            Loader3D {
                                id: worldActionTool
                                objectName: "gameWorldActionTool"
                                readonly property string tool: String(entityModel.entityPose.interaction_tool || "")
                                active: entityModel.authoredAssetVisible
                                    && ["shears","brush","rod","net","knife","hammer"].indexOf(tool) >= 0
                                property var grip: {
                                    var revision = entityModel.authoredSocketRevision
                                    return entityModel.authoredAssetRuntimeLoader
                                        ? root.findAttachmentNode(entityModel.authoredAssetRuntimeLoader, "SOCKET_MAIN_HAND") : null
                                }
                                parent: grip || entityModel
                                sourceComponent: Component {
                                    RuntimeLoader {
                                        objectName: "gameWorldActionToolMesh"
                                        source: worldActionTool.tool === "hammer"
                                            ? Qt.resolvedUrl("../assets/authored/variants/items/weapon-mace-v5.glb")
                                            : Qt.resolvedUrl("../assets/authored/nature/tool-" + worldActionTool.tool + ".glb")
                                    }
                                }
                            }

                            Repeater3D {
                                model: entityModel.entityKind === "PLAYER"
                                    ? entityModel.equipment.slice(0, 16) : []
                                delegate: Node {
                                    id: wornItem
                                    objectName: "gameEquippedItemModel"
                                    Component.onCompleted: root.equipmentFxNodes[wornItem.slot]=wornItem
                                    Component.onDestruction: {
                                        var mesh=wornItem.fxMesh()
                                        if (root.enchantMesh0===mesh) root.enchantMesh0=null
                                        if (root.enchantMesh1===mesh) root.enchantMesh1=null
                                        if (root.equipmentFxNodes[wornItem.slot]===wornItem)
                                            delete root.equipmentFxNodes[wornItem.slot]
                                    }
                                    required property var modelData
                                    readonly property var visual: modelData.visual || ({})
                                    readonly property var itemAsset: modelData.asset || ({})
                                    readonly property var articulation: itemAsset.articulation || ({})
                                    property var flailRig: null
                                    property var flailState: null
                                    property int flailSetupAttempts: 0
                                    property var flailLinkLoaders: []
                                    function flailPartSource(filename) {
                                        var source=String(itemAsset.source || "")
                                        return source.slice(0,source.lastIndexOf("/")+1)+filename
                                    }
                                    function setupFlail() {
                                        if(articulation.kind!=="FLAIL" || !authoredItemVisible)return
                                        var head=authoredFlailHead
                                        if(head.status!==RuntimeLoader.Success)return
                                        var links=[]
                                        for(var i=0;i<articulation.links;++i) {
                                            var link=flailLinkLoaders[i]
                                            if(!link || link.status!==RuntimeLoader.Success)return
                                            links.push(link)
                                        }
                                        if(head)flailRig={head:head,links:links}
                                    }
                                    function flailWorld(p) {
                                        var v=authoredEquippedItemLoader.mapPositionToScene(Qt.vector3d(p[0],p[1],p[2]))
                                        return [v.x,v.y,v.z]
                                    }
                                    function placeFlailPart(node,centre,direction,restPoint) {
                                        var local=node.parent.mapPositionFromScene(Qt.vector3d(centre[0],centre[1],centre[2]))
                                        var end=node.parent.mapPositionFromScene(Qt.vector3d(centre[0]+direction[0],centre[1]+direction[1],centre[2]+direction[2]))
                                        var q=FlailPhysics.rotationFromY([end.x-local.x,end.y-local.y,end.z-local.z])
                                        var datum=FlailPhysics.rotate(q,[restPoint[0]*node.scale.x,restPoint[1]*node.scale.y,restPoint[2]*node.scale.z])
                                        node.rotation=Qt.quaternion(q[0],q[1],q[2],q[3])
                                        node.position=Qt.vector3d(local.x-datum[0],local.y-datum[1],local.z-datum[2])
                                    }
                                    function stepFlail(dt) {
                                        if(articulation.kind!=="FLAIL" || !authoredItemVisible)return
                                        if(!flailRig) {
                                            if(flailSetupAttempts++<8)setupFlail()
                                            if(!flailRig)return
                                        }
                                        var anchor=flailWorld(articulation.anchor)
                                        var unit=flailWorld([articulation.anchor[0]+1,articulation.anchor[1],articulation.anchor[2]])
                                        var scale=FlailPhysics.norm(FlailPhysics.sub(unit,anchor))
                                        if(!flailState)flailState=FlailPhysics.create(anchor,articulation.length*scale,articulation.links)
                                        var shaft=[flailWorld(articulation.shaft[0]),flailWorld(articulation.shaft[1])]
                                        flailState=FlailPhysics.step(flailState,anchor,dt,shaft,
                                            articulation.head_radius*scale,articulation.shaft_radius*scale)
                                        var p=flailState.points
                                        for(var i=0;i<flailRig.links.length;++i) {
                                            placeFlailPart(flailRig.links[i],FlailPhysics.mul(FlailPhysics.add(p[i],p[i+1]),.5),
                                                FlailPhysics.sub(p[i],p[i+1]),articulation.link_rest[i])
                                        }
                                        placeFlailPart(flailRig.head,p[p.length-1],FlailPhysics.sub(p[p.length-2],p[p.length-1]),articulation.head_rest)
                                    }
                                    function flailPhysicsFrame() {
                                        if(!flailState || !flailRig)return null
                                        var rest=articulation.head_rest
                                        var actual=flailRig.head.mapPositionToScene(Qt.vector3d(rest[0],rest[1],rest[2]))
                                        return {points:flailState.points,steps:flailState.steps,length:flailState.length,
                                            links:flailRig.links.length,actualHead:[actual.x,actual.y,actual.z]}
                                    }
                                    function enchantFrame() {
                                        var region = wornItem.itemAsset.weapon_fx || ({})
                                        region = region[wornItem.authoredItemVisible ? "authored" : "native"] || ({})
                                        var base = region.base || [0,0,0]
                                        var tip = region.tip || [0,.5,0]
                                        var mesh = wornItem.authoredItemVisible
                                            ? authoredEquippedItemLoader : gameEquippedItemPrimitive
                                        var start = mesh.mapPositionToScene(Qt.vector3d(base[0],base[1],base[2]))
                                        var end = mesh.mapPositionToScene(Qt.vector3d(tip[0],tip[1],tip[2]))
                                        var frame = {base:{x:start.x,y:start.y,z:start.z},
                                            tip:{x:end.x,y:end.y,z:end.z}}
                                        if(flailState && flailRig) {
                                            var p=flailState.points[flailState.points.length-1]
                                            frame.base={x:p[0],y:p[1],z:p[2]}
                                            frame.tip={x:p[0],y:p[1]+.2,z:p[2]}
                                            frame.path=[frame.base,frame.tip];frame.muzzles=[]
                                            return frame
                                        }
                                        // Host bindings can expose a QML sequence rather
                                        // than a JavaScript Array. Both support length
                                        // and indexing; Array.isArray rejects the former.
                                        if (region.path && typeof region.path.length === "number"
                                                && region.path.length>1) {
                                            frame.path=[]
                                            for (var i=0;i<Math.min(region.path.length,64);++i) {
                                                var p=region.path[i]
                                                var point=mesh.mapPositionToScene(Qt.vector3d(p[0],p[1],p[2]))
                                                frame.path.push({x:point.x,y:point.y,z:point.z})
                                            }
                                        }
                                        frame.muzzles=[]
                                        if (region.magic && region.magic.colors && region.magic.colors.length) {
                                            var core=region.magic.point
                                            var glow=mesh.mapPositionToScene(Qt.vector3d(core[0],core[1],core[2]))
                                            frame.magic={point:{x:glow.x,y:glow.y,z:glow.z},
                                                theme:region.magic.theme,colors:region.magic.colors,
                                                radius:region.magic.radius}
                                        }
                                        var muzzlePoints=wornItem.itemAsset.muzzle_points || []
                                        for (var m=0;m<muzzlePoints.length && m<7;++m) {
                                            var p=muzzlePoints[m]
                                            var muzzle=mesh.mapPositionToScene(Qt.vector3d(p[0],p[1],p[2]))
                                            frame.muzzles.push({x:muzzle.x,y:muzzle.y,z:muzzle.z})
                                        }
                                        return frame
                                    }
                                    function fxMesh() {
                                        return wornItem.authoredItemVisible
                                            ? authoredEquippedItemLoader : gameEquippedItemPrimitive
                                    }
                                    readonly property var attachment: modelData.attachment
                                        || wornItem.visual.attachment
                                        || ({})
                                    readonly property string slot: String(modelData.equipped_slot || "")
                                    readonly property var displayState: root.clientDisplay
                                    visible: (wornItem.slot !== 'HEAD' || wornItem.displayState.helm !== false)
                                        && (wornItem.slot !== 'BACK' || wornItem.displayState.cloak !== false)
                                        && modelData.visual_visible !== false
                                        && (!Boolean(entityModel.entityPose.world_interaction)
                                            || (socketId !== "MAIN_HAND" && socketId !== "OFF_HAND"
                                                && slot !== "MAIN_HAND" && slot !== "OFF_HAND"))
                                    readonly property string socketId: String(
                                        wornItem.attachment.socket || wornItem.slot
                                    )
                                    readonly property string socketNodeName: String(
                                        wornItem.attachment.node
                                            || (wornItem.socketId
                                                ? "SOCKET_" + wornItem.socketId
                                                : "")
                                    )
                                    readonly property var rest: wornItem.attachment.rest || []
                                    readonly property var authoredHandRest: {
                                        if (modelData.visual_stowed || ["item.weapon_pistol","item.weapon_wand","item.weapon_staff","item.weapon_mace","item.weapon_offhand"].indexOf(modelData.definition_id)<0 || !entityModel.authoredAssetRuntimeLoader) return null
                                        var sockets=entityModel.entityAsset.attachment_sockets || ({})
                                        var anchor=sockets[wornItem.slot]
                                        if (!anchor || !anchor.model_rest) return null
                                        var p=anchor.model_rest
                                        return entityModel.authoredAssetRuntimeLoader.mapPositionToNode(entityModel,Qt.vector3d(p[0],p[1],p[2]))
                                    }
                                    property var socketNode: {
                                        var revision = entityModel.authoredSocketRevision
                                        if (!entityModel.authoredAssetVisible
                                            || !entityModel.authoredAssetRuntimeLoader
                                            || !wornItem.socketNodeName)
                                            return null
                                        return root.findAttachmentNode(
                                            entityModel.authoredAssetRuntimeLoader,
                                            wornItem.socketNodeName
                                        )
                                    }
                                    parent: wornItem.socketNode || entityModel
                                    property var itemGeometry:
                                        modelData.definition_id!=="item.guild_tabard" && root.surfaceHost
                                        && typeof root.surfaceHost
                                            .gameEngineItemGeometry === "function"
                                        ? root.surfaceHost.gameEngineItemGeometry(
                                            String(
                                                wornItem.itemAsset.geometry_key
                                                    || wornItem.visual.asset_id
                                                    || "item.unknown"
                                            ),
                                            String(
                                                wornItem.itemAsset.asset_class
                                                    || modelData.kind
                                                    || "ITEM"
                                            )
                                        ) : null
                                    onItemGeometryChanged: {
                                        if (itemGeometry)
                                            entityModel.applyNativeGeometry(
                                                gameEquippedItemPrimitive,
                                                itemGeometry
                                            )
                                    }
                                    property bool authoredItemEligible:
                                        String(wornItem.itemAsset.mode || "")
                                            === "AUTHORED_STATIC"
                                        && String(wornItem.itemAsset.source || "") !== ""
                                    property bool authoredItemVisible:
                                        wornItem.authoredItemEligible
                                        && authoredEquippedItemLoader.status
                                            === RuntimeLoader.Success
                                    onAuthoredItemVisibleChanged: Qt.callLater(root.refreshVisualEffects)
                                    property var tabardAlignment:wornItem.socketNode && wornItem.slot==="TABARD"
                                        ? root.surfaceHost.gameEngineAlignedAttachment(wornItem.socketNode.sceneRotation,entityModel.sceneRotation,
                                            Qt.vector3d(0,-.35,.34)) : null
                                    position:tabardAlignment ? tabardAlignment.position : wornItem.socketNode
                                        ? Qt.vector3d(
                                            root.number((wornItem.visual.grip_offset || [])[0],0),
                                            root.number((wornItem.visual.grip_offset || [])[1],0),
                                            root.number((wornItem.visual.grip_offset || [])[2],0))
                                        : wornItem.authoredHandRest ? wornItem.authoredHandRest
                                        : Qt.vector3d(
                                            root.number(
                                                wornItem.rest[0],
                                                wornItem.slot === "MAIN_HAND"
                                                    ? 0.48
                                                    : (wornItem.slot === "OFF_HAND" ? -0.48 : 0)
                                            ) + (wornItem.slot === "TABARD" ? root.number((wornItem.visual.grip_offset || [])[0],0) : 0),
                                            root.number(
                                                wornItem.rest[1],
                                                wornItem.slot === "HEAD"
                                                    ? 0.83
                                                    : (wornItem.slot === "CHEST"
                                                        ? 0.07
                                                        : (wornItem.slot === "BACK"
                                                            ? 0.13
                                                            : (wornItem.slot === "FEET" ? -0.61 : -0.29)))
                                            ) + entityModel.poseBob + (wornItem.slot === "TABARD" ? root.number((wornItem.visual.grip_offset || [])[1],0) : 0),
                                            root.number(
                                                wornItem.rest[2],
                                                wornItem.slot === "CHEST"
                                                    ? -0.16
                                                    : (wornItem.slot === "BACK" ? 0.22 : -0.04)
                                            ) + (wornItem.slot === "TABARD" ? root.number((wornItem.visual.grip_offset || [])[2],0) : 0)
                                        )
                                    eulerRotation:tabardAlignment ? tabardAlignment.rotation : Qt.vector3d(
                                        root.number(visual.rotation ? visual.rotation[0] : 0, 0),
                                        root.number(visual.rotation_y, visual.rotation ? visual.rotation[1] : 0),
                                        root.number(visual.rotation ? visual.rotation[2] : 0, 0)
                                    )
                                    Texture {
                                        id:tabardTexture
                                        textureData:root.surfaceHost && wornItem.visual.base_color_map
                                            ? root.surfaceHost.gameEngineEmblemTexture(String(wornItem.visual.base_color_map),wornItem) : null
                                    }
                                    Model {
                                        id: gameEquippedItemPrimitive
                                        objectName: "gameEquippedItemPrimitive"
                                        visible: !wornItem.authoredItemVisible
                                        property string requestedModel: String(
                                            visual.model || "#Cube"
                                        )
                                        property bool usesNativeGeometry:
                                            Boolean(wornItem.itemGeometry)
                                        property bool usesLowPolySphere:
                                            !Boolean(wornItem.itemGeometry)
                                            && wornItem.requestedModel === "#Sphere"
                                        source: wornItem.itemGeometry
                                            ? ""
                                            : (Boolean(root.lowPolySphereGeometry)
                                            && wornItem.requestedModel === "#Sphere"
                                            && root.lowPolySphereGeometry
                                            ? ""
                                            : (wornItem.requestedModel === "#Sphere"
                                                ? "#Cube" : String(wornItem.requestedModel || "#Cube")))
                                        geometry: wornItem.itemGeometry
                                            ? wornItem.itemGeometry
                                            : (Boolean(root.lowPolySphereGeometry)
                                                && wornItem.requestedModel === "#Sphere"
                                                ? root.lowPolySphereGeometry : null)
                                        scale: Qt.vector3d(
                                            root.number(visual.scale ? visual.scale[0] : 0.16, 0.16) * (wornItem.itemGeometry ? 1 : root.sceneScale),
                                            root.number(visual.scale ? visual.scale[1] : 0.16, 0.16) * (wornItem.itemGeometry ? 1 : root.sceneScale),
                                            root.number(visual.scale ? visual.scale[2] : 0.16, 0.16) * (wornItem.itemGeometry ? 1 : root.sceneScale)
                                        )
                                        castsShadows: root.shadowMappingEnabled
                                        receivesShadows: root.shadowMappingEnabled
                                        materials: PrincipledMaterial {
                                            baseColorMap: wornItem.visual.base_color_map ? tabardTexture : null
                                            baseColor: String(
                                                wornItem.visual.base_color
                                                    || modelData.rarity_color
                                                    || "#d6d6d6"
                                            )
                                            vertexColorsEnabled: false
                                            roughness: root.number(
                                                wornItem.visual.roughness, 0.42
                                            )
                                            metalness: root.number(
                                                wornItem.visual.metalness, 0.34
                                            )
                                            emissiveFactor: Qt.vector3d(
                                                root.number(wornItem.visual.glow, 0),
                                                root.number(wornItem.visual.glow, 0) * 0.7,
                                                root.number(wornItem.visual.glow, 0) * 0.35
                                            )
                                        }
                                    }
                                    RuntimeLoader {
                                        id: authoredEquippedItemLoader
                                        objectName: "gameAuthoredEquippedItemLoader"
                                        onStatusChanged: {
                                            wornItem.flailRig=null;wornItem.flailState=null;wornItem.flailSetupAttempts=0
                                            if(status===RuntimeLoader.Success && wornItem.articulation.kind==="FLAIL")
                                                Qt.callLater(wornItem.setupFlail)
                                        }
                                        source: wornItem.authoredItemEligible
                                            ? wornItem.articulation.kind==="FLAIL"
                                                ? wornItem.flailPartSource(wornItem.articulation.part_sources.handle)
                                                : String(wornItem.itemAsset.source || "")
                                            : ""
                                        visible: wornItem.authoredItemVisible
                                        scale: Qt.vector3d(
                                            root.number(visual.scale ? visual.scale[0] : 0.16, 0.16) * root.number(
                                                wornItem.itemAsset.unit_scale
                                                    ? wornItem.itemAsset.unit_scale[0] : 1,
                                                1
                                            ),
                                            root.number(visual.scale ? visual.scale[1] : 0.16, 0.16) * root.number(
                                                wornItem.itemAsset.unit_scale
                                                    ? wornItem.itemAsset.unit_scale[1] : 1,
                                                1
                                            ),
                                            root.number(visual.scale ? visual.scale[2] : 0.16, 0.16) * root.number(
                                                wornItem.itemAsset.unit_scale
                                                    ? wornItem.itemAsset.unit_scale[2] : 1,
                                                1
                                            )
                                        )
                                    }
                                    // RuntimeLoader's imported static children are
                                    // private. These ten bounded loaders use the
                                    // exact painted parts from the full gallery GLB.
                                    Repeater3D {
                                        model: wornItem.authoredItemEligible && wornItem.articulation.kind==="FLAIL"
                                            ? wornItem.articulation.part_sources.links : []
                                        delegate: RuntimeLoader {
                                            id: flailLink
                                            required property int index
                                            required property string modelData
                                            objectName: "gameFlailChainLoader"
                                            source: wornItem.flailPartSource(modelData)
                                            scale: authoredEquippedItemLoader.scale
                                            visible: wornItem.authoredItemVisible && status===RuntimeLoader.Success
                                            Component.onCompleted: {
                                                wornItem.flailLinkLoaders[index]=flailLink
                                                Qt.callLater(wornItem.setupFlail)
                                            }
                                            Component.onDestruction: {
                                                if(wornItem.flailLinkLoaders[index]===flailLink)
                                                    wornItem.flailLinkLoaders[index]=null
                                            }
                                            onStatusChanged: if(status===RuntimeLoader.Success)Qt.callLater(wornItem.setupFlail)
                                        }
                                    }
                                    RuntimeLoader {
                                        id: authoredFlailHead
                                        objectName: "gameFlailHeadLoader"
                                        source: wornItem.authoredItemEligible && wornItem.articulation.kind==="FLAIL"
                                            ? wornItem.flailPartSource(wornItem.articulation.part_sources.head) : ""
                                        scale: authoredEquippedItemLoader.scale
                                        visible: wornItem.authoredItemVisible && status===RuntimeLoader.Success
                                        onStatusChanged: if(status===RuntimeLoader.Success)Qt.callLater(wornItem.setupFlail)
                                    }
                                }
                            }
                        }
                    }

                    Model {
                        id: particleBatchModel
                        objectName: "gameEngineParticleBatchModel"
                        geometry: root.particleBatchGeometry
                        visible: root.paneLive
                            && !root.dosFallbackActive
                            && root.particleBatchCount > 0
                        scale: Qt.vector3d(
                            1,
                            1,
                            1
                        )
                        castsShadows: false
                        receivesShadows: false
                        materials: [clayParticleMaterial]
                    }
                    Model {
                        objectName: "gameEngineAdditiveParticleBatchModel"
                        geometry: root.additiveParticleGeometry
                        visible: root.paneLive && !root.dosFallbackActive && root.additiveParticleCount > 0
                        castsShadows: false
                        receivesShadows: false
                        materials: [luminousParticleMaterial]
                    }
                    RuntimeLoader {
                        objectName: "gameEnchantingTable"
                        source: Qt.resolvedUrl("../assets/authored/world/gg-enchanting-table.glb")
                        visible: root.paneLive && !root.dosFallbackActive
                            && root.enchantStation.x !== undefined
                            && Math.hypot(root.enchantStation.x-root.number(root.player.x,0),
                                root.enchantStation.z-root.number(root.player.z,0)) < 128
                        position: Qt.vector3d(root.number(root.enchantStation.x,0),
                            root.planetRenderY(root.number(root.enchantStation.x,0),
                                root.number(root.enchantStation.y,0),root.number(root.enchantStation.z,0)),
                            root.number(root.enchantStation.z,0))
                    }
                    Repeater3D {
                        // Fixed slots prevent creating/destroying QML lights
                        // for every spark or frame. All lights share one cap.
                        model: root.number((root.render.policy || {}).max_dynamic_lights,6)
                        delegate: PointLight {
                            required property int index
                            readonly property var sourceLight: root.localLightSources[index] || ({})
                            objectName: "gameLocalVfxLight"
                            // Visibility changes specialize every lit material
                            // for a new light count. Keep the bounded pool in
                            // the scene and turn unused slots off with zero
                            // energy, including after wrapping enchanted gear.
                            visible: root.paneLive && !root.dosFallbackActive
                            position: root.attachedLightPosition(sourceLight)
                            color: sourceLight.color || "#ffbf6c"
                            brightness: root.number(sourceLight.light_energy,0)
                            constantFade: 1.0
                            linearFade: 0.0
                            quadraticFade: WorldFx.pointLightQuadraticFade(
                                root.number(sourceLight.light_radius_m,1))
                            castsShadow: false
                        }
                    }
                }

                Loader {
                    active: root.page === "PERF" && root.paneLive
                        && !root.dosFallbackActive && !root.standalonePlayerMode
                    x: 96
                    y: 12
                    z: 20
                    sourceComponent: Component {
                        DebugView {
                            objectName: "gameRenderDebugView"
                            source: view3d
                            resourceDetailsVisible: true
                        }
                    }
                }

                Rectangle {
                    objectName: "gameCombatTargetFrame"
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 14
                    width: 240
                    height: 58
                    radius: 5
                    color: "#d91b2427"
                    border.color: root.ledgerGold
                    visible: root.paneLive && Boolean(root.combatTarget.id)
                    z: 18
                    Text {
                        anchors.fill: parent
                        anchors.margins: 8
                        color: root.text
                        font.pixelSize: 13
                        text: String(root.combatTarget.name || "Target")
                            + "  ·  " + root.fixed(root.combatTarget.distance_m, 1) + " m"
                            + "\n" + root.fixed(root.combatTarget.health, 0) + " / "
                            + root.fixed(root.combatTarget.max_health, 0) + " HP"
                    }
                }

                // Terminal fallback: this layer consumes the same bounded
                // render rows as View3D.  It is deliberately a sibling of
                // the rich scene so changing presentation cannot reset, slow
                // or fork the simulation.
                Item {
                    id: dosFallbackLayer
                    objectName: "gameEngineDosFallback"
                    anchors.fill: parent
                    visible: root.dosFallbackActive
                    z: 25

                    Rectangle {
                        anchors.fill: parent
                        color: "#030604"
                        border.color: "#2f6b3b"
                        border.width: 1
                    }

                    Canvas {
                        id: dosFallbackCanvas
                        objectName: "gameEngineDosFallbackCanvas"
                        anchors.fill: parent
                        visible: root.dosFallbackActive
                        onPaint: {
                            var ctx = getContext("2d")
                            var w = width
                            var h = height
                            var palette = root.fallbackView.palette || ({})
                            var camera = root.fallbackView.camera || ({})
                            var centerX = root.number(camera.center_x, root.number(root.player.x, 0))
                            var centerZ = root.number(camera.center_z, root.number(root.player.z, 0))
                            var radius = Math.max(6, root.number(camera.radius_m, 18))
                            var scale = Math.min(w, h) * 0.42 / radius

                            ctx.clearRect(0, 0, w, h)
                            ctx.fillStyle = String(palette.background || "#030604")
                            ctx.fillRect(0, 0, w, h)
                            var assetFrame = root.fallbackView.frame || ({})
                            var glyphRows = assetFrame.glyphs || []
                            if (glyphRows.length) {
                                var frameCols = Math.max(1, root.number(assetFrame.cols, String(glyphRows[0] || "").length))
                                var frameRows = glyphRows.length
                                var cellAspect = 0.5
                                var cellW = w / frameCols
                                var cellH = cellW / cellAspect
                                if (cellH * frameRows > h) {
                                    cellH = h / frameRows
                                    cellW = cellH * cellAspect
                                }
                                var originX = (w - cellW * frameCols) * 0.5
                                var originY = (h - cellH * frameRows) * 0.5
                                var framePalette = assetFrame.palette || []
                                var fgRows = assetFrame.fg || []
                                var bgRows = assetFrame.bg || []
                                ctx.textAlign = "center"
                                ctx.textBaseline = "middle"
                                ctx.font = Math.max(7, Math.floor(cellH * 0.78)) + "px monospace"
                                for (var frameRow = 0; frameRow < frameRows; ++frameRow) {
                                    var glyphLine = String(glyphRows[frameRow] || "")
                                    var fgLine = String(fgRows[frameRow] || "")
                                    var bgLine = String(bgRows[frameRow] || "")
                                    for (var frameCol = 0; frameCol < frameCols; ++frameCol) {
                                        var bgIndex = parseInt(bgLine.substr(frameCol * 2, 2), 16)
                                        var fgIndex = parseInt(fgLine.substr(frameCol * 2, 2), 16)
                                        var cellX = originX + frameCol * cellW
                                        var cellY = originY + frameRow * cellH
                                        ctx.fillStyle = String(framePalette[isNaN(bgIndex) ? 0 : bgIndex] || "#030604")
                                        ctx.fillRect(cellX, cellY, cellW + 0.6, cellH + 0.6)
                                        var glyph = glyphLine.charAt(frameCol)
                                        if (glyph && glyph !== " ") {
                                            ctx.fillStyle = String(framePalette[isNaN(fgIndex) ? 0 : fgIndex] || "#9fe3a4")
                                            ctx.fillText(glyph, cellX + cellW * 0.5, cellY + cellH * 0.55)
                                        }
                                    }
                                }
                                return
                            }
                            ctx.strokeStyle = String(palette.grid || "#173117")
                            ctx.lineWidth = 1
                            var gridStep = Math.max(18, Math.min(64, Math.min(w, h) / 12))
                            for (var gx = 0; gx <= w; gx += gridStep) {
                                ctx.beginPath()
                                ctx.moveTo(gx, 0)
                                ctx.lineTo(gx, h)
                                ctx.stroke()
                            }
                            for (var gy = 0; gy <= h; gy += gridStep) {
                                ctx.beginPath()
                                ctx.moveTo(0, gy)
                                ctx.lineTo(w, gy)
                                ctx.stroke()
                            }

                            function screenX(worldX) {
                                return w * 0.5 + (Number(worldX) - centerX) * scale
                            }
                            function screenY(worldZ) {
                                return h * 0.5 + (Number(worldZ) - centerZ) * scale
                            }

                            var terrainRows = root.fallbackView.terrain || []
                            ctx.font = "12px monospace"
                            ctx.textAlign = "center"
                            ctx.textBaseline = "middle"
                            for (var terrainIndex = 0; terrainIndex < terrainRows.length; ++terrainIndex) {
                                var terrainRow = terrainRows[terrainIndex]
                                if (!terrainRow)
                                    continue
                                var terrainX = screenX(root.number(terrainRow.x, 0))
                                var terrainY = screenY(root.number(terrainRow.z, 0))
                                if (terrainX < -20 || terrainX > w + 20 || terrainY < -20 || terrainY > h + 20)
                                    continue
                                ctx.fillStyle = String(terrainRow.surface || "LAND") === "WATER"
                                    ? String(palette.water || "#4c9ca0")
                                    : String(palette.muted || "#5d9b66")
                                ctx.fillText(String(terrainRow.glyph || ","), terrainX, terrainY)
                            }

                            var entityRows = root.fallbackView.entities || root.renderEntities || []
                            for (var entityIndex = 0; entityIndex < entityRows.length; ++entityIndex) {
                                var entityRow = entityRows[entityIndex]
                                if (!entityRow)
                                    continue
                                var entityX = root.number(entityRow.x, 0)
                                var entityZ = root.number(entityRow.z, 0)
                                if (Math.abs(entityX - centerX) > radius || Math.abs(entityZ - centerZ) > radius)
                                    continue
                                var markerX = screenX(entityX)
                                var markerY = screenY(entityZ)
                                var markerColor = String(entityRow.color || palette.text || "#9fe3a4")
                                if (String(entityRow.kind || "") === "PLAYER")
                                    markerColor = String(palette.player || "#e3bd63")
                                ctx.fillStyle = markerColor
                                ctx.fillText(String(entityRow.glyph || "."), markerX, markerY)
                                if (String(entityRow.kind || "") === "PLAYER"
                                    || String(entityRow.kind || "") === "NPC") {
                                    ctx.font = "10px monospace"
                                    ctx.textAlign = "left"
                                    ctx.fillText(String(entityRow.label || entityRow.id || ""), markerX + 8, markerY)
                                    var worn = entityRow.equipment || []
                                    if (worn.length) {
                                        ctx.font = "9px monospace"
                                        ctx.textAlign = "center"
                                        for (var gearIndex = 0; gearIndex < worn.length; ++gearIndex) {
                                            var wornRow = worn[gearIndex] || ({})
                                            ctx.fillStyle = String(wornRow.color || markerColor)
                                            ctx.fillText(
                                                String(wornRow.glyph || "+"),
                                                markerX + ((gearIndex % 3) - 1) * 8,
                                                markerY - 10 - Math.floor(gearIndex / 3) * 8
                                            )
                                        }
                                    }
                                    ctx.font = "12px monospace"
                                    ctx.textAlign = "center"
                                }
                            }

                            ctx.strokeStyle = String(palette.player || "#e3bd63")
                            ctx.strokeRect(w * 0.5 - 7, h * 0.5 - 7, 14, 14)
                        }
                    }

                    MouseArea {
                        anchors.fill: dosFallbackCanvas
                        acceptedButtons: Qt.LeftButton | Qt.RightButton
                        onPressed: root.forceActiveFocus()
                    }

                    Column {
                        anchors.left: parent.left
                        anchors.top: parent.top
                        anchors.margins: 18
                        spacing: 5

                        Text {
                            text: root.presentationReason === "MANUAL_DOS_MODE"
                                ? "GG//DOS  ·  SAME WORLD  ·  F8 LOW POLY"
                                : "GG//DOS  ·  LOW POLY HIDDEN  ·  F8 RETRIES"
                            color: root.ledgerGreen
                            font.family: "monospace"
                            font.pixelSize: 14
                            font.bold: true
                        }
                        Text {
                            text: String(root.presentationReason || "DOS")
                                + "  ·  SIMULATION CONTINUES  ·  SHARED ASSETS"
                            color: root.text
                            font.family: "monospace"
                            font.pixelSize: 10
                        }
                        Text {
                            text: root.fallbackTerminalText()
                            color: String((root.fallbackView.palette || ({})).text || "#9fe3a4")
                            font.family: "monospace"
                            font.pixelSize: 10
                            lineHeight: 1.15
                        }
                        Row {
                            spacing: 5
                            Text {
                                text: ">"
                                color: root.ledgerGold
                                font.family: "monospace"
                                font.pixelSize: 11
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Rectangle {
                                width: 320
                                height: 26
                                color: "#071007"
                                border.color: root.ledgerGreen
                                border.width: 1
                                TextInput {
                                    id: dosCommandInput
                                    anchors.fill: parent
                                    anchors.leftMargin: 6
                                    anchors.rightMargin: 6
                                    color: root.ledgerGreen
                                    selectionColor: root.ledgerGold
                                    font.family: "monospace"
                                    font.pixelSize: 11
                                    clip: true
                                    maximumLength: 96
                                    onAccepted: {
                                        root.dosCommand(text)
                                        text = ""
                                    }
                                }
                            }
                            GgButton {
                                text: "RUN"
                                implicitWidth: 52
                                implicitHeight: 26
                                onClicked: {
                                    root.dosCommand(dosCommandInput.text)
                                    dosCommandInput.text = ""
                                }
                            }
                        }
                    }

                    Row {
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 18
                        spacing: 6

                        GgButton {
                            text: "RETRY 3D"
                            implicitWidth: 82
                            implicitHeight: 25
                            onClicked: root.setPresentationMode("RICH_3D")
                        }
                        GgButton {
                            text: "DOS LOCK"
                            implicitWidth: 82
                            implicitHeight: 25
                            checked: root.presentationMode === "DOS_2D"
                            onClicked: root.setPresentationMode("DOS_2D")
                        }
                    }
                }

                MouseArea {
                    id: cameraMouse
                    anchors.fill: parent
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    hoverEnabled: true
                    cursorShape: terrainPicking
                        ? Qt.CrossCursor
                        : (cameraDragging
                            ? Qt.ClosedHandCursor : root.worldHoverInfo.id ? Qt.PointingHandCursor : Qt.ArrowCursor)
                    property real dragStartX: 0
                    property real dragStartY: 0
                    property bool cameraDragging: false
                    property bool terrainPicking: false
                    property string brushLastKey: ""
                    property real brushLastX: Number.NaN
                    property real brushLastZ: Number.NaN
                    property var pressGestures: ({})
                    onEntered: root.worldMouseInside = true
                    onExited: {root.worldMouseInside=false;root.worldHoverInfo=({})}

                    onPressed: function(mouse) {
                        root.forceActiveFocus()
                        if (root.assetEditorMode && mouse.button===Qt.LeftButton && !(mouse.modifiers & Qt.ShiftModifier)) {
                            var picked=root.assetPick(mouse.x,mouse.y)
                            if(picked)root.assetEdit({op:"SELECT",identity:picked})
                            if(picked && root.assetTool==="MOVE") {
                                var entity=(root.assetEditorState.selected || {}).entity || ({})
                                var t=(root.assetEditorState.selected.edit || {}).transform || ({})
                                root.assetDrag={startX:mouse.x,startY:mouse.y,x:Number(t.x!==undefined?t.x:entity.x),
                                    y:Number(t.y!==undefined?t.y:entity.y),z:Number(t.z!==undefined?t.z:entity.z)}
                                root.assetEdit({op:"BEGIN_TRANSFORM"})
                            }
                            mouse.accepted=true;return
                        }
                        if (
                            mouse.button === Qt.LeftButton
                            && (mouse.modifiers & Qt.ShiftModifier) !== 0
                        ) {
                            terrainPicking = true
                            brushLastKey = ""
                            brushLastX = Number.NaN
                            brushLastZ = Number.NaN
                            var selectedKey = root.pickTerrainCell(
                                mouse.x,
                                mouse.y
                            )
                            if (root.terrainBrushEnabled && selectedKey) {
                                brushLastKey = selectedKey
                                brushLastX = root.terrainBrushX
                                brushLastZ = root.terrainBrushZ
                                root.editTerrain(root.terrainBrushOperation)
                            }
                            mouse.accepted = true
                            return
                        }
                        if (root.controlsLocked) {
                            mouse.accepted = false
                            return
                        }
                        cameraDragging = true
                        dragStartX = mouse.x
                        dragStartY = mouse.y
                        var pressHit=root.worldPick(mouse.x,mouse.y)
                        var presses=Object.assign({},pressGestures)
                        presses[String(mouse.button)]={at:Date.now(),yaw:0,pitch:0,id:String(pressHit.id || '')}
                        if (mouse.buttons === (Qt.LeftButton | Qt.RightButton)) {
                            for (var pressKey in presses) presses[pressKey].cancelled=true
                        }
                        pressGestures=presses
                        root.beginCameraLook(mouse.button)
                    }

                    onPositionChanged: function(mouse) {
                        var point=cameraMouse.mapToItem(root,mouse.x,mouse.y)
                        root.worldMouseX=point.x;root.worldMouseY=point.y
                        if(root.assetEditorMode && root.assetDrag.startX!==undefined && pressed) {
                            var now=Date.now();if(now-root.assetDragSentAt<40)return
                            root.assetDragSentAt=now
                            var angle=root.cameraHeading*Math.PI/180
                            var meter=2*root.cameraDistance*Math.tan(25*Math.PI/180)/Math.max(1,view3d.height)
                            var dx=(mouse.x-root.assetDrag.startX)*meter, dz=(mouse.y-root.assetDrag.startY)*meter
                            root.assetEdit({op:"DRAG_PREVIEW",values:{x:root.assetDrag.x+dx*Math.cos(angle)+dz*Math.sin(angle),
                                z:root.assetDrag.z-dx*Math.sin(angle)+dz*Math.cos(angle)}})
                            return
                        }
                        if (!pressed) root.updateWorldHover(mouse.x,mouse.y,false)
                        if (terrainPicking && pressed) {
                            var selectedKey = root.pickTerrainCell(
                                mouse.x,
                                mouse.y
                            )
                            var distanceSinceBrush = Math.hypot(
                                root.terrainBrushX - brushLastX,
                                root.terrainBrushZ - brushLastZ
                            )
                            var shouldPaint = selectedKey
                                && (
                                    selectedKey !== brushLastKey
                                    || !isFinite(brushLastX)
                                    || distanceSinceBrush >= Math.max(
                                        0.5,
                                        root.terrainBrushRadius * 0.35
                                    )
                                )
                            if (
                                root.terrainBrushEnabled
                                && shouldPaint
                            ) {
                                brushLastKey = selectedKey
                                brushLastX = root.terrainBrushX
                                brushLastZ = root.terrainBrushZ
                                root.editTerrain(root.terrainBrushOperation)
                            }
                            return
                        }
                        if (cameraDragging && pressed) {
                            var dx=mouse.x-dragStartX,dy=mouse.y-dragStartY
                            var presses=Object.assign({},pressGestures)
                            for (var key in presses) {
                                presses[key].yaw+=Math.abs(dx*.225)
                                presses[key].pitch+=Math.abs(dy*.15)
                            }
                            pressGestures=presses
                            root.dragCameraLook(dx,dy)
                            dragStartX = mouse.x
                            dragStartY = mouse.y
                        }
                    }

                    onReleased: function(mouse) {
                        if(root.assetDrag.startX!==undefined) {
                            root.assetDrag=({});root.assetEdit({op:"END_TRANSFORM"});return
                        }
                        if (terrainPicking) {
                            terrainPicking = false
                            brushLastKey = ""
                            brushLastX = Number.NaN
                            brushLastZ = Number.NaN
                        } else if (cameraDragging) {
                            root.endCameraLook(mouse.button)
                            cameraDragging = root.mouseLeftHeld || root.mouseRightHeld
                            var gesture=pressGestures[String(mouse.button)]
                            var elapsed=gesture ? Date.now()-gesture.at : 10000
                            var isClick=gesture && !gesture.cancelled && (elapsed<200 || (elapsed<800 && gesture.yaw<2.25 && gesture.pitch<2))
                            var presses=Object.assign({},pressGestures);delete presses[String(mouse.button)];pressGestures=presses
                            if (isClick && !cameraDragging) {
                                if (mouse.button===Qt.LeftButton) root.selectWorld(gesture.id)
                                else if (gesture.id) root.contextWorld(gesture.id)
                            }
                            root.updateWorldHover(mouse.x,mouse.y,true)
                        }
                    }

                    onCanceled: {
                        if(root.assetDrag.startX!==undefined){root.assetDrag=({});root.assetEdit({op:"CANCEL_TRANSFORM"})}
                        terrainPicking = false
                        root.clearMovementInput()
                        cameraDragging = false
                        pressGestures=({})
                    }

                    onWheel: function(wheel) {
                        root.cameraDistance = Math.max(
                            0,
                            Math.min(50, root.cameraDistance
                                - Number(wheel.angleDelta.y) / 120)
                        )
                        root.sendInput()
                        wheel.accepted = true
                    }
                }

                GameNaturePrompt {
                    surface: root
                    z: 12
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.rightMargin: 20
                    anchors.topMargin: 30
                    visible: !root.standalonePlayerMode && root.natureTarget.available
                }

                Rectangle {
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.leftMargin: sidebar.width + 14
                    anchors.topMargin: 12
                    width: hudColumn.implicitWidth + 18
                    height: hudColumn.implicitHeight + 12
                    visible: !root.standalonePlayerMode
                    color: root.panelOverlayRaised
                    border.color: "#4a514f"
                    border.width: 1
                    radius: 2

                    Column {
                        id: hudColumn
                        anchors.centerIn: parent
                        spacing: 3

                        Text {
                            text: "PLAYGROUND · " + String(
                                root.renderStatus.state || root.status.state || "IDLE"
                            )
                            color: root.stateColor(
                                root.renderStatus.state || root.status.state
                            )
                            font.family: "monospace"
                            font.pixelSize: 11
                            font.bold: true
                        }
                        Text {
                            text: "SPEED " + root.fixed(root.player.speed, 1)
                                + "  DRIFT " + root.fixed(root.player.drift, 1)
                            color: root.ink
                            font.family: "monospace"
                            font.pixelSize: 11
                        }
                        Text {
                            text: "ENT " + String(root.simulation.render_entity_count || 0)
                                + " / " + String(root.simulation.active_entities || 0)
                                + "  FX " + String(root.particleBatchCount)
                            color: root.text
                            font.family: "monospace"
                            font.pixelSize: 10
                        }
                        Text {
                            text: root.movementMode + "  CELL "
                                + String(root.player.cell_key || "0:0")
                            color: root.ledgerGold
                            font.family: "monospace"
                            font.pixelSize: 10
                        }
                    }
                }

                Text {
                    objectName: "gameWorldPlaceName"
                    z: 5
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.top: parent.top
                    anchors.topMargin: root.standalonePlayerMode ? 68 : 20
                    visible: root.nearbyWorldPlace.length > 0 && !root.dosFallbackActive
                    text: root.nearbyWorldPlace
                    color: root.ledgerGold
                    font.family: "monospace"
                    font.pixelSize: 15
                    font.letterSpacing: 1.2
                    style: Text.Outline
                    styleColor: "#22352f"
                }

                Rectangle {
                    objectName: "gameWorldConversation"
                    z: 25
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 120
                    width: Math.min(460, parent.width - 40)
                    height: worldConversationColumn.implicitHeight + 28
                    visible: root.standalonePlayerMode && Boolean(root.dialogue.open)
                        && ((root.dialogue.node || {}).choices || []).length > 0
                    color: "#ef1b2927"
                    border.color: root.ledgerGold
                    border.width: 1
                    radius: 3
                    Column {
                        id: worldConversationColumn
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 14
                        spacing: 10
                        Text {
                            width: parent.width
                            text: String((root.dialogue.node || {}).speaker || "NPC")
                            color: root.ledgerGold
                            font.family: "monospace"
                            font.pixelSize: 16
                            font.bold: true
                        }
                        Text {
                            width: parent.width
                            text: String((root.dialogue.node || {}).text || "")
                            color: root.ink
                            font.family: "monospace"
                            font.pixelSize: 13
                            wrapMode: Text.WordWrap
                        }
                        Repeater {
                            model: (root.dialogue.node || {}).choices || []
                            delegate: GgButton {
                                required property var modelData
                                width: worldConversationColumn.width
                                implicitHeight: 28
                                text: String(modelData.label || modelData.id || "")
                                onClicked: {
                                    if (String(modelData.id) === "leave") root.closeDialogue()
                                    else root.talkNpc(String(modelData.id), String((root.dialogue.active || {}).npc_id || ""))
                                }
                            }
                        }
                    }
                }

                // PitBull/oUF-inspired unit state: one compact data frame
                // sits over the world and can later be replaced by an
                // authored layout without changing the simulation contract.
                Rectangle {
                    objectName: "gameEngineUnitFrames"
                    z: 4
                    enabled: false
                    visible: !root.standalonePlayerMode
                        && root.addonEnabled("UNIT_FRAMES")
                    anchors.left: parent.left
                    anchors.bottom: parent.bottom
                    anchors.leftMargin: sidebar.width + 14
                    anchors.bottomMargin: 34
                    width: 252
                    height: 82
                    color: root.panelOverlay
                    border.color: "#4a514f"
                    border.width: 1
                    radius: 2

                    Column {
                        anchors.fill: parent
                        anchors.margins: 8
                        spacing: 3

                        Text {
                            width: parent.width
                            text: "PLAYER  ·  LV "
                                + String(root.progression.level || 1)
                                + "  ·  " + String(
                                    root.player.movement_mode || "GROUND"
                                )
                            color: root.ledgerGreen
                            font.family: "monospace"
                            font.pixelSize: 10
                            font.bold: true
                            elide: Text.ElideRight
                        }
                        Text {
                            width: parent.width
                            text: "HP " + root.fixed(root.combatActor("player").health, 0)
                                + " / " + root.fixed(root.combatActor("player").max_health, 0)
                                + "  ·  RESOURCE " + root.fixed(root.combat.resource, 0)
                                + " / " + String(
                                    root.combat.resource_capacity || 100
                                )
                                + "  ·  SPEED " + root.fixed(root.player.speed, 1)
                            color: root.ink
                            font.family: "monospace"
                            font.pixelSize: 10
                            elide: Text.ElideRight
                        }
                        Rectangle {
                            width: parent.width
                            height: 4
                            color: Qt.rgba(0.02, 0.03, 0.03, 0.34)
                            border.color: Qt.rgba(0.55, 0.68, 0.63, 0.35)
                            border.width: 1

                            Rectangle {
                                width: parent.width * root.percent(
                                    root.combat.resource,
                                    root.combat.resource_capacity || 100
                                )
                                height: parent.height
                                color: root.ledgerGreen
                            }
                        }
                        Text {
                            width: parent.width
                            text: "CELL " + String(root.player.cell_key || "0:0")
                                + "  ·  " + String(root.player.medium || "LAND")
                                + "  ·  TARGET " + (
                                    root.addonEnabled("NPC_TRACKER")
                                        && root.npcInteraction.available
                                        ? String(root.npcInteraction.target_id || "NPC")
                                        : "NONE"
                                )
                            color: root.muted
                            font.family: "monospace"
                            font.pixelSize: 9
                            elide: Text.ElideRight
                        }
                    }
                }

                Text {
                    anchors.left: parent.left
                    anchors.bottom: parent.bottom
                    anchors.leftMargin: sidebar.width + 14
                    anchors.bottomMargin: 12
                    visible: !root.standalonePlayerMode
                    text: "W/S MOVE · A/D TURN · E INTERACT · Q GRAPPLE · RMB CAMERA · SPACE JUMP · SHIFT BOOST · G FLIGHT · V HOVERBOARD · TAB TARGET · T ATTACK · R/F UP/DOWN · MAP: EXPLORE REGIONS"
                    color: root.muted
                    font.family: "monospace"
                    font.pixelSize: 10
                }

                Rectangle {
                    id: planetMapOverlay
                    objectName: "gameEnginePlanetMap"
                    z: 20
                    visible: !root.standalonePlayerMode && root.page === "MAP"
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    anchors.leftMargin: sidebar.width + 14
                    anchors.rightMargin: inspector.width + 14
                    anchors.margins: 12
                    color: "#111b20"
                    border.color: "#8c9f91"
                    border.width: 1

                    Image {
                        id: planetMapImage
                        objectName: "gameEnginePlanetMapImage"
                        anchors.fill: parent
                        anchors.margins: 8
                        source: "../assets/authored/world/gg-first-planet-map.svg"
                        fillMode: Image.PreserveAspectFit
                        smooth: true
                    }

                    Rectangle {
                        id: playerMapMarker
                        objectName: "gameEnginePlanetMapPlayerMarker"
                        width: 14
                        height: 14
                        radius: width / 2
                        color: "#ffe393"
                        border.color: "#33291b"
                        border.width: 2
                        visible: {
                            var bounds = root.planetMap.bounds_m || ({})
                            var x = root.number(root.player.x, 0)
                            var z = root.number(root.player.z, 0)
                            x >= root.number(bounds.min_x, -2650)
                                && x <= root.number(bounds.max_x, 2650)
                                && z >= root.number(bounds.min_z, -2650)
                                && z <= root.number(bounds.max_z, 2650)
                        }
                        x: {
                            var bounds = root.planetMap.bounds_m || ({})
                            var chart = root.planetMap.chart_layout || ({})
                            var mapX = root.number(root.player.x, 0)
                            var span = root.number(bounds.max_x, 2650)
                                - root.number(bounds.min_x, -2650)
                            var fraction = span > 0
                                ? (mapX - root.number(bounds.min_x, -2650)) / span
                                : 0.5
                            var scale = planetMapImage.paintedWidth
                                / root.number(chart.viewbox_width, 1440)
                            return planetMapImage.x
                                + (planetMapImage.width - planetMapImage.paintedWidth) / 2
                                + (root.number(chart.plot_x, 64)
                                    + fraction * root.number(chart.plot_width, 840)) * scale
                                - width / 2
                        }
                        y: {
                            var bounds = root.planetMap.bounds_m || ({})
                            var chart = root.planetMap.chart_layout || ({})
                            var mapZ = root.number(root.player.z, 0)
                            var span = root.number(bounds.max_z, 2650)
                                - root.number(bounds.min_z, -2650)
                            var fraction = span > 0
                                ? (root.number(bounds.max_z, 2650) - mapZ) / span
                                : 0.5
                            var scale = planetMapImage.paintedWidth
                                / root.number(chart.viewbox_width, 1440)
                            return planetMapImage.y
                                + (planetMapImage.height - planetMapImage.paintedHeight) / 2
                                + (root.number(chart.plot_y, 82)
                                    + fraction * root.number(chart.plot_height, 840)) * scale
                                - height / 2
                        }

                        Rectangle {
                            anchors.fill: parent
                            anchors.margins: -4
                            radius: 16
                            color: "transparent"
                            border.color: "#ffe393"
                            border.width: 1
                            opacity: 0.72
                        }
                    }

                    MouseArea {
                        anchors.fill: parent
                        acceptedButtons: Qt.AllButtons
                        onPressed: function(mouse) { mouse.accepted = true }
                        onWheel: function(wheel) { wheel.accepted = true }
                    }
                }
            }

            Rectangle {
                id: inspector
                objectName: "gameEngineInspector"
                z: 30
                visible: !root.standalonePlayerMode
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                anchors.margins: 10
                width: root.inspectorCollapsed
                    ? 34
                    : root.assetEditorMode ? Math.min(390,Math.max(320,parent.width*.36))
                      : Math.max(244, Math.min(286, parent.width * 0.24))
                color: root.panelOverlay
                border.color: "#46504f"
                border.width: 1

                Rectangle {
                    id: inspectorToggle
                    objectName: "gameEngineInspectorToggle"
                    z: 5
                    anchors.top: parent.top
                    anchors.right: parent.right
                    anchors.topMargin: 5
                    anchors.rightMargin: 5
                    width: 24
                    height: 24
                    color: root.inspectorCollapsed
                        ? root.selectedPanel : root.panelOverlayRaised
                    border.color: "#5f646a"
                    border.width: 1

                    Text {
                        anchors.fill: parent
                        text: root.inspectorCollapsed ? "‹" : "›"
                        color: root.ink
                        font.pixelSize: 17
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.inspectorCollapsed =
                            !root.inspectorCollapsed
                    }
                }

                Loader {
                    id: stickyAssetPreview
                    anchors.top:parent.top;anchors.left:parent.left;anchors.right:parent.right
                    anchors.topMargin:38;anchors.leftMargin:10;anchors.rightMargin:10
                    height:active ? 190 : 0
                    active:root.assetEditorMode && !root.inspectorCollapsed
                        && !!((root.assetEditorState.selected || ({})).source)
                        && String(((root.assetEditorState.selected || ({})).detail || ({})).format)!=="GGMESH"
                    sourceComponent:Component {GameAssetPreview {controller:root}}
                }

                Loader {
                    active: inspector.visible && !root.inspectorCollapsed
                    anchors.fill: parent
                    sourceComponent: Component {
                Flickable {
                    anchors.fill: parent
                    anchors.margins: 10
                    anchors.topMargin: 38+stickyAssetPreview.height+(stickyAssetPreview.active ? 8 : 0)
                    clip: true
                    contentWidth: width
                    contentHeight: inspectorColumn.height
                    boundsBehavior: Flickable.StopAtBounds

                    Column {
                        id: inspectorColumn
                        width: parent.width
                        spacing: 10

                        GameAssetInspector {
                            width: parent.width
                            controller: root
                            visible: root.assetEditorMode
                        }

                        Column {
                            width: parent.width
                            spacing: 7
                            visible: root.page === "MAP"

                            Text {
                                text: "PLANET ATLAS"
                                color: root.ledgerGold
                                font.family: "monospace"
                                font.pixelSize: 11
                                font.bold: true
                            }
                            Text {
                                width: parent.width
                                text: String(root.planetMap.planet_id || "SANDOVER_PRIME")
                                    + " · REV " + String(root.planetMap.map_revision || 1)
                                    + "\nFIXED SEED · " + String(root.terrain.world_seed || 0)
                                    + "\nPLAYER X/Z  " + root.fixed(root.player.x, 1)
                                    + " / " + root.fixed(root.player.z, 1)
                                    + " m · CELL " + String(root.player.cell_key || "0:0")
                                color: root.text
                                font.family: "monospace"
                                font.pixelSize: 10
                                wrapMode: Text.WordWrap
                            }
                            Repeater {
                                model: root.planetMap.landmasses || []
                                delegate: Button {
                                    required property var modelData
                                    width: parent.width
                                    text: "EXPLORE " + String(modelData.name || modelData.id)
                                    onClicked: root.exploreRegion(modelData.id)
                                    font.family: "monospace"
                                    font.pixelSize: 9
                                }
                            }
                            Text {
                                width: parent.width
                                text: "PROCEDURAL: water, weather, fish, birds"
                                    + "\nDETERMINISTIC: coast, terrain, seabed"
                                    + "\nATLAS: bounded tangent-region map"
                                color: root.muted
                                font.family: "monospace"
                                font.pixelSize: 9
                                wrapMode: Text.WordWrap
                            }
                        }

                        Column {
                            width: parent.width
                            spacing: 6
                            visible: root.page === "BAG"
                            Text {
                                text: "INVENTORY / EQUIPMENT"
                                color: root.ledgerGold
                                font.family: "monospace"
                            }
                            Repeater {
                                model: (root.items.equipment || []).concat(root.items.inventory || [])
                                delegate: GgButton {
                                    required property var modelData
                                    width: parent.width
                                    implicitHeight: 30
                                    text: String(modelData.name) + " ×" + String(modelData.quantity)
                                        + (modelData.location === "EQUIPPED"
                                            ? " [" + String(modelData.equipped_slot) + "]" : "")
                                        + (modelData.gear
                                            ? " S" + String(modelData.gear.socket_count)
                                                + "/" + String(modelData.gear.socket_capacity)
                                                + (modelData.gear.runeword
                                                    ? " " + String(modelData.gear.runeword.name)
                                                    : "")
                                            : "")
                                    checked: root.selectedItemId === String(modelData.instance_id)
                                    onClicked: root.selectedItemId = String(modelData.instance_id)
                                }
                            }
                            Flow {
                                width: parent.width
                                height: childrenRect.height
                                spacing: 6
                                GgButton {
                                    text: "EQUIP"
                                    implicitWidth: 62
                                    enabled: root.selectedItemId !== ""
                                    onClicked: root.equipItem(root.selectedItemId)
                                }
                                GgButton {
                                    text: "DROP"
                                    implicitWidth: 58
                                    enabled: root.selectedItemId !== ""
                                    onClicked: {
                                        root.dropItem(root.selectedItemId)
                                        root.selectedItemId = ""
                                    }
                                }
                                GgButton {
                                    text: "SOCKET"
                                    implicitWidth: 70
                                    enabled: root.selectedItemId !== ""
                                    onClicked: root.socketItem(root.selectedItemId, "")
                                }
                                GgButton {
                                    text: "APPLY SCROLL"
                                    implicitWidth: 122
                                    enabled: root.selectedItemId !== "" && root.selectedEnchantScrollId !== ""
                                    onClicked: root.enchantGear(root.selectedItemId,
                                        root.selectedEnchantScrollId)
                                }
                            }
                            GameEnchantingControls {
                                width: parent.width
                                game: root
                            }
                            Text {
                                width: parent.width
                                text: "GEAR  " + String(root.gear.runewords || 0)
                                    + " runewords · " + String(root.gear.runes || 0)
                                    + " runes · " + String(root.gear.gems || 0)
                                    + " gems"
                                color: root.ledgerGreen
                                font.family: "monospace"
                                font.pixelSize: 10
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                width: parent.width
                                text: WorldFx.scrollError(String(root.status.error || ""))
                                color: root.signalRed
                                wrapMode: Text.WordWrap
                            }
                        }

                        Column {
                            width: parent.width
                            spacing: 5
                            visible: root.page === "BAG"
                            Text {
                                width: parent.width
                                text: "WALLET  " + String(
                                    root.economy.wallet
                                        ? root.economy.wallet.gold || 0
                                        : 0
                                ) + " GOLD"
                                color: root.ledgerGold
                                font.family: "monospace"
                                font.bold: true
                            }
                            Repeater {
                                model: root.economy.vendors || []
                                delegate: Column {
                                    id: vendorCard
                                    required property var modelData
                                    property var vendorRow: modelData
                                    width: parent.width
                                    spacing: 3
                                    Text {
                                        width: parent.width
                                        text: String(vendorCard.vendorRow.name || "VENDOR")
                                            + " · " + String(
                                                vendorCard.vendorRow.presence
                                                    && vendorCard.vendorRow.presence.available
                                                    ? "READY" : "OUT OF REACH"
                                            )
                                            + " · " + String(vendorCard.vendorRow.gold || 0)
                                            + "G"
                                        color: vendorCard.vendorRow.presence
                                            && vendorCard.vendorRow.presence.available
                                            ? root.ledgerGreen : root.muted
                                        font.family: "monospace"
                                        font.pixelSize: 10
                                        elide: Text.ElideRight
                                    }
                                    Text {
                                        width: parent.width
                                        text: "STOCK " + String(
                                            vendorCard.vendorRow.stock_count || 0
                                        ) + "/" + String(
                                            vendorCard.vendorRow.restock
                                                ? vendorCard.vendorRow.restock.stock_limit || 0
                                                : 0
                                        ) + " · RESTOCK " + String(
                                            vendorCard.vendorRow.restock
                                                ? vendorCard.vendorRow.restock.successful || 0
                                                : 0
                                        )
                                        color: root.muted
                                        font.family: "monospace"
                                        font.pixelSize: 9
                                        elide: Text.ElideRight
                                    }
                                    Text {
                                        width: parent.width
                                        visible: Boolean(
                                            vendorCard.vendorRow.decision
                                                && String(
                                                    vendorCard.vendorRow.decision.action || ""
                                                ) !== ""
                                        )
                                        text: "DECISION " + String(
                                            vendorCard.vendorRow.decision
                                                ? vendorCard.vendorRow.decision.action || ""
                                                : ""
                                        ) + " · " + String(
                                            vendorCard.vendorRow.decision
                                                ? vendorCard.vendorRow.decision.reason || ""
                                                : ""
                                        ) + (
                                            vendorCard.vendorRow.decision
                                                && vendorCard.vendorRow.decision.focus_definition_id
                                                ? " · WANT " + String(
                                                    vendorCard.vendorRow.decision
                                                        .focus_definition_id
                                                )
                                                : ""
                                        )
                                        color: root.ledgerGold
                                        font.family: "monospace"
                                        font.pixelSize: 9
                                        elide: Text.ElideRight
                                    }
                                    Repeater {
                                        model: vendorCard.vendorRow.offers
                                            ? (vendorCard.vendorRow.offers.buy || []) : []
                                        delegate: GgButton {
                                            required property var modelData
                                            width: Math.max(0, vendorCard.width - 16)
                                            implicitHeight: 24
                                            text: "BUY " + String(modelData.item.name || modelData.definition_id)
                                                + " · " + String(modelData.total_price || 0) + "G"
                                            enabled: Boolean(
                                                vendorCard.vendorRow.presence
                                                    && vendorCard.vendorRow.presence.available
                                            ) && root.number(root.economy.wallet
                                                ? root.economy.wallet.gold : 0, 0)
                                                >= root.number(modelData.total_price, 0)
                                            onClicked: root.buyFromVendor(
                                                String(vendorCard.vendorRow.id || ""),
                                                String(modelData.instance_id || "")
                                            )
                                        }
                                    }
                                    Repeater {
                                        model: vendorCard.vendorRow.offers
                                            ? (vendorCard.vendorRow.offers.sell || []) : []
                                        delegate: GgButton {
                                            required property var modelData
                                            width: Math.max(0, vendorCard.width - 16)
                                            implicitHeight: 24
                                            text: "SELL " + String(modelData.item.name || modelData.definition_id)
                                                + " · +" + String(modelData.total_price || 0) + "G"
                                            enabled: Boolean(
                                                vendorCard.vendorRow.presence
                                                    && vendorCard.vendorRow.presence.available
                                            ) && root.number(vendorCard.vendorRow.gold, 0)
                                                >= root.number(modelData.total_price, 0)
                                            onClicked: root.sellToVendor(
                                                String(vendorCard.vendorRow.id || ""),
                                                String(modelData.instance_id || "")
                                            )
                                        }
                                    }
                                }
                            }
                            Text {
                                width: parent.width
                                text: "Physical stock only · every offer has a real instance ID"
                                color: root.muted
                                font.family: "monospace"
                                font.pixelSize: 9
                                wrapMode: Text.WordWrap
                            }
                        }

                        Row {
                            width: parent.width
                            spacing: 8

                            Text {
                                text: root.page
                                color: root.ink
                                font.family: "monospace"
                                font.pixelSize: 15
                                font.bold: true
                            }

                            Text {
                                width: parent.width - 80
                                text: root.legend
                                color: root.ledgerGold
                                font.family: "monospace"
                                font.pixelSize: 10
                                horizontalAlignment: Text.AlignRight
                                verticalAlignment: Text.AlignVCenter
                            }
                        }

                        Rectangle {
                            width: parent.width
                            height: 1
                            color: "#333333"
                        }

                        Column {
                            width: parent.width
                            spacing: 6
                            visible: root.page === "PLAY"

                            Text {
                                width: parent.width
                                text: "LOCAL FIXED-STEP SIMULATION"
                                color: root.ledgerGreen
                                font.family: "monospace"
                                font.pixelSize: 11
                                font.bold: true
                            }

                            Text {
                                width: parent.width
                                text: "A bounded playground for driving, collisions, pooled debris and replay."
                                color: root.text
                                wrapMode: Text.WordWrap
                                font.family: "monospace"
                                font.pixelSize: 10
                            }

                            Row {
                                width: parent.width
                                spacing: 6

                                GgButton {
                                    text: "STEP"
                                    implicitWidth: 58
                                    implicitHeight: 26
                                    enabled: !root.running
                                    onClicked: root.stepRuntime()
                                }
                                GgButton {
                                    text: root.stress ? "NORMAL" : "STRESS"
                                    implicitWidth: 78
                                    implicitHeight: 26
                                    checked: root.stress
                                    onClicked: root.stressRuntime()
                                }
                            }

                            Row {
                                width: parent.width
                                spacing: 4

                                Text {
                                    text: "MODE"
                                    color: root.muted
                                    font.family: "monospace"
                                    font.pixelSize: 10
                                    verticalAlignment: Text.AlignVCenter
                                }

                                Repeater {
                                    model: ["GROUND", "SWIM", "FLY"]
                                    delegate: GgButton {
                                        required property string modelData
                                        text: modelData
                                        implicitWidth: 58
                                        implicitHeight: 25
                                        checked: root.movementMode === modelData
                                        onClicked: root.setMovementMode(modelData)
                                    }
                                }
                            }

                            Row {
                                width: parent.width
                                spacing: 4
                                Text {
                                    text: "STAGE"
                                    color: root.muted
                                    font.family: "monospace"
                                    font.pixelSize: 10
                                    verticalAlignment: Text.AlignVCenter
                                }
                                GgButton {
                                    text: "3D"
                                    implicitWidth: 54
                                    implicitHeight: 24
                                    checked: root.presentationMode === "RICH_3D"
                                    onClicked: root.setPresentationMode("RICH_3D")
                                }
                                GgButton {
                                    text: "DOS"
                                    implicitWidth: 54
                                    implicitHeight: 24
                                    checked: root.dosFallbackActive
                                    onClicked: root.setPresentationMode("DOS_2D")
                                }
                                Text {
                                    text: root.dosFallbackActive
                                        ? "FAILOVER ACTIVE" : "RICH 3D ACTIVE"
                                    color: root.dosFallbackActive
                                        ? root.signalRed : root.ledgerGreen
                                    font.family: "monospace"
                                    font.pixelSize: 10
                                    verticalAlignment: Text.AlignVCenter
                                }
                            }

                            Text {
                                width: parent.width
                                text: "BIOME " + String(root.terrainSurface.biome || "-")
                                    + "  MEDIUM " + String(root.terrainSurface.medium || "-")
                                    + "\nSURFACE " + root.fixed(root.terrainSurface.height_m, 2)
                                    + " m  WATER DEPTH "
                                    + root.fixed(root.terrainSurface.water_depth_m, 2) + " m"
                                color: root.signalBlue
                                font.family: "monospace"
                                font.pixelSize: 10
                                wrapMode: Text.WordWrap
                            }

                            Row {
                                width: parent.width
                                spacing: 5
                                visible: root.addonEnabled("ACTION_BAR")

                                GgButton {
                                    text: "SURGE"
                                    implicitWidth: 64
                                    implicitHeight: 25
                                    onClicked: root.useAbility("ability.surge")
                                }
                                GgButton {
                                    text: "TIDE"
                                    implicitWidth: 56
                                    implicitHeight: 25
                                    onClicked: root.useAbility("ability.undertow")
                                }
                                GgButton {
                                    text: "LEAP"
                                    implicitWidth: 56
                                    implicitHeight: 25
                                    onClicked: root.useAbility("ability.sky_leap")
                                }
                            }

                            Row {
                                width: parent.width
                                spacing: 5
                                GgButton {
                                    text: "FX " + (root.fxPreviewStyle || "OFF")
                                    implicitWidth: 108
                                    implicitHeight: 25
                                    onClicked: {
                                        var count = WorldFx.PREVIEW_STYLES.length
                                        root.fxPreviewIndex = root.fxPreviewIndex >= count - 1
                                            ? -1 : root.fxPreviewIndex + 1
                                        root.refreshRender()
                                    }
                                }
                                Text {
                                    text: "EFFECT PREVIEW"
                                    color: root.muted
                                    font.family: "monospace"
                                    font.pixelSize: 10
                                    verticalAlignment: Text.AlignVCenter
                                }
                            }

                            Column {
                                width: parent.width
                                spacing: 4
                                visible: Boolean(root.dialogue.open)

                                Text {
                                    width: parent.width
                                    text: String((root.dialogue.node || {}).speaker || "NPC")
                                        + " · " + String((root.dialogue.node || {}).text || "")
                                    color: root.ledgerGold
                                    font.family: "monospace"
                                    font.pixelSize: 9
                                    wrapMode: Text.WordWrap
                                }
                                Flow {
                                    width: parent.width
                                    spacing: 4
                                    Repeater {
                                        model: (root.dialogue.node || {}).choices || []
                                        delegate: GgButton {
                                            required property var modelData
                                            text: String(modelData.label || modelData.id || "CHOICE")
                                            implicitWidth: Math.min(176, Math.max(82,
                                                18 + text.length * 6))
                                            implicitHeight: 24
                                            onClicked: root.talkNpc(
                                                String(modelData.id || ""),
                                                String((root.dialogue.active || {}).npc_id
                                                    || root.npcInteraction.target_id || "")
                                            )
                                        }
                                    }
                                }
                            }

                            Row {
                                width: parent.width
                                spacing: 5
                                visible: root.addonEnabled("LOOT_LEDGER")

                                GgButton {
                                    text: "LOOT"
                                    implicitWidth: 56
                                    implicitHeight: 25
                                    onClicked: root.claimLoot()
                                }
                                GgButton {
                                    text: "ENCHANT"
                                    implicitWidth: 78
                                    implicitHeight: 25
                                    onClicked: root.enchantLoot("enchant.wayfinder")
                                }
                                GgButton {
                                    text: "CRAFT"
                                    implicitWidth: 64
                                    implicitHeight: 25
                                    onClicked: root.openCrafting("")
                                }
                                GgButton {
                                    text: "SOCKET"
                                    implicitWidth: 72
                                    implicitHeight: 25
                                    onClicked: root.socketItem("", "")
                                }
                                GgButton {
                                    text: "GEAR CRAFT"
                                    implicitWidth: 86
                                    implicitHeight: 25
                                    onClicked: root.openCrafting("NEAREST")
                                }
                                GgButton {
                                    text: "PACK"
                                    implicitWidth: 58
                                    implicitHeight: 25
                                    onClicked: root.activateContentPack("pack.tidefall-frontier")
                                }
                            }

                            Text {
                                width: parent.width
                                text: "WORLD ITEMS " + String(
                                        root.items.ground ? root.items.ground.length : 0
                                    )
                                    + " · EQUIPPED " + String(
                                        root.items.equipment ? root.items.equipment.length : 0
                                    )
                                    + "\nTARGET " + String(
                                        root.itemInteraction.name || "NONE"
                                    )
                                    + " · " + String(
                                        root.itemInteraction.action || "MOVE CLOSER"
                                    )
                                color: root.signalViolet
                                font.family: "monospace"
                                font.pixelSize: 10
                                wrapMode: Text.WordWrap
                            }

                            Text {
                                width: parent.width
                                text: "LIFE " + String(root.life.population || 0)
                                    + " / " + String(root.life.budget || 0)
                                    + " · " + String(root.life.clock
                                        ? root.life.clock.label : "--:--")
                                    + " " + String(root.life.clock
                                        ? root.life.clock.phase : "-")
                                    + "\nFISH " + String(root.life.activities
                                        ? root.life.activities.FISHING || 0 : 0)
                                    + " · TRAVEL " + String(root.life.activities
                                        ? root.life.activities.TRAVELING || 0 : 0)
                                    + " · SCOUT " + String(root.life.activities
                                        ? root.life.activities.SCOUTING || 0 : 0)
                                    + " · HAUL " + String(root.life.activities
                                        ? root.life.activities.HAULING || 0 : 0)
                                    + " · NOTICE " + String(root.life.stimuli
                                        ? root.life.stimuli.PLAYER_NEAR || 0 : 0)
                                    + "\nPEOPLE " + String(root.people.population || 0)
                                    + " · UNIQUE " + String(root.people.unique_names || 0)
                                    + " · MEMORY " + String(root.people.memory_events || 0)
                                color: root.ledgerGreen
                                font.family: "monospace"
                                font.pixelSize: 10
                                wrapMode: Text.WordWrap
                            }

                            Row {
                                width: parent.width
                                spacing: 5
                                GgButton {
                                    text: "INTERACT"
                                    implicitWidth: 76
                                    implicitHeight: 25
                                    onClicked: root.interactItem()
                                }
                                GgButton {
                                    text: "PICKUP"
                                    implicitWidth: 62
                                    implicitHeight: 25
                                    onClicked: root.pickupItem("")
                                }
                                GgButton {
                                    text: "EQUIP"
                                    implicitWidth: 58
                                    implicitHeight: 25
                                    onClicked: root.equipItem("")
                                }
                            }

                            Row {
                                width: parent.width
                                spacing: 5
                                GgButton {
                                    text: root.bank.nearby ? "OPEN BANK" : "OPEN CACHE"
                                    implicitWidth: root.bank.nearby ? 102 : 88
                                    implicitHeight: 25
                                    onClicked: root.openContainer(
                                        root.bank.nearby
                                            ? String(root.bank.container_id || "") : ""
                                    )
                                }
                                GgButton {
                                    text: "LOOT CACHE"
                                    implicitWidth: 88
                                    implicitHeight: 25
                                    onClicked: root.lootContainer("")
                                }
                                GgButton {
                                    text: "DROP"
                                    implicitWidth: 52
                                    implicitHeight: 25
                                    onClicked: root.dropItem("")
                                }
                            }

                            Text {
                                width: parent.width
                                text: "RESOURCE " + root.fixed(root.combat.resource, 0)
                                    + " / 100  ·  LV " + String(root.progression.level || 1)
                                    + "  ·  XP " + String(root.progression.xp || 0)
                                color: root.ledgerGold
                                font.family: "monospace"
                                font.pixelSize: 10
                            }

                            Text {
                                width: parent.width
                                text: "CTRL " + String(
                                    root.controller.model
                                        || "WOW_CLASSIC_THIRD_PERSON"
                                )
                                    + "\nINPUT CHARACTER_FORWARD_RIGHT · " + String(
                                        root.controller.movement_grammar
                                            || "W_S_MOVE_A_D_TURN_Q_E_STRAFE"
                                    )
                                    + "\nGROUND "
                                    + (root.player.grounded ? "YES" : "AIR")
                                    + "  SPRINT "
                                    + (root.player.sprinting ? "ON" : "OFF")
                                    + "\nCAM "
                                    + root.fixed(root.controller.camera
                                        ? root.controller.camera.distance_m : 12, 1)
                                    + " m  PITCH "
                                    + root.fixed(root.controller.camera
                                        ? root.controller.camera.pitch : -27, 1)
                                color: root.signalViolet
                                font.family: "monospace"
                                font.pixelSize: 10
                                wrapMode: Text.WordWrap
                            }

                            Text {
                                width: parent.width
                                text: "FIELD LEDGER " + String(
                                    root.physics.model || "TSEU_INSPIRED_BOOKKEEPING"
                                )
                                    + "\nE " + root.fixed(root.physics.total_energy, 2)
                                    + "  M " + root.fixed(root.physics.mass_equivalent, 3)
                                    + "  |V| " + root.fixed(root.physics.speed, 2)
                                    + "\nGRAVITY " + String(
                                        root.physics.gravity_status || "NOT_CONNECTED"
                                    )
                                color: root.signalViolet
                                font.family: "monospace"
                                font.pixelSize: 10
                                wrapMode: Text.WordWrap
                            }

                            Text {
                                width: parent.width
                                visible: root.addonEnabled("NPC_TRACKER")
                                text: "NPC " + String(root.npc.active || 0)
                                    + " / " + String(root.npc.capacity || 0)
                                    + "  ·  AI " + String(root.npc.decision_hz || 20)
                                    + " HZ"
                                    + "\nWANDER " + String(root.npc.states
                                        ? root.npc.states.WANDER || 0 : 0)
                                    + "  FOLLOW " + String(root.npc.states
                                        ? root.npc.states.FOLLOW || 0 : 0)
                                    + "  ALERT " + String(root.npc.states
                                        ? root.npc.states.ALERT || 0 : 0)
                                    + "  FLEE " + String(root.npc.states
                                        ? root.npc.states.FLEE || 0 : 0)
                                    + "  DEAD " + String(root.npc.states
                                        ? root.npc.states.DEAD || 0 : 0)
                                    + "\nSENSE " + String(root.npc.perception
                                        || "RADIAL_LOS_BOUNDED")
                                    + "\nNAV " + String(root.npc.navigation
                                        || "DIRECT_STEERING_BOUNDED")
                                    + "\nPATH " + String(root.navigation.model
                                        || "TILED_HEIGHTFIELD_ASTAR")
                                    + "  " + String(root.navigation.walkable_tiles
                                        || 0) + "/" + String(
                                            root.navigation.streaming
                                                ? root.navigation.streaming.loaded_tiles
                                                : 0
                                        )
                                color: root.ledgerGreen
                                font.family: "monospace"
                                font.pixelSize: 10
                                wrapMode: Text.WordWrap
                            }

                            Repeater {
                                model: (root.npc.agents || []).slice(0, 4)
                                visible: root.addonEnabled("NPC_TRACKER")
                                delegate: Text {
                                    required property var modelData
                                    width: parent.width
                                    text: "· " + String(modelData.archetype || "NPC")
                                        + " / " + String(modelData.state || "WANDER")
                                    + "  " + root.fixed(modelData.x, 1)
                                        + "," + root.fixed(modelData.z, 1)
                                        + "  S " + root.fixed(modelData.speed, 1)
                                    + "  HP " + root.fixed(
                                        modelData.combat
                                            ? modelData.combat.health : 0,
                                        0
                                    ) + "/" + root.fixed(
                                        modelData.combat
                                            ? modelData.combat.max_health : 0,
                                        0
                                    )
                                    + "  " + (modelData.line_of_sight
                                            ? "LOS" : "NO-LOS")
                                    + "  " + String(modelData.stimulus || "NONE")
                                    + "  PATH " + String(modelData.path_status || "-")
                                        + "/" + String(modelData.path_nodes || 0)
                                    + "\n  USE " + String(
                                        modelData.individual
                                            && modelData.individual.world_action
                                            ? (modelData.individual.world_action.last_action
                                                || "NONE")
                                            : "NONE"
                                    ) + " " + String(
                                        modelData.individual
                                            && modelData.individual.world_action
                                            ? (modelData.individual.world_action.status
                                                || "NONE")
                                            : "NONE"
                                    ) + " #" + String(
                                        modelData.individual
                                            && modelData.individual.world_action
                                            ? (modelData.individual.world_action.count
                                                || 0)
                                            : 0
                                    ) + "\n  LV " + String(
                                        modelData.individual
                                            && modelData.individual.progression
                                            ? (modelData.individual.progression.level || 1)
                                            : 1
                                    ) + " / " + String(
                                        modelData.individual
                                            && modelData.individual.progression
                                            ? (modelData.individual.progression.spec || "EXPLORER")
                                            : "EXPLORER"
                                    ) + "  PWR " + root.fixed(
                                        modelData.individual
                                            && modelData.individual.progression
                                            ? (modelData.individual.progression.power_score || 0)
                                            : 0,
                                        0
                                    ) + "  GEAR " + root.fixed(
                                        modelData.individual
                                            && modelData.individual.progression
                                            ? (modelData.individual.progression.gear_score || 0)
                                            : 0,
                                        0
                                    )
                                    color: String(modelData.state || "") === "FLEE"
                                        ? root.signalRed : root.text
                                    font.family: "monospace"
                                    font.pixelSize: 9
                                    elide: Text.ElideRight
                                }
                            }

                            Text {
                                width: parent.width
                                text: "WORLD POP " + String(root.livingWorld.promoted_count || 0)
                                    + "/" + String(root.livingWorld.promotion_budget || 0)
                                    + " PROMOTED  AMBIENT " + String(
                                        root.livingWorld.ambient_count || 0
                                    ) + "  SOCIAL " + String(
                                        root.social.relationship_count || 0
                                    ) + "  EVENTS " + String(
                                        root.worldEvents.active_count || 0
                                    ) + "  PACKS " + String(
                                        root.contentPacks.active_count || 0
                                    )
                                color: root.muted
                                font.family: "monospace"
                                font.pixelSize: 9
                                elide: Text.ElideRight
                            }

                            Row {
                                width: parent.width
                                spacing: 5
                                visible: root.addonEnabled("NPC_TRACKER")
                                GgButton {
                                    text: "ATTACK"
                                    implicitWidth: 70
                                    implicitHeight: 24
                                    enabled: Boolean(root.npcInteraction.available)
                                    onClicked: root.attackNpc(
                                        root.npcInteraction.target_id || ""
                                    )
                                }
                                GgButton {
                                    text: "INTERACT"
                                    implicitWidth: 76
                                    implicitHeight: 24
                                    enabled: Boolean(root.npcInteraction.available)
                                    onClicked: root.interactNpc()
                                }
                                Text {
                                    width: parent.width - 151
                                    text: root.npcInteraction.available
                                        ? String(root.npcInteraction.target_id || "NPC")
                                            + " · " + root.fixed(
                                                root.npcInteraction.target_distance_m,
                                                1
                                            ) + " m"
                                        : "NO NPC IN TALK RADIUS"
                                    color: root.npcInteraction.available
                                        ? root.ledgerGold : root.muted
                                    font.family: "monospace"
                                    font.pixelSize: 9
                                    verticalAlignment: Text.AlignVCenter
                                    elide: Text.ElideRight
                                }
                            }

                            Row {
                                width: parent.width
                                spacing: 5
                                GgButton {
                                    text: "ACCEPT QUEST"
                                    implicitWidth: 108
                                    implicitHeight: 24
                                    onClicked: root.acceptQuest("quest.shoreline-first")
                                }
                                GgButton {
                                    text: "CLAIM QUEST"
                                    implicitWidth: 104
                                    implicitHeight: 24
                                    enabled: (root.quests.ready || 0) > 0
                                    onClicked: root.claimQuest("")
                                }
                                Text {
                                    width: parent.width - 222
                                    text: "ACTIVE " + String(root.quests.active_count || 0)
                                        + " READY " + String(root.quests.ready || 0)
                                    color: root.ledgerGold
                                    font.family: "monospace"
                                    font.pixelSize: 9
                                    verticalAlignment: Text.AlignVCenter
                                    elide: Text.ElideRight
                                }
                            }

                            Row {
                                width: parent.width
                                spacing: 5
                                GgButton {
                                    text: "+25 XP"
                                    implicitWidth: 68
                                    implicitHeight: 24
                                    onClicked: root.gainXp(25)
                                }
                                GgButton {
                                    text: "TALENT +"
                                    implicitWidth: 78
                                    implicitHeight: 24
                                    onClicked: root.spendTalent("trailblazer")
                                }
                            }

                            Row {
                                width: parent.width
                                spacing: 6

                                GgButton {
                                    text: root.recording ? "STOP REC" : "RECORD"
                                    implicitWidth: 88
                                    implicitHeight: 26
                                    checked: root.recording
                                    onClicked: root.recording
                                        ? root.stopRecording()
                                        : root.startRecording()
                                }
                                GgButton {
                                    text: "REPLAY"
                                    implicitWidth: 74
                                    implicitHeight: 26
                                    enabled: !root.recording
                                    onClicked: root.replayRuntime()
                                }
                            }

                            Text {
                                width: parent.width
                                text: "INPUT  F " + root.fixed(root.throttle, 1)
                                    + "  TURN " + root.fixed(root.steer, 1)
                                    + "  STRAFE " + root.fixed(root.strafe, 1)
                                    + "  V " + root.fixed(root.vertical, 1)
                                    + "  SPRINT " + (root.boost ? "ON" : "OFF")
                                color: root.text
                                font.family: "monospace"
                                font.pixelSize: 10
                            }

                            Text {
                                width: parent.width
                                text: "TICK " + String(root.simulation.tick || 0)
                                    + "  TIME " + root.fixed(root.simulation.time_s, 2) + "s"
                                    + "\nEVENTS " + String(root.eventJournal.count || root.events.length || 0)
                                    + "  REPLAY " + String(root.replay.recorded_inputs || 0)
                                color: root.muted
                                font.family: "monospace"
                                font.pixelSize: 10
                            }

                            Rectangle {
                                width: parent.width
                                height: 1
                                color: "#333333"
                            }

                            Text {
                                text: "EVENT STREAM"
                                color: root.ledgerGold
                                font.family: "monospace"
                                font.pixelSize: 10
                                font.bold: true
                            }

                            Repeater {
                                model: root.events.slice(0, 6)
                                delegate: Text {
                                    required property var modelData
                                    width: parent.width
                                    text: String(modelData.kind || "") + " · "
                                        + String(modelData.text || "")
                                    color: root.text
                                    elide: Text.ElideRight
                                    font.family: "monospace"
                                    font.pixelSize: 10
                                }
                            }
                        }

                        Column {
                            width: parent.width
                            spacing: 6
                            visible: root.page === "SCENE"

                            Text {
                                text: "SCENE INSPECTOR"
                                color: root.ledgerGreen
                                font.family: "monospace"
                                font.pixelSize: 11
                                font.bold: true
                            }
                            Text {
                                width: parent.width
                                text: "ACTIVE " + String(root.simulation.active_entities || 0)
                                    + " / " + String(root.simulation.entity_capacity || 0)
                                    + "\nRENDER " + String(root.simulation.render_entity_count || 0)
                                    + " · CHUNKS " + String(root.chunks.loaded_count || 0)
                                    + "\nTERRAIN " + String(root.terrain.streaming
                                        ? root.terrain.streaming.loaded_count : 0)
                                        + " · LOD " + String(root.terrain.streaming
                                        ? root.terrain.streaming.render_candidates : 0)
                                    + "\nNAV " + String(root.navigation.walkable_tiles
                                        || 0) + " WALK / " + String(
                                            root.navigation.blocked_tiles || 0
                                        ) + " BLOCK"
                                    + "\nEDITOR " + String(root.editor.placement_count || 0)
                                    + " / " + String(root.editor.budget
                                        ? root.editor.budget.placements : 128)
                                color: root.text
                                font.family: "monospace"
                                font.pixelSize: 10
                            }
                            Text {
                                width: parent.width
                                text: "TARGET " + (root.terrainTargetSelected
                                    ? root.terrainTargetKey : "PLAYER CELL")
                                    + "  ·  SHIFT+CLICK / DRAG"
                                    + "\nPOINT " + root.fixed(root.terrainBrushX, 1)
                                    + "," + root.fixed(root.terrainBrushZ, 1)
                                    + "  ·  R " + root.fixed(root.terrainBrushRadius, 1)
                                    + " m"
                                    + "\nBRUSH " + (root.terrainBrushEnabled
                                        ? "ON · " + root.terrainBrushOperation
                                        : "OFF")
                                    + "  ·  " + root.terrainBrushFalloff
                                color: root.terrainTargetSelected
                                    ? root.ledgerGold : root.muted
                                font.family: "monospace"
                                font.pixelSize: 10
                                wrapMode: Text.WordWrap
                            }
                            Row {
                                width: parent.width
                                spacing: 4
                                GgButton {
                                    text: root.terrainBrushEnabled
                                        ? "BRUSH ON" : "BRUSH OFF"
                                    implicitWidth: 86
                                    implicitHeight: 24
                                    checked: root.terrainBrushEnabled
                                    onClicked: root.terrainBrushEnabled =
                                        !root.terrainBrushEnabled
                                }
                                GgButton {
                                    text: "CLEAR TARGET"
                                    implicitWidth: 102
                                    implicitHeight: 24
                                    enabled: root.terrainTargetSelected
                                    onClicked: root.clearTerrainTarget()
                                }
                            }
                            Row {
                                width: parent.width
                                spacing: 4
                                GgButton {
                                    text: "R-"
                                    implicitWidth: 34
                                    implicitHeight: 24
                                    onClicked: root.adjustTerrainBrushRadius(-1)
                                }
                                Text {
                                    width: 54
                                    text: root.fixed(root.terrainBrushRadius, 1) + " m"
                                    color: root.text
                                    font.family: "monospace"
                                    font.pixelSize: 10
                                    verticalAlignment: Text.AlignVCenter
                                    horizontalAlignment: Text.AlignHCenter
                                }
                                GgButton {
                                    text: "R+"
                                    implicitWidth: 34
                                    implicitHeight: 24
                                    onClicked: root.adjustTerrainBrushRadius(1)
                                }
                                GgButton {
                                    text: "F " + root.terrainBrushFalloff
                                    implicitWidth: 108
                                    implicitHeight: 24
                                    onClicked: root.cycleTerrainBrushFalloff()
                                }
                            }
                            Row {
                                width: parent.width
                                spacing: 5
                                GgButton {
                                    text: "PLACE PROP"
                                    implicitWidth: 92
                                    implicitHeight: 25
                                    onClicked: root.placeEditorObject("PROP")
                                }
                                GgButton {
                                    text: "PLACE RAMP"
                                    implicitWidth: 92
                                    implicitHeight: 25
                                    onClicked: root.placeEditorObject("RAMP")
                                }
                            }
                            Row {
                                width: parent.width
                                spacing: 5
                                GgButton {
                                    text: "PLACE NPC"
                                    implicitWidth: 92
                                    implicitHeight: 25
                                    onClicked: root.placeEditorObject("NPC")
                                }
                                Text {
                                    width: parent.width - 97
                                    text: "WANDERER · bounded local AI"
                                    color: root.ledgerGreen
                                    font.family: "monospace"
                                    font.pixelSize: 10
                                    verticalAlignment: Text.AlignVCenter
                                    elide: Text.ElideRight
                                }
                            }
                            Row {
                                width: parent.width
                                spacing: 4
                                GgButton {
                                    text: "RAISE"
                                    implicitWidth: 54
                                    implicitHeight: 24
                                    onClicked: root.editTerrain("RAISE")
                                }
                                GgButton {
                                    text: "LOWER"
                                    implicitWidth: 54
                                    implicitHeight: 24
                                    onClicked: root.editTerrain("LOWER")
                                }
                                GgButton {
                                    text: "LAND"
                                    implicitWidth: 50
                                    implicitHeight: 24
                                    onClicked: root.editTerrain("LAND")
                                }
                                GgButton {
                                    text: "WATER"
                                    implicitWidth: 58
                                    implicitHeight: 24
                                    onClicked: root.editTerrain("WATER")
                                }
                            }
                            Row {
                                width: parent.width
                                spacing: 4
                                GgButton {
                                    text: "REEF"
                                    implicitWidth: 50
                                    implicitHeight: 24
                                    onClicked: root.editTerrain("REEF")
                                }
                                GgButton {
                                    text: "ISLAND"
                                    implicitWidth: 58
                                    implicitHeight: 24
                                    onClicked: root.editTerrain("ISLAND")
                                }
                                GgButton {
                                    text: "CLEAR"
                                    implicitWidth: 54
                                    implicitHeight: 24
                                    onClicked: root.editTerrain("CLEAR")
                                }
                                GgButton {
                                    text: "UNDO TERRAIN"
                                    implicitWidth: 92
                                    implicitHeight: 24
                                    onClicked: root.undoTerrain()
                                }
                            }
                            Row {
                                width: parent.width
                                spacing: 5
                                GgButton {
                                    text: "UNDO"
                                    implicitWidth: 64
                                    implicitHeight: 25
                                    onClicked: root.undoEditorObject()
                                }
                                GgButton {
                                    text: "DIORAMA"
                                    implicitWidth: 76
                                    implicitHeight: 25
                                    checked: root.cinematic.preset === "FIRST_ISLAND_DIORAMA"
                                    onClicked: root.setCinematicPreset("FIRST_ISLAND_DIORAMA")
                                }
                                GgButton {
                                    text: "ORBIT"
                                    implicitWidth: 58
                                    implicitHeight: 25
                                    checked: root.cinematic.preset === "ORBIT_WORLD_SCALE"
                                    onClicked: root.setCinematicPreset("ORBIT_WORLD_SCALE")
                                }
                            }
                            Text {
                                width: parent.width
                                text: "PRESET " + String(root.cinematic.preset || "FIRST_ISLAND_DIORAMA")
                                    + "\nAUTHORING " + String(root.editor.authoring || "LOCAL")
                                    + "\nSTREAM " + String(root.terrain.streaming
                                        ? root.terrain.streaming.policy : "-")
                                    + "\nTRANSITION " + String(root.terrain.transition
                                        ? root.terrain.transition.land_water_air : "-")
                                    + "\nTERRAIN EDIT " + String(root.terrainEditor.override_count || 0)
                                        + " / " + String(root.terrainEditor.budget
                                            ? root.terrainEditor.budget.cells : 64)
                                color: root.ledgerGold
                                font.family: "monospace"
                                font.pixelSize: 10
                                wrapMode: Text.WordWrap
                            }
                            Repeater {
                                model: root.page === 'SCENE' ? Math.min(20,root.renderEntities.length) : 0
                                delegate: Rectangle {
                                    required property int index
                                    readonly property var modelData: root.renderEntities[index] || ({})
                                    width: parent.width
                                    height: 23
                                    color: index % 2 ? "transparent" : "#1e2020"

                                    Text {
                                        anchors.left: parent.left
                                        anchors.leftMargin: 5
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: String(parent.modelData.id || "") + "  "
                                            + String(parent.modelData.kind || "")
                                        color: parent.modelData.kind === "PLAYER"
                                            ? root.ledgerGold : root.text
                                        font.family: "monospace"
                                        font.pixelSize: 10
                                    }
                                    Text {
                                        anchors.right: parent.right
                                        anchors.rightMargin: 5
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: root.fixed(parent.modelData.x, 1)
                                            + "," + root.fixed(parent.modelData.z, 1)
                                        color: root.muted
                                        font.family: "monospace"
                                        font.pixelSize: 10
                                    }
                                }
                            }
                        }

                        Column {
                            width: parent.width
                            spacing: 7
                            visible: root.page === "PERF"

                            Text {
                                text: "PERFORMANCE CONTRACT"
                                color: root.ledgerGreen
                                font.family: "monospace"
                                font.pixelSize: 11
                                font.bold: true
                            }

                            Text {
                                width: parent.width
                                text: "FIXED HZ     " + String(root.simulation.fixed_hz || 60)
                                + "\nDT           " + root.fixed(root.simulation.dt_ms, 3) + " ms"
                                + "\nRENDER UPDATE " + String(root.renderUpdateHz) + " Hz"
                                    + "\nLAST TICK    " + root.fixed(root.simulation.last_tick_ms, 3) + " ms"
                                    + "\nMAX TICK     " + root.fixed(root.simulation.max_tick_ms, 3) + " ms"
                                + "\nDRAW CALLS   " + (
                                    root.render.draw_calls === null
                                        || root.render.draw_calls === undefined
                                        ? "GPU COUNTER N/A"
                                        : String(root.render.draw_calls)
                                )
                                    + "\nVISIBLE      " + String(root.render.visibility
                                        ? root.render.visibility.visible_instances : 0)
                                    + "\nTERRAIN      " + String(root.terrain.streaming
                                        ? root.terrain.streaming.loaded_count : 0)
                                    + " CELLS / " + String(root.terrain.streaming
                                        ? root.terrain.streaming.render_triangles : 0)
                                        + " TRI"
                                color: root.text
                                font.family: "monospace"
                                font.pixelSize: 10
                            }

                            Row {
                                width: parent.width
                                spacing: 4
                                Text {
                                    text: "PROFILE"
                                    color: root.muted
                                    font.family: "monospace"
                                    font.pixelSize: 10
                                    verticalAlignment: Text.AlignVCenter
                                }
                                Repeater {
                                    model: ["POTATO", "PS2_CLASSIC", "BALANCED", "MODERN", "CINEMATIC"]
                                    delegate: GgButton {
                                        required property string modelData
                                        text: modelData === "PS2_CLASSIC"
                                            ? "PS2" : modelData
                                        implicitWidth: modelData === "PS2_CLASSIC" ? 50 : 61
                                        implicitHeight: 24
                                        checked: root.render.profile === modelData
                                        onClicked: root.setRenderProfile(modelData)
                                    }
                                }
                            }

                            Text {
                                width: parent.width
                                text: root.page !== "PERF" ? "" : (
                                    "AA           " + String(root.render.anti_aliasing
                                        ? root.render.anti_aliasing.mode : "-")
                                    + "\nUPSCALER     " + String(root.render.upscaling
                                        ? root.render.upscaling.mode : "-")
                                    + "\nSNAPSHOT     " + root.fixed(root.render.measurement
                                        ? root.render.measurement.snapshot_build_ms : 0, 3) + " ms"
                                    + "\nQT FRAME     " + root.fixed(view3d.renderStats
                                        ? view3d.renderStats.frameTime : 0, 3) + " ms"
                                    + " · RENDER CPU " + root.fixed(view3d.renderStats
                                        ? view3d.renderStats.renderTime : 0, 3) + " ms"
                                )
                                color: root.ledgerGold
                                font.family: "monospace"
                                font.pixelSize: 10
                                wrapMode: Text.WordWrap
                            }

                            Text {
                                width: parent.width
                                text: "OPTIONAL GPU  DLSS / FSR / XeSS\n"
                                    + "STATUS         runtime probe required"
                                color: root.muted
                                font.family: "monospace"
                                font.pixelSize: 10
                            }

                            Text {
                                width: parent.width
                                text: "ENTITY POOL  " + String(root.simulation.active_entities || 0)
                                    + " / " + String(root.simulation.entity_capacity || 0)
                                    + "\nPARTICLE POOL " + String(root.simulation.active_particles || 0)
                                    + " / " + String(root.simulation.particle_capacity || 0)
                                color: root.text
                                font.family: "monospace"
                                font.pixelSize: 10
                            }

                            Rectangle {
                                width: parent.width
                                height: 8
                                color: "#252928"
                                border.color: "#454b49"
                                border.width: 1
                                Rectangle {
                                    height: parent.height
                                    width: parent.width * root.percent(
                                        root.simulation.active_entities,
                                        root.simulation.entity_capacity
                                    )
                                    color: root.ledgerGreen
                                }
                            }
                            Rectangle {
                                width: parent.width
                                height: 8
                                color: "#252928"
                                border.color: "#454b49"
                                border.width: 1
                                Rectangle {
                                    height: parent.height
                                    width: parent.width * root.percent(
                                        root.simulation.active_particles,
                                        root.simulation.particle_capacity
                                    )
                                    color: root.signalViolet
                                }
                            }
                        }

                        Column {
                            width: parent.width
                            spacing: 7
                            visible: root.page === "NET"

                            Text {
                                text: "NETWORK SEAM"
                                color: root.ledgerGreen
                                font.family: "monospace"
                                font.pixelSize: 11
                                font.bold: true
                            }
                            Text {
                                width: parent.width
                                text: "MODE          " + String(root.network.mode || "LOCAL_LOOPBACK")
                                    + "\nTRANSPORT     " + String(root.network.transport || "NOT_CONNECTED")
                                    + "\nSERVER        " + (root.network.authoritative_server ? "YES" : "NO")
                                    + "\nSNAPSHOT HZ   " + String(root.network.snapshot_hz || 20)
                                    + "\nSEQUENCE      " + String(root.network.sequence || 0)
                                    + "\nEST. BYTES    " + String(root.network.estimated_bytes || 0)
                                    + "\nINTEREST      " + String(root.network.interest_entities || 0)
                                color: root.text
                                font.family: "monospace"
                                font.pixelSize: 10
                            }
                            Row {
                                width: parent.width
                                spacing: 5
                                GgButton {
                                    text: "SAVE MEMORY"
                                    implicitWidth: 104
                                    implicitHeight: 25
                                    onClicked: root.saveGameState()
                                }
                                GgButton {
                                    text: "LOAD MEMORY"
                                    implicitWidth: 104
                                    implicitHeight: 25
                                    onClicked: root.loadGameState()
                                }
                            }
                            Text {
                                width: parent.width
                                text: "PERSISTENCE " + String(root.network.persistence
                                    ? root.network.persistence.mode : "MEMORY_ONLY")
                                    + " · REV " + String(root.network.persistence
                                        ? root.network.persistence.revision : 0)
                                    + "\nNo live server, sockets or account access are enabled."
                                color: root.muted
                                wrapMode: Text.WordWrap
                                font.family: "monospace"
                                font.pixelSize: 10
                            }
                        }

                        Column {
                            width: parent.width
                            spacing: 7
                            visible: root.page === "ASSETS" && !root.assetEditorMode

                            Text {
                                text: "ASSET / RUNTIME BOUNDARY"
                                color: root.ledgerGreen
                                font.family: "monospace"
                                font.pixelSize: 11
                                font.bold: true
                            }
                            Text {
                                width: parent.width
                                text: "FORMAT         " + String(root.selectedAsset.format || "-")
                                    + "\nSOURCE         " + String(
                                        root.selectedAsset.relative_source || "none"
                                    )
                                    + "\nSTATUS         " + String(
                                        root.selectedAsset.status || "NO_ASSET"
                                    )
                                    + " · " + String(
                                        root.selectedAsset.mode || "PREVIEW_FALLBACK"
                                    )
                                    + "\nRUNTIME        QtQuick3D RuntimeLoader"
                                color: root.text
                                font.family: "monospace"
                                font.pixelSize: 10
                            }
                            Text {
                                width: parent.width
                                text: "SKIN           " + String(
                                        root.selectedAsset.skinned ? "READY" : "NO"
                                    )
                                    + " · " + String(
                                        root.selectedAsset.skeleton
                                            ? root.selectedAsset.skeleton.joints : 0
                                    ) + " joints · " + String(
                                        root.selectedAsset.vertices || 0
                                    ) + " vertices"
                                    + "\nCLIPS          " + root.assetClipSummary()
                                    + "\nAUTHORED       " + String(
                                        root.render.asset_instances
                                            ? root.render.asset_instances.authored_requested
                                            : 0
                                    ) + "/" + String(
                                        root.assets.crowd_instance_budget
                                            || root.assetInstanceBudget
                                    )
                                    + " instances"
                                    + "\nRIGS           " + String(root.assetInstanceBudget)
                                    + " full · remainder Blender crowd LOD"
                                    + "\nCHARACTERS     one active low-poly model"
                                    + "\nCROWD          " + String(
                                        root.assets.crowd_selected
                                            ? root.assets.crowd_selected.mode
                                            : "NO_ASSET"
                                    ) + " · " + String(
                                        root.assets.crowd_selected
                                            ? root.assets.crowd_selected.animations : 0
                                    ) + " clips"
                                    + "\nSTYLE          " + String(
                                        root.assets.character_style
                                            ? root.assets.character_style.id
                                            : "-"
                                    ) + " · matte faceted"
                                    + "\nPROCEDURAL     " + String(
                                        root.render.asset_instances
                                            ? root.render.asset_instances
                                                .procedural_requested : 0
                                    ) + " active · " + String(
                                        root.assets.character_style
                                            ? root.assets.character_style.crowd_triangle_budget
                                            : 0
                                    ) + " tris"
                                    + "\nPOSE SEAM      IDLE/WALK/SPRINT/AIR → fixed-step geometry/timeline"
                                color: root.ledgerGreen
                                font.family: "monospace"
                                font.pixelSize: 10
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                width: parent.width
                                text: "CONTENT       " + String(root.content.abilities || 0)
                                    + " abilities · " + String(root.content.items || 0) + " items"
                                    + "\nRECIPES       " + String(root.content.recipes || 0)
                                    + " · AFFIXES " + String(root.content.affixes || 0)
                                    + "\nGEAR          " + String(root.content.gear_slots || 0)
                                    + " slots · " + String(root.content.runes || 0)
                                    + " runes · " + String(root.content.gems || 0)
                                    + " gems · " + String(root.content.runewords || 0)
                                    + " runewords"
                                    + "\nCRAFTING      " + String(root.content.workstations || 0)
                                    + " stations · " + String(root.content.gear_recipes || 0)
                                    + " recipes · " + String(root.content.gear_materials || 0)
                                    + " materials"
                                    + "\nCLASS         " + String(root.progression.class_id || "-")
                                    + " / " + String(root.progression.spec || "-")
                                    + "\nTALENTS       " + String(root.progression.talent_points || 0)
                                    + " points · ASC " + String(root.progression.ascension || 0)
                                color: root.ledgerGold
                                font.family: "monospace"
                                font.pixelSize: 10
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                width: parent.width
                                text: "ITEM GRAPH    " + String(
                                        root.items.catalog
                                            ? root.items.catalog.definitions : 0
                                    ) + " definitions · " + String(
                                        root.items.catalog
                                            ? root.items.catalog.loot_tables : 0
                                    ) + " loot tables"
                                    + "\n3D STATES     GROUND · CONTAINER · INVENTORY"
                                    + " · EQUIPPED · POCKET"
                                    + "\nRARITY        TRASH · COMMON · UNCOMMON · RARE"
                                    + " · EPIC · LEGENDARY · ARTIFACT"
                                    + "\nWORLD         " + String(
                                        root.items.counts
                                            ? root.items.counts.player_owned : 0
                                    ) + " player-owned · " + String(
                                        root.items.instances || 0
                                    ) + " live instances"
                                    + "\nAUTHORED ITEM " + String(
                                        root.render.item_asset_instances
                                            ? root.render.item_asset_instances.authored_requested
                                            : 0
                                    ) + "/" + String(
                                        root.render.item_asset_instances
                                            ? root.render.item_asset_instances.budget : 0
                                    ) + " RuntimeLoader · " + String(
                                        root.render.item_asset_instances
                                            ? root.render.item_asset_instances.primitive_fallback : 0
                                    ) + " primitive fallback"
                                    + "\nLIFE          " + String(root.life.population || 0)
                                    + " proxies · " + String(root.life.clock
                                        ? root.life.clock.phase : "-")
                                    + " · " + String(root.life.simulation || "-")
                                    + "\nASSET TABLE   " + String(root.items.catalog
                                        ? root.items.catalog.asset_rows : 0)
                                    + " rows · " + String(root.items.catalog
                                        ? root.items.catalog.insertables : 0)
                                    + " insertables"
                                color: root.signalViolet
                                font.family: "monospace"
                                font.pixelSize: 10
                                wrapMode: Text.WordWrap
                            }
                            Row {
                                width: parent.width
                                spacing: 4
                                Text {
                                    text: "RACE"
                                    color: root.muted
                                    font.family: "monospace"
                                    font.pixelSize: 10
                                    verticalAlignment: Text.AlignVCenter
                                }
                                Repeater {
                                    model: ["ISLANDER", "TIDEBORN", "SKYKIN"]
                                    delegate: GgButton {
                                        required property string modelData
                                        text: modelData
                                        implicitWidth: 62
                                        implicitHeight: 24
                                        checked: root.progression.race === modelData
                                        onClicked: root.selectRace(modelData)
                                    }
                                }
                            }
                            Row {
                                width: parent.width
                                spacing: 4
                                Text {
                                    text: "SPEC"
                                    color: root.muted
                                    font.family: "monospace"
                                    font.pixelSize: 10
                                    verticalAlignment: Text.AlignVCenter
                                }
                                Repeater {
                                    model: ["EXPLORER", "WARDEN", "DUELIST"]
                                    delegate: GgButton {
                                        required property string modelData
                                        text: modelData
                                        implicitWidth: 62
                                        implicitHeight: 24
                                        checked: root.progression.spec === modelData
                                        onClicked: root.selectSpec(modelData)
                                    }
                                }
                            }
                            Text {
                                width: parent.width
                                text: "CAPABILITIES"
                                color: root.ledgerGold
                                font.family: "monospace"
                                font.pixelSize: 10
                                font.bold: true
                            }
                            Repeater {
                                model: root.capabilities
                                delegate: Text {
                                    required property string modelData
                                    width: parent.width
                                    text: "· " + modelData
                                    color: root.text
                                    font.family: "monospace"
                                    font.pixelSize: 10
                                }
                            }
                            Text {
                                width: parent.width
                                text: "ALLOWLIST       local glTF 2.0 · max 8 authored instances\nThe bundled hero is a seam fixture, not final production art."
                                color: root.muted
                                wrapMode: Text.WordWrap
                                font.family: "monospace"
                                font.pixelSize: 10
                            }
                        }

                        Column {
                            width: parent.width
                            spacing: 7
                            visible: root.page === "UI"

                            Text {
                                text: "UI / ADDONS"
                                color: root.ledgerGreen
                                font.family: "monospace"
                                font.pixelSize: 11
                                font.bold: true
                            }
                            Text {
                                width: parent.width
                                text: "OSINT OVERLAY  24%  ·  DATA-FIRST  ·  EVENT-DRIVEN"
                                    + "\nUNIT FRAMES  " + (
                                        root.addonEnabled("UNIT_FRAMES")
                                            ? "VISIBLE" : "HIDDEN"
                                    )
                                    + "  ·  MEMORY " + String(
                                        root.addonState.active_memory_budget_kb || 0
                                    ) + " KB"
                                color: root.muted
                                font.family: "monospace"
                                font.pixelSize: 10
                                wrapMode: Text.WordWrap
                            }

                            Text {
                                text: "KEYBINDINGS  ·  WOW CLASSIC"
                                color: root.ledgerGold
                                font.family: "monospace"
                                font.pixelSize: 10
                                font.bold: true
                            }

                            Repeater {
                                model: root.bindingRows()
                                delegate: Row {
                                    required property var modelData
                                    width: parent.width
                                    spacing: 4

                                    Text {
                                        width: parent.width - 78
                                        text: modelData.label
                                        color: root.text
                                        font.family: "monospace"
                                        font.pixelSize: 9
                                        verticalAlignment: Text.AlignVCenter
                                        elide: Text.ElideRight
                                    }
                                    GgButton {
                                        text: root.bindingCaptureAction === modelData.id
                                            ? "PRESS…"
                                            : root.keysFor(modelData.id)
                                        implicitWidth: 74
                                        implicitHeight: 22
                                        checked: root.bindingCaptureAction === modelData.id
                                        onClicked: {
                                            root.bindingCaptureAction = modelData.id
                                            root.forceActiveFocus()
                                        }
                                    }
                                }
                            }

                            Row {
                                width: parent.width
                                spacing: 5
                                GgButton {
                                    text: "RESET BINDS"
                                    implicitWidth: 104
                                    implicitHeight: 24
                                    onClicked: root.resetKeybindings()
                                }
                                Text {
                                    width: parent.width - 109
                                    text: root.bindingCaptureAction !== ""
                                        ? "PRESS A KEY…"
                                        : "E INTERACT · Q GRAPPLE · A/D TURN"
                                    color: root.bindingCaptureAction !== ""
                                        ? root.ledgerGold : root.muted
                                    font.family: "monospace"
                                    font.pixelSize: 9
                                    verticalAlignment: Text.AlignVCenter
                                    elide: Text.ElideRight
                                }
                            }

                            Rectangle {
                                width: parent.width
                                height: 1
                                color: "#333333"
                            }

                            Text {
                                text: "BUILT-IN ADDONS"
                                color: root.ledgerGold
                                font.family: "monospace"
                                font.pixelSize: 10
                                font.bold: true
                            }

                            Repeater {
                                model: root.addonState.addons || []
                                delegate: Row {
                                    required property var modelData
                                    width: parent.width
                                    spacing: 4

                                    GgButton {
                                        text: modelData.enabled ? "ON" : "OFF"
                                        implicitWidth: 38
                                        implicitHeight: 22
                                        checked: Boolean(modelData.enabled)
                                        onClicked: root.toggleAddon(
                                            modelData.id,
                                            modelData.enabled
                                        )
                                    }
                                    Column {
                                        width: parent.width - 42
                                        spacing: 1
                                        Text {
                                            width: parent.width
                                            text: String(modelData.name || modelData.id)
                                            color: root.text
                                            font.family: "monospace"
                                            font.pixelSize: 9
                                            elide: Text.ElideRight
                                        }
                                        Text {
                                            width: parent.width
                                            text: String(modelData.category || "UI")
                                                + " · " + String(
                                                    modelData.memory_budget_kb || 0
                                                ) + " KB · " + String(
                                                    modelData.status || "DISABLED"
                                                )
                                            color: root.muted
                                            font.family: "monospace"
                                            font.pixelSize: 8
                                            elide: Text.ElideRight
                                        }
                                    }
                                }
                            }

                            Text {
                                width: parent.width
                                text: "ADDON ABI  " + String(
                                    root.addonState.execution
                                        || "NATIVE_DATA_ONLY_EVENT_DRIVEN"
                                )
                                    + "\nTHIRD PARTY  " + String(
                                        root.addonState.third_party
                                            ? root.addonState.third_party.status
                                            : "NOT_ENABLED"
                                    )
                                color: root.muted
                                font.family: "monospace"
                                font.pixelSize: 9
                                wrapMode: Text.WordWrap
                            }
                        }
                    }
                }
                    }
                }
            }
        }
    }

    GameInventoryPanel {
        objectName: "gameCharacterInventoryPanel"
        anchors.fill: parent
        z: 100
        visible: root.page === "BAG"
        game: root
    }
    GameLocalActionsPanel {
        anchors.fill: parent
        z: 110
        game: root
    }
    GamePresentation {
        anchors.fill: parent
        z: 50
        surfaceHost: root.surfaceHost
        paneLive: root.paneLive
        standalone: root.standalonePlayerMode
        worldSurface: root
        onClientControls: function(controls) {
            root.mountedWorldState=controls.mounted_world || ({status:"GG",message:""})
            root.syncClientCamera({player:{client_controls:controls}})
            if(controls.services) {
                var deadBefore=!!(root.localServiceState.lifecycle || {}).dead
                root.localServiceState=LocalServiceState.retain(root.localServiceState,controls.services)
                if(!deadBefore && (controls.services.lifecycle || {}).dead) localServices.openLifecycle()
            }
        }
    }
    Rectangle {
        objectName:"gameMountedWorldNotice"
        visible:root.paneLive && (root.mountedWorldState.status==="LOADING" || root.mountedWorldState.status==="UNAVAILABLE")
        anchors.top:parent.top;anchors.horizontalCenter:parent.horizontalCenter;anchors.topMargin:60
        width:Math.min(480,parent.width-32);height:message.implicitHeight+20;z:160
        color:"#ed19232b";border.color:"#806d47";radius:5
        Text {
            id:message;anchors.centerIn:parent;width:parent.width-24
            text:root.mountedWorldState.message || "";textFormat:Text.PlainText
            color:"#eed494";font.pixelSize:12;wrapMode:Text.WordWrap;horizontalAlignment:Text.AlignHCenter
        }
    }
    GgButton {
        objectName: "gameLocalServicesButton"
        text: "TJÄNSTER"
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: root.standalonePlayerMode ? 12 : 50
        z: 120
        enabled: !!root.surfaceHost
        onClicked: localServices.open()
    }
    LocalGameServices {
        id: localServices
        surfaceHost: root.surfaceHost
        game: root
        services: root.localServiceState
        inventory: root.status.items ? root.status.items.inventory || [] : []
        people: root.localServiceState.people || []
        playerName: root.status.player ? root.status.player.name || "Gold Goblin" : "Gold Goblin"
        targetId: root.combatTarget.id || ""
        onVisibleChanged: if(visible) {root.clearMovementInput();if(root.surfaceHost&&root.surfaceHost.gameEngineClientControl)root.surfaceHost.gameEngineClientControl(JSON.stringify({kind:"input",op:"Cancel"}))}
        onServiceUpdated: function(snapshot) { root.localServiceState=LocalServiceState.retain(root.localServiceState,((snapshot.player || {}).client_controls || {}).services || root.localServiceState);root.refresh() }
    }
    GameItemBindingDialog { game:root }
    GameLootBindingDialog { game:root }
    GameEnchantingDialog { game:root }
    GameDressingRoom { game:root }

}
