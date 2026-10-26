"""Explicit, finite MEDIA discovery and quick checks with a shared pause control.

Only worker threads call this module. Public status contains counts, never
source URLs or private audit identifiers. An existing CLI audit remains visible
and can be paused, but opening MEDIA never starts or adopts source work.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import closing

from backend.media_discovery import discover

MAX_SECONDS = 300.0
MAX_JOBS = 240
META_KEY = "media_background_session"


def _make_audit(index):
    # Import the HTTP/diagnostic machinery on the worker that uses it, rather
    # than on the GUI's first MEDIA status request.
    from backend.media_health_audit import MediaHealthAudit
    return MediaHealthAudit(index)


def empty_status():
    return dict(running=False, pausing=False, paused=True, phase="paused", external=False,
                workers=0, discovered_movies=0, discovered_series=0, new_movies=0,
                new_series=0, new_episodes=0, errors=0, notice="", budget_seconds=300,
                remaining_seconds=0)


class _Deadline:
    def __init__(self, cancel, deadline):
        self.cancel, self.deadline = cancel, deadline

    def is_set(self):
        return self.cancel.is_set() or time.monotonic() >= self.deadline

    def wait(self, timeout=None):
        return self.cancel.wait(max(0, min(timeout if timeout is not None else MAX_SECONDS,
                                           self.deadline - time.monotonic()))) or self.is_set()


class _Finished(Exception):
    pass


class MediaBackgroundWork:
    def __init__(self, index):
        self.index = index
        self._lock = threading.RLock()
        self._local_active = False
        self._local_cancel = None
        self._session = None

    @staticmethod
    def _latest(db):
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='media_audit_runs'").fetchone():
            return None
        row = db.execute("SELECT id,status,cancel_requested,owner,lease_until FROM media_audit_runs ORDER BY id DESC LIMIT 1").fetchone()
        return dict(id=row[0], status=row[1], cancelled=bool(row[2]), active=bool(row[3]) and row[4] > time.time()) if row else None

    def _inspect(self):
        if not self.index.path.is_file():
            return None
        with closing(sqlite3.connect(self.index.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=.25)) as db:
            return self._latest(db)

    def read_status(self):
        status = empty_status()
        if not self.index.path.is_file():
            return status
        try:
            with closing(sqlite3.connect(self.index.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=.25)) as db:
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                saved = db.execute("SELECT value FROM meta WHERE key=?", (META_KEY,)).fetchone() if "meta" in tables else None
                session = json.loads(saved[0]) if saved else {}
                for key in ("phase", "discovered_movies", "discovered_series", "errors", "notice"):
                    if key in session:
                        status[key] = session[key]
                deadline = float(session.get("deadline") or 0)
                status["remaining_seconds"] = max(0, int(deadline - time.time()))
                run = self._latest(db)
                with self._lock:
                    local = self._local_active
                    local_stopping = local and (self._local_cancel.is_set() or status["remaining_seconds"] <= 0)
                external = bool(run and run["active"] and not local)
                status["external"] = external
                status["pausing"] = local_stopping or bool(run and run["active"] and run["cancelled"])
                status["running"] = bool(local or run and run["active"]) and not status["pausing"]
                status["paused"] = not status["running"] and not status["pausing"]
                if status["pausing"]:
                    status["phase"] = "pausing"
                elif external:
                    status["phase"] = "checking"
                    status["remaining_seconds"] = 0
                elif not local and status["phase"] not in ("complete", "error"):
                    status["phase"] = "paused"
                    status["remaining_seconds"] = 0
                if run and run["active"]:
                    status["workers"] = db.execute("SELECT COUNT(*) FROM media_audit_jobs WHERE run_id=? AND state='running'", (run["id"],)).fetchone()[0]
                elif local and status["phase"] == "checking":
                    status["workers"] = 2
                if "media_background_baseline" in tables:
                    query, parameters = self._groups_query(time.time())
                    for kind, count in db.execute("SELECT current.kind,COUNT(*) FROM (" + query + ") current "
                        "LEFT JOIN media_background_baseline baseline ON baseline.kind=current.kind "
                        "AND baseline.group_key=current.group_key WHERE baseline.group_key IS NULL GROUP BY current.kind", parameters):
                        status["new_" + kind] = count
        except (OSError, sqlite3.Error, ValueError, TypeError):
            # Read-only status failure must not create work or erase a known
            # running worker. The next normal poll retries the short read.
            with self._lock:
                status["running"] = self._local_active and not self._local_cancel.is_set()
                status["pausing"] = self._local_active and self._local_cancel.is_set()
                status["paused"] = not self._local_active
            status["notice"] = "Status kunde inte läsas. Försöker igen."
        return status

    def _groups_query(self, now):
        healthy = self.index._catalogued_sql("i")
        return ("SELECT DISTINCT 'movies' AS kind,i.group_key FROM items i WHERE i.type='movie' AND " + healthy +
                " UNION SELECT DISTINCT 'episodes',i.group_key FROM items i WHERE i.type='episode' AND " + healthy +
                " UNION SELECT DISTINCT 'series',i.parent_key FROM items i WHERE i.type='episode' AND i.parent_key<>'' AND " + healthy,
                [now, now, now])

    def _save(self, **updates):
        with self._lock:
            if self._session is None:
                raw = self.index.meta(META_KEY)
                self._session = json.loads(raw) if raw else {}
            self._session.update(updates)
            self.index.meta(META_KEY, json.dumps(self._session, separators=(",", ":")))

    def _notify(self, notify):
        status = self.read_status()
        if notify:
            notify(status)
        return status

    def _baseline(self, budget):
        query, parameters = self._groups_query(time.time())
        with self.index.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS media_background_baseline(kind TEXT NOT NULL,group_key TEXT NOT NULL,PRIMARY KEY(kind,group_key))")
            db.execute("DELETE FROM media_background_baseline")
            db.execute("INSERT INTO media_background_baseline(kind,group_key) " + query, parameters)
            self._session = dict(phase="starting", discovered_movies=0, discovered_series=0, errors=0,
                                 notice="", started_at=time.time(), deadline=time.time() + budget)
            db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (META_KEY, json.dumps(self._session)))

    def run(self, cancel, *, max_seconds=MAX_SECONDS, notify=None):
        """One explicitly requested slice. No timer or browse calls this."""
        if cancel.is_set():
            return self.read_status()
        existing = self._inspect()
        if existing and existing["active"]:
            # Never silently take over or stop the prior command-line job.
            # Its visible switch can pause it explicitly before a new slice.
            return self._notify(notify)
        budget = max(.1, min(MAX_SECONDS, float(max_seconds)))
        deadline = time.monotonic() + budget
        bounded = _Deadline(cancel, deadline)
        with self._lock:
            if self._local_active:
                return self.read_status()
            self._local_active, self._local_cancel = True, cancel
        try:
            self._baseline(budget)
            self._notify(notify)
            for page in ("movies", "series"):
                if bounded.is_set():
                    break
                self._save(phase="discovering_" + page)
                self._notify(notify)
                result = discover(self.index, page, cancel=bounded, max_pages=1)
                updates = {"discovered_" + page: max(0, int(result.get("new_candidates") or 0))}
                if result.get("error"):
                    updates.update(errors=int(self._session.get("errors") or 0) + 1,
                                   notice="En källsökning kunde inte slutföras. Sparade kandidater kontrolleras ändå.")
                self._save(**updates)
                self._notify(notify)
            if bounded.is_set():
                self._save(phase="paused", notice="Pausad. Framstegen är sparade.")
                raise _Finished
            audit = _make_audit(self.index)
            latest = self._inspect()
            if latest and latest["active"]:
                raise _Finished
            if latest:
                run_id = latest["id"]
                audit.repair(run_id)
                audit.include(run_id)
            else:
                run_id = audit.start(force=False)
            if bounded.is_set():
                self._save(phase="paused", notice="Pausad. Framstegen är sparade.")
                raise _Finished
            self._save(phase="checking")
            self._notify(notify)
            result = audit.run(run_id, workers=2, max_seconds=max(.1, deadline - time.monotonic()),
                               max_jobs=MAX_JOBS, cancel=bounded, lanes=("movies", "series"))
            complete = result.get("status") == "complete"
            self._save(phase="complete" if complete else "paused",
                       notice="Kontrollen är klar." if complete else "Pausad. Framstegen är sparade; starta för att fortsätta.")
        except _Finished:
            pass
        except Exception:
            self._save(phase="error", errors=int((self._session or {}).get("errors") or 0) + 1,
                       notice="Bakgrundsarbetet kunde inte slutföras. Framstegen är sparade.")
        finally:
            with self._lock:
                self._local_active = False
        return self._notify(notify)

    def pause(self, cancel, *, wait_seconds=10, notify=None):
        """Persist stop on the real audit and wait briefly on a worker only."""
        cancel.set()
        with self._lock:
            if self._local_cancel is not None:
                self._local_cancel.set()
        latest = self._inspect()
        if latest:
            self._save(phase="pausing", notice="Pausar pågående källkontroller…")
            _make_audit(self.index).stop(latest["id"])
            self._notify(notify)
            deadline = time.monotonic() + max(0, min(10, float(wait_seconds)))
            while time.monotonic() < deadline:
                latest = self._inspect()
                if not latest or not latest["active"]:
                    break
                time.sleep(.1)
        latest = self._inspect()
        with self._lock:
            local = self._local_active
        if not local and not (latest and latest["active"]):
            if self.index.path.is_file():
                self._save(phase="paused", notice="Pausad. Framstegen är sparade.")
        return self._notify(notify)
