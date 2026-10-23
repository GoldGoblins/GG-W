from __future__ import annotations

import hashlib
import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path


PROJECT = Path(
    __file__
).resolve().parents[1]

REPO = PROJECT.parents[1]

BACKEND = PROJECT / "backend"

if str(BACKEND) not in sys.path:
    sys.path.insert(
        0,
        str(BACKEND),
    )

from capability_registry import CapabilityRegistry  # noqa: E402
from deterministic_solver_executor import (  # noqa: E402
    DeterministicSolverExecutionError,
    DeterministicSolverExecutionRequest,
    close_with_foundation_gate_pass,
    compile_foundation_gate_pass,
    execute_registered_solver,
)
from safe_edit_engine import (  # noqa: E402
    MachineEdit,
    SafeEditRequest,
    SourcePosition,
    sha256_text,
)
from solver_router import (  # noqa: E402
    CapabilityRouteEvidence,
    LaserFocusCache,
    RouteContext,
    SolverRouter,
)


SAFE_EDIT = "repair.source.safe_edit"
EVIDENCE_SHA = "a" * 64


def load_registry() -> CapabilityRegistry:
    return CapabilityRegistry.load(
        repo_root=REPO,
        project_root=PROJECT,
        seed_path=(
            PROJECT
            / "config"
            / "capability-seeds-v1.json"
        ),
        manifest_path=(
            PROJECT
            / "SOURCE-MANIFEST.json"
        ),
    )


def valid_bundle():
    registry = load_registry()
    router = SolverRouter(
        registry
    )
    cache = LaserFocusCache(
        router
    )

    source = (
        "import os\n"
        "import json\n"
        "value = 1\n"
    )

    source_sha = sha256_text(
        source
    )

    context = RouteContext(
        query=(
            "python repair unused import"
        ),
        goal_id="goal-executor-test",
        object_id="object-executor-test",
        source_revision=source_sha,
        language="python",
        diagnostic_class=(
            "F401_UNUSED_IMPORT"
        ),
        route_evidence=(
            CapabilityRouteEvidence(
                capability_id=SAFE_EDIT,
                evidence_sha256=(
                    EVIDENCE_SHA
                ),
                source_revision=(
                    source_sha
                ),
                applicability="safe",
            ),
        ),
    )

    binding = cache.bind(
        context
    )

    handle = cache.lookup(
        binding.handle_id
    )

    if handle is None:
        raise AssertionError(
            "focus lookup miss"
        )

    payload = SafeEditRequest(
        source_name="fixture.py",
        source=source,
        source_sha256=source_sha,
        evidence_sha256=(
            EVIDENCE_SHA
        ),
        edits=(
            MachineEdit(
                start=SourcePosition(
                    row=2,
                    column=1,
                ),
                end=SourcePosition(
                    row=3,
                    column=1,
                ),
                content="",
                applicability="safe",
                producer="ruff",
                code="F401",
            ),
        ),
    )

    request = DeterministicSolverExecutionRequest(
        capability_id=SAFE_EDIT,
        capability_execution_revision_sha256=(
            registry.get(
                SAFE_EDIT
            ).execution_revision_sha256
        ),
        focus_handle=handle,
        source_binding=binding,
        route_context=context,
        payload=payload,
    )

    return (
        registry,
        router,
        request,
    )


def pass_report(
    source_sha256: str,
) -> bytes:
    value = {
        "schema":
            "gg-code-gate-report-v1",
        "status":
            "PASS",
        "source": {
            "sha256":
                source_sha256,
        },
        "execution_requested":
            False,
        "secret_findings": [],
        "static_checks": [
            {
                "name":
                    "fixture-static",
                "return_code":
                    0,
                "timed_out":
                    False,
            },
        ],
    }

    return json.dumps(
        value,
        sort_keys=True,
    ).encode("utf-8")


