"""Actual native retained-floor/roof restoration and atomic packet commit."""
import os,tempfile,time,unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtGui import QGuiApplication
from backend.game_engine_adapter_formats import NativeFormats,PROJECT
from backend.game_engine_adapter_streaming import WorldStream
from tools.world import engine_world_fixtures as f
APP=QGuiApplication.instance() or QGuiApplication([])
TRIANGLE=[[-2,4,-2],[2,4,-2],[0,4,2]]
class CollisionRestore(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=PROJECT/'qml');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.reader=NativeFormats(self.root);self.addCleanup(self.reader.close)
    def query(self):return self.reader.request('collision_query',position=[0,8,0])['height']
    def stage(self,key='floor',triangles=1):self.reader.request('collision_begin',key=key,triangles=triangles)
    def append(self,rows=(TRIANGLE,),key='floor'):self.reader.request('collision_append',key=key,triangles=rows)
    def test_restored_triangles_are_invisible_until_complete_atomic_commit(self):
        self.stage();self.append();self.assertIsNone(self.query());self.reader.request('collision_commit',key='floor');self.assertEqual(self.query(),4)
        self.stage(triangles=2);self.append()
        with self.assertRaisesRegex(ValueError,'incomplete'):self.reader.request('collision_commit',key='floor')
        self.assertEqual(self.query(),4);self.assertEqual(self.reader.request('stats')['collision_staged_bytes'],0)
    def test_invalid_packet_and_changed_key_discard_staging_keep_resident_floor(self):
        self.stage();self.append();self.reader.request('collision_commit',key='floor')
        for rows,key in (([[[float('nan'),0,0],[0,0,0],[1,0,1]]],'floor'),([TRIANGLE]*257,'floor'),([TRIANGLE],'other')):
            self.stage()
            with self.assertRaises(ValueError):self.append(rows,key)
            self.assertEqual(self.query(),4);self.assertEqual(self.reader.request('stats')['collision_staged_bytes'],0)
    def test_actual_world_process_restart_preserves_roofs_and_retained_qt_buffers(self):
        s=WorldStream();self.addCleanup(s.close);s.configure(str(f.make(self.root)));end=time.monotonic()+6
        while time.monotonic()<end:
            s.update(-8,3.65,12)
            if len(s.pages)==2 and s.pending is None:break
            time.sleep(.005)
        self.assertEqual(s.last_error,'');before=s.bytes;identity=[(b,b.geometry,b.textureData) for p in s.pages.values() for b in p.batches]
        def native():
            reader=s.cache._reader();return reader.request('collision_query',position=[-8,8,12]),reader.request('stats')
        original,stats=s.pool.submit(native).result(timeout=4);self.assertEqual(original['height'],6);self.assertEqual(stats['collision_pages'],2)
        s.cache.reader.close();restored,after=s.pool.submit(native).result(timeout=4)
        self.assertEqual(restored,original);self.assertEqual(after['collision_bytes'],stats['collision_bytes']);self.assertEqual(after['collision_pages'],2);self.assertEqual(s.restored_collision_pages,2);self.assertEqual(s.bytes,before)
        for b,g,t in identity:self.assertIs(b.geometry,g);self.assertIs(b.textureData,t)
        s.close();self.assertEqual(s.bytes,0)
if __name__=='__main__':unittest.main()
