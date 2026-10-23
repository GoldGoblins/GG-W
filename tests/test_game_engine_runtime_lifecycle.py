"""CPU QObject ownership proofs; no window, renderer, or imported-asset worker."""
from enum import IntEnum
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QObject, Property, QEnum, QUrl, Signal
from PySide6.QtQml import QQmlEngine
from shiboken6 import delete, isValid

from backend.game_engine_runtime import RuntimeClipDriver


class LoaderProbe(QObject):
    class Status(IntEnum):
        Empty = 0
        Success = 1
        Error = 2
        Loading = 3
    QEnum(Status)
    sourceChanged = Signal()
    statusChanged = Signal()

    def __init__(self):
        super().__init__()
        self._source = QUrl('file:///authored/first.glb')
        self._status = self.Status.Success

    @Property(QUrl, notify=sourceChanged)
    def source(self):return self._source
    @source.setter
    def source(self, value):
        self._source = QUrl(value);self.sourceChanged.emit()

    @Property(int, notify=statusChanged)
    def status(self):return int(self._status)
    @status.setter
    def status(self, value):
        self._status = self.Status(value);self.statusChanged.emit()


class AnimationProbe(QObject):
    """Actual QObject parent/lifetime with authored imported-animation metadata."""
    def __init__(self, parent, name):
        super().__init__(parent);self.setObjectName(name);self.writes = []
        self.setProperty('duration', 1500)
    def metaObject(self):
        return SimpleNamespace(className=lambda:'QQuickTimelineAnimation')
    def setProperty(self, name, value):
        self.writes.append((name, value));return super().setProperty(name, value)


def scene(loader):
    root = QObject(loader);jobs = {};timelines = {}
    for name in ('idle', 'walk'):
        timeline = QObject(root);job = AnimationProbe(timeline, name)
        jobs[name] = job;timelines[name] = timeline
    return root, jobs, timelines


class RuntimeLifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.named = patch('backend.game_engine_runtime.named_nodes',
                           side_effect=lambda loader, pattern:loader.findChildren(AnimationProbe))
        self.defaults = patch.object(RuntimeClipDriver, '_authored_defaults', return_value=[])
        self.named.start();self.defaults_mock = self.defaults.start()
        self.addCleanup(self.named.stop);self.addCleanup(self.defaults.stop)
        self.driver = RuntimeClipDriver();self.addCleanup(self.driver.close)
        self.loader = LoaderProbe();self.root, self.jobs, self.timelines = scene(self.loader)

    def stopped(self, jobs, timelines):
        self.assertTrue(all(not job.property('running') for job in jobs.values() if isValid(job)))
        self.assertTrue(all(not timeline.property('enabled') for timeline in timelines.values() if isValid(timeline)))

    def test_eviction_stops_owned_jobs_before_close_loses_them(self):
        self.driver.MAX_LOADERS = 1
        self.assertTrue(self.driver.apply(self.loader, 'walk'))
        other = LoaderProbe();root, jobs, timelines = scene(other)
        self.assertTrue(self.driver.apply(other, 'idle'))
        self.stopped(self.jobs, self.timelines)
        self.assertNotIn(id(self.loader), self.driver._loaders)
        self.driver.close();self.stopped(self.jobs, self.timelines);self.stopped(jobs, timelines)

    def test_source_signal_retires_live_old_scene_without_a_followup_apply(self):
        self.driver.apply(self.loader, 'walk');self.driver.set_paused(self.loader, True)
        self.loader.source = QUrl('file:///authored/second.glb')
        self.stopped(self.jobs, self.timelines)
        entry = self.driver._loaders[id(self.loader)]
        self.assertEqual(entry['animations'], {});self.assertTrue(entry['paused'])

    def test_loading_and_error_reject_activation_of_still_valid_old_children(self):
        for status in (LoaderProbe.Status.Loading, LoaderProbe.Status.Error, LoaderProbe.Status.Empty):
            with self.subTest(status=status):
                self.loader.status = LoaderProbe.Status.Success
                self.assertTrue(self.driver.apply(self.loader, 'walk'))
                self.loader.status = status
                self.stopped(self.jobs, self.timelines)
                self.assertFalse(self.driver.apply(self.loader, 'walk'))

    def test_source_reload_discovers_only_new_scene_and_preserves_pause(self):
        self.driver.apply(self.loader, 'walk');self.driver.set_paused(self.loader, True)
        self.loader.status = LoaderProbe.Status.Loading
        self.loader.source = QUrl('file:///authored/second.glb')
        self.root.setParent(None)
        root, jobs, timelines = scene(self.loader)
        self.loader.status = LoaderProbe.Status.Success
        self.assertTrue(self.driver.apply(self.loader, 'idle'))
        self.stopped(self.jobs, self.timelines)
        self.assertTrue(jobs['idle'].property('running'))
        self.assertTrue(jobs['idle'].property('paused'))
        self.assertIs(self.driver._loaders[id(self.loader)]['animations']['idle'], jobs['idle'])

    def test_qml_reads_the_actual_status_when_python_has_no_enum_converter(self):
        engine = QQmlEngine()
        QQmlEngine.setContextForObject(self.loader, engine.rootContext())
        original = self.loader.property
        def enum_unavailable(name):
            if name == 'status':
                raise RuntimeError("Can't find converter for 'QQuick3DRuntimeLoader::Status'.")
            return original(name)
        # QML reads the real C++ QObject property, bypassing only the Python
        # converter failure observed with the actual RuntimeLoader smoke.
        with patch.object(self.loader, 'property', side_effect=enum_unavailable):
            self.assertTrue(self.driver.apply(self.loader, 'walk'))
            self.loader.status = LoaderProbe.Status.Loading
            self.stopped(self.jobs, self.timelines)
            self.assertFalse(self.driver.apply(self.loader, 'walk'))
            self.loader.status = LoaderProbe.Status.Success
            self.assertTrue(self.driver.apply(self.loader, 'idle'))
            self.assertTrue(self.jobs['idle'].property('running'))

    def test_unreadable_status_releases_owned_jobs_instead_of_leaving_them_running(self):
        self.driver.apply(self.loader, 'walk')
        original = self.loader.property
        def unreadable(name):
            if name == 'status':raise RuntimeError('Unavailable native enum')
            return original(name)
        with patch.object(self.loader, 'property', side_effect=unreadable):
            self.assertFalse(self.driver.apply(self.loader, 'walk'))
        self.stopped(self.jobs, self.timelines)
        self.assertNotIn(id(self.loader), self.driver._loaders)

    def test_release_stops_and_disconnects_only_that_loader(self):
        self.driver.apply(self.loader, 'walk')
        other = LoaderProbe();root, jobs, timelines = scene(other)
        self.driver.apply(other, 'idle')
        self.assertTrue(self.driver.release(self.loader));self.assertFalse(self.driver.release(self.loader))
        self.stopped(self.jobs, self.timelines)
        self.loader.source = QUrl('file:///authored/released.glb')
        self.assertNotIn(id(self.loader), self.driver._loaders)
        self.assertTrue(jobs['idle'].property('running'))

    def test_invalid_later_child_invalidates_cache_even_when_first_child_survives(self):
        self.driver.apply(self.loader, 'walk');delete(self.jobs['walk'])
        self.assertTrue(isValid(self.jobs['idle']))
        self.assertTrue(self.driver.apply(self.loader, 'idle'))
        self.assertFalse(self.timelines['walk'].property('enabled'))
        self.assertNotIn('walk', self.driver._loaders[id(self.loader)]['animations'])

    def test_close_stops_surviving_timelines_when_animation_child_was_deleted(self):
        self.driver.apply(self.loader, 'walk');delete(self.jobs['walk'])
        self.assertTrue(self.timelines['walk'].property('enabled'))
        self.driver.close();self.driver.close()
        self.stopped(self.jobs, self.timelines)
        self.assertFalse(self.driver.apply(self.loader, 'idle'))

    def test_loader_destruction_releases_cached_lifetimes_without_accessing_dead_children(self):
        self.driver.apply(self.loader, 'walk');key = id(self.loader)
        delete(self.loader)
        self.assertNotIn(key, self.driver._loaders)
        self.driver.close()

    def test_unchanged_clip_preserves_timing_and_does_not_restart(self):
        self.driver.apply(self.loader, 'walk', 2.)
        first = list(self.jobs['walk'].writes)
        self.driver.apply(self.loader, 'walk', 2.)
        added = self.jobs['walk'].writes[len(first):]
        self.assertNotIn(('running', True), added)
        self.assertFalse(any(name == 'duration' for name, value in added))
        self.assertEqual(self.jobs['walk'].property('duration'), 500)
        self.assertEqual(self.jobs['walk'].property('loops'), -1)
        self.assertEqual(self.defaults_mock.call_count, 1)


if __name__ == '__main__':unittest.main()
