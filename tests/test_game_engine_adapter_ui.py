"""Behavioural compatibility through the actual native GgEngine worker."""
from pathlib import Path
import hashlib,json,os,sys,tempfile,time,unittest
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtGui import QGuiApplication,QImage,QPainter
from PySide6.QtQuick import QQuickItem
from backend.game_engine_adapter_ui import GgEngineUI
APP=QGuiApplication.instance() or QGuiApplication([])

class GgEngineTests(unittest.TestCase):
    def setUp(self):self.ui=GgEngineUI()
    def tearDown(self):self.ui.close()
    def test_complete_original_widget_surface(self):
        census=self.ui.census();classes={c for c,m in census['widget_methods']}
        self.assertEqual(len(classes),24);self.assertEqual(len(census['widget_methods']),2295)
        self.assertIn(['UnitHealthMax','function'],census['globals'])
        self.assertIn(('EditBox','SetText'),[tuple(x) for x in census['widget_methods']])
        self.assertEqual(self.ui.evaluate('return type(pcall),type(getfenv),type(io),type(os),type(require)'),['function','function','nil','nil','nil'])
    def test_framexml_template_relative_anchors_and_resize(self):
        self.ui.xml('''<Ui><Button name="Base" virtual="true"><Size><AbsDimension x="80" y="24"/></Size></Button><Button name="Child" inherits="Base" parent="UIParent"><Anchors><Anchor point="BOTTOMRIGHT"><Offset><AbsDimension x="-10" y="12"/></Offset></Anchor></Anchors></Button></Ui>''')
        row=next(r for r in self.ui.frames() if r.get('owner')=='Child')
        self.assertEqual((row['x'],row['y'],row['width'],row['height']),(1190,684,80,24))
        self.ui.resize(640,480);row=next(r for r in self.ui.frames() if r.get('owner')=='Child')
        self.assertEqual((row['x'],row['y']),(550,444))
    def test_event_error_isolation_and_legacy_global_restore(self):
        self.ui.execute("a=CreateFrame('Frame','Bad') b=CreateFrame('Frame','Good') a:RegisterEvent('TEST') b:RegisterEvent('TEST') a:SetScript('OnEvent',function() error('broken handler') end) b:SetScript('OnEvent',function() seen=arg1 end) this='outer' event='outer' arg1='outer'")
        self.ui.event('TEST','payload');self.ui.frames()
        self.assertEqual(self.ui.evaluate('return seen,this,event,arg1'),['payload','outer','outer','outer'])
        self.assertTrue(any('broken handler' in e for e in self.ui.errors))
    def test_live_player_values_and_tick(self):
        self.ui.publish({'x':7,'z':9,'biome':'FOREST'},True,82,43,max_health=120,max_resource=75,level=6,name='Glim')
        self.ui.tick(.125)
        self.assertEqual(self.ui.evaluate("return UnitName('player'),UnitHealth('player'),UnitHealthMax('player'),UnitMana('player'),UnitManaMax('player'),UnitLevel('player'),GetTime()"),['Glim',82,120,43,75,6,.125])
    def test_mouse_editbox_and_measured_text(self):
        self.ui.execute("f=CreateFrame('Frame','F',UIParent) f:SetWidth(200) f:SetHeight(80) f:SetPoint('TOPLEFT',UIParent,'TOPLEFT',0,0) t=f:CreateFontString('T') t:SetFont('Sans Serif',12) t:SetText('Measured text') e=CreateFrame('EditBox','E',f) e:SetWidth(160) e:SetHeight(20) e:SetPoint('TOPLEFT',f,'TOPLEFT',4,-40) e:SetAutoFocus(false) e:SetFont('Sans Serif',12) e:SetText('')")
        self.assertGreater(self.ui.evaluate('return T:GetStringWidth()')[0],40)
        self.ui.request('exec',source='E:SetFocus()');self.ui.request('text',text='hello');self.ui.request('key',key='BACKSPACE')
        self.assertEqual(self.ui.evaluate('return E:GetText()'),['hell'])
        row=next(r for r in self.ui.frames() if r.get('editbox'))
        self.assertGreater(row['editbox']['caret_x'],10);self.assertGreater(row['editbox']['cell_h'],5)
    def test_scroll_clipping_is_exported(self):
        self.ui.execute("s=CreateFrame('ScrollFrame','S',UIParent) s:SetWidth(80) s:SetHeight(40) s:SetPoint('TOPLEFT',UIParent,'TOPLEFT',10,-20) c=CreateFrame('Frame','C',s) c:SetWidth(80) c:SetHeight(200) s:SetScrollChild(c) t=c:CreateTexture('CT') t:SetAllPoints() t:SetTexture(1,0,0,1)")
        row=next(r for r in self.ui.frames() if r['kind']=='Texture')
        self.assertEqual(row['clip'],[10,20,80,40]);self.assertEqual(row['height'],200)
    def test_dependencies_demand_load_and_saved_variables(self):
        with tempfile.TemporaryDirectory(prefix='gg-addon-tests-') as tmp:
            root=Path(tmp)/'addons';root.mkdir();saved=Path(tmp)/'saves'
            for name,toc,source in [('Base','',"order='base'"),('Demo','## Dependencies: Base\n## SavedVariables: Settings\n',"assert(order=='base') Settings={clicks=0} f=CreateFrame('Frame') f:RegisterEvent('ADDON_LOADED') f:SetScript('OnEvent',function() if arg1=='Demo' then Settings.clicks=Settings.clicks+1 end end)"),('Demand','## LoadOnDemand: 1\n## SavedVariables: DemandSettings\n',"demandRan=true DemandSettings={value=1}")]:
                folder=root/name;folder.mkdir();(folder/(name+'.toc')).write_text('## Interface: 11200\n'+toc+'main.lua\n');(folder/'main.lua').write_text(source)
            self.ui.load_addons(root,saved)
            self.assertEqual(self.ui.evaluate("return Settings.clicks,IsAddOnLoaded('Base'),IsAddOnLoaded('Demand')"),[1,1,None])
            self.ui.execute("local ok,why=LoadAddOn('Demand') assert(ok,why)")
            self.assertEqual(self.ui.evaluate('return demandRan'),[True]);self.ui.execute('DemandSettings.value=42 LegacySetting=17 RegisterForSave("LegacySetting")');self.ui.save();self.ui.close()
            self.ui=GgEngineUI();self.ui.load_addons(root,saved)
            self.assertEqual(self.ui.evaluate('return Settings.clicks'),[2])
            self.ui.execute("local ok,why=LoadAddOn('Demand') assert(ok,why)")
            self.assertEqual(self.ui.evaluate('return DemandSettings.value,LegacySetting'),[42,17])
    def test_failed_settings_are_kept_and_sibling_addon_continues(self):
        with tempfile.TemporaryDirectory(prefix='gg-addon-error-test-') as tmp:
            root=Path(tmp)/'addons';root.mkdir();saved=Path(tmp)/'saves'
            for name,source in [('Broken',"error('broken addon')"),('Good',"continued=true Settings={default=1}")]:
                folder=root/name;folder.mkdir();(folder/(name+'.toc')).write_text('## Interface: 11200\n## SavedVariables: Settings\nmain.lua\n');(folder/'main.lua').write_text(source)
            path=saved/'Good/account.lua';path.parent.mkdir(parents=True);path.write_text('this is invalid lua')
            self.ui.load_addons(root,saved);self.assertEqual(self.ui.evaluate('return continued'),[True]);self.ui.save()
            self.assertEqual(path.read_text(),'this is invalid lua');self.assertTrue(any('broken addon' in e for e in self.ui.errors))
    def test_actions_and_selected_unit_use_real_snapshot(self):
        self.ui.publish({},True,100,50,target={'name':'Kessa','health':75,'max_health':110,'level':4},actions=[{'index':1,'kind':'ABILITY','usable':True,'in_range':True,'count':0}])
        self.assertEqual(self.ui.evaluate("return UnitName('target'),UnitHealth('target'),UnitHealthMax('target'),HasAction(2),IsUsableAction(2)"),['Kessa',75,110,1,1,None])
        self.ui.execute('UseAction(2) ClearTarget()')
        requests=self.ui.request('requests');self.assertEqual(requests['calls'],[{'op':'action','index':1,'on_self':False},{'op':'clear'}])
        self.ui.publish({},True,100,50);self.assertEqual(self.ui.evaluate("return UnitExists('target'),HasAction(2)"),[None,None])
    def test_loose_legacy_bytes_original_toc_lists_and_text_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)/'Raw';folder.mkdir()
            (folder/'Raw.toc').write_bytes(b'## Interface: 11200\n## Title: Sch\xe4tze\n## SavedVariables: A\n## SavedVariables: B\nraw.lua')
            (folder/'raw.lua').write_bytes(b'\xef\xbb\xbf#!/usr/bin/lua\nA={} B={} byte=string.byte("\xe4") length=string.len("\xe4")')
            self.assertEqual(self.ui.load_addons(Path(temporary)),[{'id':'Raw','title':'Schätze'}])
            self.assertEqual(self.ui.evaluate('return byte,length'),[228,1])
            for source in (b'\x1bLua',b'\xef\xbb\xbf\x1bLua',b'# skip\n\x1bLua'):
                with self.assertRaisesRegex(ValueError,'text Lua'):self.ui.execute(source)
            self.assertEqual(self.ui.evaluate('return 42'),[42])
    def test_qt_markup_and_texture_tint(self):
        from backend.game_engine_adapter_text import parse_markup,paint_text
        from PySide6.QtCore import QRectF
        from backend.game_engine_adapter_canvas import GgEngineCanvas
        text,runs=parse_markup('|| |cffff0000red|r |Hitem:1|hLink|h')
        self.assertEqual(text,'| red Link');self.assertEqual(next(c.name() for _,_,c,_ in runs if c.name()=='#ff0000'),'#ff0000');self.assertTrue(any(link=='item:1' for _,_,_,link in runs))
        class Runtime:lua=None
        parent=QQuickItem();parent.setWidth(80);parent.setHeight(80);canvas=GgEngineCanvas(Runtime(),parent)
        tinted=canvas.tinted_image('game/framexml/white.png',[.5,.25,1,.5],False)
        self.assertEqual(tinted.pixelColor(0,0).getRgb(),(128,64,255,128))
        image=QImage(100,32,QImage.Format_ARGB32_Premultiplied);image.fill(0);painter=QPainter(image)
        paint_text(painter,QRectF(0,0,100,32),{'text':'|cffff0000red|r','font_height':16,'justify_v':'Top','justify_h':'Left'});painter.end()
        self.assertTrue(any(image.pixelColor(x,y).red()>180 and image.pixelColor(x,y).green()<40 and image.pixelColor(x,y).alpha()>180 for x in range(100) for y in range(32)))
    def test_equipment_views_cursor_equip_and_inventory_move_real_host(self):
        from PySide6.QtCore import QObject
        from backend.game_engine_host import GameEngineRuntime
        from backend.game_engine_presentation import Presentation
        from backend import game_engine_items as items
        from unittest.mock import patch
        state=tempfile.TemporaryDirectory();self.addCleanup(state.cleanup)
        env=patch.dict(os.environ,{'XDG_STATE_HOME':state.name});env.start();self.addCleanup(env.stop)
        runtime=GameEngineRuntime();self.addCleanup(runtime.shutdown)
        ref='item.weapon_sword';name='engine-cursor-sword'
        runtime._item_instances[name]=items.make_instance(runtime._item_catalog,name,ref)
        runtime._inventory=items.inventory_counts(runtime._item_instances.values())
        class Bridge(QObject):
            def gameEngineItemEquip(self,instance,slot):return runtime.equip_item(instance,slot)
            def gameEngineInventoryMove(self,instance,slot):return runtime.move_inventory_slot(instance,slot)
            def gameEngineEquipmentMove(self,instance,slot):return runtime.move_equipment_to_inventory(instance,slot)
        bridge=Bridge();p=Presentation(bridge,device=False);self.addCleanup(lambda p=p,bridge=bridge:p.close())
        def refresh():p.last_update=0;p.update(runtime.snapshot())
        refresh();slot=next(s for s,row in p.gameplay_views.inventory_refs.items() if row[1]==name)
        runtime.action_bar_edit(json.dumps({'index':23,'kind':'ITEM','ref':ref}));refresh()
        action=runtime.snapshot()['actions']['slots'][23]
        self.assertEqual(action['texture'],runtime.snapshot()['items']['inventory'][next(i for i,r in enumerate(runtime.snapshot()['items']['inventory']) if r['instance_id']==name)]['icon'])
        self.assertEqual(p.lua.evaluate('return GetActionTexture(24)'),[action['texture']])
        p.lua.execute("gearEvents=0 f=CreateFrame('Frame') f:RegisterEvent('UNIT_INVENTORY_CHANGED') f:SetScript('OnEvent',function() assert(arg1=='player') gearEvents=gearEvents+1 end)")
        p.lua.execute(f'PickupContainerItem(0,{slot}) assert(CursorCanGoInSlot(16)) assert(EquipCursorItem(16))')
        request=p.lua.request('requests');self.assertEqual(len(request['item_moves']),1);p._game_requests(request)
        self.assertEqual(runtime._item_instances[name]['location'],'EQUIPPED');self.assertEqual(runtime._item_instances[name]['equipped_slot'],'MAIN_HAND')
        refresh();self.assertEqual(p.gameplay_views.equipment_refs[16],name)
        self.assertEqual(p.lua.evaluate("return GetInventoryItemCount('player',16),GetInventoryItemQuality('player',16),gearEvents"),[1,2,1])
        self.assertIn('item:',p.lua.evaluate("return GetInventoryItemLink('player',16)")[0])
        from urllib.parse import urlparse,unquote
        icon=p.lua.evaluate("return GetInventoryItemTexture('player',16)")[0]
        self.assertEqual(Path(unquote(urlparse(icon).path)).name,'unknown.png')
        self.assertTrue(Path(unquote(urlparse(icon).path)).is_file())
        refresh();self.assertEqual(p.lua.evaluate('return gearEvents'),[1])
        p.lua.execute('PickupInventoryItem(16) PickupContainerItem(0,63)');p._game_requests(p.lua.request('requests'))
        self.assertEqual(runtime._item_instances[name]['location'],'INVENTORY');self.assertEqual(runtime._item_instances[name]['slot_index'],62)
        refresh();slot=next(s for s,row in p.gameplay_views.inventory_refs.items() if row[1]==name)
        p.lua.execute(f'PickupContainerItem(0,{slot}) PickupContainerItem(0,64)');p._game_requests(p.lua.request('requests'))
        self.assertEqual(runtime._item_instances[name]['slot_index'],63)
        refresh();p.lua.execute('PickupContainerItem(0,64) assert(AutoEquipCursorItem())');p._game_requests(p.lua.request('requests'))
        self.assertEqual(runtime._item_instances[name]['location'],'EQUIPPED')
        runtime._item_instances['engine-swap-sword']=items.make_instance(runtime._item_catalog,'engine-swap-sword',ref)
        runtime._inventory=items.inventory_counts(runtime._item_instances.values());refresh()
        slot=next(s for s,row in p.gameplay_views.inventory_refs.items() if row[1]=='engine-swap-sword')
        p.lua.execute(f'PickupInventoryItem(16) PickupContainerItem(0,{slot})');p._game_requests(p.lua.request('requests'))
        self.assertEqual(runtime._item_instances['engine-swap-sword']['location'],'EQUIPPED')
        self.assertEqual(runtime._item_instances[name]['slot_index'],slot-1)
        food=next(k for k,v in runtime._item_catalog['items'].items() if v.get('kind')=='CONSUMABLE')
        runtime._item_instances['engine-misfit']=items.make_instance(runtime._item_catalog,'engine-misfit',food)
        runtime._inventory=items.inventory_counts(runtime._item_instances.values());refresh()
        food_slot=next(s for s,row in p.gameplay_views.inventory_refs.items() if row[1]=='engine-misfit')
        rejected=runtime.move_equipment_to_inventory('engine-swap-sword',food_slot-1)
        self.assertEqual(rejected['error'],'ITEM_EQUIP_SLOT_INCOMPATIBLE')
        self.assertEqual(runtime._item_instances['engine-swap-sword']['location'],'EQUIPPED')
        self.assertEqual(runtime._item_instances['engine-misfit']['slot_index'],food_slot-1)
        foreign=items.make_instance(runtime._item_catalog,'foreign-sword',ref,location='EQUIPPED',owner_id='npc',equipped_slot='MAIN_HAND')
        runtime._item_instances['foreign-sword']=foreign
        self.assertEqual(runtime.move_equipment_to_inventory('foreign-sword',63)['error'],'ITEM_EQUIPMENT_MOVE_INVALID')
        self.assertEqual(foreign['location'],'EQUIPPED')
        self.assertFalse(p.errors,p.errors);self.assertFalse(p.unsupported_requests,p.unsupported_requests)

    def test_lua_split_merge_real_stacks_preserves_metadata_counts_and_rejects_bad_moves(self):
        import copy
        from PySide6.QtCore import QObject
        from backend.game_engine_host import GameEngineRuntime
        from backend.game_engine_presentation import Presentation
        from backend import game_engine_items as items
        from unittest.mock import patch
        state=tempfile.TemporaryDirectory();self.addCleanup(state.cleanup)
        env=patch.dict(os.environ,{'XDG_STATE_HOME':state.name});env.start();self.addCleanup(env.stop)
        runtime=GameEngineRuntime();self.addCleanup(runtime.shutdown)
        ref='item.sea_salt'
        source=items.make_instance(runtime._item_catalog,'split-source',ref,quantity=9)
        source.update(slot_index=0,condition=.8,craft_quality='FINE',affixes=[{'id':'test-affix'}])
        runtime._item_instances={'split-source':source};runtime._inventory={ref:9}
        class Bridge(QObject):
            def gameEngineInventoryStack(self,instance,slot,count):return runtime.transfer_inventory_stack(instance,slot,count)
            def gameEngineInventoryMove(self,instance,slot):return runtime.move_inventory_slot(instance,slot)
        bridge=Bridge();p=Presentation(bridge,device=False);self.addCleanup(lambda p=p,bridge=bridge:p.close())
        def refresh():p.last_update=0;p.update(runtime.snapshot())
        refresh();p.lua.execute('assert(SplitContainerItem(0,1,3)) PickupContainerItem(0,64)')
        p._game_requests(p.lua.request('requests'))
        child=next(r for r in runtime._item_instances.values() if r['slot_index']==63)
        self.assertEqual((source['quantity'],child['quantity']),(6,3))
        self.assertEqual((child['condition'],child['craft_quality'],child['affixes']),(.8,'FINE',[{'id':'test-affix'}]))
        self.assertEqual(runtime._inventory[ref],9)
        refresh();p.lua.execute('assert(SplitContainerItem(0,1,2)) PickupContainerItem(0,64)')
        p._game_requests(p.lua.request('requests'));self.assertEqual((source['quantity'],child['quantity']),(4,5))
        refresh();p.lua.execute('PickupContainerItem(0,64) PickupContainerItem(0,1)')
        p._game_requests(p.lua.request('requests'));self.assertEqual(source['quantity'],9)
        self.assertNotIn(child['instance_id'],runtime._item_instances)
        self.assertEqual(runtime._inventory[ref],9)
        foreign=items.make_instance(runtime._item_catalog,'split-foreign',ref,owner_id='npc',location='POCKET',quantity=4)
        runtime._item_instances['split-foreign']=foreign
        before=copy.deepcopy(runtime._item_instances)
        for args,error in ((('split-foreign',1,1),'ITEM_STACK_TRANSFER_INVALID'),(('split-source',1,99),'ITEM_STACK_TRANSFER_INVALID'),
                           (('split-source',0,2),'ITEM_STACK_SAME_SLOT'),(('split-source',64,2),'ITEM_STACK_TRANSFER_INVALID')):
            self.assertEqual(runtime.transfer_inventory_stack(*args)['error'],error)
            self.assertEqual(runtime._item_instances,before)
        different=copy.deepcopy(source);different.update(instance_id='other-quality',quantity=2,slot_index=1,craft_quality='STANDARD')
        runtime._item_instances['other-quality']=different;before=copy.deepcopy(runtime._item_instances)
        self.assertEqual(runtime.transfer_inventory_stack('split-source',1,1)['error'],'ITEM_STACK_INCOMPATIBLE')
        self.assertEqual(runtime._item_instances,before)
        different['craft_quality']='FINE';different['quantity']=98;runtime._inventory[ref]=107
        self.assertEqual(runtime.transfer_inventory_stack('split-source',1,2)['error'],'ITEM_STACK_CAPACITY')
        result=runtime.move_inventory_slot('split-source',1);self.assertNotIn('error',result)
        self.assertEqual((source['quantity'],different['quantity']),(8,99));self.assertEqual(runtime._inventory[ref],107)
        self.assertFalse(p.errors,p.errors);self.assertFalse(p.unsupported_requests,p.unsupported_requests)

    def test_lua_action_drag_places_real_spell_item_and_command_and_respects_lock(self):
        from PySide6.QtCore import QObject
        from backend.game_engine_host import GameEngineRuntime
        from backend.game_engine_presentation import Presentation
        from backend import game_engine_items as items
        from unittest.mock import patch
        state=tempfile.TemporaryDirectory();self.addCleanup(state.cleanup)
        env=patch.dict(os.environ,{'XDG_STATE_HOME':state.name});env.start();self.addCleanup(env.stop)
        runtime=GameEngineRuntime();self.addCleanup(runtime.shutdown)
        name='action-drag-sword';ref='item.weapon_sword'
        runtime._item_instances[name]=items.make_instance(runtime._item_catalog,name,ref)
        runtime._inventory=items.inventory_counts(runtime._item_instances.values())
        class Bridge(QObject):
            def gameEngineActionBarEdit(self,payload):return runtime.action_bar_edit(payload)
            def gameEngineActionUse(self,index):return runtime.action_use(index)
        bridge=Bridge();p=Presentation(bridge,device=False);self.addCleanup(lambda p=p,bridge=bridge:p.close())
        def refresh():p.last_update=0;p.update(runtime.snapshot())
        refresh();slot=next(s for s,r in p.gameplay_views.inventory_refs.items() if r[1]==name)
        p.lua.execute(f'PickupContainerItem(0,{slot}) assert(PlaceAction(24))')
        req=p.lua.request('requests');self.assertEqual(req['action_sets'][0][1]>>24,128);p._game_requests(req)
        self.assertEqual(runtime._actions.slots[23],{'kind':'ITEM','ref':ref})
        self.assertEqual(runtime._item_instances[name]['location'],'INVENTORY')
        refresh();spell=list(p.gameplay_views.spells)[0]
        p.lua.execute("ClearCursor() PickupSpell(1,'spell') assert(PlaceAction(23))")
        p._game_requests(p.lua.request('requests'));self.assertEqual(runtime._actions.slots[22],{'kind':'ABILITY','ref':spell})
        refresh();p.lua.execute('PickupAction(23) PlaceAction(24) PlaceAction(23)');p._game_requests(p.lua.request('requests'))
        self.assertEqual(runtime._actions.slots[22],{'kind':'ITEM','ref':ref})
        self.assertEqual(runtime._actions.slots[23],{'kind':'ABILITY','ref':spell})
        refresh();p.lua.execute('ClearCursor() PickupAction(6) PlaceAction(22) UseAction(22)');p._game_requests(p.lua.request('requests'))
        self.assertEqual(runtime._actions.slots[21],{'kind':'COMMAND','ref':'TOGGLE_FLIGHT'})
        self.assertEqual(runtime._movement_mode,'FLY')
        runtime.action_bar_edit(json.dumps({'verb':'LOCK','locked':True}));refresh()
        p.lua.execute('ClearCursor() PickupAction(24) PlaceAction(23)');p._game_requests(p.lua.request('requests'))
        self.assertEqual(runtime._actions.slots[22],{'kind':'ITEM','ref':ref})
        self.assertEqual(runtime._actions.slots[23],{'kind':'ABILITY','ref':spell})
        refresh();self.assertTrue(p.lua.evaluate('return HasAction(24)')[0])
        self.assertFalse(p.errors,p.errors);self.assertFalse(p.unsupported_requests,p.unsupported_requests)

    def test_gameplay_inventory_spellbook_quests_and_change_events(self):
        from backend.game_engine_adapter_gameplay import GameplayViews
        views=GameplayViews()
        snapshot={'items':{'inventory':[{'slot_index':3,'instance_id':'food-b','definition_id':'food','name':'Ration','quantity':7,'stack_limit':20,'rarity':'TRASH','kind':'CONSUMABLE'}]},'actions':{'abilities':[{'ref':'dash','name':'Dash'}],'slots':[{'ref':'dash','cooldown_s':2,'cooldown_duration_s':4}]},'quests':{'active':[{'id':'quest','name':'Hunt','description':'Protect the camp','objective':{'kind':'DEFEAT','label':'Boars defeated'},'rewards':{'gold':3},'progress':{'current':2,'required':5,'status':'ACTIVE'}}]},'economy':{'wallet':{'gold':17}}}
        self.ui.execute("events={} f=CreateFrame('Frame') f:RegisterEvent('BAG_UPDATE') f:RegisterEvent('SPELLS_CHANGED') f:RegisterEvent('SPELL_UPDATE_COOLDOWN') f:RegisterEvent('QUEST_LOG_UPDATE') f:RegisterEvent('PLAYER_MONEY') f:SetScript('OnEvent',function() events[event]=(events[event] or 0)+1 end)")
        self.ui.publish({},True,100,50,**views.update(snapshot))
        self.assertEqual(self.ui.evaluate("local texture,count,locked,quality=GetContainerItemInfo(0,4) return GetContainerNumSlots(0),count,locked,quality,GetMoney(),GetSpellName(1,'spell')"),[64,7,False,0,170000,'Dash',''])
        self.assertEqual(self.ui.evaluate("SelectQuestLogEntry(1) local text,kind,done=GetQuestLogLeaderBoard(1) return GetNumQuestLogEntries(),GetQuestLogQuestText(),GetQuestLogRewardMoney(),text,kind,done"),[1,'Protect the camp',30000,'Boars defeated: 2/5','monster',False])
        self.ui.execute("CastSpell(1,'spell') UseContainerItem(0,4)")
        calls=self.ui.request('requests')['calls'];self.assertEqual([c['op'] for c in calls],['spell','container'])
        self.assertEqual(views.spell_refs[calls[0]['spell_id']],'dash');self.assertEqual(views.inventory_refs[calls[1]['slot']],('food','food-b'))
        self.ui.publish({},True,100,50,**views.update({'actions':snapshot['actions']}))
        self.assertEqual(self.ui.evaluate("return events.BAG_UPDATE,events.SPELLS_CHANGED,events.QUEST_LOG_UPDATE,events.PLAYER_MONEY"),[1,1,1,1])
        snapshot['actions']['slots'][0]['cooldown_s']=1
        self.ui.publish({},True,100,50,**views.update(snapshot))
        self.assertEqual(self.ui.evaluate('return events.SPELLS_CHANGED,events.SPELL_UPDATE_COOLDOWN'),[1,2])
        self.ui.publish({},True,100,50,**views.update({'items':{'inventory':[]},'quests':{'active':[]},'actions':{'abilities':[],'slots':[]},'economy':{'wallet':{'gold':0}}}))
        self.assertEqual(self.ui.evaluate("return GetContainerItemLink(0,4),GetNumSpellTabs(),GetNumQuestLogEntries(),GetMoney()"),[None,0,0,0])

    def test_container_use_consumes_selected_stack_and_validates_ownership(self):
        from backend.game_engine_host import GameEngineRuntime
        from backend import game_engine_items as items
        runtime=GameEngineRuntime()
        try:
            runtime.snapshot();definition=next(k for k,v in runtime._item_catalog['items'].items() if 'RECOVERY' in v.get('tags',[]))
            for identity,owner in [('food-a','player'),('food-b','player'),('food-other','npc')]:
                row=items.make_instance(runtime._item_catalog,identity,definition,quantity=3);row['owner_id']=owner;runtime._item_instances[identity]=row
            runtime._inventory=items.inventory_counts(runtime._item_instances.values())
            runtime._combat_state['actors']['player']['health']-=30
            self.assertEqual(runtime.action_use_item(definition,'food-other')['error'],'ITEM_NOT_IN_INVENTORY')
            self.assertFalse(runtime.action_use_item(definition,'food-b').get('error'))
            self.assertEqual(runtime._item_instances['food-a']['quantity'],3);self.assertEqual(runtime._item_instances['food-b']['quantity'],2)
        finally:runtime.shutdown()

    def test_editbox_alt_arrows_and_keyboard_modifiers(self):
        self.ui.execute("e=CreateFrame('EditBox','E',UIParent) e:SetWidth(100) e:SetHeight(20) e:SetFont('Sans Serif',12) e:SetText('ABCD') e:SetAltArrowKeyMode(true) e:SetFocus()")
        self.assertFalse(self.ui.request('key',key='LEFT'))
        self.ui.request('text',text='x');self.assertEqual(self.ui.evaluate('return E:GetText()'),['ABCDx'])
        self.ui.request('key',key='LEFT',alt=True);self.ui.request('text',text='y')
        self.assertEqual(self.ui.evaluate('return E:GetText(),IsAltKeyDown()'),['ABCDyx',1])

    def test_reloaded_clock_preserves_remaining_cooldown(self):
        self.ui.close();self.ui=GgEngineUI(clock=120)
        self.ui.publish({},True,100,50,spells=[{'spell_id':1,'name':'Dash','cooldown_s':2,'cooldown_duration_s':4}])
        self.assertEqual(self.ui.evaluate("return GetSpellCooldown(1,'spell')"),[118,4,1])
        self.ui.tick(.5)
        self.assertEqual(self.ui.evaluate("local start,duration=GetSpellCooldown(1,'spell') return start+duration-GetTime()"),[1.5])
    def test_hung_pcall_cannot_freeze_parent(self):
        start=time.monotonic()
        with self.assertRaises(TimeoutError):self.ui.request('exec',source='while true do pcall(function() while true do end end) end',timeout=.12)
        self.assertLess(time.monotonic()-start,1);self.assertIsNotNone(self.ui.process.poll())
    def test_addon_bindings_press_release_and_restart(self):
        with tempfile.TemporaryDirectory(prefix='gg-binding-test-') as tmp:
            root=Path(tmp)/'addons';folder=root/'Keys';folder.mkdir(parents=True);saved=Path(tmp)/'saves'
            (folder/'Keys.toc').write_text('## Interface: 11200\nmain.lua\n');(folder/'main.lua').write_text("SetBinding('CTRL-K','GGTEST')")
            (folder/'Bindings.xml').write_text('<Bindings><Binding name="GGTEST" runOnUp="true">pressed=keystate</Binding></Bindings>')
            self.ui.load_addons(root,saved);self.ui.request('key',key='K',ctrl=True);self.assertEqual(self.ui.evaluate('return pressed,keystate'),['down',None])
            self.ui.request('key_up',key='K',ctrl=True);self.assertEqual(self.ui.evaluate('return pressed'),['up'])
            self.ui.execute("SetBinding('CTRL-J','GGTEST') SaveBindings(2)");self.ui.save();self.ui.close();self.ui=GgEngineUI();self.ui.load_addons(root,saved)
            self.ui.request('key',key='J',ctrl=True);self.assertEqual(self.ui.evaluate('return pressed'),['down'])
    def test_original_sources_and_exact_local_adaptations_retain_source_integrity(self):
        from tests.engine_source_provenance import assert_source_integrity
        root=PROJECT/'native/engine-ui';_,adaptations=assert_source_integrity(self,root)
        required={'crates/engine-ui-core/src/script/'+name+'.rs' for name in ('model','merchant','party','trade')}
        self.assertTrue(required <= {change['path'] for change in adaptations.values()})
    def test_qt_draws_actual_framexml(self):
        from backend.game_engine_adapter_canvas import GgEngineCanvas
        class Runtime:
            lua=None
            def _update_frames(self):pass
        runtime=Runtime();parent=QQuickItem();parent.setWidth(400);parent.setHeight(340)
        canvas=GgEngineCanvas(runtime,parent);self.ui.resize(400,340);self.ui.load_addons(PROJECT/'qml/game/framexml')
        canvas.sync(self.ui.frames());image=QImage(400,340,QImage.Format_ARGB32_Premultiplied);image.fill(0)
        painter=QPainter(image);canvas.paint(painter);painter.end()
        self.assertGreater(image.pixelColor(20,194).alpha(),200)
        self.assertEqual(image.pixelColor(2,2).alpha(),0)
        self.assertFalse(canvas.missing)

if __name__=='__main__':unittest.main()
