from __future__ import annotations

import copy
import hashlib
import importlib.util
from pathlib import Path

from backend.application_paths import SUPPORT_ROOT, WORKSPACE_ROOT
from types import ModuleType
from typing import Any


SCHEMA_ID = "gg.orchestrator-handoff-adapter.v1"
ACTION_AUTHORITY = "NONE"
ORCHESTRATOR_RELATIVE_PATH = "orchestrator/gg_orchestrator.py"
ORCHESTRATOR_SHA256 = (
    "f6fbddd9cdaf31984ae9c6c99bab66aa3622fc098c4946081460ed6a51b97123"
)
NEXT_ACTION = "SELECTION_HANDOFF_ONLY_NO_EXECUTION"


class OrchestratorHandoffAdapterError(RuntimeError):
    pass


def _repo_root() -> Path:
    path = Path(__file__).resolve()
    if len(path.parents) < 4:
        raise OrchestratorHandoffAdapterError(
            "ADAPTER_PATH_DEPTH_INVALID"
        )
    return SUPPORT_ROOT if SUPPORT_ROOT.is_dir() else WORKSPACE_ROOT


def _source_path() -> Path:
    path = _repo_root() / ORCHESTRATOR_RELATIVE_PATH
    if not path.is_file() or path.is_symlink():
        raise OrchestratorHandoffAdapterError(
            "ORCHESTRATOR_SOURCE_INVALID"
        )
    return path


def _source_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_orchestrator() -> ModuleType:
    path = _source_path()
    before = _source_sha256(path)

    if before != ORCHESTRATOR_SHA256:
        raise OrchestratorHandoffAdapterError(
            "ORCHESTRATOR_SOURCE_SHA_MISMATCH:" + before
        )

    spec = importlib.util.spec_from_file_location(
        "gg_orchestrator_handoff_adapter_locked_source",
        path,
    )
    if spec is None or spec.loader is None:
        raise OrchestratorHandoffAdapterError(
            "ORCHESTRATOR_SOURCE_LOADER_UNAVAILABLE"
        )

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    after = _source_sha256(path)
    if after != ORCHESTRATOR_SHA256:
        raise OrchestratorHandoffAdapterError(
            "ORCHESTRATOR_SOURCE_CHANGED_DURING_LOAD:" + after
        )

    if not callable(getattr(module, "validate_handoff", None)):
        raise OrchestratorHandoffAdapterError(
            "VALIDATE_HANDOFF_UNAVAILABLE"
        )

    required = tuple(
        getattr(module, "HANDOFF_REQUIRED", ())
    )
    if required != (
        "handoff_id",
        "from_role",
        "to_role",
        "task_id",
        "status",
        "artifacts",
        "risks",
        "next_action",
    ):
        raise OrchestratorHandoffAdapterError(
            "HANDOFF_REQUIRED_CONTRACT_DRIFT"
        )

    return module


def _blocked_result(
    *,
    reason_code: str,
    task_id: str | None,
    assigned_participant: str | None,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA_ID,
        "status": "BLOCKED",
        "reason_code": reason_code,
        "task_id": task_id,
        "assigned_participant": assigned_participant,
        "handoff": None,
        "source_binding": {
            "relative_path": ORCHESTRATOR_RELATIVE_PATH,
            "sha256": ORCHESTRATOR_SHA256,
            "validator": "validate_handoff",
        },
        "selection_handoff_only": True,
        "participant_execution": False,
        "ordinary_chat_blocked": False,
        "action_authority": ACTION_AUTHORITY,
        "orchestrator_evaluate": False,
        "gate_validated": False,
        "review_validated": False,
        "agent_core_execution": False,
        "model_inference": False,
        "network": False,
        "runtime_write": False,
    }


def _task_identity(
    policy_result: dict[str, Any],
) -> tuple[str | None, str | None]:
    task = policy_result.get("validated_task")
    if not isinstance(task, dict):
        return None, None

    task_id = task.get("task_id")
    participant = task.get("assigned_participant")

    return (
        task_id.strip()
        if isinstance(task_id, str) and task_id.strip()
        else None,
        participant.strip()
        if isinstance(participant, str) and participant.strip()
        else None,
    )


def _validate_policy_safety(
    policy_result: dict[str, Any],
) -> None:
    expected = {
        "ordinary_chat_blocked": False,
        "action_authority": "NONE",
        "orchestrator_evaluate": False,
        "handoff_created": False,
        "handoff_validated": False,
        "gate_validated": False,
        "review_validated": False,
        "agent_core_execution": False,
        "model_inference": False,
        "network": False,
        "runtime_write": False,
    }

    for field, value in expected.items():
        if policy_result.get(field) != value:
            raise OrchestratorHandoffAdapterError(
                "POLICY_SAFETY_FIELD_DRIFT:" + field
            )


