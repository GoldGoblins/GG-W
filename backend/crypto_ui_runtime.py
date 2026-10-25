"""One asynchronous snapshot/action lane for the three CRYPTO surfaces.

Qt callers read prepared strings only. Slow RPC, filesystem, subprocess and
JSON work stays in the lane; an accepted user action runs once, without retry.
"""
from __future__ import annotations

import json
import re
import threading
import time
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal, Slot


def _initial() -> dict[str, Any]:
    missing = {"closes": [], "times": [], "stale": True, "error": "", "source": ""}
    return {
        "wallet": {"connected": False, "pubkey": "", "balance_sol": "—", "network": "testnet"},
        "legend": "LOCALNET", "signer": False, "accounts": [], "holdings": [], "tokens": [],
        "lab": {"running": False, "healthy": False, "label": "CHECKING"},
        "chart": dict(missing), "kas_chart": dict(missing), "portfolio": {},
        "quote": {}, "bot": {}, "trader": {}, "paper_engine": {},
        "refreshing": True, "ui_operation": {},
    }


def _error(exc: BaseException) -> str:
    value = str(exc)
    return value if re.fullmatch(r"[A-Z][A-Z0-9_]{1,79}", value) else type(exc).__name__


def _result_error(result: Any) -> str:
    if not isinstance(result, dict):
        return ""
    error = result.get("error")
    for name in ("signal", "airdrop", "fired", "arb_last"):
        child = result.get(name)
        if isinstance(child, dict):
            error = error or child.get("error")
    if not error:
        return ""
    return _error(RuntimeError(str(error)))


class CryptoUiRuntime(QObject):
    updated = Signal(str)
    _prepared = Signal(int, str)

    def __init__(self, parent: QObject | None = None,
                 snapshot: Callable[[], dict[str, Any]] | None = None,
                 ttl: float = 0.75) -> None:
        super().__init__(parent)
        if snapshot is None:
            from backend.crypto_host import status_payload
            snapshot = status_payload
        self._snapshot = snapshot
        self._ttl = ttl
        self._lock = threading.Lock()
        self._closed = False
        self._running = False
        self._pending: tuple[str, Callable[[], Any]] | None = None
        self._active = ""
        self._operation: dict[str, Any] = {}
        self._last_completed = 0.0
        self._revision = 0
        self._published_revision = 0
        self._payload = _initial()
        self._body = self._body_prefix(self._payload)
        self._rail_body = self._body_prefix(self._rail_payload(self._payload))
        self._full = self._attach(self._body, {})
        self._rail = self._attach(self._rail_body, {})
        self._prepared.connect(self._deliver)

    @staticmethod
    def _encode(payload: dict[str, Any]) -> str:
        return json.dumps(payload, separators=(",", ":"), allow_nan=False)

    @classmethod
    def _body_prefix(cls, payload: dict[str, Any]) -> str:
        body = dict(payload)
        body.pop("ui_operation", None)
        return cls._encode(body)[:-1] + ',"ui_operation":'

    @staticmethod
    def _attach(prefix: str, operation: dict[str, Any]) -> str:
        # Only the tiny operation record is encoded on a Qt call. The complete
        # report/tape has already been encoded by the worker outside its lock.
        return prefix + json.dumps(operation, separators=(",", ":")) + "}"

    @staticmethod
    def _rail_payload(payload: dict[str, Any]) -> dict[str, Any]:
        return {key: payload.get(key) for key in
                ("wallet", "legend", "signer", "accounts", "lab", "ui_operation", "refreshing", "error")} | {
                    "holdings": (payload.get("holdings") or [])[:8],
                    "pump": {key: (payload.get("pump") or {}).get(key) for key in
                             ("mint", "state", "loading", "stale", "slot", "error")}}

    def snapshot(self, rail: bool = False) -> str:
        self.refresh()
        with self._lock:
            return self._rail if rail else self._full

    def refresh(self) -> None:
        with self._lock:
            if self._closed or self._running or time.monotonic() - self._last_completed < self._ttl:
                return
            self._running = True
        self._start()

    def submit(self, name: str, callback: Callable[[], Any]) -> str:
        launch = False
        with self._lock:
            if self._closed:
                return self._full
            # Keep only one user action; neither double-click nor a later timer
            # can queue a second transaction behind an uncertain first action.
            if self._pending is not None or self._active:
                return self._full
            self._pending = (name, callback)
            self._operation = {"name": name, "state": "running", "error": ""}
            self._full = self._attach(self._body, self._operation)
            self._rail = self._attach(self._rail_body, self._operation)
            raw = self._full
            self._revision += 1
            revision = self._revision
            if not self._running:
                self._running = True
                launch = True
        self._prepared.emit(revision, raw)
        if launch:
            self._start()
        with self._lock:
            return self._full

    def _start(self) -> None:
        try:
            threading.Thread(target=self._run, name="gg-crypto-ui", daemon=True).start()
        except Exception:
            with self._lock:
                self._running = False
                self._pending = None
                self._active = ""
                self._operation = {"name": self._operation.get("name", ""), "state": "error", "error": "CRYPTO_WORKER_START"}
                self._full = self._attach(self._body, self._operation)
                self._rail = self._attach(self._rail_body, self._operation)
                self._revision += 1
                revision, raw = self._revision, self._full
            self._prepared.emit(revision, raw)

    def _run(self) -> None:
        while True:
            with self._lock:
                if self._closed:
                    self._running = False
                    return
                action = self._pending
                self._pending = None
                self._active = action[0] if action else ""
            result: Any = None
            action_error = ""
            if action:
                try:
                    result = action[1]()
                    action_error = _result_error(result)
                except Exception as exc:
                    action_error = _error(exc)
            try:
                if isinstance(result, dict) and {"wallet", "lab", "chart"}.issubset(result):
                    payload = dict(result)
                else:
                    payload = self._snapshot()
                if not isinstance(payload, dict):
                    raise ValueError("CRYPTO_STATUS_INVALID")
                payload = dict(payload, refreshing=False)
            except Exception as exc:
                with self._lock:
                    payload = dict(self._payload)
                payload.update(refreshing=False, error=_error(exc))
            # Serialization may traverse a large backtest report. It must not
            # own the lock needed by snapshot()/submit() on Qt's GUI thread.
            try:
                body = self._body_prefix(payload)
                rail_body = self._body_prefix(self._rail_payload(payload))
            except (TypeError, ValueError):
                with self._lock:
                    payload = dict(self._payload, refreshing=False, error="CRYPTO_STATUS_INVALID")
                body = self._body_prefix(payload)
                rail_body = self._body_prefix(self._rail_payload(payload))
            with self._lock:
                self._active = ""
                if self._closed:
                    self._running = False
                    return
                if action:
                    self._operation = {"name": action[0], "state": "error" if action_error else "done", "error": action_error}
                full = self._attach(body, self._operation)
                rail = self._attach(rail_body, self._operation)
                changed = full != self._full
                self._body, self._rail_body = body, rail_body
                self._payload, self._full, self._rail = payload, full, rail
                self._last_completed = time.monotonic()
                self._revision += 1
                revision = self._revision
                again = self._pending is not None
                if not again:
                    self._running = False
            if changed:
                self._prepared.emit(revision, full)
            if not again:
                return

    @Slot(int, str)
    def _deliver(self, revision: int, raw: str) -> None:
        with self._lock:
            if self._closed or revision <= self._published_revision:
                return
            self._published_revision = revision
        self.updated.emit(raw)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._pending = None
