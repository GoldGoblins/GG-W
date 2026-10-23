"""Resident reverse dependency index for compiled GG focus handles.

The immutable Merkle DAG remains the source of dependency identity.
This module maintains only bounded mutable runtime routing state:

    dependency identity -> resident focus handle IDs

A change invalidates only handles registered against the old dependency root.
Recompilation is demand-driven and is deliberately outside this layer.

Hot lookup delegates directly to CompiledFocusCache and does not traverse the
reverse index, recompute Merkle roots, discover capabilities, touch disk, call
a model or execute a registered capability.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

if __package__:
    from . import compiled_focus as _compiled_focus
else:
    import compiled_focus as _compiled_focus

CompiledFocusCache = _compiled_focus.CompiledFocusCache
CompiledFocusHandle = _compiled_focus.CompiledFocusHandle
FocusBinding = _compiled_focus.FocusBinding
FocusDependency = _compiled_focus.FocusDependency



DEPENDENCY_KEY_SCHEMA = (
    "gg.incremental-focus-dependency-key.v1"
)
DEPENDENCY_CHANGE_SCHEMA = (
    "gg.incremental-focus-change.v1"
)
INVALIDATION_RESULT_SCHEMA = (
    "gg.incremental-focus-invalidation.v1"
)

POLICY_DEPENDENCY_NAMESPACE = (
    "binding.policy_revision"
)
COMPILER_DEPENDENCY_NAMESPACE = (
    "binding.compiler_revision"
)

_RESERVED_NAMESPACES = frozenset(
    (
        POLICY_DEPENDENCY_NAMESPACE,
        COMPILER_DEPENDENCY_NAMESPACE,
    )
)


class IncrementalFocusError(
    RuntimeError
):
    """Incremental focus routing contract violation."""


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
        raise IncrementalFocusError(
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
        raise IncrementalFocusError(
            label
            + "_TEXT_INVALID"
        )

    return value


@dataclass(frozen=True)
class DependencyKey:
    namespace: str
    root_sha256: str

    def validate(
        self,
    ) -> None:
        _require_text(
            self.namespace,
            "DEPENDENCY_NAMESPACE",
            maximum=512,
        )

        _require_sha256(
            self.root_sha256,
            "DEPENDENCY_ROOT",
        )

    def as_tuple(
        self,
    ) -> tuple[str, str]:
        self.validate()

        return (
            self.namespace,
            self.root_sha256,
        )

    def as_dict(
        self,
    ) -> dict[str, str]:
        self.validate()

        return {
            "schema":
                DEPENDENCY_KEY_SCHEMA,
            "namespace":
                self.namespace,
            "root_sha256":
                self.root_sha256,
        }


@dataclass(frozen=True)
class DependencyChange:
    namespace: str
    old_root_sha256: str
    new_root_sha256: str

    def validate(
        self,
    ) -> None:
        _require_text(
            self.namespace,
            "CHANGE_NAMESPACE",
            maximum=512,
        )

        _require_sha256(
            self.old_root_sha256,
            "CHANGE_OLD_ROOT",
        )

        _require_sha256(
            self.new_root_sha256,
            "CHANGE_NEW_ROOT",
        )

    @property
    def changed(
        self,
    ) -> bool:
        self.validate()

        return (
            self.old_root_sha256
            != self.new_root_sha256
        )

    def old_key(
        self,
    ) -> DependencyKey:
        self.validate()

        return DependencyKey(
            namespace=self.namespace,
            root_sha256=(
                self.old_root_sha256
            ),
        )


@dataclass(frozen=True)
class InvalidationResult:
    schema: str
    namespace: str
    old_root_sha256: str
    new_root_sha256: str
    changed: bool
    invalidated_handle_ids: tuple[
        str,
        ...
    ]
    recompile_mode: str = "ON_DEMAND"
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
            != INVALIDATION_RESULT_SCHEMA
        ):
            raise IncrementalFocusError(
                "INVALIDATION_SCHEMA_INVALID"
            )

        _require_text(
            self.namespace,
            "INVALIDATION_NAMESPACE",
            maximum=512,
        )

        _require_sha256(
            self.old_root_sha256,
            "INVALIDATION_OLD_ROOT",
        )

        _require_sha256(
            self.new_root_sha256,
            "INVALIDATION_NEW_ROOT",
        )

        if not isinstance(
            self.changed,
            bool,
        ):
            raise IncrementalFocusError(
                "INVALIDATION_CHANGED_INVALID"
            )

        if not isinstance(
            self.invalidated_handle_ids,
            tuple,
        ):
            raise IncrementalFocusError(
                "INVALIDATED_HANDLES_INVALID"
            )

        for handle_id in (
            self.invalidated_handle_ids
        ):
            _require_sha256(
                handle_id,
                "INVALIDATED_HANDLE",
            )

        if (
            self.recompile_mode
            != "ON_DEMAND"
        ):
            raise IncrementalFocusError(
                "RECOMPILE_MODE_INVALID"
            )

        if self.action_authority != "NONE":
            raise IncrementalFocusError(
                "ACTION_AUTHORITY_INVALID"
            )

        if self.promotion_authority != "NONE":
            raise IncrementalFocusError(
                "PROMOTION_AUTHORITY_INVALID"
            )

        if self.persistent_write != "NONE":
            raise IncrementalFocusError(
                "PERSISTENT_WRITE_INVALID"
            )

        if self.model_inference is not False:
            raise IncrementalFocusError(
                "MODEL_INFERENCE_INVALID"
            )

        if (
            self.registered_capability_execution
            is not False
        ):
            raise IncrementalFocusError(
                "REGISTERED_EXECUTION_INVALID"
            )


def _dependency_key(
    dependency: FocusDependency,
) -> DependencyKey:
    if not isinstance(
        dependency,
        FocusDependency,
    ):
        raise IncrementalFocusError(
            "FOCUS_DEPENDENCY_TYPE_INVALID"
        )

    dependency.validate()

    if (
        dependency.namespace
        in _RESERVED_NAMESPACES
    ):
        raise IncrementalFocusError(
            "DEPENDENCY_NAMESPACE_RESERVED"
        )

    return DependencyKey(
        namespace=dependency.namespace,
        root_sha256=(
            dependency.root_sha256
        ),
    )


def _binding_keys(
    binding: FocusBinding,
) -> tuple[
    DependencyKey,
    ...
]:
    if not isinstance(
        binding,
        FocusBinding,
    ):
        raise IncrementalFocusError(
            "FOCUS_BINDING_TYPE_INVALID"
        )

    binding.validate()

    values = [
        _dependency_key(
            dependency
        )
        for dependency
        in binding.dependencies
    ]

    values.extend(
        (
            DependencyKey(
                namespace=(
                    POLICY_DEPENDENCY_NAMESPACE
                ),
                root_sha256=(
                    binding
                    .policy_revision_sha256
                ),
            ),
            DependencyKey(
                namespace=(
                    COMPILER_DEPENDENCY_NAMESPACE
                ),
                root_sha256=(
                    binding
                    .compiler_revision_sha256
                ),
            ),
        )
    )

    unique = {
        item.as_tuple(): item
        for item in values
    }

    return tuple(
        unique[key]
        for key in sorted(
            unique
        )
    )


def _validate_binding_handle(
    binding: FocusBinding,
    handle: CompiledFocusHandle,
) -> None:
    if not isinstance(
        binding,
        FocusBinding,
    ):
        raise IncrementalFocusError(
            "FOCUS_BINDING_TYPE_INVALID"
        )

    if not isinstance(
        handle,
        CompiledFocusHandle,
    ):
        raise IncrementalFocusError(
            "FOCUS_HANDLE_TYPE_INVALID"
        )

    binding.validate()
    handle.validate()

    if (
        binding.binding_sha256()
        != handle.binding_sha256
    ):
        raise IncrementalFocusError(
            "FOCUS_BINDING_HANDLE_MISMATCH"
        )

    if (
        binding.dependency_root_sha256()
        != handle.dependency_root_sha256
    ):
        raise IncrementalFocusError(
            "FOCUS_DEPENDENCY_ROOT_MISMATCH"
        )

    if binding.domain != handle.domain:
        raise IncrementalFocusError(
            "FOCUS_DOMAIN_MISMATCH"
        )

    if binding.focus_id != handle.focus_id:
        raise IncrementalFocusError(
            "FOCUS_ID_MISMATCH"
        )

    if (
        binding.policy_revision_sha256
        != handle.policy_revision_sha256
    ):
        raise IncrementalFocusError(
            "FOCUS_POLICY_MISMATCH"
        )

    if (
        binding.compiler_revision_sha256
        != handle.compiler_revision_sha256
    ):
        raise IncrementalFocusError(
            "FOCUS_COMPILER_MISMATCH"
        )


class IncrementalFocusIndex:
    """Bounded resident reverse dependency index plus compiled-focus cache."""

    def __init__(
        self,
        *,
        max_entries: int = 256,
    ) -> None:
        self._cache = (
            CompiledFocusCache(
                max_entries=max_entries
            )
        )

        self._max_entries = max_entries

        self._bindings: dict[
            str,
            FocusBinding,
        ] = {}

        self._keys_by_handle: dict[
            str,
            tuple[
                DependencyKey,
                ...
            ],
        ] = {}

        self._reverse: dict[
            DependencyKey,
            set[str],
        ] = {}

        self._insertion_order: deque[
            str
        ] = deque()

    @property
    def size(
        self,
    ) -> int:
        return len(
            self._bindings
        )

    def lookup(
        self,
        handle_id: str,
    ) -> CompiledFocusHandle | None:
        return self._cache.lookup(
            handle_id
        )

    def _assert_size_consistent(
        self,
    ) -> None:
        if (
            self._cache.size
            != len(self._bindings)
        ):
            raise IncrementalFocusError(
                "FOCUS_CACHE_INDEX_SIZE_MISMATCH"
            )

    def _drop(
        self,
        handle_id: str,
        *,
        order_already_removed: bool,
    ) -> bool:
        binding = self._bindings.get(
            handle_id
        )

        if binding is None:
            if (
                self._cache.lookup(
                    handle_id
                )
                is not None
            ):
                raise IncrementalFocusError(
                    "UNINDEXED_FOCUS_HANDLE"
                )

            return False

        keys = self._keys_by_handle.get(
            handle_id
        )

        if keys is None:
            raise IncrementalFocusError(
                "FOCUS_DEPENDENCY_INDEX_MISSING"
            )

        if (
            self._cache.lookup(
                handle_id
            )
            is None
        ):
            raise IncrementalFocusError(
                "INDEXED_FOCUS_HANDLE_MISSING"
            )

        for key in keys:
            bucket = self._reverse.get(
                key
            )

            if (
                bucket is None
                or handle_id
                not in bucket
            ):
                raise IncrementalFocusError(
                    "REVERSE_DEPENDENCY_INDEX_CORRUPT"
                )

        if not order_already_removed:
            try:
                self._insertion_order.remove(
                    handle_id
                )
            except ValueError as exc:
                raise IncrementalFocusError(
                    "INCREMENTAL_ORDER_CORRUPT"
                ) from exc

        for key in keys:
            bucket = self._reverse[
                key
            ]

            bucket.remove(
                handle_id
            )

            if not bucket:
                self._reverse.pop(
                    key,
                    None,
                )

        self._keys_by_handle.pop(
            handle_id
        )

        self._bindings.pop(
            handle_id
        )

        if not self._cache.discard(
            handle_id
        ):
            raise IncrementalFocusError(
                "FOCUS_CACHE_DISCARD_FAILED"
            )

        self._assert_size_consistent()

        return True

    def register(
        self,
        binding: FocusBinding,
        handle: CompiledFocusHandle,
    ) -> CompiledFocusHandle:
        _validate_binding_handle(
            binding,
            handle,
        )

        keys = _binding_keys(
            binding
        )

        existing_binding = (
            self._bindings.get(
                handle.handle_id
            )
        )

        if existing_binding is not None:
            if (
                existing_binding
                .binding_sha256()
                != binding
                .binding_sha256()
            ):
                raise IncrementalFocusError(
                    "FOCUS_REGISTRATION_COLLISION"
                )

            stored = self._cache.store(
                handle
            )

            self._assert_size_consistent()

            return stored

        if (
            len(self._bindings)
            >= self._max_entries
        ):
            oldest = (
                self._insertion_order
                .popleft()
            )

            if not self._drop(
                oldest,
                order_already_removed=True,
            ):
                raise IncrementalFocusError(
                    "CAPACITY_EVICTION_FAILED"
                )

        stored = self._cache.store(
            handle
        )

        self._bindings[
            handle.handle_id
        ] = binding

        self._keys_by_handle[
            handle.handle_id
        ] = keys

        self._insertion_order.append(
            handle.handle_id
        )

        for key in keys:
            self._reverse.setdefault(
                key,
                set(),
            ).add(
                handle.handle_id
            )

        self._assert_size_consistent()

        return stored

    def discard(
        self,
        handle_id: str,
    ) -> bool:
        return self._drop(
            handle_id,
            order_already_removed=False,
        )

    def apply_change(
        self,
        change: DependencyChange,
    ) -> InvalidationResult:
        if not isinstance(
            change,
            DependencyChange,
        ):
            raise IncrementalFocusError(
                "DEPENDENCY_CHANGE_TYPE_INVALID"
            )

        change.validate()

        if not change.changed:
            result = InvalidationResult(
                schema=(
                    INVALIDATION_RESULT_SCHEMA
                ),
                namespace=change.namespace,
                old_root_sha256=(
                    change.old_root_sha256
                ),
                new_root_sha256=(
                    change.new_root_sha256
                ),
                changed=False,
                invalidated_handle_ids=(),
            )

            result.validate()

            return result

        affected = tuple(
            sorted(
                self._reverse.get(
                    change.old_key(),
                    (),
                )
            )
        )

        for handle_id in affected:
            if not self._drop(
                handle_id,
                order_already_removed=False,
            ):
                raise IncrementalFocusError(
                    "AFFECTED_HANDLE_DROP_FAILED"
                )

        result = InvalidationResult(
            schema=(
                INVALIDATION_RESULT_SCHEMA
            ),
            namespace=change.namespace,
            old_root_sha256=(
                change.old_root_sha256
            ),
            new_root_sha256=(
                change.new_root_sha256
            ),
            changed=True,
            invalidated_handle_ids=(
                affected
            ),
        )

        result.validate()

        return result
