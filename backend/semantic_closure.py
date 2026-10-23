"""Pure semantic DONE_WHEN and visible-acceptance boundary.

Machine correctness, semantic completion, visible acceptance and learning
promotion are deliberately separate claims.

This module performs no filesystem I/O, process execution, network access,
model inference, source mutation or authority escalation.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any


REQUEST_SCHEMA = (
    "gg.semantic-closure-request.v1"
)
SEMANTIC_EVIDENCE_SCHEMA = (
    "gg.semantic-evidence.v1"
)
CLOSURE_SCHEMA = (
    "gg.semantic-closure-result.v1"
)
VISIBLE_EVIDENCE_SCHEMA = (
    "gg.visible-acceptance-evidence.v1"
)
VISIBLE_RESULT_SCHEMA = (
    "gg.visible-acceptance-result.v1"
)
LEARNING_HANDOFF_SCHEMA = (
    "gg.semantic-learning-handoff.v1"
)

CAPABILITY_ID = (
    "verify.semantic.done_when"
)

MACHINE_STATUSES = frozenset(
    (
        "PASS",
        "FAIL",
        "UNKNOWN",
        "BLOCKED",
    )
)

SEMANTIC_EVIDENCE_STATUSES = frozenset(
    (
        "PASS",
        "FAIL",
        "UNKNOWN",
        "CONFLICT",
        "HUMAN_REQUIRED",
    )
)

TRUSTED_SEMANTIC_VERIFIER_CLASSES = frozenset(
    (
        "DETERMINISTIC_PREDICATE",
        "TASK_SPECIFIC_VERIFIER",
        "HUMAN_EXPLICIT_SEMANTIC",
    )
)

CLOSURE_STATUSES = frozenset(
    (
        "MACHINE_NOT_READY",
        "EVIDENCE_REQUIRED",
        "PASS",
        "FAIL",
        "UNKNOWN",
        "CONFLICT",
        "HUMAN_REQUIRED",
    )
)

VISIBLE_STATUSES = frozenset(
    (
        "NOT_AVAILABLE",
        "NOT_REQUIRED",
        "PENDING",
        "ACCEPTED",
        "REJECTED",
    )
)

LEARNING_INPUT_CLASSES = frozenset(
    (
        "VERIFIED_SUCCESS",
        "VERIFIED_FAILURE",
        "CONFLICT",
        "UNKNOWN",
    )
)

HUMAN_ACCEPTANCE_ACTOR = (
    "HUMAN_EXPLICIT"
)


class SemanticClosureError(
    RuntimeError
):
    """Semantic closure contract violation."""


def canonical_json(
    value: Any,
) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def digest_json(
    value: Any,
) -> str:
    return hashlib.sha256(
        canonical_json(value)
    ).hexdigest()


def _valid_sha256(
    value: object,
) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(
            character
            in "0123456789abcdef"
            for character in value
        )
    )


def _require_sha256(
    value: object,
    label: str,
) -> str:
    if not _valid_sha256(value):
        raise SemanticClosureError(
            label
            + "_SHA256_INVALID"
        )

    return value


def _require_text(
    value: object,
    label: str,
    *,
    maximum: int,
) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
    ):
        raise SemanticClosureError(
            label
            + "_TEXT_INVALID"
        )

    return value


@dataclass(frozen=True)
class SemanticClosureRequest:
    goal_id: str
    object_id: str
    current_target: str
    done_when: str
    source_sha256: str
    machine_status: str
    machine_scope: str
    machine_evidence_sha256: str
    semantic_contract_sha256: str
    visible_acceptance_required: bool

    def as_dict(
        self,
    ) -> dict[str, Any]:
        return {
            "schema":
                REQUEST_SCHEMA,
            "goal_id":
                self.goal_id,
            "object_id":
                self.object_id,
            "current_target":
                self.current_target,
            "done_when":
                self.done_when,
            "source_sha256":
                self.source_sha256,
            "machine_status":
                self.machine_status,
            "machine_scope":
                self.machine_scope,
            "machine_evidence_sha256":
                self.machine_evidence_sha256,
            "semantic_contract_sha256":
                self.semantic_contract_sha256,
            "visible_acceptance_required":
                self.visible_acceptance_required,
        }

    def request_sha256(
        self,
    ) -> str:
        return digest_json(
            self.as_dict()
        )


@dataclass(frozen=True)
class SemanticEvidence:
    request_sha256: str
    source_sha256: str
    semantic_contract_sha256: str
    status: str
    verifier_class: str
    verifier_id: str
    proof_sha256: str
    limitation: str

    def as_dict(
        self,
    ) -> dict[str, Any]:
        return {
            "schema":
                SEMANTIC_EVIDENCE_SCHEMA,
            "request_sha256":
                self.request_sha256,
            "source_sha256":
                self.source_sha256,
            "semantic_contract_sha256":
                self.semantic_contract_sha256,
            "status":
                self.status,
            "verifier_class":
                self.verifier_class,
            "verifier_id":
                self.verifier_id,
            "proof_sha256":
                self.proof_sha256,
            "limitation":
                self.limitation,
        }

    def evidence_sha256(
        self,
    ) -> str:
        return digest_json(
            self.as_dict()
        )


@dataclass(frozen=True)
class SemanticClosureResult:
    goal_id: str
    object_id: str
    current_target: str
    done_when: str
    request_sha256: str
    source_sha256: str
    machine_status: str
    machine_scope: str
    machine_evidence_sha256: str
    semantic_contract_sha256: str
    status: str
    semantic_done: bool
    visible_acceptance_required: bool
    semantic_evidence_sha256: str
    verifier_class: str
    verifier_id: str
    proof_sha256: str
    limitation: str

    def as_dict(
        self,
    ) -> dict[str, Any]:
        return {
            "schema":
                CLOSURE_SCHEMA,
            "goal_id":
                self.goal_id,
            "object_id":
                self.object_id,
            "current_target":
                self.current_target,
            "done_when":
                self.done_when,
            "request_sha256":
                self.request_sha256,
            "source_sha256":
                self.source_sha256,
            "machine_status":
                self.machine_status,
            "machine_scope":
                self.machine_scope,
            "machine_evidence_sha256":
                self.machine_evidence_sha256,
            "semantic_contract_sha256":
                self.semantic_contract_sha256,
            "status":
                self.status,
            "semantic_done":
                self.semantic_done,
            "visible_acceptance_required":
                self.visible_acceptance_required,
            "semantic_evidence_sha256":
                self.semantic_evidence_sha256,
            "verifier_class":
                self.verifier_class,
            "verifier_id":
                self.verifier_id,
            "proof_sha256":
                self.proof_sha256,
            "limitation":
                self.limitation,
        }

    def closure_sha256(
        self,
    ) -> str:
        return digest_json(
            self.as_dict()
        )


@dataclass(frozen=True)
class VisibleAcceptanceEvidence:
    closure_sha256: str
    source_sha256: str
    accepted: bool
    actor_class: str
    proof_sha256: str

    def as_dict(
        self,
    ) -> dict[str, Any]:
        return {
            "schema":
                VISIBLE_EVIDENCE_SCHEMA,
            "closure_sha256":
                self.closure_sha256,
            "source_sha256":
                self.source_sha256,
            "accepted":
                self.accepted,
            "actor_class":
                self.actor_class,
            "proof_sha256":
                self.proof_sha256,
        }

    def evidence_sha256(
        self,
    ) -> str:
        return digest_json(
            self.as_dict()
        )


@dataclass(frozen=True)
class VisibleAcceptanceResult:
    closure_sha256: str
    source_sha256: str
    status: str
    visible_accepted: bool
    acceptance_evidence_sha256: str

    def as_dict(
        self,
    ) -> dict[str, Any]:
        return {
            "schema":
                VISIBLE_RESULT_SCHEMA,
            "closure_sha256":
                self.closure_sha256,
            "source_sha256":
                self.source_sha256,
            "status":
                self.status,
            "visible_accepted":
                self.visible_accepted,
            "acceptance_evidence_sha256":
                self.acceptance_evidence_sha256,
        }

    def result_sha256(
        self,
    ) -> str:
        return digest_json(
            self.as_dict()
        )


@dataclass(frozen=True)
class LearningHandoff:
    semantic_closure_sha256: str
    visible_acceptance_result_sha256: str
    input_class: str
    candidate_eligible: bool
    generalizable_claim: bool
    canonical_policy_change: bool
    promotion_authority: str
    reason: str

    def as_dict(
        self,
    ) -> dict[str, Any]:
        return {
            "schema":
                LEARNING_HANDOFF_SCHEMA,
            "semantic_closure_sha256":
                self.semantic_closure_sha256,
            "visible_acceptance_result_sha256":
                self.visible_acceptance_result_sha256,
            "input_class":
                self.input_class,
            "candidate_eligible":
                self.candidate_eligible,
            "generalizable_claim":
                self.generalizable_claim,
            "canonical_policy_change":
                self.canonical_policy_change,
            "promotion_authority":
                self.promotion_authority,
            "reason":
                self.reason,
        }

    def handoff_sha256(
        self,
    ) -> str:
        return digest_json(
            self.as_dict()
        )


def validate_request(
    request: SemanticClosureRequest,
) -> SemanticClosureRequest:
    if not isinstance(
        request,
        SemanticClosureRequest,
    ):
        raise SemanticClosureError(
            "REQUEST_TYPE_INVALID"
        )

    _require_text(
        request.goal_id,
        "GOAL_ID",
        maximum=256,
    )

    _require_text(
        request.object_id,
        "OBJECT_ID",
        maximum=256,
    )

    _require_text(
        request.current_target,
        "CURRENT_TARGET",
        maximum=1024,
    )

    _require_text(
        request.done_when,
        "DONE_WHEN",
        maximum=2048,
    )

    _require_sha256(
        request.source_sha256,
        "SOURCE",
    )

    _require_text(
        request.machine_scope,
        "MACHINE_SCOPE",
        maximum=256,
    )

    _require_sha256(
        request.machine_evidence_sha256,
        "MACHINE_EVIDENCE",
    )

    _require_sha256(
        request.semantic_contract_sha256,
        "SEMANTIC_CONTRACT",
    )

    if (
        request.machine_status
        not in MACHINE_STATUSES
    ):
        raise SemanticClosureError(
            "MACHINE_STATUS_INVALID"
        )

    if not isinstance(
        request.visible_acceptance_required,
        bool,
    ):
        raise SemanticClosureError(
            "VISIBLE_ACCEPTANCE_REQUIRED_INVALID"
        )

    return request


def validate_semantic_evidence(
    evidence: SemanticEvidence,
) -> SemanticEvidence:
    if not isinstance(
        evidence,
        SemanticEvidence,
    ):
        raise SemanticClosureError(
            "SEMANTIC_EVIDENCE_TYPE_INVALID"
        )

    _require_sha256(
        evidence.request_sha256,
        "SEMANTIC_REQUEST",
    )

    _require_sha256(
        evidence.source_sha256,
        "SEMANTIC_SOURCE",
    )

    _require_sha256(
        evidence.semantic_contract_sha256,
        "SEMANTIC_CONTRACT",
    )

    _require_sha256(
        evidence.proof_sha256,
        "SEMANTIC_PROOF",
    )

    if (
        evidence.status
        not in SEMANTIC_EVIDENCE_STATUSES
    ):
        raise SemanticClosureError(
            "SEMANTIC_STATUS_INVALID"
        )

    if (
        evidence.verifier_class
        not in TRUSTED_SEMANTIC_VERIFIER_CLASSES
    ):
        raise SemanticClosureError(
            "SEMANTIC_VERIFIER_CLASS_UNTRUSTED"
        )

    _require_text(
        evidence.verifier_id,
        "SEMANTIC_VERIFIER_ID",
        maximum=256,
    )

    if (
        not isinstance(
            evidence.limitation,
            str,
        )
        or len(
            evidence.limitation
        ) > 1024
    ):
        raise SemanticClosureError(
            "SEMANTIC_LIMITATION_INVALID"
        )

    return evidence


def _empty_result(
    request: SemanticClosureRequest,
    *,
    status: str,
    limitation: str,
) -> SemanticClosureResult:
    if status not in CLOSURE_STATUSES:
        raise SemanticClosureError(
            "CLOSURE_STATUS_INVALID"
        )

    return SemanticClosureResult(
        goal_id=request.goal_id,
        object_id=request.object_id,
        current_target=request.current_target,
        done_when=request.done_when,
        request_sha256=(
            request.request_sha256()
        ),
        source_sha256=(
            request.source_sha256
        ),
        machine_status=(
            request.machine_status
        ),
        machine_scope=(
            request.machine_scope
        ),
        machine_evidence_sha256=(
            request.machine_evidence_sha256
        ),
        semantic_contract_sha256=(
            request.semantic_contract_sha256
        ),
        status=status,
        semantic_done=False,
        visible_acceptance_required=(
            request.visible_acceptance_required
        ),
        semantic_evidence_sha256="",
        verifier_class="",
        verifier_id="",
        proof_sha256="",
        limitation=limitation,
    )


def evaluate_semantic_closure(
    request: SemanticClosureRequest,
    evidence: SemanticEvidence | None = None,
) -> SemanticClosureResult:
    request = validate_request(
        request
    )

    if request.machine_status != "PASS":
        return _empty_result(
            request,
            status="MACHINE_NOT_READY",
            limitation=(
                "Machine correctness is not PASS."
            ),
        )

    if evidence is None:
        return _empty_result(
            request,
            status="EVIDENCE_REQUIRED",
            limitation=(
                "Machine correctness does not "
                "establish semantic DONE_WHEN."
            ),
        )

    evidence = validate_semantic_evidence(
        evidence
    )

    request_sha256 = (
        request.request_sha256()
    )

    if (
        evidence.request_sha256
        != request_sha256
    ):
        raise SemanticClosureError(
            "SEMANTIC_REQUEST_BINDING_MISMATCH"
        )

    if (
        evidence.source_sha256
        != request.source_sha256
    ):
        raise SemanticClosureError(
            "SEMANTIC_SOURCE_BINDING_MISMATCH"
        )

    if (
        evidence.semantic_contract_sha256
        != request.semantic_contract_sha256
    ):
        raise SemanticClosureError(
            "SEMANTIC_CONTRACT_BINDING_MISMATCH"
        )

    return SemanticClosureResult(
        goal_id=request.goal_id,
        object_id=request.object_id,
        current_target=request.current_target,
        done_when=request.done_when,
        request_sha256=request_sha256,
        source_sha256=(
            request.source_sha256
        ),
        machine_status=(
            request.machine_status
        ),
        machine_scope=(
            request.machine_scope
        ),
        machine_evidence_sha256=(
            request.machine_evidence_sha256
        ),
        semantic_contract_sha256=(
            request.semantic_contract_sha256
        ),
        status=evidence.status,
        semantic_done=(
            evidence.status == "PASS"
        ),
        visible_acceptance_required=(
            request.visible_acceptance_required
        ),
        semantic_evidence_sha256=(
            evidence.evidence_sha256()
        ),
        verifier_class=(
            evidence.verifier_class
        ),
        verifier_id=(
            evidence.verifier_id
        ),
        proof_sha256=(
            evidence.proof_sha256
        ),
        limitation=(
            evidence.limitation
        ),
    )


def validate_visible_evidence(
    evidence: VisibleAcceptanceEvidence,
) -> VisibleAcceptanceEvidence:
    if not isinstance(
        evidence,
        VisibleAcceptanceEvidence,
    ):
        raise SemanticClosureError(
            "VISIBLE_EVIDENCE_TYPE_INVALID"
        )

    _require_sha256(
        evidence.closure_sha256,
        "VISIBLE_CLOSURE",
    )

    _require_sha256(
        evidence.source_sha256,
        "VISIBLE_SOURCE",
    )

    _require_sha256(
        evidence.proof_sha256,
        "VISIBLE_PROOF",
    )

    if not isinstance(
        evidence.accepted,
        bool,
    ):
        raise SemanticClosureError(
            "VISIBLE_ACCEPTED_INVALID"
        )

    if (
        evidence.actor_class
        != HUMAN_ACCEPTANCE_ACTOR
    ):
        raise SemanticClosureError(
            "VISIBLE_ACTOR_NOT_EXPLICIT_HUMAN"
        )

    return evidence


def evaluate_visible_acceptance(
    closure: SemanticClosureResult,
    evidence: (
        VisibleAcceptanceEvidence
        | None
    ) = None,
) -> VisibleAcceptanceResult:
    if not isinstance(
        closure,
        SemanticClosureResult,
    ):
        raise SemanticClosureError(
            "CLOSURE_TYPE_INVALID"
        )

    closure_sha256 = (
        closure.closure_sha256()
    )

    if not closure.semantic_done:
        return VisibleAcceptanceResult(
            closure_sha256=closure_sha256,
            source_sha256=(
                closure.source_sha256
            ),
            status="NOT_AVAILABLE",
            visible_accepted=False,
            acceptance_evidence_sha256="",
        )

    if (
        not closure
        .visible_acceptance_required
    ):
        return VisibleAcceptanceResult(
            closure_sha256=closure_sha256,
            source_sha256=(
                closure.source_sha256
            ),
            status="NOT_REQUIRED",
            visible_accepted=False,
            acceptance_evidence_sha256="",
        )

    if evidence is None:
        return VisibleAcceptanceResult(
            closure_sha256=closure_sha256,
            source_sha256=(
                closure.source_sha256
            ),
            status="PENDING",
            visible_accepted=False,
            acceptance_evidence_sha256="",
        )

    evidence = validate_visible_evidence(
        evidence
    )

    if (
        evidence.closure_sha256
        != closure_sha256
    ):
        raise SemanticClosureError(
            "VISIBLE_CLOSURE_BINDING_MISMATCH"
        )

    if (
        evidence.source_sha256
        != closure.source_sha256
    ):
        raise SemanticClosureError(
            "VISIBLE_SOURCE_BINDING_MISMATCH"
        )

    return VisibleAcceptanceResult(
        closure_sha256=closure_sha256,
        source_sha256=(
            closure.source_sha256
        ),
        status=(
            "ACCEPTED"
            if evidence.accepted
            else "REJECTED"
        ),
        visible_accepted=(
            evidence.accepted
        ),
        acceptance_evidence_sha256=(
            evidence.evidence_sha256()
        ),
    )


def build_learning_handoff(
    closure: SemanticClosureResult,
    visible: (
        VisibleAcceptanceResult
        | None
    ) = None,
) -> LearningHandoff:
    if not isinstance(
        closure,
        SemanticClosureResult,
    ):
        raise SemanticClosureError(
            "LEARNING_CLOSURE_TYPE_INVALID"
        )

    closure_sha256 = (
        closure.closure_sha256()
    )

    visible_sha256 = ""

    if visible is not None:
        if not isinstance(
            visible,
            VisibleAcceptanceResult,
        ):
            raise SemanticClosureError(
                "LEARNING_VISIBLE_TYPE_INVALID"
            )

        if (
            visible.closure_sha256
            != closure_sha256
        ):
            raise SemanticClosureError(
                "LEARNING_VISIBLE_BINDING_MISMATCH"
            )

        visible_sha256 = (
            visible.result_sha256()
        )

    if closure.status == "FAIL":
        input_class = (
            "VERIFIED_FAILURE"
        )
        candidate_eligible = True
        reason = (
            "Verified semantic failure may "
            "feed failure-pattern learning."
        )

    elif closure.status == "CONFLICT":
        input_class = "CONFLICT"
        candidate_eligible = True
        reason = (
            "Verified conflict may feed "
            "conflict-resolution knowledge."
        )

    elif closure.semantic_done:
        visible_ok = (
            not closure
            .visible_acceptance_required
            or (
                visible is not None
                and visible.status
                == "ACCEPTED"
                and visible.visible_accepted
            )
        )

        if visible_ok:
            input_class = (
                "VERIFIED_SUCCESS"
            )
            candidate_eligible = True
            reason = (
                "Semantic DONE_WHEN and "
                "required visible acceptance "
                "are satisfied."
            )
        else:
            input_class = "UNKNOWN"
            candidate_eligible = False
            reason = (
                "Semantic DONE_WHEN passed "
                "but required visible acceptance "
                "is not established."
            )

    else:
        input_class = "UNKNOWN"
        candidate_eligible = False
        reason = (
            "Semantic outcome is not a "
            "verified success or failure."
        )

    if (
        input_class
        not in LEARNING_INPUT_CLASSES
    ):
        raise SemanticClosureError(
            "LEARNING_INPUT_CLASS_INVALID"
        )

    return LearningHandoff(
        semantic_closure_sha256=(
            closure_sha256
        ),
        visible_acceptance_result_sha256=(
            visible_sha256
        ),
        input_class=input_class,
        candidate_eligible=(
            candidate_eligible
        ),
        generalizable_claim=False,
        canonical_policy_change=False,
        promotion_authority="NONE",
        reason=reason,
    )
