"""Actual QML timeline jobs arriving after a ready-loader ownership scan.

No Window or GPU. Independently authored timeline fixtures exercise QObject
inheritance and event-loop handoff rather than mocked animation metadata.
"""
import unittest
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication,QObject,QUrl
from PySide6.QtQml import QQmlComponent,QQmlEngine
from backend.game_engine_runtime import RuntimeClipDriver,named_nodes
from test_game_engine_runtime_lifecycle import LoaderProbe

class OrphanClips(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QCoreApplication.instance() or QCoreApplication([])
    def setUp(self):
        self.engine=QQmlEngine();self.components=[];self.loader=LoaderProbe();self.driver=RuntimeClipDriver()
        self.addCleanup(self.driver.close)
    def timeline(self,label,*,subclass=False):
        component=QQmlComponent(self.engine)
        declaration='property bool authoredMarker:true;' if subclass else ''
        source='''import QtQuick.Timeline
Timeline {enabled:true;startFrame:0;endFrame:1000
  animations:[TimelineAnimation {%s objectName:"%s";from:0;to:1000;duration:1000;loops:-1;running:true}]
}'''%(declaration,label)
        component.setData(source.encode(),QUrl('file:///timeline-job-fixture.qml'))
        self.assertEqual(component.errors(),[]);node=component.create()
        self.assertIsNotNone(node,str(component.errors()));self.components.append(component)
        node.setParent(self.loader)
        jobs=[child for child in node.findChildren(QObject) if child.inherits('QQuickTimelineAnimation')]
        self.assertEqual(len(jobs),1);self.assertTrue(jobs[0].property('running'))
        return node,jobs[0]
    def test_late_imported_children_are_claimed_by_one_deferred_rescan(self):
        self.assertFalse(self.driver.apply(self.loader,'idle'))
        timeline,job=self.timeline('idle')
        self.app.processEvents()
        self.assertFalse(job.property('running'))
        self.assertFalse(timeline.property('enabled'))
        self.assertTrue(self.driver.apply(self.loader,'idle'))
        self.assertTrue(job.property('running'))
        entry=self.driver._loaders[id(self.loader)]
        self.assertEqual(entry['jobs'],[job]);self.driver.close()
        self.assertFalse(job.property('running'));self.assertFalse(timeline.property('enabled'))
    def test_unknown_unnamed_qml_subclass_is_stopped_and_owned_for_release(self):
        timeline,job=self.timeline('',subclass=True)
        self.assertNotEqual(job.metaObject().className(),'QQuickTimelineAnimation')
        self.assertFalse(self.driver.apply(self.loader,'not-a-real-clip'))
        self.assertFalse(job.property('running'));self.assertFalse(timeline.property('enabled'))
        entry=self.driver._loaders[id(self.loader)]
        self.assertEqual(entry['animations'],{});self.assertEqual(entry['jobs'],[job])
        job.setProperty('running',True);timeline.setProperty('enabled',True)
        self.assertTrue(self.driver.release(self.loader))
        self.assertFalse(job.property('running'));self.assertFalse(timeline.property('enabled'))
    def test_pending_rescan_cannot_reactivate_released_or_replaced_owner(self):
        self.assertFalse(self.driver.apply(self.loader,'idle'))
        self.assertTrue(self.driver.release(self.loader))
        timeline,job=self.timeline('idle')
        self.app.processEvents()
        # A released owner does not gain ownership back from a queued callback.
        self.assertTrue(job.property('running'));self.assertNotIn(id(self.loader),self.driver._loaders)
        self.assertTrue(self.driver.apply(self.loader,'idle'))
        self.loader.source=QUrl('file:///authored/replacement.glb')
        self.assertFalse(job.property('running'));self.assertFalse(timeline.property('enabled'))
        self.driver.close();self.app.processEvents()
    def test_static_empty_scene_has_exactly_one_deferred_retry_and_no_hot_walks(self):
        with patch('backend.game_engine_runtime.named_nodes',wraps=named_nodes) as scans:
            self.assertFalse(self.driver.apply(self.loader,'idle'))
            self.app.processEvents();self.app.processEvents()
            self.assertEqual(scans.call_count,2)
            for _ in range(80):self.assertFalse(self.driver.apply(self.loader,'idle'))
            self.app.processEvents();self.assertEqual(scans.call_count,2)
    def test_closed_driver_cannot_run_queued_empty_scan(self):
        with patch('backend.game_engine_runtime.named_nodes',wraps=named_nodes) as scans:
            self.assertFalse(self.driver.apply(self.loader,'idle'))
            self.driver.close();self.app.processEvents()
            self.assertEqual(scans.call_count,1);self.assertEqual(self.driver._loaders,{})

if __name__=='__main__':unittest.main()