def _handoff_id(task: dict[str, Any]) -> str:
    verified_context = task.get("verified_context")
    if not isinstance(verified_context, dict):
        raise OrchestratorHandoffAdapterError(
            "VERIFIED_CONTEXT_NOT_OBJECT"
        )

    context_sha = verified_context.get("sha256", "")
    if not isinstance(context_sha, str):
        raise OrchestratorHandoffAdapterError(
            "VERIFIED_CONTEXT_SHA_INVALID"
        )

    pieces = (
        task.get("task_id"),
        task.get("first_gate"),
        task.get("assigned_participant"),
        context_sha,
    )

    if not all(
        isinstance(value, str) and value.strip()
        for value in pieces
    ):
        raise OrchestratorHandoffAdapterError(
            "HANDOFF_ID_SOURCE_INVALID"
        )

    binding = "\x1f".join(
        value.strip()
        for value in pieces
    )

    return (
        "handoff-"
        + hashlib.sha256(
            binding.encode("utf-8")
        ).hexdigest()[:32]
    )


def _build_handoff(
    task: dict[str, Any],
) -> dict[str, Any]:
    required = (
        "task_id",
        "first_gate",
        "assigned_participant",
    )

    for field in required:
        value = task.get(field)
        if not isinstance(value, str) or not value.strip():
            raise OrchestratorHandoffAdapterError(
                "TASK_FIELD_INVALID:" + field
            )

    return {
        "handoff_id": _handoff_id(task),
        "from_role": task["first_gate"].strip(),
        "to_role": task["assigned_participant"].strip(),
        "task_id": task["task_id"].strip(),
        "status": "PASS",
        "artifacts": [],
        "risks": [],
        "next_action": NEXT_ACTION,
    }


def validate_policy_handoff(
    policy_result: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(policy_result, dict):
        return _blocked_result(
            reason_code="POLICY_RESULT_NOT_OBJECT",
            task_id=None,
            assigned_participant=None,
        )

    task_id, participant = _task_identity(policy_result)

    if policy_result.get("status") != "VALIDATED":
        reason = policy_result.get("reason_code")
        return _blocked_result(
            reason_code=(
                reason
                if isinstance(reason, str) and reason
                else "POLICY_NOT_VALIDATED"
            ),
            task_id=task_id,
            assigned_participant=participant,
        )

    task = policy_result.get("validated_task")
    if not isinstance(task, dict):
        return _blocked_result(
            reason_code="VALIDATED_TASK_NOT_OBJECT",
            task_id=task_id,
            assigned_participant=participant,
        )

    module: ModuleType | None = None

    try:
        _validate_policy_safety(policy_result)
        handoff = _build_handoff(copy.deepcopy(task))
        module = _load_orchestrator()
        module.validate_handoff(
            copy.deepcopy(handoff),
            copy.deepcopy(task),
        )

    except OrchestratorHandoffAdapterError as exc:
        return _blocked_result(
            reason_code=str(exc),
            task_id=task_id,
            assigned_participant=participant,
        )

    except Exception as exc:
        policy_error = (
            getattr(module, "PolicyError", None)
            if module is not None
            else None
        )

        reason_code = (
            str(exc)
            if isinstance(policy_error, type)
            and isinstance(exc, policy_error)
            else "VALIDATE_HANDOFF_RUNTIME_ERROR:" + type(exc).__name__
        )

        return _blocked_result(
            reason_code=reason_code,
            task_id=task_id,
            assigned_participant=participant,
        )

    return {
        "schema": SCHEMA_ID,
        "status": "VALIDATED",
        "reason_code": "VALIDATE_HANDOFF_PASS",
        "task_id": handoff["task_id"],
        "assigned_participant": handoff["to_role"],
        "handoff": copy.deepcopy(handoff),
        "source_binding": {
            "relative_path": ORCHESTRATOR_RELATIVE_PATH,
            "sha256": ORCHESTRATOR_SHA256,
            "validator": "validate_handoff",
        },
        "selection_handoff_only": True,
        "participant_execution": False,
        "ordinary_chat_blocked": False,
        "action_authority": ACTION_AUTHORITY,
        "orchestrator_evaluate": False,
        "gate_validated": False,
        "review_validated": False,
        "agent_core_execution": False,
        "model_inference": False,
        "network": False,
        "runtime_write": False,
    }
