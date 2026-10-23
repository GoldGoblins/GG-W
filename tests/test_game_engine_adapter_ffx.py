"""Original FFX switches, byte LUT and actual local camera/Lua integration."""
import itertools,json,os,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QObject,Signal
from PySide6.QtGui import QGuiApplication
from backend.game_engine_adapter_ffx import state,wave_bytes,wave_for
from backend.game_engine_adapter_streaming import WorldStream
from backend.game_engine_presentation import Presentation
from tools.world import engine_world_fixtures as fixtures
APP=QGuiApplication.instance() or QGuiApplication([])
PROJECT=Path(__file__).resolve().parents[1]

class Bridge(QObject):
    snapshotPublished=Signal(object)

class Ffx(unittest.TestCase):
    def test_original_pass_slot_and_all_switch_combinations(self):
        for master,glow,death,ghost in itertools.product((False,True),repeat=4):
            with self.subTest(master=master,glow=glow,death=death,ghost=ghost):
                enabled=master and (death if ghost else glow)
                result=state({'glow':.4,'ghost':ghost,'submersion':'WATER'},
                             {'ffx':master,'ffxGlow':glow,'ffxDeath':death},75)
                self.assertEqual(result['gain'],.4 if enabled else 0)
                self.assertEqual(result['ghost'],ghost and enabled)
                self.assertEqual(result['haze'],.75 if enabled and not ghost else 0)
                self.assertEqual(result['wave'],enabled and not ghost)
    def test_haze_floor_all_liquids_and_finite_inputs(self):
        self.assertEqual(state({}, {})['gain'],.5)
        self.assertEqual(state({'submersion':'DRY'}, {},30)['haze'],.3)
        for kind in ('WATER','OCEAN','MAGMA','SLIME','RAPIDS'):
            self.assertEqual(state({'submersion':kind}, {},0)['haze'],84/255)
            self.assertEqual(state({'submersion':kind}, {},150)['haze'],1)
        for field in ('glow','drunk'):
            for bad in (float('nan'),float('inf'),-float('inf')):
                with self.assertRaises(ValueError):state({'glow':bad} if field=='glow' else {},{},bad if field=='drunk' else 0)
        for bad in (-.1,4.1):
            with self.assertRaises(ValueError):state({'glow':bad},{})
    def test_lut_raw_channels_truncation_and_reused_qt_texture(self):
        pixels=wave_bytes();self.assertEqual(len(pixels),128*128*4)
        def at(x,y):return tuple(pixels[(y*128+x)*4:(y*128+x+1)*4])
        self.assertEqual(at(0,0),(127,127,0,255))
        self.assertEqual(at(32,96),(255,0,0,255))
        self.assertEqual(at(96,32),(0,255,0,255))
        self.assertTrue(all(at(x,17)[1]==at(0,17)[1] for x in range(128)))
        owner=QObject();texture=wave_for(owner)
        self.assertIs(wave_for(owner),texture);self.assertIs(texture.parent(),owner)
        self.assertEqual(bytes(texture.textureData()),pixels)
    def test_original_lua_cvars_control_world_effect_and_survive_ui_reload(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'XDG_STATE_HOME':directory}):
            self.bridge=Bridge();bridge=self.bridge
            world=WorldStream(bridge);self.addCleanup(world.close)
            bridge._engine_world_stream=world
            presentation=Presentation(bridge,device=False);self.addCleanup(presentation.close)
            bridge._game_presentation=presentation
            world.light.state={'glow':.4,'ghost':True};self.assertTrue(world.ffx['ghost'])
            changes=[];world.lightingChanged.connect(lambda:changes.append(world.ffx))
            presentation.lua.execute("SetCVar('ffxDeath',0)")
            presentation._ui_requests(presentation.lua.request('requests'))
            self.assertEqual(world.ffx['gain'],0);self.assertFalse(world.ffx['ghost'])
            self.assertTrue(changes)
            world.light.state={'glow':.4,'ghost':False}
            self.assertEqual(world.ffx['gain'],.4)
            presentation.lua.execute("SetCVar('ffxGlow',0);SetCVar('ffx',0)")
            presentation._ui_requests(presentation.lua.request('requests'))
            self.assertEqual(world.ffx['gain'],0)
            presentation._reload_ui()
            self.assertEqual(presentation.lua.evaluate("return GetCVar('ffx'),GetCVar('ffxGlow'),GetCVar('ffxDeath')"),['0','0','0'])
            presentation.lua.execute("SetCVar('ffx',1);SetCVar('ffxGlow',1);SetCVar('ffxDeath',2)")
            presentation._ui_requests(presentation.lua.request('requests'))
            self.assertEqual(world.ffx['gain'],.4)
            self.assertEqual(presentation.lua.evaluate("return GetCVar('ffxDeath')"),['0'])
            presentation.close()
    def test_actual_camera_submersion_without_original_lighting_database(self):
        with tempfile.TemporaryDirectory(dir=PROJECT/'qml') as directory:
            root=Path(directory);manifest=fixtures.make(root)
            (root/'Test_32_32.adt').write_bytes(fixtures.terrain(liquid={}))
            cfg=json.loads(manifest.read_text());cfg['liquids']={'STILL':{'frames':['white.blp']}}
            manifest.write_text(json.dumps(cfg))
            world=WorldStream();self.addCleanup(world.close)
            world.configure(str(manifest));deadline=time.monotonic()+10
            while len(world.pages)!=2 or world.pending is not None:
                world.update(-2,2.65,20)
                self.assertFalse(world.last_error,world.last_error)
                self.assertLess(time.monotonic(),deadline,'fixture did not load')
                time.sleep(.005)
            self.assertIsNone(world.light.config)
            changes=[];world.lightingChanged.connect(lambda:changes.append(world.ffx))
            def camera(y):world.setView({'eye':[-2,y,2],'forward':[0,0,-1],'up':[0,1,0],'near':.1,'far':100,'fov':60,'aspect':1})
            camera(4);self.assertTrue(world.ffx['wave']);self.assertEqual(world.ffx['haze'],84/255)
            camera(6);self.assertFalse(world.ffx['wave']);self.assertEqual(world.ffx['haze'],0)
            self.assertEqual(len(changes),2)
            camera(4);world.clearView();self.assertFalse(world.ffx['wave'])
            camera(4);world.close();self.assertFalse(world.ffx['wave'])

if __name__=='__main__':unittest.main()
