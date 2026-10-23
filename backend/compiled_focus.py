"""General content-addressed compiled-focus primitives for GG.

LaserFocus is treated here as an information-handling principle rather than a
router-specific feature:

* expensive discovery/derivation happens before the hot path;
* the resulting payload is bound to exact Merkle/content identities;
* a resident handle provides direct O(1) lookup;
* relevant identity drift creates a different binding and therefore misses
  closed instead of reusing stale information.

This module performs no filesystem I/O, model inference, graph search, network
access, persistent write or action-authority decision.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import hashlib
import json


FOCUS_DEPENDENCY_SCHEMA = (
    "gg.compiled-focus-dependency.v1"
)
FOCUS_DEPENDENCY_ROOT_SCHEMA = (
    "gg.compiled-focus-dependency-root.v1"
)
FOCUS_BINDING_SCHEMA = (
    "gg.compiled-focus-binding.v1"
)
FOCUS_HANDLE_SCHEMA = (
    "gg.compiled-focus-handle.v1"
)

MAX_DEPENDENCIES = 64
MAX_PAYLOAD_BYTES = 1_048_576


class CompiledFocusError(
    RuntimeError
):
    """Compiled-focus contract violation."""


def canonical_json(
    value: object,
) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def digest_json(
    value: object,
) -> str:
    return hashlib.sha256(
        canonical_json(value)
    ).hexdigest()


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
        raise CompiledFocusError(
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
        raise CompiledFocusError(
            label
            + "_TEXT_INVALID"
        )

    return value


@dataclass(frozen=True)
class FocusDependency:
    namespace: str
    root_sha256: str

    def validate(
        self,
    ) -> None:
        _require_text(
            self.namespace,
            "DEPENDENCY_NAMESPACE",
            maximum=128,
        )

        _require_sha256(
            self.root_sha256,
            "DEPENDENCY_ROOT",
        )

    def as_dict(
        self,
    ) -> dict[str, str]:
        self.validate()

        return {
            "schema":
                FOCUS_DEPENDENCY_SCHEMA,
            "namespace":
                self.namespace,
            "root_sha256":
                self.root_sha256,
        }


@dataclass(frozen=True)
class FocusBinding:
    domain: str
    focus_id: str
    dependencies: tuple[
        FocusDependency,
        ...
    ]
    policy_revision_sha256: str
    compiler_revision_sha256: str

    def validate(
        self,
    ) -> None:
        _require_text(
            self.domain,
            "FOCUS_DOMAIN",
            maximum=128,
        )

        _require_text(
            self.focus_id,
            "FOCUS_ID",
            maximum=512,
        )

        _require_sha256(
            self.policy_revision_sha256,
            "FOCUS_POLICY_REVISION",
        )

        _require_sha256(
            self.compiler_revision_sha256,
            "FOCUS_COMPILER_REVISION",
        )

        if (
            not isinstance(
                self.dependencies,
                tuple,
            )
            or not self.dependencies
            or len(
                self.dependencies
            ) > MAX_DEPENDENCIES
        ):
            raise CompiledFocusError(
                "FOCUS_DEPENDENCIES_INVALID"
            )

        seen: set[str] = set()

        for dependency in self.dependencies:
            if not isinstance(
                dependency,
                FocusDependency,
            ):
                raise CompiledFocusError(
                    "FOCUS_DEPENDENCY_TYPE_INVALID"
                )

            dependency.validate()

            if (
                dependency.namespace
                in seen
            ):
                raise CompiledFocusError(
                    "FOCUS_DEPENDENCY_NAMESPACE_DUPLICATE"
                )

            seen.add(
                dependency.namespace
            )

    def _ordered_dependencies(
        self,
    ) -> tuple[
        FocusDependency,
        ...
    ]:
        self.validate()

        return tuple(
            sorted(
                self.dependencies,
                key=lambda item: (
                    item.namespace,
                    item.root_sha256,
                ),
            )
        )

    def dependency_root_sha256(
        self,
    ) -> str:
        return digest_json(
            {
                "schema":
                    FOCUS_DEPENDENCY_ROOT_SCHEMA,
                "dependencies": [
                    dependency.as_dict()
                    for dependency
                    in self._ordered_dependencies()
                ],
            }
        )

    def as_dict(
        self,
    ) -> dict[str, object]:
        self.validate()

        return {
            "schema":
                FOCUS_BINDING_SCHEMA,
            "domain":
                self.domain,
            "focus_id":
                self.focus_id,
            "dependency_root_sha256":
                self.dependency_root_sha256(),
            "dependencies": [
                dependency.as_dict()
                for dependency
                in self._ordered_dependencies()
            ],
            "policy_revision_sha256":
                self.policy_revision_sha256,
            "compiler_revision_sha256":
                self.compiler_revision_sha256,
        }

    def binding_sha256(
        self,
    ) -> str:
        return digest_json(
            self.as_dict()
        )


@dataclass(frozen=True)
class CompiledFocusHandle:
    schema: str
    handle_id: str
    domain: str
    focus_id: str
    binding_sha256: str
    dependency_root_sha256: str
    policy_revision_sha256: str
    compiler_revision_sha256: str
    payload_sha256: str
    payload_bytes: bytes
    action_authority: str
    promotion_authority: str
    persistent_write: str
    model_inference: bool

    def validate(
        self,
    ) -> None:
        if self.schema != FOCUS_HANDLE_SCHEMA:
            raise CompiledFocusError(
                "FOCUS_HANDLE_SCHEMA_INVALID"
            )

        _require_sha256(
            self.handle_id,
            "FOCUS_HANDLE_ID",
        )

        _require_sha256(
            self.binding_sha256,
            "FOCUS_HANDLE_BINDING",
        )

        if (
            self.handle_id
            != self.binding_sha256
        ):
            raise CompiledFocusError(
                "FOCUS_HANDLE_ID_BINDING_MISMATCH"
            )

        _require_text(
            self.domain,
            "FOCUS_HANDLE_DOMAIN",
            maximum=128,
        )

        _require_text(
            self.focus_id,
            "FOCUS_HANDLE_FOCUS_ID",
            maximum=512,
        )

        _require_sha256(
            self.dependency_root_sha256,
            "FOCUS_HANDLE_DEPENDENCY_ROOT",
        )

        _require_sha256(
            self.policy_revision_sha256,
            "FOCUS_HANDLE_POLICY",
        )

        _require_sha256(
            self.compiler_revision_sha256,
            "FOCUS_HANDLE_COMPILER",
        )

        _require_sha256(
            self.payload_sha256,
            "FOCUS_HANDLE_PAYLOAD",
        )

        if not isinstance(
            self.payload_bytes,
            bytes,
        ):
            raise CompiledFocusError(
                "FOCUS_PAYLOAD_TYPE_INVALID"
            )

        if (
            len(self.payload_bytes)
            > MAX_PAYLOAD_BYTES
        ):
            raise CompiledFocusError(
                "FOCUS_PAYLOAD_TOO_LARGE"
            )

        actual_payload_sha256 = (
            hashlib.sha256(
                self.payload_bytes
            ).hexdigest()
        )

        if (
            actual_payload_sha256
            != self.payload_sha256
        ):
            raise CompiledFocusError(
                "FOCUS_PAYLOAD_BINDING_MISMATCH"
            )

        if self.action_authority != "NONE":
            raise CompiledFocusError(
                "FOCUS_ACTION_AUTHORITY_INVALID"
            )

        if (
            self.promotion_authority
            != "NONE"
        ):
            raise CompiledFocusError(
                "FOCUS_PROMOTION_AUTHORITY_INVALID"
            )

        if self.persistent_write != "NONE":
            raise CompiledFocusError(
                "FOCUS_PERSISTENT_WRITE_INVALID"
            )

        if self.model_inference is not False:
            raise CompiledFocusError(
                "FOCUS_MODEL_INFERENCE_INVALID"
            )

    def as_dict(
        self,
    ) -> dict[str, object]:
        self.validate()

        return {
            "schema":
                self.schema,
            "handle_id":
                self.handle_id,
            "domain":
                self.domain,
            "focus_id":
                self.focus_id,
            "binding_sha256":
                self.binding_sha256,
            "dependency_root_sha256":
                self.dependency_root_sha256,
            "policy_revision_sha256":
                self.policy_revision_sha256,
            "compiler_revision_sha256":
                self.compiler_revision_sha256,
            "payload_sha256":
                self.payload_sha256,
            "payload_size":
                len(self.payload_bytes),
            "action_authority":
                self.action_authority,
            "promotion_authority":
                self.promotion_authority,
            "persistent_write":
                self.persistent_write,
            "model_inference":
                self.model_inference,
        }

    def handle_sha256(
        self,
    ) -> str:
        return digest_json(
            self.as_dict()
        )


def compile_focus(
    binding: FocusBinding,
    payload_bytes: bytes,
) -> CompiledFocusHandle:
    if not isinstance(
        binding,
        FocusBinding,
    ):
        raise CompiledFocusError(
            "FOCUS_BINDING_TYPE_INVALID"
        )

    binding.validate()

    if not isinstance(
        payload_bytes,
        bytes,
    ):
        raise CompiledFocusError(
            "FOCUS_PAYLOAD_TYPE_INVALID"
        )

    if (
        len(payload_bytes)
        > MAX_PAYLOAD_BYTES
    ):
        raise CompiledFocusError(
            "FOCUS_PAYLOAD_TOO_LARGE"
        )

    binding_sha256 = (
        binding.binding_sha256()
    )

    handle = CompiledFocusHandle(
        schema=FOCUS_HANDLE_SCHEMA,
        handle_id=binding_sha256,
        domain=binding.domain,
        focus_id=binding.focus_id,
        binding_sha256=binding_sha256,
        dependency_root_sha256=(
            binding
            .dependency_root_sha256()
        ),
        policy_revision_sha256=(
            binding
            .policy_revision_sha256
        ),
        compiler_revision_sha256=(
            binding
            .compiler_revision_sha256
        ),
        payload_sha256=(
            hashlib.sha256(
                payload_bytes
            ).hexdigest()
        ),
        payload_bytes=payload_bytes,
        action_authority="NONE",
        promotion_authority="NONE",
        persistent_write="NONE",
        model_inference=False,
    )

    handle.validate()

    return handle


class CompiledFocusCache:
    """Bounded resident cache of already-compiled focus handles."""

    def __init__(
        self,
        *,
        max_entries: int = 256,
    ) -> None:
        if (
            max_entries < 1
            or max_entries > 4096
        ):
            raise CompiledFocusError(
                "FOCUS_MAX_ENTRIES_INVALID"
            )

        self._max_entries = max_entries
        self._handles: dict[
            str,
            CompiledFocusHandle,
        ] = {}
        self._insertion_order: deque[
            str
        ] = deque()

    @property
    def size(
        self,
    ) -> int:
        return len(
            self._handles
        )

    def lookup(
        self,
        handle_id: str,
    ) -> CompiledFocusHandle | None:
        return self._handles.get(
            handle_id
        )

    def store(
        self,
        handle: CompiledFocusHandle,
    ) -> CompiledFocusHandle:
        if not isinstance(
            handle,
            CompiledFocusHandle,
        ):
            raise CompiledFocusError(
                "FOCUS_HANDLE_TYPE_INVALID"
            )

        handle.validate()

        existing = self._handles.get(
            handle.handle_id
        )

        if existing is not None:
            if (
                existing.handle_sha256()
                != handle.handle_sha256()
                or existing.payload_bytes
                != handle.payload_bytes
            ):
                raise CompiledFocusError(
                    "FOCUS_HANDLE_COLLISION"
                )

            return existing

        if (
            len(self._handles)
            >= self._max_entries
        ):
            oldest = (
                self._insertion_order
                .popleft()
            )

            self._handles.pop(
                oldest,
                None,
            )

        self._handles[
            handle.handle_id
        ] = handle

        self._insertion_order.append(
            handle.handle_id
        )

        return handle

    def compile_and_store(
        self,
        binding: FocusBinding,
        payload_bytes: bytes,
    ) -> CompiledFocusHandle:
        return self.store(
            compile_focus(
                binding,
                payload_bytes,
            )
        )

    def discard(
        self,
        handle_id: str,
    ) -> bool:
        existing = self._handles.get(
            handle_id
        )

        if existing is None:
            return False

        try:
            self._insertion_order.remove(
                handle_id
            )
        except ValueError as exc:
            raise CompiledFocusError(
                "FOCUS_CACHE_ORDER_CORRUPT"
            ) from exc

        removed = self._handles.pop(
            handle_id,
            None,
        )

        if removed is not existing:
            raise CompiledFocusError(
                "FOCUS_CACHE_HANDLE_CORRUPT"
            )

        return True
