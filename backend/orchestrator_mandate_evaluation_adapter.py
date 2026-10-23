from __future__ import annotations

from backend.bound_source_platform import prepare_bound_namespace, adapt_bound_sources

import copy
import hashlib
import importlib.util
from pathlib import Path

from backend.application_paths import SUPPORT_ROOT, WORKSPACE_ROOT
from types import ModuleType
from typing import Any


SCHEMA_ID = "gg.orchestrator-mandate-evaluation-adapter.v1"
ACTION_AUTHORITY = "NONE"
MANDATE_RELATIVE_PATH = "cognitive-core/gg_mandate_approval.py"
MANDATE_SHA256 = "896b9f33da2ef8855d811da57aeb6db2bf6591bf3da3568ab1ddc5126aeac133"
EXPECTED_REQUEST_SCHEMA = "gg.mandate-approval-request.v1"
EXPECTED_EVALUATION_SCHEMA = "gg.mandate-evaluation-result.v1"
EVALUATION_CONTEXT_FIELDS = {
    "source_envelope",
    "goal_chain",
    "hypothesis_state",
    "state_base",
    "ledger_records",
    "memory_records",
}
EVALUATION_RESULT_FIELDS = {
    "schema",
    "request_capture_sha256",
    "approval_scope_revision",
    "current_approval_scope_revision",
    "mandate_assertion_sha256",
    "result",
    "reason_code",
}


class OrchestratorMandateEvaluationAdapterError(RuntimeError):
    pass


def _repo_root() -> Path:
    path = Path(__file__).resolve()
    if len(path.parents) < 4:
        raise OrchestratorMandateEvaluationAdapterError(
            "ADAPTER_PATH_DEPTH_INVALID"
        )
    return SUPPORT_ROOT if SUPPORT_ROOT.is_dir() else WORKSPACE_ROOT


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_mandate_engine() -> ModuleType:
    path = _repo_root() / MANDATE_RELATIVE_PATH
    if not path.is_file() or path.is_symlink():
        raise OrchestratorMandateEvaluationAdapterError(
            "MANDATE_SOURCE_INVALID"
        )

    before = _sha256(path)
    if before != MANDATE_SHA256:
        raise OrchestratorMandateEvaluationAdapterError(
            "MANDATE_SOURCE_SHA_MISMATCH:" + before
        )

    spec = importlib.util.spec_from_file_location(
        "gg_orchestrator_mandate_evaluation_locked_k7k",
        path,
    )
    if spec is None or spec.loader is None:
        raise OrchestratorMandateEvaluationAdapterError(
            "MANDATE_SOURCE_LOADER_UNAVAILABLE"
        )

    module = importlib.util.module_from_spec(spec)
    prepare_bound_namespace(module.__dict__)
    spec.loader.exec_module(module)

    after = _sha256(path)
    if after != MANDATE_SHA256:
        raise OrchestratorMandateEvaluationAdapterError(
            "MANDATE_SOURCE_CHANGED_DURING_LOAD:" + after
        )

    for name in (
        "validate_approval_request",
        "evaluate_mandate",
    ):
        if not callable(getattr(module, name, None)):
            raise OrchestratorMandateEvaluationAdapterError(
                "MANDATE_API_UNAVAILABLE:" + name
            )

    return adapt_bound_sources(module)


def _base_result(
    *,
    status: str,
    reason_code: str,
    task_id: object,
    handoff_id: object,
    assigned_participant: object,
    creator_actor: object,
    request_capture_sha256: object,
    mandate_requirement: object,
    evaluation_receipt: object,
    mandate_evaluated: bool,
    ordinary_chat_blocked: bool,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA_ID,
        "status": status,
        "reason_code": reason_code,
        "task_id": task_id,
        "handoff_id": handoff_id,
        "assigned_participant": assigned_participant,
        "creator_actor": creator_actor,
        "request_capture_sha256": request_capture_sha256,
        "mandate_requirement": mandate_requirement,
        "evaluation_receipt": copy.deepcopy(evaluation_receipt),
        "mandate_assertion_created": False,
        "mandate_evaluated": mandate_evaluated,
        "capability_execution": False,
        "participant_execution": False,
        "ordinary_chat_blocked": ordinary_chat_blocked,
        "action_authority": ACTION_AUTHORITY,
        "model_inference": False,
        "network": False,
        "runtime_write": False,
    }


