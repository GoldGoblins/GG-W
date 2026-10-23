from __future__ import annotations

from dataclasses import replace
import sys
import unittest
from pathlib import Path


PROJECT = Path(
    __file__
).resolve().parents[1]

BACKEND = PROJECT / "backend"

if str(BACKEND) not in sys.path:
    sys.path.insert(
        0,
        str(BACKEND),
    )

import semantic_closure as Semantic  # noqa: E402


SOURCE_SHA = "1" * 64
MACHINE_EVIDENCE_SHA = "2" * 64
SEMANTIC_CONTRACT_SHA = "3" * 64
SEMANTIC_PROOF_SHA = "4" * 64
VISIBLE_PROOF_SHA = "5" * 64


def request(
    *,
    machine_status: str = "PASS",
    visible_required: bool = True,
) -> Semantic.SemanticClosureRequest:
    return Semantic.SemanticClosureRequest(
        goal_id="goal-context-composer",
        object_id="ws.file.context-composer",
        current_target=(
            "ContextComposer.qml buffer"
        ),
        done_when=(
            "The intended component geometry "
            "is preserved, not merely QML-valid."
        ),
        source_sha256=SOURCE_SHA,
        machine_status=machine_status,
        machine_scope="QML_GATE_PROFILE",
        machine_evidence_sha256=(
            MACHINE_EVIDENCE_SHA
        ),
        semantic_contract_sha256=(
            SEMANTIC_CONTRACT_SHA
        ),
        visible_acceptance_required=(
            visible_required
        ),
    )


def evidence(
    req: Semantic.SemanticClosureRequest,
    *,
    status: str = "PASS",
    verifier_class: str = (
        "DETERMINISTIC_PREDICATE"
    ),
) -> Semantic.SemanticEvidence:
    return Semantic.SemanticEvidence(
        request_sha256=(
            req.request_sha256()
        ),
        source_sha256=(
            req.source_sha256
        ),
        semantic_contract_sha256=(
            req.semantic_contract_sha256
        ),
        status=status,
        verifier_class=(
            verifier_class
        ),
        verifier_id=(
            "semantic.fixture.v1"
        ),
        proof_sha256=(
            SEMANTIC_PROOF_SHA
        ),
        limitation=(
            "Fixture proves only the "
            "declared DONE_WHEN predicate."
        ),
    )


