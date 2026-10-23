"""Pure contract tests for the bounded authored/skinned asset seam."""

from __future__ import annotations

import math
import sys
from pathlib import Path
from urllib.parse import urlparse

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def main() -> int:
    from backend import game_engine_assets as assets
    from backend import game_engine_content as content
    from backend import game_engine_items as items
    from backend.game_engine_geometry import (
        ASSET_VERTEX_STRIDE,
        AssetGeometryCache,
    )

    catalog = assets.default_catalog()
    selected = catalog["selected"]
    assert catalog["schema"] == assets.SCHEMA
    assert catalog["policy"] == "ALLOWLISTED_LOCAL_GLTF2_RUNTIME_LOADER"
    assert catalog["instance_budget"] == assets.MAX_AUTHORED_INSTANCES
    assert catalog["character_visual"] == {
        "policy": assets.CHARACTER_VISUAL_POLICY,
        "preferred": assets.CHARACTER_VISUAL_PREFERRED,
        "fallback": assets.CHARACTER_VISUAL_FALLBACK,
        "max_active_models_per_character": 1,
    }
    assert catalog["fallback"]["mode"] == assets.CHARACTER_VISUAL_FALLBACK
    assert catalog["asset_kit"]["id"] == assets.PROCEDURAL_ASSET_STYLE_ID
    assert catalog["asset_kit"]["surface"] == "MATTE_FACETED_CLAY"
    assert catalog["procedural_asset_budget"] == assets.PROCEDURAL_ASSET_MAX_FAMILIES
    assert selected["status"] == "READY"
    assert selected["mode"] == "AUTHORED_SKINNED"
    assert selected["format"] == "GLTF2"
    assert selected["skinned"] is True
    assert selected["id"] == "gg-codex-original"
    assert selected["skeleton"] == {
        "skins": 1,
        "joints": 90,
        "skinned_primitives": 14,
    }
    assert selected["meshes"] == 1
    assert selected["primitives"] == 14
    assert selected["vertices"] == 4742
    assert selected["animations"] == 4
    assert {clip["name"] for clip in selected["clips"]} == {
        "Idle",
        "Walk",
        "Sprint",
        "Air",
    }
    assert selected["root_offset_m"] == -0.65
    assert Path(urlparse(selected["source"]).path).resolve() == assets.DEFAULT_CHARACTER_SOURCE
    assert set(selected["attachment_sockets"]) == {
        "HEAD",
        "CHEST",
        "MAIN_HAND",
        "OFF_HAND",
        "BACK",
        "FEET",
    }
    assert selected["attachment_sockets"]["MAIN_HAND"]["node"] == "SOCKET_MAIN_HAND"
    assert assets.attachment_for_slot("HEAD")["node"] == "SOCKET_HEAD"
    assert assets.attachment_for_slot("WAIST")["socket"] == ""
    assert set(catalog.get("cast", {})) == {"WANDERER", "GUARDIAN", "CRITTER"}
    fisher = assets.entity_binding(catalog, "WALK", 0.0, 1, asset_role="WANDERER")
    assert fisher["mode"] == "AUTHORED_SKINNED"
    assert fisher["clip"] == "Walk"
    idle_sockets = assets.entity_binding(catalog, "IDLE", 0.0, 0)["attachment_sockets"]
    assert "FEET" in idle_sockets
    crowd_sockets = assets.entity_binding(
        catalog, "WALK", 0.0, 1, asset_role="CROWD"
    )["attachment_sockets"]
    assert crowd_sockets == {}

    static_items = catalog["static_items"]
    assert set(static_items) == {
        "itemmesh.iron_saber",
        "container.supply_crate",
    }
    assert all(row["status"] == "READY" for row in static_items.values())
    assert all(row["mode"] == "AUTHORED_STATIC" for row in static_items.values())
    saber = assets.item_binding(catalog, "itemmesh.iron_saber", 0)
    assert saber["mode"] == assets.PROCEDURAL_ASSET_MODE
    assert saber["geometry_key"] == "itemmesh.iron_saber"
    assert saber["style_id"] == assets.PROCEDURAL_ASSET_STYLE_ID
    assert saber["authored_candidate"]["mode"] == "AUTHORED_STATIC"
    shard = assets.item_binding(catalog, "itemmesh.moon_shard", 0, "MATERIAL")
    assert shard["mode"] == assets.PROCEDURAL_ASSET_MODE
    assert shard["asset_class"] == "MATERIAL"
    bounded = dict(catalog)
    bounded["item_instance_budget"] = 0
    assert assets.item_binding(bounded, "itemmesh.iron_saber", 0)["mode"] == (
        assets.PROCEDURAL_ASSET_MODE
    )
    procedural_item = assets.procedural_item_asset(
        "container.supply_crate", "CONTAINER"
    )
    assert procedural_item["status"] == "READY"
    assert procedural_item["mode"] == assets.PROCEDURAL_ASSET_MODE
    assert procedural_item["geometry"]["vertex_stride"] == 40
    assert procedural_item["geometry"]["topology"] == "INDEXED_TRIANGLES"
    assert procedural_item["geometry"]["runtime_resolved"] is True
    assert procedural_item["geometry"]["budget"] == {
        "max_vertex_records": 4096,
        "max_triangles": 4096,
    }
    assert procedural_item["style"]["id"] == assets.PROCEDURAL_ASSET_STYLE_ID

    world_rock = assets.world_prop_asset("PROP", "e-0001")
    assert world_rock["geometry_key"] == "world.prop.mangrove"
    assert world_rock["variant"] == 1
    assert world_rock["mode"] == assets.PROCEDURAL_ASSET_MODE
    assert world_rock["style_id"] == assets.PROCEDURAL_ASSET_STYLE_ID
    assert assets.world_prop_asset("HOUSE", "e-0016")["geometry_key"] == (
        "world.stilt_hut"
    )
    palm_asset = assets.world_prop_asset("PALM", "e-0002")
    assert palm_asset["geometry_key"] == "world.palm"
    assert palm_asset["mode"] == "AUTHORED_STATIC"
    assert "gg-clay-palm.glb" in str(palm_asset.get("source") or "")
    assert palm_asset["anchor"] == "FEET"
    assert assets.world_prop_asset("LIGHT", "e-0011")["geometry_key"] == (
        "world.lantern"
    )

    # The full content table must resolve to actual bounded native geometry,
    # not merely a renderer label. Each family is cached by identity and uses
    # the shared position/normal/RGBA vertex ABI.
    geometry_cache = AssetGeometryCache()
    item_catalog = items.catalog_from_content(content.starter_content())
    assert item_catalog["asset_table"]
    for item_id, row in item_catalog["asset_table"].items():
        geometry = geometry_cache.geometry_for_item(
            row.get("geometry_key", item_id),
            row.get("kind", "ITEM"),
        )
        assert geometry.stride() == ASSET_VERTEX_STRIDE
        assert len(geometry.vertexData()) > 0
        assert len(geometry.indexData()) > 0
        assert geometry is geometry_cache.geometry_for_item(
            row.get("geometry_key", item_id),
            row.get("kind", "ITEM"),
        )
    for kind, variant in (
        ("world.prop.rock", 0),
        ("world.prop.mangrove", 1),
        ("world.prop.shrine", 2),
        ("world.prop.barrel", 3),
        ("world.ramp", 0),
        ("world.stilt_hut", 0),
        ("world.palm", 0),
        ("world.dock", 0),
        ("world.totem", 0),
        ("world.lantern", 0),
    ):
        geometry = geometry_cache.geometry_for_world_prop(kind, str(variant))
        assert geometry.stride() == ASSET_VERTEX_STRIDE
        assert len(geometry.vertexData()) > 0
        assert len(geometry.indexData()) > 0
        assert geometry is geometry_cache.geometry_for_world_prop(kind, str(variant))
        if kind == "world.palm":
            # Trunk plus a fountain of fronds, not a single stretched pole.
            palm_vertices = len(geometry.vertexData()) // ASSET_VERTEX_STRIDE
            assert palm_vertices >= 400
            assert str(geometry.objectName()).startswith("gameAuthoredWorld_palm")
        if kind == "world.stilt_hut":
            # Round stilts, plaster room and a thatch hat — not a beige crate.
            hut_vertices = len(geometry.vertexData()) // ASSET_VERTEX_STRIDE
            assert hut_vertices >= 350
        if kind == "world.dock":
            # Planks, pilings and a bollard — not a stretched box.
            dock_vertices = len(geometry.vertexData()) // ASSET_VERTEX_STRIDE
            assert dock_vertices >= 400

    idle = assets.entity_binding(catalog, "IDLE", 0.0, 0)
    assert idle["mode"] == "AUTHORED_SKINNED"
    assert idle["clip"] == "Idle"
    assert idle["clip_status"] == "READY"
    assert idle["phase"] == 0.0
    walk = assets.entity_binding(catalog, "WALK", math.tau * 2.0, 1)
    assert walk["mode"] == "AUTHORED_SKINNED"
    assert walk["clip"] == "Walk"
    assert walk["runtime_clip"] == "Walk"
    assert walk["clip_status"] == "READY"
    assert walk["phase"] == 0.0
    over_budget = assets.entity_binding(catalog, "SPRINT", float("nan"), 8)
    assert over_budget["mode"] == "PREVIEW_BUDGET"
    assert over_budget["source"] == ""
    assert over_budget["runtime_clip"] == ""
    assert over_budget["clip_status"] == "NOT_LOADED"
    assert over_budget["phase"] == 0.0

    crowd = assets.entity_binding(
        catalog,
        "WALK",
        0.0,
        1,
        asset_role="CROWD",
    )
    assert crowd["mode"] == "AUTHORED_SKINNED"
    assert crowd["id"] == catalog["crowd_variants"][1]["id"]
    assert crowd["animation_mode"] == "GLTF_SKINNED"
    assert crowd["clip"] == "Walk"
    assert crowd["runtime_clip"] == "Walk"
    assert crowd["clip_status"] == "READY"
    assert catalog["character_style"]["surface"] == "MATTE_FACETED_CLAY"
    assert catalog["crowd_visual"]["reference_policy"] == (
        "ORIGINAL_GG_BLENDER_MODELS_ONLY"
    )
    procedural = assets.procedural_character_asset()
    assert procedural["vertices"] == assets.PROCEDURAL_CHARACTER_VERTEX_RECORDS
    assert procedural["triangles"] == assets.PROCEDURAL_CHARACTER_TRIANGLES
    assert procedural["bytes"] == 50352
    assert procedural["geometry"] == {
        "vertex_stride": assets.PROCEDURAL_CHARACTER_VERTEX_STRIDE,
        "vertex_color": True,
        "pose_variants": assets.PROCEDURAL_CHARACTER_POSE_VARIANTS,
    }
    assert procedural["style"]["id"] == assets.PROCEDURAL_CHARACTER_STYLE_ID
    assert procedural["license"] == "ORIGINAL_RUNTIME_GENERATED"

    remote = assets.inspect_asset("https://example.invalid/hero.gltf")
    assert remote["status"] == "ERROR"
    assert remote["error"]["code"] == "ASSET_SOURCE_NOT_LOCAL"
    traversal = assets.inspect_asset("../hero.gltf")
    assert traversal["status"] == "ERROR"
    assert traversal["error"]["code"] == "ASSET_SOURCE_OUTSIDE_ALLOWLIST"
    unsupported = assets.inspect_asset("osint-globe-map.svg")
    assert unsupported["status"] == "ERROR"
    assert unsupported["error"]["code"] == "ASSET_FORMAT_UNSUPPORTED"

    print("GAME_ENGINE_ASSETS_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
