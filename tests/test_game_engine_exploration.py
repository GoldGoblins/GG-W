"""Exploration controls, known destination bounds and new runtime assets."""
import sys, json, math
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import game_engine_input as keys, game_engine_planet as planet
from backend import game_engine_mobility as mobility, game_engine_assets as assets
from backend.game_engine_host import GameEngineRuntime

def main():
    defaults=keys.new_bindings()['bindings']
    assert defaults['PRIMARY_ATTACK']==['T'] and defaults['TOGGLE_HOVERBOARD']==['V']
    legacy=keys.normalize_bindings({'bindings':{'PRIMARY_ATTACK':['V'],'TOGGLE_HOVERBOARD':['V']}})['bindings']
    assert legacy['PRIMARY_ATTACK']==['T'] and legacy['TOGGLE_HOVERBOARD']==['V']
    r=GameEngineRuntime()
    before=r.snapshot()['player']
    assert r.explore_region('invalid')['error']=='EXPLORATION_REGION_UNKNOWN'
    assert r.snapshot()['player']['x']==before['x']
    for region in planet.map_contract()['landmasses']:
        result=r.explore_region(region['id'])
        assert result['exploration_result']['region']==region['id']
        assert r._vehicle_kind=='NONE' and r._movement_mode=='FLY'
        assert abs(r._y[0]-r._terrain_height_locked(r._x[0],r._z[0])-8)<1e-8
        assert r._vx[0]==r._vy[0]==r._vz[0]==0
    for boost,target in [(False,80),(True,180)]:
        state={'x':0,'y':100,'z':0,'vx':0,'vy':0,'vz':0,'yaw':0}
        for _ in range(180):
            v=mobility.flight_step(**state,forward=1,strafe=0,turn=0,vertical=0,boost=boost,terrain_y=0,dt=1/60)
            state={k:v[k] for k in state}
        assert abs(v['speed']-target)<.01
        for _ in range(60):
            v=mobility.flight_step(**state,forward=0,strafe=0,turn=0,vertical=0,boost=boost,terrain_y=0,dt=1/60)
            state={k:v[k] for k in state}
        assert v['speed']==0
    for asset_id,path in assets.BLENDER_CHARACTER_SOURCES.items():
        v=assets.inspect_asset(path,asset_id)
        assert v['status']=='READY' and v['skinned'] and v['animations']==11,(path,v)
        assert path.name.startswith('gg-crew-')
    assert len(assets.BLENDER_CHARACTER_SOURCES)==9
    assert all(p.name.startswith('gg-crew-') for p in assets.CROWD_LOD_SOURCES.values())
    rows=GameEngineRuntime().snapshot()['render']['entities']
    actors=[row for row in rows if row.get('kind') in ('ACTOR','NPC','PLAYER')]
    assert len(actors)>8
    for row in actors:
        asset=row.get('asset') or {}
        assert asset.get('mode')=='AUTHORED_SKINNED',(row['id'],asset)
        assert '/gg-crew-' in asset['source']
        assert asset['instance_rank']<asset['instance_budget']
    print('GAME_ENGINE_EXPLORATION_TEST=PASS')
    return 0
if __name__=='__main__':raise SystemExit(main())
