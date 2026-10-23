"""Long-range map visibility, retained buffers, terrain edits and paced uploads."""
import gzip
import json
import math
import os
import struct
import sys
import time
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PySide6.QtGui import QGuiApplication
from PySide6.QtCore import Qt
from PySide6.QtTest import QAbstractItemModelTester
from backend.game_engine_world_trees import WorldTreeModel, sector_in_range, affected_sectors, UPLOAD_BATCH_CAP
from backend.game_engine_scene_driver import SceneDriver
from backend.game_engine_terrain import new_overrides, apply_brush, height_at
from backend.game_engine_ecology_render import instance_bytes
from backend.game_engine_ecology import TREE_SPECIES


def camera(x=0,y=100,z=0,heading=-90,pitch=0,far=10000):
    driver=SceneDriver()
    assert driver.set_view(json.dumps(dict(x=x,y=y,z=z,heading=heading,pitch=pitch,far=far,fov=45,aspect=1.6)))
    return driver.view


def settle(model,view,profile='PS2_CLASSIC'):
    model.set_view(view,profile)
    for _ in range(15000):
        model.drain()
        if not model.pending:return
    raise AssertionError('tree upload queue did not settle')


def main():
    app=QGuiApplication.instance() or QGuiApplication([])
    model=WorldTreeModel()
    tester=QAbstractItemModelTester(model,QAbstractItemModelTester.FailureReportingMode.Warning)
    assert model.catalog['tree_count']>5000
    # Saved groves have genuine spacing across sector boundaries. Candidate
    # cell coordinates must not produce the old visible trunk rows.
    occupied={};ids=set();bins=[0]*8
    spacing={'pine':48,'palm':44,'mangrove':58,'jungle':64,'deadwood':38}
    for sector in model.catalog['sectors']:
        rows=json.loads(gzip.decompress((model.assets/(sector.replace(':','_')+'.json.gz')).read_bytes()))
        for tree in rows:
            assert tree['id'] not in ids;ids.add(tree['id'])
            x,z=tree['x'],tree['z'];radius=spacing.get(tree['species'],55)
            bx,bz=math.floor(x/64),math.floor(z/64)
            for dx in (-1,0,1):
                for dz in (-1,0,1):
                    for px,pz,other in occupied.get((bx+dx,bz+dz),[]):
                        assert math.hypot(x-px,z-pz)>=max(radius,other)
            occupied.setdefault((bx,bz),[]).append((x,z,radius))
            bins[int(x%64//8)]+=1
    assert len(ids)==model.catalog['tree_count'] and min(bins)>len(ids)/16,bins
    view=camera();settle(model,view)
    assert model.rows and model.max_batches_per_tick<=UPLOAD_BATCH_CAP
    farrows=[r for r in model.rows if model.wanted[r['key']]['distance']>4000]
    assert farrows,'no map objects visible beyond the old 256m tree range'
    farrow=farrows[len(farrows)//2];entry=model.cached[farrow['base']]
    assert farrow['lod']==2
    table=entry['table'];buffer=bytes(table.getInstanceBuffer()[0])
    meta=model.wanted[farrow['key']]
    source=json.loads(gzip.decompress((model.assets/(farrow['sector'].replace(':','_')+'.json.gz')).read_bytes()))
    source=[r for r in source if r['species']==entry['species']]
    assert buffer==b''.join(instance_bytes(r) for r in source)
    assert len(buffer)==80*entry['count']
    assert model.data(model.index(model.rows.index(farrow)),Qt.UserRole+2) is table
    wanted_sectors={key for key,sector in model.catalog['sectors'].items() if sector_in_range(sector,view)}
    assert {r['sector'] for r in model.rows if r['key'] in model.wanted}==wanted_sectors
    assert sum(model.cached[key]['count'] for key in {r['base'] for r in model.rows})==sum(
        group['count'] for s in wanted_sectors for group in model.catalog['sectors'][s]['groups'].values())
    # A full turn never removes Models, recreates tables or queues uploads.
    original_rows=list(model.rows);original_uploads=model.upload_ticks
    for heading in range(-180,181,5):
        model.set_view(camera(heading=heading))
        assert model.rows==original_rows and not model.pending
    assert model.upload_ticks==original_uploads
    # Quality profiles simplify geometry, never truncate map placements.
    settle(model,view,'POTATO')
    assert {r['sector'] for r in model.rows}==wanted_sectors
    assert model.cached[farrow['base']]['table'] is table
    # Range reduction hides retained scene handles; return needs no re-upload.
    settle(model,camera(heading=0,far=2000))
    assert farrow['key'] not in model.wanted
    assert farrow in model.rows
    settle(model,view)
    assert model.cached[farrow['base']]['table'] is table
    assert bytes(table.getInstanceBuffer()[0])==buffer
    # Approaching a distant tree changes only geometry; x/z remain fixed.
    tree=source[0]
    close=camera(tree['x']+20,tree['y']+5,tree['z'],far=1000)
    settle(model,close)
    nearrows=[r for r in model.rows if r['key'] in model.wanted and r['sector']==farrow['sector'] and r['lod']==0 and model.cached[r['base']]['species']==entry['species']]
    assert nearrows
    near_matrices=[]
    for row in nearrows:
        e=model.cached[row['base']];assert e['geometries'][0] is not None
        payload=bytes(e['table'].getInstanceBuffer()[0]);near_matrices.extend(payload[i:i+80] for i in range(0,len(payload),80))
    from backend.game_engine_botanical_designs import tree_variant
    expected_near=[]
    for row in nearrows:
        spec=model.wanted[row['key']]
        expected_near.extend(instance_bytes(r) for r in source
            if [math.floor(r['x']/128),math.floor(r['z']/128)]==spec['chunk']
            and tree_variant(r['id'],r['species'])==spec['variant'])
    assert sorted(near_matrices)==sorted(expected_near),'near pages moved or lost their saved trees'
    assert instance_bytes(tree) in near_matrices,'approached tree has no detailed model'
    assert model.cached[farrow['base']]['table'] is table
    for i,row in enumerate(model.rows):
        if row['base']==farrow['base']:
            assert model.data(model.index(i),Qt.UserRole+2) is table
    assert bytes(table.getInstanceBuffer()[0])==buffer
    # A terrain brush moves trunks vertically at their saved map positions.
    doc=new_overrides()
    assert apply_brush(doc,math.floor(tree['x']/16),math.floor(tree['z']/16),center_x_m=tree['x'],center_z_m=tree['z'],radius_m=10,strength_m=2)[0]
    assert farrow['sector'] in affected_sectors(doc,model.catalog['sector_m'])
    model.set_terrain(doc);settle(model,close)
    changed=bytes(model.cached[farrow['base']]['table'].getInstanceBuffer()[0])
    original=struct.unpack_from('<20f',buffer);edited=struct.unpack_from('<20f',changed)
    assert original[3]==edited[3] and original[11]==edited[11]
    assert 1.99<edited[7]-original[7]<2.01
    # Undo/reset restores the exact baked buffer, without scattering new trees.
    model.set_terrain(new_overrides());settle(model,close)
    assert bytes(model.cached[farrow['base']]['table'].getInstanceBuffer()[0])==buffer
    settle(model,view)
    revision=model.upload_ticks;cached_ids={k:id(e['table']) for k,e in model.cached.items()}
    for _ in range(100):model.set_view(view)
    assert model.upload_ticks==revision and cached_ids=={k:id(e['table']) for k,e in model.cached.items()}
    # Native far meshes must be materially cheaper, with valid closed bounds.
    for species in TREE_SPECIES:
        low=model.meshes.geometry(species+':2');near=model.meshes.geometry(species+':0')
        assert len(bytes(low.indexData()))<=40*12
        assert len(bytes(low.indexData()))<len(bytes(near.indexData()))
    print(json.dumps(dict(status='PASS',checks='kilometre-range, no object cap, fixed source/native ABI, retained LOD/return/profile, brush/reset, zero settled rebuild, Qt model consistency',**model.measurements())))
    model.timer.stop()


if __name__=='__main__':main()
