"""Verified source-change events for resident Merkle propagation.

This module does not write source, scan the filesystem, discover capabilities
or invoke a model. It converts an already verified controlled-write receipt
into a content-addressed source change event and then into the exact LeafChange
consumed by the resident Merkle propagation DAG.

A source object's stable node ID answers *which object changed*. The old/new
SHA-256 identities answer *which exact state transition occurred*.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

if __package__:
    from . import merkle_propagation as _merkle_propagation
else:
    import merkle_propagation as _merkle_propagation

LeafChange = _merkle_propagation.LeafChange
PropagationResult = _merkle_propagation.PropagationResult
ResidentMerklePropagationDAG = (
    _merkle_propagation.ResidentMerklePropagationDAG
)



EVENT_SCHEMA = (
    "gg.verified-source-change-event.v1"
)
INGESTION_SCHEMA = (
    "gg.source-change-ingestion-result.v1"
)
WRITE_APPLY_RECEIPT_SCHEMA = (
    "gg.workbench.write-apply-receipt.v1"
)

HOST_SOURCE = "HOST_SOURCE"
IN_MEMORY_CANDIDATE = (
    "IN_MEMORY_CANDIDATE"
)

WORLDS = frozenset(
    (
        HOST_SOURCE,
        IN_MEMORY_CANDIDATE,
    )
)

WRITE_ROLLBACK_RECEIPT_SCHEMA = (
    "gg.workbench.write-rollback-receipt.v1"
)

WRITE_ROLLBACK_RECEIPT_FIELDS = frozenset(
    (
        "schema",
        "proposal_id",
        "before_sha256",
        "restored_sha256",
        "rollback_command",
        "effect_verified",
    )
)

WRITE_PROPOSAL_FIELDS = frozenset(
    (
        "schema",
        "proposal_id",
        "target_relative_path",
        "workspace_object_id",
        "context_reference",
        "head",
        "before_sha256",
        "candidate_sha256",
        "diff_sha256",
        "proposal_gate_report_sha256",
        "approval_command",
        "reject_command",
    )
)

CONTROL_APPLY_REQUEST_FIELDS = frozenset(
    (
        "schema",
        "action",
        "task_id",
        "base_head",
        "target_relative_path",
        "before_sha256",
        "candidate_sha256",
        "diff_sha256",
    )
)

CONTROL_APPLY_RESPONSE_FIELDS = frozenset(
    (
        "schema",
        "task_id",
        "status",
        "base_head",
        "before_sha256",
        "candidate_sha256",
        "host_after_sha256",
        "host_repo_changed",
        "output",
    )
)

WRITE_RECEIPT_FIELDS = frozenset(
    (
        "schema",
        "proposal_id",
        "target_relative_path",
        "before_sha256",
        "candidate_sha256",
        "post_sha256",
        "approval_command",
        "effect_verified",
    )
)


class SourceChangeEventError(
    RuntimeError
):
    """Verified source-change contract violation."""


def canonical_json(
    value: object,
) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def digest_json(
    value: object,
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
        raise SourceChangeEventError(
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
        or "\x00" in value
    ):
        raise SourceChangeEventError(
            label
            + "_TEXT_INVALID"
        )

    return value


def _require_relative_path(
    value: object,
) -> str:
    path = _require_text(
        value,
        "TARGET_RELATIVE_PATH",
        maximum=1024,
    )

    if (
        path.startswith("/")
        or "\\" in path
        or "//" in path
    ):
        raise SourceChangeEventError(
            "TARGET_RELATIVE_PATH_INVALID"
        )

    parts = path.split("/")

    if any(
        part in {
            "",
            ".",
            "..",
        }
        for part in parts
    ):
        raise SourceChangeEventError(
            "TARGET_RELATIVE_PATH_INVALID"
        )

    return path


@dataclass(frozen=True)
class SourceLeafBinding:
    world: str
    stable_node_id: str
    target_relative_path: str

    def validate(
        self,
    ) -> None:
        if self.world not in WORLDS:
            raise SourceChangeEventError(
                "SOURCE_WORLD_INVALID"
            )

        node_id = _require_text(
            self.stable_node_id,
            "STABLE_NODE_ID",
            maximum=2048,
        )

        if not node_id.startswith(
            "file:"
        ):
            raise SourceChangeEventError(
                "STABLE_NODE_ID_NOT_FILE"
            )

        _require_relative_path(
            self.target_relative_path
        )

    def as_dict(
        self,
    ) -> dict[str, str]:
        self.validate()

        return {
            "world":
                self.world,
            "stable_node_id":
                self.stable_node_id,
            "target_relative_path":
                self.target_relative_path,
        }


@dataclass(frozen=True)
class VerifiedSourceChangeEvent:
    schema: str
    world: str
    stable_node_id: str
    target_relative_path: str
    old_content_sha256: str
    new_content_sha256: str
    producer_id: str
    producer_event_id: str
    producer_content_sha256: str
    producer_contract_sha256: str
    state_base_revision: str
    evidence_sha256: str
    effect_verified: bool
    action_authority: str = "NONE"
    promotion_authority: str = "NONE"
    persistent_write_authority: str = "NONE"
    model_inference: bool = False
    registered_capability_execution: bool = False

    def validate(
        self,
    ) -> None:
        if self.schema != EVENT_SCHEMA:
            raise SourceChangeEventError(
                "EVENT_SCHEMA_INVALID"
            )

        binding = SourceLeafBinding(
            world=self.world,
            stable_node_id=(
                self.stable_node_id
            ),
            target_relative_path=(
                self.target_relative_path
            ),
        )

        binding.validate()

        _require_sha256(
            self.old_content_sha256,
            "EVENT_OLD_CONTENT",
        )

        _require_sha256(
            self.new_content_sha256,
            "EVENT_NEW_CONTENT",
        )

        if (
            self.old_content_sha256
            == self.new_content_sha256
        ):
            raise SourceChangeEventError(
                "EVENT_NO_EFFECT"
            )

        _require_text(
            self.producer_id,
            "PRODUCER_ID",
            maximum=512,
        )

        _require_text(
            self.producer_event_id,
            "PRODUCER_EVENT_ID",
            maximum=512,
        )

        _require_sha256(
            self.producer_content_sha256,
            "PRODUCER_CONTENT",
        )

        _require_sha256(
            self.producer_contract_sha256,
            "PRODUCER_CONTRACT",
        )

        _require_text(
            self.state_base_revision,
            "STATE_BASE_REVISION",
            maximum=256,
        )

        _require_sha256(
            self.evidence_sha256,
            "EVENT_EVIDENCE",
        )

        if self.effect_verified is not True:
            raise SourceChangeEventError(
                "EVENT_EFFECT_NOT_VERIFIED"
            )

        if self.action_authority != "NONE":
            raise SourceChangeEventError(
                "EVENT_ACTION_AUTHORITY_INVALID"
            )

        if self.promotion_authority != "NONE":
            raise SourceChangeEventError(
                "EVENT_PROMOTION_AUTHORITY_INVALID"
            )

        if (
            self.persistent_write_authority
            != "NONE"
        ):
            raise SourceChangeEventError(
                "EVENT_WRITE_AUTHORITY_INVALID"
            )

        if self.model_inference is not False:
            raise SourceChangeEventError(
                "EVENT_MODEL_INFERENCE_INVALID"
            )

        if (
            self.registered_capability_execution
            is not False
        ):
            raise SourceChangeEventError(
                "EVENT_REGISTERED_EXECUTION_INVALID"
            )

    def as_dict(
        self,
    ) -> dict[str, object]:
        self.validate()

        return {
            "schema":
                self.schema,
            "world":
                self.world,
            "stable_node_id":
                self.stable_node_id,
            "target_relative_path":
                self.target_relative_path,
            "old_content_sha256":
                self.old_content_sha256,
            "new_content_sha256":
                self.new_content_sha256,
            "producer_id":
                self.producer_id,
            "producer_event_id":
                self.producer_event_id,
            "producer_content_sha256":
                self.producer_content_sha256,
            "producer_contract_sha256":
                self.producer_contract_sha256,
            "state_base_revision":
                self.state_base_revision,
            "evidence_sha256":
                self.evidence_sha256,
            "effect_verified":
                self.effect_verified,
            "action_authority":
                self.action_authority,
            "promotion_authority":
                self.promotion_authority,
            "persistent_write_authority":
                self.persistent_write_authority,
            "model_inference":
                self.model_inference,
            "registered_capability_execution":
                self.registered_capability_execution,
        }

    def event_sha256(
        self,
    ) -> str:
        return digest_json(
            self.as_dict()
        )


@dataclass(frozen=True)
class SourceChangeIngestionResult:
    schema: str
    event_sha256: str
    propagation: PropagationResult
    action_authority: str = "NONE"
    promotion_authority: str = "NONE"
    persistent_write: str = "NONE"
    model_inference: bool = False
    registered_capability_execution: bool = False

    def validate(
        self,
    ) -> None:
        if (
            self.schema
            != INGESTION_SCHEMA
        ):
            raise SourceChangeEventError(
                "INGESTION_SCHEMA_INVALID"
            )

        _require_sha256(
            self.event_sha256,
            "INGESTION_EVENT",
        )

        if not isinstance(
            self.propagation,
            PropagationResult,
        ):
            raise SourceChangeEventError(
                "INGESTION_PROPAGATION_TYPE_INVALID"
            )

        self.propagation.validate()

        if self.action_authority != "NONE":
            raise SourceChangeEventError(
                "INGESTION_ACTION_AUTHORITY_INVALID"
            )

        if self.promotion_authority != "NONE":
            raise SourceChangeEventError(
                "INGESTION_PROMOTION_AUTHORITY_INVALID"
            )

        if self.persistent_write != "NONE":
            raise SourceChangeEventError(
                "INGESTION_PERSISTENT_WRITE_INVALID"
            )

        if self.model_inference is not False:
            raise SourceChangeEventError(
                "INGESTION_MODEL_INFERENCE_INVALID"
            )

        if (
            self.registered_capability_execution
            is not False
        ):
            raise SourceChangeEventError(
                "INGESTION_REGISTERED_EXECUTION_INVALID"
            )


def verified_write_apply_event(
    receipt: dict[str, Any],
    binding: SourceLeafBinding,
    *,
    producer_id: str,
    producer_content_sha256: str,
    producer_contract_sha256: str,
    state_base_revision: str,
) -> VerifiedSourceChangeEvent:
    if not isinstance(
        receipt,
        dict,
    ):
        raise SourceChangeEventError(
            "WRITE_RECEIPT_TYPE_INVALID"
        )

    if set(receipt) != WRITE_RECEIPT_FIELDS:
        raise SourceChangeEventError(
            "WRITE_RECEIPT_FIELDS_INVALID"
        )

    if not isinstance(
        binding,
        SourceLeafBinding,
    ):
        raise SourceChangeEventError(
            "SOURCE_BINDING_TYPE_INVALID"
        )

    binding.validate()

    if binding.world != HOST_SOURCE:
        raise SourceChangeEventError(
            "WRITE_RECEIPT_WORLD_NOT_HOST_SOURCE"
        )

    if (
        receipt.get("schema")
        != WRITE_APPLY_RECEIPT_SCHEMA
    ):
        raise SourceChangeEventError(
            "WRITE_RECEIPT_SCHEMA_INVALID"
        )

    proposal_id = _require_text(
        receipt.get(
            "proposal_id"
        ),
        "WRITE_PROPOSAL_ID",
        maximum=512,
    )

    target = _require_relative_path(
        receipt.get(
            "target_relative_path"
        )
    )

    if (
        target
        != binding.target_relative_path
    ):
        raise SourceChangeEventError(
            "WRITE_RECEIPT_TARGET_MISMATCH"
        )

    old_sha = _require_sha256(
        receipt.get(
            "before_sha256"
        ),
        "WRITE_BEFORE",
    )

    candidate_sha = _require_sha256(
        receipt.get(
            "candidate_sha256"
        ),
        "WRITE_CANDIDATE",
    )

    post_sha = _require_sha256(
        receipt.get(
            "post_sha256"
        ),
        "WRITE_POST",
    )

    if candidate_sha != post_sha:
        raise SourceChangeEventError(
            "WRITE_POSTIMAGE_NOT_CANDIDATE"
        )

    if old_sha == post_sha:
        raise SourceChangeEventError(
            "WRITE_RECEIPT_NO_EFFECT"
        )

    if (
        receipt.get(
            "effect_verified"
        )
        is not True
    ):
        raise SourceChangeEventError(
            "WRITE_RECEIPT_EFFECT_NOT_VERIFIED"
        )

    _require_text(
        receipt.get(
            "approval_command"
        ),
        "WRITE_APPROVAL_COMMAND",
        maximum=4096,
    )

    _require_text(
        producer_id,
        "PRODUCER_ID",
        maximum=512,
    )

    _require_sha256(
        producer_content_sha256,
        "PRODUCER_CONTENT",
    )

    _require_sha256(
        producer_contract_sha256,
        "PRODUCER_CONTRACT",
    )

    _require_text(
        state_base_revision,
        "STATE_BASE_REVISION",
        maximum=256,
    )

    event = VerifiedSourceChangeEvent(
        schema=EVENT_SCHEMA,
        world=HOST_SOURCE,
        stable_node_id=(
            binding.stable_node_id
        ),
        target_relative_path=target,
        old_content_sha256=old_sha,
        new_content_sha256=post_sha,
        producer_id=producer_id,
        producer_event_id=proposal_id,
        producer_content_sha256=(
            producer_content_sha256
        ),
        producer_contract_sha256=(
            producer_contract_sha256
        ),
        state_base_revision=(
            state_base_revision
        ),
        evidence_sha256=(
            digest_json(receipt)
        ),
        effect_verified=True,
    )

    event.validate()

    return event


def _verified_transition_event(
    *,
    binding: SourceLeafBinding,
    old_content_sha256: str,
    new_content_sha256: str,
    producer_id: str,
    producer_event_id: str,
    producer_content_sha256: str,
    producer_contract_sha256: str,
    state_base_revision: str,
    evidence: object,
) -> VerifiedSourceChangeEvent:
    if not isinstance(
        binding,
        SourceLeafBinding,
    ):
        raise SourceChangeEventError(
            "SOURCE_BINDING_TYPE_INVALID"
        )

    binding.validate()

    if binding.world != HOST_SOURCE:
        raise SourceChangeEventError(
            "TRANSITION_WORLD_NOT_HOST_SOURCE"
        )

    old_sha = _require_sha256(
        old_content_sha256,
        "TRANSITION_OLD",
    )

    new_sha = _require_sha256(
        new_content_sha256,
        "TRANSITION_NEW",
    )

    if old_sha == new_sha:
        raise SourceChangeEventError(
            "TRANSITION_NO_EFFECT"
        )

    clean_producer_id = _require_text(
        producer_id,
        "PRODUCER_ID",
        maximum=512,
    )

    clean_event_id = _require_text(
        producer_event_id,
        "PRODUCER_EVENT_ID",
        maximum=512,
    )

    _require_sha256(
        producer_content_sha256,
        "PRODUCER_CONTENT",
    )

    _require_sha256(
        producer_contract_sha256,
        "PRODUCER_CONTRACT",
    )

    clean_state_base = _require_text(
        state_base_revision,
        "STATE_BASE_REVISION",
        maximum=256,
    )

    event = VerifiedSourceChangeEvent(
        schema=EVENT_SCHEMA,
        world=HOST_SOURCE,
        stable_node_id=(
            binding.stable_node_id
        ),
        target_relative_path=(
            binding.target_relative_path
        ),
        old_content_sha256=old_sha,
        new_content_sha256=new_sha,
        producer_id=clean_producer_id,
        producer_event_id=clean_event_id,
        producer_content_sha256=(
            producer_content_sha256
        ),
        producer_contract_sha256=(
            producer_contract_sha256
        ),
        state_base_revision=clean_state_base,
        evidence_sha256=digest_json(
            evidence
        ),
        effect_verified=True,
    )

    event.validate()

    return event


def verified_write_rollback_event(
    receipt: dict[str, object],
    proposal: dict[str, object],
    binding: SourceLeafBinding,
    *,
    producer_id: str,
    producer_content_sha256: str,
    producer_contract_sha256: str,
    state_base_revision: str,
) -> VerifiedSourceChangeEvent:
    if type(receipt) is not dict:
        raise SourceChangeEventError(
            "ROLLBACK_RECEIPT_TYPE_INVALID"
        )

    if set(receipt) != WRITE_ROLLBACK_RECEIPT_FIELDS:
        raise SourceChangeEventError(
            "ROLLBACK_RECEIPT_FIELDS_INVALID"
        )

    if type(proposal) is not dict:
        raise SourceChangeEventError(
            "ROLLBACK_PROPOSAL_TYPE_INVALID"
        )

    if set(proposal) != WRITE_PROPOSAL_FIELDS:
        raise SourceChangeEventError(
            "ROLLBACK_PROPOSAL_FIELDS_INVALID"
        )

    if (
        receipt.get("schema")
        != WRITE_ROLLBACK_RECEIPT_SCHEMA
    ):
        raise SourceChangeEventError(
            "ROLLBACK_RECEIPT_SCHEMA_INVALID"
        )

    proposal_id = _require_text(
        proposal.get("proposal_id"),
        "ROLLBACK_PROPOSAL_ID",
        maximum=512,
    )

    if (
        receipt.get("proposal_id")
        != proposal_id
    ):
        raise SourceChangeEventError(
            "ROLLBACK_PROPOSAL_ID_MISMATCH"
        )

    target = _require_relative_path(
        proposal.get(
            "target_relative_path"
        )
    )

    binding.validate()

    if target != binding.target_relative_path:
        raise SourceChangeEventError(
            "ROLLBACK_TARGET_BINDING_MISMATCH"
        )

    before_sha = _require_sha256(
        proposal.get("before_sha256"),
        "ROLLBACK_BEFORE",
    )

    candidate_sha = _require_sha256(
        proposal.get("candidate_sha256"),
        "ROLLBACK_CANDIDATE",
    )

    receipt_before = _require_sha256(
        receipt.get("before_sha256"),
        "ROLLBACK_RECEIPT_BEFORE",
    )

    restored_sha = _require_sha256(
        receipt.get("restored_sha256"),
        "ROLLBACK_RESTORED",
    )

    if receipt_before != before_sha:
        raise SourceChangeEventError(
            "ROLLBACK_BEFORE_MISMATCH"
        )

    if restored_sha != before_sha:
        raise SourceChangeEventError(
            "ROLLBACK_RESTORED_NOT_BEFORE"
        )

    if candidate_sha == restored_sha:
        raise SourceChangeEventError(
            "ROLLBACK_NO_EFFECT"
        )

    if (
        receipt.get("effect_verified")
        is not True
    ):
        raise SourceChangeEventError(
            "ROLLBACK_EFFECT_NOT_VERIFIED"
        )

    _require_text(
        receipt.get("rollback_command"),
        "ROLLBACK_COMMAND",
        maximum=4096,
    )

    proposal_head = _require_text(
        proposal.get("head"),
        "ROLLBACK_PROPOSAL_HEAD",
        maximum=256,
    )

    if proposal_head != state_base_revision:
        raise SourceChangeEventError(
            "ROLLBACK_STATE_BASE_MISMATCH"
        )

    return _verified_transition_event(
        binding=binding,
        old_content_sha256=(
            candidate_sha
        ),
        new_content_sha256=(
            restored_sha
        ),
        producer_id=producer_id,
        producer_event_id=proposal_id,
        producer_content_sha256=(
            producer_content_sha256
        ),
        producer_contract_sha256=(
            producer_contract_sha256
        ),
        state_base_revision=(
            state_base_revision
        ),
        evidence={
            "kind":
                "WRITE_ROLLBACK",
            "receipt":
                receipt,
            "proposal":
                proposal,
        },
    )


def verified_control_apply_event(
    request: dict[str, object],
    response: dict[str, object],
    binding: SourceLeafBinding,
    *,
    producer_id: str,
    producer_content_sha256: str,
    producer_contract_sha256: str,
    state_base_revision: str,
) -> VerifiedSourceChangeEvent:
    if type(request) is not dict:
        raise SourceChangeEventError(
            "CONTROL_REQUEST_TYPE_INVALID"
        )

    if set(request) != CONTROL_APPLY_REQUEST_FIELDS:
        raise SourceChangeEventError(
            "CONTROL_REQUEST_FIELDS_INVALID"
        )

    if type(response) is not dict:
        raise SourceChangeEventError(
            "CONTROL_RESPONSE_TYPE_INVALID"
        )

    if set(response) != CONTROL_APPLY_RESPONSE_FIELDS:
        raise SourceChangeEventError(
            "CONTROL_RESPONSE_FIELDS_INVALID"
        )

    _require_text(
        request.get("schema"),
        "CONTROL_REQUEST_SCHEMA",
        maximum=256,
    )

    _require_text(
        response.get("schema"),
        "CONTROL_RESPONSE_SCHEMA",
        maximum=256,
    )

    if request.get("action") != "APPLY_SELFDEV":
        raise SourceChangeEventError(
            "CONTROL_ACTION_INVALID"
        )

    task_id = _require_text(
        request.get("task_id"),
        "CONTROL_TASK_ID",
        maximum=512,
    )

    if response.get("task_id") != task_id:
        raise SourceChangeEventError(
            "CONTROL_TASK_ID_MISMATCH"
        )

    target = _require_relative_path(
        request.get(
            "target_relative_path"
        )
    )

    binding.validate()

    if target != binding.target_relative_path:
        raise SourceChangeEventError(
            "CONTROL_TARGET_BINDING_MISMATCH"
        )

    base_head = _require_text(
        request.get("base_head"),
        "CONTROL_BASE_HEAD",
        maximum=256,
    )

    if (
        response.get("base_head")
        != base_head
        or state_base_revision
        != base_head
    ):
        raise SourceChangeEventError(
            "CONTROL_STATE_BASE_MISMATCH"
        )

    before_sha = _require_sha256(
        request.get("before_sha256"),
        "CONTROL_BEFORE",
    )

    candidate_sha = _require_sha256(
        request.get("candidate_sha256"),
        "CONTROL_CANDIDATE",
    )

    if (
        response.get("before_sha256")
        != before_sha
    ):
        raise SourceChangeEventError(
            "CONTROL_BEFORE_MISMATCH"
        )

    if (
        response.get("candidate_sha256")
        != candidate_sha
    ):
        raise SourceChangeEventError(
            "CONTROL_CANDIDATE_MISMATCH"
        )

    host_after = _require_sha256(
        response.get("host_after_sha256"),
        "CONTROL_HOST_AFTER",
    )

    if host_after != candidate_sha:
        raise SourceChangeEventError(
            "CONTROL_POSTIMAGE_NOT_CANDIDATE"
        )

    if before_sha == host_after:
        raise SourceChangeEventError(
            "CONTROL_NO_EFFECT"
        )

    if (
        response.get("status")
        != "APPLIED_VERIFIED"
        or response.get(
            "host_repo_changed"
        )
        is not True
    ):
        raise SourceChangeEventError(
            "CONTROL_EFFECT_NOT_VERIFIED"
        )

    _require_text(
        response.get("output"),
        "CONTROL_OUTPUT",
        maximum=65536,
    )

    return _verified_transition_event(
        binding=binding,
        old_content_sha256=before_sha,
        new_content_sha256=host_after,
        producer_id=producer_id,
        producer_event_id=task_id,
        producer_content_sha256=(
            producer_content_sha256
        ),
        producer_contract_sha256=(
            producer_contract_sha256
        ),
        state_base_revision=base_head,
        evidence={
            "kind":
                "CONTROL_APPLY",
            "request":
                request,
            "response":
                response,
        },
    )




def event_to_leaf_change(
    event: VerifiedSourceChangeEvent,
    binding: SourceLeafBinding,
) -> LeafChange:
    if not isinstance(
        event,
        VerifiedSourceChangeEvent,
    ):
        raise SourceChangeEventError(
            "EVENT_TYPE_INVALID"
        )

    if not isinstance(
        binding,
        SourceLeafBinding,
    ):
        raise SourceChangeEventError(
            "SOURCE_BINDING_TYPE_INVALID"
        )

    event.validate()
    binding.validate()

    if event.world != binding.world:
        raise SourceChangeEventError(
            "EVENT_WORLD_BINDING_MISMATCH"
        )

    if (
        event.stable_node_id
        != binding.stable_node_id
    ):
        raise SourceChangeEventError(
            "EVENT_NODE_BINDING_MISMATCH"
        )

    if (
        event.target_relative_path
        != binding.target_relative_path
    ):
        raise SourceChangeEventError(
            "EVENT_TARGET_BINDING_MISMATCH"
        )

    return LeafChange(
        node_id=event.stable_node_id,
        old_content_sha256=(
            event.old_content_sha256
        ),
        new_content_sha256=(
            event.new_content_sha256
        ),
    )


def ingest_verified_host_source_change(
    event: VerifiedSourceChangeEvent,
    binding: SourceLeafBinding,
    dag: ResidentMerklePropagationDAG,
    *,
    focus_index: object | None = None,
) -> SourceChangeIngestionResult:
    if not isinstance(
        event,
        VerifiedSourceChangeEvent,
    ):
        raise SourceChangeEventError(
            "EVENT_TYPE_INVALID"
        )

    event.validate()

    if event.world != HOST_SOURCE:
        raise SourceChangeEventError(
            "INGESTION_WORLD_NOT_HOST_SOURCE"
        )

    if not isinstance(
        dag,
        ResidentMerklePropagationDAG,
    ):
        raise SourceChangeEventError(
            "MERKLE_DAG_TYPE_INVALID"
        )

    change = event_to_leaf_change(
        event,
        binding,
    )

    propagation = (
        dag.apply_leaf_change(
            change,
            focus_index=focus_index,
        )
    )

    result = SourceChangeIngestionResult(
        schema=INGESTION_SCHEMA,
        event_sha256=(
            event.event_sha256()
        ),
        propagation=propagation,
    )

    result.validate()

    return result
