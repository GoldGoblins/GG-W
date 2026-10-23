"""GG agent input bridge for EXT; never inject into the system input devices."""
from __future__ import annotations

from collections import deque
import threading
from backend.blender_contract import sidecar_call


class WindowInput:
    virtual_only = True

    def __init__(self, parent=0, *, target_pid=None, transport=None):
        self.parent = parent
        self.target_pid = target_pid
        self._transport = transport or sidecar_call
        self._region = None
        self._focus = False
        self._visible = False
        self._closed = False
        self._busy = False
        self._error = ""
        self._events = deque()
        self._condition = threading.Condition()
        self._worker = threading.Thread(target=self._run, name="GG-agent-input", daemon=True)
        self._worker.start()

    def set_region(self, x, y, width, height, ratio):
        self._region = (x, y, width, height, ratio)

    def _point(self, x, y):
        if self._region is None:
            return None
        left, top, width, height, ratio = self._region
        if not (left <= x < left + width and top <= y < top + height):
            return None
        return {"x": round((x-left)*ratio), "y": round((y-top)*ratio)}

    def _queue(self, event):
        with self._condition:
            if self._closed:
                return False
            if event["action"] == "MOVE" and self._events and self._events[-1]["action"] == "MOVE":
                self._events[-1] = event
            elif len(self._events) < 128:
                self._events.append(event)
            else:
                self._error = "BLENDER_AGENT_INPUT_QUEUE_FULL"
                return False
            self._condition.notify()
        return True

    def active(self):
        return not self._closed

    def keyboard_owned(self, child=None):
        return self._focus and not self._closed

    def move(self, x, y, ratio=None, *, shape="default"):
        point = self._point(x, y)
        if point is None:
            self.hide_cursor()
            return False
        self._visible = True
        return self._queue({"action": "MOVE", "shape": shape, **point})

    def click(self, x, y, ratio=None, button="left"):
        point = self._point(x, y)
        self._focus = point is not None
        if point is None:
            self.hide_cursor()
            return False
        self._visible = True
        return self._queue({"action": "CLICK", "button": button, **point})

    def key(self, name):
        return self._focus and self._queue({"action": "KEY", "key": name})

    def char(self, text):
        return self._focus and self._queue({"action": "TYPE", "text": text})

    def hide_cursor(self):
        if self._visible:
            self._visible = False
            self._queue({"action": "HIDE"})

    def error(self):
        with self._condition:
            return self._error

    def pending(self):
        with self._condition:
            return len(self._events) + int(self._busy)

    def close(self):
        with self._condition:
            if self._closed:
                return
            self._events.clear()
            self._events.append({"action": "HIDE"})
            self._closed = True
            self._condition.notify()

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or bool(self._events))
                if not self._events:
                    return
                events = [self._events.popleft() for _ in range(min(32, len(self._events)))]
                self._busy = True
            try:
                answer = self._transport("input", timeout=1, events=events, target_pid=self.target_pid)
                error = "" if answer.get("ok") else str(answer.get("error", "BLENDER_AGENT_INPUT_FAILED"))
            except Exception as exc:
                error = "BLENDER_AGENT_INPUT_FAILED:" + type(exc).__name__
            with self._condition:
                self._error = error
                self._busy = False
                if self._closed and not self._events:
                    return
