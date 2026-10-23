"""Integration against original readers, live native workers and retained Qt buffers."""
import math,struct,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtGui import QGuiApplication
from backend.game_engine_adapter_formats import NativeFormats,AssetCache,PROJECT
from backend.game_engine_adapter_ui import GgEngineUI
from backend.game_engine_presentation import Presentation
from backend.game_engine_adapter_world import unit_asset,environment
from tools.world import engine_format_fixtures as f

class CharacterEffects(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QGuiApplication.instance() or QGuiApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=PROJECT/'qml');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.data=self.root/'Data';self.data.mkdir()
        (self.data/'patch.MPQ').write_bytes(f.mpq(entries=f.character_entries()))
        (self.root/'gold.blp').write_bytes(f.blp())
        self.reader=NativeFormats(self.root);self.addCleanup(self.reader.close)
        self.reader.request('mount_chain',path=str(self.data))
    def character(self,**options):
        return NativeFormats._unpack(self.reader.request('character',character={'race':1,**options}))
    def model(self,**options):
        path=self.root/'particle.m2';path.write_bytes(f.particle_m2(**options));return path
    def pose(self,path,clock,instance='a',**options):
        return self.reader.pose(path,instance=instance,anim_id=7,cursor_ms=clock,clock_ms=clock,**options)
    def test_original_atlas_alpha_over_and_equipment_tile(self):
        meta,data=self.character()
        self.assertEqual((meta['width'],meta['height'],len(data)),(256,256,256*256*4))
        self.assertEqual(data[:4],bytes((120,80,40,255)))
        self.assertEqual(data[(200*256)*4:(200*256)*4+4],bytes((160,40,20,255)))
        meta,data=self.character(equipment=[73,0,0,0,0,0,0,0])
        self.assertEqual(data[128*4:128*4+4],bytes((0,255,0,255)))
        self.assertEqual(meta['missing_candidates'],[]) # sex-specific fallback is valid
        self.assertIn(0,meta['geosets']);self.assertEqual(meta['hair'],'GG/hair.blp')
        meta,_=self.character(cloak=74);self.assertEqual(meta['object'],'Item\\ObjectComponents\\Cape\\GG_Cape.blp')
    def test_character_variants_geosets_and_unknown_display(self):
        base,_=self.character();hair,_=self.character(hair_style=1)
        self.assertIn(1,base['geosets']);self.assertNotIn(1,hair['geosets']);self.assertIn(2,hair['geosets'])
        _,blue=self.character(skin=1);self.assertEqual(blue[:4],bytes((16,24,255,255)))
        for options in ({'race':0},{'sex':2},{'race':256},{'equipment':[0]},{'equipment':[999]*8}):
            with self.subTest(options=options),self.assertRaises(ValueError):self.character(**options)
        self.assertEqual(self.reader.request('ping'),{'abi':1})
    def test_character_requires_catalog_and_bounded_pixels(self):
        (self.data/'patch.MPQ').write_bytes(f.mpq(entries={'DBFilesClient/CharSections.dbc':b'bad'}))
        self.reader.request('mount_chain',path=str(self.data))
        with self.assertRaises(ValueError):self.character()
        rows=f.character_entries();rows['GG/skin.blp']=f.blp(width=65536,height=65536,levels=[b'bad'])
        (self.data/'patch.MPQ').write_bytes(f.mpq(entries=rows));self.reader.request('mount_chain',path=str(self.data))
        with self.assertRaisesRegex(ValueError,'pixel capacity'):self.character()
    def test_live_character_composition_retains_texture_and_visibility(self):
        path=self.root/'body.m2';data=bytearray(f.animated_m2());tex=struct.unpack_from('<I',data,0x60)[0]
        struct.pack_into('<I',data,tex,1);struct.pack_into('<II',data,tex+8,0,0)
        skin=struct.unpack_from('<I',data,80)[0];section=struct.unpack_from('<I',data,skin+28)[0];struct.pack_into('<H',data,section,1)
        path.write_bytes(data);cache=AssetCache();self.addCleanup(cache.close);cache.mount_chain(self.data)
        a=cache.live_model(path,{'id':'a'});b=cache.live_model(path,{'id':'b'});batch=a.batches[0];geometry=batch.geo;texture=batch.tex
        a.appearance({'appearance':{'character':{'race':1}}});b.appearance({'appearance':{'character':{'race':1,'skin':1}}})
        self.assertEqual(bytes(texture.textureData())[:4],bytes((120,80,40,255)));self.assertEqual(bytes(b.batches[0].tex.textureData())[:4],bytes((16,24,255,255)))
        memory=cache.live_bytes;a.appearance({'appearance':{'character':{'race':1}}});self.assertEqual(cache.live_bytes,memory)
        with self.assertRaises(ValueError):a.appearance({'appearance':{'character':{'race':1,'skin':1},'body':'/etc/passwd'}})
        self.assertEqual(a.character_key,'{"race":1}');self.assertEqual(bytes(texture.textureData())[:4],bytes((120,80,40,255)))
        a.appearance({'appearance':{'character':{'race':1,'hair_style':1}}});self.assertFalse(batch.row['visible'])
        a.appearance({});self.assertTrue(batch.row['visible']);self.assertEqual(bytes(texture.textureData())[:4],b'\xff'*4)
        self.assertIs(batch.geo,geometry);self.assertIs(batch.tex,texture);cache.close();self.assertEqual(cache.live_bytes,0)
    def test_particles_spawn_age_colour_and_expire(self):
        path=self.model();self.reader.decode(path,runtime=True,instance='a',clock_ms=0,anim_id=7)
        meta,data=self.pose(path,250);effects=meta['effects'];self.assertEqual(effects['live_particles'],5)
        row=effects['rows'][0];self.assertEqual((row['stride'],row['vertices'],len(row['indices'])),(48,20,30))
        values=struct.unpack_from('<12f',data,row['offset']);self.assertTrue(all(math.isfinite(x) for x in values));self.assertGreater(values[11],0)
        self.assertEqual(effects['limitations'],[])
        self.pose(path,1000);meta,_=self.pose(path,999);self.assertTrue(meta['effects']['reset']);self.assertEqual(meta['effects']['live_particles'],0)
    def test_independent_instances_and_density_scaling(self):
        path=self.model(rate=100);self.reader.decode(path,runtime=True,instance='a',clock_ms=0,anim_id=7)
        self.pose(path,0,instance='b');a,_=self.pose(path,250);b,_=self.pose(path,250,instance='b',particle_density=.33)
        self.assertEqual(a['effects']['live_particles'],25);self.assertEqual(b['effects']['live_particles'],8)
        again,_=self.pose(path,250);self.assertEqual(again['effects']['live_particles'],25)
        for density in (-1,2):
            with self.assertRaisesRegex(ValueError,'density'):self.pose(path,250,particle_density=density)
    def test_burst_fires_once_rearms_on_new_animation_and_seek(self):
        path=self.model(flags=0x8010,rate=12)
        meta,_=self.reader.decode(path,runtime=True,instance='a',clock_ms=0,anim_id=7)
        self.assertEqual(meta['effects']['live_particles'],12)
        meta,_=self.pose(path,250);self.assertEqual(meta['effects']['live_particles'],12)
        meta,_=self.pose(path,0);self.assertTrue(meta['effects']['reset']);self.assertEqual(meta['effects']['live_particles'],12)
    def test_density_zero_stops_births_but_existing_particles_expire(self):
        path=self.model();self.reader.decode(path,runtime=True,instance='a',clock_ms=0,anim_id=7)
        self.pose(path,250)
        for clock in (500,750,1000,1250,1500):meta,_=self.pose(path,clock,particle_density=0)
        self.assertEqual(meta['effects']['live_particles'],0);self.assertFalse(meta['effects']['rows'][0]['visible'])
    def test_loading_second_pane_does_not_reset_existing_effects(self):
        path=self.model();self.reader.decode(path,runtime=True,instance='a',clock_ms=0,anim_id=7)
        self.pose(path,250)
        self.reader.decode(path,runtime=True,instance='b',clock_ms=250,anim_id=7,cursor_ms=250)
        meta,_=self.pose(path,250);self.assertEqual(meta['effects']['live_particles'],5)
    def test_gravity_and_raw_unknown_blend_fallback(self):
        heights=[]
        for gravity in (0,3):
            path=self.model(gravity=gravity,blend=255);self.reader.decode(path,runtime=True,instance='a',clock_ms=0,anim_id=7)
            meta,data=self.pose(path,250);row=meta['effects']['rows'][0];heights.append(sum(struct.unpack_from('<3f',data,row['offset']+i*48)[1] for i in range(4))/4)
            self.assertEqual(row['blend'],0);self.reader.request('release_instance',instance='a')
        self.assertLess(heights[1],heights[0]-.01)
    def test_tail_shape_blend_and_frame_modes(self):
        for shape in (1,2):
            for blend in (0,1,2,3,4):
                path=self.model(shape=shape,blend=blend,flags=0,head_tail=2)
                self.reader.decode(path,runtime=True,instance='a',clock_ms=0,anim_id=7);meta,data=self.pose(path,250)
                row=meta['effects']['rows'][0];self.assertEqual(row['blend'],blend);self.assertEqual(row['vertices'],40)
                self.assertTrue(all(math.isfinite(x) for x in struct.unpack_from('<'+str(row['vertices']*12)+'f',data,row['offset'])))
                self.reader.request('release_instance',instance='a')
    def test_retained_effect_buffers_close_and_recover_worker(self):
        path=self.model();cache=AssetCache();self.addCleanup(cache.close)
        model=cache.live_model(path,{'id':'a','clock_ms':0,'play':{'anim_id':7}});batch=model.batches[1];geometry=batch.geo
        size=cache.live_bytes;model=cache.live_model(path,{'id':'a','clock_ms':250,'play':{'anim_id':7,'cursor_ms':250}})
        self.assertEqual(model.effect_particles,5);self.assertIs(model.batches[1].geo,geometry);self.assertEqual(cache.live_bytes,size)
        cache.reader.close();cache.live_model(path,{'id':'a','clock_ms':500,'play':{'anim_id':7,'cursor_ms':500}})
        cache.retain_live_panes([]);self.assertEqual(cache.live_bytes,0)
    def test_failed_texture_creation_releases_provisional_native_slots(self):
        cache=AssetCache();self.addCleanup(cache.close)
        for i in range(9):
            path=self.root/f'missing-{i}.m2';path.write_bytes(f.m2(texture='absent.blp'))
            with self.assertRaisesRegex(ValueError,'Model texture missing'):cache.live_model(path,{'id':f'missing-{i}'})
            self.assertEqual(cache.live_bytes,0)
        path=self.model();model=cache.live_model(path,{'id':'valid'})
        self.assertEqual(len(model.batches),2);self.assertFalse(cache.reader.closed)
    def test_caps_malformed_emitter_and_nonfinite_tracks(self):
        path=self.model(rate=1e6,life=60);self.reader.decode(path,runtime=True,instance='a',clock_ms=0,anim_id=7)
        meta,_=self.pose(path,250);self.assertEqual(meta['effects']['live_particles'],256)
        for i in range(1,8):self.pose(path,0,instance=str(i))
        with self.assertRaisesRegex(ValueError,'instance capacity'):self.pose(path,0,instance='ninth')
        self.reader.request('release_instance',instance='1');self.pose(path,0,instance='ninth')
        data=bytearray(f.particle_m2());struct.pack_into('<I',data,0x13c,17);path.write_bytes(data)
        with self.assertRaisesRegex(ValueError,'emitter capacity'):self.reader.decode(path,runtime=True)
        path.write_bytes(f.particle_m2(speed=float('nan')))
        with self.assertRaisesRegex(ValueError,'parameter'):self.reader.decode(path,runtime=True,instance='a',anim_id=7)

