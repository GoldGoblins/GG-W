from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from backend import autonomy_cognitive_adapter as cognitive


EPISODE_SCHEMA = "gg.workbench.episodic-experience.v1"
CANDIDATE_SCHEMA = "gg.workbench.learning-candidate.v1"
REVIEW_SCHEMA = "gg.workbench.learning-review.v1"
APPROVAL_SCHEMA = "gg.workbench.learning-promotion-approval.v1"
PROMOTED_SCHEMA = "gg.workbench.promoted-memory.v1"
FRESHNESS_SCHEMA = "gg.workbench.memory-freshness.v1"

SEMANTIC_CLOSURE_SCHEMA = "gg.semantic-closure-result.v1"
LEARNING_HANDOFF_SCHEMA = "gg.semantic-learning-handoff.v1"

ACTION_AUTHORITY = "NONE"
NETWORK_AUTHORITY = "NONE"
CANONICAL_POLICY_CHANGE = False
MODEL_OUTPUT_AS_EVIDENCE = False

MEMORY_CLASSES = frozenset(
    {
        "PROJECT_MEMORY",
        "PROCEDURAL_MEMORY",
    }
)

INPUT_CLASSES = frozenset(
    {
        "VERIFIED_SUCCESS",
        "VERIFIED_FAILURE",
        "CONFLICT",
        "UNKNOWN",
    }
)


class LearningMemoryError(RuntimeError):
    pass


def canonical_json(
    value: object,
) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def digest_json(
    value: object,
) -> str:
    return hashlib.sha256(
        canonical_json(
            value
        ).encode(
            "utf-8"
        )
    ).hexdigest()


def _mapping(
    value: object,
    label: str,
) -> Mapping[str, Any]:
    if not isinstance(
        value,
        Mapping,
    ):
        raise LearningMemoryError(
            label + "_NOT_MAPPING"
        )

    return value


def _text(
    value: object,
    label: str,
    *,
    maximum: int = 4096,
) -> str:
    if not isinstance(
        value,
        str,
    ):
        raise LearningMemoryError(
            label + "_NOT_TEXT"
        )

    result = value.strip()

    if (
        not result
        or len(result) > maximum
    ):
        raise LearningMemoryError(
            label + "_INVALID"
        )

    return result


def _sha(
    value: object,
    label: str,
) -> str:
    result = _text(
        value,
        label,
        maximum=64,
    )

    if (
        len(result) != 64
        or any(
            ch
            not in
            "0123456789abcdef"
            for ch in result
        )
    ):
        raise LearningMemoryError(
            label + "_NOT_SHA256"
        )

    return result


def _bool(
    value: object,
    label: str,
) -> bool:
    if type(value) is not bool:
        raise LearningMemoryError(
            label + "_NOT_BOOL"
        )

    return value


def _string_sequence(
    value: object,
    label: str,
    *,
    allow_empty: bool,
) -> list[str]:
    if (
        not isinstance(
            value,
            Sequence,
        )
        or isinstance(
            value,
            (
                str,
                bytes,
                bytearray,
            ),
        )
    ):
        raise LearningMemoryError(
            label + "_NOT_SEQUENCE"
        )

    result: list[str] = []

    for index, item in enumerate(
        value
    ):
        result.append(
            _text(
                item,
                label
                + "_"
                + str(index),
            )
        )

    if (
        not allow_empty
        and not result
    ):
        raise LearningMemoryError(
            label + "_EMPTY"
        )

    if (
        len(
            set(result)
        )
        != len(result)
    ):
        raise LearningMemoryError(
            label + "_DUPLICATE"
        )

    return result


def _sha_sequence(
    value: object,
    label: str,
    *,
    allow_empty: bool,
) -> list[str]:
    raw = _string_sequence(
        value,
        label,
        allow_empty=allow_empty,
    )

    return [
        _sha(
            item,
            label + "_SHA",
        )
        for item in raw
    ]


