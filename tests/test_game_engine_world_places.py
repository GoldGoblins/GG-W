"""Whole-atlas continuity, walkable content, persistent life and native assets."""
import copy
import gzip
import json
import math
import os
import struct
import sys
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QAbstractItemModelTester
from backend import game_engine_world_places as places,game_engine_life as life,game_engine_planet as planet
from backend.game_engine_world_population import WorldPopulation,VISUAL_LIMIT
from backend.game_engine_world_places_render import WorldPlacesModel
from backend.game_engine_host import GameEngineRuntime
from backend.game_engine_geometry import _gltf_accessor_bytes
from backend.game_engine_terrain import height_at
from backend.game_engine_ecology_render import instance_bytes
from test_game_engine_world_trees import camera,settle


def authored_content():
    doc=places.catalog();sites={p['id']:p for p in doc['places']}
    for field in ('places','roads','objects','residents'):
        assert len({r['id'] for r in doc[field]})==len(doc[field])
    assert {p['region_id'] for p in sites.values()}=={p['id'] for p in planet.LANDMASSES}
    assert (len(sites),len(doc['roads']),len(doc['residents']))==(48,52,312)
    adjacency={p:set() for p in sites}
    for road in doc['roads']:
        a,b=sites[road['from_place']],sites[road['to_place']]
        assert a['region_id']==b['region_id']==road['region_id']
        assert road['points'][0]==[a['x'],a['z']] and road['points'][-1]==[b['x'],b['z']]
        adjacency[a['id']].add(b['id']);adjacency[b['id']].add(a['id'])
        for p,q in zip(road['points'],road['points'][1:]):
            for i in range(21):
                x,z=[p[k]+(q[k]-p[k])*i/20 for k in range(2)]
                assert height_at(x,z)>1,(road['id'],x,z,'road crosses the sea')
    for region in planet.LANDMASSES:
        expected={p['id'] for p in sites.values() if p['region_id']==region['id']}
        seen=set();queue=[min(expected)]
        while queue:
            p=queue.pop()
            if p in seen:continue
            seen.add(p);queue.extend(adjacency[p]-seen)
        assert seen==expected
    # Test complete legs, including approach from each exact saved stop.
    # Grid-only clearance would miss an actor clipping a corner at a door.
    shapes={'cottage':(4.5,3.5),'tower':(4.5,4.5),'statue':(7,7),'forge':(5.5,3.5),
            'mine':(6,5),'observatory':(6.5,6.5),'gate':(9,3),'windmill':(4.5,4.5),'crate':(.8,.8),'lantern':(.4,.4)}
    for resident in doc['residents']:
        assert resident['route_mode'] in ('LOOP','PING_PONG') and len(resident['stops'])>=2
        site=sites[resident['place_id']]
        obstacles=[o for o in doc['objects'] if o['kind'] in shapes and
                   math.hypot(o['x']-site['x'],o['z']-site['z'])<120]
        for a,b in zip(resident['stops'],resident['stops'][1:]):
            count=max(1,math.ceil(math.dist(a[:2],b[:2])/.5))
            for i in range(count+1):
                x,z=[a[k]+(b[k]-a[k])*i/count for k in range(2)]
                for o in obstacles:
                    lx,lz,_,_=places.building_local(o,x,z);hx,hz=shapes[o['kind']]
                    assert not (abs(lx)<hx+.45/o['scale'] and abs(lz)<hz+.45/o['scale']),('route inside object',resident['id'],o['id'],x,z)
    return doc


