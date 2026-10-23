"""Real transactions drive world poses; failed attempts never retrigger them."""
import copy
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from backend.game_engine_host import GameEngineRuntime, FIXED_DT
from backend.game_engine_animation import ACTION_CLIP_SECONDS
from backend import game_engine_items as items


def near(runtime, species):
    runtime._nature._stamp = None
    runtime._ecology_view_locked()
    row = next(row for row in runtime._nature.rows if row["species"] == species)
    runtime._x[0], runtime._y[0], runtime._z[0] = row["x"] + .2, row["y"] + .65, row["z"]
    runtime._nature._stamp = None
    runtime._ecology_view_locked()
    return row["id"]


def pose(runtime):
    frame = runtime.render_snapshot_locked()
    return next(row for row in frame["render"]["entities"] if row["kind"] == "PLAYER")


def main():
    runtime = GameEngineRuntime()
    try:
        cases = (("sun_daisy", "PICK", "Gather", ""), ("sheep", "SHEAR", "Shear", "shears"),
                 ("goat", "MILK", "Milk", ""), ("rabbit", "PET", "Pet", ""),
                 ("frog", "CATCH", "NetCatch", "net"))
        for species, action, expected, tool in cases:
            runtime.reset()
            identity = near(runtime, species)
            result = runtime.nature_action(identity, action)
            assert "error" not in result, (species, result.get("error"))
            row = pose(runtime)
            assert row["asset"]["runtime_clip"] == expected, (species, row["animation"])
            assert row["animation"]["world_interaction"]
            assert row["animation"]["interaction_tool"] == tool
            serial = row["animation"]["action_serial"]
            inventory = copy.deepcopy(runtime._inventory)
            assert "error" in runtime.nature_action(identity, action)
            assert runtime._inventory == inventory
            assert runtime._character_action_for_locked("player")["serial"] == serial
            runtime._sim_time += ACTION_CLIP_SECONDS[expected] + .01
            assert not pose(runtime)["animation"]["world_interaction"]

        runtime.reset()
        runtime._x[0], runtime._z[0] = -250., -220.
        identity = near(runtime, "sunfin")
        result = runtime.nature_action(identity, "FISH")
        assert "error" not in result, result.get("error")
        row = pose(runtime)
        assert row["asset"]["runtime_clip"] == "FishCast"
        assert row["animation"]["interaction_tool"] == "rod"

        # Moving interrupts the planted working pose and drops its transient
        # tool. Item ownership and successful harvest remain untouched.
        before = copy.deepcopy(runtime._inventory)
        runtime._vx[0] = 3.
        row = pose(runtime)
        assert not row["animation"]["world_interaction"]
        assert row["animation"]["interaction_tool"] == ""
        assert runtime._inventory == before

        runtime.reset()
        ground = items.make_instance(runtime._item_catalog, "animation-loose-ore", "material.iron_ore",
                                     location="GROUND", position={"x": runtime._x[0], "y": runtime._y[0], "z": runtime._z[0]})
        runtime._item_instances[ground["instance_id"]] = ground
        assert "error" not in runtime.pickup_item(ground["instance_id"])
        assert pose(runtime)["asset"]["runtime_clip"] == "Pickup", "loose ore must not animate mining"

        runtime.reset()
        index = runtime._npc_index_for_id_locked("npc-guardian-01")
        runtime._x[0], runtime._z[0] = runtime._x[index] + .5, runtime._z[index]
        result = runtime.talk_npc("npc-guardian-01")
        assert "error" not in result, result.get("error")
        assert pose(runtime)["asset"]["runtime_clip"] == "Talk"
        assert runtime._character_action_for_locked("npc-guardian-01")["clip"] == "Talk"
        position = (runtime._x[index], runtime._z[index])
        runtime._tick_npcs_locked(FIXED_DT)
        assert (runtime._x[index], runtime._z[index]) == position, "speaking NPC slid or teleported"
        serial = runtime._character_action_for_locked("player")["serial"]
        assert "error" in runtime.talk_npc("npc-guardian-01", "invalid-choice")
        assert runtime._character_action_for_locked("player")["serial"] == serial

        # A real dead actor's held corpse pose cannot be replaced by work.
        runtime._combat_state["actors"]["player"]["alive"] = False
        serial = runtime._start_character_action_locked("player", "Death")
        assert runtime._start_character_action_locked("player", "Talk") == 0
        assert runtime._character_action_for_locked("player")["serial"] == serial
        print("WORLD_ANIMATION_EVENTS=PASS (actual harvesting/tools, fish/net/milk/shears/petting, loose-item pickup, conversation, failure atomicity, motion interrupt, death hold)")
    finally:
        runtime.shutdown()


if __name__ == "__main__":
    main()
