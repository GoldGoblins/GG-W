from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any


PROPOSAL_SCHEMA = "gg.action-proposal.v1"
INTENT_SCHEMA = "gg.action-intent.v1"
ACTION_AUTHORITY = "NONE"
RISK_CLASSES = ("GREEN", "YELLOW", "RED")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,128}$")

_PROPOSAL_FIELDS = frozenset(
    {
        "schema",
        "capability_human_id",
        "capability_contract_sha256",
        "capability_execution_revision_sha256",
        "capability_metadata_sha256",
        "target_object_id",
        "target_source_revision",
        "effect_class",
        "risk_floor",
        "persistent_write",
        "model_inference",
        "network",
        "sudo",
        "capability_execution_profile_requirement",
        "action_authority",
        "proposal_binding_sha256",
    }
)

_INTENT_FIELDS = frozenset(
    {
        "schema",
        "task_id",
        "origin_id",
        "state_base_revision",
        "goal_chain_sha256",
        "capability_action_node_id",
        "action_trace_sha256",
        "capability_human_id",
        "capability_contract_sha256",
        "capability_execution_revision_sha256",
        "capability_metadata_sha256",
        "target_object_id",
        "target_source_revision",
        "effect_class",
        "risk_floor",
        "persistent_write",
        "model_inference",
        "network",
        "sudo",
        "capability_execution_profile_requirement",
        "action_authority",
        "proposal_binding_sha256",
        "binding_sha256",
    }
)


class ActionIntentContractError(ValueError):
    pass


