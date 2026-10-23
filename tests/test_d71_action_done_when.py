from __future__ import annotations

import copy
from pathlib import Path

from backend import action_done_when
from backend import semantic_closure


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64
SHA_9 = "9" * 64


def expect(
    condition: bool,
    message: str,
) -> None:
    if not condition:
        raise AssertionError(message)


def fixture() -> dict[str, object]:
    intent = {
        "task_id": "task-d71",
        "origin_id": "origin-d71",
        "state_base_revision": SHA_A,
        "goal_chain_sha256": SHA_B,
        "action_trace_sha256": SHA_C,
        "capability_human_id": "safe-tool.read",
        "binding_sha256": SHA_E,
        "target_object_id": "ws.file.context-composer",
        "target_source_revision": SHA_D,
    }

    evaluation_context = {
        "source_envelope": {
            "schema": "gg.cognitive-task-envelope.v1",
            "task_id": "task-d71",
            "origin_id": "origin-d71",
            "state": "READY_FOR_CONTROL",
            "original_expression": (
                "Read the current ContextComposer source."
            ),
            "current_interpretation": (
                "Deterministic source-bound action."
            ),
            "ready_core": {
                "owner": "GG",
                "goal": (
                    "Read the exact verified target source."
                ),
                "expected_value": (
                    "A provenance-bound read result."
                ),
                "scope": ["verified local workspace source"],
                "forbidden_scope": ["network", "host write"],
                "risk_class": "YELLOW",
                "stop_conditions": ["source identity drift"],
                "expected_artifacts": ["tracked read result"],
                "acceptance_criteria": [
                    "ORIGINAL_INTENT preserved",
                    (
                        "verified source identity remains "
                        "provenance-bound"
                    ),
                ],
            },
        },
        "state_base": {
            "state_base_revision": SHA_A,
            "source_binding": {
                "goal_chain_sha256": SHA_B,
                "action_trace_sha256": SHA_C,
            },
        },
        "goal_chain": {
            "schema": "fixture-goal-chain",
        },
        "hypothesis_state": {
            "schema": "fixture-hypothesis",
        },
        "ledger_records": [],
        "memory_records": [],
    }

    receipt = {
        "schema": "gg.action-execution-result.v1",
        "result": "ACTION_EXECUTED",
        "reason_code": "EXECUTION_ELIGIBLE",
        "action_executed": True,
        "actual_effect_verified": True,
        "network": "NONE",
        "sudo": "NO",
        "model_inference": False,
    }

    observation = {
        "schema": "gg.action-effect-observation.v1",
        "result": "MATCH",
        "reason_code": "EXPECTED_ACTUAL_MATCH",
        "actual_effect_verified": True,
        "d70_required": False,
        "mismatch_reasons": [],
        "target_object_id": "ws.file.context-composer",
        "target_source_path": (
            "qml/components/ContextComposer.qml"
        ),
        "expected_target_source_revision": SHA_D,
        "observed_target_source_revision": SHA_D,
        "output_sha256": SHA_F,
        "backend": "IN_PROCESS_TRACKED_READ",
        "observed_effect_class": "READ_ONLY_TOOL_EXECUTION",
        "observed_persistent_write_authority": "RUNTIME_ONLY",
        "observed_network_authority": "NONE",
    }

    recovery = {
        "schema": "gg.action-effect-recovery.v1",
        "result": "NO_RECOVERY_REQUIRED",
        "reason_code": "ACTUAL_EFFECT_VERIFIED",
        "observation_reason_code": "EXPECTED_ACTUAL_MATCH",
        "mismatch_reasons": [],
        "target_object_id": "ws.file.context-composer",
        "target_source_revision": SHA_D,
        "replan_required": False,
        "authority_reevaluation_required": False,
        "repair_execution": False,
        "automatic_rerun": False,
        "existing_mandate_reusable": False,
        "new_action_authority_granted": False,
        "action_authority": "NONE",
        "general_action_authority": "NONE",
        "execution_persistent_write_authority": "NONE",
        "network": "NONE",
        "sudo": "NO",
        "model_inference": False,
    }

    return {
        "action_intent": intent,
        "evaluation_context": evaluation_context,
        "execution_receipt": receipt,
        "actual_effect_observation": observation,
        "action_effect_recovery": recovery,
    }


def evaluate(
    data: dict[str, object],
    *,
    semantic_evidence: (
        semantic_closure.SemanticEvidence
        | None
    ) = None,
) -> dict[str, object]:
    return action_done_when.evaluate_action_done_when(
        action_intent=copy.deepcopy(
            data["action_intent"]
        ),
        evaluation_context=copy.deepcopy(
            data["evaluation_context"]
        ),
        execution_receipt=copy.deepcopy(
            data["execution_receipt"]
        ),
        actual_effect_observation=copy.deepcopy(
            data["actual_effect_observation"]
        ),
        action_effect_recovery=copy.deepcopy(
            data["action_effect_recovery"]
        ),
        semantic_evidence=semantic_evidence,
    )


