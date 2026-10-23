"""D71 action DONE_WHEN projection onto existing semantic closure.

This module does not execute repair, rerun an action, grant authority, run a
tool, invoke a model, or decide visible acceptance. It binds the existing
task/action provenance and D68-D70 machine evidence to the pre-existing
semantic_closure boundary.
"""

from __future__ import annotations

import copy
import hashlib
import json

from backend import semantic_closure


SCHEMA = "gg.action-done-when-result.v1"
COMPLETION_SCHEMA = "gg.action-completion-contract.v1"

MACHINE_SCOPE = "D68_D69_D70_SAFE_TOOL_READ"
DONE_WHEN_PREFIX = "TASK_COMPLETION_CONTRACT_SHA256="

RESULT_MACHINE_NOT_READY = "MACHINE_NOT_READY"
RESULT_EVIDENCE_REQUIRED = "EVIDENCE_REQUIRED"
RESULT_SEMANTIC_PASS = "PASS"


def _mapping(
    value: object,
    label: str,
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise RuntimeError(
            label + "_NOT_MAPPING"
        )
    return value


def _text(
    value: object,
    label: str,
    *,
    maximum: int = 4096,
) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
    ):
        raise RuntimeError(
            label + "_INVALID"
        )
    return value


def _sha256_text(
    value: object,
    label: str,
) -> str:
    text = _text(
        value,
        label,
        maximum=64,
    )
    if (
        len(text) != 64
        or any(
            char not in "0123456789abcdef"
            for char in text
        )
    ):
        raise RuntimeError(
            label + "_INVALID"
        )
    return text


def _boolean(
    value: object,
    label: str,
) -> bool:
    if not isinstance(value, bool):
        raise RuntimeError(
            label + "_INVALID"
        )
    return value


def _text_list(
    value: object,
    label: str,
) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or len(value) > 64
    ):
        raise RuntimeError(
            label + "_INVALID"
        )

    result: list[str] = []

    for item in value:
        result.append(
            _text(
                item,
                label + "_ITEM",
                maximum=4096,
            )
        )

    if len(set(result)) != len(result):
        raise RuntimeError(
            label + "_DUPLICATE"
        )

    return result


def _canonical_json(
    value: object,
) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_object(
    value: object,
) -> str:
    return hashlib.sha256(
        _canonical_json(value).encode(
            "utf-8"
        )
    ).hexdigest()


def _task_provenance(
    *,
    action_intent: dict[str, object],
    evaluation_context: dict[str, object],
) -> dict[str, object]:
    intent = _mapping(
        action_intent,
        "ACTION_INTENT",
    )
    context = _mapping(
        evaluation_context,
        "EVALUATION_CONTEXT",
    )

    task_id = _text(
        intent.get("task_id"),
        "TASK_ID",
        maximum=256,
    )
    origin_id = _text(
        intent.get("origin_id"),
        "ORIGIN_ID",
        maximum=256,
    )

    state_base_revision = _sha256_text(
        intent.get("state_base_revision"),
        "STATE_BASE_REVISION",
    )
    goal_chain_sha256 = _sha256_text(
        intent.get("goal_chain_sha256"),
        "GOAL_CHAIN_SHA256",
    )
    action_trace_sha256 = _sha256_text(
        intent.get("action_trace_sha256"),
        "ACTION_TRACE_SHA256",
    )

    source_envelope = _mapping(
        context.get("source_envelope"),
        "SOURCE_ENVELOPE",
    )

    if source_envelope.get("task_id") != task_id:
        raise RuntimeError(
            "TASK_ID_BINDING_MISMATCH"
        )

    if source_envelope.get("origin_id") != origin_id:
        raise RuntimeError(
            "ORIGIN_ID_BINDING_MISMATCH"
        )

    ready_core = _mapping(
        source_envelope.get("ready_core"),
        "READY_CORE",
    )

    goal = _text(
        ready_core.get("goal"),
        "TASK_GOAL",
        maximum=4096,
    )

    acceptance_criteria = _text_list(
        ready_core.get(
            "acceptance_criteria"
        ),
        "ACCEPTANCE_CRITERIA",
    )

    state_base = _mapping(
        context.get("state_base"),
        "STATE_BASE",
    )

    if (
        state_base.get(
            "state_base_revision"
        )
        != state_base_revision
    ):
        raise RuntimeError(
            "STATE_BASE_REVISION_BINDING_MISMATCH"
        )

    source_binding = _mapping(
        state_base.get("source_binding"),
        "STATE_SOURCE_BINDING",
    )

    if (
        source_binding.get(
            "goal_chain_sha256"
        )
        != goal_chain_sha256
    ):
        raise RuntimeError(
            "GOAL_CHAIN_BINDING_MISMATCH"
        )

    if (
        source_binding.get(
            "action_trace_sha256"
        )
        != action_trace_sha256
    ):
        raise RuntimeError(
            "ACTION_TRACE_BINDING_MISMATCH"
        )

    return {
        "task_id": task_id,
        "origin_id": origin_id,
        "goal": goal,
        "acceptance_criteria": (
            acceptance_criteria
        ),
        "source_envelope_sha256": (
            _sha256_object(
                source_envelope
            )
        ),
        "state_base_revision": (
            state_base_revision
        ),
        "goal_chain_sha256": (
            goal_chain_sha256
        ),
        "action_trace_sha256": (
            action_trace_sha256
        ),
    }


