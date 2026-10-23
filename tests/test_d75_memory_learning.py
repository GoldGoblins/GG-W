from __future__ import annotations

import copy
import importlib
import inspect
from pathlib import Path
import sys
import tempfile


PROJECT = Path(
    __file__
).resolve().parents[1]

if str(PROJECT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT),
    )

cognitive = importlib.import_module(
    "backend.autonomy_cognitive_adapter"
)
learning = importlib.import_module(
    "backend.learning_memory_promotion"
)


SOURCE_SHA = "a" * 64
REGRESSION_SHA = "b" * 64
CONFLICT_SHA = "c" * 64
APPROVAL_PROOF = "d" * 64
SUPERSEDE_PROOF = "e" * 64


def expect(
    condition: bool,
    message: str,
) -> None:
    if not condition:
        raise AssertionError(
            message
        )


def closure(
    *,
    source_sha256: str = SOURCE_SHA,
) -> dict[str, object]:
    return {
        "schema":
            "gg.semantic-closure-result.v1",
        "goal_id":
            "task-learning",
        "object_id":
            "object-learning",
        "source_sha256":
            source_sha256,
        "status":
            "PASS",
        "semantic_done":
            True,
        "visible_acceptance_required":
            False,
        "proof_sha256":
            "f" * 64,
    }


def handoff(
    value: dict[str, object],
    *,
    input_class: str = "VERIFIED_SUCCESS",
    candidate_eligible: bool = True,
) -> dict[str, object]:
    return {
        "schema":
            "gg.semantic-learning-handoff.v1",
        "semantic_closure_sha256":
            learning.digest_json(
                value
            ),
        "visible_acceptance_result_sha256":
            "",
        "input_class":
            input_class,
        "candidate_eligible":
            candidate_eligible,
        "generalizable_claim":
            False,
        "canonical_policy_change":
            False,
        "promotion_authority":
            "NONE",
        "reason":
            "synthetic verified outcome",
    }


def episode(
    task_id: str,
    *,
    state_base: str,
) -> dict[str, object]:
    value = closure()

    return (
        learning
        .build_episodic_experience(
            task_id=task_id,
            origin_id=(
                "origin-learning"
            ),
            goal=(
                "Verify controlled learning."
            ),
            state_base_revision=(
                state_base
            ),
            source_sha256=(
                SOURCE_SHA
            ),
            semantic_closure=value,
            learning_handoff=(
                handoff(
                    value
                )
            ),
        )
    )


def approval(
    candidate: dict[str, object],
    review: dict[str, object],
    *,
    proof: str,
    memory_class: str = "PROCEDURAL_MEMORY",
) -> dict[str, object]:
    return {
        "schema":
            learning.APPROVAL_SCHEMA,
        "candidate_sha256":
            learning.digest_json(
                candidate
            ),
        "review_sha256":
            learning.digest_json(
                review
            ),
        "memory_class":
            memory_class,
        "approved":
            True,
        "actor_class":
            "HUMAN_EXPLICIT",
        "current_source_sha256":
            SOURCE_SHA,
        "current_state_base_revision":
            "state-current",
        "proof_sha256":
            proof,
        "task_id":
            "task-learning-promotion",
        "origin_id":
            "origin-learning",
        "action_authority":
            "NONE",
        "network_authority":
            "NONE",
        "canonical_policy_change":
            False,
    }


