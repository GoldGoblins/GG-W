from __future__ import annotations

import hashlib
import importlib
from pathlib import Path
import sys
import unittest


PROJECT = (
    Path(__file__)
    .resolve()
    .parents[1]
)

BACKEND = (
    PROJECT
    / "backend"
)

if str(BACKEND) not in sys.path:
    sys.path.insert(
        0,
        str(BACKEND),
    )


Coordinator = importlib.import_module(
    "live_aid.post_draft_coordinator"
)


def sha(
    source: str,
) -> str:
    return hashlib.sha256(
        source.encode("utf-8")
    ).hexdigest()


def validation(
    source: str,
    *,
    status: str,
    fault_layer: str,
    diagnostics: list[dict] | None = None,
) -> dict:
    return {
        "schema":
            Coordinator.VALIDATION_SCHEMA,
        "source_sha256":
            sha(source),
        "status":
            status,
        "fault_layer":
            fault_layer,
        "diagnostics":
            diagnostics or [],
    }


def candidate(
    old_source: str,
    new_source: str,
    *,
    apply_authority: str = (
        "SYSTEM_AUTOMATIC_IN_MEMORY_ONLY"
    ),
) -> dict:
    return {
        "schema":
            Coordinator.CANDIDATE_SCHEMA,
        "source_sha256":
            sha(old_source),
        "candidate_source":
            new_source,
        "candidate_sha256":
            sha(new_source),
        "model_output_authority":
            "UNTRUSTED_MODEL_OUTPUT",
        "apply_authority":
            apply_authority,
        "persistent_write_authority":
            "NONE",
        "execution_authority":
            "NONE",
        "network_authority":
            "NONE",
    }


