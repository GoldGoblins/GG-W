"""Original MPQ patch ordering and root-restricted on-demand runtime extraction."""
import os,sys,tempfile,unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
from tools.world import engine_format_fixtures as fixture
from backend.game_engine_adapter_formats import NativeFormats,AssetCache
from PySide6.QtGui import QGuiApplication
APP=QGuiApplication.instance() or QGuiApplication([])
class Archives(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(dir=PROJECT/'qml');self.root=Path(self.directory.name);self.addCleanup(self.directory.cleanup)
        self.data=self.root/'Data';self.data.mkdir();self.reader=NativeFormats(self.root);self.addCleanup(self.reader.close)
    def write(self,name,plain=b'GG',entry='Interface/Test.txt',deleted=False):
        (self.data/name).write_bytes(fixture.mpq(entry,plain,deleted=deleted))
    def mount(self):return self.reader.request('mount_chain',path=str(self.data))
    def read(self,entry='Interface/Test.txt'):return NativeFormats._unpack(self.reader.request('chain_read',entry=entry))
    def test_original_priority_case_glob_and_tombstone(self):
        self.write('model.MPQ',b'base');self.write('PATCH.mpq',b'patch');self.write('Patch-Z.MPQ',b'last');self.write('patch-10.MPQ',b'ignored')
        self.mount();meta,blob=self.read('interface\\TEST.TXT');self.assertEqual(blob,b'last');self.assertEqual(meta['archive'],'Patch-Z.MPQ')
        self.write('speech2.MPQ',b'speech');self.mount();self.assertEqual(self.read()[1],b'speech')
        self.write('speech2.MPQ',deleted=True);self.mount()
        with self.assertRaisesRegex(ValueError,'deleted from patch chain'):self.read()
        self.assertEqual(self.reader.request('ping'),{'abi':1})
    def test_bounds_root_symlinks_and_large_entry(self):
        self.write('model.MPQ')
        with tempfile.TemporaryDirectory() as outside:
            foreign=Path(outside)/'outside.mpq';foreign.write_bytes(fixture.mpq());(self.data/'patch.MPQ').symlink_to(foreign)
            with self.assertRaisesRegex(ValueError,'outside'):self.mount()
        (self.data/'patch.MPQ').unlink();(self.data/'patch.MPQ').write_bytes(fixture.mpq(file_size=0xffffffff));self.mount()
        with self.assertRaisesRegex(ValueError,'capacity'):self.read()
    def test_on_demand_m2_texture_pose_and_cleanup(self):
        self.write('model.MPQ',fixture.animated_m2(),entry='GG/Panel.m2');self.write('texture.MPQ',fixture.blp(),entry='GG/gold.blp')
        cache=AssetCache();self.addCleanup(cache.close);cache.mount_chain(self.data)
        model=cache.resolve('gg/PANEL.M2');self.assertTrue(model.is_file());self.assertEqual(len(cache.archive_entries),1)
        live=cache.live_model(model,{'id':'a','play':{'anim_id':7,'cursor_ms':500}})
        self.assertEqual(len(cache.archive_entries),2);self.assertEqual(live.batches[0].tex.size().width(),2)
        texture=cache.texture_path('GG/GOLD');self.assertEqual(texture.suffix.lower(),'.blp')
        cache.reader.close();cache.resolve('gg/gold.blp');cache.live_model(model,{'id':'a'});self.assertFalse(cache.reader.closed)
        self.assertEqual(cache.archive_bytes,len(fixture.animated_m2())+len(fixture.blp()))
        stage=Path(cache.archive_directory.name);cache.close();self.assertFalse(stage.exists());self.assertEqual(cache.live_bytes,0)
    def test_tombstone_does_not_extract_or_fall_back(self):
        self.write('model.MPQ',fixture.blp(),entry='GG/gold.blp');self.write('patch.MPQ',entry='GG/gold.blp',deleted=True)
        cache=AssetCache();self.addCleanup(cache.close);cache.mount_chain(self.data)
        with self.assertRaisesRegex(ValueError,'deleted from patch chain'):cache.resolve('GG/gold.blp')
        self.assertIsNone(cache.archive_directory);self.assertEqual(cache.archive_bytes,0)
        with self.assertRaisesRegex(ValueError,'Escaping'):cache.resolve('../escape.blp')
    def test_original_sound_catalog_typed_schema_id_and_name(self):
        self.write('dbc.MPQ',fixture.sound_dbc(),entry='DBFilesClient/SoundEntries.dbc');self.mount()
        kit=self.reader.request('sound_kit',kit=73)
        self.assertEqual(kit['name'],'GG_Test');self.assertEqual(kit['files'],[['GG\\stereo.wav',1]])
        self.assertAlmostEqual(kit['volume'],.4);self.assertEqual((kit['flags'],kit['eax'],kit['near'],kit['far']),(32,2,1,60))
        self.assertEqual(self.reader.request('sound_kit',kit='gg_test'),kit)
        with self.assertRaisesRegex(ValueError,'unknown sound kit'):self.reader.request('sound_kit',kit=74)
    def test_archive_addons_includes_raw_lua_demand_saved_and_priority(self):
        from backend.game_engine_adapter_ui import GgEngineUI
        entries={
            'Interface/AddOns/Raw/Raw.toc':b'## Interface: 11200\n## Title: Sch\xe4tze\n## SavedVariables: A\n## SavedVariables: B\nmain.xml',
            'Interface/AddOns/Raw/main.xml':b'<Ui><Include file="nested/frame.xml"/></Ui>',
            'Interface/AddOns/Raw/nested/frame.xml':b'<Ui><Script file="literal.lua"/><Frame name="ArchiveFrame" parent="UIParent"><Size><AbsDimension x="40" y="20"/></Size><Anchors><Anchor point="TOPLEFT"/></Anchors></Frame></Ui>',
            'Interface/AddOns/Raw/nested/literal.lua':b'rawByte=string.byte("\xe4") rawLength=string.len("\xe4") A={v=1} B={v=2}',
            'Interface/AddOns/Demand/Demand.toc':b'## Interface: 11200\n## LoadOnDemand: 1\n## RequiredDependencies: Raw\n## SavedVariables: DemandState\nmain.lua',
            'Interface/AddOns/Demand/main.lua':b'assert(rawByte==228) DemandState={v=3} demandLoaded=true',
        }
        entries['(listfile)']=b'Interface/AddOns/Raw/Raw.toc\nInterface/AddOns/Demand/Demand.toc'
        (self.data/'patch.MPQ').write_bytes(fixture.mpq(entries=entries))
        self.write('model.MPQ',b'rawByte=0',entry='Interface/AddOns/Raw/nested/literal.lua')
        loose=self.root/'loose';(loose/'Raw').mkdir(parents=True)
        (loose/'Raw/Raw.toc').write_text('main.lua');(loose/'Raw/main.lua').write_text('rawByte=0')
        cache=AssetCache();cache.mount_chain(self.data);self.addCleanup(cache.close)
        ui=GgEngineUI();self.addCleanup(ui.close);saves=self.root/'saves'
        loaded=ui.load_addons(loose,saves,assets=cache)
        self.assertEqual(loaded,[{'id':'Raw','title':'Schätze'}])
        self.assertEqual(ui.evaluate('return rawByte,rawLength,B.v'),[228,1,2])
        self.assertTrue(any(r.get('owner')=='ArchiveFrame' for r in ui.frames()))
        ui.execute("assert(LoadAddOn('Demand')) A.v=11 B.v=12 DemandState.v=13")
        self.assertEqual(ui.evaluate('return demandLoaded'),[True]);ui.save();ui.close()
        restored=GgEngineUI();self.addCleanup(restored.close);restored.load_addons(loose,saves,assets=cache)
        restored.execute("assert(LoadAddOn('Demand'))")
        self.assertEqual(restored.evaluate('return A.v,B.v,DemandState.v'),[11,12,13])
        self.assertFalse(restored.errors);self.assertFalse(restored.warnings)
        self.assertEqual(cache.archive_bytes,0);self.assertIsNone(cache.archive_directory)
    def test_archive_listing_preflight(self):
        (self.data/'patch.MPQ').write_bytes(fixture.mpq('(listfile)',b'GG',file_size=2*1024*1024))
        self.mount()
        with self.assertRaisesRegex(ValueError,'listing capacity'):self.reader.request('chain_list')
        self.assertEqual(self.reader.request('ping'),{'abi':1})
    def test_original_core_toc_runs_before_addons_with_raw_bytes_and_nested_refs(self):
        from backend.game_engine_adapter_ui import GgEngineUI
        entries={
            'Interface/FrameXML/FrameXML.toc':b'## Interface: 11200\nfirst.lua\nMain.xml\nlast.lua',
            'Interface/FrameXML/first.lua':b'coreOrder="first" coreByte=string.byte("\xe4")',
            'Interface/FrameXML/Main.xml':b'<Ui><Include file="Nested/Template.xml"/></Ui>',
            'Interface/FrameXML/Nested/Template.xml':b'<Ui><Script file="code.lua"/><Frame name="CoreTemplate" virtual="true"><Size><AbsDimension x="44" y="22"/></Size></Frame></Ui>',
            'Interface/FrameXML/Nested/code.lua':b'coreOrder=coreOrder..",nested"',
            'Interface/FrameXML/last.lua':b'coreOrder=coreOrder..",last"',
            'Interface/FrameXML/Bindings.xml':b'<Bindings><Binding name="GGCORE">corePressed=true</Binding></Bindings>',
            'Interface/AddOns/Child/Child.toc':b'## Interface: 11200\nchild.xml',
            'Interface/AddOns/Child/child.xml':b'<Ui><Frame name="CoreChild" inherits="CoreTemplate" parent="UIParent"><Anchors><Anchor point="TOPLEFT"/></Anchors></Frame><Script>assert(coreOrder=="first,nested,last") assert(coreByte==228) childLoaded=true</Script></Ui>',
            '(listfile)':b'Interface/AddOns/Child/Child.toc',
        }
        (self.data/'patch.MPQ').write_bytes(fixture.mpq(entries=entries))
        cache=AssetCache();cache.mount_chain(self.data);self.addCleanup(cache.close)
        ui=GgEngineUI();self.addCleanup(ui.close);ui.load_addons(self.root/'empty',assets=cache)
        self.assertEqual(ui.evaluate("SetBinding('K','GGCORE') return childLoaded,CoreChild:GetWidth(),CoreChild:GetHeight()"),[True,44,22])
        ui.request('key',key='K');self.assertEqual(ui.evaluate('return corePressed'),[True])
        self.assertEqual(len(ui.core_files),3);self.assertFalse(ui.errors);self.assertFalse(ui.warnings)
        self.assertEqual(cache.archive_bytes,0)
    def test_loose_core_case_insensitive_paths_and_escape_rejected(self):
        from backend.game_engine_adapter_ui import GgEngineUI
        core=self.root/'core';core.mkdir()
        (core/'FrameXML.toc').write_bytes(b'FIRST.LUA\nMain.xml')
        (core/'first.lua').write_bytes(b'looseCore=7')
        (core/'Main.xml').write_bytes(b'<Ui><Script file="second.lua"/></Ui>')
        (core/'SECOND.lua').write_bytes(b'looseCore=looseCore+1')
        ui=GgEngineUI();self.addCleanup(ui.close);ui.load_addons(self.root/'empty',core_root=core)
        self.assertEqual(ui.evaluate('return looseCore'),[8]);self.assertFalse(ui.errors);self.assertFalse(ui.warnings)
        (core/'FrameXML.toc').write_bytes(b'../outside.lua')
        other=GgEngineUI();self.addCleanup(other.close)
        with self.assertRaisesRegex(ValueError,'Escaping core source'):other.load_addons(self.root/'empty',core_root=core)
    def test_broken_core_file_does_not_prevent_later_files_and_addons(self):
        from backend.game_engine_adapter_ui import GgEngineUI
        core=self.root/'core';core.mkdir();addons=self.root/'addons';(addons/'Probe').mkdir(parents=True)
        (core/'FrameXML.toc').write_bytes(b'missing.lua\nbroken.lua\ngood.lua')
        (core/'broken.lua').write_bytes(b'error("core failure")')
        (core/'good.lua').write_bytes(b'coreContinued=true')
        (addons/'Probe/Probe.toc').write_bytes(b'main.lua')
        (addons/'Probe/main.lua').write_bytes(b'assert(coreContinued) addonContinued=true')
        ui=GgEngineUI();self.addCleanup(ui.close);ui.load_addons(addons,core_root=core)
        self.assertEqual(ui.evaluate('return coreContinued,addonContinued'),[True,True])
        self.assertEqual(len(ui.errors),2);self.assertEqual(ui.core_files,['Interface/FrameXML/good.lua'])
if __name__=='__main__':unittest.main()
