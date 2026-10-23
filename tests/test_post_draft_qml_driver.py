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

BACKEND = (
    PROJECT
    / "backend"
)

if str(BACKEND) not in sys.path:
    sys.path.insert(
        0,
        str(BACKEND),
    )


Driver = importlib.import_module(
    "live_aid.post_draft_qml_driver"
)

Preflight = importlib.import_module(
    "live_aid.qml_preflight_runner"
)

Repair = importlib.import_module(
    "live_aid.repair_model_runner"
)


BROKEN = (
    "Item {\n"
    "    implicitHeight: ???\n"
    "}\n"
)

FIXED = (
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


class Ids:
    def __init__(self):
        self.value = 0

    def __call__(self) -> str:
        self.value += 1
        return f"{self.value:032x}"


def make_driver(
    *,
    budget: int = 3,
):
    return Driver.PostDraftQmlDriver(
        object_id=
            "ws.file.context-composer",
        source_name=
            "ContextComposer.qml",
        source_relative_path=
            "qml/components/ContextComposer.qml",
        max_repair_attempts=budget,
        id_factory=Ids(),
    )


def fail_preflight(
    request: dict,
) -> dict:
    return {
        "schema":
            getattr(
                Preflight,
                "RESPONSE_SCHEMA",
                "test-response",
            ),
        "request_id":
            request["request_id"],
        "object_id":
            request["object_id"],
        "source_sha256":
            request["source_sha256"],
        "status": "FAIL",
        "gate_status": "FAIL",
        "gate_report_sha256":
            "a" * 64,
        "diagnostics": [
            {
                "status": "FAIL",
                "code": "syntax",
                "message": "Expected token `;'",
                "line": 2,
                "blocking": True,
                "suggestion": "repair attested line",
            }
        ],
        "action_authority": "NONE",
        "execution_authority": "NONE",
        "network_authority": "NONE",
    }


def pass_preflight(
    request: dict,
) -> dict:
    return {
        "schema":
            getattr(
                Preflight,
                "RESPONSE_SCHEMA",
                "test-response",
            ),
        "request_id":
            request["request_id"],
        "object_id":
            request["object_id"],
        "source_sha256":
            request["source_sha256"],
        "status": "PASS",
        "gate_status": "PASS",
        "gate_report_sha256":
            "b" * 64,
        "diagnostics": [],
        "action_authority": "NONE",
        "execution_authority": "NONE",
        "network_authority": "NONE",
    }


def repair_response(
    request: dict,
) -> dict:
    return {
        "request_id":
            request["request_id"],
        "object_id":
            request["object_id"],
        "source_sha256":
            request["source_sha256"],
        "candidate_source":
            FIXED,
        "candidate_sha256":
            sha(FIXED),
        "model_output_authority":
            "UNTRUSTED_MODEL_OUTPUT",
        "apply_authority":
            "HUMAN_EXPLICIT_IN_MEMORY_ONLY",
        "persistent_write_authority":
            "NONE",
        "execution_authority":
            "NONE",
        "network_authority":
            "NONE",
        "preflight_required_after_apply":
            True,
    }


class PostDraftQmlDriverTests(
    unittest.TestCase
):
    def test_draft_is_observe_only(self):
        driver = make_driver()

        snap = driver.update_draft(
            BROKEN
        )

        self.assertEqual(
            snap.state,
            Driver.DriverState.DRAFT,
        )

        self.assertEqual(
            snap.pending_command_kind,
            "",
        )

        self.assertFalse(
            snap.execution_ready
        )


    def test_draft_complete_emits_real_preflight_contract(self):
        driver = make_driver()

        driver.update_draft(
            BROKEN
        )

        command = (
            driver.mark_draft_complete()
        )

        self.assertEqual(
            command.kind,
            Driver.DriverCommandKind.PREFLIGHT,
        )

        validated = (
            Preflight.validate_request(
                command.request
            )
        )

        self.assertEqual(
            validated["source"],
            BROKEN,
        )

        self.assertEqual(
            validated["source_sha256"],
            sha(BROKEN),
        )

        self.assertEqual(
            validated[
                "source_relative_path"
            ],
            "qml/components/ContextComposer.qml",
        )

        self.assertEqual(
            command.as_dict()[
                "execution_authority"
            ],
            "NONE",
        )


    def test_preflight_pass_reaches_ready_to_run(self):
        driver = make_driver()

        driver.update_draft(
            FIXED
        )

        command = (
            driver.mark_draft_complete()
        )

        result = pass_preflight(
            command.request
        )

        with mock.patch.object(
            Preflight,
            "validate_response",
            return_value=result,
        ) as validator:
            next_command = (
                driver
                .accept_preflight_response(
                    result
                )
            )

        self.assertIsNone(
            next_command
        )

        self.assertEqual(
            driver.state,
            Driver.DriverState.READY_TO_RUN,
        )

        self.assertTrue(
            driver.snapshot().execution_ready
        )

        validator.assert_called_once_with(
            result,
            expected_request_id=
                command.request[
                    "request_id"
                ],
            expected_object_id=
                "ws.file.context-composer",
            expected_source_sha256=
                sha(FIXED),
        )


    def test_source_fail_emits_real_repair_request_contract(self):
        driver = make_driver()

        driver.update_draft(
            BROKEN
        )

        preflight_command = (
            driver.mark_draft_complete()
        )

        response = fail_preflight(
            preflight_command.request
        )

        with mock.patch.object(
            Preflight,
            "validate_response",
            return_value=response,
        ):
            repair_command = (
                driver
                .accept_preflight_response(
                    response
                )
            )

        self.assertIsNotNone(
            repair_command
        )

        assert repair_command is not None

        self.assertEqual(
            repair_command.kind,
            Driver.DriverCommandKind.REPAIR,
        )

        validated = (
            Repair.validate_request(
                repair_command.request
            )
        )

        self.assertEqual(
            validated["source"],
            BROKEN,
        )

        self.assertEqual(
            validated[
                "preflight_report_sha256"
            ],
            "a" * 64,
        )

        self.assertEqual(
            len(
                validated[
                    "diagnostics"
                ]
            ),
            1,
        )


    def test_stage_d_proposal_gets_separate_system_authority(self):
        driver = make_driver()

        driver.update_draft(
            BROKEN
        )

        preflight_command = (
            driver.mark_draft_complete()
        )

        preflight_response = fail_preflight(
            preflight_command.request
        )

        with mock.patch.object(
            Preflight,
            "validate_response",
            return_value=
                preflight_response,
        ):
            repair_command = (
                driver
                .accept_preflight_response(
                    preflight_response
                )
            )

        assert repair_command is not None

        response = repair_response(
            repair_command.request
        )

        captured = {}

        original = (
            driver
            ._coordinator
            .accept_repair_candidate
        )

        def capture(
            value: dict,
        ):
            captured.update(
                value
            )
            return original(
                value
            )

        with (
            mock.patch.object(
                Repair,
                "validate_response",
                return_value=response,
            ),
            mock.patch.object(
                driver._coordinator,
                "accept_repair_candidate",
                side_effect=capture,
            ),
        ):
            next_command = (
                driver
                .accept_repair_response(
                    response
                )
            )

        self.assertEqual(
            next_command.kind,
            Driver.DriverCommandKind.PREFLIGHT,
        )

        self.assertEqual(
            captured[
                "model_output_authority"
            ],
            "UNTRUSTED_MODEL_OUTPUT",
        )

        self.assertEqual(
            captured[
                "apply_authority"
            ],
            "SYSTEM_AUTOMATIC_IN_MEMORY_ONLY",
        )

        provenance = captured[
            "authority_provenance"
        ]

        self.assertEqual(
            provenance[
                "model_proposal_apply_authority"
            ],
            "HUMAN_EXPLICIT_IN_MEMORY_ONLY",
        )

        self.assertEqual(
            provenance[
                "system_apply_scope"
            ],
            "PRIVATE_COORDINATOR_CANDIDATE_ONLY",
        )

        self.assertEqual(
            captured[
                "persistent_write_authority"
            ],
            "NONE",
        )

        self.assertEqual(
            captured[
                "execution_authority"
            ],
            "NONE",
        )


    def test_repair_candidate_requires_revalidation(self):
        driver = make_driver()

        driver.update_draft(
            BROKEN
        )

        first = driver.mark_draft_complete()

        failed = fail_preflight(
            first.request
        )

        with mock.patch.object(
            Preflight,
            "validate_response",
            return_value=failed,
        ):
            repair_command = (
                driver
                .accept_preflight_response(
                    failed
                )
            )

        assert repair_command is not None

        response = repair_response(
            repair_command.request
        )

        with mock.patch.object(
            Repair,
            "validate_response",
            return_value=response,
        ):
            second_preflight = (
                driver
                .accept_repair_response(
                    response
                )
            )

        self.assertEqual(
            driver.state,
            Driver.DriverState.VALIDATING,
        )

        self.assertFalse(
            driver.snapshot().execution_ready
        )

        self.assertEqual(
            driver.source,
            FIXED,
        )

        passed = pass_preflight(
            second_preflight.request
        )

        with mock.patch.object(
            Preflight,
            "validate_response",
            return_value=passed,
        ):
            driver.accept_preflight_response(
                passed
            )

        self.assertTrue(
            driver.snapshot().execution_ready
        )


    def test_model_human_authority_is_not_treated_as_system_authority(self):
        driver = make_driver()

        invalid = {
            "model_output_authority":
                "UNTRUSTED_MODEL_OUTPUT",
            "apply_authority":
                "SYSTEM_AUTOMATIC_IN_MEMORY_ONLY",
            "persistent_write_authority":
                "NONE",
            "execution_authority":
                "NONE",
            "network_authority":
                "NONE",
            "preflight_required_after_apply":
                True,
            "source_sha256":
                sha(BROKEN),
            "candidate_source":
                FIXED,
            "candidate_sha256":
                sha(FIXED),
        }

        with self.assertRaises(
            Driver.DriverError
        ):
            driver._stage_e_candidate(
                invalid
            )


    def test_external_harness_fault_blocks_without_source_mutation(self):
        driver = make_driver()

        driver.update_draft(
            BROKEN
        )

        driver.mark_draft_complete()

        before = driver.source

        snap = (
            driver.accept_external_fault(
                fault_layer="HARNESS",
                reason="runner did not start",
            )
        )

        self.assertEqual(
            snap.state,
            Driver.DriverState.BLOCKED,
        )

        self.assertEqual(
            snap.blocked_fault_layer,
            "HARNESS",
        )

        self.assertEqual(
            driver.source,
            before,
        )

        self.assertFalse(
            snap.execution_ready
        )


    def test_external_source_fault_is_rejected(self):
        driver = make_driver()

        driver.update_draft(
            BROKEN
        )

        driver.mark_draft_complete()

        with self.assertRaises(
            Driver.DriverError
        ):
            driver.accept_external_fault(
                fault_layer="SOURCE",
                reason="do not launder source diagnosis",
            )


    def test_relative_path_must_be_bound_to_qml_source(self):
        with self.assertRaises(
            Driver.DriverError
        ):
            Driver.PostDraftQmlDriver(
                object_id="x",
                source_name=
                    "ContextComposer.qml",
                source_relative_path=
                    "../ContextComposer.qml",
            )


    def test_driver_snapshot_never_grants_action_authority(self):
        driver = make_driver()

        driver.update_draft(
            BROKEN
        )

        value = (
            driver.snapshot().as_dict()
        )

        self.assertEqual(
            value[
                "persistent_write_authority"
            ],
            "NONE",
        )

        self.assertEqual(
            value[
                "execution_authority"
            ],
            "NONE",
        )

        self.assertEqual(
            value[
                "network_authority"
            ],
            "NONE",
        )


if __name__ == "__main__":
    unittest.main()