def _validate_episode(
    value: object,
) -> dict[str, Any]:
    episode = dict(
        _mapping(
            value,
            "EPISODE",
        )
    )

    if (
        episode.get(
            "schema"
        )
        != EPISODE_SCHEMA
    ):
        raise LearningMemoryError(
            "EPISODE_SCHEMA_INVALID"
        )

    _text(
        episode.get(
            "task_id"
        ),
        "EPISODE_TASK_ID",
        maximum=256,
    )

    _text(
        episode.get(
            "origin_id"
        ),
        "EPISODE_ORIGIN_ID",
        maximum=256,
    )

    _text(
        episode.get(
            "goal"
        ),
        "EPISODE_GOAL",
    )

    _text(
        episode.get(
            "state_base_revision"
        ),
        "EPISODE_STATE_BASE_REVISION",
        maximum=256,
    )

    _sha(
        episode.get(
            "source_sha256"
        ),
        "EPISODE_SOURCE_SHA256",
    )

    _sha(
        episode.get(
            "semantic_closure_sha256"
        ),
        "EPISODE_CLOSURE_SHA256",
    )

    input_class = _text(
        episode.get(
            "input_class"
        ),
        "EPISODE_INPUT_CLASS",
        maximum=64,
    )

    if (
        input_class
        not in INPUT_CLASSES
    ):
        raise LearningMemoryError(
            "EPISODE_INPUT_CLASS_INVALID"
        )

    _bool(
        episode.get(
            "candidate_eligible"
        ),
        "EPISODE_CANDIDATE_ELIGIBLE",
    )

    if (
        episode.get(
            "promotion_authority"
        )
        != "NONE"
        or episode.get(
            "action_authority"
        )
        != "NONE"
        or episode.get(
            "network_authority"
        )
        != "NONE"
        or episode.get(
            "canonical_policy_change"
        )
        is not False
        or episode.get(
            "model_output_as_evidence"
        )
        is not False
    ):
        raise LearningMemoryError(
            "EPISODE_AUTHORITY_DRIFT"
        )

    return episode


