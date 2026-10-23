from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any


PROPOSAL_SCHEMA = "gg.idekompass.initiative-proposal.v1"
SET_SCHEMA = "gg.idekompass.initiative-proposal-set.v1"

CLASSIFICATIONS = (
    "DO_NOW",
    "PROPOSE_TO_USER",
    "FUTURE_IMPROVEMENT",
    "IRRELEVANT_NOW",
)

KINDS = (
    "INFORMATION",
    "ACTION",
    "IMPROVEMENT",
)

RELEVANCE = (
    "BLOCKING",
    "DIRECT",
    "OPTIONAL",
    "OUT_OF_SCOPE",
)

INFORMATION_VALUE = (
    "HIGH",
    "MEDIUM",
    "LOW",
    "NONE",
)

RISK_CLASSES = (
    "GREEN",
    "YELLOW",
    "RED",
)

COST_RANKS = (
    "LOW",
    "MEDIUM",
    "HIGH",
)

MANDATE_REQUIREMENTS = (
    "NOT_REQUIRED",
    "EXPLICIT_REQUIRED",
    "UNKNOWN",
)

ACTION_AUTHORITY = "NONE"
AUTOMATIC_EXECUTION = False
TASK_CREATION = False
CAPABILITY_EXECUTION = False
PARTICIPANT_EXECUTION = False
MODEL_OUTPUT_AS_EVIDENCE = False

_SHA_RE = re.compile(r"[0-9a-f]{64}")

_CANDIDATE_FIELDS = frozenset(
    (
        "candidate_id",
        "description",
        "kind",
        "parent_goal_sha256",
        "relevance",
        "information_value",
        "risk_class",
        "reversible",
        "cost_rank",
        "mandate_requirement",
        "persistent_write",
        "network",
        "sudo",
        "source",
    )
)


class InitiativeProposalError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise InitiativeProposalError(
            "INITIATIVE_NOT_CANONICAL_JSON"
        ) from exc


def _sha(value: Any) -> str:
    return hashlib.sha256(
        _canonical(value)
    ).hexdigest()


def _text(
    value: Any,
    name: str,
    *,
    maximum: int = 4096,
) -> str:
    if not isinstance(value, str):
        raise InitiativeProposalError(
            name + "_NOT_TEXT"
        )

    normalized = " ".join(
        value.split()
    )

    if (
        not normalized
        or len(normalized) > maximum
    ):
        raise InitiativeProposalError(
            name + "_INVALID"
        )

    return normalized


def _sha_text(
    value: Any,
    name: str,
) -> str:
    result = _text(
        value,
        name,
        maximum=64,
    )

    if _SHA_RE.fullmatch(result) is None:
        raise InitiativeProposalError(
            name + "_INVALID"
        )

    return result


def _enum(
    value: Any,
    name: str,
    allowed: tuple[str, ...],
) -> str:
    result = _text(
        value,
        name,
        maximum=128,
    )

    if result not in allowed:
        raise InitiativeProposalError(
            name + "_INVALID"
        )

    return result


def _bool(
    value: Any,
    name: str,
) -> bool:
    if not isinstance(value, bool):
        raise InitiativeProposalError(
            name + "_NOT_BOOL"
        )

    return value


def _effect_requested(
    value: Any,
) -> bool:
    if isinstance(value, bool):
        return value

    if value is None:
        return False

    normalized = str(value).strip().upper()

    return normalized not in {
        "",
        "0",
        "FALSE",
        "NO",
        "NONE",
        "READ_ONLY",
        "READ-ONLY",
    }


def goal_chain_sha256(
    goal_chain: Any,
) -> str:
    return _sha(goal_chain)


def _candidate(
    value: Any,
) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value) != _CANDIDATE_FIELDS
    ):
        raise InitiativeProposalError(
            "INITIATIVE_CANDIDATE_SURFACE_INVALID"
        )

    candidate = copy.deepcopy(value)

    candidate["candidate_id"] = _text(
        candidate["candidate_id"],
        "CANDIDATE_ID",
        maximum=256,
    )
    candidate["description"] = _text(
        candidate["description"],
        "DESCRIPTION",
    )
    candidate["kind"] = _enum(
        candidate["kind"],
        "KIND",
        KINDS,
    )
    candidate["parent_goal_sha256"] = (
        _sha_text(
            candidate["parent_goal_sha256"],
            "PARENT_GOAL_SHA256",
        )
    )
    candidate["relevance"] = _enum(
        candidate["relevance"],
        "RELEVANCE",
        RELEVANCE,
    )
    candidate["information_value"] = (
        _enum(
            candidate["information_value"],
            "INFORMATION_VALUE",
            INFORMATION_VALUE,
        )
    )
    candidate["risk_class"] = _enum(
        candidate["risk_class"],
        "RISK_CLASS",
        RISK_CLASSES,
    )
    candidate["reversible"] = _bool(
        candidate["reversible"],
        "REVERSIBLE",
    )
    candidate["cost_rank"] = _enum(
        candidate["cost_rank"],
        "COST_RANK",
        COST_RANKS,
    )
    candidate["mandate_requirement"] = (
        _enum(
            candidate["mandate_requirement"],
            "MANDATE_REQUIREMENT",
            MANDATE_REQUIREMENTS,
        )
    )
    candidate["persistent_write"] = _bool(
        candidate["persistent_write"],
        "PERSISTENT_WRITE",
    )
    candidate["network"] = _bool(
        candidate["network"],
        "NETWORK",
    )
    candidate["sudo"] = _bool(
        candidate["sudo"],
        "SUDO",
    )
    candidate["source"] = _text(
        candidate["source"],
        "SOURCE",
        maximum=512,
    )

    return candidate


