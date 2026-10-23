"""Grok TUI adapter over the existing laser-Merkle knowledge tree.

Qwen already uses SOURCE-MANIFEST as the head, LaserFocus for O(1) handles,
and compile_neighborhood for hash-nearness. This module is the same path for
Grok TUI: identity in, nearby hashes out, miss-closed on drift.

It does not dump file bodies, grant action authority, or promote policy.
Tree growth is append-only FactStore observations bound to exact hashes.
"""

from __future__ import annotations

from backend.application_paths import STATE_ROOT
from backend.platform_support import workspace_root, desktop_relative_path

import argparse
import ast
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

if __package__:
    from . import capability_registry as _capability_registry
    from . import domain_merkle as _domain_merkle
    from . import neighborhood_compiler as _neighborhood_compiler
    from . import solver_router as _solver_router
    from .live_aid.contract import Fact
    from .live_aid.fact_store import FactStore, FactStoreError
else:
    import capability_registry as _capability_registry
    import domain_merkle as _domain_merkle
    import neighborhood_compiler as _neighborhood_compiler
    import solver_router as _solver_router
    from live_aid.contract import Fact
    from live_aid.fact_store import FactStore, FactStoreError

CapabilityRegistry = _capability_registry.CapabilityRegistry
CapabilityRegistryError = _capability_registry.CapabilityRegistryError
# Neighborhood compiler imports compiled_focus via sys.path, not the
# package. Reuse that class object or isinstance() miss-closes.
FocusDependency = _neighborhood_compiler.FocusDependency
digest_json = _domain_merkle.digest_json
NeighborhoodRequest = _neighborhood_compiler.NeighborhoodRequest
compile_neighborhood = _neighborhood_compiler.compile_neighborhood
NeighborhoodCompilerError = _neighborhood_compiler.NeighborhoodCompilerError
LaserFocusCache = _solver_router.LaserFocusCache
RouteContext = _solver_router.RouteContext
SolverRouter = _solver_router.SolverRouter
SolverRouterError = _solver_router.SolverRouterError


SCHEMA = "gg.grok-knowledge-tree.v1"
HEAD_RELATIVE = desktop_relative_path("SOURCE-MANIFEST.json")
ACTION_AUTHORITY = "NONE"
PROMOTION_AUTHORITY = "NONE"
CANONICAL_POLICY_CHANGE = False
MODEL_INFERENCE = False
NETWORK = "NONE"

DESKTOP_PROJECT = Path(__file__).resolve().parents[1]
REPO_ROOT = workspace_root()
TREE_ROOT = Path(
    str(STATE_ROOT / 'knowledge-tree')
)
HEAD_SNAPSHOT = "HEAD.json"
RECORD_KINDS = frozenset({"thought", "action", "code", "session"})
WRITE_TOOLS = frozenset(
    {
        "search_replace",
        "write",
        "Write",
        "Edit",
        "MultiEdit",
    }
)
MAX_QUERY = 1024
MAX_PATH = 1024
MAX_PROMPT_STORE = 240
MAX_RECENT = 12
WORKPLACE_QUERY = "laser merkle neighborhood compiled focus knowledge"
SKIP_QUERIES = frozenset({"session-start", "user-prompt"})
CALL_CODE_RE = re.compile(
    r"(?:sha\s*call\s*(?:kod|code)\s*=\s*)?([0-9a-f]{8,64})",
    re.IGNORECASE,
)
DESKTOP_PREFIX = "" if DESKTOP_PROJECT == REPO_ROOT else DESKTOP_PROJECT.relative_to(REPO_ROOT).as_posix() + "/"


class GrokKnowledgeTreeError(RuntimeError):
    pass


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def load_head(*, project_root: Path | None = None) -> dict[str, Any]:
    root = (project_root or DESKTOP_PROJECT).resolve(strict=True)
    path = root / "SOURCE-MANIFEST.json"
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    files = payload.get("files")
    if not isinstance(files, dict) or not files:
        raise GrokKnowledgeTreeError("HEAD_FILES_INVALID")
    return {
        "schema": SCHEMA,
        "head_relative": HEAD_RELATIVE,
        "head_path": str(path),
        "head_sha256": _sha256_bytes(raw),
        "files": files,
        "project_root": root,
        "repo_root": root.parents[1],
    }


