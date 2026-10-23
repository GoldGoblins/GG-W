"""Authored event windows, original emitter rules and actual native PCM voices."""
import array,json,math,os,struct,tempfile,time,unittest
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QObject
from PySide6.QtGui import QGuiApplication
from backend.game_engine_adapter_formats import NativeFormats,PROJECT
from backend.game_engine_adapter_streaming import WorldStream
from backend.game_engine_adapter_emitters import AmbientEmitters
from backend.game_engine_adapter_audio import ZoneAudio
from backend.game_engine_native_presentation import Audio
from backend.game_engine_audio_stream import MusicStreams
from backend.game_engine_audio_short import ShortSounds
from tools.world import engine_format_fixtures as f,engine_world_fixtures as w,engine_audio_fixtures as a
APP=QGuiApplication.instance() or QGuiApplication([])
IDENTITY=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]

class ModelEvents(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=PROJECT/'qml');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.path=self.root/'events.m2';self.path.write_bytes(f.event_m2());(self.root/'gold.blp').write_bytes(f.blp())
        self.reader=NativeFormats(self.root);self.addCleanup(self.reader.close)
    def pose(self,cursor,**options):
        meta,_=self.reader.decode(self.path,runtime=True,instance='world:events',world_instance=True,anim_id=7,cursor_ms=cursor,clock_ms=cursor,compact=True,**options)
        return meta['events']
    def test_arm_duplicate_tick_fresh_zero_key_and_actual_bone_marker(self):
        self.assertEqual(self.pose(0)['keys'],[]);self.assertEqual(self.pose(0)['keys'],[])
        self.assertEqual([r['time_ms'] for r in self.pose(100)['keys']],[0])
        anchor=IDENTITY.copy();anchor[12:15]=[5,6,7]
        rows=self.pose(300,anchor=anchor)['keys'];self.assertEqual([r['time_ms'] for r in rows],[250])
        self.assertEqual(rows[0]['tag'],'$SND');self.assertEqual(rows[0]['data'],150)
        for value,want in zip(rows[0]['position'],[6.3,10.,-8.]):self.assertAlmostEqual(value,want,places=5)
        self.assertEqual(self.pose(300)['keys'],[])
    def test_wrap_end_then_zero_and_nonloop_end_never_repeats(self):
        self.pose(500);self.assertEqual([r['time_ms'] for r in self.pose(900)['keys']],[750])
        self.assertEqual([r['time_ms'] for r in self.pose(1100)['keys']],[1000,0])
        self.reader.request('release_instance',instance='world:events');self.path.write_bytes(f.event_m2(looping=False))
        self.pose(900);self.assertEqual([r['time_ms'] for r in self.pose(1000)['keys']],[1000]);self.assertFalse(self.pose(1300)['keys'])
    def test_backward_seek_and_long_pause_reset_without_audio_backlog(self):
        self.pose(0);self.pose(300)
        self.assertEqual(self.pose(10)['reset'],'SEEK');self.assertEqual([r['time_ms'] for r in self.pose(20)['keys']],[0])
        row=self.pose(10000);self.assertTrue(row['discarded_window']);self.assertFalse(row['keys'])
        self.assertFalse(self.pose(10100)['keys'])
    def test_integral_short_clip_wrap_has_no_fractional_millisecond_drift(self):
        data=bytearray(f.event_m2([('$SND',150,0,(0,0,0),(0,333))]));seq=struct.unpack_from('<I',data,0x20)[0]
        struct.pack_into('<I',data,seq+8,333);self.path.write_bytes(data)
        self.pose(100);self.pose(200)
        self.assertEqual([r['time_ms'] for r in self.pose(333)['keys']],[333,0])
        self.assertFalse(self.pose(334)['keys'])
    def test_rigless_root_marker_and_bounded_event_output(self):
        self.path.write_bytes(f.event_m2([('$DSO',150,255,(1,2,3),(100,))],rigged=False));self.pose(0)
        self.assertEqual(self.pose(150)['keys'][0]['position'],[1,3,-2])
        self.reader.request('release_instance',instance='world:events')
        self.path.write_bytes(f.event_m2([('$SND',150,0,(0,0,0),tuple(range(1,101)))]));self.pose(0)
        row=self.pose(150);self.assertEqual(len(row['keys']),64);self.assertEqual(row['dropped'],36)
        self.reader.request('release_instance',instance='world:events');self.assertEqual(self.reader.request('stats')['effect_instances'],0)
    def test_bad_record_capacity_and_nonfinite_marker_recover_worker(self):
        for data in (f.event_m2([('$SND',150,0,(float('nan'),0,0),(0,))]),):
            self.path.write_bytes(data)
            with self.assertRaisesRegex(ValueError,'non-finite'):self.pose(0)
        data=bytearray(f.event_m2());struct.pack_into('<I',data,0x114,257);self.path.write_bytes(data)
        with self.assertRaisesRegex(ValueError,'capacity|truncated'):self.pose(0)
        self.assertEqual(self.reader.request('ping'),{'abi':1})
    def test_real_retained_world_dispatch_and_eviction_drop_late_pose(self):
        manifest=w.make(self.root);self.path=self.root/'crate.m2';self.path.write_bytes(f.event_m2())
        (self.root/'Test_32_32.adt').write_bytes(w.placed_objects(w.terrain(),[{}]))
        cfg=json.loads(manifest.read_text());cfg.update(wmos=[],radius=0);manifest.write_text(json.dumps(cfg))
        delivered=[];removed=[];host=QObject();host._game_presentation=SimpleNamespace(world_model_events=lambda owner,events:delivered.append((owner,events)),world_model_removed=removed.append)
        stream=WorldStream(host);self.addCleanup(lambda s=stream,h=host:s.close());stream.configure(str(manifest));end=time.monotonic()+8
        while time.monotonic()<end:
            stream.update(-2,2.65,20)
            if stream.pages and not stream.pending:break
            time.sleep(.003)
        self.assertTrue(stream.pages)
        stream.advance(.3);end=time.monotonic()+3
        while stream.animations.future is not None and time.monotonic()<end:stream.animations.finish();time.sleep(.001)
        self.assertEqual(stream.animations.error,'');self.assertTrue(any(r['keys'] for owner,r in delivered))
        before=len(delivered);stream.advance(.1);page=stream.pages['t:32:32'];stream._remove_page('t:32:32')
        end=time.monotonic()+3
        while stream.animations.future is not None and time.monotonic()<end:stream.animations.finish();time.sleep(.001)
        self.assertTrue(page.closed);self.assertEqual(len(delivered),before);self.assertTrue(removed)

