"""Shipped mesh geometry, magic cores, hand rules and actual wand combat."""
import hashlib,json,math,struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend import game_engine_assets as assets,game_engine_items as items,game_engine_gear as gear
from backend.game_engine_caster_designs import BANKS,equipment_visual,wand_profile
from backend.game_engine_host import GameEngineRuntime
from tools.world.scale_sandover_environment import read_glb
from tools.world.build_caricature_asset_library import rows

def identity(family,variant):
    return next(f'qa-caster-{family}-{variant}-{i}' for i in range(10000)
        if items.item_appearance_index(f'qa-caster-{family}-{variant}-{i}')==variant)

def accessor_values(document,binary,index):
    a=document['accessors'][index];view=document['bufferViews'][a['bufferView']]
    width={'SCALAR':1,'VEC2':2,'VEC3':3}[a['type']]
    kind={5121:'B',5123:'H',5125:'I',5126:'f'}[a['componentType']]
    fmt='<'+kind*width;stride=view.get('byteStride',struct.calcsize(fmt))
    offset=view.get('byteOffset',0)+a.get('byteOffset',0)
    return [struct.unpack_from(fmt,binary,offset+i*stride) for i in range(a['count'])]

def check_meshes():
    root=ROOT/'qml/assets/authored';bounds={};maximum=0
    for family,designs in BANKS.items():
        visual=json.loads((root/'items'/f'weapon-{family}.variants.json').read_text())
        assert len(visual)==36 and len({r['name'] for r in visual})==36
        assert len({d['construction'] for d in designs})==36
        asset_id='itemmesh.weapon_'+family
        base=assets._inspect_static_item_asset(asset_id,assets.DEFAULT_STATIC_ITEM_ASSET_SPECS[asset_id])
        assert base['status']=='READY',base.get('error')
        shapes=[]
        for v,row in enumerate(visual):
            assert row['name']==designs[v]['name']
            document,binary=read_glb(root/row['source']);points=[];triangles=0;glows=[]
            for mesh in document['meshes']:
                for primitive in mesh['primitives']:
                    pos,_,_=rows(document,binary,primitive['attributes']['POSITION'])
                    normal,_,_=rows(document,binary,primitive['attributes']['NORMAL'])
                    uv=accessor_values(document,binary,primitive['attributes']['TEXCOORD_0'])
                    assert all(math.isfinite(n) for p in pos+normal+uv for n in p)
                    assert all(.98<math.sqrt(sum(n*n for n in p))<1.02 for p in normal)
                    ix=accessor_values(document,binary,primitive['indices'])
                    indices=[int(p[0]) for p in ix]
                    assert len(indices)%3==0 and max(indices)<len(pos)
                    for ia,ib,ic in zip(indices[::3],indices[1::3],indices[2::3]):
                        ab=[pos[ib][i]-pos[ia][i] for i in range(3)];ac=[pos[ic][i]-pos[ia][i] for i in range(3)]
                        cross=(ab[1]*ac[2]-ab[2]*ac[1],ab[2]*ac[0]-ab[0]*ac[2],ab[0]*ac[1]-ab[1]*ac[0])
                        assert sum(n*n for n in cross)>1e-20,(family,v,'collapsed triangle')
                    points+=pos;triangles+=len(indices)//3
                    material=document['materials'][primitive['material']]
                    assert material['pbrMetallicRoughness'].get('baseColorTexture'),(family,v,material['name'])
                    if any(material.get('emissiveFactor',[])):glows.append(material)
            assert len(points)<12000 and triangles<10000,(family,v,len(points),triangles)
            maximum=max(maximum,len(points));shapes.append(hashlib.sha256(b''.join(struct.pack('<3f',*p) for p in points)).digest())
            bounds[family,v]=[max(p[i] for p in points)-min(p[i] for p in points) for i in range(3)]
            assert bounds[family,v][2]>.02,(family,v,'no depth')
            assert not designs[v]['colors'] or glows,(family,v,'missing real mesh emission')
            binding=assets.item_binding({'static_items':{asset_id:base}},asset_id,0,appearance_index=v)
            assert binding['source']==(root/row['source']).resolve().as_uri()
            assert binding['appearance_name']==row['name']
            assert binding['weapon_fx']['authored']['magic']['colors']==designs[v]['colors']
            assert binding['wielding_reference']==designs[v]['wielding_reference']
        assert len(set(shapes))==36,family
    assert min(bounds['staff',i][1] for i in range(36))>1.8
    assert max(bounds['wand',i][1] for i in range(36))<1.1
    assert max(bounds['mace',i][1] for i in range(18))<min(bounds['mace',i][1] for i in range(18,36))
    print('CASTER_GEOMETRY=PASS: 144 textured meshes, unique constructions, proper lengths, emission; max vertices='+str(maximum))