def _classification(
    candidate: dict[str, Any],
    parent_goal_sha256: str,
) -> str:
    if (
        candidate["parent_goal_sha256"]
        != parent_goal_sha256
        or candidate["relevance"]
        == "OUT_OF_SCOPE"
    ):
        return "IRRELEVANT_NOW"

    authority_sensitive = (
        candidate["risk_class"]
        in {
            "YELLOW",
            "RED",
        }
        or candidate[
            "mandate_requirement"
        ]
        in {
            "EXPLICIT_REQUIRED",
            "UNKNOWN",
        }
        or candidate["persistent_write"]
        or candidate["network"]
        or candidate["sudo"]
    )

    if authority_sensitive:
        return "PROPOSE_TO_USER"

    if (
        candidate["kind"]
        == "INFORMATION"
        and candidate["relevance"]
        == "BLOCKING"
        and candidate[
            "information_value"
        ]
        == "HIGH"
        and candidate["cost_rank"]
        == "LOW"
        and candidate["reversible"]
        is True
    ):
        return "DO_NOW"

    if candidate["kind"] == "ACTION":
        return "PROPOSE_TO_USER"

    if candidate["relevance"] in {
        "DIRECT",
        "OPTIONAL",
        "BLOCKING",
    }:
        return "FUTURE_IMPROVEMENT"

    return "IRRELEVANT_NOW"


