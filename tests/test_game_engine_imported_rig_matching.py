"""Bounded exact imported-tree matching and ready/deferred epoch custody.

Fixtures author both serialized glTF hierarchy and actual QObject scene nodes.
No window, renderer, inferred joints, or production model replacements.
"""
from collections import Counter
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QObject, QUrl
from PySide6.QtGui import QVector3D
from PySide6.QtQml import QQmlComponent, QQmlEngine
from shiboken6 import delete

from backend.game_engine_runtime import imported_named_node, RuntimeClipDriver
from test_game_engine_imported_rig import RigNode
from test_game_engine_runtime_lifecycle import LoaderProbe


class CountedNode(RigNode):
    def __init__(self, parent):
        super().__init__(parent)
        self.child_reads = 0
        self.transform_reads = Counter()

    def children(self):
        self.child_reads += 1
        return super().children()

    def property(self, name):
        if name in ('position', 'rotation'):
            self.transform_reads[name] += 1
        return super().property(name)


class ImportedRigMatching(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.loader = LoaderProbe()
        self.addCleanup(delete, self.loader)

    def authored(self, nodes, *, animations=()):
        source = Path(self.directory.name) / 'authored.gltf'
        source.write_text(json.dumps(dict(nodes=nodes, scenes=[dict(nodes=[0])],
                                         scene=0, animations=animations)), encoding='utf-8')
        self.loader.source = QUrl.fromLocalFile(str(source))

    def test_nonmatching_ready_scene_caches_all_missing_names_without_guessing_transforms(self):
        self.authored([dict(name='Root', children=[1]),
                       dict(name='Hand_R', translation=[1, 0, 0])])
        root = CountedNode(self.loader)
        hand = CountedNode(root)
        with patch.object(self.loader, 'children', wraps=self.loader.children) as reads:
            self.assertIsNone(imported_named_node(self.loader, 'Hand_R'))
            self.assertTrue(self.loader._gg_rig_names['resolved'])
            counts = (reads.call_count, root.child_reads, hand.child_reads,
                      dict(root.transform_reads), dict(hand.transform_reads))
            with patch('backend.game_engine_runtime._imported_node_document',
                       side_effect=AssertionError('Repeated failed source resolution')):
                for index in range(100):
                    self.assertIsNone(imported_named_node(self.loader, f'Missing_{index}'))
            self.assertEqual(counts, (reads.call_count, root.child_reads, hand.child_reads,
                                      dict(root.transform_reads), dict(hand.transform_reads)))
        self.assertEqual(root.objectName(), '')
        self.assertEqual(hand.objectName(), '')
        self.assertEqual(hand.property('position'), QVector3D())

    def test_status_reload_retries_exact_matching_after_static_transform_mismatch(self):
        self.authored([dict(name='Root', children=[1]),
                       dict(name='Hand_R', translation=[1, 0, 0])])
        root = RigNode(self.loader)
        hand = RigNode(root)
        self.assertIsNone(imported_named_node(self.loader, 'Hand_R'))
        self.loader.status = LoaderProbe.Status.Loading
        hand.setProperty('position', QVector3D(1, 0, 0))
        self.loader.status = LoaderProbe.Status.Success
        self.assertIs(imported_named_node(self.loader, 'Hand_R'), hand)
        self.assertEqual(root.objectName(), 'Root')

    def test_loading_failure_is_not_accepted_as_a_completed_negative_result(self):
        self.authored([dict(name='Root', children=[1]), dict(name='Hand_R')])
        root = RigNode(self.loader)
        self.loader.status = LoaderProbe.Status.Loading
        self.assertIsNone(imported_named_node(self.loader, 'Hand_R'))
        self.assertFalse(self.loader._gg_rig_names['resolved'])
        hand = RigNode(root)
        self.loader.status = LoaderProbe.Status.Success
        self.assertIs(imported_named_node(self.loader, 'Hand_R'), hand)

    def test_deleted_unnamed_node_invalidates_a_cached_negative_without_status_change(self):
        self.authored([dict(name='Root', children=[1]),
                       dict(name='Hand_R', translation=[1, 0, 0])])
        root = RigNode(self.loader)
        rejected = RigNode(root)
        self.assertIsNone(imported_named_node(self.loader, 'Hand_R'))
        delete(rejected)
        self.assertIsNone(self.loader._gg_rig_names)
        hand = RigNode(root)
        hand.setProperty('position', QVector3D(1, 0, 0))
        self.assertIs(imported_named_node(self.loader, 'Hand_R'), hand)

    def test_source_change_discards_negative_result_for_the_new_authored_tree(self):
        self.authored([dict(name='Root', children=[1]),
                       dict(name='Hand_R', translation=[1, 0, 0])])
        root = RigNode(self.loader)
        hand = RigNode(root)
        self.assertIsNone(imported_named_node(self.loader, 'Hand_R'))
        rejected_index = self.loader._gg_rig_names
        source = Path(self.directory.name) / 'replacement.gltf'
        source.write_text(json.dumps(dict(nodes=[dict(name='Root', children=[1]),
                                                dict(name='Hand_R')],
                                         scenes=[dict(nodes=[0])], scene=0)), encoding='utf-8')
        self.loader.source = QUrl.fromLocalFile(str(source))
        self.assertIs(imported_named_node(self.loader, 'Hand_R'), hand)
        self.assertIsNot(self.loader._gg_rig_names, rejected_index)

    def test_ambiguous_nonmatching_rig_reads_each_scene_once_and_each_match_once(self):
        # Every candidate has the same chain shape until the authored final
        # translation. Candidate roots therefore revisit the same descendants
        # with different indexes; memoization must bound each (index, node).
        expected_count, actual_count = 80, 240
        specs = [dict(name=f'Joint_{index}', children=[index + 1])
                 for index in range(expected_count - 1)]
        specs.append(dict(name='Hand_R', translation=[1, 0, 0]))
        self.authored(specs)
        actual = []
        parent = self.loader
        for _ in range(actual_count):
            parent = CountedNode(parent)
            actual.append(parent)
        with patch.object(self.loader, 'children', wraps=self.loader.children) as reads:
            self.assertIsNone(imported_named_node(self.loader, 'Hand_R'))
            self.assertEqual(reads.call_count, 1)
        self.assertTrue(all(node.child_reads == 1 for node in actual))
        self.assertLessEqual(max(node.transform_reads['position'] for node in actual), expected_count)
        self.assertLessEqual(sum(node.transform_reads['position'] for node in actual),
                             expected_count * actual_count)
        self.assertTrue(all(not node.objectName() for node in actual))
        with patch.object(self.loader, 'children', side_effect=AssertionError('Hot failed traversal')):
            self.assertIsNone(imported_named_node(self.loader, 'hips'))

    def test_deferred_ready_import_rescan_refreshes_empty_rig_and_actual_late_timeline(self):
        self.authored([dict(name='Root', children=[1]), dict(name='Hand_R')],
                      animations=[dict(channels=[dict(target=dict(node=1, path='rotation'))])])
        driver = RuntimeClipDriver()
        self.addCleanup(driver.close)
        engine = QQmlEngine()
        component = QQmlComponent(engine)
        self.assertFalse(driver.apply(self.loader, 'idle'))
        empty_index = self.loader._gg_rig_names
        self.assertEqual(empty_index['scene'], [])
        root = RigNode(self.loader)
        hand = RigNode(root)
        component.setData(b'''import QtQuick.Timeline
Timeline {enabled:true;startFrame:0;endFrame:1000
 animations:[TimelineAnimation {objectName:"idle";from:0;to:1000;duration:1000;loops:-1;running:true}]
}''', QUrl('file:///late-import-fixture.qml'))
        timeline = component.create()
        self.assertIsNotNone(timeline, str(component.errors()))
        timeline.setParent(self.loader)
        jobs = [node for node in timeline.findChildren(QObject)
                if node.inherits('QQuickTimelineAnimation')]
        self.assertEqual(len(jobs), 1)
        self.app.processEvents()
        self.assertIsNot(self.loader._gg_rig_names, empty_index)
        self.assertIs(imported_named_node(self.loader, 'Hand_R'), hand)
        self.assertEqual(root.objectName(), 'Root')
        self.assertIs(driver._loaders[id(self.loader)]['defaults'][0][0], hand)
        self.assertFalse(jobs[0].property('running'))
        self.assertTrue(driver.apply(self.loader, 'idle'))
        self.assertTrue(jobs[0].property('running'))
        driver.close()
        self.assertFalse(jobs[0].property('running'))


if __name__ == '__main__':
    unittest.main()
