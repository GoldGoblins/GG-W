from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
from pathlib import PurePosixPath
from typing import Any, Callable
import uuid

from . import post_draft_coordinator
from . import qml_preflight_runner
from . import repair_model_runner


DRIVER_COMMAND_SCHEMA = (
    "gg.live-aid.post-draft-qml-command.v1"
)

DRIVER_SNAPSHOT_SCHEMA = (
    "gg.live-aid.post-draft-qml-snapshot.v1"
)

AUTHORITY_PROVENANCE_SCHEMA = (
    "gg.live-aid.post-draft-authority-provenance.v1"
)


class DriverError(RuntimeError):
    pass


class DriverState(str, Enum):
    DRAFT = "DRAFT"
    VALIDATING = "VALIDATING"
    REPAIRING = "REPAIRING"
    READY_TO_RUN = "READY_TO_RUN"
    BLOCKED = "BLOCKED"


class DriverCommandKind(str, Enum):
    PREFLIGHT = "PREFLIGHT"
    REPAIR = "REPAIR"


EXTERNAL_FAULT_LAYERS = {
    "TRANSPORT",
    "HARNESS",
    "SANDBOX",
    "TARGET",
    "REGRESSION",
}


@dataclass(frozen=True)
class DriverCommand:
    command_id: str
    kind: DriverCommandKind
    request: dict[str, Any]
    source_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": DRIVER_COMMAND_SCHEMA,
            "command_id": self.command_id,
            "kind": self.kind.value,
            "request": dict(self.request),
            "source_sha256":
                self.source_sha256,
            "persistent_write_authority":
                "NONE",
            "execution_authority":
                "NONE",
            "network_authority":
                "NONE",
        }


@dataclass(frozen=True)
class DriverSnapshot:
    state: DriverState
    source: str
    source_sha256: str
    pending_command_kind: str
    repair_attempts: int
    execution_ready: bool
    blocked_fault_layer: str
    blocked_reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": DRIVER_SNAPSHOT_SCHEMA,
            "state": self.state.value,
            "source": self.source,
            "source_sha256":
                self.source_sha256,
            "pending_command_kind":
                self.pending_command_kind,
            "repair_attempts":
                self.repair_attempts,
            "execution_ready":
                self.execution_ready,
            "blocked_fault_layer":
                self.blocked_fault_layer,
            "blocked_reason":
                self.blocked_reason,
            "persistent_write_authority":
                "NONE",
            "execution_authority":
                "NONE",
            "network_authority":
                "NONE",
        }


def _sha(
    source: str,
) -> str:
    return hashlib.sha256(
        source.encode("utf-8")
    ).hexdigest()


def _require_sha(
    value: object,
    label: str,
) -> str:
    if (
        not isinstance(
            value,
            str,
        )
        or len(value) != 64
        or any(
            char not in "0123456789abcdef"
            for char in value
        )
    ):
        raise DriverError(
            label + "_SHA256"
        )

    return value