def persistent_population():
    p=WorldPopulation();coins=sum(s['coins'] for s in p.stocks.values())+sum(s['inventory']['coins'] for s in p.people.values())
    for identity,s in p.spawns.items():
        period=s['_routine_period_s'];offset=s['route_offset_s']
        for part in s['_routine_segments']:
            t=period*2+part['end']-offset
            if t<.002:continue
            a=p.position(identity,t-.001);b=p.position(identity,t+.001)
            assert math.hypot(a['x']-b['x'],a['z']-b['z'])<=s['speed']*.002+1e-6,(identity,t)
    # The full logical world cannot build poses or sample terrain offscreen.
    with patch.object(life.animation_contract,'build_pose',side_effect=AssertionError('offscreen pose')):
        for step in range(7201):p.tick(step*.5)
    assert sum(s['coins'] for s in p.stocks.values())+sum(s['inventory']['coins'] for s in p.people.values())==coins,'caravans minted money'
    assert all(s['coins']>=0 for s in p.stocks.values())
    assert p.view()['work_visits']>100 and p.view()['trade_visits']>100
    assert any(r['memory'] for r in p.people.values()) and not p.active
    assert len(p.events)<=64 and len(p.encounters)<=8*4
    q=WorldPopulation();q.restore(p.save())
    assert q.save()==p.save()
    for identity in p.people:assert p.position(identity,3600.5)==q.position(identity,3600.5)
    identity=next(iter(p.people));before=p.position(identity,3601)
    p.pause_for_talk(identity,3601)
    for t in (3601,3609,3615):
        held=p.position(identity,t)
        assert (held['x'],held['z'])==(before['x'],before['z']) and held['vx']==held['vz']==0
    p.resume_route(identity,3615)
    resumed=p.position(identity,3615)
    assert (resumed['x'],resumed['z'])==(before['x'],before['z'])
    after=p.position(identity,3615.01)
    assert math.hypot(resumed['x']-after['x'],resumed['z']-after['z'])<=p.spawns[identity]['speed']*.01+1e-6
    # Timeout releases without waiting for a far-away region to be rendered.
    p.pause_for_talk(identity,3616)
    a=p.position(identity,3646-.001);b=p.position(identity,3646+.001)
    assert math.hypot(a['x']-b['x'],a['z']-b['z'])<=p.spawns[identity]['speed']*.002+1e-6
    identity=next(iter(p.people));spawn=p.spawns[identity];person=p.people[identity]
    p.resume_route(identity,3700)
    position=p.position(identity,3700.5)
    person.update(alive=False,health=0,respawn_at=3710,death_position={k:position[k] for k in ('x','z')})
    assert p.position(identity,3709)['activity']=='DEAD'
    # Select the actor's lane exactly at respawn: the only permitted reset.
    p.lane=sorted(p.regions).index(spawn['region_id']);p.tick(3710)
    assert person['alive'] and person['health']==60
    assert p.position(identity,3710)['x']==person['home']['x'] and p.position(identity,3710)['z']==person['home']['z']
    town=next(t for t in p.locations.values() if t['kind']=='TOWN')
    p.active=[];p.admit_bucket=None
    assert len(p.select(4000,town['x'],town['z']))<=2
    assert len(p.select(4000,town['x'],town['z']))<=2
    p.select(4000,0,0)
    assert not p.select(4000,town['x'],town['z']),'repeat calls exceeded admission interval'
    for n in range(1,9):p.select(4000+n*.25,town['x'],town['z'])
    assert 0<len(p.active)<=VISUAL_LIMIT
    count=0
    def height(x,z):
        nonlocal count
        count+=1;return height_at(x,z)
    rows=p.rows(4002,town['x'],town['z'],height)
    assert count<=VISUAL_LIMIT and len(rows)<=VISUAL_LIMIT
    for row in rows:
        point=p.position(row['id'],4002)
        assert math.hypot(row['x']-point['x'],row['z']-point['z'])<.001
    p.active=[]
    assert p.rows(4002,0,0,lambda *_: (_ for _ in ()).throw(AssertionError('offscreen height')))==[]
    return p.view()


