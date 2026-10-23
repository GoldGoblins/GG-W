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
import incremental_focus as I  # noqa: E402
import merkle_propagation as P  # noqa: E402
import source_change_event as S  # noqa: E402


def h(
    value: str,
) -> str:
    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def binding(
    *,
    world: str = S.HOST_SOURCE,
) -> S.SourceLeafBinding:
    return S.SourceLeafBinding(
        world=world,
        stable_node_id=(
            "file:projects/gg-ai-desktop/"
            "qml/components/ContextComposer.qml"
        ),
        target_relative_path=(
            "qml/components/ContextComposer.qml"
        ),
    )


def receipt(
    *,
    before: str | None = None,
    post: str | None = None,
) -> dict[str, object]:
    old = (
        before
        if before is not None
        else h("before")
    )

    new = (
        post
        if post is not None
        else h("after")
    )

    return {
        "schema":
            S.WRITE_APPLY_RECEIPT_SCHEMA,
        "proposal_id":
            "proposal-test",
        "target_relative_path":
            (
                "qml/components/"
                "ContextComposer.qml"
            ),
        "before_sha256":
            old,
        "candidate_sha256":
            new,
        "post_sha256":
            new,
        "approval_command":
            (
                "/approve-write "
                "proposal-test "
                + new
            ),
        "effect_verified":
            True,
    }


def event_from(
    value: dict[str, object]
    | None = None,
    *,
    source_binding: S.SourceLeafBinding
    | None = None,
    producer: str = "producer-v1",
    state_base: str = "base-v1",
) -> S.VerifiedSourceChangeEvent:
    return S.verified_write_apply_event(
        (
            receipt()
            if value is None
            else value
        ),
        (
            binding()
            if source_binding is None
            else source_binding
        ),
        producer_id=(
            "write_runner._approve"
        ),
        producer_content_sha256=h(
            producer
        ),
        producer_contract_sha256=h(
            "write-contract-v1"
        ),
        state_base_revision=(
            state_base
        ),
    )


def source_dag(
    old_sha: str,
) -> tuple[
    P.ResidentMerklePropagationDAG,
    str,
]:
    leaf_id = (
        "file:projects/gg-ai-desktop/"
        "qml/components/ContextComposer.qml"
    )

    parent_id = (
        "source-neighborhood:test"
    )

    dag = P.ResidentMerklePropagationDAG(
        (
            P.LeafSpec(
                node_id=leaf_id,
                content_sha256=old_sha,
            ),
        ),
        (
            P.ParentSpec(
                node_id=parent_id,
                domain=(
                    "SOURCE_NEIGHBORHOOD"
                ),
                scope=(
                    "compiled-working-set"
                ),
                children=(
                    P.ChildRef(
                        namespace=(
                            "projects/gg-ai-desktop/"
                            "qml/components/"
                            "ContextComposer.qml"
                        ),
                        node_id=leaf_id,
                        kind="LEAF",
                    ),
                ),
                dependency_namespaces=(
                    "source",
                ),
            ),
        ),
    )

    return (
        dag,
        parent_id,
    )


