"""Large original-format WMO directories, ownership and atomic group windows."""
import json,os,struct,tempfile,time,unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtGui import QGuiApplication
from backend.game_engine_adapter_formats import PROJECT,NativeFormats
from backend.game_engine_adapter_streaming import WorldStream
from backend.game_engine_adapter_wmo_windows import selected,needed
from tools.world import engine_world_fixtures as f
from tools.world.engine_format_fixtures import mpq
APP=QGuiApplication.instance() or QGuiApplication([])

class WmoWindowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=PROJECT/'qml');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.manifest=f.make(self.root)
        self.path=self.root/'rooms.wmo';self.path.write_bytes(f.root(64,portal_geometry=True))
        for gi in range(64):(self.root/f'rooms_{gi:03}.wmo').write_bytes(f.room(gi))
        self.reader=NativeFormats(self.root);self.addCleanup(self.reader.close)
    def directory(self,**kwargs):
        return NativeFormats._unpack(self.reader.request('wmo_directory',path=str(self.path),timeout=4,**kwargs))
    def stream(self,**cfg):
        v=json.loads(self.manifest.read_text());v.update(cfg);self.manifest.write_text(json.dumps(v))
        stream=WorldStream();self.addCleanup(stream.close);stream.configure(str(self.manifest));return stream
    def settle(self,stream,position):
        end=time.monotonic()+12
        while time.monotonic()<end:
            stream.update(*position)
            if stream.last_error:self.fail(stream.last_error)
            if stream.pending is None and len(stream.pages)==1 and not needed(stream.pages['w:fixed:0'],position):return stream.pages['w:fixed:0']
            time.sleep(.005)
        self.fail('WMO group window did not settle')
    def dungeon(self,**cfg):
        (self.root/'Test.wdt').write_bytes(f.dungeon_wdt(str(self.path)))
        return self.stream(wmos=[],**cfg)
    def test_complete_directory_has_no_geometry_or_collision_allocation(self):
        before=self.reader.request('stats');metadata,blob=self.directory(position=[10,20,2])
        self.assertEqual(len(metadata['groups']),64);self.assertEqual(metadata['groups'][63]['id'],63)
        self.assertEqual(metadata['groups'][63]['group_id'],1063)
        self.assertEqual(metadata['rows'],[]);self.assertEqual(blob,b'')
        self.assertEqual(self.reader.request('stats')['collision_pages'],before['collision_pages'])
        self.assertEqual(metadata['portals']['refs'][0]['group'],1)
        self.assertAlmostEqual(metadata['groups'][0]['corners'][0][0],-2)
    def test_sparse_geometry_is_skipped_and_late_reference_metadata_is_read(self):
        self.path.write_bytes(f.root(64,props=[{}],lights=[{}]))
        path=self.root/'rooms_039.wmo';payload=f.room(39,props=[0],lights=[0])
        mogp=payload.index(b'PGOM');h=payload[mogp+8:mogp+8+68]
        refs=f.chunk('MODR',struct.pack('<H',0))+f.chunk('MOLR',struct.pack('<H',0))
        size=24*1024*1024
        with path.open('wb') as file:
            file.write(payload[:mogp]+b'PGOM'+struct.pack('<I',68+8+size+len(refs))+h+b'TVOM'+struct.pack('<I',size))
            file.seek(size,1);file.write(refs)
        metadata,blob=self.directory()
        self.assertEqual(blob,b'');self.assertEqual(metadata['props'][0]['owning_groups'],[39])
        self.assertEqual(metadata['props'][0]['light']['MOLR_lobes'],1)
        self.assertGreater(path.stat().st_size,16*1024*1024)
    def test_noncontiguous_selected_groups_keep_original_ids_and_light_refs(self):
        self.path.write_bytes(f.root(64,props=[{}],lights=[{}]))
        (self.root/'rooms_031.wmo').write_bytes(f.room(31,props=[0],lights=[0]))
        m,b=self.reader.decode(self.path,world_scene=True,groups_selected=[31,63])
        self.assertEqual([g['id'] for g in m['groups']],[31,63])
        self.assertEqual({r['group'] for r in m['rows']},{31,63})
        self.assertEqual(m['props'][0]['owning_groups'],[31]);self.assertEqual(m['props'][0]['light']['MOLR_lobes'],1)
        self.assertGreater(len(b),0)
        for invalid in ([31,31],[64],[],[True]):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):self.reader.decode(self.path,world_scene=True,groups_selected=invalid)
    def test_world_travel_replaces_geometry_and_native_physics_together(self):
        stream=self.dungeon();first=self.settle(stream,(-8,3.65,12))
        self.assertEqual(first.metadata['group_window'],list(range(8)))
        self.assertEqual(len(first.metadata['groups']),64);self.assertEqual(stream.query(-8,3.65,12)['area_id'],1000)
        initial=stream.bytes
        for gi in (15,31,47,63,0):
            previous=stream.pages['w:fixed:0'];position=(-8-gi*8,3.65,12)
            stream.update(*position)
            self.assertIs(stream.pages['w:fixed:0'],previous);self.assertFalse(previous.closed)
            page=self.settle(stream,position)
            self.assertTrue(previous.closed);self.assertIn(gi,page.metadata['group_window'])
            self.assertEqual(len(page.metadata['groups']),64)
            self.assertEqual(stream.query(*position)['group'],gi);self.assertEqual(stream.query(*position)['area_id'],1000+gi)
            stats=stream.cache.reader.request('stats');self.assertEqual(stats['collision_pages'],1)
            self.assertLess(stream.bytes,96*1024*1024);self.assertLess(abs(stream.bytes-initial),4000)
        stream.close();self.assertEqual(stream.bytes,0)
    def test_missing_replacement_keeps_old_geometry_collision_and_budget(self):
        stream=self.dungeon();old=self.settle(stream,(-8,3.65,12));budget=stream.bytes
        (self.root/'rooms_063.wmo').unlink();end=time.monotonic()+5
        while time.monotonic()<end and not stream.last_error:
            stream.update(-512,3.65,12);time.sleep(.005)
        self.assertTrue(stream.last_error);self.assertIs(stream.pages['w:fixed:0'],old)
        self.assertFalse(old.closed);self.assertEqual(stream.bytes,budget)
        self.assertEqual(stream.query(-8,3.65,12)['height'],3)
        self.assertEqual(stream.cache.reader.request('stats')['collision_pages'],1)
    def test_directory_ownership_keeps_exterior_light_from_unloaded_group(self):
        flags=[0]*64;flags[63]=8
        self.path.write_bytes(f.root(64,props=[{}],flags=flags));(self.root/'crate.m2').write_bytes(f.prop_m2())
        for gi in (0,63):(self.root/f'rooms_{gi:03}.wmo').write_bytes(f.room(gi,props=[0],flags=flags[gi]))
        stream=self.dungeon();page=self.settle(stream,(-8,3.65,12));prop=page.metadata['props'][0]
        self.assertEqual(prop['owning_groups'],[0,63]);self.assertFalse(prop['light']['interior'])
        self.assertNotIn(63,page.metadata['group_window']);self.assertEqual(len(page.metadata['props']),1)
    def test_archive_directory_does_not_extract_unselected_group_files(self):
        data=self.root/'Data';data.mkdir()
        # A global-WMO WDT names the original archive entry, not the temporary
        # extraction directory or an installation on the host.
        entries={p.name:p.read_bytes() for p in self.root.iterdir() if p.suffix in ('.wmo','.blp')}
        entries['Test.wdt']=f.dungeon_wdt('rooms.wmo');(data/'patch.MPQ').write_bytes(mpq(entries=entries))
        for p in list(self.root.iterdir()):
            if p.suffix in ('.wmo','.wdt','.blp'):p.unlink()
        stream=self.stream(wmos=[],directory=str(PROJECT/'qml'),archive_directory=str(data))
        page=self.settle(stream,(-8,3.65,12));self.assertEqual(len(page.metadata['groups']),64)
        self.assertEqual(len([n for n in stream.cache.archive_entries if n.endswith('.wmo')]),9)
        page=self.settle(stream,(-512,3.65,12));self.assertIn(63,page.metadata['group_window'])
        self.assertEqual(len([n for n in stream.cache.archive_entries if n.endswith('.wmo')]),9)
        self.assertLess(stream.cache.archive_bytes,64*1024*1024)
    def test_hysteresis_avoids_churn_and_escaping_metadata_is_rejected(self):
        directory,_=self.directory();ids=selected(directory,(-8,3.65,12))
        self.assertEqual(selected(directory,(-8.1,3.65,12),ids),ids)
        path=self.root/'rooms_063.wmo';path.unlink();path.symlink_to('/etc/passwd')
        with self.assertRaisesRegex(ValueError,'outside permitted root'):self.directory()

if __name__=='__main__':unittest.main()
