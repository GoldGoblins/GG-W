from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
REPO = PROJECT.parents[1]
BACKEND = PROJECT / "backend"

if str(BACKEND) not in sys.path:
    sys.path.insert(
        0,
        str(BACKEND),
    )

from capability_registry import CapabilityRegistry  # noqa: E402
from solver_router import (  # noqa: E402
    LaserFocusCache,
    RouteContext,
    SolverRouter,
)


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


def qml_context(
    *,
    query: str = "qml repair",
    source_revision: str = "buffer-1",
) -> RouteContext:
    return RouteContext(
        query=query,
        goal_id="goal-qml-repair",
        object_id="workspace-object-1",
        source_revision=source_revision,
        language="qml",
        diagnostic_class="QML_GATE_DIAGNOSTIC",
    )


class CountingRouter(SolverRouter):
    def __init__(
        self,
        value: CapabilityRegistry,
    ) -> None:
        super().__init__(value)
        self.route_calls = 0

    def route(
        self,
        context: RouteContext,
    ):
        self.route_calls += 1
        return super().route(context)


class SolverRouterTests(unittest.TestCase):
    def test_qml_repair_defers_model_until_after_prechecks(
        self,
    ) -> None:
        router = SolverRouter(
            registry()
        )

        decision = router.route(
            qml_context()
        )

        self.assertEqual(
            decision.route_mode,
            (
                "DETERMINISTIC_PRECHECK_THEN_"
                "MODEL_FALLBACK"
            ),
        )

        self.assertIn(
            "analyze.source.qml",
            decision.deterministic_prechecks,
        )

        self.assertIn(
            "verify.qml.preflight",
            decision.deterministic_prechecks,
        )

        self.assertEqual(
            decision.model_fallbacks[0],
            "repair.qml.local_model",
        )

        self.assertFalse(
            decision.automatic_model_dispatch
        )

        self.assertFalse(
            decision.registered_capability_execution
        )

    def test_qml_analyze_reuses_deterministic_analyzer(
        self,
    ) -> None:
        router = SolverRouter(
            registry()
        )

        decision = router.route(
            qml_context(
                query="qml analyze",
            )
        )

        self.assertEqual(
            decision.route_mode,
            "REUSE_DETERMINISTIC",
        )

        self.assertEqual(
            decision.primary_capability,
            "analyze.source.qml",
        )

        self.assertEqual(
            decision.model_fallbacks,
            (),
        )

    def test_source_revision_does_not_churn_route_focus(
        self,
    ) -> None:
        router = SolverRouter(
            registry()
        )

        first = qml_context(
            source_revision="buffer-a",
        )

        second = qml_context(
            source_revision="buffer-b",
        )

        self.assertEqual(
            router.route_focus_key(first),
            router.route_focus_key(second),
        )

        cache = LaserFocusCache(
            router
        )

        first_binding = cache.bind(first)
        second_binding = cache.bind(second)

        self.assertEqual(
            first_binding.handle_id,
            second_binding.handle_id,
        )

        self.assertNotEqual(
            first_binding.binding_sha256,
            second_binding.binding_sha256,
        )

    def test_direct_laser_lookup_does_not_route_again(
        self,
    ) -> None:
        router = CountingRouter(
            registry()
        )

        cache = LaserFocusCache(
            router
        )

        binding = cache.bind(
            qml_context()
        )

        self.assertEqual(
            router.route_calls,
            1,
        )

        for _ in range(1000):
            handle = cache.lookup(
                binding.handle_id
            )

            self.assertIsNotNone(
                handle
            )

        self.assertEqual(
            router.route_calls,
            1,
        )

    def test_same_focus_new_source_binding_does_not_route_again(
        self,
    ) -> None:
        router = CountingRouter(
            registry()
        )

        cache = LaserFocusCache(
            router
        )

        first = cache.bind(
            qml_context(
                source_revision="rev-1",
            )
        )

        second = cache.bind(
            qml_context(
                source_revision="rev-2",
            )
        )

        self.assertEqual(
            first.handle_id,
            second.handle_id,
        )

        self.assertEqual(
            router.route_calls,
            1,
        )

    def test_cache_is_bounded(
        self,
    ) -> None:
        cache = LaserFocusCache(
            SolverRouter(
                registry()
            ),
            max_entries=2,
        )

        contexts = (
            RouteContext(
                query="qml analyze",
                goal_id="goal-1",
                object_id="obj-1",
                source_revision="r1",
                language="qml",
                diagnostic_class="ANALYZE",
            ),
            RouteContext(
                query="qml verify",
                goal_id="goal-2",
                object_id="obj-2",
                source_revision="r2",
                language="qml",
                diagnostic_class="VERIFY",
            ),
            RouteContext(
                query="qml repair",
                goal_id="goal-3",
                object_id="obj-3",
                source_revision="r3",
                language="qml",
                diagnostic_class="REPAIR",
            ),
        )

        for context in contexts:
            cache.focus(context)

        self.assertEqual(
            cache.size,
            2,
        )


if __name__ == "__main__":
    unittest.main()
