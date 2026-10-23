from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
from typing import Any


MAX_SOURCE_BYTES = 262_144

VALIDATION_SCHEMA = (
    "gg.live-aid.post-draft-validation.v1"
)

CANDIDATE_SCHEMA = (
    "gg.live-aid.post-draft-candidate.v1"
)

ACTION_SCHEMA = (
    "gg.live-aid.post-draft-action.v1"
)

SNAPSHOT_SCHEMA = (
    "gg.live-aid.post-draft-snapshot.v1"
)


class CoordinatorError(RuntimeError):
    pass


class CoordinatorState(str, Enum):
    DRAFT = "DRAFT"
    VERIFYING = "VERIFYING"
    REPAIRING = "REPAIRING"
    VERIFIED = "VERIFIED"
    READY_TO_RUN = "READY_TO_RUN"
    BLOCKED = "BLOCKED"


class ActionKind(str, Enum):
    NONE = "NONE"
    VALIDATE = "VALIDATE"
    REPAIR = "REPAIR"
    PROMOTE_READY = "PROMOTE_READY"


ALLOWED_FAULT_LAYERS = {
    "NONE",
    "SOURCE",
    "TRANSPORT",
    "HARNESS",
    "SANDBOX",
    "TARGET",
    "REGRESSION",
}


@dataclass(frozen=True)
class CoordinatorAction:
    kind: ActionKind
    object_id: str
    source_name: str
    source: str
    source_sha256: str
    repair_attempt: int
    diagnostics: tuple[dict[str, Any], ...]
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": ACTION_SCHEMA,
            "kind": self.kind.value,
            "object_id": self.object_id,
            "source_name": self.source_name,
            "source": self.source,
            "source_sha256": self.source_sha256,
            "repair_attempt": self.repair_attempt,
            "diagnostics": [
                dict(item)
                for item in self.diagnostics
            ],
            "reason": self.reason,
            "persistent_write_authority": "NONE",
            "execution_authority": "NONE",
            "network_authority": "NONE",
            "model_inference_authority":
                "CALLER_MANDATE_REQUIRED",
        }


@dataclass(frozen=True)
class CoordinatorSnapshot:
    state: CoordinatorState
    object_id: str
    source_name: str
    language: str
    source_sha256: str
    draft_complete: bool
    repair_attempts: int
    max_repair_attempts: int
    execution_ready: bool
    blocked_reason: str
    history: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": SNAPSHOT_SCHEMA,
            "state": self.state.value,
            "object_id": self.object_id,
            "source_name": self.source_name,
            "language": self.language,
            "source_sha256": self.source_sha256,
            "draft_complete": self.draft_complete,
            "repair_attempts": self.repair_attempts,
            "max_repair_attempts":
                self.max_repair_attempts,
            "execution_ready": self.execution_ready,
            "blocked_reason": self.blocked_reason,
            "persistent_write_authority": "NONE",
            "execution_authority": "NONE",
            "network_authority": "NONE",
            "history": list(self.history),
        }


def _sha(source: str) -> str:
    return hashlib.sha256(
        source.encode("utf-8")
    ).hexdigest()


def _validate_source(
    source: str,
) -> str:
    if not isinstance(
        source,
        str,
    ):
        raise CoordinatorError(
            "SOURCE_NOT_STRING"
        )

    if len(
        source.encode("utf-8")
    ) > MAX_SOURCE_BYTES:
        raise CoordinatorError(
            "SOURCE_TOO_LARGE"
        )

    return source


