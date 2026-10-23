from __future__ import annotations

import copy
from typing import Any


SCHEMA_ID = "gg.orchestrator-ingress.v1"
ACTION_AUTHORITY = "NONE"

READY_CORE_REQUIRED = (
    "owner",
    "goal",
    "expected_value",
    "scope",
    "forbidden_scope",
    "risk_class",
    "stop_conditions",
    "expected_artifacts",
    "acceptance_criteria",
)

VERIFIED_CONTEXT_REQUIRED = (
    "source_path",
    "object_id",
    "sha256",
)

MAX_TEXT = 4096


class OrchestratorIngressError(ValueError):
    pass


def _required_text(
    value: Any,
    label: str,
) -> str:
    if not isinstance(value, str):
        raise OrchestratorIngressError(label + "_NOT_STRING")

    normalized = value.strip()

    if not normalized:
        raise OrchestratorIngressError(label + "_EMPTY")

    if len(normalized) > MAX_TEXT:
        raise OrchestratorIngressError(label + "_TOO_LONG")

    return normalized


def _optional_text(
    value: Any,
    label: str,
) -> str | None:
    if value is None:
        return None

    return _required_text(
        value,
        label,
    )


def _validate_ready_core(
    value: Any,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OrchestratorIngressError("READY_CORE_NOT_OBJECT")

    for field in READY_CORE_REQUIRED:
        if field not in value:
            raise OrchestratorIngressError(
                "READY_CORE_FIELD_MISSING:" + field
            )

        if value[field] in ("", None, [], {}):
            raise OrchestratorIngressError(
                "READY_CORE_FIELD_EMPTY:" + field
            )

    if value["risk_class"] not in {"GREEN", "YELLOW", "RED"}:
        raise OrchestratorIngressError(
            "READY_CORE_RISK_CLASS_INVALID"
        )

    return copy.deepcopy(value)


def _validate_verified_context(
    value: Any,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OrchestratorIngressError(
            "VERIFIED_CONTEXT_NOT_OBJECT"
        )

    for field in VERIFIED_CONTEXT_REQUIRED:
        if field not in value:
            raise OrchestratorIngressError(
                "VERIFIED_CONTEXT_FIELD_MISSING:" + field
            )

    source_path = _required_text(
        value["source_path"],
        "SOURCE_PATH",
    )
    object_id = _required_text(
        value["object_id"],
        "OBJECT_ID",
    )
    source_sha256 = _required_text(
        value["sha256"],
        "SOURCE_SHA256",
    ).lower()

    if (
        len(source_sha256) != 64
        or any(
            character not in "0123456789abcdef"
            for character in source_sha256
        )
    ):
        raise OrchestratorIngressError(
            "SOURCE_SHA256_INVALID"
        )

    result = copy.deepcopy(value)
    result["source_path"] = source_path
    result["object_id"] = object_id
    result["sha256"] = source_sha256
    return result


def prepare_or_block(
    *,
    envelope: dict[str, Any],
    verified_context: dict[str, Any],
    assigned_participant: str | None = None,
    creator_actor: str | None = None,
) -> dict[str, Any]:
    if not isinstance(envelope, dict):
        raise OrchestratorIngressError("ENVELOPE_NOT_OBJECT")

    if envelope.get("state") != "READY_FOR_CONTROL":
        raise OrchestratorIngressError(
            "ENVELOPE_NOT_READY_FOR_CONTROL"
        )

    task_id = _required_text(
        envelope.get("task_id"),
        "TASK_ID",
    )
    ready_core = _validate_ready_core(
        envelope.get("ready_core")
    )
    context = _validate_verified_context(
        verified_context
    )

    participant = _optional_text(
        assigned_participant,
        "ASSIGNED_PARTICIPANT",
    )
    actor = _optional_text(
        creator_actor,
        "CREATOR_ACTOR",
    )

    if participant is None and actor is None:
        status = "BLOCKED"
        reason_code = (
            "EXPLICIT_ASSIGNMENT_AND_CREATOR_ACTOR_REQUIRED"
        )
    elif participant is None:
        status = "BLOCKED"
        reason_code = "EXPLICIT_ASSIGNMENT_REQUIRED"
    elif actor is None:
        status = "BLOCKED"
        reason_code = "CREATOR_ACTOR_REQUIRED"
    else:
        status = "CONDITIONAL"
        reason_code = (
            "ORCHESTRATOR_POLICY_VALIDATION_REQUIRED"
        )

    return {
        "schema": SCHEMA_ID,
        "status": status,
        "reason_code": reason_code,
        "task_seed": {
            "task_id": task_id,
            "ready_core": ready_core,
            "verified_context": context,
        },
        "assigned_participant": participant,
        "creator_actor": actor,
        "ordinary_chat_blocked": False,
        "action_authority": ACTION_AUTHORITY,
        "orchestrator_evaluate": False,
        "agent_core_execution": False,
        "model_inference": False,
        "network": False,
        "runtime_write": False,
    }