def _blocked(
    mandate_result: object,
    reason_code: str,
) -> dict[str, Any]:
    value = mandate_result if isinstance(mandate_result, dict) else {}
    return _base_result(
        status="BLOCKED",
        reason_code=reason_code,
        task_id=value.get("task_id"),
        handoff_id=value.get("handoff_id"),
        assigned_participant=value.get("assigned_participant"),
        creator_actor=value.get("creator_actor"),
        request_capture_sha256=value.get("request_capture_sha256"),
        mandate_requirement=value.get("mandate_requirement"),
        evaluation_receipt=None,
        mandate_evaluated=False,
        ordinary_chat_blocked=True,
    )


def evaluate_not_required(
    mandate_result: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(mandate_result, dict):
        return _blocked(mandate_result, "MANDATE_RESULT_NOT_OBJECT")

    status = mandate_result.get("status")
    if status == "NOT_APPLICABLE":
        return _base_result(
            status="NOT_APPLICABLE",
            reason_code=str(mandate_result.get("reason_code", "NOT_APPLICABLE")),
            task_id=mandate_result.get("task_id"),
            handoff_id=mandate_result.get("handoff_id"),
            assigned_participant=mandate_result.get("assigned_participant"),
            creator_actor=mandate_result.get("creator_actor"),
            request_capture_sha256=None,
            mandate_requirement=None,
            evaluation_receipt=None,
            mandate_evaluated=False,
            ordinary_chat_blocked=False,
        )

    if status != "VALIDATED":
        return _blocked(
            mandate_result,
            "MANDATE_REQUEST_NOT_VALIDATED:" + str(status),
        )

    if mandate_result.get("action_authority") != ACTION_AUTHORITY:
        return _blocked(mandate_result, "D65_ACTION_AUTHORITY_DRIFT")
    if mandate_result.get("canonical_request_mutated") is not False:
        return _blocked(mandate_result, "D65_CANONICAL_REQUEST_MUTATION_DRIFT")
    if mandate_result.get("mandate_assertion_created") is not False:
        return _blocked(mandate_result, "D65_ASSERTION_STATE_DRIFT")
    if mandate_result.get("mandate_evaluated") is not False:
        return _blocked(mandate_result, "D65_EVALUATION_STATE_DRIFT")
    if mandate_result.get("capability_execution") is not False:
        return _blocked(mandate_result, "D65_CAPABILITY_STATE_DRIFT")
    if mandate_result.get("participant_execution") is not False:
        return _blocked(mandate_result, "D65_PARTICIPANT_STATE_DRIFT")

    source_binding = mandate_result.get("source_binding")
    if not isinstance(source_binding, dict):
        return _blocked(mandate_result, "D65_SOURCE_BINDING_INVALID")
    if source_binding != {
        "relative_path": MANDATE_RELATIVE_PATH,
        "sha256": MANDATE_SHA256,
        "operation": "make_approval_request",
    }:
        return _blocked(mandate_result, "D65_SOURCE_BINDING_DRIFT")

    request = mandate_result.get("approval_request")
    capture = mandate_result.get("request_capture_sha256")
    requirement = mandate_result.get("mandate_requirement")
    context = mandate_result.get("evaluation_context")

    if not isinstance(request, dict):
        return _blocked(mandate_result, "APPROVAL_REQUEST_NOT_OBJECT")
    if request.get("schema") != EXPECTED_REQUEST_SCHEMA:
        return _blocked(mandate_result, "APPROVAL_REQUEST_SCHEMA_DRIFT")
    if request.get("request_capture_sha256") != capture:
        return _blocked(mandate_result, "REQUEST_CAPTURE_CONTINUITY_FAILED")
    if request.get("mandate_requirement") != requirement:
        return _blocked(mandate_result, "MANDATE_REQUIREMENT_CONTINUITY_FAILED")

    if not isinstance(context, dict) or set(context) != EVALUATION_CONTEXT_FIELDS:
        return _blocked(mandate_result, "EVALUATION_CONTEXT_SURFACE_INVALID")

    if not isinstance(context["ledger_records"], list):
        return _blocked(mandate_result, "EVALUATION_LEDGER_RECORDS_INVALID")
    if not isinstance(context["memory_records"], list):
        return _blocked(mandate_result, "EVALUATION_MEMORY_RECORDS_INVALID")
    if context["memory_records"]:
        return _blocked(
            mandate_result,
            "CURRENT_V1_MEMORY_INPUT_MUST_BE_EXPLICIT_EMPTY_LIST",
        )

    try:
        mandate = _load_mandate_engine()
        validated = mandate.validate_approval_request(
            copy.deepcopy(request)
        )
    except OrchestratorMandateEvaluationAdapterError as exc:
        return _blocked(mandate_result, str(exc))
    except Exception as exc:
        return _blocked(
            mandate_result,
            "APPROVAL_REQUEST_VALIDATION_RUNTIME_ERROR:"
            + type(exc).__name__,
        )

    if validated.get("request_capture_sha256") != capture:
        return _blocked(
            mandate_result,
            "NATIVE_REQUEST_CAPTURE_CONTINUITY_FAILED",
        )
    if validated.get("mandate_requirement") != requirement:
        return _blocked(
            mandate_result,
            "NATIVE_MANDATE_REQUIREMENT_CONTINUITY_FAILED",
        )

    if requirement not in {"NOT_REQUIRED", "EXPLICIT_REQUIRED"}:
        return _blocked(mandate_result, "MANDATE_REQUIREMENT_INVALID")

    try:
        receipt = mandate.evaluate_mandate(
            request=copy.deepcopy(validated),
            mandate_assertion=None,
            source_envelope=copy.deepcopy(context["source_envelope"]),
            goal_chain=copy.deepcopy(context["goal_chain"]),
            hypothesis_state=copy.deepcopy(context["hypothesis_state"]),
            state_base=copy.deepcopy(context["state_base"]),
            ledger_records=copy.deepcopy(context["ledger_records"]),
            memory_records=copy.deepcopy(context["memory_records"]),
        )
    except Exception as exc:
        return _blocked(
            mandate_result,
            "MANDATE_EVALUATION_RUNTIME_ERROR:" + type(exc).__name__,
        )

    if not isinstance(receipt, dict) or set(receipt) != EVALUATION_RESULT_FIELDS:
        return _blocked(mandate_result, "EVALUATION_RECEIPT_SURFACE_INVALID")
    if receipt.get("schema") != EXPECTED_EVALUATION_SCHEMA:
        return _blocked(mandate_result, "EVALUATION_RECEIPT_SCHEMA_DRIFT")
    if receipt.get("request_capture_sha256") != capture:
        return _blocked(mandate_result, "EVALUATION_CAPTURE_CONTINUITY_FAILED")

    request_scope = request.get("approval_scope_revision")
    if receipt.get("approval_scope_revision") != request_scope:
        return _blocked(mandate_result, "EVALUATION_SCOPE_CONTINUITY_FAILED")
    if receipt.get("current_approval_scope_revision") != request_scope:
        return _blocked(mandate_result, "EVALUATION_CURRENT_SCOPE_MISMATCH")
    if receipt.get("mandate_assertion_sha256") is not None:
        return _blocked(mandate_result, "UNEXPECTED_MANDATE_ASSERTION_HASH")
    if requirement == "EXPLICIT_REQUIRED":
        if receipt.get("result") != "MANDATE_REQUIRED":
            return _blocked(mandate_result, "MANDATE_REQUIRED_RESULT_INVALID")
        if receipt.get("reason_code") != "EXPLICIT_MANDATE_MISSING":
            return _blocked(mandate_result, "MANDATE_REQUIRED_REASON_INVALID")
        return _base_result(
            status="DEFERRED",
            reason_code="MANDATE_REQUIRED_VERIFIED",
            task_id=mandate_result.get("task_id"),
            handoff_id=mandate_result.get("handoff_id"),
            assigned_participant=mandate_result.get("assigned_participant"),
            creator_actor=mandate_result.get("creator_actor"),
            request_capture_sha256=capture,
            mandate_requirement=requirement,
            evaluation_receipt=receipt,
            mandate_evaluated=True,
            ordinary_chat_blocked=True,
        )

    if receipt.get("result") != "MANDATE_NOT_REQUIRED":
        return _blocked(
            mandate_result,
            "UNEXPECTED_MANDATE_RESULT:" + str(receipt.get("result")),
        )
    if receipt.get("reason_code") != "GREEN_RISK_CLASS":
        return _blocked(
            mandate_result,
            "UNEXPECTED_MANDATE_REASON:" + str(receipt.get("reason_code")),
        )

    return _base_result(
        status="EVALUATED",
        reason_code="MANDATE_NOT_REQUIRED_VERIFIED",
        task_id=mandate_result.get("task_id"),
        handoff_id=mandate_result.get("handoff_id"),
        assigned_participant=mandate_result.get("assigned_participant"),
        creator_actor=mandate_result.get("creator_actor"),
        request_capture_sha256=capture,
        mandate_requirement=requirement,
        evaluation_receipt=receipt,
        mandate_evaluated=True,
        ordinary_chat_blocked=False,
    )


def evaluate_explicit_approval(
    mandate_result: dict[str, Any],
    *,
    approver_id: str,
    approval_scope_revision_value: str,
) -> dict[str, Any]:
    baseline = evaluate_not_required(copy.deepcopy(mandate_result))
    baseline_receipt = baseline.get("evaluation_receipt")

    if (
        baseline.get("status") != "DEFERRED"
        or baseline.get("reason_code") != "MANDATE_REQUIRED_VERIFIED"
        or not isinstance(baseline_receipt, dict)
        or baseline_receipt.get("result") != "MANDATE_REQUIRED"
        or baseline_receipt.get("reason_code") != "EXPLICIT_MANDATE_MISSING"
    ):
        return _blocked(mandate_result, "EXPLICIT_APPROVAL_BASELINE_INVALID")

    if not isinstance(approver_id, str):
        return _blocked(mandate_result, "EXPLICIT_APPROVER_ID_INVALID")

    request = mandate_result.get("approval_request")
    context = mandate_result.get("evaluation_context")
    capture = mandate_result.get("request_capture_sha256")

    if not isinstance(request, dict):
        return _blocked(mandate_result, "EXPLICIT_APPROVAL_REQUEST_INVALID")
    if not isinstance(context, dict) or set(context) != EVALUATION_CONTEXT_FIELDS:
        return _blocked(mandate_result, "EXPLICIT_EVALUATION_CONTEXT_INVALID")

    request_scope = request.get("approval_scope_revision")
    if (
        not isinstance(approval_scope_revision_value, str)
        or approval_scope_revision_value != request_scope
    ):
        return _blocked(mandate_result, "EXPLICIT_APPROVAL_SCOPE_MISMATCH")

    try:
        mandate = _load_mandate_engine()
        make_assertion = getattr(mandate, "make_mandate_assertion", None)
        if not callable(make_assertion):
            return _blocked(
                mandate_result,
                "MANDATE_API_UNAVAILABLE:make_mandate_assertion",
            )

        assertion = make_assertion(
            approver_id=approver_id,
            approval_scope_revision_value=approval_scope_revision_value,
        )
        receipt = mandate.evaluate_mandate(
            request=copy.deepcopy(request),
            mandate_assertion=copy.deepcopy(assertion),
            source_envelope=copy.deepcopy(context["source_envelope"]),
            goal_chain=copy.deepcopy(context["goal_chain"]),
            hypothesis_state=copy.deepcopy(context["hypothesis_state"]),
            state_base=copy.deepcopy(context["state_base"]),
            ledger_records=copy.deepcopy(context["ledger_records"]),
            memory_records=copy.deepcopy(context["memory_records"]),
        )
    except Exception as exc:
        return _blocked(
            mandate_result,
            "EXPLICIT_MANDATE_EVALUATION_RUNTIME_ERROR:"
            + type(exc).__name__,
        )

    if not isinstance(receipt, dict) or set(receipt) != EVALUATION_RESULT_FIELDS:
        return _blocked(
            mandate_result,
            "EXPLICIT_EVALUATION_RECEIPT_SURFACE_INVALID",
        )

    assertion_sha = assertion.get("mandate_assertion_sha256")
    if (
        receipt.get("schema") != EXPECTED_EVALUATION_SCHEMA
        or receipt.get("request_capture_sha256") != capture
        or receipt.get("approval_scope_revision") != request_scope
        or receipt.get("current_approval_scope_revision") != request_scope
        or receipt.get("mandate_assertion_sha256") != assertion_sha
        or receipt.get("result") != "MANDATE_VALID"
        or receipt.get("reason_code") != "APPROVAL_SCOPE_MATCH"
    ):
        return _blocked(
            mandate_result,
            "EXPLICIT_MANDATE_VALID_RECEIPT_INVALID",
        )

    result = _base_result(
        status="EVALUATED",
        reason_code="MANDATE_VALID_VERIFIED",
        task_id=mandate_result.get("task_id"),
        handoff_id=mandate_result.get("handoff_id"),
        assigned_participant=mandate_result.get("assigned_participant"),
        creator_actor=mandate_result.get("creator_actor"),
        request_capture_sha256=capture,
        mandate_requirement=mandate_result.get("mandate_requirement"),
        evaluation_receipt=receipt,
        mandate_evaluated=True,
        ordinary_chat_blocked=True,
    )
    result["mandate_assertion_created"] = True
    return result
