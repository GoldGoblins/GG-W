"""Real binary decoding, generated Qt models, bounds and worker lifetime."""
from pathlib import Path
import hashlib,json,os,signal,struct,sys,tempfile,time,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
from tools.world import engine_format_fixtures as fixtures
from backend.game_engine_adapter_formats import NativeFormats,AssetCache,image_from_rgba,available
from backend.game_engine_adapter_assets import asset_path,texture_path
from PySide6.QtGui import QGuiApplication,QImage,QPainter
from PySide6.QtQuick import QQuickItem
APP=QGuiApplication.instance() or QGuiApplication([])

def glb_document(path):
    data=path.read_bytes();magic,version,size=struct.unpack_from('<III',data)
    assert (magic,version,size)==(0x46546c67,2,len(data))
    count,kind=struct.unpack_from('<II',data,12);assert kind==0x4e4f534a
    return json.loads(data[20:20+count]),data[28+count:]

class FormatTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(prefix='.gg-format-test-',dir=PROJECT/'qml');self.root=Path(self.directory.name)
        self.reader=NativeFormats(self.root);self.addCleanup(self.directory.cleanup);self.addCleanup(self.reader.close)
    def decode(self,name,blob,**options):
        path=self.root/name;path.write_bytes(blob);return self.reader.decode(path,**options)
    def test_original_sources_and_verified_binary(self):
        from tests.engine_source_provenance import assert_source_integrity
        source=PROJECT/'native/engine-formats';provenance,_=assert_source_integrity(self,source)
        readers=[name for name,path in provenance['source_paths'].items() if not path.startswith(('crates/engine-protocol/','crates/engine-srp/'))]
        self.assertEqual(len(readers),283)
        for name in ('crates/engine-protocol/src/lib.rs','crates/engine-srp/src/vanilla_header.rs'):
            self.assertIn(name,provenance['source_paths'].values())
        self.assertTrue(available())
    def test_blp_raw_bgra_and_mip(self):
        levels=[bytes([3,2,1,127])*16,bytes([30,20,10,255])*4,bytes([1,1,1,255])]
        data=fixtures.blp(width=4,height=4,levels=levels);meta,pixels=self.decode('raw.blp',data)
        self.assertEqual((meta['width'],meta['height'],meta['mip_count']),(4,4,2));self.assertEqual(pixels,bytes([1,2,3,127])*16)
        meta,pixels=self.reader.decode(self.root/'raw.blp',mip=1);self.assertEqual(pixels,bytes([10,20,30,255])*4);self.assertEqual(meta['width'],2)
        # Original 1.12 reader's chain formula stops before the stored 1x1.
        with self.assertRaisesRegex(ValueError,'missing BLP mip'):self.reader.decode(self.root/'raw.blp',mip=2)
    def test_blp_palette_alpha_depths(self):
        palette=bytearray(1024);palette[4:8]=bytes([20,40,60,0])
        for bits,alpha,expected in ((0,b'', [255]*4),(1,b'\x05',[255,0,255,0]),(4,b'\xf0\x84',[0,255,68,136]),(8,b'\x00\x40\x80\xff',[0,64,128,255])):
            with self.subTest(bits=bits):
                meta,pixels=self.decode('palette.blp',fixtures.blp(1,bits,levels=[b'\x01'*4+alpha],palette=palette))
                self.assertEqual(list(pixels[3::4]),expected);self.assertEqual(pixels[:3],bytes([60,40,20]))
    def test_blp_dxt1_dxt3_dxt5(self):
        colour=struct.pack('<HHI',0xf800,0,0)
        for alpha_type,bits,block,expected in ((0,0,colour,255),(1,8,b'\x88'*8+colour,136),(7,8,b'\x80\x00'+bytes(6)+colour,128)):
            with self.subTest(alpha_type=alpha_type):
                meta,pixels=self.decode('dxt.blp',fixtures.blp(2,bits,alpha_type,4,4,[block]))
                self.assertEqual(pixels,bytes([255,0,0,expected])*16)
    def test_tga_orientation_rle_and_palette(self):
        # Disk bottom row blue, top row red; decoder must return top first.
        _,pixels=self.decode('bottom.tga',fixtures.tga(1,2,bytes([255,0,0,255,0,0,255,127]),descriptor=8))
        self.assertEqual(pixels,bytes([255,0,0,127,0,0,255,255]))
        _,pixels=self.decode('rle.tga',fixtures.tga(4,1,b'\x82\x00\x00\xff\x00\x00\xff\x00',kind=10,bpp=24))
        self.assertEqual(pixels,bytes([255,0,0,255])*3+bytes([0,255,0,255]))
        _,pixels=self.decode('palette.tga',fixtures.tga(2,1,b'\x01\x00',kind=1,bpp=8,palette=bytes([0,0,255,255,255,0,0,127])))
        self.assertEqual(pixels,bytes([0,0,255,127,255,0,0,255]))
    def test_m2_indices_basis_and_materials(self):
        meta,_=self.decode('panel.m2',fixtures.m2(),geometry=True)
        self.assertEqual(meta['geometry']['indices'],[0,1,2]);self.assertEqual(meta['geometry']['positions'],[[-1,-1,0],[1,-1,0],[0,1,0]])
        self.assertEqual(meta['geometry']['primitives'][0]['texture'],0);self.assertTrue(meta['geometry']['primitives'][0]['unlit'])
        self.assertEqual(meta['textures'][0],{'path':'gold.blp','wrap_u':True,'wrap_v':False,'replaceable':False})
        self.assertEqual(self.reader.decode(self.root/'panel.m2')[0]['geometry'],None)
    def test_m2_corrupt_indices_and_nonfinite(self):
        with self.assertRaisesRegex(ValueError,'skin vertex'):self.decode('broken.m2',fixtures.m2(invalid_index=True),geometry=True)
        data=bytearray(fixtures.m2());vertex_offset=struct.unpack_from('<I',data,72)[0];struct.pack_into('<f',data,vertex_offset,float('nan'))
        with self.assertRaisesRegex(ValueError,'non-finite'):self.decode('broken.m2',data,geometry=True)
        self.assertEqual(self.reader.request('ping'),{'abi':1})
    def test_wmo_root_group_and_material(self):
        meta,_=self.decode('hall.wmo',fixtures.wmo_root(blend=4));self.assertEqual((meta['groups'],meta['materials'][0]['blend']),(1,4))
        meta,_=self.decode('hall_000.wmo',fixtures.wmo_group(),geometry=True)
        self.assertEqual(meta['format'],'WMO_GROUP');self.assertEqual(meta['geometry']['indices'],[0,1,2]);self.assertEqual(meta['geometry']['primitives'][0],{'start':0,'count':3,'material':0})
    def test_adt_terrain_height_holes_and_wdt_tile(self):
        meta,_=self.decode('terrain.adt',fixtures.adt());row=meta['chunks'][0]
        self.assertEqual((row['x'],row['y'],row['holes'],row['impassable']),(3,7,1,True));self.assertEqual(row['position'],[10,20,30]);self.assertEqual(row['heights'],[i*.25 for i in range(145)])
        meta,_=self.decode('world.wdt',fixtures.wdt());self.assertEqual(meta['tiles'],[[3,7]])
    def test_dbc_typed_records_strings_and_schema_validation(self):
        meta,_=self.decode('records.dbc',fixtures.dbc(),schema=['uint32','int32','float32','string'])
        self.assertEqual(meta['rows'],[[73,-9,1.25,'Goblin']])
        for schema in (['uint32'],['uint32','int32','float32','unknown'],'bad'):
            with self.subTest(schema=schema),self.assertRaises(ValueError):self.reader.decode(self.root/'records.dbc',schema=schema)
        data=bytearray(fixtures.dbc());struct.pack_into('<I',data,32,9999)
        with self.assertRaises(ValueError):self.decode('records.dbc',data,schema=['uint32','int32','float32','string'])
    def test_mpq_stored_compressed_and_deleted(self):
        meta,blob=self.decode('stored.mpq',fixtures.mpq(),entry='interface\\test.TXT');self.assertEqual(blob,b'GG native readers')
        plain=b'GG compressed sector '*400
        # One 4K sector in this fixture, so keep plain below that sector size.
        plain=plain[:3000];meta,blob=self.decode('compressed.mpq',fixtures.mpq(plain=plain,compressed=True),entry='Interface/Test.txt');self.assertEqual(blob,plain)
        meta,blob=self.decode('deleted.mpq',fixtures.mpq(plain=b'',deleted=True),entry='Interface/Test.txt');self.assertTrue(meta['deleted']);self.assertEqual(blob,b'')
        with self.assertRaisesRegex(ValueError,'not found'):self.reader.decode(self.root/'stored.mpq',entry='missing.txt')
    def test_corrupt_archive_and_texture_capacities(self):
        with self.assertRaisesRegex(ValueError,'capacity'):self.decode('huge.mpq',fixtures.mpq(file_size=0xffffffff),entry='Interface/Test.txt')
        with self.assertRaisesRegex(ValueError,'capacity'):self.decode('huge.blp',fixtures.blp(width=1,height=1)[:12]+struct.pack('<II',8192,8192))
        for name in ('corrupt.blp','corrupt.tga','corrupt.m2','corrupt.wmo','corrupt.adt','corrupt.wdt','corrupt.dbc','corrupt.mpq'):
            with self.subTest(name=name),self.assertRaises(ValueError):self.decode(name,b'broken')
        self.assertEqual(self.reader.request('ping'),{'abi':1})
    def test_root_escape_and_symlink_rejected(self):
        with tempfile.TemporaryDirectory(prefix='gg-outside-assets-') as outer:
            path=Path(outer)/'outside.blp';path.write_bytes(fixtures.blp())
            if os.name=='nt':
                from backend.application_paths import expose_directory
                expose_directory(self.root/'escape',Path(outer))
                link=self.root/'escape/outside.blp'
            else:
                link=self.root/'escape.blp';link.symlink_to(path)
            for candidate in (path,link):
                with self.subTest(path=candidate),self.assertRaisesRegex(ValueError,'outside'):self.reader.decode(candidate)
            with self.assertRaises(ValueError):asset_path(link)
    def test_worker_deadline_preserves_parent(self):
        worker=NativeFormats(self.root)
        if os.name=='nt':
            import psutil
            process=psutil.Process(worker.process.pid)
            for child in reversed(process.children(recursive=True)):child.suspend()
            process.suspend()
        else:os.kill(worker.process.pid,signal.SIGSTOP)
        started=time.monotonic()
        try:
            with self.assertRaises(TimeoutError):worker.request('ping',timeout=.05)
            self.assertTrue(worker.closed);self.assertIsNotNone(worker.process.returncode);self.assertLess(time.monotonic()-started,2)
            self.assertEqual(self.reader.request('ping'),{'abi':1})
        finally:worker.close()
    def test_cache_embedded_textures_sampler_and_cleanup(self):
        fixtures.write_preview_assets(self.root);cache=AssetCache();self.addCleanup(cache.close)
        model=cache.model(self.root/'panel.m2');document,binary=glb_document(model)
        self.assertEqual(document['samplers'],[{'wrapS':10497,'wrapT':33071}]);self.assertEqual(len(document['meshes']),1)
        self.assertEqual(document['materials'][0]['extensions'],{'KHR_materials_unlit':{}})
        view=document['bufferViews'][document['images'][0]['bufferView']];png=binary[view['byteOffset']:view['byteOffset']+view['byteLength']]
        image=QImage.fromData(png,'PNG');self.assertEqual(image.pixelColor(0,0).getRgb(),(240,176,36,255))
        self.assertEqual(cache.model(self.root/'panel.m2'),model);self.assertEqual(len(cache.models),1)
        cache.close();self.assertFalse(model.exists());self.assertTrue(cache.reader.closed)
    def test_wmo_conversion_groups_blend_and_missing_dependencies(self):
        fixtures.write_preview_assets(self.root);cache=AssetCache();self.addCleanup(cache.close)
        document,_=glb_document(cache.model(self.root/'hall.wmo'));self.assertEqual(len(document['meshes']),1)
        (self.root/'mod.wmo').write_bytes(fixtures.wmo_root(blend=4));(self.root/'mod_000.wmo').write_bytes(fixtures.wmo_group())
        cache.model(self.root/'mod.wmo');self.assertTrue(any('additive/modulate' in v for v in cache.adaptations))
        (self.root/'bad.wmo').write_bytes(fixtures.wmo_root())
        with self.assertRaises((ValueError,OSError)):cache.model(self.root/'bad.wmo')
        (self.root/'bad_000.wmo').write_bytes(fixtures.wmo_group(material=1))
        cache.failures.clear()
        with self.assertRaisesRegex(ValueError,'material index'):cache.model(self.root/'bad.wmo')
    def test_failed_model_backoff_and_worker_recovery(self):
        fixtures.write_preview_assets(self.root);cache=AssetCache();self.addCleanup(cache.close)
        original=fixtures.m2(invalid_index=True);path=self.root/'broken.m2';path.write_bytes(original)
        with self.assertRaises(ValueError):cache.model(path)
        reader=cache.reader;self.assertEqual(len(cache.failures),1)
        reader.decode=lambda *args,**kwargs: self.fail('bad model decoded again during backoff')
        with self.assertRaises(ValueError):cache.model(path)
        reader.close();path.write_bytes(fixtures.m2());model=cache.model(path)
        self.assertTrue(model.is_file());self.assertIsNot(cache.reader,reader)
    def test_case_insensitive_extensionless_paths_and_qt_texture(self):
        fixtures.write_preview_assets(self.root);relative=self.root.relative_to(PROJECT/'qml').as_posix()
        self.assertEqual(texture_path(relative.upper()+'/GOLD'),self.root/'gold.blp')
        self.assertEqual(asset_path((self.root/'gold.blp').as_uri()),self.root/'gold.blp')
        from backend.game_engine_adapter_canvas import GgEngineCanvas
        class Runtime:lua=None
        parent=QQuickItem();parent.setWidth(64);parent.setHeight(64);canvas=GgEngineCanvas(Runtime(),parent);self.addCleanup(canvas.close)
        image=canvas.image(relative.upper()+'/GOLD');self.assertFalse(image.isNull());self.assertEqual(image.pixelColor(0,0).getRgb(),(240,176,36,255));self.assertEqual(canvas.missing,set())
        canvas.base_rows=[{'kind':'Texture','x':0,'y':0,'width':64,'height':64,'alpha':1,'path':relative+'/blue.tga'}]
        rendered=QImage(64,64,QImage.Format_RGBA8888);rendered.fill(0);painter=QPainter(rendered);canvas.paint(painter);painter.end()
        self.assertEqual(rendered.pixelColor(32,32).getRgb(),(50,160,220,255))

if __name__=='__main__':unittest.main()
