"""Motor-independent long-term memory on the laser-Merkle FactStore.

Deep Agents' missing layer is run → save what worked → load that lesson next
run, as files, without stuffing transcripts into every prompt. This module is
that loop for GG, on the existing tree:

- hot path: O(1) append of a compact episode (identity, not a dump)
- recall: token posting lists → nearby lesson identities (laser, not search)
- working set: bounded WORKING.md loaded on demand, like a skill description
- both GROK TUI and GPTUI read and write the same store

More lessons make recall tighter, not slower: exact query hits are cached,
posting lists stay capped, and the prompt only receives matching bullets.
This never grants action authority or promotes canonical policy.
"""

from __future__ import annotations

from backend.application_paths import STATE_ROOT

import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from backend.platform_support import file_locks as fcntl

if __package__:
    from .live_aid.contract import Fact
    from .live_aid.fact_store import FactStore, FactStoreError
else:
    from live_aid.contract import Fact
    from live_aid.fact_store import FactStore, FactStoreError


SCHEMA = "gg.long-memory.v1"
INDEX_SCHEMA = "gg.long-memory.index.v1"
ACTION_AUTHORITY = "NONE"
PROMOTION_AUTHORITY = "NONE"
CANONICAL_POLICY_CHANGE = False
MODEL_INFERENCE = False
NETWORK = "NONE"

TREE_ROOT = Path(
    str(STATE_ROOT / 'knowledge-tree')
)
INDEX_NAME = "memory-index.json"
WORKING_NAME = "WORKING.md"
LOCK_NAME = "memory-index.lock"

KINDS = frozenset({"episodic", "semantic", "procedural"})
MOTORS = frozenset({"GROK_TUI", "GPT_TUI", "QWEN", "SHARED"})
SKIP_QUERIES = frozenset({"session-start", "user-prompt"})
MAX_QUERY = 240
MAX_STATEMENT = 180
MAX_NOTE = 180
MAX_LESSONS = 512
MAX_POSTING = 48
MAX_WORKING_LINES = 48
MAX_RECALL = 6
MAX_INDEX_TOKENS = 12
MIN_QUERY = 16
_WORD_RE = re.compile(r"[\wÀ-ÖØ-öø-ÿ-]{3,}", re.UNICODE)
_SECRET_RE = re.compile(
    r"(password|lösenord|secret|token|api[_-]?key|begin [a-z]+ private)",
    re.IGNORECASE,
)
_HEX_RE = re.compile(r"\b[0-9a-f]{16,64}\b", re.IGNORECASE)
_STOP = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "your",
        "you",
        "are",
        "was",
        "have",
        "has",
        "not",
        "but",
        "jag",
        "du",
        "det",
        "den",
        "att",
        "och",
        "för",
        "med",
        "som",
        "en",
        "ett",
        "på",
        "av",
        "till",
        "om",
        "vi",
        "ni",
        "är",
        "var",
        "kan",
        "ska",
        "vill",
        "när",
        "hur",
        "vad",
        "alla",
        "allt",
        "the",
        "then",
        "than",
        "into",
        "over",
        "just",
        "also",
    }
)

_RECALL_CACHE: dict[str, tuple[tuple[dict[str, Any], ...], str]] = {}


class LongMemoryError(RuntimeError):
    pass


