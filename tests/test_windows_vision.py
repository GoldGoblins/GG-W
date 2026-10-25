"""Windows observations must remain bounded and independent of the app UI."""
from __future__ import annotations

import base64
import atexit
from contextlib import contextmanager
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from PIL import Image
from backend import windows_vision as vision
from backend import windows_vision_activity as activity


class WindowsVisionTests(unittest.TestCase):
    def setUp(self):
        if self._testMethodName not in {"test_helper_returns_and_exits_on_a_bounded_request",
                                       "test_real_stop_interrupts_only_the_owned_clip_worker"}:
            patcher = patch.object(activity, "_get_channel", return_value=activity._MemoryChannel())
            patcher.start()
            self.addCleanup(patcher.stop)

    @contextmanager
    def isolated_channel(self):
        with tempfile.TemporaryDirectory(prefix="gg-eyes-test-") as directory, \
             patch.dict(os.environ, GG_DESKTOP_STATE_ROOT=str(Path(directory)/"scope")), \
             patch.object(activity,"STATE_ROOT",Path(directory)/"scope"), \
             patch.object(activity,"_channel",None):
            try:
                yield
            finally:
                channel = activity._channel
                if channel is not None:
                    atexit.unregister(channel.close)
                    channel.close()

    def grab(self, *, bbox):
        x, y, right, bottom = bbox
        return Image.new("RGB", (right - x, bottom - y), "#198d51")

    def test_frame_is_decodable_and_region_maps_to_screen(self):
        result = vision.capture({"op": "frame", "region": [100, 50, 200, 120]},
                                grab=self.grab, screen_size=(640, 480))
        self.assertEqual(result["frame_count"], 1)
        self.assertEqual(result["source_position"], [100, 50])
        self.assertEqual(result["source_size"], [200, 120])
        self.assertFalse(result["retained_after_request"])
        frame = result["frames"][0]
        with Image.open(io.BytesIO(base64.b64decode(frame["jpeg"]))) as decoded:
            self.assertEqual(decoded.size, (200, 120))
        self.assertIsNone(frame["pts_seconds"])

    def test_clip_has_real_ordered_timestamps_and_bounded_previews(self):
        result = vision.capture({"op": "clip", "seconds": 0.16, "fps": 25},
                                grab=self.grab, screen_size=(1920, 1080))
        self.assertGreaterEqual(result["frame_count"], 3)
        self.assertLessEqual(result["frame_count"], 5)
        self.assertLessEqual(result["buffer_bytes"], result["buffer_limit_bytes"])
        self.assertGreater(result["coverage_seconds"], 0.07)
        frames = result["frames"]
        self.assertEqual([f["seq"] for f in frames], sorted(f["seq"] for f in frames))
        self.assertEqual([f["age_ms"] for f in frames], sorted((f["age_ms"] for f in frames), reverse=True))
        self.assertTrue(all(f["width"] <= 960 and f["height"] <= 540 for f in frames))

    def test_bad_requests_fail_before_capture(self):
        requests = [{"op": "shell"}, {"op": "clip", "seconds": 7},
                    {"op": "clip", "seconds": 0},
                    {"op": "clip", "fps": 60}, {"op": "clip", "seconds": float("nan")},
                    {"op": "frame", "age": 1}, {"op": "frame", "region": [-1, 0, 2, 2]},
                    {"op": "frame", "region": [1, 2, 0, 3]},
                    {"op": "frame", "region": [1, 2, 3.5, 4]},
                    {"op": "frame", "region": [630, 0, 20, 20]}]
        for command in requests:
            with self.subTest(command=command), patch.object(self, "grab") as grab:
                with self.assertRaises(ValueError):
                    vision.capture(command, grab=grab, screen_size=(640, 480))
                grab.assert_not_called()

    def test_capture_publishes_progress_and_honors_cancel_before_next_frame(self):
        progress = []
        with self.assertRaisesRegex(RuntimeError,"CANCELLED"):
            vision.capture({"op":"clip","seconds":.16,"fps":25}, grab=self.grab,
                screen_size=(640,480),on_frame=lambda **value:progress.append(value),
                cancelled=lambda:bool(progress))
        self.assertEqual(len(progress),1)
        self.assertEqual(progress[0]["frames"],1)
        self.assertLessEqual(progress[0]["last_frame_at"],time.monotonic())
        self.assertEqual(progress[0]["received_fps"],0)

    def test_no_image_files_are_written(self):
        with tempfile.TemporaryDirectory() as directory:
            original = Path.cwd()
            try:
                os.chdir(directory)
                vision.capture({"op": "frame"}, grab=self.grab, screen_size=(640, 480))
                self.assertEqual(list(Path(directory).iterdir()), [])
            finally:
                os.chdir(original)

    def test_ui_status_and_start_never_spawn_capture_or_claim_live_frames(self):
        with patch("backend.platform_process.run_bounded") as run:
            self.assertEqual(vision.request("status")["state"], "off")
            self.assertIsNone(vision.request("status")["frame_age_ms"])
            self.assertEqual(vision.request("start")["state"], "ready")
            self.assertEqual(vision.request("stop")["buffer_bytes"], 0)
            run.assert_not_called()

    def test_driver_timeout_is_reported_through_bounded_runner(self):
        with patch("backend.platform_process.run_bounded", return_value=(-1, b"", b"", "TIMEOUT")) as run:
            with self.assertRaisesRegex(RuntimeError, "TIMEOUT"):
                vision.request("clip", seconds=2, timeout=4)
            self.assertEqual(run.call_args.kwargs["timeout"], 4)
            self.assertGreater(run.call_args.kwargs["max_output_bytes"], 0)

    def test_capture_deadline_cannot_be_extended_beyond_eight_seconds(self):
        answer = json.dumps({"ok": True, "result": {"frame_count": 1}}).encode()
        with patch("backend.platform_process.run_bounded", return_value=(0, answer, b"", "NONE")) as run:
            vision.request("frame", timeout=1000)
            self.assertEqual(run.call_args.kwargs["timeout"], 8)
        with self.assertRaises(ValueError):
            vision.request("frame", timeout=float("inf"))

    def test_request_publishes_actual_activity_then_completed_observation(self):
        packet = json.dumps({"ok": True, "result": {"frame_count": 1, "received_fps": 0}}).encode()
        def observe(*args, **kwargs):
            state = vision.status()
            self.assertEqual(state["state"], "capturing")
            self.assertEqual(state["active_count"], 1)
            self.assertEqual(state["received_fps"], 0)
            self.assertFalse(kwargs["cancelled"]())
            self.assertEqual(len(args[0]), 7)  # command + private activity lease
            return 0, packet, b"", "NONE"
        with patch("backend.platform_process.run_bounded", side_effect=observe):
            vision.request("frame")
        state = vision.status()
        self.assertEqual(state["state"], "observed")
        self.assertEqual(state["last_observation_frames"], 1)
        self.assertEqual(state["received_fps"], 0)
        self.assertIsNone(state["frame_age_ms"])
        self.assertEqual(vision.request("stop")["state"], "off")

    def test_stop_cancels_runner_and_suppresses_late_result(self):
        def stopped(*args, **kwargs):
            vision.request("stop")
            self.assertTrue(kwargs["cancelled"]())
            return 0, json.dumps({"ok": True, "result": {"frame_count": 1}}).encode(), b"", "NONE"
        with patch("backend.platform_process.run_bounded", side_effect=stopped):
            with self.assertRaisesRegex(RuntimeError, "CANCELLED"):
                vision.request("frame")
        self.assertEqual(vision.status()["state"], "off")

    def test_every_runner_failure_clears_capture_without_claiming_delivery(self):
        cases = [(-1,b"",b"","TIMEOUT"), (1,b"",b"","NONE"),
                 (0,b"not-json",b"","NONE"), (0,b'{"ok":false}',b"","NONE"),
                 (0,b'{"ok":true,"result":[]}',b"","NONE")]
        for answer in cases:
            with self.subTest(answer=answer), patch("backend.platform_process.run_bounded", return_value=answer):
                with self.assertRaises((RuntimeError, ValueError)):
                    vision.request("frame")
                state = vision.status()
                self.assertEqual(state["state"], "error")
                self.assertEqual(state["active_count"], 0)
                self.assertEqual(state["last_observation_frames"], 0)
        with patch("backend.platform_process.run_bounded", side_effect=OSError("private driver path")):
            with self.assertRaises(OSError):
                vision.request("frame")
        self.assertNotIn("private driver", json.dumps(vision.status()))

    def test_ui_status_errors_never_capture_or_break_the_desktop(self):
        with patch.object(activity,"snapshot",side_effect=OSError("private channel")), \
             patch("backend.platform_process.run_bounded") as runner:
            state = vision.status()
            self.assertEqual(state["state"], "error")
            self.assertEqual(state["received_fps"], 0)
            self.assertNotIn("private channel", json.dumps(state))
            runner.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Windows subprocess integration")
    def test_helper_returns_and_exits_on_a_bounded_request(self):
        with self.isolated_channel():
            result = vision.request("frame", region=[0, 0, 32, 32], timeout=5)
            self.assertEqual(vision.status()["state"], "observed")
        self.assertEqual(result["provider"], "windows-gdi")
        self.assertEqual(result["frame_count"], 1)
        self.assertEqual(result["source_size"], [32, 32])

    @unittest.skipUnless(os.name == "nt", "Windows subprocess integration")
    def test_real_stop_interrupts_only_the_owned_clip_worker(self):
        with self.isolated_channel():
            activity.snapshot()
            failures = []
            def observe():
                try:
                    vision.request("clip", seconds=6, region=[0, 0, 32, 32])
                except RuntimeError as exc:
                    failures.append(str(exc))
            worker = threading.Thread(target=observe)
            worker.start()
            try:
                deadline = time.monotonic()+4
                while vision.status().get("frame_count",0) == 0 and worker.is_alive() and time.monotonic()<deadline:
                    time.sleep(.02)
                self.assertGreater(vision.status().get("frame_count",0),0)
                began = time.monotonic()
                vision.request("stop")
                worker.join(2)
                self.assertFalse(worker.is_alive(), "Owned capture worker ignored stop")
                self.assertLess(time.monotonic()-began,2)
                self.assertEqual(vision.status()["state"],"off")
                self.assertTrue(failures and "CANCELLED" in failures[0],failures)
            finally:
                activity.stop()
                worker.join(9)


if __name__ == "__main__":
    unittest.main()
