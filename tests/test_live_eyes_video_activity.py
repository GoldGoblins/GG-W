"""Video progress/cancellation uses fake media pipes; never fetches or captures."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from backend import live_vision as vision
from backend import windows_vision_activity as activity


class FakeDecoder:
    def __init__(self, *, blocked=False):
        from PIL import Image
        stream = io.BytesIO()
        Image.new("RGB", (2, 2), "green").save(stream, "JPEG")
        self.stdout = io.BytesIO(stream.getvalue() * 2)
        self.stderr = io.BytesIO(b"[showinfo] n: 0 pts_time:0\n[showinfo] n: 1 pts_time:0.04\n")
        self.returncode = None
        self.kills = 0
        self.reading = threading.Event()
        self.released = threading.Event()
        if blocked:
            self.stdout = self.BlockedPipe(self)

    class BlockedPipe:
        def __init__(self, owner):
            self.owner, self.closed = owner, False

        def read(self, size):
            self.owner.reading.set()
            if not self.owner.released.wait(2):
                raise AssertionError("Cancellation did not release the decoder pipe")
            return b""

        def close(self):
            self.closed = True

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def kill(self):
        self.kills += 1
        self.returncode = -9
        self.released.set()


class VideoObservationActivityTests(unittest.TestCase):
    source = str(Path(__file__).resolve())
    metadata = json.dumps({"url": "https://media.example.test/stream", "title": "Test clip",
                           "duration": 10, "http_headers": {}}).encode()

    def decode(self, process, **kwargs):
        with patch.object(vision.subprocess, "Popen", return_value=process), \
             patch.object(vision, "find_executable", return_value="fake-media-tool"):
            return vision.video_observation(self.source, **kwargs)

    def test_progress_reports_only_actual_decoded_count_and_receive_time(self):
        process = FakeDecoder()
        progress = []
        result = self.decode(process, start=3, on_frame=lambda **values: progress.append(values),
                             cancelled=lambda: False)
        self.assertEqual([row["frames"] for row in progress], [1, 2])
        self.assertTrue(all(set(row) == {"frames", "last_frame_at", "received_fps"} for row in progress))
        self.assertTrue(all(row["received_fps"] == 0 for row in progress))
        self.assertLessEqual(progress[0]["last_frame_at"], progress[1]["last_frame_at"])
        self.assertEqual(result["frame_count"], 2)
        self.assertEqual([row["pts_seconds"] for row in result["frames"]], [3, 3.04])
        self.assertEqual(process.kills, 0)
        self.assertTrue(process.stdout.closed and process.stderr.closed)

    def test_default_url_resolver_keeps_existing_subprocess_path(self):
        process = FakeDecoder()
        with patch.object(vision.subprocess, "run", return_value=SimpleNamespace(
                returncode=0, stdout=self.metadata)) as resolver, \
             patch("backend.platform_process.run_bounded") as bounded, \
             patch.object(vision.subprocess, "Popen", return_value=process), \
             patch.object(vision, "find_executable", return_value="fake-media-tool"):
            result = vision.video_observation("https://example.test/video")
        self.assertEqual(result["frame_count"], 2)
        self.assertEqual(resolver.call_args.kwargs["timeout"], 60)
        self.assertEqual(resolver.call_args.kwargs["stderr"], subprocess.DEVNULL)
        bounded.assert_not_called()

    def test_cancellable_url_resolver_is_bounded_and_quiet(self):
        process = FakeDecoder()
        with patch.object(vision.subprocess, "run") as old_resolver, \
             patch("backend.platform_process.run_bounded", return_value=(
                 0, self.metadata, b"private ignored diagnostic", "NONE")) as resolver, \
             patch.object(vision.subprocess, "Popen", return_value=process), \
             patch.object(vision, "find_executable", return_value="fake-media-tool"):
            result = vision.video_observation("https://example.test/video", cancelled=lambda: False)
        self.assertEqual(result["frame_count"], 2)
        self.assertEqual(resolver.call_args.kwargs["timeout"], 60)
        self.assertEqual(resolver.call_args.kwargs["max_output_bytes"], 4 * 1024**2)
        self.assertFalse(resolver.call_args.kwargs["cancelled"]())
        old_resolver.assert_not_called()

    def test_early_cancel_and_broken_cancel_channel_never_start_media_tools(self):
        def broken():
            raise RuntimeError("private channel input")
        for callback in (lambda: True, broken):
            with self.subTest(callback=callback), \
                 patch.object(vision.subprocess, "Popen") as decoder, \
                 patch.object(vision.subprocess, "run") as resolver:
                with self.assertRaisesRegex(RuntimeError, "CANCELLED") as failure:
                    vision.video_observation("https://example.test/private", cancelled=callback)
                self.assertNotIn("private", str(failure.exception))
                decoder.assert_not_called()
                resolver.assert_not_called()

    def test_resolver_cancel_timeout_output_limit_and_failure_skip_decoder(self):
        for code, trigger in [(0, "CANCELLED"), (-1, "TIMEOUT"),
                              (-1, "OUTPUT_LIMIT"), (1, "NONE")]:
            with self.subTest(trigger=trigger), \
                 patch("backend.platform_process.run_bounded", return_value=(
                     code, b"", b"private URL", trigger)), \
                 patch.object(vision.subprocess, "Popen") as decoder, \
                 patch.object(vision, "find_executable", return_value="fake-media-tool"):
                with self.assertRaises(RuntimeError) as failure:
                    vision.video_observation("https://example.test/private", cancelled=lambda: False)
                if trigger == "CANCELLED":
                    self.assertIn("CANCELLED", str(failure.exception))
                self.assertNotIn("private", str(failure.exception))
                decoder.assert_not_called()

    def test_cancel_watcher_unblocks_only_its_decoder_and_fails_closed(self):
        for broken in (False, True):
            with self.subTest(broken=broken):
                process = FakeDecoder(blocked=True)
                def callback():
                    if process.reading.is_set() and broken:
                        raise RuntimeError("private cancellation channel")
                    return process.reading.is_set()
                with self.assertRaisesRegex(RuntimeError, "CANCELLED") as failure:
                    self.decode(process, cancelled=callback)
                self.assertNotIn("private", str(failure.exception))
                self.assertEqual(process.kills, 1)
                self.assertTrue(process.stdout.closed and process.stderr.closed)

    def test_progress_failure_cleans_up_decoder(self):
        process = FakeDecoder()
        def progress(**values):
            raise RuntimeError("Progress channel unavailable")
        with self.assertRaisesRegex(RuntimeError, "Progress channel"):
            self.decode(process, on_frame=progress, cancelled=lambda: False)
        self.assertEqual(process.kills, 1)
        self.assertTrue(process.stdout.closed and process.stderr.closed)

    def test_stop_after_decoding_does_not_deliver_late_success(self):
        process = FakeDecoder()
        with self.assertRaisesRegex(RuntimeError, "CANCELLED"):
            self.decode(process, cancelled=lambda: process.returncode == 0)
        self.assertTrue(process.stdout.closed and process.stderr.closed)


class VideoCliActivityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        loader = importlib.machinery.SourceFileLoader("gg_eyes_video_activity_test", str(PROJECT / "gg-eyes"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        cls.cli = importlib.util.module_from_spec(spec)
        with patch("backend.platform_support.configure_stdio"):
            loader.exec_module(cls.cli)

    @unittest.skipUnless(os.name == "nt", "Windows video activity wrapper")
    def test_windows_video_wrapper_publishes_actual_progress_and_short_recent_state(self):
        channel = activity._MemoryChannel()
        now = [100.0]
        channel.store.clock = lambda: now[0]
        parts = [{"type": "text", "text": "metadata"}]
        def decode(source, **options):
            state = activity.snapshot()
            self.assertEqual((state["state"], state["observation_kind"]), ("capturing", "video"))
            self.assertFalse(options["cancelled"]())
            options["on_frame"](frames=2, last_frame_at=now[0], received_fps=0)
            self.assertEqual(activity.snapshot()["frame_count"], 2)
            return {"frame_count": 2, "source": source}
        with patch.object(activity, "_get_channel", return_value=channel), \
             patch.object(self.cli.vision, "video_observation", side_effect=decode), \
             patch.object(self.cli.vision, "image_parts", return_value=parts):
            self.assertEqual(self.cli.perform("video", {"source": "https://example.test/video"}), parts)
            state = activity.snapshot()
            self.assertEqual((state["state"], state["last_observation_frames"]), ("observed", 2))
            self.assertEqual(state["last_observation_kind"], "video")
            self.assertNotIn("example.test", json.dumps(channel.store.data))
            now[0] += 3
            self.assertEqual(activity.snapshot()["state"], "off")

    @unittest.skipUnless(os.name == "nt", "Windows video activity wrapper")
    def test_windows_video_wrapper_stop_suppresses_formatted_late_result(self):
        channel = activity._MemoryChannel()
        def decode(source, **options):
            activity.stop()
            self.assertTrue(options["cancelled"]())
            return {"frame_count": 2}
        with patch.object(activity, "_get_channel", return_value=channel), \
             patch.object(self.cli.vision, "video_observation", side_effect=decode), \
             patch.object(self.cli.vision, "image_parts", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "CANCELLED"):
                self.cli.perform("video", {"source": "https://example.test/video"})
            self.assertEqual(activity.snapshot()["state"], "off")

    def test_linux_video_wrapper_retains_default_decoder_options(self):
        with patch.object(self.cli, "os", SimpleNamespace(name="posix")), \
             patch.object(self.cli.vision, "video_observation", return_value={"frame_count": 2}) as decode, \
             patch.object(self.cli.vision, "image_parts", return_value=[]) as format_parts, \
             patch.object(activity, "begin") as begin:
            self.cli.perform("video", {"source": "test-source", "start": 3, "seconds": 1, "fps": 10})
        decode.assert_called_once_with("test-source", start=3, seconds=1, fps=10)
        format_parts.assert_called_once_with({"frame_count": 2}, sequence=True)
        begin.assert_not_called()


if __name__ == "__main__":
    unittest.main()
