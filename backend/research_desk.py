"""Local research/control plane for the GG AI Desktop.

This module turns the useful parts of the research round into small,
inspectable local primitives:

* project/task backlog with Scout -> Ship promotion;
* provenance-first evidence cards;
* source ingest and procedural method memory;
* verified, replayable web-skill manifests (never executed here);
* SQL logical-intent previews without a database connection;
* bounded evaluation and observability events.

It deliberately does not add model, network, shell, credential, merge or
production authority.  The database is a local index; source content is
bounded and secrets are scrubbed before persistence.
"""

from __future__ import annotations

from backend.application_paths import STATE_ROOT

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
import uuid
import math
from functools import wraps
from typing import Any, Iterator


SCHEMA = "gg.research-desk.v1"
ACTION_AUTHORITY = "NONE"
NETWORK = "NONE"
MODEL_INFERENCE = False
MAX_TEXT = 12_000
MAX_SOURCE = 48_000
MAX_ROWS = 256
MAX_EVENTS = 4_096
MAX_STEPS = 12
MAX_SKILL_SCRIPT = 32_000
MAX_SQL = 64_000

ROOT = Path(
    os.environ.get(
        "GG_RESEARCH_DESK_ROOT",
        str(STATE_ROOT / 'research-desk'),
    )
)
DB_NAME = "research-desk.sqlite3"
_LOCK = threading.RLock()
_TRANSACTION = threading.local()
MAX_FINDING_STORAGE = 32 * 1024 * 1024

_SECRET_RE = re.compile(
    r"(?i)(password|passwd|lösenord|secret|token|api[_-]?key|authorization)"
    r"\s*[:=]\s*[^\s,;]+"
)
_LONG_HEX_RE = re.compile(r"\b[0-9a-f]{32,128}\b", re.IGNORECASE)
_WORD_RE = re.compile(r"[\wÀ-ÖØ-öø-ÿ-]{3,}", re.UNICODE)
_SQL_WORD_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_$\.]*\b")
_SQL_TABLE_RE = re.compile(
    r"\b(?:from|join|update|into|delete\s+from|insert\s+into)\s+"
    r"([A-Za-z_][A-Za-z0-9_$\.\"]*)",
    re.IGNORECASE,
)
_SQL_CTE_RE = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_$]*)\s+as\s*\(", re.IGNORECASE
)
_DANGEROUS_SKILL_RE = re.compile(
    r"(?i)(subprocess|os\.system|shell\s*=|password|passwd|api[_-]?key|"
    r"authorization|\.env|private[_-]?key|wallet|sudo|curl\s|wget\s|"
    r"requests\.(get|post|put|delete)|exec\(|eval\()"
)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _clip(value: Any, limit: int = MAX_TEXT) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _scrub(value: Any, limit: int = MAX_TEXT) -> str:
    text = _clip(value, limit)
    text = _SECRET_RE.sub(r"\1=[REDACTED]", text)
    text = _LONG_HEX_RE.sub("[ID]", text)
    return _clip(text, limit)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _id(prefix: str, value: str) -> str:
    return prefix + "-" + _sha(value)[:24]


def _tokens(value: str) -> set[str]:
    return {
        item.casefold()
        for item in _WORD_RE.findall(str(value or ""))
        if item.casefold() not in {"the", "and", "för", "och", "med", "som"}
    }


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


