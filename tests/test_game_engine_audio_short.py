"""Real codec decoding, stereo signal, pitch, bounds and decoder cleanup."""
import array,math,os,shutil,subprocess,sys,tempfile,time,unittest,wave
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
from backend.game_engine_audio_short import Decode,ShortSounds
from backend.game_engine_native_presentation import Audio
class Sounds(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(dir=PROJECT/'qml');self.root=Path(self.directory.name);self.addCleanup(self.directory.cleanup)
        self.wav=self.root/'stereo.wav';samples=array.array('h')
        for i in range(2205):samples.extend((int(math.sin(i*math.tau*440/22050)*15000),0))
        with wave.open(str(self.wav),'wb') as w:w.setnchannels(2);w.setsampwidth(2);w.setframerate(22050);w.writeframes(samples.tobytes())
    def decode(self,path):
        decoder=Decode(path);self.addCleanup(decoder.close);end=time.monotonic()+5
        while time.monotonic()<end:
            data=decoder.pump()
            if data is not None:return decoder,data
            time.sleep(.002)
        self.fail('decoder did not complete')
    def test_wav_mp3_ogg_real_decode_stereo_and_rate(self):
        for extension,codec in (('wav',None),('mp3','libmp3lame'),('ogg','libvorbis')):
            path=self.root/('stereo.'+extension)
            if codec:subprocess.run([shutil.which('ffmpeg'),'-nostdin','-hide_banner','-loglevel','error','-i',str(self.wav),'-c:a',codec,str(path)],check=True,timeout=5)
            decoder,data=self.decode(path);self.assertEqual(decoder.rate,22050)
            left=sum(x*x for x in data[0::2]);right=sum(x*x for x in data[1::2])
            self.assertGreater(left,1);self.assertLess(right,left*.001)
            if extension=='wav':self.assertLess(max(abs(x) for x in data[1::2]),1e-6)
            self.assertIsNotNone(decoder.process.returncode)
    def test_native_stereo_pitch_and_voice_tokens(self):
        decoder,data=self.decode(self.wav);audio=Audio();self.addCleanup(audio.close);audio.clip(8,data,decoder.rate,channels=2);audio.gain(1,1,1,1,True)
        voice=audio.play(8,gain=1,pitch=2);token=audio.voice_token(voice);self.assertGreater(token,0)
        output=array.array('f');output.frombytes(audio.render(4096))
        self.assertGreater(sum(x*x for x in output[0::2]),1);self.assertLess(max(abs(x) for x in output[1::2]),1e-6)
        self.assertFalse(audio.voice_active(voice));next_voice=audio.play(8);self.assertEqual(next_voice,voice);self.assertNotEqual(audio.voice_token(voice),token)
        for pitch in (0,9,float('nan')):
            with self.assertRaises(ValueError):audio.play(8,pitch=pitch)
    def test_queue_dedup_and_close_stops_owned_voices(self):
        audio=Audio();self.addCleanup(audio.close);short=ShortSounds(audio);self.addCleanup(short.close)
        short.play(self.wav,unique=73,loop=True);short.play(self.wav,unique=73);self.assertEqual(len(short.pending),1)
        end=time.monotonic()+5
        while short.pending and time.monotonic()<end:short.pump();time.sleep(.002)
        self.assertFalse(short.errors,short.errors);self.assertFalse(short.pending);self.assertEqual(audio.voices(),1)
        short.play(self.wav,unique=73);self.assertEqual(audio.voices(),1);short.close();self.assertEqual(audio.voices(),0)
    def test_close_keeps_unrelated_voices_on_the_same_bus(self):
        audio=Audio();self.addCleanup(audio.close);short=ShortSounds(audio);self.addCleanup(short.close)
        audio.clip(0,[.2]*480,48000);other=audio.play(0,loop=True);token=audio.voice_token(other)
        short.play(self.wav,loop=True);end=time.monotonic()+5
        while short.pending and time.monotonic()<end:short.pump();time.sleep(.002)
        self.assertFalse(short.errors,short.errors);self.assertEqual(audio.voices(),2)
        short.close();self.assertEqual(audio.voices(),1);self.assertEqual(audio.voice_token(other),token)
    def test_more_than_twenty_four_files_evict_only_unused_clips(self):
        audio=Audio();self.addCleanup(audio.close);short=ShortSounds(audio);self.addCleanup(short.close)
        for i in range(28):
            path=self.root/f'sfx-{i}.wav';path.write_bytes(self.wav.read_bytes());short.play(path,loop=i==0)
            end=time.monotonic()+5
            while short.pending and time.monotonic()<end:short.pump();time.sleep(.002)
            self.assertFalse(short.pending);self.assertFalse(short.errors,short.errors)
            audio.render(8192)
        self.assertEqual(len(short.loaded),24);self.assertEqual(len(short.free_ids),0);self.assertEqual(audio.voices(),1)
        self.assertTrue(any(Path(k[0]).name=='sfx-0.wav' for k in short.loaded));self.assertFalse(any(Path(k[0]).name=='sfx-1.wav' for k in short.loaded))
    def test_broken_long_and_stopped_decoders_are_bounded(self):
        broken=self.root/'broken.wav';broken.write_bytes(b'broken');decoder=Decode(broken);self.addCleanup(decoder.close)
        with self.assertRaisesRegex(ValueError,'decoding failed'):
            while True:decoder.pump();time.sleep(.002)
        long=self.root/'long.wav'
        with wave.open(str(long),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(8000);w.writeframes(bytes(8000*11*2))
        decoder=Decode(long);self.addCleanup(decoder.close)
        with self.assertRaisesRegex(ValueError,'ten seconds'):
            while True:decoder.pump();time.sleep(.001)
        decoder=Decode(self.wav);self.addCleanup(decoder.close);decoder.deadline=0
        with self.assertRaises(TimeoutError):decoder.pump()
        decoder.close();self.assertIsNotNone(decoder.process.returncode)
if __name__=='__main__':unittest.main()