def _canonical_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sha(value: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _text(value: Any, field: str, *, max_length: int = 4096) -> str:
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise ActionIntentContractError(field + "_INVALID")
    return value


def _identifier(value: Any, field: str) -> str:
    text = _text(value, field, max_length=128)
    if _ID_RE.fullmatch(text) is None:
        raise ActionIntentContractError(field + "_INVALID")
    return text


def _sha_text(value: Any, field: str) -> str:
    text = _text(value, field, max_length=64)
    if _SHA_RE.fullmatch(text) is None:
        raise ActionIntentContractError(field + "_INVALID")
    return text


def _record_dict(capability_record: Any) -> dict[str, Any]:
    if isinstance(capability_record, dict):
        value = copy.deepcopy(capability_record)
    else:
        as_dict = getattr(capability_record, "as_dict", None)
        if not callable(as_dict):
            raise ActionIntentContractError("CAPABILITY_RECORD_INVALID")
        value = copy.deepcopy(as_dict())

    if not isinstance(value, dict):
        raise ActionIntentContractError("CAPABILITY_RECORD_INVALID")
    return value


def _proposal_material(proposal: dict[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(proposal[key])
        for key in sorted(_PROPOSAL_FIELDS - {"proposal_binding_sha256"})
    }


def make_action_proposal(
    *,
    route_primary_capability: str,
    capability_record: Any,
    target_object_id: str,
    target_source_revision: str,
) -> dict[str, Any]:
    record = _record_dict(capability_record)
    human_id = _identifier(record.get("human_id"), "CAPABILITY_HUMAN_ID")

    if route_primary_capability != human_id:
        raise ActionIntentContractError("ROUTE_CAPABILITY_BINDING_MISMATCH")

    contract = record.get("contract")
    if not isinstance(contract, dict):
        raise ActionIntentContractError("CAPABILITY_CONTRACT_INVALID")

    risk_floor = contract.get("risk_floor")
    if risk_floor not in RISK_CLASSES:
        raise ActionIntentContractError("CAPABILITY_RISK_FLOOR_INVALID")

    model_inference = contract.get("model_inference")
    if not isinstance(model_inference, bool):
        raise ActionIntentContractError("CAPABILITY_MODEL_INFERENCE_INVALID")

    proposal: dict[str, Any] = {
        "schema": PROPOSAL_SCHEMA,
        "capability_human_id": human_id,
        "capability_contract_sha256": _sha_text(
            record.get("contract_sha256"),
            "CAPABILITY_CONTRACT_SHA256",
        ),
        "capability_execution_revision_sha256": _sha_text(
            record.get("execution_revision_sha256"),
            "CAPABILITY_EXECUTION_REVISION_SHA256",
        ),
        "capability_metadata_sha256": _sha_text(
            record.get("metadata_sha256"),
            "CAPABILITY_METADATA_SHA256",
        ),
        "target_object_id": _identifier(
            target_object_id,
            "TARGET_OBJECT_ID",
        ),
        "target_source_revision": _sha_text(
            target_source_revision,
            "TARGET_SOURCE_REVISION",
        ),
        "effect_class": _identifier(
            contract.get("effect_class"),
            "EFFECT_CLASS",
        ),
        "risk_floor": risk_floor,
        "persistent_write": _text(
            contract.get("persistent_write"),
            "PERSISTENT_WRITE",
            max_length=128,
        ),
        "model_inference": model_inference,
        "network": _text(
            contract.get("network"),
            "NETWORK",
            max_length=128,
        ),
        "sudo": _text(
            contract.get("sudo"),
            "SUDO",
            max_length=128,
        ),
        "capability_execution_profile_requirement": _text(
            contract.get("execution_authority"),
            "CAPABILITY_EXECUTION_PROFILE_REQUIREMENT",
            max_length=128,
        ),
        "action_authority": ACTION_AUTHORITY,
    }
    proposal["proposal_binding_sha256"] = _sha(proposal)
    return validate_action_proposal(proposal)


def validate_action_proposal(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _PROPOSAL_FIELDS:
        raise ActionIntentContractError("ACTION_PROPOSAL_SURFACE_INVALID")

    proposal = copy.deepcopy(value)

    if proposal.get("schema") != PROPOSAL_SCHEMA:
        raise ActionIntentContractError("ACTION_PROPOSAL_SCHEMA_INVALID")

    _identifier(proposal.get("capability_human_id"), "CAPABILITY_HUMAN_ID")
    _sha_text(
        proposal.get("capability_contract_sha256"),
        "CAPABILITY_CONTRACT_SHA256",
    )
    _sha_text(
        proposal.get("capability_execution_revision_sha256"),
        "CAPABILITY_EXECUTION_REVISION_SHA256",
    )
    _sha_text(
        proposal.get("capability_metadata_sha256"),
        "CAPABILITY_METADATA_SHA256",
    )
    _identifier(proposal.get("target_object_id"), "TARGET_OBJECT_ID")
    _sha_text(
        proposal.get("target_source_revision"),
        "TARGET_SOURCE_REVISION",
    )
    _identifier(proposal.get("effect_class"), "EFFECT_CLASS")

    if proposal.get("risk_floor") not in RISK_CLASSES:
        raise ActionIntentContractError("CAPABILITY_RISK_FLOOR_INVALID")
    if not isinstance(proposal.get("model_inference"), bool):
        raise ActionIntentContractError("CAPABILITY_MODEL_INFERENCE_INVALID")

    _text(proposal.get("persistent_write"), "PERSISTENT_WRITE", max_length=128)
    _text(proposal.get("network"), "NETWORK", max_length=128)
    _text(proposal.get("sudo"), "SUDO", max_length=128)
    _text(
        proposal.get("capability_execution_profile_requirement"),
        "CAPABILITY_EXECUTION_PROFILE_REQUIREMENT",
        max_length=128,
    )

    if proposal.get("action_authority") != ACTION_AUTHORITY:
        raise ActionIntentContractError("ACTION_AUTHORITY_EXPANDED")

    actual = _sha_text(
        proposal.get("proposal_binding_sha256"),
        "PROPOSAL_BINDING_SHA256",
    )
    expected = _sha(_proposal_material(proposal))
    if actual != expected:
        raise ActionIntentContractError("ACTION_PROPOSAL_BINDING_MISMATCH")

    return proposal


def bind_action_intent(
    *,
    action_proposal: dict[str, Any],
    task_id: str,
    origin_id: str,
    state_base_revision: str,
    goal_chain_sha256: str,
    action_trace_sha256: str,
) -> dict[str, Any]:
    proposal = validate_action_proposal(action_proposal)

    intent: dict[str, Any] = {
        "schema": INTENT_SCHEMA,
        "task_id": _identifier(task_id, "TASK_ID"),
        "origin_id": _identifier(origin_id, "ORIGIN_ID"),
        "state_base_revision": _sha_text(
            state_base_revision,
            "STATE_BASE_REVISION",
        ),
        "goal_chain_sha256": _sha_text(
            goal_chain_sha256,
            "GOAL_CHAIN_SHA256",
        ),
        "capability_action_node_id": (
            "capability-action-"
            + proposal["proposal_binding_sha256"][:32]
        ),
        "action_trace_sha256": _sha_text(
            action_trace_sha256,
            "ACTION_TRACE_SHA256",
        ),
        **{
            key: copy.deepcopy(proposal[key])
            for key in (
                "capability_human_id",
                "capability_contract_sha256",
                "capability_execution_revision_sha256",
                "capability_metadata_sha256",
                "target_object_id",
                "target_source_revision",
                "effect_class",
                "risk_floor",
                "persistent_write",
                "model_inference",
                "network",
                "sudo",
                "capability_execution_profile_requirement",
                "action_authority",
                "proposal_binding_sha256",
            )
        },
    }
    intent["binding_sha256"] = _sha(intent)
    return validate_action_intent(intent)


def validate_action_intent(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _INTENT_FIELDS:
        raise ActionIntentContractError("ACTION_INTENT_SURFACE_INVALID")

    intent = copy.deepcopy(value)

    if intent.get("schema") != INTENT_SCHEMA:
        raise ActionIntentContractError("ACTION_INTENT_SCHEMA_INVALID")

    for field in ("task_id", "origin_id", "capability_human_id"):
        _identifier(intent.get(field), field.upper())

    _identifier(
        intent.get("capability_action_node_id"),
        "CAPABILITY_ACTION_NODE_ID",
    )
    _identifier(intent.get("target_object_id"), "TARGET_OBJECT_ID")
    _identifier(intent.get("effect_class"), "EFFECT_CLASS")

    for field in (
        "state_base_revision",
        "goal_chain_sha256",
        "action_trace_sha256",
        "capability_contract_sha256",
        "capability_execution_revision_sha256",
        "capability_metadata_sha256",
        "target_source_revision",
        "proposal_binding_sha256",
        "binding_sha256",
    ):
        _sha_text(intent.get(field), field.upper())

    if intent.get("risk_floor") not in RISK_CLASSES:
        raise ActionIntentContractError("CAPABILITY_RISK_FLOOR_INVALID")
    if not isinstance(intent.get("model_inference"), bool):
        raise ActionIntentContractError("CAPABILITY_MODEL_INFERENCE_INVALID")
    if intent.get("action_authority") != ACTION_AUTHORITY:
        raise ActionIntentContractError("ACTION_AUTHORITY_EXPANDED")

    _text(intent.get("persistent_write"), "PERSISTENT_WRITE", max_length=128)
    _text(intent.get("network"), "NETWORK", max_length=128)
    _text(intent.get("sudo"), "SUDO", max_length=128)
    _text(
        intent.get("capability_execution_profile_requirement"),
        "CAPABILITY_EXECUTION_PROFILE_REQUIREMENT",
        max_length=128,
    )

    material = {
        key: copy.deepcopy(intent[key])
        for key in sorted(_INTENT_FIELDS - {"binding_sha256"})
    }
    if intent["binding_sha256"] != _sha(material):
        raise ActionIntentContractError("ACTION_INTENT_BINDING_MISMATCH")

    return intent
