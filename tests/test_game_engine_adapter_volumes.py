"""Whole-group liquids never turn FLT_MAX into a buoyancy or teleport target."""
import json,math,os,tempfile,time,unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtGui import QGuiApplication
from backend.game_engine_adapter_formats import PROJECT
from backend.game_engine_adapter_streaming import WorldStream
from backend import game_engine_mobility as mobility,game_engine_host as host
from tools.world import engine_world_fixtures as f
APP=QGuiApplication.instance() or QGuiApplication([])
class Volumes(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=PROJECT/'qml');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.manifest=f.make(self.root)
    def stream(self,kind=0,liquid=None):
        (self.root/'rooms_000.wmo').write_bytes(f.room(group_liquid=kind,liquid=liquid))
        cfg=json.loads(self.manifest.read_text());cfg['liquids']={k:{'frames':['white.blp']} for k in ('STILL','MAGMA','SLIME','OCEAN','RAPIDS')};self.manifest.write_text(json.dumps(cfg))
        s=WorldStream();self.addCleanup(s.close);s.configure(str(self.manifest));end=time.monotonic()+6
        while time.monotonic()<end:
            s.update(-8,3.65,12)
            if s.last_error:self.fail(s.last_error)
            if len(s.pages)==2 and not s.pending:return s
            time.sleep(.005)
        self.fail('Flooded world did not load')
    def test_original_flooded_kinds_without_an_MLIQ_surface(self):
        for kind,want in ((0,'STILL'),(1,'OCEAN'),(2,'MAGMA'),(3,'SLIME'),(4,'STILL'),(6,'MAGMA'),(7,'SLIME'),(8,'RAPIDS')):
            s=self.stream(kind);water=s.water_sample(-8,4,12);self.assertEqual(water['body_kind'],want);self.assertEqual(water['surface_model'],'GG_ENGINE_FLOODED_VOLUME');self.assertFalse(water['has_surface']);self.assertGreater(water['height_m'],1e30);s.close()
    def test_flooded_override_wins_over_lower_grid_and_stays_in_its_room(self):
        s=self.stream(2,liquid={'nibble':0});self.assertEqual(s.water_sample(-8,4,12)['body_kind'],'MAGMA')
        self.assertEqual(s.water_sample(-16,4,12)['body_kind'],'NONE');self.assertEqual(s.water_sample(-8,7,12)['body_kind'],'NONE')
    def test_no_liquid_and_unsupported_nibbles_remain_dry(self):
        for kind in (5,9,15):
            s=self.stream(kind);self.assertEqual(s.water_sample(-8,4,12)['body_kind'],'NONE');s.close()
    def test_submerged_controller_holds_position_and_accepts_vertical_input(self):
        y=4.;vy=0.
        def step(vertical):
            return mobility.swim_step(x=0,z=0,y=y,yaw=0,vx=0,vy=vy,vz=0,forward=0,strafe=0,turn=0,vertical=vertical,boost=False,brake=False,terrain_y=3,water_y=3.4028234663852886e38,water_depth=3.4028234663852886e38,submerged_volume=True,dt=1/60)
        for _ in range(3600):
            out=step(0);y,vy=out['y'],out['vy']
        self.assertEqual(y,4);self.assertEqual(vy,0)
        for _ in range(60):out=step(1);y,vy=out['y'],out['vy']
        self.assertGreater(y,5);self.assertLess(y,7)
    def test_actual_runtime_enters_volume_without_teleport_and_stops_at_ceiling(self):
        s=self.stream();r=host.GameEngineRuntime();self.addCleanup(r.shutdown)
        with r._lock:
            r._engine_world=s;r._x[0],r._y[0],r._z[0]=-8,3.65,12;r._movement_mode='GROUND';r._vehicle_kind='NONE';r._grapple_anchor=None;r._vx[0]=r._vy[0]=r._vz[0]=0.;r._grounded=True;r._running=True;r._input['vertical']=0
            try:
                for _ in range(60):r._tick_locked(host.FIXED_DT)
                self.assertEqual(r._movement_mode,'SWIM');self.assertLess(r._y[0],5);self.assertGreater(r._y[0],3)
                r._input['vertical']=1
                for _ in range(240):r._tick_locked(host.FIXED_DT)
                self.assertLessEqual(r._y[0],5.35);self.assertTrue(math.isfinite(r._y[0]))
            finally:r._engine_world=None
if __name__=='__main__':unittest.main()
