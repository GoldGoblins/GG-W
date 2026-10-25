"""Activity metadata tests: no screenshots, capture workers, UI or network."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from backend import windows_vision_activity as activity


class ActivityStoreTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.live = {123}
        self.store = activity._MemoryStore(clock=lambda: self.now,
            alive=lambda pid: pid in self.live, pid=123)

    def test_malformed_owner_id_is_rejected_before_native_process_query(self):
        self.store.begin("frame", 8)
        for pid in (0, -1, True, 2**100):
            data = json.loads(json.dumps(self.store.data))
            next(iter(data["active"].values()))["pid"] = pid
            with self.subTest(pid=pid), self.assertRaises(ValueError):
                activity._MemoryStore(data=data)
        with patch("psutil.pid_exists") as native:
            self.assertFalse(activity._alive(2**100))
            native.assert_not_called()

    def test_contended_reader_cache_expires_failed_activity_instead_of_restarting_error(self):
        self.store.begin("frame",8)
        channel = activity._WindowsChannel.__new__(activity._WindowsChannel)
        channel.kernel = SimpleNamespace(WaitForSingleObject=lambda *args:258)
        channel.mutex = None
        channel.cached = json.loads(json.dumps(self.store.data))
        store_type = activity._MemoryStore
        def cached_store(*,data):
            return store_type(clock=lambda:self.now,alive=lambda pid:True,data=data)
        with patch.object(activity,"_MemoryStore",side_effect=cached_store):
            self.now = 109
            self.assertEqual(channel.call("snapshot")["state"],"error")
            self.now = 112
            self.assertEqual(channel.call("snapshot")["state"],"off")

    def test_quick_success_is_recent_not_a_live_capture(self):
        lease = self.store.begin("frame", 8)
        started = self.store.snapshot()
        self.assertEqual(started["state"], "capturing")
        self.assertIsNone(started["frame_age_ms"])
        self.assertEqual(started["received_fps"], 0)
        self.store.update(lease, frames=1, last_frame_at=self.now)
        self.assertEqual(self.store.snapshot()["frame_age_ms"], 0)
        self.store.finish(lease, {"frame_count": 1, "received_fps": 12})
        self.now += 1
        recent = self.store.snapshot()
        self.assertEqual(recent["state"], "observed")
        self.assertEqual(recent["last_delivered_age_ms"], 1000)
        self.assertEqual(recent["last_observation_frames"], 1)
        self.assertEqual(recent["last_observation_fps"], 12)
        self.assertEqual(recent["received_fps"], 0)
        self.assertEqual(recent["frame_count"], 0)
        self.assertIsNone(recent["frame_age_ms"])
        self.now += 2
        idle = self.store.snapshot()
        self.assertEqual(idle["state"], "off")
        self.assertIsNone(idle["last_delivered_age_ms"])
        self.assertEqual(idle["buffer_bytes"], 0)

    def test_video_activity_is_distinguished_without_a_source_url(self):
        lease = self.store.begin("video",120)
        self.assertEqual(self.store.snapshot()["observation_kind"],"video")
        self.store.update(lease,frames=3,last_frame_at=self.now)
        self.store.finish(lease,{"frame_count":3,"source":"PRIVATE_URL"})
        state = self.store.snapshot()
        self.assertEqual(state["state"],"observed")
        self.assertEqual(state["last_observation_kind"],"video")
        self.assertNotIn("PRIVATE_URL",json.dumps(self.store.data))

    def test_progress_is_actual_monotonic_and_overlaps_are_isolated(self):
        first = self.store.begin("frame", 8)
        second = self.store.begin("clip", 8)
        self.store.update(first, frames=1, last_frame_at=self.now)
        self.now += 0.1
        self.store.update(second, frames=3, last_frame_at=self.now, received_fps=20)
        self.store.update(second, frames=2, last_frame_at=self.now - 0.1, received_fps=99)
        state = self.store.snapshot()
        self.assertEqual((state["active_count"], state["frame_count"], state["received_fps"]), (2, 4, 20))
        self.store.finish(first, {"frame_count": 1})
        self.assertEqual(self.store.snapshot()["active_count"], 1)
        self.assertEqual(self.store.snapshot()["state"], "capturing")
        self.assertFalse(self.store.cancelled(second))
        self.store.finish(second, {"frame_count": 3, "received_fps": 20})
        self.assertEqual(self.store.snapshot()["state"], "observed")

    def test_stop_cancels_every_lease_and_late_finish_cannot_relight(self):
        leases = [self.store.begin("clip", 8), self.store.begin("video", 120)]
        self.store.stop()
        for lease in leases:
            self.assertTrue(self.store.cancelled(lease))
            self.assertFalse(self.store.update(lease, frames=1, last_frame_at=self.now))
            self.store.finish(lease, {"frame_count": 1})
        self.assertEqual(self.store.snapshot()["state"], "off")
        fresh = self.store.begin("frame", 1)
        self.assertNotEqual(fresh["generation"], leases[0]["generation"])
        self.assertFalse(self.store.cancelled(fresh))

    def test_failures_are_sanitized_and_never_become_success(self):
        for error, expected in [("TimeoutError", "TimeoutError"),
                                ("https://private.example/secret.png", "CaptureError")]:
            with self.subTest(error=error):
                lease = self.store.begin("frame", 8)
                self.store.finish(lease, {"frame_count": 100, "jpeg": "PRIVATE"}, error)
                state = self.store.snapshot()
                self.assertEqual((state["state"], state["error"]), ("error", expected))
                self.assertEqual(state["last_observation_frames"], 0)
                self.assertNotIn("PRIVATE", json.dumps(self.store.data))
                self.assertNotIn("private.example", json.dumps(self.store.data))
                self.now += 3
                self.assertEqual(self.store.snapshot()["state"], "off")
        lease = self.store.begin("frame", 8)
        self.store.finish(lease, {"frame_count": 0})
        self.assertEqual(self.store.snapshot()["error"], "NoFrames")

    def test_deadline_caps_and_dead_owners_cannot_stay_active(self):
        screen = self.store.begin("clip", 500)
        video = self.store.begin("video", 500)
        self.assertEqual(self.store.data["active"][screen["token"]]["deadline"], 108)
        self.assertEqual(self.store.data["active"][video["token"]]["deadline"], 220)
        self.now = 108
        self.assertTrue(self.store.cancelled(screen))
        self.assertFalse(self.store.cancelled(video))
        self.live.clear()
        self.assertTrue(self.store.cancelled(video))
        self.assertEqual(self.store.snapshot()["active_count"], 0)
        self.assertEqual(self.store.snapshot()["error"], "OwnerExited")
        self.now += 3
        self.assertEqual(self.store.snapshot()["state"], "off")

    def test_slots_are_bounded_and_released_after_failure(self):
        leases = [self.store.begin("frame", 8) for _ in range(8)]
        with self.assertRaisesRegex(RuntimeError, "Too many"):
            self.store.begin("frame", 8)
        self.store.finish(leases[0], error="RuntimeError")
        self.assertFalse(self.store.cancelled(self.store.begin("frame", 8)))
        self.assertEqual(self.store.snapshot()["active_count"], 8)

    def test_only_safe_metadata_can_enter_the_store(self):
        for kind, timeout in [("https://example.test/video", 8), ("frame", float("nan")),
                              ("clip", float("inf")), ("frame", 0), ("frame", -1)]:
            with self.subTest(kind=kind, timeout=timeout), self.assertRaises(ValueError):
                self.store.begin(kind, timeout)
        lease = self.store.begin("frame", 8)
        for parameters in [dict(frames=-1, last_frame_at=self.now),
                           dict(frames=1, last_frame_at=self.now + 1),
                           dict(frames=1, last_frame_at=float("nan")),
                           dict(frames=1, last_frame_at=self.now, received_fps=float("inf"))]:
            with self.subTest(parameters=parameters), self.assertRaises(ValueError):
                self.store.update(lease, **parameters)
        self.store.finish(lease, {"frame_count": 1, "received_fps": float("nan"),
            "frames": [{"jpeg": "SECRET_IMAGE"}], "source": "https://private.test"})
        data = json.dumps(self.store.data, allow_nan=False)
        self.assertNotIn("SECRET_IMAGE", data)
        self.assertNotIn("private.test", data)
        self.assertLess(len(data), activity.CHANNEL_BYTES)

    def test_restored_metadata_is_validated(self):
        lease = self.store.begin("frame", 8)
        copy = activity._MemoryStore(clock=lambda: self.now, alive=lambda pid: True,
                                     data=json.loads(json.dumps(self.store.data)))
        self.assertFalse(copy.cancelled(lease))
        for data in [{}, {**self.store.data, "source": "PRIVATE"},
                     {**self.store.data, "active": {"bad": {}}}]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                activity._MemoryStore(data=data)

    def test_liveness_uses_only_the_owner_pid_and_denial_is_not_death(self):
        with patch("psutil.pid_exists", return_value=False) as exists:
            self.assertFalse(activity._alive(123))
            exists.assert_called_once_with(123)
        with patch("psutil.pid_exists", side_effect=PermissionError):
            self.assertTrue(activity._alive(123))


@unittest.skipUnless(os.name == "nt", "Windows named RAM integration")
class WindowsActivityChannelTests(unittest.TestCase):
    def run_probe(self, source):
        # This path is an identity only. The channel must not create it.
        identity = str(Path(tempfile.gettempdir()) / ("gg-eyes-activity-" + uuid.uuid4().hex))
        environment = dict(os.environ, GG_DESKTOP_STATE_ROOT=identity, PYTHONUTF8="1")
        prefix = "import json, os, sys, time\nfrom backend import windows_vision_activity as activity\n"
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        result = subprocess.run([sys.executable, "-B", "-c", prefix + source], cwd=PROJECT,
            env=environment, capture_output=True, text=True, timeout=15, **options)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(Path(identity).exists())
        return result.stdout

    def test_short_worker_metadata_survives_worker_exit_in_parent_handle(self):
        output = self.run_probe('''
activity.snapshot()
child = "from backend import windows_vision_activity as a; import time; lease=a.begin('frame',8); a.update(lease,frames=1,last_frame_at=time.monotonic()); a.finish(lease,{'frame_count':1,'received_fps':0})"
import subprocess
result=subprocess.run([sys.executable,'-B','-c',child],capture_output=True,text=True,timeout=5,creationflags=subprocess.CREATE_NO_WINDOW)
assert result.returncode == 0, result.stderr
state=activity.snapshot()
assert state['state'] == 'observed', state
assert state['last_observation_frames'] == 1, state
assert state['received_fps'] == 0 and state['frame_age_ms'] is None, state
print('PERSISTENCE_PASS')
''')
        self.assertIn("PERSISTENCE_PASS", output)

    def test_crossprocess_stop_and_owner_death_cleanup(self):
        output = self.run_probe('''
activity.snapshot()
import subprocess
child="from backend import windows_vision_activity as a; import json,sys; lease=a.begin('clip',8); print(json.dumps(lease),flush=True); sys.stdin.readline(); print(a.cancelled(lease),flush=True); a.finish(lease,{'frame_count':1})"
process=subprocess.Popen([sys.executable,'-B','-c',child],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
try:
    lease=json.loads(process.stdout.readline())
    assert activity.snapshot()['active_count'] == 1
    activity.stop()
    out,err=process.communicate('continue\\n',timeout=5)
    assert process.returncode == 0 and out.strip() == 'True', (out,err)
    assert activity.snapshot()['state'] == 'off'
finally:
    if process.poll() is None: process.kill();process.wait(timeout=3)
dead="from backend import windows_vision_activity as a; a.begin('frame',8)"
result=subprocess.run([sys.executable,'-B','-c',dead],capture_output=True,text=True,timeout=5,creationflags=subprocess.CREATE_NO_WINDOW)
assert result.returncode == 0, result.stderr
state=activity.snapshot()
assert state['active_count'] == 0 and state['error'] == 'OwnerExited', state
print('CANCEL_AND_DEATH_PASS')
''')
        self.assertIn("CANCEL_AND_DEATH_PASS", output)

    def test_corrupt_mapping_resets_and_reader_never_waits_for_mutex(self):
        output = self.run_probe('''
activity.snapshot()
channel=activity._get_channel()
channel.memory[:8]=b'bad data'
assert activity.snapshot()['state'] == 'off'
lease=activity.begin('frame',8)
import threading
locked=threading.Event();release=threading.Event()
def hold():
    assert channel.kernel.WaitForSingleObject(channel.mutex,50) == 0
    locked.set();release.wait(3)
    channel.kernel.ReleaseMutex(channel.mutex)
thread=threading.Thread(target=hold);thread.start();assert locked.wait(2)
try:
    began=time.monotonic();state=activity.snapshot();elapsed=time.monotonic()-began
    assert state['state'] == 'capturing', state
    assert elapsed < 0.2, elapsed
    began=time.monotonic()
    try: activity.begin('frame',8)
    except RuntimeError: pass
    else: raise AssertionError('writer acquired a held mutex')
    assert time.monotonic()-began < 0.2
finally:
    release.set();thread.join(3)
activity.finish(lease,{'frame_count':1})
assert activity.snapshot()['state'] == 'observed'
print('CORRUPTION_AND_CONTENTION_PASS')
''')
        self.assertIn("CORRUPTION_AND_CONTENTION_PASS", output)


if __name__ == "__main__":
    unittest.main()
