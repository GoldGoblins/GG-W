from __future__ import annotations

import copy
import hashlib
import json
from pathlib import PurePosixPath
from typing import Any

from backend import action_intent_contract
from backend import safe_tool_contract


SCHEMA = "gg.action-execution-eligibility.v1"

RESULT_ELIGIBLE = "EXECUTION_ELIGIBLE"
RESULT_BLOCKED = "EXECUTION_BLOCKED"

CAPABILITY_ID = "tool.safe.dispatch"
SAFE_TOOL_PROFILE = safe_tool_contract.PROFILE_READ

ACTION_AUTHORITY = "NONE"
GENERAL_ACTION_AUTHORITY = "NONE"

_DECISION_FIELDS = frozenset(
    (
        "schema",
        "result",
        "reason_code",
        "action_intent_binding_sha256",
        "capability_human_id",
        "capability_contract_sha256",
        "capability_execution_revision_sha256",
        "capability_metadata_sha256",
        "target_object_id",
        "target_source_path",
        "target_source_revision",
        "state_base_revision",
        "request_capture_sha256",
        "approval_scope_revision",
        "mandate_assertion_sha256",
        "manifest_sha256",
        "safe_tool_profile",
        "safe_tool_request",
        "safe_tool_request_sha256",
        "capability_persistent_write",
        "execution_persistent_write_authority",
        "action_authority",
        "general_action_authority",
        "capability_execution",
        "k7_l_execution",
        "participant_execution",
        "network",
        "sudo",
        "model_inference",
        "eligibility_binding_sha256",
    )
)


class ActionExecutionEligibilityError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ActionExecutionEligibilityError(
            "CANONICAL_JSON_INVALID"
        ) from exc
    return (rendered + "\n").encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha_text(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ActionExecutionEligibilityError(label + "_INVALID")
    return value


def _text(value: Any, label: str, maximum: int = 240) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or "\x00" in value
        or "\n" in value
        or "\r" in value
    ):
        raise ActionExecutionEligibilityError(label + "_INVALID")
    return value


def _record_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return copy.deepcopy(value)

    serializer = getattr(value, "as_dict", None)
    if not callable(serializer):
        raise ActionExecutionEligibilityError(
            "CAPABILITY_RECORD_SURFACE_INVALID"
        )

    result = serializer()
    if not isinstance(result, dict):
        raise ActionExecutionEligibilityError(
            "CAPABILITY_RECORD_SERIALIZER_INVALID"
        )
    return copy.deepcopy(result)


def _target_path(value: Any) -> str:
    raw = _text(value, "TARGET_SOURCE_PATH")

    prefix = "projects/gg-ai-desktop/"
    if raw.startswith(prefix):
        raw = raw[len(prefix):]

    if raw.startswith("/"):
        raise ActionExecutionEligibilityError(
            "TARGET_SOURCE_PATH_ABSOLUTE"
        )

    pieces = raw.split("/")
    if any(piece in ("", ".", "..") for piece in pieces):
        raise ActionExecutionEligibilityError(
            "TARGET_SOURCE_PATH_TRAVERSAL"
        )

    normalized = PurePosixPath(raw).as_posix()
    if normalized != raw:
        raise ActionExecutionEligibilityError(
            "TARGET_SOURCE_PATH_NONCANONICAL"
        )

    return raw