def native_assets():
    model=WorldPlacesModel();tester=QAbstractItemModelTester(model,QAbstractItemModelTester.FailureReportingMode.Warning)
    view=camera();settle(model,view)
    assert not model.pending and model.max_batches_per_tick<=2
    assert model.measurements()['map_objects']==1479
    assert all(row['lod']==0 for row in model.rows if '/road-' in row['key'])
    assert any('/road-' in row['key'] and model.wanted[row['key']]['distance']>1024 for row in model.rows),'no far road page verified'
    tables={k:id(e['table']) for k,e in model.cached.items()};rows=list(model.rows);uploads=model.upload_ticks
    for heading in range(-180,181,15):
        model.set_view(camera(heading=heading));assert rows==model.rows and not model.pending
    assert tables=={k:id(e['table']) for k,e in model.cached.items()} and uploads==model.upload_ticks
    for entry in model.cached.values():
        sector=entry['sector'];source=json.loads(gzip.decompress((model.assets/(sector.replace(':','_')+'.json.gz')).read_bytes()))
        expected=[r for r in source if r['species']==entry['species']]
        assert bytes(entry['table'].getInstanceBuffer()[0])==b''.join(instance_bytes(r) for r in expected)
    data=(places.ASSETS/'gg-world-architecture-r1.glb').read_bytes()
    n,_=struct.unpack_from('<II',data,12);doc=json.loads(data[20:20+n]);blob=data[28+n:]
    assert len(doc['meshes'])==len(places.KINDS)
    for mesh in doc['meshes']:
        kind=next(k for k in places.KINDS if mesh['name'].startswith('GG_World_'+k))
        vertices,indices=places.kit_mesh(kind);expected={tuple(round(v,4) for v in struct.unpack_from('<3f',vertices,i)) for i in range(0,len(vertices),40)}
        actual=set();triangles=0
        for primitive in mesh['primitives']:
            assert 'COLOR_0' in primitive['attributes']
            payload,count,stride,_=_gltf_accessor_bytes(doc,blob,primitive['attributes']['POSITION'])
            actual.update(tuple(round(v,4) for v in struct.unpack_from('<3f',payload,i*stride)) for i in range(count))
            _,count,_,_=_gltf_accessor_bytes(doc,blob,primitive['indices']);triangles+=count
        assert expected==actual and triangles==len(indices),(kind,'Blender/native divergence')
    # Enter a settlement: the four near-model tables partition the very same
    # saved transforms used by its shared distant model.
    town=next(p for p in places.catalog()['places'] if p['kind']=='TOWN')
    settle(model,camera(town['x'],height_at(town['x'],town['z'])+20,town['z']))
    checked=0
    for sector,meta in model.catalog['sectors'].items():
        for species,group in meta['groups'].items():
            base=sector+'/'+species
            entries=[model.cached.get(base+'/v'+str(v)) for v in range(4)]
            if not group.get('variants') or not all(entries):continue
            actual=[]
            for entry in entries:
                assert all(g is not None for g in entry['geometries'].values())
                payload=bytes(entry['table'].getInstanceBuffer()[0]);actual.extend(payload[i:i+80] for i in range(0,len(payload),80))
            model.file.seek(group['offset']);original=model.file.read(group['count']*80)
            assert sorted(actual)==sorted(original[i:i+80] for i in range(0,len(original),80)),species
            checked+=1
    assert checked>=8,'near prop variants were not exercised'
    model.timer.stop()
    return model.measurements()


