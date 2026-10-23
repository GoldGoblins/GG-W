"""Passive content-addressed capability registry for GG.

The registry describes and indexes already-existing capabilities. Loading,
searching, or constructing an active working set never imports or executes
registered capability source.

Capability existence is not execution authority.
"""

from __future__ import annotations

from backend.application_paths import resource_path, WORKSPACE_ROOT
from backend.platform_files import is_link

import argparse
import ast
import hashlib
import json
import os
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SEED_SCHEMA = "gg.capability-seeds.v1"
CONTRACT_SCHEMA = "gg.capability-contract.v1"
DEPENDENCY_ROOT_SCHEMA = "gg.capability-dependency-root.v1"
EXECUTION_REVISION_SCHEMA = "gg.capability-execution-revision.v1"
METADATA_SCHEMA = "gg.capability-metadata.v1"
QUERY_SCHEMA = "gg.capability-query.v1"

_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:\.[a-z0-9_]+)+$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_TOKEN_RE = re.compile(r"[a-z0-9]+")

_KINDS = {
    "STATE_SERVICE",
    "ANALYZER",
    "VERIFIER",
    "MODEL",
    "REPAIR",
    "ACTION",
    "CONTROL",
    "COMPOSITE",
}

_ENTRYPOINT_KINDS = {
    "executable",
    "python_module",
    "python_symbol",
}

_EFFECT_CLASSES = {
    "IN_MEMORY_ONLY",
    "READ_ONLY_SCAN",
    "TRANSIENT_EVIDENCE_WRITE",
    "LOCAL_MODEL_INFERENCE",
    "READ_ONLY_TOOL_EXECUTION",
    "BOUNDED_PERSISTENT_WRITE",
    "RUNTIME_STATE_WRITE",
    "TASK_BOUND_CONTROLLED_RUNTIME",
}

_RISK_FLOORS = {
    "GREEN",
    "YELLOW",
    "RED",
}

_PERSISTENT_WRITE = {
    "NONE",
    "RUNTIME_ONLY",
    "LOCAL_STATE",
    "BOUNDED_SOURCE",
}

_EXECUTION_AUTHORITY = {
    "NONE",
    "CONTROLLED_PROFILE",
}

_RELATION_TYPES = {
    "RELATED_TO",
    "VALIDATES",
    "PRODUCES_FOR",
    "OBSERVES",
    "REPAIRS",
    "USED_WITH",
    "COMPOSES",
}


class CapabilityRegistryError(ValueError):
    """Fail-closed registry/schema/identity error."""


@dataclass(frozen=True)
class CapabilityRecord:
    human_id: str
    description: str
    kind: str
    source_path: str
    manifest_key: str | None
    content_sha256: str
    entrypoint_kind: str
    entrypoint: str
    contract_sha256: str
    dependency_root_sha256: str
    execution_revision_sha256: str
    metadata_sha256: str
    depends_on: tuple[str, ...]
    tags: tuple[str, ...]
    relations: tuple[tuple[str, str], ...]
    contract: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "human_id": self.human_id,
            "description": self.description,
            "kind": self.kind,
            "source_path": self.source_path,
            "manifest_key": self.manifest_key,
            "content_sha256": self.content_sha256,
            "entrypoint_kind": self.entrypoint_kind,
            "entrypoint": self.entrypoint,
            "contract_sha256": self.contract_sha256,
            "dependency_root_sha256": self.dependency_root_sha256,
            "execution_revision_sha256": self.execution_revision_sha256,
            "metadata_sha256": self.metadata_sha256,
            "depends_on": list(self.depends_on),
            "tags": list(self.tags),
            "relations": [
                {
                    "type": relation_type,
                    "target": target,
                }
                for relation_type, target in self.relations
            ],
            "contract": dict(self.contract),
        }


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def digest_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(
        _TOKEN_RE.findall(value.lower())
    )


