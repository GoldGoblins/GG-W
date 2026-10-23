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
import resident_information_state as R  # noqa: E402
import source_change_event as S  # noqa: E402


QML_TARGET = (
    "qml/components/ContextComposer.qml"
)

QML_NODE = (
    "file:projects/gg-ai-desktop/"
    + QML_TARGET
)

MAIN_TARGET = (
    "projects/gg-ai-desktop/main.py"
)

MAIN_NODE = (
    "file:"
    + MAIN_TARGET
)


def h(
    value: str,
) -> str:
    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def qml_binding() -> S.SourceLeafBinding:
    return S.SourceLeafBinding(
        world=S.HOST_SOURCE,
        stable_node_id=QML_NODE,
        target_relative_path=QML_TARGET,
    )


def main_registration(
    initial: str,
) -> R.ResidentSourceRegistration:
    return R.ResidentSourceRegistration(
        binding=S.SourceLeafBinding(
            world=S.HOST_SOURCE,
            stable_node_id=MAIN_NODE,
            target_relative_path=MAIN_TARGET,
        ),
        initial_content_sha256=initial,
        producer_id=(
            "control_plane_runner.execute"
        ),
        producer_content_sha256=h(
            "control-runner"
        ),
        producer_contract_sha256=h(
            "control-contract"
        ),
    )


def owner(
    qml_initial: str,
    main_initial: str,
) -> R.WorkbenchResidentInformationState:
    return R.WorkbenchResidentInformationState(
        source_binding=qml_binding(),
        initial_content_sha256=qml_initial,
        producer_id="write_runner._approve",
        producer_content_sha256=h(
            "write-runner"
        ),
        producer_contract_sha256=h(
            "write-contract"
        ),
        additional_sources=(
            main_registration(
                main_initial
            ),
        ),
        max_focus_entries=16,
    )


def rollback_proposal(
    *,
    before: str,
    candidate: str,
) -> dict[str, object]:
    return {
        "schema":
            "gg.workbench.write-proposal.v1",
        "proposal_id":
            "proposal-multisource",
        "target_relative_path":
            QML_TARGET,
        "workspace_object_id":
            "context-composer",
        "context_reference":
            "context-composer",
        "head":
            "a" * 40,
        "before_sha256":
            before,
        "candidate_sha256":
            candidate,
        "diff_sha256":
            h("diff"),
        "proposal_gate_report_sha256":
            h("gate"),
        "approval_command":
            (
                "/approve-write "
                "proposal-multisource "
                + candidate
            ),
        "reject_command":
            (
                "/reject-write "
                "proposal-multisource "
                + candidate
            ),
    }


def rollback_receipt(
    *,
    before: str,
) -> dict[str, object]:
    return {
        "schema":
            S.WRITE_ROLLBACK_RECEIPT_SCHEMA,
        "proposal_id":
            "proposal-multisource",
        "before_sha256":
            before,
        "restored_sha256":
            before,
        "rollback_command":
            (
                "/rollback-write "
                "proposal-multisource "
                + h("qml-candidate")
                + " "
                + before
            ),
        "effect_verified":
            True,
    }


def control_pair(
    *,
    before: str,
    after: str,
) -> tuple[
    dict[str, object],
    dict[str, object],
]:
    request = {
        "schema":
            "gg.workbench.control-apply-request.v1",
        "action":
            "APPLY_SELFDEV",
        "task_id":
            "task-multisource",
        "base_head":
            "b" * 40,
        "target_relative_path":
            MAIN_TARGET,
        "before_sha256":
            before,
        "candidate_sha256":
            after,
        "diff_sha256":
            h("control-diff"),
    }

    response = {
        "schema":
            "gg.workbench.control-apply-response.v1",
        "task_id":
            "task-multisource",
        "status":
            "APPLIED_VERIFIED",
        "base_head":
            "b" * 40,
        "before_sha256":
            before,
        "candidate_sha256":
            after,
        "host_after_sha256":
            after,
        "host_repo_changed":
            True,
        "output":
            "verified control apply",
    }

    return request, response


