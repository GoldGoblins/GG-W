"""Original LightCatalog over authored DBCs, coupled to the actual world camera."""
import json,math,os,tempfile,time,unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtGui import QGuiApplication
from backend.game_engine_adapter_formats import NativeFormats,PROJECT
from backend.game_engine_adapter_streaming import WorldStream
from backend.game_engine_adapter_lighting import settings
from tools.world import engine_lighting_fixtures as light,engine_format_fixtures as a,engine_world_fixtures as f
APP=QGuiApplication.instance() or QGuiApplication([])
class Lighting(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=PROJECT/'qml');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.data=self.root/'Data';self.data.mkdir()
        (self.data/'patch.MPQ').write_bytes(a.mpq(entries=light.entries()));self.reader=NativeFormats(self.root);self.addCleanup(self.reader.close);self.reader.request('mount_chain',path=str(self.data),timeout=2)
    def sample(self,**kw):return self.reader.request('atmosphere',map_id=0,position=[0,0,0],minute=kw.pop('minute',720),**kw)
    def test_daynight_interpolates_original_color_and_scalar_bands(self):
        m=self.sample(minute=360);self.assertEqual(m['source'],'ORIGINAL_LIGHT_DBC')
        for actual,want in zip(m['ambient'],[48/255,32/255,16/255]):self.assertAlmostEqual(actual,want,places=6)
        self.assertEqual(m['fog']['far'],150);self.assertEqual(m['fog']['near'],56.25)
        self.assertAlmostEqual(sum(x*x for x in m['to_light']),1,places=5)
    def test_scene_fog_clamps_end_and_recomputes_start_for_view_distance(self):
        m=self.sample(minute=360,far_clip=100);self.assertEqual(m['fog']['far'],100);self.assertEqual(m['fog']['near'],37.5)
        for far in (-1,float('nan'),10001):
            with self.assertRaises(ValueError):self.sample(far_clip=far)
    def test_midnight_wrap_is_symmetric(self):
        self.assertEqual(self.sample(minute=360)['ambient'],self.sample(minute=1080)['ambient'])
    def test_storm_blends_every_band_between_clear_and_storm(self):
        clear=self.sample(storm_blend=0);storm=self.sample(storm_blend=1);mid=self.sample(storm_blend=.5)
        for key in ('ambient','diffuse','sun_color'):
            for a,b,c in zip(clear[key],storm[key],mid[key]):self.assertAlmostEqual(c,(a+b)/2,places=6)
        for value in (-1,2,float('nan')):
            with self.assertRaises(ValueError):self.sample(storm_blend=value)
    def test_native_cloud_tile_and_retained_Qt_geometry(self):
        packet=self.reader.request('atmosphere',map_id=0,position=[0,0,0],minute=720,clouds=True,clock_ms=0)
        metadata,data=NativeFormats._unpack(packet);self.assertEqual(len(data),65536);self.assertEqual(metadata['clouds']['width'],128)
    def test_storm_underwater_and_ghost_use_authored_slots(self):
        for state,p in (({},1),({'submersion':'WATER'},2),({'stormy':True},3),({'stormy':True,'submersion':'WATER'},4),({'ghost':True,'stormy':True,'submersion':'WATER'},5)):
            with self.subTest(state=state):self.assertAlmostEqual(self.sample(**state)['diffuse'][1],32*p/255,places=5)
    def test_magma_and_slime_replace_the_entire_blend(self):
        self.assertAlmostEqual(self.sample(submersion='MAGMA',ghost=True)['diffuse'][1],32*7/255,places=5)
        self.assertAlmostEqual(self.sample(submersion='SLIME')['diffuse'][1],32*6/255,places=5)
    def test_river_and_ocean_swatch_alphas_are_original_params(self):
        m=self.sample()
        for actual,want in zip(m['water_river_alpha'],[.25,.8]):self.assertAlmostEqual(actual,want,places=5)
        for actual,want in zip(m['water_ocean_alpha'],[.6,1]):self.assertAlmostEqual(actual,want,places=5)
    def test_SIDN_tracks_night_and_dawn(self):
        for minute,want in ((0,1),(360,1),(390,.5),(420,0),(720,0),(1230,0),(1260,.5),(1290,1)):
            self.assertAlmostEqual(self.sample(minute=minute)['sidn'],want,places=4)
    def test_invalid_time_position_state_rejected(self):
        for kw in ({'minute':-1},{'minute':1440},{'submersion':'INVALID'}):
            with self.assertRaises(ValueError):self.sample(**kw)
    def test_missing_tables_fail_without_fabricating_authored_lighting(self):
        other=self.root/'empty';other.mkdir();(other/'patch.MPQ').write_bytes(a.mpq(entries={'DBFilesClient/Light.dbc':light.entries()['DBFilesClient/Light.dbc']}));self.reader.request('mount_chain',path=str(other),timeout=2)
        with self.assertRaises(ValueError):self.sample()
    def test_world_camera_submersion_and_clock_reach_the_native_catalog(self):
        manifest=f.make(self.root);cfg=json.loads(manifest.read_text());cfg.update(wmos=[],lighting={'map_id':0,'minute':360,'time_scale':60},archive_directory=str(self.data));manifest.write_text(json.dumps(cfg))
        s=WorldStream();self.addCleanup(s.close);s.configure(str(manifest));end=time.monotonic()+5
        while time.monotonic()<end:
            s.update(-2,2.65,20)
            if s.pages and s.pending is None:break
            time.sleep(.005)
        s.setView({'eye':[-2,5,20],'forward':[1,0,0],'up':[0,1,0],'fov':60,'aspect':1,'near':.1,'far':100});s.advance(.5)
        end=time.monotonic()+5
        while s.light.frames<1 and time.monotonic()<end:s.update(*s.position);s.light.advance();time.sleep(.005)
        self.assertEqual(s.light.error,'');self.assertEqual(s.lighting['source'],'ORIGINAL_LIGHT_DBC');self.assertAlmostEqual(s.lighting['minute'],360.5)
        s.close();self.assertEqual(s.bytes,0)
    def test_manifest_settings_validate_before_runtime_queries(self):
        for value in ({'map_id':True},{'map_id':-1},{'map_id':0,'minute':1440},{'map_id':0,'time_scale':float('nan')},{'map_id':0,'stormy':'yes'}):
            with self.assertRaises(ValueError):settings(value)
if __name__=='__main__':unittest.main()