def main() -> None:
    one = episode(
        "task-one",
        state_base="state-one",
    )

    expect(
        one[
            "memory_class"
        ]
        == "EPISODIC_MEMORY",
        "episodic memory class drift",
    )

    expect(
        one[
            "candidate_eligible"
        ]
        is True,
        "verified outcome not eligible",
    )

    expect(
        one[
            "action_authority"
        ]
        == "NONE",
        "episode gained action authority",
    )

    unknown_closure = closure()

    unknown = (
        learning
        .build_episodic_experience(
            task_id="task-unknown",
            origin_id="origin-learning",
            goal="Unknown outcome.",
            state_base_revision=(
                "state-unknown"
            ),
            source_sha256=(
                SOURCE_SHA
            ),
            semantic_closure=(
                unknown_closure
            ),
            learning_handoff=(
                handoff(
                    unknown_closure,
                    input_class="UNKNOWN",
                    candidate_eligible=False,
                )
            ),
        )
    )

    expect(
        unknown[
            "candidate_eligible"
        ]
        is False,
        "unknown outcome became eligible",
    )

    episodic_candidate = (
        learning
        .build_learning_candidate(
            [one],
            claim_key=(
                "learning.controlled-promotion"
            ),
            statement=(
                "Controlled promotion preserves "
                "authority boundaries."
            ),
            scope=(
                "GG_AI_DESKTOP"
            ),
            limitation=(
                "Requires repeated verified "
                "experience and regression evidence."
            ),
        )
    )

    expect(
        episodic_candidate[
            "status"
        ]
        == "EPISODIC_CANDIDATE",
        "single outcome promoted too far",
    )

    single_review = (
        learning
        .review_learning_candidate(
            episodic_candidate,
            regression_evidence_sha256s=[
                REGRESSION_SHA
            ],
        )
    )

    expect(
        single_review[
            "status"
        ]
        == "NEEDS_MORE_EXPERIENCE",
        "T078 single outcome became procedure",
    )

    two = episode(
        "task-two",
        state_base="state-two",
    )

    candidate = (
        learning
        .build_learning_candidate(
            [
                one,
                two,
            ],
            claim_key=(
                "learning.controlled-promotion"
            ),
            statement=(
                "Controlled promotion preserves "
                "authority boundaries."
            ),
            scope=(
                "GG_AI_DESKTOP"
            ),
            limitation=(
                "Content/state bound and subject "
                "to future contradiction."
            ),
        )
    )

    expect(
        candidate[
            "status"
        ]
        == "PROCEDURAL_CANDIDATE",
        "multi-task candidate not procedural",
    )

    expect(
        candidate[
            "canonical_policy_change"
        ]
        is False,
        "T078 learning became policy",
    )

    needs_evidence = (
        learning
        .review_learning_candidate(
            candidate,
            regression_evidence_sha256s=[],
        )
    )

    expect(
        needs_evidence[
            "status"
        ]
        == "EVIDENCE_REQUIRED",
        "review skipped regression evidence",
    )

    conflict = (
        learning
        .review_learning_candidate(
            candidate,
            regression_evidence_sha256s=[
                REGRESSION_SHA
            ],
            conflicting_evidence_sha256s=[
                CONFLICT_SHA
            ],
        )
    )

    expect(
        conflict[
            "status"
        ]
        == "BLOCKED_CONFLICT",
        "conflicting evidence did not block",
    )

    review = (
        learning
        .review_learning_candidate(
            candidate,
            regression_evidence_sha256s=[
                REGRESSION_SHA
            ],
        )
    )

    expect(
        review[
            "status"
        ]
        == "PROMOTABLE_MEMORY",
        "verified candidate not promotable",
    )

    expect(
        review[
            "promotion_authority"
        ]
        == "NONE",
        "review self-authorized promotion",
    )

    promoted = (
        learning
        .promote_reviewed_candidate(
            candidate,
            review,
            approval(
                candidate,
                review,
                proof=(
                    APPROVAL_PROOF
                ),
            ),
            memory_class=(
                "PROCEDURAL_MEMORY"
            ),
        )
    )

    expect(
        promoted[
            "promotion_authority"
        ]
        == "HUMAN_EXPLICIT_BOUND",
        "promotion approval not bound",
    )

    expect(
        promoted[
            "action_authority"
        ]
        == "NONE",
        "T079 learning raised action authority",
    )

    expect(
        promoted[
            "canonical_policy_change"
        ]
        is False,
        "T078 promoted memory became policy",
    )

    current = (
        learning
        .assess_memory_freshness(
            promoted,
            current_source_sha256=(
                SOURCE_SHA
            ),
            current_state_base_revision=(
                "state-current"
            ),
        )
    )

    expect(
        current[
            "status"
        ]
        == "CURRENT",
        "current memory marked stale",
    )

    stale = (
        learning
        .assess_memory_freshness(
            promoted,
            current_source_sha256=(
                "9" * 64
            ),
            current_state_base_revision=(
                "state-current"
            ),
        )
    )

    expect(
        stale[
            "status"
        ]
        == "REFRESH_REQUIRED",
        "T077 stale source not refreshed",
    )

    expect(
        "SOURCE_SHA256_CHANGE"
        in stale[
            "stale_reasons"
        ],
        "T077 stale reason missing",
    )

    stale_state = (
        learning
        .assess_memory_freshness(
            promoted,
            current_source_sha256=(
                SOURCE_SHA
            ),
            current_state_base_revision=(
                "state-new"
            ),
        )
    )

    expect(
        "STATE_BASE_REVISION_CHANGE"
        in stale_state[
            "stale_reasons"
        ],
        "state-bound memory did not stale",
    )

    try:
        learning.promote_reviewed_candidate(
            candidate,
            review,
            approval(
                candidate,
                review,
                proof=(
                    APPROVAL_PROOF
                ),
                memory_class=(
                    "CANONICAL_POLICY"
                ),
            ),
            memory_class=(
                "CANONICAL_POLICY"
            ),
        )
    except learning.LearningMemoryError as exc:
        expect(
            "CANONICAL_POLICY_PROMOTION_FORBIDDEN"
            in str(exc),
            "wrong canonical policy rejection",
        )
    else:
        raise AssertionError(
            "T078 canonical policy auto-promotion allowed"
        )

    with tempfile.TemporaryDirectory() as tmp:
        ledger_path = (
            Path(tmp)
            / "epistemic-ledger.jsonl"
        )

        root_record = (
            cognitive.append_claim(
                ledger_path,
                task_id=(
                    "d75-ledger-root-task"
                ),
                origin_id=(
                    "d75-ledger-root-origin"
                ),
                claim_key=(
                    "learning.verified-root"
                ),
                statement=(
                    "Verified deterministic evidence "
                    "anchors promoted memory."
                ),
                epistemic_class=(
                    "VERIFIED"
                ),
                source_kind=(
                    "DETERMINISTIC_TOOL"
                ),
                source_id=(
                    "d75-test-root"
                ),
                source_fingerprint=(
                    SOURCE_SHA
                ),
            )
        )

        ledger_candidate = (
            learning
            .build_ledger_candidate(
                promoted,
                parent_entry_sha256s=[
                    root_record[
                        "entry_sha256"
                    ]
                ],
            )
        )

        expect(
            ledger_candidate[
                "body"
            ][
                "epistemic_class"
            ]
            == "DERIVED",
            "ledger candidate epistemic class drift",
        )

        expect(
            ledger_candidate[
                "body"
            ][
                "source_kind"
            ]
            == "DERIVATION",
            "ledger candidate source kind drift",
        )

        expect(
            ledger_candidate[
                "body"
            ][
                "parent_entry_sha256s"
            ]
            == [
                root_record[
                    "entry_sha256"
                ]
            ],
            "derived promoted memory parent drift",
        )

        cognitive.append_prebuilt_candidate(
            ledger_path,
            ledger_candidate,
        )

        before = (
            cognitive.read_records(
                ledger_path
            )
        )

        expect(
            len(before) == 2,
            "root plus first promoted record missing",
        )

        root_preserved = copy.deepcopy(
            before[0]
        )

        first_preserved = copy.deepcopy(
            before[1]
        )

        promoted_sha = (
            learning.digest_json(
                promoted
            )
        )

        superseding = (
            learning
            .promote_reviewed_candidate(
                candidate,
                review,
                approval(
                    candidate,
                    review,
                    proof=(
                        SUPERSEDE_PROOF
                    ),
                ),
                memory_class=(
                    "PROCEDURAL_MEMORY"
                ),
                supersedes=[
                    promoted_sha
                ],
            )
        )

        expect(
            superseding[
                "supersedes"
            ]
            == [
                promoted_sha
            ],
            "T085 supersession provenance missing",
        )

        second_candidate = (
            learning
            .build_ledger_candidate(
                superseding,
                parent_entry_sha256s=[
                    before[1][
                        "entry_sha256"
                    ]
                ],
            )
        )

        expect(
            second_candidate[
                "body"
            ][
                "parent_entry_sha256s"
            ]
            == [
                before[1][
                    "entry_sha256"
                ]
            ],
            "superseding derivation parent drift",
        )

        cognitive.append_prebuilt_candidate(
            ledger_path,
            second_candidate,
        )

        after = (
            cognitive.read_records(
                ledger_path
            )
        )

        expect(
            len(after) == 3,
            "T085 append-only history lost",
        )

        expect(
            after[0]
            == root_preserved,
            "T085 root provenance rewritten",
        )

        expect(
            after[1]
            == first_preserved,
            "T085 old learning history rewritten",
        )

        expect(
            after[1][
                "entry_sha256"
            ]
            != after[2][
                "entry_sha256"
            ],
            "superseding record not distinct",
        )

        expect(
            after[2][
                "body"
            ][
                "parent_entry_sha256s"
            ]
            == [
                after[1][
                    "entry_sha256"
                ]
            ],
            "T085 supersession ledger provenance drift",
        )

    source = inspect.getsource(
        learning
    )

    for forbidden in (
        "subprocess",
        "socket",
        "requests",
        "urllib",
        "os.system",
        "append_prebuilt_candidate(",
    ):
        expect(
            forbidden not in source,
            "learning layer gained execution surface: "
            + forbidden,
        )

    action_source = (
        PROJECT
        / "backend"
        / "action_done_when.py"
    ).read_text(
        encoding="utf-8",
        errors="strict",
    )

    action_tree = (
        __import__("ast")
        .parse(
            action_source,
            filename=(
                "backend/action_done_when.py"
            ),
        )
    )

    episode_calls = [
        node
        for node in __import__(
            "ast"
        ).walk(
            action_tree
        )
        if (
            isinstance(
                node,
                __import__(
                    "ast"
                ).Call,
            )
            and isinstance(
                node.func,
                __import__(
                    "ast"
                ).Attribute,
            )
            and isinstance(
                node.func.value,
                __import__(
                    "ast"
                ).Name,
            )
            and node.func.value.id
            == "learning_memory"
            and node.func.attr
            == "build_episodic_experience"
        )
    ]

    expect(
        len(episode_calls) == 1,
        "D75 action outcome episode wiring drift",
    )

    expect(
        '"learning_handoff"'
        in action_source,
        "learning handoff return missing",
    )

    expect(
        '"episodic_experience"'
        in action_source,
        "episodic experience return missing",
    )

    print(
        "D75_EPISODIC_EXPERIENCE=PASS"
    )
    print(
        "D75_T077_STALE_MEMORY=PASS"
    )
    print(
        "D75_T078_LEARNING_NOT_POLICY=PASS"
    )
    print(
        "D75_T079_AUTHORITY_UNCHANGED=PASS"
    )
    print(
        "D75_T085_PROVENANCE_SUPERSESSION=PASS"
    )
    print(
        "D75_LEDGER_COMPATIBILITY=PASS"
    )
    print(
        "D75_AUTOMATIC_LEDGER_APPEND=NO"
    )
    print(
        "D75_CANONICAL_POLICY_PROMOTION=FORBIDDEN"
    )
    print(
        "D75_ACTION_AUTHORITY=NONE"
    )
    print(
        "D75_MODEL_INFERENCE=NONE"
    )
    print(
        "D75_TEST=PASS"
    )


if __name__ == "__main__":
    main()
