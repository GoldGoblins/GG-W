from __future__ import annotations

import json
import math
import re
import sys
import time
from collections import Counter
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def main() -> int:
    from PySide6.QtQuick3D import QQuick3DGeometry

    from backend.game_engine_host import (
        FIXED_HZ,
        RENDER_UPDATE_HZ,
        STRESS_RENDER_UPDATE_HZ,
        GameEngineRuntime,
    )
    from backend.game_engine_world import (
        DEFAULT_CAMERA_DISTANCE_M,
        DEFAULT_INTEREST_RADIUS,
        DEFAULT_RENDER_RADIUS,
        DEFAULT_PLANET_RADIUS_METERS,
        HOUSE_ROOF_CLEARANCE_M,
        ISLAND_LAYOUT_SCALE,
        WORLD_PROP_SCALE,
        MOVEMENT_MODES,
        local_to_planet,
        orbit_camera_position,
    )
    from backend import (
        game_engine_addons as addons,
        game_engine_assets as assets,
        game_engine_cinematic as cinematic,
        game_engine_content as content,
        game_engine_economy as economy,
        game_engine_animation as animation,
        game_engine_controller as controller,
        game_engine_editor as editor,
        game_engine_fallback as fallback,
        game_engine_geometry as geometry,
        game_engine_gear as gear,
        game_engine_input as input_contract,
        game_engine_life as life,
        game_engine_mmo as mmo,
        game_engine_nav as nav,
        game_engine_npc as npc,
        game_engine_npc_identity as identity,
        game_engine_physics as physics,
        game_engine_progression as progression,
        game_engine_render as render,
        game_engine_settlement as settlement,
        game_engine_terrain as terrain,
    )

    qml = (PROJECT / "qml" / "components" / "GameEngineSurface.qml").read_text(
        encoding="utf-8"
    )
    osint_qml = (PROJECT / "qml" / "components" / "OsintSurface.qml").read_text(
        encoding="utf-8"
    )
    if "import QtQuick3D" not in qml:
        raise AssertionError("game surface is not native QtQuick3D")
    if "Osint" in qml or "WebEngine" in qml:
        raise AssertionError("game surface must stay independent of OSINT/WebEngine")
    if "GameEngine" in osint_qml:
        raise AssertionError("OSINT surface must stay independent of Game Engine")
    # World instancing, fauna and articulated equipment add independent pools.
    # Check the retained terrain/entity bindings rather than freezing their count.
    for model in ("terrainRenderModel", "entityRenderModel"):
        if not re.search(rf"Repeater3D\s*\{{\s*model:\s*{model}\b", qml):
            raise AssertionError(f"retained 3D render pool missing: {model}")
    if "root.suspendRuntime()" not in qml or "Component.onDestruction" not in qml:
        raise AssertionError("game runtime is not suspended with the surface")
    # Rendering follows the scene graph's frame clock. It must stop when the
    # pane or simulation is inactive and pass frame time to camera/gear physics.
    frame_animation = re.search(r"FrameAnimation\s*\{(.*?)\n    \}", qml, re.S)
    if frame_animation is None:
        raise AssertionError("game surface has no scene-graph render cadence")
    frame_body = re.sub(r"\s+", " ", frame_animation.group(1))
    for frame_feature in (
        'objectName: "gameRenderFrameAnimation"',
        "running: root.paneLive && root.surfaceHost !== null && (root.running || root.replaying)",
        "root.followCamera(refreshTimer.frameTime)",
        "root.refreshRender()",
        "root.updateEquipmentPhysics(refreshTimer.frameTime)",
    ):
        if frame_feature not in frame_body:
            raise AssertionError(f"render-frame lifecycle missing: {frame_feature}")
    for render_feature in (
        "SceneEnvironment.NoAA",
        "SceneEnvironment.MSAA",
        "SceneEnvironment.SSAA",
        "view3d.renderStats",
        "shadowMappingEnabled",
        "visibilityData.shadow_caster",
        "denseTerrainCells",
        "gameClayPropMaterial",
        "gameClayCharacterMaterial",
        "castsShadow",
        "castsShadows",
        "receivesShadows",
        "lowPolySphereGeometry",
        "SphereGeometry",
        "rings: 6",
        "segments: 12",
        "vertexColorsEnabled",
        "gameEntityProxyModel",
    ):
        if render_feature not in qml:
            raise AssertionError(f"QtQuick3D render feature missing: {render_feature}")
    if "#Sphere" not in qml or "ORBIT_WORLD_SCALE" not in qml:
        raise AssertionError("world-scale orbit representation missing")
    if "terrainHlodTileModel" not in qml or "streamCoverageSize" not in qml:
        raise AssertionError("streamed world has no outer-cell HLOD coverage")
    if "root.terrainCells" not in qml or "root.terrainSurface" not in qml:
        raise AssertionError("terrain cell data is not exposed in the game surface")
    for terrain_authoring_feature in (
        "terrainTargetSelected",
        "pickTerrainCell",
        "SHIFT+CLICK / DRAG",
        "terrainBrushRadius",
        "terrainBrushFalloff",
        "gameEngineTerrainGeometry",
        "height_grid_m",
        "terrainModel.patchGeometry",
        "gameEngineStage",
        "gameEngineSidebar",
        "gameEngineInspector",
        "gameEntityFigure",
        "FIELD LEDGER",
        "TSEU_INSPIRED_BOOKKEEPING",
        "PLACE NPC",
        "INTERACT",
        "root.npc",
        "RADIAL_LOS_BOUNDED",
        "DIRECT_STEERING_BOUNDED",
        "root.navigation",
        "TILED_HEIGHTFIELD_ASTAR",
        "WOW_CLASSIC_THIRD_PERSON",
        "CHARACTER_FORWARD_RIGHT",
        "WOW_CLASSIC",
        "property var keyBindings",
        "bindingCaptureAction",
        "gameEngineKeybinding",
        "gameEngineAddon",
        "gameEngineUnitFrames",
        "PitBull",
        "W/S MOVE",
        "RMB CAMERA",
        "panelOverlay",
        "property real strafe",
        "property bool jump",
        "orbitPitch",
        "entityPose",
        "poseBob",
        "poseLean",
        "poseSway",
        "gameEngineLeftMenuToggle",
        "gameEngineEngineRail",
        "gameEngineInspectorToggle",
        "leftMenuCollapsed",
        "inspectorCollapsed",
        "terrainRenderModel",
        "entityRenderModel",
        "particleBatchModel",
        "syncRenderModels",
        "QtQuick3D.AssetUtils",
        "RuntimeLoader",
        "authoredAsset",
        "entityAsset",
        "authoredCharacterSource",
        "authoredAssetVisible",
        "gameAuthoredAssetLoader",
        "AUTHORED_STATIC",
        "itemAsset",
        "gameAuthoredItemLoader",
        "gameAuthoredEquippedItemLoader",
        "property var items",
        "property var economy",
        "property var life",
        "itemInteraction",
        "gameWorldItemModel",
        "gameEquippedItemModel",
        "GROUND_ITEM",
        "CHEST",
        "gameEngineItemInteract",
        "gameEngineContainerOpen",
        "gameEngineContainerLoot",
        "gameEngineItemEquip",
        "gameEngineItemDrop",
        "gameEngineTrade",
        "gameEngineVendorBuy",
        "gameEngineVendorSell",
        "gameEngineItemSocket",
        "gameEngineGearEnchant",
        "gameEngineGearCraft",
        "gameEnginePresentationMode",
        "gameEngineGraphicsFailure",
        "socketItem",
        "enchantGear",
        "craftGear",
        "dosFallbackActive",
        "gameEngineDosFallback",
        "gameEngineDosFallbackCanvas",
        "fallbackTerminalText",
        "RICH_3D",
        "DOS_2D",
        "Canvas",
    ):
        if terrain_authoring_feature not in qml:
            raise AssertionError(
                f"terrain authoring feature missing: {terrain_authoring_feature}"
            )
    if "readonly property real sceneScale: 0.01" not in qml:
        raise AssertionError("QtQuick3D primitive scale conversion missing")
    for mode in MOVEMENT_MODES:
        if mode not in qml:
            raise AssertionError(f"movement mode {mode} is not exposed in the surface")
    if "gameEngineMovementMode" not in qml:
        raise AssertionError("movement mode bridge missing from game surface")
    for control in (
        "gameEngineAbility",
        "gameEngineLoot",
        "gameEngineCraft",
        "gameEngineEnchant",
        "gameEngineItemInteract",
        "gameEngineItemPickup",
        "gameEngineContainerOpen",
        "gameEngineContainerLoot",
        "gameEngineItemEquip",
        "gameEngineItemDrop",
        "gameEngineTrade",
        "gameEngineVendorBuy",
        "gameEngineVendorSell",
        "gameEngineEditorPlace",
        "gameEngineNpcInteract",
        "gameEngineTerrainEdit",
        "gameEngineTerrainBrush",
        "gameEngineTerrainUndo",
        "gameEngineSave",
        "gameEngineRenderProfile",
        "gameEngineKeybinding",
        "gameEngineKeybindingsReset",
        "gameEngineAddon",
        "gameEngineInputRender",
        "entityDynamic",
        "renderDynamicSignature",
        "characterVisual",
        "gameEngineItemGeometry",
        "gameEngineWorldPropGeometry",
        "root.crewSource",
        "source: entityModel.authoredCharacterSource",
        "gameEngineRuntimeClip",
        "entityAssetMotion",
        "authoredAssetClipStatus",
        "requestedAuthoredClip",
        "authoredAssetVisualContent",
        "authoredClipForMotionState",
        "clip_status",
        "GG_CLAY_ASSET_KIT",
    ):
        if control not in qml:
            raise AssertionError(f"{control} bridge missing from game surface")
    for prototype_body in ("lowPolyCharacterGeometry", "gameCharacterBodyModel"):
        if prototype_body in qml:
            raise AssertionError("approved character assets must not restore a prototype body")
    button_qml = (PROJECT / "qml" / "components" / "GgButton.qml").read_text(
        encoding="utf-8"
    )
    if "property bool enabled: true" in button_qml:
        raise AssertionError("GgButton redeclares Item.enabled")

    runtime = GameEngineRuntime()
    try:
        initial = runtime.snapshot()
        starter = content.starter_content()
        npc_spawns = npc.spawns_from_content(starter)
        life_spawns = life.spawns_from_content(starter)
        fixtures = settlement.catalog()["fixtures"]
        # The enlarged approved village has 34 core props, its beacon, two
        # shared route meshes and the separately authored settlement fixtures.
        expected_world_props = 35 + 2 + len(fixtures)
        expected_sim_entities = 1 + expected_world_props + len(npc_spawns)
        expected_character_count = 1 + len(npc_spawns) + len(life_spawns)
        expected_render_entities = expected_sim_entities + len(life_spawns) + 4
        expected_people = set(starter["npc_individuals"]) | {
            str(row["id"]) for row in npc_spawns + life_spawns
        }
        assert len(npc_spawns) == 6
        assert len(life_spawns) == 24 == life.MAX_PROXIES
        assert initial["schema"] == "gg.game-engine.runtime.v1"
        assert initial["state"] == "IDLE"
        assert initial["simulation"]["active_entities"] == expected_sim_entities
        assert initial["simulation"]["active_npcs"] == len(npc_spawns)
        assert initial["people"]["schema"] == identity.SCHEMA
        assert initial["people"]["population"] == len(expected_people)
        assert initial["people"]["unique_names"] == len(expected_people)
        assert {row["id"] for row in initial["people"]["people"]} == expected_people
        assert initial["gear"]["slots"] == 19
        assert initial["gear"]["runes"] == 6
        assert initial["gear"]["gems"] == 6
        assert initial["gear"]["runewords"] == 3
        assert initial["render"]["ambient_life"] == {
            "visible": len(life_spawns),
            "budget": life.MAX_PROXIES,
            "simulation": "RENDER_ONLY_DETERMINISTIC_SCHEDULES",
        }
        assert "BOUNDED_AMBIENT_LIFE_PROXIES" in initial["capabilities"]
        assert "DATA_DRIVEN_AMBIENT_SCHEDULES" in initial["capabilities"]
        assert "BOUNDED_PLAYER_STIMULI" in initial["capabilities"]
        assert len(initial["render"]["entities"]) == expected_render_entities
        assert initial["life"]["schema"] == life.SCHEMA
        assert initial["life"]["population"] == len(life_spawns)
        assert initial["life"]["clock"]["phase"] == "DAWN"
        assert sum(initial["life"]["activities"].values()) == len(life_spawns)
        assert sum(initial["life"]["stimuli"].values()) == len(life_spawns)
        # Expanded village homes no longer sit next to the origin. Preserve
        # the attention behavior check with a stationary, controlled resident.
        attention_spawn = {
            "id": "host-stimulus-fixture", "x": 1.0, "z": 1.0,
            "radius": 1.0, "speed": 0.2, "sense_radius": 2.0,
        }
        near_resident = life.proxy_rows([attention_spawn], 0, player_x=0, player_z=0)[0]
        assert near_resident["life"]["activity"] == "NOTICE_PLAYER"
        assert near_resident["life"]["stimulus"] == "PLAYER_NEAR"
        far_resident = life.proxy_rows([attention_spawn], 0, player_x=100, player_z=100)[0]
        assert far_resident["life"]["stimulus"] == "NONE"
        assert initial["life"]["simulation"] == (
            "RENDER_ONLY_DETERMINISTIC_SCHEDULES"
        )
        assert initial["simulation"]["fixed_hz"] == FIXED_HZ
        assert initial["render"]["update_hz"] == RENDER_UPDATE_HZ
        assert initial["render"]["renderer"] == "QTQUICK3D_NATIVE_GEOMETRY"
        assert initial["render"]["world_asset_instances"] == {
            "native_requested": expected_world_props,
            "primitive_fallback": 0,
            "budget": 96,
        }
        world_rows = [
            row
            for row in initial["render"]["entities"]
            if row.get("kind") not in {"PLAYER", "NPC", "ACTOR", "GROUND_ITEM", "CHEST"}
        ]
        assert len(world_rows) == expected_world_props
        # Independently state the core scene contents; settlement additions
        # must be present without replacing an existing village prop.
        core_kinds = Counter({
            "HOUSE": 7, "PALM": 7, "BARREL": 1, "MANGROVE": 3,
            "ROCK": 2, "PROP": 1, "DOCK": 1, "WATER_WHEEL": 1,
            "WINDMILL": 1, "MARKET_STALL": 1, "FISH_RACK": 1,
            "BOAT": 1, "BRIDGE": 1, "LIGHT": 2, "PATH": 4,
            "TIDE_BEACON": 1, "SETTLEMENT_ROADS": 1, "SETTLEMENT_FENCES": 1,
        })
        assert Counter(row["kind"] for row in world_rows) == (
            core_kinds + Counter(row["kind"] for row in fixtures)
        )
        assert all(isinstance(row.get("asset"), dict) for row in world_rows)
        assert all(
            row["asset"].get("geometry_key")
            and (
                row["asset"].get("mode") == "AUTHORED_STATIC"
                or (
                    row["asset"].get("mode") == assets.PROCEDURAL_ASSET_MODE
                    and row["asset"].get("format") == "QQUICK3D_GEOMETRY"
                    and row["asset"].get("style_id")
                    == assets.PROCEDURAL_ASSET_STYLE_ID
                )
            )
            for row in world_rows
        )
        assert {
            row["asset"]["geometry_key"]
            for row in world_rows
        } >= {
            "world.prop.rock",
            "world.prop.mangrove",
            "world.prop.shrine",
            "world.prop.barrel",
            "world.stilt_hut",
            "world.palm",
            "world.dock",
            "world.lantern",
        }
        palms = [row for row in world_rows if row["asset"]["geometry_key"] == "world.palm"]
        assert palms
        assert all(0.85 <= float(row.get("sx", 0)) / WORLD_PROP_SCALE <= 1.15 for row in palms)
        assert all(2.0 <= float(row.get("sy", 0)) / WORLD_PROP_SCALE <= 2.5 for row in palms)
        assert all(
            str((row.get("asset") or {}).get("mode") or "") == "AUTHORED_STATIC"
            for row in palms
        )
        huts = [
            row
            for row in world_rows
            if row["asset"]["geometry_key"] == "world.stilt_hut"
        ]
        assert len(huts) == core_kinds["HOUSE"] + sum(row["kind"] == "HOUSE" for row in fixtures)
        assert all(
            math.isclose(float(row.get("sy", 0)), HOUSE_ROOF_CLEARANCE_M * WORLD_PROP_SCALE / 2)
            for row in huts
        )
        assert all(float(row.get("sx", 0)) > 0 and float(row.get("sz", 0)) > 0 for row in huts)
        docks = [
            row
            for row in world_rows
            if row["asset"]["geometry_key"] == "world.dock"
        ]
        assert docks
        assert all(
            math.isclose(float(row.get("sx", 0)), 1.10 * ISLAND_LAYOUT_SCALE, abs_tol=0.001)
            and math.isclose(float(row.get("sy", 0)), 1.40 * WORLD_PROP_SCALE, abs_tol=0.001)
            and math.isclose(float(row.get("sz", 0)), 1.20 * ISLAND_LAYOUT_SCALE, abs_tol=0.001)
            for row in docks
        )
        assert initial["render"]["authored_asset_renderer"] == (
            "QTQUICK3D_RUNTIME_LOADER_PLUS_PROCEDURAL_GEOMETRY"
        )
        assert initial["render"]["presentation"]["mode"] == render.RICH_3D
        assert initial["render"]["presentation"]["fallback_mode"] == render.DOS_2D
        assert initial["render"]["presentation"]["simulation_unchanged"] is True
        assert initial["render"]["fallback"]["schema"] == fallback.SCHEMA
        assert len(initial["render"]["fallback"]["entities"]) == expected_render_entities
        assert initial["player"]["movement_mode"] == "GROUND"
        assert initial["controller"]["model"] == "WOW_CLASSIC_THIRD_PERSON"
        assert initial["controller"]["input_space"] == "CHARACTER_FORWARD_RIGHT"
        assert initial["controller"]["movement_grammar"] == (
            "W_S_MOVE_A_D_TURN_E_INTERACT_Q_GRAPPLE"
        )
        assert initial["keybindings"]["schema"] == input_contract.SCHEMA
        assert initial["keybindings"]["bindings"]["TURN_LEFT"][0] == "A"
        assert initial["keybindings"]["bindings"]["TURN_RIGHT"][0] == "D"
        assert initial["keybindings"]["bindings"]["STRAFE_LEFT"] == []
        assert initial["keybindings"]["bindings"]["STRAFE_RIGHT"] == []
        assert initial["keybindings"]["bindings"]["MOVE_FORWARD"][0] == "W"
        assert initial["keybindings"]["bindings"]["MOVE_BACK"][0] == "S"
        assert initial["addons"]["schema"] == addons.SCHEMA
        assert initial["addons"]["active_count"] == len(addons.ADDON_DEFINITIONS)
        assert any(
            row["id"] == "UNIT_FRAMES" and row["enabled"]
            for row in initial["addons"]["addons"]
        )
        assert input_contract.action_for_key(initial["keybindings"], "Q") == [
            "GRAPPLE"
        ]
        assert input_contract.action_for_key(initial["keybindings"], "E") == ["INTERACT"]
        assert input_contract.normalize_bindings({"bindings": {}})["bindings"][
            "PRIMARY_ATTACK"
        ] == ["T"]
        assert input_contract.normalize_bindings({"bindings": {"PRIMARY_ATTACK": []}})[
            "bindings"
        ]["PRIMARY_ATTACK"] == []
        legacy_bindings = input_contract.normalize_bindings({
            "bindings": {"PRIMARY_ATTACK": ["V"], "TOGGLE_HOVERBOARD": ["V"]}
        })
        assert legacy_bindings["bindings"]["PRIMARY_ATTACK"] == ["T"]
        assert legacy_bindings["bindings"]["TOGGLE_HOVERBOARD"] == ["V"]
        remapped = runtime.set_keybinding("STRAFE_LEFT", "T")
        assert remapped["keybinding_result"]["ok"] is True
        assert remapped["keybindings"]["bindings"]["STRAFE_LEFT"][0] == "T"
        assert "T" not in remapped["keybindings"]["bindings"]["STRAFE_RIGHT"]
        assert input_contract.action_for_key(remapped["keybindings"], "T") == ["STRAFE_LEFT"]
        assert remapped["keybindings"]["bindings"]["PRIMARY_ATTACK"] == []
        addon_off = runtime.set_addon("NPC_TRACKER", False)
        assert addon_off["addon_result"]["ok"] is True
        assert not next(
            row for row in addon_off["addons"]["addons"]
            if row["id"] == "NPC_TRACKER"
        )["enabled"]
        settings_runtime = GameEngineRuntime()
        try:
            settings_runtime.set_keybinding("STRAFE_LEFT", "T")
            settings_runtime.set_addon("NPC_TRACKER", False)
            settings_runtime.save_state()
            settings_runtime.reset()
            restored_settings = settings_runtime.load_state()
            assert restored_settings["keybindings"]["bindings"]["STRAFE_LEFT"][0] == "T"
            assert restored_settings["keybindings"]["bindings"]["PRIMARY_ATTACK"] == []
            assert input_contract.action_for_key(restored_settings["keybindings"], "T") == [
                "STRAFE_LEFT"
            ]
            assert not next(
                row for row in restored_settings["addons"]["addons"]
                if row["id"] == "NPC_TRACKER"
            )["enabled"]
        finally:
            settings_runtime.shutdown()
        runtime.set_addon("NPC_TRACKER", True)
        runtime.reset_keybindings()
        assert initial["controller"]["camera"]["distance_m"] == DEFAULT_CAMERA_DISTANCE_M
        assert initial["player"]["grounded"] is True
        assert initial["render"]["entities"][0]["cell_key"] == "0:0:0"
        assert initial["render"]["entities"][0]["lod"] == "NEAR"
        assert initial["render"]["entities"][0]["motion_state"] == "IDLE"
        assert initial["render"]["entities"][0]["animation"]["schema"] == (
            animation.SCHEMA
        )
        assert initial["render"]["entities"][0]["animation"]["state"] == "IDLE"
        render_input = runtime.set_input_render(
            json.dumps({"forward": 1.0, "movement_mode": "GROUND"})
        )
        assert render_input["schema"] == "gg.game-engine.render-snapshot.v1"
        assert "render" in render_input and "entities" in render_input["render"]
        assert "items" not in render_input
        assert runtime.snapshot()["input"]["forward"] == 1.0
        ui_delta = runtime.ui_snapshot()
        assert ui_delta["schema"] == "gg.game-engine.ui-delta.v1"
        assert "items" in ui_delta and "terrain_surface" in ui_delta
        assert len(json.dumps(ui_delta)) < len(json.dumps(initial))
        assert initial["assets"]["selected"]["status"] == "READY"
        assert initial["assets"]["selected"]["mode"] == "AUTHORED_SKINNED"
        assert initial["assets"]["selected"]["format"] == "GLTF2"
        assert initial["assets"]["selected"]["skeleton"]["joints"] == 61
        assert initial["assets"]["selected"]["animations"] == 58
        assert initial["assets"]["character_visual"] == {
            "policy": assets.CHARACTER_VISUAL_POLICY,
            "preferred": assets.CHARACTER_VISUAL_PREFERRED,
            "fallback": assets.CHARACTER_VISUAL_FALLBACK,
            "max_active_models_per_character": 1,
        }
        assert initial["assets"]["asset_kit"]["id"] == (
            assets.PROCEDURAL_ASSET_STYLE_ID
        )
        assert initial["assets"]["static_items"]["itemmesh.iron_saber"]["mode"] == (
            "AUTHORED_STATIC"
        )
        assert initial["assets"]["static_items"]["container.supply_crate"]["status"] == (
            "READY"
        )
        assert initial["render"]["asset_instances"] == {
            "authored_requested": expected_character_count,
            "procedural_requested": 0,
            "preview_fallback": 0,
            "budget": assets.MAX_AUTHORED_INSTANCES,
        }
        assert initial["render"]["item_asset_instances"] == {
            "authored_requested": 8,
            "procedural_requested": 0,
            "primitive_fallback": 0,
            "budget": assets.MAX_AUTHORED_ITEM_INSTANCES,
        }
        assert initial["render"]["entities"][0]["asset"]["mode"] == (
            "AUTHORED_SKINNED"
        )
        assert initial["render"]["entities"][0]["asset"]["clip"] == "Idle"
        assert initial["render"]["entities"][0]["asset"]["phase"] == 0.0
        character_rows = [
            row
            for row in initial["render"]["entities"]
            if row.get("kind") in {"PLAYER", "NPC", "ACTOR"}
        ]
        assert len(character_rows) == expected_character_count
        assert [row["asset"]["instance_rank"] for row in character_rows] == list(
            range(expected_character_count)
        )
        assert character_rows[0]["kind"] == "PLAYER"
        assert character_rows[0]["asset"]["mode"] == "AUTHORED_SKINNED"
        npc_rows = [row for row in character_rows if row["kind"] == "NPC"]
        actor_rows = [row for row in character_rows if row["kind"] == "ACTOR"]
        assert npc_rows
        assert all(row["asset"]["mode"] == "AUTHORED_SKINNED" for row in npc_rows)
        assert all(
            row["asset"]["mode"] == "AUTHORED_SKINNED"
            for row in actor_rows
        )
        moving_snapshot = runtime.step()
        moving_npc = next(
            row
            for row in moving_snapshot["render"]["entities"]
            if row.get("kind") == "NPC"
        )
        assert moving_npc["animation"]["state"] == "WALK"
        assert moving_npc["asset"]["mode"] == "AUTHORED_SKINNED"
        assert moving_npc["asset"]["clip"] == "Walk"
        assert moving_npc["asset"]["clip_status"] == "READY"
        moving_render = runtime.render_snapshot()
        moving_render_npc = next(
            row
            for row in moving_render["render"]["entities"]
            if row.get("kind") == "NPC"
        )
        assert moving_render_npc["asset"]["clip_status"] == "READY"
        moving_character_rows = [
            row
            for row in moving_render["render"]["entities"]
            if row.get("kind") in {"PLAYER", "NPC", "ACTOR"}
        ]
        assert len(moving_character_rows) == expected_character_count
        assert moving_character_rows[0]["asset"]["mode"] == "AUTHORED_SKINNED"
        assert all(
            row["asset"]["mode"] == "AUTHORED_SKINNED"
            for row in moving_character_rows
            if row["kind"] == "NPC"
        )
        assert all(
            row["asset"]["mode"] == "AUTHORED_SKINNED"
            for row in moving_character_rows
            if row["kind"] == "ACTOR"
        )
        assert initial["world"]["schema"] == "gg.game-engine.world.v1"
        assert initial["world"]["streaming"]["visible_zones"] is False
        expected_loaded_cells = (2 * DEFAULT_INTEREST_RADIUS + 1) ** 2
        # The normal third-person camera uses the nearby 4-cell render ring;
        # the larger profile cap is reserved for the zoomed-out editor camera.
        expected_render_radius = 4
        expected_render_cells = (2 * expected_render_radius + 1) ** 2
        assert expected_render_radius <= DEFAULT_RENDER_RADIUS
        assert expected_render_radius <= render.PROFILES[initial["render"]["profile"]][
            "max_render_radius"
        ]
        assert len(initial["world"]["streaming"]["loaded_cells"]) == expected_loaded_cells
        assert initial["world"]["streaming"]["interest_radius"] == DEFAULT_INTEREST_RADIUS
        assert initial["world"]["streaming"]["coverage_diameter_m"] == 112.0
        assert len(initial["world"]["streaming"]["render_cells"]) == expected_render_cells
        assert initial["world"]["streaming"]["render_radius"] == expected_render_radius
        assert initial["world"]["streaming"]["render_coverage_diameter_m"] == 144.0
        assert initial["world"]["streaming"]["loaded_cells"][0]["lod"] == "NEAR"
        assert any(
            cell["lod"] == "HORIZON"
            for cell in initial["world"]["streaming"]["loaded_cells"]
        )
        origin = local_to_planet(0.0, 0.0, 0.0)
        assert origin == (DEFAULT_PLANET_RADIUS_METERS, 0.0, 0.0)
        assert initial["world"]["planet"]["global_position_m"]["x"] > (
            DEFAULT_PLANET_RADIUS_METERS
        )
        assert initial["world"]["planet"]["global_position_m"]["y"] == 0.0
        assert orbit_camera_position((0.0, 0.65, 0.0))[2] > 0.0
        assert initial["world"]["camera"]["player_relative_m"]["z"] < 0.0
        assert abs(initial["world"]["camera"]["surface_normal"]["x"] - 1.0) < 0.0001
        assert initial["terrain"]["schema"] == "gg.game-engine.terrain.v1"
        assert initial["terrain"]["world_seed"] == terrain.DEFAULT_WORLD_SEED
        assert initial["terrain"]["player_cell"]["key"] == "0:0:0"
        assert initial["terrain"]["player_surface"]["medium"] == "LAND"
        assert initial["terrain"]["water"]["zone_boundary"] is False
        assert initial["terrain"]["transition"]["seamless"] is True
        assert len(initial["terrain"]["cells"]) == expected_render_cells
        assert initial["terrain"]["cells"][0]["biome"] == "FIRST_ISLAND"
        assert initial["terrain"]["cells"][0]["geometry"]["representation"] == "PATCH_MESH"
        assert len(initial["terrain"]["cells"][0]["height_grid_m"]) == 25
        assert len(initial["terrain"]["cells"][1]["height_grid_m"]) == 9
        assert len(initial["terrain"]["cells"][0]["normal_grid"]) == 25 * 3
        assert initial["terrain"]["streaming"]["lod_counts"]["NEAR"] == 1
        assert initial["terrain"]["streaming"]["render_triangles"] > 0
        assert set(initial["terrain"]["streaming"]["biome_counts"]) == {
            "CLIFF", "FIRST_ISLAND"
        }
        assert initial["navigation"]["schema"] == nav.SCHEMA
        assert initial["navigation"]["model"] == "TILED_HEIGHTFIELD_ASTAR"
        assert initial["navigation"]["streaming"]["loaded_cells"] == expected_loaded_cells
        assert initial["navigation"]["streaming"]["loaded_tiles"] == expected_loaded_cells * 16
        assert initial["navigation"]["streaming"]["capacity_tiles"] >= (
            expected_loaded_cells * 16
        )
        assert initial["navigation"]["walkable_tiles"] > 0
        assert initial["navigation"]["player_tile"]["walkable"] is True
        assert nav.tile_coord(-0.001) == -1
        assert nav.tile_coord(0.0) == 0
        nav_tiles = nav.build_nav_tiles(
            initial["world"]["streaming"]["loaded_cells"]
        )
        nav_path = nav.plan_path(nav_tiles, 0.0, 0.0, 12.0, 12.0)
        assert nav_path["status"] == "READY"
        assert nav_path["waypoints"]
        # Approved Blender crew meshes face +Z at yaw zero. Movement and
        # optional strafe must agree with that facing, independent of camera orbit.
        assert controller.movement_direction(0.0, 1.0, 0.0) == (0.0, 1.0, 1.0)
        assert controller.movement_direction(0.0, 0.0, 1.0) == (-1.0, 0.0, 1.0)
        controller_step = controller.ground_step(
            camera_yaw=0.0,
            forward=1.0,
            strafe=0.0,
            dt=1.0 / 60.0,
        )
        assert controller_step["vz"] > 0.0
        turn_step = controller.ground_step(
            character_yaw=0.0,
            forward=0.0,
            strafe=0.0,
            turn_input=1.0,
            current_yaw=0.0,
            dt=1.0 / 60.0,
        )
        assert turn_step["turning"] is True
        assert turn_step["yaw"] > 0.0
        strafe_step = controller.ground_step(
            character_yaw=0.0,
            forward=0.0,
            strafe=1.0,
            turn_input=0.0,
            current_yaw=0.0,
            dt=1.0 / 60.0,
        )
        assert strafe_step["vx"] < 0.0
        assert abs(strafe_step["yaw"]) < 0.000001
        camera_independent = controller.ground_step(
            camera_yaw=90.0,
            character_yaw=0.0,
            forward=1.0,
            strafe=0.0,
            turn_input=0.0,
            dt=1.0 / 60.0,
        )
        assert abs(camera_independent["vx"]) < 0.000001
        assert camera_independent["vz"] > 0.0
        assert controller.character_basis(0.0)["forward"] == (0.0, 1.0)
        assert controller.character_basis(0.0)["right"] == (-1.0, 0.0)
        runtime.reset()
        runtime.set_input(json.dumps({"turn": 1.0}))
        before_turn = runtime.snapshot()["player"]
        for _ in range(10):
            runtime.step()
        after_turn = runtime.snapshot()["player"]
        assert after_turn["yaw"] > before_turn["yaw"]
        assert abs(after_turn["x"] - before_turn["x"]) < 0.01
        assert abs(after_turn["z"] - before_turn["z"]) < 0.01
        runtime.set_input(json.dumps({"turn": 0.0, "strafe": 1.0}))
        yaw_before_strafe = runtime.snapshot()["player"]["yaw"]
        for _ in range(24):
            runtime.step()
        after_strafe = runtime.snapshot()["player"]
        assert abs(after_strafe["yaw"] - yaw_before_strafe) < 0.0001
        assert abs(after_strafe["x"]) > 0.0
        after_motion = runtime.snapshot()
        assert after_motion["render"]["entities"][0]["asset"]["mode"] == (
            "AUTHORED_SKINNED"
        )
        assert after_motion["render"]["entities"][0]["asset"]["source"] == (
            initial["render"]["entities"][0]["asset"]["source"]
        )
        assert after_motion["render"]["asset_instances"]["budget"] == (
            assets.MAX_AUTHORED_INSTANCES
        )
        placement_before = runtime.snapshot()["player"]
        placed_forward = runtime.editor_place("PROP")
        placement = placed_forward["editor_result"]["placement"]
        placement_dx = placement["x"] - placement_before["x"]
        placement_dz = placement["z"] - placement_before["z"]
        facing = controller.character_basis(placement_before["yaw"])
        assert abs(placement_dx - facing["forward"][0] * 4.0) < 0.001
        assert abs(placement_dz - facing["forward"][1] * 4.0) < 0.001
        runtime.editor_undo()
        assert animation.motion_state(0.0) == "IDLE"
        assert animation.motion_state(5.0) == "WALK"
        assert animation.motion_state(9.0, sprinting=True) == "SPRINT"
        assert animation.motion_state(0.0, grounded=False) == "AIR"
        walk_pose = animation.build_pose(
            sim_time=0.5,
            horizontal_speed=5.0,
        )
        air_pose = animation.build_pose(
            sim_time=0.5,
            horizontal_speed=0.0,
            grounded=False,
            vertical_velocity=8.0,
        )
        assert walk_pose["state"] == "WALK"
        assert walk_pose["cadence_hz"] > 0.0
        assert air_pose["state"] == "AIR"
        assert air_pose["bob_m"] == 0.0
        initial_geometry = geometry.build_terrain_geometry(
            initial["terrain"]["cells"][0]
        )
        assert initial_geometry is not None
        assert initial_geometry.stride() == geometry.TERRAIN_VERTEX_STRIDE
        assert initial_geometry.attributeCount() == 5
        assert initial_geometry.attribute(3).semantic == QQuick3DGeometry.Attribute.ColorSemantic
        assert initial_geometry.attribute(3).offset == 32
        assert len(initial_geometry.vertexData()) == (
            (25 + 4 * 5 * 2) * geometry.TERRAIN_VERTEX_STRIDE
        )
        assert len(initial_geometry.indexData()) == 64 * 3 * 2
        character_geometry = geometry.build_character_geometry()
        assert character_geometry.objectName() == "gameCharacterBodyGeometry"
        assert character_geometry.stride() == geometry.CHARACTER_VERTEX_STRIDE
        assert len(character_geometry.vertexData()) // character_geometry.stride() == (
            assets.PROCEDURAL_CHARACTER_VERTEX_RECORDS
        )
        assert len(character_geometry.indexData()) // 2 // 3 == (
            assets.PROCEDURAL_CHARACTER_TRIANGLES
        )
        assert character_geometry.attribute(2).semantic == (
            QQuick3DGeometry.Attribute.ColorSemantic
        )
        assert len(character_geometry.vertexData()) // geometry.CHARACTER_VERTEX_STRIDE > 100
        assert len(character_geometry.indexData()) // 2 > 100
        pose_key = geometry.character_pose_key("WALK", math.pi / 2.0)
        assert pose_key == ("WALK", 2)
        walking_geometry = geometry.build_character_geometry(
            pose_key[0], pose_key[1] / geometry.CHARACTER_POSE_BUCKETS * math.tau
        )
        assert walking_geometry.objectName() == "gameCharacterBodyGeometry_CROWD_WALK_2"
        assert walking_geometry.vertexData() != character_geometry.vertexData()
        fisher_geometry = geometry.build_character_geometry(variant="WANDERER")
        guard_geometry = geometry.build_character_geometry(variant="GUARDIAN")
        critter_geometry = geometry.build_character_geometry(variant="CRITTER")
        assert fisher_geometry.objectName().startswith("gameCharacterBodyGeometry_WANDERER")
        assert guard_geometry.vertexData() != fisher_geometry.vertexData()
        assert critter_geometry.vertexData() != character_geometry.vertexData()
        assert geometry.character_variant_key("npc") == "CROWD"
        sphere_geometry = geometry.build_low_poly_sphere_geometry()
        assert sphere_geometry.objectName() == "gameLowPolySphereGeometry"
        assert sphere_geometry.stride() == geometry.VERTEX_STRIDE
        assert len(sphere_geometry.vertexData()) // geometry.VERTEX_STRIDE == 67
        assert len(sphere_geometry.indexData()) // 2 // 3 == 120
        assert len(sphere_geometry.indexData()) // 2 // 3 < 4900
        assert initial["physics"]["model"] == physics.MODEL
        assert initial["physics"]["mass_equivalent"] == 1.0
        assert initial["physics"]["gravity_status"] == "NOT_CONNECTED"
        assert abs(physics.real_nth_root(81, 4) - 3.0) < 0.000001
        assert abs(physics.real_nth_root(-27, 3) + 3.0) < 0.000001
        assert abs(physics.log_power(2, 10) - 1024.0) < 0.000001
        assert abs(physics.log_base(81, 3) - 4.0) < 0.000001
        assert physics.lp_norm((3, 4), 2) == 5.0
        try:
            physics.real_nth_root(-1, 2)
        except ValueError:
            pass
        else:
            raise AssertionError("negative even root was accepted")
        geometry_cache = geometry.TerrainGeometryCache()
        assert geometry_cache.geometry_for_cell(
            initial["terrain"]["cells"][0]
        ) is not None
        assert "TERRAIN_CELL_TARGETING_BRUSH" in initial["capabilities"]
        assert "SUBCELL_TERRAIN_SCULPTING" in initial["capabilities"]
        assert "TERRAIN_LOD_SKIRT_SEAMS" in initial["capabilities"]
        assert "CHARACTER_SHARED_LOW_POLY_BODY" in initial["capabilities"]
        assert "CHARACTER_PHASED_MESH_VARIANTS" in initial["capabilities"]
        assert "DETERMINISTIC_ROOT_POSE" in initial["capabilities"]
        assert "AUTHORED_GLTF2_ASSET_IMPORT" in initial["capabilities"]
        assert "SKINNED_ASSET_POSE_SEAM" in initial["capabilities"]
        assert "BOUNDED_AUTHORED_ASSET_INSTANCES" in initial["capabilities"]
        assert any(
            cell["visibility"]["simulation"] == "NO_LOCAL_PHYSICS"
            for cell in initial["terrain"]["cells"]
        )
        assert terrain.cell_seed(-2, 3) == terrain.cell_seed(-2, 3)
        assert terrain.height_at(5.0, -7.0) == terrain.height_at(5.0, -7.0)
        assert abs(
            terrain.height_at(16.0 - 0.000001, 4.0)
            - terrain.height_at(16.0 + 0.000001, 4.0)
        ) < 0.001
        terrain_doc = terrain.new_overrides()
        base_center_height = terrain.height_at(8.0, 8.0)
        edited, _ = terrain.apply_override(
            terrain_doc, 0, 0, height_delta_m=2.0
        )
        assert edited is True
        assert terrain.height_at(8.0, 8.0, overrides=terrain_doc) == (
            base_center_height + 2.0
        )
        assert abs(
            terrain.height_at(16.0 - 0.000001, 4.0, overrides=terrain_doc)
            - terrain.height_at(16.0 + 0.000001, 4.0, overrides=terrain_doc)
        ) < 0.001
        assert terrain.undo_override(terrain_doc)[0] is True
        brush_doc = terrain.new_overrides()
        brush_center_base = terrain.height_at(4.0, 4.0)
        brush_edge_base = terrain.height_at(7.0, 4.0)
        brushed, brush_result = terrain.apply_brush(
            brush_doc,
            0,
            0,
            center_x_m=4.0,
            center_z_m=4.0,
            radius_m=4.0,
            strength_m=2.0,
            falloff="LINEAR",
        )
        assert brushed is True
        assert brush_result["stamp"]["falloff"] == "LINEAR"
        assert terrain.height_at(4.0, 4.0, overrides=brush_doc) - brush_center_base > (
            terrain.height_at(7.0, 4.0, overrides=brush_doc) - brush_edge_base
        ) > 0.0
        assert abs(
            terrain.height_at(16.0 - 0.000001, 7.0, overrides=brush_doc)
            - terrain.height_at(16.0 + 0.000001, 7.0, overrides=brush_doc)
        ) < 0.001
        normalized_stamps = terrain._normalized_brush_stamps(brush_doc)
        brush_index = terrain._build_brush_index(normalized_stamps)
        for sample_x, sample_z in ((4.0, 4.0), (16.0, 7.0), (-3.5, 22.0)):
            assert terrain._height_delta_at(
                sample_x,
                sample_z,
                brush_doc,
                brush_stamps=normalized_stamps,
                brush_index=brush_index,
            ) == terrain._height_delta_at(
                sample_x,
                sample_z,
                brush_doc,
                brush_stamps=normalized_stamps,
            )
        clamped_doc = terrain.new_overrides()
        clamped, clamped_result = terrain.apply_brush(
            clamped_doc,
            0,
            0,
            center_x_m=999.0,
            center_z_m=-999.0,
            radius_m=999.0,
            strength_m=999.0,
            falloff="NOT_A_FALLOFF",
        )
        assert clamped is True
        assert clamped_result["stamp"] == {
            "id": "brush-000001",
            "cell_x": 0,
            "cell_z": 0,
            "center_x_m": 16.0,
            "center_z_m": 0.0,
            "radius_m": terrain.MAX_BRUSH_RADIUS_M,
            "strength_m": terrain.MAX_BRUSH_STRENGTH_M,
            "falloff": "SMOOTH",
        }
        budget_doc = terrain.new_overrides()
        for _ in range(terrain.MAX_BRUSH_STAMPS):
            assert terrain.apply_brush(budget_doc, 0, 0)[0] is True
        over_budget, over_budget_result = terrain.apply_brush(budget_doc, 0, 0)
        assert over_budget is False
        assert over_budget_result["error"] == "TERRAIN_AUTHORING_BRUSH_BUDGET"
        assert terrain.summary(budget_doc)["brush_count"] == terrain.MAX_BRUSH_STAMPS
        cloned_brush = terrain.clone_overrides(brush_doc)
        assert cloned_brush["stamps"] == brush_doc["stamps"]
        assert terrain.undo_override(cloned_brush)[0] is True
        assert cloned_brush["stamps"] == []
        assert terrain.cell_view(0, 0, lod="ORBIT")["geometry"]["representation"] == "POINT_DETAIL"
        assert initial["render"]["schema"] == "gg.game-engine.render.v1"
        assert initial["render"]["measurement"]["kind"] == "CPU_HOST_SNAPSHOT_TIMING"
        assert initial["render"]["instancing"]["strategy"] == "BOUNDED_QML_MODELS_FOR_WORLD_ENTITIES"
        assert initial["render"]["instancing"]["native_bridge"] == "QQUICK3D_INSTANCING_LINKED_FOR_FLORA"
        assert {row["name"] for row in initial["render"]["optional_layers"]} == {
            "DLSS",
            "FSR",
            "XeSS",
            "GPU_TIMESTAMPS",
        }
        assert initial["content"]["abilities"] == 7
        assert initial["content"]["items"] == len(starter["items"])
        assert initial["content"]["ambient_life"] == len(life_spawns)
        assert initial["content"]["vendors"] == 1
        assert initial["economy"]["schema"] == economy.SCHEMA
        assert initial["economy"]["wallet"]["gold"] == economy.STARTER_PLAYER_GOLD
        assert initial["items"]["catalog"]["loot_tables"] == 187
        assert initial["items"]["catalog"]["insertables"] == 12
        assert initial["items"]["catalog"]["asset_rows"] == 74
        assert initial["items"]["counts"]["by_location"]["GROUND"] == 4
        assert initial["items"]["interaction_target"]["action"] == "PICKUP"
        assert initial["render"]["item_instances"]["ground"] == 4
        assert "ITEM_INSTANCE_WORLD_STATE" in initial["capabilities"]
        assert "GEAR_EXACT_ORDER_RUNEWORDS" in initial["capabilities"]
        assert "INDIVIDUAL_NPC_STATE" in initial["capabilities"]
        assert "DUAL_PRESENTATION_RICH_3D_DOS_2D" in initial["capabilities"]
        assert "PRESENTATION_ONLY_FAILOVER" in initial["capabilities"]
        assert "SHARED_FALLBACK_ENTITY_ITEM_DATA" in initial["capabilities"]
        assert initial["content"]["enchantments"] == 2
        assert initial["content"]["races"] == 3
        assert initial["combat"]["resource"] == 100.0
        assert initial["progression"]["spec"] == "EXPLORER"
        assert initial["editor"]["placement_count"] == 0
        assert initial["cinematic"]["preset"] == "FIRST_ISLAND_DIORAMA"
        assert initial["network"]["persistence"]["mode"] == "MEMORY_ONLY"
        assert initial["npc"]["schema"] == npc.SCHEMA
        assert initial["npc"]["active"] == 6
        assert initial["npc"]["decision_hz"] == npc.DECISION_HZ
        assert initial["npc"]["perception"] == npc.PERCEPTION_MODEL
        assert initial["npc"]["navigation"] == npc.NAVIGATION_STATUS
        assert {row["archetype"] for row in initial["npc"]["agents"]} == {
            "WANDERER",
            "GUARDIAN",
            "CRITTER",
        }
        assert npc.normalize_archetype("not-a-profile") == "WANDERER"
        stepped_npc = runtime.step()
        assert all(
            "path_status" in row and "path_nodes" in row
            for row in stepped_npc["npc"]["agents"]
        )
        assert any(
            row["path_status"].startswith("READY")
            for row in stepped_npc["npc"]["agents"]
        )
        assert npc.decide(
            "WANDERER", "WANDER", 1.25, 4, 0, 4, 0, 0, 0, 0
        ) == npc.decide(
            "WANDERER", "WANDER", 1.25, 4, 0, 4, 0, 0, 0, 0
        )
        assert npc.decide(
            "WANDERER", "WANDER", 0, 0, 0, 0, 0, 4, 0
        ).state == "FOLLOW"
        assert npc.decide(
            "GUARDIAN", "WANDER", 0, 0, 0, 0, 0, 4, 0
        ).state == "ALERT"
        assert npc.decide(
            "CRITTER", "WANDER", 0, 0, 0, 0, 0, 1, 0
        ).state == "FLEE"
        no_los = npc.decide(
            "WANDERER", "WANDER", 0, 0, 0, 0, 0, 4, 0,
            phase=0,
            line_of_sight=False,
            memory_age=60,
            last_seen_x=4,
            last_seen_z=0,
        )
        assert no_los.state == "WANDER"
        remembered = npc.decide(
            "WANDERER", "WANDER", 0, 0, 0, 0, 0, 4, 0,
            phase=0,
            line_of_sight=False,
            memory_age=0.5,
            last_seen_x=4,
            last_seen_z=0,
        )
        assert remembered.state == "FOLLOW"
        assert remembered.stimulus == "LAST_SEEN_MEMORY"
        assert remembered.line_of_sight is False
        perception_runtime = GameEngineRuntime()
        try:
            guardian = next(
                index for index in perception_runtime._npc_indices
                if perception_runtime._npc_ids[index] == "npc-guardian-01"
            )
            # A controlled open-ground pair keeps the visibility and memory
            # checks independent of the enlarged authored village placements.
            with perception_runtime._lock:
                perception_runtime._x[guardian] = 0.0
                perception_runtime._z[guardian] = 3.0
                perception_runtime._y[guardian] = perception_runtime._terrain_height_locked(0, 3) + 0.65
                perception_runtime._x[0] = 0.0
                perception_runtime._z[0] = 0.0
            perception_runtime.step()
            visible_agent = next(
                row for row in perception_runtime.snapshot()["npc"]["agents"]
                if row["id"] == "npc-guardian-01"
            )
            assert visible_agent["stimulus"] == "VISIBLE_PLAYER"
            assert visible_agent["line_of_sight"] is True
            assert visible_agent["last_seen_age_s"] == 0.0
            perception_runtime._x[0] = 100.0
            perception_runtime._z[0] = 100.0
            for _ in range(6):
                perception_runtime.step()
            remembered_agent = next(
                row for row in perception_runtime.snapshot()["npc"]["agents"]
                if row["id"] == "npc-guardian-01"
            )
            assert remembered_agent["stimulus"] == "LAST_SEEN_MEMORY"
            assert remembered_agent["line_of_sight"] is False
            assert 0.0 < remembered_agent["last_seen_age_s"] < 2.0
            for _ in range(150):
                perception_runtime.step()
            expired_agent = next(
                row for row in perception_runtime.snapshot()["npc"]["agents"]
                if row["id"] == "npc-guardian-01"
            )
            assert expired_agent["stimulus"] == "NONE"
            assert expired_agent["state"] == "WANDER"
        finally:
            perception_runtime.shutdown()

        occluded_runtime = GameEngineRuntime()
        try:
            guardian = next(
                index for index in occluded_runtime._npc_indices
                if occluded_runtime._npc_ids[index] == "npc-guardian-01"
            )
            with occluded_runtime._lock:
                occluded_runtime._x[0] = 0.0
                occluded_runtime._z[0] = 0.0
                occluded_runtime._x[guardian] = 0.0
                occluded_runtime._z[guardian] = 2.8
                occluded_runtime._y[guardian] = occluded_runtime._terrain_height_locked(0, 2.8) + 0.65
                wall_x, wall_z = 0.0, 1.4
                wall = occluded_runtime._spawn_entity_locked(
                    "WALL",
                    wall_x,
                    occluded_runtime._terrain_height_locked(wall_x, wall_z) + 1.0,
                    wall_z,
                    (1.0, 1.0, 1.0),
                    "#46504f",
                    0.9,
                )
            assert wall is not None
            occluded_result = occluded_runtime.npc_interact()
            assert occluded_result["npc_interaction_result"]["error"] == (
                "NPC_INTERACTION_OCCLUDED"
            )
        finally:
            occluded_runtime.shutdown()
        deterministic_a = GameEngineRuntime()
        deterministic_b = GameEngineRuntime()
        try:
            for _ in range(60):
                deterministic_a.step()
                deterministic_b.step()
            assert deterministic_a.snapshot()["npc"]["agents"] == (
                deterministic_b.snapshot()["npc"]["agents"]
            )
        finally:
            deterministic_a.shutdown()
            deterministic_b.shutdown()
        interaction_runtime = GameEngineRuntime()
        try:
            wanderer = next(
                index
                for index in interaction_runtime._npc_indices
                if interaction_runtime._npc_ids[index] == "npc-wanderer-01"
            )
            interaction_runtime._x[0] = interaction_runtime._x[wanderer]
            interaction_runtime._z[0] = interaction_runtime._z[wanderer]
            interaction_view = interaction_runtime.snapshot()["npc"]["interaction"]
            assert interaction_view["available"] is True
            interaction_result = interaction_runtime.npc_interact()
            assert interaction_result["npc_interaction_result"]["id"] == (
                "npc-wanderer-01"
            )
            assert interaction_result["npc"]["interaction"]["last_result"][
                "interaction_count"
            ] == 1
        finally:
            interaction_runtime.shutdown()

        starter = content.starter_content()
        assert content.deterministic_loot(starter, 77) == content.deterministic_loot(starter, 77)
        rolled_item = content.deterministic_loot(starter, 88)
        rolled_item["instance_id"] = "loot-test"
        enchanted, enchant_result = content.enchant_item(
            starter, rolled_item, "enchant.wayfinder"
        )
        assert enchanted is True
        assert enchant_result["enchantment"]["stat"] == "loot_find"
        craft_inventory = {"item.sea_salt": 1, "item.sun_herb": 2}
        crafted, craft_result = content.craft(
            starter, "recipe.field_ration", craft_inventory
        )
        assert crafted is True
        assert craft_inventory["item.field_ration"] == 1
        assert craft_result["recipe_id"] == "recipe.field_ration"

        editor_doc = editor.new_document()
        placed, placed_result = editor.place(
            editor_doc, "RAMP", (1, 2, 3), (1, 1, 1), "#6aa8c8"
        )
        assert placed is True
        assert editor.summary(editor_doc)["placement_count"] == 1
        undone, _ = editor.undo(editor_doc)
        assert undone is True

        progression_state = progression.starter_state()
        xp_result = progression.grant_xp(progression_state, 100)
        assert xp_result["level"] == 2
        assert progression.add_talent(progression_state, "trailblazer")[0] is True
        assert progression_state["talent_points"] == 2
        assert progression.select_race(progression_state, "TIDEBORN")[0] is True
        assert progression.select_spec(progression_state, "WARDEN")[0] is True
        assert render.normalize_profile("modern") == "MODERN"
        assert render.normalize_presentation_mode("dos_2d") == render.DOS_2D
        assert render.presentation_view(render.RICH_3D)["simulation_unchanged"] is True
        assert render.build_render_view(
            "POTATO", active_entities=999, active_particles=999
        )["visibility"]["visible_instances"] == 48
        assert cinematic.build_view("ORBIT_WORLD_SCALE")["camera"]["mode"] == "PLANET_ORBIT"
        store = mmo.MemoryStateStore()
        save_result = store.save("player", {"level": 2})
        assert store.load("player")["level"] == 2
        assert save_result["mode"] == "MEMORY_ONLY"

        ability = runtime.activate_ability("ability.surge")
        assert ability["combat"]["last_ability"] == "ability.surge"
        assert ability["combat"]["resource"] < 100.0
        runtime.reset()
        socket_one = runtime.socket_item("starter-iron-saber", "rune.tir")
        socket_two = runtime.socket_item("starter-iron-saber", "rune.ort")
        socket_three = runtime.socket_item("starter-iron-saber", "rune.tal")
        assert socket_one["gear_result"]["socket_count"] == 1
        assert socket_two["gear_result"]["socket_count"] == 2
        assert socket_three["gear_result"]["runeword"]["id"] == "runeword.tideguard"
        enchanted_gear = runtime.enchant_gear(
            "starter-iron-saber",
            "enchant.aquatic_edge",
        )
        assert enchanted_gear["gear_result"]["enchantment"]["id"] == "enchant.aquatic_edge"
        crafted_gear = runtime.craft_gear(
            "recipe.fiber_rope",
            "station.workbench",
        )
        assert crafted_gear["gear_craft_result"]["recipe_id"] == "recipe.fiber_rope"
        gear_save = runtime.save_state()
        assert gear_save["persistence_result"]["mode"] == "MEMORY_ONLY"
        runtime.reset()
        restored_gear = runtime.load_state()
        restored_saber = next(
            row for row in restored_gear["items"]["equipment"]
            if row["instance_id"] == "starter-iron-saber"
        )
        assert restored_saber["gear"]["runeword"]["id"] == "runeword.tideguard"
        assert restored_saber["gear"]["enchantments"][0]["id"] == "enchant.aquatic_edge"
        loot = runtime.claim_loot(123)
        assert loot["loot_result"]["item"]["seed"] == 123
        assert len(loot["inventory"]["loot_items"]) == 1
        enchanted_runtime = runtime.enchant_last_loot()
        assert enchanted_runtime["enchant_result"]["enchantment"]["id"] == "enchant.wayfinder"
        crafted_runtime = runtime.craft_recipe()
        assert crafted_runtime["craft_result"]["recipe_id"] == "recipe.field_ration"
        runtime.grant_experience(100)
        assert runtime.snapshot()["progression"]["level"] == 2
        assert runtime.add_talent("trailblazer")["talent_result"]["rank"] == 2
        assert runtime.select_race("TIDEBORN")["progression"]["race"] == "TIDEBORN"
        assert runtime.select_spec("WARDEN")["progression"]["spec"] == "WARDEN"
        placed_runtime = runtime.editor_place("RAMP")
        assert placed_runtime["editor"]["placement_count"] == 1
        assert placed_runtime["simulation"]["active_entities"] == expected_sim_entities + 1
        undo_runtime = runtime.editor_undo()
        assert undo_runtime["editor"]["placement_count"] == 0
        assert undo_runtime["simulation"]["active_entities"] == expected_sim_entities
        placed_npc = runtime.editor_place("NPC")
        assert placed_npc["editor"]["placement_count"] == 1
        assert placed_npc["simulation"]["active_entities"] == expected_sim_entities + 1
        assert placed_npc["simulation"]["active_npcs"] == 7
        assert any(
            row["kind"] == "NPC" for row in placed_npc["render"]["entities"]
        )
        undo_npc = runtime.editor_undo()
        assert undo_npc["editor"]["placement_count"] == 0
        assert undo_npc["simulation"]["active_npcs"] == 6
        npc_persistence_runtime = GameEngineRuntime()
        try:
            npc_persistence_runtime.editor_place("NPC")
            npc_persistence_runtime.save_state()
            npc_persistence_runtime.reset()
            loaded_npc = npc_persistence_runtime.load_state()
            assert loaded_npc["editor"]["placement_count"] == 1
            assert loaded_npc["simulation"]["active_npcs"] == 7
            assert any(
                row["id"].startswith("editor-placement-")
                for row in loaded_npc["npc"]["agents"]
            )
        finally:
            npc_persistence_runtime.shutdown()
        terrain_edit_runtime = runtime.terrain_edit("RAISE")
        assert terrain_edit_runtime["terrain_editor"]["override_count"] == 1
        assert terrain_edit_runtime["terrain"]["cells"][0]["authoring"]["overridden"] is True
        target_edit_runtime = runtime.terrain_edit("WATER", 1, 0)
        assert target_edit_runtime["terrain_editor"]["override_count"] == 2
        assert target_edit_runtime["terrain_edit_result"]["target"] == {
            "key": "0:1:0",
            "x": 1,
            "z": 0,
            "source": "EXPLICIT_CELL",
        }
        assert next(
            cell for cell in target_edit_runtime["terrain"]["cells"]
            if cell["key"] == "0:1:0"
        )["authoring"]["water_mode"] == "WATER"
        runtime.editor_place("PROP")
        saved = runtime.save_state()
        assert saved["persistence_result"]["mode"] == "MEMORY_ONLY"
        runtime.reset()
        loaded = runtime.load_state()
        assert loaded["editor"]["placement_count"] == 1
        assert loaded["terrain_editor"]["override_count"] == 2
        assert any(
            cell["key"] == "0:1:0"
            for cell in loaded["terrain_editor"]["cells"]
        )
        assert loaded["network"]["persistence"]["revision"] == 2
        terrain_undo_runtime = runtime.terrain_undo()
        assert terrain_undo_runtime["terrain_editor"]["override_count"] == 1
        assert terrain_undo_runtime["terrain_edit_result"]["key"] == "0:1:0"
        terrain_undo_runtime = runtime.terrain_undo()
        assert terrain_undo_runtime["terrain_editor"]["override_count"] == 0
        invalid_target = runtime.terrain_edit("RAISE", 99, 99)
        assert invalid_target["error"] == "GAME_ENGINE_TERRAIN_CELL_NOT_LOADED"
        assert invalid_target["terrain_editor"]["override_count"] == 0
        brush_runtime = runtime.terrain_brush_edit(
            "RAISE",
            0,
            0,
            4.0,
            4.0,
            2.0,
            "GAUSSIAN",
        )
        assert brush_runtime["terrain_editor"]["brush_count"] == 1
        assert brush_runtime["terrain_brush_result"]["brush"]["falloff"] == "GAUSSIAN"
        updated_geometry = geometry_cache.geometry_for_cell(
            brush_runtime["terrain"]["cells"][0]
        )
        assert updated_geometry is not None
        assert updated_geometry.vertexData() != initial_geometry.vertexData()
        brush_saved = runtime.save_state()
        assert brush_saved["persistence_result"]["mode"] == "MEMORY_ONLY"
        runtime.reset()
        brush_loaded = runtime.load_state()
        assert brush_loaded["terrain_editor"]["brush_count"] == 1
        assert brush_loaded["terrain_editor"]["brushes"][0]["radius_m"] == 2.0
        brush_undo = runtime.terrain_undo()
        assert brush_undo["terrain_editor"]["brush_count"] == 0
        assert brush_undo["terrain_edit_result"]["kind"] == "BRUSH"
        assert runtime.set_render_profile("MODERN")["render"]["profile"] == "MODERN"
        assert runtime.set_cinematic_preset("ORBIT_WORLD_SCALE")["cinematic"]["preset"] == "ORBIT_WORLD_SCALE"
        runtime.reset()

        invalid_mode = runtime.set_movement_mode("SPACE")
        assert invalid_mode["error"] == "GAME_ENGINE_MOVEMENT_MODE_INVALID"
        assert invalid_mode["allowed"] == list(MOVEMENT_MODES)

        # The island origin is dry land. Exercise swimming in real deep water
        # and start at its moving surface, rather than inside the terrain.
        with runtime._lock:
            runtime._x[0], runtime._z[0] = 0.0, -300.0
            assert runtime._water_depth_locked(0, -300) > 5.0
        runtime.set_movement_mode("SWIM")
        with runtime._lock:
            runtime._y[0] = runtime._water_sample_locked(0, -300)["height_m"] + 0.18
            runtime._vx[0] = runtime._vy[0] = runtime._vz[0] = 0.0
        swim = runtime.snapshot()
        assert swim["player"]["movement_mode"] == "SWIM"
        assert swim["player"]["medium"] == "WATER"
        assert swim["terrain"]["player_surface"]["medium"] == "WATER"
        runtime.set_input(
            json.dumps(
                {
                    "forward": 1,
                    "vertical": 1,
                    "movement_mode": "SWIM",
                }
            )
        )
        for _ in range(12):
            runtime.step()
        swimming = runtime.snapshot()
        assert swimming["player"]["movement_mode"] == "SWIM"
        assert swimming["player"]["y"] > swim["player"]["y"]

        runtime.set_movement_mode("FLY")
        runtime.set_input(
            json.dumps(
                {
                    "forward": 1,
                    "vertical": 1,
                    "movement_mode": "FLY",
                }
            )
        )
        for _ in range(12):
            runtime.step()
        flying = runtime.snapshot()
        assert flying["player"]["movement_mode"] == "FLY"
        assert flying["player"]["y"] > swimming["player"]["y"]

        runtime.set_movement_mode("GROUND")
        runtime.reset()

        runtime.set_input(json.dumps({"throttle": 1, "steer": 0, "boost": True}))
        for _ in range(240):
            runtime.step()
        crossed_cell = runtime.snapshot()
        assert abs(crossed_cell["world"]["player_cell"]["z"]) >= 1
        assert crossed_cell["world"]["streaming"]["loaded_cells"][0]["key"] == (
            crossed_cell["world"]["player_cell"]["key"]
        )
        runtime.start()
        time.sleep(0.08)
        running = runtime.snapshot()
        assert running["state"] == "RUNNING"
        assert running["simulation"]["tick"] > 0
        assert running["player"]["boost"] is True

        burst = runtime.burst()
        assert burst["simulation"]["active_particles"] >= 48

        runtime.pause()
        runtime.start_recording()
        runtime.set_input(json.dumps({"throttle": 0.6, "steer": -0.2}))
        runtime.start()
        time.sleep(0.08)
        recorded = runtime.stop_recording()
        assert recorded["replay"]["recorded_inputs"] > 0

        replay = runtime.play_replay()
        assert replay["replay"]["replaying"] is True
        time.sleep(0.04)
        assert runtime.snapshot()["simulation"]["tick"] > 0

        stressed = runtime.set_stress(True)
        assert stressed["stress"] is True
        assert stressed["render"]["update_hz"] == STRESS_RENDER_UPDATE_HZ
        assert stressed["simulation"]["active_entities"] > 400
        assert stressed["simulation"]["active_entities"] <= 2048

        runtime.reset()
        runtime.step()
        stepped = runtime.snapshot()
        assert stepped["simulation"]["tick"] == 1
        assert stepped["state"] == "PAUSED"
    finally:
        runtime.shutdown()

    print("GAME_ENGINE_HOST_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
