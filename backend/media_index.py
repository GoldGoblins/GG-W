"""Disk-backed MEDIA index. Called by workers; never loads a catalogue into QML."""
from __future__ import annotations

from contextlib import contextmanager
from collections import OrderedDict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading
import time
from typing import Any, Iterable
from urllib.parse import quote

from backend.media_library import annotate, _IDENTIFIER, _file_allowed

PAGE_SIZE = 80
LIVE_CATALOG_RETENTION_SECONDS = 7 * 86400
VOD_CATALOG_RETENTION_SECONDS = 30 * 86400
# Catalogue pages contain labels and identifiers. Source URLs, file lists and
# provider details are read from the index only after the user selects a row.
SUMMARY_FIELDS = frozenset({
    "id", "kind", "content_type", "title", "series_title", "episode_title", "year",
    "category", "language", "provider", "source_label", "country", "artist", "album",
    "season", "episode", "episode_count", "collection_key", "archive_id", "series_id",
    "system", "system_label", "media", "is_live", "stream", "play", "player",
})
PAGES = {"live": ("TV", "live"), "movies": ("TV", "movie"), "series": ("TV", "series"),
         "music": ("MUSIC", "music"), "radio": ("RADIO", "music"),
         "downloads": ("FETCH", ""), "games": ("GAME", "game")}


