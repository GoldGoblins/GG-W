"""Qt bridge for the bounded native OSIRIS collector."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import json
import threading
import time
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from backend import osint_contract, osint_nearby, research_desk

_EMPTY_UI: dict[str, Any] = {
    "page": "OVERVIEW",
    "navMode": False,
    "navPlaces": [],
    "navDraft": "",
    "navMeta": "",
    "route": None,
    "selected": None,
    "view": None,
    "sidebarCollapsed": False,
    "streamMode": "NEWS",
}


class OsintHost(QObject):
    """Keep public-feed I/O off the Qt GUI thread."""

    updated = Signal(str)
    stateChanged = Signal(str)
    flightLookedUp = Signal(str)
    nearbyUpdated = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="gg-osiris-refresh",
        )
        self._future: Future[Any] | None = None
        self._raw = json.dumps(
            osint_contract.empty_snapshot(), separators=(",", ":")
        )
        self._closed = False
        self._ui: dict[str, Any] = dict(_EMPTY_UI)
        self._nearby_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gg-nearby")
        self._nearby_future: Future[Any] | None = None
        self._nearby_active = False
        self._nearby_generation = 0
        self._nearby_at = 0.0
        self._nearby_raw = json.dumps({"status": "PAUSED", "rows": [], "sources": []})

    @Slot(str, result=str)
    def snapshot(self, page: str = "OVERVIEW") -> str:
        with self._lock:
            if self._closed:
                return self._raw
        try:
            return json.dumps(
                osint_contract.snapshot(page), separators=(",", ":")
            )
        except Exception as exc:
            return json.dumps(
                {
                    "schema": osint_contract.SCHEMA,
                    "scope": osint_contract.SAFE_SCOPE,
                    "page": str(page or "OVERVIEW").upper(),
                    "status": "ERROR",
                    "error": type(exc).__name__,
                },
                separators=(",", ":"),
            )

    @Slot(str, result=str)
    def viewportSnapshot(self, view_json: str = "{}") -> str:
        """Return only the render window for the current map viewport."""
        try:
            view = json.loads(view_json or "{}")
        except (TypeError, ValueError):
            view = {}
        if not isinstance(view, dict):
            view = {}
        try:
            return json.dumps(
                osint_contract.viewport_snapshot(view), separators=(",", ":")
            )
        except Exception as exc:
            return json.dumps(
                {
                    "schema": osint_contract.SCHEMA,
                    "scope": osint_contract.SAFE_SCOPE,
                    "page": "MAP",
                    "status": "ERROR",
                    "error": type(exc).__name__,
                },
                separators=(",", ":"),
            )

    @Slot(bool)
    def setNearbyActive(self, enabled: bool) -> None:
        with self._lock:
            enabled = bool(enabled) and not self._closed
            if enabled != self._nearby_active:
                self._nearby_active = enabled
                self._nearby_generation += 1
                self._nearby_at = 0.0
                self._nearby_raw = json.dumps({"status": "WAITING" if enabled else "PAUSED", "rows": [], "sources": []})
        if enabled:
            self.nearbySnapshot()

    @Slot(result=str)
    def nearbySnapshot(self) -> str:
        with self._lock:
            if self._nearby_active and self._nearby_future is None and time.monotonic() - self._nearby_at >= 5:
                token = self._nearby_generation
                self._nearby_future = self._nearby_executor.submit(osint_nearby.collect)
                self._nearby_future.add_done_callback(lambda future: self._nearby_finished(future, token))
            return self._nearby_raw

    def _nearby_finished(self, future: Future[Any], token: int) -> None:
        try:
            payload = future.result()
        except Exception:
            payload = {"status": "UNAVAILABLE", "rows": [], "sources": []}
        with self._lock:
            if self._nearby_future is future:
                self._nearby_future = None
            if self._closed or not self._nearby_active or token != self._nearby_generation:
                return
            self._nearby_at = time.monotonic()
            self._nearby_raw = json.dumps(payload, separators=(",", ":"))
            raw = self._nearby_raw
        self.nearbyUpdated.emit(raw)

    @Slot(str, str, result=str)
    def recordEvidence(self, kind: str, event_id: str) -> str:
        payload = osint_contract.observation_evidence(kind, event_id)
        if payload.get("status") == "OBSERVATION_READY":
            try:
                result = research_desk.add_evidence(payload)
                payload = {"status": result["status"]}
            except Exception as exc:
                payload = {"status": "ERROR", "error": type(exc).__name__}
        return json.dumps(payload, separators=(",", ":"))

    @Slot(str, result=str)
    def planRoute(self, spec_json: str = "{}") -> str:
        try:
            spec = json.loads(spec_json or "{}")
        except json.JSONDecodeError:
            spec = {}
        if not isinstance(spec, dict):
            spec = {}
        places = spec.get("places") or []
        if not isinstance(places, list):
            places = []
        gps = spec.get("gps") if isinstance(spec.get("gps"), dict) else None
        result = osint_contract.plan_driving_route(
            [str(item) for item in places],
            gps,
        )
        with self._lock:
            self._ui["navPlaces"] = [str(item) for item in places][:26]
            self._ui["route"] = result if result.get("ok") else None
            if result.get("ok"):
                km = (float(result.get("distance_m") or 0) / 1000.0)
                minutes = round(float(result.get("duration_s") or 0) / 60.0)
                self._ui["navMeta"] = (
                    f"{km:.1f} km · {minutes} min · {len(places)} places"
                )
                self._ui["navMode"] = True
        return json.dumps(result, separators=(",", ":"))

    @Slot(str)
    def saveUi(self, raw: str = "{}") -> None:
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return
        if not isinstance(payload, dict):
            return
        with self._lock:
            for key in _EMPTY_UI:
                if key in payload:
                    self._ui[key] = payload[key]

    @Slot(result=str)
    def loadUi(self) -> str:
        with self._lock:
            return json.dumps(self._ui, separators=(",", ":"))

    @Slot(str, str, result=str)
    def lookupFlight(self, callsign: str = "", icao: str = "") -> str:
        cached = osint_contract.cached_flight(
            str(callsign or ""), str(icao or "")
        )
        if cached:
            return json.dumps(cached, separators=(",", ":"))
        with self._lock:
            if self._closed:
                return "{}"
            self._executor.submit(
                self._lookup_flight_job,
                str(callsign or ""),
                str(icao or ""),
            )
        return "{}"

    def _lookup_flight_job(self, callsign: str, icao: str) -> None:
        try:
            payload = osint_contract.lookup_flight(callsign, icao)
            raw = json.dumps(payload, separators=(",", ":"))
        except Exception as exc:
            raw = json.dumps(
                {"ok": False, "error": type(exc).__name__},
                separators=(",", ":"),
            )
        with self._lock:
            if self._closed:
                return
        self.flightLookedUp.emit(raw)

    @Slot(str, result=bool)
    def refresh(self, page: str = "OVERVIEW") -> bool:
        with self._lock:
            if self._closed:
                return False
            if self._future is not None:
                return False
            self.stateChanged.emit("FETCHING")
            self._future = self._executor.submit(
                osint_contract.collect_snapshot,
                str(page or "OVERVIEW"),
                True,
                self._publish_partial,
            )
            self._future.add_done_callback(self._finished)
        return True

    def _publish_partial(self, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, separators=(",", ":"))
        with self._lock:
            if self._closed:
                return
            self._raw = raw
        self.updated.emit(raw)

    def _finished(self, future: Future[Any]) -> None:
        try:
            payload = future.result()
            raw = json.dumps(payload, separators=(",", ":"))
            state = str(payload.get("status") or "READY")
        except Exception as exc:
            raw = json.dumps(
                {
                    "schema": osint_contract.SCHEMA,
                    "scope": osint_contract.SAFE_SCOPE,
                    "status": "ERROR",
                    "fetching": False,
                    "error": type(exc).__name__,
                },
                separators=(",", ":"),
            )
            state = "ERROR"
        with self._lock:
            if self._closed:
                return
            self._raw = raw
            if self._future is future:
                self._future = None
        # PySide queues this signal when a QML receiver lives on the GUI
        # thread.  The worker never touches QML objects directly.
        self.updated.emit(raw)
        self.stateChanged.emit(state)

    def shutdown(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._nearby_active = False
            self._nearby_generation += 1
            future = self._future
            self._future = None
        if future is not None:
            future.cancel()
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._nearby_executor.shutdown(wait=False, cancel_futures=True)