def _decision(
    *,
    intent: dict[str, Any],
    target_source_path: str,
    request_capture_sha256: str,
    approval_scope_revision: str,
    mandate_assertion_sha256: str,
    manifest_sha256: str,
    result: str,
    reason_code: str,
    safe_tool_request: dict[str, Any] | None,
    safe_tool_request_sha256: str | None,
) -> dict[str, Any]:
    value = {
        "schema": SCHEMA,
        "result": result,
        "reason_code": reason_code,
        "action_intent_binding_sha256": intent["binding_sha256"],
        "capability_human_id": intent["capability_human_id"],
        "capability_contract_sha256": intent[
            "capability_contract_sha256"
        ],
        "capability_execution_revision_sha256": intent[
            "capability_execution_revision_sha256"
        ],
        "capability_metadata_sha256": intent[
            "capability_metadata_sha256"
        ],
        "target_object_id": intent["target_object_id"],
        "target_source_path": target_source_path,
        "target_source_revision": intent["target_source_revision"],
        "state_base_revision": intent["state_base_revision"],
        "request_capture_sha256": request_capture_sha256,
        "approval_scope_revision": approval_scope_revision,
        "mandate_assertion_sha256": mandate_assertion_sha256,
        "manifest_sha256": manifest_sha256,
        "safe_tool_profile": SAFE_TOOL_PROFILE,
        "safe_tool_request": copy.deepcopy(safe_tool_request),
        "safe_tool_request_sha256": safe_tool_request_sha256,
        "capability_persistent_write": intent["persistent_write"],
        "execution_persistent_write_authority": "NONE",
        "action_authority": ACTION_AUTHORITY,
        "general_action_authority": GENERAL_ACTION_AUTHORITY,
        "capability_execution": False,
        "k7_l_execution": False,
        "participant_execution": False,
        "network": "NONE",
        "sudo": "NO",
        "model_inference": False,
    }
    value["eligibility_binding_sha256"] = _sha(value)
    return validate_execution_eligibility(value)