def _safe_repo_file(
    repo_root: Path,
    relative: str,
) -> Path:
    if (
        not relative
        or relative.startswith("/")
        or "\x00" in relative
    ):
        raise CapabilityRegistryError(
            "source path invalid"
        )

    from pathlib import PureWindowsPath
    relative_path = Path(relative)
    if relative_path.is_absolute() or PureWindowsPath(relative).drive or ".." in relative_path.parts:
        raise CapabilityRegistryError("source path invalid")
    candidate = repo_root / relative
    if not candidate.exists() and repo_root.resolve() == WORKSPACE_ROOT.resolve():
        candidate = resource_path(relative, workspace=repo_root)
    if is_link(candidate):
        raise CapabilityRegistryError("source path is not a regular file")
    candidate = candidate.resolve(strict=True)

    try:
        candidate.relative_to(repo_root)
    except ValueError as exc:
        raise CapabilityRegistryError(
            "source path escaped repository"
        ) from exc

    if (
        not candidate.is_file()
        or candidate.is_symlink()
    ):
        raise CapabilityRegistryError(
            "source path is not a regular file"
        )

    return candidate


def _resolve_python_symbol(
    tree: ast.Module,
    symbol: str,
) -> bool:
    parts = symbol.split(".")

    if not parts:
        return False

    current: ast.AST | None = None

    for node in tree.body:
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.ClassDef,
            ),
        ) and node.name == parts[0]:
            current = node
            break

    if current is None:
        return False

    for name in parts[1:]:
        if not isinstance(current, ast.ClassDef):
            return False

        child_match: ast.AST | None = None

        for child in current.body:
            if isinstance(
                child,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                    ast.ClassDef,
                ),
            ) and child.name == name:
                child_match = child
                break

        if child_match is None:
            return False

        current = child_match

    return True


def _verify_entrypoint(
    path: Path,
    entrypoint_kind: str,
    entrypoint: str,
) -> None:
    if entrypoint_kind == "executable":
        # This is passive source indexing, not permission to launch a host
        # process. Windows does not retain the source tree's POSIX +x bits.
        if os.name == "nt":
            with path.open("rb") as source:
                prefix = source.read(2)
            if prefix not in (b"#!", b"MZ") and path.suffix.lower() not in (".cmd", ".bat"):
                raise CapabilityRegistryError("executable entrypoint format invalid")
        elif not path.stat().st_mode & 0o111:
            raise CapabilityRegistryError(
                "executable entrypoint lacks execute mode"
            )
        return

    if path.suffix != ".py":
        raise CapabilityRegistryError(
            "python entrypoint source is not .py"
        )

    try:
        tree = ast.parse(
            path.read_text(encoding="utf-8"),
            filename=str(path),
        )
    except (
        SyntaxError,
        UnicodeDecodeError,
    ) as exc:
        raise CapabilityRegistryError(
            "python entrypoint source invalid"
        ) from exc

    if entrypoint_kind == "python_module":
        return

    if not _resolve_python_symbol(
        tree,
        entrypoint,
    ):
        raise CapabilityRegistryError(
            "python symbol entrypoint missing:"
            + entrypoint
        )


