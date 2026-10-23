"""WDL original reader/mesh/oracle and actual bounded world lifecycle."""
import json,math,os,struct,tempfile,time,unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtGui import QGuiApplication
from PySide6.QtCore import QCoreApplication,QEvent
from backend.game_engine_adapter_formats import NativeFormats,PROJECT
from backend.game_engine_adapter_horizon import Heights,settings
from backend.game_engine_adapter_streaming import WorldStream,TILE
from tools.world import engine_world_fixtures as f,engine_format_fixtures as a
APP=QGuiApplication.instance() or QGuiApplication([])

class HorizonTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=PROJECT/'qml');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.data=self.root/'Data';self.data.mkdir();self.reader=NativeFormats(self.root);self.addCleanup(self.reader.close)
    def mount(self,tiles,height=None,raw=None):
        (self.data/'model.MPQ').write_bytes(a.mpq(entries={'World/Maps/Test/Test.wdl':raw if raw is not None else f.wdl(tiles,height)}));self.reader.request('mount_chain',path=str(self.data))
        return NativeFormats._unpack(self.reader.request('wdl_load',map='Test',timeout=4))
    def settle(self,stream,predicate,position=None):
        end=time.monotonic()+12
        while time.monotonic()<end:
            stream.update(*(position or stream.position));APP.processEvents()
            if stream.last_error or stream.horizon.error:self.fail(stream.last_error or stream.horizon.error)
            if predicate():return
            time.sleep(.003)
        self.fail('Horizon did not settle: '+str(stream.status()))
    def test_full_map_compact_oracle_matches_original_all_four_fans_and_edges(self):
        meta,blob=self.mount([(32,32),(33,32)],lambda r,c:int((r-512)*3+(c-512)*7+5*(r%1)))
        oracle=Heights(meta,blob);self.assertEqual(len(blob),2180);self.assertGreater(meta['native_bytes'],4_000_000)
        points=[]
        for r,c in ((.1,.1),(.05,.7),(.8,.95),(.6,.1),(.5,.5),(0,0),(15.75,15.1),(1.2,16.5),(16,0),(-.01,0)):
            points.append([-r*TILE/16,-c*TILE/16,0])
        result=self.reader.request('wdl_heights',points=points)
        for point,want in zip(points,result):self.assertEqual(oracle.sample(*point[:2]),want)
        self.assertIsNone(oracle.sample(1e6,0));self.assertIsNone(oracle.sample(float('inf'),0))
    def test_original_mesh_seams_indices_origin_and_bounds(self):
        self.mount([(32,32),(33,32)],lambda r,c:int(r+c))
        meta,blob=NativeFormats._unpack(self.reader.request('wdl_tiles',tiles=[[32,32],[33,32]],origin=[100,200,300]))
        left,right=meta['rows'];self.assertEqual(left['vertices'],545);self.assertEqual(len(left['indices']),3072)
        for r in range(17):
            aoff=left['offset']+(r*17+16)*32;boff=right['offset']+(r*17)*32
            self.assertEqual(blob[aoff:aoff+12],blob[boff:boff+12])
        self.assertEqual(struct.unpack_from('<3f',blob),(-100.,724.,200.))
        with self.assertRaisesRegex(ValueError,'capacity'):self.reader.request('wdl_tiles',tiles=[[32,32]]*9,origin=[0,0,0])
        self.reader.request('wdl_release');self.assertEqual(self.reader.request('stats')['wdl_bytes'],0)
        with self.assertRaisesRegex(ValueError,'not loaded'):self.reader.request('wdl_heights',points=[])
    def test_ring_eight_tile_batches_eviction_and_close_memory(self):
        tiles=[(x,y) for y in range(27,38) for x in range(27,38)]+[(48,48)]
        self.mount(tiles);manifest=f.make(self.root,wmos=False);cfg=json.loads(manifest.read_text());cfg['archive_directory']=str(self.data);manifest.write_text(json.dumps(cfg))
        stream=WorldStream();self.addCleanup(stream.close);stream.configure(str(manifest))
        self.settle(stream,lambda:len(stream.horizon.tiles)==121 and stream.horizon.future is None)
        self.assertEqual(stream.horizon.frames,math.ceil(121/8));self.assertLess(stream.bytes,stream.budget_limit)
        self.assertEqual(stream.horizon.height(-10,10),0)
        retain={key:(tile.batch,tile.batch.geo) for key,tile in stream.horizon.tiles.items()}
        self.settle(stream,lambda:stream.horizon.future is None,position=(-20,4,30))
        for key,(batch,geo) in retain.items():self.assertIs(stream.horizon.tiles[key].batch,batch);self.assertIs(batch.geo,geo)
        self.settle(stream,lambda:set(stream.horizon.tiles)=={(48,48)} and stream.horizon.future is None,position=(-16*TILE,4,16*TILE))
        self.assertEqual(len(stream.pages),0);stream.close();QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
        self.assertEqual(stream.bytes,0);self.assertEqual(stream.horizon.status()['bytes'],0);self.assertFalse(stream.active)
    def test_absent_optional_map_and_malformed_original_map_distinguished(self):
        manifest=f.make(self.root,wmos=False);stream=WorldStream();self.addCleanup(stream.close);stream.configure(str(manifest));self.settle(stream,lambda:stream.horizon.stage=='UNAVAILABLE')
        self.assertEqual(stream.horizon.error,'');self.assertTrue(stream.active)
        with self.assertRaises(ValueError):self.mount([(32,32)],raw=f.wdl([(32,32)])[:120])
        with self.assertRaisesRegex(ValueError,'directory'):self.reader.request('wdl_load',map='../Test')
    def test_closed_during_header_load_and_disabled_configuration(self):
        self.mount([(32,32)]);manifest=f.make(self.root,wmos=False);cfg=json.loads(manifest.read_text());cfg.update(archive_directory=str(self.data),horizon=False);manifest.write_text(json.dumps(cfg))
        stream=WorldStream();self.addCleanup(stream.close);stream.configure(str(manifest));self.settle(stream,lambda:len(stream.pages)==1 and stream.pending is None)
        self.assertEqual(stream.horizon.stage,'OFF');self.assertEqual(stream.detailedFar,0);stream.close();self.assertEqual(stream.bytes,0)
        cfg['horizon']=True;manifest.write_text(json.dumps(cfg));other=WorldStream();self.addCleanup(other.close);other.configure(str(manifest));other.horizon.schedule();other.close();self.assertEqual(other.bytes,0);self.assertIsNone(other.horizon.heights)
    def test_manifest_and_oracle_validation(self):
        for value in ({'far_clip':176},{'far_clip':float('nan')},{'enabled':1},[]):
            with self.assertRaises(ValueError):settings(value)
        self.assertEqual(settings(None)['far_clip'],350)
        with self.assertRaises(ValueError):Heights({'tiles':[{'x':32,'y':32,'offset':1}]},bytes(1090))

if __name__=='__main__':unittest.main()