def runtime_integration():
    r=GameEngineRuntime()
    try:
        town=next(t for t in places.catalog()['places'] if t['kind']=='TOWN')
        r.explore_region(town['region_id']);r._sim_time=1000
        population=r._world_population
        from backend import game_engine_assets as assets
        for appearance in range(len(r._asset_catalog['crowd_variants'])):
            variants=[assets.entity_binding(r._asset_catalog,'IDLE',0,rank,asset_role='CROWD',variant_index=appearance) for rank in (3,7,8,19)]
            assert all(v['mode']=='AUTHORED_SKINNED' for v in variants)
            assert len({v['source'] for v in variants})==1,'loading order changed this persons appearance'
        identity=next(i for i,s in population.spawns.items() if s.get('home_object_id') and s['place_id']==town['id'])
        s=population.spawns[identity];r._sim_time=s['_routine_period_s']*2-s['route_offset_s']
        position=population.position(identity,r._sim_time)
        r._x[0]=position['x'];r._z[0]=position['z'];r._y[0]=height_at(r._x[0],r._z[0])+.65
        population.active=[identity]
        frame=r.render_snapshot()['render']['entities'];row=next(row for row in frame if row['id']==identity)
        assert row['asset']['mode']=='AUTHORED_SKINNED' and row['asset']['instance_rank']<32 and len(frame)<=96
        assert r.ui_snapshot()['npcs']['interaction']['target_id']==identity
        result=r.npc_interact()
        assert 'error' not in result and result['dialogue_result']['npc_id']==identity
        result=r.talk_npc(identity,'work')
        assert 'error' not in result and result['dialogue_result']['node']['speaker']==population.people[identity]['name']
        assert 'food' in result['dialogue_result']['node']['text']
        assert population.people[identity]['memory'][-1]['kind']=='TALKED_TO_PLAYER_WORK'
        invalid=r.talk_npc(identity,'not-a-choice');assert invalid.get('error')=='DIALOGUE_CHOICE_UNKNOWN'
        before=population.save();r.save_state();population.people[identity]['inventory']['food']=99
        r.load_state();assert r._world_population.save()==before
        assert r.snapshot()['dialogue']['node']['speaker']==r._world_population.people[identity]['name']
        r._x[0]+=1000
        assert r.talk_npc(identity,'leave').get('error')=='NPC_DIALOGUE_OUT_OF_RANGE'
        # Local-space cottage collision permits the actual open door and
        # supports a level floor, even after a rotated saved placement.
        house=next(o for o in places.catalog()['objects'] if o['id']==s['home_object_id'])
        a=math.radians(house['yaw']);scale=house['scale'];base=height_at(house['x'],house['z'])
        def point(x,z):return house['x']+(x*math.cos(a)+z*math.sin(a))*scale,house['z']+(-x*math.sin(a)+z*math.cos(a))*scale
        x,z=point(0,-3.35);assert math.dist((x,z),places.building_walls(x,z,base+.65,height_at))<1e-6
        x,z=point(4.35,0);assert math.dist((x,z),places.building_walls(x,z,base+.65,height_at))>.1
        assert abs(places.building_floor(house['x'],house['z'],base+.65,height_at)-(base+.3*scale+.65))<1e-6
    finally:r.shutdown()


def navigation_mode_reuse():
    from backend import game_engine_nav as nav,game_engine_terrain as terrain
    cells=[dict(x=0,z=0),dict(x=430,z=20),dict(x=4,z=4)]
    original=nav.build_nav_tiles(cells,movement_mode='GROUND')
    for mode in ('FLY','SWIM','GROUND'):
        expected=nav.build_nav_tiles(cells,movement_mode=mode)
        with patch.object(terrain,'height_at',side_effect=AssertionError('mode-only terrain rebuild')):
            actual=nav.tiles_for_mode(original,mode)
        assert actual==expected and all(r['movement_mode']=='GROUND' for r in original)
    r=GameEngineRuntime()
    try:
        with r._lock:
            baseline=copy.deepcopy(r._navigation_tiles_for_cells_locked(cells,'GROUND'))
            with patch.object(nav,'build_nav_tiles',side_effect=AssertionError('host discarded existing terrain')):
                for mode in ('FLY','GROUND','SWIM','GROUND'):
                    rows=r._navigation_tiles_for_cells_locked(cells,mode)
            assert rows==baseline
    finally:r.shutdown()


def main():
    app=QGuiApplication.instance() or QGuiApplication([])
    authored_content();population=persistent_population();native=native_assets();runtime_integration();navigation_mode_reuse()
    print(json.dumps(dict(status='PASS',checks='regional connectivity, complete path clearance, 312 continuous clocks, offscreen work/trade, coin conservation, memory/save/death/respawn, paced 12-rig cast, live dialogue/range, open door/floor, native retained map and Blender parity, exact navigation mode reuse without resampling',population=population,native=native)))


if __name__=='__main__':main()
