"""Capture interlock tests use metadata and synthetic images, never a screen."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch
from types import SimpleNamespace

from backend import sensitive_ui_guard as guard
from backend import live_vision,windows_vision,desktop_operator


class MemoryChannel:
    def __init__(self):self.blocked=False;self.generation=0;self.lock=threading.RLock()
    def call(self,blocked=None,*,token=False):
        with self.lock:
            if blocked is True:self.blocked=True;self.generation+=1
            elif blocked is False:self.blocked=False
            return (self.blocked,self.generation) if token else self.blocked


class TermuxMetadataLocationTests(unittest.TestCase):
    def test_fixed_interpreter_prefix_ignores_profile_and_wallet_environment(self):
        from pathlib import PurePosixPath
        expected=PurePosixPath('/data/user/0/com.termux/files/usr/tmp/gg-sensitive-ui-10123')
        with patch.dict(os.environ,{'HOME':'/untrusted','TMPDIR':'/untrusted','GG_DESKTOP_STATE_ROOT':'/another-wallet'}):
            self.assertEqual(guard._termux_candidate('/data/user/0/com.termux/files/usr/bin/python3.13',10123),expected)
        self.assertIsNone(guard._termux_candidate('/tmp/com.termux/files/usr/bin/python3',10123))
        self.assertIsNone(guard._termux_candidate('/data/user/0/com.termux/files/home/bin/python3',10123))
        self.assertIsNone(guard._termux_candidate('/data/user/0/other.app/files/usr/bin/python3',10123))


class SensitiveUiGuardTests(unittest.TestCase):
    def setUp(self):
        self.channel=MemoryChannel()
        self.owners=patch.object(guard,'_owners',set());self.owners.start();self.addCleanup(self.owners.stop)
        self.adapter=patch.object(guard,'_channel',self.channel);self.adapter.start();self.addCleanup(self.adapter.stop)
        self.stopping=patch.object(live_vision,'stop_if_running');self.stop=self.stopping.start();self.addCleanup(self.stopping.stop)
    def test_nested_owners_are_bounded_idempotent_and_do_not_resume_capture(self):
        guard.enter('one');guard.enter('one');guard.enter('two');self.assertTrue(guard.active())
        self.assertEqual(self.stop.call_count,2)
        guard.leave('one');self.assertTrue(guard.active());guard.leave('two');self.assertFalse(guard.active())
        self.assertEqual(self.stop.call_count,2)
        for index in range(guard.MAX_OWNERS):guard.enter('bounded-'+str(index))
        with self.assertRaises(RuntimeError):guard.enter('overflow')
        with self.assertRaises(ValueError):guard.enter('')
    def test_capture_spanning_enter_and_leave_is_rejected_even_after_view_is_closed(self):
        token=guard.capture_token();guard.enter('private');guard.leave('private')
        self.assertFalse(guard.active())
        with self.assertRaisesRegex(RuntimeError,'SENSITIVE_UI'):guard.require_capture_allowed(token)
        guard.require_capture_allowed(guard.capture_token())
    def test_blocked_pixels_progress_framebuffers_and_exports_are_never_produced(self):
        ring=live_vision.FrameRing();ring.append(b'public-marker',1,1,None)
        guard.enter('private');grab=Mock();progress=Mock()
        with self.assertRaisesRegex(RuntimeError,'SENSITIVE_UI'):windows_vision.capture({'op':'frame'},grab=grab,screen_size=(10,10),on_frame=progress)
        grab.assert_not_called();progress.assert_not_called()
        with self.assertRaisesRegex(RuntimeError,'SENSITIVE_UI'):ring.observation()
        self.assertFalse(ring.frames);self.assertEqual(ring.bytes,0)
        with self.assertRaisesRegex(RuntimeError,'SENSITIVE_UI'):live_vision.image_parts({})
        with self.assertRaisesRegex(RuntimeError,'SENSITIVE_UI'):live_vision.export_parts([])
    def test_in_flight_grab_loses_epoch_without_append_or_emission(self):
        from PIL import Image
        def grab(**_):
            guard.enter('transient');guard.leave('transient')
            return Image.new('RGB',(10,10),'#123456')
        with patch.object(live_vision.FrameRing,'append') as append:
            with self.assertRaisesRegex(RuntimeError,'SENSITIVE_UI'):windows_vision.capture({'op':'frame'},grab=grab,screen_size=(10,10))
            append.assert_not_called()
    def test_accessibility_results_are_redacted_and_client_refuses_before_command_write(self):
        guard.enter('private')
        with patch.object(desktop_operator,'_authority_fields',return_value={}):
            result=desktop_operator.make_result({'action':'SNAPSHOT'},ok=True,reason_code='SNAPSHOT',text='public-sensitive-test-marker',names=['public-test-name'],image='public-test-image.png')
        self.assertFalse(result['ok']);self.assertEqual(result['reason_code'],'SENSITIVE_UI_ACTIVE')
        self.assertEqual((result['text'],result['names'],result['image']),('',[],''))
        with patch.object(desktop_operator,'validate_command',return_value={'action':'FIND'}),patch.object(desktop_operator,'ensure_root') as write:
            with self.assertRaisesRegex(desktop_operator.DesktopOperatorError,'SENSITIVE_UI_ACTIVE'):desktop_operator.submit({})
            write.assert_not_called()
    def test_worker_thread_can_enter_and_leave_without_qt(self):
        errors=[]
        def run():
            try:guard.enter('worker');self.assertTrue(guard.active());guard.leave('worker')
            except BaseException as error:errors.append(type(error).__name__)
        worker=threading.Thread(target=run);worker.start();worker.join(2)
        self.assertFalse(worker.is_alive());self.assertFalse(errors);self.assertFalse(guard.active())
    def test_portal_and_kwin_refuse_before_pulling_or_allocating_new_frames(self):
        from backend.live_vision_capture import Capture
        from backend.live_vision_kwin import NativeKWin
        guard.enter('private')
        capture=Capture.__new__(Capture);capture.ring=Mock();capture.detail_lock=threading.RLock();capture.detail='public-test-frame'
        capture.Gst=SimpleNamespace(FlowReturn=SimpleNamespace(FLUSHING='flushing'));capture.GLib=SimpleNamespace(idle_add=Mock());capture.stop=Mock()
        sink=Mock()
        self.assertEqual(capture._sample(sink),'flushing');self.assertIsNone(capture.detail)
        self.assertEqual(capture._detail_sample(sink),'flushing');sink.emit.assert_not_called()
        self.assertEqual(capture.GLib.idle_add.call_count,2)
        native=NativeKWin.__new__(NativeKWin)
        with self.assertRaisesRegex(RuntimeError,'SENSITIVE_UI'):native._raw_frame()


@unittest.skipUnless(os.name=='nt','Windows shared RAM mapping')
class WindowsSharedInterlockTests(unittest.TestCase):
    def test_other_gg_process_observes_block_and_metadata_contains_no_owner_input(self):
        from backend import application_paths
        with tempfile.TemporaryDirectory(prefix='gg-sensitive-guard-') as temporary,patch.object(application_paths,'STATE_ROOT',Path(temporary)),patch.object(guard,'_channel',None),patch.object(guard,'_owners',set()),patch.object(live_vision,'stop_if_running'):
            environment=os.environ.copy();environment['GG_DESKTOP_STATE_ROOT']=str(Path(temporary)/'intentionally-different-cli-profile')
            guard.enter('public-sensitive-test-owner')
            channel=guard._channel
            try:
                self.assertNotIn(b'public-sensitive-test-owner',channel.memory[:4096])
                code="from backend.sensitive_ui_guard import active;import json;print(json.dumps({'blocked':active()}))"
                before=subprocess.run([sys.executable,'-X','utf8','-B','-c',code],cwd=Path(__file__).resolve().parents[1],env=environment,capture_output=True,text=True,timeout=10)
                self.assertEqual(before.returncode,0,before.stderr);self.assertTrue(json.loads(before.stdout)['blocked'])
                guard.leave('public-sensitive-test-owner')
                after=subprocess.run([sys.executable,'-X','utf8','-B','-c',code],cwd=Path(__file__).resolve().parents[1],env=environment,capture_output=True,text=True,timeout=10)
                self.assertEqual(after.returncode,0,after.stderr);self.assertFalse(json.loads(after.stdout)['blocked'])
            finally:
                import atexit
                atexit.unregister(channel.close);channel.close()


if __name__=='__main__':unittest.main()
