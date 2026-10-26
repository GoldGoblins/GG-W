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
from backend import media_languages as languages
from backend import media_search_scope as scope

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
                remaining_seconds=0, discovered_live=0, new_live=0,
                operation="expand", checked_existing=0, available_existing=0, failed_existing=0, unknown_existing=0, check_video_prepared=False,
                **{"new_" + key: 0 for key in ("music", "radio", "games", "downloads")},
                **{"discovered_" + key: 0 for key in ("music", "radio", "games", "downloads")})


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
                for key in ("phase", "errors", "notice", "selected_types", "operation", "checked_existing", "available_existing",
                            "failed_existing", "unknown_existing", "check_video_prepared", *["discovered_" + key for key in scope.DEFAULT_TYPES]):
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
                " UNION SELECT DISTINCT 'live',i.group_key FROM items i WHERE i.type='live' AND " + healthy +
                " UNION SELECT DISTINCT 'episodes',i.group_key FROM items i WHERE i.type='episode' AND " + healthy +
                " UNION SELECT DISTINCT 'series',i.parent_key FROM items i WHERE i.type='episode' AND i.parent_key<>'' AND " + healthy +
                " UNION SELECT DISTINCT CASE i.kind WHEN 'MUSIC' THEN 'music' WHEN 'RADIO' THEN 'radio' "
                "WHEN 'GAME' THEN 'games' WHEN 'FETCH' THEN 'downloads' END,i.group_key FROM items i "
                "WHERE i.kind IN ('MUSIC','RADIO','GAME','FETCH') AND COALESCE(json_extract(i.payload,'$.source'),'')<>'' "
                "AND NOT EXISTS (SELECT 1 FROM media_hidden_items hidden WHERE hidden.item_id=i.id) "
                "AND NOT EXISTS (SELECT 1 FROM media_hidden_groups hidden WHERE hidden.group_key=i.group_key)",
                [now, now, now, now])

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

    def _baseline(self, budget, selected_types=None):
        query, parameters = self._groups_query(time.time())
        with self.index.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS media_background_baseline(kind TEXT NOT NULL,group_key TEXT NOT NULL,PRIMARY KEY(kind,group_key))")
            db.execute("DELETE FROM media_background_baseline")
            db.execute("INSERT INTO media_background_baseline(kind,group_key) " + query, parameters)
            self._session = dict(phase="starting", discovered_movies=0, discovered_series=0, errors=0,
                                 selected_types=list(selected_types or ("movies", "series")),
                                 notice="", started_at=time.time(), deadline=time.time() + budget)
            db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (META_KEY, json.dumps(self._session)))

    def run(self, cancel, *, max_seconds=MAX_SECONDS, notify=None, selected_languages=None, page=None, selected_types=None, check_only=False):
        """One explicitly requested slice. No timer or browse calls this."""
        if cancel.is_set():
            return self.read_status()
        targets = scope.types(selected_types) if selected_types is not None else (("live",) if page == "live" else ("movies", "series"))
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
            previous = json.loads(self.index.meta(META_KEY) or "{}")
            chosen_languages = list(languages.selection(selected_languages) or [])
            resume = bool(check_only and previous.get("operation") == "check" and previous.get("phase") in ("paused", "pausing", "error")
                          and previous.get("selected_types") == list(targets) and previous.get("selected_languages") == chosen_languages)
            cycle_started = float(previous.get("check_started_at") or time.time()) if resume else time.time()
            self._baseline(budget, targets)
            self._save(operation="check" if check_only else "expand", selected_languages=chosen_languages,
                       check_started_at=cycle_started, check_video_prepared=bool(resume and previous.get("check_video_prepared")),
                       **{key: int(previous.get(key) or 0) if resume else 0 for key in
                          ("checked_existing", "available_existing", "failed_existing", "unknown_existing")})
            self._notify(notify)
            pages = tuple(target for target in targets if target in ("live", "movies", "series"))
            for target in (() if check_only else targets):
                if bounded.is_set():
                    break
                self._save(phase="discovering_" + target)
                self._notify(notify)
                try:
                    if target in ("movies", "series"):
                        result = discover(self.index, target, cancel=bounded, max_pages=1, selected_languages=selected_languages)
                    else:
                        result = scope.collect(self.index, target, cancel=bounded, selected_languages=selected_languages)
                except (OSError, RuntimeError, ValueError, TimeoutError):
                    result = {"error": "source_unavailable"}
                updates = {"discovered_" + target: max(0, int(result.get("new_candidates", result.get("new_sources")) or 0))}
                if result.get("error"):
                    updates.update(errors=int(self._session.get("errors") or 0) + 1,
                                   notice="En källsökning kunde inte slutföras. Sparade kandidater kontrolleras ändå.")
                self._save(**updates)
                self._notify(notify)
            other_pending = False
            other_checked = 0
            if check_only:
                from backend.media_existing_checks import check_saved
                self._save(phase="checking")
                self._notify(notify)
                checked = check_saved(self.index, targets, selected_languages=selected_languages, cycle_started=cycle_started,
                                      cancel=bounded, max_jobs=MAX_JOBS // 2 if pages else MAX_JOBS)
                other_pending = checked["pending"]
                other_checked = checked["checked"]
                self._save(**{key + "_existing": int(self._session.get(key + "_existing") or 0) + checked[key]
                              for key in ("checked", "available", "failed", "unknown")})
                self._notify(notify)
            if bounded.is_set():
                self._save(phase="paused", notice="Pausad. Framstegen är sparade.")
                raise _Finished
            if not pages:
                self._save(phase="paused" if other_pending else "complete", notice="Pausad. Starta källkontrollen för att fortsätta."
                           if other_pending else "Källkontrollen är klar." if check_only else "Sökningen är klar med källfel. Sparade träffar finns kvar."
                           if self._session.get("errors") else "Sökningen är klar. Valda mediatyper har uppdaterats.")
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
            if check_only and not self._session.get("check_video_prepared"):
                audit.recheck(run_id, lanes=pages, selected_languages=selected_languages, before=cycle_started)
                self._save(check_video_prepared=True)
            if bounded.is_set():
                self._save(phase="paused", notice="Pausad. Framstegen är sparade.")
                raise _Finished
            self._save(phase="checking")
            self._notify(notify)
            result = audit.run(run_id, workers=2, max_seconds=max(.1, deadline - time.monotonic()),
                               max_jobs=max(1, MAX_JOBS - other_checked), cancel=bounded, lanes=pages, selected_languages=selected_languages)
            complete = not other_pending and (result.get("status") == "complete" or ("focus_total" in result and result["focus_done"] >= result["focus_total"]))
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
        if latest and latest["active"]:
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
            if self.index.path.is_file() and self.read_status().get("phase") != "complete":
                self._save(phase="paused", notice="Pausad. Framstegen är sparade.")
        return self._notify(notify)
