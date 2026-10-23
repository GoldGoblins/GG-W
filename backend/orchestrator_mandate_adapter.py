from __future__ import annotations

import copy
import hashlib
import importlib.util
from pathlib import Path

from backend.application_paths import SUPPORT_ROOT, WORKSPACE_ROOT
from backend.bound_source_platform import prepare_bound_namespace, adapt_bound_sources
from types import ModuleType
from typing import Any


SCHEMA_ID = "gg.orchestrator-mandate-adapter.v1"
ACTION_AUTHORITY = "NONE"
MANDATE_RELATIVE_PATH = "cognitive-core/gg_mandate_approval.py"
MANDATE_SHA256 = (
    "896b9f33da2ef8855d811da57aeb6db2"
    "bf6591bf3da3568ab1ddc5126aeac133"
)
EXPECTED_REQUEST_SCHEMA = "gg.mandate-approval-request.v1"


class OrchestratorMandateAdapterError(RuntimeError):
    pass


def _repo_root() -> Path:
    path = Path(__file__).resolve()
    if len(path.parents) < 4:
        raise OrchestratorMandateAdapterError("ADAPTER_PATH_DEPTH_INVALID")
    return SUPPORT_ROOT if SUPPORT_ROOT.is_dir() else WORKSPACE_ROOT


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_mandate_engine() -> ModuleType:
    path = _repo_root() / MANDATE_RELATIVE_PATH
    if not path.is_file() or path.is_symlink():
        raise OrchestratorMandateAdapterError("MANDATE_SOURCE_INVALID")

    before = _sha256(path)
    if before != MANDATE_SHA256:
        raise OrchestratorMandateAdapterError(
            "MANDATE_SOURCE_SHA_MISMATCH:" + before
        )

    spec = importlib.util.spec_from_file_location(
        "gg_orchestrator_mandate_adapter_locked_k7k",
        path,
    )
    if spec is None or spec.loader is None:
        raise OrchestratorMandateAdapterError(
            "MANDATE_SOURCE_LOADER_UNAVAILABLE"
        )

    module = importlib.util.module_from_spec(spec)
    prepare_bound_namespace(module.__dict__)
    spec.loader.exec_module(module)

    after = _sha256(path)
    if after != MANDATE_SHA256:
        raise OrchestratorMandateAdapterError(
            "MANDATE_SOURCE_CHANGED_DURING_LOAD:" + after
        )

    if not callable(getattr(module, "make_approval_request", None)):
        raise OrchestratorMandateAdapterError(
            "MAKE_APPROVAL_REQUEST_UNAVAILABLE"
        )

    return adapt_bound_sources(module)


def _nonplan_result(decision_kind: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA_ID,
        "status": "NOT_APPLICABLE",
        "reason_code": "DECISION_NOT_PLAN_ACTION:" + decision_kind,
        "task_id": None,
        "handoff_id": None,
        "assigned_participant": None,
        "creator_actor": None,
        "approval_request": None,
        "request_capture_sha256": None,
        "provenance_binding_sha256": None,
        "mandate_requirement": None,
        "source_binding": {
            "relative_path": MANDATE_RELATIVE_PATH,
            "sha256": MANDATE_SHA256,
            "operation": "make_approval_request",
        },
        "canonical_request_mutated": False,
        "mandate_assertion_created": False,
        "mandate_evaluated": False,
        "capability_execution": False,
        "participant_execution": False,
        "ordinary_chat_blocked": False,
        "action_authority": ACTION_AUTHORITY,
        "model_inference": False,
        "network": False,
        "runtime_write": False,
    }


def _blocked_result(
    *,
    reason_code: str,
    task_id: str | None,
    handoff_id: str | None,
    assigned_participant: str | None,
    creator_actor: str | None,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA_ID,
        "status": "BLOCKED",
        "reason_code": reason_code,
        "task_id": task_id,
        "handoff_id": handoff_id,
        "assigned_participant": assigned_participant,
        "creator_actor": creator_actor,
        "approval_request": None,
        "request_capture_sha256": None,
        "provenance_binding_sha256": None,
        "mandate_requirement": None,
        "source_binding": {
            "relative_path": MANDATE_RELATIVE_PATH,
            "sha256": MANDATE_SHA256,
            "operation": "make_approval_request",
        },
        "canonical_request_mutated": False,
        "mandate_assertion_created": False,
        "mandate_evaluated": False,
        "capability_execution": False,
        "participant_execution": False,
        "ordinary_chat_blocked": False,
        "action_authority": ACTION_AUTHORITY,
        "model_inference": False,
        "network": False,
        "runtime_write": False,
    }


