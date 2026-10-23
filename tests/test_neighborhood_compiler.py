from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
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
import neighborhood_compiler as N  # noqa: E402


def h(
    value: str,
) -> str:
    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


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
        self.calls = 0

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

        self.calls += 1

        return self.records[
            :limit
        ]


def record(
    human_id: str,
    source_path: str,
    *,
    revision: str | None = None,
) -> Record:
    return Record(
        human_id=human_id,
        kind="ANALYZER",
        source_path=source_path,
        execution_revision_sha256=(
            revision
            if revision is not None
            else h(
                "exec:"
                + human_id
            )
        ),
        metadata_sha256=h(
            "meta:"
            + human_id
        ),
    )


def roots(
    *,
    machine: str = "machine-v1",
) -> tuple[
    F.FocusDependency,
    ...
]:
    return (
        F.FocusDependency(
            namespace="knowledge.generic",
            root_sha256=h(
                "generic-v1"
            ),
        ),
        F.FocusDependency(
            namespace="knowledge.machine",
            root_sha256=h(
                machine
            ),
        ),
        F.FocusDependency(
            namespace="policy",
            root_sha256=h(
                "policy-v1"
            ),
        ),
    )


def request(
    source_map: dict[
        str,
        str,
    ],
    *,
    relevant_roots: tuple[
        F.FocusDependency,
        ...
    ] | None = None,
    max_semantic_items: int = 8,
    max_source_items: int = 8,
) -> N.NeighborhoodRequest:
    if relevant_roots is None:
        relevant_roots = roots()

    return N.NeighborhoodRequest(
        query=(
            "knowledge specialization focus"
        ),
        task_identity_sha256=h(
            "task-v1"
        ),
        focus_domain=(
            "task.neighborhood"
        ),
        focus_id="task-1",
        source_identity_map=(
            source_map
        ),
        relevant_roots=(
            relevant_roots
        ),
        policy_revision_sha256=h(
            "policy-v1"
        ),
        focus_compiler_revision_sha256=h(
            "focus-compiler-v1"
        ),
        neighborhood_compiler_revision_sha256=h(
            "neighborhood-compiler-v1"
        ),
        semantic_depth=2,
        max_semantic_items=(
            max_semantic_items
        ),
        max_source_items=(
            max_source_items
        ),
    )