def _key(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def view_request(page="live", letter="all", category="all", language="all", season="all", query="", offset=0, **extra):
    page = str(page) if page in PAGES else "live"
    return dict(page=page, letter=str(letter)[:8] or "all", category=str(category)[:100] or "all",
                language=str(language)[:100] or "all", season=str(season)[:8] or "all",
                query=str(query).strip()[:160], offset=max(0, min(1000000, int(offset or 0))),
                collection_key=str(extra.get("collection_key") or "")[:300],
                collection_title=str(extra.get("collection_title") or "")[:180])


def echo(view: dict[str, Any]) -> dict[str, Any]:
    return {"mode": PAGES[view["page"]][0], **{"library_" + key: view[key] for key in
            ("page", "letter", "category", "language", "season", "query", "offset")},
            "library_collection": view.get("collection_title", ""),
            "library_collection_key": view.get("collection_key", ""), "library_page_size": PAGE_SIZE}


class MediaIndex:
    def __init__(self, path: Path | None = None):
        if path is None:
            from backend.media_contract import STATE_DIR
            path = STATE_DIR / "catalog" / "library.sqlite3"
        self.path = Path(path)
        self._page_cache = OrderedDict()
        self._cache_lock = threading.Lock()

    @contextmanager
    def connection(self):
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=2)
        db.row_factory = sqlite3.Row
        db.create_function("gg_casefold", 1, _key, deterministic=True)
        db.execute("PRAGMA busy_timeout=2000")
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def initialize(self):
        with self.connection() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS items (
                  id TEXT PRIMARY KEY, kind TEXT NOT NULL, type TEXT NOT NULL,
                  title TEXT NOT NULL, sort_title TEXT NOT NULL, letter TEXT NOT NULL,
                  category TEXT NOT NULL, language TEXT NOT NULL, season INTEGER NOT NULL,
                  episode INTEGER NOT NULL, group_key TEXT NOT NULL, parent_key TEXT NOT NULL,
                  source_key TEXT NOT NULL, payload TEXT NOT NULL,
                  status TEXT NOT NULL DEFAULT 'unknown', checked_at REAL NOT NULL DEFAULT 0,
                  verified_until REAL NOT NULL DEFAULT 0, retry_at REAL NOT NULL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS media_view ON items(kind,type,letter,sort_title);
                CREATE INDEX IF NOT EXISTS media_health ON items(status,verified_until,retry_at);
                CREATE INDEX IF NOT EXISTS media_series ON items(parent_key,season,episode);
                CREATE INDEX IF NOT EXISTS media_identity ON items(group_key,verified_until);
                CREATE INDEX IF NOT EXISTS media_series_health ON items(parent_key,status,verified_until);
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
            db.execute("BEGIN IMMEDIATE")
            columns = {row[1] for row in db.execute("PRAGMA table_info(items)")}
            for name, declaration in (("check_scope", "TEXT NOT NULL DEFAULT ''"),
                                      ("check_decoded", "INTEGER NOT NULL DEFAULT 0")):
                if name not in columns:
                    db.execute("ALTER TABLE items ADD COLUMN " + name + " " + declaration)
            policy = db.execute("SELECT value FROM meta WHERE key='health_policy'").fetchone()
            if policy is None or policy[0] != "metadata-and-decoded-sample-v2":
                # Older proofs did not bind source identity. Keep their logs,
                # but admit them again only after the stronger audit/check.
                revoked = db.execute("UPDATE items SET status='unknown',verified_until=0 WHERE kind IN ('TV','FETCH')")
                db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('health_policy','metadata-and-decoded-sample-v2')")
                self._changed(db, structural=True, withdrawn=revoked.rowcount > 0)

    @staticmethod
    def _changed(db, *, structural=False, withdrawn=False):
        # Shared by index instances/processes, including explicit catalogue
        # refreshes. Repeated tab visits can reuse small pages safely.
        db.execute("INSERT INTO meta(key,value) VALUES('inventory_revision','1') "
                   "ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+1")
        if structural:
            db.execute("INSERT INTO meta(key,value) VALUES('inventory_structure_revision','1') "
                       "ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+1")
        if withdrawn:
            db.execute("INSERT INTO meta(key,value) VALUES('inventory_withdraw_revision','1') "
                       "ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+1")

    @staticmethod
    def _structure_changed(db, prepared):
        # Health/URL updates must not invalidate the ordering of a continuous
        # scroll session. Compare only grouping, ordering and filter fields.
        fields = "id,kind,type,sort_title,letter,category,language,season,episode,group_key,parent_key"
        for start in range(0, len(prepared), 500):
            chunk = prepared[start:start + 500]
            existing = {row[0]: tuple(row) for row in db.execute(
                "SELECT " + fields + " FROM items WHERE id IN (" + ",".join("?" for _ in chunk) + ")",
                [row[0] for row in chunk])}
            for row in chunk:
                shape = (row[0], row[1], row[2], *row[4:12])
                if existing.get(row[0]) != shape:
                    return True
        return False

    @staticmethod
    def series_key(row):
        return "series:" + _key(row.get("series_title") or row.get("title")) + "|" + _key(row.get("language"))

    @staticmethod
    def identity_key(row):
        normalized = annotate(row)
        fields = ("kind", "content_type", "title", "series_title", "year", "language", "season", "episode",
                  "archive_id", "archive_file", "archive_title", "referrer", "user_agent")
        return hashlib.sha256(json.dumps([normalized.get(key) or "" for key in fields],
                                         ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()

    def ingest(self, rows: Iterable[dict[str, Any]]) -> int:
        with self.connection() as db:
            return self._ingest(rows, db)

    def correct_metadata(self, row, *, expected):
        """Commit an evidence-based correction only to its original source."""
        identifier = str(expected.get("id") or "")
        if str(row.get("id") or "") != identifier or row.get("source") != expected.get("source"):
            raise ValueError("MEDIA_SOURCE_CHANGED")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            stored = db.execute("SELECT payload FROM items WHERE id=?", (identifier,)).fetchone()
            current = json.loads(stored[0]) if stored else None
            if (not current or current.get("source") != expected.get("source")
                    or self.identity_key(current) != self.identity_key(expected)):
                raise ValueError("MEDIA_SOURCE_CHANGED")
            self._ingest([row], db)
            return json.loads(db.execute("SELECT payload FROM items WHERE id=?", (identifier,)).fetchone()[0])

    @staticmethod
    def _descriptor_of_resolved(existing, discovered):
        """A provider's original item page cannot replace its resolved file."""
        identifier = str(discovered.get("archive_id") or "")
        filename = str(existing.get("archive_file") or "")
        if (not _IDENTIFIER.fullmatch(identifier) or identifier != existing.get("archive_id")
                or discovered.get("archive_file") or existing.get("content_type") not in ("movie", "episode")
                or not _file_allowed({"name": filename})):
            return False
        canonical = "https://archive.org/"
        return (discovered.get("source") == canonical + "details/" + quote(identifier, safe="")
                and existing.get("source") == canonical + "download/" + quote(identifier, safe="")
                + "/" + quote(filename, safe="/"))

    def ingest_discovered(self, rows: Iterable[dict[str, Any]], *,
                          expected: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        """Add provider discoveries without replacing a curated same-source row.

        Archive descriptors can expand the same file more than once, using a
        raw filename instead of its saved episode label. That is enrichment,
        not a replacement of the user's established title or episode mapping.
        Return the exact persisted identities so audit jobs do not keep a
        pre-merge snapshot. The merge and readback share one write transaction.
        A selected source resolved outside that transaction can supply its
        original snapshot in ``expected``. Any intervening source/identity
        replacement rejects the entire write, including newly resolved IDs.
        """
        protected = {"id", "source", "kind", "content_type", "title", "series_title", "year",
                     "language", "season", "episode", "archive_id", "archive_file", "archive_title",
                     "collection_key", "series_id", "episode_title", "category"}
        identifiers, seen, incoming = [], set(), []
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            for identifier, snapshot in (expected or {}).items():
                stored = db.execute("SELECT payload FROM items WHERE id=?", (str(identifier),)).fetchone()
                current = json.loads(stored[0]) if stored else None
                if (not current or current.get("source") != snapshot.get("source")
                        or self.identity_key(current) != self.identity_key(snapshot)):
                    raise ValueError("MEDIA_SOURCE_CHANGED")
            for raw in rows:
                if not isinstance(raw, dict) or not raw.get("id"):
                    continue
                row = annotate(raw)
                identifier = str(row["id"])
                stored = db.execute("SELECT payload FROM items WHERE id=?", (identifier,)).fetchone()
                existing = json.loads(stored[0]) if stored else None
                if existing and (existing.get("source") == row.get("source")
                                 or self._descriptor_of_resolved(existing, row)):
                    merged = dict(existing)
                    for key, value in row.items():
                        if (key in ("referrer", "user_agent") and value != merged.get(key)
                                or key not in protected and merged.get(key) in (None, "", 0, [], {})):
                            merged[key] = value
                    if merged != existing:
                        incoming.append(merged)
                else:
                    incoming.append(row)
                if identifier not in seen:
                    identifiers.append(identifier)
                    seen.add(identifier)
            self._ingest(incoming, db)
            canonical = []
            for identifier in identifiers:
                stored = db.execute("SELECT payload FROM items WHERE id=?", (identifier,)).fetchone()
                if stored:
                    canonical.append(json.loads(stored[0]))
        return canonical

    def _ingest(self, rows: Iterable[dict[str, Any]], db) -> int:
        prepared, parents = [], {}
        for raw in rows:
            if not isinstance(raw, dict) or not raw.get("id"):
                continue
            row = annotate(raw)
            content_type = row["content_type"]
            title = str(row.get("title") or "")[:180]
            if not title:
                continue
            # Keep the selected collection stable when lazy provider metadata
            # enriches its language/title after it has already been opened.
            collection_key = str(row.get("collection_key") or "")[:300]
            parent = (collection_key or self.series_key(row)) if content_type == "episode" else ""
            if content_type == "series":
                group = collection_key or self.series_key(row)
            elif content_type == "live":
                group = "live:" + _key(row.get("channel_id") or title)
            elif row["kind"] == "MUSIC" and content_type == "music":
                # Each local file remains selectable, including equal track
                # titles from different artists, albums or encodings.
                group = "music:" + str(row["id"])
            elif content_type == "episode":
                position = f"{row.get('season', 0)}:{row.get('episode', 0)}"
                group = parent + "|" + (position if row.get("episode") else _key(row.get("episode_title") or title))
                if parent not in parents:
                    parent_row = dict(row, id="group:" + hashlib.sha256(parent.encode()).hexdigest()[:20],
                                      title=row["series_title"], content_type="series", media="collection", source="",
                                      collection_key=parent)
                    parent_row.pop("archive_file", None)
                    parents[parent] = parent_row
            else:
                group = content_type + ":" + _key(title) + "|" + str(row.get("year") or "") + "|" + _key(row.get("language"))
            row["collection_key"] = group if content_type == "series" else parent
            first = title.strip()[:1].upper()
            letter = first if re.fullmatch("[A-ZÅÄÖ]", first) else "#"
            source_key = hashlib.sha256(str(row.get("source") or "").encode()).hexdigest()
            prepared.append((str(row["id"]), row["kind"], content_type, title, _key(title), letter,
                             str(row.get("category") or ""), str(row.get("language") or ""),
                             int(row.get("season") or 0), int(row.get("episode") or 0), group, parent,
                             source_key, json.dumps(row, ensure_ascii=False, separators=(",", ":"))))
        if not prepared:
            return 0
        identity_matches = " AND ".join(
            ["items." + field + "=excluded." + field for field in
             ("kind", "type", "title", "language", "season", "episode")] +
            ["json_extract(items.payload,'$." + field + "') IS json_extract(excluded.payload,'$." + field + "')"
             for field in ("series_title", "year", "archive_id", "archive_file", "archive_title", "referrer", "user_agent")])
        proof_matches = ("items.source_key=excluded.source_key AND " + identity_matches
            + " AND NOT (excluded.kind='MUSIC' AND items.status IN ('failed','error') "
              "AND json_extract(excluded.payload,'$.local')=1 "
              "AND COALESCE(json_extract(excluded.payload,'$.audio_metadata_version'),0)>=1)")
        withdrawn = False
        membership_changed = False
        for start in range(0, len(prepared), 400):
            batch = prepared[start:start + 400]
            incoming = {row[0]: row for row in batch}
            previous = db.execute("SELECT id,payload,status,checked_at,verified_until,retry_at FROM items WHERE id IN (" +
                                  ",".join("?" for _ in batch) + ")", list(incoming))
            for old in previous:
                old_payload = json.loads(old[1])
                replacement = json.loads(incoming[old[0]][13])
                same_identity = (old_payload.get("source") == replacement.get("source")
                                 and self.identity_key(old_payload) == self.identity_key(replacement))
                now = time.time()
                old_member = self._metadata_member(old_payload, old[2], old[3], old[5], now)
                new_member = self._metadata_member(replacement, old[2] if same_identity else "unknown",
                    old[3] if same_identity else 0, old[5] if same_identity else 0, now)
                membership_changed = membership_changed or old_member != new_member
                withdrawn = withdrawn or old_member and not new_member
                if (old[2] == 'verified' and old[3] > 0 and old[4] > old[3]
                        and self._catalog_until(old[3], old_payload) > now and not same_identity):
                    withdrawn = True
        structural = membership_changed or self._structure_changed(db, prepared)
        db.executemany("""INSERT INTO items(id,kind,type,title,sort_title,letter,category,language,season,episode,
              group_key,parent_key,source_key,payload) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(id) DO UPDATE SET kind=excluded.kind,type=excluded.type,title=excluded.title,
                sort_title=excluded.sort_title,letter=excluded.letter,category=excluded.category,
                language=excluded.language,season=excluded.season,episode=excluded.episode,
                group_key=excluded.group_key,parent_key=excluded.parent_key,payload=excluded.payload,
                verified_until=CASE WHEN """ + proof_matches + """ THEN items.verified_until ELSE 0 END,
                checked_at=CASE WHEN """ + proof_matches + """ THEN items.checked_at ELSE 0 END,
                retry_at=CASE WHEN """ + proof_matches + """ THEN items.retry_at ELSE 0 END,
                status=CASE WHEN """ + proof_matches + """ THEN items.status ELSE 'unknown' END,
                check_scope=CASE WHEN """ + proof_matches + """ THEN items.check_scope ELSE '' END,
                check_decoded=CASE WHEN """ + proof_matches + """ THEN items.check_decoded ELSE 0 END,
                source_key=excluded.source_key""", prepared)
        self._changed(db, structural=structural, withdrawn=withdrawn)
        # Keep a stable parent for episode identity even if a provider later
        # renames its descriptor. Browsing groups matching parents into one row.
        if parents:
            self._ingest(parents.values(), db)
        return len(prepared)

    def get(self, identifier: str):
        with self.connection() as db:
            row = db.execute("SELECT payload FROM items WHERE id=?", (identifier,)).fetchone()
            return json.loads(row[0]) if row else None

    @staticmethod
    def _catalog_until(checked_at, row):
        retention = (LIVE_CATALOG_RETENTION_SECONDS if row.get("content_type") == "live"
                     or row.get("kind") == "RADIO" else VOD_CATALOG_RETENTION_SECONDS)
        return float(checked_at) + retention

    @staticmethod
    def _catalog_until_sql(alias="i"):
        return (f"({alias}.checked_at+CASE WHEN {alias}.type='live' OR {alias}.kind='RADIO' "
                f"THEN {LIVE_CATALOG_RETENTION_SECONDS} ELSE {VOD_CATALOG_RETENTION_SECONDS} END)")

    @classmethod
    def _catalogued_sql(cls, alias="i"):
        # Playback freshness is deliberately shorter than catalogue retention.
        # A row still needs a real positive check with a valid original proof.
        return (f"({alias}.status='verified' AND {alias}.checked_at>0 "
                f"AND {alias}.verified_until>{alias}.checked_at AND {cls._catalog_until_sql(alias)}>?)")

    @staticmethod
    def _metadata_member(row, status, checked_at, retry_at, now):
        return bool(str(row.get("source") or "").strip()) and (status not in ("failed", "error") or retry_at <= now)

    @staticmethod
    def _metadata_sql(alias="i"):
        return (f"(COALESCE(trim(json_extract({alias}.payload,'$.source')),'')<>'' AND "
                f"({alias}.status NOT IN ('failed','error') OR {alias}.retry_at<=?))")

    @classmethod
    def _listed_sql(cls, alias="i"):
        return ("(" + cls._metadata_sql(alias) + f" OR ({alias}.type='series' AND EXISTS "
                f"(SELECT 1 FROM items child WHERE child.parent_key={alias}.group_key AND "
                + cls._metadata_sql("child") + ")))")

    def record(self, identifier: str, report: dict[str, Any], *, source=None, identity=None):
        status = str(report.get("status") or "unknown")
        checked = float(report.get("checked_at") or time.time())
        expiry = float(report.get("expires_at") or 0) if status == "verified" else 0
        evidence = report.get("evidence") or {}
        decoded = bool(evidence.get("decoded") is True or evidence.get("video_frames", 0) > 0
                       or evidence.get("audio_frames", 0) > 0)
        scope = str(report.get("scope") or ("decoded_sample" if decoded else ""))[:80]
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT status,verified_until,source_key,payload,checked_at,retry_at FROM items WHERE id=?", (identifier,)).fetchone()
            expected_source = hashlib.sha256(str(source).encode()).hexdigest() if source is not None else None
            if previous is None or (expected_source is not None and previous[2] != expected_source):
                return
            if identity is not None and self.identity_key(json.loads(previous[3])) != identity:
                return
            now = time.time()
            payload = json.loads(previous[3])
            retry_at = expiry if status == "verified" else checked + (300 if status == "unknown" else 1800)
            old_member = self._metadata_member(payload, previous[0], previous[4], previous[5], now)
            new_member = self._metadata_member(payload, status, checked, retry_at, now)
            membership_changed = old_member != new_member
            # Provider refreshes may replace a URL while its former probe runs.
            # That former proof must never certify the replacement source.
            source_clause = " AND source_key=?" if source is not None else ""
            args = [status, checked, expiry, retry_at, scope, int(decoded), identifier]
            if source is not None:
                args.append(hashlib.sha256(str(source).encode()).hexdigest())
            db.execute("UPDATE items SET status=?,checked_at=?,verified_until=?,retry_at=?,check_scope=?,check_decoded=? "
                       "WHERE id=?" + source_clause, args)
            self._changed(db, structural=membership_changed, withdrawn=old_member and not new_member)

    def is_verified(self, identifier: str) -> bool:
        with self.connection() as db:
            row = db.execute("SELECT 1 FROM items WHERE id=? AND status='verified' AND verified_until>?",
                             (identifier, time.time())).fetchone()
            return row is not None

    def _where(self, view, *, verified=False, candidates=False):
        mode, content_type = PAGES[view["page"]]
        clauses, args = ["i.kind IN ('TV','FETCH')" if mode == "TV" else "i.kind=?"], ([] if mode == "TV" else [mode])
        collection = view.get("collection_key")
        if collection:
            clauses.append("i.parent_key=?")
            args.append(collection)
        elif content_type:
            if candidates and content_type == "series":
                clauses.append("i.type IN ('series','episode')")
            else:
                clauses.append("i.type=?")
                args.append(content_type)
        if not collection and view["letter"] != "all":
            clauses.append("i.letter=?")
            args.append(view["letter"])
        for field in ("category", "language"):
            if view[field] != "all":
                clauses.append("i." + field + "=?")
                args.append(view[field])
        if view["season"] != "all" and collection:
            clauses.append("i.season=?")
            args.append(int(view["season"]) if view["season"].isdigit() else -1)
        if view["query"]:
            for word in _key(view["query"]).split()[:12]:
                search = ["i.sort_title", "i.parent_key"]
                if mode == "MUSIC":
                    search.extend(["gg_casefold(json_extract(i.payload,'$.artist'))",
                                   "gg_casefold(json_extract(i.payload,'$.album'))"])
                clauses.append("(" + " OR ".join(value + " LIKE ? ESCAPE '\\'" for value in search) + ")")
                word = word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                args.extend(["%" + word + "%"] * len(search))
        now = time.time()
        if verified:
            # Importing meaningful metadata makes it selectable. Only a
            # definite failed check temporarily withdraws it. A timeout or
            # inconclusive response does not establish that a source is dead.
            clauses.append(self._listed_sql())
            args.extend([now, now])
        elif candidates:
            clauses.append("i.verified_until<=? AND i.retry_at<=?")
            args.extend([now, now])
        return " AND ".join(clauses), args

    @classmethod
    def _source_order(cls):
        # Prefer a working source without hiding other known catalogue entries.
        # A failed alternative must not become the representative of a healthy
        # channel merely because SQLite happened to visit it last.
        return ("CASE WHEN i.status='verified' AND i.verified_until>? THEN 0 "
                "WHEN " + cls._catalogued_sql() + " THEN 1 "
                "WHEN i.status='failed' THEN 4 WHEN i.checked_at>0 THEN 3 ELSE 2 END,"
                "i.id LIKE 'group:%',i.id")

    @classmethod
    def _summary(cls, record, now):
        payload = json.loads(record["payload"])
        row = {key: value for key, value in payload.items() if key in SUMMARY_FIELDS}
        status = record["status"]
        catalog_until = cls._catalog_until(record["checked_at"], payload)
        fresh = status == "verified" and record["verified_until"] > now
        decoded = bool(record["check_decoded"])
        scope = record["check_scope"] or "previous_check"
        if status == "verified" and (catalog_until <= now or record["verified_until"] <= record["checked_at"]):
            status = "expired"
        if status == "verified" and not decoded:
            status = "available"
        row.update(availability=status, availability_checked_at=record["checked_at"],
                   availability_expires_at=record["verified_until"], availability_fresh=fresh,
                   availability_catalog_until=catalog_until, availability_decoded=decoded,
                   availability_scope="metadata")
        if status == "verified":
            row["availability_scope"] = "decoded_sample" if fresh else "previously_decoded"
        elif status == "available":
            row["availability_scope"] = scope
        return row

    def _series_summary(self, db, row, group, now):
        children = db.execute("SELECT COUNT(DISTINCT c.group_key),MAX(c.checked_at),MAX(c.verified_until),"
            "MAX(CASE WHEN c.status='verified' AND c.verified_until>c.checked_at THEN 1 ELSE 0 END),"
            "MAX(CASE WHEN c.status='verified' AND c.verified_until>c.checked_at THEN c.check_decoded ELSE 0 END) "
            "FROM items c WHERE c.parent_key=? AND " + self._metadata_sql("c"), (group, now)).fetchone()
        row["episode_count"] = children[0]
        if children[0] and (children[3] or row["availability"] not in ("verified", "available")):
            row.update(availability="verified" if children[4] else "available" if children[3] else "unknown",
                       availability_scope="checked_episodes" if children[4] else "available_episodes" if children[3]
                           else "metadata_episodes", availability_decoded=bool(children[4]),
                       availability_checked_at=children[1] or 0, availability_expires_at=children[2] or 0,
                       availability_fresh=(children[2] or 0) > now,
                       availability_catalog_until=self._catalog_until(children[1] or 0, row))
        return row

    @staticmethod
    def _browse_order(view):
        def alphabetic(field):
            return "replace(replace(replace(" + field + ",'å','{a'),'ä','{b'),'ö','{c')"
        title = alphabetic("sort_title")
        if view.get("collection_key"):
            return "season,episode," + title
        if view["page"] == "music":
            return alphabetic("gg_casefold(category)") + "," + title
        return title

    def browse(self, view, *, cancel=None):
        """Page known metadata; browsing never starts source or decoder work."""
        if cancel is not None and cancel.is_set():
            raise ValueError("MEDIA_BROWSE_CANCELLED")
        where, args = self._where(view, verified=True)
        order = self._browse_order(view)
        now = time.time()
        with self.connection() as db:
            if cancel is not None:
                db.set_progress_handler(lambda: int(cancel.is_set()), 1000)
            revision = db.execute("SELECT value FROM meta WHERE key='inventory_revision'").fetchone()
            cache_key = ((revision[0] if revision else "0"), json.dumps(view, sort_keys=True, ensure_ascii=False))
            with self._cache_lock:
                cached = self._page_cache.get(cache_key)
                if cached and cached[0] > now:
                    self._page_cache.move_to_end(cache_key)
                    return deepcopy(cached[1])
            structure_revision = db.execute("SELECT value FROM meta WHERE key='inventory_structure_revision'").fetchone()
            total = db.execute("SELECT COUNT(DISTINCT i.group_key) FROM items i WHERE " + where, args).fetchone()[0]
            groups = db.execute("SELECT i.group_key,MIN(i.category) AS category,MIN(i.sort_title) AS sort_title,MIN(i.season) AS season,"
                                "MIN(i.episode) AS episode FROM items i WHERE " + where +
                                " GROUP BY i.group_key ORDER BY " + order + ",i.group_key LIMIT ? OFFSET ?",
                                [*args, PAGE_SIZE, view["offset"]]).fetchall()
            rows = []
            # At most80 indexed lookups, regardless of the catalogue size. Each
            # returns one full DB record, then emits only its lightweight label.
            for group in groups:
                if cancel is not None and cancel.is_set():
                    raise ValueError("MEDIA_BROWSE_CANCELLED")
                record = db.execute("SELECT i.payload,i.status,i.checked_at,i.verified_until,i.check_scope,i.check_decoded FROM items i WHERE "
                                    + where + " AND i.group_key=? ORDER BY " + self._source_order() + " LIMIT 1",
                                    [*args, group["group_key"], now, now]).fetchone()
                if record is not None:
                    row = self._summary(record, now)
                    if row.get("content_type") == "series":
                        row = self._series_summary(db, row, group["group_key"], now)
                    rows.append(row)
            options = {}
            for field in ("category", "language", "season"):
                option_view = dict(view, **{field: "all"}, offset=0)
                option_where, option_args = self._where(option_view, verified=True)
                option_limit = 2048 if field == "category" and view["page"] == "music" else 150
                values = db.execute("SELECT DISTINCT i." + field + " FROM items i WHERE " + option_where +
                                    " ORDER BY gg_casefold(i." + field + ") LIMIT ?", [*option_args, option_limit]).fetchall()
                label = {"category": "Alla kategorier", "language": "Alla språk", "season": "Alla säsonger"}[field]
                if field == "category" and view["page"] == "music":
                    label = "Alla artister"
                options["library_" + {"category": "categories", "language": "languages", "season": "seasons"}[field]] = [
                    {"value": "all", "label": label}] + [{"value": str(row[0]), "label":
                     ("Utan säsongsnummer" if row[0] == 0 else "Säsong " + str(row[0])) if field == "season" else str(row[0])}
                     for row in values if row[0] != ""]
            counts = db.execute("SELECT COUNT(*),SUM(i.checked_at>0),SUM(" + self._catalogued_sql() + "),"
                                "MIN(CASE WHEN " + self._catalogued_sql() + " THEN " + self._catalog_until_sql() + " END) FROM items i",
                                (now, now)).fetchone()
        result = {**echo(view), **options, "items": rows, "library_total": total, "library_count": total,
                  "library_catalog_revision": str(structure_revision[0] if structure_revision else "0") + ":" + str(total),
                  "library_has_more": view["offset"] + len(rows) < total,
                  "library_candidate_count": counts[0], "library_checked_count": counts[1] or 0,
                  "library_verified_count": counts[2] or 0}
        expiry = min([now + 30] + ([counts[3]] if counts[3] else []) + [row["availability_expires_at"] for row in rows
                                  if row["availability"] in ("verified", "available") and row["availability_expires_at"] > now])
        with self._cache_lock:
            self._page_cache[cache_key] = (expiry, deepcopy(result))
            self._page_cache.move_to_end(cache_key)
            while len(self._page_cache) > 24:
                self._page_cache.popitem(last=False)
        return result

    def snapshot_groups(self, view, cancel=None):
        """Capture only ordered identities on a worker, never source metadata."""
        where, args = self._where(view, verified=True)
        order = self._browse_order(view)
        with self.connection() as db:
            if cancel is not None:
                db.set_progress_handler(lambda: int(cancel.is_set()), 1000)
            rows = []
            for row in db.execute(
                "SELECT i.group_key,MIN(i.category) AS category,MIN(i.sort_title) AS sort_title,MIN(i.season) AS season,MIN(i.episode) AS episode "
                "FROM items i WHERE " + where + " GROUP BY i.group_key ORDER BY " + order + ",i.group_key", args):
                rows.append(row[0])
                if len(rows) % 256 == 0:
                    if cancel is not None and cancel.is_set():
                        raise ValueError("MEDIA_SNAPSHOT_CANCELLED")
                    time.sleep(0)
            return tuple(rows)

    def snapshot_page(self, view, groups, position, cancel=None):
        """Read up to80 selectable summaries from a stable identity list."""
        where, args = self._where(view, verified=True)
        rows, positions = [], []
        now = time.time()
        with self.connection() as db:
            db.execute("BEGIN")
            if cancel is not None:
                db.set_progress_handler(lambda: int(cancel.is_set()), 1000)
            while position < len(groups) and len(rows) <= PAGE_SIZE:
                if cancel is not None and cancel.is_set():
                    raise ValueError("MEDIA_SNAPSHOT_CANCELLED")
                batch = groups[position:position + 256]
                alive = {row[0] for row in db.execute("SELECT DISTINCT i.group_key FROM items i WHERE " + where +
                    " AND i.group_key IN (" + ",".join("?" for _ in batch) + ")", [*args, *batch])}
                for group in batch:
                    if cancel is not None and cancel.is_set():
                        raise ValueError("MEDIA_SNAPSHOT_CANCELLED")
                    position += 1
                    if group not in alive:
                        continue
                    record = db.execute("SELECT i.payload,i.status,i.checked_at,i.verified_until,i.check_scope,i.check_decoded FROM items i WHERE "
                        + where + " AND i.group_key=? ORDER BY " + self._source_order() + " LIMIT 1",
                        [*args, group, now, now]).fetchone()
                    if record is None:
                        continue
                    row = self._summary(record, now)
                    if row.get("content_type") == "series":
                        row = self._series_summary(db, row, group, now)
                    rows.append(row)
                    positions.append(position)
                    if len(rows) > PAGE_SIZE:
                        break
        has_more = len(rows) > PAGE_SIZE
        next_position = positions[PAGE_SIZE - 1] if has_more else position
        return rows[:PAGE_SIZE], next_position, has_more

    def collection_descriptors(self, collection_key, limit=12):
        """Provider descriptors for one selected series, excluding fake parents."""
        output, seen = [], set()
        with self.connection() as db:
            records = db.execute("SELECT i.payload FROM items i WHERE i.group_key=? AND i.type='series' "
                                 "AND i.id NOT LIKE 'group:%' ORDER BY " + self._source_order(),
                                 [str(collection_key), time.time(), time.time()])
            for record in records:
                row = json.loads(record[0])
                archive_id = str(row.get("archive_id") or "")
                source = str(row.get("source") or "")
                # Generated episode parents inherit archive_id, but deliberately
                # have no descriptor URL. They are not another provider request.
                if not archive_id or not source or "/details/" not in source or archive_id in seen:
                    continue
                seen.add(archive_id)
                output.append(row)
                if len(output) >= max(1, min(24, int(limit))):
                    break
        return output

    def collection_descriptor(self, collection_key):
        rows = self.collection_descriptors(collection_key, limit=1)
        return rows[0] if rows else None

    def group_sources(self, identifier, limit=12):
        """Full alternate sources for a selected title/channel only."""
        with self.connection() as db:
            group = db.execute("SELECT group_key FROM items WHERE id=?", (str(identifier),)).fetchone()
            if group is None:
                return []
            records = db.execute("SELECT i.payload FROM items i WHERE i.group_key=? ORDER BY "
                                 + self._source_order() + " LIMIT ?",
                                 [group[0], time.time(), time.time(), max(1, min(24, int(limit)))]).fetchall()
        return [json.loads(record[0]) for record in records]

    def candidates(self, view, limit=12):
        if view["page"] == "games":
            return []
        where, args = self._where(view, verified=False, candidates=True)
        with self.connection() as db:
            # Known direct files precede descriptors which require metadata IO.
            rows = db.execute("SELECT i.payload FROM items i WHERE " + where +
                              " ORDER BY i.checked_at,CASE WHEN i.type='series' THEN 1 ELSE 0 END,i.sort_title LIMIT ?",
                              [*args, max(1, min(80, int(limit)))]).fetchall()
        return [json.loads(row[0]) for row in rows]

    def mark_expanded(self, identifier):
        with self.connection() as db:
            db.execute("UPDATE items SET retry_at=? WHERE id=?", (time.time() + 6 * 3600, identifier))

    def meta(self, key, value=None):
        with self.connection() as db:
            if value is not None:
                db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (key, str(value)))
                return str(value)
            row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            return row[0] if row else ""