class FakeShort:
    def __init__(self):self.voices={};self.stops=[]
    def play(self,path,**options):self.voices[options['unique']]=dict(options)
    def has(self,key):return key in self.voices
    def move(self,key,position):
        if key in self.voices:self.voices[key]['position']=position;return True
        return False
    def stop(self,key,fade_ms=0):self.stops.append((key,fade_ms));self.voices.pop(key,None)

class PoolRules(unittest.TestCase):
    def setUp(self):self.short=FakeShort();self.pool=AmbientEmitters(self.short)
    def ready(self):
        while self.pool.preparation():
            serial,kit,pos=self.pool.preparation();self.pool.resolve(serial,(Path('/unused.wav'),{},60.))
    def test_one_kit_one_channel_nearest_tie_stable_without_restart(self):
        self.pool.register('a',10,[-4,0,0]);self.pool.register('b',10,[4,0,0]);self.ready();self.pool.update([0,0,0])
        entry=self.pool.entries[0];key=entry['key'];self.assertEqual(self.short.voices[key]['position'],(-4,0,0));self.assertEqual(self.pool.starts,1)
        self.pool.update([5,0,0]);self.assertEqual(self.short.voices[key]['position'],(4,0,0));self.assertEqual(self.pool.starts,1)
        self.pool.release('b');self.pool.update([0,0,0]);self.assertEqual(self.pool.starts,1)
        self.pool.release('a');self.assertEqual(self.short.stops[-1],(key,3000))
    def test_claim_order_four_channel_cap_and_out_of_range_does_not_claim(self):
        for i in range(6):self.pool.register(str(i),i+1,[100 if i==0 else 6-i,0,0])
        self.ready();self.pool.update([0,0,0]);self.assertEqual(len(self.short.voices),4)
        self.assertEqual({self.pool.entries[i]['key'] for i in range(1,5)},set(self.short.voices))
        self.pool.register('0',1,[1,0,0]);self.pool.update([0,0,0]);self.assertEqual(set(self.short.voices),{self.pool.entries[i]['key'] for i in range(4)})
    def test_owner_replacement_keep_first_and_stale_preparation_never_revives(self):
        self.pool.register('a',1,[0,0,0]);serial=self.pool.preparation()[0]
        self.pool.register('a',2,[1,0,0],keep_first=True);self.assertEqual(self.pool.entries[0]['kit'],1)
        self.pool.register('a',2,[1,0,0]);self.assertFalse(self.pool.resolve(serial,(Path('/unused'),{},60)))
        self.assertEqual(self.pool.entries[0]['kit'],2);self.assertEqual(len(self.pool.handles),1)
    def test_32_kit_and_256_record_caps_evict_first_farther_owner(self):
        for i in range(32):self.assertTrue(self.pool.register('kit'+str(i),i+1,[0,0,0]))
        self.assertFalse(self.pool.register('overflow',33,[0,0,0]));self.assertEqual(len(self.pool.handles),32)
        self.pool.clear()
        for i in range(256):self.assertTrue(self.pool.register(str(i),1,[500-i,0,0]))
        self.assertTrue(self.pool.register('near',1,[0,0,0]));self.assertNotIn('0',self.pool.handles);self.assertIn('near',self.pool.handles)
        self.assertFalse(self.pool.register('far',1,[1000,0,0]));self.assertEqual(len(self.pool.handles),256)

