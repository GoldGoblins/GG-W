"""Authoritative scroll crafting, mixed tiers, combat statuses and visual parity."""
import copy,json,os,sys
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QJSEngine
from backend import game_engine_enchants as enchants, game_engine_combat as combat
from backend import game_engine_gear as gear, game_engine_items as items
from backend.game_engine_host import GameEngineRuntime
from backend.game_engine_geometry import build_item_geometry


def profile(key='', kind='PLAYER'):
    p=combat.profile({},kind=kind,actor_id='player' if kind=='PLAYER' else 'target')
    p.update(max_health=100,damage=10,armor=0,crit_chance=0)
    p['enchant_effects']=[dict(e,source_id=key) for e in enchants.definition(key).get('on_hit',[])]
    return p


def hit(state,key,time=0):
    return combat.resolve_attack(state,attacker_id='player',defender_id='target',
        attacker_profile=profile(key),defender_profile=profile(kind='NPC'),sim_time=time)


def prepare(runtime):
    with runtime._lock:
        runtime._x[0]=-3;runtime._z[0]=-1.5
        runtime._y[0]=runtime._terrain_height_locked(-3,-1.5)+.65
        runtime._inventory.update({'material.fiber':40,'material.runic_oil':40,'item.moon_shard':40})
        runtime._reconcile_item_instances_locked()


def craft(runtime,key):
    result=runtime.craft_gear('recipe.enchant_scroll.'+key,'station.enchanting_altar')
    assert not result.get('error'),result.get('error')
    return result['gear_craft_result']['created'][0]


