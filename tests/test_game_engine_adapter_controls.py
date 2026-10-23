"""Original Lua camera/binding APIs must move the local rig and durable character state."""
import copy,json,math,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QObject
from PySide6.QtGui import QGuiApplication
from backend import game_engine_mmo as mmo,game_engine_character_creation as appearance
from backend.game_engine_presentation import Presentation
APP=QGuiApplication.instance() or QGuiApplication([])

class Bridge(QObject):
    def __init__(self,runtime):super().__init__();self.runtime=runtime
    def gameEngineClientControl(self,raw):return json.dumps(self.runtime.client_control(raw))
    def gameEngineClientControls(self,raw):return json.dumps(self.runtime.client_controls_batch(raw))

class Controls(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name)
        for context in (patch.dict(os.environ,{'XDG_STATE_HOME':str(root)}),patch.object(mmo,'DEFAULT_STASH_PATH',root/'stash.json'),patch.object(appearance,'STATE_PATH',root/'appearance.json')):
            context.start();self.addCleanup(context.stop)
        from backend.game_engine_host import GameEngineRuntime
        self.runtime=GameEngineRuntime();self.addCleanup(self.runtime.shutdown)
        self.bridge=Bridge(self.runtime);self.presentation=Presentation(self.bridge,device=False);self.addCleanup(self.presentation.close)
        self.ui=self.presentation.lua;self.publish()
    def publish(self):
        self.presentation.last_update=0;self.presentation.update(self.runtime.snapshot())
    def call(self,chunk):
        self.ui.execute(chunk);self.presentation._ui_requests(self.ui.request('requests'));self.publish()
    def control(self,kind,op,**fields):return self.runtime.client_control(json.dumps({'kind':kind,'op':op,**fields}))
    def test_original_five_views_end_stops_saves_and_fractional_yaw(self):
        self.call('SetView(1)');self.assertEqual(self.runtime._camera_distance,0.)
        self.call('PrevView()');self.assertEqual(self.runtime._camera_view_index,0)
        self.call('SetView(4.9)');self.assertEqual(self.runtime._camera_view_index,3);self.assertAlmostEqual(self.runtime._camera_pitch,-30.)
        self.call('NextView() NextView()');self.assertEqual(self.runtime._camera_view_index,4)
        self.runtime.set_input(json.dumps({'camera_distance':8.,'camera_pitch':-22.,'camera_yaw':155.5}))
        self.call('SaveView(2) SetView(1) SetView(2)');self.assertEqual(self.runtime._camera_distance,8.);self.assertEqual(self.runtime._camera_pitch,-22.)
        self.call('FlipCameraYaw(10.25)');self.assertAlmostEqual(self.runtime._camera_yaw,165.75)
        self.call('ResetView(2)');self.assertAlmostEqual(self.runtime._camera_distance,5.55);self.assertAlmostEqual(self.runtime._camera_pitch,-10.)
        self.assertEqual(self.ui.evaluate("return GetCVar('cameraView'),GetCVar('cameraDistanceA'),GetCVar('cameraPitchA')"),['1','5.550000','10.000000'])
        before=copy.deepcopy(self.runtime._camera_views)
        self.call("SetView(0) SaveView(6) ResetView('bad')");self.assertEqual(self.runtime._camera_views,before)
    def test_camera_pose_helmet_cloak_and_views_roundtrip_real_save_load(self):
        self.runtime.set_input(json.dumps({'camera_distance':9.,'camera_pitch':-21.,'camera_yaw':123.}))
        self.call('SaveView(3) ShowHelm(false) ShowCloak("0")');self.runtime.save_state()
        self.call('ResetView(3) ShowHelm(true) ShowCloak(true) SetView(1)')
        self.runtime.load_state();self.publish()
        self.assertEqual(self.runtime._camera_distance,9.);self.assertEqual(self.runtime._camera_pitch,-21.);self.assertAlmostEqual(self.runtime._camera_yaw,123.)
        self.assertEqual(self.ui.evaluate('return ShowingHelm(),ShowingCloak()'),[None,None])
        self.call('SetView(3)');self.assertEqual(self.runtime._camera_distance,9.)
        self.assertFalse(self.runtime._legacy_held);self.assertFalse(self.runtime._legacy_autorun)
    def test_original_hardware_gate_and_press_release_move_actual_player(self):
        self.ui.execute("MoveForwardStart() Jump() ToggleRun()");self.assertEqual(self.ui.request('requests')['binding_input'],[])
        self.ui.execute("CreateFrame('Frame','Input')");self.ui.request('addon_bindings',name='GGInput',source='<Bindings><Binding name="GG_FORWARD" runOnUp="true">if keystate == "down" then MoveForwardStart() else MoveForwardStop() end</Binding></Bindings>')
        self.ui.execute("SetBinding('W','GG_FORWARD')")
        self.ui.request('key',key='W');self.presentation._ui_requests(self.ui.request('requests'))
        with self.runtime._lock:
            before=(self.runtime._x[0],self.runtime._z[0])
            self.runtime._running=True
            try:
                for _ in range(24):self.runtime._tick_locked(1/60)
            finally:self.runtime._running=False
        self.assertGreater(math.hypot(self.runtime._x[0]-before[0],self.runtime._z[0]-before[1]),.25)
        self.ui.request('key_up',key='W');self.presentation._ui_requests(self.ui.request('requests'))
        self.assertFalse(self.runtime._legacy_held)
        self.runtime.set_input(json.dumps({'forward':.75}));self.assertEqual(self.runtime._legacy_input_locked(self.runtime._input)['forward'],.75)
    def test_autorun_opposing_channels_mouselook_walk_and_cancel(self):
        for key in ('MoveForward','MoveBackward'):self.control('input','Start',key=key)
        self.assertEqual(self.runtime._legacy_input_locked({'forward':1.})['forward'],0.)
        self.control('input','Cancel');self.control('input','Fire',key='ToggleAutoRun');self.assertEqual(self.runtime._legacy_input_locked({})['forward'],1.)
        self.control('input','Start',key='TurnRight');self.call('MouselookStart()')
        value=self.runtime._legacy_input_locked({});self.assertEqual(value['turn'],0.);self.assertEqual(value['strafe'],1.)
        self.control('input','Fire',key='ToggleRun');self.assertEqual(self.runtime._legacy_input_locked({})['forward'],.5)
        self.call('MouselookStop()');self.runtime.set_input(json.dumps({'cancel_legacy_input':True}))
        self.assertFalse(self.runtime._legacy_held);self.assertFalse(self.runtime._legacy_autorun)
    def test_visibility_same_frame_double_toggle_preserves_original_belief(self):
        self.call('ShowHelm(false) ShowHelm(false) ShowCloak(false) ShowHelm(true)')
        self.assertEqual(self.runtime._player_display,{'helm':True,'cloak':False,'sheath':1})
        self.assertEqual(self.ui.evaluate('return ShowingHelm(),ShowingCloak()'),[1,None])
        self.assertEqual(self.ui.request('requests')['worn_display'],[])
    def test_bad_commands_and_bad_saved_views_do_not_leave_nonfinite_pose(self):
        before=self.runtime._client_controls_save_locked()
        with patch('backend.game_engine_adapter_services.time.time',return_value=before['services']['clock']):
            for row in ({'kind':'camera','op':'Set','index':True},{'kind':'camera','op':'FlipYaw','value':float('nan')},{'kind':'input','op':'Start','key':'INVALID'}):
                self.assertIn('error',self.runtime.client_control(json.dumps(row)))
        self.assertEqual(self.runtime._client_controls_save_locked(),before)
        self.runtime._restore_client_controls_locked({'views':[[0,float('nan'),0]]*5,'current':0,'pose':[0,0,0]})
        self.assertTrue(all(math.isfinite(n) for row in self.runtime._camera_views for n in row))
        self.assertGreaterEqual(self.runtime._camera_distance,0)
    def test_real_equipment_stow_survives_compact_render_and_delta_transport(self):
        from backend import game_engine_items as items
        from backend.game_engine_render_transport import RenderTransport
        with self.runtime._lock:
            for key,old in list(self.runtime._item_instances.items()):
                if old.get('owner_id')=='player' and old.get('location')=='EQUIPPED':self.runtime._item_instances.pop(key)
            self.runtime._item_instances['stow-probe']=items.make_instance(self.runtime._item_catalog,'stow-probe','item.weapon_sword',location='EQUIPPED',owner_id='player',equipped_slot='MAIN_HAND')
            self.runtime._render_snapshot_cache=None
        transport=RenderTransport()
        def equipment():
            snap=self.runtime.render_snapshot();player=next(r for r in snap['render']['entities'] if r['kind']=='PLAYER');return snap,player['equipment'][0]
        before,row=equipment();self.assertFalse(row['visual_stowed']);transport.prepare(before)
        self.control('input','Fire',key='ToggleSheath');after,row=equipment()
        self.assertTrue(row['visual_stowed']);self.assertTrue(row['visual_visible']);self.assertEqual(row['attachment']['node'],'SOCKET_BACK')
        delta=transport.prepare(after);self.assertTrue(any(r['kind']=='PLAYER' for r in delta['render']['entities_delta']))
        self.control('input','Fire',key='ToggleSheath');_,row=equipment();self.assertFalse(row['visual_stowed'])
    def test_control_batch_single_snapshot_and_overflow_clears_held_input(self):
        original=self.runtime.snapshot_locked;calls=[]
        def count():calls.append(1);return original()
        with patch.object(self.runtime,'snapshot_locked',count):
            row=self.runtime.client_controls_batch(json.dumps([{'kind':'input','op':'Start','key':'MoveForward'}]*128))
        self.assertEqual(len(calls),1);self.assertNotIn('error',row);self.assertIn('MoveForward',self.runtime._legacy_held)
        row=self.runtime.client_controls_batch(json.dumps([{'kind':'input','op':'Stop','key':'MoveForward'}]*129))
        self.assertIn('error',row);self.assertFalse(self.runtime._legacy_held)
        self.control('input','Start',key='MoveForward')
        self.presentation._ui_requests({'binding_input':[{'op':'Start','key':'MoveForward'}]*129})
        self.assertFalse(self.runtime._legacy_held)
