"""Real native packing, audio signal invariants, Lua lifetime and Qt interfaces."""
import array,ctypes as C,importlib.util,json,math,os,random,shutil,struct,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ['GG_GAME_PRESENTATION_NATIVE']='required'
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
from backend import game_engine_native_presentation as core
from backend.game_engine_ecology_render import FloraInstances,instance_bytes
from backend.game_engine_presentation import Presentation,load_toc
from PySide6.QtGui import QGuiApplication
APP=QGuiApplication.instance() or QGuiApplication([])

def samples(data):
    out=array.array('f');out.frombytes(data);return out
def rms(rows):return math.sqrt(sum(x*x for x in rows)/len(rows))
def row(**overrides):return {'id':'a','x':1,'y':2,'z':3,'scale':1,'yaw':0,**overrides}
def lua():
    if not (PROJECT/'qml/game/lua/host.lua').is_file():
        raise unittest.SkipTest('Requires the optional game Lua host content')
    vm=core.Lua();vm.execute((PROJECT/'qml/game/lua/host.lua').read_text());return vm

class PresentationTests(unittest.TestCase):
    def setUp(self):
        self.state=tempfile.TemporaryDirectory(prefix='gg-presentation-test-state-');self.addCleanup(self.state.cleanup)
        state_env=patch.dict(os.environ,{'XDG_STATE_HOME':self.state.name});state_env.start();self.addCleanup(state_env.stop)
    def test_instance_matrix_colour_reference(self):
        rng=random.Random(52)
        rows=[row(id=str(i),x=rng.uniform(-2000,2000),y=rng.uniform(-100,100),z=rng.uniform(-2000,2000),scale=rng.uniform(.01,10),
                  pitch=rng.uniform(-180,180),yaw=rng.uniform(-180,180),roll=rng.uniform(-180,180),tint=rng.uniform(0,1),
                  editor_color='#da7591' if i%3==0 else None,alpha=.5 if i%7==0 else 1) for i in range(513)]
        actual=struct.unpack('<'+str(len(rows)*20)+'f',core.pack_instances(rows))
        expected=struct.unpack('<'+str(len(rows)*20)+'f',b''.join(instance_bytes(r) for r in rows))
        for a,b in zip(actual,expected):self.assertAlmostEqual(a,b,delta=max(1e-7,abs(b)*1e-6))
    def test_qt_buffer_flags_and_retention(self):
        table=FloraInstances();table.replace([row()],1)
        self.assertEqual(table.pack_backend,'CPP');self.assertEqual(table.pack_calls,1)
        table.replace([row()],2);self.assertEqual(table.pack_calls,1);self.assertEqual(table.revision,2)
        table.replace([row(alpha=.5)],3)
        self.assertTrue(table.hasTransparency());self.assertTrue(table.depthSortingEnabled());self.assertEqual(table.getInstanceBuffer()[1],1)
        self.assertEqual(struct.unpack('<20f',bytes(table.getInstanceBuffer()[0]))[15],.5)
        with self.assertRaises(ValueError):table.replace([row(x=float('nan'))],4)
        self.assertEqual(table.revision,3);self.assertEqual(table.getInstanceBuffer()[1],1)
    def test_qt_material_lanes(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtQml import QQmlEngine,QQmlComponent
        engine=QQmlEngine()
        for lane in range(7):
            component=QQmlComponent(engine)
            source=('import QtQuick3D\nimport "'+(PROJECT/'qml/components').as_uri()+'"\nGgBatchMaterial {renderLane: '+str(lane)+'; property bool writes: depthDrawMode === Material.OpaqueOnlyDepthDraw;property bool blends: sourceBlend !== CustomMaterial.NoBlend}')
            component.setData(source.encode(),QUrl.fromLocalFile(str(PROJECT/'test-material.qml')))
            obj=component.create();self.assertIsNotNone(obj,[str(e) for e in component.errors()])
            self.assertEqual(obj.property('writes'),lane<2);self.assertEqual(obj.property('blends'),lane>=2);obj.deleteLater()
    def test_raw_pack_invalid_is_transactional(self):
        lib=core.library();rows=(core.Instance*2)(core.Instance(0,0,0,1,0,0,0,1,1,1,1,1),core.Instance(0,0,float('nan'),1,0,0,0,1,1,1,1,1))
        out=(C.c_float*40)(*([17]*40));self.assertEqual(lib.ggm_pack_instances(rows,2,out,2),-1);self.assertEqual(list(out),[17]*40)
        self.assertEqual(lib.ggm_pack_instances(rows,65537,out,2),-1)
    def test_audio_spatial_rolloff_and_rotation(self):
        def signal(position,yaw=0):
            a=core.Audio();a.clip(0,[.5]*4800,48000);a.gain(1,1,1,1,True);a.listener(0,0,0,yaw)
            self.assertGreaterEqual(a.play(0,position=position,gain=1,near=8,far=100),0)
            data=samples(a.render(4800))[2400:];a.close();return rms(data[::2]),rms(data[1::2])
        near=signal((0,0,8));far=signal((0,0,16));self.assertAlmostEqual(far[0]/near[0],.2,places=4)
        right=signal((8,0,0));left=signal((8,0,0),math.pi)
        self.assertLess(right[0],1e-6);self.assertGreater(right[1],.1);self.assertLess(left[1],1e-6)
        self.assertEqual(signal((0,0,100)),(0,0))
        self.assertGreater(signal((0,0,0))[0],.1)
    def test_audio_cap_limiter_mute_and_stop(self):
        a=core.Audio();a.clip(0,[1.]*4096,48000);a.gain(1,1,1,1,True)
        for _ in range(64):self.assertGreaterEqual(a.play(0,gain=1,loop=True),0)
        self.assertEqual(a.play(0),-2);self.assertEqual(a.voices(),64)
        data=samples(a.render(4096));self.assertLessEqual(max(abs(x) for x in data),.990001)
        a.gain(enabled=False);a.render(16384);data=samples(a.render(2048));self.assertLess(max(abs(x) for x in data),1e-6)
        a.stop();self.assertEqual(a.voices(),0);a.close();a.close()
        with self.assertRaises(RuntimeError):a.render(8)
    def test_audio_rejects_live_replacement_and_nan(self):
        a=core.Audio();a.clip(0,[.2]*48,24000);a.play(0,loop=True)
        with self.assertRaises(ValueError):a.clip(0,[.1]*48,24000)
        with self.assertRaises(ValueError):a.gain(master=float('nan'))
        with self.assertRaises(ValueError):a.clip(1,[float('nan')],24000)
        self.assertEqual(a.voices(),1);a.close()
    def test_lua_snapshot_event_click_and_json_escape(self):
        v=lua();v.execute((PROJECT/'qml/game/lua/GgExplorer/Explorer.lua').read_text())
        v.publish({'x':12,'z':34,'speed':2,'biome':'FOREST'},True);v.event('SNAPSHOT')
        self.assertIn('12, 34',v.frames()[0]['text']);v.event('GAME_EVENT','HIT "fox"\n')
        self.assertIn('HIT "fox"',v.frames()[0]['text']);v.click('GgExplorer');self.assertEqual(v.frames()[0]['height'],30)
        self.assertLess(v.memory(),4194304);v.close()
    def test_lua_instruction_and_memory_bounds_recover(self):
        code="from backend.game_engine_native_presentation import Lua; v=Lua(524288); errors=[]\nfor s in ['while true do end',\"retained=string.rep('x',1000000)\"]:\n try:v.execute(s)\n except ValueError as e:errors.append(str(e))\nassert len(errors)==2;v.execute('retained=nil; ok=true');assert v.memory()<=524288;v.close();print('PASS')"
        p=subprocess.run([sys.executable,'-B','-c',code],cwd=PROJECT,capture_output=True,text=True,timeout=5)
        self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(p.stdout.strip(),'PASS')
    def test_lua_restricted_library_and_dialect(self):
        v=lua();v.execute("assert(io==nil and os==nil and package==nil and debug==nil and coroutine==nil and pcall==nil); local n=0; for k,v in {a=1,b=2} do n=n+v end; assert(n==3)")
        with self.assertRaises(ValueError):v.execute('return #{}')
        v.close()
    def test_lua_unicode_bounds_keep_valid_ui_text(self):
        v=lua();v.execute((PROJECT/'qml/game/lua/GgExplorer/Explorer.lua').read_text())
        v.publish({'biome':'🌲'*100},True);v.event('GAME_EVENT','🎉'*200)
        self.assertIn('🎉',v.frames()[0]['text']);v.close()
    def test_manifest_paths_and_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'a.lua').write_text('a=1');(root/'b.lua').write_text('b=1')
            p=root/'x.toc';p.write_text('\ufeff## Interface: 1\r\nb.lua\r\na.lua\n');m,paths=load_toc(p);self.assertEqual([x.name for x in paths],['b.lua','a.lua'])
            p.write_text('## Interface: 1\n../outside.lua\n')
            with self.assertRaises(ValueError):load_toc(p)
    @unittest.skipUnless((PROJECT/'qml/game/lua/host.lua').is_file(), 'Requires the optional game Lua host content')
    def test_qt_presentation_real_data_offline(self):
        p=Presentation(device=False)
        snapshot={'state':'RUNNING','player':{'x':4,'y':0,'z':8,'yaw':0,'time_s':1,'speed':2,'grounded':True,'biome':'FOREST','last_ability':'','last_ability_time':0},'combat_live':{'resource':90,'player':{'health':80}}}
        p.update(snapshot)
        if p.full_ui:self.assertIn('4.0 / 8.0',next(r['text'] for r in json.loads(p.framesJson) if r['kind']=='Text'))
        else:self.assertIn('4, 8',json.loads(p.framesJson)[0]['text'])
        self.assertTrue(p.click('GgExplorer'));self.assertEqual(next(r['height'] for r in json.loads(p.framesJson) if r.get('owner')=='GgExplorer' and r['kind']=='Frame') if p.full_ui else json.loads(p.framesJson)[0]['height'],30)
        self.assertTrue(p.setVolume('master',.25));self.assertFalse(p.setVolume('evil',.5));self.assertFalse(p.setVolume('music',float('nan')))
        data=samples(p.audio.render(4800));self.assertGreater(rms(data),0);self.assertFalse(p.errors,p.errors)
        p.close()
    def test_lua_model_retains_identity_during_updates(self):
        from backend.game_engine_presentation import FrameModel
        m=FrameModel();resets=[];changed=[]
        m.modelReset.connect(lambda:resets.append(True));m.dataChanged.connect(lambda *args:changed.append(True))
        m.sync([{'id':'p','text':'a'}]);m.sync([{'id':'p','text':'b'}]);m.sync([{'id':'p','text':'b'}])
        self.assertEqual(len(resets),1);self.assertEqual(len(changed),1);self.assertEqual(m.data(m.index(0),m.ROLE)['text'],'b')
    @unittest.skipUnless((PROJECT/'qml/game/audio/music.wav').is_file(), 'Requires the optional game audio content')
    def test_gameplay_drives_step_attack_damage_and_pause(self):
        p=Presentation(device=False)
        snapshot={'state':'RUNNING','player':{'x':0,'y':0,'z':0,'time_s':1,'grounded':True,'last_ability':'','last_ability_time':0},'combat_live':{'player':{'health':100}}}
        p.update(snapshot);self.assertEqual(p.audio.voices(),2)
        snapshot['player'].update(x=2,time_s=1.2,last_ability='FIRE',last_ability_time=1.2);snapshot['combat_live']['player']['health']=80
        p.last_update=0;p.update(snapshot);self.assertEqual(p.audio.voices(),5)
        snapshot['state']='PAUSED';p.last_update=0;p.update(snapshot)
        p.audio.render(16384);self.assertLess(rms(samples(p.audio.render(2048))),1e-6)
        self.assertFalse(p.errors,p.errors);p.close()
    @unittest.skipUnless((PROJECT/'tools/package_gg_game_release.py').is_file(), 'Requires the optional game release packager')
    def test_packaged_native_runtime_relocates(self):
        spec=importlib.util.spec_from_file_location('packager',PROJECT/'tools/package_gg_game_release.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        files=module.package_files();required=['backend/native/linux-x86_64/libgg_presentation.so','backend/native/linux-x86_64/libgg_engine_ui.so','backend/native/linux-x86_64/libgg_engine_formats.so','native/engine-formats/LICENSE-MIT','native/engine-formats/LICENSE-APACHE','qml/game/lua/host.lua','qml/game/framexml/GGExplorer/Explorer.xml','qml/game/audio/music.wav','qml/shaders/gg-ground-cover.frag','native/presentation/lua/lapi.c','backend/licenses/engine-lua-MIT.txt','backend/game_engine_adapter_models.py','backend/game_engine_adapter_gameplay.py','backend/game_engine_adapter_bank.py','backend/game_engine_adapter_merchant.py','backend/game_engine_actions.py','backend/game_engine_adapter_addon_sources.py','backend/game_engine_audio_short.py','qml/components/GgEngineModelPane.qml','qml/components/GgEngineModelMaterial.qml']
        required+=['backend/game_engine_adapter_mips.py','backend/game_engine_adapter_local_client.py']
        required+=['backend/game_engine_legacy.py']
        required+=['backend/game_engine_adapter_channels.py','backend/game_engine_local_channels.py',
                   'qml/components/LocalServiceComboBox.qml','qml/components/LocalServiceState.js']
        required+=['backend/game_engine_adapter_service_views.py','backend/game_engine_adapter_services.py','backend/game_engine_adapter_pane_anchor.py','qml/components/LocalGameServices.qml']
        for name in required:self.assertIn(PROJECT/name,files)
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)
            for path in files:
                relative=path.relative_to(PROJECT)
                if relative.as_posix()=='backend/game_engine_legacy.py':
                    target=dest/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
                    continue
                if str(relative).startswith(('native/presentation/','native/engine-ui/','native/engine-formats/','backend/native/','qml/game/lua/','qml/game/framexml/')) or str(relative) in ('backend/game_engine_native_presentation.py','backend/game_engine_adapter_ui.py','backend/game_engine_adapter_worker.py','backend/game_engine_adapter_text.py','backend/game_engine_adapter_assets.py','backend/game_engine_adapter_transport.py','backend/game_engine_adapter_formats.py','backend/game_engine_adapter_asset_worker.py','backend/game_engine_adapter_models.py','backend/game_engine_adapter_mips.py','backend/game_engine_adapter_gameplay.py','backend/game_engine_adapter_bank.py','backend/game_engine_adapter_merchant.py','backend/game_engine_adapter_quests.py','backend/game_engine_adapter_local_views.py','backend/game_engine_adapter_service_views.py','backend/game_engine_adapter_pane_anchor.py','backend/game_engine_actions.py','backend/game_engine_adapter_addon_sources.py','backend/game_engine_adapter_addon_state.py','backend/game_engine_audio_short.py','backend/game_engine_audio_stream.py'):
                    target=dest/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
            fixture_path=dest/'qml/relocated.tga';fixture_path.write_bytes(bytes([0,0,2])+bytes(9)+struct.pack('<HHBB',1,1,24,0x20)+bytes([3,2,1]))
            from tools.world.engine_format_fixtures import animated_m2,blp
            (dest/'qml/relocated.m2').write_bytes(animated_m2());(dest/'qml/gold.blp').write_bytes(blp())
            import wave
            with wave.open(str(dest/'qml/short.wav'),'wb') as audio:
                audio.setnchannels(2);audio.setsampwidth(2);audio.setframerate(22050);audio.writeframes(struct.pack('<hh',16000,0)*1024)
            code='''from pathlib import Path
from PySide6.QtGui import QGuiApplication
from backend.game_engine_native_presentation import Lua,Audio,status
from backend.game_engine_adapter_ui import GgEngineUI
from backend.game_engine_adapter_formats import NativeFormats,AssetCache
from backend.game_engine_audio_short import ShortSounds
from backend.game_engine_adapter_gameplay import GameplayViews
import time
app=QGuiApplication([])
assert status()['backend']=='CPP'
v=Lua();v.execute(Path('qml/game/lua/host.lua').read_text());assert v.frames()==[];v.close()
u=GgEngineUI();u.load_addons(Path('qml/game/framexml'));assert any(r.get('owner')=='GgExplorer' for r in u.frames())
views=GameplayViews();data=views.update({'bank':{'accessible':True,'capacity':48,'revision':1,'items':[{'slot_index':47,'instance_id':'portable-bank','definition_id':'portable-stone','location':'BANK','quantity':4,'name':'Stone'}]}})
u.publish({},True,100,100,**data);assert u.evaluate('return GetContainerNumSlots(-1),GetContainerItemInfo(-1,48)')[0:3]==[48,None,4];u.close()
a=NativeFormats();m,b=a.decode(Path('qml/relocated.tga').resolve());assert m['format']=='TGA' and b==bytes([1,2,3,255]);a.close()
cache=AssetCache();model=cache.live_model(Path('qml/relocated.m2'),{'id':'portable','camera':0,'play':{'anim_id':7,'cursor_ms':500}})
assert model.batches[0].tex.size().width()==2 and model.camera
cache.close();assert cache.live_bytes==0
audio=Audio();sounds=ShortSounds(audio);sounds.play(Path('qml/short.wav'),gain=.5)
deadline=time.monotonic()+6
while sounds.pending and time.monotonic()<deadline:sounds.pump();time.sleep(.002)
assert not sounds.pending and not sounds.errors and audio.voices()==1
sounds.close();audio.close()
print('PASS')'''
            r=subprocess.run([sys.executable,'-B','-c',code],cwd=dest,env={**os.environ,'PYTHONPATH':str(dest)},capture_output=True,text=True,timeout=15)
            self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(r.stdout.strip(),'PASS')

if __name__=='__main__':unittest.main()