class SourceChangeEventTests(
    unittest.TestCase
):
    def test_write_receipt_builds_host_source_event(
        self,
    ) -> None:
        event = event_from()

        self.assertEqual(
            event.world,
            S.HOST_SOURCE,
        )

        self.assertEqual(
            event.old_content_sha256,
            h("before"),
        )

        self.assertEqual(
            event.new_content_sha256,
            h("after"),
        )

        self.assertTrue(
            event.effect_verified
        )

    def test_receipt_fields_are_exact(
        self,
    ) -> None:
        value = receipt()
        value["extra"] = "forbidden"

        with self.assertRaisesRegex(
            S.SourceChangeEventError,
            "WRITE_RECEIPT_FIELDS_INVALID",
        ):
            event_from(value)

    def test_receipt_target_must_match_binding(
        self,
    ) -> None:
        wrong = S.SourceLeafBinding(
            world=S.HOST_SOURCE,
            stable_node_id="file:x.py",
            target_relative_path="x.py",
        )

        with self.assertRaisesRegex(
            S.SourceChangeEventError,
            "WRITE_RECEIPT_TARGET_MISMATCH",
        ):
            event_from(
                source_binding=wrong
            )

    def test_postimage_must_equal_candidate(
        self,
    ) -> None:
        value = receipt()
        value["candidate_sha256"] = h(
            "candidate"
        )

        with self.assertRaisesRegex(
            S.SourceChangeEventError,
            "WRITE_POSTIMAGE_NOT_CANDIDATE",
        ):
            event_from(value)

    def test_effect_verified_is_required(
        self,
    ) -> None:
        value = receipt()
        value["effect_verified"] = False

        with self.assertRaisesRegex(
            S.SourceChangeEventError,
            "WRITE_RECEIPT_EFFECT_NOT_VERIFIED",
        ):
            event_from(value)

    def test_host_write_receipt_cannot_claim_candidate_world(
        self,
    ) -> None:
        candidate_binding = binding(
            world=S.IN_MEMORY_CANDIDATE
        )

        with self.assertRaisesRegex(
            S.SourceChangeEventError,
            "WRITE_RECEIPT_WORLD_NOT_HOST_SOURCE",
        ):
            event_from(
                source_binding=(
                    candidate_binding
                )
            )

    def test_event_hash_binds_producer_identity(
        self,
    ) -> None:
        one = event_from(
            producer="producer-one"
        )

        two = event_from(
            producer="producer-two"
        )

        self.assertNotEqual(
            one.event_sha256(),
            two.event_sha256(),
        )

    def test_event_hash_binds_state_base(
        self,
    ) -> None:
        one = event_from(
            state_base="base-one"
        )

        two = event_from(
            state_base="base-two"
        )

        self.assertNotEqual(
            one.event_sha256(),
            two.event_sha256(),
        )

    def test_evidence_hash_binds_exact_receipt(
        self,
    ) -> None:
        value = receipt()
        event = event_from(value)

        self.assertEqual(
            event.evidence_sha256,
            S.digest_json(value),
        )

    def test_event_to_leaf_requires_exact_stable_binding(
        self,
    ) -> None:
        event = event_from()

        wrong = S.SourceLeafBinding(
            world=S.HOST_SOURCE,
            stable_node_id="file:wrong",
            target_relative_path=(
                event.target_relative_path
            ),
        )

        with self.assertRaisesRegex(
            S.SourceChangeEventError,
            "EVENT_NODE_BINDING_MISMATCH",
        ):
            S.event_to_leaf_change(
                event,
                wrong,
            )

    def test_verified_event_invalidates_bound_focus(
        self,
    ) -> None:
        event = event_from()

        dag, parent_id = source_dag(
            event.old_content_sha256
        )

        source_root = dag.current_root(
            parent_id
        )

        focus_binding = F.FocusBinding(
            domain="test",
            focus_id="affected",
            dependencies=(
                F.FocusDependency(
                    namespace="source",
                    root_sha256=(
                        source_root
                    ),
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
            focus_binding,
            b"affected",
        )

        index = I.IncrementalFocusIndex()

        index.register(
            focus_binding,
            handle,
        )

        result = (
            S.ingest_verified_host_source_change(
                event,
                binding(),
                dag,
                focus_index=index,
            )
        )

        self.assertIsNone(
            index.lookup(
                handle.handle_id
            )
        )

        self.assertEqual(
            result
            .propagation
            .dependency_changes[0]
            .namespace,
            "source",
        )

    def test_unrelated_focus_remains_resident(
        self,
    ) -> None:
        event = event_from()

        dag, parent_id = source_dag(
            event.old_content_sha256
        )

        affected_binding = F.FocusBinding(
            domain="test",
            focus_id="affected",
            dependencies=(
                F.FocusDependency(
                    namespace="source",
                    root_sha256=(
                        dag.current_root(
                            parent_id
                        )
                    ),
                ),
            ),
            policy_revision_sha256=h(
                "policy"
            ),
            compiler_revision_sha256=h(
                "compiler"
            ),
        )

        affected = F.compile_focus(
            affected_binding,
            b"affected",
        )

        unrelated_binding = F.FocusBinding(
            domain="test",
            focus_id="unrelated",
            dependencies=(
                F.FocusDependency(
                    namespace="source",
                    root_sha256=h(
                        "unrelated"
                    ),
                ),
            ),
            policy_revision_sha256=h(
                "policy"
            ),
            compiler_revision_sha256=h(
                "compiler"
            ),
        )

        unrelated = F.compile_focus(
            unrelated_binding,
            b"unrelated",
        )

        index = I.IncrementalFocusIndex()

        index.register(
            affected_binding,
            affected,
        )

        index.register(
            unrelated_binding,
            unrelated,
        )

        S.ingest_verified_host_source_change(
            event,
            binding(),
            dag,
            focus_index=index,
        )

        self.assertIsNone(
            index.lookup(
                affected.handle_id
            )
        )

        self.assertIs(
            index.lookup(
                unrelated.handle_id
            ),
            unrelated,
        )

    def test_resident_leaf_preimage_mismatch_fails_closed(
        self,
    ) -> None:
        event = event_from()

        dag, parent_id = source_dag(
            h("different-resident-state")
        )

        before_parent = (
            dag.current_root(
                parent_id
            )
        )

        with self.assertRaisesRegex(
            P.MerklePropagationError,
            "LEAF_PREIMAGE_MISMATCH",
        ):
            S.ingest_verified_host_source_change(
                event,
                binding(),
                dag,
            )

        self.assertEqual(
            dag.current_root(
                parent_id
            ),
            before_parent,
        )

    def test_malformed_producer_identity_fails_closed(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            S.SourceChangeEventError,
            "PRODUCER_CONTENT_SHA256_INVALID",
        ):
            S.verified_write_apply_event(
                receipt(),
                binding(),
                producer_id=(
                    "write_runner._approve"
                ),
                producer_content_sha256=(
                    "bad"
                ),
                producer_contract_sha256=h(
                    "contract"
                ),
                state_base_revision="base",
            )

    def test_event_and_ingestion_grant_no_authority(
        self,
    ) -> None:
        event = event_from()

        dag, _ = source_dag(
            event.old_content_sha256
        )

        result = (
            S.ingest_verified_host_source_change(
                event,
                binding(),
                dag,
            )
        )

        self.assertEqual(
            event.action_authority,
            "NONE",
        )

        self.assertEqual(
            event.promotion_authority,
            "NONE",
        )

        self.assertEqual(
            event.persistent_write_authority,
            "NONE",
        )

        self.assertEqual(
            result.action_authority,
            "NONE",
        )

        self.assertEqual(
            result.persistent_write,
            "NONE",
        )

        self.assertFalse(
            result.model_inference
        )

    def test_ingestion_path_has_no_discovery_or_io(
        self,
    ) -> None:
        source = inspect.getsource(
            S.ingest_verified_host_source_change
        )

        for forbidden in (
            "open(",
            "Path(",
            "rglob",
            "CapabilityRegistry",
            "SourceIndex",
            "model",
        ):
            self.assertNotIn(
                forbidden,
                source,
            )


if __name__ == "__main__":
    unittest.main()
