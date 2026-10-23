"""Real ABI + Qt retained buffers: original attach lookup, item catalog and ribbon tracks."""
import os,struct,tempfile,unittest,math
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtGui import QGuiApplication
from backend.game_engine_adapter_formats import PROJECT,NativeFormats,AssetCache
from backend.game_engine_adapter_ui import GgEngineUI
from tools.world import engine_format_fixtures as f
APP=QGuiApplication.instance() or QGuiApplication([])
class AttachmentsRibbons(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=PROJECT/'qml');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.reader=NativeFormats(self.root);self.addCleanup(self.reader.close)
        (self.root/'gold.blp').write_bytes(f.blp());self.body=self.root/'body.m2';self.body.write_bytes(f.attachment_m2())
        self.child=self.root/'child.m2';self.child.write_bytes(f.m2())
    def cache(self):
        cache=AssetCache();self.addCleanup(cache.close);return cache
    def row(self,clock=0):return {'id':'p','clock_ms':clock,'play':{'anim_id':7,'cursor_ms':clock}}
    def test_lookup_duplicate_record_and_live_bone_anchor(self):
        meta,_=self.reader.decode(self.body,runtime=True,anim_id=7,cursor_ms=500)
        self.assertEqual(meta['attachments']['11'][12:15],[.5,0.,1.2000000476837158])
        self.assertNotIn('3',meta['attachments'])
        child,blob=self.reader.decode(self.child,runtime=True,anchor=meta['attachments']['11'])
        self.assertAlmostEqual(struct.unpack_from('<3f',blob)[0],-.5)
        self.assertAlmostEqual(struct.unpack_from('<3f',blob)[1],.2,places=5)
    def test_anchor_rejects_nonaffine_singular_and_malformed(self):
        for anchor in ([1]*16,[1]*15,[0]*16):
            with self.assertRaisesRegex(ValueError,'anchor'):self.reader.decode(self.child,runtime=True,anchor=anchor)
        self.assertEqual(self.reader.request('ping'),{'abi':1})
    def test_retained_attachment_follows_animation_and_clears(self):
        cache=self.cache();model=cache.live_model(self.body,self.row())
        look={'attachments':[{'id':11,'model':str(self.child)}]};model.appearance({'appearance':look})
        child=model.children[11];geometry=child.batches[0].geo;first=bytes(geometry.vertexData());size=cache.live_bytes
        cache.live_model(self.body,self.row(500)).appearance({'appearance':look})
        self.assertIs(model.children[11],child);self.assertIs(child.batches[0].geo,geometry);self.assertEqual(cache.live_bytes,size)
        self.assertAlmostEqual(struct.unpack_from('<f',bytes(geometry.vertexData()))[0]-struct.unpack_from('<f',first)[0],.5)
        model.appearance({});self.assertEqual(model.children,{});self.assertEqual(cache.attachment_models,{})
        cache.close();self.assertEqual(cache.live_bytes,0)
    def test_parent_panes_share_child_file_but_keep_pose_and_cleanup(self):
        cache=self.cache();a=cache.live_model(self.body,self.row());b=cache.live_model(self.body,{**self.row(500),'id':'q'})
        look={'attachments':[{'id':1,'model':str(self.child)}]}
        a.appearance({'appearance':look});b.appearance({'appearance':look})
        self.assertIsNot(a.children[1],b.children[1]);self.assertNotEqual(bytes(a.children[1].batches[0].geo.vertexData()),bytes(b.children[1].batches[0].geo.vertexData()))
        cache.retain_live_panes(['q']);b=cache.live_model(self.body,{**self.row(600),'id':'q'});b.appearance({'appearance':look})
        self.assertEqual(len(cache.attachment_models),1);cache.retain_live_panes([]);self.assertEqual(cache.live_bytes,0)
    def test_bad_outfit_and_paths_leave_published_attachments(self):
        cache=self.cache();model=cache.live_model(self.body,self.row());spec={'id':1,'model':str(self.child)}
        model.appearance({'appearance':{'attachments':[spec]}});old=model.children[1];size=cache.live_bytes
        bad=self.root/'bad.m2';bad.write_bytes(b'bad')
        for specs in ([spec,{'id':2,'model':str(bad)}],[spec,spec],[{'id':1,'model':'/etc/passwd'}],[spec]*7):
            with self.subTest(specs=specs),self.assertRaises((ValueError,RuntimeError)):model.appearance({'appearance':{'attachments':specs}})
            self.assertIs(model.children[1],old);self.assertEqual(cache.live_bytes,size)
    def test_failed_staged_texture_swap_does_not_change_old_texture(self):
        cache=self.cache();model=cache.live_model(self.body,self.row());spec={'id':1,'model':str(self.child)}
        model.appearance({'appearance':{'attachments':[spec]}});old=model.children[1];pixels=bytes(old.batches[0].tex.textureData());size=cache.live_bytes
        # Replaceable Object texture changes first; the second staged model then fails.
        data=bytearray(f.m2(texture=''));texture=struct.unpack_from('<I',data,0x60)[0];struct.pack_into('<I',data,texture,2)
        replacement=self.root/'replacement.m2';replacement.write_bytes(data);bad=self.root/'bad.m2';bad.write_bytes(b'bad')
        with self.assertRaises(ValueError):model.appearance({'appearance':{'attachments':[{'id':1,'model':str(replacement),'object':str(self.root/'gold.blp')},{'id':2,'model':str(bad)}]}})
        self.assertIs(model.children[1],old);self.assertEqual(bytes(old.batches[0].tex.textureData()),pixels);self.assertEqual(cache.live_bytes,size)
        cache.live_model(self.body,self.row(100)).appearance({'appearance':{'attachments':[spec]}})
    def test_missing_attach_point_is_reported_and_worker_recovers(self):
        cache=self.cache();model=cache.live_model(self.body,self.row());model.appearance({'appearance':{'attachments':[{'id':3,'model':str(self.child)}]}})
        self.assertFalse(model.children);self.assertIn('M2 attachment point unavailable: 3',model.limitations)
        cache.reader.close();cache.live_model(self.body,self.row(100)).appearance({'appearance':{'attachments':[{'id':1,'model':str(self.child)}]}})
        self.assertEqual(len(model.children),1)
    def test_item_catalog_resolves_racial_helm_asymmetric_shoulders_and_shield(self):
        data=self.root/'Data';data.mkdir();(data/'patch.MPQ').write_bytes(f.mpq(entries=f.equipment_entries()))
        cache=self.cache();cache.mount_chain(data);model=cache.live_model(self.body,self.row())
        character={'race':1,'helmet':80,'shoulders':81,'mainhand':82,'offhand':83,'offhand_is_shield':True}
        model.appearance({'appearance':{'character':character}})
        self.assertEqual(set(model.children),{11,6,5,1,0});self.assertTrue(model.children[11].path.name.endswith('HuM.m2'))
        left=bytes(model.children[6].batches[0].tex.textureData())[:4];right=bytes(model.children[5].batches[0].tex.textureData())[:4]
        self.assertEqual(left,bytes((10,255,10,255)));self.assertEqual(right,bytes((10,10,255,255)))
        self.assertFalse(any('attachment renderer' in s for s in model.limitations))
        model.appearance({'appearance':{'character':{'race':1}}});self.assertFalse(model.children)
        self.reader.request('mount_chain',path=str(data));meta,_=NativeFormats._unpack(self.reader.request('character',character={**character,'sex':1}))
        self.assertTrue(next(row['model'] for row in meta['attachments'] if row['id']==11).endswith('HuF.m2'))
    def ribbon(self,**options):
        path=self.root/'ribbon.m2';path.write_bytes(f.ribbon_m2(**options));self.reader.decode(path,runtime=True,instance='a',anim_id=7,clock_ms=0);return path
    def pose(self,path,clock,instance='a',**options):return self.reader.pose(path,instance=instance,anim_id=7,cursor_ms=clock,clock_ms=clock,**options)
    def test_ribbon_original_width_color_cell_blend_and_history(self):
        path=self.ribbon();meta,blob=self.pose(path,100);row=meta['ribbons']['rows'][0]
        self.assertEqual(meta['ribbons']['live_edges'],2);self.assertEqual(row['vertices'],8);self.assertEqual(row['blend'],6)
        vertices=struct.unpack_from('<96f',blob,row['offset']);self.assertTrue(all(math.isfinite(v) for v in vertices))
        self.assertAlmostEqual(vertices[6],0);self.assertAlmostEqual(vertices[7],1);self.assertAlmostEqual(vertices[8],1);self.assertAlmostEqual(vertices[9],.25)
        self.assertAlmostEqual(vertices[11],24575/32767,places=5)
        meta,blob=self.pose(path,200);row=meta['ribbons']['rows'][0];points=[struct.unpack_from('<3f',blob,row['offset']+i*48) for i in range(row['vertices'])]
        self.assertGreater(max(p[0] for p in points)-min(p[0] for p in points),.09)
        self.assertAlmostEqual(max(p[2] for p in points)-min(p[2] for p in points),.18,places=5)
    def test_ribbon_gate_hides_whole_draw_ages_and_seek_resets(self):
        path=self.ribbon(gate=True);meta,_=self.pose(path,100);self.assertFalse(meta['ribbons']['rows'][0]['visible'])
        meta,_=self.pose(path,250);self.assertTrue(meta['ribbons']['rows'][0]['visible'])
        meta,_=self.pose(path,450);self.assertFalse(meta['ribbons']['rows'][0]['visible']);self.assertGreater(meta['ribbons']['live_edges'],0)
        meta,_=self.pose(path,50);self.assertTrue(meta['ribbons']['reset']);self.assertEqual(meta['ribbons']['live_edges'],0)
    def test_ribbon_gravity_positive_rise_and_instance_independence(self):
        height=[]
        for gravity in (0,2):
            path=self.ribbon(gravity=gravity);self.pose(path,100);meta,blob=self.pose(path,200);row=meta['ribbons']['rows'][0];height.append(max(struct.unpack_from('<3f',blob,row['offset']+i*48)[1] for i in range(row['vertices'])))
        self.assertGreater(height[1],height[0]+.015)
        self.pose(path,0,instance='b');meta,_=self.pose(path,200,instance='b');self.assertEqual(meta['ribbons']['live_edges'],2)
        meta,_=self.pose(path,200);self.assertEqual(meta['ribbons']['live_edges'],4)
    def test_ribbon_retained_buffers_bounded_history_and_malformed_input(self):
        path=self.ribbon(rate=1e6,life=60);cache=self.cache();model=cache.live_model(path,self.row());geo=model.batches[-1].geo;size=cache.live_bytes
        for clock in (100,200,300):cache.live_model(path,self.row(clock))
        self.assertEqual(model.ribbon_edges,512);self.assertIs(model.batches[-1].geo,geo);self.assertEqual(cache.live_bytes,size)
        data=bytearray(f.ribbon_m2());struct.pack_into('<I',data,0x134,17);path.write_bytes(data)
        with self.assertRaisesRegex(ValueError,'emitter capacity'):self.reader.decode(path,runtime=True)
        path.write_bytes(f.ribbon_m2(gravity=float('nan')))
        with self.assertRaisesRegex(ValueError,'parameter'):self.reader.decode(path,runtime=True,instance='a',anim_id=7)
    def test_effect_only_model_loads_without_surface_batches(self):
        path=self.root/'effect-only.m2';data=bytearray(f.ribbon_m2());view=struct.unpack_from('<I',data,80)[0];struct.pack_into('<I',data,view+32,0);path.write_bytes(data)
        cache=self.cache();model=cache.live_model(path,self.row());self.assertEqual(model.mesh_count,0);self.assertEqual(len(model.batches),1)
        cache.live_model(path,self.row(100));self.assertEqual(model.ribbon_edges,2)
    def test_lua_equipment_extension_roundtrips_without_touching_original_methods(self):
        ui=GgEngineUI();self.addCleanup(ui.close)
        ui.execute("m=CreateFrame('PlayerModel','Gear',UIParent) m:SetAllPoints() GG_SetCharacterAppearance('Gear',{race=1,helmet=80,shoulders=81,mainhand=82,offhand=83,offhand_is_shield=true})")
        model=next(row for row in ui.frames() if row.get('name')=='Gear')
        self.assertEqual(model['appearance']['character']['shoulders'],81);self.assertTrue(model['appearance']['character']['offhand_is_shield'])

    def catalog(self):
        data=self.root/'Data';data.mkdir();(data/'patch.MPQ').write_bytes(f.mpq(entries=f.creature_entries()))
        cache=self.cache();cache.mount_chain(data);self.reader.request('mount_chain',path=str(data));return cache
    def test_creature_catalog_model_skins_scale_alpha_and_physical_metadata(self):
        cache=self.catalog();display=cache.creature_display(100)
        self.assertEqual(display['source'],'GG\\creature.m2');self.assertEqual(display['scale'],1.)
        self.assertAlmostEqual(display['alpha'],128/255,places=6);self.assertEqual(display['collision_height'],3.)
        self.assertFalse(display['breathes']);self.assertEqual(display['foley_material'],4)
        self.assertEqual(display['appearance']['skins'],['GG\\GG_Monster.blp',None,None])
        path=cache.attachment_path(display['source'],self.body);model=cache.live_model(path,self.row());model.appearance({'appearance':display['appearance']})
        self.assertEqual(bytes(model.batches[0].tex.textureData())[:4],bytes((16,24,255,255)))
        display['appearance']['skins'][0]='BROKEN';self.assertEqual(cache.creature_display(100)['appearance']['skins'][0],'GG\\GG_Monster.blp')
        for value in (0,True,-1,0x100000000,999):
            with self.subTest(value=value),self.assertRaises(ValueError):cache.creature_display(value)
    def test_npc_catalog_bake_is_preserved_and_live_composite_fallback_works(self):
        cache=self.catalog();baked=cache.creature_display(101);live=cache.creature_display(102)
        self.assertNotIn('skins',baked['appearance']);self.assertEqual(baked['appearance']['character']['equipment'],[0]*8)
        for display,expected in ((baked,bytes((200,0,255,255))),(live,bytes((120,80,40,255)))):
            meta,image=cache.character(display['appearance']['character']);self.assertEqual(bytes(image.constBits())[:4],expected)
            path=cache.attachment_path(display['source'],self.body);model=cache.live_model(path,self.row());model.appearance({'appearance':display['appearance']})
            self.assertEqual(set(model.children),{11,5,6});self.assertEqual(bytes(model.batches[0].tex.textureData())[:4],expected)
        cache.close();self.assertEqual(cache.live_bytes,0)
    def test_catalog_bounds_and_bake_missing_reject_without_poisoning_reader(self):
        cache=self.catalog();baked=cache.creature_display(101)['appearance']['character']
        with self.assertRaises(ValueError):cache.character({**baked,'baked':'Textures/BakedNpcTextures/missing.blp'})
        data=self.root/'Data';entries=f.creature_entries();entries['DBFilesClient/CreatureModelData.dbc']=b'bad'
        (data/'patch.MPQ').write_bytes(f.mpq(entries=entries));self.reader.request('mount_chain',path=str(data))
        with self.assertRaises(ValueError):self.reader.request('creature_display',display_id=100)
        self.assertEqual(self.reader.request('ping'),{'abi':1})
    def test_lua_creature_display_set_clear_and_named_unit_animation_clock(self):
        ui=GgEngineUI();self.addCleanup(ui.close)
        ui.execute("m=CreateFrame('PlayerModel','NPC',UIParent) m:SetAllPoints() m:SetUnit('player') GG_SetCreatureDisplay('NPC',101)")
        ui.request('model_facts',path='npc.m2',name='NPC',facts={'sequences':[{'anim_id':7,'duration_ms':1000,'looping':True}],'bbox':[[-1,0,-1],[1,0,1]],'cameras':1})
        ui.tick(.5);row=next(r for r in ui.frames() if r.get('name')=='NPC')
        self.assertEqual(row['clock_ms'],500);self.assertEqual(row['play']['anim_id'],7);self.assertEqual(row['raw_cursor_ms'],500)
        self.assertEqual(row['appearance']['display_id'],101)
        ui.execute("GG_SetCreatureDisplay('NPC',nil)");row=next(r for r in ui.frames() if r.get('name')=='NPC');self.assertNotIn('appearance',row)
    def test_looped_effect_clock_is_continuous_but_manual_seek_resets(self):
        path=self.root/'ribbon.m2';path.write_bytes(f.ribbon_m2(life=2));ui=GgEngineUI();self.addCleanup(ui.close)
        ui.execute("m=CreateFrame('Model','Loop',UIParent) m:SetAllPoints() m:SetModel('loop.m2')")
        ui.request('model_facts',path='loop.m2',facts={'sequences':[{'anim_id':7,'duration_ms':1000,'looping':True}],'bbox':[[-1,0,-1],[1,0,1]],'cameras':0})
        cache=self.cache();model=None
        for _ in range(12):
            row=next(r for r in ui.frames() if r.get('name')=='Loop');model=cache.live_model(path,row);ui.tick(.1)
        row=next(r for r in ui.frames() if r.get('name')=='Loop');self.assertEqual(row['raw_cursor_ms'],1200);self.assertEqual(row['play']['cursor_ms'],200)
        self.assertGreaterEqual(model.ribbon_edges,20)
        ui.execute('m:SetSequenceTime(7,100)');row=next(r for r in ui.frames() if r.get('name')=='Loop');model=cache.live_model(path,row)
        self.assertEqual(row['raw_cursor_ms'],100);self.assertEqual(model.ribbon_edges,0)

    def test_ribbon_gate_repeats_on_clip_loop_without_losing_edge_history(self):
        path=self.ribbon(gate=True,life=2)
        self.pose(path,250);meta,_=self.pose(path,450);self.assertFalse(meta['ribbons']['rows'][0]['visible'])
        for clock in (650,850,1050):self.pose(path,clock)
        meta,_=self.pose(path,1250);self.assertTrue(meta['ribbons']['rows'][0]['visible']);self.assertFalse(meta['ribbons']['reset']);self.assertGreaterEqual(meta['ribbons']['live_edges'],4)

    def test_named_unit_clock_survives_hide_show_and_hidden_fact_eviction(self):
        ui=GgEngineUI();self.addCleanup(ui.close)
        facts={'sequences':[{'anim_id':7,'duration_ms':1000,'looping':True}],'bbox':[[-1,0,-1],[1,0,1]],'cameras':0}
        for i in range(10):
            if i:ui.execute('m:Hide()')
            ui.execute(f"m=CreateFrame('PlayerModel','Unit{i}',UIParent) m:SetAllPoints() m:SetUnit('player')")
            ui.request('model_facts',path='npc.m2',name=f'Unit{i}',facts=facts);ui.tick(.1)
            row=next(r for r in ui.frames() if r.get('name')==f'Unit{i}');self.assertEqual(row['host_model_source'],'npc.m2')
        ui.execute('m:Hide()');ui.frames();ui.execute('m:Show()');row=next(r for r in ui.frames() if r.get('name')=='Unit9')
        self.assertEqual(row['play']['cursor_ms'],100)
        ui.execute('m:Hide() Unit0:Show()');row=next(r for r in ui.frames() if r.get('name')=='Unit0')
        self.assertIsNone(row['host_model_source']);ui.request('model_facts',path='npc.m2',name='Unit0',facts=facts)
        ui.tick(.1);self.assertIsNotNone(next(r for r in ui.frames() if r.get('name')=='Unit0')['play'])
    def test_full_eight_panes_six_parts_and_provisional_outfit_capacity(self):
        cache=self.cache();slots=(0,1,2,5,6,11);models=[]
        appearance={'attachments':[{'id':slot,'model':str(self.child)} for slot in slots]}
        for i in range(8):
            model=cache.live_model(self.body,{**self.row(),'id':f'pane-{i}'});model.appearance({'appearance':appearance});models.append(model)
        self.assertEqual(len(cache.attachment_models),48)
        replacement=self.root/'replacement.m2';replacement.write_bytes(f.m2())
        models[0].appearance({'appearance':{'attachments':[{'id':slot,'model':str(replacement)} for slot in slots]}})
        self.assertEqual(len(cache.attachment_models),48);self.assertTrue(all(child.path==replacement for child in models[0].children.values()))
        with self.assertRaisesRegex(ValueError,'Live model capacity'):cache.live_model(self.body,{**self.row(),'id':'ninth'})
        cache.close();self.assertEqual(cache.live_bytes,0);self.assertFalse(cache.attachment_models)

    def test_outfit_atlas_memory_is_reserved_before_attachment_commit(self):
        entries=f.equipment_entries();entries['GG/large.blp']=f.blp(width=512,height=512,levels=[bytes((10,10,255,255))*512*512])
        data=self.root/'Data';data.mkdir();(data/'patch.MPQ').write_bytes(f.mpq(entries=entries))
        body=bytearray(f.attachment_m2());tex=struct.unpack_from('<I',body,0x60)[0];struct.pack_into('<I',body,tex,1);struct.pack_into('<II',body,tex+8,0,0);self.body.write_bytes(body)
        cache=self.cache();cache.mount_chain(data);model=cache.live_model(self.body,self.row());model.appearance({'appearance':{'character':{'race':1}}})
        original=model.character_key;pixels=bytes(model.batches[0].tex.textureData());used=cache.live_bytes
        growth=(512*512-256*256)*4*3 # CPU atlas plus retained texture CPU/GPU budget.
        cache.bytes=64*1024*1024-used-growth-100
        with self.assertRaisesRegex(ValueError,'memory capacity'):model.appearance({'appearance':{'character':{'race':1,'baked':'GG/large.blp','helmet':80}}})
        self.assertEqual(model.character_key,original);self.assertFalse(model.children);self.assertEqual(cache.live_bytes,used)
        self.assertEqual(bytes(model.batches[0].tex.textureData()),pixels)
        cache.bytes=0;model.appearance({'appearance':{'character':{'race':1,'baked':'GG/large.blp','helmet':80}}})
        self.assertEqual(set(model.children),{11});cache.close();self.assertEqual(cache.live_bytes,0)
