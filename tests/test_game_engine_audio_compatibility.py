"""Audio behaviour across limiter blocks, reverb sends, fades and bounded streams."""
from pathlib import Path
import array,math,os,sys,tempfile,time,unittest,wave
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
from backend.game_engine_native_presentation import Audio
from backend.game_engine_audio_stream import AudioFileStream,MusicStreams
def floats(data):a=array.array('f');a.frombytes(data);return a
def energy(data):return sum(x*x for x in floats(data))
class AudioCompatibility(unittest.TestCase):
    def setUp(self):self.audio=Audio();self.audio.gain(1,1,1,1,True)
    def tearDown(self):self.audio.close()
    def test_lookahead_priming_and_block_invariance(self):
        def run(blocks):
            a=Audio();a.gain(1,1,1,1,True);a.clip(0,[.8]*1500,48000)
            for _ in range(4):a.play(0,gain=1)
            signal=b''.join(a.render(n) for n in blocks);a.close();return signal
        self.assertEqual(run([2000]),run([17,31,83,1869]))
        signal=floats(run([2000]));self.assertEqual(list(signal[:192]),[0.]*192)
        self.assertLessEqual(max(abs(x) for x in signal),.99001)
    def test_reverb_tail_is_only_for_opted_in_spatial_effects(self):
        def tail(position,send):
            a=Audio();a.gain(1,1,1,1,True);a.reverb(.5,.9,.1,1);a.clip(0,[.7]*96,48000)
            a.play(0,position=position,gain=1,reverb=send);a.render(4096);result=energy(a.render(8192));a.close();return result
        self.assertGreater(tail((0,0,0),True),1e-5)
        self.assertEqual(tail(None,True),0);self.assertEqual(tail((0,0,0),False),0)
    def test_voice_fade_releases_capacity(self):
        self.audio.clip(0,[.5]*100,48000);voice=self.audio.play(0,loop=True,gain=1)
        self.audio.fade(voice,0,20,True);self.audio.render(960);self.assertEqual(self.audio.voices(),0)
    def test_paused_stream_retains_samples_and_resumes_then_stop_releases(self):
        self.audio.stream_create(5,48000,4096);self.audio.stream_write(5,[.3,-.3]*4096,end=True)
        voice=self.audio.stream_play(5,2,1);self.audio.render(300);free=self.audio.stream_free(5)
        self.audio.pause(voice);self.audio.render(8192);self.assertEqual(self.audio.stream_free(5),free)
        self.assertTrue(self.audio.voice_active(voice));self.audio.pause(voice,False)
        self.assertGreater(energy(self.audio.render(1000)),1);self.assertGreater(self.audio.stream_free(5),free)
        self.audio.pause(voice);self.audio.fade(voice,0,15,True);self.audio.render(720);self.assertFalse(self.audio.voice_active(voice))
    def test_stereo_stream_capacity_end_and_resampling(self):
        self.audio.stream_create(0,24000,2400);self.assertEqual(self.audio.stream_write(0,[.6,-.3]*2400,end=True),2400)
        self.assertEqual(self.audio.stream_free(0),0);self.audio.stream_play(0,gain=1)
        signal=floats(self.audio.render(5000));self.assertGreater(max(signal),.2);self.assertLess(min(signal),-.1)
        self.assertEqual(self.audio.stream_active(0),-1)
        with self.assertRaises(ValueError):self.audio.stream_write(0,[0,0])
    def test_long_music_stream_does_not_load_entire_file(self):
        with tempfile.TemporaryDirectory(prefix='gg-audio-stream-test-') as tmp:
            path=Path(tmp)/'music.wav'
            with wave.open(str(path),'wb') as f:
                f.setnchannels(2);f.setsampwidth(2);f.setframerate(48000)
                chunk=array.array('h',(round(math.sin(i*.04)*10000) for i in range(4800*2))).tobytes()
                for _ in range(310):f.writeframesraw(chunk)
            stream=AudioFileStream(self.audio,0,path,loop=False,gain=1)
            try:
                total=0
                for _ in range(100):
                    stream.pump();total+=energy(self.audio.render(2048));time.sleep(.003)
                self.assertGreater(total,1);self.assertLessEqual(len(stream.pending),65536)
                self.assertGreaterEqual(self.audio.stream_free(0),0)
            finally:stream.close()
    def test_rapid_crossfade_and_stop_cancel_pending(self):
        path=PROJECT/'qml/game/audio/music.wav';music=MusicStreams(self.audio)
        try:
            music.play(path);music.play(path);music.play(path)
            self.assertIn('lua',music.pending)
            music.stop('lua',15);self.assertNotIn('lua',music.pending)
            self.audio.render(16384);music.pump();self.assertFalse(music.streams)
            music.play(path)
            for _ in range(20):music.pump();self.audio.render(2048);time.sleep(.005)
            self.assertEqual(len(music.streams),1);self.assertEqual(len(music.current),1)
        finally:music.close()
    def test_stream_manager_close_stops_owned_voices_preserves_same_bus_sound(self):
        music=MusicStreams(self.audio);self.audio.clip(0,[.3]*100,48000);unrelated=self.audio.play(0,bus=1,loop=True)
        music.play(PROJECT/'qml/game/audio/music.wav');self.assertEqual(self.audio.voices(),2)
        music.close();self.assertEqual(self.audio.voices(),1);self.assertTrue(self.audio.voice_active(unrelated))

    def test_crossfade_waits_for_actual_native_voice_release(self):
        path=PROJECT/'qml/game/audio/music.wav';music=MusicStreams(self.audio)
        try:
            music.play(path);music.play(path);music.play(path)
            music.pump();self.assertIn('lua',music.pending)
            self.audio.render(719);music.pump();self.assertIn('lua',music.pending)
            self.audio.render(2);music.pump();self.assertNotIn('lua',music.pending)
            for _ in range(20):music.pump();self.audio.render(2048);time.sleep(.005)
            self.assertEqual(len(music.streams),1)
            self.assertGreaterEqual(self.audio.stream_active(music.current['lua']),0)
        finally:music.close()

    def test_bad_music_file_preserves_other_game_audio(self):
        with tempfile.TemporaryDirectory(prefix='gg-bad-music-') as tmp:
            path=Path(tmp)/'bad.wav';path.write_bytes(b'not a wave file')
            music=MusicStreams(self.audio)
            try:
                music.play(path)
                deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    music.pump();self.audio.render(2048)
                    if music.errors and not music.streams:break
                    time.sleep(.005)
                self.assertTrue(music.errors);self.assertFalse(music.streams)
                self.audio.clip(0,[.5]*1000,48000);self.audio.play(0,gain=1)
                self.assertGreater(energy(self.audio.render(1500)),1)
            finally:music.close()

    def test_six_concurrent_decoders_remain_bounded_and_deliver_audio(self):
        streams=[]
        try:
            with tempfile.TemporaryDirectory(prefix='gg-six-decoders-') as tmp:
                path=Path(tmp)/'stereo.wav'
                with wave.open(str(path),'wb') as source:
                    source.setnchannels(2);source.setsampwidth(2);source.setframerate(48000)
                    source.writeframes(array.array('h',[8192,-8192]*48000).tobytes())
                for identity in range(6):
                    stream=AudioFileStream(self.audio,identity,path,gain=.15)
                    streams.append(stream);self.audio.pause(stream.voice)
                # Decode concurrently under actual ring/pipe backpressure before
                # consuming PCM. Rendering empty rings races decoder startup and
                # makes aggregate energy depend on wall-clock CPU scheduling.
                end=time.monotonic()+5
                while time.monotonic()<end and any(self.audio.stream_free(s.identity) for s in streams):
                    for stream in streams:stream.pump()
                    time.sleep(.005)
                self.assertEqual([self.audio.stream_free(s.identity) for s in streams],[0]*6)
                self.assertEqual(self.audio.voices(),6)
                self.assertTrue(all(s.process.poll() is None and len(s.pending)<=65536 for s in streams))
                self.assertEqual(energy(self.audio.render(1024)),0)
                # Every decoder must independently supply the authored stereo
                # samples after the native gain ramp; five working voices cannot
                # conceal one silent voice.
                for stream in streams:
                    self.audio.pause(stream.voice,False)
                    block=self.audio.render(8192);samples=floats(block)
                    self.assertGreater(energy(block),5)
                    self.assertAlmostEqual(samples[-2],.0375,places=5)
                    self.assertAlmostEqual(samples[-1],-.0375,places=5)
                    self.assertEqual(self.audio.stream_free(stream.identity),8192)
                    self.audio.pause(stream.voice);self.audio.render(192)
                for stream in streams:self.audio.pause(stream.voice,False)
                samples=floats(self.audio.render(8192))
                self.assertAlmostEqual(samples[-2],.225,delta=5e-5)
                self.assertAlmostEqual(samples[-1],-.225,delta=5e-5)
                self.assertEqual([self.audio.stream_free(s.identity) for s in streams],[16384]*6)
                self.assertTrue(all(s.process.poll() is None and len(s.pending)<=65536 for s in streams))
        finally:
            for stream in streams:stream.close()
        self.assertEqual(self.audio.voices(),0)
        self.assertTrue(all(s.process.poll() is not None for s in streams))

if __name__=='__main__':unittest.main()