def _load_registry(head: dict[str, Any]) -> CapabilityRegistry:
    project_root = head["project_root"]
    return CapabilityRegistry.load(
        repo_root=head["repo_root"],
        project_root=project_root,
        seed_path=project_root / "config" / "capability-seeds-v1.json",
        manifest_path=project_root / "SOURCE-MANIFEST.json",
    )


def read_head_snapshot(*, tree_root: Path | None = None) -> dict[str, Any]:
    path = Path(tree_root or TREE_ROOT) / HEAD_SNAPSHOT
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _recent_facts(tree_root: Path) -> list[dict[str, str]]:
    store = FactStore(tree_root)
    index = store.index
    if not index.is_file():
        return []
    lines = [
        line
        for line in index.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    recent: list[dict[str, str]] = []
    for raw in reversed(lines[-MAX_RECENT:]):
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        fact_id = row.get("fact_id")
        if not isinstance(fact_id, str):
            continue
        try:
            fact = store.get(fact_id)
        except FactStoreError:
            continue
        value = fact.value if isinstance(fact.value, dict) else {}
        recent.append(
            {
                "fact_id": fact.fact_id,
                "kind": str(value.get("kind") or ""),
                "path": str(value.get("path") or fact.source_id),
                "query": str(value.get("query") or "")[:MAX_PROMPT_STORE],
            }
        )
    return recent


def _compile_neighborhood(
    text: str,
    *,
    identity: str,
    head: dict[str, Any],
    files: dict[str, Any],
    registry: CapabilityRegistry,
    router: SolverRouter,
) -> Any:
    source_identity_map = {
        record.source_path: record.content_sha256
        for record in registry.records()
    }
    request = NeighborhoodRequest(
        query=text,
        task_identity_sha256=digest_json(
            {"engine": "GROK_TUI", "object_id": identity}
        ),
        focus_domain="task.neighborhood",
        focus_id="grok-tui",
        source_identity_map=source_identity_map,
        relevant_roots=(
            FocusDependency(
                namespace="knowledge.generic",
                root_sha256=head["head_sha256"],
            ),
            FocusDependency(
                namespace="knowledge.machine",
                root_sha256=digest_json(
                    {
                        "laser": files["backend/solver_router.py"],
                        "focus": files["backend/compiled_focus.py"],
                        "merkle": files["backend/domain_merkle.py"],
                    }
                ),
            ),
            FocusDependency(
                namespace="policy",
                root_sha256=router.policy_revision_sha256,
            ),
        ),
        policy_revision_sha256=router.policy_revision_sha256,
        focus_compiler_revision_sha256=files["backend/compiled_focus.py"],
        neighborhood_compiler_revision_sha256=files[
            "backend/neighborhood_compiler.py"
        ],
        semantic_depth=2,
        max_semantic_items=32,
        max_source_items=32,
    )
    return compile_neighborhood(request, registry)


def _desktop_path(rel: str) -> str:
    value = str(rel or "").strip().lstrip("./")
    if value.startswith(DESKTOP_PREFIX):
        return value
    return DESKTOP_PREFIX + value


def extract_call_codes(text: str) -> tuple[str, ...]:
    found: list[str] = []
    seen: set[str] = set()
    for match in CALL_CODE_RE.finditer(str(text or "")):
        code = match.group(1).lower()
        if (
            code in seen
            or len(code) < 8
            or not all(character in "0123456789abcdef" for character in code)
        ):
            continue
        seen.add(code)
        found.append(code)
    return tuple(found)


def _symbol_rows(path: Path, relative_path: str, live_sha: str) -> list[dict[str, Any]]:
    if path.suffix != ".py":
        return []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative_path)
    except (OSError, UnicodeDecodeError, SyntaxError):
        return []
    rows: list[dict[str, Any]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            rows.append(
                {
                    "name": node.name,
                    "kind": (
                        "class"
                        if isinstance(node, ast.ClassDef)
                        else "function"
                    ),
                    "line": int(node.lineno),
                    "path": _desktop_path(relative_path),
                    "sha256": live_sha,
                }
            )
    return rows


def _record_file_symbols(
    *,
    relative_path: str,
    live_sha: str,
    path: Path,
    query: str,
    head_sha256: str,
    tree_root: Path,
) -> list[str]:
    store = FactStore(tree_root)
    ids: list[str] = []
    for row in _symbol_rows(path, relative_path, live_sha):
        fact = Fact(
            key="grok.tree.symbol." + live_sha[:16] + "." + row["name"],
            value={
                "query": query[:MAX_PROMPT_STORE],
                "path": row["path"],
                "kind": "symbol",
                "name": row["name"],
                "symbol_kind": row["kind"],
                "line": row["line"],
                "head_sha256": head_sha256,
            },
            epistemic_class="OBSERVED_CONTENT_BOUND",
            source_kind="GROK_TUI_TREE",
            source_id=row["path"],
            source_sha256=live_sha,
            scope="REPOSITORY_SOURCE@" + head_sha256,
            freshness="CONTENT_BOUND",
        )
        try:
            ids.append(store.append(fact))
        except FactStoreError:
            continue
    return ids


def call_hashes(
    codes: list[str] | tuple[str, ...],
    *,
    project_root: Path | None = None,
    tree_root: Path | None = None,
) -> dict[str, Any]:
    normalized: list[str] = []
    for raw in codes:
        code = str(raw or "").strip().lower()
        if code.startswith("sha256:"):
            code = code[7:]
        if len(code) < 8 or len(code) > 64:
            return {
                "schema": SCHEMA,
                "status": "MISS_CLOSED",
                "reason": "CALL_CODE_INVALID",
                "action_authority": ACTION_AUTHORITY,
            }
        if not all(character in "0123456789abcdef" for character in code):
            return {
                "schema": SCHEMA,
                "status": "MISS_CLOSED",
                "reason": "CALL_CODE_INVALID",
                "action_authority": ACTION_AUTHORITY,
            }
        normalized.append(code)
    if not normalized:
        return {
            "schema": SCHEMA,
            "status": "MISS_CLOSED",
            "reason": "CALL_CODE_INVALID",
            "action_authority": ACTION_AUTHORITY,
        }

    head = load_head(project_root=project_root)
    files = head["files"]
    repo = head["repo_root"]
    store = FactStore(tree_root or TREE_ROOT)
    index_path = store.index
    fact_rows: list[dict[str, str]] = []
    if index_path.is_file():
        for raw in index_path.read_text(encoding="utf-8").splitlines():
            if raw.strip():
                try:
                    row = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    fact_rows.append(row)

    calls: list[dict[str, Any]] = []
    for code in normalized:
        matches: list[dict[str, Any]] = []
        for rel, digest in files.items():
            if not isinstance(digest, str) or not digest.startswith(code):
                continue
            matches.append(
                {
                    "path": _desktop_path(rel),
                    "sha256": digest,
                    "kind": "source",
                    "name": Path(rel).name,
                }
            )
        for row in fact_rows:
            fact_id = str(row.get("fact_id") or "")
            try:
                fact = store.get(fact_id)
            except FactStoreError:
                continue
            if not str(fact.source_sha256).startswith(code) and not fact_id.replace(
                "fact-", ""
            ).startswith(code):
                continue
            value = fact.value if isinstance(fact.value, dict) else {}
            matches.append(
                {
                    "path": str(value.get("path") or fact.source_id),
                    "sha256": fact.source_sha256,
                    "kind": str(value.get("kind") or "fact"),
                    "name": str(value.get("name") or ""),
                }
            )
        unique: dict[str, dict[str, Any]] = {}
        for item in matches:
            sha = item["sha256"]
            if sha not in unique:
                unique[sha] = item
            elif item.get("name") and not unique[sha].get("name"):
                unique[sha] = item
        if not unique:
            return {
                "schema": SCHEMA,
                "status": "MISS_CLOSED",
                "reason": "CALL_UNKNOWN:" + code,
                "head_sha256": head["head_sha256"],
                "action_authority": ACTION_AUTHORITY,
            }
        if len(unique) > 1:
            return {
                "schema": SCHEMA,
                "status": "MISS_CLOSED",
                "reason": "CALL_AMBIGUOUS:" + code,
                "head_sha256": head["head_sha256"],
                "action_authority": ACTION_AUTHORITY,
            }
        hit = next(iter(unique.values()))
        rel = str(hit["path"])
        if rel.startswith(DESKTOP_PREFIX):
            live_path = repo / rel
        else:
            live_path = repo / rel
        if live_path.is_file():
            live_sha = _sha256_file(live_path)
            if live_sha != hit["sha256"]:
                return {
                    "schema": SCHEMA,
                    "status": "STALE_BLOCKED",
                    "reason": "SOURCE_IDENTITY_DRIFT:" + rel,
                    "head_sha256": head["head_sha256"],
                    "live_sha256": live_sha,
                    "manifest_sha256": hit["sha256"],
                    "action_authority": ACTION_AUTHORITY,
                }
        symbols = _symbol_rows(live_path, rel, hit["sha256"]) if live_path.is_file() else []
        hit["symbols"] = [
            {"name": row["name"], "kind": row["kind"], "line": row["line"]}
            for row in symbols
        ]
        calls.append(hit)

    return {
        "schema": SCHEMA,
        "status": "READY",
        "head_relative": HEAD_RELATIVE,
        "head_sha256": head["head_sha256"],
        "calls": calls,
        "action_authority": ACTION_AUTHORITY,
        "promotion_authority": PROMOTION_AUTHORITY,
        "canonical_policy_change": CANONICAL_POLICY_CHANGE,
        "model_inference": MODEL_INFERENCE,
        "network": NETWORK,
    }


def lookup(
    query: str,
    *,
    object_id: str = "ws.tui.grok",
    project_root: Path | None = None,
) -> dict[str, Any]:
    text = " ".join(str(query or "").split())
    if not text or len(text) > MAX_QUERY:
        raise GrokKnowledgeTreeError("QUERY_INVALID")
    identity = str(object_id or "").strip() or "ws.tui.grok"
    if len(identity) > MAX_QUERY:
        raise GrokKnowledgeTreeError("OBJECT_ID_INVALID")

    head = load_head(project_root=project_root)
    files = head["files"]
    try:
        registry = _load_registry(head)
    except CapabilityRegistryError as exc:
        return {
            "schema": SCHEMA,
            "status": "STALE_BLOCKED",
            "reason": str(exc),
            "head_relative": HEAD_RELATIVE,
            "head_sha256": head["head_sha256"],
            "action_authority": ACTION_AUTHORITY,
            "promotion_authority": PROMOTION_AUTHORITY,
            "canonical_policy_change": CANONICAL_POLICY_CHANGE,
        }

    router = SolverRouter(registry)
    laser = LaserFocusCache(router)
    source_revision = str(files.get("backend/solver_router.py") or "")
    if not _valid_sha256(source_revision):
        raise GrokKnowledgeTreeError("LASER_SOURCE_REVISION_MISSING")

    try:
        context = RouteContext(
            query=text[:1024],
            goal_id="goal-grok-tree",
            object_id=identity,
            source_revision=source_revision,
            language="python",
            diagnostic_class="GROK_TUI_KNOWLEDGE",
        )
        binding = laser.bind(context)
        handle = laser.lookup(binding.handle_id)
    except SolverRouterError as exc:
        return {
            "schema": SCHEMA,
            "status": "MISS_CLOSED",
            "reason": str(exc),
            "head_sha256": head["head_sha256"],
            "action_authority": ACTION_AUTHORITY,
        }

    if handle is None:
        return {
            "schema": SCHEMA,
            "status": "MISS_CLOSED",
            "reason": "LASER_FOCUS_HANDLE_MISSING",
            "head_sha256": head["head_sha256"],
            "query": text,
            "action_authority": ACTION_AUTHORITY,
        }

    route = handle.route.as_dict()
    laser = {
        "handle_id": binding.handle_id,
        "binding_sha256": binding.binding_sha256,
        "source_revision": binding.source_revision,
        "selected": route.get("selected_capability_id"),
        "working_set": route.get("working_set"),
        "why": route.get("why"),
    }
    codes = extract_call_codes(text)
    if codes:
        resolved = call_hashes(
            codes,
            project_root=project_root,
        )
        if resolved.get("status") == "READY":
            calls = list(resolved.get("calls") or [])
            sources = [
                {"path": item["path"], "sha256": item["sha256"]}
                for item in calls
            ]
            return {
                "schema": SCHEMA,
                "status": "READY",
                "head_relative": HEAD_RELATIVE,
                "head_sha256": head["head_sha256"],
                "query": text,
                "query_sha256": digest_json({"schema": SCHEMA, "query": text}),
                "laser": laser,
                "calls": calls,
                "neighborhood": {
                    "handle_id": digest_json(
                        {"calls": [item["sha256"] for item in calls]}
                    ),
                    "origin": "CALL",
                    "task_root_sha256": digest_json(
                        {"engine": "GROK_TUI", "query": text}
                    ),
                    "source_root_sha256": digest_json(
                        {"sources": [item["sha256"] for item in calls]}
                    ),
                    "capability_root_sha256": digest_json({"calls": True}),
                    "semantic": [],
                    "sources": sources,
                },
                "action_authority": ACTION_AUTHORITY,
                "promotion_authority": PROMOTION_AUTHORITY,
                "canonical_policy_change": CANONICAL_POLICY_CHANGE,
                "model_inference": MODEL_INFERENCE,
                "network": NETWORK,
            }
    origin = "QUERY"
    reason = None
    try:
        neighborhood = _compile_neighborhood(
            text,
            identity=identity,
            head=head,
            files=files,
            registry=registry,
            router=router,
        )
    except NeighborhoodCompilerError as exc:
        if str(exc) != "SEMANTIC_NEIGHBORHOOD_EMPTY" or text == WORKPLACE_QUERY:
            return {
                "schema": SCHEMA,
                "status": "MISS_CLOSED",
                "reason": str(exc),
                "head_sha256": head["head_sha256"],
                "query": text,
                "laser": laser,
                "action_authority": ACTION_AUTHORITY,
            }
        try:
            neighborhood = _compile_neighborhood(
                WORKPLACE_QUERY,
                identity=identity,
                head=head,
                files=files,
                registry=registry,
                router=router,
            )
        except NeighborhoodCompilerError as fallback_exc:
            return {
                "schema": SCHEMA,
                "status": "MISS_CLOSED",
                "reason": str(fallback_exc),
                "head_sha256": head["head_sha256"],
                "query": text,
                "laser": laser,
                "action_authority": ACTION_AUTHORITY,
            }
        origin = "WORKPLACE_DEFAULT"
        reason = "SEMANTIC_NEIGHBORHOOD_EMPTY"

    query_sha256 = (
        neighborhood.query_sha256
        if origin == "QUERY"
        else digest_json({"schema": SCHEMA, "query": text})
    )
    payload = {
        "schema": SCHEMA,
        "status": "READY",
        "head_relative": HEAD_RELATIVE,
        "head_sha256": head["head_sha256"],
        "query": text,
        "query_sha256": query_sha256,
        "laser": laser,
        "neighborhood": {
            "handle_id": neighborhood.handle.handle_id,
            "origin": origin,
            "task_root_sha256": neighborhood.task_root_sha256,
            "source_root_sha256": neighborhood.source_root_sha256,
            "capability_root_sha256": neighborhood.capability_root_sha256,
            "semantic": [
                {
                    "id": item.human_id,
                    "path": item.source_path,
                    "sha256": item.execution_revision_sha256,
                }
                for item in neighborhood.semantic_items
            ],
            "sources": [
                {
                    "path": item.source_path,
                    "sha256": item.content_sha256,
                }
                for item in neighborhood.source_items
            ],
        },
        "action_authority": ACTION_AUTHORITY,
        "promotion_authority": PROMOTION_AUTHORITY,
        "canonical_policy_change": CANONICAL_POLICY_CHANGE,
        "model_inference": MODEL_INFERENCE,
        "network": NETWORK,
    }
    if reason is not None:
        payload["reason"] = reason
    return payload


def record(
    query: str,
    *,
    relative_path: str,
    kind: str,
    project_root: Path | None = None,
    tree_root: Path | None = None,
) -> dict[str, Any]:
    text = " ".join(str(query or "").split())
    if not text or len(text) > MAX_QUERY:
        raise GrokKnowledgeTreeError("QUERY_INVALID")
    kind_value = str(kind or "").strip().lower()
    if kind_value not in RECORD_KINDS:
        raise GrokKnowledgeTreeError("RECORD_KIND_INVALID")
    rel = str(relative_path or "").strip().lstrip("./")
    if not rel or len(rel) > MAX_PATH or ".." in Path(rel).parts:
        raise GrokKnowledgeTreeError("PATH_INVALID")

    head = load_head(project_root=project_root)
    repo = head["repo_root"]
    candidate = (repo / rel).resolve()
    if not candidate.is_relative_to(repo) or not candidate.is_file():
        raise GrokKnowledgeTreeError("PATH_UNBOUND")
    live_sha = _sha256_file(candidate)
    manifest_key = rel
    prefix = "projects/gg-ai-desktop/"
    if rel.startswith(prefix):
        manifest_key = rel[len(prefix) :]
    expected = head["files"].get(manifest_key)
    if expected is not None and expected != live_sha:
        return {
            "schema": SCHEMA,
            "status": "STALE_BLOCKED",
            "reason": "SOURCE_IDENTITY_DRIFT:" + rel,
            "head_sha256": head["head_sha256"],
            "live_sha256": live_sha,
            "manifest_sha256": expected,
            "action_authority": ACTION_AUTHORITY,
        }

    store = FactStore(tree_root or TREE_ROOT)
    fact = Fact(
        key="grok.tree." + kind_value + "." + live_sha[:16],
        value={
            "query": text,
            "path": rel,
            "kind": kind_value,
            "head_sha256": head["head_sha256"],
        },
        epistemic_class="OBSERVED_CONTENT_BOUND",
        source_kind="GROK_TUI_TREE",
        source_id=rel,
        source_sha256=live_sha,
        scope="REPOSITORY_SOURCE@" + head["head_sha256"],
        freshness="CONTENT_BOUND",
    )
    try:
        fact_id = store.append(fact)
    except FactStoreError as exc:
        raise GrokKnowledgeTreeError("FACT_APPEND_FAILED:" + str(exc)) from exc
    symbol_ids = _record_file_symbols(
        relative_path=rel,
        live_sha=live_sha,
        path=candidate,
        query=text,
        head_sha256=head["head_sha256"],
        tree_root=tree_root or TREE_ROOT,
    )
    return {
        "schema": SCHEMA,
        "status": "RECORDED",
        "fact_id": fact_id,
        "path": rel,
        "kind": kind_value,
        "source_sha256": live_sha,
        "call_code": live_sha[:16],
        "calls": [
            {
                "path": _desktop_path(rel),
                "sha256": live_sha,
                "kind": kind_value,
                "call_code": live_sha[:16],
            }
        ],
        "symbol_fact_ids": symbol_ids,
        "head_sha256": head["head_sha256"],
        "action_authority": ACTION_AUTHORITY,
        "promotion_authority": PROMOTION_AUTHORITY,
        "canonical_policy_change": CANONICAL_POLICY_CHANGE,
    }


def record_thought(
    query: str,
    *,
    laser_handle: str | None = None,
    project_root: Path | None = None,
    tree_root: Path | None = None,
) -> dict[str, Any]:
    text = " ".join(str(query or "").split())
    if not text or len(text) > MAX_QUERY:
        raise GrokKnowledgeTreeError("QUERY_INVALID")
    if text in SKIP_QUERIES:
        return {
            "schema": SCHEMA,
            "status": "SKIPPED",
            "reason": "QUERY_NOT_STORED",
            "action_authority": ACTION_AUTHORITY,
        }
    head = load_head(project_root=project_root)
    query_sha = _sha256_bytes(text.encode("utf-8"))
    store = FactStore(tree_root or TREE_ROOT)
    fact = Fact(
        key="grok.tree.thought." + query_sha[:16],
        value={
            "query": text[:MAX_PROMPT_STORE],
            "path": "prompt",
            "kind": "thought",
            "head_sha256": head["head_sha256"],
            "laser_handle": laser_handle,
        },
        epistemic_class="OBSERVED_CONTENT_BOUND",
        source_kind="GROK_TUI_TREE",
        source_id="prompt",
        source_sha256=query_sha,
        scope="REPOSITORY_SOURCE@" + head["head_sha256"],
        freshness="CONTENT_BOUND",
    )
    try:
        fact_id = store.append(fact)
    except FactStoreError as exc:
        raise GrokKnowledgeTreeError("FACT_APPEND_FAILED:" + str(exc)) from exc
    return {
        "schema": SCHEMA,
        "status": "RECORDED",
        "fact_id": fact_id,
        "path": "prompt",
        "kind": "thought",
        "source_sha256": query_sha,
        "head_sha256": head["head_sha256"],
        "action_authority": ACTION_AUTHORITY,
        "promotion_authority": PROMOTION_AUTHORITY,
        "canonical_policy_change": CANONICAL_POLICY_CHANGE,
    }


def write_head_snapshot(
    payload: dict[str, Any],
    *,
    tree_root: Path | None = None,
) -> Path:
    root = Path(tree_root or TREE_ROOT)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    prior = read_head_snapshot(tree_root=root)
    neighborhood = payload.get("neighborhood") or {}
    sources = list(neighborhood.get("sources") or [])
    neighborhood_handle = neighborhood.get("handle_id")
    origin = neighborhood.get("origin")
    if (
        not sources
        and prior.get("head_sha256") == payload.get("head_sha256")
        and prior.get("sources")
    ):
        sources = list(prior.get("sources") or [])
        neighborhood_handle = prior.get("neighborhood_handle")
        origin = origin or "PRIOR"
    compact = {
        "schema": SCHEMA,
        "status": payload.get("status") or "READY",
        "head_relative": HEAD_RELATIVE,
        "head_sha256": payload.get("head_sha256"),
        "query": payload.get("query"),
        "query_sha256": payload.get("query_sha256"),
        "laser_handle": (payload.get("laser") or {}).get("handle_id")
        or payload.get("laser_handle"),
        "neighborhood_handle": neighborhood_handle,
        "origin": origin,
        "reason": payload.get("reason"),
        "sources": sources,
        "recent": payload.get("recent") or _recent_facts(root),
        "calls": payload.get("calls") or [],
        "path": payload.get("path"),
        "kind": payload.get("kind"),
        "action_authority": ACTION_AUTHORITY,
    }
    target = root / HEAD_SNAPSHOT
    target.write_text(
        json.dumps(compact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def _event_name(event: dict[str, Any]) -> str:
    raw = str(
        event.get("hookEventName")
        or event.get("event")
        or os.environ.get("GROK_HOOK_EVENT")
        or ""
    ).strip().lower()
    return raw.replace("-", "_")


def _prompt_text(event: dict[str, Any]) -> str:
    for key in (
        "prompt",
        "userPrompt",
        "text",
        "query",
        "content",
        "message",
        "promptText",
    ):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())[:MAX_QUERY]
        if isinstance(value, list):
            parts: list[str] = []
            for item in value:
                if isinstance(item, str) and item.strip():
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text") or item.get("content")
                    if isinstance(text, str) and text.strip():
                        parts.append(text)
            joined = " ".join(parts).strip()
            if joined:
                return " ".join(joined.split())[:MAX_QUERY]
    nested = event.get("hookSpecificInput")
    if isinstance(nested, dict):
        return _prompt_text(nested)
    return ""


def _repo_relative(path_text: str, repo: Path) -> str:
    raw = str(path_text or "").strip()
    if not raw:
        return ""
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = (repo / raw).resolve()
    else:
        candidate = candidate.resolve()
    if not candidate.is_relative_to(repo):
        return ""
    return candidate.relative_to(repo).as_posix()


def _tool_path(event: dict[str, Any], repo: Path) -> str:
    tool_input = event.get("toolInput")
    if not isinstance(tool_input, dict):
        return ""
    for key in ("file_path", "target_file", "path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return _repo_relative(value, repo)
    return ""


def _capture_long_memory(
    query: str,
    *,
    motor: str,
    kind: str,
    note: str,
    tree_root: Path | None = None,
) -> None:
    try:
        if __package__:
            from . import long_memory as _long_memory
        else:
            import long_memory as _long_memory
        _long_memory.capture(
            query,
            motor=motor,
            kind=kind,
            note=note,
            tree_root=tree_root,
        )
    except Exception:
        return


def observe_event(
    event: dict[str, Any],
    *,
    project_root: Path | None = None,
    tree_root: Path | None = None,
) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise GrokKnowledgeTreeError("HOOK_EVENT_INVALID")
    name = _event_name(event)
    prompt = _prompt_text(event)
    if not name:
        name = "user_prompt_submit" if prompt else "session_start"
    root = Path(tree_root or TREE_ROOT)
    if name in {"session_start", "sessionstart"}:
        prior = read_head_snapshot(tree_root=root)
        prior_query = str(prior.get("query") or "").strip()
        query = (
            prior_query
            if prior_query and prior_query not in SKIP_QUERIES
            else WORKPLACE_QUERY
        )
        payload = lookup(query, project_root=project_root)
        write_head_snapshot(payload, tree_root=root)
        return payload
    if name in {"user_prompt_submit", "userpromptsubmit"}:
        query = prompt or "user-prompt"
        payload = lookup(query, project_root=project_root)
        thought = record_thought(
            query,
            laser_handle=(payload.get("laser") or {}).get("handle_id"),
            project_root=project_root,
            tree_root=root,
        )
        if thought.get("status") == "RECORDED":
            payload = dict(payload)
            payload["thought_fact_id"] = thought.get("fact_id")
            payload["kind"] = "thought"
            payload["path"] = "prompt"
            _capture_long_memory(
                query,
                motor="GROK_TUI",
                kind="episodic",
                note=query,
                tree_root=root,
            )
        write_head_snapshot(payload, tree_root=root)
        return payload
    if name in {"post_tool_use", "posttooluse"}:
        tool = str(event.get("toolName") or "")
        if tool not in WRITE_TOOLS:
            return {
                "schema": SCHEMA,
                "status": "SKIPPED",
                "reason": "NOT_A_WRITE_TOOL",
                "action_authority": ACTION_AUTHORITY,
            }
        head = load_head(project_root=project_root)
        rel = _tool_path(event, head["repo_root"])
        if not rel:
            return {
                "schema": SCHEMA,
                "status": "SKIPPED",
                "reason": "PATH_UNBOUND",
                "action_authority": ACTION_AUTHORITY,
            }
        query = _prompt_text(event) or ("tool:" + tool)
        payload = record(
            query,
            relative_path=rel,
            kind="code",
            project_root=project_root,
            tree_root=root,
        )
        if payload.get("status") == "RECORDED":
            _capture_long_memory(
                query,
                motor="GROK_TUI",
                kind="procedural",
                note="wrote " + rel,
                tree_root=root,
            )
        write_head_snapshot(payload, tree_root=root)
        return payload
    return {
        "schema": SCHEMA,
        "status": "SKIPPED",
        "reason": "EVENT_UNHANDLED:" + name,
        "action_authority": ACTION_AUTHORITY,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Grok TUI laser-Merkle knowledge tree. "
            "Lookup nearby hashes; do not dump file bodies."
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)
    look = sub.add_parser("lookup")
    look.add_argument("--query", required=True)
    look.add_argument("--object-id", default="ws.tui.grok")
    rec = sub.add_parser("record")
    rec.add_argument("--query", required=True)
    rec.add_argument("--path", required=True)
    rec.add_argument("--kind", required=True)
    call = sub.add_parser("call")
    call.add_argument("--sha", action="append", required=True)
    sub.add_parser("observe")
    args = parser.parse_args(argv)
    try:
        if args.command == "lookup":
            payload = lookup(args.query, object_id=args.object_id)
        elif args.command == "observe":
            raw = sys.stdin.read()
            event = json.loads(raw) if raw.strip() else {}
            if not isinstance(event, dict):
                raise GrokKnowledgeTreeError("HOOK_EVENT_INVALID")
            payload = observe_event(event)
            print(json.dumps(payload, ensure_ascii=False), flush=True)
            return 0
        elif args.command == "call":
            payload = call_hashes(args.sha)
        else:
            payload = record(
                args.query,
                relative_path=args.path,
                kind=args.kind,
            )
    except Exception as exc:
        if args.command == "observe":
            sys.stderr.write(type(exc).__name__ + ":" + str(exc) + "\n")
            return 0
        print(json.dumps({"ok": False, "reason": str(exc)}, indent=2))
        return 2
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload.get("status") in {"READY", "RECORDED"} else 2


if __name__ == "__main__":
    if str(DESKTOP_PROJECT) not in sys.path:
        sys.path.insert(0, str(DESKTOP_PROJECT))
    if str(DESKTOP_PROJECT / "backend") not in sys.path:
        sys.path.insert(0, str(DESKTOP_PROJECT / "backend"))
    raise SystemExit(main())
