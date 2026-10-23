"""Regression tests for bounded schedules and ambient player stimuli."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def main() -> int:
    from backend import game_engine_life as life

    spawns = life.spawns_from_content({"ambient_life": life.starter_spawns()})
    assert len(spawns) == 24
    assert len({row["id"] for row in spawns}) == 24
    assert life.world_clock(0)["phase"] == "DAWN"
    assert life.world_clock(105)["phase"] == "NIGHT"
    assert life.world_clock(120)["day"] == 2

    first = life.proxy_rows(spawns, 0.0, player_x=100.0, player_z=100.0)
    second = life.proxy_rows(spawns, 0.0, player_x=100.0, player_z=100.0)
    assert first == second
    assert all(row["kind"] == "ACTOR" for row in first)
    assert all(
        row["animation"]["schema"] == "gg.game-engine.animation.v1"
        for row in first
    )
    assert any(row['life']['route']=='AUTHORED_ROUTINE' for row in first)

    fisher_before=next(row for row in first if row['id']=='ambient-fisher-01')
    noticed = life.proxy_rows(spawns, 0.0, player_x=fisher_before['x'], player_z=fisher_before['z'])
    fisher = next(row for row in noticed if row["id"] == "ambient-fisher-01")
    assert fisher["life"]["activity"] == "NOTICE_PLAYER"
    assert fisher["life"]["stimulus"] == "PLAYER_NEAR"
    assert fisher["speed"] == 0.0

    night = life.proxy_rows(spawns, 110.0,player_x=10000,player_z=10000)
    assert all(row['life']['route']=='AUTHORED_ROUTINE' for row in night)
    view = life.build_view(night, 110.0)
    assert view["population"] == 24
    assert any(row['life']['activity']=='TRAVELING' for row in night)
    assert view["clock"]["phase"] == "NIGHT"

    # Every authored loop returns continuously, at walking speed, to saved
    # stops. Midnight/camera movement cannot teleport its residents.
    for spawn in spawns:
        assert spawn.get('waypoints')
        period=spawn['_routine_period_s']
        before=life.routine_state(spawn,period-.001)
        after=life.routine_state(spawn,period+.001)
        import math
        assert math.hypot(after['x']-before['x'],after['z']-before['z'])<=spawn['speed']*.0021
        for t in range(int(period)):
            a,b=life.routine_state(spawn,t),life.routine_state(spawn,t+.1)
            assert math.hypot(b['x']-a['x'],b['z']-a['z'])<=spawn['speed']*.1001

    heights=[]
    far=life.proxy_rows(spawns,15,player_x=10000,player_z=10000,
                        terrain_height=lambda x,z:heights.append((x,z)) or 1,
                        render_radius_m=life.RENDER_RADIUS_M)
    assert not heights and all(r['hidden'] and r['animation'] is None for r in far)
    near=life.proxy_rows(spawns,15,player_x=100,player_z=100,render_radius_m=life.RENDER_RADIUS_M)
    assert [(r['id'],r['x'],r['z']) for r in far]==[(r['id'],r['x'],r['z']) for r in near]
    traveler=next(s for s in spawns if s['id']=='ambient-traveler-01')
    moving=next(life.routine_state(traveler,t) for t in range(100) if life.routine_state(traveler,t)['vx'] or life.routine_state(traveler,t)['vz'])
    time=next(t for t in range(100) if life.routine_state(traveler,t)==moving)
    passing=life.proxy_rows([traveler],time,player_x=moving['x'],player_z=moving['z'])[0]
    assert passing['life']['attention'] and passing['speed']>0 and passing['motion_state']=='WALK'

    print("GAME_ENGINE_LIFE_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