def classify_candidates(
    *,
    task_id: str,
    goal_chain: Any,
    state_base_revision: str,
    candidates: list[dict[str, Any]]
    | tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    task = _text(
        task_id,
        "TASK_ID",
        maximum=4096,
    )
    state_revision = _sha_text(
        state_base_revision,
        "STATE_BASE_REVISION",
    )
    parent_goal = goal_chain_sha256(
        goal_chain
    )

    if not isinstance(
        candidates,
        (list, tuple),
    ):
        raise InitiativeProposalError(
            "INITIATIVE_CANDIDATES_NOT_SEQUENCE"
        )

    if len(candidates) > 64:
        raise InitiativeProposalError(
            "INITIATIVE_CANDIDATE_BUDGET_EXCEEDED"
        )

    normalized = [
        _candidate(value)
        for value in candidates
    ]

    candidate_ids = [
        item["candidate_id"]
        for item in normalized
    ]

    if len(candidate_ids) != len(
        set(candidate_ids)
    ):
        raise InitiativeProposalError(
            "INITIATIVE_CANDIDATE_ID_DUPLICATE"
        )

    proposals = []

    for candidate in normalized:
        classification = _classification(
            candidate,
            parent_goal,
        )

        proposal = {
            "schema": PROPOSAL_SCHEMA,
            **copy.deepcopy(candidate),
            "classification":
                classification,
            "automatic_execution":
                AUTOMATIC_EXECUTION,
            "creates_task":
                TASK_CREATION,
            "action_authority":
                ACTION_AUTHORITY,
            "capability_execution":
                CAPABILITY_EXECUTION,
            "participant_execution":
                PARTICIPANT_EXECUTION,
            "model_output_as_evidence":
                MODEL_OUTPUT_AS_EVIDENCE,
        }

        proposal[
            "proposal_binding_sha256"
        ] = _sha(proposal)

        proposals.append(proposal)

    rank = {
        "DO_NOW": 0,
        "PROPOSE_TO_USER": 1,
        "FUTURE_IMPROVEMENT": 2,
        "IRRELEVANT_NOW": 3,
    }

    proposals.sort(
        key=lambda item: (
            rank[item["classification"]],
            item["candidate_id"],
        )
    )

    primary = (
        proposals[0]
        if proposals
        else None
    )

    result = {
        "schema": SET_SCHEMA,
        "task_id": task,
        "parent_goal_sha256":
            parent_goal,
        "state_base_revision":
            state_revision,
        "classifications":
            list(CLASSIFICATIONS),
        "proposal_count":
            len(proposals),
        "proposals":
            proposals,
        "primary_proposal_id": (
            primary["candidate_id"]
            if primary is not None
            else None
        ),
        "primary_classification": (
            primary["classification"]
            if primary is not None
            else None
        ),
        "automatic_execution":
            AUTOMATIC_EXECUTION,
        "task_creation":
            TASK_CREATION,
        "action_authority":
            ACTION_AUTHORITY,
        "capability_execution":
            CAPABILITY_EXECUTION,
        "participant_execution":
            PARTICIPANT_EXECUTION,
        "persistent_write": False,
        "network": False,
        "sudo": False,
        "model_output_as_evidence":
            MODEL_OUTPUT_AS_EVIDENCE,
    }

    result["binding_sha256"] = _sha(
        result
    )

    return result


def derive_from_decision(
    *,
    task_id: str,
    goal_chain: Any,
    state_base_revision: str,
    decision_kind: str,
    reason_code: str,
    selected_action_node_id: Any,
    information_options: list[dict[str, Any]]
    | tuple[dict[str, Any], ...],
    action_proposal: dict[str, Any] | None,
) -> dict[str, Any]:
    decision = _text(
        decision_kind,
        "DECISION_KIND",
        maximum=128,
    )
    reason = _text(
        reason_code,
        "REASON_CODE",
        maximum=1024,
    )
    parent_goal = goal_chain_sha256(
        goal_chain
    )

    if not isinstance(
        information_options,
        (list, tuple),
    ):
        raise InitiativeProposalError(
            "INFORMATION_OPTIONS_NOT_SEQUENCE"
        )

    candidates: list[
        dict[str, Any]
    ] = []

    for index, option in enumerate(
        information_options
    ):
        if not isinstance(option, dict):
            raise InitiativeProposalError(
                "INFORMATION_OPTION_NOT_OBJECT"
            )

        description = _text(
            option.get("description"),
            "INFORMATION_DESCRIPTION",
        )

        cost = str(
            option.get(
                "cost_rank",
                "HIGH",
            )
        ).strip().upper()

        if cost not in COST_RANKS:
            cost = "HIGH"

        blocking = decision in {
            "GATHER_INFORMATION",
            "STOP_UNCERTAINTY",
        }

        material = {
            "index": index,
            "description": description,
            "kind": str(
                option.get(
                    "kind",
                    "OBSERVE_MORE",
                )
            ),
            "decision": decision,
            "reason": reason,
        }

        candidates.append(
            {
                "candidate_id":
                    "initiative-info-"
                    + _sha(material)[:24],
                "description":
                    description,
                "kind":
                    "INFORMATION",
                "parent_goal_sha256":
                    parent_goal,
                "relevance": (
                    "BLOCKING"
                    if blocking
                    else "OPTIONAL"
                ),
                "information_value": (
                    "HIGH"
                    if blocking
                    else "MEDIUM"
                ),
                "risk_class":
                    "GREEN",
                "reversible":
                    True,
                "cost_rank":
                    cost,
                "mandate_requirement":
                    "NOT_REQUIRED",
                "persistent_write":
                    False,
                "network":
                    False,
                "sudo":
                    False,
                "source":
                    "IDEKOMPASS_INFORMATION_OPTION:"
                    + str(
                        option.get(
                            "kind",
                            "OBSERVE_MORE",
                        )
                    )[:128],
            }
        )

    if selected_action_node_id is not None:
        node_id = _text(
            str(selected_action_node_id),
            "SELECTED_ACTION_NODE_ID",
            maximum=512,
        )

        risk = "GREEN"
        persistent_write = False
        network = False
        sudo = False

        if action_proposal is not None:
            if not isinstance(
                action_proposal,
                dict,
            ):
                raise InitiativeProposalError(
                    "ACTION_PROPOSAL_NOT_OBJECT"
                )

            proposal_risk = str(
                action_proposal.get(
                    "risk_floor",
                    "GREEN",
                )
            ).strip().upper()

            if proposal_risk in RISK_CLASSES:
                risk = proposal_risk
            else:
                risk = "RED"

            persistent_write = (
                _effect_requested(
                    action_proposal.get(
                        "persistent_write"
                    )
                )
            )
            network = _effect_requested(
                action_proposal.get(
                    "network"
                )
            )
            sudo = _effect_requested(
                action_proposal.get(
                    "sudo"
                )
            )

        action_material = {
            "node_id": node_id,
            "decision": decision,
            "reason": reason,
            "risk": risk,
            "persistent_write":
                persistent_write,
            "network": network,
            "sudo": sudo,
        }

        candidates.append(
            {
                "candidate_id":
                    "initiative-action-"
                    + _sha(
                        action_material
                    )[:24],
                "description": (
                    "Review the current "
                    "Idékompass action "
                    "candidate before any "
                    "execution: "
                    + node_id
                ),
                "kind":
                    "ACTION",
                "parent_goal_sha256":
                    parent_goal,
                "relevance":
                    "DIRECT",
                "information_value":
                    "NONE",
                "risk_class":
                    risk,
                "reversible":
                    False,
                "cost_rank":
                    "MEDIUM",
                "mandate_requirement":
                    "UNKNOWN",
                "persistent_write":
                    persistent_write,
                "network":
                    network,
                "sudo":
                    sudo,
                "source":
                    "IDEKOMPASS_COGNITIVE_ACTION_NODE",
            }
        )

    return classify_candidates(
        task_id=task_id,
        goal_chain=goal_chain,
        state_base_revision=state_base_revision,
        candidates=candidates,
    )
