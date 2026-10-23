"""Original table joins and real asynchronous streams through the native mixer."""
from pathlib import Path
import array,os,sys,tempfile,time,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
from PySide6.QtGui import QGuiApplication
from tools.world.engine_audio_fixtures import entries
from tools.world.engine_format_fixtures import mpq
from backend.game_engine_adapter_formats import NativeFormats
from backend.game_engine_native_presentation import Audio
from backend.game_engine_audio_stream import MusicStreams
from backend.game_engine_audio_short import ShortSounds
from backend.game_engine_adapter_audio import ZoneAudio
APP=QGuiApplication.instance() or QGuiApplication([])

class OriginalAudio(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=PROJECT/'qml');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.data=self.root/'Data';self.data.mkdir()
        (self.data/'model.MPQ').write_bytes(mpq(entries=entries()))
        self.audio=Audio();self.addCleanup(self.audio.close);self.audio.gain(1,1,1,1,True)
        self.streams=MusicStreams(self.audio);self.addCleanup(self.streams.close);self.now=0.
        self.short=ShortSounds(self.audio);self.addCleanup(self.short.close)
        self.zone=ZoneAudio(self.streams,self.data,clock=lambda:self.now,short_sounds=self.short);self.addCleanup(self.zone.close)
        self.state={'area_id':8,'minute':720,'indoors':False,'underwater':False,'ghost':False,'weather':0}
    def step(self,n=1):
        data=bytearray()
        for _ in range(n):
            self.now+=.01;self.zone.update(**self.state);self.streams.pump();self.short.pump();data.extend(self.audio.render(480));time.sleep(.001)
        return data
    def until(self,predicate,n=600):
        for _ in range(n):
            self.step()
            if predicate():return
        self.fail('Audio transition did not finish: '+str(self.zone.diagnostics()))
    def path(self,channel):
        stream=self.streams.streams.get(self.streams.current.get(channel))
        return stream.path.name if stream else None
    def test_native_parent_inheritance_and_wmo_keys(self):
        reader=NativeFormats(self.root);self.addCleanup(reader.close);reader.request('mount_chain',path=str(self.data))
        row=reader.request('area_audio',area_id=8)
        self.assertEqual(row['name'],'GG Audio Child');self.assertEqual(row['music']['kits'],[101,102]);self.assertEqual(row['ambience']['kits'],[110,111])
        room=reader.request('area_audio',area_id=7,interior={'wmo_id':44,'name_set':5,'group_id':1000})
        self.assertEqual(room['area_id'],8);self.assertEqual(room['interior_name'],'GG Room');self.assertEqual(room['music']['id'],30)
        self.assertEqual(room['ambience']['kits'],[140,111]);self.assertEqual(room['intro']['kit'],103)
        self.assertEqual(reader.request('sound_beds'),{'ghost':130,'underwater':131})
        self.assertFalse(reader.request('area_audio',area_id=0xffffffff)['found'])
        with self.assertRaises(ValueError):reader.request('area_audio',area_id=-1)
        with self.assertRaises(ValueError):reader.request('area_audio',area_id=8,interior={'wmo_id':44,'name_set':-1,'group_id':1000})
    def test_native_provider_projection_and_live_submersion_selection(self):
        import math
        (self.data/'model.MPQ').write_bytes(mpq(entries=entries(providers=True)))
        self.until(lambda:self.zone.provider_applied==1)
        row=self.zone.assets.provider(1)
        self.assertAlmostEqual(row['feedback'],min(.98,10**(-.108/1.49)),places=7)
        self.assertAlmostEqual(row['damping'],(1-.83/2)*.7+.01*.3,places=7)
        self.assertAlmostEqual(row['wet'],10**(-8/20),places=7)
        self.state['underwater']=True;self.until(lambda:self.zone.provider_applied==2)
        self.state['reverb']=False;self.step();self.assertEqual(self.zone.provider_applied,0)
    def test_intro_cooldown_and_real_file_effect_from_the_selected_chain(self):
        (self.data/'model.MPQ').write_bytes(mpq(entries=entries(intro=True)))
        self.until(lambda:self.zone.music_kit==103)
        stamp=self.zone.intro_last[9];self.until(lambda:self.zone.music_kit==101)
        self.state['area_id']=99;self.until(lambda:self.zone.catalog is not None and not self.zone.catalog['found'])
        self.state['area_id']=8;self.until(lambda:self.zone.music_kit==101)
        self.assertEqual(self.zone.intro_last[9],stamp)
        self.assertTrue(self.zone.sound({'file':'GG/Audio/103.wav'}))
        self.until(lambda:bool(self.short.loaded));self.assertFalse(self.short.errors)
        self.assertTrue(any(Path(k[0]).name=='103.wav' for k in self.short.loaded))
    def test_cinematic_pauses_lua_without_rearming_zone_deadline(self):
        self.until(lambda:self.zone.music_live)
        self.zone.lua_music('GG/Audio/103.wav');self.until(lambda:self.zone.lua_path is not None)
        self.step(100);armed=self.zone.next_track_at;identity=self.streams.current['lua']
        self.state['suppressed']=True;self.step(110);free=self.audio.stream_free(identity)
        self.step(40);self.assertLessEqual(self.audio.stream_free(identity),free);self.assertEqual(self.zone.next_track_at,armed)
        self.state['suppressed']=False;self.step(10);self.assertEqual(self.zone.next_track_at,armed)
        self.assertTrue(self.streams.active('lua'))
    def test_weather_replaces_outdoor_bed_indoor_day_night_and_submersion(self):
        self.until(lambda:self.path('ambience')=='110.wav' and self.zone.music_kit==101)
        self.state['weather']=120;self.until(lambda:self.path('ambience')=='120.wav')
        self.state['indoors']=True;self.until(lambda:self.zone.ambience_played==110 and self.path('ambience')=='110.wav')
        self.state['minute']=1260;self.until(lambda:self.zone.ambience_played==111 and self.path('ambience')=='111.wav')
        self.state['underwater']=True;self.until(lambda:self.zone.ambience_played==131)
        self.assertEqual(self.zone.ambience_fade,0)
        self.audio.gain(1,0,0,1,True);measured=0.
        for _ in range(10):
            samples=array.array('f');samples.frombytes(self.step(80));measured+=sum(v*v for v in samples)
            if measured>10:break
        self.assertGreater(measured,10)
        self.state['ghost']=True;self.until(lambda:self.zone.ambience_played==130);self.assertEqual(self.zone.ambience_fade,5000)
        self.assertLessEqual(len(self.streams.streams),6);self.assertEqual(self.zone.errors,[])
    def test_lua_slot_delays_zone_pump_and_cold_stop_arms_six_seconds(self):
        self.until(lambda:self.zone.music_live and self.zone.ambience_played==110)
        self.zone.lua_music('GG/Audio/103.wav');armed=self.zone.next_track_at
        self.assertAlmostEqual(armed,self.now+6)
        self.until(lambda:self.zone.lua_path=='GG/Audio/103.wav')
        self.assertEqual(self.path('lua'),'103.wav');self.assertFalse(self.zone.music_live)
        self.step(30);self.assertTrue(self.streams.active('lua'));self.assertEqual(self.zone.next_track_at,armed)
        self.zone.lua_music();armed=self.now+6;self.assertEqual(self.zone.next_track_at,armed)
        self.step(500);self.assertFalse(self.zone.music_live)
        self.until(lambda:self.zone.music_live);self.assertGreaterEqual(self.now,armed)
    def test_failed_lua_decode_releases_suppression_and_zone_resumes(self):
        files=entries();files['GG/Audio/bad.wav']=b'not an audio file';(self.data/'model.MPQ').write_bytes(mpq(entries=files))
        self.until(lambda:self.zone.music_live)
        self.zone.lua_music('GG/Audio/bad.wav');self.until(lambda:bool(self.streams.errors))
        self.until(lambda:self.zone.lua_path is None and self.zone.lua_request is None)
        armed=self.zone.next_track_at;self.assertIsNotNone(armed);self.until(lambda:self.zone.music_live,n=900);self.assertGreaterEqual(self.now,armed)
    def test_failed_pick_retries_without_losing_zone_and_same_kit_server_push(self):
        files=entries();files.pop('GG/Audio/101.wav');(self.data/'model.MPQ').write_bytes(mpq(entries=files))
        self.until(lambda:self.zone.errors and self.zone.ambience_played==110)
        self.assertIsNotNone(self.zone.next_track_at);self.assertFalse(self.zone.music_live)
        self.assertEqual(len(self.zone.errors),1)
        self.state['minute']=1260;self.until(lambda:self.zone.music_kit==102)
        before=self.zone.opens;self.assertTrue(self.zone.server_music(102));self.assertEqual(self.zone.opens,before)
    def test_missing_forced_bed_is_silence_without_weather_fallback(self):
        (self.data/'model.MPQ').write_bytes(mpq(entries=entries(forced=False)))
        self.state['weather']=120;self.until(lambda:self.zone.ambience_played==120)
        self.state['ghost']=True;self.step(10)
        self.assertEqual(self.zone.ambience_kit,0);self.assertEqual(self.zone.ambience_played,0)
        self.assertNotIn('ambience',self.streams.current)
    def test_unload_removes_only_extracted_audio_and_releases_channels(self):
        self.until(lambda:self.zone.music_live and self.zone.ambience_played==110)
        extracted=Path(self.zone.assets.cache.archive_directory.name);self.assertTrue(extracted.exists())
        self.zone.close();self.assertFalse(extracted.exists());self.assertTrue((self.data/'model.MPQ').exists())
        self.audio.render(16384);self.streams.pump();self.assertFalse(self.streams.streams)

if __name__=='__main__':unittest.main()
