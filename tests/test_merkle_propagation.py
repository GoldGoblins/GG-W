from __future__ import annotations

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
import domain_merkle as M  # noqa: E402
import incremental_focus as I  # noqa: E402
import merkle_propagation as P  # noqa: E402


def h(
    value: str,
) -> str:
    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def leaf(
    node_id: str,
    value: str,
) -> P.LeafSpec:
    return P.LeafSpec(
        node_id=node_id,
        content_sha256=h(
            value
        ),
    )


def child_leaf(
    namespace: str,
    node_id: str,
) -> P.ChildRef:
    return P.ChildRef(
        namespace=namespace,
        node_id=node_id,
        kind="LEAF",
    )


def child_parent(
    namespace: str,
    node_id: str,
) -> P.ChildRef:
    return P.ChildRef(
        namespace=namespace,
        node_id=node_id,
        kind="SUBTREE",
    )


def focus_for_root(
    root: str,
    *,
    focus_id: str,
) -> tuple[
    F.FocusBinding,
    F.CompiledFocusHandle,
]:
    binding = F.FocusBinding(
        domain="test.propagation",
        focus_id=focus_id,
        dependencies=(
            F.FocusDependency(
                namespace="source",
                root_sha256=root,
            ),
        ),
        policy_revision_sha256=h(
            "policy"
        ),
        compiler_revision_sha256=h(
            "compiler"
        ),
    )

    handle = F.compile_focus(
        binding,
        (
            "payload:"
            + focus_id
        ).encode("utf-8"),
    )

    return (
        binding,
        handle,
    )


