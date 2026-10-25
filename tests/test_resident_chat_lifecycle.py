"""Idle model cleanup must preserve the desktop's shared live services."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[1]


class ResidentChatLifecycleTests(unittest.TestCase):
    def run_lifecycle(self, scenario: str) -> None:
        with tempfile.TemporaryDirectory(prefix="gg-resident-lifecycle-") as temporary:
            env = os.environ.copy()
            env.update(
                QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
                PYTHONDONTWRITEBYTECODE="1",
                GG_DATA_HOME=str(Path(temporary) / "data"),
                GG_USER_HOME=str(Path(temporary) / "user"),
                GG_DESKTOP_STATE_ROOT=str(Path(temporary) / "state"),
                GG_DESKTOP_DATA_ROOT=str(Path(temporary) / "data"),
                GG_USER_CODEX_HOME=str(Path(temporary) / "codex"),
                CODEX_HOME=str(Path(temporary) / "codex"),
            )
            code = r'''
import codecs, sys
from unittest.mock import patch
from PySide6.QtCore import QEventLoop, QObject, QProcess, QTimer
from PySide6.QtWidgets import QApplication
from backend import resident_chat_qt
from backend.resident_chat_qt import ResidentChatTransport
from shiboken6 import isValid

app = QApplication([])

class SamplerFixture(QObject):
    def __init__(self, parent):
        super().__init__(parent)
        self.samples = 0
        self.timer = QTimer(self)
        self.timer.setInterval(5)
        self.timer.timeout.connect(self.sample)
        self.timer.start()
    def sample(self):
        self.samples += 1
    def close(self):
        self.timer.stop()

class SurfaceFixture(QObject):
    def __init__(self, parent):
        super().__init__(parent)
        self.ticks = 0
        self.shutdown_calls = 0
        self.fail_shutdown = False
        self.timer = QTimer(self)
        self.timer.setInterval(5)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.sampler = SamplerFixture(self)
    def tick(self):
        self.ticks += 1
    def shutdown(self):
        self.shutdown_calls += 1
        self.timer.stop()
        self.sampler.close()
        if self.fail_shutdown:
            raise RuntimeError('fixture surface cleanup failed')

class GrokFixture:
    def __init__(self):
        self.active = False
        self.idle_calls = 0
        self.shutdown_calls = 0
        self.fail_shutdown = False
        self.refuse_idle = False
    def busy(self):
        return self.active
    def shutdown_idle(self):
        self.idle_calls += 1
        return not (self.active or self.refuse_idle)
    def shutdown(self):
        self.shutdown_calls += 1
        if self.fail_shutdown:
            raise RuntimeError('fixture grok cleanup failed')

class TransportFixture(ResidentChatTransport):
    def __init__(self):
        # Avoid desktop initialization, saved state, and instrumentation.
        QObject.__init__(self)
        self._surface_host = SurfaceFixture(self)
        self._grok = GrokFixture()
        self._process = None
        self._decoder = codecs.getincrementaldecoder('utf-8')(errors='strict')
        self._stdout_buffer = ''
        self._stderr_buffer = ''
        self._busy = False
        self._request_id = ''
        self._stop_requested = False
        self._closing = False
        self.activity = []
        self._activity_callback = lambda *args: self.activity.append(args)

class IdleServerProcess(QProcess):
    def setArguments(self, arguments):
        # Exercise the actual transport startup/finished hooks using a local
        # sleeping child, without loading a model or reaching any service.
        super().setArguments(['-B', '-c', 'import time; time.sleep(60)'])

transport = TransportFixture()
host = transport._surface_host
grok = transport._grok

def start_server():
    with patch.object(resident_chat_qt, 'QProcess', IdleServerProcess):
        transport._ensure_server()
    process = transport._process
    assert process is not None
    assert process.state() == QProcess.Running
    return process

def stopped(process):
    return not isValid(process) or process.state() == QProcess.NotRunning

def ticks_continue():
    ticks, samples = host.ticks, host.sampler.samples
    loop = QEventLoop()
    QTimer.singleShot(35, loop.quit)
    loop.exec()
    assert host.timer.isActive(), 'shared surface timer was stopped'
    assert host.sampler.timer.isActive(), 'shared sampler was closed'
    assert host.ticks > ticks and host.sampler.samples > samples

scenario = sys.argv[1]
process = start_server()
try:
    if scenario == 'busy':
        transport._busy = True
        assert transport.shutdown_idle() is False
        assert transport._process is process and not stopped(process)
        transport._busy = False
        grok.active = True
        assert transport.shutdown_idle() is False
        assert transport._process is process and not stopped(process)
        assert grok.idle_calls == 0 and host.shutdown_calls == 0
        grok.active = False
        ticks_continue()
    elif scenario == 'grok-refusal':
        grok.refuse_idle = True
        assert transport.shutdown_idle() is False
        assert transport._process is process and not stopped(process)
        assert host.shutdown_calls == 0
        ticks_continue()
    elif scenario == 'idle':
        assert transport.shutdown_idle() is True
        assert stopped(process) and transport._process is None
        assert grok.idle_calls == 1 and grok.shutdown_calls == 0
        assert host.shutdown_calls == 0
        assert not transport._closing and not transport.busy()
        ticks_continue()
    elif scenario == 'restart':
        assert transport.shutdown_idle() is True and stopped(process)
        assert transport.shutdown_idle() is True
        replacement = start_server()
        assert replacement is not process
        assert transport.shutdown_idle() is True and stopped(replacement)
        assert host.shutdown_calls == 0
        assert grok.shutdown_calls == 0 and grok.idle_calls == 3
        ticks_continue()
    elif scenario == 'full':
        transport.shutdown()
        assert stopped(process) and transport._process is None
        assert host.shutdown_calls == 1 and grok.shutdown_calls == 1
        assert not host.timer.isActive() and not host.sampler.timer.isActive()
    elif scenario in ('surface-failure', 'grok-failure'):
        host.fail_shutdown = scenario == 'surface-failure'
        grok.fail_shutdown = scenario == 'grok-failure'
        try:
            transport.shutdown()
        except RuntimeError:
            pass
        else:
            raise AssertionError('cleanup failure unexpectedly disappeared')
        assert stopped(process) and transport._process is None
        assert host.shutdown_calls == 1 and grok.shutdown_calls == 1
        assert not transport._closing
        assert not host.timer.isActive() and not host.sampler.timer.isActive()
    else:
        raise AssertionError('unknown test scenario')
    print('LIFECYCLE_OK', flush=True)
finally:
    host.fail_shutdown = grok.fail_shutdown = False
    grok.active = False
    transport.shutdown()
'''
            result = subprocess.run(
                [sys.executable, "-X", "utf8", "-B", "-c", code, scenario],
                cwd=PROJECT, env=env, capture_output=True, text=True,
                encoding="utf-8", timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("LIFECYCLE_OK", result.stdout)
            self.assertNotIn("QProcess: Destroyed while process", result.stderr)

    def test_idle_cleanup_keeps_surface_and_sampler_ticking(self):
        self.run_lifecycle("idle")

    def test_busy_chat_and_busy_grok_refuse_idle_cleanup(self):
        self.run_lifecycle("busy")

    def test_grok_idle_refusal_preserves_model_process(self):
        self.run_lifecycle("grok-refusal")

    def test_repeated_idle_cleanup_allows_model_restart(self):
        self.run_lifecycle("restart")

    def test_full_shutdown_stops_surface_sampler_and_model(self):
        self.run_lifecycle("full")

    def test_surface_cleanup_failure_still_stops_grok_and_model(self):
        self.run_lifecycle("surface-failure")

    def test_grok_cleanup_failure_still_stops_model(self):
        self.run_lifecycle("grok-failure")


if __name__ == "__main__":
    unittest.main()
