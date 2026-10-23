from __future__ import annotations

from pathlib import Path

from backend import action_effect_recovery


PROJECT = Path(__file__).resolve().parents[1]
RECOVERY = (
    PROJECT
    / "backend"
    / "action_effect_recovery.py"
)
ADAPTER = (
    PROJECT
    / "backend"
    / "action_execution_safe_tool_adapter.py"
)
MAIN = PROJECT / "main.py"


def expect(
    condition: bool,
    message: str,
) -> None:
    if not condition:
        raise AssertionError(message)


def fixture() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    revision = "a" * 64

    intent: dict[str, object] = {
        "effect_class": (
            "READ_ONLY_TOOL_EXECUTION"
        ),
        "persistent_write": "RUNTIME_ONLY",
        "network": "NONE",
        "sudo": "NO",
        "target_object_id": (
            "workspace-context-composer"
        ),
        "target_source_revision": revision,
    }

    eligibility: dict[str, object] = {
        "action_authority": "NONE",
        "general_action_authority": "NONE",
        "execution_persistent_write_authority": (
            "NONE"
        ),
        "capability_execution": False,
        "k7_l_execution": False,
        "participant_execution": False,
        "network": "NONE",
        "sudo": "NO",
        "model_inference": False,
    }

    observation: dict[str, object] = {
        "schema": (
            "gg.action-effect-observation.v1"
        ),
        "result": "MATCH",
        "reason_code": (
            "EXPECTED_ACTUAL_MATCH"
        ),
        "actual_effect_verified": True,
        "d70_required": False,
        "mismatch_reasons": [],
        "target_object_id": (
            "workspace-context-composer"
        ),
        "expected_target_source_revision": (
            revision
        ),
        "observed_target_source_revision": (
            revision
        ),
    }

    return (
        intent,
        eligibility,
        observation,
    )


def unit_contract() -> None:
    (
        intent,
        eligibility,
        observation,
    ) = fixture()

    matched = (
        action_effect_recovery
        .classify_action_effect_recovery(
            action_intent=dict(intent),
            execution_eligibility=dict(
                eligibility
            ),
            actual_effect_observation=dict(
                observation
            ),
            execution_state=(
                "CONSUMED_PASS"
            ),
        )
    )

    expect(
        matched["schema"]
        == "gg.action-effect-recovery.v1",
        "D70 schema mismatch",
    )
    expect(
        matched["result"]
        == "NO_RECOVERY_REQUIRED",
        "D70 MATCH should require no recovery",
    )
    expect(
        matched["reason_code"]
        == "ACTUAL_EFFECT_VERIFIED",
        "D70 MATCH reason mismatch",
    )
    expect(
        matched["replan_required"]
        is False,
        "D70 MATCH cannot require replan",
    )
    expect(
        matched[
            "authority_reevaluation_required"
        ]
        is False,
        "D70 MATCH cannot require authority reevaluation",
    )
    expect(
        matched["repair_execution"]
        is False,
        "D70 must not execute repair",
    )
    expect(
        matched["automatic_rerun"]
        is False,
        "D70 must not rerun action",
    )
    expect(
        matched["existing_mandate_reusable"]
        is False,
        "consumed mandate cannot become reusable",
    )
    expect(
        matched[
            "new_action_authority_granted"
        ]
        is False,
        "D70 cannot grant authority",
    )

    mismatch = dict(observation)
    mismatch.update(
        {
            "result": "MISMATCH",
            "reason_code": (
                "TARGET_SOURCE_REVISION_MISMATCH"
            ),
            "actual_effect_verified": False,
            "d70_required": True,
            "mismatch_reasons": [
                "TARGET_SOURCE_REVISION_MISMATCH"
            ],
            "observed_target_source_revision": (
                "b" * 64
            ),
        }
    )

    replanned = (
        action_effect_recovery
        .classify_action_effect_recovery(
            action_intent=dict(intent),
            execution_eligibility=dict(
                eligibility
            ),
            actual_effect_observation=mismatch,
            execution_state=(
                "CONSUMED_PASS"
            ),
        )
    )

    expect(
        replanned["result"]
        == "REPLAN_REQUIRED",
        "D70 mismatch must require replan",
    )
    expect(
        replanned["reason_code"]
        == (
            "ACTUAL_EFFECT_MISMATCH_"
            "REQUIRES_REPLAN"
        ),
        "D70 replan reason mismatch",
    )
    expect(
        replanned[
            "observation_reason_code"
        ]
        == "TARGET_SOURCE_REVISION_MISMATCH",
        "D70 must preserve D69 reason",
    )
    expect(
        replanned["mismatch_reasons"]
        == [
            "TARGET_SOURCE_REVISION_MISMATCH"
        ],
        "D70 mismatch provenance lost",
    )
    expect(
        replanned["replan_required"]
        is True,
        "D70 mismatch must mark replan",
    )
    expect(
        replanned[
            "authority_reevaluation_required"
        ]
        is True,
        "D70 mismatch must require authority reevaluation",
    )
    expect(
        replanned["repair_execution"]
        is False,
        "D70 mismatch must not execute repair",
    )
    expect(
        replanned["automatic_rerun"]
        is False,
        "D70 mismatch must not rerun consumed action",
    )
    expect(
        replanned[
            "existing_mandate_reusable"
        ]
        is False,
        "D70 mismatch must not reuse mandate",
    )

    authority_drift = dict(
        eligibility
    )
    authority_drift[
        "action_authority"
    ] = "YELLOW"

    try:
        (
            action_effect_recovery
            .classify_action_effect_recovery(
                action_intent=dict(intent),
                execution_eligibility=(
                    authority_drift
                ),
                actual_effect_observation=dict(
                    observation
                ),
                execution_state=(
                    "CONSUMED_PASS"
                ),
            )
        )
    except RuntimeError as exc:
        expect(
            str(exc)
            == "D70_EXECUTION_AUTHORITY_UNSUPPORTED",
            "D70 authority drift reason mismatch",
        )
    else:
        raise AssertionError(
            "D70 accepted expanded authority"
        )

    print(
        "D70_MATCH_NO_RECOVERY_REQUIRED=PASS"
    )
    print(
        "D70_MISMATCH_REPLAN_REQUIRED=PASS"
    )
    print(
        "D70_AUTHORITY_REEVALUATION_FLAG=PASS"
    )
    print(
        "D70_REPAIR_EXECUTION=NONE"
    )
    print(
        "D70_AUTOMATIC_RERUN=NO"
    )


