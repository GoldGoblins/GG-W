from __future__ import annotations

import hashlib
import importlib
from pathlib import Path
import sys
import unittest
from unittest import mock


PROJECT = (
    Path(__file__)
    .resolve()
    .parents[1]
)

if str(PROJECT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT),
    )


Executor = importlib.import_module(
    "backend.live_aid.post_draft_qml_executor"
)

Preflight = importlib.import_module(
    "backend.live_aid.qml_preflight_runner"
)

Repair = importlib.import_module(
    "backend.live_aid.repair_model_runner"
)


BROKEN = (
    "import QtQuick\n"
    "Item {\n"
    "    implicitHeight: ???\n"
    "}\n"
)

FIXED = (
    "import QtQuick\n"
    "Item {\n"
    "    implicitHeight: 48;\n"
    "}\n"
)


def sha(
    source: str,
) -> str:
    return hashlib.sha256(
        source.encode("utf-8")
    ).hexdigest()


def preflight_response(
    request: dict,
    *,
    passed: bool,
) -> dict:
    if passed:
        report = {
            "schema":
                "gg-code-gate-report-v1",
            "status": "PASS",
            "source": {
                "sha256":
                    request[
                        "source_sha256"
                    ],
            },
            "qml": {
                "success": True,
                "diagnostics": [],
            },
        }

        return (
            Preflight
            .build_response_from_gate_report(
                request,
                report,
                gate_report_path=
                    "/synthetic/pass-report.json",
                gate_report_sha256=
                    "b" * 64,
                wrapper_return_code=0,
            )
        )

    report = {
        "schema":
            "gg-code-gate-report-v1",
        "status": "FAIL",
        "source": {
            "sha256":
                request[
                    "source_sha256"
                ],
        },
        "qml": {
            "success": False,
            "diagnostics": [
                {
                    "id":
                        "qml-syntax",
                    "message":
                        "Expected token `;'",
                    "line": 3,
                }
            ],
        },
    }

    return (
        Preflight
        .build_response_from_gate_report(
            request,
            report,
            gate_report_path=
                "/synthetic/fail-report.json",
            gate_report_sha256=
                "a" * 64,
            wrapper_return_code=1,
        )
    )


def repair_response(
    request: dict,
) -> dict:
    proposal = {
        "schema":
            Repair
            .semantic_transport
            .contract
            .SEMANTIC_PROPOSAL_SCHEMA,
        "hypothesis":
            "invalid expression",
        "old_text":
            "implicitHeight: ???",
        "new_text":
            "implicitHeight: 48;",
        "why":
            "use valid QML expression",
    }

    return (
        Repair.build_response(
            request,
            proposal,
            model_evidence_path=
                "/run/user/1000/"
                "synthetic-model-evidence",
            model_response_sha256=
                "f" * 64,
        )
    )


def make_executor(
    *,
    budget: int = 1,
):
    return (
        Executor
        .PostDraftQmlExecutor(
            object_id=
                "ws.file.context-composer",
            source_name=
                "ContextComposer.qml",
            source_relative_path=
                "qml/components/"
                "ContextComposer.qml",
            max_repair_attempts=
                budget,
            model_dispatch_budget=
                budget,
        )
    )


