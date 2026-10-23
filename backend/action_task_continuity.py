from __future__ import annotations

import copy
from typing import Any

from backend import control_plane_contract as control_contract


SCHEMA = "gg.workbench.action-task-continuity.v1"
CONTINUITY_SCHEMA = "gg.workbench.action-continuity-snapshot.v1"
MANDATE_SCHEMA = "gg.workbench.action-mandate-evidence.v1"
EVIDENCE_SCHEMA = "gg.workbench.action-execution-evidence.v1"
EFFECTS_SCHEMA = "gg.workbench.action-effects-evidence.v1"

SHA256_CHARS = frozenset("0123456789abcdef")


class ActionTaskContinuityError(ValueError):
    pass


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ActionTaskContinuityError(
            label + "_NOT_MAPPING"
        )
    return copy.deepcopy(value)


def _text(
    value: Any,
    label: str,
    *,
    maximum: int = 32768,
) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or "\x00" in value
    ):
        raise ActionTaskContinuityError(
            label + "_INVALID"
        )
    return value


def _sha(value: Any, label: str) -> str:
    text = _text(
        value,
        label,
        maximum=64,
    )
    if (
        len(text) != 64
        or any(char not in SHA256_CHARS for char in text)
    ):
        raise ActionTaskContinuityError(
            label + "_INVALID"
        )
    return text


def resident_task_id(
    action_intent: dict[str, Any],
) -> str:
    intent = _mapping(
        action_intent,
        "ACTION_INTENT",
    )
    binding = _sha(
        intent.get("binding_sha256"),
        "ACTION_BINDING_SHA256",
    )
    return "task-" + binding[:32]


def replay_reusable(value: str) -> bool:
    return value == "UNUSED"


def _goal(
    pending: dict[str, Any],
    original_intent: str,
) -> str:
    evaluation = pending.get(
        "evaluation_context"
    )

    if isinstance(evaluation, dict):
        envelope = evaluation.get(
            "source_envelope"
        )

        if isinstance(envelope, dict):
            ready = envelope.get(
                "ready_core"
            )

            if isinstance(ready, dict):
                candidate = ready.get("goal")

                if (
                    isinstance(candidate, str)
                    and candidate
                    and len(candidate) <= 4096
                    and "\x00" not in candidate
                ):
                    return candidate

    return original_intent[:4096]


def _status_and_reason(
    pending: dict[str, Any],
) -> tuple[str, str]:
    status = str(
        pending.get("status", "")
    )
    replay = str(
        pending.get(
            "execution_state",
            "UNUSED",
        )
    )

    if status == "REJECTED":
        return "STOPPED", "OPERATOR_REJECTED"

    completion = pending.get(
        "action_done_when"
    )

    if isinstance(completion, dict):
        result = str(
            completion.get("result", "")
        )

        if (
            completion.get("semantic_done") is True
            and result == "PASS"
        ):
            return "DONE", "DONE_WHEN_VERIFIED"

        if result == "EVIDENCE_REQUIRED":
            return (
                "BLOCKED",
                "SEMANTIC_EVIDENCE_REQUIRED",
            )

        if result == "MACHINE_NOT_READY":
            return "BLOCKED", "MACHINE_NOT_READY"

        if result:
            return (
                "BLOCKED",
                "DONE_WHEN_" + result,
            )

    if replay == "CONSUMED_START_FAILED":
        return (
            "BLOCKED",
            "ACTION_EXECUTION_START_FAILED",
        )

    if replay == "CONSUMED_FAILED":
        return (
            "BLOCKED",
            "ACTION_EXECUTION_FAILED",
        )

    if status.startswith("BLOCKED"):
        return "BLOCKED", status

    if (
        replay == "CONSUMED_PASS"
        or status == "ACTION_EXECUTED"
    ):
        return "VERIFYING", "DONE_WHEN_PENDING"

    if (
        replay == "DISPATCHED"
        or status == "EXECUTION_RUNNING"
    ):
        return "RUNNING", "ACTION_DISPATCHED"

    if status == "APPROVED_VALID":
        return "APPROVED", "MANDATE_APPROVED_VALID"

    if status == "WAITING_APPROVAL":
        return (
            "WAITING_FOR_USER",
            "EXPLICIT_MANDATE_REQUIRED",
        )

    return "CREATED", "ACTION_TASK_CREATED"


