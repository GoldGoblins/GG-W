"""Windows observations must remain bounded and independent of the app UI."""
from __future__ import annotations

import base64
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from PIL import Image
from backend import windows_vision as vision


class WindowsVisionTests(unittest.TestCase):
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

    @unittest.skipUnless(os.name == "nt", "Windows subprocess integration")
    def test_helper_returns_and_exits_on_a_bounded_request(self):
        result = vision.request("frame", region=[0, 0, 32, 32], timeout=5)
        self.assertEqual(result["provider"], "windows-gdi")
        self.assertEqual(result["frame_count"], 1)
        self.assertEqual(result["source_size"], [32, 32])


if __name__ == "__main__":
    unittest.main()