def build_episodic_experience(
    *,
    task_id: str,
    origin_id: str,
    goal: str,
    state_base_revision: str,
    source_sha256: str,
    semantic_closure: Mapping[
        str,
        Any,
    ],
    learning_handoff: Mapping[
        str,
        Any,
    ],
) -> dict[str, Any]:
    task = _text(
        task_id,
        "TASK_ID",
        maximum=256,
    )

    origin = _text(
        origin_id,
        "ORIGIN_ID",
        maximum=256,
    )

    goal_text = _text(
        goal,
        "GOAL",
    )

    state_base = _text(
        state_base_revision,
        "STATE_BASE_REVISION",
        maximum=256,
    )

    source_sha = _sha(
        source_sha256,
        "SOURCE_SHA256",
    )

    closure = dict(
        _mapping(
            semantic_closure,
            "SEMANTIC_CLOSURE",
        )
    )

    handoff = dict(
        _mapping(
            learning_handoff,
            "LEARNING_HANDOFF",
        )
    )

    if (
        closure.get(
            "schema"
        )
        != SEMANTIC_CLOSURE_SCHEMA
    ):
        raise LearningMemoryError(
            "SEMANTIC_CLOSURE_SCHEMA_INVALID"
        )

    if (
        handoff.get(
            "schema"
        )
        != LEARNING_HANDOFF_SCHEMA
    ):
        raise LearningMemoryError(
            "LEARNING_HANDOFF_SCHEMA_INVALID"
        )

    closure_sha = digest_json(
        closure
    )

    if (
        handoff.get(
            "semantic_closure_sha256"
        )
        != closure_sha
    ):
        raise LearningMemoryError(
            "LEARNING_HANDOFF_CLOSURE_BINDING_MISMATCH"
        )

    if (
        closure.get(
            "source_sha256"
        )
        != source_sha
    ):
        raise LearningMemoryError(
            "EPISODE_SOURCE_BINDING_MISMATCH"
        )

    input_class = _text(
        handoff.get(
            "input_class"
        ),
        "LEARNING_INPUT_CLASS",
        maximum=64,
    )

    if (
        input_class
        not in INPUT_CLASSES
    ):
        raise LearningMemoryError(
            "LEARNING_INPUT_CLASS_INVALID"
        )

    candidate_eligible = _bool(
        handoff.get(
            "candidate_eligible"
        ),
        "LEARNING_CANDIDATE_ELIGIBLE",
    )

    if (
        handoff.get(
            "generalizable_claim"
        )
        is not False
        or handoff.get(
            "canonical_policy_change"
        )
        is not False
        or handoff.get(
            "promotion_authority"
        )
        != "NONE"
    ):
        raise LearningMemoryError(
            "LEARNING_HANDOFF_AUTHORITY_DRIFT"
        )

    verified_outcome = (
        input_class
        in {
            "VERIFIED_SUCCESS",
            "VERIFIED_FAILURE",
            "CONFLICT",
        }
    )

    return {
        "schema":
            EPISODE_SCHEMA,
        "memory_class":
            "EPISODIC_MEMORY",
        "task_id":
            task,
        "origin_id":
            origin,
        "goal":
            goal_text,
        "state_base_revision":
            state_base,
        "source_sha256":
            source_sha,
        "semantic_closure_sha256":
            closure_sha,
        "visible_acceptance_result_sha256":
            str(
                handoff.get(
                    "visible_acceptance_result_sha256",
                    "",
                )
            ),
        "input_class":
            input_class,
        "outcome_verified":
            verified_outcome,
        "candidate_eligible":
            (
                candidate_eligible
                and verified_outcome
            ),
        "freshness_policy":
            "SOURCE_AND_STATE_BOUND",
        "scope":
            "TASK",
        "promotion_authority":
            "NONE",
        "action_authority":
            "NONE",
        "network_authority":
            "NONE",
        "canonical_policy_change":
            False,
        "model_output_as_evidence":
            False,
    }


def build_learning_candidate(
    experiences: Sequence[
        Mapping[
            str,
            Any,
        ]
    ],
    *,
    claim_key: str,
    statement: str,
    scope: str,
    limitation: str,
) -> dict[str, Any]:
    if (
        not isinstance(
            experiences,
            Sequence,
        )
        or isinstance(
            experiences,
            (
                str,
                bytes,
                bytearray,
            ),
        )
        or not experiences
    ):
        raise LearningMemoryError(
            "LEARNING_EXPERIENCES_INVALID"
        )

    normalized = [
        _validate_episode(
            item
        )
        for item in experiences
    ]

    for item in normalized:
        if not item[
            "candidate_eligible"
        ]:
            raise LearningMemoryError(
                "LEARNING_EXPERIENCE_NOT_ELIGIBLE"
            )

    support = sorted(
        {
            digest_json(
                item
            )
            for item in normalized
        }
    )

    task_ids = sorted(
        {
            str(
                item[
                    "task_id"
                ]
            )
            for item in normalized
        }
    )

    origin_ids = sorted(
        {
            str(
                item[
                    "origin_id"
                ]
            )
            for item in normalized
        }
    )

    source_bindings = sorted(
        {
            str(
                item[
                    "source_sha256"
                ]
            )
            for item in normalized
        }
    )

    state_bases = sorted(
        {
            str(
                item[
                    "state_base_revision"
                ]
            )
            for item in normalized
        }
    )

    status = (
        "PROCEDURAL_CANDIDATE"
        if len(task_ids) >= 2
        else "EPISODIC_CANDIDATE"
    )

    return {
        "schema":
            CANDIDATE_SCHEMA,
        "status":
            status,
        "claim_key":
            _text(
                claim_key,
                "CLAIM_KEY",
                maximum=256,
            ),
        "statement":
            _text(
                statement,
                "STATEMENT",
            ),
        "scope":
            _text(
                scope,
                "SCOPE",
                maximum=256,
            ),
        "limitation":
            _text(
                limitation,
                "LIMITATION",
            ),
        "supporting_experience_sha256s":
            support,
        "supporting_task_ids":
            task_ids,
        "supporting_origin_ids":
            origin_ids,
        "source_bindings":
            source_bindings,
        "state_base_revisions":
            state_bases,
        "generalizable_claim":
            False,
        "canonical_policy_change":
            False,
        "promotion_authority":
            "NONE",
        "action_authority":
            "NONE",
        "network_authority":
            "NONE",
        "model_output_as_evidence":
            False,
    }