class PostDraftCoordinatorTests(
    unittest.TestCase
):
    def make(
        self,
        *,
        budget: int = 3,
    ):
        return (
            Coordinator
            .PostDraftCoordinator(
                object_id=
                    "ws.file.example",
                source_name=
                    "example.qml",
                language="qml",
                max_repair_attempts=
                    budget,
            )
        )

    def test_draft_updates_do_not_emit_repair(self):
        coordinator = self.make()

        first = coordinator.update_draft(
            "Item {\n"
        )

        second = coordinator.update_draft(
            "Item {\n}\n"
        )

        self.assertEqual(
            first.state,
            Coordinator.CoordinatorState.DRAFT,
        )

        self.assertEqual(
            second.state,
            Coordinator.CoordinatorState.DRAFT,
        )

        self.assertFalse(
            second.draft_complete
        )

        self.assertFalse(
            second.execution_ready
        )

        self.assertEqual(
            second.repair_attempts,
            0,
        )


    def test_draft_complete_starts_validation(self):
        coordinator = self.make()

        source = (
            "Item {\n"
            "    implicitHeight: ???\n"
            "}\n"
        )

        coordinator.update_draft(
            source
        )

        action = (
            coordinator
            .mark_draft_complete()
        )

        self.assertEqual(
            action.kind,
            Coordinator.ActionKind.VALIDATE,
        )

        self.assertEqual(
            action.source_sha256,
            sha(source),
        )

        self.assertEqual(
            coordinator.state,
            Coordinator.CoordinatorState.VERIFYING,
        )

        self.assertEqual(
            action.as_dict()[
                "execution_authority"
            ],
            "NONE",
        )


    def test_pass_becomes_verified_then_ready(self):
        coordinator = self.make()

        source = (
            "Item {\n"
            "    implicitHeight: 93\n"
            "}\n"
        )

        coordinator.update_draft(
            source
        )

        coordinator.mark_draft_complete()

        action = (
            coordinator
            .accept_validation(
                validation(
                    source,
                    status="PASS",
                    fault_layer="NONE",
                )
            )
        )

        self.assertEqual(
            action.kind,
            Coordinator.ActionKind.PROMOTE_READY,
        )

        self.assertEqual(
            coordinator.state,
            Coordinator.CoordinatorState.VERIFIED,
        )

        ready = (
            coordinator
            .promote_ready()
        )

        self.assertEqual(
            ready.state,
            Coordinator.CoordinatorState.READY_TO_RUN,
        )

        self.assertTrue(
            ready.execution_ready
        )

        self.assertEqual(
            ready.as_dict()[
                "persistent_write_authority"
            ],
            "NONE",
        )

        self.assertEqual(
            ready.as_dict()[
                "execution_authority"
            ],
            "NONE",
        )


    def test_source_fail_requests_repair_only_after_complete(self):
        coordinator = self.make()

        source = (
            "Item {\n"
            "    implicitHeight: ???\n"
            "}\n"
        )

        coordinator.update_draft(
            source
        )

        coordinator.mark_draft_complete()

        action = (
            coordinator
            .accept_validation(
                validation(
                    source,
                    status="FAIL",
                    fault_layer="SOURCE",
                    diagnostics=[
                        {
                            "status": "FAIL",
                            "line": 2,
                            "blocking": True,
                        }
                    ],
                )
            )
        )

        self.assertEqual(
            action.kind,
            Coordinator.ActionKind.REPAIR,
        )

        self.assertEqual(
            coordinator.state,
            Coordinator.CoordinatorState.REPAIRING,
        )

        self.assertEqual(
            action.repair_attempt,
            0,
        )


    def test_non_source_fail_never_requests_source_repair(self):
        for layer in (
            "TRANSPORT",
            "HARNESS",
            "SANDBOX",
            "TARGET",
            "REGRESSION",
        ):
            with self.subTest(
                layer=layer
            ):
                coordinator = self.make()

                source = (
                    "Item {\n}\n"
                )

                coordinator.update_draft(
                    source
                )

                coordinator.mark_draft_complete()

                action = (
                    coordinator
                    .accept_validation(
                        validation(
                            source,
                            status="FAIL",
                            fault_layer=layer,
                            diagnostics=[
                                {
                                    "status": "FAIL",
                                    "blocking": True,
                                }
                            ],
                        )
                    )
                )

                self.assertEqual(
                    action.kind,
                    Coordinator.ActionKind.NONE,
                )

                self.assertEqual(
                    coordinator.state,
                    Coordinator.CoordinatorState.BLOCKED,
                )


    def test_stale_validation_is_rejected(self):
        coordinator = self.make()

        source = (
            "Item {\n}\n"
        )

        coordinator.update_draft(
            source
        )

        coordinator.mark_draft_complete()

        stale = validation(
            source + "\n",
            status="PASS",
            fault_layer="NONE",
        )

        with self.assertRaises(
            Coordinator.CoordinatorError
        ):
            coordinator.accept_validation(
                stale
            )


    def test_stage_d_human_apply_authority_cannot_be_laundered(self):
        coordinator = self.make()

        old = (
            "Item {\n"
            "    implicitHeight: ???\n"
            "}\n"
        )

        new = (
            "Item {\n"
            "    implicitHeight: 48;\n"
            "}\n"
        )

        coordinator.update_draft(
            old
        )

        coordinator.mark_draft_complete()

        coordinator.accept_validation(
            validation(
                old,
                status="FAIL",
                fault_layer="SOURCE",
                diagnostics=[
                    {
                        "status": "FAIL",
                        "line": 2,
                        "blocking": True,
                    }
                ],
            )
        )

        proposal = candidate(
            old,
            new,
            apply_authority=
                "HUMAN_EXPLICIT_IN_MEMORY_ONLY",
        )

        with self.assertRaises(
            Coordinator.CoordinatorError
        ):
            coordinator.accept_repair_candidate(
                proposal
            )

        self.assertEqual(
            coordinator.state,
            Coordinator.CoordinatorState.REPAIRING,
        )

        self.assertEqual(
            coordinator.source,
            old,
        )


    def test_automatic_candidate_is_in_memory_then_revalidated(self):
        coordinator = self.make()

        old = (
            "Item {\n"
            "    implicitHeight: ???\n"
            "}\n"
        )

        new = (
            "Item {\n"
            "    implicitHeight: 48;\n"
            "}\n"
        )

        coordinator.update_draft(
            old
        )

        coordinator.mark_draft_complete()

        coordinator.accept_validation(
            validation(
                old,
                status="FAIL",
                fault_layer="SOURCE",
                diagnostics=[
                    {
                        "status": "FAIL",
                        "line": 2,
                        "blocking": True,
                    }
                ],
            )
        )

        action = (
            coordinator
            .accept_repair_candidate(
                candidate(
                    old,
                    new,
                )
            )
        )

        self.assertEqual(
            action.kind,
            Coordinator.ActionKind.VALIDATE,
        )

        self.assertEqual(
            coordinator.state,
            Coordinator.CoordinatorState.VERIFYING,
        )

        self.assertEqual(
            coordinator.source,
            new,
        )

        self.assertEqual(
            coordinator.snapshot().repair_attempts,
            1,
        )

        self.assertFalse(
            coordinator.snapshot().execution_ready
        )


    def test_ready_requires_revalidation_after_repair(self):
        coordinator = self.make()

        old = (
            "Item {\n"
            "    implicitHeight: ???\n"
            "}\n"
        )

        new = (
            "Item {\n"
            "    implicitHeight: 48;\n"
            "}\n"
        )

        coordinator.update_draft(
            old
        )

        coordinator.mark_draft_complete()

        coordinator.accept_validation(
            validation(
                old,
                status="FAIL",
                fault_layer="SOURCE",
                diagnostics=[
                    {
                        "status": "FAIL",
                        "blocking": True,
                    }
                ],
            )
        )

        coordinator.accept_repair_candidate(
            candidate(
                old,
                new,
            )
        )

        self.assertFalse(
            coordinator.snapshot().execution_ready
        )

        promote = (
            coordinator
            .accept_validation(
                validation(
                    new,
                    status="PASS",
                    fault_layer="NONE",
                )
            )
        )

        self.assertEqual(
            promote.kind,
            Coordinator.ActionKind.PROMOTE_READY,
        )

        ready = (
            coordinator
            .promote_ready()
        )

        self.assertTrue(
            ready.execution_ready
        )


    def test_repair_budget_is_bounded(self):
        coordinator = self.make(
            budget=1
        )

        first = "x = ???\n"
        second = "x = 1 + ???\n"

        coordinator.update_draft(
            first
        )

        coordinator.mark_draft_complete()

        coordinator.accept_validation(
            validation(
                first,
                status="FAIL",
                fault_layer="SOURCE",
                diagnostics=[
                    {
                        "status": "FAIL",
                        "blocking": True,
                    }
                ],
            )
        )

        coordinator.accept_repair_candidate(
            candidate(
                first,
                second,
            )
        )

        action = (
            coordinator
            .accept_validation(
                validation(
                    second,
                    status="FAIL",
                    fault_layer="SOURCE",
                    diagnostics=[
                        {
                            "status": "FAIL",
                            "blocking": True,
                        }
                    ],
                )
            )
        )

        self.assertEqual(
            action.kind,
            Coordinator.ActionKind.NONE,
        )

        self.assertEqual(
            coordinator.state,
            Coordinator.CoordinatorState.BLOCKED,
        )

        self.assertEqual(
            coordinator.snapshot().blocked_reason,
            "REPAIR_BUDGET_EXHAUSTED",
        )


    def test_noop_candidate_is_rejected(self):
        coordinator = self.make()

        source = (
            "x = ???\n"
        )

        coordinator.update_draft(
            source
        )

        coordinator.mark_draft_complete()

        coordinator.accept_validation(
            validation(
                source,
                status="FAIL",
                fault_layer="SOURCE",
                diagnostics=[
                    {
                        "status": "FAIL",
                        "blocking": True,
                    }
                ],
            )
        )

        with self.assertRaises(
            Coordinator.CoordinatorError
        ):
            coordinator.accept_repair_candidate(
                candidate(
                    source,
                    source,
                )
            )


    def test_draft_cannot_mutate_after_draft_complete(self):
        coordinator = self.make()

        coordinator.update_draft(
            "x = 1\n"
        )

        coordinator.mark_draft_complete()

        with self.assertRaises(
            Coordinator.CoordinatorError
        ):
            coordinator.update_draft(
                "x = 2\n"
            )


if __name__ == "__main__":
    unittest.main()
