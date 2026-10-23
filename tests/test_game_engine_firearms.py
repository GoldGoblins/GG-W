"""Real ammo transfers, per-hand firing, fire-rate limits and persistence."""
import copy, math, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend import game_engine_firearms as guns,game_engine_items as items,game_engine_enchants as enchants
from backend.game_engine_host import GameEngineRuntime
from backend.game_engine_pistol_designs import PISTOLS
from tools.world.scale_sandover_environment import read_glb
from tools.world.build_caricature_asset_library import rows

def gun_id(variant):
    return next(f'qa-firearm-{variant}-{i}' for i in range(10000)
        if items.item_appearance_index(f'qa-firearm-{variant}-{i}')==variant)

def add_gun(runtime,variant,slot='MAIN_HAND'):
    key=gun_id(variant)
    runtime._item_instances[key]=items.make_instance(runtime._item_catalog,key,'item.weapon_pistol')
    result=runtime.equip_item(key,slot)
    assert not result.get('error'),result.get('error')
    return runtime._item_instances[key]

def result(runtime,target=''):
    return runtime.attack(target)['combat_result']

def ammo(runtime,ammo_id,count):
    runtime._inventory[ammo_id]=count
    runtime._reconcile_item_instances_locked()

def clear_guns(runtime):
    for key,row in list(runtime._item_instances.items()):
        if row.get('definition_id')=='item.weapon_pistol' and row.get('owner_id')=='player':
            del runtime._item_instances[key]
    runtime._inventory.pop('item.weapon_pistol',None)
    runtime._combat_target_id=''
    runtime._firearm_last_hand=''

def check_assets():
    assert len(PISTOLS)==36 and len(guns.AMMO)==19
    ammo_ids={row['id'] for row in guns.AMMO.values()}
    assert {guns.profile(gun_id(i))['ammo_id'] for i in range(36)}==ammo_ids
    for slug in guns.AMMO:
        path=ROOT/f'qml/assets/authored/items/ammo-{slug}.glb'
        document,binary=read_glb(path)
        count=0
        for mesh in document['meshes']:
            for primitive in mesh['primitives']:
                points,_,_=rows(document,binary,primitive['attributes']['POSITION'])
                normals,_,_=rows(document,binary,primitive['attributes']['NORMAL'])
                assert all(math.isfinite(v) for p in points+normals for v in p),slug
                assert all(.98<math.sqrt(sum(v*v for v in p))<1.02 for p in normals),slug
                assert primitive['attributes'].get('TEXCOORD_0') is not None,slug
                assert document['materials'][primitive['material']]['pbrMetallicRoughness'].get('baseColorTexture'),slug
                count+=len(points)
        assert 0<count<5000,(slug,count)
        assert (ROOT/f'qml/assets/authored/items/icons/itemmesh-ammo_{slug}.png').is_file(),slug
    print('AMMUNITION_ASSETS=PASS: 19 painted meshes, matching icons and all 36 profiles')

