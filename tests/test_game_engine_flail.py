"""Exported moving parts and real gravity/inertia/length constraints."""
import json,math,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PySide6.QtCore import QCoreApplication
from PySide6.QtQml import QJSEngine
from backend import game_engine_assets as assets
from backend.game_engine_caster_designs import equipment_visual
from tools.world.scale_sandover_environment import read_glb
from tools.world.build_caricature_asset_library import rows

def check_warhammer():
    source=equipment_visual('mace',5)['source']
    document,binary=read_glb(ROOT/'qml/assets/authored'/source)
    points=[p for mesh in document['meshes'] for primitive in mesh['primitives']
        for p in rows(document,binary,primitive['attributes']['POSITION'])[0]]
    front=min(p[0] for p in points)
    tips=set(tuple(round(n,5) for n in p) for p in points if abs(p[0]-front)<1e-5)
    assert len(tips)==4,('four corner teeth required',tips)
    assert len({p[1] for p in tips})==len({p[2] for p in tips})==2,tips
    face=front+.175*.26
    ring=[p for p in points if abs(p[0]-face)<1e-5]
    assert len(ring)>=8
    height=max(p[1] for p in ring)-min(p[1] for p in ring)
    depth=max(p[2] for p in ring)-min(p[2] for p in ring)
    assert .08<height<.12 and abs(height-depth)<1e-5,('small square face',height,depth)
    print('WARHAMMER=PASS: small square striking face, four projecting corner teeth, continuous head')

def check():
    row=equipment_visual('mace',7);rig=row['articulation']
    assert row['wielding_reference']=='1H' and row['weapon_subtype']=='flail'
    document,_=read_glb(ROOT/'qml/assets/authored'/row['source'])
    names={node.get('name') for node in document['nodes']}
    assert {'FLAIL_HANDLE',rig['head_node'],*rig['link_nodes']}<=names
    assert rig['links']==8 and len(rig['link_rest'])==8
    for filename in [rig['part_sources']['handle'],rig['part_sources']['head'],*rig['part_sources']['links']]:
        part,_=read_glb(ROOT/'qml/assets/authored'/Path(row['source']).parent/filename)
        assert part.get('meshes') and part.get('materials'),filename
    spec=assets.DEFAULT_STATIC_ITEM_ASSET_SPECS['itemmesh.weapon_mace']
    base=assets._inspect_static_item_asset('itemmesh.weapon_mace',spec)
    bound=assets.item_binding({'static_items':{'itemmesh.weapon_mace':base}},'itemmesh.weapon_mace',0,appearance_index=7)
    assert bound['articulation']==rig
    app=QCoreApplication.instance() or QCoreApplication([]);engine=QJSEngine()
    result=engine.evaluate((ROOT/'qml/components/engine/FlailPhysics.js').read_text().replace('.pragma library',''))
    assert not result.isError(),result.toString()
    def js(code):
        r=engine.evaluate(code);assert not r.isError(),r.toString()
        return json.loads(r.toString())
    def lengths(state,tolerance=.002):
        assert all(math.isfinite(n) for point in state['points'] for n in point)
        assert all(abs(math.dist(a,b)-state['length']/state['links'])<tolerance
            for a,b in zip(state['points'],state['points'][1:])),state
    settled=js('var s=create([0,1,0],.44,8);for(var i=0;i<1200;i++)s=step(s,[0,1,0],1/120);JSON.stringify(s)')
    lengths(settled)
    assert abs(settled['points'][-1][0])<.001 and settled['points'][-1][1]<.57
    # A sudden hand movement pulls the chain root immediately, leaving ball
    # inertia behind. Damping then lets it settle instead of looping forever.
    moving=js('s=step(s,[.15,1,0],1/120);JSON.stringify(s)')
    assert moving['points'][0]==[.15,1,0] and moving['points'][-1][0]<.10
    lengths(moving,.012)
    stopped=js('for(var i=0;i<1200;i++)s=step(s,[.15,1,0],1/120);JSON.stringify(s)')
    lengths(stopped);assert abs(stopped['points'][-1][0]-.15)<.001
    # Fixed timestep produces the same resting dynamics at both frame rates.
    different_fps=js('var a=create([2,3,-4],.44,8),b=create([2,3,-4],.44,8);for(var i=0;i<300;i++)a=step(a,[2,3,-4],1/60);for(var i=0;i<600;i++)b=step(b,[2,3,-4],1/120);JSON.stringify([a,b])')
    assert different_fps[0]['steps']==different_fps[1]['steps']==600
    assert different_fps[0]['points']==different_fps[1]['points']
    collided=js('var s=create([.205,1,0],.44,8);for(var i=0;i<600;i++)s=step(s,[.205,1,0],1/120,[[0,.2,0],[.035,1,0]],.215,.055);JSON.stringify(s)')
    lengths(collided)
    for p in collided['points'][1:]:
        assert p[0]>.08,'link or ball entered the handle'
    # A moving handle can hit the swinging ball. Preserve steel-link lengths
    # while resolving that contact, including the large jerks used by the GUI.
    for offset in (-.25,.25):
        stress=js('var s=create([.205,1,0],.44,8);for(var i=0;i<600;i++)s=step(s,[.205,1,0],1/120,[[0,.2,0],[.035,1,0]],.215,.055);var worst=0;for(var i=0;i<240;i++){s=step(s,['+str(.205+offset)+',1,0],1/120,[['+str(offset)+',.2,0],['+str(.035+offset)+',1,0]],.215,.055);for(var j=1;j<=8;j++)worst=Math.max(worst,Math.abs(norm(sub(s.points[j],s.points[j-1]))-.055));}JSON.stringify({state:s,worst:worst})')
        lengths(stress['state']);assert stress['worst']<.006,stress['worst']
    reset=js('s=step(s,[100,4,-20],.1);JSON.stringify(s)')
    lengths(reset);assert reset['points'][0]==[100,4,-20] and reset['steps']==0
    finite=js('JSON.stringify(avoidShaft([0,0,0],[0,0,0],[0,0,0],.2))')
    assert finite==[.2,0,0]
    # Node rotations must preserve baked mesh datums and align link axes.
    for direction in ([0,1,0],[0,-1,0],[1,0,0],[.3,-.8,.2]):
        turned=js('var d='+json.dumps(direction)+';JSON.stringify(rotate(rotationFromY(d),[0,1,0]))')
        expected=[n/math.sqrt(sum(v*v for v in direction)) for n in direction]
        assert math.dist(turned,expected)<1e-8
    print('FLAIL=PASS: eight authored links, real gravity, inertia, damping, fixed timestep, shaft collision, bounded reset and mesh rotation')

if __name__=='__main__':check_warhammer();check()
