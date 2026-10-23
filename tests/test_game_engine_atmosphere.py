"""The fog conceals the actual coverage boundary; ambience stays deterministic."""
import json
import math
import sys
from pathlib import Path

from PySide6.QtQml import QJSEngine
from PySide6.QtCore import QCoreApplication

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.game_engine_render import PROFILES
from backend.game_engine_world_effects import environment_anchors,lamp_beacons,_lamps


def main():
    app=QCoreApplication([])
    engine=QJSEngine()
    code=(ROOT/'qml/components/engine/WorldAtmosphere.js').read_text().replace('.pragma library','')
    value=engine.evaluate(code)
    assert not value.isError(),value.toString()
    def js(expression):
        value=engine.evaluate('JSON.stringify('+expression+')')
        assert not value.isError(),value.toString()
        return json.loads(value.toString())
    for policy in PROFILES.values():
        limit=policy['world_view_distance_m']
        for altitude in (.75,3,200,10000):
            horizon=math.sqrt(2*1000000*altitude+altitude*altitude)
            clip=js(f'farClip({limit},{horizon},1000000)')
            assert 240<=clip<=limit
            for baked in ('true','false'):
                covered=js(f'coveredDistance({clip},{baked},4,16,6)')
                fog=js(f'fogRange({covered},{baked},4,16,6,.48)')
                assert 0<fog['near']<fog['far']<covered<=clip
                assert fog['density']==1,'Partially transparent fog exposes the cutoff'
                if baked=='false':assert fog['far']<4*16-6-16
    for biome in ('FIRST_ISLAND','TEMPERATE','JUNGLE','TUNDRA','VOLCANIC','MAELSTROM'):
        first=js(f'palette("{biome}",0,120)')
        last=js(f'palette("{biome}",120,120)')
        assert first==last,'Clock wrap must not flash the sky'
        day=js(f'palette("{biome}",45,120)')
        night=js(f'palette("{biome}",112,120)')
        assert day['keyEnergy']>night['keyEnergy']
        assert night['lampEnergy']>day['lampEnergy']
        # No discontinuity around the day/night phase boundaries.
        for t in (0,18,81.6,99.6,120):
            a=js(f'palette("{biome}",{max(0,t-.001)},120)')
            b=js(f'palette("{biome}",{t+.001},120)')
            assert abs(a['keyEnergy']-b['keyEnergy'])<.001
    height=lambda x,z:5
    a=environment_anchors(0,0,height)
    assert a and len(a)<=8
    assert a==environment_anchors(0,0,height)
    moved={row['id']:row for row in environment_anchors(5,3,height)}
    overlap=0
    for row in a:
        if row['id'] in moved:
            overlap+=1
            assert all(row[key]==moved[row['id']][key] for key in ('x','y','z','phase'))
    assert overlap,'Nearby movement should retain environmental anchors'
    assert environment_anchors(0,0,lambda x,z:-5)==[]
    from backend.game_engine_world_effects import _waterfalls
    w=_waterfalls()[0];angle=math.radians(w['yaw'])
    wx=w['x']+math.sin(angle)*w['length_m'];wz=w['z']+math.cos(angle)*w['length_m']
    cascade=environment_anchors(wx,wz,height)
    assert any(row.get('kind')=='WATERFALL' for row in cascade)
    assert len(cascade)<=8
    fx=(ROOT/'qml/components/engine/WorldFx.js').read_text().replace('.pragma library','')
    value=engine.evaluate(fx)
    assert not value.isError(),value.toString()
    def particles(time):
        return js('(function(){var r=[];emitEnvironment(r,'+json.dumps(a)+','+str(time)
                  +',palette("TEMPERATE",'+str(time)+',120));return r})()')
    day=particles(45);night=particles(112)
    assert 0<len(day)<=24 and len(night)<=72
    assert any(row['kind']=='AURA' for row in night)
    assert day==particles(45)
    # An entire enchant cloud contributes one light, with its actual colour.
    cloud=[dict(kind='ENCHANT',light_emitter='blade',x=2,y=1+i*.04,z=3,
                color='#df39f0',opacity=.6) for i in range(14)]
    cloud+= [dict(kind='MIST',x=0,y=0,z=0,color='#ffffff',opacity=1),
             dict(x=0,y=0,z=0,color='#ffffff',opacity=1)]
    sources=js('lightSources('+json.dumps(cloud)+',[],{x:0,y:0,z:0},1)')
    assert len(sources)==1 and sources[0]['color']=='#df39f0'
    assert sources[0]['light_radius_m']==2.5 and math.isclose(sources[0]['light_energy'],2.8*.6)
    for radius in (.4,2.5,8):
        coefficient=js(f'pointLightQuadraticFade({radius})')
        assert math.isclose(1/(1+radius*radius*coefficient*.0001),1/26)
    for kind,radius in (('FLAME',8),('LIGHTNING',10),('XP',3),('ARCANE',7)):
        rows=[dict(kind=kind,x=1,y=1,z=1,color='#39ff91',opacity=.8)]
        light=js('lightSources('+json.dumps(rows)+',[],{x:0,y:0,z:0},1)')[0]
        assert light['color']=='#39ff91' and light['light_radius_m']==radius
    lamps=[dict(id='saved-lamp',x=2,y=4,z=3,fade=.9)]
    lamp_sources=js('(function(){var rows=[];emitLamps(rows,'+json.dumps(lamps)
        +',112,1);return lightSources(rows,'+json.dumps(lamps)+',{x:0,y:0,z:0},1)})()')
    assert len(lamp_sources)==1 and lamp_sources[0]['light_radius_m']==8
    # Many active emitters cannot increase the fixed QML light pool.
    many=[dict(id='effect:'+str(i),kind='ARCANE',x=0,y=0,z=i,distance_m=i,
               light_radius_m=7,light_energy=1,color='#397cff') for i in range(100)]
    for policy in PROFILES.values():
        lights=js('nearbyLights('+json.dumps(many)+','+str(policy['max_dynamic_lights'])+')')
        assert len(lights)==policy['max_dynamic_lights']<=10
    # Real saved lamps beyond ordinary draw distance survive nearby crowding.
    far_lamp=dict(id='distant',kind='LAMP',x=0,y=4,z=110,
                  light_radius_m=8,light_energy=2.2,color='#ffbf6c')
    near=[dict(row,x=0,z=65+i) for i,row in enumerate(many[:30])]
    beacons=js('(function(){var rows=[];emitLightBeacons(rows,'+json.dumps(near)+','
        +json.dumps([far_lamp])+',{x:0,y:0,z:0},118,1,12);return rows})()')
    assert len(beacons)<=12 and any(row['z']==110 for row in beacons)
    assert all(row['through_fog'] for row in beacons)
    assert all(40<math.hypot(row['y'],row['z'])<118 for row in beacons)
    assert len(js('nearbyLights('+json.dumps([dict(far_lamp,distance_m=110)])+',10)'))==0
    # Beacon heights are sampled once per saved object; camera rotation only
    # changes visibility. The lamp's real position does not move with the view.
    anchor=_lamps()[0];origin=(anchor['x'],10,anchor['z']-100)
    view=(origin,(0,0,1),(1,0,0),(0,1,0),.4142,1.6,80)
    cache={};calls=[]
    def terrain(x,z):calls.append((x,z));return 5
    rows=lamp_beacons(view,118,terrain,12,cache);sampled=len(calls)
    repeat=lamp_beacons(view,118,terrain,12,cache)
    assert rows==repeat and len(calls)==sampled and len(rows)<=12
    saved={row['id']:row for row in rows}
    assert anchor['id'] in saved and saved[anchor['id']]['x']==anchor['x']
    assert saved[anchor['id']]['y']==5+4.3*anchor.get('scale',1)
    assert lamp_beacons(view,118,terrain,0,cache)==[]
    print('ATMOSPHERE_CONTRACT=PASS fog, clock, stable FX, coloured radii, shared light/beacon budgets')


if __name__=='__main__':main()