def _identity(
    policy_result: dict[str, Any],
    handoff_result: dict[str, Any],
) -> tuple[
    str | None,
    str | None,
    str | None,
    str | None,
]:
    task = policy_result.get("validated_task")
    handoff = handoff_result.get("handoff")

    task_id = None
    participant = None
    creator = None
    handoff_id = None

    if isinstance(task, dict):
        value = task.get("task_id")
        if isinstance(value, str) and value.strip():
            task_id = value.strip()

        value = task.get("assigned_participant")
        if isinstance(value, str) and value.strip():
            participant = value.strip()

        value = task.get("creator_actor")
        if isinstance(value, str) and value.strip():
            creator = value.strip()

    if isinstance(handoff, dict):
        value = handoff.get("handoff_id")
        if isinstance(value, str) and value.strip():
            handoff_id = value.strip()

    return task_id, handoff_id, participant, creator


def _validate_orchestration(
    policy_result: dict[str, Any],
    handoff_result: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if policy_result.get("status") != "VALIDATED":
        raise OrchestratorMandateAdapterError("POLICY_NOT_VALIDATED")

    if handoff_result.get("status") != "VALIDATED":
        raise OrchestratorMandateAdapterError("HANDOFF_NOT_VALIDATED")

    task = policy_result.get("validated_task")
    handoff = handoff_result.get("handoff")

    if not isinstance(task, dict):
        raise OrchestratorMandateAdapterError(
            "VALIDATED_TASK_NOT_OBJECT"
        )

    if not isinstance(handoff, dict):
        raise OrchestratorMandateAdapterError(
            "VALIDATED_HANDOFF_NOT_OBJECT"
        )

    required_task = (
        "task_id",
        "assigned_participant",
        "creator_actor",
        "risk_class",
    )
    for field in required_task:
        value = task.get(field)
        if not isinstance(value, str) or not value.strip():
            raise OrchestratorMandateAdapterError(
                "TASK_FIELD_INVALID:" + field
            )

    required_handoff = (
        "handoff_id",
        "task_id",
        "to_role",
    )
    for field in required_handoff:
        value = handoff.get(field)
        if not isinstance(value, str) or not value.strip():
            raise OrchestratorMandateAdapterError(
                "HANDOFF_FIELD_INVALID:" + field
            )

    if handoff["task_id"].strip() != task["task_id"].strip():
        raise OrchestratorMandateAdapterError(
            "TASK_ID_CONTINUITY_FAILED"
        )

    if handoff["to_role"].strip() != task["assigned_participant"].strip():
        raise OrchestratorMandateAdapterError(
            "PARTICIPANT_CONTINUITY_FAILED"
        )

    if policy_result.get("action_authority") != "NONE":
        raise OrchestratorMandateAdapterError(
            "POLICY_ACTION_AUTHORITY_DRIFT"
        )

    if handoff_result.get("action_authority") != "NONE":
        raise OrchestratorMandateAdapterError(
            "HANDOFF_ACTION_AUTHORITY_DRIFT"
        )

    if handoff_result.get("participant_execution") is not False:
        raise OrchestratorMandateAdapterError(
            "HANDOFF_PARTICIPANT_EXECUTION_DRIFT"
        )

    return copy.deepcopy(task), copy.deepcopy(handoff)


def _provenance_binding(
    *,
    task_id: str,
    handoff_id: str,
    assigned_participant: str,
    creator_actor: str,
    request_capture_sha256: str,
) -> str:
    material = "\x1f".join(
        (
            task_id,
            handoff_id,
            assigned_participant,
            creator_actor,
            request_capture_sha256,
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def prepare_approval_request(
    *,
    decision_kind: str,
    revalidation_result: str,
    source_envelope: dict[str, Any],
    goal_chain: dict[str, Any],
    hypothesis_state: dict[str, Any],
    state_base: dict[str, Any],
    ledger_records: list[dict[str, Any]],
    memory_records: list[dict[str, Any]],
    orchestrator_policy: dict[str, Any],
    orchestrator_handoff: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(decision_kind, str) or not decision_kind.strip():
        return _blocked_result(
            reason_code="DECISION_KIND_INVALID",
            task_id=None,
            handoff_id=None,
            assigned_participant=None,
            creator_actor=None,
        )

    normalized_decision = decision_kind.strip()

    if normalized_decision != "PLAN_ACTION":
        return _nonplan_result(normalized_decision)

    task_id, handoff_id, participant, creator = _identity(
        orchestrator_policy,
        orchestrator_handoff,
    )

    if revalidation_result != "REVALIDATED":
        return _blocked_result(
            reason_code="STATE_NOT_REVALIDATED",
            task_id=task_id,
            handoff_id=handoff_id,
            assigned_participant=participant,
            creator_actor=creator,
        )

    if not isinstance(memory_records, list) or memory_records:
        return _blocked_result(
            reason_code="CURRENT_V1_MEMORY_INPUT_MUST_BE_EXPLICIT_EMPTY_LIST",
            task_id=task_id,
            handoff_id=handoff_id,
            assigned_participant=participant,
            creator_actor=creator,
        )

    try:
        task, handoff = _validate_orchestration(
            orchestrator_policy,
            orchestrator_handoff,
        )
        mandate = _load_mandate_engine()
        request = mandate.make_approval_request(
            source_envelope=copy.deepcopy(source_envelope),
            goal_chain=copy.deepcopy(goal_chain),
            hypothesis_state=copy.deepcopy(hypothesis_state),
            state_base=copy.deepcopy(state_base),
            ledger_records=copy.deepcopy(ledger_records),
            memory_records=[],
        )
    except OrchestratorMandateAdapterError as exc:
        return _blocked_result(
            reason_code=str(exc),
            task_id=task_id,
            handoff_id=handoff_id,
            assigned_participant=participant,
            creator_actor=creator,
        )
    except Exception as exc:
        return _blocked_result(
            reason_code=(
                "MAKE_APPROVAL_REQUEST_RUNTIME_ERROR:"
                + type(exc).__name__
            ),
            task_id=task_id,
            handoff_id=handoff_id,
            assigned_participant=participant,
            creator_actor=creator,
        )

    if not isinstance(request, dict):
        return _blocked_result(
            reason_code="APPROVAL_REQUEST_NOT_OBJECT",
            task_id=task["task_id"],
            handoff_id=handoff["handoff_id"],
            assigned_participant=task["assigned_participant"],
            creator_actor=task["creator_actor"],
        )

    if request.get("schema") != EXPECTED_REQUEST_SCHEMA:
        return _blocked_result(
            reason_code="APPROVAL_REQUEST_SCHEMA_DRIFT",
            task_id=task["task_id"],
            handoff_id=handoff["handoff_id"],
            assigned_participant=task["assigned_participant"],
            creator_actor=task["creator_actor"],
        )

    if request.get("task_id") != task["task_id"]:
        return _blocked_result(
            reason_code="K7K_TASK_ID_CONTINUITY_FAILED",
            task_id=task["task_id"],
            handoff_id=handoff["handoff_id"],
            assigned_participant=task["assigned_participant"],
            creator_actor=task["creator_actor"],
        )

    capture = request.get("request_capture_sha256")
    requirement = request.get("mandate_requirement")

    if (
        not isinstance(capture, str)
        or len(capture) != 64
        or any(char not in "0123456789abcdef" for char in capture)
    ):
        return _blocked_result(
            reason_code="REQUEST_CAPTURE_SHA256_INVALID",
            task_id=task["task_id"],
            handoff_id=handoff["handoff_id"],
            assigned_participant=task["assigned_participant"],
            creator_actor=task["creator_actor"],
        )

    if requirement not in {"NOT_REQUIRED", "EXPLICIT_REQUIRED"}:
        return _blocked_result(
            reason_code="MANDATE_REQUIREMENT_INVALID",
            task_id=task["task_id"],
            handoff_id=handoff["handoff_id"],
            assigned_participant=task["assigned_participant"],
            creator_actor=task["creator_actor"],
        )

    binding = _provenance_binding(
        task_id=task["task_id"],
        handoff_id=handoff["handoff_id"],
        assigned_participant=task["assigned_participant"],
        creator_actor=task["creator_actor"],
        request_capture_sha256=capture,
    )

    return {
        "schema": SCHEMA_ID,
        "status": "VALIDATED",
        "reason_code": "MANDATE_REQUEST_PREPARED",
        "task_id": task["task_id"],
        "handoff_id": handoff["handoff_id"],
        "assigned_participant": task["assigned_participant"],
        "creator_actor": task["creator_actor"],
        "approval_request": copy.deepcopy(request),
        "evaluation_context": {
            "source_envelope": copy.deepcopy(source_envelope),
            "goal_chain": copy.deepcopy(goal_chain),
            "hypothesis_state": copy.deepcopy(hypothesis_state),
            "state_base": copy.deepcopy(state_base),
            "ledger_records": copy.deepcopy(ledger_records),
            "memory_records": copy.deepcopy(memory_records),
        },
        "request_capture_sha256": capture,
        "provenance_binding_sha256": binding,
        "mandate_requirement": requirement,
        "source_binding": {
            "relative_path": MANDATE_RELATIVE_PATH,
            "sha256": MANDATE_SHA256,
            "operation": "make_approval_request",
        },
        "canonical_request_mutated": False,
        "mandate_assertion_created": False,
        "mandate_evaluated": False,
        "capability_execution": False,
        "participant_execution": False,
        "ordinary_chat_blocked": False,
        "action_authority": ACTION_AUTHORITY,
        "model_inference": False,
        "network": False,
        "runtime_write": False,
    }
