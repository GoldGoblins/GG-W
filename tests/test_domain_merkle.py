from __future__ import annotations

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
import domain_merkle as M  # noqa: E402


def h(
    value: str,
) -> str:
    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def source_component(
    *,
    second: str = "b-v1",
) -> M.DomainMerkleRoot:
    return M.build_domain_root(
        "SOURCE",
        "component/editor",
        (
            M.leaf(
                "file/a.qml",
                h("a-v1"),
            ),
            M.leaf(
                "file/b.qml",
                h(second),
            ),
        ),
    )


def generic_root(
    *,
    value: str = "generic-v1",
) -> M.DomainMerkleRoot:
    return M.build_domain_root(
        "GENERIC_KNOWLEDGE",
        "capability-concepts",
        (
            M.leaf(
                "verification-kind",
                h(value),
            ),
        ),
    )


def machine_root(
    *,
    value: str = "machine-v1",
) -> M.DomainMerkleRoot:
    return M.build_domain_root(
        "MACHINE_KNOWLEDGE",
        "gg/project",
        (
            M.leaf(
                "capability-registry",
                h(value),
            ),
        ),
    )


def policy_root() -> M.DomainMerkleRoot:
    return M.build_domain_root(
        "POLICY",
        "gg",
        (
            M.leaf(
                "solver-router",
                h("policy-v1"),
            ),
        ),
    )


def source_focus(
    source: M.DomainMerkleRoot,
) -> F.FocusBinding:
    policy = policy_root()

    return F.FocusBinding(
        domain="source.task",
        focus_id="editor.qml",
        dependencies=(
            F.FocusDependency(
                namespace="source",
                root_sha256=(
                    source.root_sha256()
                ),
            ),
            F.FocusDependency(
                namespace="policy",
                root_sha256=(
                    policy.root_sha256()
                ),
            ),
        ),
        policy_revision_sha256=(
            policy.root_sha256()
        ),
        compiler_revision_sha256=h(
            "focus-compiler"
        ),
    )


def knowledge_focus(
    generic: M.DomainMerkleRoot,
    machine: M.DomainMerkleRoot,
) -> F.FocusBinding:
    policy = policy_root()

    return F.FocusBinding(
        domain="knowledge.specialization",
        focus_id="verification-kind",
        dependencies=(
            F.FocusDependency(
                namespace="knowledge.generic",
                root_sha256=(
                    generic.root_sha256()
                ),
            ),
            F.FocusDependency(
                namespace="knowledge.machine",
                root_sha256=(
                    machine.root_sha256()
                ),
            ),
            F.FocusDependency(
                namespace="policy",
                root_sha256=(
                    policy.root_sha256()
                ),
            ),
        ),
        policy_revision_sha256=(
            policy.root_sha256()
        ),
        compiler_revision_sha256=h(
            "focus-compiler"
        ),
    )