def _root(tree_root: Path | None = None) -> Path:
    env = os.environ.get("GG_LONG_MEMORY_ROOT", "").strip()
    if tree_root is not None:
        return Path(tree_root)
    if env:
        return Path(env)
    return TREE_ROOT


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _compact(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _strip_secrets(text: str) -> str:
    cleaned = _HEX_RE.sub("", text)
    return " ".join(cleaned.split())


def tokens(text: str, *, limit: int = MAX_INDEX_TOKENS) -> tuple[str, ...]:
    found: list[str] = []
    seen: set[str] = set()
    for raw in _WORD_RE.findall(str(text or "").casefold()):
        if raw in _STOP or raw in seen or len(raw) < 3:
            continue
        seen.add(raw)
        found.append(raw)
        if len(found) >= limit:
            break
    return tuple(found)


def _empty_index() -> dict[str, Any]:
    return {
        "schema": INDEX_SCHEMA,
        "lessons": {},
        "posting": {},
        "order": [],
    }


@contextmanager
def _locked(root: Path):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle = None
    try:
        handle = (root / LOCK_NAME).open("a+", encoding="utf-8")
        if fcntl is not None:
            fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        if handle is not None:
            try:
                if fcntl is not None:
                    fcntl.flock(handle, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                handle.close()
            except OSError:
                pass


def _index_path(root: Path) -> Path:
    return root / INDEX_NAME


def _working_path(root: Path) -> Path:
    return root / WORKING_NAME


def _read_index(root: Path) -> dict[str, Any]:
    path = _index_path(root)
    if not path.is_file():
        return _empty_index()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return _empty_index()
    if not isinstance(payload, dict):
        return _empty_index()
    lessons = payload.get("lessons")
    posting = payload.get("posting")
    order = payload.get("order")
    if not isinstance(lessons, dict):
        lessons = {}
    if not isinstance(posting, dict):
        posting = {}
    if not isinstance(order, list):
        order = []
    return {
        "schema": INDEX_SCHEMA,
        "lessons": lessons,
        "posting": posting,
        "order": [item for item in order if isinstance(item, str)],
    }


def _write_index(root: Path, payload: dict[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    body = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )
    fd, temporary_name = tempfile.mkstemp(
        prefix=".memory-index.",
        dir=str(root),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, _index_path(root))
        try:
            os.chmod(_index_path(root), 0o600)
        except OSError:
            pass
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass


def _lesson_id(kind: str, statement: str) -> str:
    return _sha("kind=" + kind + "\n" + statement)[:32]


def _trim_index(index: dict[str, Any]) -> None:
    order = list(index.get("order") or [])
    lessons = index.get("lessons") or {}
    if len(order) <= MAX_LESSONS:
        return
    drop = order[: len(order) - MAX_LESSONS]
    keep = set(order[len(order) - MAX_LESSONS :])
    index["order"] = order[len(order) - MAX_LESSONS :]
    for lesson_id in drop:
        lessons.pop(lesson_id, None)
    posting = index.get("posting") or {}
    for token, ids in list(posting.items()):
        if not isinstance(ids, list):
            posting.pop(token, None)
            continue
        trimmed = [item for item in ids if item in keep][-MAX_POSTING:]
        if trimmed:
            posting[token] = trimmed
        else:
            posting.pop(token, None)


def _cache_clear() -> None:
    _RECALL_CACHE.clear()


def capture(
    query: str,
    *,
    motor: str = "SHARED",
    kind: str = "episodic",
    note: str = "",
    outcome: str = "",
    tree_root: Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Append one compact lesson. Same statement is an identity hit, not a dump."""
    text = _strip_secrets(_compact(query, MAX_QUERY))
    kind_value = str(kind or "episodic").strip().lower()
    motor_value = str(motor or "SHARED").strip().upper() or "SHARED"
    if kind_value not in KINDS:
        return {
            "schema": SCHEMA,
            "status": "SKIPPED",
            "reason": "KIND_INVALID",
            "action_authority": ACTION_AUTHORITY,
        }
    if motor_value not in MOTORS:
        motor_value = "SHARED"
    if _SECRET_RE.search(text):
        return {
            "schema": SCHEMA,
            "status": "SKIPPED",
            "reason": "SECRET_BLOCKED",
            "action_authority": ACTION_AUTHORITY,
        }
    if not force and (len(text) < MIN_QUERY or text in SKIP_QUERIES):
        return {
            "schema": SCHEMA,
            "status": "SKIPPED",
            "reason": "QUERY_NOT_STORED",
            "action_authority": ACTION_AUTHORITY,
        }

    note_text = _strip_secrets(_compact(note, MAX_NOTE))
    outcome_text = _compact(outcome, 32)
    statement = _compact(
        note_text or text,
        MAX_STATEMENT,
    )
    if not statement:
        return {
            "schema": SCHEMA,
            "status": "SKIPPED",
            "reason": "STATEMENT_EMPTY",
            "action_authority": ACTION_AUTHORITY,
        }

    root = _root(tree_root)
    lesson_id = _lesson_id(kind_value, statement)
    query_sha = _sha(text)
    indexed = tokens(text + " " + statement)
    fact_id = ""
    store = FactStore(root)
    fact = Fact(
        key="gg.memory." + kind_value + "." + lesson_id,
        value={
            "kind": kind_value,
            "motor": motor_value,
            "statement": statement,
            "query": text,
            "outcome": outcome_text,
            "schema": SCHEMA,
        },
        epistemic_class="OBSERVED_CONTENT_BOUND",
        source_kind="LONG_MEMORY",
        source_id="memory:" + kind_value,
        source_sha256=query_sha,
        scope="WORKSPACE_SHARED",
        freshness="CONTENT_BOUND",
    )
    try:
        fact_id = store.append(fact)
    except FactStoreError:
        fact_id = ""

    with _locked(root):
        index = _read_index(root)
        lessons = index["lessons"]
        existing = lessons.get(lesson_id)
        if isinstance(existing, dict):
            support = int(existing.get("support") or 1) + 1
            motors = existing.get("motors")
            if not isinstance(motors, list):
                motors = [str(existing.get("motor") or motor_value)]
            if motor_value not in motors:
                motors.append(motor_value)
            existing["support"] = support
            existing["motors"] = motors[-4:]
            existing["query_sha256"] = query_sha
            existing["kind"] = kind_value
            existing["statement"] = statement
            hit = "IDENTITY"
        else:
            support = 1
            lessons[lesson_id] = {
                "kind": kind_value,
                "statement": statement,
                "motor": motor_value,
                "motors": [motor_value],
                "support": 1,
                "query_sha256": query_sha,
                "tokens": list(indexed),
            }
            hit = "NEW"
        order = [item for item in index["order"] if item != lesson_id]
        order.append(lesson_id)
        index["order"] = order
        posting = index["posting"]
        for token in indexed:
            ids = posting.get(token)
            if not isinstance(ids, list):
                ids = []
            ids = [item for item in ids if item != lesson_id]
            ids.append(lesson_id)
            posting[token] = ids[-MAX_POSTING:]
        _trim_index(index)
        _write_index(root, index)
    _cache_clear()
    return {
        "schema": SCHEMA,
        "status": "RECORDED",
        "lesson_id": lesson_id,
        "kind": kind_value,
        "motor": motor_value,
        "hit": hit,
        "support": support,
        "fact_id": fact_id,
        "tokens": list(indexed),
        "action_authority": ACTION_AUTHORITY,
        "promotion_authority": PROMOTION_AUTHORITY,
        "canonical_policy_change": CANONICAL_POLICY_CHANGE,
        "model_inference": MODEL_INFERENCE,
        "network": NETWORK,
    }


def recall(
    query: str,
    *,
    limit: int = MAX_RECALL,
    tree_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Return compact matching lessons. Exact query is an identity cache hit."""
    text = _strip_secrets(_compact(query, MAX_QUERY))
    try:
        cap = max(1, min(int(limit), MAX_RECALL))
    except (TypeError, ValueError):
        cap = MAX_RECALL
    query_sha = _sha(text)
    cached = _RECALL_CACHE.get(query_sha)
    root = _root(tree_root)
    root_key = str(root)
    if cached is not None and cached[1] == root_key:
        return [dict(item) for item in cached[0][:cap]]

    wanted = tokens(text)
    with _locked(root):
        index = _read_index(root)
    lessons = index.get("lessons") or {}
    posting = index.get("posting") or {}
    scores: dict[str, int] = {}
    for token in wanted:
        ids = posting.get(token)
        if not isinstance(ids, list):
            continue
        for lesson_id in ids:
            row = lessons.get(lesson_id)
            if not isinstance(row, dict):
                continue
            support = int(row.get("support") or 1)
            scores[lesson_id] = scores.get(lesson_id, 0) + support
            if str(row.get("query_sha256") or "") == query_sha:
                scores[lesson_id] += 8

    ranked = sorted(
        scores.items(),
        key=lambda item: (-item[1], item[0]),
    )
    hits: list[dict[str, Any]] = []
    for lesson_id, score in ranked:
        row = lessons.get(lesson_id)
        if not isinstance(row, dict):
            continue
        statement = _compact(row.get("statement") or "", MAX_STATEMENT)
        if not statement:
            continue
        hits.append(
            {
                "lesson_id": lesson_id,
                "kind": str(row.get("kind") or "episodic"),
                "statement": statement,
                "support": int(row.get("support") or 1),
                "score": score,
                "motor": str(row.get("motor") or "SHARED"),
            }
        )
        if len(hits) >= cap:
            break
    _RECALL_CACHE[query_sha] = (tuple(hits), root_key)
    if len(_RECALL_CACHE) > 64:
        oldest = next(iter(_RECALL_CACHE))
        _RECALL_CACHE.pop(oldest, None)
    return [dict(item) for item in hits]


def density(*, tree_root: Path | None = None) -> float:
    """0..1 working-set fill. MEMORY node uses this instead of scanning facts."""
    root = _root(tree_root)
    with _locked(root):
        index = _read_index(root)
    count = len(index.get("order") or [])
    if count <= 0:
        return 0.0
    return round(min(1.0, count / 64.0), 4)


def consolidate(*, tree_root: Path | None = None) -> dict[str, Any]:
    """Sleep-time merge: rebuild the bounded WORKING.md from highest-support lessons."""
    root = _root(tree_root)
    with _locked(root):
        index = _read_index(root)
        lessons = index.get("lessons") or {}
        order = list(index.get("order") or [])
        ranked = sorted(
            (
                (
                    int((lessons.get(lesson_id) or {}).get("support") or 0),
                    position,
                    lesson_id,
                )
                for position, lesson_id in enumerate(order)
                if isinstance(lessons.get(lesson_id), dict)
            ),
            key=lambda item: (-item[0], -item[1]),
        )
        lines = [
            "# GG long memory",
            "schema=" + SCHEMA,
            "motor=SHARED",
            "retrieval=LASER_IDENTITY",
            "",
        ]
        kept = 0
        for _support, _position, lesson_id in ranked:
            row = lessons.get(lesson_id) or {}
            statement = _compact(row.get("statement") or "", MAX_STATEMENT)
            kind_value = str(row.get("kind") or "episodic")
            if not statement:
                continue
            lines.append("- [" + kind_value + "] " + statement)
            kept += 1
            if kept >= MAX_WORKING_LINES:
                break
        body = "\n".join(lines) + "\n"
        target = _working_path(root)
        target.write_text(body, encoding="utf-8")
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
        working_sha = _sha(body)
    _cache_clear()
    return {
        "schema": SCHEMA,
        "status": "CONSOLIDATED",
        "lessons": kept,
        "working_sha256": working_sha,
        "path": str(target),
        "action_authority": ACTION_AUTHORITY,
        "promotion_authority": PROMOTION_AUTHORITY,
        "canonical_policy_change": CANONICAL_POLICY_CHANGE,
    }


def render(
    query: str,
    *,
    budget: int = 900,
    tree_root: Path | None = None,
) -> str:
    """Bounded prompt block. Empty when nothing matches — never a transcript dump."""
    try:
        cap = max(0, int(budget))
    except (TypeError, ValueError):
        cap = 900
    if cap < 80:
        return ""
    hits = recall(query, tree_root=tree_root)
    if not hits:
        return ""
    lines = [
        "[GG LONG MEMORY]",
        "schema=" + SCHEMA,
        "retrieval=LASER_IDENTITY",
        "lessons=" + str(len(hits)),
    ]
    for hit in hits:
        lines.append(
            "- ["
            + str(hit.get("kind") or "episodic")
            + "] "
            + str(hit.get("statement") or "")
        )
    lines.append("[/GG LONG MEMORY]")
    text = "\n".join(lines)
    if len(text) <= cap:
        return text
    trimmed = text[: cap - 18].rstrip() + "\n[/GG LONG MEMORY]"
    if "[GG LONG MEMORY]" not in trimmed:
        return ""
    return trimmed
