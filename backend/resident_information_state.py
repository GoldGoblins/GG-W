"""Application-lifetime resident information state for GG Workbench.

The owner is deliberately narrow:

* one resident Merkle propagation DAG for explicitly bound source objects;
* one resident IncrementalFocusIndex for compiled-focus handles;
* no source writes;
* no filesystem discovery or scanning on the change path;
* no model, network or registered-capability execution;
* fail-closed state if a verified real host change cannot be reconciled with
  the resident preimage.

The controlled writer remains the authority boundary. This module only
maintains information-state identity after an already verified effect.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any

if __package__:
    from . import compiled_focus as _compiled_focus
    from . import incremental_focus as _incremental_focus
    from . import merkle_propagation as _merkle_propagation
    from . import source_change_event as _source_change_event
else:
    import compiled_focus as _compiled_focus
    import incremental_focus as _incremental_focus
    import merkle_propagation as _merkle_propagation
    import source_change_event as _source_change_event

CompiledFocusHandle = _compiled_focus.CompiledFocusHandle
FocusBinding = _compiled_focus.FocusBinding
FocusDependency = _compiled_focus.FocusDependency
IncrementalFocusIndex = _incremental_focus.IncrementalFocusIndex
ChildRef = _merkle_propagation.ChildRef
LeafSpec = _merkle_propagation.LeafSpec
ParentSpec = _merkle_propagation.ParentSpec
ResidentMerklePropagationDAG = (
    _merkle_propagation.ResidentMerklePropagationDAG
)
HOST_SOURCE = _source_change_event.HOST_SOURCE
SourceChangeIngestionResult = (
    _source_change_event.SourceChangeIngestionResult
)
SourceLeafBinding = _source_change_event.SourceLeafBinding
ingest_verified_host_source_change = (
    _source_change_event.ingest_verified_host_source_change
)
verified_write_apply_event = (
    _source_change_event.verified_write_apply_event
)

verified_write_rollback_event = (
    _source_change_event.verified_write_rollback_event
)
verified_control_apply_event = (
    _source_change_event.verified_control_apply_event
)



READY = "READY"
STALE_BLOCKED = "STALE_BLOCKED"

PROPOSAL_SCHEMA = (
    "gg.workbench.write-proposal.v1"
)

PROPOSAL_FIELDS = frozenset(
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


class ResidentInformationStateError(
    RuntimeError
):
    """Resident information-state contract violation."""


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
        raise ResidentInformationStateError(
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
        raise ResidentInformationStateError(
            label
            + "_TEXT_INVALID"
        )

    return value


def _sha256_bytes(
    value: bytes,
) -> str:
    return hashlib.sha256(
        value
    ).hexdigest()


def _regular_file_bytes(
    path: Path,
    label: str,
) -> bytes:
    candidate = Path(path)

    if (
        candidate.is_symlink()
        or not candidate.is_file()
    ):
        raise ResidentInformationStateError(
            label
            + "_FILE_INVALID"
        )

    return candidate.read_bytes()


def _relative_target(
    value: str,
) -> str:
    target = _require_text(
        value,
        "TARGET_RELATIVE_PATH",
        maximum=1024,
    )

    if (
        target.startswith("/")
        or "\\" in target
        or "//" in target
    ):
        raise ResidentInformationStateError(
            "TARGET_RELATIVE_PATH_INVALID"
        )

    if any(
        part in {
            "",
            ".",
            "..",
        }
        for part in target.split("/")
    ):
        raise ResidentInformationStateError(
            "TARGET_RELATIVE_PATH_INVALID"
        )

    return target


def _state_base_from_proposal(
    receipt: dict[str, Any],
    proposal: dict[str, Any],
    binding: SourceLeafBinding,
) -> str:
    if not isinstance(
        proposal,
        dict,
    ):
        raise ResidentInformationStateError(
            "PROPOSAL_TYPE_INVALID"
        )

    if set(proposal) != PROPOSAL_FIELDS:
        raise ResidentInformationStateError(
            "PROPOSAL_FIELDS_INVALID"
        )

    if proposal.get(
        "schema"
    ) != PROPOSAL_SCHEMA:
        raise ResidentInformationStateError(
            "PROPOSAL_SCHEMA_INVALID"
        )

    if (
        proposal.get(
            "proposal_id"
        )
        != receipt.get(
            "proposal_id"
        )
    ):
        raise ResidentInformationStateError(
            "PROPOSAL_RECEIPT_ID_MISMATCH"
        )

    target = _relative_target(
        str(
            proposal.get(
                "target_relative_path",
                "",
            )
        )
    )

    if (
        target
        != binding.target_relative_path
        or target
        != receipt.get(
            "target_relative_path"
        )
    ):
        raise ResidentInformationStateError(
            "PROPOSAL_RECEIPT_TARGET_MISMATCH"
        )

    for proposal_key, receipt_key in (
        (
            "before_sha256",
            "before_sha256",
        ),
        (
            "candidate_sha256",
            "candidate_sha256",
        ),
        (
            "approval_command",
            "approval_command",
        ),
    ):
        if (
            proposal.get(
                proposal_key
            )
            != receipt.get(
                receipt_key
            )
        ):
            raise ResidentInformationStateError(
                "PROPOSAL_RECEIPT_BINDING_MISMATCH:"
                + proposal_key
            )

    for key in (
        "before_sha256",
        "candidate_sha256",
        "diff_sha256",
        "proposal_gate_report_sha256",
    ):
        _require_sha256(
            proposal.get(key),
            "PROPOSAL_"
            + key.upper(),
        )

    head = _require_text(
        proposal.get("head"),
        "PROPOSAL_HEAD",
        maximum=64,
    )

    if (
        len(head) not in (
            40,
            64,
        )
        or any(
            character
            not in "0123456789abcdef"
            for character in head
        )
    ):
        raise ResidentInformationStateError(
            "PROPOSAL_HEAD_INVALID"
        )

    return head



@dataclass(frozen=True)
class ResidentSourceRegistration:
    binding: SourceLeafBinding
    initial_content_sha256: str
    producer_id: str
    producer_content_sha256: str
    producer_contract_sha256: str

    def validate(
        self,
    ) -> None:
        if not isinstance(
            self.binding,
            SourceLeafBinding,
        ):
            raise ResidentInformationStateError(
                "SOURCE_REGISTRATION_BINDING_TYPE_INVALID"
            )

        self.binding.validate()

        if self.binding.world != HOST_SOURCE:
            raise ResidentInformationStateError(
                "SOURCE_REGISTRATION_WORLD_INVALID"
            )

        _require_sha256(
            self.initial_content_sha256,
            "SOURCE_REGISTRATION_INITIAL_CONTENT",
        )

        _require_text(
            self.producer_id,
            "SOURCE_REGISTRATION_PRODUCER_ID",
            maximum=512,
        )

        _require_sha256(
            self.producer_content_sha256,
            "SOURCE_REGISTRATION_PRODUCER_CONTENT",
        )

        _require_sha256(
            self.producer_contract_sha256,
            "SOURCE_REGISTRATION_PRODUCER_CONTRACT",
        )


@dataclass(frozen=True)
class ResidentInformationSnapshot:
    status: str
    stable_node_id: str
    target_relative_path: str
    current_content_sha256: str
    current_source_root_sha256: str
    last_event_sha256: str
    event_count: int
    last_reason: str
    action_authority: str = "NONE"
    promotion_authority: str = "NONE"
    persistent_write: str = "NONE"
    model_inference: bool = False

    def validate(
        self,
    ) -> None:
        if self.status not in {
            READY,
            STALE_BLOCKED,
        }:
            raise ResidentInformationStateError(
                "SNAPSHOT_STATUS_INVALID"
            )

        _require_text(
            self.stable_node_id,
            "SNAPSHOT_NODE_ID",
            maximum=2048,
        )

        _relative_target(
            self.target_relative_path
        )

        _require_sha256(
            self.current_content_sha256,
            "SNAPSHOT_CONTENT",
        )

        _require_sha256(
            self.current_source_root_sha256,
            "SNAPSHOT_SOURCE_ROOT",
        )

        if self.last_event_sha256:
            _require_sha256(
                self.last_event_sha256,
                "SNAPSHOT_EVENT",
            )

        if (
            not isinstance(
                self.event_count,
                int,
            )
            or self.event_count < 0
        ):
            raise ResidentInformationStateError(
                "SNAPSHOT_EVENT_COUNT_INVALID"
            )

        if not isinstance(
            self.last_reason,
            str,
        ):
            raise ResidentInformationStateError(
                "SNAPSHOT_REASON_INVALID"
            )

        if self.action_authority != "NONE":
            raise ResidentInformationStateError(
                "SNAPSHOT_ACTION_AUTHORITY_INVALID"
            )

        if self.promotion_authority != "NONE":
            raise ResidentInformationStateError(
                "SNAPSHOT_PROMOTION_AUTHORITY_INVALID"
            )

        if self.persistent_write != "NONE":
            raise ResidentInformationStateError(
                "SNAPSHOT_PERSISTENT_WRITE_INVALID"
            )

        if self.model_inference is not False:
            raise ResidentInformationStateError(
                "SNAPSHOT_MODEL_INFERENCE_INVALID"
            )


class WorkbenchResidentInformationState:
    def __init__(
        self,
        *,
        source_binding: SourceLeafBinding,
        initial_content_sha256: str,
        producer_id: str,
        producer_content_sha256: str,
        producer_contract_sha256: str,
        additional_sources: tuple[
            ResidentSourceRegistration,
            ...,
        ] = (),
        max_focus_entries: int = 256,
    ) -> None:
        primary = ResidentSourceRegistration(
            binding=source_binding,
            initial_content_sha256=(
                initial_content_sha256
            ),
            producer_id=producer_id,
            producer_content_sha256=(
                producer_content_sha256
            ),
            producer_contract_sha256=(
                producer_contract_sha256
            ),
        )

        primary.validate()

        if not isinstance(
            additional_sources,
            tuple,
        ):
            raise ResidentInformationStateError(
                "ADDITIONAL_SOURCES_TYPE_INVALID"
            )

        registrations = (
            primary,
            *additional_sources,
        )

        if (
            len(registrations) < 1
            or len(registrations) > 16
        ):
            raise ResidentInformationStateError(
                "SOURCE_REGISTRATION_COUNT_INVALID"
            )

        for registration in registrations:
            if not isinstance(
                registration,
                ResidentSourceRegistration,
            ):
                raise ResidentInformationStateError(
                    "SOURCE_REGISTRATION_TYPE_INVALID"
                )

            registration.validate()

        if (
            not isinstance(
                max_focus_entries,
                int,
            )
            or max_focus_entries < 1
            or max_focus_entries > 4096
        ):
            raise ResidentInformationStateError(
                "FOCUS_CAPACITY_INVALID"
            )

        by_node: dict[
            str,
            ResidentSourceRegistration,
        ] = {}

        by_target: dict[
            str,
            ResidentSourceRegistration,
        ] = {}

        parent_ids: dict[str, str] = {}

        for registration in registrations:
            binding = registration.binding

            if binding.stable_node_id in by_node:
                raise ResidentInformationStateError(
                    "SOURCE_NODE_DUPLICATE"
                )

            if (
                binding.target_relative_path
                in by_target
            ):
                raise ResidentInformationStateError(
                    "SOURCE_TARGET_DUPLICATE"
                )

            by_node[
                binding.stable_node_id
            ] = registration

            by_target[
                binding.target_relative_path
            ] = registration

            suffix = hashlib.sha256(
                (
                    binding.stable_node_id
                    + "\n"
                    + binding.target_relative_path
                ).encode("utf-8")
            ).hexdigest()[:24]

            parent_ids[
                binding.stable_node_id
            ] = (
                "source-neighborhood:workbench:"
                + suffix
            )

        self._source_binding = (
            primary.binding
        )

        self._producer_id = (
            primary.producer_id
        )

        self._producer_content_sha256 = (
            primary.producer_content_sha256
        )

        self._producer_contract_sha256 = (
            primary.producer_contract_sha256
        )

        self._source_registrations = (
            registrations
        )

        self._sources_by_node = by_node
        self._sources_by_target = by_target
        self._source_parent_node_ids = (
            parent_ids
        )

        self._source_parent_node_id = (
            parent_ids[
                primary.binding
                .stable_node_id
            ]
        )

        self._focus_index = (
            IncrementalFocusIndex(
                max_entries=max_focus_entries
            )
        )

        leaves = tuple(
            LeafSpec(
                node_id=(
                    registration
                    .binding
                    .stable_node_id
                ),
                content_sha256=(
                    registration
                    .initial_content_sha256
                ),
            )
            for registration in registrations
        )

        parents = tuple(
            ParentSpec(
                node_id=(
                    parent_ids[
                        registration
                        .binding
                        .stable_node_id
                    ]
                ),
                domain=(
                    "SOURCE_NEIGHBORHOOD"
                ),
                scope=(
                    "workbench-controlled-source"
                ),
                children=(
                    ChildRef(
                        namespace=(
                            registration
                            .binding
                            .stable_node_id
                            .removeprefix(
                                "file:"
                            )
                        ),
                        node_id=(
                            registration
                            .binding
                            .stable_node_id
                        ),
                        kind="LEAF",
                    ),
                ),
                dependency_namespaces=(
                    "source",
                ),
            )
            for registration in registrations
        )

        self._dag = (
            ResidentMerklePropagationDAG(
                leaves,
                parents,
            )
        )

        self._status = READY
        self._last_reason = ""
        self._last_event_sha256 = ""
        self._event_count = 0

    @classmethod
    def bootstrap_limited_write(
        cls,
        *,
        project_root: Path,
        target_relative_path: str,
        producer_id: str,
        producer_path: Path,
        producer_contract_path: Path,
        repo_project_prefix: str = (
            "projects/gg-ai-desktop"
        ),
        max_focus_entries: int = 256,
    ) -> "WorkbenchResidentInformationState":
        project = Path(
            project_root
        ).resolve(strict=True)

        if not project.is_dir():
            raise ResidentInformationStateError(
                "PROJECT_ROOT_INVALID"
            )

        target_relative = (
            _relative_target(
                target_relative_path
            )
        )

        prefix = _relative_target(
            repo_project_prefix
        )

        target = (
            project
            / target_relative
        )

        target_bytes = (
            _regular_file_bytes(
                target,
                "CONTROLLED_TARGET",
            )
        )

        producer_bytes = (
            _regular_file_bytes(
                Path(producer_path),
                "WRITE_PRODUCER",
            )
        )

        contract_bytes = (
            _regular_file_bytes(
                Path(
                    producer_contract_path
                ),
                "WRITE_CONTRACT",
            )
        )

        binding = SourceLeafBinding(
            world=HOST_SOURCE,
            stable_node_id=(
                "file:"
                + prefix
                + "/"
                + target_relative
            ),
            target_relative_path=(
                target_relative
            ),
        )

        return cls(
            source_binding=binding,
            initial_content_sha256=(
                _sha256_bytes(
                    target_bytes
                )
            ),
            producer_id=producer_id,
            producer_content_sha256=(
                _sha256_bytes(
                    producer_bytes
                )
            ),
            producer_contract_sha256=(
                _sha256_bytes(
                    contract_bytes
                )
            ),
            max_focus_entries=(
                max_focus_entries
            ),
        )

    @classmethod
    def bootstrap_workbench_sources(
        cls,
        *,
        repo_root: Path,
        limited_target_relative_path: str,
        limited_producer_path: Path,
        limited_producer_contract_path: Path,
        control_target_relative_path: str,
        control_producer_path: Path,
        control_producer_contract_path: Path,
        project_relative_root: str = (
            "projects/gg-ai-desktop"
        ),
        max_focus_entries: int = 256,
    ) -> "WorkbenchResidentInformationState":
        repo = Path(
            repo_root
        ).resolve(strict=True)

        if not repo.is_dir():
            raise ResidentInformationStateError(
                "REPO_ROOT_INVALID"
            )

        project_prefix = (
            _relative_target(
                project_relative_root
            )
            if project_relative_root else ""
        )

        limited_relative = (
            _relative_target(
                limited_target_relative_path
            )
        )

        control_relative = (
            _relative_target(
                control_target_relative_path
            )
        )

        limited_target = (
            repo
            / project_prefix
            / limited_relative
        )

        control_target = (
            repo
            / control_relative
        )

        limited_target_bytes = (
            _regular_file_bytes(
                limited_target,
                "LIMITED_CONTROLLED_TARGET",
            )
        )

        control_target_bytes = (
            _regular_file_bytes(
                control_target,
                "CONTROL_PLANE_TARGET",
            )
        )

        limited_producer_bytes = (
            _regular_file_bytes(
                Path(
                    limited_producer_path
                ),
                "LIMITED_WRITE_PRODUCER",
            )
        )

        limited_contract_bytes = (
            _regular_file_bytes(
                Path(
                    limited_producer_contract_path
                ),
                "LIMITED_WRITE_CONTRACT",
            )
        )

        control_producer_bytes = (
            _regular_file_bytes(
                Path(
                    control_producer_path
                ),
                "CONTROL_PLANE_PRODUCER",
            )
        )

        control_contract_bytes = (
            _regular_file_bytes(
                Path(
                    control_producer_contract_path
                ),
                "CONTROL_PLANE_CONTRACT",
            )
        )

        limited_binding = (
            SourceLeafBinding(
                world=HOST_SOURCE,
                stable_node_id=(
                    "file:"
                    + (project_prefix + "/" if project_prefix else "")
                    + limited_relative
                ),
                target_relative_path=(
                    limited_relative
                ),
            )
        )

        control_binding = (
            SourceLeafBinding(
                world=HOST_SOURCE,
                stable_node_id=(
                    "file:"
                    + control_relative
                ),
                target_relative_path=(
                    control_relative
                ),
            )
        )

        control_registration = (
            ResidentSourceRegistration(
                binding=control_binding,
                initial_content_sha256=(
                    _sha256_bytes(
                        control_target_bytes
                    )
                ),
                producer_id=(
                    "control_plane_runner.execute"
                ),
                producer_content_sha256=(
                    _sha256_bytes(
                        control_producer_bytes
                    )
                ),
                producer_contract_sha256=(
                    _sha256_bytes(
                        control_contract_bytes
                    )
                ),
            )
        )

        return cls(
            source_binding=limited_binding,
            initial_content_sha256=(
                _sha256_bytes(
                    limited_target_bytes
                )
            ),
            producer_id=(
                "write_runner._approve"
            ),
            producer_content_sha256=(
                _sha256_bytes(
                    limited_producer_bytes
                )
            ),
            producer_contract_sha256=(
                _sha256_bytes(
                    limited_contract_bytes
                )
            ),
            additional_sources=(
                control_registration,
            ),
            max_focus_entries=(
                max_focus_entries
            ),
        )

    @property
    def status(
        self,
    ) -> str:
        return self._status

    @property
    def source_binding(
        self,
    ) -> SourceLeafBinding:
        return self._source_binding

    @property
    def source_bindings(
        self,
    ) -> tuple[SourceLeafBinding, ...]:
        return tuple(
            registration.binding
            for registration
            in self._source_registrations
        )

    def _require_ready(
        self,
    ) -> None:
        if self._status != READY:
            raise ResidentInformationStateError(
                "RESIDENT_INFORMATION_STATE_BLOCKED:"
                + self._last_reason
            )

    def _registration_for_node(
        self,
        stable_node_id: str,
    ) -> ResidentSourceRegistration:
        registration = (
            self._sources_by_node.get(
                stable_node_id
            )
        )

        if registration is None:
            raise ResidentInformationStateError(
                "SOURCE_NODE_NOT_REGISTERED:"
                + stable_node_id
            )

        return registration

    def _registration_for_target(
        self,
        target_relative_path: str,
    ) -> ResidentSourceRegistration:
        target = _relative_target(
            target_relative_path
        )

        registration = (
            self._sources_by_target.get(
                target
            )
        )

        if registration is None:
            raise ResidentInformationStateError(
                "SOURCE_TARGET_NOT_REGISTERED:"
                + target
            )

        return registration

    def source_binding_for(
        self,
        stable_node_id: str,
    ) -> SourceLeafBinding:
        return (
            self
            ._registration_for_node(
                stable_node_id
            )
            .binding
        )

    def current_content_sha256(
        self,
    ) -> str:
        return self.current_content_sha256_for(
            self._source_binding
            .stable_node_id
        )

    def current_content_sha256_for(
        self,
        stable_node_id: str,
    ) -> str:
        registration = (
            self._registration_for_node(
                stable_node_id
            )
        )

        return self._dag.current_root(
            registration.binding
            .stable_node_id
        )

    def current_source_root_sha256(
        self,
    ) -> str:
        return (
            self.current_source_root_sha256_for(
                self._source_binding
                .stable_node_id
            )
        )

    def current_source_root_sha256_for(
        self,
        stable_node_id: str,
    ) -> str:
        self._registration_for_node(
            stable_node_id
        )

        return self._dag.current_root(
            self._source_parent_node_ids[
                stable_node_id
            ]
        )

    def source_dependency(
        self,
    ) -> FocusDependency:
        return self.source_dependency_for(
            self._source_binding
            .stable_node_id
        )

    def source_dependency_for(
        self,
        stable_node_id: str,
    ) -> FocusDependency:
        return FocusDependency(
            namespace="source",
            root_sha256=(
                self
                .current_source_root_sha256_for(
                    stable_node_id
                )
            ),
        )

    def register_focus(
        self,
        binding: FocusBinding,
        handle: CompiledFocusHandle,
    ) -> CompiledFocusHandle:
        self._require_ready()

        return self._focus_index.register(
            binding,
            handle,
        )

    def lookup_focus(
        self,
        handle_id: str,
    ) -> CompiledFocusHandle | None:
        if self._status != READY:
            return None

        return self._focus_index.lookup(
            handle_id
        )

    def block_after_verified_host_change(
        self,
        reason: str,
    ) -> None:
        clean = _require_text(
            reason,
            "BLOCK_REASON",
            maximum=1024,
        )

        self._status = STALE_BLOCKED
        self._last_reason = clean

    def _ingest_event(
        self,
        event: Any,
        binding: SourceLeafBinding,
    ) -> SourceChangeIngestionResult:
        result = (
            ingest_verified_host_source_change(
                event,
                binding,
                self._dag,
                focus_index=(
                    self._focus_index
                ),
            )
        )

        self._last_event_sha256 = (
            event.event_sha256()
        )

        self._event_count += 1

        return result

    def _sync_failed(
        self,
        exc: Exception,
    ) -> ResidentInformationStateError:
        self._status = STALE_BLOCKED
        self._last_reason = (
            type(exc).__name__
            + ":"
            + str(exc)
        )

        return ResidentInformationStateError(
            "VERIFIED_HOST_EFFECT_RESIDENT_SYNC_FAILED:"
            + self._last_reason
        )

    def ingest_verified_write_completion(
        self,
        receipt: dict[str, Any],
        proposal: dict[str, Any],
    ) -> SourceChangeIngestionResult:
        self._require_ready()

        try:
            state_base = (
                _state_base_from_proposal(
                    receipt,
                    proposal,
                    self._source_binding,
                )
            )

            event = (
                verified_write_apply_event(
                    receipt,
                    self._source_binding,
                    producer_id=(
                        self._producer_id
                    ),
                    producer_content_sha256=(
                        self
                        ._producer_content_sha256
                    ),
                    producer_contract_sha256=(
                        self
                        ._producer_contract_sha256
                    ),
                    state_base_revision=(
                        state_base
                    ),
                )
            )

            return self._ingest_event(
                event,
                self._source_binding,
            )

        except Exception as exc:
            raise self._sync_failed(
                exc
            ) from exc

    def ingest_verified_write_rollback(
        self,
        receipt: dict[str, Any],
        proposal: dict[str, Any],
    ) -> SourceChangeIngestionResult:
        self._require_ready()

        try:
            registration = (
                self._registration_for_target(
                    self._source_binding
                    .target_relative_path
                )
            )

            state_base = _require_text(
                proposal.get("head"),
                "ROLLBACK_STATE_BASE",
                maximum=256,
            )

            event = (
                verified_write_rollback_event(
                    receipt,
                    proposal,
                    registration.binding,
                    producer_id=(
                        "write_runner._rollback"
                    ),
                    producer_content_sha256=(
                        registration
                        .producer_content_sha256
                    ),
                    producer_contract_sha256=(
                        registration
                        .producer_contract_sha256
                    ),
                    state_base_revision=(
                        state_base
                    ),
                )
            )

            return self._ingest_event(
                event,
                registration.binding,
            )

        except Exception as exc:
            raise self._sync_failed(
                exc
            ) from exc

    def ingest_verified_control_apply(
        self,
        request: dict[str, Any],
        response: dict[str, Any],
    ) -> SourceChangeIngestionResult:
        self._require_ready()

        try:
            target = _relative_target(
                str(
                    request.get(
                        "target_relative_path",
                        "",
                    )
                )
            )

            registration = (
                self._registration_for_target(
                    target
                )
            )

            state_base = _require_text(
                request.get("base_head"),
                "CONTROL_STATE_BASE",
                maximum=256,
            )

            event = (
                verified_control_apply_event(
                    request,
                    response,
                    registration.binding,
                    producer_id=(
                        registration
                        .producer_id
                    ),
                    producer_content_sha256=(
                        registration
                        .producer_content_sha256
                    ),
                    producer_contract_sha256=(
                        registration
                        .producer_contract_sha256
                    ),
                    state_base_revision=(
                        state_base
                    ),
                )
            )

            return self._ingest_event(
                event,
                registration.binding,
            )

        except Exception as exc:
            raise self._sync_failed(
                exc
            ) from exc

    def snapshot(
        self,
    ) -> ResidentInformationSnapshot:
        result = ResidentInformationSnapshot(
            status=self._status,
            stable_node_id=(
                self._source_binding
                .stable_node_id
            ),
            target_relative_path=(
                self._source_binding
                .target_relative_path
            ),
            current_content_sha256=(
                self.current_content_sha256()
            ),
            current_source_root_sha256=(
                self
                .current_source_root_sha256()
            ),
            last_event_sha256=(
                self._last_event_sha256
            ),
            event_count=(
                self._event_count
            ),
            last_reason=(
                self._last_reason
            ),
        )

        result.validate()

        return result