class PostDraftQmlExecutorTests(
    unittest.TestCase
):
    def test_pass_path_never_dispatches_model(self):
        executor = make_executor()

        def invoke(
            *,
            runner,
            prefix,
            request,
            fault_layer,
        ):
            self.assertEqual(
                runner,
                Executor
                .PREFLIGHT_RUNNER_PATH,
            )

            self.assertEqual(
                prefix,
                "gg-live-aid-preflight.",
            )

            self.assertEqual(
                fault_layer,
                "HARNESS",
            )

            return preflight_response(
                request,
                passed=True,
            )

        with mock.patch.object(
            executor,
            "_invoke_runner",
            side_effect=invoke,
        ):
            result = (
                executor
                .run_complete_draft(
                    FIXED
                )
            )

        self.assertTrue(
            result.execution_ready
        )

        self.assertEqual(
            result.state,
            "READY_TO_RUN",
        )

        self.assertEqual(
            result.model_dispatch_count,
            0,
        )


    def test_full_fail_repair_pass_is_automatic(self):
        executor = make_executor()

        calls = []

        def invoke(
            *,
            runner,
            prefix,
            request,
            fault_layer,
        ):
            calls.append(
                (
                    runner.name,
                    request["source"],
                    fault_layer,
                )
            )

            if (
                runner
                == Executor
                .REPAIR_RUNNER_PATH
            ):
                return repair_response(
                    request
                )

            return preflight_response(
                request,
                passed=(
                    request["source"]
                    == FIXED
                ),
            )

        with mock.patch.object(
            executor,
            "_invoke_runner",
            side_effect=invoke,
        ):
            result = (
                executor
                .run_complete_draft(
                    BROKEN
                )
            )

        self.assertTrue(
            result.execution_ready
        )

        self.assertEqual(
            result.state,
            "READY_TO_RUN",
        )

        self.assertEqual(
            result.source,
            FIXED,
        )

        self.assertEqual(
            result.model_dispatch_count,
            1,
        )

        self.assertEqual(
            result.repair_attempts,
            1,
        )

        self.assertEqual(
            [
                item[0]
                for item in calls
            ],
            [
                "qml_preflight_runner.py",
                "repair_model_runner.py",
                "qml_preflight_runner.py",
            ],
        )


    def test_model_evidence_path_is_preserved(self):
        executor = make_executor()

        def invoke(
            *,
            runner,
            prefix,
            request,
            fault_layer,
        ):
            if (
                runner
                == Executor
                .REPAIR_RUNNER_PATH
            ):
                return repair_response(
                    request
                )

            return preflight_response(
                request,
                passed=(
                    request["source"]
                    == FIXED
                ),
            )

        with mock.patch.object(
            executor,
            "_invoke_runner",
            side_effect=invoke,
        ):
            result = (
                executor
                .run_complete_draft(
                    BROKEN
                )
            )

        self.assertEqual(
            result.model_evidence_paths,
            (
                "/run/user/1000/"
                "synthetic-model-evidence",
            ),
        )


    def test_events_are_truthful_states_not_fake_percent(self):
        events = []

        executor = (
            Executor
            .PostDraftQmlExecutor(
                object_id=
                    "ws.file.context-composer",
                source_name=
                    "ContextComposer.qml",
                source_relative_path=
                    "qml/components/"
                    "ContextComposer.qml",
                max_repair_attempts=1,
                model_dispatch_budget=1,
                event_sink=
                    events.append,
            )
        )

        def invoke(
            *,
            runner,
            prefix,
            request,
            fault_layer,
        ):
            if (
                runner
                == Executor
                .REPAIR_RUNNER_PATH
            ):
                return repair_response(
                    request
                )

            return preflight_response(
                request,
                passed=(
                    request["source"]
                    == FIXED
                ),
            )

        with mock.patch.object(
            executor,
            "_invoke_runner",
            side_effect=invoke,
        ):
            executor.run_complete_draft(
                BROKEN
            )

        names = [
            event["event"]
            for event in events
        ]

        self.assertIn(
            "DRAFT_COMPLETE",
            names,
        )

        self.assertIn(
            "VERIFYING",
            names,
        )

        self.assertIn(
            "REPAIRING",
            names,
        )

        self.assertIn(
            "CANDIDATE_APPLIED_IN_MEMORY",
            names,
        )

        self.assertEqual(
            names[-1],
            "READY_TO_RUN",
        )

        for event in events:
            self.assertNotIn(
                "percent",
                event,
            )


    def test_budget_zero_blocks_before_model_dispatch(self):
        executor = (
            Executor
            .PostDraftQmlExecutor(
                object_id=
                    "ws.file.context-composer",
                source_name=
                    "ContextComposer.qml",
                source_relative_path=
                    "qml/components/"
                    "ContextComposer.qml",
                max_repair_attempts=1,
                model_dispatch_budget=0,
            )
        )

        def invoke(
            *,
            runner,
            prefix,
            request,
            fault_layer,
        ):
            self.assertEqual(
                runner,
                Executor
                .PREFLIGHT_RUNNER_PATH,
            )

            return preflight_response(
                request,
                passed=False,
            )

        with (
            mock.patch.object(
                executor,
                "_invoke_runner",
                side_effect=invoke,
            ),
            self.assertRaises(
                Executor.ExecutorError
            ),
        ):
            executor.run_complete_draft(
                BROKEN
            )

        snapshot = (
            executor.driver.snapshot()
        )

        self.assertEqual(
            snapshot.state.value,
            "BLOCKED",
        )

        self.assertEqual(
            snapshot.blocked_fault_layer,
            "TRANSPORT",
        )

        self.assertEqual(
            snapshot.blocked_reason,
            "MODEL_DISPATCH_BUDGET_EXHAUSTED",
        )


    def test_default_qml_deterministic_gate_is_not_applicable_before_model(
        self,
    ):
        executor = make_executor()
        calls = []

        def invoke(
            *,
            runner,
            prefix,
            request,
            fault_layer,
        ):
            calls.append(
                runner.name
            )

            if (
                runner
                == Executor
                .REPAIR_RUNNER_PATH
            ):
                return repair_response(
                    request
                )

            return preflight_response(
                request,
                passed=(
                    request["source"]
                    == FIXED
                ),
            )

        with mock.patch.object(
            executor,
            "_invoke_runner",
            side_effect=invoke,
        ):
            result = (
                executor
                .run_complete_draft(
                    BROKEN
                )
            )

        self.assertEqual(
            result.model_dispatch_count,
            1,
        )

        repairing = [
            event
            for event in result.events
            if event["event"]
            == "REPAIRING"
        ]

        self.assertEqual(
            len(repairing),
            1,
        )

        self.assertEqual(
            repairing[0][
                "deterministic_outcome"
            ],
            "NOT_APPLICABLE",
        )

        self.assertEqual(
            repairing[0][
                "deterministic_reason"
            ],
            (
                "QML_PREFLIGHT_HAS_NO_EXACT_"
                "MACHINE_SAFE_EDIT"
            ),
        )

        self.assertTrue(
            repairing[0][
                "model_fallback_required"
            ]
        )

        self.assertEqual(
            calls,
            [
                "qml_preflight_runner.py",
                "repair_model_runner.py",
                "qml_preflight_runner.py",
            ],
        )

    def test_closed_deterministic_outcome_forbids_model_dispatch(
        self,
    ):
        executor = (
            Executor
            .PostDraftQmlExecutor(
                object_id=
                    "ws.file.context-composer",
                source_name=
                    "ContextComposer.qml",
                source_relative_path=
                    "qml/components/"
                    "ContextComposer.qml",
                max_repair_attempts=1,
                model_dispatch_budget=1,
                deterministic_fallback_gate=(
                    lambda _command:
                        Executor
                        .DeterministicFallbackDecision(
                            outcome="CLOSED",
                            reason=(
                                "FIXTURE_DETERMINISTIC_"
                                "DONE_WHEN_PASS"
                            ),
                        )
                ),
            )
        )

        calls = []

        def invoke(
            *,
            runner,
            prefix,
            request,
            fault_layer,
        ):
            calls.append(
                runner.name
            )

            self.assertEqual(
                runner,
                Executor
                .PREFLIGHT_RUNNER_PATH,
            )

            return preflight_response(
                request,
                passed=False,
            )

        with (
            mock.patch.object(
                executor,
                "_invoke_runner",
                side_effect=invoke,
            ),
            self.assertRaisesRegex(
                Executor.ExecutorError,
                (
                    "MODEL_DISPATCH_FORBIDDEN_AFTER_"
                    "DETERMINISTIC_CLOSURE"
                ),
            ),
        ):
            executor.run_complete_draft(
                BROKEN
            )

        result = executor._result()

        self.assertEqual(
            result.model_dispatch_count,
            0,
        )

        self.assertEqual(
            calls,
            [
                "qml_preflight_runner.py",
            ],
        )

        self.assertEqual(
            result.state,
            "BLOCKED",
        )

        self.assertEqual(
            result.blocked_fault_layer,
            "HARNESS",
        )

        self.assertEqual(
            result.blocked_reason,
            (
                "MODEL_DISPATCH_FORBIDDEN_AFTER_"
                "DETERMINISTIC_CLOSURE"
            ),
        )

        self.assertFalse(
            any(
                event["event"]
                == "REPAIRING"
                for event
                in result.events
            )
        )

if __name__ == "__main__":
    unittest.main()
