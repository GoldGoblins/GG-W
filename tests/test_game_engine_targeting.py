"""Target selection remains separate from authoritative melee resolution."""
import json, os, sys
from pathlib import Path
os.environ.setdefault("XDG_STATE_HOME","/tmp/gg-game-targeting-regression-state")
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.game_engine_host import GameEngineRuntime
from backend import game_engine_input

def main():
    r=GameEngineRuntime()
    for index,(x,z) in zip(r._npc_indices[:2],[(10.0,12.0),(-12.0,10.0)]):
        r._x[index],r._z[index]=x,z
        r._y[index]=r._terrain_height_locked(x,z)+.65
    assert game_engine_input.new_bindings()["bindings"]["TARGET_NEXT"]==["TAB"]
    first=r.cycle_target()["targeting"]["selected"]
    assert first and first["distance_m"]<=64
    health=dict(r._combat_state["actors"][first["id"]])
    second=r.cycle_target()["targeting"]["selected"]
    assert second["id"]!=first["id"]
    assert r.cycle_target(True)["targeting"]["selected"]["id"]==first["id"]
    assert r._combat_state["actors"][first["id"]]==health
    # A selected distant actor cannot be damaged by changing UI selection.
    assert r.attack()["combat_result"]["error"]=="COMBAT_TARGET_OUT_OF_RANGE"
    assert r._combat_state["actors"][first["id"]]==health
    assert not r.clear_target()["targeting"]["selected"]
    r.save_state();r.cycle_target();r.load_state()
    assert not r._combat_target_id
    r.cycle_target()
    selected=r._combat_target_id
    r._combat_state["actors"][selected]["alive"]=False
    assert not r.render_snapshot_locked()["targeting"]["selected"]
    assert r._combat_target_id==""
    r.cycle_target();r.reset()
    assert not r._combat_target_id
    r._x[0]=10000;r._z[0]=10000
    assert not r.cycle_target()["targeting"]["selected"]
    print(json.dumps({"status":"PASS","checks":"forward/reverse cycle, no selection damage, range validation, death/reset/distance clearing"}))
    return 0

if __name__=="__main__":raise SystemExit(main())