class ResidentMultiSourceTests(
    unittest.TestCase,
):
    def test_same_owner_contains_both_explicit_sources(
        self,
    ) -> None:
        state = owner(
            h("qml"),
            h("main"),
        )

        self.assertEqual(
            tuple(
                item.stable_node_id
                for item
                in state.source_bindings
            ),
            (
                QML_NODE,
                MAIN_NODE,
            ),
        )

        self.assertEqual(
            state.source_binding
            .stable_node_id,
            QML_NODE,
        )

        self.assertEqual(
            state.source_binding_for(
                MAIN_NODE
            ).target_relative_path,
            MAIN_TARGET,
        )

    def test_verified_rollback_is_candidate_to_restored_before(
        self,
    ) -> None:
        original = h(
            "qml-original"
        )

        candidate = h(
            "qml-candidate"
        )

        state = owner(
            candidate,
            h("main"),
        )

        proposal = rollback_proposal(
            before=original,
            candidate=candidate,
        )

        receipt = rollback_receipt(
            before=original,
        )

        event = (
            S.verified_write_rollback_event(
                receipt,
                proposal,
                qml_binding(),
                producer_id=(
                    "write_runner._rollback"
                ),
                producer_content_sha256=h(
                    "write-runner"
                ),
                producer_contract_sha256=h(
                    "write-contract"
                ),
                state_base_revision=(
                    "a" * 40
                ),
            )
        )

        self.assertEqual(
            event.old_content_sha256,
            candidate,
        )

        self.assertEqual(
            event.new_content_sha256,
            original,
        )

        result = (
            state
            .ingest_verified_write_rollback(
                receipt,
                proposal,
            )
        )

        self.assertTrue(
            result.propagation.changed
        )

        self.assertEqual(
            state.current_content_sha256(),
            original,
        )

        self.assertEqual(
            state.status,
            R.READY,
        )

    def test_verified_control_apply_advances_only_main_leaf(
        self,
    ) -> None:
        qml_initial = h("qml")
        main_before = h(
            "main-before"
        )
        main_after = h(
            "main-after"
        )

        state = owner(
            qml_initial,
            main_before,
        )

        request, response = (
            control_pair(
                before=main_before,
                after=main_after,
            )
        )

        event = (
            S.verified_control_apply_event(
                request,
                response,
                state.source_binding_for(
                    MAIN_NODE
                ),
                producer_id=(
                    "control_plane_runner.execute"
                ),
                producer_content_sha256=h(
                    "control-runner"
                ),
                producer_contract_sha256=h(
                    "control-contract"
                ),
                state_base_revision=(
                    "b" * 40
                ),
            )
        )

        self.assertEqual(
            event.old_content_sha256,
            main_before,
        )

        self.assertEqual(
            event.new_content_sha256,
            main_after,
        )

        state.ingest_verified_control_apply(
            request,
            response,
        )

        self.assertEqual(
            state.current_content_sha256_for(
                MAIN_NODE
            ),
            main_after,
        )

        self.assertEqual(
            state.current_content_sha256(),
            qml_initial,
        )

    def test_control_change_invalidates_only_main_focus(
        self,
    ) -> None:
        qml_initial = h("qml")
        main_before = h(
            "main-before"
        )
        main_after = h(
            "main-after"
        )

        state = owner(
            qml_initial,
            main_before,
        )

        qml_binding_value = F.FocusBinding(
            domain="multisource",
            focus_id="qml",
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

        main_binding_value = F.FocusBinding(
            domain="multisource",
            focus_id="main",
            dependencies=(
                state.source_dependency_for(
                    MAIN_NODE
                ),
            ),
            policy_revision_sha256=h(
                "policy"
            ),
            compiler_revision_sha256=h(
                "compiler"
            ),
        )

        qml_handle = F.compile_focus(
            qml_binding_value,
            b"qml",
        )

        main_handle = F.compile_focus(
            main_binding_value,
            b"main",
        )

        state.register_focus(
            qml_binding_value,
            qml_handle,
        )

        state.register_focus(
            main_binding_value,
            main_handle,
        )

        request, response = (
            control_pair(
                before=main_before,
                after=main_after,
            )
        )

        state.ingest_verified_control_apply(
            request,
            response,
        )

        self.assertIs(
            state.lookup_focus(
                qml_handle.handle_id
            ),
            qml_handle,
        )

        self.assertIsNone(
            state.lookup_focus(
                main_handle.handle_id
            )
        )

    def test_wrong_control_preimage_blocks_owner(
        self,
    ) -> None:
        state = owner(
            h("qml"),
            h("resident-main"),
        )

        request, response = (
            control_pair(
                before=h(
                    "different-main"
                ),
                after=h(
                    "new-main"
                ),
            )
        )

        with self.assertRaisesRegex(
            R.ResidentInformationStateError,
            "VERIFIED_HOST_EFFECT_RESIDENT_SYNC_FAILED",
        ):
            state.ingest_verified_control_apply(
                request,
                response,
            )

        self.assertEqual(
            state.status,
            R.STALE_BLOCKED,
        )

        self.assertIsNone(
            state.lookup_focus(
                "anything"
            )
        )

    def test_event_adapters_grant_no_authority(
        self,
    ) -> None:
        main_before = h(
            "main-before"
        )

        main_after = h(
            "main-after"
        )

        state = owner(
            h("qml"),
            main_before,
        )

        request, response = (
            control_pair(
                before=main_before,
                after=main_after,
            )
        )

        event = (
            S.verified_control_apply_event(
                request,
                response,
                state.source_binding_for(
                    MAIN_NODE
                ),
                producer_id=(
                    "control_plane_runner.execute"
                ),
                producer_content_sha256=h(
                    "control-runner"
                ),
                producer_contract_sha256=h(
                    "control-contract"
                ),
                state_base_revision=(
                    "b" * 40
                ),
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

        self.assertFalse(
            event.model_inference
        )


if __name__ == "__main__":
    unittest.main()
