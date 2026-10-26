"""Finite, resumable MEDIA source audit, independent of catalogue browsing.

The audit checks decoded samples and source-metadata consistency. It does not
claim to have watched complete programmes or identified live-channel branding
from pixels. Only a decoded source whose metadata checks pass is admitted.
The CLI prints counts only; source URLs and item IDs stay in the private index.
"""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path
import re
import threading
import time
import unicodedata
from urllib.parse import quote, urlsplit
import uuid

from backend import media_availability as availability, media_contract as contract, media_library as library
from backend.media_index import MediaIndex

SCHEMA = "gg.media.health-audit.v1"
AUDIT_POLICY = "identity-and-numbering-v2"
TERMINAL = {"healthy", "failed", "unknown", "expanded", "changed"}
LANES = ("live", "movies", "series")
MAX_WORKERS = 24
ARCHIVE_PROVIDER_SLOTS = 12
RETRYABLE_ERRORS = {"timeout", "network_error", "provider_error", "rate_limited", "no_decoded_frames",
                    "byte_limit", "metadata_unavailable", "metadata_expansion_inconclusive", "worker_exception",
                    "encrypted_stream", "playlist_too_large", "unrecognized_media", "range_rejected",
                    "audio_unverified", "range_unsupported"}
CORRECTABLE_IDENTITY_REASONS = {"language_unconfirmed", "missing_season_evidence", "missing_episode_evidence",
                                "title_mismatch", "season_mismatch", "file_size_unconfirmed"}


def _queue_group(row):
    content_type = row.get("content_type")
    lane = "live" if content_type == "live" else "series" if content_type in ("series", "episode") else "movies"
    if lane == "series":
        group = row.get("collection_key") or MediaIndex.series_key(row)
    elif lane == "live":
        group = str(row.get("channel_id") or row.get("title") or row.get("id")).casefold()
    else:
        group = str(row.get("title") or row.get("id")).casefold() + "|" + str(row.get("year") or "")
    return lane, _hash(group)


def _is_descriptor(row):
    return int(not row.get("archive_file") and "/details/" in str(row.get("source") or ""))


def _hash(source):
    return hashlib.sha256(str(source).encode()).hexdigest()


def _cancelled(cancel):
    return bool(cancel and cancel.is_set())


def _words(value):
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return re.findall(r"[^\W_]+", "".join(c for c in text if not unicodedata.combining(c)), flags=re.UNICODE)


def _title_matches(expected, actual):
    left, right = _words(expected), _words(actual)
    if left and left == right:
        return True
    stop = {"season", "sasong", "seasons", "series", "complete", "full", "episode", "avsnitt",
            "swedish", "svenska", "swe", "english", "eng", "dvd", "dvdrip", "bluray", "hd", "tv",
            "film", "movie", "programme", "program", "show", "the", "an", "and", "of", "for", "with"}
    meaningful = lambda values: {word for word in values if word not in stop and not word.isdigit()
                                  and not re.fullmatch(r"s\d+(?:e\d+)?|\d{3,4}p", word) and len(word) > 1}
    left, right = meaningful(left), meaningful(right)
    return bool(left and right and (len(left & right) / len(left) >= .6
                # A publisher may use the subtitle while the catalogue keeps
                # its full release name, e.g. Sällskapsresan II – Snowroller.
                or (right.issubset(left) and (len(right) >= 2 or any(len(word) >= 6 for word in right)))))


def _season_number(text):
    match = re.search(r"(?i)(?:^|[^a-z0-9])(?:season|säsong|s)[ ._-]*(\d{1,2})(?![a-z0-9])", str(text or ""))
    return int(match[1]) if match else 0


def _provider_numbers(text, *, leading=False):
    season, episode, _, _ = library._episode_info(str(text or ""))
    if not episode:
        match = re.search(r"(?i)(?<![a-z0-9])(?:del|part)[ ._#-]*(\d{1,3})(?!\d)", str(text or ""))
        if not match and leading:
            match = re.match(r"\s*(\d{1,3})[ ._-]+[^\d\s]", str(text or ""))
        episode = int(match[1]) if match else 0
    return season, episode


def _label_languages(*values):
    aliases = {"sv": {"swedish", "svenska", "svensk", "svenskt", "swe"},
               "en": {"english", "engelska", "eng"}, "no": {"norwegian", "norsk", "nor"},
               "da": {"danish", "danska", "dan"}, "fi": {"finnish", "finska", "fin"},
               "de": {"german", "deutsch", "tyska", "ger", "deu"},
               "fr": {"french", "francais", "franska", "fra", "fre"},
               "es": {"spanish", "espanol", "spanska", "spa"}}
    words = set(_words(" ".join(str(value or "") for value in values)))
    return {code for code, names in aliases.items() if words.intersection(names)}


def _number_field(metadata, *names):
    for name in names:
        value = str(metadata.get(name) or "").strip()
        if re.fullmatch(r"\d{1,3}", value) and int(value) > 0:
            return int(value)
    return 0


def _identity(status, scope, reason="", **evidence):
    return dict(status=status, scope=scope, reason=reason, **evidence)