class LiveModelAudio(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=PROJECT/'qml');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);data=self.root/'Data';data.mkdir();(data/'patch.MPQ').write_bytes(f.mpq(entries=a.entries()))
        self.audio=Audio();self.addCleanup(self.audio.close);self.audio.gain(1,1,0,0,True);self.audio.listener(0,0,0,0)
        self.streams=MusicStreams(self.audio);self.addCleanup(self.streams.close);self.short=ShortSounds(self.audio);self.addCleanup(self.short.close)
        self.now=0.;self.zone=ZoneAudio(self.streams,data,clock=lambda:self.now,short_sounds=self.short);self.addCleanup(self.zone.close)
    def step(self):
        self.now+=.01;self.zone.update(area_id=99);self.streams.pump();self.short.pump();self.audio.render(480);time.sleep(.001)
    def until(self,predicate):
        for _ in range(600):
            self.step()
            if predicate():return
        self.fail(str(self.zone.diagnostics())+str(self.short.errors))
    def event(self,tag,kit=150,pos=(-8,0,0)):return {'keys':[{'tag':tag,'data':kit,'position':list(pos)}]}
    def test_actual_shared_loop_changes_stereo_without_changing_voice_generation(self):
        self.zone.model_events('world:a',self.event('$DSL'));self.zone.model_events('world:b',self.event('$DSL',pos=(8,0,0)))
        self.until(lambda:bool(self.short.voices));key=next(iter(self.short.voices));voice=self.short.voices[key];self.assertEqual(len(self.short.voices),1)
        def powers():
            samples=array.array('f');samples.frombytes(self.audio.render(4800));return [sum(v*v for v in samples[c::2]) for c in (0,1)]
        left=powers();self.zone.release_model('world:a');self.zone.emitters.update((0,0,0));right=powers()
        self.assertEqual(self.short.voices[key],voice);self.assertEqual(self.audio.voice_token(voice[0]),voice[1])
        self.assertGreater(left[0]+left[1],.01);self.assertGreater(right[0]+right[1],.01)
        self.assertLess((left[0]-left[1])*(right[0]-right[1]),0)
        self.zone.model_events('world:b',self.event('$DSE',0));self.assertFalse(self.short.voices)
        for _ in range(30):self.audio.render(4800)
        self.assertFalse(self.audio.voice_active(voice[0]))
    def test_actual_one_shot_and_late_preparation_rejected_after_owner_reuse(self):
        self.assertTrue(self.zone.model_events('world:a',self.event('$SND')));self.until(lambda:bool(self.short.loaded))
        self.assertFalse(self.short.errors);self.assertFalse(self.zone.errors)
        future=Future();future.set_result((self.root/'missing.wav',{'gain':1.}))
        serial=self.zone.model_owners['world:a'];self.zone.release_model('world:a');self.zone.model_events('world:a',{'keys':[]})
        self.zone.future=future;self.zone.job=('effect',(self.zone.sound_generation,('world:a',serial)))
        self.zone._finish(self.now);self.assertFalse(self.zone.errors)
    def test_native_stale_voice_move_cannot_move_reused_channel(self):
        self.audio.clip(0,[.1]*4800,48000);voice=self.audio.play(0,position=(-3,0,0),loop=True);old=self.audio.voice_token(voice)
        self.audio.stop_voice(voice,old);new_voice=self.audio.play(0,position=(3,0,0),loop=True);self.assertEqual(new_voice,voice)
        self.audio.move_voice(voice,old,(-3,0,0));self.assertNotEqual(self.audio.voice_token(voice),old)
        samples=array.array('f');samples.frombytes(self.audio.render(4800));before=sum(v*v for v in samples[::2])-sum(v*v for v in samples[1::2])
        self.audio.move_voice(voice,self.audio.voice_token(voice),(-3,0,0))
        samples=array.array('f');samples.frombytes(self.audio.render(4800));after=sum(v*v for v in samples[::2])-sum(v*v for v in samples[1::2]);self.assertLess(before*after,0)
        with self.assertRaises(ValueError):self.audio.move_voice(voice,self.audio.voice_token(voice),(float('nan'),0,0))
