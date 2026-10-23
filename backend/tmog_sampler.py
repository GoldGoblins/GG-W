"""Bounded telemetry workers; QML getters only read prepared JSON strings.

Meters and page inventories have separate lanes so a slow process/service
query cannot block either rendering or the live meters. Each lane has one
worker, one current request, and bounded latest-value storage.
"""
from __future__ import annotations

import json
import os
import threading
import time

from backend import tmog_contract

PAGES = frozenset(("", "SUMMARY", "PERFORMANCE", "PROCESSES", "SYSTEM", "STARTUP",
                   "USERS", "SERVICES", "FREQ", "FLIGHT", "CONNECTIONS", "APPS",
                   "DRIVERS", "DISK", "BENCHMARKS"))
FRAME_SECONDS = 1.0 / 60.0
PAGE_SECONDS = 1.0
IDLE_SECONDS = 2.0


class TmogSampler:
    def __init__(self, *, isolate: bool | None = None) -> None:
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._meter_wake = threading.Event()
        self._page_wake = threading.Event()
        self._meter_thread: threading.Thread | None = None
        self._page_thread: threading.Thread | None = None
        self._meter_requested = 0.0
        self._page_requested = 0.0
        self._page = "SUMMARY"
        self._live = {"schema": tmog_contract.SCHEMA, "pending": True}
        self._pulse_raw = json.dumps(self._live, separators=(",", ":"))
        self._pages: dict[str, str] = {}
        # Windows psutil calls can hold the GIL. Background threads alone
        # would still stall Python slots used by other desktop surfaces.
        self._isolate = os.name == "nt" if isolate is None else isolate
        self._workers: dict[str, object] = {}
        self._retry_at: dict[str, float] = {}

    def _collect(self, op: str, **kwargs):
        if not self._isolate:
            return tmog_contract.pulse() if op == "pulse" else tmog_contract.snapshot(**kwargs)
        worker = self._workers.get(op)
        if worker is None or worker.closed:
            if time.monotonic() < self._retry_at.get(op, 0):
                raise RuntimeError("TELEMETRY_RETRY_PENDING")
            self._retry_at[op] = time.monotonic() + 5.0
            from backend.tmog_worker import TmogWorker
            worker = TmogWorker()
            with self._lock:
                self._workers[op] = worker
            if self._stop.is_set():
                worker.close()
                raise RuntimeError("TELEMETRY_CLOSED")
        return worker.request(op, timeout=2.0 if op == "pulse" else 15.0, **kwargs)

    def _close_worker(self, op: str) -> None:
        worker = self._workers.get(op)
        if worker is not None:
            worker.close()

    def _start_meters_locked(self) -> None:
        if self._meter_thread is None and not self._stop.is_set():
            self._meter_thread = threading.Thread(
                target=self._meters, name="gg-tmog-meters", daemon=True)
            self._meter_thread.start()

    def pulse(self) -> str:
        with self._lock:
            if not self._stop.is_set():
                self._meter_requested = time.monotonic()
                self._start_meters_locked()
                self._meter_wake.set()
            return self._pulse_raw

    def snapshot(self, page: str = "") -> str:
        page = str(page or "").strip().upper()
        if page not in PAGES:
            page = "SUMMARY"
        with self._lock:
            if not self._stop.is_set():
                self._page = page
                self._page_requested = self._meter_requested = time.monotonic()
                self._start_meters_locked()
                if self._page_thread is None:
                    self._page_thread = threading.Thread(
                        target=self._inventory, name="gg-tmog-pages", daemon=True)
                    self._page_thread.start()
                self._page_wake.set()
                self._meter_wake.set()
            raw = self._pages.get(page)
        return raw if raw is not None else json.dumps(
            {"schema": tmog_contract.SCHEMA, "page": page or "FULL", "pending": True},
            separators=(",", ":"))

    def _meters(self) -> None:
        while not self._stop.is_set():
            began = time.monotonic()
            with self._lock:
                active = began - self._meter_requested < IDLE_SECONDS
            if not active:
                self._meter_wake.wait(0.25)
                self._meter_wake.clear()
                continue
            try:
                live = self._collect("pulse")
                raw = json.dumps(live, separators=(",", ":"))
            except Exception as exc:
                with self._lock:
                    live = dict(self._live)
                live["error"] = type(exc).__name__
                raw = json.dumps(live, separators=(",", ":"))
            with self._lock:
                if self._stop.is_set():
                    break
                self._live, self._pulse_raw = live, raw
            # Python's high-resolution sleep avoids Windows Event.wait()
            # rounding a 16.7 ms period up to roughly 31 ms.
            time.sleep(max(0.0, FRAME_SECONDS - (time.monotonic() - began)))
        self._close_worker("pulse")

    def _inventory(self) -> None:
        previous_page = None
        next_sample = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            with self._lock:
                page = self._page
                active = now - self._page_requested < IDLE_SECONDS
                live = dict(self._live)
            if not active or (page == previous_page and now < next_sample):
                self._page_wake.wait(0.25 if not active else
                                     min(0.25, max(0.001, next_sample - now)))
                self._page_wake.clear()
                continue
            if live.get("pending"):
                self._stop.wait(FRAME_SECONDS)
                continue
            try:
                data = self._collect("snapshot", page=page, live=live)
                raw = json.dumps(data, separators=(",", ":"))
            except Exception as exc:
                raw = json.dumps({"schema": tmog_contract.SCHEMA,
                                  "page": page or "FULL", "error": type(exc).__name__},
                                 separators=(",", ":"))
            with self._lock:
                if self._stop.is_set():
                    break
                self._pages[page] = raw
            previous_page = page
            next_sample = time.monotonic() + PAGE_SECONDS
        self._close_worker("snapshot")

    def close(self) -> None:
        self._stop.set()
        self._meter_wake.set()
        self._page_wake.set()
        with self._lock:
            workers = list(self._workers.values())
        for worker in workers:
            # Each fixed telemetry worker has no descendants. Terminate only
            # that child here; its IO lane reaps it and closes pipes off-UI.
            try:
                worker.process.terminate()
            except OSError:
                pass
        # A driver may be slow even during shutdown. Never wait on it from
        # the UI; daemon workers stop after their current read and publish
        # nothing once closed. Idle workers exit immediately.