def check_identity(row):
    """Check source/metadata correspondence; this is not whole-video semantics."""
    source = str(row.get("source") or "")
    parsed = urlsplit(source)
    if parsed.scheme in ("http", "https"):
        contract.stream_allowed(source)
    elif parsed.scheme == "file" or "://" not in source:
        from backend.platform_support import local_file_path
        contract.confined(local_file_path(source))
        return _identity("consistent", "confined_local_file")
    else:
        return _identity("failed", "source", "unsupported_source")
    identifier = str(row.get("archive_id") or "")
    if not identifier:
        # A live playlist's label is publisher-supplied. This deliberately
        # records a weaker identity scope than Archive file correspondence.
        if not str(row.get("title") or "").strip():
            return _identity("unknown", "catalogue_metadata", "missing_title")
        return _identity("consistent", "catalogue_metadata",
                         semantic_identity_verified=False)
    if not library._IDENTIFIER.fullmatch(identifier):
        return _identity("failed", "archive_metadata", "invalid_identifier")
    if parsed.scheme != "https" or parsed.netloc != "archive.org" or parsed.query or parsed.fragment:
        return _identity("failed", "archive_metadata", "source_mismatch")
    payload = library._cached_json("https://archive.org/metadata/" + quote(identifier, safe=""), library._valid_metadata)
    if library._restricted(payload):
        return _identity("failed", "archive_metadata", "restricted")
    metadata = payload["metadata"]
    if str(metadata.get("identifier") or "") != identifier:
        return _identity("failed", "archive_metadata", "identifier_mismatch")
    filename = str(row.get("archive_file") or "")
    descriptor = "/details/" in parsed.path and not filename
    entry = None
    if descriptor:
        if parsed.path.rstrip("/") != "/details/" + quote(identifier, safe=""):
            return _identity("failed", "archive_metadata", "source_mismatch")
    else:
        expected_path = "/download/" + quote(identifier, safe="") + "/" + quote(filename, safe="/")
        if not filename or parsed.path != expected_path:
            return _identity("failed", "archive_file", "source_mismatch")
        entry = next((entry for entry in payload["files"][:library.MAX_FILES]
                      if isinstance(entry, dict) and entry.get("name") == filename), None)
        if entry is None or not library._file_allowed(entry):
            return _identity("failed", "archive_file", "file_missing_or_disallowed")
    corrections, reason = {}, ""
    expected = row.get("series_title") if row.get("content_type") in ("series", "episode") else row.get("title")
    expected = expected or row.get("title")
    if not _words(expected) and _title_matches(row.get("title"), metadata.get("title")):
        expected = row["title"]
        corrections["series_title"] = re.sub(r"(?i)^\W*s\d+[ ._-]*e\d+\W*", "", expected).strip() or expected
        reason = "unusable_series_label"
    actual = " ".join(str(value or "") for value in (metadata.get("title"), (entry or {}).get("title"), filename))
    if (not any(_title_matches(expected, value) for value in (metadata.get("title"), actual))
            or (row.get("archive_title") and not _title_matches(row["archive_title"], metadata.get("title")))):
        return _identity("unknown", "archive_metadata", "title_mismatch")
    if row.get("content_type") == "movie" and re.search(r"(?i)\b(?:trailer|teaser|preview|sample)\b", str(metadata.get("title") or "")):
        return _identity("failed", "archive_metadata", "preview_not_programme")
    language = set(library._language(row.get("language")).split("; ")) - {""}
    provider_language = set(library._language(metadata.get("language")).split("; ")) - {""}
    file_language = set(library._language((entry or {}).get("language")).split("; ")) - {""}
    language_evidence = (file_language or _label_languages(filename, (entry or {}).get("title"))
                         or provider_language or _label_languages(metadata.get("title")))
    if language and language_evidence and not language.intersection(language_evidence):
        return _identity("failed", "archive_metadata", "language_mismatch")
    if language and not language_evidence:
        corrections["language"] = ""
        reason = reason or "language_unconfirmed"
    if descriptor:
        if corrections:
            return _identity("unknown", "archive_descriptor", reason, metadata_corrections=corrections)
        return _identity("consistent", "archive_descriptor", title_match=True,
                         language_consistent=True, semantic_identity_verified=False)
    # Missing provider size metadata is not proof that a real media object is
    # absent. The subsequent bounded decoder check proves its actual bytes.
    file_size_confirmed = int(entry.get("size") or 0) > 0
    season, episode = _provider_numbers(filename)
    entry_season, entry_episode = _provider_numbers(entry.get("title"))
    provider_season, provider_episode = _provider_numbers(metadata.get("title"), leading=True)
    # File/entry numbering is strongest; an episode-specific Archive item's
    # own metadata can supply numbering when the filename is generic. A bare
    # curated link is not evidence of a season/episode mapping.
    episode = episode or entry_episode or provider_episode or _number_field(metadata, "episode", "episode_number")
    season = (season or entry_season or _season_number(filename) or _season_number(entry.get("title"))
              or provider_season or _season_number(metadata.get("title"))
              or _number_field(metadata, "season", "season_number"))
    expected_episode, expected_season = int(row.get("episode") or 0), int(row.get("season") or 0)
    if episode and expected_episode and expected_episode != episode:
        return _identity("failed", "archive_file", "episode_mismatch")
    if season and expected_season and expected_season != season:
        return _identity("failed", "archive_file", "season_mismatch")
    if expected_episode and not episode:
        corrections["episode"] = 0
        reason = reason or "missing_episode_evidence"
    if expected_season and not season:
        corrections["season"] = 0
        reason = reason or "missing_season_evidence"
    if "season" in corrections or "episode" in corrections:
        # Keep a playable source under the exact provider file label instead
        # of advertising invented season/episode numbers in its display title.
        label = library._label(Path(filename).stem)[:180]
        corrections.update(title=label, episode_title=label)
    if corrections:
        return _identity("unknown", "archive_file", reason, metadata_corrections=corrections)
    return _identity("consistent", "archive_file", title_match=True, language_consistent=True,
                     episode_consistent=True if expected_episode else None,
                     season_consistent=True if expected_season else None,
                     file_size_confirmed=file_size_confirmed,
                     semantic_identity_verified=False)


def prepare_identity(row):
    """Normalize unsupported labels, then check the truthful source identity.

    A missing metadata field does not mean a video is broken. It does mean the
    catalogue must stop claiming that field. This function never persists or
    transfers a playback proof; callers atomically save corrections and decode
    the corrected identity before admitting it.
    """
    candidate, reasons = dict(row), []
    for _ in range(3):
        identity = check_identity(candidate)
        updates = identity.get("metadata_corrections") or {}
        if identity["status"] != "unknown" or not updates:
            if reasons:
                identity = dict(identity, metadata_normalized=True, corrected_fields=sorted({
                    key for key in candidate if candidate.get(key) != row.get(key)}))
            return candidate, identity
        reasons.append(identity["reason"])
        candidate = library.annotate(dict(candidate, **updates))
    return candidate, check_identity(candidate)


def _safe_report(report):
    """Retain audit evidence without copying signed/source URLs into reports."""
    result = {}
    for key in ("schema", "status", "checked_at", "expires_at", "ttl_seconds", "elapsed_seconds", "downloaded_bytes",
                "max_seconds", "max_bytes", "requests"):
        value = report.get(key)
        if isinstance(value, (str, bool, int, float)) and (not isinstance(value, float) or math.isfinite(value)):
            result[key] = value
    error = str(report.get("error") or "")
    result["error"] = error if re.fullmatch(r"[a-z0-9_]{0,80}", error) else "check_inconclusive"
    evidence = {}
    for key, value in (report.get("evidence") or {}).items():
        if isinstance(value, (int, float, bool)) and (not isinstance(value, float) or math.isfinite(value)):
            evidence[str(key)[:80]] = value
        elif isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_. -]{0,80}", value):
            evidence[str(key)[:80]] = value
    result["evidence"] = evidence
    return result


