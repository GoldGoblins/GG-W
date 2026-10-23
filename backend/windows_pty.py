"""A ConPTY terminal with the byte IO and process interface used by the UI."""
from __future__ import annotations

import codecs
import os
import signal
import subprocess
import time

from winpty import PtyProcess
from winpty.enums import Backend


class WindowsPty:
    def __init__(self, argv, *, cwd, env, cols=72, rows=36):
        self.args = list(argv)
        environment = dict(env)
        environment["PYWINPTY_BACKEND"] = str(Backend.ConPTY)
        self._pty = PtyProcess.spawn(self.args, cwd=str(cwd), env=environment,
                                     dimensions=(rows, cols), backend=Backend.ConPTY)
        self.pid = self._pty.pid
        self.returncode = None
        self._input_decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._closed = False
        self._pty.fileobj.setblocking(False)

    def fileno(self):
        return self._pty.fileobj.fileno()

    def read(self, size):
        return self._pty.fileobj.recv(size)

    def write(self, data):
        if self.poll() is not None:
            raise OSError("Terminal process has exited")
        text = self._input_decoder.decode(data)
        text = text.replace("\r\n", "\r").replace("\n", "\r")
        if text:
            try:
                self._pty.write(text)
            except EOFError as exc:
                raise OSError("Terminal process has exited") from exc
        return len(data)

    def resize(self, cols, rows):
        self._pty.setwinsize(rows, cols)

    def poll(self):
        if self.returncode is None and not self._pty.isalive():
            self.returncode = self._pty.exitstatus or 0
        return self.returncode

    def terminate(self):
        if self.poll() is None:
            # SIGTERM maps to TerminateProcess on Windows. This is the child
            # created by this terminal, never a host-wide process search.
            os.kill(self.pid, signal.SIGTERM)

    kill = terminate

    def wait(self, timeout=None):
        deadline = time.monotonic() + timeout if timeout is not None else None
        while self.poll() is None:
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(self.args, timeout)
            time.sleep(0.01)
        return self.returncode

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self.poll() is None:
            self.terminate()
            self.wait(timeout=1)
        self._pty.fileobj.close()
        self._pty._server.close()
        self._pty.closed = True
