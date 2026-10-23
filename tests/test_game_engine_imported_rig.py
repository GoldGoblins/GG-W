"""Socket lookup ownership, hot-path and source-retirement regressions."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QObject, QUrl
from PySide6.QtGui import QQuaternion, QVector3D
from shiboken6 import delete

from backend.game_engine_runtime import imported_named_node, named_nodes, RuntimeClipDriver, scene_models
from test_game_engine_runtime_lifecycle import LoaderProbe


class RigNode(QObject):
    def __init__(self, parent, name=''):
        super().__init__(parent);self.setObjectName(name)
        self.setProperty('position', QVector3D())
        self.setProperty('rotation', QQuaternion())
    def inherits(self, name):
        return name == 'QQuick3DNode' or super().inherits(name)


class Keyframes(QObject):
    def inherits(self, name):
        return name == 'QQuickKeyframeGroup' or super().inherits(name)
    def children(self):
        raise AssertionError('Socket or clip search descended into a keyframe table')


class ImportedRig(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.loader = LoaderProbe()
        self.root = RigNode(self.loader)
        self.hand = RigNode(self.root, 'Hand_R')
        self.keys = Keyframes(self.loader)

    def test_hot_socket_lookups_do_not_repeat_any_scene_or_keyframe_walk(self):
        self.assertIs(imported_named_node(self.loader, 'hand_r'), self.hand)
        with patch.object(self.loader, 'children', side_effect=AssertionError('Repeated scene walk')):
            for _ in range(100):
                self.assertIs(imported_named_node(self.loader, 'HAND_R'), self.hand)

    def test_clip_search_does_not_enter_sibling_keyframe_groups(self):
        self.assertEqual(named_nodes(self.loader, '^hand_r$'), [self.hand])

    def test_material_model_search_never_enters_sibling_keyframe_tables(self):
        self.assertEqual(list(scene_models(self.loader)), [])

    def test_authored_rest_defaults_reuse_the_small_rig_index(self):
        import json
        self.root.setObjectName('');self.hand.setObjectName('')
        document = dict(nodes=[dict(name='Root', children=[1]), dict(name='Hand_R')],
                        scenes=[dict(nodes=[0])], scene=0,
                        animations=[dict(channels=[dict(target=dict(node=1, path='rotation'))])])
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'rig.gltf';source.write_text(json.dumps(document))
            self.loader.source = QUrl.fromLocalFile(str(source))
            defaults = RuntimeClipDriver._authored_defaults(self.loader)
            self.assertEqual(len(defaults), 1)
            self.assertIs(defaults[0][0], self.hand)
            self.assertEqual(defaults[0][1]['rotation'], QQuaternion())

    def test_source_retirement_resolves_the_new_scene_instead_of_old_live_nodes(self):
        self.assertIs(imported_named_node(self.loader, 'Hand_R'), self.hand)
        self.root.setParent(None)
        self.loader.source = QUrl('file:///authored/second.glb')
        new_root = RigNode(self.loader);new_hand = RigNode(new_root, 'Hand_R')
        self.assertIs(imported_named_node(self.loader, 'Hand_R'), new_hand)

    def test_status_reload_invalidates_names_even_when_source_is_unchanged(self):
        self.assertIs(imported_named_node(self.loader, 'Hand_R'), self.hand)
        delete(self.root)
        self.loader.status = LoaderProbe.Status.Loading
        new_root = RigNode(self.loader);new_hand = RigNode(new_root, 'Hand_R')
        self.loader.status = LoaderProbe.Status.Success
        self.assertIs(imported_named_node(self.loader, 'Hand_R'), new_hand)

    def test_deleted_cached_joint_is_not_returned_and_new_joint_can_be_resolved(self):
        self.assertIs(imported_named_node(self.loader, 'Hand_R'), self.hand)
        delete(self.hand)
        replacement = RigNode(self.root, 'Hand_R')
        self.assertIs(imported_named_node(self.loader, 'Hand_R'), replacement)

    def test_serialized_tree_restores_authored_names_and_caches_missing_sockets(self):
        import json
        self.root.setObjectName('');self.hand.setObjectName('')
        document = dict(nodes=[dict(name='Root', children=[1]), dict(name='Hand_R')],
                        scenes=[dict(nodes=[0])], scene=0)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'rig.gltf';source.write_text(json.dumps(document))
            self.loader.source = QUrl.fromLocalFile(str(source))
            self.assertIs(imported_named_node(self.loader, 'Hand_R'), self.hand)
            self.assertEqual(self.root.objectName(), 'Root')
            with patch.object(self.loader, 'children', side_effect=AssertionError('Repeated scene walk')):
                for _ in range(100):
                    self.assertIsNone(imported_named_node(self.loader, 'Unprovided_Socket'))


if __name__ == '__main__':unittest.main()
