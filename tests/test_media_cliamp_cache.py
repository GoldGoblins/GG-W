"""CLIAMP GUI status stays cached across acknowledged playback controls."""
from __future__ import annotations
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from backend import media_host as host

class MediaCliampCacheTests(unittest.TestCase):
    def setUp(self):
        self.patches=ExitStack()
        self.addCleanup(self.patches.close)
        state=dict(ok=True,state='playing',position=61.5,duration=240.0,
                   eq_preset='Rock',eq_bands=[1.0]*10,track={'title':'Song','path':'song.mp3'})
        for key,value in dict(_backend='cliamp',_last_live_state=state,_last_live_at=0.0,
                              _live_json='',_live_payload={},_spectrum=[],_proc=None,
                              _cliamp_proc=None,_item={'id':'song','title':'Song'},_want_source='',
                              _library_page_state={},_library_page_items=[]).items():
            self.patches.enter_context(patch.object(host,key,value))
        self.patches.enter_context(patch.object(host,'start_live_pump'))
        self.patches.enter_context(patch.object(host,'load_prefs',return_value={
            'mode':'MUSIC','volume':70,'last_id':'song'}))
        self.patches.enter_context(patch.object(host,'_catalog_rows',return_value=[]))
        self.patches.enter_context(patch.object(host,'_cliamp_sock',return_value=Mock(exists=lambda:True)))
        # AF_UNIX is intentionally optional on Windows installations.
        self.patches.enter_context(patch.object(host.socket,'AF_UNIX',1,create=True))

    def command(self,payload,reply):
        sock=Mock()
        sock.recv.return_value=(json.dumps(reply)+'\n').encode()
        with patch.object(host.socket,'socket',return_value=sock):
            return host._cliamp_call(payload)

    def snapshot(self):
        with patch.object(host,'_cliamp_live',side_effect=AssertionError('GUI socket read')):
            return host.status_payload(live=True)

    def test_volume_and_eq_ack_preserve_playback_clock_and_eq_snapshot(self):
        self.command({'cmd':'volume','value':-10},{'ok':True})
        state=self.snapshot()
        self.assertTrue(state['playing'])
        self.assertEqual((state['position'],state['duration']),(61.5,240.0))
        self.assertEqual((state['eq_preset'],state['eq_bands']),('Rock',[1.0]*10))
        self.assertEqual(host._last_live_at,0.0)
        self.command({'cmd':'eq','band':3,'value':5.0},{'ok':True})
        state=self.snapshot()
        self.assertTrue(state['playing'])
        self.assertEqual((state['position'],state['duration']),(61.5,240.0))
        self.assertEqual(state['eq_preset'],'Rock')
        self.assertEqual(state['eq_bands'],[1.0,1.0,1.0,5.0,1.0,1.0,1.0,1.0,1.0,1.0])
        self.command({'cmd':'eq','name':'Flat'},{'ok':True,'eq_bands':[0.0]*10})
        state=self.snapshot()
        self.assertEqual(state['eq_preset'],'Flat')
        self.assertEqual(state['eq_bands'],[0.0]*10)
        self.assertEqual(state['duration'],240.0)

    def test_pause_status_reply_is_cached_immediately(self):
        self.command({'cmd':'toggle'},{'ok':True})
        state=self.snapshot()
        self.assertFalse(state['playing'])
        self.assertTrue(state['paused'])
        paused=dict(host._last_live_state,state='paused',position=62.0)
        self.command({'cmd':'status'},paused)
        state=self.snapshot()
        self.assertTrue(state['paused'])
        self.assertFalse(state['playing'])
        self.assertEqual((state['position'],state['duration']),(62.0,240.0))
        self.assertGreater(host._last_live_at,0)

    def test_failed_control_does_not_invent_changed_state(self):
        self.command({'cmd':'eq','band':3,'value':8.0},{'ok':False,'error':'unavailable'})
        self.assertEqual(self.snapshot()['eq_bands'],[1.0]*10)
        self.command({'cmd':'toggle'},{'ok':False})
        self.assertTrue(self.snapshot()['playing'])

    def test_cold_live_json_reads_cached_state_without_socket(self):
        with patch.object(host,'_cliamp_live',side_effect=AssertionError('GUI socket read')):
            state=json.loads(host.live_status_json())
        self.assertTrue(state['playing'])
        self.assertEqual((state['position'],state['duration']),(61.5,240.0))
        self.assertEqual(state['eq_preset'],'Rock')

if __name__=='__main__':
    unittest.main()