def _validate_candidate(
    value: object,
) -> dict[str, Any]:
    candidate = dict(
        _mapping(
            value,
            "LEARNING_CANDIDATE",
        )
    )

    if (
        candidate.get(
            "schema"
        )
        != CANDIDATE_SCHEMA
    ):
        raise LearningMemoryError(
            "LEARNING_CANDIDATE_SCHEMA_INVALID"
        )

    if (
        candidate.get(
            "status"
        )
        not in {
            "EPISODIC_CANDIDATE",
            "PROCEDURAL_CANDIDATE",
        }
    ):
        raise LearningMemoryError(
            "LEARNING_CANDIDATE_STATUS_INVALID"
        )

    if (
        candidate.get(
            "canonical_policy_change"
        )
        is not False
        or candidate.get(
            "promotion_authority"
        )
        != "NONE"
        or candidate.get(
            "action_authority"
        )
        != "NONE"
        or candidate.get(
            "network_authority"
        )
        != "NONE"
        or candidate.get(
            "model_output_as_evidence"
        )
        is not False
    ):
        raise LearningMemoryError(
            "LEARNING_CANDIDATE_AUTHORITY_DRIFT"
        )

    _text(
        candidate.get(
            "claim_key"
        ),
        "LEARNING_CLAIM_KEY",
        maximum=256,
    )

    _text(
        candidate.get(
            "statement"
        ),
        "LEARNING_STATEMENT",
    )

    _text(
        candidate.get(
            "scope"
        ),
        "LEARNING_SCOPE",
        maximum=256,
    )

    _sha_sequence(
        candidate.get(
            "supporting_experience_sha256s"
        ),
        "SUPPORTING_EXPERIENCE",
        allow_empty=False,
    )

    return candidate


def review_learning_candidate(
    candidate: Mapping[
        str,
        Any,
    ],
    *,
    regression_evidence_sha256s: Sequence[
        str
    ],
    conflicting_evidence_sha256s: Sequence[
        str
    ] = (),
) -> dict[str, Any]:
    normalized = (
        _validate_candidate(
            candidate
        )
    )

    candidate_sha = digest_json(
        normalized
    )

    regressions = sorted(
        set(
            _sha_sequence(
                regression_evidence_sha256s,
                "REGRESSION_EVIDENCE",
                allow_empty=True,
            )
        )
    )

    conflicts = sorted(
        set(
            _sha_sequence(
                conflicting_evidence_sha256s,
                "CONFLICTING_EVIDENCE",
                allow_empty=True,
            )
        )
    )

    if conflicts:
        status = (
            "BLOCKED_CONFLICT"
        )
        reason = (
            "Contradicting evidence requires "
            "reconciliation before promotion."
        )
    elif (
        normalized[
            "status"
        ]
        != "PROCEDURAL_CANDIDATE"
    ):
        status = (
            "NEEDS_MORE_EXPERIENCE"
        )
        reason = (
            "A single-task episodic candidate "
            "does not establish a procedure."
        )
    elif not regressions:
        status = (
            "EVIDENCE_REQUIRED"
        )
        reason = (
            "Regression evidence is required "
            "before memory promotion."
        )
    else:
        status = (
            "PROMOTABLE_MEMORY"
        )
        reason = (
            "Candidate has multi-task support, "
            "regression evidence, and no "
            "registered conflict."
        )

    return {
        "schema":
            REVIEW_SCHEMA,
        "candidate_sha256":
            candidate_sha,
        "status":
            status,
        "reason":
            reason,
        "regression_evidence_sha256s":
            regressions,
        "conflicting_evidence_sha256s":
            conflicts,
        "canonical_policy_change":
            False,
        "policy_promotion_required":
            True,
        "promotion_authority":
            "NONE",
        "action_authority":
            "NONE",
        "network_authority":
            "NONE",
    }


