"""Authored DBC/MPQ joins and real entity events through the native clip mixer."""
from pathlib import Path
import array,json,os,struct,sys,tempfile,time,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
from PySide6.QtGui import QGuiApplication
from tools.world.engine_audio_fixtures import entries,signal
from tools.world.engine_format_fixtures import mpq,table_dbc,event_m2,blp
from backend.game_engine_adapter_formats import NativeFormats,AssetCache
from backend.game_engine_native_presentation import Audio
from backend.game_engine_audio_stream import MusicStreams
from backend.game_engine_audio_short import ShortSounds
from backend.game_engine_adapter_audio import ZoneAudio
from backend.game_engine_adapter_entity_audio import EntityAudio as EntityAudioFeed
from backend.game_engine_adapter_streaming import WorldStream,Surface,ground_effect_at
from tools.world import engine_world_fixtures as world_fixtures
APP=QGuiApplication.instance() or QGuiApplication([])

def entity_entries():
    files=entries();kits=[]
    for ident in range(160,176):
        row=[0]*29;row[0]=ident;row[1]=2;row[2]=f'GG entity {ident}';row[3]=f'{ident}.wav';row[13]=1;row[23]='GG/Audio';row[24]=.7;row[26]=1.;row[27]=60.
        if ident==175:row[25]=0x200
        kits.append(row);files[f'GG/Audio/{ident}.wav']=signal(300+50*(ident-160),seconds=.09)
    # Keep zone beds/music plus distinct entity kits in the original table.
    for ident,name,kind in ((101,'Day Music',28),(102,'Night Music',28),(103,'Intro',28),(110,'Day Bed',50),(111,'Night Bed',50),(130,'Ghost (DONOTRENAME)',50),(131,'Underwater (DONOTRENAME)',50)):
        row=[0]*29;row[0]=ident;row[1]=kind;row[2]=name;row[3]=f'{ident}.wav';row[13]=1;row[23]='GG/Audio';row[24]=.2;row[26]=1.;row[27]=60.;kits.append(row)
    voice=[0]*30;voice[0]=1;voice[1:9]=[160,161,162,163,164,165,166,167];voice[9]=3;voice[10]=168;voice[11]=169;voice[12]=170;voice[13]=171
    voice[14:18]=[160,161,162,163];voice[18:22]=[164,165,166,167];voice[23]=175;voice[24]=2;voice[25:30]=[160,161,162,163,164]
    override=voice.copy();override[0]=2;override[6]=174;override[9]=0
    model=[0]*16;model[0]=10;model[13]=1
    fallback=[0]*12;fallback[0]=100;fallback[1]=10
    direct=fallback.copy();direct[0]=101;direct[2]=2
    empty=fallback.copy();empty[0]=102;empty[1]=999
    files.update({
        'DBFilesClient/SoundEntries.dbc':table_dbc(kits,29),
        'DBFilesClient/CreatureSoundData.dbc':table_dbc([voice,override],30),
        'DBFilesClient/CreatureModelData.dbc':table_dbc([model],16),
        'DBFilesClient/CreatureDisplayInfo.dbc':table_dbc([fallback,direct,empty],12),
        'DBFilesClient/GameObjectDisplayInfo.dbc':table_dbc([[200,'GG/chest.mdx',0,160,175,161,162,163,164,165,166,167],[201,'GG/silent.mdx']+[0]*10],12),
        'DBFilesClient/GroundEffectTexture.dbc':table_dbc([[900,0,0,0,0,0,4]],7),
        'DBFilesClient/TerrainType.dbc':table_dbc([[4,'GG snow',0,0,8,1],[10,'GG none',0,0,0,0]],6),
        'DBFilesClient/FootstepTerrainLookup.dbc':table_dbc([[1,3,8,171,172]],5),
        'DBFilesClient/Material.dbc':table_dbc([[1,0,173],[2,3,174],[3,4,0]],3),
        'DBFilesClient/WeaponSwingSounds2.dbc':table_dbc([[1,0,0,160],[2,0,1,161],[3,1,0,162]],4),
        'DBFilesClient/WeaponImpactSounds.dbc':table_dbc([[1,0,0]+[163]*10+[164]*10],23),
    })
    return files

