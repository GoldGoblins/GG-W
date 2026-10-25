"""One application master volume and a real spectrum of its mixed audio.

Windows capture is restricted to this process tree. PCM stays in a bounded
RAM window; the only persistent data is the user's volume preference.
"""
from __future__ import annotations

import atexit
import ctypes
import json
import os
from pathlib import Path
import time

import numpy as np

from backend.application_paths import PROJECT_ROOT, STATE_ROOT
from backend.media_spectrum import PcmSpectrum
from backend.platform_support import native_directory


class AppAudio:
    def __init__(self, *, preference_path=None, process_id=None):
        self.preference_path = Path(preference_path or STATE_ROOT / "audio/master.json")
        try:
            self.volume = self._clamp(json.loads(self.preference_path.read_text(encoding="utf-8"))["volume"])
        except (OSError, ValueError, KeyError, TypeError):
            self.volume = 100
        self.library = None
        self.handle = None
        self.process_id = process_id or os.getpid()
        self._captures = {}
        self._capture_scan_at = 0.0
        self._samples = np.zeros((PcmSpectrum.FRAMES, 2), dtype=np.float32)
        self._sequence = ctypes.c_uint64(0)
        self._spectrum = PcmSpectrum()
        self._pcm_at = 0.0
        self._status_at = 0.0
        self._cached = {}
        if os.name != "nt":
            return
        try:
            library = ctypes.CDLL(str(native_directory(PROJECT_ROOT) / "gg_app_audio.dll"))
            library.gga_abi_version.restype = ctypes.c_uint
            if library.gga_abi_version() != 1:
                return
            library.gga_start.argtypes = [ctypes.c_uint, ctypes.c_float]
            library.gga_start.restype = ctypes.c_void_p
            library.gga_capture_start.argtypes = [ctypes.c_uint]
            library.gga_capture_start.restype = ctypes.c_void_p
            library.gga_renderers.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint), ctypes.c_uint]
            library.gga_renderers.restype = ctypes.c_uint
            library.gga_stop.argtypes = [ctypes.c_void_p]
            library.gga_stop.restype = None
            library.gga_gain.argtypes = [ctypes.c_void_p, ctypes.c_float]
            library.gga_gain.restype = None
            library.gga_observed_gain.argtypes = [ctypes.c_void_p]
            library.gga_observed_gain.restype = ctypes.c_float
            for name in ("gga_state", "gga_error", "gga_sessions"):
                method = getattr(library, name)
                method.argtypes = [ctypes.c_void_p]
                method.restype = ctypes.c_uint
            library.gga_read.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_float),
                                         ctypes.c_uint, ctypes.POINTER(ctypes.c_uint64)]
            library.gga_read.restype = ctypes.c_uint
            self.handle = library.gga_start(self.process_id, self.volume / 100)
            if self.handle:
                self.library = library
        except (OSError, AttributeError):
            pass

    @staticmethod
    def _clamp(value):
        return max(0, min(100, int(value)))

    def set_volume(self, volume, *, persist=True):
        self.volume = self._clamp(volume)
        if self.handle:
            self.library.gga_gain(self.handle, self.volume / 100)
        self._status_at = 0
        if persist:
            self.preference_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.preference_path.with_name("master.pending")
            temporary.write_text(json.dumps({"volume": self.volume}) + "\n", encoding="utf-8")
            os.replace(temporary, self.preference_path)
        return self.status()

    @staticmethod
    def _accept_pcm(spectrum, samples, previous_at, now):
        # Windows process loopback can keep delivering silent packets while
        # no owned application is audible. Do not run an FFT for those packets.
        if np.any(samples):
            spectrum.push(samples, 48000)
            return now
        if previous_at:
            spectrum.reset()
        return 0.0

    def status(self):
        now = time.monotonic()
        if self._cached and now - self._status_at < .016:
            return self._cached
        state = self.library.gga_state(self.handle) if self.handle else 0
        if self.handle:
            frames = self.library.gga_read(self.handle,
                self._samples.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                PcmSpectrum.FRAMES, ctypes.byref(self._sequence))
            if frames:
                self._pcm_at = self._accept_pcm(
                    self._spectrum, self._samples[:frames], self._pcm_at, now)
        fresh = now - self._pcm_at < .25 and bool(state & 2)
        # Process loopback already includes the Windows session gain. Applying
        # the master a second time would under-report the audible level.
        levels = self._spectrum.levels() if fresh and self.volume else []
        if self.handle:
            # Some Windows audio graphs expose helper-process audio only on
            # the renderer's own loopback stream. Enumerate owned sessions and
            # analyze those bounded streams too; never capture a device mix.
            if now - self._capture_scan_at >= .4:
                self._capture_scan_at = now
                renderers = (ctypes.c_uint * 16)()
                size = self.library.gga_renderers(self.handle, renderers, 16)
                wanted = set(renderers[:size]) - {self.process_id}
                for pid in set(self._captures) - wanted:
                    self.library.gga_stop(self._captures.pop(pid)["handle"])
                for pid in wanted - set(self._captures):
                    handle = self.library.gga_capture_start(pid)
                    if handle:
                        self._captures[pid] = dict(handle=handle, sequence=ctypes.c_uint64(0),
                            samples=np.zeros_like(self._samples), spectrum=PcmSpectrum(), at=0.0)
            for capture in self._captures.values():
                frames = self.library.gga_read(capture["handle"],
                    capture["samples"].ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                    PcmSpectrum.FRAMES, ctypes.byref(capture["sequence"]))
                if frames:
                    capture["at"] = self._accept_pcm(
                        capture["spectrum"], capture["samples"][:frames], capture["at"], now)
                if self.volume and now - capture["at"] < .25:
                    own = capture["spectrum"].levels()
                    # Peak-per-band union avoids double-counting audio already
                    # present in the main process-tree loopback window.
                    levels = np.maximum(levels, own).tolist() if levels else own
        active = bool(levels and max(levels) > .002)
        self._cached = {"available": bool(state & 1), "meter_available": bool(state & 2),
                        "volume": self.volume, "active": active, "spectrum": levels}
        self._status_at = now
        return self._cached

    def close(self):
        for capture in self._captures.values():
            self.library.gga_stop(capture["handle"])
        self._captures.clear()
        if self.handle:
            handle, self.handle = self.handle, None
            self.library.gga_stop(handle)
        self._spectrum.reset()
        self._cached = {}


_bus = None


def service():
    global _bus
    if _bus is None:
        _bus = AppAudio()
        atexit.register(_bus.close)
        from PySide6.QtCore import QCoreApplication
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(_bus.close)
    return _bus
