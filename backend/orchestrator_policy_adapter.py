from __future__ import annotations

import copy
import hashlib
import importlib.util
from pathlib import Path

from backend.application_paths import SUPPORT_ROOT, WORKSPACE_ROOT
from types import ModuleType
from typing import Any

SCHEMA_ID = "gg.orchestrator-policy-adapter.v1"
ACTION_AUTHORITY = "NONE"
ORCHESTRATOR_RELATIVE_PATH = "orchestrator/gg_orchestrator.py"
ORCHESTRATOR_SHA256 = "f6fbddd9cdaf31984ae9c6c99bab66aa3622fc098c4946081460ed6a51b97123"
FIRST_GATE = "idekompassen-2.0"

IDEKOMPASS_REQUIRED = (
    "task_id",
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

TASK_SCOPED_EFFECTS = (
    "network",
    "credentials",
    "production",
    "one_com",
    "merge",
    "deploy",
    "write",
    "sudo",
)
BLOCKED_EFFECTS = ("unbounded_background_autonomy",)


class OrchestratorPolicyAdapterError(RuntimeError):
    pass


def _repo_root() -> Path:
    path = Path(__file__).resolve()
    if len(path.parents) < 4:
        raise OrchestratorPolicyAdapterError("ADAPTER_PATH_DEPTH_INVALID")
    return SUPPORT_ROOT if SUPPORT_ROOT.is_dir() else WORKSPACE_ROOT


def _source_path() -> Path:
    path = _repo_root() / ORCHESTRATOR_RELATIVE_PATH
    if not path.is_file() or path.is_symlink():
        raise OrchestratorPolicyAdapterError("ORCHESTRATOR_SOURCE_INVALID")
    return path


def _source_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_orchestrator() -> ModuleType:
    path = _source_path()
    before = _source_sha256(path)
    if before != ORCHESTRATOR_SHA256:
        raise OrchestratorPolicyAdapterError(
            "ORCHESTRATOR_SOURCE_SHA_MISMATCH:" + before
        )

    spec = importlib.util.spec_from_file_location(
        "gg_orchestrator_policy_adapter_locked_source",
        path,
    )
    if spec is None or spec.loader is None:
        raise OrchestratorPolicyAdapterError(
            "ORCHESTRATOR_SOURCE_LOADER_UNAVAILABLE"
        )

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    after = _source_sha256(path)
    if after != ORCHESTRATOR_SHA256:
        raise OrchestratorPolicyAdapterError(
            "ORCHESTRATOR_SOURCE_CHANGED_DURING_LOAD:" + after
        )

    if not callable(getattr(module, "validate_task", None)):
        raise OrchestratorPolicyAdapterError("VALIDATE_TASK_UNAVAILABLE")

    if tuple(getattr(module, "IDEKOMPASS_REQUIRED", ())) != IDEKOMPASS_REQUIRED:
        raise OrchestratorPolicyAdapterError(
            "IDEKOMPASS_REQUIRED_CONTRACT_DRIFT"
        )

    if tuple(getattr(module, "BLOCKED_EFFECTS", ())) != BLOCKED_EFFECTS:
        raise OrchestratorPolicyAdapterError(
            "BLOCKED_EFFECTS_CONTRACT_DRIFT"
        )

    return module


def _blocked_result(
    *,
    reason_code: str,
    task_id: str | None,
    assigned_participant: str | None,
    creator_actor: str | None,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA_ID,
        "status": "BLOCKED",
        "reason_code": reason_code,
        "task_id": task_id,
        "assigned_participant": assigned_participant,
        "creator_actor": creator_actor,
        "validated_task": None,
        "source_binding": {
            "relative_path": ORCHESTRATOR_RELATIVE_PATH,
            "sha256": ORCHESTRATOR_SHA256,
            "validator": "validate_task",
        },
        "ordinary_chat_blocked": False,
        "action_authority": ACTION_AUTHORITY,
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


def _prepared_identity(
    prepared: dict[str, Any],
) -> tuple[str | None, str | None, str | None]:
    seed = prepared.get("task_seed")
    task_id: str | None = None
    if isinstance(seed, dict):
        value = seed.get("task_id")
        if isinstance(value, str) and value.strip():
            task_id = value.strip()

    participant = prepared.get("assigned_participant")
    actor = prepared.get("creator_actor")
    participant_value = (
        participant.strip()
        if isinstance(participant, str) and participant.strip()
        else None
    )
    actor_value = (
        actor.strip()
        if isinstance(actor, str) and actor.strip()
        else None
    )
    return task_id, participant_value, actor_value


def _validate_ingress_safety(prepared: dict[str, Any]) -> None:
    expected = {
        "ordinary_chat_blocked": False,
        "action_authority": "NONE",
        "orchestrator_evaluate": False,
        "agent_core_execution": False,
        "model_inference": False,
        "network": False,
        "runtime_write": False,
    }
    for field, value in expected.items():
        if prepared.get(field) != value:
            raise OrchestratorPolicyAdapterError(
                "INGRESS_SAFETY_FIELD_DRIFT:" + field
            )


def _map_task(prepared: dict[str, Any]) -> dict[str, Any]:
    seed = prepared.get("task_seed")
    if not isinstance(seed, dict):
        raise OrchestratorPolicyAdapterError("TASK_SEED_NOT_OBJECT")

    task_id = seed.get("task_id")
    ready_core = seed.get("ready_core")
    verified_context = seed.get("verified_context")

    if not isinstance(task_id, str) or not task_id.strip():
        raise OrchestratorPolicyAdapterError("TASK_ID_INVALID")
    if not isinstance(ready_core, dict):
        raise OrchestratorPolicyAdapterError("READY_CORE_NOT_OBJECT")
    if not isinstance(verified_context, dict):
        raise OrchestratorPolicyAdapterError("VERIFIED_CONTEXT_NOT_OBJECT")

    missing = [
        field
        for field in IDEKOMPASS_REQUIRED
        if field != "task_id" and field not in ready_core
    ]
    if missing:
        raise OrchestratorPolicyAdapterError(
            "READY_CORE_FIELD_MISSING:" + missing[0]
        )

    participant = prepared.get("assigned_participant")
    actor = prepared.get("creator_actor")
    if not isinstance(participant, str) or not participant.strip():
        raise OrchestratorPolicyAdapterError(
            "ASSIGNED_PARTICIPANT_REQUIRED"
        )
    if not isinstance(actor, str) or not actor.strip():
        raise OrchestratorPolicyAdapterError("CREATOR_ACTOR_REQUIRED")

    task = copy.deepcopy(ready_core)
    task["task_id"] = task_id.strip()
    task["first_gate"] = FIRST_GATE
    task["assigned_participant"] = participant.strip()
    task["creator_actor"] = actor.strip()
    task["verified_context"] = copy.deepcopy(verified_context)
    task["historical_context"] = {}
    task["rights_expansion"] = False
    requested_effects = ready_core.get("requested_effects", {})
    if not isinstance(requested_effects, dict):
        raise OrchestratorPolicyAdapterError(
            "REQUESTED_EFFECTS_NOT_OBJECT"
        )
    task["task_scoped_scope_authority"] = "ALL_TASK_SCOPED_EFFECTS"
    task["requested_effects"] = {
        effect: bool(requested_effects.get(effect, False))
        for effect in TASK_SCOPED_EFFECTS
    }
    task["requested_effects"]["unbounded_background_autonomy"] = False
    return task


def validate_prepared_task(
    prepared: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(prepared, dict):
        return _blocked_result(
            reason_code="PREPARED_NOT_OBJECT",
            task_id=None,
            assigned_participant=None,
            creator_actor=None,
        )

    task_id, participant, actor = _prepared_identity(prepared)

    if prepared.get("status") != "CONDITIONAL":
        reason = prepared.get("reason_code")
        return _blocked_result(
            reason_code=(
                reason
                if isinstance(reason, str) and reason
                else "INGRESS_NOT_CONDITIONAL"
            ),
            task_id=task_id,
            assigned_participant=participant,
            creator_actor=actor,
        )

    if (
        prepared.get("reason_code")
        != "ORCHESTRATOR_POLICY_VALIDATION_REQUIRED"
    ):
        return _blocked_result(
            reason_code="INGRESS_POLICY_BOUNDARY_DRIFT",
            task_id=task_id,
            assigned_participant=participant,
            creator_actor=actor,
        )

    module: ModuleType | None = None

    try:
        _validate_ingress_safety(prepared)
        task = _map_task(prepared)
        module = _load_orchestrator()
        module.validate_task(copy.deepcopy(task))
    except OrchestratorPolicyAdapterError as exc:
        return _blocked_result(
            reason_code=str(exc),
            task_id=task_id,
            assigned_participant=participant,
            creator_actor=actor,
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
            else "VALIDATE_TASK_RUNTIME_ERROR:" + type(exc).__name__
        )
        return _blocked_result(
            reason_code=reason_code,
            task_id=task_id,
            assigned_participant=participant,
            creator_actor=actor,
        )

    return {
        "schema": SCHEMA_ID,
        "status": "VALIDATED",
        "reason_code": "VALIDATE_TASK_PASS",
        "task_id": task["task_id"],
        "assigned_participant": task["assigned_participant"],
        "creator_actor": task["creator_actor"],
        "validated_task": copy.deepcopy(task),
        "source_binding": {
            "relative_path": ORCHESTRATOR_RELATIVE_PATH,
            "sha256": ORCHESTRATOR_SHA256,
            "validator": "validate_task",
        },
        "ordinary_chat_blocked": False,
        "action_authority": ACTION_AUTHORITY,
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
