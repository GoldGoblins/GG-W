"""Actual MPQ sector reads, large-track backpressure and archive loops."""
import array,io,math,tempfile,time,unittest,wave
from pathlib import Path
from backend.game_engine_adapter_formats import NativeFormats,PROJECT
from backend.game_engine_adapter_audio import AudioAssets
from backend.game_engine_audio_archive import ArchiveAudioSource
from backend.game_engine_audio_stream import AudioFileStream
from backend.game_engine_native_presentation import Audio
from tools.world import engine_format_fixtures as f
def wav(seconds):
    buffer=io.BytesIO()
    with wave.open(buffer,'wb') as writer:
        writer.setnchannels(2);writer.setsampwidth(2);writer.setframerate(48000)
        chunk=array.array('h',(round(math.sin(i*.04)*10000) for i in range(9600))).tobytes()
        for _ in range(round(seconds*10)):writer.writeframesraw(chunk)
    return buffer.getvalue()
def energy(data):
    values=array.array('f');values.frombytes(data);return sum(x*x for x in values)
class ArchiveAudio(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=PROJECT/'qml');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.data=self.root/'Data';self.data.mkdir();self.reader=NativeFormats(self.root);self.addCleanup(self.reader.close)
    def mount(self,entries):
        (self.data/'patch.MPQ').write_bytes(f.mpq(entries=entries));self.reader.request('mount_chain',path=str(self.data))
    def test_original_archive_stream_can_seek_read_close_and_reject_stale_handles(self):
        raw=wav(.1);self.mount({'Music/Test.wav':raw});opened=self.reader.request('archive_audio_open',entry='music/test.wav');self.assertEqual(opened['size'],len(raw))
        _,data=NativeFormats._unpack(self.reader.request('archive_audio_read',id=opened['id'],position=4090,limit=80));self.assertEqual(data,raw[4090:4090+len(data)])
        _,header=NativeFormats._unpack(self.reader.request('archive_audio_read',id=opened['id'],position=0,limit=44));self.assertEqual(header,raw[:44])
        self.reader.request('archive_audio_close',id=opened['id'])
        with self.assertRaisesRegex(ValueError,'unavailable'):self.reader.request('archive_audio_read',id=opened['id'],position=0,limit=1)
        self.assertEqual(self.reader.request('stats')['archive_audio_handles'],0)
    def test_large_original_track_streams_without_full_extraction(self):
        raw=wav(50);self.assertGreater(len(raw),8*1024*1024);self.mount({'Music/Long.wav':raw})
        assets=AudioAssets(self.data);self.addCleanup(assets.close);source,_,_=assets.prepare_file('Music/Long.wav',set());self.assertIsInstance(source,ArchiveAudioSource);self.assertEqual(assets.cache.archive_bytes,0)
        audio=Audio();self.addCleanup(audio.close);audio.gain(1,1,1,1,True);stream=AudioFileStream(audio,0,source,loop=False,gain=1);self.addCleanup(stream.close)
        total=0;end=time.monotonic()+6
        while total<100 and time.monotonic()<end:stream.pump();total+=energy(audio.render(2048));time.sleep(.005)
        self.assertGreater(total,100);self.assertLess(stream.feeder.bytes_read,len(raw)//2);self.assertLessEqual(len(stream.pending),65536)
        stream.close();stream.feeder.thread.join(timeout=3);self.assertFalse(stream.feeder.thread.is_alive());self.assertEqual(assets.cache.archive_bytes,0)
    def test_loop_rewinds_original_archive_without_restarting_native_reader(self):
        raw=wav(.1);self.mount({'Music/Loop.wav':raw});source=ArchiveAudioSource(self.data,'Music/Loop.wav',len(raw));audio=Audio();self.addCleanup(audio.close);audio.gain(1,1,1,1,True)
        stream=AudioFileStream(audio,0,source,loop=True,gain=1);self.addCleanup(stream.close);end=time.monotonic()+6;total=0
        while stream.feeder.loops<3 and time.monotonic()<end:stream.pump();total+=energy(audio.render(2048));time.sleep(.005)
        self.assertGreaterEqual(stream.feeder.loops,3);self.assertGreater(total,100);self.assertFalse(stream.ended)
        stream.close();stream.feeder.thread.join(timeout=3);self.assertFalse(stream.feeder.thread.is_alive())
if __name__=='__main__':unittest.main()
