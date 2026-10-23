"""Scene-only changes must preserve gameplay data without rebuilding terrain."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import game_engine_host as host, game_engine_items as items, game_engine_terrain as terrain
from backend.game_engine_animation import ACTION_CLIP_SECONDS


class CountingRuntime(host.GameEngineRuntime):
    full_snapshots = 0

    def snapshot_locked(self):
        self.full_snapshots += 1
        return super().snapshot_locked()


def check_scene(runtime, mutate):
    before = runtime.render_snapshot_locked()
    preserved = copy.deepcopy(before)
    full_count = runtime.full_snapshots
    mutate()
    actual = runtime.render_snapshot_locked()
    assert runtime.full_snapshots == full_count, "ordinary scene change rebuilt the full world"
    assert actual["player"]["movement_mode"] == runtime._movement_mode
    assert before == preserved, "scene refresh mutated an already published frame"
    current_ui = runtime.ui_snapshot_locked()
    runtime.snapshot_locked()
    expected = runtime.render_snapshot_locked()
    assert actual["render"]["entities"] == expected["render"]["entities"]
    for key in ("asset_instances", "item_instances", "item_asset_instances", "world_asset_instances", "ambient_life"):
        assert actual["render"][key] == expected["render"][key], key
    for key in ("ground", "inventory", "equipment"):
        assert current_ui["items"][key] == runtime.ui_snapshot_locked()["items"][key], key
    assert current_ui["living_world"] == runtime.ui_snapshot_locked()["living_world"]
    assert current_ui["npc"]["active"] == runtime.ui_snapshot_locked()["npc"]["active"]
    return actual


def main():
    runtime = CountingRuntime()
    try:
        runtime.snapshot_locked()
        full_count=runtime.full_snapshots
        original=copy.deepcopy(runtime.render_snapshot_locked())
        runtime._start_character_action_locked('player','OneHandSlash')
        acting=runtime.render_snapshot_locked()
        player=next(row for row in acting['render']['entities'] if row['kind']=='PLAYER')
        assert player['asset']['runtime_clip']=='OneHandSlash'
        assert player['animation']['action_serial']>0
        runtime._sim_time+=ACTION_CLIP_SECONDS['OneHandSlash']+.01
        settled=runtime.render_snapshot_locked()
        player=next(row for row in settled['render']['entities'] if row['kind']=='PLAYER')
        assert player['asset']['runtime_clip']=='Idle', 'expired action remained in the compact asset binding'
        assert player['animation']['action_serial']==0
        assert runtime.full_snapshots==full_count, 'combat clip switching rebuilt the world'
        assert not next(row for row in original['render']['entities'] if row['kind']=='PLAYER')['animation']['action']
        actor=runtime._combat_state['actors']['player']
        actor['alive']=False
        serial=runtime._start_character_action_locked('player','Death')
        runtime._sim_time+=ACTION_CLIP_SECONDS['Death']+.1
        dead=runtime.render_snapshot_locked()
        player=next(row for row in dead['render']['entities'] if row['kind']=='PLAYER')
        assert player['asset']['runtime_clip']=='Death'
        assert player['animation']['action_serial']==serial, 'death replayed instead of holding the terminal pose'
        actor['alive']=True
        respawned=runtime.render_snapshot_locked()
        assert next(row for row in respawned['render']['entities'] if row['kind']=='PLAYER')['asset']['runtime_clip']=='Idle'
        check_scene(runtime, lambda: runtime._color.__setitem__(0, "#b89a65"))
        check_scene(runtime, lambda: setattr(runtime, "_movement_mode", "FLY"))
        loot = items.make_instance(runtime._item_catalog, "cache-probe", "item.iron_saber",
                                   location="GROUND", position={"x": 7.0, "z": 8.0})
        def add_loot():
            runtime._item_instances[loot["instance_id"]] = loot
        frame = check_scene(runtime, add_loot)
        assert any(row["id"] == "item-cache-probe" for row in frame["render"]["entities"])
        def move_loot():
            loot["position"] = {"x": -9.0, "y": 0.0, "z": 11.0}
        check_scene(runtime, move_loot)
        def carry_loot():
            loot.update(location="INVENTORY", owner_id="player", slot_index=-1)
        check_scene(runtime, carry_loot)
        assert loot["slot_index"] >= 0, "scene refresh did not allocate a real inventory slot"
        def equip_loot():
            loot.update(location="EQUIPPED", owner_id="player", equipped_slot="WEAPON")
        frame = check_scene(runtime, equip_loot)
        player = next(row for row in frame["render"]["entities"] if row["kind"] == "PLAYER")
        assert any(row["instance_id"] == "cache-probe" for row in player["equipment"])
        check_scene(runtime, lambda: runtime._item_instances.pop("cache-probe"))
        spawn = runtime._life_spawns[0]
        def promote():
            assert runtime._promote_life_actor_locked(spawn)
            runtime._combat_state["actors"].pop(spawn["id"], None)
        check_scene(runtime, promote)
        assert spawn["id"] in runtime._combat_state["actors"]
        ui = runtime.ui_snapshot_locked()
        assert ui["living_world"]["promoted_count"] == 1
        assert ui["npc"]["active"] == len(runtime._npc_indices)

        # A profile change still refreshes the environment and enforces its cap.
        count = runtime.full_snapshots
        runtime._render_profile = "POTATO"
        frame = runtime.render_snapshot_locked()
        assert runtime.full_snapshots == count + 1
        assert len(frame["render"]["entities"]) <= 48
        # Return to RICH_3D from DOS with a real, updated fallback frame.
        runtime._presentation_mode = "DOS_2D"
        frame = runtime.render_snapshot_locked()
        assert frame["render"]["fallback"]["frame"]["glyphs"]
        runtime._presentation_mode = "RICH_3D"
        assert runtime.render_snapshot_locked()["render"]["presentation"]["mode"] == "RICH_3D"

        # Moving samples cannot flush fixed anchors, and both caches stay bounded.
        fixed = runtime._static_terrain_height_locked(8.0, -8.0)
        for i in range(host.MOVING_HEIGHT_CACHE_LIMIT + 25):
            x, z = i * .031, i * -.017
            assert runtime._terrain_height_locked(x, z) == terrain.height_at(
                x, z, host.WORLD_SEED, overrides=runtime._terrain_overrides)
        assert (8.0, -8.0) in runtime._static_height_samples
        assert runtime._static_terrain_height_locked(8.0, -8.0) == fixed
        assert len(runtime._height_samples) <= host.MOVING_HEIGHT_CACHE_LIMIT
        for i in range(host.STATIC_HEIGHT_CACHE_LIMIT + 25):
            runtime._static_terrain_height_locked(i * .021, i * .013)
        assert len(runtime._static_height_samples) <= host.STATIC_HEIGHT_CACHE_LIMIT

        # Sub-cell edits invalidate cached samples and the prepared brush index.
        ok, _ = terrain.apply_brush(runtime._terrain_overrides, 0, -1,
                                    center_x_m=8, center_z_m=-8, radius_m=3, strength_m=.7)
        assert ok
        expected = terrain.height_at(8, -8, host.WORLD_SEED, overrides=runtime._terrain_overrides)
        assert expected != fixed
        assert runtime._terrain_height_locked(8, -8) == expected
        assert runtime._static_terrain_height_locked(8, -8) == expected
        count = runtime.full_snapshots
        runtime.render_snapshot_locked()
        assert runtime.full_snapshots == count + 1, "terrain edit did not refresh the environment"
        runtime._refresh_nature_locked()
        plant = next(row for row in runtime._nature.rows if row["id"] == "nature:garden:sea_bell")
        assert plant["ground_height_m"] == expected

        # Replacing an authoring document at the same revision also invalidates.
        revision = runtime._terrain_overrides["revision"]
        runtime._terrain_overrides = terrain.new_overrides()
        runtime._terrain_overrides["revision"] = revision
        assert runtime._terrain_height_locked(8, -8) == fixed
        assert runtime._static_terrain_height_locked(8, -8) == fixed
        runtime.reset()
        assert runtime._terrain_height_locked(8, -8) == fixed
    finally:
        runtime.shutdown()
    print("GAME_ENGINE_RENDER_CACHE_TEST=PASS (scene/full parity, loot/equipment, promotion, modes, bounded exact heights, edit/document/reset invalidation)")


if __name__ == "__main__":
    main()