class DeterministicSolverExecutorTests(
    unittest.TestCase
):
    def test_current_route_executes_safe_edit(
        self,
    ) -> None:
        (
            registry,
            router,
            request,
        ) = valid_bundle()

        result = execute_registered_solver(
            registry,
            router,
            request,
        )

        self.assertEqual(
            result.candidate,
            (
                "import os\n"
                "value = 1\n"
            ),
        )

        self.assertTrue(
            result.registered_capability_execution
        )

        self.assertFalse(
            result.persistent_write
        )

        self.assertFalse(
            result.model_inference
        )

        raw = pass_report(
            result.candidate_sha256
        )

        attestation = (
            compile_foundation_gate_pass(
                raw,
                hashlib.sha256(
                    raw
                ).hexdigest(),
            )
        )

        closure = (
            close_with_foundation_gate_pass(
                result,
                attestation,
            )
        )

        self.assertTrue(
            closure.done
        )

        self.assertEqual(
            closure.done_when,
            "SOURCE_STATIC_GATE_PASS",
        )

        self.assertFalse(
            closure.target_verified
        )

        self.assertFalse(
            closure.model_dispatch
        )

    def test_plain_route_cannot_execute_safe_edit(
        self,
    ) -> None:
        registry = load_registry()
        router = SolverRouter(
            registry
        )
        cache = LaserFocusCache(
            router
        )

        source = "value = 1\n"
        source_sha = sha256_text(
            source
        )

        context = RouteContext(
            query="python repair",
            goal_id="goal-plain",
            object_id="object-plain",
            source_revision=source_sha,
            language="python",
            diagnostic_class="PY_SYNTAX",
        )

        binding = cache.bind(
            context
        )

        handle = cache.lookup(
            binding.handle_id
        )

        if handle is None:
            self.fail(
                "focus lookup miss"
            )

        payload = SafeEditRequest(
            source_name="fixture.py",
            source=source,
            source_sha256=source_sha,
            evidence_sha256=(
                EVIDENCE_SHA
            ),
            edits=(
                MachineEdit(
                    start=SourcePosition(
                        row=1,
                        column=9,
                    ),
                    end=SourcePosition(
                        row=1,
                        column=10,
                    ),
                    content="2",
                    applicability="safe",
                    producer="fixture",
                    code="FIXTURE",
                ),
            ),
        )

        request = DeterministicSolverExecutionRequest(
            capability_id=SAFE_EDIT,
            capability_execution_revision_sha256=(
                registry.get(
                    SAFE_EDIT
                ).execution_revision_sha256
            ),
            focus_handle=handle,
            source_binding=binding,
            route_context=context,
            payload=payload,
        )

        with self.assertRaisesRegex(
            DeterministicSolverExecutionError,
            "ROUTE_PRIMARY_MISMATCH",
        ):
            execute_registered_solver(
                registry,
                router,
                request,
            )

    def test_stale_source_binding_fails_closed(
        self,
    ) -> None:
        (
            registry,
            router,
            request,
        ) = valid_bundle()

        stale_binding = replace(
            request.source_binding,
            source_revision=(
                "0" * 64
            ),
        )

        bad = replace(
            request,
            source_binding=stale_binding,
        )

        with self.assertRaisesRegex(
            DeterministicSolverExecutionError,
            "SOURCE_BINDING_REVISION_MISMATCH",
        ):
            execute_registered_solver(
                registry,
                router,
                bad,
            )

    def test_execution_revision_mismatch_fails_closed(
        self,
    ) -> None:
        (
            registry,
            router,
            request,
        ) = valid_bundle()

        bad = replace(
            request,
            capability_execution_revision_sha256=(
                "0" * 64
            ),
        )

        with self.assertRaisesRegex(
            DeterministicSolverExecutionError,
            "CAPABILITY_EXECUTION_REVISION_MISMATCH",
        ):
            execute_registered_solver(
                registry,
                router,
                bad,
            )

    def test_payload_evidence_mismatch_fails_closed(
        self,
    ) -> None:
        (
            registry,
            router,
            request,
        ) = valid_bundle()

        bad_payload = replace(
            request.payload,
            evidence_sha256=(
                "b" * 64
            ),
        )

        bad = replace(
            request,
            payload=bad_payload,
        )

        with self.assertRaisesRegex(
            DeterministicSolverExecutionError,
            "ROUTE_EVIDENCE_PAYLOAD_MISMATCH",
        ):
            execute_registered_solver(
                registry,
                router,
                bad,
            )

    def test_automatic_model_dispatch_route_is_rejected(
        self,
    ) -> None:
        (
            registry,
            router,
            request,
        ) = valid_bundle()

        bad_route = replace(
            request.focus_handle.route,
            automatic_model_dispatch=True,
        )

        bad_handle = replace(
            request.focus_handle,
            route=bad_route,
        )

        bad = replace(
            request,
            focus_handle=bad_handle,
        )

        with self.assertRaisesRegex(
            DeterministicSolverExecutionError,
            "AUTOMATIC_MODEL_DISPATCH",
        ):
            execute_registered_solver(
                registry,
                router,
                bad,
            )

    def test_arbitrary_registry_capability_is_not_executable(
        self,
    ) -> None:
        (
            registry,
            router,
            request,
        ) = valid_bundle()

        arbitrary = (
            "route.solver.deterministic"
        )

        bad = replace(
            request,
            capability_id=arbitrary,
            capability_execution_revision_sha256=(
                registry.get(
                    arbitrary
                ).execution_revision_sha256
            ),
        )

        with self.assertRaisesRegex(
            DeterministicSolverExecutionError,
            "CAPABILITY_NOT_STATICALLY_BOUND",
        ):
            execute_registered_solver(
                registry,
                router,
                bad,
            )

    def test_compile_foundation_gate_pass(
        self,
    ) -> None:
        source_sha = "c" * 64
        raw = pass_report(
            source_sha
        )

        attestation = (
            compile_foundation_gate_pass(
                raw,
                hashlib.sha256(
                    raw
                ).hexdigest(),
            )
        )

        self.assertEqual(
            attestation.source_sha256,
            source_sha,
        )

        self.assertEqual(
            attestation.static_check_count,
            1,
        )

    def test_bad_report_hash_is_rejected(
        self,
    ) -> None:
        raw = pass_report(
            "c" * 64
        )

        with self.assertRaisesRegex(
            DeterministicSolverExecutionError,
            "GATE_REPORT_SHA256_MISMATCH",
        ):
            compile_foundation_gate_pass(
                raw,
                "0" * 64,
            )

    def test_non_pass_report_is_rejected(
        self,
    ) -> None:
        value = {
            "schema":
                "gg-code-gate-report-v1",
            "status":
                "FAIL",
            "source": {
                "sha256":
                    "c" * 64,
            },
            "execution_requested":
                False,
            "secret_findings": [],
            "static_checks": [
                {
                    "name":
                        "fixture",
                    "return_code":
                        1,
                    "timed_out":
                        False,
                },
            ],
        }

        raw = json.dumps(
            value,
            sort_keys=True,
        ).encode("utf-8")

        with self.assertRaisesRegex(
            DeterministicSolverExecutionError,
            "GATE_REPORT_NOT_PASS",
        ):
            compile_foundation_gate_pass(
                raw,
                hashlib.sha256(
                    raw
                ).hexdigest(),
            )

    def test_closure_candidate_mismatch_is_rejected(
        self,
    ) -> None:
        (
            registry,
            router,
            request,
        ) = valid_bundle()

        result = execute_registered_solver(
            registry,
            router,
            request,
        )

        raw = pass_report(
            "d" * 64
        )

        attestation = (
            compile_foundation_gate_pass(
                raw,
                hashlib.sha256(
                    raw
                ).hexdigest(),
            )
        )

        with self.assertRaisesRegex(
            DeterministicSolverExecutionError,
            "REVALIDATION_SOURCE_SHA_MISMATCH",
        ):
            close_with_foundation_gate_pass(
                result,
                attestation,
            )


if __name__ == "__main__":
    unittest.main()