@contextmanager
def _db(root: Path | None = None) -> Iterator[sqlite3.Connection]:
    target_root = Path(root or ROOT)
    active = getattr(_TRANSACTION, 'connection', None)
    if active is not None:
        if target_root.resolve() != _TRANSACTION.root:
            raise ValueError('RESEARCH_TRANSACTION_TARGET_CHANGED')
        yield active
        return
    target_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    connection = sqlite3.connect(
        str(target_root / DB_NAME), timeout=5.0, check_same_thread=False
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            mode TEXT NOT NULL,
            status TEXT NOT NULL,
            priority INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id)
        );
        CREATE TABLE IF NOT EXISTS sources (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            kind TEXT NOT NULL,
            origin TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            excerpt TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS methods (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            trigger_text TEXT NOT NULL,
            steps_json TEXT NOT NULL,
            proof TEXT NOT NULL,
            source_id TEXT NOT NULL,
            status TEXT NOT NULL,
            uses INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS evidence (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            claim TEXT NOT NULL,
            source_url TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            provenance TEXT NOT NULL,
            confidence REAL NOT NULL,
            details_json TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS skills (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            template TEXT NOT NULL,
            script TEXT NOT NULL,
            parameters_json TEXT NOT NULL,
            status TEXT NOT NULL,
            checks_json TEXT NOT NULL,
            source_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            eval_name TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL,
            score REAL,
            metrics_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            stage TEXT NOT NULL,
            status TEXT NOT NULL,
            duration_ms INTEGER NOT NULL,
            metadata_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS tasks_updated ON tasks(updated_at DESC);
        CREATE INDEX IF NOT EXISTS evidence_created ON evidence(created_at DESC);
        CREATE INDEX IF NOT EXISTS events_created ON events(created_at DESC);
        CREATE TABLE IF NOT EXISTS method_tests (
            method_id TEXT PRIMARY KEY, method_digest TEXT NOT NULL,
            proof_json TEXT NOT NULL, tested_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS finding_snapshots (
            finding_id TEXT PRIMARY KEY, source_id TEXT NOT NULL,
            content_sha256 TEXT NOT NULL, content_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS wb_batches (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, state TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS wb_items (
            id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES wb_batches(id),
            position INTEGER NOT NULL, url TEXT NOT NULL, state TEXT NOT NULL,
            lease TEXT NOT NULL DEFAULT '', lease_until REAL NOT NULL DEFAULT 0,
            note TEXT NOT NULL DEFAULT '', observation_id TEXT NOT NULL DEFAULT '',
            UNIQUE(batch_id,url)
        );
        CREATE INDEX IF NOT EXISTS wb_items_queue ON wb_items(batch_id,state,position);
        CREATE TABLE IF NOT EXISTS wb_observations (
            id TEXT PRIMARY KEY, session TEXT NOT NULL, source TEXT NOT NULL,
            version TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
            exit_code INTEGER, redacted INTEGER NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS wb_observations_session ON wb_observations(session,created_at);
        CREATE TABLE IF NOT EXISTS wb_requirements (
            id TEXT PRIMARY KEY, task TEXT NOT NULL, title TEXT NOT NULL,
            paths_json TEXT NOT NULL, test_module TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS wb_receipts (
            id TEXT PRIMARY KEY, requirement_id TEXT NOT NULL REFERENCES wb_requirements(id),
            version TEXT NOT NULL, status TEXT NOT NULL, observation_id TEXT NOT NULL,
            duration_ms INTEGER NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS wb_receipts_requirement ON wb_receipts(requirement_id,created_at);
        CREATE TABLE IF NOT EXISTS wb_usage (
            id TEXT PRIMARY KEY, task TEXT NOT NULL, model TEXT NOT NULL,
            outcome TEXT NOT NULL, basis TEXT NOT NULL, input_tokens INTEGER,
            output_tokens INTEGER, cost REAL, currency TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS wb_source_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT NOT NULL REFERENCES sources(id),
            state TEXT NOT NULL, note TEXT NOT NULL, valid_at TEXT NOT NULL,
            valid_until TEXT NOT NULL, observed_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS wb_source_history ON wb_source_events(source_id,id);
        """
    )
    _TRANSACTION.connection = connection
    _TRANSACTION.root = target_root.resolve()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        _TRANSACTION.connection = None
        _TRANSACTION.root = None
        connection.close()


def atomic_operation(function):
    """One user operation commits together, including nested index helpers."""
    @wraps(function)
    def atomic(*args, **kwargs):
        with _LOCK, _db():
            return function(*args, **kwargs)
    return atomic


def retain_finding(finding_id: str, source_id: str, report: dict) -> None:
    """Keep the bounded, already-redacted report instead of only its excerpt."""
    content = _json(report)
    size = len(content.encode('utf-8'))
    if size > 2 * 1024 * 1024:
        raise ValueError('FINDING_TOO_LARGE')
    with _LOCK, _db() as db:
        used = db.execute('SELECT COALESCE(SUM(length(CAST(content_json AS BLOB))),0) FROM finding_snapshots WHERE finding_id<>?', (finding_id,)).fetchone()[0]
        if used + size > MAX_FINDING_STORAGE:
            raise ValueError('FINDING_STORAGE_LIMIT')
        db.execute('INSERT OR REPLACE INTO finding_snapshots VALUES(?,?,?,?,?)',
                   (finding_id, source_id, _sha(content), content, _now()))


def finding_snapshot(finding_id: str) -> dict | None:
    with _LOCK, _db() as db:
        row = db.execute('SELECT * FROM finding_snapshots WHERE finding_id=?', (finding_id,)).fetchone()
    if row is None or _sha(row['content_json']) != row['content_sha256']:
        return None
    return json.loads(row['content_json'])


def _method_digest(row) -> str:
    return _sha(_json([row[key] for key in ('id', 'name', 'trigger_text', 'steps_json', 'source_id', 'proof')]))


@atomic_operation
def _record_tested_method(payload: dict, proof: dict) -> dict:
    checks = proof.get('checks')
    if (proof.get('test_schema') != 'gg.research-known-answer.v1' or
            not isinstance(checks, dict) or not checks or
            not all(value is True for value in checks.values()) or
            not proof.get('scope') or not proof.get('engine')):
        raise ValueError('PASSING_INDEPENDENT_TEST_REQUIRED')
    result = add_method({**payload, 'status': 'PROPOSED'})
    with _db() as db:
        row = db.execute('SELECT * FROM methods WHERE id=?', (result['method_id'],)).fetchone()
        db.execute('INSERT OR REPLACE INTO method_tests VALUES(?,?,?,?)',
                   (row['id'], _method_digest(row), _json(proof), _now()))
        db.execute("UPDATE methods SET status='VERIFIED' WHERE id=?", (row['id'],))
    return {**result, 'method_status': 'VERIFIED'}


def method_test(method_id: str) -> dict | None:
    with _LOCK, _db() as db:
        row = db.execute('SELECT * FROM methods WHERE id=?', (method_id,)).fetchone()
        test = db.execute('SELECT * FROM method_tests WHERE method_id=?', (method_id,)).fetchone()
    if row is None or test is None or row['status'] != 'VERIFIED' or _method_digest(row) != test['method_digest']:
        return None
    if source_freshness(row['source_id']) not in {'CURRENT', 'UNREVIEWED'}:
        return None
    try:
        proof = json.loads(test['proof_json'])
    except (ValueError, TypeError):
        return None
    if not isinstance(proof, dict):
        return None
    checks = proof.get('checks')
    if proof.get('test_schema') != 'gg.research-known-answer.v1' or not isinstance(checks, dict) or not checks or not all(v is True for v in checks.values()):
        return None
    return proof


def source_freshness(source_id: str) -> str:
    with _LOCK, _db() as db:
        event = db.execute('SELECT * FROM wb_source_events WHERE source_id=? ORDER BY id DESC LIMIT 1', (source_id,)).fetchone()
    if not event:
        return 'UNREVIEWED'
    if event['state'] != 'CURRENT':
        return event['state']
    if event['valid_at'] and event['valid_at'] > _now():
        return 'NOT_YET_VALID'
    return 'STALE' if event['valid_until'] and event['valid_until'] <= _now() else 'CURRENT'


def _ensure_default_project(connection: sqlite3.Connection) -> str:
    project_id = "project-gg-ai-desktop"
    now = _now()
    connection.execute(
        "INSERT OR IGNORE INTO projects(id,title,status,created_at,updated_at) "
        "VALUES(?,?,?,?,?)",
        (project_id, "GG AI Desktop", "ACTIVE", now, now),
    )
    return project_id


def _rows(connection: sqlite3.Connection, table: str, limit: int = MAX_ROWS) -> list[dict[str, Any]]:
    allowed = {"projects", "tasks", "sources", "methods", "evidence", "skills", "runs", "events"}
    if table not in allowed:
        return []
    rows = connection.execute(
        f"SELECT * FROM {table} ORDER BY rowid DESC LIMIT ?", (max(1, min(limit, MAX_ROWS)),)
    ).fetchall()
    return [dict(row) for row in rows]


def empty_snapshot() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "action_authority": ACTION_AUTHORITY,
        "network": NETWORK,
        "model_inference": MODEL_INFERENCE,
        "status": "READY",
        "projects": [],
        "tasks": [],
        "evidence": [],
        "sources": [],
        "methods": [],
        "skills": [],
        "runs": [],
        "events": [],
        "observability": {"events": 0, "runs": 0, "last_event": ""},
    }


def snapshot() -> dict[str, Any]:
    with _LOCK, _db() as connection:
        project_id = _ensure_default_project(connection)
        projects = _rows(connection, "projects", 32)
        tasks = _rows(connection, "tasks", 96)
        evidence = _rows(connection, "evidence", 96)
        saved_findings = {row[0] for row in connection.execute('SELECT finding_id FROM finding_snapshots')}
        for card in evidence:
            card['has_snapshot'] = card['id'] in saved_findings
            try:
                source_id = json.loads(card['details_json']).get('source_id', '')
            except (ValueError, TypeError, AttributeError):
                source_id = ''
            card['source_freshness'] = source_freshness(source_id)
        sources = _rows(connection, "sources", 96)
        methods = _rows(connection, "methods", 96)
        skills = _rows(connection, "skills", 64)
        for method in methods:
            tested = method_test(method['id']) is not None
            if method['status'] == 'VERIFIED' and not tested:
                method['status'] = 'PROPOSED'
            method['verification_level'] = 'FIXTURE_TESTED' if tested else 'INDEPENDENT_TEST_REQUIRED'
        for skill in skills:
            if skill['status'] == 'VERIFIED':
                skill['status'] = 'STRUCTURE_CHECKED'
            skill['verification_level'] = 'STRUCTURE_ONLY'
        runs = _rows(connection, "runs", 64)
        events = _rows(connection, "events", 128)
        event_count = int(connection.execute("SELECT COUNT(*) FROM events").fetchone()[0])
        last_event = connection.execute(
            "SELECT created_at FROM events ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return {
        **empty_snapshot(),
        "project_id": project_id,
        "projects": projects,
        "tasks": tasks,
        "evidence": evidence,
        "sources": sources,
        "methods": methods,
        "skills": skills,
        "runs": runs,
        "events": events,
        "observability": {
            "events": event_count,
            "runs": len(runs),
            "last_event": str(last_event[0]) if last_event else "",
        },
    }


def create_project(title: str) -> dict[str, Any]:
    clean = _scrub(title, 120) or "Untitled project"
    project_id = _id("project", clean)
    now = _now()
    with _LOCK, _db() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO projects VALUES(?,?,?,?,?)",
            (project_id, clean, "ACTIVE", now, now),
        )
    return {"schema": SCHEMA, "status": "PROJECT_READY", "project_id": project_id, "title": clean}


def add_task(title: str, body: str = "", project_id: str = "", mode: str = "SCOUT", priority: int = 50) -> dict[str, Any]:
    clean_title = _scrub(title, 180) or "Untitled task"
    clean_body = _scrub(body, MAX_TEXT)
    mode_value = str(mode or "SCOUT").upper()
    if mode_value not in {"SCOUT", "SHIP"}:
        mode_value = "SCOUT"
    try:
        priority_value = max(0, min(100, int(priority)))
    except (TypeError, ValueError):
        priority_value = 50
    now = _now()
    with _LOCK, _db() as connection:
        selected_project = project_id.strip() or _ensure_default_project(connection)
        exists = connection.execute("SELECT id FROM projects WHERE id=?", (selected_project,)).fetchone()
        if exists is None:
            selected_project = _ensure_default_project(connection)
        task_id = _id("task", selected_project + "\n" + clean_title + "\n" + now)
        connection.execute(
            "INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?)",
            (task_id, selected_project, clean_title, clean_body, mode_value, "BACKLOG", priority_value, now, now),
        )
    return {"schema": SCHEMA, "status": "TASK_CREATED", "task_id": task_id, "mode": mode_value}


def promote_task(task_id: str, mode: str = "SHIP") -> dict[str, Any]:
    wanted = str(mode or "SHIP").upper()
    if wanted not in {"SCOUT", "SHIP"}:
        wanted = "SHIP"
    with _LOCK, _db() as connection:
        now = _now()
        cursor = connection.execute(
            "UPDATE tasks SET mode=?, updated_at=? WHERE id=?",
            (wanted, now, str(task_id or "").strip()),
        )
        if cursor.rowcount != 1:
            return {"schema": SCHEMA, "status": "TASK_NOT_FOUND", "task_id": task_id}
    return {
        "schema": SCHEMA,
        "status": "TASK_PROMOTED" if wanted == "SHIP" else "TASK_DEMOTED",
        "task_id": task_id,
        "mode": wanted,
        "merge_authority": "NONE",
        "apply_authority": "NONE",
    }


def add_evidence(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    kind = _scrub(data.get("kind") or "OBSERVATION", 48).upper()
    title = _scrub(data.get("title") or "Untitled evidence", 180)
    claim = _scrub(data.get("claim") or data.get("summary") or "", MAX_TEXT)
    source_url = _scrub(data.get("source_url") or data.get("url") or "", 500)
    observed_at = _scrub(data.get("observed_at") or _now(), 48)
    provenance = _scrub(data.get("provenance") or "OBSERVED", 48).upper()
    try:
        confidence = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
    except (TypeError, ValueError):
        confidence = 0.5
    details = data.get("details") if isinstance(data.get("details"), dict) else {}
    details_text = _json({str(k)[:64]: _scrub(v, 500) for k, v in list(details.items())[:32]})
    fingerprint = "\n".join((kind, title, claim, source_url, observed_at, provenance, details_text))
    evidence_id = _id("evidence", fingerprint)
    now = _now()
    with _LOCK, _db() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO evidence VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (evidence_id, kind, title, claim, source_url, observed_at, provenance, confidence, details_text, _sha(fingerprint), now),
        )
    return {"schema": SCHEMA, "status": "EVIDENCE_RECORDED", "evidence_id": evidence_id, "sha256": _sha(fingerprint), "provenance": provenance}


def ingest_source(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    title = _scrub(data.get("title") or "Imported source", 180)
    kind = _scrub(data.get("kind") or "TEXT", 48).upper()
    origin = _scrub(data.get("origin") or data.get("source_url") or "LOCAL", 500)
    content = _scrub(data.get("content") or data.get("text") or "", MAX_SOURCE)
    if not content:
        return {"schema": SCHEMA, "status": "SOURCE_EMPTY"}
    source_sha = _sha(content)
    source_id = _id("source", title + "\n" + origin + "\n" + source_sha)
    now = _now()
    with _LOCK, _db() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO sources VALUES(?,?,?,?,?,?,?)",
            (source_id, title, kind, origin, source_sha, _clip(content, 1800), now),
        )
    memory_id = ""
    if bool(data.get("remember")):
        try:
            from backend import long_memory

            remembered = long_memory.capture(
                title + ": " + _clip(content, 150),
                kind="semantic",
                note="Source " + source_id + " · " + _clip(content, 150),
                force=True,
            )
            memory_id = str(remembered.get("lesson_id") or "")
        except Exception:
            memory_id = ""
    return {"schema": SCHEMA, "status": "SOURCE_INGESTED", "source_id": source_id, "sha256": source_sha, "memory_id": memory_id}


def add_method(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    name = _scrub(data.get("name") or "Unnamed method", 120)
    trigger = _scrub(data.get("trigger") or data.get("trigger_text") or "", 300)
    raw_steps = data.get("steps") if isinstance(data.get("steps"), list) else []
    steps = [_scrub(item, 220) for item in raw_steps[:MAX_STEPS] if _scrub(item, 220)]
    proof = _scrub(data.get("proof") or "", 800)
    source_id = _scrub(data.get("source_id") or "", 120)
    status = str(data.get("status") or "PROPOSED").upper()
    if status not in {"PROPOSED", "RETIRED"}:
        status = "PROPOSED"
    method_id = _id("method", name + "\n" + trigger + "\n" + _json(steps))
    with _LOCK, _db() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO methods VALUES(?,?,?,?,?,?,?,?,?)",
            (method_id, name, trigger, _json(steps), proof, source_id, status, 0, _now()),
        )
        connection.execute('DELETE FROM method_tests WHERE method_id=?', (method_id,))
    return {"schema": SCHEMA, "status": "METHOD_RECORDED", "method_id": method_id, "method_status": status}


def match_methods(query: str, limit: int = 6) -> list[dict[str, Any]]:
    wanted = _tokens(query)
    with _LOCK, _db() as connection:
        rows = _rows(connection, "methods", 96)
    ranked: list[tuple[int, dict[str, Any]]] = []
    for row in rows:
        if row.get("status") == "RETIRED":
            continue
        tested = method_test(row['id']) is not None
        if row['status'] == 'VERIFIED' and not tested:
            row['status'] = 'PROPOSED'
        row['verification_level'] = 'FIXTURE_TESTED' if tested else 'INDEPENDENT_TEST_REQUIRED'
        hay = _tokens(str(row.get("name") or "") + " " + str(row.get("trigger_text") or "") + " " + str(row.get("steps_json") or ""))
        score = len(wanted & hay)
        if score:
            ranked.append((score + int(row.get("uses") or 0), row))
    ranked.sort(key=lambda item: (-item[0], str(item[1].get("id") or "")))
    return [{**row, "match_score": score} for score, row in ranked[: max(1, min(int(limit), 12))]]


def _skill_checks(script: str, template: str) -> dict[str, Any]:
    checks: dict[str, Any] = {
        "bounded_script": len(script) <= MAX_SKILL_SCRIPT,
        "no_credential_markers": not bool(_DANGEROUS_SKILL_RE.search(script + " " + template)),
        "has_replay_shape": bool(script.strip()) and ("page." in script or "playwright" in script.lower()),
        "has_evidence_marker": "evidence" in (script + " " + template).casefold(),
    }
    checks["pass"] = all(bool(value) for value in checks.values())
    return checks


def add_web_skill(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    name = _scrub(data.get("name") or "Unnamed web skill", 120)
    template = _scrub(data.get("template") or "", 600)
    script = _scrub(data.get("script") or "", MAX_SKILL_SCRIPT)
    parameters = data.get("parameters") if isinstance(data.get("parameters"), list) else []
    parameters = [_scrub(item, 64) for item in parameters[:24]]
    source_id = _scrub(data.get("source_id") or "", 120)
    checks = _skill_checks(script, template)
    status = "STRUCTURE_CHECKED" if bool(data.get("verify")) and checks["pass"] else "DRAFT"
    skill_id = _id("web-skill", name + "\n" + template + "\n" + script)
    with _LOCK, _db() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO skills VALUES(?,?,?,?,?,?,?,?,?)",
            (skill_id, name, template, script, _json(parameters), status, _json(checks), source_id, _now()),
        )
    return {"schema": SCHEMA, "status": "WEB_SKILL_STRUCTURE_CHECKED" if status == "STRUCTURE_CHECKED" else "WEB_SKILL_DRAFT", "skill_id": skill_id, "checks": checks, "execution": "NOT_EXECUTED", "verification_level": "STRUCTURE_ONLY"}


def verify_web_skill(skill_id: str) -> dict[str, Any]:
    with _LOCK, _db() as connection:
        row = connection.execute("SELECT * FROM skills WHERE id=?", (str(skill_id or ""),)).fetchone()
        if row is None:
            return {"schema": SCHEMA, "status": "SKILL_NOT_FOUND", "skill_id": skill_id}
        checks = _skill_checks(str(row["script"]), str(row["template"]))
        status = "STRUCTURE_CHECKED" if checks["pass"] else "DRAFT"
        connection.execute("UPDATE skills SET status=?, checks_json=? WHERE id=?", (status, _json(checks), row["id"]))
    return {"schema": SCHEMA, "status": "WEB_SKILL_STRUCTURE_CHECKED" if status == "STRUCTURE_CHECKED" else "WEB_SKILL_REJECTED", "skill_id": skill_id, "checks": checks, "execution": "NOT_EXECUTED", "verification_level": "STRUCTURE_ONLY"}


def sql_preview(sql: str) -> dict[str, Any]:
    source = str(sql or "")[:MAX_SQL]
    normalized = re.sub(r"/\*.*?\*/|--[^\n]*", " ", source, flags=re.DOTALL)
    normalized = " ".join(normalized.split())
    sha = _sha(normalized)
    first = (re.match(r"(?is)^\s*(?:with\b.*?\b)?([a-z]+)", normalized) or ["", ""])[1].upper()
    if normalized.upper().startswith("WITH"):
        first = "WITH"
    ctes = list(dict.fromkeys(match.group(1) for match in _SQL_CTE_RE.finditer(normalized)))
    tables = list(dict.fromkeys(match.group(1).replace('"', "") for match in _SQL_TABLE_RE.finditer(normalized)))
    nodes: list[dict[str, Any]] = [{"id": "statement", "kind": "STATEMENT", "label": first or "UNKNOWN"}]
    edges: list[dict[str, str]] = []
    for index, cte in enumerate(ctes):
        node_id = "cte-" + str(index)
        nodes.append({"id": node_id, "kind": "CTE", "label": cte})
        edges.append({"from": node_id, "to": "statement", "kind": "feeds"})
    for index, table in enumerate(tables[:64]):
        node_id = "table-" + str(index)
        nodes.append({"id": node_id, "kind": "SOURCE", "label": table})
        edges.append({"from": node_id, "to": "statement", "kind": "reads"})
    warnings: list[str] = []
    upper = normalized.upper()
    mutations = ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "CREATE", "GRANT", "REVOKE")
    if any(re.search(r"\b" + word + r"\b", upper) for word in mutations):
        warnings.append("MUTATING_STATEMENT")
    if "FOR UPDATE" in upper or "LOCK TABLE" in upper:
        warnings.append("LOCKING_STATEMENT")
    if "CROSS JOIN" in upper:
        warnings.append("CROSS_JOIN_REVIEW")
    if first in {"SELECT", "WITH"} and "WHERE" not in upper and tables:
        warnings.append("NO_FILTER_REVIEW")
    return {
        "schema": "gg.sql.intent-preview.v1",
        "sha256": sha,
        "executed": False,
        "database_connection": False,
        "statement": first or "UNKNOWN",
        "tables": tables[:64],
        "ctes": ctes[:32],
        "nodes": nodes,
        "edges": edges,
        "warnings": warnings,
        "risk": "HIGH" if any(item in warnings for item in ("MUTATING_STATEMENT", "LOCKING_STATEMENT")) else ("MEDIUM" if warnings else "LOW"),
        "summary": (first or "UNKNOWN") + " · " + str(len(tables)) + " source(s) · " + str(len(warnings)) + " warning(s)",
    }


def start_run(task_id: str = "", eval_name: str = "WORKBENCH") -> dict[str, Any]:
    run_id = 'run-' + uuid.uuid4().hex[:24]
    with _LOCK, _db() as connection:
        connection.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?,?)", (run_id, _scrub(task_id, 120), _scrub(eval_name, 120), "RUNNING", _now(), "", None, "{}"))
    return {"schema": SCHEMA, "status": "RUN_STARTED", "run_id": run_id}


def record_event(run_id: str, stage: str, status: str = "OK", duration_ms: int = 0, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        duration = max(0, min(86_400_000, int(duration_ms)))
    except (TypeError, ValueError):
        duration = 0
    safe_meta = metadata if isinstance(metadata, dict) else {}
    safe_meta = {str(key)[:48]: _scrub(value, 300) for key, value in list(safe_meta.items())[:24]}
    with _LOCK, _db() as connection:
        connection.execute("INSERT INTO events(run_id,stage,status,duration_ms,metadata_json,created_at) VALUES(?,?,?,?,?,?)", (str(run_id or "")[:120], _scrub(stage, 80), _scrub(status, 48).upper(), duration, _json(safe_meta), _now()))
        connection.execute("DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT ?)", (MAX_EVENTS,))
    return {"schema": SCHEMA, "status": "EVENT_RECORDED", "run_id": run_id, "stage": stage, "duration_ms": duration}


def finish_run(run_id: str, status: str = "PASS", score: float | None = None, metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    safe_status = _scrub(status, 48).upper() or "PASS"
    safe_metrics = metrics if isinstance(metrics, dict) else {}
    safe_metrics = {str(key)[:48]: _scrub(value, 300) for key, value in list(safe_metrics.items())[:32]}
    try:
        score_value = None if score is None else float(score)
    except (TypeError, ValueError):
        return {'schema': SCHEMA, 'status': 'ERROR', 'reason': 'SCORE_MUST_BE_BETWEEN_ZERO_AND_ONE'}
    if score_value is not None and (isinstance(score, bool) or not math.isfinite(score_value) or not 0 <= score_value <= 1):
        return {'schema': SCHEMA, 'status': 'ERROR', 'reason': 'SCORE_MUST_BE_BETWEEN_ZERO_AND_ONE'}
    with _LOCK, _db() as connection:
        cursor = connection.execute("UPDATE runs SET status=?, finished_at=?, score=?, metrics_json=? WHERE id=?", (safe_status, _now(), score_value, _json(safe_metrics), str(run_id or "")))
        if cursor.rowcount != 1:
            return {"schema": SCHEMA, "status": "RUN_NOT_FOUND", "run_id": run_id}
    return {"schema": SCHEMA, "status": "RUN_FINISHED", "run_id": run_id, "result": safe_status, "score": score_value}


def adaptive_execution_plan(text: str) -> dict[str, Any]:
    """Return a bounded DAG budget; this never creates model agents."""
    raw = " ".join(str(text or "").split())
    words = _tokens(raw)
    pieces = [part.strip() for part in re.split(r"\s+(?:och|and|sen|then|;|,)\s+", raw, flags=re.IGNORECASE) if part.strip()]
    work = bool(re.search(r"(?i)\b(fixa|bygg|koda|skapa|test|implement|research|jämför|gör|run|write)\b", raw))
    risk = "RED" if re.search(r"(?i)\b(password|lösenord|secret|wp-admin|one\.com|sudo)\b", raw) else ("YELLOW" if re.search(r"(?i)\b(live|deploy|production|mainnet|write|push|network|nätverk)\b", raw) else "GREEN")
    independent = max(1, min(8, len(pieces)))
    if not work:
        lanes, loops = 4, 1
    else:
        lanes = max(6, min(12, independent + 5))
        loops = 3 if risk != "GREEN" or len(words) > 60 else (2 if independent > 1 else 1)
    return {
        "mode": "BOUNDED_DAG" if work else "CONVERSATION",
        "lanes": lanes,
        "workers": min(lanes, 12),
        "loops": min(3, loops),
        "independent_units": independent,
        "risk": risk,
        "free_agent_brain": False,
        "model_agents": False,
        "action_authority": ACTION_AUTHORITY,
        "policy": "ADAPTIVE_BOUNDED_LANES_WITH_CODE_FRONT_MAN",
    }
