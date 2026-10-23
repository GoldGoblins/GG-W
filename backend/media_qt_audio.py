"""In-process desktop audio; no Unix sockets or POSIX pause signals."""
from __future__ import annotations

import time

import numpy as np
from PySide6.QtCore import QCoreApplication, QThread, QUrl
from PySide6.QtMultimedia import QAudioBufferOutput, QAudioFormat, QAudioOutput, QMediaPlayer

from backend.media_spectrum import PcmSpectrum
from backend.media_reconnect import RadioReconnect

_player = None
_output = None
_buffer_output = None
_spectrum = PcmSpectrum()
_buffer_at = 0.0
_reconnect = None


def _clear_spectrum():
    global _buffer_at
    _buffer_at = 0.0
    _spectrum.reset()


def _receive_buffer(buffer):
    global _buffer_at
    if not buffer.isValid() or not buffer.frameCount():
        return
    fmt = buffer.format()
    formats = {
        QAudioFormat.UInt8: (np.uint8, 128.0, 128.0),
        QAudioFormat.Int16: (np.int16, 0.0, 32768.0),
        QAudioFormat.Int32: (np.int32, 0.0, 2147483648.0),
        QAudioFormat.Float: (np.float32, 0.0, 1.0),
    }
    if fmt.sampleFormat() not in formats or not 1 <= fmt.channelCount() <= 8:
        return
    dtype, offset, scale = formats[fmt.sampleFormat()]
    # Copy only the latest window while the borrowed Qt buffer is valid.
    frames = min(buffer.frameCount(), PcmSpectrum.FRAMES)
    count = frames * fmt.channelCount()
    size = np.dtype(dtype).itemsize
    raw = memoryview(buffer.constData())
    start = (buffer.frameCount() - frames) * fmt.channelCount() * size
    samples = np.frombuffer(raw, dtype=dtype, count=count, offset=start).astype(np.float32)
    samples = ((samples - offset) / scale).reshape(frames, fmt.channelCount())
    _spectrum.push(samples, fmt.sampleRate())
    _buffer_at = time.monotonic()
    if _reconnect is not None:
        _reconnect.audio_received()


def _ensure():
    global _player, _output, _buffer_output, _reconnect
    app = QCoreApplication.instance()
    if app is None or QThread.currentThread() != app.thread():
        raise RuntimeError('MEDIA_REQUIRES_DESKTOP_THREAD')
    if _player is None:
        _output = QAudioOutput(app)
        _player = QMediaPlayer(app)
        _player.setAudioOutput(_output)
        _buffer_output = QAudioBufferOutput(_player)
        _buffer_output.audioBufferReceived.connect(_receive_buffer)
        _player.setAudioBufferOutput(_buffer_output)
        _reconnect = RadioReconnect(_player, before_restart=_clear_spectrum)
        app.aboutToQuit.connect(stop)
    return _player


def play(source, volume=70, *, live=False):
    player = _ensure()
    _reconnect.stop()
    player.stop()
    _clear_spectrum()
    url = QUrl(source) if str(source).startswith(('https://', 'http://')) else QUrl.fromLocalFile(str(source))
    _output.setVolume(max(0, min(100, int(volume))) / 100)
    player.setSource(url)
    _reconnect.start(url, live=live)
    player.play()
    if _reconnect.enabled and _reconnect._failed():
        _reconnect._schedule()


def stop():
    was_live = _reconnect is not None and _reconnect.live
    if _reconnect is not None:
        _reconnect.stop()
    if _player is not None:
        _player.stop()
        if was_live:
            _player.setSource(QUrl())
    _clear_spectrum()


def pause(paused):
    player = _ensure()
    _reconnect.pause(paused)
    player.pause() if paused else player.play()


def seek(seconds):
    _clear_spectrum()
    _ensure().setPosition(max(0, int(seconds * 1000)))


def volume(value):
    _ensure()
    _output.setVolume(max(0, min(100, int(value))) / 100)


def status():
    if _player is None:
        return {'playing': False, 'buffering': False, 'position': 0, 'duration': 0,
                'error': '', 'spectrum': []}
    failed = _player.error() != QMediaPlayer.NoError
    reconnecting = _reconnect is not None and _reconnect.recovering
    fresh = time.monotonic() - _buffer_at < .5
    loading = _player.mediaStatus() in (QMediaPlayer.LoadingMedia, QMediaPlayer.BufferingMedia, QMediaPlayer.StalledMedia)
    playing = not failed and not reconnecting and _player.playbackState() == QMediaPlayer.PlayingState and (not loading or fresh)
    gain = 0 if _output.isMuted() else _output.volume()
    retry_error = _reconnect.last_error if _reconnect is not None and _reconnect.exhausted else ''
    return {'playing': playing, 'buffering': reconnecting or (loading and not playing and not failed),
            'reconnecting': reconnecting,
            'retry_attempt': _reconnect.attempts if _reconnect is not None else 0,
            'retry_limit': len(RadioReconnect.DELAYS_MS),
            'position': _player.position() / 1000, 'duration': _player.duration() / 1000,
            'error': _player.errorString() if failed else retry_error,
            'spectrum': _spectrum.levels(gain) if playing and fresh else []}