def expect_runtime_error(
    data: dict[str, object],
    expected: str,
) -> None:
    try:
        evaluate(data)
    except RuntimeError as exc:
        expect(
            expected in str(exc),
            (
                "unexpected RuntimeError: "
                + str(exc)
            ),
        )
        return

    raise AssertionError(
        "expected RuntimeError: "
        + expected
    )


def test_machine_pass_needs_semantic_evidence() -> None:
    data = fixture()

    result = evaluate(data)

    expect(
        result["machine_status"] == "PASS",
        "machine status should PASS",
    )
    expect(
        result["machine_effect_verified"] is True,
        "machine effect should verify",
    )
    expect(
        result["semantic_status"] == "EVIDENCE_REQUIRED",
        "semantic evidence must be required",
    )
    expect(
        result["semantic_done"] is False,
        "machine PASS must not imply semantic DONE",
    )
    expect(
        result["semantic_evidence_supplied"] is False,
        "production-equivalent path supplies no semantic evidence",
    )

    second = evaluate(data)

    expect(
        result["completion_contract_sha256"]
        == second["completion_contract_sha256"],
        "completion hash must be deterministic",
    )
    expect(
        result["semantic_request_sha256"]
        == second["semantic_request_sha256"],
        "semantic request hash must be deterministic",
    )

    print(
        "D71_MACHINE_PASS_EVIDENCE_REQUIRED=PASS"
    )


def test_explicit_trusted_semantic_evidence_can_close() -> None:
    data = fixture()
    initial = evaluate(data)

    evidence = semantic_closure.SemanticEvidence(
        request_sha256=str(
            initial["semantic_request_sha256"]
        ),
        source_sha256=str(
            initial["source_sha256"]
        ),
        semantic_contract_sha256=str(
            initial[
                "completion_contract_sha256"
            ]
        ),
        status="PASS",
        verifier_class="DETERMINISTIC_PREDICATE",
        verifier_id="d71-regression-verifier",
        proof_sha256=SHA_F,
        limitation="",
    )

    result = evaluate(
        data,
        semantic_evidence=evidence,
    )

    expect(
        result["semantic_status"] == "PASS",
        "trusted semantic evidence should PASS",
    )
    expect(
        result["semantic_done"] is True,
        "trusted semantic PASS should close DONE_WHEN",
    )

    print(
        "D71_TRUSTED_SEMANTIC_PASS=PASS"
    )


def test_ai_judgment_is_not_trusted_semantic_evidence() -> None:
    data = fixture()
    initial = evaluate(data)

    evidence = semantic_closure.SemanticEvidence(
        request_sha256=str(
            initial["semantic_request_sha256"]
        ),
        source_sha256=str(
            initial["source_sha256"]
        ),
        semantic_contract_sha256=str(
            initial[
                "completion_contract_sha256"
            ]
        ),
        status="PASS",
        verifier_class="AI_SEMANTIC_JUDGMENT",
        verifier_id="d71-untrusted-ai",
        proof_sha256=SHA_F,
        limitation="",
    )

    try:
        evaluate(
            data,
            semantic_evidence=evidence,
        )
    except semantic_closure.SemanticClosureError as exc:
        expect(
            "SEMANTIC_VERIFIER_CLASS_UNTRUSTED"
            in str(exc),
            "wrong AI evidence rejection",
        )
        print(
            "D71_AI_SEMANTIC_JUDGMENT_REJECTED=PASS"
        )
        return

    raise AssertionError(
        "AI semantic judgment unexpectedly trusted"
    )


def test_replan_blocks_semantic_closure() -> None:
    data = fixture()

    observation = data[
        "actual_effect_observation"
    ]
    assert isinstance(observation, dict)

    observation["result"] = "MISMATCH"
    observation["reason_code"] = (
        "OUTPUT_PROVENANCE_MISMATCH"
    )
    observation["actual_effect_verified"] = False
    observation["d70_required"] = True
    observation["mismatch_reasons"] = [
        "OUTPUT_PROVENANCE_MISMATCH"
    ]

    recovery = data[
        "action_effect_recovery"
    ]
    assert isinstance(recovery, dict)

    recovery["result"] = "REPLAN_REQUIRED"
    recovery["reason_code"] = (
        "ACTUAL_EFFECT_MISMATCH_REQUIRES_REPLAN"
    )
    recovery["observation_reason_code"] = (
        "OUTPUT_PROVENANCE_MISMATCH"
    )
    recovery["mismatch_reasons"] = [
        "OUTPUT_PROVENANCE_MISMATCH"
    ]
    recovery["replan_required"] = True
    recovery[
        "authority_reevaluation_required"
    ] = True

    result = evaluate(data)

    expect(
        result["machine_status"] == "BLOCKED",
        "replan should block machine readiness",
    )
    expect(
        result["semantic_status"] == "MACHINE_NOT_READY",
        "replan must produce MACHINE_NOT_READY",
    )
    expect(
        result["semantic_done"] is False,
        "replan must never be semantic DONE",
    )

    print(
        "D71_REPLAN_MACHINE_NOT_READY=PASS"
    )


