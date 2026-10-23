"""Real enchant/defeat hooks, optical blending and bounded saved cosmetics."""
import json,math,os,struct,sys
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QJSEngine
from backend.game_engine_host import GameEngineRuntime
from backend.game_engine_ground_cover import GroundCoverModel,ASSETS
from backend.game_engine_world_effects import lamp_anchors
from backend import game_engine_world_places as places
from backend.game_engine_geometry import ParticleBatchGeometry
from PIL import Image
from test_game_engine_world_trees import camera,settle

def main():
    app=QGuiApplication.instance() or QGuiApplication([]);js=QJSEngine()
    value=js.evaluate((ROOT/'qml/components/engine/WorldFx.js').read_text().replace('.pragma library',''))
    assert not value.isError(),value.toString()
    runtime=GameEngineRuntime()
    def rows(player,equipment):
        call='rows('+json.dumps(player)+','+json.dumps(equipment)+',"",1.85,{})'
        result=js.evaluate(call);assert not result.isError(),result.toString()
        return result.toVariant()
    try:
        assert not rows(runtime.snapshot()['player'],runtime.snapshot()['items']['equipment'])
        runtime.enchant_gear('starter-iron-saber','enchant.ember_edge')
        snapshot=runtime.snapshot();fx=rows(snapshot['player'],snapshot['items']['equipment'])
        assert len(fx)==14 and {r['kind'] for r in fx}=={'ENCHANT'}
        frame={'base':{'x':8.,'y':11.,'z':-2.},'tip':{'x':9.,'y':12.,'z':-3.}}
        for age in (0.,.3,1.,4.):
            call='rows('+json.dumps(dict(snapshot['player'],time_s=age))+','+json.dumps(snapshot['items']['equipment'])+',"",1.85,{},'+json.dumps({'MAIN_HAND':frame})+')'
            cloud=js.evaluate(call).toVariant();assert len(cloud)==14
            base=frame['base'];axis=[frame['tip'][k]-base[k] for k in ('x','y','z')]
            for row in cloud:
                delta=[row[k]-base[k] for k in ('x','y','z')]
                t=sum(a*d for a,d in zip(axis,delta))/sum(a*a for a in axis)
                assert 0<t<1
                assert math.sqrt(sum((d-t*a)**2 for a,d in zip(axis,delta)))<.20
                assert 0<row['opacity']<.5 and row['size']<=.36
        assert js.evaluate('isAdditive({kind:"ENCHANT"})').toBool()
        assert js.evaluate('isAdditive({kind:"FLAME"})').toBool()
        assert not js.evaluate('isAdditive({kind:"SMOKE"})').toBool()
        i=runtime._npc_indices[0]
        with runtime._lock:
            defeat=runtime._handle_npc_defeat_locked(runtime._npc_ids[i],i,{'damage':100})
        assert defeat['xp']['xp_gained']>0
        player=runtime.render_snapshot()['player'];birth=player['xp_visual']
        assert birth['x']==runtime._x[i] and birth['z']==runtime._z[i]
        for age in (0,.4,.8,1.14):
            p=dict(player,time_s=birth['time_s']+age)
            xp=[r for r in rows(p,[]) if r['kind']=='XP'];assert len(xp)==8
            assert all(math.isfinite(r[k]) for r in xp for k in ('x','y','z'))
        assert not [r for r in rows(dict(player,time_s=birth['time_s']+1.16),[]) if r['kind']=='XP']
        runtime.reset();assert runtime.snapshot()['player']['xp_visual'] is None
        town=places.catalog()['places'][0]
        first=lamp_anchors(town['x'],town['z'],lambda x,z:10)
        assert first==lamp_anchors(town['x'],town['z'],lambda x,z:10) and len(first)<=4
        assert all(0<=r['fade']<=1 and r['distance_m']<48 for r in first)
        alpha=ParticleBatchGeometry();luminous=ParticleBatchGeometry()
        assert alpha.update([dict(x=0,y=0,z=0,kind='SMOKE')])==1
        assert luminous.update(fx)==14
        assert luminous.geometry.stride()==48
        first=struct.unpack_from('<12f',bytes(luminous.geometry.vertexData()),0)
        assert first[-2:]==(.5,.5)
        model=GroundCoverModel();view=camera(x=town['x'],z=town['z'])
        settle(model,view)
        assert model.rows and model.catalog['interactive'] is False
        buffers={k:bytes(v['table'].getInstanceBuffer()[0]) for k,v in model.cached.items()}
        uploads=model.upload_ticks
        for angle in (-180,-90,0,90,180):
            model.set_view(camera(x=town['x'],z=town['z'],heading=angle))
            assert not model.pending
            assert uploads==model.upload_ticks
            assert buffers=={k:bytes(v['table'].getInstanceBuffer()[0]) for k,v in model.cached.items()}
        assert all(r['lod']==0 for r in model.rows)
        for name in model.catalog['meshes']:
            image=Image.open(ASSETS/(name+'.png'));assert image.mode=='RGBA'
            assert image.getchannel('A').getextrema()==(0,255)
        model.timer.stop();model.expiry_timer.stop()
        print(json.dumps(dict(status='PASS',real_weapon_enchant=True,real_defeat_xp=True,
            additive_separate_from_smoke=True,blade_clouds_follow_rotated_axis=True,
            cosmetic_cards=model.catalog['tree_count'],
            rotation_reuses_positions_and_buffers=True,interactive=False)))
    finally:runtime.shutdown()

if __name__=='__main__':main()