class PostDraftCoordinator:
    """Pure in-memory Stage-E authoring state machine.

    This object owns no model runtime, disk-write, network, shell,
    Git, or execution capability.

    Live Aid may observe while state is DRAFT, but no repair action
    can be emitted until mark_draft_complete() has frozen the current
    candidate identity.
    """

    def __init__(
        self,
        *,
        object_id: str,
        source_name: str,
        language: str,
        max_repair_attempts: int = 3,
    ):
        if (
            not isinstance(
                object_id,
                str,
            )
            or not object_id
            or len(object_id) > 160
        ):
            raise CoordinatorError(
                "OBJECT_ID_INVALID"
            )

        if (
            not isinstance(
                source_name,
                str,
            )
            or not source_name
            or len(source_name) > 300
        ):
            raise CoordinatorError(
                "SOURCE_NAME_INVALID"
            )

        if (
            not isinstance(
                language,
                str,
            )
            or not language
            or len(language) > 40
        ):
            raise CoordinatorError(
                "LANGUAGE_INVALID"
            )

        if (
            not isinstance(
                max_repair_attempts,
                int,
            )
            or isinstance(
                max_repair_attempts,
                bool,
            )
            or not 1 <= max_repair_attempts <= 8
        ):
            raise CoordinatorError(
                "REPAIR_BUDGET_INVALID"
            )

        self.object_id = object_id
        self.source_name = source_name
        self.language = language

        self.max_repair_attempts = (
            max_repair_attempts
        )

        self._state = (
            CoordinatorState.DRAFT
        )

        self._source = ""
        self._source_sha256 = _sha("")
        self._draft_complete = False
        self._repair_attempts = 0
        self._blocked_reason = ""

        self._history: list[str] = [
            "DRAFT"
        ]

    @property
    def source(self) -> str:
        return self._source

    @property
    def state(self) -> CoordinatorState:
        return self._state

    def snapshot(
        self,
    ) -> CoordinatorSnapshot:
        return CoordinatorSnapshot(
            state=self._state,
            object_id=self.object_id,
            source_name=self.source_name,
            language=self.language,
            source_sha256=
                self._source_sha256,
            draft_complete=
                self._draft_complete,
            repair_attempts=
                self._repair_attempts,
            max_repair_attempts=
                self.max_repair_attempts,
            execution_ready=(
                self._state
                == CoordinatorState.READY_TO_RUN
            ),
            blocked_reason=
                self._blocked_reason,
            history=tuple(
                self._history
            ),
        )

    def _action(
        self,
        kind: ActionKind,
        *,
        diagnostics: tuple[
            dict[str, Any],
            ...,
        ] = (),
        reason: str = "",
    ) -> CoordinatorAction:
        return CoordinatorAction(
            kind=kind,
            object_id=self.object_id,
            source_name=self.source_name,
            source=self._source,
            source_sha256=
                self._source_sha256,
            repair_attempt=
                self._repair_attempts,
            diagnostics=diagnostics,
            reason=reason,
        )

    def update_draft(
        self,
        source: str,
    ) -> CoordinatorSnapshot:
        if (
            self._state
            != CoordinatorState.DRAFT
        ):
            raise CoordinatorError(
                "DRAFT_ALREADY_COMPLETE"
            )

        source = _validate_source(
            source
        )

        self._source = source
        self._source_sha256 = _sha(
            source
        )

        self._history.append(
            "DRAFT_UPDATED:"
            + self._source_sha256
        )

        return self.snapshot()

    def mark_draft_complete(
        self,
    ) -> CoordinatorAction:
        if (
            self._state
            != CoordinatorState.DRAFT
        ):
            raise CoordinatorError(
                "DRAFT_COMPLETE_STATE_INVALID"
            )

        self._draft_complete = True

        self._state = (
            CoordinatorState.VERIFYING
        )

        self._history.extend(
            [
                "DRAFT_COMPLETE:"
                + self._source_sha256,
                "VERIFYING:"
                + self._source_sha256,
            ]
        )

        return self._action(
            ActionKind.VALIDATE,
            reason="DRAFT_COMPLETE",
        )

    def accept_validation(
        self,
        report: dict[str, Any],
    ) -> CoordinatorAction:
        if (
            self._state
            != CoordinatorState.VERIFYING
        ):
            raise CoordinatorError(
                "VALIDATION_STATE_INVALID"
            )

        if (
            not isinstance(
                report,
                dict,
            )
            or report.get("schema")
            != VALIDATION_SCHEMA
        ):
            raise CoordinatorError(
                "VALIDATION_SCHEMA"
            )

        if (
            report.get("source_sha256")
            != self._source_sha256
        ):
            raise CoordinatorError(
                "VALIDATION_STALE_SOURCE"
            )

        status = report.get(
            "status"
        )

        if status not in {
            "PASS",
            "FAIL",
            "UNKNOWN",
            "BLOCKED",
        }:
            raise CoordinatorError(
                "VALIDATION_STATUS"
            )

        fault_layer = report.get(
            "fault_layer"
        )

        if fault_layer not in (
            ALLOWED_FAULT_LAYERS
        ):
            raise CoordinatorError(
                "FAULT_LAYER_INVALID"
            )

        raw_diagnostics = report.get(
            "diagnostics",
            [],
        )

        if not isinstance(
            raw_diagnostics,
            list,
        ):
            raise CoordinatorError(
                "VALIDATION_DIAGNOSTICS"
            )

        diagnostics = tuple(
            dict(item)
            for item in raw_diagnostics
            if isinstance(
                item,
                dict,
            )
        )

        if len(diagnostics) != len(
            raw_diagnostics
        ):
            raise CoordinatorError(
                "VALIDATION_DIAGNOSTIC_ITEM"
            )

        if status == "PASS":
            if fault_layer != "NONE":
                raise CoordinatorError(
                    "PASS_WITH_FAULT_LAYER"
                )

            self._state = (
                CoordinatorState.VERIFIED
            )

            self._history.append(
                "VERIFIED:"
                + self._source_sha256
            )

            return self._action(
                ActionKind.PROMOTE_READY,
                reason="VALIDATION_PASS",
            )

        if (
            status == "FAIL"
            and fault_layer == "SOURCE"
        ):
            if not diagnostics:
                self._state = (
                    CoordinatorState.BLOCKED
                )

                self._blocked_reason = (
                    "SOURCE_FAIL_WITHOUT_DIAGNOSTICS"
                )

                self._history.append(
                    "BLOCKED:"
                    + self._blocked_reason
                )

                return self._action(
                    ActionKind.NONE,
                    reason=
                        self._blocked_reason,
                )

            if (
                self._repair_attempts
                >= self.max_repair_attempts
            ):
                self._state = (
                    CoordinatorState.BLOCKED
                )

                self._blocked_reason = (
                    "REPAIR_BUDGET_EXHAUSTED"
                )

                self._history.append(
                    "BLOCKED:"
                    + self._blocked_reason
                )

                return self._action(
                    ActionKind.NONE,
                    diagnostics=diagnostics,
                    reason=
                        self._blocked_reason,
                )

            self._state = (
                CoordinatorState.REPAIRING
            )

            self._history.append(
                "REPAIRING:"
                + self._source_sha256
            )

            return self._action(
                ActionKind.REPAIR,
                diagnostics=diagnostics,
                reason="SOURCE_FAIL",
            )

        self._state = (
            CoordinatorState.BLOCKED
        )

        self._blocked_reason = (
            str(status)
            + ":"
            + str(fault_layer)
        )

        self._history.append(
            "BLOCKED:"
            + self._blocked_reason
        )

        return self._action(
            ActionKind.NONE,
            diagnostics=diagnostics,
            reason=self._blocked_reason,
        )

    def accept_repair_candidate(
        self,
        proposal: dict[str, Any],
    ) -> CoordinatorAction:
        if (
            self._state
            != CoordinatorState.REPAIRING
        ):
            raise CoordinatorError(
                "REPAIR_CANDIDATE_STATE_INVALID"
            )

        if (
            not isinstance(
                proposal,
                dict,
            )
            or proposal.get("schema")
            != CANDIDATE_SCHEMA
        ):
            raise CoordinatorError(
                "REPAIR_CANDIDATE_SCHEMA"
            )

        if (
            proposal.get("source_sha256")
            != self._source_sha256
        ):
            raise CoordinatorError(
                "REPAIR_CANDIDATE_STALE_SOURCE"
            )

        if (
            proposal.get(
                "model_output_authority"
            )
            != "UNTRUSTED_MODEL_OUTPUT"
        ):
            raise CoordinatorError(
                "MODEL_OUTPUT_AUTHORITY"
            )

        if (
            proposal.get(
                "apply_authority"
            )
            != "SYSTEM_AUTOMATIC_IN_MEMORY_ONLY"
        ):
            raise CoordinatorError(
                "AUTOMATIC_APPLY_AUTHORITY"
            )

        if (
            proposal.get(
                "persistent_write_authority"
            )
            != "NONE"
            or proposal.get(
                "execution_authority"
            )
            != "NONE"
            or proposal.get(
                "network_authority"
            )
            != "NONE"
        ):
            raise CoordinatorError(
                "REPAIR_CANDIDATE_ACTION_AUTHORITY"
            )

        candidate = proposal.get(
            "candidate_source"
        )

        if not isinstance(
            candidate,
            str,
        ):
            raise CoordinatorError(
                "REPAIR_CANDIDATE_SOURCE"
            )

        candidate = _validate_source(
            candidate
        )

        candidate_sha = _sha(
            candidate
        )

        if (
            proposal.get(
                "candidate_sha256"
            )
            != candidate_sha
        ):
            raise CoordinatorError(
                "REPAIR_CANDIDATE_SHA"
            )

        if (
            candidate_sha
            == self._source_sha256
        ):
            raise CoordinatorError(
                "REPAIR_CANDIDATE_NOOP"
            )

        self._repair_attempts += 1

        self._source = candidate
        self._source_sha256 = (
            candidate_sha
        )

        self._state = (
            CoordinatorState.VERIFYING
        )

        self._history.extend(
            [
                "REPAIR_APPLIED_IN_MEMORY:"
                + candidate_sha,
                "VERIFYING:"
                + candidate_sha,
            ]
        )

        return self._action(
            ActionKind.VALIDATE,
            reason=
                "REPAIR_APPLIED_IN_MEMORY",
        )

    def promote_ready(
        self,
    ) -> CoordinatorSnapshot:
        if (
            self._state
            != CoordinatorState.VERIFIED
        ):
            raise CoordinatorError(
                "READY_PROMOTION_STATE_INVALID"
            )

        self._state = (
            CoordinatorState.READY_TO_RUN
        )

        self._history.append(
            "READY_TO_RUN:"
            + self._source_sha256
        )

        return self.snapshot()
