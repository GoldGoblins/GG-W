"""Observed resident positions cannot jump at route, day or simulation seams."""
import copy
import math
import os
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from PySide6.QtGui import QGuiApplication
from backend import game_engine_life as life, game_engine_npc as npc
from backend.game_engine_host import GameEngineRuntime


def separation(a,b):
    return math.hypot(a['x']-b['x'],a['z']-b['z'])


def check_rows(spawns,boundary):
    dt=.002
    # Exercise the actual render rows, including near-player attention and
    # far-away unloading. They must agree on where a resident really is.
    before=life.proxy_rows(spawns,boundary-dt/2,player_x=0,player_z=0)
    after=life.proxy_rows(spawns,boundary+dt/2,player_x=0,player_z=0)
    far=life.proxy_rows(spawns,boundary+dt/2,player_x=10000,player_z=10000,
                        render_radius_m=life.RENDER_RADIUS_M)
    assert [(r['id'],r['x'],r['z']) for r in after]==[(r['id'],r['x'],r['z']) for r in far]
    for s,a,b in zip(spawns,before,after):
        # Rows round coordinates to a millimetre, so allow that rounding error.
        assert separation(a,b)<=s['speed']*dt+.0015,(s['id'],boundary,a,b)


def main():
    app=QGuiApplication.instance() or QGuiApplication([])
    runtime=GameEngineRuntime()
    try:
        spawns=copy.deepcopy(runtime._life_spawns)
        assert len(spawns)==24 and all(s.get('waypoints') for s in spawns)
        for day in range(10):
            for offset in (18,81.6,99.6,120):
                check_rows(spawns,day*120+offset)
        for s in spawns:
            period=s['_routine_period_s'];offset=s['route_offset_s']
            for cycle in (1,2,5):
                for edge in (0,*[part['end'] for part in s['_routine_segments']]):
                    boundary=cycle*period+edge-offset
                    if boundary>.001:check_rows([s],boundary)

        # A bent ping-pong route must retrace the bend, rather than closing
        # through a diagonal shortcut. Its endpoints have no duplicate wait.
        sample=dict(x=0,z=0,speed=1,route_mode='PING_PONG',waypoints=[
            dict(x=0,z=0,wait_s=2),dict(x=3,z=0,wait_s=0),dict(x=3,z=4,wait_s=3)])
        life.prepare_routine(sample)
        assert sample['_routine_period_s']==19
        for t,expected in ((0,(0,0)),(5,(3,0)),(9,(3,4)),(14,(3,2)),(16,(3,0)),(18,(1,0)),(19,(0,0))):
            row=life.routine_state(sample,t)
            assert (row['x'],row['z'])==expected,(t,row)
        # Older content without explicit waypoints is migrated into a closed
        # local path too, with no night-time home snap.
        old=dict(id='old-content',x=20,z=10,radius=8,speed=1.2,phase=.3)
        for boundary in (99.6,120,219.6,240):check_rows([old],boundary)

        with runtime._lock:
            # Promotion hands the full simulation the current position,
            # rather than resetting a route or using the spawn point.
            s=next(s for s in runtime._life_spawns if s.get('allow_promotion'))
            runtime._sim_time=99.599
            before=life.proxy_rows([s],runtime._sim_time)[0]
            assert runtime._promote_life_actor_locked(s)
            index=runtime._npc_index_for_id_locked(s['id'])
            assert separation(before,dict(x=runtime._x[index],z=runtime._z[index]))<.001
            assert (runtime._npc_home_x[index],runtime._npc_home_z[index])==(s['x'],s['z'])
            dt=1/60
            for _ in range(120):
                before=dict(x=runtime._x[index],z=runtime._z[index])
                runtime._tick+=1;runtime._sim_time+=dt
                runtime._tick_npcs_locked(dt)
                profile=npc.PROFILES[runtime._npc_archetype[index]]
                assert separation(before,dict(x=runtime._x[index],z=runtime._z[index]))<=profile['run_speed']*dt+1e-8
            # A displaced live NPC must walk back inside its home area. The
            # old home-radius safety clamp teleported this person 10 metres.
            runtime._x[index]=runtime._npc_home_x[index]+profile['wander_radius']+10
            runtime._z[index]=runtime._npc_home_z[index]
            runtime._vx[index]=runtime._vz[index]=0
            before=dict(x=runtime._x[index],z=runtime._z[index])
            runtime._tick_npcs_locked(dt)
            assert separation(before,dict(x=runtime._x[index],z=runtime._z[index]))<=profile['run_speed']*dt+1e-8,'home area correction teleported a living NPC'
            # Only a defeated actor with an elapsed respawn timer may reset
            # to the authored spawn. It must stay put until that timer ends.
            runtime._ensure_combat_actors_locked()
            actor=runtime._combat_state['actors'][s['id']]
            actor.update(alive=False,health=0,respawn_at=runtime._sim_time+5)
            before=dict(x=runtime._x[index],z=runtime._z[index])
            runtime._tick=3
            runtime._tick_npcs_locked(dt);runtime._tick_combat_locked()
            assert separation(before,dict(x=runtime._x[index],z=runtime._z[index]))==0
            runtime._sim_time+=5
            runtime._tick_combat_locked()
            assert (runtime._x[index],runtime._z[index])==(s['x'],s['z'])
            assert actor['alive'] and runtime._vx[index]==runtime._vz[index]==0
        print('GAME_ENGINE_ROUTE_CONTINUITY_TEST=PASS')
    finally:runtime.shutdown()


if __name__=='__main__':main()