def check_runtime():
    runtime=GameEngineRuntime()
    try:
        def equip(family,v,slot=''):
            key=identity(family,v)
            runtime._item_instances[key]=items.make_instance(runtime._item_catalog,key,'item.weapon_'+family)
            result=runtime.equip_item(key,slot)
            return key,result
        for family,designs in BANKS.items():
            for v,row in enumerate(designs):
                key=identity(family,v);item=items.make_instance(runtime._item_catalog,key,'item.weapon_'+family)
                view=items.instance_view(runtime._item_catalog,item)
                assert view['name']==row['name'] and view['wielding_reference']==row['wielding_reference']
                assert view['appearance_index']==v
                slots=view['equip_slots']
                assert slots==(['OFF_HAND'] if family=='offhand' else ['MAIN_HAND','OFF_HAND'] if family=='mace' and v<18 else ['MAIN_HAND'])
                assert GameEngineRuntime._compact_ui_item_row(view)['appearance_index']==v
                assert gear._base_category(item['gear']['base_type'])==('ARMOR' if family=='offhand' else 'WEAPON')
        focus,r=equip('offhand',1);assert not r.get('error')
        staff,r=equip('staff',3);assert not r.get('error')
        assert runtime._item_instances[focus]['location']=='INVENTORY'
        assert runtime.equip_item(focus,'MAIN_HAND')['error']=='ITEM_EQUIP_SLOT_INCOMPATIBLE'
        assert runtime.equip_item(focus,'OFF_HAND')['error']=='ITEM_EQUIP_TWO_HANDS_OCCUPIED'
        assert not runtime.unequip_item(staff).get('error')
        assert runtime.equip_item(staff,'OFF_HAND')['error']=='ITEM_EQUIP_SLOT_INCOMPATIBLE'
        mace,r=equip('mace',20);assert not r.get('error')
        assert runtime.equip_item(focus,'OFF_HAND')['error']=='ITEM_EQUIP_TWO_HANDS_OCCUPIED'
        one,r=equip('mace',5);assert not r.get('error')
        assert not runtime.equip_item(focus,'OFF_HAND').get('error')
        wand,r=equip('wand',18);assert not r.get('error')
        assert not runtime.enchant_gear(wand,'enchant.storm_edge').get('error')
        assert runtime.enchant_gear(focus,'enchant.storm_edge')['error']=='GEAR_ENCHANTMENT_SLOT_INVALID'
        # Real NPC damage at range, with a themed bolt and owned weapon enchant.
        index=next(i for i,key in enumerate(runtime._npc_ids) if key)
        target=runtime._npc_ids[index];runtime._npc_indices=[index];runtime._alive[index]=True
        runtime._x[index]=runtime._x[0];runtime._z[index]=runtime._z[0]+20
        runtime._npc_line_of_sight_locked=lambda _:True
        response=runtime.attack(target);cast=response['combat_result']
        assert cast['ok'] and cast['damage']>0,cast
        assert cast['cast']['kind']=='WAND' and cast['cast']['slot']=='MAIN_HAND'
        assert cast['cast']['color']==wand_profile(18)['colors'][0]
        assert {e['id'] for e in cast['cast']['enchants']}=={'enchant.storm_edge'}
        assert any(e['kind']=='burn' for e in cast['enchant_effects']),cast
        assert runtime.attack(target)['combat_result']['status']=='COOLDOWN'
        runtime._sim_time+=2;runtime._npc_line_of_sight_locked=lambda _:False
        before={shot['id'] for shot in runtime._firearm_shots}
        assert runtime.attack(target)['error']=='COMBAT_LINE_OF_SIGHT_BLOCKED'
        assert {shot['id'] for shot in runtime._firearm_shots}<=before
        runtime._npc_line_of_sight_locked=lambda _:True;runtime._z[index]=runtime._z[0]+100
        assert runtime.attack(target)['error']=='COMBAT_TARGET_OUT_OF_RANGE'
        assert {shot['id'] for shot in runtime._firearm_shots}<=before
        # Craft new families through the actual item/gear pipeline.
        runtime._inventory.update({'material.wood':8,'material.iron_ingot':4,'material.fiber':4})
        runtime._reconcile_item_instances_locked()
        for family in BANKS:
            crafted=runtime.craft_gear('recipe.weapon_'+family,'station.workbench')
            assert not crafted.get('error'),(family,crafted.get('error'))
        runtime.save_state();runtime.reset();assert not runtime.load_state().get('error')
        equipped={row['equipped_slot']:row for row in runtime._player_equipped_instances_locked()}
        assert equipped['MAIN_HAND']['instance_id']==wand and equipped['OFF_HAND']['instance_id']==focus
        print('CASTER_RUNTIME=PASS: all hand rules, 2H exclusivity, crafting, caster enchants, ranged themed wand hits and persistence')
    finally:runtime.shutdown()