class WorldLuaSound(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QGuiApplication.instance() or QGuiApplication([])
    def test_target_model_uses_render_identity(self):
        snapshot={'targeting':{'selected':{'id':'npc-one','entity_id':'e-one'}},'render':{'entities':[{'id':'e-one','asset':{'source':'correct.m2'}},{'id':'npc-one','asset':{'source':'wrong.m2'}}]}}
        self.assertEqual(unit_asset(snapshot,'target')['source'],'correct.m2')
        snapshot['targeting']['selected']=None;self.assertEqual(unit_asset(snapshot,'target'),{})
    def test_actual_region_place_building_height_and_combat(self):
        snapshot={'player':{'x':10,'y':2,'z':20,'biome':'FOREST','medium':'WATER','cell_key':'cell','grounded':False},'combat_live':{'player':{'engaged_target':'npc'}}}
        with patch('backend.game_engine_adapter_world.planet.region_at',return_value={'id':'LAND','name':'GG Land'}),patch('backend.game_engine_adapter_world.planet.surface_height',return_value=0),patch('backend.game_engine_adapter_world.places.catalog',return_value={'places':[{'id':'town','name':'Town','x':10,'z':20,'clearing_m':30}]}),patch('backend.game_engine_adapter_world.places.building_index',return_value={(0,0):[{'x':10,'z':20,'yaw':0,'scale':1}]}):
            state=environment(snapshot);self.assertEqual((state['zone'],state['minimap'],state['medium']),('GG Land','Town','WATER'));self.assertTrue(state['indoors']);self.assertTrue(state['in_combat'])
            snapshot['player']['y']=20;self.assertFalse(environment(snapshot)['indoors'])
    def test_original_zone_getters_events_world_state_and_unit_combat(self):
        ui=GgEngineUI();self.addCleanup(ui.close)
        ui.execute("events={} f=CreateFrame('Frame') f:RegisterEvent('ZONE_CHANGED_NEW_AREA') f:RegisterEvent('MINIMAP_ZONE_CHANGED') f:SetScript('OnEvent',function() table.insert(events,GetZoneText()) end)")
        world={'zone':'Sandover','real_zone':'Sandover','subzone':'GG Forge','minimap':'GG Forge','medium':'WATER','indoors':True,'in_combat':True,'x':42}
        ui.publish({},True,100,100,world=world)
        self.assertEqual(ui.evaluate("return GetZoneText(),GetRealZoneText(),GetSubZoneText(),GetMinimapZoneText(),UnitAffectingCombat('player')"),['Sandover','Sandover','GG Forge','GG Forge',1])
        self.assertEqual(ui.evaluate('return getn(events),events[1],GG_GetWorldState().medium,GG_GetWorldState().indoors'),[2,'Sandover','WATER',True])
        ui.execute("local w=GG_GetWorldState() w.x=0");self.assertEqual(ui.evaluate('return GG_GetWorldState().x'),[42])
        ui.publish({},True,100,100,world=world);self.assertEqual(ui.evaluate('return getn(events)'),[2])
    def test_lua_cvars_control_actual_audio_and_effect_runtime(self):
        runtime=Presentation(device=False);self.addCleanup(runtime.close);self.assertTrue(runtime.full_ui)
        runtime.running=True;runtime._gain()
        runtime.lua.execute("SetCVar('MasterVolume',.25) SetCVar('MusicVolume',.2) SetCVar('EnableMusic',0) SetCVar('EnableAmbience',0) SetCVar('spellEffectLevel',0) SetCVar('SoundReverb',0)")
        runtime._ui_requests(runtime.lua.request('requests'))
        self.assertEqual(runtime.volumes['master'],.25);self.assertEqual(runtime.particle_density,.33);self.assertEqual(runtime.runtime_settings['EnableMusic'],'0')
        runtime.audio.stop();runtime.audio.play(4,gain=.4);values=runtime.audio.render(4096)
        self.assertGreater(max(abs(n) for n in struct.unpack('<8192f',values)),1e-4)
        runtime.lua.execute("SetCVar('MasterSoundEffects',0)");runtime._ui_requests(runtime.lua.request('requests'))
        runtime.audio.render(16384) # the existing click-free gain ramp and look-ahead buffer
        self.assertLess(max(abs(n) for n in struct.unpack('<1024f',runtime.audio.render(512))),1e-6)
        runtime.lua.execute("SetCVar('MasterVolume','nan') SetCVar('spellEffectLevel',99)");runtime._ui_requests(runtime.lua.request('requests'))
        self.assertEqual(runtime.volumes['master'],.25);self.assertEqual(runtime.particle_density,.33)
        self.assertEqual(runtime.lua.evaluate("return GetCVar('MasterVolume'),GetCVar('spellEffectLevel')"),['0.25','0'])
        runtime.setVolume('music',.6);self.assertEqual(runtime.lua.evaluate("return GetCVar('MusicVolume')"),['0.6'])
        runtime._reload_ui();self.assertEqual(runtime.lua.evaluate("return GetCVar('MasterVolume'),GetCVar('spellEffectLevel')"),['0.25','0'])
    def test_lua_character_appearance_draw_clear_and_bounds(self):
        ui=GgEngineUI();self.addCleanup(ui.close)
        ui.execute("hero=CreateFrame('Model','Hero',UIParent) hero:SetWidth(20) hero:SetHeight(20) hero:SetPoint('CENTER',UIParent,'CENTER',0,0) hero:SetModel('GG/hero.m2') GG_SetCharacterAppearance('Hero',{race=1,skin=2,equipment={73,0,0,0,0,0,0,0}})")
        row=next(r for r in ui.frames() if r.get('name')=='Hero')
        self.assertEqual(row['appearance']['character']['skin'],2);self.assertEqual(row['appearance']['character']['equipment'][0],73)
        ui.execute("GG_SetCharacterAppearance('Hero',nil)");self.assertNotIn('appearance',next(r for r in ui.frames() if r.get('name')=='Hero'))
        self.assertEqual(ui.evaluate("return pcall(function() GG_SetCharacterAppearance('Hero',{race=1,equipment={1}}) end)")[0],False)
    def test_audio_cvar_bus_switches_leave_effects_audible(self):
        runtime=Presentation(device=False);self.addCleanup(runtime.close);runtime.running=True;runtime._gain()
        if runtime.music_streams:runtime.music_streams.stop()
        for name,bus,clip in (('EnableMusic',1,7),('EnableAmbience',2,6)):
            runtime.lua.execute(f"SetCVar('{name}',1)");runtime._ui_requests(runtime.lua.request('requests'));runtime.audio.stop();runtime.audio.play(clip,bus=bus,gain=.5,loop=True)
            runtime.audio.render(16384);active=struct.unpack('<4096f',runtime.audio.render(2048));self.assertGreater(max(map(abs,active)),1e-4)
            runtime.lua.execute(f"SetCVar('{name}',0)");runtime._ui_requests(runtime.lua.request('requests'));runtime.audio.render(16384)
            quiet=struct.unpack('<4096f',runtime.audio.render(2048));self.assertLess(max(map(abs,quiet)),1e-6)

if __name__=='__main__':unittest.main()