def _validate_review(
    value: object,
    *,
    candidate_sha256: str,
) -> dict[str, Any]:
    review = dict(
        _mapping(
            value,
            "LEARNING_REVIEW",
        )
    )

    if (
        review.get(
            "schema"
        )
        != REVIEW_SCHEMA
    ):
        raise LearningMemoryError(
            "LEARNING_REVIEW_SCHEMA_INVALID"
        )

    if (
        review.get(
            "candidate_sha256"
        )
        != candidate_sha256
    ):
        raise LearningMemoryError(
            "LEARNING_REVIEW_CANDIDATE_BINDING_MISMATCH"
        )

    if (
        review.get(
            "canonical_policy_change"
        )
        is not False
        or review.get(
            "policy_promotion_required"
        )
        is not True
        or review.get(
            "promotion_authority"
        )
        != "NONE"
        or review.get(
            "action_authority"
        )
        != "NONE"
        or review.get(
            "network_authority"
        )
        != "NONE"
    ):
        raise LearningMemoryError(
            "LEARNING_REVIEW_AUTHORITY_DRIFT"
        )

    return review


def _validate_approval(
    value: object,
    *,
    candidate_sha256: str,
    review_sha256: str,
    memory_class: str,
) -> dict[str, Any]:
    approval = dict(
        _mapping(
            value,
            "PROMOTION_APPROVAL",
        )
    )

    if (
        approval.get(
            "schema"
        )
        != APPROVAL_SCHEMA
    ):
        raise LearningMemoryError(
            "PROMOTION_APPROVAL_SCHEMA_INVALID"
        )

    if (
        approval.get(
            "candidate_sha256"
        )
        != candidate_sha256
    ):
        raise LearningMemoryError(
            "PROMOTION_APPROVAL_CANDIDATE_BINDING_MISMATCH"
        )

    if (
        approval.get(
            "review_sha256"
        )
        != review_sha256
    ):
        raise LearningMemoryError(
            "PROMOTION_APPROVAL_REVIEW_BINDING_MISMATCH"
        )

    if (
        approval.get(
            "memory_class"
        )
        != memory_class
    ):
        raise LearningMemoryError(
            "PROMOTION_APPROVAL_CLASS_BINDING_MISMATCH"
        )

    if (
        approval.get(
            "approved"
        )
        is not True
        or approval.get(
            "actor_class"
        )
        != "HUMAN_EXPLICIT"
        or approval.get(
            "action_authority"
        )
        != "NONE"
        or approval.get(
            "network_authority"
        )
        != "NONE"
        or approval.get(
            "canonical_policy_change"
        )
        is not False
    ):
        raise LearningMemoryError(
            "PROMOTION_APPROVAL_AUTHORITY_INVALID"
        )

    _sha(
        approval.get(
            "current_source_sha256"
        ),
        "APPROVAL_SOURCE_SHA256",
    )

    _text(
        approval.get(
            "current_state_base_revision"
        ),
        "APPROVAL_STATE_BASE",
        maximum=256,
    )

    _sha(
        approval.get(
            "proof_sha256"
        ),
        "APPROVAL_PROOF_SHA256",
    )

    _text(
        approval.get(
            "task_id"
        ),
        "APPROVAL_TASK_ID",
        maximum=256,
    )

    _text(
        approval.get(
            "origin_id"
        ),
        "APPROVAL_ORIGIN_ID",
        maximum=256,
    )

    return approval