def _decoded(report, row):
    if not availability.is_fresh_verified(report):
        return False
    evidence = report.get("evidence") or {}
    if row.get("content_type") == "music" or row.get("kind") in ("MUSIC", "RADIO"):
        return int(evidence.get("audio_frames") or 0) > 0
    return (int(evidence.get("video_frames") or 0) > 0
            and (not evidence.get("audio_stream") or int(evidence.get("audio_frames") or 0) > 0))


class MediaHealthAudit:
    def __init__(self, index=None):
        self.index = index or MediaIndex()
        self._provider_lock = threading.Lock()
        self._provider_slots = {}
        self._database_gate = threading.RLock()

    @contextmanager
    def _connection(self):
        # Network/decode workers may run concurrently; short SQLite writes
        # must not contend with sixteen connections and silently stop the run.
        with self._database_gate:
            with self.index.connection() as db:
                yield db

    def initialize(self):
        self.index.initialize()
        with self._connection() as db:
            db.executescript("""
              CREATE TABLE IF NOT EXISTS media_audit_runs (
                id INTEGER PRIMARY KEY, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                status TEXT NOT NULL, force INTEGER NOT NULL, owner TEXT NOT NULL DEFAULT '',
                lease_until REAL NOT NULL DEFAULT 0, cancel_requested INTEGER NOT NULL DEFAULT 0,
                snapshot_items INTEGER NOT NULL DEFAULT 0, expanded_sources INTEGER NOT NULL DEFAULT 0,
                audit_policy TEXT NOT NULL DEFAULT '');
              CREATE TABLE IF NOT EXISTS media_audit_jobs (
                run_id INTEGER NOT NULL, source_key TEXT NOT NULL, payload TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'queued', priority INTEGER NOT NULL DEFAULT 20,
                attempts INTEGER NOT NULL DEFAULT 0, lease_until REAL NOT NULL DEFAULT 0,
                checked_at REAL NOT NULL DEFAULT 0, report TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY(run_id,source_key));
              CREATE INDEX IF NOT EXISTS media_audit_queue ON media_audit_jobs(run_id,state,priority);
              CREATE TABLE IF NOT EXISTS media_audit_members (
                run_id INTEGER NOT NULL, source_key TEXT NOT NULL, item_id TEXT NOT NULL,
                payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued', identity_report TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY(run_id,source_key,item_id));
              CREATE TABLE IF NOT EXISTS media_audit_groups (
                run_id INTEGER NOT NULL, lane TEXT NOT NULL, coverage_key TEXT NOT NULL,
                sampled INTEGER NOT NULL DEFAULT 0, last_claimed REAL NOT NULL DEFAULT 0,
                PRIMARY KEY(run_id,lane,coverage_key));
            """)
            job_columns = {row[1] for row in db.execute("PRAGMA table_info(media_audit_jobs)")}
            for column in ("lane", "coverage_key"):
                if column not in job_columns:
                    db.execute("ALTER TABLE media_audit_jobs ADD COLUMN " + column + " TEXT NOT NULL DEFAULT ''")
            if "descriptor" not in job_columns:
                db.execute("ALTER TABLE media_audit_jobs ADD COLUMN descriptor INTEGER NOT NULL DEFAULT 0")
                db.execute("UPDATE media_audit_jobs SET descriptor=CASE "
                           "WHEN COALESCE(json_extract(payload,'$.archive_file'),'')='' "
                           "AND instr(json_extract(payload,'$.source'),'/details/')>0 THEN 1 ELSE 0 END")
            # A local, once-only queue migration. Existing successes stay intact.
            for row in db.execute("SELECT run_id,source_key,payload,state FROM media_audit_jobs WHERE lane='' ").fetchall():
                lane, group = _queue_group(json.loads(row[2]))
                db.execute("UPDATE media_audit_jobs SET lane=?,coverage_key=? WHERE run_id=? AND source_key=?",
                           (lane, group, row[0], row[1]))
                db.execute("INSERT INTO media_audit_groups(run_id,lane,coverage_key,sampled) VALUES(?,?,?,?) "
                           "ON CONFLICT(run_id,lane,coverage_key) DO UPDATE SET sampled=MAX(sampled,excluded.sampled)",
                           (row[0], lane, group, int(row[3] in ("healthy", "failed", "unknown"))))
            db.execute("CREATE INDEX IF NOT EXISTS media_audit_lanes ON media_audit_jobs(run_id,state,lane,coverage_key)")
            columns = {row[1] for row in db.execute("PRAGMA table_info(media_audit_runs)")}
            if "audit_policy" not in columns:
                db.execute("ALTER TABLE media_audit_runs ADD COLUMN audit_policy TEXT NOT NULL DEFAULT ''")
            if "last_worker_error" not in columns:
                db.execute("ALTER TABLE media_audit_runs ADD COLUMN last_worker_error TEXT NOT NULL DEFAULT ''")
            if "lanes" not in columns:
                db.execute("ALTER TABLE media_audit_runs ADD COLUMN lanes TEXT NOT NULL DEFAULT '[]'")
            legacy = db.execute("SELECT id,owner,lease_until FROM media_audit_runs WHERE audit_policy<>?",
                                (AUDIT_POLICY,)).fetchall()
            for run in legacy:
                if run[1] and run[2] > time.time():
                    # Ask a still-running previous checker to yield before
                    # changing ownership or resetting its completed jobs.
                    db.execute("UPDATE media_audit_runs SET cancel_requested=1 WHERE id=?", (run[0],))
                    continue
                revoked = db.execute("""UPDATE items SET status='unknown',checked_at=0,verified_until=0,retry_at=0
                    WHERE status='verified' AND EXISTS (
                      SELECT 1 FROM media_audit_members m JOIN media_audit_jobs j
                        ON j.run_id=m.run_id AND j.source_key=m.source_key
                      WHERE m.run_id=? AND j.state='healthy' AND m.state='healthy'
                        AND m.item_id=items.id AND j.source_key=items.source_key
                        AND items.checked_at<=j.checked_at)""", (run[0],))
                if revoked.rowcount:
                    self.index._changed(db, structural=True, withdrawn=True)
                db.execute("UPDATE media_audit_members SET state='queued',identity_report='{}' "
                           "WHERE run_id=? AND state='healthy'", (run[0],))
                requeued = db.execute("UPDATE media_audit_jobs SET state='queued',report='{}',checked_at=0,lease_until=0 "
                                      "WHERE run_id=? AND state='healthy'", (run[0],)).rowcount
                db.execute("UPDATE media_audit_runs SET audit_policy=?,owner='',lease_until=0,"
                           "status=CASE WHEN ? THEN 'paused' ELSE status END,updated_at=? WHERE id=?",
                           (AUDIT_POLICY, requeued, time.time(), run[0]))

    def _enqueue(self, db, run_id, rows):
        added = 0
        for row in rows:
            source = str(row.get("source") or "")
            if not source or row.get("kind") not in ("TV", "FETCH") or row.get("content_type") not in ("movie", "series", "episode", "live"):
                continue
            key = _hash(source)
            lane, group = _queue_group(row)
            priority = (0 if "sv" in str(row.get("language") or "").split("; ") else
                        30 if "/details/" in source else 20 if row.get("content_type") == "live" else 10)
            payload = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
            result = db.execute("INSERT OR IGNORE INTO media_audit_jobs(run_id,source_key,payload,priority,lane,coverage_key,descriptor) VALUES(?,?,?,?,?,?,?)",
                                (run_id, key, payload, priority, lane, group, _is_descriptor(row)))
            added += result.rowcount
            db.execute("INSERT OR IGNORE INTO media_audit_groups(run_id,lane,coverage_key) VALUES(?,?,?)",
                       (run_id, lane, group))
            member = db.execute("INSERT OR IGNORE INTO media_audit_members(run_id,source_key,item_id,payload) VALUES(?,?,?,?)",
                                (run_id, key, str(row["id"]), payload))
            if member.rowcount and not result.rowcount:
                # A newly discovered label still needs its own identity check,
                # even when another label already decoded the same URL.
                db.execute("UPDATE media_audit_jobs SET state='queued',lease_until=0 "
                           "WHERE run_id=? AND source_key=? AND state<>'running'", (run_id, key))
        return added

    def include(self, run_id=None):
        """Explicitly extend the saved finite run with the current local index.

        This never discovers or opens external sources. It is separate from
        ordinary resume/browsing, which retain the original snapshot boundary.
        Existing members and successful proofs are not overwritten.
        """
        self.initialize()
        run_id = self._latest(run_id)
        added_sources, added_members = 0, 0
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            run = db.execute("SELECT owner,lease_until FROM media_audit_runs WHERE id=?", (run_id,)).fetchone()
            if run[0] and run[1] > time.time():
                raise RuntimeError("MEDIA_AUDIT_RUNNING")
            before = db.execute("SELECT COUNT(*) FROM media_audit_members WHERE run_id=?", (run_id,)).fetchone()[0]
            cursor = db.execute("SELECT payload FROM items WHERE kind IN ('TV','FETCH') AND type IN ('movie','episode','series','live')")
            while records := cursor.fetchmany(200):
                added_sources += self._enqueue(db, run_id, [json.loads(row[0]) for row in records])
            after = db.execute("SELECT COUNT(*) FROM media_audit_members WHERE run_id=?", (run_id,)).fetchone()[0]
            added_members = after - before
            if added_members:
                db.execute("UPDATE media_audit_runs SET snapshot_items=snapshot_items+?,status='paused',updated_at=? WHERE id=?",
                           (added_members, time.time(), run_id))
        return dict(self.status(run_id), included_sources=added_sources, included_members=added_members)

    def repair(self, run_id=None, *, initial_retry=False):
        """Reconcile this finite snapshot after metadata/probe fixes, without I/O.

        Changed identities are checked anew; a former decoded URL never certifies
        a new label. Transient failures get at most one extra attempt per run.
        ``initial_retry`` is reserved for explicit desktop Refresh of its own
        initial run and grants exhausted transient sources a new finite pair.
        No unrelated newly discovered inventory is pulled into this snapshot.
        """
        self.initialize()
        run_id = self._latest(run_id)
        repaired, retried = set(), set()
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if initial_retry:
                marker = db.execute("SELECT value FROM meta WHERE key='starter_audit_run'").fetchone()
                latest = db.execute("SELECT MAX(id) FROM media_audit_runs").fetchone()[0]
                if not marker or marker[0] != str(run_id) or latest != run_id:
                    raise RuntimeError("MEDIA_INITIAL_AUDIT_SCOPE")
            run = db.execute("SELECT owner,lease_until FROM media_audit_runs WHERE id=?", (run_id,)).fetchone()
            if run[0] and run[1] > time.time():
                raise RuntimeError("MEDIA_AUDIT_RUNNING")
            members = db.execute("""SELECT m.source_key,m.item_id,m.payload,i.payload,j.state,j.attempts
                FROM media_audit_members m JOIN media_audit_jobs j
                  ON j.run_id=m.run_id AND j.source_key=m.source_key
                LEFT JOIN items i ON i.id=m.item_id WHERE m.run_id=? AND m.state<>'superseded'""", (run_id,)).fetchall()
            for member in members:
                if not member[3]:
                    continue
                old, current = json.loads(member[2]), json.loads(member[3])
                if (_hash(current.get("source")) == member[0]
                        and self.index.identity_key(current) == self.index.identity_key(old)):
                    continue
                new_key = _hash(current.get("source"))
                self._enqueue(db, run_id, [current])
                encoded = json.dumps(current, ensure_ascii=False, separators=(",", ":"))
                db.execute("UPDATE media_audit_members SET payload=?,state='queued',identity_report='{}' "
                           "WHERE run_id=? AND source_key=? AND item_id=?", (encoded, run_id, new_key, member[1]))
                lane, group = _queue_group(current)
                db.execute("UPDATE media_audit_jobs SET payload=?,state='queued',report='{}',checked_at=0,"
                           "lane=?,coverage_key=?,descriptor=?,lease_until=0 WHERE run_id=? AND source_key=?",
                           (encoded, lane, group, _is_descriptor(current), run_id, new_key))
                if new_key != member[0]:
                    db.execute("UPDATE media_audit_members SET state='superseded' "
                               "WHERE run_id=? AND source_key=? AND item_id=?", (run_id, member[0], member[1]))
                    remaining = db.execute("SELECT COUNT(*) FROM media_audit_members "
                                           "WHERE run_id=? AND source_key=? AND state<>'superseded'",
                                           (run_id, member[0])).fetchone()[0]
                    if not remaining:
                        db.execute("UPDATE media_audit_jobs SET state='changed',lease_until=0 "
                                   "WHERE run_id=? AND source_key=?", (run_id, member[0]))
                repaired.add(new_key)
            for job in db.execute("SELECT source_key,report,attempts FROM media_audit_jobs "
                                  "WHERE run_id=? AND state IN ('unknown','failed')", (run_id,)).fetchall():
                retryable = json.loads(job[1]).get("error") in RETRYABLE_ERRORS
                if job[2] >= 2 and not (initial_retry and retryable):
                    continue
                correctable = any(json.loads(row[0]).get("reason") in CORRECTABLE_IDENTITY_REASONS
                                  for row in db.execute("SELECT identity_report FROM media_audit_members "
                                                        "WHERE run_id=? AND source_key=?", (run_id, job[0])))
                if retryable or correctable:
                    # Only an explicit refresh of the app-owned initial run
                    # grants exhausted transient sources another finite pair
                    # of attempts. Opening a pane and ordinary repair do not.
                    attempts = 0 if initial_retry and retryable and job[2] >= 2 else job[2]
                    db.execute("UPDATE media_audit_jobs SET state='queued',report='{}',lease_until=0,attempts=? "
                               "WHERE run_id=? AND source_key=?", (attempts, run_id, job[0]))
                    retried.add(job[0])
            # The former short VOD profile rejected real playable films.
            # Give those terminal old-budget failures one check under the new
            # bounded profile. Its saved limits prevent repeated migration.
            for job in db.execute("SELECT source_key FROM media_audit_jobs WHERE run_id=? AND state='unknown' "
                    "AND lane IN ('movies','series') AND json_extract(report,'$.error') IN ('timeout','byte_limit','no_decoded_frames') "
                    "AND COALESCE(json_extract(report,'$.max_bytes'),0)<?", (run_id, availability.MAX_CHECK_BYTES)).fetchall():
                db.execute("UPDATE media_audit_jobs SET state='queued',attempts=1,priority=-100,lease_until=0 "
                           "WHERE run_id=? AND source_key=?", (run_id, job[0]))
                retried.add(job[0])
            for job in db.execute("SELECT source_key FROM media_audit_jobs WHERE run_id=? AND state='expanded' "
                    "AND COALESCE(json_extract(report,'$.evidence.encoding_groups_version'),0)<?",
                    (run_id, library.ENCODING_GROUPS_VERSION)).fetchall():
                db.execute("UPDATE media_audit_jobs SET state='queued',priority=-100,lease_until=0 "
                           "WHERE run_id=? AND source_key=?", (run_id, job[0]))
                retried.add(job[0])
            if repaired or retried:
                for key in repaired | retried:
                    db.execute("UPDATE media_audit_jobs SET priority=-100 WHERE run_id=? AND source_key=?", (run_id, key))
                    db.execute("""UPDATE media_audit_groups SET sampled=0,last_claimed=0 WHERE run_id=?
                        AND (lane,coverage_key) IN (SELECT lane,coverage_key FROM media_audit_jobs
                          WHERE run_id=? AND source_key=?)""", (run_id, run_id, key))
                db.execute("UPDATE media_audit_runs SET status='paused',updated_at=? WHERE id=?", (time.time(), run_id))
        return dict(self.status(run_id), repaired_sources=len(repaired), retried_sources=len(retried))

    def start(self, *, force=True, initial=False):
        """Create a fixed snapshot, or resume the existing unfinished snapshot."""
        self.initialize()
        now = time.time()
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if initial and db.execute("SELECT 1 FROM media_audit_runs LIMIT 1").fetchone():
                # A first-install helper must never adopt an existing manual
                # run, including a stopped run or one created concurrently.
                return None
            pending = db.execute("SELECT id FROM media_audit_runs WHERE status IN ('ready','running','paused') ORDER BY id DESC LIMIT 1").fetchone()
            if pending:
                return int(pending[0])
            cursor = db.execute("INSERT INTO media_audit_runs(created_at,updated_at,status,force,audit_policy) VALUES(?,?,'ready',?,?)",
                                (now, now, int(force), AUDIT_POLICY))
            run_id = int(cursor.lastrowid)
            if initial:
                db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('starter_audit_run',?)", (str(run_id),))
            snapshot_items = 0
            cursor = db.execute("SELECT payload FROM items WHERE kind IN ('TV','FETCH') AND type IN ('movie','episode','series','live')")
            while records := cursor.fetchmany(200):
                rows = [json.loads(record[0]) for record in records]
                snapshot_items += sum(bool(row.get("source")) for row in rows)
                self._enqueue(db, run_id, rows)
            db.execute("UPDATE media_audit_runs SET snapshot_items=? WHERE id=?", (snapshot_items, run_id))
        return run_id

    def _latest(self, run_id=None):
        with self._connection() as db:
            row = db.execute("SELECT id FROM media_audit_runs " + ("WHERE id=?" if run_id else "ORDER BY id DESC LIMIT 1"),
                             (int(run_id),) if run_id else ()).fetchone()
        if row is None:
            raise ValueError("MEDIA_AUDIT_NOT_FOUND")
        return int(row[0])

    def status(self, run_id=None):
        self.initialize()
        try:
            run_id = self._latest(run_id)
        except ValueError:
            return dict(schema=SCHEMA, status="not_started", total=0, done=0, healthy=0, failed=0, unknown=0, pending=0)
        with self._connection() as db:
            run = db.execute("SELECT status,snapshot_items,expanded_sources,updated_at,cancel_requested,last_worker_error,lanes FROM media_audit_runs WHERE id=?", (run_id,)).fetchone()
            counts = {row[0]: row[1] for row in db.execute("SELECT state,COUNT(*) FROM media_audit_jobs WHERE run_id=? GROUP BY state", (run_id,))}
            lanes = tuple(lane for lane in json.loads(run[6] or "[]") if lane in LANES) or LANES
            focused = dict(db.execute("SELECT state,COUNT(*) FROM media_audit_jobs WHERE run_id=? AND lane IN (" +
                ",".join("?" for _ in lanes) + ") GROUP BY state", [run_id, *lanes]))
        total = sum(counts.values())
        done = sum(counts.get(state, 0) for state in TERMINAL)
        return dict(schema=SCHEMA, status=run[0], total=total, done=done, healthy=counts.get("healthy", 0),
                    failed=counts.get("failed", 0), unknown=counts.get("unknown", 0), changed=counts.get("changed", 0),
                    expanded=counts.get("expanded", 0), pending=counts.get("queued", 0), running=counts.get("running", 0),
                    snapshot_items=run[1], expanded_sources=run[2], updated_at=run[3], cancel_requested=bool(run[4]),
                    last_worker_error=run[5], active_lanes=list(lanes), focus_total=sum(focused.values()),
                    focus_done=sum(focused.get(state, 0) for state in TERMINAL))

    def stop(self, run_id=None):
        self.initialize()
        run_id = self._latest(run_id)
        with self._connection() as db:
            db.execute("UPDATE media_audit_runs SET cancel_requested=1,updated_at=? WHERE id=?", (time.time(), run_id))
        return self.status(run_id)

    def _claim(self, run_id, lane=None):
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            # First sample each title/series before spending the whole run on
            # hundreds of episodes of one show. Expanded descriptors keep their
            # group unsampled until one actual child has been checked.
            row = db.execute("""SELECT j.source_key,j.payload,j.lane,j.coverage_key
                FROM media_audit_jobs j JOIN media_audit_groups g
                  ON g.run_id=j.run_id AND g.lane=j.lane AND g.coverage_key=j.coverage_key
                WHERE j.run_id=? AND j.state='queued'""" + (" AND j.lane=?" if lane else "") +
                " ORDER BY CASE WHEN j.priority<0 THEN 0 ELSE 1 END,g.sampled,j.descriptor,"
                "g.last_claimed,j.priority,j.source_key LIMIT 1",
                (run_id, lane) if lane else (run_id,)).fetchone()
            if row is None:
                return None
            db.execute("UPDATE media_audit_jobs SET state='running',attempts=attempts+1,lease_until=? WHERE run_id=? AND source_key=?",
                       (time.time() + 180, run_id, row[0]))
            db.execute("UPDATE media_audit_groups SET last_claimed=? WHERE run_id=? AND lane=? AND coverage_key=?",
                       (time.time(), run_id, row[2], row[3]))
        return row[0], json.loads(row[1])

    def _members(self, run_id, key):
        with self._connection() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT payload FROM media_audit_members WHERE run_id=? AND source_key=?", (run_id, key))]

    def _current(self, row, key):
        current = self.index.get(str(row["id"]))
        return current if (current and _hash(current.get("source")) == key
                           and self.index.identity_key(current) == self.index.identity_key(row)) else None

    def _finish(self, run_id, key, state, report):
        with self._connection() as db:
            db.execute("UPDATE media_audit_jobs SET state=?,report=?,checked_at=?,lease_until=0 WHERE run_id=? AND source_key=?",
                       (state, json.dumps(_safe_report(report), separators=(",", ":")), time.time(), run_id, key))
            db.execute("UPDATE media_audit_runs SET updated_at=? WHERE id=?", (time.time(), run_id))
            if state in ("healthy", "failed", "unknown"):
                db.execute("""UPDATE media_audit_groups SET sampled=1 WHERE run_id=? AND (lane,coverage_key) IN
                    (SELECT lane,coverage_key FROM media_audit_jobs WHERE run_id=? AND source_key=?)""",
                    (run_id, run_id, key))
            if state == "unknown" and report.get("error") in RETRYABLE_ERRORS:
                # One later retry, behind untouched title groups. This is a
                # finite pass over saved sources, never an open-ended monitor.
                db.execute("UPDATE media_audit_jobs SET state='queued',priority=priority+1000 "
                           "WHERE run_id=? AND source_key=? AND attempts<2", (run_id, key))
            if state == "healthy" and (report.get("evidence") or {}).get("retryable_contexts", 0):
                db.execute("UPDATE media_audit_jobs SET state='queued',priority=priority+1000 "
                           "WHERE run_id=? AND source_key=? AND attempts<2", (run_id, key))
            if state in ("healthy", "failed", "expanded") or (state == "unknown" and report.get("error") != "worker_exception"):
                # Descriptor expansion may add a same-URL member while this
                # worker is decoding the previous member list. Check that new
                # identity in a later finite turn before declaring the URL done.
                db.execute("UPDATE media_audit_jobs SET state='queued',lease_until=0 WHERE run_id=? AND source_key=? "
                           "AND EXISTS(SELECT 1 FROM media_audit_members m WHERE m.run_id=? AND m.source_key=? AND m.state='queued')",
                           (run_id, key, run_id, key))

    def _member_result(self, run_id, key, row, state, identity, report=None):
        with self._database_gate:
            return self._record_member_result(run_id, key, row, state, identity, report)

    def _record_member_result(self, run_id, key, row, state, identity, report=None):
        current = self._current(row, key)
        if current is None:
            state = "changed"
        elif report is not None:
            self.index.record(str(row["id"]), report, source=row["source"], identity=self.index.identity_key(row))
            if self._current(row, key) is None:
                state = "changed"
        with self._connection() as db:
            db.execute("UPDATE media_audit_members SET state=?,identity_report=? WHERE run_id=? AND source_key=? AND item_id=?",
                       (state, json.dumps(identity, separators=(",", ":")), run_id, key, str(row["id"])))
        return state

    def _process(self, run_id, key, snapshot, cancelled):
        members = self._members(run_id, key)
        consistent = []
        for row in members:
            if cancelled.is_set():
                return self._finish(run_id, key, "queued", {})
            if self._current(row, key) is None:
                self._member_result(run_id, key, row, "changed", _identity("unknown", "source", "source_changed"))
                continue
            try:
                prepared, identity = prepare_identity(row)
                if identity["status"] == "consistent" and self.index.identity_key(prepared) != self.index.identity_key(row):
                    with self._database_gate:
                        prepared = self.index.correct_metadata(prepared, expected=row)
                        encoded = json.dumps(prepared, ensure_ascii=False, separators=(",", ":"))
                        with self._connection() as db:
                            db.execute("UPDATE media_audit_members SET payload=? "
                                       "WHERE run_id=? AND source_key=? AND item_id=?",
                                       (encoded, run_id, key, str(row["id"])))
                            db.execute("UPDATE media_audit_jobs SET payload=? WHERE run_id=? AND source_key=? "
                                       "AND json_extract(payload,'$.id')=?", (encoded, run_id, key, str(row["id"])))
                    row = prepared
            except (OSError, ValueError, RuntimeError, TimeoutError) as error:
                retryable = isinstance(error, OSError) or str(error) == "MEDIA_ARCHIVE_UNAVAILABLE"
                identity = _identity("unknown", "source_metadata", "identity_inconclusive", retryable=retryable)
            if cancelled.is_set():
                return self._finish(run_id, key, "queued", {})
            if identity["status"] == "consistent":
                consistent.append((row, identity))
            else:
                report = dict(status="failed" if identity["status"] == "failed" else "unknown",
                              checked_at=time.time(), error=identity["reason"], evidence={"decoded": False})
                self._member_result(run_id, key, row, report["status"], identity, report)
        if not consistent:
            with self._connection() as db:
                states = [row[0] for row in db.execute("SELECT state FROM media_audit_members WHERE run_id=? AND source_key=?", (run_id, key))]
                retryable = any(json.loads(row[0]).get("retryable") for row in db.execute(
                    "SELECT identity_report FROM media_audit_members WHERE run_id=? AND source_key=?", (run_id, key)))
            state = "changed" if states and all(s == "changed" for s in states) else "failed" if "failed" in states else "unknown"
            return self._finish(run_id, key, state, dict(status=state,
                error="metadata_unavailable" if retryable else "identity_not_confirmed"))
        first, identity = consistent[0]
        if identity["scope"] == "archive_descriptor":
            try:
                children = library.expand_item(first)
                if cancelled.is_set():
                    return self._finish(run_id, key, "queued", {})
                if self._current(first, key) is None:
                    for row, evidence in consistent:
                        self._member_result(run_id, key, row, "changed", evidence)
                    return self._finish(run_id, key, "changed", dict(status="unknown", error="source_identity_changed"))
                if not children:
                    raise ValueError("empty_archive")
                if first.get("content_type") == "series":
                    collection = first.get("collection_key") or self.index.series_key(first)
                    children = [dict(child, collection_key=collection,
                                     series_title=first.get("series_title") or first["title"]) for child in children]
                with self._database_gate:
                    children = self.index.ingest_discovered(children, expected={str(first["id"]): first})
                with self._connection() as db:
                    added = self._enqueue(db, run_id, children)
                    db.execute("UPDATE media_audit_runs SET expanded_sources=expanded_sources+? WHERE id=?", (added, run_id))
                for row, evidence in consistent:
                    self._member_result(run_id, key, row, "expanded", evidence)
                return self._finish(run_id, key, "expanded", dict(status="expanded", evidence={"child_sources": added,
                    "encoding_groups_version": library.ENCODING_GROUPS_VERSION}))
            except (OSError, ValueError, RuntimeError, TimeoutError) as error:
                if str(error) == "MEDIA_SOURCE_CHANGED":
                    for row, evidence in consistent:
                        self._member_result(run_id, key, row, "changed", evidence)
                    return self._finish(run_id, key, "changed", dict(status="unknown", error="source_changed"))
                retryable = isinstance(error, OSError) or str(error) == "MEDIA_ARCHIVE_UNAVAILABLE"
                report = dict(status="unknown", checked_at=time.time(),
                              error="metadata_unavailable" if retryable else "metadata_expansion_inconclusive")
                for row, evidence in consistent:
                    self._member_result(run_id, key, row, "unknown", evidence, report)
                return self._finish(run_id, key, "unknown", report)
        from backend.media_request import public_headers
        contexts, outcomes = {}, []
        for row, evidence in consistent:
            try:
                # Omitted hints and explicitly supplied defaults are the same
                # request context. A different published Referer or UA needs
                # its own proof, even when the media URL is identical.
                context = json.dumps(public_headers(row), sort_keys=True, separators=(",", ":"))
            except ValueError:
                report = dict(status="unknown", checked_at=time.time(), error="invalid_request_context", evidence={"decoded": False})
                state = self._member_result(run_id, key, row, "unknown", evidence, report)
                outcomes.append((state, report))
                continue
            contexts.setdefault(context, []).append((row, evidence))
        for grouped in contexts.values():
            if cancelled.is_set():
                return self._finish(run_id, key, "queued", {})
            checked_row = grouped[0][0]
            profile = ({"max_seconds": availability.MAX_CHECK_SECONDS, "max_bytes": availability.MAX_CHECK_BYTES}
                       if checked_row.get("content_type") in ("movie", "episode") else {})
            report = availability.verify(checked_row, cancel=cancelled, **profile)
            if cancelled.is_set():
                return self._finish(run_id, key, "queued", {})
            if report.get("status") == "verified" and not _decoded(report, checked_row):
                report = dict(status="unknown", checked_at=time.time(), error="decoded_proof_missing", evidence={"decoded": False})
            state = "healthy" if report.get("status") == "verified" else "failed" if report.get("status") == "failed" else "unknown"
            states = [self._member_result(run_id, key, row, state, evidence, report) for row, evidence in grouped]
            if all(member == "changed" for member in states):
                state, report = "changed", dict(status="unknown", checked_at=time.time(), error="source_changed")
            outcomes.append((state, report))
        state = next((value for value in ("healthy", "unknown", "failed", "changed")
                      if any(outcome == value for outcome, _ in outcomes)), "unknown")
        selected = next((report for outcome, report in outcomes if outcome == state), {})
        report = dict(selected, evidence=dict(selected.get("evidence") or {}))
        report["evidence"].update(request_contexts=len(outcomes),
            healthy_contexts=sum(outcome == "healthy" for outcome, _ in outcomes),
            failed_contexts=sum(outcome == "failed" for outcome, _ in outcomes),
            unknown_contexts=sum(outcome == "unknown" for outcome, _ in outcomes),
            changed_contexts=sum(outcome == "changed" for outcome, _ in outcomes),
            retryable_contexts=sum(outcome == "unknown" and value.get("error") in RETRYABLE_ERRORS
                                   for outcome, value in outcomes))
        return self._finish(run_id, key, state, report)

    def _process_bounded(self, run_id, key, snapshot, cancelled):
        hostname = str(urlsplit(snapshot.get("source") or "").hostname or "local").casefold()
        provider = "archive.org" if hostname == "archive.org" or hostname.endswith(".archive.org") else hostname
        with self._provider_lock:
            slots = self._provider_slots.setdefault(provider, threading.BoundedSemaphore(ARCHIVE_PROVIDER_SLOTS if provider == "archive.org" else 2))
        while not slots.acquire(timeout=.1):
            if cancelled.is_set():
                return self._finish(run_id, key, "queued", {})
        try:
            if cancelled.is_set():
                return self._finish(run_id, key, "queued", {})
            return self._process(run_id, key, snapshot, cancelled)
        finally:
            slots.release()

    def run(self, run_id=None, *, workers=2, max_seconds=300, max_jobs=1000, cancel=None, lanes=None):
        selected_lanes = tuple(dict.fromkeys(lanes if lanes is not None else LANES))
        if not selected_lanes or any(lane not in LANES for lane in selected_lanes):
            raise ValueError("MEDIA_AUDIT_LANES_INVALID")
        self.initialize()
        run_id = self._latest(run_id)
        workers = max(1, min(MAX_WORKERS, int(workers)))
        max_jobs = max(1, min(1000000, int(max_jobs)))
        max_seconds = max(.1, min(12 * 3600, float(max_seconds)))
        owner, now = uuid.uuid4().hex, time.time()
        cancelled = threading.Event()
        unavailable = False
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            run = db.execute("SELECT owner,lease_until,status,audit_policy FROM media_audit_runs WHERE id=?", (run_id,)).fetchone()
            if run[0] and run[1] > now:
                unavailable = True
            elif run[2] == "complete" or run[3] != AUDIT_POLICY:
                unavailable = True
            else:
                db.execute("UPDATE media_audit_runs SET owner=?,lease_until=?,status='running',cancel_requested=0,"
                           "last_worker_error='',lanes=? WHERE id=?", (owner, now + 60, json.dumps(selected_lanes), run_id))
                db.execute("UPDATE media_audit_jobs SET state='queued',lease_until=0 WHERE run_id=? AND state='running'", (run_id,))
        if unavailable:
            return self.status(run_id)
        deadline = time.monotonic() + max_seconds
        claimed, futures, lane_cursor = 0, {}, 0
        lane_cap = max(1, math.ceil(workers / len(selected_lanes)))
        try:
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="gg-media-audit") as pool:
                while True:
                    with self._connection() as db:
                        stop = db.execute("SELECT cancel_requested FROM media_audit_runs WHERE id=?", (run_id,)).fetchone()[0]
                        db.execute("UPDATE media_audit_runs SET lease_until=?,updated_at=? WHERE id=? AND owner=?", (time.time() + 60, time.time(), run_id, owner))
                    if stop or _cancelled(cancel) or time.monotonic() >= deadline:
                        cancelled.set()
                    while not cancelled.is_set() and claimed < max_jobs and len(futures) < workers:
                        # Reserve scheduling turns for all three content kinds;
                        # old priority ordering starved eleven thousand channels.
                        job = None
                        for _ in selected_lanes:
                            lane = selected_lanes[lane_cursor % len(selected_lanes)]
                            lane_cursor += 1
                            if sum(active[0] == lane for active in futures.values()) >= lane_cap:
                                continue
                            job = self._claim(run_id, lane)
                            if job is not None:
                                break
                        if job is None:
                            break
                        claimed += 1
                        futures[pool.submit(self._process_bounded, run_id, *job, cancelled)] = (lane, job[0])
                    if not futures:
                        break
                    completed, _ = wait(futures, timeout=.15, return_when=FIRST_COMPLETED)
                    for future in completed:
                        _, job_key = futures.pop(future)
                        # Unexpected failures preserve a checkpoint for the
                        # next slice rather than falsely completing a source.
                        try:
                            future.result()
                        except Exception as error:
                            # Retain a sanitized diagnosis instead of silently
                            # pausing a forty-thousand-source run.
                            name = type(error).__name__
                            sqlite_name = str(getattr(error, "sqlite_errorname", ""))
                            if re.fullmatch(r"SQLITE_[A-Z_]{1,60}", sqlite_name):
                                name += "_" + sqlite_name
                            safe_name = name if re.fullmatch(r"[A-Za-z0-9_]{1,80}", name) else "WorkerError"
                            with self._connection() as db:
                                db.execute("UPDATE media_audit_runs SET last_worker_error=? WHERE id=?",
                                           (safe_name, run_id))
                            try:
                                self._finish(run_id, job_key, "unknown", dict(status="unknown",
                                    checked_at=time.time(), error="worker_exception", evidence={"exception_type": safe_name}))
                            except Exception:
                                # If checkpoint storage itself is unavailable,
                                # leave the remaining finite work resumable.
                                cancelled.set()
                # Running calls observe cancellation; metadata calls retain
                # the provider's bounded timeout and may outlast the slice.
        finally:
            with self._connection() as db:
                pending = db.execute("SELECT COUNT(*) FROM media_audit_jobs WHERE run_id=? AND state IN ('queued','running')", (run_id,)).fetchone()[0]
                status = "complete" if not pending else "paused"
                db.execute("UPDATE media_audit_runs SET status=?,owner='',lease_until=0,updated_at=? WHERE id=? AND owner=?", (status, time.time(), run_id, owner))
                db.execute("UPDATE media_audit_jobs SET state='queued',lease_until=0 WHERE run_id=? AND state='running'", (run_id,))
        return self.status(run_id)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("start", "status", "run", "stop", "repair", "include"))
    parser.add_argument("--index", type=Path)
    parser.add_argument("--run-id", type=int)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--max-seconds", type=float, default=300)
    parser.add_argument("--max-jobs", type=int, default=1000)
    parser.add_argument("--lanes", default=",".join(LANES))
    args = parser.parse_args(argv)
    audit = MediaHealthAudit(MediaIndex(args.index))
    if args.operation == "start":
        result = audit.status(audit.start())
    elif args.operation == "status":
        result = audit.status(args.run_id)
    elif args.operation == "stop":
        result = audit.stop(args.run_id)
    elif args.operation == "repair":
        result = audit.repair(args.run_id)
    elif args.operation == "include":
        result = audit.include(args.run_id)
    else:
        result = audit.run(args.run_id, workers=args.workers, max_seconds=args.max_seconds, max_jobs=args.max_jobs,
                           lanes=tuple(value.strip() for value in args.lanes.split(",") if value.strip()))
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