def _normalized_replay(
    pending: dict[str, Any],
) -> str:
    status = str(
        pending.get("status", "")
    )
    replay = str(
        pending.get(
            "execution_state",
            "UNUSED",
        )
    )

    if status == "REJECTED":
        return "REJECTED"

    if status == "STOPPED_BY_USER":
        return "STOPPED"

    return replay


def _put(
    ledger: control_contract.TaskLedger,
    value: dict[str, Any],
) -> str:
    return ledger.put_object(
        copy.deepcopy(value)
    )


def _sync(
    ledger: control_contract.TaskLedger | None,
    pending: dict[str, Any],
) -> dict[str, object]:
    if ledger is None:
        raise ActionTaskContinuityError(
            "TASK_LEDGER_UNAVAILABLE"
        )

    source = _mapping(
        pending,
        "PENDING_ACTION",
    )

    intent = _mapping(
        source.get("action_intent"),
        "ACTION_INTENT",
    )

    task_id = resident_task_id(intent)

    original_intent = _text(
        source.get("user_text"),
        "ORIGINAL_INTENT",
    )

    route_why = source.get("route_why")
    why = (
        route_why
        if (
            isinstance(route_why, str)
            and route_why
            and len(route_why) <= 32768
            and "\x00" not in route_why
        )
        else original_intent
    )

    source_task_id = _text(
        intent.get("task_id"),
        "SOURCE_TASK_ID",
        maximum=4096,
    )

    action_binding = _sha(
        intent.get("binding_sha256"),
        "ACTION_BINDING_SHA256",
    )

    state_base = _sha(
        intent.get("state_base_revision"),
        "STATE_BASE_REVISION",
    )

    goal = _goal(
        source,
        original_intent,
    )

    mandate_object = {
        "schema": MANDATE_SCHEMA,
        "pending_id": source.get("pending_id"),
        "mandate_result": copy.deepcopy(
            source.get("mandate_result")
        ),
        "evaluation_context": copy.deepcopy(
            source.get("evaluation_context")
        ),
        "approval_receipt": copy.deepcopy(
            source.get("approval_receipt")
        ),
        "approver_id": source.get("approver_id"),
        "mandate_assertion_sha256": (
            source.get(
                "mandate_assertion_sha256"
            )
        ),
        "approval_scope_revision": (
            source.get(
                "approval_scope_revision"
            )
        ),
        "request_capture_sha256": (
            source.get(
                "request_capture_sha256"
            )
        ),
    }

    execution_object = {
        "schema": EVIDENCE_SCHEMA,
        "execution_eligibility": copy.deepcopy(
            source.get("execution_eligibility")
        ),
        "execution_eligibility_binding_sha256": (
            source.get(
                "execution_eligibility_binding_sha256"
            )
        ),
        "execution_safe_tool_request_sha256": (
            source.get(
                "execution_safe_tool_request_sha256"
            )
        ),
        "execution_evidence_path": source.get(
            "execution_evidence_path"
        ),
        "execution_receipt": copy.deepcopy(
            source.get("execution_receipt")
        ),
    }

    effects_object = {
        "schema": EFFECTS_SCHEMA,
        "actual_effect_observation": copy.deepcopy(
            source.get(
                "actual_effect_observation"
            )
        ),
        "action_effect_recovery": copy.deepcopy(
            source.get(
                "action_effect_recovery"
            )
        ),
        "action_done_when": copy.deepcopy(
            source.get("action_done_when")
        ),
    }

    mandate_sha = _put(
        ledger,
        mandate_object,
    )
    evidence_sha = _put(
        ledger,
        execution_object,
    )
    effects_sha = _put(
        ledger,
        effects_object,
    )

    status, reason = _status_and_reason(
        source
    )

    replay = _normalized_replay(
        source
    )

    completion = source.get(
        "action_done_when"
    )

    done_when = ""

    if isinstance(completion, dict):
        candidate = completion.get(
            "done_when"
        )
        if isinstance(candidate, str):
            done_when = candidate

    previous = ledger.get(task_id)

    previous_continuity = ""

    if previous is not None:
        previous_continuity = str(
            previous.get(
                "continuity_sha256",
                "",
            )
        )

    continuity_object = {
        "schema": CONTINUITY_SCHEMA,
        "resident_task_id": task_id,
        "source_task_id": source_task_id,
        "original_intent": original_intent,
        "goal": goal,
        "why": why,
        "state_base_revision": state_base,
        "action_binding_sha256": action_binding,
        "action_intent": copy.deepcopy(intent),
        "mandate_sha256": mandate_sha,
        "evidence_sha256": evidence_sha,
        "effects_sha256": effects_sha,
        "done_when": done_when,
        "status": status,
        "last_reason": reason,
        "action_replay_state": replay,
        "previous_continuity_sha256": (
            previous_continuity
        ),
    }

    continuity_sha = _put(
        ledger,
        continuity_object,
    )

    fields = {
        "original_intent": original_intent,
        "why": why,
        "source_task_id": source_task_id,
        "action_binding_sha256": action_binding,
        "state_base_revision": state_base,
        "continuity_sha256": continuity_sha,
        "mandate_sha256": mandate_sha,
        "evidence_sha256": evidence_sha,
        "effects_sha256": effects_sha,
        "done_when": done_when,
        "action_replay_state": replay,
        "last_reason": reason,
    }

    if previous is None:
        return ledger.create(
            task_id,
            "ACTION",
            status,
            goal,
            str(
                source.get(
                    "context_reference",
                    "@current",
                )
            ),
            str(
                source.get(
                    "workspace_object_id",
                    "",
                )
            ),
            **fields,
        )

    immutable = (
        ("original_intent", original_intent),
        ("source_task_id", source_task_id),
        (
            "action_binding_sha256",
            action_binding,
        ),
        (
            "state_base_revision",
            state_base,
        ),
    )

    for key, expected in immutable:
        if previous.get(key) != expected:
            raise ActionTaskContinuityError(
                "ACTION_CONTINUITY_IDENTITY_DRIFT:"
                + key
            )

    return ledger.update(
        task_id,
        status=status,
        goal=goal,
        **fields,
    )


