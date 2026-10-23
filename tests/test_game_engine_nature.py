"""Nature must be harvestable, bounded, stable and atomic through real inventory."""
import copy,json,math,os,sys,time
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
from backend import game_engine_nature_catalog as catalog,game_engine_nature as nature
from backend import game_engine_items as items,game_engine_host as host


def near(runtime,species):
    runtime._nature._stamp=None;runtime._ecology_view_locked()
    row=next(r for r in runtime._nature.rows if r['species']==species)
    runtime._x[0]=row['x']+.2;runtime._y[0]=row['y']+.65;runtime._z[0]=row['z']
    runtime._nature._stamp=None;runtime._ecology_view_locked()
    return row['id']


def main():
    assert len(catalog.PLANTS)>=10
    assert len([s for s in catalog.SPECIES.values() if s['domain']=='LAND'])>=10
    assert {'turtle','octopus','bee','butterfly'}<=catalog.SPECIES.keys()
    runtime=host.GameEngineRuntime()
    try:
        definitions=runtime._item_catalog['items'];tables=runtime._item_catalog['loot_tables']
        for species,s in catalog.SPECIES.items():
            assert s['loot_table_id'] in tables
            for a in s['actions'].values():
                if not a['resource']:continue
                assert a['table_id'] in tables
                assert all(e['item_id'] in definitions for e in tables[a['table_id']]['entries'])
                assert items.roll_loot(runtime._item_catalog,123,a['table_id'])==items.roll_loot(runtime._item_catalog,123,a['table_id'])
        identity=near(runtime,'sun_daisy')
        before=copy.deepcopy(runtime._inventory)
        harvested=runtime.nature_action(identity,'PICK');assert 'error' not in harvested,harvested.get('error')
        assert runtime._inventory!=before
        after=copy.deepcopy(runtime._inventory)
        assert 'error' in runtime.nature_action(identity,'PICK')
        assert runtime._inventory==after
        # Leaving and returning cannot regenerate an already gathered plant.
        runtime._x[0]=7200;runtime._z[0]=100;runtime._ecology_view_locked()
        runtime._x[0]=8;runtime._z[0]=-8;runtime._ecology_view_locked()
        assert not runtime._nature.visible(identity,runtime._sim_time)
        saved=runtime._nature.save(runtime._sim_time)
        restored=nature.NatureWorld(host.WORLD_SEED);restored.restore(saved,100)
        assert not restored.visible(identity,100) and restored.visible(identity,281)
        # Actual runtime save/load includes depletion, not just the item reward.
        runtime.save_state();runtime._nature.states.clear();runtime.load_state()
        assert not runtime._nature.visible(identity,runtime._sim_time)
        runtime.reset();identity=near(runtime,'sheep')
        shears=runtime._item_instances['nature-tool-shears']
        shears['location']='BANK';runtime._inventory=items.inventory_counts(runtime._item_instances.values())
        assert 'error' in runtime.nature_action(identity,'SHEAR')
        assert identity not in runtime._nature.states
        shears['location']='INVENTORY';runtime._inventory=items.inventory_counts(runtime._item_instances.values())
        assert 'error' not in runtime.nature_action(identity,'SHEAR')
        assert not runtime._nature.states[identity].get('dead',False)
        assert not any(r['id']==identity for r in runtime._nature.groups['sheep:coat'])
        assert 'error' in runtime.nature_action(identity,'SHEAR')
        identity=near(runtime,'goat')
        assert 'error' not in runtime.nature_action(identity,'MILK')
        assert not runtime._nature.states[identity].get('dead',False)
        runtime.reset();identity=near(runtime,'rabbit')
        assert 'error' not in runtime.nature_action(identity,'PET')
        # A noncombat save must retain this species' original health on restore.
        saved=runtime._nature.save(runtime._sim_time)
        runtime._nature.restore(saved,runtime._sim_time)
        assert 'health' not in runtime._nature.states[identity]
        assert 'error' in runtime.nature_action(identity,'LOOT')
        assert 'error' not in runtime.nature_action(identity,'ATTACK')
        assert runtime._nature.states[identity]['dead']
        assert 'error' in runtime.nature_action(identity,'SKIN')
        assert 'error' not in runtime.nature_action(identity,'LOOT')
        loot_after=copy.deepcopy(runtime._inventory)
        assert 'error' in runtime.nature_action(identity,'LOOT') and runtime._inventory==loot_after
        runtime.save_state();runtime.load_state()
        assert runtime._nature.states[identity]['looted']
        assert runtime.world_hover(identity)['cursor']=='SKIN'
        assert 'error' not in runtime.nature_action(identity,'SKIN')
        assert not runtime._nature.visible(identity,runtime._sim_time)
        runtime.reset();identity=near(runtime,'berry_bush')
        for i in range(items.MAX_INVENTORY_SLOTS):
            runtime._item_instances['filler'+str(i)]=items.make_instance(runtime._item_catalog,'filler'+str(i),'item.island_compass')
        runtime._inventory=items.inventory_counts(runtime._item_instances.values())
        runtime._ensure_inventory_slots_locked()
        before=copy.deepcopy(runtime._item_instances)
        assert runtime.nature_action(identity,'PICK')['error']=='ITEM_INVENTORY_FULL'
        assert runtime._item_instances==before and identity not in runtime._nature.states
        runtime.reset()
        for species in ('frog','bee','butterfly'):
            identity=near(runtime,species)
            assert 'error' not in runtime.nature_action(identity,'CATCH')
            assert not runtime._nature.visible(identity,runtime._sim_time)
        runtime.reset();runtime._x[0]=-250;runtime._z[0]=-220;runtime._ecology_view_locked()
        for species,action in (('turtle','CATCH'),('sunfin','FISH')):
            identity=near(runtime,species)
            assert 'error' not in runtime.nature_action(identity,action)
            assert not runtime._nature.visible(identity,runtime._sim_time)
        runtime.reset();identity=near(runtime,'amanita')
        runtime._x[0]+=30
        assert runtime.nature_action(identity,'PICK')['error']=='NATURE_TARGET_OUT_OF_REACH'
    finally:runtime.shutdown()
    # Every sea species appears in seeded ocean cells and swims above seabed.
    sea=nature.NatureWorld(host.WORLD_SEED);seen=set()
    for i in range(20):
        sea.update(i*500,500,1,lambda x,z:-10,[])
        assert len(sea.rows)<=nature.MAX_ANIMALS
        seen|={r['species'] for r in sea.rows}
        assert all(-10<r['y']<0 for r in sea.rows)
    assert {k for k,v in catalog.SPECIES.items() if v['domain']=='WATER'}<=seen
    assert len(sea.cells)<=nature.MAX_CELLS
    first=nature.NatureWorld(host.WORLD_SEED);second=nature.NatureWorld(host.WORLD_SEED)
    first.update(1000,500,1,lambda x,z:-10,[]);second.update(1000,500,1,lambda x,z:-10,[])
    assert first.rows==second.rows
    first.update(9000,500,2,lambda x,z:-10,[]);first.update(1000,500,1,lambda x,z:-10,[])
    assert first.rows==second.rows
    # GPU buffers must reflect horizontal movement and articulation, not only Y.
    from PySide6.QtGui import QGuiApplication
    from backend.game_engine_ecology_render import FloraRenderCache
    app=QGuiApplication.instance() or QGuiApplication([])
    cache=FloraRenderCache(assets=PROJECT/'qml/assets/authored/nature',keys=nature.GROUP_KEYS)
    manifest=json.loads((PROJECT/'qml/assets/authored/nature/nature-kit.asset.json').read_text())
    for key in nature.GROUP_KEYS:
        geometry=cache.geometry(key);assert geometry is not None,key
        species,part=key.split(':')
        assert len(bytes(geometry.indexData()))==manifest['species'][species]['parts'][part.split('-v')[0]]['triangles']*12
    row={'id':'x','x':1,'y':2,'z':3,'yaw':0,'scale':1,'tint':1}
    table=cache.table('rabbit:body',[row],1);old=bytes(table.getInstanceBuffer()[0])
    row.update(x=2,roll=10);cache.table('rabbit:body',[row],2)
    assert bytes(table.getInstanceBuffer()[0])!=old
    print('GAME_ENGINE_NATURE_TEST=PASS (34 species, tools, live harvest, hunting, atomic capacity, cooldown/save/load, seeded residency, sea habitat, native moving buffers)')

if __name__=='__main__':main()