class MerklePropagationTests(
    unittest.TestCase
):
    def test_initial_parent_root_matches_domain_merkle(
        self,
    ) -> None:
        a = leaf("a", "a-v1")
        b = leaf("b", "b-v1")

        parent = P.ParentSpec(
            node_id="component",
            domain="SOURCE",
            scope="component",
            children=(
                child_leaf(
                    "a.py",
                    "a",
                ),
                child_leaf(
                    "b.py",
                    "b",
                ),
            ),
        )

        dag = P.ResidentMerklePropagationDAG(
            (
                a,
                b,
            ),
            (
                parent,
            ),
        )

        expected = M.build_domain_root(
            "SOURCE",
            "component",
            (
                M.leaf(
                    "a.py",
                    a.content_sha256,
                ),
                M.leaf(
                    "b.py",
                    b.content_sha256,
                ),
            ),
        )

        self.assertEqual(
            dag.current_root(
                "component"
            ),
            expected.root_sha256(),
        )

    def test_leaf_change_updates_direct_parent(
        self,
    ) -> None:
        a = leaf("a", "a-v1")

        dag = P.ResidentMerklePropagationDAG(
            (
                a,
            ),
            (
                P.ParentSpec(
                    node_id="component",
                    domain="SOURCE",
                    scope="component",
                    children=(
                        child_leaf(
                            "a.py",
                            "a",
                        ),
                    ),
                ),
            ),
        )

        before = dag.current_root(
            "component"
        )

        result = dag.apply_leaf_change(
            P.LeafChange(
                node_id="a",
                old_content_sha256=(
                    a.content_sha256
                ),
                new_content_sha256=h(
                    "a-v2"
                ),
            )
        )

        self.assertNotEqual(
            before,
            dag.current_root(
                "component"
            ),
        )

        self.assertEqual(
            result.affected_parent_ids,
            (
                "component",
            ),
        )

    def test_preimage_mismatch_fails_closed(
        self,
    ) -> None:
        a = leaf("a", "a-v1")

        dag = P.ResidentMerklePropagationDAG(
            (
                a,
            ),
            (),
        )

        with self.assertRaisesRegex(
            P.MerklePropagationError,
            "LEAF_PREIMAGE_MISMATCH",
        ):
            dag.apply_leaf_change(
                P.LeafChange(
                    node_id="a",
                    old_content_sha256=h(
                        "wrong"
                    ),
                    new_content_sha256=h(
                        "a-v2"
                    ),
                )
            )

        self.assertEqual(
            dag.current_root("a"),
            a.content_sha256,
        )

    def test_equal_change_is_noop(
        self,
    ) -> None:
        a = leaf("a", "a-v1")

        dag = P.ResidentMerklePropagationDAG(
            (
                a,
            ),
            (),
        )

        result = dag.apply_leaf_change(
            P.LeafChange(
                node_id="a",
                old_content_sha256=(
                    a.content_sha256
                ),
                new_content_sha256=(
                    a.content_sha256
                ),
            )
        )

        self.assertFalse(
            result.changed
        )

        self.assertEqual(
            result.affected_parent_ids,
            (),
        )

    def test_unrelated_parent_root_stays_exact(
        self,
    ) -> None:
        a = leaf("a", "a-v1")
        b = leaf("b", "b-v1")

        dag = P.ResidentMerklePropagationDAG(
            (
                a,
                b,
            ),
            (
                P.ParentSpec(
                    node_id="pa",
                    domain="SOURCE",
                    scope="a",
                    children=(
                        child_leaf(
                            "a.py",
                            "a",
                        ),
                    ),
                ),
                P.ParentSpec(
                    node_id="pb",
                    domain="SOURCE",
                    scope="b",
                    children=(
                        child_leaf(
                            "b.py",
                            "b",
                        ),
                    ),
                ),
            ),
        )

        unrelated_before = (
            dag.current_root(
                "pb"
            )
        )

        result = dag.apply_leaf_change(
            P.LeafChange(
                node_id="a",
                old_content_sha256=(
                    a.content_sha256
                ),
                new_content_sha256=h(
                    "a-v2"
                ),
            )
        )

        self.assertEqual(
            result.affected_parent_ids,
            (
                "pa",
            ),
        )

        self.assertEqual(
            dag.current_root("pb"),
            unrelated_before,
        )

    def test_one_leaf_may_feed_two_parent_projections(
        self,
    ) -> None:
        a = leaf("a", "a-v1")

        dag = P.ResidentMerklePropagationDAG(
            (
                a,
            ),
            (
                P.ParentSpec(
                    node_id="component",
                    domain="SOURCE",
                    scope="component",
                    children=(
                        child_leaf(
                            "a.py",
                            "a",
                        ),
                    ),
                ),
                P.ParentSpec(
                    node_id="focus-source",
                    domain=(
                        "SOURCE_NEIGHBORHOOD"
                    ),
                    scope=(
                        "compiled-working-set"
                    ),
                    children=(
                        child_leaf(
                            "a.py",
                            "a",
                        ),
                    ),
                ),
            ),
        )

        result = dag.apply_leaf_change(
            P.LeafChange(
                node_id="a",
                old_content_sha256=(
                    a.content_sha256
                ),
                new_content_sha256=h(
                    "a-v2"
                ),
            )
        )

        self.assertEqual(
            set(
                result
                .affected_parent_ids
            ),
            {
                "component",
                "focus-source",
            },
        )

    def test_multilevel_parent_chain_propagates(
        self,
    ) -> None:
        a = leaf("a", "a-v1")

        dag = P.ResidentMerklePropagationDAG(
            (
                a,
            ),
            (
                P.ParentSpec(
                    node_id="component",
                    domain="SOURCE",
                    scope="component",
                    children=(
                        child_leaf(
                            "a.py",
                            "a",
                        ),
                    ),
                ),
                P.ParentSpec(
                    node_id="project",
                    domain="SOURCE",
                    scope="project",
                    children=(
                        child_parent(
                            "component",
                            "component",
                        ),
                    ),
                ),
            ),
        )

        project_before = (
            dag.current_root(
                "project"
            )
        )

        result = dag.apply_leaf_change(
            P.LeafChange(
                node_id="a",
                old_content_sha256=(
                    a.content_sha256
                ),
                new_content_sha256=h(
                    "a-v2"
                ),
            )
        )

        self.assertEqual(
            result.affected_parent_ids,
            (
                "component",
                "project",
            ),
        )

        self.assertNotEqual(
            dag.current_root(
                "project"
            ),
            project_before,
        )

    def test_diamond_ancestor_is_recomputed_once(
        self,
    ) -> None:
        a = leaf("a", "a-v1")

        dag = P.ResidentMerklePropagationDAG(
            (
                a,
            ),
            (
                P.ParentSpec(
                    node_id="left",
                    domain="SOURCE",
                    scope="left",
                    children=(
                        child_leaf(
                            "a.py",
                            "a",
                        ),
                    ),
                ),
                P.ParentSpec(
                    node_id="right",
                    domain="SOURCE",
                    scope="right",
                    children=(
                        child_leaf(
                            "a.py",
                            "a",
                        ),
                    ),
                ),
                P.ParentSpec(
                    node_id="top",
                    domain="SOURCE",
                    scope="top",
                    children=(
                        child_parent(
                            "left",
                            "left",
                        ),
                        child_parent(
                            "right",
                            "right",
                        ),
                    ),
                ),
            ),
        )

        result = dag.apply_leaf_change(
            P.LeafChange(
                node_id="a",
                old_content_sha256=(
                    a.content_sha256
                ),
                new_content_sha256=h(
                    "a-v2"
                ),
            )
        )

        self.assertEqual(
            result
            .affected_parent_ids
            .count("top"),
            1,
        )

        self.assertEqual(
            set(
                result
                .affected_parent_ids
            ),
            {
                "left",
                "right",
                "top",
            },
        )

    def test_focus_bridge_invalidates_bound_handle(
        self,
    ) -> None:
        a = leaf("a", "a-v1")

        dag = P.ResidentMerklePropagationDAG(
            (
                a,
            ),
            (
                P.ParentSpec(
                    node_id="source-root",
                    domain=(
                        "SOURCE_NEIGHBORHOOD"
                    ),
                    scope=(
                        "compiled-working-set"
                    ),
                    children=(
                        child_leaf(
                            "a.py",
                            "a",
                        ),
                    ),
                    dependency_namespaces=(
                        "source",
                    ),
                ),
            ),
        )

        root = dag.current_root(
            "source-root"
        )

        binding, handle = (
            focus_for_root(
                root,
                focus_id="bound",
            )
        )

        index = I.IncrementalFocusIndex()

        index.register(
            binding,
            handle,
        )

        result = dag.apply_leaf_change(
            P.LeafChange(
                node_id="a",
                old_content_sha256=(
                    a.content_sha256
                ),
                new_content_sha256=h(
                    "a-v2"
                ),
            ),
            focus_index=index,
        )

        self.assertIsNone(
            index.lookup(
                handle.handle_id
            )
        )

        self.assertEqual(
            len(
                result
                .dependency_changes
            ),
            1,
        )

        self.assertEqual(
            result
            .dependency_changes[0]
            .namespace,
            "source",
        )

        self.assertEqual(
            result
            .focus_invalidations[0]
            .invalidated_handle_ids,
            (
                handle.handle_id,
            ),
        )

    def test_unrelated_focus_remains_hot(
        self,
    ) -> None:
        a = leaf("a", "a-v1")

        dag = P.ResidentMerklePropagationDAG(
            (
                a,
            ),
            (
                P.ParentSpec(
                    node_id="source-root",
                    domain="SOURCE",
                    scope="source",
                    children=(
                        child_leaf(
                            "a.py",
                            "a",
                        ),
                    ),
                    dependency_namespaces=(
                        "source",
                    ),
                ),
            ),
        )

        affected_binding, affected_handle = (
            focus_for_root(
                dag.current_root(
                    "source-root"
                ),
                focus_id="affected",
            )
        )

        unrelated_binding, unrelated_handle = (
            focus_for_root(
                h(
                    "unrelated-source-root"
                ),
                focus_id="unrelated",
            )
        )

        index = I.IncrementalFocusIndex()

        index.register(
            affected_binding,
            affected_handle,
        )

        index.register(
            unrelated_binding,
            unrelated_handle,
        )

        dag.apply_leaf_change(
            P.LeafChange(
                node_id="a",
                old_content_sha256=(
                    a.content_sha256
                ),
                new_content_sha256=h(
                    "a-v2"
                ),
            ),
            focus_index=index,
        )

        self.assertIsNone(
            index.lookup(
                affected_handle.handle_id
            )
        )

        self.assertIs(
            index.lookup(
                unrelated_handle.handle_id
            ),
            unrelated_handle,
        )

    def test_unknown_leaf_fails_closed(
        self,
    ) -> None:
        dag = P.ResidentMerklePropagationDAG(
            (),
            (),
        )

        with self.assertRaisesRegex(
            P.MerklePropagationError,
            "CHANGE_LEAF_UNKNOWN",
        ):
            dag.apply_leaf_change(
                P.LeafChange(
                    node_id="missing",
                    old_content_sha256=h(
                        "old"
                    ),
                    new_content_sha256=h(
                        "new"
                    ),
                )
            )

    def test_parent_cycle_fails_closed(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            P.MerklePropagationError,
            "MERKLE_PARENT_CYCLE",
        ):
            P.ResidentMerklePropagationDAG(
                (),
                (
                    P.ParentSpec(
                        node_id="a",
                        domain="SOURCE",
                        scope="a",
                        children=(
                            child_parent(
                                "b",
                                "b",
                            ),
                        ),
                    ),
                    P.ParentSpec(
                        node_id="b",
                        domain="SOURCE",
                        scope="b",
                        children=(
                            child_parent(
                                "a",
                                "a",
                            ),
                        ),
                    ),
                ),
            )

    def test_child_kind_target_mismatch_fails_closed(
        self,
    ) -> None:
        a = leaf("a", "a-v1")

        with self.assertRaisesRegex(
            P.MerklePropagationError,
            "CHILD_KIND_TARGET_MISMATCH",
        ):
            P.ResidentMerklePropagationDAG(
                (
                    a,
                ),
                (
                    P.ParentSpec(
                        node_id="parent",
                        domain="SOURCE",
                        scope="parent",
                        children=(
                            P.ChildRef(
                                namespace="a",
                                node_id="a",
                                kind="SUBTREE",
                            ),
                        ),
                    ),
                ),
            )

    def test_parent_fanout_bound_fails_closed(
        self,
    ) -> None:
        a = leaf("a", "a-v1")

        parents = tuple(
            P.ParentSpec(
                node_id=(
                    "p"
                    + str(index)
                ),
                domain="SOURCE",
                scope=(
                    "p"
                    + str(index)
                ),
                children=(
                    child_leaf(
                        "a",
                        "a",
                    ),
                ),
            )
            for index in range(3)
        )

        with self.assertRaisesRegex(
            P.MerklePropagationError,
            "PARENT_FANOUT_LIMIT_EXCEEDED",
        ):
            P.ResidentMerklePropagationDAG(
                (
                    a,
                ),
                parents,
                max_parent_fanout=2,
            )

    def test_propagation_depth_bound_fails_before_mutation(
        self,
    ) -> None:
        a = leaf("a", "a-v1")

        dag = P.ResidentMerklePropagationDAG(
            (
                a,
            ),
            (
                P.ParentSpec(
                    node_id="one",
                    domain="SOURCE",
                    scope="one",
                    children=(
                        child_leaf(
                            "a",
                            "a",
                        ),
                    ),
                ),
                P.ParentSpec(
                    node_id="two",
                    domain="SOURCE",
                    scope="two",
                    children=(
                        child_parent(
                            "one",
                            "one",
                        ),
                    ),
                ),
            ),
            max_propagation_depth=1,
        )

        old_leaf = dag.current_root(
            "a"
        )

        old_one = dag.current_root(
            "one"
        )

        with self.assertRaisesRegex(
            P.MerklePropagationError,
            "PROPAGATION_DEPTH_LIMIT_EXCEEDED",
        ):
            dag.apply_leaf_change(
                P.LeafChange(
                    node_id="a",
                    old_content_sha256=(
                        a.content_sha256
                    ),
                    new_content_sha256=h(
                        "a-v2"
                    ),
                )
            )

        self.assertEqual(
            dag.current_root("a"),
            old_leaf,
        )

        self.assertEqual(
            dag.current_root("one"),
            old_one,
        )

    def test_affected_node_bound_fails_before_mutation(
        self,
    ) -> None:
        a = leaf("a", "a-v1")

        dag = P.ResidentMerklePropagationDAG(
            (
                a,
            ),
            (
                P.ParentSpec(
                    node_id="one",
                    domain="SOURCE",
                    scope="one",
                    children=(
                        child_leaf(
                            "a",
                            "a",
                        ),
                    ),
                ),
                P.ParentSpec(
                    node_id="two",
                    domain="SOURCE",
                    scope="two",
                    children=(
                        child_leaf(
                            "a",
                            "a",
                        ),
                    ),
                ),
            ),
            max_affected_nodes=1,
        )

        old_leaf = dag.current_root(
            "a"
        )

        with self.assertRaisesRegex(
            P.MerklePropagationError,
            "AFFECTED_NODE_LIMIT_EXCEEDED",
        ):
            dag.apply_leaf_change(
                P.LeafChange(
                    node_id="a",
                    old_content_sha256=(
                        a.content_sha256
                    ),
                    new_content_sha256=h(
                        "a-v2"
                    ),
                )
            )

        self.assertEqual(
            dag.current_root("a"),
            old_leaf,
        )

    def test_change_path_has_no_global_root_iteration(
        self,
    ) -> None:
        source = inspect.getsource(
            P.ResidentMerklePropagationDAG
            .apply_leaf_change
        )

        self.assertNotIn(
            "self._roots.items",
            source,
        )

        self.assertNotIn(
            "self._roots.values",
            source,
        )

        self.assertNotIn(
            "for node_id in self._roots",
            source,
        )

        self.assertNotIn(
            "for root in self._roots",
            source,
        )

    def test_stable_node_id_survives_root_change(
        self,
    ) -> None:
        a = leaf("file:a.py", "a-v1")

        dag = P.ResidentMerklePropagationDAG(
            (
                a,
            ),
            (),
        )

        dag.apply_leaf_change(
            P.LeafChange(
                node_id="file:a.py",
                old_content_sha256=(
                    a.content_sha256
                ),
                new_content_sha256=h(
                    "a-v2"
                ),
            )
        )

        self.assertEqual(
            dag.current_root(
                "file:a.py"
            ),
            h("a-v2"),
        )

    def test_propagation_result_grants_no_authority(
        self,
    ) -> None:
        a = leaf("a", "a-v1")

        dag = P.ResidentMerklePropagationDAG(
            (
                a,
            ),
            (),
        )

        result = dag.apply_leaf_change(
            P.LeafChange(
                node_id="a",
                old_content_sha256=(
                    a.content_sha256
                ),
                new_content_sha256=h(
                    "a-v2"
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
