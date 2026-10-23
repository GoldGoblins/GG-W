from __future__ import annotations

import ast
import hashlib
import inspect
import sys
import tempfile
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
import resident_information_state as R  # noqa: E402
import source_change_event as S  # noqa: E402


def h(
    value: str,
) -> str:
    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def proposal(
    before: str,
    after: str,
    *,
    proposal_id: str = "proposal-test",
) -> dict[str, object]:
    return {
        "schema":
            R.PROPOSAL_SCHEMA,
        "proposal_id":
            proposal_id,
        "target_relative_path":
            "qml/components/ContextComposer.qml",
        "workspace_object_id":
            "ws.file.context-composer",
        "context_reference":
            "@current",
        "head":
            "a" * 40,
        "before_sha256":
            before,
        "candidate_sha256":
            after,
        "diff_sha256":
            h("diff"),
        "proposal_gate_report_sha256":
            h("gate"),
        "approval_command":
            (
                "/approve-write "
                + proposal_id
                + " "
                + after
            ),
        "reject_command":
            (
                "/reject-write "
                + proposal_id
                + " "
                + after
            ),
    }


def receipt(
    before: str,
    after: str,
    *,
    proposal_id: str = "proposal-test",
) -> dict[str, object]:
    return {
        "schema":
            S.WRITE_APPLY_RECEIPT_SCHEMA,
        "proposal_id":
            proposal_id,
        "target_relative_path":
            "qml/components/ContextComposer.qml",
        "before_sha256":
            before,
        "candidate_sha256":
            after,
        "post_sha256":
            after,
        "approval_command":
            (
                "/approve-write "
                + proposal_id
                + " "
                + after
            ),
        "effect_verified":
            True,
    }


def owner(
    initial: str,
) -> R.WorkbenchResidentInformationState:
    return R.WorkbenchResidentInformationState(
        source_binding=(
            S.SourceLeafBinding(
                world=S.HOST_SOURCE,
                stable_node_id=(
                    "file:projects/gg-ai-desktop/"
                    "qml/components/ContextComposer.qml"
                ),
                target_relative_path=(
                    "qml/components/ContextComposer.qml"
                ),
            )
        ),
        initial_content_sha256=initial,
        producer_id="write_runner._approve",
        producer_content_sha256=h(
            "writer"
        ),
        producer_contract_sha256=h(
            "contract"
        ),
        max_focus_entries=16,
    )


