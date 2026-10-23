"""Real QML animation jobs follow retained-scene visibility and pause state."""
import json
import unittest

from PySide6.QtCore import QCoreApplication, QObject, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from backend.game_engine_runtime import RuntimeClipDriver
from backend.game_engine_scene_driver import SceneDriver
from test_game_engine_runtime_lifecycle import LoaderProbe


class SceneAnimationVisibility(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.engine = QQmlEngine()
        self.components = []
        self.loader = LoaderProbe()
        self.driver = RuntimeClipDriver()
        self.addCleanup(self.driver.close)
        self.jobs = {}
        for name in ('idle', 'walk'):
            component = QQmlComponent(self.engine)
            component.setData(('''import QtQuick.Timeline
Timeline {enabled:true;startFrame:0;endFrame:1000;
animations:[TimelineAnimation {objectName:"%s";from:0;to:1000;duration:1000;loops:-1;running:true}]}
''' % name).encode(), QUrl('file:///visibility-timeline.qml'))
            timeline = component.create()
            self.assertIsNotNone(timeline, str(component.errors()))
            timeline.setParent(self.loader)
            self.components.append(component)
            self.jobs[name] = next(child for child in timeline.children()
                                   if child.inherits('QQuickTimelineAnimation'))
        self.scene = SceneDriver()
        self.node = QObject()
        self.scene.register(self.node, 'real-npc')
        self.assertTrue(self.scene.set_view(json.dumps(dict(x=0, y=1, z=0, heading=0,
            pitch=0, fov=45, aspect=1.6, far=100))))
        self.assertTrue(self.driver.apply(self.loader, 'idle'))
        self.scene.register_rig(self.loader, 'real-npc', self.driver)

    def update(self, z, time, state='RUNNING', hidden=False):
        self.scene.update(dict(state=state, player={'time_s': time}, render={'entities': [
            dict(id='real-npc', kind='NPC', x=0, y=0, z=z, yaw=0, hidden=hidden)]}))

    def test_culled_real_job_pauses_and_new_selected_clip_remains_paused_until_visible(self):
        self.update(10, 0)
        self.assertFalse(self.jobs['idle'].property('paused'))
        self.update(-10, 1)
        self.assertTrue(self.node.property('nativeVisible'))
        self.update(-10, 1.51)
        self.assertFalse(self.node.property('nativeVisible'))
        self.assertTrue(self.jobs['idle'].property('paused'))
        self.assertTrue(self.driver.apply(self.loader, 'walk'))
        self.assertFalse(self.jobs['idle'].property('running'))
        self.assertTrue(self.jobs['walk'].property('running'))
        self.assertTrue(self.jobs['walk'].property('paused'))
        self.update(10, 1.52)
        self.assertTrue(self.node.property('nativeVisible'))
        self.assertFalse(self.jobs['walk'].property('paused'))
        self.assertEqual(self.driver._loaders[id(self.loader)]['active'], 'walk')

    def test_hidden_and_simulation_pause_do_not_drop_or_recreate_retained_rig(self):
        entry = self.driver._loaders[id(self.loader)]
        self.update(10, 0, hidden=True)
        self.assertFalse(self.node.property('nativeVisible'))
        self.assertTrue(self.jobs['idle'].property('paused'))
        self.update(10, .1, state='PAUSED')
        self.assertTrue(self.node.property('nativeVisible'))
        self.assertTrue(self.jobs['idle'].property('paused'))
        self.update(10, .2)
        self.assertFalse(self.jobs['idle'].property('paused'))
        self.assertIs(self.driver._loaders[id(self.loader)], entry)
        self.assertIs(self.scene.rigs['real-npc'][0], self.loader)


if __name__ == '__main__':
    unittest.main()