def test_provenance_drift_fails_closed() -> None:
    data = fixture()
    intent = data["action_intent"]
    assert isinstance(intent, dict)
    intent["task_id"] = "task-drift"

    expect_runtime_error(
        data,
        "TASK_ID_BINDING_MISMATCH",
    )

    data = fixture()
    context = data["evaluation_context"]
    assert isinstance(context, dict)
    state = context["state_base"]
    assert isinstance(state, dict)
    state["state_base_revision"] = SHA_9

    expect_runtime_error(
        data,
        "STATE_BASE_REVISION_BINDING_MISMATCH",
    )

    data = fixture()
    context = data["evaluation_context"]
    assert isinstance(context, dict)
    state = context["state_base"]
    assert isinstance(state, dict)
    binding = state["source_binding"]
    assert isinstance(binding, dict)
    binding["goal_chain_sha256"] = SHA_9

    expect_runtime_error(
        data,
        "GOAL_CHAIN_BINDING_MISMATCH",
    )

    data = fixture()
    context = data["evaluation_context"]
    assert isinstance(context, dict)
    state = context["state_base"]
    assert isinstance(state, dict)
    binding = state["source_binding"]
    assert isinstance(binding, dict)
    binding["action_trace_sha256"] = SHA_9

    expect_runtime_error(
        data,
        "ACTION_TRACE_BINDING_MISMATCH",
    )

    data = fixture()
    observation = data[
        "actual_effect_observation"
    ]
    assert isinstance(observation, dict)
    observation[
        "observed_target_source_revision"
    ] = SHA_9

    expect_runtime_error(
        data,
        "TARGET_SOURCE_REVISION_MISMATCH",
    )

    print(
        "D71_PROVENANCE_DRIFT_FAILS_CLOSED=PASS"
    )


def static_contract() -> None:
    project = Path(__file__).resolve().parents[1]

    module_source = (
        project
        / "backend/action_done_when.py"
    ).read_text(
        encoding="utf-8",
        errors="strict",
    )

    adapter_source = (
        project
        / "backend/action_execution_safe_tool_adapter.py"
    ).read_text(
        encoding="utf-8",
        errors="strict",
    )

    for forbidden in (
        "subprocess",
        "QProcess",
        "repair_executor",
        "run_safe_tool",
        "model_runner",
    ):
        expect(
            forbidden not in module_source,
            (
                "D71 module contains forbidden execution surface: "
                + forbidden
            ),
        )

    expect(
        "semantic_closure"
        ".evaluate_semantic_closure"
        in module_source.replace(
            "\n",
            "",
        ).replace(
            " ",
            "",
        ),
        "D71 must call existing semantic closure",
    )

    expect(
        "semantic_evidence=None"
        in adapter_source.replace(
            " ",
            "",
        ).replace(
            "\n",
            "",
        ),
        (
            "production D71 call must not fabricate "
            "semantic evidence"
        ),
    )

    expect(
        'pending["action_done_when"]'
        in adapter_source,
        "D71 result must be stored on pending",
    )

    expect(
        'pending["status"] = "DONE"'
        not in adapter_source,
        "D71 must not own D72 DONE transition",
    )

    print(
        "D71_STATIC_NO_AUTHORITY_EXPANSION=PASS"
    )


def main() -> int:
    test_machine_pass_needs_semantic_evidence()
    test_explicit_trusted_semantic_evidence_can_close()
    test_ai_judgment_is_not_trusted_semantic_evidence()
    test_replan_blocks_semantic_closure()
    test_provenance_drift_fails_closed()
    static_contract()

    print(
        "D71_DONE_WHEN_REGRESSION=PASS"
    )
    print(
        "D71_REPAIR_EXECUTION=NONE"
    )
    print(
        "D71_AUTOMATIC_RERUN=NO"
    )
    print(
        "D71_NEW_ACTION_AUTHORITY=NONE"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
