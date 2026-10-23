"""Original staged RestartGx affects the actual Qt client window and no assets."""
import copy
import json
import unittest
from unittest.mock import patch
import test_game_engine_adapter_controls as controls
from PySide6.QtQuick import QQuickWindow
from PySide6.QtCore import QCoreApplication,QEvent


class Graphics(unittest.TestCase):
    publish=controls.Controls.publish
    call=controls.Controls.call

    def setUp(self):
        controls.Controls.setUp(self)
        self.window=QQuickWindow();self.window.resize(1360,768);self.window.show()
        self.window.setPersistentGraphics(False);self.window.setPersistentSceneGraph(False)
        self.addCleanup(self.close_window)
        self.presentation.attachCanvas(self.window.contentItem(),True)
        controls.APP.processEvents()

    def close_window(self):
        self.presentation.close()
        self.window.close();self.window.releaseResources();self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        controls.APP.processEvents()

    def test_original_staged_resolution_applies_to_real_window_once_and_keeps_same_items(self):
        before=copy.deepcopy((self.runtime._item_instances,self.runtime._inventory,self.runtime._economy_state))
        self.call("SetCVar('gxResolution','1024x768')")
        self.assertEqual(self.ui.evaluate("return GetCVar('gxResolution')"),['1360x768'])
        self.assertEqual((self.window.width(),self.window.height()),(1360,768))
        self.call('RestartGx()');self.assertEqual(self.presentation.graphics.generation,0)
        for _ in range(3):controls.APP.processEvents()
        self.assertEqual((self.window.width(),self.window.height()),(1024,768))
        self.assertEqual(self.presentation.graphics.generation,1)
        self.assertEqual(self.ui.evaluate("return GetCVar('gxResolution'),GetCurrentResolution()"),['1024x768',1])
        self.assertEqual(before,(self.runtime._item_instances,self.runtime._inventory,self.runtime._economy_state))
        self.assertEqual(self.ui.request('requests')['client_tools']['graphics_restarts'],0)
        saved=json.loads(self.presentation.graphics.path().read_text())
        self.assertEqual(saved['values'],{'gxWindow':'1','gxResolution':'1024x768'})

    def test_invalid_resolution_preserves_applied_values_and_window_with_a_retryable_stage(self):
        before=copy.deepcopy(self.runtime._item_instances)
        self.call("SetCVar('gxResolution','9999x9999');RestartGx()")
        controls.APP.processEvents()
        self.assertEqual(self.presentation.graphics.error,'GRAPHICS_RESOLUTION_INVALID')
        self.assertEqual(self.presentation.graphics.generation,0)
        self.assertEqual((self.window.width(),self.window.height()),(1360,768))
        self.assertEqual(self.ui.evaluate("return GetCVar('gxResolution')"),['1360x768'])
        self.call("SetCVar('gxResolution','1024x768');RestartGx()")
        for _ in range(3):controls.APP.processEvents()
        self.assertEqual(self.presentation.graphics.generation,1)
        self.assertEqual(before,self.runtime._item_instances)

    def test_original_restart_refuses_missing_window_without_committing_or_replaying(self):
        self.window.close();controls.APP.processEvents()
        self.call("SetCVar('gxResolution','1024x768');RestartGx()")
        self.assertEqual(self.presentation.graphics.error,'GRAPHICS_WINDOW_UNAVAILABLE')
        self.assertEqual(self.presentation.graphics.generation,0)
        self.assertEqual(self.ui.evaluate("return GetCVar('gxResolution')"),['1360x768'])
        self.presentation._ui_requests(self.ui.request('requests'))
        self.assertEqual(self.presentation.graphics.generation,0)

    def test_failed_settings_save_does_not_resize_the_window_or_change_applied_values(self):
        self.call("SetCVar('gxResolution','1024x768')")
        with patch.object(self.presentation.graphics,'save',side_effect=OSError('disk full')):
            self.call('RestartGx()')
            for _ in range(3):controls.APP.processEvents()
        self.assertEqual(self.presentation.graphics.error,'GRAPHICS_SAVE_FAILED')
        self.assertEqual((self.window.width(),self.window.height()),(1360,768))
        self.assertEqual(self.ui.evaluate("return GetCVar('gxResolution')"),['1360x768'])
        self.assertEqual(self.presentation.graphics.generation,0)

    def test_ui_replacement_discards_an_old_pending_restart_and_restores_the_last_applied_account_settings(self):
        self.call("SetCVar('gxResolution','1024x768');RestartGx()")
        for _ in range(3):controls.APP.processEvents()
        self.assertEqual(self.presentation.graphics.generation,1)
        self.window.resize(1360,768)
        self.call("SetCVar('gxResolution','800x600');RestartGx()")
        old=self.presentation.lua
        self.assertTrue(self.presentation._reload_ui())
        self.ui=self.presentation.lua;self.assertIsNot(self.ui,old)
        for _ in range(8):controls.APP.processEvents()
        self.assertEqual((self.window.width(),self.window.height()),(1024,768))
        self.assertEqual(self.presentation.graphics.error,'')
        self.assertEqual(self.ui.evaluate("return GetCVar('gxResolution')"),['1024x768'])
        saved=json.loads(self.presentation.graphics.path().read_text())
        self.assertEqual(saved['values']['gxResolution'],'1024x768')


if __name__=='__main__':unittest.main()