class ResidentInformationStateTests(
    unittest.TestCase
):
    def test_initial_state_is_ready(
        self,
    ) -> None:
        initial = h("before")
        state = owner(initial)

        snapshot = state.snapshot()

        self.assertEqual(
            snapshot.status,
            R.READY,
        )

        self.assertEqual(
            snapshot.current_content_sha256,
            initial,
        )

    def test_source_dependency_is_current_parent_root(
        self,
    ) -> None:
        state = owner(
            h("before")
        )

        dependency = (
            state.source_dependency()
        )

        self.assertEqual(
            dependency.namespace,
            "source",
        )

        self.assertEqual(
            dependency.root_sha256,
            state.current_source_root_sha256(),
        )

    def test_verified_write_advances_exact_leaf(
        self,
    ) -> None:
        before = h("before")
        after = h("after")
        state = owner(before)

        result = (
            state.ingest_verified_write_completion(
                receipt(before, after),
                proposal(before, after),
            )
        )

        self.assertTrue(
            result.propagation.changed
        )

        self.assertEqual(
            state.current_content_sha256(),
            after,
        )

        self.assertEqual(
            state.status,
            R.READY,
        )

    def test_verified_write_invalidates_bound_focus(
        self,
    ) -> None:
        before = h("before")
        after = h("after")
        state = owner(before)

        focus_binding = F.FocusBinding(
            domain="test",
            focus_id="affected",
            dependencies=(
                state.source_dependency(),
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

        state.register_focus(
            focus_binding,
            handle,
        )

        state.ingest_verified_write_completion(
            receipt(before, after),
            proposal(before, after),
        )

        self.assertIsNone(
            state.lookup_focus(
                handle.handle_id
            )
        )

    def test_unrelated_focus_remains_hot(
        self,
    ) -> None:
        before = h("before")
        after = h("after")
        state = owner(before)

        affected_binding = F.FocusBinding(
            domain="test",
            focus_id="affected",
            dependencies=(
                state.source_dependency(),
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
                        "unrelated-root"
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

        state.register_focus(
            affected_binding,
            affected,
        )

        state.register_focus(
            unrelated_binding,
            unrelated,
        )

        state.ingest_verified_write_completion(
            receipt(before, after),
            proposal(before, after),
        )

        self.assertIsNone(
            state.lookup_focus(
                affected.handle_id
            )
        )

        self.assertIs(
            state.lookup_focus(
                unrelated.handle_id
            ),
            unrelated,
        )

    def test_resident_preimage_mismatch_blocks_state(
        self,
    ) -> None:
        state = owner(
            h("resident")
        )

        with self.assertRaisesRegex(
            R.ResidentInformationStateError,
            "VERIFIED_HOST_EFFECT_RESIDENT_SYNC_FAILED",
        ):
            state.ingest_verified_write_completion(
                receipt(
                    h("different"),
                    h("after"),
                ),
                proposal(
                    h("different"),
                    h("after"),
                ),
            )

        self.assertEqual(
            state.status,
            R.STALE_BLOCKED,
        )

        self.assertEqual(
            state.current_content_sha256(),
            h("resident"),
        )

    def test_blocked_state_never_returns_focus(
        self,
    ) -> None:
        state = owner(
            h("before")
        )

        focus_binding = F.FocusBinding(
            domain="test",
            focus_id="focus",
            dependencies=(
                state.source_dependency(),
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
            b"payload",
        )

        state.register_focus(
            focus_binding,
            handle,
        )

        state.block_after_verified_host_change(
            "verified external change"
        )

        self.assertIsNone(
            state.lookup_focus(
                handle.handle_id
            )
        )

    def test_blocked_state_rejects_new_registration(
        self,
    ) -> None:
        state = owner(
            h("before")
        )

        state.block_after_verified_host_change(
            "verified external change"
        )

        focus_binding = F.FocusBinding(
            domain="test",
            focus_id="focus",
            dependencies=(
                state.source_dependency(),
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
            b"payload",
        )

        with self.assertRaisesRegex(
            R.ResidentInformationStateError,
            "RESIDENT_INFORMATION_STATE_BLOCKED",
        ):
            state.register_focus(
                focus_binding,
                handle,
            )

    def test_proposal_must_bind_receipt(
        self,
    ) -> None:
        before = h("before")
        after = h("after")
        state = owner(before)

        bad = proposal(
            before,
            after,
        )

        bad[
            "candidate_sha256"
        ] = h("wrong")

        with self.assertRaisesRegex(
            R.ResidentInformationStateError,
            "VERIFIED_HOST_EFFECT_RESIDENT_SYNC_FAILED",
        ):
            state.ingest_verified_write_completion(
                receipt(
                    before,
                    after,
                ),
                bad,
            )

        self.assertEqual(
            state.status,
            R.STALE_BLOCKED,
        )

    def test_state_base_comes_from_bound_proposal(
        self,
    ) -> None:
        before = h("before")
        after = h("after")
        state = owner(before)

        value = proposal(
            before,
            after,
        )

        value["head"] = "b" * 40

        result = (
            state.ingest_verified_write_completion(
                receipt(before, after),
                value,
            )
        )

        self.assertTrue(
            result.propagation.changed
        )

    def test_bootstrap_reads_only_explicit_files(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project = root / "project"
            target = (
                project
                / "qml"
                / "components"
                / "ContextComposer.qml"
            )

            target.parent.mkdir(
                parents=True
            )

            target.write_text(
                "Item {}\n",
                encoding="utf-8",
            )

            producer = root / "writer.py"
            contract = root / "contract.py"

            producer.write_text(
                "writer\n",
                encoding="utf-8",
            )

            contract.write_text(
                "contract\n",
                encoding="utf-8",
            )

            state = (
                R.WorkbenchResidentInformationState.bootstrap_limited_write(
                    project_root=project,
                    target_relative_path=(
                        "qml/components/ContextComposer.qml"
                    ),
                    producer_id=(
                        "write_runner._approve"
                    ),
                    producer_path=producer,
                    producer_contract_path=(
                        contract
                    ),
                )
            )

            self.assertEqual(
                state.current_content_sha256(),
                hashlib.sha256(
                    b"Item {}\n"
                ).hexdigest(),
            )

    def test_change_path_has_no_filesystem_or_model_surface(
        self,
    ) -> None:
        source = inspect.getsource(
            R.WorkbenchResidentInformationState
            .ingest_verified_write_completion
        )

        for forbidden in (
            "read_bytes",
            "read_text",
            "rglob",
            "glob(",
            "os.walk",
            "subprocess",
            "model",
        ):
            self.assertNotIn(
                forbidden,
                source,
            )

    def test_owner_has_no_write_or_execution_authority(
        self,
    ) -> None:
        snapshot = owner(
            h("before")
        ).snapshot()

        self.assertEqual(
            snapshot.action_authority,
            "NONE",
        )

        self.assertEqual(
            snapshot.promotion_authority,
            "NONE",
        )

        self.assertEqual(
            snapshot.persistent_write,
            "NONE",
        )

        self.assertFalse(
            snapshot.model_inference
        )

    def test_main_owns_one_application_lifetime_state(
        self,
    ) -> None:
        main = (
            PROJECT
            / "main.py"
        ).read_text(
            encoding="utf-8"
        )

        tree = ast.parse(
            main,
            filename=str(
                PROJECT
                / "main.py"
            ),
        )

        chat = next(
            node
            for node in tree.body
            if (
                isinstance(
                    node,
                    ast.ClassDef,
                )
                and node.name
                == "ChatBridge"
            )
        )

        init = next(
            node
            for node in chat.body
            if (
                isinstance(
                    node,
                    ast.FunctionDef,
                )
                and node.name
                == "__init__"
            )
        )

        segment = (
            ast.get_source_segment(
                main,
                init,
            )
            or ""
        )

        self.assertEqual(
            segment.count(
                "bootstrap_workbench_sources("
            ),
            1,
        )

        self.assertIn(
            "self._resident_information_state",
            segment,
        )

    def test_main_ingests_only_verified_approve_completion(
        self,
    ) -> None:
        main = (
            PROJECT
            / "main.py"
        ).read_text(
            encoding="utf-8"
        )

        tree = ast.parse(
            main,
            filename=str(
                PROJECT
                / "main.py"
            ),
        )

        chat = next(
            node
            for node in tree.body
            if (
                isinstance(
                    node,
                    ast.ClassDef,
                )
                and node.name
                == "ChatBridge"
            )
        )

        method = next(
            node
            for node in chat.body
            if (
                isinstance(
                    node,
                    ast.FunctionDef,
                )
                and node.name
                == "_write_finished"
            )
        )

        segment = (
            ast.get_source_segment(
                main,
                method,
            )
            or ""
        )

        self.assertIn(
            'action == write_contract.ACTION_APPROVE',
            segment,
        )

        self.assertIn(
            'status == "APPLIED_VERIFIED"',
            segment,
        )

        self.assertIn(
            "ingest_verified_write_completion(",
            segment,
        )

    def test_main_delivers_verified_effects_to_resident_owner(
        self,
    ) -> None:
        main = (
            PROJECT
            / "main.py"
        ).read_text(
            encoding="utf-8"
        )

        self.assertNotIn(
            "VERIFIED_ROLLBACK_REQUIRES_SOURCE_EVENT_ADAPTER",
            main,
        )

        self.assertIn(
            "bootstrap_workbench_sources(",
            main,
        )

        self.assertIn(
            "ingest_verified_write_rollback(",
            main,
        )

        self.assertIn(
            'evidence\n                    / "rollback.json"',
            main,
        )

        self.assertIn(
            "ingest_verified_control_apply(",
            main,
        )


    def test_snapshot_tracks_constant_space_event_identity(
        self,
    ) -> None:
        before = h("before")
        after = h("after")
        state = owner(before)

        state.ingest_verified_write_completion(
            receipt(before, after),
            proposal(before, after),
        )

        snapshot = state.snapshot()

        self.assertEqual(
            snapshot.event_count,
            1,
        )

        self.assertRegex(
            snapshot.last_event_sha256,
            r"^[0-9a-f]{64}$",
        )


if __name__ == "__main__":
    unittest.main()