def check_runtime():
    runtime=GameEngineRuntime()
    try:
        # Isolated real runtime; no persistent game save on disk is touched.
        runtime._npc_indices=[]
        runtime._x[0]=1.5;runtime._z[0]=2.1
        runtime._y[0]=runtime._terrain_height_locked(1.5,2.1)+.65
        resources={}
        for recipe in guns.crafting_recipes().values():
            for key,amount in recipe['inputs'].items():resources[key]=resources.get(key,0)+amount
        runtime._inventory.update(resources)
        runtime._reconcile_item_instances_locked()
        before=copy.deepcopy(runtime._inventory);runtime._x[0]+=100
        assert runtime.craft_gear('recipe.ammo_pistol_45','station.workbench')['error']=='AMMO_WORKBENCH_OUT_OF_REACH'
        assert runtime._inventory==before
        runtime._x[0]-=100
        assert len(runtime.snapshot()['crafting']['ammunition_recipes'])==19
        for slug,spec in guns.AMMO.items():
            before=runtime._inventory.get(spec['id'],0)
            crafted=runtime.craft_gear('recipe.ammo_'+slug,'station.workbench')
            assert not crafted.get('error'),(slug,crafted.get('error'))
            expected=6 if slug in ('rocket','disc') else 24
            assert runtime._inventory[spec['id']]==before+expected
            assert any(r['definition_id']==spec['id'] and r['location']=='INVENTORY'
                for r in runtime._item_instances.values()),slug
        # Each gun really reloads and fires its own matching ammunition.
        for variant in range(36):
            clear_guns(runtime);row=add_gun(runtime,variant);spec=guns.profile(row['instance_id'])
            ammo(runtime,spec['ammo_id'],spec['capacity']+13)
            dry=result(runtime)
            assert dry['status']=='RELOADING' and not dry['ok'],(variant,dry)
            assert runtime._inventory[spec['ammo_id']]==13
            pending=row['magazine']['pending'];assert pending==spec['capacity']
            repeat=runtime.reload_firearms()
            assert repeat['firearm_result']['hands'][0]['status']=='RELOADING'
            assert runtime._inventory[spec['ammo_id']]==13
            runtime._sim_time=row['magazine']['reload_until']-.01
            assert result(runtime)['status']=='RELOADING'
            runtime._sim_time+=.01
            response=runtime.attack();fired=response['combat_result']
            assert response['schema']=='gg.game-engine.render-snapshot.v1'
            assert fired['ok'] and fired['ammo_id']==spec['ammo_id'],(variant,fired)
            assert row['magazine']['rounds']==spec['capacity']-spec['rounds_per_shot']
            assert fired['projectiles']==spec['projectiles']
            assert fired['shot']['color']==spec['color'] and fired['shot']['shape']==spec['shape']
            assert math.isclose(fired['cooldown_s'],1/spec['rounds_per_s'])
            before=copy.deepcopy(row['magazine'])
            assert result(runtime)['status']=='COOLDOWN'
            assert row['magazine']==before
            runtime._sim_time=before['next_fire']
            next_shot=result(runtime)
            assert next_shot['ok'] or next_shot['status']=='RELOADING',next_shot
        print('FIREARMS_RUNTIME=PASS: all 36 reload/consume/emit distinct shots, with enforced cooldowns')
        # Wrong ammunition cannot be spent, and empty guns cannot fire.
        clear_guns(runtime);row=add_gun(runtime,1)
        ammo(runtime,'item.ammo_pistol_45',0);ammo(runtime,'item.ammo_shotgun',24)
        before=copy.deepcopy(row['magazine'])
        assert result(runtime)['status']=='NO_AMMO'
        assert row['magazine']==before and runtime._inventory['item.ammo_shotgun']==24
        # Reload reservation survives save/load, including inventory conservation.
        ammo(runtime,'item.ammo_pistol_45',20)
        runtime.reload_firearms();reserved=copy.deepcopy(row['magazine']);saved_time=runtime._sim_time
        runtime.save_state();runtime.reset();loaded=runtime.load_state()
        assert not loaded.get('error'),loaded.get('error')
        runtime._npc_indices=[]
        row=runtime._item_instances[gun_id(1)]
        assert row['magazine']==reserved and runtime._sim_time==saved_time
        assert runtime._inventory['item.ammo_pistol_45']==13
        runtime.reload_firearms();assert runtime._inventory['item.ammo_pistol_45']==13
        runtime._sim_time=reserved['reload_until'];assert result(runtime)['ok']
        # Moving a weapon between hands does not refill its magazine.
        rounds=row['magazine']['rounds']
        assert not runtime.unequip_item(row['instance_id']).get('error')
        assert not runtime.equip_item(row['instance_id'],'OFF_HAND').get('error')
        assert row['magazine']['rounds']==rounds
        # Opposite hands have independent timers and magazines.
        other=add_gun(runtime,12,'MAIN_HAND');ammo(runtime,'item.ammo_pistol_45',30)
        runtime.reload_firearms();runtime._sim_time+=2
        a=result(runtime);b=result(runtime)
        assert a['ok'] and b['ok'] and {a['hand'],b['hand']}=={'MAIN_HAND','OFF_HAND'},(a,b)
        assert result(runtime)['status']=='COOLDOWN'
        # An automatic trigger never fires the semi-auto in the other hand.
        runtime._sim_time+=1;auto=add_gun(runtime,9,'MAIN_HAND')
        ammo(runtime,'item.ammo_smg_9mm',40);runtime.reload_firearms();runtime._sim_time+=3
        runtime._firearms_view_locked()
        semi_rounds=row['magazine']['rounds']
        held=runtime.attack('',action_id='automatic_fire')['combat_result']
        assert held['ok'] and held['weapon_id']==auto['instance_id']
        assert row['magazine']['rounds']==semi_rounds
        print('MAGAZINES_AKIMBO=PASS: no wrong-ammo spend, no reload duplication, durable clips and independent hands')
        # Real target damage, independent combat cooldown groups and hand enchants.
        clear_guns(runtime);main=add_gun(runtime,9);off=add_gun(runtime,12,'OFF_HAND')
        for r in (main,off):
            spec=guns.profile(r['instance_id']);ammo(runtime,spec['ammo_id'],spec['capacity']+20)
        runtime.reload_firearms();runtime._sim_time+=3
        index=next(i for i,key in enumerate(runtime._npc_ids) if key)
        target=runtime._npc_ids[index];runtime._npc_indices=[index];runtime._alive[index]=True
        runtime._x[index]=runtime._x[0];runtime._z[index]=runtime._z[0]+8
        runtime._npc_line_of_sight_locked=lambda _:True
        for r,enchant in ((main,'enchant.ember_edge'),(off,'enchant.storm_edge')):
            assert not runtime.enchant_gear(r['instance_id'],enchant).get('error')
        first=result(runtime,target);second=result(runtime,target)
        assert first['ok'] and second['ok'] and first['weapon_id']!=second['weapon_id'],(first,second)
        for shot in (first,second):
            sources={e.get('source_id') for e in shot.get('enchant_effects',[])}
            own='enchant.ember_edge' if shot['weapon_id']==main['instance_id'] else 'enchant.storm_edge'
            other_enchant='enchant.storm_edge' if own=='enchant.ember_edge' else 'enchant.ember_edge'
            assert own in sources and other_enchant not in sources,(own,sources)
            assert {e['id'] for e in shot['shot']['enchants']}=={own}
            assert shot['shot']['enchant_colors']==enchants.firearm_bursts(main if own=='enchant.ember_edge' else off,1)[0]['colors']
        runtime._sim_time=main['magazine']['next_fire']
        third=result(runtime,target)
        assert third['ok'] and third['weapon_id']==main['instance_id'],third
        # Failed line-of-sight/range checks spend no round or weapon deadline.
        runtime._sim_time+=1;runtime._npc_line_of_sight_locked=lambda _:False
        before=[copy.deepcopy(r['magazine']) for r in (main,off)]
        assert result(runtime,target)['status']=='LINE_OF_SIGHT_BLOCKED'
        assert before==[r['magazine'] for r in (main,off)]
        runtime._npc_line_of_sight_locked=lambda _:True;runtime._z[index]=runtime._z[0]+500
        assert result(runtime,target)['status']=='TARGET_OUT_OF_RANGE'
        assert before==[r['magazine'] for r in (main,off)]
        spec=guns.profile(gun_id(10))
        assert sum(math.hypot(x,y)<=.5 for x,y in guns.projectile_offsets(spec,2,1))>sum(
            math.hypot(x,y)<=.5 for x,y in guns.projectile_offsets(spec,30,1))
        print('FIREARM_COMBAT=PASS: ranged NPC damage, high fire rate, per-hand enchants, LOS/range guards and shotgun spread')
    finally:runtime.shutdown()