def capture_action_task(
    ledger: control_contract.TaskLedger | None,
    pending: dict[str, Any],
) -> dict[str, object]:
    return _sync(
        ledger,
        pending,
    )


def record_action_approval(
    ledger: control_contract.TaskLedger | None,
    pending: dict[str, Any],
) -> dict[str, object]:
    return _sync(
        ledger,
        pending,
    )


def record_action_dispatch(
    ledger: control_contract.TaskLedger | None,
    pending: dict[str, Any],
) -> dict[str, object]:
    return _sync(
        ledger,
        pending,
    )


def record_action_completion(
    ledger: control_contract.TaskLedger | None,
    pending: dict[str, Any],
) -> dict[str, object]:
    if ledger is None:
        raise ActionTaskContinuityError(
            "TASK_LEDGER_UNAVAILABLE"
        )

    intent = _mapping(
        pending.get("action_intent"),
        "ACTION_INTENT",
    )

    task_id = resident_task_id(
        intent
    )

    current = ledger.get(task_id)

    if (
        current is not None
        and current.get("status") == "RUNNING"
        and pending.get("execution_receipt")
        is not None
    ):
        ledger.update(
            task_id,
            status="VERIFYING",
            last_reason=(
                "DONE_WHEN_VERIFICATION"
            ),
        )

    return _sync(
        ledger,
        pending,
    )