def promote_reviewed_candidate(
    candidate: Mapping[
        str,
        Any,
    ],
    review: Mapping[
        str,
        Any,
    ],
    approval: Mapping[
        str,
        Any,
    ],
    *,
    memory_class: str,
    supersedes: Sequence[
        str
    ] = (),
) -> dict[str, Any]:
    normalized = (
        _validate_candidate(
            candidate
        )
    )

    candidate_sha = digest_json(
        normalized
    )

    checked_review = (
        _validate_review(
            review,
            candidate_sha256=(
                candidate_sha
            ),
        )
    )

    if (
        checked_review.get(
            "status"
        )
        != "PROMOTABLE_MEMORY"
    ):
        raise LearningMemoryError(
            "LEARNING_REVIEW_NOT_PROMOTABLE"
        )

    if (
        memory_class
        not in MEMORY_CLASSES
    ):
        raise LearningMemoryError(
            "CANONICAL_POLICY_PROMOTION_FORBIDDEN"
        )

    review_sha = digest_json(
        checked_review
    )

    checked_approval = (
        _validate_approval(
            approval,
            candidate_sha256=(
                candidate_sha
            ),
            review_sha256=(
                review_sha
            ),
            memory_class=(
                memory_class
            ),
        )
    )

    superseded = sorted(
        set(
            _sha_sequence(
                supersedes,
                "SUPERSEDES",
                allow_empty=True,
            )
        )
    )

    return {
        "schema":
            PROMOTED_SCHEMA,
        "version":
            1,
        "status":
            "PROMOTED",
        "memory_class":
            memory_class,
        "claim_key":
            normalized[
                "claim_key"
            ],
        "statement":
            normalized[
                "statement"
            ],
        "scope":
            normalized[
                "scope"
            ],
        "limitation":
            normalized[
                "limitation"
            ],
        "candidate_sha256":
            candidate_sha,
        "review_sha256":
            review_sha,
        "approval_sha256":
            digest_json(
                checked_approval
            ),
        "supporting_experience_sha256s":
            list(
                normalized[
                    "supporting_experience_sha256s"
                ]
            ),
        "regression_evidence_sha256s":
            list(
                checked_review[
                    "regression_evidence_sha256s"
                ]
            ),
        "contradicting_evidence_sha256s":
            list(
                checked_review[
                    "conflicting_evidence_sha256s"
                ]
            ),
        "verified_source_sha256":
            checked_approval[
                "current_source_sha256"
            ],
        "verified_state_base_revision":
            checked_approval[
                "current_state_base_revision"
            ],
        "stale_conditions": [
            "SOURCE_SHA256_CHANGE",
            "STATE_BASE_REVISION_CHANGE",
            "CONTRADICTING_EVIDENCE",
        ],
        "supersedes":
            superseded,
        "promotion_task_id":
            checked_approval[
                "task_id"
            ],
        "promotion_origin_id":
            checked_approval[
                "origin_id"
            ],
        "promotion_authority":
            "HUMAN_EXPLICIT_BOUND",
        "canonical_policy_change":
            False,
        "action_authority":
            "NONE",
        "network_authority":
            "NONE",
        "model_output_as_evidence":
            False,
    }


def _validate_promoted_memory(
    value: object,
) -> dict[str, Any]:
    memory = dict(
        _mapping(
            value,
            "PROMOTED_MEMORY",
        )
    )

    if (
        memory.get(
            "schema"
        )
        != PROMOTED_SCHEMA
    ):
        raise LearningMemoryError(
            "PROMOTED_MEMORY_SCHEMA_INVALID"
        )

    if (
        memory.get(
            "memory_class"
        )
        not in MEMORY_CLASSES
    ):
        raise LearningMemoryError(
            "PROMOTED_MEMORY_CLASS_INVALID"
        )

    if (
        memory.get(
            "status"
        )
        != "PROMOTED"
        or memory.get(
            "canonical_policy_change"
        )
        is not False
        or memory.get(
            "action_authority"
        )
        != "NONE"
        or memory.get(
            "network_authority"
        )
        != "NONE"
        or memory.get(
            "model_output_as_evidence"
        )
        is not False
    ):
        raise LearningMemoryError(
            "PROMOTED_MEMORY_AUTHORITY_DRIFT"
        )

    _sha(
        memory.get(
            "candidate_sha256"
        ),
        "PROMOTED_CANDIDATE_SHA",
    )

    _sha(
        memory.get(
            "review_sha256"
        ),
        "PROMOTED_REVIEW_SHA",
    )

    _sha(
        memory.get(
            "approval_sha256"
        ),
        "PROMOTED_APPROVAL_SHA",
    )

    _sha(
        memory.get(
            "verified_source_sha256"
        ),
        "PROMOTED_SOURCE_SHA",
    )

    _text(
        memory.get(
            "verified_state_base_revision"
        ),
        "PROMOTED_STATE_BASE",
        maximum=256,
    )

    return memory