class SemanticClosureTests(
    unittest.TestCase
):
    def test_machine_pass_alone_is_not_semantic_done(
        self,
    ) -> None:
        result = (
            Semantic.evaluate_semantic_closure(
                request()
            )
        )

        self.assertEqual(
            result.status,
            "EVIDENCE_REQUIRED",
        )

        self.assertFalse(
            result.semantic_done
        )

    def test_machine_not_ready_cannot_close_semantically(
        self,
    ) -> None:
        result = (
            Semantic.evaluate_semantic_closure(
                request(
                    machine_status="FAIL"
                )
            )
        )

        self.assertEqual(
            result.status,
            "MACHINE_NOT_READY",
        )

        self.assertFalse(
            result.semantic_done
        )

    def test_trusted_semantic_pass_closes_done_when(
        self,
    ) -> None:
        req = request()

        result = (
            Semantic.evaluate_semantic_closure(
                req,
                evidence(req),
            )
        )

        self.assertEqual(
            result.status,
            "PASS",
        )

        self.assertTrue(
            result.semantic_done
        )

    def test_semantic_source_mismatch_fails_closed(
        self,
    ) -> None:
        req = request()

        stale = replace(
            evidence(req),
            source_sha256="9" * 64,
        )

        with self.assertRaisesRegex(
            Semantic.SemanticClosureError,
            "SEMANTIC_SOURCE_BINDING_MISMATCH",
        ):
            Semantic.evaluate_semantic_closure(
                req,
                stale,
            )

    def test_semantic_contract_mismatch_fails_closed(
        self,
    ) -> None:
        req = request()

        wrong = replace(
            evidence(req),
            semantic_contract_sha256=(
                "8" * 64
            ),
        )

        with self.assertRaisesRegex(
            Semantic.SemanticClosureError,
            "SEMANTIC_CONTRACT_BINDING_MISMATCH",
        ):
            Semantic.evaluate_semantic_closure(
                req,
                wrong,
            )

    def test_ai_judgment_is_not_trusted_closure_evidence_v1(
        self,
    ) -> None:
        req = request()

        ai = evidence(
            req,
            verifier_class=(
                "AI_SEMANTIC_JUDGMENT"
            ),
        )

        with self.assertRaisesRegex(
            Semantic.SemanticClosureError,
            "SEMANTIC_VERIFIER_CLASS_UNTRUSTED",
        ):
            Semantic.evaluate_semantic_closure(
                req,
                ai,
            )

    def test_semantic_pass_does_not_auto_visible_accept(
        self,
    ) -> None:
        req = request()

        closure = (
            Semantic.evaluate_semantic_closure(
                req,
                evidence(req),
            )
        )

        visible = (
            Semantic
            .evaluate_visible_acceptance(
                closure
            )
        )

        self.assertEqual(
            visible.status,
            "PENDING",
        )

        self.assertFalse(
            visible.visible_accepted
        )

    def test_explicit_human_visible_acceptance_is_bound(
        self,
    ) -> None:
        req = request()

        closure = (
            Semantic.evaluate_semantic_closure(
                req,
                evidence(req),
            )
        )

        accepted = (
            Semantic.VisibleAcceptanceEvidence(
                closure_sha256=(
                    closure.closure_sha256()
                ),
                source_sha256=(
                    closure.source_sha256
                ),
                accepted=True,
                actor_class=(
                    "HUMAN_EXPLICIT"
                ),
                proof_sha256=(
                    VISIBLE_PROOF_SHA
                ),
            )
        )

        visible = (
            Semantic
            .evaluate_visible_acceptance(
                closure,
                accepted,
            )
        )

        self.assertEqual(
            visible.status,
            "ACCEPTED",
        )

        self.assertTrue(
            visible.visible_accepted
        )

    def test_visible_acceptance_stale_closure_fails_closed(
        self,
    ) -> None:
        req = request()

        closure = (
            Semantic.evaluate_semantic_closure(
                req,
                evidence(req),
            )
        )

        stale = (
            Semantic.VisibleAcceptanceEvidence(
                closure_sha256="7" * 64,
                source_sha256=(
                    closure.source_sha256
                ),
                accepted=True,
                actor_class=(
                    "HUMAN_EXPLICIT"
                ),
                proof_sha256=(
                    VISIBLE_PROOF_SHA
                ),
            )
        )

        with self.assertRaisesRegex(
            Semantic.SemanticClosureError,
            "VISIBLE_CLOSURE_BINDING_MISMATCH",
        ):
            Semantic.evaluate_visible_acceptance(
                closure,
                stale,
            )

    def test_verified_success_can_only_feed_candidate(
        self,
    ) -> None:
        req = request()

        closure = (
            Semantic.evaluate_semantic_closure(
                req,
                evidence(req),
            )
        )

        accepted = (
            Semantic.VisibleAcceptanceEvidence(
                closure_sha256=(
                    closure.closure_sha256()
                ),
                source_sha256=(
                    closure.source_sha256
                ),
                accepted=True,
                actor_class=(
                    "HUMAN_EXPLICIT"
                ),
                proof_sha256=(
                    VISIBLE_PROOF_SHA
                ),
            )
        )

        visible = (
            Semantic
            .evaluate_visible_acceptance(
                closure,
                accepted,
            )
        )

        handoff = (
            Semantic.build_learning_handoff(
                closure,
                visible,
            )
        )

        self.assertEqual(
            handoff.input_class,
            "VERIFIED_SUCCESS",
        )

        self.assertTrue(
            handoff.candidate_eligible
        )

        self.assertFalse(
            handoff.generalizable_claim
        )

        self.assertFalse(
            handoff.canonical_policy_change
        )

        self.assertEqual(
            handoff.promotion_authority,
            "NONE",
        )

    def test_verified_failure_is_not_success_or_policy(
        self,
    ) -> None:
        req = request(
            visible_required=False
        )

        closure = (
            Semantic.evaluate_semantic_closure(
                req,
                evidence(
                    req,
                    status="FAIL",
                ),
            )
        )

        handoff = (
            Semantic.build_learning_handoff(
                closure
            )
        )

        self.assertEqual(
            handoff.input_class,
            "VERIFIED_FAILURE",
        )

        self.assertTrue(
            handoff.candidate_eligible
        )

        self.assertFalse(
            handoff.generalizable_claim
        )

        self.assertEqual(
            handoff.promotion_authority,
            "NONE",
        )

    def test_semantic_pass_without_required_visible_acceptance_is_unknown_learning(
        self,
    ) -> None:
        req = request()

        closure = (
            Semantic.evaluate_semantic_closure(
                req,
                evidence(req),
            )
        )

        visible = (
            Semantic
            .evaluate_visible_acceptance(
                closure
            )
        )

        handoff = (
            Semantic.build_learning_handoff(
                closure,
                visible,
            )
        )

        self.assertEqual(
            handoff.input_class,
            "UNKNOWN",
        )

        self.assertFalse(
            handoff.candidate_eligible
        )


if __name__ == "__main__":
    unittest.main()