def _machine_evidence(
    *,
    action_intent: dict[str, object],
    execution_receipt: dict[str, object],
    actual_effect_observation: dict[str, object],
    action_effect_recovery: dict[str, object],
) -> tuple[str, bool, str]:
    intent = _mapping(
        action_intent,
        "ACTION_INTENT",
    )
    receipt = _mapping(
        execution_receipt,
        "EXECUTION_RECEIPT",
    )
    observation = _mapping(
        actual_effect_observation,
        "ACTUAL_EFFECT_OBSERVATION",
    )
    recovery = _mapping(
        action_effect_recovery,
        "ACTION_EFFECT_RECOVERY",
    )

    target_object_id = _text(
        intent.get("target_object_id"),
        "TARGET_OBJECT_ID",
        maximum=256,
    )
    target_source_revision = _sha256_text(
        intent.get(
            "target_source_revision"
        ),
        "TARGET_SOURCE_REVISION",
    )

    if (
        receipt.get("schema")
        != "gg.action-execution-result.v1"
    ):
        raise RuntimeError(
            "EXECUTION_RECEIPT_SCHEMA_INVALID"
        )

    if (
        _boolean(
            receipt.get("action_executed"),
            "ACTION_EXECUTED",
        )
        is not True
    ):
        raise RuntimeError(
            "ACTION_EXECUTION_NOT_VERIFIED"
        )

    if receipt.get("network") != "NONE":
        raise RuntimeError(
            "EXECUTION_NETWORK_AUTHORITY_DRIFT"
        )

    if receipt.get("sudo") != "NO":
        raise RuntimeError(
            "EXECUTION_SUDO_AUTHORITY_DRIFT"
        )

    if (
        _boolean(
            receipt.get("model_inference"),
            "EXECUTION_MODEL_INFERENCE",
        )
        is not False
    ):
        raise RuntimeError(
            "EXECUTION_MODEL_INFERENCE_DRIFT"
        )

    observation_result = _text(
        observation.get("result"),
        "OBSERVATION_RESULT",
        maximum=64,
    )
    actual_effect_verified = _boolean(
        observation.get(
            "actual_effect_verified"
        ),
        "ACTUAL_EFFECT_VERIFIED",
    )
    d70_required = _boolean(
        observation.get("d70_required"),
        "D70_REQUIRED",
    )

    mismatch_reasons_raw = observation.get(
        "mismatch_reasons"
    )

    if not isinstance(
        mismatch_reasons_raw,
        list,
    ):
        raise RuntimeError(
            "MISMATCH_REASONS_INVALID"
        )

    mismatch_reasons = [
        _text(
            item,
            "MISMATCH_REASON",
            maximum=256,
        )
        for item in mismatch_reasons_raw
    ]

    recovery_result = _text(
        recovery.get("result"),
        "RECOVERY_RESULT",
        maximum=64,
    )
    replan_required = _boolean(
        recovery.get("replan_required"),
        "REPLAN_REQUIRED",
    )
    authority_reevaluation = _boolean(
        recovery.get(
            "authority_reevaluation_required"
        ),
        "AUTHORITY_REEVALUATION_REQUIRED",
    )

    if (
        recovery.get("target_object_id")
        != target_object_id
    ):
        raise RuntimeError(
            "RECOVERY_TARGET_OBJECT_BINDING_MISMATCH"
        )

    if (
        recovery.get(
            "target_source_revision"
        )
        != target_source_revision
    ):
        raise RuntimeError(
            "RECOVERY_TARGET_SOURCE_BINDING_MISMATCH"
        )

    for field in (
        "repair_execution",
        "automatic_rerun",
        "existing_mandate_reusable",
        "new_action_authority_granted",
    ):
        if (
            _boolean(
                recovery.get(field),
                field.upper(),
            )
            is not False
        ):
            raise RuntimeError(
                "RECOVERY_EFFECT_AUTHORITY_DRIFT:"
                + field
            )

    if recovery.get("action_authority") != "NONE":
        raise RuntimeError(
            "RECOVERY_ACTION_AUTHORITY_DRIFT"
        )

    if (
        recovery.get(
            "general_action_authority"
        )
        != "NONE"
    ):
        raise RuntimeError(
            "RECOVERY_GENERAL_AUTHORITY_DRIFT"
        )

    if recovery_result == "NO_RECOVERY_REQUIRED":
        if (
            observation_result != "MATCH"
            or actual_effect_verified is not True
            or d70_required is not False
            or mismatch_reasons
            or replan_required is not False
            or authority_reevaluation is not False
        ):
            raise RuntimeError(
                "D71_MATCH_MACHINE_CONTRACT_INVALID"
            )

        if (
            observation.get(
                "target_object_id"
            )
            != target_object_id
        ):
            raise RuntimeError(
                "TARGET_OBJECT_ID_MISMATCH"
            )

        if (
            observation.get(
                "expected_target_source_revision"
            )
            != target_source_revision
            or observation.get(
                "observed_target_source_revision"
            )
            != target_source_revision
        ):
            raise RuntimeError(
                "TARGET_SOURCE_REVISION_MISMATCH"
            )

        machine_status = "PASS"
        machine_effect_verified = True

    elif recovery_result == "REPLAN_REQUIRED":
        if (
            observation_result != "MISMATCH"
            or actual_effect_verified is not False
            or d70_required is not True
            or not mismatch_reasons
            or replan_required is not True
            or authority_reevaluation is not True
        ):
            raise RuntimeError(
                "D71_REPLAN_MACHINE_CONTRACT_INVALID"
            )

        machine_status = "BLOCKED"
        machine_effect_verified = False

    else:
        raise RuntimeError(
            "D71_RECOVERY_RESULT_UNSUPPORTED:"
            + recovery_result
        )

    machine_evidence = {
        "execution_receipt": (
            copy.deepcopy(receipt)
        ),
        "actual_effect_observation": (
            copy.deepcopy(observation)
        ),
        "action_effect_recovery": (
            copy.deepcopy(recovery)
        ),
    }

    return (
        machine_status,
        machine_effect_verified,
        _sha256_object(
            machine_evidence
        ),
    )