class PostDraftQmlDriver:
    """Stage-E command driver.

    This object does not execute QML Gate, model inference,
    shell commands, network actions, Git mutations, or disk writes.

    It translates the pure post-draft coordinator state machine into
    requests for the already-verified Stage-D preflight and repair
    runners. An external async harness may execute those commands.

    Stage-D model output remains UNTRUSTED and retains its original
    HUMAN_EXPLICIT_IN_MEMORY_ONLY proposal authority. This driver
    creates a separate Stage-E system decision authorizing only an
    automatic mutation of the private in-memory candidate.
    """

    def __init__(
        self,
        *,
        object_id: str,
        source_name: str,
        source_relative_path: str,
        max_repair_attempts: int = 3,
        id_factory: Callable[[], str] | None = None,
    ):
        relative = PurePosixPath(
            source_relative_path
        )

        if (
            relative.is_absolute()
            or ".." in relative.parts
            or relative.name != source_name
            or relative.suffix.lower() != ".qml"
        ):
            raise DriverError(
                "SOURCE_RELATIVE_PATH_INVALID"
            )

        self.object_id = object_id
        self.source_name = source_name
        self.source_relative_path = (
            relative.as_posix()
        )

        self._id_factory = (
            id_factory
            if id_factory is not None
            else lambda: uuid.uuid4().hex
        )

        self._coordinator = (
            post_draft_coordinator
            .PostDraftCoordinator(
                object_id=object_id,
                source_name=source_name,
                language="qml",
                max_repair_attempts=
                    max_repair_attempts,
            )
        )

        self._state = DriverState.DRAFT

        self._pending: DriverCommand | None = None

        self._last_preflight: dict[str, Any] | None = None

        self._blocked_fault_layer = ""
        self._blocked_reason = ""

    @property
    def source(self) -> str:
        return self._coordinator.source

    @property
    def state(self) -> DriverState:
        return self._state

    def snapshot(
        self,
    ) -> DriverSnapshot:
        coordinator = (
            self._coordinator.snapshot()
        )

        pending = (
            ""
            if self._pending is None
            else self._pending.kind.value
        )

        return DriverSnapshot(
            state=self._state,
            source=self.source,
            source_sha256=
                coordinator.source_sha256,
            pending_command_kind=pending,
            repair_attempts=
                coordinator.repair_attempts,
            execution_ready=(
                self._state
                == DriverState.READY_TO_RUN
                and coordinator.execution_ready
            ),
            blocked_fault_layer=
                self._blocked_fault_layer,
            blocked_reason=
                self._blocked_reason,
        )

    def update_draft(
        self,
        source: str,
    ) -> DriverSnapshot:
        if self._state != DriverState.DRAFT:
            raise DriverError(
                "DRIVER_DRAFT_ALREADY_COMPLETE"
            )

        self._coordinator.update_draft(
            source
        )

        return self.snapshot()

    def _new_id(
        self,
        prefix: str,
    ) -> str:
        token = self._id_factory()

        if (
            not isinstance(token, str)
            or not token
            or len(token) > 128
        ):
            raise DriverError(
                "ID_FACTORY_INVALID"
            )

        return prefix + token

    def _preflight_command(
        self,
        *,
        reason: str,
    ) -> DriverCommand:
        source = self.source
        source_sha = _sha(source)

        request_id = self._new_id(
            "preflight-"
        )

        request = (
            qml_preflight_runner
            .validate_request(
                {
                    "schema":
                        qml_preflight_runner
                        .REQUEST_SCHEMA,
                    "request_id":
                        request_id,
                    "object_id":
                        self.object_id,
                    "source_name":
                        self.source_name,
                    "source_relative_path":
                        self.source_relative_path,
                    "language":
                        "qml",
                    "source":
                        source,
                    "source_sha256":
                        source_sha,
                }
            )
        )

        command = DriverCommand(
            command_id=self._new_id(
                "command-"
            ),
            kind=DriverCommandKind.PREFLIGHT,
            request=request,
            source_sha256=source_sha,
        )

        self._pending = command
        self._state = (
            DriverState.VALIDATING
        )

        return command

    def mark_draft_complete(
        self,
    ) -> DriverCommand:
        if self._state != DriverState.DRAFT:
            raise DriverError(
                "DRIVER_DRAFT_COMPLETE_STATE"
            )

        action = (
            self._coordinator
            .mark_draft_complete()
        )

        if (
            action.kind
            != post_draft_coordinator
            .ActionKind.VALIDATE
        ):
            raise DriverError(
                "COORDINATOR_DID_NOT_REQUEST_VALIDATION"
            )

        return self._preflight_command(
            reason="DRAFT_COMPLETE"
        )

    def _require_pending(
        self,
        kind: DriverCommandKind,
    ) -> DriverCommand:
        command = self._pending

        if (
            command is None
            or command.kind != kind
        ):
            raise DriverError(
                "PENDING_COMMAND_MISMATCH"
            )

        return command

    def accept_preflight_response(
        self,
        response: dict[str, Any],
    ) -> DriverCommand | None:
        command = self._require_pending(
            DriverCommandKind.PREFLIGHT
        )

        request = command.request

        validated = (
            qml_preflight_runner
            .validate_response(
                response,
                expected_request_id=
                    request["request_id"],
                expected_object_id=
                    self.object_id,
                expected_source_sha256=
                    command.source_sha256,
            )
        )

        status = validated.get(
            "status"
        )

        gate_status = validated.get(
            "gate_status"
        )

        if (
            status not in {"PASS", "FAIL"}
            or gate_status
            not in {"PASS", "FAIL"}
            or status != gate_status
        ):
            raise DriverError(
                "PREFLIGHT_STATUS_INCONSISTENT"
            )

        diagnostics = validated.get(
            "diagnostics",
        )

        if not isinstance(
            diagnostics,
            list,
        ):
            raise DriverError(
                "PREFLIGHT_DIAGNOSTICS_INVALID"
            )

        if status == "PASS":
            action = (
                self._coordinator
                .accept_validation(
                    {
                        "schema":
                            post_draft_coordinator
                            .VALIDATION_SCHEMA,
                        "source_sha256":
                            command.source_sha256,
                        "status": "PASS",
                        "fault_layer": "NONE",
                        "diagnostics": [],
                    }
                )
            )

            if (
                action.kind
                != post_draft_coordinator
                .ActionKind.PROMOTE_READY
            ):
                raise DriverError(
                    "COORDINATOR_PASS_ACTION"
                )

            ready = (
                self._coordinator
                .promote_ready()
            )

            if not ready.execution_ready:
                raise DriverError(
                    "COORDINATOR_NOT_READY"
                )

            self._pending = None
            self._last_preflight = validated
            self._state = (
                DriverState.READY_TO_RUN
            )

            return None

        if not diagnostics:
            raise DriverError(
                "SOURCE_FAIL_WITHOUT_DIAGNOSTICS"
            )

        report_sha = _require_sha(
            validated.get(
                "gate_report_sha256"
            ),
            "PREFLIGHT_REPORT",
        )

        action = (
            self._coordinator
            .accept_validation(
                {
                    "schema":
                        post_draft_coordinator
                        .VALIDATION_SCHEMA,
                    "source_sha256":
                        command.source_sha256,
                    "status": "FAIL",
                    "fault_layer": "SOURCE",
                    "diagnostics":
                        diagnostics,
                }
            )
        )

        if (
            action.kind
            != post_draft_coordinator
            .ActionKind.REPAIR
        ):
            self._pending = None
            self._state = (
                DriverState.BLOCKED
            )
            self._blocked_fault_layer = (
                "SOURCE"
            )
            self._blocked_reason = (
                action.reason
            )
            return None

        request_id = self._new_id(
            "repair-model-"
        )

        repair_request = (
            repair_model_runner
            .validate_request(
                {
                    "schema":
                        repair_model_runner
                        .REQUEST_SCHEMA,
                    "request_id":
                        request_id,
                    "object_id":
                        self.object_id,
                    "source_name":
                        self.source_name,
                    "language": "qml",
                    "source":
                        self.source,
                    "source_sha256":
                        command.source_sha256,
                    "preflight_report_sha256":
                        report_sha,
                    "diagnostics":
                        diagnostics,
                }
            )
        )

        repair_command = DriverCommand(
            command_id=self._new_id(
                "command-"
            ),
            kind=DriverCommandKind.REPAIR,
            request=repair_request,
            source_sha256=
                command.source_sha256,
        )

        self._last_preflight = validated
        self._pending = repair_command
        self._state = (
            DriverState.REPAIRING
        )

        return repair_command

    def _stage_e_candidate(
        self,
        validated: dict[str, Any],
    ) -> dict[str, Any]:
        if (
            validated.get(
                "model_output_authority"
            )
            != "UNTRUSTED_MODEL_OUTPUT"
        ):
            raise DriverError(
                "MODEL_OUTPUT_AUTHORITY"
            )

        if (
            validated.get(
                "apply_authority"
            )
            != "HUMAN_EXPLICIT_IN_MEMORY_ONLY"
        ):
            raise DriverError(
                "STAGE_D_PROPOSAL_AUTHORITY"
            )

        if (
            validated.get(
                "persistent_write_authority"
            )
            != "NONE"
            or validated.get(
                "execution_authority"
            )
            != "NONE"
            or validated.get(
                "network_authority"
            )
            != "NONE"
        ):
            raise DriverError(
                "MODEL_PROPOSAL_ACTION_AUTHORITY"
            )

        if (
            validated.get(
                "preflight_required_after_apply"
            )
            is not True
        ):
            raise DriverError(
                "POST_APPLY_PREFLIGHT_NOT_REQUIRED"
            )

        source_sha = _require_sha(
            validated.get(
                "source_sha256"
            ),
            "PROPOSAL_SOURCE",
        )

        candidate = validated.get(
            "candidate_source"
        )

        if not isinstance(
            candidate,
            str,
        ):
            raise DriverError(
                "PROPOSAL_CANDIDATE_SOURCE"
            )

        candidate_sha = _sha(
            candidate
        )

        if (
            validated.get(
                "candidate_sha256"
            )
            != candidate_sha
        ):
            raise DriverError(
                "PROPOSAL_CANDIDATE_SHA"
            )

        return {
            "schema":
                post_draft_coordinator
                .CANDIDATE_SCHEMA,
            "source_sha256":
                source_sha,
            "candidate_source":
                candidate,
            "candidate_sha256":
                candidate_sha,
            "model_output_authority":
                "UNTRUSTED_MODEL_OUTPUT",
            "apply_authority":
                "SYSTEM_AUTOMATIC_IN_MEMORY_ONLY",
            "persistent_write_authority":
                "NONE",
            "execution_authority":
                "NONE",
            "network_authority":
                "NONE",
            "authority_provenance": {
                "schema":
                    AUTHORITY_PROVENANCE_SCHEMA,
                "model_proposal_apply_authority":
                    "HUMAN_EXPLICIT_IN_MEMORY_ONLY",
                "system_apply_authority":
                    "SYSTEM_AUTOMATIC_IN_MEMORY_ONLY",
                "system_apply_scope":
                    "PRIVATE_COORDINATOR_CANDIDATE_ONLY",
                "persistent_write_authority":
                    "NONE",
                "execution_authority":
                    "NONE",
                "network_authority":
                    "NONE",
                "reason":
                    "POST_DRAFT_AUTOMATIC_REPAIR",
            },
        }

    def accept_repair_response(
        self,
        response: dict[str, Any],
    ) -> DriverCommand:
        command = self._require_pending(
            DriverCommandKind.REPAIR
        )

        request = command.request

        validated = (
            repair_model_runner
            .validate_response(
                response,
                expected_request_id=
                    request["request_id"],
                expected_object_id=
                    self.object_id,
                expected_source_sha256=
                    command.source_sha256,
            )
        )

        stage_e_candidate = (
            self._stage_e_candidate(
                validated
            )
        )

        action = (
            self._coordinator
            .accept_repair_candidate(
                stage_e_candidate
            )
        )

        if (
            action.kind
            != post_draft_coordinator
            .ActionKind.VALIDATE
        ):
            raise DriverError(
                "COORDINATOR_REPAIR_ACTION"
            )

        self._pending = None

        return self._preflight_command(
            reason=
                "REPAIR_APPLIED_IN_MEMORY"
        )

    def accept_external_fault(
        self,
        *,
        fault_layer: str,
        reason: str,
    ) -> DriverSnapshot:
        if fault_layer not in (
            EXTERNAL_FAULT_LAYERS
        ):
            raise DriverError(
                "EXTERNAL_FAULT_LAYER_INVALID"
            )

        if (
            not isinstance(
                reason,
                str,
            )
            or not reason
            or len(reason) > 1000
        ):
            raise DriverError(
                "EXTERNAL_FAULT_REASON_INVALID"
            )

        self._pending = None
        self._state = DriverState.BLOCKED
        self._blocked_fault_layer = (
            fault_layer
        )
        self._blocked_reason = reason

        return self.snapshot()
