"""Content-bound in-process execution of selected deterministic solvers.

This module deliberately does not provide arbitrary registry dispatch.
Every executable adapter is statically bound in source and must also match
the current content-addressed capability record.

The hot execution path performs no filesystem I/O, process spawning,
network access, model inference, or persistent source writes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Callable

from capability_registry import (
    CapabilityRegistry,
)
from safe_edit_engine import (
    SafeEditRequest,
    SafeEditResult,
    apply_safe_edits,
)
from solver_router import (
    LaserFocusBinding,
    LaserFocusHandle,
    ROUTE_EVIDENCE_REQUIRED_TAG,
    RouteContext,
    SolverRouter,
)


EXECUTION_REQUEST_SCHEMA = (
    "gg.deterministic-solver-execution-request.v1"
)
EXECUTION_RESULT_SCHEMA = (
    "gg.deterministic-solver-execution-result.v1"
)
GATE_ATTESTATION_SCHEMA = (
    "gg.foundation-gate-pass-attestation.v1"
)
CLOSURE_RESULT_SCHEMA = (
    "gg.deterministic-source-closure.v1"
)

EXECUTOR_ID = (
    "control.solver.in_memory_execute"
)

SAFE_EDIT_CAPABILITY_ID = (
    "repair.source.safe_edit"
)

SAFE_EDIT_CONTENT_SHA256 = (
    "0a39ec5f011845376b7046034241bb650"
    "b96461a6de7129099095031a27da5a3"
)

MAX_GATE_REPORT_BYTES = (
    2 * 1024 * 1024
)


class DeterministicSolverExecutionError(
    RuntimeError
):
    """Raised when deterministic execution cannot be proven safe."""


@dataclass(frozen=True)
class DeterministicSolverExecutionRequest:
    capability_id: str
    capability_execution_revision_sha256: str
    focus_handle: LaserFocusHandle
    source_binding: LaserFocusBinding
    route_context: RouteContext
    payload: SafeEditRequest


@dataclass(frozen=True)
class DeterministicSolverExecutionResult:
    schema: str
    executor_id: str
    capability_id: str
    capability_execution_revision_sha256: str
    focus_handle_id: str
    source_binding_sha256: str
    source_sha256: str
    evidence_sha256: str
    candidate: str
    candidate_sha256: str
    registered_capability_execution: bool
    persistent_write: bool
    model_inference: bool
    network_authority: str
    execution_authority: str


@dataclass(frozen=True)
class FoundationGatePassAttestation:
    schema: str
    report_sha256: str
    source_sha256: str
    gate_report_schema: str
    static_check_count: int
    execution_requested: bool


@dataclass(frozen=True)
class DeterministicClosureResult:
    schema: str
    done: bool
    done_when: str
    capability_id: str
    candidate_sha256: str
    verifier_report_sha256: str
    static_verification: str
    target_verified: bool
    model_dispatch: bool
    persistent_write: bool


@dataclass(frozen=True)
class _SolverAdapter:
    capability_id: str
    content_sha256: str
    entrypoint: str
    invoke: Callable[
        [SafeEditRequest],
        SafeEditResult,
    ]


_ADAPTERS = {
    SAFE_EDIT_CAPABILITY_ID:
        _SolverAdapter(
            capability_id=(
                SAFE_EDIT_CAPABILITY_ID
            ),
            content_sha256=(
                SAFE_EDIT_CONTENT_SHA256
            ),
            entrypoint=(
                "apply_safe_edits"
            ),
            invoke=apply_safe_edits,
        ),
}


def _valid_sha256(
    value: str,
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
    value: str,
    label: str,
) -> None:
    if not _valid_sha256(value):
        raise DeterministicSolverExecutionError(
            label
            + "_SHA256_INVALID"
        )


def _matching_route_evidence(
    context: RouteContext,
    capability_id: str,
) -> tuple[str, str]:
    context.validate()

    matches = tuple(
        evidence
        for evidence
        in context.route_evidence
        if evidence.capability_id
        == capability_id
    )

    if len(matches) != 1:
        raise DeterministicSolverExecutionError(
            "CURRENT_ROUTE_EVIDENCE_REQUIRED"
        )

    evidence = matches[0]

    if (
        evidence.source_revision
        != context.source_revision
    ):
        raise DeterministicSolverExecutionError(
            "ROUTE_EVIDENCE_SOURCE_STALE"
        )

    if evidence.applicability != "safe":
        raise DeterministicSolverExecutionError(
            "ROUTE_EVIDENCE_NOT_SAFE"
        )

    return (
        evidence.evidence_sha256,
        evidence.source_revision,
    )


def execute_registered_solver(
    registry: CapabilityRegistry,
    router: SolverRouter,
    request: DeterministicSolverExecutionRequest,
) -> DeterministicSolverExecutionResult:
    if not isinstance(
        request,
        DeterministicSolverExecutionRequest,
    ):
        raise DeterministicSolverExecutionError(
            "EXECUTION_REQUEST_TYPE_INVALID"
        )

    adapter = _ADAPTERS.get(
        request.capability_id
    )

    if adapter is None:
        raise DeterministicSolverExecutionError(
            "CAPABILITY_NOT_STATICALLY_BOUND"
        )

    _require_sha256(
        request.capability_execution_revision_sha256,
        "CAPABILITY_EXECUTION_REVISION",
    )

    context = request.route_context
    context.validate()

    handle = request.focus_handle
    binding = request.source_binding
    route = handle.route
    payload = request.payload

    if (
        binding.handle_id
        != handle.handle_id
    ):
        raise DeterministicSolverExecutionError(
            "FOCUS_BINDING_HANDLE_MISMATCH"
        )

    if (
        binding.source_revision
        != context.source_revision
    ):
        raise DeterministicSolverExecutionError(
            "SOURCE_BINDING_REVISION_MISMATCH"
        )

    if (
        context.source_revision
        != payload.source_sha256
    ):
        raise DeterministicSolverExecutionError(
            "PAYLOAD_SOURCE_REVISION_MISMATCH"
        )

    if (
        route.graph_revision_sha256
        != router.graph_revision_sha256
    ):
        raise DeterministicSolverExecutionError(
            "ROUTE_GRAPH_REVISION_STALE"
        )

    if (
        route.policy_revision_sha256
        != router.policy_revision_sha256
    ):
        raise DeterministicSolverExecutionError(
            "ROUTE_POLICY_REVISION_STALE"
        )

    if (
        route.primary_capability
        != request.capability_id
    ):
        raise DeterministicSolverExecutionError(
            "ROUTE_PRIMARY_MISMATCH"
        )

    if (
        request.capability_id
        not in route.deterministic_solvers
    ):
        raise DeterministicSolverExecutionError(
            "CAPABILITY_NOT_IN_DETERMINISTIC_SOLVERS"
        )

    if route.automatic_model_dispatch:
        raise DeterministicSolverExecutionError(
            "ROUTE_AUTOMATIC_MODEL_DISPATCH_FORBIDDEN"
        )

    if route.registered_capability_execution:
        raise DeterministicSolverExecutionError(
            "ROUTE_ALREADY_CLAIMS_EXECUTION"
        )

    record = registry.get(
        request.capability_id
    )

    if (
        record.execution_revision_sha256
        != request.capability_execution_revision_sha256
    ):
        raise DeterministicSolverExecutionError(
            "CAPABILITY_EXECUTION_REVISION_MISMATCH"
        )

    if (
        record.content_sha256
        != adapter.content_sha256
    ):
        raise DeterministicSolverExecutionError(
            "STATIC_ADAPTER_CONTENT_BINDING_MISMATCH"
        )

    if (
        record.entrypoint
        != adapter.entrypoint
    ):
        raise DeterministicSolverExecutionError(
            "STATIC_ADAPTER_ENTRYPOINT_MISMATCH"
        )

    contract = record.contract

    if (
        contract.get("effect_class")
        != "IN_MEMORY_ONLY"
    ):
        raise DeterministicSolverExecutionError(
            "CAPABILITY_EFFECT_NOT_IN_MEMORY_ONLY"
        )

    if (
        contract.get("persistent_write")
        != "NONE"
    ):
        raise DeterministicSolverExecutionError(
            "CAPABILITY_PERSISTENT_WRITE_FORBIDDEN"
        )

    if contract.get("network") != "NONE":
        raise DeterministicSolverExecutionError(
            "CAPABILITY_NETWORK_FORBIDDEN"
        )

    if (
        contract.get("model_inference")
        is not False
    ):
        raise DeterministicSolverExecutionError(
            "CAPABILITY_MODEL_INFERENCE_FORBIDDEN"
        )

    if (
        contract.get("execution_authority")
        != "NONE"
    ):
        raise DeterministicSolverExecutionError(
            "CAPABILITY_EXTERNAL_EXECUTION_AUTHORITY_FORBIDDEN"
        )

    if (
        ROUTE_EVIDENCE_REQUIRED_TAG
        not in record.tags
    ):
        raise DeterministicSolverExecutionError(
            "CAPABILITY_ROUTE_EVIDENCE_POLICY_MISSING"
        )

    (
        route_evidence_sha256,
        route_source_revision,
    ) = _matching_route_evidence(
        context,
        request.capability_id,
    )

    if (
        route_source_revision
        != payload.source_sha256
    ):
        raise DeterministicSolverExecutionError(
            "ROUTE_EVIDENCE_SOURCE_BINDING_MISMATCH"
        )

    if (
        route_evidence_sha256
        != payload.evidence_sha256
    ):
        raise DeterministicSolverExecutionError(
            "ROUTE_EVIDENCE_PAYLOAD_MISMATCH"
        )

    result = adapter.invoke(
        payload
    )

    if (
        result.solver_id
        != request.capability_id
    ):
        raise DeterministicSolverExecutionError(
            "SOLVER_RESULT_IDENTITY_MISMATCH"
        )

    if (
        result.source_sha256
        != payload.source_sha256
    ):
        raise DeterministicSolverExecutionError(
            "SOLVER_RESULT_SOURCE_MISMATCH"
        )

    if (
        result.evidence_sha256
        != payload.evidence_sha256
    ):
        raise DeterministicSolverExecutionError(
            "SOLVER_RESULT_EVIDENCE_MISMATCH"
        )

    if result.persistent_write:
        raise DeterministicSolverExecutionError(
            "SOLVER_RESULT_PERSISTENT_WRITE_TRUE"
        )

    if result.model_inference:
        raise DeterministicSolverExecutionError(
            "SOLVER_RESULT_MODEL_INFERENCE_TRUE"
        )

    return DeterministicSolverExecutionResult(
        schema=EXECUTION_RESULT_SCHEMA,
        executor_id=EXECUTOR_ID,
        capability_id=(
            request.capability_id
        ),
        capability_execution_revision_sha256=(
            record.execution_revision_sha256
        ),
        focus_handle_id=(
            handle.handle_id
        ),
        source_binding_sha256=(
            binding.binding_sha256
        ),
        source_sha256=(
            result.source_sha256
        ),
        evidence_sha256=(
            result.evidence_sha256
        ),
        candidate=(
            result.candidate
        ),
        candidate_sha256=(
            result.candidate_sha256
        ),
        registered_capability_execution=True,
        persistent_write=False,
        model_inference=False,
        network_authority="NONE",
        execution_authority="NONE",
    )


def compile_foundation_gate_pass(
    report_bytes: bytes,
    expected_report_sha256: str,
) -> FoundationGatePassAttestation:
    if not isinstance(
        report_bytes,
        bytes,
    ):
        raise DeterministicSolverExecutionError(
            "GATE_REPORT_BYTES_INVALID"
        )

    if (
        not report_bytes
        or len(report_bytes)
        > MAX_GATE_REPORT_BYTES
    ):
        raise DeterministicSolverExecutionError(
            "GATE_REPORT_BUDGET_INVALID"
        )

    _require_sha256(
        expected_report_sha256,
        "GATE_REPORT",
    )

    actual_report_sha256 = hashlib.sha256(
        report_bytes
    ).hexdigest()

    if (
        actual_report_sha256
        != expected_report_sha256
    ):
        raise DeterministicSolverExecutionError(
            "GATE_REPORT_SHA256_MISMATCH"
        )

    try:
        value = json.loads(
            report_bytes.decode("utf-8")
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise DeterministicSolverExecutionError(
            "GATE_REPORT_JSON_INVALID"
        ) from exc

    if not isinstance(value, dict):
        raise DeterministicSolverExecutionError(
            "GATE_REPORT_ROOT_INVALID"
        )

    if (
        value.get("schema")
        != "gg-code-gate-report-v1"
    ):
        raise DeterministicSolverExecutionError(
            "GATE_REPORT_SCHEMA_INVALID"
        )

    if value.get("status") != "PASS":
        raise DeterministicSolverExecutionError(
            "GATE_REPORT_NOT_PASS"
        )

    if (
        value.get("execution_requested")
        is not False
    ):
        raise DeterministicSolverExecutionError(
            "GATE_REPORT_EXECUTION_REQUESTED"
        )

    source = value.get("source")

    if not isinstance(source, dict):
        raise DeterministicSolverExecutionError(
            "GATE_REPORT_SOURCE_INVALID"
        )

    source_sha256 = source.get(
        "sha256"
    )

    _require_sha256(
        source_sha256,
        "GATE_REPORT_SOURCE",
    )

    checks = value.get(
        "static_checks"
    )

    if (
        not isinstance(checks, list)
        or not checks
    ):
        raise DeterministicSolverExecutionError(
            "GATE_REPORT_STATIC_CHECKS_INVALID"
        )

    for check in checks:
        if (
            not isinstance(check, dict)
            or check.get(
                "return_code"
            ) != 0
            or check.get(
                "timed_out"
            ) is not False
        ):
            raise DeterministicSolverExecutionError(
                "GATE_REPORT_STATIC_CHECK_NOT_PASS"
            )

    if value.get(
        "secret_findings"
    ) not in (
        None,
        [],
    ):
        raise DeterministicSolverExecutionError(
            "GATE_REPORT_SECRET_FINDINGS"
        )

    return FoundationGatePassAttestation(
        schema=GATE_ATTESTATION_SCHEMA,
        report_sha256=(
            actual_report_sha256
        ),
        source_sha256=(
            source_sha256
        ),
        gate_report_schema=(
            value["schema"]
        ),
        static_check_count=(
            len(checks)
        ),
        execution_requested=False,
    )


def close_with_foundation_gate_pass(
    execution: DeterministicSolverExecutionResult,
    attestation: FoundationGatePassAttestation,
) -> DeterministicClosureResult:
    if not isinstance(
        execution,
        DeterministicSolverExecutionResult,
    ):
        raise DeterministicSolverExecutionError(
            "EXECUTION_RESULT_TYPE_INVALID"
        )

    if not isinstance(
        attestation,
        FoundationGatePassAttestation,
    ):
        raise DeterministicSolverExecutionError(
            "GATE_ATTESTATION_TYPE_INVALID"
        )

    if (
        execution.candidate_sha256
        != attestation.source_sha256
    ):
        raise DeterministicSolverExecutionError(
            "REVALIDATION_SOURCE_SHA_MISMATCH"
        )

    if (
        not execution.registered_capability_execution
    ):
        raise DeterministicSolverExecutionError(
            "REGISTERED_CAPABILITY_EXECUTION_NOT_PROVEN"
        )

    if execution.persistent_write:
        raise DeterministicSolverExecutionError(
            "EXECUTION_PERSISTENT_WRITE_TRUE"
        )

    if execution.model_inference:
        raise DeterministicSolverExecutionError(
            "EXECUTION_MODEL_INFERENCE_TRUE"
        )

    return DeterministicClosureResult(
        schema=CLOSURE_RESULT_SCHEMA,
        done=True,
        done_when=(
            "SOURCE_STATIC_GATE_PASS"
        ),
        capability_id=(
            execution.capability_id
        ),
        candidate_sha256=(
            execution.candidate_sha256
        ),
        verifier_report_sha256=(
            attestation.report_sha256
        ),
        static_verification="PASS",
        target_verified=False,
        model_dispatch=False,
        persistent_write=False,
    )
