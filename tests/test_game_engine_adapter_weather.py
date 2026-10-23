"""Original weather through the actual native protocol, Qt tables and world lifecycle."""
import json,math,os,struct,tempfile,time,unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtGui import QGuiApplication
from PySide6.QtCore import QCoreApplication,QEvent
from backend.game_engine_adapter_formats import NativeFormats,PROJECT
from backend.game_engine_adapter_streaming import WorldStream
from backend.game_engine_adapter_weather import settings
from tools.world import engine_world_fixtures as f,engine_format_fixtures as a
APP=QGuiApplication.instance() or QGuiApplication([])
VIEW={'eye':[0,10,0],'forward':[0,0,-1],'up':[0,1,0],'fov':60}

class WeatherTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=PROJECT/'qml');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.reader=NativeFormats(self.root);self.addCleanup(self.reader.close)
    def set_weather(self,kind=1,grade=1,instant=True,now=0,quality=3):return self.reader.request('weather_set',kind=kind,grade=grade,instant=instant,now_ms=now,quality=quality)
    def frame(self,now,draw=True,view=None,player=None,revision=0):
        view=view or VIEW
        return self.reader.request('weather_frame',now_ms=now,draw=draw,view=view,player=player or view['eye'],facing=view['forward'],speed=0,collision_revision=revision,fog=[.2,.3,.4],timeout=3)
    def draw(self,state,kind):return NativeFormats._unpack(self.reader.request('weather_draw',generation=state['generation'],kind=kind,offset=0,limit=32768,timeout=3))
    def test_real_time_ramp_old_target_retarget_and_sky_leads_precipitation(self):
        self.set_weather(instant=False);zero=self.frame(0);knee=self.frame(2500);middle=self.frame(5000)
        self.assertEqual(zero['density'],0);self.assertAlmostEqual(knee['storm_blend'],.25,places=2);self.assertEqual(knee['density'],0)
        self.assertAlmostEqual(middle['storm_blend'],.5,places=2);self.assertAlmostEqual(middle['density'],1/3,places=2)
        changed=self.set_weather(0,instant=False,now=5000);self.assertEqual(changed['intensity'],1);self.assertEqual(changed['storm_blend'],1)
        final=self.frame(16000);self.assertEqual(final['density'],0);self.assertEqual(final['storm_blend'],0)
    def test_delayed_packets_cut_pending_and_hidden_simulation_continues(self):
        self.set_weather();first=self.frame(0);early=self.frame(17);self.assertEqual(early['counts'][0],0);self.assertGreater(early['pending'][0],0)
        state=early
        for n in range(2,100):state=self.frame(round(n*1000/60),draw=False)
        self.assertGreater(state['counts'][0],100);self.assertFalse(state['draw'])
        metadata,blob=self.draw(state,0);self.assertEqual(metadata['row']['instance_count'],0)
        self.set_weather(2,instant=True,now=1700);changed=self.frame(1700)
        self.assertEqual(changed['cut'],first['cut']+1);self.assertLess(changed['pending'][0],state['pending'][0]);self.assertGreater(changed['counts'][0],0)
        self.assertGreater(changed['pending'][1],0)
        drained=self.frame(2700);self.assertEqual(drained['pending'][0],0)
    def test_snow_instances_preserve_pixel_size_and_camera_relative_precision(self):
        self.set_weather(2);view={**VIEW,'eye':[5600,10,-5600]}
        for n in range(140):state=self.frame(round(n*1000/60),view=view)
        meta,blob=self.draw(state,2);row=meta['row'];self.assertEqual(row['vertices'],4);self.assertGreater(row['instance_count'],100)
        self.assertEqual(row['camera_anchor'],view['eye']);self.assertEqual(len(blob),128+80*row['instance_count'])
        for i in range(min(row['instance_count'],100)):
            m=struct.unpack_from('<20f',blob,row['instance_offset']+i*80);x,y,z=m[3],m[7],m[11]
            self.assertGreater(-z,0);self.assertLess(abs(x),150)
            half=math.sqrt(m[0]**2+m[4]**2+m[8]**2);radial=math.sqrt(x*x+y*y+z*z);px=max(1,14*max(0,min(1,1-.02*radial)))
            self.assertAlmostEqual(half,px*(-z)*math.tan(math.pi/6)/800,places=5)
        with self.assertRaisesRegex(ValueError,'stale'):self.reader.request('weather_draw',generation=state['generation']-1,kind=2,offset=0,limit=32768)
    def test_native_roof_ground_splash_uses_250_yard_oracle(self):
        path=self.root/'rooms.wmo';path.write_bytes(f.root(portal_geometry=True))
        for g in range(3):(self.root/f'rooms_{g:03}.wmo').write_bytes(f.room(g))
        self.reader.decode(path,world_scene=True,collision_key='roof');self.set_weather();view={**VIEW,'eye':[-8,4,12]}
        found=[]
        for n in range(300):
            state=self.frame(round(n*1000/60),view=view,revision=1)
            if n%30==0 and state['counts'][1]:
                meta,blob=self.draw(state,1);row=meta['row']
                for i in range(row['instance_count']):
                    m=struct.unpack_from('<20f',blob,row['instance_offset']+i*80)
                    if abs(m[7]-2.02)<.001:found.append(m)
        self.assertGreater(len(found),5,'Rain landed on the room floor instead of its roof')
    def test_native_validation_does_not_accept_nonfinite_or_replayed_clocks(self):
        self.set_weather();self.frame(1000)
        for cfg in ({'grade':float('nan')},{'quality':4},{'kind':True},{'instant':1},{'now_ms':999}):
            v={'kind':1,'grade':1,'instant':True,'now_ms':1000,'quality':3,**cfg}
            with self.assertRaises(ValueError):self.reader.request('weather_set',**v)
        with self.assertRaisesRegex(ValueError,'backwards'):self.frame(999)
        with self.assertRaises(ValueError):self.frame(1001,view={**VIEW,'forward':[0,0,0]})
        self.assertGreater(self.frame(1001)['generation'],0)
    def world(self,art=True):
        manifest=f.make(self.root,wmos=False);cfg=json.loads(manifest.read_text());cfg.update(weather={'kind':'SNOW','grade':1,'instant':True},horizon=False)
        if art:
            data=self.root/'Data';data.mkdir();(data/'patch.MPQ').write_bytes(a.mpq(entries={'textures/weather/'+name+'.blp':a.blp() for name in ('snowflake01','snowmist01','raindrop01','raindropsplash01')}));cfg['archive_directory']=str(data)
        manifest.write_text(json.dumps(cfg));stream=WorldStream();self.addCleanup(stream.close);stream.configure(str(manifest));stream.weather.timer.stop();stream.weather.clock=lambda:self.fake_time;stream.weather.epoch=0;self.fake_time=0
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            stream.update(*stream.position)
            if stream.pages and stream.pending is None:break
            time.sleep(.003)
        self.assertEqual(stream.last_error,'');stream.setView({'eye':[-8,8,16],'forward':[0,0,-1],'up':[0,1,0],'fov':60,'aspect':1,'near':.1,'far':3000});return stream
    def world_frame(self,s,n):
        self.fake_time=n/60;s.weather.advance()
        if s.weather.future:s.weather.future.result(timeout=4);s.weather.finish()
        self.assertEqual(s.weather.error,'')
    def test_actual_world_tables_retained_live_type_changes_and_close(self):
        s=self.world()
        for n in range(130):self.world_frame(s,n)
        self.assertGreater(s.weather.state['counts'][2],100);self.assertTrue(s.weatherBatches);self.assertGreater(s.weather.status()['bytes'],0)
        retained={key:(layer.batch,layer.batch.geo,layer.batch.instances) for key,layer in s.weather.layers.items()}
        for n in range(130,135):self.world_frame(s,n)
        for key,(batch,geo,instances) in retained.items():self.assertIs(s.weather.layers[key].batch,batch);self.assertIs(batch.geo,geo);self.assertIs(batch.instances,instances)
        self.assertTrue(s.setWeather({'kind':'FINE','instant':True}));self.world_frame(s,136);self.assertEqual(s.weather.state['kind'],'FINE')
        for n in range(137,230):self.world_frame(s,n)
        self.assertEqual(s.weather.state['pending'][1],0)
        s.close();QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete);self.assertEqual(s.bytes,0);self.assertFalse(s.weather.timer.isActive())
    def test_missing_original_art_reported_without_substitute_snow(self):
        s=self.world(art=False)
        for n in range(120):self.world_frame(s,n)
        self.assertGreater(s.weather.state['counts'][2],0);self.assertIn('snowflake01',s.weather.missing);self.assertFalse(s.weatherBatches)
    def test_manifest_validation(self):
        for value in ({'kind':'hail'},{'kind':True},{'grade':-1},{'grade':float('inf')},{'quality':4},{'instant':'yes'},[]):
            with self.assertRaises(ValueError):settings(value)
        self.assertEqual(settings({'kind':'snow'})['kind'],2)
    def test_wire_weather_body_drives_native_sound_and_instant_flag(self):
        from PySide6.QtCore import QByteArray
        s=self.world();pending=len(s.weather.pending)
        for payload in (b'',bytes(12),bytes(14),struct.pack('<IfIB',1,float('nan'),8533,0)):
            self.assertFalse(s.weatherPacket(QByteArray(payload)));self.assertEqual(len(s.weather.pending),pending)
        self.assertTrue(s.weatherPacket(QByteArray(struct.pack('<IfIB',1,.8,8533,7))))
        self.world_frame(s,1);self.assertEqual(s.weather.state['sound_id'],8533);self.assertEqual(s.weather.state['kind'],'RAIN');self.assertAlmostEqual(s.weather.state['intensity'],.8)
        self.assertTrue(s.weatherPacket(QByteArray(struct.pack('<IfIB',0,0,0,1))))
        self.world_frame(s,2);self.assertEqual(s.weather.state['sound_id'],0);self.assertEqual(s.weather.state['density'],0)
        s.close();self.assertFalse(s.weatherPacket(QByteArray(struct.pack('<IfIB',1,1,8533,1))))
    def test_avatar_motion_controls_native_spawn_slab_independently_of_camera_orbit(self):
        s=self.world();self.assertTrue(s.setPlayerMotion({'facing':[1,0,0],'speed':18}))
        self.world_frame(s,0);self.world_frame(s,1);before=s.weather.state['spawn_slab_up']
        self.assertGreater(before[0],.9);self.assertAlmostEqual(before[2],0,places=5)
        s.setView({'eye':[-8,8,16],'forward':[1,0,0],'up':[0,1,0],'fov':60,'aspect':1,'near':.1,'far':3000});self.world_frame(s,2)
        self.assertEqual(s.weather.state['spawn_slab_up'],before)
        for value in ({'facing':[0,0,0],'speed':18},{'facing':[float('nan'),0,1],'speed':18},{'facing':[0,0,1],'speed':201}):self.assertFalse(s.setPlayerMotion(value))
        self.world_frame(s,3);self.assertEqual(s.weather.state['spawn_slab_up'],before)
    def test_worker_restart_restores_both_ramp_endpoints_clock_and_sound(self):
        s=self.world(art=False)
        self.world_frame(s,0);self.fake_time=1.;s.weather.set({'kind':'RAIN','grade':1.,'instant':False,'sound_id':8533});s.weather.timer.stop()
        self.world_frame(s,120);self.fake_time=3.;s.weather.set({'kind':'RAIN','grade':.4,'instant':False,'sound_id':8534});s.weather.timer.stop()
        self.world_frame(s,240);before=s.weather.state
        s.cache.reader.close();self.world_frame(s,300)
        # Mid-ramp retarget starts at the old target 1, rather than the value
        # reached on the first upswing. The restored epoch remains at t=3.
        expected=1.-.6*(2./((.6-.001)*10.))
        self.assertAlmostEqual(s.weather.state['intensity'],expected,places=5)
        self.assertEqual(s.weather.state['sound_id'],8534);self.assertEqual(s.weather.state['kind'],'RAIN')
        self.assertLess(s.weather.state['intensity'],before['intensity']);self.assertEqual(len(s.weather.history),2)
    def test_rejected_weather_layer_budget_keeps_published_snapshot(self):
        from concurrent.futures import Future
        s=self.world()
        for n in range(130):self.world_frame(s,n)
        self.fake_time=3.;s.weather.set({'kind':'RAIN','grade':1.,'instant':True});s.weather.timer.stop()
        commands,s.weather.pending=s.weather.pending,[]
        result=s.pool.submit(s.weather._sample,s.weather.request(3100),commands,tuple(s.weather.history)).result(timeout=4)
        future=Future();future.set_result(result);s.weather.future=future;s.weather.finish()
        retained={k:(l.batch,l.batch.instances.getInstanceBuffer()) for k,l in s.weather.layers.items()};before=s.weather.state;used=s.bytes
        native_before=s.cache.reader.request('weather_status')
        # Advance enough for actual rain pages, so this is a real new-layer
        # allocation rather than a synthetic request mirroring the code.
        # budget_limit is a constant Qt property; fill the bookkeeping budget
        # with a temporary reservation, then remove that reservation afterwards.
        reservation=s.budget_limit-s.bytes;s.bytes+=reservation
        future=s.pool.submit(s.weather._sample,s.weather.request(4000),[],tuple(s.weather.history))
        from backend.game_engine_adapter_weather import WeatherFrameRejected
        with self.assertRaisesRegex(WeatherFrameRejected,'budget'):future.result(timeout=4)
        s.weather.future=future;s.weather.finish()
        self.assertIn('budget',s.weather.error);self.assertIs(s.weather.state,before);self.assertEqual(set(s.weather.layers),set(retained))
        for k,(batch,packet) in retained.items():self.assertIs(s.weather.layers[k].batch,batch);self.assertEqual(batch.instances.getInstanceBuffer(),packet)
        s.bytes-=reservation;self.assertEqual(s.bytes,used)
        self.assertEqual(s.cache.reader.request('weather_status'),native_before)
    def test_native_weather_rollback_restores_clock_sound_and_allocation_capacities(self):
        self.set_weather();self.frame(0);self.frame(2200);before=self.reader.request('weather_status')
        self.reader.request('weather_checkpoint');self.set_weather(kind=2,now=2300)
        self.frame(2700);self.reader.request('weather_rollback')
        self.assertEqual(self.reader.request('weather_status'),before)
        self.reader.request('weather_checkpoint');self.frame(2300);self.reader.request('weather_commit')
        self.assertGreater(self.reader.request('weather_status')['generation'],before['generation'])

if __name__=='__main__':unittest.main()
