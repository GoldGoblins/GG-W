from __future__ import annotations

import sys
import unittest
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
from solver_router import (  # noqa: E402
    CapabilityRouteEvidence,
    LaserFocusCache,
    RouteContext,
    SolverRouter,
    SolverRouterError,
)


SAFE_EDIT = "repair.source.safe_edit"
EVIDENCE_SHA = "a" * 64


def registry() -> CapabilityRegistry:
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


def evidence(
    revision: str,
    *,
    capability_id: str = SAFE_EDIT,
    applicability: str = "safe",
    evidence_sha256: str = EVIDENCE_SHA,
) -> CapabilityRouteEvidence:
    return CapabilityRouteEvidence(
        capability_id=capability_id,
        evidence_sha256=evidence_sha256,
        source_revision=revision,
        applicability=applicability,
    )


def context(
    revision: str,
    *,
    route_evidence: tuple[
        CapabilityRouteEvidence,
        ...,
    ] = (),
    query: str = (
        "python repair unused import"
    ),
) -> RouteContext:
    return RouteContext(
        query=query,
        goal_id="goal-e2d3b",
        object_id="object-e2d3b",
        source_revision=revision,
        language="python",
        diagnostic_class=(
            "F401_UNUSED_IMPORT"
        ),
        route_evidence=route_evidence,
    )


class EvidenceRoutingTests(
    unittest.TestCase
):
    def test_plain_repair_does_not_select_safe_edit(
        self,
    ) -> None:
        result = SolverRouter(
            registry()
        ).route(
            context("rev-1")
        )

        self.assertNotIn(
            SAFE_EDIT,
            result.deterministic_solvers,
        )

        self.assertIsNone(
            result.primary_capability
        )

        self.assertEqual(
            result.route_mode,
            (
                "DETERMINISTIC_PRECHECK_THEN_"
                "MODEL_FALLBACK"
            ),
        )

    def test_even_safe_edit_query_text_cannot_bypass_evidence_gate(
        self,
    ) -> None:
        result = SolverRouter(
            registry()
        ).route(
            context(
                "rev-1",
                query=(
                    "safe edit repair source"
                ),
            )
        )

        self.assertNotIn(
            SAFE_EDIT,
            result.deterministic_solvers,
        )

    def test_current_safe_evidence_selects_safe_edit(
        self,
    ) -> None:
        router = SolverRouter(
            registry()
        )

        revision = "rev-current"

        result = router.route(
            context(
                revision,
                route_evidence=(
                    evidence(revision),
                ),
            )
        )

        self.assertEqual(
            result.primary_capability,
            SAFE_EDIT,
        )

        self.assertEqual(
            result.deterministic_solvers[
                0
            ],
            SAFE_EDIT,
        )

        self.assertEqual(
            result.route_mode,
            "REUSE_DETERMINISTIC",
        )

        self.assertTrue(
            result.model_fallbacks
        )

        self.assertFalse(
            result.automatic_model_dispatch
        )

        self.assertFalse(
            result.registered_capability_execution
        )

    def test_stale_evidence_fails_closed(
        self,
    ) -> None:
        router = SolverRouter(
            registry()
        )

        stale = context(
            "rev-new",
            route_evidence=(
                evidence("rev-old"),
            ),
        )

        plain = context(
            "rev-new"
        )

        stale_result = router.route(
            stale
        )

        self.assertNotIn(
            SAFE_EDIT,
            stale_result.deterministic_solvers,
        )

        self.assertEqual(
            router.route_focus_key(stale),
            router.route_focus_key(plain),
        )

    def test_valid_evidence_changes_route_focus(
        self,
    ) -> None:
        router = SolverRouter(
            registry()
        )

        revision = "rev-focus"

        plain = context(
            revision
        )

        valid = context(
            revision,
            route_evidence=(
                evidence(revision),
            ),
        )

        self.assertNotEqual(
            router.route_focus_key(plain),
            router.route_focus_key(valid),
        )

    def test_source_revision_without_evidence_does_not_churn_focus(
        self,
    ) -> None:
        router = SolverRouter(
            registry()
        )

        first = context("rev-a")
        second = context("rev-b")

        self.assertEqual(
            router.route_focus_key(first),
            router.route_focus_key(second),
        )

        cache = LaserFocusCache(
            router
        )

        first_binding = cache.bind(
            first
        )

        second_binding = cache.bind(
            second
        )

        self.assertEqual(
            first_binding.handle_id,
            second_binding.handle_id,
        )

        self.assertNotEqual(
            first_binding.binding_sha256,
            second_binding.binding_sha256,
        )

    def test_unknown_capability_evidence_is_ignored(
        self,
    ) -> None:
        router = SolverRouter(
            registry()
        )

        revision = "rev-unknown"

        supplied = context(
            revision,
            route_evidence=(
                evidence(
                    revision,
                    capability_id=(
                        "repair.source.does_not_exist"
                    ),
                ),
            ),
        )

        plain = context(
            revision
        )

        self.assertEqual(
            router.route_focus_key(supplied),
            router.route_focus_key(plain),
        )

    def test_non_safe_applicability_is_not_routable(
        self,
    ) -> None:
        router = SolverRouter(
            registry()
        )

        revision = "rev-unsafe"

        result = router.route(
            context(
                revision,
                route_evidence=(
                    evidence(
                        revision,
                        applicability="unsafe",
                    ),
                ),
            )
        )

        self.assertNotIn(
            SAFE_EDIT,
            result.deterministic_solvers,
        )

    def test_invalid_evidence_sha_is_rejected(
        self,
    ) -> None:
        router = SolverRouter(
            registry()
        )

        supplied = context(
            "rev-invalid",
            route_evidence=(
                evidence(
                    "rev-invalid",
                    evidence_sha256="bad",
                ),
            ),
        )

        with self.assertRaisesRegex(
            SolverRouterError,
            "route evidence sha256 invalid",
        ):
            router.route(
                supplied
            )


if __name__ == "__main__":
    unittest.main()