class DomainMerkleTests(
    unittest.TestCase
):
    def test_child_order_is_canonical(
        self,
    ) -> None:
        first = M.build_domain_root(
            "SOURCE",
            "x",
            (
                M.leaf("a", h("1")),
                M.leaf("b", h("2")),
            ),
        )

        second = M.build_domain_root(
            "SOURCE",
            "x",
            (
                M.leaf("b", h("2")),
                M.leaf("a", h("1")),
            ),
        )

        self.assertEqual(
            first.root_sha256(),
            second.root_sha256(),
        )

    def test_duplicate_namespace_fails_closed(
        self,
    ) -> None:
        root = M.DomainMerkleRoot(
            domain="SOURCE",
            scope="x",
            children=(
                M.leaf("same", h("1")),
                M.leaf("same", h("2")),
            ),
        )

        with self.assertRaisesRegex(
            M.DomainMerkleError,
            "MERKLE_CHILD_NAMESPACE_DUPLICATE",
        ):
            root.validate()

    def test_malformed_hash_fails_closed(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            M.DomainMerkleError,
            "MERKLE_CHILD_ROOT_SHA256_INVALID",
        ):
            M.leaf(
                "bad",
                "not-a-hash",
            )

    def test_leaf_change_changes_component_root(
        self,
    ) -> None:
        self.assertNotEqual(
            source_component(
                second="b-v1"
            ).root_sha256(),
            source_component(
                second="b-v2"
            ).root_sha256(),
        )

    def test_unchanged_sibling_root_is_reusable(
        self,
    ) -> None:
        sibling = M.build_domain_root(
            "SOURCE",
            "component/other",
            (
                M.leaf(
                    "file/c.qml",
                    h("c-v1"),
                ),
            ),
        )

        before = sibling.root_sha256()
        after = sibling.root_sha256()

        self.assertEqual(
            before,
            after,
        )

    def test_subtree_change_changes_parent_source_root(
        self,
    ) -> None:
        sibling = M.build_domain_root(
            "SOURCE",
            "component/other",
            (
                M.leaf(
                    "file/c.qml",
                    h("c-v1"),
                ),
            ),
        )

        first = M.build_domain_root(
            "SOURCE",
            "project",
            (
                M.subtree(
                    "editor",
                    source_component(
                        second="b-v1"
                    ),
                ),
                M.subtree(
                    "other",
                    sibling,
                ),
            ),
        )

        second = M.build_domain_root(
            "SOURCE",
            "project",
            (
                M.subtree(
                    "editor",
                    source_component(
                        second="b-v2"
                    ),
                ),
                M.subtree(
                    "other",
                    sibling,
                ),
            ),
        )

        self.assertNotEqual(
            first.root_sha256(),
            second.root_sha256(),
        )

    def test_unrelated_generic_change_does_not_invalidate_source_focus(
        self,
    ) -> None:
        source = source_component()

        before = source_focus(
            source
        ).binding_sha256()

        _ = generic_root(
            value="generic-v2"
        )

        after = source_focus(
            source
        ).binding_sha256()

        self.assertEqual(
            before,
            after,
        )

    def test_relevant_source_change_invalidates_source_focus(
        self,
    ) -> None:
        self.assertNotEqual(
            source_focus(
                source_component(
                    second="b-v1"
                )
            ).binding_sha256(),
            source_focus(
                source_component(
                    second="b-v2"
                )
            ).binding_sha256(),
        )

    def test_unrelated_source_change_does_not_invalidate_knowledge_focus(
        self,
    ) -> None:
        generic = generic_root()
        machine = machine_root()

        before = knowledge_focus(
            generic,
            machine,
        ).binding_sha256()

        _ = source_component(
            second="changed"
        )

        after = knowledge_focus(
            generic,
            machine,
        ).binding_sha256()

        self.assertEqual(
            before,
            after,
        )

    def test_relevant_machine_change_invalidates_knowledge_focus(
        self,
    ) -> None:
        generic = generic_root()

        self.assertNotEqual(
            knowledge_focus(
                generic,
                machine_root(
                    value="machine-v1"
                ),
            ).binding_sha256(),
            knowledge_focus(
                generic,
                machine_root(
                    value="machine-v2"
                ),
            ).binding_sha256(),
        )

    def test_global_root_changes_on_unrelated_domain_change(
        self,
    ) -> None:
        source = source_component()
        generic = generic_root()

        global_one = M.build_domain_root(
            "GLOBAL",
            "gg",
            (
                M.subtree(
                    "source",
                    source,
                ),
                M.subtree(
                    "generic",
                    generic,
                ),
                M.subtree(
                    "machine",
                    machine_root(
                        value="machine-v1"
                    ),
                ),
            ),
        )

        global_two = M.build_domain_root(
            "GLOBAL",
            "gg",
            (
                M.subtree(
                    "source",
                    source,
                ),
                M.subtree(
                    "generic",
                    generic,
                ),
                M.subtree(
                    "machine",
                    machine_root(
                        value="machine-v2"
                    ),
                ),
            ),
        )

        self.assertNotEqual(
            global_one.root_sha256(),
            global_two.root_sha256(),
        )

        self.assertEqual(
            source_focus(
                source
            ).binding_sha256(),
            source_focus(
                source
            ).binding_sha256(),
        )

    def test_same_children_different_domain_have_different_roots(
        self,
    ) -> None:
        children = (
            M.leaf(
                "x",
                h("same"),
            ),
        )

        self.assertNotEqual(
            M.build_domain_root(
                "SOURCE",
                "scope",
                children,
            ).root_sha256(),
            M.build_domain_root(
                "MACHINE_KNOWLEDGE",
                "scope",
                children,
            ).root_sha256(),
        )

    def test_subtree_binds_child_root(
        self,
    ) -> None:
        child = source_component()

        reference = M.subtree(
            "editor",
            child,
        )

        self.assertEqual(
            reference.kind,
            M.SUBTREE,
        )

        self.assertEqual(
            reference.root_sha256,
            child.root_sha256(),
        )

    def test_stale_relevant_root_is_focus_cache_miss(
        self,
    ) -> None:
        cache = F.CompiledFocusCache()

        current = knowledge_focus(
            generic_root(),
            machine_root(
                value="machine-v1"
            ),
        )

        handle = cache.compile_and_store(
            current,
            b"VERIFIER",
        )

        stale = knowledge_focus(
            generic_root(),
            machine_root(
                value="machine-v2"
            ),
        )

        self.assertIsNotNone(
            cache.lookup(
                handle.handle_id
            )
        )

        self.assertIsNone(
            cache.lookup(
                stale.binding_sha256()
            )
        )


if __name__ == "__main__":
    unittest.main()