def assess_memory_freshness(
    promoted_memory: Mapping[
        str,
        Any,
    ],
    *,
    current_source_sha256: str,
    current_state_base_revision: str,
    contradicting_evidence_sha256s: Sequence[
        str
    ] = (),
) -> dict[str, Any]:
    memory = (
        _validate_promoted_memory(
            promoted_memory
        )
    )

    memory_sha = digest_json(
        memory
    )

    source_sha = _sha(
        current_source_sha256,
        "CURRENT_SOURCE_SHA256",
    )

    state_base = _text(
        current_state_base_revision,
        "CURRENT_STATE_BASE_REVISION",
        maximum=256,
    )

    contradictions = sorted(
        set(
            _sha_sequence(
                contradicting_evidence_sha256s,
                "CURRENT_CONTRADICTING_EVIDENCE",
                allow_empty=True,
            )
        )
    )

    reasons: list[str] = []

    if (
        memory[
            "verified_source_sha256"
        ]
        != source_sha
    ):
        reasons.append(
            "SOURCE_SHA256_CHANGE"
        )

    if (
        memory[
            "verified_state_base_revision"
        ]
        != state_base
    ):
        reasons.append(
            "STATE_BASE_REVISION_CHANGE"
        )

    if contradictions:
        reasons.append(
            "CONTRADICTING_EVIDENCE"
        )

    return {
        "schema":
            FRESHNESS_SCHEMA,
        "memory_sha256":
            memory_sha,
        "status":
            (
                "REFRESH_REQUIRED"
                if reasons
                else "CURRENT"
            ),
        "stale_reasons":
            reasons,
        "current_source_sha256":
            source_sha,
        "current_state_base_revision":
            state_base,
        "contradicting_evidence_sha256s":
            contradictions,
        "action_authority":
            "NONE",
        "network_authority":
            "NONE",
    }


def build_ledger_candidate(
    promoted_memory: Mapping[
        str,
        Any,
    ],
    *,
    parent_entry_sha256s: Sequence[
        str
    ],
) -> dict[str, Any]:
    memory = (
        _validate_promoted_memory(
            promoted_memory
        )
    )

    parents = list(
        _sha_sequence(
            parent_entry_sha256s,
            "PARENT_ENTRY_SHA256S",
            allow_empty=False,
        )
    )

    memory_sha = digest_json(
        memory
    )

    stack = cognitive.load_stack()

    return (
        stack[
            "ledger"
        ]
        .make_claim_candidate(
            task_id=str(
                memory[
                    "promotion_task_id"
                ]
            ),
            origin_id=str(
                memory[
                    "promotion_origin_id"
                ]
            ),
            claim_key=str(
                memory[
                    "claim_key"
                ]
            ),
            statement=str(
                memory[
                    "statement"
                ]
            ),
            epistemic_class=(
                "DERIVED"
            ),
            source_kind=(
                "DERIVATION"
            ),
            source_id=(
                "workbench-learning-memory-promotion"
            ),
            source_fingerprint=(
                memory_sha
            ),
            parent_entry_sha256s=(
                parents
            ),
        )
    )
