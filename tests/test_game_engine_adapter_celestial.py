"""Original star corpus/fallback and celestial horizon, cloud and weather laws."""
import math,os,struct,tempfile,unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtGui import QGuiApplication
from backend.game_engine_adapter_formats import PROJECT,NativeFormats
from backend.game_engine_adapter_celestial import radial
from tools.world import engine_format_fixtures as a,engine_lighting_fixtures as l
APP=QGuiApplication.instance() or QGuiApplication([])
class Celestial(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=PROJECT/'qml');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);data=self.root/'Data';data.mkdir();(data/'patch.MPQ').write_bytes(a.mpq(entries=l.entries()))
        self.reader=NativeFormats(self.root);self.addCleanup(self.reader.close);self.reader.request('mount_chain',path=str(data))
    def sample(self,clock=0,**kwargs):return NativeFormats._unpack(self.reader.request('atmosphere',map_id=0,position=[0,0,0],minute=720,clock_ms=clock,clouds=True,**kwargs))[0]
    def test_original_assetless_mesh_is_350_stable_stars(self):
        m,data=NativeFormats._unpack(self.reader.request('sky_stars'));self.assertFalse(m['authored']);self.assertEqual(m['rows'][0]['vertices'],1400);self.assertEqual(len(m['rows'][0]['indices']),2100)
        values=[struct.unpack_from('<3f',data,i*32) for i in range(1400)];self.assertTrue(all(p[1]>0 for p in values));self.assertTrue(all(abs(math.sqrt(sum(v*v for v in p))-1)<.00002 for p in values))
        _,again=NativeFormats._unpack(self.reader.request('sky_stars'));self.assertEqual(data,again)
    def test_authored_star_model_is_normalized_without_fake_dot_geometry(self):
        source=self.root/'Stars.m2';source.write_bytes(a.m2());m,data=NativeFormats._unpack(self.reader.request('sky_stars',path=str(source)))
        self.assertTrue(m['authored']);self.assertEqual(m['rows'][0]['vertices'],3);self.assertAlmostEqual(max(math.sqrt(sum(v*v for v in struct.unpack_from('<3f',data,i*32))) for i in range(3)),1,places=6)
    def test_original_disc_basis_span_and_unwritten_moon02_alpha(self):
        state=self.sample();sprites={s['name']:s for s in state['celestial_sprites']};self.assertEqual(set(sprites),{'sun','sun_glare','moon','moon_glare','moon02'})
        self.assertEqual(sprites['moon02']['alpha'],0);self.assertEqual(sprites['moon02']['tint'],[0,0,0])
        for sprite in sprites.values():
            for vector in ('direction','right','up'):self.assertAlmostEqual(sum(v*v for v in sprite[vector]),1,places=5)
            self.assertAlmostEqual(sum(a*b for a,b in zip(sprite['direction'],sprite['right'])),0,places=5)
        self.assertLess(sprites['sun']['span'][0],sprites['sun']['span'][1])
    def test_weather_seed_cloud_occlusion_and_camera_depth_are_applied(self):
        state=self.sample(storm_blend=.4,submersion_depth=2);sprites={s['name']:s for s in state['celestial_sprites']}
        self.assertAlmostEqual(sprites['sun']['alpha'],math.floor(255*.6)/255,places=6)
        clouds=state['clouds'];self.assertAlmostEqual(clouds['occlusion_sun'],1-clouds['coverage_sun'],places=5)
        r=clouds['coverage_moon'];self.assertAlmostEqual(clouds['occlusion_moon'],1-abs(2*(r-.5)),places=5)
        with self.assertRaisesRegex(ValueError,'submersion depth'):self.sample(submersion_depth=-1)
        with self.assertRaisesRegex(ValueError,'flare visibility'):self.sample(flare_visibility=[2,0])
    def test_original_radial_fallback_has_the_original_alpha_edge(self):
        for size,core,edge in ((128,.55,.95),(64,0,1),(32,.2,1)):
            im=radial(size,core,edge);self.assertEqual(im.pixelColor(size//2,size//2).red(),255);self.assertEqual(im.pixelColor(0,0).alpha(),0);self.assertGreater(im.pixelColor(size//2,size//2).alpha(),250)
if __name__=='__main__':unittest.main()
