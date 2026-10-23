"""Engine clock, runtime reset, finite API and real Qt transform integration."""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys
import subprocess
import unittest

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
from backend.game_engine_rigid_physics import PhysicsScene
from backend.game_engine_host import GameEngineRuntime


class RigidPhysicsTests(unittest.TestCase):
    def test_unavailable_backend_reports_without_allocating_scene(self):
        code="from backend.game_engine_rigid_physics import PhysicsScene;s=PhysicsScene();r=s.request({'op':'BODY_CREATE','id':'body'});assert not r['ok'];assert s.world is None;print('PASS')"
        result=subprocess.run([sys.executable,'-c',code],cwd=PROJECT,env={**os.environ,'GG_GAME_PHYSICS_NATIVE':'0'},
                              capture_output=True,text=True,check=True,timeout=15)
        self.assertEqual(result.stdout.strip(),'PASS')

    def test_scene_commands_validation_and_cleanup(self):
        scene=PhysicsScene()
        try:
            self.assertFalse(scene.request({'op':'STEP'})['ok'])
            self.assertIsNone(scene.world)
            scene.step(.1)  # An unused backend does not intercept existing test/tool clocks.
            self.assertFalse(scene.request({'op':'BODY_CREATE','id':'bad','params':{'shape':{'half_extents':[0,1,1]}}})['ok'])
            self.assertIsNone(scene.world)
            self.assertTrue(scene.request({'op':'CONFIGURE','params':{'workers':2}})['ok'])
            self.assertTrue(scene.request({'op':'BODY_CREATE','id':'body','params':{'shape':{'kind':'BOX'}}})['ok'])
            self.assertFalse(scene.request({'op':'BODY_CREATE','id':'body'})['ok'])
            self.assertFalse(scene.request({'op':'BODY_FORCE','id':'absent','params':{'value':[1,2,3]}})['ok'])
            self.assertFalse(scene.request({'op':'CONFIGURE','params':{'workers':4}})['ok'])
            self.assertFalse(scene.request({'op':'BODY_CREATE','id':'bad','params':{'shape':{'half_extents':[0,1,1]}}})['ok'])
            self.assertEqual(scene.status()['stats']['bodies'],1)
            self.assertFalse(scene.request({'op':'STATUS','path':'/tmp/unknown'})['ok'])
            with self.assertRaises(ValueError):scene.step(.1)
            self.assertTrue(scene.request({'op':'RESET'})['ok'])
            self.assertFalse(scene.status()['configured'])
            self.assertEqual(scene.settings['workers'],2)
        finally:scene.close()

    def test_engine_clock_pause_reset_and_shutdown(self):
        runtime=GameEngineRuntime()
        try:
            for request in ({'op':'BODY_CREATE','id':'ground','params':{'body_type':'STATIC','position':[0,-.5,0],'shape':{'half_extents':[5,.5,5]}}},
                            {'op':'BODY_CREATE','id':'ball','params':{'position':[0,3,0],'shape':{'kind':'SPHERE'}}}):
                self.assertTrue(runtime.physics_command(request)['ok'])
            before=runtime.physics_status()['stats']['steps']
            runtime.render_snapshot();runtime.physics_status()
            self.assertEqual(runtime.physics_status()['stats']['steps'],before)
            for _ in range(90):runtime.step()
            result=runtime.physics_command({'op':'BODY_STATE','id':'ball'})['result']
            self.assertAlmostEqual(result['position'][1],.5,delta=.03)
            self.assertEqual(runtime.physics_status()['stats']['steps'],90)
            frame=runtime.render_snapshot()
            self.assertEqual(frame['rigid_physics']['stats']['steps'],90)
            self.assertEqual(frame['rigid_physics']['bodies'][1]['scene_node'],'physics:ball')
            runtime.reset()
            self.assertEqual(runtime.physics_status()['stats']['bodies'],0)
            self.assertFalse(runtime.physics_status()['configured'])
        finally:runtime.shutdown()

    def test_native_recording_through_engine_api(self):
        runtime=GameEngineRuntime()
        try:
            self.assertTrue(runtime.physics_command({'op':'BODY_CREATE','id':'box','params':{'shape':{'kind':'BOX'}}})['ok'])
            self.assertTrue(runtime.physics_command({'op':'RECORD_START'})['ok'])
            for _ in range(20):runtime.step()
            reply=runtime.physics_command({'op':'RECORD_VERIFY'})
            self.assertTrue(reply['ok']);self.assertTrue(reply['result']['verified'])
        finally:runtime.shutdown()

    def test_qt_nodes_receive_native_position_and_rotation(self):
        from PySide6.QtCore import QObject
        from PySide6.QtGui import QGuiApplication
        from backend.game_engine_scene_driver import SceneDriver
        app=QGuiApplication.instance() or QGuiApplication([])
        scene=PhysicsScene();driver=SceneDriver();node=QObject()
        try:
            driver.register(node,'physics:test')
            scene.request({'op':'BODY_CREATE','id':'test','params':{'position':[1,4,2],'shape':{'kind':'BOX'}}})
            scene.step(1/60)
            driver.update({'state':'RUNNING','rigid_physics':scene.status(transforms=True)})
            self.assertAlmostEqual(node.property('position').x(),1)
            self.assertLess(node.property('position').y(),4)
            self.assertAlmostEqual(node.property('rotation').scalar(),1)
            self.assertTrue(node.property('nativeVisible'))
            scene.reset();driver.update({'rigid_physics':scene.frame()})
            self.assertFalse(node.property('nativeVisible'))
        finally:scene.close();node.deleteLater();app.processEvents()

    def test_desktop_qt_bridge_is_physics_only(self):
        from backend.chat_surface_host import ChatSurfaceHost
        # These slots deliberately use no desktop initialization or scene publication.
        value=json.loads(ChatSurfaceHost.gameEnginePhysicsStatus(None))
        self.assertTrue(value['capabilities']['available'])
        reply=json.loads(ChatSurfaceHost.gameEnginePhysicsCommand(None,'{"op":"CAPABILITIES"}'))
        self.assertTrue(reply['ok']);self.assertEqual(reply['result']['backend'],'BOX3D')
        self.assertFalse(json.loads(ChatSurfaceHost.gameEnginePhysicsCommand(None,'{"op":"DOWNLOAD"}'))['ok'])


if __name__=='__main__':unittest.main()