class NeighborhoodCompilerTests(
    unittest.TestCase
):
    def setUp(
        self,
    ) -> None:
        self.a = record(
            "cap.a",
            "project/a.py",
        )

        self.b = record(
            "cap.b",
            "project/b.py",
        )

        self.source_map = {
            "project/a.py":
                h("a-v1"),
            "project/b.py":
                h("b-v1"),
            "project/unrelated.py":
                h("unrelated-v1"),
        }

    def compile(
        self,
        records: tuple[
            Record,
            ...
        ] | None = None,
        *,
        source_map: dict[
            str,
            str,
        ] | None = None,
        relevant_roots: tuple[
            F.FocusDependency,
            ...
        ] | None = None,
    ) -> N.NeighborhoodCompilation:
        if records is None:
            records = (
                self.a,
                self.b,
            )

        if source_map is None:
            source_map = dict(
                self.source_map
            )

        return N.compile_neighborhood(
            request(
                source_map,
                relevant_roots=(
                    relevant_roots
                ),
            ),
            Registry(records),
        )

    def test_semantic_order_is_canonical(
        self,
    ) -> None:
        first = self.compile(
            (
                self.a,
                self.b,
            )
        )

        second = self.compile(
            (
                self.b,
                self.a,
            )
        )

        self.assertEqual(
            first.handle.handle_id,
            second.handle.handle_id,
        )

    def test_unrelated_source_change_does_not_invalidate(
        self,
    ) -> None:
        first = self.compile()

        changed = dict(
            self.source_map
        )

        changed[
            "project/unrelated.py"
        ] = h(
            "unrelated-v2"
        )

        second = self.compile(
            source_map=changed
        )

        self.assertEqual(
            first.handle.handle_id,
            second.handle.handle_id,
        )

    def test_relevant_source_change_invalidates(
        self,
    ) -> None:
        first = self.compile()

        changed = dict(
            self.source_map
        )

        changed[
            "project/a.py"
        ] = h(
            "a-v2"
        )

        second = self.compile(
            source_map=changed
        )

        self.assertNotEqual(
            first.handle.handle_id,
            second.handle.handle_id,
        )

    def test_relevant_capability_revision_invalidates(
        self,
    ) -> None:
        first = self.compile()

        changed = replace(
            self.a,
            execution_revision_sha256=h(
                "exec:a-v2"
            ),
        )

        second = self.compile(
            (
                changed,
                self.b,
            )
        )

        self.assertNotEqual(
            first.handle.handle_id,
            second.handle.handle_id,
        )

    def test_relevant_knowledge_root_invalidates(
        self,
    ) -> None:
        first = self.compile(
            relevant_roots=roots(
                machine="machine-v1"
            )
        )

        second = self.compile(
            relevant_roots=roots(
                machine="machine-v2"
            )
        )

        self.assertNotEqual(
            first.handle.handle_id,
            second.handle.handle_id,
        )

    def test_semantic_overflow_fails_closed(
        self,
    ) -> None:
        registry = Registry(
            (
                self.a,
                self.b,
            )
        )

        with self.assertRaisesRegex(
            N.NeighborhoodCompilerError,
            "SEMANTIC_NEIGHBORHOOD_OVERFLOW",
        ):
            N.compile_neighborhood(
                request(
                    self.source_map,
                    max_semantic_items=1,
                ),
                registry,
            )

    def test_source_overflow_fails_closed(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            N.NeighborhoodCompilerError,
            "SOURCE_NEIGHBORHOOD_OVERFLOW",
        ):
            N.compile_neighborhood(
                request(
                    self.source_map,
                    max_source_items=1,
                ),
                Registry(
                    (
                        self.a,
                        self.b,
                    )
                ),
            )

    def test_missing_source_identity_fails_closed(
        self,
    ) -> None:
        incomplete = {
            "project/a.py":
                h("a-v1"),
        }

        with self.assertRaisesRegex(
            N.NeighborhoodCompilerError,
            "SOURCE_IDENTITY_MISSING",
        ):
            N.compile_neighborhood(
                request(
                    incomplete
                ),
                Registry(
                    (
                        self.a,
                        self.b,
                    )
                ),
            )

    def test_empty_semantic_neighborhood_fails_closed(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            N.NeighborhoodCompilerError,
            "SEMANTIC_NEIGHBORHOOD_EMPTY",
        ):
            N.compile_neighborhood(
                request(
                    self.source_map
                ),
                Registry(()),
            )

    def test_duplicate_relevant_root_namespace_fails_closed(
        self,
    ) -> None:
        duplicate = (
            F.FocusDependency(
                namespace="knowledge",
                root_sha256=h("one"),
            ),
            F.FocusDependency(
                namespace="knowledge",
                root_sha256=h("two"),
            ),
        )

        with self.assertRaisesRegex(
            N.NeighborhoodCompilerError,
            "RELEVANT_ROOT_NAMESPACE_DUPLICATE",
        ):
            request(
                self.source_map,
                relevant_roots=duplicate,
            ).validate()

    def test_reserved_relevant_root_namespace_fails_closed(
        self,
    ) -> None:
        reserved = (
            F.FocusDependency(
                namespace="source",
                root_sha256=h("one"),
            ),
        )

        with self.assertRaisesRegex(
            N.NeighborhoodCompilerError,
            "RELEVANT_ROOT_NAMESPACE_RESERVED",
        ):
            request(
                self.source_map,
                relevant_roots=reserved,
            ).validate()

    def test_payload_contains_only_selected_sources(
        self,
    ) -> None:
        result = self.compile()

        selected = {
            item.source_path
            for item in result.source_items
        }

        self.assertEqual(
            selected,
            {
                "project/a.py",
                "project/b.py",
            },
        )

        self.assertNotIn(
            b"unrelated.py",
            result.handle.payload_bytes,
        )

    def test_hot_cache_lookup_returns_same_handle(
        self,
    ) -> None:
        result = self.compile()

        cache = F.CompiledFocusCache()

        stored = cache.store(
            result.handle
        )

        self.assertIs(
            cache.lookup(
                result.handle.handle_id
            ),
            stored,
        )

    def test_compilation_grants_no_authority(
        self,
    ) -> None:
        result = self.compile()

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

    def test_cold_discovery_called_once(
        self,
    ) -> None:
        registry = Registry(
            (
                self.a,
                self.b,
            )
        )

        result = N.compile_neighborhood(
            request(
                self.source_map
            ),
            registry,
        )

        self.assertEqual(
            registry.calls,
            1,
        )

        cache = F.CompiledFocusCache()

        cache.store(
            result.handle
        )

        for _ in range(100):
            self.assertIsNotNone(
                cache.lookup(
                    result.handle.handle_id
                )
            )

        self.assertEqual(
            registry.calls,
            1,
        )


if __name__ == "__main__":
    unittest.main()
