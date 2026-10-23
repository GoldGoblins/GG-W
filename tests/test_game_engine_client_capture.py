"""Screenshot requests finish asynchronously against the requesting VM and folder."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from PySide6.QtCore import QCoreApplication, QObject, Signal
from PySide6.QtGui import QImage
from backend.game_engine_adapter_client_tools import ClientTools


class Grab(QObject):
    ready=Signal()
    def __init__(self):
        super().__init__()
        self.pixels=QImage(8,6,QImage.Format.Format_ARGB32)
        self.pixels.fill(0xff916f32)
    def image(self):return self.pixels


class Capture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QCoreApplication.instance() or QCoreApplication([])
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.events=[];self.grabs=[]
        self.vm=SimpleNamespace(saving_enabled=True,character_saved_root=self.root,saved_root=None,closed=False,event=lambda *args:self.events.append(args))
        def grab():
            result=Grab();self.grabs.append(result);return result
        self.window=SimpleNamespace(isVisible=lambda:True,contentItem=lambda:SimpleNamespace(grabToImage=grab),
            grabWindow=lambda:self.fail('Synchronous render-thread capture must never be used'))
        self.presentation=SimpleNamespace(lua=self.vm,_canvas=SimpleNamespace(window=lambda:self.window))
        self.tools=ClientTools(self.presentation);self.addCleanup(self.tools.close)
    def request(self,count=1):
        self.tools.requests({'screenshots':count});self.app.processEvents()
    def files(self):return list((self.root/'Screenshots').glob('GG-*.png'))

    def test_ready_saves_real_pixels_once_and_success_follows_save(self):
        self.request(2)
        self.assertTrue(self.tools.capture_pending);self.assertEqual(self.events,[]);self.assertEqual(self.files(),[])
        self.grabs[0].ready.emit()
        self.assertFalse(self.tools.capture_pending);self.assertEqual(self.events,[('SCREENSHOT_SUCCEEDED',)])
        self.assertEqual(len(self.files()),2)
        self.assertEqual(QImage(str(self.files()[0])).pixel(0,0),0xff916f32)
        self.grabs[0].ready.emit();self.assertEqual(len(self.files()),2);self.assertEqual(len(self.events),1)

    def test_vm_switch_and_character_folder_switch_discard_old_capture(self):
        self.request();self.presentation.lua=SimpleNamespace(**vars(self.vm));self.grabs[0].ready.emit()
        self.assertEqual(self.events,[]);self.assertEqual(self.files(),[]);self.assertFalse(self.tools.capture_pending)
        self.presentation.lua=self.vm;self.request();self.vm.character_saved_root=self.root/'other'
        self.grabs[1].ready.emit()
        self.assertEqual(self.events,[]);self.assertFalse((self.root/'other').exists());self.assertFalse(self.tools.capture_pending)

    def test_timeout_late_ready_cannot_complete_or_clear_a_new_request(self):
        self.request();old=self.tools._capture_job;old['timer'].timeout.emit()
        self.assertEqual(self.events,[('SCREENSHOT_FAILED',)]);self.assertFalse(self.tools.capture_pending)
        self.request();self.grabs[0].ready.emit();self.tools._capture_ready(old)
        self.assertTrue(self.tools.capture_pending);self.assertEqual(self.files(),[])
        self.grabs[1].ready.emit();self.assertEqual(self.events[-1],('SCREENSHOT_SUCCEEDED',));self.assertEqual(len(self.files()),1)

    def test_capacity_rechecked_before_save_and_null_image_fails(self):
        self.request();folder=self.root/'Screenshots';folder.mkdir()
        for index in range(32):(folder/f'GG-{index}.png').write_bytes(b'preexisting')
        self.grabs[0].ready.emit();self.assertEqual(self.events,[('SCREENSHOT_FAILED',)]);self.assertEqual(len(self.files()),32)
        self.request();self.assertEqual(len(self.grabs),1);self.assertEqual(self.events[-1],('SCREENSHOT_FAILED',))

    def test_close_invalidates_queued_and_inflight_callbacks(self):
        self.tools.requests({'screenshots':1});self.tools.close();self.app.processEvents()
        self.assertEqual(self.grabs,[]);self.assertEqual(self.events,[])
        self.request();self.tools.close();self.grabs[0].ready.emit()
        self.assertEqual(self.files(),[]);self.assertEqual(self.events,[]);self.assertFalse(self.tools.capture_pending)

    def test_null_image_and_invalid_request_never_report_success(self):
        self.request();self.grabs[0].pixels=QImage();self.grabs[0].ready.emit()
        self.assertEqual(self.events,[('SCREENSHOT_FAILED',)]);self.assertEqual(self.files(),[])
        self.request(5);self.assertEqual(len(self.grabs),1);self.assertFalse(self.tools.capture_pending)


if __name__=='__main__':unittest.main()