def validate_execution_eligibility(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _DECISION_FIELDS:
        raise ActionExecutionEligibilityError(
            "ELIGIBILITY_SURFACE_INVALID"
        )

    result = copy.deepcopy(value)

    if result["schema"] != SCHEMA:
        raise ActionExecutionEligibilityError(
            "ELIGIBILITY_SCHEMA_INVALID"
        )

    if result["result"] not in (RESULT_ELIGIBLE, RESULT_BLOCKED):
        raise ActionExecutionEligibilityError(
            "ELIGIBILITY_RESULT_INVALID"
        )

    _text(result["reason_code"], "REASON_CODE", 128)

    for field in (
        "action_intent_binding_sha256",
        "capability_contract_sha256",
        "capability_execution_revision_sha256",
        "capability_metadata_sha256",
        "target_source_revision",
        "state_base_revision",
        "request_capture_sha256",
        "approval_scope_revision",
        "mandate_assertion_sha256",
        "manifest_sha256",
        "eligibility_binding_sha256",
    ):
        _sha_text(result[field], field.upper())

    _text(result["capability_human_id"], "CAPABILITY_HUMAN_ID", 128)
    _text(result["target_object_id"], "TARGET_OBJECT_ID", 128)
    _target_path(result["target_source_path"])

    if result["safe_tool_profile"] != SAFE_TOOL_PROFILE:
        raise ActionExecutionEligibilityError(
            "SAFE_TOOL_PROFILE_INVALID"
        )

    safe_request = result["safe_tool_request"]
    safe_request_sha = result["safe_tool_request_sha256"]

    if result["result"] == RESULT_ELIGIBLE:
        if not isinstance(safe_request, dict):
            raise ActionExecutionEligibilityError(
                "SAFE_TOOL_REQUEST_MISSING"
            )
        validated_request = safe_tool_contract.validate_request(
            safe_request
        )
        if validated_request["profile"] != SAFE_TOOL_PROFILE:
            raise ActionExecutionEligibilityError(
                "SAFE_TOOL_REQUEST_PROFILE_INVALID"
            )
        _sha_text(
            safe_request_sha,
            "SAFE_TOOL_REQUEST_SHA256",
        )
        actual_request_sha = hashlib.sha256(
            safe_tool_contract.canonical_request_json(
                validated_request
            ).encode("utf-8")
        ).hexdigest()
        if actual_request_sha != safe_request_sha:
            raise ActionExecutionEligibilityError(
                "SAFE_TOOL_REQUEST_SHA256_MISMATCH"
            )
    elif safe_request is not None or safe_request_sha is not None:
        raise ActionExecutionEligibilityError(
            "BLOCKED_DECISION_EXPOSED_RUNNABLE_REQUEST"
        )

    constants = {
        "execution_persistent_write_authority": "NONE",
        "action_authority": "NONE",
        "general_action_authority": "NONE",
        "capability_execution": False,
        "k7_l_execution": False,
        "participant_execution": False,
        "network": "NONE",
        "sudo": "NO",
        "model_inference": False,
    }

    for field, expected in constants.items():
        if result[field] != expected:
            raise ActionExecutionEligibilityError(
                "ELIGIBILITY_AUTHORITY_DRIFT:" + field
            )

    without_binding = {
        key: copy.deepcopy(item)
        for key, item in result.items()
        if key != "eligibility_binding_sha256"
    }

    if _sha(without_binding) != result["eligibility_binding_sha256"]:
        raise ActionExecutionEligibilityError(
            "ELIGIBILITY_BINDING_SHA256_MISMATCH"
        )

    return result


def evaluate_execution_eligibility(
    *,
    action_intent: dict[str, Any],
    capability_record: Any,
    approval_request: dict[str, Any],
    approval_receipt: dict[str, Any],
    mandate_assertion_sha256: str,
    current_manifest_sha256: str,
    expected_manifest_sha256: str,
    current_target_object_id: str,
    current_target_source_path: str,
    current_target_source_revision: str,
    replay_state: str,
) -> dict[str, Any]:
    intent = action_intent_contract.validate_action_intent(
        action_intent
    )

    request = copy.deepcopy(approval_request)
    receipt = copy.deepcopy(approval_receipt)

    if not isinstance(request, dict):
        raise ActionExecutionEligibilityError(
            "APPROVAL_REQUEST_INVALID"
        )
    if not isinstance(receipt, dict):
        raise ActionExecutionEligibilityError(
            "APPROVAL_RECEIPT_INVALID"
        )

    scope = request.get("approval_scope")
    if not isinstance(scope, dict):
        raise ActionExecutionEligibilityError(
            "APPROVAL_SCOPE_INVALID"
        )

    ready_core = scope.get("ready_core")
    if not isinstance(ready_core, dict):
        raise ActionExecutionEligibilityError(
            "READY_CORE_INVALID"
        )

    request_capture = _sha_text(
        request.get("request_capture_sha256"),
        "REQUEST_CAPTURE_SHA256",
    )
    scope_revision = _sha_text(
        request.get("approval_scope_revision"),
        "APPROVAL_SCOPE_REVISION",
    )
    assertion_sha = _sha_text(
        mandate_assertion_sha256,
        "MANDATE_ASSERTION_SHA256",
    )
    current_manifest = _sha_text(
        current_manifest_sha256,
        "CURRENT_MANIFEST_SHA256",
    )
    expected_manifest = _sha_text(
        expected_manifest_sha256,
        "EXPECTED_MANIFEST_SHA256",
    )
    current_target_revision = _sha_text(
        current_target_source_revision,
        "CURRENT_TARGET_SOURCE_REVISION",
    )

    target_object = _text(
        current_target_object_id,
        "CURRENT_TARGET_OBJECT_ID",
        128,
    )
    target_path = _target_path(
        current_target_source_path
    )

    def blocked(reason: str) -> dict[str, Any]:
        return _decision(
            intent=intent,
            target_source_path=target_path,
            request_capture_sha256=request_capture,
            approval_scope_revision=scope_revision,
            mandate_assertion_sha256=assertion_sha,
            manifest_sha256=current_manifest,
            result=RESULT_BLOCKED,
            reason_code=reason,
            safe_tool_request=None,
            safe_tool_request_sha256=None,
        )

    if replay_state != "UNUSED":
        return blocked("REPLAY_STATE_INVALID")

    if current_manifest != expected_manifest:
        return blocked("MANIFEST_REVISION_MISMATCH")

    if intent["capability_human_id"] != CAPABILITY_ID:
        return blocked("CAPABILITY_UNSUPPORTED")

    record = _record_dict(capability_record)

    if record.get("human_id") != intent["capability_human_id"]:
        return blocked("CAPABILITY_HUMAN_ID_MISMATCH")

    if (
        record.get("contract_sha256")
        != intent["capability_contract_sha256"]
    ):
        return blocked("CAPABILITY_CONTRACT_SHA_MISMATCH")

    if (
        record.get("execution_revision_sha256")
        != intent["capability_execution_revision_sha256"]
    ):
        return blocked("CAPABILITY_EXECUTION_REVISION_MISMATCH")

    if (
        record.get("metadata_sha256")
        != intent["capability_metadata_sha256"]
    ):
        return blocked("CAPABILITY_METADATA_SHA_MISMATCH")

    contract = record.get("contract")
    if not isinstance(contract, dict):
        return blocked("CAPABILITY_CONTRACT_SURFACE_INVALID")

    exact_contract = {
        "effect_class": "READ_ONLY_TOOL_EXECUTION",
        "risk_floor": "YELLOW",
        "persistent_write": "RUNTIME_ONLY",
        "network": "NONE",
        "sudo": "NO",
        "execution_authority": "CONTROLLED_PROFILE",
        "model_inference": False,
    }

    for field, expected in exact_contract.items():
        if contract.get(field) != expected:
            return blocked(
                "CAPABILITY_CONTRACT_UNSUPPORTED:" + field
            )

    intent_contract = {
        "effect_class": intent["effect_class"],
        "risk_floor": intent["risk_floor"],
        "persistent_write": intent["persistent_write"],
        "network": intent["network"],
        "sudo": intent["sudo"],
        "execution_authority": intent[
            "capability_execution_profile_requirement"
        ],
        "model_inference": intent["model_inference"],
    }

    if intent_contract != exact_contract:
        return blocked("ACTION_INTENT_CAPABILITY_CONTRACT_DRIFT")

    if intent["action_authority"] != "NONE":
        return blocked("ACTION_INTENT_AUTHORITY_INVALID")

    if target_object != intent["target_object_id"]:
        return blocked("TARGET_OBJECT_ID_MISMATCH")

    if current_target_revision != intent["target_source_revision"]:
        return blocked("TARGET_SOURCE_REVISION_MISMATCH")

    if request.get("task_id") != intent["task_id"]:
        return blocked("APPROVAL_TASK_ID_MISMATCH")

    if request.get("origin_id") != intent["origin_id"]:
        return blocked("APPROVAL_ORIGIN_ID_MISMATCH")

    if (
        scope.get("state_base_revision")
        != intent["state_base_revision"]
    ):
        return blocked("APPROVAL_STATE_BASE_MISMATCH")

    if (
        scope.get("action_trace_sha256")
        != intent["action_trace_sha256"]
    ):
        return blocked("APPROVAL_ACTION_TRACE_MISMATCH")

    if ready_core.get("risk_class") != intent["risk_floor"]:
        return blocked("APPROVAL_RISK_MISMATCH")

    if receipt.get("result") != "MANDATE_VALID":
        return blocked("MANDATE_RESULT_INVALID")

    if receipt.get("reason_code") != "APPROVAL_SCOPE_MATCH":
        return blocked("MANDATE_REASON_INVALID")

    if receipt.get("request_capture_sha256") != request_capture:
        return blocked("MANDATE_REQUEST_CAPTURE_MISMATCH")

    if receipt.get("approval_scope_revision") != scope_revision:
        return blocked("MANDATE_SCOPE_REVISION_MISMATCH")

    if (
        receipt.get("current_approval_scope_revision")
        != scope_revision
    ):
        return blocked("MANDATE_CURRENT_SCOPE_REVISION_MISMATCH")

    if receipt.get("mandate_assertion_sha256") != assertion_sha:
        return blocked("MANDATE_ASSERTION_MISMATCH")

    safe_request = safe_tool_contract.validate_request(
        {
            "schema": safe_tool_contract.REQUEST_SCHEMA,
            "request_id": (
                'tool-'
                + intent["binding_sha256"][:32]
            ),
            "profile": SAFE_TOOL_PROFILE,
            "arguments": {
                "path": (
                    "projects/gg-ai-desktop/"
                    + target_path
                ),
            },
        }
    )

    safe_request_sha = hashlib.sha256(
        safe_tool_contract.canonical_request_json(
            safe_request
        ).encode("utf-8")
    ).hexdigest()

    return _decision(
        intent=intent,
        target_source_path=target_path,
        request_capture_sha256=request_capture,
        approval_scope_revision=scope_revision,
        mandate_assertion_sha256=assertion_sha,
        manifest_sha256=current_manifest,
        result=RESULT_ELIGIBLE,
        reason_code="EXACT_SAFE_TOOL_READ_REFINEMENT",
        safe_tool_request=safe_request,
        safe_tool_request_sha256=safe_request_sha,
    )