def evaluate_action_done_when(
    *,
    action_intent: dict[str, object],
    evaluation_context: dict[str, object],
    execution_receipt: dict[str, object],
    actual_effect_observation: dict[str, object],
    action_effect_recovery: dict[str, object],
    semantic_evidence: (
        semantic_closure.SemanticEvidence
        | None
    ) = None,
) -> dict[str, object]:
    provenance = _task_provenance(
        action_intent=action_intent,
        evaluation_context=(
            evaluation_context
        ),
    )

    intent = _mapping(
        action_intent,
        "ACTION_INTENT",
    )

    target_object_id = _text(
        intent.get("target_object_id"),
        "TARGET_OBJECT_ID",
        maximum=256,
    )
    target_source_revision = _sha256_text(
        intent.get(
            "target_source_revision"
        ),
        "TARGET_SOURCE_REVISION",
    )
    capability_human_id = _text(
        intent.get(
            "capability_human_id"
        ),
        "CAPABILITY_HUMAN_ID",
        maximum=256,
    )
    action_binding_sha256 = _sha256_text(
        intent.get("binding_sha256"),
        "ACTION_BINDING_SHA256",
    )

    (
        machine_status,
        machine_effect_verified,
        machine_evidence_sha256,
    ) = _machine_evidence(
        action_intent=intent,
        execution_receipt=execution_receipt,
        actual_effect_observation=(
            actual_effect_observation
        ),
        action_effect_recovery=(
            action_effect_recovery
        ),
    )

    completion_contract = {
        "schema": COMPLETION_SCHEMA,
        "task_id": provenance["task_id"],
        "origin_id": provenance["origin_id"],
        "goal": provenance["goal"],
        "acceptance_criteria": copy.deepcopy(
            provenance[
                "acceptance_criteria"
            ]
        ),
        "source_envelope_sha256": (
            provenance[
                "source_envelope_sha256"
            ]
        ),
        "state_base_revision": (
            provenance[
                "state_base_revision"
            ]
        ),
        "goal_chain_sha256": (
            provenance[
                "goal_chain_sha256"
            ]
        ),
        "action_trace_sha256": (
            provenance[
                "action_trace_sha256"
            ]
        ),
        "capability_human_id": (
            capability_human_id
        ),
        "action_binding_sha256": (
            action_binding_sha256
        ),
        "target_object_id": (
            target_object_id
        ),
        "target_source_revision": (
            target_source_revision
        ),
        "required_machine_condition": (
            "D69_MATCH_AND_"
            "D70_NO_RECOVERY_REQUIRED"
        ),
        "semantic_evidence_required": True,
        "visible_acceptance_required": False,
    }

    completion_contract_sha256 = (
        _sha256_object(
            completion_contract
        )
    )

    done_when = (
        DONE_WHEN_PREFIX
        + completion_contract_sha256
    )

    request = (
        semantic_closure
        .SemanticClosureRequest(
            goal_id=str(
                provenance["task_id"]
            ),
            object_id=target_object_id,
            current_target=(
                target_object_id
                + "@"
                + target_source_revision
            ),
            done_when=done_when,
            source_sha256=(
                target_source_revision
            ),
            machine_status=machine_status,
            machine_scope=MACHINE_SCOPE,
            machine_evidence_sha256=(
                machine_evidence_sha256
            ),
            semantic_contract_sha256=(
                completion_contract_sha256
            ),
            visible_acceptance_required=False,
        )
    )

    closure = (
        semantic_closure
        .evaluate_semantic_closure(
            request,
            semantic_evidence,
        )
    )

    from backend import learning_memory_promotion as learning_memory

    learning_handoff = (
        semantic_closure
        .build_learning_handoff(
            closure
        )
    )

    episodic_experience = (
        learning_memory
        .build_episodic_experience(
            task_id=str(
                provenance["task_id"]
            ),
            origin_id=str(
                provenance["origin_id"]
            ),
            goal=str(
                provenance["goal"]
            ),
            state_base_revision=str(
                provenance[
                    "state_base_revision"
                ]
            ),
            source_sha256=(
                target_source_revision
            ),
            semantic_closure=(
                closure.as_dict()
            ),
            learning_handoff=(
                learning_handoff.as_dict()
            ),
        )
    )

    if closure.status == "PASS":
        reason_code = (
            "SEMANTIC_DONE_WHEN_VERIFIED"
        )
    elif closure.status == "EVIDENCE_REQUIRED":
        reason_code = (
            "SEMANTIC_EVIDENCE_REQUIRED"
        )
    elif closure.status == "MACHINE_NOT_READY":
        reason_code = (
            "MACHINE_NOT_READY"
        )
    else:
        reason_code = (
            "SEMANTIC_"
            + closure.status
        )

    return {
        "schema": SCHEMA,
        "result": closure.status,
        "reason_code": reason_code,
        "completion_contract": (
            copy.deepcopy(
                completion_contract
            )
        ),
        "completion_contract_sha256": (
            completion_contract_sha256
        ),
        "done_when": done_when,
        "source_sha256": (
            target_source_revision
        ),
        "machine_status": (
            machine_status
        ),
        "machine_scope": MACHINE_SCOPE,
        "machine_effect_verified": (
            machine_effect_verified
        ),
        "machine_evidence_sha256": (
            machine_evidence_sha256
        ),
        "semantic_request_sha256": (
            request.request_sha256()
        ),
        "semantic_status": closure.status,
        "semantic_done": (
            closure.semantic_done
        ),
        "semantic_closure": (
            closure.as_dict()
        ),
        "semantic_closure_sha256": (
            closure.closure_sha256()
        ),
        "semantic_evidence_supplied": (
            semantic_evidence is not None
        ),
        "visible_acceptance_required": False,
        "repair_execution": False,
        "automatic_rerun": False,
        "existing_mandate_reusable": False,
        "new_action_authority_granted": False,
        "action_authority": "NONE",
        "general_action_authority": "NONE",
        "network": "NONE",
        "sudo": "NO",
        "model_inference": False,

        "learning_handoff": (
            learning_handoff.as_dict()
        ),
        "learning_handoff_sha256": (
            learning_handoff
            .handoff_sha256()
        ),
        "episodic_experience": (
            copy.deepcopy(
                episodic_experience
            )
        ),
        "episodic_experience_sha256": (
            learning_memory
            .digest_json(
                episodic_experience
            )
        ),
    }
