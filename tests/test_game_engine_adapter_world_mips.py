"""Authored levels through real world workers, native decoders and Qt uploads."""
import json,os,struct,tempfile,time,unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtGui import QGuiApplication,QImage
from backend.game_engine_adapter_formats import PROJECT
from backend.game_engine_adapter_streaming import WorldStream,Page
from backend.game_engine_adapter_liquids import prepare_atlas
from backend.game_engine_adapter_mips import image_levels
from tools.world import engine_world_fixtures as world,engine_format_fixtures as formats
APP=QGuiApplication.instance() or QGuiApplication([])

COLORS=((255,0,0,255),(0,255,0,255),(0,0,255,255))
def blp(colors=COLORS,levels=3):
    return formats.blp(width=8,height=8,levels=[bytes((b,g,r,a))*max(1,8>>i)**2 for i,(r,g,b,a) in enumerate(colors[:levels])])

class WorldMips(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=PROJECT/'qml');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.manifest=world.make(self.root,wmos=False,alpha=(15,8,4))
        for name in ('red','green','blue','gold','white'):(self.root/(name+'.blp')).write_bytes(blp())
        self.stream=WorldStream();self.addCleanup(self.stream.close);self.stream.configure(str(self.manifest))
    def settle(self):
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            self.stream.update(-2,2.65,20)
            if self.stream.last_error:self.fail(self.stream.last_error)
            if self.stream.pages and self.stream.pending is None:return self.stream.pages['t:32:32']
            time.sleep(.005)
        self.fail('Actual mip world worker did not settle')
    def test_worker_preserves_all_four_terrain_layers_and_exact_float_lookup(self):
        page=self.settle();batch=page.batches[0]
        self.assertEqual(batch.row['mip_counts'],[3]*4)
        self.assertEqual((batch.tex.size().width(),batch.tex.size().height()),(8,14))
        for texture in [batch.tex]+batch.stages[:3]:
            data=bytes(texture.textureData())
            for y,color in zip((0,8,12),COLORS):self.assertEqual(tuple(data[y*8*4:y*8*4+4]),color)
        table=bytes(batch.mipTableData.textureData())
        self.assertEqual(len(table),16*4*16)
        for layer in range(4):
            self.assertEqual([struct.unpack_from('<4f',table,(layer*16+i)*16) for i in range(3)],[(0.,0.,8.,8.),(0.,8.,4.,4.),(0.,12.,2.,2.)])
        identity=(batch.geo,batch.tex,batch.mipTableData);used=self.stream.bytes
        self.stream.update(-2,2.65,20);self.assertEqual(identity,(batch.geo,batch.tex,batch.mipTableData));self.assertEqual(self.stream.bytes,used)
        self.stream.close();self.assertEqual(self.stream.bytes,0)
    def test_repeated_chunks_share_mip_textures_and_rectangle_table(self):
        first=world.terrain();second=world.terrain(position=(-533.3333/16,0,2),index=(0,1))
        (self.root/'Test_32_32.adt').write_bytes(first+second[second.index(b'KNCM'):])
        page=self.settle();a,b=page.batches
        self.assertIs(a.tex,b.tex);self.assertIs(a.mipTableData,b.mipTableData)
        self.assertEqual(b.row['mip_counts'],[3]*4);self.assertEqual(b.texture_bytes,0)
        self.assertEqual(len(page.shared_mip_tables),1)
    def test_liquid_sheets_preserve_each_frame_and_partial_level_rgb_alpha(self):
        transparent=((100,80,20,0),(30,90,40,0),(60,10,110,0))
        (self.root/'second.blp').write_bytes(blp(transparent))
        def prepare():
            self.stream.cache.deadline=time.monotonic()+5
            try:return prepare_atlas(self.stream.cache,self.root/'Test_32_32.adt','STILL',{'STILL':{'frames':['white.blp','second.blp']}})
            finally:self.stream.cache.deadline=None
        image,material,notes=self.stream.pool.submit(prepare).result(timeout=8)
        self.assertEqual(image_levels(image),[[0,0,16,8],[0,8,8,4],[0,12,4,2]])
        self.assertEqual(material['atlas_grid'],[2,1]);self.assertEqual(material['atlas_size'],[16,14]);self.assertEqual(notes,[])
        for rectangle,first,second in zip(image_levels(image),COLORS,transparent):
            x,y,w,h=rectangle
            self.assertEqual(image.pixelColor(x,y).getRgb(),first)
            self.assertEqual(image.pixelColor(x+w//2,y).getRgb(),second)
    def test_secondary_layer_reused_as_another_chunk_base_keeps_authored_metadata(self):
        first=world.terrain();second=bytearray(world.terrain(position=(-533.3333/16,0,2),index=(0,1)))
        offset=second.index(b'YLCM')+8;struct.pack_into('<I',second,offset,1)
        (self.root/'Test_32_32.adt').write_bytes(first+second[second.index(b'KNCM'):])
        page=self.settle();a,b=page.batches
        self.assertIs(b.tex,a.stages[0])
        self.assertEqual(b.row['mip_levels'],[[0,0,8,8],[0,8,4,4],[0,12,2,2]])
        self.assertEqual(b.row['mip_counts'],[3]*4)
        self.assertEqual(struct.unpack_from('<4f',bytes(b.mipTableData.textureData()),16),(0.,8.,4.,4.))
    def test_liquid_mismatched_authored_chain_rejects_before_page_publication(self):
        page=self.settle();used=self.stream.bytes;pixels=bytes(page.batches[0].tex.textureData())
        (self.root/'partial.blp').write_bytes(blp(levels=2))
        def prepare():
            self.stream.cache.deadline=time.monotonic()+5
            try:return prepare_atlas(self.stream.cache,self.root/'Test_32_32.adt','STILL',{'STILL':{'frames':['white.blp','partial.blp']}})
            finally:self.stream.cache.deadline=None
        with self.assertRaisesRegex(ValueError,'mip layout'):self.stream.pool.submit(prepare).result(timeout=8)
        self.assertEqual(self.stream.bytes,used);self.assertEqual(bytes(page.batches[0].tex.textureData()),pixels);self.assertFalse(page.closed)
    def test_liquid_staging_budget_rejects_next_large_frame_before_decoding(self):
        page=self.settle();used=self.stream.bytes;pixels=bytes(page.batches[0].tex.textureData())
        levels=[bytes((0,0,255,255))*max(1,512>>i)**2 for i in range(10)]
        (self.root/'large.blp').write_bytes(formats.blp(width=512,height=512,levels=levels))
        def prepare():
            self.stream.cache.deadline=time.monotonic()+5
            try:
                with patch.object(self.stream.cache,'decode',wraps=self.stream.cache.decode) as decode:
                    with self.assertRaisesRegex(ValueError,'staging memory'):
                        prepare_atlas(self.stream.cache,self.root/'Test_32_32.adt','STILL',{'STILL':{'frames':['large.blp']*30}},staging_budget=5*1024*1024)
                    self.assertEqual(decode.call_count,1)
            finally:self.stream.cache.deadline=None
        self.stream.pool.submit(prepare).result(timeout=8)
        self.assertEqual(self.stream.bytes,used);self.assertEqual(bytes(page.batches[0].tex.textureData()),pixels);self.assertFalse(page.closed)
    def test_missing_default_suffix_finishes_at_exact_staging_capacity(self):
        directory=self.root/'XTextures'/'river';directory.mkdir(parents=True)
        (directory/'lake_a.1.blp').write_bytes(blp())
        def prepare():
            self.stream.cache.deadline=time.monotonic()+5
            try:return prepare_atlas(self.stream.cache,self.root/'Test_32_32.adt','STILL',{},staging_budget=8*14*4*2)
            finally:self.stream.cache.deadline=None
        image,material,notes=self.stream.pool.submit(prepare).result(timeout=8)
        self.assertEqual(image_levels(image),[[0,0,8,8],[0,8,4,4],[0,12,2,2]])
        self.assertEqual(material['frames'],1);self.assertEqual(notes,['STILL: using 1 of 30 animation frames'])
    def test_native_oversize_liquid_rejects_before_mip_atlas_allocation(self):
        (self.root/'oversize.blp').write_bytes(formats.blp(width=1024,height=1024))
        def prepare():
            self.stream.cache.deadline=time.monotonic()+5
            try:
                with patch('backend.game_engine_adapter_mips.atlas') as atlas:
                    with self.assertRaisesRegex(ValueError,'frame dimensions'):
                        prepare_atlas(self.stream.cache,self.root/'Test_32_32.adt','STILL',{'STILL':{'frames':['oversize.blp']}})
                    atlas.assert_not_called()
            finally:self.stream.cache.deadline=None
        self.stream.pool.submit(prepare).result(timeout=8)
    def test_first_valid_frame_cannot_allocate_beyond_remaining_staging_budget(self):
        def prepare():
            self.stream.cache.deadline=time.monotonic()+5
            try:
                with patch('backend.game_engine_adapter_mips.atlas') as atlas:
                    with self.assertRaisesRegex(ValueError,'staging memory'):
                        prepare_atlas(self.stream.cache,self.root/'Test_32_32.adt','STILL',{'STILL':{'frames':['white.blp']}},staging_budget=8*14*4*2-1)
                    atlas.assert_not_called()
            finally:self.stream.cache.deadline=None
        self.stream.pool.submit(prepare).result(timeout=8)
    def test_default_suffix_never_swallows_capacity_corruption_or_disk_errors(self):
        directory=self.root/'XTextures'/'river';directory.mkdir(parents=True)
        (directory/'lake_a.1.blp').write_bytes(blp())
        original=self.stream.cache._texture
        for error in (ValueError('Archive extraction entry capacity exceeded'),ValueError('Archive extraction memory capacity exceeded'),ValueError('Corrupt MPQ index'),OSError('disk write failed')):
            with self.subTest(error=str(error)):
                def resolve(source,path):
                    if source.endswith('.2.blp'):raise error
                    return original(source,path)
                def prepare():
                    self.stream.cache.deadline=time.monotonic()+5
                    try:
                        with patch.object(self.stream.cache,'_texture',side_effect=resolve):
                            with self.assertRaisesRegex(type(error),str(error)):
                                prepare_atlas(self.stream.cache,self.root/'Test_32_32.adt','STILL',{})
                    finally:self.stream.cache.deadline=None
                self.stream.pool.submit(prepare).result(timeout=8)
    def test_native_weather_frame_uses_authored_levels_and_budgeted_lookup(self):
        art=self.root/'textures'/'weather';art.mkdir(parents=True)
        for name in ('raindrop01','raindropsplash01','snowflake01','snowmist01'):(art/(name+'.blp')).write_bytes(blp())
        value={'view':{'eye':[0,10,0],'forward':[0,0,-1],'up':[0,1,0],'fov':60},'player':[0,10,0],'facing':[0,0,-1],'speed':0,'collision_revision':0,'fog':[0,0,0]}
        def prepare():
            reader=self.stream.cache._reader();reader.request('weather_set',now_ms=0,kind=1,grade=1,instant=True,quality=3,sound_id=0)
            for i in range(140):reader.request('weather_frame',now_ms=i*17,draw=False,**value)
            return self.stream.weather._prepare(reader,dict(value,now_ms=2400,draw=True))
        packet=self.stream.pool.submit(prepare).result(timeout=8)
        future=Future();future.set_result(packet);self.stream.weather.future=future;self.stream.weather.finish()
        self.assertFalse(self.stream.weather.error);self.assertTrue(self.stream.weather.layers)
        for layer in self.stream.weather.layers.values():
            self.assertEqual(layer.batch.row['mip_counts'],[3]);self.assertEqual(layer.batch.row['mip_levels'],[[0,0,8,8],[0,8,4,4],[0,12,2,2]])
            self.assertEqual(len(bytes(layer.batch.mipTableData.textureData())),256)
            self.assertGreaterEqual(layer.bytes,512+8*14*4*2)
        self.stream.close();self.assertEqual(self.stream.bytes,0)
    def test_untrusted_rectangle_metadata_rejects_outside_upload(self):
        image=QImage(8,14,QImage.Format_RGBA8888)
        for rows in ([[0,0,9,8]],[[0,12,2,3]],[[0,0,True,1]],[],[[0,0,1,1]]*17):
            with self.subTest(rows=rows):
                image.setText('GG_MIP_LEVELS',json.dumps(rows))
                with self.assertRaises(ValueError):image_levels(image)

if __name__=='__main__':unittest.main()
