"""Real road surfaces, saved homes/routes and autonomous remembered meetings."""
import json
import math
import os
import struct
import sys
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PySide6.QtGui import QGuiApplication
from backend import game_engine_settlement as settlement, game_engine_life as life, game_engine_world as world
from backend.game_engine_host import GameEngineRuntime
from backend.game_engine_geometry import AssetGeometryCache
from backend.game_engine_terrain import height_at


def main():
    app=QGuiApplication.instance() or QGuiApplication([])
    cache=AssetGeometryCache();road=cache.geometry_for_world_prop('WORLD.SETTLEMENT_ROADS')
    fence=cache.geometry_for_world_prop('WORLD.SETTLEMENT_FENCES')
    data=bytes(road.vertexData());indices=struct.unpack('<'+'H'*(len(bytes(road.indexData()))//2),bytes(road.indexData()))
    assert len(data)>10000 and max(indices)<len(data)//40
    assert len(bytes(fence.indexData()))>1000
    # The live EXT export contains exactly the two route meshes, with world
    # positions and vertex colors matching the runtime's source data.
    from backend.game_engine_geometry import _gltf_accessor_bytes
    exported=(ROOT/'qml/assets/authored/world/gg-sandover-routes-r2.glb').read_bytes()
    n,_=struct.unpack_from('<II',exported,12);document=json.loads(exported[20:20+n]);blob=exported[28+n:]
    assert len(document['meshes'])==2
    for mesh in document['meshes']:
        kind='SETTLEMENT_ROADS' if 'ROADS' in mesh['name'] else 'SETTLEMENT_FENCES'
        native,triangles=settlement.mesh_data(kind)
        expected={tuple(round(v,4) for v in struct.unpack_from('<3f',native,i)) for i in range(0,len(native),40)}
        actual=set();count=0
        for primitive in mesh['primitives']:
            assert 'COLOR_0' in primitive['attributes']
            payload,size,stride,_=_gltf_accessor_bytes(document,blob,primitive['attributes']['POSITION'])
            actual.update(tuple(round(v,4) for v in struct.unpack_from('<3f',payload,i*stride)) for i in range(size))
            _,size,_,_=_gltf_accessor_bytes(document,blob,primitive['indices']);count+=size
        assert actual==expected and count==len(triangles)
    # Paving follows each saved route and the actual terrain, with upward
    # winding. It isn't another floating placeholder at the village origin.
    for offset in range(0,len(data),40):
        x,y,z,*_=struct.unpack_from('<10f',data,offset)
        assert abs(y-height_at(x,z)-.10)<.002
    for a,b,c in zip(indices[::3],indices[1::3],indices[2::3]):
        p,q,r=[struct.unpack_from('<3f',data,i*40) for i in (a,b,c)]
        assert (q[2]-p[2])*(r[0]-p[0])-(q[0]-p[0])*(r[2]-p[2])>0
    runtime=GameEngineRuntime()
    try:
        spawns={s['id']:s for s in runtime._life_spawns}
        for authored in settlement.catalog()['routines']:
            s=spawns[authored['id']]
            assert s['x']==authored['stops'][0][0]*world.ISLAND_LAYOUT_SCALE
            assert s['z']==authored['stops'][0][1]*world.ISLAND_LAYOUT_SCALE
            period=s['_routine_period_s'];previous=None
            for tick in range(0,int(period)*2):
                state=life.routine_state(s,tick*.5)
                assert height_at(state['x'],state['z'])>.5,(s['id'],'route enters sea',state)
                if previous:
                    assert math.hypot(state['x']-previous['x'],state['z']-previous['z'])<=s['speed']*.501
                previous=state
        with runtime._lock:
            # The player is far away. Fisher and merchant meet at their own
            # workplace, and the existing social engine commits real memories.
            runtime._x[0]=10000;runtime._z[0]=10000
            runtime._sim_time=20
            runtime._tick_population_locked()
            assert not runtime._promoted_life_ids,'far resident entered the physical pool'
            runtime._sim_time=1;runtime._tick=30
            runtime._tick_social_locked()
            history=runtime._social_state['history']
            assert any('ambient-fisher-01' in (e['a_id'],e['b_id']) and
                       'ambient-merchant-01' in (e['a_id'],e['b_id']) for e in history),history
            people=runtime._individual_state['individuals']
            assert any(m.get('kind')=='NPC_MEETING' for m in people['ambient-merchant-01']['memory']),people['ambient-merchant-01']
            far=runtime.render_snapshot()['render']['entities']
            assert all(row['hidden'] for row in far if row['id'].startswith('ambient-'))
            runtime._x[0]=0;runtime._z[0]=0
            near=runtime.render_snapshot()['render']['entities']
            assert any(not row['hidden'] and row.get('animation') for row in near if row['id'].startswith('ambient-'))
        # Save/load retains the encounter, identities and the routine clock.
        import copy
        memory=copy.deepcopy(runtime._individual_state['individuals']['ambient-merchant-01']['memory'])
        before=life.routine_state(runtime._life_spawns[0],runtime._sim_time)
        runtime.save_state()
        runtime._individual_state['individuals']['ambient-merchant-01']['memory']=[]
        runtime.load_state()
        assert runtime._individual_state['individuals']['ambient-merchant-01']['memory']==memory
        assert life.routine_state(runtime._life_spawns[0],runtime._sim_time)==before
        print('GAME_ENGINE_SETTLEMENT_TEST=PASS')
    finally:runtime.shutdown()


if __name__=='__main__':main()
