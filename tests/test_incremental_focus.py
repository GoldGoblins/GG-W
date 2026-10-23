from __future__ import annotations

from dataclasses import dataclass
import hashlib
import inspect
import sys
import unittest
from pathlib import Path


PROJECT = Path(
    __file__
).resolve().parents[1]

BACKEND = PROJECT / "backend"

if str(BACKEND) not in sys.path:
    sys.path.insert(
        0,
        str(BACKEND),
    )

import compiled_focus as F  # noqa: E402
import incremental_focus as I  # noqa: E402
import neighborhood_compiler as N  # noqa: E402


def h(
    value: str,
) -> str:
    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def binding(
    name: str,
    *,
    namespace: str = "source",
    root: str | None = None,
    policy: str | None = None,
    compiler: str | None = None,
) -> F.FocusBinding:
    if root is None:
        root = h(
            "root:"
            + name
        )

    if policy is None:
        policy = h(
            "policy"
        )

    if compiler is None:
        compiler = h(
            "compiler"
        )

    return F.FocusBinding(
        domain="test.incremental",
        focus_id=name,
        dependencies=(
            F.FocusDependency(
                namespace=namespace,
                root_sha256=root,
            ),
        ),
        policy_revision_sha256=(
            policy
        ),
        compiler_revision_sha256=(
            compiler
        ),
    )


def compile_handle(
    value: F.FocusBinding,
) -> F.CompiledFocusHandle:
    return F.compile_focus(
        value,
        (
            "payload:"
            + value.focus_id
        ).encode("utf-8"),
    )


@dataclass(frozen=True)
class Record:
    human_id: str
    kind: str
    source_path: str
    execution_revision_sha256: str
    metadata_sha256: str


class Registry:
    def __init__(
        self,
        records: tuple[
            Record,
            ...
        ],
    ) -> None:
        self.records = records

    def active_working_set(
        self,
        query: str,
        *,
        limit: int,
        depth: int,
    ) -> tuple[
        Record,
        ...
    ]:
        del query
        del depth

        return self.records[
            :limit
        ]