def check_fx():
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtQml import QJSEngine
    app=QCoreApplication.instance() or QCoreApplication([]);engine=QJSEngine()
    assert not engine.evaluate((ROOT/'qml/components/engine/WorldFx.js').read_text().replace('.pragma library','')).isError()
    for family,designs in BANKS.items():
        for v,row in enumerate(designs):
            magic=equipment_visual(family,v)['weapon_fx']['authored']['magic']
            magic=dict(magic,point=dict(x=11,y=3,z=-4))
            engine.evaluate('var sockets='+json.dumps(dict(MAIN_HAND=dict(magic=magic))))
            particles=json.loads(engine.evaluate('var result=[];emitMagicCores(result,sockets,7);JSON.stringify(result)').toString())
            assert bool(particles)==bool(row['colors']),(family,v)
            assert len(particles)<=5
            assert all(p['color'] in row['colors'] for p in particles)
            assert all(abs(p['x']-11)<.4 and abs(p['y']-3)<.4 and abs(p['z']+4)<.4 for p in particles)
            assert all(math.isfinite(float(p[k])) for p in particles for k in ('x','y','z','size','opacity'))
    # Fractional simulation time in a wand identity must not produce NaNs.
    shot=dict(kind='WAND',id='test:cast:1:20.4',time_s=20.4,slot='MAIN_HAND',start=[0,0,0],target=[0,2,12],
        construction='wand',flight_s=.5,offsets=[[0,0]],color='#ff7038',enchant_colors=['#ff7038','#ffd36b'],enchants=[],silent=True,shape='cell',impact=True,impact_size=.23)
    engine.evaluate('var shot='+json.dumps(shot))
    for age in (.04,.25,.55):
        value=engine.evaluate('var result=[];emitGunfire(result,[shot],'+str(20.4+age)+',sockets);JSON.stringify(result)')
        assert not value.isError(),value.toString()
        particles=json.loads(value.toString());assert particles
        if age==.04:
            trail=next(p for p in particles if p['kind']=='LASER')
            assert (trail['x'],trail['y'],trail['z'])==(11,3,-4),trail
        assert all(math.isfinite(float(p[k])) for p in particles for k in ('x','y','z','size','opacity'))
    assert engine.evaluate('var result=[];emitGunfire(result,[shot],22,sockets);result.length').toInt()==0
    print('CASTER_FX=PASS: all magic themes, attached finite particles, plain items quiet, wand cast lifetime')

if __name__=='__main__':check_meshes();check_runtime();check_fx()