def _validate_contract(
    value: Any,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CapabilityRegistryError(
            "contract must be an object"
        )

    expected = {
        "effect_class",
        "risk_floor",
        "persistent_write",
        "network",
        "sudo",
        "execution_authority",
        "model_inference",
    }

    if set(value) != expected:
        raise CapabilityRegistryError(
            "contract fields invalid"
        )

    if value["effect_class"] not in _EFFECT_CLASSES:
        raise CapabilityRegistryError(
            "effect class invalid"
        )

    if value["risk_floor"] not in _RISK_FLOORS:
        raise CapabilityRegistryError(
            "risk floor invalid"
        )

    if value["persistent_write"] not in _PERSISTENT_WRITE:
        raise CapabilityRegistryError(
            "persistent write class invalid"
        )

    if value["network"] != "NONE":
        raise CapabilityRegistryError(
            "v1 network authority must be NONE"
        )

    if value["sudo"] != "NO":
        raise CapabilityRegistryError(
            "v1 sudo authority must be NO"
        )

    if value["execution_authority"] not in _EXECUTION_AUTHORITY:
        raise CapabilityRegistryError(
            "execution authority invalid"
        )

    if not isinstance(
        value["model_inference"],
        bool,
    ):
        raise CapabilityRegistryError(
            "model_inference must be bool"
        )

    return dict(value)


def _validate_string_list(
    value: Any,
    field: str,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise CapabilityRegistryError(
            field + " must be a list"
        )

    if not all(
        isinstance(item, str)
        and item
        for item in value
    ):
        raise CapabilityRegistryError(
            field + " contains invalid string"
        )

    if len(set(value)) != len(value):
        raise CapabilityRegistryError(
            field + " contains duplicates"
        )

    return tuple(value)


class CapabilityRegistry:
    """Static registry and bounded lexical/graph working-set index."""

    def __init__(
        self,
        records: dict[str, CapabilityRecord],
    ) -> None:
        self._records = dict(records)

        token_index: dict[str, set[str]] = defaultdict(set)
        adjacency: dict[str, set[str]] = defaultdict(set)

        for record in self._records.values():
            weighted_text = " ".join(
                (
                    record.human_id,
                    record.description,
                    record.kind,
                    *record.tags,
                )
            )

            for token in set(
                _tokens(weighted_text)
            ):
                token_index[token].add(
                    record.human_id
                )

            for dependency in record.depends_on:
                adjacency[record.human_id].add(
                    dependency
                )
                adjacency[dependency].add(
                    record.human_id
                )

            for _, target in record.relations:
                adjacency[record.human_id].add(
                    target
                )
                adjacency[target].add(
                    record.human_id
                )

        self._token_index = {
            token: frozenset(values)
            for token, values in token_index.items()
        }

        self._adjacency = {
            human_id: frozenset(values)
            for human_id, values in adjacency.items()
        }

    @classmethod
    def load(
        cls,
        *,
        repo_root: Path,
        project_root: Path,
        seed_path: Path,
        manifest_path: Path,
    ) -> "CapabilityRegistry":
        seed_data = json.loads(
            seed_path.read_text(
                encoding="utf-8"
            )
        )

        manifest = json.loads(
            manifest_path.read_text(
                encoding="utf-8"
            )
        )

        return cls.from_data(
            repo_root=repo_root,
            project_root=project_root,
            seed_data=seed_data,
            manifest=manifest,
        )

    @classmethod
    def from_data(
        cls,
        *,
        repo_root: Path,
        project_root: Path,
        seed_data: dict[str, Any],
        manifest: dict[str, Any],
    ) -> "CapabilityRegistry":
        repo_root = repo_root.resolve(strict=True)
        project_root = project_root.resolve(strict=True)

        try:
            project_root.relative_to(repo_root)
        except ValueError as exc:
            raise CapabilityRegistryError(
                "project root escaped repository"
            ) from exc

        if set(seed_data) != {
            "schema",
            "capabilities",
        }:
            raise CapabilityRegistryError(
                "seed top-level fields invalid"
            )

        if seed_data["schema"] != SEED_SCHEMA:
            raise CapabilityRegistryError(
                "seed schema invalid"
            )

        raw_capabilities = seed_data["capabilities"]

        if not isinstance(
            raw_capabilities,
            list,
        ):
            raise CapabilityRegistryError(
                "capabilities must be a list"
            )

        manifest_files = manifest.get(
            "files",
            {},
        )

        if not isinstance(
            manifest_files,
            dict,
        ):
            raise CapabilityRegistryError(
                "manifest files invalid"
            )

        normalized: dict[str, dict[str, Any]] = {}

        expected_fields = {
            "human_id",
            "description",
            "kind",
            "source_path",
            "manifest_key",
            "content_sha256",
            "entrypoint_kind",
            "entrypoint",
            "contract",
            "depends_on",
            "tags",
            "relations",
        }

        for raw in raw_capabilities:
            if (
                not isinstance(raw, dict)
                or set(raw) != expected_fields
            ):
                raise CapabilityRegistryError(
                    "capability fields invalid"
                )

            human_id = raw["human_id"]

            if (
                not isinstance(human_id, str)
                or not _ID_RE.fullmatch(human_id)
            ):
                raise CapabilityRegistryError(
                    "human_id invalid"
                )

            if human_id in normalized:
                raise CapabilityRegistryError(
                    "duplicate human_id:"
                    + human_id
                )

            description = raw["description"]

            if (
                not isinstance(description, str)
                or not description.strip()
                or len(description) > 700
            ):
                raise CapabilityRegistryError(
                    "description invalid:"
                    + human_id
                )

            kind = raw["kind"]

            if kind not in _KINDS:
                raise CapabilityRegistryError(
                    "kind invalid:"
                    + human_id
                )

            source_path = raw["source_path"]

            if not isinstance(
                source_path,
                str,
            ):
                raise CapabilityRegistryError(
                    "source_path invalid:"
                    + human_id
                )

            content_sha256 = raw["content_sha256"]

            if (
                not isinstance(content_sha256, str)
                or not _SHA_RE.fullmatch(
                    content_sha256
                )
            ):
                raise CapabilityRegistryError(
                    "content sha invalid:"
                    + human_id
                )

            manifest_key = raw["manifest_key"]

            if (
                manifest_key is not None
                and not isinstance(
                    manifest_key,
                    str,
                )
            ):
                raise CapabilityRegistryError(
                    "manifest key invalid:"
                    + human_id
                )

            entrypoint_kind = raw[
                "entrypoint_kind"
            ]

            if entrypoint_kind not in _ENTRYPOINT_KINDS:
                raise CapabilityRegistryError(
                    "entrypoint kind invalid:"
                    + human_id
                )

            entrypoint = raw["entrypoint"]

            if (
                not isinstance(entrypoint, str)
                or not entrypoint
            ):
                raise CapabilityRegistryError(
                    "entrypoint invalid:"
                    + human_id
                )

            depends_on = _validate_string_list(
                raw["depends_on"],
                "depends_on",
            )

            tags = _validate_string_list(
                raw["tags"],
                "tags",
            )

            relations_raw = raw["relations"]

            if not isinstance(
                relations_raw,
                list,
            ):
                raise CapabilityRegistryError(
                    "relations must be a list"
                )

            relations: list[tuple[str, str]] = []

            for relation in relations_raw:
                if (
                    not isinstance(relation, dict)
                    or set(relation)
                    != {
                        "type",
                        "target",
                    }
                ):
                    raise CapabilityRegistryError(
                        "relation invalid"
                    )

                relation_type = relation["type"]
                target = relation["target"]

                if relation_type not in _RELATION_TYPES:
                    raise CapabilityRegistryError(
                        "relation type invalid"
                    )

                if not isinstance(
                    target,
                    str,
                ):
                    raise CapabilityRegistryError(
                        "relation target invalid"
                    )

                relations.append(
                    (
                        relation_type,
                        target,
                    )
                )

            if len(set(relations)) != len(relations):
                raise CapabilityRegistryError(
                    "duplicate relation:"
                    + human_id
                )

            contract = _validate_contract(
                raw["contract"]
            )

            path = _safe_repo_file(
                repo_root,
                source_path,
            )

            actual_sha = _file_sha256(path)

            if actual_sha != content_sha256:
                raise CapabilityRegistryError(
                    "source identity drift:"
                    + human_id
                )

            if manifest_key is not None:
                if (
                    manifest_files.get(
                        manifest_key
                    )
                    != content_sha256
                ):
                    raise CapabilityRegistryError(
                        "manifest binding drift:"
                        + human_id
                    )

            _verify_entrypoint(
                path,
                entrypoint_kind,
                entrypoint,
            )

            normalized[human_id] = {
                "human_id":
                    human_id,
                "description":
                    description.strip(),
                "kind":
                    kind,
                "source_path":
                    source_path,
                "manifest_key":
                    manifest_key,
                "content_sha256":
                    content_sha256,
                "entrypoint_kind":
                    entrypoint_kind,
                "entrypoint":
                    entrypoint,
                "contract":
                    contract,
                "depends_on":
                    depends_on,
                "tags":
                    tags,
                "relations":
                    tuple(relations),
            }

        all_ids = set(normalized)

        for human_id, item in normalized.items():
            for dependency in item["depends_on"]:
                if dependency not in all_ids:
                    raise CapabilityRegistryError(
                        "dependency missing:"
                        + human_id
                        + "->"
                        + dependency
                    )

            for _, target in item["relations"]:
                if target not in all_ids:
                    raise CapabilityRegistryError(
                        "relation target missing:"
                        + human_id
                        + "->"
                        + target
                    )

        records: dict[str, CapabilityRecord] = {}
        visiting: set[str] = set()

        def build(
            human_id: str,
        ) -> CapabilityRecord:
            if human_id in records:
                return records[human_id]

            if human_id in visiting:
                raise CapabilityRegistryError(
                    "hard dependency cycle:"
                    + human_id
                )

            visiting.add(human_id)

            item = normalized[human_id]

            dependencies = [
                build(dependency)
                for dependency
                in item["depends_on"]
            ]

            dependency_root_sha256 = digest_json(
                {
                    "schema":
                        DEPENDENCY_ROOT_SCHEMA,
                    "execution_revisions":
                        sorted(
                            dependency
                            .execution_revision_sha256
                            for dependency
                            in dependencies
                        ),
                }
            )

            contract_sha256 = digest_json(
                {
                    "schema":
                        CONTRACT_SCHEMA,
                    **item["contract"],
                }
            )

            execution_revision_sha256 = digest_json(
                {
                    "schema":
                        EXECUTION_REVISION_SCHEMA,
                    "source_path":
                        item["source_path"],
                    "content_sha256":
                        item["content_sha256"],
                    "entrypoint_kind":
                        item["entrypoint_kind"],
                    "entrypoint":
                        item["entrypoint"],
                    "contract_sha256":
                        contract_sha256,
                    "dependency_root_sha256":
                        dependency_root_sha256,
                }
            )

            metadata_sha256 = digest_json(
                {
                    "schema":
                        METADATA_SCHEMA,
                    "human_id":
                        item["human_id"],
                    "description":
                        item["description"],
                    "kind":
                        item["kind"],
                    "depends_on":
                        sorted(
                            item["depends_on"]
                        ),
                    "tags":
                        sorted(
                            item["tags"]
                        ),
                    "relations": [
                        {
                            "type":
                                relation_type,
                            "target":
                                target,
                        }
                        for (
                            relation_type,
                            target,
                        )
                        in sorted(
                            item["relations"]
                        )
                    ],
                }
            )

            record = CapabilityRecord(
                human_id=item["human_id"],
                description=item["description"],
                kind=item["kind"],
                source_path=item["source_path"],
                manifest_key=item["manifest_key"],
                content_sha256=item["content_sha256"],
                entrypoint_kind=item["entrypoint_kind"],
                entrypoint=item["entrypoint"],
                contract_sha256=contract_sha256,
                dependency_root_sha256=dependency_root_sha256,
                execution_revision_sha256=execution_revision_sha256,
                metadata_sha256=metadata_sha256,
                depends_on=item["depends_on"],
                tags=item["tags"],
                relations=item["relations"],
                contract=dict(
                    item["contract"]
                ),
            )

            visiting.remove(human_id)
            records[human_id] = record

            return record

        for human_id in sorted(normalized):
            build(human_id)

        return cls(records)

    def get(
        self,
        human_id: str,
    ) -> CapabilityRecord:
        try:
            return self._records[human_id]
        except KeyError as exc:
            raise CapabilityRegistryError(
                "unknown capability:"
                + human_id
            ) from exc

    def records(
        self,
    ) -> tuple[CapabilityRecord, ...]:
        return tuple(
            self._records[human_id]
            for human_id
            in sorted(self._records)
        )

    def search(
        self,
        query: str,
        *,
        limit: int = 8,
    ) -> tuple[CapabilityRecord, ...]:
        if not isinstance(query, str):
            raise CapabilityRegistryError(
                "query must be text"
            )

        if (
            not isinstance(limit, int)
            or limit < 1
            or limit > 64
        ):
            raise CapabilityRegistryError(
                "search limit invalid"
            )

        query_tokens = set(
            _tokens(query)
        )

        if not query_tokens:
            return ()

        candidate_ids: set[str] = set()

        for token in query_tokens:
            candidate_ids.update(
                self._token_index.get(
                    token,
                    (),
                )
            )

        scored: list[tuple[int, str]] = []

        for human_id in candidate_ids:
            record = self._records[
                human_id
            ]

            id_tokens = set(
                _tokens(record.human_id)
            )

            description_tokens = set(
                _tokens(record.description)
            )

            tag_tokens = set()

            for tag in record.tags:
                tag_tokens.update(
                    _tokens(tag)
                )

            kind_tokens = set(
                _tokens(record.kind)
            )

            score = 0

            for token in query_tokens:
                if token in id_tokens:
                    score += 12

                if token in tag_tokens:
                    score += 8

                if token in kind_tokens:
                    score += 4

                if token in description_tokens:
                    score += 2

            scored.append(
                (
                    -score,
                    human_id,
                )
            )

        scored.sort()

        return tuple(
            self._records[human_id]
            for _, human_id
            in scored[:limit]
        )

    def active_working_set(
        self,
        query: str,
        *,
        limit: int = 12,
        depth: int = 2,
    ) -> tuple[CapabilityRecord, ...]:
        if (
            not isinstance(limit, int)
            or limit < 1
            or limit > 64
        ):
            raise CapabilityRegistryError(
                "working-set limit invalid"
            )

        if (
            not isinstance(depth, int)
            or depth < 0
            or depth > 4
        ):
            raise CapabilityRegistryError(
                "working-set depth invalid"
            )

        roots = self.search(
            query,
            limit=min(
                4,
                limit,
            ),
        )

        if not roots:
            return ()

        queue: deque[tuple[str, int]] = deque(
            (
                record.human_id,
                0,
            )
            for record in roots
        )

        seen: set[str] = set()
        ordered: list[str] = []

        while queue and len(ordered) < limit:
            human_id, current_depth = (
                queue.popleft()
            )

            if human_id in seen:
                continue

            seen.add(human_id)
            ordered.append(human_id)

            if current_depth >= depth:
                continue

            for neighbor in sorted(
                self._adjacency.get(
                    human_id,
                    (),
                )
            ):
                if neighbor not in seen:
                    queue.append(
                        (
                            neighbor,
                            current_depth + 1,
                        )
                    )

        return tuple(
            self._records[human_id]
            for human_id in ordered
        )

    def summary(
        self,
    ) -> dict[str, Any]:
        kinds: dict[str, int] = defaultdict(int)
        dependency_edges = 0
        semantic_edges = 0

        for record in self._records.values():
            kinds[record.kind] += 1
            dependency_edges += len(
                record.depends_on
            )
            semantic_edges += len(
                record.relations
            )

        return {
            "schema":
                "gg.capability-registry-summary.v1",
            "capability_count":
                len(self._records),
            "kind_counts":
                dict(
                    sorted(kinds.items())
                ),
            "dependency_edge_count":
                dependency_edges,
            "semantic_edge_count":
                semantic_edges,
        }


def _default_paths(
    repo_root: Path,
) -> tuple[Path, Path, Path]:
    project_root = (
        repo_root
        / "projects"
        / "gg-ai-desktop"
    )

    return (
        project_root,
        project_root
        / "config"
        / "capability-seeds-v1.json",
        project_root
        / "SOURCE-MANIFEST.json",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Passive GG capability registry query. "
            "Does not execute registered capabilities."
        )
    )

    parser.add_argument(
        "--repo-root",
        required=True,
    )

    parser.add_argument(
        "--query",
        default="",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=12,
    )

    args = parser.parse_args()

    repo_root = Path(
        args.repo_root
    ).resolve(strict=True)

    (
        project_root,
        seed_path,
        manifest_path,
    ) = _default_paths(repo_root)

    load_started = time.perf_counter()

    registry = CapabilityRegistry.load(
        repo_root=repo_root,
        project_root=project_root,
        seed_path=seed_path,
        manifest_path=manifest_path,
    )

    load_ms = (
        time.perf_counter()
        - load_started
    ) * 1000.0

    query_started = time.perf_counter()

    search_results = registry.search(
        args.query,
        limit=args.limit,
    ) if args.query else ()

    working_set = registry.active_working_set(
        args.query,
        limit=args.limit,
    ) if args.query else ()

    query_ms = (
        time.perf_counter()
        - query_started
    ) * 1000.0

    payload = {
        "schema":
            QUERY_SCHEMA,
        "summary":
            registry.summary(),
        "query":
            args.query,
        "search_results": [
            record.human_id
            for record in search_results
        ],
        "active_working_set": [
            record.human_id
            for record in working_set
        ],
        "load_ms":
            round(load_ms, 3),
        "query_ms":
            round(query_ms, 3),
        "capability_execution":
            False,
        "model_inference":
            False,
    }

    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