class EntityAudio(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=PROJECT/'qml');self.addCleanup(self.tmp.cleanup)
        self.data=Path(self.tmp.name)/'Data';self.data.mkdir();(self.data/'model.MPQ').write_bytes(mpq(entries=entity_entries()))
        self.audio=Audio();self.addCleanup(self.audio.close);self.audio.gain(1,1,1,1,True)
        self.streams=MusicStreams(self.audio);self.addCleanup(self.streams.close)
        self.short=ShortSounds(self.audio);self.addCleanup(self.short.close)
        self.now=0.;self.zone=ZoneAudio(self.streams,self.data,clock=lambda:self.now,short_sounds=self.short);self.addCleanup(self.zone.close)
        self.state={'area_id':8,'minute':720,'indoors':False,'underwater':False,'ghost':False}
        self.context={'kind':'creature','display_id':100,'position':(0.,0.,-2.)}
    def step(self,n=1):
        total=0.
        for _ in range(n):
            self.now+=.01;self.zone.update(**self.state);self.streams.pump();self.short.pump()
            values=array.array('f');values.frombytes(self.audio.render(480));total+=sum(x*x for x in values);time.sleep(.001)
        return total
    def until(self,predicate,n=750):
        for _ in range(n):
            self.step()
            if predicate():return
        self.fail('Entity audio did not complete: '+str(self.zone.diagnostics()))
    def reader(self):
        reader=NativeFormats();self.addCleanup(reader.close);reader.request('mount_chain',path=str(self.data));return reader
    def loaded(self,ident):return any(Path(key[0]).name==f'{ident}.wav' for key in self.short.loaded)
    def emit(self,event,**context):return self.zone.entity_event('entity:test',event,{**self.context,**context})
    def specs(self,event,**context):
        # Catalog and extraction ownership stays on the one IO worker, even
        # while an already playing bed is being prepared.
        return self.zone.pool.submit(self.zone.assets.entity_effect,{'entity_event':event,'context':{**self.context,**context}},set()).result(timeout=15)
    def test_original_voice_override_model_fallback_and_absent_rows(self):
        reader=self.reader();fallback=reader.request('creature_voice',display_id=100);direct=reader.request('creature_voice',display_id=101)
        self.assertEqual((fallback['death'],fallback['exertion'],fallback['footstep_class']),(165,[160,161],3))
        self.assertEqual((direct['death'],direct['footstep_class']),(174,0))
        self.assertEqual(reader.request('creature_voice',model_id=10)['death'],165)
        self.assertFalse(reader.request('creature_voice',display_id=102)['found'])
        self.assertFalse(reader.request('creature_voice',display_id=0xffffffff)['found'])
    def test_gameobject_columns_and_zero_rows_remain_silent(self):
        reader=self.reader();row=reader.request('gameobject_audio',display_id=200)
        self.assertEqual(row['slots'],[0,160,175,161,162,163,164,165,166,167])
        self.assertFalse(reader.request('gameobject_audio',display_id=201)['found'])
    def test_ground_effect_and_wmo_surface_resolve_same_actual_terrain(self):
        reader=self.reader();a=reader.request('footstep_audio',footstep_class=3,ground_effect_id=900);b=reader.request('footstep_audio',footstep_class=3,terrain_id=4)
        self.assertEqual(a,b);self.assertEqual((a['dry'],a['splash'],a['footprints']),(171,172,True))
        self.assertEqual(reader.request('footstep_audio',footstep_class=3)['dry'],0)
        self.assertEqual(reader.request('footstep_audio',footstep_class=0,terrain_id=4)['dry'],0)
        self.assertFalse(reader.request('footstep_audio',footstep_class=3,terrain_id=10)['found'])
    def test_material_and_weapon_original_joins_preserve_silence(self):
        reader=self.reader();self.assertEqual(reader.request('material_audio',material_id=2),{'material_id':2,'foley':174,'metal':True,'impact_slot':2})
        self.assertEqual(reader.request('combat_audio',kind='swing',swing_type=0,critical=True)['kit'],161)
        self.assertEqual(reader.request('combat_audio',kind='swing',swing_type=3,critical=False)['kit'],0)
        # The original impact catalog intentionally uses the other material row
        # when that subclass exists in only one material.
        self.assertEqual(reader.request('combat_audio',kind='impact',weapon_subclass=0,metal=True,target_slot=8,critical=True)['kit'],164)
    def test_native_rejects_invalid_ids_booleans_ambiguous_surfaces_and_slots(self):
        reader=self.reader()
        for op,kw in [('creature_voice',{'display_id':True}),('creature_voice',{'display_id':-1}),('creature_voice',{'display_id':100,'model_id':10}),('footstep_audio',{'footstep_class':3,'terrain_id':4,'ground_effect_id':900}),('combat_audio',{'kind':'impact','critical':False,'weapon_subclass':0,'metal':True,'target_slot':10})]:
            with self.assertRaises(ValueError):reader.request(op,**kw)
    def test_death_damage_pet_and_custom_animation_reach_real_decoder(self):
        self.assertTrue(self.emit('death'));self.until(lambda:self.loaded(165));self.assertFalse(self.short.errors)
        self.zone.release_model('entity:test');self.assertTrue(self.emit('injury',critical=True));self.until(lambda:self.loaded(163))
        self.zone.release_model('entity:test');self.assertTrue(self.emit('pet_order'));self.until(lambda:self.loaded(163))
        self.zone.release_model('entity:test');self.assertTrue(self.zone.model_events('world:actor',{'keys':[{'tag':'$AH2','data':0,'position':[0,0,-2]}]},self.context));self.until(lambda:self.loaded(166))
    def test_wading_uses_splash_and_foley_while_swimming_has_foley_only(self):
        self.assertTrue(self.emit('$FSD',terrain_id=4,water_depth=.5,collision_height=2.,material_id=1));self.until(lambda:self.loaded(172) and self.loaded(173))
        self.assertFalse(self.loaded(171));self.zone.release_model('entity:test')
        specs=self.specs('footstep',terrain_id=4,water_depth=2.,collision_height=2.,material_id=1)
        self.assertEqual([r['channel'] for r in specs],['foley'])
    def test_class_zero_still_rustles_and_state_gates_mute_every_step(self):
        specs=self.specs('footstep',display_id=101,terrain_id=4,material_id=1)
        self.assertEqual([r['channel'] for r in specs],['foley'])
        for state in ('ghost','stealth','hover'):
            self.assertEqual(self.specs('footstep',terrain_id=4,material_id=1,**{state:True}),[])
    def test_missing_surface_is_silent_without_default_character_footstep(self):
        self.assertTrue(self.emit('footstep'));self.until(lambda:self.zone.catalog is not None and self.zone.future is None and not self.zone.sound_queue)
        self.assertFalse(self.loaded(171));self.assertFalse(self.loaded(172));self.assertEqual(self.zone.errors,[])
    def test_gameobject_tags_use_actual_display_and_share_existing_loop_pool(self):
        c={'kind':'gameobject','display_id':200,'position':(0.,0.,-2.)}
        self.assertTrue(self.zone.model_events('world:chest',{'keys':[{'tag':'$GO1','data':999999,'position':[0,0,-2]}]},c));self.until(lambda:self.loaded(160))
        self.assertTrue(self.zone.entity_event('world:chest','body_loop',c));self.until(lambda:self.zone.emitters.diagnostics()['owners']==1)
        self.until(lambda:self.loaded(175));self.assertEqual(self.zone.emitters.diagnostics()['kits'],1)
        self.assertTrue(self.zone.entity_event('world:chest','close',c));self.assertEqual(self.zone.emitters.diagnostics()['owners'],0)
        self.zone.release_model('world:chest');self.assertEqual(self.zone.emitters.diagnostics()['owners'],0)
    def test_owner_removal_invalidates_queue_future_and_decode(self):
        self.assertTrue(self.emit('death'));self.zone.release_model('entity:test');self.assertFalse(self.zone.sound_queue)
        self.assertTrue(self.emit('death'));self.until(lambda:self.zone.job and self.zone.job[0]=='entity');self.zone.release_model('entity:test')
        self.until(lambda:self.zone.future is None);self.assertFalse(self.loaded(165))
        self.assertTrue(self.emit('death'));self.until(lambda:self.short.has(('entity','entity:test','vocal')))
        self.zone.release_model('entity:test');self.assertFalse(self.short.has(('entity','entity:test','vocal')))
    def test_combat_whoosh_and_material_impact_use_same_mixer(self):
        self.assertTrue(self.emit('swing',swing_type=0,critical=True));self.until(lambda:self.loaded(161))
        self.assertTrue(self.emit('impact',weapon_subclass=0,metal=True,target_slot=8,critical=False));self.until(lambda:self.loaded(163))
        self.assertFalse(self.short.errors)
    def test_invalid_context_and_request_capacity_are_bounded(self):
        for event,context in [('injury',{'display_id':True}),('footstep',{'terrain_id':4,'ground_effect_id':900}),('death',{'position':(float('nan'),0,0)}),('swing',{}),('impact',{'weapon_subclass':0,'metal':True,'target_slot':11}),('death',{'ghost':1}),('not_real',{})]:
            self.assertFalse(self.emit(event,**context))
        for _ in range(64):self.assertTrue(self.emit('injury'))
        self.assertFalse(self.emit('injury'));self.assertEqual(len(self.zone.sound_queue),64)
    def test_committed_death_cancels_a_pending_wound_and_body_loop(self):
        self.assertTrue(self.emit('body_loop'));self.until(lambda:self.zone.emitters.diagnostics()['owners']==1)
        self.assertTrue(self.emit('injury'));self.until(lambda:self.zone.job and self.zone.job[0]=='entity')
        previous=self.zone.model_owners['entity:test'];self.assertTrue(self.emit('death'))
        self.assertGreater(self.zone.model_owners['entity:test'],previous)
        self.assertEqual(self.zone.emitters.diagnostics()['owners'],0)
        self.until(lambda:self.loaded(165));self.assertFalse(self.loaded(162));self.assertFalse(self.short.errors)
    def test_stand_original_chance_global_cooldown_and_self_gate(self):
        class Draw:
            def getrandbits(self,n):return 0
        self.zone.rng=Draw();self.assertFalse(self.emit('$FDX',self_player=True));self.assertTrue(self.emit('$FDX'))
        self.assertFalse(self.zone.entity_event('entity:other','$FDX',self.context));self.now+=10.;self.assertTrue(self.emit('stand'))
    def world(self):
        root=Path(self.tmp.name)/'world';manifest=world_fixtures.make(root,wmos=False)
        stream=WorldStream();self.addCleanup(stream.close)
        return root,manifest,stream
    def settle_world(self,stream,x=-16,y=3,z=16):
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            stream.update(x,y,z)
            if stream.pages and stream.pending is None:return
            if stream.last_error:self.fail(stream.last_error)
            time.sleep(.005)
        self.fail('Authored sound surface did not load')
    def test_native_adt_cell_export_and_retained_sampler_use_predominant_layer(self):
        root,manifest,stream=self.world();data=bytearray(world_fixtures.terrain())
        layer=data.index(b'YLCM')+8
        struct.pack_into('<I',data,layer+12,900);struct.pack_into('<I',data,layer+16+12,901)
        header=data.index(b'KNCM')+8;data[header+0x40:header+0x50]=bytes((0x55,))*16
        (root/'Test_32_32.adt').write_bytes(data);stream.configure(str(manifest));self.settle_world(stream)
        row=next(iter(stream.pages.values())).metadata['rows'][0]
        self.assertEqual(row['ground_effect_ids'],[901]*64)
        self.assertEqual(ground_effect_at(row,-16,16),901);self.assertIsNone(ground_effect_at(row,1,16))
        self.assertEqual(stream.query(-16,3,16)['ground_effect_id'],901)
        self.assertIsNone(stream.query(-16,3,16)['terrain_id'])
    def test_native_wmo_sound_faces_export_real_material_and_query_overrides_adt(self):
        root,manifest,stream=self.world();wmo=bytearray(world_fixtures.root(groups=1))
        material=wmo.index(b'TMOM')+8;struct.pack_into('<I',wmo,material+0x20,4)
        (root/'sound.wmo').write_bytes(wmo);(root/'sound_000.wmo').write_bytes(world_fixtures.room())
        cfg=json.loads(manifest.read_text());cfg['wmos']=[{'model':str(root/'sound.wmo'),'position':[0,0,0],'rotation':[0,180,0]}];manifest.write_text(json.dumps(cfg))
        stream.configure(str(manifest));self.settle_world(stream,x=-8,y=3.1,z=12)
        self.until_world_pages(stream,x=-8,y=3.1,z=12,count=2)
        row=stream.query(-8,3.1,12)
        self.assertEqual(row['terrain_id'],4);self.assertIsNone(row['ground_effect_id']);self.assertTrue(row['wmo_claim'])
        self.assertLess(stream.bytes,96*1024*1024)
    def until_world_pages(self,stream,x,y,z,count):
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            stream.update(x,y,z)
            if len(stream.pages)==count and stream.pending is None:return
            if stream.last_error:self.fail(stream.last_error)
            time.sleep(.005)
        self.fail('Authored WMO sound surface did not load')
    def test_wmo_collision_visited_faces_cannot_claim_a_rendered_sound_material(self):
        root,_,_=self.world();wmo=bytearray(world_fixtures.root(groups=1));struct.pack_into('<I',wmo,wmo.index(b'TMOM')+8+0x20,4)
        (root/'mute.wmo').write_bytes(wmo);group=bytearray(world_fixtures.room());at=group.index(b'YPOM')+8
        # The sound down-ray ignores collision/visited sheets, even though the
        # unchanged walking reader still retains these actual solid triangles.
        group[at:at+12]=bytes((0x88,0))*6;(root/'mute_000.wmo').write_bytes(group)
        reader=NativeFormats(root);self.addCleanup(reader.close);metadata,blob=reader.decode(root/'mute.wmo',world_scene=True)
        self.assertEqual(metadata['audio_surfaces'],[]);self.assertTrue(metadata['collision'])
    def test_committed_host_journal_final_hit_reaches_native_death_audio_after_removal(self):
        from tests.test_game_engine_adapter_entity_audio_host import snapshot,Stream
        feed=EntityAudioFeed(clock=lambda:self.now);self.addCleanup(feed.close);s=snapshot();feed.update(self.zone,s,Stream(),scope='test-one')
        s['render']['entities']=s['render']['entities'][:1]
        s['event_journal']['events'].extend([
            {'sequence':2,'kind':'COMBAT_ATTACK','actor_id':'player','target_id':'mira','payload':{'damage':5}},
            {'sequence':3,'kind':'COMBAT_DEFEAT','actor_id':'player','target_id':'mira'},
        ])
        feed.update(self.zone,s,Stream(),scope='test-one');self.until(lambda:self.loaded(174))
        count=self.zone.entity_events;feed.update(self.zone,s,Stream(),scope='test-one');self.assertEqual(self.zone.entity_events,count)
        self.assertFalse(self.loaded(162));self.assertFalse(self.short.errors)
    def test_actual_native_model_events_are_retained_drained_and_explicit_world_consumed(self):
        root=Path(self.tmp.name);path=root/'actor.m2';path.write_bytes(event_m2(events=[('$FSD',0,0,(0,0,0),(0,250))]));(root/'gold.blp').write_bytes(blp())
        cache=AssetCache();self.addCleanup(cache.close);seen=[];cache.model_event_sink=lambda row,events:seen.append((dict(row),events))
        row={'id':'world:model-proof','play':{'anim_id':7,'cursor_ms':0},'clock_ms':0,'audio_world':True,'audio_actor_id':'player','audio_world_space':True,
             'world_anchor':[1,0,0,0,0,1,0,0,0,0,1,0,0,0,-2,1]}
        model=cache.live_model(path,row);self.assertFalse(model.take_model_events())
        row['play']['cursor_ms']=300;row['clock_ms']=300;cache.live_model(path,row)
        self.assertEqual([key['tag'] for r,e in seen for key in e['keys']],['$FSD','$FSD']);self.assertFalse(model.take_model_events())
        self.assertTrue(all(r['audio_world'] and r['audio_world_space'] for r,e in seen))
        cache.retain_live_panes(set());self.assertIsNone(seen[-1][1])
    def test_committed_spell_damage_reaches_original_voice_catalog_and_actual_mixer_without_weapon_swing(self):
        from tests.test_game_engine_adapter_entity_audio_host import snapshot,Stream
        feed=EntityAudioFeed(clock=lambda:self.now);self.addCleanup(feed.close);s=snapshot()
        s['render']['entities'][0]['asset']['swing_type']=0
        feed.update(self.zone,s,Stream(),scope='test-spell');before=self.zone.entity_events
        s['event_journal']['events'].append({'sequence':2,'kind':'COMBAT_ATTACK','actor_id':'player',
            'target_id':'mira','payload':{'kind':'SPELL','damage':5}})
        feed.update(self.zone,s,Stream(),scope='test-spell')
        self.assertEqual(self.zone.entity_events-before,2)
        self.until(lambda:self.loaded(162) and (self.loaded(160) or self.loaded(161)))
        self.assertFalse(self.short.errors)

if __name__=='__main__':unittest.main()