def main():
    app=QGuiApplication.instance() or QGuiApplication([])
    js=QJSEngine();v=js.evaluate((ROOT/'qml/components/engine/WorldFx.js').read_text().replace('.pragma library',''))
    assert not v.isError(),v.toString()
    assert js.evaluate('JSON.stringify(ENCHANT_CHOICES)').toString()==json.dumps(enchants.visual_catalog(),separators=(',',':'))
    assert len(enchants.CATALOG)==21
    assert len(enchants.GEAR_CATALOG)==6
    assert {r['tier'] for r in enchants.CATALOG.values()}=={1,2,3}
    for key,row in enchants.CATALOG.items():
        if row['tier']==1:assert len(row['on_hit'])==1 and len(row['families'])==1
        if row['tier']==3:assert set(row['families'])=={'OFFENSIVE','DEFENSIVE','RECOVERY'} and row['required_level']==60
        s=combat.new_state();combat.ensure_actor(s,'player',profile(key))['health']=50
        result=hit(s,key);assert result['ok'] and result['enchant_effects']
        actor=s['actors']['target'];p=s['actors']['player']
        for e in row['on_hit']:
            kind=e['kind']
            if kind=='heal':assert p['health']>50
            elif kind=='lifesteal':assert p['health']>50
            elif kind=='slow':assert combat.movement_scale(actor,0)<1
            elif kind=='snare':assert combat.movement_scale(actor,0)==0
            elif kind=='weaken':
                retaliate=combat.resolve_attack(s,attacker_id='target',defender_id='player',attacker_profile=profile(kind='NPC'),defender_profile=profile(key),sim_time=.01)
                assert retaliate['damage']<10
            elif kind in ('fire','acid','arcane','shock','frost'):assert result['damage']>10
            elif kind in ('burn','poison'):assert combat.tick_statuses(s,1)
            elif kind=='regen':
                before=p['health'];combat.tick_statuses(s,1);assert p['health']>before
            elif kind=='ward':assert combat.status_strength(p,'ward',0)>0
        # Every real weapon palette emits the exact authored colors, at a fixed budget.
        item={'equipped_slot':'MAIN_HAND','gear':{'enchantments':[dict(row)]}}
        fx=js.evaluate('rows({x:0,y:0,z:0},'+json.dumps([item])+',"",1,{})').toVariant()
        assert len(fx)==14 and {r['color'] for r in fx}==set(row['colors'])
    s=combat.new_state();key='enchant.chromatic.red';hit(s,key)
    before=copy.deepcopy(s);assert hit(s,key,.1)['status']=='COOLDOWN';assert s==before
    hit(s,key,.9);assert len(s['actors']['target']['statuses'])==1
    assert combat.tick_statuses(s,1)[0]['damage']==2 # Refresh doesn't delay the tick.
    normalized=combat.normalize_state(s);assert normalized['actors']['target']['statuses']==s['actors']['target']['statuses']
    before=copy.deepcopy(s);combat.tick_statuses(s,1);assert s==before
    s=combat.new_state();hit(s,'enchant.chromatic.white')
    retaliate=combat.resolve_attack(s,attacker_id='target',defender_id='player',attacker_profile=profile(kind='NPC'),defender_profile=profile(),sim_time=.01)
    assert retaliate['damage']==5 and retaliate['absorbed']==5
    s=combat.new_state();hit(s,'enchant.chromatic.indigo');assert combat.movement_scale(s['actors']['target'],1.21)==1
    s=combat.new_state();hit(s,'enchant.custom.red+blue');s['actors']['target']['health']=1
    events=combat.tick_statuses(s,1);assert len(events)==1 and events[0]['defeated']
    assert not combat.tick_statuses(s,2)
    respawn=combat.respawn_actor(s,'target',profile(kind='NPC'),21);assert respawn['statuses']==[]
    # Mixed healing and damage use the same timeline at different tick cadences.
    mixed=combat.new_state();actor=combat.ensure_actor(mixed,'target',profile(kind='NPC'));actor['health']=5
    combat.apply_status(actor,dict(kind='burn',amount=3,duration_s=4,source_id='fire'),'player',0)
    combat.apply_status(actor,dict(kind='regen',amount=2,duration_s=4,source_id='regen'),'target',0)
    catchup=copy.deepcopy(mixed)
    for now in (1,2):combat.tick_statuses(mixed,now)
    combat.tick_statuses(catchup,2)
    assert mixed['actors']==catchup['actors'] and mixed['actors']['target']['alive']
    assert not enchants.definition('enchant.custom.red+red')
    assert not enchants.definition('enchant.custom.red+green+yellow')
    assert not enchants.definition('enchant.custom.arbitrary')
    assert enchants.definition('enchant.custom.red+blue')['id']=='enchant.custom.blue+red'
    assert enchants.definition('enchant.custom.red+white+pink')['tier']==3
    assert build_item_geometry('itemmesh.enchant_scroll','SCROLL').vertexData()
    runtime=GameEngineRuntime()
    try:
        prepare(runtime);key='enchant.custom.blue+red'
        before=copy.deepcopy(runtime._inventory)
        assert runtime.enchant_gear('starter-iron-saber',key)['error']=='ENCHANT_SCROLL_REQUIRED'
        assert runtime._inventory==before
        runtime._x[0]=100
        assert runtime.craft_gear('recipe.enchant_scroll.'+key,'station.enchanting_altar')['error']=='ENCHANT_TABLE_OUT_OF_REACH'
        assert runtime._inventory==before;runtime._x[0]=-3
        scroll=craft(runtime,key)
        assert runtime._inventory['material.fiber']==before['material.fiber']-2
        assert items.normalize_instance(runtime._item_catalog,runtime._item_instances[scroll['instance_id']])['scroll_enchant_id']==key
        before=copy.deepcopy(runtime._inventory)
        result=runtime.enchant_gear('starter-drift-cloak',key)
        assert result.get('error') in ('GEAR_ENCHANTMENT_SLOT_INVALID','GEAR_ENCHANT_TARGET_REQUIRED')
        assert runtime._inventory==before and scroll['instance_id'] in runtime._item_instances
        result=runtime.enchant_gear('starter-iron-saber',key);assert not result.get('error'),result.get('error')
        assert scroll['instance_id'] not in runtime._item_instances
        assert {e['kind'] for e in runtime._player_combat_profile_locked()['enchant_effects']}=={'burn','slow'}
        runtime.unequip_item('starter-iron-saber');assert not runtime._player_combat_profile_locked()['enchant_effects']
        runtime.equip_item('starter-iron-saber')
        # Real DoT defeat grants XP/loot once through the host, at the target position.
        identity='npc-critter-01';index=runtime._npc_index_for_id_locked(identity);assert index is not None
        with runtime._lock:
            runtime._x[0]=runtime._x[index]+1;runtime._z[0]=runtime._z[index]
            runtime._y[0]=runtime._terrain_height_locked(runtime._x[0],runtime._z[0])+.65
            runtime._ensure_combat_actors_locked()
            runtime._combat_state['actors'][identity]['health']=45
        result=runtime.attack(identity);assert result['combat_result']['ok'] and not result['combat_result']['defeated']
        with runtime._lock:
            runtime._combat_state['actors'][identity]['health']=1
            runtime._sim_time=1.1;runtime._tick=3
            xp_before=runtime._progression['xp'];runtime._tick_combat_locked()
            assert not runtime._combat_state['actors'][identity]['alive']
            assert runtime._progression['xp']>xp_before
            xp_after=runtime._progression['xp'];drops=len(runtime._item_instances)
            runtime._sim_time=2.1;runtime._tick=6;runtime._tick_combat_locked()
            assert runtime._progression['xp']==xp_after and len(runtime._item_instances)==drops
        prepare(runtime)
        before=copy.deepcopy(runtime._inventory)
        assert runtime.craft_gear('recipe.enchant_scroll.enchant.custom.red+white+pink','station.enchanting_altar')['error']=='ENCHANT_LEVEL_REQUIRED'
        assert runtime._inventory==before
        runtime._progression['level']=60;artifact=craft(runtime,'enchant.custom.red+white+pink')
        assert artifact['rarity']=='ARTIFACT'
        second=craft(runtime,key);before=copy.deepcopy(runtime._inventory)
        assert runtime.enchant_gear('starter-iron-saber',key)['error']=='GEAR_ENCHANTMENT_DUPLICATE'
        assert runtime._inventory==before and second['instance_id'] in runtime._item_instances
        # Gear boost is a separate scroll and modifies authoritative derived health.
        target=next(row for row in runtime._player_equipped_instances_locked() if row['gear']['base_type'] not in ('SWORD','BOW','DAGGER'))
        health_before=runtime._player_combat_profile_locked()['max_health']
        craft(runtime,'enchant.gear.vitality')
        assert not runtime.enchant_gear(target['instance_id'],'enchant.gear.vitality').get('error')
        assert runtime._player_combat_profile_locked()['max_health']==health_before+12
        # A full save/load uses an isolated memory store, never the user's save file.
        class Store:
            revision=1
            def save(self,key,payload):self.payload=copy.deepcopy(payload);return {'ok':True,'revision':1}
            def load(self,key):return copy.deepcopy(self.payload)
        original=runtime._state_store;runtime._state_store=Store()
        runtime.save_state();runtime.load_state();runtime._state_store=original
        assert runtime._item_instances[artifact['instance_id']]['scroll_enchant_id']=='enchant.custom.pink+red+white'
        assert {e['kind'] for e in runtime._player_combat_profile_locked()['enchant_effects']}=={'burn','slow'}
        assert all(row.get('scroll_enchant_id') for row in runtime.ui_snapshot()['items']['inventory'] if row['definition_id']=='item.enchant_scroll')
        print(json.dumps(dict(status='PASS',weapon_presets=21,single_colors=12,mixed_presets=6,artifact_presets=3,
            gear_stat_scrolls=6,custom_recipes=True,real_combat_effects=True,scrolls_consumed_on_success_only=True,
            dot_rewards_once=True,save_load=True,visual_palette_parity=True)))
    finally:runtime.shutdown()

if __name__=='__main__':main()
