"""Shared deterministic geology, inland water, grotto contacts and native ABI."""
import json,math,struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend import game_engine_landscape as land,game_engine_planet as planet
from backend.game_engine_terrain import height_at
from backend.game_engine_host import GameEngineRuntime
from backend.game_engine_world_places import catalog as places,building_floor
from backend.game_engine_world import DEFAULT_PLANET_RADIUS_METERS as RADIUS

def main():
    doc=land.catalog();assert land.enabled() and doc['map_revision']==3
    assert len({r['id'] for r in doc['features']})==len(doc['features'])>=200
    assert {r['region_id'] for r in doc['features']}=={r['id'] for r in planet.LANDMASSES}
    peaks=[r for r in doc['features'] if r['kind']=='PEAK']
    assert max(height_at(r['x'],r['z']) for r in peaks)>1400
    for p in places()['places']:
        assert abs(height_at(p['x'],p['z'])-planet.base_surface_height(p['x'],p['z']))<.001,p['id']
    for row in doc['features']:
        x,z=row['x'],row['z'];h=height_at(x,z)
        assert math.isfinite(h) and height_at(x,z)==h
        if row['kind']=='LAKE':
            assert land.water_at(x,z)['level_m']==row['level_m']
            assert h<row['level_m']-3
            assert land.tree_density(x,z,h)==0
        elif row['kind']=='RIVER':
            assert all(a>=b for a,b in zip(row['levels_m'],row['levels_m'][1:]))
            assert row['levels_m'][-1]==0
            for a,b in zip(row['points'],row['points'][1:]):
                for t in (0.,.25,.5,.75,1.):
                    xx,zz=a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t
                    w=land.water_at(xx,zz)
                    assert height_at(xx,zz)<w['level_m']-.5,(row['name'],xx,zz)
        elif row['kind']=='GROTTO':
            roof=land.cave_outer_roof(row,0,0)
            assert land.contact_height(x,z,row['floor_m']+.65,height_at) is None
            assert abs(land.contact_height(x,z,roof+.65,height_at)-(roof+.65))<1e-8
            assert land.cave_collision(x,z,row['floor_m']+.65)==(x,z,row['floor_m']+.65)
            # From an inside approach the back wall blocks; the entrance stays open.
            a=math.radians(row['yaw']);px=x+43*math.sin(a);pz=z+43*math.cos(a)
            cx,cz,_=land.cave_collision(px,pz,row['floor_m']+1)
            assert abs(land.local(row,cx,cz)[1]-45)<1e-7 or abs(land.local(row,cx,cz)[1]-41.5)<1e-7
        elif row['kind']=='SEAT':
            assert building_floor(x,z,row['floor_m']+1,height_at) is not None
    runtime=GameEngineRuntime();lake=next(r for r in doc['features'] if r['kind']=='LAKE')
    with runtime._lock:
        water=runtime._water_sample_locked(lake['x'],lake['z'])
        assert set(('height_m','normal','slope','current_mps','vertical_velocity_mps','surface_model'))<=water.keys()
        assert runtime._water_depth_locked(lake['x'],lake['z'])>3
    native=json.loads((land.ASSETS/'world-landscape.catalog.json').read_text())
    cascades=json.loads((land.ASSETS/'waterfalls.catalog.json').read_text())
    assert cascades['variants']==4 and len(cascades['placements'])>=4
    for cascade in cascades['placements']:
        a=math.radians(cascade['yaw'])
        for t in (.1,.5,.9):
            x=cascade['x']+math.sin(a)*cascade['length_m']*t
            z=cascade['z']+math.cos(a)*cascade['length_m']*t
            water=land.water_at(x,z)
            assert abs(water['level_m']-(cascade['floor_m']-cascade['drop_m']*t))<.001
    assert native['map_revision']==planet.MAP_REVISION and native['feature_count']==len(doc['features'])
    assert (land.ASSETS/native['data_file']).stat().st_size==native['tree_count']*80
    triangles=0
    for name in native['meshes']:
        raw=(land.ASSETS/(name+'-0.ggmesh')).read_bytes();magic,stride,nv,ni=struct.unpack_from('<8sIII',raw)
        assert magic==b'GGFLORA1' and stride==40 and len(raw)==20+nv*40+ni*4
        assert nv<200000 and ni%3==0
        triangles+=ni//3
    # A bridge supports the body on top while leaving the water below usable.
    for b in doc['bridges']:
        x,z=b['x'],b['z'];top=b['deck_m']+.65
        assert land.contact_height(x,z,top,height_at)==top
        assert land.contact_height(x,z,height_at(x,z)+.65,height_at) is None
    # Compare changed mesh vertices with physical ground, including spherical projection.
    from tools.world.scale_sandover_environment import read_glb,Accessor,ASSETS
    glb,binary=read_glb(ASSETS/'gg-sandover-planet-surface-landscape.glb');count=0;maximum=0
    for mesh in glb['meshes']:
        for p in mesh['primitives']:
            assert 'COLOR_0' in p['attributes']
            a=Accessor(glb,binary,p['attributes']['POSITION'])
            for i in range(0,a.count,max(1,a.count//120)):
                x,y,z=a.row(i)
                if not any(r['kind'] in land.SHAPE_KINDS for r in land.nearby(x,z)):continue
                expected=math.sqrt(max(1,(RADIUS+height_at(x,z))**2-x*x-z*z))-RADIUS
                error=abs(expected-y);maximum=max(maximum,error);assert error<.12,(mesh['name'],x,z,error)
                count+=1
    assert count>100
    print(json.dumps(dict(status='PASS',features=len(doc['features']),peaks=len(peaks),native_pages=native['tree_count'],landmark_water_triangles=triangles,mesh_physics_samples=count,max_error_m=maximum)))
if __name__=='__main__':main()
