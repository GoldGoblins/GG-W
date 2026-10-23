"""Actual firearm events and weapon families select their authored actions."""
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from backend import game_engine_firearms as guns, game_engine_items as items
from backend.game_engine_host import GameEngineRuntime, FIXED_DT
from backend.game_engine_animation import CLIP_FRAMES, ACTION_CLIP_SECONDS


def identity(family, variant):
    return next(key for number in range(10000)
                if items.item_appearance_index(key := f"anim-{family}-{variant}-{number}") == variant)


def main():
    runtime = GameEngineRuntime()
    try:
        assert runtime._player_attack_animation_clip_locked() == "OneHandSlash"
        runtime._npc_indices = []
        runtime._grounded=False
        runtime._vy[0]=-3.
        runtime._y[0]=runtime._ground_contact_height_locked(runtime._x[0],runtime._z[0])+.01
        runtime._running=True
        runtime._tick_locked(FIXED_DT)
        runtime._running=False
        assert runtime._grounded
        assert runtime._character_action_for_locked('player')['clip']=='Land'
        runtime._sim_time+=ACTION_CLIP_SECONDS['Land']+.01
        for variant in range(36):
            for key, old in list(runtime._item_instances.items()):
                if old.get("owner_id") == "player" and old.get("definition_id") == "item.weapon_pistol":
                    runtime._item_instances.pop(key)
            runtime._inventory.pop("item.weapon_pistol", None)
            key = identity("pistol", variant)
            row = items.make_instance(runtime._item_catalog, key, "item.weapon_pistol",
                                      location="EQUIPPED", owner_id="player", equipped_slot="MAIN_HAND")
            runtime._item_instances[key] = row
            spec = guns.profile(key)
            runtime._inventory[spec["ammo_id"]] = spec["capacity"] + 2
            runtime._reconcile_item_instances_locked()
            reload = runtime.reload_firearms()["firearm_result"]["hands"][0]
            assert reload["ok"], (variant, reload)
            assert runtime._character_action_for_locked("player")["clip"] == "Reload"
            runtime._sim_time = row["magazine"]["reload_until"] + .01
            shot = runtime.attack()["combat_result"]
            assert shot["ok"], (variant, shot)
            expected = ("ShotgunFire" if spec["weapon_subtype"] == "shotgun" else
                        "RifleFire" if spec["wielding_reference"] == "2H" else "PistolFire")
            action = dict(runtime._character_action_for_locked("player"))
            assert action["clip"] == expected, (variant, action, expected)
            assert runtime.attack()["combat_result"]["status"] == "COOLDOWN"
            assert runtime._character_action_for_locked("player")["serial"] == action["serial"]

        # Family dispatch uses each real, deterministic item appearance.
        expected = (("sword", 0, "OneHandThrust"), ("sword", 17, "TwoHandSlash"),
                    ("sword", 30, "TwoHandSlash"), ("axe", 3, "TwoHandOverhead"),
                    ("axe", 35, "ScytheSweep"), ("mace", 7, "FlailSwing"),
                    ("mace", 3, "OneHandOverhead"), ("mace", 18, "TwoHandOverhead"),
                    ("wand", 0, "WandCast"), ("staff", 0, "StaffCast"),
                    ("spear", 0, "SpearThrust"), ("bow", 0, "BowShot"),
                    ("whip", 0, "WhipCrack"), ("boomerang", 0, "BoomerangThrow"))
        for family, variant, clip in expected:
            equipped = dict(definition_id="item.weapon_" + family,
                            instance_id=identity(family, variant), equipped_slot="MAIN_HAND")
            runtime._player_equipped_instances_locked = lambda: [equipped]
            assert runtime._player_attack_animation_clip_locked() == clip, (family, variant, clip)
            assert clip in CLIP_FRAMES
        equipped=dict(definition_id='item.weapon_sword',instance_id=identity('sword',17),equipped_slot='MAIN_HAND')
        runtime._player_equipped_instances_locked=lambda:[equipped]
        runtime._character_actions.pop('player',None)
        for state,stance in (('IDLE','TwoHandIdle'),('WALK','TwoHandWalk'),('SPRINT','TwoHandSprint')):
            pose=dict(locomotion=state,cadence_hz=1.7,speed_mps=0.)
            assert runtime._decorate_character_animation_locked(pose,'player')==stance
            assert pose['action']=='' and pose['cadence_hz']==1.7
        view=items.instance_view(runtime._item_catalog,equipped)
        assert items.equipment_wielding(equipped)=='2H' and view['equip_slots']==['MAIN_HAND']
        assert view['visual']['grip_offset']==[0.,-.72*.7,0.]
        runtime._start_character_action_locked('player','TwoHandSlash')
        pose=dict(locomotion='WALK',cadence_hz=1.7,speed_mps=1.)
        assert runtime._decorate_character_animation_locked(pose,'player')=='TwoHandSlash'
        assert pose['cadence_hz']==0. and pose['action']=='TwoHandSlash'
        runtime._player_equipped_instances_locked = lambda: [
            dict(definition_id="item.weapon_pistol", instance_id=identity("pistol", 1), equipped_slot=slot)
            for slot in ("MAIN_HAND", "OFF_HAND")]
        assert runtime._player_attack_animation_clip_locked() == "DualPistolFire"
        print("CHARACTER_ACTION_EVENTS=PASS (landing, 36 gun reloads/shots/cooldowns, melee/caster dispatch, akimbo)")
    finally:
        runtime.shutdown()


if __name__ == "__main__":
    main()
