"""Native failure recovery, image admission and transactional UV publication."""
from __future__ import annotations
import copy
import array
import ctypes
import json
import io
import os
from pathlib import Path
import struct
import sys
import tempfile
import shutil
import time
from types import SimpleNamespace
import unittest
import wave
from unittest.mock import patch
import zlib

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))


def panic_worker():
    # Inject the native ABI's exact panic response at the real worker seam.
    # No production flag, native export or user-selected executable is added.
    from backend.game_engine_adapter_asset_worker import serve
    class ABI:
        def gga_request(self,_handle,packet,_length):
            if json.loads(packet).get('op')=='archive_audio_open':
                answer={'ok':True,'result':{'id':1,'size':44}}
            else:answer={'ok':False,'error':'native asset decoder panic'}
            self.response=ctypes.create_string_buffer(json.dumps(answer).encode());return 0
        def gga_response(self,_handle,length):
            length._obj.value=len(self.response.value)
            return ctypes.addressof(self.response)
        def gga_blob(self,_handle,length):length._obj.value=0;return None
    reusable=serve(ABI(),1,sys.stdin.buffer,sys.stdout.buffer)
    return 9 if reusable else 0


if __name__=='__main__' and '--panic-worker' in sys.argv:
    raise SystemExit(panic_worker())

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QByteArray,QBuffer,QIODevice,QCoreApplication
from PySide6.QtGui import QGuiApplication,QImage,QImageReader
from backend import game_engine_asset_editor as editor,game_engine_assets as assets,image_admission
from backend.game_engine_adapter_formats import AssetCache,NativeFormats
from backend.game_engine_adapter_transport import BoundedWorker,NativeWorkerFatalError
from backend.game_workflow_rig import GLB
from tools.world import engine_format_fixtures as fixture


def triangle():
    model=GLB();positions=model.accessor([[0,0,0],[1,0,0],[0,1,0]],'VEC3',bounds=True)
    normals=model.accessor([[0,0,1]]*3,'VEC3');indices=model.accessor([[0],[1],[2]],'SCALAR',component=5123)
    model.doc.update(nodes=[{'mesh':0}],scene=0,scenes=[{'nodes':[0]}],
        meshes=[{'primitives':[{'attributes':{'POSITION':positions,'NORMAL':normals},'indices':indices,'material':0}]}],
        materials=[{'name':'Gold','pbrMetallicRoughness':{'baseColorFactor':[.3,.7,.9,1],
                    'metallicFactor':0,'roughnessFactor':1}}])
    return bytes(model.finish())


class AssetFailureRecovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='.gg-failure-recovery-',dir=PROJECT/'qml')
        self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.library=self.root/'library';self.library.mkdir()
        self.generated=self.root/'generated';self.generated.mkdir()
        self.enterContext(patch.object(assets,'ASSET_ROOT',self.library))
        self.enterContext(patch.object(editor,'GENERATED_ROOT',self.generated))
        self.enterContext(patch.object(editor,'DOCUMENT_PATH',self.root/'scene.json'))

    def scene(self):
        source=self.library/'original.glb';source.write_bytes(triangle())
        runtime=SimpleNamespace(_running=False,_render_snapshot_signature='original')
        scene=editor.AssetEditor(runtime,None)
        scene.selected={'key':'asset:'+source.as_uri(),'source':source.as_uri(),'identity':''}
        return scene,source

    def test_fatal_native_reply_retires_worker_then_restores_known_archive(self):
        worker=BoundedWorker();worker._start_worker([sys.executable,'-B',str(Path(__file__)), '--panic-worker'],os.environ.copy())
        self.addCleanup(worker.close)
        directory=self.root/'Data';directory.mkdir()
        (directory/'model.MPQ').write_bytes(fixture.mpq('Interface/Test.txt',b'clean next request'))
        cache=AssetCache();self.addCleanup(cache.close)
        cache.reader=worker;cache.archive_source=directory;cache._mounted_reader=worker
        old_handle=worker.request('archive_audio_open',timeout=10)['id']
        with self.assertRaisesRegex(NativeWorkerFatalError,'decoder panic'):
            worker.request('decode',path='synthetic',timeout=10)
        self.assertTrue(worker.closed);self.assertIsNotNone(worker.process.poll())
        with self.assertRaisesRegex(RuntimeError,'stopped'):
            worker.request('archive_audio_read',id=old_handle,position=0,limit=1)
        reader=cache._reader()
        self.assertIsNot(reader,worker)
        _meta,blob=NativeFormats._unpack(reader.request('chain_read',entry='Interface/Test.txt',timeout=3))
        self.assertEqual(blob,b'clean next request')
        with self.assertRaisesRegex(ValueError,'unavailable'):
            reader.request('archive_audio_read',id=old_handle,position=0,limit=1)
        self.assertEqual(reader.request('ping'),{'abi':1})

    def test_normal_invalid_asset_does_not_poison_reader(self):
        reader=NativeFormats(self.root);self.addCleanup(reader.close)
        bad=self.root/'broken.blp';bad.write_bytes(b'broken')
        with self.assertRaises(ValueError):reader.decode(bad)
        self.assertFalse(reader.closed)
        good=self.root/'good.blp';good.write_bytes(fixture.blp())
        metadata,blob=reader.decode(good)
        self.assertEqual(metadata['blob_kind'],'rgba');self.assertTrue(blob)

    def png(self):
        image=QImage(2,2,QImage.Format.Format_RGBA8888);image.fill(0xffaabbcc)
        packet=QByteArray();buffer=QBuffer(packet);buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        self.assertTrue(image.save(buffer,'PNG'));return bytes(packet)

    def test_image_pixel_budget_checked_before_decode_and_next_image_succeeds(self):
        data=bytearray(self.png());struct.pack_into('>I',data,16,4097)
        struct.pack_into('>I',data,29,zlib.crc32(data[12:29]))
        class PreflightReader(QImageReader):
            def read(self):raise AssertionError('oversized image reached pixel decode')
        limits={'max_encoded_bytes':1024*1024,'max_dimension':4096,'max_decoded_bytes':64*1024*1024}
        with patch.object(image_admission,'QImageReader',PreflightReader):
            with self.assertRaisesRegex(ValueError,'PIXEL_BUDGET'):image_admission.decode_image(bytes(data),**limits)
        self.assertLessEqual(QImageReader.allocationLimit(),64)
        with self.assertRaises(ValueError):image_admission.decode_image(self.png()[:20],**limits)
        image=image_admission.decode_image(self.png(),**limits)
        self.assertEqual((image.width(),image.height()),(2,2))

    def test_uv_rejects_invalid_staging_without_publishing_or_changing_scene(self):
        scene,source=self.scene();old=copy.deepcopy(scene.document);selection=copy.deepcopy(scene.selected)
        pending=self.generated/'atlas.pending.glb';pending.write_bytes(b'truncated')
        target=self.generated/'atlas.glb'
        with self.assertRaises(ValueError):
            scene._install_uv_artifact(pending,target,scene.detail(source.as_uri()),selection,source.as_uri(),0)
        self.assertFalse(target.exists());self.assertEqual(scene.document,old);self.assertEqual(scene.selected,selection)
        editor._discard_uv_file(pending)
        pending.write_bytes(triangle())
        scene._install_uv_artifact(pending,target,scene.detail(source.as_uri()),selection,source.as_uri(),0)
        self.assertTrue(target.is_file());self.assertFalse(pending.exists())
        self.assertEqual(scene.document['edits'][selection['key']]['model_source'],target.as_uri())
        self.assertEqual(source.read_bytes(),triangle())

    def test_uv_preparation_failure_preserves_existing_scene_and_cached_target(self):
        scene,source=self.scene();pending=self.generated/'atlas.pending.glb';pending.write_bytes(triangle())
        target=self.generated/'atlas.glb';old=copy.deepcopy(scene.document)
        with patch.object(scene,'detail',side_effect=RuntimeError('injected inspection failure')):
            with self.assertRaisesRegex(RuntimeError,'injected'):
                scene._install_uv_artifact(pending,target,{},scene.selected,source.as_uri(),0)
        self.assertEqual(scene.document,old);self.assertFalse(target.exists())
        with patch.object(editor,'atomic_replace',side_effect=PermissionError('reader lock')):
            with self.assertRaises(PermissionError):
                scene._install_uv_artifact(pending,target,scene.detail(source.as_uri()),scene.selected,source.as_uri(),0)
        self.assertEqual(scene.document,old);self.assertFalse(target.exists());self.assertTrue(pending.exists())

    def test_uv_rejects_changed_scene_and_pending_cleanup_handles_long_paths(self):
        scene,source=self.scene();pending=self.generated/'staged.pending.glb';pending.write_bytes(triangle())
        scene.revision=1
        with self.assertRaisesRegex(ValueError,'Scenen ändrades'):
            scene._install_uv_artifact(pending,self.generated/'atlas.glb',{},scene.selected,source.as_uri(),0)
        long_root=self.root
        while len(str(long_root))<280:long_root=long_root/('owned-'+'x'*30)
        extended=Path('\\\\?\\'+str(long_root)) if os.name=='nt' else long_root
        extended.mkdir(parents=True)
        self.addCleanup(shutil.rmtree,extended)
        with patch.object(editor,'GENERATED_ROOT',long_root):
            long_pending=long_root/'atlas.pending.glb';(extended/long_pending.name).write_bytes(b'partial')
            editor._discard_uv_file(long_pending);self.assertFalse((extended/long_pending.name).exists())
            with self.assertRaisesRegex(ValueError,'OUTSIDE_ROOT'):editor._discard_uv_file(self.root/'foreign')

    @unittest.skipUnless(os.name=='nt','Installed Windows Blender integration')
    def test_real_windows_uv_background_job_preserves_source_and_commits(self):
        scene,source=self.scene();original=source.read_bytes()
        old=copy.deepcopy(scene.document)
        injected=self.root/'failed-exporter';script=injected/'tools/blender/prepare_game_asset_uv.py'
        script.parent.mkdir(parents=True)
        script.write_text('import sys\nfrom pathlib import Path\nPath(sys.argv[-1]).write_bytes(b"truncated")\n',encoding='utf-8')
        with patch.object(assets,'PROJECT_ROOT',injected):
            scene.prepare_uv()
            self.wait_uv(scene)
        self.assertIn('error',scene.uv_progress)
        self.assertEqual(scene.document,old)
        self.assertFalse(list(self.generated.glob('*.glb')))
        # The real exporter can retry immediately after the invalid child.
        scene.prepare_uv()
        self.wait_uv(scene)
        self.assertNotIn('error',scene.uv_progress,scene.uv_progress)
        self.assertEqual(scene.uv_progress['percent'],100)
        target=editor.local_path(scene.document['edits'][scene.selected['key']]['model_binding']['source'])
        self.assertTrue(target.is_file(),scene.document)
        self.assertEqual(source.read_bytes(),original)
        self.assertFalse(list(self.generated.glob('*.pending.glb')))
        self.assertEqual(scene.detail(target.as_uri())['triangles'],1)

    def wait_uv(self,scene):
        deadline=time.monotonic()+100
        while scene.uv_job is not None and time.monotonic()<deadline:
            QCoreApplication.processEvents();time.sleep(.02)
        if scene.uv_job is not None:
            scene.uv_job.kill();scene.uv_job.waitForFinished(5000)
        self.assertIsNone(scene.uv_job,scene.uv_progress)

    def test_uv_preserves_rigs_and_paint_and_full_generated_budget(self):
        scene,source=self.scene()
        with patch.object(scene,'detail',return_value={'joints':1}):
            with self.assertRaisesRegex(ValueError,'Riggade'):scene.prepare_uv()
        scene.document['edits'][scene.selected['key']]={'source':source.as_uri(),
            'materials':{'0':{'strokes':[{'points':[[0,0]]}]}}}
        before=copy.deepcopy(scene.document)
        with self.assertRaisesRegex(ValueError,'Förbered UV före målning'):scene.prepare_uv()
        self.assertEqual(scene.document,before)
        pending=self.generated/'atlas.pending.glb';pending.write_bytes(triangle())
        with patch.object(editor,'MAX_GENERATED_BYTES',len(triangle())-1):
            with self.assertRaisesRegex(ValueError,'lagringsgränsen'):
                scene._install_uv_artifact(pending,self.generated/'atlas.glb',scene.detail(source.as_uri()),
                                           scene.selected,source.as_uri(),scene.revision)
        self.assertFalse((self.generated/'atlas.glb').exists());self.assertEqual(scene.document,before)

    @unittest.skipUnless(os.name=='nt','Windows bounded audio decoder')
    def test_windows_audio_stop_releases_real_ffmpeg_child_and_input(self):
        import psutil
        from backend.game_engine_native_presentation import Audio
        from backend.game_engine_audio_stream import AudioFileStream
        raw=io.BytesIO()
        with wave.open(raw,'wb') as writer:
            writer.setnchannels(2);writer.setsampwidth(2);writer.setframerate(48000)
            writer.writeframes(array.array('h',[8192,-8192]*4800).tobytes())
        source=self.root/'owned audio å.wav';source.write_bytes(raw.getvalue())
        audio=Audio();self.addCleanup(audio.close)
        stream=AudioFileStream(audio,0,source,loop=True);self.addCleanup(stream.close)
        children=[];deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            stream.pump();children=psutil.Process(stream.process.pid).children(recursive=True);time.sleep(.02)
            if any(child.name().lower()=='ffmpeg.exe' for child in children):break
        self.assertTrue(any(child.name().lower()=='ffmpeg.exe' for child in children))
        self.assertLessEqual(len(stream.pending),65536)
        stream.close()
        self.assertIsNotNone(stream.process.poll())
        self.assertFalse(psutil.wait_procs(children,timeout=1)[1])
        source.unlink();self.assertFalse(source.exists())


if __name__=='__main__':unittest.main()
