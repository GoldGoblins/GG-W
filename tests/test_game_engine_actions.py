"""Authoritative action slots, GgEngine click/TAB rules and actual inventory effects."""
import copy,json,os,sys
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import game_engine_actions as actions,game_engine_items as items
from backend.game_engine_host import GameEngineRuntime,FIXED_DT
from test_game_engine_nature import near

def main():
    assert actions.click_gesture(199,90,90)
    assert actions.click_gesture(799,2.24,1.99)
    assert not actions.click_gesture(800,0,0)
    assert not actions.click_gesture(250,2.25,0)
    bar=actions.ActionBars()
    rows=[{'id':'off','on_screen':False,'distance_m':1},
          {'id':'centre','on_screen':True,'distance_m':20},
          {'id':'attacker','on_screen':True,'distance_m':30,'combat_with_me':True},
          {'id':'critter','on_screen':True,'distance_m':1,'no_tab':True},
          {'id':'friend','on_screen':True,'distance_m':1,'attackable':False}]
    assert bar.cycle(rows,'',0)=='attacker'
    assert bar.cycle(rows,'attacker',.2)=='centre'
    assert bar.cycle(rows,'centre',.3,True)=='attacker'
    r=GameEngineRuntime()
    try:
        r.snapshot()
        inventory=copy.deepcopy(r._item_instances)
        assert not r.action_bar_edit(json.dumps({'index':15,'kind':'ITEM','ref':'item.nature.tool_shears'})).get('error')
        assert r._item_instances==inventory
        assert r.action_bar_edit(json.dumps({'index':15,'kind':'ABILITY','ref':'nonexistent'}))['error']=='ACTION_REFERENCE_INVALID'
        assert r._actions.slots[15]['kind']=='ITEM'
        r.action_bar_edit(json.dumps({'verb':'LOCK','locked':True}))
        assert r.action_bar_edit(json.dumps({'verb':'MOVE','source':15,'index':16}))['error']=='ACTION_BAR_LOCKED'
        r.action_bar_edit(json.dumps({'verb':'LOCK','locked':False}))
        r.action_bar_edit(json.dumps({'verb':'MOVE','source':15,'index':16}))
        assert r._actions.slots[16]['ref']=='item.nature.tool_shears'
        r.save_state();r._actions.slots[16]={};r.load_state()
        assert r._actions.slots[16]['ref']=='item.nature.tool_shears'
        identity=near(r,'sheep')
        before=copy.deepcopy(r._nature.states)
        assert not r.world_select(identity).get('error')
        assert r._nature.states==before,'Selection must never deal damage'
        assert r.world_hover(identity)['cursor']=='SHEAR'
        assert not r.action_use(16).get('error')
        assert r._nature.states[identity]['cooldowns']['SHEAR']>r._sim_time
        assert 'error' in r.action_use(16)
        r.reset();identity=near(r,'goat');r.world_select(identity)
        assert not r.action_use_item('item.nature.tool_bucket').get('error')
        assert not r._nature.states[identity].get('dead',False)
        # A shortcut consumes precisely one real bag item and cannot bypass its cooldown.
        r.reset()
        food_definition=next(k for k,v in r._item_catalog['items'].items() if 'RECOVERY' in v.get('tags',[]))
        food=items.make_instance(r._item_catalog,'test-food',food_definition,quantity=3)
        r._item_instances['test-food']=food;r._inventory=items.inventory_counts(r._item_instances.values())
        definition=food['definition_id'];amount=r._inventory[definition]
        actor=r._combat_state['actors']['player'];actor['health']-=30
        assert not r.action_use_item(definition).get('error')
        assert r._inventory.get(definition,0)==amount-1
        assert r.action_use_item(definition)['error'] in {'ITEM_ON_COOLDOWN','ITEM_NOT_IN_INVENTORY'}
        # Ground loot and containers are picks with stable identities too.
        ground=next(v for v in r._item_instances.values() if v['location']=='GROUND')
        position=ground['position'];r._x[0]=position['x'];r._z[0]=position['z'];r._y[0]=position['y']+.65
        assert r.world_hover(ground['instance_id'])['cursor'] in {'LOOT','OPEN'}
        assert any(v.get('entity_id')=='item-'+ground['instance_id'] for v in r._world_interaction_rows_locked())
        # Friendly villagers cannot become auto-attack targets; critters can be clicked.
        r.reset();npc=r._npc_ids[r._npc_indices[0]];r.world_select(npc)
        assert r.action_command('ATTACK')['error']=='COMBAT_TARGET_REQUIRED'
        identity=near(r,'rabbit');r.world_select(identity);r.action_command('ATTACK')
        r._running=True;r._tick_locked(FIXED_DT);r._tick_locked(FIXED_DT);r._running=False
        assert r._nature.states[identity]['dead']
        assert not r._actions.auto_attack
        r.reset();identity=near(r,'boar');r.world_select(identity);r.action_command('ATTACK')
        r._combat_state['actors']['player']['alive']=False
        r._tick_auto_attack_locked();assert not r._actions.auto_attack
        assert not r._nature.states.get(identity,{}).get('health')
        # Dead players cannot spend energy, move or start an ability cooldown,
        # whether using the action bar or calling the ability API directly.
        r.reset()
        ability_slot=next(i for i,entry in enumerate(r._actions.slots) if entry.get('kind')=='ABILITY')
        ability_id=r._actions.slots[ability_slot]['ref']
        r._combat_state['actors']['player']['alive']=False
        before=(r._resource,r._vx[0],r._vy[0],r._vz[0],dict(r._ability_cooldowns))
        assert r.action_use(ability_slot)['error']=='COMBAT_PLAYER_DEFEATED'
        assert r.activate_ability(ability_id)['error']=='COMBAT_PLAYER_DEFEATED'
        assert before==(r._resource,r._vx[0],r._vy[0],r._vz[0],dict(r._ability_cooldowns))
        ability_state=r._action_view_locked()['slots'][ability_slot]
        assert not ability_state['usable'] and ability_state['reason']=='Defeated'
        # Invalid camera values cannot poison TAB state or produce NaN snapshots.
        assert r.world_target_cycle('{"x":NaN}')['error']=='TARGET_CAMERA_INVALID'
        print(json.dumps({'status':'PASS','checks':'click travel, screen-priority TAB/reverse, no critter TAB, typed slots, bag ownership, locks/swap/save, shear/milk, real consumable cooldown, ground picks, friendly gate, automatic combat/death, defeated ability gate'}))
    finally:r.shutdown()

if __name__=='__main__':main()
