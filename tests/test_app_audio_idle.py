"""Silent loopback packets should not keep the FFT/spectrum worker active."""
from __future__ import annotations

import ctypes
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from backend.app_audio import AppAudio
from backend.media_spectrum import PcmSpectrum


class LoopbackFixture:
    def __init__(self, *, helper=False):
        self.helper = helper
        self.main = "silence"
        self.child = "silence"
        self.gains = []

    def gga_state(self, handle):
        return 3

    def gga_read(self, handle, buffer, capacity, sequence):
        mode = self.child if handle == "child" else self.main
        if mode == "none":
            return 0
        samples = np.ctypeslib.as_array(buffer, shape=(capacity * 2,)).reshape(capacity, 2)
        if mode == "silence":
            samples.fill(0)
        else:
            frequency = 440 if mode == "bass" else 6000
            tone = (.01 * np.sin(2 * np.pi * frequency * np.arange(capacity) / 48000)).astype(np.float32)
            samples[:, 0] = tone
            samples[:, 1] = tone
        return capacity

    def gga_renderers(self, handle, renderers, capacity):
        if self.helper:
            renderers[0] = 77
        return int(self.helper)

    def gga_capture_start(self, pid):
        return "child"

    def gga_gain(self, handle, value):
        self.gains.append(value)


def make_bus(*, helper=False):
    # No native DLL/session, preferences, user files or actual audio device.
    bus = AppAudio.__new__(AppAudio)
    bus.volume = 100
    bus.library = LoopbackFixture(helper=helper)
    bus.handle = "main"
    bus.process_id = 1
    bus._captures = {}
    bus._capture_scan_at = 0.0
    bus._samples = np.zeros((PcmSpectrum.FRAMES, 2), dtype=np.float32)
    bus._sequence = ctypes.c_uint64(0)
    bus._spectrum = PcmSpectrum()
    bus._pcm_at = 0.0
    bus._status_at = 0.0
    bus._cached = {}
    return bus


class AppAudioIdleTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.clock = patch("backend.app_audio.time.monotonic", side_effect=lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def status(self, bus, *, seconds=.02):
        self.now += seconds
        return bus.status()

    def test_continuous_digital_silence_has_no_fft_or_spectrum(self):
        bus = make_bus()
        with patch.object(bus._spectrum, "_analyze", wraps=bus._spectrum._analyze) as analyze, \
             patch.object(bus._spectrum, "reset", wraps=bus._spectrum.reset) as reset:
            for _ in range(10):
                result = self.status(bus)
                self.assertFalse(result["active"])
                self.assertEqual(result["spectrum"], [])
                self.assertTrue(result["available"])
                self.assertTrue(result["meter_available"])
            self.assertEqual(analyze.call_count, 0)
            self.assertEqual(reset.call_count, 0)

    def test_silence_clears_previous_audio_once_and_new_audio_recovers(self):
        bus = make_bus()
        bus.library.main = "bass"
        result = self.status(bus)
        self.assertTrue(result["active"])
        self.assertLess(np.argmax(result["spectrum"]), 65)
        bus.library.main = "silence"
        with patch.object(bus._spectrum, "_analyze", wraps=bus._spectrum._analyze) as analyze, \
             patch.object(bus._spectrum, "reset", wraps=bus._spectrum.reset) as reset:
            for _ in range(10):
                result = self.status(bus)
                self.assertFalse(result["active"])
                self.assertEqual(result["spectrum"], [])
            self.assertEqual(analyze.call_count, 0)
            self.assertEqual(reset.call_count, 1)
        bus.library.main = "treble"
        result = self.status(bus)
        self.assertTrue(result["active"])
        self.assertGreater(np.argmax(result["spectrum"]), 90)

    def test_silent_helpers_skip_fft_and_tone_helpers_still_contribute(self):
        bus = make_bus(helper=True)
        result = self.status(bus)
        capture = bus._captures[77]
        with patch.object(capture["spectrum"], "_analyze", wraps=capture["spectrum"]._analyze) as analyze:
            for _ in range(10):
                result = self.status(bus)
                self.assertFalse(result["active"])
            self.assertEqual(analyze.call_count, 0)
            bus.library.child = "bass"
            result = self.status(bus)
            self.assertTrue(result["active"])
            self.assertLess(np.argmax(result["spectrum"]), 65)
            self.assertEqual(analyze.call_count, 1)
        bus.library.child = "silence"
        with patch.object(capture["spectrum"], "reset", wraps=capture["spectrum"].reset) as reset:
            for _ in range(10):
                result = self.status(bus)
                self.assertFalse(result["active"])
                self.assertEqual(result["spectrum"], [])
            self.assertEqual(reset.call_count, 1)

    def test_no_new_frames_retain_recent_audio_then_expire(self):
        bus = make_bus()
        bus.library.main = "bass"
        self.assertTrue(self.status(bus)["active"])
        bus.library.main = "none"
        self.assertTrue(self.status(bus, seconds=.1)["active"])
        result = self.status(bus, seconds=.2)
        self.assertFalse(result["active"])
        self.assertEqual(result["spectrum"], [])

    def test_gain_control_keeps_working_during_silence_and_real_audio(self):
        bus = make_bus()
        result = bus.set_volume(37, persist=False)
        self.assertEqual(result["volume"], 37)
        self.assertFalse(result["active"])
        self.assertEqual(bus.library.gains, [.37])
        bus.library.main = "bass"
        self.assertTrue(self.status(bus)["active"])
        result = bus.set_volume(0, persist=False)
        self.assertFalse(result["active"])
        self.assertEqual(result["spectrum"], [])
        self.assertEqual(bus.library.gains[-1], 0)
        result = bus.set_volume(100, persist=False)
        self.assertTrue(result["active"])
        self.assertEqual(bus.library.gains[-1], 1)


if __name__ == "__main__":
    unittest.main()