def static_contract() -> None:
    recovery_source = RECOVERY.read_text(
        encoding="utf-8",
        errors="strict",
    )
    adapter_source = ADAPTER.read_text(
        encoding="utf-8",
        errors="strict",
    )
    main_source = MAIN.read_text(
        encoding="utf-8",
        errors="strict",
    )

    for forbidden in (
        "subprocess",
        "repair_to_intended",
        "accept_repair_candidate",
        "accept_repair_response",
        "repair_model_runner",
        "safe_tool_runner",
        "QProcess",
    ):
        expect(
            forbidden not in recovery_source,
            "D70 classifier gained forbidden executor: "
            + forbidden,
        )

    for required in (
        "classify_action_effect_recovery",
        "REPLAN_REQUIRED",
        "NO_RECOVERY_REQUIRED",
        '"repair_execution": False',
        '"automatic_rerun": False',
        '"existing_mandate_reusable": False',
        '"new_action_authority_granted": False',
        '"authority_reevaluation_required"',
    ):
        expect(
            required in recovery_source,
            "D70 classifier marker missing: "
            + required,
        )

    for required in (
        "from backend import action_effect_recovery",
        ".classify_action_effect_recovery(",
        'pending["action_effect_recovery"]',
        '"D70 ROUTING: "',
    ):
        expect(
            required in adapter_source,
            "D70 adapter wiring missing: "
            + required,
        )

    for forbidden in (
        "repair_to_intended",
        "accept_repair_candidate",
        "accept_repair_response",
    ):
        expect(
            forbidden not in adapter_source,
            "D70 adapter directly invokes repair: "
            + forbidden,
        )

    for required in (
        '"action_effect_recovery": None',
        '"ACTION_EFFECT_RECOVERY"',
        '"backend.action_effect_recovery"',
        '"action_effect_recovery.'
        'classify_action_effect_recovery"',
    ):
        expect(
            required in main_source,
            "D70 main/graph marker missing: "
            + required,
        )

    print(
        "D70_CLASSIFIER_STATIC_BOUNDARY=PASS"
    )
    print(
        "D70_ADAPTER_WIRING=PASS"
    )
    print(
        "D70_MACHINE_GRAPH_WIRING=PASS"
    )


def main() -> int:
    unit_contract()
    static_contract()

    print(
        "D70_ACTION_EFFECT_RECOVERY=PASS"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