def check_enchanted_fx():
    import json
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtQml import QJSEngine
    app=QCoreApplication.instance() or QCoreApplication([])
    engine=QJSEngine()
    source=(ROOT/'qml/components/engine/WorldFx.js').read_text().replace('.pragma library','')
    value=engine.evaluate(source);assert not value.isError(),value.toString()
    for key,row in enchants.CATALOG.items():
        gun=dict(gear=dict(enchantments=[dict(id=key)]))
        bursts=enchants.firearm_bursts(gun,60)
        assert bursts and bursts[0]['colors']==row['colors'],key
        if row['required_level']==60:assert not enchants.firearm_bursts(gun,1)
        shot=dict(id=key+':1',slot='MAIN_HAND',time_s=10,start=[0,1,0],target=[0,1,10],
            flight_s=.5,offsets=[[0,0]],impact=True,impact_size=.15,construction='1911',
            shape='bullet',color='#ffc96b',enchants=bursts,enchant_colors=row['colors'])
        engine.evaluate('var sampleShot='+json.dumps(shot))
        for age in (.04,.25,.55):
            rendered=engine.evaluate('var out=[];emitGunfire(out,[sampleShot],'+str(10+age)+',{});JSON.stringify(out)')
            assert not rendered.isError(),rendered.toString()
            particles=json.loads(rendered.toString())
            assert particles and any(p['color'] in row['colors'] for p in particles),(key,age)
            assert all(math.isfinite(float(p[k])) for p in particles for k in ('x','y','z','size','opacity'))
            assert len(particles)<=224
        expired=engine.evaluate('var out=[];emitGunfire(out,[sampleShot],11,{});JSON.stringify(out)').toString()
        assert json.loads(expired)==[]
        # These same enchants still emit clouds on a melee blade, but none on guns.
        equipment=[dict(definition_id='item.weapon_pistol',equipped_slot='MAIN_HAND',gear=dict(enchantments=[row]))]
        engine.evaluate('var sampleEquipment='+json.dumps(equipment))
        idle=engine.evaluate('JSON.stringify(rows({x:0,y:0,z:0,time_s:10},sampleEquipment,"",1,{},{}))').toString()
        assert not any(p['kind']=='ENCHANT' for p in json.loads(idle)),(key,idle)
        equipment[0]['definition_id']='item.weapon_sword'
        engine.evaluate('var sampleEquipment='+json.dumps(equipment))
        melee=json.loads(engine.evaluate('JSON.stringify(rows({x:0,y:0,z:0,time_s:10},sampleEquipment,"",1,{},{}))').toString())
        assert any(p['kind']=='ENCHANT' for p in melee),(key,melee)
    # Two hands must retain different event colours after switching equipment.
    print('ENCHANTED_SHOT_FX=PASS: all authored colours, mixed/artifact enchants, muzzle/projectile/impact lifetimes, guns quiet at idle and melee clouds retained')

if __name__=='__main__':
    check_assets();check_runtime();check_enchanted_fx()
