"""Authored BLP levels through the real native reader and retained Qt batch."""
import copy,os,struct,tempfile,unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtGui import QGuiApplication
from backend.game_engine_adapter_formats import AssetCache,NativeFormats,PROJECT
from backend.game_engine_adapter_mips import atlas
from tools.world import engine_format_fixtures as f
APP=QGuiApplication.instance() or QGuiApplication([])

def fixture(size=8,levels=3):
    return f.blp(width=size,height=size,levels=[bytes(c)*max(1,size>>i)**2 for i,c in enumerate([(0,0,255,255),(0,255,0,255),(255,0,0,255)][:levels])])

def skinned():
    data=bytearray(f.m2());offset=struct.unpack_from('<II',data,0x5c)[1]
    struct.pack_into('<4I',data,offset,11,1,0,0) # Original Monster1 replaceable.
    return bytes(data)

class Mips(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=PROJECT/'qml');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.cache=AssetCache();self.addCleanup(self.cache.close)
        self.path=self.root/'authored.blp';self.path.write_bytes(fixture())
    def test_original_pixels_partial_chain_and_atlas_layout(self):
        metadata,data=self.cache.decode(self.path,mip_chain=True);image,rows=atlas(metadata,data)
        self.assertEqual(rows,[[0,0,8,8],[0,8,4,4],[0,12,2,2]])
        self.assertEqual((image.width(),image.height()),(8,14))
        self.assertEqual([image.pixelColor(0,row[1]).getRgb() for row in rows],[(255,0,0,255),(0,255,0,255),(0,0,255,255)])
        self.assertEqual(metadata['mip_count'],3);self.assertEqual(len(data),(64+16+4)*4)
    def test_retained_batch_appearance_change_restores_regular_texture(self):
        model=self.root/'model.m2';model.write_bytes(skinned())
        live=self.cache.live_model(model,{'id':'mips','play':{}})
        live.appearance({'appearance':{'skins':[str(self.path),None,None]}})
        batch=live.batches[0];self.assertEqual(len(batch.row['mip_levels']),3)
        memory=self.cache.live_bytes;geo=batch.geo;tex=batch.tex
        self.cache.live_model(model,{'id':'mips','clock_ms':100,'play':{}})
        self.assertIs(batch.geo,geo);self.assertIs(batch.tex,tex);self.assertEqual(self.cache.live_bytes,memory)
        live.appearance({'appearance':{'skins':[None,None,None]}});self.assertFalse(batch.row['mip_levels'])
        self.cache.close();self.assertEqual(self.cache.live_bytes,0)
    def test_invalid_levels_rejected_without_padding_or_trailing_data(self):
        metadata,data=self.cache.decode(self.path,mip_chain=True)
        for field,bad in (('offset',1),('width',9),('height',9),('bytes',1),('mip',5)):
            changed=copy.deepcopy(metadata);changed['levels'][1][field]=bad
            with self.assertRaises(ValueError):atlas(changed,data)
        for changed in (data[:-1],data+b'x'):
            with self.assertRaises(ValueError):atlas(metadata,changed)
    def test_single_level_is_preserved(self):
        self.path.write_bytes(fixture(levels=1));metadata,data=self.cache.decode(self.path,mip_chain=True);image,rows=atlas(metadata,data)
        self.assertEqual(rows,[[0,0,8,8]]);self.assertEqual(image.height(),8)
    def test_bad_texture_does_not_replace_retained_pixels_and_recovers(self):
        model=self.root/'model.m2';model.write_bytes(skinned())
        live=self.cache.live_model(model,{'id':'recover','play':{}})
        live.appearance({'appearance':{'skins':[str(self.path),None,None]}})
        before=bytes(live.batches[0].tex.textureData());memory=self.cache.live_bytes
        bad=self.root/'bad.blp';bad.write_bytes(fixture()[:148])
        with self.assertRaises(ValueError):live.appearance({'appearance':{'skins':[str(bad),None,None]}})
        self.assertEqual(bytes(live.batches[0].tex.textureData()),before);self.assertEqual(self.cache.live_bytes,memory)
        bad.write_bytes(fixture(levels=1));live.appearance({'appearance':{'skins':[str(bad),None,None]}})
        self.assertEqual(len(live.batches[0].row['mip_levels']),1)

if __name__=='__main__':unittest.main()