class IncrementalFocusTests(
    unittest.TestCase
):
    def test_register_and_direct_lookup(
        self,
    ) -> None:
        value = binding("one")
        handle = compile_handle(value)

        index = I.IncrementalFocusIndex()

        stored = index.register(
            value,
            handle,
        )

        self.assertIs(
            index.lookup(
                handle.handle_id
            ),
            stored,
        )

        self.assertEqual(
            index.size,
            1,
        )

    def test_duplicate_registration_is_stable(
        self,
    ) -> None:
        value = binding("one")
        handle = compile_handle(value)

        index = I.IncrementalFocusIndex()

        first = index.register(
            value,
            handle,
        )

        second = index.register(
            value,
            handle,
        )

        self.assertIs(
            first,
            second,
        )

        self.assertEqual(
            index.size,
            1,
        )

    def test_binding_handle_mismatch_fails_closed(
        self,
    ) -> None:
        first = binding("one")
        second = binding("two")

        index = I.IncrementalFocusIndex()

        with self.assertRaisesRegex(
            I.IncrementalFocusError,
            "FOCUS_BINDING_HANDLE_MISMATCH",
        ):
            index.register(
                first,
                compile_handle(
                    second
                ),
            )

    def test_same_root_change_is_noop(
        self,
    ) -> None:
        value = binding("one")
        handle = compile_handle(value)

        index = I.IncrementalFocusIndex()

        index.register(
            value,
            handle,
        )

        root = (
            value.dependencies[0]
            .root_sha256
        )

        result = index.apply_change(
            I.DependencyChange(
                namespace="source",
                old_root_sha256=root,
                new_root_sha256=root,
            )
        )

        self.assertFalse(
            result.changed
        )

        self.assertEqual(
            result.invalidated_handle_ids,
            (),
        )

        self.assertIsNotNone(
            index.lookup(
                handle.handle_id
            )
        )

    def test_unrelated_change_keeps_handle_hot(
        self,
    ) -> None:
        value = binding("one")
        handle = compile_handle(value)

        index = I.IncrementalFocusIndex()

        index.register(
            value,
            handle,
        )

        result = index.apply_change(
            I.DependencyChange(
                namespace="source",
                old_root_sha256=h(
                    "unrelated-old"
                ),
                new_root_sha256=h(
                    "unrelated-new"
                ),
            )
        )

        self.assertEqual(
            result.invalidated_handle_ids,
            (),
        )

        self.assertIsNotNone(
            index.lookup(
                handle.handle_id
            )
        )

    def test_relevant_change_evicts_only_affected_handle(
        self,
    ) -> None:
        first = binding(
            "one",
            root=h("shared-one"),
        )

        second = binding(
            "two",
            root=h("other"),
        )

        first_handle = compile_handle(
            first
        )
        second_handle = compile_handle(
            second
        )

        index = I.IncrementalFocusIndex()

        index.register(
            first,
            first_handle,
        )
        index.register(
            second,
            second_handle,
        )

        result = index.apply_change(
            I.DependencyChange(
                namespace="source",
                old_root_sha256=h(
                    "shared-one"
                ),
                new_root_sha256=h(
                    "shared-two"
                ),
            )
        )

        self.assertEqual(
            result.invalidated_handle_ids,
            (
                first_handle.handle_id,
            ),
        )

        self.assertIsNone(
            index.lookup(
                first_handle.handle_id
            )
        )

        self.assertIsNotNone(
            index.lookup(
                second_handle.handle_id
            )
        )

    def test_shared_dependency_invalidates_multiple_handles(
        self,
    ) -> None:
        shared = h(
            "shared"
        )

        first = binding(
            "one",
            root=shared,
        )

        second = binding(
            "two",
            root=shared,
        )

        first_handle = compile_handle(
            first
        )
        second_handle = compile_handle(
            second
        )

        index = I.IncrementalFocusIndex()

        index.register(
            first,
            first_handle,
        )
        index.register(
            second,
            second_handle,
        )

        result = index.apply_change(
            I.DependencyChange(
                namespace="source",
                old_root_sha256=shared,
                new_root_sha256=h(
                    "shared-next"
                ),
            )
        )

        self.assertEqual(
            set(
                result
                .invalidated_handle_ids
            ),
            {
                first_handle.handle_id,
                second_handle.handle_id,
            },
        )

        self.assertEqual(
            index.size,
            0,
        )

    def test_namespace_is_part_of_reverse_key(
        self,
    ) -> None:
        shared = h(
            "same-root"
        )

        value = binding(
            "one",
            namespace="source",
            root=shared,
        )

        handle = compile_handle(
            value
        )

        index = I.IncrementalFocusIndex()

        index.register(
            value,
            handle,
        )

        result = index.apply_change(
            I.DependencyChange(
                namespace="knowledge.machine",
                old_root_sha256=shared,
                new_root_sha256=h(
                    "new"
                ),
            )
        )

        self.assertEqual(
            result.invalidated_handle_ids,
            (),
        )

        self.assertIsNotNone(
            index.lookup(
                handle.handle_id
            )
        )

    def test_manual_discard_cleans_reverse_index(
        self,
    ) -> None:
        value = binding("one")
        handle = compile_handle(value)
        root = (
            value.dependencies[0]
            .root_sha256
        )

        index = I.IncrementalFocusIndex()

        index.register(
            value,
            handle,
        )

        self.assertTrue(
            index.discard(
                handle.handle_id
            )
        )

        result = index.apply_change(
            I.DependencyChange(
                namespace="source",
                old_root_sha256=root,
                new_root_sha256=h(
                    "next"
                ),
            )
        )

        self.assertEqual(
            result.invalidated_handle_ids,
            (),
        )

    def test_capacity_eviction_cleans_reverse_index(
        self,
    ) -> None:
        first = binding("one")
        second = binding("two")
        third = binding("three")

        first_handle = compile_handle(
            first
        )

        index = I.IncrementalFocusIndex(
            max_entries=2
        )

        index.register(
            first,
            first_handle,
        )

        index.register(
            second,
            compile_handle(second),
        )

        index.register(
            third,
            compile_handle(third),
        )

        self.assertIsNone(
            index.lookup(
                first_handle.handle_id
            )
        )

        result = index.apply_change(
            I.DependencyChange(
                namespace="source",
                old_root_sha256=(
                    first.dependencies[0]
                    .root_sha256
                ),
                new_root_sha256=h(
                    "changed"
                ),
            )
        )

        self.assertEqual(
            result.invalidated_handle_ids,
            (),
        )

        self.assertEqual(
            index.size,
            2,
        )

    def test_policy_revision_is_reverse_indexed(
        self,
    ) -> None:
        policy = h(
            "policy-v1"
        )

        value = binding(
            "one",
            policy=policy,
        )

        handle = compile_handle(value)

        index = I.IncrementalFocusIndex()

        index.register(
            value,
            handle,
        )

        result = index.apply_change(
            I.DependencyChange(
                namespace=(
                    I.POLICY_DEPENDENCY_NAMESPACE
                ),
                old_root_sha256=policy,
                new_root_sha256=h(
                    "policy-v2"
                ),
            )
        )

        self.assertEqual(
            result.invalidated_handle_ids,
            (
                handle.handle_id,
            ),
        )

    def test_compiler_revision_is_reverse_indexed(
        self,
    ) -> None:
        compiler = h(
            "compiler-v1"
        )

        value = binding(
            "one",
            compiler=compiler,
        )

        handle = compile_handle(value)

        index = I.IncrementalFocusIndex()

        index.register(
            value,
            handle,
        )

        result = index.apply_change(
            I.DependencyChange(
                namespace=(
                    I.COMPILER_DEPENDENCY_NAMESPACE
                ),
                old_root_sha256=compiler,
                new_root_sha256=h(
                    "compiler-v2"
                ),
            )
        )

        self.assertEqual(
            result.invalidated_handle_ids,
            (
                handle.handle_id,
            ),
        )

    def test_malformed_change_fails_closed(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            I.IncrementalFocusError,
            "CHANGE_OLD_ROOT_SHA256_INVALID",
        ):
            I.DependencyChange(
                namespace="source",
                old_root_sha256="bad",
                new_root_sha256=h(
                    "next"
                ),
            ).validate()

    def test_neighborhood_compilation_preserves_exact_binding(
        self,
    ) -> None:
        item = Record(
            human_id="cap.one",
            kind="ANALYZER",
            source_path="project/one.py",
            execution_revision_sha256=h(
                "exec"
            ),
            metadata_sha256=h(
                "meta"
            ),
        )

        request = N.NeighborhoodRequest(
            query="one",
            task_identity_sha256=h(
                "task"
            ),
            focus_domain="test.neighborhood",
            focus_id="one",
            source_identity_map={
                "project/one.py":
                    h("source"),
            },
            relevant_roots=(
                F.FocusDependency(
                    namespace="knowledge.machine",
                    root_sha256=h(
                        "machine"
                    ),
                ),
            ),
            policy_revision_sha256=h(
                "policy"
            ),
            focus_compiler_revision_sha256=h(
                "focus-compiler"
            ),
            neighborhood_compiler_revision_sha256=h(
                "neighborhood-compiler"
            ),
            semantic_depth=1,
            max_semantic_items=4,
            max_source_items=4,
        )

        result = N.compile_neighborhood(
            request,
            Registry(
                (
                    item,
                )
            ),
        )

        self.assertEqual(
            result.binding.binding_sha256(),
            result.handle.binding_sha256,
        )

        index = I.IncrementalFocusIndex()

        index.register(
            result.binding,
            result.handle,
        )

        self.assertIsNotNone(
            index.lookup(
                result.handle.handle_id
            )
        )

    def test_hot_lookup_source_does_not_touch_reverse_index(
        self,
    ) -> None:
        source = inspect.getsource(
            I.IncrementalFocusIndex.lookup
        )

        self.assertNotIn(
            "_reverse",
            source,
        )

        self.assertNotIn(
            "_bindings",
            source,
        )

        self.assertNotIn(
            "sorted(",
            source,
        )

        self.assertNotIn(
            "for ",
            source,
        )

        self.assertIn(
            "_cache.lookup",
            source,
        )

    def test_invalidation_grants_no_authority(
        self,
    ) -> None:
        value = binding("one")
        handle = compile_handle(value)

        index = I.IncrementalFocusIndex()

        index.register(
            value,
            handle,
        )

        result = index.apply_change(
            I.DependencyChange(
                namespace="source",
                old_root_sha256=(
                    value.dependencies[0]
                    .root_sha256
                ),
                new_root_sha256=h(
                    "next"
                ),
            )
        )

        self.assertEqual(
            result.action_authority,
            "NONE",
        )

        self.assertEqual(
            result.promotion_authority,
            "NONE",
        )

        self.assertEqual(
            result.persistent_write,
            "NONE",
        )

        self.assertFalse(
            result.model_inference
        )

        self.assertFalse(
            result.registered_capability_execution
        )


if __name__ == "__main__":
    unittest.main()
