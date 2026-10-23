"""GG's existing agent devices remain separate from Windows system input."""
import os
from pathlib import Path
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


class AgentInputTests(unittest.TestCase):
    def test_gg_bridge_routes_only_its_own_region_and_keeps_its_own_keyboard_focus(self):
        from backend.windows_input import WindowInput
        calls=[]
        def transport(command,**fields):
            calls.extend(fields['events']);return {'ok':True}
        bridge=WindowInput(target_pid=123,transport=transport)
        bridge.set_region(100,50,400,300,1.5)
        self.assertFalse(bridge.click(20,20))
        self.assertFalse(bridge.key('Tab'))
        self.assertTrue(bridge.click(200,150))
        self.assertTrue(bridge.keyboard_owned())
        self.assertTrue(bridge.key('Tab'))
        until=time.monotonic()+1
        while bridge.pending() and time.monotonic()<until: time.sleep(.001)
        self.assertEqual(calls[0],{'action':'CLICK','button':'left','x':150,'y':150})
        self.assertEqual(calls[1],{'action':'KEY','key':'Tab'})
        self.assertFalse(bridge.click(20,20))
        self.assertFalse(bridge.keyboard_owned())
        bridge.close()

    def test_slow_connection_does_not_block_agent_animation(self):
        from backend.windows_input import WindowInput
        gate=threading.Event()
        def delayed(*_,**fields): gate.wait(1);return {'ok':True}
        bridge=WindowInput(transport=delayed)
        bridge.set_region(0,0,1000,1000,1)
        begin=time.monotonic()
        for i in range(100): bridge.move(i,i)
        self.assertLess(time.monotonic()-begin,.05)
        self.assertLessEqual(len(bridge._events),1)
        gate.set();bridge.close()

    def test_virtual_mouse_and_keyboard_use_blender_events(self):
        from tools.blender import gg_blender_virtual_input as module
        events=[]
        window=SimpleNamespace(width=600,height=400,event_simulate=lambda **event: events.append(event))
        bpy=SimpleNamespace(app=SimpleNamespace(use_event_simulate=True),context=SimpleNamespace(
            window=window,preferences=SimpleNamespace(inputs=SimpleNamespace(use_mouse_continuous=True))))
        with patch.object(module,'_show') as cursor:
            reply=module.dispatch(bpy,{'target_pid':os.getpid(),'events':[
                {'action':'CLICK','x':200,'y':100},{'action':'KEY','key':'Tab'},
                {'action':'TYPE','text':'a1'}]})
        self.assertTrue(reply['ok'])
        self.assertEqual(events[0]['x'],200)
        self.assertEqual(events[0]['y'],299)
        self.assertEqual([event['type'] for event in events],
                         ['MOUSEMOVE','LEFTMOUSE','LEFTMOUSE','TAB','TAB','A','A','ONE','ONE'])
        self.assertFalse(bpy.context.preferences.inputs.use_mouse_continuous)
        self.assertTrue(cursor.called)

    def test_invalid_target_and_position_do_not_emit_events(self):
        from tools.blender import gg_blender_virtual_input as module
        events=[]
        window=SimpleNamespace(width=600,height=400,event_simulate=lambda **event:events.append(event))
        bpy=SimpleNamespace(app=SimpleNamespace(use_event_simulate=True),context=SimpleNamespace(
            window=window,preferences=SimpleNamespace(inputs=SimpleNamespace(use_mouse_continuous=True))))
        with patch.object(module,'_show'):
            self.assertFalse(module.dispatch(bpy,{'target_pid':-1,'events':[{'action':'CLICK','x':1,'y':1}]})['ok'])
            self.assertFalse(module.dispatch(bpy,{'events':[{'action':'CLICK','x':-1,'y':1}]})['ok'])
        self.assertEqual(events,[])

    def test_no_system_device_or_clipboard_access_in_agent_bridge(self):
        for name in ('backend/windows_input.py','tools/blender/gg_blender_virtual_input.py'):
            source=(ROOT/name).read_text(encoding='utf-8')
            for api in ('SendInput','SetCursorPos','keybd_event','mouse_event','SetForegroundWindow',
                        'AttachThreadInput','OpenClipboard'):
                self.assertNotIn(api,source,name+':'+api)


if __name__=='__main__': unittest.main()
