"""Bounded cold-path neighborhood compiler for GG.

The compiler reuses the existing CapabilityRegistry semantic working-set
discovery, a preloaded content-addressed source identity map, already-derived
Merkle roots and the generic compiled-focus primitives.

Discovery, sorting and Merkle composition happen here on the cold path.
The resulting CompiledFocusHandle is suitable for direct resident lookup on
the hot path.

This module performs no filesystem scan, filesystem I/O, model inference,
registered-capability execution, persistent write or authority decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from compiled_focus import (
    CompiledFocusHandle,
    FocusBinding,
    FocusDependency,
    canonical_json as focus_canonical_json,
    compile_focus,
)
from domain_merkle import (
    DomainMerkleRoot,
    build_domain_root,
    digest_json,
    leaf,
)


NEIGHBORHOOD_REQUEST_SCHEMA = (
    "gg.neighborhood-request.v1"
)
NEIGHBORHOOD_CAPABILITY_ITEM_SCHEMA = (
    "gg.neighborhood-capability-item.v1"
)
NEIGHBORHOOD_SOURCE_ITEM_SCHEMA = (
    "gg.neighborhood-source-item.v1"
)
NEIGHBORHOOD_PAYLOAD_SCHEMA = (
    "gg.neighborhood-payload.v1"
)
NEIGHBORHOOD_COMPILATION_SCHEMA = (
    "gg.neighborhood-compilation.v2"
)

MAX_RELEVANT_ROOTS = 16
MAX_SEMANTIC_ITEMS = 63
MAX_SOURCE_ITEMS = 64

_INTERNAL_NAMESPACES = frozenset(
    (
        "task",
        "source",
        "capability.neighborhood",
        "compiler.neighborhood",
    )
)


class NeighborhoodCompilerError(
    RuntimeError
):
    """Neighborhood compiler contract violation."""


class CapabilityDiscovery(
    Protocol
):
    def active_working_set(
        self,
        query: str,
        *,
        limit: int,
        depth: int,
    ) -> tuple[Any, ...]:
        ...


def _valid_sha256(
    value: object,
) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(
            character
            in "0123456789abcdef"
            for character in value
        )
    )


def _require_sha256(
    value: object,
    label: str,
) -> str:
    if not _valid_sha256(value):
        raise NeighborhoodCompilerError(
            label
            + "_SHA256_INVALID"
        )

    return value


def _require_text(
    value: object,
    label: str,
    *,
    maximum: int,
) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
    ):
        raise NeighborhoodCompilerError(
            label
            + "_TEXT_INVALID"
        )

    return value


def _normalized_query(
    query: str,
) -> str:
    _require_text(
        query,
        "QUERY",
        maximum=4096,
    )

    return " ".join(
        query.split()
    )


@dataclass(frozen=True)
class NeighborhoodRequest:
    query: str
    task_identity_sha256: str
    focus_domain: str
    focus_id: str
    source_identity_map: dict[str, str]
    relevant_roots: tuple[
        FocusDependency,
        ...
    ]
    policy_revision_sha256: str
    focus_compiler_revision_sha256: str
    neighborhood_compiler_revision_sha256: str
    semantic_depth: int = 2
    max_semantic_items: int = 12
    max_source_items: int = 12

    def validate(
        self,
    ) -> None:
        _normalized_query(
            self.query
        )

        _require_sha256(
            self.task_identity_sha256,
            "TASK_IDENTITY",
        )

        _require_text(
            self.focus_domain,
            "FOCUS_DOMAIN",
            maximum=128,
        )

        _require_text(
            self.focus_id,
            "FOCUS_ID",
            maximum=512,
        )

        if not isinstance(
            self.source_identity_map,
            dict,
        ):
            raise NeighborhoodCompilerError(
                "SOURCE_IDENTITY_MAP_INVALID"
            )

        if (
            not isinstance(
                self.semantic_depth,
                int,
            )
            or self.semantic_depth < 0
            or self.semantic_depth > 4
        ):
            raise NeighborhoodCompilerError(
                "SEMANTIC_DEPTH_INVALID"
            )

        if (
            not isinstance(
                self.max_semantic_items,
                int,
            )
            or self.max_semantic_items < 1
            or self.max_semantic_items
            > MAX_SEMANTIC_ITEMS
        ):
            raise NeighborhoodCompilerError(
                "SEMANTIC_LIMIT_INVALID"
            )

        if (
            not isinstance(
                self.max_source_items,
                int,
            )
            or self.max_source_items < 1
            or self.max_source_items
            > MAX_SOURCE_ITEMS
        ):
            raise NeighborhoodCompilerError(
                "SOURCE_LIMIT_INVALID"
            )

        if (
            not isinstance(
                self.relevant_roots,
                tuple,
            )
            or len(
                self.relevant_roots
            ) > MAX_RELEVANT_ROOTS
        ):
            raise NeighborhoodCompilerError(
                "RELEVANT_ROOTS_INVALID"
            )

        seen: set[str] = set()

        for dependency in self.relevant_roots:
            if not isinstance(
                dependency,
                FocusDependency,
            ):
                raise NeighborhoodCompilerError(
                    "RELEVANT_ROOT_TYPE_INVALID"
                )

            dependency.validate()

            if (
                dependency.namespace
                in _INTERNAL_NAMESPACES
            ):
                raise NeighborhoodCompilerError(
                    "RELEVANT_ROOT_NAMESPACE_RESERVED"
                )

            if dependency.namespace in seen:
                raise NeighborhoodCompilerError(
                    "RELEVANT_ROOT_NAMESPACE_DUPLICATE"
                )

            seen.add(
                dependency.namespace
            )

        _require_sha256(
            self.policy_revision_sha256,
            "POLICY_REVISION",
        )

        _require_sha256(
            self.focus_compiler_revision_sha256,
            "FOCUS_COMPILER_REVISION",
        )

        _require_sha256(
            self.neighborhood_compiler_revision_sha256,
            "NEIGHBORHOOD_COMPILER_REVISION",
        )


@dataclass(frozen=True)
class CapabilityNeighborhoodItem:
    human_id: str
    kind: str
    source_path: str
    execution_revision_sha256: str
    metadata_sha256: str

    def validate(
        self,
    ) -> None:
        _require_text(
            self.human_id,
            "CAPABILITY_ID",
            maximum=256,
        )

        _require_text(
            self.kind,
            "CAPABILITY_KIND",
            maximum=64,
        )

        _require_text(
            self.source_path,
            "CAPABILITY_SOURCE_PATH",
            maximum=1024,
        )

        _require_sha256(
            self.execution_revision_sha256,
            "CAPABILITY_EXECUTION_REVISION",
        )

        _require_sha256(
            self.metadata_sha256,
            "CAPABILITY_METADATA",
        )

    def as_dict(
        self,
    ) -> dict[str, str]:
        self.validate()

        return {
            "schema":
                NEIGHBORHOOD_CAPABILITY_ITEM_SCHEMA,
            "human_id":
                self.human_id,
            "kind":
                self.kind,
            "source_path":
                self.source_path,
            "execution_revision_sha256":
                self.execution_revision_sha256,
            "metadata_sha256":
                self.metadata_sha256,
        }

    def identity_sha256(
        self,
    ) -> str:
        return digest_json(
            self.as_dict()
        )


@dataclass(frozen=True)
class SourceNeighborhoodItem:
    source_path: str
    content_sha256: str

    def validate(
        self,
    ) -> None:
        _require_text(
            self.source_path,
            "SOURCE_PATH",
            maximum=1024,
        )

        _require_sha256(
            self.content_sha256,
            "SOURCE_CONTENT",
        )

    def as_dict(
        self,
    ) -> dict[str, str]:
        self.validate()

        return {
            "schema":
                NEIGHBORHOOD_SOURCE_ITEM_SCHEMA,
            "source_path":
                self.source_path,
            "content_sha256":
                self.content_sha256,
        }


@dataclass(frozen=True)
class NeighborhoodCompilation:
    schema: str
    task_root_sha256: str
    source_root_sha256: str
    capability_root_sha256: str
    query_sha256: str
    semantic_items: tuple[
        CapabilityNeighborhoodItem,
        ...
    ]
    source_items: tuple[
        SourceNeighborhoodItem,
        ...
    ]
    binding: FocusBinding
    handle: CompiledFocusHandle
    action_authority: str = "NONE"
    promotion_authority: str = "NONE"
    persistent_write: str = "NONE"
    model_inference: bool = False
    registered_capability_execution: bool = False

    def validate(
        self,
    ) -> None:
        if (
            self.schema
            != NEIGHBORHOOD_COMPILATION_SCHEMA
        ):
            raise NeighborhoodCompilerError(
                "COMPILATION_SCHEMA_INVALID"
            )

        for value, label in (
            (
                self.task_root_sha256,
                "TASK_ROOT",
            ),
            (
                self.source_root_sha256,
                "SOURCE_ROOT",
            ),
            (
                self.capability_root_sha256,
                "CAPABILITY_ROOT",
            ),
            (
                self.query_sha256,
                "QUERY",
            ),
        ):
            _require_sha256(
                value,
                label,
            )

        if not self.semantic_items:
            raise NeighborhoodCompilerError(
                "SEMANTIC_NEIGHBORHOOD_EMPTY"
            )

        for item in self.semantic_items:
            item.validate()

        for item in self.source_items:
            item.validate()

        if not isinstance(
            self.binding,
            FocusBinding,
        ):
            raise NeighborhoodCompilerError(
                "FOCUS_BINDING_TYPE_INVALID"
            )

        self.binding.validate()
        self.handle.validate()

        if (
            self.binding.binding_sha256()
            != self.handle.binding_sha256
        ):
            raise NeighborhoodCompilerError(
                "FOCUS_BINDING_HANDLE_MISMATCH"
            )

        if (
            self.binding.dependency_root_sha256()
            != self.handle.dependency_root_sha256
        ):
            raise NeighborhoodCompilerError(
                "FOCUS_DEPENDENCY_ROOT_MISMATCH"
            )

        if self.action_authority != "NONE":
            raise NeighborhoodCompilerError(
                "ACTION_AUTHORITY_INVALID"
            )

        if self.promotion_authority != "NONE":
            raise NeighborhoodCompilerError(
                "PROMOTION_AUTHORITY_INVALID"
            )

        if self.persistent_write != "NONE":
            raise NeighborhoodCompilerError(
                "PERSISTENT_WRITE_INVALID"
            )

        if self.model_inference is not False:
            raise NeighborhoodCompilerError(
                "MODEL_INFERENCE_INVALID"
            )

        if (
            self.registered_capability_execution
            is not False
        ):
            raise NeighborhoodCompilerError(
                "REGISTERED_EXECUTION_INVALID"
            )

    def as_dict(
        self,
    ) -> dict[str, object]:
        self.validate()

        return {
            "schema":
                self.schema,
            "task_root_sha256":
                self.task_root_sha256,
            "source_root_sha256":
                self.source_root_sha256,
            "capability_root_sha256":
                self.capability_root_sha256,
            "query_sha256":
                self.query_sha256,
            "semantic_items": [
                item.as_dict()
                for item
                in self.semantic_items
            ],
            "source_items": [
                item.as_dict()
                for item
                in self.source_items
            ],
            "binding":
                self.binding.as_dict(),
            "handle":
                self.handle.as_dict(),
            "action_authority":
                self.action_authority,
            "promotion_authority":
                self.promotion_authority,
            "persistent_write":
                self.persistent_write,
            "model_inference":
                self.model_inference,
            "registered_capability_execution":
                self.registered_capability_execution,
        }

    def compilation_sha256(
        self,
    ) -> str:
        return digest_json(
            self.as_dict()
        )


def _capability_item(
    record: Any,
) -> CapabilityNeighborhoodItem:
    try:
        item = CapabilityNeighborhoodItem(
            human_id=record.human_id,
            kind=record.kind,
            source_path=record.source_path,
            execution_revision_sha256=(
                record.execution_revision_sha256
            ),
            metadata_sha256=(
                record.metadata_sha256
            ),
        )
    except AttributeError as exc:
        raise NeighborhoodCompilerError(
            "CAPABILITY_RECORD_SHAPE_INVALID"
        ) from exc

    item.validate()

    return item


def _capability_root(
    items: tuple[
        CapabilityNeighborhoodItem,
        ...
    ],
) -> DomainMerkleRoot:
    if not items:
        raise NeighborhoodCompilerError(
            "SEMANTIC_NEIGHBORHOOD_EMPTY"
        )

    return build_domain_root(
        "CAPABILITY_NEIGHBORHOOD",
        "compiled-working-set",
        tuple(
            leaf(
                item.human_id,
                item.identity_sha256(),
            )
            for item in items
        ),
    )


def _source_root(
    items: tuple[
        SourceNeighborhoodItem,
        ...
    ],
) -> DomainMerkleRoot:
    if not items:
        raise NeighborhoodCompilerError(
            "SOURCE_NEIGHBORHOOD_EMPTY"
        )

    return build_domain_root(
        "SOURCE_NEIGHBORHOOD",
        "compiled-working-set",
        tuple(
            leaf(
                item.source_path,
                item.content_sha256,
            )
            for item in items
        ),
    )


def _task_root(
    task_identity_sha256: str,
    query_sha256: str,
) -> DomainMerkleRoot:
    return build_domain_root(
        "TASK",
        "compiled-neighborhood",
        (
            leaf(
                "task-identity",
                task_identity_sha256,
            ),
            leaf(
                "query",
                query_sha256,
            ),
        ),
    )


def compile_neighborhood(
    request: NeighborhoodRequest,
    registry: CapabilityDiscovery,
) -> NeighborhoodCompilation:
    if not isinstance(
        request,
        NeighborhoodRequest,
    ):
        raise NeighborhoodCompilerError(
            "REQUEST_TYPE_INVALID"
        )

    request.validate()

    if not hasattr(
        registry,
        "active_working_set",
    ):
        raise NeighborhoodCompilerError(
            "DISCOVERY_PROVIDER_INVALID"
        )

    query = _normalized_query(
        request.query
    )

    raw = registry.active_working_set(
        query,
        limit=(
            request.max_semantic_items
            + 1
        ),
        depth=request.semantic_depth,
    )

    if not isinstance(
        raw,
        tuple,
    ):
        raw = tuple(raw)

    if len(raw) > request.max_semantic_items:
        raise NeighborhoodCompilerError(
            "SEMANTIC_NEIGHBORHOOD_OVERFLOW"
        )

    if not raw:
        raise NeighborhoodCompilerError(
            "SEMANTIC_NEIGHBORHOOD_EMPTY"
        )

    semantic_items = tuple(
        sorted(
            (
                _capability_item(
                    record
                )
                for record in raw
            ),
            key=lambda item: (
                item.human_id,
                item.execution_revision_sha256,
                item.metadata_sha256,
            ),
        )
    )

    semantic_ids = [
        item.human_id
        for item in semantic_items
    ]

    if (
        len(set(semantic_ids))
        != len(semantic_ids)
    ):
        raise NeighborhoodCompilerError(
            "SEMANTIC_CAPABILITY_DUPLICATE"
        )

    source_by_path: dict[
        str,
        SourceNeighborhoodItem,
    ] = {}

    for item in semantic_items:
        content_sha256 = (
            request.source_identity_map.get(
                item.source_path
            )
        )

        if content_sha256 is None:
            raise NeighborhoodCompilerError(
                "SOURCE_IDENTITY_MISSING:"
                + item.source_path
            )

        _require_sha256(
            content_sha256,
            "SOURCE_CONTENT",
        )

        source_by_path[
            item.source_path
        ] = SourceNeighborhoodItem(
            source_path=item.source_path,
            content_sha256=content_sha256,
        )

    if (
        len(source_by_path)
        > request.max_source_items
    ):
        raise NeighborhoodCompilerError(
            "SOURCE_NEIGHBORHOOD_OVERFLOW"
        )

    source_items = tuple(
        source_by_path[path]
        for path in sorted(
            source_by_path
        )
    )

    capability_root = (
        _capability_root(
            semantic_items
        )
    )

    source_root = _source_root(
        source_items
    )

    query_sha256 = digest_json(
        {
            "schema":
                NEIGHBORHOOD_REQUEST_SCHEMA,
            "query":
                query,
        }
    )

    task_root = _task_root(
        request.task_identity_sha256,
        query_sha256,
    )

    dependencies = (
        FocusDependency(
            namespace="task",
            root_sha256=(
                task_root.root_sha256()
            ),
        ),
        FocusDependency(
            namespace="source",
            root_sha256=(
                source_root.root_sha256()
            ),
        ),
        FocusDependency(
            namespace=(
                "capability.neighborhood"
            ),
            root_sha256=(
                capability_root
                .root_sha256()
            ),
        ),
        FocusDependency(
            namespace=(
                "compiler.neighborhood"
            ),
            root_sha256=(
                request
                .neighborhood_compiler_revision_sha256
            ),
        ),
        *request.relevant_roots,
    )

    binding = FocusBinding(
        domain=request.focus_domain,
        focus_id=request.focus_id,
        dependencies=dependencies,
        policy_revision_sha256=(
            request
            .policy_revision_sha256
        ),
        compiler_revision_sha256=(
            request
            .focus_compiler_revision_sha256
        ),
    )

    payload = {
        "schema":
            NEIGHBORHOOD_PAYLOAD_SCHEMA,
        "query_sha256":
            query_sha256,
        "task_root_sha256":
            task_root.root_sha256(),
        "source_root_sha256":
            source_root.root_sha256(),
        "capability_root_sha256":
            capability_root.root_sha256(),
        "semantic_items": [
            item.as_dict()
            for item in semantic_items
        ],
        "source_items": [
            item.as_dict()
            for item in source_items
        ],
        "relevant_roots": [
            item.as_dict()
            for item in sorted(
                request.relevant_roots,
                key=lambda value: (
                    value.namespace,
                    value.root_sha256,
                ),
            )
        ],
        "neighborhood_compiler_revision_sha256":
            request
            .neighborhood_compiler_revision_sha256,
    }

    payload_bytes = (
        focus_canonical_json(
            payload
        )
    )

    handle = compile_focus(
        binding,
        payload_bytes,
    )

    result = NeighborhoodCompilation(
        schema=(
            NEIGHBORHOOD_COMPILATION_SCHEMA
        ),
        task_root_sha256=(
            task_root.root_sha256()
        ),
        source_root_sha256=(
            source_root.root_sha256()
        ),
        capability_root_sha256=(
            capability_root.root_sha256()
        ),
        query_sha256=query_sha256,
        semantic_items=semantic_items,
        source_items=source_items,
        binding=binding,
        handle=handle,
    )

    result.validate()

    return result
