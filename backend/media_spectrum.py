"""Bounded frequency analysis of the PCM frames decoded for media playback."""
from __future__ import annotations

import numpy as np

from backend.media_contract import SPECTRUM_BARS


class PcmSpectrum:
    FRAMES = 4096

    def __init__(self):
        self.reset()
        self._window = np.hanning(self.FRAMES).astype(np.float32)

    def reset(self):
        self._samples = np.empty((0, 1), dtype=np.float32)
        self._rate = 0
        self._amplitudes = np.zeros(SPECTRUM_BARS)
        self._dirty = False

    def push(self, samples, rate):
        """Keep at most one FFT window; callers supply normalized frame/channel PCM."""
        samples = np.asarray(samples, dtype=np.float32)
        if (samples.ndim != 2 or not 1 <= samples.shape[1] <= 8
                or not 1000 <= rate <= 768000):
            raise ValueError('INVALID_AUDIO_FORMAT')
        if not len(samples):
            return
        if rate != self._rate or samples.shape[1] != self._samples.shape[1]:
            self.reset()
            self._rate = rate
            self._samples = np.empty((0, samples.shape[1]), dtype=np.float32)
        self._samples = np.concatenate((self._samples, samples[-self.FRAMES:]))[-self.FRAMES:]
        self._dirty = True

    def _analyze(self):
        frame = np.zeros((self.FRAMES, self._samples.shape[1]), dtype=np.float32)
        frame[-len(self._samples):] = self._samples
        np.nan_to_num(frame, copy=False, nan=0, posinf=0, neginf=0)
        np.clip(frame, -1, 1, out=frame)
        frame -= frame.mean(axis=0)
        transform = np.fft.rfft(frame * self._window[:, None], axis=0)
        # Channel powers preserve audible stereo even when L and R have
        # opposite phase; averaging their PCM would incorrectly show silence.
        amplitudes = np.sqrt(np.mean(np.abs(transform) ** 2, axis=1)) * (2 / self._window.sum())
        edges = np.geomspace(30, min(20000, self._rate / 2), SPECTRUM_BARS + 1)
        bins = np.clip(np.rint(edges * self.FRAMES / self._rate).astype(int), 1, len(amplitudes) - 1)
        self._amplitudes = np.array([
            amplitudes[left:max(left + 1, right)].max()
            for left, right in zip(bins[:-1], bins[1:])
        ])
        self._dirty = False

    def levels(self, gain=1.0):
        """Fixed -70 dB floor: quiet passages stay quiet and silence stays dark."""
        if self._dirty:
            self._analyze()
        decibels = 20 * np.log10(np.maximum(self._amplitudes * max(0, gain), 1e-7))
        return np.clip((decibels + 70) / 70, 0, 1).tolist()
