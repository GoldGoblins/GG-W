"""Resident Merkle propagation DAG for GG.

Stable node IDs answer *which* leaf/subtree changed. Merkle roots answer
*what exact state* the node currently represents.

Registration builds a bounded reverse-parent index once. A leaf change then
walks only its actual ancestors, recomputes only those parent roots and emits
exact DependencyChange records for parent roots exposed to IncrementalFocus.

No filesystem scan, global node scan, focus-handle scan, model inference,
registered-capability execution or persistent write exists in this layer.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Protocol

if __package__:
    from . import domain_merkle as _domain_merkle
    from . import incremental_focus as _incremental_focus
else:
    import domain_merkle as _domain_merkle
    import incremental_focus as _incremental_focus

DomainMerkleRoot = _domain_merkle.DomainMerkleRoot
MerkleChild = _domain_merkle.MerkleChild
build_domain_root = _domain_merkle.build_domain_root
DependencyChange = _incremental_focus.DependencyChange
InvalidationResult = _incremental_focus.InvalidationResult



LEAF_KIND = "LEAF"
SUBTREE_KIND = "SUBTREE"

PROPAGATION_RESULT_SCHEMA = (
    "gg.merkle-propagation-result.v1"
)
ROOT_CHANGE_SCHEMA = (
    "gg.merkle-root-change.v1"
)

MAX_DEPENDENCY_NAMESPACES = 16


class MerklePropagationError(
    RuntimeError
):
    """Resident Merkle propagation contract violation."""


class FocusInvalidator(
    Protocol
):
    def apply_change(
        self,
        change: DependencyChange,
    ) -> InvalidationResult:
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
        raise MerklePropagationError(
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
        raise MerklePropagationError(
            label
            + "_TEXT_INVALID"
        )

    return value


@dataclass(frozen=True)
class LeafSpec:
    node_id: str
    content_sha256: str

    def validate(
        self,
    ) -> None:
        _require_text(
            self.node_id,
            "LEAF_NODE_ID",
            maximum=1024,
        )

        _require_sha256(
            self.content_sha256,
            "LEAF_CONTENT",
        )


@dataclass(frozen=True)
class ChildRef:
    namespace: str
    node_id: str
    kind: str

    def validate(
        self,
    ) -> None:
        _require_text(
            self.namespace,
            "CHILD_NAMESPACE",
            maximum=1024,
        )

        _require_text(
            self.node_id,
            "CHILD_NODE_ID",
            maximum=1024,
        )

        if self.kind not in {
            LEAF_KIND,
            SUBTREE_KIND,
        }:
            raise MerklePropagationError(
                "CHILD_KIND_INVALID"
            )


@dataclass(frozen=True)
class ParentSpec:
    node_id: str
    domain: str
    scope: str
    children: tuple[
        ChildRef,
        ...
    ]
    dependency_namespaces: tuple[
        str,
        ...
    ] = ()

    def validate(
        self,
    ) -> None:
        _require_text(
            self.node_id,
            "PARENT_NODE_ID",
            maximum=1024,
        )

        _require_text(
            self.domain,
            "PARENT_DOMAIN",
            maximum=128,
        )

        _require_text(
            self.scope,
            "PARENT_SCOPE",
            maximum=1024,
        )

        if (
            not isinstance(
                self.children,
                tuple,
            )
            or not self.children
        ):
            raise MerklePropagationError(
                "PARENT_CHILDREN_INVALID"
            )

        seen_namespaces: set[str] = set()

        for child in self.children:
            if not isinstance(
                child,
                ChildRef,
            ):
                raise MerklePropagationError(
                    "CHILD_REF_TYPE_INVALID"
                )

            child.validate()

            if (
                child.namespace
                in seen_namespaces
            ):
                raise MerklePropagationError(
                    "CHILD_NAMESPACE_DUPLICATE"
                )

            seen_namespaces.add(
                child.namespace
            )

        if (
            not isinstance(
                self.dependency_namespaces,
                tuple,
            )
            or len(
                self.dependency_namespaces
            ) > MAX_DEPENDENCY_NAMESPACES
        ):
            raise MerklePropagationError(
                "DEPENDENCY_NAMESPACES_INVALID"
            )

        if (
            len(
                set(
                    self.dependency_namespaces
                )
            )
            != len(
                self.dependency_namespaces
            )
        ):
            raise MerklePropagationError(
                "DEPENDENCY_NAMESPACE_DUPLICATE"
            )

        for namespace in (
            self.dependency_namespaces
        ):
            _require_text(
                namespace,
                "DEPENDENCY_NAMESPACE",
                maximum=512,
            )


@dataclass(frozen=True)
class LeafChange:
    node_id: str
    old_content_sha256: str
    new_content_sha256: str

    def validate(
        self,
    ) -> None:
        _require_text(
            self.node_id,
            "CHANGE_NODE_ID",
            maximum=1024,
        )

        _require_sha256(
            self.old_content_sha256,
            "CHANGE_OLD_CONTENT",
        )

        _require_sha256(
            self.new_content_sha256,
            "CHANGE_NEW_CONTENT",
        )

    @property
    def changed(
        self,
    ) -> bool:
        self.validate()

        return (
            self.old_content_sha256
            != self.new_content_sha256
        )


@dataclass(frozen=True)
class RootChange:
    schema: str
    node_id: str
    old_root_sha256: str
    new_root_sha256: str
    dependency_namespaces: tuple[
        str,
        ...
    ]

    def validate(
        self,
    ) -> None:
        if self.schema != ROOT_CHANGE_SCHEMA:
            raise MerklePropagationError(
                "ROOT_CHANGE_SCHEMA_INVALID"
            )

        _require_text(
            self.node_id,
            "ROOT_CHANGE_NODE_ID",
            maximum=1024,
        )

        _require_sha256(
            self.old_root_sha256,
            "ROOT_CHANGE_OLD",
        )

        _require_sha256(
            self.new_root_sha256,
            "ROOT_CHANGE_NEW",
        )

        if (
            self.old_root_sha256
            == self.new_root_sha256
        ):
            raise MerklePropagationError(
                "ROOT_CHANGE_NOT_CHANGED"
            )

        for namespace in (
            self.dependency_namespaces
        ):
            _require_text(
                namespace,
                "ROOT_CHANGE_NAMESPACE",
                maximum=512,
            )


@dataclass(frozen=True)
class PropagationResult:
    schema: str
    leaf_node_id: str
    old_content_sha256: str
    new_content_sha256: str
    changed: bool
    affected_parent_ids: tuple[
        str,
        ...
    ]
    root_changes: tuple[
        RootChange,
        ...
    ]
    dependency_changes: tuple[
        DependencyChange,
        ...
    ]
    focus_invalidations: tuple[
        InvalidationResult,
        ...
    ]
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
            != PROPAGATION_RESULT_SCHEMA
        ):
            raise MerklePropagationError(
                "PROPAGATION_SCHEMA_INVALID"
            )

        _require_text(
            self.leaf_node_id,
            "RESULT_LEAF_NODE_ID",
            maximum=1024,
        )

        _require_sha256(
            self.old_content_sha256,
            "RESULT_OLD_CONTENT",
        )

        _require_sha256(
            self.new_content_sha256,
            "RESULT_NEW_CONTENT",
        )

        if not isinstance(
            self.changed,
            bool,
        ):
            raise MerklePropagationError(
                "RESULT_CHANGED_INVALID"
            )

        for node_id in (
            self.affected_parent_ids
        ):
            _require_text(
                node_id,
                "AFFECTED_PARENT_ID",
                maximum=1024,
            )

        for change in self.root_changes:
            if not isinstance(
                change,
                RootChange,
            ):
                raise MerklePropagationError(
                    "ROOT_CHANGE_TYPE_INVALID"
                )

            change.validate()

        for change in (
            self.dependency_changes
        ):
            if not isinstance(
                change,
                DependencyChange,
            ):
                raise MerklePropagationError(
                    "DEPENDENCY_CHANGE_TYPE_INVALID"
                )

            change.validate()

        for result in (
            self.focus_invalidations
        ):
            if not isinstance(
                result,
                InvalidationResult,
            ):
                raise MerklePropagationError(
                    "INVALIDATION_RESULT_TYPE_INVALID"
                )

            result.validate()

        if self.action_authority != "NONE":
            raise MerklePropagationError(
                "ACTION_AUTHORITY_INVALID"
            )

        if self.promotion_authority != "NONE":
            raise MerklePropagationError(
                "PROMOTION_AUTHORITY_INVALID"
            )

        if self.persistent_write != "NONE":
            raise MerklePropagationError(
                "PERSISTENT_WRITE_INVALID"
            )

        if self.model_inference is not False:
            raise MerklePropagationError(
                "MODEL_INFERENCE_INVALID"
            )

        if (
            self.registered_capability_execution
            is not False
        ):
            raise MerklePropagationError(
                "REGISTERED_EXECUTION_INVALID"
            )


class ResidentMerklePropagationDAG:
    """Bounded resident parent graph with localized change propagation."""

    def __init__(
        self,
        leaf_specs: tuple[
            LeafSpec,
            ...
        ],
        parent_specs: tuple[
            ParentSpec,
            ...
        ],
        *,
        max_nodes: int = 4096,
        max_parent_fanout: int = 64,
        max_propagation_depth: int = 64,
        max_affected_nodes: int = 1024,
    ) -> None:
        for value, label, maximum in (
            (
                max_nodes,
                "MAX_NODES",
                65536,
            ),
            (
                max_parent_fanout,
                "MAX_PARENT_FANOUT",
                4096,
            ),
            (
                max_propagation_depth,
                "MAX_PROPAGATION_DEPTH",
                1024,
            ),
            (
                max_affected_nodes,
                "MAX_AFFECTED_NODES",
                65536,
            ),
        ):
            if (
                not isinstance(
                    value,
                    int,
                )
                or value < 1
                or value > maximum
            ):
                raise MerklePropagationError(
                    label
                    + "_INVALID"
                )

        if (
            not isinstance(
                leaf_specs,
                tuple,
            )
            or not isinstance(
                parent_specs,
                tuple,
            )
        ):
            raise MerklePropagationError(
                "NODE_SPECS_INVALID"
            )

        if (
            len(leaf_specs)
            + len(parent_specs)
            > max_nodes
        ):
            raise MerklePropagationError(
                "NODE_LIMIT_EXCEEDED"
            )

        self._max_nodes = max_nodes
        self._max_parent_fanout = (
            max_parent_fanout
        )
        self._max_propagation_depth = (
            max_propagation_depth
        )
        self._max_affected_nodes = (
            max_affected_nodes
        )

        self._leaves: dict[
            str,
            LeafSpec,
        ] = {}

        self._parents: dict[
            str,
            ParentSpec,
        ] = {}

        for leaf_spec in leaf_specs:
            if not isinstance(
                leaf_spec,
                LeafSpec,
            ):
                raise MerklePropagationError(
                    "LEAF_SPEC_TYPE_INVALID"
                )

            leaf_spec.validate()

            if (
                leaf_spec.node_id
                in self._leaves
            ):
                raise MerklePropagationError(
                    "LEAF_NODE_DUPLICATE"
                )

            self._leaves[
                leaf_spec.node_id
            ] = leaf_spec

        for parent_spec in parent_specs:
            if not isinstance(
                parent_spec,
                ParentSpec,
            ):
                raise MerklePropagationError(
                    "PARENT_SPEC_TYPE_INVALID"
                )

            parent_spec.validate()

            if (
                parent_spec.node_id
                in self._parents
                or parent_spec.node_id
                in self._leaves
            ):
                raise MerklePropagationError(
                    "NODE_ID_DUPLICATE"
                )

            self._parents[
                parent_spec.node_id
            ] = parent_spec

        self._parents_by_child: dict[
            str,
            tuple[
                str,
                ...
            ],
        ] = {}

        mutable_reverse: dict[
            str,
            set[str],
        ] = {}

        all_nodes = (
            set(self._leaves)
            | set(self._parents)
        )

        for parent_spec in (
            self._parents.values()
        ):
            for child in (
                parent_spec.children
            ):
                if (
                    child.node_id
                    not in all_nodes
                ):
                    raise MerklePropagationError(
                        "CHILD_NODE_UNKNOWN:"
                        + child.node_id
                    )

                actual_kind = (
                    LEAF_KIND
                    if child.node_id
                    in self._leaves
                    else SUBTREE_KIND
                )

                if child.kind != actual_kind:
                    raise MerklePropagationError(
                        "CHILD_KIND_TARGET_MISMATCH"
                    )

                mutable_reverse.setdefault(
                    child.node_id,
                    set(),
                ).add(
                    parent_spec.node_id
                )

        for (
            child_id,
            parent_ids,
        ) in mutable_reverse.items():
            if (
                len(parent_ids)
                > self._max_parent_fanout
            ):
                raise MerklePropagationError(
                    "PARENT_FANOUT_LIMIT_EXCEEDED:"
                    + child_id
                )

            self._parents_by_child[
                child_id
            ] = tuple(
                sorted(
                    parent_ids
                )
            )

        parent_order = (
            self._parent_topological_order()
        )

        self._roots: dict[
            str,
            str,
        ] = {
            node_id:
                leaf_spec.content_sha256
            for node_id, leaf_spec
            in self._leaves.items()
        }

        for parent_id in parent_order:
            root = self._build_parent_root(
                self._parents[
                    parent_id
                ],
                self._roots,
            )

            self._roots[
                parent_id
            ] = root.root_sha256()

    @property
    def node_count(
        self,
    ) -> int:
        return (
            len(self._leaves)
            + len(self._parents)
        )

    def current_root(
        self,
        node_id: str,
    ) -> str:
        _require_text(
            node_id,
            "NODE_ID",
            maximum=1024,
        )

        try:
            return self._roots[
                node_id
            ]
        except KeyError as exc:
            raise MerklePropagationError(
                "NODE_UNKNOWN:"
                + node_id
            ) from exc

    def _parent_topological_order(
        self,
    ) -> tuple[str, ...]:
        indegree: dict[
            str,
            int,
        ] = {
            parent_id: 0
            for parent_id
            in self._parents
        }

        for (
            parent_id,
            parent_spec,
        ) in self._parents.items():
            indegree[
                parent_id
            ] = sum(
                1
                for child
                in parent_spec.children
                if child.node_id
                in self._parents
            )

        ready = deque(
            sorted(
                parent_id
                for parent_id, count
                in indegree.items()
                if count == 0
            )
        )

        order: list[str] = []

        while ready:
            parent_id = ready.popleft()

            order.append(
                parent_id
            )

            for super_parent in (
                self._parents_by_child.get(
                    parent_id,
                    (),
                )
            ):
                indegree[
                    super_parent
                ] -= 1

                if (
                    indegree[
                        super_parent
                    ]
                    == 0
                ):
                    ready.append(
                        super_parent
                    )

        if (
            len(order)
            != len(self._parents)
        ):
            raise MerklePropagationError(
                "MERKLE_PARENT_CYCLE"
            )

        return tuple(
            order
        )

    def _build_parent_root(
        self,
        parent_spec: ParentSpec,
        roots: dict[
            str,
            str,
        ],
    ) -> DomainMerkleRoot:
        children = tuple(
            MerkleChild(
                namespace=child.namespace,
                kind=child.kind,
                root_sha256=roots[
                    child.node_id
                ],
            )
            for child
            in parent_spec.children
        )

        return build_domain_root(
            parent_spec.domain,
            parent_spec.scope,
            children,
        )

    def _collect_affected_parents(
        self,
        leaf_node_id: str,
    ) -> tuple[
        set[str],
        dict[str, int],
    ]:
        affected: set[str] = set()

        depth_by_node: dict[
            str,
            int,
        ] = {
            leaf_node_id: 0
        }

        queue: deque[
            str
        ] = deque(
            (
                leaf_node_id,
            )
        )

        while queue:
            child_id = queue.popleft()

            child_depth = (
                depth_by_node[
                    child_id
                ]
            )

            for parent_id in (
                self._parents_by_child.get(
                    child_id,
                    (),
                )
            ):
                parent_depth = (
                    child_depth
                    + 1
                )

                if (
                    parent_depth
                    > self
                    ._max_propagation_depth
                ):
                    raise MerklePropagationError(
                        "PROPAGATION_DEPTH_LIMIT_EXCEEDED"
                    )

                previous = (
                    depth_by_node.get(
                        parent_id,
                        -1,
                    )
                )

                if (
                    parent_depth
                    <= previous
                ):
                    continue

                depth_by_node[
                    parent_id
                ] = parent_depth

                if (
                    parent_id
                    not in affected
                ):
                    affected.add(
                        parent_id
                    )

                    if (
                        len(affected)
                        > self
                        ._max_affected_nodes
                    ):
                        raise MerklePropagationError(
                            "AFFECTED_NODE_LIMIT_EXCEEDED"
                        )

                queue.append(
                    parent_id
                )

        return (
            affected,
            depth_by_node,
        )

    def _affected_topological_order(
        self,
        affected: set[str],
    ) -> tuple[str, ...]:
        indegree: dict[
            str,
            int,
        ] = {}

        for parent_id in affected:
            parent_spec = (
                self._parents[
                    parent_id
                ]
            )

            indegree[
                parent_id
            ] = sum(
                1
                for child
                in parent_spec.children
                if child.node_id
                in affected
            )

        ready = deque(
            sorted(
                parent_id
                for parent_id, count
                in indegree.items()
                if count == 0
            )
        )

        order: list[str] = []

        while ready:
            parent_id = ready.popleft()

            order.append(
                parent_id
            )

            for super_parent in (
                self._parents_by_child.get(
                    parent_id,
                    (),
                )
            ):
                if (
                    super_parent
                    not in affected
                ):
                    continue

                indegree[
                    super_parent
                ] -= 1

                if (
                    indegree[
                        super_parent
                    ]
                    == 0
                ):
                    ready.append(
                        super_parent
                    )

        if len(order) != len(affected):
            raise MerklePropagationError(
                "AFFECTED_PARENT_ORDER_INVALID"
            )

        return tuple(
            order
        )

    def apply_leaf_change(
        self,
        change: LeafChange,
        *,
        focus_index: FocusInvalidator
        | None = None,
    ) -> PropagationResult:
        if not isinstance(
            change,
            LeafChange,
        ):
            raise MerklePropagationError(
                "LEAF_CHANGE_TYPE_INVALID"
            )

        change.validate()

        if (
            change.node_id
            not in self._leaves
        ):
            raise MerklePropagationError(
                "CHANGE_LEAF_UNKNOWN"
            )

        current = self._roots[
            change.node_id
        ]

        if (
            current
            != change.old_content_sha256
        ):
            raise MerklePropagationError(
                "LEAF_PREIMAGE_MISMATCH"
            )

        if not change.changed:
            result = PropagationResult(
                schema=(
                    PROPAGATION_RESULT_SCHEMA
                ),
                leaf_node_id=change.node_id,
                old_content_sha256=(
                    change.old_content_sha256
                ),
                new_content_sha256=(
                    change.new_content_sha256
                ),
                changed=False,
                affected_parent_ids=(),
                root_changes=(),
                dependency_changes=(),
                focus_invalidations=(),
            )

            result.validate()

            return result

        affected, _ = (
            self._collect_affected_parents(
                change.node_id
            )
        )

        order = (
            self._affected_topological_order(
                affected
            )
        )

        proposed_roots: dict[
            str,
            str,
        ] = {
            change.node_id:
                change.new_content_sha256
        }

        root_changes: list[
            RootChange
        ] = []

        def root_for(
            node_id: str,
        ) -> str:
            value = proposed_roots.get(
                node_id
            )

            if value is not None:
                return value

            return self._roots[
                node_id
            ]

        for parent_id in order:
            parent_spec = (
                self._parents[
                    parent_id
                ]
            )

            child_roots = {
                child.node_id:
                    root_for(
                        child.node_id
                    )
                for child
                in parent_spec.children
            }

            root = self._build_parent_root(
                parent_spec,
                child_roots,
            )

            old_root = self._roots[
                parent_id
            ]

            new_root = (
                root.root_sha256()
            )

            if new_root == old_root:
                continue

            proposed_roots[
                parent_id
            ] = new_root

            root_change = RootChange(
                schema=ROOT_CHANGE_SCHEMA,
                node_id=parent_id,
                old_root_sha256=old_root,
                new_root_sha256=new_root,
                dependency_namespaces=(
                    parent_spec
                    .dependency_namespaces
                ),
            )

            root_change.validate()

            root_changes.append(
                root_change
            )

        dependency_changes: list[
            DependencyChange
        ] = []

        seen_dependency_changes: set[
            tuple[
                str,
                str,
                str,
            ]
        ] = set()

        for root_change in root_changes:
            for namespace in sorted(
                root_change
                .dependency_namespaces
            ):
                key = (
                    namespace,
                    root_change
                    .old_root_sha256,
                    root_change
                    .new_root_sha256,
                )

                if (
                    key
                    in seen_dependency_changes
                ):
                    continue

                seen_dependency_changes.add(
                    key
                )

                dependency_change = (
                    DependencyChange(
                        namespace=namespace,
                        old_root_sha256=(
                            root_change
                            .old_root_sha256
                        ),
                        new_root_sha256=(
                            root_change
                            .new_root_sha256
                        ),
                    )
                )

                dependency_change.validate()

                dependency_changes.append(
                    dependency_change
                )

        invalidations: list[
            InvalidationResult
        ] = []

        if focus_index is not None:
            if not hasattr(
                focus_index,
                "apply_change",
            ):
                raise MerklePropagationError(
                    "FOCUS_INVALIDATOR_INVALID"
                )

            for dependency_change in (
                dependency_changes
            ):
                invalidation = (
                    focus_index.apply_change(
                        dependency_change
                    )
                )

                if not isinstance(
                    invalidation,
                    InvalidationResult,
                ):
                    raise MerklePropagationError(
                        "FOCUS_INVALIDATION_RESULT_INVALID"
                    )

                invalidation.validate()

                invalidations.append(
                    invalidation
                )

        self._roots[
            change.node_id
        ] = change.new_content_sha256

        for root_change in root_changes:
            self._roots[
                root_change.node_id
            ] = (
                root_change
                .new_root_sha256
            )

        result = PropagationResult(
            schema=(
                PROPAGATION_RESULT_SCHEMA
            ),
            leaf_node_id=change.node_id,
            old_content_sha256=(
                change.old_content_sha256
            ),
            new_content_sha256=(
                change.new_content_sha256
            ),
            changed=True,
            affected_parent_ids=order,
            root_changes=tuple(
                root_changes
            ),
            dependency_changes=tuple(
                dependency_changes
            ),
            focus_invalidations=tuple(
                invalidations
            ),
        )

        result.validate()

        return result
